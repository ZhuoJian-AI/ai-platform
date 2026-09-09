"""Compatibility coverage for retired duplicate tool abstractions."""

import pytest
from httpx import AsyncClient

from app.main import app


def test_all_retired_product_routes_are_absent_from_openapi():
    paths = app.openapi()["paths"]
    retired_fragments = (
        "/connectors",
        "/data-systems",
        "/data-interfaces",
        "/tool-bindings",
        "/ontologies",
        "/judges",
        "/oauth",
        "/mcp",
        "/platform-extensions",
        "/module-publisher",
        "/teams",
        "/office-edit",
        "/scope-manager",
        "/rag",
        "/skills",
    )
    assert not any(fragment in path for path in paths for fragment in retired_fragments)


async def _make_org(client: AsyncClient, slug: str) -> str:
    response = await client.post(
        "/api/v1/organizations",
        json={"name": f"公司-{slug}", "slug": slug},
    )
    assert response.status_code == 201
    return response.json()["id"]


@pytest.mark.asyncio
async def test_connector_and_data_interface_routes_are_absent(client: AsyncClient):
    org_id = await _make_org(client, "retired-connector")
    checks = [
        await client.get(f"/api/v1/organizations/{org_id}/connectors"),
        await client.post(
            f"/api/v1/organizations/{org_id}/connectors",
            json={"name": "ERP", "slug": "erp", "base_url": "https://example.test"},
        ),
        await client.get(f"/api/v1/organizations/{org_id}/data-systems"),
        await client.get("/api/v1/terminal/data-systems"),
    ]
    assert {response.status_code for response in checks} == {404}
    openapi = (await client.get("/openapi.json")).json()
    retired_fragments = ("/connectors", "/data-systems", "/data-interfaces", "/tool-bindings")
    assert not any(
        fragment in path
        for path in openapi["paths"]
        for fragment in retired_fragments
    )


@pytest.mark.asyncio
async def test_ontology_surface_is_retired(client: AsyncClient):
    org_id = await _make_org(client, "retired-ontology")
    response = await client.get(f"/api/v1/organizations/{org_id}/ontologies")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_platform_rag_and_user_skill_products_are_retired(client: AsyncClient):
    org_id = await _make_org(client, "retired-definition-skill")
    responses = [
        await client.get(f"/api/v1/organizations/{org_id}/skills"),
        await client.get(f"/api/v1/organizations/{org_id}/rag"),
        await client.get("/api/v1/terminal/rag"),
    ]
    assert {response.status_code for response in responses} == {404}
