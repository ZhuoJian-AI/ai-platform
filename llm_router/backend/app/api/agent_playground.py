"""Compatibility tombstones for the retired administrator playground."""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.api.retirement import retired_response

router = APIRouter()
_METHODS = ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]


@router.api_route("/agents/{agent_id}/playground", methods=_METHODS, include_in_schema=False)
@router.api_route("/agents/{agent_id}/runs", methods=_METHODS, include_in_schema=False)
async def retired_agent_playground(agent_id: str) -> JSONResponse:
    del agent_id
    return retired_response("管理员智能体测试广场已下线；请使用真实用户端到端验收。")
