"""JudgeTemplate service — CRUD."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.judge import JudgeTemplate
from app.schemas.judge import JudgeTemplateCreate, JudgeTemplateUpdate


async def create_judge(db: AsyncSession, org_id: UUID, data: JudgeTemplateCreate) -> JudgeTemplate:
    jt = JudgeTemplate(organization_id=org_id, **data.model_dump())
    db.add(jt)
    await db.flush()
    return jt


async def list_judges(db: AsyncSession, org_id: UUID) -> list[JudgeTemplate]:
    result = await db.execute(
        select(JudgeTemplate).where(JudgeTemplate.organization_id == org_id, JudgeTemplate.deleted_at.is_(None))
    )
    return list(result.scalars().all())


async def get_judge(db: AsyncSession, judge_id: UUID) -> JudgeTemplate | None:
    result = await db.execute(
        select(JudgeTemplate).where(JudgeTemplate.id == judge_id, JudgeTemplate.deleted_at.is_(None))
    )
    return result.scalar_one_or_none()


async def update_judge(db: AsyncSession, jt: JudgeTemplate, data: JudgeTemplateUpdate) -> JudgeTemplate:
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(jt, field, value)
    await db.flush()
    await db.refresh(jt)
    return jt


async def soft_delete_judge(db: AsyncSession, jt: JudgeTemplate) -> None:
    jt.deleted_at = datetime.now(UTC)
    await db.flush()
