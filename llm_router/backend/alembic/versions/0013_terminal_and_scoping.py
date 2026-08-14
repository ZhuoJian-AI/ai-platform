"""terminal user portal + resource scoping + hierarchical memory

为组织终端用户端新增：
- users 增加 department_id / team_id 绑定（驱动资源 scope 过滤与 4 级记忆载入）
- skills / ontologies / rag_collections / workspaces 增加 scope_type + scope_id（仿 dlp_rules）
- agent_runs.agent_id 改 nullable，新增 task_id / user_id（终端通用智能体执行记录）
- 新表 memories（分级长期记忆：org/dept/team/user）、tasks / task_messages（终端任务线程）

Revision ID: 0013_terminal_and_scoping
Revises: 0012_admin_username
Create Date: 2026-06-29
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from pgvector.sqlalchemy import Vector

# revision identifiers
revision = "0013_terminal_and_scoping"
down_revision = "0012_admin_username"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── users: 终端用户作用域绑定 ──
    op.add_column(
        "users",
        sa.Column("department_id", sa.UUID(), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("team_id", sa.UUID(), nullable=True),
    )
    op.create_index("ix_users_department_id", "users", ["department_id"])
    op.create_index("ix_users_team_id", "users", ["team_id"])
    op.create_foreign_key(
        "fk_users_department_id", "users", "departments",
        ["department_id"], ["id"], ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_users_team_id", "users", "teams",
        ["team_id"], ["id"], ondelete="SET NULL",
    )

    # ── 资源 scope 字段（skills / ontologies / rag_collections / workspaces）──
    for table in ("skills", "ontologies", "rag_collections", "workspaces"):
        op.add_column(
            table,
            sa.Column("scope_type", sa.String(length=20), nullable=False, server_default="organization"),
        )
        op.add_column(
            table,
            sa.Column("scope_id", sa.String(length=36), nullable=True),
        )
        op.create_index(f"ix_{table}_scope_id", table, ["scope_id"])

    # ── memories: 分级长期记忆 ──
    op.create_table(
        "memories",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("scope_type", sa.String(length=20), nullable=False),
        sa.Column("scope_id", sa.String(length=36), nullable=True),
        sa.Column("category", sa.String(length=100), nullable=False, server_default="general"),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False, server_default="manual"),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("embedding", Vector(None), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_memories_organization_id", "memories", ["organization_id"])
    op.create_index("ix_memory_scope", "memories", ["organization_id", "scope_type", "scope_id"])

    # ── tasks / task_messages: 终端任务线程（先于 agent_runs.task_id FK）──
    op.create_table(
        "tasks",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("department_id", sa.UUID(), nullable=True),
        sa.Column("team_id", sa.UUID(), nullable=True),
        sa.Column("session_id", sa.String(length=128), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("message", sa.Text(), nullable=False, server_default=""),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["department_id"], ["departments.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_tasks_organization_id", "tasks", ["organization_id"])
    op.create_index("ix_tasks_user_id", "tasks", ["user_id"])
    op.create_index("ix_tasks_session_id", "tasks", ["session_id"])

    op.create_table(
        "task_messages",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("task_id", sa.UUID(), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_task_messages_task_id", "task_messages", ["task_id"])

    # ── agent_runs: agent_id 改 nullable + task_id / user_id ──
    op.alter_column("agent_runs", "agent_id", existing_type=sa.UUID(), nullable=True)
    op.add_column("agent_runs", sa.Column("task_id", sa.UUID(), nullable=True))
    op.add_column("agent_runs", sa.Column("user_id", sa.UUID(), nullable=True))
    op.create_index("ix_agent_runs_task_id", "agent_runs", ["task_id"])
    op.create_index("ix_agent_runs_user_id", "agent_runs", ["user_id"])
    op.create_foreign_key(
        "fk_agent_runs_task_id", "agent_runs", "tasks",
        ["task_id"], ["id"], ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_agent_runs_user_id", "agent_runs", "users",
        ["user_id"], ["id"], ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_agent_runs_user_id", "agent_runs", type_="foreignkey")
    op.drop_constraint("fk_agent_runs_task_id", "agent_runs", type_="foreignkey")
    op.drop_index("ix_agent_runs_user_id", table_name="agent_runs")
    op.drop_index("ix_agent_runs_task_id", table_name="agent_runs")
    op.drop_column("agent_runs", "user_id")
    op.drop_column("agent_runs", "task_id")
    op.alter_column("agent_runs", "agent_id", existing_type=sa.UUID(), nullable=False)

    op.drop_table("task_messages")
    op.drop_table("tasks")
    op.drop_table("memories")

    for table in ("skills", "ontologies", "rag_collections", "workspaces"):
        op.drop_index(f"ix_{table}_scope_id", table_name=table)
        op.drop_column(table, "scope_id")
        op.drop_column(table, "scope_type")

    op.drop_constraint("fk_users_team_id", "users", type_="foreignkey")
    op.drop_constraint("fk_users_department_id", "users", type_="foreignkey")
    op.drop_index("ix_users_team_id", table_name="users")
    op.drop_index("ix_users_department_id", table_name="users")
    op.drop_column("users", "team_id")
    op.drop_column("users", "department_id")
