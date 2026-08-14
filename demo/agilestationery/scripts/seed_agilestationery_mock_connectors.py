"""为「敏睿文具」组织注册 mock 连接器 + 端点 + 数据接口 + 9 个部门级技能。

与 ``seed_agilesteel_mock_connectors.py`` 同构，差异：
  - 目标组织 slug=``agilestationery``，使用各系统的 ``agilestationery`` 专属 API key；
  - 7 个 mock 系统（erp/crm/scm/hrm/pim/cst/chn）注册了 agilestationery tenant，
    循环 ``MOCK_SYSTEMS`` 时自动跳过未授权 tenant 的系统（mes/plm/eqm/ems/ehs）；
  - 9 个部门级技能（按场景归口，绑定相关系统子集 GET 端点）；无组织级技能。
  - 数据接口仍保持 org 级镜像（与 agilesteel 一致），scope 隔离靠 SkillFolder 实现：
    员工终端任务勾选其部门技能时，agent ``_build_tools`` 只暴露 bound_endpoint_ids
    对应的工具，自然实现部门级数据可见性边界。

幂等：按 slug / name 去重，已存在则更新 spec / 端点 / 技能绑定。可安全重复执行。

前置：先 ``make mock-up``（mock 网关 :8010）与 ``python scripts/seed_agilestationery_org.py``。

用法:
    docker cp demo/agilestationery/scripts/seed_agilestationery_mock_connectors.py ai_infra_backend:/app/scripts/
    docker exec ai_infra_backend python scripts/seed_agilestationery_mock_connectors.py
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

ORG_SLUG = os.getenv("MOCK_SEED_ORG_SLUG", "agilestationery")
DEFAULT_BASE_URL = os.getenv("MOCK_BASE_URL", "http://localhost:8010")


# ───────────────────────── 9 个技能定义（9 dept，无 org 级） ─────────────────────────

SKILL_DEFS = [
    # 1. SAL 销售部（crm 客户/订单/异议/应收 + erp 物料/库存）
    {
        "slug": "agilestationery-sales-crm-erp-query",
        "name": "敏睿文具·销售部 查询技能",
        "scope_type": "department",
        "dept_slug": "sales",
        "bindings": {
            "crm": ["listCustomers", "getCustomer", "listOpportunities", "listQuotations",
                    "listSalesOrders", "getSalesOrder", "listComplaints", "listReceivables",
                    "listFollowUps"],
            "erp": ["listMaterials", "listInventory"],
        },
        "description": "渠道运营/KA经理：查经销商客户(DLR-)/KA(KA-)/商机/报价/销售订单(SO-)/客诉工单(CASE-)/应收(REC-)——支撑渠道健康度监测与销售补货预测闭环。",
    },
    # 2. ECOM 电商部（chn 渠道秩序 + crm 客户）
    {
        "slug": "agilestationery-ecom-chn-crm-query",
        "name": "敏睿文具·电商部 查询技能",
        "scope_type": "department",
        "dept_slug": "ecommerce",
        "bindings": {
            "chn": ["listMerchants", "getMerchant", "listPriceViolations", "listUnauthorizedStores",
                    "listEvidence", "listChannelPerformance", "scoreViolationRisk"],
            "crm": ["listCustomers", "getCustomer"],
        },
        "description": "电商运营：查渠道商家(MR-)/低价窜货违规/非授权店铺/取证(EV-)/渠道效能(ROI)/违规风险打分——支撑线上渠道秩序管控与渠道效能分析。",
    },
    # 3. MKT 市场部（chn 竞品/渠道效能 + crm 商机/客户）
    {
        "slug": "agilestationery-mkt-chn-query",
        "name": "敏睿文具·市场部 查询技能",
        "scope_type": "department",
        "dept_slug": "marketing",
        "bindings": {
            "chn": ["listCompetitors", "getCompetitor", "listChannelPerformance"],
            "crm": ["listOpportunities", "listCustomers"],
        },
        "description": "市场分析：查竞品动态(CMP-)/渠道效能/商机/客户——支撑竞品监测与B端文本营销物料生成。",
    },
    # 4. SCM 供应链部（cst 报关/发票/合规 + scm 供应商/比价/补货 + erp 采购/库存）
    {
        "slug": "agilestationery-supply-cst-scm-erp-query",
        "name": "敏睿文具·供应链部 查询技能",
        "scope_type": "department",
        "dept_slug": "supply",
        "bindings": {
            "cst": ["listDeclarations", "getDeclaration", "listHsCodes", "recommendHsCode",
                    "listInvoices", "verifyInvoice", "getExchangeRate", "listComplianceChecks",
                    "checkCompliance", "scoreDeclarationRisk"],
            "scm": ["listSuppliers", "getSupplier", "listQuotations", "compareQuotations",
                    "getQuotation", "listReplenishmentSuggestions", "suggestReplenishment",
                    "listFabricArrivalPlans", "listLeadtimeSnapshots", "getLeadtimeDiff",
                    "listMaterialValidations"],
            "erp": ["listPurchaseOrders", "listInventory", "listMaterials"],
        },
        "description": "报关/物流员：查报关单(CD-)/HS归类/发票(INV-)验真/汇率(FX-)/合规校验 + 供应商(SUP-)/多家比价/补货建议/在途到货/交期异动 + 采购单(PO-)/库存——支撑报关单证智能处理与库存补货规划。",
    },
    # 5. PRD 产品部（pim 产品/品类/防伪/反馈）
    {
        "slug": "agilestationery-product-pim-query",
        "name": "敏睿文具·产品部 查询技能",
        "scope_type": "department",
        "dept_slug": "product",
        "bindings": {
            "pim": ["listProducts", "getProduct", "listCategories", "listAntiCounterfeitSamples",
                    "getAuthenticityProfile", "identifyAuthenticity", "listFeedback",
                    "listFeedbackStats", "scoreCounterfeitRisk"],
        },
        "description": "产品/防伪专员：查文具产品(SKU-ZB-)/品类(CAT-)/防伪档案/假货样本(CTF-)/真伪鉴定/全渠道反馈(FB-)/假货风险打分——支撑渠道假货识别与全渠道反馈分析。",
    },
    # 6. SRV 客服部（crm 工单/客诉/客户/订单 + erp 库存/采购）
    {
        "slug": "agilestationery-service-crm-erp-query",
        "name": "敏睿文具·客服部 查询技能",
        "scope_type": "department",
        "dept_slug": "service",
        "bindings": {
            "crm": ["listComplaints", "getComplaint", "listCustomers", "getCustomer",
                    "listSalesOrders", "getSalesOrder", "listFollowUps"],
            "erp": ["listInventory", "listMaterials", "listPurchaseOrders"],
        },
        "description": "客服/售后：查售后工单(CASE-)/客诉/客户/销售订单(SO-)/回访 + 库存/采购——支撑售后工单智能处理与B端客服辅助。",
    },
    # 7. FIN 财务部（跨 ERP/CST/CRM 对账 + 发票识别验真 + 应收催收）
    {
        "slug": "agilestationery-finance-erp-cst-crm-query",
        "name": "敏睿文具·财务部 查询技能",
        "scope_type": "department",
        "dept_slug": "finance",
        "bindings": {
            "erp": ["listVouchers", "listPayables", "listPurchaseOrders", "listCostCenters",
                    "listMaterials", "listInventory"],
            "cst": ["listInvoices", "verifyInvoice", "getExchangeRate", "listComplianceChecks",
                    "checkCompliance"],
            "crm": ["listReceivables", "listCustomers", "listSalesOrders"],
        },
        "description": "财务会计：跨 ERP/CST/CRM 对账（凭证 BV-↔发票 INV-↔采购 PO-↔应收 REC-）+ 发票识别验真 + 应收催收——支撑发票识别审核与费用对账闭环。",
    },
    # 8. HR 人力资源部（hrm 全查询，不含 shortlistResumes POST 端点）
    {
        "slug": "agilestationery-hr-hrm-query",
        "name": "敏睿文具·人力资源部 查询技能",
        "scope_type": "department",
        "dept_slug": "hr",
        "bindings": {
            "hrm": ["listEmployees", "getEmployee", "listDepartments", "getDepartment",
                    "listPositions", "listAttendance", "listLeaves", "listPayrolls",
                    "listPerformances", "listRecruitments", "listResumesByPosition",
                    "listMeetings"],
        },
        "description": "招聘/培训/薪酬专员：查员工(EMP-)/部门(PD-)/岗位(P-)/简历库(RSM-)/招聘需求(RC-)/考勤/薪酬/绩效/会议——支撑招聘人岗匹配与人事事务闭环。",
    },
    # 9. LGL 法务部（chn 违规商家/取证/竞品 + crm 客户）
    {
        "slug": "agilestationery-legal-chn-crm-query",
        "name": "敏睿文具·法务部 查询技能",
        "scope_type": "department",
        "dept_slug": "legal",
        "bindings": {
            "chn": ["listMerchants", "getMerchant", "listPriceViolations", "listUnauthorizedStores",
                    "listEvidence", "scoreViolationRisk", "listCompetitors", "getCompetitor"],
            "crm": ["listCustomers", "getCustomer"],
        },
        "description": "法务/合规：查渠道违规商家(MR-)/取证(EV-)/竞品 + 经销商客户——支撑合同智能审核与渠道维权合规。",
    },
]


# ───────────────────────── 辅助 ─────────────────────────

async def _get_org(db: AsyncSession, slug: str) -> Organization | None:
    result = await db.execute(
        select(Organization).where(Organization.slug == slug, Organization.deleted_at.is_(None))
    )
    return result.scalar_one_or_none()


def _agilestationery_api_key(sysdef) -> str:
    """从 SystemDef.keys_to_tenants 取 agilestationery tenant 对应的 API key。"""
    mapping = sysdef.keys_to_tenants
    for key, tenant in mapping.items():
        if tenant == "agilestationery":
            return key
    raise RuntimeError(f"{sysdef.key} 不支持 agilestationery tenant（keys={mapping}）")


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
    slug = f"agilestationery-{sysdef.key}"
    base = f"{base_url.rstrip('/')}{sysdef.prefix}"
    spec = _fetch_spec(sysdef, base_url)
    key = _agilestationery_api_key(sysdef)
    auth_cfg = {"header_key": "X-API-Key", "api_key": key}

    result = await db.execute(
        select(ToolConnector).where(
            ToolConnector.organization_id == org_id, ToolConnector.slug == slug,
            ToolConnector.deleted_at.is_(None),
        )
    )
    conn = result.scalar_one_or_none()
    conn_name = f"{sysdef.name}（敏睿文具）"
    conn_desc = f"敏睿文具 {sysdef.name} mock（tenant=agilestationery）"
    if conn is None:
        conn = await create_connector(db, org_id, ToolConnectorCreate(
            name=conn_name, slug=slug, description=conn_desc,
            type=sysdef.key, base_url=base, auth_type="apikey",
            auth_config=auth_cfg, spec=spec, is_active=True,
        ))
        stats["connector"] += 1
        logger.info("agilestationery_connector_created", system=sysdef.key, slug=slug)
    else:
        await update_connector(db, conn, ToolConnectorUpdate(
            base_url=base, auth_type="apikey", auth_config=auth_cfg, spec=spec, is_active=True,
            name=conn_name, description=conn_desc,
        ))
        logger.info("agilestationery_connector_updated", system=sysdef.key, slug=slug)

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
            logger.warning("agilestationery_skill_dept_missing", slug=skill_def["slug"],
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
        logger.info("agilestationery_skill_created", slug=skill_def["slug"], bound=len(bound_endpoints))
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
                f"组织 slug='{ORG_SLUG}' 不存在，请先运行 python scripts/seed_agilestationery_org.py。"
            )
        logger.info("agilestationery_mock_org", slug=org.slug, org_id=str(org.id))

        sysdef_by_key: dict = {}
        system_stats: dict = {}
        for sysdef in MOCK_SYSTEMS:
            if "agilestationery" not in sysdef.tenants:
                logger.info("agilestationery_skip_system", system=sysdef.key, reason="no agilestationery tenant")
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
    print("敏睿文具 mock 连接器 / 数据接口 / 9 部门级技能 导入完成")
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
    print("提示：在管理端「敏睿文具」组织下查看 连接器 / 数据接口 / 技能 页；")
    print("      终端任务勾选归口部门技能后，agent 自然语言调用 mock（tenant=agilestationery）。")
    print("=" * 70)


if __name__ == "__main__":
    res = asyncio.run(seed())
    _print_report(res)
