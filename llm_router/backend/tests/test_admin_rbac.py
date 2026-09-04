"""Administrator two-role model and tenant-management invariants."""

from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.models.admin import Admin
from app.models.organization import Organization
from app.schemas.admin import AdminCreate, AdminUpdate
from app.services import admin_service


async def _organization(db_session, label: str) -> Organization:
    row = Organization(name=f"Organization {label}", slug=f"org-{label}-{uuid4().hex[:6]}")
    db_session.add(row)
    await db_session.flush()
    return row


async def _admin(
    db_session,
    username: str,
    role: str,
    organization_id=None,
    *,
    active: bool = True,
) -> Admin:
    row = Admin(
        username=username,
        password_hash="not-used",
        role=role,
        organization_id=organization_id,
        is_active=active,
    )
    db_session.add(row)
    await db_session.flush()
    return row


def test_admin_create_schema_allows_only_the_two_valid_role_shapes() -> None:
    org_id = uuid4()
    assert (
        AdminCreate(
            username="platform",
            password="password-123",
            role="platform_super_admin",
        ).organization_id
        is None
    )
    assert (
        AdminCreate(
            username="enterprise",
            password="password-123",
            role="enterprise_admin",
            organization_id=org_id,
        ).organization_id
        == org_id
    )

    with pytest.raises(ValueError):
        AdminCreate(username="legacy", password="password-123", role="super_admin")
    with pytest.raises(ValueError):
        AdminCreate(username="unbound", password="password-123", role="enterprise_admin")
    with pytest.raises(ValueError):
        AdminCreate(
            username="bound-platform",
            password="password-123",
            role="platform_super_admin",
            organization_id=org_id,
        )


@pytest.mark.asyncio
async def test_enterprise_admin_can_only_create_and_list_peers_in_its_organization(db_session) -> None:
    first_org = await _organization(db_session, "first")
    second_org = await _organization(db_session, "second")
    actor = await _admin(
        db_session,
        "first-owner",
        "enterprise_admin",
        first_org.id,
    )
    await _admin(db_session, "second-owner", "enterprise_admin", second_org.id)
    await _admin(db_session, "platform-owner", "platform_super_admin")

    peer = await admin_service.create_admin(
        db_session,
        AdminCreate(
            username="first-peer",
            password="password-123",
            role="enterprise_admin",
            organization_id=first_org.id,
        ),
        actor=actor,
    )
    visible = await admin_service.list_admins(db_session, actor=actor)
    assert {admin.id for admin in visible} == {actor.id, peer.id}

    with pytest.raises(HTTPException) as cross_org:
        await admin_service.create_admin(
            db_session,
            AdminCreate(
                username="forbidden-peer",
                password="password-123",
                role="enterprise_admin",
                organization_id=second_org.id,
            ),
            actor=actor,
        )
    assert cross_org.value.status_code == 403

    with pytest.raises(HTTPException) as platform_escalation:
        await admin_service.create_admin(
            db_session,
            AdminCreate(
                username="forbidden-platform",
                password="password-123",
                role="platform_super_admin",
            ),
            actor=actor,
        )
    assert platform_escalation.value.status_code == 403


@pytest.mark.asyncio
async def test_enterprise_binding_is_immutable_and_last_admin_cannot_be_disabled(db_session) -> None:
    org = await _organization(db_session, "immutable")
    other_org = await _organization(db_session, "other")
    actor = await _admin(db_session, "owner", "enterprise_admin", org.id)
    peer = await _admin(db_session, "peer", "enterprise_admin", org.id)
    platform = await _admin(db_session, "platform", "platform_super_admin")

    with pytest.raises(HTTPException) as self_disable:
        await admin_service.update_admin(
            db_session,
            actor,
            AdminUpdate(is_active=False),
            actor=actor,
        )
    assert self_disable.value.status_code == 409

    with pytest.raises(HTTPException) as move_org:
        await admin_service.update_admin(
            db_session,
            peer,
            AdminUpdate(organization_id=other_org.id),
            actor=actor,
        )
    assert move_org.value.status_code == 409

    with pytest.raises(HTTPException) as promote:
        await admin_service.update_admin(
            db_session,
            peer,
            AdminUpdate(role="platform_super_admin"),
            actor=platform,
        )
    assert promote.value.status_code == 409

    starting_epoch = peer.auth_epoch
    await admin_service.delete_admin(db_session, peer, actor=actor)
    assert peer.is_active is False
    assert peer.auth_epoch == starting_epoch + 1

    with pytest.raises(HTTPException) as last_admin:
        await admin_service.update_admin(
            db_session,
            actor,
            AdminUpdate(is_active=False),
            actor=platform,
        )
    assert last_admin.value.status_code == 409


@pytest.mark.asyncio
async def test_password_change_increments_auth_epoch(db_session, monkeypatch) -> None:
    admin = await _admin(db_session, "password-owner", "platform_super_admin")
    monkeypatch.setattr(admin_service, "_verify_password", lambda _plain, _hashed: True)
    monkeypatch.setattr(admin_service, "_hash_password", lambda value: f"hashed:{value}")

    changed = await admin_service.change_password(db_session, admin, "old", "new-password")

    assert changed is True
    assert admin.password_hash == "hashed:new-password"
    assert admin.auth_epoch == 1
