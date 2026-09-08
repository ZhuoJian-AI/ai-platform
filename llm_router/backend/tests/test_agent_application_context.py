from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.agent import AgentCreate, AgentUpdate
from app.services.agent_service import merged_application_context


@pytest.fixture(autouse=True)
def db_engine():
    """Schema and merge unit tests do not require PostgreSQL."""
    yield


def _create_payload(**overrides):
    payload = {
        "name": "生产查询助手",
        "system_prompt": "仅使用当前员工获准的业务页面。",
    }
    payload.update(overrides)
    return payload


def test_agent_create_requires_a_complete_manifest_page_context():
    with pytest.raises(ValidationError, match="必须同时提供"):
        AgentCreate(**_create_payload(application_id=uuid4()))


def test_agent_create_accepts_a_complete_manifest_page_context():
    application_id = uuid4()

    result = AgentCreate(
        **_create_payload(
            application_id=application_id,
            module_key="production",
            page_key="progress_dashboard",
        )
    )

    assert result.application_id == application_id
    assert result.module_key == "production"
    assert result.page_key == "progress_dashboard"


def test_agent_partial_update_is_merged_before_context_validation():
    application_id = uuid4()
    agent = SimpleNamespace(
        application_id=str(application_id),
        module_key="production",
        page_key="progress_dashboard",
    )

    result = merged_application_context(agent, AgentUpdate(page_key="factory_progress"))

    assert result == (str(application_id), "production", "factory_progress")
