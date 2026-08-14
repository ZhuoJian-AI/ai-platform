"""Tool connector & endpoint service — CRUD + spec import."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.connector import ToolConnector, ToolEndpoint
from app.schemas.connector import (
    ToolConnectorCreate,
    ToolConnectorUpdate,
    ToolEndpointCreate,
    ToolEndpointUpdate,
)
from app.tools.executor import encrypt_auth_config
from app.tools.spec_parser import parse_spec

# ── Connector ──

async def create_connector(db: AsyncSession, org_id: UUID, data: ToolConnectorCreate) -> ToolConnector:
    conn = ToolConnector(
        organization_id=org_id,
        name=data.name,
        slug=data.slug,
        description=data.description,
        type=data.type,
        base_url=data.base_url,
        auth_type=data.auth_type,
        auth_config_encrypted=encrypt_auth_config(data.auth_config) if data.auth_config else "",
        spec=data.spec,
        is_active=data.is_active,
    )
    db.add(conn)
    await db.flush()
    return conn


async def list_connectors(db: AsyncSession, org_id: UUID) -> list[ToolConnector]:
    result = await db.execute(
        select(ToolConnector).where(ToolConnector.organization_id == org_id, ToolConnector.deleted_at.is_(None))
    )
    return list(result.scalars().all())


async def get_connector(db: AsyncSession, conn_id: UUID) -> ToolConnector | None:
    result = await db.execute(
        select(ToolConnector).where(ToolConnector.id == conn_id, ToolConnector.deleted_at.is_(None))
    )
    return result.scalar_one_or_none()


async def update_connector(db: AsyncSession, conn: ToolConnector, data: ToolConnectorUpdate) -> ToolConnector:
    d = data.model_dump(exclude_unset=True)
    if "auth_config" in d:
        cfg = d.pop("auth_config")
        conn.auth_config_encrypted = encrypt_auth_config(cfg) if cfg else ""
    for field, value in d.items():
        setattr(conn, field, value)
    await db.flush()
    await db.refresh(conn)
    return conn


async def soft_delete_connector(db: AsyncSession, conn: ToolConnector) -> None:
    conn.deleted_at = datetime.now(UTC)
    await db.flush()


async def import_spec(db: AsyncSession, conn: ToolConnector) -> list[ToolEndpoint]:
    """从连接器 spec 解析并创建 ToolEndpoint（已存在同名跳过）。返回新建/更新的端点。"""
    endpoints = parse_spec(conn.spec or {})
    created: list[ToolEndpoint] = []
    for ep in endpoints:
        # 查同名（同 connector + name）
        existing = await db.execute(
            select(ToolEndpoint).where(
                ToolEndpoint.connector_id == conn.id,
                ToolEndpoint.name == ep["name"],
                ToolEndpoint.deleted_at.is_(None),
            )
        )
        row = existing.scalar_one_or_none()
        if row is None:
            row = ToolEndpoint(
                connector_id=conn.id,
                name=ep["name"],
                method=ep["method"],
                path=ep["path"],
                description=ep["description"],
                params_schema=ep["params_schema"],
                response_schema=ep["response_schema"],
            )
            db.add(row)
        else:
            row.method = ep["method"]
            row.path = ep["path"]
            row.description = ep["description"]
            row.params_schema = ep["params_schema"]
            row.response_schema = ep["response_schema"]
        created.append(row)
    await db.flush()
    return created


# ── Endpoint ──

async def list_endpoints(db: AsyncSession, conn_id: UUID) -> list[ToolEndpoint]:
    result = await db.execute(
        select(ToolEndpoint).where(ToolEndpoint.connector_id == conn_id, ToolEndpoint.deleted_at.is_(None))
    )
    return list(result.scalars().all())


async def create_endpoint(db: AsyncSession, conn: ToolConnector, data: ToolEndpointCreate) -> ToolEndpoint:
    ep = ToolEndpoint(connector_id=conn.id, **data.model_dump())
    db.add(ep)
    await db.flush()
    return ep


async def get_endpoint(db: AsyncSession, ep_id: UUID) -> ToolEndpoint | None:
    result = await db.execute(
        select(ToolEndpoint).where(ToolEndpoint.id == ep_id, ToolEndpoint.deleted_at.is_(None))
    )
    return result.scalar_one_or_none()


async def update_endpoint(db: AsyncSession, ep: ToolEndpoint, data: ToolEndpointUpdate) -> ToolEndpoint:
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(ep, field, value)
    await db.flush()
    await db.refresh(ep)
    return ep


async def soft_delete_endpoint(db: AsyncSession, ep: ToolEndpoint) -> None:
    ep.deleted_at = datetime.now(UTC)
    await db.flush()
