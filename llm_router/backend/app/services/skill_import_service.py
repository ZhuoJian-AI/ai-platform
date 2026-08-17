"""Safe Skill package import, immutable versioning, and activation."""

from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from pathlib import PurePosixPath
from uuid import UUID

from fastapi import HTTPException, UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.skill import SkillFolder, SkillVersion
from app.schemas.skill import SkillFileCreate, SkillFolderCreate
from app.services import skill_store_service
from app.tools.skill_manifest import parse_skill_manifest, parse_skill_manifest_dict

MAX_PACKAGE_BYTES = 10 * 1024 * 1024
MAX_ARCHIVE_FILES = 200
MAX_UNCOMPRESSED_BYTES = 50 * 1024 * 1024
TEXT_FILE_LIMIT = 1024 * 1024
_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(value: str, package_hash: str) -> str:
    slug = _SLUG_RE.sub("-", value.lower()).strip("-")[:90]
    return slug or f"skill-{package_hash[:10]}"


def _safe_archive(raw: bytes, filename: str) -> tuple[bytes, dict[str, bytes], str]:
    suffix = PurePosixPath(filename.lower()).suffix
    if suffix in {".md", ".markdown"}:
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("SKILL.md", raw)
        return out.getvalue(), {"SKILL.md": raw}, "SKILL.md"
    if suffix != ".zip":
        raise HTTPException(status_code=415, detail="Only .zip and .md Skill packages are supported")
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            infos = [i for i in zf.infolist() if not i.is_dir()]
            if not infos or len(infos) > MAX_ARCHIVE_FILES:
                raise HTTPException(status_code=422, detail="Skill archive must contain 1-200 files")
            if sum(i.file_size for i in infos) > MAX_UNCOMPRESSED_BYTES:
                raise HTTPException(status_code=413, detail="Expanded Skill package exceeds 50MB")
            files: dict[str, bytes] = {}
            for info in infos:
                normalized = info.filename.replace("\\", "/").lstrip("/")
                path = PurePosixPath(normalized)
                if not normalized or ".." in path.parts or path.is_absolute():
                    raise HTTPException(status_code=422, detail="Unsafe path in Skill archive")
                files[str(path)] = zf.read(info)
    except zipfile.BadZipFile as exc:
        raise HTTPException(status_code=422, detail="Invalid ZIP package") from exc

    skill_paths = [path for path in files if PurePosixPath(path).name.lower() == "skill.md"]
    if len(skill_paths) != 1:
        raise HTTPException(status_code=422, detail="Skill package must contain exactly one SKILL.md")
    skill_path = skill_paths[0]
    root = str(PurePosixPath(skill_path).parent)
    if root not in {".", ""}:
        prefix = root.rstrip("/") + "/"
        if all(path.startswith(prefix) for path in files):
            files = {path[len(prefix):]: data for path, data in files.items()}
            skill_path = "SKILL.md"
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for path, data in sorted(files.items()):
            zf.writestr(path, data)
    return out.getvalue(), files, skill_path


def _resolve_runtime(manifest: dict, files: dict[str, bytes]) -> tuple[str, str | None, bool]:
    runtime = str(manifest.get("runtime") or "prompt").lower()
    entrypoint = str(manifest.get("entrypoint") or "").strip() or None
    if runtime not in {"prompt", "python", "node"}:
        raise HTTPException(status_code=422, detail="runtime must be prompt, python, or node")
    if runtime == "node" and not entrypoint and "package.json" in files:
        try:
            package = json.loads(files["package.json"].decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=422, detail="Invalid package.json") from exc
        command = str(manifest.get("command") or "")
        bins = package.get("bin")
        if isinstance(bins, str):
            entrypoint = bins
        elif isinstance(bins, dict) and command in bins:
            entrypoint = str(bins[command])
    if runtime in {"python", "node"}:
        if not entrypoint:
            raise HTTPException(status_code=422, detail="Executable Skill requires entrypoint or package.json.bin")
        normalized = str(PurePosixPath(entrypoint.replace("\\", "/")))
        if normalized not in files or ".." in PurePosixPath(normalized).parts:
            raise HTTPException(status_code=422, detail="Skill entrypoint is missing from the package")
        return runtime, normalized, True
    return "prompt", None, False


async def import_package(
    db: AsyncSession,
    *,
    org_id: UUID,
    scope_type: str,
    scope_id: str | None,
    upload: UploadFile,
    created_by: str | None,
) -> tuple[SkillFolder, SkillVersion]:
    raw = await upload.read(MAX_PACKAGE_BYTES + 1)
    if not raw:
        raise HTTPException(status_code=422, detail="Skill package is empty")
    if len(raw) > MAX_PACKAGE_BYTES:
        raise HTTPException(status_code=413, detail="Skill package exceeds 10MB")
    archive, files, skill_path = _safe_archive(raw, upload.filename or "skill.zip")
    try:
        skill_md = files[skill_path].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=422, detail="SKILL.md must be UTF-8") from exc
    manifest = parse_skill_manifest_dict(skill_md)
    parsed = parse_skill_manifest(skill_md)
    if manifest is None or parsed is None:
        raise HTTPException(status_code=422, detail="SKILL.md requires a valid name and manifest/frontmatter")
    package_hash = hashlib.sha256(archive).hexdigest()
    slug = _slugify(str(manifest.get("command") or manifest.get("name") or parsed.name), package_hash)
    runtime, entrypoint, executable = _resolve_runtime(manifest, files)

    folder = (await db.execute(select(SkillFolder).where(
        SkillFolder.organization_id == org_id,
        SkillFolder.scope_type == scope_type,
        SkillFolder.scope_id.is_(None) if scope_id is None else SkillFolder.scope_id == scope_id,
        SkillFolder.slug == slug,
        SkillFolder.deleted_at.is_(None),
    ))).scalar_one_or_none()
    if folder is None:
        folder = await skill_store_service.create_folder(db, org_id, SkillFolderCreate(
            name=str(manifest.get("name") or parsed.name)[:255],
            slug=slug,
            scope_type=scope_type,
            scope_id=scope_id,
        ), created_by=created_by)
    existing = (await db.execute(select(SkillVersion).where(
        SkillVersion.skill_folder_id == folder.id,
        SkillVersion.package_hash == package_hash,
    ))).scalar_one_or_none()
    if existing:
        return folder, existing
    next_no = int((await db.execute(select(func.max(SkillVersion.version_no)).where(
        SkillVersion.skill_folder_id == folder.id,
    ))).scalar_one_or_none() or 0) + 1
    status = "pending" if executable and settings.code_skills_enabled else "ready"
    version = SkillVersion(
        skill_folder_id=folder.id,
        version_no=next_no,
        package_hash=package_hash,
        manifest=manifest,
        archive=archive,
        runtime=runtime,
        entrypoint=entrypoint,
        is_executable=executable,
        install_status=status,
    )
    db.add(version)
    await db.flush()
    if status == "ready":
        await activate_version(db, folder, version, skill_md)
    return folder, version


async def activate_version(
    db: AsyncSession, folder: SkillFolder, version: SkillVersion, skill_md: str | None = None,
) -> None:
    if version.install_status != "ready":
        raise HTTPException(status_code=409, detail="Only ready versions can be activated")
    if skill_md is None:
        with zipfile.ZipFile(io.BytesIO(version.archive)) as zf:
            match = next(name for name in zf.namelist() if PurePosixPath(name).name.lower() == "skill.md")
            skill_md = zf.read(match).decode("utf-8")
    await skill_store_service.upsert_file(db, folder, SkillFileCreate(
        path="skill.md", content=skill_md, metadata={"version_id": str(version.id)}
    ))
    folder.active_version_id = version.id
    await db.flush()


async def list_versions(db: AsyncSession, folder_id: UUID) -> list[SkillVersion]:
    return list((await db.execute(select(SkillVersion).where(
        SkillVersion.skill_folder_id == folder_id,
    ).order_by(SkillVersion.version_no.desc()))).scalars().all())
