"""DLP Rule service — CRUD, rule testing, and rule-library lookup."""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dlp.engine import DLPEngine
from app.dlp.patterns import ALL_BUILTIN_RULES
from app.models.dlp_rule import DlpRule
from app.schemas.dlp_rule import DlpRuleCreate, DlpRuleLibraryEntry, DlpRuleUpdate


_BUILTIN_BY_NAME: dict[str, dict] = {r["name"]: r for r in ALL_BUILTIN_RULES}


def list_rule_library() -> list[DlpRuleLibraryEntry]:
    """规则库（代码内置、只读）：返回全部预置规则定义。"""
    return [
        DlpRuleLibraryEntry(
            name=r["name"],
            rule_type=r["rule_type"],
            pattern=r["pattern"],
            severity=r["severity"],
            action=r["action"],
            direction=r["direction"],
            description=f"内置规则 — {r['name']}",
        )
        for r in ALL_BUILTIN_RULES
    ]


async def seed_builtin_dlp_rules(db: AsyncSession, org_id: UUID) -> None:
    """为指定组织播种全部内置规则，作为组织级规则（scope_type='organization'）。

    不存在「全局规则」概念——每个组织各自持有一份内置规则副本，组织管理员可启停。
    默认 is_active=True、priority=0、scope_id=None。同名同组织未软删规则跳过（幂等，
    供新建组织与回填脚本共用）。
    """
    org_id_str = str(org_id)
    for r in ALL_BUILTIN_RULES:
        exists = await _conflicting_active(db, org_id_str, "organization", None, r["name"])
        if exists:
            continue
        db.add(
            DlpRule(
                organization_id=org_id_str,
                name=r["name"],
                description=f"内置规则 — {r['name']}",
                rule_type=r["rule_type"],
                pattern=r["pattern"],
                severity=r["severity"],
                action=r["action"],
                direction=r["direction"],
                scope_type="organization",
                scope_id=None,
                is_active=True,
                priority=0,
            )
        )
    await db.flush()


async def _conflicting_active(
    db: AsyncSession,
    org_id: UUID | str,
    scope_type: str,
    scope_id: str | None,
    name: str,
    exclude_id: UUID | None = None,
) -> bool:
    """同一 scope 下是否已有同名未软删规则（去重）。规则一律归属到某组织。"""
    conds = [
        DlpRule.deleted_at.is_(None),
        DlpRule.scope_type == scope_type,
        DlpRule.name == name,
        DlpRule.organization_id == str(org_id),
        DlpRule.scope_id == (str(scope_id) if scope_id else None),
    ]
    if exclude_id is not None:
        conds.append(DlpRule.id != exclude_id)
    result = await db.execute(select(DlpRule.id).where(*conds).limit(1))
    return result.first() is not None


async def create_dlp_rule(db: AsyncSession, org_id: UUID, data: DlpRuleCreate) -> DlpRule:
    """从规则库添加一条规则到指定 scope。

    library_name 在规则库中查找；name/rule_type/pattern/description 由库拷入（不可由调用方指定）。
    同 scope 同名规则去重 → 409。
    """
    builtin = _BUILTIN_BY_NAME.get(data.library_name)
    if builtin is None:
        raise HTTPException(status_code=404, detail=f"Rule library has no entry '{data.library_name}'")

    scope_id = str(data.scope_id) if data.scope_id else None
    if await _conflicting_active(db, org_id, data.scope_type, scope_id, builtin["name"]):
        raise HTTPException(status_code=409, detail="该范围下已存在同名规则，请勿重复添加")

    rule = DlpRule(
        organization_id=str(org_id),
        name=builtin["name"],
        description=f"内置规则 — {builtin['name']}",
        rule_type=builtin["rule_type"],
        pattern=builtin["pattern"],
        severity=data.severity,
        action=data.action,
        direction=data.direction,
        scope_type=data.scope_type,
        scope_id=scope_id,
        is_active=data.is_active,
        priority=data.priority,
    )
    db.add(rule)
    await db.flush()
    return rule


async def list_dlp_rules(db: AsyncSession, org_id: UUID) -> list[DlpRule]:
    result = await db.execute(
        select(DlpRule).where(
            DlpRule.organization_id == org_id,
            DlpRule.deleted_at.is_(None),
        ).order_by(DlpRule.priority.desc())
    )
    return list(result.scalars().all())


async def get_dlp_rule(db: AsyncSession, rule_id: UUID) -> DlpRule | None:
    result = await db.execute(
        select(DlpRule).where(DlpRule.id == rule_id, DlpRule.deleted_at.is_(None))
    )
    return result.scalar_one_or_none()


async def update_dlp_rule(db: AsyncSession, rule: DlpRule, data: DlpRuleUpdate) -> DlpRule:
    """配置规则：仅 6 项可改（severity/action/direction/scope/priority/is_active）。

    name/rule_type/pattern 不在 schema 中，不可改。改 scope 后做同名去重检查 → 409。
    """
    changes = data.model_dump(exclude_unset=True)
    new_scope_type = changes.get("scope_type", rule.scope_type)
    new_scope_id = changes.get("scope_id", rule.scope_id)
    new_scope_id_str = str(new_scope_id) if new_scope_id else None
    # scope 变化时检查目标 scope 是否已有同名规则
    if ("scope_type" in changes or "scope_id" in changes) and await _conflicting_active(
        db, rule.organization_id or "", new_scope_type, new_scope_id_str, rule.name, exclude_id=rule.id
    ):
        raise HTTPException(status_code=409, detail="目标范围下已存在同名规则")

    for field, value in changes.items():
        setattr(rule, field, value)
    await db.flush()
    await db.refresh(rule)
    return rule


async def soft_delete_dlp_rule(db: AsyncSession, rule: DlpRule) -> None:
    rule.deleted_at = datetime.now(UTC)
    await db.flush()


async def test_dlp_rule(rule: DlpRule, text: str, direction: str) -> dict:
    """测试单个 DLP 规则对文本的匹配结果。"""
    engine = DLPEngine(rules=[rule])
    result = await engine.scan(text, direction=direction)
    return {
        "matched": result.blocked or bool(result.violations),
        "violations": [
            {
                "rule_id": str(v.rule_id),
                "rule_name": v.rule_name,
                "severity": v.severity,
                "matched_text_redacted": v.matched_text_redacted,
            }
            for v in result.violations
        ],
        "redacted_text": result.redacted_text,
    }
