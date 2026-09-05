"""Terminal runner backed by the single DSH Agent Runtime."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any

import structlog
from starlette.responses import Response, StreamingResponse

from app.agents.dsh import client, registry
from app.agents.dsh.registry import DshRunContext
from app.agents.graph import run_registry
from app.agents.graph.context import bind_runtime
from app.agents.graph.nodes import (
    dsh_tool_specs,
    extract_memory,
    judge,
    load_config,
    load_memory,
    prepare_dsh_turn,
    save_memory,
    write_run_log,
)
from app.agents.runtime_support import (
    admin_context,
    finalize_bg_error,
    general_context,
    general_initial_state,
    initial_state,
    persist_run_events,
    sse_replay_and_tail,
    user_message_metadata,
)
from app.auth.user_auth import CurrentUser
from app.config import settings
from app.database import async_session_factory
from app.models.agent_run import AgentRun
from app.models.task import TaskMessage
from app.services.agent_admission import agent_admission
from app.services.message_verification import contains_unverified_tool_success_claim

logger = structlog.get_logger()
_SSE_HEADERS = {
    "cache-control": "no-cache", "connection": "keep-alive", "x-accel-buffering": "no",
}
# Tools whose successful ``tool_result`` counts as "a file was produced" for the runtime's
# completion policy.  The contract is name-level: the runtime cannot see per-action semantics
# (e.g. ``spreadsheet_tool action=inspect``), so this list only names tools that can write files.
_FILE_OUTPUT_TOOL_NAMES = (
    "spreadsheet_tool", "document_tool", "presentation_tool", "pdf_tool", "text_tool",
    "image_tool", "archive_tool",
    "workspace_create_file", "workspace_write_file", "workspace_update_file",
    "workspace_rename_file", "workspace_move_file", "workspace_copy_file",
    "workspace_restore_version", "image_generation_tool", "run_skill_script",
)
# Registry kinds whose dynamically named tools materialize Runner outputs as workspace files.
_FILE_OUTPUT_REGISTRY_KINDS = {"code", "run_skill_script"}
# A file-delivery request needs BOTH an explicit production verb AND an artifact noun
# (audit M4): "处理一下" + attachment or "看看这个表里合计多少" must not arm the policy.
_FILE_PRODUCTION_VERBS = (
    "生成", "创建", "制作", "导出", "转换", "转成", "转为", "保存", "另存", "输出", "做一份", "做成",
    "写一份", "整理成", "汇总成", "编辑", "修改", "新建", "产出", "交付",
    "generate", "create", "make", "produce", "export", "convert", "save", "write", "build", "deliver",
)
_FILE_ARTIFACT_NOUNS = (
    "文件", "表格", "excel", "xlsx", "xls", "csv", "word", "docx", "文档", "ppt", "pptx", "幻灯片",
    "演示文稿", "pdf", "报告", "报表", "压缩包", "zip", "附件", "产物", "交付物",
    "spreadsheet", "sheet", "document", "report", "slide", "deck", "presentation", "archive",
    "deliverable", "file",
)
# Runtime-side continuation budget (``settings.agent_completion_max_nudges`` overrides if defined).
_COMPLETION_MAX_NUDGES = 1
_COMPLETION_NUDGE_TEXT = (
    "[系统续执行要求] 上一次只完成了技能加载或说明读取，尚未产生用户要求的文件。"
    "请重新调用必要的 Skill/文件工具并实际生成产物；只有真实 tool_result 返回输出文件后才能结束。"
)
_POLICY_TITLES = {
    "continuation": "续执行要求", "repeat_failure_block": "重复失败拦截", "tool_timeout": "工具超时",
    "approval_requested": "审批请求", "approval_decided": "审批结果",
}
# Optional ``policy`` event fields copied into the step / trace record when present.
_POLICY_DETAIL_KEYS = ("tool", "detail", "nudge", "approval_id", "outcome", "decided_by")


class DshRunError(RuntimeError):
    """Structured failure emitted by the DSH runtime stream."""

    def __init__(self, message: str, *, code: str | None = None):
        super().__init__(message)
        self.code = code


def _public_failure_message(exc: Exception) -> str:
    if isinstance(exc, DshRunError) and exc.code == "MAX_STEPS_EXCEEDED":
        return "达到最大步数，未产生最终回答。"
    if isinstance(exc, DshRunError) and exc.code == "CANCELLED":
        # The runtime now closes a cancelled run with error(code=CANCELLED) instead of done.
        return "本次运行已停止。"
    if isinstance(exc, DshRunError):
        message = str(exc)
        if "尚未完成全部能力验证" in message:
            return "当前模型尚未完成全部能力验证，请联系管理员完成该模型声明的全部能力测试。"
        if "尚未启用已验证模型网关" in message:
            return "当前组织尚未启用已验证模型网关，请联系管理员检查模型配置。"
    return "智能体暂时无法完成本次请求，请稍后重试。"


def _merge(state: dict, patch: dict | None) -> None:
    if patch:
        state.update(patch)


def _tool_specs(tools: list[dict], registry: dict[str, dict] | None = None) -> list[dict]:
    """DSH ToolSpecs (name/description/input_schema + runtime metadata) for the RunRequest."""
    return dsh_tool_specs(tools, registry or {})


def _requests_file_delivery(request: str) -> bool:
    """Return whether the user explicitly asked for a file / document / table deliverable."""
    text = (request or "").lower()
    return bool(text) and any(verb in text for verb in _FILE_PRODUCTION_VERBS) and any(
        noun in text for noun in _FILE_ARTIFACT_NOUNS
    )


def _file_output_tools(state: dict) -> list[str]:
    names = list(_FILE_OUTPUT_TOOL_NAMES)
    for name, entry in (state.get("_dsh_tool_registry") or {}).items():
        if isinstance(entry, dict) and entry.get("kind") in _FILE_OUTPUT_REGISTRY_KINDS and name not in names:
            names.append(name)
    return names


def _completion_policy(state: dict) -> dict[str, Any]:
    """Build the runtime-owned ``completion_policy`` for this run.

    The DSH runtime enforces it (nudging the model at most ``max_nudges`` times when no
    file-producing tool succeeded); Python only reports the resulting ``policy`` events.
    """
    require_file = (
        (state.get("exec_mode") or "craft") == "craft"
        and _requests_file_delivery(str(state.get("request") or ""))
    )
    return {
        "require_file_output": require_file,
        "file_output_tools": _file_output_tools(state),
        "max_nudges": int(getattr(settings, "agent_completion_max_nudges", _COMPLETION_MAX_NUDGES)),
        "nudge_text": _COMPLETION_NUDGE_TEXT,
    }


def _history(state: dict) -> list[dict[str, str]]:
    rows = [
        {"role": item.get("role"), "content": str(item.get("content") or "")}
        for item in state.get("messages") or []
        if item.get("role") in {"user", "assistant"} and isinstance(item.get("content"), str)
    ]
    request = str(state.get("request") or "")
    while rows and rows[-1]["role"] == "user" and rows[-1]["content"] == request:
        rows.pop()
    return rows


def _image_inputs(messages: list[dict]) -> list[dict[str, str]]:
    for message in reversed(messages):
        if message.get("role") != "user" or not isinstance(message.get("content"), list):
            continue
        result: list[dict[str, str]] = []
        for part in message["content"]:
            if not isinstance(part, dict) or part.get("type") != "image_url":
                continue
            image = part.get("image_url") if isinstance(part.get("image_url"), dict) else {}
            if image.get("url"):
                result.append({"data_url": str(image["url"]), "detail": str(image.get("detail") or "auto")})
        return result
    return []


def _publish(handle: run_registry.RunHandle | None, staged: list[dict], event: dict) -> None:
    staged.append(event)
    if handle is not None:
        run_registry.publish(handle, json.dumps(event, ensure_ascii=False))


def _trace_for_tool(state: dict, name: str, call_id: str, arguments: str, result: str, ok: bool) -> None:
    entry = (state.get("_dsh_tool_registry") or {}).get(name) or {}
    kind = entry.get("kind")
    if name.endswith("_tool") or name.startswith("workspace_"):
        category, title = "file", "文件解析与引用"
    elif kind in {"code", "run_skill_script"}:
        category, title = "skill", "Runner脚本执行"
    elif kind in {"load_skill", "read_skill_resource", "prompt"}:
        category, title = "skill", "Skill自动匹配"
    elif kind == "rag_search":
        category, title = "rag", "知识库按需检索"
    elif kind == "memory":
        category, title = "memory", "长期记忆"
    else:
        category, title = "skill", name
    state.setdefault("traces", []).append({
        "category": category, "title": title, "id": call_id, "name": name,
        "arguments": arguments, "result": result[:4000], "ok": ok,
    })


def _apply_policy_event(
    state: dict, event: dict, text: str, handle: run_registry.RunHandle | None, staged: list[dict],
) -> str:
    """Record a runtime ``policy`` decision and return the text still standing on the UI.

    ``continuation`` means the runtime nudged the model to keep working, so the half answer
    streamed so far is retracted (the UI drops it) and the text buffer restarts. The other
    actions (``repeat_failure_block`` / ``tool_timeout`` / ``approval_requested`` /
    ``approval_decided``) are informational: steps + trace only.
    """
    action = str(event.get("action") or "")
    detail = {key: event[key] for key in _POLICY_DETAIL_KEYS if event.get(key) is not None}
    state.setdefault("steps", []).append({"step": "policy", "action": action, **detail})
    trace = {"category": "policy", "title": _POLICY_TITLES.get(action, action), "action": action, **detail}
    state.setdefault("traces", []).append(trace)
    _publish(handle, staged, {"type": "trace", **trace})
    if action == "continuation":
        if text:
            _publish(handle, staged, {"type": "text_retract", "chars": len(text)})
        return ""
    return text


async def _prepare(
    state: dict, deps: dict, writer: Any, *,
    handle: run_registry.RunHandle | None = None, staged: list[dict] | None = None,
) -> tuple[dict, str]:
    with bind_runtime(deps, writer):
        _merge(state, await load_config(state))
        _merge(state, await load_memory(state))
        prepared = await prepare_dsh_turn(state)
    state["traces"] = prepared["traces"]
    state["_dsh_tool_registry"] = prepared["registry"]
    # ``handle`` / ``staged`` let bridge callbacks (user approvals) publish onto this run's SSE
    # channel and into the persisted event log exactly like the runner's own events.
    context = DshRunContext(
        state=state, db=deps["db"], deps=deps, tool_registry=prepared["registry"],
        image_inputs=_image_inputs(prepared.get("messages") or []),
        provider_override=prepared["provider_override"], model_override=prepared["model_override"],
        handle=handle, staged=staged,
    )
    return prepared, registry.register(context)


async def _consume_dsh(
    state: dict, prepared: dict, run_token: str, handle: run_registry.RunHandle | None,
    staged: list[dict],
) -> None:
    request = {
        "run_id": str(state["run_id"]),
        "user_id": str(state.get("user_id") or "platform-admin"),
        "task_id": str(state.get("task_id") or f"agent:{state.get('agent_id', '')}"),
        "run_token": run_token, "messages": _history(state), "message": state.get("request", ""),
        "system_prompt": prepared["system_prompt"], "model": {
            "alias": state.get("model_alias") or "default", "max_tokens": state.get("max_tokens"),
            "temperature": state.get("temperature"),
        },
        "memory_context": prepared.get("memory_context") or None,
        "exec_mode": state.get("exec_mode") or "craft",
        "tools": _tool_specs(
            prepared["tools"], prepared.get("registry") or state.get("_dsh_tool_registry") or {},
        ),
        "max_steps": settings.agent_max_steps,
        # Continuation nudges and repeat-failure blocking live in the DSH pipeline now;
        # Python never re-runs the request under a "-continuation" id.
        "completion_policy": _completion_policy(state),
    }
    text = ""
    successful_tools = 0
    failed_tools: list[tuple[str, str]] = []
    tool_arguments: dict[str, str] = {}
    usage = {"input_tokens": 0, "output_tokens": 0}
    async for event in client.stream_run(request):
        kind = event.get("type")
        if kind == "text_delta":
            delta = str(event.get("delta") or "")
            text += delta
            _publish(handle, staged, {"type": "text", "delta": delta})
        elif kind in {"phase", "tool_call"}:
            _publish(handle, staged, event)
            if kind == "tool_call":
                call_id = str(event.get("id") or "")
                tool_arguments[call_id] = str(event.get("arguments") or "")
                state.setdefault("steps", []).append({"step": "llm", "tool_calls": [event.get("name")]})
        elif kind == "tool_result":
            _publish(handle, staged, event)
            ok = bool(event.get("ok"))
            name = str(event.get("name") or "tool")
            successful_tools += int(ok)
            call_id = str(event.get("id") or "")
            if not ok:
                failed_tools.append((name, str(event.get("content") or "工具未返回错误详情")))
            state.setdefault("steps", []).append({"step": "tool", "name": name, "ok": ok})
            _trace_for_tool(
                state, name, call_id, tool_arguments.get(call_id, ""),
                str(event.get("content") or ""), ok,
            )
        elif kind == "policy":
            text = _apply_policy_event(state, event, text, handle, staged)
        elif kind == "usage":
            usage["input_tokens"] += int(event.get("input_tokens") or 0)
            usage["output_tokens"] += int(event.get("output_tokens") or 0)
        elif kind == "error":
            raise DshRunError(
                str(event.get("message") or "DSH runtime failed"),
                code=str(event.get("code") or "") or None,
            )
        elif kind == "done":
            text = str(event.get("text") or text)

    if successful_tools == 0 and contains_unverified_tool_success_claim(text):
        if text:
            _publish(handle, staged, {"type": "text_retract", "chars": len(text)})
        text = "本轮未产生真实工具调用，因此无法确认任务已执行。请重试或检查当前模型的工具调用能力。"
        _publish(handle, staged, {"type": "text", "delta": text})
        state.setdefault("steps", []).append({"step": "tool_claim_rejected"})
    if not text:
        if failed_tools:
            tool_name, detail = failed_tools[-1]
            state["error"] = f"Tool '{tool_name}' failed: {detail[:1000]}"
            text = f"工具执行失败（{tool_name}）：{detail[:500]}"
        else:
            state["error"] = "DSH runtime completed without a final response"
            text = "模型未返回最终回答，请重试。"
        _publish(handle, staged, {"type": "text", "delta": text})
    state["assistant_final"] = text
    state["usage"] = usage
    state.setdefault("messages", []).append({"role": "assistant", "content": state["assistant_final"]})
    state.setdefault("steps", []).append({"step": "llm_final"})
    _publish(handle, staged, {"type": "done", "usage": usage})


async def _set_run_status(db: Any, run_id: int, status: str) -> None:
    run = await db.get(AgentRun, run_id)
    if run is not None:
        run.status = status
        await db.commit()


async def _admitted_run(
    state: dict, deps: dict, prepared: dict, run_token: str,
    handle: run_registry.RunHandle | None, staged: list[dict], user_id: str,
) -> None:
    """Acquire a shared Redis permit before entering the DSH process."""
    run_id = int(state["run_id"])
    await _set_run_status(deps["db"], run_id, "queued")

    async def status(value: str, position: int | None) -> None:
        event: dict[str, Any] = {"type": "run_status", "status": value}
        if position is not None:
            event["position"] = position
        _publish(handle, staged, event)
        if value == "running":
            await _set_run_status(deps["db"], run_id, "running")

    async with agent_admission.permit(str(run_id), user_id, status):
        await _consume_dsh(state, prepared, run_token, handle, staged)


async def _finish(state: dict, deps: dict) -> None:
    with bind_runtime(deps, lambda _payload: None):
        await save_memory(state)
        _merge(state, await extract_memory(state))
        _merge(state, await judge(state))
        await write_run_log(state)
        await deps["db"].commit()


def _publish_failure_reply(
    handle: run_registry.RunHandle | None, staged: list[dict], state: dict, exc: Exception,
) -> None:
    """流式失败时把「公开错误回复」推到 SSE：撤回已流出的半截文本，再推错误文案 + done。

    推的文案与 ``_finish_failed_run`` 落库的 assistant 消息一致，保证刷新前后看到的是同一句话。
    """
    streamed = 0
    for event in staged:
        if event.get("type") == "text":
            streamed += len(str(event.get("delta") or ""))
        elif event.get("type") == "text_retract":
            streamed -= int(event.get("chars") or 0)
    if streamed > 0:
        _publish(handle, staged, {"type": "text_retract", "chars": streamed})
    _publish(handle, staged, {"type": "text", "delta": _public_failure_message(exc)})
    _publish(handle, staged, {"type": "done", "usage": state.get("usage") or {}})


async def _finish_failed_run(state: dict, deps: dict, exc: Exception) -> None:
    """Preserve the public graceful-error contract when the coordinator is unavailable."""
    message = f"DSH runtime failed: {exc}"
    state["error"] = message
    state["assistant_final"] = _public_failure_message(exc)
    state.setdefault("messages", []).append(
        {"role": "assistant", "content": state["assistant_final"]},
    )
    state.setdefault("steps", []).append({"step": "runtime_error", "error": message})
    await _finish(state, deps)


async def _run_playground(
    state: dict, deps: dict, *, handle: run_registry.RunHandle | None = None,
) -> dict:
    start = time.monotonic()
    staged: list[dict] = []
    run_token = ""
    try:
        prepared, run_token = await _prepare(
            state, deps, lambda raw: staged.append(json.loads(raw)), handle=handle, staged=staged,
        )
        try:
            await _admitted_run(
                state, deps, prepared, run_token, handle, staged,
                str(state.get("user_id") or "platform-admin"),
            )
            await _finish(state, deps)
        except Exception as exc:  # noqa: BLE001
            logger.warning("dsh_playground_failed", error=str(exc), exc_info=True)
            await _finish_failed_run(state, deps, exc)
    finally:
        if run_token:
            registry.revoke(run_token)
    result = {
        "session_id": state["session_id"], "assistant": state.get("assistant_final", ""),
        "steps": state.get("steps", []), "usage": state.get("usage", {}),
        "judge": state.get("judge_result"), "error": state.get("error"),
        "run_id": state.get("run_id"), "latency_ms": int((time.monotonic() - start) * 1000),
    }
    if handle is not None:
        run_registry.mark_done(
            handle, json.dumps({"type": "final", **result}, ensure_ascii=False),
            error=str(result.get("error") or "") or None,
        )
    return result


async def run_agent(
    *, agent_id: str, org_id: str, message: str, session_id: str | None,
    db: Any, request: Any, admin: Any,
) -> dict:
    """Run the management playground through the same single DSH coordinator."""
    state = initial_state(agent_id, org_id, message, session_id)
    return await _run_playground(state, admin_context(db, request, admin))


async def stream_agent(
    *, agent_id: str, org_id: str, message: str, session_id: str | None,
    db: Any, request: Any, admin: Any,
) -> Response:
    """Stream real DSH deltas/tool events in the management playground."""
    async def body():
        handle = run_registry.RunHandle(task_id=f"playground:{uuid.uuid4()}")
        state = initial_state(agent_id, org_id, message, session_id)

        async def execute() -> None:
            try:
                await _run_playground(state, admin_context(db, request, admin), handle=handle)
            except Exception as exc:  # noqa: BLE001
                error = json.dumps({"type": "error", "message": str(exc)}, ensure_ascii=False)
                run_registry.publish(handle, error)
                run_registry.mark_done(handle, None, error=str(exc))

        task = asyncio.create_task(
            execute(),
            name=f"dsh_playground:{agent_id}",
        )
        try:
            async for payload in sse_replay_and_tail(handle):
                yield payload
        except Exception as exc:  # noqa: BLE001
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)}, ensure_ascii=False)}\n\n"
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    return StreamingResponse(body(), media_type="text/event-stream", headers=_SSE_HEADERS)


async def run_general_agent(
    *, org_id: str, user: CurrentUser, task: Any, message: str, config: dict,
    session_id: str | None, db: Any, request: Any,
    attachment_files: list[dict] | None = None, file_refs_v1: list[dict] | None = None,
    invoked_skills: list[dict] | None = None,
) -> dict:
    start = time.monotonic()
    state = general_initial_state(
        org_id=org_id, user=user, task_id=str(task.id), message=message,
        session_id=session_id, config=config, attachment_files=attachment_files,
        file_refs_v1=file_refs_v1,
        invoked_skills=invoked_skills,
    )
    deps = general_context(db, request, user, task)
    db.add(TaskMessage(
        task_id=task.id, role="user", content=message, metadata_=user_message_metadata(state),
    ))
    await db.commit()
    staged: list[dict] = []
    run_token = ""
    try:
        prepared, run_token = await _prepare(state, deps, lambda raw: staged.append(json.loads(raw)), staged=staged)
        try:
            await _admitted_run(state, deps, prepared, run_token, None, staged, str(user.id))
            await _finish(state, deps)
        except Exception as exc:  # noqa: BLE001
            logger.warning("dsh_terminal_run_failed", error=str(exc), exc_info=True)
            await _finish_failed_run(state, deps, exc)
    finally:
        if run_token:
            registry.revoke(run_token)
    return {
        "session_id": state["session_id"], "assistant": state.get("assistant_final", ""),
        "steps": state.get("steps", []), "usage": state.get("usage", {}),
        "error": state.get("error"), "run_id": state.get("run_id"),
        "latency_ms": int((time.monotonic() - start) * 1000),
    }


async def stream_general_agent(
    *, org_id: str, user: CurrentUser, task: Any, message: str, config: dict,
    session_id: str | None, db: Any, request: Any,
    attachment_files: list[dict] | None = None, file_refs_v1: list[dict] | None = None,
    invoked_skills: list[dict] | None = None,
) -> Response:
    task_id = str(task.id)
    handle = run_registry.get(task_id)
    if handle is None or handle.done:
        handle = run_registry.get_or_register(task_id)
        state = general_initial_state(
            org_id=org_id, user=user, task_id=task_id, message=message,
            session_id=session_id or f"sess-{uuid.uuid4()}", config=config,
            attachment_files=attachment_files, file_refs_v1=file_refs_v1,
            invoked_skills=invoked_skills,
        )
        handle.bg_task = asyncio.create_task(
            _run_bg(handle, state=state, user=user, task=task), name=f"dsh_agent_run:{task_id}",
        )
    return StreamingResponse(
        sse_replay_and_tail(handle), status_code=200, media_type="text/event-stream", headers=_SSE_HEADERS,
    )


async def _run_bg(handle: run_registry.RunHandle, *, state: dict, user: CurrentUser, task: Any) -> None:
    start = time.monotonic()
    staged: list[dict] = []
    run_token = ""
    try:
        async with async_session_factory() as db:
            deps = general_context(db, None, user, task)
            db.add(TaskMessage(
                task_id=task.id, role="user", content=state.get("request", ""),
                metadata_=user_message_metadata(state),
            ))
            await db.commit()

            def writer(raw: str) -> None:
                event = json.loads(raw)
                _publish(handle, staged, event)

            prepared, run_token = await _prepare(state, deps, writer, handle=handle, staged=staged)
            handle.run_id = int(state["run_id"])
            try:
                await _admitted_run(state, deps, prepared, run_token, handle, staged, str(user.id))
                await _finish(state, deps)
            except asyncio.CancelledError:
                # 用户 Stop / 进程关停：不走「失败回复」，交给外层 CancelledError 分支
                # （finalize_bg_error 会以 "cancelled" 收口，前端按「已停止」展示）。
                raise
            except Exception as exc:  # noqa: BLE001
                # 与 run_general_agent 一致：把失败落成一条 assistant TaskMessage + done 事件，
                # 让流式用户看到明确的错误回复，而不是流悄悄结束、刷新后本轮没有任何回复。
                logger.warning(
                    "dsh_general_bg_run_failed", task_id=str(task.id), error=str(exc), exc_info=True,
                )
                _publish_failure_reply(handle, staged, state, exc)
                await _finish_failed_run(state, deps, exc)
            finally:
                # The runtime stream is over (done / failed / user Stop): any approval still waiting
                # is settled as ``cancelled`` *before* ``staged`` is persisted so the decision is on record.
                registry.cancel_approvals(run_token)
            final = json.dumps({
                "type": "final", "session_id": state["session_id"], "run_id": state.get("run_id"),
                "latency_ms": int((time.monotonic() - start) * 1000),
            }, ensure_ascii=False)
            await persist_run_events(state.get("run_id"), str(task.id), staged, final)
            run_registry.mark_done(handle, final, error=str(state.get("error") or "") or None)
    except asyncio.CancelledError:
        if state.get("run_id") is not None:
            await client.cancel_run(str(state["run_id"]))
        await persist_run_events(state.get("run_id"), str(task.id), staged, None)
        await finalize_bg_error(
            handle, task, state.get("run_id"), "cancelled", "cancelled by user/shutdown",
            state["session_id"], start,
        )
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error("dsh_general_bg_error", task_id=str(task.id), error=str(exc), exc_info=True)
        await persist_run_events(state.get("run_id"), str(task.id), staged, None)
        await finalize_bg_error(
            handle, task, state.get("run_id"), str(exc)[:500], str(exc), state["session_id"], start,
        )
    finally:
        if run_token:
            registry.revoke(run_token)
        if handle.done:
            run_registry.drop(str(task.id))
