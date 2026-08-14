"""resolve_permissions 节点 —— 加载组织架构、级联解析权限、校验模型访问。

等价于原 ``proxy/router.py`` 中「加载 org/dept/team → resolve_effective_permissions
→ 模型访问校验」这一段。模型越权时设置 ``state.error``，由条件边导向 build_error。
"""

from __future__ import annotations

import structlog

from app.auth.permission_resolver import resolve_effective_permissions
from app.graph.context import get_deps
from app.graph.state import ProxyState
from app.models.department import Department
from app.models.organization import Organization
from app.models.team import Team

logger = structlog.get_logger()


async def resolve_permissions(state: ProxyState) -> dict:
    """加载作用域、解析生效权限并校验模型访问。"""
    deps = get_deps()
    db = deps["db"]
    auth = deps["auth"]

    org = await db.get(Organization, auth.organization_id)
    dept = await db.get(Department, auth.department_id) if auth.department_id else None
    team = await db.get(Team, auth.team_id) if auth.team_id else None

    perms = resolve_effective_permissions(auth.api_key, org, dept, team)
    allowed_models = sorted(perms.allowed_models)

    requested_model = state.get("requested_model", "")
    if "*" not in allowed_models and requested_model not in allowed_models:
        logger.warning("model_not_allowed", model=requested_model, key_id=auth.api_key.id)
        return {
            "allowed_models": allowed_models,
            "org_id": str(auth.organization_id),
            "dept_id": str(auth.department_id) if auth.department_id else None,
            "team_id": str(auth.team_id) if auth.team_id else None,
            "error": {
                "status_code": 403,
                "error_type": "forbidden",
                "message": f"Model '{requested_model}' is not allowed for this API key",
                "extra": None,
            },
        }

    return {
        "allowed_models": allowed_models,
        "org_id": str(auth.organization_id),
        "dept_id": str(auth.department_id) if auth.department_id else None,
        "team_id": str(auth.team_id) if auth.team_id else None,
    }


def route_after_perms(state: ProxyState) -> str:
    """权限校验后的条件路由：越权 → build_error，否则 → dlp_request。"""
    return "build_error" if state.get("error") else "dlp_request"
