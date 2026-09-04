"""Converge administrator roles and add immediate session revocation.

Revision ID: 0064_admin_roles
Revises: 0063_subsystem_credentials_sso
Create Date: 2026-09-04
"""

import sqlalchemy as sa

from alembic import op

revision = "0064_admin_roles"
down_revision = "0063_subsystem_credentials_sso"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "admins",
        sa.Column("auth_epoch", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.drop_constraint(
        "fk_admins_organization_id_organizations",
        "admins",
        type_="foreignkey",
    )

    # Organization binding determines the only two valid administrator shapes.
    # Legacy ``admin`` rows remain usable but must change their password. This
    # avoids locking an existing installation out during the role migration.
    op.execute(
        """
        UPDATE admins
        SET
          is_active = CASE
            WHEN role = 'super_admin' AND organization_id IS NULL THEN is_active
            WHEN role = 'org_admin' AND organization_id IS NOT NULL THEN is_active
            WHEN role = 'admin' THEN is_active
            ELSE false
          END,
          must_change_password = CASE
            WHEN role = 'super_admin' AND organization_id IS NULL THEN must_change_password
            WHEN role = 'org_admin' AND organization_id IS NOT NULL THEN must_change_password
            WHEN role = 'admin' THEN true
            ELSE true
          END,
          role = CASE
            WHEN role = 'super_admin' AND organization_id IS NULL THEN 'platform_super_admin'
            WHEN role = 'org_admin' AND organization_id IS NOT NULL THEN 'enterprise_admin'
            WHEN organization_id IS NOT NULL THEN 'enterprise_admin'
            ELSE 'platform_super_admin'
          END
        """
    )
    op.create_foreign_key(
        "fk_admins_organization_id_organizations",
        "admins",
        "organizations",
        ["organization_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_admin_role_organization",
        "admins",
        "(role = 'platform_super_admin' AND organization_id IS NULL) OR "
        "(role = 'enterprise_admin' AND organization_id IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_admin_role_organization", "admins", type_="check")
    op.drop_constraint(
        "fk_admins_organization_id_organizations",
        "admins",
        type_="foreignkey",
    )
    op.execute(
        """
        UPDATE admins
        SET role = CASE
          WHEN role = 'platform_super_admin' THEN 'super_admin'
          ELSE 'org_admin'
        END
        """
    )
    op.create_foreign_key(
        "fk_admins_organization_id_organizations",
        "admins",
        "organizations",
        ["organization_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.drop_column("admins", "auth_epoch")
