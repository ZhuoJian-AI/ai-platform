"""Organization-scoped hybrid RBAC models.

Users keep one organizational department while roles grant product capabilities and
data scopes.  Direct department/team/user grants remain additive for compatibility.
"""

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin


class Role(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "roles"
    __table_args__ = (
        UniqueConstraint("organization_id", "code", name="uq_role_org_code"),
        CheckConstraint(
            "data_scope IN ('all','custom_departments','department','department_and_children','self')",
            name="ck_role_data_scope",
        ),
    )

    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    code: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    data_scope: Mapped[str] = mapped_column(String(40), nullable=False, default="self")
    is_builtin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    permissions = relationship(
        "RolePermission", back_populates="role", cascade="all, delete-orphan", lazy="selectin"
    )
    data_departments = relationship(
        "RoleDataDepartment", back_populates="role", cascade="all, delete-orphan", lazy="selectin"
    )

    @property
    def permission_codes(self) -> list[str]:
        return sorted({item.permission_code for item in self.permissions})

    @property
    def department_ids(self) -> list[str]:
        return [str(item.department_id) for item in self.data_departments]


class UserRole(TimestampMixin, Base):
    __tablename__ = "user_roles"
    __table_args__ = (UniqueConstraint("user_id", "role_id", name="uq_user_role"),)

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    role_id: Mapped[str] = mapped_column(
        ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True
    )
    role = relationship("Role", lazy="selectin")


class RolePermission(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "role_permissions"
    __table_args__ = (
        UniqueConstraint("role_id", "permission_code", name="uq_role_permission_code"),
    )

    role_id: Mapped[str] = mapped_column(
        ForeignKey("roles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    permission_code: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    role = relationship("Role", back_populates="permissions")


class RoleDataDepartment(TimestampMixin, Base):
    __tablename__ = "role_data_departments"
    __table_args__ = (
        UniqueConstraint("role_id", "department_id", name="uq_role_data_department"),
    )

    role_id: Mapped[str] = mapped_column(
        ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True
    )
    department_id: Mapped[str] = mapped_column(
        ForeignKey("departments.id", ondelete="CASCADE"), primary_key=True
    )
    role = relationship("Role", back_populates="data_departments")
