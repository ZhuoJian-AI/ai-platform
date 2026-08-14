"""导入「敏睿空调」AI 应用 demo 组织数据（HVAC 企业组织架构 + LLM 路由 + API Key）。

幂等：按 slug / username 去重，已存在则跳过；可安全重复执行。
覆盖：组织 → 部门 → 团队 → 用户（含 password_hash=hash_password('12345678')）→
      LLM 提供商 → 模型别名 → 路由策略 → 示例 API Key。

组织架构（11 部门 / 16+ 团队 / 17 用户）依据 README §4：
    rnd / product / production / quality / supply / sales / after-sales /
    marketing / finance / hr / it

与 mock 多租户对接：组织级 API Key 供「敏睿连接器」绑定到 PLM/SCM/ERP/MES/CRM/HRM
各自的 agileac 演示 key（连接器 auth_config 内直接持有 mock key）。本脚本只生成
平台侧 API Key（用于调 LLM Router / Terminal Agent），不重复生成 mock 侧 key。

⚠️ 与 starclothing/minrui seed 不同：本脚本直接对 17 个用户写入
   `password_hash = hash_password("12345678")`，确保登录 `/agileac/terminal/login`
   可用——无需后续管理员手动重置。

用法:
    docker cp demo/agileac/scripts/seed_agileac_org.py ai_infra_backend:/app/scripts/
    docker exec ai_infra_backend python scripts/seed_agileac_org.py
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path

# 兼容两种位置：容器内 /app/scripts/ → backend=/app；本地 demo/agileac/scripts/ → backend=repo/llm_router/backend
_HERE = Path(__file__).resolve()
_BACKEND_DIR = _HERE.parent.parent
if not (_BACKEND_DIR / "app" / "database.py").exists():
    _BACKEND_DIR = _HERE.parents[3] / "llm_router" / "backend"
sys.path.insert(0, str(_BACKEND_DIR))

import structlog  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.auth.security import hash_password  # noqa: E402
from app.database import async_session_factory  # noqa: E402
from app.models.api_key import ApiKey  # noqa: E402
from app.models.department import Department  # noqa: E402
from app.models.llm_provider import LlmProvider  # noqa: E402
from app.models.organization import Organization  # noqa: E402
from app.models.routing_policy import RoutingPolicy  # noqa: E402
from app.models.team import Team  # noqa: E402
from app.models.user import User  # noqa: E402
from app.utils.crypto import encrypt_api_key, encrypt_provider_api_key, generate_api_key  # noqa: E402

logger = structlog.get_logger()

DEFAULT_PASSWORD = "12345678"


# ───────────────────────── 预置数据定义 ─────────────────────────

ORG_DEF = {
    "name": "敏睿空调",
    "slug": "agileac",
    "description": "家用+商用空调全产业链 AI 应用 demo——11 场景按部门边界划分，员工 vibe working 辅助",
    "rate_limit_rpm": 1500,
    "rate_limit_tpm": 800_000,
    "budget_cap_usd": 3000,
    "budget_cap_tokens": 150_000_000,
    "settings": {"locale": "zh-CN", "industry": "hvac"},
}

# 11 部门（README §4.2）
DEPARTMENT_DEFS = {
    "rnd": {"name": "研发部", "slug": "rnd",
            "description": "产品研发、结构设计、电气控制、技术翻译",
            "rate_limit_rpm": 350, "budget_cap_usd": 400},
    "product": {"name": "产品部", "slug": "product",
                "description": "产品规划、卖点提炼、生命周期管理",
                "rate_limit_rpm": 250, "budget_cap_usd": 300},
    "production": {"name": "生产制造部", "slug": "production",
                   "description": "排产计划、总装车间、测试车间",
                   "rate_limit_rpm": 350, "budget_cap_usd": 350},
    "quality": {"name": "质量部", "slug": "quality",
                "description": "制程质量、缺陷分析、5W2H 根因",
                "rate_limit_rpm": 250, "budget_cap_usd": 250},
    "supply": {"name": "供应链部", "slug": "supply",
               "description": "采购、物流、对账、交期管理",
               "rate_limit_rpm": 300, "budget_cap_usd": 300},
    "sales": {"name": "销售部", "slug": "sales",
              "description": "销售运营、电商、经销渠道",
              "rate_limit_rpm": 300, "budget_cap_usd": 300},
    "after-sales": {"name": "售后服务部", "slug": "after-sales",
                    "description": "现场售后、故障诊断、客诉闭环",
                    "rate_limit_rpm": 300, "budget_cap_usd": 300},
    "marketing": {"name": "市场部", "slug": "marketing",
                  "description": "市场内容、竞情、培训",
                  "rate_limit_rpm": 350, "budget_cap_usd": 400},
    "finance": {"name": "财务部", "slug": "finance",
                "description": "应付应收、成本核算、对账",
                "rate_limit_rpm": 200, "budget_cap_usd": 200},
    "hr": {"name": "人力资源部", "slug": "hr",
           "description": "招聘、培训、薪酬绩效",
           "rate_limit_rpm": 200, "budget_cap_usd": 200},
    "it": {"name": "信息技术部", "slug": "it",
           "description": "系统运维、AI 应用落地",
           "rate_limit_rpm": 350, "budget_cap_usd": 400},
}

# 16 团队（README §4.3）
TEAM_DEFS = {
    "rnd": [
        {"name": "研发翻译组", "slug": "rnd-translation", "description": "技术资料 / 卖点文案多语种翻译"},
        {"name": "结构组", "slug": "rnd-mechanical", "description": "钣金、注塑、管路结构设计"},
        {"name": "电气组", "slug": "rnd-electrical", "description": "电控板、变频驱动、通讯协议"},
    ],
    "product": [],  # 产品部不分团队
    "production": [
        {"name": "排产计划组", "slug": "prod-planning", "description": "PMC 排产、补单节奏、产能协调"},
        {"name": "总装车间", "slug": "prod-assembly", "description": "家用/商用总装线"},
        {"name": "测试车间", "slug": "prod-test", "description": "安规 / 性能 / EMC 测试"},
    ],
    "quality": [
        {"name": "质量工程组", "slug": "qal-engineering", "description": "缺陷 5W2H 根因、SOP 修订"},
    ],
    "supply": [
        {"name": "采购组", "slug": "supply-procurement", "description": "压缩机/换热器/阀件/制冷剂采购"},
        {"name": "物流组", "slug": "supply-logistics", "description": "入库、配送、售后件调拨"},
    ],
    "sales": [
        {"name": "销售运营组", "slug": "sales-ops", "description": "工程项目 / 经销订单 / 回款"},
        {"name": "电商组", "slug": "sales-ecom", "description": "电商订单、退换货、评价"},
        {"name": "经销渠道组", "slug": "sales-dealer", "description": "经销商拓展、渠道政策"},
    ],
    "after-sales": [
        {"name": "售后工程师组", "slug": "svc-engineer", "description": "现场故障诊断、维修、客诉闭环"},
    ],
    "marketing": [
        {"name": "市场内容组", "slug": "mkt-content", "description": "卖点文案、内容资产、PR"},
        {"name": "竞情组", "slug": "mkt-competitive", "description": "竞品分析、价格监测"},
        {"name": "市场培训组", "slug": "mkt-training", "description": "经销商培训、内训"},
    ],
    "finance": [
        {"name": "财务对账组", "slug": "fin-recon", "description": "应付对账、供应商对账"},
        {"name": "财务应收组", "slug": "fin-receivable", "description": "客户应收、逾期管理"},
        {"name": "财务应付组", "slug": "fin-payable", "description": "付款执行、票据管理"},
    ],
    "hr": [
        {"name": "招聘组", "slug": "hr-recruiting", "description": "简历筛选、面试、录用"},
        {"name": "培训组", "slug": "hr-training", "description": "新人培训、制度文档"},
        {"name": "薪酬组", "slug": "hr-compensation", "description": "薪酬核算、绩效"},
    ],
    "it": [
        {"name": "系统运维组", "slug": "it-infra", "description": "基础设施、网络、安全"},
        {"name": "AI 应用组", "slug": "it-ai", "description": "Agent / RAG / 工具接入"},
    ],
}

# 17 用户（README §4.4）——username 非邮箱形式，密码统一 12345678
# 字段: username, display_name, role, dept_slug, team_slug, scenario
USER_DEFS = [
    {"username": "admin", "display_name": "组织管理员", "role": "admin",
     "dept_slug": None, "team_slug": None, "scenario": "管理端配置"},
    {"username": "it-specialist", "display_name": "IT AI 应用专员", "role": "member",
     "dept_slug": "it", "team_slug": "it-ai", "scenario": "平台运维（非对外场景）"},
    {"username": "rnd-translator", "display_name": "研发翻译员", "role": "member",
     "dept_slug": "rnd", "team_slug": "rnd-translation", "scenario": "RND-01"},
    {"username": "pm-product", "display_name": "产品专员", "role": "member",
     "dept_slug": "product", "team_slug": None, "scenario": "PRD-01"},
    {"username": "mfg-planner", "display_name": "排产计划员", "role": "member",
     "dept_slug": "production", "team_slug": "prod-planning", "scenario": "MFG-01"},
    {"username": "qal-engineer", "display_name": "质量工程师", "role": "member",
     "dept_slug": "quality", "team_slug": "qal-engineering", "scenario": "QAL-01"},
    {"username": "scm-buyer", "display_name": "采购员", "role": "member",
     "dept_slug": "supply", "team_slug": "supply-procurement", "scenario": "SCM-01 采购"},
    {"username": "scm-logistics", "display_name": "物流员", "role": "member",
     "dept_slug": "supply", "team_slug": "supply-logistics", "scenario": "SCM-01 物流"},
    {"username": "sal-ops", "display_name": "销售运营员", "role": "member",
     "dept_slug": "sales", "team_slug": "sales-ops", "scenario": "SAL-01 订单回款 + SAL-02 报销进度"},
    {"username": "sal-ecom", "display_name": "电商运营员", "role": "member",
     "dept_slug": "sales", "team_slug": "sales-ecom", "scenario": "SAL-01 退换货"},
    {"username": "svc-engineer", "display_name": "售后工程师", "role": "member",
     "dept_slug": "after-sales", "team_slug": "svc-engineer", "scenario": "SVC-01"},
    {"username": "mkt-specialist", "display_name": "市场专员", "role": "member",
     "dept_slug": "marketing", "team_slug": "mkt-content", "scenario": "MKT-01"},
    {"username": "fin-accountant", "display_name": "财务会计", "role": "member",
     "dept_slug": "finance", "team_slug": "fin-recon", "scenario": "FIN-01 对账"},
    {"username": "fin-receivable", "display_name": "应收会计", "role": "member",
     "dept_slug": "finance", "team_slug": "fin-receivable", "scenario": "FIN-01 应收"},
    {"username": "hr-recruiter", "display_name": "招聘专员", "role": "member",
     "dept_slug": "hr", "team_slug": "hr-recruiting", "scenario": "HR-01 招聘"},
    {"username": "hr-trainer", "display_name": "培训专员", "role": "member",
     "dept_slug": "hr", "team_slug": "hr-training", "scenario": "HR-01 培训制度"},
    {"username": "hr-compensation", "display_name": "薪酬专员", "role": "member",
     "dept_slug": "hr", "team_slug": "hr-compensation", "scenario": "HR-01 薪酬"},
]

# LLM 提供商（与 minrui/starclothing 同构，部署后替换 api_key）
PROVIDER_DEFS = [
    {
        "name": "Anthropic 官方",
        "provider_type": "anthropic",
        "base_url": "https://api.anthropic.com",
        "api_key": "demo-provider-key-not-a-secret",
        "priority": 100,
        "weight": 1,
        "timeout_seconds": 120,
        "max_retries": 2,
        "supported_models": ["claude-opus-4", "claude-sonnet-4", "claude-haiku-4"],
        "config": {},
    },
    {
        "name": "OpenAI 官方",
        "provider_type": "openai",
        "base_url": "https://api.openai.com/v1",
        "api_key": "sk-PRESET-REPLACE-ME",
        "priority": 90,
        "weight": 1,
        "timeout_seconds": 120,
        "max_retries": 2,
        "supported_models": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo"],
        "config": {},
    },
    {
        "name": "DeepSeek",
        "provider_type": "custom",
        "base_url": "https://api.deepseek.com/v1",
        "api_key": "sk-PRESET-REPLACE-ME",
        "priority": 70,
        "weight": 2,
        "timeout_seconds": 120,
        "max_retries": 2,
        "supported_models": ["deepseek-chat", "deepseek-reasoner"],
        "config": {"auth_header": "Authorization", "auth_scheme": "Bearer"},
    },
    {
        "name": "智谱 AI",
        "provider_type": "custom",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "api_key": "PRESET-REPLACE-ME",
        "priority": 80,
        "weight": 2,
        "timeout_seconds": 120,
        "max_retries": 2,
        "supported_models": ["glm-5.2", "glm-4.6", "glm-4-plus"],
        "config": {"auth_header": "Authorization", "auth_scheme": "Bearer"},
    },
]

ROUTING_DEFS = [
    {"name": "Claude 路由（主）", "description": "claude-* 命中走 Anthropic",
     "model_pattern": "claude-*", "strategy": "priority",
     "provider_names": ["Anthropic 官方"], "is_default": True},
    {"name": "GPT 路由", "description": "gpt-* 命中走 OpenAI",
     "model_pattern": "gpt-*", "strategy": "priority",
     "provider_names": ["OpenAI 官方"], "is_default": False},
    {"name": "DeepSeek 路由", "description": "deepseek-* 命中走 DeepSeek",
     "model_pattern": "deepseek-*", "strategy": "priority",
     "provider_names": ["DeepSeek"], "is_default": False},
    {"name": "GLM 路由", "description": "glm-* 命中走智谱",
     "model_pattern": "glm-*", "strategy": "priority",
     "provider_names": ["智谱 AI"], "is_default": False},
]

# 16 把 API Key（1 组织级 + 1 部门级 + 14 团队级，README §4.6）
APIKEY_DEFS = [
    {"key_name": "敏睿空调 默认 Key（组织级，demo 用）",
     "scope_type": "organization", "department_slug": None, "team_slug": None,
     "allowed_models": [], "rate_limit_rpm": 300, "budget_cap_usd": 300},
    {"key_name": "研发翻译组 Key", "scope_type": "team",
     "department_slug": "rnd", "team_slug": "rnd-translation",
     "allowed_models": ["claude-sonnet-4", "gpt-4o-mini", "glm-5.2"],
     "rate_limit_rpm": 60, "budget_cap_usd": 80},
    {"key_name": "产品部 Key", "scope_type": "department",
     "department_slug": "product", "team_slug": None,
     "allowed_models": ["claude-sonnet-4", "gpt-4o-mini", "glm-5.2"],
     "rate_limit_rpm": 80, "budget_cap_usd": 100},
    {"key_name": "排产计划组 Key", "scope_type": "team",
     "department_slug": "production", "team_slug": "prod-planning",
     "allowed_models": ["claude-sonnet-4", "gpt-4o-mini", "glm-5.2"],
     "rate_limit_rpm": 60, "budget_cap_usd": 80},
    {"key_name": "质量工程组 Key", "scope_type": "team",
     "department_slug": "quality", "team_slug": "qal-engineering",
     "allowed_models": ["claude-sonnet-4", "gpt-4o-mini", "glm-5.2"],
     "rate_limit_rpm": 60, "budget_cap_usd": 80},
    {"key_name": "采购组 Key", "scope_type": "team",
     "department_slug": "supply", "team_slug": "supply-procurement",
     "allowed_models": ["claude-sonnet-4", "deepseek-chat", "glm-5.2"],
     "rate_limit_rpm": 60, "budget_cap_usd": 80},
    {"key_name": "物流组 Key", "scope_type": "team",
     "department_slug": "supply", "team_slug": "supply-logistics",
     "allowed_models": ["claude-sonnet-4", "gpt-4o-mini", "glm-5.2"],
     "rate_limit_rpm": 60, "budget_cap_usd": 80},
    {"key_name": "销售运营组 Key", "scope_type": "team",
     "department_slug": "sales", "team_slug": "sales-ops",
     "allowed_models": ["claude-sonnet-4", "gpt-4o-mini", "glm-5.2"],
     "rate_limit_rpm": 60, "budget_cap_usd": 80},
    {"key_name": "电商组 Key", "scope_type": "team",
     "department_slug": "sales", "team_slug": "sales-ecom",
     "allowed_models": ["claude-sonnet-4", "gpt-4o-mini", "glm-5.2"],
     "rate_limit_rpm": 60, "budget_cap_usd": 80},
    {"key_name": "售后工程师组 Key", "scope_type": "team",
     "department_slug": "after-sales", "team_slug": "svc-engineer",
     "allowed_models": ["claude-sonnet-4", "claude-haiku-4", "glm-5.2"],
     "rate_limit_rpm": 60, "budget_cap_usd": 80},
    {"key_name": "市场内容组 Key", "scope_type": "team",
     "department_slug": "marketing", "team_slug": "mkt-content",
     "allowed_models": ["claude-sonnet-4", "gpt-4o-mini", "glm-5.2"],
     "rate_limit_rpm": 60, "budget_cap_usd": 80},
    {"key_name": "财务对账组 Key", "scope_type": "team",
     "department_slug": "finance", "team_slug": "fin-recon",
     "allowed_models": ["claude-sonnet-4", "glm-5.2"],
     "rate_limit_rpm": 40, "budget_cap_usd": 60},
    {"key_name": "财务应收组 Key", "scope_type": "team",
     "department_slug": "finance", "team_slug": "fin-receivable",
     "allowed_models": ["claude-sonnet-4", "glm-5.2"],
     "rate_limit_rpm": 40, "budget_cap_usd": 60},
    {"key_name": "招聘组 Key", "scope_type": "team",
     "department_slug": "hr", "team_slug": "hr-recruiting",
     "allowed_models": ["claude-sonnet-4", "glm-5.2"],
     "rate_limit_rpm": 40, "budget_cap_usd": 60},
    {"key_name": "培训组 Key", "scope_type": "team",
     "department_slug": "hr", "team_slug": "hr-training",
     "allowed_models": ["claude-sonnet-4", "glm-5.2"],
     "rate_limit_rpm": 40, "budget_cap_usd": 60},
    {"key_name": "薪酬组 Key", "scope_type": "team",
     "department_slug": "hr", "team_slug": "hr-compensation",
     "allowed_models": ["claude-sonnet-4", "glm-5.2"],
     "rate_limit_rpm": 40, "budget_cap_usd": 60},
]


# ───────────────────────── 辅助 ─────────────────────────

async def _get_org_by_slug(db: AsyncSession, slug: str) -> Organization | None:
    result = await db.execute(
        select(Organization).where(Organization.slug == slug, Organization.deleted_at.is_(None))
    )
    return result.scalar_one_or_none()


async def _get_dept_by_slug(db: AsyncSession, org_id, slug: str) -> Department | None:
    result = await db.execute(
        select(Department).where(
            Department.organization_id == org_id,
            Department.slug == slug,
            Department.deleted_at.is_(None),
        )
    )
    return result.scalar_one_or_none()


async def _get_team_by_slug(db: AsyncSession, dept_id, slug: str) -> Team | None:
    result = await db.execute(
        select(Team).where(Team.department_id == dept_id, Team.slug == slug, Team.deleted_at.is_(None))
    )
    return result.scalar_one_or_none()


# ───────────────────────── 主流程 ─────────────────────────

async def seed() -> dict:
    stats = {
        "organization": 0, "department": 0, "team": 0, "user": 0, "user_password_set": 0,
        "provider": 0, "routing_policy": 0, "api_key": 0,
    }
    created_api_keys: list[tuple[str, str]] = []

    async with async_session_factory() as db:
        # 1) 组织
        org = await _get_org_by_slug(db, ORG_DEF["slug"])
        if org is None:
            org = Organization(**ORG_DEF)
            db.add(org)
            await db.flush()
            stats["organization"] += 1
            logger.info("seed_org_created", slug=org.slug)
        else:
            updated = False
            if org.name != ORG_DEF["name"]:
                org.name = ORG_DEF["name"]; updated = True
            if org.description != ORG_DEF["description"]:
                org.description = ORG_DEF["description"]; updated = True
            if org.rate_limit_rpm != ORG_DEF["rate_limit_rpm"]:
                org.rate_limit_rpm = ORG_DEF["rate_limit_rpm"]; updated = True
            if org.rate_limit_tpm != ORG_DEF["rate_limit_tpm"]:
                org.rate_limit_tpm = ORG_DEF["rate_limit_tpm"]; updated = True
            if org.budget_cap_usd != ORG_DEF["budget_cap_usd"]:
                org.budget_cap_usd = ORG_DEF["budget_cap_usd"]; updated = True
            if org.settings != ORG_DEF["settings"]:
                org.settings = ORG_DEF["settings"]; updated = True
            if updated:
                logger.info("seed_org_updated", slug=org.slug)
            else:
                logger.info("seed_org_exists", slug=org.slug)

        # 2) 部门
        dept_by_slug: dict[str, Department] = {}
        for slug, ddef in DEPARTMENT_DEFS.items():
            dept = await _get_dept_by_slug(db, org.id, slug)
            if dept is None:
                dept = Department(organization_id=org.id, **ddef)
                db.add(dept)
                await db.flush()
                stats["department"] += 1
                logger.info("seed_dept_created", slug=slug)
            dept_by_slug[slug] = dept

        # 3) 团队
        for dept_slug, tdefs in TEAM_DEFS.items():
            if not tdefs:
                continue
            dept = dept_by_slug[dept_slug]
            for tdef in tdefs:
                team = await _get_team_by_slug(db, dept.id, tdef["slug"])
                if team is None:
                    team = Team(department_id=dept.id, organization_id=org.id, **tdef)
                    db.add(team)
                    await db.flush()
                    stats["team"] += 1
                    logger.info("seed_team_created", slug=tdef["slug"])

        # 4) 用户（含 password_hash = hash_password(DEFAULT_PASSWORD)）
        pwd_hash = hash_password(DEFAULT_PASSWORD)
        for udef in USER_DEFS:
            result = await db.execute(
                select(User).where(
                    User.organization_id == org.id,
                    User.username == udef["username"],
                    User.deleted_at.is_(None),
                )
            )
            user = result.scalar_one_or_none()
            dept_id = dept_by_slug[udef["dept_slug"]].id if udef["dept_slug"] else None
            team_id = None
            if udef["team_slug"]:
                dept = dept_by_slug[udef["dept_slug"]]
                team = await _get_team_by_slug(db, dept.id, udef["team_slug"])
                team_id = team.id if team else None

            if user is None:
                user = User(
                    organization_id=org.id,
                    username=udef["username"],
                    display_name=udef["display_name"],
                    role=udef["role"],
                    department_id=dept_id,
                    team_id=team_id,
                    password_hash=pwd_hash,
                )
                db.add(user)
                await db.flush()
                stats["user"] += 1
                stats["user_password_set"] += 1
                logger.info("seed_user_created", username=udef["username"], scenario=udef["scenario"])
            else:
                # 已存在：补齐 dept/team/password（覆盖式更新）
                changed = False
                if user.display_name != udef["display_name"]:
                    user.display_name = udef["display_name"]; changed = True
                if user.role != udef["role"]:
                    user.role = udef["role"]; changed = True
                if user.department_id != dept_id:
                    user.department_id = dept_id; changed = True
                if user.team_id != team_id:
                    user.team_id = team_id; changed = True
                if not user.password_hash:
                    user.password_hash = pwd_hash
                    stats["user_password_set"] += 1
                    changed = True
                if changed:
                    logger.info("seed_user_updated", username=udef["username"])

        # 5) LLM 提供商
        provider_by_name: dict[str, LlmProvider] = {}
        for pdef in PROVIDER_DEFS:
            result = await db.execute(
                select(LlmProvider).where(
                    LlmProvider.organization_id == org.id,
                    LlmProvider.name == pdef["name"],
                    LlmProvider.deleted_at.is_(None),
                )
            )
            prov = result.scalar_one_or_none()
            if prov is None:
                prov = LlmProvider(
                    organization_id=org.id,
                    name=pdef["name"],
                    provider_type=pdef["provider_type"],
                    base_url=pdef["base_url"],
                    api_key_encrypted=encrypt_provider_api_key(pdef["api_key"]),
                    api_key_version=1,
                    is_active=True,
                    priority=pdef["priority"],
                    weight=pdef["weight"],
                    timeout_seconds=pdef["timeout_seconds"],
                    max_retries=pdef["max_retries"],
                    supported_models=pdef["supported_models"],
                    health_status="unknown",
                    config=pdef["config"],
                )
                db.add(prov)
                await db.flush()
                stats["provider"] += 1
                logger.info("seed_provider_created", name=pdef["name"])
            provider_by_name[pdef["name"]] = prov

        # 6) 路由策略
        for rdef in ROUTING_DEFS:
            result = await db.execute(
                select(RoutingPolicy).where(
                    RoutingPolicy.organization_id == org.id,
                    RoutingPolicy.name == rdef["name"],
                    RoutingPolicy.deleted_at.is_(None),
                )
            )
            if result.scalar_one_or_none() is None:
                provider_ids = [
                    str(provider_by_name[n].id) for n in rdef["provider_names"] if n in provider_by_name
                ]
                db.add(RoutingPolicy(
                    organization_id=org.id,
                    name=rdef["name"],
                    description=rdef["description"],
                    model_pattern=rdef["model_pattern"],
                    strategy=rdef["strategy"],
                    provider_ids=provider_ids,
                    is_default=rdef["is_default"],
                ))
                await db.flush()
                stats["routing_policy"] += 1
                logger.info("seed_routing_created", name=rdef["name"])

        # 7) 示例 API Key
        for kdef in APIKEY_DEFS:
            result = await db.execute(
                select(ApiKey).where(
                    ApiKey.organization_id == org.id,
                    ApiKey.key_name == kdef["key_name"],
                    ApiKey.revoked_at.is_(None),
                ).order_by(ApiKey.created_at.desc())
            )
            rows = list(result.scalars().all())
            if rows:
                # 已存在则跳过
                continue

            dept_id = None
            team_id = None
            if kdef["department_slug"]:
                dept_id = dept_by_slug[kdef["department_slug"]].id
            if kdef["team_slug"]:
                dept = dept_by_slug[kdef["department_slug"]]
                team = await _get_team_by_slug(db, dept.id, kdef["team_slug"])
                team_id = team.id if team else None

            scope = kdef["scope_type"]
            full_key, key_prefix, key_hash = generate_api_key(scope)
            db.add(ApiKey(
                key_prefix=key_prefix,
                key_hash=key_hash,
                key_encrypted=encrypt_api_key(full_key),
                key_name=kdef["key_name"],
                scope_type=scope,
                organization_id=org.id,
                department_id=dept_id,
                team_id=team_id,
                allowed_models=kdef["allowed_models"],
                rate_limit_rpm=kdef["rate_limit_rpm"],
                budget_cap_usd=kdef["budget_cap_usd"],
                is_active=True,
            ))
            await db.flush()
            stats["api_key"] += 1
            created_api_keys.append((kdef["key_name"], full_key))
            logger.info("seed_apikey_created", key_name=kdef["key_name"], prefix=key_prefix)

        await db.commit()

    return {"stats": stats, "api_keys": created_api_keys}


def _print_report(result: dict) -> None:
    stats = result["stats"]
    print("\n" + "=" * 60)
    print("「敏睿空调」AI 应用 demo 组织数据导入完成（仅统计新增；已存在则跳过）")
    print("-" * 60)
    labels = {
        "organization": "组织", "department": "部门", "team": "团队", "user": "用户",
        "user_password_set": "  ├ 密码回填",
        "provider": "LLM 提供商",
        "routing_policy": "路由策略", "api_key": "示例 API Key",
    }
    for key, label in labels.items():
        print(f"  {label:<14}: +{stats[key]}")
    print("-" * 60)
    print(f"  ℹ  全部 {len(USER_DEFS)} 用户密码统一为 '{DEFAULT_PASSWORD}'")
    if result["api_keys"]:
        print("⚠️  以下 API Key 明文仅此一次展示，请妥善保存：")
        for name, key in result["api_keys"]:
            print(f"  [{name}]\n      {key}")
    else:
        print("（示例 API Key 均已存在，未生成新密钥）")
    print("=" * 60)


if __name__ == "__main__":
    result = asyncio.run(seed())
    _print_report(result)
