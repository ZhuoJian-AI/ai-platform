"""导入「星途勘探」AI 应用 demo 组织数据（勘探设计企业组织架构 + LLM 路由 + API Key）。

幂等：按 slug / username 去重，已存在则跳过；可安全重复执行。
覆盖：组织 → 部门 → 团队 → 用户（含 password_hash=hash_password('12345678')）→
      LLM 提供商 → 路由策略 → 示例 API Key。

组织架构（9 业务部门 + 信息中心 / 多团队 / 11 用户）：
    design / cost / epc / safety / security / finance / admin / legal / hr / it

LLM 提供商与路由策略完全照搬 agileac / agilesteel / agilestationery（4 家 provider + 4 条路由），
部署后用 README §3 的 SQL 从 agileac 复制真实 provider key（占位 key 无 embedding/chat 能力）。
与 mock 多租户对接：组织级 API Key 供「星途勘探」连接器绑定到
DES/EPC/SEC/ERP/HRM/CRM 各自的 starexploration 演示 key。

用法:
    docker cp demo/starexploration/scripts/seed_starexploration_org.py ai_infra_backend:/app/scripts/
    docker exec ai_infra_backend python scripts/seed_starexploration_org.py
"""

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

ORG_DEF = {
    "name": "星途勘探",
    "slug": "starexploration",
    "description": "勘探设计企业 AI 应用 demo——9 场景按部门边界划分，工程咨询/勘察设计/EPC总承包/涉密保密/职能管理",
    "rate_limit_rpm": 1500,
    "rate_limit_tpm": 800_000,
    "budget_cap_usd": 3000,
    "budget_cap_tokens": 150_000_000,
    "settings": {"locale": "zh-CN", "industry": "survey-design"},
}

# 9 业务部门 + 信息中心
DEPARTMENT_DEFS = {
    "design": {"name": "设计研究院", "slug": "design",
               "description": "方案设计、BIM/绘图、规范合规校验、智能算量与造价、设计知识管理",
               "rate_limit_rpm": 300, "budget_cap_usd": 300},
    "cost": {"name": "造价技经部", "slug": "cost",
             "description": "工程算量、概预算、EPC 成本测算、变更签证、造价数据库",
             "rate_limit_rpm": 250, "budget_cap_usd": 250},
    "epc": {"name": "EPC 总承包部", "slug": "epc",
            "description": "工程总承包项目进度/成本/采购/施工/文档全流程管控",
            "rate_limit_rpm": 300, "budget_cap_usd": 300},
    "safety": {"name": "安全生产部", "slug": "safety",
               "description": "办公区与项目现场安全管控、智能巡检、风险分级、安全教育",
               "rate_limit_rpm": 250, "budget_cap_usd": 250},
    "security": {"name": "保密办公室", "slug": "security",
                 "description": "涉密内容检测、文档脱密、保密行为预警、涉密载体全生命周期",
                 "rate_limit_rpm": 250, "budget_cap_usd": 250},
    "finance": {"name": "资产财务部", "slug": "finance",
                "description": "智能核算、票据验真、预算成本管控、资金税务、财务风险预警",
                "rate_limit_rpm": 200, "budget_cap_usd": 200},
    "admin": {"name": "综合管理部", "slug": "admin",
              "description": "公文处理、会议纪要、行政知识问答、后勤保障",
              "rate_limit_rpm": 200, "budget_cap_usd": 200},
    "legal": {"name": "法律合规部", "slug": "legal",
              "description": "合同智能审查、合规风险校验、法律检索与文书生成、纠纷处理",
              "rate_limit_rpm": 200, "budget_cap_usd": 200},
    "hr": {"name": "人力资源部", "slug": "hr",
           "description": "智能招聘人岗匹配、个性化培训、党建辅助、人力数据分析",
           "rate_limit_rpm": 200, "budget_cap_usd": 200},
    "it": {"name": "信息中心", "slug": "it",
           "description": "AI 基础设施建设、智能运维与安全、智能 IT 服务（底座承载，无对外场景）",
           "rate_limit_rpm": 350, "budget_cap_usd": 400},
}

TEAM_DEFS = {
    "design": [
        {"name": "设计合规组", "slug": "design-compliance", "description": "方案比选、规范合规校验、BIM 辅助"},
    ],
    "cost": [
        {"name": "造价测算组", "slug": "cost-takeoff", "description": "智能算量、造价测算、变更签证对账"},
    ],
    "epc": [
        {"name": "项目管控组", "slug": "epc-control", "description": "进度风险预警、成本管控、现场监管"},
    ],
    "safety": [
        {"name": "安全巡检组", "slug": "safety-inspect", "description": "现场智能巡检、风险分级、安全教育"},
    ],
    "security": [
        {"name": "保密检测组", "slug": "security-scan", "description": "涉密内容检测、文档脱密、行为预警"},
    ],
    "finance": [
        {"name": "核算与票据组", "slug": "fin-accounting", "description": "票据验真、智能核算、预算成本"},
    ],
    "admin": [
        {"name": "公文会议组", "slug": "admin-doc", "description": "公文生成、会议纪要闭环、行政问答"},
    ],
    "legal": [
        {"name": "合同审查组", "slug": "legal-contract", "description": "合同智能审查、合规校验、文书生成"},
    ],
    "hr": [
        {"name": "招聘组", "slug": "hr-recruiting", "description": "简历筛选、人岗匹配、录用"},
        {"name": "培训与人事组", "slug": "hr-ops", "description": "培训发展、人事事务、薪酬考勤"},
    ],
    "it": [
        {"name": "系统运维组", "slug": "it-infra", "description": "基础设施、网络、信息安全"},
        {"name": "AI 应用组", "slug": "it-ai", "description": "Agent / RAG / 工具接入"},
    ],
}

# 11 用户——username 非邮箱形式，密码统一 12345678
USER_DEFS = [
    {"username": "admin", "display_name": "组织管理员", "role": "admin",
     "dept_slug": None, "team_slug": None, "scenario": "管理端配置"},
    {"username": "it-specialist", "display_name": "IT AI 应用专员", "role": "member",
     "dept_slug": "it", "team_slug": "it-ai", "scenario": "平台运维（非对外场景）"},
    {"username": "des-engineer", "display_name": "设计合规工程师", "role": "member",
     "dept_slug": "design", "team_slug": "design-compliance", "scenario": "DES-01 设计方案比选与合规校验"},
    {"username": "cost-estimator", "display_name": "造价工程师", "role": "member",
     "dept_slug": "cost", "team_slug": "cost-takeoff", "scenario": "QTO-01 智能算量与造价测算"},
    {"username": "epc-manager", "display_name": "EPC 项目经理", "role": "member",
     "dept_slug": "epc", "team_slug": "epc-control", "scenario": "EPC-01 项目进度风险与成本管控"},
    {"username": "saf-inspector", "display_name": "安全巡检工程师", "role": "member",
     "dept_slug": "safety", "team_slug": "safety-inspect", "scenario": "SAF-01 施工现场安全智能识别"},
    {"username": "sec-officer", "display_name": "保密专员", "role": "member",
     "dept_slug": "security", "team_slug": "security-scan", "scenario": "SEC-01 涉密检测与文档脱密"},
    {"username": "fin-accountant", "display_name": "财务会计", "role": "member",
     "dept_slug": "finance", "team_slug": "fin-accounting", "scenario": "FIN-01 票据识别审核与智能核算"},
    {"username": "admin-officer", "display_name": "行政专员", "role": "member",
     "dept_slug": "admin", "team_slug": "admin-doc", "scenario": "ADM-01 公文生成与会议纪要闭环"},
    {"username": "leg-counsel", "display_name": "法务专员", "role": "member",
     "dept_slug": "legal", "team_slug": "legal-contract", "scenario": "LEG-01 合同智能审查与履约风险校验"},
    {"username": "hr-recruiter", "display_name": "招聘专员", "role": "member",
     "dept_slug": "hr", "team_slug": "hr-recruiting", "scenario": "HR-01 智能招聘与人岗匹配"},
    {"username": "it-infra", "display_name": "IT 运维专员", "role": "member",
     "dept_slug": "it", "team_slug": "it-infra", "scenario": "IT 运维（非对外场景）"},
]

# LLM 提供商（与 agileac/agilesteel/agilestationery 一致，部署后替换 api_key + 用 README §3 SQL 同步真实 key）
PROVIDER_DEFS = [
    {
        "name": "Anthropic 官方", "provider_type": "anthropic",
        "base_url": "https://api.anthropic.com", "api_key": "demo-provider-key-not-a-secret",
        "priority": 100, "weight": 1, "timeout_seconds": 120, "max_retries": 2,
        "supported_models": ["claude-opus-4", "claude-sonnet-4", "claude-haiku-4"], "config": {},
    },
    {
        "name": "OpenAI 官方", "provider_type": "openai",
        "base_url": "https://api.openai.com/v1", "api_key": "sk-PRESET-REPLACE-ME",
        "priority": 90, "weight": 1, "timeout_seconds": 120, "max_retries": 2,
        "supported_models": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo"], "config": {},
    },
    {
        "name": "DeepSeek", "provider_type": "custom",
        "base_url": "https://api.deepseek.com/v1", "api_key": "sk-PRESET-REPLACE-ME",
        "priority": 70, "weight": 2, "timeout_seconds": 120, "max_retries": 2,
        "supported_models": ["deepseek-chat", "deepseek-reasoner"],
        "config": {"auth_header": "Authorization", "auth_scheme": "Bearer"},
    },
    {
        "name": "智谱 AI", "provider_type": "custom",
        "base_url": "https://open.bigmodel.cn/api/paas/v4", "api_key": "PRESET-REPLACE-ME",
        "priority": 80, "weight": 2, "timeout_seconds": 120, "max_retries": 2,
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

# API Key（1 组织级 + 团队级）
APIKEY_DEFS = [
    {"key_name": "星途勘探 默认 Key（组织级，demo 用）",
     "scope_type": "organization", "department_slug": None, "team_slug": None,
     "allowed_models": [], "rate_limit_rpm": 300, "budget_cap_usd": 300},
    {"key_name": "设计合规组 Key", "scope_type": "team",
     "department_slug": "design", "team_slug": "design-compliance",
     "allowed_models": ["claude-sonnet-4", "gpt-4o-mini", "glm-5.2"],
     "rate_limit_rpm": 60, "budget_cap_usd": 80},
    {"key_name": "造价测算组 Key", "scope_type": "team",
     "department_slug": "cost", "team_slug": "cost-takeoff",
     "allowed_models": ["claude-sonnet-4", "glm-5.2"],
     "rate_limit_rpm": 60, "budget_cap_usd": 80},
    {"key_name": "项目管控组 Key", "scope_type": "team",
     "department_slug": "epc", "team_slug": "epc-control",
     "allowed_models": ["claude-sonnet-4", "glm-5.2"],
     "rate_limit_rpm": 60, "budget_cap_usd": 80},
    {"key_name": "安全巡检组 Key", "scope_type": "team",
     "department_slug": "safety", "team_slug": "safety-inspect",
     "allowed_models": ["claude-sonnet-4", "glm-5.2"],
     "rate_limit_rpm": 60, "budget_cap_usd": 80},
    {"key_name": "保密检测组 Key", "scope_type": "team",
     "department_slug": "security", "team_slug": "security-scan",
     "allowed_models": ["claude-sonnet-4", "glm-5.2"],
     "rate_limit_rpm": 60, "budget_cap_usd": 80},
    {"key_name": "核算与票据组 Key", "scope_type": "team",
     "department_slug": "finance", "team_slug": "fin-accounting",
     "allowed_models": ["claude-sonnet-4", "glm-5.2"],
     "rate_limit_rpm": 40, "budget_cap_usd": 60},
    {"key_name": "公文会议组 Key", "scope_type": "team",
     "department_slug": "admin", "team_slug": "admin-doc",
     "allowed_models": ["claude-sonnet-4", "glm-5.2"],
     "rate_limit_rpm": 40, "budget_cap_usd": 60},
    {"key_name": "合同审查组 Key", "scope_type": "team",
     "department_slug": "legal", "team_slug": "legal-contract",
     "allowed_models": ["claude-sonnet-4", "glm-5.2"],
     "rate_limit_rpm": 40, "budget_cap_usd": 60},
    {"key_name": "招聘组 Key", "scope_type": "team",
     "department_slug": "hr", "team_slug": "hr-recruiting",
     "allowed_models": ["claude-sonnet-4", "glm-5.2"],
     "rate_limit_rpm": 40, "budget_cap_usd": 60},
    {"key_name": "培训与人事组 Key", "scope_type": "team",
     "department_slug": "hr", "team_slug": "hr-ops",
     "allowed_models": ["claude-sonnet-4", "glm-5.2"],
     "rate_limit_rpm": 40, "budget_cap_usd": 60},
    {"key_name": "系统运维组 Key", "scope_type": "team",
     "department_slug": "it", "team_slug": "it-infra",
     "allowed_models": ["claude-sonnet-4", "glm-5.2"],
     "rate_limit_rpm": 60, "budget_cap_usd": 80},
    {"key_name": "AI 应用组 Key", "scope_type": "team",
     "department_slug": "it", "team_slug": "it-ai",
     "allowed_models": ["claude-sonnet-4", "gpt-4o-mini", "glm-5.2"],
     "rate_limit_rpm": 60, "budget_cap_usd": 80},
]


async def _get_org_by_slug(db: AsyncSession, slug: str) -> Organization | None:
    result = await db.execute(
        select(Organization).where(Organization.slug == slug, Organization.deleted_at.is_(None))
    )
    return result.scalar_one_or_none()


async def _get_dept_by_slug(db: AsyncSession, org_id, slug: str) -> Department | None:
    result = await db.execute(
        select(Department).where(
            Department.organization_id == org_id, Department.slug == slug,
            Department.deleted_at.is_(None),
        )
    )
    return result.scalar_one_or_none()


async def _get_team_by_slug(db: AsyncSession, dept_id, slug: str) -> Team | None:
    result = await db.execute(
        select(Team).where(Team.department_id == dept_id, Team.slug == slug, Team.deleted_at.is_(None))
    )
    return result.scalar_one_or_none()


async def seed() -> dict:
    stats = {
        "organization": 0, "department": 0, "team": 0, "user": 0, "user_password_set": 0,
        "provider": 0, "routing_policy": 0, "api_key": 0,
    }
    created_api_keys: list[tuple[str, str]] = []

    async with async_session_factory() as db:
        org = await _get_org_by_slug(db, ORG_DEF["slug"])
        if org is None:
            org = Organization(**ORG_DEF)
            db.add(org)
            await db.flush()
            stats["organization"] += 1
            logger.info("seed_org_created", slug=org.slug)
        else:
            org.name = ORG_DEF["name"]; org.description = ORG_DEF["description"]
            org.rate_limit_rpm = ORG_DEF["rate_limit_rpm"]; org.rate_limit_tpm = ORG_DEF["rate_limit_tpm"]
            org.budget_cap_usd = ORG_DEF["budget_cap_usd"]; org.settings = ORG_DEF["settings"]
            logger.info("seed_org_updated", slug=org.slug)

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

        pwd_hash = hash_password(DEFAULT_PASSWORD)
        for udef in USER_DEFS:
            result = await db.execute(
                select(User).where(
                    User.organization_id == org.id, User.username == udef["username"],
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
                    organization_id=org.id, username=udef["username"],
                    display_name=udef["display_name"], role=udef["role"],
                    department_id=dept_id, team_id=team_id, password_hash=pwd_hash,
                )
                db.add(user)
                await db.flush()
                stats["user"] += 1
                stats["user_password_set"] += 1
                logger.info("seed_user_created", username=udef["username"], scenario=udef["scenario"])
            else:
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

        provider_by_name: dict[str, LlmProvider] = {}
        for pdef in PROVIDER_DEFS:
            result = await db.execute(
                select(LlmProvider).where(
                    LlmProvider.organization_id == org.id, LlmProvider.name == pdef["name"],
                    LlmProvider.deleted_at.is_(None),
                )
            )
            prov = result.scalar_one_or_none()
            if prov is None:
                prov = LlmProvider(
                    organization_id=org.id, name=pdef["name"],
                    provider_type=pdef["provider_type"], base_url=pdef["base_url"],
                    api_key_encrypted=encrypt_provider_api_key(pdef["api_key"]),
                    api_key_version=1, is_active=True,
                    priority=pdef["priority"], weight=pdef["weight"],
                    timeout_seconds=pdef["timeout_seconds"], max_retries=pdef["max_retries"],
                    supported_models=pdef["supported_models"], health_status="unknown",
                    config=pdef["config"],
                )
                db.add(prov)
                await db.flush()
                stats["provider"] += 1
                logger.info("seed_provider_created", name=pdef["name"])
            provider_by_name[pdef["name"]] = prov

        for rdef in ROUTING_DEFS:
            result = await db.execute(
                select(RoutingPolicy).where(
                    RoutingPolicy.organization_id == org.id, RoutingPolicy.name == rdef["name"],
                    RoutingPolicy.deleted_at.is_(None),
                )
            )
            if result.scalar_one_or_none() is None:
                provider_ids = [str(provider_by_name[n].id) for n in rdef["provider_names"] if n in provider_by_name]
                db.add(RoutingPolicy(
                    organization_id=org.id, name=rdef["name"], description=rdef["description"],
                    model_pattern=rdef["model_pattern"], strategy=rdef["strategy"],
                    provider_ids=provider_ids, is_default=rdef["is_default"],
                ))
                await db.flush()
                stats["routing_policy"] += 1
                logger.info("seed_routing_created", name=rdef["name"])

        for kdef in APIKEY_DEFS:
            result = await db.execute(
                select(ApiKey).where(
                    ApiKey.organization_id == org.id, ApiKey.key_name == kdef["key_name"],
                    ApiKey.revoked_at.is_(None),
                ).order_by(ApiKey.created_at.desc())
            )
            if list(result.scalars().all()):
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
                key_prefix=key_prefix, key_hash=key_hash, key_encrypted=encrypt_api_key(full_key),
                key_name=kdef["key_name"], scope_type=scope, organization_id=org.id,
                department_id=dept_id, team_id=team_id,
                allowed_models=kdef["allowed_models"], rate_limit_rpm=kdef["rate_limit_rpm"],
                budget_cap_usd=kdef["budget_cap_usd"], is_active=True,
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
    print("「星途勘探」AI 应用 demo 组织数据导入完成（仅统计新增；已存在则跳过）")
    print("-" * 60)
    labels = {
        "organization": "组织", "department": "部门", "team": "团队", "user": "用户",
        "user_password_set": "  ├ 密码回填", "provider": "LLM 提供商",
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
