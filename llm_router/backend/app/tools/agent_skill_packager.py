"""Utilities for repairing legacy Agent Skill ZIP layouts."""

from __future__ import annotations

from pathlib import PurePosixPath

from app.services.skill_import_service import _normalize_files, _safe_archive


def _safe_package_path(value: str, *, label: str) -> str:
    normalized = value.replace("\\", "/").lstrip("/")
    path = PurePosixPath(normalized)
    if not normalized or path.is_absolute() or ".." in path.parts:
        raise ValueError(f"{label} must be a safe relative package path")
    return normalized


def repackage_agent_skill(
    raw_archive: bytes,
    *,
    source_script: str = "process_bank_statement.py",
    target_script: str = "scripts/process_bank_statement.py",
    drop_paths: tuple[str, ...] = (),
    instruction_replacements: tuple[tuple[str, str], ...] = (),
) -> bytes:
    """Move one legacy script into ``scripts/`` and rebuild a deterministic ZIP.

    ``drop_paths`` is deliberately explicit: repair tooling must not guess which
    files are backups and accidentally remove a legitimate Skill resource.
    """
    source = _safe_package_path(source_script, label="source_script")
    target = _safe_package_path(target_script, label="target_script")
    drops = {_safe_package_path(path, label="drop_path") for path in drop_paths}

    _, files, skill_path = _safe_archive(raw_archive, "skill.zip")
    if source not in files:
        raise ValueError(f"Source script is missing from package: {source}")
    if target != source and target in files:
        raise ValueError(f"Target script already exists in package: {target}")
    if skill_path in drops or source in drops or target in drops:
        raise ValueError("SKILL.md and the source/target script cannot be dropped")

    repaired = {path: data for path, data in files.items() if path not in drops}
    repaired[target] = repaired.pop(source)
    try:
        skill_md = repaired[skill_path].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("SKILL.md must be UTF-8") from exc
    skill_md = skill_md.replace(source, target)
    for old, new in instruction_replacements:
        if not old:
            raise ValueError("instruction replacement source cannot be empty")
        if old not in skill_md:
            raise ValueError(f"Instruction text is missing from SKILL.md: {old}")
        skill_md = skill_md.replace(old, new)
    repaired[skill_path] = skill_md.encode("utf-8")

    archive, _, _ = _normalize_files(repaired)
    return archive
