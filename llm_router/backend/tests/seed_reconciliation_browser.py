"""Candidate-only E2E fixture. No remote business command is sent."""
import asyncio
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import delete
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.audit_log import AuditLog
from app.models.enterprise_application import (
    EnterpriseApplication,
    EnterpriseApplicationAction,
    EnterpriseApplicationActionRequest,
)
from app.models.organization import Organization
from app.models.user import User
from app.services.subsystem_action_service import _request_payload
from app.utils.crypto import encrypt_provider_api_key


async def main():
    url = os.environ["DATABASE_URL"]
    parsed = make_url(url)
    assert (parsed.host, parsed.port, parsed.database) == ("127.0.0.1", 5459, "ai_infra_voice_current_3ee1e57")
    engine = create_async_engine(url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as db:
            if len(sys.argv) > 1:
                org_id = UUID(sys.argv[1])
                org = await db.get(Organization, org_id)
                assert org and org.slug == "e2e-reconcile-" + org_id.hex
                await db.execute(delete(EnterpriseApplication).where(EnterpriseApplication.organization_id == org_id))
                await db.execute(delete(AuditLog).where(AuditLog.organization_id == str(org_id)))
                await db.execute(delete(User).where(User.organization_id == org_id))
                await db.delete(org)
                await db.commit()
                print("E2E candidate records cleaned")
                return
            org_id, app_id, user_id = uuid4(), uuid4(), uuid4()
            db.add(Organization(id=org_id, name="E2E-核实测试", slug="e2e-reconcile-" + org_id.hex))
            await db.flush()
            db.add(User(id=user_id, organization_id=org_id, username="E2E-reconcile"))
            db.add(EnterpriseApplication(id=app_id, organization_id=org_id, name="E2E-核实测试",
                                        slug="e2e-reconcile", entry_url="https://example.invalid"))
            await db.flush()
            action = EnterpriseApplicationAction(application_id=app_id, organization_id=org_id, module_key="orders",
                action_key="update", name="E2E-修改负责人", operation="update", requires_confirmation=True)
            db.add(action)
            await db.flush()
            for index in range(2):
                db.add(EnterpriseApplicationActionRequest(application_id=app_id, organization_id=org_id,
                    action_id=action.id, user_id=user_id, request_id=f"E2E-reconcile-{index}", module_key="orders",
                    status="failed" if index == 0 else "executing", result={"executionOutcome": "unknown"},
                    expires_at=datetime.now(UTC) + timedelta(minutes=5),
                    params_encrypted=encrypt_provider_api_key(_request_payload({"id": index}, "main", 1))))
            await db.commit()
            print(json.dumps({"org_id": str(org_id), "app_id": str(app_id)}))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
