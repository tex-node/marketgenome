"""Phase 1 Step 10A.3 -- confirmatory independent (non-Yahoo) replication runner.

Narrow by design: evaluates exactly the frozen primary configuration
(dna_robust_cosine_v1, same_instrument, K=10, uniform weighting, episode cap=1,
horizon=20) plus four frozen controls, against an independently sourced dataset.
Do not add methods, horizons, or K values here without re-freezing the protocol --
that would turn a confirmatory test back into an exploratory search.

Mirrors the proven structure of scripts/run_yahoo_pilot_validation.py (same Row/
load_rows/eligible_candidates/rank_method/aggregate/calibration/bootstrap plumbing)
so the algorithm under test is identical; only the dataset differs.
"""
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
from market_genome_replication.service import ReplicationService, classify_replication_decision
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
    dna_vector: np.ndarray
    robust_dna_vector: np.ndarray
    context: dict[str, str | None]
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
    snap["status"] = "PASSED" if not reasons else "INDEPENDENT_REPLICATION_PAUSED_RESOURCE_GUARD"
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


def calibration(rows: list[dict[str, Any]], bins: int = 10) -> tuple[float, float, list[dict[str, Any]]]:
    if not rows:
        return 0.0, 0.0, []
    out = []
    ece = 0.0
    mce = 0.0
    for idx in range(bins):
        low, high = idx / bins, (idx + 1) / bins
        members = [r for r in rows if low <= float(r["predicted_positive_probability"]) < high or (idx == bins - 1 and float(r["predicted_positive_probability"]) == 1.0)]
        if not members:
            out.append({"bin": idx, "count": 0})
            continue
        mean_p = statistics.fmean(float(r["predicted_positive_probability"]) for r in members)
        observed = statistics.fmean(1.0 if r["actual_positive"] else 0.0 for r in members)
        gap = abs(mean_p - observed)
        ece += len(members) / len(rows) * gap
        mce = max(mce, gap)
        out.append({"bin": idx, "count": len(members), "mean_predicted_probability": mean_p, "observed_frequency": observed})
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
          pw.id::text as id, pw.instrument_id::text as instrument_id, pw.timeframe_id::text as timeframe_id,
          i.symbol, i.asset_class, pw.window_length, pw.start_timestamp, pw.end_timestamp,
          np.normalized_values, md.feature_values, md.feature_vector,
          mc.trend_state, mc.volatility_state, mc.volatility_phase_state, mc.persistence_state,
          mc.activity_state, mc.shock_state, mc.market_phase_state,
          coalesce(
            (select se.episode_id from study_episodes se
             where se.study_id = :study_id and se.instrument_id = pw.instrument_id
               and se.timeframe_id = pw.timeframe_id
               and pw.end_timestamp between se.episode_start and se.episode_end
             order by se.episode_start desc limit 1),
            i.symbol || ':' || to_char(pw.end_timestamp, 'YYYY-MM')
          ) as episode_id
        from pattern_windows pw
        join instruments i on i.id = pw.instrument_id
        join normalized_patterns np on np.pattern_window_id = pw.id
        join market_dna md on md.pattern_window_id = pw.id
        left join market_contexts mc on mc.pattern_window_id = pw.id
        where pw.instrument_id = any(:instrument_ids) and pw.timeframe_id = any(:timeframe_ids)
          and pw.window_length = :window_length
        order by pw.end_timestamp, pw.id
        """
    )
    db_rows = session.execute(
        sql, {"study_id": study_id, "instrument_ids": instrument_ids, "timeframe_ids": timeframe_ids, "window_length": window_length}
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
                episode_id=item["episode_id"],
            )
        )
    outcome_sql = text(
        """
        select oo.pattern_window_id::text as window_id, oo.horizon_bars, oo.future_simple_return
        from outcome_observations oo
        join pattern_windows pw on pw.id = oo.pattern_window_id
        where pw.instrument_id = any(:instrument_ids) and pw.timeframe_id = any(:timeframe_ids)
          and pw.window_length = :window_length and oo.horizon_bars = any(:horizons) and oo.is_complete is true
        """
    )
    outcomes = {
        (item["window_id"], int(item["horizon_bars"])): dict(item)
        for item in session.execute(
            outcome_sql, {"instrument_ids": instrument_ids, "timeframe_ids": timeframe_ids, "window_length": window_length, "horizons": horizons}
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


def eligible_candidates(query: Row, rows: list[Row], outcomes: dict[tuple[str, int], dict[str, Any]], horizon: int, limit: int, seed: int) -> tuple[list[Row], Counter]:
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
        if row.instrument_id != query.instrument_id:
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


def cosine_distance(query: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    denom = np.linalg.norm(matrix, axis=1) * max(float(np.linalg.norm(query)), 1e-12)
    cosine = np.clip((matrix @ query) / np.maximum(denom, 1e-12), -1.0, 1.0)
    return 1.0 - cosine


def rank_method(query: Row, candidates: list[Row], method: str, episode_cap: int, k: int) -> list[tuple[Row, float]]:
    if not candidates:
        return []
    if method == "shape_euclidean_v1":
        dist = shape_euclidean(query, candidates)
    elif method == "dna_cosine_v1":
        matrix = np.vstack([row.dna_vector for row in candidates])
        dist = cosine_distance(query.dna_vector, matrix)
    elif method == "dna_robust_cosine_v1":
        matrix = np.vstack([row.robust_dna_vector for row in candidates])
        dist = cosine_distance(query.robust_dna_vector, matrix)
    else:
        raise ValueError(f"UNSUPPORTED_METHOD:{method}")
    ordered = sorted(zip(candidates, dist, strict=False), key=lambda item: (float(item[1]), item[0].end, item[0].id))
    counts: Counter = Counter()
    selected = []
    for row, distance in ordered:
        if counts[row.episode_id] >= episode_cap:
            continue
        counts[row.episode_id] += 1
        selected.append((row, float(distance)))
        if len(selected) >= k:
            break
    return selected


def baseline_rank(query: Row, candidates: list[Row], baseline: str, k: int, seed: int) -> list[tuple[Row, float]]:
    filtered = list(candidates)
    if baseline == "same_context_random_v1":
        filtered = [
            row for row in filtered
            if row.context.get("trend_state") == query.context.get("trend_state")
            and row.context.get("volatility_state") == query.context.get("volatility_state")
        ]
    rng = random.Random(seed)
    rng.shuffle(filtered)
    if baseline == "unconditional_outcome_v1":
        filtered = sorted(filtered, key=lambda row: (row.end, row.id))
    return [(row, float(rank)) for rank, row in enumerate(filtered[:k], start=1)]


def aggregate(ranked: list[tuple[Row, float]], outcomes: dict[tuple[str, int], dict[str, Any]], horizon: int) -> dict[str, Any] | None:
    rows = [(row, outcomes[(row.id, horizon)]) for row, _ in ranked if (row.id, horizon) in outcomes]
    if not rows:
        return None
    returns = np.asarray([float(outcome["future_simple_return"]) for _, outcome in rows], dtype=np.float64)
    prob_pos = float(np.mean(returns > 0))
    episode_counts = Counter(row.episode_id for row, _ in rows)
    top_counts = sorted(episode_counts.values(), reverse=True)
    return {
        "predicted_positive_probability": prob_pos,
        "expected_return": float(np.mean(returns)),
        "unique_episode_count": len(episode_counts),
        "largest_episode_share": (top_counts[0] / len(rows)) if rows else 0.0,
        "retrieved_match_count": len(rows),
    }


def summarize(group_rows: list[dict[str, Any]], baseline_brier: float | None) -> dict[str, Any]:
    if not group_rows:
        return {}
    briers = [float(r["brier_score"]) for r in group_rows]
    ece, _, _ = calibration(group_rows)
    own_brier = statistics.fmean(briers)
    return {
        "sample_count": len(group_rows),
        "brier_score": own_brier,
        "brier_skill_vs_unconditional": None if baseline_brier is None else 1.0 - own_brier / max(1e-12, baseline_brier),
        "log_loss": statistics.fmean(float(r["log_loss"]) for r in group_rows),
        "return_mae": statistics.fmean(float(r["return_absolute_error"]) for r in group_rows),
        "median_absolute_return_error": statistics.median(float(r["return_absolute_error"]) for r in group_rows),
        "direction_accuracy": statistics.fmean(
            1.0 if (float(r["predicted_positive_probability"]) >= 0.5) == bool(r["actual_positive"]) else 0.0 for r in group_rows
        ),
        "expected_calibration_error": ece,
        "mean_unique_episode_count": statistics.fmean(float(r["unique_episode_count"]) for r in group_rows),
        "mean_largest_episode_share": statistics.fmean(float(r["largest_episode_share"]) for r in group_rows),
    }


def load_yahoo_baseline_metrics(session, source_experiment_id: str) -> dict[str, Any] | None:
    artifact = (
        session.query(ExperimentArtifact)
        .filter(ExperimentArtifact.experiment_run_id == source_experiment_id, ExperimentArtifact.name == "method_summary.csv")
        .one_or_none()
    )
    if artifact is None:
        return None
    reader = csv.DictReader(artifact.content.splitlines())
    for row in reader:
        if row.get("method") == "dna_robust_cosine_v1" and row.get("study_arm") == "same_instrument" and row.get("horizon") == "20" and row.get("neighbour_count") == "10":
            return row
    return None


def run_replication(config_path: Path, output_root: Path, dry_run: bool) -> int:
    cfg = load_yaml(config_path)
    output_root.mkdir(parents=True, exist_ok=True)
    resources = [enforce_resource_guard(cfg, output_root, "start")]
    started = time.monotonic()
    config_hash = sha256_canonical(cfg)
    primary = cfg["primary"]
    horizon = int(cfg["outcome_horizons"][0])
    k = int(primary["neighbour_count"])
    episode_cap = int(primary["episode_cap"])
    methods = [primary["method"], *[m for m in cfg["controls"] if m in {"dna_cosine_v1", "shape_euclidean_v1"}]]
    baselines = [m for m in cfg["controls"] if m in {"unconditional_outcome_v1", "same_context_random_v1"}]

    with SessionLocal() as session:
        replication_service = ReplicationService(session)
        protocol = replication_service.freeze_protocol(
            cfg["replication"]["protocol_code"], cfg["replication"]["source_experiment_id"]
        )

        study = session.query(StudyManifest).filter(StudyManifest.name == "independent_robust_dna_replication_v1").order_by(StudyManifest.created_at.desc()).first()
        if study is None:
            raise RuntimeError("INDEPENDENT_STUDY_NOT_FOUND")
        study_id = study.id
        source_before = protected_counts(session)
        dataset_hash_value = study.dataset_hash

        evaluations: list[dict[str, Any]] = []
        dry_summary: list[dict[str, Any]] = []
        for window_length in cfg["window_lengths"]:
            resources.append(enforce_resource_guard(cfg, output_root, f"load_window_{window_length}"))
            rows, outcomes = load_rows(session, study_id, int(window_length), [horizon])
            queries = select_queries(rows, outcomes, [horizon], int(cfg["validation"]["query_sample_per_instrument_window"]))
            dry_summary.append(
                {
                    "window_length": window_length,
                    "loaded_windows": len(rows),
                    "selected_query_windows": len(queries),
                    "query_count_by_asset_class": dict(Counter(row.asset_class for row in queries)),
                    "query_count_by_instrument": dict(Counter(row.symbol for row in queries)),
                }
            )
            if dry_run:
                continue
            for query in queries:
                actual = outcomes.get((query.id, horizon))
                if actual is None:
                    continue
                candidates, _counts = eligible_candidates(
                    query, rows, outcomes, horizon, int(cfg["validation"]["candidate_sample_limit"]),
                    int(sha256_canonical([cfg["random"]["seed"], query.id, horizon])[:16], 16),
                )
                actual_return = float(actual["future_simple_return"])
                actual_positive = actual_return > 0.0
                for method in methods:
                    ranked = rank_method(query, candidates, method, episode_cap, k)
                    agg = aggregate(ranked, outcomes, horizon)
                    if agg is None:
                        continue
                    evaluations.append(
                        {
                            "query_window_id": query.id, "query_timestamp": query.end.isoformat(), "symbol": query.symbol,
                            "asset_class": query.asset_class, "window_length": window_length, "method": method,
                            "method_type": "primary" if method == primary["method"] else "control_similarity",
                            "actual_return": actual_return, "actual_positive": actual_positive,
                            "brier_score": brier(agg["predicted_positive_probability"], actual_positive),
                            "log_loss": log_loss(agg["predicted_positive_probability"], actual_positive),
                            "return_absolute_error": abs(agg["expected_return"] - actual_return),
                            **agg,
                        }
                    )
                for baseline in baselines:
                    ranked = baseline_rank(
                        query, candidates, baseline, k,
                        int(sha256_canonical([cfg["random"]["seed"], query.id, horizon, baseline])[:16], 16),
                    )
                    agg = aggregate(ranked, outcomes, horizon)
                    if agg is None:
                        continue
                    evaluations.append(
                        {
                            "query_window_id": query.id, "query_timestamp": query.end.isoformat(), "symbol": query.symbol,
                            "asset_class": query.asset_class, "window_length": window_length, "method": baseline,
                            "method_type": "control_baseline",
                            "actual_return": actual_return, "actual_positive": actual_positive,
                            "brier_score": brier(agg["predicted_positive_probability"], actual_positive),
                            "log_loss": log_loss(agg["predicted_positive_probability"], actual_positive),
                            "return_absolute_error": abs(agg["expected_return"] - actual_return),
                            **agg,
                        }
                    )

        if dry_run:
            summary = {
                "status": "DRY_RUN", "configuration_hash": config_hash, "dataset_hash": dataset_hash_value,
                "window_summaries": dry_summary, "resource_snapshots": resources, "source_counts": source_before,
                "protocol_id": protocol.id, "protocol_status": protocol.status,
            }
            (output_root / "dry_run.json").write_text(json.dumps(summary, indent=2, sort_keys=True, default=str), encoding="utf-8")
            print(json.dumps(summary, indent=2, sort_keys=True, default=str))
            return 0

        instrument_universe = sorted({row["symbol"] for row in evaluations})
        lock = replication_service.create_lock(
            protocol.id, study_id=study_id, source_study_id=cfg["replication"]["source_study_id"],
            dataset_hash=dataset_hash_value, provider_code=cfg["dataset"]["provider"],
            provider_provenance_hash=sha256_canonical({"provider": cfg["dataset"]["provider"], "dataset_hash": dataset_hash_value}),
            instrument_universe=instrument_universe,
            date_range={"start": min(row["query_timestamp"] for row in evaluations), "end": max(row["query_timestamp"] for row in evaluations)},
        )
        record = replication_service.create_record(lock.id, provider_independence="CONFIRMED")

        source_after = protected_counts(session)

        grouped: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
        for row in evaluations:
            grouped[(row["method"], int(row["window_length"]))].append(row)
        unconditional_briers: dict[int, float] = {}
        same_context_briers: dict[int, float] = {}
        for (method, window_length), rows_for_key in grouped.items():
            if method == "unconditional_outcome_v1":
                unconditional_briers[window_length] = statistics.fmean(float(r["brier_score"]) for r in rows_for_key)
            if method == "same_context_random_v1":
                same_context_briers[window_length] = statistics.fmean(float(r["brier_score"]) for r in rows_for_key)

        window_horizon_results = []
        pvals = []
        for (method, window_length), rows_for_key in grouped.items():
            summary = summarize(rows_for_key, unconditional_briers.get(window_length))
            same_context = same_context_briers.get(window_length)
            summary["brier_skill_vs_same_context_random"] = None if same_context is None else 1.0 - float(summary["brier_score"]) / max(1e-12, same_context)
            skill_samples = [1.0 - float(r["brier_score"]) / max(1e-12, unconditional_briers.get(window_length, 0.25)) for r in rows_for_key]
            pval = p_value_from_skill(skill_samples)
            pvals.append(pval)
            window_horizon_results.append({"method": method, "window_length": window_length, "raw_p_value": pval, **summary})
        adjusted = bh_adjust(pvals)
        for row, adj in zip(window_horizon_results, adjusted, strict=False):
            row["adjusted_p_value"] = adj

        # Frozen aggregate: pool across window_lengths 16/32/64 with equal weight per
        # query, in addition to the per-window breakdown above (section 30).
        pooled: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in evaluations:
            pooled[row["method"]].append(row)
        pooled_unconditional_brier = statistics.fmean(float(r["brier_score"]) for r in pooled.get("unconditional_outcome_v1", [])) if pooled.get("unconditional_outcome_v1") else None
        pooled_same_context_brier = statistics.fmean(float(r["brier_score"]) for r in pooled.get("same_context_random_v1", [])) if pooled.get("same_context_random_v1") else None
        pooled_summary = {}
        for method, rows_for_method in pooled.items():
            summary = summarize(rows_for_method, pooled_unconditional_brier)
            summary["brier_skill_vs_same_context_random"] = (
                None if pooled_same_context_brier is None else 1.0 - float(summary["brier_score"]) / max(1e-12, pooled_same_context_brier)
            )
            pooled_summary[method] = summary

        instrument_results = []
        for symbol in instrument_universe:
            for method, rows_for_method in pooled.items():
                subset = [r for r in rows_for_method if r["symbol"] == symbol]
                if not subset:
                    continue
                baseline_brier = statistics.fmean(float(r["brier_score"]) for r in pooled.get("unconditional_outcome_v1", []) if r["symbol"] == symbol) if any(r["symbol"] == symbol for r in pooled.get("unconditional_outcome_v1", [])) else None
                instrument_results.append({"symbol": symbol, "method": method, **summarize(subset, baseline_brier)})
        asset_class_results = []
        for asset_class in sorted({row["asset_class"] for row in evaluations}):
            for method, rows_for_method in pooled.items():
                subset = [r for r in rows_for_method if r["asset_class"] == asset_class]
                if not subset:
                    continue
                asset_class_results.append({"asset_class": asset_class, "method": method, **summarize(subset, pooled_unconditional_brier)})

        primary_pooled = pooled_summary.get(primary["method"], {})
        primary_by_instrument = [r for r in instrument_results if r["method"] == primary["method"]]
        single_instrument_dependent = False
        if len(primary_by_instrument) > 1:
            skills = sorted((r.get("brier_skill_vs_unconditional") or -999 for r in primary_by_instrument), reverse=True)
            single_instrument_dependent = skills[0] > 0 and all(s <= 0 for s in skills[1:])
        primary_rows = pooled.get(primary["method"], [])
        bootstrap_ci = time_block_ci(
            [float(r["brier_score"]) for r in primary_rows],
            [datetime.fromisoformat(str(r["query_timestamp"])) for r in primary_rows],
            int(sha256_canonical([cfg["random"]["seed"], primary["method"]])[:16], 16),
            int(cfg["statistics"]["bootstrap_iterations"]), float(cfg["statistics"]["confidence_level"]),
        )
        bootstrap_ci_low_skill = None
        if bootstrap_ci["low"] is not None and pooled_unconditional_brier:
            bootstrap_ci_low_skill = 1.0 - bootstrap_ci["high"] / max(1e-12, pooled_unconditional_brier)

        yahoo_baseline = load_yahoo_baseline_metrics(session, cfg["replication"]["source_experiment_id"])
        sufficient_evidence = len(primary_rows) >= 30 and len(instrument_universe) >= 3

        decision_result = classify_replication_decision(
            brier_skill_vs_unconditional=primary_pooled.get("brier_skill_vs_unconditional"),
            brier_skill_vs_same_context_random=primary_pooled.get("brier_skill_vs_same_context_random"),
            effect_direction_consistent=(primary_pooled.get("brier_skill_vs_unconditional") or -1) > 0,
            adequate_episode_diversity=(primary_pooled.get("mean_unique_episode_count") or 0) >= min(5, k),
            single_instrument_dependent=single_instrument_dependent,
            acceptable_calibration=(primary_pooled.get("expected_calibration_error") or 1.0) <= 0.20,
            bootstrap_ci_low=bootstrap_ci_low_skill,
            provider_independence="CONFIRMED",
            sufficient_evidence=sufficient_evidence,
        )

        comparison = {
            "yahoo_brier_skill_vs_unconditional": float(yahoo_baseline["brier_skill_vs_unconditional"]) if yahoo_baseline and yahoo_baseline.get("brier_skill_vs_unconditional") not in (None, "") else None,
            "independent_brier_skill_vs_unconditional": primary_pooled.get("brier_skill_vs_unconditional"),
            "yahoo_direction_accuracy": float(yahoo_baseline["direction_accuracy"]) if yahoo_baseline and yahoo_baseline.get("direction_accuracy") not in (None, "") else None,
            "independent_direction_accuracy": primary_pooled.get("direction_accuracy"),
        }

        run = ExperimentRun(
            experiment_code=cfg["experiment"]["code"], experiment_version="replication_v1", name=cfg["experiment"]["name"],
            hypothesis=protocol.hypothesis_text, status=ExperimentRunStatus.completed.value, dataset_hash=dataset_hash_value,
            code_version={"source": "local_and_vps_reconciled"}, configuration=cfg, configuration_hash=config_hash,
            run_nonce=f"independent-replication-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}",
            similarity_method=primary["method"], baseline_methods=baselines,
            outcome_set_code="forward_outcomes_v1", outcome_set_version="forward_outcomes_v1", outcome_horizons=[horizon],
            validation_method="anchored_holdout_bounded_historical_as_of_v1", validation_configuration=cfg["validation"],
            instrument_scope=instrument_universe, timeframe_scope=[cfg["dataset"]["timeframe"]], window_length_scope=cfg["window_lengths"],
            parameter_grid={"primary": primary, "controls": cfg["controls"], "windows": cfg["window_lengths"], "horizon": horizon},
            multiple_testing_family="independent_replication_v1_primary_and_controls", decision=decision_result.decision,
            summary={"classification": "CONFIRMATORY_REPLICATION", "protocol_id": protocol.id, "lock_id": lock.id, "record_id": record.id, "source_mutation_check": source_before == source_after},
            started_at=datetime.now(UTC) - timedelta(seconds=time.monotonic() - started), completed_at=datetime.now(UTC),
            elapsed_seconds=round(time.monotonic() - started, 3),
        )
        session.add(run)
        session.flush()

        replication_service.decide(
            record.id, replication_experiment_id=run.id, decision=decision_result.decision,
            decision_rationale=decision_result.rationale, comparison=comparison,
        )

        report_json = {
            "phase_status": "INDEPENDENT_REPLICATION_COMPLETED", "experiment_id": run.id, "protocol_id": protocol.id,
            "lock_id": lock.id, "record_id": record.id, "configuration_hash": config_hash, "dataset_hash": dataset_hash_value,
            "decision": decision_result.decision, "decision_rationale": decision_result.rationale,
            "primary_pooled_metrics": primary_pooled, "per_window_length": window_horizon_results,
            "per_instrument": instrument_results, "per_asset_class": asset_class_results, "comparison_vs_yahoo": comparison,
            "instrument_universe": instrument_universe, "evaluation_rows": len(evaluations),
            "source_counts_before": source_before, "source_counts_after": source_after,
            "source_layer_mutation_check": source_before == source_after,
            "resource_snapshots": resources + [resource_snapshot(output_root)],
            "final_test_lock": "NO", "trading_logic": "NO", "ai_ml_model": "NO",
        }
        report_md = [
            "# Independent (Alpha Vantage) Replication v1", "", f"Decision: `{decision_result.decision}`", "",
            decision_result.rationale, "", f"Experiment ID: `{run.id}`", f"Protocol ID: `{protocol.id}`", f"Lock ID: `{lock.id}`",
            f"Configuration hash: `{config_hash}`", f"Dataset hash: `{dataset_hash_value}`", "",
            "No final-test lock, final test, model training, trading signal, or execution logic was run.", "",
            "## Primary pooled result", "", json.dumps(primary_pooled, indent=2, sort_keys=True, default=str), "",
            "## Comparison vs Yahoo pilot", "", json.dumps(comparison, indent=2, sort_keys=True, default=str), "",
            "## Source-layer mutation check", "", f"Protected counts unchanged: `{source_before == source_after}`",
        ]
        (output_root / "report.md").write_text("\n".join(report_md), encoding="utf-8")
        artifacts = {
            "report.json": report_json, "replication_protocol.json": protocol.configuration,
            "replication_decision.json": {"decision": decision_result.decision, "rationale": decision_result.rationale},
        }
        for name, payload in artifacts.items():
            (output_root / name).write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")
        write_csv(output_root / "primary_replication_metrics.csv", [{"method": primary["method"], **primary_pooled}])
        write_csv(output_root / "window_horizon_results.csv", window_horizon_results)
        write_csv(output_root / "instrument_summary.csv", instrument_results)
        write_csv(output_root / "asset_class_summary.csv", asset_class_results)
        write_csv(output_root / "yahoo_vs_replication.csv", [comparison])
        write_csv(output_root / "resource_usage.csv", resources + [resource_snapshot(output_root)])
        for path in output_root.iterdir():
            if path.is_file():
                content = path.read_text(encoding="utf-8", errors="replace")
                session.add(
                    ExperimentArtifact(
                        experiment_run_id=run.id, artifact_type=path.suffix.lstrip(".") or "text", name=path.name,
                        content=content, artifact_metadata={"path": str(path)}, artifact_hash=sha256_canonical(content),
                    )
                )
        session.commit()
        print(json.dumps(report_json, indent=2, sort_keys=True, default=str))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("config", type=Path)
    parser.add_argument("--output-root", type=Path, default=Path("/opt/market-genome/reports/independent_robust_dna_replication_v1"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    os.environ.setdefault("PYTHONHASHSEED", "0")
    return run_replication(args.config, args.output_root, args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
