"""Versioned business summary approval and durable architecture handoff."""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "summary_revisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("analysis_version", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column("markdown", sa.Text(), nullable=False),
        sa.Column("reviewer", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("project_id", "analysis_version", "revision"),
    )
    op.create_index("ix_summary_revisions_project_id", "summary_revisions", ["project_id"])
    op.create_table(
        "requirements_approvals",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("analysis_version", sa.Integer(), nullable=False),
        sa.Column("summary_revision", sa.Integer(), nullable=False),
        sa.Column("reviewer", sa.String(200), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("markdown", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("project_id", "analysis_version"),
    )
    op.create_index(
        "ix_requirements_approvals_project_id", "requirements_approvals", ["project_id"]
    )
    op.create_table(
        "architecture_handoffs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "approval_id",
            sa.String(36),
            sa.ForeignKey("requirements_approvals.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_architecture_handoffs_project_id", "architecture_handoffs", ["project_id"])


def downgrade() -> None:
    op.drop_table("architecture_handoffs")
    op.drop_table("requirements_approvals")
    op.drop_table("summary_revisions")
