"""本体 service — CRUD + validation."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ontology import Ontology
from app.schemas.ontology import OntologyCreate, OntologyUpdate
from app.tools.ontology_validator import validate_ontology


async def create_ontology(db: AsyncSession, org_id: UUID, data: OntologyCreate) -> Ontology:
    o = Ontology(organization_id=org_id, **data.model_dump())
    db.add(o)
    await db.flush()
    return o


async def list_ontologies(db: AsyncSession, org_id: UUID) -> list[Ontology]:
    result = await db.execute(
        select(Ontology).where(Ontology.organization_id == org_id, Ontology.deleted_at.is_(None))
    )
    return list(result.scalars().all())


async def get_ontology(db: AsyncSession, o_id: UUID) -> Ontology | None:
    result = await db.execute(
        select(Ontology).where(Ontology.id == o_id, Ontology.deleted_at.is_(None))
    )
    return result.scalar_one_or_none()


async def update_ontology(db: AsyncSession, o: Ontology, data: OntologyUpdate) -> Ontology:
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(o, field, value)
    o.version += 1
    await db.flush()
    await db.refresh(o)
    return o


async def soft_delete_ontology(db: AsyncSession, o: Ontology) -> None:
    o.deleted_at = datetime.now(UTC)
    await db.flush()


def validate(o: Ontology) -> tuple[bool, list[str]]:
    return validate_ontology(o.entities or [], o.relations or [])
