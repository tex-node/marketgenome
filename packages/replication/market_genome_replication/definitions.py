from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ReplicationProtocolDefinition:
    protocol_code: str
    protocol_version: str
    hypothesis_text: str
    primary_method: str
    study_arm: str
    timeframe: str
    window_lengths: tuple[int, ...]
    primary_horizon: int
    neighbour_count: int
    weighting: str
    episode_cap: int
    primary_metrics: tuple[str, ...]
    controls: tuple[str, ...]
    success_criteria: dict[str, object]
    failure_criteria: dict[str, object]
    independent_source_requirement: str


INDEPENDENT_ROBUST_DNA_REPLICATION_V1 = ReplicationProtocolDefinition(
    protocol_code="independent_robust_dna_replication_v1",
    protocol_version="protocol_v1",
    hypothesis_text=(
        "For D1 market states, same-instrument historical analogue retrieval using "
        "dna_robust_cosine_v1, K=10, uniform weighting and episode cap=1 produces more "
        "informative 20-bar forward positive/negative outcome estimates than historical "
        "unconditional outcomes and same-context random retrieval."
    ),
    primary_method="dna_robust_cosine_v1",
    study_arm="same_instrument",
    timeframe="D1",
    window_lengths=(16, 32, 64),
    primary_horizon=20,
    neighbour_count=10,
    weighting="uniform_v1",
    episode_cap=1,
    primary_metrics=(
        "brier_score",
        "brier_skill_vs_unconditional",
        "brier_skill_vs_same_context_random",
        "log_loss",
        "return_mae",
        "median_absolute_return_error",
        "expected_calibration_error",
    ),
    controls=(
        "unconditional_outcome_v1",
        "same_context_random_v1",
        "dna_cosine_v1",
        "shape_euclidean_v1",
    ),
    success_criteria={
        "brier_skill_vs_unconditional_gt": 0.0,
        "brier_skill_vs_same_context_random_gt": 0.0,
        "effect_direction_consistent_with_yahoo": True,
        "adequate_episode_diversity": True,
        "not_single_instrument_dependent": True,
        "acceptable_calibration": True,
        "bootstrap_supports_nontrivial_positive_effect": True,
        "provider_independence": "CONFIRMED",
    },
    failure_criteria={
        "brier_skill_vs_unconditional_le": 0.0,
        "materially_worse_than_same_context_random": True,
        "direction_reversed": True,
    },
    independent_source_requirement="CONFIRMED_INDEPENDENT_PROVIDER",
)

CONTEXT_DNA_INCREMENTAL_VALUE_V1 = ReplicationProtocolDefinition(
    protocol_code="context_dna_incremental_value_v1",
    protocol_version="protocol_v1",
    hypothesis_text=(
        "Among historical D1 states matched on predeclared Market Context dimensions, robust "
        "Market DNA similarity (dna_robust_cosine_v1) provides lower Brier score and/or lower "
        "forward-return error than random historical sampling from the same context."
    ),
    primary_method="dna_robust_cosine_v1",
    study_arm="same_instrument",
    timeframe="D1",
    window_lengths=(16, 32, 64),
    primary_horizon=20,
    neighbour_count=10,
    weighting="uniform_v1",
    episode_cap=1,
    primary_metrics=(
        "brier_score",
        "brier_skill_vs_context_random",
        "paired_brier_difference",
        "return_mae_difference",
    ),
    controls=(
        "same_context_random_v1",
        "unconditional_outcome_v1",
        "dna_robust_cosine_v1_no_context_filter",
    ),
    success_criteria={
        "context_beats_unconditional": True,
        "dna_incremental_brier_skill_gt": 0.02,
        "paired_confidence_interval_favors_dna": True,
        "not_single_instrument_dependent": True,
        "consistent_across_more_than_one_window_scale": True,
    },
    failure_criteria={
        "context_does_not_beat_unconditional": True,
        "dna_within_context_le_context_random": True,
    },
    independent_source_requirement="FOLLOW_UP_CONFIRMATORY_DIAGNOSTIC",
)

REPLICATION_PROTOCOLS = {
    INDEPENDENT_ROBUST_DNA_REPLICATION_V1.protocol_code: INDEPENDENT_ROBUST_DNA_REPLICATION_V1,
    CONTEXT_DNA_INCREMENTAL_VALUE_V1.protocol_code: CONTEXT_DNA_INCREMENTAL_VALUE_V1,
}

REPLICATION_DECISIONS = (
    "REPLICATION_SUPPORTED",
    "REPLICATION_PARTIAL",
    "REPLICATION_NOT_SUPPORTED",
    "REPLICATION_INCONCLUSIVE",
)


def list_replication_protocol_definitions() -> list[ReplicationProtocolDefinition]:
    return list(REPLICATION_PROTOCOLS.values())


def get_replication_protocol_definition(code: str) -> ReplicationProtocolDefinition:
    try:
        return REPLICATION_PROTOCOLS[code]
    except KeyError as exc:
        raise ValueError("REPLICATION_PROTOCOL_DEFINITION_NOT_FOUND") from exc
