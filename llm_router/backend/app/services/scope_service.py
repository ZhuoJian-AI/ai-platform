"""Scope service — resolve a terminal user's effective resource scope.

资源（Agent / Workspace）按 ``scope_type`` + ``scope_id`` 分级。工作空间仍兼容
历史 role scope；文本智能体只允许 organization / department / user 三种作用域。

「自动匹配全部」= 用户有效 scope 集合内的资源并集。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.agent import Agent
from app.models.api_key import ApiKey
from app.models.department import Department
from app.models.organization import Organization
from app.models.role import Role
from app.models.user import User
from app.models.workspace import Workspace
from app.services import multimodal_service, workspace_permission_service

if TYPE_CHECKING:
    from app.auth.user_auth import CurrentUser


def department_scope_ids(cu: CurrentUser) -> tuple[str, ...]:
    """Return primary plus role-derived department data scopes.

    The user's organization membership still has exactly one department.  The
    additional ids are query scopes resolved from roles, not extra memberships.
    """
    values = {str(value) for value in (getattr(cu, "department_ids", ()) or ()) if value}
    primary = getattr(cu, "department_id", None)
    if primary:
        values.add(str(primary))
    data_scope = getattr(cu, "effective_data_scopes", None) or {}
    values.update(str(value) for value in (data_scope.get("department_ids") or ()) if value)
    return tuple(sorted(values))


def has_unrestricted_data_scope(cu: CurrentUser) -> bool:
    """Whether an active role grants all department-owned data in this tenant."""
    return bool((getattr(cu, "effective_data_scopes", None) or {}).get("unrestricted"))


def effective_scope_set(cu: CurrentUser) -> list[tuple[str, str | None]]:
    """返回用户有效 scope 集合 [(scope_type, scope_id), ...]。

    organization 级 scope_id 为 None；department/user/role 级为对应 id。
    """
    scopes: list[tuple[str, str | None]] = [("organization", None)]
    scopes.extend(("department", department_id) for department_id in department_scope_ids(cu))
    scopes.append(("user", cu.id))
    scopes.extend(("role", role_id) for role_id in (getattr(cu, "role_ids", ()) or ()))
    return scopes


def scope_filter(model, cu: CurrentUser):
    """构造 ``model`` 的可见性 WHERE 条件（组织、部门、角色、个人）。"""
    conds = [model.scope_type == "organization"]
    department_ids = department_scope_ids(cu)
    if has_unrestricted_data_scope(cu):
        conds.append(model.scope_type == "department")
    elif department_ids:
        conds.append((model.scope_type == "department") & (model.scope_id.in_(department_ids)))
    role_ids = tuple(getattr(cu, "role_ids", ()) or ())
    if role_ids:
        conds.append((model.scope_type == "role") & (model.scope_id.in_(role_ids)))
    conds.append((model.scope_type == "user") & (model.scope_id == cu.id))
    return or_(*conds)


VALID_SCOPE_TYPES = {"organization", "department", "user", "role"}


async def validate_scope_target(
    db: AsyncSession,
    org_id: UUID | str,
    scope_type: str,
    scope_id: str | UUID | None,
) -> str | None:
    """Validate a tenant-owned authorization scope."""
    if scope_type not in VALID_SCOPE_TYPES:
        raise HTTPException(status_code=422, detail="作用域类型无效")
    sid = str(scope_id) if scope_id else None
    if scope_type == "organization":
        if sid:
            raise HTTPException(status_code=422, detail="企业级智能体不能设置 scope_id")
        return None
    if not sid:
        raise HTTPException(status_code=422, detail="该作用域必须指定 scope_id")
    model = {"department": Department, "user": User, "role": Role}[scope_type]
    row = (await db.execute(select(model).where(
        model.id == UUID(sid),
        model.organization_id == UUID(str(org_id)),
        model.deleted_at.is_(None),
    ))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=422, detail="所选作用域不属于当前企业")
    return sid


async def validate_agent_scope_target(
    db: AsyncSession,
    org_id: UUID | str,
    scope_type: str,
    scope_id: str | UUID | None,
) -> str | None:
    """Text personas support only enterprise, department and personal scopes."""
    if scope_type not in {"organization", "department", "user"}:
        raise HTTPException(status_code=422, detail="智能体作用域只支持企业、部门或个人")
    return await validate_scope_target(db, org_id, scope_type, scope_id)


async def validate_user_membership(
    db: AsyncSession,
    org_id: UUID | str,
    department_id: UUID | None,
) -> None:
    """Ensure the selected primary department belongs to the user's enterprise."""
    if department_id is None:
        return
    department = (await db.execute(select(Department).where(
        Department.id == department_id,
        Department.organization_id == UUID(str(org_id)),
        Department.deleted_at.is_(None),
    ))).scalar_one_or_none()
    if department is None:
        raise HTTPException(status_code=422, detail="所选主部门不属于当前企业")


async def validate_user_departments(
    db: AsyncSession,
    org_id: UUID | str,
    department_ids: list[UUID],
) -> None:
    """Ensure all department references stay inside one enterprise."""
    unique_ids = set(department_ids)
    if not unique_ids:
        return
    rows = set((await db.execute(select(Department.id).where(
        Department.id.in_(unique_ids),
        Department.organization_id == UUID(str(org_id)),
        Department.deleted_at.is_(None),
    ))).scalars().all())
    if rows != unique_ids:
        raise HTTPException(status_code=422, detail="所选部门中存在不属于当前企业的部门")


async def list_workspaces_for_user(db: AsyncSession, cu: CurrentUser) -> list[Workspace]:
    """Return only workspaces readable under the dedicated role matrix.

    Generic role data_scope still governs business records and other scoped
    resources, but it must not silently broaden workspace-file visibility.
    """
    stmt = select(Workspace).where(
        Workspace.organization_id == cu.organization_id,
        Workspace.deleted_at.is_(None),
        Workspace.is_active.is_(True),
    )
    rows = list((await db.execute(stmt)).scalars().all())
    workspaces = [
        workspace for workspace in rows
        if (await workspace_permission_service.capabilities(db, workspace, cu))["read"]
    ]
    department_rows = list((await db.execute(select(Department).where(
        Department.organization_id == cu.organization_id,
        Department.deleted_at.is_(None),
    ))).scalars().all())
    department_order = {str(department.id): department.sort_order for department in department_rows}
    scope_order = {"organization": 0, "department": 1, "role": 2, "user": 3}
    return sorted(workspaces, key=lambda workspace: (
        scope_order.get(workspace.scope_type, 4),
        department_order.get(str(workspace.scope_id), 0)
        if workspace.scope_type == "department" else 0,
        workspace.created_at,
        str(workspace.id),
    ))


async def list_agents_for_user(db: AsyncSession, cu: CurrentUser) -> list[Agent]:
    """用户可见的活跃智能体（企业、部门和个人范围取并集）。

    供终端「选智能体」下拉：返回 Agent 行（已加 scope_type/scope_id 列），
    仅 is_active 且未删除者。终端选中后以 template_agent_id 逐次覆盖运行（不落库）。
    """
    stmt = select(Agent).where(
        Agent.organization_id == cu.organization_id,
        Agent.deleted_at.is_(None),
        Agent.is_active.is_(True),
        scope_filter(Agent, cu),
    )
    return list((await db.execute(stmt)).scalars().all())


async def get_user_workspace(db: AsyncSession, cu: CurrentUser) -> Workspace | None:
    """用户的个人工作空间（scope_type=user，scope_id=用户 id）。终端默认工作空间取此。"""
    stmt = select(Workspace).where(
        Workspace.organization_id == cu.organization_id,
        Workspace.scope_type == "user",
        Workspace.scope_id == cu.id,
        Workspace.is_active.is_(True),
        Workspace.deleted_at.is_(None),
    )
    return (await db.execute(stmt)).scalar_one_or_none()


def is_workspace_visible(ws: Workspace, cu: CurrentUser) -> bool:
    """Runtime read check using the dedicated workspace role matrix."""
    return workspace_permission_service.is_workspace_readable(ws, cu)


async def list_api_keys_for_user(db: AsyncSession, cu: CurrentUser) -> list[ApiKey]:
    """用户可访问的活跃 API Key（组织级 + 获权部门；未过期、未吊销）。"""
    now = datetime.now(UTC)
    conds: list = [ApiKey.scope_type == "organization"]
    department_ids = department_scope_ids(cu)
    if has_unrestricted_data_scope(cu):
        conds.append(ApiKey.scope_type == "department")
    elif department_ids:
        conds.append((ApiKey.scope_type == "department") & (ApiKey.department_id.in_(department_ids)))
    stmt = select(ApiKey).where(
        ApiKey.organization_id == cu.organization_id,
        ApiKey.is_active.is_(True),
        ApiKey.revoked_at.is_(None),
        or_(ApiKey.expires_at.is_(None), ApiKey.expires_at > now),
        or_(*conds),
    )
    return list((await db.execute(stmt)).scalars().all())


async def list_available_models_for_user(
    db: AsyncSession, cu: CurrentUser,
) -> list[str]:
    """用户可用的模型名（按可访问 API Key 聚合，embedding 模型已过滤）。

    模型名按可访问 API Key 聚合：任一 Key 的 ``allowed_models`` 为空（= 不限模型）→ 组织全部
    活跃 provider 的 ``supported_models`` 并集；否则 → 各 Key 的 ``allowed_models`` 并集。
    返回的模型名可直接填入 ``TaskConfig.model_alias``（真实模型 id，或 "default" 走组织默认路由）。

    embedding 类模型（名字含 ``embed``，不区分大小写）一律过滤——任务配置只关心对话/生成类模型。
    """
    keys = await list_api_keys_for_user(db, cu)

    providers = await multimodal_service.visible_providers(
        db, cu.organization_id, dept_id=cu.department_id,
    )
    organization = await db.get(Organization, cu.organization_id)
    allow_new_gateway = bool(
        organization
        and settings.model_gateway_enabled_for(
            organization.slug, organization_id=organization.id
        )
    )
    provider_models: list[str] = []
    for p in providers:
        configured_deployments = [
            deployment for deployment in (p.model_deployments or [])
            if deployment.deleted_at is None
        ]
        declared = [
            deployment.model_id for deployment in configured_deployments
            if deployment.is_active
            and (
                deployment.verification_status == "legacy"
                or (allow_new_gateway and deployment.verification_status == "verified")
            )
            and "chat" in (deployment.capabilities or [])
        ]
        if configured_deployments:
            # An explicit deployment is the routing source of truth.  Do not
            # expose its legacy ``supported_models`` shadow while verification
            # is pending or failed: the task picker must never offer a model
            # that the gateway will reject at run time.
            provider_models.extend(declared)
        else:
            # Pre-gateway providers retain the old conservative name filter.
            provider_models.extend(
                model for model in (p.supported_models or []) if "embed" not in model.lower()
            )

    if any(not k.allowed_models for k in keys):
        # 存在不限模型的 Key → 用户可调用 provider 全集
        models = sorted(set(provider_models))
    else:
        models = sorted({m for k in keys for m in (k.allowed_models or []) if m in set(provider_models)})

    # 过滤 embedding 模型：任务配置只列对话/生成类，避免误选无法 chat 的嵌入模型
    generation_models = {
        deployment.model_id
        for provider in providers
        for deployment in (provider.model_deployments or [])
        if "image_generation" in (deployment.capabilities or [])
    } | {
        model for provider in providers
        if (model := multimodal_service.provider_image_generation_model(provider))
    }
    return [m for m in models if m not in generation_models]


async def terminal_model_capabilities(db: AsyncSession, cu: CurrentUser, models: list[str]) -> dict:
    """Return additive multimodal metadata without changing the legacy models array."""
    capabilities = await multimodal_service.model_capabilities_for_scope(
        db, cu.organization_id, models, dept_id=cu.department_id,
    )
    fallback = await multimodal_service.resolve_vision_fallback(
        db, cu.organization_id, dept_id=cu.department_id,
    )
    image_generation = await multimodal_service.resolve_image_generation(
        db, cu.organization_id, dept_id=cu.department_id,
    )
    return {
        "capabilities": capabilities,
        "vision_fallback_available": fallback is not None,
        "image_generation_available": image_generation is not None,
    }
