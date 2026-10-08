"""independent replication

Revision ID: 0012_independent_replication
Revises: 0011_window_continuity_policy_identity
Create Date: 2026-08-21
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012_independent_replication"
down_revision: str | None = "0011_window_continuity_policy_identity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = postgresql.JSONB(astext_type=sa.Text())


def _index_many(table: str, columns: tuple[str, ...]) -> None:
    for column in columns:
        op.create_index(f"ix_{table}_{column}", table, [column])


def upgrade() -> None:
    op.create_table(
        "replication_protocols",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("protocol_code", sa.String(64), nullable=False),
        sa.Column("protocol_version", sa.String(64), nullable=False),
        sa.Column("source_experiment_id", sa.String(36), nullable=False),
        sa.Column("source_config_hash", sa.String(64), nullable=False),
        sa.Column("source_dataset_hash", sa.String(64), nullable=False),
        sa.Column("hypothesis_text", sa.Text(), nullable=False),
        sa.Column("primary_method", sa.String(64), nullable=False),
        sa.Column("study_arm", sa.String(64), nullable=False),
        sa.Column("timeframe", sa.String(32), nullable=False),
        sa.Column("window_lengths", JSONB, nullable=False),
        sa.Column("primary_horizon", sa.Integer(), nullable=False),
        sa.Column("neighbour_count", sa.Integer(), nullable=False),
        sa.Column("weighting", sa.String(64), nullable=False),
        sa.Column("episode_cap", sa.Integer(), nullable=False),
        sa.Column("primary_metrics", JSONB, nullable=False),
        sa.Column("controls", JSONB, nullable=False),
        sa.Column("success_criteria", JSONB, nullable=False),
        sa.Column("failure_criteria", JSONB, nullable=False),
        sa.Column("independent_source_requirement", sa.String(64), nullable=False),
        sa.Column("configuration", JSONB, nullable=False),
        sa.Column("configuration_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(64), nullable=False),
        sa.Column("frozen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("frozen_by", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["source_experiment_id"], ["experiment_runs.id"]),
        sa.UniqueConstraint("protocol_code", "protocol_version", name="uq_replication_protocol_identity"),
    )
    _index_many(
        "replication_protocols",
        (
            "protocol_code",
            "protocol_version",
            "source_experiment_id",
            "source_config_hash",
            "source_dataset_hash",
            "primary_method",
            "study_arm",
            "configuration_hash",
            "status",
            "created_at",
        ),
    )

    op.create_table(
        "replication_locks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("protocol_id", sa.String(36), nullable=False),
        sa.Column("study_id", sa.String(36), nullable=False),
        sa.Column("source_study_id", sa.String(36), nullable=False),
        sa.Column("dataset_hash", sa.String(64), nullable=False),
        sa.Column("provider_code", sa.String(64), nullable=False),
        sa.Column("provider_provenance_hash", sa.String(64), nullable=False),
        sa.Column("instrument_universe", JSONB, nullable=False),
        sa.Column("date_range", JSONB, nullable=False),
        sa.Column("lock_payload", JSONB, nullable=False),
        sa.Column("lock_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(64), nullable=False),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("locked_by", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["protocol_id"], ["replication_protocols.id"]),
        sa.ForeignKeyConstraint(["study_id"], ["study_manifests.id"]),
        sa.ForeignKeyConstraint(["source_study_id"], ["study_manifests.id"]),
    )
    _index_many(
        "replication_locks",
        (
            "protocol_id",
            "study_id",
            "source_study_id",
            "dataset_hash",
            "provider_code",
            "provider_provenance_hash",
            "lock_hash",
            "status",
            "created_at",
        ),
    )

    op.create_table(
        "replication_records",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("protocol_id", sa.String(36), nullable=False),
        sa.Column("lock_id", sa.String(36), nullable=False),
        sa.Column("source_experiment_id", sa.String(36), nullable=False),
        sa.Column("replication_experiment_id", sa.String(36), nullable=True),
        sa.Column("provider_independence", sa.String(32), nullable=False),
        sa.Column("independence_notes", sa.Text(), nullable=True),
        sa.Column("decision", sa.String(64), nullable=False),
        sa.Column("decision_rationale", sa.Text(), nullable=True),
        sa.Column("comparison", JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["protocol_id"], ["replication_protocols.id"]),
        sa.ForeignKeyConstraint(["lock_id"], ["replication_locks.id"]),
        sa.ForeignKeyConstraint(["source_experiment_id"], ["experiment_runs.id"]),
        sa.ForeignKeyConstraint(["replication_experiment_id"], ["experiment_runs.id"]),
    )
    _index_many(
        "replication_records",
        (
            "protocol_id",
            "lock_id",
            "source_experiment_id",
            "replication_experiment_id",
            "provider_independence",
            "decision",
            "created_at",
        ),
    )


def downgrade() -> None:
    op.drop_table("replication_records")
    op.drop_table("replication_locks")
    op.drop_table("replication_protocols")
