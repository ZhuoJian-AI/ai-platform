from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.schemas.enterprise_application import ActionReconciliationInput
from app.services import subsystem_action_service as actions
from app.services.action_reconciliation_service import apply_resolution, list_requests, reconcile


def unknown(status="failed"):
    return SimpleNamespace(status=status, result={"executionOutcome": "unknown"}, params_encrypted="binding")


@pytest.mark.parametrize("decision,status", [("executed", "completed"), ("not_executed", "rejected")])
def test_evidence_changes_state_without_discarding_duplicate_binding(decision, status):
    row = unknown()
    assert apply_resolution(row, decision=decision, evidence="receipt E2E-1", admin_id=1)
    assert row.status == status
    assert row.params_encrypted == "binding"
    assert row.result["reconciliation"]["source"] == "administrator_evidence"
    assert "artifacts" not in row.result
    assert not apply_resolution(row, decision=decision, evidence="receipt E2E-1", admin_id=1)


@pytest.mark.parametrize("status", ["executing", "pending", "completed", "rejected", "expired"])
def test_cannot_override_live_or_resolved_request(status):
    row = unknown(status)
    with pytest.raises(HTTPException) as error:
        apply_resolution(row, decision="not_executed", evidence="receipt", admin_id=1)
    assert error.value.status_code == 409
    assert row.status == status


def test_cannot_overwrite_evidence_or_actor():
    row = unknown()
    apply_resolution(row, decision="executed", evidence="receipt", admin_id=1)
    for decision, evidence, actor in [
        ("not_executed", "receipt", 1), ("executed", "different", 1), ("executed", "receipt", 2),
    ]:
        with pytest.raises(HTTPException):
            apply_resolution(row, decision=decision, evidence=evidence, admin_id=actor)


@pytest.mark.parametrize("evidence", ["", "  ", "\n"])
def test_evidence_required(evidence):
    with pytest.raises(ValidationError):
        ActionReconciliationInput(decision="executed", evidence=evidence)


@pytest.mark.asyncio
async def test_other_tenant_rejected_before_database_access():
    db = AsyncMock()
    application = SimpleNamespace(organization_id=uuid4())
    auth = SimpleNamespace(role="enterprise_admin", organization_id=uuid4(), id=1)
    for call in [
        list_requests(db, application, auth),
        reconcile(db, application, auth, uuid4(), decision="executed", evidence="receipt"),
    ]:
        with pytest.raises(HTTPException) as error:
            await call
        assert error.value.status_code == 403
    db.execute.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("confirmed", [True, False])
async def test_old_confirmation_after_reconciliation_never_dispatches(monkeypatch, confirmed):
    now = datetime.now(UTC)
    app = SimpleNamespace(id=uuid4())
    action = SimpleNamespace(
        id=uuid4(), operation="update", module_key="orders", action_key="change",
        is_active=True, ai_enabled=True,
    )
    row = SimpleNamespace(
        created_at=now - timedelta(minutes=1),
        params_encrypted=actions._request_payload({"id": 1}, "main", 3),
    )
    monkeypatch.setattr(actions, "decrypt_provider_api_key", lambda value: value)
    monkeypatch.setattr(actions, "_integration_or_409", AsyncMock(return_value=object()))
    monkeypatch.setattr(actions, "_manifest_page_action_keys", lambda *a: {"change"})
    monkeypatch.setattr(actions.enterprise_application_service, "effective_page_permissions", lambda *a: set())
    monkeypatch.setattr(actions.enterprise_application_service, "action_allowed_for_user", lambda *a: True)
    monkeypatch.setattr(actions, "_lock_write_dispatch", AsyncMock())
    monkeypatch.setattr(actions, "_unresolved_identical_write", AsyncMock(side_effect=[
        None, SimpleNamespace(resolved_at=now),
    ]))
    transport = AsyncMock()
    monkeypatch.setattr(actions, "request_public_http", transport)
    with pytest.raises(HTTPException) as error:
        await actions._execute_request(AsyncMock(), row, app, action, object(), confirmed=confirmed)
    assert error.value.status_code == 409
    transport.assert_not_awaited()
