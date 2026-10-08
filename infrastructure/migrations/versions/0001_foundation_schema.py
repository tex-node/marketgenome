"""foundation schema

Revision ID: 0001_foundation_schema
Revises:
Create Date: 2026-07-26
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_foundation_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "instruments",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("symbol", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("asset_class", sa.String(length=32), nullable=False),
        sa.Column("exchange", sa.String(length=64), nullable=True),
        sa.Column("currency", sa.String(length=16), nullable=True),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("tick_size", sa.Numeric(), nullable=True),
        sa.Column("price_precision", sa.Integer(), nullable=True),
        sa.Column("volume_type", sa.String(length=32), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("instrument_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_instruments_symbol", "instruments", ["symbol"], unique=True)

    op.create_table(
        "timeframes",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("seconds", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(length=64), nullable=False),
        sa.Column("is_intraday", sa.Boolean(), nullable=False),
    )
    op.create_index("ix_timeframes_code", "timeframes", ["code"], unique=True)

    op.create_table(
        "data_sources",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("source_type", sa.String(length=64), nullable=False),
        sa.Column("configuration_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    )
    op.create_index("ix_data_sources_name", "data_sources", ["name"], unique=True)

    op.create_table(
        "price_bars",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("instrument_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("timeframe_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("open", sa.Numeric(), nullable=False),
        sa.Column("high", sa.Numeric(), nullable=False),
        sa.Column("low", sa.Numeric(), nullable=False),
        sa.Column("close", sa.Numeric(), nullable=False),
        sa.Column("volume", sa.Numeric(), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("data_quality_flags", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(["instrument_id"], ["instruments.id"]),
        sa.ForeignKeyConstraint(["timeframe_id"], ["timeframes.id"]),
        sa.ForeignKeyConstraint(["source_id"], ["data_sources.id"]),
        sa.UniqueConstraint(
            "instrument_id",
            "timeframe_id",
            "timestamp",
            "source_id",
            name="uq_price_bar_identity",
        ),
    )
    op.create_index("ix_price_bars_instrument_id", "price_bars", ["instrument_id"])
    op.create_index("ix_price_bars_timeframe_id", "price_bars", ["timeframe_id"])
    op.create_index("ix_price_bars_source_id", "price_bars", ["source_id"])
    op.create_index("ix_price_bars_timestamp", "price_bars", ["timestamp"])


def downgrade() -> None:
    op.drop_table("price_bars")
    op.drop_table("data_sources")
    op.drop_table("timeframes")
    op.drop_table("instruments")

