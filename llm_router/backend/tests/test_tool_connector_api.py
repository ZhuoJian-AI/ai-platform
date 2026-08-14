"""Tests for tool connector CRUD, spec import, ontology validation."""

import pytest
from httpx import AsyncClient

from app.tools.ontology_validator import validate_ontology
from app.tools.spec_parser import endpoint_to_skill_definition, parse_spec


async def _make_org(client: AsyncClient, slug: str = "tool-org") -> str:
    r = await client.post("/api/v1/organizations", json={"name": f"公司-{slug}", "slug": slug})
    assert r.status_code == 201
    return r.json()["id"]


SAMPLE_SPEC = {
    "openapi": "3.0.0",
    "paths": {
        "/orders/{id}": {
            "get": {
                "operationId": "getOrder",
                "summary": "获取订单",
                "parameters": [
                    {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}},
                ],
            },
        },
        "/orders": {
            "post": {
                "operationId": "createOrder",
                "summary": "创建订单",
                "parameters": [],
            },
        },
    },
}


# ── spec_parser unit ──

def test_parse_spec_and_skill_definition():
    eps = parse_spec(SAMPLE_SPEC)
    assert len(eps) == 2
    get_ep = next(e for e in eps if e["name"] == "getOrder")
    assert get_ep["method"] == "GET"
    assert get_ep["path"] == "/orders/{id}"
    assert get_ep["params_schema"]["required"] == ["id"]

    skill_def = endpoint_to_skill_definition(get_ep)
    assert skill_def["name"] == "getOrder"
    assert skill_def["parameters"]["required"] == ["id"]


# ── ontology_validator unit ──

def test_validate_ontology_ok_and_errors():
    entities = [{"id": "customer", "name": "客户"}, {"id": "order", "name": "订单"}]
    relations = [{"src": "customer", "dst": "order", "type": "places"}]
    ok, errs = validate_ontology(entities, relations)
    assert ok and errs == []

    bad_ok, bad_errs = validate_ontology(
        [{"id": "x"}, {"id": "x"}],
        [{"src": "x", "dst": "missing"}],
    )
    assert bad_ok is False
    assert any("重复" in e for e in bad_errs)
    assert any("missing" in e for e in bad_errs)


# ── Connector CRUD + spec import ──

@pytest.mark.asyncio
async def test_connector_and_spec_import(client: AsyncClient):
    org_id = await _make_org(client, "conn-org")
    r = await client.post(
        f"/api/v1/organizations/{org_id}/connectors",
        json={"name": "ERP", "slug": "erp", "type": "erp",
              "base_url": "https://erp.example.com", "auth_type": "bearer",
              "auth_config": {"token": "secret"}, "spec": SAMPLE_SPEC},
    )
    assert r.status_code == 201
    conn_id = r.json()["id"]
    assert r.json()["auth_type"] == "bearer"
    # 鉴权配置不应回显
    assert "auth_config" not in r.json()

    # 导入 spec → 生成 endpoints
    imp = await client.post(f"/api/v1/connectors/{conn_id}/import-spec")
    assert imp.status_code == 200
    names = {e["name"] for e in imp.json()}
    assert {"getOrder", "createOrder"} <= names

    eps = await client.get(f"/api/v1/connectors/{conn_id}/endpoints")
    assert len(eps.json()) >= 2


# ── Skill + 本体 CRUD ──

@pytest.mark.asyncio
async def test_skill_crud(client: AsyncClient):
    org_id = await _make_org(client, "sk-org")
    r = await client.post(
        f"/api/v1/organizations/{org_id}/skills",
        json={"name": "查询订单", "slug": "get-order",
              "definition": {"name": "getOrder", "parameters": {}},
              "bound_endpoint_ids": []},
    )
    assert r.status_code == 201
    sid = r.json()["id"]
    assert r.json()["definition"]["name"] == "getOrder"

    g = await client.get(f"/api/v1/skills/{sid}")
    assert g.status_code == 200


@pytest.mark.asyncio
async def test_ontology_crud_and_validate(client: AsyncClient):
    org_id = await _make_org(client, "ont-org")
    r = await client.post(
        f"/api/v1/organizations/{org_id}/ontologies",
        json={"name": "销售本体", "slug": "sales",
              "entities": [{"id": "c", "name": "客户"}, {"id": "o", "name": "订单"}],
              "relations": [{"src": "c", "dst": "o", "type": "places"}]},
    )
    assert r.status_code == 201
    oid = r.json()["id"]

    v = await client.post(f"/api/v1/ontologies/{oid}/validate")
    assert v.status_code == 200
    assert v.json()["ok"] is True
    assert v.json()["errors"] == []
