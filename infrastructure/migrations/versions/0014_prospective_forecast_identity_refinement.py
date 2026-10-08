"""prospective forecast identity refinement

Revision ID: 0014_prospective_forecast_identity_refinement
Revises: 0013_prospective_context_validation
Create Date: 2026-08-22
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_prospective_forecast_identity_refinement"
down_revision: str | None = "0013_prospective_context_validation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Forecast identity: pattern_window_id already uniquely implies instrument,
    # timeframe, window length, and query timestamp (it references one immutable
    # PatternWindow row), so the prior identity boundary
    # (protocol_id, instrument_id, timeframe_id, window_length, forecast_timestamp,
    # horizon_bars) repeated information already carried by pattern_window_id and
    # relied on a datetime-equality join. Replaced with the smallest non-redundant
    # boundary: (protocol_id, pattern_window_id, horizon_bars, provenance_class) --
    # provenance_class is included so the same pattern_window/horizon can carry both
    # a TRUE_PROSPECTIVE forecast and, separately, a BACKFILL_SIMULATION or
    # HISTORICAL_VALIDATION one without colliding.
    with op.batch_alter_table("prospective_forecasts") as batch_op:
        batch_op.drop_constraint("uq_prospective_forecast_identity", type_="unique")
        batch_op.create_unique_constraint(
            "uq_prospective_forecast_identity",
            ["protocol_id", "pattern_window_id", "horizon_bars", "provenance_class"],
        )

    # Reference the existing immutable ForwardOutcome (OutcomeObservation) rather than
    # only duplicating its computation; source_outcome_hash lets maturation detect a
    # provider data revision without ever silently mutating the forecast/outcome.
    # prospective_forecast_outcomes is empty at this point (nothing has matured yet),
    # so these can be added as NOT NULL directly, matching the ORM model exactly.
    with op.batch_alter_table("prospective_forecast_outcomes") as batch_op:
        batch_op.add_column(sa.Column("source_forward_outcome_id", sa.String(36), nullable=False))
        batch_op.add_column(sa.Column("source_outcome_hash", sa.String(64), nullable=False))
        batch_op.create_foreign_key(
            "fk_prospective_forecast_outcomes_source_forward_outcome",
            "outcome_observations",
            ["source_forward_outcome_id"],
            ["id"],
        )
    op.create_index(
        "ix_prospective_forecast_outcomes_source_forward_outcome_id",
        "prospective_forecast_outcomes",
        ["source_forward_outcome_id"],
    )
    op.create_index(
        "ix_prospective_forecast_outcomes_source_outcome_hash", "prospective_forecast_outcomes", ["source_outcome_hash"]
    )

    with op.batch_alter_table("prospective_evaluation_snapshots") as batch_op:
        batch_op.add_column(sa.Column("balanced_accuracy", sa.Numeric(), nullable=True))
        batch_op.add_column(sa.Column("mcc", sa.Numeric(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("prospective_evaluation_snapshots") as batch_op:
        batch_op.drop_column("mcc")
        batch_op.drop_column("balanced_accuracy")

    op.drop_index("ix_prospective_forecast_outcomes_source_outcome_hash", table_name="prospective_forecast_outcomes")
    op.drop_index("ix_prospective_forecast_outcomes_source_forward_outcome_id", table_name="prospective_forecast_outcomes")
    with op.batch_alter_table("prospective_forecast_outcomes") as batch_op:
        batch_op.drop_constraint("fk_prospective_forecast_outcomes_source_forward_outcome", type_="foreignkey")
        batch_op.drop_column("source_outcome_hash")
        batch_op.drop_column("source_forward_outcome_id")

    with op.batch_alter_table("prospective_forecasts") as batch_op:
        batch_op.drop_constraint("uq_prospective_forecast_identity", type_="unique")
        batch_op.create_unique_constraint(
            "uq_prospective_forecast_identity",
            ["protocol_id", "instrument_id", "timeframe_id", "window_length", "forecast_timestamp", "horizon_bars"],
        )
