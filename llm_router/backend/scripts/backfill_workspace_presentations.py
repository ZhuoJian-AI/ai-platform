"""Backfill friendly workspace file metadata without renaming stored objects."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import async_session_factory  # noqa: E402
from app.services.workspace_presentation_backfill import backfill_workspace_presentations  # noqa: E402


async def main(*, dry_run: bool) -> None:
    async with async_session_factory() as db:
        result = await backfill_workspace_presentations(db, dry_run=dry_run)
        if dry_run:
            await db.rollback()
        else:
            await db.commit()
        print(json.dumps({**result, "dry_run": dry_run}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(dry_run=args.dry_run))
