"""ORM models — import all to ensure Alembic discovers them."""

from app.models.admin import Admin
from app.models.agent import Agent
from app.models.agent_memory import AgentMessage
from app.models.agent_run import AgentRun, AgentRunEvent
from app.models.api_key import ApiKey
from app.models.audit_log import AuditLog
from app.models.budget import BudgetUsage
from app.models.connector import ToolConnector, ToolEndpoint
from app.models.data_interface import DataInterface, DataSystem
from app.models.department import Department
from app.models.dlp_rule import DlpRule
from app.models.ecs_runtime import EcsModuleRelease, EcsRuntime
from app.models.enterprise_application import (
    CrossDepartmentWorkItem,
    EnterpriseApplication,
    EnterpriseApplicationAction,
    EnterpriseApplicationActionRequest,
    EnterpriseApplicationEvent,
    EnterpriseApplicationEventDelivery,
    EnterpriseApplicationEventRoute,
    EnterpriseApplicationGrant,
    EnterpriseApplicationIntegration,
    EnterpriseApplicationToolBinding,
)
from app.models.judge import JudgeTemplate
from app.models.llm_provider import LlmProvider, ModelDeployment
from app.models.memory import Memory
from app.models.module_deployment import ModuleDeployment, ModuleDeploymentProfile
from app.models.multimodal import MultimodalJob, VoiceAuthorizationRecord, VoiceProfile, VoiceProfileGrant
from app.models.ontology import Ontology, OntologyFile, OntologyFolder
from app.models.organization import Organization, OrganizationSlugAlias
from app.models.platform_extension import (
    PlatformExtensionCatalogEntry,
    PlatformExtensionRelease,
    PlatformExtensionReleaseEvent,
    PlatformExtensionSource,
)
from app.models.rag import RagChunk, RagCollection, RagDocument, RagFolder
from app.models.role import Role, RoleDataDepartment, RolePermission, UserRole
from app.models.routing_policy import RoutingPolicy
from app.models.skill import ScopeManagerAssignment, Skill, SkillExecution, SkillFile, SkillFolder, SkillVersion
from app.models.task import Task, TaskMessage
from app.models.team import Team
from app.models.tool_call_log import ToolCallLog
from app.models.user import User, user_department_memberships
from app.models.workspace import (
    Workspace,
    WorkspaceAuditEvent,
    WorkspaceFile,
    WorkspaceFileVersion,
    WorkspaceFolder,
    WorkspaceShareLink,
    WorkspaceUploadSession,
)

__all__ = [
    "Admin",
    "Organization",
    "OrganizationSlugAlias",
    "Department",
    "Team",
    "User",
    "user_department_memberships",
    "ApiKey",
    "LlmProvider",
    "ModelDeployment",
    "DlpRule",
    "EcsRuntime",
    "EcsModuleRelease",
    "EnterpriseApplication",
    "EnterpriseApplicationAction",
    "EnterpriseApplicationActionRequest",
    "EnterpriseApplicationIntegration",
    "EnterpriseApplicationEvent",
    "EnterpriseApplicationEventDelivery",
    "EnterpriseApplicationEventRoute",
    "CrossDepartmentWorkItem",
    "EnterpriseApplicationGrant",
    "EnterpriseApplicationToolBinding",
    "RoutingPolicy",
    "Role",
    "UserRole",
    "RolePermission",
    "RoleDataDepartment",
    "AuditLog",
    "BudgetUsage",
    "PlatformExtensionSource",
    "PlatformExtensionCatalogEntry",
    "PlatformExtensionRelease",
    "PlatformExtensionReleaseEvent",
    # 智能体平台
    "Workspace",
    "WorkspaceFile",
    "WorkspaceFolder",
    "WorkspaceFileVersion",
    "WorkspaceUploadSession",
    "WorkspaceAuditEvent",
    "WorkspaceShareLink",
    "Agent",
    "AgentRun",
    "AgentRunEvent",
    "AgentMessage",
    "RagCollection",
    "RagDocument",
    "RagFolder",
    "RagChunk",
    "JudgeTemplate",
    # 工具连接器
    "ToolConnector",
    "ToolEndpoint",
    "DataSystem",
    "DataInterface",
    "Skill",
    "SkillFolder",
    "SkillFile",
    "SkillVersion",
    "SkillExecution",
    "ScopeManagerAssignment",
    "Ontology",
    "OntologyFolder",
    "OntologyFile",
    "ToolCallLog",
    # 终端用户端
    "Task",
    "TaskMessage",
    "Memory",
    "ModuleDeployment",
    "ModuleDeploymentProfile",
    "MultimodalJob",
    "VoiceProfile",
    "VoiceProfileGrant",
    "VoiceAuthorizationRecord",
]
