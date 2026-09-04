"""Refresh monthly quota rollups and alert before the immutable ledger fills disk."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import settings


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--refresh-rollups",
        action="store_true",
        help="Refresh ai_quota_monthly_rollups before measuring capacity.",
    )
    parser.add_argument(
        "--warn-gib",
        type=float,
        default=20.0,
        help="Exit 2 when the fact table plus indexes reaches this many GiB.",
    )
    parser.add_argument(
        "--warn-rows",
        type=int,
        default=50_000_000,
        help="Exit 2 when the immutable fact ledger reaches this row count.",
    )
    return parser


async def inspect_capacity(*, refresh_rollups: bool) -> dict[str, Any]:
    engine = create_async_engine(str(settings.database_url), pool_pre_ping=True)
    try:
        async with engine.begin() as connection:
            if refresh_rollups:
                await connection.execute(
                    text("REFRESH MATERIALIZED VIEW ai_quota_monthly_rollups")
                )
            row = (
                await connection.execute(
                    text(
                        """
                        SELECT
                            COUNT(*)::bigint AS row_count,
                            pg_total_relation_size('ai_quota_events')::bigint AS total_bytes,
                            MIN(created_at) AS oldest_event,
                            MAX(created_at) AS newest_event
                        FROM ai_quota_events
                        """
                    )
                )
            ).mappings().one()
            closed_months = int(
                (
                    await connection.execute(
                        text(
                            """
                            SELECT COUNT(DISTINCT period_month)::bigint
                            FROM ai_quota_monthly_rollups
                            WHERE period_month < date_trunc('month', now() AT TIME ZONE 'UTC')::date
                            """
                        )
                    )
                ).scalar_one()
                or 0
            )
        return {
            "row_count": int(row["row_count"] or 0),
            "total_bytes": int(row["total_bytes"] or 0),
            "oldest_event": row["oldest_event"].isoformat() if row["oldest_event"] else None,
            "newest_event": row["newest_event"].isoformat() if row["newest_event"] else None,
            "closed_months_in_rollup": closed_months,
            "rollups_refreshed": refresh_rollups,
        }
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.warn_gib <= 0 or args.warn_rows <= 0:
        raise SystemExit("warning thresholds must be positive")
    report = asyncio.run(inspect_capacity(refresh_rollups=args.refresh_rollups))
    report["warning"] = (
        report["total_bytes"] >= int(args.warn_gib * 1024**3)
        or report["row_count"] >= args.warn_rows
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["warning"]:
        print(
            "AI quota ledger capacity threshold exceeded; expand storage and review retention policy.",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
