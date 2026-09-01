"""Tests for API management routes."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.workspace import Workspace


@pytest.mark.asyncio
async def test_health_check(client: AsyncClient):
    """测试健康检查端点。"""
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_create_organization(client: AsyncClient):
    """测试创建组织。"""
    resp = await client.post(
        "/api/v1/organizations",
        json={"name": "测试公司", "slug": "test-company"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "测试公司"
    assert data["slug"] == "test-company"
    assert "id" in data


@pytest.mark.asyncio
async def test_list_organizations(client: AsyncClient):
    """测试列出组织。"""
    # 先创建
    await client.post(
        "/api/v1/organizations",
        json={"name": "公司A", "slug": "company-a"},
    )
    resp = await client.get("/api/v1/organizations")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1


@pytest.mark.asyncio
async def test_create_department(client: AsyncClient):
    """测试在组织下创建部门。"""
    # 先创建组织
    org_resp = await client.post(
        "/api/v1/organizations",
        json={"name": "测试组织", "slug": "test-org"},
    )
    org_id = org_resp.json()["id"]

    # 创建部门
    resp = await client.post(
        f"/api/v1/organizations/{org_id}/departments",
        json={"name": "研发部", "slug": "rd"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "研发部"
    assert data["organization_id"] == org_id


@pytest.mark.asyncio
async def test_recreate_department_with_deleted_slug_gets_a_new_workspace(
    client: AsyncClient,
    db_session: AsyncSession,
):
    """新部门可复用已删除部门的 slug，但不得复活旧部门的工作空间。"""
    org_resp = await client.post(
        "/api/v1/organizations",
        json={"name": "工作空间隔离测试组织", "slug": "workspace-isolation-org"},
    )
    org_id = org_resp.json()["id"]

    first_resp = await client.post(
        f"/api/v1/organizations/{org_id}/departments",
        json={"name": "原设计部", "slug": "design-dept"},
    )
    assert first_resp.status_code == 201
    first_department_id = first_resp.json()["id"]

    delete_resp = await client.delete(f"/api/v1/departments/{first_department_id}")
    assert delete_resp.status_code == 204

    second_resp = await client.post(
        f"/api/v1/organizations/{org_id}/departments",
        json={"name": "新设计部", "slug": "design-dept"},
    )
    assert second_resp.status_code == 201
    second_department_id = second_resp.json()["id"]
    assert second_department_id != first_department_id

    workspaces = list(
        (
            await db_session.execute(
                select(Workspace).where(
                    Workspace.organization_id == org_id,
                    Workspace.slug == "design-dept",
                )
            )
        ).scalars()
    )
    assert len(workspaces) == 2
    assert {workspace.scope_id for workspace in workspaces} == {
        first_department_id,
        second_department_id,
    }
    active_workspaces = [workspace for workspace in workspaces if workspace.deleted_at is None]
    assert len(active_workspaces) == 1
    assert active_workspaces[0].scope_id == second_department_id


@pytest.mark.asyncio
async def test_create_llm_provider(client: AsyncClient):
    """测试创建 LLM 提供商。"""
    # 先创建组织
    org_resp = await client.post(
        "/api/v1/organizations",
        json={"name": "AI公司", "slug": "ai-company"},
    )
    org_id = org_resp.json()["id"]

    # 创建提供商
    resp = await client.post(
        f"/api/v1/organizations/{org_id}/providers",
        json={
            "name": "Anthropic Direct",
            "provider_type": "anthropic",
            "base_url": "https://api.anthropic.com",
            "api_key": "sk-ant-test-key",
            "supported_models": ["claude-opus-4-8", "claude-sonnet-4-6"],
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Anthropic Direct"
    assert data["provider_type"] == "anthropic"
    assert "claude-opus-4-8" in data["supported_models"]
