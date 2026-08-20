"""LLM provider credentials and capability-scoped model deployments."""

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin


class LlmProvider(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "llm_providers"

    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # ``vendor`` identifies who owns the account/billing relationship. ``provider_type``
    # is retained as the legacy default wire protocol so existing proxy clients keep
    # working while model deployments select their own adapter.
    vendor: Mapped[str] = mapped_column(String(50), nullable=False, default="custom", index=True)
    provider_type: Mapped[str] = mapped_column(String(50), nullable=False)
    region: Mapped[str | None] = mapped_column(String(64), nullable=True)
    workspace_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # 层级范围：organization / department / team（调用解析遵循 团队>部门>组织 优先级且继承）
    scope_type: Mapped[str] = mapped_column(String(20), nullable=False, default="organization", index=True)
    department_id: Mapped[str | None] = mapped_column(
        ForeignKey("departments.id", ondelete="SET NULL"), nullable=True, index=True
    )
    team_id: Mapped[str | None] = mapped_column(
        ForeignKey("teams.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # 连接配置
    base_url: Mapped[str] = mapped_column(Text, nullable=False)
    api_key_encrypted: Mapped[str] = mapped_column(Text, nullable=False)  # AES-256-GCM 加密
    api_key_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # 路由配置
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # 越高越优先
    weight: Mapped[int] = mapped_column(Integer, nullable=False, default=1)  # 加权负载均衡
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=120)
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=2)

    # 支持的模型列表
    supported_models: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    # 健康状态
    health_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="unknown"
    )  # healthy, degraded, down, unknown

    # 提供商特定配置（如 Azure 的 deployment name, API version 等）
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    # 关系
    organization = relationship("Organization", back_populates="providers")
    model_deployments = relationship(
        "ModelDeployment",
        back_populates="provider",
        cascade="all, delete-orphan",
        lazy="selectin",
        primaryjoin="and_(LlmProvider.id == ModelDeployment.provider_id, ModelDeployment.deleted_at.is_(None))",
    )


class ModelDeployment(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    """One callable upstream model and its protocol/capability declaration."""

    __tablename__ = "model_deployments"
    __table_args__ = (
        Index(
            "uq_model_deployment_provider_model_adapter_active",
            "provider_id",
            "model_id",
            "adapter",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    provider_id: Mapped[str] = mapped_column(
        ForeignKey("llm_providers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    model_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    adapter: Mapped[str] = mapped_column(String(64), nullable=False, default="openai_chat_completions")
    capabilities: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    base_url_override: Mapped[str | None] = mapped_column(Text, nullable=True)
    endpoint_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    embedding_dimensions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    routing_priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    verification_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="unverified", index=True
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    provider = relationship("LlmProvider", back_populates="model_deployments")
