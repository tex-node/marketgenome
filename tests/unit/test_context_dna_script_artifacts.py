from __future__ import annotations

from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "run_context_dna_incremental_value.py"

REQUIRED_ARTIFACT_FILENAMES = (
    "report.md",
    "report.json",
    "protocol.json",
    "protocol_lock.json",
    "information_layer_summary.csv",
    "context_only_results.csv",
    "dna_within_context_results.csv",
    "paired_comparisons.csv",
    "instrument_results.csv",
    "asset_class_results.csv",
    "window_length_results.csv",
    "context_definition_results.csv",
    "candidate_coverage.csv",
    "episode_diversity.csv",
    "calibration.csv",
    "outcome_dispersion.csv",
    "bootstrap_confidence.csv",
    "query_exclusions.csv",
    "resource_usage.csv",
    "decision.json",
)


def test_run_script_writes_every_required_artifact_without_a_rerun() -> None:
    """Regression guard for the Step 10A.3 gap: bootstrap confidence intervals were
    computed and used in decision logic but never written as their own artifact,
    which would have required rerunning the whole experiment to recover them. This
    phase's run script must write every required artifact (including
    bootstrap_confidence.csv) unconditionally on every real (non-dry-run) execution."""
    source = SCRIPT_PATH.read_text(encoding="utf-8")

    # The write_csv/artifact block must not be dry_run-gated: the dry_run branch
    # returns before this point, so any call reached here always runs for real.
    real_run_section = source.split("if dry_run:", 1)[1]
    assert "return 0" in real_run_section  # confirms the dry-run early-return exists

    for filename in REQUIRED_ARTIFACT_FILENAMES:
        assert f'"{filename}"' in source, f"missing required artifact reference: {filename}"


def test_bootstrap_confidence_csv_is_written_from_the_same_bootstrap_rows_list() -> None:
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    assert 'write_csv(output_root / "bootstrap_confidence.csv", bootstrap_rows)' in source
    assert "paired_block_bootstrap(" in source


def test_candidate_universe_equality_is_enforced_before_ranking_or_sampling() -> None:
    """Regression guard: the DNA-ranking and context-random populations must be
    independently derived and explicitly checked for equality (assert_candidate_universe_equality
    raising CandidateUniverseMismatchError on divergence), not silently assumed equal."""
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    assert "assert_candidate_universe_equality(dna_population_ids, random_population_ids)" in source
    assert "except CandidateUniverseMismatchError:" in source
    assert '"reason": "BASELINE_UNIVERSE_MISMATCH"' in source

    # The equality check and both selection mechanisms must run in that order: the
    # try/except block appears before the DNA ranking and context-random sampling calls.
    equality_check_pos = source.index("assert_candidate_universe_equality(dna_population_ids, random_population_ids)")
    dna_ranking_pos = source.index("rank_dna(query, within_rows, episode_cap, k)")
    random_sampling_pos = source.index("context_random_estimate(\n                        random_population_ids")
    assert equality_check_pos < dna_ranking_pos
    assert equality_check_pos < random_sampling_pos


def test_primary_baseline_is_same_context_random_not_unconditional() -> None:
    """The Step 10A.4 primary comparison is DNA-within-context vs same_context_random_v1.
    Unconditional history is Level 0 reference only, not the primary baseline."""
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    assert "primary_baseline: same_context_random_v1" in (
        Path(__file__).resolve().parents[2] / "research" / "experiments" / "context_dna_incremental_value_v1.yaml"
    ).read_text(encoding="utf-8")
    # The paired comparison itself must be computed between the DNA and context-random
    # aggregates, not between DNA and the unconditional aggregate.
    assert "context_eval = evaluate(context_random_agg" in source
    assert '"brier_diff": context_eval["brier_score"] - dna_eval["brier_score"]' in source


def test_frozen_primary_configuration_values_are_hardcoded_correctly() -> None:
    """Guards against silently drifting K, episode cap, weighting, or timeframe away
    from the values frozen by the independent replication protocol this phase reuses."""
    config_path = Path(__file__).resolve().parents[2] / "research" / "experiments" / "context_dna_incremental_value_v1.yaml"
    config_text = config_path.read_text(encoding="utf-8")
    assert "timeframe: D1" in config_text
    assert "window_lengths: [16, 32, 64]" in config_text
    assert "outcome_horizon: 20" in config_text
    assert "method: dna_robust_cosine_v1" in config_text
    assert "k: 10" in config_text
    assert "weighting: uniform_v1" in config_text
    assert "episode_cap: 1" in config_text
    for definition in ("trend_volatility", "trend_volatility_persistence", "core_context", "context_family"):
        assert definition in config_text
