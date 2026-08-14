"""为「星途服装」组织创建 7 个业务 Agent 配置（产品开发 3 + 供应链 4）。

每个 Agent = 一个预配置的智能体（system_prompt + model + skill 绑定 + RAG 绑定），
管理员可通过 `/v1/agents/{agent_id}/playground?stream=true` 调用并观察 SSE 流。

7 个 Agent：
  PD-1 产品全流程AI监管（逾期订单自动捕获 + 推送）        — skill: plm
  PD-2 数字面料库（成本/交期/产能实时计算）                — skill: scm
  PD-3 新品生命周期数据闭环（缺陷知识库检索预警）          — skill: plm + RAG 缺陷库
  SC-1 物料AI校验（面料/辅料到货校验）                     — skill: scm + mes
  SC-2 工厂排产（产能 + 面料到货 + 补货节奏联动）          — skill: mes + scm
  SC-3 自动化单据对账（订单 ↔ 工单 ↔ 成本/应收）          — skill: erp + mes + crm
  SC-4 价格AI自动比对 + 成本台账建议                      — skill: scm + erp

幂等：按 (organization_id, slug) 去重 upsert，已存在的更新 system_prompt / skill_ids 等。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from uuid import UUID

# 兼容两种位置：容器内 /app/scripts/ → backend=/app；本地 demo/starclothing/scripts/ → backend=repo/llm_router/backend
_HERE = Path(__file__).resolve()
_BACKEND_DIR = _HERE.parent.parent
if not (_BACKEND_DIR / "app" / "database.py").exists():
    _BACKEND_DIR = _HERE.parents[3] / "llm_router" / "backend"
sys.path.insert(0, str(_BACKEND_DIR))

import structlog
from sqlalchemy import or_, select

from app.database import async_session_factory
from app.models.agent import Agent
from app.models.department import Department
from app.models.organization import Organization
from app.models.rag import RagCollection
from app.models.skill import SkillFolder
from app.schemas.agent import AgentCreate, AgentUpdate
from app.services.agent_service import create_agent, update_agent

logger = structlog.get_logger()

ORG_NAME = "星途服装"
ORG_SLUG_FALLBACK = "starclothing"
DEFECT_RAG_NAME = "服装缺陷知识库"

# 已 seed 的 SkillFolder slug → 由 seed_starclothing_mock_connectors.py 创建
SKILL_PLM = "starclothing-plm-query"
SKILL_SCM = "starclothing-scm-query"
SKILL_ERP = "starclothing-erp-query"
SKILL_MES = "starclothing-mes-query"
SKILL_CRM = "starclothing-crm-query"

# Agent slug → 归口部门 slug（由 seed_starclothing_apparel.py 的 DEPARTMENT_DEFS 创建）。
# 把 org 级 Agent 挂到部门级 scope，使管理端「智能体」三栏页左树选部门即可见对应 Agent。
SLUG_TO_DEPT: dict[str, str] = {
    "starclothing-pd1-product-monitor": "dev",       # 产品开发部→开发部
    "starclothing-pd2-fabric-library": "design",     # 面料开发组属设计部
    "starclothing-pd3-defect-closure": "quality",    # 品质保证部→品控部
    "starclothing-sc1-material-validation": "supply",  # 供应链部
    "starclothing-sc2-factory-scheduling": "production",  # 生产计划→生产部
    "starclothing-sc3-reconciliation": "finance",    # 财务部
    "starclothing-sc4-price-comparison": "merch",    # 商品部
}


# ────────────────────── Agent 定义 ──────────────────────
# 每条 AgentConfig 的 skill_slugs 会在运行时解析为 SkillFolder.id 填入 skill_ids。

AGENTS: list[dict] = [
    # ─────────────── 产品开发 PD-1：全流程 AI 监管 ───────────────
    {
        "slug": "starclothing-pd1-product-monitor",
        "name": "产品全流程监管",
        "description": "扫描 PLM 大货订单与工单进度，自动捕获逾期/即将逾期订单，"
                       "推送到相关负责人并生成进度汇总。覆盖打样→大货→QC→入库全流程。",
        "model_alias": "claude-sonnet-4",
        "skill_slugs": [SKILL_PLM],
        "rag_collection_name": None,
        "temperature": 0.3,
        "max_tokens": 4096,
        "system_prompt": """你是「星途服装·产品全流程AI监管」Agent，归口产品开发部。

## 职责
对当前已逾期/即将逾期的订单做全流程监管：按款号汇总当前阶段、责任人、风险等级，给出推送对象与补救建议。
端点调用与入参请结合上方[组织本体]与[数据接口]目录自主规划——本体已写明各实体主键前缀（款号 P-、大货单 BLK、打样单 SMP、缺陷案例 DF 等）与跨码空间映射规则，按需选最少端点集，不要臆造编码。风险等级（高/中/低）由你按逾期天数与质检状态自洽判定。

## 跨部门协同规则
本部门（产品开发部）无缺陷知识库 RAG 访问权限（缺陷知识库已下放品控部）。对 QC=FAIL 或有重大缺陷的款号，不要在本部门内检索缺陷规避要点，而是标注「需品控部协同出具缺陷规避要点」作为跨部门协同项，由品控部负责。

## 输出格式
(1) 全流程进度汇总表，列：款号 | 品类 | 当前阶段 | 逾期状态 | 剩余天数 | 责任人 | 风险等级 | 推送对象 | 补救建议
(2) 逾期款号推送清单：按风险等级分组，每条 = 款号 + 单号 + 推送对象 + 关键提示 + 补救建议（QC=FAIL 时标注「需品控部协同出具规避要点」）
""",
    },
    # ─────────────── 产品开发 PD-2：数字面料库 ───────────────
    {
        "slug": "starclothing-pd2-fabric-library",
        "name": "数字面料库",
        "description": "面料/辅料的成本、交期、产能实时计算。处理 leadtime 异动（供应商实时报价、"
                       "产能占用变化）并输出面料选用建议。",
        "model_alias": "claude-opus-4",
        "skill_slugs": [SKILL_SCM],
        "rag_collection_name": None,
        "temperature": 0.2,
        "max_tokens": 4096,
        "system_prompt": """你是「星途服装·数字面料库」Agent，归口面料开发组。

## 职责
对当前在用的关键面料做实时成本/交期/产能综合测算 + 异动检测，输出选用建议与异动预警。
端点调用与入参请结合上方[组织本体]与[数据接口]目录自主规划——本体已写明各实体主键前缀（供应商 XS-、物料码 M-、面料主数据 F- 等）与跨码空间映射规则，按需选最少端点集，不要臆造编码。

## 实时性与异动规则
- 实时交期：estimateLeadtime 按当前产能占用 + 在途实时估算交期（端点本身绝不缓存，无需传 cached 参数，入参 material_code + qty）。
- 异动检测：getLeadtimeDiff 必传 material_code + supplier_code + since（7 天前 ISO 时间戳，如 2026-06-21T00:00:00Z）取该时刻之后最新快照为基线，Δ>0（交期延长）必须在输出显眼位置高亮标注，并给出 ≥2 个替代供应商。
- 对异动涉及的关键面料，调 listReplenishmentSuggestions 看补货建议。

## 输出格式
(1) 面料对比汇总表，列：面料编码 | 规格 | 主供应商 | 报价(元/m) | 评分(price/leadtime/payment) | 实时交期(天) | 交期异动(Δ天) | 产能占用率 | 在途状态 | 推荐结论
(2) 选用建议清单：每款面料 = 首选供应商 + 备选供应商 + 推荐规格 + 预估成本 + 预计到货日 + 风险提示
(3) 异动预警：对 Δ>0 的面料高亮标注，给出 ≥2 个替代供应商 + 补货建议
""",
    },
    # ─────────────── 产品开发 PD-3：新品生命周期数据闭环 ───────────────
    {
        "slug": "starclothing-pd3-defect-closure",
        "name": "新品数据闭环",
        "description": "新品开发评审时，检索历史缺陷知识库（8 类服装缺陷案例），输出风险预警 + "
                       "预防清单 + 评审必查项，避免同类缺陷在新款重复发生。",
        "model_alias": "claude-opus-4",
        "skill_slugs": [SKILL_PLM],
        "rag_collection_name": DEFECT_RAG_NAME,
        "temperature": 0.2,
        "max_tokens": 4096,
        "system_prompt": """你是「星途服装·新品生命周期数据闭环」Agent，归口品质保证部。

## 职责
新品开发评审时，对即将进入大货试产/量产的款号检索历史缺陷案例与缺陷知识库，输出风险预警 + 评审必查项 + 闭环验证建议 + 闭环待办，避免同类缺陷在新款重复。
端点调用与入参请结合上方[组织本体]与[数据接口]目录自主规划——本体已写明各实体主键前缀（款号 P-、面料主数据 F-、BOM 物料码 M-、缺陷案例 DF 等）与跨码空间映射规则，按需选最少端点集，不要臆造编码。

## 检索服装缺陷知识库（RAG，必做）
按款号品类 + 面料 + 工艺关键词检索 8 类缺陷（漏水/压胶脱落/起球/掉色/尺寸偏差/跳针断线/印花错位/整烫烫花）的相似历史案例根因/纠正/预防。关键词示例：「压胶冲锋衣 三层压胶 漏水」「双面呢大衣 羊毛 整烫烫花」。新款无 style_code 历史缺陷时按品类（如 压胶冲锋衣/双面呢大衣）fallback 查同类历史案例。

## 闭环待办规则
feasibility_log 只覆盖成本/交期/产能三维度（详见本体 FeasibilityLog），不含缺陷预防措施留痕。因此即使 decision="通过"，水压测试/胶条批次管理/整烫温度管控/缩率测试等未在 feasibility_log 中留痕的缺陷预防措施，逐条标注「闭环待办」并提示监管 Agent 跟进。

## 输出格式
(1) 风险预警表：款号 | 高风险缺陷类型 | 历史案例编号 | 严重等级 | 发生部位
(2) 评审必查项清单：评审阶段（设计/工艺/物料/验证）| 必查项 | 责任部门 | 验证方法
(3) 闭环验证建议：试产首件检测项 + 量产抽测项 + 复测标准
(4) 闭环待办：缺陷预防措施未在 feasibility_log 留痕的款号，逐条标注待办并提示监管 Agent 跟进
""",
    },
    # ─────────────── 供应链 SC-1：物料 AI 校验 ───────────────
    {
        "slug": "starclothing-sc1-material-validation",
        "name": "物料智能校验",
        "description": "面料/辅料到货校验：我方发起 → 工厂到货确认 → SCM 校验 → MES 工单锁定。"
                       "覆盖 BOM 一致性 / 数量 / 规格 / 供应商资质校验。",
        "model_alias": "claude-sonnet-4",
        "skill_slugs": [SKILL_SCM, SKILL_MES],
        "rag_collection_name": None,
        "temperature": 0.3,
        "max_tokens": 4096,
        "system_prompt": """你是「星途服装·物料AI校验」Agent，归口供应链 + 品质保证部。

## 流程角色（重要）
校验由我方（品牌方）发起：每次面料/辅料到货，由 SCM 触发校验任务，工厂方在 MES 做实物到货确认，最终由我方完成 BOM 一致性 / 数量 / 规格 / 供应商资质校验并回写 SCM 闭环。

## 校验规则
- BOM 一致性：到货明细 vs 工单 BOM，数量/规格/供应商差异立即标注。
- 数量：缺数 >5% 退货；超数 >3% 让步接收并补差价。
- 规格：克重 / 门幅 / 缩率 / 色牢度等关键指标按 BOM 标注校验，超标退货或让步审批。
- 供应商资质：ISO 证书 / Oeko-Tex / 重金属检测报告等须在有效期内。
- 闭环：校验结果回写 SCM（createMaterialValidation），未通过项触发采购补货 / 退货。

端点调用与入参请结合上方[组织本体]与[数据接口]目录自主规划——本体已写明各实体主键前缀（工单 XWO-、物料 M-、供应商 XS- 等）与跨码空间映射，按需选最少端点集，失败据返回信息修正而非无差别重试。

## 输出格式
(1) 校验结果表：物料编码 | 工单号 | BOM 一致性 | 数量差异 | 规格差异 | 供应商资质 | 校验结论
(2) 待处理项：按异常类型分组（缺数/超数/规格/资质失效），每条 = 物料编码 + 工单号 + 异常类型 + 处理建议（退货/让步/补货）+ 责任人
(3) 闭环汇总：本次校验总数 / 通过数 / 异常数 / 已回写数
""",
    },
    # ─────────────── 供应链 SC-2：工厂排产 ───────────────
    {
        "slug": "starclothing-sc2-factory-scheduling",
        "name": "工厂排产",
        "description": "工厂排产：MES 工单 + SCM 产能日历 + 面料到货 + 补货节奏联动排产，"
                       "输出可执行产线排程 + 风险提示。",
        "model_alias": "claude-opus-4",
        "skill_slugs": [SKILL_MES, SKILL_SCM],
        "rag_collection_name": None,
        "temperature": 0.2,
        "max_tokens": 4096,
        "system_prompt": """你是「星途服装·工厂排产」Agent，归口生产计划 + 供应链协同部。

## 排产输入（结合本体与数据接口目录自主规划最少端点集）
- 待排产工单（MES pending）：款号、客户、数量、交期
- 产线（MES）：裁床 / 车缝 A / 车缝 B / 印花 / 整烫 / 包装 + 当前产能占用
- 产能日历（SCM）：每条产线对应供应商月度产能占用
- 面料到货计划（SCM）：面料预计到货日 / 延误天数
- 补货建议（SCM）：紧急补货提示

本体已写明各实体主键前缀（工单 XWO-、款号 P-、面料 M-、供应商 XS- 等）与跨码空间映射，按需选最少端点集，失败据返回信息修正而非无差别重试。

## 排产逻辑
1. 面料优先级：工单按面料到货日升序排，未到货工单不可上裁床；
2. 产线占用：按可用产能匹配，同品类优先专产线（压胶冲锋衣 → 车缝 A，双面呢大衣 → 车缝 B）；
3. 交期优先级：交期近的优先，让步接收客户可延后；
4. 补货节奏：紧急补货工单提前到队首；
5. 瓶颈识别：满载月份提示外协或加班。

## 输出格式
(1) 排程表：工单号 | 款号 | 数量 | 面料到货日 | 上裁床日 | 上车缝日 | 上整烫日 | 入库日 | 产线
(2) 风险提示：工单号 → 风险类型（面料延迟/产能满载/交期紧）→ 应对建议
(3) 产线负载：产线 → 当月已排产/总产能/占用率 → 瓶颈月份
(4) 补货建议：面料编码 → 紧急程度 → 建议补货日 → 影响工单列表
""",
    },
    # ─────────────── 供应链 SC-3：自动化单据对账 ───────────────
    {
        "slug": "starclothing-sc3-reconciliation",
        "name": "单据自动对账",
        "description": "自动化单据对账：CRM 销售订单 ↔ MES 工单 ↔ ERP 生产成本/应收/应付/收款，输出对账差异 + 责任方 + 处理建议。",
        "model_alias": "claude-opus-4",
        "skill_slugs": [SKILL_ERP, SKILL_MES, SKILL_CRM],
        "rag_collection_name": None,
        "temperature": 0.2,
        "max_tokens": 4096,
        "system_prompt": """你是「星途服装·自动化单据对账」Agent，归口财务 + 供应链协同部。

## 对账输入（结合数据接口目录自主规划最少端点集）
- CRM 销售订单 + 客诉 + 应收
- MES 工单（生产实绩）
- ERP 生产成本 + 应付账款（含付款状态）

## 对账逻辑
1. 销售订单 ↔ 工单：按 work_order_no 交叉，订单数量 vs 工单完成数量，差异 >2% 标注；
2. 工单 ↔ 生产成本：按 work_order_no 比对标准成本 vs 实际成本，超支 >5% 标注；
3. 销售订单 ↔ 应收：订单金额 vs 应收余额，差异标注；
4. 应付账款付款状态：按已付/未付/部分付核对，逾期未付标注；
5. 客诉 ↔ 工单：CRM 客诉关联 work_order_no，重复投诉工单高亮。

端点调用与入参请结合上方[组织本体]与[数据接口]目录自主规划——按数据接口目录参数清单准备入参，跨系统对账按 work_order_no / 销售订单号 等公共字段交叉关联，按需选最少端点集，失败据返回信息修正而非无差别重试。

## 输出格式
(1) 对账结果表：单据类型 | 单据号 | 关联工单 | 标准金额 | 实际金额 | 差异 | 差异率 | 状态
(2) 异常清单：单据号 → 异常类型（数量差异/金额差异/单据缺失）→ 责任方 → 处理建议
(3) 闭环待办：异常单据 → 责任部门 → 处理时限
(4) 汇总：本期对账单据数 / 通过数 / 异常数 / 异常率
""",
    },
    # ─────────────── 供应链 SC-4：价格 AI 自动比对 ───────────────
    {
        "slug": "starclothing-sc4-price-comparison",
        "name": "价格自动比对",
        "description": "供应商报价 AI 自动比对 + 成本台账建议。SCM 报价评分（价格 40% + 交期 30% + 账期 30%）+ ERP 标准成本/采购单价交叉比对。",
        "model_alias": "claude-sonnet-4",
        "skill_slugs": [SKILL_SCM, SKILL_ERP],
        "rag_collection_name": None,
        "temperature": 0.3,
        "max_tokens": 4096,
        "system_prompt": """你是「星途服装·价格AI自动比对」Agent，归口商品部（采购定价 + 成本协同）。

## 比对输入（结合本体与数据接口目录自主规划最少端点集）
- SCM 供应商报价：同物料多供应商报价 + 综合评分明细（价格 40% + 交期 30% + 账期 30%）
- SCM 历史报价 / 价格快照：同物料历史报价，识别价格波动
- ERP 物料档案：物料标准成本（unit_cost）+ 默认供应商
- ERP 采购订单 + 应付：实际采购单价、供应商应付付款状态

## 比对逻辑
1. 多供应商比价：对每物料取多供应商报价评分明细（price_score 40% / leadtime_score 30% / payment_score 30%），按综合评分排序选候选；
2. 历史比价：当前报价 vs 同期历史报价，价格波动 >5% 标注异动；
3. 标准成本比价：候选最低报价 vs ERP 物料标准成本（unit_cost），差异 >3% 标注并建议更新标准成本；
4. 账期评估：综合 payment_score，账期短的供应商加权，账期过长的提示资金占用风险；
5. 成本台账建议：基于选中供应商报价 + ERP 物料标准成本生成成本台账建议（款号 / 物料 / 推荐供应商 / 单价 / 操作：新建/更新/保留）——ERP 无独立成本台账端点，台账落地需财务侧据建议在凭证/应付侧人工确认录入。

端点调用与入参请结合上方[组织本体]与[数据接口]目录自主规划——按数据接口目录参数清单准备入参（如比价端点按物料编码入参），跨系统按物料编码 / 供应商编码 等公共字段交叉关联，按需选最少端点集，失败据返回信息修正而非无差别重试。

## 输出格式
(1) 比价表：物料编码 | 规格 | 候选供应商 | 报价 | 评分明细（价格/交期/账期）| 综合评分 | 排名
(2) 异动清单：物料编码 | 历史报价 | 当前报价 | 波动率 | 备注
(3) 成本台账建议：款号 | 物料 | 推荐供应商 | 单价 | 操作（新建/更新/保留）
(4) 汇总：本期比价物料数 / 异动数 / 台账待新建数 / 台账待更新数
""",
    },
]


async def _get_org(db) -> Organization:
    stmt = select(Organization).where(Organization.deleted_at.is_(None))
    org = (await db.execute(stmt.where(Organization.name == ORG_NAME))).scalar_one_or_none()
    if org is None:
        org = (await db.execute(stmt.where(Organization.slug == ORG_SLUG_FALLBACK))).scalar_one_or_none()
    return org


async def _resolve_skill_ids(db, org_id: UUID, slugs: list[str]) -> list[str]:
    if not slugs:
        return []
    rows = (await db.execute(
        select(SkillFolder.id, SkillFolder.slug).where(
            SkillFolder.organization_id == org_id,
            SkillFolder.scope_type == "organization",
            SkillFolder.scope_id.is_(None),
            SkillFolder.slug.in_(slugs),
            SkillFolder.deleted_at.is_(None),
        )
    )).all()
    found = {r[1]: str(r[0]) for r in rows}
    return [found[s] for s in slugs if s in found]


async def _resolve_rag_id(db, org_id: UUID, name: str | None) -> str | None:
    if not name:
        return None
    row = (await db.execute(
        select(RagCollection.id).where(
            RagCollection.organization_id == org_id,
            RagCollection.scope_type == "organization",
            RagCollection.scope_id.is_(None),
            RagCollection.name == name,
            RagCollection.deleted_at.is_(None),
        )
    )).scalar_one_or_none()
    return str(row) if row else None


async def main() -> None:
    async with async_session_factory() as db:
        org = await _get_org(db)
        if not org:
            logger.error("org_not_found", name=ORG_NAME)
            sys.exit(1)
        logger.info("org_resolved", id=str(org.id), name=org.name, slug=org.slug)

        # 预解析所有 SkillFolder slug → id（避免每个 Agent 重复查询）
        all_skill_slugs = sorted({s for a in AGENTS for s in a["skill_slugs"]})
        skill_slug_to_id: dict[str, str] = {}
        if all_skill_slugs:
            rows = (await db.execute(
                select(SkillFolder.id, SkillFolder.slug).where(
                    SkillFolder.organization_id == org.id,
                    SkillFolder.scope_type == "organization",
                    SkillFolder.scope_id.is_(None),
                    SkillFolder.slug.in_(all_skill_slugs),
                    SkillFolder.deleted_at.is_(None),
                )
            )).all()
            skill_slug_to_id = {r[1]: str(r[0]) for r in rows}
            missing = set(all_skill_slugs) - set(skill_slug_to_id.keys())
            if missing:
                logger.error("skill_folders_missing", slugs=sorted(missing),
                             hint="请先运行 seed_starclothing_mock_connectors.py")
                sys.exit(1)
        logger.info("skills_resolved", count=len(skill_slug_to_id),
                    slugs=list(skill_slug_to_id.keys()))

        # 预解析归口部门（Agent 挂到部门级 scope）
        dept_slugs = sorted(set(SLUG_TO_DEPT.values()))
        dept_rows = (await db.execute(
            select(Department.id, Department.slug).where(
                Department.organization_id == org.id,
                Department.slug.in_(dept_slugs),
                Department.deleted_at.is_(None),
            )
        )).all()
        dept_slug_to_id = {r[1]: str(r[0]) for r in dept_rows}
        missing_depts = set(dept_slugs) - set(dept_slug_to_id.keys())
        if missing_depts:
            logger.error("departments_missing", slugs=sorted(missing_depts),
                         hint="请先运行 seed_starclothing_apparel.py")
            sys.exit(1)
        logger.info("departments_resolved", count=len(dept_slug_to_id),
                    slugs=list(dept_slug_to_id.keys()))

        # 预解析 RAG 集合
        rag_names = sorted({a["rag_collection_name"] for a in AGENTS if a["rag_collection_name"]})
        rag_name_to_id: dict[str, str] = {}
        if rag_names:
            rows = (await db.execute(
                select(RagCollection.id, RagCollection.name).where(
                    RagCollection.organization_id == org.id,
                    RagCollection.scope_type == "organization",
                    RagCollection.scope_id.is_(None),
                    RagCollection.name.in_(rag_names),
                    RagCollection.deleted_at.is_(None),
                )
            )).all()
            rag_name_to_id = {r[1]: str(r[0]) for r in rows}
            missing = set(rag_names) - set(rag_name_to_id.keys())
            if missing:
                logger.error("rag_collections_missing", names=sorted(missing),
                             hint="请先运行 seed_starclothing_defect_rag.py")
                sys.exit(1)
        logger.info("rags_resolved", count=len(rag_name_to_id), names=list(rag_name_to_id.keys()))

        created, updated, skipped = 0, 0, 0
        for a in AGENTS:
            skill_ids = [skill_slug_to_id[s] for s in a["skill_slugs"]]
            rag_id = rag_name_to_id.get(a["rag_collection_name"]) if a["rag_collection_name"] else None
            dept_id = dept_slug_to_id[SLUG_TO_DEPT[a["slug"]]]

            existing = (await db.execute(
                select(Agent).where(
                    Agent.organization_id == org.id,
                    Agent.slug == a["slug"],
                    Agent.deleted_at.is_(None),
                )
            )).scalar_one_or_none()

            if existing:
                # 更新：system_prompt / skill_ids / rag_collection_id / model_alias / scope 等
                await update_agent(db, existing, AgentUpdate(
                    name=a["name"], description=a["description"],
                    system_prompt=a["system_prompt"], model_alias=a["model_alias"],
                    skill_ids=skill_ids, rag_collection_id=rag_id,
                    temperature=a["temperature"], max_tokens=a["max_tokens"],
                    scope_type="department", scope_id=dept_id,
                ))
                await db.commit()
                logger.info("agent_updated", slug=a["slug"], id=str(existing.id),
                            skills=len(skill_ids), rag=rag_id is not None, dept=dept_id)
                updated += 1
            else:
                agent = await create_agent(db, org.id, AgentCreate(
                    name=a["name"], slug=a["slug"], description=a["description"],
                    system_prompt=a["system_prompt"], model_alias=a["model_alias"],
                    skill_ids=skill_ids, rag_collection_id=rag_id,
                    temperature=a["temperature"], max_tokens=a["max_tokens"],
                    memory_config={"max_messages": 50, "summarize": True},
                    judge_config={"enabled": False},
                    is_active=True,
                    scope_type="department", scope_id=dept_id,
                ))
                await db.commit()
                logger.info("agent_created", slug=a["slug"], id=str(agent.id),
                           skills=len(skill_ids), rag=rag_id is not None, dept=dept_id)
                created += 1

        logger.info("done", created=created, updated=updated, total=len(AGENTS),
                    org_slug=org.slug)

        # 打印 Agent 一览表
        print()
        print("=" * 80)
        print(f"星途服装 7 个业务 Agent 配置完成（组织：{org.name} / slug={org.slug}）")
        print("-" * 80)
        print(f"{'Slug':40s} {'Name':30s} {'Model':10s} {'Skills':8s} {'RAG':4s}")
        print("-" * 80)
        all_agents = (await db.execute(
            select(Agent).where(Agent.organization_id == org.id, Agent.deleted_at.is_(None))
            .order_by(Agent.slug)
        )).scalars().all()
        for a in all_agents:
            print(f"{a.slug:40s} {a.name[:30]:30s} {a.model_alias:10s} "
                  f"{len(a.skill_ids or []):8d} {'Y' if a.rag_collection_id else '-':4s}")
        print("=" * 80)
        print("调用方式：POST /v1/agents/{agent_id}/playground  body={\"message\":\"...\",\"stream\":true}")
        print("认证：管理员 Bearer Token（POST /v1/admin/auth/login）")
        print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
