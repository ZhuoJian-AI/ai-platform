"""Skill service — CRUD."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.skill import Skill
from app.schemas.skill import SkillCreate, SkillUpdate


async def create_skill(db: AsyncSession, org_id: UUID, data: SkillCreate) -> Skill:
    s = Skill(organization_id=org_id, **data.model_dump())
    db.add(s)
    await db.flush()
    return s


async def list_skills(db: AsyncSession, org_id: UUID) -> list[Skill]:
    result = await db.execute(
        select(Skill).where(Skill.organization_id == org_id, Skill.deleted_at.is_(None))
    )
    return list(result.scalars().all())


async def get_skill(db: AsyncSession, skill_id: UUID) -> Skill | None:
    result = await db.execute(
        select(Skill).where(Skill.id == skill_id, Skill.deleted_at.is_(None))
    )
    return result.scalar_one_or_none()


async def update_skill(db: AsyncSession, s: Skill, data: SkillUpdate) -> Skill:
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(s, field, value)
    await db.flush()
    await db.refresh(s)
    return s


async def soft_delete_skill(db: AsyncSession, s: Skill) -> None:
    s.deleted_at = datetime.now(UTC)
    await db.flush()
