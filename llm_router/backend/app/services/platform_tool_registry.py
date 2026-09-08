"""Compatibility facade for the native Assistant Core tool catalog."""

from __future__ import annotations

from app.services.assistant_tool_catalog import platform_managed_tool_names


async def active_platform_tool_names(db) -> set[str] | None:
    """Return the platform-owned Assistant Core tools."""

    del db
    return platform_managed_tool_names()
