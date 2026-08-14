"""LLM Provider ORM model."""

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin


class LlmProvider(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "llm_providers"

    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    provider_type: Mapped[str] = mapped_column(String(50), nullable=False)  # anthropic, openai, azure_openai, custom

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
