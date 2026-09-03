"""Single source of truth for tenant workspace capabilities."""

from __future__ import annotations

import re

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.user_auth import CurrentUser
from app.models.workspace import Workspace

DEPARTMENT_READ_PREFIX = "workspace.department.read:"
DEPARTMENT_UPLOAD_PREFIX = "workspace.department.upload:"
PERMISSION_QUESTION_MARKERS = (
    "权限", "角色", "能不能", "能否", "可以吗", "能做什么", "可做什么", "哪些部门", "什么部门",
)
WRITE_ACTION_MARKERS = ("修改", "上传", "写入", "保存", "生成", "重命名", "恢复", "新建", "创建")
DIRECT_FILE_ACTION_MARKERS = (
    "读取", "查看", "列出", "扫描", "处理", "分析", "修改", "上传", "写入", "保存", "生成", "重命名", "恢复",
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

    Department membership is identity, not a permission bundle.  A user's
    primary department is readable by default; shared writes and cross-
    department access must be granted by one of the user's roles.
    """
    codes = set(getattr(cu, "permission_codes", ()) or ())
    wildcard = "*" in codes
    can_upload = wildcard or f"{DEPARTMENT_UPLOAD_PREFIX}{department_id}" in codes
    explicit_read = wildcard or f"{DEPARTMENT_READ_PREFIX}{department_id}" in codes
    home_department = department_id == str(getattr(cu, "department_id", None) or "")
    return home_department or explicit_read or can_upload, can_upload


def _role_sources(cu: CurrentUser, permission_code: str) -> list[dict[str, str]]:
    """Return active roles contributing one concrete permission code."""
    sources: list[dict[str, str]] = []
    user_state = getattr(getattr(cu, "user", None), "__dict__", {})
    for assignment in user_state.get("role_assignments", ()) or ():
        role = getattr(assignment, "role", None)
        if role is None or not role.is_active or role.deleted_at is not None:
            continue
        if any(item.permission_code in {"*", permission_code} for item in role.permissions):
            sources.append({"type": "role", "id": str(role.id), "name": role.name})
    return sorted(sources, key=lambda item: (item["name"], item["id"]))


async def capabilities(db: AsyncSession, workspace: Workspace, cu: CurrentUser) -> dict[str, bool]:
    # ORM Workspace / CurrentUser always expose these fields.  A few internal
    # integrations and tests intentionally pass lightweight projected objects;
    # keep read-only compatibility without weakening checks for real rows.
    if not hasattr(workspace, "organization_id"):
        return {
            "read": True, "create": False, "update": False, "delete": False,
            "manage": False, "publish": False,
        }
    cross_tenant = str(workspace.organization_id) != str(getattr(cu, "organization_id", None))
    if (
        cross_tenant
        or getattr(workspace, "deleted_at", None) is not None
        or not getattr(workspace, "is_active", True)
    ):
        return {
            "read": False, "create": False, "update": False, "delete": False,
            "manage": False, "publish": False,
        }
    scope_type = getattr(workspace, "scope_type", "organization")
    scope_id = str(getattr(workspace, "scope_id", None) or "")
    own = scope_type == "user" and scope_id == str(getattr(cu, "id", ""))
    team_id = getattr(cu, "team_id", None)
    department_read, department_upload = _department_workspace_access(cu, scope_id)
    same_department = scope_type == "department" and department_read
    same_team = scope_type == "team" and bool(team_id) and scope_id == str(team_id)
    same_organization = scope_type == "organization"
    # Terminal work is personal by default.  Shared department workspaces are
    # readable for the home department and for departments explicitly granted
    # to a role.  The organization workspace is a company-wide read-only area.
    # Shared writes are never inferred from administrator status or the legacy
    # role data-scope field.
    can_read = own or same_department or same_team or same_organization
    can_write_department = scope_type == "department" and department_upload
    can_update = own or can_write_department
    return {
        "read": can_read,
        "create": own or can_write_department,
        "update": can_update,
        # Shared workspace deletion is intentionally not granted by the
        # department "upload / modify" permission.
        "delete": own,
        # Compatibility for existing clients while mutation endpoints migrate
        # to the explicit update/delete capabilities.
        "manage": can_update,
        "publish": False,
    }


def capability_sources(workspace: Workspace, cu: CurrentUser) -> dict[str, list[dict[str, str]]]:
    """Explain why the principal has each workspace capability."""
    scope_type = getattr(workspace, "scope_type", "organization")
    scope_id = str(getattr(workspace, "scope_id", None) or "")
    own = scope_type == "user" and scope_id == str(getattr(cu, "id", ""))
    if own:
        source = [{"type": "ownership", "id": str(cu.id), "name": "个人工作空间"}]
        return {key: source for key in ("read", "create", "update", "delete")}
    if scope_type == "organization":
        return {"read": [{"type": "organization", "id": str(cu.organization_id), "name": "同公司公共只读"}]}
    if scope_type == "team" and scope_id == str(getattr(cu, "team_id", None) or ""):
        return {"read": [{"type": "membership", "id": scope_id, "name": "所属团队"}]}
    if scope_type != "department":
        return {}

    read_code = f"{DEPARTMENT_READ_PREFIX}{scope_id}"
    upload_code = f"{DEPARTMENT_UPLOAD_PREFIX}{scope_id}"
    read_sources = _role_sources(cu, read_code)
    upload_sources = _role_sources(cu, upload_code)
    if scope_id == str(getattr(cu, "department_id", None) or ""):
        read_sources = [
            {"type": "membership", "id": scope_id, "name": "主部门默认只读"},
            *read_sources,
        ]
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
    scope_order = {"organization": 0, "department": 1, "team": 2, "user": 3}
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
    """Resolve this turn's shared-workspace boundary without reading file metadata.

    The personal workspace is always the default. Shared workspace names only
    authorize tools for a concrete file operation, while permission questions
    are answered from ``access`` alone.
    """
    text = (request or "").casefold().strip()
    workspaces = list(access.get("workspaces") or [])
    personal_ids = {
        str(item["id"]) for item in workspaces
        if item.get("scope_type") == "user" and item.get("capabilities", {}).get("read")
    }
    # A referenced file authorizes that exact file in the tool layer, never
    # the rest of its workspace. The caller still supplies workspace ids so
    # this distinction stays explicit at the boundary.
    direct_file_operation = (
        any(marker in text for marker in DIRECT_FILE_ACTION_MARKERS)
        and any(marker in text for marker in ("文件", "表格", "文档", "附件", "目录", "工作空间"))
    )
    # 「我能不能修改财务部文件」是在问权限；「读取 销售表.xlsx 检查是否有重复行」是在下达
    # 文件操作。区分点是情态词是否出现在文件动作动词**之前**：只有领先于动词时才算权限
    # 提问；没有动词时照旧算。"是否" 在普通指令里过于常见（检查是否…），不再作为标记。
    verb_positions = [text.find(marker) for marker in DIRECT_FILE_ACTION_MARKERS if marker in text]
    first_verb = min(verb_positions) if verb_positions else len(text)
    leading_permission_question = any(
        marker in text and text.find(marker) < first_verb
        for marker in ("能不能", "能否", "可不可以")
    )
    permission_question = leading_permission_question or (
        any(marker in text for marker in PERMISSION_QUESTION_MARKERS) and not direct_file_operation
    )
    file_operation = direct_file_operation and not permission_question
    write_operation = file_operation and any(marker in text for marker in WRITE_ACTION_MARKERS)

    aliases: dict[str, list[dict]] = {}
    for item in workspaces:
        if item.get("scope_type") == "user":
            continue
        for raw in (item.get("name"), item.get("slug")):
            key = str(raw or "").casefold().strip()
            if key:
                aliases.setdefault(key, []).append(item)
    organization_rows = [item for item in workspaces if item.get("scope_type") == "organization"]
    if any(phrase in text for phrase in ("公司公共", "公司空间", "企业公共", "组织公共")):
        aliases.setdefault("__organization__", []).extend(organization_rows)

    matched: dict[str, dict] = {}
    ambiguous: list[str] = []
    for alias, rows in aliases.items():
        if alias == "__organization__":
            mentioned = True
        elif re.fullmatch(r"[a-z0-9][a-z0-9_-]*", alias):
            mentioned = bool(re.search(rf"(?<![a-z0-9_-]){re.escape(alias)}(?![a-z0-9_-])", text))
        else:
            mentioned = alias in text
        if not mentioned:
            continue
        unique = {str(item["id"]): item for item in rows}
        if len(unique) > 1:
            ambiguous.append("公司公共空间" if alias == "__organization__" else alias)
            continue
        matched.update(unique)

    if any(phrase in text for phrase in ("所有我有权限的部门", "全部我有权限的部门", "所有有权限的部门")):
        for item in workspaces:
            if item.get("scope_type") == "department" and item.get("capabilities", {}).get("read"):
                matched[str(item["id"])] = item

    read_ids = set(personal_ids)
    write_ids = set(personal_ids)
    if file_operation and not ambiguous:
        read_ids.update(
            workspace_id for workspace_id, item in matched.items()
            if item.get("capabilities", {}).get("read")
        )
        if write_operation:
            write_ids.update(
                workspace_id for workspace_id, item in matched.items()
                if item.get("capabilities", {}).get("create")
                or item.get("capabilities", {}).get("update")
            )
    return {
        "permission_question": permission_question,
        "file_operation": file_operation,
        "write_operation": write_operation,
        "matched_workspace_ids": sorted(matched),
        "read_workspace_ids": sorted(read_ids),
        "write_workspace_ids": sorted(write_ids),
        "ambiguous_names": sorted(set(ambiguous)),
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
    valid = (
        workspace.scope_type == "department" and can_upload_department
    ) or (
        workspace.scope_type == "team" and str(workspace.scope_id or "") == str(cu.team_id or "")
    )
    if not valid:
        raise HTTPException(status_code=403, detail="Files may only be published to your department or team")
    await assert_can_create(db, workspace, cu)
