from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import numpy as np
from market_genome_diagnostics.service import availability_aware_distance
from market_genome_domain.models import (
    MarketContext,
    MarketDNA,
    NormalizedPattern,
    PatternWindow,
    SimilarityMatch,
    SimilarityQuery,
    SimilarityQueryStatus,
)
from market_genome_features.definitions import FEATURE_DEFINITIONS, MARKET_DNA_V1_FEATURES
from market_genome_shared.hashing import sha256_canonical
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from market_genome_similarity.definitions import SimilarityMethodDefinition, get_similarity_method


@dataclass(frozen=True)
class SimilarityInput:
    window: PatternWindow
    normalized_pattern: NormalizedPattern | None
    market_dna: MarketDNA | None
    market_context: MarketContext | None


@dataclass(frozen=True)
class SimilarityScore:
    distance: float
    similarity_score: float
    component_scores: dict[str, Any]
    quality_flags: list[str]


@dataclass
class SimilaritySearchResult:
    query: SimilarityQuery
    candidate_count: int = 0
    returned_match_count: int = 0
    elapsed_seconds: float | None = None
    errors: list[str] = field(default_factory=list)


def similarity_configuration_hash(configuration: dict[str, Any]) -> str:
    return sha256_canonical(configuration)


def query_hash(payload: dict[str, Any]) -> str:
    return sha256_canonical(payload)


def vector_hash(payload: dict[str, Any]) -> str:
    return sha256_canonical(payload)


def _shape_vector(item: SimilarityInput) -> np.ndarray:
    if item.normalized_pattern is None:
        raise ValueError("SIMILARITY_NORMALIZED_PATTERN_REQUIRED")
    values = item.normalized_pattern.normalized_values.get("close", [])
    vector = np.asarray(values, dtype=np.float64)
    if len(vector) < 2 or not np.all(np.isfinite(vector)):
        raise ValueError("SIMILARITY_INVALID_SHAPE_VECTOR")
    return vector


def _dna_vector_pair(query: SimilarityInput, candidate: SimilarityInput) -> tuple[np.ndarray, np.ndarray, int]:
    if query.market_dna is None or candidate.market_dna is None:
        raise ValueError("SIMILARITY_MARKET_DNA_REQUIRED")
    query_features = query.market_dna.feature_values
    candidate_features = candidate.market_dna.feature_values
    keys = [
        key
        for key in query.market_dna.feature_vector["ordered_features"]
        if query_features.get(key) is not None and candidate_features.get(key) is not None
    ]
    if not keys:
        raise ValueError("SIMILARITY_NO_COMMON_FEATURES")
    return (
        np.asarray([float(query_features[key]) for key in keys], dtype=np.float64),
        np.asarray([float(candidate_features[key]) for key in keys], dtype=np.float64),
        len(keys),
    )


def _dna_feature_dict(item: SimilarityInput, robust_compress: bool = False) -> dict[str, float | None]:
    if item.market_dna is None:
        raise ValueError("SIMILARITY_MARKET_DNA_REQUIRED")
    values: dict[str, float | None] = {}
    for feature in MARKET_DNA_V1_FEATURES:
        value = item.market_dna.feature_values.get(feature)
        if value is None:
            values[feature] = None
            continue
        x = float(value)
        values[feature] = math.copysign(math.log1p(abs(x)), x) if robust_compress else x
    return values


def _dna_groups() -> dict[str, str]:
    return {feature: FEATURE_DEFINITIONS[feature].feature_group for feature in MARKET_DNA_V1_FEATURES}


def _euclidean(a: np.ndarray, b: np.ndarray) -> float:
    if len(a) != len(b):
        raise ValueError("SIMILARITY_VECTOR_LENGTH_MISMATCH")
    return float(np.linalg.norm(a - b) / math.sqrt(len(a)))


def _correlation_distance(a: np.ndarray, b: np.ndarray) -> float:
    if len(a) != len(b):
        raise ValueError("SIMILARITY_VECTOR_LENGTH_MISMATCH")
    if float(np.std(a)) < 1e-12 or float(np.std(b)) < 1e-12:
        return 1.0
    corr = float(np.corrcoef(a, b)[0, 1])
    return float(1.0 - max(-1.0, min(1.0, corr)))


def _cosine_distance(a: np.ndarray, b: np.ndarray) -> float:
    denominator = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denominator < 1e-12:
        return 1.0
    cosine = float(np.dot(a, b) / denominator)
    return float(1.0 - max(-1.0, min(1.0, cosine)))


def _context_distance(query: SimilarityInput, candidate: SimilarityInput) -> float:
    if query.market_context is None or candidate.market_context is None:
        return 1.0
    dimensions = [
        "trend_state",
        "volatility_state",
        "volatility_phase_state",
        "persistence_state",
        "activity_state",
        "shock_state",
        "market_phase_state",
    ]
    matches = sum(1 for attr in dimensions if getattr(query.market_context, attr) == getattr(candidate.market_context, attr))
    return 1.0 - matches / len(dimensions)


def _score(distance: float) -> float:
    return float(1.0 / (1.0 + max(0.0, distance)))


def compute_similarity(
    query: SimilarityInput,
    candidate: SimilarityInput,
    method: SimilarityMethodDefinition | str = "market_analogue_v1",
    configuration: dict[str, Any] | None = None,
) -> SimilarityScore:
    method = get_similarity_method(method) if isinstance(method, str) else method
    cfg = method.default_configuration | (configuration or {})
    flags: list[str] = []
    components: dict[str, Any] = {}
    if method.code == "shape_euclidean_v1":
        distance = _euclidean(_shape_vector(query), _shape_vector(candidate))
        components["shape_euclidean_distance"] = distance
    elif method.code == "shape_correlation_v1":
        distance = _correlation_distance(_shape_vector(query), _shape_vector(candidate))
        components["shape_correlation_distance"] = distance
    elif method.code == "dna_cosine_v1":
        qa, ca, common = _dna_vector_pair(query, candidate)
        if common < int(cfg["minimum_common_features"]):
            flags.append("LOW_COMMON_FEATURE_COUNT")
        distance = _cosine_distance(qa, ca)
        components |= {"dna_cosine_distance": distance, "common_feature_count": common}
    elif method.code == "market_analogue_v1":
        shape_distance = _euclidean(_shape_vector(query), _shape_vector(candidate))
        try:
            qa, ca, common = _dna_vector_pair(query, candidate)
            dna_distance = _cosine_distance(qa, ca)
            if common < int(cfg["minimum_common_features"]):
                flags.append("LOW_COMMON_FEATURE_COUNT")
        except ValueError:
            dna_distance = 1.0
            common = 0
            flags.append("DNA_UNAVAILABLE")
        context_distance = _context_distance(query, candidate)
        distance = (
            float(cfg["shape_weight"]) * shape_distance
            + float(cfg["dna_weight"]) * dna_distance
            + float(cfg["context_weight"]) * context_distance
        )
        components |= {
            "shape_euclidean_distance": shape_distance,
            "dna_cosine_distance": dna_distance,
            "context_distance": context_distance,
            "common_feature_count": common,
            "weights": {
                "shape": cfg["shape_weight"],
                "dna": cfg["dna_weight"],
                "context": cfg["context_weight"],
            },
        }
    elif method.code in {"dna_robust_cosine_v1", "dna_robust_euclidean_v1", "dna_group_balanced_v1"}:
        distance_result = availability_aware_distance(
            _dna_feature_dict(query, robust_compress=True),
            _dna_feature_dict(candidate, robust_compress=True),
            _dna_groups(),
            policy=cfg["availability_policy"],
            minimum_joint_feature_ratio=float(cfg["minimum_joint_feature_ratio"]),
            metric="euclidean" if method.code == "dna_robust_euclidean_v1" else "cosine",
            group_balanced=method.code == "dna_group_balanced_v1",
        )
        distance = distance_result.distance
        flags.extend(distance_result.quality_flags)
        components |= {
            "dna_availability_aware_distance": distance_result.distance,
            "joint_feature_count": distance_result.joint_feature_count,
            "joint_feature_ratio": distance_result.joint_feature_ratio,
            "group_coverage": distance_result.group_coverage,
            "availability_policy": cfg["availability_policy"],
            "rejected_by_coverage": distance_result.rejected,
        }
    elif method.code in {"shape_dna_context_v2", "episode_diverse_analogue_v1"}:
        if method.code == "episode_diverse_analogue_v1":
            cfg = get_similarity_method(cfg["underlying_similarity_method"]).default_configuration | cfg
        shape_distance = _euclidean(_shape_vector(query), _shape_vector(candidate))
        distance_result = availability_aware_distance(
            _dna_feature_dict(query, robust_compress=True),
            _dna_feature_dict(candidate, robust_compress=True),
            _dna_groups(),
            policy=cfg["availability_policy"],
            minimum_joint_feature_ratio=float(cfg["minimum_joint_feature_ratio"]),
            metric="cosine",
        )
        context_distance = _context_distance(query, candidate)
        distance = (
            float(cfg["shape_weight"]) * shape_distance
            + float(cfg["dna_weight"]) * distance_result.distance
            + float(cfg["context_weight"]) * context_distance
        )
        flags.extend(distance_result.quality_flags)
        components |= {
            "shape_euclidean_distance": shape_distance,
            "dna_availability_aware_distance": distance_result.distance,
            "context_distance": context_distance,
            "joint_feature_count": distance_result.joint_feature_count,
            "joint_feature_ratio": distance_result.joint_feature_ratio,
            "group_coverage": distance_result.group_coverage,
            "weights": {"shape": cfg["shape_weight"], "dna": cfg["dna_weight"], "context": cfg["context_weight"]},
        }
    else:
        raise ValueError("SIMILARITY_METHOD_NOT_SUPPORTED")
    return SimilarityScore(distance=distance, similarity_score=_score(distance), component_scores=components, quality_flags=flags or ["NONE"])


class SimilaritySearchService:
    def __init__(self, session: Session):
        self.session = session

    def search(
        self,
        query_window_id: str,
        similarity_method_code: str = "market_analogue_v1",
        top_k: int = 20,
        instrument_id: str | None = None,
        timeframe_id: str | None = None,
        window_length: int | None = None,
        temporal_policy: str = "historical_only",
        include_self: bool = False,
    ) -> SimilaritySearchResult:
        started = time.monotonic()
        if top_k <= 0:
            raise ValueError("SIMILARITY_TOP_K_INVALID")
        if temporal_policy not in {"historical_only", "all"}:
            raise ValueError("SIMILARITY_TEMPORAL_POLICY_INVALID")
        method = get_similarity_method(similarity_method_code)
        query_input = self._input_for_window(query_window_id, method)
        configuration = {
            "query_window_id": query_window_id,
            "similarity_method_code": method.code,
            "similarity_method_version": method.version,
            "method_configuration": method.default_configuration,
            "top_k": top_k,
            "instrument_id": instrument_id,
            "timeframe_id": timeframe_id,
            "window_length": window_length,
            "temporal_policy": temporal_policy,
            "include_self": include_self,
        }
        config_hash = similarity_configuration_hash(configuration)
        q_hash = query_hash(
            {
                "query_window_id": query_window_id,
                "query_source_hash": query_input.window.source_data_hash,
                "query_normalized_pattern_hash": query_input.normalized_pattern.representation_hash
                if query_input.normalized_pattern
                else None,
                "query_market_dna_hash": query_input.market_dna.feature_vector_hash if query_input.market_dna else None,
                "configuration_hash": config_hash,
            }
        )
        query_record = SimilarityQuery(
            query_window_id=query_window_id,
            query_normalized_pattern_id=query_input.normalized_pattern.id if query_input.normalized_pattern else None,
            query_market_dna_id=query_input.market_dna.id if query_input.market_dna else None,
            similarity_method_code=method.code,
            similarity_method_version=method.version,
            feature_set_code=query_input.market_dna.feature_set_code if query_input.market_dna else None,
            feature_set_version=query_input.market_dna.feature_set_version if query_input.market_dna else None,
            normalization_method=query_input.normalized_pattern.normalization_method if query_input.normalized_pattern else None,
            normalization_version=query_input.normalized_pattern.normalization_version if query_input.normalized_pattern else None,
            resampling_method=query_input.normalized_pattern.resampling_method if query_input.normalized_pattern else None,
            resample_points=query_input.normalized_pattern.resample_points if query_input.normalized_pattern else None,
            top_k=top_k,
            temporal_policy=temporal_policy,
            configuration=configuration,
            configuration_hash=config_hash,
            query_hash=q_hash,
            status=SimilarityQueryStatus.running.value,
            started_at=datetime.now(UTC),
            diagnostics={},
        )
        self.session.add(query_record)
        self.session.flush()
        result = SimilaritySearchResult(query=query_record)
        try:
            scored = []
            for candidate in self._candidates(query_input, instrument_id, timeframe_id, window_length, temporal_policy, include_self, method):
                try:
                    score = compute_similarity(query_input, candidate, method)
                    scored.append((score.distance, -score.similarity_score, candidate, score))
                except ValueError as exc:
                    result.errors.append(str(exc))
            scored.sort(key=lambda item: (item[0], item[2].window.end_timestamp, item[2].window.id))
            result.candidate_count = len(scored)
            for rank, (_, _, candidate, score) in enumerate(scored[:top_k], start=1):
                self.session.add(
                    SimilarityMatch(
                        query_id=query_record.id,
                        query_window_id=query_input.window.id,
                        candidate_window_id=candidate.window.id,
                        candidate_normalized_pattern_id=candidate.normalized_pattern.id if candidate.normalized_pattern else None,
                        candidate_market_dna_id=candidate.market_dna.id if candidate.market_dna else None,
                        rank=rank,
                        distance=score.distance,
                        similarity_score=score.similarity_score,
                        similarity_method_code=method.code,
                        similarity_method_version=method.version,
                        configuration_hash=config_hash,
                        query_source_hash=query_input.window.source_data_hash,
                        candidate_source_hash=candidate.window.source_data_hash,
                        query_vector_hash=self._input_hash(query_input),
                        candidate_vector_hash=self._input_hash(candidate),
                        component_scores=score.component_scores,
                        diagnostics={
                            "query_end_timestamp": query_input.window.end_timestamp.isoformat(),
                            "candidate_end_timestamp": candidate.window.end_timestamp.isoformat(),
                            "temporal_policy": temporal_policy,
                            "uses_future_outcomes": False,
                        },
                        quality_flags=score.quality_flags,
                    )
                )
                result.returned_match_count += 1
            result.elapsed_seconds = round(time.monotonic() - started, 3)
            query_record.candidate_count = result.candidate_count
            query_record.returned_match_count = result.returned_match_count
            query_record.status = SimilarityQueryStatus.completed_with_warnings.value if result.errors else SimilarityQueryStatus.completed.value
            query_record.error_message = "; ".join(result.errors[:5]) or None
            query_record.elapsed_seconds = result.elapsed_seconds
            query_record.completed_at = datetime.now(UTC)
            query_record.diagnostics = {
                "candidate_count": result.candidate_count,
                "returned_match_count": result.returned_match_count,
                "error_count": len(result.errors),
                "uses_future_outcomes": False,
            }
            self.session.commit()
            self.session.refresh(query_record)
            return result
        except Exception as exc:
            query_record.status = SimilarityQueryStatus.failed.value
            query_record.error_message = str(exc)
            query_record.completed_at = datetime.now(UTC)
            query_record.elapsed_seconds = round(time.monotonic() - started, 3)
            self.session.commit()
            raise

    def _input_for_window(self, window_id: str, method: SimilarityMethodDefinition) -> SimilarityInput:
        window = self.session.get(PatternWindow, window_id)
        if window is None:
            raise ValueError("SIMILARITY_QUERY_WINDOW_NOT_FOUND")
        normalized = self.session.scalar(
            select(NormalizedPattern)
            .where(NormalizedPattern.pattern_window_id == window_id)
            .order_by(NormalizedPattern.created_at.desc())
            .limit(1)
        )
        market_dna = self.session.scalar(
            select(MarketDNA)
            .where(MarketDNA.pattern_window_id == window_id)
            .order_by(MarketDNA.created_at.desc())
            .limit(1)
        )
        context = self.session.scalar(
            select(MarketContext)
            .where(MarketContext.pattern_window_id == window_id)
            .order_by(MarketContext.created_at.desc())
            .limit(1)
        )
        if "normalized_pattern.close" in method.input_sources and normalized is None:
            raise ValueError("SIMILARITY_NORMALIZED_PATTERN_REQUIRED")
        if method.code == "dna_cosine_v1" and market_dna is None:
            raise ValueError("SIMILARITY_MARKET_DNA_REQUIRED")
        return SimilarityInput(window=window, normalized_pattern=normalized, market_dna=market_dna, market_context=context)

    def _candidates(
        self,
        query_input: SimilarityInput,
        instrument_id: str | None,
        timeframe_id: str | None,
        window_length: int | None,
        temporal_policy: str,
        include_self: bool,
        method: SimilarityMethodDefinition,
    ) -> list[SimilarityInput]:
        query = select(PatternWindow).options(selectinload(PatternWindow.instrument), selectinload(PatternWindow.timeframe))
        if instrument_id:
            query = query.where(PatternWindow.instrument_id == instrument_id)
        if timeframe_id:
            query = query.where(PatternWindow.timeframe_id == timeframe_id)
        if window_length:
            query = query.where(PatternWindow.window_length == window_length)
        else:
            query = query.where(PatternWindow.window_length == query_input.window.window_length)
        if temporal_policy == "historical_only":
            query = query.where(PatternWindow.end_timestamp < query_input.window.end_timestamp)
        if not include_self:
            query = query.where(PatternWindow.id != query_input.window.id)
        candidates = []
        for window in self.session.scalars(query.order_by(PatternWindow.end_timestamp, PatternWindow.id)):
            try:
                candidates.append(self._input_for_window(window.id, method))
            except ValueError:
                continue
        return candidates

    def _input_hash(self, item: SimilarityInput) -> str:
        return vector_hash(
            {
                "window_id": item.window.id,
                "source_window_hash": item.window.source_data_hash,
                "normalized_pattern_hash": item.normalized_pattern.representation_hash if item.normalized_pattern else None,
                "market_dna_hash": item.market_dna.feature_vector_hash if item.market_dna else None,
                "context_hash": item.market_context.context_hash if item.market_context else None,
            }
        )
