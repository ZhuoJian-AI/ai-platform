"""Add organization roles, data scopes and role application grants.

Revision ID: 0050_hybrid_rbac
Revises: 0049_single_user_department
Create Date: 2026-09-01
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0050_hybrid_rbac"
down_revision = "0049_single_user_department"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("departments", sa.Column("parent_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_departments_parent_id", "departments", "departments", ["parent_id"], ["id"], ondelete="SET NULL"
    )
    op.create_index("ix_departments_parent_id", "departments", ["parent_id"])

    op.create_table(
        "roles",
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("code", sa.String(length=100), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("data_scope", sa.String(length=40), nullable=False, server_default="self"),
        sa.Column("is_builtin", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "data_scope IN ('all','custom_departments','department','department_and_children','self')",
            name="ck_role_data_scope",
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "code", name="uq_role_org_code"),
    )
    op.create_index("ix_roles_organization_id", "roles", ["organization_id"])
    op.create_table(
        "role_permissions",
        sa.Column("role_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("permission_code", sa.String(length=160), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("role_id", "permission_code", name="uq_role_permission_code"),
    )
    op.create_index("ix_role_permissions_role_id", "role_permissions", ["role_id"])
    op.create_index("ix_role_permissions_permission_code", "role_permissions", ["permission_code"])
    op.create_table(
        "role_data_departments",
        sa.Column("role_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("department_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["department_id"], ["departments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("role_id", "department_id"),
        sa.UniqueConstraint("role_id", "department_id", name="uq_role_data_department"),
    )
    op.create_table(
        "user_roles",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "role_id"),
        sa.UniqueConstraint("user_id", "role_id", name="uq_user_role"),
    )

    op.execute(sa.text("""
        INSERT INTO roles (id, organization_id, name, code, data_scope, is_builtin, is_active)
        SELECT gen_random_uuid(), id, '企业管理员', 'enterprise_admin', 'all', true, true
        FROM organizations WHERE deleted_at IS NULL
    """))
    op.execute(sa.text("""
        INSERT INTO roles (id, organization_id, name, code, data_scope, is_builtin, is_active)
        SELECT gen_random_uuid(), id, '普通员工', 'employee', 'self', true, true
        FROM organizations WHERE deleted_at IS NULL
    """))
    op.execute(sa.text("""
        INSERT INTO role_permissions (id, role_id, permission_code)
        SELECT gen_random_uuid(), id, '*' FROM roles WHERE code = 'enterprise_admin'
    """))
    op.execute(sa.text("""
        INSERT INTO user_roles (user_id, role_id)
        SELECT app_user.id, role.id
        FROM users AS app_user
        JOIN roles AS role ON role.organization_id = app_user.organization_id
          AND role.code = CASE WHEN app_user.role = 'admin' THEN 'enterprise_admin' ELSE 'employee' END
        WHERE app_user.deleted_at IS NULL
    """))

    op.drop_constraint("ck_enterprise_application_grant_scope_type", "enterprise_application_grants", type_="check")
    op.create_check_constraint(
        "ck_enterprise_application_grant_scope_type",
        "enterprise_application_grants",
        "scope_type IN ('organization','department','team','user','role')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_enterprise_application_grant_scope_type", "enterprise_application_grants", type_="check")
    op.create_check_constraint(
        "ck_enterprise_application_grant_scope_type",
        "enterprise_application_grants",
        "scope_type IN ('organization','department','team','user')",
    )
    op.drop_table("user_roles")
    op.drop_table("role_data_departments")
    op.drop_index("ix_role_permissions_permission_code", table_name="role_permissions")
    op.drop_index("ix_role_permissions_role_id", table_name="role_permissions")
    op.drop_table("role_permissions")
    op.drop_index("ix_roles_organization_id", table_name="roles")
    op.drop_table("roles")
    op.drop_index("ix_departments_parent_id", table_name="departments")
    op.drop_constraint("fk_departments_parent_id", "departments", type_="foreignkey")
    op.drop_column("departments", "parent_id")
