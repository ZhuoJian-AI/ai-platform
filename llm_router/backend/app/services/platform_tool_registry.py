"""Release-aware metadata registry for platform-maintained model tools."""

from __future__ import annotations

from sqlalchemy import select

from app.models.platform_extension import PlatformExtensionRelease
from app.services.platform_extension_catalog import SYSTEM_TOOL_GROUPS


def platform_managed_tool_names() -> set[str]:
    """Names controlled by the platform release manifest.

    Dynamic enterprise endpoint names are deliberately excluded: their
    existing tenant authorization and connector lifecycle remain unchanged.
    """
    return {
        str(name)
        for group in SYSTEM_TOOL_GROUPS
        for name in (group.get("tools") or [])
    }


async def active_platform_tool_names(db) -> set[str] | None:
    """Return enabled built-in tool names, or None before baseline migration.

    This filters only platform-maintained built-ins. User Skills, RAG bindings
    and enterprise connectors keep their existing authorization paths.
    """
    release = (
        await db.execute(select(PlatformExtensionRelease).where(PlatformExtensionRelease.is_active.is_(True)))
    ).scalar_one_or_none()
    if not release:
        return None
    names: set[str] = set()
    for group in (release.manifest or {}).get("system_tools") or []:
        if group.get("enabled", True):
            names.update(str(value) for value in (group.get("tools") or []))
    return names


async def active_external_tool_defs(
    db,
    *,
    organization_id: str,
    user_role: str | None,
    exec_mode: str,
) -> list[dict]:
    """Return approved Node tool schemas after run-level scope filtering.

    Execution remains inside DSH, but a handler is callable only when this
    function includes its schema in the current run request.
    """
    release = (
        await db.execute(select(PlatformExtensionRelease).where(PlatformExtensionRelease.is_active.is_(True)))
    ).scalar_one_or_none()
    if not release:
        return []
    definitions: list[dict] = []
    for extension in (release.manifest or {}).get("external_extensions") or []:
        if extension.get("enabled", True) is False or extension.get("type") != "system_tool":
            continue
        for tool in extension.get("tools") or []:
            modes = set(tool.get("allowed_modes") or ["craft"])
            organizations = set(str(value) for value in (tool.get("allowed_organization_ids") or []))
            roles = set(str(value) for value in (tool.get("required_user_roles") or []))
            if exec_mode not in modes:
                continue
            if organizations and organization_id not in organizations:
                continue
            if roles and (user_role or "") not in roles:
                continue
            definitions.append(
                {
                    "type": "function",
                    "function": {
                        "name": str(tool["name"]),
                        "description": str(tool.get("description") or "平台审核的外部系统工具"),
                        "parameters": tool.get("input_schema")
                        or {
                            "type": "object",
                            "properties": {},
                            "additionalProperties": False,
                        },
                    },
                }
            )
    return definitions
