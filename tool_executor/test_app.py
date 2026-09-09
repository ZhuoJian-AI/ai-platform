from __future__ import annotations

import base64

import pytest
from fastapi.testclient import TestClient

import app as executor_app


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    for key in executor_app.FORBIDDEN_PLATFORM_SECRET_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(executor_app, "EXECUTOR_TOKEN", "test-tool-token")
    return TestClient(executor_app.app)


def _headers() -> dict[str, str]:
    return {"X-Tool-Executor-Token": "test-tool-token"}


def test_health_reports_fixed_executor(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["service"] == "tool-executor"
    assert "text" in body["tool_kinds"]


def test_execute_requires_executor_token(client: TestClient) -> None:
    response = client.post(
        "/execute-builtin",
        json={
            "tool_kind": "text",
            "action": "create",
            "params": {"content": "hello", "filename": "hello.txt"},
            "execution_id": "missing-auth",
        },
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "平台工具执行凭据无效"


def test_execute_text_create_returns_verified_file(client: TestClient) -> None:
    response = client.post(
        "/execute-builtin",
        headers=_headers(),
        json={
            "tool_kind": "text",
            "action": "create",
            "params": {"content": "平台固定工具", "format": "md", "output_name": "result.md"},
            "execution_id": "text-create",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "success"
    assert len(body["outputs"]) == 1
    output = body["outputs"][0]
    assert output["name"] == "result.md"
    assert output["format_verified"] is True
    assert base64.b64decode(output["content_base64"]).decode("utf-8") == "平台固定工具"


def test_arbitrary_code_execution_endpoints_are_gone(client: TestClient) -> None:
    assert client.post("/install", json={}).status_code == 404
    assert client.post("/execute", json={}).status_code == 404
    assert client.get("/cache/inventory").status_code == 404


def test_request_rejects_extra_fields(client: TestClient) -> None:
    response = client.post(
        "/execute-builtin",
        headers=_headers(),
        json={
            "tool_kind": "text",
            "action": "create",
            "params": {"content": "hello"},
            "execution_id": "extra-field",
            "script": "print('should never run')",
        },
    )
    assert response.status_code == 422


def test_input_requires_exactly_one_source(client: TestClient) -> None:
    response = client.post(
        "/execute-builtin",
        headers=_headers(),
        json={
            "tool_kind": "text",
            "action": "inspect",
            "params": {},
            "inputs": [{"file_id": "f1", "name": "input.txt"}],
            "execution_id": "missing-input-source",
        },
    )
    assert response.status_code == 422
    assert "必须且只能提供一种内容来源" in response.json()["detail"]


def test_platform_secrets_fail_health(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://must-not-be-here")
    response = client.get("/health")
    assert response.status_code == 503
    assert response.json()["detail"] == "平台工具执行器包含不应注入的主服务凭据"
