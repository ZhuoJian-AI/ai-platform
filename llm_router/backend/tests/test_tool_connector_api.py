"""Compatibility coverage for retired duplicate tool abstractions."""

import pytest
from httpx import AsyncClient


async def _make_org(client: AsyncClient, slug: str) -> str:
    response = await client.post(
        "/api/v1/organizations",
        json={"name": f"公司-{slug}", "slug": slug},
    )
    assert response.status_code == 201
    return response.json()["id"]


@pytest.mark.asyncio
async def test_connector_configuration_writes_are_retired(client: AsyncClient):
    org_id = await _make_org(client, "retired-connector")
    create = await client.post(
        f"/api/v1/organizations/{org_id}/connectors",
        json={"name": "ERP", "slug": "erp", "type": "erp", "base_url": "https://example.test"},
    )
    assert create.status_code == 410
    assert "Connector" in create.json()["detail"]["message"]

    inspect = await client.post(
        f"/api/v1/organizations/{org_id}/connectors/inspect-spec",
        json={"content": '{"openapi":"3.0.0","paths":{}}'},
    )
    assert inspect.status_code == 410


@pytest.mark.asyncio
async def test_ontology_surface_is_retired(client: AsyncClient):
    org_id = await _make_org(client, "retired-ontology")
    response = await client.get(f"/api/v1/organizations/{org_id}/ontologies")
    assert response.status_code == 410
    assert "Ontology" in response.json()["detail"]["message"]


@pytest.mark.asyncio
async def test_old_definition_skill_is_retired_without_affecting_skill_packages(client: AsyncClient):
    org_id = await _make_org(client, "retired-definition-skill")
    response = await client.get(f"/api/v1/organizations/{org_id}/skills")
    assert response.status_code == 410
    assert "旧 Definition Skill" in response.json()["detail"]["message"]
