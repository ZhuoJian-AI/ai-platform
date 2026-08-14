"""导入「星途服装」AI 应用 demo 组织数据（服装企业组织架构 + LLM 路由 + API Key）。

幂等：按 slug / name / username 去重，已存在则跳过，可安全重复执行。
覆盖：组织 → 部门 → 团队 → 用户 → LLM 提供商 → 模型别名 → 路由策略 → 示例 API Key。

组织架构依据典型服装企业部门设置：
    总经办 / 设计部 / 开发部 / 商品部 / 供应链部 / 品控部 / 生产部 / 财务部 / 人力资源部 / 信息技术部

与 mock 多租户对接：组织级 API Key 供后续「星途连接器」绑定到 PLM/SCM/ERP/MES/CRM
各自的 starclothing 演示 key（连接器 auth_config 内直接持有 mock key）。本脚本只生成
平台侧 API Key（用于调 LLM Router / Terminal Agent），不重复生成 mock 侧 key。

用法:
    # 容器内（docker cp 后）：
    docker cp demo/starclothing/scripts/seed_starclothing_apparel.py ai_infra_backend:/app/scripts/
    docker exec ai_infra_backend python scripts/seed_starclothing_apparel.py

    # 本地 dev（在 repo 根目录）：
    python demo/starclothing/scripts/seed_starclothing_apparel.py
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path

# 兼容两种位置：容器内 /app/scripts/ → backend=/app；本地 demo/starclothing/scripts/ → backend=repo/llm_router/backend
_HERE = Path(__file__).resolve()
_BACKEND_DIR = _HERE.parent.parent
if not (_BACKEND_DIR / "app" / "database.py").exists():
    _BACKEND_DIR = _HERE.parents[3] / "llm_router" / "backend"
sys.path.insert(0, str(_BACKEND_DIR))

import structlog  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

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


# ───────────────────────── 预置数据定义 ─────────────────────────

ORG_DEF = {
    "name": "星途服装",
    "slug": "starclothing",
    "description": "服装企业 AI 应用 demo 组织——产品全流程监管 / 数字面料库 / 缺陷闭环 / 供应链协同",
    "rate_limit_rpm": 1200,
    "rate_limit_tpm": 600_000,
    "budget_cap_usd": 2000,
    "budget_cap_tokens": 100_000_000,
    "settings": {"locale": "zh-CN", "industry": "apparel"},
}

# slug -> 部门定义（依据服装企业典型部门设置）
DEPARTMENT_DEFS = {
    "executive": {
        "name": "总经办",
        "slug": "executive",
        "description": "经营决策、战略规划与跨部门协调",
        "rate_limit_rpm": 200,
        "budget_cap_usd": 300,
    },
    "design": {
        "name": "设计部",
        "slug": "design",
        "description": "款式企划、面料开发与样衣设计",
        "rate_limit_rpm": 250,
        "budget_cap_usd": 350,
    },
    "dev": {
        "name": "开发部",
        "slug": "dev",
        "description": "打样跟单、工艺开发与新品试制",
        "rate_limit_rpm": 300,
        "budget_cap_usd": 350,
    },
    "merch": {
        "name": "商品部",
        "slug": "merch",
        "description": "商品企划、订单管理与生命周期",
        "rate_limit_rpm": 200,
        "budget_cap_usd": 200,
    },
    "supply": {
        "name": "供应链部",
        "slug": "supply",
        "description": "采购、跟单、对账与供应商管理",
        "rate_limit_rpm": 250,
        "budget_cap_usd": 250,
    },
    "quality": {
        "name": "品控部",
        "slug": "quality",
        "description": "来料 / 制程 / 出货全流程品控与 AQL 检验",
        "rate_limit_rpm": 200,
        "budget_cap_usd": 200,
    },
    "production": {
        "name": "生产部",
        "slug": "production",
        "description": "排产计划、裁剪车缝印花包装车间",
        "rate_limit_rpm": 300,
        "budget_cap_usd": 300,
    },
    "finance": {
        "name": "财务部",
        "slug": "finance",
        "description": "应付应收核算与成本管理",
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
        "description": "系统运维与 AI 应用落地",
        "rate_limit_rpm": 300,
        "budget_cap_usd": 350,
    },
}

# dept_slug -> [团队定义]
TEAM_DEFS = {
    "executive": [
        {"name": "总裁办", "slug": "exec-office", "description": "战略与高管支持"},
    ],
    "design": [
        {"name": "款式设计组", "slug": "style-design", "description": "款式企划与设计"},
        {"name": "面料开发组", "slug": "fabric-dev", "description": "面料选型与可行性"},
    ],
    "dev": [
        {"name": "打样跟单组", "slug": "sampling", "description": "打样进度跟踪"},
        {"name": "工艺工程组", "slug": "process-eng", "description": "工艺路线与工时"},
    ],
    "merch": [
        {"name": "商品企划组", "slug": "merch-plan", "description": "季节企划与款式定价"},
        {"name": "订单管理组", "slug": "order-mgmt", "description": "大货订单与交期跟踪"},
    ],
    "supply": [
        {"name": "采购组", "slug": "procurement", "description": "面料辅料采购"},
        {"name": "跟单对账组", "slug": "follow-recon", "description": "跟单、单据对账与价格台账"},
    ],
    "quality": [
        {"name": "来料检验组", "slug": "iqc", "description": "IQC 面料辅料检验"},
        {"name": "制程检验组", "slug": "ipqc", "description": "IPQC 车缝/印花巡检"},
        {"name": "出货检验组", "slug": "oqc", "description": "OQC 成品出货检验"},
    ],
    "production": [
        {"name": "排产计划组", "slug": "planning", "description": "PMC 排产与补单节奏"},
        {"name": "裁剪车间", "slug": "cutting", "description": "自动裁床与裁片配送"},
        {"name": "车缝车间", "slug": "sewing", "description": "平车/包缝/特种车缝"},
        {"name": "后整包装车间", "slug": "finishing", "description": "整烫、折叠、入箱"},
    ],
    "finance": [
        {"name": "应付组", "slug": "payables", "description": "供应商应付核算"},
        {"name": "应收组", "slug": "receivables", "description": "客户应收与逾期管理"},
    ],
    "hr": [
        {"name": "招聘培训组", "slug": "recruiting-training", "description": "人才引进与培训"},
        {"name": "薪酬绩效组", "slug": "compensation", "description": "薪酬与绩效"},
    ],
    "it": [
        {"name": "系统运维组", "slug": "infra-ops", "description": "基础设施与网络"},
        {"name": "AI 应用组", "slug": "ai-apps", "description": "Agent / RAG / 工具接入落地"},
    ],
}

# 用户定义（username 在组织内唯一；role: admin / member）
USER_DEFS = [
    {"username": "admin@starclothing.demo", "display_name": "组织管理员", "role": "admin"},
    {"username": "ceo@starclothing.demo", "display_name": "总经理", "role": "admin"},
    {"username": "design-lead@starclothing.demo", "display_name": "设计总监", "role": "member"},
    {"username": "dev-lead@starclothing.demo", "display_name": "开发部长", "role": "member"},
    {"username": "merch-lead@starclothing.demo", "display_name": "商品总监", "role": "member"},
    {"username": "supply-lead@starclothing.demo", "display_name": "供应链部长", "role": "member"},
    {"username": "qc-lead@starclothing.demo", "display_name": "品控部长", "role": "member"},
    {"username": "prod-lead@starclothing.demo", "display_name": "生产部长", "role": "member"},
    {"username": "finance-lead@starclothing.demo", "display_name": "财务总监", "role": "member"},
    {"username": "hr-lead@starclothing.demo", "display_name": "人力资源部长", "role": "member"},
    {"username": "it-lead@starclothing.demo", "display_name": "信息技术部长", "role": "member"},
    {"username": "designer@starclothing.demo", "display_name": "款式设计师", "role": "member"},
    {"username": "fabric-buyer@starclothing.demo", "display_name": "面料采购员", "role": "member"},
    {"username": "sampling-merch@starclothing.demo", "display_name": "打样跟单员", "role": "member"},
    {"username": "planner@starclothing.demo", "display_name": "排产计划员", "role": "member"},
    {"username": "qc@starclothing.demo", "display_name": "QC 检验员", "role": "member"},
    {"username": "buyer@starclothing.demo", "display_name": "辅料采购员", "role": "member"},
    {"username": "recon@starclothing.demo", "display_name": "对账会计", "role": "member"},
]

# LLM 提供商（与 minrui 同构，api_key 为占位符，部署后请替换）
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

ROUTING_DEFS = [
    {
        "name": "Claude 路由（主）",
        "description": "claude-* 命中走 Anthropic",
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
]

# 示例 API Key（组织级 + 团队级；明文会在脚本结束时打印一次）
# 组织级 Key 供 demo 脚本调用 Terminal Agent；团队级 Key 演示作用域隔离。
APIKEY_DEFS = [
    {
        "key_name": "星途服装 默认 Key（组织级，demo 用）",
        "scope_type": "organization",
        "department_slug": None,
        "team_slug": None,
        "allowed_models": [],
        "rate_limit_rpm": 200,
        "budget_cap_usd": 200,
    },
    {
        "key_name": "AI 应用组 Key（团队级）",
        "scope_type": "team",
        "department_slug": "it",
        "team_slug": "ai-apps",
        "allowed_models": ["claude-*", "gpt-4o-mini", "deepseek-chat"],
        "rate_limit_rpm": 60,
        "budget_cap_usd": 80,
    },
    {
        "key_name": "打样跟单组 Key（团队级）",
        "scope_type": "team",
        "department_slug": "dev",
        "team_slug": "sampling",
        "allowed_models": ["claude-sonnet-4", "gpt-4o-mini"],
        "rate_limit_rpm": 40,
        "budget_cap_usd": 40,
    },
    {
        "key_name": "采购组 Key（团队级）",
        "scope_type": "team",
        "department_slug": "supply",
        "team_slug": "procurement",
        "allowed_models": ["claude-sonnet-4", "deepseek-chat"],
        "rate_limit_rpm": 40,
        "budget_cap_usd": 40,
    },
    {
        "key_name": "排产计划组 Key（团队级）",
        "scope_type": "team",
        "department_slug": "production",
        "team_slug": "planning",
        "allowed_models": ["claude-sonnet-4", "gpt-4o-mini"],
        "rate_limit_rpm": 40,
        "budget_cap_usd": 40,
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
        "organization": 0, "department": 0, "team": 0, "user": 0,
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
            # 兼容历史名「星图服装」→ 改名为「星途服装」
            if org.name != ORG_DEF["name"]:
                logger.info("seed_org_renamed", slug=org.slug, old=org.name, new=ORG_DEF["name"])
                org.name = ORG_DEF["name"]
            if org.description != ORG_DEF["description"]:
                org.description = ORG_DEF["description"]
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
            # 兼容历史名「星图服装 默认 Key...」→ 改名为「星途服装 默认 Key...」
            legacy_name = kdef["key_name"].replace("星途服装", "星图服装")
            result = await db.execute(
                select(ApiKey).where(
                    ApiKey.organization_id == org.id,
                    ApiKey.key_name.in_([kdef["key_name"], legacy_name]),
                    ApiKey.revoked_at.is_(None),
                ).order_by(ApiKey.created_at.desc())
            )
            rows = list(result.scalars().all())
            if rows:
                # 保留最早创建的一把（其明文用户最可能已保存），改名对齐；其余重复项吊销
                keep = min(rows, key=lambda k: k.created_at)
                dupes = [k for k in rows if k.id != keep.id]
                if keep.key_name != kdef["key_name"]:
                    logger.info("seed_apikey_renamed", old=keep.key_name, new=kdef["key_name"])
                    keep.key_name = kdef["key_name"]
                for d in dupes:
                    logger.info("seed_apikey_dedup_revoked", key_name=d.key_name, prefix=d.key_prefix)
                    d.is_active = False
                    d.revoked_at = datetime.now(UTC)
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
    print("「星途服装」AI 应用 demo 组织数据导入完成（仅统计新增；已存在则跳过）")
    print("-" * 60)
    labels = {
        "organization": "组织", "department": "部门", "team": "团队", "user": "用户",
        "provider": "LLM 提供商",
        "routing_policy": "路由策略", "api_key": "示例 API Key",
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
