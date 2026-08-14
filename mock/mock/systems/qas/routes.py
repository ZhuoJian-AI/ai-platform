"""QAS 路由——质量与技术服务只读查询。

多租户：经 ``Depends(get_tenant)`` 取 tenant，再调 ``data.load(tenant)`` 取数。
``operationId`` 保持稳定。全部 GET（业务端点亦为 GET+query/path 参数，便于技能只绑
GET 端点）。path 参数一律用真实码（如 ``CC-2026-001``），勿用 ``{code}`` 占位。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from mock.core.tenant import get_tenant
from . import data as M

router = APIRouter(prefix="/api/v1", tags=["QAS 质量与技术服务"])


# ── 检测报告 ───────────────────────────────────────────────

@router.get("/quality-reports", operation_id="listQualityReports",
            summary="检测报告列表（按类型/批次/配方过滤）")
def list_quality_reports(
    tenant: Annotated[str, Depends(get_tenant)],
    type: Annotated[str | None, Query(description="来料/成品")] = None,
    batch_no: Annotated[str | None, Query(description="MES 批次 BAT-...")] = None,
    formula_no: Annotated[str | None, Query(description="配方 FORM-...")] = None,
) -> list[dict]:
    rows = M.load(tenant).quality_reports
    if type:
        rows = [r for r in rows if r["type"] == type]
    if batch_no:
        rows = [r for r in rows if r.get("batch_no") == batch_no]
    if formula_no:
        rows = [r for r in rows if r.get("formula_no") == formula_no]
    return rows


@router.get("/quality-reports/{qr_no}", operation_id="getQualityReport",
            summary="检测报告详情")
def get_quality_report(
    qr_no: Annotated[str, Path(description="报告号，如 QR-FG-2026-002")],
    tenant: Annotated[str, Depends(get_tenant)],
) -> dict:
    q = M.load(tenant).quality_report_by_code.get(qr_no)
    if q is None:
        raise HTTPException(404, f"quality report {qr_no} not found")
    return q


@router.get("/inspection-report", operation_id="generateInspectionReport",
            summary="检测报告自动生成（聚合来料/成品检验数据）")
def generate_inspection_report(
    tenant: Annotated[str, Depends(get_tenant)],
    batch_no: Annotated[str | None, Query(description="MES 批次 BAT-...")] = None,
    qr_no: Annotated[str | None, Query(description="报告号 QR-...")] = None,
) -> dict:
    res = M.generate_inspection_report(tenant, batch_no=batch_no, qr_no=qr_no)
    if not res:
        raise HTTPException(404, "no quality report for given batch/qr")
    return res


# ── 客诉 ───────────────────────────────────────────────────

@router.get("/complaints", operation_id="listCustomerComplaints",
            summary="客诉列表（按客户/现象/状态过滤）")
def list_customer_complaints(
    tenant: Annotated[str, Depends(get_tenant)],
    customer_code: Annotated[str | None, Query(description="客户码 CLI-...")] = None,
    symptom: Annotated[str | None, Query(description="开胶/拉丝/堵枪/低温失效")] = None,
    status: Annotated[str | None, Query(description="处理中/待复测/已闭环")] = None,
) -> list[dict]:
    rows = M.load(tenant).customer_complaints
    if customer_code:
        rows = [r for r in rows if r["customer_code"] == customer_code]
    if symptom:
        rows = [r for r in rows if r["symptom"] == symptom]
    if status:
        rows = [r for r in rows if r["status"] == status]
    return rows


@router.get("/complaints/{cc_no}", operation_id="getCustomerComplaint",
            summary="客诉详情")
def get_customer_complaint(
    cc_no: Annotated[str, Path(description="客诉号，如 CC-2026-001")],
    tenant: Annotated[str, Depends(get_tenant)],
) -> dict:
    c = M.load(tenant).complaint_by_code.get(cc_no)
    if c is None:
        raise HTTPException(404, f"complaint {cc_no} not found")
    return c


# ── 故障案例 / 根因分析 ───────────────────────────────────

@router.get("/failure-cases", operation_id="listFailureCases",
            summary="故障案例库（按现象过滤，售后诊断知识库）")
def list_failure_cases(
    tenant: Annotated[str, Depends(get_tenant)],
    symptom: Annotated[str | None, Query(description="开胶/拉丝/堵枪/低温失效")] = None,
) -> list[dict]:
    rows = M.load(tenant).failure_cases
    if symptom:
        rows = [r for r in rows if r["symptom"] == symptom]
    return rows


@router.get("/diagnose-fault", operation_id="diagnoseAfterSalesFault",
            summary="售后故障智能诊断（现象+工况匹配案例给排查方案）")
def diagnose_after_sales_fault(
    tenant: Annotated[str, Depends(get_tenant)],
    symptom: Annotated[str | None, Query(description="开胶/拉丝/堵枪/低温失效")] = None,
    substrate: Annotated[str | None, Query(description="粘接基材")] = None,
    condition: Annotated[str | None, Query(description="工况描述")] = None,
) -> dict:
    return M.diagnose_after_sales_fault(
        tenant, symptom=symptom, substrate=substrate, condition=condition,
    )


@router.get("/root-cause", operation_id="analyzeRootCause",
            summary="质量异常根因分析（不良品关联配方/工艺/客诉）")
def analyze_root_cause(
    tenant: Annotated[str, Depends(get_tenant)],
    ng_no: Annotated[str | None, Query(description="不良品号 NG-...")] = None,
    batch_no: Annotated[str | None, Query(description="MES 批次 BAT-...")] = None,
) -> dict:
    res = M.analyze_root_cause(tenant, ng_no=ng_no, batch_no=batch_no)
    if not res:
        raise HTTPException(404, "no ng record for given ng/batch")
    return res


@router.get("/ng-records", operation_id="listNgRecords",
            summary="不良品记录列表")
def list_ng_records(
    tenant: Annotated[str, Depends(get_tenant)],
    batch_no: Annotated[str | None, Query(description="MES 批次 BAT-...")] = None,
) -> list[dict]:
    rows = M.load(tenant).ng_records
    if batch_no:
        rows = [r for r in rows if r["batch_no"] == batch_no]
    return rows
