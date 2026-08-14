"""为「星途勘探」组织注册 mock 连接器 + 端点 + 数据接口 + 9 个部门级技能。

与 ``seed_agilestationery_mock_connectors.py`` 同构，差异：
  - 目标组织 slug=``starexploration``，使用各系统的 ``starexploration`` 专属 API key；
  - 6 个 mock 系统（erp/crm/hrm + des/epc/sec）注册了 starexploration tenant，
    循环 ``MOCK_SYSTEMS`` 时自动跳过未授权 tenant 的系统（mes/plm/scm/eqm/ems/ehs/pim/cst/chn）；
  - 9 个部门级技能（按场景归口，绑定相关系统子集 GET 端点）；无组织级技能。
  - 数据接口仍保持 org 级镜像，scope 隔离靠 SkillFolder 实现：员工终端任务勾选其部门技能时，
    agent ``_build_tools`` 只暴露 bound_endpoint_ids 对应的工具，自然实现部门级数据可见性边界。

幂等：按 slug / name 去重，已存在则更新 spec / 端点 / 技能绑定。可安全重复执行。

前置：先启 mock 网关 :8010（含 des/epc/sec）与 ``python scripts/seed_starexploration_org.py``。
重建 backend 后必先 ``docker cp mock/mock ai_infra_backend:/app/mock`` 注入 mock 包。

用法:
    docker cp demo/starexploration/scripts/seed_starexploration_mock_connectors.py ai_infra_backend:/app/scripts/
    MOCK_BASE_URL=http://ai_infra_mock:8010 docker exec -e MOCK_BASE_URL=http://ai_infra_mock:8010 \
        ai_infra_backend python scripts/seed_starexploration_mock_connectors.py
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

ORG_SLUG = os.getenv("MOCK_SEED_ORG_SLUG", "starexploration")
DEFAULT_BASE_URL = os.getenv("MOCK_BASE_URL", "http://localhost:8010")
TENANT = "starexploration"


# ───────────────────────── 9 个技能定义（9 dept，无 org 级） ─────────────────────────

SKILL_DEFS = [
    # 1. DES 设计研究院（des 方案/图纸/规范/合规/碰撞 + erp 物料库存）
    {
        "slug": "starexploration-design-des-erp-query",
        "name": "星途勘探·设计研究院 查询技能",
        "scope_type": "department",
        "dept_slug": "design",
        "bindings": {
            "des": ["listSchemes", "getScheme", "listDrawings", "getDrawing", "listSpecs",
                    "checkDrawingCompliance", "detectClashes", "listQuantityItems"],
            "erp": ["listMaterials", "listInventory"],
        },
        "description": "设计合规工程师：查设计方案(SCH-IND-/SCH-BAT-/SCH-CIV-)/图纸(DWG-ARC-/DWG-STR-/DWG-MEP-)/规范强条(SPEC-GB-)/图纸合规校验(返违规项+修正)/跨专业碰撞(CLS-)/算量项(QTI-CON-/QTI-STE-)——支撑设计方案智能比选与规范合规校验闭环。",
    },
    # 2. QTO 造价技经部（des 算量/造价 + erp 物料/采购/成本中心）
    {
        "slug": "starexploration-cost-des-erp-query",
        "name": "星途勘探·造价技经部 查询技能",
        "scope_type": "department",
        "dept_slug": "cost",
        "bindings": {
            "des": ["listSchemes", "getScheme", "listDrawings", "listQuantityItems",
                    "computeQuantityTakeoff"],
            "erp": ["listMaterials", "listPurchaseOrders", "listInventory", "listCostCenters",
                    "listStockMovements"],
        },
        "description": "造价工程师：查方案算量项(QTI-)并测算造价(联动 ERP 物料 M-CON-/M-STE- prefix 转换)+采购单(POSE-)/库存/成本中心(CC-IND-/CC-BAT-/CC-CIV-)/出入库——支撑智能算量与造价测算闭环。",
    },
    # 3. FIN 资产财务部（erp 凭证/应付/采购/成本 + crm 应收/合同/争议）
    {
        "slug": "starexploration-finance-erp-crm-query",
        "name": "星途勘探·资产财务部 查询技能",
        "scope_type": "department",
        "dept_slug": "finance",
        "bindings": {
            "erp": ["listVouchers", "listPayables", "listPurchaseOrders", "listCostCenters",
                    "listMaterials", "listInventory", "listStockMovements", "listProductionCosts"],
            "crm": ["listReceivables", "listSalesOrders", "listCustomers", "listComplaints"],
        },
        "description": "财务会计：跨 ERP/CRM 对账（凭证 BV-SE-↔发票 INV-↔应付/回款 REC-）+ 票据识别验真 + 应收催收 + 项目成本(PC-SE-)——支撑票据识别审核与智能核算闭环。",
    },
    # 4. ADM 综合管理部（hrm 会议/部门/员工/考勤/请假）
    {
        "slug": "starexploration-admin-hrm-query",
        "name": "星途勘探·综合管理部 查询技能",
        "scope_type": "department",
        "dept_slug": "admin",
        "bindings": {
            "hrm": ["listMeetings", "listDepartments", "getDepartment", "listEmployees",
                    "listAttendance", "listLeaves"],
        },
        "description": "行政专员：查会议纪要(SEMT-)/部门(PD-)/员工(SEOF-)/考勤/请假——支撑公文生成与会议纪要闭环（提取待办与责任人、跟踪任务闭环）。",
    },
    # 5. LEG 法律合规部（crm 合同/客户/争议/回款 + erp 凭证/采购）
    {
        "slug": "starexploration-legal-crm-erp-query",
        "name": "星途勘探·法律合规部 查询技能",
        "scope_type": "department",
        "dept_slug": "legal",
        "bindings": {
            "crm": ["listSalesOrders", "listCustomers", "getCustomer", "listComplaints",
                    "getComplaint", "listFollowUps", "listReceivables"],
            "erp": ["listVouchers", "listPurchaseOrders", "listCostCenters"],
        },
        "description": "法务专员：查中标合同(CT-SE-)/工程客户(CLI-)/履约争议(DSP-)/回款(REC-) + 凭证(BV-SE-)/采购(POSE-)——支撑合同智能审查与履约风险校验（风险点+修改建议+履约节点提醒）。",
    },
    # 6. EPC 总承包部（epc 项目/进度/隐患/文档 + erp 成本/采购/库存）
    {
        "slug": "starexploration-epc-epc-erp-query",
        "name": "星途勘探·EPC 总承包部 查询技能",
        "scope_type": "department",
        "dept_slug": "epc",
        "bindings": {
            "epc": ["listProjects", "getProject", "listScheduleActivities", "predictScheduleRisk",
                    "listProjectDocuments", "listSiteHazards"],
            "erp": ["listCostCenters", "listPurchaseOrders", "listInventory", "listProductionCosts",
                    "listStockMovements"],
        },
        "description": "项目经理：查工程项目(PRJ-IND-/PRJ-BAT-/PRJ-CIV-)/进度工序(SCD-)/进度风险预测(关键路径延误)/项目文档(PDOC-)/现场隐患(HAZ-) + 成本中心(CC-)/采购/项目成本(PC-SE-)——支撑项目进度风险预警与成本管控。",
    },
    # 7. SAF 安全生产部（epc 项目/隐患/识别 + 进度）
    {
        "slug": "starexploration-safety-epc-query",
        "name": "星途勘探·安全生产部 查询技能",
        "scope_type": "department",
        "dept_slug": "safety",
        "bindings": {
            "epc": ["listProjects", "getProject", "listSiteHazards", "detectSiteHazard",
                    "listScheduleActivities"],
        },
        "description": "安全巡检工程师：查工程项目(PRJ-)/现场隐患(HAZ-，含 sample_desc 画面描述)/隐患识别(感知类，返识别结果+整改工单，不生成视频)/进度工序——支撑施工现场安全隐患智能识别与整改闭环。",
    },
    # 8. SEC 保密办公室（sec 涉密/标记/脱敏/行为 + des 图纸 + epc 文档）
    {
        "slug": "starexploration-security-sec-des-epc-query",
        "name": "星途勘探·保密办公室 查询技能",
        "scope_type": "department",
        "dept_slug": "security",
        "bindings": {
            "sec": ["listConfidentialDocs", "getConfidentialDoc", "listConfidentialFlags",
                    "listDesensitizationRecords", "listBehaviorLogs", "scanConfidentiality",
                    "desensitizeDocument", "listBehaviorAnomalies"],
            "des": ["listDrawings", "getDrawing"],
            "epc": ["listProjectDocuments"],
        },
        "description": "保密专员：查涉密文档(SECDOC-)/涉密标记(SECMARK-)/脱敏记录(DESEN-)/行为日志(BHV-) + 涉密检测(按来源 DES DWG-/EPC PDOC- 返密级+是否需脱密) + 文档脱密 + 行为预警(高频下载/非工作时间/外发)——支撑涉密内容检测与文档脱密闭环。",
    },
    # 9. HR 人力资源部（hrm 全查询，不含 POST 端点）
    {
        "slug": "starexploration-hr-hrm-query",
        "name": "星途勘探·人力资源部 查询技能",
        "scope_type": "department",
        "dept_slug": "hr",
        "bindings": {
            "hrm": ["listEmployees", "getEmployee", "listDepartments", "getDepartment",
                    "listPositions", "listRecruitments", "listResumesByPosition",
                    "listMeetings", "listPerformances", "listAttendance"],
        },
        "description": "招聘专员：查员工(SEOF-)/部门(PD-DES/PD-COST/...)/岗位(P-DES/P-COST/...)/招聘需求(ASRC)/简历库(SERM-，按岗位)/会议纪要/绩效——支撑智能招聘与人岗匹配闭环。",
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
            " 请先启 mock 网关（含 des/epc/sec）。"
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
    conn_name = f"{sysdef.name}（星途勘探）"
    conn_desc = f"星途勘探 {sysdef.name} mock（tenant={tenant}）"
    if conn is None:
        conn = await create_connector(db, org_id, ToolConnectorCreate(
            name=conn_name, slug=slug, description=conn_desc,
            type=sysdef.key, base_url=base, auth_type="apikey",
            auth_config=auth_cfg, spec=spec, is_active=True,
        ))
        stats["connector"] += 1
        logger.info("starexploration_connector_created", system=sysdef.key, slug=slug)
    else:
        await update_connector(db, conn, ToolConnectorUpdate(
            base_url=base, auth_type="apikey", auth_config=auth_cfg, spec=spec, is_active=True,
            name=conn_name, description=conn_desc,
        ))
        logger.info("starexploration_connector_updated", system=sysdef.key, slug=slug)

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
            logger.warning("starexploration_skill_dept_missing", slug=skill_def["slug"],
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
        logger.info("starexploration_skill_created", slug=skill_def["slug"], bound=len(bound_endpoints))
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
                f"组织 slug='{ORG_SLUG}' 不存在，请先运行 python scripts/seed_starexploration_org.py。"
            )
        logger.info("starexploration_mock_org", slug=org.slug, org_id=str(org.id))

        sysdef_by_key: dict = {}
        system_stats: dict = {}
        for sysdef in MOCK_SYSTEMS:
            if TENANT not in sysdef.tenants:
                logger.info("starexploration_skip_system", system=sysdef.key, reason=f"no {TENANT} tenant")
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
    print("星途勘探 mock 连接器 / 数据接口 / 9 部门级技能 导入完成")
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
    print("提示：在管理端「星途勘探」组织下查看 连接器 / 数据接口 / 技能 页；")
    print("      终端任务勾选归口部门技能后，agent 自然语言调用 mock（tenant=starexploration）。")
    print("=" * 70)


if __name__ == "__main__":
    res = asyncio.run(seed())
    _print_report(res)
