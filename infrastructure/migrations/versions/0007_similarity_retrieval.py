"""similarity retrieval

Revision ID: 0007_similarity_retrieval
Revises: 0006_forward_outcomes
Create Date: 2026-07-26
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007_similarity_retrieval"
down_revision: str | None = "0006_forward_outcomes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "similarity_queries",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("query_window_id", sa.String(length=36), nullable=False),
        sa.Column("query_normalized_pattern_id", sa.String(length=36), nullable=True),
        sa.Column("query_market_dna_id", sa.String(length=36), nullable=True),
        sa.Column("similarity_method_code", sa.String(length=64), nullable=False),
        sa.Column("similarity_method_version", sa.String(length=64), nullable=False),
        sa.Column("feature_set_code", sa.String(length=64), nullable=True),
        sa.Column("feature_set_version", sa.String(length=64), nullable=True),
        sa.Column("normalization_method", sa.String(length=64), nullable=True),
        sa.Column("normalization_version", sa.String(length=64), nullable=True),
        sa.Column("resampling_method", sa.String(length=32), nullable=True),
        sa.Column("resample_points", sa.Integer(), nullable=True),
        sa.Column("top_k", sa.Integer(), nullable=False),
        sa.Column("candidate_count", sa.Integer(), nullable=False),
        sa.Column("returned_match_count", sa.Integer(), nullable=False),
        sa.Column("temporal_policy", sa.String(length=64), nullable=False),
        sa.Column("configuration", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("configuration_hash", sa.String(length=64), nullable=False),
        sa.Column("query_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("elapsed_seconds", sa.Numeric(), nullable=True),
        sa.Column("diagnostics", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["query_window_id"], ["pattern_windows.id"]),
    )
    for column in (
        "query_window_id",
        "query_normalized_pattern_id",
        "query_market_dna_id",
        "similarity_method_code",
        "feature_set_code",
        "configuration_hash",
        "query_hash",
        "status",
        "created_at",
    ):
        op.create_index(f"ix_similarity_queries_{column}", "similarity_queries", [column])

    op.create_table(
        "similarity_matches",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("query_id", sa.String(length=36), nullable=False),
        sa.Column("query_window_id", sa.String(length=36), nullable=False),
        sa.Column("candidate_window_id", sa.String(length=36), nullable=False),
        sa.Column("candidate_normalized_pattern_id", sa.String(length=36), nullable=True),
        sa.Column("candidate_market_dna_id", sa.String(length=36), nullable=True),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("distance", sa.Numeric(), nullable=False),
        sa.Column("similarity_score", sa.Numeric(), nullable=False),
        sa.Column("similarity_method_code", sa.String(length=64), nullable=False),
        sa.Column("similarity_method_version", sa.String(length=64), nullable=False),
        sa.Column("configuration_hash", sa.String(length=64), nullable=False),
        sa.Column("query_source_hash", sa.String(length=64), nullable=False),
        sa.Column("candidate_source_hash", sa.String(length=64), nullable=False),
        sa.Column("query_vector_hash", sa.String(length=64), nullable=False),
        sa.Column("candidate_vector_hash", sa.String(length=64), nullable=False),
        sa.Column("component_scores", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("diagnostics", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("quality_flags", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["query_id"], ["similarity_queries.id"]),
        sa.ForeignKeyConstraint(["query_window_id"], ["pattern_windows.id"]),
        sa.ForeignKeyConstraint(["candidate_window_id"], ["pattern_windows.id"]),
        sa.UniqueConstraint(
            "query_id",
            "candidate_window_id",
            "similarity_method_code",
            "configuration_hash",
            name="uq_similarity_match_identity",
        ),
    )
    for column in (
        "query_id",
        "query_window_id",
        "candidate_window_id",
        "rank",
        "distance",
        "similarity_score",
        "similarity_method_code",
        "configuration_hash",
        "created_at",
    ):
        op.create_index(f"ix_similarity_matches_{column}", "similarity_matches", [column])


def downgrade() -> None:
    op.drop_table("similarity_matches")
    op.drop_table("similarity_queries")
