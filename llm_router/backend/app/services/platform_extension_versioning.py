"""DB-free rules for keeping release manifests on the DSH version this backend ships.

The DSH runtime (``dsh_runtime/src/extensions.ts::verifyRelease``) refuses to activate a
release whose ``manifest.dsh_version`` differs from its own ``DSH_VERSION``.  Release rows
are immutable snapshots, so after a DSH upgrade every stored manifest still names the old
version and the runtime silently stays on its built-in baseline.  This module decides how
such a row is brought forward; ``platform_extension_service`` applies the decision.

Two modes:

* ``baseline_regenerated`` – the active row is the platform-generated baseline
  (``validation_report.status == "baseline"``, never customised).  Its content is a pure
  function of the catalog, so it is regenerated from ``baseline_manifest()``.
* ``version_rewritten`` – the active row is a custom release.  Only ``dsh_version`` (and the
  core plugin ``version`` fields that mirror it) are rewritten, and only when every item in
  the manifest is still compatible with the current catalog / DSH version.  Otherwise the
  row is left untouched and the caller logs a warning naming it.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from app.services.platform_extension_catalog import (
    CORE_PLUGINS,
    DSH_VERSION,
    SYSTEM_TOOL_GROUPS,
    baseline_manifest,
)

BASELINE_RELEASE_NAME = "平台基线"
BASELINE_VALIDATION_STATUS = "baseline"
HEALED_VALIDATION_STATUS = "healed"

MODE_BASELINE_REGENERATED = "baseline_regenerated"
MODE_VERSION_REWRITTEN = "version_rewritten"


def manifest_dsh_version(manifest: dict | None) -> str | None:
    value = (manifest or {}).get("dsh_version")
    return str(value) if value else None


def needs_dsh_version_heal(manifest: dict | None, *, current: str = DSH_VERSION) -> bool:
    """True when the runtime would reject this manifest for naming another DSH version."""
    return manifest_dsh_version(manifest) != current


def _enabled_external_extensions(manifest: dict | None) -> list[dict]:
    return [
        item
        for item in (manifest or {}).get("external_extensions") or []
        if isinstance(item, dict) and item.get("enabled", True) is not False
    ]


def is_platform_baseline_release(*, validation_report: dict | None, manifest: dict | None) -> bool:
    """Identify the row ``ensure_baseline`` (or a previous heal) generated from the catalog.

    The marker is ``validation_report.status == "baseline"``: only the platform writes it and
    ``validate_release`` / ``publish_release`` overwrite the report for every admin-made
    candidate, so a customised release never carries it.  A baseline also never contains
    enabled external extensions; that is checked defensively so a hand-edited row is treated
    as custom rather than regenerated (which would drop its extensions).
    """
    status = (validation_report or {}).get("status")
    return status == BASELINE_VALIDATION_STATUS and not _enabled_external_extensions(manifest)


# ── node-semver subset for ``dsh_version`` requirements of external extensions ────────────
#
# The extension builder validates ``ai-platform.extension.json::dsh_version`` with node's
# ``semver.satisfies(version, range, { includePrerelease: true })`` and stores the raw
# requirement on the item (``dsh_version`` / ``runtime_requirements.dsh``).  Re-checking it
# here needs only the operators those manifests realistically use.

_SEMVER_RE = re.compile(
    r"^v?(?P<major>\d+|[xX*])(?:\.(?P<minor>\d+|[xX*]))?(?:\.(?P<patch>\d+|[xX*]))?"
    r"(?:-(?P<pre>[0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?$"
)


def _parse_semver(text: str) -> tuple[list[int | None], list[str]] | None:
    match = _SEMVER_RE.match(text.strip())
    if not match:
        return None
    parts: list[int | None] = []
    for key in ("major", "minor", "patch"):
        raw = match.group(key)
        parts.append(None if raw is None or raw in {"x", "X", "*"} else int(raw))
    pre = match.group("pre")
    return parts, (pre.split(".") if pre else [])


def _semver_key(version: str) -> tuple:
    parsed = _parse_semver(version)
    if parsed is None:
        raise ValueError(f"invalid semver: {version!r}")
    parts, pre = parsed
    numbers = tuple(part or 0 for part in parts)
    if not pre:
        # A release sorts after every pre-release of the same triple.
        return (*numbers, 1, ())
    identifiers = tuple(
        (0, int(item), "") if item.isdigit() else (1, 0, item)
        for item in pre
    )
    return (*numbers, 0, identifiers)


def _comparator_accepts(comparator: str, version_key: tuple) -> bool:
    comparator = comparator.strip()
    if comparator in {"", "*", "x", "X"}:
        return True
    match = re.match(r"^(>=|<=|>|<|=|\^|~)?\s*(.+)$", comparator)
    if not match:
        return False
    operator, operand = match.group(1) or "=", match.group(2).strip()
    parsed = _parse_semver(operand)
    if parsed is None:
        return False
    (major, minor, patch), pre = parsed
    major = major or 0
    lower_key = _semver_key(f"{major}.{minor or 0}.{patch or 0}" + (f"-{'.'.join(pre)}" if pre else ""))
    # ``upper`` is the exclusive bound of the range an operand denotes; ``None`` means the
    # operand is one exact version.  ``X.Y.Z-0`` is the lowest pre-release of X.Y.Z, so a
    # pre-release of the next minor/major never slips into the range (node semver does the same).
    upper: tuple[int, int, int] | None
    if operator == "^":
        if major > 0:
            upper = (major + 1, 0, 0)
        elif minor is None:
            upper = (1, 0, 0)
        elif minor > 0 or patch is None:
            upper = (0, minor + 1, 0)
        else:
            upper = (0, 0, patch + 1)
    elif operator == "~" or minor is None or patch is None:
        upper = (major + 1, 0, 0) if minor is None else (major, minor + 1, 0)
    else:
        upper = None
    if upper is None:
        return {
            "=": version_key == lower_key,
            ">=": version_key >= lower_key,
            ">": version_key > lower_key,
            "<=": version_key <= lower_key,
            "<": version_key < lower_key,
        }.get(operator, False)
    upper_key = _semver_key(f"{upper[0]}.{upper[1]}.{upper[2]}-0")
    return {
        "=": lower_key <= version_key < upper_key,
        "^": lower_key <= version_key < upper_key,
        "~": lower_key <= version_key < upper_key,
        ">=": version_key >= lower_key,
        ">": version_key >= upper_key,
        "<=": version_key < upper_key,
        "<": version_key < lower_key,
    }.get(operator, False)


def dsh_requirement_accepts(requirement: Any, version: str = DSH_VERSION) -> bool:
    """Evaluate a node-semver requirement the way the builder did (``includePrerelease``).

    Supports exact versions, comparators (``>= > <= < =``), ``^``, ``~``, ``x``/``*``
    wildcards, whitespace-joined AND sets, hyphen ranges and ``||`` alternatives.  An empty
    requirement accepts everything; anything unparsable is rejected, matching
    ``compatibleDsh`` in ``extension_builder/src/builder.ts``.
    """
    if requirement is None:
        return True
    text = str(requirement).strip()
    if not text:
        return True
    try:
        version_key = _semver_key(version)
    except ValueError:
        return False
    for alternative in text.split("||"):
        alternative = alternative.strip()
        hyphen = re.match(r"^(\S+)\s+-\s+(\S+)$", alternative)
        if hyphen:
            comparators = [f">={hyphen.group(1)}", f"<={hyphen.group(2)}"]
        else:
            comparators = alternative.split() or [""]
        if all(_comparator_accepts(item, version_key) for item in comparators):
            return True
    return False


# ── compatibility and rewrite ────────────────────────────────────────────────────────────


def manifest_compatibility_problems(manifest: dict | None, *, current: str = DSH_VERSION) -> list[str]:
    """Reasons a custom manifest cannot simply be re-versioned; empty means compatible.

    A core plugin is compatible when its slug is still in the catalog and its ``version`` is
    either the manifest's own ``dsh_version`` (it will be bumped together with it) or already
    the current version.  System tool groups must still exist.  Enabled external extensions
    must have a ``dsh_version`` requirement that accepts the current DSH version.
    """
    manifest = manifest or {}
    old_version = manifest_dsh_version(manifest)
    catalog_plugins = {item["slug"]: item for item in CORE_PLUGINS}
    catalog_groups = {item["slug"] for item in SYSTEM_TOOL_GROUPS}
    problems: list[str] = []
    for item in manifest.get("plugins") or []:
        slug = str(item.get("slug"))
        catalog_item = catalog_plugins.get(slug)
        if catalog_item is None:
            problems.append(f"plugin {slug} is not in the current catalog")
            continue
        version = item.get("version")
        if version not in {old_version, current, catalog_item["version"]}:
            problems.append(f"plugin {slug} version {version} is neither {old_version} nor {current}")
    for item in manifest.get("system_tools") or []:
        slug = str(item.get("slug"))
        if slug not in catalog_groups:
            problems.append(f"system tool group {slug} is not in the current catalog")
    for item in _enabled_external_extensions(manifest):
        requirement = item.get("dsh_version") or (item.get("runtime_requirements") or {}).get("dsh")
        if not dsh_requirement_accepts(requirement, current):
            problems.append(
                f"extension {item.get('slug')} requires DSH {requirement}, which does not accept {current}"
            )
    return problems


def rewrite_manifest_dsh_version(manifest: dict | None, *, current: str = DSH_VERSION) -> dict:
    """Return a deep copy naming ``current``; core plugin versions that mirrored the old value follow.

    Nothing else changes: external extensions, tool group states, ``release_config`` and
    ``replacement_slots`` are preserved verbatim.  Idempotent.
    """
    copy = json.loads(json.dumps(manifest or {}))
    old_version = manifest_dsh_version(copy)
    copy["dsh_version"] = current
    catalog_plugins = {item["slug"]: item for item in CORE_PLUGINS}
    for item in copy.get("plugins") or []:
        if not isinstance(item, dict):
            continue
        if old_version is not None and item.get("version") == old_version and item.get("slug") in catalog_plugins:
            item["version"] = current
    return copy


@dataclass(frozen=True)
class ReleaseVersionHealPlan:
    """What the service must persist to bring a stale active release forward."""

    mode: str
    name: str
    manifest: dict
    validation_report: dict
    from_dsh_version: str | None
    to_dsh_version: str


@dataclass(frozen=True)
class ReleaseVersionHealRefusal:
    """A custom release that must not be rewritten; ``reasons`` explain why."""

    from_dsh_version: str | None
    to_dsh_version: str
    reasons: list[str] = field(default_factory=list)


def plan_release_version_heal(
    *,
    name: str,
    validation_report: dict | None,
    manifest: dict | None,
    current: str = DSH_VERSION,
) -> ReleaseVersionHealPlan | ReleaseVersionHealRefusal | None:
    """Decide how (or whether) an active release moves to ``current``.

    ``None`` means the release already names the current version.
    """
    if not needs_dsh_version_heal(manifest, current=current):
        return None
    old_version = manifest_dsh_version(manifest)
    if is_platform_baseline_release(validation_report=validation_report, manifest=manifest):
        regenerated = baseline_manifest()
        regenerated["dsh_version"] = current
        return ReleaseVersionHealPlan(
            mode=MODE_BASELINE_REGENERATED,
            name=BASELINE_RELEASE_NAME,
            manifest=regenerated,
            validation_report={
                "status": BASELINE_VALIDATION_STATUS,
                "migrated_without_behavior_change": True,
                "healed_from": {"dsh_version": old_version},
            },
            from_dsh_version=old_version,
            to_dsh_version=current,
        )
    reasons = manifest_compatibility_problems(manifest, current=current)
    if reasons:
        return ReleaseVersionHealRefusal(from_dsh_version=old_version, to_dsh_version=current, reasons=reasons)
    return ReleaseVersionHealPlan(
        mode=MODE_VERSION_REWRITTEN,
        name=name,
        manifest=rewrite_manifest_dsh_version(manifest, current=current),
        validation_report={
            "status": HEALED_VALIDATION_STATUS,
            "migrated_without_behavior_change": True,
            "healed_from": {"dsh_version": old_version},
        },
        from_dsh_version=old_version,
        to_dsh_version=current,
    )
