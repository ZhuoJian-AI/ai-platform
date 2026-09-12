"""Native model/tool loop for the unified AI Assistant Core.

This coordinator emits the platform's normalized Task, Run, Message, Artifact and SSE
events directly so every assistant mode shares one execution contract.
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

from app.agents.core import approval_registry
from app.agents.graph.context import bind_runtime
from app.agents.graph.nodes import _execute_tool_call
from app.services import model_gateway
from app.services.assistant_delivery_policy import explicit_output_formats, missing_output_formats
from app.services.assistant_tool_catalog import search_assistant_capabilities
from app.services.assistant_tool_protocol import descriptor_from_spec, tool_result_json

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
_MAX_CORRECTION_CALLS = 3
_MAX_FAILED_ATTEMPTS = 1 + _MAX_CORRECTION_CALLS


def _platform_tools(specs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert runtime-neutral ToolSpecs to the model gateway function schema."""
    return [
        {
            "type": "function",
            "function": {
                "name": str(spec.get("name") or ""),
                "description": str(spec.get("description") or "") + (
                    " 调用本工具会先由平台显示确认卡片，用户确认前不会执行写入。"
                    "参数明确后请调用工具发起确认，不要用文字按钮代替确认卡片。"
                    if spec.get("approval") == "ask" else ""
                ),
                "parameters": spec.get("input_schema") or {"type": "object", "properties": {}},
                "strict": True,
            },
        }
        for spec in specs
        if str(spec.get("name") or "")
    ]


def _model_messages(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop platform-only history annotations before calling a provider."""
    # OpenAI-compatible reasoning models such as MiMo require an assistant
    # tool-call turn's ``reasoning_content`` to be passed back verbatim on the
    # following request.  It remains provider-facing metadata and is never
    # emitted as user-visible progress or stored as chat prose.
    allowed = {"role", "content", "reasoning_content", "tool_calls", "tool_call_id", "name"}
    return [{key: value for key, value in row.items() if key in allowed} for row in rows]


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _failure_key(name: str, arguments: dict[str, Any]) -> str:
    material = f"{name}\0{_stable_json(arguments)}".encode()
    return hashlib.sha256(material).hexdigest()


def _tool_error(
    code: str,
    message: str,
    correction: str = "",
    *,
    retryable: bool = False,
    correction_fields: list[dict[str, Any]] | None = None,
) -> str:
    return tool_result_json(
        "retryable_error" if retryable else "failed",
        error={
            "code": code,
            "messageZh": message,
            "correctionFields": list(correction_fields or []),
            "retryable": retryable,
        },
        data={"correctionHint": correction} if correction else None,
    )


def _parse_and_validate_arguments(
    call: dict[str, Any], spec: dict[str, Any],
) -> tuple[dict[str, Any] | None, str | None]:
    raw = call.get("arguments", "{}")
    try:
        value = json.loads(raw) if isinstance(raw, str) else raw
    except (json.JSONDecodeError, TypeError):
        return None, _tool_error(
            "invalid_tool_arguments",
            "工具参数不是有效的 JSON",
            "请按工具参数结构重新提交",
            retryable=True,
        )
    if not isinstance(value, dict):
        return None, _tool_error(
            "invalid_tool_arguments",
            "工具参数必须是对象",
            "请使用字段名和值组成对象",
            retryable=True,
        )
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
        retryable=True,
        correction_fields=[{"field": location, "reason": first.message}],
    )


def _bounded_tool_content(content: str, limit: int) -> str:
    if limit <= 0 or len(content) <= limit:
        return content
    return content[:limit] + f"\n[工具结果已截断，共 {len(content)} 字符；如需更多内容请分页读取]"


def _tool_result_artifacts(content: str | dict[str, Any]) -> list[dict[str, Any]]:
    """Only a stable workspace file/version identity counts as delivery.

    A tool name, server path, URL, or free-form success message is not proof that
    the workspace transaction committed.  Both the native continuation policy
    and the final persistence guard use this same minimum identity contract.
    """

    value: Any = content
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return []
    if not isinstance(value, dict):
        return []

    def has_identity(item: Any) -> bool:
        if not isinstance(item, dict):
            return False
        file_id = item.get("file_id") or item.get("fileId")
        version_id = item.get("version_id") or item.get("versionId")
        return bool(file_id and version_id)

    artifacts = [value] if has_identity(value) else []
    containers = [value]
    data = value.get("data")
    if isinstance(data, dict):
        containers.append(data)
    for container in containers:
        for key in ("artifacts", "outputs", "files"):
            candidates = container.get(key)
            if isinstance(candidates, list):
                artifacts.extend(item for item in candidates if has_identity(item))
    return artifacts


def _tool_result_has_trusted_artifact(content: str | dict[str, Any]) -> bool:
    return bool(_tool_result_artifacts(content))


def _capability_search_result(
    query: str,
    lazy_specs: dict[str, dict[str, Any]],
    business_catalog: list[dict[str, Any]],
    *,
    limit: int,
) -> tuple[str, list[str]]:
    selected = search_assistant_capabilities(query, lazy_specs.values(), business_catalog, limit=limit)
    selected_specs = [entry["item"] for entry in selected if entry["kind"] == "tool"]
    activated = [
        str(item.get("name") or "")
        for item in selected_specs
        if item.get("name")
    ]
    candidates = [
        {"kind": "tool", "descriptor": descriptor_from_spec(entry["item"])}
        if entry["kind"] == "tool" else {**entry["item"], "kind": "business"}
        for entry in selected
    ]
    return (
        tool_result_json(
            "completed",
            data={
                "query": query,
                "candidates": candidates,
                "activatedTools": activated,
            },
        ),
        activated,
    )


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
) -> tuple[str, list[dict[str, Any]], dict[str, int], str | None]:
    text = ""
    calls: list[dict[str, Any]] = []
    reasoning_parts: list[str] = []
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
        provider_override=prepared.get("provider_override"),
        model_override=prepared.get("model_override"),
    )
    async for kind, payload, extra in _iterate_with_runtime(stream, deps):
        if kind == "text":
            delta = str(payload or "")
            text += delta
            if delta and deps.get("public_text_sink") is not None:
                await deps["public_text_sink"](delta)
        elif kind == "tool_calls":
            calls = list(payload or [])
        elif kind == "reasoning_content" and payload:
            reasoning_parts.append(str(payload))
        elif kind == "usage" and isinstance(extra, dict):
            usage["input_tokens"] += int(extra.get("input_tokens") or 0)
            usage["output_tokens"] += int(extra.get("output_tokens") or 0)
    if text or calls:
        reasoning_content = "".join(reasoning_parts) or None
        return text, calls, usage, reasoning_content

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
            provider_override=prepared.get("provider_override"),
            model_override=prepared.get("model_override"),
        )
    usage["input_tokens"] += int((result.usage or {}).get("input_tokens") or 0)
    usage["output_tokens"] += int((result.usage or {}).get("output_tokens") or 0)
    return (
        str(result.content or ""),
        list(result.tool_calls or []),
        usage,
        str(result.reasoning_content) if result.reasoning_content else None,
    )


async def _stream_model_turn(**kwargs):
    """Relay public text while the model runs; never relay private reasoning.

    The queue is bounded for slow SSE consumers. Closing the generator cancels
    its sole producer, which lets the gateway settle quota in its finally block.
    Tools still execute only after the complete model turn is validated.
    """
    queue = asyncio.Queue(maxsize=32)

    async def sink(delta):
        await queue.put(("text", delta))

    async def produce():
        try:
            result = await _model_turn(**{**kwargs, "deps": {**kwargs["deps"], "public_text_sink": sink}})
            await queue.put(("result", result))
        except Exception as exc:
            await queue.put(("error", exc))

    producer = asyncio.create_task(produce(), name="assistant-public-text-relay")
    try:
        while True:
            kind, payload = await queue.get()
            if kind == "error":
                raise payload
            yield kind, payload
            if kind == "result":
                return
    finally:
        if not producer.done():
            producer.cancel()
        # Always retrieve the producer outcome, including disconnect cancellation.
        await asyncio.gather(producer, return_exceptions=True)


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
        labels = spec.get("confirmation_field_labels")
        labels = labels if isinstance(labels, dict) else {}
        summary_fields = []
        for field, value in arguments.items():
            rendered = _stable_json(value) if isinstance(value, (dict, list)) else str(value)
            if len(rendered) > 160:
                rendered = rendered[:157] + "..."
            summary_fields.append(
                {
                    "label": str(labels.get(field) or field),
                    "value": rendered,
                }
            )
        result = await approval_registry.await_approval(
            context,
            approval_id=approval_id,
            tool=name,
            call_id=call_id,
            reason=f"{name} 会产生业务或文件副作用，需要用户确认",
            arguments_preview=preview,
            display_title=str(spec.get("display_title") or "确认本次操作"),
            summary_fields=summary_fields,
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
    lazy_specs = {
        str(item.get("name") or ""): item
        for item in request.get("lazy_tools") or []
        if item.get("name")
    }
    business_catalog = [
        dict(item)
        for item in request.get("capability_catalog") or []
        if isinstance(item, dict)
    ]
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
    required_formats = explicit_output_formats(str(state.get("request") or ""))
    delivered_artifacts: list[dict[str, Any]] = []
    nudges = 0
    visible_text = ""
    last_failure_key = ""
    consecutive_failures = 0
    tool_failures: dict[str, int] = {}
    exhausted_tools: set[str] = set()
    discovery_corrections = 0
    successful_side_effects: dict[str, str] = {}
    uncertain_writes: dict[str, str] = {}

    for step_index in range(max_steps):
        yield {"type": "phase", "phase": "llm", "index": step_index}
        emitted_text = ""
        turn_result = None
        turn_stream = _stream_model_turn(
            state=state,
            prepared=prepared,
            deps=deps,
            messages=messages,
            tools=model_tools,
        )
        try:
            async for event_kind, payload in turn_stream:
                if event_kind == "text":
                    emitted_text += payload
                    visible_text += payload
                    yield {"type": "text_delta", "delta": payload}
                else:
                    turn_result = payload
        finally:
            await turn_stream.aclose()
        text, calls, usage, reasoning_content = turn_result
        # Non-streaming fallback/adapter responses have not been sent yet.
        if text and not emitted_text:
            visible_text += text
            yield {"type": "text_delta", "delta": text}
        yield {"type": "usage", **usage}

        authorized_calls = [call for call in calls if str(call.get("name") or "") in allowed_names]
        rejected_calls = [str(call.get("name") or "<empty>") for call in calls if call not in authorized_calls]
        if rejected_calls:
            recoverable = (
                all(name in lazy_specs for name in rejected_calls)
                and "enterprise_capability_search" in allowed_names
                and discovery_corrections < _MAX_CORRECTION_CALLS
            )
            yield {
                "type": "trace",
                "category": "policy",
                "title": "工具调用未执行",
                "code": "tool_not_loaded_or_allowed",
                "tools": sorted({name[:128] for name in rejected_calls})[:64],
                "visibleTools": sorted(allowed_names),
                "retryable": recoverable,
            }
            logger.warning(
                "native_unadvertised_tool_calls",
                tools=sorted(set(rejected_calls)),
                run_id=state.get("run_id"),
            )
            if not recoverable:
                raise RuntimeError("模型请求了本轮未授权或尚未加载的工具，已拒绝执行")
            discovery_corrections += 1
            # Reject the entire batch before side effects. Preserve a complete
            # assistant/tool exchange, including provider reasoning metadata.
            correction_turn = {
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
                    for index, call in enumerate(calls)
                ],
            }
            if reasoning_content:
                correction_turn["reasoning_content"] = reasoning_content
            messages.append(correction_turn)
            for call in correction_turn["tool_calls"]:
                messages.append({
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "content": _tool_error(
                        "tool_discovery_required",
                        "本批次未执行：包含尚未加载的工具",
                        "请先调用 enterprise_capability_search 搜索所需能力，"
                        "获得完整 Schema 后重新提交；不要直接重试未加载工具",
                        retryable=True,
                    ),
                })
            continue

        if authorized_calls:
            assistant_tool_turn = {
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
            if reasoning_content:
                assistant_tool_turn["reasoning_content"] = reasoning_content
            messages.append(assistant_tool_turn)
            recovery_guidance: list[dict[str, str]] = []
            for index, original in enumerate(authorized_calls):
                call = dict(original)
                call["id"] = str(call.get("id") or f"native-{step_index}-{index}")
                name = str(call.get("name") or "")
                spec = specs[name]
                params, validation_error = _parse_and_validate_arguments(call, spec)
                arguments_text = str(call.get("arguments") or "{}")
                yield {"type": "tool_call", "id": call["id"], "name": name, "arguments": arguments_text}

                failure_key = _failure_key(name, params or {"_raw": arguments_text})
                dedupe_side_effect = validation_error is None and not bool(spec.get("concurrency_safe"))
                skip_repeat = failure_key == last_failure_key and consecutive_failures >= 2
                if name in uncertain_writes:
                    # A new call id or changed arguments cannot establish that
                    # a timed-out write did not commit. Keep reads available,
                    # but never automatically issue this write again.
                    content, ok = uncertain_writes[name], False
                elif name in exhausted_tools:
                    content = _tool_error(
                        "tool_retry_exhausted",
                        "首次尝试及三次纠正均未成功，已停止该工具重试",
                        "请使用其他获权能力，或如实说明无法完成；不要生成替代产物",
                    )
                    ok = False
                elif skip_repeat:
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
                elif dedupe_side_effect and failure_key in successful_side_effects:
                    content = successful_side_effects[failure_key]
                    ok = True
                    yield {
                        "type": "policy",
                        "action": "duplicate_side_effect_reused",
                        "tool": name,
                        "detail": "same_tool_and_arguments=true; backend_skipped=true",
                    }
                else:
                    assert params is not None
                    call["arguments"] = _stable_json(params)
                    if name == "enterprise_capability_search":
                        content, activated_names = _capability_search_result(
                            str(params.get("query") or ""),
                            lazy_specs,
                            business_catalog,
                            limit=int(params.get("limit") or 8),
                        )
                        for activated_name in activated_names:
                            activated_spec = lazy_specs.pop(activated_name, None)
                            if activated_spec is not None:
                                specs[activated_name] = activated_spec
                                allowed_names.add(activated_name)
                        model_tools = _platform_tools([
                            item for key, item in specs.items() if key in allowed_names
                        ])
                        ok = True
                        yield {
                            "type": "policy",
                            "action": "tool_catalog_loaded",
                            "tool": name,
                            "detail": f"activated={len(activated_names)}",
                            "activatedTools": activated_names,
                            "visibleTools": sorted(allowed_names),
                        }
                    elif spec.get("approval") == "ask":
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
                                "write_outcome_unknown" if dedupe_side_effect else "tool_timeout",
                                ("写操作超时，执行结果尚未确认" if dedupe_side_effect
                                 else f"工具执行超时（{int(timeout * 1000)} ms）"),
                                ("先通过只读查询核对执行状态，不得重新提交写操作或宣称成功；"
                                 f"原调用标识：{call['id']}" if dedupe_side_effect
                                 else "请缩小处理范围或稍后重试"),
                                retryable=not dedupe_side_effect,
                            )
                            if dedupe_side_effect:
                                uncertain_writes[name] = content
                            ok = False
                            yield {
                                "type": "policy",
                                "action": "tool_timeout",
                                "tool": name,
                                "detail": f"timeout_ms={int(timeout * 1000)}",
                            }

                if ok:
                    tool_failures[name] = 0
                    consecutive_failures = 0
                    last_failure_key = failure_key
                    if dedupe_side_effect:
                        successful_side_effects.setdefault(failure_key, content)
                    if name in file_tools:
                        delivered_artifacts.extend(_tool_result_artifacts(content))
                    delivered = bool(delivered_artifacts) and not missing_output_formats(
                        required_formats, delivered_artifacts,
                    )
                else:
                    tool_failures[name] = tool_failures.get(name, 0) + 1
                    consecutive_failures = consecutive_failures + 1 if failure_key == last_failure_key else 1
                    last_failure_key = failure_key
                    if consecutive_failures >= 2 and not skip_repeat:
                        yield {
                            "type": "policy",
                            "action": "repeat_failure_block",
                            "tool": name,
                            "detail": f"consecutive_failures={consecutive_failures}; backend_skipped=false",
                        }
                    if consecutive_failures == 2:
                        recovery_guidance.append({"role": "user", "content": _REPEAT_FAILURE_GUIDANCE})

                yield {"type": "tool_result", "id": call["id"], "name": name, "content": content, "ok": ok}
                model_content = _bounded_tool_content(str(content), int(spec.get("max_model_chars") or 60_000))
                messages.append({"role": "tool", "tool_call_id": call["id"], "content": model_content})
                if tool_failures.get(name, 0) >= _MAX_FAILED_ATTEMPTS and name not in exhausted_tools:
                    # A changed argument or an unrelated successful lookup must
                    # not reset this tool's correction budget. Keep other tools
                    # available so the model may choose a genuinely different path.
                    exhausted_tools.add(name)
                    allowed_names.discard(name)
                    model_tools = _platform_tools([
                        item for key, item in specs.items() if key in allowed_names
                    ])
                    yield {
                        "type": "policy",
                        "action": "tool_retry_exhausted",
                        "tool": name,
                        "detail": "首次尝试及三次纠正均失败；其他获权工具仍可使用",
                    }
                    recovery_guidance.append({
                        "role": "user",
                        "content": (
                            f"[执行状态] {name} 首次尝试及三次纠正均失败，本轮不再提供。"
                            "请选择其他获权能力；如果无法交付用户要求的结果，请明确失败，"
                            "不要用其他格式的文件替代。"
                        ),
                    })
            # Every tool_call must receive its tool response before guidance or
            # another user turn (required by OpenAI-compatible providers).
            messages.extend(recovery_guidance)
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
            missing = missing_output_formats(required_formats, delivered_artifacts)
            correction = str(policy.get("nudge_text") or _DEFAULT_COMPLETION_NUDGE)
            if missing:
                correction += " 尚未交付要求的格式：" + "、".join(sorted(missing)) + "；其他格式不能替代。"
            messages.append({"role": "user", "content": correction})
            continue

        if policy.get("require_file_output") and not delivered:
            yield {
                "type": "error",
                "code": "ARTIFACT_DELIVERY_FAILED",
                "message": "文件生成未完成：未取得工作空间确认的文件版本，不能宣称交付成功。",
            }
            return

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
