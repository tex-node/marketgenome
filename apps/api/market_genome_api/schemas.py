from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ErrorResponse(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    correlation_id: str | None = None


class InstrumentCreate(BaseModel):
    symbol: str
    name: str | None = None
    asset_class: str = "other"
    exchange: str | None = None
    currency: str | None = None
    timezone: str = "UTC"
    tick_size: float | None = None
    price_precision: int | None = None
    volume_type: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class InstrumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    symbol: str
    name: str | None
    asset_class: str
    exchange: str | None
    currency: str | None
    timezone: str
    is_active: bool


class TimeframeCreate(BaseModel):
    code: str
    seconds: int | None = None
    label: str | None = None
    is_intraday: bool | None = None


class TimeframeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    code: str
    seconds: int | None
    label: str
    is_intraday: bool


class DataSourceCreate(BaseModel):
    name: str
    source_type: str = "csv"
    configuration_metadata: dict[str, Any] = Field(default_factory=dict)


class DataSourceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    source_type: str
    configuration_metadata: dict[str, Any]


class EntityRef(BaseModel):
    id: str
    symbol: str | None = None
    code: str | None = None
    name: str | None = None


class ImportSummary(BaseModel):
    rows_read: int
    rows_valid: int
    rows_inserted: int
    rows_updated: int
    rows_skipped: int
    warnings: int
    errors: int


class ImportResponse(BaseModel):
    import_id: str
    status: str
    dry_run: bool
    source_hash: str
    instrument: EntityRef
    timeframe: EntityRef
    source: EntityRef
    summary: ImportSummary
    quality: dict[str, Any]
    created_at: datetime


class ImportIssueResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    import_id: str
    row_number: int
    severity: str
    issue_type: str
    message: str


class WindowQualityPolicyRequest(BaseModel):
    mode: str = "strict"
    maximum_missing_bars: int = 0
    maximum_gap_ratio: float = 0.0
    calendar_mode: str = "continuous"


class WindowBuildRequest(BaseModel):
    instrument_id: str
    timeframe_id: str
    window_lengths: list[int] = Field(default_factory=lambda: [8, 16, 32, 64, 128, 256])
    stride: int = 1
    mode: str = "incremental"
    window_version: str = "window_v1"
    start_timestamp: datetime | None = None
    end_timestamp: datetime | None = None
    quality_policy: WindowQualityPolicyRequest = Field(default_factory=WindowQualityPolicyRequest)


class WindowBuildResponse(BaseModel):
    id: str
    status: str
    instrument_id: str
    timeframe_id: str
    requested_lengths: list[int]
    stride: int
    mode: str
    window_version: str
    configuration_hash: str
    source_bar_count: int
    candidate_windows: int
    created_windows: int
    existing_windows: int
    skipped_windows: int
    incomplete_windows: int
    quality_warning_windows: int
    first_window_start: datetime | None
    last_window_end: datetime | None
    elapsed_seconds: float | None


class PatternWindowResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    instrument_id: str
    timeframe_id: str
    start_timestamp: datetime
    end_timestamp: datetime
    start_bar_id: str
    end_bar_id: str
    window_length: int
    stride: int
    bar_count: int
    window_version: str
    source_data_hash: str
    build_configuration_hash: str
    is_complete: bool
    quality_flags: list[str]


class PriceBarResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    data_quality_flags: list[str]


class NormalizationMethodResponse(BaseModel):
    code: str
    label: str
    version: str
    description: str
    is_price_scale_invariant: bool
    is_translation_invariant: bool
    is_amplitude_invariant: bool
    is_volatility_adjusted: bool
    supports_ohlc: bool
    supports_volume: bool
    minimum_bars: int
    channels: list[str]
    channel_schema: str


class NormalizationPoliciesRequest(BaseModel):
    source_hash_mismatch: str = "reject"
    non_positive_price: str = "reject"
    zero_variance: str = "reject"
    zero_range: str = "reject"
    zero_volatility: str = "reject"
    zero_atr: str = "reject"
    missing_volume: str = "allow"
    invalid_ohlc: str = "reject"
    ddof: int = 0
    minimum_std: float = 1e-12
    minimum_volatility: float = 1e-12
    minimum_atr: float = 1e-12
    range_centered: bool = False
    storage_decimals: int = 12
    calculation_dtype: str = "float64"


class NormalizationBuildRequest(BaseModel):
    normalization_method: str = "anchored_log_return"
    normalization_version: str = "normalization_v1"
    resampling_method: str = "linear"
    resample_points: int = 64
    mode: str = "incremental"
    instrument_id: str | None = None
    timeframe_id: str | None = None
    window_length: int | None = None
    start_timestamp: datetime | None = None
    end_timestamp: datetime | None = None
    source_window_version: str = "window_v1"
    policies: NormalizationPoliciesRequest = Field(default_factory=NormalizationPoliciesRequest)


class NormalizationBuildResponse(BaseModel):
    id: str
    status: str
    normalization_method: str
    normalization_version: str
    resampling_method: str
    resample_points: int
    source_window_version: str
    configuration_hash: str
    source_window_count: int
    created_representations: int
    existing_representations: int
    skipped_representations: int
    failed_representations: int
    elapsed_seconds: float | None


class NormalizedPatternResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    pattern_window_id: str
    normalization_method: str
    normalization_version: str
    resampling_method: str
    resample_points: int
    source_window_hash: str
    configuration_hash: str
    representation_hash: str
    channel_schema: dict[str, Any]
    quality_flags: list[str]
    created_at: datetime


class NormalizedPatternValuesResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    normalized_pattern_id: str
    schema_: str = Field(alias="schema")
    channels: list[str]
    points: int
    values: dict[str, list[float]]


class FeatureDefinitionResponse(BaseModel):
    code: str
    label: str
    version: str
    description: str
    feature_group: str
    input_source: str
    required_channels: list[str]
    minimum_bars: int
    output_type: str
    is_scale_invariant: bool
    is_translation_invariant: bool
    expected_range: str | None
    missing_value_policy: str
    numerical_stability_notes: str
    formula_reference: str


class FeatureSetResponse(BaseModel):
    code: str
    version: str
    label: str
    description: str
    ordered_feature_codes: list[str]
    required_normalization_method: str
    required_normalization_version: str
    required_resampling_method: str
    required_resample_points: int
    configuration: dict[str, Any]


class FeatureBuildRequest(BaseModel):
    feature_set_code: str = "market_dna_v1"
    mode: str = "incremental"
    instrument_id: str | None = None
    timeframe_id: str | None = None
    window_length: int | None = None
    start_timestamp: datetime | None = None
    end_timestamp: datetime | None = None


class FeatureBuildResponse(BaseModel):
    id: str
    status: str
    feature_set_code: str
    feature_set_version: str
    source_normalization_method: str
    source_normalization_version: str
    source_resampling_method: str
    source_resample_points: int
    configuration_hash: str
    source_pattern_count: int
    created_features: int
    existing_features: int
    skipped_features: int
    failed_features: int
    elapsed_seconds: float | None


class MarketDNAResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    pattern_window_id: str
    normalized_pattern_id: str
    feature_set_code: str
    feature_set_version: str
    source_window_hash: str
    source_representation_hash: str
    configuration_hash: str
    feature_vector_hash: str
    feature_count: int
    available_feature_count: int
    unavailable_feature_count: int
    availability: dict[str, Any]
    quality_flags: list[str]
    created_at: datetime


class MarketDNAValuesResponse(BaseModel):
    market_dna_id: str
    ordered_features: list[str]
    values: list[float | int | None]
    availability_mask: list[bool]
    feature_values: dict[str, float | int | None]


class ContextProducerResponse(BaseModel):
    code: str
    version: str
    label: str
    description: str
    required_feature_set_code: str
    required_feature_set_version: str
    required_normalization_method: str
    required_normalization_version: str
    required_resampling_method: str
    required_resample_points: int
    dimensions: list[str]
    is_supervised: bool
    uses_future_outcomes: bool
    supports_multi_resolution: bool
    configuration_schema: dict[str, Any]


class ContextDimensionResponse(BaseModel):
    code: str
    states: list[str]
    version: str


class ContextBuildRequest(BaseModel):
    context_producer_code: str = "transparent_context_v1"
    feature_set_code: str = "market_dna_v1"
    mode: str = "incremental"
    instrument_id: str | None = None
    timeframe_id: str | None = None
    window_length: int | None = None
    start_timestamp: datetime | None = None
    end_timestamp: datetime | None = None


class ContextBuildResponse(BaseModel):
    id: str
    status: str
    context_producer_code: str
    context_producer_version: str
    feature_set_code: str
    feature_set_version: str
    configuration_hash: str
    source_market_dna_count: int
    created_contexts: int
    existing_contexts: int
    partial_contexts: int
    skipped_contexts: int
    failed_contexts: int
    elapsed_seconds: float | None


class MarketContextResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    pattern_window_id: str
    normalized_pattern_id: str
    market_dna_id: str
    context_producer_code: str
    context_producer_version: str
    feature_set_code: str
    feature_set_version: str
    source_window_hash: str
    source_representation_hash: str
    source_feature_vector_hash: str
    configuration_hash: str
    context_hash: str
    trend_state: str
    volatility_state: str
    volatility_phase_state: str
    persistence_state: str
    activity_state: str
    shock_state: str
    market_phase_state: str
    multi_resolution_state: str
    trend_confidence: float
    volatility_confidence: float
    volatility_phase_confidence: float
    persistence_confidence: float
    activity_confidence: float
    shock_confidence: float
    market_phase_confidence: float
    multi_resolution_confidence: float
    composite_context_code: str
    context_family_code: str
    composite_confidence: float
    completeness_score: float
    quality_flags: list[str]
    created_at: datetime


class OutcomeDefinitionResponse(BaseModel):
    code: str
    version: str
    label: str
    description: str
    input_source: str
    formula: str
    units: str
    required_horizon: str
    minimum_future_bars: int
    supports_partial: bool
    direction_convention: str
    missing_data_policy: str
    limitations: str


class OutcomeSetResponse(BaseModel):
    code: str
    version: str
    label: str
    description: str
    ordered_outcome_definitions: list[str]
    default_horizons: list[int]
    anchor_method: str
    forward_path_method: str
    barrier_configuration: dict[str, Any]
    classification_configuration: dict[str, Any]
    precision_policy: dict[str, Any]
    configuration: dict[str, Any]


class OutcomeBuildRequest(BaseModel):
    outcome_set_code: str = "forward_outcomes_v1"
    horizons: list[int] | None = None
    mode: str = "incremental"
    instrument_id: str | None = None
    timeframe_id: str | None = None
    window_length: int | None = None
    start_timestamp: datetime | None = None
    end_timestamp: datetime | None = None


class OutcomeBuildResponse(BaseModel):
    id: str
    status: str
    outcome_set_code: str
    outcome_set_version: str
    requested_horizons: list[int]
    mode: str
    configuration_hash: str
    source_pattern_count: int
    eligible_pattern_count: int
    created_observations: int
    existing_observations: int
    partial_observations: int
    skipped_patterns: int
    failed_observations: int
    elapsed_seconds: float | None


class OutcomeObservationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    pattern_window_id: str
    instrument_id: str
    timeframe_id: str
    window_length: int
    window_start_timestamp: datetime
    window_end_timestamp: datetime
    outcome_set_code: str
    outcome_set_version: str
    horizon_bars: int
    available_future_bars: int
    is_complete: bool
    anchor_timestamp: datetime
    anchor_price: float
    first_future_timestamp: datetime | None
    last_future_timestamp: datetime | None
    future_simple_return: float | None
    future_log_return: float | None
    maximum_favourable_excursion: float | None
    maximum_adverse_excursion: float | None
    time_to_mfe_bars: int | None
    time_to_mae_bars: int | None
    future_realized_volatility: float | None
    future_path_efficiency: float | None
    future_maximum_drawdown: float | None
    future_maximum_runup: float | None
    direction_class: str
    continuation_reversal_class: str
    first_barrier_hit: str
    gain_before_drawdown: str
    drawdown_before_gain: str
    source_window_hash: str
    future_bar_hash: str
    configuration_hash: str
    outcome_hash: str
    quality_flags: list[str]
    supersedes_observation_id: str | None
    created_at: datetime


class OutcomeValuesResponse(BaseModel):
    outcome_observation_id: str
    scalar_values: dict[str, Any]


class ForwardPathResponse(BaseModel):
    outcome_observation_id: str
    forward_path: dict[str, Any]


class SimilarityMethodResponse(BaseModel):
    code: str
    version: str
    label: str
    description: str
    input_sources: list[str]
    output_distance: str
    supports_missing_features: bool
    uses_future_outcomes: bool
    default_configuration: dict[str, Any]


class SimilaritySearchRequest(BaseModel):
    query_window_id: str
    similarity_method_code: str = "market_analogue_v1"
    top_k: int = 20
    instrument_id: str | None = None
    timeframe_id: str | None = None
    window_length: int | None = None
    temporal_policy: str = "historical_only"
    include_self: bool = False


class SimilarityQueryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    query_window_id: str
    query_normalized_pattern_id: str | None
    query_market_dna_id: str | None
    similarity_method_code: str
    similarity_method_version: str
    feature_set_code: str | None
    feature_set_version: str | None
    top_k: int
    candidate_count: int
    returned_match_count: int
    temporal_policy: str
    configuration_hash: str
    query_hash: str
    status: str
    elapsed_seconds: float | None
    diagnostics: dict[str, Any]
    created_at: datetime


class SimilarityMatchResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    query_id: str
    query_window_id: str
    candidate_window_id: str
    candidate_normalized_pattern_id: str | None
    candidate_market_dna_id: str | None
    rank: int
    distance: float
    similarity_score: float
    similarity_method_code: str
    similarity_method_version: str
    configuration_hash: str
    query_source_hash: str
    candidate_source_hash: str
    query_vector_hash: str
    candidate_vector_hash: str
    component_scores: dict[str, Any]
    diagnostics: dict[str, Any]
    quality_flags: list[str]
    created_at: datetime


class ExperimentDefinitionResponse(BaseModel):
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


class ValidationMethodResponse(BaseModel):
    code: str
    version: str
    label: str
    description: str
    time_series_safe: bool
    supports_purge: bool
    supports_embargo: bool


class BaselineMethodResponse(BaseModel):
    code: str
    version: str
    label: str
    description: str
    eligible_data: str
    historical_restriction: str
    sampling_method: str
    seed_behavior: str
    limitations: str


class MetricDefinitionResponse(BaseModel):
    code: str
    version: str
    label: str
    metric_family: str
    higher_is_better: bool


class ExperimentCreateRequest(BaseModel):
    configuration: dict[str, Any] = Field(default_factory=dict)


class DiagnosticDefinitionResponse(BaseModel):
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


class DiagnosticMethodResponse(BaseModel):
    code: str
    version: str
    description: str


class DiagnosticExperimentCreateRequest(BaseModel):
    configuration: dict[str, Any] = Field(default_factory=dict)


class DiagnosticArtifactResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    experiment_run_id: str
    diagnostic_code: str
    artifact_type: str
    schema_version: str
    configuration_hash: str
    payload: dict[str, Any]
    artifact_hash: str
    created_at: datetime


class ExperimentRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    experiment_code: str
    experiment_version: str
    name: str
    hypothesis: str | None
    status: str
    dataset_version: str
    dataset_hash: str
    configuration_hash: str
    similarity_method: str
    baseline_methods: list[str]
    outcome_set_code: str
    outcome_set_version: str
    outcome_horizons: list[int]
    validation_method: str
    decision: str | None
    summary: dict[str, Any]
    elapsed_seconds: float | None
    created_at: datetime


class ExperimentFoldResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    experiment_run_id: str
    fold_number: int
    index_start: datetime | None
    index_end: datetime | None
    test_start: datetime
    test_end: datetime
    embargo_bars: int
    eligible_index_count: int
    eligible_query_count: int
    excluded_overlap_count: int
    excluded_future_count: int
    excluded_quality_count: int
    fold_hash: str
    status: str


class QueryEvaluationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    experiment_run_id: str
    fold_id: str
    query_window_id: str
    horizon_bars: int
    similarity_method: str | None
    baseline_method: str | None
    neighbour_count: int
    weighting_method: str
    predicted_direction_probability: float | None
    predicted_return_mean: float | None
    actual_direction: str | None
    actual_return: float | None
    direction_correct: bool | None
    brier_component: float | None
    quality_flags: list[str]


class ExperimentMetricResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    experiment_run_id: str
    fold_id: str | None
    metric_code: str
    metric_version: str
    value: float | None
    sample_count: int
    segment_type: str | None
    segment_value: str | None
    horizon_bars: int | None
    similarity_method: str | None
    baseline_method: str | None
    confidence_interval_low: float | None
    confidence_interval_high: float | None
    standard_error: float | None
    p_value: float | None
    effect_size: float | None
    metric_metadata: dict[str, Any]
    metric_hash: str


class StudyCreateRequest(BaseModel):
    configuration: dict[str, Any] = Field(default_factory=dict)


class StudyDefinitionResponse(BaseModel):
    code: str
    version: str
    label: str
    description: str
    required_records: list[str]
    period_design: str
    final_test_lock_required: bool


class StudyManifestResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    study_code: str
    study_version: str
    name: str
    configuration_hash: str
    dataset_hash: str
    status: str
    decision: str | None
    decision_rationale: str | None
    final_test_lock_hash: str | None
    created_at: datetime
    completed_at: datetime | None


class StudyDatasetEntryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    study_id: str
    instrument_id: str
    timeframe_id: str
    date_start: datetime | None
    date_end: datetime | None
    bar_count: int
    window_count: int
    episode_count: int
    complete_outcome_rate: float
    quality_status: str
    inclusion_status: str
    exclusion_reason: str | None
    dataset_entry_hash: str


class StudyEpisodeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    study_id: str
    episode_id: str
    instrument_id: str
    timeframe_id: str
    episode_start: datetime
    episode_end: datetime
    window_count: int
    outcome_span: int
    episode_hash: str


class StudyPreflightResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    study_id: str
    gate_code: str
    status: str
    actual_value: str
    required_value: str
    details: dict[str, Any]


class StudyArmResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    study_id: str
    arm_code: str
    period_role: str
    status: str
    similarity_method: str | None
    baseline_methods: list[str]
    episode_cap: int | None
    metrics: dict[str, Any]
    segments: dict[str, Any]


class ProspectiveProtocolResponse(BaseModel):
    """Research signal protocol -- not a trading recommendation."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    protocol_code: str
    protocol_version: str
    context_definition: str
    fallback_hierarchy: list[str]
    timeframe: str
    window_lengths: list[int]
    primary_horizon: int
    secondary_horizons: list[int]
    minimum_historical_sample: int
    minimum_evidence_matured_forecasts: int
    preferred_evidence_matured_forecasts: int
    instrument_universe: list[str]
    configuration_hash: str
    status: str
    frozen_at: datetime | None
    created_at: datetime


class ProspectiveForecastResponse(BaseModel):
    """Estimated probability from historical context matching -- a research signal,
    not a trade recommendation."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    protocol_id: str
    instrument_id: str
    timeframe_id: str
    window_length: int
    forecast_timestamp: datetime
    data_cutoff_timestamp: datetime
    horizon_bars: int
    context_code: str
    context_level_used: str
    fallback_reason: str | None
    probability_positive: float
    probability_negative: float
    sample_count: int
    positive_count: int
    negative_count: int
    confidence_lower: float
    confidence_upper: float
    provenance_class: str
    status: str
    forecast_hash: str
    created_at: datetime


class ProspectiveEvaluationSnapshotResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    protocol_id: str
    as_of: datetime
    forecast_count: int
    matured_count: int
    brier_score: float | None
    brier_skill_vs_unconditional: float | None
    log_loss: float | None
    expected_calibration_error: float | None
    direction_accuracy: float | None
    balanced_accuracy: float | None
    mcc: float | None
    primary_horizon: int | None
    primary_horizon_matured_count: int | None
    bootstrap_ci_low: float | None
    bootstrap_ci_high: float | None
    per_horizon_metrics: dict | None
    status: str
    snapshot_hash: str
    created_at: datetime
