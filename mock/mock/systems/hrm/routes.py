"""HRM 路由——人力资源系统只读查询 + 请假/核算/会议纪要（演示 POST）。

多租户：经 ``Depends(get_tenant)`` 取 ``X-API-Key`` 解析的 tenant，再调
``data.load(tenant)`` 取数。``operationId`` 保持稳定值。
"""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query

from mock.core.tenant import get_tenant
from . import data as H

router = APIRouter(prefix="/api/v1", tags=["HRM 人力资源"])


# ── 员工 / 部门 / 岗位 ─────────────────────────────────────

@router.get("/employees", operation_id="listEmployees", summary="员工列表")
def list_employees(
    tenant: Annotated[str, Depends(get_tenant)],
    department: Annotated[str | None, Query(description="部门编码")] = None,
    status: Annotated[str | None, Query(description="在职/试用/离职")] = None,
    keyword: Annotated[str | None, Query(description="姓名/工号模糊匹配")] = None,
) -> list[dict]:
    rows = H.load(tenant).employees
    if department:
        rows = [r for r in rows if r["department"] == department]
    if status:
        rows = [r for r in rows if r["status"] == status]
    if keyword:
        rows = [r for r in rows if keyword in r["name"] or keyword in r["emp_no"]]
    return rows


@router.get("/employees/{emp_no}", operation_id="getEmployee", summary="员工详情 + 考勤/绩效")
def get_employee(
    emp_no: Annotated[str, Path()],
    tenant: Annotated[str, Depends(get_tenant)],
) -> dict:
    d = H.load(tenant)
    e = d.emp_by_no.get(emp_no)
    if e is None:
        raise HTTPException(404, f"employee {emp_no} not found")
    return {
        **e,
        "attendance": [a for a in d.attendance if a["emp_no"] == emp_no],
        "performances": [p for p in d.performances if p["emp_no"] == emp_no],
    }


@router.get("/departments", operation_id="listDepartments", summary="部门列表")
def list_departments(
    tenant: Annotated[str, Depends(get_tenant)],
) -> list[dict]:
    return H.load(tenant).departments


@router.get("/departments/{code}", operation_id="getDepartment", summary="部门详情 + 员工")
def get_department(
    code: Annotated[str, Path()],
    tenant: Annotated[str, Depends(get_tenant)],
) -> dict:
    d = H.load(tenant)
    dept = d.dept_by_code.get(code)
    if dept is None:
        raise HTTPException(404, f"department {code} not found")
    return {**dept, "employees": [e for e in d.employees if e["department"] == code]}


@router.get("/positions", operation_id="listPositions", summary="岗位列表")
def list_positions(
    tenant: Annotated[str, Depends(get_tenant)],
) -> list[dict]:
    return H.load(tenant).positions


# ── 考勤 / 请假 ────────────────────────────────────────────

@router.get("/attendance", operation_id="listAttendance", summary="考勤记录")
def list_attendance(
    tenant: Annotated[str, Depends(get_tenant)],
    emp_no: Annotated[str | None, Query()] = None,
    date: Annotated[str | None, Query(description="YYYY-MM-DD")] = None,
    status: Annotated[str | None, Query(description="正常/迟到/早退/缺勤/加班")] = None,
) -> list[dict]:
    rows = H.load(tenant).attendance
    if emp_no:
        rows = [r for r in rows if r["emp_no"] == emp_no]
    if date:
        rows = [r for r in rows if r["date"] == date]
    if status:
        rows = [r for r in rows if r["status"] == status]
    return rows


@router.get("/leaves", operation_id="listLeaves", summary="请假记录")
def list_leaves(
    tenant: Annotated[str, Depends(get_tenant)],
    emp_no: Annotated[str | None, Query()] = None,
    status: Annotated[str | None, Query(description="待批/已批/已驳/已销")] = None,
) -> list[dict]:
    rows = H.load(tenant).leaves
    if emp_no:
        rows = [r for r in rows if r["emp_no"] == emp_no]
    if status:
        rows = [r for r in rows if r["status"] == status]
    return rows


@router.post("/leaves", operation_id="applyLeave", summary="请假申请（写入演示）")
def apply_leave(
    tenant: Annotated[str, Depends(get_tenant)],
    payload: Annotated[dict, Body(examples=[{"emp_no": "OP0007", "type": "年假", "start": "2026-07-01",
                                             "end": "2026-07-02", "days": 2, "reason": "家事"}])] = None,
) -> dict:
    d = H.load(tenant)
    p = payload or {}
    emp = d.emp_by_no.get(p.get("emp_no", ""))
    if emp is None:
        raise HTTPException(404, f"employee {p.get('emp_no')} not found")
    return {"leave_id": f"LV{H.D.pad(len(d.leaves) + 1)}", "emp_no": emp["emp_no"],
            "status": "待批", "accepted": True, "tenant": tenant}


# ── 薪酬 / 绩效 / 招聘 ─────────────────────────────────────

@router.get("/payrolls", operation_id="listPayrolls", summary="薪酬列表")
def list_payrolls(
    tenant: Annotated[str, Depends(get_tenant)],
    emp_no: Annotated[str | None, Query()] = None,
    period: Annotated[str | None, Query(description="YYYY-MM")] = None,
    status: Annotated[str | None, Query(description="已核算/已发放/待审批")] = None,
) -> list[dict]:
    rows = H.load(tenant).payrolls
    if emp_no:
        rows = [r for r in rows if r["emp_no"] == emp_no]
    if period:
        rows = [r for r in rows if r["period"] == period]
    if status:
        rows = [r for r in rows if r["status"] == status]
    return rows


@router.post("/payrolls/run", operation_id="runPayroll", summary="生成薪酬（写入演示）")
def run_payroll(
    tenant: Annotated[str, Depends(get_tenant)],
    payload: Annotated[dict, Body(examples=[{"period": "2026-06", "cost_center": "CC-MACH"}])] = None,
) -> dict:
    d = H.load(tenant)
    p = payload or {}
    period = p.get("period", "2026-06")
    matched = [r for r in d.payrolls
               if r["period"] == period
               and (not p.get("cost_center") or r["cost_center"] == p["cost_center"])]
    return {"period": period, "headcount": len(matched),
            "total_net_pay": sum(r["net_pay"] for r in matched),
            "status": "已核算", "tenant": tenant}


@router.get("/performances", operation_id="listPerformances", summary="绩效列表")
def list_performances(
    tenant: Annotated[str, Depends(get_tenant)],
    emp_no: Annotated[str | None, Query()] = None,
    period: Annotated[str | None, Query()] = None,
    grade: Annotated[str | None, Query(description="A/B/C/D")] = None,
) -> list[dict]:
    rows = H.load(tenant).performances
    if emp_no:
        rows = [r for r in rows if r["emp_no"] == emp_no]
    if period:
        rows = [r for r in rows if r["period"] == period]
    if grade:
        rows = [r for r in rows if r["grade"] == grade]
    return rows


@router.get("/recruitments", operation_id="listRecruitments", summary="招聘需求列表")
def list_recruitments(
    tenant: Annotated[str, Depends(get_tenant)],
    department: Annotated[str | None, Query()] = None,
    status: Annotated[str | None, Query(description="招聘中/已关闭")] = None,
) -> list[dict]:
    rows = H.load(tenant).recruitments
    if department:
        rows = [r for r in rows if r["department"] == department]
    if status:
        rows = [r for r in rows if r["status"] == status]
    return rows


# ── 简历 / 会议纪要（AG-HR-01 招聘助手） ────────────────────

@router.get("/resumes", operation_id="listResumesByPosition", summary="简历库（按岗位过滤）")
def list_resumes(
    tenant: Annotated[str, Depends(get_tenant)],
    position: Annotated[str | None, Query(description="岗位编码 P-RND/P-SVC/...")] = None,
    status: Annotated[str | None, Query(description="待筛选/已初面/已复面/已录用/已淘汰")] = None,
) -> list[dict]:
    rows = H.load(tenant).resumes
    if position:
        rows = [r for r in rows if r["position_code"] == position]
    if status:
        rows = [r for r in rows if r["status"] == status]
    return rows


@router.post("/resumes/shortlist", operation_id="shortlistResumes",
             summary="生成岗位候选人短名单（评分排序）")
def shortlist_resumes(
    tenant: Annotated[str, Depends(get_tenant)],
    position: Annotated[str, Query(description="岗位编码")],
    topn: Annotated[int, Query(ge=1, le=20)] = 5,
) -> dict:
    d = H.load(tenant)
    cands = [r for r in d.resumes if r["position_code"] == position]
    cands.sort(key=lambda r: r.get("rating_score", 0), reverse=True)
    short = cands[:topn]
    return {
        "position_code": position,
        "position_name": d.position_by_code.get(position, {}).get("name"),
        "total_candidates": len(cands),
        "shortlist_count": len(short),
        "items": [
            {"resume_id": r["resume_id"], "name": r["name"],
             "education": r["education"], "years_of_experience": r["years_of_experience"],
             "rating_score": r["rating_score"], "status": r["status"],
             "tags": r["tags"], "source": r["source"]}
            for r in short
        ],
        "tenant": tenant,
    }


@router.get("/meetings", operation_id="listMeetings", summary="会议纪要列表")
def list_meetings(
    tenant: Annotated[str, Depends(get_tenant)],
    department: Annotated[str | None, Query()] = None,
    status: Annotated[str | None, Query(description="进行中/已完成")] = None,
) -> list[dict]:
    rows = H.load(tenant).meetings
    if department:
        rows = [r for r in rows if r["department"] == department]
    if status:
        rows = [r for r in rows if r["status"] == status]
    return rows


@router.post("/meetings", operation_id="postMeetingMinutes", summary="提交会议纪要（写入演示）")
def post_meeting_minutes(
    tenant: Annotated[str, Depends(get_tenant)],
    payload: Annotated[dict, Body(examples=[{
        "title": "P-SVC 候选人复评", "department": "PD-HR",
        "meeting_at": "2026-07-02T14:00:00", "owner_emp_no": "AGOF0206",
        "summary": "孙售后终评通过，建议发 offer；李维修需补充技术复试",
    }])] = None,
) -> dict:
    d = H.load(tenant)
    p = payload or {}
    seq = len(d.meetings) + 1
    return {
        "meeting_id": f"AGMT{H.D.pad(20260000 + seq)}",
        "title": p.get("title", "未命名会议"),
        "department": p.get("department"),
        "meeting_at": p.get("meeting_at"),
        "status": "已完成",
        "owner_emp_no": p.get("owner_emp_no"),
        "summary": p.get("summary", ""),
        "created_at": p.get("meeting_at", f"{date.today()}"),
        "tenant": tenant,
        "created": True,
    }
