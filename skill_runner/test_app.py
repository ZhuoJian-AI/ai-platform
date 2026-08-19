"""Focused tests for direct Open Agent Skill script execution."""

from __future__ import annotations

import base64
import io
import json
import zipfile
from pathlib import Path

import pytest

import app as runner


def _package(script_path: str, content: bytes) -> tuple[str, str]:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("SKILL.md", "---\nname: Test\ndescription: Test script\n---\n")
        zf.writestr(script_path, content)
    raw = out.getvalue()
    import hashlib
    return hashlib.sha256(raw).hexdigest(), base64.b64encode(raw).decode("ascii")


def _package_files(files: dict[str, bytes]) -> tuple[str, str]:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("SKILL.md", "---\nname: Test\ndescription: Test script\n---\n")
        for path, content in files.items():
            zf.writestr(path, content)
    raw = out.getvalue()
    import hashlib
    return hashlib.sha256(raw).hexdigest(), base64.b64encode(raw).decode("ascii")


@pytest.mark.asyncio
async def test_python_agent_skill_uses_direct_script_and_io_directories(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "CACHE_ROOT", tmp_path / "cache")
    script = b"""import os
from pathlib import Path
source = next(Path(os.environ['SKILL_INPUT_DIR']).iterdir())
target = Path(os.environ['SKILL_OUTPUT_DIR']) / 'cleaned.txt'
target.write_text(source.read_text(encoding='utf-8').upper(), encoding='utf-8')
"""
    package_hash, archive = _package("scripts/clean.py", script)
    request = runner.ExecuteRequest(
        package_hash=package_hash,
        archive_base64=archive,
        runtime="agent_skill",
        script_path="scripts/clean.py",
        inputs=[runner.InputFile(
            file_id="1", name="input.txt",
            content_base64=base64.b64encode(b"hello").decode(),
        )],
        execution_id=1,
    )
    result = await runner.execute(request, runner.RUNNER_TOKEN)
    assert result["status"] == "success"
    assert result["outputs"][0]["name"] == "cleaned.txt"
    assert base64.b64decode(result["outputs"][0]["content_base64"]).decode() == "HELLO"


@pytest.mark.asyncio
async def test_standard_script_must_stay_under_scripts(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "CACHE_ROOT", tmp_path / "cache")
    package_hash, archive = _package("scripts/clean.py", b"print('ok')")
    request = runner.ExecuteRequest(
        package_hash=package_hash,
        archive_base64=archive,
        runtime="agent_skill",
        script_path="../scripts/clean.py",
        execution_id=2,
    )
    with pytest.raises(runner.HTTPException) as exc:
        await runner.execute(request, runner.RUNNER_TOKEN)
    assert exc.value.status_code == 422


@pytest.mark.parametrize("script_path,language", [
    ("scripts/a.py", "python"),
    ("scripts/a.js", "node"),
    ("scripts/a.sh", "bash"),
])
def test_supported_script_languages_are_detected(tmp_path: Path, script_path: str, language: str):
    package = tmp_path / "package"
    target = package / script_path
    target.parent.mkdir(parents=True)
    target.write_text("", encoding="utf-8")
    _, actual = runner._script(package.resolve(), script_path, None)
    assert actual == language


def test_python_version_requirement_rejects_incompatible_skill(tmp_path: Path, monkeypatch):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "run.py").write_text("print('ok')", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname="future-skill"\nversion="1.0.0"\nrequires-python=">=99"\n', encoding="utf-8",
    )
    monkeypatch.setattr(runner, "_runtime_info", lambda: {
        "python_version": "3.12.0", "node_version": "20.0.0",
        "bash_version": None, "libreoffice_version": None, "builtin_dependencies": {},
    })
    with pytest.raises(runner.HTTPException) as exc:
        runner._validate_runtime_compatibility(tmp_path)
    assert "requires Python >=99" in exc.value.detail


def test_node_engine_requirement_and_missing_version_warning(tmp_path: Path, monkeypatch):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "run.js").write_text("console.log('ok')", encoding="utf-8")
    (tmp_path / "package.json").write_text('{"engines":{"node":">=20 <21"}}', encoding="utf-8")
    monkeypatch.setattr(runner, "_runtime_info", lambda: {
        "python_version": "3.12.0", "node_version": "20.20.2",
        "bash_version": None, "libreoffice_version": None, "builtin_dependencies": {},
    })
    assert runner._validate_runtime_compatibility(tmp_path) == []
    (tmp_path / "package.json").write_text('{}', encoding="utf-8")
    warnings = runner._validate_runtime_compatibility(tmp_path)
    assert any("engines.node" in warning for warning in warnings)


@pytest.mark.asyncio
async def test_pyproject_takes_precedence_over_requirements(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(runner, "CACHE_ROOT", tmp_path / "cache")
    calls: list[list[str]] = []

    async def fake_run(argv, *_args, **_kwargs):
        calls.append(argv)
        return 0, "", ""

    monkeypatch.setattr(runner, "_run", fake_run)
    monkeypatch.setattr(runner, "_runtime_info", lambda: {
        "python_version": "3.12.0", "node_version": "20.0.0",
        "bash_version": None, "libreoffice_version": None, "builtin_dependencies": {},
    })
    package_hash, archive = _package_files({
        "scripts/run.py": b"print('ok')",
        "pyproject.toml": b'[project]\nname="priority-test"\nversion="1.0.0"\nrequires-python=">=3.12"\n',
        "requirements.txt": b"this-must-not-be-installed==999\n",
    })
    await runner._ensure_installed(runner.InstallRequest(
        package_hash=package_hash, archive_base64=archive, runtime="agent_skill",
    ))
    pip_calls = [call for call in calls if "pip" in call]
    assert any(call[-2:] == ["install", "."] for call in pip_calls)
    assert not any("-r" in call for call in pip_calls)


@pytest.mark.asyncio
@pytest.mark.parametrize(("script_path", "content", "output_name", "expected"), [
    (
        "scripts/write.js",
        b"require('fs').writeFileSync(process.env.SKILL_OUTPUT_DIR + '/node.txt', 'NODE')\n",
        "node.txt",
        b"NODE",
    ),
    (
        "scripts/write.sh",
        b"printf BASH > \"$SKILL_OUTPUT_DIR/bash.txt\"\n",
        "bash.txt",
        b"BASH",
    ),
])
async def test_node_and_bash_scripts_execute_directly(
    tmp_path, monkeypatch, script_path: str, content: bytes, output_name: str, expected: bytes,
):
    monkeypatch.setattr(runner, "CACHE_ROOT", tmp_path / "cache")
    package_hash, archive = _package(script_path, content)
    result = await runner.execute(runner.ExecuteRequest(
        package_hash=package_hash,
        archive_base64=archive,
        runtime="agent_skill",
        script_path=script_path,
        execution_id=3,
    ), runner.RUNNER_TOKEN)
    output = next(item for item in result["outputs"] if item["name"] == output_name)
    assert base64.b64decode(output["content_base64"]) == expected


@pytest.mark.asyncio
async def test_python_skill_without_requirements_uses_builtin_excel_library(
    tmp_path, monkeypatch,
):
    monkeypatch.setattr(runner, "CACHE_ROOT", tmp_path / "cache")
    script = b"""from pathlib import Path
import os
from openpyxl import Workbook

book = Workbook()
book.active.append(["name", "value"])
book.active.append(["ready", 1])
book.save(Path(os.environ["SKILL_OUTPUT_DIR"]) / "result.xlsx")
"""
    package_hash, archive = _package("scripts/create_excel.py", script)
    result = await runner.execute(
        runner.ExecuteRequest(
            package_hash=package_hash,
            archive_base64=archive,
            runtime="agent_skill",
            script_path="scripts/create_excel.py",
            execution_id=4,
        ),
        runner.RUNNER_TOKEN,
    )
    output = next(item for item in result["outputs"] if item["name"] == "result.xlsx")
    assert base64.b64decode(output["content_base64"]).startswith(b"PK")


@pytest.mark.asyncio
async def test_node_skill_without_package_json_uses_builtin_exceljs(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "CACHE_ROOT", tmp_path / "cache")
    script = b"""const ExcelJS = require('exceljs');
const path = require('path');
const workbook = new ExcelJS.Workbook();
workbook.addWorksheet('Sheet1').addRow(['ready', 1]);
(async () => {
  await workbook.xlsx.writeFile(path.join(process.env.SKILL_OUTPUT_DIR, 'result.xlsx'));
})();
"""
    package_hash, archive = _package("scripts/create_excel.js", script)
    result = await runner.execute(
        runner.ExecuteRequest(
            package_hash=package_hash,
            archive_base64=archive,
            runtime="agent_skill",
            script_path="scripts/create_excel.js",
            execution_id=5,
        ),
        runner.RUNNER_TOKEN,
    )
    output = next(item for item in result["outputs"] if item["name"] == "result.xlsx")
    assert base64.b64decode(output["content_base64"]).startswith(b"PK")


@pytest.mark.asyncio
async def test_python_skill_installs_extra_dependency_in_its_own_environment(
    tmp_path, monkeypatch,
):
    monkeypatch.setattr(runner, "CACHE_ROOT", tmp_path / "cache")
    package_hash, archive = _package_files({
        "requirements.txt": b"humanize==4.12.1\n",
        "scripts/run.py": b"""from pathlib import Path
import os
import humanize

Path(os.environ["SKILL_OUTPUT_DIR"], "result.txt").write_text(
    humanize.intcomma(1234567), encoding="utf-8"
)
""",
    })
    result = await runner.execute(
        runner.ExecuteRequest(
            package_hash=package_hash,
            archive_base64=archive,
            runtime="agent_skill",
            script_path="scripts/run.py",
            execution_id=6,
        ),
        runner.RUNNER_TOKEN,
    )
    output = next(item for item in result["outputs"] if item["name"] == "result.txt")
    assert base64.b64decode(output["content_base64"]) == b"1,234,567"
    metadata = json.loads((tmp_path / "cache" / package_hash / ".install.json").read_text())
    assert metadata["installed_dependencies"]["python"] == ["humanize==4.12.1"]
