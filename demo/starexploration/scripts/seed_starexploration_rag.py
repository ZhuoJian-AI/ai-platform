"""为「星途勘探」组织创建并填充 9 个 RAG 集合（8 部门级 + 1 团队级）。

覆盖 9 个 demo 场景中需要 RAG 检索的场景：
  - department 级 8 个：设计规范与方案比选规则库(design) / 工程算量与造价规则库(cost) /
    项目进度与成本管控规则库(epc) / 现场安全监管与巡检规则库(safety) /
    涉密检测与脱密规则库(security) / 财务核算与票据规则库(finance) /
    公文与会议纪要规则库(admin) / 合同审查与合规规则库(legal)
  - team 级 1 个：岗位JD与人岗匹配规则库(hr-recruiting，HR-01 招聘子任务)

embedding=text-embedding-v4，chunk_size=512，chunk_overlap=64。
幂等：集合按 (org, scope, name) 去重；文档按 (collection, source) 去重。
embedding 失败单文档置 failed 不阻断其余；重跑因 source 去重跳过已成功。
注：若前次入库残留 status=failed 的文档，按 source 去重会再次跳过（A4 坑），
    需手动清理 RagDocument 后重跑，或先删除该 collection 再重建。

用法:
    docker cp demo/starexploration/scripts/seed_starexploration_rag.py ai_infra_backend:/app/scripts/
    docker exec ai_infra_backend python scripts/seed_starexploration_rag.py
"""

# ruff: noqa: E501
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
_BACKEND_DIR = _HERE.parent.parent
if not (_BACKEND_DIR / "app" / "database.py").exists():
    _BACKEND_DIR = _HERE.parents[3] / "llm_router" / "backend"
sys.path.insert(0, str(_BACKEND_DIR))

import structlog  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.database import async_session_factory  # noqa: E402
from app.models.department import Department  # noqa: E402
from app.models.organization import Organization  # noqa: E402
from app.models.rag import RagCollection, RagDocument  # noqa: E402
from app.models.team import Team  # noqa: E402
from app.schemas.rag import RagCollectionCreate, RagDocumentCreate  # noqa: E402
from app.services.rag_service import (  # noqa: E402
    create_collection, get_collection, ingest_document, list_collections,
)

logger = structlog.get_logger()

ORG_SLUG = "starexploration"
ORG_NAME_FALLBACK = "星途勘探"


# ───────────────────────── RAG 集合定义 ─────────────────────────

COLLECTIONS: list[dict] = [
    # ── 1. 设计规范与方案比选规则库（dept design） ──
    {
        "name": "设计规范与方案比选规则库",
        "scope_type": "department",
        "dept_slug": "design", "team_slug": None,
        "description": "规范强条合规校验 + 设计方案比选维度，供设计 agent 检索。",
        "chunk_size": 512, "chunk_overlap": 64,
        "docs": [
            {
                "source": "规范强条合规校验规则.md",
                "title": "抗震/防火/地基规范强条与图纸合规校验",
                "content": """# 规范强条合规校验规则

## 核心规范强条（SPEC-GB- 编号）
- SPEC-GB-50011 建筑抗震设计规范 6.1.2：钢筋混凝土房屋抗震等级按设防烈度与房屋高度查表
- SPEC-GB-50011 6.1.3：丙类建筑抗震设防烈度按所在地区采用
- SPEC-GB-50016 建筑设计防火规范 3.3.1：厂房防火分区最大允许建筑面积按类别与层数查表
- SPEC-GB-50016 3.7.4：厂房内任一点至最近安全出口疏散距离限值
- SPEC-GB-50007 建筑地基基础设计规范 3.0.4：地基基础设计等级按建筑规模与地基复杂程度确定
- SPEC-GB-50207 洁净厂房设计规范 4.3.1：洁净区疏散口满足安全疏散要求
- SPEC-GB-50058 爆炸危险环境电力装置设计规范 5.2.2：防爆区电气选型与隔离满足防爆等级

## 图纸合规校验流程
- 输入图纸号 DWG-ARC-/DWG-STR-/DWG-MEP-（建筑/结构/机电）
- 调 checkDrawingCompliance(drawing_no=...) 返 violations 列表（违规项含 spec_code/clause/fix_suggestion）
- 常见违规：防火分区面积超限（SPEC-GB-50016 3.3.1）、抗震等级取值偏低（SPEC-GB-50011 6.1.2）、
  洁净区疏散距离偏长（SPEC-GB-50207 4.3.1）、防爆区电气未隔离（SPEC-GB-50058 5.2.2）
- 校验通过则 passed=true；不通过给修正建议，勿杜撰违规项
""",
            },
            {
                "source": "设计方案比选维度.md",
                "title": "方案比选维度与多专业协同",
                "content": """# 设计方案比选维度

## 方案比选（SCH-IND-/SCH-BAT-/SCH-CIV-）
- 比选维度：占地 footprint_m2、投资 invest_wan、产能 capacity、工期、合规性、可建造性
- 工业厂房（SCH-IND-）：优先合规性与工期；电池工厂（SCH-BAT-）：优先洁净度与防爆合规
- 市政水厂（SCH-CIV-）：优先工艺与水工结构

## 多专业协同与碰撞
- 专业：建筑(DWG-ARC-)/结构(DWG-STR-)/机电(DWG-MEP-)/工艺/洁净/水工
- 调 detectClashes(scheme_no=...) 返同方案内跨专业碰撞 CLS-（结构梁与机电风管、防火墙开洞等）
- 碰撞 severity 高/中，状态待协调/已协调；高 severity 须先协调后出图
- 方案转项目：方案 SCH-BAT-001 与 EPC 项目 PRJ-BAT-001 按 scheme_no 关联，勿直传
""",
            },
        ],
    },
    # ── 2. 工程算量与造价规则库（dept cost） ──
    {
        "name": "工程算量与造价规则库",
        "scope_type": "department",
        "dept_slug": "cost", "team_slug": None,
        "description": "工程算量规则 + 造价测算 + 物料 prefix 转换，供造价 agent 检索。",
        "chunk_size": 512, "chunk_overlap": 64,
        "docs": [
            {
                "source": "工程算量与造价测算规则.md",
                "title": "算量项聚合 + 物料 prefix 转换 + 造价测算",
                "content": """# 工程算量与造价测算规则

## 算量项（QTI-）
- 混凝土 QTI-CON-（C35/C30/C40，uom=m³）、钢筋 QTI-STE-（HRB400/HRB500，uom=t）、做法 QTI-ARC-（uom=m²）
- 算量项挂在方案 SCH- 与图纸 DWG- 下；调 computeQuantityTakeoff(scheme_no='SCH-IND-001')
  返 by_discipline（按专业聚合）+ by_material（按物料聚合，含 material_code）+ total_cost

## 物料 prefix 转换（关键 no-guessing）
- 算量项 material_code 字段值即 ERP 物料码，prefix 转换：QTI-CON-→M-CON-、QTI-STE-→M-STE-
- 调 ERP listMaterials(material_code='M-CON-001') 查物料单价/库存，勿把 QTI- 当 M- 传 ERP
- 例：SCH-IND-001 算量 M-CON-001(C35 混凝土 580元/m³) + M-STE-001(HRB400 钢筋 4200元/t)

## 造价测算
- total_cost = Σ(qty × unit_cost)，按专业分项汇总
- 与 ERP 采购单 POSE-、库存、成本中心 CC-IND-/CC-BAT-/CC-CIV- 联动做成本偏差分析
- 项目成本 PC-SE-.heat_no 承载项目号 PRJ-，勿把 PC-SE- 当 PRJ- 传 EPC
""",
            },
        ],
    },
    # ── 3. 项目进度与成本管控规则库（dept epc） ──
    {
        "name": "项目进度与成本管控规则库",
        "scope_type": "department",
        "dept_slug": "epc", "team_slug": None,
        "description": "关键路径进度风险 + 成本归集与偏差，供 EPC 项目经理 agent 检索。",
        "chunk_size": 512, "chunk_overlap": 64,
        "docs": [
            {
                "source": "项目进度风险与成本管控规则.md",
                "title": "关键路径延误 + 进度风险预测 + 成本归集",
                "content": """# 项目进度风险与成本管控规则

## 工程项目（PRJ-IND-/PRJ-BAT-/PRJ-CIV-）
- 项目挂设计方案 SCH-（按 scheme_no）、合同 CT-SE-（按 client_code）、成本中心 CC-（按 cost_center_code）
- 调 listProjects/getProject(project_code='PRJ-IND-001') 查进度 progress_pct、状态、关键路径工序

## 进度风险预测
- 进度工序 SCD-（on_critical_path=true 为关键路径，含 delay_days 延误天、weight_pct 权重）
- 调 predictScheduleRisk(project_code='PRJ-IND-001') 返 risk_score/risk_level（高/中/低）+ critical_delayed_activities
- 关键路径累计延误即工期风险；risk_score≥50 启动赶工/资源调配重排关键路径
- PRJ-IND-001：基础施工 SCD-001 延误 8 天、主体结构 SCD-003 延误 5 天 → risk_level 高

## 成本归集
- 项目成本 PC-SE-（ERP）heat_no 承载项目号 PRJ-、work_order_no 引用合同号 CT-SE-、cost_center 对齐 CC-
- 采购单 POSE- → 物料 M- → 库存 → 项目成本 PC-SE- → 成本中心 CC-
- 成本偏差 = 实际成本(PC-SE-) − 合同金额(CT-SE-.contract_amount)，超支预警
- 勿把成本中心 CC- 当项目 PRJ- 传 EPC、勿把采购 POSE- 当项目成本 PC-SE- 传 ERP
""",
            },
        ],
    },
    # ── 4. 现场安全监管与巡检规则库（dept safety） ──
    {
        "name": "现场安全监管与巡检规则库",
        "scope_type": "department",
        "dept_slug": "safety", "team_slug": None,
        "description": "现场隐患识别 + 整改闭环 + 风险分级，供安全巡检 agent 检索。",
        "chunk_size": 512, "chunk_overlap": 64,
        "docs": [
            {
                "source": "现场安全隐患识别与整改规则.md",
                "title": "隐患识别（感知类）+ 整改工单闭环 + 风险分级",
                "content": """# 现场安全隐患识别与整改规则

## 现场隐患（HAZ-，感知类）
- 类别：个人防护（未戴安全帽）、临时用电（线缆拖地）、消防（易燃材料无器材）、高空作业（无临边防护）
- 调 listSiteHazards(project_code='PRJ-IND-001') 查隐患清单（含 sample_desc 画面描述、severity、整改工单 RO-）
- 调 detectSiteHazard(project_code=..., sample_desc='摄像头 C07 画面：3 名作业人员未戴安全帽...')
  返 identified_hazards（识别结果 + rectification 整改措施 + rectification_order 工单号）
- 感知类端点：仅返文本识别结果与整改工单，不生成图片/视频

## 整改闭环
- 待整改 HAZ- 须关联整改工单 RO-，整改后状态→已整改，需复查闭环
- 高 severity（未戴安全帽/无临边防护/易燃无器材）须立即停工整改

## 风险分级
- 按项目类型/环境/历史数据预测安全风险等级，差异化管控
- 安全教育：生成定制化培训课件、考核试题、安全交底文件
- 隐患关联项目 PRJ- 与进度工序 SCD-，勿把 HAZ- 当 PRJ- 传 EPC
""",
            },
        ],
    },
    # ── 5. 涉密检测与脱密规则库（dept security） ──
    {
        "name": "涉密检测与脱密规则库",
        "scope_type": "department",
        "dept_slug": "security", "team_slug": None,
        "description": "涉密内容检测 + 文档脱密 + 保密行为预警，供保密办 agent 检索。",
        "chunk_size": 512, "chunk_overlap": 64,
        "docs": [
            {
                "source": "涉密检测与脱密行为预警规则.md",
                "title": "密级判定 + 脱敏方式 + 行为预警",
                "content": """# 涉密检测与脱密行为预警规则

## 涉密文档（SECDOC-，密级 机密/秘密/内部）
- 来源：DES 图纸 DWG-（source_system=DES，如基础计算书/结构图）、EPC 项目文档 PDOC-（source_system=EPC，如合同）
- 涉密标记 SECMARK-：定位具体条文/图样（如能量密度 280Wh/kg、合同金额 9.2 亿元、抗震等级）

## 涉密检测
- 调 scanConfidentiality(source_doc='DWG-STR-001', source_system='DES') 返 matched_docs + confidential_marks
  + highest_classification + needs_desensitization
- 密级判定：机密>秘密>内部；机密/秘密须脱密后外发，内部可直接内部使用外发前仍需复核
- 勿把 SECDOC- 当 DWG- 传 DES、勿把 SECDOC- 当 PDOC- 传 EPC；按来源文档号跳转

## 文档脱密
- 调 desensitizeDocument(source_doc='DWG-ARC-001', source_system='DES') 产出脱敏记录 DESEN-
- 方式：DES 数值脱密（隐藏坐标/尺寸/配筋率精度）、EPC 条款脱密（隐藏金额/里程碑/工艺参数）
- 脱密前密级→脱密后内部；脱敏记录需保密办复核归档后生效

## 保密行为预警
- 调 listBehaviorAnomalies() 返异常行为日志 BHV-（高频下载涉密文件、非工作时间访问、尝试外发）
- 高 risk_level（尝试外发/高频下载）须立即核查；已拦截状态须留证
- 行为日志按 user(emp_no)/doc_no(SECDOC-) 关联，勿把 BHV- 当 SECDOC- 传
""",
            },
        ],
    },
    # ── 6. 财务核算与票据规则库（dept finance） ──
    {
        "name": "财务核算与票据规则库",
        "scope_type": "department",
        "dept_slug": "finance", "team_slug": None,
        "description": "票据验真 + 智能核算 + 对账规则，供财务 agent 检索。",
        "chunk_size": 512, "chunk_overlap": 64,
        "docs": [
            {
                "source": "票据核算与对账规则.md",
                "title": "发票识别验真 + 凭证入账 + 跨系统对账",
                "content": """# 票据核算与对账规则

## 票据识别与验真
- 发票 INV-（CRM 回款发票）、应付 SEAP-（ERP 工程款应付）、凭证 BV-SE-（ERP 财务凭证）
- 验真查重：发票号 INV202607001 唯一性 + 真伪校验，自动入账生成凭证 BV-SE-

## 跨系统对账（关键 no-guessing）
- 回款发票 INV-(CRM) ↔ 凭证 BV-SE-(ERP) 按 invoice_no/voucher_no 关联（INV202607001↔BV-SE-2026-0701）
- 应付 SEAP-.invoice_no 关联回款发票 INV-；勿把 BV-SE- 当 INV- 传 CRM、勿把 INV- 当 BV-SE- 传 ERP
- 对账差异：凭证金额(BV-SE-) vs 回款金额(REC-) vs 应付金额(SEAP-)，差异闭环

## 预算与成本管控
- 成本中心 CC-IND-/CC-BAT-/CC-CIV-（项目）+ CC-SE-DES/FIN/HR/LEG/ADM（部门）
- 项目成本 PC-SE- 按 cost_center 归集；超支预警 = 实际(PC-SE-) − 预算
- 财务风险：异常报销/违规付款/坏账风险，days_overdue>30 逾期预警
""",
            },
        ],
    },
    # ── 7. 公文与会议纪要规则库（dept admin） ──
    {
        "name": "公文与会议纪要规则库",
        "scope_type": "department",
        "dept_slug": "admin", "team_slug": None,
        "description": "公文生成 + 会议纪要闭环 + 待办提取，供行政 agent 检索。",
        "chunk_size": 512, "chunk_overlap": 64,
        "docs": [
            {
                "source": "公文与会议纪要闭环规则.md",
                "title": "公文格式 + 会议纪要生成 + 待办责任人闭环",
                "content": """# 公文与会议纪要闭环规则

## 公文处理
- 公文类型：请示/报告/通知/纪要；自动生成 + 格式校对 + 行文润色
- 收文关键信息识别 → 分流承办（按部门 PD-）

## 会议纪要闭环
- 会议纪要 SEMT-（HRM）：调 listMeetings 查会议（含 title/department/meeting_at/summary/attendees）
- 自动生成纪要：提取待办事项 + 责任人（emp_no SEOF-）+ 截止时间，跟踪任务闭环
- 待办格式：①事项 ②责任人 ③截止 ④状态（待办/进行中/已完成）
- 跨部门待办分发：设计院 PD-DES / 安全部 PD-SAF / 保密办 PD-SEC 等

## 行政知识问答
- 制度与办事指南知识库，解答员工办事咨询
- 会议关联部门 PD- 与员工 emp_no，勿把 SEMT- 当 emp_no 传
""",
            },
        ],
    },
    # ── 8. 合同审查与合规规则库（dept legal） ──
    {
        "name": "合同审查与合规规则库",
        "scope_type": "department",
        "dept_slug": "legal", "team_slug": None,
        "description": "合同智能审查 + 履约风险校验 + 文书生成，供法务 agent 检索。",
        "chunk_size": 512, "chunk_overlap": 64,
        "docs": [
            {
                "source": "合同审查与履约风险规则.md",
                "title": "合同条款审查 + 风险点识别 + 履约节点提醒",
                "content": """# 合同审查与履约风险规则

## 中标合同（CT-SE-，CRM）
- 调 listSalesOrders 查合同（so_no=CT-SE-001/002/003，含 contract_amount/risk_flags/payment_milestones/confidential）
- 合同关联工程客户 CLI- 与项目 PRJ-（client_code）；勿把 CT-SE- 当 PRJ- 传 EPC

## 合同审查要点
- 关键条款提取：金额/付款里程碑/保密条款/变更签证/质保金/违约责任
- 风险点识别：付款里程碑偏紧、保密条款需强化、变更签证条款待细化、质保金返还节点争议
- 修改建议：对照标准模板给出条款修改建议；履约节点提醒（里程碑到期/质保期届满）

## 履约争议/纠纷（DSP-，对应 complaints）
- 调 listComplaints 查履约争议（进度款支付里程碑争议、设计变更签证费用分歧、地质变化工期顺延等）
- DSP-.product_code 承载项目号 PRJ-，按 product_code 关联 EPC 项目；勿把 DSP- 当 PRJ- 传 EPC
- 法律检索：法条与司法案例检索；自动生成法律意见书/律师函基础文书
- 合规风险校验：投标/经营活动合规核查，生成审查意见
""",
            },
        ],
    },
    # ── 9. 岗位JD与人岗匹配规则库（team hr-recruiting，HR-01） ──
    {
        "name": "岗位JD与人岗匹配规则库",
        "scope_type": "team",
        "dept_slug": "hr", "team_slug": "hr-recruiting",
        "description": "岗位 JD + 人岗匹配评分规则，供招聘 agent 检索。",
        "chunk_size": 512, "chunk_overlap": 64,
        "docs": [
            {
                "source": "岗位JD与人岗匹配规则.md",
                "title": "岗位 JD + 简历评分 + 匹配推荐",
                "content": """# 岗位 JD 与人岗匹配规则

## 岗位（P-，HRM）
- P-DES 设计师 / P-COST 造价工程师 / P-EPC 项目经理 / P-SAF 安全工程师 / P-SEC 保密专员 / P-LEG 法务
- 岗位码 P- 与 ERP 物料 M- 不同码空间（P-DES 设计岗 vs M-CON- 混凝土），按 prefix 区分勿互传

## 招聘需求（ASRC-）与简历库（SERM-）
- 调 listRecruitments 查需求（position 关联岗位 P-、headcount、urgency 紧急/常规、status）
- 调 listResumesByPosition(position_code='P-DES') 查简历（rating_score、tags、education、years_of_experience）
- ASRC.position 字段值即岗位码 P-，按 position_code 关联；勿把 ASRC 当 P- 传

## 人岗匹配评分
- 匹配维度：专业（education 对口）、年限（years_of_experience）、技能标签（tags 命中度）、评分（rating_score）
- 短名单：rating_score≥80 且 tags 命中 ≥3 → 入选复面；紧急岗位优先
- 例：P-DES 设计师急招 3 人，SERM20260001 陈建筑(硕士/建筑学/工业厂房方案/BIM) rating_score 高 → 入选
- 输出：短名单 + 匹配理由 + 建议录用/复面/淘汰，勿杜撰评分
""",
            },
        ],
    },
]


# ───────────────────────── 辅助 ─────────────────────────

async def _get_org(db, slug: str) -> Organization | None:
    stmt = select(Organization).where(Organization.deleted_at.is_(None))
    org = (await db.execute(stmt.where(Organization.slug == slug))).scalar_one_or_none()
    if org is None:
        org = (await db.execute(stmt.where(Organization.name == ORG_NAME_FALLBACK))).scalar_one_or_none()
    return org


async def _get_dept_by_slug(db, org_id, slug: str) -> Department | None:
    return (await db.execute(
        select(Department).where(
            Department.organization_id == org_id, Department.slug == slug,
            Department.deleted_at.is_(None),
        )
    )).scalar_one_or_none()


async def _get_team_by_slug(db, dept_id, slug: str) -> Team | None:
    return (await db.execute(
        select(Team).where(
            Team.department_id == dept_id, Team.slug == slug,
            Team.deleted_at.is_(None),
        )
    )).scalar_one_or_none()


async def _resolve_scope_id(db, org_id, spec: dict) -> str | None:
    if spec["scope_type"] == "organization":
        return None
    if spec["scope_type"] == "department":
        dept = await _get_dept_by_slug(db, org_id, spec["dept_slug"])
        if dept is None:
            raise RuntimeError(f"部门 slug='{spec['dept_slug']}' 不存在，请先运行 seed_starexploration_org.py。")
        return str(dept.id)
    if spec["scope_type"] == "team":
        dept = await _get_dept_by_slug(db, org_id, spec["dept_slug"])
        if dept is None:
            raise RuntimeError(f"部门 slug='{spec['dept_slug']}' 不存在。")
        team = await _get_team_by_slug(db, dept.id, spec["team_slug"])
        if team is None:
            raise RuntimeError(f"团队 slug='{spec['team_slug']}（部门 {spec['dept_slug']}）不存在。")
        return str(team.id)
    raise ValueError(f"未知 scope_type: {spec['scope_type']}")


async def main() -> None:
    overall = {"added": 0, "skipped": 0, "failed": 0, "collections": []}
    async with async_session_factory() as db:
        org = await _get_org(db, ORG_SLUG)
        if org is None:
            logger.error("org_not_found", slug=ORG_SLUG)
            sys.exit(1)
        logger.info("org_resolved", id=str(org.id), name=org.name, slug=org.slug)

        for spec in COLLECTIONS:
            scope_id = await _resolve_scope_id(db, org.id, spec)
            scope_label = f"{spec['scope_type']}:{spec['dept_slug'] or 'org'}/{spec['team_slug'] or '-'}"

            colls = await list_collections(db, org.id, scope_type=spec["scope_type"])
            coll = next((c for c in colls if c.name == spec["name"]
                         and (str(c.scope_id) if c.scope_id else None) == (str(scope_id) if scope_id else None)), None)
            if not coll:
                coll = await create_collection(db, org.id, RagCollectionCreate(
                    name=spec["name"], description=spec["description"],
                    embedding_model="text-embedding-v4",
                    chunk_size=spec["chunk_size"], chunk_overlap=spec["chunk_overlap"],
                    scope_type=spec["scope_type"], scope_id=scope_id,
                ))
                await db.commit()
                logger.info("collection_created", id=str(coll.id), name=coll.name, scope=scope_label)
            else:
                coll = await get_collection(db, coll.id)
                logger.info("collection_resolved", id=str(coll.id), name=coll.name,
                            embedding=coll.embedding_model, chunk=f"{coll.chunk_size}/{coll.chunk_overlap}",
                            scope=scope_label)

            existing = {row[0] for row in (await db.execute(
                select(RagDocument.source).where(
                    RagDocument.collection_id == coll.id, RagDocument.deleted_at.is_(None)
                )
            )).all()}

            added = skipped = failed = 0
            failed_sources: list[str] = []
            for d in spec["docs"]:
                if d["source"] in existing:
                    logger.info("skip_exists", source=d["source"], collection=spec["name"])
                    skipped += 1
                    continue
                try:
                    doc = await ingest_document(db, coll, org.id, RagDocumentCreate(
                        source=d["source"], title=d["title"], content=d["content"], folder_path="",
                    ))
                    await db.commit()
                except Exception as exc:  # noqa: BLE001
                    try:
                        await db.commit()
                    except Exception:  # noqa: BLE001
                        await db.rollback()
                    logger.error("ingest_failed", source=d["source"], collection=spec["name"], error=str(exc))
                    failed += 1
                    failed_sources.append(d["source"])
                    continue
                logger.info("ingested", source=doc.source, title=doc.title, doc_id=str(doc.id),
                            collection=spec["name"])
                added += 1

            overall["added"] += added
            overall["skipped"] += skipped
            overall["failed"] += failed
            overall["collections"].append({
                "name": spec["name"], "scope": scope_label,
                "added": added, "skipped": skipped, "failed": failed, "total": len(spec["docs"]),
                "failed_sources": failed_sources,
            })

    print("\n" + "=" * 72)
    print("星途勘探 RAG 集合导入完成（覆盖式幂等，可安全重复执行）")
    print("-" * 72)
    print(f"{'集合':<28}{'scope':<32}{'新增':>6}{'跳过':>6}{'失败':>6}{'合计':>6}")
    for c in overall["collections"]:
        print(f"{c['name']:<28}{c['scope']:<32}{c['added']:>6}{c['skipped']:>6}{c['failed']:>6}{c['total']:>6}")
        for src in c.get("failed_sources", []):
            print(f"    ✗ failed: {src}")
    print("-" * 72)
    print(f"合计：新增 {overall['added']} ｜ 跳过 {overall['skipped']} ｜ 失败 {overall['failed']} 个文档")
    if overall["failed"]:
        print(f"⚠️ {overall['failed']} 个文档入库失败（多为 embedding 不可用）：请检查组织级 embedding "
              "供应商配置后重跑（重跑因 source 去重会跳过已成功、重试失败的）")
        print("  注：若前次残留 status=failed 的文档（A4 坑），按 source 去重会再次跳过，"
              "需手动清理 RagDocument 后重跑。")
    else:
        print("✓ 无失败：embedding 通道已生效，所有 chunk 均已嵌入向量")
    print("位置：管理端「星途勘探」组织 → RAG 知识库 → 各集合（按 scope 分级可见）")
    print("=" * 72)


if __name__ == "__main__":
    asyncio.run(main())
