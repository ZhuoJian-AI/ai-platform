"""Platform-owned coordinator for all Assistant Core runs."""

from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from typing import Any

import structlog
from fastapi import HTTPException
from starlette.responses import Response, StreamingResponse

from app.agents.core import approval_registry
from app.agents.core import native as native_core
from app.agents.core.approval_registry import AssistantRunContext
from app.agents.graph import run_registry
from app.agents.graph.context import bind_runtime
from app.agents.graph.nodes import (
    assistant_tool_specs,
    extract_memory,
    load_config,
    load_memory,
    prepare_assistant_turn,
    save_memory,
    write_run_log,
)
from app.agents.runtime_support import (
    finalize_bg_error,
    general_context,
    general_initial_state,
    persist_run_events,
    sse_replay_and_tail,
    user_message_metadata,
)
from app.auth.user_auth import CurrentUser
from app.config import settings
from app.database import async_session_factory
from app.models.agent_run import AgentRun
from app.models.task import TaskMessage
from app.services import business_assistant_orchestration
from app.services.agent_admission import agent_admission
from app.services.assistant_tool_catalog import partition_tool_specs
from app.services.file_capability_registry import FILE_CREATE_TOOL_NAMES, FILE_TOOL_OPERATIONS
from app.services.message_verification import contains_unverified_tool_success_claim

logger = structlog.get_logger()
_SSE_HEADERS = {
    "cache-control": "no-cache",
    "connection": "keep-alive",
    "x-accel-buffering": "no",
}
# Tools whose successful ``tool_result`` counts as "a file was produced" for the runtime's
# completion policy.  The contract is name-level: the runtime cannot see per-action semantics
# (e.g. ``spreadsheet_tool action=inspect``), so this list only names tools that can write files.
_FILE_OUTPUT_TOOL_NAMES = tuple(
    sorted(
        FILE_CREATE_TOOL_NAMES
        | {
            # Hidden compatibility aliases remain completion-capable for already persisted runs.
            "spreadsheet_tool",
            "document_tool",
            "presentation_tool",
            "pdf_tool",
            "text_tool",
            "image_tool",
            "archive_tool",
            "workspace_create_file",
            "workspace_write_file",
            "workspace_update_file",
            "workspace_rename_file",
            "workspace_move_file",
            "workspace_copy_file",
            "workspace_restore_version",
            "image_generation_tool",
            "speech_synthesize",
        }
    )
)
# Registry kinds whose dynamically named tools materialize Runner outputs as workspace files.
_FILE_OUTPUT_REGISTRY_KINDS = {"enterprise_export_file"}
# A file-delivery request needs BOTH an explicit production verb AND an artifact noun
# (audit M4): "处理一下" + attachment or "看看这个表里合计多少" must not arm the policy.
_FILE_PRODUCTION_VERBS = (
    "生成",
    "创建",
    "制作",
    "导出",
    "转换",
    "转成",
    "转为",
    "保存",
    "另存",
    "输出",
    "做一份",
    "做成",
    "写一份",
    "整理成",
    "汇总成",
    "编辑",
    "修改",
    "新建",
    "产出",
    "交付",
    "generate",
    "create",
    "make",
    "produce",
    "export",
    "convert",
    "save",
    "write",
    "build",
    "deliver",
)
_FILE_ARTIFACT_NOUNS = (
    "文件",
    "表格",
    "excel",
    "xlsx",
    "xls",
    "csv",
    "word",
    "docx",
    "文档",
    "ppt",
    "pptx",
    "幻灯片",
    "演示文稿",
    "pdf",
    "报告",
    "报表",
    "压缩包",
    "zip",
    "附件",
    "产物",
    "交付物",
    "spreadsheet",
    "sheet",
    "document",
    "report",
    "slide",
    "deck",
    "presentation",
    "archive",
    "deliverable",
    "file",
)
_CURRENT_BUSINESS_DATA_TERMS = (
    "当前",
    "现在",
    "今天",
    "今日",
    "实时",
    "最新",
    "查询",
    "查一下",
    "汇总",
    "统计",
    "多少",
    "数量",
    "记录",
    "列表",
    "进度",
    "异常",
    "风险",
    "逾期",
    "待处理",
    "业务概况",
    "current",
    "today",
    "latest",
    "query",
    "list",
    "count",
    "progress",
    "risk",
    "overdue",
)
_BUSINESS_MUTATION_TERMS = (
    "新增",
    "新建",
    "创建",
    "添加",
    "录入",
    "保存",
    "修改",
    "更新",
    "编辑",
    "调整",
    "改成",
    "改为",
    "删除",
    "移除",
    "作废",
    "恢复",
    "审批",
    "批准",
    "提交",
    "create",
    "add",
    "insert",
    "save",
    "update",
    "edit",
    "change",
    "delete",
    "remove",
    "approve",
)
_FILE_DESTINATION_TERMS = (
    "个人空间",
    "工作空间",
    "部门空间",
    "企业公共空间",
    "公司空间",
    "文件夹",
    "目录",
    "workspace",
    "folder",
    "directory",
)
_REQUEST_CLAUSE_SEPARATOR = re.compile(r"(?:[，,。；;！!？?\n]+|并且|然后|同时|以及|随后|并|再|\b(?:and|then)\b)")
# Runtime-side continuation budget (``settings.agent_completion_max_nudges`` overrides if defined).
_COMPLETION_MAX_NUDGES = 1
_COMPLETION_NUDGE_TEXT = (
    "[系统续执行要求] 上一次尚未产生用户要求的文件。"
    "请调用必要的平台文件工具并实际生成产物；只有真实 tool_result 返回输出文件后才能结束。"
)
_POLICY_TITLES = {
    "continuation": "续执行要求",
    "repeat_failure_block": "重复失败拦截",
    "tool_timeout": "工具超时",
    "approval_requested": "审批请求",
    "approval_decided": "审批结果",
}
# Optional ``policy`` event fields copied into the step / trace record when present.
_POLICY_DETAIL_KEYS = ("tool", "detail", "nudge", "approval_id", "outcome", "decided_by")


class AssistantRunError(RuntimeError):
    """Structured failure emitted by the native Assistant Core."""

    def __init__(self, message: str, *, code: str | None = None):
        super().__init__(message)
        self.code = code


def _public_failure_message(exc: Exception) -> str:
    if isinstance(exc, AssistantRunError) and exc.code == "MAX_STEPS_EXCEEDED":
        return "达到最大步数，未产生最终回答。"
    if isinstance(exc, AssistantRunError) and exc.code == "CANCELLED":
        return "本次运行已停止。"
    if isinstance(exc, AssistantRunError):
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
    """Native tool specs (schema plus runtime metadata) for one run."""
    return assistant_tool_specs(tools, registry or {})


def _requests_file_delivery(request: str) -> bool:
    """Return whether the user explicitly asked for a file / document / table deliverable."""
    text = (request or "").lower()
    return (
        bool(text)
        and any(verb in text for verb in _FILE_PRODUCTION_VERBS)
        and any(noun in text for noun in _FILE_ARTIFACT_NOUNS)
    )


def _requests_current_business_data(state: dict) -> bool:
    """Identify business-assistant requests that require a live subsystem Action result."""

    if not state.get("application_id"):
        return False
    intent = state.get("business_turn_intent") or {}
    if intent:
        return bool(intent.get("requiresLiveData")) and intent.get("intent") in {"query", "export_file"}
    # Compatibility for already registered pages that have not migrated to
    # aiSemantics. New and updated pages are validated onto the structured path.
    request = str(state.get("request") or "").lower()
    return any(term in request for term in _CURRENT_BUSINESS_DATA_TERMS)


def _requests_business_mutation(state: dict) -> bool:
    """Identify application requests that ask the assistant to change business data."""

    if not state.get("application_id"):
        return False
    intent = state.get("business_turn_intent") or {}
    if intent:
        return intent.get("intent") == "mutate"
    request = str(state.get("request") or "").lower()
    for term in _BUSINESS_MUTATION_TERMS:
        if term.isascii():
            continue
        for prefix in ("已", "已经", "曾", "曾经", "不要", "无需", "不必", "请勿", "禁止"):
            request = request.replace(f"{prefix}{term}", "")
    clauses = [part.strip() for part in _REQUEST_CLAUSE_SEPARATOR.split(request) if part.strip()]
    if _requests_file_delivery(request):
        clauses = [
            clause
            for clause in clauses
            if not (
                any(noun in clause for noun in _FILE_ARTIFACT_NOUNS)
                or any(destination in clause for destination in _FILE_DESTINATION_TERMS)
            )
        ]
    return any(term in clause for clause in clauses for term in _BUSINESS_MUTATION_TERMS)


def _enterprise_operation(entry: dict, tool_name: str = "") -> str:
    action = entry.get("action")
    operation = str(getattr(action, "operation", "") or entry.get("operation") or "").lower()
    if operation:
        return operation
    lowered = tool_name.lower()
    for candidate in ("query", "create", "update", "delete", "approve", "export"):
        if candidate in lowered:
            return candidate
    return ""


def _enterprise_result_status(content: object) -> str:
    if not isinstance(content, str):
        return ""
    try:
        value = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return ""
    return str(value.get("status") or "").lower() if isinstance(value, dict) else ""


def _file_output_tools(state: dict) -> list[str]:
    names = list(_FILE_OUTPUT_TOOL_NAMES)
    for name, entry in (state.get("_assistant_tool_registry") or {}).items():
        if isinstance(entry, dict) and entry.get("kind") in _FILE_OUTPUT_REGISTRY_KINDS and name not in names:
            names.append(name)
    return names


def _completion_policy(state: dict) -> dict[str, Any]:
    """Build the runtime-owned ``completion_policy`` for this run.

    The native runtime enforces it (nudging the model at most ``max_nudges`` times when no
    file-producing tool succeeded); Python only reports the resulting ``policy`` events.
    """
    if state.get("application_id"):
        intent = state.get("business_turn_intent") or {}
        require_file = (
            business_assistant_orchestration.intent_requires_artifact(intent)
            if intent
            else _requests_file_delivery(str(state.get("request") or ""))
        )
    else:
        require_file = _requests_file_delivery(str(state.get("request") or ""))
    require_file = (state.get("exec_mode") or "craft") == "craft" and require_file
    return {
        "require_file_output": require_file,
        "file_output_tools": _file_output_tools(state),
        "max_nudges": int(getattr(settings, "agent_completion_max_nudges", _COMPLETION_MAX_NUDGES)),
        "nudge_text": _COMPLETION_NUDGE_TEXT,
    }


def _history(state: dict) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for item in state.get("messages") or []:
        if item.get("role") not in {"user", "assistant"} or not isinstance(item.get("content"), str):
            continue
        content = str(item.get("content") or "")
        business_context = item.get("business_context")
        if state.get("application_id") and isinstance(business_context, dict) and business_context:
            content = (
                f"{content}\n\n[该历史消息的可信业务上下文]\n"
                f"{json.dumps(business_context, ensure_ascii=False, default=str)}"
            )
        rows.append({"role": item.get("role"), "content": content})
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
    entry = (state.get("_assistant_tool_registry") or {}).get(name) or {}
    kind = entry.get("kind")
    if name in FILE_TOOL_OPERATIONS or name.endswith("_tool") or name.startswith("workspace_"):
        category, title = "file", "文件解析与引用"
    elif kind == "memory":
        category, title = "memory", "长期记忆"
    else:
        category, title = "tool", name
    state.setdefault("traces", []).append(
        {
            "category": category,
            "title": title,
            "id": call_id,
            "name": name,
            "arguments": arguments,
            "result": result[:4000],
            "ok": ok,
        }
    )


def _apply_policy_event(
    state: dict,
    event: dict,
    text: str,
    handle: run_registry.RunHandle | None,
    staged: list[dict],
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
    state: dict,
    deps: dict,
    writer: Any,
    *,
    handle: run_registry.RunHandle | None = None,
    staged: list[dict] | None = None,
) -> tuple[dict, str]:
    with bind_runtime(deps, writer):
        _merge(state, await load_config(state))
        _merge(state, await load_memory(state))
        if state.get("application_id") and (state.get("business_turn_envelope") or {}).get("semanticReady"):
            envelope = business_assistant_orchestration.BusinessTurnEnvelope.model_validate(
                state.get("business_turn_envelope") or {}
            )
            writer(json.dumps({"type": "business_state", "status": "understanding"}, ensure_ascii=False))
            intent, classifier_usage, attempts = await business_assistant_orchestration.classify_business_turn(
                deps["db"],
                envelope=envelope,
                request_text=str(state.get("request") or ""),
                model_alias=str(state.get("model_alias") or "default"),
                department_id=state.get("department_id"),
                history_refs=[
                    dict(item.get("business_context") or {})
                    for item in state.get("messages") or []
                    if isinstance(item, dict) and item.get("business_context")
                ],
            )
            state["business_turn_intent"] = business_assistant_orchestration.intent_dict(intent)
            state["usage"] = {
                "input_tokens": int((state.get("usage") or {}).get("input_tokens") or 0)
                + classifier_usage["input_tokens"],
                "output_tokens": int((state.get("usage") or {}).get("output_tokens") or 0)
                + classifier_usage["output_tokens"],
            }
            state.setdefault("steps", []).append({
                "step": "business_intent",
                "intent": intent.intent,
                "target": intent.target.model_dump(mode="json", by_alias=True),
                "attempts": attempts,
            })
            trace = {
                "category": "business_orchestration",
                "title": "业务路由提示（非执行门禁）",
                "intent": intent.intent,
                "targetPage": intent.target.page_key,
                "attempts": attempts,
            }
            state.setdefault("traces", []).append(trace)
            writer(json.dumps({"type": "trace", **trace}, ensure_ascii=False))
            if intent.intent == "navigate":
                target_page = next(
                    (
                        item for item in envelope.candidate_pages
                        if item.get("moduleKey") == intent.target.module_key
                        and item.get("pageKey") == intent.target.page_key
                    ),
                    None,
                )
                if target_page:
                    state["business_navigation_suggestion"] = {
                        "applicationId": envelope.application_id,
                        "moduleKey": intent.target.module_key,
                        "pageKey": intent.target.page_key,
                        "pageName": target_page.get("pageName"),
                        "route": target_page.get("routePattern"),
                    }
            if state.get("user_message_id"):
                message = await deps["db"].get(TaskMessage, uuid.UUID(str(state["user_message_id"])))
                if message is not None:
                    metadata = dict(message.metadata_ or {})
                    metadata["business_turn_intent"] = state["business_turn_intent"]
                    metadata["business_turn_envelope"] = {
                        "requestId": envelope.request_id,
                        "applicationId": envelope.application_id,
                        "moduleKey": envelope.module_key,
                        "pageKey": envelope.page_key,
                        "pageName": envelope.page_name,
                        "authEpoch": envelope.auth_epoch,
                    }
                    message.metadata_ = metadata
                    await deps["db"].flush()
            writer(json.dumps({
                "type": "business_state",
                "status": "awaiting_clarification" if intent.intent == "clarify" else "planned",
                "intent": intent.intent,
            }, ensure_ascii=False))
        prepared = await prepare_assistant_turn(state)
    state["traces"] = prepared["traces"]
    state["_assistant_tool_registry"] = prepared["registry"]
    if state.get("application_id"):
        selected_tools = [
            str((item.get("function") or {}).get("name") or "")
            for item in (prepared.get("tools") or [])
            if str((item.get("function") or {}).get("name") or "")
        ]
        tool_trace = {
            "category": "business_orchestration",
            "title": "本轮授权工具集合",
            "intent": (state.get("business_turn_intent") or {}).get("intent") or "legacy",
            "tools": selected_tools,
        }
        state.setdefault("traces", []).append(tool_trace)
        writer(json.dumps({"type": "trace", **tool_trace}, ensure_ascii=False))
    # ``handle`` / ``staged`` let bridge callbacks (user approvals) publish onto this run's SSE
    # channel and into the persisted event log exactly like the runner's own events.
    context = AssistantRunContext(
        state=state,
        db=deps["db"],
        deps=deps,
        tool_registry=prepared["registry"],
        allowed_tool_names={
            str((item.get("function") or {}).get("name") or "")
            for item in (prepared.get("tools") or [])
            if str((item.get("function") or {}).get("name") or "")
        },
        image_inputs=_image_inputs(prepared.get("messages") or []),
        provider_override=prepared["provider_override"],
        model_override=prepared["model_override"],
        handle=handle,
        staged=staged,
    )
    return prepared, approval_registry.register(context)


async def _consume_native(
    state: dict,
    prepared: dict,
    run_token: str,
    handle: run_registry.RunHandle | None,
    staged: list[dict],
    deps: dict,
) -> None:
    intent = state.get("business_turn_intent") or {}
    # The classifier is a retrieval hint only.  It may suggest clarification or a
    # target page, but it must never short-circuit the main LLM before the LLM sees
    # the current context and authorized tools.  The main loop can query for missing
    # facts, repair invalid tool arguments, navigate when useful, or ask the user only
    # when the ambiguity genuinely cannot be resolved.
    _publish(handle, staged, {"type": "business_state", "status": "executing", "intent": intent.get("intent")})
    tool_registry = prepared.get("registry") or state.get("_assistant_tool_registry") or {}
    all_tool_specs = _tool_specs(prepared["tools"], tool_registry)
    current_page_tool_names = {
        str(name)
        for name, entry in tool_registry.items()
        if isinstance(entry, dict)
        and entry.get("kind") in {"enterprise_action", "enterprise_export_file"}
        and bool(entry.get("current_page", True))
    }
    visible_tool_specs, lazy_tool_specs = partition_tool_specs(
        all_tool_specs,
        current_page_tool_names=current_page_tool_names,
    )
    capability_entry = tool_registry.get("enterprise_capability_search") or {}
    capability_application_id = str(capability_entry.get("application_id") or "")
    capability_catalog = [
        {
            "applicationId": capability_application_id,
            **item,
        }
        for item in [
            *(capability_entry.get("candidate_pages") or []),
            *(capability_entry.get("authorized_actions") or []),
        ]
        if isinstance(item, dict)
    ]
    request = {
        "run_id": str(state["run_id"]),
        "user_id": str(state.get("user_id") or "platform-admin"),
        "task_id": str(state.get("task_id") or f"agent:{state.get('agent_id', '')}"),
        "run_token": run_token,
        "messages": _history(state),
        "message": state.get("request", ""),
        "system_prompt": prepared["system_prompt"],
        "model": {
            "alias": state.get("model_alias") or "default",
            "max_tokens": state.get("max_tokens"),
            "temperature": state.get("temperature"),
        },
        "memory_context": prepared.get("memory_context") or None,
        "exec_mode": state.get("exec_mode") or "craft",
        "tools": visible_tool_specs,
        "lazy_tools": lazy_tool_specs,
        "capability_catalog": capability_catalog,
        "max_steps": settings.agent_max_steps,
        # The native loop owns continuation nudges and repeat-failure blocking;
        # the coordinator never re-runs a request under a second id.
        "completion_policy": _completion_policy(state),
    }
    text = ""
    successful_tools = 0
    failed_tools: list[tuple[str, str]] = []
    enterprise_action_calls = 0
    enterprise_query_calls = 0
    successful_enterprise_queries = 0
    enterprise_mutation_calls = 0
    successful_enterprise_mutations = 0
    pending_enterprise_mutations = 0
    failed_enterprise_mutations: list[str] = []
    tool_arguments: dict[str, str] = {}
    usage = {
        "input_tokens": int((state.get("usage") or {}).get("input_tokens") or 0),
        "output_tokens": int((state.get("usage") or {}).get("output_tokens") or 0),
    }
    event_source = native_core.stream_run(
        request,
        state=state,
        prepared=prepared,
        deps=deps,
        run_context=approval_registry.get(run_token),
    )
    async for event in event_source:
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
            ok = bool(event.get("ok"))
            name = str(event.get("name") or "tool")
            successful_tools += int(ok)
            call_id = str(event.get("id") or "")
            entry = (state.get("_assistant_tool_registry") or {}).get(name) or {}
            entry_kind = entry.get("kind")
            published_event = dict(event)
            published_event["tool_kind"] = entry_kind or ""
            try:
                tool_envelope = json.loads(str(event.get("content") or ""))
            except (json.JSONDecodeError, TypeError):
                tool_envelope = None
            if isinstance(tool_envelope, dict) and isinstance(tool_envelope.get("uiIntent"), dict):
                ui_intent = dict(tool_envelope["uiIntent"])
                if ui_intent.get("type") == "navigate":
                    state["business_navigation_suggestion"] = ui_intent
                _publish(
                    handle,
                    staged,
                    {
                        "type": "ui_intent",
                        "runId": str(state.get("run_id") or ""),
                        "toolCallId": call_id,
                        "intent": ui_intent,
                    },
                )
            if entry_kind == "enterprise_action":
                enterprise_action_calls += 1
                operation = _enterprise_operation(entry, name)
                result_status = _enterprise_result_status(event.get("content"))
                mutation_committed = bool(
                    ok
                    and operation in {"create", "update", "delete", "approve"}
                    and result_status not in {"pending", "failed", "error"}
                )
                published_event.update(
                    {
                        "business_operation": operation,
                        "business_result_status": result_status,
                        "business_mutation_committed": mutation_committed,
                    }
                )
                if operation == "query":
                    enterprise_query_calls += 1
                    successful_enterprise_queries += int(ok and result_status != "failed")
                elif operation in {"create", "update", "delete", "approve"}:
                    enterprise_mutation_calls += 1
                    if ok and result_status == "pending":
                        pending_enterprise_mutations += 1
                    elif mutation_committed:
                        successful_enterprise_mutations += 1
                    else:
                        failed_enterprise_mutations.append(str(event.get("content") or "未返回错误详情"))
            elif entry_kind == "enterprise_export_file":
                # This trusted composite tool performs the current-page export Action
                # itself, validates every paged result, then commits the artifact through
                # the platform file service.  Count the successful composite result as a
                # verified live query; otherwise the final guard would retract a genuine
                # export merely because the model never saw a separate Action tool call.
                enterprise_action_calls += 1
                enterprise_query_calls += 1
                result_status = _enterprise_result_status(event.get("content"))
                successful_enterprise_queries += int(ok and result_status not in {"failed", "error"})
            _publish(handle, staged, published_event)
            state.setdefault("business_tool_executions", []).append({
                "toolCallId": call_id,
                "name": name,
                "kind": entry_kind or "",
                "operation": published_event.get("business_operation") or _enterprise_operation(entry, name),
                "ok": ok,
                "resultStatus": published_event.get("business_result_status") or "",
            })
            if not ok:
                failed_tools.append((name, str(event.get("content") or "工具未返回错误详情")))
            state.setdefault("steps", []).append({"step": "tool", "name": name, "ok": ok})
            _trace_for_tool(
                state,
                name,
                call_id,
                tool_arguments.get(call_id, ""),
                str(event.get("content") or ""),
                ok,
            )
        elif kind == "policy":
            text = _apply_policy_event(state, event, text, handle, staged)
        elif kind == "usage":
            usage["input_tokens"] += int(event.get("input_tokens") or 0)
            usage["output_tokens"] += int(event.get("output_tokens") or 0)
        elif kind == "error":
            raise AssistantRunError(
                str(event.get("message") or "Assistant Core failed"),
                code=str(event.get("code") or "") or None,
            )
        elif kind == "done":
            text = str(event.get("text") or text)

    _publish(handle, staged, {"type": "business_state", "status": "verifying", "intent": intent.get("intent")})
    mutation_required = _requests_business_mutation(state)
    mutation_unverified = mutation_required and successful_enterprise_mutations == 0
    # A successful mutation already carries the subsystem's authoritative result.
    # Generic nouns such as "记录" must not arm a second query requirement and turn a
    # completed write into a failed run merely because the model did not query again.
    live_business_data_required = _requests_current_business_data(state) and not mutation_required
    live_business_data_unverified = live_business_data_required and successful_enterprise_queries == 0
    if mutation_unverified:
        if text:
            _publish(handle, staged, {"type": "text_retract", "chars": len(text)})
        if pending_enterprise_mutations:
            text = "该业务操作尚未执行，正在等待你确认。确认后系统才会真正修改业务数据。"
            state.setdefault("steps", []).append(
                {
                    "step": "business_mutation_pending_confirmation",
                    "pending_enterprise_mutations": pending_enterprise_mutations,
                }
            )
        elif enterprise_mutation_calls:
            detail = " ".join((failed_enterprise_mutations[-1] if failed_enterprise_mutations else "").split())[:300]
            text = "本轮业务操作没有成功执行，业务数据未被修改。"
            if detail:
                text += f" 原因：{detail}"
            state["error"] = "Requested business mutation was not completed"
            state.setdefault("steps", []).append(
                {
                    "step": "business_mutation_rejected",
                    "enterprise_mutation_calls": enterprise_mutation_calls,
                }
            )
        else:
            text = "本轮未调用当前页面的业务操作，因此业务数据没有被修改。请重试。"
            state["error"] = "Requested business mutation was not completed"
            state.setdefault("steps", []).append(
                {
                    "step": "business_mutation_rejected",
                    "enterprise_mutation_calls": enterprise_mutation_calls,
                }
            )
        _publish(handle, staged, {"type": "text", "delta": text})
    elif live_business_data_unverified:
        if text:
            _publish(handle, staged, {"type": "text_retract", "chars": len(text)})
        if enterprise_query_calls:
            text = "本轮实时业务查询没有成功返回，因此暂时无法确认当前数据。请稍后重试。"
        else:
            text = "本轮未调用当前页面的实时业务查询，因此无法确认当前数据。请重试。"
        _publish(handle, staged, {"type": "text", "delta": text})
        state["error"] = "Current business data was not verified by a successful enterprise Action"
        state.setdefault("steps", []).append(
            {
                "step": "current_business_data_rejected",
                "enterprise_action_calls": enterprise_action_calls,
            }
        )
    elif successful_tools == 0 and contains_unverified_tool_success_claim(text):
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
            state["error"] = "Assistant Core completed without a final response"
            text = "模型未返回最终回答，请重试。"
        _publish(handle, staged, {"type": "text", "delta": text})
    state["assistant_final"] = text
    state["usage"] = usage
    state.setdefault("messages", []).append({"role": "assistant", "content": state["assistant_final"]})
    state.setdefault("steps", []).append({"step": "llm_final"})


async def _set_run_status(
    db: Any,
    run_id: int,
    status: str,
) -> None:
    run = await db.get(AgentRun, run_id)
    if run is not None:
        run.status = status
        await db.commit()


async def _admitted_run(
    state: dict,
    deps: dict,
    prepared: dict,
    run_token: str,
    handle: run_registry.RunHandle | None,
    staged: list[dict],
    user_id: str,
) -> None:
    """Acquire a shared Redis permit before entering the native Assistant Core."""
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
        await _consume_native(state, prepared, run_token, handle, staged, deps)


async def _finish(state: dict, deps: dict, writer: Any = lambda _payload: None) -> None:
    """Persist the final response before the caller emits the terminal ``done`` event."""
    with bind_runtime(deps, writer):
        await save_memory(state)
        _merge(state, await extract_memory(state))
        await write_run_log(state)
        await deps["db"].commit()


def _publish_failure_reply(
    handle: run_registry.RunHandle | None,
    staged: list[dict],
    state: dict,
    exc: Exception,
) -> None:
    """流式失败时把「公开错误回复」推到 SSE，最终 done 由持久化完成后统一发送。

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


async def _finish_failed_run(
    state: dict,
    deps: dict,
    exc: Exception,
    writer: Any = lambda _payload: None,
) -> None:
    """Preserve the public graceful-error contract when the coordinator is unavailable."""
    message = f"Assistant Core failed: {exc}"
    state["error"] = message
    state["assistant_final"] = _public_failure_message(exc)
    state.setdefault("messages", []).append(
        {"role": "assistant", "content": state["assistant_final"]},
    )
    state.setdefault("steps", []).append({"step": "runtime_error", "error": message})
    await _finish(state, deps, writer)


async def _persist_early_failure_reply(state: dict, task: Any, exc: Exception) -> str:
    """Persist a public assistant reply when preparation fails before execution starts."""

    public_message = _public_failure_message(exc)
    state["error"] = f"Assistant Core failed: {exc}"
    state["assistant_final"] = public_message
    state.setdefault("messages", []).append({"role": "assistant", "content": public_message})
    state.setdefault("steps", []).append({"step": "runtime_prepare_error"})
    message_id = uuid.uuid4()
    async with async_session_factory() as db:
        db.add(
            TaskMessage(
                id=message_id,
                task_id=task.id,
                role="assistant",
                content=public_message,
                metadata_={
                    "traces": state.get("traces") or [],
                    "artifacts": [],
                    "business_turn_intent": state.get("business_turn_intent") or {},
                    "page_context": state.get("page_context") or {},
                    "tool_executions": state.get("business_tool_executions") or [],
                    "runtime_error": True,
                },
            )
        )
        await db.commit()
    state["assistant_message_id"] = str(message_id)
    return str(message_id)


async def run_general_agent(
    *,
    org_id: str,
    user: CurrentUser,
    task: Any,
    message: str,
    config: dict,
    session_id: str | None,
    db: Any,
    request: Any,
    attachment_files: list[dict] | None = None,
    file_refs_v1: list[dict] | None = None,
    client_request_id: str | None = None,
) -> dict:
    start = time.monotonic()
    state = general_initial_state(
        org_id=org_id,
        user=user,
        task_id=str(task.id),
        message=message,
        session_id=session_id,
        config=config,
        attachment_files=attachment_files,
        file_refs_v1=file_refs_v1,
    )
    state["client_request_id"] = client_request_id
    deps = general_context(db, request, user, task)
    user_message = TaskMessage(
        task_id=task.id,
        role="user",
        content=message,
        metadata_=user_message_metadata(state),
    )
    db.add(user_message)
    await db.commit()
    state["user_message_id"] = str(user_message.id)
    staged: list[dict] = []
    run_token = ""
    try:
        prepared, run_token = await _prepare(state, deps, lambda raw: staged.append(json.loads(raw)), staged=staged)
        try:
            await _admitted_run(state, deps, prepared, run_token, None, staged, str(user.id))
            await _finish(state, deps)
        except Exception as exc:  # noqa: BLE001
            logger.warning("assistant_terminal_run_failed", error=str(exc), exc_info=True)
            await _finish_failed_run(state, deps, exc)
    finally:
        if run_token:
            approval_registry.revoke(run_token)
    status = "failed" if state.get("error") else "completed"
    return {
        "session_id": state["session_id"],
        "assistant": state.get("assistant_final", ""),
        "steps": state.get("steps", []),
        "usage": state.get("usage", {}),
        "error": state.get("error"),
        "run_id": state.get("run_id"),
        "latency_ms": int((time.monotonic() - start) * 1000),
        "taskId": str(task.id),
        "runId": state.get("run_id"),
        "userMessageId": state.get("user_message_id"),
        "assistantMessageId": state.get("assistant_message_id"),
        "status": status,
        "content": state.get("assistant_final", ""),
        "intent": state.get("business_turn_intent"),
        "pageContext": state.get("page_context") or {},
        "toolExecutions": state.get("business_tool_executions") or [],
        "artifacts": state.get("artifacts") or [],
        "navigationSuggestion": state.get("business_navigation_suggestion"),
    }


async def stream_general_agent(
    *,
    org_id: str,
    user: CurrentUser,
    task: Any,
    message: str,
    config: dict,
    session_id: str | None,
    db: Any,
    request: Any,
    attachment_files: list[dict] | None = None,
    file_refs_v1: list[dict] | None = None,
    client_request_id: str | None = None,
) -> Response:
    task_id = str(task.id)
    handle = run_registry.get(task_id)
    if handle is not None and not handle.done:
        if client_request_id and handle.client_request_id == client_request_id:
            return StreamingResponse(
                sse_replay_and_tail(handle),
                status_code=200,
                media_type="text/event-stream",
                headers=_SSE_HEADERS,
            )
        raise HTTPException(status_code=409, detail="当前对话已有任务正在执行，请等待完成后再提交")
    if handle is not None and handle.done:
        run_registry.drop(task_id)
        handle = None
    if handle is None:
        handle = run_registry.get_or_register(task_id)
        handle.client_request_id = client_request_id
        state = general_initial_state(
            org_id=org_id,
            user=user,
            task_id=task_id,
            message=message,
            session_id=session_id or f"sess-{uuid.uuid4()}",
            config=config,
            attachment_files=attachment_files,
            file_refs_v1=file_refs_v1,
        )
        state["client_request_id"] = client_request_id
        handle.bg_task = asyncio.create_task(
            _run_bg(handle, state=state, user=user, task=task),
            name=f"assistant_core_run:{task_id}",
        )
    return StreamingResponse(
        sse_replay_and_tail(handle),
        status_code=200,
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


async def _run_bg(handle: run_registry.RunHandle, *, state: dict, user: CurrentUser, task: Any) -> None:
    start = time.monotonic()
    staged: list[dict] = []
    run_token = ""
    try:
        async with async_session_factory() as db:
            deps = general_context(db, None, user, task)
            user_message = TaskMessage(
                task_id=task.id,
                role="user",
                content=state.get("request", ""),
                metadata_=user_message_metadata(state),
            )
            db.add(user_message)
            await db.commit()
            state["user_message_id"] = str(user_message.id)

            def writer(raw: str) -> None:
                event = json.loads(raw)
                _publish(handle, staged, event)

            prepared, run_token = await _prepare(state, deps, writer, handle=handle, staged=staged)
            handle.run_id = int(state["run_id"])
            try:
                await _admitted_run(state, deps, prepared, run_token, handle, staged, str(user.id))
                await _finish(state, deps, writer)
                _publish(handle, staged, {"type": "done", "usage": state.get("usage") or {}})
            except asyncio.CancelledError:
                # 用户 Stop / 进程关停：不走「失败回复」，交给外层 CancelledError 分支
                # （finalize_bg_error 会以 "cancelled" 收口，前端按「已停止」展示）。
                raise
            except Exception as exc:  # noqa: BLE001
                # 与 run_general_agent 一致：把失败落成一条 assistant TaskMessage + done 事件，
                # 让流式用户看到明确的错误回复，而不是流悄悄结束、刷新后本轮没有任何回复。
                logger.warning(
                    "assistant_general_bg_run_failed",
                    task_id=str(task.id),
                    error=str(exc),
                    exc_info=True,
                )
                _publish_failure_reply(handle, staged, state, exc)
                await _finish_failed_run(state, deps, exc, writer)
                _publish(handle, staged, {"type": "done", "usage": state.get("usage") or {}})
            finally:
                # The runtime stream is over (done / failed / user Stop): any approval still waiting
                # is settled as ``cancelled`` *before* ``staged`` is persisted so the decision is on record.
                approval_registry.cancel_approvals(run_token)
            final = json.dumps(
                {
                    "type": "final",
                    "session_id": state["session_id"],
                    "run_id": state.get("run_id"),
                    "latency_ms": int((time.monotonic() - start) * 1000),
                    "taskId": str(task.id),
                    "runId": state.get("run_id"),
                    "userMessageId": state.get("user_message_id"),
                    "assistantMessageId": state.get("assistant_message_id"),
                    "status": "failed" if state.get("error") else "completed",
                    "content": state.get("assistant_final", ""),
                    "intent": state.get("business_turn_intent"),
                    "pageContext": state.get("page_context") or {},
                    "toolExecutions": state.get("business_tool_executions") or [],
                    "artifacts": state.get("artifacts") or [],
                    "navigationSuggestion": state.get("business_navigation_suggestion"),
                    "error": state.get("error"),
                },
                ensure_ascii=False,
            )
            await persist_run_events(state.get("run_id"), str(task.id), staged, final)
            run_registry.mark_done(handle, final, error=str(state.get("error") or "") or None)
    except asyncio.CancelledError:
        await persist_run_events(state.get("run_id"), str(task.id), staged, None)
        await finalize_bg_error(
            handle,
            task,
            state.get("run_id"),
            "cancelled",
            "cancelled by user/shutdown",
            state["session_id"],
            start,
        )
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error("assistant_general_bg_error", task_id=str(task.id), error=str(exc), exc_info=True)
        public_message = _public_failure_message(exc)
        _publish_failure_reply(handle, staged, state, exc)
        try:
            assistant_message_id = await _persist_early_failure_reply(state, task, exc)
            _publish(
                handle,
                staged,
                {
                    "type": "assistant_message",
                    "messageId": assistant_message_id,
                    "content": public_message,
                    "artifacts": [],
                },
            )
        except Exception:  # noqa: BLE001
            logger.warning("assistant_prepare_failure_reply_persist_failed", task_id=str(task.id), exc_info=True)
        await persist_run_events(state.get("run_id"), str(task.id), staged, None)
        await finalize_bg_error(
            handle,
            task,
            state.get("run_id"),
            public_message,
            str(exc),
            state["session_id"],
            start,
        )
    finally:
        if run_token:
            approval_registry.revoke(run_token)
        if handle.done:
            run_registry.drop(str(task.id))
