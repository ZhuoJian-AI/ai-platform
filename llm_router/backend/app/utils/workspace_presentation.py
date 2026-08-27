"""User-facing workspace file names and artifact metadata.

Storage paths are deliberately immutable transport identifiers.  This module
keeps those identifiers available to services while deriving a stable,
human-readable presentation for APIs and task messages.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import PurePosixPath
from typing import Any

MANAGED_OUTPUT_ROOTS = {
    "技能输出": "skill",
    "平台工具输出": "platform_tool",
}

_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-"
    r"[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$"
)
_MANAGED_PREFIX_RE = re.compile(r"^\d{8}-\d{6}-[0-9a-fA-F]{8}-(?=.)")
_ATTACHMENT_PREFIX_RE = re.compile(r"^\d{8}T\d{6}Z-[0-9a-fA-F]{8}-(?=.)")


def clean_display_name(path: str, metadata: dict[str, Any] | None = None) -> str:
    """Return a friendly filename without changing the persisted path."""
    meta = metadata or {}
    explicit = str(meta.get("display_name") or meta.get("name") or "").strip()
    if explicit:
        return PurePosixPath(explicit.replace("\\", "/")).name
    name = PurePosixPath((path or "未命名文件").replace("\\", "/")).name
    name = _MANAGED_PREFIX_RE.sub("", name)
    name = _ATTACHMENT_PREFIX_RE.sub("", name)
    return name or "未命名文件"


def infer_source(path: str, metadata: dict[str, Any] | None = None) -> tuple[str, str | None]:
    """Infer source kind and task id only from managed paths/explicit metadata."""
    meta = metadata or {}
    source_kind = str(meta.get("source_kind") or "").strip()
    task_id = str(meta.get("source_task_id") or meta.get("task_id") or "").strip() or None
    parts = [part for part in (path or "").replace("\\", "/").split("/") if part]
    if not source_kind and parts:
        source_kind = MANAGED_OUTPUT_ROOTS.get(parts[0], "")
    if task_id is None and len(parts) >= 2 and parts[0] in MANAGED_OUTPUT_ROOTS and _UUID_RE.fullmatch(parts[1]):
        task_id = parts[1]
    if not source_kind:
        generated_by = str(meta.get("generated_by") or "")
        source_kind = "platform_tool" if generated_by else "upload"
    return source_kind, task_id


def presentation_dict(
    path: str,
    metadata: dict[str, Any] | None = None,
    *,
    created_at: datetime | str | None = None,
) -> dict[str, Any]:
    meta = metadata or {}
    source_kind, task_id = infer_source(path, meta)
    # A persisted row timestamp is authoritative when the caller has it.  The
    # metadata timestamp remains the fallback for legacy/task payloads.
    created = created_at or meta.get("source_created_at")
    if isinstance(created, datetime):
        created = created.isoformat()
    return {
        "display_name": clean_display_name(path, meta),
        "source_kind": source_kind,
        "source_task_id": task_id,
        "source_task_title": meta.get("source_task_title"),
        "skill_id": meta.get("skill_id"),
        "skill_display_name": meta.get("skill_display_name"),
        "skill_version": meta.get("skill_version"),
        "created_at": created,
    }


def enrich_metadata(
    path: str,
    metadata: dict[str, Any] | None,
    *,
    created_at: datetime | str | None = None,
    **source: Any,
) -> dict[str, Any]:
    """Add presentation fields without deleting existing storage metadata."""
    merged = {**(metadata or {}), **{key: value for key, value in source.items() if value is not None}}
    presentation = presentation_dict(path, merged, created_at=created_at)
    merged["display_name"] = presentation["display_name"]
    for key in (
        "source_kind", "source_task_id", "source_task_title", "skill_id",
        "skill_display_name", "skill_version", "source_created_at",
    ):
        presentation_key = "created_at" if key == "source_created_at" else key
        value = merged.get(key) if merged.get(key) is not None else presentation.get(presentation_key)
        if value is not None:
            merged[key] = str(value) if key != "source_created_at" else value
    if created_at and not merged.get("source_created_at"):
        merged["source_created_at"] = created_at.isoformat() if isinstance(created_at, datetime) else created_at
    return merged


def _decode_json(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    stripped = value.strip()
    if not stripped or stripped[0] not in "[{":
        return value
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return value


def artifacts_from_traces(
    traces: list[dict[str, Any]] | None,
    *,
    task_id: str | None,
    task_title: str | None = None,
    executed_skills: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Extract verified file outputs into assistant-message metadata.

    The full trace remains available for technical replay; this compact list is
    the stable user-facing contract consumed by the frontend.
    """
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    skill = (executed_skills or [])[-1] if executed_skills else {}

    def visit(value: Any, trace: dict[str, Any]) -> None:
        value = _decode_json(value)
        if isinstance(value, list):
            for item in value:
                visit(item, trace)
            return
        if not isinstance(value, dict):
            return
        file_id = str(value.get("file_id") or value.get("fileId") or "").strip()
        path = str(value.get("path") or "").strip()
        if file_id or path:
            marker = file_id or path
            if marker not in seen:
                seen.add(marker)
                name = str(value.get("display_name") or value.get("name") or value.get("filename") or "")
                source_kind = "skill" if skill or "skill" in str(trace.get("name") or "") else "platform_tool"
                records.append({
                    "file_id": file_id or None,
                    "display_name": clean_display_name(path or name, {"name": name} if name else None),
                    "mime_type": value.get("mime_type") or value.get("mime"),
                    "size": value.get("size"),
                    "parse_status": value.get("parse_status"),
                    "source": {
                        "kind": source_kind,
                        "task_id": task_id,
                        "task_title": task_title,
                        "skill_id": skill.get("id"),
                        "skill_display_name": skill.get("name"),
                        "skill_version": skill.get("version_no"),
                    },
                    "workspace_path": path or None,
                })
        for key in ("outputs", "files", "artifacts", "output", "data", "result", "content"):
            if key in value:
                visit(value[key], trace)

    for trace in traces or []:
        if not isinstance(trace, dict) or trace.get("ok") is False:
            continue
        visit(trace.get("result"), trace)
    return records
