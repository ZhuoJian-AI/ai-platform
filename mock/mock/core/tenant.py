"""多租户支持——同一套 mock 子系统按 ``X-API-Key`` 映射到不同企业数据集。

设计要点：
  - 每个租户（minrui / starclothing / …）在每个 mock 子系统下持有一份独立数据；
  - ``SystemDef.keys_to_tenants`` 把多把演示用 API key 映射到 tenant slug；
  - ``ApiKeyMiddleware`` 校验时把命中的 tenant 写入 ``request.state.tenant``；
  - 业务路由经 ``Depends(get_tenant)`` 取 tenant，再调 ``data.load(tenant)`` 取数。

向后兼容：未携带 ``X-API-Key`` 的请求（仅 ``/health`` 等公共端点允许）默认 tenant
为 ``minrui``；老 minrui 演示用 key 仍走 minrui 数据集，行为不变。
"""

from __future__ import annotations

from fastapi import Request

DEFAULT_TENANT = "minrui"


def resolve_tenant(request: Request, system_key: str) -> str:
    """据 ``X-API-Key`` 解析 tenant slug。

    命中 ``app.state.keys_to_tenants`` 的 key 返回对应 tenant；其余情形返回
    ``DEFAULT_TENANT``（仅在公共放行路径会走到这里——业务路径已被 middleware 401 拦截）。
    """
    mapping: dict[str, str] = getattr(request.app.state, "keys_to_tenants", {}) or {}
    api_key = request.headers.get("X-API-Key", "")
    if api_key and api_key in mapping:
        return mapping[api_key]
    return DEFAULT_TENANT


def get_tenant(request: Request) -> str:
    """路由依赖：从 ``request.state.tenant`` 读取（由 middleware 写入）。"""
    return getattr(request.state, "tenant", DEFAULT_TENANT)


# ───────────────────────── 多租户懒构建辅助 ─────────────────────────
# 各 mock 子系统在 ``data.py`` 用 ``LazyTenantRegistry`` 包装两个 tenant 的 builder，
# 避免模块导入时 eager build 触发跨系统循环导入回退（CRM↔MES 互相引用工单/订单号）。
#
# 行为：
#   - ``load(tenant)`` 首次调用时触发 builder，缓存结果；
#   - 若构建期间递归调用同 system 同 tenant（循环依赖），抛 ``TenantBuilding``，
#     调用方（跨系统函数）捕获后用占位 ref，等所有系统 import 完成后的首次真实
#     ``load`` 会重新解析真实 ref（占位仅出现在「被打断那次构建」里，后续 load 命中缓存）。
#
# 由于不同 system 的 DataCls 不同，泛型用 TypeVar 表达。


from typing import Callable, Generic, TypeVar

_T = TypeVar("_T")


class TenantBuilding(Exception):
    """构造中递归调用——调用方应捕获并用占位 ref。"""


class LazyTenantRegistry(Generic[_T]):
    def __init__(self, builders: dict[str, Callable[[], _T]]):
        self._builders = builders
        self._cache: dict[str, _T] = {}
        self._building: set[str] = set()

    def load(self, tenant: str) -> _T:
        if tenant in self._cache:
            return self._cache[tenant]
        if tenant not in self._builders:
            raise KeyError(f"unknown tenant: {tenant}")
        if tenant in self._building:
            raise TenantBuilding(tenant)
        self._building.add(tenant)
        try:
            data = self._builders[tenant]()
            self._cache[tenant] = data
            return data
        finally:
            self._building.discard(tenant)

    # dict-like 接口，向后兼容 ``TENANTS["minrui"]`` / ``"minrui" in TENANTS`` / ``TENANTS.keys()``
    def __getitem__(self, tenant: str) -> _T:
        return self.load(tenant)

    def __contains__(self, tenant: object) -> bool:
        return tenant in self._builders

    def keys(self) -> list[str]:
        return list(self._builders.keys())

    def known_tenants(self) -> list[str]:
        return list(self._builders.keys())

    def is_known(self, tenant: str) -> bool:
        return tenant in self._builders
