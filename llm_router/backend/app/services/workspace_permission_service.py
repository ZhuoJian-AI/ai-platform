"""Single source of truth for tenant workspace capabilities."""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.user_auth import CurrentUser
from app.models.workspace import Workspace

DEPARTMENT_READ_PREFIX = "workspace.department.read:"
DEPARTMENT_UPLOAD_PREFIX = "workspace.department.upload:"


def department_workspace_scope_ids(cu: CurrentUser) -> tuple[str, ...]:
    """Return departments explicitly exposed to the user by role permissions."""
    department_ids: set[str] = set()
    for code in set(getattr(cu, "permission_codes", ()) or ()):
        for prefix in (DEPARTMENT_READ_PREFIX, DEPARTMENT_UPLOAD_PREFIX):
            if code.startswith(prefix):
                department_id = code.removeprefix(prefix).strip()
                if department_id:
                    department_ids.add(department_id)
    return tuple(sorted(department_ids))


def _department_workspace_access(cu: CurrentUser, department_id: str) -> tuple[bool, bool]:
    """Return explicit role-based read/upload access for one department.

    Department membership is identity, not a permission bundle.  A user's
    primary department is readable by default; shared writes and cross-
    department access must be granted by one of the user's roles.
    """
    codes = set(getattr(cu, "permission_codes", ()) or ())
    can_upload = f"{DEPARTMENT_UPLOAD_PREFIX}{department_id}" in codes
    explicit_read = f"{DEPARTMENT_READ_PREFIX}{department_id}" in codes
    home_department = department_id == str(getattr(cu, "department_id", None) or "")
    return home_department or explicit_read or can_upload, can_upload


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
    team_id = getattr(cu, "team_id", None)
    department_read, department_upload = _department_workspace_access(cu, scope_id)
    same_department = scope_type == "department" and department_read
    same_team = scope_type == "team" and bool(team_id) and scope_id == str(team_id)
    # Terminal work is personal by default.  Shared department workspaces are
    # readable for the home department and for departments explicitly granted
    # to a role.  Shared writes are never inferred from administrator status or
    # the legacy role data-scope field.
    can_read = own or same_department or same_team
    can_write_department = scope_type == "department" and department_upload
    return {
        "read": can_read,
        "create": own or can_write_department,
        "manage": own or can_write_department,
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
    department_id = str(workspace.scope_id or "")
    _, can_upload_department = _department_workspace_access(cu, department_id)
    valid = (
        workspace.scope_type == "department" and can_upload_department
    ) or (
        workspace.scope_type == "team" and str(workspace.scope_id or "") == str(cu.team_id or "")
    )
    if not valid:
        raise HTTPException(status_code=403, detail="Files may only be published to your department or team")
    await assert_can_create(db, workspace, cu)
