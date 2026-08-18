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
from app.models.department import Department
from app.models.organization import Organization
from app.models.rag import RagCollection
from app.models.skill import SkillFolder, SkillVersion
from app.models.team import Team
from app.models.user import User
from app.models.workspace import Workspace
from app.schemas.user import ManagerScopeGrant
from app.services import skill_import_service, workspace_service
from app.services.scope_service import assert_bound_rags_visible
from app.services.skill_scope_service import (
    assert_bound_skills_visible,
    assert_user_can_manage_scope,
    managed_scopes,
    replace_manager_grants,
    validate_scope_target,
)


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
    assert folder.active_version_id == version2.id
    assert version1.archive != version2.archive

    assert await assert_bound_skills_visible(db_session, cu, [str(folder.id)]) == [folder]
    empty_tools, empty_registry = await _build_tools(db_session, [], None, user=cu)
    assert empty_tools == []
    assert empty_registry == {}
    tools, registry = await _build_tools(db_session, [str(folder.id)], None, user=cu)
    assert [tool["function"]["name"] for tool in tools] == ["load_bank-process"]
    assert set(registry) == {"load_bank-process"}

    folder.is_active = False
    await db_session.flush()
    with pytest.raises(HTTPException) as exc:
        await assert_bound_skills_visible(db_session, cu, [str(folder.id)])
    assert exc.value.status_code == 422
    disabled_tools, _ = await _build_tools(db_session, [str(folder.id)], None, user=cu)
    assert disabled_tools == []


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
    assert [item["function"]["name"] for item in tools] == [
        "load_skill", "read_skill_resource", "run_skill_script",
    ]
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
