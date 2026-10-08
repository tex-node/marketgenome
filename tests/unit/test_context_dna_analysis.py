from __future__ import annotations

import random

import pytest
from market_genome_replication.context_dna_analysis import (
    CONTEXT_DEFINITIONS,
    CandidateUniverseMismatchError,
    assert_candidate_universe_equality,
    candidate_universe_hash,
    classify_candidate_sufficiency,
    classify_context_dna_decision,
    context_dimensions_for,
    deterministic_context_random_draws,
    filter_by_context,
    information_layer_table,
    matches_context,
    paired_block_bootstrap,
    paired_differences_summary,
)


def test_context_dimensions_for_known_and_unknown_definitions() -> None:
    assert context_dimensions_for("trend_volatility") == ("trend_state", "volatility_state")
    assert context_dimensions_for("core_context") == (
        "trend_state",
        "volatility_state",
        "persistence_state",
        "shock_state",
    )
    assert context_dimensions_for("context_family") == ("context_family_code",)
    assert set(CONTEXT_DEFINITIONS) == {
        "trend_volatility",
        "trend_volatility_persistence",
        "core_context",
        "context_family",
    }
    with pytest.raises(ValueError, match="UNSUPPORTED_CONTEXT_DEFINITION"):
        context_dimensions_for("everything")


def test_matches_context_requires_all_dims_equal_and_non_null() -> None:
    query = {"trend_state": "UP", "volatility_state": "HIGH"}
    same = {"trend_state": "UP", "volatility_state": "HIGH"}
    different = {"trend_state": "UP", "volatility_state": "LOW"}
    missing = {"trend_state": "UP", "volatility_state": None}
    dims = ("trend_state", "volatility_state")

    assert matches_context(query, same, dims) is True
    assert matches_context(query, different, dims) is False
    assert matches_context(query, missing, dims) is False


def test_filter_by_context_returns_only_matching_candidate_ids() -> None:
    candidate_ids = ["a", "b", "c"]
    contexts = [
        {"trend_state": "UP", "volatility_state": "HIGH"},
        {"trend_state": "DOWN", "volatility_state": "HIGH"},
        {"trend_state": "UP", "volatility_state": "HIGH"},
    ]
    query_context = {"trend_state": "UP", "volatility_state": "HIGH"}

    result = filter_by_context(candidate_ids, contexts, query_context, ("trend_state", "volatility_state"))

    assert result == ["a", "c"]


def test_classify_candidate_sufficiency_thresholds() -> None:
    assert classify_candidate_sufficiency(5) == "INSUFFICIENT_WITHIN_CONTEXT_SAMPLE"
    assert classify_candidate_sufficiency(19) == "INSUFFICIENT_WITHIN_CONTEXT_SAMPLE"
    assert classify_candidate_sufficiency(20) == "MARGINAL_WITHIN_CONTEXT_SAMPLE"
    assert classify_candidate_sufficiency(29) == "MARGINAL_WITHIN_CONTEXT_SAMPLE"
    assert classify_candidate_sufficiency(30) == "ADEQUATE_WITHIN_CONTEXT_SAMPLE"
    assert classify_candidate_sufficiency(1000) == "ADEQUATE_WITHIN_CONTEXT_SAMPLE"


def test_candidate_universe_hash_is_order_independent_and_deterministic() -> None:
    ids_a = ["z", "a", "m"]
    ids_b = ["a", "m", "z"]
    assert candidate_universe_hash(ids_a) == candidate_universe_hash(ids_b)
    assert candidate_universe_hash(ids_a) != candidate_universe_hash(["a", "m"])


def test_assert_candidate_universe_equality_passes_for_identical_populations() -> None:
    dna_ids = ["a", "b", "c"]
    random_ids = ["c", "a", "b"]  # same set, different order -- must still match

    result_hash = assert_candidate_universe_equality(dna_ids, random_ids)

    assert result_hash == candidate_universe_hash(dna_ids)


def test_assert_candidate_universe_equality_raises_on_divergence() -> None:
    dna_ids = ["a", "b", "c"]
    random_ids = ["a", "b", "d"]  # one id differs -- must be caught, not silently ignored

    with pytest.raises(CandidateUniverseMismatchError, match="BASELINE_UNIVERSE_MISMATCH"):
        assert_candidate_universe_equality(dna_ids, random_ids)


def test_deterministic_context_random_draws_do_not_use_builtin_hash() -> None:
    """Regression guard: seeds must come from a stable, deterministic derivation
    (sha256-based upstream, then a plain integer combination here), never from
    Python's process-randomized built-in hash()."""
    import inspect

    source = inspect.getsource(deterministic_context_random_draws)
    assert "hash(" not in source


def test_deterministic_context_random_draws_are_reproducible_and_bounded() -> None:
    pool = [f"c{i}" for i in range(50)]
    draws_first = deterministic_context_random_draws(pool, k=10, repetitions=5, seed_base=1729)
    draws_second = deterministic_context_random_draws(pool, k=10, repetitions=5, seed_base=1729)
    draws_different_seed = deterministic_context_random_draws(pool, k=10, repetitions=5, seed_base=42)

    assert draws_first == draws_second
    assert len(draws_first) == 5
    assert all(len(draw) == 10 for draw in draws_first)
    assert all(set(draw) <= set(pool) for draw in draws_first)
    assert draws_first != draws_different_seed


def test_deterministic_context_random_draws_handles_small_pool() -> None:
    pool = ["a", "b", "c"]
    draws = deterministic_context_random_draws(pool, k=10, repetitions=3, seed_base=1)
    assert all(sorted(draw) == sorted(pool) for draw in draws)


def test_paired_differences_summary_empty_and_nonempty() -> None:
    assert paired_differences_summary([]) == {"mean": 0.0, "median": 0.0}
    summary = paired_differences_summary([1.0, 2.0, 3.0])
    assert summary["mean"] == 2.0
    assert summary["median"] == 2.0


def test_paired_block_bootstrap_ci_brackets_a_clear_positive_effect() -> None:
    differences = [0.05] * 200
    result = paired_block_bootstrap(differences, seed=1729, iterations=200)
    assert result.mean == pytest.approx(0.05)
    assert result.low > 0.0
    assert result.high > 0.0


def test_paired_block_bootstrap_ci_overlaps_zero_for_noisy_no_effect_data() -> None:
    rng = random.Random(7)
    differences = [rng.gauss(0.0, 1.0) for _ in range(200)]
    result = paired_block_bootstrap(differences, seed=1729, iterations=200)
    assert result.low < 0.0 < result.high


def test_information_layer_table_computes_skill_vs_prior_layer() -> None:
    levels = [
        {"layer": "unconditional", "brier": 0.30},
        {"layer": "context", "brier": 0.27},
        {"layer": "context_plus_dna", "brier": 0.27},
    ]
    table = information_layer_table(levels)

    assert table[0]["skill_vs_prior_layer"] is None
    assert table[1]["skill_vs_prior_layer"] == pytest.approx(1.0 - 0.27 / 0.30)
    assert table[2]["skill_vs_prior_layer"] == pytest.approx(0.0)


def test_classify_context_dna_decision_adds_value() -> None:
    result = classify_context_dna_decision(
        context_supported=True,
        dna_incremental_brier_skill=0.05,
        dna_ci_low=0.01,
        dna_ci_high=0.09,
        consistent_across_instruments=True,
        consistent_across_window_scales=True,
        mixed_by_asset=False,
        mixed_by_context_definition=False,
        sufficient_evidence=True,
    )
    assert result.decision == "CONTEXT_SIGNAL_SUPPORTED_DNA_ADDS_VALUE"


def test_classify_context_dna_decision_no_incremental_value() -> None:
    result = classify_context_dna_decision(
        context_supported=True,
        dna_incremental_brier_skill=-0.005,
        dna_ci_low=-0.02,
        dna_ci_high=0.01,
        consistent_across_instruments=True,
        consistent_across_window_scales=True,
        mixed_by_asset=False,
        mixed_by_context_definition=False,
        sufficient_evidence=True,
    )
    assert result.decision == "CONTEXT_SIGNAL_SUPPORTED_DNA_NO_INCREMENTAL_VALUE"


def test_classify_context_dna_decision_weak_when_ci_overlaps_zero() -> None:
    result = classify_context_dna_decision(
        context_supported=True,
        dna_incremental_brier_skill=0.03,
        dna_ci_low=-0.01,
        dna_ci_high=0.07,
        consistent_across_instruments=True,
        consistent_across_window_scales=True,
        mixed_by_asset=False,
        mixed_by_context_definition=False,
        sufficient_evidence=True,
    )
    assert result.decision == "CONTEXT_SIGNAL_SUPPORTED_DNA_INCREMENTAL_VALUE_WEAK"


def test_classify_context_dna_decision_context_not_supported() -> None:
    result = classify_context_dna_decision(
        context_supported=False,
        dna_incremental_brier_skill=0.03,
        dna_ci_low=0.01,
        dna_ci_high=0.05,
        consistent_across_instruments=True,
        consistent_across_window_scales=True,
        mixed_by_asset=False,
        mixed_by_context_definition=False,
        sufficient_evidence=True,
    )
    assert result.decision == "CONTEXT_SIGNAL_NOT_SUPPORTED"


def test_classify_context_dna_decision_inconclusive_when_insufficient_evidence() -> None:
    result = classify_context_dna_decision(
        context_supported=True,
        dna_incremental_brier_skill=0.03,
        dna_ci_low=0.01,
        dna_ci_high=0.05,
        consistent_across_instruments=True,
        consistent_across_window_scales=True,
        mixed_by_asset=False,
        mixed_by_context_definition=False,
        sufficient_evidence=False,
    )
    assert result.decision == "INCONCLUSIVE_SAMPLE_LIMITED"


def test_classify_context_dna_decision_mixed_by_asset_takes_priority() -> None:
    result = classify_context_dna_decision(
        context_supported=True,
        dna_incremental_brier_skill=0.05,
        dna_ci_low=0.01,
        dna_ci_high=0.09,
        consistent_across_instruments=True,
        consistent_across_window_scales=True,
        mixed_by_asset=True,
        mixed_by_context_definition=False,
        sufficient_evidence=True,
    )
    assert result.decision == "RESULT_MIXED_BY_ASSET"


def test_classify_context_dna_decision_mixed_by_context_definition() -> None:
    result = classify_context_dna_decision(
        context_supported=True,
        dna_incremental_brier_skill=0.05,
        dna_ci_low=0.01,
        dna_ci_high=0.09,
        consistent_across_instruments=True,
        consistent_across_window_scales=True,
        mixed_by_asset=False,
        mixed_by_context_definition=True,
        sufficient_evidence=True,
    )
    assert result.decision == "RESULT_MIXED_BY_CONTEXT"
