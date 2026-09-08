"""Scoped specialist-AI runs requested by an embedded business subsystem.

The browser host supplies the authenticated employee session and injects the
active application/page identity.  A subsystem declaration can narrow an AI
capability, but it can never choose a provider, model, tenant or wider scope.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import PurePath
from uuid import UUID, uuid4

from fastapi import HTTPException
from jsonschema import SchemaError, ValidationError, validate
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.user_auth import CurrentUser
from app.config import settings
from app.models.enterprise_application import EnterpriseApplication, EnterpriseApplicationAction
from app.models.multimodal import MultimodalJob
from app.models.organization import Organization
from app.services import enterprise_application_service, storage_gateway_service
from app.services.multimodal_service import prepare_image_bytes

SUPPORTED_CAPABILITIES = {
    "vision.ocr",
    "vision.compare",
    "vision.classify",
    "speech.transcribe",
    "text.extract",
    "business.predict",
}
SUPPORTED_INPUT_KINDS = {"image", "audio", "text", "json"}
REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,119}$")
_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
_AUDIO_SUFFIXES = {".mp3", ".wav", ".m4a", ".webm", ".opus", ".ogg"}
_TEXT_SUFFIXES = {".txt", ".md", ".markdown", ".csv", ".tsv", ".json"}


@dataclass(frozen=True)
class SubsystemAiInput:
    name: str
    mime_type: str
    raw: bytes
    kind: str
    sha256: str


def _manifest_capability(
    application: EnterpriseApplication,
    module_key: str,
    action_key: str,
) -> dict | None:
    integration = application.integration
    manifest = integration.manifest if integration and isinstance(integration.manifest, dict) else {}
    for module in manifest.get("modules") or []:
        if not isinstance(module, dict) or module.get("moduleKey") != module_key:
            continue
        for action in module.get("actions") or []:
            if isinstance(action, dict) and action.get("actionKey") == action_key:
                value = action.get("platformAiCapability")
                return value if isinstance(value, dict) else None
    return None


async def authorize_run(
    db: AsyncSession,
    user: CurrentUser,
    *,
    application_id: UUID,
    module_key: str,
    page_key: str,
    action_key: str,
    capability: str,
) -> tuple[EnterpriseApplication, EnterpriseApplicationAction, dict]:
    if capability not in SUPPORTED_CAPABILITIES:
        raise HTTPException(status_code=422, detail="该专业 AI 能力暂不受支持")
    organization = await db.get(Organization, user.organization_id)
    if (
        organization is None
        or not settings.subsystem_ai_enabled_for(
            organization.slug, organization_id=organization.id
        )
    ):
        raise HTTPException(status_code=404, detail="当前企业尚未启用子系统专业 AI 能力")
    application = await enterprise_application_service.get_application(db, application_id)
    if (
        application is None
        or str(application.organization_id) != str(user.organization_id)
        or not application.is_active
        or application.admin_disabled
    ):
        raise HTTPException(status_code=404, detail="业务应用不可用")
    action = next(
        (
            item
            for item in application.actions
            if item.action_key == action_key and item.module_key == module_key
        ),
        None,
    )
    if (
        action is None
        or not action.is_active
        or action.admin_disabled
        or not action.ai_enabled
        or action.operation != "query"
    ):
        raise HTTPException(status_code=403, detail="当前页面未授权该专业 AI 操作")
    if not enterprise_application_service.action_allowed_for_user(
        application,
        user,
        module_key,
        page_key,
        action_key,
        "ai_query",
    ):
        raise HTTPException(status_code=403, detail="当前员工无权在此页面使用该专业 AI 操作")
    declaration = _manifest_capability(application, module_key, action_key)
    if not declaration or declaration.get("type") != capability:
        raise HTTPException(status_code=409, detail="子系统专业 AI 声明与请求不一致")
    if declaration.get("humanConfirmation") != "required":
        raise HTTPException(status_code=409, detail="专业 AI 结果必须要求人工确认")
    return application, action, declaration


def prepare_input(name: str, mime_type: str | None, raw: bytes) -> SubsystemAiInput:
    safe_name = PurePath(name or "input.bin").name[:255]
    if not raw:
        raise HTTPException(status_code=422, detail=f"输入文件 {safe_name} 为空")
    suffix = PurePath(safe_name).suffix.lower()
    declared = (mime_type or "application/octet-stream").split(";", 1)[0].lower()
    if suffix in _IMAGE_SUFFIXES:
        try:
            prepared = prepare_image_bytes(
                file_id=hashlib.sha256(raw).hexdigest()[:16],
                name=safe_name,
                declared_mime=declared,
                raw=raw,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return SubsystemAiInput(
            name=safe_name,
            mime_type=prepared.mime_type,
            raw=prepared.raw,
            kind="image",
            sha256=prepared.sha256,
        )
    if suffix in _AUDIO_SUFFIXES:
        expected_prefixes = {
            ".mp3": (b"ID3", b"\xff"),
            ".wav": (b"RIFF",),
            ".m4a": (),
            ".webm": (b"\x1aE\xdf\xa3",),
            ".opus": (b"OggS",),
            ".ogg": (b"OggS",),
        }
        format_matches = (
            len(raw) >= 12 and raw[4:8] == b"ftyp"
            if suffix == ".m4a"
            else any(raw.startswith(prefix) for prefix in expected_prefixes[suffix])
        )
        if not format_matches:
            raise HTTPException(status_code=422, detail=f"音频文件 {safe_name} 的真实格式与扩展名不一致")
        if not declared.startswith("audio/") and declared != "application/ogg":
            raise HTTPException(status_code=422, detail=f"音频文件 {safe_name} 的 MIME 类型无效")
        return SubsystemAiInput(
            name=safe_name,
            mime_type=declared,
            raw=raw,
            kind="audio",
            sha256=hashlib.sha256(raw).hexdigest(),
        )
    if suffix in _TEXT_SUFFIXES:
        if not (
            declared.startswith("text/")
            or declared in {"application/json", "application/octet-stream"}
        ):
            raise HTTPException(status_code=422, detail=f"文本文件 {safe_name} 的 MIME 类型无效")
        try:
            raw.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise HTTPException(status_code=422, detail=f"文本文件 {safe_name} 必须使用 UTF-8 编码") from exc
        return SubsystemAiInput(
            name=safe_name,
            mime_type=declared,
            raw=raw,
            kind="text",
            sha256=hashlib.sha256(raw).hexdigest(),
        )
    raise HTTPException(status_code=422, detail=f"输入文件 {safe_name} 的格式暂不支持")


def validate_inputs(
    capability: str,
    declaration: dict,
    inputs: list[SubsystemAiInput],
    *,
    text_input: str,
    context: dict,
) -> None:
    declared_kinds = declaration.get("inputKinds")
    if (
        not isinstance(declared_kinds, list)
        or not declared_kinds
        or any(kind not in SUPPORTED_INPUT_KINDS for kind in declared_kinds)
    ):
        raise HTTPException(status_code=409, detail="子系统专业 AI 输入类型声明无效")
    actual_kinds = {item.kind for item in inputs}
    if text_input:
        actual_kinds.add("text")
    if context:
        actual_kinds.add("json")
    if not actual_kinds.issubset(set(declared_kinds)):
        raise HTTPException(status_code=422, detail="本次输入类型超出当前页面声明的专业 AI 范围")
    image_count = sum(item.kind == "image" for item in inputs)
    audio_count = sum(item.kind == "audio" for item in inputs)
    text_count = sum(item.kind == "text" for item in inputs) + int(bool(text_input))
    if capability in {"vision.ocr", "vision.classify"} and image_count < 1:
        raise HTTPException(status_code=422, detail="该操作至少需要一张图片")
    if capability == "vision.compare" and image_count < 2:
        raise HTTPException(status_code=422, detail="图片比较至少需要两张图片")
    if capability == "speech.transcribe" and (audio_count != 1 or len(inputs) != 1):
        raise HTTPException(status_code=422, detail="语音转写每次只接受一个音频文件")
    if capability == "text.extract" and text_count < 1:
        raise HTTPException(status_code=422, detail="结构化抽取需要文字输入或文本文件")
    if capability == "business.predict" and not context:
        raise HTTPException(status_code=422, detail="业务预测需要结构化业务数据")


def _fingerprint(payload: dict) -> str:
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


async def create_run(
    db: AsyncSession,
    user: CurrentUser,
    *,
    application_id: UUID,
    module_key: str,
    page_key: str,
    action_key: str,
    capability: str,
    instruction: str,
    context: dict,
    text_input: str,
    request_id: str,
    inputs: list[SubsystemAiInput],
) -> MultimodalJob:
    if not REQUEST_ID_RE.fullmatch(request_id):
        raise HTTPException(status_code=422, detail="request_id 必须是 8–120 位安全标识")
    if len(inputs) > settings.subsystem_ai_max_files:
        raise HTTPException(status_code=422, detail=f"每次最多上传 {settings.subsystem_ai_max_files} 个输入文件")
    if sum(len(item.raw) for item in inputs) > settings.subsystem_ai_max_input_bytes:
        raise HTTPException(status_code=413, detail="专业 AI 输入文件总大小超过平台限制")
    _, _, declaration = await authorize_run(
        db,
        user,
        application_id=application_id,
        module_key=module_key,
        page_key=page_key,
        action_key=action_key,
        capability=capability,
    )
    validate_inputs(capability, declaration, inputs, text_input=text_input, context=context)
    stable_request = {
        "applicationId": str(application_id),
        "moduleKey": module_key,
        "pageKey": page_key,
        "actionKey": action_key,
        "capability": capability,
        "instruction": instruction,
        "context": context,
        "textInput": text_input,
        "inputs": [
            {"name": item.name, "mimeType": item.mime_type, "kind": item.kind, "sha256": item.sha256}
            for item in inputs
        ],
    }
    fingerprint = _fingerprint(stable_request)
    key = f"subsystem-ai:{_fingerprint({'applicationId': str(application_id), 'requestId': request_id})}"
    existing = (await db.execute(select(MultimodalJob).where(
        MultimodalJob.organization_id == user.organization_id,
        MultimodalJob.user_id == UUID(user.id),
        MultimodalJob.idempotency_key == key,
    ))).scalar_one_or_none()
    if existing is not None:
        if existing.params.get("requestFingerprint") != fingerprint:
            raise HTTPException(status_code=409, detail="同一个 request_id 已用于不同的专业 AI 请求")
        return existing
    active = int((await db.scalar(select(func.count(MultimodalJob.id)).where(
        MultimodalJob.user_id == UUID(user.id),
        MultimodalJob.status.in_(["queued", "processing"]),
    ))) or 0)
    if active >= settings.multimodal_user_concurrency:
        raise HTTPException(status_code=429, detail="当前同时运行的 AI 任务过多，请稍后再试")
    job_id = uuid4()
    uploaded: list[dict] = []
    try:
        for index, item in enumerate(inputs):
            suffix = PurePath(item.name).suffix.lower()
            content_ref = await storage_gateway_service.upload_bytes(
                item.raw,
                filename=f"subsystem-ai/{user.organization_id}/{job_id}/{index}{suffix}",
                content_type=item.mime_type,
            )
            uploaded.append({
                "contentRef": content_ref,
                "name": item.name,
                "mimeType": item.mime_type,
                "kind": item.kind,
                "sizeBytes": len(item.raw),
                "sha256": item.sha256,
            })
    except Exception as exc:
        for item in uploaded:
            try:
                await storage_gateway_service.delete_object(item["contentRef"])
            except Exception:
                pass
        raise HTTPException(status_code=503, detail="专业 AI 输入暂存失败，请稍后重试") from exc
    now = datetime.now(UTC)
    job = MultimodalJob(
        id=job_id,
        organization_id=user.organization_id,
        user_id=UUID(user.id),
        department_id=UUID(user.department_id) if user.department_id else None,
        capability=f"platform_ai:{capability}",
        status="queued",
        request_id=request_id,
        idempotency_key=key,
        params={
            **stable_request,
            "requestFingerprint": fingerprint,
            "authEpoch": user.user.auth_epoch,
            "inputObjects": uploaded,
        },
        result={},
        usage={},
        available_at=now,
    )
    db.add(job)
    await db.flush()
    await db.refresh(job)
    return job


def _job_context(job: MultimodalJob) -> tuple[UUID, str, str, str, str]:
    params = job.params or {}
    capability = str(job.capability).removeprefix("platform_ai:")
    try:
        return (
            UUID(str(params["applicationId"])),
            str(params["moduleKey"]),
            str(params["pageKey"]),
            str(params["actionKey"]),
            capability,
        )
    except (KeyError, ValueError, TypeError) as exc:
        raise HTTPException(status_code=409, detail="专业 AI 运行上下文已损坏") from exc


async def require_visible_run(
    db: AsyncSession, user: CurrentUser, run_id: UUID
) -> MultimodalJob:
    job = await db.get(MultimodalJob, run_id)
    if (
        job is None
        or str(job.organization_id) != str(user.organization_id)
        or str(job.user_id) != user.id
        or not str(job.capability).startswith("platform_ai:")
    ):
        raise HTTPException(status_code=404, detail="专业 AI 任务不存在")
    if int((job.params or {}).get("authEpoch", -1)) != int(user.user.auth_epoch):
        raise HTTPException(status_code=403, detail="员工权限已变化，请重新发起专业 AI 操作")
    application_id, module_key, page_key, action_key, capability = _job_context(job)
    await authorize_run(
        db,
        user,
        application_id=application_id,
        module_key=module_key,
        page_key=page_key,
        action_key=action_key,
        capability=capability,
    )
    return job


async def purge_inputs(job: MultimodalJob) -> bool:
    params = dict(job.params or {})
    pending: list[dict] = []
    for item in params.get("inputObjects") or []:
        if not isinstance(item, dict) or not item.get("contentRef"):
            continue
        try:
            await storage_gateway_service.delete_object(str(item["contentRef"]))
        except Exception:
            pending.append(item)
    params["inputObjects"] = pending
    params["inputsPurgedAt"] = datetime.now(UTC).isoformat()
    if pending:
        params["inputCleanupPending"] = True
    else:
        params.pop("inputCleanupPending", None)
    job.params = params
    return not pending


async def cancel_run(db: AsyncSession, user: CurrentUser, run_id: UUID) -> MultimodalJob:
    job = await require_visible_run(db, user, run_id)
    if job.status in {"succeeded", "failed", "cancelled"}:
        return job
    job.status = "cancelled"
    job.finished_at = datetime.now(UTC)
    job.error_category = "cancelled_by_user"
    job.error_detail = "任务已由用户取消"
    await purge_inputs(job)
    await db.flush()
    return job


def run_payload(job: MultimodalJob) -> dict:
    application_id, module_key, page_key, action_key, capability = _job_context(job)
    error = None
    if job.status == "failed":
        error = {
            "code": job.error_category or "subsystem_ai_failed",
            "messageZh": job.error_detail or "专业 AI 处理失败，请稍后重试",
            "retryable": job.error_category in {
                "network_timeout",
                "network_failure",
                "quota_or_rate_limit",
                "provider_service_unavailable",
            },
        }
    elif job.status == "cancelled":
        error = {"code": "cancelled", "messageZh": "任务已取消", "retryable": False}
    return {
        "run_id": job.id,
        "request_id": job.request_id,
        "capability": capability,
        "application_id": application_id,
        "module_key": module_key,
        "page_key": page_key,
        "action_key": action_key,
        "status": job.status,
        "result": job.result or {},
        "error": error,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
        "finished_at": job.finished_at,
    }


def parse_structured_result(content: str, schema: dict) -> tuple[dict, float | None, list[str]]:
    value = content.strip()
    if value.startswith("```"):
        value = re.sub(r"^```(?:json)?\s*|\s*```$", "", value, flags=re.IGNORECASE)
    try:
        payload = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError("模型没有返回有效的结构化 JSON") from exc
    if (
        not isinstance(payload, dict)
        or set(payload) != {"result", "confidence", "warnings"}
        or not isinstance(payload.get("result"), dict)
    ):
        raise ValueError("模型返回缺少结构化 result")
    confidence = payload.get("confidence")
    if (
        isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or not 0 <= confidence <= 1
    ):
        raise ValueError("模型返回的 confidence 无效")
    warnings = payload.get("warnings")
    if not isinstance(warnings, list) or any(not isinstance(item, str) for item in warnings):
        raise ValueError("模型返回的 warnings 无效")
    try:
        validate(instance=payload["result"], schema=schema)
    except SchemaError as exc:
        raise RuntimeError("子系统专业 AI resultSchema 无效") from exc
    except ValidationError as exc:
        raise ValueError(f"模型结果不符合子系统 Schema：{exc.message}") from exc
    return payload["result"], float(confidence), warnings[:20]
