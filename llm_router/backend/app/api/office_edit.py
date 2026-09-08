"""Compatibility tombstone for retired WebOffice save callbacks."""

from fastapi import APIRouter

from app.api.retirement import retired_api_dependency

router = APIRouter(
    prefix="/internal/weboffice",
    dependencies=[retired_api_dependency("WebOffice 在线协作编辑")],
)


@router.post("/save-events", status_code=410)
async def retired_office_save_event():
    """Reject legacy callbacks without parsing or persisting their payload."""
