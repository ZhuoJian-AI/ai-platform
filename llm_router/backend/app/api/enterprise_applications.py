"""Management and terminal APIs for tenant business applications."""

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
    EnterpriseApplicationCreate,
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
from app.services import subsystem_integration_service as integration_service

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
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0), follow_redirects=True) as client:
            response = await client.get(row.entry_url, headers={"user-agent": "AI-Platform-App-Health/1.0"})
            status_code = response.status_code
            healthy = status_code < 500
            if not healthy:
                detail = f"HTTP {status_code}"
    except httpx.HTTPError as exc:
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
    return [
        TerminalEnterpriseApplicationRead(
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
        )
        for row, permissions in rows
    ]


@router.post(
    "/terminal/applications/{app_id}/launch",
    response_model=EnterpriseApplicationLaunchRead,
)
async def launch_terminal_application_endpoint(
    app_id: UUID,
    cu: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    row, permissions = await service.assert_application_permission(db, app_id, cu, "view")
    return EnterpriseApplicationLaunchRead(
        application_id=row.id,
        url=row.entry_url,
        display_mode=row.display_mode,
        permissions=sorted(permissions),
        module_keys=service.effective_module_keys(row, cu),
    )


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
