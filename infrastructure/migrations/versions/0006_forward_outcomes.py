"""forward outcomes

Revision ID: 0006_forward_outcomes
Revises: 0005_market_context
Create Date: 2026-07-26
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_forward_outcomes"
down_revision: str | None = "0005_market_context"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "outcome_builds",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("outcome_set_code", sa.String(length=64), nullable=False),
        sa.Column("outcome_set_version", sa.String(length=64), nullable=False),
        sa.Column("instrument_id", sa.String(length=36), nullable=True),
        sa.Column("timeframe_id", sa.String(length=36), nullable=True),
        sa.Column("window_length", sa.Integer(), nullable=True),
        sa.Column("start_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("requested_horizons", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("mode", sa.String(length=32), nullable=False),
        sa.Column("configuration", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("configuration_hash", sa.String(length=64), nullable=False),
        sa.Column("source_pattern_count", sa.Integer(), nullable=False),
        sa.Column("eligible_pattern_count", sa.Integer(), nullable=False),
        sa.Column("created_observation_count", sa.Integer(), nullable=False),
        sa.Column("existing_observation_count", sa.Integer(), nullable=False),
        sa.Column("partial_observation_count", sa.Integer(), nullable=False),
        sa.Column("skipped_pattern_count", sa.Integer(), nullable=False),
        sa.Column("failed_observation_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("elapsed_seconds", sa.Numeric(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    for column in ("status", "created_at", "outcome_set_code", "instrument_id", "timeframe_id"):
        op.create_index(f"ix_outcome_builds_{column}", "outcome_builds", [column])

    op.create_table(
        "outcome_observations",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("pattern_window_id", sa.String(length=36), nullable=False),
        sa.Column("instrument_id", sa.String(length=36), nullable=False),
        sa.Column("timeframe_id", sa.String(length=36), nullable=False),
        sa.Column("window_length", sa.Integer(), nullable=False),
        sa.Column("window_start_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("outcome_set_code", sa.String(length=64), nullable=False),
        sa.Column("outcome_set_version", sa.String(length=64), nullable=False),
        sa.Column("horizon_bars", sa.Integer(), nullable=False),
        sa.Column("available_future_bars", sa.Integer(), nullable=False),
        sa.Column("is_complete", sa.Boolean(), nullable=False),
        sa.Column("anchor_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("anchor_price", sa.Numeric(), nullable=False),
        sa.Column("first_future_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_future_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("future_simple_return", sa.Numeric(), nullable=True),
        sa.Column("future_log_return", sa.Numeric(), nullable=True),
        sa.Column("maximum_favourable_excursion", sa.Numeric(), nullable=True),
        sa.Column("maximum_adverse_excursion", sa.Numeric(), nullable=True),
        sa.Column("time_to_mfe_bars", sa.Integer(), nullable=True),
        sa.Column("time_to_mae_bars", sa.Integer(), nullable=True),
        sa.Column("future_realized_volatility", sa.Numeric(), nullable=True),
        sa.Column("future_path_efficiency", sa.Numeric(), nullable=True),
        sa.Column("future_maximum_drawdown", sa.Numeric(), nullable=True),
        sa.Column("future_maximum_runup", sa.Numeric(), nullable=True),
        sa.Column("direction_class", sa.String(length=32), nullable=False),
        sa.Column("continuation_reversal_class", sa.String(length=64), nullable=False),
        sa.Column("first_barrier_hit", sa.String(length=64), nullable=False),
        sa.Column("gain_before_drawdown", sa.String(length=64), nullable=False),
        sa.Column("drawdown_before_gain", sa.String(length=64), nullable=False),
        sa.Column("source_window_hash", sa.String(length=64), nullable=False),
        sa.Column("future_bar_hash", sa.String(length=64), nullable=False),
        sa.Column("configuration_hash", sa.String(length=64), nullable=False),
        sa.Column("outcome_hash", sa.String(length=64), nullable=False),
        sa.Column("scalar_values", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("forward_path", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("barrier_results", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("diagnostics", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("quality_flags", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("supersedes_observation_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["pattern_window_id"], ["pattern_windows.id"]),
        sa.UniqueConstraint(
            "pattern_window_id",
            "outcome_set_code",
            "outcome_set_version",
            "horizon_bars",
            "source_window_hash",
            "future_bar_hash",
            "configuration_hash",
            "is_complete",
            name="uq_outcome_observation_identity",
        ),
    )
    for column in (
        "pattern_window_id",
        "instrument_id",
        "timeframe_id",
        "window_length",
        "horizon_bars",
        "is_complete",
        "direction_class",
        "continuation_reversal_class",
        "first_barrier_hit",
        "window_end_timestamp",
        "outcome_hash",
        "created_at",
    ):
        op.create_index(f"ix_outcome_observations_{column}", "outcome_observations", [column])


def downgrade() -> None:
    op.drop_table("outcome_observations")
    op.drop_table("outcome_builds")
