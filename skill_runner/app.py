"""Internal Open Agent Skill package installer and script executor."""

from __future__ import annotations

import asyncio
import base64
import importlib.metadata
import io
import json
import os
import platform
import re
import shutil
import signal
import subprocess
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Literal

from builtin_tools import BuiltinToolError, execute_builtin
from fastapi import FastAPI, Header, HTTPException
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version
from pydantic import BaseModel, Field

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - production Runner is Python 3.12
    import tomli as tomllib

CACHE_ROOT = Path(os.getenv("SKILL_CACHE_ROOT", "/cache")).resolve()
RUNNER_TOKEN = os.getenv("SKILL_RUNNER_TOKEN", "skill-runner-dev-token-change-in-production")
MAX_PACKAGE_BYTES = 10 * 1024 * 1024
MAX_OUTPUT_BYTES = 5 * 1024 * 1024
MAX_OUTPUT_FILES = 20
BASE_NODE_MODULES = Path(os.getenv("SKILL_BASE_NODE_MODULES", "/opt/skill-node/node_modules"))
BUILTIN_PYTHON_PACKAGES = (
    "openpyxl", "pandas", "python-docx", "python-pptx", "PyMuPDF", "pypdf",
)
BUILTIN_NODE_PACKAGES = ("exceljs",)

app = FastAPI(title="AI Platform Skill Runner")


def _command_version(argv: list[str]) -> str | None:
    try:
        result = subprocess.run(argv, capture_output=True, timeout=5, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    raw = result.stdout or result.stderr or b""
    value = raw.decode("utf-8", errors="replace").strip().splitlines()
    return value[0] if value else None


def _package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def _runtime_info() -> dict:
    return {
        "python_version": platform.python_version(),
        "node_version": (_command_version(["node", "--version"]) or "").lstrip("v") or None,
        "bash_version": _command_version(["bash", "--version"]),
        "libreoffice_version": _command_version(["libreoffice", "--version"]),
        "builtin_dependencies": {
            "python": {name: _package_version(name) for name in BUILTIN_PYTHON_PACKAGES},
            "node": {"exceljs": "4.4.0" if (BASE_NODE_MODULES / "exceljs").exists() else None},
        },
    }


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


class BuiltinExecuteRequest(BaseModel):
    tool_kind: Literal["spreadsheet", "document", "presentation", "pdf", "text"]
    action: Literal["inspect", "create", "edit", "convert"]
    params: dict = Field(default_factory=dict)
    inputs: list[InputFile] = Field(default_factory=list)
    execution_id: str
    timeout_seconds: int = Field(120, ge=1, le=600)


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


def _uses_language(root: Path, suffixes: set[str]) -> bool:
    scripts = root / "scripts"
    return scripts.is_dir() and any(path.suffix.lower() in suffixes for path in scripts.rglob("*"))


def _python_spec(root: Path) -> str | None:
    pyproject = root / "pyproject.toml"
    if not pyproject.exists():
        return None
    try:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise HTTPException(status_code=422, detail=f"Invalid pyproject.toml: {exc}") from exc
    project = data.get("project")
    return str(project.get("requires-python")) if isinstance(project, dict) and project.get("requires-python") else None


def _node_spec(root: Path) -> str | None:
    package_json = root / "package.json"
    if not package_json.exists():
        return None
    try:
        data = json.loads(package_json.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=422, detail=f"Invalid package.json: {exc}") from exc
    engines = data.get("engines")
    return str(engines.get("node")) if isinstance(engines, dict) and engines.get("node") else None


def _node_version_matches(spec: str, actual: str) -> bool:
    """Evaluate the common subset of npm engine ranges used by Skills.

    Supports exact/major versions, comparison ranges, caret/tilde ranges and
    `x` wildcards.  `||` alternatives are accepted.  Invalid ranges are
    rejected explicitly instead of silently claiming compatibility.
    """
    try:
        current = Version(actual)
    except InvalidVersion as exc:
        raise HTTPException(status_code=422, detail=f"Runner Node version is invalid: {actual}") from exc
    for alternative in spec.split("||"):
        tokens = [token for token in re.split(r"[ ,]+", alternative.strip()) if token]
        ok = True
        for token in tokens:
            token = token.strip()
            if token in {"*", "x", "X"}:
                continue
            match = re.fullmatch(r"(>=|<=|>|<|=)?v?(\d+)(?:\.(\d+|x|X|\*))?(?:\.(\d+|x|X|\*))?", token)
            if token.startswith(("^", "~")):
                operator, raw = token[0], token[1:].lstrip("v")
                parts = [int(p) for p in raw.split(".") if p.isdigit()]
                if not parts:
                    raise HTTPException(status_code=422, detail=f"Unsupported Node engine range: {spec}")
                low = Version(".".join(map(str, parts + [0] * (3 - len(parts)))))
                high = Version(f"{low.major + 1}.0.0") if operator == "^" else Version(f"{low.major}.{low.minor + 1}.0")
                ok = ok and current >= low and current < high
                continue
            if not match:
                raise HTTPException(status_code=422, detail=f"Unsupported Node engine range: {spec}")
            op, major, minor, patch = match.groups()
            if minor in {None, "x", "X", "*"}:
                if op:
                    target = Version(f"{major}.0.0")
                else:
                    ok = ok and current.major == int(major)
                    continue
            elif patch in {None, "x", "X", "*"} and not op:
                ok = ok and current.major == int(major) and current.minor == int(minor)
                continue
            else:
                target = Version(f"{major}.{minor}.{patch or 0}")
            ok = ok and {
                ">=": current >= target, "<=": current <= target, ">": current > target,
                "<": current < target, "=": current == target, None: current == target,
            }[op]
        if ok:
            return True
    return False


def _dependency_declarations(root: Path) -> dict[str, list[str]]:
    python_deps: list[str] = []
    node_deps: list[str] = []
    pyproject = root / "pyproject.toml"
    requirements = root / "requirements.txt"
    if pyproject.exists():
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        project = data.get("project")
        values = project.get("dependencies") if isinstance(project, dict) else []
        python_deps = [str(value) for value in values] if isinstance(values, list) else []
    elif requirements.exists():
        python_deps = [
            line.strip() for line in requirements.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
    package_json = root / "package.json"
    if package_json.exists():
        data = json.loads(package_json.read_text(encoding="utf-8"))
        dependencies = data.get("dependencies")
        if isinstance(dependencies, dict):
            node_deps = [f"{name}@{version}" for name, version in sorted(dependencies.items())]
    return {"python": python_deps, "node": node_deps}


def _validate_runtime_compatibility(root: Path) -> list[str]:
    info = _runtime_info()
    warnings: list[str] = []
    uses_python = (
        _uses_language(root, {".py"})
        or (root / "pyproject.toml").exists()
        or (root / "requirements.txt").exists()
    )
    uses_node = _uses_language(root, {".js", ".mjs", ".cjs"}) or (root / "package.json").exists()
    if uses_python:
        spec = _python_spec(root)
        if spec:
            try:
                compatible = Version(info["python_version"]) in SpecifierSet(spec)
            except (InvalidSpecifier, InvalidVersion) as exc:
                raise HTTPException(status_code=422, detail=f"Invalid requires-python value: {spec}") from exc
            if not compatible:
                raise HTTPException(
                    status_code=422,
                    detail=f"Skill requires Python {spec}, but Runner provides Python {info['python_version']}",
                )
        else:
            warnings.append(f"Skill 未声明 requires-python；当前使用 Python {info['python_version']}")
    if uses_node:
        spec = _node_spec(root)
        actual = info.get("node_version")
        if not actual:
            raise HTTPException(status_code=422, detail="Runner Node runtime is unavailable")
        if spec and not _node_version_matches(spec, actual):
            raise HTTPException(
                status_code=422,
                detail=f"Skill requires Node {spec}, but Runner provides Node {actual}",
            )
        if not spec:
            warnings.append(f"Skill 未声明 package.json engines.node；当前使用 Node {actual}")
    return warnings


async def _ensure_installed(req: InstallRequest) -> tuple[Path, dict]:
    CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    package_dir = (CACHE_ROOT / req.package_hash).resolve()
    marker = package_dir / ".ready"
    if marker.exists():
        metadata_file = package_dir / ".install.json"
        metadata = json.loads(metadata_file.read_text(encoding="utf-8")) if metadata_file.exists() else {
            **_runtime_info(), "installed_dependencies": {"python": [], "node": []}, "compatibility_warnings": [],
        }
        return package_dir, metadata
    temp = Path(tempfile.mkdtemp(prefix=f"install-{req.package_hash[:8]}-", dir=CACHE_ROOT))
    try:
        _extract(_decode_archive(req.archive_base64), temp)
        warnings = _validate_runtime_compatibility(temp)
        needs_python = req.runtime == "python" or (
            req.runtime == "agent_skill"
            and any((temp / name).exists() for name in ("requirements.txt", "pyproject.toml"))
        )
        needs_node = req.runtime == "node" or (req.runtime == "agent_skill" and (temp / "package.json").exists())
        if needs_python:
            venv = temp / ".venv"
            code, _, err = await _run(["python", "-m", "venv", "--system-site-packages", str(venv)], temp, 120)
            if code:
                raise HTTPException(status_code=422, detail=err[-2000:])
            python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
            if (temp / "pyproject.toml").exists():
                code, _, err = await _run([str(python), "-m", "pip", "install", "."], temp, 300)
                if code:
                    raise HTTPException(status_code=422, detail=err[-2000:])
            elif (temp / "requirements.txt").exists():
                code, _, err = await _run(
                    [str(python), "-m", "pip", "install", "-r", str(temp / "requirements.txt")], temp, 300,
                )
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
        metadata = {
            **_runtime_info(),
            "installed_dependencies": _dependency_declarations(temp),
            "compatibility_warnings": warnings,
        }
        # The cache entry does not exist until the atomically prepared temp
        # directory is renamed into place. Write the marker inside that temp
        # directory so a partially installed package can never look ready.
        (temp / ".install.json").write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")
        (temp / ".ready").write_text("ready", encoding="utf-8")
        if package_dir.exists():
            shutil.rmtree(package_dir)
        temp.replace(package_dir)
        return package_dir, metadata
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
async def health() -> dict:
    return {"status": "ok", **_runtime_info()}


@app.post("/install")
async def install(req: InstallRequest, x_skill_runner_token: str | None = Header(None)) -> dict:
    _auth(x_skill_runner_token)
    path, metadata = await _ensure_installed(req)
    return {"status": "ready", "package_hash": req.package_hash, "path": str(path), **metadata}


@app.post("/execute-builtin")
async def execute_builtin_tool(
    req: BuiltinExecuteRequest,
    x_skill_runner_token: str | None = Header(None),
) -> dict:
    """Execute a platform-owned file handler without loading a user Skill."""
    _auth(x_skill_runner_token)
    run_root = Path(tempfile.mkdtemp(prefix=f"builtin-{req.execution_id}-"))
    try:
        input_dir, output_dir = run_root / "input", run_root / "output"
        input_dir.mkdir()
        output_dir.mkdir()
        input_paths: list[Path] = []
        for item in req.inputs:
            path = input_dir / _safe_name(item.name)
            try:
                raw = base64.b64decode(item.content_base64, validate=True)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=f"Invalid input {item.name}") from exc
            if len(raw) > MAX_OUTPUT_BYTES:
                raise HTTPException(status_code=413, detail=f"Input {item.name} exceeds 5MB")
            path.write_bytes(raw)
            path.chmod(0o444)
            input_paths.append(path)
        input_dir.chmod(0o555)
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(
                    execute_builtin,
                    req.tool_kind,
                    req.action,
                    input_paths,
                    req.params,
                    output_dir,
                ),
                timeout=req.timeout_seconds,
            )
        except TimeoutError as exc:
            raise HTTPException(
                status_code=408,
                detail=f"Builtin tool execution exceeded {req.timeout_seconds}s",
            ) from exc
        except BuiltinToolError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        files = [path for path in output_dir.rglob("*") if path.is_file()]
        if len(files) > MAX_OUTPUT_FILES:
            raise HTTPException(status_code=422, detail="Builtin tool produced more than 20 files")
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
                "mime_type": (result.get("mime_types") or {}).get(path.name),
            })
        return {
            "status": "success",
            "tool_kind": req.tool_kind,
            "action": req.action,
            "summary": result.get("summary"),
            "outputs": outputs,
        }
    finally:
        shutil.rmtree(run_root, ignore_errors=True)


@app.post("/execute")
async def execute(req: ExecuteRequest, x_skill_runner_token: str | None = Header(None)) -> dict:
    _auth(x_skill_runner_token)
    package, _ = await _ensure_installed(req)
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
            path.chmod(0o444)
            input_paths.append(path)
        input_dir.chmod(0o555)
        params_path = run_root / "params.json"
        params_path.write_text(json.dumps(req.params, ensure_ascii=False), encoding="utf-8")
        params_path.chmod(0o444)
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
        node_paths = [str(package / "node_modules")]
        if BASE_NODE_MODULES.exists():
            node_paths.append(str(BASE_NODE_MODULES))
        code, stdout, stderr = await _run(argv, skill_dir, req.timeout_seconds, {
            "SKILL_INPUT_DIR": str(input_dir), "SKILL_OUTPUT_DIR": str(output_dir),
            "SKILL_PARAMS_JSON": str(params_path),
            "SKILL_DIR": str(skill_dir), "SKILL_ROOT": str(skill_dir),
            "NODE_PATH": os.pathsep.join(node_paths),
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
