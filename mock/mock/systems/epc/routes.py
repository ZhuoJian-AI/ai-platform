"""EPC 路由——工程总承包与项目管理只读查询。

多租户：经 ``Depends(get_tenant)`` 取 tenant，再调 ``data.load(tenant)`` 取数。
``operationId`` 保持稳定。全部 GET（业务端点亦为 GET+query 参数，便于技能只绑 GET
端点）。path 参数一律用真实码（如 ``PRJ-BAT-001``），勿用 ``{code}`` 占位。
``detectSiteHazard`` 为感知类端点：传 sample_desc（现场画面文本描述），返识别结果 +
整改工单，不生成图片/视频。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from mock.core.tenant import get_tenant
from . import data as M

router = APIRouter(prefix="/api/v1", tags=["EPC 工程总承包"])


# ── 工程项目 ───────────────────────────────────────────────

@router.get("/projects", operation_id="listProjects",
            summary="工程项目列表（按状态过滤）")
def list_projects(
    tenant: Annotated[str, Depends(get_tenant)],
    status: Annotated[str | None, Query(description="在建/前期/竣工")] = None,
) -> list[dict]:
    rows = M.load(tenant).projects
    if status:
        rows = [r for r in rows if r["status"] == status]
    return rows


@router.get("/projects/{project_code}", operation_id="getProject",
            summary="项目详情 + 进度工序 + 待整改隐患数")
def get_project(
    project_code: Annotated[str, Path()],
    tenant: Annotated[str, Depends(get_tenant)],
) -> dict:
    d = M.load(tenant)
    prj = d.project_by_code.get(project_code)
    if prj is None:
        raise HTTPException(404, f"project {project_code} not found")
    return {
        **prj,
        "schedule_activities": [a for a in d.schedule_activities
                                if a["project_code"] == project_code],
        "open_hazards": sum(1 for h in d.site_hazards
                            if h["project_code"] == project_code and h["status"] == "待整改"),
    }


# ── 进度工序 ───────────────────────────────────────────────

@router.get("/schedule-activities", operation_id="listScheduleActivities",
            summary="进度工序列表（按项目/关键路径过滤；含延误天）")
def list_schedule_activities(
    tenant: Annotated[str, Depends(get_tenant)],
    project_code: Annotated[str | None, Query(description="项目号 PRJ-...")] = None,
    critical_only: Annotated[bool, Query(description="仅关键路径")] = False,
) -> list[dict]:
    rows = M.load(tenant).schedule_activities
    if project_code:
        rows = [r for r in rows if r["project_code"] == project_code]
    if critical_only:
        rows = [r for r in rows if r["on_critical_path"]]
    return rows


# ── 现场隐患 ───────────────────────────────────────────────

@router.get("/site-hazards", operation_id="listSiteHazards",
            summary="现场隐患清单（按项目/状态过滤）")
def list_site_hazards(
    tenant: Annotated[str, Depends(get_tenant)],
    project_code: Annotated[str | None, Query(description="项目号 PRJ-...")] = None,
    status: Annotated[str | None, Query(description="待整改/已整改")] = None,
) -> list[dict]:
    rows = M.load(tenant).site_hazards
    if project_code:
        rows = [r for r in rows if r["project_code"] == project_code]
    if status:
        rows = [r for r in rows if r["status"] == status]
    return rows


# ── 项目文档 ───────────────────────────────────────────────

@router.get("/project-documents", operation_id="listProjectDocuments",
            summary="项目文档清单（合同/图纸/签证/验收；带涉密标记）")
def list_project_documents(
    tenant: Annotated[str, Depends(get_tenant)],
    project_code: Annotated[str | None, Query(description="项目号 PRJ-...")] = None,
    type: Annotated[str | None, Query(description="合同/图纸/签证/验收")] = None,
) -> list[dict]:
    rows = M.load(tenant).project_documents
    if project_code:
        rows = [r for r in rows if r["project_code"] == project_code]
    if type:
        rows = [r for r in rows if r["type"] == type]
    return rows


# ── 业务端点（GET + query 参数，便于技能绑定） ───────────────

@router.get("/projects/{project_code}/schedule-risk", operation_id="predictScheduleRisk",
            summary="项目进度风险预测（关键路径延误+权重）")
def predict_schedule_risk(
    project_code: Annotated[str, Path(description="项目号，如 PRJ-IND-001")],
    tenant: Annotated[str, Depends(get_tenant)],
) -> dict:
    res = M.predict_schedule_risk(tenant, project_code)
    if not res:
        raise HTTPException(404, f"project {project_code} not found")
    return res


@router.get("/projects/{project_code}/site-hazard-detection", operation_id="detectSiteHazard",
            summary="现场安全隐患识别（感知类，传 sample_desc 返识别结果+整改工单）")
def detect_site_hazard(
    project_code: Annotated[str, Path(description="项目号，如 PRJ-IND-001")],
    tenant: Annotated[str, Depends(get_tenant)],
    sample_desc: Annotated[str, Query(description="现场画面文本描述，如『摄像头 C07 画面：3 名作业人员未戴安全帽通过 2#塔吊下方作业区』")],
) -> dict:
    res = M.detect_site_hazard(tenant, project_code, sample_desc)
    if not res:
        raise HTTPException(404, f"project {project_code} not found")
    return res
