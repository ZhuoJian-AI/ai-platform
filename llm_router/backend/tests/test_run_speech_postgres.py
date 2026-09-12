"""Opt-in, isolated PostgreSQL test. Run with --noconftest; never staging."""
import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.agents import runtime_support
from app.models.agent_run import AgentRun, AgentRunEvent
from app.models.base import Base
from app.models.organization import Organization
from app.models.task import Task
from app.models.user import User
from app.services import run_speech_service as speech


@unittest.skipUnless(os.environ.get("VOICE_TEST_DATABASE_URL"), "isolated PostgreSQL not configured")
class RunSpeechPostgresTest(unittest.IsolatedAsyncioTestCase):
    async def test_durable_worker_read_reset_and_final_are_idempotent(self):
        url = os.environ["VOICE_TEST_DATABASE_URL"]
        parsed = make_url(url)
        if parsed.host != "127.0.0.1" or parsed.port != 5459 or parsed.username != "voice_e2e":
            self.fail("Only the dedicated local voice_e2e instance on port 5459 is allowed")
        schema = "voice_e2e_" + uuid4().hex
        admin = create_async_engine(url)
        async with admin.begin() as conn:
            await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        engine = create_async_engine(url, connect_args={"server_settings": {"search_path": schema}})
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            org, user, task = uuid4(), uuid4(), uuid4()
            async with sessions() as db:
                db.add(Organization(id=org, name="E2E-voice", slug=schema))
                await db.flush()
                db.add(User(id=user, organization_id=org, username="E2E-voice"))
                await db.flush()
                db.add(Task(id=task, organization_id=org, user_id=user, session_id=schema))
                await db.flush()
                run = AgentRun(organization_id=org, user_id=user, task_id=task, session_id=schema)
                db.add(run)
                await db.commit()
                run_id = run.id
            cu = SimpleNamespace(id=str(user), organization_id=org)
            events = [{"type": "speech_segment", "segmentIndex": 0, "text": "第一句。"}]
            with patch.object(runtime_support, "async_session_factory", sessions), \
                    patch.object(speech.run_registry, "get", return_value=None):
                self.assertTrue(await runtime_support.persist_run_events(run_id, str(task), events, None))
                async with sessions() as worker:
                    segment = await speech.owned_segment(worker, cu, task, run_id, 0)
                    self.assertEqual(segment["text"], "第一句。")
                events.extend([{"type": "speech_reset"},
                               {"type": "speech_segment", "segmentIndex": 1, "text": "纠正后的正文。"}])
                final = json.dumps({"type": "final", "run_id": run_id})
                for _ in range(2):
                    self.assertTrue(await runtime_support.persist_run_events(run_id, str(task), events, final))
                async with sessions() as worker:
                    with self.assertRaises(HTTPException) as error:
                        await speech.owned_segment(worker, cu, task, run_id, 0)
                    self.assertEqual(error.exception.status_code, 409)
                    self.assertEqual((await speech.owned_segment(worker, cu, task, run_id, 1))["text"],
                                     "纠正后的正文。")
                    rows = (await worker.execute(select(AgentRunEvent).order_by(AgentRunEvent.seq))).scalars().all()
                    self.assertEqual([row.seq for row in rows], [1, 2, 3, 4])
                    self.assertEqual(rows[-1].payload["type"], "final")
        finally:
            await engine.dispose()
            async with admin.begin() as conn:
                await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            await admin.dispose()
