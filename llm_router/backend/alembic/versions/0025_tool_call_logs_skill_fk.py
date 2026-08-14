"""tool_call_logs.skill_id 外键修正

技能已文件夹化（0018-0020）：运行时 ``execute_endpoint`` 传入的 ``skill_id`` 实为
``skill_folders.id``，而 ``tool_call_logs.skill_id`` 的外键仍指向已废弃的旧 ``skills``
表，导致任何调用技能的任务在写日志时违反外键（``tool_call_logs_skill_id_fkey``）。

日志表的 ``skill_id`` 改为松散引用（不再强制外键）：技能文件夹可被删除，历史调用
日志不应因引用对象消失而无法留存。旧 ``skills`` 表内仅余 dummy 数据，不重指向
``skill_folders``（会因历史 legacy 行违反约束）。

Revision ID: 0025_tool_call_logs_skill_fk
Revises: 0024_agent_run_exec_mode
Create Date: 2026-06-30
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision = "0025_tool_call_logs_skill_fk"
down_revision = "0024_agent_run_exec_mode"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("tool_call_logs_skill_id_fkey", "tool_call_logs", type_="foreignkey")


def downgrade() -> None:
    op.create_foreign_key(
        "tool_call_logs_skill_id_fkey",
        "tool_call_logs",
        "skills",
        ["skill_id"],
        ["id"],
    )
