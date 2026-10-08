"""normalized patterns

Revision ID: 0003_normalized_patterns
Revises: 0002_registry_imports_windows
Create Date: 2026-07-26
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_normalized_patterns"
down_revision: str | None = "0002_registry_imports_windows"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "normalization_builds",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("normalization_method", sa.String(length=64), nullable=False),
        sa.Column("normalization_version", sa.String(length=64), nullable=False),
        sa.Column("resampling_method", sa.String(length=32), nullable=False),
        sa.Column("resample_points", sa.Integer(), nullable=False),
        sa.Column("source_window_version", sa.String(length=64), nullable=False),
        sa.Column("instrument_id", sa.String(length=36), nullable=True),
        sa.Column("timeframe_id", sa.String(length=36), nullable=True),
        sa.Column("window_length", sa.Integer(), nullable=True),
        sa.Column("start_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("mode", sa.String(length=32), nullable=False),
        sa.Column("configuration", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("configuration_hash", sa.String(length=64), nullable=False),
        sa.Column("source_window_count", sa.Integer(), nullable=False),
        sa.Column("created_representation_count", sa.Integer(), nullable=False),
        sa.Column("existing_representation_count", sa.Integer(), nullable=False),
        sa.Column("skipped_representation_count", sa.Integer(), nullable=False),
        sa.Column("failed_representation_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("elapsed_seconds", sa.Numeric(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_normalization_builds_status", "normalization_builds", ["status"])
    op.create_index("ix_normalization_builds_created_at", "normalization_builds", ["created_at"])
    op.create_index("ix_normalization_builds_normalization_method", "normalization_builds", ["normalization_method"])
    op.create_index("ix_normalization_builds_instrument_id", "normalization_builds", ["instrument_id"])
    op.create_index("ix_normalization_builds_timeframe_id", "normalization_builds", ["timeframe_id"])
    op.create_index("ix_normalization_builds_configuration_hash", "normalization_builds", ["configuration_hash"])

    op.create_table(
        "normalized_patterns",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("pattern_window_id", sa.String(length=36), nullable=False),
        sa.Column("normalization_method", sa.String(length=64), nullable=False),
        sa.Column("normalization_version", sa.String(length=64), nullable=False),
        sa.Column("resampling_method", sa.String(length=32), nullable=False),
        sa.Column("resample_points", sa.Integer(), nullable=False),
        sa.Column("source_window_hash", sa.String(length=64), nullable=False),
        sa.Column("configuration_hash", sa.String(length=64), nullable=False),
        sa.Column("representation_hash", sa.String(length=64), nullable=False),
        sa.Column("channel_schema", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("normalized_values", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("diagnostics", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("quality_flags", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["pattern_window_id"], ["pattern_windows.id"]),
        sa.UniqueConstraint(
            "pattern_window_id",
            "normalization_method",
            "normalization_version",
            "resampling_method",
            "resample_points",
            "configuration_hash",
            "source_window_hash",
            name="uq_normalized_pattern_identity",
        ),
    )
    op.create_index("ix_normalized_patterns_pattern_window_id", "normalized_patterns", ["pattern_window_id"])
    op.create_index("ix_normalized_patterns_normalization_method", "normalized_patterns", ["normalization_method"])
    op.create_index("ix_normalized_patterns_normalization_version", "normalized_patterns", ["normalization_version"])
    op.create_index("ix_normalized_patterns_resample_points", "normalized_patterns", ["resample_points"])
    op.create_index("ix_normalized_patterns_configuration_hash", "normalized_patterns", ["configuration_hash"])
    op.create_index("ix_normalized_patterns_representation_hash", "normalized_patterns", ["representation_hash"])
    op.create_index("ix_normalized_patterns_created_at", "normalized_patterns", ["created_at"])


def downgrade() -> None:
    op.drop_table("normalized_patterns")
    op.drop_table("normalization_builds")

