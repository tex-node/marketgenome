from __future__ import annotations

import argparse
import csv
import json
import math
import os
import random
import shutil
import statistics
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import yaml
from market_genome_domain.database import SessionLocal
from market_genome_domain.models import (
    ExperimentArtifact,
    ExperimentRun,
    ExperimentRunStatus,
    StudyDatasetEntry,
    StudyManifest,
)
from market_genome_shared.hashing import sha256_canonical
from sqlalchemy import text

PROTECTED_TABLES = [
    "price_bars",
    "pattern_windows",
    "normalized_patterns",
    "market_dna",
    "market_contexts",
    "outcome_observations",
    "study_episodes",
]


@dataclass(frozen=True)
class Row:
    id: str
    instrument_id: str
    symbol: str
    asset_class: str
    timeframe_id: str
    window_length: int
    start: datetime
    end: datetime
    shape: np.ndarray
    dna: dict[str, float]
    dna_vector: np.ndarray
    robust_dna_vector: np.ndarray
    context: dict[str, str | None]
    context_family: str
    episode_id: str


def load_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fieldnames is None:
        keys: list[str] = []
        for row in rows:
            for key in row:
                if key not in keys:
                    keys.append(key)
        fieldnames = keys
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def read_meminfo() -> dict[str, int]:
    values: dict[str, int] = {}
    for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
        if ":" not in line:
            continue
        key, raw = line.split(":", 1)
        try:
            values[key] = int(raw.strip().split()[0]) // 1024
        except (IndexError, ValueError):
            continue
    return values


def resource_snapshot(output_root: Path) -> dict[str, Any]:
    mem = read_meminfo() if Path("/proc/meminfo").exists() else {}
    disk = shutil.disk_usage(output_root if output_root.exists() else output_root.parent)
    return {
        "timestamp": datetime.now(UTC).isoformat(),
        "available_ram_mb": mem.get("MemAvailable"),
        "free_swap_mb": mem.get("SwapFree"),
        "disk_free_gb": round(disk.free / (1024**3), 3),
    }


def enforce_resource_guard(cfg: dict[str, Any], output_root: Path, stage: str) -> dict[str, Any]:
    limits = cfg["resource_limits"]
    snap = resource_snapshot(output_root)
    reasons = []
    if snap["available_ram_mb"] is not None and snap["available_ram_mb"] < int(limits["min_available_ram_mb"]):
        reasons.append("AVAILABLE_RAM_BELOW_THRESHOLD")
    if snap["free_swap_mb"] is not None and snap["free_swap_mb"] < int(limits["min_free_swap_mb"]):
        reasons.append("FREE_SWAP_BELOW_THRESHOLD")
    if snap["disk_free_gb"] < float(limits["min_free_disk_gb"]):
        reasons.append("FREE_DISK_BELOW_THRESHOLD")
    snap["stage"] = stage
    snap["status"] = "PASSED" if not reasons else "PILOT_VALIDATION_PAUSED_RESOURCE_GUARD"
    snap["reasons"] = reasons
    if reasons:
        print(json.dumps(snap, sort_keys=True))
        raise SystemExit(75)
    return snap


def brier(probability: float, actual_positive: bool) -> float:
    p = min(1.0, max(0.0, probability))
    return float((p - (1.0 if actual_positive else 0.0)) ** 2)


def log_loss(probability: float, actual_positive: bool) -> float:
    p = min(1.0 - 1e-12, max(1e-12, probability))
    return float(-(math.log(p) if actual_positive else math.log(1.0 - p)))


def entropy(probabilities: list[float]) -> float:
    return float(-sum(p * math.log(max(p, 1e-12)) for p in probabilities if p > 0.0))


def calibration(rows: list[dict[str, Any]], bins: int = 10) -> tuple[float, float, list[dict[str, Any]]]:
    if not rows:
        return 0.0, 0.0, []
    out = []
    ece = 0.0
    mce = 0.0
    for idx in range(bins):
        low = idx / bins
        high = (idx + 1) / bins
        members = [r for r in rows if low <= float(r["predicted_positive_probability"]) < high or (idx == bins - 1 and float(r["predicted_positive_probability"]) == 1.0)]
        if not members:
            out.append({"bin": idx, "count": 0, "mean_predicted_probability": None, "observed_frequency": None, "confidence_interval_low": None, "confidence_interval_high": None})
            continue
        mean_p = statistics.fmean(float(r["predicted_positive_probability"]) for r in members)
        observed = statistics.fmean(1.0 if r["actual_positive"] else 0.0 for r in members)
        gap = abs(mean_p - observed)
        ece += len(members) / len(rows) * gap
        mce = max(mce, gap)
        se = math.sqrt(max(0.0, observed * (1.0 - observed)) / max(1, len(members)))
        out.append(
            {
                "bin": idx,
                "count": len(members),
                "mean_predicted_probability": mean_p,
                "observed_frequency": observed,
                "confidence_interval_low": max(0.0, observed - 1.96 * se),
                "confidence_interval_high": min(1.0, observed + 1.96 * se),
            }
        )
    return float(ece), float(mce), out


def time_block_ci(values: list[float], stamps: list[datetime], seed: int, iterations: int, confidence: float) -> dict[str, float | None]:
    if not values:
        return {"low": None, "high": None, "standard_error": None}
    pairs = sorted(zip(stamps, values, strict=False), key=lambda item: item[0])
    vals = [v for _, v in pairs]
    block = max(1, int(math.sqrt(len(vals))))
    blocks = [vals[i : i + block] for i in range(0, len(vals), block)]
    rng = random.Random(seed)
    samples = []
    for _ in range(iterations):
        sample: list[float] = []
        while len(sample) < len(vals):
            sample.extend(rng.choice(blocks))
        samples.append(statistics.fmean(sample[: len(vals)]))
    samples.sort()
    alpha = 1.0 - confidence
    low = samples[int((alpha / 2) * (iterations - 1))]
    high = samples[int((1 - alpha / 2) * (iterations - 1))]
    return {"low": low, "high": high, "standard_error": float(np.std(samples, ddof=1)) if len(samples) > 1 else 0.0}


def bh_adjust(p_values: list[float]) -> list[float]:
    if not p_values:
        return []
    ordered = sorted(enumerate(p_values), key=lambda item: item[1], reverse=True)
    adjusted = [1.0] * len(p_values)
    running = 1.0
    n = len(p_values)
    for rank_from_end, (idx, pval) in enumerate(ordered, start=1):
        rank = n - rank_from_end + 1
        running = min(running, pval * n / max(rank, 1))
        adjusted[idx] = min(1.0, max(pval, running))
    return adjusted


def p_value_from_skill(skill_samples: list[float]) -> float:
    if not skill_samples:
        return 1.0
    mean = statistics.fmean(skill_samples)
    se = statistics.pstdev(skill_samples) / math.sqrt(len(skill_samples)) if len(skill_samples) > 1 else 0.0
    if se <= 1e-12:
        return 1.0
    z = mean / se
    return float(0.5 * math.erfc(z / math.sqrt(2)))


def protected_counts(session) -> dict[str, int]:
    return {table: int(session.execute(text(f"select count(*) from {table}")).scalar_one()) for table in PROTECTED_TABLES}


def dry_run_window_summary(session, study_id: str, window_length: int, horizons: list[int], per_instrument: int) -> dict[str, Any]:
    sql = text(
        """
        with included as (
          select sde.instrument_id, sde.timeframe_id
          from study_dataset_entries sde
          where sde.study_id = :study_id
            and sde.inclusion_status = 'INCLUDED'
        ),
        eligible as (
          select
            pw.id,
            pw.instrument_id,
            i.symbol,
            i.asset_class,
            pw.end_timestamp,
            row_number() over (partition by pw.instrument_id order by pw.end_timestamp, pw.id) as rn,
            count(*) over (partition by pw.instrument_id) as n
          from pattern_windows pw
          join included inc on inc.instrument_id = pw.instrument_id and inc.timeframe_id = pw.timeframe_id
          join instruments i on i.id = pw.instrument_id
          where pw.window_length = :window_length
            and not exists (
              select 1
              from unnest(:horizons) as h(horizon)
              where not exists (
                select 1
                from outcome_observations oo
                where oo.pattern_window_id = pw.id
                  and oo.horizon_bars = h.horizon
                  and oo.is_complete is true
              )
            )
        ),
        validation as (
          select *
          from eligible
          where rn > floor(n * 0.70)
        ),
        selected as (
          select *
          from (
            select
              validation.*,
              row_number() over (partition by instrument_id order by end_timestamp, id) as vrn,
              count(*) over (partition by instrument_id) as vn
            from validation
          ) s
          where vrn <= :per_instrument
        )
        select
          (select count(*) from eligible) as eligible_windows,
          (select count(*) from validation) as validation_windows,
          (select count(*) from selected) as selected_query_windows,
          coalesce(jsonb_object_agg(symbol, symbol_count), '{}'::jsonb) as query_count_by_instrument,
          coalesce(jsonb_object_agg(asset_class, asset_class_count), '{}'::jsonb) as query_count_by_asset_class
        from (
          select distinct
            symbol,
            count(*) over (partition by symbol) as symbol_count,
            asset_class,
            count(*) over (partition by asset_class) as asset_class_count
          from selected
        ) counts
        """
    )
    row = session.execute(
        sql,
        {
            "study_id": study_id,
            "window_length": window_length,
            "horizons": horizons,
            "per_instrument": per_instrument,
        },
    ).mappings().one()
    return {
        "window_length": window_length,
        "loaded_windows": int(row["eligible_windows"] or 0),
        "validation_windows": int(row["validation_windows"] or 0),
        "selected_query_windows": int(row["selected_query_windows"] or 0),
        "query_count_by_asset_class": dict(row["query_count_by_asset_class"] or {}),
        "query_count_by_instrument": dict(row["query_count_by_instrument"] or {}),
    }


def load_rows(session, study_id: str, window_length: int, horizons: list[int]) -> tuple[list[Row], dict[tuple[str, int], dict[str, Any]]]:
    entries = (
        session.query(StudyDatasetEntry)
        .filter(StudyDatasetEntry.study_id == study_id, StudyDatasetEntry.inclusion_status == "INCLUDED")
        .all()
    )
    instrument_ids = [entry.instrument_id for entry in entries]
    timeframe_ids = sorted({entry.timeframe_id for entry in entries})
    if not instrument_ids:
        raise RuntimeError("NO_INCLUDED_STUDY_DATASETS")
    sql = text(
        """
        select
          pw.id::text as id,
          pw.instrument_id::text as instrument_id,
          pw.timeframe_id::text as timeframe_id,
          i.symbol,
          i.asset_class,
          pw.window_length,
          pw.start_timestamp,
          pw.end_timestamp,
          np.normalized_values,
          md.feature_values,
          md.feature_vector,
          mc.trend_state,
          mc.volatility_state,
          mc.volatility_phase_state,
          mc.persistence_state,
          mc.activity_state,
          mc.shock_state,
          mc.market_phase_state,
          mc.context_family_code,
          coalesce(
            (
              select se.episode_id
              from study_episodes se
              where se.study_id = :study_id
                and se.instrument_id = pw.instrument_id
                and se.timeframe_id = pw.timeframe_id
                and pw.end_timestamp between se.episode_start and se.episode_end
              order by se.episode_start desc
              limit 1
            ),
            i.symbol || ':' || to_char(pw.end_timestamp, 'YYYY-MM')
          ) as episode_id
        from pattern_windows pw
        join instruments i on i.id = pw.instrument_id
        join normalized_patterns np on np.pattern_window_id = pw.id
        join market_dna md on md.pattern_window_id = pw.id
        left join market_contexts mc on mc.pattern_window_id = pw.id
        where pw.instrument_id = any(:instrument_ids)
          and pw.timeframe_id = any(:timeframe_ids)
          and pw.window_length = :window_length
        order by pw.end_timestamp, pw.id
        """
    )
    db_rows = session.execute(
        sql,
        {"study_id": study_id, "instrument_ids": instrument_ids, "timeframe_ids": timeframe_ids, "window_length": window_length},
    ).mappings()
    rows: list[Row] = []
    for item in db_rows:
        ordered = item["feature_vector"].get("ordered_features", [])
        dna = {key: float(item["feature_values"][key]) for key in ordered if item["feature_values"].get(key) is not None}
        dna_vec = np.asarray([dna.get(key, 0.0) for key in ordered], dtype=np.float64)
        robust = np.sign(dna_vec) * np.log1p(np.abs(dna_vec))
        rows.append(
            Row(
                id=item["id"],
                instrument_id=item["instrument_id"],
                symbol=item["symbol"],
                asset_class=item["asset_class"],
                timeframe_id=item["timeframe_id"],
                window_length=int(item["window_length"]),
                start=item["start_timestamp"],
                end=item["end_timestamp"],
                shape=np.asarray(item["normalized_values"].get("close", []), dtype=np.float64),
                dna=dna,
                dna_vector=dna_vec,
                robust_dna_vector=robust,
                context={
                    "trend_state": item["trend_state"],
                    "volatility_state": item["volatility_state"],
                    "volatility_phase_state": item["volatility_phase_state"],
                    "persistence_state": item["persistence_state"],
                    "activity_state": item["activity_state"],
                    "shock_state": item["shock_state"],
                    "market_phase_state": item["market_phase_state"],
                },
                context_family=item["context_family_code"] or "UNAVAILABLE",
                episode_id=item["episode_id"],
            )
        )
    outcome_sql = text(
        """
        select oo.pattern_window_id::text as window_id, oo.horizon_bars, oo.future_simple_return,
               oo.maximum_favourable_excursion, oo.maximum_adverse_excursion,
               oo.direction_class, oo.continuation_reversal_class
        from outcome_observations oo
        join pattern_windows pw on pw.id = oo.pattern_window_id
        where pw.instrument_id = any(:instrument_ids)
          and pw.timeframe_id = any(:timeframe_ids)
          and pw.window_length = :window_length
          and oo.horizon_bars = any(:horizons)
          and oo.is_complete is true
        """
    )
    outcomes = {
        (item["window_id"], int(item["horizon_bars"])): dict(item)
        for item in session.execute(
            outcome_sql,
            {"instrument_ids": instrument_ids, "timeframe_ids": timeframe_ids, "window_length": window_length, "horizons": horizons},
        ).mappings()
    }
    return rows, outcomes


def select_queries(rows: list[Row], outcomes: dict[tuple[str, int], dict[str, Any]], horizons: list[int], per_instrument: int) -> list[Row]:
    by_key: dict[str, list[Row]] = defaultdict(list)
    for row in rows:
        if all((row.id, horizon) in outcomes for horizon in horizons):
            by_key[row.instrument_id].append(row)
    selected = []
    for items in by_key.values():
        items = sorted(items, key=lambda row: (row.end, row.id))
        start = int(len(items) * 0.70)
        validation = items[start:]
        if not validation:
            continue
        if per_instrument >= len(validation):
            selected.extend(validation)
        else:
            for idx in np.linspace(0, len(validation) - 1, per_instrument, dtype=int):
                selected.append(validation[int(idx)])
    return sorted(selected, key=lambda row: (row.end, row.id))


def eligible_candidates(
    query: Row,
    rows: list[Row],
    outcomes: dict[tuple[str, int], dict[str, Any]],
    horizon: int,
    arm: str,
    limit: int,
    seed: int,
) -> tuple[list[Row], Counter]:
    counts: Counter = Counter()
    eligible = []
    embargo = timedelta(days=horizon)
    for row in rows:
        if row.id == query.id:
            counts["same_query"] += 1
            continue
        if row.end >= query.end:
            counts["future_or_contemporary"] += 1
            continue
        if row.end >= query.start:
            counts["source_overlap"] += 1
            continue
        if row.end + embargo >= query.start:
            counts["outcome_overlap"] += 1
            continue
        if (row.id, horizon) not in outcomes:
            counts["missing_outcome"] += 1
            continue
        if arm == "same_instrument" and row.instrument_id != query.instrument_id:
            counts["arm_exclusion"] += 1
            continue
        if arm == "same_asset_class" and row.asset_class != query.asset_class:
            counts["arm_exclusion"] += 1
            continue
        eligible.append(row)
    if len(eligible) > limit:
        rng = random.Random(seed)
        eligible = rng.sample(eligible, limit)
        counts["candidate_sampled_out"] += max(0, len(rows) - limit)
    return eligible, counts


def shape_euclidean(query: Row, candidates: list[Row]) -> np.ndarray:
    matrix = np.vstack([row.shape for row in candidates])
    return np.linalg.norm(matrix - query.shape, axis=1) / math.sqrt(max(1, len(query.shape)))


def shape_correlation(query: Row, candidates: list[Row]) -> np.ndarray:
    q = query.shape
    q_std = np.std(q)
    out = []
    for row in candidates:
        c_std = np.std(row.shape)
        if q_std < 1e-12 or c_std < 1e-12:
            out.append(1.0)
        else:
            out.append(1.0 - max(-1.0, min(1.0, float(np.corrcoef(q, row.shape)[0, 1]))))
    return np.asarray(out, dtype=np.float64)


def cosine_distance(query: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    denom = np.linalg.norm(matrix, axis=1) * max(float(np.linalg.norm(query)), 1e-12)
    cosine = np.clip((matrix @ query) / np.maximum(denom, 1e-12), -1.0, 1.0)
    return 1.0 - cosine


def dna_euclidean(query: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    return np.linalg.norm(matrix - query, axis=1) / math.sqrt(max(1, len(query)))


def context_distance(query: Row, candidates: list[Row]) -> np.ndarray:
    dims = ["trend_state", "volatility_state", "volatility_phase_state", "persistence_state", "activity_state", "shock_state", "market_phase_state"]
    out = []
    for row in candidates:
        matches = sum(1 for dim in dims if row.context.get(dim) == query.context.get(dim))
        out.append(1.0 - matches / len(dims))
    return np.asarray(out, dtype=np.float64)


def rank_method(query: Row, candidates: list[Row], method: str, episode_cap: int, k: int) -> list[tuple[Row, float]]:
    if not candidates:
        return []
    if method == "shape_euclidean_v1":
        dist = shape_euclidean(query, candidates)
    elif method == "shape_correlation_v1":
        dist = shape_correlation(query, candidates)
    elif method == "dna_cosine_v1":
        matrix = np.vstack([row.dna_vector for row in candidates])
        dist = cosine_distance(query.dna_vector, matrix)
    elif method == "dna_robust_cosine_v1":
        matrix = np.vstack([row.robust_dna_vector for row in candidates])
        dist = cosine_distance(query.robust_dna_vector, matrix)
    elif method == "dna_robust_euclidean_v1" or method == "dna_group_balanced_v1":
        matrix = np.vstack([row.robust_dna_vector for row in candidates])
        dist = dna_euclidean(query.robust_dna_vector, matrix)
    elif method == "market_analogue_v1":
        matrix = np.vstack([row.dna_vector for row in candidates])
        dist = 0.45 * shape_euclidean(query, candidates) + 0.45 * cosine_distance(query.dna_vector, matrix) + 0.10 * context_distance(query, candidates)
    elif method in {"shape_dna_context_v2", "episode_diverse_analogue_v1"}:
        matrix = np.vstack([row.robust_dna_vector for row in candidates])
        dist = 0.34 * shape_euclidean(query, candidates) + 0.33 * cosine_distance(query.robust_dna_vector, matrix) + 0.33 * context_distance(query, candidates)
    else:
        raise ValueError(f"UNSUPPORTED_METHOD:{method}")
    ordered = sorted(zip(candidates, dist, strict=False), key=lambda item: (float(item[1]), item[0].end, item[0].id))
    cap = episode_cap if method == "episode_diverse_analogue_v1" else 10**9
    counts: Counter = Counter()
    selected = []
    for row, distance in ordered:
        if counts[row.episode_id] >= cap:
            continue
        counts[row.episode_id] += 1
        selected.append((row, float(distance)))
        if len(selected) >= k:
            break
    return selected


def baseline_rank(query: Row, candidates: list[Row], baseline: str, k: int, seed: int) -> list[tuple[Row, float]]:
    filtered = list(candidates)
    if baseline == "same_instrument_random_v1":
        filtered = [row for row in filtered if row.instrument_id == query.instrument_id]
    elif baseline == "same_asset_class_random_v1":
        filtered = [row for row in filtered if row.asset_class == query.asset_class]
    elif baseline in {"same_context_random_v1", "context_filter_random_v1"}:
        filtered = [
            row
            for row in filtered
            if row.context.get("trend_state") == query.context.get("trend_state")
            and row.context.get("volatility_state") == query.context.get("volatility_state")
        ]
    rng = random.Random(seed)
    rng.shuffle(filtered)
    if baseline in {"unconditional_outcome_v1", "naive_continuation_v1", "naive_mean_reversion_v1"}:
        filtered = sorted(filtered, key=lambda row: (row.end, row.id))
    return [(row, float(rank)) for rank, row in enumerate(filtered[:k], start=1)]


def aggregate(
    ranked: list[tuple[Row, float]],
    outcomes: dict[tuple[str, int], dict[str, Any]],
    horizon: int,
    weighting: str,
    query: Row,
    baseline: str | None,
) -> dict[str, Any] | None:
    rows = [(row, distance, outcomes[(row.id, horizon)]) for row, distance in ranked if (row.id, horizon) in outcomes]
    if not rows:
        return None
    distances = np.asarray([distance for _, distance, _ in rows], dtype=np.float64)
    if weighting == "inverse_distance_v1":
        weights = 1.0 / np.maximum(distances, 1e-9)
    else:
        weights = np.ones(len(rows), dtype=np.float64)
    weights = weights / np.sum(weights)
    returns = np.asarray([float(outcome["future_simple_return"]) for _, _, outcome in rows], dtype=np.float64)
    mfes = np.asarray([float(outcome["maximum_favourable_excursion"] or 0.0) for _, _, outcome in rows], dtype=np.float64)
    maes = np.asarray([float(outcome["maximum_adverse_excursion"] or 0.0) for _, _, outcome in rows], dtype=np.float64)
    prob_pos = float(np.sum(weights[returns > 0]))
    if baseline == "naive_continuation_v1":
        query_direction_positive = bool(query.shape[-1] >= query.shape[0]) if len(query.shape) else True
        prob_pos = 0.60 if query_direction_positive else 0.40
    elif baseline == "naive_mean_reversion_v1":
        query_direction_positive = bool(query.shape[-1] >= query.shape[0]) if len(query.shape) else True
        prob_pos = 0.40 if query_direction_positive else 0.60
    episode_counts = Counter(row.episode_id for row, _, _ in rows)
    top_counts = sorted(episode_counts.values(), reverse=True)
    return {
        "predicted_positive_probability": prob_pos,
        "predicted_negative_probability": float(np.sum(weights[returns < 0])),
        "predicted_flat_probability": max(0.0, 1.0 - prob_pos - float(np.sum(weights[returns < 0]))),
        "expected_return": float(np.sum(weights * returns)),
        "median_return": float(np.median(returns)),
        "return_q10": float(np.quantile(returns, 0.10)),
        "return_q50": float(np.quantile(returns, 0.50)),
        "return_q90": float(np.quantile(returns, 0.90)),
        "expected_mfe": float(np.sum(weights * mfes)),
        "expected_mae": float(np.sum(weights * maes)),
        "return_std": float(np.std(returns, ddof=1)) if len(returns) > 1 else 0.0,
        "return_mad": float(np.median(np.abs(returns - np.median(returns)))),
        "return_iqr": float(np.quantile(returns, 0.75) - np.quantile(returns, 0.25)),
        "mfe_dispersion": float(np.std(mfes, ddof=1)) if len(mfes) > 1 else 0.0,
        "mae_dispersion": float(np.std(maes, ddof=1)) if len(maes) > 1 else 0.0,
        "direction_entropy": entropy([prob_pos, float(np.sum(weights[returns < 0])), max(0.0, 1.0 - prob_pos - float(np.sum(weights[returns < 0])))]),
        "raw_neighbour_count": len(ranked),
        "retrieved_match_count": len(rows),
        "unique_episode_count": len(episode_counts),
        "largest_episode_share": (top_counts[0] / len(rows)) if rows else 0.0,
        "top_three_episode_share": (sum(top_counts[:3]) / len(rows)) if rows else 0.0,
        "effective_sample_size": float(1.0 / np.sum(weights * weights)),
    }


def summarize(group_rows: list[dict[str, Any]], baseline_brier: float | None = None) -> dict[str, Any]:
    if not group_rows:
        return {}
    briers = [float(r["brier_score"]) for r in group_rows]
    log_losses = [float(r["log_loss"]) for r in group_rows]
    abs_errors = [float(r["return_absolute_error"]) for r in group_rows]
    probs = [float(r["predicted_positive_probability"]) for r in group_rows]
    actual = [bool(r["actual_positive"]) for r in group_rows]
    ece, mce, _ = calibration(group_rows)
    own_brier = statistics.fmean(briers)
    return {
        "sample_count": len(group_rows),
        "brier_score": own_brier,
        "brier_skill_vs_unconditional": None if baseline_brier is None else 1.0 - own_brier / max(1e-12, baseline_brier),
        "log_loss": statistics.fmean(log_losses),
        "return_mae": statistics.fmean(abs_errors),
        "median_absolute_return_error": statistics.median(abs_errors),
        "direction_accuracy": statistics.fmean(1.0 if (p >= 0.5) == a else 0.0 for p, a in zip(probs, actual, strict=False)),
        "expected_calibration_error": ece,
        "maximum_calibration_error": mce,
        "mean_effective_sample_size": statistics.fmean(float(r["effective_sample_size"]) for r in group_rows),
        "mean_unique_episode_count": statistics.fmean(float(r["unique_episode_count"]) for r in group_rows),
        "mean_return_std": statistics.fmean(float(r["return_std"]) for r in group_rows),
        "mean_return_mad": statistics.fmean(float(r["return_mad"]) for r in group_rows),
        "mean_direction_entropy": statistics.fmean(float(r["direction_entropy"]) for r in group_rows),
    }


def run_validation(config_path: Path, output_root: Path, dry_run: bool) -> int:
    cfg = load_yaml(config_path)
    output_root.mkdir(parents=True, exist_ok=True)
    resources = [enforce_resource_guard(cfg, output_root, "start")]
    started = time.monotonic()
    study_id = cfg["dataset"]["study_id"]
    config_hash = sha256_canonical(cfg)
    eval_config_count = (
        (len(cfg["similarity_methods"]) + len(cfg["baselines"]))
        * len(cfg["study_arms"])
        * len(cfg["neighbour_counts"])
        * len(cfg["episode_caps"])
        * len(cfg["weighting"])
    )
    if eval_config_count > int(cfg["resource_limits"]["maximum_evaluated_configurations"]):
        raise RuntimeError(f"VALIDATION_GRID_TOO_LARGE:{eval_config_count}")

    evaluations: list[dict[str, Any]] = []
    exclusions: list[dict[str, Any]] = []
    deciles: list[dict[str, Any]] = []
    dry_summary: list[dict[str, Any]] = []
    source_before: dict[str, int]
    source_after: dict[str, int]
    with SessionLocal() as session:
        study = session.get(StudyManifest, study_id)
        if study is None:
            raise RuntimeError("STUDY_NOT_FOUND")
        source_before = protected_counts(session)
        dataset_hash_value = study.dataset_hash
        for window_length in cfg["window_lengths"]:
            resources.append(enforce_resource_guard(cfg, output_root, f"load_window_{window_length}"))
            if dry_run:
                dry_summary.append(
                    dry_run_window_summary(
                        session,
                        study_id,
                        int(window_length),
                        [int(h) for h in cfg["outcome_horizons"]],
                        int(cfg["validation"]["query_sample_per_instrument_window"]),
                    )
                )
                continue
            rows, outcomes = load_rows(session, study_id, int(window_length), [int(h) for h in cfg["outcome_horizons"]])
            queries = select_queries(rows, outcomes, [int(h) for h in cfg["outcome_horizons"]], int(cfg["validation"]["query_sample_per_instrument_window"]))
            dry_summary.append(
                {
                    "window_length": window_length,
                    "loaded_windows": len(rows),
                    "selected_query_windows": len(queries),
                    "query_count_by_asset_class": dict(Counter(row.asset_class for row in queries)),
                    "query_count_by_instrument": dict(Counter(row.symbol for row in queries)),
                }
            )
            for query in queries:
                for horizon in cfg["outcome_horizons"]:
                    actual = outcomes.get((query.id, int(horizon)))
                    if actual is None:
                        continue
                    for arm in cfg["study_arms"]:
                        candidates, counts = eligible_candidates(
                            query,
                            rows,
                            outcomes,
                            int(horizon),
                            arm,
                            int(cfg["validation"]["candidate_sample_limit"]),
                            int(sha256_canonical([cfg["random"]["seed"], query.id, horizon, arm])[:16], 16),
                        )
                        exclusions.append(
                            {
                                "query_window_id": query.id,
                                "symbol": query.symbol,
                                "asset_class": query.asset_class,
                                "window_length": window_length,
                                "horizon": horizon,
                                "study_arm": arm,
                                "eligible_candidate_count": len(candidates),
                                **counts,
                            }
                        )
                        for k in cfg["neighbour_counts"]:
                            for episode_cap in cfg["episode_caps"]:
                                for weighting in cfg["weighting"]:
                                    for method in cfg["similarity_methods"]:
                                        ranked = rank_method(query, candidates, method, int(episode_cap), int(k))
                                        agg = aggregate(ranked, outcomes, int(horizon), weighting, query, None)
                                        if agg is None:
                                            continue
                                        actual_return = float(actual["future_simple_return"])
                                        actual_positive = actual_return > 0.0
                                        evaluations.append(
                                            {
                                                "query_window_id": query.id,
                                                "query_timestamp": query.end.isoformat(),
                                                "symbol": query.symbol,
                                                "asset_class": query.asset_class,
                                                "window_length": window_length,
                                                "horizon": horizon,
                                                "study_arm": arm,
                                                "method": method,
                                                "method_type": "similarity",
                                                "neighbour_count": k,
                                                "episode_cap": episode_cap,
                                                "weighting": weighting,
                                                "eligible_candidate_count": len(candidates),
                                                "actual_return": actual_return,
                                                "actual_positive": actual_positive,
                                                "brier_score": brier(agg["predicted_positive_probability"], actual_positive),
                                                "log_loss": log_loss(agg["predicted_positive_probability"], actual_positive),
                                                "return_absolute_error": abs(agg["expected_return"] - actual_return),
                                                **agg,
                                            }
                                        )
                                        if method in {"shape_euclidean_v1", "shape_dna_context_v2", "episode_diverse_analogue_v1"} and ranked:
                                            all_ranked = rank_method(query, candidates, method, 10**9, min(len(candidates), 200))
                                            for decile_idx, chunk in enumerate(np.array_split(all_ranked, 10), start=1):
                                                chunk_list = list(chunk)
                                                if not chunk_list:
                                                    continue
                                                chunk_returns = [float(outcomes[(row.id, int(horizon))]["future_simple_return"]) for row, _ in chunk_list if (row.id, int(horizon)) in outcomes]
                                                if not chunk_returns:
                                                    continue
                                                deciles.append(
                                                    {
                                                        "method": method,
                                                        "window_length": window_length,
                                                        "horizon": horizon,
                                                        "study_arm": arm,
                                                        "similarity_decile": decile_idx,
                                                        "sample_count": len(chunk_returns),
                                                        "mean_outcome_discrepancy": statistics.fmean(abs(v - actual_return) for v in chunk_returns),
                                                        "median_outcome_discrepancy": statistics.median(abs(v - actual_return) for v in chunk_returns),
                                                        "direction_agreement": statistics.fmean(1.0 if (v > 0) == actual_positive else 0.0 for v in chunk_returns),
                                                        "return_dispersion": float(np.std(chunk_returns, ddof=1)) if len(chunk_returns) > 1 else 0.0,
                                                    }
                                                )
                                    for baseline in cfg["baselines"]:
                                        ranked = baseline_rank(
                                            query,
                                            candidates,
                                            baseline,
                                            int(k),
                                            int(sha256_canonical([cfg["random"]["seed"], query.id, horizon, arm, baseline, k])[:16], 16),
                                        )
                                        agg = aggregate(ranked, outcomes, int(horizon), weighting, query, baseline)
                                        if agg is None:
                                            continue
                                        actual_return = float(actual["future_simple_return"])
                                        actual_positive = actual_return > 0.0
                                        evaluations.append(
                                            {
                                                "query_window_id": query.id,
                                                "query_timestamp": query.end.isoformat(),
                                                "symbol": query.symbol,
                                                "asset_class": query.asset_class,
                                                "window_length": window_length,
                                                "horizon": horizon,
                                                "study_arm": arm,
                                                "method": baseline,
                                                "method_type": "baseline",
                                                "neighbour_count": k,
                                                "episode_cap": episode_cap,
                                                "weighting": weighting,
                                                "eligible_candidate_count": len(candidates),
                                                "actual_return": actual_return,
                                                "actual_positive": actual_positive,
                                                "brier_score": brier(agg["predicted_positive_probability"], actual_positive),
                                                "log_loss": log_loss(agg["predicted_positive_probability"], actual_positive),
                                                "return_absolute_error": abs(agg["expected_return"] - actual_return),
                                                **agg,
                                            }
                                        )
        if dry_run:
            summary = {
                "status": "DRY_RUN",
                "configuration_hash": config_hash,
                "dataset_hash": dataset_hash_value,
                "evaluated_configuration_count": eval_config_count,
                "expected_query_window_count": sum(row["selected_query_windows"] for row in dry_summary),
                "expected_query_horizon_count": sum(row["selected_query_windows"] for row in dry_summary) * len(cfg["outcome_horizons"]),
                "window_summaries": dry_summary,
                "resource_snapshots": resources,
                "source_counts": source_before,
            }
            (output_root / "dry_run.json").write_text(json.dumps(summary, indent=2, sort_keys=True, default=str), encoding="utf-8")
            print(json.dumps(summary, indent=2, sort_keys=True, default=str))
            return 0
        source_after = protected_counts(session)

        grouped: dict[tuple[str, str, int, int, str], list[dict[str, Any]]] = defaultdict(list)
        for row in evaluations:
            grouped[(row["method"], row["study_arm"], int(row["horizon"]), int(row["neighbour_count"]), str(row["weighting"]))].append(row)
        unconditional_briers: dict[tuple[str, int, int, str], float] = {}
        same_context_briers: dict[tuple[str, int, int, str], float] = {}
        for key, rows_for_key in grouped.items():
            method, arm, horizon, k, weighting = key
            if method == "unconditional_outcome_v1":
                unconditional_briers[(arm, horizon, k, weighting)] = statistics.fmean(float(r["brier_score"]) for r in rows_for_key)
            if method == "same_context_random_v1":
                same_context_briers[(arm, horizon, k, weighting)] = statistics.fmean(float(r["brier_score"]) for r in rows_for_key)
        method_summary = []
        pvals = []
        for key, rows_for_key in grouped.items():
            method, arm, horizon, k, weighting = key
            summary = summarize(rows_for_key, unconditional_briers.get((arm, horizon, k, weighting)))
            same_context = same_context_briers.get((arm, horizon, k, weighting))
            summary["brier_skill_vs_same_context_random"] = None if same_context is None else 1.0 - float(summary["brier_score"]) / max(1e-12, same_context)
            skill_samples = [
                1.0 - float(r["brier_score"]) / max(1e-12, unconditional_briers.get((arm, horizon, k, weighting), 0.25))
                for r in rows_for_key
            ]
            pval = p_value_from_skill(skill_samples)
            pvals.append(pval)
            method_summary.append(
                {
                    "method": method,
                    "method_type": rows_for_key[0]["method_type"],
                    "study_arm": arm,
                    "horizon": horizon,
                    "neighbour_count": k,
                    "weighting": weighting,
                    "raw_p_value": pval,
                    **summary,
                }
            )
        adjusted = bh_adjust(pvals)
        for row, adj in zip(method_summary, adjusted, strict=False):
            row["adjusted_p_value"] = adj

        def aggregate_by(keys: list[str]) -> list[dict[str, Any]]:
            buckets: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
            for row in evaluations:
                buckets[tuple(row[key] for key in keys)].append(row)
            out = []
            for bucket, rows_for_bucket in buckets.items():
                base = {key: value for key, value in zip(keys, bucket, strict=False)}
                uncond = [r for r in rows_for_bucket if r["method"] == "unconditional_outcome_v1"]
                baseline_brier = statistics.fmean(float(r["brier_score"]) for r in uncond) if uncond else None
                out.append(base | summarize(rows_for_bucket, baseline_brier))
            return out

        instrument_results = aggregate_by(["symbol", "method", "horizon", "neighbour_count"])
        asset_class_results = aggregate_by(["asset_class", "method", "horizon", "neighbour_count"])
        window_horizon_results = aggregate_by(["window_length", "horizon", "method"])
        episode_diversity = aggregate_by(["method", "study_arm", "neighbour_count"])
        outcome_dispersion = aggregate_by(["method", "study_arm", "horizon"])
        stability = aggregate_by(["method", "neighbour_count"])
        calibration_rows = []
        for (method, arm, horizon, k, weighting), rows_for_key in grouped.items():
            ece, mce, bins = calibration(rows_for_key)
            for bin_row in bins:
                calibration_rows.append({"method": method, "study_arm": arm, "horizon": horizon, "neighbour_count": k, "ece": ece, "mce": mce, **bin_row})
        bootstrap_rows = []
        for row in method_summary:
            rows_for_key = grouped[(row["method"], row["study_arm"], int(row["horizon"]), int(row["neighbour_count"]), row["weighting"])]
            ci = time_block_ci(
                [float(r["brier_score"]) for r in rows_for_key],
                [datetime.fromisoformat(str(r["query_timestamp"])) for r in rows_for_key],
                int(sha256_canonical([cfg["random"]["seed"], row["method"], row["study_arm"], row["horizon"], row["neighbour_count"]])[:16], 16),
                int(cfg["statistics"]["bootstrap_iterations"]),
                float(cfg["statistics"]["confidence_level"]),
            )
            bootstrap_rows.append({"method": row["method"], "study_arm": row["study_arm"], "horizon": row["horizon"], "neighbour_count": row["neighbour_count"], "metric": "brier_score", **ci})

        promising = [
            row for row in method_summary
            if row["method_type"] == "similarity"
            and (row.get("brier_skill_vs_unconditional") or -1) > 0
            and (row.get("brier_skill_vs_same_context_random") or 0) >= 0
            and (row.get("expected_calibration_error") or 1) <= 0.20
            and (row.get("mean_unique_episode_count") or 0) >= min(5, int(row["neighbour_count"]))
        ]
        best = max(
            (row for row in method_summary if row["method_type"] == "similarity"),
            key=lambda row: (
                row.get("brier_skill_vs_unconditional") or -999,
                row.get("brier_skill_vs_same_context_random") or -999,
                -(row.get("return_mae") or 999),
            ),
        )
        if promising:
            decision = "PILOT_RETRIEVAL_PROMISING"
        elif any((row.get("brier_skill_vs_unconditional") or -1) > 0 for row in method_summary if row["method_type"] == "similarity"):
            decision = "PILOT_EPISODE_DIVERSITY_LIMITED"
        else:
            decision = "PILOT_NO_RETRIEVAL_EDGE"

        run = ExperimentRun(
            experiment_code=cfg["experiment"]["code"],
            experiment_version="pilot_validation_v1",
            name=cfg["experiment"]["name"],
            hypothesis="Bounded Yahoo-only historical-as-of retrieval evidence review.",
            status=ExperimentRunStatus.completed.value,
            dataset_hash=dataset_hash_value,
            code_version={"source": "local_and_vps_reconciled", "migration_head": "0011_window_continuity_policy_identity"},
            configuration=cfg,
            configuration_hash=config_hash,
            run_nonce=f"yahoo-pilot-validation-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}",
            similarity_method="bounded_multi_method",
            baseline_methods=cfg["baselines"],
            outcome_set_code="forward_outcomes_v1",
            outcome_set_version="forward_outcomes_v1",
            outcome_horizons=cfg["outcome_horizons"],
            validation_method="anchored_holdout_bounded_historical_as_of_v1",
            validation_configuration=cfg["validation"],
            instrument_scope=sorted({row["symbol"] for row in evaluations}),
            timeframe_scope=[cfg["dataset"]["timeframe"]],
            window_length_scope=cfg["window_lengths"],
            parameter_grid={
                "methods_tested": cfg["similarity_methods"],
                "baselines_tested": cfg["baselines"],
                "neighbour_counts": cfg["neighbour_counts"],
                "episode_caps": cfg["episode_caps"],
                "study_arms": cfg["study_arms"],
                "windows": cfg["window_lengths"],
                "horizons": cfg["outcome_horizons"],
                "evaluated_configuration_count": eval_config_count,
            },
            multiple_testing_family="yahoo_pilot_validation_v1_bounded",
            decision=decision,
            summary={
                "classification": "PILOT_ONLY",
                "required_blocker": "YAHOO_SOURCE_REQUIRES_INDEPENDENT_REPLICATION",
                "evaluation_rows": len(evaluations),
                "best_descriptive_method": best,
                "source_mutation_check": source_before == source_after,
            },
            started_at=datetime.now(UTC) - timedelta(seconds=time.monotonic() - started),
            completed_at=datetime.now(UTC),
            elapsed_seconds=round(time.monotonic() - started, 3),
        )
        session.add(run)
        session.flush()

        report_json = {
            "phase_status": "COMPLETED",
            "experiment_id": run.id,
            "configuration_hash": config_hash,
            "dataset_hash": dataset_hash_value,
            "decision": decision,
            "classification": "PILOT_ONLY",
            "independent_replication_requirement": "YAHOO_SOURCE_REQUIRES_INDEPENDENT_REPLICATION",
            "development_fraction": cfg["validation"]["development_fraction"],
            "validation_fraction": cfg["validation"]["validation_fraction"],
            "evaluated_configuration_count": eval_config_count,
            "evaluation_rows": len(evaluations),
            "best_descriptive_method": best,
            "source_counts_before": source_before,
            "source_counts_after": source_after,
            "source_layer_mutation_check": source_before == source_after,
            "resource_snapshots": resources + [resource_snapshot(output_root)],
            "limitations": [
                "Yahoo-only pilot data; independent replication required.",
                "Deterministic candidate/query sampling used for bounded VPS execution.",
                "No formal final-test lock or out-of-sample support claim.",
            ],
        }
        report_md = [
            "# Yahoo Pilot Validation v1",
            "",
            f"Decision: `{decision}`",
            "",
            "Classification remains `PILOT_ONLY`.",
            "",
            "Required blocker remains `YAHOO_SOURCE_REQUIRES_INDEPENDENT_REPLICATION`.",
            "",
            f"Experiment ID: `{run.id}`",
            f"Configuration hash: `{config_hash}`",
            f"Dataset hash: `{dataset_hash_value}`",
            "",
            "No final-test lock, final test, model training, trading signal, or execution logic was run.",
            "",
            "## Best descriptive method",
            "",
            json.dumps(best, indent=2, sort_keys=True, default=str),
            "",
            "## Source-layer mutation check",
            "",
            f"Protected counts unchanged: `{source_before == source_after}`",
        ]

        artifacts = {
            "report.json": report_json,
            "experiment_config.json": cfg,
            "pilot_decision.json": {"decision": decision, "classification": "PILOT_ONLY", "required_blocker": "YAHOO_SOURCE_REQUIRES_INDEPENDENT_REPLICATION"},
        }
        (output_root / "report.md").write_text("\n".join(report_md), encoding="utf-8")
        for name, payload in artifacts.items():
            (output_root / name).write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")
        write_csv(output_root / "method_summary.csv", method_summary)
        write_csv(output_root / "baseline_summary.csv", [row for row in method_summary if row["method_type"] == "baseline"])
        write_csv(output_root / "instrument_results.csv", instrument_results)
        write_csv(output_root / "asset_class_results.csv", asset_class_results)
        write_csv(output_root / "window_horizon_results.csv", window_horizon_results)
        write_csv(output_root / "episode_diversity.csv", episode_diversity)
        write_csv(output_root / "retrieval_stability.csv", stability)
        write_csv(output_root / "outcome_dispersion.csv", outcome_dispersion)
        write_csv(output_root / "calibration.csv", calibration_rows)
        write_csv(output_root / "bootstrap_confidence.csv", bootstrap_rows)
        write_csv(output_root / "statistical_comparisons.csv", method_summary)
        write_csv(output_root / "multiple_testing.csv", method_summary)
        write_csv(output_root / "query_exclusion_summary.csv", exclusions)
        write_csv(output_root / "similarity_deciles.csv", deciles)
        write_csv(output_root / "resource_usage.csv", resources + [resource_snapshot(output_root)])
        for path in output_root.iterdir():
            if path.is_file():
                content = path.read_text(encoding="utf-8", errors="replace")
                session.add(
                    ExperimentArtifact(
                        experiment_run_id=run.id,
                        artifact_type=path.suffix.lstrip(".") or "text",
                        name=path.name,
                        content=content,
                        artifact_metadata={"path": str(path)},
                        artifact_hash=sha256_canonical(content),
                    )
                )
        session.commit()
        print(json.dumps(report_json, indent=2, sort_keys=True, default=str))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("config", type=Path)
    parser.add_argument("--output-root", type=Path, default=Path("/opt/market-genome/reports/yahoo_pilot_validation_v1"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    os.environ.setdefault("PYTHONHASHSEED", "0")
    return run_validation(args.config, args.output_root, args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
