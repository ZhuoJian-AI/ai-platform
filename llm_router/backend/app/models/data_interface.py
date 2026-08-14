"""Data interface ORM models — 数据接口页独立数据结构（系统 + 接口）。

与连接器（ToolConnector/ToolEndpoint，供技能绑定与 agent 调用）解耦。
数据接口仅用于管理端启用/禁用 + 查看输入输出样例。系统按节点作用域化。
"""

from sqlalchemy import Boolean, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin


class DataSystem(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    """数据接口系统：按 (organization_id, scope_type, scope_id) 节点作用域化。"""

    __tablename__ = "data_systems"
    __table_args__ = (
        UniqueConstraint("organization_id", "scope_type", "scope_id", "name", name="uq_data_system_scope_name"),
    )

    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    scope_type: Mapped[str] = mapped_column(String(20), nullable=False, default="organization")
    scope_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    interfaces = relationship("DataInterface", back_populates="system", lazy="selectin")


class DataInterface(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    """数据接口：隶属于一个系统，承载输入输出样例（params_schema / response_schema）。"""

    __tablename__ = "data_interfaces"
    __table_args__ = (
        UniqueConstraint("data_system_id", "name", name="uq_data_interface_system_name"),
    )

    data_system_id: Mapped[str] = mapped_column(
        ForeignKey("data_systems.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    method: Mapped[str | None] = mapped_column(String(20), nullable=True)
    path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    params_schema: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    response_schema: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    system = relationship("DataSystem", back_populates="interfaces")
