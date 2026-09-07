"""Retire Team from active authorization while preserving legacy access.

Revision ID: 0069_retire_team_scope
Revises: 0068_ai_quota_rollups
Create Date: 2026-09-07

This is the expand/migrate phase. Legacy columns and the Team table remain for
one rollback-compatible release, but active identities and resources no longer
depend on them. Physical column/table removal follows only after live zero-use
verification.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0069_retire_team_scope"
down_revision = "0068_ai_quota_rollups"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A Team workspace cannot be widened to its whole department without a
    # file-level ACL. Refuse the migration instead of disclosing old files.
    op.execute(sa.text("""
        DO $$
        BEGIN
          IF EXISTS (
            SELECT 1
            FROM workspaces w
            JOIN workspace_files f ON f.workspace_id = w.id AND f.deleted_at IS NULL
            WHERE w.scope_type = 'team' AND w.deleted_at IS NULL
          ) THEN
            RAISE EXCEPTION
              'Team workspace still contains files; migrate them with an explicit role ACL before retiring Team';
          END IF;
        END $$;
    """))

    # Preserve former membership as an ordinary role. The deterministic code
    # lets operators trace where a compatibility role came from.
    op.execute(sa.text("""
        INSERT INTO roles (
          id, organization_id, name, code, description, data_scope,
          is_builtin, is_active, created_at, updated_at
        )
        SELECT
          gen_random_uuid(), t.organization_id, t.name,
          'legacy_team_' || replace(t.id::text, '-', ''),
          '由已退役 Team 自动迁移；仅用于保留原成员的既有访问范围',
          'custom_departments', false, true, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        FROM teams t
        WHERE t.deleted_at IS NULL
          AND NOT EXISTS (
            SELECT 1 FROM roles r
            WHERE r.organization_id = t.organization_id
              AND r.code = 'legacy_team_' || replace(t.id::text, '-', '')
          );
    """))
    op.execute(sa.text("""
        INSERT INTO role_data_departments (role_id, department_id, created_at, updated_at)
        SELECT r.id, t.department_id, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        FROM teams t
        JOIN roles r ON r.organization_id = t.organization_id
          AND r.code = 'legacy_team_' || replace(t.id::text, '-', '')
        ON CONFLICT (role_id, department_id) DO NOTHING;
    """))
    op.execute(sa.text("""
        INSERT INTO user_roles (user_id, role_id, created_at, updated_at)
        SELECT u.id, r.id, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        FROM users u
        JOIN teams t ON t.id = u.team_id
        JOIN roles r ON r.organization_id = t.organization_id
          AND r.code = 'legacy_team_' || replace(t.id::text, '-', '')
        WHERE u.deleted_at IS NULL
        ON CONFLICT (user_id, role_id) DO NOTHING;
    """))

    # Team-scoped application grants become grants to the migrated role.
    op.execute(sa.text("""
        UPDATE enterprise_application_grants g
        SET scope_type = 'role', scope_id = r.id::text, updated_at = CURRENT_TIMESTAMP
        FROM teams t
        JOIN roles r ON r.organization_id = t.organization_id
          AND r.code = 'legacy_team_' || replace(t.id::text, '-', '')
        WHERE g.scope_type = 'team' AND g.scope_id = t.id::text
          AND NOT EXISTS (
            SELECT 1 FROM enterprise_application_grants existing
            WHERE existing.application_id = g.application_id
              AND existing.scope_type = 'role'
              AND existing.scope_id = r.id::text
              AND existing.deleted_at IS NULL
          );
    """))
    op.execute(sa.text("""
        UPDATE enterprise_application_grants g
        SET deleted_at = COALESCE(g.deleted_at, CURRENT_TIMESTAMP), updated_at = CURRENT_TIMESTAMP
        FROM teams t
        JOIN roles r ON r.organization_id = t.organization_id
          AND r.code = 'legacy_team_' || replace(t.id::text, '-', '')
        WHERE g.scope_type = 'team' AND g.scope_id = t.id::text;
    """))

    # Scoped content can be authorized by the compatibility role. Workspaces
    # are the exception: empty Team workspaces are retired, never widened.
    for table in (
        "agents",
        "data_systems",
        "memories",
        "ontology_folders",
        "ontology_files",
        "rag_collections",
        "skill_folders",
        "skills",
    ):
        op.execute(sa.text(f"""
            UPDATE {table} resource
            SET scope_type = 'role', scope_id = r.id::text, updated_at = CURRENT_TIMESTAMP
            FROM teams t
            JOIN roles r ON r.organization_id = t.organization_id
              AND r.code = 'legacy_team_' || replace(t.id::text, '-', '')
            WHERE resource.scope_type = 'team' AND resource.scope_id = t.id::text;
        """))

    op.execute(sa.text("""
        UPDATE workspaces
        SET is_active = false,
            deleted_at = COALESCE(deleted_at, CURRENT_TIMESTAMP),
            updated_at = CURRENT_TIMESTAMP
        WHERE scope_type = 'team';
    """))
    op.execute(sa.text("""
        UPDATE llm_providers
        SET is_active = false, updated_at = CURRENT_TIMESTAMP
        WHERE scope_type = 'team' OR team_id IS NOT NULL;
    """))
    op.execute(sa.text("""
        UPDATE api_keys
        SET is_active = false,
            revoked_at = COALESCE(revoked_at, CURRENT_TIMESTAMP),
            updated_at = CURRENT_TIMESTAMP
        WHERE scope_type = 'team' OR team_id IS NOT NULL;
    """))
    op.execute(sa.text("""
        UPDATE dlp_rules
        SET is_active = false, updated_at = CURRENT_TIMESTAMP
        WHERE scope_type = 'team';
    """))
    op.execute(sa.text("""
        UPDATE enterprise_application_event_routes route
        SET target_scope_type = 'department',
            target_scope_id = team.department_id::text,
            updated_at = CURRENT_TIMESTAMP
        FROM teams team
        WHERE route.target_scope_type = 'team'
          AND route.target_scope_id = team.id::text;
    """))
    # A PostgreSQL CHECK constraint also validates soft-deleted rows. These
    # retired manager grants cannot survive the department-only constraint,
    # so remove them after the deployment backup has preserved their audit
    # history. Team membership access itself is retained by compatibility
    # roles above.
    op.execute(sa.text("""
        DELETE FROM scope_manager_assignments
        WHERE scope_type = 'team';
    """))
    op.execute(sa.text("""
        UPDATE users
        SET team_id = NULL, auth_epoch = auth_epoch + 1, updated_at = CURRENT_TIMESTAMP
        WHERE team_id IS NOT NULL;
    """))
    # Conversation and asynchronous-job rows keep their department/user
    # ownership, so the retired membership dimension can be removed without
    # changing task history or generated artifacts.
    op.execute(sa.text("""
        UPDATE tasks
        SET team_id = NULL, updated_at = CURRENT_TIMESTAMP
        WHERE team_id IS NOT NULL;
    """))
    op.execute(sa.text("""
        UPDATE multimodal_jobs
        SET team_id = NULL, updated_at = CURRENT_TIMESTAMP
        WHERE team_id IS NOT NULL;
    """))
    op.execute(sa.text("""
        UPDATE teams
        SET deleted_at = COALESCE(deleted_at, CURRENT_TIMESTAMP),
            updated_at = CURRENT_TIMESTAMP
        WHERE deleted_at IS NULL;
    """))

    op.drop_constraint(
        "ck_enterprise_application_grant_scope_type",
        "enterprise_application_grants",
        type_="check",
    )
    op.create_check_constraint(
        "ck_enterprise_application_grant_scope_type",
        "enterprise_application_grants",
        "scope_type IN ('organization','department','user','role')",
    )
    op.drop_constraint(
        "ck_enterprise_application_event_route_scope_type",
        "enterprise_application_event_routes",
        type_="check",
    )
    op.create_check_constraint(
        "ck_enterprise_application_event_route_scope_type",
        "enterprise_application_event_routes",
        "target_scope_type IN ('organization','department','user')",
    )
    op.drop_constraint("ck_scope_manager_type", "scope_manager_assignments", type_="check")
    op.create_check_constraint(
        "ck_scope_manager_type",
        "scope_manager_assignments",
        "scope_type = 'department'",
    )

    # SaaS no longer owns business work items. A deployment-time database
    # backup preserves the retired history outside the active schema.
    op.drop_table("cross_department_work_items")


def downgrade() -> None:
    # Retired work-item rows and Team membership are intentionally not restored.
    # The downgrade recreates the old schema only for application compatibility.
    op.create_table(
        "cross_department_work_items",
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_application_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("route_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_event_id", sa.String(200), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="open"),
        sa.Column("target_scope_type", sa.String(20), nullable=False),
        sa.Column("target_scope_id", sa.String(36), nullable=True),
        sa.Column("target_module_key", sa.String(120), nullable=True),
        sa.Column(
            "source_context",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "status IN ('open','done')",
            name="ck_cross_department_work_item_status",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["source_application_id"],
            ["enterprise_applications.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["route_id"], ["enterprise_application_event_routes.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "route_id",
            "source_event_id",
            name="uq_cross_department_work_item_route_event",
        ),
    )
    op.create_index(
        "ix_cross_department_work_items_organization_id",
        "cross_department_work_items",
        ["organization_id"],
    )
    op.create_index(
        "ix_cross_department_work_items_source_application_id",
        "cross_department_work_items",
        ["source_application_id"],
    )
    op.create_index(
        "ix_cross_department_work_items_route_id",
        "cross_department_work_items",
        ["route_id"],
    )
    op.create_index(
        "ix_cross_department_work_items_target_scope_id",
        "cross_department_work_items",
        ["target_scope_id"],
    )
    op.drop_constraint("ck_scope_manager_type", "scope_manager_assignments", type_="check")
    op.create_check_constraint(
        "ck_scope_manager_type",
        "scope_manager_assignments",
        "scope_type IN ('department','team')",
    )
    op.drop_constraint(
        "ck_enterprise_application_event_route_scope_type",
        "enterprise_application_event_routes",
        type_="check",
    )
    op.create_check_constraint(
        "ck_enterprise_application_event_route_scope_type",
        "enterprise_application_event_routes",
        "target_scope_type IN ('organization','department','team','user')",
    )
    op.drop_constraint(
        "ck_enterprise_application_grant_scope_type",
        "enterprise_application_grants",
        type_="check",
    )
    op.create_check_constraint(
        "ck_enterprise_application_grant_scope_type",
        "enterprise_application_grants",
        "scope_type IN ('organization','department','team','user','role')",
    )
