"""Alembic migration environment configuration."""

import asyncio
from logging.config import fileConfig

from sqlalchemy import BigInteger, Integer, pool
from sqlalchemy.ext.asyncio import async_engine_from_config

# Import the model package for its registration side effects.  Keeping an
# explicit symbol list here made every compatibility-model retirement break
# Alembic before a migration could even connect to PostgreSQL.
import app.models  # noqa: F401
from alembic import context
from app.config import settings
from app.models.base import Base

config = context.config
config.set_main_option("sqlalchemy.url", settings.database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# The audited 0075 schema contains deliberately optimized partial/composite
# indexes that are not expressible through the simple ``index=True`` flags in
# the runtime ORM. These exact objects are owned by the migration schema. Keep
# them out of autogenerate comparison while continuing to detect every other
# drift.
_BASELINE_MANAGED_INDEXES = {
    ("enterprise_application_event_deliveries", "ix_ea_event_deliveries_event"),
    ("enterprise_application_event_deliveries", "ix_ea_event_deliveries_org"),
    ("enterprise_application_event_deliveries", "ix_ea_event_deliveries_route"),
    ("enterprise_application_event_deliveries", "ix_ea_event_deliveries_target"),
    (
        "enterprise_application_event_deliveries",
        "ix_enterprise_application_event_deliveries_organization_id",
    ),
    (
        "enterprise_application_event_deliveries",
        "ix_enterprise_application_event_deliveries_route_id",
    ),
    (
        "enterprise_application_event_deliveries",
        "ix_enterprise_application_event_deliveries_source_event_id",
    ),
    (
        "enterprise_application_event_deliveries",
        "ix_enterprise_application_event_deliveries_target_application_id",
    ),
    ("enterprise_application_grants", "ix_enterprise_application_grants_managed_key"),
    ("enterprise_application_grants", "ix_enterprise_application_grants_scope"),
    ("enterprise_applications", "ix_enterprise_applications_active_order"),
    ("organizations", "uq_organizations_is_default"),
    ("organizations", "uq_organizations_name_active"),
    ("organizations", "uq_organizations_slug_active"),
    ("tasks", "ix_tasks_department_id"),
    ("voice_profile_grants", "ix_voice_profile_grants_organization_id"),
    ("workspace_share_links", "ix_workspace_share_links_token_hash"),
}

_BASELINE_MANAGED_UNIQUE_CONSTRAINTS = {
    ("role_data_departments", "uq_role_data_department"),
    ("user_roles", "uq_user_role"),
    ("workspace_share_links", "uq_workspace_share_token_hash"),
}

_BASELINE_BIGINT_ADMIN_FOREIGN_KEYS = {
    ("workspace_audit_events", "actor_admin_id"),
    ("workspace_file_versions", "created_by_admin_id"),
    ("workspace_files", "deleted_by_admin_id"),
    ("workspace_share_links", "created_by_admin_id"),
    ("workspace_upload_sessions", "admin_id"),
}


def _include_baseline_object(object_, name, type_, reflected, compare_to):
    del reflected, compare_to
    table_name = getattr(getattr(object_, "table", None), "name", None)
    identity = (table_name, name)
    if type_ == "index" and identity in _BASELINE_MANAGED_INDEXES:
        return False
    if type_ == "unique_constraint" and identity in _BASELINE_MANAGED_UNIQUE_CONSTRAINTS:
        return False
    return True


def _compare_baseline_type(
    context_, inspected_column, metadata_column, inspected_type, metadata_type
):
    del context_, metadata_column
    identity = (inspected_column.table.name, inspected_column.name)
    if (
        identity in _BASELINE_BIGINT_ADMIN_FOREIGN_KEYS
        and isinstance(inspected_type, BigInteger)
        and isinstance(metadata_type, Integer)
    ):
        return False
    return None


_AUTOGENERATE_OPTIONS = {
    "include_object": _include_baseline_object,
    "compare_type": _compare_baseline_type,
}


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        **_AUTOGENERATE_OPTIONS,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        **_AUTOGENERATE_OPTIONS,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations in 'online' mode with async engine."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
