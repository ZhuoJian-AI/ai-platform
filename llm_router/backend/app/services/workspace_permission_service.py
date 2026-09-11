"""Single source of truth for tenant workspace capabilities."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.workspace import Workspace

if TYPE_CHECKING:
    from app.auth.user_auth import CurrentUser

DEPARTMENT_READ_PREFIX = "workspace.department.read:"
DEPARTMENT_UPLOAD_PREFIX = "workspace.department.upload:"
ORGANIZATION_MANAGE_PERMISSION = "workspace.organization.manage"
ORGANIZATION_READ_PERMISSION = "workspace.organization.read"


def _has_tenant_identity(workspace: Workspace, cu: CurrentUser) -> bool:
    """Projected objects must carry the same identity evidence as ORM rows."""
    return bool(
        getattr(workspace, "organization_id", None)
        and getattr(cu, "organization_id", None)
        and getattr(cu, "id", None)
        and str(workspace.organization_id) == str(cu.organization_id)
    )


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

    Department membership is identity, not a permission bundle. All shared
    access, including the primary department, requires a role permission.
    """
    codes = set(getattr(cu, "permission_codes", ()) or ())
    wildcard = "*" in codes
    can_upload = wildcard or f"{DEPARTMENT_UPLOAD_PREFIX}{department_id}" in codes
    explicit_read = wildcard or f"{DEPARTMENT_READ_PREFIX}{department_id}" in codes
    return explicit_read or can_upload, can_upload


def is_workspace_readable(workspace: Workspace, cu: CurrentUser) -> bool:
    """Synchronous read predicate shared by catalogue and legacy callers."""

    if (
        not _has_tenant_identity(workspace, cu)
        or getattr(workspace, "deleted_at", None) is not None
        or not getattr(workspace, "is_active", True)
    ):
        return False
    scope_type = getattr(workspace, "scope_type", "organization")
    scope_id = str(getattr(workspace, "scope_id", None) or "")
    if scope_type == "user":
        return scope_id == str(getattr(cu, "id", ""))
    if scope_type == "organization":
        codes = set(getattr(cu, "permission_codes", ()) or ())
        return bool(codes & {"*", ORGANIZATION_READ_PERMISSION, ORGANIZATION_MANAGE_PERMISSION})
    if scope_type == "department":
        can_read, _ = _department_workspace_access(cu, scope_id)
        return can_read
    return False


def _role_sources(
    cu: CurrentUser,
    permission_code: str,
    *,
    include_wildcard: bool = True,
) -> list[dict[str, str]]:
    """Return active roles contributing one concrete permission code."""
    sources: list[dict[str, str]] = []
    user_state = getattr(getattr(cu, "user", None), "__dict__", {})
    for assignment in user_state.get("role_assignments", ()) or ():
        role = getattr(assignment, "role", None)
        if role is None or not role.is_active or role.deleted_at is not None:
            continue
        accepted = {permission_code, *({"*"} if include_wildcard else set())}
        if any(item.permission_code in accepted for item in role.permissions):
            sources.append({"type": "role", "id": str(role.id), "name": role.name})
    return sorted(sources, key=lambda item: (item["name"], item["id"]))


async def capabilities(db: AsyncSession, workspace: Workspace, cu: CurrentUser) -> dict[str, bool]:
    if (
        not _has_tenant_identity(workspace, cu)
        or getattr(workspace, "deleted_at", None) is not None
        or not getattr(workspace, "is_active", True)
    ):
        return {
            "read": False, "create": False, "update": False, "delete": False,
            "manage": False, "publish": False,
        }
    scope_type = getattr(workspace, "scope_type", "organization")
    scope_id = str(getattr(workspace, "scope_id", None) or "")
    codes = set(getattr(cu, "permission_codes", ()) or ())
    own = scope_type == "user" and scope_id == str(getattr(cu, "id", ""))
    _, department_upload = _department_workspace_access(cu, scope_id)
    organization_manage = (
        scope_type == "organization"
        and (ORGANIZATION_MANAGE_PERMISSION in codes or "*" in codes)
    )
    # Both company and department access follow the explicit role matrix.
    can_read = is_workspace_readable(workspace, cu)
    can_write_department = scope_type == "department" and department_upload
    can_update = own or can_write_department or organization_manage
    return {
        "read": can_read,
        "create": own or can_write_department or organization_manage,
        "update": can_update,
        # Shared workspace deletion is intentionally not granted by the
        # department "upload / modify" permission.
        "delete": own or organization_manage,
        # Compatibility for existing clients while mutation endpoints migrate
        # to the explicit update/delete capabilities.
        "manage": can_update,
        "publish": False,
    }


def capability_sources(workspace: Workspace, cu: CurrentUser) -> dict[str, list[dict[str, str]]]:
    """Explain why the principal has each workspace capability."""
    if not is_workspace_readable(workspace, cu):
        return {}
    scope_type = getattr(workspace, "scope_type", "organization")
    scope_id = str(getattr(workspace, "scope_id", None) or "")
    own = scope_type == "user" and scope_id == str(getattr(cu, "id", ""))
    if own:
        source = [{"type": "ownership", "id": str(cu.id), "name": "个人工作空间"}]
        return {key: source for key in ("read", "create", "update", "delete")}
    if scope_type == "organization":
        result = {}
        read_sources = _role_sources(cu, ORGANIZATION_READ_PERMISSION)
        manage_sources = _role_sources(
            cu,
            ORGANIZATION_MANAGE_PERMISSION,
            include_wildcard=True,
        )
        if manage_sources:
            result.update({key: manage_sources for key in ("create", "update", "delete")})
        read_sources.extend(item for item in manage_sources if item not in read_sources)
        if read_sources:
            result["read"] = read_sources
        return result
    if scope_type != "department":
        return {}

    read_code = f"{DEPARTMENT_READ_PREFIX}{scope_id}"
    upload_code = f"{DEPARTMENT_UPLOAD_PREFIX}{scope_id}"
    read_sources = _role_sources(cu, read_code)
    upload_sources = _role_sources(cu, upload_code)
    # Upload implies read in the role editor and server-side resolver.
    read_sources.extend(item for item in upload_sources if item not in read_sources)
    result: dict[str, list[dict[str, str]]] = {}
    if read_sources:
        result["read"] = read_sources
    if upload_sources:
        result["create"] = upload_sources
        result["update"] = upload_sources
    return result


async def effective_access(db: AsyncSession, cu: CurrentUser) -> dict:
    """Resolve the user's role-aware workspace access without listing files."""
    workspaces = list((await db.execute(select(Workspace).where(
        Workspace.organization_id == cu.organization_id,
        Workspace.deleted_at.is_(None),
        Workspace.is_active.is_(True),
    ))).scalars().all())
    scope_order = {"organization": 0, "department": 1, "user": 2}
    rows = []
    for workspace in sorted(
        workspaces,
        key=lambda item: (scope_order.get(item.scope_type, 9), item.name, str(item.id)),
    ):
        if workspace.scope_type == "user" and str(workspace.scope_id) != str(cu.id):
            # Other employees' personal workspace names are not part of the
            # organization permission catalogue and must not be disclosed.
            continue
        caps = await capabilities(db, workspace, cu)
        # The employee/runtime catalogue is an allow-list, not an organization
        # directory.  Workspaces for which the principal has no capability must
        # not leak their name, slug or scope id through the terminal API or the
        # model prompt.
        if not any(caps.values()):
            continue
        rows.append({
            "id": str(workspace.id),
            "name": workspace.name,
            "slug": workspace.slug,
            "scope_type": workspace.scope_type,
            "scope_id": str(workspace.scope_id) if workspace.scope_id else None,
            "capabilities": caps,
            "sources": capability_sources(workspace, cu),
        })
    user_state = getattr(getattr(cu, "user", None), "__dict__", {})
    roles = [{
        "id": str(assignment.role.id), "name": assignment.role.name,
        "code": assignment.role.code, "data_scope": assignment.role.data_scope,
        "is_builtin": assignment.role.is_builtin,
    } for assignment in (user_state.get("role_assignments", ()) or ())
        if assignment.role.is_active and assignment.role.deleted_at is None]
    return {"roles": roles, "workspaces": rows}


def resolve_workspace_intent(
    access: dict,
    request: str,
    *,
    referenced_workspace_ids: list[str] | tuple[str, ...] = (),
) -> dict:
    """Return the capability-derived workspace set available to the agent.

    This compatibility helper deliberately ignores natural-language keywords.
    Role-based capabilities are the only workspace boundary; every concrete
    tool operation performs a fresh RBAC check before reading or mutating data.
    ``referenced_workspace_ids`` remains accepted for older callers but never
    widens the capability set.
    """
    del request, referenced_workspace_ids
    workspaces = list(access.get("workspaces") or [])
    read_ids = {
        str(item["id"]) for item in workspaces
        if item.get("capabilities", {}).get("read")
    }
    write_ids = {
        str(item["id"]) for item in workspaces
        if any(item.get("capabilities", {}).get(key) for key in ("create", "update", "delete"))
    }
    return {
        "permission_question": False,
        "file_operation": False,
        "write_operation": False,
        "matched_workspace_ids": sorted(read_ids),
        "read_workspace_ids": sorted(read_ids),
        "write_workspace_ids": sorted(write_ids),
        "ambiguous_names": [],
    }


async def _assert(db: AsyncSession, workspace: Workspace, cu: CurrentUser, capability: str) -> None:
    if not (await capabilities(db, workspace, cu))[capability]:
        # Cross-tenant resources deliberately look absent.
        cross_tenant = str(getattr(workspace, "organization_id", None)) != str(
            getattr(cu, "organization_id", None)
        )
        status = 404 if cross_tenant else 403
        operation = {
            "read": "读取", "create": "创建文件", "update": "修改文件",
            "delete": "删除文件", "publish": "发布文件",
        }.get(capability, "操作")
        detail = "工作空间不存在" if cross_tenant else f"当前角色没有该工作空间的{operation}权限"
        raise HTTPException(status_code=status, detail=detail)


async def assert_can_read(db: AsyncSession, workspace: Workspace, cu: CurrentUser) -> None:
    await _assert(db, workspace, cu, "read")


async def assert_can_create(db: AsyncSession, workspace: Workspace, cu: CurrentUser) -> None:
    await _assert(db, workspace, cu, "create")


async def assert_can_manage(db: AsyncSession, workspace: Workspace, cu: CurrentUser) -> None:
    await _assert(db, workspace, cu, "update")


async def assert_can_update(db: AsyncSession, workspace: Workspace, cu: CurrentUser) -> None:
    await _assert(db, workspace, cu, "update")


async def assert_can_delete(db: AsyncSession, workspace: Workspace, cu: CurrentUser) -> None:
    await _assert(db, workspace, cu, "delete")


async def assert_can_publish(db: AsyncSession, workspace: Workspace, cu: CurrentUser) -> None:
    await _assert(db, workspace, cu, "publish")


async def assert_publish_target(db: AsyncSession, workspace: Workspace, cu: CurrentUser) -> None:
    if str(workspace.organization_id) != str(cu.organization_id):
        raise HTTPException(status_code=404, detail="Workspace not found")
    department_id = str(workspace.scope_id or "")
    _, can_upload_department = _department_workspace_access(cu, department_id)
    valid = workspace.scope_type == "department" and can_upload_department
    if not valid:
        raise HTTPException(status_code=403, detail="文件只能发布到已获授权的部门工作空间")
    await assert_can_create(db, workspace, cu)
