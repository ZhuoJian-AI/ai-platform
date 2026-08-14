"""DES 路由——工程设计管理只读查询。

多租户：经 ``Depends(get_tenant)`` 取 tenant，再调 ``data.load(tenant)`` 取数。
``operationId`` 保持稳定，平台 spec 导入与技能绑定不受影响。全部 GET（业务端点亦为
GET+query 参数，便于技能只绑 GET 端点）。path 参数一律用真实码（如 ``DWG-ARC-001``），
勿用 ``{code}`` 占位。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from mock.core.tenant import get_tenant
from . import data as M

router = APIRouter(prefix="/api/v1", tags=["DES 设计管理"])


# ── 设计方案 ───────────────────────────────────────────────

@router.get("/schemes", operation_id="listSchemes",
            summary="设计方案列表（按域/阶段过滤）")
def list_schemes(
    tenant: Annotated[str, Depends(get_tenant)],
    domain: Annotated[str | None, Query(description="工业工程/能源环保/城乡服务")] = None,
    stage: Annotated[str | None, Query(description="可研/扩初/施工图")] = None,
) -> list[dict]:
    rows = M.load(tenant).schemes
    if domain:
        rows = [r for r in rows if r["domain"] == domain]
    if stage:
        rows = [r for r in rows if r["stage"] == stage]
    return rows


@router.get("/schemes/{scheme_no}", operation_id="getScheme",
            summary="方案详情 + 关联图纸 + 碰撞数")
def get_scheme(
    scheme_no: Annotated[str, Path()],
    tenant: Annotated[str, Depends(get_tenant)],
) -> dict:
    d = M.load(tenant)
    sch = d.scheme_by_code.get(scheme_no)
    if sch is None:
        raise HTTPException(404, f"scheme {scheme_no} not found")
    return {
        **sch,
        "drawings": [dw for dw in d.drawings if dw["scheme_no"] == scheme_no],
        "clash_count": sum(1 for c in d.clashes if c["scheme_no"] == scheme_no),
    }


# ── 图纸 ───────────────────────────────────────────────────

@router.get("/drawings", operation_id="listDrawings",
            summary="图纸列表（按方案/专业过滤）")
def list_drawings(
    tenant: Annotated[str, Depends(get_tenant)],
    scheme_no: Annotated[str | None, Query(description="方案号 SCH-...")] = None,
    discipline: Annotated[str | None, Query(description="建筑/结构/机电/工艺")] = None,
) -> list[dict]:
    rows = M.load(tenant).drawings
    if scheme_no:
        rows = [r for r in rows if r["scheme_no"] == scheme_no]
    if discipline:
        rows = [r for r in rows if r["discipline"] == discipline]
    return rows


@router.get("/drawings/{drawing_no}", operation_id="getDrawing",
            summary="图纸详情 + 合规标记")
def get_drawing(
    drawing_no: Annotated[str, Path()],
    tenant: Annotated[str, Depends(get_tenant)],
) -> dict:
    dwg = M.load(tenant).drawing_by_code.get(drawing_no)
    if dwg is None:
        raise HTTPException(404, f"drawing {drawing_no} not found")
    return dwg


# ── 规范条款 ───────────────────────────────────────────────

@router.get("/specs", operation_id="listSpecs",
            summary="设计规范强条列表（按专业过滤）")
def list_specs(
    tenant: Annotated[str, Depends(get_tenant)],
    discipline: Annotated[str | None, Query(description="建筑/结构/机电/工艺/洁净")] = None,
    mandatory_only: Annotated[bool, Query(description="仅强条")] = True,
) -> list[dict]:
    rows = M.load(tenant).specs
    if discipline:
        rows = [r for r in rows if r["discipline"] == discipline]
    if mandatory_only:
        rows = [r for r in rows if r["is_mandatory"]]
    return rows


# ── 算量项 ─────────────────────────────────────────────────

@router.get("/quantity-items", operation_id="listQuantityItems",
            summary="算量项列表（按方案/专业过滤；带 ERP 物料码）")
def list_quantity_items(
    tenant: Annotated[str, Depends(get_tenant)],
    scheme_no: Annotated[str | None, Query(description="方案号 SCH-...")] = None,
    discipline: Annotated[str | None, Query(description="结构/建筑/机电")] = None,
) -> list[dict]:
    rows = M.load(tenant).quantity_items
    if scheme_no:
        rows = [r for r in rows if r["scheme_no"] == scheme_no]
    if discipline:
        rows = [r for r in rows if r["discipline"] == discipline]
    return rows


# ── 业务端点（GET + query 参数，便于技能绑定） ───────────────

@router.get("/drawings/{drawing_no}/compliance", operation_id="checkDrawingCompliance",
            summary="图纸规范合规校验（扫描强条返违规项+修正建议）")
def check_drawing_compliance(
    drawing_no: Annotated[str, Path(description="图纸号，如 DWG-ARC-001")],
    tenant: Annotated[str, Depends(get_tenant)],
) -> dict:
    res = M.check_drawing_compliance(tenant, drawing_no)
    if not res:
        raise HTTPException(404, f"drawing {drawing_no} not found")
    return res


@router.get("/schemes/{scheme_no}/takeoff", operation_id="computeQuantityTakeoff",
            summary="方案算量与造价测算（联动 ERP 物料码）")
def compute_quantity_takeoff(
    scheme_no: Annotated[str, Path(description="方案号，如 SCH-IND-001")],
    tenant: Annotated[str, Depends(get_tenant)],
) -> dict:
    res = M.compute_quantity_takeoff(tenant, scheme_no)
    if not res:
        raise HTTPException(404, f"scheme {scheme_no} not found")
    return res


@router.get("/schemes/{scheme_no}/clashes", operation_id="detectClashes",
            summary="方案内跨专业碰撞清单")
def detect_clashes(
    scheme_no: Annotated[str, Path(description="方案号，如 SCH-IND-001")],
    tenant: Annotated[str, Depends(get_tenant)],
) -> list[dict]:
    return M.detect_clashes(tenant, scheme_no)
