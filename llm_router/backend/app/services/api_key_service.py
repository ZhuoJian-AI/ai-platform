"""API Key service — creation, validation, revocation."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.api_key import ApiKey
from app.schemas.api_key import ApiKeyCreate, ApiKeyUpdate
from app.utils.crypto import decrypt_api_key, encrypt_api_key, generate_api_key, hash_api_key


async def create_api_key(
    db: AsyncSession, org_id: UUID, data: ApiKeyCreate, dept_id: UUID | None = None, team_id: UUID | None = None
) -> tuple[ApiKey, str]:
    """创建分层 API Key，返回 (key_record, full_key_plaintext)。"""
    scope = data.scope_type
    full_key, key_prefix, key_hash = generate_api_key(scope)

    api_key = ApiKey(
        key_prefix=key_prefix,
        key_hash=key_hash,
        key_encrypted=encrypt_api_key(full_key),
        key_name=data.key_name,
        scope_type=scope,
        organization_id=org_id,
        department_id=dept_id,
        team_id=team_id,
        allowed_models=data.allowed_models,
        rate_limit_rpm=data.rate_limit_rpm,
        rate_limit_tpm=data.rate_limit_tpm,
        budget_cap_usd=data.budget_cap_usd,
        budget_cap_tokens=data.budget_cap_tokens,
        expires_at=data.expires_at,
    )
    db.add(api_key)
    await db.flush()
    return api_key, full_key


async def validate_api_key(db: AsyncSession, raw_key: str) -> ApiKey | None:
    """验证 API Key —— 根据 prefix 查找并校验 hash。"""
    key_prefix = raw_key[:12]
    key_hash = hash_api_key(raw_key)

    result = await db.execute(
        select(ApiKey).where(
            ApiKey.key_prefix == key_prefix,
            ApiKey.key_hash == key_hash,
            ApiKey.is_active.is_(True),
            ApiKey.revoked_at.is_(None),
        )
    )
    api_key = result.scalar_one_or_none()
    if api_key is None:
        return None

    # 检查是否过期
    if api_key.expires_at and api_key.expires_at < datetime.now(UTC):
        return None

    # 更新最后使用时间（不阻塞主流程）
    api_key.last_used_at = datetime.now(UTC)
    await db.flush()

    return api_key


async def list_api_keys(db: AsyncSession, org_id: UUID) -> list[ApiKey]:
    result = await db.execute(
        select(ApiKey).where(ApiKey.organization_id == org_id, ApiKey.revoked_at.is_(None))
    )
    return list(result.scalars().all())


async def get_api_key(db: AsyncSession, key_id: UUID) -> ApiKey | None:
    result = await db.execute(select(ApiKey).where(ApiKey.id == key_id))
    return result.scalar_one_or_none()


async def update_api_key(db: AsyncSession, api_key: ApiKey, data: ApiKeyUpdate) -> ApiKey:
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(api_key, field, value)
    await db.flush()
    await db.refresh(api_key)
    return api_key


async def revoke_api_key(db: AsyncSession, api_key: ApiKey) -> ApiKey:
    api_key.revoked_at = datetime.now(UTC)
    api_key.is_active = False
    await db.flush()
    await db.refresh(api_key)
    return api_key


def get_decrypted_key(api_key: ApiKey) -> str:
    """解密 API Key 的完整明文。旧 Key 可能无密文，返回空串。"""
    if not api_key.key_encrypted:
        return ""
    return decrypt_api_key(api_key.key_encrypted)
