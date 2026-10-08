from __future__ import annotations

import math
import random
import statistics
from dataclasses import dataclass
from datetime import datetime
from typing import Any

Z_95 = 1.959963985
PROSPECTIVE_DECISIONS = (
    "PROSPECTIVE_CONTEXT_SIGNAL_SUPPORTED",
    "PROSPECTIVE_CONTEXT_SIGNAL_WEAK",
    "PROSPECTIVE_CONTEXT_SIGNAL_NOT_SUPPORTED",
    "PROSPECTIVE_EVIDENCE_ACCUMULATING",
)
FORECAST_STATUSES = ("PENDING_OUTCOME", "MATURED", "INSUFFICIENT_CONTEXT_HISTORY")
PROVENANCE_CLASSES = ("TRUE_PROSPECTIVE", "BACKFILL_SIMULATION", "HISTORICAL_VALIDATION")


def wilson_confidence_interval(positive: int, total: int, *, z: float = Z_95) -> tuple[float, float]:
    """Wilson score interval -- stays well-behaved for small samples, unlike a naive
    normal approximation around the point estimate."""
    if total <= 0:
        return 0.0, 1.0
    p = positive / total
    denom = 1.0 + z * z / total
    centre = p + z * z / (2 * total)
    spread = z * math.sqrt((p * (1 - p) + z * z / (4 * total)) / total)
    low = (centre - spread) / denom
    high = (centre + spread) / denom
    return max(0.0, low), min(1.0, high)


def laplace_smoothed_probability(positive: int, total: int, *, alpha: float = 1.0, beta: float = 1.0) -> float:
    """Beta-Binomial posterior mean with prior Beta(alpha, beta). alpha=beta=1 is
    Laplace (add-one) smoothing; both must be frozen in the protocol before any
    prospective prediction is made."""
    return (positive + alpha) / (total + alpha + beta)


def classify_sample_sufficiency(count: int, *, minimum: int) -> str:
    return "FORECAST_AVAILABLE" if count >= minimum else "INSUFFICIENT_CONTEXT_HISTORY"


@dataclass(frozen=True)
class FallbackLevelStats:
    level: str
    positive_count: int
    total_count: int


@dataclass(frozen=True)
class FallbackSelection:
    level_used: str
    fallback_reason: str | None
    positive_count: int
    total_count: int


def select_fallback_level(levels: list[FallbackLevelStats], *, minimum: int) -> FallbackSelection:
    """Walks a predeclared, ordered (most-specific-first) fallback hierarchy and
    returns the first level meeting the minimum historical sample. If none do, the
    least-specific (last) level is used and flagged accordingly -- this must never
    silently change which level was actually used."""
    if not levels:
        raise ValueError("EMPTY_FALLBACK_HIERARCHY")
    for level in levels[:-1]:
        if level.total_count >= minimum:
            reason = None if level is levels[0] else f"FALLBACK_FROM_{levels[0].level.upper()}"
            return FallbackSelection(level.level, reason, level.positive_count, level.total_count)
    last = levels[-1]
    if last.total_count >= minimum:
        reason = None if last is levels[0] else f"FALLBACK_FROM_{levels[0].level.upper()}"
        return FallbackSelection(last.level, reason, last.positive_count, last.total_count)
    return FallbackSelection(last.level, "INSUFFICIENT_AT_ALL_FALLBACK_LEVELS", last.positive_count, last.total_count)


def verify_historical_as_of(forecast_created_at: datetime, outcome_available_at: datetime) -> bool:
    """A prospective forecast is only valid if it was created strictly before the
    future outcome it predicts could possibly have existed."""
    return forecast_created_at < outcome_available_at


def detect_data_revision(original_hash: str, current_hash: str) -> bool:
    """True means the provider's data changed retroactively since the forecast/outcome
    was first computed. The original forecast/outcome must never be silently rewritten
    when this is detected -- only recorded."""
    return original_hash != current_hash


def brier(probability: float, actual_positive: bool) -> float:
    p = min(1.0, max(0.0, probability))
    return float((p - (1.0 if actual_positive else 0.0)) ** 2)


def log_loss(probability: float, actual_positive: bool) -> float:
    p = min(1.0 - 1e-12, max(1e-12, probability))
    return float(-(math.log(p) if actual_positive else math.log(1.0 - p)))


def calibration_error(rows: list[dict[str, Any]], *, bins: int = 10) -> tuple[float, list[dict[str, Any]]]:
    if not rows:
        return 0.0, []
    ece = 0.0
    out = []
    for idx in range(bins):
        low, high = idx / bins, (idx + 1) / bins
        members = [
            r for r in rows
            if low <= float(r["probability_positive"]) < high or (idx == bins - 1 and float(r["probability_positive"]) == 1.0)
        ]
        if not members:
            out.append({"bin": idx, "count": 0})
            continue
        mean_p = statistics.fmean(float(r["probability_positive"]) for r in members)
        observed = statistics.fmean(1.0 if r["actual_positive"] else 0.0 for r in members)
        gap = abs(mean_p - observed)
        ece += len(members) / len(rows) * gap
        out.append({"bin": idx, "count": len(members), "mean_predicted": mean_p, "observed_frequency": observed})
    return float(ece), out


def balanced_accuracy_and_mcc(rows: list[dict[str, Any]], *, threshold: float = 0.5) -> tuple[float | None, float | None]:
    """Binary classification quality at a fixed decision threshold, treating
    probability_positive >= threshold as a predicted-positive call. Both metrics are
    None when a class is entirely absent (positive or negative rate is degenerate),
    since balanced accuracy and MCC are undefined in that case rather than merely 0."""
    tp = fp = tn = fn = 0
    for r in rows:
        predicted_positive = float(r["probability_positive"]) >= threshold
        actual_positive = bool(r["actual_positive"])
        if predicted_positive and actual_positive:
            tp += 1
        elif predicted_positive and not actual_positive:
            fp += 1
        elif not predicted_positive and actual_positive:
            fn += 1
        else:
            tn += 1

    sensitivity = tp / (tp + fn) if (tp + fn) > 0 else None
    specificity = tn / (tn + fp) if (tn + fp) > 0 else None
    balanced_accuracy = None if sensitivity is None or specificity is None else (sensitivity + specificity) / 2.0

    mcc_denominator = math.sqrt((tp + fp) * (tp + fn) * (tn + fp) * (tn + fn))
    mcc = None if mcc_denominator == 0 else (tp * tn - fp * fn) / mcc_denominator

    return balanced_accuracy, mcc


def _baseline_values(rows: list[dict[str, Any]], default: float | None) -> list[float | None]:
    """Per-row unconditional baseline. Each row may carry its own
    `unconditional_probability` (the historical base rate for that row's own
    instrument/window-length/horizon); otherwise the scalar `default` applies. A skill
    score is only meaningful when every row in the set has a baseline, so callers treat
    a set containing any missing baseline as unscoreable rather than silently mixing."""
    values = []
    for row in rows:
        own = row.get("unconditional_probability")
        values.append(float(own) if own is not None else default)
    return values


def brier_evaluation(rows: list[dict[str, Any]], *, unconditional_probability: float | None = None) -> dict[str, Any]:
    """rows: [{"probability_positive": float, "actual_positive": bool, optional
    "unconditional_probability": float}, ...].

    A per-row `unconditional_probability` takes precedence over the scalar
    `unconditional_probability`; this matters when the set pools several
    instrument/horizon combinations whose base rates genuinely differ -- a single scalar
    baseline would misstate skill for every row that is not that one combination."""
    if not rows:
        return {"sample_count": 0}
    briers = [brier(float(r["probability_positive"]), bool(r["actual_positive"])) for r in rows]
    own_brier = statistics.fmean(briers)
    baselines = _baseline_values(rows, unconditional_probability)
    baseline_brier = None
    if all(value is not None for value in baselines):
        baseline_brier = statistics.fmean(
            brier(float(base), bool(row["actual_positive"])) for base, row in zip(baselines, rows)
        )
    ece, bins = calibration_error(rows)
    balanced_accuracy, mcc = balanced_accuracy_and_mcc(rows)
    return {
        "sample_count": len(rows),
        "brier_score": own_brier,
        "brier_skill_vs_unconditional": None if baseline_brier is None else 1.0 - own_brier / max(1e-12, baseline_brier),
        "log_loss": statistics.fmean(log_loss(float(r["probability_positive"]), bool(r["actual_positive"])) for r in rows),
        "direction_accuracy": statistics.fmean(
            1.0 if (float(r["probability_positive"]) >= 0.5) == bool(r["actual_positive"]) else 0.0 for r in rows
        ),
        "balanced_accuracy": balanced_accuracy,
        "mcc": mcc,
        "expected_calibration_error": ece,
        "calibration_bins": bins,
    }


def paired_brier_skill_bootstrap(
    rows: list[dict[str, Any]],
    *,
    seed: int,
    unconditional_probability: float | None = None,
    iterations: int = 1000,
    confidence: float = 0.95,
    block_size: int | None = None,
) -> dict[str, Any]:
    """Confidence interval for the reported `1 - brier_model / brier_unconditional`
    statistic. Matured forecasts are resampled in contiguous blocks (default block size
    = floor(sqrt(n)), matching the project's paired-block-bootstrap convention) and the
    skill is recomputed within each resample, so the interval reflects the same
    statistic that is reported. Rows must be ordered (e.g. by forecast timestamp) for
    block contiguity to carry any temporal meaning. Deterministic for a fixed seed."""
    n = len(rows)
    empty = {"low": None, "high": None, "standard_error": None, "iterations": 0, "block_size": 0}
    if n == 0:
        return empty
    baselines = _baseline_values(rows, unconditional_probability)
    if any(value is None for value in baselines):
        return empty
    block = block_size or max(1, int(math.sqrt(n)))
    blocks = [list(range(start, min(start + block, n))) for start in range(0, n, block)]
    rng = random.Random(seed)
    skills: list[float] = []
    for _ in range(iterations):
        sampled: list[int] = []
        while len(sampled) < n:
            sampled.extend(rng.choice(blocks))
        sampled = sampled[:n]
        model = statistics.fmean(brier(float(rows[i]["probability_positive"]), bool(rows[i]["actual_positive"])) for i in sampled)
        baseline = statistics.fmean(brier(float(baselines[i]), bool(rows[i]["actual_positive"])) for i in sampled)
        skills.append(1.0 - model / max(1e-12, baseline))
    skills.sort()
    alpha = 1.0 - confidence
    low = skills[int((alpha / 2) * (iterations - 1))]
    high = skills[int((1 - alpha / 2) * (iterations - 1))]
    standard_error = statistics.pstdev(skills) if len(skills) > 1 else 0.0
    return {"low": low, "high": high, "standard_error": standard_error, "iterations": iterations, "block_size": block}


def per_horizon_evaluation(
    rows: list[dict[str, Any]],
    *,
    seed: int,
    iterations: int = 1000,
    confidence: float = 0.95,
) -> dict[str, dict[str, Any]]:
    """Evaluate each horizon independently. `rows` must each carry `horizon_bars`;
    `block_size` for the paired bootstrap is derived per horizon from its own sample
    size. Keyed by `str(horizon_bars)` so the result is JSON-round-trippable."""
    horizons = sorted({int(r["horizon_bars"]) for r in rows})
    grouped: dict[str, dict[str, Any]] = {}
    for horizon in horizons:
        horizon_rows = [r for r in rows if int(r["horizon_bars"]) == horizon]
        metrics = brier_evaluation(horizon_rows)
        interval = paired_brier_skill_bootstrap(
            horizon_rows,
            seed=seed + horizon,
            iterations=iterations,
            confidence=confidence,
        )
        metrics["bootstrap_ci_low"] = interval["low"]
        metrics["bootstrap_ci_high"] = interval["high"]
        metrics["bootstrap_standard_error"] = interval["standard_error"]
        grouped[str(horizon)] = metrics
    return grouped


@dataclass(frozen=True)
class ProspectiveDecisionResult:
    decision: str
    rationale: str


def classify_prospective_decision(
    *,
    matured_count: int,
    minimum_evidence: int,
    preferred_evidence: int,
    brier_skill_vs_unconditional: float | None,
    bootstrap_ci_low: float | None,
) -> ProspectiveDecisionResult:
    if matured_count < minimum_evidence:
        return ProspectiveDecisionResult(
            "PROSPECTIVE_EVIDENCE_ACCUMULATING",
            f"Only {matured_count} of the required minimum {minimum_evidence} matured forecasts exist; "
            "no scientific interpretation is warranted yet.",
        )
    if brier_skill_vs_unconditional is None:
        return ProspectiveDecisionResult(
            "PROSPECTIVE_EVIDENCE_ACCUMULATING", "Brier skill could not be computed from matured forecasts yet."
        )
    if brier_skill_vs_unconditional <= 0.0:
        return ProspectiveDecisionResult(
            "PROSPECTIVE_CONTEXT_SIGNAL_NOT_SUPPORTED",
            "Prospective Brier skill vs unconditional history is not positive.",
        )
    if (
        matured_count >= preferred_evidence
        and bootstrap_ci_low is not None
        and bootstrap_ci_low > 0.0
    ):
        return ProspectiveDecisionResult(
            "PROSPECTIVE_CONTEXT_SIGNAL_SUPPORTED",
            f"{matured_count} matured forecasts (>= preferred {preferred_evidence}); positive Brier skill "
            "with a confidence interval excluding zero.",
        )
    return ProspectiveDecisionResult(
        "PROSPECTIVE_CONTEXT_SIGNAL_WEAK",
        "Prospective Brier skill vs unconditional history is positive but either the matured sample has not "
        "yet reached the preferred evidence threshold or the confidence interval does not clearly exclude zero.",
    )
