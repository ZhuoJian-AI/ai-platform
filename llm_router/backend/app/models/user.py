"""User ORM model."""

from sqlalchemy import ForeignKey, String, UniqueConstraint
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
    role: Mapped[str] = mapped_column(String(50), nullable=False, default="member")  # admin, member
    is_active: Mapped[bool] = mapped_column(default=True)
    # 终端用户作用域绑定：驱动资源 scope 过滤与 4 级记忆载入（org + dept + team + user）。
    # 任一可为空（未分配部门/团队的用户仅命中 organization + user 两级）。
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
