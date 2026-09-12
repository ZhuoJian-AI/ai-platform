"""Pure framing tests: runnable with unittest, no database/provider calls."""

import unittest

from app.services.speech_segments import SpeechSegmenter


class SpeechSegmentsTest(unittest.TestCase):
    def test_first_sentence_before_end(self):
        stream = SpeechSegmenter()
        self.assertEqual(stream.append("你好"), [])
        first = stream.append("。我继续回答")
        self.assertEqual([(s.index, s.text) for s in first], [(0, "你好。")])
        tail = stream.append("你的问题", final=True)
        self.assertEqual(tail[0].text, "我继续回答你的问题")
        self.assertEqual(tail[0].start, first[0].end)

    def test_sse_chunking_preserves_identity(self):
        text = "价格是3.14。Next sentence. 最后一句！"
        whole = SpeechSegmenter().append(text, final=True)
        stream, pieces = SpeechSegmenter(), []
        for char in text:
            pieces.extend(stream.append(char))
        pieces.extend(stream.append("", final=True))
        self.assertEqual(pieces, whole)

    def test_long_input_bounded(self):
        stream = SpeechSegmenter(max_chars=16)
        result = stream.append("字" * 40, final=True)
        self.assertEqual([len(s.text) for s in result], [16, 16, 8])

    def test_overflow_does_not_partially_advance(self):
        stream = SpeechSegmenter(max_chars=16, max_segments=1)
        with self.assertRaises(ValueError):
            stream.append("第一句。第二句。")
        result = stream.append("新的回答。", final=True)
        self.assertEqual(result[0].index, 0)
        self.assertEqual(result[0].start, 0)

    def test_cancel_and_close_reject_late_results(self):
        for cancel in (True, False):
            stream = SpeechSegmenter()
            stream.append("未完成")
            stream.cancel() if cancel else stream.append("", final=True)
            with self.assertRaises(ValueError):
                stream.append("迟到结果")


if __name__ == "__main__":
    unittest.main()
