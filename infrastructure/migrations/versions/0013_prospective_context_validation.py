"""prospective context validation

Revision ID: 0013_prospective_context_validation
Revises: 0012_independent_replication
Create Date: 2026-08-21
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013_prospective_context_validation"
down_revision: str | None = "0012_independent_replication"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = postgresql.JSONB(astext_type=sa.Text())


def _index_many(table: str, columns: tuple[str, ...]) -> None:
    for column in columns:
        op.create_index(f"ix_{table}_{column}", table, [column])


def upgrade() -> None:
    op.create_table(
        "prospective_protocols",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("protocol_code", sa.String(64), nullable=False),
        sa.Column("protocol_version", sa.String(64), nullable=False),
        sa.Column("source_replication_protocol_id", sa.String(36), nullable=False),
        sa.Column("source_replication_experiment_id", sa.String(36), nullable=False),
        sa.Column("hypothesis_text", sa.Text(), nullable=False),
        sa.Column("context_definition", sa.String(64), nullable=False),
        sa.Column("context_producer_code", sa.String(64), nullable=False),
        sa.Column("context_producer_version", sa.String(64), nullable=False),
        sa.Column("fallback_hierarchy", JSONB, nullable=False),
        sa.Column("timeframe", sa.String(32), nullable=False),
        sa.Column("window_lengths", JSONB, nullable=False),
        sa.Column("primary_horizon", sa.Integer(), nullable=False),
        sa.Column("secondary_horizons", JSONB, nullable=False),
        sa.Column("probability_method", sa.String(64), nullable=False),
        sa.Column("smoothing_method", sa.String(64), nullable=False),
        sa.Column("smoothing_parameters", JSONB, nullable=False),
        sa.Column("minimum_historical_sample", sa.Integer(), nullable=False),
        sa.Column("calibration_method", sa.String(64), nullable=False),
        sa.Column("refresh_policy", sa.String(64), nullable=False),
        sa.Column("provider_code", sa.String(64), nullable=False),
        sa.Column("instrument_universe", JSONB, nullable=False),
        sa.Column("success_criteria", JSONB, nullable=False),
        sa.Column("minimum_evidence_matured_forecasts", sa.Integer(), nullable=False),
        sa.Column("preferred_evidence_matured_forecasts", sa.Integer(), nullable=False),
        sa.Column("configuration", JSONB, nullable=False),
        sa.Column("configuration_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(64), nullable=False),
        sa.Column("frozen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("frozen_by", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["source_replication_protocol_id"], ["replication_protocols.id"]),
        sa.ForeignKeyConstraint(["source_replication_experiment_id"], ["experiment_runs.id"]),
        sa.UniqueConstraint("protocol_code", "protocol_version", name="uq_prospective_protocol_identity"),
    )
    _index_many(
        "prospective_protocols",
        (
            "protocol_code", "protocol_version", "source_replication_protocol_id", "source_replication_experiment_id",
            "context_definition", "configuration_hash", "status", "created_at",
        ),
    )

    op.create_table(
        "prospective_forecasts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("protocol_id", sa.String(36), nullable=False),
        sa.Column("instrument_id", sa.String(36), nullable=False),
        sa.Column("timeframe_id", sa.String(36), nullable=False),
        sa.Column("window_length", sa.Integer(), nullable=False),
        sa.Column("pattern_window_id", sa.String(36), nullable=False),
        sa.Column("forecast_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("data_cutoff_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("forecast_created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("horizon_bars", sa.Integer(), nullable=False),
        sa.Column("context_code", sa.String(512), nullable=False),
        sa.Column("context_level_used", sa.String(64), nullable=False),
        sa.Column("fallback_reason", sa.String(128), nullable=True),
        sa.Column("probability_positive", sa.Numeric(), nullable=False),
        sa.Column("probability_negative", sa.Numeric(), nullable=False),
        sa.Column("expected_return", sa.Numeric(), nullable=True),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("positive_count", sa.Integer(), nullable=False),
        sa.Column("negative_count", sa.Integer(), nullable=False),
        sa.Column("confidence_lower", sa.Numeric(), nullable=False),
        sa.Column("confidence_upper", sa.Numeric(), nullable=False),
        sa.Column("provenance_class", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column("context_hash", sa.String(64), nullable=False),
        sa.Column("historical_reference_hash", sa.String(64), nullable=False),
        sa.Column("forecast_hash", sa.String(64), nullable=False),
        sa.Column("provider_code", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["protocol_id"], ["prospective_protocols.id"]),
        sa.ForeignKeyConstraint(["pattern_window_id"], ["pattern_windows.id"]),
        sa.UniqueConstraint(
            "protocol_id", "instrument_id", "timeframe_id", "window_length", "forecast_timestamp", "horizon_bars",
            name="uq_prospective_forecast_identity",
        ),
    )
    _index_many(
        "prospective_forecasts",
        (
            "protocol_id", "instrument_id", "timeframe_id", "window_length", "pattern_window_id", "forecast_timestamp", "data_cutoff_timestamp",
            "forecast_created_at", "horizon_bars", "context_level_used", "provenance_class", "status",
            "source_hash", "context_hash", "historical_reference_hash", "forecast_hash", "created_at",
        ),
    )

    op.create_table(
        "prospective_forecast_outcomes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("forecast_id", sa.String(36), nullable=False),
        sa.Column("actual_return", sa.Numeric(), nullable=False),
        sa.Column("actual_direction", sa.String(16), nullable=False),
        sa.Column("maximum_favourable_excursion", sa.Numeric(), nullable=True),
        sa.Column("maximum_adverse_excursion", sa.Numeric(), nullable=True),
        sa.Column("future_bar_count", sa.Integer(), nullable=False),
        sa.Column("outcome_hash", sa.String(64), nullable=False),
        sa.Column("data_revision_detected", sa.Boolean(), nullable=False),
        sa.Column("matured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["forecast_id"], ["prospective_forecasts.id"]),
        sa.UniqueConstraint("forecast_id", name="uq_prospective_forecast_outcome_identity"),
    )
    _index_many(
        "prospective_forecast_outcomes",
        ("forecast_id", "actual_direction", "outcome_hash", "matured_at", "created_at"),
    )

    op.create_table(
        "prospective_evaluation_snapshots",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("protocol_id", sa.String(36), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("forecast_count", sa.Integer(), nullable=False),
        sa.Column("matured_count", sa.Integer(), nullable=False),
        sa.Column("brier_score", sa.Numeric(), nullable=True),
        sa.Column("brier_skill_vs_unconditional", sa.Numeric(), nullable=True),
        sa.Column("log_loss", sa.Numeric(), nullable=True),
        sa.Column("expected_calibration_error", sa.Numeric(), nullable=True),
        sa.Column("direction_accuracy", sa.Numeric(), nullable=True),
        sa.Column("calibration_bins", JSONB, nullable=False),
        sa.Column("status", sa.String(64), nullable=False),
        sa.Column("snapshot_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["protocol_id"], ["prospective_protocols.id"]),
    )
    _index_many("prospective_evaluation_snapshots", ("protocol_id", "as_of", "status", "snapshot_hash", "created_at"))


def downgrade() -> None:
    op.drop_table("prospective_evaluation_snapshots")
    op.drop_table("prospective_forecast_outcomes")
    op.drop_table("prospective_forecasts")
    op.drop_table("prospective_protocols")
