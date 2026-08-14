"""把 ``mock/`` 各业务系统（MES / CRM / …）注册为平台连接器 + 数据接口 + agent 技能。

幂等：按 slug / name 去重，已存在则更新，可安全重复执行。挂「敏睿制造」组织（slug=``minrui``）。

对 ``mock.core.registry.MOCK_SYSTEMS`` 每个子系统：
  1. 拉取 ``/<prefix>/openapi.json``（不可达则回退 ``mock/openapi/<key>.json`` 快照）；
  2. 建或更新 ``ToolConnector``（auth_type=apikey，X-API-Key）；
  3. ``import_spec`` 生成 ``ToolEndpoint``（同名幂等，ID 跨重跑稳定）；
  4. 镜像写入 ``DataSystem`` + ``DataInterface``（供「数据接口」管理页展示样例）；
  5. 建或更新 ``SkillFolder`` + ``skill.md``，``bound_endpoint_ids`` 绑定该系统只读 GET 端点，
     供终端 agent 经 ``execute_endpoint`` 调用 mock。

前置：先启动 mock 网关（``make mock-up`` 或 ``python -m mock``）。可用 ``MOCK_BASE_URL`` 覆盖地址。

用法:
    cd llm_router/backend
    python scripts/seed_mock_connectors.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

# backend/（导入 app）与 仓库根/mock/（导入 mock 包）纳入 sys.path
_BACKEND_DIR = Path(__file__).resolve().parent.parent
_REPO_ROOT = _BACKEND_DIR.parent.parent
_MOCK_ROOT = _REPO_ROOT / "mock"
for _p in (str(_BACKEND_DIR), str(_MOCK_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import httpx  # noqa: E402
import structlog  # noqa: E402
from mock.core.registry import MOCK_SYSTEMS  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.database import async_session_factory  # noqa: E402
from app.models.connector import ToolConnector  # noqa: E402
from app.models.data_interface import DataInterface, DataSystem  # noqa: E402
from app.models.organization import Organization  # noqa: E402
from app.models.skill import SkillFolder  # noqa: E402
from app.schemas.connector import ToolConnectorCreate, ToolConnectorUpdate  # noqa: E402
from app.schemas.data_interface import DataInterfaceCreate, DataSystemCreate  # noqa: E402
from app.schemas.skill import SkillFileCreate, SkillFolderCreate  # noqa: E402
from app.services.connector_service import (  # noqa: E402
    create_connector,
    import_spec,
    update_connector,
)
from app.services.data_interface_service import create_interface, create_system  # noqa: E402
from app.services.skill_store_service import create_folder, upsert_file  # noqa: E402

logger = structlog.get_logger()

ORG_SLUG = os.getenv("MOCK_SEED_ORG_SLUG", "minrui")
ORG_NAME_FALLBACK = "敏睿制造"  # slug 找不到时按名称回退（兼容历史数据）
DEFAULT_BASE_URL = os.getenv("MOCK_BASE_URL", "http://localhost:8010")


# ── 辅助 ───────────────────────────────────────────────────

async def _get_org(db: AsyncSession, slug: str) -> Organization | None:
    """按 slug 查组织；找不到则按名称回退（兼容历史 slug 不一致的环境）。"""
    result = await db.execute(
        select(Organization).where(Organization.slug == slug, Organization.deleted_at.is_(None))
    )
    org = result.scalar_one_or_none()
    if org is not None:
        return org
    result = await db.execute(
        select(Organization).where(Organization.name == ORG_NAME_FALLBACK, Organization.deleted_at.is_(None))
    )
    return result.scalar_one_or_none()


def _fetch_spec(sysdef, base_url: str) -> dict:
    """优先从运行中的网关拉 spec；不可达回退本地快照。"""
    url = f"{base_url.rstrip('/')}{sysdef.prefix}/openapi.json"
    try:
        resp = httpx.get(url, timeout=5.0)
        resp.raise_for_status()
        logger.info("mock_spec_fetched_live", system=sysdef.key, url=url)
        return resp.json()
    except Exception as exc:  # noqa: BLE001
        logger.warning("mock_spec_live_unreachable", system=sysdef.key, url=url, error=str(exc))
        snap = _MOCK_ROOT / "openapi" / f"{sysdef.key}.json"
        if snap.exists():
            logger.info("mock_spec_fallback_snapshot", system=sysdef.key, path=str(snap))
            return json.loads(snap.read_text(encoding="utf-8"))
        raise RuntimeError(
            f"无法获取 {sysdef.key} 的 OpenAPI spec：网关 {url} 不可达，且无快照 {snap}。"
            " 请先 `make mock-up`。"
        )


def _build_skill_manifest(sysdef, get_endpoints: list) -> str:
    """生成 skill.md 内容，绑定只读 GET 端点（排除健康检查）。

    每个绑定端点在 agent 运行时会作为独立 function-tool 暴露给 LLM（见
    ``_build_tools``），故 manifest 的 ``parameters`` 仅作兜底；端点自身的
    ``params_schema`` 优先。健康检查端点（``/health``）非数据查询，绑上去会
    让 LLM 误调并只拿到 ``{"status":"ok"}``，故排除。
    """
    data_endpoints = [
        ep for ep in get_endpoints
        if (ep.path or "") != "/health" and not (ep.name or "").startswith("health_")
    ]
    bound = [str(ep.id) for ep in data_endpoints]
    obj = {
        "name": f"query_{sysdef.key}",
        "description": f"查询 {sysdef.name} 的只读数据接口",
        "parameters": {"type": "object", "properties": {}},
        "bound_endpoint_ids": bound,
    }
    body = json.dumps(obj, ensure_ascii=False, indent=2)
    return f"# {sysdef.name} 查询技能\n\n```skill\n{body}\n```\n"


# ── 单系统注册 ─────────────────────────────────────────────

async def _seed_one(db: AsyncSession, org_id, sysdef, base_url: str) -> dict:
    stats = {"connector": 0, "endpoint": 0, "data_system": 0, "data_interface": 0, "skill": 0}
    slug = f"mock-{sysdef.key}"
    base = f"{base_url.rstrip('/')}{sysdef.prefix}"
    spec = _fetch_spec(sysdef, base_url)
    auth_cfg = {"header_key": "X-API-Key", "api_key": sysdef.api_key}

    # 1) 连接器 upsert
    result = await db.execute(
        select(ToolConnector).where(
            ToolConnector.organization_id == org_id,
            ToolConnector.slug == slug,
            ToolConnector.deleted_at.is_(None),
        )
    )
    conn = result.scalar_one_or_none()
    if conn is None:
        conn = await create_connector(db, org_id, ToolConnectorCreate(
            name=sysdef.name, slug=slug, description=f"{sysdef.name} mock（演示）",
            type=sysdef.key, base_url=base, auth_type="apikey",
            auth_config=auth_cfg, spec=spec, is_active=True,
        ))
        stats["connector"] += 1
        logger.info("mock_connector_created", system=sysdef.key, slug=slug)
    else:
        await update_connector(db, conn, ToolConnectorUpdate(
            base_url=base, auth_type="apikey", auth_config=auth_cfg, spec=spec, is_active=True,
        ))
        logger.info("mock_connector_updated", system=sysdef.key, slug=slug)

    # 2) 导入端点
    endpoints = await import_spec(db, conn)
    stats["endpoint"] = len(endpoints)

    # 3) 数据接口页镜像
    result = await db.execute(
        select(DataSystem).where(
            DataSystem.organization_id == org_id,
            DataSystem.scope_type == "organization",
            DataSystem.scope_id.is_(None),
            DataSystem.name == sysdef.name,
            DataSystem.deleted_at.is_(None),
        )
    )
    system = result.scalar_one_or_none()
    if system is None:
        system = await create_system(db, org_id, DataSystemCreate(
            name=sysdef.name, description=f"{sysdef.name} mock 数据接口（演示）",
            scope_type="organization", scope_id=None, is_active=True,
        ))
        stats["data_system"] += 1
    for ep in endpoints:
        existing = await db.execute(
            select(DataInterface).where(
                DataInterface.data_system_id == system.id,
                DataInterface.name == ep.name,
                DataInterface.deleted_at.is_(None),
            )
        )
        if existing.scalar_one_or_none() is None:
            await create_interface(db, system, DataInterfaceCreate(
                name=ep.name, method=ep.method, path=ep.path, description=ep.description or "",
                params_schema=ep.params_schema, response_schema=ep.response_schema, is_active=True,
            ))
            stats["data_interface"] += 1

    # 4) agent 技能绑定（仅 GET）
    result = await db.execute(
        select(SkillFolder).where(
            SkillFolder.organization_id == org_id,
            SkillFolder.scope_type == "organization",
            SkillFolder.scope_id.is_(None),
            SkillFolder.slug == f"mock-{sysdef.key}-query",
            SkillFolder.deleted_at.is_(None),
        )
    )
    folder = result.scalar_one_or_none()
    if folder is None:
        folder = await create_folder(db, org_id, SkillFolderCreate(
            name=f"{sysdef.name} 查询技能", slug=f"mock-{sysdef.key}-query",
            scope_type="organization", scope_id=None,
        ))
        stats["skill"] += 1
    get_endpoints = [ep for ep in endpoints if (ep.method or "").upper() == "GET"]
    await upsert_file(db, folder, SkillFileCreate(
        path="skill.md", content=_build_skill_manifest(sysdef, get_endpoints),
    ))
    logger.info("mock_skill_bound", system=sysdef.key, bound=len(get_endpoints))

    await db.flush()
    return stats


# ── 主流程 ─────────────────────────────────────────────────

async def seed() -> dict:
    base_url = DEFAULT_BASE_URL
    overall: dict = {"systems": []}
    async with async_session_factory() as db:
        org = await _get_org(db, ORG_SLUG)
        if org is None:
            raise RuntimeError(
                f"组织 slug='{ORG_SLUG}'（或名称='{ORG_NAME_FALLBACK}'）不存在，"
                "请先运行 seed_minrui_manufacturing.py，或用 MOCK_SEED_ORG_SLUG 指定目标组织 slug。"
            )
        logger.info("seed_mock_org", slug=org.slug, org_id=str(org.id))

        for sysdef in MOCK_SYSTEMS:
            stats = await _seed_one(db, org.id, sysdef, base_url)
            overall["systems"].append({"key": sysdef.key, "name": sysdef.name, **stats})

        await db.commit()
    return overall


def _print_report(result: dict) -> None:
    print("\n" + "=" * 64)
    print("mock 连接器 / 数据接口 / 技能 导入完成（仅统计新增；已存在则更新）")
    print("-" * 64)
    print(f"{'系统':<22}{'连接器':>6}{'端点':>6}{'数据系统':>10}{'接口':>6}{'技能':>6}")
    for s in result["systems"]:
        print(f"{s['name']:<20}{s['connector']:>8}{s['endpoint']:>6}"
              f"{s['data_system']:>10}{s['data_interface']:>8}{s['skill']:>6}")
    print("-" * 64)
    print("提示：在管理端「敏睿制造」组织下查看 连接器 / 数据接口 / 技能 页；")
    print("      终端任务勾选对应技能后，agent 可自然语言调用 mock。")
    print("=" * 64)


if __name__ == "__main__":
    res = asyncio.run(seed())
    _print_report(res)
