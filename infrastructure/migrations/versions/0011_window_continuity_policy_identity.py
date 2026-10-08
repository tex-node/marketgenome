"""window continuity policy identity

Revision ID: 0011_window_continuity_policy_identity
Revises: 0010_multi_asset_diagnostic_study
Create Date: 2026-08-16
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0011_window_continuity_policy_identity"
down_revision: str | None = "0010_multi_asset_diagnostic_study"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("pattern_windows") as batch_op:
        batch_op.drop_constraint("uq_pattern_window_identity", type_="unique")
        batch_op.create_unique_constraint(
            "uq_pattern_window_identity",
            [
                "instrument_id",
                "timeframe_id",
                "end_timestamp",
                "window_length",
                "window_version",
                "source_data_hash",
                "build_configuration_hash",
            ],
        )


def downgrade() -> None:
    with op.batch_alter_table("pattern_windows") as batch_op:
        batch_op.drop_constraint("uq_pattern_window_identity", type_="unique")
        batch_op.create_unique_constraint(
            "uq_pattern_window_identity",
            [
                "instrument_id",
                "timeframe_id",
                "end_timestamp",
                "window_length",
                "window_version",
                "source_data_hash",
            ],
        )
