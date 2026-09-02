"""Repackage a legacy Agent Skill ZIP without importing or activating it."""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.tools.agent_skill_packager import repackage_agent_skill  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_zip", type=Path)
    parser.add_argument("output_zip", type=Path)
    parser.add_argument("--source", default="process_bank_statement.py")
    parser.add_argument("--target", default="scripts/process_bank_statement.py")
    parser.add_argument(
        "--drop",
        action="append",
        default=[],
        help="Exact package path to omit; repeat for multiple files.",
    )
    args = parser.parse_args()

    repaired = repackage_agent_skill(
        args.input_zip.read_bytes(),
        source_script=args.source,
        target_script=args.target,
        drop_paths=tuple(args.drop),
    )
    args.output_zip.parent.mkdir(parents=True, exist_ok=True)
    args.output_zip.write_bytes(repaired)
    print(f"output={args.output_zip.resolve()}")
    print(f"sha256={hashlib.sha256(repaired).hexdigest()}")


if __name__ == "__main__":
    main()
