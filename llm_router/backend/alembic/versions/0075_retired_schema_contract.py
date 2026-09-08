"""Create the post-0075 AI Platform schema from a static PostgreSQL baseline.

Revision ID: 0075_retired_schema_contract
Revises: None
Create Date: 2026-09-09

Existing databases already stamped at this revision execute no migration. New
installations execute the adjacent, checksummed SQL captured from the audited
0001-to-0075 migration result. The SQL is intentionally independent from the
runtime ORM so a future model change cannot rewrite historical installation
semantics.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from alembic import context, op

revision = "0075_retired_schema_contract"
down_revision = None
branch_labels = None
depends_on = None

_BASELINE_FILE = Path(__file__).with_name("0075_schema_baseline.sql")
_BASELINE_SHA256 = "e2cc9449c01eb17fb64987d5202498365962578889a73cfc195f7512e06d92a3"
_REQUIRED_MARKERS = (
    "CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public VERSION '0.8.2'",
    "CREATE FUNCTION public.reject_ai_quota_event_mutation()",
    "CREATE MATERIALIZED VIEW public.ai_quota_monthly_rollups AS",
    "CREATE TRIGGER trg_ai_quota_events_append_only",
)


def _load_verified_baseline() -> str:
    payload = _BASELINE_FILE.read_bytes()
    actual_sha256 = hashlib.sha256(payload).hexdigest()
    if actual_sha256 != _BASELINE_SHA256:
        raise RuntimeError(
            "0075 schema baseline checksum mismatch: "
            f"expected {_BASELINE_SHA256}, got {actual_sha256}"
        )
    sql = payload.decode("utf-8")
    missing = [marker for marker in _REQUIRED_MARKERS if marker not in sql]
    if missing:
        raise RuntimeError(f"0075 schema baseline is incomplete: missing {missing!r}")
    return sql


def upgrade() -> None:
    if context.is_offline_mode():
        raise RuntimeError("0075 静态基线必须连接 PostgreSQL 在线执行，不能生成离线 SQL")

    sql = _load_verified_baseline()
    adapted_connection = op.get_bind().connection
    run_async = getattr(adapted_connection, "run_async", None)
    if run_async is None:
        raise RuntimeError("0075 静态基线要求使用 asyncpg Alembic 连接")
    run_async(lambda driver_connection: driver_connection.execute(sql))


def downgrade() -> None:
    raise RuntimeError("0075 是不可逆的新安装基线；请恢复数据库快照和匹配镜像")
