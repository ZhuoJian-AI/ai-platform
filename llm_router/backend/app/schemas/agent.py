"""Agent Pydantic schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class AgentCreate(BaseModel):
    name: str = Field(..., max_length=255)
    # slug 可不填：未提供时由 service 按编码规则自动生成（名称派生 + 同 scope 内唯一）。
    slug: str | None = Field(None, max_length=100, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    description: str | None = None
    # 作用域：organization / department / team / user；scope_id 为对应 id（org 级为 None）
    scope_type: str = "organization"
    scope_id: UUID | None = None
    system_prompt: str = Field(..., min_length=1)
    model_alias: str = "default"
    workflow: list = Field(default_factory=list)
    memory_config: dict = Field(default_factory=dict)
    judge_config: dict = Field(default_factory=dict)
    workspace_id: UUID | None = None
    rag_collection_id: UUID | None = None
    rag_collection_ids: list[str] = Field(default_factory=list)
    judge_template_id: UUID | None = None
    skill_ids: list[str] = Field(default_factory=list)
    temperature: float | None = None
    max_tokens: int | None = None
    is_active: bool = True


class AgentUpdate(BaseModel):
    name: str | None = Field(None, max_length=255)
    description: str | None = None
    system_prompt: str | None = None
    model_alias: str | None = None
    workflow: list | None = None
    memory_config: dict | None = None
    judge_config: dict | None = None
    workspace_id: UUID | None = None
    rag_collection_id: UUID | None = None
    rag_collection_ids: list[str] | None = None
    judge_template_id: UUID | None = None
    skill_ids: list[str] | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    is_active: bool | None = None
    # 终端/管理端允许迁移 agent 所属 scope；None=不改动，空串=置 org 级。
    scope_type: str | None = None
    scope_id: UUID | None = None


class AgentRead(BaseModel):
    id: UUID
    organization_id: UUID
    scope_type: str
    scope_id: UUID | None
    created_by: UUID | None
    name: str
    slug: str
    description: str | None
    system_prompt: str
    model_alias: str
    workflow: list
    memory_config: dict
    judge_config: dict
    workspace_id: UUID | None
    rag_collection_id: UUID | None
    rag_collection_ids: list[str]
    judge_template_id: UUID | None
    skill_ids: list[str]
    temperature: float | None
    max_tokens: int | None
    is_active: bool
    version: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AgentRunRead(BaseModel):
    id: int
    organization_id: UUID
    agent_id: UUID
    session_id: str
    request: str
    messages: list
    steps: list
    input_tokens: int | None
    output_tokens: int | None
    latency_ms: int | None
    status: str
    error: str | None
    judge_score: dict | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
