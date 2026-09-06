"""Focused regression tests for enterprise Action reliability boundaries."""

import re
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from app.agents.dsh import runner
from app.agents.graph import nodes
from app.services.subsystem_action_service import _subsystem_response_error, _validate_result


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


def test_browser_retry_keeps_action_and_file_idempotency_across_new_run_ids():
    first = nodes._enterprise_action_request_id(
        {"task_id": "task-1", "run_id": 7, "client_request_id": "browser-request-1"},
        "call-1", {"limit": 50},
    )
    retried = nodes._enterprise_action_request_id(
        {"task_id": "task-1", "run_id": 8, "client_request_id": "browser-request-1"},
        "call-1", {"limit": 50},
    )
    assert first == retried


def test_action_request_id_is_contract_safe_even_with_long_runtime_identifiers():
    request_id = nodes._enterprise_action_request_id(
        {
            "task_id": "task-" + "a" * 200,
            "client_request_id": "browser-" + "b" * 200,
        },
        "provider-tool-call-" + "c" * 300,
        {"筛选": "值" * 300},
    )

    assert 8 <= len(request_id) <= 128
    assert re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{7,127}", request_id)


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


def _export_action(result_schema: dict) -> SimpleNamespace:
    return SimpleNamespace(operation="export", result_schema=result_schema)


def _export_schema() -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["snapshotId", "snapshotAt", "columns", "rows", "rowCount", "nextCursor"],
        "properties": {
            "snapshotId": {"type": "string"},
            "snapshotAt": {"type": "string"},
            "columns": {"type": "array", "items": {"type": "object"}},
            "rows": {"type": "array", "items": {"type": "object"}},
            "rowCount": {"type": "integer", "minimum": 0},
            "nextCursor": {"type": ["string", "null"]},
        },
    }


def test_export_result_is_schema_validated_before_model_use():
    action = _export_action(_export_schema())
    _validate_result(action, {
        "snapshotId": "snap-1", "snapshotAt": "2026-09-06T00:00:00Z",
        "columns": [{"key": "orderNo", "label": "订单号", "type": "string"}],
        "rows": [{"orderNo": "PO-1"}], "rowCount": 1, "nextCursor": None,
    })

    with pytest.raises(RuntimeError, match="不符合约定"):
        _validate_result(action, {
            "snapshotId": "snap-1", "snapshotAt": "2026-09-06T00:00:00Z",
            "columns": [], "rows": [], "rowCount": "1", "nextCursor": None,
        })

    with pytest.raises(RuntimeError, match="未声明"):
        _validate_result(action, {
            "snapshotId": "snap-1", "snapshotAt": "2026-09-06T00:00:00Z",
            "columns": [{"key": "orderNo", "label": "订单号", "type": "string"}],
            "rows": [{"orderNo": "PO-1", "serverOnly": "x"}],
            "rowCount": 1, "nextCursor": None,
        })


def test_export_result_rejects_nested_server_paths_even_when_schema_allows_them():
    schema = _export_schema()
    schema["properties"]["rows"] = {"type": "array", "items": {"type": "object"}}
    with pytest.raises(RuntimeError, match="不得返回服务器路径"):
        _validate_result(_export_action(schema), {
            "snapshotId": "snap-1", "snapshotAt": "2026-09-06T00:00:00Z",
            "columns": [], "rows": [{"metadata": {"download": "/var/backups/db.sqlite"}}],
            "rowCount": 1, "nextCursor": None,
        })


def test_export_file_tool_name_stays_within_provider_limit():
    name = nodes._enterprise_export_file_tool_name("x" * 64)
    assert name.endswith("_file")
    assert len(name) == 64


@pytest.mark.asyncio
async def test_trusted_export_executor_collects_one_snapshot_without_exposing_rows_to_model(monkeypatch):
    user = SimpleNamespace(id="user-1")
    pages = [
        {
            "status": "completed",
            "result": {
                "snapshotId": "snap-1", "snapshotAt": "2026-09-06T00:00:00Z",
                "columns": [{"key": "id", "label": "编号", "type": "string"}],
                "rows": [{"id": "1"}, {"id": "2"}], "rowCount": 3, "nextCursor": "cursor-2",
            },
            "provenance": {"actionKey": "orders.export", "requestId": "request-1"},
        },
        {
            "status": "completed",
            "result": {
                "snapshotId": "snap-1", "snapshotAt": "2026-09-06T00:00:00Z",
                "columns": [{"key": "id", "label": "编号", "type": "string"}],
                "rows": [{"id": "3"}], "rowCount": 3, "nextCursor": None,
            },
            "provenance": {"actionKey": "orders.export", "requestId": "request-2"},
        },
    ]
    invoked: list[dict] = []
    generated: dict = {}

    async def fresh_user(_db, current):
        assert current is user
        return user

    async def invoke(_db, _application_id, _action_key, _module_key, action_params, _user, **kwargs):
        invoked.append({"params": action_params, **kwargs})
        return pages[len(invoked) - 1]

    async def generate(_state, name, params, _ws, current):
        generated.update({"name": name, "params": params, "user": current})
        return '{"status":"success","outputs":[{"file_id":"file-1"}]}'

    monkeypatch.setattr(nodes, "_fresh_user_principal", fresh_user)
    monkeypatch.setattr(nodes.subsystem_action_service, "invoke_action", invoke)
    monkeypatch.setattr(nodes, "_execute_platform_file_tool", generate)
    state = {"task_id": "task-1", "run_id": 7, "business_action_provenance": []}
    entry = {
        "application": SimpleNamespace(id=uuid4()),
        "action": SimpleNamespace(action_key="orders.export", module_key="orders"),
        "page_key": "orders.list",
    }

    content, ok = await nodes._execute_enterprise_export_file(
        state, entry, {"limit": 2, "output_name": "订单.xlsx"}, user, object(), "call-1",
    )

    assert ok is True
    assert len(invoked) == 2
    assert invoked[1]["params"]["snapshotId"] == "snap-1"
    assert invoked[1]["params"]["nextCursor"] == "cursor-2"
    assert generated["name"] == "spreadsheet_tool"
    assert generated["params"]["sheets"][0]["rows"] == [["编号"], ["1"], ["2"], ["3"]]
    assert "snap-1" not in content  # model only receives the committed file result
    assert state["business_action_provenance"][-1]["row_count"] == 3


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
        "request": (
            "请实时查询当前面辅料耗料核算共有多少条已保存的核算记录；"
            "必须只调用当前模块查询工具，并返回数据版本。"
        ),
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
