"""primary-horizon evaluation and per-horizon metrics

Revision ID: 0015_primary_horizon_evaluation
Revises: 0014_prospective_forecast_identity_refinement
Create Date: 2026-09-12
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015_primary_horizon_evaluation"
down_revision: str | None = "0014_prospective_forecast_identity_refinement"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Evaluation-layer correction only -- no forecast/outcome/methodology change.
    # Snapshots previously pooled every horizon into one Brier score while using a
    # single unconditional baseline computed at the primary horizon; they now report the
    # primary horizon as the headline and persist every horizon's metrics separately.
    # All new columns are nullable so the pre-existing snapshots remain valid as-is.
    with op.batch_alter_table("prospective_evaluation_snapshots") as batch_op:
        batch_op.add_column(sa.Column("primary_horizon", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("primary_horizon_matured_count", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("bootstrap_ci_low", sa.Numeric(), nullable=True))
        batch_op.add_column(sa.Column("bootstrap_ci_high", sa.Numeric(), nullable=True))
        batch_op.add_column(sa.Column("per_horizon_metrics", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("prospective_evaluation_snapshots") as batch_op:
        batch_op.drop_column("per_horizon_metrics")
        batch_op.drop_column("bootstrap_ci_high")
        batch_op.drop_column("bootstrap_ci_low")
        batch_op.drop_column("primary_horizon_matured_count")
        batch_op.drop_column("primary_horizon")
