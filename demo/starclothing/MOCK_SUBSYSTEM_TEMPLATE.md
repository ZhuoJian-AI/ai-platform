# Mock 子系统骨架模板

> 从零写一个新 mock 子系统（如 `inventory` / `logistics`）的最小可运行骨架。
> Starclothing 的 PLM / SCM 子系统按此模板扩展。

---

## 文件结构

```
mock/mock/systems/<sysname>/
├── __init__.py      # 4 行：构造 FastAPI 子应用，挂载 router
├── routes.py        # APIRouter(prefix="/api/v1") + 端点定义
└── data.py          # dataclass PlmData + LazyTenantRegistry 多租户数据
```

三个文件 + 在 `mock/mock/core/registry.py` 注册一行 SystemDef，子系统即接入 mock 网关。

---

## `__init__.py`（4 行模板）

```python
"""<SysName> 子系统——构造可被网关挂载的 FastAPI 子应用。"""

from mock.core.registry import by_key
from mock.core.server import build_app
from . import routes

_SYS = by_key("<sysname>")
app = build_app(
    title=_SYS.name,
    version="1.0.0",
    system_key=_SYS.key,
    api_key=_SYS.api_key,
    keys_to_tenants=_SYS.keys_to_tenants,
    router=routes.router,
)
```

---

## `routes.py`（最小骨架，含 list + get + 业务逻辑 3 类端点）

```python
"""<SysName> 端点。"""

from typing import Annotated
from fastapi import APIRouter, Body, Depends, Query
from mock.core.tenant import get_tenant
from . import data as D
from . import P  # tenant-aware 数据 loader

router = APIRouter(prefix="/api/v1", tags=["<sysname>"])


# ── 健康检查（mock 网关自动加 /health，子系统无需写）──


# ── list 端点（query 参数过滤）── query 参数不受 path-param bug 影响，推荐
@router.get("/items", operation_id="listItems", summary="条目列表")
def list_items(
    tenant: Annotated[str, Depends(get_tenant)],
    keyword: Annotated[str | None, Query()] = None,
    category: Annotated[str | None, Query()] = None,
) -> list[dict]:
    rows = P.load(tenant).items
    if keyword:
        rows = [r for r in rows if keyword in r.get("name", "")]
    if category:
        rows = [r for r in rows if r["category"] == category]
    return rows


# ── get 端点（path 参数）—— ⚠️ 当前 path-param wrapper 有 bug（见 KNOWN_ISSUES.md）
# 推荐改用 list + query 过滤替代；若必须用 path，agent 端会 fallback
@router.get("/items/{item_code}", operation_id="getItem", summary="条目详情")
def get_item(
    tenant: Annotated[str, Depends(get_tenant)],
    item_code: Annotated[str, Query()] = None,  # 改 Query 规避 path-param bug
) -> dict:
    rows = P.load(tenant).items
    for r in rows:
        if r["code"] == item_code:
            return r
    from fastapi import HTTPException
    raise HTTPException(404, f"item {item_code} not found")


# ── 业务逻辑端点（评分 / 比对 / 检测等）—— PD-2 compareQuotations 是范例
@router.get("/compare", operation_id="compareItems", summary="条目对比 + 评分")
def compare_items(
    tenant: Annotated[str, Depends(get_tenant)],
    category: Annotated[str, Query()] = None,
) -> dict:
    rows = P.load(tenant).items
    if category:
        rows = [r for r in rows if r["category"] == category]
    if not rows:
        return {"category": category, "items": []}
    # 评分示例：价格越低分越高（40 满），评分越短分越高（30 满）
    prices = [r["price"] for r in rows]
    price_min, price_max = min(prices), max(prices)
    for r in rows:
        r["price_score"] = (
            (price_max - r["price"]) / (price_max - price_min) * 40
            if price_max > price_min else 20.0
        )
    return {"category": category, "best_item": min(rows, key=lambda x: x["price"])["code"], "items": rows}


# ── 写入端点（POST，用于演示写动作）—— PD-1 addDefectRecord 是范例
@router.post("/items", operation_id="createItem", summary="新建条目")
def create_item(
    tenant: Annotated[str, Depends(get_tenant)],
    payload: Annotated[dict, Body()] = None,
) -> dict:
    p = payload or {}
    return {"code": p.get("code"), "status": "ok", "tenant": tenant}
```

---

## `data.py`（dataclass + 多租户懒加载）

```python
"""<SysName> 数据集——按 tenant 隔离。"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
import random

from mock.core.registry import LazyTenantRegistry


@dataclass
class <SysName>Data:
    items: list[dict]
    # ... 其他业务表


BASE_DATE = datetime(2026, 7, 1)


def _build_<org>(tenant: str) -> <SysName>Data:
    """构造 <org> 租户的样本数据。"""
    items_specs = [
        # (code, name, category, price, off)
        ("ITM-001", "条目一", "A 类", 100.0, -10),
        ("ITM-002", "条目二", "A 类", 80.0, -8),
        ("ITM-003", "条目三", "B 类", 200.0, -5),
        ("ITM-004", "条目四", "B 类", 180.0, -3),
    ]
    items = []
    for code, name, cat, price, off in items_specs:
        items.append({
            "code": code,
            "name": name,
            "category": cat,
            "price": price,
            "date": f"{BASE_DATE + timedelta(days=off)}",
        })
    return <SysName>Data(items=items)


# ── 多租户注册表（懒构建）── 复制改 <org> 名即可扩展
TENANTS = LazyTenantRegistry[<SysName>Data]({
    "<org>": _build_<org>,
    # 新增 tenant："<org2>": _build_<org2>,
})


# ── 模块级 P：让 routes.py 用 P.load(tenant) 拿当前租户数据
class _Loader:
    def load(self, tenant: str) -> <SysName>Data:
        return TENANTS.get(tenant)


P = _Loader()
```

---

## 注册到 `mock/mock/core/registry.py`

```python
SystemDef(
    key="<sysname>",
    name="<SysName> 中文全称",
    prefix="/<sysname>",
    api_key="<sysname>-<org>-demo-key",
    keys_to_tenants={"<sysname>-<org>-demo-key": "<org>"},
),
```

参考 Starclothing 的 5 个 SystemDef（CRM/ERP/HRM/MES/PLM/SCM）。

---

## OpenAPI 导出（给 seed_mock_connectors.py 用）

```bash
# 启动 mock 后
curl -s http://localhost:8010/<sysname>/openapi.json -H "X-API-Key: <sysname>-<org>-demo-key" \
  > mock/openapi/<sysname>.json
```

`seed_<org>_mock_connectors.py` 会从这个 JSON 自动注册连接器 + 端点 + 数据接口。

---

## 多租户测试

```bash
# 不同 API key → 不同 tenant 数据
curl -s "http://localhost:8010/<sysname>/api/v1/items" \
  -H "X-API-Key: <sysname>-<org1>-demo-key"  # 返回 org1 数据
curl -s "http://localhost:8010/<sysname>/api/v1/items" \
  -H "X-API-Key: <sysname>-<org2>-demo-key"  # 返回 org2 数据
```

---

## 设计要点（避坑）

1. **list 端点用 query 参数，不用 path 参数**：path-param 占位符替换有 bug（见 `KNOWN_ISSUES.md`），agent 调 path 端点会 404，需要 fallback 到 list。
2. **`get_tenant` 依赖注入**：每个端点都要 `Annotated[str, Depends(get_tenant)]`，从 X-API-Key 反查 tenant 写入 `request.state.tenant`。
3. **数据隔离**：`data.py` 用 `LazyTenantRegistry` 按 tenant 构建独立数据集，避免租户间污染。
4. **`api_key` vs `keys_to_tenants`**：`api_key` 是默认 key（兼容旧敏睿制造），`keys_to_tenants` 是多租户映射。新组织建议只填 `keys_to_tenants`。
5. **mock 容器无 volume mount**：改了 `data.py` / `routes.py` 必须 `docker cp` 进容器再 `docker restart ai_infra_mock`，不像 backend 有 volume 同步。
6. **OpenAPI path 占位符**：`/api/v1/items/{item_code}` 在 OpenAPI 文档里是占位符，agent wrapper 当前不替换，所以推荐用 query 参数。
7. **`operation_id` 必填**：seed_mock_connectors 通过 operation_id 注册数据接口，缺了端点不会出现在数据接口目录里。

---

## 参考实现

- `mock/mock/systems/plm/`：21 端点 PLM 子系统，含 styles / boms / fabrics / defect-history / feasibility-logs / overdue-orders 等
- `mock/mock/systems/scm/`：17 端点 SCM 子系统，含 quotations / compareQuotations / estimateLeadtime / getLeadtimeDiff / capacityCalendar 等
- `mock/mock/core/tenant.py`：多租户中间件实现
- `mock/mock/core/server.py` + `registry.py`：mock 网关骨架
