"""Provider credentials, endpoint presets and model deployment CRUD."""

import re
from copy import deepcopy
from datetime import UTC
from urllib.parse import urlparse
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.llm_provider import LlmProvider, ModelDeployment
from app.schemas.llm_provider import (
    LlmProviderCreate,
    LlmProviderUpdate,
    ModelDeploymentCreate,
    ModelDeploymentUpdate,
)
from app.services.multimodal_service import validate_provider_config
from app.utils.crypto import decrypt_provider_api_key, encrypt_provider_api_key


def _validate_base_url(value: str) -> str:
    normalized = value.strip().rstrip("/")
    parsed = urlparse(normalized)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Base URL must be an HTTPS origin without embedded credentials")
    return normalized


_BAILIAN_WORKSPACE_ID = re.compile(r"^[A-Za-z0-9_-]+$")
_BAILIAN_REGION_HOSTS = {
    "cn-beijing": "cn-beijing",
    "ap-southeast-1": "ap-southeast-1",
    "ap-northeast-1": "ap-northeast-1",
    "eu-central-1": "eu-central-1",
}


def normalize_bailian_workspace_id(value: str | None, region: str | None) -> str | None:
    """Accept either a Bailian workspace ID or its API host and store only the ID.

    The console prominently displays an ``API Host``.  Treating that host as an
    ID used to produce duplicated hosts such as
    ``<host>.cn-beijing.maas.aliyuncs.com``.  Being liberal at this UI boundary
    prevents a valid credential from becoming an invalid endpoint.
    """
    if value is None or not value.strip():
        return None
    selected = region or "cn-beijing"
    host_region = _BAILIAN_REGION_HOSTS.get(selected)
    if host_region is None:
        raise ValueError("Unsupported Bailian region")
    raw = value.strip().rstrip("/")
    parsed = urlparse(raw if "://" in raw else f"//{raw}")
    hostname = parsed.hostname
    suffix = f".{host_region}.maas.aliyuncs.com"
    if hostname and hostname.lower().endswith(suffix):
        if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
            raise ValueError("Bailian workspace must be an ID or API Host without a path")
        raw = hostname[: -len(suffix)]
    if not _BAILIAN_WORKSPACE_ID.fullmatch(raw):
        raise ValueError("Bailian workspace ID contains unsupported characters")
    return raw


def provider_base_url(
    vendor: str, *, region: str | None, workspace_id: str | None,
    provider_type: str, explicit: str | None,
) -> str:
    """Return a production API endpoint without exposing billing credentials."""
    if explicit:
        return _validate_base_url(explicit)
    if vendor == "openai":
        return "https://api.openai.com/v1"
    if vendor == "anthropic":
        return "https://api.anthropic.com"
    if vendor == "volcengine_ark":
        if (region or "cn-beijing") != "cn-beijing":
            raise ValueError(
                "Volcengine Ark currently supports the cn-beijing preset; provide Base URL for another region"
            )
        return "https://ark.cn-beijing.volces.com/api/v3"
    if vendor == "xiaomi_mimo":
        return "https://api.xiaomimimo.com/v1"
    if vendor == "aliyun_bailian":
        selected = region or "cn-beijing"
        workspace_id = normalize_bailian_workspace_id(workspace_id, selected)
        if workspace_id:
            if selected not in _BAILIAN_REGION_HOSTS:
                raise ValueError("Unsupported Bailian region")
            root = f"https://{workspace_id}.{_BAILIAN_REGION_HOSTS[selected]}.maas.aliyuncs.com"
            return f"{root}/apps/anthropic" if provider_type == "anthropic" else f"{root}/compatible-mode/v1"
        if selected == "cn-beijing":
            return (
                "https://dashscope.aliyuncs.com/apps/anthropic"
                if provider_type == "anthropic" else "https://dashscope.aliyuncs.com/compatible-mode/v1"
            )
        if selected == "ap-southeast-1":
            return (
                "https://dashscope-intl.aliyuncs.com/apps/anthropic"
                if provider_type == "anthropic" else "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
            )
        raise ValueError("Bailian workspace_id is required for this region")
    raise ValueError("Base URL is required for custom and Azure providers")


def _legacy_deployments(data: LlmProviderCreate) -> list[ModelDeploymentCreate]:
    if data.model_deployments:
        return data.model_deployments
    caps = (data.config or {}).get("model_capabilities") or {}
    image = (data.config or {}).get("image_generation") or {}
    deployments: list[ModelDeploymentCreate] = []
    for model in data.supported_models:
        if image.get("enabled") and image.get("model") == model:
            deployments.append(ModelDeploymentCreate(
                model_id=model, adapter="openai_images", capabilities=["image_generation"],
                endpoint_path=image.get("endpoint_path") or "/images/generations",
            ))
            continue
        capabilities = ["chat"]
        if (caps.get(model) or {}).get("vision"):
            capabilities.append("vision")
        deployments.append(ModelDeploymentCreate(
            model_id=model,
            adapter="anthropic_messages" if data.provider_type == "anthropic" else "openai_chat_completions",
            capabilities=capabilities,
        ))
    return deployments


def _sync_legacy_config(config: dict, deployments: list[ModelDeploymentCreate]) -> dict:
    """Keep old selectors and multimodal services operational during gateway rollout."""
    value = dict(config or {})
    model_capabilities = dict(value.get("model_capabilities") or {})
    vision_fallback = value.get("vision_fallback_model")
    image_generation = dict(value.get("image_generation") or {})
    for deployment in deployments:
        if "vision" in deployment.capabilities:
            model_capabilities[deployment.model_id] = {
                **(model_capabilities.get(deployment.model_id) or {}),
                "vision": True,
            }
            vision_fallback = vision_fallback or deployment.model_id
        if "image_generation" in deployment.capabilities and not image_generation.get("enabled"):
            image_generation = {
                "enabled": True,
                "model": deployment.model_id,
                "endpoint_path": deployment.endpoint_path or "/images/generations",
                "default_size": str((deployment.config or {}).get("default_size") or "1024x1024"),
            }
    value["model_capabilities"] = model_capabilities
    value["vision_fallback_model"] = vision_fallback
    value["image_generation"] = image_generation or {
        "enabled": False,
        "model": None,
        "endpoint_path": "/images/generations",
        "default_size": "1024x1024",
    }
    return value


async def create_provider(
    db: AsyncSession,
    org_id: UUID,
    data: LlmProviderCreate,
    dept_id: UUID | None = None,
    team_id: UUID | None = None,
) -> LlmProvider:
    workspace_id = (
        normalize_bailian_workspace_id(data.workspace_id, data.region)
        if data.vendor == "aliyun_bailian" else data.workspace_id
    )
    deployments = _legacy_deployments(data)
    declared_models = list(dict.fromkeys([*data.supported_models, *(d.model_id for d in deployments)]))
    normalized_config = validate_provider_config(
        _sync_legacy_config(data.config, deployments), declared_models,
    )
    encrypted_key = encrypt_provider_api_key(data.api_key)
    base_url = provider_base_url(
        data.vendor, region=data.region, workspace_id=workspace_id,
        provider_type=data.provider_type, explicit=data.base_url,
    )
    provider = LlmProvider(
        organization_id=org_id,
        name=data.name,
        vendor=data.vendor,
        provider_type=data.provider_type,
        region=data.region,
        workspace_id=workspace_id,
        scope_type=data.scope_type,
        department_id=dept_id,
        team_id=team_id,
        base_url=base_url,
        api_key_encrypted=encrypted_key,
        priority=data.priority,
        weight=data.weight,
        timeout_seconds=data.timeout_seconds,
        max_retries=data.max_retries,
        supported_models=declared_models,
        config={**normalized_config, "access_mode": data.access_mode},
    )
    db.add(provider)
    await db.flush()
    for deployment in deployments:
        db.add(ModelDeployment(
            provider_id=provider.id,
            **deployment.model_dump(),
            verification_status="legacy" if not data.model_deployments else "unverified",
        ))
    await db.flush()
    await db.refresh(provider)
    return provider


async def list_providers(db: AsyncSession, org_id: UUID) -> list[LlmProvider]:
    result = await db.execute(
        select(LlmProvider)
        .options(selectinload(LlmProvider.model_deployments))
        .where(LlmProvider.organization_id == org_id, LlmProvider.deleted_at.is_(None))
    )
    return list(result.scalars().all())


async def get_provider(db: AsyncSession, provider_id: UUID) -> LlmProvider | None:
    result = await db.execute(
        select(LlmProvider)
        .options(selectinload(LlmProvider.model_deployments))
        .where(LlmProvider.id == provider_id, LlmProvider.deleted_at.is_(None))
    )
    return result.scalar_one_or_none()


async def update_provider(db: AsyncSession, provider: LlmProvider, data: LlmProviderUpdate) -> LlmProvider:
    update_data = data.model_dump(exclude_unset=True)
    if provider.vendor == "aliyun_bailian" and ({"workspace_id", "region"} & update_data.keys()):
        update_data["workspace_id"] = normalize_bailian_workspace_id(
            update_data.get("workspace_id", provider.workspace_id),
            update_data.get("region", provider.region),
        )
    if "api_key" in update_data:
        update_data["api_key_encrypted"] = encrypt_provider_api_key(update_data.pop("api_key"))
        provider.api_key_version += 1
    if "config" in update_data or "supported_models" in update_data:
        update_data["config"] = validate_provider_config(
            update_data.get("config", provider.config),
            update_data.get("supported_models", provider.supported_models),
        )
    if {"base_url", "region", "workspace_id"} & update_data.keys():
        update_data["base_url"] = provider_base_url(
            provider.vendor,
            region=update_data.get("region", provider.region),
            workspace_id=update_data.get("workspace_id", provider.workspace_id),
            provider_type=provider.provider_type,
            explicit=update_data.get("base_url"),
        )
    for field, value in update_data.items():
        setattr(provider, field, value)
    await db.flush()
    # onupdate 会让 updated_at 等服务端生成字段失效，刷新以避免响应序列化时触发同步懒加载（MissingGreenlet）
    await db.refresh(provider)
    return provider


async def soft_delete_provider(db: AsyncSession, provider: LlmProvider) -> None:
    from datetime import datetime
    provider.deleted_at = datetime.now(UTC)
    await db.flush()


async def get_decrypted_api_key(provider: LlmProvider) -> str:
    """获取提供商的解密 API Key。"""
    return decrypt_provider_api_key(provider.api_key_encrypted)


async def list_model_deployments(db: AsyncSession, provider_id: UUID) -> list[ModelDeployment]:
    result = await db.execute(select(ModelDeployment).where(
        ModelDeployment.provider_id == provider_id, ModelDeployment.deleted_at.is_(None),
    ).order_by(ModelDeployment.routing_priority.desc(), ModelDeployment.model_id))
    return list(result.scalars().all())


async def get_model_deployment(db: AsyncSession, deployment_id: UUID) -> ModelDeployment | None:
    result = await db.execute(select(ModelDeployment).where(
        ModelDeployment.id == deployment_id, ModelDeployment.deleted_at.is_(None),
    ))
    return result.scalar_one_or_none()


async def create_model_deployment(
    db: AsyncSession, provider: LlmProvider, data: ModelDeploymentCreate,
) -> ModelDeployment:
    deployment = ModelDeployment(provider_id=provider.id, **data.model_dump(), verification_status="unverified")
    db.add(deployment)
    if data.model_id not in provider.supported_models:
        provider.supported_models = [*provider.supported_models, data.model_id]
    provider.config = validate_provider_config(
        _sync_legacy_config(provider.config, [data]), provider.supported_models,
    )
    await db.flush()
    return deployment


async def _rebuild_provider_legacy_view(db: AsyncSession, provider_id: UUID) -> None:
    """Mirror active deployments into fields still consumed by legacy selectors.

    The gateway is authoritative.  Rebuilding instead of incrementally mutating
    these fields prevents a deleted or edited deployment from reappearing through
    the compatibility path.
    """
    provider = await db.get(LlmProvider, provider_id)
    if provider is None:
        return
    deployments = await list_model_deployments(db, provider_id)
    active = [item for item in deployments if item.is_active]
    provider.supported_models = list(dict.fromkeys(item.model_id for item in active))

    config = dict(provider.config or {})
    config["model_capabilities"] = {}
    config["vision_fallback_model"] = None
    config["image_generation"] = {
        "enabled": False,
        "model": None,
        "endpoint_path": "/images/generations",
        "default_size": "1024x1024",
    }
    declarations = [
        ModelDeploymentCreate(
            model_id=item.model_id,
            display_name=item.display_name,
            adapter=item.adapter,
            capabilities=item.capabilities,
            base_url_override=item.base_url_override,
            endpoint_path=item.endpoint_path,
            embedding_dimensions=item.embedding_dimensions,
            routing_priority=item.routing_priority,
            is_active=item.is_active,
            config=item.config,
        )
        for item in active
    ]
    provider.config = validate_provider_config(
        _sync_legacy_config(config, declarations), provider.supported_models,
    )
    await db.flush()


async def update_model_deployment(
    db: AsyncSession, deployment: ModelDeployment, data: ModelDeploymentUpdate,
) -> ModelDeployment:
    payload = data.model_dump(exclude_unset=True)
    if "adapter" in payload or "capabilities" in payload or "endpoint_path" in payload:
        checked = ModelDeploymentCreate(
            model_id=deployment.model_id,
            adapter=payload.get("adapter", deployment.adapter),
            capabilities=payload.get("capabilities", deployment.capabilities),
            endpoint_path=payload.get("endpoint_path", deployment.endpoint_path),
            base_url_override=payload.get("base_url_override", deployment.base_url_override),
            embedding_dimensions=payload.get("embedding_dimensions", deployment.embedding_dimensions),
            routing_priority=payload.get("routing_priority", deployment.routing_priority),
            is_active=payload.get("is_active", deployment.is_active),
            config=payload.get("config", deployment.config),
        )
        payload.update(checked.model_dump(exclude={"model_id"}))
    for field, value in payload.items():
        setattr(deployment, field, value)
    deployment.verification_status = "unverified"
    deployment.last_error = None
    deployment.config = {**(deployment.config or {}), "verified_capabilities": []}
    await db.flush()
    await _rebuild_provider_legacy_view(db, deployment.provider_id)
    await db.refresh(deployment)
    return deployment


async def delete_model_deployment(db: AsyncSession, deployment: ModelDeployment) -> None:
    from datetime import datetime
    deployment.deleted_at = datetime.now(UTC)
    await db.flush()
    await _rebuild_provider_legacy_view(db, deployment.provider_id)


def effective_provider(provider: LlmProvider, deployment: ModelDeployment) -> LlmProvider:
    """Return a request-local provider copy configured for one deployment adapter."""
    # Do not use ``copy.copy`` on SQLAlchemy mapped instances.  A shallow copy
    # shares the original ``InstanceState``; once the original ORM object is
    # released, assigning a mapped attribute on the copy raises
    # ``parent object ... has been garbage collected``.  This path is commonly
    # hit twice by agent tools (capability resolution, then gateway dispatch),
    # so build a transient mapped instance with independent instrumentation.
    values = {
        column.key: deepcopy(getattr(provider, column.key))
        for column in LlmProvider.__table__.columns
    }
    resolved = LlmProvider(**values)
    resolved.provider_type = "anthropic" if deployment.adapter == "anthropic_messages" else "openai"
    if deployment.base_url_override:
        resolved.base_url = deployment.base_url_override.rstrip("/")
    config = dict(provider.config or {})
    capabilities = dict(config.get("model_capabilities") or {})
    capabilities[deployment.model_id] = {
        **(capabilities.get(deployment.model_id) or {}),
        "vision": "vision" in deployment.capabilities,
    }
    resolved.config = {
        **config,
        "model_capabilities": capabilities,
        "_gateway_deployment_id": str(deployment.id),
        "_gateway_adapter": deployment.adapter,
    }
    return resolved
