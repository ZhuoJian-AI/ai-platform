import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from fastapi import HTTPException
from pydantic import ValidationError

from app.agents.core.speech_progress import SpeechProgress
from app.services import run_speech_service as speech


class RunSpeechTest(unittest.IsolatedAsyncioTestCase):
    def test_sentence_ready_before_full_answer_and_no_repeat(self):
        progress = SpeechProgress()
        self.assertEqual(progress.update("第一句", ready=True), [])
        first = progress.update("第一句。第二句", ready=True)
        self.assertEqual(first[0]["text"], "第一句。")
        self.assertEqual(progress.update("第一句。第二句", ready=True), [])
        last = progress.update("第一句。第二句", ready=True, final=True)
        self.assertEqual(last[0]["segmentIndex"], 1)

    def test_unverified_and_markup_are_not_spoken_early(self):
        progress = SpeechProgress()
        self.assertEqual(progress.update("已修改订单。", ready=False), [])
        self.assertEqual(progress.update("<think>secret。", ready=True), [])
        events = progress.update("<think>secret。</think>公开答复。", ready=True, final=True)
        self.assertEqual(events[0]["text"], "公开答复。")

    def test_reset_invalidates_old_segments_and_indices_do_not_reuse(self):
        progress = SpeechProgress()
        first = progress.update("初始正文。", ready=True)
        second = progress.update("纠正正文。", ready=True, final=True)
        self.assertEqual(second[0]["type"], "speech_reset")
        self.assertEqual(list(speech.select_segments(first + second)), [1])

    async def test_foreign_run_fails_before_reading_live_registry(self):
        db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: None)))
        cu = SimpleNamespace(id=str(uuid4()), organization_id=uuid4())
        with patch.object(speech.run_registry, "get") as registry:
            with self.assertRaises(HTTPException) as error:
                await speech.owned_events(db, cu, uuid4(), 1)
            self.assertEqual(error.exception.status_code, 404)
            registry.assert_not_called()

    async def test_cancelled_run_cannot_replay_old_audio(self):
        db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(
            scalar_one_or_none=lambda: SimpleNamespace(status="cancelled"))))
        cu = SimpleNamespace(id=str(uuid4()), organization_id=uuid4())
        self.assertEqual(await speech.owned_events(db, cu, uuid4(), 1), ([], True))

    def test_browser_cannot_submit_text_or_provider(self):
        fields = dict(task_id=uuid4(), run_id=1, segment_index=0, expected_content_version="a" * 64)
        for extra in ({"text": "invented"}, {"model": "arbitrary"}, {"run_id": 0}):
            with self.assertRaises(ValidationError):
                speech.RunSpeechCreate(**{**fields, **extra})

    async def test_worker_without_live_handle_uses_durable_segments(self):
        event = {"type": "speech_segment", "segmentIndex": 0, "text": "已核验正文。"}
        db = SimpleNamespace(execute=AsyncMock(side_effect=[
            SimpleNamespace(scalar_one_or_none=lambda: SimpleNamespace(status="running")),
            SimpleNamespace(scalars=lambda: [event]),
        ]))
        cu = SimpleNamespace(id=str(uuid4()), organization_id=uuid4())
        with patch.object(speech.run_registry, "get", return_value=None):
            result = await speech.owned_segment(db, cu, uuid4(), 1, 0)
        self.assertEqual(result["text"], "已核验正文。")

    def test_long_response_does_not_restart_or_read_everything(self):
        progress = SpeechProgress()
        text = ("这是一个已验证的结果。" * 100)
        events = progress.update(text, ready=True)
        self.assertEqual(events[-1]["text"], "后续详细内容请查看文字回复。")
        self.assertEqual(progress.update(text, ready=True, final=True), [])


if __name__ == "__main__":
    unittest.main()
