"""LLM Provider service — CRUD and health checks."""

from datetime import UTC
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.llm_provider import LlmProvider
from app.schemas.llm_provider import LlmProviderCreate, LlmProviderUpdate
from app.utils.crypto import decrypt_provider_api_key, encrypt_provider_api_key


async def create_provider(
    db: AsyncSession,
    org_id: UUID,
    data: LlmProviderCreate,
    dept_id: UUID | None = None,
    team_id: UUID | None = None,
) -> LlmProvider:
    encrypted_key = encrypt_provider_api_key(data.api_key)
    provider = LlmProvider(
        organization_id=org_id,
        name=data.name,
        provider_type=data.provider_type,
        scope_type=data.scope_type,
        department_id=dept_id,
        team_id=team_id,
        base_url=data.base_url,
        api_key_encrypted=encrypted_key,
        priority=data.priority,
        weight=data.weight,
        timeout_seconds=data.timeout_seconds,
        max_retries=data.max_retries,
        supported_models=data.supported_models,
        config=data.config,
    )
    db.add(provider)
    await db.flush()
    return provider


async def list_providers(db: AsyncSession, org_id: UUID) -> list[LlmProvider]:
    result = await db.execute(
        select(LlmProvider).where(LlmProvider.organization_id == org_id, LlmProvider.deleted_at.is_(None))
    )
    return list(result.scalars().all())


async def get_provider(db: AsyncSession, provider_id: UUID) -> LlmProvider | None:
    result = await db.execute(
        select(LlmProvider).where(LlmProvider.id == provider_id, LlmProvider.deleted_at.is_(None))
    )
    return result.scalar_one_or_none()


async def update_provider(db: AsyncSession, provider: LlmProvider, data: LlmProviderUpdate) -> LlmProvider:
    update_data = data.model_dump(exclude_unset=True)
    if "api_key" in update_data:
        update_data["api_key_encrypted"] = encrypt_provider_api_key(update_data.pop("api_key"))
        provider.api_key_version += 1
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
