from __future__ import annotations

import json
import math
import random
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
from market_genome_domain.models import (
    DiagnosticArtifact,
    ExperimentRun,
    ExperimentRunStatus,
    FeatureScalingSnapshot,
    MarketContext,
    MarketDNA,
    OutcomeObservation,
    PatternWindow,
)
from market_genome_features.definitions import FEATURE_DEFINITIONS, MARKET_DNA_V1_FEATURES
from market_genome_shared.hashing import sha256_canonical
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from market_genome_diagnostics.definitions import (
    get_availability_policy,
    get_diagnostic_definition,
    get_scaling_method,
)

MAD_CONSISTENCY = 1.4826


@dataclass(frozen=True)
class FeatureMatrix:
    ids: list[str]
    window_ids: list[str]
    feature_codes: list[str]
    groups: dict[str, str]
    values: np.ndarray
    available: np.ndarray


@dataclass(frozen=True)
class AvailabilityDistance:
    distance: float
    similarity_score: float
    joint_feature_count: int
    joint_feature_ratio: float
    group_coverage: dict[str, float]
    rejected: bool
    quality_flags: list[str]


@dataclass(frozen=True)
class EpisodeAssignment:
    candidate_id: str
    episode_id: str


def canonical_hash(payload: Any) -> str:
    return sha256_canonical(payload)


def load_diagnostic_config(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("DIAGNOSTIC_CONFIGURATION_INVALID") from exc


def finite_values(values: list[float | None]) -> list[float]:
    return [float(value) for value in values if value is not None and math.isfinite(float(value))]


def quantile(values: list[float], q: float) -> float | None:
    return None if not values else float(np.quantile(np.asarray(values, dtype=np.float64), q))


def median(values: list[float]) -> float | None:
    return quantile(values, 0.5)


def mad(values: list[float]) -> float | None:
    med = median(values)
    return None if med is None else float(np.median(np.abs(np.asarray(values, dtype=np.float64) - med)))


def feature_distribution(values: list[float | None], total_count: int | None = None) -> dict[str, Any]:
    total = total_count or len(values)
    finite = finite_values(values)
    unavailable = total - len([value for value in values if value is not None])
    non_finite = len([value for value in values if value is not None]) - len(finite)
    if not finite:
        return {
            "available_count": 0,
            "unavailable_count": unavailable,
            "availability_rate": 0.0,
            "finite_count": 0,
            "non_finite_count": non_finite,
            "near_constant": True,
            "extreme_outlier_rate": 0.0,
        }
    arr = np.asarray(finite, dtype=np.float64)
    q1, q5, q25, q50, q75, q95, q99 = [float(np.quantile(arr, q)) for q in (0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99)]
    std = float(np.std(arr, ddof=1)) if len(arr) > 1 else 0.0
    mad_value = float(np.median(np.abs(arr - q50)))
    iqr = q75 - q25
    robust_scale = max(MAD_CONSISTENCY * mad_value, iqr / 1.349 if iqr > 0 else 0.0, 1e-12)
    outlier_rate = float(np.mean(np.abs(arr - q50) > 10.0 * robust_scale))
    unique_count = len({round(float(value), 12) for value in arr})
    return {
        "available_count": len([value for value in values if value is not None]),
        "unavailable_count": unavailable,
        "availability_rate": len([value for value in values if value is not None]) / max(1, total),
        "finite_count": len(finite),
        "non_finite_count": non_finite,
        "mean": float(np.mean(arr)),
        "standard_deviation": std,
        "minimum": float(np.min(arr)),
        "maximum": float(np.max(arr)),
        "median": q50,
        "mad": mad_value,
        "quantiles": {"0.01": q1, "0.05": q5, "0.25": q25, "0.50": q50, "0.75": q75, "0.95": q95, "0.99": q99},
        "unique_value_count": unique_count,
        "near_constant": unique_count <= 1 or std < 1e-12 or iqr < 1e-12,
        "extreme_outlier_rate": outlier_rate,
        "robust_scale": robust_scale,
        "range": float(np.max(arr) - np.min(arr)),
        "iqr": iqr,
    }


def scaling_statistics(values_by_feature: dict[str, list[float | None]]) -> dict[str, dict[str, Any]]:
    return {feature: feature_distribution(values) for feature, values in values_by_feature.items()}


def scale_value(value: float | None, stats: dict[str, Any], method: str) -> float | None:
    if value is None or not math.isfinite(float(value)):
        return None
    x = float(value)
    if method == "none_v1":
        return x
    if method == "zscore_reference_v1":
        return (x - float(stats.get("mean", 0.0))) / max(float(stats.get("standard_deviation") or 0.0), 1e-12)
    if method in {"robust_median_mad_v1", "group_balanced_robust_v1"}:
        return (x - float(stats.get("median", 0.0))) / max(MAD_CONSISTENCY * float(stats.get("mad") or 0.0), 1e-12)
    if method == "robust_iqr_v1":
        return (x - float(stats.get("median", 0.0))) / max(float(stats.get("iqr") or 0.0) / 1.349, 1e-12)
    if method == "winsorized_zscore_v1":
        low = float(stats.get("quantiles", {}).get("0.01", x))
        high = float(stats.get("quantiles", {}).get("0.99", x))
        clipped = min(high, max(low, x))
        return (clipped - float(stats.get("mean", 0.0))) / max(float(stats.get("standard_deviation") or 0.0), 1e-12)
    raise ValueError("DIAGNOSTIC_SCALING_FAILED")


def scale_feature_dict(values: dict[str, Any], stats: dict[str, dict[str, Any]], method: str) -> dict[str, float | None]:
    get_scaling_method(method)
    return {feature: scale_value(values.get(feature), stats.get(feature, {}), method) for feature in MARKET_DNA_V1_FEATURES}


def joint_group_coverage(keys: list[str], groups: dict[str, str]) -> dict[str, float]:
    all_groups: dict[str, int] = {}
    joint_groups: dict[str, int] = {}
    for feature, group in groups.items():
        all_groups[group] = all_groups.get(group, 0) + 1
        if feature in keys:
            joint_groups[group] = joint_groups.get(group, 0) + 1
    return {group: joint_groups.get(group, 0) / max(1, count) for group, count in all_groups.items()}


def availability_aware_distance(
    query: dict[str, float | None],
    candidate: dict[str, float | None],
    groups: dict[str, str],
    *,
    policy: str = "joint_available_with_coverage_penalty_v1",
    minimum_joint_feature_ratio: float = 0.7,
    metric: str = "cosine",
    group_balanced: bool = False,
) -> AvailabilityDistance:
    get_availability_policy(policy)
    ordered = [feature for feature in MARKET_DNA_V1_FEATURES if feature in query or feature in candidate]
    keys = [feature for feature in ordered if query.get(feature) is not None and candidate.get(feature) is not None]
    ratio = len(keys) / max(1, len(ordered))
    coverage = joint_group_coverage(keys, groups)
    flags: list[str] = []
    if not keys:
        return AvailabilityDistance(1.0, 0.0, 0, 0.0, coverage, True, ["NO_JOINT_FEATURES"])
    if policy in {"minimum_coverage_reject_v1", "group_balanced_availability_v1"} and ratio < minimum_joint_feature_ratio:
        return AvailabilityDistance(1.0, 0.0, len(keys), ratio, coverage, True, ["LOW_JOINT_FEATURE_RATIO"])
    qa = np.asarray([float(query[feature]) for feature in keys], dtype=np.float64)
    ca = np.asarray([float(candidate[feature]) for feature in keys], dtype=np.float64)
    if group_balanced or policy == "group_balanced_availability_v1":
        group_weights = np.asarray([1.0 / max(1, sum(1 for key in keys if groups.get(key) == groups.get(feature))) for feature in keys], dtype=np.float64)
        qa = qa * group_weights
        ca = ca * group_weights
    if metric == "euclidean":
        distance = float(np.linalg.norm(qa - ca) / math.sqrt(len(keys)))
    else:
        denom = float(np.linalg.norm(qa) * np.linalg.norm(ca))
        distance = 1.0 if denom < 1e-12 else float(1.0 - max(-1.0, min(1.0, float(np.dot(qa, ca) / denom))))
    if policy in {"joint_available_with_coverage_penalty_v1", "group_balanced_availability_v1"}:
        distance += 1.0 - ratio
        flags.append("COVERAGE_PENALTY_APPLIED")
    return AvailabilityDistance(distance, 1.0 / (1.0 + max(0.0, distance)), len(keys), ratio, coverage, False, flags or ["NONE"])


def rankdata(values: list[float]) -> list[float]:
    ordered = sorted(enumerate(values), key=lambda item: item[1])
    ranks = [0.0] * len(values)
    index = 0
    while index < len(ordered):
        end = index
        while end + 1 < len(ordered) and ordered[end + 1][1] == ordered[index][1]:
            end += 1
        rank = (index + end + 2) / 2.0
        for offset in range(index, end + 1):
            ranks[ordered[offset][0]] = rank
        index = end + 1
    return ranks


def pearson(a: list[float], b: list[float]) -> float:
    if len(a) < 2 or len(b) < 2:
        return 0.0
    av = np.asarray(a, dtype=np.float64)
    bv = np.asarray(b, dtype=np.float64)
    if float(np.std(av)) < 1e-12 or float(np.std(bv)) < 1e-12:
        return 0.0
    return float(np.corrcoef(av, bv)[0, 1])


def spearman(a: list[float], b: list[float]) -> float:
    return pearson(rankdata(a), rankdata(b))


def redundancy_clusters(matrix: list[dict[str, float | None]], feature_codes: list[str], threshold: float = 0.95) -> dict[str, Any]:
    correlations: dict[str, dict[str, float]] = {}
    for left in feature_codes:
        correlations[left] = {}
        for right in feature_codes:
            pairs = [(row[left], row[right]) for row in matrix if row.get(left) is not None and row.get(right) is not None]
            corr = pearson([float(x) for x, _ in pairs], [float(y) for _, y in pairs]) if len(pairs) >= 3 else 0.0
            correlations[left][right] = corr
    parent = {feature: feature for feature in feature_codes}

    def find(feature: str) -> str:
        while parent[feature] != feature:
            parent[feature] = parent[parent[feature]]
            feature = parent[feature]
        return feature

    def union(left: str, right: str) -> None:
        l_root, r_root = find(left), find(right)
        if l_root != r_root:
            parent[max(l_root, r_root)] = min(l_root, r_root)

    for idx, left in enumerate(feature_codes):
        for right in feature_codes[idx + 1 :]:
            if abs(correlations[left][right]) >= threshold:
                union(left, right)
    clusters: dict[str, list[str]] = {}
    for feature in feature_codes:
        clusters.setdefault(find(feature), []).append(feature)
    payload = {
        "threshold": threshold,
        "clusters": [sorted(features) for features in sorted(clusters.values(), key=lambda item: (len(item), item[0]), reverse=True) if len(features) > 1],
        "mean_absolute_correlation": float(np.mean([abs(correlations[a][b]) for a in feature_codes for b in feature_codes if a != b])) if len(feature_codes) > 1 else 0.0,
        "correlations": {feature: {other: round(value, 6) for other, value in row.items()} for feature, row in correlations.items()},
    }
    return payload


def assign_similarity_deciles(scores: list[tuple[str, float]]) -> list[dict[str, Any]]:
    ordered = sorted(scores, key=lambda item: (-item[1], item[0]))
    n = len(ordered)
    rows = []
    for idx, (candidate_id, score) in enumerate(ordered):
        decile = min(10, int(idx * 10 / max(1, n)) + 1)
        rows.append({"candidate_id": candidate_id, "similarity_score": score, "decile": decile})
    return rows


def distance_outcome_monotonicity(rows: list[dict[str, float]], bins: int = 10) -> dict[str, Any]:
    if not rows:
        return {"curve": [], "spearman": 0.0, "decision": "INSUFFICIENT_SAMPLE"}
    ordered = sorted(rows, key=lambda item: (item["distance"], item.get("candidate_id", "")))
    curve = []
    for bin_index in range(bins):
        start = int(bin_index * len(ordered) / bins)
        end = int((bin_index + 1) * len(ordered) / bins)
        members = ordered[start:end]
        if not members:
            continue
        diffs = [float(item["outcome_discrepancy"]) for item in members]
        curve.append({"decile": bin_index + 1, "sample_count": len(members), "mean_outcome_discrepancy": float(np.mean(diffs)), "median_outcome_discrepancy": float(np.median(diffs))})
    corr = spearman([float(item["distance"]) for item in ordered], [float(item["outcome_discrepancy"]) for item in ordered]) if len(ordered) >= 3 else 0.0
    return {"curve": curve, "spearman": corr, "decision": "MONOTONIC" if corr > 0.1 else "FLAT_OR_INVERSE"}


def outcome_dispersion(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"sample_count": 0}
    arr = np.asarray(values, dtype=np.float64)
    q25, q75 = np.quantile(arr, [0.25, 0.75])
    med = float(np.median(arr))
    return {
        "sample_count": len(values),
        "standard_deviation": float(np.std(arr, ddof=1)) if len(values) > 1 else 0.0,
        "mad": float(np.median(np.abs(arr - med))),
        "iqr": float(q75 - q25),
        "median": med,
    }


def entropy(labels: list[str]) -> float:
    if not labels:
        return 0.0
    counts: dict[str, int] = {}
    for label in labels:
        counts[label] = counts.get(label, 0) + 1
    total = len(labels)
    return float(-sum((count / total) * math.log2(count / total) for count in counts.values()))


def neighbour_dispersion(outcomes: list[OutcomeObservation]) -> dict[str, Any]:
    returns = [float(row.future_simple_return) for row in outcomes if row.future_simple_return is not None]
    return {
        "return": outcome_dispersion(returns),
        "direction_entropy": entropy([row.direction_class for row in outcomes]),
        "continuation_entropy": entropy([row.continuation_reversal_class for row in outcomes]),
        "mfe": outcome_dispersion([float(row.maximum_favourable_excursion or 0.0) for row in outcomes]),
        "mae": outcome_dispersion([float(row.maximum_adverse_excursion or 0.0) for row in outcomes]),
    }


def episode_id(window: PatternWindow, grouping_distance_bars: int = 32) -> str:
    bucket = int(window.end_timestamp.timestamp() // max(1, grouping_distance_bars))
    return canonical_hash([window.instrument_id, window.timeframe_id, bucket])[:16]


def episode_assignments(windows: list[PatternWindow], grouping_distance_bars: int = 32) -> list[EpisodeAssignment]:
    return [EpisodeAssignment(window.id, episode_id(window, grouping_distance_bars)) for window in sorted(windows, key=lambda item: (item.instrument_id, item.timeframe_id, item.end_timestamp, item.id))]


def enforce_episode_cap(matches: list[tuple[PatternWindow, float]], maximum_per_episode: int | None, grouping_distance_bars: int = 32) -> list[tuple[PatternWindow, float]]:
    if maximum_per_episode is None:
        return matches
    counts: dict[str, int] = {}
    kept = []
    for window, score in matches:
        eid = episode_id(window, grouping_distance_bars)
        if counts.get(eid, 0) >= maximum_per_episode:
            continue
        counts[eid] = counts.get(eid, 0) + 1
        kept.append((window, score))
    return kept


def episode_concentration(windows: list[PatternWindow], grouping_distance_bars: int = 32) -> dict[str, Any]:
    assignments = episode_assignments(windows, grouping_distance_bars)
    counts: dict[str, int] = {}
    instruments: dict[str, int] = {}
    id_to_window = {window.id: window for window in windows}
    for assignment in assignments:
        counts[assignment.episode_id] = counts.get(assignment.episode_id, 0) + 1
        instrument = id_to_window[assignment.candidate_id].instrument_id
        instruments[instrument] = instruments.get(instrument, 0) + 1
    total = max(1, len(windows))
    top_counts = sorted(counts.values(), reverse=True)
    flags = []
    if top_counts and top_counts[0] / total > 0.5:
        flags.append("SINGLE_EPISODE_DOMINANCE")
    if len(counts) < max(2, len(windows) // 5):
        flags.append("LOW_EPISODE_DIVERSITY")
    if len(instruments) <= 1 and len(windows) > 1:
        flags.append("LOW_INSTRUMENT_DIVERSITY")
    return {
        "raw_neighbour_count": len(windows),
        "unique_episode_count": len(counts),
        "largest_episode_share": top_counts[0] / total if top_counts else 0.0,
        "top_three_episode_share": sum(top_counts[:3]) / total,
        "instrument_concentration": instruments,
        "episode_adjusted_effective_sample_size": 0.0 if not top_counts else float(total**2 / sum(count * count for count in top_counts)),
        "quality_flags": flags or ["NONE"],
    }


def context_compatibility(query: MarketContext | None, candidate: MarketContext | None) -> dict[str, Any]:
    if query is None or candidate is None:
        return {"classification": "missing_context", "dimension_matches": {}, "score": 0.0}
    dimensions = ["trend_state", "volatility_state", "volatility_phase_state", "persistence_state", "shock_state", "market_phase_state", "multi_resolution_state"]
    matches = {dimension: getattr(query, dimension) == getattr(candidate, dimension) for dimension in dimensions}
    score = sum(1 for value in matches.values() if value) / len(matches)
    if score == 1.0:
        classification = "same_context"
    elif matches.get("trend_state") is False or matches.get("volatility_state") is False:
        classification = "conflicting_context"
    else:
        classification = "adjacent_context"
    return {"classification": classification, "dimension_matches": matches, "score": score}


def window_horizon_alignment(window_lengths: list[int], horizons: list[int]) -> list[dict[str, Any]]:
    rows = []
    for length in window_lengths:
        for horizon in horizons:
            ratio = horizon / max(1, length)
            rows.append({"window_length": length, "horizon_bars": horizon, "horizon_window_ratio": ratio, "ratio_bucket": min([0.125, 0.25, 0.5, 1.0, 2.0], key=lambda item: abs(item - ratio))})
    return rows


def diagnostic_decision(summary: dict[str, Any]) -> str:
    if summary.get("record_count", 0) < 20:
        return "INSUFFICIENT_SAMPLE"
    if summary.get("episode_flags"):
        return "EPISODE_CONCENTRATION_FAILURE"
    if summary.get("near_constant_rate", 0.0) > 0.25:
        return "REPRESENTATION_FAILURE"
    if summary.get("mean_availability_rate", 1.0) < 0.7:
        return "REPRESENTATION_FAILURE"
    if abs(summary.get("distance_outcome_spearman", 0.0)) < 0.05:
        return "NO_RETRIEVAL_EDGE"
    if summary.get("synthetic_recovery_rate", 0.0) > 0.8 and abs(summary.get("distance_outcome_spearman", 0.0)) < 0.1:
        return "SYNTHETIC_RECOVERY_ONLY"
    return "REFINEMENT_PROMISING"


class RetrievalDiagnosticService:
    def __init__(self, session: Session):
        self.session = session

    def run(self, configuration: dict[str, Any]) -> ExperimentRun:
        started = time.monotonic()
        cfg = self._default_configuration() | configuration
        definition = get_diagnostic_definition(cfg["diagnostic_code"])
        config_hash = canonical_hash(cfg)
        rows = self._market_dna_rows(cfg)
        if not rows:
            raise ValueError("DIAGNOSTIC_DATASET_EMPTY")
        run = ExperimentRun(
            experiment_code=definition.code,
            experiment_version=definition.version,
            name=cfg.get("name") or definition.code,
            hypothesis=cfg.get("hypothesis"),
            status=ExperimentRunStatus.running.value,
            dataset_hash=canonical_hash([row.feature_vector_hash for row in rows]),
            code_version={"diagnostic_engine": "diagnostic_v1"},
            configuration=cfg,
            configuration_hash=config_hash,
            run_nonce=cfg.get("run_nonce", "default"),
            similarity_method=cfg["similarity_methods"][0],
            baseline_methods=[],
            outcome_set_code="forward_outcomes_v1",
            outcome_set_version="outcome_v1",
            outcome_horizons=cfg["outcome_horizons"],
            validation_method="diagnostic_three_way_temporal_v1",
            validation_configuration=cfg["development_design"],
            instrument_scope=cfg.get("instrument_ids", []),
            timeframe_scope=cfg.get("timeframe_ids", []),
            window_length_scope=cfg.get("window_lengths", []),
            parameter_grid={"scaling_methods": cfg["scaling_methods"], "similarity_methods": cfg["similarity_methods"]},
            multiple_testing_family="diagnostic_family_v1",
            summary={},
            started_at=datetime.now(UTC),
        )
        self.session.add(run)
        self.session.flush()
        matrix = self._feature_matrix(rows)
        distributions = self.feature_distributions(matrix)
        snapshot = self.create_scaling_snapshot(run, matrix, cfg["scaling_methods"][0], "DESCRIPTIVE_FULL_SAMPLE")
        redundancy = redundancy_clusters(self._rows_as_dicts(matrix), matrix.feature_codes, threshold=float(cfg["redundancy_threshold"]))
        distance_outcome = self.distance_outcome_artifact(matrix, cfg)
        episodes = episode_concentration([row.pattern_window for row in rows if row.pattern_window is not None], int(cfg["episode_grouping_distance_bars"]))
        alignment = {"matrix": window_horizon_alignment(cfg.get("window_lengths") or sorted({row.pattern_window.window_length for row in rows}), cfg["outcome_horizons"])}
        summary = {
            "record_count": len(rows),
            "feature_count": len(matrix.feature_codes),
            "mean_availability_rate": float(np.mean([item.get("availability_rate", 0.0) for item in distributions["features"].values()])),
            "near_constant_rate": sum(1 for item in distributions["features"].values() if item.get("near_constant")) / max(1, len(matrix.feature_codes)),
            "redundancy_cluster_count": len(redundancy["clusters"]),
            "distance_outcome_spearman": distance_outcome["spearman"],
            "episode_flags": [flag for flag in episodes["quality_flags"] if flag != "NONE"],
        }
        run.summary = summary
        run.decision = diagnostic_decision(summary)
        run.status = ExperimentRunStatus.completed.value
        run.completed_at = datetime.now(UTC)
        run.elapsed_seconds = round(time.monotonic() - started, 6)
        self._artifact(run, "FEATURE_DISTRIBUTION", "feature_distributions", distributions)
        self._artifact(run, "CORRELATION_MATRIX", "redundancy", redundancy)
        self._artifact(run, "DISTANCE_OUTCOME_CURVE", "distance_outcome", distance_outcome)
        self._artifact(run, "EPISODE_CONCENTRATION", "episode_concentration", episodes)
        self._artifact(run, "WINDOW_HORIZON_MATRIX", "window_horizon", alignment)
        self._artifact(run, "DIAGNOSTIC_REPORT", "report", {"report": self.generate_report(run, summary, snapshot.snapshot_hash)})
        self.session.commit()
        return run

    def generate_report(self, run: ExperimentRun, summary: dict[str, Any] | None = None, snapshot_hash: str | None = None) -> str:
        summary = summary or run.summary
        return "\n".join(
            [
                f"# Retrieval Diagnostic Report: {run.name}",
                "",
                f"- Decision: `{run.decision}`",
                f"- Experiment: `{run.experiment_code}`",
                f"- Records: {summary.get('record_count', 0)}",
                f"- Mean availability: {summary.get('mean_availability_rate')}",
                f"- Near-constant rate: {summary.get('near_constant_rate')}",
                f"- Redundancy clusters: {summary.get('redundancy_cluster_count')}",
                f"- Distance/outcome Spearman: {summary.get('distance_outcome_spearman')}",
                f"- Scaling snapshot: `{snapshot_hash or 'persisted'}`",
                "",
                "No trading decision is implied by this diagnostic report.",
            ]
        )

    def artifacts(self, run_id: str, artifact_type: str | None = None, limit: int = 100) -> list[DiagnosticArtifact]:
        query = select(DiagnosticArtifact).where(DiagnosticArtifact.experiment_run_id == run_id).order_by(DiagnosticArtifact.created_at)
        if artifact_type:
            query = query.where(DiagnosticArtifact.artifact_type == artifact_type)
        return list(self.session.scalars(query.limit(limit)))

    def feature_distributions(self, matrix: FeatureMatrix) -> dict[str, Any]:
        features = {
            feature: feature_distribution(
                [None if not matrix.available[row_idx, col_idx] else float(matrix.values[row_idx, col_idx]) for row_idx in range(len(matrix.ids))],
                total_count=len(matrix.ids),
            )
            for col_idx, feature in enumerate(matrix.feature_codes)
        }
        return {"schema_version": "feature_distribution_v1", "record_count": len(matrix.ids), "features": features}

    def create_scaling_snapshot(self, run: ExperimentRun, matrix: FeatureMatrix, method: str, historical_mode: str) -> FeatureScalingSnapshot:
        get_scaling_method(method)
        values = {
            feature: [None if not matrix.available[row_idx, col_idx] else float(matrix.values[row_idx, col_idx]) for row_idx in range(len(matrix.ids))]
            for col_idx, feature in enumerate(matrix.feature_codes)
        }
        stats = scaling_statistics(values)
        availability = {feature: {"availability_rate": stats[feature].get("availability_rate", 0.0)} for feature in matrix.feature_codes}
        configuration = {"method": method, "mad_consistency": MAD_CONSISTENCY}
        snap_hash = canonical_hash({"ids": matrix.ids, "stats": stats, "availability": availability, "configuration": configuration, "historical_mode": historical_mode})
        snapshot = FeatureScalingSnapshot(
            experiment_run_id=run.id,
            scope={"window_ids": matrix.window_ids},
            feature_set_code="market_dna_v1",
            feature_set_version="market_dna_v1",
            historical_mode=historical_mode,
            record_count=len(matrix.ids),
            feature_statistics=stats,
            feature_availability=availability,
            configuration=configuration,
            configuration_hash=canonical_hash(configuration),
            snapshot_hash=snap_hash,
        )
        self.session.add(snapshot)
        self.session.flush()
        return snapshot

    def distance_outcome_artifact(self, matrix: FeatureMatrix, cfg: dict[str, Any]) -> dict[str, Any]:
        limit = int(cfg.get("maximum_pairs", 1000))
        outcomes = self._outcome_map(cfg["outcome_horizons"][0])
        groups = matrix.groups
        rows = self._rows_as_dicts(matrix)
        scored = []
        for i, query in enumerate(rows):
            q_out = outcomes.get(matrix.window_ids[i])
            if q_out is None or q_out.future_simple_return is None:
                continue
            for j in range(i):
                c_out = outcomes.get(matrix.window_ids[j])
                if c_out is None or c_out.future_simple_return is None:
                    continue
                distance = availability_aware_distance(query, rows[j], groups, policy=cfg["availability_policy"], minimum_joint_feature_ratio=float(cfg["minimum_joint_feature_ratio"]))
                if distance.rejected:
                    continue
                scored.append(
                    {
                        "candidate_id": matrix.window_ids[j],
                        "distance": distance.distance,
                        "similarity_score": distance.similarity_score,
                        "outcome_discrepancy": abs(float(q_out.future_simple_return) - float(c_out.future_simple_return)),
                    }
                )
                if len(scored) >= limit:
                    return distance_outcome_monotonicity(scored)
        return distance_outcome_monotonicity(scored)

    def _market_dna_rows(self, cfg: dict[str, Any]) -> list[MarketDNA]:
        query = select(MarketDNA).options(selectinload(MarketDNA.pattern_window)).order_by(MarketDNA.created_at, MarketDNA.id)
        rows = list(self.session.scalars(query))
        rows = [row for row in rows if row.pattern_window is not None]
        if cfg.get("instrument_ids"):
            rows = [row for row in rows if row.pattern_window.instrument_id in cfg["instrument_ids"]]
        if cfg.get("timeframe_ids"):
            rows = [row for row in rows if row.pattern_window.timeframe_id in cfg["timeframe_ids"]]
        if cfg.get("window_lengths"):
            rows = [row for row in rows if row.pattern_window.window_length in cfg["window_lengths"]]
        maximum_records = int(cfg.get("maximum_records", 500))
        if len(rows) > maximum_records:
            rng = random.Random(int(cfg.get("seed", 1729)))
            rows = sorted(rng.sample(rows, maximum_records), key=lambda item: (item.pattern_window.end_timestamp, item.id))
        return rows

    def _feature_matrix(self, rows: list[MarketDNA]) -> FeatureMatrix:
        values = np.full((len(rows), len(MARKET_DNA_V1_FEATURES)), np.nan, dtype=np.float64)
        available = np.zeros((len(rows), len(MARKET_DNA_V1_FEATURES)), dtype=bool)
        for row_idx, row in enumerate(rows):
            for col_idx, feature in enumerate(MARKET_DNA_V1_FEATURES):
                value = row.feature_values.get(feature)
                if value is not None and math.isfinite(float(value)):
                    values[row_idx, col_idx] = float(value)
                    available[row_idx, col_idx] = True
        return FeatureMatrix(
            ids=[row.id for row in rows],
            window_ids=[row.pattern_window_id for row in rows],
            feature_codes=list(MARKET_DNA_V1_FEATURES),
            groups={feature: FEATURE_DEFINITIONS[feature].feature_group for feature in MARKET_DNA_V1_FEATURES},
            values=values,
            available=available,
        )

    def _rows_as_dicts(self, matrix: FeatureMatrix) -> list[dict[str, float | None]]:
        rows = []
        for row_idx in range(len(matrix.ids)):
            rows.append({feature: None if not matrix.available[row_idx, col_idx] else float(matrix.values[row_idx, col_idx]) for col_idx, feature in enumerate(matrix.feature_codes)})
        return rows

    def _outcome_map(self, horizon: int) -> dict[str, OutcomeObservation]:
        rows = self.session.scalars(
            select(OutcomeObservation).where(
                OutcomeObservation.horizon_bars == horizon,
                OutcomeObservation.is_complete.is_(True),
            )
        )
        return {row.pattern_window_id: row for row in rows}

    def _artifact(self, run: ExperimentRun, artifact_type: str, diagnostic_code: str, payload: dict[str, Any]) -> DiagnosticArtifact:
        artifact_hash = canonical_hash({"run": run.id, "type": artifact_type, "diagnostic": diagnostic_code, "payload": payload})
        artifact = DiagnosticArtifact(
            experiment_run_id=run.id,
            diagnostic_code=diagnostic_code,
            artifact_type=artifact_type,
            schema_version="diagnostic_artifact_v1",
            configuration_hash=run.configuration_hash,
            payload=payload,
            artifact_hash=artifact_hash,
        )
        self.session.add(artifact)
        return artifact

    def _default_configuration(self) -> dict[str, Any]:
        return {
            "diagnostic_code": "representation_quality_diagnostic_v1",
            "name": "retrieval diagnostic",
            "development_design": {"development_fraction": 0.6, "validation_fraction": 0.2, "final_test_fraction": 0.2, "final_test_locked": True},
            "window_lengths": [],
            "outcome_horizons": [1],
            "scaling_methods": ["robust_median_mad_v1"],
            "similarity_methods": ["dna_robust_cosine_v1"],
            "availability_policy": "joint_available_with_coverage_penalty_v1",
            "minimum_joint_feature_ratio": 0.7,
            "redundancy_threshold": 0.95,
            "episode_grouping_distance_bars": 32,
            "maximum_records": 500,
            "maximum_pairs": 1000,
            "seed": 1729,
            "run_nonce": "default",
        }
