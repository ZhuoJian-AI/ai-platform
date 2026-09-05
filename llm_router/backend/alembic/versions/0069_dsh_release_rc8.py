"""Move stored platform extension release manifests from DSH 0.1.0-rc.5 to 0.1.0-rc.8.

Revision ID: 0069_dsh_release_rc8
Revises: 0068_ai_quota_rollups
Create Date: 2026-09-06

Release rows are immutable snapshots, so after the vendored DeepSeek Harness moved from
rc.5 to rc.8 every ``platform_extension_releases.manifest`` still names ``dsh_version:
0.1.0-rc.5`` and the rc.8 runtime (``dsh_runtime/src/extensions.ts::verifyRelease``) refuses
to activate them.  The backend also self-heals the *active* row at startup
(``app/services/platform_extension_service.py::heal_active_release_version``); this one-off
data migration additionally repairs history rows so rollback targets stay activatable.

Scope: rows whose manifest contains only platform-baseline items (core ``dsh-*`` plugins and
platform tool groups, no enabled external extension).  Rows with external extensions are
left to the service, which checks each extension's own DSH requirement.

Idempotent: only rows naming rc.5 are touched.  Reversible: every rewritten row gets a
``dsh_version_migrated`` event carrying this revision id; ``downgrade`` finds those events,
restores rc.5 plus the previous checksum, and removes its own marker events.
"""

from __future__ import annotations

import hashlib
import json

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0069_dsh_release_rc8"
down_revision = "0068_ai_quota_rollups"
branch_labels = None
depends_on = None

OLD_DSH_VERSION = "0.1.0-rc.5"
NEW_DSH_VERSION = "0.1.0-rc.8"
EVENT_TYPE = "dsh_version_migrated"

# Platform-baseline item slugs as of rc.8 (``platform_extension_catalog.py``).  The rc.5
# baseline used a subset of the plugin slugs, so subset membership is the right test.
BASELINE_PLUGIN_SLUGS = frozenset(
    {
        "dsh-llm-runtime",
        "dsh-session",
        "dsh-system-prompt",
        "dsh-tools",
        "dsh-agent",
        "dsh-agent-loop",
        "dsh-invariants",
        "dsh-timeout",
        "dsh-user-approval",
        "dsh-session-persistence-jsonl",
        "dsh-code-runtime-worker-thread",
        "dsh-repeat-tool-reminder",
        "dsh-tool-call-timeout-policy",
    }
)
BASELINE_TOOL_GROUP_SLUGS = frozenset(
    {
        "workspace-files",
        "office-documents",
        "media",
        "archives",
        "web",
        "rag",
        "agent-skills",
        "enterprise-connectors",
    }
)


def _canonical_value(value):
    # Replicates app/services/platform_extension_service.py::_canonical_value.
    if isinstance(value, dict):
        return {key: _canonical_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_canonical_value(item) for item in value]
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _checksum(manifest: dict) -> str:
    # Replicates app/services/platform_extension_service.py::manifest_checksum byte for byte;
    # the Node runtime hashes the same canonical form (extensions.ts::stable).
    raw = json.dumps(
        _canonical_value(manifest),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(raw).hexdigest()


def _pure_baseline_items(manifest: dict, *, from_version: str, to_version: str) -> bool:
    """True when every item is a platform-baseline item of a known version."""
    for item in manifest.get("plugins") or []:
        if not isinstance(item, dict) or item.get("slug") not in BASELINE_PLUGIN_SLUGS:
            return False
        if item.get("version") not in {from_version, to_version}:
            return False
    for item in manifest.get("system_tools") or []:
        if not isinstance(item, dict) or item.get("slug") not in BASELINE_TOOL_GROUP_SLUGS:
            return False
    for item in manifest.get("external_extensions") or []:
        if not isinstance(item, dict) or item.get("enabled", True) is not False:
            return False
    return True


def _rewrite(manifest: dict, *, from_version: str, to_version: str) -> dict:
    """Same transformation as platform_extension_versioning.rewrite_manifest_dsh_version."""
    copy = json.loads(json.dumps(manifest))
    copy["dsh_version"] = to_version
    for item in copy.get("plugins") or []:
        if isinstance(item, dict) and item.get("version") == from_version and item.get("slug") in BASELINE_PLUGIN_SLUGS:
            item["version"] = to_version
    return copy


def _load(value):
    return json.loads(value) if isinstance(value, str) else value


_SELECT_BY_VERSION = sa.text(
    "SELECT id, checksum, manifest FROM platform_extension_releases "
    "WHERE manifest->>'dsh_version' = :version ORDER BY version_no"
)
_UPDATE_RELEASE = sa.text(
    "UPDATE platform_extension_releases SET manifest = :manifest, checksum = :checksum, updated_at = now() "
    "WHERE id = :id"
).bindparams(sa.bindparam("manifest", type_=postgresql.JSONB()))
_INSERT_EVENT = sa.text(
    "INSERT INTO platform_extension_release_events (release_id, event_type, status, details) "
    "VALUES (:release_id, :event_type, 'ok', :details)"
).bindparams(sa.bindparam("details", type_=postgresql.JSONB()))
_SELECT_EVENTS = sa.text(
    "SELECT id, release_id, details FROM platform_extension_release_events "
    "WHERE event_type = :event_type AND details->>'revision' = :revision ORDER BY id"
)
_SELECT_RELEASE = sa.text("SELECT checksum, manifest FROM platform_extension_releases WHERE id = :id")
_DELETE_EVENT = sa.text("DELETE FROM platform_extension_release_events WHERE id = :id")


def upgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(_SELECT_BY_VERSION, {"version": OLD_DSH_VERSION}).mappings().all()
    for row in rows:
        manifest = _load(row["manifest"])
        if not _pure_baseline_items(manifest, from_version=OLD_DSH_VERSION, to_version=NEW_DSH_VERSION):
            continue
        rewritten = _rewrite(manifest, from_version=OLD_DSH_VERSION, to_version=NEW_DSH_VERSION)
        checksum = _checksum(rewritten)
        bind.execute(_UPDATE_RELEASE, {"id": row["id"], "manifest": rewritten, "checksum": checksum})
        bind.execute(
            _INSERT_EVENT,
            {
                "release_id": row["id"],
                "event_type": EVENT_TYPE,
                "details": {
                    "revision": revision,
                    "from_dsh_version": OLD_DSH_VERSION,
                    "to_dsh_version": NEW_DSH_VERSION,
                    "previous_checksum": row["checksum"],
                    "checksum": checksum,
                },
            },
        )


def downgrade() -> None:
    bind = op.get_bind()
    events = bind.execute(_SELECT_EVENTS, {"event_type": EVENT_TYPE, "revision": revision}).mappings().all()
    for event in events:
        release = bind.execute(_SELECT_RELEASE, {"id": event["release_id"]}).mappings().first()
        if release is not None:
            manifest = _load(release["manifest"])
            if manifest.get("dsh_version") == NEW_DSH_VERSION:
                restored = _rewrite(manifest, from_version=NEW_DSH_VERSION, to_version=OLD_DSH_VERSION)
                bind.execute(
                    _UPDATE_RELEASE,
                    {"id": event["release_id"], "manifest": restored, "checksum": _checksum(restored)},
                )
        # The marker rows belong to this revision, not to an admin action; removing them keeps
        # a later re-upgrade from double-recording.
        bind.execute(_DELETE_EVENT, {"id": event["id"]})
