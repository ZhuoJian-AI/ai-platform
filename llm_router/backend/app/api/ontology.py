"""Compatibility tombstones for the retired Ontology abstraction."""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.api.retirement import retired_response

router = APIRouter()
_METHODS = ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]


async def _retired_ontology() -> JSONResponse:
    return retired_response("Ontology 已下线；请使用知识库/RAG 与工作空间文件。")


for _path in (
    "/organizations/{org_id}/ontologies",
    "/ontologies/{path:path}",
    "/organizations/{org_id}/ontology-folders",
    "/ontology-folders/{path:path}",
    "/organizations/{org_id}/ontology-files",
    "/ontology-files/{path:path}",
):
    router.add_api_route(
        _path,
        _retired_ontology,
        methods=_METHODS,
        include_in_schema=False,
    )
