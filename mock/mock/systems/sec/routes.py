"""SEC 路由——保密与合规管理只读查询。

多租户：经 ``Depends(get_tenant)`` 取 tenant，再调 ``data.load(tenant)`` 取数。
``operationId`` 保持稳定。全部 GET。path 参数用真实码（如 ``SECDOC-001``、
``DWG-STR-001``），勿用 ``{code}`` 占位。``scanConfidentiality`` / ``desensitizeDocument``
按来源文档号（DES ``DWG-`` / EPC ``PDOC-``）查询；行为预警列出异常行为日志。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from mock.core.tenant import get_tenant
from . import data as M

router = APIRouter(prefix="/api/v1", tags=["SEC 保密与合规"])


# ── 涉密文档 ───────────────────────────────────────────────

@router.get("/confidential-docs", operation_id="listConfidentialDocs",
            summary="涉密文档清单（按密级/项目过滤）")
def list_confidential_docs(
    tenant: Annotated[str, Depends(get_tenant)],
    classification: Annotated[str | None, Query(description="机密/秘密/内部")] = None,
    project_code: Annotated[str | None, Query(description="项目号 PRJ-...")] = None,
) -> list[dict]:
    rows = M.load(tenant).confidential_docs
    if classification:
        rows = [r for r in rows if r["classification"] == classification]
    if project_code:
        rows = [r for r in rows if r.get("project_code") == project_code]
    return rows


@router.get("/confidential-docs/{doc_no}", operation_id="getConfidentialDoc",
            summary="涉密文档详情（密级/敏感词/来源）")
def get_confidential_doc(
    doc_no: Annotated[str, Path(description="涉密文档号，如 SECDOC-001")],
    tenant: Annotated[str, Depends(get_tenant)],
) -> dict:
    d = M.load(tenant)
    doc = d.doc_by_code.get(doc_no)
    if doc is None:
        raise HTTPException(404, f"confidential doc {doc_no} not found")
    marks = [m for m in d.confidential_marks if m["doc_no"] == doc_no]
    return {**doc, "marks": marks}


# ── 涉密标记 / 脱敏记录 / 行为日志 ───────────────────────

@router.get("/confidential-marks", operation_id="listConfidentialFlags",
            summary="涉密标记清单（密级/条文/图样定位；按文档过滤）")
def list_confidential_marks(
    tenant: Annotated[str, Depends(get_tenant)],
    doc_no: Annotated[str | None, Query(description="涉密文档号 SECDOC-...")] = None,
) -> list[dict]:
    rows = M.load(tenant).confidential_marks
    if doc_no:
        rows = [r for r in rows if r["doc_no"] == doc_no]
    return rows


@router.get("/desensitization-records", operation_id="listDesensitizationRecords",
            summary="脱敏记录清单（脱密产物 + 处理方式）")
def list_desensitization_records(
    tenant: Annotated[str, Depends(get_tenant)],
    source_system: Annotated[str | None, Query(description="DES/EPC")] = None,
) -> list[dict]:
    rows = M.load(tenant).desensitization_records
    if source_system:
        rows = [r for r in rows if r["source_system"] == source_system]
    return rows


@router.get("/behavior-logs", operation_id="listBehaviorLogs",
            summary="行为日志清单（含异常标记）")
def list_behavior_logs(
    tenant: Annotated[str, Depends(get_tenant)],
    risk_level: Annotated[str | None, Query(description="高/中/低")] = None,
) -> list[dict]:
    rows = M.load(tenant).behavior_logs
    if risk_level:
        rows = [r for r in rows if r["risk_level"] == risk_level]
    return rows


# ── 业务端点（GET + query 参数，便于技能绑定） ───────────────

@router.get("/scan-confidentiality", operation_id="scanConfidentiality",
            summary="涉密内容检测（按来源文档号 DES DWG-/EPC PDOC- 返密级+标记+是否需脱密）")
def scan_confidentiality(
    tenant: Annotated[str, Depends(get_tenant)],
    source_doc: Annotated[str, Query(description="来源文档号，如 DWG-STR-001 或 PDOC-BAT-001；亦可直传 SECDOC-001")],
    source_system: Annotated[str, Query(description="来源系统：DES/EPC；直传 SECDOC- 时任填")] = "DES",
) -> dict:
    res = M.scan_confidentiality(tenant, source_doc, source_system)
    if not res.get("matched_docs") and not res.get("confidential_marks") and res["highest_classification"] == "内部":
        # 仅当完全无匹配且为默认内部时，仍返回结果（非 404），便于 LLM 知悉「未发现涉密」
        return res
    return res


@router.get("/desensitize", operation_id="desensitizeDocument",
            summary="文档脱密（按来源文档号产出脱敏记录）")
def desensitize_document(
    tenant: Annotated[str, Depends(get_tenant)],
    source_doc: Annotated[str, Query(description="来源文档号，如 DWG-ARC-001 或 PDOC-BAT-001")],
    source_system: Annotated[str, Query(description="来源系统：DES/EPC")] = "DES",
) -> dict:
    return M.desensitize_document(tenant, source_doc, source_system)


@router.get("/behavior-anomalies", operation_id="listBehaviorAnomalies",
            summary="保密行为预警（高频下载/非工作时间/尝试外发，按风险排序）")
def list_behavior_anomalies(
    tenant: Annotated[str, Depends(get_tenant)],
) -> list[dict]:
    return M.list_behavior_anomalies(tenant)
