"""Internal Open Agent Skill package installer and script executor."""

from __future__ import annotations

import asyncio
import base64
import hashlib
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
import time
import zipfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path, PurePosixPath
from typing import Literal

import httpx
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
MAX_PACKAGE_BYTES = int(os.getenv("SKILL_PACKAGE_MAX_BYTES", str(100 * 1024 * 1024)))
MAX_EXPANDED_PACKAGE_BYTES = int(
    os.getenv("SKILL_PACKAGE_EXPANDED_MAX_BYTES", str(500 * 1024 * 1024))
)
MAX_PACKAGE_FILES = int(os.getenv("SKILL_PACKAGE_MAX_FILES", "1000"))
MAX_OUTPUT_BYTES = 100 * 1024 * 1024
INLINE_TRANSFER_BYTES = 10 * 1024 * 1024
MAX_OUTPUT_FILES = 20
BASE_NODE_MODULES = Path(os.getenv("SKILL_BASE_NODE_MODULES", "/opt/skill-node/node_modules"))
STORAGE_GATEWAY_URL = os.getenv("STORAGE_GATEWAY_URL", "").rstrip("/")
STORAGE_PROJECT_TOKEN = os.getenv("STORAGE_PROJECT_TOKEN", "")
RUNNER_MAX_CONCURRENCY = int(os.getenv("SKILL_RUNNER_MAX_CONCURRENCY", "4"))
RUNNER_MAX_QUEUE = int(os.getenv("SKILL_RUNNER_MAX_QUEUE", "100"))
RUNNER_QUEUE_WAIT_SECONDS = int(os.getenv("SKILL_RUNNER_QUEUE_WAIT_SECONDS", "300"))
RUNNER_OFFICE_CONCURRENCY = int(os.getenv("SKILL_RUNNER_OFFICE_CONCURRENCY", "1"))
CACHE_RETENTION_SECONDS = int(os.getenv("SKILL_CACHE_RETENTION_SECONDS", str(7 * 24 * 60 * 60)))
CACHE_MAX_BYTES = int(os.getenv("SKILL_CACHE_MAX_BYTES", str(10 * 1024 * 1024 * 1024)))
FAILED_TEMP_RETENTION_SECONDS = int(os.getenv("SKILL_FAILED_TEMP_RETENTION_SECONDS", "3600"))
BUILTIN_PYTHON_PACKAGES = (
    "openpyxl", "pandas", "python-docx", "python-pptx", "PyMuPDF", "pypdf", "Pillow", "pytesseract",
)
BUILTIN_NODE_PACKAGES = ("exceljs",)

# The Runner executes user-controlled Python, Node, Bash, and dependency
# installation hooks.  These platform credentials must never exist in its
# process namespace: a child can inspect /proc even when its direct environment
# is rebuilt from an allowlist.
FORBIDDEN_PLATFORM_SECRET_KEYS = (
    "DATABASE_URL",
    "REDIS_URL",
    "POSTGRES_PASSWORD",
    "REDIS_PASSWORD",
    "SECRET_KEY",
    "MASTER_ENCRYPTION_KEY",
    "CRM_API_KEY",
    "MES_API_KEY",
    "DSH_RUNTIME_TOKEN",
    "EXTENSION_BUILDER_TOKEN",
)

app = FastAPI(title="AI Platform Skill Runner")
_CACHE_LOCK = asyncio.Lock()
_ACTIVE_PACKAGE_HASHES: set[str] = set()
_INSTALL_LOCKS: dict[str, asyncio.Lock] = {}


class RunnerCapacity:
    """A small in-process queue protecting this isolated Runner container."""

    def __init__(self, limit: int, queue_limit: int, wait_seconds: int, label: str) -> None:
        self.limit = max(1, limit)
        self.queue_limit = max(0, queue_limit)
        self.wait_seconds = max(1, wait_seconds)
        self.label = label
        self.active = 0
        self.waiting = 0
        self._condition = asyncio.Condition()

    async def _wait_for_slot(self) -> None:
        async with self._condition:
            if self.waiting >= self.queue_limit:
                raise HTTPException(status_code=429, detail=f"{self.label} queue is full")
            self.waiting += 1
            try:
                await asyncio.wait_for(
                    self._condition.wait_for(lambda: self.active < self.limit),
                    timeout=self.wait_seconds,
                )
            except TimeoutError as exc:
                raise HTTPException(
                    status_code=503,
                    detail=f"{self.label} remained busy for {self.wait_seconds}s",
                ) from exc
            finally:
                self.waiting -= 1
            self.active += 1

    async def _release(self) -> None:
        async with self._condition:
            self.active = max(0, self.active - 1)
            self._condition.notify_all()

    @asynccontextmanager
    async def slot(self) -> AsyncIterator[None]:
        await self._wait_for_slot()
        try:
            yield
        finally:
            await self._release()

    def snapshot(self) -> dict:
        return {"active": self.active, "waiting": self.waiting, "limit": self.limit}


EXECUTION_CAPACITY = RunnerCapacity(
    RUNNER_MAX_CONCURRENCY, RUNNER_MAX_QUEUE, RUNNER_QUEUE_WAIT_SECONDS, "Skill Runner",
)
OFFICE_CAPACITY = RunnerCapacity(
    RUNNER_OFFICE_CONCURRENCY, RUNNER_MAX_QUEUE, RUNNER_QUEUE_WAIT_SECONDS, "Office Runner",
)


def _command_version(argv: list[str]) -> str | None:
    try:
        result = subprocess.run(argv, capture_output=True, timeout=5, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
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
        "tesseract_version": _command_version(["tesseract", "--version"]),
        "platform_tools": [
            "spreadsheet", "document", "presentation", "pdf", "text", "web", "image", "archive",
        ],
        "builtin_dependencies": {
            "python": {name: _package_version(name) for name in BUILTIN_PYTHON_PACKAGES},
            "node": {"exceljs": "4.4.0" if (BASE_NODE_MODULES / "exceljs").exists() else None},
        },
    }


class InstallRequest(BaseModel):
    package_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    archive_base64: str | None = None
    archive_url: str | None = None
    archive_headers: dict[str, str] = Field(default_factory=dict)
    archive_size: int | None = Field(None, ge=1, le=MAX_PACKAGE_BYTES)
    runtime: str
    entrypoint: str | None = None


class InputFile(BaseModel):
    file_id: str
    name: str
    content_base64: str | None = None
    download_url: str | None = None
    download_headers: dict[str, str] = Field(default_factory=dict)
    expected_size: int | None = Field(None, ge=1, le=100 * 1024 * 1024)


class ExecuteRequest(InstallRequest):
    params: dict = Field(default_factory=dict)
    inputs: list[InputFile] = Field(default_factory=list)
    execution_id: int
    timeout_seconds: int = Field(120, ge=1, le=600)
    arguments: list[str] = Field(default_factory=list)
    script_path: str | None = None
    args: list[str] = Field(default_factory=list)


class BuiltinExecuteRequest(BaseModel):
    tool_kind: Literal[
        "spreadsheet", "document", "presentation", "pdf", "text", "web", "image", "archive",
    ]
    action: str = Field(min_length=1, max_length=32)
    params: dict = Field(default_factory=dict)
    inputs: list[InputFile] = Field(default_factory=list)
    execution_id: str
    timeout_seconds: int = Field(120, ge=1, le=600)


def _auth(token: str | None) -> None:
    if not token or token != RUNNER_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid runner token")


def _assert_platform_secrets_absent() -> None:
    leaked = sorted(key for key in FORBIDDEN_PLATFORM_SECRET_KEYS if os.getenv(key))
    if leaked:
        raise HTTPException(
            status_code=503,
            detail="Skill Runner contains forbidden platform secrets: " + ", ".join(leaked),
        )


def _decode_archive(encoded: str) -> bytes:
    try:
        raw = base64.b64decode(encoded, validate=True)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid package encoding") from exc
    if not raw or len(raw) > MAX_PACKAGE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Package must be 1 byte to {MAX_PACKAGE_BYTES // (1024 * 1024)}MB",
        )
    return raw


async def _load_archive(req: InstallRequest) -> bytes:
    if bool(req.archive_base64) == bool(req.archive_url):
        raise HTTPException(
            status_code=422,
            detail="Exactly one of archive_base64 or archive_url is required",
        )
    if req.archive_base64:
        raw = _decode_archive(req.archive_base64)
    else:
        chunks: list[bytes] = []
        total = 0
        try:
            async with (
                httpx.AsyncClient(timeout=300, trust_env=False, follow_redirects=False) as client,
                client.stream("GET", req.archive_url, headers=req.archive_headers) as response,
            ):
                response.raise_for_status()
                async for chunk in response.aiter_bytes(1024 * 1024):
                    total += len(chunk)
                    if total > MAX_PACKAGE_BYTES:
                        raise HTTPException(status_code=413, detail="Skill package exceeds 100MB")
                    chunks.append(chunk)
        except HTTPException:
            raise
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail="Unable to download Skill package") from exc
        raw = b"".join(chunks)
    if req.archive_size is not None and len(raw) != req.archive_size:
        raise HTTPException(status_code=422, detail="Skill package size does not match metadata")
    if hashlib.sha256(raw).hexdigest() != req.package_hash:
        raise HTTPException(status_code=422, detail="Skill package checksum mismatch")
    return raw


def _extract(raw: bytes, target: Path) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            entries = zf.infolist()
            file_entries = [item for item in entries if not item.is_dir()]
            if len(file_entries) > MAX_PACKAGE_FILES:
                raise HTTPException(
                    status_code=413,
                    detail=f"Skill package contains more than {MAX_PACKAGE_FILES} files",
                )
            expanded_size = sum(item.file_size for item in file_entries)
            if expanded_size > MAX_EXPANDED_PACKAGE_BYTES:
                raise HTTPException(status_code=413, detail="Expanded Skill package exceeds 500MB")
            seen_paths: set[str] = set()
            for info in entries:
                name = info.filename.replace("\\", "/").lstrip("/")
                path = PurePosixPath(name)
                if not name or ".." in path.parts or path.is_absolute():
                    raise HTTPException(status_code=422, detail="Unsafe archive path")
                normalized = path.as_posix().casefold()
                if normalized in seen_paths:
                    raise HTTPException(status_code=422, detail="Duplicate archive path")
                seen_paths.add(normalized)
                destination = (target / Path(*path.parts)).resolve()
                if target not in destination.parents and destination != target:
                    raise HTTPException(status_code=422, detail="Unsafe archive path")
                if info.is_dir():
                    destination.mkdir(parents=True, exist_ok=True)
                else:
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(info) as source, destination.open("wb") as output:
                        shutil.copyfileobj(source, output, length=1024 * 1024)
    except zipfile.BadZipFile as exc:
        raise HTTPException(status_code=422, detail="Invalid ZIP package") from exc


_CHILD_ENV_ALLOWLIST = {
    "PATH", "HOME", "LANG", "LC_ALL", "TZ", "SSL_CERT_FILE", "SSL_CERT_DIR",
    # Windows needs these process-level values to start Python/Node reliably. They
    # describe the operating system and temporary directory, not platform secrets.
    "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "PATHEXT", "COMSPEC",
    "PIP_INDEX_URL", "PIP_TRUSTED_HOST", "PIP_DEFAULT_TIMEOUT", "PIP_RETRIES",
    "NPM_CONFIG_REGISTRY", "NPM_CONFIG_FETCH_RETRIES", "NPM_CONFIG_FETCH_RETRY_MINTIMEOUT",
    "NPM_CONFIG_FETCH_RETRY_MAXTIMEOUT", "NPM_CONFIG_FETCH_TIMEOUT", "NODE_PATH",
}


def _child_environment(extra: dict[str, str] | None = None) -> dict[str, str]:
    result = {key: value for key, value in os.environ.items() if key in _CHILD_ENV_ALLOWLIST}
    result.update(extra or {})
    result.setdefault("HOME", "/tmp/skill-home" if os.name == "posix" else tempfile.gettempdir())
    result.setdefault("LANG", "C.UTF-8")
    return result


def _remove_tree(path: Path) -> None:
    """Remove an execution tree even when its mounted inputs were made read-only."""
    if not path.exists():
        return
    for item in sorted(path.rglob("*"), reverse=True):
        try:
            item.chmod(0o700 if item.is_dir() else 0o600)
        except OSError:
            pass
    try:
        path.chmod(0o700)
    except OSError:
        pass
    shutil.rmtree(path, ignore_errors=True)


async def _run(argv: list[str], cwd: Path, timeout: int, env: dict[str, str] | None = None) -> tuple[int, str, str]:
    process = await asyncio.create_subprocess_exec(
        *argv,
        cwd=str(cwd),
        env=_child_environment(env),
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


def _cache_entry_size(path: Path) -> int:
    total = 0
    for item in path.rglob("*"):
        try:
            if item.is_file():
                total += item.stat().st_size
        except OSError:
            continue
    return total


def _touch_cache_entry(path: Path) -> None:
    marker = path / ".last_used"
    marker.touch(exist_ok=True)


def _cache_last_used(path: Path) -> float:
    marker = path / ".last_used"
    try:
        return (marker if marker.exists() else path).stat().st_mtime
    except OSError:
        return 0.0


async def _cleanup_cache() -> dict[str, int]:
    CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    async with _CACHE_LOCK:
        now = time.time()
        removed_entries = 0
        removed_bytes = 0
        entries: list[tuple[Path, str, float, int]] = []
        for path in list(CACHE_ROOT.iterdir()):
            if not path.is_dir():
                continue
            name = path.name
            if name.startswith("install-"):
                try:
                    age = now - path.stat().st_mtime
                except OSError:
                    continue
                if age >= FAILED_TEMP_RETENTION_SECONDS:
                    size = _cache_entry_size(path)
                    shutil.rmtree(path, ignore_errors=True)
                    removed_entries += 1
                    removed_bytes += size
                continue
            if not re.fullmatch(r"[0-9a-f]{64}", name):
                continue
            size = _cache_entry_size(path)
            last_used = _cache_last_used(path)
            entries.append((path, name, last_used, size))

        survivors: list[tuple[Path, str, float, int]] = []
        for path, package_hash, last_used, size in entries:
            if package_hash not in _ACTIVE_PACKAGE_HASHES and now - last_used >= CACHE_RETENTION_SECONDS:
                shutil.rmtree(path, ignore_errors=True)
                removed_entries += 1
                removed_bytes += size
            else:
                survivors.append((path, package_hash, last_used, size))

        total_bytes = sum(item[3] for item in survivors)
        for path, package_hash, _, size in sorted(survivors, key=lambda item: item[2]):
            if total_bytes <= CACHE_MAX_BYTES:
                break
            if package_hash in _ACTIVE_PACKAGE_HASHES:
                continue
            shutil.rmtree(path, ignore_errors=True)
            total_bytes -= size
            removed_entries += 1
            removed_bytes += size
        return {
            "cache_bytes": max(total_bytes, 0),
            "removed_entries": removed_entries,
            "removed_bytes": removed_bytes,
            "active_entries": len(_ACTIVE_PACKAGE_HASHES),
        }


async def _ensure_installed(req: InstallRequest) -> tuple[Path, dict]:
    CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    await _cleanup_cache()
    lock = _INSTALL_LOCKS.setdefault(req.package_hash, asyncio.Lock())
    async with lock:
        package_dir = (CACHE_ROOT / req.package_hash).resolve()
        marker = package_dir / ".ready"
        if marker.exists():
            _touch_cache_entry(package_dir)
            metadata_file = package_dir / ".install.json"
            metadata = json.loads(metadata_file.read_text(encoding="utf-8")) if metadata_file.exists() else {
                **_runtime_info(), "installed_dependencies": {"python": [], "node": []}, "compatibility_warnings": [],
            }
            return package_dir, metadata
        temp = Path(tempfile.mkdtemp(prefix=f"install-{req.package_hash[:8]}-", dir=CACHE_ROOT))
        try:
            _extract(await _load_archive(req), temp)
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
            (temp / ".install.json").write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")
            (temp / ".ready").write_text("ready", encoding="utf-8")
            _touch_cache_entry(temp)
            if package_dir.exists():
                shutil.rmtree(package_dir)
            temp.replace(package_dir)
            return package_dir, metadata
        except Exception:
            # Keep failed install state briefly for local diagnosis; the hourly/LRU
            # cleanup removes it after FAILED_TEMP_RETENTION_SECONDS.
            try:
                (temp / ".failed").write_text(str(time.time()), encoding="utf-8")
            except OSError:
                pass
            raise
        finally:
            # This finally block runs before ``async with lock`` releases the
            # lock. Schedule the bounded lock-map cleanup for the next loop
            # turn, after __aexit__ has completed.
            def discard_install_lock() -> None:
                if _INSTALL_LOCKS.get(req.package_hash) is lock and not lock.locked():
                    _INSTALL_LOCKS.pop(req.package_hash, None)

            asyncio.get_running_loop().call_soon(discard_install_lock)


def _safe_name(name: str) -> str:
    return Path(name.replace("\\", "/")).name or "input.bin"


async def _materialize_input(item: InputFile, path: Path) -> None:
    if item.content_base64 is not None:
        try:
            raw = base64.b64decode(item.content_base64, validate=True)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"Invalid input {item.name}") from exc
        if len(raw) > MAX_OUTPUT_BYTES:
            raise HTTPException(status_code=413, detail=f"Input {item.name} exceeds 100MB")
        path.write_bytes(raw)
    elif item.download_url:
        total = 0
        try:
            async with (
                httpx.AsyncClient(timeout=300, trust_env=False, follow_redirects=False) as client,
                client.stream("GET", item.download_url, headers=item.download_headers) as response,
            ):
                response.raise_for_status()
                with path.open("wb") as handle:
                    async for chunk in response.aiter_bytes(1024 * 1024):
                        total += len(chunk)
                        if total > MAX_OUTPUT_BYTES:
                            raise HTTPException(status_code=413, detail=f"Input {item.name} exceeds 100MB")
                        handle.write(chunk)
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"Unable to download input {item.name}") from exc
        if item.expected_size is not None and total != item.expected_size:
            raise HTTPException(status_code=409, detail=f"Input {item.name} size mismatch")
    else:
        raise HTTPException(status_code=422, detail=f"Input {item.name} has no content")
    path.chmod(0o444)


async def _serialize_output(path: Path, relative_path: str, mime_type: str | None = None) -> dict:
    size = path.stat().st_size
    if size > MAX_OUTPUT_BYTES:
        raise HTTPException(status_code=413, detail=f"Output {path.name} exceeds 100MB")
    base = {"name": path.name, "relative_path": relative_path, "size": size, "mime_type": mime_type}
    if size <= INLINE_TRANSFER_BYTES:
        return {**base, "content_base64": base64.b64encode(path.read_bytes()).decode("ascii")}
    if not STORAGE_GATEWAY_URL or not STORAGE_PROJECT_TOKEN:
        raise HTTPException(status_code=503, detail="Large Skill output requires Storage Gateway")
    headers = {"Authorization": f"Bearer {STORAGE_PROJECT_TOKEN}"}
    content_type = mime_type or "application/octet-stream"
    async def chunks():
        with path.open("rb") as handle:
            while True:
                chunk = await asyncio.to_thread(handle.read, 1024 * 1024)
                if not chunk:
                    break
                yield chunk
    try:
        async with httpx.AsyncClient(timeout=300, trust_env=False) as client:
            signed = await client.post(
                f"{STORAGE_GATEWAY_URL}/v1/uploads/sign", headers=headers,
                json={"filename": path.name, "content_type": content_type, "size_bytes": size},
            )
            signed.raise_for_status()
            payload = signed.json()
            upload_headers = {str(k): str(v) for k, v in (payload.get("headers") or {}).items()}
            upload_headers.setdefault("Content-Length", str(size))
            upload = await client.put(
                str(payload["url"]), headers=upload_headers,
                content=chunks(),
            )
            upload.raise_for_status()
            return {**base, "content_ref": f"oss://{payload['object_key']}", "etag": upload.headers.get("etag", "").strip('"')}
    except (httpx.HTTPError, KeyError, ValueError, TypeError) as exc:
        raise HTTPException(status_code=502, detail=f"Unable to upload large output {path.name}") from exc


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
    _assert_platform_secrets_absent()
    cache = await _cleanup_cache()
    return {
        "status": "ok", **_runtime_info(),
        "execution_capacity": EXECUTION_CAPACITY.snapshot(),
        "office_capacity": OFFICE_CAPACITY.snapshot(),
        "queue_limit": RUNNER_MAX_QUEUE,
        "queue_wait_seconds": RUNNER_QUEUE_WAIT_SECONDS,
        "cache": {
            **cache,
            "retention_seconds": CACHE_RETENTION_SECONDS,
            "max_bytes": CACHE_MAX_BYTES,
        },
    }


@app.post("/install")
async def install(req: InstallRequest, x_skill_runner_token: str | None = Header(None)) -> dict:
    _auth(x_skill_runner_token)
    _assert_platform_secrets_absent()
    path, metadata = await _ensure_installed(req)
    return {"status": "ready", "package_hash": req.package_hash, "path": str(path), **metadata}


@app.post("/cache/cleanup")
async def cleanup_cache(x_skill_runner_token: str | None = Header(None)) -> dict:
    _auth(x_skill_runner_token)
    return {"status": "ok", **await _cleanup_cache()}


@app.delete("/cache/{package_hash}")
async def delete_cache_entry(
    package_hash: str,
    x_skill_runner_token: str | None = Header(None),
) -> dict:
    _auth(x_skill_runner_token)
    if not re.fullmatch(r"[0-9a-f]{64}", package_hash):
        raise HTTPException(status_code=422, detail="Invalid package hash")
    async with _CACHE_LOCK:
        if package_hash in _ACTIVE_PACKAGE_HASHES:
            raise HTTPException(status_code=409, detail="Skill package is currently executing")
        path = (CACHE_ROOT / package_hash).resolve()
        removed_bytes = _cache_entry_size(path) if path.exists() else 0
        shutil.rmtree(path, ignore_errors=True)
    return {"status": "deleted", "package_hash": package_hash, "removed_bytes": removed_bytes}


async def _execute_builtin_tool(
    req: BuiltinExecuteRequest,
) -> dict:
    """Execute a platform-owned file handler without loading a user Skill."""
    if len(req.inputs) > 20:
        raise HTTPException(status_code=422, detail="Builtin tools accept at most 20 input files")
    run_root = Path(tempfile.mkdtemp(prefix=f"builtin-{req.execution_id}-"))
    try:
        input_dir, output_dir = run_root / "input", run_root / "output"
        input_dir.mkdir()
        output_dir.mkdir()
        input_paths: list[Path] = []
        used_names: set[str] = set()
        for index, item in enumerate(req.inputs):
            safe_name = _safe_name(item.name)
            if safe_name in used_names:
                safe_name = f"{index + 1}-{safe_name}"
            used_names.add(safe_name)
            path = input_dir / safe_name
            await _materialize_input(item, path)
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
            outputs.append(await _serialize_output(
                path, path.relative_to(output_dir).as_posix(),
                (result.get("mime_types") or {}).get(path.name),
            ))
        return {
            "status": "success",
            "tool_kind": req.tool_kind,
            "action": req.action,
            "summary": result.get("summary"),
            "outputs": outputs,
        }
    finally:
        shutil.rmtree(run_root, ignore_errors=True)


@app.post("/execute-builtin")
async def execute_builtin_tool(
    req: BuiltinExecuteRequest,
    x_skill_runner_token: str | None = Header(None),
) -> dict:
    _auth(x_skill_runner_token)
    _assert_platform_secrets_absent()
    if req.tool_kind in {"spreadsheet", "document", "presentation"}:
        async with OFFICE_CAPACITY.slot(), EXECUTION_CAPACITY.slot():
            return await _execute_builtin_tool(req)
    async with EXECUTION_CAPACITY.slot():
        return await _execute_builtin_tool(req)


async def _execute(req: ExecuteRequest) -> dict:
    _ACTIVE_PACKAGE_HASHES.add(req.package_hash)
    try:
        package, _ = await _ensure_installed(req)
        if req.runtime not in {"python", "node", "agent_skill"}:
            raise HTTPException(status_code=422, detail="Skill is not executable")
        entrypoint, language = _script(package, req.script_path, req.entrypoint)
        run_root = Path(tempfile.mkdtemp(prefix=f"run-{req.execution_id}-"))
        _touch_cache_entry(package)
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
            await _materialize_input(item, path)
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
            outputs.append(await _serialize_output(path, path.relative_to(output_dir).as_posix()))
        return {"status": "success", "stdout": stdout[-4000:], "outputs": outputs}
    finally:
        if "run_root" in locals():
            _remove_tree(run_root)
        _ACTIVE_PACKAGE_HASHES.discard(req.package_hash)


@app.post("/execute")
async def execute(req: ExecuteRequest, x_skill_runner_token: str | None = Header(None)) -> dict:
    _auth(x_skill_runner_token)
    _assert_platform_secrets_absent()
    async with EXECUTION_CAPACITY.slot():
        return await _execute(req)
