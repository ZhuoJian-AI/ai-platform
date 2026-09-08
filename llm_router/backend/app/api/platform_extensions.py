"""Compatibility tombstones for the retired DSH extension market."""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.api.retirement import retired_response

router = APIRouter(prefix="/platform/extensions")
_METHODS = ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]


@router.api_route("", methods=_METHODS, include_in_schema=False)
@router.api_route("/{path:path}", methods=_METHODS, include_in_schema=False)
async def retired_platform_extensions(path: str = "") -> JSONResponse:
    del path
    return retired_response("DSH 外部扩展与市场已下线；请使用统一 AI Assistant Core。")
