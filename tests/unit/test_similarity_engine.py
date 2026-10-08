from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from market_genome_domain.models import MarketContext, MarketDNA, NormalizedPattern, PatternWindow
from market_genome_similarity.definitions import list_similarity_methods
from market_genome_similarity.service import SimilarityInput, compute_similarity


def _window(identifier: str, end_offset: int = 0) -> PatternWindow:
    return PatternWindow(
        id=identifier,
        instrument_id="instrument",
        timeframe_id="H1",
        start_timestamp=datetime(2024, 1, 1, tzinfo=UTC),
        end_timestamp=datetime(2024, 1, 1, tzinfo=UTC) + timedelta(hours=end_offset),
        start_bar_id="start",
        end_bar_id="end",
        window_length=4,
        stride=1,
        bar_count=4,
        source_data_hash=f"source-{identifier}",
        build_configuration_hash="build",
        quality_flags=[],
    )


def _normalized(window_id: str, values: list[float]) -> NormalizedPattern:
    return NormalizedPattern(
        id=f"norm-{window_id}",
        pattern_window_id=window_id,
        normalization_method="anchored_log_return",
        normalization_version="normalization_v1",
        resampling_method="linear",
        resample_points=len(values),
        source_window_hash=f"source-{window_id}",
        configuration_hash="config",
        representation_hash=f"repr-{window_id}",
        channel_schema={"channels": ["close"], "points": len(values)},
        normalized_values={"close": values},
        diagnostics={},
        quality_flags=[],
    )


def _dna(window_id: str, values: dict[str, float | None]) -> MarketDNA:
    ordered = list(values)
    return MarketDNA(
        id=f"dna-{window_id}",
        pattern_window_id=window_id,
        normalized_pattern_id=f"norm-{window_id}",
        feature_set_code="market_dna_v1",
        feature_set_version="market_dna_v1",
        source_window_hash=f"source-{window_id}",
        source_representation_hash=f"repr-{window_id}",
        configuration_hash="feature-config",
        feature_vector_hash=f"dna-hash-{window_id}",
        feature_count=len(ordered),
        available_feature_count=sum(1 for value in values.values() if value is not None),
        unavailable_feature_count=sum(1 for value in values.values() if value is None),
        feature_vector={"ordered_features": ordered, "values": list(values.values())},
        feature_values=values,
        availability={},
        diagnostics={},
        quality_flags=[],
    )


def _context(window_id: str, trend: str = "UP") -> MarketContext:
    return MarketContext(
        id=f"context-{window_id}",
        pattern_window_id=window_id,
        normalized_pattern_id=f"norm-{window_id}",
        market_dna_id=f"dna-{window_id}",
        context_producer_code="transparent_context_v1",
        context_producer_version="transparent_context_v1",
        feature_set_code="market_dna_v1",
        feature_set_version="market_dna_v1",
        source_window_hash=f"source-{window_id}",
        source_representation_hash=f"repr-{window_id}",
        source_feature_vector_hash=f"dna-hash-{window_id}",
        configuration_hash="context-config",
        context_hash=f"context-hash-{window_id}",
        trend_state=trend,
        volatility_state="NORMAL",
        volatility_phase_state="STABLE",
        persistence_state="NEUTRAL",
        activity_state="NORMAL",
        shock_state="NONE",
        market_phase_state="TRENDING",
        multi_resolution_state="UNAVAILABLE",
        trend_confidence=1.0,
        volatility_confidence=1.0,
        volatility_phase_confidence=1.0,
        persistence_confidence=1.0,
        activity_confidence=1.0,
        shock_confidence=1.0,
        market_phase_confidence=1.0,
        multi_resolution_confidence=0.0,
        composite_context_code="UP|NORMAL",
        context_family_code="TRENDING",
        composite_confidence=1.0,
        completeness_score=1.0,
        dimension_scores={},
        evidence={},
        opposing_evidence={},
        diagnostics={},
        multi_resolution_links={},
        quality_flags=[],
    )


def _input(identifier: str, values: list[float], features: dict[str, float | None]) -> SimilarityInput:
    return SimilarityInput(
        window=_window(identifier),
        normalized_pattern=_normalized(identifier, values),
        market_dna=_dna(identifier, features),
        market_context=_context(identifier),
    )


def test_similarity_methods_do_not_use_future_outcomes() -> None:
    assert list_similarity_methods()
    assert all(not method.uses_future_outcomes for method in list_similarity_methods())


def test_shape_similarity_orders_identical_path_above_different_path() -> None:
    query = _input("q", [0.0, 0.1, 0.2, 0.3], {"a": 1.0, "b": 2.0})
    same = _input("same", [0.0, 0.1, 0.2, 0.3], {"a": 1.0, "b": 2.0})
    different = _input("different", [0.0, -0.1, -0.2, -0.3], {"a": 1.0, "b": 2.0})

    same_score = compute_similarity(query, same, "shape_euclidean_v1")
    different_score = compute_similarity(query, different, "shape_euclidean_v1")

    assert same_score.distance == pytest.approx(0.0)
    assert same_score.similarity_score > different_score.similarity_score


def test_dna_cosine_uses_only_common_available_features() -> None:
    query = _input("q", [0.0, 0.1], {"a": 1.0, "b": 0.0, "c": None})
    candidate = _input("c", [0.0, 0.1], {"a": 1.0, "b": 0.0, "c": 100.0})

    score = compute_similarity(query, candidate, "dna_cosine_v1", {"minimum_common_features": 2})

    assert score.distance == pytest.approx(0.0)
    assert score.component_scores["common_feature_count"] == 2


def test_market_analogue_includes_context_component() -> None:
    query = _input("q", [0.0, 0.1], {"a": 1.0, "b": 2.0})
    candidate = _input("c", [0.0, 0.1], {"a": 1.0, "b": 2.0})
    candidate.market_context.trend_state = "DOWN"

    score = compute_similarity(query, candidate, "market_analogue_v1")

    assert score.component_scores["context_distance"] > 0.0
    assert score.distance > 0.0
