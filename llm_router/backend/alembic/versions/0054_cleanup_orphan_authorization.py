"""Repair orphan enterprise grants and reactivate built-in roles.

Revision ID: 0054_auth_cleanup
Revises: 0053_workspace_active_slug
Create Date: 2026-09-01
"""

import sqlalchemy as sa

from alembic import op

revision = "0054_auth_cleanup"
down_revision = "0053_workspace_active_slug"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Built-in roles are authentication infrastructure. Historical UI versions
    # allowed them to be disabled, which left invisible UUIDs selected in forms.
    op.execute(sa.text("""
        UPDATE roles
        SET is_active = true, updated_at = CURRENT_TIMESTAMP
        WHERE is_builtin = true AND deleted_at IS NULL AND is_active = false
    """))

    # Soft-deleted scope targets cannot be validated by a replace-all request.
    # Retire only genuinely orphaned rows; valid inactive users/custom roles keep
    # their grants so reactivation does not silently lose configuration.
    op.execute(sa.text("""
        UPDATE enterprise_application_grants AS g
        SET deleted_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
        WHERE g.deleted_at IS NULL AND (
            (g.scope_type = 'organization' AND g.scope_id IS NOT NULL)
            OR (g.scope_type = 'department' AND NOT EXISTS (
                SELECT 1 FROM departments AS target
                WHERE target.id::text = g.scope_id
                  AND target.organization_id = g.organization_id
                  AND target.deleted_at IS NULL
            ))
            OR (g.scope_type = 'team' AND NOT EXISTS (
                SELECT 1 FROM teams AS target
                WHERE target.id::text = g.scope_id
                  AND target.organization_id = g.organization_id
                  AND target.deleted_at IS NULL
            ))
            OR (g.scope_type = 'user' AND NOT EXISTS (
                SELECT 1 FROM users AS target
                WHERE target.id::text = g.scope_id
                  AND target.organization_id = g.organization_id
                  AND target.deleted_at IS NULL
            ))
            OR (g.scope_type = 'role' AND NOT EXISTS (
                SELECT 1 FROM roles AS target
                WHERE target.id::text = g.scope_id
                  AND target.organization_id = g.organization_id
                  AND target.deleted_at IS NULL
            ))
        )
    """))


def downgrade() -> None:
    # Data repair is intentionally irreversible: restoring orphan authorization
    # rows would reintroduce access to targets that no longer exist.
    pass
