"""为「敏睿钢铁」组织注册 mock 连接器 + 端点 + 数据接口 + 9 个部门级技能。

与 ``seed_agileac_mock_connectors.py`` 同构，差异：
  - 目标组织 slug=``agilesteel``，使用各系统的 ``agilesteel`` 专属 API key；
  - 9 个 mock 系统（6 复用 + EQM/EMS/EHS 新建），循环 ``MOCK_SYSTEMS`` 自动覆盖；
  - 9 个部门级技能（按场景归口，绑定相关系统子集 GET 端点）；无组织级技能。
  - 数据接口仍保持 org 级镜像（与 agileac 一致），scope 隔离靠 SkillFolder 实现：
    员工终端任务勾选其部门技能时，agent ``_build_tools`` 只暴露 bound_endpoint_ids
    对应的工具，自然实现部门级数据可见性边界。

幂等：按 slug / name 去重，已存在则更新 spec / 端点 / 技能绑定。可安全重复执行。

前置：先 ``make mock-up``（mock 网关 :8010）与 ``python scripts/seed_agilesteel_org.py``。

用法:
    docker cp demo/agilesteel/scripts/seed_agilesteel_mock_connectors.py ai_infra_backend:/app/scripts/
    docker exec ai_infra_backend python scripts/seed_agilesteel_mock_connectors.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

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

ORG_SLUG = os.getenv("MOCK_SEED_ORG_SLUG", "agilesteel")
DEFAULT_BASE_URL = os.getenv("MOCK_BASE_URL", "http://localhost:8010")


# ───────────────────────── 9 个技能定义（9 dept，无 org 级） ─────────────────────────

SKILL_DEFS = [
    # 1. MFG-01 生产制造部（mes 炉次/工单/排产 + erp 钢坯库存）
    {
        "slug": "agilesteel-production-mes-erp-query",
        "name": "敏睿钢·生产部 查询技能",
        "scope_type": "department",
        "dept_slug": "production",
        "bindings": {
            "mes": ["listProductionOrders", "getProductionOrder", "listWorkOrders", "getWorkOrder",
                    "listHeats", "getHeat", "listShiftOutputs", "listWip", "listEquipmentStatus",
                    "getOee"],
            "erp": ["listMaterials", "listInventory"],
        },
        "description": "排产计划员：查炉次(HT)/工单(SWO)/生产订单(SPO)/钢坯库存/产线设备 OEE——支撑转炉终点碳温预测与炼钢-连铸-轧钢一体化排产。",
    },
    # 2. EQP-01 设备管理部（eqm 预测性维护 + 备件）
    {
        "slug": "agilesteel-equipment-eqm-query",
        "name": "敏睿钢·设备部 查询技能",
        "scope_type": "department",
        "dept_slug": "equipment",
        "bindings": {
            "eqm": ["listEquipment", "getEquipment", "listSpareParts", "getSparePart",
                    "listFaultHistory", "listMaintenancePlans", "listSensorReadings",
                    "predictEquipmentFailure", "scoreMaintenancePriority"],
        },
        "description": "设备工程师：查关键设备档案/振动温度传感器时序/故障历史(MTBF/MTTR)/预测性维护建议/备件——支撑高炉转炉轧机预测性维护与备件建议闭环。",
    },
    # 3. QAL-01 质量管理部（mes 缺陷/炉次 + plm 钢种主数据/历史案例）
    {
        "slug": "agilesteel-quality-mes-plm-query",
        "name": "敏睿钢·质量部 查询技能",
        "scope_type": "department",
        "dept_slug": "quality",
        "bindings": {
            "mes": ["listDefects", "getDefectRootCause", "listHeats", "getHeat",
                    "listWorkOrders", "getWorkOrder"],
            "plm": ["listSteelGrades", "getSteelGrade", "listDefectHistory"],
        },
        "description": "质量工程师：查表面缺陷(DF)/炉次(HT)/钢种主数据(P-ST-)/PLM 钢种质量历史案例(DF-AS-)——支撑表面缺陷检测与全流程质量追溯闭环。",
    },
    # 4. SCM-01 采购与供应链部（scm 供应商/废钢/报价 + erp 采购/库存/应付）
    {
        "slug": "agilesteel-supply-scm-erp-query",
        "name": "敏睿钢·供应链部 查询技能",
        "scope_type": "department",
        "dept_slug": "supply",
        "bindings": {
            "scm": ["listSuppliers", "getSupplier", "listQuotations", "compareQuotations",
                    "getQuotation", "listScrapGrades", "getScrapPrice"],
            "erp": ["listMaterials", "listPurchaseOrders", "listInventory", "listPayables"],
        },
        "description": "采购/物流员：查大宗原料(铁矿石/焦炭/废钢)供应商/报价多家比价/废钢分级(SCR-)/采购单/应付——支撑价格预测与供应商风控闭环。",
    },
    # 5. SAL-01 销售公司（crm 客户/订单/异议/应收 + erp 钢材库存）
    {
        "slug": "agilesteel-sales-crm-erp-query",
        "name": "敏睿钢·销售部 查询技能",
        "scope_type": "department",
        "dept_slug": "sales",
        "bindings": {
            "crm": ["listCustomers", "getCustomer", "listOpportunities", "listQuotations",
                    "listSalesOrders", "getSalesOrder", "listComplaints", "listReceivables",
                    "listFollowUps"],
            "erp": ["listMaterials", "listInventory"],
        },
        "description": "销售运营/电商：查客户(C-AS-)/商机/销售订单(ASSO)/质量异议(ASCP)/应收(ASIV)/钢材现货——支撑需求预测与订单评审交期答复闭环。",
    },
    # 6. ENE-01 能源环保部（ems 全端点）
    {
        "slug": "agilesteel-energy-ems-query",
        "name": "敏睿钢·能源部 查询技能",
        "scope_type": "department",
        "dept_slug": "energy",
        "bindings": {
            "ems": ["listMeters", "getMeter", "listMediaBalance", "listEmissions",
                    "listEnergyConsumption", "listDispatchPlans", "listAlarms",
                    "predictMediaShortfall", "scoreEmissionRisk"],
        },
        "description": "能源调度员：查煤气/蒸汽/电力/氧气/水介质平衡(EM-)/排放(SO2/NOx/颗粒物/CO2)/工序能耗/调度方案/预警——支撑能源介质平衡调度与排放预警闭环。",
    },
    # 7. SAF-01 安全环保部（ehs 全端点）
    {
        "slug": "agilesteel-safety-ehs-query",
        "name": "敏睿钢·安全部 查询技能",
        "scope_type": "department",
        "dept_slug": "safety",
        "bindings": {
            "ehs": ["listHazards", "getHazard", "listViolations", "getViolation",
                    "listInspections", "listSafetyRisks", "listPpe",
                    "detectViolationType", "scoreHazardPriority"],
        },
        "description": "安全巡检员：查隐患台账(HD-)/违章(VIO-)/巡检(INS-)/风险点分级(红橙黄蓝)/劳保——支撑现场违章识别与隐患闭环管理。",
    },
    # 8. FIN-01 财务部（五方对账：erp 凭证/应付/采购/炉次成本 + mes 炉次 + scm 报价 + plm 成本台账 + crm 应收）
    {
        "slug": "agilesteel-finance-erp-mes-scm-plm-crm-query",
        "name": "敏睿钢·财务部 查询技能",
        "scope_type": "department",
        "dept_slug": "finance",
        "bindings": {
            "erp": ["listVouchers", "listPayables", "listPurchaseOrders", "listProductionCosts",
                    "listCostCenters", "listMaterials"],
            "mes": ["listHeats", "getHeat", "listWorkOrders", "getWorkOrder"],
            "scm": ["listQuotations", "compareQuotations"],
            "plm": ["getCostLedger"],
            "crm": ["listReceivables", "listCustomers", "listSalesOrders"],
        },
        "description": "成本/应收会计：跨 ERP/MES/SCM/PLM/CRM 五方对账（凭证 BV-AS- ↔炉次成本 PC-AS-↔报价 ASQ↔成本台账↔应收 ASINV）+ 分钢种炉次成本核算。",
    },
    # 9. HR-01 人力资源部（hrm 全查询）
    {
        "slug": "agilesteel-hr-hrm-query",
        "name": "敏睿钢·人力资源部 查询技能",
        "scope_type": "department",
        "dept_slug": "hr",
        "bindings": {
            "hrm": ["listEmployees", "getEmployee", "listDepartments", "getDepartment",
                    "listPositions", "listAttendance", "listLeaves", "listPayrolls",
                    "listPerformances", "listRecruitments", "listResumesByPosition",
                    "shortlistResumes", "listMeetings"],
        },
        "description": "招聘/培训/薪酬专员：查员工(ASSA/ASOF)/部门/岗位(P-)/简历库/会议纪要/绩效——支撑招聘人岗匹配与培训薪酬一体化闭环。",
    },
]


# ───────────────────────── 辅助 ─────────────────────────

async def _get_org(db: AsyncSession, slug: str) -> Organization | None:
    result = await db.execute(
        select(Organization).where(Organization.slug == slug, Organization.deleted_at.is_(None))
    )
    return result.scalar_one_or_none()


def _agilesteel_api_key(sysdef) -> str:
    """从 SystemDef.keys_to_tenants 取 agilesteel tenant 对应的 API key。"""
    mapping = sysdef.keys_to_tenants
    for key, tenant in mapping.items():
        if tenant == "agilesteel":
            return key
    raise RuntimeError(f"{sysdef.key} 不支持 agilesteel tenant（keys={mapping}）")


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
    slug = f"agilesteel-{sysdef.key}"
    base = f"{base_url.rstrip('/')}{sysdef.prefix}"
    spec = _fetch_spec(sysdef, base_url)
    key = _agilesteel_api_key(sysdef)
    auth_cfg = {"header_key": "X-API-Key", "api_key": key}

    result = await db.execute(
        select(ToolConnector).where(
            ToolConnector.organization_id == org_id, ToolConnector.slug == slug,
            ToolConnector.deleted_at.is_(None),
        )
    )
    conn = result.scalar_one_or_none()
    conn_name = f"{sysdef.name}（敏睿钢）"
    conn_desc = f"敏睿钢铁 {sysdef.name} mock（tenant=agilesteel）"
    if conn is None:
        conn = await create_connector(db, org_id, ToolConnectorCreate(
            name=conn_name, slug=slug, description=conn_desc,
            type=sysdef.key, base_url=base, auth_type="apikey",
            auth_config=auth_cfg, spec=spec, is_active=True,
        ))
        stats["connector"] += 1
        logger.info("agilesteel_connector_created", system=sysdef.key, slug=slug)
    else:
        await update_connector(db, conn, ToolConnectorUpdate(
            base_url=base, auth_type="apikey", auth_config=auth_cfg, spec=spec, is_active=True,
            name=conn_name, description=conn_desc,
        ))
        logger.info("agilesteel_connector_updated", system=sysdef.key, slug=slug)

    endpoints = await import_spec(db, conn)
    stats["endpoint"] = len(endpoints)

    new_name = conn_name
    new_desc = conn_desc.replace("mock", "数据接口")
    result = await db.execute(
        select(DataSystem).where(
            DataSystem.organization_id == org_id, DataSystem.scope_type == "organization",
            DataSystem.scope_id.is_(None), DataSystem.name == new_name,
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
                DataInterface.data_system_id == system.id, DataInterface.name == ep.name,
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
    bound_endpoints = []
    for sys_key, ops in skill_def["bindings"].items():
        if sys_key not in system_stats:
            continue
        endpoints = system_stats[sys_key]["_endpoints"]
        if ops == "*":
            bound_endpoints.extend([ep for ep in endpoints if (ep.method or "").upper() == "GET"])
        else:
            wanted = set(ops)
            for ep in endpoints:
                if (ep.method or "").upper() == "GET" and ep.name in wanted:
                    bound_endpoints.append(ep)

    scope_type = skill_def["scope_type"]
    scope_id = None
    if scope_type == "department":
        dept = dept_by_slug.get(skill_def["dept_slug"])
        if dept is None:
            logger.warning("agilesteel_skill_dept_missing", slug=skill_def["slug"],
                           dept_slug=skill_def["dept_slug"])
            return {"skill": 0, "bound": 0}
        scope_id = str(dept.id)

    result = await db.execute(
        select(SkillFolder).where(
            SkillFolder.organization_id == org_id, SkillFolder.scope_type == scope_type,
            SkillFolder.scope_id.is_(None) if scope_id is None else SkillFolder.scope_id == scope_id,
            SkillFolder.slug == skill_def["slug"], SkillFolder.deleted_at.is_(None),
        )
    )
    folder = result.scalar_one_or_none()
    if folder is None:
        folder = await create_folder(db, org_id, SkillFolderCreate(
            name=skill_def["name"], slug=skill_def["slug"],
            scope_type=scope_type, scope_id=scope_id,
        ))
        logger.info("agilesteel_skill_created", slug=skill_def["slug"], bound=len(bound_endpoints))
    elif folder.name != skill_def["name"]:
        folder = await update_folder(db, folder, SkillFolderUpdate(name=skill_def["name"]))

    sys_name_map = {k: v.name for k, v in sysdef_by_key.items()}
    content = _build_skill_manifest(skill_def, bound_endpoints, sys_name_map)
    await upsert_file(db, folder, SkillFileCreate(path="skill.md", content=content))

    await db.flush()
    return {"skill": 1, "bound": len(bound_endpoints)}


async def seed() -> dict:
    base_url = DEFAULT_BASE_URL
    overall: dict = {"systems": [], "skills": []}
    async with async_session_factory() as db:
        org = await _get_org(db, ORG_SLUG)
        if org is None:
            raise RuntimeError(
                f"组织 slug='{ORG_SLUG}' 不存在，请先运行 python scripts/seed_agilesteel_org.py。"
            )
        logger.info("agilesteel_mock_org", slug=org.slug, org_id=str(org.id))

        sysdef_by_key: dict = {}
        system_stats: dict = {}
        for sysdef in MOCK_SYSTEMS:
            if "agilesteel" not in sysdef.tenants:
                logger.info("agilesteel_skip_system", system=sysdef.key, reason="no agilesteel tenant")
                continue
            stats = await _seed_one_system(db, org.id, sysdef, base_url)
            sysdef_by_key[sysdef.key] = sysdef
            system_stats[sysdef.key] = stats
            overall["systems"].append({
                "key": sysdef.key, "name": sysdef.name,
                "connector": stats["connector"], "endpoint": stats["endpoint"],
                "data_system": stats["data_system"], "data_interface": stats["data_interface"],
            })

        from app.models.department import Department
        dept_by_slug: dict = {}
        result = await db.execute(
            select(Department).where(
                Department.organization_id == org.id, Department.deleted_at.is_(None),
            )
        )
        for dept in result.scalars().all():
            dept_by_slug[dept.slug] = dept

        for skill_def in SKILL_DEFS:
            s = await _seed_one_skill(db, org.id, skill_def, sysdef_by_key,
                                      system_stats, dept_by_slug)
            overall["skills"].append({
                "slug": skill_def["slug"], "name": skill_def["name"],
                "scope_type": skill_def["scope_type"], "dept_slug": skill_def["dept_slug"],
                "bound_endpoints": s["bound"],
            })

        await db.commit()
    return overall


def _print_report(result: dict) -> None:
    print("\n" + "=" * 70)
    print("敏睿钢铁 mock 连接器 / 数据接口 / 9 部门级技能 导入完成")
    print("-" * 70)
    print(f"{'系统':<28}{'连接器':>8}{'端点':>6}{'数据系统':>10}{'接口':>6}")
    for s in result["systems"]:
        print(f"{s['name']:<26}{s['connector']:>10}{s['endpoint']:>6}"
              f"{s['data_system']:>10}{s['data_interface']:>8}")
    print("-" * 70)
    print(f"{'技能':<52}{'scope':<14}{'绑定端点':>10}")
    for s in result["skills"]:
        dept = s["dept_slug"] or "-"
        print(f"{s['slug']:<50}{s['scope_type']:<14}{s['bound_endpoints']:>10}  ({dept})")
    print("-" * 70)
    print("提示：在管理端「敏睿钢铁」组织下查看 连接器 / 数据接口 / 技能 页；")
    print("      终端任务勾选归口部门技能后，agent 自然语言调用 mock（tenant=agilesteel）。")
    print("=" * 70)


if __name__ == "__main__":
    res = asyncio.run(seed())
    _print_report(res)
