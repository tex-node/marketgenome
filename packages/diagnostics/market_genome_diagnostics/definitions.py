from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DiagnosticExperimentDefinition:
    code: str
    version: str
    description: str
    required_representations: list[str]
    required_outcomes: list[str]
    supported_segmentations: list[str]
    supported_metrics: list[str]
    requires_historical_as_of: bool
    uses_future_outcomes: bool
    status: str


@dataclass(frozen=True)
class FeatureScalingMethodDefinition:
    code: str
    version: str
    description: str
    historical_as_of_safe: bool


@dataclass(frozen=True)
class AvailabilityPolicyDefinition:
    code: str
    version: str
    description: str
    rejects_low_coverage: bool
    applies_penalty: bool


@dataclass(frozen=True)
class DiagnosticWeightConfiguration:
    code: str
    version: str
    description: str
    weights: dict[str, float]


DIAGNOSTIC_EXPERIMENT_CODES = [
    "representation_quality_diagnostic_v1",
    "feature_distribution_diagnostic_v1",
    "feature_redundancy_diagnostic_v1",
    "feature_outcome_association_v1",
    "distance_outcome_monotonicity_v1",
    "neighbour_dispersion_diagnostic_v1",
    "similarity_decile_analysis_v1",
    "retrieval_stability_diagnostic_v1",
    "candidate_density_diagnostic_v1",
    "episode_concentration_diagnostic_v1",
    "context_compatibility_diagnostic_v1",
    "window_horizon_alignment_v1",
    "normalization_comparison_v1",
    "shape_channel_ablation_v1",
    "feature_group_weighting_v1",
    "synthetic_motif_recovery_v1",
    "refined_similarity_validation_v1",
]

DIAGNOSTIC_METRICS = [
    "availability_rate",
    "near_constant_rate",
    "redundancy_cluster_count",
    "mean_absolute_correlation",
    "distance_outcome_spearman",
    "top_decile_dispersion",
    "episode_adjusted_effective_sample_size",
    "context_conditioned_dispersion_delta",
    "window_horizon_alignment_score",
    "synthetic_recovery_rate",
]

DIAGNOSTIC_EXPERIMENTS = {
    code: DiagnosticExperimentDefinition(
        code=code,
        version="diagnostic_v1",
        description=f"{code} retrieval diagnostic.",
        required_representations=["normalized_patterns", "market_dna", "market_contexts"],
        required_outcomes=["outcome_observations"] if "distribution" not in code and "redundancy" not in code else [],
        supported_segmentations=["instrument", "timeframe", "window_length", "asset_class", "context_family"],
        supported_metrics=DIAGNOSTIC_METRICS,
        requires_historical_as_of=True,
        uses_future_outcomes="outcome" in code or "decile" in code or "dispersion" in code or "motif" in code,
        status="diagnostic" if code != "refined_similarity_validation_v1" else "confirmatory",
    )
    for code in DIAGNOSTIC_EXPERIMENT_CODES
}

SCALING_METHODS = {
    "none_v1": FeatureScalingMethodDefinition("none_v1", "scaling_v1", "Use raw feature values.", True),
    "zscore_reference_v1": FeatureScalingMethodDefinition("zscore_reference_v1", "scaling_v1", "Reference mean/std z-score.", True),
    "robust_median_mad_v1": FeatureScalingMethodDefinition("robust_median_mad_v1", "scaling_v1", "Reference median/MAD robust scaling.", True),
    "robust_iqr_v1": FeatureScalingMethodDefinition("robust_iqr_v1", "scaling_v1", "Reference median/IQR robust scaling.", True),
    "winsorized_zscore_v1": FeatureScalingMethodDefinition("winsorized_zscore_v1", "scaling_v1", "Winsorize by reference quantiles then z-score.", True),
    "group_balanced_robust_v1": FeatureScalingMethodDefinition("group_balanced_robust_v1", "scaling_v1", "Robust scaling with equalized feature-group contribution.", True),
}

AVAILABILITY_POLICIES = {
    "joint_available_only_v1": AvailabilityPolicyDefinition("joint_available_only_v1", "availability_v1", "Compare only jointly available features.", False, False),
    "joint_available_with_coverage_penalty_v1": AvailabilityPolicyDefinition("joint_available_with_coverage_penalty_v1", "availability_v1", "Compare jointly available features and penalize low coverage.", False, True),
    "minimum_coverage_reject_v1": AvailabilityPolicyDefinition("minimum_coverage_reject_v1", "availability_v1", "Reject pairs below minimum joint coverage.", True, False),
    "group_balanced_availability_v1": AvailabilityPolicyDefinition("group_balanced_availability_v1", "availability_v1", "Require and report group-level joint coverage.", True, True),
}

WEIGHT_CONFIGURATIONS = {
    "dna_robust_balanced_v1": DiagnosticWeightConfiguration("dna_robust_balanced_v1", "weights_v1", "Equal contribution by DNA feature group.", {"dna": 1.0}),
    "shape_dna_context_balanced_v1": DiagnosticWeightConfiguration("shape_dna_context_balanced_v1", "weights_v1", "Balanced shape, DNA, and context distance.", {"shape": 0.34, "dna": 0.33, "context": 0.33}),
    "context_sensitive_v1": DiagnosticWeightConfiguration("context_sensitive_v1", "weights_v1", "Higher transparent context contribution.", {"shape": 0.30, "dna": 0.40, "context": 0.30}),
}


def list_diagnostic_definitions() -> list[DiagnosticExperimentDefinition]:
    return list(DIAGNOSTIC_EXPERIMENTS.values())


def get_diagnostic_definition(code: str) -> DiagnosticExperimentDefinition:
    try:
        return DIAGNOSTIC_EXPERIMENTS[code]
    except KeyError as exc:
        raise ValueError("DIAGNOSTIC_DEFINITION_NOT_FOUND") from exc


def list_scaling_methods() -> list[FeatureScalingMethodDefinition]:
    return list(SCALING_METHODS.values())


def get_scaling_method(code: str) -> FeatureScalingMethodDefinition:
    try:
        return SCALING_METHODS[code]
    except KeyError as exc:
        raise ValueError("DIAGNOSTIC_SCALING_FAILED") from exc


def list_availability_policies() -> list[AvailabilityPolicyDefinition]:
    return list(AVAILABILITY_POLICIES.values())


def get_availability_policy(code: str) -> AvailabilityPolicyDefinition:
    try:
        return AVAILABILITY_POLICIES[code]
    except KeyError as exc:
        raise ValueError("SIMILARITY_FEATURE_COVERAGE_TOO_LOW") from exc


def list_weight_configurations() -> list[DiagnosticWeightConfiguration]:
    return list(WEIGHT_CONFIGURATIONS.values())
