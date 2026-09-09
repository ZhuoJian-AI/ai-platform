"""Isolated executor for AI Platform's fixed, reviewed tools only."""

from __future__ import annotations

import asyncio
import base64
import importlib.metadata
import os
import platform
import secrets
import shutil
import subprocess
import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

import httpx
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from builtin_tools import BuiltinToolError, execute_builtin

EXECUTOR_TOKEN = os.getenv(
    "TOOL_EXECUTOR_TOKEN",
    "tool-executor-dev-token-change-in-production",
)
MAX_FILE_BYTES = 100 * 1024 * 1024
MAX_INPUT_FILES = 20
MAX_OUTPUT_FILES = 20
MAX_CONCURRENCY = int(os.getenv("TOOL_EXECUTOR_MAX_CONCURRENCY", "4"))
MAX_QUEUE = int(os.getenv("TOOL_EXECUTOR_MAX_QUEUE", "100"))
QUEUE_WAIT_SECONDS = int(os.getenv("TOOL_EXECUTOR_QUEUE_WAIT_SECONDS", "300"))
OFFICE_CONCURRENCY = int(os.getenv("TOOL_EXECUTOR_OFFICE_CONCURRENCY", "1"))
FORBIDDEN_PLATFORM_SECRET_KEYS = (
    "DATABASE_URL",
    "REDIS_URL",
    "POSTGRES_PASSWORD",
    "REDIS_PASSWORD",
    "SECRET_KEY",
    "MASTER_ENCRYPTION_KEY",
    "CRM_API_KEY",
    "MES_API_KEY",
    "STORAGE_PROJECT_TOKEN",
)
TOOL_KINDS = (
    "spreadsheet",
    "document",
    "presentation",
    "pdf",
    "text",
    "web",
    "image",
    "archive",
)

app = FastAPI(title="AI Platform Tool Executor")


class ExecutorCapacity:
    """Bound active work and reject an unbounded internal queue."""

    def __init__(self, limit: int, queue_limit: int, wait_seconds: int) -> None:
        self.limit = max(1, limit)
        self.queue_limit = max(0, queue_limit)
        self.wait_seconds = max(1, wait_seconds)
        self.active = 0
        self.waiting = 0
        self._condition = asyncio.Condition()

    async def _acquire(self) -> None:
        async with self._condition:
            if self.waiting >= self.queue_limit:
                raise HTTPException(status_code=429, detail="平台工具执行队列已满")
            self.waiting += 1
            try:
                await asyncio.wait_for(
                    self._condition.wait_for(lambda: self.active < self.limit),
                    timeout=self.wait_seconds,
                )
            except TimeoutError as exc:
                raise HTTPException(status_code=503, detail="平台工具执行繁忙，请稍后重试") from exc
            finally:
                self.waiting -= 1
            self.active += 1

    async def _release(self) -> None:
        async with self._condition:
            self.active = max(0, self.active - 1)
            self._condition.notify_all()

    @asynccontextmanager
    async def slot(self) -> AsyncIterator[None]:
        await self._acquire()
        try:
            yield
        finally:
            await self._release()

    def snapshot(self) -> dict[str, int]:
        return {
            "active": self.active,
            "waiting": self.waiting,
            "limit": self.limit,
            "queue_limit": self.queue_limit,
        }


EXECUTION_CAPACITY = ExecutorCapacity(MAX_CONCURRENCY, MAX_QUEUE, QUEUE_WAIT_SECONDS)
OFFICE_CAPACITY = ExecutorCapacity(OFFICE_CONCURRENCY, MAX_QUEUE, QUEUE_WAIT_SECONDS)


class InputFile(BaseModel):
    file_id: str
    name: str = Field(min_length=1, max_length=255)
    content_base64: str | None = None
    download_url: str | None = None
    download_headers: dict[str, str] = Field(default_factory=dict)
    expected_size: int | None = Field(None, ge=1, le=MAX_FILE_BYTES)

    model_config = {"extra": "forbid"}


class BuiltinExecuteRequest(BaseModel):
    tool_kind: Literal[
        "spreadsheet",
        "document",
        "presentation",
        "pdf",
        "text",
        "web",
        "image",
        "archive",
    ]
    action: str = Field(min_length=1, max_length=32)
    params: dict = Field(default_factory=dict)
    inputs: list[InputFile] = Field(default_factory=list, max_length=MAX_INPUT_FILES)
    execution_id: str = Field(min_length=1, max_length=128)
    timeout_seconds: int = Field(120, ge=1, le=600)

    model_config = {"extra": "forbid"}


def _auth(token: str | None) -> None:
    if not token or not secrets.compare_digest(token, EXECUTOR_TOKEN):
        raise HTTPException(status_code=401, detail="平台工具执行凭据无效")


def _assert_platform_secrets_absent() -> None:
    leaked = sorted(key for key in FORBIDDEN_PLATFORM_SECRET_KEYS if os.getenv(key))
    if leaked:
        raise HTTPException(status_code=503, detail="平台工具执行器包含不应注入的主服务凭据")


def _command_version(argv: list[str]) -> str | None:
    try:
        result = subprocess.run(argv, capture_output=True, timeout=5, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    lines = (result.stdout or result.stderr or b"").decode("utf-8", errors="replace").strip().splitlines()
    return lines[0] if lines else None


def _package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def _safe_name(name: str) -> str:
    return Path(name.replace("\\", "/")).name or "input.bin"


async def _materialize_input(item: InputFile, path: Path) -> None:
    if (item.content_base64 is None) == (item.download_url is None):
        raise HTTPException(status_code=422, detail=f"输入文件 {item.name} 必须且只能提供一种内容来源")
    if item.content_base64 is not None:
        try:
            raw = base64.b64decode(item.content_base64, validate=True)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"输入文件 {item.name} 内容无效") from exc
        if not raw or len(raw) > MAX_FILE_BYTES:
            raise HTTPException(status_code=413, detail=f"输入文件 {item.name} 大小超出限制")
        path.write_bytes(raw)
    else:
        total = 0
        try:
            async with (
                httpx.AsyncClient(timeout=300, trust_env=False, follow_redirects=False) as client,
                client.stream("GET", str(item.download_url), headers=item.download_headers) as response,
            ):
                response.raise_for_status()
                with path.open("wb") as handle:
                    async for chunk in response.aiter_bytes(1024 * 1024):
                        total += len(chunk)
                        if total > MAX_FILE_BYTES:
                            raise HTTPException(status_code=413, detail=f"输入文件 {item.name} 大小超出限制")
                        handle.write(chunk)
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"无法读取输入文件 {item.name}") from exc
        if total == 0:
            raise HTTPException(status_code=422, detail=f"输入文件 {item.name} 为空")
        if item.expected_size is not None and total != item.expected_size:
            raise HTTPException(status_code=409, detail=f"输入文件 {item.name} 大小校验失败")
    path.chmod(0o444)


async def _serialize_output(
    path: Path,
    relative_path: str,
    mime_type: str | None,
    verification: dict | None,
) -> dict:
    size = path.stat().st_size
    if size <= 0 or size > MAX_FILE_BYTES:
        raise HTTPException(status_code=413, detail=f"输出文件 {path.name} 大小超出限制")
    return {
        "name": path.name,
        "relative_path": relative_path,
        "size": size,
        "mime_type": mime_type,
        "format_verified": bool(verification),
        **(verification or {}),
        "content_base64": base64.b64encode(path.read_bytes()).decode("ascii"),
    }


async def _execute_builtin_tool(req: BuiltinExecuteRequest) -> dict:
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
            raise HTTPException(status_code=408, detail="平台工具执行超时") from exc
        except BuiltinToolError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        files = [path for path in output_dir.rglob("*") if path.is_file()]
        if len(files) > MAX_OUTPUT_FILES:
            raise HTTPException(status_code=422, detail="平台工具生成的文件数量超出限制")
        outputs = []
        for path in files:
            verification = (result.get("output_verification") or {}).get(path.name)
            outputs.append(await _serialize_output(
                path,
                path.relative_to(output_dir).as_posix(),
                (result.get("mime_types") or {}).get(path.name),
                verification,
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


@app.get("/health")
async def health() -> dict:
    _assert_platform_secrets_absent()
    return {
        "status": "ok",
        "service": "tool-executor",
        "python_version": platform.python_version(),
        "libreoffice_version": _command_version(["libreoffice", "--version"]),
        "tesseract_version": _command_version(["tesseract", "--version"]),
        "tool_kinds": TOOL_KINDS,
        "dependencies": {
            name: _package_version(name)
            for name in (
                "openpyxl",
                "pandas",
                "python-docx",
                "python-pptx",
                "PyMuPDF",
                "pypdf",
                "Pillow",
                "pytesseract",
            )
        },
        "capacity": EXECUTION_CAPACITY.snapshot(),
        "office_capacity": OFFICE_CAPACITY.snapshot(),
    }


@app.post("/execute-builtin")
async def execute_builtin_tool(
    req: BuiltinExecuteRequest,
    x_tool_executor_token: str | None = Header(None),
) -> dict:
    _auth(x_tool_executor_token)
    _assert_platform_secrets_absent()
    if req.tool_kind in {"spreadsheet", "document", "presentation"}:
        async with OFFICE_CAPACITY.slot(), EXECUTION_CAPACITY.slot():
            return await _execute_builtin_tool(req)
    async with EXECUTION_CAPACITY.slot():
        return await _execute_builtin_tool(req)
