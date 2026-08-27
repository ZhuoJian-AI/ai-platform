"""Tests for tool connector CRUD, spec import, ontology validation."""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tool_call_log import ToolCallLog
from app.tools.ontology_validator import validate_ontology
from app.tools.openapi_loader import parse_openapi_document
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


def test_parse_openapi_document_accepts_yaml_and_rejects_invalid_content():
    parsed = parse_openapi_document(
        """openapi: 3.0.0
info:
  title: Purchase API
paths:
  /orders:
    get:
      operationId: listOrders
"""
    )
    assert parsed["info"]["title"] == "Purchase API"
    with pytest.raises(ValueError, match="missing the openapi/swagger version"):
        parse_openapi_document('{"paths":{"/orders":{}}}')


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


@pytest.mark.asyncio
async def test_inspect_openapi_spec_without_persisting_connector(client: AsyncClient):
    org_id = await _make_org(client, "inspect-spec-org")
    inspected = await client.post(
        f"/api/v1/organizations/{org_id}/connectors/inspect-spec",
        json={"content": """openapi: 3.0.0
info:
  title: Purchase API
  version: v1
paths:
  /orders:
    get:
      operationId: listOrders
      summary: 查询采购订单
"""},
    )
    assert inspected.status_code == 200
    body = inspected.json()
    assert body["title"] == "Purchase API"
    assert body["version"] == "v1"
    assert body["endpoints"][0]["name"] == "listOrders"

    connectors_response = await client.get(f"/api/v1/organizations/{org_id}/connectors")
    assert connectors_response.json() == []


@pytest.mark.asyncio
async def test_manual_endpoint_test_and_publish_as_chat_skill(
    client: AsyncClient, db_session: AsyncSession,
):
    org_id = await _make_org(client, "publish-connector-org")
    conn = await client.post(
        f"/api/v1/organizations/{org_id}/connectors",
        json={
            "name": "库存 ERP",
            "slug": "inventory-erp",
            "type": "erp",
            "base_url": "https://erp.example.com",
            "auth_type": "apikey",
            "auth_config": {"header_key": "X-API-Key", "api_key": "secret"},
        },
    )
    assert conn.status_code == 201
    conn_id = conn.json()["id"]

    endpoint = await client.post(
        f"/api/v1/connectors/{conn_id}/endpoints",
        json={
            "name": "query inventory",
            "method": "GET",
            "path": "/inventory/{sku}",
            "description": "按 SKU 查询库存",
            "params_schema": {
                "type": "object",
                "properties": {"sku": {"type": "string"}, "warehouse": {"type": "string"}},
                "required": ["sku"],
            },
        },
    )
    assert endpoint.status_code == 201
    endpoint_id = endpoint.json()["id"]

    response = Response(
        200,
        json={"sku": "SKU001", "warehouse": "上海仓", "available_quantity": 120},
        request=Request("GET", "https://erp.example.com/inventory/SKU001"),
    )

    request_mock = AsyncMock(return_value=response)

    class ExternalClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        request = request_mock

    with patch("app.tools.executor.httpx.AsyncClient", ExternalClient):
        tested = await client.post(
            f"/api/v1/endpoints/{endpoint_id}/test",
            json={"params": {"sku": "SKU001", "warehouse": "上海仓"}},
        )
    assert tested.status_code == 200
    assert tested.json()["body"]["available_quantity"] == 120
    log = (await db_session.execute(select(ToolCallLog))).scalar_one()
    assert str(log.endpoint_id) == endpoint_id
    assert log.skill_id is None
    assert log.status_code == 200
    call = request_mock.await_args
    assert call.args[0] == "GET"
    assert call.args[1].endswith("/inventory/SKU001")
    assert call.kwargs["params"] == {"warehouse": "上海仓"}
    assert call.kwargs["headers"]["X-API-Key"] == "secret"

    published = await client.post(
        f"/api/v1/connectors/{conn_id}/publish-skill",
        json={
            "name": "库存查询助手",
            "slug": "inventory-query",
            "description": "查询 ERP 库存",
            "endpoint_ids": [endpoint_id],
        },
    )
    assert published.status_code == 201
    folder = published.json()
    assert folder["scope_type"] == "organization"
    assert folder["is_installed"] is True

    files = await client.get(f"/api/v1/skill-folders/{folder['id']}/files")
    assert files.status_code == 200
    skill_file = await client.get(f"/api/v1/skill-files/{files.json()[0]['id']}")
    content = skill_file.json()["content"]
    assert endpoint_id in content
    assert "query inventory" in content

    duplicate = await client.post(
        f"/api/v1/connectors/{conn_id}/publish-skill",
        json={
            "name": "重复",
            "slug": "inventory-query",
            "endpoint_ids": [endpoint_id],
        },
    )
    assert duplicate.status_code == 409


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
