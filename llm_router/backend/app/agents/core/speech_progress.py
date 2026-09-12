"""Publish bounded public sentences only after the coordinator's evidence gate."""
import re

from fastapi import HTTPException

from app.services.message_speech_service import content_version, spoken_text


class SpeechProgress:
    def __init__(self):
        self.prefix = ""
        self.index = 0
        self.finished = False

    def update(self, text: str, *, ready: bool, final: bool = False):
        if not ready or self.index >= 64 or self.finished:
            return []
        # Incomplete rich markup can change interpretation of earlier characters.
        # Defer it until final sanitization rather than speaking partial URLs/code.
        if not final and any(marker in text for marker in ("<", "`", "~", "[", "|", "http", "oss://")):
            return []
        try:
            prose = spoken_text(text, excerpt=False)
        except HTTPException:
            return []
        events = []
        if not prose.startswith(self.prefix):
            events.append({"type": "speech_reset", "invalidatesBefore": self.index})
            self.prefix = ""
        if final and (len(prose) > 600 or "|" in text or self.index >= 63):
            # The audio endpoint adapts this final public source lazily. Ordinary
            # text-only runs incur no summary model call. Keep prior segment IDs.
            events.append({"type": "speech_segment", "segmentIndex": self.index,
                           "text": text, "summaryRequired": True,
                           "contentVersion": content_version(text)})
            self.index += 1
            self.finished = True
            return events
        remaining = prose[len(self.prefix):]
        while remaining and self.index < 63:
            boundary = re.search(r"[。！？!?]|\.(?=\s)", remaining)
            if boundary is None and not final:
                break
            end = boundary.end() if boundary else len(remaining)
            sentence = remaining[:end]
            if len(self.prefix) + len(sentence) > 600:
                # Wait for the verified final reply, including any late failure,
                # instead of permanently finishing at an arbitrary text cutoff.
                break
            # Rich/long answers retain the existing explicit excerpt policy.
            if len(sentence) > 600:
                break
            self.prefix += sentence
            remaining = remaining[end:]
            if sentence.strip():
                events.append({"type": "speech_segment", "segmentIndex": self.index,
                               "text": sentence.strip(), "contentVersion": content_version(sentence.strip())})
                self.index += 1
        return events
