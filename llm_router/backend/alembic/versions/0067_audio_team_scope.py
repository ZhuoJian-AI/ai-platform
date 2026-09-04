"""Persist the team quota scope on asynchronous audio jobs.

Revision ID: 0067_audio_team_scope
Revises: 0066_ai_quota_ledger
Create Date: 2026-09-04

Existing jobs remain valid with a NULL team_id. New jobs capture the caller's
team so delayed workers enforce the same organization/department/team budget
hierarchy that applied when the logical request was created.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0067_audio_team_scope"
down_revision = "0066_ai_quota_ledger"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "multimodal_jobs",
        sa.Column("team_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_multimodal_jobs_team_id_teams",
        "multimodal_jobs",
        "teams",
        ["team_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_multimodal_jobs_team_id",
        "multimodal_jobs",
        ["team_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_multimodal_jobs_team_id", table_name="multimodal_jobs")
    op.drop_constraint(
        "fk_multimodal_jobs_team_id_teams",
        "multimodal_jobs",
        type_="foreignkey",
    )
    op.drop_column("multimodal_jobs", "team_id")
