"""Regression coverage for repairing executable Agent Skill packages."""

from __future__ import annotations

import io
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from app.services import skill_import_service
from app.tools.agent_skill_packager import repackage_agent_skill


def _legacy_bank_package() -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "bank-skill/SKILL.md",
            """---
name: Bank Statement Processor
description: Process a bank statement workbook
---

Run `process_bank_statement.py` with the input workbook.
""",
        )
        archive.writestr(
            "bank-skill/process_bank_statement.py",
            """from pathlib import Path
import os
import shutil
import sys
import zipfile

input_path = Path(sys.argv[1])
output_path = Path(sys.argv[2])
if not zipfile.is_zipfile(input_path):
    raise ValueError("input is not an XLSX container")
output_path.parent.mkdir(parents=True, exist_ok=True)
shutil.copyfile(input_path, output_path)
(Path(os.environ["SKILL_OUTPUT_DIR"]) / "processing.log").write_text("ok\\n")
""",
        )
        archive.writestr("bank-skill/process_bank_statement.py.backup", "old\n")
        archive.writestr("bank-skill/references/columns.md", "# Columns\n")
    return out.getvalue()


def test_bank_skill_repackage_is_executable_and_deterministic(tmp_path: Path) -> None:
    kwargs = {"drop_paths": ("process_bank_statement.py.backup",)}
    first = repackage_agent_skill(_legacy_bank_package(), **kwargs)
    second = repackage_agent_skill(_legacy_bank_package(), **kwargs)
    assert first == second

    normalized, files, skill_path = skill_import_service._safe_archive(first, "candidate.zip")
    assert normalized == first
    assert skill_path == "SKILL.md"
    assert "process_bank_statement.py" not in files
    assert "process_bank_statement.py.backup" not in files
    assert "scripts/process_bank_statement.py" in files
    assert b"scripts/process_bank_statement.py" in files[skill_path]

    metadata = skill_import_service._agent_skill_metadata({}, files, files[skill_path].decode())
    assert metadata["scripts"] == [
        {"path": "scripts/process_bank_statement.py", "language": "python"},
    ]
    assert metadata["script_languages"] == ["python"]

    package_dir = tmp_path / "package"
    package_dir.mkdir()
    with zipfile.ZipFile(io.BytesIO(first)) as archive:
        archive.extractall(package_dir)
    input_xlsx = tmp_path / "input.xlsx"
    with zipfile.ZipFile(input_xlsx, "w") as workbook:
        workbook.writestr("[Content_Types].xml", "<Types />")
    output_dir = tmp_path / "outputs"
    output_dir.mkdir()
    output_xlsx = output_dir / "processed.xlsx"
    env = os.environ.copy()
    env["SKILL_OUTPUT_DIR"] = str(output_dir)
    subprocess.run(
        [sys.executable, package_dir / "scripts/process_bank_statement.py", input_xlsx, output_xlsx],
        check=True,
        env=env,
    )
    assert zipfile.is_zipfile(output_xlsx)
    assert output_xlsx.read_bytes() == input_xlsx.read_bytes()
    assert (output_dir / "processing.log").read_text() == "ok\n"


def test_bank_skill_repackage_rejects_missing_source_and_target_collision() -> None:
    with pytest.raises(ValueError, match="Source script is missing"):
        repackage_agent_skill(_legacy_bank_package(), source_script="missing.py")

    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("SKILL.md", "---\nname: Bank\ndescription: Bank\n---\n")
        archive.writestr("process_bank_statement.py", "print('old')\n")
        archive.writestr("scripts/process_bank_statement.py", "print('new')\n")
    with pytest.raises(ValueError, match="Target script already exists"):
        repackage_agent_skill(out.getvalue())
