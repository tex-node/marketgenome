from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from market_genome_domain.models import PatternWindow
from market_genome_studies.definitions import list_study_arm_definitions, list_study_definitions
from market_genome_studies.service import (
    quality_state,
    study_decision,
    temporal_episode_gap,
)


def _window(index: int, instrument_id: str = "inst-1") -> PatternWindow:
    start = datetime(2024, 1, 1, tzinfo=UTC) + timedelta(hours=index)
    return PatternWindow(
        id=f"{instrument_id}-{index}",
        instrument_id=instrument_id,
        timeframe_id="tf-1",
        start_timestamp=start,
        end_timestamp=start + timedelta(hours=7),
        start_bar_id=f"b-{index}",
        end_bar_id=f"b-{index + 7}",
        window_length=8,
        bar_count=8,
        source_data_hash=f"h-{instrument_id}-{index}",
        build_configuration_hash="cfg",
        is_complete=True,
        quality_flags=[],
    )


def test_study_definition_registry_contains_required_surface() -> None:
    definitions = {item.code: item for item in list_study_definitions()}
    arms = {item.code for item in list_study_arm_definitions()}

    assert definitions["multi_asset_episode_study_v1"].final_test_lock_required is True
    assert {
        "same_instrument_v1",
        "same_asset_class_v1",
        "cross_asset_v1",
        "context_matched_v1",
        "shape_only_v1",
        "dna_only_v1",
        "shape_dna_context_v1",
        "episode_diverse_combined_v1",
    } <= arms


def test_temporal_episode_gap_includes_window_horizon_and_minimum_separation() -> None:
    assert temporal_episode_gap(16, [1, 3, 20], 5) == 20
    assert temporal_episode_gap(64, [1, 3, 20], 5) == 64
    assert temporal_episode_gap(16, [1, 3], 40) == 40


def test_quality_state_thresholds() -> None:
    cfg = {"minimum_unique_episodes": 30, "maximum_single_episode_share": 0.10, "maximum_top_three_episode_share": 0.25}
    assert quality_state(30, 0.10, 0.25, cfg) == "ADEQUATE"
    assert quality_state(15, 0.20, 0.60, cfg) == "MARGINAL"
    assert quality_state(10, 0.30, 0.60, cfg) == "INADEQUATE"


@pytest.mark.parametrize(
    ("summary", "decision"),
    [
        ({"preflight_status": "FAILED", "eligible_instruments": 0}, "STUDY_NOT_READY"),
        ({"preflight_status": "FAILED", "eligible_instruments": 2}, "PILOT_ONLY"),
        ({"preflight_status": "PASSED", "episode_quality": "INADEQUATE"}, "INSUFFICIENT_EPISODE_DIVERSITY"),
        ({"preflight_status": "PASSED", "episode_quality": "ADEQUATE", "validation_skill": 0.1}, "REFINEMENT_PROMISING"),
        ({"preflight_status": "PASSED", "episode_quality": "ADEQUATE", "validation_skill": 0.0}, "NO_RETRIEVAL_EDGE"),
    ],
)
def test_study_decisions(summary: dict, decision: str) -> None:
    assert study_decision(summary) == decision
