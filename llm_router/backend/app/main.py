"""LLM Router — FastAPI application entry point."""

import asyncio
import re
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, HTTPException, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.oauth import well_known_router
from app.api.router import api_router
from app.config import settings
from app.database import async_session_factory
from app.mcp.server import mcp, organization_mcp_app
from app.proxy.router import proxy_router

logger = structlog.get_logger()

# 实例化 MCP ASGI 子应用（同时惰性创建 session_manager，供 lifespan 启动 task group）。
_organization_mcp_asgi = organization_mcp_app()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan: startup and shutdown events."""
    logger.info("llm_router_starting", env=settings.app_env, debug=settings.debug)

    # 孤儿 run 清理：上一进程的内存图任务与等待队列消费者已随进程死亡，
    # 残留 queued/running 行会永远卡住（Redis 临时许可会由租约自动过期）。
    # 行会永远卡住（前端 resume 端点虽能兜底单条，但启动期一次性清扫更干净）。幂等。
    from sqlalchemy import text as _sa_text

    async with async_session_factory() as session:
        from app.services.ai_quota_service import quota_startup_preflight

        await quota_startup_preflight(session)
        result = await session.execute(
            _sa_text(
                "UPDATE agent_runs SET status='error', error='interrupted by server restart' "
                "WHERE status IN ('queued', 'running')"
            )
        )
        await session.commit()
        if result.rowcount:
            logger.info("orphan_runs_cleaned", count=result.rowcount)

    # DLP 规则库为代码内置（ALL_BUILTIN_RULES）。无全局规则概念——
    # 新建组织时由 organization_service.create_organization 自动播种为组织级规则，
    # 组织管理员可启停；存量组织由迁移 0030 一次性回填。

    # 预热 LangGraph 代理流水线单例图（编译 + 首次实例化）
    from app.graph import get_proxy_graph

    get_proxy_graph()
    logger.info("proxy_graph_ready")

    # 智能体协调由独立 DSH Runtime 承担；本进程只保留平台能力与授权边界。
    logger.info("agent_runtime", coordinator="dsh")

    # Retry interrupted executable Skill dependency installs after restart.
    install_resume_task = None
    if settings.code_skills_enabled:
        from app.services.skill_runner_client import resume_pending_installs
        install_resume_task = asyncio.create_task(resume_pending_installs())

    # PostgreSQL is the release fact source.  If DSH restarted independently,
    # restore the last active immutable manifest after both services are up.
    from app.services.platform_extension_service import sync_active_release_to_runtime
    extension_sync_task = asyncio.create_task(sync_active_release_to_runtime())
    from app.services.platform_extension_discovery import run_catalog_sync_scheduler
    catalog_sync_task = asyncio.create_task(run_catalog_sync_scheduler())
    from app.services.subsystem_integration_service import run_subsystem_sync_scheduler
    subsystem_sync_task = asyncio.create_task(run_subsystem_sync_scheduler())

    # 启动 MCP session manager task group（FastAPI app.mount 不跑子应用 lifespan，
    # 故在此显式启动；否则 streamable_http 握手报 "Task group is not initialized"）。
    async with mcp.session_manager.run():
        yield
    if install_resume_task is not None and not install_resume_task.done():
        install_resume_task.cancel()
    if not extension_sync_task.done():
        extension_sync_task.cancel()
    if not catalog_sync_task.done():
        catalog_sync_task.cancel()
    if not subsystem_sync_task.done():
        subsystem_sync_task.cancel()
    logger.info("llm_router_stopping")


app = FastAPI(
    title=settings.app_name,
    description="Enterprise LLM API routing platform with DLP security fence",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.is_development else None,
    redoc_url="/redoc" if settings.is_development else None,
)


def _redacted_validation_errors(exc: RequestValidationError) -> list[dict]:
    """Keep actionable validation locations without echoing request secrets."""
    return [
        {key: error[key] for key in ("type", "loc", "msg") if key in error}
        for error in exc.errors()
    ]


_STABLE_FILE_PATH_RE = re.compile(
    r"/(?:terminal/)?files/[0-9a-fA-F]{8}-[0-9a-fA-F-]{27,}(?:/|$)"
)


@app.exception_handler(HTTPException)
async def conceal_stable_file_forbidden(
    request: Request,
    exc: HTTPException,
):
    """Do not reveal whether an opaque stable file id exists."""
    if exc.status_code == 403 and _STABLE_FILE_PATH_RE.search(request.url.path):
        return JSONResponse(status_code=404, content={"detail": "File not found"})
    return await http_exception_handler(request, exc)


@app.exception_handler(RequestValidationError)
async def request_validation_error_handler(
    _request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    # Pydantic's default error representation includes ``input`` and sometimes
    # ``ctx``.  Tokens or signed URLs in malformed bodies must not be reflected
    # to clients, access logs or observability collectors.
    return JSONResponse(status_code=422, content={"detail": _redacted_validation_errors(exc)})

# Credentialed browser calls use an explicit origin and header allowlist.
_browser_origins = [
    origin.strip().rstrip("/")
    for origin in settings.browser_allowed_origins.split(",")
    if origin.strip()
]
if settings.is_development:
    _browser_origins.extend(["http://localhost:3000", "http://localhost:5173"])
for _public_origin in (
    settings.normalized_oauth_public_base_url,
    settings.normalized_proxy_base_url or "",
):
    if _public_origin and _public_origin not in _browser_origins:
        _browser_origins.append(_public_origin)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_browser_origins,
    allow_credentials=True,
    allow_methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-CSRF-Token", "X-Request-ID"],
)

# 管理 API 路由
app.include_router(api_router)
app.include_router(well_known_router)

# LLM 代理路由 — 这是最核心的部分
app.include_router(proxy_router)

# Organization-specific OAuth resource. Generic API-key MCP access is not
# mounted: employee role changes must revoke personal-AI access immediately.
app.mount("/mcp/organizations", _organization_mcp_asgi)


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "ok"}
