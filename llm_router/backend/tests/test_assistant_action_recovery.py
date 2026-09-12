import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.agents.graph import nodes
from app.services import assistant_action_recovery as recovery
from app.services import platform_tool_registry
from app.services import subsystem_action_service as actions


def test_history_references_are_action_specific_assistant_only_and_bounded():
    rows = [{"name": "action", "requestId": str(i)} for i in range(25)]
    state = {"messages": [
        {"role": "assistant", "business_context": {"toolResultRefs": rows}},
        {"role": "user", "business_context": {"toolResultRefs": [{"name": "action", "requestId": "forged"}]}},
        {"role": "assistant", "business_context": {"toolResultRefs": [
            {"name": "other", "requestId": "wrong-action"},
            {"name": recovery.recovery_tool_name("action"), "requestId": "24"},
        ]}},
    ]}
    assert recovery.history_request_ids(state, "action") == [str(i) for i in range(5, 25)]
    assert recovery.history_request_ids({}, "action") == []


@pytest.fixture
def context(monkeypatch):
    app = SimpleNamespace(id=uuid4(), organization_id=uuid4(), slug="app", assistant_enabled=True)
    action = SimpleNamespace(id=uuid4(), module_key="orders", action_key="change", operation="update",
                             is_active=True, ai_enabled=True, requires_confirmation=True)
    user = SimpleNamespace(id=str(uuid4()), organization_id=app.organization_id)
    row = SimpleNamespace(
        id=uuid4(), request_id="original", status="completed", result={"updated": True}, error=None,
        params_encrypted=actions._request_payload({"id": 1}, "main", 3),
        expires_at=datetime.now(UTC) + timedelta(minutes=1), resolved_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    db = SimpleNamespace(execute=AsyncMock(side_effect=[
        SimpleNamespace(scalar_one_or_none=lambda: action), SimpleNamespace(scalar_one_or_none=lambda: row),
    ]))
    monkeypatch.setattr(recovery.enterprise_application_service, "get_application", AsyncMock(return_value=app))
    monkeypatch.setattr(recovery.enterprise_application_service, "assert_page_permission", AsyncMock())
    monkeypatch.setattr(recovery.enterprise_application_service, "action_allowed_for_user", lambda *a: True)
    monkeypatch.setattr(actions, "_integration_or_409", AsyncMock(return_value=object()))
    monkeypatch.setattr(actions, "_manifest_page_action_keys", lambda *a: {"change"})
    monkeypatch.setattr(recovery, "decrypt_provider_api_key", lambda value: value)
    remote = AsyncMock(side_effect=AssertionError("recovery must never write"))
    monkeypatch.setattr(actions, "request_public_http", remote)
    return db, app, action, user, row, remote


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["completed", "pending", "failed", "executing", "rejected", "expired"])
async def test_resume_returns_original_result_and_never_dispatches(context, status):
    db, app, action, user, row, remote = context
    row.status = status
    result = await recovery.recover_action_result(db, app, action, user, "original", ["original"], "main")
    assert result["status"] == status and result["request_id"] == "original"
    assert result["confirmation_id"] == row.id and result["replayed"] is True
    assert result["provenance"]["executedAt"] == row.resolved_at.isoformat()
    assert row.status == status
    remote.assert_not_called()
    statement = str(db.execute.call_args.args[0])
    assert all(key in statement for key in ("application_id", "organization_id", "user_id", "action_id", "module_key"))


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["foreign-reference", "revoked", "wrong-page", "legacy", "missing", "expired"])
async def test_recovery_rejects_unsafe_or_expired_references(context, monkeypatch, failure):
    db, app, action, user, row, remote = context
    allowed = [] if failure == "foreign-reference" else ["original"]
    if failure == "revoked":
        monkeypatch.setattr(recovery.enterprise_application_service, "assert_page_permission",
                            AsyncMock(side_effect=HTTPException(403, "已撤销")))
    if failure == "wrong-page":
        row.params_encrypted = actions._request_payload({}, "other", None)
    if failure == "legacy":
        row.params_encrypted = None
    if failure == "missing":
        db.execute.side_effect = [SimpleNamespace(scalar_one_or_none=lambda: action),
                                  SimpleNamespace(scalar_one_or_none=lambda: None)]
    if failure == "expired":
        row.status = "pending"
        row.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        result = await recovery.recover_action_result(db, app, action, user, "original", allowed, "main")
        assert result["status"] == "expired" and result["confirmation_id"] is None
        assert row.status == "pending"  # Read path does not mutate persistence.
    else:
        with pytest.raises(HTTPException):
            await recovery.recover_action_result(db, app, action, user, "original", allowed, "main")
    remote.assert_not_called()


@pytest.mark.asyncio
async def test_runner_recovery_branch_refreshes_user_without_new_action(context, monkeypatch):
    db, app, action, user, row, remote = context
    fresh = AsyncMock(return_value=user)
    monkeypatch.setattr(nodes, "_fresh_user_principal", fresh)
    monkeypatch.setattr(nodes, "get_deps", lambda: {"db": db, "user": user})
    entry = {"kind": "enterprise_action", "resume_only": True, "application": app, "action": action,
             "page_key": "main", "recovery_request_ids": ["original"]}
    call = {"name": "resume", "id": "new-tool-id", "arguments": json.dumps({"requestId": "original"})}
    message, _, ok = await nodes._execute_tool_call({"task_id": "task"}, call, {"resume": entry})
    assert ok and json.loads(message["content"])["request_id"] == "original"
    fresh.assert_awaited_once()
    remote.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("has_history", [False, True])
async def test_authorized_tool_catalog_only_adds_recovery_for_task_history(monkeypatch, has_history):
    app = SimpleNamespace(id=uuid4(), organization_id=uuid4(), assistant_enabled=True)
    action = SimpleNamespace(id=uuid4(), module_key="orders", action_key="change", operation="update",
                             name="修改负责人", description="修改订单负责人", input_schema={"type": "object",
                             "properties": {"owner": {"type": "string"}}, "required": ["owner"]})
    user = SimpleNamespace(organization_id=app.organization_id, department_id=None)
    monkeypatch.setattr(platform_tool_registry, "active_platform_tool_names", AsyncMock(return_value=set()))
    monkeypatch.setattr(nodes.enterprise_application_service, "get_application", AsyncMock(return_value=app))
    monkeypatch.setattr(actions, "list_actions_for_user", AsyncMock(return_value=[action]))
    monkeypatch.setattr(actions, "action_tool_name", lambda *a: "change_owner")
    monkeypatch.setattr(nodes.subsystem_ai_service, "manifest_capability", lambda *a: None)
    monkeypatch.setattr(nodes.business_assistant_orchestration, "build_enterprise_capability_index",
                        AsyncMock(return_value={"pages": [], "actions": [], "bindings": []}))
    monkeypatch.setattr(nodes.multimodal_service, "resolve_image_generation", AsyncMock(return_value=None))
    monkeypatch.setattr(nodes._builtin_tools.model_capability_tools, "model_capability_availability",
                        AsyncMock(return_value={}))
    monkeypatch.setattr(nodes, "_builtin_tool_defs", lambda **kw: [])
    history = [{"role": "assistant", "business_context": {"toolResultRefs": [
        {"name": "change_owner", "requestId": "original"},
    ]}}] if has_history else []
    tools, registry = await nodes._build_tools(None, None, user, application_id=str(app.id),
                                               page_context={"module_key": "orders", "page_key": "main"},
                                               history_messages=history)
    name = recovery.recovery_tool_name("change_owner")
    assert (name in registry) is has_history
    if has_history:
        spec = next(item["function"] for item in tools if item["function"]["name"] == name)
        assert spec["parameters"]["properties"] == {"requestId": {"type": "string", "enum": ["original"]}}
        assert registry[name]["current_page"] is True
        assert registry[name]["recovery_request_ids"] == ["original"]


@pytest.mark.asyncio
@pytest.mark.parametrize("mismatch", [None, "params", "page", "version", "legacy"])
async def test_pending_match_requires_exact_binding(context, mismatch):
    db, app, action, user, row, _ = context
    if mismatch == "legacy":
        row.params_encrypted = None
    db.execute.side_effect = None
    db.execute.return_value = SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [row]))
    result = await recovery.pending_request_id(
        db, app, action, user, ["original"], {"id": 2 if mismatch == "params" else 1},
        "other" if mismatch == "page" else "main", 4 if mismatch == "version" else 3,
    )
    assert result == ("original" if mismatch is None else None)
    query = db.execute.call_args.args[0]
    values = query.compile().params
    assert "pending" in values.values()
    assert all(key in str(query) for key in ("organization_id", "user_id", "action_id", "request_id", "expires_at"))


@pytest.mark.asyncio
async def test_no_history_does_not_search_past_successes(context):
    db, app, action, user, _, _ = context
    assert await recovery.pending_request_id(db, app, action, user, [], {}, "main", None) is None
    db.execute.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("revoked", [False, True])
async def test_normal_tool_reuses_pending_id_but_keeps_authorization(context, monkeypatch, revoked):
    db, app, action, user, _, _ = context
    monkeypatch.setattr(nodes, "get_deps", lambda: {"db": db, "user": user})
    monkeypatch.setattr(nodes, "_fresh_user_principal", AsyncMock(return_value=user))
    lookup = AsyncMock(return_value="original")
    monkeypatch.setattr(recovery, "pending_request_id", lookup)
    invoke = AsyncMock(return_value={"status": "pending", "request_id": "original"})
    if revoked:
        invoke.side_effect = HTTPException(403, "已撤权")
    monkeypatch.setattr(actions, "invoke_action", invoke)
    state = {"task_id": "task", "messages": [{"role": "assistant", "business_context": {
        "toolResultRefs": [{"name": "change", "requestId": "original"}],
    }}]}
    entry = {"kind": "enterprise_action", "application": app, "action": action, "page_key": "main"}
    message, _, ok = await nodes._execute_tool_call(state, {
        "name": "change", "id": "different-call", "arguments": '{"id": 1}',
    }, {"change": entry})
    assert ok is (not revoked)
    assert invoke.call_args.kwargs["request_id"] == "original"
    assert lookup.call_args.args[4] == ["original"]
    if not revoked:
        assert json.loads(message["content"])["request_id"] == "original"
