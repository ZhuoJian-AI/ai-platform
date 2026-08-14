"""HRM 多租户确定性种子数据——人力资源（中国制造企业口径）。

固定种子 + 固定基准日，重启可复现。覆盖员工 / 部门 / 岗位 / 考勤 / 请假 / 薪酬 / 绩效 /
招聘 / 简历 / 会议。每 tenant 一份 ``HrmData``，按 ``load(tenant)`` 取数。

跨系统对齐（同 tenant）：
  - 车间员工 ``emp_no`` 取自 MES 工单作业员；
  - 销售员工 ``name`` 取自 CRM 负责人；
  - 部门 ``cost_center`` 与 ERP 成本中心同码。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from mock.core import data as D
from mock.core.tenant import LazyTenantRegistry, TenantBuilding

BASE_DATE: date = date(2026, 6, 29)


# ───────────────────────── 多租户数据容器 ─────────────────────────


@dataclass
class HrmData:
    departments: list[dict]
    dept_by_code: dict[str, dict]
    positions: list[dict]
    position_by_code: dict[str, dict]
    employees: list[dict]
    emp_by_no: dict[str, dict]
    attendance: list[dict]
    leaves: list[dict]
    payrolls: list[dict]
    performances: list[dict]
    recruitments: list[dict]
    resumes: list[dict] = field(default_factory=list)
    meetings: list[dict] = field(default_factory=list)


# ───────────────────────── 跨系统取数（同 tenant） ─────────────────────────


def _mes_operators(tenant: str) -> list[str]:
    """MES 工单作业员编号 → 车间员工 emp_no（跨系统对齐）。"""
    try:
        from mock.systems.mes.data import load as _load_mes
        d = _load_mes(tenant)
        return sorted({w["operator"] for w in d.work_orders})
    except (Exception, TenantBuilding):  # noqa: BLE001
        return ["OP0007", "OP0012"]


def _crm_owners(tenant: str) -> list[str]:
    """CRM 负责人姓名 → 销售员工 name（跨系统对齐）。"""
    try:
        from mock.systems.crm.data import load as _load_crm
        d = _load_crm(tenant)
        return list({c["owner"] for c in d.customers})
    except (Exception, TenantBuilding):  # noqa: BLE001
        return ["张磊", "林芳"]


# ───────────────────────── minrui（原星图员工） ─────────────────────────


def _build_minrui() -> HrmData:
    R = D.rng(20240910)

    departments = [
        {"code": "PD-PROD", "name": "生产部", "parent_code": None,
         "manager_emp_no": None, "cost_center": "CC-MACH"},
        {"code": "PD-SA", "name": "销售部", "parent_code": None,
         "manager_emp_no": None, "cost_center": "CC-SA"},
        {"code": "PD-FIN", "name": "财务部", "parent_code": None,
         "manager_emp_no": None, "cost_center": "CC-ADM"},
        {"code": "PD-HR", "name": "人力资源部", "parent_code": None,
         "manager_emp_no": None, "cost_center": "CC-ADM"},
        {"code": "PD-ADM", "name": "管理部", "parent_code": None,
         "manager_emp_no": None, "cost_center": "CC-ADM"},
    ]
    dept_by_code = {d["code"]: d for d in departments}

    positions = [
        {"code": "P-OP", "name": "作业员", "grade": "技工", "level": 3},
        {"code": "P-TECH", "name": "工艺技术员", "grade": "技术", "level": 5},
        {"code": "P-SALE", "name": "销售经理", "grade": "管理", "level": 6},
        {"code": "P-ACCT", "name": "会计", "grade": "专业", "level": 5},
        {"code": "P-HR", "name": "HR 专员", "grade": "专业", "level": 5},
        {"code": "P-MGR", "name": "部门经理", "grade": "管理", "level": 8},
    ]
    position_by_code = {p["code"]: p for p in positions}

    employees: list[dict] = []
    emp_by_no: dict[str, dict] = {}

    surnames = ["李", "王", "张", "刘", "陈", "杨", "赵", "黄", "周", "吴", "徐", "孙", "马", "朱", "胡"]
    _op_pool = _mes_operators("minrui")
    for op in _op_pool[:10]:
        dept = "PD-PROD"
        emp = {
            "emp_no": op,
            "name": D.pick(R, surnames) + D.pick(R, ["伟", "强", "磊", "杰", "斌", "涛", "明", "辉"]),
            "gender": D.pick(R, ["男", "男", "女"]),
            "department": dept, "position": "P-OP",
            "status": D.pick(R, ["在职", "在职", "在职", "试用"]),
            "hire_date": f"{BASE_DATE - timedelta(days=D.randint(R, 100, 1500))}",
            "phone": f"1{D.randint(R, 30, 89)}{D.randint(R, 10000000, 99999999)}",
            "email": f"{op.lower()}@minrui.example",
            "cost_center": dept_by_code[dept]["cost_center"],
        }
        employees.append(emp)
        emp_by_no[emp["emp_no"]] = emp

    _sale_id = 100
    for owner in _crm_owners("minrui"):
        emp_no = f"SA{D.pad(_sale_id)}"
        _sale_id += 1
        emp = {
            "emp_no": emp_no,
            "name": owner,
            "gender": D.pick(R, ["男", "女"]),
            "department": "PD-SA", "position": "P-SALE",
            "status": "在职",
            "hire_date": f"{BASE_DATE - timedelta(days=D.randint(R, 200, 1800))}",
            "phone": f"1{D.randint(R, 30, 89)}{D.randint(R, 10000000, 99999999)}",
            "email": f"sale{_sale_id}@minrui.example",
            "cost_center": "CC-SA",
        }
        employees.append(emp)
        emp_by_no[emp["emp_no"]] = emp

    for i in range(6):
        dept = D.pick(R, ["PD-FIN", "PD-HR", "PD-ADM"])
        emp_no = f"OF{D.pad(200 + i)}"
        emp = {
            "emp_no": emp_no,
            "name": D.pick(R, surnames) + D.pick(R, ["敏", "婷", "浩", "洁", "峰", "静"]),
            "gender": D.pick(R, ["男", "女"]),
            "department": dept,
            "position": {"PD-FIN": "P-ACCT", "PD-HR": "P-HR", "PD-ADM": "P-MGR"}[dept],
            "status": D.pick(R, ["在职", "在职", "试用"]),
            "hire_date": f"{BASE_DATE - timedelta(days=D.randint(R, 200, 2000))}",
            "phone": f"1{D.randint(R, 30, 89)}{D.randint(R, 10000000, 99999999)}",
            "email": f"{emp_no.lower()}@minrui.example",
            "cost_center": dept_by_code[dept]["cost_center"],
        }
        employees.append(emp)
        emp_by_no[emp["emp_no"]] = emp

    departments[0]["manager_emp_no"] = employees[0]["emp_no"]
    departments[1]["manager_emp_no"] = next(e["emp_no"] for e in employees if e["department"] == "PD-SA")

    att_status = ["正常", "正常", "正常", "迟到", "早退", "缺勤", "加班"]
    attendance: list[dict] = []
    for d_off in range(-3, 1):
        for emp in D.sample(R, employees, min(8, len(employees))):
            st = D.pick(R, att_status)
            attendance.append({
                "emp_no": emp["emp_no"], "name": emp["name"],
                "date": f"{BASE_DATE + timedelta(days=d_off)}",
                "shift": D.pick(R, ["早班", "中班", "晚班", "常白"]),
                "check_in": f"{BASE_DATE + timedelta(days=d_off)}T{D.pad(D.randint(R, 7, 9), 2)}:{D.pick(R, ['00', '15', '30', '45'])}:00",
                "check_out": f"{BASE_DATE + timedelta(days=d_off)}T{D.pad(D.randint(R, 17, 21), 2)}:{D.pick(R, ['00', '15', '30', '45'])}:00",
                "status": st,
                "overtime_hours": D.randint(R, 0, 3) if st == "加班" else 0,
            })

    leave_types = ["年假", "病假", "事假", "调休", "婚假"]
    leaves: list[dict] = []
    for i in range(8):
        emp = D.pick(R, employees)
        start = BASE_DATE + timedelta(days=D.randint(R, -10, 15))
        days = D.randint(R, 1, 5)
        leaves.append({
            "leave_id": f"LV{D.pad(20260000 + i * 17)}",
            "emp_no": emp["emp_no"], "name": emp["name"], "department": emp["department"],
            "type": D.pick(R, leave_types),
            "start": f"{start}", "end": f"{start + timedelta(days=days - 1)}",
            "days": days, "reason": D.pick(R, ["家事", "就医", "调休补休", "个人事务", "婚假"]),
            "status": D.pick(R, ["待批", "已批", "已驳", "已销"]),
            "approver": D.pick(R, [e["emp_no"] for e in employees if e["position"] == "P-MGR"] or [employees[0]["emp_no"]]),
        })

    payrolls: list[dict] = []
    performances: list[dict] = []
    for emp in employees:
        if emp["status"] == "离职":
            continue
        period = f"{BASE_DATE.year}-{D.pad(D.randint(R, 4, 6))}"
        base = D.randint(R, 6000, 25000)
        ot = D.randint(R, 0, 3000)
        bonus = D.randint(R, 0, 5000)
        ded = D.randint(R, 0, 1500)
        payrolls.append({
            "payroll_id": f"PR{D.pad(D.randint(R, 20260000, 20269999))}",
            "emp_no": emp["emp_no"], "name": emp["name"], "department": emp["department"],
            "cost_center": emp["cost_center"],
            "period": period,
            "base_salary": base, "overtime_pay": ot, "bonus": bonus, "deduction": ded,
            "net_pay": base + ot + bonus - ded,
            "status": D.pick(R, ["已核算", "已发放", "待审批"]),
        })
        if emp["status"] == "在职":
            score = D.randint(R, 60, 99)
            performances.append({
                "perf_id": f"PF{D.pad(D.randint(R, 20260000, 20269999))}",
                "emp_no": emp["emp_no"], "name": emp["name"], "department": emp["department"],
                "period": period, "score": score,
                "grade": "A" if score >= 90 else ("B" if score >= 80 else ("C" if score >= 70 else "D")),
                "kpi": D.pick(R, ["产量达成", "质量合格率", "销售额", "回款率", "工艺改进", "招聘完成率"]),
                "comment": D.pick(R, ["超额完成", "达标", "需提升", "表现优秀", "基本达标"]),
            })

    recruitments: list[dict] = []
    for i in range(5):
        dept = D.pick(R, departments)
        recruitments.append({
            "req_id": f"RC{D.pad(20260000 + i * 13)}",
            "department": dept["code"], "position": D.pick(R, positions)["code"],
            "headcount": D.randint(R, 1, 5),
            "status": D.pick(R, ["招聘中", "招聘中", "已关闭"]),
            "urgency": D.pick(R, ["紧急", "常规", "储备"]),
            "owner": D.pick(R, [e["emp_no"] for e in employees if e["position"] == "P-HR"] or [employees[0]["emp_no"]]),
            "open_date": f"{BASE_DATE - timedelta(days=D.randint(R, 5, 40))}",
        })

    return HrmData(
        departments=departments, dept_by_code=dept_by_code,
        positions=positions, position_by_code=position_by_code,
        employees=employees, emp_by_no=emp_by_no,
        attendance=attendance, leaves=leaves,
        payrolls=payrolls, performances=performances,
        recruitments=recruitments,
    )


# ───────────────────────── starclothing（星图服装） ─────────────────────────


def _build_starclothing() -> HrmData:
    R = D.rng(20250101)

    departments = [
        {"code": "PD-PROD", "name": "生产部", "parent_code": None,
         "manager_emp_no": None, "cost_center": "CC-XT-CUT"},
        {"code": "PD-SA", "name": "销售部", "parent_code": None,
         "manager_emp_no": None, "cost_center": "CC-XT-SA"},
        {"code": "PD-FIN", "name": "财务部", "parent_code": None,
         "manager_emp_no": None, "cost_center": "CC-XT-FIN"},
        {"code": "PD-HR", "name": "人力资源部", "parent_code": None,
         "manager_emp_no": None, "cost_center": "CC-XT-HR"},
        {"code": "PD-ADM", "name": "管理部", "parent_code": None,
         "manager_emp_no": None, "cost_center": "CC-XT-ADM"},
    ]
    dept_by_code = {d["code"]: d for d in departments}

    positions = [
        {"code": "P-OP", "name": "车缝作业员", "grade": "技工", "level": 3},
        {"code": "P-CUT", "name": "裁剪技术员", "grade": "技术", "level": 5},
        {"code": "P-SALE", "name": "销售经理", "grade": "管理", "level": 6},
        {"code": "P-ACCT", "name": "会计", "grade": "专业", "level": 5},
        {"code": "P-HR", "name": "HR 专员", "grade": "专业", "level": 5},
        {"code": "P-MGR", "name": "部门经理", "grade": "管理", "level": 8},
    ]
    position_by_code = {p["code"]: p for p in positions}

    employees: list[dict] = []
    emp_by_no: dict[str, dict] = {}

    surnames = ["李", "王", "张", "刘", "陈", "杨", "赵", "黄", "周", "吴", "徐", "孙", "马", "朱", "胡"]
    _op_pool = _mes_operators("starclothing")
    for op in _op_pool[:10]:
        dept = "PD-PROD"
        emp = {
            "emp_no": op,
            "name": D.pick(R, surnames) + D.pick(R, ["伟", "强", "磊", "杰", "斌", "涛", "明", "辉"]),
            "gender": D.pick(R, ["男", "男", "女"]),
            "department": dept, "position": "P-OP",
            "status": D.pick(R, ["在职", "在职", "在职", "试用"]),
            "hire_date": f"{BASE_DATE - timedelta(days=D.randint(R, 100, 1500))}",
            "phone": f"1{D.randint(R, 30, 89)}{D.randint(R, 10000000, 99999999)}",
            "email": f"{op.lower()}@starclothing.example",
            "cost_center": dept_by_code[dept]["cost_center"],
        }
        employees.append(emp)
        emp_by_no[emp["emp_no"]] = emp

    _sale_id = 100
    for owner in _crm_owners("starclothing"):
        emp_no = f"SA{D.pad(_sale_id)}"
        _sale_id += 1
        emp = {
            "emp_no": emp_no,
            "name": owner,
            "gender": D.pick(R, ["男", "女"]),
            "department": "PD-SA", "position": "P-SALE",
            "status": "在职",
            "hire_date": f"{BASE_DATE - timedelta(days=D.randint(R, 200, 1800))}",
            "phone": f"1{D.randint(R, 30, 89)}{D.randint(R, 10000000, 99999999)}",
            "email": f"sale{_sale_id}@starclothing.example",
            "cost_center": "CC-XT-SA",
        }
        employees.append(emp)
        emp_by_no[emp["emp_no"]] = emp

    for i in range(6):
        dept = D.pick(R, ["PD-FIN", "PD-HR", "PD-ADM"])
        emp_no = f"OF{D.pad(200 + i)}"
        emp = {
            "emp_no": emp_no,
            "name": D.pick(R, surnames) + D.pick(R, ["敏", "婷", "浩", "洁", "峰", "静"]),
            "gender": D.pick(R, ["男", "女"]),
            "department": dept,
            "position": {"PD-FIN": "P-ACCT", "PD-HR": "P-HR", "PD-ADM": "P-MGR"}[dept],
            "status": D.pick(R, ["在职", "在职", "试用"]),
            "hire_date": f"{BASE_DATE - timedelta(days=D.randint(R, 200, 2000))}",
            "phone": f"1{D.randint(R, 30, 89)}{D.randint(R, 10000000, 99999999)}",
            "email": f"{emp_no.lower()}@starclothing.example",
            "cost_center": dept_by_code[dept]["cost_center"],
        }
        employees.append(emp)
        emp_by_no[emp["emp_no"]] = emp

    departments[0]["manager_emp_no"] = employees[0]["emp_no"]
    departments[1]["manager_emp_no"] = next(e["emp_no"] for e in employees if e["department"] == "PD-SA")

    att_status = ["正常", "正常", "正常", "迟到", "早退", "缺勤", "加班"]
    attendance: list[dict] = []
    for d_off in range(-3, 1):
        for emp in D.sample(R, employees, min(8, len(employees))):
            st = D.pick(R, att_status)
            attendance.append({
                "emp_no": emp["emp_no"], "name": emp["name"],
                "date": f"{BASE_DATE + timedelta(days=d_off)}",
                "shift": D.pick(R, ["早班", "中班", "晚班", "常白"]),
                "check_in": f"{BASE_DATE + timedelta(days=d_off)}T{D.pad(D.randint(R, 7, 9), 2)}:{D.pick(R, ['00', '15', '30', '45'])}:00",
                "check_out": f"{BASE_DATE + timedelta(days=d_off)}T{D.pad(D.randint(R, 17, 21), 2)}:{D.pick(R, ['00', '15', '30', '45'])}:00",
                "status": st,
                "overtime_hours": D.randint(R, 0, 3) if st == "加班" else 0,
            })

    leave_types = ["年假", "病假", "事假", "调休", "婚假"]
    leaves: list[dict] = []
    for i in range(8):
        emp = D.pick(R, employees)
        start = BASE_DATE + timedelta(days=D.randint(R, -10, 15))
        days = D.randint(R, 1, 5)
        leaves.append({
            "leave_id": f"SVLV{D.pad(20260000 + i * 17)}",
            "emp_no": emp["emp_no"], "name": emp["name"], "department": emp["department"],
            "type": D.pick(R, leave_types),
            "start": f"{start}", "end": f"{start + timedelta(days=days - 1)}",
            "days": days, "reason": D.pick(R, ["家事", "就医", "调休补休", "个人事务", "婚假"]),
            "status": D.pick(R, ["待批", "已批", "已驳", "已销"]),
            "approver": D.pick(R, [e["emp_no"] for e in employees if e["position"] == "P-MGR"] or [employees[0]["emp_no"]]),
        })

    payrolls: list[dict] = []
    performances: list[dict] = []
    for emp in employees:
        if emp["status"] == "离职":
            continue
        period = f"{BASE_DATE.year}-{D.pad(D.randint(R, 4, 6))}"
        base = D.randint(R, 6000, 25000)
        ot = D.randint(R, 0, 3000)
        bonus = D.randint(R, 0, 5000)
        ded = D.randint(R, 0, 1500)
        payrolls.append({
            "payroll_id": f"SVPR{D.pad(D.randint(R, 20260000, 20269999))}",
            "emp_no": emp["emp_no"], "name": emp["name"], "department": emp["department"],
            "cost_center": emp["cost_center"],
            "period": period,
            "base_salary": base, "overtime_pay": ot, "bonus": bonus, "deduction": ded,
            "net_pay": base + ot + bonus - ded,
            "status": D.pick(R, ["已核算", "已发放", "待审批"]),
        })
        if emp["status"] == "在职":
            score = D.randint(R, 60, 99)
            performances.append({
                "perf_id": f"SVPF{D.pad(D.randint(R, 20260000, 20269999))}",
                "emp_no": emp["emp_no"], "name": emp["name"], "department": emp["department"],
                "period": period, "score": score,
                "grade": "A" if score >= 90 else ("B" if score >= 80 else ("C" if score >= 70 else "D")),
                "kpi": D.pick(R, ["产量达成", "质量合格率", "销售额", "回款率", "工艺改进", "招聘完成率"]),
                "comment": D.pick(R, ["超额完成", "达标", "需提升", "表现优秀", "基本达标"]),
            })

    recruitments: list[dict] = []
    for i in range(5):
        dept = D.pick(R, departments)
        recruitments.append({
            "req_id": f"SVRC{D.pad(20260000 + i * 13)}",
            "department": dept["code"], "position": D.pick(R, positions)["code"],
            "headcount": D.randint(R, 1, 5),
            "status": D.pick(R, ["招聘中", "招聘中", "已关闭"]),
            "urgency": D.pick(R, ["紧急", "常规", "储备"]),
            "owner": D.pick(R, [e["emp_no"] for e in employees if e["position"] == "P-HR"] or [employees[0]["emp_no"]]),
            "open_date": f"{BASE_DATE - timedelta(days=D.randint(R, 5, 40))}",
        })

    return HrmData(
        departments=departments, dept_by_code=dept_by_code,
        positions=positions, position_by_code=position_by_code,
        employees=employees, emp_by_no=emp_by_no,
        attendance=attendance, leaves=leaves,
        payrolls=payrolls, performances=performances,
        recruitments=recruitments,
    )


# ───────────────────────── agileac（敏睿空调） ─────────────────────────


def _build_agileac() -> HrmData:
    """敏睿空调人力资源数据：6 部门 + 10 车间员工 + 销售员工 + 职能员工 + 简历库 + 会议纪要。

    车间员工 emp_no 对齐 MES agileac 工单作业员；销售员工 name 对齐 CRM agileac 负责人；
    cost_center 对齐 ERP agileac 成本中心 (CC-AG-RC/CC/TST/PIP/RND/SA/FIN/HR/IT/ADM)。
    """
    R = D.rng(20260313)

    departments = [
        {"code": "PD-PROD", "name": "生产部", "parent_code": None,
         "manager_emp_no": None, "cost_center": "CC-AG-RC"},
        {"code": "PD-TECH", "name": "工艺技术部", "parent_code": None,
         "manager_emp_no": None, "cost_center": "CC-AG-PIP"},
        {"code": "PD-RND", "name": "研发部", "parent_code": None,
         "manager_emp_no": None, "cost_center": "CC-AG-RND"},
        {"code": "PD-SA", "name": "销售部", "parent_code": None,
         "manager_emp_no": None, "cost_center": "CC-AG-SA"},
        {"code": "PD-FIN", "name": "财务部", "parent_code": None,
         "manager_emp_no": None, "cost_center": "CC-AG-FIN"},
        {"code": "PD-HR", "name": "人力资源部", "parent_code": None,
         "manager_emp_no": None, "cost_center": "CC-AG-HR"},
        {"code": "PD-IT", "name": "信息技术部", "parent_code": None,
         "manager_emp_no": None, "cost_center": "CC-AG-IT"},
        {"code": "PD-ADM", "name": "管理部", "parent_code": None,
         "manager_emp_no": None, "cost_center": "CC-AG-ADM"},
    ]
    dept_by_code = {d["code"]: d for d in departments}

    positions = [
        {"code": "P-OP", "name": "装配作业员", "grade": "技工", "level": 3},
        {"code": "P-TST", "name": "检测技术员", "grade": "技术", "level": 5},
        {"code": "P-PIP", "name": "管焊技术员", "grade": "技术", "level": 5},
        {"code": "P-RND", "name": "研发工程师", "grade": "技术", "level": 7},
        {"code": "P-SALE", "name": "销售经理", "grade": "管理", "level": 6},
        {"code": "P-SVC", "name": "售后工程师", "grade": "技术", "level": 5},
        {"code": "P-ACCT", "name": "会计", "grade": "专业", "level": 5},
        {"code": "P-HR", "name": "HR 专员", "grade": "专业", "level": 5},
        {"code": "P-IT", "name": "IT 工程师", "grade": "专业", "level": 6},
        {"code": "P-MGR", "name": "部门经理", "grade": "管理", "level": 8},
    ]
    position_by_code = {p["code"]: p for p in positions}

    employees: list[dict] = []
    emp_by_no: dict[str, dict] = {}

    surnames = ["李", "王", "张", "刘", "陈", "杨", "赵", "黄", "周", "吴", "徐", "孙", "马", "朱", "胡"]

    # 车间员工（emp_no 对齐 MES agileac 作业员）
    _op_pool = _mes_operators("agileac")
    for op in _op_pool[:12]:
        dept = "PD-PROD"
        emp = {
            "emp_no": op,
            "name": D.pick(R, surnames) + D.pick(R, ["伟", "强", "磊", "杰", "斌", "涛", "明", "辉"]),
            "gender": D.pick(R, ["男", "男", "女"]),
            "department": dept, "position": "P-OP",
            "status": D.pick(R, ["在职", "在职", "在职", "试用"]),
            "hire_date": f"{BASE_DATE - timedelta(days=D.randint(R, 100, 1500))}",
            "phone": f"1{D.randint(R, 30, 89)}{D.randint(R, 10000000, 99999999)}",
            "email": f"{op.lower()}@agileac.example",
            "cost_center": dept_by_code[dept]["cost_center"],
        }
        employees.append(emp)
        emp_by_no[emp["emp_no"]] = emp

    # 销售员工（name 对齐 CRM agileac 负责人）
    _sale_id = 100
    for owner in _crm_owners("agileac"):
        emp_no = f"AGSA{D.pad(_sale_id)}"
        _sale_id += 1
        emp = {
            "emp_no": emp_no,
            "name": owner,
            "gender": D.pick(R, ["男", "女"]),
            "department": "PD-SA", "position": "P-SALE",
            "status": "在职",
            "hire_date": f"{BASE_DATE - timedelta(days=D.randint(R, 200, 1800))}",
            "phone": f"1{D.randint(R, 30, 89)}{D.randint(R, 10000000, 99999999)}",
            "email": f"sale{_sale_id}@agileac.example",
            "cost_center": "CC-AG-SA",
        }
        employees.append(emp)
        emp_by_no[emp["emp_no"]] = emp

    # 职能/技术/管理员工（10 个）
    staff_assigns = [
        ("PD-RND", "P-RND"), ("PD-RND", "P-RND"), ("PD-TECH", "P-PIP"), ("PD-TECH", "P-TST"),
        ("PD-FIN", "P-ACCT"), ("PD-HR", "P-HR"), ("PD-IT", "P-IT"), ("PD-IT", "P-IT"),
        ("PD-ADM", "P-MGR"), ("PD-SA", "P-SVC"),
    ]
    for i, (dept, pos) in enumerate(staff_assigns):
        emp_no = f"AGOF{D.pad(200 + i)}"
        emp = {
            "emp_no": emp_no,
            "name": D.pick(R, surnames) + D.pick(R, ["敏", "婷", "浩", "洁", "峰", "静", "岩", "睿"]),
            "gender": D.pick(R, ["男", "女"]),
            "department": dept,
            "position": pos,
            "status": D.pick(R, ["在职", "在职", "试用"]),
            "hire_date": f"{BASE_DATE - timedelta(days=D.randint(R, 200, 2000))}",
            "phone": f"1{D.randint(R, 30, 89)}{D.randint(R, 10000000, 99999999)}",
            "email": f"{emp_no.lower()}@agileac.example",
            "cost_center": dept_by_code[dept]["cost_center"],
        }
        employees.append(emp)
        emp_by_no[emp["emp_no"]] = emp

    departments[0]["manager_emp_no"] = employees[0]["emp_no"]
    departments[3]["manager_emp_no"] = next(e["emp_no"] for e in employees if e["department"] == "PD-SA")

    # ── 考勤 ──
    att_status = ["正常", "正常", "正常", "迟到", "早退", "缺勤", "加班"]
    attendance: list[dict] = []
    for d_off in range(-3, 1):
        for emp in D.sample(R, employees, min(10, len(employees))):
            st = D.pick(R, att_status)
            attendance.append({
                "emp_no": emp["emp_no"], "name": emp["name"],
                "date": f"{BASE_DATE + timedelta(days=d_off)}",
                "shift": D.pick(R, ["早班", "中班", "晚班", "常白"]),
                "check_in": f"{BASE_DATE + timedelta(days=d_off)}T{D.pad(D.randint(R, 7, 9), 2)}:{D.pick(R, ['00', '15', '30', '45'])}:00",
                "check_out": f"{BASE_DATE + timedelta(days=d_off)}T{D.pad(D.randint(R, 17, 21), 2)}:{D.pick(R, ['00', '15', '30', '45'])}:00",
                "status": st,
                "overtime_hours": D.randint(R, 0, 3) if st == "加班" else 0,
            })

    # ── 请假 ──
    leave_types = ["年假", "病假", "事假", "调休", "婚假"]
    leaves: list[dict] = []
    for i in range(8):
        emp = D.pick(R, employees)
        start = BASE_DATE + timedelta(days=D.randint(R, -10, 15))
        days = D.randint(R, 1, 5)
        leaves.append({
            "leave_id": f"AGLV{D.pad(20260000 + i * 17)}",
            "emp_no": emp["emp_no"], "name": emp["name"], "department": emp["department"],
            "type": D.pick(R, leave_types),
            "start": f"{start}", "end": f"{start + timedelta(days=days - 1)}",
            "days": days, "reason": D.pick(R, ["家事", "就医", "调休补休", "个人事务", "婚假"]),
            "status": D.pick(R, ["待批", "已批", "已驳", "已销"]),
            "approver": D.pick(R, [e["emp_no"] for e in employees if e["position"] == "P-MGR"] or [employees[0]["emp_no"]]),
        })

    # ── 薪酬 / 绩效 ──
    payrolls: list[dict] = []
    performances: list[dict] = []
    for emp in employees:
        if emp["status"] == "离职":
            continue
        period = f"{BASE_DATE.year}-{D.pad(D.randint(R, 4, 6))}"
        # 不同岗位 base 范围不同
        if emp["position"] in ("P-OP",):
            base = D.randint(R, 5000, 9000)
        elif emp["position"] in ("P-TST", "P-PIP", "P-ACCT", "P-HR"):
            base = D.randint(R, 8000, 15000)
        elif emp["position"] in ("P-RND", "P-IT", "P-SALE", "P-SVC"):
            base = D.randint(R, 12000, 22000)
        else:  # P-MGR
            base = D.randint(R, 18000, 30000)
        ot = D.randint(R, 0, 3000)
        bonus = D.randint(R, 0, 8000)
        ded = D.randint(R, 0, 1500)
        payrolls.append({
            "payroll_id": f"AGPR{D.pad(D.randint(R, 20260000, 20269999))}",
            "emp_no": emp["emp_no"], "name": emp["name"], "department": emp["department"],
            "cost_center": emp["cost_center"],
            "period": period,
            "base_salary": base, "overtime_pay": ot, "bonus": bonus, "deduction": ded,
            "net_pay": base + ot + bonus - ded,
            "status": D.pick(R, ["已核算", "已发放", "待审批"]),
        })
        if emp["status"] == "在职":
            score = D.randint(R, 60, 99)
            performances.append({
                "perf_id": f"AGPF{D.pad(D.randint(R, 20260000, 20269999))}",
                "emp_no": emp["emp_no"], "name": emp["name"], "department": emp["department"],
                "period": period, "score": score,
                "grade": "A" if score >= 90 else ("B" if score >= 80 else ("C" if score >= 70 else "D")),
                "kpi": D.pick(R, ["产量达成", "一次合格率", "销售额", "回款率",
                                 "工艺改进", "招聘完成率", "客诉闭环率", "系统稳定率"]),
                "comment": D.pick(R, ["超额完成", "达标", "需提升", "表现优秀", "基本达标"]),
            })

    # ── 招聘需求 ──
    recruitments: list[dict] = []
    recr_specs = [
        ("PD-RND", "P-RND", 2, "紧急", "招聘中"),
        ("PD-TECH", "P-PIP", 1, "常规", "招聘中"),
        ("PD-SA", "P-SVC", 3, "紧急", "招聘中"),  # 售后工程师急招（呼应 AG-SVC-01）
        ("PD-IT", "P-IT", 1, "常规", "招聘中"),
        ("PD-PROD", "P-OP", 5, "常规", "已关闭"),
    ]
    for i, (dept, pos, hc, urg, st) in enumerate(recr_specs):
        recruitments.append({
            "req_id": f"AGRC{D.pad(20260000 + i * 13)}",
            "department": dept, "position": pos,
            "headcount": hc,
            "status": st,
            "urgency": urg,
            "owner": D.pick(R, [e["emp_no"] for e in employees if e["position"] == "P-HR"] or [employees[0]["emp_no"]]),
            "open_date": f"{BASE_DATE - timedelta(days=D.randint(R, 5, 40))}",
        })

    # ── 简历库（AG-HR-01 招聘助手核心数据） ──
    resumes: list[dict] = []
    resume_specs = [
        # (resume_id, position, name, edu, years, age, source, status, tags)
        ("AGRM20260001", "P-RND", "陈瑞达", "硕士/制冷与低温工程", 7, 32, "猎头", "待筛选",
         "变频压缩机/系统匹配/R32"),
        ("AGRM20260002", "P-RND", "林子昂", "硕士/热能工程", 5, 29, "内推", "已初面",
         "VRV 系统/控制算法"),
        ("AGRM20260003", "P-RND", "周思齐", "博士/工程热物理", 9, 35, "主动投递", "已复面",
         "换热器强化/微通道"),
        ("AGRM20260004", "P-PIP", "赵工艺", "本科/机械工程", 8, 33, "猎头", "待筛选",
         "钎焊工艺/铜管"),
        ("AGRM20260005", "P-TST", "黄品保", "本科/测控技术", 6, 30, "内推", "已初面",
         "空调安规测试/EMC"),
        ("AGRM20260006", "P-SVC", "孙售后", "大专/制冷设备维修", 10, 38, "主动投递", "已录用",
         "现场故障诊断/R410A/通讯故障"),
        ("AGRM20260007", "P-SVC", "李维修", "大专/机电一体化", 6, 31, "猎头", "已初面",
         "变频板维修/不制冷/漏水"),
        ("AGRM20260008", "P-SVC", "吴服务", "中技/制冷", 12, 40, "内推", "待筛选",
         "VRV 多联机/化霜逻辑"),
        ("AGRM20260009", "P-IT", "郑数据", "硕士/计算机", 4, 28, "主动投递", "已复面",
         "Python/RAG/LLM 应用"),
        ("AGRM20260010", "P-IT", "王后端", "本科/软件工程", 5, 29, "猎头", "待筛选",
         "FastAPI/微服务/可观测"),
        ("AGRM20260011", "P-SALE", "钱商务", "本科/市场营销", 8, 33, "内推", "已初面",
         "工程项目/家装渠道"),
        ("AGRM20260012", "P-SALE", "冯销售", "本科/制冷与空调", 7, 32, "主动投递", "待筛选",
         "工程机/中央空调/招投标"),
    ]
    for rid, pos, name, edu, years, age, source, status, tags in resume_specs:
        resumes.append({
            "resume_id": rid, "position_code": pos,
            "position_name": position_by_code[pos]["name"],
            "name": name, "gender": D.pick(R, ["男", "女"]),
            "age": age, "education": edu, "years_of_experience": years,
            "source": source, "status": status,
            "tags": tags,
            "applied_at": f"{BASE_DATE - timedelta(days=D.randint(R, 5, 30))}T09:00:00",
            "rating_score": D.randint(R, 60, 95),
            "recruitment_req_id": next(
                (r["req_id"] for r in recruitments if r["position"] == pos), None),
        })

    # ── 会议纪要（AG-HR-01 postMeetingMinutes 写入演示） ──
    meetings: list[dict] = []
    meeting_specs = [
        ("AGMT20260001", "周度招聘评审", "PD-HR", "2026-06-23T14:00:00", "已完成", "AGOF0206",
         "P-RND 陈瑞达复面通过，建议录用；P-SVC 孙售后已入职培训中；P-IT 郑数据待终面"),
        ("AGMT20260002", "售后工程师急招专题", "PD-HR", "2026-06-26T10:00:00", "已完成", "AGOF0206",
         "P-SVC 急需 3 人，孙售后/李维修/吴服务 3 人入选短名单；建议 7/5 前发 offer"),
        ("AGMT20260003", "研发部扩编评审", "PD-RND", "2026-06-27T15:00:00", "进行中", "AGOF0200",
         "P-RND 2 个 HC：陈瑞达/周思齐技术面试通过，待 HR 谈薪"),
    ]
    for mid, title, dept, mtg_at, status, owner, summary in meeting_specs:
        meetings.append({
            "meeting_id": mid, "title": title,
            "department": dept, "meeting_at": mtg_at,
            "status": status, "owner_emp_no": owner,
            "attendees": [e["emp_no"] for e in employees if e["department"] == dept][:5],
            "summary": summary,
            "created_at": mtg_at,
        })

    return HrmData(
        departments=departments, dept_by_code=dept_by_code,
        positions=positions, position_by_code=position_by_code,
        employees=employees, emp_by_no=emp_by_no,
        attendance=attendance, leaves=leaves,
        payrolls=payrolls, performances=performances,
        recruitments=recruitments, resumes=resumes, meetings=meetings,
    )


# ───────────────────────── agilesteel（敏睿钢铁） ─────────────────────────


def _build_agilesteel() -> HrmData:
    """敏睿钢铁人力资源数据：9 业务部门 + IT + 车间/销售/职能员工 + 简历库 + 会议纪要。

    车间员工 emp_no 对齐 MES agilesteel 工单作业员；销售员工 name 对齐 CRM agilesteel 负责人；
    cost_center 对齐 ERP agilesteel 成本中心 (CC-AS-IRON/STEEL/ROLL/SPECIAL/SA/FIN/HR)。
    岗位码 ``P-`` 前缀（如 P-MELT）与 PLM 钢种 ``P-ST-`` 不同码空间，identifiers.md 显式消歧。
    """
    R = D.rng(20260622)

    departments = [
        {"code": "PD-IRON", "name": "炼铁厂", "parent_code": None,
         "manager_emp_no": None, "cost_center": "CC-AS-IRON"},
        {"code": "PD-STEEL", "name": "炼钢厂", "parent_code": None,
         "manager_emp_no": None, "cost_center": "CC-AS-STEEL"},
        {"code": "PD-ROLL", "name": "轧钢厂", "parent_code": None,
         "manager_emp_no": None, "cost_center": "CC-AS-ROLL"},
        {"code": "PD-SPECIAL", "name": "特钢厂", "parent_code": None,
         "manager_emp_no": None, "cost_center": "CC-AS-SPECIAL"},
        {"code": "PD-EQP", "name": "设备管理部", "parent_code": None,
         "manager_emp_no": None, "cost_center": "CC-AS-IRON"},
        {"code": "PD-ENE", "name": "能源环保部", "parent_code": None,
         "manager_emp_no": None, "cost_center": "CC-AS-PUB"},
        {"code": "PD-SAF", "name": "安全环保部", "parent_code": None,
         "manager_emp_no": None, "cost_center": "CC-AS-IRON"},
        {"code": "PD-SA", "name": "销售公司", "parent_code": None,
         "manager_emp_no": None, "cost_center": "CC-AS-SA"},
        {"code": "PD-FIN", "name": "财务部", "parent_code": None,
         "manager_emp_no": None, "cost_center": "CC-AS-FIN"},
        {"code": "PD-HR", "name": "人力资源部", "parent_code": None,
         "manager_emp_no": None, "cost_center": "CC-AS-HR"},
        {"code": "PD-IT", "name": "信息技术部", "parent_code": None,
         "manager_emp_no": None, "cost_center": "CC-AS-HR"},
    ]
    dept_by_code = {d["code"]: d for d in departments}

    positions = [
        {"code": "P-FURNACE", "name": "炉前工", "grade": "技工", "level": 4},
        {"code": "P-MELT", "name": "炼钢工程师", "grade": "技术", "level": 7},
        {"code": "P-ROLL", "name": "轧钢工程师", "grade": "技术", "level": 7},
        {"code": "P-SPECIAL", "name": "特钢工艺工程师", "grade": "技术", "level": 7},
        {"code": "P-EQP", "name": "设备工程师", "grade": "技术", "level": 6},
        {"code": "P-ENE", "name": "能源调度员", "grade": "技术", "level": 6},
        {"code": "P-SAF", "name": "安全员", "grade": "专业", "level": 5},
        {"code": "P-SALE", "name": "销售经理", "grade": "管理", "level": 6},
        {"code": "P-ACCT", "name": "会计", "grade": "专业", "level": 5},
        {"code": "P-HR", "name": "HR 专员", "grade": "专业", "level": 5},
        {"code": "P-IT", "name": "IT 工程师", "grade": "专业", "level": 6},
        {"code": "P-MGR", "name": "部门经理", "grade": "管理", "level": 8},
    ]
    position_by_code = {p["code"]: p for p in positions}

    employees: list[dict] = []
    emp_by_no: dict[str, dict] = {}

    surnames = ["李", "王", "张", "刘", "陈", "杨", "赵", "黄", "周", "吴", "徐", "孙", "马", "朱", "胡"]

    # 车间员工（emp_no 对齐 MES agilesteel 作业员）
    _op_pool = _mes_operators("agilesteel")
    dept_by_line = {"LINE-IRON": "PD-IRON", "LINE-STEEL": "PD-STEEL",
                    "LINE-ROLL": "PD-ROLL", "LINE-SPECIAL": "PD-SPECIAL"}
    for op in _op_pool[:14]:
        dept = D.pick(R, ["PD-IRON", "PD-STEEL", "PD-ROLL", "PD-SPECIAL"])
        pos = D.pick(R, ["P-FURNACE", "P-FURNACE", "P-MELT", "P-ROLL", "P-SPECIAL"])
        emp = {
            "emp_no": op,
            "name": D.pick(R, surnames) + D.pick(R, ["伟", "强", "磊", "杰", "斌", "涛", "明", "辉"]),
            "gender": D.pick(R, ["男", "男", "女"]),
            "department": dept, "position": pos,
            "status": D.pick(R, ["在职", "在职", "在职", "试用"]),
            "hire_date": f"{BASE_DATE - timedelta(days=D.randint(R, 100, 1500))}",
            "phone": f"1{D.randint(R, 30, 89)}{D.randint(R, 10000000, 99999999)}",
            "email": f"{op.lower()}@agilesteel.example",
            "cost_center": dept_by_code[dept]["cost_center"],
        }
        employees.append(emp)
        emp_by_no[emp["emp_no"]] = emp

    # 销售员工（name 对齐 CRM agilesteel 负责人）
    _sale_id = 100
    for owner in _crm_owners("agilesteel"):
        emp_no = f"ASSA{D.pad(_sale_id)}"
        _sale_id += 1
        emp = {
            "emp_no": emp_no,
            "name": owner,
            "gender": D.pick(R, ["男", "女"]),
            "department": "PD-SA", "position": "P-SALE",
            "status": "在职",
            "hire_date": f"{BASE_DATE - timedelta(days=D.randint(R, 200, 1800))}",
            "phone": f"1{D.randint(R, 30, 89)}{D.randint(R, 10000000, 99999999)}",
            "email": f"sale{_sale_id}@agilesteel.example",
            "cost_center": "CC-AS-SA",
        }
        employees.append(emp)
        emp_by_no[emp["emp_no"]] = emp

    # 职能/技术/管理员工
    staff_assigns = [
        ("PD-EQP", "P-EQP"), ("PD-EQP", "P-EQP"), ("PD-ENE", "P-ENE"), ("PD-ENE", "P-ENE"),
        ("PD-SAF", "P-SAF"), ("PD-SAF", "P-SAF"), ("PD-FIN", "P-ACCT"), ("PD-HR", "P-HR"),
        ("PD-IT", "P-IT"), ("PD-IT", "P-IT"), ("PD-STEEL", "P-MELT"), ("PD-ROLL", "P-ROLL"),
    ]
    for i, (dept, pos) in enumerate(staff_assigns):
        emp_no = f"ASOF{D.pad(200 + i)}"
        emp = {
            "emp_no": emp_no,
            "name": D.pick(R, surnames) + D.pick(R, ["敏", "婷", "浩", "洁", "峰", "静", "岩", "睿"]),
            "gender": D.pick(R, ["男", "女"]),
            "department": dept,
            "position": pos,
            "status": D.pick(R, ["在职", "在职", "试用"]),
            "hire_date": f"{BASE_DATE - timedelta(days=D.randint(R, 200, 2000))}",
            "phone": f"1{D.randint(R, 30, 89)}{D.randint(R, 10000000, 99999999)}",
            "email": f"{emp_no.lower()}@agilesteel.example",
            "cost_center": dept_by_code[dept]["cost_center"],
        }
        employees.append(emp)
        emp_by_no[emp["emp_no"]] = emp

    departments[1]["manager_emp_no"] = next(e["emp_no"] for e in employees if e["department"] == "PD-STEEL")
    departments[7]["manager_emp_no"] = next(e["emp_no"] for e in employees if e["department"] == "PD-SA")

    # ── 考勤 ──
    att_status = ["正常", "正常", "正常", "迟到", "早退", "缺勤", "加班"]
    attendance: list[dict] = []
    for d_off in range(-3, 1):
        for emp in D.sample(R, employees, min(12, len(employees))):
            st = D.pick(R, att_status)
            attendance.append({
                "emp_no": emp["emp_no"], "name": emp["name"],
                "date": f"{BASE_DATE + timedelta(days=d_off)}",
                "shift": D.pick(R, ["早班", "中班", "晚班", "常白"]),
                "check_in": f"{BASE_DATE + timedelta(days=d_off)}T{D.pad(D.randint(R, 7, 9), 2)}:{D.pick(R, ['00', '15', '30', '45'])}:00",
                "check_out": f"{BASE_DATE + timedelta(days=d_off)}T{D.pad(D.randint(R, 17, 21), 2)}:{D.pick(R, ['00', '15', '30', '45'])}:00",
                "status": st,
                "overtime_hours": D.randint(R, 0, 3) if st == "加班" else 0,
            })

    # ── 请假 ──
    leave_types = ["年假", "病假", "事假", "调休", "婚假"]
    leaves: list[dict] = []
    for i in range(8):
        emp = D.pick(R, employees)
        start = BASE_DATE + timedelta(days=D.randint(R, -10, 15))
        days = D.randint(R, 1, 5)
        leaves.append({
            "leave_id": f"ASLV{D.pad(20260000 + i * 17)}",
            "emp_no": emp["emp_no"], "name": emp["name"], "department": emp["department"],
            "type": D.pick(R, leave_types),
            "start": f"{start}", "end": f"{start + timedelta(days=days - 1)}",
            "days": days, "reason": D.pick(R, ["家事", "就医", "调休补休", "个人事务", "婚假"]),
            "status": D.pick(R, ["待批", "已批", "已驳", "已销"]),
            "approver": D.pick(R, [e["emp_no"] for e in employees if e["position"] == "P-MGR"] or [employees[0]["emp_no"]]),
        })

    # ── 薪酬 / 绩效 ──
    payrolls: list[dict] = []
    performances: list[dict] = []
    for emp in employees:
        if emp["status"] == "离职":
            continue
        period = f"{BASE_DATE.year}-{D.pad(D.randint(R, 4, 6))}"
        if emp["position"] in ("P-FURNACE",):
            base = D.randint(R, 7000, 12000)
        elif emp["position"] in ("P-EQP", "P-ENE", "P-SAF", "P-ACCT", "P-HR"):
            base = D.randint(R, 9000, 16000)
        elif emp["position"] in ("P-MELT", "P-ROLL", "P-SPECIAL", "P-IT", "P-SALE"):
            base = D.randint(R, 14000, 26000)
        else:
            base = D.randint(R, 20000, 34000)
        ot = D.randint(R, 0, 3000)
        bonus = D.randint(R, 0, 8000)
        ded = D.randint(R, 0, 1500)
        payrolls.append({
            "payroll_id": f"ASPR{D.pad(D.randint(R, 20260000, 20269999))}",
            "emp_no": emp["emp_no"], "name": emp["name"], "department": emp["department"],
            "cost_center": emp["cost_center"],
            "period": period,
            "base_salary": base, "overtime_pay": ot, "bonus": bonus, "deduction": ded,
            "net_pay": base + ot + bonus - ded,
            "status": D.pick(R, ["已核算", "已发放", "待审批"]),
        })
        if emp["status"] == "在职":
            score = D.randint(R, 60, 99)
            performances.append({
                "perf_id": f"ASPF{D.pad(D.randint(R, 20260000, 20269999))}",
                "emp_no": emp["emp_no"], "name": emp["name"], "department": emp["department"],
                "period": period, "score": score,
                "grade": "A" if score >= 90 else ("B" if score >= 80 else ("C" if score >= 70 else "D")),
                "kpi": D.pick(R, ["炉次产量", "一次合格率", "吨钢能耗", "设备可用率",
                                 "销售额", "回款率", "隐患闭环率", "系统稳定率"]),
                "comment": D.pick(R, ["超额完成", "达标", "需提升", "表现优秀", "基本达标"]),
            })

    # ── 招聘需求 ──
    recruitments: list[dict] = []
    recr_specs = [
        ("PD-STEEL", "P-MELT", 2, "紧急", "招聘中"),
        ("PD-ROLL", "P-ROLL", 1, "常规", "招聘中"),
        ("PD-EQP", "P-EQP", 3, "紧急", "招聘中"),  # 设备工程师急招（呼应 EQP-01）
        ("PD-ENE", "P-ENE", 1, "常规", "招聘中"),
        ("PD-SAF", "P-SAF", 2, "常规", "招聘中"),
        ("PD-IT", "P-IT", 1, "常规", "招聘中"),
        ("PD-IRON", "P-FURNACE", 5, "常规", "已关闭"),
    ]
    for i, (dept, pos, hc, urg, st) in enumerate(recr_specs):
        recruitments.append({
            "req_id": f"ASRC{D.pad(20260000 + i * 13)}",
            "department": dept, "position": pos,
            "headcount": hc,
            "status": st,
            "urgency": urg,
            "owner": D.pick(R, [e["emp_no"] for e in employees if e["position"] == "P-HR"] or [employees[0]["emp_no"]]),
            "open_date": f"{BASE_DATE - timedelta(days=D.randint(R, 5, 40))}",
        })

    # ── 简历库（HR-01 招聘助手核心数据） ──
    resumes: list[dict] = []
    resume_specs = [
        # (resume_id, position, name, edu, years, age, source, status, tags)
        ("ASRM20260001", "P-MELT", "陈瑞达", "硕士/冶金工程", 7, 32, "猎头", "待筛选",
         "转炉炼钢/终点碳温控制/钢种优化"),
        ("ASRM20260002", "P-MELT", "林子昂", "硕士/钢铁冶金", 5, 29, "内推", "已初面",
         "精炼工艺/合金微调/夹杂物控制"),
        ("ASRM20260003", "P-MELT", "周思齐", "博士/冶金物理化学", 9, 35, "主动投递", "已复面",
         "炉外精炼/洁净钢/RH 真空脱气"),
        ("ASRM20260004", "P-ROLL", "赵轧钢", "本科/材料成型与控制", 8, 33, "猎头", "待筛选",
         "热轧工艺/板形控制/轧辊管理"),
        ("ASRM20260005", "P-SPECIAL", "黄特钢", "硕士/材料科学与工程", 6, 30, "内推", "已初面",
         "特钢深加工/非调质钢/切削性能"),
        ("ASRM20260006", "P-EQP", "孙设备", "本科/机械工程", 10, 38, "主动投递", "已录用",
         "设备预测性维护/振动诊断/高炉"),
        ("ASRM20260007", "P-EQP", "李维护", "大专/机电一体化", 6, 31, "猎头", "已初面",
         "转炉设备/氧枪/状态监测"),
        ("ASRM20260008", "P-EQP", "吴机械", "本科/机械设计制造", 12, 40, "内推", "待筛选",
         "轧机/液压系统/备件管理"),
        ("ASRM20260009", "P-ENE", "郑能源", "硕士/热能工程", 4, 28, "主动投递", "已复面",
         "能源调度/煤气平衡/碳足迹"),
        ("ASRM20260010", "P-IT", "王数据", "硕士/计算机", 5, 29, "猎头", "待筛选",
         "Python/工业大数据/预测模型"),
        ("ASRM20260011", "P-SALE", "钱商务", "本科/市场营销", 8, 33, "内推", "已初面",
         "工程直供/钢贸渠道/招投标"),
        ("ASRM20260012", "P-SALE", "冯销售", "本科/金属材料", 7, 32, "主动投递", "待筛选",
         "优特钢/汽车用钢/终端开发"),
    ]
    for rid, pos, name, edu, years, age, source, status, tags in resume_specs:
        resumes.append({
            "resume_id": rid, "position_code": pos,
            "position_name": position_by_code[pos]["name"],
            "name": name, "gender": D.pick(R, ["男", "女"]),
            "age": age, "education": edu, "years_of_experience": years,
            "source": source, "status": status,
            "tags": tags,
            "applied_at": f"{BASE_DATE - timedelta(days=D.randint(R, 5, 30))}T09:00:00",
            "rating_score": D.randint(R, 60, 95),
            "recruitment_req_id": next(
                (r["req_id"] for r in recruitments if r["position"] == pos), None),
        })

    # ── 会议纪要 ──
    meetings: list[dict] = []
    meeting_specs = [
        ("ASMT20260001", "周度招聘评审", "PD-HR", "2026-06-23T14:00:00", "已完成", "ASOF0206",
         "P-MELT 陈瑞达复面通过，建议录用；P-EQP 孙设备已入职培训中；P-IT 王数据待终面"),
        ("ASMT20260002", "设备工程师急招专题", "PD-HR", "2026-06-26T10:00:00", "已完成", "ASOF0206",
         "P-EQP 急需 3 人，孙设备/李维护/吴机械 3 人入选短名单；建议 7/5 前发 offer"),
        ("ASMT20260003", "炼钢工程师扩编评审", "PD-STEEL", "2026-06-27T15:00:00", "进行中", "ASOF0200",
         "P-MELT 2 个 HC：陈瑞达/周思齐技术面试通过，待 HR 谈薪"),
    ]
    for mid, title, dept, mtg_at, status, owner, summary in meeting_specs:
        meetings.append({
            "meeting_id": mid, "title": title,
            "department": dept, "meeting_at": mtg_at,
            "status": status, "owner_emp_no": owner,
            "attendees": [e["emp_no"] for e in employees if e["department"] == dept][:5],
            "summary": summary,
            "created_at": mtg_at,
        })

    return HrmData(
        departments=departments, dept_by_code=dept_by_code,
        positions=positions, position_by_code=position_by_code,
        employees=employees, emp_by_no=emp_by_no,
        attendance=attendance, leaves=leaves,
        payrolls=payrolls, performances=performances,
        recruitments=recruitments, resumes=resumes, meetings=meetings,
    )


# ───────────────────────── agilestationery（敏睿文具） ─────────────────────────


def _build_agilestationery() -> HrmData:
    """敏睿文具人力资源口径：9 业务部门 + IT + 销售/职能员工 + 简历库 + 会议纪要。

    销售员工 name 取自 CRM agilestationery 负责人（黄淇/林苒/周琰/陈鹭）；cost_center
    对齐 ERP agilestationery 成本中心 (CC-ZB-SA/EC/MKT/SCM/PRD/SVC/FIN/HR/LEG)。
    岗位码 ``P-`` 前缀（如 P-CHN 渠道经理）与 PIM 产品 ``SKU-ZB-`` 不同码空间，
    identifiers.md 显式消歧。文具贸易无车间员工，故不取 MES 作业员。"""
    R = D.rng(20260720)

    departments = [
        {"code": "PD-SALES", "name": "销售管理部", "parent_code": None,
         "manager_emp_no": None, "cost_center": "CC-ZB-SA"},
        {"code": "PD-EC", "name": "电商渠道部", "parent_code": None,
         "manager_emp_no": None, "cost_center": "CC-ZB-EC"},
        {"code": "PD-MKT", "name": "市场营销部", "parent_code": None,
         "manager_emp_no": None, "cost_center": "CC-ZB-MKT"},
        {"code": "PD-SCM", "name": "供应链与物流部", "parent_code": None,
         "manager_emp_no": None, "cost_center": "CC-ZB-SCM"},
        {"code": "PD-PRD", "name": "产品管理部", "parent_code": None,
         "manager_emp_no": None, "cost_center": "CC-ZB-PRD"},
        {"code": "PD-SVC", "name": "客户服务部", "parent_code": None,
         "manager_emp_no": None, "cost_center": "CC-ZB-SVC"},
        {"code": "PD-FIN", "name": "财务部", "parent_code": None,
         "manager_emp_no": None, "cost_center": "CC-ZB-FIN"},
        {"code": "PD-HR", "name": "人力资源部", "parent_code": None,
         "manager_emp_no": None, "cost_center": "CC-ZB-HR"},
        {"code": "PD-LEG", "name": "法务合规部", "parent_code": None,
         "manager_emp_no": None, "cost_center": "CC-ZB-LEG"},
        {"code": "PD-IT", "name": "行政与IT部", "parent_code": None,
         "manager_emp_no": None, "cost_center": "CC-ZB-IT"},
    ]
    dept_by_code = {d["code"]: d for d in departments}

    positions = [
        {"code": "P-CHN", "name": "渠道经理", "grade": "管理", "level": 7},
        {"code": "P-EC", "name": "电商运营专员", "grade": "专业", "level": 6},
        {"code": "P-MKT", "name": "市场分析专员", "grade": "专业", "level": 6},
        {"code": "P-SCM", "name": "供应链专员", "grade": "专业", "level": 5},
        {"code": "P-CUS", "name": "报关与单证专员", "grade": "专业", "level": 5},
        {"code": "P-PRD", "name": "产品管理专员", "grade": "专业", "level": 6},
        {"code": "P-SVC", "name": "客户服务专员", "grade": "专业", "level": 5},
        {"code": "P-ACCT", "name": "会计", "grade": "专业", "level": 5},
        {"code": "P-HR", "name": "HR 专员", "grade": "专业", "level": 5},
        {"code": "P-LEG", "name": "法务专员", "grade": "专业", "level": 6},
        {"code": "P-IT", "name": "IT 工程师", "grade": "专业", "level": 6},
        {"code": "P-MGR", "name": "部门经理", "grade": "管理", "level": 8},
    ]
    position_by_code = {p["code"]: p for p in positions}

    employees: list[dict] = []
    emp_by_no: dict[str, dict] = {}
    surnames = ["李", "王", "张", "刘", "陈", "杨", "赵", "黄", "周", "吴", "徐", "孙", "马", "朱", "胡"]

    # 销售员工（name 取自 CRM agilestationery 负责人）
    _sale_id = 100
    for owner in _crm_owners("agilestationery"):
        emp_no = f"ASSA{D.pad(_sale_id)}"
        _sale_id += 1
        emp = {
            "emp_no": emp_no, "name": owner, "gender": D.pick(R, ["男", "女"]),
            "department": "PD-SALES", "position": "P-CHN", "status": "在职",
            "hire_date": f"{BASE_DATE - timedelta(days=D.randint(R, 200, 1500))}",
            "phone": f"1{D.randint(R, 30, 89)}{D.randint(R, 10000000, 99999999)}",
            "email": f"sale{_sale_id}@agilestationery.example",
            "cost_center": "CC-ZB-SA",
        }
        employees.append(emp); emp_by_no[emp["emp_no"]] = emp

    # 职能/专业/管理员工
    staff_assigns = [
        ("PD-EC", "P-EC"), ("PD-EC", "P-EC"), ("PD-MKT", "P-MKT"), ("PD-MKT", "P-MKT"),
        ("PD-SCM", "P-SCM"), ("PD-SCM", "P-CUS"), ("PD-PRD", "P-PRD"), ("PD-PRD", "P-PRD"),
        ("PD-SVC", "P-SVC"), ("PD-SVC", "P-SVC"), ("PD-FIN", "P-ACCT"), ("PD-FIN", "P-ACCT"),
        ("PD-HR", "P-HR"), ("PD-LEG", "P-LEG"), ("PD-IT", "P-IT"), ("PD-IT", "P-IT"),
        ("PD-SALES", "P-MGR"), ("PD-EC", "P-MGR"),
    ]
    for i, (dept, pos) in enumerate(staff_assigns):
        emp_no = f"ASOF{D.pad(200 + i)}"
        emp = {
            "emp_no": emp_no,
            "name": D.pick(R, surnames) + D.pick(R, ["敏", "婷", "浩", "洁", "峰", "静", "岩", "睿"]),
            "gender": D.pick(R, ["男", "女"]), "department": dept, "position": pos,
            "status": D.pick(R, ["在职", "在职", "试用"]),
            "hire_date": f"{BASE_DATE - timedelta(days=D.randint(R, 200, 2000))}",
            "phone": f"1{D.randint(R, 30, 89)}{D.randint(R, 10000000, 99999999)}",
            "email": f"{emp_no.lower()}@agilestationery.example",
            "cost_center": dept_by_code[dept]["cost_center"],
        }
        employees.append(emp); emp_by_no[emp["emp_no"]] = emp

    departments[0]["manager_emp_no"] = next(e["emp_no"] for e in employees if e["department"] == "PD-SALES" and e["position"] == "P-MGR")
    departments[1]["manager_emp_no"] = next(e["emp_no"] for e in employees if e["department"] == "PD-EC" and e["position"] == "P-MGR")

    # 考勤
    att_status = ["正常", "正常", "正常", "迟到", "早退", "缺勤", "加班"]
    attendance: list[dict] = []
    for d_off in range(-3, 1):
        for emp in D.sample(R, employees, min(12, len(employees))):
            st = D.pick(R, att_status)
            attendance.append({
                "emp_no": emp["emp_no"], "name": emp["name"],
                "date": f"{BASE_DATE + timedelta(days=d_off)}",
                "shift": "常白",
                "check_in": f"{BASE_DATE + timedelta(days=d_off)}T{D.pad(D.randint(R, 8, 9), 2)}:{D.pick(R, ['00', '15', '30', '45'])}:00",
                "check_out": f"{BASE_DATE + timedelta(days=d_off)}T{D.pad(D.randint(R, 17, 19), 2)}:{D.pick(R, ['00', '15', '30', '45'])}:00",
                "status": st,
                "overtime_hours": D.randint(R, 0, 3) if st == "加班" else 0,
            })

    # 请假
    leave_types = ["年假", "病假", "事假", "调休", "婚假"]
    leaves: list[dict] = []
    for i in range(8):
        emp = D.pick(R, employees)
        start = BASE_DATE + timedelta(days=D.randint(R, -10, 15))
        days = D.randint(R, 1, 5)
        leaves.append({
            "leave_id": f"ASLV{D.pad(20260000 + i * 17)}",
            "emp_no": emp["emp_no"], "name": emp["name"], "department": emp["department"],
            "type": D.pick(R, leave_types),
            "start": f"{start}", "end": f"{start + timedelta(days=days - 1)}",
            "days": days, "reason": D.pick(R, ["家事", "就医", "调休补休", "个人事务", "婚假"]),
            "status": D.pick(R, ["待批", "已批", "已驳", "已销"]),
            "approver": D.pick(R, [e["emp_no"] for e in employees if e["position"] == "P-MGR"] or [employees[0]["emp_no"]]),
        })

    # 薪酬 / 绩效
    payrolls: list[dict] = []
    performances: list[dict] = []
    for emp in employees:
        if emp["status"] == "离职":
            continue
        period = f"{BASE_DATE.year}-{D.pad(D.randint(R, 5, 7))}"
        if emp["position"] in ("P-EC", "P-MKT", "P-PRD", "P-LEG", "P-IT", "P-CHN"):
            base = D.randint(R, 9000, 18000)
        elif emp["position"] in ("P-SCM", "P-CUS", "P-SVC", "P-ACCT", "P-HR"):
            base = D.randint(R, 7000, 13000)
        else:
            base = D.randint(R, 15000, 28000)
        ot = D.randint(R, 0, 2000); bonus = D.randint(R, 0, 6000); ded = D.randint(R, 0, 1200)
        payrolls.append({
            "payroll_id": f"ASPR{D.pad(D.randint(R, 20260000, 20269999))}",
            "emp_no": emp["emp_no"], "name": emp["name"], "department": emp["department"],
            "cost_center": emp["cost_center"], "period": period,
            "base_salary": base, "overtime_pay": ot, "bonus": bonus, "deduction": ded,
            "net_pay": base + ot + bonus - ded,
            "status": D.pick(R, ["已核算", "已发放", "待审批"]),
        })
        if emp["status"] == "在职":
            score = D.randint(R, 60, 99)
            performances.append({
                "perf_id": f"ASPF{D.pad(D.randint(R, 20260000, 20269999))}",
                "emp_no": emp["emp_no"], "name": emp["name"], "department": emp["department"],
                "period": period, "score": score,
                "grade": "A" if score >= 90 else ("B" if score >= 80 else ("C" if score >= 70 else "D")),
                "kpi": D.pick(R, ["渠道回款率", "电商 GMV", "投放 ROI", "库存周转",
                                 "假货识别率", "工单闭环率", "对账差异率", "系统稳定率"]),
                "comment": D.pick(R, ["超额完成", "达标", "需提升", "表现优秀", "基本达标"]),
            })

    # 招聘需求
    recruitments: list[dict] = []
    recr_specs = [
        ("PD-EC", "P-EC", 2, "紧急", "招聘中"),     # 电商运营急招（呼应 ECM-01）
        ("PD-PRD", "P-PRD", 1, "常规", "招聘中"),   # 产品管理（呼应 PRD-01）
        ("PD-SCM", "P-CUS", 1, "紧急", "招聘中"),   # 报关专员急招（呼应 SCM-01）
        ("PD-SVC", "P-SVC", 2, "常规", "招聘中"),
        ("PD-LEG", "P-LEG", 1, "常规", "招聘中"),
        ("PD-IT", "P-IT", 1, "常规", "招聘中"),
        ("PD-SALES", "P-CHN", 1, "常规", "已关闭"),
    ]
    for i, (dept, pos, hc, urg, st) in enumerate(recr_specs):
        recruitments.append({
            "req_id": f"ASRC{D.pad(20260000 + i * 13)}",
            "department": dept, "position": pos, "headcount": hc,
            "status": st, "urgency": urg,
            "owner": D.pick(R, [e["emp_no"] for e in employees if e["position"] == "P-HR"] or [employees[0]["emp_no"]]),
            "open_date": f"{BASE_DATE - timedelta(days=D.randint(R, 5, 40))}",
        })

    # 简历库（HR-01 核心数据，围绕电商运营/产品管理/报关/法务岗位）
    resumes: list[dict] = []
    resume_specs = [
        # (resume_id, position, name, edu, years, age, source, status, tags)
        ("ASRM20260001", "P-EC", "陈运营", "本科/电子商务", 5, 28, "猎头", "待筛选",
         "天猫旗舰运营/投放优化/ROI 分析"),
        ("ASRM20260002", "P-EC", "林电商", "本科/市场营销", 4, 27, "内推", "已初面",
         "京东自营运营/大促策划/转化漏斗"),
        ("ASRM20260003", "P-EC", "周投放", "硕士/数据科学", 6, 30, "主动投递", "已复面",
         "信息流投放/人群标签/预算动态分配"),
        ("ASRM20260004", "P-EC", "吴直播", "大专/新媒体", 3, 25, "主动投递", "待筛选",
         "直播带货/内容种草/文具垂类"),
        ("ASRM20260005", "P-EC", "郑数据", "硕士/统计学", 5, 29, "猎头", "已初面",
         "渠道效能分析/多渠道归因/BI 报表"),
        ("ASRM20260006", "P-EC", "黄选品", "本科/商品学", 4, 26, "内推", "待筛选",
         "选品策略/库存周转/清库"),
        ("ASRM20260007", "P-PRD", "孙产品", "本科/工业设计", 6, 30, "猎头", "待筛选",
         "文具品类规划/生命周期/本地化适配"),
        ("ASRM20260008", "P-CUS", "李报关", "本科/国际经济与贸易", 7, 31, "主动投递", "已初面",
         "进口报关/HS 归类/单证合规"),
        ("ASRM20260009", "P-LEG", "赵法务", "硕士/知识产权法", 5, 30, "内推", "待筛选",
         "渠道维权/商标专利/合同审核"),
        ("ASRM20260010", "P-IT", "王数据", "硕士/计算机", 5, 29, "猎头", "待筛选",
         "Python/AI 应用/运维自动化"),
    ]
    for rid, pos, name, edu, years, age, source, status, tags in resume_specs:
        resumes.append({
            "resume_id": rid, "position_code": pos,
            "position_name": position_by_code[pos]["name"],
            "name": name, "gender": D.pick(R, ["男", "女"]),
            "age": age, "education": edu, "years_of_experience": years,
            "source": source, "status": status, "tags": tags,
            "applied_at": f"{BASE_DATE - timedelta(days=D.randint(R, 5, 30))}T09:00:00",
            "rating_score": D.randint(R, 60, 95),
            "recruitment_req_id": next(
                (r["req_id"] for r in recruitments if r["position"] == pos), None),
        })

    # 会议纪要
    meetings: list[dict] = []
    meeting_specs = [
        ("ASMT20260001", "周度招聘评审", "PD-HR", "2026-07-10T14:00:00", "已完成", "ASOF0213",
         "P-EC 电商运营急招 2 人：陈运营/周投放复面通过，建议录用；P-CUS 报关专员待终面"),
        ("ASMT20260002", "电商运营急招专题", "PD-HR", "2026-07-12T10:00:00", "已完成", "ASOF0213",
         "P-EC 急需 2 人，陈运营/林电商/周投放入选短名单；建议 7/18 前发 offer"),
        ("ASMT20260003", "产品管理扩编评审", "PD-PRD", "2026-07-13T15:00:00", "进行中", "ASOF0206",
         "P-PRD 1 个 HC：孙产品技术面试通过，待 HR 谈薪"),
    ]
    for mid, title, dept, mtg_at, status, owner, summary in meeting_specs:
        meetings.append({
            "meeting_id": mid, "title": title, "department": dept, "meeting_at": mtg_at,
            "status": status, "owner_emp_no": owner,
            "attendees": [e["emp_no"] for e in employees if e["department"] == dept][:5],
            "summary": summary, "created_at": mtg_at,
        })

    return HrmData(
        departments=departments, dept_by_code=dept_by_code,
        positions=positions, position_by_code=position_by_code,
        employees=employees, emp_by_no=emp_by_no,
        attendance=attendance, leaves=leaves,
        payrolls=payrolls, performances=performances,
        recruitments=recruitments, resumes=resumes, meetings=meetings,
    )


def _build_starexploration() -> HrmData:
    """星途勘探人力资源口径：9 业务部门 + 信息中心 + 设计/造价/EPC/安全/保密等岗位 +
    简历库（围绕设计/造价/EPC 岗位）+ 会议纪要（公文会议闭环）。

    销售客户经理 name 取自 CRM starexploration 负责人；cost_center 对齐 ERP
    starexploration 成本中心（CC-SE-DES/FIN/HR/LEG/ADM + 项目 CC-IND/BAT/CIV）。
    岗位码 ``P-``（如 P-DES 设计岗）与 ERP 物料 ``M-`` 不同码空间，按 prefix 区分勿互传。"""
    R = D.rng(20260723)

    departments = [
        {"code": "PD-DES", "name": "设计研究院", "parent_code": None,
         "manager_emp_no": None, "cost_center": "CC-SE-DES"},
        {"code": "PD-COST", "name": "造价技经部", "parent_code": None,
         "manager_emp_no": None, "cost_center": "CC-SE-DES"},
        {"code": "PD-EPC", "name": "EPC 总承包部", "parent_code": None,
         "manager_emp_no": None, "cost_center": "CC-IND-001"},
        {"code": "PD-SAF", "name": "安全生产部", "parent_code": None,
         "manager_emp_no": None, "cost_center": "CC-SE-ADM"},
        {"code": "PD-SEC", "name": "保密办公室", "parent_code": None,
         "manager_emp_no": None, "cost_center": "CC-SE-ADM"},
        {"code": "PD-FIN", "name": "资产财务部", "parent_code": None,
         "manager_emp_no": None, "cost_center": "CC-SE-FIN"},
        {"code": "PD-ADM", "name": "综合管理部", "parent_code": None,
         "manager_emp_no": None, "cost_center": "CC-SE-ADM"},
        {"code": "PD-LEG", "name": "法律合规部", "parent_code": None,
         "manager_emp_no": None, "cost_center": "CC-SE-LEG"},
        {"code": "PD-HR", "name": "人力资源部", "parent_code": None,
         "manager_emp_no": None, "cost_center": "CC-SE-HR"},
        {"code": "PD-IT", "name": "信息中心", "parent_code": None,
         "manager_emp_no": None, "cost_center": "CC-SE-ADM"},
    ]
    dept_by_code = {d["code"]: d for d in departments}

    positions = [
        {"code": "P-DES", "name": "设计师", "grade": "专业", "level": 6},
        {"code": "P-COST", "name": "造价工程师", "grade": "专业", "level": 6},
        {"code": "P-EPC", "name": "项目经理", "grade": "管理", "level": 8},
        {"code": "P-SAF", "name": "安全工程师", "grade": "专业", "level": 6},
        {"code": "P-SEC", "name": "保密专员", "grade": "专业", "level": 6},
        {"code": "P-ACCT", "name": "会计", "grade": "专业", "level": 5},
        {"code": "P-HR", "name": "HR 专员", "grade": "专业", "level": 5},
        {"code": "P-LEG", "name": "法务专员", "grade": "专业", "level": 6},
        {"code": "P-ADM", "name": "行政专员", "grade": "专业", "level": 5},
        {"code": "P-IT", "name": "IT 工程师", "grade": "专业", "level": 6},
        {"code": "P-MGR", "name": "部门经理", "grade": "管理", "level": 8},
    ]
    position_by_code = {p["code"]: p for p in positions}

    employees: list[dict] = []
    emp_by_no: dict[str, dict] = {}
    surnames = ["李", "王", "张", "刘", "陈", "杨", "赵", "黄", "周", "吴", "徐", "孙", "马", "朱", "胡"]

    # 客户经理（name 取自 CRM starexploration 负责人）
    _cm_id = 100
    for owner in _crm_owners("starexploration"):
        emp_no = f"SESA{D.pad(_cm_id)}"
        _cm_id += 1
        emp = {
            "emp_no": emp_no, "name": owner, "gender": D.pick(R, ["男", "女"]),
            "department": "PD-EPC", "position": "P-EPC", "status": "在职",
            "hire_date": f"{BASE_DATE - timedelta(days=D.randint(R, 200, 1500))}",
            "phone": f"1{D.randint(R, 30, 89)}{D.randint(R, 10000000, 99999999)}",
            "email": f"epc{_cm_id}@starexploration.example",
            "cost_center": "CC-IND-001",
        }
        employees.append(emp); emp_by_no[emp["emp_no"]] = emp

    # 设计/造价/职能员工
    staff_assigns = [
        ("PD-DES", "P-DES"), ("PD-DES", "P-DES"), ("PD-DES", "P-DES"),
        ("PD-COST", "P-COST"), ("PD-COST", "P-COST"),
        ("PD-EPC", "P-EPC"), ("PD-SAF", "P-SAF"), ("PD-SAF", "P-SAF"),
        ("PD-SEC", "P-SEC"), ("PD-FIN", "P-ACCT"), ("PD-FIN", "P-ACCT"),
        ("PD-ADM", "P-ADM"), ("PD-ADM", "P-ADM"), ("PD-LEG", "P-LEG"),
        ("PD-HR", "P-HR"), ("PD-IT", "P-IT"), ("PD-IT", "P-IT"),
        ("PD-DES", "P-MGR"), ("PD-EPC", "P-MGR"),
    ]
    for i, (dept, pos) in enumerate(staff_assigns):
        emp_no = f"SEOF{D.pad(200 + i)}"
        emp = {
            "emp_no": emp_no,
            "name": D.pick(R, surnames) + D.pick(R, ["峰", "婷", "浩", "洁", "岩", "静", "睿", "敏"]),
            "gender": D.pick(R, ["男", "女"]), "department": dept, "position": pos,
            "status": D.pick(R, ["在职", "在职", "试用"]),
            "hire_date": f"{BASE_DATE - timedelta(days=D.randint(R, 200, 2000))}",
            "phone": f"1{D.randint(R, 30, 89)}{D.randint(R, 10000000, 99999999)}",
            "email": f"{emp_no.lower()}@starexploration.example",
            "cost_center": dept_by_code[dept]["cost_center"],
        }
        employees.append(emp); emp_by_no[emp["emp_no"]] = emp

    departments[0]["manager_emp_no"] = next(e["emp_no"] for e in employees if e["department"] == "PD-DES" and e["position"] == "P-MGR")
    departments[2]["manager_emp_no"] = next(e["emp_no"] for e in employees if e["department"] == "PD-EPC" and e["position"] == "P-MGR")

    # 考勤
    att_status = ["正常", "正常", "正常", "迟到", "早退", "缺勤", "加班"]
    attendance: list[dict] = []
    for d_off in range(-3, 1):
        for emp in D.sample(R, employees, min(12, len(employees))):
            st = D.pick(R, att_status)
            attendance.append({
                "emp_no": emp["emp_no"], "name": emp["name"],
                "date": f"{BASE_DATE + timedelta(days=d_off)}",
                "shift": "常白",
                "check_in": f"{BASE_DATE + timedelta(days=d_off)}T{D.pad(D.randint(R, 8, 9), 2)}:{D.pick(R, ['00', '15', '30', '45'])}:00",
                "check_out": f"{BASE_DATE + timedelta(days=d_off)}T{D.pad(D.randint(R, 17, 19), 2)}:{D.pick(R, ['00', '15', '30', '45'])}:00",
                "status": st,
                "overtime_hours": D.randint(R, 0, 3) if st == "加班" else 0,
            })

    # 请假
    leave_types = ["年假", "病假", "事假", "调休", "婚假"]
    leaves: list[dict] = []
    for i in range(8):
        emp = D.pick(R, employees)
        start = BASE_DATE + timedelta(days=D.randint(R, -10, 15))
        days = D.randint(R, 1, 5)
        leaves.append({
            "leave_id": f"SELV{D.pad(20260000 + i * 17)}",
            "emp_no": emp["emp_no"], "name": emp["name"], "department": emp["department"],
            "type": D.pick(R, leave_types),
            "start": f"{start}", "end": f"{start + timedelta(days=days - 1)}",
            "days": days, "reason": D.pick(R, ["家事", "就医", "调休补休", "个人事务", "婚假"]),
            "status": D.pick(R, ["待批", "已批", "已驳", "已销"]),
            "approver": D.pick(R, [e["emp_no"] for e in employees if e["position"] == "P-MGR"] or [employees[0]["emp_no"]]),
        })

    # 薪酬 / 绩效
    payrolls: list[dict] = []
    performances: list[dict] = []
    for emp in employees:
        if emp["status"] == "离职":
            continue
        period = f"{BASE_DATE.year}-{D.pad(D.randint(R, 5, 7))}"
        if emp["position"] in ("P-DES", "P-COST", "P-LEG", "P-IT", "P-EPC"):
            base = D.randint(R, 9000, 18000)
        elif emp["position"] in ("P-SAF", "P-SEC", "P-ACCT", "P-HR", "P-ADM"):
            base = D.randint(R, 7000, 13000)
        else:
            base = D.randint(R, 15000, 28000)
        ot = D.randint(R, 0, 2000); bonus = D.randint(R, 0, 6000); ded = D.randint(R, 0, 1200)
        payrolls.append({
            "payroll_id": f"SEPR{D.pad(D.randint(R, 20260000, 20269999))}",
            "emp_no": emp["emp_no"], "name": emp["name"], "department": emp["department"],
            "cost_center": emp["cost_center"], "period": period,
            "base_salary": base, "overtime_pay": ot, "bonus": bonus, "deduction": ded,
            "net_pay": base + ot + bonus - ded,
            "status": D.pick(R, ["已核算", "已发放", "待审批"]),
        })
        if emp["status"] == "在职":
            score = D.randint(R, 60, 99)
            performances.append({
                "perf_id": f"SEPF{D.pad(D.randint(R, 20260000, 20269999))}",
                "emp_no": emp["emp_no"], "name": emp["name"], "department": emp["department"],
                "period": period, "score": score,
                "grade": "A" if score >= 90 else ("B" if score >= 80 else ("C" if score >= 70 else "D")),
                "kpi": D.pick(R, ["设计合规率", "算量准确率", "工期达成率", "成本偏差率",
                                 "隐患闭环率", "保密合规率", "票据核算准确率", "合同审查时效"]),
                "comment": D.pick(R, ["超额完成", "达标", "需提升", "表现优秀", "基本达标"]),
            })

    # 招聘需求
    recruitments: list[dict] = []
    recr_specs = [
        ("PD-DES", "P-DES", 3, "紧急", "招聘中"),    # 设计师急招（呼应 DES-01）
        ("PD-COST", "P-COST", 2, "常规", "招聘中"),   # 造价工程师（呼应 QTO-01）
        ("PD-EPC", "P-EPC", 1, "紧急", "招聘中"),     # 项目经理（呼应 EPC-01）
        ("PD-SAF", "P-SAF", 1, "常规", "招聘中"),
        ("PD-LEG", "P-LEG", 1, "常规", "招聘中"),
        ("PD-IT", "P-IT", 1, "常规", "招聘中"),
        ("PD-DES", "P-MGR", 1, "常规", "已关闭"),
    ]
    for i, (dept, pos, hc, urg, st) in enumerate(recr_specs):
        recruitments.append({
            "req_id": f"ASRC{D.pad(20260000 + i * 13)}",
            "department": dept, "position": pos, "headcount": hc,
            "status": st, "urgency": urg,
            "owner": D.pick(R, [e["emp_no"] for e in employees if e["position"] == "P-HR"] or [employees[0]["emp_no"]]),
            "open_date": f"{BASE_DATE - timedelta(days=D.randint(R, 5, 40))}",
        })

    # 简历库（HR-01 核心数据，围绕设计/造价/EPC 岗位）
    resumes: list[dict] = []
    resume_specs = [
        ("SERM20260001", "P-DES", "陈建筑", "硕士/建筑学", 6, 30, "猎头", "待筛选",
         "工业厂房方案设计/BIM/防火分区"),
        ("SERM20260002", "P-DES", "林结构", "硕士/结构工程", 7, 31, "内推", "已初面",
         "抗震设计/混凝土结构/算量"),
        ("SERM20260003", "P-DES", "周机电", "本科/建筑环境与能源应用", 5, 28, "主动投递", "已复面",
         "机电管线综合/防排烟/洁净空调"),
        ("SERM20260004", "P-DES", "吴市政", "硕士/市政工程", 4, 27, "主动投递", "待筛选",
         "水厂设计/水工结构/工艺"),
        ("SERM20260005", "P-COST", "郑造价", "本科/工程造价", 6, 29, "猎头", "已初面",
         "工程算量/概预算/EPC 成本测算"),
        ("SERM20260006", "P-COST", "黄技经", "本科/技术经济", 5, 28, "内推", "待筛选",
         "造价数据库/变更签证/对账"),
        ("SERM20260007", "P-EPC", "孙总包", "硕士/工程管理", 8, 33, "猎头", "待筛选",
         "EPC 总承包/进度管控/合同履约"),
        ("SERM20260008", "P-SAF", "李安全", "本科/安全工程", 6, 30, "主动投递", "已初面",
         "现场安全/隐患排查/安全教育"),
        ("SERM20260009", "P-LEG", "赵法务", "硕士/工程法", 5, 30, "内推", "待筛选",
         "工程合同审查/合规/纠纷处理"),
        ("SERM20260010", "P-IT", "王数据", "硕士/计算机", 5, 29, "猎头", "待筛选",
         "Python/AI 应用/BIM 二次开发"),
    ]
    for rid, pos, name, edu, years, age, source, status, tags in resume_specs:
        resumes.append({
            "resume_id": rid, "position_code": pos,
            "position_name": position_by_code[pos]["name"],
            "name": name, "gender": D.pick(R, ["男", "女"]),
            "age": age, "education": edu, "years_of_experience": years,
            "source": source, "status": status, "tags": tags,
            "applied_at": f"{BASE_DATE - timedelta(days=D.randint(R, 5, 30))}T09:00:00",
            "rating_score": D.randint(R, 60, 95),
            "recruitment_req_id": next(
                (r["req_id"] for r in recruitments if r["position"] == pos), None),
        })

    # 会议纪要（ADM-01 公文会议闭环核心数据）
    meetings: list[dict] = []
    meeting_specs = [
        ("SEMT20260001", "电池工厂 EPC 设计交底会", "PD-EPC", "2026-07-18T09:30:00", "已完成", "SEOF0218",
         "SCH-BAT-001 设计交底：洁净车间抗震等级三级、防爆区电气隔离、能量密度参数涉密，待保密办脱密后下发"),
        ("SEMT20260002", "周度经营调度会", "PD-ADM", "2026-07-21T14:00:00", "已完成", "SEOF0213",
         "PRJ-IND-001 进度滞后 5 天、PRJ-BAT-001 待整改隐患 1 项；待办：①设计院复核抗震等级 ②安全部闭环 RO-2026-004 ③保密办脱密 DWG-STR-001"),
        ("SEMT20260003", "合同审查专题会", "PD-LEG", "2026-07-22T10:00:00", "进行中", "SEOF0214",
         "CT-SE-002 电池工厂 EPC 合同：付款里程碑风险点 2 处、保密条款需强化、履约节点提醒待设置"),
    ]
    for mid, title, dept, mtg_at, status, owner, summary in meeting_specs:
        meetings.append({
            "meeting_id": mid, "title": title, "department": dept, "meeting_at": mtg_at,
            "status": status, "owner_emp_no": owner,
            "attendees": [e["emp_no"] for e in employees if e["department"] == dept][:5],
            "summary": summary, "created_at": mtg_at,
        })

    return HrmData(
        departments=departments, dept_by_code=dept_by_code,
        positions=positions, position_by_code=position_by_code,
        employees=employees, emp_by_no=emp_by_no,
        attendance=attendance, leaves=leaves,
        payrolls=payrolls, performances=performances,
        recruitments=recruitments, resumes=resumes, meetings=meetings,
    )


# ───────────────────────── 多租户注册表（懒构建） ─────────────────────────


TENANTS = LazyTenantRegistry[HrmData]({
    "minrui": _build_minrui,
    "starclothing": _build_starclothing,
    "agileac": _build_agileac,
    "agilesteel": _build_agilesteel,
    "agilestationery": _build_agilestationery,
    "starexploration": _build_starexploration,
})


def load(tenant: str) -> HrmData:
    """按 tenant 取数据集；首次调用时触发构建并缓存。"""
    return TENANTS.load(tenant)


def all_tenant_ids() -> list[str]:
    return TENANTS.known_tenants()
