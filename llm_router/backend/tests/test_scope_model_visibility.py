"""Model picker visibility must match the model gateway routing contract."""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services import scope_service


@pytest.fixture(autouse=True)
def db_engine():
    """These scope tests use a tiny fake session and do not need PostgreSQL."""
    yield


class _FakeDb:
    def __init__(self, organization):
        self.organization = organization

    async def get(self, _model, _identifier):
        return self.organization


@pytest.mark.asyncio
async def test_explicit_deployments_never_fall_back_to_unverified_legacy_names(monkeypatch):
    organization_id = uuid4()
    organization = SimpleNamespace(id=organization_id, slug="alphabet")
    current_user = SimpleNamespace(
        organization_id=organization_id, department_id=None, team_id=None,
    )
    deployment = SimpleNamespace(
        model_id="mimo-v2.5", capabilities=["chat"], is_active=True,
        deleted_at=None, verification_status="unverified",
    )
    provider = SimpleNamespace(
        model_deployments=[deployment], supported_models=["mimo-v2.5"], config={},
    )

    async def keys(*_args, **_kwargs):
        return [SimpleNamespace(allowed_models=[])]

    async def visible_providers(*_args, **_kwargs):
        return [provider]

    monkeypatch.setattr(scope_service, "list_api_keys_for_user", keys)
    monkeypatch.setattr(scope_service.multimodal_service, "visible_providers", visible_providers)
    monkeypatch.setattr(
        type(scope_service.settings), "model_gateway_enabled_for",
        lambda _self, _slug, *, organization_id=None: True,
    )

    db = _FakeDb(organization)
    assert await scope_service.list_available_models_for_user(db, current_user) == []

    deployment.verification_status = "verified"
    assert await scope_service.list_available_models_for_user(db, current_user) == ["mimo-v2.5"]

    deployment.is_active = False
    assert await scope_service.list_available_models_for_user(db, current_user) == []

    provider.model_deployments = []
    assert await scope_service.list_available_models_for_user(db, current_user) == ["mimo-v2.5"]
