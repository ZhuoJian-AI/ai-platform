"""Bounded sentence framing for trusted public prose, not raw model events.

The caller must first exclude reasoning, tool payloads and provisional business
claims. This module deliberately does not decide whether a result is truthful.
Offsets bind each segment to the exact approved text, independent of SSE chunks.
"""

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class SpeechSegment:
    index: int
    start: int
    end: int
    text: str


class SpeechSegmenter:
    def __init__(self, max_chars: int = 240, max_segments: int = 64):
        if max_chars < 16 or max_segments < 1:
            raise ValueError("Invalid speech framing limits")
        self.max_chars = max_chars
        self.max_segments = max_segments
        self._pending = ""
        self._offset = 0
        self._index = 0
        self._closed = False

    def append(self, approved_prose: str, *, final: bool = False) -> list[SpeechSegment]:
        if self._closed:
            raise ValueError("Speech stream already closed")
        # Limits are checked before changing state. Never silently drop overflow.
        if len(self._pending) + len(approved_prose) > self.max_chars * self.max_segments:
            raise ValueError("Speech text exceeds bounded buffer")
        pending = self._pending + approved_prose
        offset, index = self._offset, self._index
        segments = []
        while pending:
            boundary = self._boundary(pending, final)
            if boundary is None:
                break
            raw = pending[:boundary]
            if raw.strip():
                if index >= self.max_segments:
                    raise ValueError("Speech segment budget exceeded")
                segments.append(SpeechSegment(index, offset, offset + boundary, raw.strip()))
                index += 1
            offset += boundary
            pending = pending[boundary:]
        self._pending, self._offset, self._index = pending, offset, index
        self._closed = final
        return segments

    def _boundary(self, text: str, final: bool) -> int | None:
        # Chinese punctuation is unambiguous. English full stops need a following
        # separator so token splits in 3.14 or example.com do not split a sentence.
        match = re.search(r"[。！？!?\n]|\.(?=\s)", text)
        if match and match.end() <= self.max_chars:
            return match.end()
        if len(text) >= self.max_chars:
            # Prefer a clause/word boundary; long unpunctuated input is still bounded.
            candidates = list(re.finditer(r"[，,；;\s]", text[:self.max_chars]))
            cut = candidates[-1].end() if candidates else self.max_chars
            return cut if cut >= self.max_chars // 2 else self.max_chars
        return len(text) if final else None

    def cancel(self) -> None:
        self._pending = ""
        self._closed = True
