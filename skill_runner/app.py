"""Internal Open Agent Skill package installer and script executor."""

from __future__ import annotations

import asyncio
import base64
import io
import json
import os
import shutil
import signal
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

CACHE_ROOT = Path(os.getenv("SKILL_CACHE_ROOT", "/cache")).resolve()
RUNNER_TOKEN = os.getenv("SKILL_RUNNER_TOKEN", "skill-runner-dev-token-change-in-production")
MAX_PACKAGE_BYTES = 10 * 1024 * 1024
MAX_OUTPUT_BYTES = 5 * 1024 * 1024
MAX_OUTPUT_FILES = 20

app = FastAPI(title="AI Platform Skill Runner")


class InstallRequest(BaseModel):
    package_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    archive_base64: str
    runtime: str
    entrypoint: str | None = None


class InputFile(BaseModel):
    file_id: str
    name: str
    content_base64: str


class ExecuteRequest(InstallRequest):
    params: dict = Field(default_factory=dict)
    inputs: list[InputFile] = Field(default_factory=list)
    execution_id: int
    timeout_seconds: int = Field(120, ge=1, le=600)
    arguments: list[str] = Field(default_factory=list)
    script_path: str | None = None
    args: list[str] = Field(default_factory=list)


def _auth(token: str | None) -> None:
    if not token or token != RUNNER_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid runner token")


def _decode_archive(encoded: str) -> bytes:
    try:
        raw = base64.b64decode(encoded, validate=True)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid package encoding") from exc
    if not raw or len(raw) > MAX_PACKAGE_BYTES:
        raise HTTPException(status_code=413, detail="Package must be 1 byte to 10MB")
    return raw


def _extract(raw: bytes, target: Path) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            for info in zf.infolist():
                name = info.filename.replace("\\", "/").lstrip("/")
                path = PurePosixPath(name)
                if not name or ".." in path.parts or path.is_absolute():
                    raise HTTPException(status_code=422, detail="Unsafe archive path")
                destination = (target / Path(*path.parts)).resolve()
                if target not in destination.parents and destination != target:
                    raise HTTPException(status_code=422, detail="Unsafe archive path")
                if info.is_dir():
                    destination.mkdir(parents=True, exist_ok=True)
                else:
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(zf.read(info))
    except zipfile.BadZipFile as exc:
        raise HTTPException(status_code=422, detail="Invalid ZIP package") from exc


async def _run(argv: list[str], cwd: Path, timeout: int, env: dict[str, str] | None = None) -> tuple[int, str, str]:
    process = await asyncio.create_subprocess_exec(
        *argv,
        cwd=str(cwd),
        env={**os.environ, **(env or {})},
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        creationflags=0,
        start_new_session=True,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except TimeoutError:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
        await process.communicate()
        raise HTTPException(status_code=408, detail=f"Skill execution exceeded {timeout}s")
    return process.returncode or 0, stdout.decode("utf-8", "replace"), stderr.decode("utf-8", "replace")


async def _ensure_installed(req: InstallRequest) -> Path:
    CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    package_dir = (CACHE_ROOT / req.package_hash).resolve()
    marker = package_dir / ".ready"
    if marker.exists():
        return package_dir
    temp = Path(tempfile.mkdtemp(prefix=f"install-{req.package_hash[:8]}-", dir=CACHE_ROOT))
    try:
        _extract(_decode_archive(req.archive_base64), temp)
        needs_python = req.runtime == "python" or (
            req.runtime == "agent_skill"
            and any((temp / name).exists() for name in ("requirements.txt", "pyproject.toml"))
        )
        needs_node = req.runtime == "node" or (req.runtime == "agent_skill" and (temp / "package.json").exists())
        if needs_python:
            venv = temp / ".venv"
            code, _, err = await _run(["python", "-m", "venv", str(venv)], temp, 120)
            if code:
                raise HTTPException(status_code=422, detail=err[-2000:])
            requirements = temp / "requirements.txt"
            if requirements.exists():
                python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
                code, _, err = await _run([str(python), "-m", "pip", "install", "-r", str(requirements)], temp, 300)
                if code:
                    raise HTTPException(status_code=422, detail=err[-2000:])
            if (temp / "pyproject.toml").exists():
                python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
                code, _, err = await _run([str(python), "-m", "pip", "install", "."], temp, 300)
                if code:
                    raise HTTPException(status_code=422, detail=err[-2000:])
        if needs_node and (temp / "package.json").exists():
            command = (
                ["npm", "ci", "--omit=dev"]
                if (temp / "package-lock.json").exists()
                else ["npm", "install", "--omit=dev"]
            )
            code, _, err = await _run(command, temp, 300)
            if code:
                raise HTTPException(status_code=422, detail=err[-2000:])
        # The cache entry does not exist until the atomically prepared temp
        # directory is renamed into place. Write the marker inside that temp
        # directory so a partially installed package can never look ready.
        (temp / ".ready").write_text("ready", encoding="utf-8")
        if package_dir.exists():
            shutil.rmtree(package_dir)
        temp.replace(package_dir)
        return package_dir
    except Exception:
        shutil.rmtree(temp, ignore_errors=True)
        raise


def _safe_name(name: str) -> str:
    return Path(name.replace("\\", "/")).name or "input.bin"


def _script(package: Path, requested: str | None, legacy_entrypoint: str | None) -> tuple[Path, str]:
    value = requested or legacy_entrypoint
    if not value:
        raise HTTPException(status_code=422, detail="A script_path is required")
    normalized = PurePosixPath(value.replace("\\", "/").lstrip("/"))
    if normalized.is_absolute() or ".." in normalized.parts:
        raise HTTPException(status_code=422, detail="Unsafe script path")
    if requested and (not normalized.parts or normalized.parts[0].lower() != "scripts"):
        raise HTTPException(status_code=422, detail="Standard Skill scripts must be inside scripts/")
    language = {
        ".py": "python", ".js": "node", ".mjs": "node", ".cjs": "node", ".sh": "bash",
    }.get(normalized.suffix.lower())
    if not language:
        raise HTTPException(status_code=422, detail="Only Python, Node, and Bash scripts are executable")
    path = (package / Path(*normalized.parts)).resolve()
    if package not in path.parents or not path.is_file():
        raise HTTPException(status_code=422, detail="Skill script is unavailable")
    return path, language


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/install")
async def install(req: InstallRequest, x_skill_runner_token: str | None = Header(None)) -> dict:
    _auth(x_skill_runner_token)
    path = await _ensure_installed(req)
    return {"status": "ready", "package_hash": req.package_hash, "path": str(path)}


@app.post("/execute")
async def execute(req: ExecuteRequest, x_skill_runner_token: str | None = Header(None)) -> dict:
    _auth(x_skill_runner_token)
    package = await _ensure_installed(req)
    if req.runtime not in {"python", "node", "agent_skill"}:
        raise HTTPException(status_code=422, detail="Skill is not executable")
    entrypoint, language = _script(package, req.script_path, req.entrypoint)
    run_root = Path(tempfile.mkdtemp(prefix=f"run-{req.execution_id}-"))
    try:
        skill_dir, input_dir, output_dir = run_root / "skill", run_root / "input", run_root / "output"
        shutil.copytree(package, skill_dir, ignore=shutil.ignore_patterns(".venv", "node_modules", ".ready"))
        input_dir.mkdir()
        output_dir.mkdir()
        for path in sorted(skill_dir.rglob("*"), reverse=True):
            path.chmod(0o555 if path.is_dir() else 0o444)
        copied_entrypoint = skill_dir / entrypoint.relative_to(package)
        input_paths: list[Path] = []
        for item in req.inputs:
            path = input_dir / _safe_name(item.name)
            try:
                raw = base64.b64decode(item.content_base64, validate=True)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=f"Invalid input {item.name}") from exc
            path.write_bytes(raw)
            input_paths.append(path)
        params_path = run_root / "params.json"
        params_path.write_text(json.dumps(req.params, ensure_ascii=False), encoding="utf-8")
        replacements = {
            "{input_dir}": str(input_dir), "{output_dir}": str(output_dir), "{params_json}": str(params_path),
            "{input_file}": str(input_paths[0]) if input_paths else "",
        }
        args = []
        requested_args = req.args if req.script_path else req.arguments
        for value in requested_args:
            for key, replacement in replacements.items():
                value = value.replace(key, replacement)
            args.append(value)
        if not args and not req.script_path:
            args = ["--input-dir", str(input_dir), "--output-dir", str(output_dir), "--params", str(params_path)]
        if language == "python":
            executable = package / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
            if not executable.exists():
                executable = Path(shutil.which("python") or "python")
            argv = [str(executable), str(copied_entrypoint), *args]
        elif language == "node":
            argv = ["node", str(copied_entrypoint), *args]
        else:
            bash = shutil.which("bash")
            if not bash:
                raise HTTPException(status_code=422, detail="Bash interpreter is unavailable")
            argv = [bash, str(copied_entrypoint), *args]
        code, stdout, stderr = await _run(argv, skill_dir, req.timeout_seconds, {
            "SKILL_INPUT_DIR": str(input_dir), "SKILL_OUTPUT_DIR": str(output_dir),
            "SKILL_PARAMS_JSON": str(params_path),
            "SKILL_DIR": str(skill_dir), "SKILL_ROOT": str(skill_dir),
            "NODE_PATH": str(package / "node_modules"),
        })
        if code:
            raise HTTPException(status_code=422, detail=(stderr or stdout)[-4000:])
        files = [path for path in output_dir.rglob("*") if path.is_file()]
        if len(files) > MAX_OUTPUT_FILES:
            raise HTTPException(status_code=422, detail="Skill produced more than 20 files")
        outputs = []
        for path in files:
            raw = path.read_bytes()
            if len(raw) > MAX_OUTPUT_BYTES:
                raise HTTPException(status_code=413, detail=f"Output {path.name} exceeds 5MB")
            outputs.append({
                "name": path.name,
                "relative_path": path.relative_to(output_dir).as_posix(),
                "content_base64": base64.b64encode(raw).decode("ascii"),
                "size": len(raw),
            })
        return {"status": "success", "stdout": stdout[-4000:], "outputs": outputs}
    finally:
        shutil.rmtree(run_root, ignore_errors=True)
