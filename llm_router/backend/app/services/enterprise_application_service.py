"""CRUD and centralized authorization for embedded tenant applications."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload, with_loader_criteria

from app.auth.user_auth import CurrentUser
from app.models.connector import ToolConnector, ToolEndpoint
from app.models.data_interface import DataInterface, DataSystem
from app.models.enterprise_application import (
    EnterpriseApplication,
    EnterpriseApplicationGrant,
    EnterpriseApplicationToolBinding,
)
from app.models.skill import SkillFolder
from app.schemas.enterprise_application import (
    EnterpriseApplicationCreate,
    EnterpriseApplicationGrantInput,
    EnterpriseApplicationToolBindingInput,
    EnterpriseApplicationUpdate,
)
from app.services import scope_service, skill_scope_service

PERMISSIONS = {"view", "ai_query", "ai_create", "ai_update", "ai_delete", "export"}
OPERATION_PERMISSION = {
    "query": "ai_query",
    "create": "ai_create",
    "update": "ai_update",
    "delete": "ai_delete",
    "export": "export",
}


def _application_options():
    return (
        selectinload(EnterpriseApplication.grants),
        selectinload(EnterpriseApplication.tool_bindings),
        with_loader_criteria(
            EnterpriseApplicationGrant,
            EnterpriseApplicationGrant.deleted_at.is_(None),
            include_aliases=True,
        ),
        with_loader_criteria(
            EnterpriseApplicationToolBinding,
            EnterpriseApplicationToolBinding.deleted_at.is_(None),
            include_aliases=True,
        ),
    )


async def create_application(
    db: AsyncSession,
    org_id: UUID,
    data: EnterpriseApplicationCreate,
) -> EnterpriseApplication:
    values = data.model_dump(mode="json")
    values["entry_url"] = str(values["entry_url"])
    if values.get("icon_url"):
        values["icon_url"] = str(values["icon_url"])
    row = EnterpriseApplication(organization_id=org_id, **values)
    db.add(row)
    await db.flush()
    return await get_application(db, row.id)  # type: ignore[return-value]


async def list_applications(db: AsyncSession, org_id: UUID) -> list[EnterpriseApplication]:
    result = await db.execute(
        select(EnterpriseApplication)
        .options(*_application_options())
        .where(
            EnterpriseApplication.organization_id == org_id,
            EnterpriseApplication.deleted_at.is_(None),
        )
        .order_by(EnterpriseApplication.sort_order, EnterpriseApplication.created_at)
    )
    return list(result.scalars().unique().all())


async def get_application(db: AsyncSession, app_id: UUID | str) -> EnterpriseApplication | None:
    result = await db.execute(
        select(EnterpriseApplication)
        .options(*_application_options())
        .execution_options(
            populate_existing=True,
        )
        .where(
            EnterpriseApplication.id == UUID(str(app_id)),
            EnterpriseApplication.deleted_at.is_(None),
        )
    )
    return result.scalar_one_or_none()


async def update_application(
    db: AsyncSession,
    row: EnterpriseApplication,
    data: EnterpriseApplicationUpdate,
) -> EnterpriseApplication:
    values = data.model_dump(exclude_unset=True, mode="json")
    for field, value in values.items():
        setattr(row, field, str(value) if field in {"entry_url", "icon_url"} and value else value)
    await db.flush()
    return await get_application(db, row.id)  # type: ignore[return-value]


async def soft_delete_application(db: AsyncSession, row: EnterpriseApplication) -> None:
    now = datetime.now(UTC)
    row.deleted_at = now
    for grant in row.grants:
        grant.deleted_at = now
    for binding in row.tool_bindings:
        binding.deleted_at = now
    await db.flush()


async def replace_grants(
    db: AsyncSession,
    row: EnterpriseApplication,
    grants: list[EnterpriseApplicationGrantInput],
) -> EnterpriseApplication:
    normalized: dict[tuple[str, str | None], list[str]] = {}
    for item in grants:
        sid = await skill_scope_service.validate_scope_target(
            db,
            row.organization_id,
            item.scope_type,
            item.scope_id,
        )
        permissions = [value for value in item.permissions if value in PERMISSIONS]
        if permissions:
            normalized[(item.scope_type, sid)] = permissions

    all_grants = list(
        (
            await db.execute(
                select(EnterpriseApplicationGrant).where(
                    EnterpriseApplicationGrant.application_id == row.id,
                )
            )
        )
        .scalars()
        .all()
    )
    current = {(grant.scope_type, grant.scope_id): grant for grant in all_grants}
    now = datetime.now(UTC)
    for key, grant in current.items():
        if key not in normalized:
            grant.deleted_at = now
        else:
            grant.permissions = normalized[key]
            grant.deleted_at = None
    for (scope_type, scope_id), permissions in normalized.items():
        if (scope_type, scope_id) not in current:
            db.add(
                EnterpriseApplicationGrant(
                    application_id=row.id,
                    organization_id=row.organization_id,
                    scope_type=scope_type,
                    scope_id=scope_id,
                    permissions=permissions,
                )
            )
    await db.flush()
    return await get_application(db, row.id)  # type: ignore[return-value]


async def _assert_binding_target(
    db: AsyncSession,
    org_id: UUID | str,
    item: EnterpriseApplicationToolBindingInput,
) -> None:
    target_id = UUID(str(item.target_id))
    if item.target_type == "tool_endpoint":
        row = (
            await db.execute(
                select(ToolEndpoint)
                .join(ToolConnector)
                .where(
                    ToolEndpoint.id == target_id,
                    ToolEndpoint.deleted_at.is_(None),
                    ToolConnector.organization_id == UUID(str(org_id)),
                    ToolConnector.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
    elif item.target_type == "data_interface":
        row = (
            await db.execute(
                select(DataInterface)
                .join(DataSystem)
                .where(
                    DataInterface.id == target_id,
                    DataInterface.deleted_at.is_(None),
                    DataSystem.organization_id == UUID(str(org_id)),
                    DataSystem.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
    else:
        row = (
            await db.execute(
                select(SkillFolder).where(
                    SkillFolder.id == target_id,
                    SkillFolder.organization_id == UUID(str(org_id)),
                    SkillFolder.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=422, detail="Tool binding target does not belong to this organization")


async def replace_tool_bindings(
    db: AsyncSession,
    row: EnterpriseApplication,
    bindings: list[EnterpriseApplicationToolBindingInput],
) -> EnterpriseApplication:
    normalized: dict[tuple[str, str, str], bool] = {}
    for item in bindings:
        await _assert_binding_target(db, row.organization_id, item)
        normalized[(item.target_type, str(item.target_id), item.operation)] = item.is_active
    all_bindings = list(
        (
            await db.execute(
                select(EnterpriseApplicationToolBinding).where(
                    EnterpriseApplicationToolBinding.application_id == row.id,
                )
            )
        )
        .scalars()
        .all()
    )
    current = {(binding.target_type, binding.target_id, binding.operation): binding for binding in all_bindings}
    now = datetime.now(UTC)
    for key, binding in current.items():
        if key not in normalized:
            binding.deleted_at = now
        else:
            binding.is_active = normalized[key]
            binding.deleted_at = None
    for (target_type, target_id, operation), is_active in normalized.items():
        if (target_type, target_id, operation) not in current:
            db.add(
                EnterpriseApplicationToolBinding(
                    application_id=row.id,
                    organization_id=row.organization_id,
                    target_type=target_type,
                    target_id=target_id,
                    operation=operation,
                    is_active=is_active,
                )
            )
    await db.flush()
    return await get_application(db, row.id)  # type: ignore[return-value]


def effective_permissions(row: EnterpriseApplication, user: CurrentUser) -> set[str]:
    if not row.is_active or row.deleted_at is not None:
        return set()
    scopes = set(scope_service.effective_scope_set(user))
    permissions: set[str] = set()
    for grant in row.grants:
        if grant.deleted_at is None and (grant.scope_type, grant.scope_id or None) in scopes:
            permissions.update(value for value in (grant.permissions or []) if value in PERMISSIONS)
    return permissions


async def list_applications_for_user(
    db: AsyncSession,
    user: CurrentUser,
) -> list[tuple[EnterpriseApplication, set[str]]]:
    rows = await list_applications(db, user.organization_id)
    visible: list[tuple[EnterpriseApplication, set[str]]] = []
    for row in rows:
        permissions = effective_permissions(row, user)
        if "view" in permissions:
            visible.append((row, permissions))
    return visible


async def assert_application_permission(
    db: AsyncSession,
    app_id: UUID | str,
    user: CurrentUser,
    permission: str = "view",
) -> tuple[EnterpriseApplication, set[str]]:
    row = await get_application(db, app_id)
    if row is None or str(row.organization_id) != str(user.organization_id):
        raise HTTPException(status_code=404, detail="Application not found")
    permissions = effective_permissions(row, user)
    if permission not in permissions:
        raise HTTPException(status_code=403, detail=f"Application permission '{permission}' required")
    return row, permissions


async def target_allowed_for_user(
    db: AsyncSession,
    user: CurrentUser,
    target_type: str,
    target_id: UUID | str,
) -> bool:
    """Unbound targets retain legacy scope behavior; bound targets require an app grant."""
    bindings = list(
        (
            await db.execute(
                select(EnterpriseApplicationToolBinding).where(
                    EnterpriseApplicationToolBinding.organization_id == user.organization_id,
                    EnterpriseApplicationToolBinding.target_type == target_type,
                    EnterpriseApplicationToolBinding.target_id == str(target_id),
                    EnterpriseApplicationToolBinding.is_active.is_(True),
                    EnterpriseApplicationToolBinding.deleted_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    if not bindings:
        return True
    app_ids = {binding.application_id for binding in bindings}
    apps = list(
        (
            await db.execute(
                select(EnterpriseApplication)
                .options(*_application_options())
                .where(
                    EnterpriseApplication.id.in_(app_ids),
                    EnterpriseApplication.organization_id == user.organization_id,
                    EnterpriseApplication.is_active.is_(True),
                    EnterpriseApplication.deleted_at.is_(None),
                )
            )
        )
        .scalars()
        .unique()
        .all()
    )
    by_id = {str(app.id): app for app in apps}
    for binding in bindings:
        app = by_id.get(str(binding.application_id))
        if app is None:
            continue
        required = OPERATION_PERMISSION[binding.operation]
        permissions = effective_permissions(app, user)
        if "view" in permissions and required in permissions:
            return True
    return False


async def assert_target_allowed_for_user(
    db: AsyncSession,
    user: CurrentUser,
    target_type: str,
    target_id: UUID | str,
) -> None:
    if not await target_allowed_for_user(db, user, target_type, target_id):
        raise HTTPException(status_code=403, detail="Enterprise application permission required for this tool")
