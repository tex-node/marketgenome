"""retrieval diagnostics

Revision ID: 0009_retrieval_diagnostics
Revises: 0008_validation_experiments
Create Date: 2026-07-26
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009_retrieval_diagnostics"
down_revision: str | None = "0008_validation_experiments"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.create_table(
        "diagnostic_artifacts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("experiment_run_id", sa.String(36), nullable=False),
        sa.Column("diagnostic_code", sa.String(64), nullable=False),
        sa.Column("artifact_type", sa.String(64), nullable=False),
        sa.Column("schema_version", sa.String(64), nullable=False),
        sa.Column("configuration_hash", sa.String(64), nullable=False),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column("artifact_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["experiment_run_id"], ["experiment_runs.id"]),
    )
    for column in (
        "experiment_run_id",
        "diagnostic_code",
        "artifact_type",
        "configuration_hash",
        "artifact_hash",
        "created_at",
    ):
        op.create_index(f"ix_diagnostic_artifacts_{column}", "diagnostic_artifacts", [column])

    op.create_table(
        "feature_scaling_snapshots",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("experiment_run_id", sa.String(36), nullable=True),
        sa.Column("scope", JSONB, nullable=False),
        sa.Column("feature_set_code", sa.String(64), nullable=False),
        sa.Column("feature_set_version", sa.String(64), nullable=False),
        sa.Column("date_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("date_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("historical_mode", sa.String(64), nullable=False),
        sa.Column("record_count", sa.Integer(), nullable=False),
        sa.Column("feature_statistics", JSONB, nullable=False),
        sa.Column("feature_availability", JSONB, nullable=False),
        sa.Column("configuration", JSONB, nullable=False),
        sa.Column("configuration_hash", sa.String(64), nullable=False),
        sa.Column("snapshot_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["experiment_run_id"], ["experiment_runs.id"]),
        sa.UniqueConstraint(
            "feature_set_code",
            "feature_set_version",
            "historical_mode",
            "configuration_hash",
            "snapshot_hash",
            name="uq_feature_scaling_snapshot_identity",
        ),
    )
    for column in (
        "experiment_run_id",
        "feature_set_code",
        "feature_set_version",
        "historical_mode",
        "configuration_hash",
        "snapshot_hash",
        "created_at",
    ):
        op.create_index(f"ix_feature_scaling_snapshots_{column}", "feature_scaling_snapshots", [column])


def downgrade() -> None:
    op.drop_table("feature_scaling_snapshots")
    op.drop_table("diagnostic_artifacts")
