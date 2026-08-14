"""导入预置演示数据。

幂等：按 slug / name / username 去重，已存在则跳过，可安全重复执行。
覆盖：组织 → 部门 → 团队 → 用户 → LLM 提供商 → 模型别名 → 路由策略 → 示例 API Key。

用法:
    cd llm_router/backend
    python scripts/seed_preset_data.py
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
    "name": "示例企业 Acme",
    "slug": "acme",
    "description": "预置演示组织——用于体验 LLM Router 的组织架构、路由与安全围栏能力",
    "rate_limit_rpm": 600,
    "rate_limit_tpm": 300_000,
    "budget_cap_usd": 1000,
    "budget_cap_tokens": 50_000_000,
    "settings": {"locale": "zh-CN"},
}

# slug -> 部门定义
DEPARTMENT_DEFS = {
    "eng": {
        "name": "工程部",
        "slug": "eng",
        "description": "负责平台与产品研发",
        "rate_limit_rpm": 300,
        "budget_cap_usd": 600,
    },
    "product": {
        "name": "产品部",
        "slug": "product",
        "description": "负责产品设计、需求与运营",
        "rate_limit_rpm": 150,
        "budget_cap_usd": 200,
    },
}

# dept_slug -> [团队定义]
TEAM_DEFS = {
    "eng": [
        {"name": "平台组", "slug": "platform", "description": "基础设施与网关"},
        {"name": "AI 组", "slug": "ai-research", "description": "模型应用与提示工程"},
    ],
    "product": [
        {"name": "设计组", "slug": "design", "description": "UI/UX 与品牌"},
    ],
}

# 用户定义（username 在组织内唯一）
USER_DEFS = [
    {"username": "admin@acme.demo", "display_name": "组织管理员", "role": "admin"},
    {"username": "alice@acme.demo", "display_name": "Alice", "role": "member"},
    {"username": "bob@acme.demo", "display_name": "Bob", "role": "member"},
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

# 路由策略：name -> {model_pattern, strategy, provider_name(引用上方), is_default}
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

# 示例 API Key（组织级，明文会在脚本结束时打印一次）
APIKEY_DEFS = [
    {
        "key_name": "Acme 默认 Key（组织级）",
        "scope_type": "organization",
        "department_slug": None,
        "team_slug": None,
        "allowed_models": [],  # 空 = 全部
        "rate_limit_rpm": 60,
        "budget_cap_usd": 50,
    },
    {
        "key_name": "AI 组 Key（团队级）",
        "scope_type": "team",
        "department_slug": "eng",
        "team_slug": "ai-research",
        "allowed_models": ["claude-*", "gpt-4o-mini"],
        "rate_limit_rpm": 30,
        "budget_cap_usd": 20,
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
    print("预置数据导入完成（仅统计新增；已存在则跳过）")
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
