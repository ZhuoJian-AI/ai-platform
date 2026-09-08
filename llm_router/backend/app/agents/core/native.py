"""Native model/tool loop for the unified AI Assistant Core.

This coordinator intentionally emits the same normalized events as the legacy DSH
runtime.  The caller therefore keeps one Task/Run/Message/Artifact/SSE contract while
the execution engine is changed at a run boundary.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import structlog
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from app.agents.dsh import registry as approval_registry
from app.agents.graph.context import bind_runtime
from app.agents.graph.nodes import _execute_tool_call
from app.services import model_gateway

logger = structlog.get_logger()

_REPEAT_FAILURE_GUIDANCE = (
    "[系统提示] 同一工具以相同参数反复失败，继续原样重试不会成功。请检查错误并修正参数；"
    "若权限、文件或依赖不满足，请先补齐前置条件；仍无法完成时应如实说明，不能声称成功。"
)
_DEFAULT_COMPLETION_NUDGE = (
    "请继续：上一步尚未产生用户要求的真实文件。现在调用获准的文件工具生成、验证并保存文件，"
    "只有工作空间返回真实文件后才能结束。"
)
_MAX_APPROVAL_PREVIEW_CHARS = 500


def _platform_tools(specs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert runtime-neutral ToolSpecs to the model gateway function schema."""
    return [
        {
            "type": "function",
            "function": {
                "name": str(spec.get("name") or ""),
                "description": str(spec.get("description") or ""),
                "parameters": spec.get("input_schema") or {"type": "object", "properties": {}},
                "strict": True,
            },
        }
        for spec in specs
        if str(spec.get("name") or "")
    ]


def _model_messages(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop platform-only history annotations before calling a provider."""
    allowed = {"role", "content", "tool_calls", "tool_call_id", "name"}
    return [{key: value for key, value in row.items() if key in allowed} for row in rows]


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _failure_key(name: str, arguments: dict[str, Any]) -> str:
    material = f"{name}\0{_stable_json(arguments)}".encode()
    return hashlib.sha256(material).hexdigest()


def _tool_error(code: str, message: str, correction: str = "") -> str:
    return json.dumps(
        {
            "status": "error",
            "code": code,
            "messageZh": message,
            "retryable": False,
            "correctionHint": correction,
        },
        ensure_ascii=False,
    )


def _parse_and_validate_arguments(
    call: dict[str, Any], spec: dict[str, Any],
) -> tuple[dict[str, Any] | None, str | None]:
    raw = call.get("arguments", "{}")
    try:
        value = json.loads(raw) if isinstance(raw, str) else raw
    except (json.JSONDecodeError, TypeError):
        return None, _tool_error("invalid_tool_arguments", "工具参数不是有效的 JSON", "请按工具参数结构重新提交")
    if not isinstance(value, dict):
        return None, _tool_error("invalid_tool_arguments", "工具参数必须是对象", "请使用字段名和值组成对象")
    schema = spec.get("input_schema") or {"type": "object", "properties": {}}
    try:
        errors = sorted(Draft202012Validator(schema).iter_errors(value), key=lambda item: list(item.path))
    except SchemaError:
        logger.error("native_tool_schema_invalid", tool=spec.get("name"), exc_info=True)
        return None, _tool_error("invalid_tool_schema", "平台工具定义无效", "请联系管理员修复工具定义")
    if not errors:
        return value, None
    first = errors[0]
    location = ".".join(str(part) for part in first.absolute_path) or "根对象"
    return None, _tool_error(
        "invalid_tool_arguments",
        f"工具参数校验失败：{location} {first.message}",
        "请根据工具字段类型、必填项和取值范围修正后重试",
    )


def _bounded_tool_content(content: str, limit: int) -> str:
    if limit <= 0 or len(content) <= limit:
        return content
    return content[:limit] + f"\n[工具结果已截断，共 {len(content)} 字符；如需更多内容请分页读取]"


async def _iterate_with_runtime(source: Any, deps: dict[str, Any]):
    """Advance each async-generator step with platform runtime context bound."""
    iterator = aiter(source)
    try:
        while True:
            try:
                with bind_runtime(deps):
                    item = await anext(iterator)
            except StopAsyncIteration:
                return
            yield item
    finally:
        close = getattr(iterator, "aclose", None)
        if close is not None:
            with bind_runtime(deps):
                await close()


async def _model_turn(
    *,
    state: dict[str, Any],
    prepared: dict[str, Any],
    deps: dict[str, Any],
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
) -> tuple[str, list[dict[str, Any]], dict[str, int]]:
    text = ""
    calls: list[dict[str, Any]] = []
    usage = {"input_tokens": 0, "output_tokens": 0}
    stream = model_gateway.stream_chat(
        deps["db"],
        UUID(str(state["org_id"])),
        str(state.get("model_alias") or "default"),
        messages,
        system_prompt=str(prepared.get("system_prompt") or ""),
        temperature=state.get("temperature"),
        max_tokens=state.get("max_tokens"),
        tools=tools or None,
        dept_id=state.get("department_id"),
        team_id=None,
        provider_override=prepared.get("provider_override"),
        model_override=prepared.get("model_override"),
    )
    async for kind, payload, extra in _iterate_with_runtime(stream, deps):
        if kind == "text":
            text += str(payload or "")
        elif kind == "tool_calls":
            calls = list(payload or [])
        elif kind == "usage" and isinstance(extra, dict):
            usage["input_tokens"] += int(extra.get("input_tokens") or 0)
            usage["output_tokens"] += int(extra.get("output_tokens") or 0)
    if text or calls:
        return text, calls, usage

    # Some OpenAI-compatible providers omit tool calls from their streaming response.
    # A non-streaming retry is safe because no text/tool side effect was emitted.
    with bind_runtime(deps):
        result = await model_gateway.chat(
            deps["db"],
            UUID(str(state["org_id"])),
            str(state.get("model_alias") or "default"),
            messages,
            system_prompt=str(prepared.get("system_prompt") or ""),
            temperature=state.get("temperature"),
            max_tokens=state.get("max_tokens"),
            tools=tools or None,
            dept_id=state.get("department_id"),
            team_id=None,
            provider_override=prepared.get("provider_override"),
            model_override=prepared.get("model_override"),
        )
    usage["input_tokens"] += int((result.usage or {}).get("input_tokens") or 0)
    usage["output_tokens"] += int((result.usage or {}).get("output_tokens") or 0)
    return str(result.content or ""), list(result.tool_calls or []), usage


async def _approval(
    *,
    context: Any,
    spec: dict[str, Any],
    call: dict[str, Any],
    arguments: dict[str, Any],
) -> tuple[bool, dict[str, Any], dict[str, Any]]:
    approval_id = str(uuid.uuid4())
    name = str(call.get("name") or "tool")
    call_id = str(call.get("id") or "")
    requested = {
        "type": "policy",
        "action": "approval_requested",
        "tool": name,
        "approval_id": approval_id,
        "detail": f"approval_id={approval_id}",
    }
    if context is None:
        result = {"outcome": "unavailable", "decided_by": "system"}
    else:
        preview = _stable_json(arguments)
        if len(preview) > _MAX_APPROVAL_PREVIEW_CHARS:
            preview = preview[: _MAX_APPROVAL_PREVIEW_CHARS - 3] + "..."
        result = await approval_registry.await_approval(
            context,
            approval_id=approval_id,
            tool=name,
            call_id=call_id,
            reason=f"{name} 会产生业务或文件副作用，需要用户确认",
            arguments_preview=preview,
            timeout_ms=int(spec.get("approval_timeout_ms") or 120_000),
        )
    decided = {
        "type": "policy",
        "action": "approval_decided",
        "tool": name,
        "approval_id": approval_id,
        "outcome": result.get("outcome"),
        "decided_by": result.get("decided_by"),
        "detail": f"outcome={result.get('outcome')}; decided_by={result.get('decided_by')}",
    }
    return result.get("outcome") == approval_registry.APPROVAL_ALLOWED, requested, decided


async def stream_run(
    request: dict[str, Any],
    *,
    state: dict[str, Any],
    prepared: dict[str, Any],
    deps: dict[str, Any],
    run_context: Any = None,
) -> AsyncIterator[dict[str, Any]]:
    """Execute one run and yield the legacy-normalized runtime event protocol."""
    specs = {str(item.get("name") or ""): item for item in request.get("tools") or [] if item.get("name")}
    allowed_names = set(specs)
    model_tools = _platform_tools(list(specs.values()))
    messages = _model_messages(list(prepared.get("messages") or []))
    memory = str(prepared.get("memory_context") or "").strip()
    if memory:
        prepared = {**prepared, "system_prompt": f"{prepared.get('system_prompt') or ''}\n\n{memory}"}

    max_steps = max(1, min(int(request.get("max_steps") or 24), 64))
    policy = request.get("completion_policy") or {}
    file_tools = {str(item) for item in policy.get("file_output_tools") or []}
    max_nudges = max(0, min(int(policy.get("max_nudges") or 0), 3))
    delivered = False
    nudges = 0
    visible_text = ""
    last_failure_key = ""
    consecutive_failures = 0

    for step_index in range(max_steps):
        yield {"type": "phase", "phase": "llm", "index": step_index}
        text, calls, usage = await _model_turn(
            state=state,
            prepared=prepared,
            deps=deps,
            messages=messages,
            tools=model_tools,
        )
        if text:
            visible_text += text
            yield {"type": "text_delta", "delta": text}
        yield {"type": "usage", **usage}

        authorized_calls = [call for call in calls if str(call.get("name") or "") in allowed_names]
        rejected_calls = [str(call.get("name") or "<empty>") for call in calls if call not in authorized_calls]
        if rejected_calls:
            logger.warning(
                "native_unadvertised_tool_calls",
                tools=sorted(set(rejected_calls)),
                run_id=state.get("run_id"),
            )
            if not authorized_calls:
                raise RuntimeError("模型请求了本轮未授权的工具，已拒绝执行")

        if authorized_calls:
            messages.append(
                {
                    "role": "assistant",
                    "content": text,
                    "tool_calls": [
                        {
                            "id": str(call.get("id") or f"native-{step_index}-{index}"),
                            "type": "function",
                            "function": {
                                "name": str(call.get("name") or ""),
                                "arguments": str(call.get("arguments") or "{}"),
                            },
                        }
                        for index, call in enumerate(authorized_calls)
                    ],
                }
            )
            for index, original in enumerate(authorized_calls):
                call = dict(original)
                call["id"] = str(call.get("id") or f"native-{step_index}-{index}")
                name = str(call.get("name") or "")
                spec = specs[name]
                params, validation_error = _parse_and_validate_arguments(call, spec)
                arguments_text = str(call.get("arguments") or "{}")
                yield {"type": "tool_call", "id": call["id"], "name": name, "arguments": arguments_text}

                failure_key = _failure_key(name, params or {"_raw": arguments_text})
                skip_repeat = failure_key == last_failure_key and consecutive_failures >= 2
                if skip_repeat:
                    content = _tool_error(
                        "repeat_failure_blocked",
                        f"相同工具与参数已连续失败 {consecutive_failures + 1} 次",
                        "请修改参数、补齐前置条件或改用其他方法",
                    )
                    ok = False
                    yield {
                        "type": "policy",
                        "action": "repeat_failure_block",
                        "tool": name,
                        "detail": f"consecutive_failures={consecutive_failures + 1}; backend_skipped=true",
                    }
                elif validation_error is not None:
                    content, ok = validation_error, False
                else:
                    assert params is not None
                    call["arguments"] = _stable_json(params)
                    if spec.get("approval") == "ask":
                        approved, requested, decided = await _approval(
                            context=run_context,
                            spec=spec,
                            call=call,
                            arguments=params,
                        )
                        yield requested
                        yield decided
                        if not approved:
                            content = _tool_error(
                                "approval_rejected",
                                "该操作未获用户确认，未执行",
                                "如需执行请重新发起并确认",
                            )
                            ok = False
                        else:
                            content = ""
                            ok = True
                    else:
                        content, ok = "", True

                    if ok and not content:
                        timeout = max(1, min(int(spec.get("timeout_ms") or 120_000), 600_000)) / 1000
                        try:
                            with bind_runtime(deps):
                                tool_message, _preview, ok = await asyncio.wait_for(
                                    _execute_tool_call(state, call, prepared.get("registry") or {}),
                                    timeout=timeout,
                                )
                            content = str(tool_message.get("content") or "")
                        except TimeoutError:
                            content = _tool_error(
                                "tool_timeout",
                                f"工具执行超时（{int(timeout * 1000)} ms）",
                                "请缩小处理范围或稍后重试",
                            )
                            ok = False
                            yield {
                                "type": "policy",
                                "action": "tool_timeout",
                                "tool": name,
                                "detail": f"timeout_ms={int(timeout * 1000)}",
                            }

                if ok:
                    consecutive_failures = 0
                    last_failure_key = failure_key
                    delivered = delivered or name in file_tools
                else:
                    consecutive_failures = consecutive_failures + 1 if failure_key == last_failure_key else 1
                    last_failure_key = failure_key
                    if consecutive_failures >= 2 and not skip_repeat:
                        yield {
                            "type": "policy",
                            "action": "repeat_failure_block",
                            "tool": name,
                            "detail": f"consecutive_failures={consecutive_failures}; backend_skipped=false",
                        }
                    if consecutive_failures in {3, 5}:
                        messages.append({"role": "user", "content": _REPEAT_FAILURE_GUIDANCE})

                yield {"type": "tool_result", "id": call["id"], "name": name, "content": content, "ok": ok}
                model_content = _bounded_tool_content(str(content), int(spec.get("max_model_chars") or 60_000))
                messages.append({"role": "tool", "tool_call_id": call["id"], "content": model_content})
            continue

        if policy.get("require_file_output") and not delivered and nudges < max_nudges and step_index + 1 < max_steps:
            nudges += 1
            yield {
                "type": "policy",
                "action": "continuation",
                "nudge": nudges,
                "detail": "file output required but no file_output_tools call succeeded",
            }
            visible_text = ""
            messages.append({"role": "assistant", "content": text})
            messages.append({"role": "user", "content": str(policy.get("nudge_text") or _DEFAULT_COMPLETION_NUDGE)})
            continue

        if not text:
            raise RuntimeError("模型服务没有返回有效的最终响应")
        messages.append({"role": "assistant", "content": text})
        yield {"type": "done", "text": visible_text, "steps": step_index + 1}
        return

    yield {
        "type": "error",
        "code": "MAX_STEPS_EXCEEDED",
        "message": "达到最大步数，未产生最终回答。",
    }
