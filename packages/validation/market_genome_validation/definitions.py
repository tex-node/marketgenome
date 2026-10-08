from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ExperimentDefinition:
    code: str
    version: str
    label: str
    description: str
    required_inputs: list[str]
    supported_similarity_methods: list[str]
    supported_baselines: list[str]
    supported_metrics: list[str]
    uses_training_period: bool
    uses_validation_period: bool
    uses_test_period: bool
    supports_parameter_sweeps: bool
    walk_forward_safe: bool


@dataclass(frozen=True)
class ValidationMethodDefinition:
    code: str
    version: str
    label: str
    description: str
    time_series_safe: bool
    supports_purge: bool
    supports_embargo: bool


@dataclass(frozen=True)
class BaselineMethodDefinition:
    code: str
    version: str
    label: str
    description: str
    eligible_data: str
    historical_restriction: str
    sampling_method: str
    seed_behavior: str
    limitations: str


@dataclass(frozen=True)
class MetricDefinition:
    code: str
    version: str
    label: str
    metric_family: str
    higher_is_better: bool


@dataclass(frozen=True)
class WeightingMethodDefinition:
    code: str
    version: str
    label: str
    description: str


SIMILARITY_METHODS = ["shape_euclidean_v1", "shape_correlation_v1", "dna_cosine_v1", "market_analogue_v1"]
BASELINES = [
    "random_history_v1",
    "same_instrument_random_v1",
    "same_context_random_v1",
    "same_volatility_random_v1",
    "recent_return_match_v1",
    "raw_shape_euclidean_v1",
    "dna_only_cosine_v1",
    "context_filter_random_v1",
    "same_asset_class_random_v1",
    "unconditional_outcome_v1",
    "naive_continuation_v1",
    "naive_mean_reversion_v1",
    "recent_mean_return_v1",
]
METRICS = [
    "direction_accuracy",
    "balanced_accuracy",
    "matthews_correlation",
    "brier_score",
    "brier_skill_score",
    "log_loss",
    "mae",
    "rmse",
    "pinball_loss",
    "expected_calibration_error",
    "maximum_calibration_error",
    "empirical_crps",
]


EXPERIMENT_DEFINITION_CODES = [
    "walk_forward_analogue_validation_v1",
    "purged_cv_analogue_validation_v1",
    "baseline_comparison_v1",
    "neighbour_count_sensitivity_v1",
    "context_ablation_v1",
    "feature_ablation_v1",
    "cross_asset_generalization_v1",
    "cross_timeframe_generalization_v1",
    "normalization_sensitivity_v1",
    "window_length_sensitivity_v1",
    "horizon_sensitivity_v1",
    "retrieval_stability_v1",
    "calibration_analysis_v1",
]

EXPERIMENT_DEFINITIONS = {
    code: ExperimentDefinition(
        code=code,
        version="experiment_v1",
        label=code.replace("_", " ").title(),
        description=f"{code} validation experiment.",
        required_inputs=["pattern_windows", "normalized_patterns", "market_dna", "market_contexts", "outcome_observations"],
        supported_similarity_methods=SIMILARITY_METHODS,
        supported_baselines=BASELINES,
        supported_metrics=METRICS,
        uses_training_period=True,
        uses_validation_period="holdout" not in code,
        uses_test_period=True,
        supports_parameter_sweeps="sensitivity" in code or "ablation" in code,
        walk_forward_safe=True,
    )
    for code in EXPERIMENT_DEFINITION_CODES
}

VALIDATION_METHODS = {
    "expanding_walk_forward_v1": ValidationMethodDefinition("expanding_walk_forward_v1", "validation_v1", "Expanding Walk-Forward v1", "Expanding historical index and later contiguous test folds.", True, True, True),
    "rolling_walk_forward_v1": ValidationMethodDefinition("rolling_walk_forward_v1", "validation_v1", "Rolling Walk-Forward v1", "Fixed-size rolling historical index and later test folds.", True, True, True),
    "purged_kfold_v1": ValidationMethodDefinition("purged_kfold_v1", "validation_v1", "Purged K-Fold v1", "Contiguous time folds with purge and embargo.", True, True, True),
    "anchored_holdout_v1": ValidationMethodDefinition("anchored_holdout_v1", "validation_v1", "Anchored Holdout v1", "One historical development period and one later test period.", True, True, True),
}

BASELINE_METHODS = {
    code: BaselineMethodDefinition(
        code=code,
        version="baseline_v1",
        label=code.replace("_", " ").title(),
        description=f"{code} validation baseline.",
        eligible_data="same historical candidate universe as similarity unless stated by filter",
        historical_restriction="candidate.window_end < query.window_end before sampling or scoring",
        sampling_method="deterministic seeded sampling or deterministic ranking",
        seed_behavior="seeded by experiment seed, query id, baseline code, and repetition",
        limitations="Research baseline only; no transaction-cost or execution model.",
    )
    for code in BASELINES
}

METRIC_DEFINITIONS = {
    code: MetricDefinition(
        code=code,
        version="metric_v1",
        label=code.replace("_", " ").title(),
        metric_family="classification" if code in {"direction_accuracy", "balanced_accuracy", "matthews_correlation", "brier_score", "brier_skill_score", "log_loss"} else "regression_calibration",
        higher_is_better=code in {"direction_accuracy", "balanced_accuracy", "matthews_correlation", "brier_skill_score"},
    )
    for code in METRICS
}

WEIGHTING_METHODS = {
    "uniform_v1": WeightingMethodDefinition("uniform_v1", "weighting_v1", "Uniform v1", "Equal analogue weights."),
    "inverse_distance_v1": WeightingMethodDefinition("inverse_distance_v1", "weighting_v1", "Inverse Distance v1", "Stable inverse-distance weights."),
    "softmax_similarity_v1": WeightingMethodDefinition("softmax_similarity_v1", "weighting_v1", "Softmax Similarity v1", "Softmax over similarity scores."),
    "rank_decay_v1": WeightingMethodDefinition("rank_decay_v1", "weighting_v1", "Rank Decay v1", "Weight equals 1/rank."),
}


def list_experiment_definitions() -> list[ExperimentDefinition]:
    return list(EXPERIMENT_DEFINITIONS.values())


def get_experiment_definition(code: str) -> ExperimentDefinition:
    try:
        return EXPERIMENT_DEFINITIONS[code]
    except KeyError as exc:
        raise ValueError("EXPERIMENT_DEFINITION_NOT_FOUND") from exc


def list_validation_methods() -> list[ValidationMethodDefinition]:
    return list(VALIDATION_METHODS.values())


def get_validation_method(code: str) -> ValidationMethodDefinition:
    try:
        return VALIDATION_METHODS[code]
    except KeyError as exc:
        raise ValueError("VALIDATION_METHOD_NOT_FOUND") from exc


def list_baseline_methods() -> list[BaselineMethodDefinition]:
    return list(BASELINE_METHODS.values())


def get_baseline_method(code: str) -> BaselineMethodDefinition:
    try:
        return BASELINE_METHODS[code]
    except KeyError as exc:
        raise ValueError("BASELINE_METHOD_NOT_FOUND") from exc


def list_metric_definitions() -> list[MetricDefinition]:
    return list(METRIC_DEFINITIONS.values())


def list_weighting_methods() -> list[WeightingMethodDefinition]:
    return list(WEIGHTING_METHODS.values())
