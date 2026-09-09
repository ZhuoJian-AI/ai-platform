"""Management API router — aggregates all admin routes."""

from fastapi import APIRouter

from app.api.admin import router as admin_router

# 智能体平台
from app.api.agents import router as agent_router
from app.api.api_keys import router as api_key_router
from app.api.audit_logs import router as audit_router
from app.api.budget import router as budget_router
from app.api.config import router as config_router
from app.api.departments import router as dept_router
from app.api.dlp_rules import router as dlp_router
from app.api.ecs_publisher import router as ecs_publisher_router
from app.api.enterprise_applications import router as enterprise_application_router
from app.api.file_events import router as file_event_router
from app.api.llm_providers import router as provider_router
from app.api.memory import router as memory_router
from app.api.monitor import router as monitor_router
from app.api.multimodal import router as multimodal_router
from app.api.organizations import router as org_router
from app.api.roles import router as role_router
from app.api.routing_policies import router as routing_router
from app.api.storage_lifecycle import router as storage_lifecycle_router
from app.api.subsystem_ai import router as subsystem_ai_router
from app.api.terminal import router as terminal_router
from app.api.users import router as user_router
from app.api.workspaces import router as workspace_router

api_router = APIRouter(prefix="/api/v1")

# 认证相关 — 无需 JWT 保护
api_router.include_router(admin_router, tags=["auth"])
api_router.include_router(config_router, tags=["config"])
api_router.include_router(storage_lifecycle_router, tags=["storage-lifecycle"])
api_router.include_router(enterprise_application_router, tags=["enterprise-applications"])
api_router.include_router(ecs_publisher_router, tags=["ecs-publisher"])

# 以下路由需要 JWT 管理员认证，
# 认证通过 require_admin 依赖在各自的路由文件中声明
api_router.include_router(org_router, tags=["organizations"])
api_router.include_router(dept_router, tags=["departments"])
api_router.include_router(user_router, tags=["users"])
api_router.include_router(role_router, tags=["roles"])
api_router.include_router(workspace_router, tags=["workspaces"])
api_router.include_router(agent_router, tags=["agents"])
api_router.include_router(api_key_router, tags=["api-keys"])
api_router.include_router(provider_router, tags=["llm-providers"])
api_router.include_router(dlp_router, tags=["dlp-rules"])
api_router.include_router(routing_router, tags=["routing-policies"])
api_router.include_router(audit_router, tags=["audit-logs"])
api_router.include_router(budget_router, tags=["budget"])
# 应用监控台
api_router.include_router(monitor_router, tags=["monitor"])
api_router.include_router(multimodal_router, tags=["multimodal"])
api_router.include_router(subsystem_ai_router, tags=["subsystem-ai"])
# 终端用户端（require_user 守卫，用户 JWT）
api_router.include_router(terminal_router, tags=["terminal"])
api_router.include_router(file_event_router, tags=["terminal-file-events"])
# 长期记忆（管理端维护组织、部门、角色和员工级长期记忆）
api_router.include_router(memory_router, tags=["memory"])
