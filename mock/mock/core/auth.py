"""X-API-Key 鉴权中间件——多租户：单系统多把 key 各映射到不同 tenant。

对应平台连接器 ``auth_type=apikey``、``auth_config={"header_key":"X-API-Key","api_key":...}``。
不同组织的连接器使用各自专属的 ``api_key``，mock 据此判定 tenant，调用对应数据集。

放行路径：``/health``、``/openapi.json``、``/docs``、``/redoc`` 及其静态资源——
seed 脚本与平台「导入 spec」需在无 key 情况下读取 OpenAPI。
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

# 子应用被网关 mount 后，``scope["path"]`` 为含前缀的完整路径（如 /mes/health），
# 故用「后缀匹配」放行公共端点；业务路由无以这些后缀结尾者。
_PUBLIC_SUFFIXES = ("/health", "/openapi.json", "/docs", "/redoc")
_HEADER = "X-API-Key"


def is_public(path: str) -> bool:
    return any(path.endswith(s) for s in _PUBLIC_SUFFIXES)


class ApiKeyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if is_public(request.scope.get("path", "")):
            return await call_next(request)

        api_key = request.headers.get(_HEADER, "")
        # 多租户：app.state.keys_to_tenants = {api_key -> tenant_slug}
        mapping: dict[str, str] = getattr(request.app.state, "keys_to_tenants", {}) or {}
        # 单租户回退：app.state.api_key（老 demo 单 key 模式，归 minrui）
        legacy_key = getattr(request.app.state, "api_key", "")

        tenant: str | None = None
        if api_key and api_key in mapping:
            tenant = mapping[api_key]
        elif legacy_key and api_key == legacy_key:
            tenant = "minrui"

        if tenant is None:
            return JSONResponse(
                status_code=401,
                content={"detail": f"missing or invalid {_HEADER}"},
            )

        request.state.tenant = tenant
        return await call_next(request)
