"""网关应用——单进程挂载所有 mock 子系统。

``python -m mock`` → ``uvicorn mock.gateway:app``（默认 8010）。
访问：
  - 根 ``/`` 列出子系统
  - ``/<prefix>/health`` 各子系统健康
  - ``/<prefix>/openapi.json`` 各子系统 OpenAPI（seed 与平台导入用）
  - ``/<prefix>/api/v1/...`` 业务接口（需 X-API-Key）
"""

from __future__ import annotations

from fastapi import FastAPI

from mock.core.registry import MOCK_SYSTEMS


def create_app() -> FastAPI:
    app = FastAPI(
        title="企业 Mock 网关",
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    @app.get("/", tags=["meta"])
    def index() -> dict:
        return {
            "service": "enterprise-mock gateway",
            "systems": [
                {"key": s.key, "name": s.name, "prefix": s.prefix, "openapi": f"{s.prefix}/openapi.json"}
                for s in MOCK_SYSTEMS
            ],
        }

    @app.get("/health", tags=["meta"])
    def health() -> dict:
        return {"status": "ok", "systems": [s.key for s in MOCK_SYSTEMS]}

    for s in MOCK_SYSTEMS:
        app.mount(s.prefix, s.load_app())

    return app


app = create_app()
