"""Input-bound receipts for file analysis, separate from auxiliary business reads."""

import json
from dataclasses import dataclass, field


@dataclass
class FileAnalysisEvidence:
    requirements: dict[str, set[str]] = field(default_factory=dict)
    observed: set[str] = field(default_factory=set)

    def observe(self, *, name: str, kind: str, arguments: str, content: str, ok: bool) -> None:
        try:
            params = json.loads(arguments or "{}")
        except (ValueError, TypeError):
            return
        if not isinstance(params, dict):
            return
        values = params.get("input_file_ids")
        if not isinstance(values, list):
            return
        inputs = {value for value in values if isinstance(value, str) and value}
        if kind == "subsystem_specialist":
            self.requirements[name] = inputs
        try:
            result = json.loads(content)
        except (ValueError, TypeError):
            return
        if not ok or not isinstance(result, dict) or result.get("status") != "completed":
            return
        data = result.get("data")
        if not isinstance(data, dict):
            return
        if kind == "subsystem_specialist":
            if isinstance(data.get("draft"), dict) and data["draft"]:
                self.observed.update(inputs)
        elif kind in {"", "platform_tool"}:
            # Only built-in input-consuming receipts qualify. Search results,
            # generated files and subsystem-provided lookalike envelopes do not.
            if name == "image_tool" and params.get("action") == "understand" and data.get("answer"):
                rows = data.get("inputFiles") or []
            elif name == "audio_transcribe":
                rows = [r for r in data.get("transcriptions") or [] if isinstance(r, dict) and r.get("text")]
            elif name == "audio_understand":
                rows = [r for r in data.get("answers") or [] if isinstance(r, dict) and r.get("answer")]
            else:
                rows = []
            self.observed.update(
                row["fileId"] for row in rows
                if isinstance(row, dict) and isinstance(row.get("fileId"), str) and row["fileId"] in inputs
            )

    @property
    def required(self) -> set[str]:
        return set().union(*self.requirements.values())

    @property
    def verified(self) -> bool:
        return bool(self.required) and self.required <= self.observed
