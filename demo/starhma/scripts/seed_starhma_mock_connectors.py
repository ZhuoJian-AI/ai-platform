"""为「星途热熔胶」组织注册 mock 连接器 + 端点 + 数据接口 + 9 个部门级技能。

与 ``seed_starexploration_mock_connectors.py`` 同构，差异：
  - 目标组织 slug=``starhma``，使用各系统的 ``starhma`` 专属 API key；
  - 6 个 mock 系统（frm/pcm/qas 新建 + erp/mes/crm 复用扩展）注册了 starhma tenant，
    循环 ``MOCK_SYSTEMS`` 时自动跳过未授权 tenant 的系统；
  - 9 个部门级技能（按场景归口，绑定相关系统子集 GET 端点）；无组织级技能。
  - 数据接口仍保持 org 级镜像，scope 隔离靠 SkillFolder 实现：员工终端任务勾选其部门技能时，
    agent ``_build_tools`` 只暴露 bound_endpoint_ids 对应的工具，自然实现部门级数据可见性边界。

幂等：按 slug / name 去重，已存在则更新 spec / 端点 / 技能绑定。可安全重复执行。

前置：先启 mock 网关 :8010（含 frm/pcm/qas）与 ``python scripts/seed_starhma_org.py``。
重建 backend 后必先 ``docker cp mock/mock ai_infra_backend:/app/mock`` 注入 mock 包。

用法:
    docker cp demo/starhma/scripts/seed_starhma_mock_connectors.py ai_infra_backend:/app/scripts/
    MOCK_BASE_URL=http://ai_infra_mock:8010 docker exec -e MOCK_BASE_URL=http://ai_infra_mock:8010 \
        ai_infra_backend python scripts/seed_starhma_mock_connectors.py
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

ORG_SLUG = os.getenv("MOCK_SEED_ORG_SLUG", "starhma")
DEFAULT_BASE_URL = os.getenv("MOCK_BASE_URL", "http://localhost:8010")
TENANT = "starhma"


# ───────────────────────── 9 个技能定义（9 dept，无 org 级） ─────────────────────────

SKILL_DEFS = [
    # 1. RDM-01 配方智能推荐与初始配比（研发中心 rd）：frm 配方/推荐/性能/实验/样品/失效 + erp 物料/库存
    {
        "slug": "starhma-rd-frm-erp-query",
        "name": "星途热熔胶·研发中心 查询技能",
        "scope_type": "department",
        "dept_slug": "rd",
        "bindings": {
            "frm": ["listFormulas", "getFormula", "recommendFormula", "predictPerformance",
                    "listExperiments", "listTestSamples", "listFailureRecords"],
            "erp": ["listMaterials", "listInventory"],
        },
        "description": "配方研发工程师：查配方(FORM-STD-001/002/003 标准品、FORM-CUS-001/002/003 定制)、按基材/施胶温度/开放时间/剥离力做配方智能推荐(recommendFormula)、性能预测(PERF-)、历史实验(EXP-RHE-/EXP-TEN-/EXP-ADH-)、测试样品(SMP-)与失效记录(FR-)——支撑医疗用品低温热熔胶配方智能推荐与初始配比(ING-RES-001/ING-TK-002 → ERP M-RES-/M-TK- 采购物料 prefix 转换)闭环。",
    },
    # 2. RDM-02 实验数据分析与报告生成（研发中心 rd）：frm 实验/分析/报告/预测/方案/失效/配方
    {
        "slug": "starhma-rd-lab-frm-query",
        "name": "星途热熔胶·研发中心实验室 查询技能",
        "scope_type": "department",
        "dept_slug": "rd",
        "bindings": {
            "frm": ["listExperiments", "getExperiment", "analyzeExperimentData",
                    "generateExperimentReport", "predictPerformance", "listTestSchemes",
                    "listFailureRecords", "listFormulas", "getFormula"],
        },
        "description": "应用测试实验员：查实验(EXP-RHE- 流变 / EXP-TEN- 拉力 / EXP-ADH- 持粘)、实验数据分析(异常识别)、生成标准化实验报告、性能预测(PERF-)、测试方案(TS-)、失效记录(FR-2025-021)、配方(FORM-CUS-002)——支撑配方 FORM-CUS-002 实验数据分析与报告生成闭环。",
    },
    # 3. SAL-01 智能询盘与初步粘接方案（营销销售中心 sales）：crm 客户/询盘/报价/订单/跟进 + frm 配方/推荐 + erp 物料
    {
        "slug": "starhma-sales-crm-frm-erp-query",
        "name": "星途热熔胶·营销销售中心 查询技能",
        "scope_type": "department",
        "dept_slug": "sales",
        "bindings": {
            "crm": ["listCustomers", "getCustomer", "listOpportunities", "getOpportunity",
                    "listQuotations", "getQuotation", "listSalesOrders", "listFollowUps"],
            "frm": ["recommendFormula", "getFormula", "listFormulas"],
            "erp": ["listMaterials"],
        },
        "description": "销售/技术销售：查客户(CLI-001..005)、询盘(INQ-002 医疗用品客户)、商机、报价(HMAQT-)、销售订单、跟进记录 + 配方智能推荐(FORM-CUS-002)与历史配方查询 + ERP 物料(M-RES-)——支撑智能询盘与初步粘接方案(样品 SMP-2026-002)闭环。",
    },
    # 4. MFG-01 智能排产与订单冲突识别（生产制造部 mfg）：mes 工单/订单/产出/在制品/不良 + pcm 排产/方案/工艺 + erp 库存/物料/生产成本
    {
        "slug": "starhma-mfg-mes-pcm-erp-query",
        "name": "星途热熔胶·生产制造部 查询技能",
        "scope_type": "department",
        "dept_slug": "mfg",
        "bindings": {
            "mes": ["listWorkOrders", "getWorkOrder", "listProductionOrders", "listShiftOutputs",
                    "listWip", "listDefects"],
            "pcm": ["optimizeProductionSchedule", "listScheduleRules", "recommendProcessParams",
                    "listProcessParams"],
            "erp": ["listInventory", "listMaterials", "listProductionCosts"],
        },
        "description": "生产排产员：查 MES 工单(WO202607001..005)、产线(LINE-AUTO-01/02、LINE-03/04)负荷、班次产出、在制品(WIP)、不良(DF) + PCM 排产优化(optimizeProductionSchedule，返排产建议 PSCH- 与冲突订单)、排产规则、工艺参数(PP-STIR-/PP-REACT-/PP-COOL-) + ERP 库存/物料(M-FG-/M-RES-)生产成本(PC-HMA-)——支撑智能排产与订单冲突识别闭环。",
    },
    # 5. EQP-01 设备预测性维护与保养提醒（生产制造部 mfg）：pcm 设备/故障预测/运行数据/工艺 + mes 设备状态
    {
        "slug": "starhma-eqp-pcm-mes-query",
        "name": "星途热熔胶·设备运维组 查询技能",
        "scope_type": "department",
        "dept_slug": "mfg",
        "bindings": {
            "pcm": ["listEquipment", "getEquipment", "predictEquipmentFault",
                    "getEquipmentRunData", "listProcessParams", "recommendProcessParams"],
            "mes": ["listEquipmentStatus", "getEquipment"],
        },
        "description": "设备运维工程师：查设备(EQ-RX- 反应釜 / EQ-MTR-02 电机 / EQ-GRN- 造粒机)、故障预测(predictEquipmentFault，返振动/温升/健康分+风险等级 PM-)+运行数据、工艺参数(PP-REACT-002) + MES 设备运行状态(LINE-AUTO-02)——支撑设备 EQ-MTR-02 预测性维护与保养提醒闭环。",
    },
    # 6. SCM-01 库存智能预警与补货建议（供应链部 scm）：erp 库存/物料/采购/出入库/仓库/供应商 + crm 销售订单
    {
        "slug": "starhma-scm-erp-crm-query",
        "name": "星途热熔胶·供应链部 查询技能",
        "scope_type": "department",
        "dept_slug": "scm",
        "bindings": {
            "erp": ["listInventory", "listMaterials", "listPurchaseOrders", "listStockMovements",
                    "listWarehouses", "listSuppliers"],
            "crm": ["listSalesOrders"],
        },
        "description": "采购仓储经理：查 ERP 原料(M-RES-001/M-TK-002/M-AO-001)与成品(M-FG-002)库存对比安全库存、采购单(POHMA)、出入库记录、仓库(WH-HMA-)、供应商(S-HMA-) + CRM 销售订单预测——支撑库存智能预警与补货建议闭环。",
    },
    # 7. QAS-01 售后粘接故障智能诊断（品质与技术服务部 qas）：qas 客诉/诊断/案例/根因/不良/质检报告 + crm 客户/投诉 + frm 配方
    {
        "slug": "starhma-qas-qas-crm-frm-query",
        "name": "星途热熔胶·品质与技术服务部 查询技能",
        "scope_type": "department",
        "dept_slug": "qas",
        "bindings": {
            "qas": ["listCustomerComplaints", "getCustomerComplaint", "diagnoseAfterSalesFault",
                    "listFailureCases", "analyzeRootCause", "listNgRecords",
                    "listQualityReports", "getQualityReport"],
            "crm": ["listCustomers", "getCustomer", "listComplaints"],
            "frm": ["getFormula", "listFormulas"],
        },
        "description": "品质与售后技术工程师：查客诉(CC-2026-001 开胶/拉丝/堵枪/低温失效)、售后故障智能诊断(diagnoseAfterSalesFault，按现象/基材/工况匹配故障案例 FC-2025-008 与历史客诉)、故障案例、根因分析(RCA-)、不良品(NG-，batch_no→MES BAT-)、质检报告(QR-IN- 来料 / QR-FG- 成品) + CRM 客户(CLI-001)+投诉 + FRM 配方(FORM-CUS-001)——支撑售后粘接故障智能诊断与配方调整建议闭环。",
    },
    # 8. ADM-01 跨系统经营数据汇总（综合管理部 admin）：erp 凭证/应付/采购/库存/生产成本/成本中心/物料 + crm 订单/客户/回款/投诉 + mes 工单/产出/订单
    {
        "slug": "starhma-admin-erp-crm-mes-query",
        "name": "星途热熔胶·综合管理部 查询技能",
        "scope_type": "department",
        "dept_slug": "admin",
        "bindings": {
            "erp": ["listVouchers", "listPayables", "listPurchaseOrders", "listInventory",
                    "listProductionCosts", "listCostCenters", "listMaterials"],
            "crm": ["listSalesOrders", "listCustomers", "listReceivables", "listComplaints"],
            "mes": ["listWorkOrders", "listShiftOutputs", "listProductionOrders"],
        },
        "description": "企管行政专员：跨 ERP/CRM/MES 经营数据汇总——ERP 凭证(BV-HMA-)/应付(HMAAP)/采购(POHMA)/库存/生产成本(PC-HMA-，heat_no=BAT- 批次，work_order_no=CT-HMA- 合同)/成本中心(CC-HMA-)/物料(M-) + CRM 销售订单/客户(CLI-)/回款(HMAAR-)/投诉 + MES 工单(WO)/班次产出/生产订单——支撑跨系统经营数据汇总(营收/产能/订单/客户统计+应收应付对账 INV202607001↔BV-HMA-2026-0701)闭环。",
    },
    # 9. DOC-01 文档智能处理与检索（综合管理部 admin）：erp 采购/凭证/成本中心 + crm 订单/客户
    {
        "slug": "starhma-admin-doc-erp-crm-query",
        "name": "星途热熔胶·文档资质组 查询技能",
        "scope_type": "department",
        "dept_slug": "admin",
        "bindings": {
            "erp": ["listPurchaseOrders", "getPurchaseOrder", "listVouchers", "listCostCenters"],
            "crm": ["listSalesOrders", "getCustomer", "listCustomers"],
        },
        "description": "文档资质专员：查 ERP 采购单(POHMA)/凭证(BV-HMA-)/成本中心(CC-HMA-) + CRM 销售订单/客户(CLI-)——支撑文档智能处理与检索（合同 CT-HMA-001/002 与采购单/凭证的关键条款/摘要，提取付款里程碑与风险点，生成文档摘要）闭环。",
    },
]


# ───────────────────────── 辅助 ─────────────────────────

async def _get_org(db: AsyncSession, slug: str) -> Organization | None:
    result = await db.execute(
        select(Organization).where(Organization.slug == slug, Organization.deleted_at.is_(None))
    )
    return result.scalar_one_or_none()


def _tenant_api_key(sysdef, tenant: str) -> str:
    """从 SystemDef.keys_to_tenants 取指定 tenant 对应的 API key。"""
    mapping = sysdef.keys_to_tenants
    for key, t in mapping.items():
        if t == tenant:
            return key
    raise RuntimeError(f"{sysdef.key} 不支持 {tenant} tenant（keys={mapping}）")


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
            " 请先启 mock 网关（含 frm/pcm/qas）。"
        )


async def _seed_one_system(db: AsyncSession, org_id, sysdef, base_url: str, tenant: str) -> dict:
    """对一个 mock 系统注册连接器 + 端点 + 数据系统 + 数据接口镜像。"""
    stats = {"connector": 0, "endpoint": 0, "data_system": 0, "data_interface": 0}
    slug = f"{tenant}-{sysdef.key}"
    base = f"{base_url.rstrip('/')}{sysdef.prefix}"
    spec = _fetch_spec(sysdef, base_url)
    key = _tenant_api_key(sysdef, tenant)
    auth_cfg = {"header_key": "X-API-Key", "api_key": key}

    result = await db.execute(
        select(ToolConnector).where(
            ToolConnector.organization_id == org_id, ToolConnector.slug == slug,
            ToolConnector.deleted_at.is_(None),
        )
    )
    conn = result.scalar_one_or_none()
    conn_name = f"{sysdef.name}（星途热熔胶）"
    conn_desc = f"星途热熔胶 {sysdef.name} mock（tenant={tenant}）"
    if conn is None:
        conn = await create_connector(db, org_id, ToolConnectorCreate(
            name=conn_name, slug=slug, description=conn_desc,
            type=sysdef.key, base_url=base, auth_type="apikey",
            auth_config=auth_cfg, spec=spec, is_active=True,
        ))
        stats["connector"] += 1
        logger.info("starhma_connector_created", system=sysdef.key, slug=slug)
    else:
        await update_connector(db, conn, ToolConnectorUpdate(
            base_url=base, auth_type="apikey", auth_config=auth_cfg, spec=spec, is_active=True,
            name=conn_name, description=conn_desc,
        ))
        logger.info("starhma_connector_updated", system=sysdef.key, slug=slug)

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
            logger.warning("starhma_skill_dept_missing", slug=skill_def["slug"],
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
        logger.info("starhma_skill_created", slug=skill_def["slug"], bound=len(bound_endpoints))
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
                f"组织 slug='{ORG_SLUG}' 不存在，请先运行 python scripts/seed_starhma_org.py。"
            )
        logger.info("starhma_mock_org", slug=org.slug, org_id=str(org.id))

        sysdef_by_key: dict = {}
        system_stats: dict = {}
        for sysdef in MOCK_SYSTEMS:
            if TENANT not in sysdef.tenants:
                logger.info("starhma_skip_system", system=sysdef.key, reason=f"no {TENANT} tenant")
                continue
            stats = await _seed_one_system(db, org.id, sysdef, base_url, TENANT)
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
    print("星途热熔胶 mock 连接器 / 数据接口 / 9 部门级技能 导入完成")
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
    print("提示：在管理端「星途热熔胶」组织下查看 连接器 / 数据接口 / 技能 页；")
    print("      终端任务勾选归口部门技能后，agent 自然语言调用 mock（tenant=starhma）。")
    print("=" * 70)


if __name__ == "__main__":
    res = asyncio.run(seed())
    _print_report(res)
