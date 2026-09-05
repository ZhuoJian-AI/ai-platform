"""Focused coverage for scoped Skill authorization, versions, and Agent exposure."""

from __future__ import annotations

import base64
import io
import json
import zipfile
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException, UploadFile

from app.agents.graph import nodes
from app.agents.graph.nodes import _build_tools
from app.api.skill_packages import _import_response
from app.auth.user_auth import CurrentUser
from app.models.agent import Agent
from app.models.department import Department
from app.models.organization import Organization
from app.models.rag import RagCollection
from app.models.skill import SkillFolder, SkillVersion
from app.models.team import Team
from app.models.user import User
from app.models.workspace import Workspace
from app.schemas.user import ManagerScopeGrant
from app.services import platform_tool_registry, skill_import_service, workspace_service
from app.services.scope_service import assert_bound_rags_visible
from app.services.skill_scope_service import (
    assert_bound_skills_visible,
    assert_user_can_manage_scope,
    managed_scopes,
    replace_manager_grants,
    validate_scope_target,
)

_AUTHENTICATED_BUILTIN_TOOLS = {
    "workspace_list",
    "workspace_search",
    "workspace_get_file",
    "workspace_list_files",
    "workspace_read_file",
    "workspace_create_file",
    "workspace_write_file",
    "workspace_update_file",
    "workspace_rename_file",
    "workspace_move_file",
    "workspace_copy_file",
    "workspace_delete_file",
    "workspace_list_versions",
    "workspace_restore_version",
    "web_tool",
    *nodes.PLATFORM_TOOL_NAMES,
}


async def _hierarchy(db_session):
    org = Organization(name="Scoped Skill Org", slug=f"scoped-{uuid4().hex[:8]}")
    other_org = Organization(name="Other Org", slug=f"other-{uuid4().hex[:8]}")
    db_session.add_all([org, other_org])
    await db_session.flush()
    department = Department(
        organization_id=org.id, name="Finance", slug=f"finance-{uuid4().hex[:6]}",
    )
    other_department = Department(
        organization_id=other_org.id, name="Other Finance", slug=f"other-finance-{uuid4().hex[:6]}",
    )
    db_session.add_all([department, other_department])
    await db_session.flush()
    team = Team(
        organization_id=org.id, department_id=department.id,
        name="Accounting", slug=f"accounting-{uuid4().hex[:6]}",
    )
    user = User(
        organization_id=org.id, username=f"member-{uuid4().hex[:8]}", role="member",
        department_id=department.id, team_id=None, is_active=True,
    )
    db_session.add_all([team, user])
    await db_session.flush()
    cu = CurrentUser(
        user=user, id=str(user.id), email=user.username, role=user.role,
        organization_id=org.id, department_id=str(department.id), team_id=None,
    )
    return org, other_org, department, other_department, team, user, cu


@pytest.mark.asyncio
async def test_department_manager_inherits_team_management_and_cross_tenant_is_rejected(db_session):
    org, other_org, department, other_department, team, user, cu = await _hierarchy(db_session)
    await replace_manager_grants(db_session, user, [
        ManagerScopeGrant(scope_type="department", scope_id=department.id),
    ])

    scopes = await managed_scopes(db_session, cu)
    assert ("department", str(department.id)) in scopes
    assert ("team", str(team.id)) in scopes
    assert await assert_user_can_manage_scope(db_session, cu, "team", team.id) == str(team.id)

    with pytest.raises(HTTPException) as exc:
        await validate_scope_target(db_session, org.id, "department", other_department.id)
    assert exc.value.status_code == 422

    foreign = SkillFolder(
        organization_id=other_org.id, scope_type="organization", scope_id=None,
        name="Foreign", slug=f"foreign-{uuid4().hex[:8]}", is_active=True,
    )
    db_session.add(foreign)
    await db_session.flush()
    with pytest.raises(HTTPException) as exc:
        await assert_bound_skills_visible(db_session, cu, [str(foreign.id)], require_ready=False)
    assert exc.value.status_code == 403

    foreign_rag = RagCollection(
        organization_id=other_org.id, name="Foreign Knowledge", slug=f"foreign-rag-{uuid4().hex[:8]}",
        scope_type="organization", scope_id=None,
    )
    db_session.add(foreign_rag)
    await db_session.flush()
    with pytest.raises(HTTPException) as exc:
        await assert_bound_rags_visible(db_session, cu, [str(foreign_rag.id)])
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_prompt_skill_import_is_idempotent_versioned_and_bound_only(db_session):
    org, _, department, _, _, user, cu = await _hierarchy(db_session)
    skill_v1 = b"""---
name: Ningbo Bank Processor
description: Process Ningbo bank statements
command: bank-process
runtime: prompt
user_invocable: true
---

# Instructions
Always validate the input workbook before processing.
"""
    upload = UploadFile(filename="SKILL.md", file=io.BytesIO(skill_v1))
    folder, version1 = await skill_import_service.import_package(
        db_session, org_id=org.id, scope_type="user", scope_id=str(user.id),
        upload=upload, created_by=str(user.id),
    )
    assert version1.version_no == 1
    assert version1.install_status == "ready"
    assert folder.active_version_id == version1.id
    await db_session.commit()
    response = await _import_response(db_session, folder, version1)
    assert response.folder.is_installed is True

    duplicate = UploadFile(filename="skill.md", file=io.BytesIO(skill_v1))
    same_folder, same_version = await skill_import_service.import_package(
        db_session, org_id=org.id, scope_type="user", scope_id=str(user.id),
        upload=duplicate, created_by=str(user.id),
    )
    assert same_folder.id == folder.id
    assert same_version.id == version1.id

    skill_v2 = skill_v1 + b"\nReturn an audit summary.\n"
    upgraded = UploadFile(filename="skill.md", file=io.BytesIO(skill_v2))
    _, version2 = await skill_import_service.import_package(
        db_session, org_id=org.id, scope_type="user", scope_id=str(user.id),
        upload=upgraded, created_by=str(user.id),
    )
    assert version2.version_no == 2
    assert version2.id != version1.id
    assert folder.active_version_id == version1.id
    assert version1.archive != version2.archive

    assert await assert_bound_skills_visible(db_session, cu, [str(folder.id)]) == [folder]
    empty_tools, empty_registry = await _build_tools(db_session, [], None, user=cu)
    empty_names = {tool["function"]["name"] for tool in empty_tools}
    assert _AUTHENTICATED_BUILTIN_TOOLS <= empty_names
    assert empty_registry == {}
    tools, registry = await _build_tools(db_session, [str(folder.id)], None, user=cu)
    tool_names = {tool["function"]["name"] for tool in tools}
    assert _AUTHENTICATED_BUILTIN_TOOLS <= tool_names
    assert "load_bank-process" in tool_names
    assert set(registry) == {"load_bank-process"}

    folder.is_active = False
    await db_session.flush()
    with pytest.raises(HTTPException) as exc:
        await assert_bound_skills_visible(db_session, cu, [str(folder.id)])
    assert exc.value.status_code == 422
    disabled_tools, disabled_registry = await _build_tools(
        db_session, [str(folder.id)], None, user=cu,
    )
    disabled_names = {tool["function"]["name"] for tool in disabled_tools}
    assert _AUTHENTICATED_BUILTIN_TOOLS <= disabled_names
    assert "load_bank-process" not in disabled_names
    assert disabled_registry == {}


@pytest.mark.asyncio
async def test_agent_skill_folder_and_zip_are_equivalent_and_progressively_loaded(db_session, monkeypatch):
    org, _, _, _, _, user, cu = await _hierarchy(db_session)
    skill_md = b"""---
name: Workbook Cleaner
description: Clean an uploaded workbook and create a normalized copy
---

# Workflow
Read references/rules.md, then run scripts/clean.py with the input attachment.
"""
    package_files = {
        "bank-skill/SKILL.md": skill_md,
        "bank-skill/references/rules.md": b"Keep the first worksheet.",
        "bank-skill/scripts/clean.py": b"print('ready')\n",
    }
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for path, raw in package_files.items():
            zf.writestr(path, raw)

    monkeypatch.setattr(skill_import_service.settings, "code_skills_enabled", False)
    zip_upload = UploadFile(filename="bank-skill.zip", file=io.BytesIO(archive.getvalue()))
    folder, zip_version = await skill_import_service.import_package(
        db_session, org_id=org.id, scope_type="user", scope_id=str(user.id),
        upload=zip_upload, created_by=str(user.id),
    )
    folder_uploads = [
        UploadFile(filename=path.rsplit("/", 1)[-1], file=io.BytesIO(raw))
        for path, raw in package_files.items()
    ]
    same_folder, folder_version = await skill_import_service.import_package_folder(
        db_session, org_id=org.id, scope_type="user", scope_id=str(user.id),
        uploads=folder_uploads, relative_paths=list(package_files), created_by=str(user.id),
    )
    assert same_folder.id == folder.id
    assert folder_version.id == zip_version.id
    assert zip_version.runtime == "agent_skill"
    assert zip_version.manifest["_platform"]["script_languages"] == ["python"]
    assert {item["path"] for item in zip_version.manifest["_platform"]["resources"]} == {
        "SKILL.md", "references/rules.md", "scripts/clean.py",
    }

    monkeypatch.setattr(skill_import_service.settings, "code_skills_enabled", True)
    tools, registry = await _build_tools(db_session, [str(folder.id)], None, user=cu)
    tool_names = {item["function"]["name"] for item in tools}
    assert _AUTHENTICATED_BUILTIN_TOOLS <= tool_names
    assert {"load_skill", "read_skill_resource", "run_skill_script"} <= tool_names
    run_tool = next(
        item["function"] for item in tools
        if item.get("function", {}).get("name") == "run_skill_script"
    )
    args_description = run_tool["parameters"]["properties"]["args"]["description"]
    assert "{input_file}" in args_description
    assert "{output_dir}" in args_description
    assert "严禁猜测" in args_description
    monkeypatch.setattr(nodes, "get_deps", lambda: {"db": db_session, "user": cu})
    state = {"org_id": str(org.id)}
    loaded = json.loads(await nodes._execute_agent_skill_tool(
        state, registry["load_skill"], "load_skill", {"skill_slug": folder.slug},
    ))
    assert loaded["status"] == "success"
    assert "scripts/clean.py" in {item["path"] for item in loaded["scripts"]}
    resource = json.loads(await nodes._execute_agent_skill_tool(
        state, registry["read_skill_resource"], "read_skill_resource",
        {"skill_slug": folder.slug, "path": "references/rules.md"},
    ))
    assert resource["content"] == "Keep the first worksheet."
    denied = json.loads(await nodes._execute_agent_skill_tool(
        state, registry["load_skill"], "load_skill", {"skill_slug": "not-bound"},
    ))
    assert denied["status"] == "error"

    workspace = Workspace(
        organization_id=org.id,
        name="Agent Skill workspace",
        slug=f"agent-skill-{uuid4().hex[:8]}",
        scope_type="user",
        scope_id=str(user.id),
        is_active=True,
    )
    db_session.add(workspace)
    await db_session.flush()
    input_file = await workspace_service.ingest_uploaded_file(
        db_session,
        workspace,
        path="会话附件/test/input.txt",
        filename="input.txt",
        content_type="text/plain",
        raw=b"source data",
    )
    runner = AsyncMock(return_value=({
        "stdout": "normalized",
        "outputs": [{
            "name": "normalized.txt",
            "content_base64": base64.b64encode(b"clean data").decode(),
        }],
    }, 23))
    monkeypatch.setattr(nodes.skill_runner_client, "execute_version", runner)
    run_state = {
        "org_id": str(org.id),
        "task_id": None,
        "template_agent_id": None,
        "workspace_id": str(workspace.id),
        "exec_mode": "craft",
        "referenced_file_ids": [str(input_file.id)],
    }
    executed = json.loads(await nodes._execute_agent_skill_tool(
        run_state,
        registry["run_skill_script"],
        "run_skill_script",
        {
            "skill_slug": folder.slug,
            "script_path": "scripts/clean.py",
            "args": ["{input_file}", "{output_dir}/normalized.txt"],
        },
    ))
    assert executed["status"] == "success"
    assert executed["summary"] == "normalized"
    assert executed["outputs"][0]["name"] == "normalized.txt"
    assert executed["outputs"][0]["path"].startswith("技能输出/playground/")
    runner.assert_awaited_once()
    runner_call = runner.await_args.kwargs
    assert runner_call["script_path"] == "scripts/clean.py"
    assert runner_call["args"] == ["{input_file}", "{output_dir}/normalized.txt"]
    assert runner_call["inputs"][0]["name"] == "input.txt"


def test_agent_skill_archive_rejects_traversal_and_expansion_limits(monkeypatch):
    traversal = io.BytesIO()
    with zipfile.ZipFile(traversal, "w") as archive:
        archive.writestr("../SKILL.md", "blocked")
    with pytest.raises(HTTPException, match="Unsafe path"):
        skill_import_service._safe_archive(traversal.getvalue(), "unsafe.zip")

    monkeypatch.setattr(skill_import_service, "MAX_ARCHIVE_FILES", 1)
    too_many = io.BytesIO()
    with zipfile.ZipFile(too_many, "w") as archive:
        archive.writestr("SKILL.md", "manifest")
        archive.writestr("scripts/run.py", "print('x')")
    with pytest.raises(HTTPException, match="1-1 files"):
        skill_import_service._safe_archive(too_many.getvalue(), "too-many.zip")

    monkeypatch.setattr(skill_import_service, "MAX_ARCHIVE_FILES", 1000)
    monkeypatch.setattr(skill_import_service, "MAX_UNCOMPRESSED_BYTES", 4)
    expanded = io.BytesIO()
    with zipfile.ZipFile(expanded, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("SKILL.md", "12345")
    with pytest.raises(HTTPException, match="Expanded Skill package"):
        skill_import_service._safe_archive(expanded.getvalue(), "expanded.zip")


@pytest.mark.asyncio
async def test_agent_skill_folder_applies_total_upload_limit(monkeypatch):
    monkeypatch.setattr(skill_import_service, "MAX_UNCOMPRESSED_BYTES", 8)
    monkeypatch.setattr(skill_import_service, "MAX_PACKAGE_BYTES", 1024)
    uploads = [
        UploadFile(filename="SKILL.md", file=io.BytesIO(b"12345")),
        UploadFile(filename="run.py", file=io.BytesIO(b"6789")),
    ]
    with pytest.raises(HTTPException, match="Expanded Skill package exceeds 500MB"):
        await skill_import_service._folder_archive(
            uploads,
            ["SKILL.md", "scripts/run.py"],
        )


def test_agent_skill_rejects_case_insensitive_duplicate_paths():
    with pytest.raises(HTTPException, match="Duplicate Skill path"):
        skill_import_service._normalize_files({
            "SKILL.md": b"---\nname: Example\ndescription: example\n---\n",
            "scripts/Run.py": b"print('first')",
            "scripts/run.py": b"print('second')",
        })


def test_standard_agent_skill_requires_root_manifest_and_scripts_directory() -> None:
    manifest = b"---\nname: Example\ndescription: example\n---\n"
    with pytest.raises(HTTPException, match="SKILL.md at package root"):
        skill_import_service._validate_standard_agent_skill_layout(
            {"nested/SKILL.md": manifest, "nested/scripts/run.py": b"print('ok')"},
            "nested/SKILL.md",
        )
    with pytest.raises(HTTPException, match="must be under scripts"):
        skill_import_service._validate_standard_agent_skill_layout(
            {"SKILL.md": manifest, "process_bank_statement.py": b"print('bad')"},
            "SKILL.md",
        )
    skill_import_service._validate_standard_agent_skill_layout(
        {"SKILL.md": manifest, "scripts/process_bank_statement.py": b"print('ok')"},
        "SKILL.md",
    )


def test_agent_skill_normalized_archive_respects_compressed_limit(monkeypatch):
    monkeypatch.setattr(skill_import_service, "MAX_PACKAGE_BYTES", 4)
    with pytest.raises(HTTPException, match="Normalized Skill archive exceeds 100MB"):
        skill_import_service._normalize_files({"SKILL.md": b"manifest"})


@pytest.mark.asyncio
async def test_executable_skill_output_is_ingested_into_workspace(db_session, monkeypatch):
    org, _, department, _, _, user, cu = await _hierarchy(db_session)
    workspace = Workspace(
        organization_id=org.id,
        name="Personal workspace",
        slug=f"personal-{uuid4().hex[:8]}",
        scope_type="user",
        scope_id=str(user.id),
        is_active=True,
    )
    folder = SkillFolder(
        organization_id=org.id,
        scope_type="user",
        scope_id=str(user.id),
        created_by=str(user.id),
        name="Executable report",
        slug=f"report-{uuid4().hex[:8]}",
        is_active=True,
    )
    db_session.add_all([workspace, folder])
    await db_session.flush()
    version = SkillVersion(
        skill_folder_id=folder.id,
        version_no=1,
        package_hash=uuid4().hex + uuid4().hex,
        manifest={},
        archive=b"test-package",
        runtime="python",
        entrypoint="main.py",
        is_executable=True,
        install_status="ready",
    )
    db_session.add(version)
    await db_session.flush()
    folder.active_version_id = version.id
    await db_session.flush()

    monkeypatch.setattr(nodes, "get_deps", lambda: {"db": db_session, "user": cu})
    monkeypatch.setattr(
        nodes.skill_runner_client,
        "execute_version",
        AsyncMock(return_value=({
            "stdout": "created result",
            "outputs": [{
                "name": "result.txt",
                "content_base64": base64.b64encode("处理完成".encode()).decode(),
            }],
        }, 17)),
    )

    result = json.loads(await nodes._execute_code_skill(
        {
            "org_id": str(org.id),
            "task_id": None,
            "template_agent_id": None,
            "workspace_id": str(workspace.id),
            "exec_mode": "craft",
            "referenced_file_ids": [],
        },
        {"folder": folder, "version": version},
        {},
    ))

    assert result["status"] == "success"
    assert result["summary"] == "created result"
    assert len(result["outputs"]) == 1
    output = result["outputs"][0]
    assert output["name"] == "result.txt"
    assert output["path"].startswith("技能输出/playground/")
    saved = await workspace_service.get_file(db_session, output["file_id"])
    assert saved is not None
    assert saved.parse_status == "ready"
    assert base64.b64decode(saved.content or "").decode() == "处理完成"


@pytest.mark.asyncio
async def test_platform_file_tools_are_available_without_skills_and_persist_outputs(
    db_session, monkeypatch,
):
    org, _, _, _, _, user, cu = await _hierarchy(db_session)
    workspace = Workspace(
        organization_id=org.id,
        name="Builtin tools workspace",
        slug=f"builtin-{uuid4().hex[:8]}",
        scope_type="user",
        scope_id=str(user.id),
        is_active=True,
    )
    db_session.add(workspace)
    await db_session.flush()

    tools, registry = await _build_tools(db_session, [], str(workspace.id), user=cu)
    names = {item["function"]["name"] for item in tools}
    assert {
        "spreadsheet_tool", "document_tool", "presentation_tool", "pdf_tool", "text_tool",
        "image_tool", "archive_tool", "web_tool",
    } <= names
    assert "generate_docx" not in names
    assert registry == {}

    runner = AsyncMock(return_value=({
        "summary": "created text file",
        "outputs": [{
            "name": "result.md",
            "mime_type": "text/markdown",
            "content_base64": base64.b64encode("# 完成".encode()).decode(),
        }],
    }, 12))
    monkeypatch.setattr(nodes.skill_runner_client, "execute_builtin", runner)
    monkeypatch.setattr(nodes, "get_deps", lambda: {"db": db_session, "user": cu})
    state = {
        "org_id": str(org.id),
        "workspace_id": str(workspace.id),
        "exec_mode": "craft",
        "task_id": None,
        "referenced_file_ids": [],
    }
    result = json.loads(await nodes._execute_builtin_tool(
        state,
        "text_tool",
        {"action": "create", "output_name": "result.md", "content": "# 完成"},
    ))
    assert result["status"] == "success"
    assert result["outputs"][0]["name"] == "result.md"
    assert result["outputs"][0]["path"].startswith("平台工具输出/playground/")
    runner.assert_awaited_once()
    assert runner.await_args.kwargs["tool_kind"] == "text"


def test_platform_tool_registry_keeps_legacy_docx_hidden():
    names = {item["function"]["name"] for item in nodes._builtin_tool_defs()}
    assert nodes.PLATFORM_TOOL_NAMES <= names
    assert "generate_docx" not in names
    assert "generate_docx" in nodes.LEGACY_BUILTIN_TOOL_NAMES


def test_enterprise_mutation_tools_require_an_explicit_expected_version():
    original = {
        "type": "object",
        "properties": {"id": {"type": "string"}},
        "required": ["id"],
    }
    parameters = nodes._enterprise_action_parameters(original, "delete")

    assert parameters["required"] == ["id", "expectedVersion"]
    assert parameters["properties"]["expectedVersion"]["anyOf"] == [
        {"type": "integer"}, {"type": "string"},
    ]
    assert original == {
        "type": "object",
        "properties": {"id": {"type": "string"}},
        "required": ["id"],
    }


def test_enterprise_action_idempotency_is_scoped_to_the_current_run():
    first = nodes._enterprise_action_request_id(
        {"task_id": "task-1", "run_id": 101}, "tool-call-1"
    )
    replay = nodes._enterprise_action_request_id(
        {"task_id": "task-1", "run_id": 101}, "tool-call-1"
    )
    next_turn = nodes._enterprise_action_request_id(
        {"task_id": "task-1", "run_id": 102}, "tool-call-1"
    )

    assert first == replay
    assert first != next_turn
    assert first == "task-1:101:tool-call-1"


@pytest.mark.asyncio
async def test_web_tool_is_available_and_executable_without_workspace(db_session, monkeypatch):
    _, _, _, _, _, _, cu = await _hierarchy(db_session)
    tools, registry = await _build_tools(db_session, [], None, user=cu)
    assert _AUTHENTICATED_BUILTIN_TOOLS <= {
        item["function"]["name"] for item in tools
    }
    assert registry == {}

    runner = AsyncMock(return_value=({
        "summary": {"query": "AI", "results": [{"title": "Result", "url": "https://example.com"}]},
        "outputs": [],
    }, 8))
    monkeypatch.setattr(nodes.skill_runner_client, "execute_builtin", runner)
    monkeypatch.setattr(nodes, "get_deps", lambda: {"db": db_session, "user": cu})
    result = json.loads(await nodes._execute_builtin_tool(
        {"exec_mode": "craft", "referenced_file_ids": [str(uuid4())]},
        "web_tool",
        {"action": "search", "query": "AI"},
    ))
    assert result["status"] == "success"
    assert result["summary"]["results"][0]["title"] == "Result"
    assert runner.await_args.kwargs["inputs"] == []


@pytest.mark.asyncio
async def test_business_application_turn_excludes_global_external_tools(db_session, monkeypatch):
    """应用助手只拿契约 Action；普通聊天仍可使用平台启用的外部扩展工具。"""
    _, _, _, _, _, _, cu = await _hierarchy(db_session)

    external_tool = {
        "type": "function",
        "function": {
            "name": "legacy_production_query",
            "description": "旧生产接口",
            "parameters": {"type": "object", "properties": {}},
        },
    }
    external_defs = AsyncMock(return_value=[external_tool])
    monkeypatch.setattr(platform_tool_registry, "active_external_tool_defs", external_defs)

    normal_tools, _ = await _build_tools(db_session, [], None, user=cu)
    assert "legacy_production_query" in {
        item["function"]["name"] for item in normal_tools
    }

    application_tools, _ = await _build_tools(
        db_session,
        [str(uuid4())],
        None,
        user=cu,
        application_id=str(uuid4()),
        page_context={"module_key": "progress_dashboard"},
    )
    application_tool_names = {
        item["function"]["name"] for item in application_tools
    }
    assert "legacy_production_query" not in application_tool_names
    assert application_tool_names.isdisjoint(_AUTHENTICATED_BUILTIN_TOOLS)
    external_defs.assert_awaited_once()


@pytest.mark.asyncio
async def test_manager_grant_is_revoked_when_membership_no_longer_matches(db_session):
    _, _, department, _, _, user, cu = await _hierarchy(db_session)
    await replace_manager_grants(db_session, user, [
        ManagerScopeGrant(scope_type="department", scope_id=department.id),
    ])
    assert ("department", str(department.id)) in await managed_scopes(db_session, cu)

    user.department_id = None
    await replace_manager_grants(db_session, user, [])
    await db_session.flush()
    cu.department_id = None
    assert ("department", str(department.id)) not in await managed_scopes(db_session, cu)


@pytest.mark.asyncio
async def test_general_agent_keeps_rag_fixed_and_prioritizes_explicit_skill_catalog(db_session):
    org, _, _, _, _, user, cu = await _hierarchy(db_session)

    async def import_prompt(name: str, description: str):
        content = f"""---
name: {name}
description: {description}
runtime: prompt
---

# {name}
Follow these instructions.
""".encode()
        return await skill_import_service.import_package(
            db_session, org_id=org.id, scope_type="user", scope_id=str(user.id),
            upload=UploadFile(filename="SKILL.md", file=io.BytesIO(content)),
            created_by=str(user.id),
        )

    default_folder, _ = await import_prompt("Default Finance", "Default finance workflow")
    explicit_folder, _ = await import_prompt("Explicit Cleaner", "Clean the selected workbook")
    rag = RagCollection(
        organization_id=org.id, name="Finance RAG", slug=f"finance-rag-{uuid4().hex[:8]}",
        scope_type="user", scope_id=str(user.id),
    )
    db_session.add(rag)
    await db_session.flush()
    agent = Agent(
        organization_id=org.id, scope_type="user", scope_id=str(user.id), created_by=str(user.id),
        name="Finance Agent", slug=f"finance-agent-{uuid4().hex[:8]}",
        system_prompt="You are a finance agent.", model_alias="default",
        skill_ids=[str(default_folder.id)], rag_collection_ids=[str(rag.id)], is_active=True,
    )
    db_session.add(agent)
    await db_session.flush()

    state = {
        "org_id": str(org.id), "task_id": None, "user_id": str(user.id),
        "session_id": f"sess-{uuid4()}", "request": "请用清洗技能处理文件",
        "exec_mode": "craft", "template_agent_id": str(agent.id),
        "model_alias": "default", "skill_ids": [], "ontology_ids": [],
        "invoked_skill_ids": [str(explicit_folder.id)],
        "invoked_skills": [{"id": str(explicit_folder.id)}],
        "referenced_file_ids": [],
    }
    configured = await nodes._load_config_general(state, {"user": cu}, db_session)

    assert configured["rag_collection_ids"] == [str(rag.id)]
    assert configured["skill_ids"][:2] == [str(explicit_folder.id), str(default_folder.id)]
    assert configured["skill_catalog"][0]["description"] == "Clean the selected workbook"
    assert configured["default_skills"][0]["id"] == str(default_folder.id)
    assert configured["referenced_skills"][0]["id"] == str(explicit_folder.id)
    assert configured["referenced_skills"][0]["activation"] == "explicit"

    general_state = {
        **state,
        "session_id": f"sess-{uuid4()}", "template_agent_id": None,
        "invoked_skill_ids": [], "invoked_skills": [],
    }
    general = await nodes._load_config_general(general_state, {"user": cu}, db_session)
    assert general["rag_collection_ids"] == []
    assert {row["id"] for row in general["skill_catalog"]} == {
        str(default_folder.id), str(explicit_folder.id),
    }
