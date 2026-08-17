"""Focused coverage for scoped Skill authorization, versions, and Agent exposure."""

from __future__ import annotations

import io
from uuid import uuid4

import pytest
from fastapi import HTTPException, UploadFile

from app.agents.graph.nodes import _build_tools
from app.auth.user_auth import CurrentUser
from app.models.department import Department
from app.models.organization import Organization
from app.models.rag import RagCollection
from app.models.skill import SkillFolder
from app.models.team import Team
from app.models.user import User
from app.schemas.user import ManagerScopeGrant
from app.services import skill_import_service
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
