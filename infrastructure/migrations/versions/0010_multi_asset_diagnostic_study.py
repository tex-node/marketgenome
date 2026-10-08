"""multi asset diagnostic study

Revision ID: 0010_multi_asset_diagnostic_study
Revises: 0009_retrieval_diagnostics
Create Date: 2026-08-02
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010_multi_asset_diagnostic_study"
down_revision: str | None = "0009_retrieval_diagnostics"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = postgresql.JSONB(astext_type=sa.Text())
REGISTRY_ID = postgresql.UUID(as_uuid=False).with_variant(sa.String(36), "sqlite")


def _index_many(table: str, columns: tuple[str, ...]) -> None:
    for column in columns:
        op.create_index(f"ix_{table}_{column}", table, [column])


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.alter_column(
            "alembic_version",
            "version_num",
            existing_type=sa.String(32),
            type_=sa.String(64),
            existing_nullable=False,
        )

    op.create_table(
        "study_manifests",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("study_code", sa.String(64), nullable=False),
        sa.Column("study_version", sa.String(64), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("configuration", JSONB, nullable=False),
        sa.Column("configuration_hash", sa.String(64), nullable=False),
        sa.Column("dataset_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(64), nullable=False),
        sa.Column("decision", sa.String(64), nullable=True),
        sa.Column("decision_rationale", sa.Text(), nullable=True),
        sa.Column("final_test_lock", JSONB, nullable=False),
        sa.Column("final_test_lock_hash", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    _index_many(
        "study_manifests",
        (
            "study_code",
            "study_version",
            "configuration_hash",
            "dataset_hash",
            "status",
            "decision",
            "final_test_lock_hash",
            "created_at",
        ),
    )

    op.create_table(
        "study_dataset_entries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("study_id", sa.String(36), nullable=False),
        sa.Column("instrument_id", REGISTRY_ID, nullable=False),
        sa.Column("timeframe_id", REGISTRY_ID, nullable=False),
        sa.Column("source_id", REGISTRY_ID, nullable=True),
        sa.Column("date_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("date_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("bar_count", sa.Integer(), nullable=False),
        sa.Column("window_count", sa.Integer(), nullable=False),
        sa.Column("episode_count", sa.Integer(), nullable=False),
        sa.Column("complete_outcome_rate", sa.Numeric(), nullable=False),
        sa.Column("quality_status", sa.String(64), nullable=False),
        sa.Column("inclusion_status", sa.String(64), nullable=False),
        sa.Column("exclusion_reason", sa.Text(), nullable=True),
        sa.Column("dataset_entry_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["study_id"], ["study_manifests.id"]),
        sa.ForeignKeyConstraint(["instrument_id"], ["instruments.id"]),
        sa.ForeignKeyConstraint(["timeframe_id"], ["timeframes.id"]),
    )
    _index_many(
        "study_dataset_entries",
        (
            "study_id",
            "instrument_id",
            "timeframe_id",
            "source_id",
            "quality_status",
            "inclusion_status",
            "dataset_entry_hash",
            "created_at",
        ),
    )

    op.create_table(
        "study_episodes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("study_id", sa.String(36), nullable=False),
        sa.Column("episode_id", sa.String(64), nullable=False),
        sa.Column("instrument_id", REGISTRY_ID, nullable=False),
        sa.Column("timeframe_id", REGISTRY_ID, nullable=False),
        sa.Column("episode_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("episode_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_count", sa.Integer(), nullable=False),
        sa.Column("outcome_span", sa.Integer(), nullable=False),
        sa.Column("episode_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["study_id"], ["study_manifests.id"]),
        sa.ForeignKeyConstraint(["instrument_id"], ["instruments.id"]),
        sa.ForeignKeyConstraint(["timeframe_id"], ["timeframes.id"]),
    )
    _index_many(
        "study_episodes",
        (
            "study_id",
            "episode_id",
            "instrument_id",
            "timeframe_id",
            "episode_start",
            "episode_end",
            "episode_hash",
            "created_at",
        ),
    )

    op.create_table(
        "study_preflights",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("study_id", sa.String(36), nullable=False),
        sa.Column("gate_code", sa.String(64), nullable=False),
        sa.Column("status", sa.String(64), nullable=False),
        sa.Column("actual_value", sa.String(255), nullable=False),
        sa.Column("required_value", sa.String(255), nullable=False),
        sa.Column("details", JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["study_id"], ["study_manifests.id"]),
    )
    _index_many("study_preflights", ("study_id", "gate_code", "status", "created_at"))

    op.create_table(
        "study_arms",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("study_id", sa.String(36), nullable=False),
        sa.Column("arm_code", sa.String(64), nullable=False),
        sa.Column("period_role", sa.String(64), nullable=False),
        sa.Column("status", sa.String(64), nullable=False),
        sa.Column("similarity_method", sa.String(64), nullable=True),
        sa.Column("baseline_methods", JSONB, nullable=False),
        sa.Column("episode_cap", sa.Integer(), nullable=True),
        sa.Column("metrics", JSONB, nullable=False),
        sa.Column("segments", JSONB, nullable=False),
        sa.Column("configuration_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["study_id"], ["study_manifests.id"]),
    )
    _index_many(
        "study_arms",
        (
            "study_id",
            "arm_code",
            "period_role",
            "status",
            "similarity_method",
            "configuration_hash",
            "created_at",
        ),
    )


def downgrade() -> None:
    op.drop_table("study_arms")
    op.drop_table("study_preflights")
    op.drop_table("study_episodes")
    op.drop_table("study_dataset_entries")
    op.drop_table("study_manifests")
