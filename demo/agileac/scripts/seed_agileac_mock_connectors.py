"""为「敏睿空调」组织注册 mock 连接器 + 端点 + 数据接口 + 10 个部门级技能。

与 ``seed_starclothing_mock_connectors.py`` 同构，差异：
  - 目标组织 slug=``agileac``，使用各系统的 ``agileac`` 专属 API key；
  - **包含 HRM**（HRM 已多租户化，HR-01 依赖）；
  - 按 README §9.3 创建 10 个部门级技能（按场景归口，绑定相关系统子集端点）；无组织级技能。
  - 数据接口仍保持 org 级镜像（与 starclothing 一致），scope 隔离靠 SkillFolder 实现：
    员工终端任务勾选其部门技能时，agent ``_build_tools`` 只暴露 bound_endpoint_ids
    对应的工具，自然实现部门级数据可见性边界。

幂等：按 slug / name 去重，已存在则更新 spec / 端点 / 技能绑定。可安全重复执行。

前置：先 ``make mock-up``（mock 网关 :8010）与 ``python scripts/seed_agileac_org.py``。

用法:
    docker cp demo/agileac/scripts/seed_agileac_mock_connectors.py ai_infra_backend:/app/scripts/
    docker exec ai_infra_backend python scripts/seed_agileac_mock_connectors.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

# 兼容两种位置：容器内 /app/scripts/ → backend=/app；本地 demo/agileac/scripts/ → backend=repo/llm_router/backend
_HERE = Path(__file__).resolve()
_BACKEND_DIR = _HERE.parent.parent
if not (_BACKEND_DIR / "app" / "database.py").exists():
    _BACKEND_DIR = _HERE.parents[3] / "llm_router" / "backend"
_REPO_ROOT = _BACKEND_DIR.parent.parent
_MOCK_ROOT = _REPO_ROOT / "mock"
if not _MOCK_ROOT.exists():
    _MOCK_ROOT = _BACKEND_DIR / "mock"
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
from app.schemas.skill import SkillFileCreate, SkillFolderCreate, SkillFolderUpdate  # noqa: E402
from app.services.connector_service import (  # noqa: E402
    create_connector, import_spec, update_connector,
)
from app.services.data_interface_service import create_interface, create_system, update_system  # noqa: E402
from app.services.skill_store_service import (  # noqa: E402
    create_folder, update_folder, upsert_file,
)

logger = structlog.get_logger()

ORG_SLUG = os.getenv("MOCK_SEED_ORG_SLUG", "agileac")
DEFAULT_BASE_URL = os.getenv("MOCK_BASE_URL", "http://localhost:8010")


# ───────────────────────── 10 个技能定义（10 dept，无 org 级） ─────────────────────────
#
# 每个 skill 定义：
#   slug: 技能 slug（唯一）
#   name: 技能名（前端展示）
#   scope_type: organization / department
#   dept_slug: 部门 slug（scope_type=department 时使用；organization 时为 None）
#   bindings: dict[system_key -> list[str]]
#       - list 元素为 operationId（端点 name），空 list = 该系统全部 GET 端点
#       - "*"  = 该系统全部 GET 端点（显式标记）

SKILL_DEFS = [
    # 1. RND-01 研发部
    {
        "slug": "agileac-rnd-plm-query",
        "name": "敏睿·研发部 查询技能",
        "scope_type": "department",
        "dept_slug": "rnd",
        "bindings": {
            "plm": ["listStyles", "getStyle", "listBoms", "listDefectHistory",
                    "listCostLedger", "listFeasibilityLogs"],
        },
        "description": "研发翻译员：查询产品款式、BOM、历史故障案例、成本台账、可行性日志——支撑技术资料翻译与跨语种卖点对齐。",
    },
    # 2. PRD-01 产品部
    {
        "slug": "agileac-prd-plm-crm-query",
        "name": "敏睿·产品部 查询技能",
        "scope_type": "department",
        "dept_slug": "product",
        "bindings": {
            "plm": ["listStyles", "getStyle", "listBoms", "listCostLedger"],
            "crm": ["listCustomers", "getCustomer", "listFollowUps", "listOpportunities"],
        },
        "description": "产品专员：查询产品款式、客户反馈与商机——支撑产品规划与卖点提炼。",
    },
    # 3. MFG-01 生产制造部
    {
        "slug": "agileac-mfg-mes-erp-scm-query",
        "name": "敏睿·生产制造部 查询技能",
        "scope_type": "department",
        "dept_slug": "production",
        "bindings": {
            "mes": ["listProductionOrders", "getProductionOrder", "listWorkOrders", "getWorkOrder",
                    "getRouting", "listShiftOutputs", "listWip", "listEquipmentStatus",
                    "getOee"],
            "erp": ["listMaterials", "listWarehouses", "listInventory"],
            "scm": ["listReplenishmentSuggestions", "suggestReplenishment",
                    "listFabricArrivalPlans", "listLeadtimeSnapshots"],
        },
        "description": "排产计划员：查询工单/产线/设备 OEE、物料库存、补单节奏与到货计划——支撑排产决策。",
    },
    # 4. QAL-01 质量部
    {
        "slug": "agileac-qal-mes-plm-query",
        "name": "敏睿·质量部 查询技能",
        "scope_type": "department",
        "dept_slug": "quality",
        "bindings": {
            "mes": ["listDefects", "getDefectRootCause", "listWorkOrders", "getWorkOrder",
                    "listProductionOrders"],
            "plm": ["listDefectHistory", "listStyles", "getStyle"],
        },
        "description": "质量工程师：查询缺陷记录、5W2H 根因、历史相似缺陷、PLM 故障案例——支撑缺陷闭环。",
    },
    # 5. SCM-01 供应链部
    {
        "slug": "agileac-scm-scm-erp-query",
        "name": "敏睿·供应链部 查询技能",
        "scope_type": "department",
        "dept_slug": "supply",
        "bindings": {
            "scm": ["listSuppliers", "getSupplier", "listQuotations", "compareQuotations",
                    "getQuotation", "listCapacityCalendar", "getSupplierCapacity",
                    "listFabricArrivalPlans", "listLeadtimeSnapshots", "getLeadtimeDiff",
                    "estimateLeadtime", "listReplenishmentSuggestions", "suggestReplenishment"],
            "erp": ["listMaterials", "listPurchaseOrders", "listInventory", "listPayables"],
        },
        "description": "采购/物流员：查询供应商/报价/产能/在途/交期异动 + 采购单/应付——支撑采购决策与对账。",
    },
    # 6. SAL-01 销售部
    {
        "slug": "agileac-sal-crm-erp-query",
        "name": "敏睿·销售部 查询技能",
        "scope_type": "department",
        "dept_slug": "sales",
        "bindings": {
            "crm": ["listCustomers", "getCustomer", "listOpportunities", "listQuotations",
                    "listSalesOrders", "getSalesOrder", "listComplaints", "listReceivables",
                    "listFollowUps"],
            "erp": ["listVouchers", "listProductionCosts"],
        },
        "description": "销售运营/电商：查询客户/商机/订单/客诉/应收 + 凭证——支撑订单管理与回款。",
    },
    # 7. SVC-01 售后服务部
    {
        "slug": "agileac-svc-crm-mes-plm-query",
        "name": "敏睿·售后部 查询技能",
        "scope_type": "department",
        "dept_slug": "after-sales",
        "bindings": {
            "crm": ["listCustomers", "getCustomer", "listComplaints"],
            "mes": ["listDefects", "getDefectRootCause", "listWorkOrders", "getWorkOrder",
                    "listProductionOrders", "getProductionOrder", "listEquipmentStatus"],
            "plm": ["listStyles", "getStyle", "listDefectHistory", "listBoms"],
        },
        "description": "售后工程师：查客诉 + MES 缺陷根因 + PLM 历史故障案例 + 产品 BOM——支撑现场故障诊断闭环（不制冷/漏水/异音/通讯故障等 8 大故障类型）。",
    },
    # 8. MKT-01 市场部
    {
        "slug": "agileac-mkt-plm-crm-query",
        "name": "敏睿·市场部 查询技能",
        "scope_type": "department",
        "dept_slug": "marketing",
        "bindings": {
            "plm": ["listStyles", "getStyle", "listBoms"],
            "crm": ["listCustomers", "listFollowUps", "listOpportunities", "listComplaints"],
        },
        "description": "市场专员：查询产品款式、客户跟进、商机、客诉反馈——支撑卖点内容与竞情。",
    },
    # 9. FIN-01 财务部（四方对账 + SSO：ERP 凭证/应付/生产成本 + MES 工单成本 + SCM 报价 + PLM 成本台账 + CRM 应收/客户）
    {
        "slug": "agileac-fin-erp-crm-query",
        "name": "敏睿·财务部 查询技能",
        "scope_type": "department",
        "dept_slug": "finance",
        "bindings": {
            "erp": ["listVouchers", "listPayables", "listPurchaseOrders",
                    "listProductionCosts", "listCostCenters", "listMaterials"],
            "mes": ["listWorkOrders", "getWorkOrder"],
            "scm": ["listQuotations", "compareQuotations"],
            "plm": ["getCostLedger"],
            "crm": ["listReceivables", "listCustomers", "listSalesOrders"],
        },
        "description": "对账/应收会计：跨 ERP/MES/SCM/PLM 四方对账（凭证↔工单成本↔报价↔成本台账，SSO 免登）+ CRM 应收催办——支撑对账与逾期管理。",
    },
    # 10. HR-01 人力资源部
    {
        "slug": "agileac-hr-hrm-query",
        "name": "敏睿·人力资源部 查询技能",
        "scope_type": "department",
        "dept_slug": "hr",
        "bindings": {
            "hrm": ["listEmployees", "getEmployee", "listDepartments", "getDepartment",
                    "listPositions", "listAttendance", "listLeaves", "listPayrolls",
                    "listPerformances", "listRecruitments", "listResumesByPosition",
                    "shortlistResumes", "listMeetings"],
        },
        "description": "招聘/培训/薪酬专员：查询员工/部门/简历库/会议纪要/绩效——支撑招聘评审与薪酬核算。",
    },
]


# ───────────────────────── 辅助 ─────────────────────────

async def _get_org(db: AsyncSession, slug: str) -> Organization | None:
    result = await db.execute(
        select(Organization).where(Organization.slug == slug, Organization.deleted_at.is_(None))
    )
    return result.scalar_one_or_none()


def _agileac_api_key(sysdef) -> str:
    """从 SystemDef.keys_to_tenants 取 agileac tenant 对应的 API key。"""
    mapping = sysdef.keys_to_tenants
    for key, tenant in mapping.items():
        if tenant == "agileac":
            return key
    raise RuntimeError(f"{sysdef.key} 不支持 agileac tenant（keys={mapping}）")


def _fetch_spec(sysdef, base_url: str) -> dict:
    url = f"{base_url.rstrip('/')}{sysdef.prefix}/openapi.json"
    try:
        resp = httpx.get(url, timeout=5.0)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:  # noqa: BLE001
        logger.warning("mock_spec_live_unreachable", system=sysdef.key, url=url, error=str(exc))
        snap = _MOCK_ROOT / "openapi" / f"{sysdef.key}.json"
        if snap.exists():
            return json.loads(snap.read_text(encoding="utf-8"))
        raise RuntimeError(
            f"无法获取 {sysdef.key} 的 OpenAPI spec：网关 {url} 不可达，且无快照 {snap}。"
            " 请先 `make mock-up`。"
        )


async def _seed_one_system(db: AsyncSession, org_id, sysdef, base_url: str) -> dict:
    """对一个 mock 系统注册连接器 + 端点 + 数据系统 + 数据接口镜像。"""
    stats = {"connector": 0, "endpoint": 0, "data_system": 0, "data_interface": 0}
    slug = f"agileac-{sysdef.key}"
    base = f"{base_url.rstrip('/')}{sysdef.prefix}"
    spec = _fetch_spec(sysdef, base_url)
    agileac_key = _agileac_api_key(sysdef)
    auth_cfg = {"header_key": "X-API-Key", "api_key": agileac_key}

    # 1) 连接器 upsert
    result = await db.execute(
        select(ToolConnector).where(
            ToolConnector.organization_id == org_id,
            ToolConnector.slug == slug,
            ToolConnector.deleted_at.is_(None),
        )
    )
    conn = result.scalar_one_or_none()
    conn_name = f"{sysdef.name}（敏睿）"
    conn_desc = f"敏睿空调 {sysdef.name} mock（tenant=agileac）"
    if conn is None:
        conn = await create_connector(db, org_id, ToolConnectorCreate(
            name=conn_name, slug=slug, description=conn_desc,
            type=sysdef.key, base_url=base, auth_type="apikey",
            auth_config=auth_cfg, spec=spec, is_active=True,
        ))
        stats["connector"] += 1
        logger.info("agileac_connector_created", system=sysdef.key, slug=slug)
    else:
        await update_connector(db, conn, ToolConnectorUpdate(
            base_url=base, auth_type="apikey", auth_config=auth_cfg, spec=spec, is_active=True,
            name=conn_name, description=conn_desc,
        ))
        logger.info("agileac_connector_updated", system=sysdef.key, slug=slug)

    # 2) 导入端点
    endpoints = await import_spec(db, conn)
    stats["endpoint"] = len(endpoints)

    # 3) 数据系统镜像（org 级，与 starclothing 一致）
    new_name = conn_name
    new_desc = conn_desc.replace("mock", "数据接口")
    result = await db.execute(
        select(DataSystem).where(
            DataSystem.organization_id == org_id,
            DataSystem.scope_type == "organization",
            DataSystem.scope_id.is_(None),
            DataSystem.name == new_name,
            DataSystem.deleted_at.is_(None),
        )
    )
    system = result.scalar_one_or_none()
    if system is None:
        system = await create_system(db, org_id, DataSystemCreate(
            name=new_name, description=new_desc,
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
                name=ep.name, method=ep.method, path=ep.path,
                description=ep.description or "",
                params_schema=ep.params_schema, response_schema=ep.response_schema, is_active=True,
            ))
            stats["data_interface"] += 1

    await db.flush()
    return {**stats, "_conn_id": conn.id, "_endpoints": endpoints}


def _build_skill_manifest(skill_def: dict, bound_endpoints: list, sys_name_map: dict) -> str:
    """生成 skill.md，绑定指定端点。"""
    bound_ids = [str(ep.id) for ep in bound_endpoints]
    sys_summary = ", ".join(
        f"{sys_name_map.get(sk, sk)}({len(eps) if eps != '*' else 'all'} 个端点)"
        for sk, eps in skill_def["bindings"].items()
    )
    obj = {
        "name": skill_def["slug"],
        "description": skill_def["description"],
        "parameters": {"type": "object", "properties": {}},
        "bound_endpoint_ids": bound_ids,
    }
    body = json.dumps(obj, ensure_ascii=False, indent=2)
    return (
        f"# {skill_def['name']}\n\n"
        f"绑定端点：{sys_summary}\n\n"
        f"{skill_def['description']}\n\n"
        f"```skill\n{body}\n```\n"
    )


async def _seed_one_skill(db: AsyncSession, org_id, skill_def: dict,
                          sysdef_by_key: dict, system_stats: dict,
                          dept_by_slug: dict) -> dict:
    """对一个技能（10 个之一）创建 SkillFolder + skill.md，绑定相关端点。"""
    # 收集要绑定的端点（按系统 + operationId 列表过滤）
    bound_endpoints = []
    for sys_key, ops in skill_def["bindings"].items():
        if sys_key not in system_stats:
            continue
        endpoints = system_stats[sys_key]["_endpoints"]
        if ops == "*":
            # 该系统全部 GET 端点
            bound_endpoints.extend([ep for ep in endpoints if (ep.method or "").upper() == "GET"])
        else:
            wanted = set(ops)
            for ep in endpoints:
                if (ep.method or "").upper() == "GET" and ep.name in wanted:
                    bound_endpoints.append(ep)

    # 计算 scope_id
    scope_type = skill_def["scope_type"]
    scope_id = None
    if scope_type == "department":
        dept = dept_by_slug.get(skill_def["dept_slug"])
        if dept is None:
            logger.warning("agileac_skill_dept_missing", slug=skill_def["slug"],
                           dept_slug=skill_def["dept_slug"])
            return {"skill": 0, "bound": 0}
        scope_id = str(dept.id)

    # upsert SkillFolder
    result = await db.execute(
        select(SkillFolder).where(
            SkillFolder.organization_id == org_id,
            SkillFolder.scope_type == scope_type,
            SkillFolder.scope_id.is_(None) if scope_id is None else SkillFolder.scope_id == scope_id,
            SkillFolder.slug == skill_def["slug"],
            SkillFolder.deleted_at.is_(None),
        )
    )
    folder = result.scalar_one_or_none()
    if folder is None:
        folder = await create_folder(db, org_id, SkillFolderCreate(
            name=skill_def["name"], slug=skill_def["slug"],
            scope_type=scope_type, scope_id=scope_id,
        ))
        logger.info("agileac_skill_created", slug=skill_def["slug"], bound=len(bound_endpoints))
    elif folder.name != skill_def["name"]:
        folder = await update_folder(db, folder, SkillFolderUpdate(name=skill_def["name"]))

    # 写 skill.md
    sys_name_map = {k: v.name for k, v in sysdef_by_key.items()}
    content = _build_skill_manifest(skill_def, bound_endpoints, sys_name_map)
    await upsert_file(db, folder, SkillFileCreate(path="skill.md", content=content))

    await db.flush()
    return {"skill": 1, "bound": len(bound_endpoints)}


# ───────────────────────── 主流程 ─────────────────────────

async def seed() -> dict:
    base_url = DEFAULT_BASE_URL
    overall: dict = {"systems": [], "skills": []}
    async with async_session_factory() as db:
        org = await _get_org(db, ORG_SLUG)
        if org is None:
            raise RuntimeError(
                f"组织 slug='{ORG_SLUG}' 不存在，请先运行 python scripts/seed_agileac_org.py。"
            )
        logger.info("agileac_mock_org", slug=org.slug, org_id=str(org.id))

        # 1) 6 个系统：连接器 + 端点 + 数据接口
        sysdef_by_key: dict = {}
        system_stats: dict = {}
        for sysdef in MOCK_SYSTEMS:
            if "agileac" not in sysdef.tenants:
                logger.info("agileac_skip_system", system=sysdef.key, reason="no agileac tenant")
                continue
            stats = await _seed_one_system(db, org.id, sysdef, base_url)
            sysdef_by_key[sysdef.key] = sysdef
            system_stats[sysdef.key] = stats
            overall["systems"].append({
                "key": sysdef.key, "name": sysdef.name,
                "connector": stats["connector"], "endpoint": stats["endpoint"],
                "data_system": stats["data_system"], "data_interface": stats["data_interface"],
            })

        # 2) 加载部门映射（用于 skill scope_id）
        from app.models.department import Department
        dept_by_slug: dict = {}
        result = await db.execute(
            select(Department).where(
                Department.organization_id == org.id,
                Department.deleted_at.is_(None),
            )
        )
        for dept in result.scalars().all():
            dept_by_slug[dept.slug] = dept

        # 3) 10 个技能（10 dept，无 org 级技能）
        for skill_def in SKILL_DEFS:
            s = await _seed_one_skill(db, org.id, skill_def, sysdef_by_key,
                                       system_stats, dept_by_slug)
            overall["skills"].append({
                "slug": skill_def["slug"], "name": skill_def["name"],
                "scope_type": skill_def["scope_type"],
                "dept_slug": skill_def["dept_slug"],
                "bound_endpoints": s["bound"],
            })

        await db.commit()
    return overall


def _print_report(result: dict) -> None:
    print("\n" + "=" * 70)
    print("敏睿空调 mock 连接器 / 数据接口 / 11 部门级技能 导入完成")
    print("-" * 70)
    print(f"{'系统':<28}{'连接器':>8}{'端点':>6}{'数据系统':>10}{'接口':>6}")
    for s in result["systems"]:
        print(f"{s['name']:<26}{s['connector']:>10}{s['endpoint']:>6}"
              f"{s['data_system']:>10}{s['data_interface']:>8}")
    print("-" * 70)
    print(f"{'技能':<42}{'scope':<14}{'绑定端点':>10}")
    for s in result["skills"]:
        dept = s["dept_slug"] or "-"
        print(f"{s['slug']:<40}{s['scope_type']:<14}{s['bound_endpoints']:>10}  ({dept})")
    print("-" * 70)
    print("提示：在管理端「敏睿空调」组织下查看 连接器 / 数据接口 / 技能 页；")
    print("      终端任务勾选归口部门技能后，agent 自然语言调用 mock（tenant=agileac）。")
    print("=" * 70)


if __name__ == "__main__":
    res = asyncio.run(seed())
    _print_report(res)
