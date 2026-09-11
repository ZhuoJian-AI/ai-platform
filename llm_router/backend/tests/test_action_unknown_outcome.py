from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest

from app.services import subsystem_action_service as service


@pytest.mark.parametrize("operation", ["create", "update", "delete", "approve", "query", "export"])
@pytest.mark.parametrize("failure,code,uncertain", [
    (httpx.ReadTimeout("late"), None, True),
    (httpx.WriteError("interrupted"), None, True),
    (httpx.ConnectTimeout("connect"), None, False),
    (httpx.ConnectError("connect"), None, False),
    (httpx.PoolTimeout("pool"), None, False),
    (ValueError("invalid result"), 200, True),
    (RuntimeError("error"), 503, True),
    (RuntimeError("error"), 408, True),
    (RuntimeError("error"), 409, False),
    (RuntimeError("error"), 422, False),
])
def test_uncertainty_is_not_confused_with_rejection(operation, failure, code, uncertain):
    response = httpx.Response(code) if code else None
    assert service._write_outcome_unknown(operation, failure, response) == (
        uncertain and operation not in {"query", "export"}
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("matches", [True, False])
async def test_identical_unknown_request_is_reused_not_resubmitted(monkeypatch, matches):
    app = SimpleNamespace(id=uuid4(), organization_id=uuid4())
    action = SimpleNamespace(id=uuid4(), module_key="orders", operation="update")
    user = SimpleNamespace(id=str(uuid4()))
    row = SimpleNamespace(params_encrypted=service._request_payload({"owner": "李娜"}, "main", 3))
    db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(
        scalars=lambda: SimpleNamespace(all=lambda: [row]),
    )))
    monkeypatch.setattr(service, "decrypt_provider_api_key", lambda value: value)
    result = await service._unresolved_identical_write(
        db, app, action, user, {"owner": "李娜" if matches else "李四"}, "main", 3,
    )
    assert result is (row if matches else None)
    statement = str(db.execute.call_args.args[0])
    for scope in ("application_id", "organization_id", "user_id", "action_id", "module_key", "status"):
        assert scope in statement


@pytest.mark.asyncio
async def test_reads_do_not_get_blocked_by_unknown_writes():
    db = SimpleNamespace(execute=AsyncMock())
    assert await service._unresolved_identical_write(
        db, None, SimpleNamespace(operation="query"), None, {}, None, None,
    ) is None
    db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_new_request_id_reuses_unknown_receipt_before_creating_a_confirmation(monkeypatch):
    app = SimpleNamespace(id=uuid4(), organization_id=uuid4(), slug="app", assistant_enabled=True)
    action = SimpleNamespace(id=uuid4(), module_key="orders", action_key="change", operation="update",
                             ai_enabled=True, requires_confirmation=True)
    user = SimpleNamespace(id=str(uuid4()), organization_id=app.organization_id)
    original = SimpleNamespace(id=uuid4(), request_id="original", status="failed",
                               result={"executionOutcome": "unknown"}, error="请核实")
    db = SimpleNamespace(execute=AsyncMock(side_effect=[
        SimpleNamespace(scalar_one_or_none=lambda: action),
        SimpleNamespace(scalar_one_or_none=lambda: None),
    ]), add=AsyncMock())
    monkeypatch.setattr(service.enterprise_application_service, "get_application", AsyncMock(return_value=app))
    monkeypatch.setattr(service.enterprise_application_service, "assert_page_permission", AsyncMock())
    monkeypatch.setattr(service.enterprise_application_service, "action_allowed_for_user", lambda *a: True)
    monkeypatch.setattr(service, "_validate_params", lambda *a: None)
    monkeypatch.setattr(service, "_integration_or_409", AsyncMock(return_value=object()))
    monkeypatch.setattr(service, "_manifest_page_action_keys", lambda *a: {"change"})
    monkeypatch.setattr(service, "_unresolved_identical_write", AsyncMock(return_value=original))
    execute = AsyncMock()
    monkeypatch.setattr(service, "_execute_request", execute)
    result = await service.invoke_action(
        db, app.id, "change", "orders", {"owner": "李娜"}, user,
        request_id="new-turn-id", page_key="main", expected_version=3,
    )
    assert result["request_id"] == "original"
    assert result["result"]["executionOutcome"] == "unknown"
    db.add.assert_not_called()
    execute.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["update", "query"])
async def test_execution_timeout_keeps_recovery_payload_only_for_write(monkeypatch, operation):
    app = SimpleNamespace(id=uuid4(), slug="app", entry_url="https://example.test")
    action = SimpleNamespace(id=uuid4(), operation=operation, is_active=True, ai_enabled=True,
                             module_key="orders", action_key="change", requires_confirmation=False)
    encrypted = service._request_payload({"owner": "李娜"}, "main", 3)
    row = SimpleNamespace(id=uuid4(), request_id="original", params_encrypted=encrypted, result={}, error=None)
    db = SimpleNamespace(flush=AsyncMock())
    monkeypatch.setattr(service, "_integration_or_409", AsyncMock(return_value=object()))
    monkeypatch.setattr(service, "decrypt_provider_api_key", lambda value: value)
    monkeypatch.setattr(service, "_unresolved_identical_write", AsyncMock(return_value=None))
    monkeypatch.setattr(service, "_manifest_page_action_keys", lambda *args: {"change"})
    monkeypatch.setattr(service.enterprise_application_service, "effective_page_permissions", lambda *a: set())
    monkeypatch.setattr(service.enterprise_application_service, "action_allowed_for_user", lambda *a: True)
    monkeypatch.setattr(service, "_action_signing_secret", lambda *a: "not-a-real-secret")
    monkeypatch.setattr(service, "_identity_claims", lambda *a, **kw: {})
    monkeypatch.setattr(service.jwt, "encode", lambda *a, **kw: "test")
    transport = AsyncMock(side_effect=httpx.ReadTimeout("response timed out"))
    monkeypatch.setattr(service, "request_public_http", transport)
    result = await service._execute_request(db, row, app, action, object())
    transport.assert_awaited_once()
    assert result["status"] == "failed"
    if operation == "update":
        assert result["result"] == {"executionOutcome": "unknown"}
        assert row.params_encrypted == encrypted
        assert row.resolved_at is None
        assert "不要重复提交" in result["error"]
    else:
        assert row.params_encrypted is None
        assert row.resolved_at is not None
