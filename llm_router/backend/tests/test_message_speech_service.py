from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.services import message_speech_service as speech


def test_request_cannot_supply_text_model_or_address():
    for field in ("text", "model", "url", "voice_profile_id"):
        with pytest.raises(ValidationError):
            speech.MessageSpeechCreate(task_id=uuid4(), message_id=uuid4(), **{field: "injected"})


def test_speech_is_only_bounded_final_prose():
    text = "<think>secret</think>已经完成。\n|名称|金额|\n```json\nsecret\n```\n[查看](https://example.com)"
    assert speech.spoken_text(text) == "已经完成。 查看"
    assert "更多内容" in speech.spoken_text("结果正确。" * 200)
    with pytest.raises(HTTPException):
        speech.spoken_text("<analysis>unclosed private reasoning")


def fixture():
    cu = SimpleNamespace(id=str(uuid4()), organization_id=uuid4(), permission_codes=["multimodal.speech.use"])
    voice = SimpleNamespace(id=uuid4(), updated_at=datetime.now(UTC),
                            provider_voice_id="standard", voice_type="builtin")
    job = SimpleNamespace(user_id=cu.id, organization_id=cu.organization_id, voice_profile_id=voice.id,
                          params={"task_id": str(uuid4()), "message_id": str(uuid4()),
                                  "content_version": speech.content_version("回答"),
                                  "voice_version": speech.voice_version(voice),
                                  "cleanup_after": (datetime.now(UTC) + timedelta(hours=1)).isoformat()})
    return cu, voice, job


@pytest.mark.asyncio
@pytest.mark.parametrize("change,status", [
    ("owner", 404), ("role", 403), ("content", 409), ("voice", 409), ("expiry", 410), ("none", 0),
])
async def test_read_authorization_is_live(monkeypatch, change, status):
    cu, voice, job = fixture()
    db = SimpleNamespace(refresh=AsyncMock())
    content = "回答"
    if change == "owner":
        cu.id = str(uuid4())
    elif change == "role":
        cu.permission_codes = []
    elif change == "content":
        content = "新回答"
    elif change == "voice":
        voice.provider_voice_id = "new-standard"
    elif change == "expiry":
        job.params["cleanup_after"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    monkeypatch.setattr(speech.audio, "require_multimodal_enabled", AsyncMock())
    monkeypatch.setattr(speech, "owned_message", AsyncMock(return_value=SimpleNamespace(content=content)))
    monkeypatch.setattr(speech.audio, "get_visible_voice", AsyncMock(return_value=voice))
    if status:
        with pytest.raises(HTTPException) as exc:
            await speech.authorize(db, cu, job)
        assert exc.value.status_code == status
    else:
        await speech.authorize(db, cu, job)


@pytest.mark.asyncio
async def test_cleanup_deletes_only_expired_audio(monkeypatch):
    _, _, job = fixture()
    job.output_file_ref = "oss://test/read-aloud"
    job.result = {"output_file_ref": job.output_file_ref, "format": "mp3"}
    db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(scalars=lambda: [job])), flush=AsyncMock())
    delete = AsyncMock()
    monkeypatch.setattr(speech.storage, "delete_object", delete)
    await speech.cleanup(db)
    delete.assert_not_awaited()
    job.params["cleanup_after"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    await speech.cleanup(db)
    delete.assert_awaited_once_with("oss://test/read-aloud")
    assert job.output_file_ref is None
    assert job.result == {"format": "mp3"}
