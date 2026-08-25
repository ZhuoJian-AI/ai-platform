"""Internal HTTP client and resilient installation worker for skill-runner."""

from __future__ import annotations

import time
from uuid import UUID

import httpx
import structlog
from sqlalchemy import select

from app.config import settings
from app.database import async_session_factory
from app.models.skill import SkillFolder, SkillVersion
from app.services.skill_import_service import activate_version, signed_version_archive

logger = structlog.get_logger()


def _headers() -> dict[str, str]:
    return {"X-Skill-Runner-Token": settings.skill_runner_token}


async def install_version(version_id: UUID | str) -> None:
    async with async_session_factory() as db:
        version = await db.get(SkillVersion, UUID(str(version_id)))
        if version is None or version.install_status == "ready":
            return
        version.install_status = "installing"
        version.install_error = None
        await db.commit()
        payload = {
            "package_hash": version.package_hash,
            "runtime": version.runtime,
            "entrypoint": version.entrypoint,
            **await signed_version_archive(version),
        }
        try:
            async with httpx.AsyncClient(timeout=max(360, settings.skill_runner_timeout_seconds + 30)) as client:
                response = await client.post(
                    f"{settings.skill_runner_url.rstrip('/')}/install", json=payload, headers=_headers()
                )
                if response.is_error:
                    try:
                        detail = response.json().get("detail")
                    except (ValueError, AttributeError):
                        detail = response.text
                    raise RuntimeError(str(detail or f"Runner install failed ({response.status_code})"))
            runner_metadata = response.json()
            manifest = dict(version.manifest or {})
            platform = dict(manifest.get("_platform") or {})
            existing_warnings = list(platform.get("compatibility_warnings") or [])
            runner_warnings = list(runner_metadata.get("compatibility_warnings") or [])
            platform.update({
                "python_version": runner_metadata.get("python_version"),
                "node_version": runner_metadata.get("node_version"),
                "bash_version": runner_metadata.get("bash_version"),
                "libreoffice_version": runner_metadata.get("libreoffice_version"),
                "builtin_dependencies": runner_metadata.get("builtin_dependencies") or {},
                "installed_dependencies": runner_metadata.get("installed_dependencies") or {},
                "compatibility_warnings": list(dict.fromkeys([*existing_warnings, *runner_warnings])),
            })
            manifest["_platform"] = platform
            # Assign a new JSON object so SQLAlchemy persists the JSONB change.
            version.manifest = manifest
            version.install_status = "ready"
            folder = await db.get(SkillFolder, version.skill_folder_id)
            if folder is not None:
                await activate_version(db, folder, version)
        except Exception as exc:  # noqa: BLE001
            version.install_status = "failed"
            version.install_error = str(exc)[:2000]
            logger.warning("skill_install_failed", version_id=str(version.id), error=str(exc))
        await db.commit()


async def resume_pending_installs() -> None:
    if not settings.code_skills_enabled:
        return
    async with async_session_factory() as db:
        ids = list((await db.execute(select(SkillVersion.id).where(
            SkillVersion.is_executable.is_(True),
            SkillVersion.install_status.in_(["pending", "installing"]),
        ))).scalars().all())
    for version_id in ids:
        await install_version(version_id)


async def execute_version(
    version: SkillVersion, *, params: dict, inputs: list[dict], execution_id: int,
    script_path: str | None = None, args: list[str] | None = None,
) -> tuple[dict, int]:
    started = time.perf_counter()
    payload = {
        "package_hash": version.package_hash,
        "runtime": version.runtime,
        "entrypoint": version.entrypoint,
        "params": params,
        "inputs": inputs,
        "arguments": version.manifest.get("arguments") or [],
        "script_path": script_path,
        "args": args or [],
        "execution_id": execution_id,
        "timeout_seconds": settings.skill_runner_timeout_seconds,
        **await signed_version_archive(version),
    }
    timeout = settings.skill_runner_queue_wait_seconds + settings.skill_runner_timeout_seconds + 15
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            f"{settings.skill_runner_url.rstrip('/')}/execute", json=payload, headers=_headers()
        )
        if response.is_error:
            try:
                detail = response.json().get("detail")
            except (ValueError, AttributeError):
                detail = response.text
            raise RuntimeError(str(detail or f"Runner execution failed ({response.status_code})"))
    return response.json(), int((time.perf_counter() - started) * 1000)


async def execute_builtin(
    *, tool_kind: str, action: str, params: dict, inputs: list[dict],
    execution_id: str, timeout_seconds: int | None = None,
) -> tuple[dict, int]:
    """Execute a platform-owned file handler in Runner's immutable base environment."""
    started = time.perf_counter()
    payload = {
        "tool_kind": tool_kind,
        "action": action,
        "params": params,
        "inputs": inputs,
        "execution_id": execution_id,
        "timeout_seconds": timeout_seconds or settings.skill_runner_timeout_seconds,
    }
    timeout = (
        settings.skill_runner_queue_wait_seconds
        + (timeout_seconds or settings.skill_runner_timeout_seconds)
        + 15
    )
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            f"{settings.skill_runner_url.rstrip('/')}/execute-builtin",
            json=payload,
            headers=_headers(),
        )
        if response.is_error:
            try:
                detail = response.json().get("detail")
            except (ValueError, AttributeError):
                detail = response.text
            raise RuntimeError(str(detail or f"Runner builtin execution failed ({response.status_code})"))
    return response.json(), int((time.perf_counter() - started) * 1000)
