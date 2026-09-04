"""Admin ORM model — platform-level administrators (optionally scoped to one organization)."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Admin(Base):
    __tablename__ = "admins"
    # 用户名（非邮箱）作为登录标识：
    # - 组织级账号（organization_id IS NOT NULL）：(organization_id, username) 组织内唯一
    # - 平台级账号（organization_id IS NULL）：username 全局唯一
    # 同一组织内不可同名，不同组织之间可以同名；平台级账号全局唯一。
    __table_args__ = (
        CheckConstraint(
            "(role = 'platform_super_admin' AND organization_id IS NULL) OR "
            "(role = 'enterprise_admin' AND organization_id IS NOT NULL)",
            name="ck_admin_role_organization",
        ),
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

    # 管理员只有两个角色：
    # - platform_super_admin: 平台超级管理员，不绑定组织，可管理所有组织
    # - enterprise_admin: 企业管理员，永久绑定一个组织，只能管理该组织
    role: Mapped[str] = mapped_column(String(20), nullable=False)

    # enterprise_admin 必填且一经创建不可变；platform_super_admin 必须为 NULL。
    organization_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=True
    )

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # 是否需要强制修改密码（自动创建的管理员首次登录时为 True）
    must_change_password: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # 密码、角色或启停状态变化时递增。JWT 携带该值，旧会话立即失效。
    auth_epoch: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    # TOTP seed is encrypted with the platform master key. Recovery codes are
    # random high-entropy values and only their SHA-256 verifiers are stored.
    mfa_secret_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    mfa_recovery_code_hashes: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    mfa_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    mfa_last_totp_counter: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
