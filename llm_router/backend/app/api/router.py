"""Management API router — aggregates all admin routes."""

from fastapi import APIRouter

from app.api.admin import router as admin_router

# 智能体平台
from app.api.agent_judge import router as judge_router
from app.api.agent_playground import router as agent_playground_router
from app.api.agents import router as agent_router
from app.api.api_keys import router as api_key_router
from app.api.audit_logs import router as audit_router
from app.api.budget import router as budget_router
from app.api.config import router as config_router

# 工具连接器
from app.api.connectors import router as connector_router
from app.api.data_interfaces import router as data_interface_router
from app.api.departments import router as dept_router
from app.api.dlp_rules import router as dlp_router
from app.api.dsh_internal import router as dsh_internal_router
from app.api.llm_providers import router as provider_router
from app.api.memory import router as memory_router
from app.api.monitor import router as monitor_router
from app.api.ontology import router as ontology_router
from app.api.organizations import router as org_router
from app.api.rag import router as rag_router
from app.api.routing_policies import router as routing_router
from app.api.skill_packages import router as skill_package_router
from app.api.skills import router as skill_router
from app.api.teams import router as team_router
from app.api.terminal import router as terminal_router
from app.api.users import router as user_router
from app.api.workspaces import router as workspace_router

api_router = APIRouter(prefix="/api/v1")

# 认证相关 — 无需 JWT 保护
api_router.include_router(admin_router, tags=["auth"])
api_router.include_router(config_router, tags=["config"])
# Docker-internal DSH callbacks use a dedicated service token, never user/admin JWTs.
api_router.include_router(dsh_internal_router, tags=["internal-dsh"])

# 以下路由需要 JWT 管理员认证，
# 认证通过 require_admin 依赖在各自的路由文件中声明
api_router.include_router(org_router, tags=["organizations"])
api_router.include_router(dept_router, tags=["departments"])
api_router.include_router(team_router, tags=["teams"])
api_router.include_router(user_router, tags=["users"])
api_router.include_router(workspace_router, tags=["workspaces"])
api_router.include_router(agent_router, tags=["agents"])
api_router.include_router(agent_playground_router, tags=["agent-playground"])
api_router.include_router(rag_router, tags=["rag"])
api_router.include_router(judge_router, tags=["judges"])
# 工具连接器
api_router.include_router(connector_router, tags=["connectors"])
api_router.include_router(data_interface_router, tags=["data-interfaces"])
api_router.include_router(skill_router, tags=["skills"])
api_router.include_router(skill_package_router, tags=["skill-packages"])
api_router.include_router(ontology_router, tags=["ontology"])
api_router.include_router(api_key_router, tags=["api-keys"])
api_router.include_router(provider_router, tags=["llm-providers"])
api_router.include_router(dlp_router, tags=["dlp-rules"])
api_router.include_router(routing_router, tags=["routing-policies"])
api_router.include_router(audit_router, tags=["audit-logs"])
api_router.include_router(budget_router, tags=["budget"])
# 应用监控台
api_router.include_router(monitor_router, tags=["monitor"])
# 终端用户端（require_user 守卫，用户 JWT）
api_router.include_router(terminal_router, tags=["terminal"])
# 长期记忆（管理端维护 org/dept/team 级长期记忆）
api_router.include_router(memory_router, tags=["memory"])
