from __future__ import annotations

import json
import math
import random
import subprocess
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from subprocess import SubprocessError, TimeoutExpired
from typing import Any

import numpy as np
from market_genome_domain.models import (
    ExperimentArtifact,
    ExperimentFold,
    ExperimentMetric,
    ExperimentRun,
    ExperimentRunStatus,
    MarketContext,
    OutcomeObservation,
    PatternWindow,
    QueryEvaluation,
)
from market_genome_shared.hashing import sha256_canonical
from market_genome_similarity.definitions import get_similarity_method
from market_genome_similarity.service import (
    SimilaritySearchService,
    compute_similarity,
)
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from market_genome_validation.definitions import (
    METRICS,
    get_baseline_method,
    get_experiment_definition,
    get_validation_method,
)


@dataclass(frozen=True)
class FoldDefinition:
    fold_number: int
    index_start: datetime | None
    index_end: datetime | None
    validation_start: datetime | None
    validation_end: datetime | None
    test_start: datetime
    test_end: datetime
    purge_start: datetime | None
    purge_end: datetime | None
    embargo_bars: int
    configuration: dict[str, Any]
    fold_hash: str


@dataclass(frozen=True)
class EligibilityResult:
    eligible: bool
    reason: str = "ELIGIBLE"


@dataclass
class ExperimentRunResult:
    run: ExperimentRun
    folds: int = 0
    query_evaluations: int = 0
    metric_records: int = 0
    artifact_records: int = 0
    elapsed_seconds: float | None = None
    decision: str = "INSUFFICIENT_DATA"
    errors: list[str] = field(default_factory=list)


def configuration_hash(configuration: dict[str, Any]) -> str:
    return sha256_canonical(configuration)


def dataset_hash(payload: dict[str, Any]) -> str:
    return sha256_canonical(payload)


def fold_hash(payload: dict[str, Any]) -> str:
    return sha256_canonical(payload)


def evaluation_hash(payload: dict[str, Any]) -> str:
    return sha256_canonical(payload)


def metric_hash(payload: dict[str, Any]) -> str:
    return sha256_canonical(payload)


def deterministic_seed(*parts: Any) -> int:
    return int(sha256_canonical(list(parts))[:16], 16)


def source_endpoint_return(window: PatternWindow) -> float:
    return 0.0 if window.start_timestamp == window.end_timestamp else 1.0


def intervals_overlap(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    return a_start <= b_end and b_start <= a_end


def outcome_interval(window: PatternWindow, horizon_bars: int) -> tuple[datetime, datetime]:
    # Without a calendar/session model, bar-count horizons are represented by source interval length multiples.
    span = max(window.end_timestamp - window.start_timestamp, window.end_timestamp - window.end_timestamp)
    step = span / max(1, window.window_length - 1) if window.window_length > 1 else span
    return window.end_timestamp, window.end_timestamp + step * horizon_bars


def check_candidate_eligibility(
    query: PatternWindow,
    candidate: PatternWindow,
    horizon_bars: int,
    *,
    minimum_temporal_distance_bars: int = 0,
    embargo_bars: int = 0,
    purge_source_overlap: bool = True,
    purge_outcome_overlap: bool = True,
    allow_same_instrument: bool = True,
    allow_cross_asset: bool = True,
) -> EligibilityResult:
    if candidate.id == query.id:
        return EligibilityResult(False, "SAME_QUERY")
    if candidate.end_timestamp >= query.end_timestamp:
        return EligibilityResult(False, "FUTURE_OR_CONTEMPORARY")
    if not allow_cross_asset and candidate.instrument_id != query.instrument_id:
        return EligibilityResult(False, "CROSS_ASSET_EXCLUDED")
    if not allow_same_instrument and candidate.instrument_id == query.instrument_id:
        return EligibilityResult(False, "SAME_INSTRUMENT_EXCLUDED")
    min_gap = minimum_temporal_distance_bars + embargo_bars
    if min_gap > 0:
        # Approximate bars by requiring at least min_gap non-overlapping source intervals.
        source_span = max(query.end_timestamp - query.start_timestamp, candidate.end_timestamp - candidate.start_timestamp)
        bar_step = source_span / max(1, max(query.window_length, candidate.window_length) - 1)
        if candidate.end_timestamp > query.end_timestamp - bar_step * min_gap:
            return EligibilityResult(False, "EMBARGO_OR_TEMPORAL_DISTANCE")
    if purge_source_overlap and intervals_overlap(candidate.start_timestamp, candidate.end_timestamp, query.start_timestamp, query.end_timestamp):
        return EligibilityResult(False, "SOURCE_OVERLAP")
    if purge_outcome_overlap:
        q_out_start, q_out_end = outcome_interval(query, horizon_bars)
        c_out_start, c_out_end = outcome_interval(candidate, horizon_bars)
        if intervals_overlap(candidate.start_timestamp, candidate.end_timestamp, q_out_start, q_out_end):
            return EligibilityResult(False, "CANDIDATE_SOURCE_OVERLAPS_QUERY_OUTCOME")
        if intervals_overlap(c_out_start, c_out_end, query.start_timestamp, query.end_timestamp):
            return EligibilityResult(False, "CANDIDATE_OUTCOME_OVERLAPS_QUERY_SOURCE")
        if intervals_overlap(c_out_start, c_out_end, q_out_start, q_out_end):
            return EligibilityResult(False, "OUTCOME_OVERLAP")
    return EligibilityResult(True)


def generate_folds(windows: list[PatternWindow], method: str, configuration: dict[str, Any] | None = None) -> list[FoldDefinition]:
    cfg = {
        "fold_count": 3,
        "minimum_index_windows": 5,
        "test_window_count": 3,
        "rolling_index_window_count": 10,
        "embargo_bars": 0,
    } | (configuration or {})
    get_validation_method(method)
    ordered = sorted(windows, key=lambda item: (item.end_timestamp, item.id))
    if len(ordered) < int(cfg["minimum_index_windows"]) + 1:
        raise ValueError("EXPERIMENT_NO_ELIGIBLE_QUERIES")
    folds: list[FoldDefinition] = []
    if method == "anchored_holdout_v1":
        split = max(int(cfg["minimum_index_windows"]), int(len(ordered) * 0.7))
        starts = [split]
    elif method == "purged_kfold_v1":
        test_size = max(1, len(ordered) // int(cfg["fold_count"]))
        starts = [i * test_size for i in range(1, int(cfg["fold_count"]))]
    else:
        test_size = int(cfg["test_window_count"])
        start = int(cfg["minimum_index_windows"])
        starts = [start + i * test_size for i in range(int(cfg["fold_count"])) if start + i * test_size < len(ordered)]
    for number, start_index in enumerate(starts, start=1):
        test = ordered[start_index : start_index + int(cfg["test_window_count"])]
        if not test:
            continue
        if method == "rolling_walk_forward_v1":
            index = ordered[max(0, start_index - int(cfg["rolling_index_window_count"])) : start_index]
        elif method == "purged_kfold_v1":
            index = ordered[:start_index] + ordered[start_index + len(test) :]
        else:
            index = ordered[:start_index]
        if not index:
            continue
        payload = {
            "method": method,
            "fold_number": number,
            "index_start": index[0].end_timestamp,
            "index_end": index[-1].end_timestamp,
            "test_start": test[0].end_timestamp,
            "test_end": test[-1].end_timestamp,
            "configuration": cfg,
        }
        folds.append(
            FoldDefinition(
                fold_number=number,
                index_start=index[0].end_timestamp,
                index_end=index[-1].end_timestamp,
                validation_start=None,
                validation_end=None,
                test_start=test[0].end_timestamp,
                test_end=test[-1].end_timestamp,
                purge_start=test[0].start_timestamp,
                purge_end=test[-1].end_timestamp,
                embargo_bars=int(cfg["embargo_bars"]),
                configuration=cfg,
                fold_hash=fold_hash(payload),
            )
        )
    if not folds:
        raise ValueError("EXPERIMENT_NO_ELIGIBLE_QUERIES")
    return folds


def weights_for(method: str, distances: list[float], similarities: list[float] | None = None, temperature: float = 1.0) -> list[float]:
    if not distances:
        return []
    if method == "uniform_v1":
        raw = [1.0 for _ in distances]
    elif method == "inverse_distance_v1":
        raw = [1.0 / (max(0.0, d) + 1e-9) for d in distances]
    elif method == "softmax_similarity_v1":
        sims = np.asarray(similarities or [1.0 / (1.0 + d) for d in distances], dtype=np.float64) / max(temperature, 1e-9)
        sims = sims - np.max(sims)
        raw = list(np.exp(sims))
    elif method == "rank_decay_v1":
        raw = [1.0 / rank for rank in range(1, len(distances) + 1)]
    else:
        raise ValueError("EXPERIMENT_WEIGHTING_METHOD_NOT_FOUND")
    total = float(sum(raw))
    return [float(value / total) for value in raw]


def effective_sample_size(weights: list[float]) -> float:
    if not weights:
        return 0.0
    denominator = sum(w * w for w in weights)
    if denominator <= 0:
        return 0.0
    return min(float(len(weights)), max(1.0, float(sum(weights) ** 2 / denominator)))


def aggregate_outcomes(outcomes: list[OutcomeObservation], weights: list[float] | None = None, complete_only: bool = True) -> dict[str, Any]:
    rows = [row for row in outcomes if (row.is_complete or not complete_only) and row.future_simple_return is not None]
    if not rows:
        return {"effective_sample_size": 0.0, "complete_outcome_count": 0, "partial_outcome_count": 0, "scenario_probabilities": {}}
    weights = weights or weights_for("uniform_v1", [0.0] * len(rows))
    weights = weights[: len(rows)]
    returns = np.asarray([float(row.future_simple_return) for row in rows], dtype=np.float64)
    mfe = np.asarray([float(row.maximum_favourable_excursion or 0.0) for row in rows], dtype=np.float64)
    mae = np.asarray([float(row.maximum_adverse_excursion or 0.0) for row in rows], dtype=np.float64)
    w = np.asarray(weights, dtype=np.float64)
    w = w / np.sum(w)
    pos = float(np.sum(w[returns > 0]))
    neg = float(np.sum(w[returns < 0]))
    flat = max(0.0, 1.0 - pos - neg)
    scenario = {
        "positive": pos,
        "negative": neg,
        "flat": flat,
        "continuation": float(np.sum([w[i] for i, row in enumerate(rows) if row.continuation_reversal_class == "CONTINUATION"])),
        "reversal": float(np.sum([w[i] for i, row in enumerate(rows) if row.continuation_reversal_class == "REVERSAL"])),
        "sideways": float(np.sum([w[i] for i, row in enumerate(rows) if row.continuation_reversal_class == "SIDEWAYS"])),
    }
    return {
        "effective_sample_size": effective_sample_size(list(w)),
        "complete_outcome_count": sum(1 for row in outcomes if row.is_complete),
        "partial_outcome_count": sum(1 for row in outcomes if not row.is_complete),
        "positive_frequency": pos,
        "negative_frequency": neg,
        "flat_frequency": flat,
        "mean_future_return": float(np.sum(w * returns)),
        "median_future_return": float(np.median(returns)),
        "std_future_return": float(np.std(returns, ddof=1)) if len(returns) > 1 else 0.0,
        "return_quantiles": {"0.1": float(np.quantile(returns, 0.1)), "0.5": float(np.quantile(returns, 0.5)), "0.9": float(np.quantile(returns, 0.9))},
        "trimmed_mean": float(np.mean(np.sort(returns)[max(0, len(returns) // 10) : max(1, len(returns) - len(returns) // 10)])),
        "median_absolute_deviation": float(np.median(np.abs(returns - np.median(returns)))),
        "mean_mfe": float(np.sum(w * mfe)),
        "median_mfe": float(np.median(mfe)),
        "mean_mae": float(np.sum(w * mae)),
        "median_mae": float(np.median(mae)),
        "scenario_probabilities": scenario,
    }


def brier_score(probability: float, actual_positive: bool) -> float:
    p = min(1.0, max(0.0, probability))
    return float((p - (1.0 if actual_positive else 0.0)) ** 2)


def log_loss(probability: float, actual_positive: bool) -> float:
    p = min(1.0 - 1e-12, max(1e-12, probability))
    return float(-(math.log(p) if actual_positive else math.log(1.0 - p)))


def pinball_loss(actual: float, prediction: float, quantile: float) -> float:
    error = actual - prediction
    return float(max(quantile * error, (quantile - 1.0) * error))


def classification_metrics(actual: list[bool], predicted: list[bool]) -> dict[str, float]:
    tp = sum(1 for a, p in zip(actual, predicted, strict=False) if a and p)
    tn = sum(1 for a, p in zip(actual, predicted, strict=False) if not a and not p)
    fp = sum(1 for a, p in zip(actual, predicted, strict=False) if not a and p)
    fn = sum(1 for a, p in zip(actual, predicted, strict=False) if a and not p)
    n = max(1, len(actual))
    tpr = tp / max(1, tp + fn)
    tnr = tn / max(1, tn + fp)
    denom = math.sqrt(max(1, (tp + fp) * (tp + fn) * (tn + fp) * (tn + fn)))
    return {"accuracy": (tp + tn) / n, "balanced_accuracy": (tpr + tnr) / 2.0, "matthews_correlation": (tp * tn - fp * fn) / denom}


def calibration_metrics(probabilities: list[float], actual: list[bool], bins: int = 10) -> dict[str, Any]:
    if not probabilities:
        return {"ece": 0.0, "mce": 0.0, "bins": [], "quality_flags": ["LOW_SAMPLE"]}
    entries = []
    ece = 0.0
    mce = 0.0
    for idx in range(bins):
        low, high = idx / bins, (idx + 1) / bins
        members = [i for i, p in enumerate(probabilities) if low <= p < high or (idx == bins - 1 and p == 1.0)]
        if not members:
            entries.append({"bin": idx, "count": 0})
            continue
        conf = sum(probabilities[i] for i in members) / len(members)
        freq = sum(1 for i in members if actual[i]) / len(members)
        gap = abs(conf - freq)
        ece += len(members) / len(probabilities) * gap
        mce = max(mce, gap)
        entries.append({"bin": idx, "count": len(members), "confidence": conf, "frequency": freq, "gap": gap})
    return {"ece": float(ece), "mce": float(mce), "bins": entries, "quality_flags": ["LOW_SAMPLE"] if len(probabilities) < bins else ["NONE"]}


def bootstrap_ci(values: list[float], seed: int = 1, repetitions: int = 200, alpha: float = 0.05) -> dict[str, float | None]:
    if not values:
        return {"low": None, "high": None, "standard_error": None}
    rng = random.Random(seed)
    samples = [sum(rng.choice(values) for _ in values) / len(values) for _ in range(repetitions)]
    samples.sort()
    low_idx = int((alpha / 2) * (repetitions - 1))
    high_idx = int((1 - alpha / 2) * (repetitions - 1))
    return {"low": samples[low_idx], "high": samples[high_idx], "standard_error": float(np.std(samples, ddof=1)) if len(samples) > 1 else 0.0}


def benjamini_hochberg(p_values: list[float]) -> list[float]:
    n = len(p_values)
    ordered = sorted(enumerate(p_values), key=lambda item: item[1], reverse=True)
    adjusted = [0.0] * n
    running = 1.0
    for rank_from_end, (idx, value) in enumerate(ordered, start=1):
        rank = n - rank_from_end + 1
        running = min(running, value * n / max(1, rank))
        adjusted[idx] = min(1.0, max(value, running))
    return adjusted


def holm(p_values: list[float]) -> list[float]:
    ordered = sorted(enumerate(p_values), key=lambda item: item[1])
    adjusted = [0.0] * len(p_values)
    running = 0.0
    n = len(p_values)
    for rank, (idx, value) in enumerate(ordered, start=1):
        running = max(running, min(1.0, (n - rank + 1) * value))
        adjusted[idx] = max(value, running)
    return adjusted


def experiment_decision(metrics: dict[str, float], sample_count: int) -> str:
    if sample_count < 10:
        return "INSUFFICIENT_DATA"
    skill = metrics.get("brier_skill_score", 0.0)
    accuracy = metrics.get("direction_accuracy", 0.0)
    ci_low = metrics.get("skill_ci_low", -1.0)
    if skill <= 0 or accuracy <= 0.5:
        return "NO_SUPPORTED_EDGE"
    if ci_low <= 0:
        return "PROMISING"
    if sample_count >= 50:
        return "OUT_OF_SAMPLE_SUPPORTED"
    return "PROMISING"


class ValidationExperimentService:
    def __init__(self, session: Session):
        self.session = session
        self.similarity = SimilaritySearchService(session)

    def run(self, configuration: dict[str, Any]) -> ExperimentRunResult:
        started = time.monotonic()
        cfg = self._default_configuration() | configuration
        get_experiment_definition(cfg["experiment_code"])
        get_validation_method(cfg["validation_method"])
        for baseline in cfg["baseline_methods"]:
            get_baseline_method(baseline)
        windows = self._windows(cfg)
        if not windows:
            raise ValueError("EXPERIMENT_NO_ELIGIBLE_QUERIES")
        ds_hash = self._dataset_hash(windows, cfg)
        cfg_hash = configuration_hash(cfg)
        run = ExperimentRun(
            experiment_code=cfg["experiment_code"],
            experiment_version="experiment_v1",
            name=cfg.get("name") or cfg["experiment_code"],
            hypothesis=cfg.get("hypothesis"),
            status=ExperimentRunStatus.running.value,
            dataset_hash=ds_hash,
            code_version=self._code_version(),
            configuration=cfg,
            configuration_hash=cfg_hash,
            run_nonce=cfg.get("run_nonce", "default"),
            similarity_method=cfg["similarity_method"],
            baseline_methods=cfg["baseline_methods"],
            outcome_set_code=cfg["outcome_set_code"],
            outcome_set_version=cfg["outcome_set_version"],
            outcome_horizons=cfg["outcome_horizons"],
            validation_method=cfg["validation_method"],
            validation_configuration=cfg["validation"],
            instrument_scope=cfg.get("instrument_ids") or [],
            timeframe_scope=cfg.get("timeframe_ids") or [],
            window_length_scope=cfg.get("window_lengths") or [],
            parameter_grid=cfg.get("parameter_grid", {}),
            multiple_testing_family=cfg.get("multiple_testing_family"),
            started_at=datetime.now(UTC),
        )
        self.session.add(run)
        self.session.flush()
        result = ExperimentRunResult(run=run)
        try:
            fold_defs = generate_folds(windows, cfg["validation_method"], cfg["validation"])
            for fold_def in fold_defs:
                fold = ExperimentFold(
                    experiment_run_id=run.id,
                    fold_number=fold_def.fold_number,
                    index_start=fold_def.index_start,
                    index_end=fold_def.index_end,
                    validation_start=fold_def.validation_start,
                    validation_end=fold_def.validation_end,
                    test_start=fold_def.test_start,
                    test_end=fold_def.test_end,
                    purge_start=fold_def.purge_start,
                    purge_end=fold_def.purge_end,
                    embargo_bars=fold_def.embargo_bars,
                    configuration=fold_def.configuration,
                    fold_hash=fold_def.fold_hash,
                    status=ExperimentRunStatus.running.value,
                    started_at=datetime.now(UTC),
                )
                self.session.add(fold)
                self.session.flush()
                queries = [w for w in windows if fold.test_start <= w.end_timestamp <= fold.test_end]
                fold.eligible_query_count = len(queries)
                for query_window in queries:
                    for horizon in cfg["outcome_horizons"]:
                        actual = self._outcome(query_window.id, horizon, complete_only=True)
                        if actual is None:
                            continue
                        candidates, counts = self._eligible_candidates(windows, query_window, horizon, cfg)
                        fold.eligible_index_count += len(candidates)
                        fold.excluded_future_count += counts["future"]
                        fold.excluded_overlap_count += counts["overlap"]
                        fold.excluded_quality_count += counts["quality"]
                        evals = self._evaluate_query(run, fold, query_window, actual, candidates, horizon, cfg)
                        result.query_evaluations += len(evals)
                fold.status = ExperimentRunStatus.completed.value
                fold.completed_at = datetime.now(UTC)
                result.folds += 1
            result.metric_records = self._persist_metrics(run, cfg)
            report = self.generate_report(run.id)
            artifact = ExperimentArtifact(
                experiment_run_id=run.id,
                artifact_type="markdown_report",
                name=f"{run.name} report",
                content=report,
                artifact_metadata={"format": "markdown"},
                artifact_hash=sha256_canonical(report),
            )
            self.session.add(artifact)
            result.artifact_records = 1
            result.elapsed_seconds = round(time.monotonic() - started, 3)
            run.summary = {"folds": result.folds, "query_evaluations": result.query_evaluations, "metric_records": result.metric_records}
            run.decision = self._decision_for_run(run.id)
            run.status = ExperimentRunStatus.completed.value if result.query_evaluations else ExperimentRunStatus.completed_with_warnings.value
            run.completed_at = datetime.now(UTC)
            run.elapsed_seconds = result.elapsed_seconds
            result.decision = run.decision or "INSUFFICIENT_DATA"
            self.session.commit()
            self.session.refresh(run)
            return result
        except Exception as exc:
            run.status = ExperimentRunStatus.failed.value
            run.error_message = str(exc)
            run.completed_at = datetime.now(UTC)
            run.elapsed_seconds = round(time.monotonic() - started, 3)
            self.session.commit()
            raise

    def generate_report(self, run_id: str) -> str:
        run = self.session.get(ExperimentRun, run_id)
        if run is None:
            raise ValueError("EXPERIMENT_NOT_FOUND")
        metrics = list(self.session.scalars(select(ExperimentMetric).where(ExperimentMetric.experiment_run_id == run_id).order_by(ExperimentMetric.metric_code)))
        lines = [
            f"# Experiment Report: {run.name}",
            "",
            f"- Decision: `{run.decision or 'PENDING'}`",
            f"- Experiment: `{run.experiment_code}`",
            f"- Validation: `{run.validation_method}`",
            f"- Dataset hash: `{run.dataset_hash}`",
            f"- Configuration hash: `{run.configuration_hash}`",
            "",
            "## Metrics",
            "",
        ]
        for metric in metrics:
            method = metric.similarity_method or metric.baseline_method or "all"
            lines.append(f"- `{metric.metric_code}` `{method}` h={metric.horizon_bars}: {metric.value} n={metric.sample_count}")
        return "\n".join(lines)

    def _default_configuration(self) -> dict[str, Any]:
        return {
            "experiment_code": "walk_forward_analogue_validation_v1",
            "name": "Walk-forward analogue validation",
            "similarity_method": "market_analogue_v1",
            "baseline_methods": ["random_history_v1", "same_context_random_v1", "unconditional_outcome_v1", "naive_continuation_v1", "naive_mean_reversion_v1"],
            "outcome_set_code": "forward_outcomes_v1",
            "outcome_set_version": "forward_outcomes_v1",
            "outcome_horizons": [1, 3],
            "validation_method": "expanding_walk_forward_v1",
            "validation": {"fold_count": 2, "minimum_index_windows": 8, "test_window_count": 3, "embargo_bars": 0},
            "neighbour_counts": [5],
            "weighting_method": "uniform_v1",
            "random_seed": 1729,
            "random_repetitions": 1,
            "complete_outcomes_only": True,
            "purge_source_overlap": True,
            "purge_outcome_overlap": True,
            "minimum_temporal_distance_bars": 0,
            "run_nonce": "default",
        }

    def _windows(self, cfg: dict[str, Any]) -> list[PatternWindow]:
        query = select(PatternWindow).order_by(PatternWindow.end_timestamp, PatternWindow.id)
        if cfg.get("instrument_ids"):
            query = query.where(PatternWindow.instrument_id.in_(cfg["instrument_ids"]))
        if cfg.get("timeframe_ids"):
            query = query.where(PatternWindow.timeframe_id.in_(cfg["timeframe_ids"]))
        if cfg.get("window_lengths"):
            query = query.where(PatternWindow.window_length.in_(cfg["window_lengths"]))
        return list(self.session.scalars(query))

    def _dataset_hash(self, windows: list[PatternWindow], cfg: dict[str, Any]) -> str:
        return dataset_hash(
            {
                "window_ids": [w.id for w in windows],
                "window_hashes": [w.source_data_hash for w in windows],
                "outcome_set": [cfg["outcome_set_code"], cfg["outcome_set_version"], cfg["outcome_horizons"]],
                "similarity_method": cfg["similarity_method"],
                "quality_filters": {"complete_outcomes_only": cfg["complete_outcomes_only"]},
            }
        )

    def _code_version(self) -> dict[str, Any]:
        try:
            commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=Path.cwd(), capture_output=True, text=True, timeout=5, check=False)
            dirty = subprocess.run(["git", "status", "--porcelain"], cwd=Path.cwd(), capture_output=True, text=True, timeout=5, check=False)
            diff = subprocess.run(["git", "diff", "--", "."], cwd=Path.cwd(), capture_output=True, text=True, timeout=10, check=False)
            return {
                "commit_hash": commit.stdout.strip() if commit.returncode == 0 else None,
                "working_tree_dirty": bool(dirty.stdout.strip()),
                "working_tree_diff_hash": sha256_canonical(diff.stdout) if diff.returncode == 0 else None,
            }
        except (OSError, SubprocessError, TimeoutExpired):
            return {"commit_hash": None, "working_tree_dirty": True, "working_tree_diff_hash": None}

    def _eligible_candidates(self, windows: list[PatternWindow], query_window: PatternWindow, horizon: int, cfg: dict[str, Any]) -> tuple[list[PatternWindow], dict[str, int]]:
        eligible: list[PatternWindow] = []
        counts = {"future": 0, "overlap": 0, "quality": 0}
        for candidate in windows:
            result = check_candidate_eligibility(
                query_window,
                candidate,
                horizon,
                minimum_temporal_distance_bars=cfg["minimum_temporal_distance_bars"],
                embargo_bars=cfg["validation"].get("embargo_bars", 0),
                purge_source_overlap=cfg["purge_source_overlap"],
                purge_outcome_overlap=cfg["purge_outcome_overlap"],
            )
            if result.eligible:
                if self._outcome(candidate.id, horizon, complete_only=cfg["complete_outcomes_only"]) is not None:
                    eligible.append(candidate)
                else:
                    counts["quality"] += 1
            elif result.reason == "FUTURE_OR_CONTEMPORARY":
                counts["future"] += 1
            elif "OVERLAP" in result.reason or "EMBARGO" in result.reason:
                counts["overlap"] += 1
        return eligible, counts

    def _evaluate_query(self, run: ExperimentRun, fold: ExperimentFold, query_window: PatternWindow, actual: OutcomeObservation, candidates: list[PatternWindow], horizon: int, cfg: dict[str, Any]) -> list[QueryEvaluation]:
        evaluations = []
        for neighbour_count in cfg["neighbour_counts"]:
            ranked = self._rank_similarity(query_window, candidates, cfg["similarity_method"], neighbour_count)
            evaluations.append(self._persist_evaluation(run, fold, query_window, actual, ranked, horizon, cfg, cfg["similarity_method"], None))
            for baseline in cfg["baseline_methods"]:
                baseline_ranked = self._baseline(query_window, candidates, baseline, neighbour_count, horizon, cfg)
                evaluations.append(self._persist_evaluation(run, fold, query_window, actual, baseline_ranked, horizon, cfg, None, baseline))
        return evaluations

    def _rank_similarity(self, query_window: PatternWindow, candidates: list[PatternWindow], method_code: str, limit: int) -> list[tuple[PatternWindow, float, float]]:
        method = get_similarity_method(method_code)
        query_input = self.similarity._input_for_window(query_window.id, method)
        scored = []
        for candidate in candidates:
            try:
                candidate_input = self.similarity._input_for_window(candidate.id, method)
                score = compute_similarity(query_input, candidate_input, method)
                scored.append((candidate, score.distance, score.similarity_score))
            except ValueError:
                continue
        return sorted(scored, key=lambda item: (item[1], item[0].end_timestamp, item[0].id))[:limit]

    def _baseline(self, query_window: PatternWindow, candidates: list[PatternWindow], baseline: str, limit: int, horizon: int, cfg: dict[str, Any]) -> list[tuple[PatternWindow, float, float]]:
        if baseline in {"raw_shape_euclidean_v1", "dna_only_cosine_v1"}:
            method = "shape_euclidean_v1" if baseline == "raw_shape_euclidean_v1" else "dna_cosine_v1"
            return self._rank_similarity(query_window, candidates, method, limit)
        filtered = candidates
        q_context = self._context(query_window.id)
        if baseline == "same_instrument_random_v1":
            filtered = [c for c in filtered if c.instrument_id == query_window.instrument_id]
        elif baseline == "same_asset_class_random_v1":
            query_asset_class = query_window.instrument.asset_class if query_window.instrument is not None else None
            filtered = [
                c
                for c in filtered
                if c.instrument is not None and c.instrument.asset_class == query_asset_class
            ]
        elif baseline in {"same_context_random_v1", "context_filter_random_v1"} and q_context is not None:
            dims = cfg.get("context_match_dimensions", ["trend_state", "volatility_state", "persistence_state", "shock_state"])
            filtered = [c for c in filtered if self._context_matches(q_context, self._context(c.id), dims)]
        elif baseline == "same_volatility_random_v1" and q_context is not None:
            filtered = [c for c in filtered if (ctx := self._context(c.id)) is not None and ctx.volatility_state == q_context.volatility_state]
        elif baseline == "recent_return_match_v1":
            filtered = sorted(filtered, key=lambda c: abs(source_endpoint_return(c) - source_endpoint_return(query_window)))
            return [(c, float(rank), 1.0 / (1.0 + rank)) for rank, c in enumerate(filtered[:limit], start=1)]
        elif baseline in {"unconditional_outcome_v1", "naive_continuation_v1", "naive_mean_reversion_v1", "recent_mean_return_v1"}:
            filtered = sorted(filtered, key=lambda c: (c.end_timestamp, c.id))
            return [(c, 1.0, 0.5) for c in filtered[:limit]]
        seed = deterministic_seed(cfg["random_seed"], query_window.id, baseline, horizon, limit)
        rng = random.Random(seed)
        pool = list(filtered)
        rng.shuffle(pool)
        return [(c, float(rank), 1.0 / (1.0 + rank)) for rank, c in enumerate(pool[:limit], start=1)]

    def _persist_evaluation(self, run: ExperimentRun, fold: ExperimentFold, query_window: PatternWindow, actual: OutcomeObservation, ranked: list[tuple[PatternWindow, float, float]], horizon: int, cfg: dict[str, Any], similarity_method: str | None, baseline_method: str | None) -> QueryEvaluation:
        outcomes = [self._outcome(window.id, horizon, complete_only=cfg["complete_outcomes_only"]) for window, _, _ in ranked]
        outcomes = [row for row in outcomes if row is not None]
        distances = [distance for _, distance, _ in ranked[: len(outcomes)]]
        similarities = [score for _, _, score in ranked[: len(outcomes)]]
        weights = weights_for(cfg["weighting_method"], distances or [1.0] * len(outcomes), similarities)
        aggregate = aggregate_outcomes(outcomes, weights, complete_only=cfg["complete_outcomes_only"])
        probability = aggregate.get("positive_frequency")
        actual_positive = float(actual.future_simple_return or 0.0) > 0
        predicted_positive = (probability or 0.0) >= 0.5
        flags = []
        if aggregate.get("effective_sample_size", 0.0) < min(3, len(outcomes)):
            flags.append("LOW_EFFECTIVE_SAMPLE_SIZE")
        payload = {
            "run": run.id,
            "fold": fold.id,
            "query": query_window.id,
            "horizon": horizon,
            "similarity_method": similarity_method,
            "baseline_method": baseline_method,
            "ranked": [w.id for w, _, _ in ranked],
            "aggregate": aggregate,
            "actual_hash": actual.outcome_hash,
        }
        ev_hash = evaluation_hash(payload)
        evaluation = QueryEvaluation(
            experiment_run_id=run.id,
            fold_id=fold.id,
            query_window_id=query_window.id,
            query_timestamp=query_window.end_timestamp,
            horizon_bars=horizon,
            similarity_method=similarity_method,
            baseline_method=baseline_method,
            neighbour_count=len(ranked),
            weighting_method=cfg["weighting_method"],
            eligible_candidate_count=len(ranked),
            retrieved_match_count=len(ranked),
            effective_match_count=aggregate.get("effective_sample_size", 0.0),
            predicted_direction_probability=probability,
            predicted_return_mean=aggregate.get("mean_future_return"),
            predicted_return_median=aggregate.get("median_future_return"),
            predicted_return_quantiles=aggregate.get("return_quantiles", {}),
            predicted_mfe_mean=aggregate.get("mean_mfe"),
            predicted_mae_mean=aggregate.get("mean_mae"),
            scenario_probabilities=aggregate.get("scenario_probabilities", {}),
            actual_direction=actual.direction_class,
            actual_return=actual.future_simple_return,
            actual_mfe=actual.maximum_favourable_excursion,
            actual_mae=actual.maximum_adverse_excursion,
            direction_correct=predicted_positive == actual_positive if probability is not None else None,
            brier_component=brier_score(probability or 0.0, actual_positive) if probability is not None else None,
            log_loss_component=log_loss(probability or 0.0, actual_positive) if probability is not None else None,
            absolute_error=abs((aggregate.get("mean_future_return") or 0.0) - float(actual.future_simple_return or 0.0)),
            squared_error=((aggregate.get("mean_future_return") or 0.0) - float(actual.future_simple_return or 0.0)) ** 2,
            quantile_losses={q: pinball_loss(float(actual.future_simple_return or 0.0), v, float(q)) for q, v in aggregate.get("return_quantiles", {}).items()},
            query_context=self._context_dict(self._context(query_window.id)),
            retrieved_context_distribution=self._context_distribution([window.id for window, _, _ in ranked]),
            retrieval_diagnostics={"historical_as_of": True, "uses_query_actual_outcome_for_forecast": False, "candidate_window_ids": [window.id for window, _, _ in ranked]},
            quality_flags=flags or ["NONE"],
            configuration_hash=run.configuration_hash,
            evaluation_hash=ev_hash,
        )
        self.session.add(evaluation)
        return evaluation

    def _persist_metrics(self, run: ExperimentRun, cfg: dict[str, Any]) -> int:
        rows = list(self.session.scalars(select(QueryEvaluation).where(QueryEvaluation.experiment_run_id == run.id)))
        count = 0
        groups: dict[tuple[int, str], list[QueryEvaluation]] = {}
        for row in rows:
            method = row.similarity_method or row.baseline_method or "unknown"
            groups.setdefault((row.horizon_bars, method), []).append(row)
        for (horizon, method), values in groups.items():
            probabilities = [float(v.predicted_direction_probability) for v in values if v.predicted_direction_probability is not None]
            actual = [float(v.actual_return or 0.0) > 0 for v in values if v.predicted_direction_probability is not None]
            predicted = [p >= 0.5 for p in probabilities]
            briers = [float(v.brier_component) for v in values if v.brier_component is not None]
            log_losses = [float(v.log_loss_component) for v in values if v.log_loss_component is not None]
            errors = [float(v.absolute_error) for v in values if v.absolute_error is not None]
            squared = [float(v.squared_error) for v in values if v.squared_error is not None]
            class_metrics = classification_metrics(actual, predicted) if actual else {"accuracy": 0.0, "balanced_accuracy": 0.0, "matthews_correlation": 0.0}
            cal = calibration_metrics(probabilities, actual)
            metric_values = {
                "direction_accuracy": class_metrics["accuracy"],
                "balanced_accuracy": class_metrics["balanced_accuracy"],
                "matthews_correlation": class_metrics["matthews_correlation"],
                "brier_score": float(np.mean(briers)) if briers else None,
                "log_loss": float(np.mean(log_losses)) if log_losses else None,
                "mae": float(np.mean(errors)) if errors else None,
                "rmse": math.sqrt(float(np.mean(squared))) if squared else None,
                "expected_calibration_error": cal["ece"],
                "maximum_calibration_error": cal["mce"],
            }
            baseline_brier = max(1e-12, float(np.mean([(0.5 - (1.0 if a else 0.0)) ** 2 for a in actual]))) if actual else None
            if baseline_brier is not None and metric_values["brier_score"] is not None:
                metric_values["brier_skill_score"] = 1.0 - float(metric_values["brier_score"]) / baseline_brier
            returns = [float(v.actual_return or 0.0) for v in values]
            metric_values["empirical_crps"] = float(np.mean([abs(r - float(v.predicted_return_mean or 0.0)) for r, v in zip(returns, values, strict=False)])) if returns else None
            pinball_samples = [sum(v.quantile_losses.values()) / len(v.quantile_losses) for v in values if v.quantile_losses]
            metric_values["pinball_loss"] = float(np.mean(pinball_samples)) if pinball_samples else None
            for code, value in metric_values.items():
                if code not in METRICS:
                    continue
                samples = [float(v.brier_component or 0.0) for v in values] if code == "brier_score" else [float(v.direction_correct is True) for v in values]
                ci = bootstrap_ci(samples, seed=deterministic_seed(run.id, horizon, method, code), repetitions=100)
                payload = {"run": run.id, "horizon": horizon, "method": method, "metric": code, "value": value, "sample_count": len(values)}
                metric = ExperimentMetric(
                    experiment_run_id=run.id,
                    fold_id=None,
                    metric_code=code,
                    metric_version="metric_v1",
                    value=value,
                    sample_count=len(values),
                    horizon_bars=horizon,
                    similarity_method=method if method == cfg["similarity_method"] else None,
                    baseline_method=method if method != cfg["similarity_method"] else None,
                    confidence_interval_low=ci["low"],
                    confidence_interval_high=ci["high"],
                    standard_error=ci["standard_error"],
                    metric_metadata={"calibration": cal if code in {"expected_calibration_error", "maximum_calibration_error"} else {}, "bootstrap_repetitions": 100},
                    metric_hash=metric_hash(payload),
                )
                self.session.add(metric)
                count += 1
        return count

    def _decision_for_run(self, run_id: str) -> str:
        metrics = {
            metric.metric_code: float(metric.value)
            for metric in self.session.scalars(select(ExperimentMetric).where(ExperimentMetric.experiment_run_id == run_id, ExperimentMetric.similarity_method.is_not(None)))
            if metric.value is not None
        }
        sample_count = self.session.scalar(select(func.count(QueryEvaluation.id)).where(QueryEvaluation.experiment_run_id == run_id)) or 0
        metrics["skill_ci_low"] = min((float(m.confidence_interval_low) for m in self.session.scalars(select(ExperimentMetric).where(ExperimentMetric.experiment_run_id == run_id, ExperimentMetric.metric_code == "brier_skill_score")) if m.confidence_interval_low is not None), default=-1.0)
        return experiment_decision(metrics, sample_count)

    def _outcome(self, window_id: str, horizon: int, complete_only: bool) -> OutcomeObservation | None:
        query = select(OutcomeObservation).where(OutcomeObservation.pattern_window_id == window_id, OutcomeObservation.horizon_bars == horizon)
        if complete_only:
            query = query.where(OutcomeObservation.is_complete.is_(True))
        return self.session.scalar(query.order_by(OutcomeObservation.created_at.desc()).limit(1))

    def _context(self, window_id: str) -> MarketContext | None:
        return self.session.scalar(select(MarketContext).where(MarketContext.pattern_window_id == window_id).order_by(MarketContext.created_at.desc()).limit(1))

    def _context_matches(self, query: MarketContext, candidate: MarketContext | None, dimensions: list[str]) -> bool:
        return candidate is not None and all(getattr(query, dim) == getattr(candidate, dim) for dim in dimensions)

    def _context_dict(self, context: MarketContext | None) -> dict[str, Any]:
        if context is None:
            return {}
        return {
            "trend_state": context.trend_state,
            "volatility_state": context.volatility_state,
            "persistence_state": context.persistence_state,
            "shock_state": context.shock_state,
            "market_phase_state": context.market_phase_state,
        }

    def _context_distribution(self, window_ids: list[str]) -> dict[str, Any]:
        counts: dict[str, int] = {}
        for window_id in window_ids:
            context = self._context(window_id)
            key = context.composite_context_code if context else "UNAVAILABLE"
            counts[key] = counts.get(key, 0) + 1
        return counts


def load_experiment_config(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))
