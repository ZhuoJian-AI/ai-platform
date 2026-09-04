"""Regression tests for workspace-file references in the general agent runtime."""

from __future__ import annotations

import base64
import io
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from openpyxl import Workbook
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import runtime_support
from app.agents.dsh import runner as dsh_runner
from app.agents.graph import nodes
from app.api import terminal as terminal_api
from app.auth.user_auth import CurrentUser
from app.models.organization import Organization
from app.models.task import Task, TaskMessage
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceFile
from app.schemas.workspace import WorkspaceFileCreate, WorkspaceFolderCreate
from app.services import workspace_permission_service, workspace_service


async def _make_workspace(db: AsyncSession) -> tuple[Organization, Workspace]:
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
    return org, ws


async def _make_personal_principal(
    db: AsyncSession,
    org: Organization,
    workspace: Workspace,
    *,
    prefix: str,
) -> User:
    user = User(
        organization_id=org.id,
        username=f"{prefix}-{uuid4().hex[:8]}",
        role="member",
        is_active=True,
    )
    db.add(user)
    await db.flush()
    workspace.scope_type = "user"
    workspace.scope_id = str(user.id)
    await db.flush()
    return user


async def _make_workspace_with_file(
    db: AsyncSession,
    *,
    path: str,
    content: str,
) -> tuple[Organization, Workspace, WorkspaceFile]:
    org, ws = await _make_workspace(db)
    file = await workspace_service.upsert_file(
        db,
        ws,
        WorkspaceFileCreate(path=path, content=content),
    )
    await db.flush()
    return org, ws, file


def _xlsx_bytes(value: str) -> bytes:
    """Build a real OOXML workbook for tests that exercise spreadsheet replacement."""
    stream = io.BytesIO()
    workbook = Workbook()
    workbook.active["A1"] = value
    workbook.save(stream)
    workbook.close()
    return stream.getvalue()


def test_workspace_file_tool_schema_exposes_ids_and_paths():
    tools = {item["function"]["name"]: item["function"] for item in nodes._builtin_tool_defs()}

    assert "file_id" in tools["workspace_read_file"]["parameters"]["properties"]
    assert "path" in tools["workspace_read_file"]["parameters"]["properties"]
    assert "offset" in tools["workspace_read_file"]["parameters"]["properties"]
    assert "limit" in tools["workspace_read_file"]["parameters"]["properties"]
    assert "workspace_id" in tools["workspace_list_files"]["parameters"]["properties"]
    assert "workspace_id" in tools["workspace_read_file"]["parameters"]["properties"]
    assert "target_workspace_id" in tools["workspace_write_file"]["parameters"]["properties"]
    assert "target_workspace_id" in tools["spreadsheet_tool"]["parameters"]["properties"]
    assert "target_file_id" in tools["spreadsheet_tool"]["parameters"]["properties"]
    assert "base_version_id" in tools["document_tool"]["parameters"]["properties"]
    assert "idempotency_key" in tools["presentation_tool"]["parameters"]["properties"]
    assert "offset" in tools["workspace_search"]["parameters"]["properties"]
    assert "普通问答、解释或文件分析不得擅自生成附件" in nodes.OUTPUT_PROTOCOL_PROMPT


@pytest.mark.asyncio
async def test_workspace_tools_list_mapping_and_read_by_file_id(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    _, ws, selected = await _make_workspace_with_file(
        db_session,
        path="WAIC展商联系方式.txt",
        content="选中文件的解析内容",
    )
    _, other_ws, other_file = await _make_workspace_with_file(
        db_session,
        path="其他空间.txt",
        content="不能跨空间读取",
    )
    assert other_ws.id != ws.id
    monkeypatch.setattr(nodes, "get_deps", lambda: {"db": db_session})
    state = {"workspace_id": str(ws.id)}

    listed = json.loads(await nodes._execute_builtin_tool(state, "workspace_list_files", {}))
    assert listed["has_more"] is False
    assert [(item["file_id"], item["path"]) for item in listed["items"]] == [
        (str(selected.id), selected.path),
    ]
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
        path="WAIC展商联系方式.txt",
        content="唯一应被分析的文件内容",
    )
    await workspace_service.upsert_file(
        db_session,
        ws,
        WorkspaceFileCreate(
            path="附件3报名表.txt",
            content="不应被注入的其他文件内容",
        ),
    )
    user = await _make_personal_principal(
        db_session, org, ws, prefix="prompt-ref",
    )
    principal = CurrentUser(
        user=user,
        id=str(user.id),
        email=user.username,
        role=user.role,
        organization_id=org.id,
    )
    await db_session.flush()
    async def fake_build_tools(
        _db,
        _skill_ids,
        _workspace_id,
        _user=None,
        *,
            exec_mode="craft",
            application_id=None,
            page_context=None,
    ):
        return nodes._builtin_tool_defs(), {}

    async def fake_visual(_state, _db, _user, _messages, prompt):
        return None, None, prompt

    monkeypatch.setattr(nodes, "get_deps", lambda: {"db": db_session, "user": principal})
    monkeypatch.setattr(nodes, "_build_tools", fake_build_tools)
    monkeypatch.setattr(nodes, "_configure_visual_turn", fake_visual)

    file_id = str(selected.id)
    result = await nodes.prepare_dsh_turn({
        "mode": "general",
        "org_id": str(org.id),
        "workspace_id": str(ws.id),
        "system_prompt": "你是测试助手。",
        "messages": [{"role": "user", "content": f"@{file_id} 这个能分析一下么？"}],
        "referenced_file_ids": [file_id],
        "file_refs_v1": [{"file_id": file_id, "inject_content": True}],
        "skill_ids": [],
        "exec_mode": "craft",
        "memory_context": [],
        "rag_context": [],
        "steps": [],
        "traces": [],
        "usage": {},
    })

    prompt = result["system_prompt"]
    canonical = f"{ws.name}:/WAIC展商联系方式.txt"
    assert f"@{file_id} → {canonical}" in prompt
    assert f"file_id={file_id}" in prompt
    assert f"path={canonical}" in prompt
    assert "唯一应被分析的文件内容" in prompt
    assert "不应被注入的其他文件内容" not in prompt
    assert "不得声称无法按 UUID 定位" in prompt
    assert "引用是上下文提示，不是授权凭证" in prompt
    file_trace = next(trace for trace in result["traces"] if trace.get("category") == "file")
    assert file_trace["references"] == [
        {
            "file_id": file_id,
            "path": canonical,
            "version_id": str(selected.current_version_id),
        },
    ]


@pytest.mark.asyncio
async def test_structured_attachment_injects_exact_file_without_uuid_in_message(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    org, ws, selected = await _make_workspace_with_file(
        db_session,
        path="会话附件/task-1/指定文件.txt",
        content="只能注入这份附件的内容",
    )
    await workspace_service.upsert_file(
        db_session,
        ws,
        WorkspaceFileCreate(path="根目录/其他文件.txt", content="绝对不得注入"),
    )
    user = await _make_personal_principal(
        db_session, org, ws, prefix="structured-ref",
    )
    principal = CurrentUser(
        user=user,
        id=str(user.id),
        email=user.username,
        role=user.role,
        organization_id=org.id,
    )
    await db_session.flush()
    async def fake_build_tools(
        _db,
        _skill_ids,
        _workspace_id,
        _user=None,
        *,
            exec_mode="craft",
            application_id=None,
            page_context=None,
    ):
        return nodes._builtin_tool_defs(), {}

    async def fake_visual(_state, _db, _user, _messages, prompt):
        return None, None, prompt

    monkeypatch.setattr(nodes, "get_deps", lambda: {"db": db_session, "user": principal})
    monkeypatch.setattr(nodes, "_build_tools", fake_build_tools)
    monkeypatch.setattr(nodes, "_configure_visual_turn", fake_visual)

    file_id = str(selected.id)
    result = await nodes.prepare_dsh_turn({
        "mode": "general",
        "org_id": str(org.id),
        "workspace_id": str(ws.id),
        "system_prompt": "你是测试助手。",
        "messages": [{"role": "user", "content": "请分析我刚刚拖入的文件"}],
        "referenced_file_ids": [file_id],
        "file_refs_v1": [{"file_id": file_id, "inject_content": True}],
        "skill_ids": [],
        "exec_mode": "craft",
        "memory_context": [],
        "rag_context": [],
        "steps": [],
        "traces": [],
        "usage": {},
    })

    prompt = result["system_prompt"]
    assert "只能注入这份附件的内容" in prompt
    assert "绝对不得注入" not in prompt
    assert f"@{file_id} → {ws.name}:/会话附件/task-1/指定文件.txt" in prompt


@pytest.mark.asyncio
async def test_dsh_runtime_retracts_unverified_tool_success(
    monkeypatch: pytest.MonkeyPatch,
):
    fake_id = str(uuid4())

    async def fake_stream_run(_payload):
        yield {
            "type": "text_delta",
            "delta": f"已真实调用 image_tool，执行成功，file_id={fake_id}",
        }
        yield {"type": "done"}

    monkeypatch.setattr(dsh_runner.client, "stream_run", fake_stream_run)
    state = {"run_id": 1, "request": "请处理附件", "steps": [], "messages": []}
    staged: list[dict] = []
    await dsh_runner._consume_dsh(
        state,
        {"system_prompt": "测试", "tools": [], "memory_context": None},
        "run-token",
        None,
        staged,
    )

    assert fake_id not in state["assistant_final"]
    assert any(event.get("type") == "text_retract" for event in staged)
    assert any(step.get("step") == "tool_claim_rejected" for step in state["steps"])


def test_general_state_and_message_metadata_preserve_attachment_snapshot():
    file_id = str(uuid4())
    workspace_id = str(uuid4())
    snapshot = {
        "file_id": file_id,
        "workspace_id": workspace_id,
        "path": "会话附件/draft/report.xlsx",
        "name": "report.xlsx",
    }
    invoked_skill = {
        "id": str(uuid4()), "name": "Workbook Cleaner", "slug": "workbook-cleaner",
        "scope_type": "user", "is_executable": True,
    }
    user = SimpleNamespace(id=str(uuid4()), department_id=None, team_id=None)

    state = runtime_support.general_initial_state(
        org_id=str(uuid4()),
        user=user,
        task_id=str(uuid4()),
        message="请分析附件",
        session_id=None,
        config={"workspace_id": workspace_id, "model_alias": "test"},
        attachment_files=[snapshot],
        invoked_skills=[invoked_skill],
    )

    assert state["referenced_file_ids"] == [file_id]
    assert state["invoked_skill_ids"] == [invoked_skill["id"]]
    assert runtime_support.user_message_metadata(state) == {
        "attachments": [snapshot], "invoked_skills": [invoked_skill],
    }


@pytest.mark.asyncio
async def test_attachment_validation_accepts_authorized_cross_workspace_and_unready(
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
    snapshots = await terminal_api._resolve_task_attachments(
        db_session, cu, str(workspace_id), [file_id],
    )
    assert snapshots[0]["workspace_id"] == str(other_workspace_id)

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
    snapshots = await terminal_api._resolve_task_attachments(
        db_session, cu, str(workspace_id), [file_id],
    )
    assert snapshots[0]["file_id"] == str(file_id)

    async def raw_png_file(_db, _file_id):
        return SimpleNamespace(
            id=file_id,
            workspace_id=workspace_id,
            path="会话附件/task/screenshot.png",
            parse_status="unsupported",
            parse_error="不支持的文件类型",
            metadata_={"name": "截图.png", "binary": True, "mime": "image/png"},
        )

    monkeypatch.setattr(terminal_api.workspace_service, "get_file", raw_png_file)
    snapshots = await terminal_api._resolve_task_attachments(
        db_session, cu, str(workspace_id), [file_id],
    )
    assert snapshots[0]["name"] == "截图.png"


def test_workspace_intent_is_capability_derived_not_keyword_gated() -> None:
    personal_id = str(uuid4())
    finance_id = str(uuid4())
    access = {
        "roles": [{"name": "财务经理"}],
        "workspaces": [
            {"id": personal_id, "name": "我的空间", "slug": "me", "scope_type": "user",
             "capabilities": {"read": True, "create": True, "update": True, "delete": True}},
            {"id": finance_id, "name": "财务部", "slug": "finance-dept", "scope_type": "department",
             "capabilities": {"read": True, "create": True, "update": True, "delete": False}},
        ],
    }

    question = workspace_permission_service.resolve_workspace_intent(
        access, "我能不能修改财务部文件？",
    )
    assert question["permission_question"] is False
    assert set(question["read_workspace_ids"]) == {personal_id, finance_id}
    assert set(question["write_workspace_ids"]) == {personal_id, finance_id}

    operation = workspace_permission_service.resolve_workspace_intent(
        access, "请修改财务部文件里的预算表",
    )
    assert operation["permission_question"] is False
    assert finance_id in operation["read_workspace_ids"]
    assert finance_id in operation["write_workspace_ids"]

    exact_reference = workspace_permission_service.resolve_workspace_intent(
        access, "请分析附件", referenced_workspace_ids=[finance_id],
    )
    assert finance_id in exact_reference["read_workspace_ids"]

    all_authorized_files = workspace_permission_service.resolve_workspace_intent(
        access, "请列出所有我有权限的部门文件",
    )
    assert all_authorized_files["permission_question"] is False
    assert finance_id in all_authorized_files["read_workspace_ids"]

    prompt = nodes._workspace_access_prompt(access, question)
    assert "财务经理" in prompt
    assert "所有实时 read=true 的空间中使用 workspace_search" in prompt
    assert "预算表" not in prompt


@pytest.mark.asyncio
async def test_delete_inferred_workspace_folder_path_recursively(db_session: AsyncSession):
    _, ws, first = await _make_workspace_with_file(
        db_session,
        path="平台工具输出/task-a/result.txt",
        content="a",
    )
    second = await workspace_service.upsert_file(
        db_session,
        ws,
        WorkspaceFileCreate(path="平台工具输出/task-b/report.md", content="b"),
    )
    keep = await workspace_service.upsert_file(
        db_session,
        ws,
        WorkspaceFileCreate(path="会话附件/task-c/input.txt", content="c"),
    )
    await db_session.flush()

    deleted = await workspace_service.soft_delete_folder_path(
        db_session, ws.id, "平台工具输出",
    )

    assert deleted == {"folders": 0, "files": 2}
    assert first.deleted_at is not None
    assert second.deleted_at is not None
    assert keep.deleted_at is None


@pytest.mark.asyncio
async def test_bulk_delete_deduplicates_nested_folders_and_selected_files(db_session: AsyncSession):
    _, ws, first = await _make_workspace_with_file(
        db_session, path="平台工具输出/task-a/result.txt", content="a",
    )
    second = await workspace_service.upsert_file(
        db_session, ws, WorkspaceFileCreate(path="平台工具输出/task-b/report.md", content="b"),
    )
    keep = await workspace_service.upsert_file(
        db_session, ws, WorkspaceFileCreate(path="会话附件/task-c/input.txt", content="c"),
    )
    await workspace_service.create_folder(
        db_session, ws, WorkspaceFolderCreate(path="平台工具输出/task-a"),
    )

    deleted = await workspace_service.bulk_soft_delete_items(
        db_session,
        ws.id,
        file_ids=[first.id, first.id],
        folder_paths=["平台工具输出", "平台工具输出/task-a"],
    )

    assert deleted == {"deleted_files": 2, "deleted_folders": 1}
    assert first.deleted_at is not None
    assert second.deleted_at is not None
    assert keep.deleted_at is None


@pytest.mark.asyncio
async def test_bulk_delete_rejects_cross_workspace_and_traversal(db_session: AsyncSession):
    _, ws, _ = await _make_workspace_with_file(db_session, path="keep.txt", content="a")
    _, other_ws, other = await _make_workspace_with_file(db_session, path="other.txt", content="b")

    with pytest.raises(ValueError, match="不属于当前工作空间"):
        await workspace_service.bulk_soft_delete_items(
            db_session, ws.id, file_ids=[other.id], folder_paths=[],
        )
    with pytest.raises(ValueError, match="不能包含"):
        await workspace_service.bulk_soft_delete_items(
            db_session, other_ws.id, file_ids=[], folder_paths=["../根目录"],
        )


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
        db_session, path="会话附件/task/报告.txt", content="历史文件正文",
    )
    user = await _make_personal_principal(
        db_session, org, ws, prefix="history",
    )
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
             "path": available.path, "name": "报告.txt"},
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
    assert "[历史文件引用]" in history_content
    assert str(available.id) in history_content
    assert '"status": "available"' in history_content
    assert missing_id in history_content
    assert '"status": "unavailable"' in history_content
    assert "历史文件正文" not in history_content
    assert result["messages"][-1]["content"] == "继续分析刚才的文件"


@pytest.mark.asyncio
async def test_agent_searches_and_reads_authorized_shared_space_without_reference(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    _, default_ws, _ = await _make_workspace_with_file(
        db_session, path="personal.txt", content="personal",
    )
    _, shared_ws, shared_file = await _make_workspace_with_file(
        db_session, path="2026冬尺寸表/AD2604M601.txt", content="shared-data",
    )
    principal = SimpleNamespace(id=str(uuid4()))
    allowed = {"value": True}

    async def caps(*_args, **_kwargs):
        value = allowed["value"]
        return {"read": value, "create": value, "update": value, "delete": value}

    async def readable_workspaces(*_args, **_kwargs):
        return [default_ws, shared_ws]

    monkeypatch.setattr(nodes, "get_deps", lambda: {"db": db_session, "user": principal})
    monkeypatch.setattr(nodes.workspace_permission_service, "capabilities", caps)
    monkeypatch.setattr(nodes.scope_service, "list_workspaces_for_user", readable_workspaces)
    state = {"workspace_id": str(default_ws.id), "referenced_file_ids": []}

    searched = json.loads(await nodes._execute_builtin_tool(
        state, "workspace_search", {"query": "AD2604", "limit": 10, "offset": 0},
    ))
    assert [item["file_id"] for item in searched["items"]] == [str(shared_file.id)]
    assert searched["items"][0]["canonical_path"] == (
        f"{shared_ws.name}:/2026冬尺寸表/AD2604M601.txt"
    )

    read = json.loads(await nodes._execute_builtin_tool(
        state, "workspace_read_file", {"file_id": str(shared_file.id)},
    ))
    assert read["content"] == "shared-data"

    # The next operation uses fresh capabilities rather than the earlier result
    # or an attachment/file-ref snapshot.
    allowed["value"] = False
    denied = await nodes._execute_builtin_tool(
        state, "workspace_read_file", {"file_id": str(shared_file.id)},
    )
    assert denied == "file not found"


@pytest.mark.asyncio
async def test_platform_runner_target_file_updates_in_place(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    org, ws = await _make_workspace(db_session)
    file = await workspace_service.ingest_uploaded_file(
        db_session,
        ws,
        path="财务/共享明细.xlsx",
        filename="共享明细.xlsx",
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        raw=_xlsx_bytes("old"),
    )
    principal_user = User(
        organization_id=org.id,
        username=f"runner-{uuid4().hex[:8]}",
        role="member",
        is_active=True,
    )
    db_session.add(principal_user)
    await db_session.flush()
    principal = SimpleNamespace(id=str(principal_user.id))
    base_version_id = file.current_version_id
    output_bytes = _xlsx_bytes("new")

    async def caps(*_args, **_kwargs):
        return {"read": True, "create": True, "update": True, "delete": False}

    async def execute_builtin(**_kwargs):
        return ({
            "summary": "updated",
            "outputs": [{
                "name": "runner-output.xlsx",
                "mime_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "content_base64": base64.b64encode(output_bytes).decode("ascii"),
            }],
        }, 12)

    monkeypatch.setattr(nodes, "get_deps", lambda: {"db": db_session, "user": principal})
    monkeypatch.setattr(nodes.workspace_permission_service, "capabilities", caps)
    monkeypatch.setattr(nodes.skill_runner_client, "execute_builtin", execute_builtin)

    result = json.loads(await nodes._execute_builtin_tool(
        {"workspace_id": str(ws.id), "exec_mode": "craft", "referenced_file_ids": []},
        "spreadsheet_tool",
        {
            "action": "edit",
            "target_file_id": str(file.id),
            "base_version_id": str(base_version_id),
            "idempotency_key": "runner-update-0001",
            "operations": [],
        },
    ))

    await db_session.refresh(file)
    assert result["status"] == "success"
    assert result["outputs"][0]["file_id"] == str(file.id)
    assert file.current_version_id != base_version_id
    assert file.content == base64.b64encode(output_bytes).decode("ascii")
