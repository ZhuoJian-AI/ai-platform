"""Agent ORM model — agent configuration (system prompt / workflow / memory / judge)."""

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin


class Agent(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    """智能体配置：系统提示词 + 模型 + workflow + 记忆 + 判官 + RAG + 技能 绑定。"""

    __tablename__ = "agents"
    __table_args__ = (
        UniqueConstraint("organization_id", "scope_type", "scope_id", "slug", name="uq_agent_scope_slug"),
    )

    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    # 作用范围：organization / department / team / user；scope_id 为对应 id（org 级为 None）。
    scope_type: Mapped[str] = mapped_column(String(20), nullable=False, default="organization")
    scope_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    # 创建者（终端用户 id）：admin / 历史数据为 None（与 SkillFolder/RagCollection 一致，纯字符串无 FK）。
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    system_prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # 真实模型 id（如 glm-5.2 / claude-sonnet-4），或 "default" 走组织默认路由。
    model_alias: Mapped[str] = mapped_column(String(255), nullable=False, default="default")

    # workflow 定义：节点序列/编排（JSON）。当前 v1 为线性步骤列表，后续可扩展为 DAG。
    workflow: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    # 记忆配置：{"max_messages": int, "summarize": bool, ...}
    memory_config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # 判官配置覆盖：{"enabled": bool, "criteria_overrides": {...}}；配合 judge_template_id
    judge_config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    workspace_id: Mapped[str | None] = mapped_column(
        ForeignKey("workspaces.id", ondelete="SET NULL"), nullable=True, index=True
    )
    rag_collection_id: Mapped[str | None] = mapped_column(
        ForeignKey("rag_collections.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # 绑定的 RAG 集合 ID 列表（复数，供终端 general 模式继承；与 skill_ids 同范式）。
    # 旧单 FK rag_collection_id 仍供管理端测试广场（agent 模式）单 RAG 使用。
    rag_collection_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    judge_template_id: Mapped[str | None] = mapped_column(
        ForeignKey("judge_templates.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # 绑定的技能 ID 列表（Skill.id）
    skill_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    temperature: Mapped[float | None] = mapped_column(nullable=True)
    max_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    runs = relationship("AgentRun", back_populates="agent", lazy="noload")
