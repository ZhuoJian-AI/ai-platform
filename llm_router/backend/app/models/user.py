"""User ORM model."""

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin


class User(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("organization_id", "username", name="uq_user_org_username"),)

    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    # 用户名（非邮箱）作为登录标识：同一组织内不可同名，不同组织之间可以同名。
    username: Mapped[str] = mapped_column(String(320), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(default=True)
    # 员工只有一个组织归属部门；跨部门能力由角色授权并集决定。
    department_id: Mapped[str | None] = mapped_column(
        ForeignKey("departments.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # 密码登录体系：nullable 以兼容存量用户（无密码则不可密码登录，需管理员重置）
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    must_change_password: Mapped[bool] = mapped_column(default=False)
    # Monotonic credential/authorization version.  Browser and MCP sessions
    # carry this value and fail immediately after a password, role or scope
    # change instead of waiting for token expiry.
    auth_epoch: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # 关系
    organization = relationship("Organization", back_populates="users")
    role_assignments = relationship(
        "UserRole", lazy="selectin", cascade="all, delete-orphan"
    )

    @property
    def department_ids(self) -> list[str]:
        """One-release compatibility response containing zero or one department."""
        return [str(self.department_id)] if self.department_id else []

    @property
    def role(self) -> str:
        """One-release compatibility field; administrators use the separate Admin model."""
        return "member"

    @role.setter
    def role(self, value: str) -> None:
        if value not in {None, "member"}:
            raise ValueError("员工账号不能作为管理员账号使用")

    @property
    def roles(self) -> list[dict]:
        return [
            {
                "id": assignment.role.id,
                "name": assignment.role.name,
                "code": assignment.role.code,
                "data_scope": assignment.role.data_scope,
                "is_builtin": assignment.role.is_builtin,
            }
            for assignment in (self.role_assignments or [])
            if assignment.role.deleted_at is None and assignment.role.is_active
        ]

    @property
    def role_ids(self) -> list[str]:
        return [str(item["id"]) for item in self.roles]

    @property
    def permission_codes(self) -> list[str]:
        return sorted({
            permission.permission_code
            for assignment in (self.role_assignments or [])
            if assignment.role.deleted_at is None and assignment.role.is_active
            for permission in assignment.role.permissions
        })
