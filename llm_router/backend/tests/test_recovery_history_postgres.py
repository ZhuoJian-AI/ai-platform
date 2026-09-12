"""Opt-in isolated PostgreSQL proof; never connects to staging's database."""
import json
import os
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.base import Base
from app.models.enterprise_application import (
    EnterpriseApplication,
    EnterpriseApplicationAction,
    EnterpriseApplicationActionRequest,
)
from app.models.organization import Organization
from app.models.task import Task, TaskMessage
from app.models.user import User
from app.services import assistant_action_recovery as recovery
from app.services import subsystem_action_service as actions


@pytest.mark.asyncio
@pytest.mark.skipif(not os.getenv("VOICE_TEST_DATABASE_URL"), reason="isolated PostgreSQL not configured")
async def test_durable_same_task_history_survives_context_window_and_rejects_other_owner(monkeypatch):
    url = os.environ["VOICE_TEST_DATABASE_URL"]
    parsed = make_url(url)
    assert (parsed.host, parsed.port, parsed.username, parsed.database) == (
        "127.0.0.1", 5459, "voice_e2e", "voice_e2e",
    )
    schema = "recovery_e2e_" + uuid4().hex
    admin = create_async_engine(url)
    async with admin.begin() as conn:
        await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_async_engine(url, connect_args={"server_settings": {"search_path": schema}})
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        org_id, user_id, task_id, other_task = uuid4(), uuid4(), uuid4(), uuid4()
        monkeypatch.setattr(recovery, "decrypt_provider_api_key", lambda value: value)
        async with sessions() as db:
            db.add(Organization(id=org_id, name="E2E-recovery", slug=schema))
            await db.flush()
            db.add(User(id=user_id, organization_id=org_id, username="E2E-recovery"))
            app = EnterpriseApplication(organization_id=org_id, name="E2E-app", slug="test",
                                        entry_url="https://example.invalid")
            db.add(app)
            await db.flush()
            action = EnterpriseApplicationAction(application_id=app.id, organization_id=org_id,
                module_key="orders", action_key="change", name="修改负责人", operation="update")
            db.add(action)
            db.add_all([Task(id=value, organization_id=org_id, user_id=user_id, session_id=str(value))
                        for value in (task_id, other_task)])
            await db.flush()
            db.add(EnterpriseApplicationActionRequest(application_id=app.id, organization_id=org_id,
                action_id=action.id, user_id=user_id, request_id="old-success", module_key="orders",
                status="completed", expires_at=datetime.now(UTC) - timedelta(days=1),
                params_encrypted=json.dumps({"_bindingOnly": 1, "params": {},
                    "paramsDigest": actions._params_hash({"id": 1}), "pageKey": "main", "expectedVersion": 3})))
            db.add(TaskMessage(task_id=task_id, role="assistant", content="业务成功，文件失败",
                               metadata_={"tool_executions": [{"requestId": "old-success"}]}))
            await db.commit()
            cu = SimpleNamespace(id=str(user_id), organization_id=org_id)
            assert await recovery.pending_request_id(db, app, action, cu, [], {"id": 1}, "main", 3,
                                                      task_id=task_id) == "old-success"
            assert await recovery.pending_request_id(db, app, action, cu, [], {"id": 1}, "main", 3,
                                                      task_id=other_task) is None
            assert await recovery.pending_request_id(db, app, action, cu, [], {"id": 2}, "main", 3,
                                                      task_id=task_id) is None
            cu.id = str(uuid4())
            assert await recovery.pending_request_id(db, app, action, cu, [], {"id": 1}, "main", 3,
                                                      task_id=task_id) is None
    finally:
        await engine.dispose()
        async with admin.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await admin.dispose()
