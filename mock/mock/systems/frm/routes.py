"""FRM 路由——配方研发管理只读查询。

多租户：经 ``Depends(get_tenant)`` 取 tenant，再调 ``data.load(tenant)`` 取数。
``operationId`` 保持稳定，平台 spec 导入与技能绑定不受影响。全部 GET（业务端点亦为
GET+query 参数，便于技能只绑 GET 端点）。path 参数一律用真实码（如 ``FORM-CUS-002``），
勿用 ``{code}`` 占位。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from mock.core.tenant import get_tenant
from . import data as M

router = APIRouter(prefix="/api/v1", tags=["FRM 配方研发管理"])


# ── 配方 ───────────────────────────────────────────────────

@router.get("/formulas", operation_id="listFormulas",
            summary="配方列表（按类型/行业/基材/环保过滤）")
def list_formulas(
    tenant: Annotated[str, Depends(get_tenant)],
    type: Annotated[str | None, Query(description="标准品/定制")] = None,
    industry: Annotated[str | None, Query(description="汽车内饰/医疗/食品包装/物流快递袋/鞋材箱包")] = None,
    substrate: Annotated[str | None, Query(description="粘接基材")] = None,
    env_std: Annotated[str | None, Query(description="FDA/REACH/SGS/ISO-10993")] = None,
) -> list[dict]:
    rows = M.load(tenant).formulas
    if type:
        rows = [r for r in rows if r["type"] == type]
    if industry:
        rows = [r for r in rows if industry in r["industry"] or r["industry"] in industry]
    if substrate:
        rows = [r for r in rows if substrate in r["substrate"] or r["substrate"] in substrate]
    if env_std:
        rows = [r for r in rows if env_std in (r.get("env_std") or [])]
    return rows


@router.get("/formulas/{formula_no}", operation_id="getFormula",
            summary="配方详情 + 组分配比 + 近期实验")
def get_formula(
    formula_no: Annotated[str, Path(description="配方号，如 FORM-CUS-002")],
    tenant: Annotated[str, Depends(get_tenant)],
) -> dict:
    d = M.load(tenant)
    f = d.formula_by_code.get(formula_no)
    if f is None:
        raise HTTPException(404, f"formula {formula_no} not found")
    return {
        **f,
        "experiments": [e for e in d.experiments if e["formula_no"] == formula_no],
        "samples": [s for s in d.samples if s["formula_no"] == formula_no],
        "failure_records": [fr for fr in d.failure_records if fr["formula_no"] == formula_no],
    }


@router.get("/recommend-formula", operation_id="recommendFormula",
            summary="配方智能推荐（按工况匹配历史配方+初始配比+预估性能）")
def recommend_formula(
    tenant: Annotated[str, Depends(get_tenant)],
    industry: Annotated[str | None, Query(description="客户行业")] = None,
    substrate: Annotated[str | None, Query(description="粘接基材")] = None,
    application_temp: Annotated[str | None, Query(description="施胶温度，如 130℃")] = None,
    open_time_sec: Annotated[int | None, Query(description="开放时间(秒)")] = None,
    peel_strength_N: Annotated[int | None, Query(description="剥离力(N)")] = None,
    env_std: Annotated[str | None, Query(description="环保标准 FDA/REACH/SGS")] = None,
    cost_upper: Annotated[float | None, Query(description="成本上限(元/kg)")] = None,
) -> dict:
    return M.recommend_formula(
        tenant, industry=industry, substrate=substrate,
        application_temp=application_temp, open_time_sec=open_time_sec,
        peel_strength_N=peel_strength_N, env_std=env_std, cost_upper=cost_upper,
    )


@router.get("/formulas/{formula_no}/performance", operation_id="predictPerformance",
            summary="配方性能预测（软化点/粘度/剥离/耐温，减少小试）")
def predict_performance(
    formula_no: Annotated[str, Path(description="配方号，如 FORM-CUS-002")],
    tenant: Annotated[str, Depends(get_tenant)],
) -> dict:
    res = M.predict_performance(tenant, formula_no)
    if not res:
        raise HTTPException(404, f"formula {formula_no} not found")
    return res


# ── 实验 ───────────────────────────────────────────────────

@router.get("/experiments", operation_id="listExperiments",
            summary="实验列表（按配方/测试类型过滤）")
def list_experiments(
    tenant: Annotated[str, Depends(get_tenant)],
    formula_no: Annotated[str | None, Query(description="配方号 FORM-...")] = None,
    test_type: Annotated[str | None, Query(description="流变/拉力剥离/持粘")] = None,
) -> list[dict]:
    rows = M.load(tenant).experiments
    if formula_no:
        rows = [r for r in rows if r["formula_no"] == formula_no]
    if test_type:
        rows = [r for r in rows if r["test_type"] == test_type]
    return rows


@router.get("/experiments/{exp_no}", operation_id="getExperiment",
            summary="实验详情")
def get_experiment(
    exp_no: Annotated[str, Path(description="实验号，如 EXP-RHE-001")],
    tenant: Annotated[str, Depends(get_tenant)],
) -> dict:
    e = M.load(tenant).experiment_by_code.get(exp_no)
    if e is None:
        raise HTTPException(404, f"experiment {exp_no} not found")
    return e


@router.get("/experiments/{exp_no}/analysis", operation_id="analyzeExperimentData",
            summary="实验数据智能分析（异常识别+历史对比+失效记录关联）")
def analyze_experiment_data(
    exp_no: Annotated[str, Path(description="实验号，如 EXP-RHE-002")],
    tenant: Annotated[str, Depends(get_tenant)],
) -> dict:
    res = M.analyze_experiment_data(tenant, exp_no)
    if not res:
        raise HTTPException(404, f"experiment {exp_no} not found")
    return res


@router.get("/formulas/{formula_no}/report", operation_id="generateExperimentReport",
            summary="实验报告自动生成（聚合实验+测试方案+派生结论）")
def generate_experiment_report(
    formula_no: Annotated[str, Path(description="配方号，如 FORM-CUS-002")],
    tenant: Annotated[str, Depends(get_tenant)],
) -> dict:
    res = M.generate_experiment_report(tenant, formula_no)
    if not res:
        raise HTTPException(404, f"formula {formula_no} not found")
    return res


# ── 样品 / 测试方案 ────────────────────────────────────────

@router.get("/samples", operation_id="listTestSamples",
            summary="样品列表（按配方/客户过滤）")
def list_test_samples(
    tenant: Annotated[str, Depends(get_tenant)],
    formula_no: Annotated[str | None, Query(description="配方号 FORM-...")] = None,
    customer_code: Annotated[str | None, Query(description="客户码 CLI-...")] = None,
) -> list[dict]:
    rows = M.load(tenant).samples
    if formula_no:
        rows = [r for r in rows if r["formula_no"] == formula_no]
    if customer_code:
        rows = [r for r in rows if r["customer_code"] == customer_code]
    return rows


@router.get("/test-schemes", operation_id="listTestSchemes",
            summary="测试方案模板列表")
def list_test_schemes(
    tenant: Annotated[str, Depends(get_tenant)],
) -> list[dict]:
    return M.load(tenant).test_schemes


@router.get("/failure-records", operation_id="listFailureRecords",
            summary="失效实验记录列表（研发知识库，按配方过滤）")
def list_failure_records(
    tenant: Annotated[str, Depends(get_tenant)],
    formula_no: Annotated[str | None, Query(description="配方号 FORM-...")] = None,
) -> list[dict]:
    rows = M.load(tenant).failure_records
    if formula_no:
        rows = [r for r in rows if r["formula_no"] == formula_no]
    return rows
