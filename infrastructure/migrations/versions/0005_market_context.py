"""market context

Revision ID: 0005_market_context
Revises: 0004_market_dna_features
Create Date: 2026-07-26
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_market_context"
down_revision: str | None = "0004_market_dna_features"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "context_builds",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("context_producer_code", sa.String(length=64), nullable=False),
        sa.Column("context_producer_version", sa.String(length=64), nullable=False),
        sa.Column("feature_set_code", sa.String(length=64), nullable=False),
        sa.Column("feature_set_version", sa.String(length=64), nullable=False),
        sa.Column("instrument_id", sa.String(length=36), nullable=True),
        sa.Column("timeframe_id", sa.String(length=36), nullable=True),
        sa.Column("window_length", sa.Integer(), nullable=True),
        sa.Column("start_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("mode", sa.String(length=32), nullable=False),
        sa.Column("configuration", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("configuration_hash", sa.String(length=64), nullable=False),
        sa.Column("source_market_dna_count", sa.Integer(), nullable=False),
        sa.Column("created_context_count", sa.Integer(), nullable=False),
        sa.Column("existing_context_count", sa.Integer(), nullable=False),
        sa.Column("partial_context_count", sa.Integer(), nullable=False),
        sa.Column("skipped_context_count", sa.Integer(), nullable=False),
        sa.Column("failed_context_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("elapsed_seconds", sa.Numeric(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    for column in ("status", "created_at", "context_producer_code", "instrument_id", "timeframe_id"):
        op.create_index(f"ix_context_builds_{column}", "context_builds", [column])

    op.create_table(
        "market_contexts",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("pattern_window_id", sa.String(length=36), nullable=False),
        sa.Column("normalized_pattern_id", sa.String(length=36), nullable=False),
        sa.Column("market_dna_id", sa.String(length=36), nullable=False),
        sa.Column("context_producer_code", sa.String(length=64), nullable=False),
        sa.Column("context_producer_version", sa.String(length=64), nullable=False),
        sa.Column("feature_set_code", sa.String(length=64), nullable=False),
        sa.Column("feature_set_version", sa.String(length=64), nullable=False),
        sa.Column("source_window_hash", sa.String(length=64), nullable=False),
        sa.Column("source_representation_hash", sa.String(length=64), nullable=False),
        sa.Column("source_feature_vector_hash", sa.String(length=64), nullable=False),
        sa.Column("configuration_hash", sa.String(length=64), nullable=False),
        sa.Column("context_hash", sa.String(length=64), nullable=False),
        sa.Column("trend_state", sa.String(length=64), nullable=False),
        sa.Column("volatility_state", sa.String(length=64), nullable=False),
        sa.Column("volatility_phase_state", sa.String(length=64), nullable=False),
        sa.Column("persistence_state", sa.String(length=64), nullable=False),
        sa.Column("activity_state", sa.String(length=64), nullable=False),
        sa.Column("shock_state", sa.String(length=64), nullable=False),
        sa.Column("market_phase_state", sa.String(length=64), nullable=False),
        sa.Column("multi_resolution_state", sa.String(length=64), nullable=False),
        sa.Column("trend_confidence", sa.Numeric(), nullable=False),
        sa.Column("volatility_confidence", sa.Numeric(), nullable=False),
        sa.Column("volatility_phase_confidence", sa.Numeric(), nullable=False),
        sa.Column("persistence_confidence", sa.Numeric(), nullable=False),
        sa.Column("activity_confidence", sa.Numeric(), nullable=False),
        sa.Column("shock_confidence", sa.Numeric(), nullable=False),
        sa.Column("market_phase_confidence", sa.Numeric(), nullable=False),
        sa.Column("multi_resolution_confidence", sa.Numeric(), nullable=False),
        sa.Column("composite_context_code", sa.String(length=512), nullable=False),
        sa.Column("context_family_code", sa.String(length=128), nullable=False),
        sa.Column("composite_confidence", sa.Numeric(), nullable=False),
        sa.Column("completeness_score", sa.Numeric(), nullable=False),
        sa.Column("dimension_scores", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("opposing_evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("diagnostics", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("multi_resolution_links", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("quality_flags", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["pattern_window_id"], ["pattern_windows.id"]),
        sa.ForeignKeyConstraint(["normalized_pattern_id"], ["normalized_patterns.id"]),
        sa.ForeignKeyConstraint(["market_dna_id"], ["market_dna.id"]),
        sa.UniqueConstraint(
            "pattern_window_id",
            "normalized_pattern_id",
            "market_dna_id",
            "context_producer_code",
            "context_producer_version",
            "configuration_hash",
            "source_window_hash",
            "source_representation_hash",
            "source_feature_vector_hash",
            name="uq_market_context_identity",
        ),
    )
    for column in (
        "pattern_window_id",
        "market_dna_id",
        "context_producer_code",
        "context_producer_version",
        "trend_state",
        "volatility_state",
        "persistence_state",
        "activity_state",
        "shock_state",
        "market_phase_state",
        "multi_resolution_state",
        "context_family_code",
        "composite_context_code",
        "composite_confidence",
        "context_hash",
        "created_at",
    ):
        op.create_index(f"ix_market_contexts_{column}", "market_contexts", [column])


def downgrade() -> None:
    op.drop_table("market_contexts")
    op.drop_table("context_builds")
