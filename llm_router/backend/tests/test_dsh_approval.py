"""DB-free contracts for user approval of risky tools (Phase B1).

Covers the three backend halves: ``ToolSpec.approval`` metadata, the runtime bridge
``POST /internal/dsh/approval/request`` (SSE ``approval_request`` / ``approval_decided``) and the
terminal decision ``POST /terminal/tasks/{task_id}/approvals/{approval_id}``.
"""

import asyncio
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.agents.dsh import registry, runner
from app.agents.graph import nodes, run_registry
from app.api import dsh_internal, terminal
from app.config import settings
from app.schemas.task import TaskApprovalDecision
from app.services import platform_extension_catalog as catalog


@pytest.fixture(autouse=True)
def db_engine():
    """These approval tests are pure and do not require the PostgreSQL fixture."""
    yield


def _tool(name: str, **extra) -> dict:
    return {
        "type": "function",
        "function": {"name": name, "description": "", "parameters": {"type": "object", "properties": {}}},
        **extra,
    }


def _spec(name: str, entry: dict | None = None, **extra) -> dict:
    return nodes.dsh_tool_specs([_tool(name, **extra)], {name: entry} if entry is not None else {})[0]


def _action(operation: str, requires_confirmation: bool = False) -> dict:
    return {
        "kind": "enterprise_action", "application": object(),
        "action": SimpleNamespace(operation=operation, requires_confirmation=requires_confirmation),
    }


# ── ToolSpec.approval ────────────────────────────────────────────────────


def test_risky_tools_carry_approval_ask():
    assert _spec("workspace_delete_file")["approval"] == "ask"
    delete_endpoint = {"folder": object(), "endpoint": SimpleNamespace(method="DELETE")}
    assert _spec("erp__purge_1234", delete_endpoint)["approval"] == "ask"
    assert _spec("ext_high", {"kind": "x", "risk_level": "high", "side_effects": False})["approval"] == "ask"
    assert _spec("ext_critical", {"kind": "x", "risk_level": "critical"})["approval"] == "ask"
    assert _spec("ext_effects", {"kind": "x", "risk_level": "low", "side_effects": True})["approval"] == "ask"
    for operation in ("create", "update", "delete", "approve"):
        assert _spec(f"crm_{operation}", _action(operation))["approval"] == "ask", operation
    assert _spec("crm_query_confirm", _action("query", requires_confirmation=True))["approval"] == "ask"


def test_read_only_and_ordinary_write_tools_never_ask():
    for name in ("workspace_read_file", "workspace_search", "workspace_list_files", "web_tool", "workspace_write_file",
                 "workspace_move_file", "spreadsheet_tool", "image_generation_tool"):
        assert "approval" not in _spec(name), name
    assert "approval" not in _spec("write_memory", {"kind": "memory", "operation": "write"})
    assert "approval" not in _spec("read_memory", {"kind": "memory", "operation": "read"})
    assert "approval" not in _spec("rag_search", {"kind": "rag_search", "collection_ids": []})
    assert "approval" not in _spec("load_skill", {"kind": "load_skill"})
    assert "approval" not in _spec("bank_flow", {"kind": "code"})
    assert "approval" not in _spec("erp__query_1234", {"folder": object(), "endpoint": SimpleNamespace(method="POST")})
    assert "approval" not in _spec("ext_low", {"kind": "x", "risk_level": "low", "side_effects": False})
    for operation in ("query", "export"):
        assert "approval" not in _spec(f"crm_{operation}", _action(operation)), operation
    # A read tool that happens to carry a manifest risk flag is still never gated.
    assert "approval" not in _spec("rag_search", {"kind": "rag_search", "risk_level": "high"})


def test_external_extension_tools_use_the_risk_flags_attached_to_their_definition():
    """Extension tools have no execution registry entry; ``_build_tools`` puts the manifest flags on the def."""
    high = _spec("node_ext_wipe", risk={"risk_level": "high", "side_effects": False})
    low = _spec("node_ext_lookup", risk={"risk_level": "low", "side_effects": False})
    effects = _spec("node_ext_post", risk={"risk_level": "medium", "side_effects": True})

    assert high["kind"] == "external_tool" and high["approval"] == "ask"
    assert effects["approval"] == "ask"
    assert low["kind"] == "external_tool" and "approval" not in low
    assert "approval" not in _spec("node_ext_plain")


def test_builtin_defs_only_gate_the_hard_delete():
    specs = nodes.dsh_tool_specs(nodes._builtin_tool_defs(include_image_generation=True), {})
    gated = sorted(spec["name"] for spec in specs if spec.get("approval") == "ask")
    assert gated == ["workspace_delete_file"]
    assert all(spec.get("approval") in (None, "ask") for spec in specs)


def test_approval_metadata_is_gated_by_the_setting(monkeypatch):
    assert settings.dsh_tool_approval_enabled is True  # default
    monkeypatch.setattr(settings, "dsh_tool_approval_enabled", False)
    specs = nodes.dsh_tool_specs(
        [*nodes._builtin_tool_defs(include_image_generation=True), _tool("crm_delete"), _tool("ext_high")],
        {"crm_delete": _action("delete"), "ext_high": {"kind": "x", "risk_level": "critical", "side_effects": True}},
    )
    assert specs and not any("approval" in spec for spec in specs)
    assert {"kind", "timeout_ms", "concurrency_safe", "max_model_chars"} <= set(specs[0])


# ── bridge + terminal decision round trip ────────────────────────────────


def _context(task_id: str | None = "task-approval", *, with_handle: bool = True):
    staged: list[dict] = []
    handle = run_registry.RunHandle(task_id=task_id or "playground:x") if with_handle else None
    state = {"run_id": 42, "steps": []}
    if task_id:
        state["task_id"] = task_id
    context = registry.DshRunContext(
        state=state, db=None, deps={}, tool_registry={}, allowed_tool_names=set(),
        image_inputs=[], handle=handle, staged=staged,
    )
    return context, registry.register(context), handle, staged


def _bridge(token: str, approval_id: str = "ap-1", timeout_ms: int = 5_000) -> asyncio.Task:
    return asyncio.create_task(dsh_internal.request_approval(
        dsh_internal.ApprovalBridgeRequest(
            run_token=token, approval_id=approval_id, tool="workspace_delete_file", call_id="call-9",
            reason="硬删除文件", arguments_preview='{"file_id":"f-1"}', timeout_ms=timeout_ms,
        ),
        authorization=f"Bearer {settings.dsh_runtime_token}",
    ))


async def _settle() -> None:
    for _ in range(5):
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_user_allow_round_trip_publishes_request_then_decision():
    context, token, handle, staged = _context()
    try:
        request = _bridge(token)
        await _settle()

        live = [json.loads(item) for item in handle.buffer]
        assert len(live) == 1
        assert live[0] == {
            "type": "approval_request", "approval_id": "ap-1", "tool": "workspace_delete_file", "call_id": "call-9",
            "reason": "硬删除文件", "arguments_preview": '{"file_id":"f-1"}', "expires_at": live[0]["expires_at"],
            "run_id": 42,
        }
        assert live[0]["expires_at"].endswith("Z") and "T" in live[0]["expires_at"]
        assert not request.done()

        assert registry.decide_approval("task-approval", "ap-1", "allow") == "allowed-once"
        assert await request == {"outcome": "allowed-once", "decided_by": "user"}
        assert [event["type"] for event in staged] == ["approval_request", "approval_decided"]
        assert staged[1] == {
            "type": "approval_decided", "approval_id": "ap-1", "outcome": "allowed-once", "decided_by": "user",
        }
        assert [json.loads(item) for item in handle.buffer] == staged
        assert context.state["steps"] == [
            {"step": "approval", "tool": "workspace_delete_file", "outcome": "allowed-once", "decided_by": "user"},
        ]
        # A second decision is a conflict, not a silent overwrite.
        with pytest.raises(registry.ApprovalAlreadyDecidedError):
            registry.decide_approval("task-approval", "ap-1", "reject")
    finally:
        registry.revoke(token)
    with pytest.raises(registry.ApprovalNotFoundError):
        registry.decide_approval("task-approval", "ap-1", "allow")


@pytest.mark.asyncio
async def test_user_reject_and_lookup_failures():
    context, token, _handle, _staged = _context()
    try:
        request = _bridge(token, approval_id="ap-2")
        await _settle()
        with pytest.raises(registry.ApprovalNotFoundError):
            registry.decide_approval("task-approval", "ap-unknown", "allow")
        with pytest.raises(registry.ApprovalNotFoundError):  # another user's task never sees this approval
            registry.decide_approval("task-other", "ap-2", "allow")
        with pytest.raises(ValueError):
            registry.decide_approval("task-approval", "ap-2", "maybe")
        assert not request.done()
        assert registry.decide_approval("task-approval", "ap-2", "reject") == "rejected"
        assert await request == {"outcome": "rejected", "decided_by": "user"}
        assert context.state["steps"][-1]["outcome"] == "rejected"
    finally:
        registry.revoke(token)


@pytest.mark.asyncio
async def test_timeout_rejects_and_a_late_decision_is_a_conflict():
    context, token, _handle, staged = _context()
    try:
        result = await _bridge(token, approval_id="ap-3", timeout_ms=10)
        assert result == {"outcome": "rejected", "decided_by": "timeout"}
        assert staged[-1] == {
            "type": "approval_decided", "approval_id": "ap-3", "outcome": "rejected", "decided_by": "timeout",
        }
        assert context.state["steps"] == [
            {"step": "approval", "tool": "workspace_delete_file", "outcome": "rejected", "decided_by": "timeout"},
        ]
        with pytest.raises(registry.ApprovalAlreadyDecidedError):
            registry.decide_approval("task-approval", "ap-3", "allow")
    finally:
        registry.revoke(token)


@pytest.mark.asyncio
async def test_runs_without_a_live_channel_or_terminal_task_are_unavailable():
    _context_sync, token_sync, _none, staged_sync = _context(with_handle=False)
    _context_pg, token_pg, _handle_pg, staged_pg = _context(task_id=None)
    try:
        assert await _bridge(token_sync) == {"outcome": "unavailable", "decided_by": "system"}
        assert await _bridge(token_pg) == {"outcome": "unavailable", "decided_by": "system"}
        for staged in (staged_sync, staged_pg):
            assert [event["type"] for event in staged] == ["approval_request", "approval_decided"]
            assert staged[1]["outcome"] == "unavailable" and staged[1]["decided_by"] == "system"
    finally:
        registry.revoke(token_sync)
        registry.revoke(token_pg)


@pytest.mark.asyncio
async def test_stopping_the_run_cancels_pending_approvals():
    context, token, handle, staged = _context()
    request = _bridge(token, approval_id="ap-4")
    await _settle()
    registry.cancel_approvals(token)  # runner: stream over / user Stop, before persisting ``staged``
    assert await request == {"outcome": "cancelled", "decided_by": "system"}
    assert staged[-1] == {
        "type": "approval_decided", "approval_id": "ap-4", "outcome": "cancelled", "decided_by": "system",
    }
    assert context.state["steps"][-1] == {
        "step": "approval", "tool": "workspace_delete_file", "outcome": "cancelled", "decided_by": "system",
    }
    assert json.loads(handle.buffer[-1])["outcome"] == "cancelled"
    assert registry.get(token) is context  # cancelling approvals does not revoke the token itself

    # ``revoke`` (every runner ``finally``) settles anything still pending the same way.
    second = _bridge(token, approval_id="ap-5")
    await _settle()
    registry.revoke(token)
    assert await second == {"outcome": "cancelled", "decided_by": "system"}
    with pytest.raises(registry.ApprovalNotFoundError):
        registry.decide_approval("task-approval", "ap-5", "allow")


@pytest.mark.asyncio
async def test_bridge_requires_the_service_token_and_a_live_run_token():
    with pytest.raises(HTTPException) as unauthenticated:
        await dsh_internal.request_approval(
            dsh_internal.ApprovalBridgeRequest(run_token="x", approval_id="a", tool="t", call_id="c"),
            authorization="Bearer wrong",
        )
    assert unauthenticated.value.status_code == 401
    with pytest.raises(HTTPException) as expired:
        await dsh_internal.request_approval(
            dsh_internal.ApprovalBridgeRequest(run_token="expired-token", approval_id="a", tool="t", call_id="c"),
            authorization=f"Bearer {settings.dsh_runtime_token}",
        )
    assert expired.value.status_code == 401
    assert expired.value.detail == "expired run token"


@pytest.mark.asyncio
async def test_bridge_caps_the_wait_at_five_minutes():
    _context_, token, _handle, staged = _context()
    try:
        request = _bridge(token, timeout_ms=10 * 60 * 1000)
        await _settle()
        requested = staged[0]
        # ``expires_at`` reflects the capped window (≤ 300 s from now), never the requested 10 min.
        from datetime import UTC, datetime
        expires = datetime.fromisoformat(requested["expires_at"].replace("Z", "+00:00"))
        assert (expires - datetime.now(UTC)).total_seconds() <= registry.APPROVAL_MAX_TIMEOUT_MS / 1000 + 1
        registry.decide_approval("task-approval", "ap-1", "allow")
        await request
    finally:
        registry.revoke(token)


@pytest.mark.asyncio
async def test_terminal_endpoint_maps_outcomes_to_http_statuses(monkeypatch):
    task_uuid = uuid4()
    context, token, _handle, _staged = _context(task_id=str(task_uuid))

    async def owned(_db, task_id, _cu):
        assert task_id == task_uuid
        return SimpleNamespace(id=task_uuid)

    monkeypatch.setattr(terminal, "_get_owned_task", owned)
    user = SimpleNamespace(id="user-1", organization_id=uuid4(), role="member")
    try:
        request = _bridge(token, approval_id="ap-http")
        await _settle()
        with pytest.raises(HTTPException) as unknown:
            await terminal.decide_task_approval_endpoint(
                task_uuid, "ap-missing", TaskApprovalDecision(decision="allow"), cu=user, db=None,
            )
        assert unknown.value.status_code == 404

        decided = await terminal.decide_task_approval_endpoint(
            task_uuid, "ap-http", TaskApprovalDecision(decision="allow"), cu=user, db=None,
        )
        assert decided == {"outcome": "allowed-once"}
        assert await request == {"outcome": "allowed-once", "decided_by": "user"}

        with pytest.raises(HTTPException) as conflict:
            await terminal.decide_task_approval_endpoint(
                task_uuid, "ap-http", TaskApprovalDecision(decision="reject"), cu=user, db=None,
            )
        assert conflict.value.status_code == 409
    finally:
        registry.revoke(token)


def test_terminal_decision_schema_only_accepts_allow_or_reject():
    assert TaskApprovalDecision(decision="reject").decision == "reject"
    with pytest.raises(ValueError):
        TaskApprovalDecision(decision="maybe")


# ── runner: runtime policy events + catalog ──────────────────────────────


@pytest.mark.asyncio
async def test_runtime_approval_policy_events_are_traced_like_other_policies(monkeypatch):
    async def stream_run(_request):
        yield {"type": "policy", "action": "approval_requested", "tool": "workspace_delete_file", "approval_id": "ap-1"}
        yield {
            "type": "policy", "action": "approval_decided", "tool": "workspace_delete_file", "approval_id": "ap-1",
            "outcome": "rejected", "decided_by": "user",
        }
        yield {"type": "done", "text": "已按你的要求放弃删除。", "steps": 1, "tool_calls": 0}

    monkeypatch.setattr(runner.client, "stream_run", stream_run)
    state = {"run_id": 11, "request": "删掉那个文件", "messages": [], "steps": [], "traces": []}
    staged: list[dict] = []

    await runner._consume_dsh(state, {"system_prompt": "", "tools": []}, "run-token", None, staged)

    traces = [trace for trace in state["traces"] if trace.get("category") == "policy"]
    assert [trace["title"] for trace in traces] == ["审批请求", "审批结果"]
    assert traces[1]["outcome"] == "rejected" and traces[1]["decided_by"] == "user"
    assert traces[0]["approval_id"] == "ap-1"
    assert {
        "step": "policy", "action": "approval_decided", "tool": "workspace_delete_file", "approval_id": "ap-1",
        "outcome": "rejected", "decided_by": "user",
    } in state["steps"]
    assert [event["action"] for event in staged if event.get("type") == "trace"] == [
        "approval_requested", "approval_decided",
    ]
    assert state["assistant_final"] == "已按你的要求放弃删除。"


def test_user_approval_plugin_is_enabled_in_the_catalog_and_manifest():
    row = next(item for item in catalog.catalog_items() if item["slug"] == "dsh-user-approval")
    assert row["status"] == "enabled"
    assert row["compatibility_warnings"] == []
    assert "SSE" in row["description"] and "审批" in row["description"]
    plugin = next(item for item in catalog.baseline_manifest()["plugins"] if item["slug"] == "dsh-user-approval")
    assert plugin["enabled"] is True
    assert "description" not in plugin  # release manifest keeps its shape
    assert plugin["capabilities"] == ["approval"]
