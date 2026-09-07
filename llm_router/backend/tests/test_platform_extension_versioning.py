"""DB-free contracts for keeping release manifests on the platform's DSH version.

Covers the heal decision (``plan_release_version_heal``), the manifest rewrite, the external
extension requirement check and byte-for-byte parity between the service's checksum /
rewrite and the inline copies in alembic revision ``0069_dsh_release_rc8``.
"""

import importlib.util
import json
import pathlib

import pytest

from app.services import platform_extension_service as service
from app.services.platform_extension_catalog import CORE_PLUGINS, DSH_VERSION, baseline_manifest
from app.services.platform_extension_versioning import (
    BASELINE_RELEASE_NAME,
    MODE_BASELINE_REGENERATED,
    MODE_VERSION_REWRITTEN,
    ReleaseVersionHealPlan,
    ReleaseVersionHealRefusal,
    dsh_requirement_accepts,
    is_platform_baseline_release,
    manifest_compatibility_problems,
    needs_dsh_version_heal,
    plan_release_version_heal,
    rewrite_manifest_dsh_version,
)

OLD = "0.1.0-rc.5"
RC8_ONLY_SLUGS = {
    "dsh-session-persistence-jsonl",
    "dsh-code-runtime-worker-thread",
    "dsh-repeat-tool-reminder",
    "dsh-tool-call-timeout-policy",
}
BASELINE_REPORT = {"status": "baseline", "migrated_without_behavior_change": True}


@pytest.fixture(autouse=True)
def db_engine():
    """Pure decision logic; the PostgreSQL fixture is not needed."""
    yield


def _rc5_baseline() -> dict:
    """The baseline row an rc.5 deployment created: no rc.8-only providers, rc.5 everywhere."""
    manifest = baseline_manifest()
    manifest["dsh_version"] = OLD
    manifest["plugins"] = [
        {**item, "version": OLD} for item in manifest["plugins"] if item["slug"] not in RC8_ONLY_SLUGS
    ]
    return manifest


def _rc5_custom(external_requirement: str | None = ">=0.1.0-rc.5 <0.2.0") -> dict:
    """A published rc.5 candidate: web group off, one reviewed system tool installed."""
    manifest = _rc5_baseline()
    for group in manifest["system_tools"]:
        if group["slug"] == "web":
            group["enabled"] = False
    manifest["external_extensions"] = [
        {
            "slug": "reviewed-lookup",
            "name": "Reviewed Lookup",
            "version": "1.0.0",
            "type": "system_tool",
            "entry": "dist/index.js",
            "enabled": True,
            "source_id": "11111111-1111-1111-1111-111111111111",
            "artifact_ref": "oss://platform-extensions/reviewed.tar.gz",
            "artifact_sha256": "a" * 64,
            "dsh_version": external_requirement,
            "runtime_requirements": {"node": None, "dsh": external_requirement},
            "tools": [{"name": "reviewed_lookup"}],
        }
    ]
    manifest["replacement_slots"] = {}
    manifest["release_config"] = {"disabled_tool_groups": ["web"], "lifecycle_action": "install"}
    return manifest


# ── constants and detection ──────────────────────────────────────────────────────────────


def test_baseline_manifest_and_catalog_use_the_single_dsh_constant():
    manifest = baseline_manifest()
    assert manifest["dsh_version"] == DSH_VERSION
    assert {item["version"] for item in manifest["plugins"]} == {DSH_VERSION}
    assert {item["version"] for item in CORE_PLUGINS} == {DSH_VERSION}
    assert not needs_dsh_version_heal(manifest)


@pytest.mark.parametrize(
    ("manifest", "expected"),
    [
        ({"dsh_version": OLD}, True),
        ({"dsh_version": DSH_VERSION}, False),
        ({}, True),
        (None, True),
    ],
)
def test_needs_heal_compares_against_the_platform_constant(manifest, expected):
    assert needs_dsh_version_heal(manifest) is expected


def test_platform_baseline_is_identified_by_report_marker_and_no_extensions():
    assert is_platform_baseline_release(validation_report=BASELINE_REPORT, manifest=_rc5_baseline())
    assert not is_platform_baseline_release(validation_report={"ok": True}, manifest=_rc5_baseline())
    assert not is_platform_baseline_release(validation_report=None, manifest=_rc5_baseline())
    # A hand-edited baseline row carrying enabled extensions must be treated as custom.
    assert not is_platform_baseline_release(validation_report=BASELINE_REPORT, manifest=_rc5_custom())
    disabled = _rc5_custom()
    disabled["external_extensions"][0]["enabled"] = False
    assert is_platform_baseline_release(validation_report=BASELINE_REPORT, manifest=disabled)


# ── heal plan ────────────────────────────────────────────────────────────────────────────


def test_plan_is_none_when_release_already_names_current_version():
    assert plan_release_version_heal(name="x", validation_report=BASELINE_REPORT, manifest=baseline_manifest()) is None
    current_custom = rewrite_manifest_dsh_version(_rc5_custom())
    assert plan_release_version_heal(name="x", validation_report={}, manifest=current_custom) is None


def test_plan_regenerates_the_platform_baseline_from_the_catalog():
    plan = plan_release_version_heal(
        name=BASELINE_RELEASE_NAME, validation_report=BASELINE_REPORT, manifest=_rc5_baseline()
    )
    assert isinstance(plan, ReleaseVersionHealPlan)
    assert plan.mode == MODE_BASELINE_REGENERATED
    assert plan.name == BASELINE_RELEASE_NAME
    assert plan.manifest == baseline_manifest()
    assert {item["slug"] for item in plan.manifest["plugins"]} >= RC8_ONLY_SLUGS
    assert plan.validation_report["status"] == "baseline"
    assert plan.validation_report["healed_from"] == {"dsh_version": OLD}
    assert (plan.from_dsh_version, plan.to_dsh_version) == (OLD, DSH_VERSION)
    assert service.manifest_checksum(plan.manifest) != service.manifest_checksum(_rc5_baseline())


def test_plan_rewrites_only_the_version_of_a_compatible_custom_release():
    stale = _rc5_custom()
    plan = plan_release_version_heal(
        name="安装系统工具：Reviewed Lookup", validation_report={"ok": True}, manifest=stale
    )
    assert isinstance(plan, ReleaseVersionHealPlan)
    assert plan.mode == MODE_VERSION_REWRITTEN
    assert plan.name == "安装系统工具：Reviewed Lookup"
    assert plan.manifest["dsh_version"] == DSH_VERSION
    assert {item["version"] for item in plan.manifest["plugins"]} == {DSH_VERSION}
    # Everything that is not the DSH version survives verbatim.
    assert plan.manifest["external_extensions"] == stale["external_extensions"]
    assert plan.manifest["release_config"] == stale["release_config"]
    assert plan.manifest["replacement_slots"] == stale["replacement_slots"]
    assert next(g for g in plan.manifest["system_tools"] if g["slug"] == "web")["enabled"] is False
    assert {item["slug"] for item in plan.manifest["plugins"]} == {item["slug"] for item in stale["plugins"]}
    assert plan.validation_report["status"] == "healed"


def test_plan_refuses_a_custom_release_whose_extension_pins_the_old_dsh_version():
    plan = plan_release_version_heal(name="pinned", validation_report={"ok": True}, manifest=_rc5_custom(OLD))
    assert isinstance(plan, ReleaseVersionHealRefusal)
    assert plan.from_dsh_version == OLD and plan.to_dsh_version == DSH_VERSION
    assert len(plan.reasons) == 1
    assert "reviewed-lookup" in plan.reasons[0] and OLD in plan.reasons[0] and DSH_VERSION in plan.reasons[0]


def test_compatibility_problems_name_unknown_items_and_foreign_versions():
    manifest = _rc5_custom(None)
    manifest["plugins"].append({"slug": "dsh-mystery", "version": OLD, "enabled": True, "capabilities": []})
    manifest["plugins"][0]["version"] = "0.0.9"
    manifest["system_tools"].append({"slug": "shadow-tools", "enabled": True, "tools": []})
    problems = manifest_compatibility_problems(manifest)
    assert any("dsh-mystery" in reason for reason in problems)
    assert any("0.0.9" in reason for reason in problems)
    assert any("shadow-tools" in reason for reason in problems)
    # A null requirement (builder found none) accepts every DSH version.
    assert not any("reviewed-lookup" in reason for reason in problems)
    assert manifest_compatibility_problems(_rc5_custom()) == []
    assert manifest_compatibility_problems(_rc5_baseline()) == []


# ── rewrite ──────────────────────────────────────────────────────────────────────────────


def test_rewrite_is_pure_idempotent_and_only_touches_mirrored_plugin_versions():
    stale = _rc5_custom()
    stale["plugins"].append({"slug": "dsh-timeout", "version": "9.9.9", "kind": "library", "enabled": True})
    snapshot = json.loads(json.dumps(stale))
    rewritten = rewrite_manifest_dsh_version(stale)
    assert stale == snapshot, "input must not be mutated"
    assert rewritten["dsh_version"] == DSH_VERSION
    versions = {item["slug"]: item["version"] for item in rewritten["plugins"]}
    assert versions["dsh-agent-loop"] == DSH_VERSION
    assert versions["dsh-timeout"] in {DSH_VERSION, "9.9.9"}
    assert any(item["version"] == "9.9.9" for item in rewritten["plugins"]), "foreign versions stay"
    assert rewrite_manifest_dsh_version(rewritten) == rewritten
    assert rewrite_manifest_dsh_version(baseline_manifest()) == baseline_manifest()


# ── node-semver subset ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("requirement", "version", "expected"),
    [
        (None, "0.1.0-rc.8", True),
        ("", "0.1.0-rc.8", True),
        ("*", "0.1.0-rc.8", True),
        ("0.1.0-rc.8", "0.1.0-rc.8", True),
        ("0.1.0-rc.5", "0.1.0-rc.8", False),
        ("0.1.0-rc.10", "0.1.0-rc.8", False),
        (">=0.1.0-rc.8", "0.1.0-rc.10", True),
        (">=0.1.0-rc.5 <0.2.0", "0.1.0-rc.8", True),
        (">=0.1.0-rc.9", "0.1.0-rc.8", False),
        ("^0.1.0-rc.5", "0.1.0-rc.8", True),
        ("^0.1.0-rc.5", "0.1.0", True),
        ("^0.1.0-rc.5", "0.2.0", False),
        ("^0.1.0-rc.5", "0.2.0-rc.1", False),
        ("^0.0.3", "0.0.3", True),
        ("^0.0.3", "0.0.4", False),
        ("^1.2.3", "1.9.0", True),
        ("^1.2.3", "2.0.0-0", False),
        ("~0.1.0", "0.1.5", True),
        ("~0.1.0", "0.2.0", False),
        ("0.1.x", "0.1.9", True),
        ("0.1.x", "0.1.0-rc.8", False),  # node: 0.1.x → >=0.1.0, and rc.8 sorts below 0.1.0
        ("0", "0.9.9", True),
        ("1", "0.9.9", False),
        (">0.1", "0.2.0", True),
        (">0.1", "0.1.9", False),
        ("<0.1.0", "0.1.0-rc.8", True),
        ("<=0.1.0-rc.8", "0.1.0-rc.8", True),
        (">0.1.0-rc.7", "0.1.0-rc.8", True),
        ("0.1.0-rc.5 || 0.1.0-rc.8", "0.1.0-rc.8", True),
        ("0.1.0-rc.5 - 0.1.0-rc.9", "0.1.0-rc.8", True),
        ("garbage!!", "0.1.0-rc.8", False),
    ],
)
def test_dsh_requirement_accepts_matches_node_semver_with_prereleases(requirement, version, expected):
    assert dsh_requirement_accepts(requirement, version) is expected


# ── alembic 0069 parity ──────────────────────────────────────────────────────────────────


def _migration():
    path = pathlib.Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0069_dsh_release_rc8.py"
    spec = importlib.util.spec_from_file_location("migration_0069", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_0069_chains_after_0068_and_targets_the_platform_constant():
    migration = _migration()
    assert migration.revision == "0069_dsh_release_rc8"
    assert migration.down_revision == "0068_ai_quota_rollups"
    assert migration.NEW_DSH_VERSION == DSH_VERSION
    assert migration.BASELINE_PLUGIN_SLUGS == {item["slug"] for item in CORE_PLUGINS}
    assert migration.BASELINE_TOOL_GROUP_SLUGS == {item["slug"] for item in baseline_manifest()["system_tools"]}


def test_migration_0069_checksum_and_rewrite_match_the_service():
    migration = _migration()
    samples = [
        baseline_manifest(),
        _rc5_baseline(),
        _rc5_custom(),
        {"dsh_version": OLD, "plugins": [], "system_tools": [], "weights": [1.0, 2.5], "名称": "平台基线"},
    ]
    for manifest in samples:
        assert migration._checksum(manifest) == service.manifest_checksum(manifest)
    stale = _rc5_baseline()
    migrated = migration._rewrite(stale, from_version=OLD, to_version=DSH_VERSION)
    assert migrated == rewrite_manifest_dsh_version(stale)
    assert migration._checksum(migrated) == service.manifest_checksum(rewrite_manifest_dsh_version(stale))
    # downgrade round-trips the rows upgrade touched
    assert migration._rewrite(migrated, from_version=DSH_VERSION, to_version=OLD) == stale


def test_migration_0069_only_touches_pure_baseline_rows():
    migration = _migration()
    check = migration._pure_baseline_items
    assert check(_rc5_baseline(), from_version=OLD, to_version=DSH_VERSION)
    with_config = {**_rc5_baseline(), "release_config": {"disabled_tool_groups": ["web"]}, "replacement_slots": {}}
    assert check(with_config, from_version=OLD, to_version=DSH_VERSION)
    assert not check(_rc5_custom(), from_version=OLD, to_version=DSH_VERSION)
    disabled_external = _rc5_custom()
    disabled_external["external_extensions"][0]["enabled"] = False
    assert check(disabled_external, from_version=OLD, to_version=DSH_VERSION)
    foreign_plugin = _rc5_baseline()
    foreign_plugin["plugins"].append({"slug": "dsh-mystery", "version": OLD})
    assert not check(foreign_plugin, from_version=OLD, to_version=DSH_VERSION)
