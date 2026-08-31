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
    # department_id 是兼容存量逻辑的“主部门”；完整成员关系在
    # user_department_memberships 中。team_id 仍为单一主团队，且必须属于主部门。
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
        """Return all department memberships with the primary department first."""
        primary = str(self.department_id) if self.department_id else None
        values = {str(department.id) for department in (self.departments or [])}
        if primary:
            values.add(primary)
        return ([primary] if primary else []) + sorted(value for value in values if value != primary)

    @property
    def manager_scopes(self) -> list[dict]:
        return [
            {"scope_type": grant.scope_type, "scope_id": grant.scope_id}
            for grant in (self.manager_assignments or [])
            if grant.deleted_at is None
        ]
