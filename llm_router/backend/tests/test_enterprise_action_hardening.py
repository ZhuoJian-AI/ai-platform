"""Focused regression tests for enterprise Action reliability boundaries."""

from types import SimpleNamespace

import httpx
import pytest

from app.agents.dsh import runner
from app.agents.graph import nodes
from app.services.subsystem_action_service import _subsystem_response_error


@pytest.fixture
def db_engine():
    """These pure runtime tests do not need the integration-test PostgreSQL fixture."""

    yield None


def test_corrected_action_arguments_get_a_new_idempotency_key():
    state = {"task_id": "task-1", "run_id": "run-1"}
    first = nodes._enterprise_action_request_id(state, "call-1", {})
    exact_retry = nodes._enterprise_action_request_id(state, "call-1", {})
    corrected = nodes._enterprise_action_request_id(state, "call-1", {"name": "新厂商"})

    assert first == exact_retry
    assert corrected != first


def test_update_delete_and_approve_require_a_trusted_version():
    for operation in ("update", "delete", "approve"):
        parameters = nodes._enterprise_action_parameters({"type": "object", "properties": {}}, operation)
        assert "expectedVersion" in parameters["required"]
        assert parameters["properties"]["expectedVersion"]["type"] == "integer"


def test_numeric_string_version_is_normalized_before_action_dispatch():
    assert nodes._normalize_expected_version(" 12 ") == 12
    assert nodes._normalize_expected_version(12) == 12
    assert nodes._normalize_expected_version("version-12") == "version-12"


def test_subsystem_json_error_is_preserved_and_bounded():
    response = httpx.Response(409, json={"error": "记录已更新，请重新查询当前版本\n再试"})
    assert _subsystem_response_error(response) == (
        "子系统 Action 返回 HTTP 409：记录已更新，请重新查询当前版本 再试"
    )


@pytest.mark.asyncio
async def test_successful_query_does_not_mask_a_failed_mutation(monkeypatch):
    async def stream_run(_request):
        yield {"type": "tool_call", "id": "q1", "name": "record_query", "arguments": "{}"}
        yield {
            "type": "tool_result", "id": "q1", "name": "record_query",
            "content": '{"status":"completed","result":{"count":1}}', "ok": True,
        }
        yield {"type": "tool_call", "id": "u1", "name": "record_update", "arguments": "{}"}
        yield {
            "type": "tool_result", "id": "u1", "name": "record_update",
            "content": "子系统 Action 返回 HTTP 409：记录已更新", "ok": False,
        }
        yield {"type": "done", "text": "已经修改成功。"}

    monkeypatch.setattr(runner.client, "stream_run", stream_run)
    state = {
        "run_id": 21,
        "request": "查询这条记录并把联系人修改为李四",
        "application_id": "app-1",
        "messages": [],
        "steps": [],
        "_dsh_tool_registry": {
            "record_query": {
                "kind": "enterprise_action", "action": SimpleNamespace(operation="query"),
            },
            "record_update": {
                "kind": "enterprise_action", "action": SimpleNamespace(operation="update"),
            },
        },
    }
    staged: list[dict] = []

    await runner._consume_dsh(state, {"system_prompt": "", "tools": []}, "run-token", None, staged)

    assert "业务数据未被修改" in state["assistant_final"]
    assert "已经修改成功" not in state["assistant_final"]
    assert "HTTP 409" in state["assistant_final"]
    assert any(event.get("type") == "text_retract" for event in staged)


@pytest.mark.asyncio
async def test_successful_mutation_is_not_failed_by_the_generic_record_noun(monkeypatch):
    async def stream_run(_request):
        yield {"type": "tool_call", "id": "c1", "name": "record_create", "arguments": "{}"}
        yield {
            "type": "tool_result", "id": "c1", "name": "record_create",
            "content": '{"status":"completed","result":{"id":3,"dataVersion":1}}', "ok": True,
        }
        yield {"type": "done", "text": "已新增供应商记录，编号 3。"}

    monkeypatch.setattr(runner.client, "stream_run", stream_run)
    state = {
        "run_id": 23,
        "request": "新增一条供应商记录",
        "application_id": "app-1",
        "messages": [],
        "steps": [],
        "_dsh_tool_registry": {
            "record_create": {
                "kind": "enterprise_action", "action": SimpleNamespace(operation="create"),
            },
        },
    }

    await runner._consume_dsh(state, {"system_prompt": "", "tools": []}, "run-token", None, [])

    assert state["assistant_final"] == "已新增供应商记录，编号 3。"
    assert state.get("error") is None


@pytest.mark.asyncio
async def test_query_for_saved_records_is_not_misclassified_as_a_mutation(monkeypatch):
    async def stream_run(_request):
        yield {"type": "tool_call", "id": "q1", "name": "record_query", "arguments": "{}"}
        yield {
            "type": "tool_result", "id": "q1", "name": "record_query",
            "content": '{"status":"completed","result":{"totalCount":0,"dataVersion":1}}', "ok": True,
        }
        yield {"type": "done", "text": "当前共有 0 条已保存的核算记录。"}

    monkeypatch.setattr(runner.client, "stream_run", stream_run)
    state = {
        "run_id": 24,
        "request": "请实时查询当前面辅料耗料核算共有多少条已保存的核算记录；必须只调用当前模块查询工具，并返回数据版本。",
        "application_id": "app-1",
        "messages": [],
        "steps": [],
        "_dsh_tool_registry": {
            "record_query": {
                "kind": "enterprise_action", "action": SimpleNamespace(operation="query"),
            },
        },
    }

    await runner._consume_dsh(state, {"system_prompt": "", "tools": []}, "run-token", None, [])

    assert state["assistant_final"] == "当前共有 0 条已保存的核算记录。"
    assert state.get("error") is None


@pytest.mark.asyncio
async def test_pending_mutation_is_not_reported_as_completed(monkeypatch):
    async def stream_run(_request):
        yield {"type": "tool_call", "id": "d1", "name": "record_delete", "arguments": "{}"}
        yield {
            "type": "tool_result", "id": "d1", "name": "record_delete",
            "content": '{"status":"pending","confirmation_id":"confirm-1"}', "ok": True,
        }
        yield {"type": "done", "text": "记录已删除。"}

    monkeypatch.setattr(runner.client, "stream_run", stream_run)
    state = {
        "run_id": 22,
        "request": "删除这条记录",
        "application_id": "app-1",
        "messages": [],
        "steps": [],
        "_dsh_tool_registry": {
            "record_delete": {
                "kind": "enterprise_action", "action": SimpleNamespace(operation="delete"),
            },
        },
    }

    await runner._consume_dsh(state, {"system_prompt": "", "tools": []}, "run-token", None, [])

    assert state["assistant_final"] == "该业务操作尚未执行，正在等待你确认。确认后系统才会真正修改业务数据。"
    assert "已删除" not in state["assistant_final"]
    assert "error" not in state
    assert any(step.get("step") == "business_mutation_pending_confirmation" for step in state["steps"])
