"""子系统应用工厂——各 mock 系统共用统一的 FastAPI 装配方式。

每个子系统 ``__init__.py`` 构造一个 ``APIRouter(prefix="/api/v1")`` 写满路由，
再调用 ``build_app`` 注入鉴权与 ``/health``，得到可被网关 ``app.mount(prefix, app)``
挂载的子应用。子应用 OpenAPI 路径相对（不含前缀），与平台 spec_parser 的
``base_url + path`` 拼接约定吻合。
"""

from __future__ import annotations

from fastapi import APIRouter, FastAPI

from mock.core.auth import ApiKeyMiddleware


def build_app(
    *,
    title: str,
    version: str,
    system_key: str,
    api_key: str = "",
    keys_to_tenants: dict[str, str] | None = None,
    router: APIRouter,
) -> FastAPI:
    """构造子系统子应用。

    多租户模式：传 ``keys_to_tenants={"key1":"minrui","key2":"starclothing"}``，
    ``ApiKeyMiddleware`` 据此把命中 key 写入 ``request.state.tenant``。
    单租户回退：仅传 ``api_key`` 时，老 demo key 归 minrui（向后兼容）。
    """
    app = FastAPI(
        title=title,
        version=version,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )
    app.state.system_key = system_key
    app.state.api_key = api_key
    app.state.keys_to_tenants = keys_to_tenants or {}

    app.add_middleware(ApiKeyMiddleware)

    @app.get("/health", tags=["meta"])
    def health() -> dict:
        return {
            "status": "ok",
            "system": system_key,
            "version": version,
            "tenants": list(app.state.keys_to_tenants.values()) or ["minrui"],
        }

    app.include_router(router)
    return app
