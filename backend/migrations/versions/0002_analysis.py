"""Versioned analysis, clarification answers and transactional graph runtime."""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "requirement_versions",
        sa.Column("source_data", sa.JSON(), nullable=False, server_default="[]"),
    )
    op.create_table(
        "analysis_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("source_version", sa.Integer(), nullable=False),
        sa.Column("document", sa.JSON(), nullable=False),
        sa.Column("answers", sa.JSON(), nullable=False),
        sa.Column("sources", sa.JSON(), nullable=False),
        sa.Column("summary", sa.JSON(), nullable=True),
        sa.Column("markdown", sa.Text(), nullable=True),
        sa.Column("usage", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("project_id", "version"),
    )
    op.create_index("ix_analysis_versions_project_id", "analysis_versions", ["project_id"])
    op.create_table(
        "clarification_answers",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("question_id", sa.String(20), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("analysis_version", sa.Integer(), nullable=False),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("project_id", "question_id", "revision"),
    )
    op.create_index("ix_clarification_answers_project_id", "clarification_answers", ["project_id"])
    op.create_table(
        "graph_runtime",
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), primary_key=True),
        sa.Column("payload", sa.JSON(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("graph_runtime")
    op.drop_table("clarification_answers")
    op.drop_table("analysis_versions")
    op.drop_column("requirement_versions", "source_data")
