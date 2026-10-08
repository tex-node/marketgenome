from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from market_genome_domain.models import (
    ContextBuild,
    ContextBuildStatus,
    MarketContext,
    MarketDNA,
    PatternWindow,
)
from market_genome_features.service import feature_vector_hash
from market_genome_normalization.service import representation_hash
from market_genome_shared.hashing import sha256_canonical
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from market_genome_context.definitions import (
    ContextProducerDefinition,
    get_context_producer,
)

DIMENSION_ORDER = [
    "trend",
    "volatility",
    "volatility_phase",
    "persistence",
    "activity",
    "shock",
    "market_phase",
    "multi_resolution",
]


@dataclass
class DimensionResult:
    state: str
    confidence: float
    scores: dict[str, float]
    evidence: list[dict[str, Any]] = field(default_factory=list)
    opposing_evidence: list[dict[str, Any]] = field(default_factory=list)
    quality_flags: list[str] = field(default_factory=list)


@dataclass
class ComputedContext:
    states: dict[str, str]
    confidences: dict[str, float]
    dimension_scores: dict[str, Any]
    evidence: dict[str, Any]
    opposing_evidence: dict[str, Any]
    diagnostics: dict[str, Any]
    multi_resolution_links: dict[str, Any]
    composite_context_code: str
    context_family_code: str
    composite_confidence: float
    completeness_score: float
    quality_flags: list[str]
    context_hash: str


@dataclass
class ContextBuildResult:
    build: ContextBuild
    source_market_dna_count: int = 0
    created_contexts: int = 0
    existing_contexts: int = 0
    partial_contexts: int = 0
    skipped_contexts: int = 0
    failed_contexts: int = 0
    elapsed_seconds: float | None = None
    errors: list[str] = field(default_factory=list)


def context_configuration_hash(configuration: dict[str, Any]) -> str:
    return sha256_canonical(configuration)


def context_hash(payload: dict[str, Any]) -> str:
    return sha256_canonical(payload)


def _clip(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


def _value(features: dict[str, Any], code: str) -> float | None:
    value = features.get(code)
    if value is None:
        return None
    return float(value)


def _available(availability: dict[str, Any], code: str) -> bool:
    return availability.get(code) == "AVAILABLE"


def _evidence(features: dict[str, Any], *codes: str) -> list[dict[str, Any]]:
    return [{"feature": code, "value": features.get(code)} for code in codes if features.get(code) is not None]


def classify_trend(features: dict[str, Any], availability: dict[str, Any], cfg: dict[str, Any]) -> DimensionResult:
    slope = _value(features, "linear_regression_slope")
    r2 = _value(features, "linear_regression_r_squared") or 0.0
    efficiency = _value(features, "path_efficiency_ratio") or 0.0
    consistency = _value(features, "trend_direction_consistency") or 0.0
    endpoint = _value(features, "normalized_endpoint_return") or 0.0
    displacement = _value(features, "path_displacement") or 0.0
    momentum = _value(features, "momentum_acceleration") or 0.0
    higher = (_value(features, "higher_high_count") or 0.0) + (_value(features, "higher_low_count") or 0.0)
    lower = (_value(features, "lower_high_count") or 0.0) + (_value(features, "lower_low_count") or 0.0)
    if slope is None or not _available(availability, "linear_regression_slope"):
        return DimensionResult("UNCERTAIN", 0.0, {}, quality_flags=["MISSING_TREND_FEATURES"])
    direction = _clip(slope / cfg["strong_slope_threshold"], -1.0, 1.0)
    fit_score = (r2 + efficiency + consistency) / 3.0
    strength = _clip((abs(slope) / cfg["strong_slope_threshold"] + fit_score) / 2.0)
    structure_alignment = _clip((higher - lower) / max(1.0, higher + lower), -1.0, 1.0)
    conflicts: list[str] = []
    opposing: list[dict[str, Any]] = []
    if abs(endpoint) < cfg["minimum_displacement"] or displacement < cfg["minimum_displacement"]:
        conflicts.append("LOW_MAGNITUDE_DIRECTION")
    if structure_alignment and direction and structure_alignment * direction < -0.2:
        conflicts.append("SLOPE_STRUCTURE_CONFLICT")
        opposing.append({"feature": "structure_alignment_score", "value": structure_alignment})
    if momentum and direction and momentum * direction < 0:
        conflicts.append("TREND_MOMENTUM_CONFLICT")
        opposing.append({"feature": "momentum_acceleration", "value": momentum})
    if abs(slope) >= cfg["strong_slope_threshold"] and r2 >= cfg["strong_trend_r_squared"] and efficiency >= cfg["strong_efficiency_ratio"]:
        state = "STRONG_UPTREND" if slope > 0 else "STRONG_DOWNTREND"
    elif abs(slope) >= cfg["weak_slope_threshold"] and fit_score >= 0.35 and abs(endpoint) >= cfg["minimum_displacement"]:
        state = "WEAK_UPTREND" if slope > 0 else "WEAK_DOWNTREND"
    elif fit_score < 0.45 or abs(slope) < cfg["weak_slope_threshold"]:
        state = "RANGE"
    else:
        state = "UNCERTAIN"
    confidence = _clip(strength - 0.12 * len(conflicts))
    return DimensionResult(
        state,
        confidence,
        {
            "direction_score": direction,
            "strength_score": strength,
            "structure_alignment_score": structure_alignment,
            "trend_conflict_score": _clip(len(conflicts) / 3),
        },
        _evidence(features, "linear_regression_slope", "linear_regression_r_squared", "path_efficiency_ratio", "trend_direction_consistency", "normalized_endpoint_return"),
        opposing,
        conflicts,
    )


def classify_volatility(features: dict[str, Any], _availability: dict[str, Any], cfg: dict[str, Any]) -> DimensionResult:
    realized = abs(_value(features, "realized_volatility") or _value(features, "return_std") or 0.0)
    atr = abs(_value(features, "normalized_atr") or 0.0)
    upper = abs(_value(features, "upper_tail_ratio") or 0.0)
    lower = abs(_value(features, "lower_tail_ratio") or 0.0)
    continuous = _clip((realized / 0.035 + atr / 0.03) / 2.0)
    tail = _clip(max(upper, lower) / 4.0)
    score = _clip((continuous * 0.75) + (tail * 0.25))
    if realized >= 0.07 or atr >= 0.07 or score >= cfg["extreme_score_min"]:
        state = "EXTREME"
    elif score >= cfg["high_score_min"]:
        state = "HIGH"
    elif score <= cfg["very_low_score_max"]:
        state = "VERY_LOW"
    elif score <= cfg["low_score_max"]:
        state = "LOW"
    else:
        state = "NORMAL"
    confidence = _clip(abs(score - 0.5) * 1.5 + 0.25)
    return DimensionResult(state, confidence, {"volatility_level_score": score, "continuous_volatility_score": continuous, "tail_volatility_score": tail}, _evidence(features, "realized_volatility", "normalized_atr", "upper_tail_ratio", "lower_tail_ratio"))


def classify_volatility_phase(features: dict[str, Any], _availability: dict[str, Any], cfg: dict[str, Any]) -> DimensionResult:
    vol_ratio = _value(features, "volatility_expansion_ratio")
    range_ratio = _value(features, "range_expansion_ratio")
    if vol_ratio is None or range_ratio is None:
        return DimensionResult("UNCERTAIN", 0.0, {}, quality_flags=["MISSING_VOLATILITY_PHASE_FEATURES"])
    agreement = 1.0 - min(1.0, abs(vol_ratio - range_ratio) / max(abs(vol_ratio), abs(range_ratio), 1.0))
    average = (vol_ratio + range_ratio) / 2.0
    if average <= cfg["compression_ratio_max"]:
        state = "COMPRESSING"
    elif average >= cfg["expansion_ratio_min"]:
        state = "EXPANDING"
    else:
        state = "STABLE"
    confidence = _clip((abs(average - 1.0) if state != "STABLE" else 0.45) + 0.35 * agreement)
    opposing = [] if agreement >= 0.5 else [{"feature": "volatility_range_agreement", "value": agreement}]
    return DimensionResult(state, confidence, {"volatility_ratio_score": vol_ratio, "range_ratio_score": range_ratio, "agreement_score": agreement}, _evidence(features, "volatility_expansion_ratio", "range_expansion_ratio"), opposing)


def classify_persistence(features: dict[str, Any], availability: dict[str, Any], cfg: dict[str, Any]) -> DimensionResult:
    votes: list[int] = []
    evidence = []
    for code, low, high in (
        ("hurst_rs_v1", cfg["hurst_mean_reverting_max"], cfg["hurst_persistent_min"]),
        ("ar_1_coefficient", cfg["ar1_mean_reverting_max"], cfg["ar1_persistent_min"]),
        ("lag_1_autocorrelation", cfg["ar1_mean_reverting_max"], cfg["ar1_persistent_min"]),
        ("variance_ratio_2", cfg["variance_ratio_mean_reverting_max"], cfg["variance_ratio_persistent_min"]),
        ("variance_ratio_4", cfg["variance_ratio_mean_reverting_max"], cfg["variance_ratio_persistent_min"]),
    ):
        value = _value(features, code)
        if value is None or not _available(availability, code):
            continue
        evidence.append({"feature": code, "value": value})
        votes.append(1 if value >= high else -1 if value <= low else 0)
    if not votes:
        return DimensionResult("UNCERTAIN", 0.0, {}, quality_flags=["MISSING_PERSISTENCE_FEATURES"])
    score = sum(votes) / len(votes)
    conflicts = len({vote for vote in votes if vote != 0}) > 1
    state = "PERSISTENT" if score > 0.35 else "MEAN_REVERTING" if score < -0.35 else "NEUTRAL"
    confidence = _clip(abs(score) if state != "NEUTRAL" else 0.55)
    if conflicts:
        confidence = _clip(confidence - 0.2)
    return DimensionResult(state, confidence, {"agreement_score": 1.0 - (0.25 if conflicts else 0.0), "persistence_vote_score": score}, evidence, [{"conflict": "PERSISTENCE_EVIDENCE_CONFLICT"}] if conflicts else [])


def classify_activity(features: dict[str, Any], availability: dict[str, Any], cfg: dict[str, Any]) -> DimensionResult:
    required = ["relative_volume_mean", "volume_coefficient_of_variation", "volume_expansion_ratio", "volume_trend_slope"]
    if any(not _available(availability, code) for code in required):
        return DimensionResult("UNAVAILABLE", 0.0, {}, quality_flags=["MISSING_ACTIVITY_FEATURES"])
    rel = _value(features, "relative_volume_mean") or 1.0
    expansion = _value(features, "volume_expansion_ratio") or 1.0
    cov = _value(features, "volume_coefficient_of_variation") or 0.0
    trend = _value(features, "volume_trend_slope") or 0.0
    score = _clip((rel - 0.5) / 1.5 * 0.35 + _clip(expansion / 2.0) * 0.35 + _clip(cov / 1.0) * 0.2 + _clip(abs(trend) / 1.0) * 0.1)
    if score <= cfg["low_score_max"]:
        state = "LOW"
    elif score >= cfg["elevated_score_min"]:
        state = "ELEVATED"
    else:
        state = "NORMAL"
    return DimensionResult(state, _clip(abs(score - 0.5) + 0.45), {"activity_score": score}, _evidence(features, *required))


def classify_shock(features: dict[str, Any], _availability: dict[str, Any], cfg: dict[str, Any]) -> DimensionResult:
    std = abs(_value(features, "return_std") or 0.0)
    max_pos = abs(_value(features, "maximum_positive_return") or 0.0)
    max_neg = abs(_value(features, "maximum_negative_return") or 0.0)
    largest = max(max_pos, max_neg)
    z = largest / max(std, 1e-12)
    path = _value(features, "path_length") or 0.0
    share = largest / max(path, 1e-12)
    tail = max(abs(_value(features, "upper_tail_ratio") or 0.0), abs(_value(features, "lower_tail_ratio") or 0.0))
    if z >= cfg["discontinuous_largest_return_z"] or share >= cfg["discontinuity_path_share"]:
        state = "DISCONTINUOUS"
    elif z >= cfg["event_largest_return_z"] or tail >= cfg["event_tail_ratio"]:
        state = "EVENT_LIKE"
    else:
        state = "NORMAL"
    confidence = _clip((z / cfg["discontinuous_largest_return_z"]) if state != "NORMAL" else 1.0 - min(0.8, z / 10.0))
    return DimensionResult(state, confidence, {"largest_return_z": z, "discontinuity_path_share": share, "tail_ratio_score": tail}, _evidence(features, "maximum_positive_return", "maximum_negative_return", "return_std", "path_length"))


def classify_market_phase(trend: DimensionResult, volatility_phase: DimensionResult, activity: DimensionResult) -> DimensionResult:
    if trend.state in {"STRONG_UPTREND", "WEAK_UPTREND"} and volatility_phase.state != "COMPRESSING":
        state = "MARKUP_LIKE"
    elif trend.state in {"STRONG_DOWNTREND", "WEAK_DOWNTREND"} and volatility_phase.state != "COMPRESSING":
        state = "MARKDOWN_LIKE"
    elif trend.state == "RANGE" and activity.state in {"LOW", "NORMAL", "UNAVAILABLE"}:
        state = "ACCUMULATION_LIKE" if volatility_phase.state == "COMPRESSING" else "BALANCED"
    elif trend.state == "RANGE" and activity.state == "ELEVATED":
        state = "DISTRIBUTION_LIKE"
    else:
        state = "TRANSITION"
    confidence = _clip((trend.confidence + volatility_phase.confidence + max(activity.confidence, 0.5)) / 3.0)
    return DimensionResult(state, confidence, {"phase_confidence_inputs": confidence}, quality_flags=[] if confidence >= 0.45 else ["LOW_PHASE_CONFIDENCE"])


def _polarity(trend_state: str) -> str:
    if "UPTREND" in trend_state:
        return "BULLISH"
    if "DOWNTREND" in trend_state:
        return "BEARISH"
    if trend_state == "RANGE":
        return "RANGE"
    return "UNCERTAIN"


def classify_multi_resolution(local_state: str, links: dict[str, Any]) -> DimensionResult:
    intermediate = links.get("intermediate", {}).get("trend_state")
    macro = links.get("macro", {}).get("trend_state")
    if not intermediate or not macro:
        return DimensionResult("UNAVAILABLE", 0.0, {}, quality_flags=["MULTI_RESOLUTION_DEPENDENCY_MISSING"])
    local, inter, mac = _polarity(local_state), _polarity(intermediate), _polarity(macro)
    if local == inter == mac == "BULLISH":
        state = "ALIGNED_BULLISH"
    elif local == inter == mac == "BEARISH":
        state = "ALIGNED_BEARISH"
    elif local == inter == mac == "RANGE":
        state = "ALIGNED_RANGE"
    elif local == "BULLISH" and mac == "BEARISH":
        state = "LOCAL_BULLISH_MACRO_BEARISH"
    elif local == "BEARISH" and mac == "BULLISH":
        state = "LOCAL_BEARISH_MACRO_BULLISH"
    elif local in {"BULLISH", "BEARISH"} and mac == "RANGE":
        state = "LOCAL_TREND_MACRO_RANGE"
    elif local == "RANGE" and mac in {"BULLISH", "BEARISH"}:
        state = "LOCAL_RANGE_MACRO_TREND"
    else:
        state = "MIXED"
    confidence = 0.85 if state.startswith("ALIGNED") else 0.65
    return DimensionResult(state, confidence, {"local": local, "intermediate": inter, "macro": mac}, evidence=[{"links": links}], quality_flags=[] if state.startswith("ALIGNED") else ["MULTI_RESOLUTION_CONFLICT"])


def composite_code(states: dict[str, str]) -> str:
    return "__".join(states[dimension] for dimension in DIMENSION_ORDER)


def family_code(states: dict[str, str]) -> str:
    trend = states["trend"]
    vol = states["volatility"]
    shock = states["shock"]
    multi = states["multi_resolution"]
    if shock in {"EVENT_LIKE", "DISCONTINUOUS"}:
        return "TRANSITIONAL_SHOCK"
    if multi.startswith("LOCAL_") or multi == "MIXED":
        return "MIXED_MULTI_SCALE"
    if "UPTREND" in trend:
        return "BULL_TREND_HIGH_VOL" if vol in {"HIGH", "EXTREME"} else "BULL_TREND_LOW_VOL"
    if "DOWNTREND" in trend:
        return "BEAR_TREND_HIGH_VOL" if vol in {"HIGH", "EXTREME"} else "BEAR_TREND_LOW_VOL"
    if trend == "RANGE":
        return "RANGE_LOW_VOL" if vol in {"VERY_LOW", "LOW"} else "RANGE_HIGH_VOL"
    return "UNCERTAIN_CONTEXT"


def classify_market_context(
    market_dna: MarketDNA,
    producer: ContextProducerDefinition | None = None,
    configuration_hash: str | None = None,
    multi_resolution_links: dict[str, Any] | None = None,
) -> ComputedContext:
    producer = producer or get_context_producer("transparent_context_v1")
    cfg = producer.configuration_schema
    features = market_dna.feature_values
    availability = market_dna.availability
    results: dict[str, DimensionResult] = {}
    results["trend"] = classify_trend(features, availability, cfg["trend"])
    results["volatility"] = classify_volatility(features, availability, cfg["volatility"])
    results["volatility_phase"] = classify_volatility_phase(features, availability, cfg["volatility_phase"])
    results["persistence"] = classify_persistence(features, availability, cfg["persistence"])
    results["activity"] = classify_activity(features, availability, cfg["activity"])
    results["shock"] = classify_shock(features, availability, cfg["shock"])
    results["market_phase"] = classify_market_phase(results["trend"], results["volatility_phase"], results["activity"])
    links = multi_resolution_links or {}
    results["multi_resolution"] = classify_multi_resolution(results["trend"].state, links)
    states = {dimension: result.state for dimension, result in results.items()}
    confidences = {dimension: round(result.confidence, 12) for dimension, result in results.items()}
    weights = cfg["composite_weights"]
    composite_confidence = _clip(sum(confidences[dimension] * weights[dimension] for dimension in DIMENSION_ORDER))
    complete_count = sum(1 for result in results.values() if result.state not in {"UNCERTAIN", "UNAVAILABLE"})
    completeness = complete_count / len(DIMENSION_ORDER)
    quality_flags = sorted({flag for result in results.values() for flag in result.quality_flags})
    if completeness < 1.0:
        quality_flags.append("PARTIAL_CONTEXT")
    if composite_confidence < cfg["confidence"]["minimum_composite_confidence"]:
        quality_flags.append("LOW_COMPOSITE_CONFIDENCE")
    full_code = composite_code(states)
    fam_code = family_code(states)
    diagnostics = {
        "producer": producer.code,
        "threshold_mode": cfg["threshold_mode"]["default"],
        "threshold_mode_note": "absolute thresholds are baseline engineering thresholds, not proven market truths",
        "descriptive_reference_quantile_supported": True,
        "historical_as_of_reference_deferred": True,
    }
    hash_payload = {
        "market_dna_id": market_dna.id,
        "producer": producer.code,
        "producer_version": producer.version,
        "configuration_hash": configuration_hash,
        "states": states,
        "confidences": confidences,
        "composite_context_code": full_code,
        "context_family_code": fam_code,
        "completeness_score": completeness,
        "source_feature_vector_hash": market_dna.feature_vector_hash,
        "multi_resolution_links": links,
    }
    return ComputedContext(
        states=states,
        confidences=confidences,
        dimension_scores={dimension: result.scores for dimension, result in results.items()},
        evidence={dimension: result.evidence for dimension, result in results.items()},
        opposing_evidence={dimension: result.opposing_evidence for dimension, result in results.items()},
        diagnostics=diagnostics,
        multi_resolution_links=links,
        composite_context_code=full_code,
        context_family_code=fam_code,
        composite_confidence=round(composite_confidence, 12),
        completeness_score=round(completeness, 12),
        quality_flags=quality_flags or ["NONE"],
        context_hash=context_hash(hash_payload),
    )


class ContextBuildService:
    def __init__(self, session: Session):
        self.session = session

    def build(
        self,
        context_producer_code: str = "transparent_context_v1",
        feature_set_code: str = "market_dna_v1",
        mode: str = "incremental",
        instrument_id: str | None = None,
        timeframe_id: str | None = None,
        window_length: int | None = None,
        start_timestamp: datetime | None = None,
        end_timestamp: datetime | None = None,
    ) -> ContextBuildResult:
        started = time.monotonic()
        if mode not in {"full", "incremental", "range"}:
            raise ValueError("CONTEXT_CONFIGURATION_INVALID")
        producer = get_context_producer(context_producer_code)
        if feature_set_code != producer.required_feature_set_code:
            raise ValueError("CONTEXT_SOURCE_FEATURE_SET_MISMATCH")
        configuration = {
            "context_producer_code": producer.code,
            "context_producer_version": producer.version,
            "feature_set_code": feature_set_code,
            "feature_set_version": producer.required_feature_set_version,
            "producer_configuration": producer.configuration_schema,
            "instrument_id": instrument_id,
            "timeframe_id": timeframe_id,
            "window_length": window_length,
            "start_timestamp": start_timestamp,
            "end_timestamp": end_timestamp,
        }
        config_hash = context_configuration_hash(configuration)
        build = ContextBuild(
            context_producer_code=producer.code,
            context_producer_version=producer.version,
            feature_set_code=feature_set_code,
            feature_set_version=producer.required_feature_set_version,
            instrument_id=instrument_id,
            timeframe_id=timeframe_id,
            window_length=window_length,
            start_timestamp=start_timestamp,
            end_timestamp=end_timestamp,
            mode=mode,
            configuration=configuration,
            configuration_hash=config_hash,
            status=ContextBuildStatus.running.value,
            started_at=datetime.now(UTC),
        )
        self.session.add(build)
        self.session.flush()
        result = ContextBuildResult(build=build)
        try:
            rows = self._select_market_dna(producer, instrument_id, timeframe_id, window_length, start_timestamp, end_timestamp)
            result.source_market_dna_count = len(rows)
            market_dna_ids = {row.id for row in rows}
            existing = self._existing_keys(producer, config_hash, market_dna_ids)
            link_map = self._multi_resolution_link_map(rows, producer, config_hash)
            pending_contexts: list[MarketContext] = []
            for market_dna in rows:
                key = (
                    market_dna.pattern_window_id,
                    market_dna.normalized_pattern_id,
                    market_dna.id,
                    producer.code,
                    producer.version,
                    config_hash,
                    market_dna.source_window_hash,
                    market_dna.source_representation_hash,
                    market_dna.feature_vector_hash,
                )
                if mode == "incremental" and key in existing:
                    result.existing_contexts += 1
                    continue
                try:
                    self._verify_dependencies(market_dna, producer)
                    links = link_map.get(market_dna.id, {})
                    computed = classify_market_context(market_dna, producer, config_hash, links)
                    if key in existing:
                        result.existing_contexts += 1
                        continue
                    context = MarketContext(
                        pattern_window_id=market_dna.pattern_window_id,
                        normalized_pattern_id=market_dna.normalized_pattern_id,
                        market_dna_id=market_dna.id,
                        context_producer_code=producer.code,
                        context_producer_version=producer.version,
                        feature_set_code=market_dna.feature_set_code,
                        feature_set_version=market_dna.feature_set_version,
                        source_window_hash=market_dna.source_window_hash,
                        source_representation_hash=market_dna.source_representation_hash,
                        source_feature_vector_hash=market_dna.feature_vector_hash,
                        configuration_hash=config_hash,
                        context_hash=computed.context_hash,
                        trend_state=computed.states["trend"],
                        volatility_state=computed.states["volatility"],
                        volatility_phase_state=computed.states["volatility_phase"],
                        persistence_state=computed.states["persistence"],
                        activity_state=computed.states["activity"],
                        shock_state=computed.states["shock"],
                        market_phase_state=computed.states["market_phase"],
                        multi_resolution_state=computed.states["multi_resolution"],
                        trend_confidence=computed.confidences["trend"],
                        volatility_confidence=computed.confidences["volatility"],
                        volatility_phase_confidence=computed.confidences["volatility_phase"],
                        persistence_confidence=computed.confidences["persistence"],
                        activity_confidence=computed.confidences["activity"],
                        shock_confidence=computed.confidences["shock"],
                        market_phase_confidence=computed.confidences["market_phase"],
                        multi_resolution_confidence=computed.confidences["multi_resolution"],
                        composite_context_code=computed.composite_context_code,
                        context_family_code=computed.context_family_code,
                        composite_confidence=computed.composite_confidence,
                        completeness_score=computed.completeness_score,
                        dimension_scores=computed.dimension_scores,
                        evidence=computed.evidence,
                        opposing_evidence=computed.opposing_evidence,
                        diagnostics=computed.diagnostics,
                        multi_resolution_links=computed.multi_resolution_links,
                        quality_flags=computed.quality_flags,
                    )
                    self.session.add(context)
                    pending_contexts.append(context)
                    existing.add(key)
                    result.created_contexts += 1
                    if computed.completeness_score < 1.0:
                        result.partial_contexts += 1
                    if len(pending_contexts) >= 1_000:
                        self.session.flush()
                        for pending in pending_contexts:
                            self.session.expunge(pending)
                        pending_contexts.clear()
                except ValueError as exc:
                    result.failed_contexts += 1
                    result.errors.append(str(exc))
            if pending_contexts:
                self.session.flush()
                for pending in pending_contexts:
                    self.session.expunge(pending)
                pending_contexts.clear()
            result.elapsed_seconds = round(time.monotonic() - started, 3)
            build.source_market_dna_count = result.source_market_dna_count
            build.created_context_count = result.created_contexts
            build.existing_context_count = result.existing_contexts
            build.partial_context_count = result.partial_contexts
            build.skipped_context_count = result.skipped_contexts
            build.failed_context_count = result.failed_contexts
            build.status = ContextBuildStatus.completed_with_warnings.value if result.failed_contexts or result.partial_contexts else ContextBuildStatus.completed.value
            build.error_message = "; ".join(result.errors[:5]) or None
            build.completed_at = datetime.now(UTC)
            build.elapsed_seconds = result.elapsed_seconds
            self.session.commit()
            self.session.refresh(build)
            return result
        except Exception as exc:
            build.status = ContextBuildStatus.failed.value
            build.error_message = str(exc)
            build.completed_at = datetime.now(UTC)
            build.elapsed_seconds = round(time.monotonic() - started, 3)
            self.session.commit()
            raise

    def _select_market_dna(self, producer, instrument_id, timeframe_id, window_length, start_timestamp, end_timestamp):
        query = (
            select(MarketDNA)
            .join(PatternWindow, PatternWindow.id == MarketDNA.pattern_window_id)
            .options(selectinload(MarketDNA.pattern_window), selectinload(MarketDNA.normalized_pattern))
            .where(
                MarketDNA.feature_set_code == producer.required_feature_set_code,
                MarketDNA.feature_set_version == producer.required_feature_set_version,
            )
        )
        if instrument_id:
            query = query.where(PatternWindow.instrument_id == instrument_id)
        if timeframe_id:
            query = query.where(PatternWindow.timeframe_id == timeframe_id)
        if window_length:
            query = query.where(PatternWindow.window_length == window_length)
        if start_timestamp:
            query = query.where(PatternWindow.end_timestamp >= start_timestamp)
        if end_timestamp:
            query = query.where(PatternWindow.end_timestamp <= end_timestamp)
        return list(self.session.scalars(query.order_by(PatternWindow.end_timestamp, PatternWindow.window_length, MarketDNA.id)))

    def _verify_dependencies(self, market_dna: MarketDNA, producer) -> None:
        window = market_dna.pattern_window
        normalized = market_dna.normalized_pattern
        if market_dna.feature_set_code != producer.required_feature_set_code or market_dna.feature_set_version != producer.required_feature_set_version:
            raise ValueError("CONTEXT_SOURCE_FEATURE_SET_MISMATCH")
        if market_dna.source_window_hash != window.source_data_hash:
            raise ValueError("CONTEXT_SOURCE_WINDOW_HASH_MISMATCH")
        rep_hash = representation_hash(
            {
                "channel_schema": normalized.channel_schema,
                "values": normalized.normalized_values,
                "method": normalized.normalization_method,
                "version": normalized.normalization_version,
                "resampling_method": normalized.resampling_method,
                "resample_points": normalized.resample_points,
                "precision": normalized.diagnostics.get("storage_precision", 12),
                "source_window_hash": normalized.source_window_hash,
                "configuration_hash": normalized.configuration_hash,
            }
        )
        if rep_hash != market_dna.source_representation_hash:
            raise ValueError("CONTEXT_SOURCE_REPRESENTATION_HASH_MISMATCH")
        vector_hash = feature_vector_hash(
            {
                "feature_set_code": market_dna.feature_set_code,
                "feature_set_version": market_dna.feature_set_version,
                "configuration_hash": market_dna.configuration_hash,
                "source_window_hash": market_dna.source_window_hash,
                "source_representation_hash": market_dna.source_representation_hash,
                "feature_vector": market_dna.feature_vector,
                "availability": market_dna.availability,
            }
        )
        if vector_hash != market_dna.feature_vector_hash:
            raise ValueError("CONTEXT_SOURCE_FEATURE_HASH_MISMATCH")

    def _existing_keys(self, producer, configuration_hash: str, market_dna_ids: set[str]) -> set[tuple[Any, ...]]:
        if not market_dna_ids:
            return set()
        rows = self.session.execute(
            select(
                MarketContext.pattern_window_id,
                MarketContext.normalized_pattern_id,
                MarketContext.market_dna_id,
                MarketContext.context_producer_code,
                MarketContext.context_producer_version,
                MarketContext.configuration_hash,
                MarketContext.source_window_hash,
                MarketContext.source_representation_hash,
                MarketContext.source_feature_vector_hash,
            ).where(
                MarketContext.context_producer_code == producer.code,
                MarketContext.context_producer_version == producer.version,
                MarketContext.configuration_hash == configuration_hash,
                MarketContext.market_dna_id.in_(market_dna_ids),
            )
        )
        return {tuple(row) for row in rows}

    def _multi_resolution_link_map(self, rows: list[MarketDNA], producer, configuration_hash: str) -> dict[str, dict[str, Any]]:
        by_key: dict[tuple[str, str, datetime], dict[int, MarketDNA]] = {}
        for row in rows:
            window = row.pattern_window
            by_key.setdefault((window.instrument_id, window.timeframe_id, window.end_timestamp), {})[window.window_length] = row
        out: dict[str, dict[str, Any]] = {}
        cfg = producer.configuration_schema["multi_resolution"]
        for row in rows:
            window = row.pattern_window
            same_time = by_key.get((window.instrument_id, window.timeframe_id, window.end_timestamp), {})
            links: dict[str, Any] = {}
            for name, length in (("local", cfg["local_length"]), ("intermediate", cfg["intermediate_length"]), ("macro", cfg["macro_length"])):
                candidate = same_time.get(length)
                if candidate is not None and candidate.id != row.id:
                    computed = classify_market_context(candidate, producer, configuration_hash, {})
                    links[name] = {
                        "market_dna_id": candidate.id,
                        "pattern_window_id": candidate.pattern_window_id,
                        "window_length": candidate.pattern_window.window_length,
                        "end_timestamp": candidate.pattern_window.end_timestamp.isoformat(),
                        "trend_state": computed.states["trend"],
                    }
            out[row.id] = links
        return out
