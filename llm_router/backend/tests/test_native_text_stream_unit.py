"""Public-text latency and cancellation without provider or database calls."""
import asyncio
import unittest
from unittest.mock import patch
from uuid import uuid4

from app.agents.core import native


class NativeTextStreamTest(unittest.IsolatedAsyncioTestCase):
    async def test_public_text_arrives_before_provider_finishes(self):
        release = asyncio.Event()

        async def source(*args, **kwargs):
            yield "reasoning_content", "private reasoning", None
            yield "text", "第一句。", None
            await release.wait()
            yield "text", "第二句。", None
            yield "usage", None, {"input_tokens": 2, "output_tokens": 3}

        with patch.object(native.model_gateway, "stream_chat", source):
            stream = native._stream_model_turn(state={"org_id": str(uuid4())}, prepared={},
                                               deps={"db": None}, messages=[], tools=[])
            try:
                self.assertEqual(await asyncio.wait_for(anext(stream), 1), ("text", "第一句。"))
                self.assertFalse(release.is_set())
                release.set()
                self.assertEqual(await anext(stream), ("text", "第二句。"))
                kind, result = await anext(stream)
                self.assertEqual(kind, "result")
                self.assertEqual(result[0], "第一句。第二句。")
                self.assertEqual(result[3], "private reasoning")  # remains internal protocol context
            finally:
                await stream.aclose()

    async def test_closing_stream_closes_provider(self):
        closed = asyncio.Event()

        async def source(*args, **kwargs):
            try:
                yield "text", "第一句。", None
                await asyncio.Event().wait()
            finally:
                closed.set()

        with patch.object(native.model_gateway, "stream_chat", source):
            stream = native._stream_model_turn(state={"org_id": str(uuid4())}, prepared={},
                                               deps={"db": None}, messages=[], tools=[])
            await anext(stream)
            await asyncio.wait_for(stream.aclose(), 1)
            self.assertTrue(closed.is_set())

    async def test_provider_failure_is_propagated_not_retried(self):
        calls = []

        async def source(*args, **kwargs):
            calls.append(1)
            yield "text", "部分正文", None
            raise RuntimeError("provider connection lost")

        with patch.object(native.model_gateway, "stream_chat", source):
            stream = native._stream_model_turn(state={"org_id": str(uuid4())}, prepared={},
                                               deps={"db": None}, messages=[], tools=[])
            await anext(stream)
            with self.assertRaisesRegex(RuntimeError, "connection lost"):
                await anext(stream)
            self.assertEqual(calls, [1])


if __name__ == "__main__":
    unittest.main()
