"""LLM Router — FastAPI application entry point."""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.config import settings
from app.database import async_session_factory
from app.mcp.server import mcp, mcp_app
from app.proxy.router import proxy_router
from app.services.admin_service import ensure_super_admin

logger = structlog.get_logger()

# 实例化 MCP ASGI 子应用（同时惰性创建 session_manager，供 lifespan 启动 task group）。
_mcp_asgi = mcp_app()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan: startup and shutdown events."""
    logger.info("llm_router_starting", env=settings.app_env, debug=settings.debug)

    # 启动时确保 super_admin 存在
    async with async_session_factory() as session:
        admin = await ensure_super_admin(session)
        await session.commit()
        logger.info(
            "super_admin_ready",
            username=admin.username,
            message="If newly created, check logs for initial password",
        )

    # 孤儿 run 清理：上一进程的内存图任务与等待队列消费者已随进程死亡，
    # 残留 queued/running 行会永远卡住（Redis 临时许可会由租约自动过期）。
    # 行会永远卡住（前端 resume 端点虽能兜底单条，但启动期一次性清扫更干净）。幂等。
    from sqlalchemy import text as _sa_text

    async with async_session_factory() as session:
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

    # 启动 MCP session manager task group（FastAPI app.mount 不跑子应用 lifespan，
    # 故在此显式启动；否则 streamable_http 握手报 "Task group is not initialized"）。
    async with mcp.session_manager.run():
        yield
    if install_resume_task is not None and not install_resume_task.done():
        install_resume_task.cancel()
    if not extension_sync_task.done():
        extension_sync_task.cancel()
    logger.info("llm_router_stopping")


app = FastAPI(
    title=settings.app_name,
    description="Enterprise LLM API routing platform with DLP security fence",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.is_development else None,
    redoc_url="/redoc" if settings.is_development else None,
)

# CORS — 允许前端本地开发
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 管理 API 路由
app.include_router(api_router)

# LLM 代理路由 — 这是最核心的部分
app.include_router(proxy_router)

# MCP server —— 把归口用户 scope 内五项能力暴露给第三方智能体终端（/mcp）。
# 第三方终端经 skills 包内 .mcp.json 携带内嵌 Bearer 访问，鉴权与平台内部同源。
# 复用模块级 _mcp_asgi（已惰性创建 session_manager）；lifespan 中启动其 task group。
app.mount("/mcp", _mcp_asgi)


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "ok"}
