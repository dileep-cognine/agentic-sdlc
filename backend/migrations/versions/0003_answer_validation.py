"""Preserve semantic validation and explicit confirmation audit history."""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "answer_validation_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("question_id", sa.String(20), nullable=False),
        sa.Column("analysis_version", sa.Integer(), nullable=False),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.Column("assessment", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_answer_validation_events_project_id", "answer_validation_events", ["project_id"]
    )


def downgrade() -> None:
    op.drop_table("answer_validation_events")
