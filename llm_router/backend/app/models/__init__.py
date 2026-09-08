"""ORM models — import all to ensure Alembic discovers them."""

from app.models.admin import Admin
from app.models.agent import Agent
from app.models.agent_run import AgentRun, AgentRunEvent
from app.models.api_key import ApiKey
from app.models.audit_log import AuditLog
from app.models.budget import AiQuotaEvent, BudgetUsage
from app.models.connector import ToolConnector, ToolEndpoint
from app.models.data_interface import DataInterface, DataSystem
from app.models.department import Department
from app.models.dlp_rule import DlpRule
from app.models.ecs_runtime import EcsModuleRelease, EcsRuntime
from app.models.enterprise_application import (
    EnterpriseApplication,
    EnterpriseApplicationAction,
    EnterpriseApplicationActionRequest,
    EnterpriseApplicationEvent,
    EnterpriseApplicationEventDelivery,
    EnterpriseApplicationEventRoute,
    EnterpriseApplicationGrant,
    EnterpriseApplicationIntegration,
    EnterpriseApplicationSsoCode,
    EnterpriseApplicationToolBinding,
)
from app.models.llm_provider import LlmProvider, ModelDeployment
from app.models.memory import Memory
from app.models.multimodal import MultimodalJob, VoiceAuthorizationRecord, VoiceProfile, VoiceProfileGrant
from app.models.organization import Organization, OrganizationSlugAlias
from app.models.rag import RagChunk, RagCollection, RagDocument, RagFolder
from app.models.role import Role, RoleDataDepartment, RolePermission, UserRole
from app.models.routing_policy import RoutingPolicy
from app.models.skill import SkillExecution, SkillFile, SkillFolder, SkillVersion
from app.models.task import Task, TaskFileRef, TaskMessage
from app.models.team import Team
from app.models.tool_call_log import ToolCallLog
from app.models.user import User
from app.models.workspace import (
    Workspace,
    WorkspaceAuditEvent,
    WorkspaceFile,
    WorkspaceFileEventOutbox,
    WorkspaceFileMutation,
    WorkspaceFileVersion,
    WorkspaceFolder,
    WorkspacePreviewJob,
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
    "EnterpriseApplicationSsoCode",
    "EnterpriseApplicationEvent",
    "EnterpriseApplicationEventDelivery",
    "EnterpriseApplicationEventRoute",
    "EnterpriseApplicationGrant",
    "EnterpriseApplicationToolBinding",
    "RoutingPolicy",
    "Role",
    "UserRole",
    "RolePermission",
    "RoleDataDepartment",
    "AuditLog",
    "BudgetUsage",
    "AiQuotaEvent",
    # 智能体平台
    "Workspace",
    "WorkspaceFile",
    "WorkspaceFileMutation",
    "WorkspaceFolder",
    "WorkspaceFileVersion",
    "WorkspacePreviewJob",
    "WorkspaceUploadSession",
    "WorkspaceAuditEvent",
    "WorkspaceShareLink",
    "WorkspaceFileEventOutbox",
    "Agent",
    "AgentRun",
    "AgentRunEvent",
    "RagCollection",
    "RagDocument",
    "RagFolder",
    "RagChunk",
    # 工具连接器
    "ToolConnector",
    "ToolEndpoint",
    "DataSystem",
    "DataInterface",
    "SkillFolder",
    "SkillFile",
    "SkillVersion",
    "SkillExecution",
    "ToolCallLog",
    # 终端用户端
    "Task",
    "TaskFileRef",
    "TaskMessage",
    "Memory",
    "MultimodalJob",
    "VoiceProfile",
    "VoiceProfileGrant",
    "VoiceAuthorizationRecord",
]
