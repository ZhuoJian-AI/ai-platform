"""Compatibility tombstones for the retired Data Interface abstraction."""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.api.retirement import retired_response

router = APIRouter()
_METHODS = ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]


async def _retired_data_interfaces() -> JSONResponse:
    return retired_response("Data System 与 Data Interface 已下线；业务数据请通过应用 Manifest Action 接入。")


router.add_api_route(
    "/organizations/{org_id}/data-systems",
    _retired_data_interfaces,
    methods=_METHODS,
    include_in_schema=False,
)
router.add_api_route(
    "/data-systems/{path:path}",
    _retired_data_interfaces,
    methods=_METHODS,
    include_in_schema=False,
)
router.add_api_route(
    "/data-interfaces/{path:path}",
    _retired_data_interfaces,
    methods=_METHODS,
    include_in_schema=False,
)
