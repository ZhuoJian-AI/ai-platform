"""Focused tests for direct Open Agent Skill script execution."""

from __future__ import annotations

import base64
import io
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
