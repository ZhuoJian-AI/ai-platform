from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.services import voice_recording_service as recordings


def fake_db(job):
    return SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(
        scalar_one_or_none=lambda: job, scalars=lambda: [job],
    )), flush=AsyncMock())


def fake_job(**overrides):
    return SimpleNamespace(status="queued", available_at=datetime.now(UTC) + timedelta(minutes=5),
                           params={"purpose": recordings.PURPOSE, "input_ref": "oss://test/recording",
                                   "size_bytes": 12, **overrides})


@pytest.mark.asyncio
async def test_cancel_remains_available_after_permission_revocation():
    job = fake_job()
    user = SimpleNamespace(id=str(uuid4()), organization_id=uuid4(), permission_codes=[])
    await recordings.cancel(fake_db(job), user, uuid4())
    assert job.status == "cancelled"
    assert job.result == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("size,expected", [(12, True), (11, False)])
async def test_finalize_checks_uploaded_size(monkeypatch, size, expected):
    job = fake_job()
    user = SimpleNamespace(id=str(uuid4()), organization_id=uuid4(), permission_codes=["multimodal.audio.transcribe"])
    monkeypatch.setattr(recordings.audio, "require_multimodal_enabled", AsyncMock())
    monkeypatch.setattr(recordings.storage, "inspect_object", AsyncMock(return_value={"size": size}))
    if expected:
        await recordings.finalize(fake_db(job), user, uuid4())
        assert job.params["upload_ready"] is True
    else:
        with pytest.raises(HTTPException) as error:
            await recordings.finalize(fake_db(job), user, uuid4())
        assert error.value.status_code == 422
        assert not job.params.get("upload_ready")


@pytest.mark.asyncio
@pytest.mark.parametrize("expired", [False, True])
async def test_cleanup_waits_for_upload_expiry(monkeypatch, expired):
    deadline = datetime.now(UTC) + timedelta(minutes=-1 if expired else 1)
    job = fake_job(cleanup_after=deadline.isoformat())
    delete = AsyncMock()
    monkeypatch.setattr(recordings.storage, "delete_object", delete)
    await recordings.cleanup(fake_db(job))
    assert delete.await_count == int(expired)
    assert ("input_ref" not in job.params) == expired


@pytest.mark.asyncio
async def test_non_recording_job_cannot_be_cancelled():
    job = fake_job(purpose="business_operation")
    user = SimpleNamespace(id=str(uuid4()), organization_id=uuid4())
    with pytest.raises(HTTPException) as error:
        await recordings.cancel(fake_db(job), user, uuid4())
    assert error.value.status_code == 404
    assert job.status == "queued"
