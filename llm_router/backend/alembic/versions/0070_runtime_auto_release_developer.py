"""Add managed Runtime developer access and persistent administrator stops.

Revision ID: 0070_runtime_auto_release
Revises: 0069_retire_team_scope
Create Date: 2026-09-08
"""

import json

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0070_runtime_auto_release"
down_revision = "0069_retire_team_scope"
branch_labels = None
depends_on = None

RUNTIME_PERMISSIONS = [
    "ai_approve",
    "ai_create",
    "ai_delete",
    "ai_query",
    "ai_update",
    "export",
    "view",
]


def _manifest_access(manifest: object) -> tuple[list[str], dict]:
    if not isinstance(manifest, dict):
        return [], {}
    access: dict[str, dict] = {}
    for module in manifest.get("modules") or []:
        if not isinstance(module, dict) or not module.get("moduleKey"):
            continue
        module_key = str(module["moduleKey"])
        action_keys = [
            str(action["actionKey"])
            for action in (module.get("actions") or [])
            if isinstance(action, dict) and action.get("actionKey")
        ]
        pages = {}
        for page in module.get("pages") or []:
            if not isinstance(page, dict) or not page.get("pageKey"):
                continue
            pages[str(page["pageKey"])] = {
                "permissions": RUNTIME_PERMISSIONS,
                "action_keys": [str(key) for key in (page.get("actionKeys") or [])],
                "ai_enabled": True,
            }
        access[module_key] = {
            "role": "runtime_developer",
            "permissions": RUNTIME_PERMISSIONS,
            "action_keys": action_keys,
            "page_access": pages,
        }
    return list(access), access


def upgrade() -> None:
    op.add_column("roles", sa.Column("system_key", sa.String(100), nullable=True))
    op.create_unique_constraint(
        "uq_role_org_system_key", "roles", ["organization_id", "system_key"]
    )
    op.add_column(
        "enterprise_applications",
        sa.Column("admin_disabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "enterprise_application_actions",
        sa.Column("admin_disabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "enterprise_application_grants",
        sa.Column("managed_key", sa.String(100), nullable=True),
    )
    op.add_column(
        "enterprise_application_grants",
        sa.Column(
            "denied_resources",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.create_index(
        "ix_enterprise_application_grants_managed_key",
        "enterprise_application_grants",
        ["managed_key"],
    )

    op.execute(sa.text("""
        UPDATE roles SET system_key = code
        WHERE code IN ('enterprise_admin', 'employee') AND system_key IS NULL
    """))
    op.execute(sa.text("""
        UPDATE roles SET system_key = 'runtime_developer', is_builtin = true,
          name = '系统研发者', data_scope = 'all', is_active = true
        WHERE code = 'zj-runtime-developer' AND system_key IS NULL
    """))
    op.execute(sa.text("""
        DELETE FROM role_permissions permission
        USING roles role
        WHERE permission.role_id = role.id
          AND role.system_key = 'runtime_developer'
          AND permission.permission_code <> 'runtime.developer'
    """))
    op.execute(sa.text("""
        INSERT INTO roles (
          id, organization_id, name, code, system_key, description, data_scope,
          is_builtin, is_active, created_at, updated_at
        )
        SELECT gen_random_uuid(), organization.id, '系统研发者',
          'zj-runtime-developer', 'runtime_developer',
          '系统托管：查看和调试本企业 Runtime 发布的业务系统',
          'all', true, true, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        FROM organizations organization
        WHERE organization.deleted_at IS NULL
          AND NOT EXISTS (
            SELECT 1 FROM roles role
            WHERE role.organization_id = organization.id
              AND role.system_key = 'runtime_developer'
          )
    """))
    op.execute(sa.text("""
        INSERT INTO role_permissions (id, role_id, permission_code, created_at, updated_at)
        SELECT gen_random_uuid(), role.id, 'runtime.developer', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        FROM roles role
        WHERE role.system_key = 'runtime_developer'
          AND NOT EXISTS (
            SELECT 1 FROM role_permissions permission
            WHERE permission.role_id = role.id
              AND permission.permission_code = 'runtime.developer'
          )
    """))

    bind = op.get_bind()
    runtime_applications = bind.execute(sa.text("""
        SELECT application.id AS application_id,
               application.organization_id AS organization_id,
               role.id AS role_id,
               integration.manifest AS manifest
        FROM enterprise_applications application
        JOIN roles role
          ON role.organization_id = application.organization_id
         AND role.system_key = 'runtime_developer'
         AND role.deleted_at IS NULL
        LEFT JOIN enterprise_application_integrations integration
          ON integration.application_id = application.id
        WHERE application.deleted_at IS NULL
          AND application.assistant_config ->> 'deploymentManaged' = 'true'
    """)).mappings()
    for application in runtime_applications:
        module_keys, module_access = _manifest_access(application["manifest"])
        values = {
            "application_id": application["application_id"],
            "organization_id": application["organization_id"],
            "role_id": str(application["role_id"]),
            "permissions": json.dumps(RUNTIME_PERMISSIONS),
            "module_keys": json.dumps(module_keys),
            "module_access": json.dumps(module_access, ensure_ascii=False),
        }
        existing_id = bind.execute(sa.text("""
            SELECT id FROM enterprise_application_grants
            WHERE application_id = :application_id
              AND scope_type = 'role'
              AND scope_id = :role_id
        """), values).scalar_one_or_none()
        if existing_id is None:
            bind.execute(sa.text("""
                INSERT INTO enterprise_application_grants (
                  id, application_id, organization_id, scope_type, scope_id,
                  permissions, module_keys, module_access, managed_key,
                  denied_resources, created_at, updated_at
                ) VALUES (
                  gen_random_uuid(), :application_id, :organization_id, 'role', :role_id,
                  CAST(:permissions AS jsonb), CAST(:module_keys AS jsonb),
                  CAST(:module_access AS jsonb), 'runtime_developer', '{}'::jsonb,
                  CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                )
            """), values)
        else:
            bind.execute(sa.text("""
                UPDATE enterprise_application_grants
                SET organization_id = :organization_id,
                    permissions = CAST(:permissions AS jsonb),
                    module_keys = CAST(:module_keys AS jsonb),
                    module_access = CAST(:module_access AS jsonb),
                    managed_key = 'runtime_developer',
                    denied_resources = '{}'::jsonb,
                    deleted_at = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :existing_id
            """), {**values, "existing_id": existing_id})


def downgrade() -> None:
    op.drop_index(
        "ix_enterprise_application_grants_managed_key",
        table_name="enterprise_application_grants",
    )
    op.drop_column("enterprise_application_grants", "denied_resources")
    op.drop_column("enterprise_application_grants", "managed_key")
    op.drop_column("enterprise_application_actions", "admin_disabled")
    op.drop_column("enterprise_applications", "admin_disabled")
    op.drop_constraint("uq_role_org_system_key", "roles", type_="unique")
    op.drop_column("roles", "system_key")
