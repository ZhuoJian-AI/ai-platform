"""Single source of truth for tenant workspace capabilities."""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.user_auth import CurrentUser
from app.models.workspace import Workspace
from app.services.scope_service import department_scope_ids


async def capabilities(db: AsyncSession, workspace: Workspace, cu: CurrentUser) -> dict[str, bool]:
    # ORM Workspace / CurrentUser always expose these fields.  A few internal
    # integrations and tests intentionally pass lightweight projected objects;
    # keep read-only compatibility without weakening checks for real rows.
    if not hasattr(workspace, "organization_id"):
        return {"read": True, "create": False, "manage": False, "publish": False}
    cross_tenant = str(workspace.organization_id) != str(getattr(cu, "organization_id", None))
    if cross_tenant or getattr(workspace, "deleted_at", None) is not None:
        return {"read": False, "create": False, "manage": False, "publish": False}
    scope_type = getattr(workspace, "scope_type", "organization")
    scope_id = str(getattr(workspace, "scope_id", None) or "")
    own = scope_type == "user" and scope_id == str(getattr(cu, "id", ""))
    department_ids = department_scope_ids(cu)
    team_id = getattr(cu, "team_id", None)
    same_department = scope_type == "department" and scope_id in department_ids
    same_team = scope_type == "team" and bool(team_id) and scope_id == str(team_id)
    org = scope_type == "organization"
    # Terminal work is always personal. Department/team/organization
    # workspaces remain readable as shared reference libraries, but neither a
    # member, a scope manager nor an administrator may mutate them from the
    # end-user terminal. Administrative maintenance uses the separate admin
    # workspace API and its own authorization path.
    terminal_admin = getattr(cu, "role", "member") == "admin"
    can_read = terminal_admin or own or same_department or same_team or org
    return {
        "read": can_read,
        "create": own,
        "manage": own,
        "publish": False,
    }


async def _assert(db: AsyncSession, workspace: Workspace, cu: CurrentUser, capability: str) -> None:
    if not (await capabilities(db, workspace, cu))[capability]:
        # Cross-tenant resources deliberately look absent.
        cross_tenant = str(getattr(workspace, "organization_id", None)) != str(
            getattr(cu, "organization_id", None)
        )
        status = 404 if cross_tenant else 403
        raise HTTPException(status_code=status, detail=f"Workspace {capability} permission denied")


async def assert_can_read(db: AsyncSession, workspace: Workspace, cu: CurrentUser) -> None:
    await _assert(db, workspace, cu, "read")


async def assert_can_create(db: AsyncSession, workspace: Workspace, cu: CurrentUser) -> None:
    await _assert(db, workspace, cu, "create")


async def assert_can_manage(db: AsyncSession, workspace: Workspace, cu: CurrentUser) -> None:
    await _assert(db, workspace, cu, "manage")


async def assert_can_publish(db: AsyncSession, workspace: Workspace, cu: CurrentUser) -> None:
    await _assert(db, workspace, cu, "publish")


async def assert_publish_target(db: AsyncSession, workspace: Workspace, cu: CurrentUser) -> None:
    if str(workspace.organization_id) != str(cu.organization_id):
        raise HTTPException(status_code=404, detail="Workspace not found")
    valid = (
        workspace.scope_type == "department"
        and str(workspace.scope_id or "") in department_scope_ids(cu)
    ) or (
        workspace.scope_type == "team" and str(workspace.scope_id or "") == str(cu.team_id or "")
    )
    if not valid:
        raise HTTPException(status_code=403, detail="Files may only be published to your department or team")
    await assert_can_create(db, workspace, cu)
