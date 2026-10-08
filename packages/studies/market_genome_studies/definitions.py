from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StudyDefinition:
    code: str
    version: str
    label: str
    description: str
    required_records: list[str]
    period_design: str
    final_test_lock_required: bool


@dataclass(frozen=True)
class StudyArmDefinition:
    code: str
    label: str
    candidate_scope: str
    default_similarity_method: str


STUDY_DEFINITIONS = {
    "multi_asset_episode_study_v1": StudyDefinition(
        code="multi_asset_episode_study_v1",
        version="study_v1",
        label="Real Multi-Asset Episode Diversity Study",
        description="Bounded multi-asset diagnostic study with preflight gates and final-test lock.",
        required_records=["price_bars", "pattern_windows", "normalized_patterns", "market_dna", "market_contexts", "outcome_observations"],
        period_design="chronological_fraction",
        final_test_lock_required=True,
    )
}

STUDY_ARMS = {
    "same_instrument_v1": StudyArmDefinition("same_instrument_v1", "Same Instrument", "same_instrument", "shape_dna_context_v2"),
    "same_asset_class_v1": StudyArmDefinition("same_asset_class_v1", "Same Asset Class", "same_asset_class", "shape_dna_context_v2"),
    "cross_asset_v1": StudyArmDefinition("cross_asset_v1", "Cross Asset", "all_instruments", "shape_dna_context_v2"),
    "context_matched_v1": StudyArmDefinition("context_matched_v1", "Context Matched", "context_matched", "shape_dna_context_v2"),
    "shape_only_v1": StudyArmDefinition("shape_only_v1", "Shape Only", "same_timeframe", "shape_euclidean_v1"),
    "dna_only_v1": StudyArmDefinition("dna_only_v1", "DNA Only", "same_timeframe", "dna_robust_cosine_v1"),
    "shape_dna_context_v1": StudyArmDefinition("shape_dna_context_v1", "Shape DNA Context", "same_timeframe", "shape_dna_context_v2"),
    "episode_diverse_combined_v1": StudyArmDefinition("episode_diverse_combined_v1", "Episode Diverse Combined", "same_timeframe", "episode_diverse_analogue_v1"),
}


def list_study_definitions() -> list[StudyDefinition]:
    return list(STUDY_DEFINITIONS.values())


def get_study_definition(code: str) -> StudyDefinition:
    try:
        return STUDY_DEFINITIONS[code]
    except KeyError as exc:
        raise ValueError("STUDY_DEFINITION_NOT_FOUND") from exc


def list_study_arm_definitions() -> list[StudyArmDefinition]:
    return list(STUDY_ARMS.values())


def get_study_arm_definition(code: str) -> StudyArmDefinition:
    try:
        return STUDY_ARMS[code]
    except KeyError as exc:
        raise ValueError("STUDY_ARM_NOT_FOUND") from exc
