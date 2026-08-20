"""LLM provider credentials, deployments and explicit verification API."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
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
from app.schemas.llm_provider import (
    LlmProviderCreate,
    LlmProviderRead,
    LlmProviderUpdate,
    ModelCapabilityTestRead,
    ModelDeploymentCreate,
    ModelDeploymentRead,
    ModelDeploymentUpdate,
    ProviderConnectionTestRead,
)
from app.services.llm_provider_service import (
    create_model_deployment,
    create_provider,
    delete_model_deployment,
    get_model_deployment,
    get_provider,
    list_model_deployments,
    list_providers,
    soft_delete_provider,
    update_model_deployment,
    update_provider,
)
from app.services.model_gateway import test_deployment, test_provider_connection
from app.services.organization_service import get_department, get_team

router = APIRouter()


@router.post("/organizations/{org_id}/providers", response_model=LlmProviderRead, status_code=201)
async def create_provider_endpoint(
    org_id: UUID,
    data: LlmProviderCreate,
    _: CurrentAdmin = Depends(require_org_access_write),
    db: AsyncSession = Depends(get_db),
):
    if data.scope_type != "organization":
        raise HTTPException(status_code=400, detail="scope_type must be 'organization' for this endpoint")
    return await create_provider(db, org_id, data)


@router.post("/departments/{dept_id}/providers", response_model=LlmProviderRead, status_code=201)
async def create_dept_provider_endpoint(
    dept_id: UUID,
    data: LlmProviderCreate,
    auth: CurrentAdmin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """创建部门级提供商：调用解析遵循 团队>部门>组织 优先级且继承。"""
    if data.scope_type != "department":
        raise HTTPException(status_code=400, detail="scope_type must be 'department' for this endpoint")
    dept = await get_department(db, dept_id)
    if not dept:
        raise HTTPException(status_code=404, detail="Department not found")
    assert_org_write_access(auth, dept.organization_id)
    return await create_provider(db, dept.organization_id, data, dept_id=dept_id)


@router.post("/teams/{team_id}/providers", response_model=LlmProviderRead, status_code=201)
async def create_team_provider_endpoint(
    team_id: UUID,
    data: LlmProviderCreate,
    auth: CurrentAdmin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """创建团队级提供商：调用解析遵循 团队>部门>组织 优先级且继承。"""
    if data.scope_type != "team":
        raise HTTPException(status_code=400, detail="scope_type must be 'team' for this endpoint")
    team = await get_team(db, team_id)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    assert_org_write_access(auth, team.organization_id)
    return await create_provider(db, team.organization_id, data, team_id=team_id)


@router.get("/organizations/{org_id}/providers", response_model=list[LlmProviderRead])
async def list_providers_endpoint(
    org_id: UUID,
    _: CurrentAdmin = Depends(require_org_access),
    db: AsyncSession = Depends(get_db),
):
    return await list_providers(db, org_id)


@router.get("/providers/{provider_id}", response_model=LlmProviderRead)
async def get_provider_endpoint(
    provider_id: UUID,
    auth: CurrentAdmin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    provider = await get_provider(db, provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    assert_org_access(auth, provider.organization_id)
    return provider


@router.patch("/providers/{provider_id}", response_model=LlmProviderRead)
async def update_provider_endpoint(
    provider_id: UUID,
    data: LlmProviderUpdate,
    auth: CurrentAdmin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    provider = await get_provider(db, provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    assert_org_write_access(auth, provider.organization_id)
    return await update_provider(db, provider, data)


@router.delete("/providers/{provider_id}", status_code=204)
async def delete_provider_endpoint(
    provider_id: UUID,
    auth: CurrentAdmin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    provider = await get_provider(db, provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    assert_org_write_access(auth, provider.organization_id)
    await soft_delete_provider(db, provider)


@router.post("/providers/{provider_id}/test", response_model=ProviderConnectionTestRead)
async def test_provider_endpoint(
    provider_id: UUID,
    auth: CurrentAdmin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    provider = await get_provider(db, provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    assert_org_write_access(auth, provider.organization_id)
    try:
        result = await test_provider_connection(provider)
    except RuntimeError as exc:
        provider.health_status = "degraded"
        await db.flush()
        labels = {
            "network_failure": "网络连接失败",
            "invalid_credentials_or_permission": "凭证无效或无访问权限",
            "endpoint_not_supported": "供应商未提供模型列表接口，请改用单模型能力测试",
            "quota_or_rate_limit": "余额不足、配额不足或请求限流",
            "provider_service_unavailable": "供应商服务暂不可用",
            "provider_rejected_request": "供应商拒绝了测试请求",
        }
        raise HTTPException(status_code=400, detail=labels.get(str(exc), "连接测试失败")) from exc
    provider.health_status = "healthy"
    await db.flush()
    return result


@router.get("/providers/{provider_id}/models", response_model=list[ModelDeploymentRead])
async def list_model_deployments_endpoint(
    provider_id: UUID,
    auth: CurrentAdmin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    provider = await get_provider(db, provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    assert_org_access(auth, provider.organization_id)
    return await list_model_deployments(db, provider_id)


@router.post("/providers/{provider_id}/models", response_model=ModelDeploymentRead, status_code=201)
async def create_model_deployment_endpoint(
    provider_id: UUID,
    data: ModelDeploymentCreate,
    auth: CurrentAdmin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    provider = await get_provider(db, provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    assert_org_write_access(auth, provider.organization_id)
    return await create_model_deployment(db, provider, data)


@router.patch("/providers/{provider_id}/models/{deployment_id}", response_model=ModelDeploymentRead)
async def update_model_deployment_endpoint(
    provider_id: UUID,
    deployment_id: UUID,
    data: ModelDeploymentUpdate,
    auth: CurrentAdmin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    provider = await get_provider(db, provider_id)
    deployment = await get_model_deployment(db, deployment_id)
    if not provider or not deployment or deployment.provider_id != provider_id:
        raise HTTPException(status_code=404, detail="Model deployment not found")
    assert_org_write_access(auth, provider.organization_id)
    return await update_model_deployment(db, deployment, data)


@router.delete("/providers/{provider_id}/models/{deployment_id}", status_code=204)
async def delete_model_deployment_endpoint(
    provider_id: UUID,
    deployment_id: UUID,
    auth: CurrentAdmin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    provider = await get_provider(db, provider_id)
    deployment = await get_model_deployment(db, deployment_id)
    if not provider or not deployment or deployment.provider_id != provider_id:
        raise HTTPException(status_code=404, detail="Model deployment not found")
    assert_org_write_access(auth, provider.organization_id)
    await delete_model_deployment(db, deployment)


@router.post(
    "/providers/{provider_id}/models/{deployment_id}/test/{capability}",
    response_model=ModelCapabilityTestRead,
)
async def test_model_deployment_endpoint(
    provider_id: UUID,
    deployment_id: UUID,
    capability: str,
    auth: CurrentAdmin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    provider = await get_provider(db, provider_id)
    deployment = await get_model_deployment(db, deployment_id)
    if not provider or not deployment or deployment.provider_id != provider_id:
        raise HTTPException(status_code=404, detail="Model deployment not found")
    assert_org_write_access(auth, provider.organization_id)
    if capability not in (deployment.capabilities or []):
        raise HTTPException(status_code=400, detail="能力与该模型部署不匹配")
    try:
        await test_deployment(db, provider, deployment, capability)
    except Exception as exc:
        verified = set((deployment.config or {}).get("verified_capabilities") or [])
        verified.discard(capability)
        deployment.config = {**(deployment.config or {}), "verified_capabilities": sorted(verified)}
        deployment.verification_status = "failed"
        # Upstream bodies can echo request headers or vendor diagnostics.  Persist
        # only a stable category so encrypted credentials never leak through an
        # admin response, audit export or database support dump.
        deployment.last_error = "capability_test_failed"
        await db.flush()
        raise HTTPException(status_code=400, detail="模型测试失败：请检查模型ID、权限、余额和能力类型") from exc
    verified = set((deployment.config or {}).get("verified_capabilities") or [])
    verified.add(capability)
    deployment.config = {**(deployment.config or {}), "verified_capabilities": sorted(verified)}
    all_verified = set(deployment.capabilities or []).issubset(verified)
    deployment.verification_status = "verified" if all_verified else "partially_verified"
    deployment.last_error = None
    await db.flush()
    return ModelCapabilityTestRead(
        status=deployment.verification_status,
        capability=capability,
        model_id=deployment.model_id,
        detail=(
            "全部声明能力已通过真实供应商测试"
            if all_verified else "该能力测试通过；请继续测试其余声明能力后加入生产路由"
        ),
    )
