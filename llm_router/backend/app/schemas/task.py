"""Task & TaskMessage Pydantic schemas — 终端用户任务线程。"""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas._base import MetaReadModel
from app.services.message_verification import classify_execution_verification


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
    # 企业业务模块上下文；仅在用户具备该应用 view 权限时允许创建/运行。
    application_id: UUID | None = None


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
    # 当前轮由用户明确选择的 Skill。只影响本次运行，不写回 Task.config，发送后由前端清空。
    # /slug 仍由运行时解析以兼容历史和手动输入，但选择器必须传真实 UUID，避免同名 slug 歧义。
    invoked_skill_ids: list[UUID] = Field(default_factory=list, max_length=20)
    # 聊天输入框拖入/选择的工作空间文件。与正文中的历史 ``@UUID`` 引用并行兼容；
    # 端点会校验文件属于任务当前工作空间且已解析完成，再把快照写入 user 消息 metadata。
    attachment_file_ids: list[UUID] = Field(default_factory=list, max_length=10)
    # 逐次运行覆盖（不落库）：
    #   字段未传 → 沿用 task.config.template_agent_id（向后兼容 demo 旧 /run 调用）
    #   显式传 UUID → 该次用此智能体（load_config 拼 persona + 继承 skill_ids/model_alias）
    #   显式传 null/空 → 强制通用智能体（不绑模板，纯 GENERAL_SYSTEM_PROMPT）
    template_agent_id: str | None = None
    # 业务小助手可逐轮覆盖任务绑定应用；页面上下文只在本轮使用，不写回任务配置。
    application_id: UUID | None = None
    page_context: dict = Field(default_factory=dict)

    @field_validator("page_context")
    @classmethod
    def limit_page_context(cls, value: dict) -> dict:
        import json

        if len(json.dumps(value, ensure_ascii=False, default=str).encode("utf-8")) > 16_384:
            raise ValueError("page_context exceeds 16KB")
        cls._validate_context_value(value, depth=0)
        if "bridge_version" in value:
            if value.get("bridge_version") != 1:
                raise ValueError("unsupported iframe bridge version")
            bridge_strings = {
                "application_slug",
                "route",
                "module_key",
                "module_name",
                "entity_type",
                "entity_id",
            }
            for key in bridge_strings:
                item = value.get(key)
                if item is not None and (not isinstance(item, str) or len(item) > 1_000):
                    raise ValueError(f"invalid iframe bridge field: {key}")
            for key in ("filters", "selection"):
                item = value.get(key)
                if item is not None and not isinstance(item, dict):
                    raise ValueError(f"invalid iframe bridge field: {key}")
            data_version = value.get("data_version")
            if data_version is not None:
                import math

                if (
                    not isinstance(data_version, str | int | float)
                    or isinstance(data_version, bool)
                    or (isinstance(data_version, str) and len(data_version) > 1_000)
                    or (isinstance(data_version, float) and not math.isfinite(data_version))
                ):
                    raise ValueError("invalid iframe bridge field: data_version")
        return value

    @classmethod
    def _validate_context_value(cls, value, *, depth: int) -> None:
        if depth > 5:
            raise ValueError("page_context nesting is too deep")
        if value is None or isinstance(value, bool | int | float):
            return
        if isinstance(value, str):
            if len(value) > 4_000:
                raise ValueError("page_context string is too long")
            return
        if isinstance(value, list):
            if len(value) > 200:
                raise ValueError("page_context list is too large")
            for item in value:
                cls._validate_context_value(item, depth=depth + 1)
            return
        if isinstance(value, dict):
            if len(value) > 200:
                raise ValueError("page_context object is too large")
            for key, item in value.items():
                if not isinstance(key, str) or len(key) > 128:
                    raise ValueError("page_context contains an invalid key")
                cls._validate_context_value(item, depth=depth + 1)
            return
        raise ValueError("page_context must contain JSON-compatible values")


class ExecutionVerification(BaseModel):
    status: Literal["verified", "partial", "failed", "legacy_unverified"]
    tool_calls: int
    succeeded: int
    failed: int


class TaskMessageRead(MetaReadModel):
    id: UUID
    task_id: UUID
    role: str
    content: str
    created_at: datetime
    updated_at: datetime
    execution_verification: ExecutionVerification | None = None

    @model_validator(mode="after")
    def _derive_execution_verification(self):
        if self.role == "assistant" and self.execution_verification is None:
            result = classify_execution_verification(self.content, self.metadata)
            if result is not None:
                self.execution_verification = ExecutionVerification(**result)
        return self


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
    match_excerpt: str | None = None

    model_config = {"from_attributes": True}


class TaskReadWithMessages(TaskRead):
    messages: list[TaskMessageRead] = Field(default_factory=list)
    # 该任务最新一次 run 的状态（agent_runs.status）—— 前端据此判断是否需要
    # 调 GET /stream 重连续接（后台 detach 执行，刷新不丢）。None=尚无 run。
    run_status: str | None = None
