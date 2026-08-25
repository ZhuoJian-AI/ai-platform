"""Super-admin storage lifecycle status and retry controls."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.admin_auth import CurrentAdmin, require_super_admin
from app.database import get_db
from app.services import storage_lifecycle_service

router = APIRouter(prefix="/platform/storage-lifecycle")


@router.get("/overview")
async def lifecycle_overview(
    _: CurrentAdmin = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, int]:
    return await storage_lifecycle_service.overview(db)


@router.post("/retry")
async def retry_failed_cleanup(
    _: CurrentAdmin = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, int]:
    return await storage_lifecycle_service.run_cleanup(db)
