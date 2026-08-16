"""Regression tests for workspace-file references in the general agent runtime."""

from __future__ import annotations

import json
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.graph import nodes
from app.models.organization import Organization
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
    assert await nodes._execute_builtin_tool(
        state,
        "workspace_read_file",
        {"file_id": str(selected.id)},
    ) == "选中文件的解析内容"
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

    async def fake_build_tools(_db, _skill_ids, _workspace_id):
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
