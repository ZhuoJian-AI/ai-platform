"""DB-free contracts for the runtime-owned DSH policies (Phase A: completion / tool metadata / memory)."""

import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.agents.dsh import runner
from app.agents.graph import nodes, run_registry
from app.services import platform_tool_registry


@pytest.fixture(autouse=True)
def db_engine():
    """These policy tests are pure and do not require the PostgreSQL fixture."""
    yield


# ── completion_policy ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("request_text", "expected"),
    [
        ("请生成一份 Excel 表格汇总各部门销量", True),
        ("把这份数据导出成 PDF 报告", True),
        ("Generate a spreadsheet of the monthly totals", True),
        ("看看这个表里合计多少", False),
        ("处理一下附件", False),
        ("这个文件里说了什么", False),
        ("根据这份报告回答：交期是多少天", False),
    ],
)
def test_completion_policy_requires_an_explicit_artifact_request(request_text, expected):
    """M4：仅「生产动词 + 产物名词」才要求文件产出；处理/看看 + 附件不算。"""
    state = {
        "exec_mode": "craft", "request": request_text,
        "attachment_files": [{"file_id": "file-1"}], "invoked_skill_ids": ["skill-1"],
    }

    policy = runner._completion_policy(state)

    assert policy["require_file_output"] is expected
    assert policy["max_nudges"] == 1
    assert policy["nudge_text"].startswith("[系统续执行要求]")
    assert "spreadsheet_tool" in policy["file_output_tools"]


def test_completion_policy_never_arms_outside_craft_mode():
    for mode in ("ask", "plan"):
        policy = runner._completion_policy({"exec_mode": mode, "request": "请生成一份 Excel 表格"})
        assert policy["require_file_output"] is False


def test_completion_policy_lists_executable_skill_tools_from_the_registry():
    state = {
        "exec_mode": "craft", "request": "你好",
        "_dsh_tool_registry": {
            "bank_flow": {"kind": "code"},
            "run_skill_script": {"kind": "run_skill_script"},
            "load_skill": {"kind": "load_skill"},
            "rag_search": {"kind": "rag_search"},
        },
    }

    tools = runner._completion_policy(state)["file_output_tools"]

    assert "bank_flow" in tools
    assert tools.count("run_skill_script") == 1
    assert "load_skill" not in tools
    assert "rag_search" not in tools
    assert {"workspace_write_file", "document_tool", "image_generation_tool"} <= set(tools)


# ── policy events from the runtime ───────────────────────────────────────


@pytest.mark.asyncio
async def test_policy_continuation_retracts_the_half_answer_streamed_so_far(monkeypatch):
    async def stream_run(_request):
        yield {"type": "text_delta", "delta": "我先加载技能"}
        yield {"type": "text_delta", "delta": "，稍等。"}
        yield {"type": "policy", "action": "continuation", "nudge": 1}
        yield {
            "type": "tool_call", "id": "sheet-1", "name": "spreadsheet_tool",
            "arguments": '{"action":"create"}',
        }
        yield {
            "type": "tool_result", "id": "sheet-1", "name": "spreadsheet_tool",
            "content": "output.xlsx", "ok": True,
        }
        yield {"type": "text_delta", "delta": "处理完成，文件已生成。"}
        yield {"type": "done", "text": "处理完成，文件已生成。", "steps": 2, "tool_calls": 1}

    monkeypatch.setattr(runner.client, "stream_run", stream_run)
    handle = run_registry.RunHandle(task_id="task-policy-continuation")
    state = {"run_id": 7, "request": "请生成一份 Excel 表格", "messages": [], "steps": [], "exec_mode": "craft"}
    staged: list[dict] = []

    await runner._consume_dsh(state, {"system_prompt": "", "tools": []}, "run-token", handle, staged)

    retracts = [event for event in staged if event.get("type") == "text_retract"]
    assert retracts == [{"type": "text_retract", "chars": len("我先加载技能，稍等。")}]
    # The retract is ordered after the half answer and before the continued answer.
    kinds = [event["type"] for event in staged]
    assert kinds.index("text_retract") > kinds.index("text")
    assert kinds.index("text_retract") < kinds.index("tool_call")
    assert {"step": "policy", "action": "continuation", "nudge": 1} in state["steps"]
    assert state.get("error") is None
    assert state["assistant_final"] == "处理完成，文件已生成。"
    live = [json.loads(item) for item in handle.buffer]
    assert any(event.get("type") == "text_retract" for event in live)


@pytest.mark.asyncio
async def test_policy_blocks_and_timeouts_are_recorded_without_retracting_text(monkeypatch):
    async def stream_run(_request):
        yield {"type": "text_delta", "delta": "尝试读取。"}
        yield {
            "type": "policy", "action": "repeat_failure_block", "tool": "spreadsheet_tool",
            "detail": "identical arguments failed twice",
        }
        yield {"type": "policy", "action": "tool_timeout", "tool": "run_skill_script", "detail": "300000ms"}
        yield {"type": "done", "text": "尝试读取。脚本超时，已如实说明。", "steps": 3, "tool_calls": 2}

    monkeypatch.setattr(runner.client, "stream_run", stream_run)
    state = {"run_id": 8, "request": "跑一下脚本", "messages": [], "steps": [], "traces": []}
    staged: list[dict] = []

    await runner._consume_dsh(state, {"system_prompt": "", "tools": []}, "run-token", None, staged)

    policy_steps = [step for step in state["steps"] if step.get("step") == "policy"]
    assert policy_steps == [
        {
            "step": "policy", "action": "repeat_failure_block", "tool": "spreadsheet_tool",
            "detail": "identical arguments failed twice",
        },
        {"step": "policy", "action": "tool_timeout", "tool": "run_skill_script", "detail": "300000ms"},
    ]
    policy_traces = [trace for trace in state["traces"] if trace.get("category") == "policy"]
    assert [trace["action"] for trace in policy_traces] == ["repeat_failure_block", "tool_timeout"]
    assert all(trace.get("ok") is None for trace in policy_traces)  # never counted as a tool call
    forwarded = [event for event in staged if event.get("type") == "trace"]
    assert [event["action"] for event in forwarded] == ["repeat_failure_block", "tool_timeout"]
    assert forwarded[1]["title"] == "工具超时"
    assert not any(event.get("type") == "text_retract" for event in staged)
    assert state["assistant_final"] == "尝试读取。脚本超时，已如实说明。"


@pytest.mark.asyncio
async def test_runtime_cancel_surfaces_as_a_stopped_run_not_a_generic_failure(monkeypatch):
    """运行时取消以 error(code=CANCELLED) 收口（不再发 done）；公开文案不能是「暂时无法完成」。"""
    async def stream_run(_request):
        yield {"type": "status", "status": "cancelled"}
        yield {"type": "error", "message": "cancelled", "code": "CANCELLED"}

    monkeypatch.setattr(runner.client, "stream_run", stream_run)

    with pytest.raises(runner.DshRunError) as raised:
        await runner._consume_dsh(
            {"run_id": 9, "request": "停一下", "messages": [], "steps": []},
            {"system_prompt": "", "tools": []}, "run-token", None, [],
        )

    assert raised.value.code == "CANCELLED"
    assert runner._public_failure_message(raised.value) == "本次运行已停止。"


# ── ToolSpec metadata ────────────────────────────────────────────────────


def test_builtin_tool_specs_carry_runtime_metadata():
    specs = {
        spec["name"]: spec
        for spec in nodes.dsh_tool_specs(nodes._builtin_tool_defs(include_image_generation=True), {})
    }

    assert specs  # sanity
    required_keys = {
        "name", "description", "input_schema", "kind", "timeout_ms", "concurrency_safe", "max_model_chars",
    }
    for spec in specs.values():
        assert required_keys <= set(spec)
        assert spec["max_model_chars"] == nodes.DSH_TOOL_MAX_MODEL_CHARS
        assert spec["max_model_chars"] > 4000  # H2: never the trace preview limit
    for name in ("workspace_read_file", "workspace_search", "workspace_list_files", "workspace_get_file"):
        assert specs[name]["concurrency_safe"] is True
        assert specs[name]["timeout_ms"] == nodes.DSH_TOOL_TIMEOUT_READ_MS
        assert specs[name]["kind"] == "workspace_file"
    for name in ("workspace_write_file", "workspace_move_file", "workspace_delete_file", "workspace_create_file"):
        assert specs[name]["concurrency_safe"] is False
        assert specs[name]["timeout_ms"] == nodes.DSH_TOOL_TIMEOUT_DEFAULT_MS
    office_tools = (
        "spreadsheet_tool", "document_tool", "presentation_tool", "pdf_tool", "text_tool", "image_tool", "archive_tool",
    )
    for name in office_tools:
        assert specs[name]["kind"] == "platform_tool"
        assert specs[name]["concurrency_safe"] is False
        assert specs[name]["timeout_ms"] == nodes.DSH_TOOL_TIMEOUT_DEFAULT_MS
    assert specs["web_tool"]["kind"] == "web"
    assert specs["web_tool"]["concurrency_safe"] is True
    assert specs["web_tool"]["timeout_ms"] == nodes.DSH_TOOL_TIMEOUT_LONG_MS
    assert specs["image_generation_tool"]["concurrency_safe"] is False
    assert specs["image_generation_tool"]["timeout_ms"] == nodes.DSH_TOOL_TIMEOUT_LONG_MS


def test_registry_backed_tool_specs_are_classified_by_kind():
    registry = {
        "run_skill_script": {"kind": "run_skill_script"},
        "load_skill": {"kind": "load_skill"},
        "read_skill_resource": {"kind": "read_skill_resource"},
        "load_bank_flow": {"kind": "prompt"},
        "bank_flow": {"kind": "code"},
        "rag_search": {"kind": "rag_search", "collection_ids": []},
        "erp__query_stock_1234abcd": {"folder": object(), "endpoint": object()},
        "crm_create_order": {"kind": "enterprise_action"},
        "read_memory": {"kind": "memory", "operation": "read"},
        "write_memory": {"kind": "memory", "operation": "write"},
    }
    tools = [
        {"type": "function", "function": {
            "name": name, "description": "", "parameters": {"type": "object", "properties": {}},
        }}
        for name in [*registry, "node_ext_lookup"]
    ]

    specs = {spec["name"]: spec for spec in nodes.dsh_tool_specs(tools, registry)}

    def check(name, kind, timeout_ms, concurrency_safe):
        assert specs[name]["kind"] == kind, name
        assert specs[name]["timeout_ms"] == timeout_ms, name
        assert specs[name]["concurrency_safe"] is concurrency_safe, name

    check("run_skill_script", "skill", nodes.DSH_TOOL_TIMEOUT_LONG_MS, False)
    check("bank_flow", "skill", nodes.DSH_TOOL_TIMEOUT_LONG_MS, False)
    check("load_skill", "skill", nodes.DSH_TOOL_TIMEOUT_READ_MS, True)
    check("read_skill_resource", "skill", nodes.DSH_TOOL_TIMEOUT_READ_MS, True)
    check("load_bank_flow", "skill", nodes.DSH_TOOL_TIMEOUT_READ_MS, True)
    check("rag_search", "rag", nodes.DSH_TOOL_TIMEOUT_READ_MS, True)
    check("erp__query_stock_1234abcd", "connector", nodes.DSH_TOOL_TIMEOUT_DEFAULT_MS, False)
    check("crm_create_order", "enterprise_action", nodes.DSH_TOOL_TIMEOUT_LONG_MS, False)
    check("read_memory", "memory", nodes.DSH_TOOL_TIMEOUT_READ_MS, True)
    check("write_memory", "memory", nodes.DSH_TOOL_TIMEOUT_DEFAULT_MS, False)
    check("node_ext_lookup", "external_tool", nodes.DSH_TOOL_TIMEOUT_DEFAULT_MS, False)


def test_runner_tool_specs_delegate_to_the_shared_assembly():
    tools = [{"type": "function", "function": {
        "name": "workspace_read_file", "description": "读", "parameters": {"type": "object"},
    }}]
    specs = runner._tool_specs(tools, {})
    assert specs == nodes.dsh_tool_specs(tools, {})
    assert specs[0]["input_schema"] == {"type": "object"}
    assert specs[0]["concurrency_safe"] is True


# ── memory tools ─────────────────────────────────────────────────────────


def _craft_state(**overrides) -> dict:
    state = {
        "mode": "general", "org_id": str(uuid4()), "user_id": "user-1", "workspace_id": None,
        "system_prompt": "你是测试助手。", "messages": [{"role": "user", "content": "记住我偏好账期长的供应商"}],
        "request": "记住我偏好账期长的供应商", "referenced_file_ids": [], "file_refs_v1": [], "skill_ids": [],
        "exec_mode": "craft", "memory_context": [], "rag_context": [], "steps": [], "traces": [], "usage": {},
    }
    state.update(overrides)
    return state


def _patch_prepare_dependencies(monkeypatch, principal):
    async def fake_build_tools(
        _db, _skill_ids, _workspace_id, _user=None, *, exec_mode="craft", application_id=None, page_context=None,
    ):
        return nodes._builtin_tool_defs(), {}

    async def fake_visual(_state, _db, _user, _messages, prompt):
        return None, None, prompt

    async def no_interfaces(_db, _user):
        return []

    async def no_release(_db):
        return None

    monkeypatch.setattr(nodes, "get_deps", lambda: {"db": object(), "user": principal})
    monkeypatch.setattr(nodes, "_build_tools", fake_build_tools)
    monkeypatch.setattr(nodes, "_configure_visual_turn", fake_visual)
    monkeypatch.setattr(nodes.scope_service, "list_data_interfaces_for_user", no_interfaces)
    monkeypatch.setattr(platform_tool_registry, "active_platform_tool_names", no_release)


@pytest.mark.asyncio
async def test_craft_turn_offers_memory_tools_to_a_terminal_user(monkeypatch):
    principal = SimpleNamespace(id="user-1", organization_id=uuid4(), department_id=None, team_id=None, role="member")
    _patch_prepare_dependencies(monkeypatch, principal)

    result = await nodes.prepare_dsh_turn(_craft_state())

    names = [tool["function"]["name"] for tool in result["tools"]]
    assert "read_memory" in names and "write_memory" in names
    assert result["registry"]["read_memory"] == {"kind": "memory", "operation": "read"}
    assert result["registry"]["write_memory"] == {"kind": "memory", "operation": "write"}
    write_def = next(tool["function"] for tool in result["tools"] if tool["function"]["name"] == "write_memory")
    assert write_def["parameters"]["required"] == ["content"]
    specs = {spec["name"]: spec for spec in nodes.dsh_tool_specs(result["tools"], result["registry"])}
    assert specs["read_memory"]["concurrency_safe"] is True
    assert specs["write_memory"]["concurrency_safe"] is False
    assert specs["write_memory"]["kind"] == "memory"


@pytest.mark.asyncio
async def test_ask_and_playground_turns_do_not_offer_memory_tools(monkeypatch):
    principal = SimpleNamespace(id="user-1", organization_id=uuid4(), department_id=None, team_id=None, role="member")
    _patch_prepare_dependencies(monkeypatch, principal)
    ask = await nodes.prepare_dsh_turn(_craft_state(exec_mode="ask"))
    assert ask["tools"] == [] and "write_memory" not in ask["registry"]

    _patch_prepare_dependencies(monkeypatch, None)  # admin playground: no terminal principal
    playground = await nodes.prepare_dsh_turn(_craft_state(mode="agent", user_id=None))
    names = [tool["function"]["name"] for tool in playground["tools"]]
    assert "write_memory" not in names and "read_memory" not in names


class _FakeDb:
    @asynccontextmanager
    async def begin_nested(self):
        yield


@pytest.mark.asyncio
async def test_execute_tool_call_dispatches_memory_tools_for_the_current_principal(monkeypatch):
    from app.tools import capability_tools

    writes: list[tuple[str, str]] = []

    async def fake_write(_db, principal, content):
        writes.append((principal.id, content))
        return "ok: 已沉淀到个人记忆 mem-1"

    async def fake_read(_db, principal):
        return f"[user]\n{principal.id} 偏好账期长的供应商"

    principal = SimpleNamespace(id="user-1", organization_id=uuid4())
    monkeypatch.setattr(nodes, "get_deps", lambda: {"db": _FakeDb(), "user": principal})
    monkeypatch.setattr(capability_tools, "_write_memory", fake_write)
    monkeypatch.setattr(capability_tools, "_read_memory", fake_read)
    registry = {
        "read_memory": {"kind": "memory", "operation": "read"},
        "write_memory": {"kind": "memory", "operation": "write"},
    }
    state = {"task_id": "task-1", "run_id": 1}

    message, preview, ok = await nodes._execute_tool_call(
        state, {"id": "c1", "name": "write_memory", "arguments": {"content": "供应商 A → 账期 → 60 天"}}, registry,
    )
    assert ok is True
    assert writes == [("user-1", "供应商 A → 账期 → 60 天")]
    assert json.loads(message["content"])["status"] == "success"
    assert preview == message["content"]
    assert state["_dsh_memory_written"] is True

    message, _preview, ok = await nodes._execute_tool_call(
        state, {"id": "c2", "name": "read_memory", "arguments": "{}"}, registry,
    )
    assert ok is True
    assert "偏好账期长" in json.loads(message["content"])["memory"]

    message, _preview, ok = await nodes._execute_tool_call(
        state, {"id": "c3", "name": "write_memory", "arguments": {"content": "   "}}, registry,
    )
    assert ok is False
    assert len(writes) == 1  # blank content never reaches the service


@pytest.mark.asyncio
async def test_memory_tools_require_a_terminal_user(monkeypatch):
    monkeypatch.setattr(nodes, "get_deps", lambda: {"db": _FakeDb(), "user": None})

    message, _preview, ok = await nodes._execute_tool_call(
        {}, {"id": "c1", "name": "write_memory", "arguments": {"content": "x"}},
        {"write_memory": {"kind": "memory", "operation": "write"}},
    )

    assert ok is False
    assert "terminal user" in json.loads(message["content"])["error"]


@pytest.mark.asyncio
async def test_extract_memory_skips_the_llm_pass_when_the_run_already_wrote_memory(monkeypatch):
    async def never_called(*_args, **_kwargs):
        raise AssertionError("extract_memory must not call the model after write_memory")

    monkeypatch.setattr(nodes.llm_client, "chat", never_called)
    monkeypatch.setattr(nodes, "get_deps", lambda: {"db": object()})
    state = {
        "mode": "general", "exec_mode": "craft", "user_id": "user-1", "org_id": str(uuid4()),
        "_dsh_memory_written": True, "steps": [{"step": "llm_final"}], "traces": [],
    }

    result = await nodes.extract_memory(state)

    assert result["steps"][-1] == {"step": "extract_memory", "facts": 0, "skipped": "write_memory"}
    assert result["traces"][-1]["skipped"] == "write_memory"
