"""Regression tests for workspace-file references in the general agent runtime."""

from __future__ import annotations

import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.graph import nodes, runner
from app.api import terminal as terminal_api
from app.models.organization import Organization
from app.models.task import Task, TaskMessage
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceFile
from app.schemas.workspace import WorkspaceFileCreate
from app.services import workspace_service


async def _make_workspace_with_file(
    db: AsyncSession,
    *,
    path: str,
    content: str,
) -> tuple[Organization, Workspace, WorkspaceFile]:
    suffix = uuid4().hex[:10]
    org = Organization(name=f"引用测试组织-{suffix}", slug=f"ref-{suffix}")
    db.add(org)
    await db.flush()
    ws = Workspace(
        organization_id=org.id,
        name=f"测试空间-{suffix}",
        slug=f"ws-{suffix}",
        scope_type="organization",
    )
    db.add(ws)
    await db.flush()
    file = await workspace_service.upsert_file(
        db,
        ws,
        WorkspaceFileCreate(path=path, content=content),
    )
    await db.flush()
    return org, ws, file


def test_workspace_file_tool_schema_exposes_ids_and_paths():
    tools = {item["function"]["name"]: item["function"] for item in nodes._builtin_tool_defs()}

    assert "file_id" in tools["workspace_read_file"]["parameters"]["properties"]
    assert "path" in tools["workspace_read_file"]["parameters"]["properties"]
    assert "offset" in tools["workspace_read_file"]["parameters"]["properties"]
    assert "limit" in tools["workspace_read_file"]["parameters"]["properties"]
    assert "file_id" in tools["workspace_list_files"]["description"]
    assert "普通问答、解释或文件分析不得擅自生成附件" in nodes.OUTPUT_PROTOCOL_PROMPT


@pytest.mark.asyncio
async def test_workspace_tools_list_mapping_and_read_by_file_id(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    _, ws, selected = await _make_workspace_with_file(
        db_session,
        path="WAIC展商联系方式.xlsx",
        content="选中文件的解析内容",
    )
    _, other_ws, other_file = await _make_workspace_with_file(
        db_session,
        path="其他空间.xlsx",
        content="不能跨空间读取",
    )
    assert other_ws.id != ws.id
    monkeypatch.setattr(nodes, "get_deps", lambda: {"db": db_session})
    state = {"workspace_id": str(ws.id)}

    listed = json.loads(await nodes._execute_builtin_tool(state, "workspace_list_files", {}))
    assert listed == [{"file_id": str(selected.id), "path": selected.path}]
    read_result = json.loads(await nodes._execute_builtin_tool(
        state,
        "workspace_read_file",
        {"file_id": str(selected.id)},
    ))
    assert read_result["content"] == "选中文件的解析内容"
    assert read_result["has_more"] is False
    assert await nodes._execute_builtin_tool(
        state,
        "workspace_read_file",
        {"file_id": str(other_file.id)},
    ) == "file not found"
    assert await nodes._execute_builtin_tool(
        state,
        "workspace_read_file",
        {},
    ) == "file_id or path is required"


@pytest.mark.asyncio
async def test_builtin_tool_keeps_full_model_result_and_only_truncates_trace_preview(
    monkeypatch: pytest.MonkeyPatch,
):
    full_result = json.dumps({
        "status": "ready",
        "content": "长" * 5000,
    }, ensure_ascii=False)

    async def fake_execute(*_args, **_kwargs):
        return full_result

    monkeypatch.setattr(nodes, "get_deps", lambda: {"db": object()})
    monkeypatch.setattr(nodes, "_execute_builtin_tool", fake_execute)
    tool_message, preview, ok = await nodes._execute_tool_call(
        {},
        {"id": "call-1", "name": "workspace_read_file", "arguments": "{}"},
        {},
    )

    assert ok is True
    assert tool_message["content"] == full_result
    assert len(tool_message["content"]) > 4000
    assert len(preview) < len(full_result)
    assert "模型已收到完整分页结果" in preview


@pytest.mark.asyncio
async def test_builtin_structured_read_error_is_reported_as_failed(
    monkeypatch: pytest.MonkeyPatch,
):
    async def fake_execute(*_args, **_kwargs):
        return json.dumps({"status": "unavailable", "error": "文件已删除"}, ensure_ascii=False)

    monkeypatch.setattr(nodes, "get_deps", lambda: {"db": object()})
    monkeypatch.setattr(nodes, "_execute_builtin_tool", fake_execute)
    tool_message, _preview, ok = await nodes._execute_tool_call(
        {},
        {"id": "call-2", "name": "workspace_read_file", "arguments": "{}"},
        {},
    )

    assert ok is False
    assert "文件已删除" in tool_message["content"]


@pytest.mark.asyncio
async def test_agent_prompt_maps_uuid_to_only_the_referenced_file(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    org, ws, selected = await _make_workspace_with_file(
        db_session,
        path="WAIC展商联系方式.xlsx",
        content="唯一应被分析的文件内容",
    )
    await workspace_service.upsert_file(
        db_session,
        ws,
        WorkspaceFileCreate(
            path="附件3报名表.xlsx",
            content="不应被注入的其他文件内容",
        ),
    )
    await db_session.flush()
    captured: dict = {}

    async def fake_stream_chat(_db, _org_id, _alias, messages, **kwargs):
        captured["messages"] = messages
        captured["system_prompt"] = kwargs["system_prompt"]
        yield "text", "已分析指定文件", None

    async def fake_build_tools(_db, _skill_ids, _workspace_id, _user=None):
        return nodes._builtin_tool_defs(), {}

    monkeypatch.setattr(nodes, "get_deps", lambda: {"db": db_session})
    monkeypatch.setattr(nodes.llm_client, "stream_chat", fake_stream_chat)
    monkeypatch.setattr(nodes, "_build_tools", fake_build_tools)

    file_id = str(selected.id)
    result = await nodes.agent_loop({
        "mode": "general",
        "org_id": str(org.id),
        "workspace_id": str(ws.id),
        "system_prompt": "你是测试助手。",
        "messages": [{"role": "user", "content": f"@{file_id} 这个能分析一下么？"}],
        "referenced_file_ids": [file_id],
        "skill_ids": [],
        "exec_mode": "craft",
        "memory_context": [],
        "rag_context": [],
        "steps": [],
        "traces": [],
        "usage": {},
    })

    prompt = captured["system_prompt"]
    assert f"@{file_id} → WAIC展商联系方式.xlsx" in prompt
    assert f"file_id={file_id} path=WAIC展商联系方式.xlsx" in prompt
    assert "唯一应被分析的文件内容" in prompt
    assert "不应被注入的其他文件内容" not in prompt
    assert "不得声称无法按 UUID 定位" in prompt
    assert "不要调用工作空间列表/读取工具" in prompt
    assert result["assistant_final"] == "已分析指定文件"
    file_trace = next(trace for trace in result["traces"] if trace.get("category") == "file")
    assert file_trace["references"] == [
        {"file_id": file_id, "path": "WAIC展商联系方式.xlsx"},
    ]


@pytest.mark.asyncio
async def test_structured_attachment_injects_exact_file_without_uuid_in_message(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    org, ws, selected = await _make_workspace_with_file(
        db_session,
        path="会话附件/task-1/指定文件.docx",
        content="只能注入这份附件的内容",
    )
    await workspace_service.upsert_file(
        db_session,
        ws,
        WorkspaceFileCreate(path="根目录/其他文件.docx", content="绝对不得注入"),
    )
    await db_session.flush()
    captured: dict = {}

    async def fake_stream_chat(_db, _org_id, _alias, messages, **kwargs):
        captured["system_prompt"] = kwargs["system_prompt"]
        yield "text", "已分析附件", None

    async def fake_build_tools(_db, _skill_ids, _workspace_id, _user=None):
        return nodes._builtin_tool_defs(), {}

    monkeypatch.setattr(nodes, "get_deps", lambda: {"db": db_session})
    monkeypatch.setattr(nodes.llm_client, "stream_chat", fake_stream_chat)
    monkeypatch.setattr(nodes, "_build_tools", fake_build_tools)

    file_id = str(selected.id)
    result = await nodes.agent_loop({
        "mode": "general",
        "org_id": str(org.id),
        "workspace_id": str(ws.id),
        "system_prompt": "你是测试助手。",
        "messages": [{"role": "user", "content": "请分析我刚刚拖入的文件"}],
        "referenced_file_ids": [file_id],
        "skill_ids": [],
        "exec_mode": "craft",
        "memory_context": [],
        "rag_context": [],
        "steps": [],
        "traces": [],
        "usage": {},
    })

    prompt = captured["system_prompt"]
    assert "只能注入这份附件的内容" in prompt
    assert "绝对不得注入" not in prompt
    assert f"@{file_id} → 会话附件/task-1/指定文件.docx" in prompt
    assert result["assistant_final"] == "已分析附件"


def test_general_state_and_message_metadata_preserve_attachment_snapshot():
    file_id = str(uuid4())
    workspace_id = str(uuid4())
    snapshot = {
        "file_id": file_id,
        "workspace_id": workspace_id,
        "path": "会话附件/draft/report.xlsx",
        "name": "report.xlsx",
    }
    user = SimpleNamespace(id=str(uuid4()), department_id=None, team_id=None)

    state = runner._general_initial_state(
        org_id=str(uuid4()),
        user=user,
        task_id=str(uuid4()),
        message="请分析附件",
        session_id=None,
        config={"workspace_id": workspace_id, "model_alias": "test"},
        attachment_files=[snapshot],
    )

    assert state["referenced_file_ids"] == [file_id]
    assert runner._user_message_metadata(state) == {"attachments": [snapshot]}


@pytest.mark.asyncio
async def test_attachment_validation_rejects_cross_workspace_and_unready(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    workspace_id = uuid4()
    other_workspace_id = uuid4()
    file_id = uuid4()
    cu = SimpleNamespace()
    ws = SimpleNamespace(id=workspace_id)

    async def get_workspace(_db, _workspace_id):
        return ws

    monkeypatch.setattr(terminal_api.workspace_service, "get_workspace", get_workspace)
    monkeypatch.setattr(terminal_api.scope_service, "is_workspace_visible", lambda _ws, _cu: True)

    async def cross_workspace_file(_db, _file_id):
        return SimpleNamespace(
            id=file_id,
            workspace_id=other_workspace_id,
            path="other/report.xlsx",
            parse_status="ready",
            parse_error=None,
            metadata_={"name": "report.xlsx"},
        )

    monkeypatch.setattr(terminal_api.workspace_service, "get_file", cross_workspace_file)
    with pytest.raises(HTTPException) as exc_info:
        await terminal_api._resolve_task_attachments(db_session, cu, str(workspace_id), [file_id])
    assert exc_info.value.status_code == 400
    assert "不属于当前任务工作空间" in exc_info.value.detail

    async def unready_file(_db, _file_id):
        return SimpleNamespace(
            id=file_id,
            workspace_id=workspace_id,
            path="会话附件/task/report.xlsx",
            parse_status="failed",
            parse_error="文档已加密",
            metadata_={"name": "report.xlsx"},
        )

    monkeypatch.setattr(terminal_api.workspace_service, "get_file", unready_file)
    with pytest.raises(HTTPException) as exc_info:
        await terminal_api._resolve_task_attachments(db_session, cu, str(workspace_id), [file_id])
    assert exc_info.value.status_code == 422
    assert "文档已加密" in exc_info.value.detail


@pytest.mark.asyncio
async def test_attachment_validation_returns_deduplicated_display_snapshot(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    workspace_id = uuid4()
    file_id = uuid4()
    cu = SimpleNamespace()

    async def get_file(_db, _file_id):
        return SimpleNamespace(
            id=file_id,
            workspace_id=workspace_id,
            path="会话附件/task/internal-report.xlsx",
            parse_status="ready",
            parse_error=None,
            metadata_={"name": "原始报告.xlsx"},
        )

    async def get_workspace(_db, _workspace_id):
        return SimpleNamespace(id=workspace_id)

    monkeypatch.setattr(terminal_api.workspace_service, "get_file", get_file)
    monkeypatch.setattr(terminal_api.workspace_service, "get_workspace", get_workspace)
    monkeypatch.setattr(terminal_api.scope_service, "is_workspace_visible", lambda _ws, _cu: True)

    snapshots = await terminal_api._resolve_task_attachments(
        db_session, cu, str(workspace_id), [file_id, file_id],
    )
    assert snapshots == [{
        "file_id": str(file_id),
        "workspace_id": str(workspace_id),
        "path": "会话附件/task/internal-report.xlsx",
        "name": "原始报告.xlsx",
    }]


@pytest.mark.asyncio
async def test_history_restores_available_and_unavailable_attachment_refs(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    org, ws, available = await _make_workspace_with_file(
        db_session, path="会话附件/task/报告.xlsx", content="历史文件正文",
    )
    user = User(
        organization_id=org.id,
        username=f"history-{uuid4().hex[:8]}",
        role="member",
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()
    task = Task(
        organization_id=org.id,
        user_id=user.id,
        session_id=f"history-{uuid4().hex}",
        title="历史附件",
        message="分析报告",
        config={"workspace_id": str(ws.id)},
    )
    db_session.add(task)
    await db_session.flush()
    missing_id = str(uuid4())
    db_session.add(TaskMessage(
        task_id=task.id,
        role="user",
        content="请分析这两份文件",
        metadata_={"attachments": [
            {"file_id": str(available.id), "workspace_id": str(ws.id),
             "path": available.path, "name": "报告.xlsx"},
            {"file_id": missing_id, "workspace_id": str(ws.id),
             "path": "会话附件/task/已删除.xlsx", "name": "已删除.xlsx"},
        ]},
    ))
    await db_session.flush()

    async def no_memory(*_args, **_kwargs):
        return []

    monkeypatch.setattr(nodes.memory_service, "load_memory_for_scopes", no_memory)
    cu = SimpleNamespace(
        id=str(user.id), organization_id=org.id, department_id=None, team_id=None,
    )
    result = await nodes._load_memory_general(
        {
            "task_id": str(task.id),
            "workspace_id": str(ws.id),
            "org_id": str(org.id),
            "messages": [{"role": "user", "content": "继续分析刚才的文件"}],
            "steps": [],
            "traces": [],
        },
        {"user": cu},
        db_session,
        select,
    )

    history_content = result["messages"][0]["content"]
    assert "[历史消息附件]" in history_content
    assert str(available.id) in history_content
    assert '"status": "available"' in history_content
    assert missing_id in history_content
    assert '"status": "unavailable"' in history_content
    assert "历史文件正文" not in history_content
    assert result["messages"][-1]["content"] == "继续分析刚才的文件"
