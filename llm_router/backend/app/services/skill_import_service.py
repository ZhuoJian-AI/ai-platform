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
from app.models.organization import Organization
from app.models.skill import SkillFile, SkillFolder, SkillVersion
from app.schemas.skill import SkillFolderCreate
from app.services import skill_store_service, storage_gateway_service
from app.services.storage_lifecycle_service import mark_deleted, restore
from app.tools.skill_manifest import parse_skill_manifest, parse_skill_manifest_dict

MAX_PACKAGE_BYTES = settings.skill_package_max_bytes
MAX_ARCHIVE_FILES = settings.skill_package_max_files
MAX_UNCOMPRESSED_BYTES = settings.skill_package_expanded_max_bytes
TEXT_FILE_LIMIT = 1024 * 1024
_SLUG_RE = re.compile(r"[^a-z0-9]+")
_SCRIPT_LANGUAGES = {
    ".py": "python",
    ".js": "node",
    ".mjs": "node",
    ".cjs": "node",
    ".sh": "bash",
}
_TEXT_SUFFIXES = {
    ".md", ".markdown", ".txt", ".json", ".yaml", ".yml", ".toml",
    ".py", ".js", ".mjs", ".cjs", ".sh", ".csv", ".tsv", ".xml", ".html", ".css",
}
_LEGACY_MANIFEST_KEYS = {"runtime", "entrypoint", "bound_endpoint_ids", "parameters", "arguments"}


def _slugify(value: str, package_hash: str) -> str:
    slug = _SLUG_RE.sub("-", value.lower()).strip("-")[:90]
    return slug or f"skill-{package_hash[:10]}"


def _normalize_files(files: dict[str, bytes]) -> tuple[bytes, dict[str, bytes], str]:
    """Validate and canonicalize an Agent Skill directory tree.

    A single wrapper directory (the normal result of zipping a folder) is
    removed so ZIP and browser-directory uploads produce the same package
    hash and the same immutable SkillVersion.
    """
    if not files or len(files) > MAX_ARCHIVE_FILES:
        raise HTTPException(status_code=422, detail=f"Skill package must contain 1-{MAX_ARCHIVE_FILES} files")
    normalized_files: dict[str, bytes] = {}
    canonical_paths: set[str] = set()
    total = 0
    for raw_path, data in files.items():
        normalized = raw_path.replace("\\", "/").lstrip("/")
        path = PurePosixPath(normalized)
        if not normalized or ".." in path.parts or path.is_absolute():
            raise HTTPException(status_code=422, detail="Unsafe path in Skill package")
        canonical = normalized.casefold()
        if canonical in canonical_paths:
            raise HTTPException(status_code=422, detail=f"Duplicate Skill path: {normalized}")
        canonical_paths.add(canonical)
        total += len(data)
        if total > MAX_UNCOMPRESSED_BYTES:
            raise HTTPException(status_code=413, detail="Expanded Skill package exceeds 500MB")
        normalized_files[normalized] = data

    skill_paths = [path for path in normalized_files if PurePosixPath(path).name.lower() == "skill.md"]
    if len(skill_paths) != 1:
        raise HTTPException(status_code=422, detail="Skill package must contain exactly one SKILL.md")
    skill_path = skill_paths[0]
    root = str(PurePosixPath(skill_path).parent)
    if root not in {".", ""}:
        prefix = root.rstrip("/") + "/"
        if all(path.startswith(prefix) for path in normalized_files):
            normalized_files = {path[len(prefix):]: data for path, data in normalized_files.items()}
            skill_path = "SKILL.md"

    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for path, data in sorted(normalized_files.items()):
            info = zipfile.ZipInfo(path, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            zf.writestr(info, data)
    archive = out.getvalue()
    if len(archive) > MAX_PACKAGE_BYTES:
        raise HTTPException(status_code=413, detail="Normalized Skill archive exceeds 100MB")
    return archive, normalized_files, skill_path


def _safe_archive(raw: bytes, filename: str) -> tuple[bytes, dict[str, bytes], str]:
    suffix = PurePosixPath(filename.lower()).suffix
    if suffix in {".md", ".markdown"}:
        return _normalize_files({"SKILL.md": raw})
    if suffix != ".zip":
        raise HTTPException(status_code=415, detail="Only .zip and .md Skill packages are supported")
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            infos = [i for i in zf.infolist() if not i.is_dir()]
            if not infos or len(infos) > MAX_ARCHIVE_FILES:
                raise HTTPException(
                    status_code=422, detail=f"Skill archive must contain 1-{MAX_ARCHIVE_FILES} files",
                )
            if sum(info.file_size for info in infos) > MAX_UNCOMPRESSED_BYTES:
                raise HTTPException(status_code=413, detail="Expanded Skill package exceeds 500MB")
            files: dict[str, bytes] = {}
            for info in infos:
                normalized = info.filename.replace("\\", "/").lstrip("/")
                if normalized in files:
                    raise HTTPException(status_code=422, detail=f"Duplicate Skill path: {normalized}")
                files[normalized] = zf.read(info)
    except (zipfile.BadZipFile, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail="Invalid ZIP package") from exc

    return _normalize_files(files)


async def _folder_archive(
    uploads: list[UploadFile], relative_paths: list[str],
) -> tuple[bytes, dict[str, bytes], str]:
    if not uploads or len(uploads) != len(relative_paths):
        raise HTTPException(status_code=422, detail="files and relative_paths must have the same non-zero length")
    if len(uploads) > MAX_ARCHIVE_FILES:
        raise HTTPException(status_code=422, detail=f"Skill package must contain 1-{MAX_ARCHIVE_FILES} files")
    files: dict[str, bytes] = {}
    total = 0
    for upload, path in zip(uploads, relative_paths, strict=True):
        # A browser folder upload is already expanded. Apply the expanded
        # 500MB boundary here; the deterministic ZIP produced by
        # ``_normalize_files`` is independently constrained to 100MB.
        remaining = MAX_UNCOMPRESSED_BYTES - total
        raw = await upload.read(remaining + 1)
        total += len(raw)
        if total > MAX_UNCOMPRESSED_BYTES:
            raise HTTPException(status_code=413, detail="Expanded Skill package exceeds 500MB")
        files[path or upload.filename or ""] = raw
    return _normalize_files(files)


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


def _agent_skill_metadata(manifest: dict, files: dict[str, bytes], skill_md: str) -> dict:
    scripts = []
    unsupported_scripts = []
    for path in sorted(files):
        posix = PurePosixPath(path)
        if not posix.parts or posix.parts[0].lower() != "scripts":
            continue
        language = _SCRIPT_LANGUAGES.get(posix.suffix.lower())
        if language:
            scripts.append({"path": path, "language": language})
        elif posix.suffix:
            unsupported_scripts.append(path)
    warnings: list[str] = []
    if unsupported_scripts:
        warnings.append("不支持的脚本类型：" + "、".join(unsupported_scripts[:10]))
    proprietary = sorted(key for key in ("allowed-tools", "context", "agent", "hooks") if key in manifest)
    if proprietary:
        warnings.append("已保留但不模拟的 Claude 扩展字段：" + "、".join(proprietary))
    lowered = skill_md.lower()
    if "computer use" in lowered or "computer_use" in lowered:
        warnings.append("当前宿主不提供 Computer Use")
    if "mcp" in lowered:
        warnings.append("Skill 中的 MCP 能力不会由代码 Runner 自动提供")
    if re.search(r"(^|\n)\s*!\S+", skill_md):
        warnings.append("Claude !command 语法不会自动执行")
    resources = [
        {"path": path, "size": len(data), "kind": (PurePosixPath(path).parts[0].lower()
         if len(PurePosixPath(path).parts) > 1 else "root")}
        for path, data in sorted(files.items())
    ]
    languages = sorted({item["language"] for item in scripts})
    dependency_names = ("requirements.txt", "pyproject.toml", "package.json", "package-lock.json")
    dependencies = [path for path in dependency_names if path in files]
    return {
        "package_format": "agent_skill",
        "scripts": scripts,
        "resources": resources,
        "script_languages": languages,
        "dependencies": dependencies,
        "compatibility_warnings": warnings,
    }


async def _persist_package(
    db: AsyncSession, *, org_id: UUID, scope_type: str, scope_id: str | None,
    archive: bytes, files: dict[str, bytes], skill_path: str, created_by: str | None,
) -> tuple[SkillFolder, SkillVersion]:
    try:
        skill_md = files[skill_path].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=422, detail="SKILL.md must be UTF-8") from exc
    raw_manifest = parse_skill_manifest_dict(skill_md)
    parsed = parse_skill_manifest(skill_md)
    if raw_manifest is None or parsed is None:
        raise HTTPException(
            status_code=422, detail="SKILL.md requires valid YAML frontmatter with name and description",
        )
    legacy = bool(_LEGACY_MANIFEST_KEYS.intersection(raw_manifest))
    if not legacy and not str(raw_manifest.get("description") or "").strip():
        raise HTTPException(status_code=422, detail="Standard Agent Skill requires frontmatter name and description")

    manifest = dict(raw_manifest)
    if legacy:
        runtime, entrypoint, executable = _resolve_runtime(manifest, files)
    else:
        platform = _agent_skill_metadata(manifest, files, skill_md)
        manifest["_platform"] = platform
        runtime, entrypoint = "agent_skill", None
        executable = bool(platform["scripts"])

    package_hash = hashlib.sha256(archive).hexdigest()
    slug = _slugify(str(manifest.get("command") or manifest.get("name") or parsed.name), package_hash)
    return await _create_version(
        db, org_id=org_id, scope_type=scope_type, scope_id=scope_id,
        archive=archive, files=files, skill_md=skill_md, manifest=manifest,
        parsed=parsed, package_hash=package_hash, slug=slug, runtime=runtime,
        entrypoint=entrypoint, executable=executable, created_by=created_by,
    )


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
        raise HTTPException(status_code=413, detail="Skill package exceeds 100MB")
    archive, files, skill_path = _safe_archive(raw, upload.filename or "skill.zip")
    return await _persist_package(
        db, org_id=org_id, scope_type=scope_type, scope_id=scope_id,
        archive=archive, files=files, skill_path=skill_path, created_by=created_by,
    )


async def import_package_folder(
    db: AsyncSession, *, org_id: UUID, scope_type: str, scope_id: str | None,
    uploads: list[UploadFile], relative_paths: list[str], created_by: str | None,
) -> tuple[SkillFolder, SkillVersion]:
    archive, files, skill_path = await _folder_archive(uploads, relative_paths)
    return await _persist_package(
        db, org_id=org_id, scope_type=scope_type, scope_id=scope_id,
        archive=archive, files=files, skill_path=skill_path, created_by=created_by,
    )


async def _create_version(
    db: AsyncSession, *, org_id: UUID, scope_type: str, scope_id: str | None,
    archive: bytes, files: dict[str, bytes], skill_md: str, manifest: dict,
    parsed, package_hash: str, slug: str, runtime: str, entrypoint: str | None,
    executable: bool, created_by: str | None,
) -> tuple[SkillFolder, SkillVersion]:

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
    organization = await db.get(Organization, org_id)
    agent_package = manifest.get("_platform", {}).get("package_format") == "agent_skill"
    enabled = settings.code_skills_enabled
    if agent_package:
        enabled = bool(organization and settings.agent_skills_enabled_for(organization.slug))
    status = "pending" if executable and enabled else "ready"
    archive_ref: str | None = None
    inline_archive: bytes | None = archive
    storage_status = "inline"
    if settings.workspace_object_storage_configured:
        try:
            archive_ref = await storage_gateway_service.upload_skill_archive(
                archive, organization_id=str(org_id), package_hash=package_hash,
            )
        except storage_gateway_service.StorageGatewayError as exc:
            raise HTTPException(status_code=502, detail="Skill package OSS upload failed") from exc
        inline_archive = None
        storage_status = "stored"
    version = SkillVersion(
        skill_folder_id=folder.id,
        version_no=next_no,
        package_hash=package_hash,
        manifest=manifest,
        archive=inline_archive,
        archive_ref=archive_ref,
        archive_size=len(archive),
        storage_status=storage_status,
        runtime=runtime,
        entrypoint=entrypoint,
        is_executable=executable,
        install_status=status,
    )
    db.add(version)
    await db.flush()
    if status == "ready":
        await activate_version(db, folder, version, skill_md, archive=archive)
    return folder, version


async def activate_version(
    db: AsyncSession, folder: SkillFolder, version: SkillVersion, skill_md: str | None = None,
    archive: bytes | None = None,
) -> None:
    if version.install_status != "ready":
        raise HTTPException(status_code=409, detail="Only ready versions can be activated")
    package = archive if archive is not None else await load_version_archive(version)
    with zipfile.ZipFile(io.BytesIO(package)) as zf:
        package_files = {name: zf.read(name) for name in zf.namelist() if not name.endswith("/")}
    existing = list((await db.execute(select(SkillFile).where(
        SkillFile.skill_folder_id == folder.id,
    ))).scalars().all())
    by_path = {item.path: item for item in existing}
    active_paths: set[str] = set()
    for path, raw in package_files.items():
        normalized = str(PurePosixPath(path))
        posix_path = PurePosixPath(normalized)
        if posix_path.name.lower() == "skill.md" and posix_path.parent == PurePosixPath("."):
            # Existing runtime and APIs use the historical lowercase manifest path.
            normalized = "skill.md"
        active_paths.add(normalized)
        content: str | None = None
        if len(raw) <= TEXT_FILE_LIMIT and PurePosixPath(path).suffix.lower() in _TEXT_SUFFIXES:
            try:
                content = raw.decode("utf-8")
            except UnicodeDecodeError:
                content = None
        item = by_path.get(normalized)
        meta = {
            "version_id": str(version.id),
            "binary": content is None,
            "package_path": normalized,
        }
        if item is None:
            item = SkillFile(skill_folder_id=folder.id, path=normalized)
            db.add(item)
        restore(item)
        item.size = len(raw)
        item.content_hash = hashlib.sha256(raw).hexdigest()
        item.content = content
        item.metadata_ = meta
    for item in existing:
        if item.path not in active_paths and item.deleted_at is None:
            # Package activation is a complete immutable snapshot; resources
            # removed by a newer version must not remain visible as stale files.
            mark_deleted(item)
    folder.active_version_id = version.id
    await db.flush()


async def load_version_archive(version: SkillVersion) -> bytes:
    """Load a package during the inline-to-OSS rolling migration."""
    if version.archive_ref:
        raw = await storage_gateway_service.download_bytes(version.archive_ref)
    elif version.archive:
        raw = bytes(version.archive)
    else:
        raise HTTPException(status_code=410, detail="Skill package has been physically purged")
    if len(raw) != int(version.archive_size or len(raw)):
        raise HTTPException(status_code=409, detail="Skill package size mismatch")
    if hashlib.sha256(raw).hexdigest() != version.package_hash:
        raise HTTPException(status_code=409, detail="Skill package hash mismatch")
    return raw


async def signed_version_archive(version: SkillVersion) -> dict:
    """Return a short-lived Runner input, with inline fallback for legacy rows."""
    if version.archive_ref:
        signed = await storage_gateway_service.get_signed_download(version.archive_ref)
        return {
            "archive_url": signed["url"],
            "archive_headers": signed.get("headers") or {},
            "archive_size": int(version.archive_size or 0),
        }
    if version.archive:
        import base64
        return {"archive_base64": base64.b64encode(version.archive).decode("ascii")}
    raise HTTPException(status_code=410, detail="Skill package has been physically purged")


async def read_version_resource(version: SkillVersion, path: str) -> bytes:
    """Read one immutable package resource with traversal-safe exact matching."""
    normalized = str(PurePosixPath(path.replace("\\", "/").lstrip("/")))
    posix = PurePosixPath(normalized)
    if not normalized or ".." in posix.parts or posix.is_absolute():
        raise HTTPException(status_code=422, detail="Unsafe Skill resource path")
    package = await load_version_archive(version)
    with zipfile.ZipFile(io.BytesIO(package)) as zf:
        names = {name: name for name in zf.namelist() if not name.endswith("/")}
        actual = names.get(normalized)
        if actual is None:
            raise HTTPException(status_code=404, detail="Skill resource not found")
        return zf.read(actual)


async def list_versions(db: AsyncSession, folder_id: UUID) -> list[SkillVersion]:
    return list((await db.execute(select(SkillVersion).where(
        SkillVersion.skill_folder_id == folder_id,
    ).order_by(SkillVersion.version_no.desc()))).scalars().all())
