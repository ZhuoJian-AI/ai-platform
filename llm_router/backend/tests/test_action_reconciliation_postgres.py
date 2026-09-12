"""Opt-in real PostgreSQL verification in a disposable candidate-only schema."""
import asyncio
import os
import unittest
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.audit_log import AuditLog
from app.models.base import Base
from app.models.enterprise_application import (
    EnterpriseApplication,
    EnterpriseApplicationAction,
    EnterpriseApplicationActionRequest,
)
from app.models.organization import Organization
from app.models.user import User
from app.services import action_reconciliation_service as service
from app.services import subsystem_action_service as actions
from app.utils.crypto import encrypt_provider_api_key


@unittest.skipUnless(os.environ.get("RECOVERY_TEST_DATABASE_URL"), "candidate database not configured")
class ReconciliationPostgresTest(unittest.IsolatedAsyncioTestCase):
    async def test_concurrent_resolution_audit_and_duplicate_barriers(self):
        url = os.environ["RECOVERY_TEST_DATABASE_URL"]
        parsed = make_url(url)
        self.assertEqual((parsed.host, parsed.port, parsed.database, parsed.username),
                         ("127.0.0.1", 5459, "ai_infra_candidate", "e2e"))
        schema = "reconciliation_e2e_" + uuid4().hex
        admin = create_async_engine(url)
        async with admin.begin() as conn:
            await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        engine = create_async_engine(url, connect_args={"server_settings": {"search_path": schema}})
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            org, user, app_id, action_id = [uuid4() for _ in range(4)]
            now = datetime.now(UTC)
            async with sessions() as db:
                db.add(Organization(id=org, name="E2E-recovery", slug=schema))
                await db.flush()
                db.add(User(id=user, organization_id=org, username="E2E-recovery"))
                app = EnterpriseApplication(id=app_id, organization_id=org, name="E2E-recovery",
                                            slug=schema, entry_url="https://example.invalid")
                db.add(app)
                await db.flush()
                action = EnterpriseApplicationAction(id=action_id, application_id=app_id, organization_id=org,
                    module_key="orders", action_key="update", name="修改负责人", operation="update")
                db.add(action)
                await db.flush()
                records = []
                for index, state in enumerate(["failed", "failed", "executing", "completed"]):
                    row = EnterpriseApplicationActionRequest(
                        application_id=app_id, organization_id=org, action_id=action_id, user_id=user,
                        request_id=f"E2E-{index}", module_key="orders", status=state,
                        expires_at=now + timedelta(minutes=5),
                        result={"executionOutcome": "unknown"} if state != "completed" else {},
                        params_encrypted=encrypt_provider_api_key(actions._request_payload({"id": index}, "main", 3)),
                    )
                    db.add(row)
                    records.append(row)
                await db.commit()
                ids = [row.id for row in records]
            auth = SimpleNamespace(role="enterprise_admin", organization_id=org, id=7)
            application = SimpleNamespace(id=app_id, organization_id=org)

            async def resolve(record_id, decision, evidence="E2E receipt verified"):
                async with sessions() as db:
                    result = await service.reconcile(db, application, auth, record_id,
                                                     decision=decision, evidence=evidence)
                    await db.commit()
                    return result

            # Separate transactions racing on the same row must append one audit only.
            results = await asyncio.gather(resolve(ids[0], "executed"), resolve(ids[0], "executed"))
            self.assertEqual([result["status"] for result in results], ["completed", "completed"])
            with self.assertRaises(HTTPException) as error:
                await resolve(ids[0], "not_executed")
            self.assertEqual(error.exception.status_code, 409)
            await resolve(ids[1], "not_executed")
            with self.assertRaises(HTTPException):
                await resolve(ids[2], "executed")
            async with sessions() as db:
                self.assertEqual(await db.scalar(select(func.count()).select_from(AuditLog)), 2)
                rows = await service.list_requests(db, application, auth)
                self.assertEqual({row["id"] for row in rows}, {str(value) for value in ids[:3]})
                cu = SimpleNamespace(id=str(user))
                original = await actions._unresolved_identical_write(db, application, action, cu, {"id": 0}, "main", 3)
                self.assertEqual(original.id, ids[0])
                self.assertIsNone(await actions._unresolved_identical_write(
                    db, application, action, cu, {"id": 1}, "main", 3))
                retry = await actions._unresolved_identical_write(
                    db, application, action, cu, {"id": 1}, "main", 3, retry_confirmation=True)
                self.assertEqual(retry.id, ids[1])
        finally:
            await engine.dispose()
            async with admin.begin() as conn:
                await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            await admin.dispose()
