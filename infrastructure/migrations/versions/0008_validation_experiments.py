"""validation experiments

Revision ID: 0008_validation_experiments
Revises: 0007_similarity_retrieval
Create Date: 2026-07-26
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008_validation_experiments"
down_revision: str | None = "0007_similarity_retrieval"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


JSONB = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.create_table(
        "experiment_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("experiment_code", sa.String(64), nullable=False),
        sa.Column("experiment_version", sa.String(64), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("hypothesis", sa.Text(), nullable=True),
        sa.Column("status", sa.String(64), nullable=False),
        sa.Column("dataset_version", sa.String(64), nullable=False),
        sa.Column("dataset_hash", sa.String(64), nullable=False),
        sa.Column("code_version", JSONB, nullable=False),
        sa.Column("configuration", JSONB, nullable=False),
        sa.Column("configuration_hash", sa.String(64), nullable=False),
        sa.Column("run_nonce", sa.String(64), nullable=False),
        sa.Column("similarity_method", sa.String(64), nullable=False),
        sa.Column("baseline_methods", JSONB, nullable=False),
        sa.Column("outcome_set_code", sa.String(64), nullable=False),
        sa.Column("outcome_set_version", sa.String(64), nullable=False),
        sa.Column("outcome_horizons", JSONB, nullable=False),
        sa.Column("validation_method", sa.String(64), nullable=False),
        sa.Column("validation_configuration", JSONB, nullable=False),
        sa.Column("instrument_scope", JSONB, nullable=False),
        sa.Column("timeframe_scope", JSONB, nullable=False),
        sa.Column("window_length_scope", JSONB, nullable=False),
        sa.Column("date_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("date_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("parameter_grid", JSONB, nullable=False),
        sa.Column("multiple_testing_family", sa.String(128), nullable=True),
        sa.Column("decision", sa.String(64), nullable=True),
        sa.Column("summary", JSONB, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("elapsed_seconds", sa.Numeric(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "experiment_code",
            "experiment_version",
            "dataset_hash",
            "configuration_hash",
            "run_nonce",
            name="uq_experiment_run_identity",
        ),
    )
    for column in ("status", "created_at", "experiment_code", "experiment_version", "dataset_hash", "configuration_hash", "similarity_method", "outcome_set_code", "validation_method", "decision"):
        op.create_index(f"ix_experiment_runs_{column}", "experiment_runs", [column])

    op.create_table(
        "experiment_folds",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("experiment_run_id", sa.String(36), nullable=False),
        sa.Column("fold_number", sa.Integer(), nullable=False),
        sa.Column("index_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("index_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("validation_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("validation_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("test_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("test_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("purge_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("purge_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("embargo_bars", sa.Integer(), nullable=False),
        sa.Column("eligible_index_count", sa.Integer(), nullable=False),
        sa.Column("eligible_query_count", sa.Integer(), nullable=False),
        sa.Column("excluded_overlap_count", sa.Integer(), nullable=False),
        sa.Column("excluded_future_count", sa.Integer(), nullable=False),
        sa.Column("excluded_quality_count", sa.Integer(), nullable=False),
        sa.Column("configuration", JSONB, nullable=False),
        sa.Column("fold_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(64), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["experiment_run_id"], ["experiment_runs.id"]),
        sa.UniqueConstraint("experiment_run_id", "fold_number", name="uq_experiment_fold_number"),
    )
    for column in ("experiment_run_id", "fold_number", "test_start", "test_end", "fold_hash", "status", "created_at"):
        op.create_index(f"ix_experiment_folds_{column}", "experiment_folds", [column])

    op.create_table(
        "query_evaluations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("experiment_run_id", sa.String(36), nullable=False),
        sa.Column("fold_id", sa.String(36), nullable=False),
        sa.Column("query_window_id", sa.String(36), nullable=False),
        sa.Column("query_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("horizon_bars", sa.Integer(), nullable=False),
        sa.Column("similarity_method", sa.String(64), nullable=True),
        sa.Column("baseline_method", sa.String(64), nullable=True),
        sa.Column("neighbour_count", sa.Integer(), nullable=False),
        sa.Column("weighting_method", sa.String(64), nullable=False),
        sa.Column("eligible_candidate_count", sa.Integer(), nullable=False),
        sa.Column("retrieved_match_count", sa.Integer(), nullable=False),
        sa.Column("effective_match_count", sa.Numeric(), nullable=False),
        sa.Column("predicted_direction_probability", sa.Numeric(), nullable=True),
        sa.Column("predicted_return_mean", sa.Numeric(), nullable=True),
        sa.Column("predicted_return_median", sa.Numeric(), nullable=True),
        sa.Column("predicted_return_quantiles", JSONB, nullable=False),
        sa.Column("predicted_mfe_mean", sa.Numeric(), nullable=True),
        sa.Column("predicted_mae_mean", sa.Numeric(), nullable=True),
        sa.Column("scenario_probabilities", JSONB, nullable=False),
        sa.Column("actual_direction", sa.String(32), nullable=True),
        sa.Column("actual_return", sa.Numeric(), nullable=True),
        sa.Column("actual_mfe", sa.Numeric(), nullable=True),
        sa.Column("actual_mae", sa.Numeric(), nullable=True),
        sa.Column("direction_correct", sa.Boolean(), nullable=True),
        sa.Column("brier_component", sa.Numeric(), nullable=True),
        sa.Column("log_loss_component", sa.Numeric(), nullable=True),
        sa.Column("absolute_error", sa.Numeric(), nullable=True),
        sa.Column("squared_error", sa.Numeric(), nullable=True),
        sa.Column("quantile_losses", JSONB, nullable=False),
        sa.Column("query_context", JSONB, nullable=False),
        sa.Column("retrieved_context_distribution", JSONB, nullable=False),
        sa.Column("retrieval_diagnostics", JSONB, nullable=False),
        sa.Column("quality_flags", JSONB, nullable=False),
        sa.Column("configuration_hash", sa.String(64), nullable=False),
        sa.Column("evaluation_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["experiment_run_id"], ["experiment_runs.id"]),
        sa.ForeignKeyConstraint(["fold_id"], ["experiment_folds.id"]),
        sa.ForeignKeyConstraint(["query_window_id"], ["pattern_windows.id"]),
        sa.UniqueConstraint(
            "experiment_run_id",
            "fold_id",
            "query_window_id",
            "similarity_method",
            "baseline_method",
            "horizon_bars",
            "neighbour_count",
            "weighting_method",
            "configuration_hash",
            name="uq_query_evaluation_identity",
        ),
    )
    for column in ("experiment_run_id", "fold_id", "query_window_id", "horizon_bars", "similarity_method", "baseline_method", "weighting_method", "configuration_hash", "evaluation_hash", "created_at"):
        op.create_index(f"ix_query_evaluations_{column}", "query_evaluations", [column])

    op.create_table(
        "experiment_metrics",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("experiment_run_id", sa.String(36), nullable=False),
        sa.Column("fold_id", sa.String(36), nullable=True),
        sa.Column("metric_code", sa.String(64), nullable=False),
        sa.Column("metric_version", sa.String(64), nullable=False),
        sa.Column("value", sa.Numeric(), nullable=True),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("segment_type", sa.String(64), nullable=True),
        sa.Column("segment_value", sa.String(255), nullable=True),
        sa.Column("horizon_bars", sa.Integer(), nullable=True),
        sa.Column("similarity_method", sa.String(64), nullable=True),
        sa.Column("baseline_method", sa.String(64), nullable=True),
        sa.Column("confidence_interval_low", sa.Numeric(), nullable=True),
        sa.Column("confidence_interval_high", sa.Numeric(), nullable=True),
        sa.Column("standard_error", sa.Numeric(), nullable=True),
        sa.Column("p_value", sa.Numeric(), nullable=True),
        sa.Column("effect_size", sa.Numeric(), nullable=True),
        sa.Column("metric_metadata", JSONB, nullable=False),
        sa.Column("metric_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["experiment_run_id"], ["experiment_runs.id"]),
        sa.ForeignKeyConstraint(["fold_id"], ["experiment_folds.id"]),
    )
    for column in ("experiment_run_id", "fold_id", "metric_code", "horizon_bars", "segment_type", "segment_value", "similarity_method", "baseline_method", "metric_hash", "created_at"):
        op.create_index(f"ix_experiment_metrics_{column}", "experiment_metrics", [column])

    op.create_table(
        "experiment_artifacts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("experiment_run_id", sa.String(36), nullable=False),
        sa.Column("artifact_type", sa.String(64), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("artifact_metadata", JSONB, nullable=False),
        sa.Column("artifact_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["experiment_run_id"], ["experiment_runs.id"]),
    )
    for column in ("experiment_run_id", "artifact_type", "artifact_hash", "created_at"):
        op.create_index(f"ix_experiment_artifacts_{column}", "experiment_artifacts", [column])


def downgrade() -> None:
    op.drop_table("experiment_artifacts")
    op.drop_table("experiment_metrics")
    op.drop_table("query_evaluations")
    op.drop_table("experiment_folds")
    op.drop_table("experiment_runs")
