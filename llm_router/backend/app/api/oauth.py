"""Compatibility tombstones for the retired MCP OAuth surface."""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.api.retirement import retired_response

router = APIRouter(prefix="/oauth")
well_known_router = APIRouter()

_METHODS = ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]


@router.api_route("", methods=_METHODS, include_in_schema=False)
@router.api_route("/{path:path}", methods=_METHODS, include_in_schema=False)
async def retired_oauth(path: str = "") -> JSONResponse:
    """Return one stable Chinese retirement response to stale clients."""

    del path
    return retired_response("MCP/OAuth Skill Pack 已下线；请使用平台内置助手与用户上传 Skill。")


@well_known_router.api_route(
    "/.well-known/oauth-authorization-server",
    methods=_METHODS,
    include_in_schema=False,
)
@well_known_router.api_route(
    "/.well-known/oauth-protected-resource/{path:path}",
    methods=_METHODS,
    include_in_schema=False,
)
async def retired_oauth_metadata(path: str = "") -> JSONResponse:
    del path
    return retired_response("MCP/OAuth Skill Pack 已下线；请使用平台内置助手与用户上传 Skill。")
