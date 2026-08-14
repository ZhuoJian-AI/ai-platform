"""EPC 多租户确定性种子数据——starexploration（星途勘探，工程总承包与项目管理）。

EPC 是叶系统（其他 mock 不反向引用 EPC），沿用懒构建。``starexploration`` 一份
``EpcData``，覆盖工程项目 / 进度工序 / 现场隐患（感知类，仅返识别结果+整改工单，
不生成视频）/ 项目文档，支撑「项目进度风险预警 + 成本管控 + 现场安全监管」场景。

码空间约定（no-guessing，详见 seed ontology ``identifiers.md``）：
  - 项目 ``PRJ-``（PRJ-IND- / PRJ-BAT- / PRJ-CIV-）；与 DES 设计方案 ``SCH-`` 按
    ``scheme_no`` 关联（方案转项目，PRJ-BAT-001 ↔ SCH-BAT-001）。
  - 进度工序 ``SCD-``（关键路径节点）。
  - 现场隐患 ``HAZ-``（感知类，含 sample_desc 描述现场画面）。
  - 项目文档 ``PDOC-``（合同/图纸/签证/验收）；图纸类交付物与 DES ``DWG-`` 按
    ``drawing_no`` 关联、与 SEC ``SECDOC-`` 按文档号关联（脱密对象）。
  - 成本：项目成本中心与 ERP 按 ``cost_center_code`` 关联；采购按 ERP ``po_no`` 关联。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from mock.core import data as D
from mock.core.tenant import LazyTenantRegistry

BASE_DATE: date = date(2026, 7, 23)


# ───────────────────────── 多租户数据容器 ─────────────────────────


@dataclass
class EpcData:
    projects: list[dict]                     # 工程项目
    project_by_code: dict[str, dict]
    schedule_activities: list[dict]          # 进度工序（关键路径节点）
    site_hazards: list[dict]                 # 现场隐患（感知类）
    project_documents: list[dict]            # 项目文档（合同/图纸/签证/验收）


# ───────────────────────── starexploration（星途勘探） ─────────────────────────


def _build_starexploration() -> EpcData:
    """星途勘探 EPC 口径：三总承包项目 + 关键路径工序 + 现场隐患 + 项目文档。"""
    R = D.rng(20260723)

    projects = [
        {"project_code": "PRJ-IND-001", "name": "电工装备制造厂房 EPC 总承包",
         "scheme_no": "SCH-IND-001", "client_code": "CT-SE-001",
         "site": "湖南长沙经开区", "contract_wan": 18500, "cost_center_code": "CC-IND-001",
         "start_date": "2026-03-01", "plan_end_date": "2027-02-28",
         "progress_pct": 42.0, "status": "在建", "pm": "P-DES-001",
         "critical_path": ["SCD-001", "SCD-003", "SCD-005"],
         "updated_at": f"{BASE_DATE}"},
        {"project_code": "PRJ-BAT-001", "name": "锂离子电池工厂 EPC 总承包",
         "scheme_no": "SCH-BAT-001", "client_code": "CT-SE-002",
         "site": "江苏常州高新区", "contract_wan": 92000, "cost_center_code": "CC-BAT-001",
         "start_date": "2026-05-15", "plan_end_date": "2027-12-31",
         "progress_pct": 18.0, "status": "在建", "pm": "P-DES-002",
         "critical_path": ["SCD-002", "SCD-004"],
         "updated_at": f"{BASE_DATE}"},
        {"project_code": "PRJ-CIV-001", "name": "市政污水处理厂 EPC 总承包",
         "scheme_no": "SCH-CIV-001", "client_code": "CT-SE-003",
         "site": "安徽合肥滨湖", "contract_wan": 31500, "cost_center_code": "CC-CIV-001",
         "start_date": "2026-06-10", "plan_end_date": "2027-06-30",
         "progress_pct": 9.0, "status": "前期", "pm": "P-DES-003",
         "critical_path": ["SCD-006"],
         "updated_at": f"{BASE_DATE}"},
    ]
    project_by_code = {p["project_code"]: p for p in projects}

    # 进度工序（关键路径节点，含计划/实际/延误天）
    schedule_activities = [
        {"activity_no": "SCD-001", "project_code": "PRJ-IND-001", "name": "基础施工",
         "plan_start": "2026-03-10", "plan_finish": "2026-05-20",
         "actual_finish": "2026-05-28", "delay_days": 8, "on_critical_path": True,
         "status": "完成", "weight_pct": 15.0},
        {"activity_no": "SCD-002", "project_code": "PRJ-BAT-001", "name": "桩基与基础",
         "plan_start": "2026-05-20", "plan_finish": "2026-08-10",
         "actual_finish": None, "delay_days": 3, "on_critical_path": True,
         "status": "进行中", "weight_pct": 12.0},
        {"activity_no": "SCD-003", "project_code": "PRJ-IND-001", "name": "主体结构",
         "plan_start": "2026-05-30", "plan_finish": "2026-09-30",
         "actual_finish": None, "delay_days": 5, "on_critical_path": True,
         "status": "进行中", "weight_pct": 25.0},
        {"activity_no": "SCD-004", "project_code": "PRJ-BAT-001", "name": "主体结构",
         "plan_start": "2026-08-15", "plan_finish": "2026-12-30",
         "actual_finish": None, "delay_days": 0, "on_critical_path": True,
         "status": "未开始", "weight_pct": 28.0},
        {"activity_no": "SCD-005", "project_code": "PRJ-IND-001", "name": "机电安装",
         "plan_start": "2026-10-01", "plan_finish": "2027-01-15",
         "actual_finish": None, "delay_days": 0, "on_critical_path": True,
         "status": "未开始", "weight_pct": 20.0},
        {"activity_no": "SCD-006", "project_code": "PRJ-CIV-001", "name": "水池主体",
         "plan_start": "2026-07-01", "plan_finish": "2026-11-30",
         "actual_finish": None, "delay_days": 0, "on_critical_path": True,
         "status": "未开始", "weight_pct": 30.0},
    ]

    # 现场隐患（感知类：sample_desc 描述画面，返识别结果 + 整改工单，不生成视频/图片）
    site_hazards = [
        {"hazard_no": "HAZ-2026-001", "project_code": "PRJ-IND-001",
         "category": "个人防护", "desc": "作业人员未佩戴安全帽进入施工区域",
         "sample_desc": "摄像头 C07 画面：3 名作业人员未戴安全帽通过 2#塔吊下方作业区",
         "severity": "高", "location": "2#塔吊下方作业区", "detected_at": f"{BASE_DATE}T09:12:00",
         "status": "待整改", "rectification_order": "RO-2026-001",
         "rectification": "现场安全教育 + 督促佩戴安全帽 + 复查"},
        {"hazard_no": "HAZ-2026-002", "project_code": "PRJ-IND-001",
         "category": "临时用电", "desc": "临时用电线缆拖地未做绝缘保护",
         "sample_desc": "摄像头 C12 画面：配电箱至楼层线缆拖地浸水、接头裸露",
         "severity": "中", "location": "主体结构 1 层", "detected_at": f"{BASE_DATE}T10:05:00",
         "status": "待整改", "rectification_order": "RO-2026-002",
         "rectification": "线缆架空或穿管保护 + 规范接头处理 + 复电前绝缘测试"},
        {"hazard_no": "HAZ-2026-003", "project_code": "PRJ-BAT-001",
         "category": "消防", "desc": "易燃材料堆放区未配置消防器材",
         "sample_desc": "无人机航拍画面：洁净车间南侧临时堆场堆放保温板，无灭火器与禁烟标识",
         "severity": "高", "location": "洁净车间南侧堆场", "detected_at": f"{BASE_DATE - timedelta(days=1)}T15:40:00",
         "status": "已整改", "rectification_order": "RO-2026-003",
         "rectification": "增设消防器材 + 设置禁烟标识 + 材料分类隔离堆放"},
        {"hazard_no": "HAZ-2026-004", "project_code": "PRJ-BAT-001",
         "category": "高空作业", "desc": "高空作业未设置临边防护",
         "sample_desc": "摄像头 C03 画面：二层结构临边无防护栏，作业人员临边作业",
         "severity": "高", "location": "主体结构二层临边", "detected_at": f"{BASE_DATE}T11:20:00",
         "status": "待整改", "rectification_order": "RO-2026-004",
         "rectification": "立即停工 + 设置临边防护栏 + 验收后复工"},
    ]

    # 项目文档（图纸类交付物关联 DES DWG-，可被 SEC 脱密）
    project_documents = [
        {"doc_no": "PDOC-IND-001", "project_code": "PRJ-IND-001", "type": "合同",
         "title": "电工装备厂房 EPC 总承包合同", "linked_code": "CT-SE-001",
         "confidential": False, "status": "已归档", "updated_at": f"{BASE_DATE - timedelta(days=110)}"},
        {"doc_no": "PDOC-IND-002", "project_code": "PRJ-IND-001", "type": "图纸",
         "title": "厂房建筑总平面与立面图", "linked_code": "DWG-ARC-001",
         "confidential": False, "status": "已交付", "updated_at": f"{BASE_DATE - timedelta(days=5)}"},
        {"doc_no": "PDOC-IND-003", "project_code": "PRJ-IND-001", "type": "图纸",
         "title": "厂房结构图（含基础计算书）", "linked_code": "DWG-STR-001",
         "confidential": True, "status": "已交付", "updated_at": f"{BASE_DATE - timedelta(days=4)}"},
        {"doc_no": "PDOC-IND-004", "project_code": "PRJ-IND-001", "type": "签证",
         "title": "基础变更签证", "linked_code": None,
         "confidential": False, "status": "待审批", "updated_at": f"{BASE_DATE - timedelta(days=2)}"},
        {"doc_no": "PDOC-BAT-001", "project_code": "PRJ-BAT-001", "type": "合同",
         "title": "电池工厂 EPC 总承包合同", "linked_code": "CT-SE-002",
         "confidential": True, "status": "已归档", "updated_at": f"{BASE_DATE - timedelta(days=60)}"},
        {"doc_no": "PDOC-BAT-002", "project_code": "PRJ-BAT-001", "type": "图纸",
         "title": "电池工厂结构方案图", "linked_code": "DWG-STR-002",
         "confidential": False, "status": "已交付", "updated_at": f"{BASE_DATE - timedelta(days=2)}"},
    ]

    return EpcData(
        projects=projects, project_by_code=project_by_code,
        schedule_activities=schedule_activities, site_hazards=site_hazards,
        project_documents=project_documents,
    )


# ───────────────────────── 多租户注册表（懒构建） ─────────────────────────


TENANTS = LazyTenantRegistry[EpcData]({
    "starexploration": _build_starexploration,
})


def load(tenant: str) -> EpcData:
    return TENANTS.load(tenant)


def all_tenant_ids() -> list[str]:
    return TENANTS.known_tenants()


# ── 派生量 ───────────────────────────────────────────────────


def predict_schedule_risk(tenant: str, project_code: str) -> dict:
    """项目进度风险预测：按关键路径工序延误天 + 权重估算工期风险与建议（确定性派生）。"""
    d = load(tenant)
    prj = d.project_by_code.get(project_code)
    if prj is None:
        return {}
    acts = [a for a in d.schedule_activities if a["project_code"] == project_code]
    critical = [a for a in acts if a["on_critical_path"]]
    delayed = [a for a in critical if (a["delay_days"] or 0) > 0]
    total_delay = sum(a["delay_days"] or 0 for a in delayed)
    # 关键路径累计延误即工期风险（粗略确定性映射）
    risk_score = min(100, total_delay * 6 + len(delayed) * 4)
    risk_level = ("高" if risk_score >= 50 else "中" if risk_score >= 25 else "低")
    return {
        "project_code": project_code, "name": prj["name"],
        "progress_pct": prj["progress_pct"], "plan_end_date": prj["plan_end_date"],
        "critical_path": prj["critical_path"],
        "critical_delayed_activities": [
            {"activity_no": a["activity_no"], "name": a["name"],
             "delay_days": a["delay_days"], "status": a["status"],
             "weight_pct": a["weight_pct"]} for a in delayed],
        "total_critical_delay_days": total_delay,
        "risk_score": risk_score, "risk_level": risk_level,
        "recommendation": ("启动赶工/资源调配，重排关键路径工序排程" if risk_score >= 50
                           else "关注延误工序，预警下游关键节点" if risk_score >= 25
                           else "进度可控，维持正常排程"),
    }


def detect_site_hazard(tenant: str, project_code: str, sample_desc: str) -> dict:
    """现场隐患识别（感知类）：据 sample_desc 匹配该项目的隐患记录，返识别结果+整改工单。
    不生成图片/视频，仅基于文本画面描述匹配并给出整改建议。"""
    d = load(tenant)
    prj = d.project_by_code.get(project_code)
    if prj is None:
        return {}
    matches = [h for h in d.site_hazards
               if h["project_code"] == project_code and h["sample_desc"] == sample_desc]
    if not matches:
        # 退而按项目+desc 关键词宽松匹配
        kw = {c for c in ["安全帽", "线缆", "消防", "临边", "高空"] if c in sample_desc}
        matches = [h for h in d.site_hazards
                   if h["project_code"] == project_code and kw & set(h["desc"])]
    return {
        "project_code": project_code, "input_sample_desc": sample_desc,
        "identified_count": len(matches),
        "identified_hazards": [
            {"hazard_no": h["hazard_no"], "category": h["category"], "desc": h["desc"],
             "severity": h["severity"], "location": h["location"], "status": h["status"],
             "rectification_order": h["rectification_order"],
             "rectification": h["rectification"]} for h in matches],
        "note": "感知类端点：仅返文本识别结果与整改工单，不生成图片/视频",
    }
