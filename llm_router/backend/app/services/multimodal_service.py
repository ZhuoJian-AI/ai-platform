"""Scoped multimodal provider configuration and safe image preparation."""

from __future__ import annotations

import base64
import hashlib
import io
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from uuid import UUID

from PIL import Image, UnidentifiedImageError
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.llm_provider import LlmProvider
from app.models.organization import Organization
from app.routing.router import find_provider

MAX_IMAGE_COUNT = 5
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_IMAGE_TOTAL_BYTES = 20 * 1024 * 1024
ALLOWED_DIRECT_FORMATS = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}
CONVERT_TO_PNG_FORMATS = {"BMP", "TIFF"}
ALLOWED_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
ALLOWED_IMAGE_SIZES = {
    "256x256", "512x512", "1024x1024", "1024x1536", "1536x1024", "auto",
}
_SCOPE_RANK = {"team": 3, "department": 2, "organization": 1}


@dataclass(frozen=True)
class PreparedImage:
    file_id: str
    name: str
    mime_type: str
    raw: bytes
    width: int
    height: int
    sha256: str

    @property
    def data_url(self) -> str:
        encoded = base64.b64encode(self.raw).decode("ascii")
        return f"data:{self.mime_type};base64,{encoded}"


@dataclass(frozen=True)
class ScopedModel:
    provider: LlmProvider
    model: str


def validate_provider_config(config: dict | None, supported_models: list[str] | None = None) -> dict:
    """Validate and normalize the additive multimodal section of provider.config."""
    value = dict(config or {})
    capabilities = value.get("model_capabilities") or {}
    if not isinstance(capabilities, dict):
        raise ValueError("config.model_capabilities must be an object")
    normalized_caps: dict[str, dict] = {}
    for model, capability in capabilities.items():
        if not isinstance(model, str) or not model.strip() or not isinstance(capability, dict):
            raise ValueError("each model_capabilities entry must be a named object")
        normalized_caps[model.strip()] = {**capability, "vision": bool(capability.get("vision", False))}
    value["model_capabilities"] = normalized_caps

    fallback = value.get("vision_fallback_model")
    if fallback is not None and not isinstance(fallback, str):
        raise ValueError("config.vision_fallback_model must be a string or null")
    fallback = fallback.strip() if isinstance(fallback, str) else ""
    value["vision_fallback_model"] = fallback or None

    generation = value.get("image_generation") or {}
    if not isinstance(generation, dict):
        raise ValueError("config.image_generation must be an object")
    enabled = bool(generation.get("enabled", False))
    model = str(generation.get("model") or "").strip()
    endpoint = str(generation.get("endpoint_path") or "/images/generations").strip()
    size = str(generation.get("default_size") or "1024x1024").strip()
    if enabled and not model:
        raise ValueError("config.image_generation.model is required when enabled")
    if not endpoint.startswith("/") or "://" in endpoint or ".." in endpoint:
        raise ValueError("config.image_generation.endpoint_path must be a safe relative path")
    if size not in ALLOWED_IMAGE_SIZES and not re.fullmatch(r"\d{2,5}x\d{2,5}", size):
        raise ValueError("config.image_generation.default_size is invalid")
    value["image_generation"] = {
        **generation,
        "enabled": enabled,
        "model": model or None,
        "endpoint_path": endpoint,
        "default_size": size,
    }

    declared = set(supported_models or [])
    referenced = set(normalized_caps)
    if fallback:
        referenced.add(fallback)
    if model:
        referenced.add(model)
    if declared and not referenced.issubset(declared):
        missing = ", ".join(sorted(referenced - declared))
        raise ValueError(f"multimodal models must be present in supported_models: {missing}")
    return value


def provider_model_supports_vision(provider: LlmProvider, model: str) -> bool:
    capabilities = (provider.config or {}).get("model_capabilities") or {}
    return bool(isinstance(capabilities, dict) and (capabilities.get(model) or {}).get("vision"))


def provider_image_generation_model(provider: LlmProvider) -> str | None:
    generation = (provider.config or {}).get("image_generation") or {}
    if not isinstance(generation, dict) or not generation.get("enabled"):
        return None
    model = str(generation.get("model") or "").strip()
    return model or None


def _scope_clause(dept_id: str | UUID | None, team_id: str | UUID | None):
    branches = [LlmProvider.scope_type == "organization"]
    if dept_id:
        branches.append((LlmProvider.scope_type == "department") & (LlmProvider.department_id == str(dept_id)))
    if team_id:
        branches.append((LlmProvider.scope_type == "team") & (LlmProvider.team_id == str(team_id)))
    return or_(*branches)


async def visible_providers(
    db: AsyncSession, org_id: UUID, *, dept_id: str | UUID | None = None,
    team_id: str | UUID | None = None,
) -> list[LlmProvider]:
    rows = list((await db.execute(select(LlmProvider).where(
        LlmProvider.organization_id == org_id,
        LlmProvider.is_active.is_(True),
        LlmProvider.deleted_at.is_(None),
        LlmProvider.health_status != "down",
        _scope_clause(dept_id, team_id),
    ))).scalars().all())
    rows.sort(key=lambda p: (_SCOPE_RANK.get(p.scope_type, 0), p.priority), reverse=True)
    return rows


async def organization_feature_flags(db: AsyncSession, org_id: UUID) -> tuple[bool, bool]:
    organization = await db.get(Organization, org_id)
    if organization is None:
        return False, False
    return (
        settings.multimodal_vision_enabled_for(organization.slug),
        settings.image_generation_enabled_for(organization.slug),
    )


async def resolve_vision_fallback(
    db: AsyncSession, org_id: UUID, *, dept_id: str | UUID | None = None,
    team_id: str | UUID | None = None,
) -> ScopedModel | None:
    vision_enabled, _ = await organization_feature_flags(db, org_id)
    if not vision_enabled:
        return None
    for provider in await visible_providers(db, org_id, dept_id=dept_id, team_id=team_id):
        deployments = sorted(
            [
                item for item in (provider.model_deployments or [])
                if item.is_active and item.deleted_at is None
                and item.verification_status in {"verified", "legacy"}
                and "vision" in (item.capabilities or [])
            ],
            key=lambda item: item.routing_priority,
            reverse=True,
        )
        if deployments:
            from app.services.llm_provider_service import effective_provider
            return ScopedModel(
                provider=effective_provider(provider, deployments[0]),
                model=deployments[0].model_id,
            )
        if provider.provider_type == "anthropic":
            continue
        model = str((provider.config or {}).get("vision_fallback_model") or "").strip()
        if model and (not provider.supported_models or model in provider.supported_models):
            return ScopedModel(provider=provider, model=model)
    return None


async def resolve_image_generation(
    db: AsyncSession, org_id: UUID, *, dept_id: str | UUID | None = None,
    team_id: str | UUID | None = None,
) -> ScopedModel | None:
    _, generation_enabled = await organization_feature_flags(db, org_id)
    if not generation_enabled:
        return None
    for provider in await visible_providers(db, org_id, dept_id=dept_id, team_id=team_id):
        deployments = sorted(
            [
                item for item in (provider.model_deployments or [])
                if item.is_active and item.deleted_at is None
                and item.verification_status in {"verified", "legacy"}
                and "image_generation" in (item.capabilities or [])
            ],
            key=lambda item: item.routing_priority,
            reverse=True,
        )
        if deployments:
            return ScopedModel(
                # Keep the provider together with its loaded deployment list.
                # ``model_gateway.generate_image`` selects the capability adapter
                # from that relationship and applies the deployment-specific
                # endpoint itself.  Returning an already-effective transient
                # provider here drops the relationship and incorrectly falls
                # back to the legacy OpenAI Images endpoint.
                provider=provider,
                model=deployments[0].model_id,
            )
        if provider.provider_type == "anthropic":
            continue
        model = provider_image_generation_model(provider)
        if model and (not provider.supported_models or model in provider.supported_models):
            return ScopedModel(provider=provider, model=model)
    return None


async def model_capabilities_for_scope(
    db: AsyncSession, org_id: UUID, models: list[str], *, dept_id: str | UUID | None = None,
    team_id: str | UUID | None = None,
) -> dict[str, dict[str, bool]]:
    vision_enabled, _ = await organization_feature_flags(db, org_id)
    if not vision_enabled:
        return {model: {"vision": False} for model in models}
    capabilities: dict[str, dict[str, bool]] = {}
    providers = await visible_providers(db, org_id, dept_id=dept_id, team_id=team_id)
    for model in models:
        deployment = next((
            item
            for provider in providers
            for item in (provider.model_deployments or [])
            if item.model_id == model and item.is_active and item.deleted_at is None
            and item.verification_status in {"verified", "legacy"}
            and "chat" in (item.capabilities or [])
        ), None)
        if deployment is not None:
            capabilities[model] = {"vision": "vision" in (deployment.capabilities or [])}
            continue
        provider = await find_provider(db, org_id, model, dept_id=dept_id, team_id=team_id)
        capabilities[model] = {
            "vision": bool(
                provider and provider.provider_type != "anthropic"
                and provider_model_supports_vision(provider, model)
            ),
        }
    return capabilities


def prepare_image_bytes(*, file_id: str, name: str, declared_mime: str | None, raw: bytes) -> PreparedImage:
    """Validate extension, MIME and magic bytes; normalize BMP/TIFF to PNG."""
    if not raw:
        raise ValueError(f"图片 {name} 为空")
    if len(raw) > MAX_IMAGE_BYTES:
        raise ValueError(f"图片 {name} 超过 5MB 限制")
    suffix = PurePosixPath(name).suffix.lower()
    if suffix not in ALLOWED_IMAGE_SUFFIXES:
        raise ValueError(f"不支持的图片类型：{suffix or '未知'}")
    try:
        with Image.open(io.BytesIO(raw)) as opened:
            fmt = (opened.format or "").upper()
            width, height = opened.size
            opened.verify()
        if fmt in CONVERT_TO_PNG_FORMATS:
            with Image.open(io.BytesIO(raw)) as opened:
                converted = opened.convert("RGBA" if "A" in opened.getbands() else "RGB")
                buf = io.BytesIO()
                converted.save(buf, format="PNG")
                raw = buf.getvalue()
            mime = "image/png"
        elif fmt in ALLOWED_DIRECT_FORMATS:
            mime = ALLOWED_DIRECT_FORMATS[fmt]
        else:
            raise ValueError(f"不支持的图片文件魔数：{fmt or '未知'}")
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError(f"图片 {name} 已损坏或格式无效") from exc
    if declared_mime and declared_mime.startswith("image/"):
        declared = declared_mime.lower()
        compatible = {mime}
        if mime == "image/jpeg":
            compatible.add("image/jpg")
        if fmt not in CONVERT_TO_PNG_FORMATS and declared not in compatible:
            raise ValueError(f"图片 {name} 的 MIME 与实际格式不一致")
    return PreparedImage(
        file_id=file_id, name=name, mime_type=mime, raw=raw, width=width, height=height,
        sha256=hashlib.sha256(raw).hexdigest(),
    )


def ensure_image_batch_limits(images: list[PreparedImage]) -> None:
    if len(images) > MAX_IMAGE_COUNT:
        raise ValueError(f"每轮最多发送 {MAX_IMAGE_COUNT} 张图片")
    if sum(len(image.raw) for image in images) > MAX_IMAGE_TOTAL_BYTES:
        raise ValueError("本轮图片合计超过 20MB 限制")


def normalize_generated_png(raw: bytes) -> tuple[bytes, int, int]:
    """Validate a generated image and normalize it to a real PNG artifact."""
    if not raw or len(raw) > MAX_IMAGE_BYTES:
        raise ValueError("生成图片为空或超过 5MB 限制")
    try:
        with Image.open(io.BytesIO(raw)) as opened:
            opened.load()
            width, height = opened.size
            converted = opened.convert("RGBA" if "A" in opened.getbands() else "RGB")
            output = io.BytesIO()
            converted.save(output, format="PNG", optimize=True)
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError("生图模型返回的内容不是有效图片") from exc
    normalized = output.getvalue()
    if len(normalized) > MAX_IMAGE_BYTES:
        raise ValueError("生成图片转换为 PNG 后超过 5MB 限制")
    return normalized, width, height
