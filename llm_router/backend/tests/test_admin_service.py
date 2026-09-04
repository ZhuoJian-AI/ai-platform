"""Administrator bootstrap invariants."""

import pytest

from app.models.admin import Admin
from app.services.admin_service import ensure_super_admin


@pytest.mark.asyncio
async def test_ensure_super_admin_tolerates_multiple_active_admins(db_session):
    first = Admin(username="root-a", password_hash="x", role="platform_super_admin", is_active=True)
    second = Admin(username="root-b", password_hash="x", role="platform_super_admin", is_active=True)
    db_session.add_all([first, second])
    await db_session.flush()

    selected = await ensure_super_admin(db_session)

    assert selected.id == first.id

