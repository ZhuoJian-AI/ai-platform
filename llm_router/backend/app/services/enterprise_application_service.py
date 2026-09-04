"""CRUD and centralized authorization for embedded tenant applications."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import or_, select
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
from app.models.tool_call_log import ToolCallLog
from app.schemas.enterprise_application import (
    EnterpriseApplicationCreate,
    EnterpriseApplicationGrantInput,
    EnterpriseApplicationToolBindingInput,
    EnterpriseApplicationUpdate,
)
from app.services import role_service, scope_service, skill_scope_service

PERMISSIONS = {"view", "ai_query", "ai_create", "ai_update", "ai_delete", "ai_approve", "export"}
OPERATION_PERMISSION = {
    "query": "ai_query",
    "create": "ai_create",
    "update": "ai_update",
    "delete": "ai_delete",
    "approve": "ai_approve",
    "export": "export",
}


def _application_options():
    return (
        selectinload(EnterpriseApplication.grants),
        selectinload(EnterpriseApplication.tool_bindings),
        selectinload(EnterpriseApplication.integration),
        selectinload(EnterpriseApplication.actions),
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


def _uses_role_authorization(row: EnterpriseApplication) -> bool:
    """Contract 2.4+ makes roles the only native authorization subject.

    Older integrations retain their historical department/team/user grants until an
    administrator upgrades the subsystem manifest and converts those grants.
    """
    integration = row.integration
    if integration is None or not isinstance(integration.manifest, dict):
        return False
    revision = str(integration.manifest.get("contractRevision") or "")
    try:
        major, minor = (int(part) for part in revision.split(".", maxsplit=1))
    except (TypeError, ValueError):
        return False
    return (major, minor) >= (2, 4)


def _matching_grants(row: EnterpriseApplication, user: CurrentUser):
    if _uses_role_authorization(row):
        role_ids = {str(role_id) for role_id in user.role_ids}
        return [
            grant
            for grant in row.grants
            if grant.deleted_at is None and grant.scope_type == "role" and grant.scope_id in role_ids
        ]
    scopes = set(scope_service.effective_scope_set(user))
    return [
        grant
        for grant in row.grants
        if grant.deleted_at is None and (grant.scope_type, grant.scope_id or None) in scopes
    ]


def _application_role_ids(row: EnterpriseApplication) -> set[str]:
    return {
        str(grant.scope_id)
        for grant in row.grants
        if grant.scope_type == "role" and grant.scope_id and grant.deleted_at is None
    }


def _grant_application_permissions(grant) -> set[str]:
    permissions = {value for value in (grant.permissions or []) if value in PERMISSIONS}
    if any(
        "view" in (access.get("permissions") or [])
        for access in (grant.module_access or {}).values()
        if isinstance(access, dict)
    ):
        permissions.add("view")
    return permissions


def _grant_module_permissions(grant, module_key: str) -> set[str]:
    access = (grant.module_access or {}).get(module_key)
    if isinstance(access, dict):
        return {value for value in (access.get("permissions") or []) if value in PERMISSIONS}
    keys = grant.module_keys or []
    if not keys or module_key in keys:
        return {value for value in (grant.permissions or []) if value in PERMISSIONS}
    return set()


def _grant_page_permissions(grant, module_key: str, page_key: str | None) -> set[str]:
    if not page_key:
        return _grant_module_permissions(grant, module_key)
    access = (grant.module_access or {}).get(module_key)
    if isinstance(access, dict):
        page_access = access.get("page_access")
        if isinstance(page_access, dict) and page_access:
            page = page_access.get(page_key)
            if not isinstance(page, dict):
                return set()
            return {value for value in (page.get("permissions") or []) if value in PERMISSIONS}
        return {value for value in (access.get("permissions") or []) if value in PERMISSIONS}
    keys = grant.module_keys or []
    if not keys or module_key in keys:
        return {value for value in (grant.permissions or []) if value in PERMISSIONS}
    return set()


def _grant_allows_action(
    grant,
    module_key: str,
    page_key: str | None,
    action_key: str,
    required_permission: str,
) -> bool:
    access = (grant.module_access or {}).get(module_key)
    if not isinstance(access, dict):
        keys = grant.module_keys or []
        permissions = set(grant.permissions or [])
        return (not keys or module_key in keys) and {"view", required_permission} <= permissions
    permissions = set(access.get("permissions") or [])
    module_actions = access.get("action_keys")
    if isinstance(module_actions, list) and module_actions and action_key not in module_actions:
        return False
    page_access = access.get("page_access")
    if page_key and isinstance(page_access, dict) and page_access:
        page = page_access.get(page_key)
        if not isinstance(page, dict) or page.get("ai_enabled", True) is not True:
            return False
        permissions = set(page.get("permissions") or [])
        page_actions = page.get("action_keys")
        if not isinstance(page_actions, list) or action_key not in page_actions:
            return False
    return {"view", required_permission} <= permissions


def effective_data_scope(
    row: EnterpriseApplication,
    user: CurrentUser,
    module_key: str | None = None,
    page_key: str | None = None,
    action_key: str | None = None,
    required_permission: str = "view",
) -> dict:
    """Merge scopes only from roles that independently authorize this resource.

    Legacy pre-2.4 integrations retain their historical principal-wide scope during
    the compatibility window. Native role contracts fail closed when per-role scope
    material is missing.
    """
    if not row.is_active or row.deleted_at is not None:
        return role_service.merge_effective_data_scopes([])
    if not _uses_role_authorization(row):
        return dict(user.effective_data_scopes or role_service.merge_effective_data_scopes([]))

    authorized_role_ids: set[str] = set()
    for grant in _matching_grants(row, user):
        if grant.scope_type != "role" or not grant.scope_id:
            continue
        if action_key is not None:
            allowed = bool(module_key) and _grant_allows_action(
                grant,
                module_key,
                page_key,
                action_key,
                required_permission,
            )
        elif page_key is not None:
            page_permissions = _grant_page_permissions(grant, module_key, page_key)
            required_page_permissions = {required_permission}
            if required_permission != "view":
                required_page_permissions.add("view")
            allowed = bool(module_key) and required_page_permissions <= page_permissions
        elif module_key is not None:
            allowed = required_permission in _grant_module_permissions(grant, module_key)
        else:
            allowed = required_permission in _grant_application_permissions(grant)
        if allowed:
            authorized_role_ids.add(str(grant.scope_id))

    role_scopes = user.role_data_scopes or {}
    return role_service.merge_effective_data_scopes(
        [role_scopes[role_id] for role_id in authorized_role_ids if role_id in role_scopes]
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
    access_changed = "is_active" in values and values["is_active"] != row.is_active
    for field, value in values.items():
        setattr(row, field, str(value) if field in {"entry_url", "icon_url"} and value else value)
    if access_changed:
        await role_service.touch_users_for_role_ids(db, _application_role_ids(row))
    await db.flush()
    return await get_application(db, row.id)  # type: ignore[return-value]


async def soft_delete_application(db: AsyncSession, row: EnterpriseApplication) -> None:
    now = datetime.now(UTC)
    affected_role_ids = _application_role_ids(row)
    row.deleted_at = now
    for grant in row.grants:
        grant.deleted_at = now
    for binding in row.tool_bindings:
        binding.deleted_at = now
    await role_service.touch_users_for_role_ids(db, affected_role_ids)
    await db.flush()


async def replace_grants(
    db: AsyncSession,
    row: EnterpriseApplication,
    grants: list[EnterpriseApplicationGrantInput],
) -> EnterpriseApplication:
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
    role_only = _uses_role_authorization(row)
    normalized: dict[tuple[str, str | None], tuple[list[str], list[str], dict]] = {}
    for item in grants:
        requested_key = (
            item.scope_type,
            str(item.scope_id) if item.scope_id else None,
        )
        if role_only and item.scope_type != "role":
            # A replace-all client may echo a historical grant while upgrading an
            # application to 2.4. Existing legacy rows are omitted and therefore
            # soft-deleted below; a newly forged non-role scope remains invalid.
            if requested_key in current:
                continue
            raise HTTPException(
                status_code=422,
                detail="Contract 2.4+ native applications can only be granted to roles",
            )
        try:
            sid = await skill_scope_service.validate_scope_target(
                db,
                row.organization_id,
                item.scope_type,
                item.scope_id,
            )
        except HTTPException as exc:
            # Older clients submit the complete grant list. If a referenced
            # department/team/user/role was deleted after the page loaded, let the
            # same request repair that pre-existing orphan instead of blocking all
            # unrelated role changes. Unknown invalid targets are still rejected.
            if exc.status_code == 422 and requested_key in current:
                continue
            raise
        permissions = [value for value in item.permissions if value in PERMISSIONS]
        module_access = {key: access.model_dump(mode="json") for key, access in item.module_access.items()}
        if permissions or module_access:
            normalized[(item.scope_type, sid)] = (
                permissions,
                item.module_keys,
                module_access,
            )

    now = datetime.now(UTC)
    for key, grant in current.items():
        if key not in normalized:
            grant.deleted_at = now
        else:
            grant.permissions, grant.module_keys, grant.module_access = normalized[key]
            grant.deleted_at = None
    for (scope_type, scope_id), (permissions, module_keys, module_access) in normalized.items():
        if (scope_type, scope_id) not in current:
            db.add(
                EnterpriseApplicationGrant(
                    application_id=row.id,
                    organization_id=row.organization_id,
                    scope_type=scope_type,
                    scope_id=scope_id,
                    permissions=permissions,
                    module_keys=module_keys,
                    module_access=module_access,
                )
            )
    affected_role_ids = {
        str(scope_id) for scope_type, scope_id in {*current, *normalized} if scope_type == "role" and scope_id
    }
    await role_service.touch_users_for_role_ids(db, affected_role_ids)
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


async def get_application_overview(db: AsyncSession, row: EnterpriseApplication) -> dict:
    """Resolve opaque application bindings into an administrator-facing read model."""
    active_bindings = [binding for binding in row.tool_bindings if binding.deleted_at is None]
    endpoint_ids = {
        UUID(str(binding.target_id)) for binding in active_bindings if binding.target_type == "tool_endpoint"
    }
    interface_ids = {
        UUID(str(binding.target_id)) for binding in active_bindings if binding.target_type == "data_interface"
    }
    skill_ids = {UUID(str(binding.target_id)) for binding in active_bindings if binding.target_type == "skill_folder"}

    endpoints: dict[str, tuple[ToolEndpoint, ToolConnector]] = {}
    if endpoint_ids:
        result = await db.execute(
            select(ToolEndpoint, ToolConnector)
            .join(ToolConnector, ToolEndpoint.connector_id == ToolConnector.id)
            .where(
                ToolEndpoint.id.in_(endpoint_ids),
                ToolConnector.organization_id == row.organization_id,
                ToolEndpoint.deleted_at.is_(None),
                ToolConnector.deleted_at.is_(None),
            )
        )
        endpoints = {str(endpoint.id): (endpoint, connector) for endpoint, connector in result.all()}

    interfaces: dict[str, tuple[DataInterface, DataSystem]] = {}
    if interface_ids:
        result = await db.execute(
            select(DataInterface, DataSystem)
            .join(DataSystem, DataInterface.data_system_id == DataSystem.id)
            .where(
                DataInterface.id.in_(interface_ids),
                DataSystem.organization_id == row.organization_id,
                DataInterface.deleted_at.is_(None),
                DataSystem.deleted_at.is_(None),
            )
        )
        interfaces = {str(item.id): (item, system) for item, system in result.all()}

    skills: dict[str, SkillFolder] = {}
    if skill_ids:
        result = await db.execute(
            select(SkillFolder).where(
                SkillFolder.id.in_(skill_ids),
                SkillFolder.organization_id == row.organization_id,
                SkillFolder.deleted_at.is_(None),
            )
        )
        skills = {str(item.id): item for item in result.scalars().all()}

    capabilities: list[dict] = []
    for binding in active_bindings:
        target_id = str(binding.target_id)
        common = {
            "binding_id": binding.id,
            "target_type": binding.target_type,
            "target_id": UUID(target_id),
            "operation": binding.operation,
            "binding_active": binding.is_active,
        }
        if binding.target_type == "tool_endpoint" and target_id in endpoints:
            endpoint, connector = endpoints[target_id]
            capabilities.append(
                {
                    **common,
                    "name": endpoint.name,
                    "source_name": connector.name,
                    "description": endpoint.description,
                    "method": endpoint.method,
                    "path": endpoint.path,
                    "target_active": endpoint.is_active and connector.is_active,
                    "health_status": connector.health_status,
                }
            )
        elif binding.target_type == "data_interface" and target_id in interfaces:
            interface, system = interfaces[target_id]
            capabilities.append(
                {
                    **common,
                    "name": interface.name,
                    "source_name": system.name,
                    "description": interface.description,
                    "method": interface.method,
                    "path": interface.path,
                    "target_active": interface.is_active and system.is_active,
                    "health_status": None,
                }
            )
        elif binding.target_type == "skill_folder" and target_id in skills:
            skill = skills[target_id]
            capabilities.append(
                {
                    **common,
                    "name": skill.name,
                    "source_name": "Skill 运行包",
                    "description": None,
                    "method": None,
                    "path": None,
                    "target_active": skill.is_active,
                    "health_status": "ready" if skill.is_installed else "unavailable",
                }
            )

    # Connector-generated Skill wrappers and their direct endpoints may coexist.
    # Count the direct business APIs when present so the administrator does not
    # see the same capability twice; Skill-only applications still count Skills.
    direct_capabilities = [item for item in capabilities if item["target_type"] != "skill_folder"]
    counted_capabilities = direct_capabilities or capabilities
    operation_counts = {operation: 0 for operation in OPERATION_PERMISSION}
    for item in counted_capabilities:
        if item["binding_active"] and item["target_active"]:
            operation_counts[item["operation"]] += 1

    recent_calls: list[dict] = []
    call_filters = []
    if endpoint_ids:
        call_filters.append(ToolCallLog.endpoint_id.in_(endpoint_ids))
    if skill_ids:
        call_filters.append(ToolCallLog.skill_id.in_(skill_ids))
    if call_filters:
        result = await db.execute(
            select(ToolCallLog)
            .where(
                ToolCallLog.organization_id == row.organization_id,
                or_(*call_filters),
            )
            .order_by(ToolCallLog.created_at.desc())
            .limit(20)
        )
        endpoint_names = {key: value[0].name for key, value in endpoints.items()}
        skill_names = {key: value.name for key, value in skills.items()}
        for call in result.scalars().all():
            failed = bool(call.error) or bool(call.status_code and call.status_code >= 400)
            recent_calls.append(
                {
                    "id": call.id,
                    "capability_name": (
                        endpoint_names.get(str(call.endpoint_id))
                        or skill_names.get(str(call.skill_id))
                        or call.path
                        or "未知工具"
                    ),
                    "method": call.method,
                    "path": call.path,
                    "status": "failed" if failed else "success",
                    "status_code": call.status_code,
                    "latency_ms": call.latency_ms,
                    "error": call.error,
                    "created_at": call.created_at,
                }
            )

    return {
        "application_id": row.id,
        "operation_counts": operation_counts,
        "active_capability_count": sum(operation_counts.values()),
        "direct_capability_count": len(direct_capabilities),
        "skill_binding_count": len([item for item in capabilities if item["target_type"] == "skill_folder"]),
        "capabilities": capabilities,
        "recent_calls": recent_calls,
    }


def effective_permissions(row: EnterpriseApplication, user: CurrentUser) -> set[str]:
    if not row.is_active or row.deleted_at is not None:
        return set()
    permissions: set[str] = set()
    for grant in _matching_grants(row, user):
        permissions.update(_grant_application_permissions(grant))
    return permissions


def effective_module_keys(row: EnterpriseApplication, user: CurrentUser) -> list[str]:
    """Return allowed module keys; an empty list means unrestricted for compatibility."""
    matching = _matching_grants(row, user)
    if not matching:
        return []
    if any(not (grant.module_keys or []) and not (grant.module_access or {}) for grant in matching):
        return []
    return sorted(
        {key for grant in matching for key in [*(grant.module_keys or []), *(grant.module_access or {}).keys()]}
    )


def _manifest_read_only_claims(
    row: EnterpriseApplication, module_key: str
) -> tuple[set[str], dict[str, dict[str, set[str]]]]:
    """Project a legacy app-level ``view`` grant onto protocol-v2 pages.

    Grants created before native child-module authorization did not contain
    page or action allowlists.  A strict v2 subsystem must never receive an
    unrestricted ticket, so the compatibility ceiling is deliberately small:
    every declared page may be viewed and only its declared query action may
    be called.  Mutations, exports, approvals and sensitive actions still need
    an explicit structured grant from an administrator.
    """
    integration = row.integration
    if integration is None or integration.protocol_version < 2:
        return set(), {}
    manifest = integration.manifest if isinstance(integration.manifest, dict) else {}
    modules = manifest.get("modules")
    if not isinstance(modules, list):
        return set(), {}
    module = next(
        (item for item in modules if isinstance(item, dict) and item.get("moduleKey") == module_key),
        None,
    )
    if not isinstance(module, dict):
        return set(), {}

    action_keys: set[str] = set()
    page_access: dict[str, dict] = {}
    pages = module.get("pages")
    for page in pages if isinstance(pages, list) else []:
        if not isinstance(page, dict) or not isinstance(page.get("pageKey"), str):
            continue
        query_action = page.get("queryActionKey")
        declared_actions = page.get("actionKeys")
        page_actions = set()
        if isinstance(query_action, str) and isinstance(declared_actions, list) and query_action in declared_actions:
            page_actions.add(query_action)
            action_keys.add(query_action)
        page_access[str(page["pageKey"])] = {
            "permissions": {"view"},
            "action_keys": page_actions,
        }
    return action_keys, page_access


def visible_manifest_modules(row: EnterpriseApplication, user: CurrentUser) -> list[dict[str, str]]:
    """Return the protocol-v2 modules the current user may actually launch.

    The terminal navigation and launch endpoint intentionally share this
    projection so a child module can never be displayed without the same
    server-side ``view`` decision that protects its SSO ticket.
    """
    integration = row.integration
    if integration is None or integration.protocol_version < 2:
        return []
    manifest_modules = integration.manifest.get("modules") if isinstance(integration.manifest, dict) else []
    if not isinstance(manifest_modules, list):
        return []
    visible: list[dict[str, str]] = []
    for item in manifest_modules:
        if not isinstance(item, dict) or not item.get("moduleKey"):
            continue
        module_key = str(item["moduleKey"])
        if "view" not in effective_module_permissions(row, user, module_key):
            continue
        claims = effective_module_claims(row, user, module_key)
        if not claims.get("page_access"):
            continue
        visible.append(
            {
                "module_key": module_key,
                "name": str(item.get("name") or module_key),
            }
        )
    return visible


def effective_module_permissions(row: EnterpriseApplication, user: CurrentUser, module_key: str) -> set[str]:
    """Resolve v2 per-module permissions while preserving v1 grants."""
    if not row.is_active or row.deleted_at is not None:
        return set()
    permissions: set[str] = set()
    for grant in _matching_grants(row, user):
        permissions.update(_grant_module_permissions(grant, module_key))
    return permissions


def effective_module_claims(row: EnterpriseApplication, user: CurrentUser, module_key: str) -> dict:
    """Build the least-privilege page/action scope embedded in an SSO ticket.

    Legacy grants are projected to read-only manifest pages instead of issuing
    an unrestricted ticket. Structured grants are merged across every scope
    that applies to the user.
    """
    action_keys: set[str] = set()
    page_access: dict[str, dict[str, set[str]]] = {}
    unrestricted_actions = False
    unrestricted_pages = False
    matched = False
    for grant in _matching_grants(row, user):
        access = (grant.module_access or {}).get(module_key)
        if not isinstance(access, dict):
            keys = grant.module_keys or []
            if not keys or module_key in keys:
                matched = True
                unrestricted_actions = True
                unrestricted_pages = True
            continue
        matched = True
        actions = access.get("action_keys")
        if isinstance(actions, list):
            action_keys.update(str(item) for item in actions if isinstance(item, str))
        else:
            unrestricted_actions = True
        pages = access.get("page_access")
        if not isinstance(pages, dict) or not pages:
            unrestricted_pages = True
            continue
        for page_key, page in pages.items():
            if not isinstance(page_key, str) or not isinstance(page, dict):
                continue
            merged = page_access.setdefault(
                page_key,
                {"permissions": set(), "action_keys": set(), "ai_enabled": False},
            )
            merged["permissions"].update(value for value in (page.get("permissions") or []) if value in PERMISSIONS)
            merged["action_keys"].update(str(item) for item in (page.get("action_keys") or []) if isinstance(item, str))
            # Multiple roles are merged by union.  Missing values belong to
            # grants created before the separate AI gate and remain enabled
            # for compatibility; new admin grants always persist the flag.
            merged["ai_enabled"] = bool(merged["ai_enabled"]) or bool(page.get("ai_enabled", True))
            if not isinstance(actions, list):
                action_keys.update(merged["action_keys"])
    if matched and (unrestricted_actions or unrestricted_pages):
        fallback_actions, fallback_pages = _manifest_read_only_claims(row, module_key)
        if unrestricted_pages:
            for page_key, fallback in fallback_pages.items():
                merged = page_access.setdefault(
                    page_key,
                    {"permissions": set(), "action_keys": set(), "ai_enabled": False},
                )
                merged["permissions"].update(fallback["permissions"])
                merged["action_keys"].update(fallback["action_keys"])
        if unrestricted_actions:
            action_keys.update(fallback_actions)

    launchable_page_access = {
        page_key: access for page_key, access in page_access.items() if "view" in access["permissions"]
    }

    # A global action allowlist must be the union of page-scoped actions. This
    # keeps malformed legacy rows from placing an unbound mutation in a ticket.
    scoped_action_keys = {action_key for page in launchable_page_access.values() for action_key in page["action_keys"]}
    action_keys.intersection_update(scoped_action_keys)
    action_permissions = {
        action.action_key: OPERATION_PERMISSION[action.operation]
        for action in (getattr(row, "actions", None) or ())
        if action.module_key == module_key
        and action.is_active
        and action.operation in OPERATION_PERMISSION
    }
    manifest = row.integration.manifest if row.integration and isinstance(row.integration.manifest, dict) else {}
    for module in manifest.get("modules") or []:
        if not isinstance(module, dict) or module.get("moduleKey") != module_key:
            continue
        for action in module.get("actions") or []:
            if not isinstance(action, dict):
                continue
            action_key = action.get("actionKey")
            operation = action.get("operation")
            if isinstance(action_key, str) and operation in OPERATION_PERMISSION:
                action_permissions.setdefault(action_key, OPERATION_PERMISSION[operation])
        for page in module.get("pages") or []:
            if not isinstance(page, dict):
                continue
            query_action_key = page.get("queryActionKey")
            if isinstance(query_action_key, str):
                action_permissions.setdefault(query_action_key, "ai_query")
    action_keys.intersection_update(action_permissions)
    return {
        "permissions": sorted(effective_module_permissions(row, user, module_key)),
        "action_keys": sorted(action_keys),
        "page_access": {
            key: {
                "permissions": sorted(value["permissions"]),
                "action_keys": sorted(value["action_keys"] & action_keys),
                "data_scopes": {
                    permission: effective_data_scope(
                        row,
                        user,
                        module_key,
                        key,
                        required_permission=permission,
                    )
                    for permission in sorted(value["permissions"])
                },
                "action_data_scopes": {
                    action_key: effective_data_scope(
                        row,
                        user,
                        module_key,
                        key,
                        action_key,
                        action_permissions[action_key],
                    )
                    for action_key in sorted(value["action_keys"] & action_keys)
                },
            }
            for key, value in sorted(launchable_page_access.items())
        },
    }


def effective_page_permissions(
    row: EnterpriseApplication, user: CurrentUser, module_key: str, page_key: str | None
) -> set[str]:
    """Resolve page permissions; v2.0 grants without page_access keep module behaviour."""
    if not page_key:
        return effective_module_permissions(row, user, module_key)
    if not row.is_active or row.deleted_at is not None:
        return set()
    permissions: set[str] = set()
    for grant in _matching_grants(row, user):
        permissions.update(_grant_page_permissions(grant, module_key, page_key))
    return permissions


def action_allowed_for_user(
    row: EnterpriseApplication,
    user: CurrentUser,
    module_key: str,
    page_key: str | None,
    action_key: str,
    required_permission: str,
) -> bool:
    """Require one matching grant to authorize the page, operation and action catalog entry."""
    if not row.is_active or row.deleted_at is not None:
        return False
    return any(
        _grant_allows_action(
            grant,
            module_key,
            page_key,
            action_key,
            required_permission,
        )
        for grant in _matching_grants(row, user)
    )


async def assert_page_permission(
    db: AsyncSession,
    app_id: UUID | str,
    user: CurrentUser,
    module_key: str,
    page_key: str | None,
    permission: str,
) -> EnterpriseApplication:
    row = await get_application(db, app_id)
    if row is None or str(row.organization_id) != str(user.organization_id):
        raise HTTPException(status_code=404, detail="Application not found")
    if permission not in effective_page_permissions(row, user, module_key, page_key):
        raise HTTPException(status_code=403, detail="Application page permission denied")
    return row


async def assert_module_permission(
    db: AsyncSession,
    app_id: UUID | str,
    user: CurrentUser,
    module_key: str,
    permission: str = "view",
) -> tuple[EnterpriseApplication, set[str]]:
    row = await get_application(db, app_id)
    if row is None or str(row.organization_id) != str(user.organization_id):
        raise HTTPException(status_code=404, detail="Application not found")
    permissions = effective_module_permissions(row, user, module_key)
    if permission not in permissions:
        raise HTTPException(status_code=403, detail=f"Module permission '{permission}' required")
    return row, permissions


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
