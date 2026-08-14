"""导入「敏睿制造」POC 演示数据（生产制造企业组织架构）。

幂等：按 slug / name / username 去重，已存在则跳过，可安全重复执行。
覆盖：组织 → 部门 → 团队 → 用户 → LLM 提供商 → 模型别名 → 路由策略 → 示例 API Key。

组织架构依据典型生产制造企业部门设置：
    总经办 / 研发部 / 生产部 / 质量部 / 供应链部 / 销售部 / 财务部 / 人力资源部 / 信息技术部

用法:
    cd llm_router/backend
    python scripts/seed_minrui_manufacturing.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# 确保能把 `app` 包导入（脚本从 backend/ 目录运行）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session_factory
from app.models.api_key import ApiKey
from app.models.department import Department
from app.models.llm_provider import LlmProvider
from app.models.organization import Organization
from app.models.routing_policy import RoutingPolicy
from app.models.team import Team
from app.models.user import User
from app.utils.crypto import encrypt_api_key, encrypt_provider_api_key, generate_api_key, hash_api_key

logger = structlog.get_logger()


# ───────────────────────── 预置数据定义 ─────────────────────────

ORG_DEF = {
    "name": "敏睿制造",
    "slug": "minrui",
    "description": "生产制造企业 POC 演示组织——用于体验 LLM Router 在制造行业的组织架构、路由与安全围栏能力",
    "rate_limit_rpm": 1200,
    "rate_limit_tpm": 600_000,
    "budget_cap_usd": 2000,
    "budget_cap_tokens": 100_000_000,
    "settings": {"locale": "zh-CN", "industry": "manufacturing"},
}

# slug -> 部门定义（依据生产制造企业典型部门设置）
DEPARTMENT_DEFS = {
    "executive": {
        "name": "总经办",
        "slug": "executive",
        "description": "经营决策、战略规划与跨部门协调",
        "rate_limit_rpm": 200,
        "budget_cap_usd": 300,
    },
    "rnd": {
        "name": "研发部",
        "slug": "rnd",
        "description": "产品研发与工艺技术",
        "rate_limit_rpm": 400,
        "budget_cap_usd": 500,
    },
    "production": {
        "name": "生产部",
        "slug": "production",
        "description": "制造排产、机加工与装配",
        "rate_limit_rpm": 300,
        "budget_cap_usd": 300,
    },
    "quality": {
        "name": "质量部",
        "slug": "quality",
        "description": "来料 / 制程 / 出货全流程品控",
        "rate_limit_rpm": 200,
        "budget_cap_usd": 200,
    },
    "supply-chain": {
        "name": "供应链部",
        "slug": "supply-chain",
        "description": "采购与仓储物流",
        "rate_limit_rpm": 200,
        "budget_cap_usd": 200,
    },
    "sales": {
        "name": "销售部",
        "slug": "sales",
        "description": "市场拓展与客户经营",
        "rate_limit_rpm": 250,
        "budget_cap_usd": 250,
    },
    "finance": {
        "name": "财务部",
        "slug": "finance",
        "description": "会计核算与成本管理",
        "rate_limit_rpm": 150,
        "budget_cap_usd": 150,
    },
    "hr": {
        "name": "人力资源部",
        "slug": "hr",
        "description": "招聘培训与薪酬绩效",
        "rate_limit_rpm": 150,
        "budget_cap_usd": 150,
    },
    "it": {
        "name": "信息技术部",
        "slug": "it",
        "description": "系统运维与数字化转型",
        "rate_limit_rpm": 300,
        "budget_cap_usd": 350,
    },
}

# dept_slug -> [团队定义]
TEAM_DEFS = {
    "executive": [
        {"name": "总裁办", "slug": "exec-office", "description": "战略与高管支持"},
    ],
    "rnd": [
        {"name": "产品研发组", "slug": "product-rnd", "description": "新产品设计与样机"},
        {"name": "工艺工程组", "slug": "process-eng", "description": "工艺路线与工装夹具"},
    ],
    "production": [
        {"name": "生产计划组", "slug": "planning", "description": "PMC 排产与物料齐套"},
        {"name": "机加工车间", "slug": "machining", "description": "数控加工与表面处理"},
        {"name": "装配车间", "slug": "assembly", "description": "总装调试与试运行"},
    ],
    "quality": [
        {"name": "来料检验组", "slug": "iqc", "description": "IQC 进料检验"},
        {"name": "制程检验组", "slug": "ipqc", "description": "IPQC 过程巡检"},
        {"name": "出货检验组", "slug": "oqc", "description": "OQC 成品出货检验"},
    ],
    "supply-chain": [
        {"name": "采购组", "slug": "procurement", "description": "供应商管理与物料采购"},
        {"name": "仓储物流组", "slug": "warehouse-logistics", "description": "原料仓 / 成品仓与发运"},
    ],
    "sales": [
        {"name": "国内销售组", "slug": "domestic-sales", "description": "国内市场与渠道"},
        {"name": "海外销售组", "slug": "overseas-sales", "description": "海外市场与外贸"},
    ],
    "finance": [
        {"name": "会计组", "slug": "accounting", "description": "总账与报表"},
        {"name": "成本核算组", "slug": "costing", "description": "标准成本与差异分析"},
    ],
    "hr": [
        {"name": "招聘培训组", "slug": "recruiting-training", "description": "人才引进与培训发展"},
        {"name": "薪酬绩效组", "slug": "compensation", "description": "薪酬福利与绩效考核"},
    ],
    "it": [
        {"name": "系统运维组", "slug": "infra-ops", "description": "基础设施与网络安全"},
        {"name": "数字化转型组", "slug": "digital-transformation", "description": "MES / ERP 与 AI 应用落地"},
    ],
}

# 用户定义（username 在组织内唯一；role: admin / member）
USER_DEFS = [
    {"username": "admin@minrui.demo", "display_name": "组织管理员", "role": "admin"},
    {"username": "ceo@minrui.demo", "display_name": "总经理", "role": "admin"},
    {"username": "rnd-lead@minrui.demo", "display_name": "研发总监", "role": "member"},
    {"username": "prod-lead@minrui.demo", "display_name": "生产部长", "role": "member"},
    {"username": "qc-lead@minrui.demo", "display_name": "质量部长", "role": "member"},
    {"username": "scm-lead@minrui.demo", "display_name": "供应链部长", "role": "member"},
    {"username": "sales-lead@minrui.demo", "display_name": "销售总监", "role": "member"},
    {"username": "finance-lead@minrui.demo", "display_name": "财务总监", "role": "member"},
    {"username": "hr-lead@minrui.demo", "display_name": "人力资源部长", "role": "member"},
    {"username": "it-lead@minrui.demo", "display_name": "信息技术部长", "role": "member"},
    {"username": "engineer@minrui.demo", "display_name": "工艺工程师", "role": "member"},
    {"username": "planner@minrui.demo", "display_name": "生产计划员", "role": "member"},
]

# LLM 提供商定义（api_key 为占位符，部署后请在控制台替换为真实密钥）
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
]


# 路由策略：name -> {model_pattern, strategy, provider_names(引用上方), is_default}
ROUTING_DEFS = [
    {
        "name": "Claude 路由（主）",
        "description": "claude-* 命中走 Anthropic，主路由",
        "model_pattern": "claude-*",
        "strategy": "priority",
        "provider_names": ["Anthropic 官方"],
        "is_default": True,
    },
    {
        "name": "GPT 路由",
        "description": "gpt-* 命中走 OpenAI",
        "model_pattern": "gpt-*",
        "strategy": "priority",
        "provider_names": ["OpenAI 官方"],
        "is_default": False,
    },
    {
        "name": "DeepSeek 路由",
        "description": "deepseek-* 命中走 DeepSeek",
        "model_pattern": "deepseek-*",
        "strategy": "priority",
        "provider_names": ["DeepSeek"],
        "is_default": False,
    },
    {
        "name": "OpenAI 兼容容灾",
        "description": "OpenAI 不可用时容灾到 DeepSeek（OpenAI 兼容协议）",
        "model_pattern": "gpt-4o-mini",
        "strategy": "failover",
        "provider_names": ["OpenAI 官方", "DeepSeek"],
        "is_default": False,
    },
]

# 示例 API Key（组织级 / 团队级；明文会在脚本结束时打印一次）
APIKEY_DEFS = [
    {
        "key_name": "敏睿制造 默认 Key（组织级）",
        "scope_type": "organization",
        "department_slug": None,
        "team_slug": None,
        "allowed_models": [],  # 空 = 全部
        "rate_limit_rpm": 120,
        "budget_cap_usd": 100,
    },
    {
        "key_name": "数字化转型组 Key（团队级）",
        "scope_type": "team",
        "department_slug": "it",
        "team_slug": "digital-transformation",
        "allowed_models": ["claude-*", "gpt-4o-mini", "deepseek-chat"],
        "rate_limit_rpm": 60,
        "budget_cap_usd": 50,
    },
    {
        "key_name": "生产计划组 Key（团队级）",
        "scope_type": "team",
        "department_slug": "production",
        "team_slug": "planning",
        "allowed_models": ["claude-sonnet-4", "gpt-4o-mini"],
        "rate_limit_rpm": 40,
        "budget_cap_usd": 30,
    },
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
        "organization": 0,
        "department": 0,
        "team": 0,
        "user": 0,
        "provider": 0,
        "routing_policy": 0,
        "api_key": 0,
    }
    created_api_keys: list[tuple[str, str]] = []  # (key_name, full_key_plaintext)

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
            dept = dept_by_slug[dept_slug]
            for tdef in tdefs:
                team = await _get_team_by_slug(db, dept.id, tdef["slug"])
                if team is None:
                    team = Team(department_id=dept.id, organization_id=org.id, **tdef)
                    db.add(team)
                    await db.flush()
                    stats["team"] += 1
                    logger.info("seed_team_created", slug=tdef["slug"])

        # 4) 用户
        for udef in USER_DEFS:
            result = await db.execute(
                select(User).where(
                    User.organization_id == org.id,
                    User.username == udef["username"],
                    User.deleted_at.is_(None),
                )
            )
            if result.scalar_one_or_none() is None:
                db.add(User(organization_id=org.id, **udef))
                await db.flush()
                stats["user"] += 1
                logger.info("seed_user_created", username=udef["username"])

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
                db.add(
                    RoutingPolicy(
                        organization_id=org.id,
                        name=rdef["name"],
                        description=rdef["description"],
                        model_pattern=rdef["model_pattern"],
                        strategy=rdef["strategy"],
                        provider_ids=provider_ids,
                        is_default=rdef["is_default"],
                    )
                )
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
                )
            )
            if result.scalar_one_or_none() is not None:
                continue

            dept_id = None
            team_id = None
            if kdef["department_slug"]:
                dept_id = dept_by_slug[kdef["department_slug"]].id
            if kdef["team_slug"]:
                # 团队在对应部门下
                dept = dept_by_slug[kdef["department_slug"]]
                team = await _get_team_by_slug(db, dept.id, kdef["team_slug"])
                team_id = team.id if team else None

            scope = kdef["scope_type"]
            full_key, key_prefix, key_hash = generate_api_key(scope)
            db.add(
                ApiKey(
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
                )
            )
            await db.flush()
            stats["api_key"] += 1
            created_api_keys.append((kdef["key_name"], full_key))
            logger.info("seed_apikey_created", key_name=kdef["key_name"], prefix=key_prefix)

        await db.commit()

    return {"stats": stats, "api_keys": created_api_keys}


def _print_report(result: dict) -> None:
    stats = result["stats"]
    print("\n" + "=" * 60)
    print("「敏睿制造」POC 数据导入完成（仅统计新增；已存在则跳过）")
    print("-" * 60)
    labels = {
        "organization": "组织",
        "department": "部门",
        "team": "团队",
        "user": "用户",
        "provider": "LLM 提供商",
        "routing_policy": "路由策略",
        "api_key": "示例 API Key",
    }
    for key, label in labels.items():
        print(f"  {label:<14}: +{stats[key]}")
    print("-" * 60)
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
