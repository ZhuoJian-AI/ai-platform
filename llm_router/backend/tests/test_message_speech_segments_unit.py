"""No database or provider calls: segment request and trusted text selection."""
import unittest
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from fastapi import HTTPException
from pydantic import ValidationError

from app.services import message_speech_service as speech


class SpeechBindingTest(unittest.IsolatedAsyncioTestCase):
    def test_segment_requires_exact_content_version(self):
        fields = dict(task_id=uuid4(), message_id=uuid4())
        for extra in ({"segment_index": 0}, {"expected_content_version": "a" * 64},
                      {"segment_index": -1, "expected_content_version": "a" * 64},
                      {"text": "arbitrary provider input"}):
            with self.assertRaises(ValidationError):
                speech.MessageSpeechCreate(**fields, **extra)
        speech.MessageSpeechCreate(**fields, segment_index=0, expected_content_version="a" * 64)

    async def test_stale_version_or_index_does_not_create_job(self):
        content = "第一句。第二句。"
        cu = SimpleNamespace(id=str(uuid4()), organization_id=uuid4(), permission_codes=["multimodal.speech.use"])
        db = SimpleNamespace(execute=AsyncMock())
        with patch.object(speech.audio, "require_multimodal_enabled", AsyncMock()), \
             patch.object(speech, "owned_message", AsyncMock(return_value=SimpleNamespace(content=content))), \
             patch.object(speech.audio, "_create_job", AsyncMock()) as create:
            for version, index, status in (("0" * 64, 0, 409), (speech.content_version(content), 5, 422)):
                request = speech.MessageSpeechCreate(task_id=uuid4(), message_id=uuid4(),
                    segment_index=index, expected_content_version=version)
                with self.assertRaises(HTTPException) as error:
                    await speech.create(db, cu, request)
                self.assertEqual(error.exception.status_code, status)
            create.assert_not_awaited()

    def test_segment_source_excludes_private_and_rich_payloads(self):
        text = "<think>secret</think>公开回答。\n```json\nsecret\n```\n|秘密|字段|\n下一句。"
        result = speech.message_segments(text)
        self.assertEqual([s.text for s in result], ["公开回答。", "下一句。"])

    async def test_segments_have_distinct_cache_and_server_selected_text(self):
        content = "第一句。第二句。"
        cu = SimpleNamespace(id=str(uuid4()), organization_id=uuid4(), department_id=None,
                             permission_codes=["multimodal.speech.use"])
        voice = SimpleNamespace(id=uuid4(), updated_at=datetime.now(UTC),
                                provider_voice_id="standard", voice_type="builtin")
        db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: None)))
        with patch.object(speech.audio, "require_multimodal_enabled", AsyncMock()), \
             patch.object(speech, "owned_message", AsyncMock(return_value=SimpleNamespace(content=content))), \
             patch.object(speech.audio, "list_visible_voices", AsyncMock(return_value=[voice])), \
             patch.object(speech.audio.model_gateway, "resolve_deployment", AsyncMock(return_value=object())), \
             patch.object(speech.audio, "_create_job", AsyncMock()) as create:
            task_id, message_id = uuid4(), uuid4()
            for index in range(2):
                await speech.create(db, cu, speech.MessageSpeechCreate(task_id=task_id, message_id=message_id,
                    segment_index=index, expected_content_version=speech.content_version(content)))
            params = [call.kwargs["params"] for call in create.await_args_list]
            self.assertEqual([p["text"] for p in params], ["第一句。", "第二句。"])
            self.assertNotEqual(params[0]["cache_key"], params[1]["cache_key"])
            self.assertTrue(all(p["purpose"] == speech.PURPOSE for p in params))


if __name__ == "__main__":
    unittest.main()
