"""SEC 多租户确定性种子数据——starexploration（星途勘探，保密与合规管理）。

SEC 是叶系统，沿用懒构建。``starexploration`` 一份 ``SecData``，覆盖涉密文档 /
涉密标记 / 脱敏记录 / 行为日志，支撑「涉密内容检测 + 文档脱密 + 保密行为预警」场景。
星途勘探为涉密资质单位，保密管控为核心特色域。

码空间约定（no-guessing，详见 seed ontology ``identifiers.md``）：
  - 涉密文档 ``SECDOC-``；其 ``source_doc`` 关联 DES 图纸 ``DWG-`` 或 EPC 项目文档
    ``PDOC-``（脱密对象来源）。
  - 涉密标记 ``SECMARK-``（密级：机密/秘密/内部，标识具体条文/图样）。
  - 脱敏记录 ``DESEN-``（脱密后产物 + 处理方式）。
  - 行为日志 ``BHV-``（高频下载涉密文件、非工作时间访问等异常行为）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from mock.core import data as D
from mock.core.tenant import LazyTenantRegistry

BASE_DATE: date = date(2026, 7, 23)


# ───────────────────────── 多租户数据容器 ─────────────────────────


@dataclass
class SecData:
    confidential_docs: list[dict]          # 涉密文档（关联 DES/EPC 来源）
    doc_by_code: dict[str, dict]
    confidential_marks: list[dict]         # 涉密标记（密级/条文/图样定位）
    desensitization_records: list[dict]    # 脱敏记录
    behavior_logs: list[dict]              # 行为日志（含异常标记）


# ───────────────────────── starexploration（星途勘探） ─────────────────────────


def _build_starexploration() -> SecData:
    """星途勘探保密口径：涉密文档（含基础计算书/工艺参数/合同）+ 涉密标记 +
    脱敏记录 + 异常行为日志。"""
    R = D.rng(20260723)

    confidential_docs = [
        {"doc_no": "SECDOC-001", "title": "电工装备厂房基础计算书",
         "source_doc": "DWG-STR-001", "source_system": "DES", "project_code": "PRJ-IND-001",
         "classification": "秘密", "content_preview": "...地基承载力特征值 fak=180kPa，桩基设计等级乙级...",
         "sensitive_terms": ["地基承载力", "桩基设计等级", "基础配筋率"],
         "owner": "P-DES-012", "status": "在控", "updated_at": f"{BASE_DATE - timedelta(days=4)}"},
        {"doc_no": "SECDOC-002", "title": "电池工厂核心工艺参数表",
         "source_doc": None, "source_system": "DES", "project_code": "PRJ-BAT-001",
         "classification": "机密", "content_preview": "...极片线速度 80m/min，涂布面密度 250g/m²，能量密度 280Wh/kg...",
         "sensitive_terms": ["极片线速度", "涂布面密度", "能量密度", "良率"],
         "owner": "P-DES-002", "status": "在控", "updated_at": f"{BASE_DATE - timedelta(days=2)}"},
        {"doc_no": "SECDOC-003", "title": "电池工厂 EPC 总承包合同",
         "source_doc": "PDOC-BAT-001", "source_system": "EPC", "project_code": "PRJ-BAT-001",
         "classification": "机密", "content_preview": "...合同金额 9.2 亿元，付款里程碑...保密条款...",
         "sensitive_terms": ["合同金额", "付款里程碑", "保密条款"],
         "owner": "P-DES-002", "status": "在控", "updated_at": f"{BASE_DATE - timedelta(days=60)}"},
        {"doc_no": "SECDOC-004", "title": "电工装备厂房结构施工图（电子版）",
         "source_doc": "DWG-STR-001", "source_system": "DES", "project_code": "PRJ-IND-001",
         "classification": "秘密", "content_preview": "...抗震等级三级，柱配筋率 1.2%，梁配筋率 0.8%...",
         "sensitive_terms": ["抗震等级", "柱配筋率", "梁配筋率"],
         "owner": "P-DES-012", "status": "在控", "updated_at": f"{BASE_DATE - timedelta(days=4)}"},
    ]
    doc_by_code = {d["doc_no"]: d for d in confidential_docs}

    confidential_marks = [
        {"mark_no": "SECMARK-001", "doc_no": "SECDOC-001", "classification": "秘密",
         "term": "地基承载力特征值 fak=180kPa", "location": "第 3 章 第 2 节",
         "marked_at": f"{BASE_DATE - timedelta(days=4)}", "handled": False},
        {"mark_no": "SECMARK-002", "doc_no": "SECDOC-002", "classification": "机密",
         "term": "能量密度 280Wh/kg", "location": "参数表 第 12 行",
         "marked_at": f"{BASE_DATE - timedelta(days=2)}", "handled": False},
        {"mark_no": "SECMARK-003", "doc_no": "SECDOC-003", "classification": "机密",
         "term": "合同金额 9.2 亿元", "location": "第 4 条",
         "marked_at": f"{BASE_DATE - timedelta(days=60)}", "handled": True},
    ]

    desensitization_records = [
        {"record_no": "DESEN-2026-001", "source_doc": "DWG-ARC-001", "source_system": "DES",
         "method": "数值脱敏（隐藏具体坐标/尺寸精度）", "output_doc": "DWG-ARC-001-脱密",
         "classification_before": "秘密", "classification_after": "内部",
         "operator": "P-SEC-001", "operated_at": f"{BASE_DATE - timedelta(days=3)}",
         "status": "已完成"},
        {"record_no": "DESEN-2026-002", "source_doc": "PDOC-BAT-001", "source_system": "EPC",
         "method": "条款脱敏（隐藏金额与里程碑）", "output_doc": "PDOC-BAT-001-脱密",
         "classification_before": "机密", "classification_after": "内部",
         "operator": "P-SEC-001", "operated_at": f"{BASE_DATE - timedelta(days=30)}",
         "status": "已完成"},
    ]

    behavior_logs = [
        {"log_no": "BHV-2026-001", "user": "P-DES-012", "behavior": "高频下载涉密文档",
         "doc_no": "SECDOC-001", "count": 9, "period": "近 7 日",
         "occurred_at": f"{BASE_DATE - timedelta(days=1)}T22:40:00",
         "off_hours": True, "risk_level": "高", "status": "待核查"},
        {"log_no": "BHV-2026-002", "user": "P-DES-023", "behavior": "非工作时间访问涉密系统",
         "doc_no": "SECDOC-002", "count": 3, "period": "近 7 日",
         "occurred_at": f"{BASE_DATE - timedelta(days=1)}T23:15:00",
         "off_hours": True, "risk_level": "中", "status": "待核查"},
        {"log_no": "BHV-2026-003", "user": "P-DES-013", "behavior": "尝试外发涉密文档",
         "doc_no": "SECDOC-004", "count": 1, "period": "近 7 日",
         "occurred_at": f"{BASE_DATE - timedelta(days=2)}T14:20:00",
         "off_hours": False, "risk_level": "高", "status": "已拦截"},
        {"log_no": "BHV-2026-004", "user": "P-DES-021", "behavior": "高频下载涉密文档",
         "doc_no": "SECDOC-002", "count": 6, "period": "近 7 日",
         "occurred_at": f"{BASE_DATE - timedelta(days=2)}T20:05:00",
         "off_hours": False, "risk_level": "中", "status": "待核查"},
    ]

    return SecData(
        confidential_docs=confidential_docs, doc_by_code=doc_by_code,
        confidential_marks=confidential_marks,
        desensitization_records=desensitization_records,
        behavior_logs=behavior_logs,
    )


# ───────────────────────── 多租户注册表（懒构建） ─────────────────────────


TENANTS = LazyTenantRegistry[SecData]({
    "starexploration": _build_starexploration,
})


def load(tenant: str) -> SecData:
    return TENANTS.load(tenant)


def all_tenant_ids() -> list[str]:
    return TENANTS.known_tenants()


# ── 派生量 ───────────────────────────────────────────────────


def scan_confidentiality(tenant: str, source_doc: str, source_system: str = "DES") -> dict:
    """涉密内容检测：按来源文档号（DES DWG- / EPC PDOC-）匹配涉密文档，返密级 +
    涉密标记 + 是否需脱密（确定性派生，不杜撰密级）。"""
    d = load(tenant)
    docs = [c for c in d.confidential_docs
            if c.get("source_doc") == source_doc and c.get("source_system") == source_system]
    if not docs:
        # 退而按 doc_no 直查（直接传 SECDOC-）
        direct = d.doc_by_code.get(source_doc)
        if direct:
            docs = [direct]
    marks = [m for c in docs for m in d.confidential_marks if m["doc_no"] == c["doc_no"]]
    highest = max((c["classification"] for c in docs), key=lambda x: {"机密": 3, "秘密": 2, "内部": 1}.get(x, 0), default="内部")
    return {
        "source_doc": source_doc, "source_system": source_system,
        "matched_docs": [{"doc_no": c["doc_no"], "title": c["title"],
                          "classification": c["classification"],
                          "sensitive_terms": c["sensitive_terms"],
                          "project_code": c.get("project_code")}
                         for c in docs],
        "confidential_marks": [{"mark_no": m["mark_no"], "term": m["term"],
                                "location": m["location"], "handled": m["handled"]}
                               for m in marks],
        "highest_classification": highest,
        "needs_desensitization": highest in ("机密", "秘密"),
        "recommendation": ("建议脱密后外发/共享" if highest in ("机密", "秘密")
                           else "可直接内部使用，外发前仍需复核"),
    }


def desensitize_document(tenant: str, source_doc: str, source_system: str = "DES") -> dict:
    """文档脱密：据来源文档查涉密标记并产出脱敏记录（确定性派生）。"""
    d = load(tenant)
    scan = scan_confidentiality(tenant, source_doc, source_system)
    cls_before = scan["highest_classification"]
    cls_after = "内部" if cls_before in ("机密", "秘密") else cls_before
    method = ("条款脱敏（隐藏金额/里程碑/工艺参数）" if source_system == "EPC"
              else "数值脱敏（隐藏坐标/尺寸/配筋率精度）")
    record_no = f"DESEN-2026-{len(d.desensitization_records) + 1:03d}"
    return {
        "record_no": record_no, "source_doc": source_doc, "source_system": source_system,
        "method": method, "output_doc": f"{source_doc}-脱密",
        "classification_before": cls_before, "classification_after": cls_after,
        "terms_handled": [m["term"] for m in scan["confidential_marks"] if not m["handled"]],
        "operator": "P-SEC-001", "operated_at": f"{BASE_DATE}",
        "status": "已完成",
        "note": "脱敏记录需保密办复核归档后生效",
    }


def list_behavior_anomalies(tenant: str) -> list[dict]:
    """保密行为预警：列出异常行为日志（高频下载/非工作时间/尝试外发），按风险排序。"""
    d = load(tenant)
    rows = [b for b in d.behavior_logs if b["risk_level"] in ("高", "中")]
    rows.sort(key=lambda b: ({"高": 2, "中": 1}[b["risk_level"]], b["count"]),
             reverse=True)
    return [{"log_no": b["log_no"], "user": b["user"], "behavior": b["behavior"],
             "doc_no": b["doc_no"], "count": b["count"], "period": b["period"],
             "occurred_at": b["occurred_at"], "off_hours": b["off_hours"],
             "risk_level": b["risk_level"], "status": b["status"]} for b in rows]
