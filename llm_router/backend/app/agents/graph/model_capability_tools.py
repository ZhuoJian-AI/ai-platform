"""Stable Assistant Core tools backed by verified model capabilities.

The model sees provider-neutral tool names.  Provider, deployment, credentials and
endpoint selection stay inside :mod:`app.services.model_gateway` and are resolved
from the administrator's verified capability configuration on every call.
"""

from __future__ import annotations

import hashlib
import mimetypes
import re
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Any
from uuid import UUID, uuid4

import structlog
from fastapi import HTTPException

from app.auth.user_auth import CurrentUser
from app.dlp.scanner import scan_request
from app.models.audit_log import AuditLog
from app.services import (
    model_gateway,
    multimodal_audio_service,
    multimodal_service,
    storage_gateway_service,
    workspace_service,
)
from app.services.assistant_tool_protocol import tool_result_json
from app.utils.workspace_presentation import enrich_metadata

logger = structlog.get_logger()

AUDIO_TOOL_NAMES = {
    "audio_transcribe",
    "audio_understand",
    "speech_synthesize",
}
MODEL_CAPABILITY_TOOL_NAMES = {*AUDIO_TOOL_NAMES}
_AUDIO_INPUT_SUFFIXES = {".mp3": "mp3", ".wav": "wav"}
_AUDIO_MAX_INPUT_FILES = 5
_AUDIO_OUTPUT_FORMATS = {"mp3", "wav"}

AuthorizeInput = Callable[[object, CurrentUser | None], Awaitable[tuple[Any | None, CurrentUser | None]]]
ResolveOutputWorkspace = Callable[
    [dict[str, Any], CurrentUser | None],
    Awaitable[tuple[Any | None, CurrentUser | None, str | None]],
]
TaskSource = Callable[[], Awaitable[dict[str, str | None]]]
FileIdentity = Callable[[Any, Any, CurrentUser | None], Awaitable[dict[str, Any]]]


def _has_permission(user: CurrentUser | None, permission: str) -> bool:
    codes = set(getattr(user, "permission_codes", ()) or ())
    return user is not None and ("*" in codes or permission in codes)


async def _audio_feature_enabled(db: Any, organization_id: UUID) -> bool:
    try:
        await multimodal_audio_service.require_multimodal_enabled(db, organization_id)
    except HTTPException:
        return False
    return True


async def model_capability_availability(
    db: Any,
    user: CurrentUser | None,
) -> dict[str, Any]:
    """Return only capabilities usable by this employee at tool-assembly time."""

    if user is None:
        return {
            "vision": False,
            "audio_transcribe": False,
            "audio_understand": False,
            "speech_synthesize": False,
            "speech_modes": [],
        }
    organization_id = UUID(str(user.organization_id))
    department_id = user.department_id
    vision = (
        await multimodal_service.resolve_vision_fallback(
            db,
            organization_id,
            dept_id=department_id,
        )
        is not None
    )
    audio_enabled = await _audio_feature_enabled(db, organization_id)
    transcribe = bool(
        audio_enabled
        and _has_permission(user, "multimodal.audio.transcribe")
        and await model_gateway.resolve_deployment(
            db,
            organization_id,
            "default",
            "speech_to_text",
            dept_id=department_id,
        )
    )
    understand = bool(
        audio_enabled
        and _has_permission(user, "multimodal.audio.understand")
        and await model_gateway.resolve_deployment(
            db,
            organization_id,
            "default",
            "audio_understanding",
            dept_id=department_id,
        )
    )
    speech_modes: list[str] = []
    if audio_enabled and _has_permission(user, "multimodal.speech.use"):
        for mode, capability in (
            ("standard", "text_to_speech"),
            ("design", "voice_design"),
            ("clone", "voice_clone"),
        ):
            if await model_gateway.resolve_deployment(
                db,
                organization_id,
                "default",
                capability,
                dept_id=department_id,
            ):
                speech_modes.append(mode)
    return {
        "vision": vision,
        "audio_transcribe": transcribe,
        "audio_understand": understand,
        "speech_synthesize": bool(speech_modes),
        "speech_modes": speech_modes,
    }


def model_capability_tool_definitions(availability: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Build closed schemas without exposing provider/model/key/url parameters."""

    availability = availability or {}
    tools: list[dict[str, Any]] = []
    if availability.get("audio_transcribe"):
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": "audio_transcribe",
                    "description": "转写当前用户有权读取的工作空间 MP3/WAV 音频，返回文本和可用时间片段。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "input_file_ids": {
                                "type": "array",
                                "items": {"type": "string"},
                                "minItems": 1,
                                "maxItems": _AUDIO_MAX_INPUT_FILES,
                            },
                            "language": {
                                "type": "string",
                                "description": "可选语言提示，如 zh、en；不确定时省略",
                            },
                        },
                        "required": ["input_file_ids"],
                        "additionalProperties": False,
                    },
                    "strict": True,
                },
            }
        )
    if availability.get("audio_understand"):
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": "audio_understand",
                    "description": "直接理解当前用户有权读取的工作空间音频，并回答与声音内容有关的问题。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "input_file_ids": {
                                "type": "array",
                                "items": {"type": "string"},
                                "minItems": 1,
                                "maxItems": _AUDIO_MAX_INPUT_FILES,
                            },
                            "question": {"type": "string", "minLength": 1, "maxLength": 4000},
                        },
                        "required": ["input_file_ids", "question"],
                        "additionalProperties": False,
                    },
                    "strict": True,
                },
            }
        )
    speech_modes = [
        mode
        for mode in (availability.get("speech_modes") or [])
        if mode in {"standard", "design", "clone"}
    ]
    if availability.get("speech_synthesize") and speech_modes:
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": "speech_synthesize",
                    "description": (
                        "把文本合成为真实 MP3/WAV 文件并交付到当前用户工作空间。"
                        "voice_alias 只能使用管理员已授权的企业音色名称。"
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "text": {"type": "string", "minLength": 1, "maxLength": 20000},
                            "mode": {"type": "string", "enum": speech_modes},
                            "voice_alias": {"type": "string", "maxLength": 255},
                            "style": {"type": "string", "maxLength": 1000},
                            "speed": {"type": "number", "minimum": 0.5, "maximum": 2.0},
                            "output_format": {"type": "string", "enum": ["mp3", "wav"]},
                            "output_name": {"type": "string", "maxLength": 255},
                            "target_workspace_id": {"type": "string"},
                        },
                        "required": ["text"],
                        "additionalProperties": False,
                    },
                    "strict": True,
                },
            }
        )
    return tools


def _error(
    code: str,
    message_zh: str,
    *,
    hint: str,
    fields: list[str] | None = None,
    retryable: bool = True,
) -> str:
    correction = []
    if fields:
        correction.append({"fields": fields, "hint": hint})
    return tool_result_json(
        "retryable_error" if retryable else "failed",
        error={
            "code": code,
            "messageZh": message_zh,
            "correctionFields": correction,
            "retryable": retryable,
        },
    )


def _audio_format(file: Any) -> str | None:
    suffix = PurePosixPath(str(getattr(file, "path", "") or "")).suffix.lower()
    return _AUDIO_INPUT_SUFFIXES.get(suffix)


def _validate_audio_output(raw: bytes, output_format: str) -> str:
    if not raw:
        raise ValueError("语音模型返回了空文件")
    if output_format == "wav":
        if len(raw) < 12 or not raw.startswith(b"RIFF") or raw[8:12] != b"WAVE":
            raise ValueError("语音模型返回的内容不是有效 WAV 文件")
        return "audio/wav"
    is_id3 = raw.startswith(b"ID3")
    is_frame = len(raw) >= 2 and raw[0] == 0xFF and (raw[1] & 0xE0) == 0xE0
    if not (is_id3 or is_frame):
        raise ValueError("语音模型返回的内容不是有效 MP3 文件")
    return "audio/mpeg"


def _safe_audio_name(value: object, output_format: str) -> str:
    requested = PurePosixPath(str(value or f"语音-{uuid4().hex[:8]}.{output_format}")).name
    stem = PurePosixPath(requested).stem or "语音"
    stem = re.sub(r"[^\w\-.\u4e00-\u9fff]+", "-", stem, flags=re.UNICODE).strip("-.") or "语音"
    return f"{stem}.{output_format}"


async def _check_audio_permission(
    db: Any,
    user: CurrentUser | None,
    permission: str,
) -> str | None:
    if user is None:
        return "语音工具需要有效的员工身份"
    try:
        await multimodal_audio_service.require_multimodal_enabled(db, UUID(str(user.organization_id)))
        multimodal_audio_service.require_permission(user, permission)
    except HTTPException:
        return "当前角色没有此语音能力，或企业尚未启用该能力"
    return None


async def _transcribe(
    *,
    db: Any,
    state: dict[str, Any],
    params: dict[str, Any],
    user: CurrentUser | None,
    authorize_input: AuthorizeInput,
) -> str:
    values = params.get("input_file_ids")
    if not isinstance(values, list) or not 1 <= len(values) <= _AUDIO_MAX_INPUT_FILES:
        return _error(
            "invalid_input_file_ids",
            "请选择 1 至 5 个音频文件",
            hint="传入工作空间音频文件 ID 数组",
            fields=["input_file_ids"],
        )
    results: list[dict[str, Any]] = []
    principal = user
    for value in values:
        file, principal = await authorize_input(value, principal)
        if file is None:
            return _error(
                "audio_file_unavailable",
                "音频文件不存在或当前角色无权读取",
                hint="重新选择有读取权限的工作空间文件",
                fields=["input_file_ids"],
                retryable=False,
            )
        audio_format = _audio_format(file)
        if audio_format is None:
            return _error(
                "unsupported_audio_format",
                "语音转写当前支持 MP3 和 WAV",
                hint="先把音频转换为 MP3 或 WAV 后重试",
                fields=["input_file_ids"],
            )
        permission_error = await _check_audio_permission(db, principal, "multimodal.audio.transcribe")
        if permission_error:
            return _error(
                "audio_permission_denied",
                permission_error,
                hint="请联系企业管理员为当前角色授权语音转写",
                retryable=False,
            )
        raw = await workspace_service.load_file_bytes(file)
        try:
            result = await model_gateway.transcribe_audio(
                db,
                UUID(str(state["org_id"])),
                raw,
                audio_format=audio_format,
                language=str(params.get("language") or "auto"),
                model_alias="default",
                dept_id=getattr(principal, "department_id", None),
                request_id=f"assistant-asr-{state.get('run_id') or uuid4().hex}",
            )
        except model_gateway.GatewayError as exc:
            logger.warning("assistant_audio_transcribe_failed", category=exc.category)
            return _error(
                exc.category,
                "语音转写暂时失败",
                hint="请稍后重试，或检查管理员是否已验证语音转写模型",
            )
        results.append(
            {
                "fileId": str(file.id),
                "name": PurePosixPath(file.path).name,
                "text": result.get("text") or "",
                "segments": result.get("segments") or [],
            }
        )
    return tool_result_json("completed", data={"transcriptions": results})


async def _understand(
    *,
    db: Any,
    state: dict[str, Any],
    params: dict[str, Any],
    user: CurrentUser | None,
    authorize_input: AuthorizeInput,
) -> str:
    values = params.get("input_file_ids")
    question = str(params.get("question") or "").strip()
    if not isinstance(values, list) or not 1 <= len(values) <= _AUDIO_MAX_INPUT_FILES:
        return _error(
            "invalid_input_file_ids",
            "请选择 1 至 5 个音频文件",
            hint="传入工作空间音频文件 ID 数组",
            fields=["input_file_ids"],
        )
    if not question:
        return _error(
            "missing_question",
            "请说明需要从音频中了解什么",
            hint="补充 question，例如“总结会议决定”",
            fields=["question"],
        )
    dlp = await scan_request(db, question, str(state["org_id"]), state.get("department_id"))
    if dlp.blocked:
        return _error(
            "audio_question_blocked",
            "音频问题被安全策略拦截",
            hint="移除敏感内容后重试",
            fields=["question"],
            retryable=False,
        )
    question = dlp.redacted_text or question
    principal = user
    answers: list[dict[str, Any]] = []
    for value in values:
        file, principal = await authorize_input(value, principal)
        if file is None:
            return _error(
                "audio_file_unavailable",
                "音频文件不存在或当前角色无权读取",
                hint="重新选择有读取权限的工作空间文件",
                fields=["input_file_ids"],
                retryable=False,
            )
        if _audio_format(file) is None:
            return _error(
                "unsupported_audio_format",
                "音频理解当前支持 MP3 和 WAV",
                hint="先把音频转换为 MP3 或 WAV 后重试",
                fields=["input_file_ids"],
            )
        permission_error = await _check_audio_permission(db, principal, "multimodal.audio.understand")
        if permission_error:
            return _error(
                "audio_permission_denied",
                permission_error,
                hint="请联系企业管理员为当前角色授权音频理解",
                retryable=False,
            )
        if not storage_gateway_service.is_object_ref(file.content_ref):
            return _error(
                "audio_not_in_object_storage",
                "音频尚未进入受控对象存储，无法交给音频理解模型",
                hint="重新上传音频到工作空间后重试",
                fields=["input_file_ids"],
            )
        signed = await storage_gateway_service.get_browser_signed_download(
            str(file.content_ref),
            version_id=workspace_service.storage_version_id(file),
        )
        try:
            result = await model_gateway.understand_audio(
                db,
                UUID(str(state["org_id"])),
                signed["url"],
                question,
                model_alias="default",
                dept_id=getattr(principal, "department_id", None),
                audio_size_bytes=file.size,
            )
        except model_gateway.GatewayError as exc:
            logger.warning("assistant_audio_understand_failed", category=exc.category)
            return _error(
                exc.category,
                "音频理解暂时失败",
                hint="可以改用语音转写后再由主脑分析，或稍后重试",
            )
        answers.append(
            {
                "fileId": str(file.id),
                "name": PurePosixPath(file.path).name,
                "answer": result.content or result.reasoning_content or "",
            }
        )
    return tool_result_json("completed", data={"answers": answers})


async def _synthesize(
    *,
    db: Any,
    state: dict[str, Any],
    params: dict[str, Any],
    user: CurrentUser | None,
    resolve_output_workspace: ResolveOutputWorkspace,
    task_source: TaskSource,
    file_identity: FileIdentity,
) -> str:
    text = str(params.get("text") or "").strip()
    if not text:
        return _error(
            "missing_text",
            "请输入需要合成的文本",
            hint="补充 text",
            fields=["text"],
        )
    if len(text) > 20000:
        return _error(
            "text_too_long",
            "单次语音合成文本过长",
            hint="把文本拆分为不超过 20000 字符的片段",
            fields=["text"],
        )
    dlp = await scan_request(db, text, str(state["org_id"]), state.get("department_id"))
    if dlp.blocked:
        return _error(
            "speech_text_blocked",
            "语音合成文本被安全策略拦截",
            hint="移除敏感内容后重试",
            fields=["text"],
            retryable=False,
        )
    text = dlp.redacted_text or text
    workspace, principal, workspace_error = await resolve_output_workspace(params, user)
    if workspace_error or workspace is None or principal is None:
        return _error(
            "workspace_permission_denied",
            workspace_error or "没有可写入的工作空间",
            hint="选择个人空间或当前角色有创建权限的空间",
            fields=["target_workspace_id"],
            retryable=False,
        )
    permission_error = await _check_audio_permission(db, principal, "multimodal.speech.use")
    if permission_error:
        return _error(
            "speech_permission_denied",
            permission_error,
            hint="请联系企业管理员为当前角色授权语音合成",
            retryable=False,
        )
    mode = str(params.get("mode") or "standard").strip().lower()
    if mode not in {"standard", "design", "clone"}:
        return _error(
            "invalid_speech_mode",
            "语音合成模式无效",
            hint="mode 只能是 standard、design 或 clone",
            fields=["mode"],
        )
    voice_alias = str(params.get("voice_alias") or "").strip()
    voice_profile = None
    if voice_alias:
        voices = await multimodal_audio_service.list_visible_voices(db, principal)
        voice_profile = next((item for item in voices if item.name.casefold() == voice_alias.casefold()), None)
        if voice_profile is None:
            return _error(
                "voice_alias_unavailable",
                "指定音色不存在或当前角色无权使用",
                hint="改用管理员已授权的企业音色名称，或省略 voice_alias 使用默认音色",
                fields=["voice_alias"],
            )
        expected_mode = {"builtin": "standard", "designed": "design", "cloned": "clone"}[voice_profile.voice_type]
        if mode != expected_mode:
            return _error(
                "voice_mode_mismatch",
                f"该音色需要使用 {expected_mode} 模式",
                hint=f"把 mode 改为 {expected_mode}",
                fields=["mode"],
            )
    elif mode in {"design", "clone"}:
        return _error(
            "voice_alias_required",
            "音色设计或克隆模式必须选择管理员已授权的企业音色",
            hint="补充 voice_alias，或改用 standard 模式",
            fields=["voice_alias", "mode"],
        )

    output_format = str(params.get("output_format") or "mp3").strip().lower()
    if output_format not in _AUDIO_OUTPUT_FORMATS:
        return _error(
            "unsupported_audio_format",
            "语音产物只能生成 MP3 或 WAV",
            hint="把 output_format 改为 mp3 或 wav",
            fields=["output_format"],
        )
    clone_audio = None
    clone_format = "wav"
    if voice_profile is not None and voice_profile.voice_type == "cloned":
        sample = await workspace_service.get_file(db, UUID(str(voice_profile.sample_file_id)))
        sample_workspace = (
            await workspace_service.get_workspace(db, sample.workspace_id)
            if sample is not None
            else None
        )
        if sample is None or sample_workspace is None or str(sample_workspace.organization_id) != str(
            principal.organization_id
        ):
            # ``sample_file_id`` is administrator-validated at voice creation;
            # fail closed if the referenced file was later removed or moved.
            return _error(
                "voice_sample_unavailable",
                "克隆音色的授权样本已不可用",
                hint="请联系企业管理员重新配置该音色",
                retryable=False,
            )
        clone_format = _audio_format(sample) or ""
        if not clone_format:
            return _error(
                "voice_sample_format_invalid",
                "克隆音色样本不是有效的 MP3/WAV 文件",
                hint="请联系企业管理员重新配置该音色",
                retryable=False,
            )
        clone_audio = await workspace_service.load_file_bytes(sample)

    tool_call_id = str(params.get("_tool_call_id") or uuid4().hex[:8])
    request_id = f"assistant-tts-{state.get('run_id') or uuid4().hex}-{tool_call_id}"
    try:
        result = await model_gateway.synthesize_audio(
            db,
            UUID(str(state["org_id"])),
            text=text,
            voice=voice_profile.provider_voice_id if voice_profile is not None else None,
            audio_format=output_format,
            style=str(params.get("style") or "").strip() or None,
            speed=float(params.get("speed") or 1.0),
            design_prompt=voice_profile.design_prompt if voice_profile is not None else None,
            clone_audio=clone_audio,
            clone_format=clone_format,
            model_alias="default",
            dept_id=principal.department_id,
            request_id=request_id,
        )
        raw = result["audio"]
        mime_type = _validate_audio_output(raw, output_format)
    except (model_gateway.GatewayError, ValueError, TypeError, KeyError) as exc:
        category = exc.category if isinstance(exc, model_gateway.GatewayError) else "invalid_audio_output"
        logger.warning("assistant_speech_synthesize_failed", category=category)
        return _error(
            category,
            "语音文件生成或校验失败",
            hint="请稍后重试，或检查管理员配置的语音模型能力",
        )

    # A provider call can outlive a role change. Resolve the same workspace
    # again through the callback that reloads the employee's current roles,
    # before uploading bytes or creating a file version.
    final_workspace, final_principal, final_error = await resolve_output_workspace(params, principal)
    if (
        final_error or final_workspace is None or final_principal is None
        or str(final_workspace.id) != str(workspace.id)
        or str(final_principal.id) != str(principal.id)
    ):
        return _error(
            "workspace_permission_changed",
            "语音生成期间工作空间权限或目标发生变化，未保存文件",
            hint="请确认当前角色有目标空间写入权限后重新生成",
            retryable=False,
        )
    permission_error = await _check_audio_permission(db, final_principal, "multimodal.speech.use")
    if permission_error:
        return _error(
            "speech_permission_changed",
            "语音生成期间语音权限已变化，未保存文件",
            hint="请联系企业管理员确认当前角色的语音权限",
            retryable=False,
        )
    workspace, principal = final_workspace, final_principal

    filename = _safe_audio_name(params.get("output_name"), output_format)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    task_part = str(state.get("task_id") or "playground")
    path = f"平台工具输出/{task_part}/{stamp}-{uuid4().hex[:8]}-{filename}"
    saved = await workspace_service.ingest_uploaded_file(
        db,
        workspace,
        path=path,
        filename=filename,
        content_type=mime_type,
        raw=raw,
        created_by_user_id=principal.id,
    )
    source = await task_source()
    saved.metadata_ = enrich_metadata(
        saved.path,
        {
            **(saved.metadata_ or {}),
            "generated_by": "speech_synthesize",
            "task_id": task_part,
            "voice_alias": voice_profile.name if voice_profile is not None else None,
            "speech_mode": mode,
            "sha256": hashlib.sha256(raw).hexdigest(),
        },
        source_kind="platform_tool",
        **source,
    )
    await workspace_service.sync_current_version(db, saved)
    identity = await file_identity(db, saved, workspace, principal)
    identity.update(
        {
            "display_name": filename,
            "name": filename,
            "mime_type": mime_type,
            "size": len(raw),
            "tool_call_id": tool_call_id,
        }
    )
    usage = result.get("usage") or {}
    routed_capability = result.get("capability") or model_gateway.speech_capability(
        design_prompt=voice_profile.design_prompt if voice_profile is not None else None,
        clone_audio=clone_audio,
    )
    db.add(
        AuditLog(
            request_id=request_id,
            organization_id=str(state["org_id"]),
            department_id=principal.department_id,
            event_type="speech_synthesis",
            direction="outbound",
            model_requested=f"default:{routed_capability}",
            model_served=result.get("model"),
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
            status_code=200,
            metadata_={
                "file_id": str(saved.id),
                "format": output_format,
                "speech_mode": mode,
                "checksum_sha256": saved.content_hash,
            },
        )
    )
    await db.flush()
    return tool_result_json(
        "completed",
        data={"message": "语音文件已保存到工作空间"},
        artifacts=[identity],
    )


async def execute_audio_tool(
    *,
    db: Any,
    state: dict[str, Any],
    name: str,
    params: dict[str, Any],
    user: CurrentUser | None,
    authorize_input: AuthorizeInput,
    resolve_output_workspace: ResolveOutputWorkspace,
    task_source: TaskSource,
    file_identity: FileIdentity,
) -> str:
    """Execute one stable audio tool with live role and workspace checks."""

    if name == "audio_transcribe":
        return await _transcribe(
            db=db,
            state=state,
            params=params,
            user=user,
            authorize_input=authorize_input,
        )
    if name == "audio_understand":
        return await _understand(
            db=db,
            state=state,
            params=params,
            user=user,
            authorize_input=authorize_input,
        )
    if name == "speech_synthesize":
        return await _synthesize(
            db=db,
            state=state,
            params=params,
            user=user,
            resolve_output_workspace=resolve_output_workspace,
            task_source=task_source,
            file_identity=file_identity,
        )
    return _error(
        "unknown_model_capability_tool",
        "未知模型能力工具",
        hint="重新搜索当前可用能力",
        retryable=False,
    )


async def execute_image_understanding(
    *,
    db: Any,
    state: dict[str, Any],
    params: dict[str, Any],
    user: CurrentUser | None,
    authorize_input: AuthorizeInput,
) -> str:
    """Understand authorized workspace images through the verified vision route."""

    values = params.get("input_file_ids")
    question = str(params.get("question") or "").strip()
    if not isinstance(values, list) or not 1 <= len(values) <= multimodal_service.MAX_IMAGE_COUNT:
        return _error(
            "invalid_input_file_ids",
            f"请选择 1 至 {multimodal_service.MAX_IMAGE_COUNT} 张图片",
            hint="传入当前角色有权读取的工作空间图片 ID 数组",
            fields=["input_file_ids"],
        )
    if not question:
        return _error(
            "missing_question",
            "请说明需要从图片中了解什么",
            hint="补充 question，例如“识别款式细节并总结”",
            fields=["question"],
        )
    dlp = await scan_request(db, question, str(state["org_id"]), state.get("department_id"))
    if dlp.blocked:
        return _error(
            "vision_question_blocked",
            "图片问题被安全策略拦截",
            hint="移除敏感内容后重试",
            fields=["question"],
            retryable=False,
        )
    question = dlp.redacted_text or question
    principal = user
    images: list[multimodal_service.PreparedImage] = []
    for value in values:
        file, principal = await authorize_input(value, principal)
        if file is None:
            return _error(
                "image_file_unavailable",
                "图片不存在或当前角色无权读取",
                hint="重新选择有读取权限的图片",
                fields=["input_file_ids"],
                retryable=False,
            )
        raw = await workspace_service.load_file_bytes(file)
        metadata = file.metadata_ or {}
        try:
            images.append(
                multimodal_service.prepare_image_bytes(
                    file_id=str(file.id),
                    name=str(metadata.get("name") or PurePosixPath(file.path).name),
                    declared_mime=str(metadata.get("mime") or mimetypes.guess_type(file.path)[0] or "") or None,
                    raw=raw,
                )
            )
        except ValueError as exc:
            return _error(
                "invalid_image",
                str(exc),
                hint="重新选择有效图片，或先用图片转换工具处理",
                fields=["input_file_ids"],
            )
    multimodal_service.ensure_image_batch_limits(images)
    fallback = await multimodal_service.resolve_vision_fallback(
        db,
        UUID(str(state["org_id"])),
        dept_id=getattr(principal, "department_id", None),
    )
    if fallback is None:
        return _error(
            "capability_not_configured",
            "当前企业没有可用的视觉模型",
            hint="请联系管理员验证并启用 vision 模型部署",
            retryable=False,
        )
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": question},
                *[
                    {"type": "image_url", "image_url": {"url": image.data_url, "detail": "auto"}}
                    for image in images
                ],
            ],
        }
    ]
    try:
        result = await model_gateway.chat(
            db,
            UUID(str(state["org_id"])),
            fallback.model,
            messages,
            system_prompt="只根据图片中可验证的内容回答；不确定时明确说明，不得编造。",
            provider_override=fallback.provider,
            model_override=fallback.model,
            dept_id=getattr(principal, "department_id", None),
            request_id=f"assistant-vision-{state.get('run_id') or uuid4().hex}",
        )
    except model_gateway.GatewayError as exc:
        logger.warning("assistant_image_understand_failed", category=exc.category)
        return _error(
            exc.category,
            "图片理解暂时失败",
            hint="请稍后重试，或检查管理员配置的视觉模型能力",
        )
    return tool_result_json(
        "completed",
        data={
            "answer": result.content or result.reasoning_content or "",
            "inputFiles": [
                {"fileId": image.file_id, "name": image.name, "checksumSha256": image.sha256}
                for image in images
            ],
        },
    )
