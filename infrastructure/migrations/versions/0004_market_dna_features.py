"""market dna features

Revision ID: 0004_market_dna_features
Revises: 0003_normalized_patterns
Create Date: 2026-07-26
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_market_dna_features"
down_revision: str | None = "0003_normalized_patterns"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "feature_builds",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("feature_set_code", sa.String(length=64), nullable=False),
        sa.Column("feature_set_version", sa.String(length=64), nullable=False),
        sa.Column("source_normalization_method", sa.String(length=64), nullable=False),
        sa.Column("source_normalization_version", sa.String(length=64), nullable=False),
        sa.Column("source_resampling_method", sa.String(length=32), nullable=False),
        sa.Column("source_resample_points", sa.Integer(), nullable=False),
        sa.Column("instrument_id", sa.String(length=36), nullable=True),
        sa.Column("timeframe_id", sa.String(length=36), nullable=True),
        sa.Column("window_length", sa.Integer(), nullable=True),
        sa.Column("start_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("mode", sa.String(length=32), nullable=False),
        sa.Column("configuration", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("configuration_hash", sa.String(length=64), nullable=False),
        sa.Column("source_pattern_count", sa.Integer(), nullable=False),
        sa.Column("created_feature_count", sa.Integer(), nullable=False),
        sa.Column("existing_feature_count", sa.Integer(), nullable=False),
        sa.Column("skipped_feature_count", sa.Integer(), nullable=False),
        sa.Column("failed_feature_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("elapsed_seconds", sa.Numeric(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_feature_builds_status", "feature_builds", ["status"])
    op.create_index("ix_feature_builds_created_at", "feature_builds", ["created_at"])
    op.create_index("ix_feature_builds_feature_set_code", "feature_builds", ["feature_set_code"])
    op.create_index("ix_feature_builds_instrument_id", "feature_builds", ["instrument_id"])
    op.create_index("ix_feature_builds_timeframe_id", "feature_builds", ["timeframe_id"])
    op.create_index("ix_feature_builds_configuration_hash", "feature_builds", ["configuration_hash"])

    op.create_table(
        "market_dna",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("pattern_window_id", sa.String(length=36), nullable=False),
        sa.Column("normalized_pattern_id", sa.String(length=36), nullable=False),
        sa.Column("feature_set_code", sa.String(length=64), nullable=False),
        sa.Column("feature_set_version", sa.String(length=64), nullable=False),
        sa.Column("source_window_hash", sa.String(length=64), nullable=False),
        sa.Column("source_representation_hash", sa.String(length=64), nullable=False),
        sa.Column("configuration_hash", sa.String(length=64), nullable=False),
        sa.Column("feature_vector_hash", sa.String(length=64), nullable=False),
        sa.Column("feature_count", sa.Integer(), nullable=False),
        sa.Column("available_feature_count", sa.Integer(), nullable=False),
        sa.Column("unavailable_feature_count", sa.Integer(), nullable=False),
        sa.Column("feature_vector", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("feature_values", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("availability", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("diagnostics", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("quality_flags", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["pattern_window_id"], ["pattern_windows.id"]),
        sa.ForeignKeyConstraint(["normalized_pattern_id"], ["normalized_patterns.id"]),
        sa.UniqueConstraint(
            "pattern_window_id",
            "normalized_pattern_id",
            "feature_set_code",
            "feature_set_version",
            "configuration_hash",
            "source_window_hash",
            "source_representation_hash",
            name="uq_market_dna_identity",
        ),
    )
    op.create_index("ix_market_dna_pattern_window_id", "market_dna", ["pattern_window_id"])
    op.create_index("ix_market_dna_normalized_pattern_id", "market_dna", ["normalized_pattern_id"])
    op.create_index("ix_market_dna_feature_set_code", "market_dna", ["feature_set_code"])
    op.create_index("ix_market_dna_feature_set_version", "market_dna", ["feature_set_version"])
    op.create_index("ix_market_dna_configuration_hash", "market_dna", ["configuration_hash"])
    op.create_index("ix_market_dna_feature_vector_hash", "market_dna", ["feature_vector_hash"])
    op.create_index("ix_market_dna_created_at", "market_dna", ["created_at"])


def downgrade() -> None:
    op.drop_table("market_dna")
    op.drop_table("feature_builds")

