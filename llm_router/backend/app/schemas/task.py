"""Task & TaskMessage Pydantic schemas — 终端用户任务线程。"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas._base import MetaReadModel


class TaskConfig(BaseModel):
    """任务装配配置。空数组维度 = 运行时按用户权限自动匹配全集。

    长期记忆不在此配置：运行时按用户权限自动载入 组织+部门+团队+个人 四级记忆全集。
    """

    workspace_id: str | None = None
    skill_ids: list[str] = Field(default_factory=list)
    ontology_ids: list[str] = Field(default_factory=list)
    rag_collection_ids: list[str] = Field(default_factory=list)
    model_alias: str | None = None
    # 执行模式：craft（自主多步执行）/ ask（只读单轮问答）/ plan（出方案不执行）
    exec_mode: str = "craft"
    # 可选：引用一个 Agent 行作为「场景模板」，其 system_prompt 作为 persona/policy
    # 前缀拼到运行时 system_prompt 最前。承载场景 persona + 不可由本体/目录推导的
    # 业务规则 + 输出骨架，使终端用户 composer 只需写目标+对象，不必复制整套提示词。
    template_agent_id: str | None = None


class TaskCreate(BaseModel):
    title: str = Field("", max_length=255)
    message: str = ""
    config: TaskConfig = Field(default_factory=TaskConfig)


class TaskUpdate(BaseModel):
    title: str | None = Field(None, max_length=255)
    status: str | None = Field(None, max_length=20)
    config: TaskConfig | None = None


class TaskRunRequest(BaseModel):
    message: str
    stream: bool = False
    # 逐次运行覆盖（不落库）：
    #   字段未传 → 沿用 task.config.template_agent_id（向后兼容 demo 旧 /run 调用）
    #   显式传 UUID → 该次用此智能体（load_config 拼 persona + 继承 skill_ids/model_alias）
    #   显式传 null/空 → 强制通用智能体（不绑模板，纯 GENERAL_SYSTEM_PROMPT）
    template_agent_id: str | None = None


class TaskMessageRead(MetaReadModel):
    id: UUID
    task_id: UUID
    role: str
    content: str
    created_at: datetime
    updated_at: datetime


class TaskRead(BaseModel):
    id: UUID
    organization_id: UUID
    user_id: UUID
    department_id: UUID | None = None
    team_id: UUID | None = None
    session_id: str
    title: str
    message: str
    config: dict
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TaskReadWithMessages(TaskRead):
    messages: list[TaskMessageRead] = Field(default_factory=list)
    # 该任务最新一次 run 的状态（agent_runs.status）—— 前端据此判断是否需要
    # 调 GET /stream 重连续接（后台 detach 执行，刷新不丢）。None=尚无 run。
    run_status: str | None = None
