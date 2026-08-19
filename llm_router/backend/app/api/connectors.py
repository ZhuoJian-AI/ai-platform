"""Tool connector CRUD + spec import + endpoint test/publish API."""

import json

from uuid import UUID

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
from app.database import get_db
from app.models.connector import ToolConnector
from app.schemas.connector import (
    ConnectorSkillPublishRequest,
    EndpointTestRequest,
    ToolConnectorCreate,
    ToolConnectorRead,
    ToolConnectorUpdate,
    ToolEndpointCreate,
    ToolEndpointRead,
    ToolEndpointUpdate,
)
from app.schemas.skill import SkillFileCreate, SkillFolderCreate, SkillFolderRead
from app.services.connector_service import (
    create_connector,
    create_endpoint,
    get_connector,
    get_endpoint,
    import_spec,
    list_connectors,
    list_endpoints,
    soft_delete_connector,
    soft_delete_endpoint,
    update_connector,
    update_endpoint,
)
from app.services.skill_store_service import create_folder, list_folders, upsert_file
from app.tools.executor import execute_endpoint

router = APIRouter()


async def _get_connector_or_404(db: AsyncSession, conn_id: UUID) -> ToolConnector:
    conn = await get_connector(db, conn_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Connector not found")
    return conn


# ── Connector ──

@router.post("/organizations/{org_id}/connectors", response_model=ToolConnectorRead, status_code=201)
async def create_connector_endpoint(
    org_id: UUID, data: ToolConnectorCreate,
    _: CurrentAdmin = Depends(require_org_access_write), db: AsyncSession = Depends(get_db),
):
    try:
        return await create_connector(db, org_id, data)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail=f"Slug '{data.slug}' already exists")


@router.get("/organizations/{org_id}/connectors", response_model=list[ToolConnectorRead])
async def list_connectors_endpoint(
    org_id: UUID, _: CurrentAdmin = Depends(require_org_access), db: AsyncSession = Depends(get_db),
):
    return await list_connectors(db, org_id)


@router.get("/connectors/{conn_id}", response_model=ToolConnectorRead)
async def get_connector_endpoint(
    conn_id: UUID, auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    conn = await _get_connector_or_404(db, conn_id)
    assert_org_access(auth, conn.organization_id)
    return conn


@router.patch("/connectors/{conn_id}", response_model=ToolConnectorRead)
async def update_connector_endpoint(
    conn_id: UUID, data: ToolConnectorUpdate,
    auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    conn = await _get_connector_or_404(db, conn_id)
    assert_org_write_access(auth, conn.organization_id)
    return await update_connector(db, conn, data)


@router.delete("/connectors/{conn_id}", status_code=204)
async def delete_connector_endpoint(
    conn_id: UUID, auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    conn = await _get_connector_or_404(db, conn_id)
    assert_org_write_access(auth, conn.organization_id)
    await soft_delete_connector(db, conn)


# ── Spec import ──

@router.post("/connectors/{conn_id}/import-spec", response_model=list[ToolEndpointRead])
async def import_spec_endpoint(
    conn_id: UUID,
    auth: CurrentAdmin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    conn = await _get_connector_or_404(db, conn_id)
    assert_org_write_access(auth, conn.organization_id)
    if not conn.spec:
        raise HTTPException(status_code=400, detail="Connector has no spec to import")
    return await import_spec(db, conn)


@router.post(
    "/connectors/{conn_id}/publish-skill",
    response_model=SkillFolderRead,
    status_code=201,
)
async def publish_connector_skill_endpoint(
    conn_id: UUID,
    data: ConnectorSkillPublishRequest,
    auth: CurrentAdmin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Expose selected enterprise API endpoints to the agent runtime as a Skill.

    Connector credentials remain on the connector.  The generated Skill only
    stores endpoint UUIDs and the human-facing instructions/schema, so users
    never receive the enterprise secret.
    """
    conn = await _get_connector_or_404(db, conn_id)
    assert_org_write_access(auth, conn.organization_id)

    endpoint_ids: list[str] = []
    endpoint_docs: list[str] = []
    for endpoint_id in data.endpoint_ids:
        endpoint = await get_endpoint(db, endpoint_id)
        if endpoint is None or str(endpoint.connector_id) != str(conn.id):
            raise HTTPException(status_code=422, detail=f"Endpoint {endpoint_id} does not belong to connector")
        endpoint_ids.append(str(endpoint.id))
        endpoint_docs.append(
            f"- `{endpoint.name}` — `{endpoint.method} {endpoint.path}`"
            + (f"：{endpoint.description}" if endpoint.description else "")
        )

    # Function names sent to OpenAI-compatible providers must use a restricted
    # alphabet.  Keep the folder slug user-friendly and use an underscore form
    # as the manifest namespace.
    manifest_name = data.slug.replace("-", "_")
    manifest = {
        "name": manifest_name,
        "description": data.description or f"调用 {conn.name} 的企业接口",
        "parameters": {"type": "object", "properties": {}},
        "bound_endpoint_ids": endpoint_ids,
        "user_invocable": True,
    }
    skill_md = (
        "```skill\n"
        + json.dumps(manifest, ensure_ascii=False, indent=2)
        + "\n```\n\n"
        + f"# {data.name}\n\n"
        + (data.description or f"通过 {conn.name} 连接器调用企业系统。")
        + "\n\n## 可调用端点\n\n"
        + "\n".join(endpoint_docs)
        + "\n\n调用前根据端点参数结构收集必填参数；接口返回后再向用户解释结果。\n"
    )
    existing_folders = await list_folders(db, conn.organization_id, "organization", None)
    if any(folder.slug == data.slug for folder in existing_folders):
        raise HTTPException(status_code=409, detail=f"Skill slug '{data.slug}' already exists")
    try:
        folder = await create_folder(
            db,
            conn.organization_id,
            SkillFolderCreate(
                name=data.name,
                slug=data.slug,
                scope_type="organization",
                scope_id=None,
            ),
        )
        await upsert_file(
            db,
            folder,
            SkillFileCreate(path="skill.md", content=skill_md, metadata={"connector_id": str(conn.id)}),
        )
        await db.refresh(folder, ["files"])
        return folder
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail=f"Skill slug '{data.slug}' already exists")


# ── Endpoints ──

@router.get("/connectors/{conn_id}/endpoints", response_model=list[ToolEndpointRead])
async def list_endpoints_endpoint(
    conn_id: UUID, auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    conn = await _get_connector_or_404(db, conn_id)
    assert_org_access(auth, conn.organization_id)
    return await list_endpoints(db, conn_id)


@router.post("/connectors/{conn_id}/endpoints", response_model=ToolEndpointRead, status_code=201)
async def create_endpoint_endpoint(
    conn_id: UUID, data: ToolEndpointCreate,
    auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    conn = await _get_connector_or_404(db, conn_id)
    assert_org_write_access(auth, conn.organization_id)
    return await create_endpoint(db, conn, data)


@router.patch("/endpoints/{ep_id}", response_model=ToolEndpointRead)
async def update_endpoint_endpoint(
    ep_id: UUID, data: ToolEndpointUpdate,
    auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    ep = await get_endpoint(db, ep_id)
    if not ep:
        raise HTTPException(status_code=404, detail="Endpoint not found")
    conn = await _get_connector_or_404(db, ep.connector_id)
    assert_org_write_access(auth, conn.organization_id)
    return await update_endpoint(db, ep, data)


@router.delete("/endpoints/{ep_id}", status_code=204)
async def delete_endpoint_endpoint(
    ep_id: UUID, auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    ep = await get_endpoint(db, ep_id)
    if not ep:
        raise HTTPException(status_code=404, detail="Endpoint not found")
    conn = await _get_connector_or_404(db, ep.connector_id)
    assert_org_write_access(auth, conn.organization_id)
    await soft_delete_endpoint(db, ep)


# ── Endpoint test (playground) ──

@router.post("/endpoints/{ep_id}/test")
async def test_endpoint_endpoint(
    ep_id: UUID, data: EndpointTestRequest,
    auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    ep = await get_endpoint(db, ep_id)
    if not ep:
        raise HTTPException(status_code=404, detail="Endpoint not found")
    conn = await get_connector(db, ep.connector_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Connector not found")
    assert_org_write_access(auth, conn.organization_id)
    result = await execute_endpoint(
        db, org_id=conn.organization_id, connector=conn, endpoint=ep, params=data.params,
    )
    return {
        "status_code": result.status_code,
        "latency_ms": result.latency_ms,
        "body": result.body,
        "error": result.error,
    }
