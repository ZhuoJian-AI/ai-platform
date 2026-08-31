"""Management and terminal APIs for tenant business applications."""

from urllib.parse import urlencode, urljoin
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.admin_auth import (
    CurrentAdmin,
    assert_org_access,
    assert_org_write_access,
    require_admin,
    require_org_access,
    require_org_access_write,
)
from app.auth.user_auth import CurrentUser, require_user
from app.database import get_db
from app.schemas.enterprise_application import (
    CrossDepartmentWorkItemRead,
    CrossDepartmentWorkItemUpdate,
    EnterpriseApplicationActionInvoke,
    EnterpriseApplicationActionRead,
    EnterpriseApplicationActionRequestRead,
    EnterpriseApplicationActionResultRead,
    EnterpriseApplicationCreate,
    EnterpriseApplicationDiscoveryInput,
    EnterpriseApplicationDiscoveryRead,
    EnterpriseApplicationEventRouteRead,
    EnterpriseApplicationEventRoutesReplace,
    EnterpriseApplicationGrantsReplace,
    EnterpriseApplicationHealthRead,
    EnterpriseApplicationIntegrationInput,
    EnterpriseApplicationIntegrationRead,
    EnterpriseApplicationLaunchRead,
    EnterpriseApplicationOverviewRead,
    EnterpriseApplicationRead,
    EnterpriseApplicationSyncRead,
    EnterpriseApplicationToolBindingsReplace,
    EnterpriseApplicationUpdate,
    TerminalEnterpriseApplicationRead,
)
from app.services import enterprise_application_service as service
from app.services import subsystem_action_service as action_service
from app.services import subsystem_integration_service as integration_service
from app.utils.public_url import assert_public_http_url, same_origin

router = APIRouter()


async def _application_or_404(db: AsyncSession, app_id: UUID):
    row = await service.get_application(db, app_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Application not found")
    return row


@router.post(
    "/organizations/{org_id}/applications",
    response_model=EnterpriseApplicationRead,
    status_code=201,
)
async def create_application_endpoint(
    org_id: UUID,
    data: EnterpriseApplicationCreate,
    _: CurrentAdmin = Depends(require_org_access_write),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await service.create_application(db, org_id, data)
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail=f"Application slug '{data.slug}' already exists") from exc


@router.post(
    "/organizations/{org_id}/applications/discover",
    response_model=EnterpriseApplicationDiscoveryRead,
)
async def discover_application_endpoint(
    org_id: UUID,
    data: EnterpriseApplicationDiscoveryInput,
    _: CurrentAdmin = Depends(require_org_access_write),
    db: AsyncSession = Depends(get_db),
):
    return await integration_service.discover_subsystem(
        db, org_id, str(data.base_url), data.auth_token
    )


@router.get("/organizations/{org_id}/applications", response_model=list[EnterpriseApplicationRead])
async def list_applications_endpoint(
    org_id: UUID,
    _: CurrentAdmin = Depends(require_org_access),
    db: AsyncSession = Depends(get_db),
):
    return await service.list_applications(db, org_id)


@router.get("/applications/{app_id}", response_model=EnterpriseApplicationRead)
async def get_application_endpoint(
    app_id: UUID,
    auth: CurrentAdmin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    row = await _application_or_404(db, app_id)
    assert_org_access(auth, row.organization_id)
    return row


@router.get("/applications/{app_id}/overview", response_model=EnterpriseApplicationOverviewRead)
async def get_application_overview_endpoint(
    app_id: UUID,
    auth: CurrentAdmin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    row = await _application_or_404(db, app_id)
    assert_org_access(auth, row.organization_id)
    return await service.get_application_overview(db, row)


@router.patch("/applications/{app_id}", response_model=EnterpriseApplicationRead)
async def update_application_endpoint(
    app_id: UUID,
    data: EnterpriseApplicationUpdate,
    auth: CurrentAdmin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    row = await _application_or_404(db, app_id)
    assert_org_write_access(auth, row.organization_id)
    return await service.update_application(db, row, data)


@router.delete("/applications/{app_id}", status_code=204)
async def delete_application_endpoint(
    app_id: UUID,
    auth: CurrentAdmin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    row = await _application_or_404(db, app_id)
    assert_org_write_access(auth, row.organization_id)
    await service.soft_delete_application(db, row)


@router.put("/applications/{app_id}/grants", response_model=EnterpriseApplicationRead)
async def replace_application_grants_endpoint(
    app_id: UUID,
    data: EnterpriseApplicationGrantsReplace,
    auth: CurrentAdmin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    row = await _application_or_404(db, app_id)
    assert_org_write_access(auth, row.organization_id)
    return await service.replace_grants(db, row, data.grants)


@router.put("/applications/{app_id}/tool-bindings", response_model=EnterpriseApplicationRead)
async def replace_application_tool_bindings_endpoint(
    app_id: UUID,
    data: EnterpriseApplicationToolBindingsReplace,
    auth: CurrentAdmin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    row = await _application_or_404(db, app_id)
    assert_org_write_access(auth, row.organization_id)
    return await service.replace_tool_bindings(db, row, data.bindings)


@router.get(
    "/applications/{app_id}/integration",
    response_model=EnterpriseApplicationIntegrationRead,
)
async def get_application_integration_endpoint(
    app_id: UUID,
    auth: CurrentAdmin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    row = await _application_or_404(db, app_id)
    assert_org_access(auth, row.organization_id)
    integration = await integration_service.get_integration(db, row.id)
    if integration is None:
        raise HTTPException(status_code=404, detail="Subsystem integration is not configured")
    return integration_service.integration_read(integration)


@router.put(
    "/applications/{app_id}/integration",
    response_model=EnterpriseApplicationIntegrationRead,
)
async def configure_application_integration_endpoint(
    app_id: UUID,
    data: EnterpriseApplicationIntegrationInput,
    auth: CurrentAdmin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    row = await _application_or_404(db, app_id)
    assert_org_write_access(auth, row.organization_id)
    integration = await integration_service.configure_integration(db, row, data)
    return integration_service.integration_read(integration)


@router.post(
    "/applications/{app_id}/integration/sync",
    response_model=EnterpriseApplicationSyncRead,
)
async def sync_application_integration_endpoint(
    app_id: UUID,
    auth: CurrentAdmin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    row = await _application_or_404(db, app_id)
    assert_org_write_access(auth, row.organization_id)
    return await integration_service.sync_integration(db, row)


@router.get(
    "/applications/{app_id}/actions",
    response_model=list[EnterpriseApplicationActionRead],
)
async def list_application_actions_endpoint(
    app_id: UUID,
    auth: CurrentAdmin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    row = await _application_or_404(db, app_id)
    assert_org_access(auth, row.organization_id)
    return await action_service.list_actions(db, row.id)


@router.get(
    "/applications/{app_id}/event-routes",
    response_model=list[EnterpriseApplicationEventRouteRead],
)
async def list_application_event_routes_endpoint(
    app_id: UUID,
    auth: CurrentAdmin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    row = await _application_or_404(db, app_id)
    assert_org_access(auth, row.organization_id)
    return await integration_service.list_routes(db, row.id)


@router.put(
    "/applications/{app_id}/event-routes",
    response_model=list[EnterpriseApplicationEventRouteRead],
)
async def replace_application_event_routes_endpoint(
    app_id: UUID,
    data: EnterpriseApplicationEventRoutesReplace,
    auth: CurrentAdmin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    row = await _application_or_404(db, app_id)
    assert_org_write_access(auth, row.organization_id)
    return await integration_service.replace_routes(db, row, data.routes)


@router.post("/applications/{app_id}/test", response_model=EnterpriseApplicationHealthRead)
async def test_application_endpoint(
    app_id: UUID,
    auth: CurrentAdmin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    row = await _application_or_404(db, app_id)
    assert_org_write_access(auth, row.organization_id)
    status_code: int | None = None
    detail: str | None = None
    healthy = False
    try:
        health_url = urljoin(row.entry_url.rstrip("/") + "/", "health")
        assert_public_http_url(health_url, require_https=True)
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0), follow_redirects=False) as client:
            response = await client.get(health_url, headers={"user-agent": "AI-Platform-App-Health/2.0"})
            status_code = response.status_code
            healthy = 200 <= status_code < 300
            if not healthy:
                detail = f"HTTP {status_code}"
    except (httpx.HTTPError, ValueError) as exc:
        detail = str(exc)[:500]
    row.health_status = "healthy" if healthy else "unhealthy"
    await db.flush()
    return EnterpriseApplicationHealthRead(
        status="healthy" if healthy else "unhealthy",
        status_code=status_code,
        detail=detail,
    )


@router.get("/terminal/applications", response_model=list[TerminalEnterpriseApplicationRead])
async def terminal_applications_endpoint(
    cu: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    rows = await service.list_applications_for_user(db, cu)
    applications: list[TerminalEnterpriseApplicationRead] = []
    for row, permissions in rows:
        visible_modules = service.visible_manifest_modules(row, cu)
        applications.append(TerminalEnterpriseApplicationRead(
            id=row.id,
            name=row.name,
            slug=row.slug,
            description=row.description,
            icon_url=row.icon_url,
            display_mode=row.display_mode,
            sort_order=row.sort_order,
            assistant_enabled=row.assistant_enabled,
            permissions=sorted(permissions),
            module_keys=service.effective_module_keys(row, cu),
            modules=visible_modules,
        ))
    return applications


@router.post(
    "/terminal/applications/{app_id}/launch",
    response_model=EnterpriseApplicationLaunchRead,
)
async def launch_terminal_application_endpoint(
    app_id: UUID,
    module_key: str | None = None,
    cu: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    row, permissions = await service.assert_application_permission(db, app_id, cu, "view")
    module_keys = service.effective_module_keys(row, cu)
    integration = await integration_service.get_integration(db, row.id)
    launch_url = row.entry_url
    selected_module = module_key
    accessible_modules: list[dict[str, str]] = []
    if integration is not None and integration.protocol_version >= 2:
        if not integration.sync_enabled or not integration.auth_token_encrypted:
            raise HTTPException(status_code=409, detail="Subsystem access has been revoked")
        modules = integration.manifest.get("modules") if isinstance(integration.manifest, dict) else []
        modules = modules if isinstance(modules, list) else []
        accessible_modules = service.visible_manifest_modules(row, cu)
        if selected_module is None:
            selected_module = accessible_modules[0]["module_key"] if accessible_modules else None
        if selected_module is None:
            raise HTTPException(status_code=409, detail="Subsystem manifest has no launchable module")
        row, module_permissions = await service.assert_module_permission(
            db, app_id, cu, selected_module, "view"
        )
        module = next(
            (item for item in modules if isinstance(item, dict) and item.get("moduleKey") == selected_module),
            None,
        )
        if module is None:
            raise HTTPException(status_code=404, detail="Subsystem module not found")
        module_claims = service.effective_module_claims(row, cu, selected_module)
        redirect_path = str(module.get("route") or "/")
        page_access = module_claims.get("page_access")
        if isinstance(page_access, dict):
            authorized_pages = [
                page for page in (module.get("pages") or [])
                if isinstance(page, dict) and page.get("pageKey") in page_access
            ]
            authorized_routes = [
                str(page.get("routePattern")) for page in authorized_pages
                if isinstance(page.get("routePattern"), str)
            ]
            if not authorized_routes:
                raise HTTPException(status_code=403, detail="Module has no authorized launch page")
            if redirect_path not in authorized_routes:
                redirect_path = authorized_routes[0]
        auth = integration.manifest.get("auth") if isinstance(integration.manifest.get("auth"), dict) else {}
        sso_path = str(auth.get("ssoPath") or "/api/integration/sso")
        sso_url = urljoin(row.entry_url.rstrip("/") + "/", sso_path)
        if not same_origin(row.entry_url, sso_url):
            raise HTTPException(status_code=409, detail="SSO endpoint left the registered application origin")
        ticket = action_service.issue_launch_ticket(
            integration,
            row,
            cu,
            selected_module,
            module_permissions,
            module_claims,
        )
        launch_url = f"{sso_url}?{urlencode({'ticket': ticket, 'redirect': redirect_path})}"
    return EnterpriseApplicationLaunchRead(
        application_id=row.id,
        url=launch_url,
        display_mode=row.display_mode,
        permissions=sorted(permissions),
        module_keys=[item["module_key"] for item in accessible_modules] if accessible_modules else module_keys,
        module_key=selected_module,
        modules=accessible_modules,
    )


@router.post(
    "/terminal/applications/{app_id}/actions/{action_key}",
    response_model=EnterpriseApplicationActionResultRead,
)
async def invoke_terminal_application_action_endpoint(
    app_id: UUID,
    action_key: str,
    data: EnterpriseApplicationActionInvoke,
    cu: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    return await action_service.invoke_action(
        db,
        app_id,
        action_key,
        data.module_key,
        data.params,
        cu,
        request_id=data.request_id,
        page_key=data.page_key,
        operation=data.operation,
        expected_version=data.expected_version,
    )


@router.get(
    "/terminal/application-action-confirmations",
    response_model=list[EnterpriseApplicationActionRequestRead],
)
async def list_terminal_application_action_confirmations_endpoint(
    cu: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    return await action_service.list_confirmation_requests(db, cu)


@router.post(
    "/terminal/application-action-confirmations/{confirmation_id}/approve",
    response_model=EnterpriseApplicationActionResultRead,
)
async def approve_terminal_application_action_endpoint(
    confirmation_id: UUID,
    cu: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    return await action_service.resolve_confirmation(db, confirmation_id, cu, approve=True)


@router.post(
    "/terminal/application-action-confirmations/{confirmation_id}/reject",
    response_model=EnterpriseApplicationActionResultRead,
)
async def reject_terminal_application_action_endpoint(
    confirmation_id: UUID,
    cu: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    return await action_service.resolve_confirmation(db, confirmation_id, cu, approve=False)


@router.get("/terminal/cross-department-work-items", response_model=list[CrossDepartmentWorkItemRead])
async def terminal_cross_department_work_items_endpoint(
    cu: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    return await integration_service.list_work_items_for_user(db, cu)


@router.patch(
    "/terminal/cross-department-work-items/{item_id}",
    response_model=CrossDepartmentWorkItemRead,
)
async def update_terminal_cross_department_work_item_endpoint(
    item_id: UUID,
    data: CrossDepartmentWorkItemUpdate,
    cu: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    return await integration_service.update_work_item_status(db, cu, item_id, data.status)
