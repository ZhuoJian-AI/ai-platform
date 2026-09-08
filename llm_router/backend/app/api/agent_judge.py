"""Compatibility tombstones for the retired Judge product."""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.api.retirement import retired_response

router = APIRouter()
_METHODS = ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]


@router.api_route("/organizations/{org_id}/judges", methods=_METHODS, include_in_schema=False)
@router.api_route("/judges/{path:path}", methods=_METHODS, include_in_schema=False)
async def retired_judges(org_id: str = "", path: str = "") -> JSONResponse:
    del org_id, path
    return retired_response("Judge 模板已下线；助手质量改由自动化端到端验收保障。")
