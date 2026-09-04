"""Interactively create the one and only first platform administrator."""

from __future__ import annotations

import argparse
import asyncio
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import async_session_factory  # noqa: E402
from app.services.admin_service import bootstrap_platform_admin  # noqa: E402


async def _run(username: str) -> None:
    password = getpass.getpass("Initial password (at least 12 characters): ")
    confirmation = getpass.getpass("Repeat password: ")
    if password != confirmation:
        raise SystemExit("Passwords do not match")
    async with async_session_factory() as db:
        admin = await bootstrap_platform_admin(db, username=username, password=password)
        await db.commit()
        print(f"Created platform administrator: {admin.username}")
        print("Sign in and change the temporary password immediately.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Create a platform administrator only when none is active. "
            "This is also the local recovery path after a legacy migration."
        )
    )
    parser.add_argument("--username", required=True, help="Initial platform administrator username")
    args = parser.parse_args()
    asyncio.run(_run(args.username))


if __name__ == "__main__":
    main()
