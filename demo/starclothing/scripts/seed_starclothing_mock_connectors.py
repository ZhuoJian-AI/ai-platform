"""为「星途服装」组织注册 mock 连接器 + 端点 + 数据接口 + 技能（PLM/SCM/ERP/MES/CRM）。

与 ``seed_mock_connectors.py``（敏睿制造）同构，差异：
  - 目标组织 slug=``starclothing``（早期 demo 用 ``xingtu``，后全套重命名为
    ``starclothing``——见 NEW_ORG_DEMO_CHECKLIST.md §0.3 命名规约）；
  - 每个系统用其 ``starclothing`` 专属 API key（``keys_to_tenants`` 反查），让 mock 中间件
    把命中 key 写入 ``request.state.tenant = "starclothing"``，调用对应数据集；
  - 跳过 HRM（HRM 未多租户化，demo 不依赖）。

幂等：按 slug / name 去重，已存在则更新 spec / 端点 / 技能绑定。可安全重复执行。

前置：先 ``make mock-up``（mock 网关 :8010）与 ``python scripts/seed_starclothing_apparel.py``。

用法:
    # 容器内（docker cp 后）：
    docker cp demo/starclothing/scripts/seed_starclothing_mock_connectors.py ai_infra_backend:/app/scripts/
    docker exec ai_infra_backend python scripts/seed_starclothing_mock_connectors.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

# 兼容两种位置：容器内 /app/scripts/ → backend=/app；本地 demo/starclothing/scripts/ → backend=repo/llm_router/backend
_HERE = Path(__file__).resolve()
_BACKEND_DIR = _HERE.parent.parent
if not (_BACKEND_DIR / "app" / "database.py").exists():
    _BACKEND_DIR = _HERE.parents[3] / "llm_router" / "backend"
_REPO_ROOT = _BACKEND_DIR.parent.parent
# 容器内 backend 在 /app，mock 安装为 editable package；本地开发时 mock 在 _REPO_ROOT/mock
_MOCK_ROOT = _REPO_ROOT / "mock"
if not _MOCK_ROOT.exists():
    _MOCK_ROOT = _BACKEND_DIR / "mock"  # 容器：/app/mock
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
from app.schemas.data_interface import DataInterfaceCreate, DataSystemCreate, DataSystemUpdate  # noqa: E402
from app.schemas.skill import SkillFileCreate, SkillFolderCreate  # noqa: E402
from app.services.connector_service import (  # noqa: E402
    create_connector, import_spec, update_connector,
)
from app.services.data_interface_service import create_interface, create_system, update_system  # noqa: E402
from app.services.skill_store_service import create_folder, upsert_file  # noqa: E402

logger = structlog.get_logger()

ORG_SLUG = os.getenv("MOCK_SEED_ORG_SLUG", "starclothing")
ORG_NAME_FALLBACK = "星途服装"
# 历史名称：用于兼容已落库的旧记录（按旧名查到后改名）
LEGACY_ORG_NAME_FALLBACK = "星图服装"
DEFAULT_BASE_URL = os.getenv("MOCK_BASE_URL", "http://localhost:8010")

# 跳过未多租户化的系统（demo 不依赖 HRM）
SKIP_SYSTEMS = {"hrm"}


async def _get_org(db: AsyncSession, slug: str) -> Organization | None:
    result = await db.execute(
        select(Organization).where(Organization.slug == slug, Organization.deleted_at.is_(None))
    )
    org = result.scalar_one_or_none()
    if org is not None:
        return org
    # 兼容历史名「星图服装」与目标名「星途服装」
    result = await db.execute(
        select(Organization).where(
            Organization.name.in_([ORG_NAME_FALLBACK, LEGACY_ORG_NAME_FALLBACK]),
            Organization.deleted_at.is_(None),
        )
    )
    return result.scalar_one_or_none()


def _starclothing_api_key(sysdef) -> str:
    """从 SystemDef.keys_to_tenants 取 starclothing tenant 对应的 API key。"""
    mapping = sysdef.keys_to_tenants
    for key, tenant in mapping.items():
        if tenant == "starclothing":
            return key
    raise RuntimeError(f"{sysdef.key} 不支持 starclothing tenant（keys={mapping}）")


def _fetch_spec(sysdef, base_url: str) -> dict:
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
    """生成 skill.md，绑定该系统所有只读 GET 端点（排除 /health）。"""
    data_endpoints = [
        ep for ep in get_endpoints
        if (ep.path or "") != "/health" and not (ep.name or "").startswith("health_")
    ]
    bound = [str(ep.id) for ep in data_endpoints]
    obj = {
        "name": f"starclothing_query_{sysdef.key}",
        "description": f"星途服装：查询 {sysdef.name} 的只读数据接口（tenant=starclothing）",
        "parameters": {"type": "object", "properties": {}},
        "bound_endpoint_ids": bound,
    }
    body = json.dumps(obj, ensure_ascii=False, indent=2)
    return f"# 星途服装 · {sysdef.name} 查询技能\n\n```skill\n{body}\n```\n"


async def _seed_one(db: AsyncSession, org_id, sysdef, base_url: str) -> dict:
    stats = {"connector": 0, "endpoint": 0, "data_system": 0, "data_interface": 0, "skill": 0}
    slug = f"starclothing-{sysdef.key}"
    base = f"{base_url.rstrip('/')}{sysdef.prefix}"
    spec = _fetch_spec(sysdef, base_url)
    starclothing_key = _starclothing_api_key(sysdef)
    auth_cfg = {"header_key": "X-API-Key", "api_key": starclothing_key}

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
            name=f"{sysdef.name}（星途）", slug=slug,
            description=f"星途服装 {sysdef.name} mock（tenant=starclothing）",
            type=sysdef.key, base_url=base, auth_type="apikey",
            auth_config=auth_cfg, spec=spec, is_active=True,
        ))
        stats["connector"] += 1
        logger.info("starclothing_connector_created", system=sysdef.key, slug=slug)
    else:
        await update_connector(db, conn, ToolConnectorUpdate(
            base_url=base, auth_type="apikey", auth_config=auth_cfg, spec=spec, is_active=True,
            name=f"{sysdef.name}（星途）", description=f"星途服装 {sysdef.name} mock（tenant=starclothing）",
        ))
        logger.info("starclothing_connector_updated", system=sysdef.key, slug=slug)

    # 2) 导入端点
    endpoints = await import_spec(db, conn)
    stats["endpoint"] = len(endpoints)

    # 3) 数据接口镜像
    # 兼容旧名「（星图）」：命中后改名为「（星途）」
    new_name = f"{sysdef.name}（星途）"
    new_desc = f"星途服装 {sysdef.name} 数据接口（tenant=starclothing）"
    result = await db.execute(
        select(DataSystem).where(
            DataSystem.organization_id == org_id,
            DataSystem.scope_type == "organization",
            DataSystem.scope_id.is_(None),
            DataSystem.name.in_([new_name, f"{sysdef.name}（星图）"]),
            DataSystem.deleted_at.is_(None),
        )
    )
    system = result.scalar_one_or_none()
    if system is None:
        system = await create_system(db, org_id, DataSystemCreate(
            name=new_name,
            description=new_desc,
            scope_type="organization", scope_id=None, is_active=True,
        ))
        stats["data_system"] += 1
    elif system.name != new_name or (system.description or "") != new_desc:
        await update_system(db, system, DataSystemUpdate(name=new_name, description=new_desc))
        logger.info("starclothing_data_system_renamed", system=sysdef.key,
                    old=system.name, new=new_name)
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
                name=ep.name, method=ep.method, path=ep.path,
                description=ep.description or "",
                params_schema=ep.params_schema, response_schema=ep.response_schema, is_active=True,
            ))
            stats["data_interface"] += 1

    # 4) 技能文件夹 + skill.md（绑定只读 GET）
    skill_slug = f"starclothing-{sysdef.key}-query"
    new_skill_name = f"星途 · {sysdef.name} 查询技能"
    result = await db.execute(
        select(SkillFolder).where(
            SkillFolder.organization_id == org_id,
            SkillFolder.scope_type == "organization",
            SkillFolder.scope_id.is_(None),
            SkillFolder.slug == skill_slug,
            SkillFolder.deleted_at.is_(None),
        )
    )
    folder = result.scalar_one_or_none()
    if folder is None:
        folder = await create_folder(db, org_id, SkillFolderCreate(
            name=new_skill_name, slug=skill_slug,
            scope_type="organization", scope_id=None,
        ))
        stats["skill"] += 1
    elif folder.name != new_skill_name:
        from app.schemas.skill import SkillFolderUpdate
        from app.services.skill_store_service import update_folder as _update_folder
        folder = await _update_folder(db, folder, SkillFolderUpdate(name=new_skill_name))
        logger.info("starclothing_skill_folder_renamed", system=sysdef.key,
                    slug=skill_slug, new=new_skill_name)
    get_endpoints = [ep for ep in endpoints if (ep.method or "").upper() == "GET"]
    await upsert_file(db, folder, SkillFileCreate(
        path="skill.md", content=_build_skill_manifest(sysdef, get_endpoints),
    ))
    logger.info("starclothing_skill_bound", system=sysdef.key, bound=len(get_endpoints))

    await db.flush()
    return stats


async def seed() -> dict:
    base_url = DEFAULT_BASE_URL
    overall: dict = {"systems": []}
    async with async_session_factory() as db:
        org = await _get_org(db, ORG_SLUG)
        if org is None:
            raise RuntimeError(
                f"组织 slug='{ORG_SLUG}'（或名称='{ORG_NAME_FALLBACK}'/'{LEGACY_ORG_NAME_FALLBACK}'）不存在，"
                "请先运行 python scripts/seed_starclothing_apparel.py。"
            )
        logger.info("starclothing_mock_org", slug=org.slug, org_id=str(org.id))

        for sysdef in MOCK_SYSTEMS:
            if sysdef.key in SKIP_SYSTEMS:
                logger.info("starclothing_skip_system", system=sysdef.key, reason="not multi-tenant")
                continue
            if "starclothing" not in sysdef.tenants:
                logger.info("starclothing_skip_system", system=sysdef.key, reason="no starclothing tenant")
                continue
            stats = await _seed_one(db, org.id, sysdef, base_url)
            overall["systems"].append({"key": sysdef.key, "name": sysdef.name, **stats})

        await db.commit()
    return overall


def _print_report(result: dict) -> None:
    print("\n" + "=" * 64)
    print("星途服装 mock 连接器 / 数据接口 / 技能 导入完成（仅统计新增；已存在则更新）")
    print("-" * 64)
    print(f"{'系统':<32}{'连接器':>6}{'端点':>6}{'数据系统':>10}{'接口':>6}{'技能':>6}")
    for s in result["systems"]:
        print(f"{s['name']:<30}{s['connector']:>8}{s['endpoint']:>6}"
              f"{s['data_system']:>10}{s['data_interface']:>8}{s['skill']:>6}")
    print("-" * 64)
    print("提示：在管理端「星途服装」组织下查看 连接器 / 数据接口 / 技能 页；")
    print("      终端任务勾选对应技能后，agent 可自然语言调用 mock（tenant=starclothing）。")
    print("=" * 64)


if __name__ == "__main__":
    res = asyncio.run(seed())
    _print_report(res)
