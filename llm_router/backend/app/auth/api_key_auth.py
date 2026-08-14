"""API Key authentication — extract and verify hierarchical keys from request headers."""

import re
from dataclasses import dataclass
from uuid import UUID

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.api_key import ApiKey
from app.services.api_key_service import validate_api_key

# 合法的 lr_sk_{scope}_{32chars}，scope 为 organization/department/team
API_KEY_PATTERN = re.compile(r"^lr_sk_(organization|department|team)_[a-zA-Z0-9]{32}$")


@dataclass
class AuthenticatedKey:
    """解析并验证后的 API Key 上下文。"""
    api_key: ApiKey
    organization_id: UUID
    department_id: UUID | None
    team_id: UUID | None
    scope_type: str


def extract_api_key(request: Request) -> str:
    """从请求头中提取 API Key，兼容 Anthropic 和 OpenAI 协议。

    Anthropic: x-api-key header
    OpenAI: Authorization: Bearer <key>
    """
    # 优先 Anthropic header
    anthropic_key = request.headers.get("x-api-key")
    if anthropic_key and anthropic_key.startswith("lr_sk_"):
        return anthropic_key

    # 其次 OpenAI Bearer token
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
        if token.startswith("lr_sk_"):
            return token

    raise HTTPException(status_code=401, detail="Missing or invalid API key")


async def authenticate_request(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> AuthenticatedKey:
    """FastAPI 依赖：提取、验证 API Key 并返回认证上下文。"""
    raw_key = extract_api_key(request)

    # 格式校验
    if not API_KEY_PATTERN.match(raw_key):
        raise HTTPException(status_code=401, detail="Invalid API key format")

    api_key = await validate_api_key(db, raw_key)
    if api_key is None:
        raise HTTPException(status_code=401, detail="Invalid or revoked API key")

    return AuthenticatedKey(
        api_key=api_key,
        organization_id=api_key.organization_id,
        department_id=api_key.department_id,
        team_id=api_key.team_id,
        scope_type=api_key.scope_type,
    )
