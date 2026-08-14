"""Admin ORM model — platform-level administrators (optionally scoped to one organization)."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Admin(Base):
    __tablename__ = "admins"
    # 用户名（非邮箱）作为登录标识：
    # - 组织级账号（organization_id IS NOT NULL）：(organization_id, username) 组织内唯一
    # - 平台级账号（organization_id IS NULL）：username 全局唯一
    # 同一组织内不可同名，不同组织之间可以同名；平台级账号全局唯一。
    __table_args__ = (
        Index(
            "uq_admins_username_org",
            "organization_id",
            "username",
            unique=True,
            postgresql_where=text("organization_id IS NOT NULL"),
        ),
        Index(
            "uq_admins_username_platform",
            "username",
            unique=True,
            postgresql_where=text("organization_id IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(320), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # super_admin: 平台超级管理员，可创建/删除其他管理员，管理所有组织
    # admin: 平台管理员，可管理所有组织的架构/Key/规则等，不可管理管理员
    # org_admin: 组织管理员，仅可管理自己被指派的组织（见 organization_id）
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="admin")

    # 组织绑定：org_admin 必填，指向其负责的组织；super_admin / 平台 admin 为 NULL
    # （平台级账号不绑定组织，可跨组织操作）
    organization_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True
    )

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # 是否需要强制修改密码（自动创建的管理员首次登录时为 True）
    must_change_password: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
