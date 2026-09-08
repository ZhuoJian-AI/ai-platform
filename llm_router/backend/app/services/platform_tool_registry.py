"""Compatibility facade for the native Assistant Core tool catalog."""

from __future__ import annotations

from app.services.assistant_tool_catalog import platform_managed_tool_names


async def active_platform_tool_names(db) -> set[str] | None:
    """Return platform-owned tools without consulting retired release tables."""

    del db
    return platform_managed_tool_names()


async def active_external_tool_defs(
    db,
    *,
    organization_id: str,
    user_role: str | None,
    exec_mode: str,
) -> list[dict]:
    """External DSH extensions are retired and are never injected."""

    del db, organization_id, user_role, exec_mode
    return []
