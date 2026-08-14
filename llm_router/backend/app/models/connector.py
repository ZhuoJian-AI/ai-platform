"""Tool connector ORM models — external systems (ERP/CRM/HRM) and their endpoints."""

from sqlalchemy import Boolean, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin


class ToolConnector(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    """外部系统连接器（ERP/CRM/HRM/其他）：base_url + 鉴权 + OpenAPI spec。"""

    __tablename__ = "tool_connectors"
    __table_args__ = (UniqueConstraint("organization_id", "slug", name="uq_connector_org_slug"),)

    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    type: Mapped[str] = mapped_column(String(20), nullable=False, default="other")  # erp/crm/hrm/other
    base_url: Mapped[str] = mapped_column(Text, nullable=False)
    # none / basic / bearer / apikey / oauth
    auth_type: Mapped[str] = mapped_column(String(20), nullable=False, default="none")
    # 鉴权配置（密钥/token 等）AES-256-GCM 加密存储
    auth_config_encrypted: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # OpenAPI / Swagger spec（JSON），用于解析生成 ToolEndpoint / Skill
    spec: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    health_status: Mapped[str] = mapped_column(String(20), nullable=False, default="unknown")

    endpoints = relationship("ToolEndpoint", back_populates="connector", lazy="selectin")


class ToolEndpoint(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    """连接器下的单个 API 端点（可由 spec 解析或手填）。"""

    __tablename__ = "tool_endpoints"

    connector_id: Mapped[str] = mapped_column(
        ForeignKey("tool_connectors.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    method: Mapped[str] = mapped_column(String(10), nullable=False, default="GET")
    path: Mapped[str] = mapped_column(String(1024), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    params_schema: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    response_schema: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    connector = relationship("ToolConnector", back_populates="endpoints")
