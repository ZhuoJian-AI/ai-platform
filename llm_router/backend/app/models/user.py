"""User ORM model."""

from sqlalchemy import Column, ForeignKey, Index, String, Table, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin

user_department_memberships = Table(
    "user_department_memberships",
    Base.metadata,
    Column("user_id", UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column(
        "department_id",
        UUID(as_uuid=True),
        ForeignKey("departments.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Index("ix_user_department_memberships_department_id", "department_id"),
    UniqueConstraint("user_id", name="uq_user_department_memberships_user_id"),
)


class User(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("organization_id", "username", name="uq_user_org_username"),)

    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    # 用户名（非邮箱）作为登录标识：同一组织内不可同名，不同组织之间可以同名。
    username: Mapped[str] = mapped_column(String(320), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[str] = mapped_column(String(50), nullable=False, default="member")  # admin, member
    is_active: Mapped[bool] = mapped_column(default=True)
    # 每个用户只有一个所属部门。关联表仅为兼容旧版本和渐进迁移保留；
    # 模块可见性由应用/子模块授权决定，不通过多部门成员关系叠加。
    department_id: Mapped[str | None] = mapped_column(
        ForeignKey("departments.id", ondelete="SET NULL"), nullable=True, index=True
    )
    team_id: Mapped[str | None] = mapped_column(
        ForeignKey("teams.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # 密码登录体系：nullable 以兼容存量用户（无密码则不可密码登录，需管理员重置）
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    must_change_password: Mapped[bool] = mapped_column(default=False)

    # 关系
    organization = relationship("Organization", back_populates="users")
    departments = relationship(
        "Department",
        secondary=user_department_memberships,
        lazy="selectin",
    )
    manager_assignments = relationship(
        "ScopeManagerAssignment", lazy="selectin", primaryjoin="User.id==ScopeManagerAssignment.user_id"
    )

    @property
    def department_ids(self) -> list[str]:
        """Compatibility response field containing zero or one department."""
        return [str(self.department_id)] if self.department_id else []

    @property
    def manager_scopes(self) -> list[dict]:
        return [
            {"scope_type": grant.scope_type, "scope_id": grant.scope_id}
            for grant in (self.manager_assignments or [])
            if grant.deleted_at is None
        ]
