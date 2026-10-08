"""registry imports and window engine

Revision ID: 0002_registry_imports_windows
Revises: 0001_foundation_schema
Create Date: 2026-07-26
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_registry_imports_windows"
down_revision: str | None = "0001_foundation_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index("ix_instruments_symbol", table_name="instruments")
    op.create_index("ix_instruments_symbol", "instruments", ["symbol"], unique=False)
    op.create_unique_constraint(
        "uq_instrument_symbol_exchange",
        "instruments",
        ["symbol", "exchange"],
    )
    op.alter_column("timeframes", "seconds", existing_type=sa.Integer(), nullable=True)
    op.create_index(
        "ix_price_bars_instrument_timeframe_timestamp",
        "price_bars",
        ["instrument_id", "timeframe_id", "timestamp"],
        unique=False,
    )

    op.create_table(
        "data_imports",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("instrument_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("timeframe_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("source_hash", sa.String(length=64), nullable=False),
        sa.Column("configuration_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("dry_run", sa.Boolean(), nullable=False),
        sa.Column("rows_read", sa.Integer(), nullable=False),
        sa.Column("rows_valid", sa.Integer(), nullable=False),
        sa.Column("rows_inserted", sa.Integer(), nullable=False),
        sa.Column("rows_updated", sa.Integer(), nullable=False),
        sa.Column("rows_skipped", sa.Integer(), nullable=False),
        sa.Column("warnings_count", sa.Integer(), nullable=False),
        sa.Column("errors_count", sa.Integer(), nullable=False),
        sa.Column("quality_summary", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("configuration", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["instrument_id"], ["instruments.id"]),
        sa.ForeignKeyConstraint(["timeframe_id"], ["timeframes.id"]),
        sa.ForeignKeyConstraint(["source_id"], ["data_sources.id"]),
        sa.UniqueConstraint(
            "source_hash",
            "configuration_hash",
            name="uq_data_import_source_configuration",
        ),
    )
    op.create_index("ix_data_imports_instrument_id", "data_imports", ["instrument_id"])
    op.create_index("ix_data_imports_timeframe_id", "data_imports", ["timeframe_id"])
    op.create_index("ix_data_imports_source_id", "data_imports", ["source_id"])
    op.create_index("ix_data_imports_source_hash", "data_imports", ["source_hash"])
    op.create_index("ix_data_imports_configuration_hash", "data_imports", ["configuration_hash"])
    op.create_index("ix_data_imports_status", "data_imports", ["status"])

    op.create_table(
        "data_import_issues",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("import_id", sa.String(length=36), nullable=False),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("issue_type", sa.String(length=64), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["import_id"], ["data_imports.id"]),
    )
    op.create_index("ix_data_import_issues_import_id", "data_import_issues", ["import_id"])
    op.create_index("ix_data_import_issues_row_number", "data_import_issues", ["row_number"])
    op.create_index("ix_data_import_issues_severity", "data_import_issues", ["severity"])
    op.create_index("ix_data_import_issues_issue_type", "data_import_issues", ["issue_type"])

    op.create_table(
        "pattern_windows",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("instrument_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("timeframe_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("start_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("start_bar_id", sa.String(length=36), nullable=False),
        sa.Column("end_bar_id", sa.String(length=36), nullable=False),
        sa.Column("window_length", sa.Integer(), nullable=False),
        sa.Column("stride", sa.Integer(), nullable=False),
        sa.Column("bar_count", sa.Integer(), nullable=False),
        sa.Column("window_version", sa.String(length=64), nullable=False),
        sa.Column("source_data_hash", sa.String(length=64), nullable=False),
        sa.Column("build_configuration_hash", sa.String(length=64), nullable=False),
        sa.Column("is_complete", sa.Boolean(), nullable=False),
        sa.Column("quality_flags", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["instrument_id"], ["instruments.id"]),
        sa.ForeignKeyConstraint(["timeframe_id"], ["timeframes.id"]),
        sa.UniqueConstraint(
            "instrument_id",
            "timeframe_id",
            "end_timestamp",
            "window_length",
            "window_version",
            "source_data_hash",
            name="uq_pattern_window_identity",
        ),
    )
    op.create_index("ix_pattern_windows_instrument_id", "pattern_windows", ["instrument_id"])
    op.create_index("ix_pattern_windows_timeframe_id", "pattern_windows", ["timeframe_id"])
    op.create_index("ix_pattern_windows_start_timestamp", "pattern_windows", ["start_timestamp"])
    op.create_index("ix_pattern_windows_end_timestamp", "pattern_windows", ["end_timestamp"])
    op.create_index("ix_pattern_windows_start_bar_id", "pattern_windows", ["start_bar_id"])
    op.create_index("ix_pattern_windows_end_bar_id", "pattern_windows", ["end_bar_id"])
    op.create_index("ix_pattern_windows_window_length", "pattern_windows", ["window_length"])
    op.create_index("ix_pattern_windows_window_version", "pattern_windows", ["window_version"])
    op.create_index("ix_pattern_windows_source_data_hash", "pattern_windows", ["source_data_hash"])
    op.create_index(
        "ix_pattern_windows_build_configuration_hash",
        "pattern_windows",
        ["build_configuration_hash"],
    )
    op.create_index(
        "ix_pattern_windows_lookup",
        "pattern_windows",
        ["instrument_id", "timeframe_id", "end_timestamp", "window_length", "window_version"],
    )

    op.create_table(
        "window_builds",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("instrument_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("timeframe_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("requested_lengths", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("stride", sa.Integer(), nullable=False),
        sa.Column("start_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("window_version", sa.String(length=64), nullable=False),
        sa.Column("mode", sa.String(length=32), nullable=False),
        sa.Column("configuration", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("configuration_hash", sa.String(length=64), nullable=False),
        sa.Column("source_bar_count", sa.Integer(), nullable=False),
        sa.Column("candidate_windows", sa.Integer(), nullable=False),
        sa.Column("created_window_count", sa.Integer(), nullable=False),
        sa.Column("existing_window_count", sa.Integer(), nullable=False),
        sa.Column("skipped_window_count", sa.Integer(), nullable=False),
        sa.Column("incomplete_window_count", sa.Integer(), nullable=False),
        sa.Column("quality_warning_window_count", sa.Integer(), nullable=False),
        sa.Column("first_window_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_window_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("elapsed_seconds", sa.Numeric(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["instrument_id"], ["instruments.id"]),
        sa.ForeignKeyConstraint(["timeframe_id"], ["timeframes.id"]),
    )
    op.create_index("ix_window_builds_instrument_id", "window_builds", ["instrument_id"])
    op.create_index("ix_window_builds_timeframe_id", "window_builds", ["timeframe_id"])
    op.create_index("ix_window_builds_configuration_hash", "window_builds", ["configuration_hash"])
    op.create_index("ix_window_builds_status", "window_builds", ["status"])
    op.create_index("ix_window_builds_created_at", "window_builds", ["created_at"])


def downgrade() -> None:
    op.drop_table("window_builds")
    op.drop_table("pattern_windows")
    op.drop_table("data_import_issues")
    op.drop_table("data_imports")
    op.drop_index("ix_price_bars_instrument_timeframe_timestamp", table_name="price_bars")
    op.alter_column("timeframes", "seconds", existing_type=sa.Integer(), nullable=False)
    op.drop_constraint("uq_instrument_symbol_exchange", "instruments", type_="unique")
    op.drop_index("ix_instruments_symbol", table_name="instruments")
    op.create_index("ix_instruments_symbol", "instruments", ["symbol"], unique=True)

