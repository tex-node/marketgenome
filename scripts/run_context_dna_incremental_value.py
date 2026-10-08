"""Phase 1 Step 10A.4 -- context signal isolation and Market DNA incremental-value test.

Deliberately narrow, FOLLOW_UP_CONFIRMATORY_DIAGNOSTIC on the already-prepared independent
(Alpha Vantage) dataset from Step 10A.3. No new data acquisition, no new similarity method,
no parameter search. The primary comparison is no longer "DNA vs random history" -- it is
"DNA similarity within a matched context" vs "random sampling from that same matched context",
so that DNA cannot appear useful merely because its features indirectly re-encode context.
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
from market_genome_replication.context_dna_analysis import (
    CONTEXT_DNA_DECISIONS,
    CandidateUniverseMismatchError,
    assert_candidate_universe_equality,
    classify_candidate_sufficiency,
    classify_context_dna_decision,
    context_dimensions_for,
    deterministic_context_random_draws,
    filter_by_context,
    information_layer_table,
    paired_block_bootstrap,
)
from market_genome_replication.service import ReplicationService
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
    window_length: int
    start: datetime
    end: datetime
    robust_dna_vector: np.ndarray
    context: dict[str, Any]
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
    snap["status"] = "PASSED" if not reasons else "CONTEXT_DNA_TEST_PAUSED_RESOURCE_GUARD"
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


def calibration(rows: list[dict[str, Any]], bins: int = 10) -> tuple[float, float]:
    if not rows:
        return 0.0, 0.0
    ece = 0.0
    mce = 0.0
    for idx in range(bins):
        low, high = idx / bins, (idx + 1) / bins
        members = [r for r in rows if low <= float(r["predicted_positive_probability"]) < high or (idx == bins - 1 and float(r["predicted_positive_probability"]) == 1.0)]
        if not members:
            continue
        mean_p = statistics.fmean(float(r["predicted_positive_probability"]) for r in members)
        observed = statistics.fmean(1.0 if r["actual_positive"] else 0.0 for r in members)
        gap = abs(mean_p - observed)
        ece += len(members) / len(rows) * gap
        mce = max(mce, gap)
    return float(ece), float(mce)


def protected_counts(session) -> dict[str, int]:
    return {table: int(session.execute(text(f"select count(*) from {table}")).scalar_one()) for table in PROTECTED_TABLES}


def load_rows(session, study_id: str, window_length: int, horizon: int) -> tuple[list[Row], dict[str, dict[str, Any]]]:
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
          pw.id::text as id, pw.instrument_id::text as instrument_id, i.symbol, i.asset_class,
          pw.window_length, pw.start_timestamp, pw.end_timestamp,
          md.feature_values, md.feature_vector,
          mc.trend_state, mc.volatility_state, mc.volatility_phase_state, mc.persistence_state,
          mc.activity_state, mc.shock_state, mc.market_phase_state, mc.context_family_code,
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
                window_length=int(item["window_length"]),
                start=item["start_timestamp"],
                end=item["end_timestamp"],
                robust_dna_vector=robust,
                context={
                    "trend_state": item["trend_state"],
                    "volatility_state": item["volatility_state"],
                    "volatility_phase_state": item["volatility_phase_state"],
                    "persistence_state": item["persistence_state"],
                    "activity_state": item["activity_state"],
                    "shock_state": item["shock_state"],
                    "market_phase_state": item["market_phase_state"],
                    "context_family_code": item["context_family_code"],
                },
                episode_id=item["episode_id"],
            )
        )
    outcome_sql = text(
        """
        select oo.pattern_window_id::text as window_id, oo.future_simple_return
        from outcome_observations oo
        join pattern_windows pw on pw.id = oo.pattern_window_id
        where pw.instrument_id = any(:instrument_ids) and pw.timeframe_id = any(:timeframe_ids)
          and pw.window_length = :window_length and oo.horizon_bars = :horizon and oo.is_complete is true
        """
    )
    outcomes = {
        item["window_id"]: dict(item)
        for item in session.execute(
            outcome_sql, {"instrument_ids": instrument_ids, "timeframe_ids": timeframe_ids, "window_length": window_length, "horizon": horizon}
        ).mappings()
    }
    return rows, outcomes


def select_queries(rows: list[Row], outcomes: dict[str, dict[str, Any]], per_instrument: int) -> list[Row]:
    by_key: dict[str, list[Row]] = defaultdict(list)
    for row in rows:
        if row.id in outcomes:
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


def eligible_candidates(query: Row, rows: list[Row], outcomes: dict[str, dict[str, Any]], horizon: int, limit: int, seed: int) -> tuple[list[Row], Counter]:
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
        if row.id not in outcomes:
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


def cosine_distance(query: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    denom = np.linalg.norm(matrix, axis=1) * max(float(np.linalg.norm(query)), 1e-12)
    cosine = np.clip((matrix @ query) / np.maximum(denom, 1e-12), -1.0, 1.0)
    return 1.0 - cosine


def rank_dna(query: Row, candidates: list[Row], episode_cap: int, k: int) -> list[Row]:
    if not candidates:
        return []
    matrix = np.vstack([row.robust_dna_vector for row in candidates])
    dist = cosine_distance(query.robust_dna_vector, matrix)
    ordered = sorted(zip(candidates, dist, strict=False), key=lambda item: (float(item[1]), item[0].end, item[0].id))
    counts: Counter = Counter()
    selected = []
    for row, _distance in ordered:
        if counts[row.episode_id] >= episode_cap:
            continue
        counts[row.episode_id] += 1
        selected.append(row)
        if len(selected) >= k:
            break
    return selected


def aggregate(selected_ids: list[str], by_id: dict[str, Row], outcomes: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    returns = [float(outcomes[i]["future_simple_return"]) for i in selected_ids if i in outcomes]
    if not returns:
        return None
    arr = np.asarray(returns, dtype=np.float64)
    episode_counts = Counter(by_id[i].episode_id for i in selected_ids if i in by_id)
    top = sorted(episode_counts.values(), reverse=True)
    return {
        "predicted_positive_probability": float(np.mean(arr > 0)),
        "expected_return": float(np.mean(arr)),
        "unique_episode_count": len(episode_counts),
        "largest_episode_share": (top[0] / len(returns)) if returns else 0.0,
        "return_std": float(np.std(arr, ddof=1)) if len(arr) > 1 else 0.0,
    }


def evaluate(agg: dict[str, Any], actual_return: float, actual_positive: bool) -> dict[str, Any]:
    return {
        "brier_score": brier(agg["predicted_positive_probability"], actual_positive),
        "log_loss": log_loss(agg["predicted_positive_probability"], actual_positive),
        "return_absolute_error": abs(agg["expected_return"] - actual_return),
        "predicted_positive_probability": agg["predicted_positive_probability"],
        "actual_positive": actual_positive,
        "unique_episode_count": agg["unique_episode_count"],
        "largest_episode_share": agg["largest_episode_share"],
        "return_std": agg["return_std"],
    }


def context_random_estimate(
    within_context_ids: list[str], by_id: dict[str, Row], outcomes: dict[str, dict[str, Any]], k: int, repetitions: int, seed_base: int
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    draws = deterministic_context_random_draws(within_context_ids, k=k, repetitions=repetitions, seed_base=seed_base)
    per_repetition = []
    for draw in draws:
        agg = aggregate(draw, by_id, outcomes)
        if agg is not None:
            per_repetition.append(agg)
    if not per_repetition:
        return {}, []
    mean_agg = {
        "predicted_positive_probability": statistics.fmean(a["predicted_positive_probability"] for a in per_repetition),
        "expected_return": statistics.fmean(a["expected_return"] for a in per_repetition),
        "unique_episode_count": statistics.fmean(a["unique_episode_count"] for a in per_repetition),
        "largest_episode_share": statistics.fmean(a["largest_episode_share"] for a in per_repetition),
        "return_std": statistics.fmean(a["return_std"] for a in per_repetition),
    }
    return mean_agg, per_repetition


def summarize(rows_for_group: list[dict[str, Any]], baseline_brier: float | None) -> dict[str, Any]:
    if not rows_for_group:
        return {}
    briers = [float(r["brier_score"]) for r in rows_for_group]
    ece, mce = calibration(rows_for_group)
    own_brier = statistics.fmean(briers)
    return {
        "sample_count": len(rows_for_group),
        "brier_score": own_brier,
        "brier_skill_vs_prior": None if baseline_brier is None else 1.0 - own_brier / max(1e-12, baseline_brier),
        "log_loss": statistics.fmean(float(r["log_loss"]) for r in rows_for_group),
        "return_mae": statistics.fmean(float(r["return_absolute_error"]) for r in rows_for_group),
        "direction_accuracy": statistics.fmean(
            1.0 if (float(r["predicted_positive_probability"]) >= 0.5) == bool(r["actual_positive"]) else 0.0 for r in rows_for_group
        ),
        "expected_calibration_error": ece,
        "maximum_calibration_error": mce,
        "mean_unique_episode_count": statistics.fmean(float(r["unique_episode_count"]) for r in rows_for_group),
        "mean_largest_episode_share": statistics.fmean(float(r["largest_episode_share"]) for r in rows_for_group),
    }


def run(config_path: Path, output_root: Path, dry_run: bool) -> int:
    cfg = load_yaml(config_path)
    output_root.mkdir(parents=True, exist_ok=True)
    resources = [enforce_resource_guard(cfg, output_root, "start")]
    started = time.monotonic()
    config_hash = sha256_canonical(cfg)
    horizon = int(cfg["outcome_horizon"])
    k = int(cfg["retrieval"]["k"])
    episode_cap = int(cfg["retrieval"]["episode_cap"])
    repetitions = int(cfg["baseline_repetitions"])
    minimum_candidates = int(cfg["minimum_within_context_candidates"])
    preferred_candidates = int(cfg["preferred_within_context_candidates"])
    context_defs = list(cfg["context_definitions"])
    per_instrument = int(cfg["validation"]["query_sample_per_instrument_window"])
    candidate_limit = int(cfg["validation"]["candidate_sample_limit"])
    seed = int(cfg["random"]["seed"])

    with SessionLocal() as session:
        replication_service = ReplicationService(session)
        protocol = replication_service.freeze_protocol(cfg["replication"]["protocol_code"], cfg["replication"]["source_experiment_id"])

        study = session.get(StudyManifest, cfg["dataset"]["study_id"])
        if study is None:
            raise RuntimeError("STUDY_NOT_FOUND")
        study_id = study.id
        dataset_hash_value = study.dataset_hash
        source_before = protected_counts(session)

        query_exclusions: list[dict[str, Any]] = []
        candidate_coverage: list[dict[str, Any]] = []
        paired_rows: list[dict[str, Any]] = []
        unconditional_rows: list[dict[str, Any]] = []
        dna_no_filter_rows: list[dict[str, Any]] = []
        dry_summary: list[dict[str, Any]] = []
        universe_symbols: set[str] = set()

        for window_length in cfg["window_lengths"]:
            resources.append(enforce_resource_guard(cfg, output_root, f"load_window_{window_length}"))
            rows, outcomes = load_rows(session, study_id, int(window_length), horizon)
            by_id = {row.id: row for row in rows}
            queries = select_queries(rows, outcomes, per_instrument)
            dry_summary.append(
                {
                    "window_length": window_length,
                    "loaded_windows": len(rows),
                    "selected_query_windows": len(queries),
                    "query_count_by_instrument": dict(Counter(row.symbol for row in queries)),
                }
            )
            if dry_run:
                for definition in context_defs:
                    dims = context_dimensions_for(definition)
                    coverage_counts = []
                    for query in queries[: min(len(queries), 200)]:
                        candidates, _ = eligible_candidates(query, rows, outcomes, horizon, candidate_limit, seed)
                        candidate_ids = [c.id for c in candidates]
                        candidate_contexts = [by_id[i].context for i in candidate_ids]
                        within = filter_by_context(candidate_ids, candidate_contexts, query.context, dims)
                        coverage_counts.append(len(within))
                    candidate_coverage.append(
                        {
                            "window_length": window_length,
                            "context_definition": definition,
                            "sampled_queries": len(coverage_counts),
                            "mean_candidate_count": statistics.fmean(coverage_counts) if coverage_counts else 0,
                            "min_candidate_count": min(coverage_counts) if coverage_counts else 0,
                            "below_minimum_count": sum(1 for c in coverage_counts if c < minimum_candidates),
                        }
                    )
                continue

            for query in queries:
                actual = outcomes.get(query.id)
                if actual is None:
                    continue
                universe_symbols.add(query.symbol)
                actual_return = float(actual["future_simple_return"])
                actual_positive = actual_return > 0.0
                candidates, _ = eligible_candidates(query, rows, outcomes, horizon, candidate_limit, seed)
                if not candidates:
                    query_exclusions.append({"query_id": query.id, "symbol": query.symbol, "window_length": window_length, "reason": "NO_ELIGIBLE_CANDIDATES"})
                    continue
                candidate_ids = [c.id for c in candidates]

                # Level 0: unconditional history (deterministic earliest-K, matching existing convention)
                sorted_candidates = sorted(candidate_ids, key=lambda i: (by_id[i].end, i))
                uncond_agg = aggregate(sorted_candidates[:k], by_id, outcomes)
                if uncond_agg is not None:
                    unconditional_rows.append(
                        {"symbol": query.symbol, "asset_class": query.asset_class, "window_length": window_length, **evaluate(uncond_agg, actual_return, actual_positive)}
                    )

                # Reference: DNA without context filtering (secondary reference only)
                dna_no_filter_selected = rank_dna(query, candidates, episode_cap, k)
                dna_no_filter_agg = aggregate([r.id for r in dna_no_filter_selected], by_id, outcomes)
                if dna_no_filter_agg is not None:
                    dna_no_filter_rows.append(
                        {"symbol": query.symbol, "asset_class": query.asset_class, "window_length": window_length, **evaluate(dna_no_filter_agg, actual_return, actual_positive)}
                    )

                for definition in context_defs:
                    dims = context_dimensions_for(definition)
                    candidate_contexts = [by_id[i].context for i in candidate_ids]
                    within_ids = filter_by_context(candidate_ids, candidate_contexts, query.context, dims)
                    sufficiency = classify_candidate_sufficiency(len(within_ids), minimum=minimum_candidates, preferred=preferred_candidates)
                    if sufficiency == "INSUFFICIENT_WITHIN_CONTEXT_SAMPLE":
                        query_exclusions.append(
                            {"query_id": query.id, "symbol": query.symbol, "window_length": window_length, "context_definition": definition, "reason": sufficiency, "candidate_count": len(within_ids)}
                        )
                        continue
                    within_rows = [by_id[i] for i in within_ids]
                    # Independently derive each side's candidate population from what is
                    # actually handed to its selection mechanism (DNA ranking receives
                    # `within_rows`, context-random sampling receives `within_ids`), then
                    # verify equality before either mechanism runs -- a real regression
                    # guard against a future refactor silently letting the two populations
                    # diverge, not just a restatement of a single shared variable.
                    dna_population_ids = [row.id for row in within_rows]
                    random_population_ids = list(within_ids)
                    try:
                        candidate_universe_hash_value = assert_candidate_universe_equality(dna_population_ids, random_population_ids)
                    except CandidateUniverseMismatchError:
                        query_exclusions.append(
                            {"query_id": query.id, "symbol": query.symbol, "window_length": window_length, "context_definition": definition, "reason": "BASELINE_UNIVERSE_MISMATCH"}
                        )
                        continue

                    dna_selected = rank_dna(query, within_rows, episode_cap, k)
                    dna_agg = aggregate([r.id for r in dna_selected], by_id, outcomes)
                    context_random_agg, _repetitions = context_random_estimate(
                        random_population_ids, by_id, outcomes, k, repetitions, int(sha256_canonical([seed, query.id, definition])[:12], 16)
                    )
                    if dna_agg is None or not context_random_agg:
                        continue
                    dna_eval = evaluate(dna_agg, actual_return, actual_positive)
                    context_eval = evaluate(context_random_agg, actual_return, actual_positive)
                    paired_rows.append(
                        {
                            "query_id": query.id,
                            "symbol": query.symbol,
                            "asset_class": query.asset_class,
                            "window_length": window_length,
                            "context_definition": definition,
                            "candidate_count": len(within_ids),
                            "sufficiency": sufficiency,
                            "candidate_universe_hash": candidate_universe_hash_value,
                            "brier_dna": dna_eval["brier_score"],
                            "brier_context_random": context_eval["brier_score"],
                            "brier_diff": context_eval["brier_score"] - dna_eval["brier_score"],
                            "log_loss_dna": dna_eval["log_loss"],
                            "log_loss_context_random": context_eval["log_loss"],
                            "mae_dna": dna_eval["return_absolute_error"],
                            "mae_context_random": context_eval["return_absolute_error"],
                            "mae_diff": context_eval["return_absolute_error"] - dna_eval["return_absolute_error"],
                            "unique_episode_count_dna": dna_eval["unique_episode_count"],
                            "largest_episode_share_dna": dna_eval["largest_episode_share"],
                            "predicted_positive_probability_dna": dna_eval["predicted_positive_probability"],
                            "predicted_positive_probability_context_random": context_eval["predicted_positive_probability"],
                            "actual_positive": actual_positive,
                        }
                    )

        if dry_run:
            summary = {
                "status": "DRY_RUN",
                "configuration_hash": config_hash,
                "dataset_hash": dataset_hash_value,
                "protocol_id": protocol.id,
                "protocol_status": protocol.status,
                "window_summaries": dry_summary,
                "candidate_coverage_sample": candidate_coverage,
                "resource_snapshots": resources,
                "source_counts": source_before,
            }
            (output_root / "dry_run.json").write_text(json.dumps(summary, indent=2, sort_keys=True, default=str), encoding="utf-8")
            print(json.dumps(summary, indent=2, sort_keys=True, default=str))
            return 0

        source_after = protected_counts(session)
        instrument_universe = sorted(universe_symbols)
        lock = replication_service.create_lock(
            protocol.id,
            study_id=study_id,
            source_study_id=study_id,
            dataset_hash=dataset_hash_value,
            provider_code=cfg["dataset"]["provider"],
            provider_provenance_hash=sha256_canonical({"provider": cfg["dataset"]["provider"], "dataset_hash": dataset_hash_value, "phase": "context_dna_incremental_value_v1"}),
            instrument_universe=instrument_universe,
            date_range={"start": "reused_from_step_10a3", "end": "reused_from_step_10a3"},
        )
        record = replication_service.create_record(lock.id, provider_independence="CONFIRMED")

        # --- Level 0/1/2 pooled summaries ---
        unconditional_summary = summarize(unconditional_rows, None)
        context_definition_results = []
        context_only_results = []
        dna_within_context_results = []
        bootstrap_rows = []
        instrument_results = []
        asset_class_results = []
        window_length_results = []
        episode_diversity_rows = []
        calibration_rows = []

        for definition in context_defs:
            rows_for_def = [r for r in paired_rows if r["context_definition"] == definition]
            if not rows_for_def:
                continue
            context_random_eval_rows = [
                {"brier_score": r["brier_context_random"], "log_loss": r["log_loss_context_random"], "return_absolute_error": r["mae_context_random"],
                 "predicted_positive_probability": r["predicted_positive_probability_context_random"], "actual_positive": r["actual_positive"],
                 "unique_episode_count": r["unique_episode_count_dna"], "largest_episode_share": r["largest_episode_share_dna"]}
                for r in rows_for_def
            ]
            dna_eval_rows = [
                {"brier_score": r["brier_dna"], "log_loss": r["log_loss_dna"], "return_absolute_error": r["mae_dna"],
                 "predicted_positive_probability": r["predicted_positive_probability_dna"], "actual_positive": r["actual_positive"],
                 "unique_episode_count": r["unique_episode_count_dna"], "largest_episode_share": r["largest_episode_share_dna"]}
                for r in rows_for_def
            ]
            context_summary = summarize(context_random_eval_rows, unconditional_summary.get("brier_score"))
            dna_summary = summarize(dna_eval_rows, context_summary.get("brier_score"))
            context_only_results.append({"context_definition": definition, **context_summary})
            dna_within_context_results.append({"context_definition": definition, **dna_summary})

            diffs = [r["brier_diff"] for r in rows_for_def]
            bootstrap = paired_block_bootstrap(diffs, seed=seed, iterations=int(cfg["statistics"]["paired_block_bootstrap_iterations"]), confidence=float(cfg["statistics"]["confidence_level"]))
            bootstrap_rows.append(
                {
                    "context_definition": definition, "metric": "brier_diff_context_minus_dna",
                    "mean": bootstrap.mean, "median": bootstrap.median, "low": bootstrap.low, "high": bootstrap.high,
                    "standard_error": bootstrap.standard_error, "sample_count": len(diffs),
                }
            )
            context_definition_results.append(
                {
                    "context_definition": definition, "query_coverage": len(rows_for_def),
                    "candidate_count_mean": statistics.fmean(r["candidate_count"] for r in rows_for_def),
                    "context_only_brier": context_summary.get("brier_score"), "dna_within_context_brier": dna_summary.get("brier_score"),
                    "dna_incremental_brier_skill": dna_summary.get("brier_skill_vs_prior"),
                    "paired_brier_diff_mean": bootstrap.mean, "paired_brier_diff_ci_low": bootstrap.low, "paired_brier_diff_ci_high": bootstrap.high,
                }
            )
            episode_diversity_rows.append(
                {
                    "context_definition": definition, "mean_unique_episode_count": dna_summary.get("mean_unique_episode_count"),
                    "mean_largest_episode_share": dna_summary.get("mean_largest_episode_share"),
                }
            )
            ece_dna, mce_dna = calibration(dna_eval_rows)
            ece_ctx, mce_ctx = calibration(context_random_eval_rows)
            calibration_rows.append({"context_definition": definition, "ece_dna": ece_dna, "mce_dna": mce_dna, "ece_context_random": ece_ctx, "mce_context_random": mce_ctx})

            for symbol in sorted({r["symbol"] for r in rows_for_def}):
                subset = [r for r in rows_for_def if r["symbol"] == symbol]
                sub_diffs = [r["brier_diff"] for r in subset]
                instrument_results.append(
                    {
                        "context_definition": definition, "symbol": symbol, "eligible_queries": len(subset),
                        "paired_brier_diff_mean": statistics.fmean(sub_diffs) if sub_diffs else 0.0,
                        "mae_diff_mean": statistics.fmean(r["mae_diff"] for r in subset) if subset else 0.0,
                    }
                )
            for asset_class in sorted({r["asset_class"] for r in rows_for_def}):
                subset = [r for r in rows_for_def if r["asset_class"] == asset_class]
                sub_diffs = [r["brier_diff"] for r in subset]
                asset_class_results.append(
                    {
                        "context_definition": definition, "asset_class": asset_class, "eligible_queries": len(subset),
                        "paired_brier_diff_mean": statistics.fmean(sub_diffs) if sub_diffs else 0.0,
                    }
                )
            for window_length in cfg["window_lengths"]:
                subset = [r for r in rows_for_def if r["window_length"] == window_length]
                sub_diffs = [r["brier_diff"] for r in subset]
                window_length_results.append(
                    {
                        "context_definition": definition, "window_length": window_length, "eligible_queries": len(subset),
                        "paired_brier_diff_mean": statistics.fmean(sub_diffs) if sub_diffs else 0.0,
                    }
                )

        dna_no_filter_summary = summarize(dna_no_filter_rows, unconditional_summary.get("brier_score"))

        # --- Canonical 3-level decomposition using core_context ---
        configured_canonical = cfg.get("canonical_context_definition")
        canonical_definition = (
            configured_canonical
            if configured_canonical and any(r["context_definition"] == configured_canonical for r in context_only_results)
            else (context_defs[0] if context_defs else None)
        )
        canonical_context = next((r for r in context_only_results if r["context_definition"] == canonical_definition), {})
        canonical_dna = next((r for r in dna_within_context_results if r["context_definition"] == canonical_definition), {})
        information_layers = information_layer_table(
            [
                {"layer": "unconditional", "brier": unconditional_summary.get("brier_score", 0.0), "log_loss": unconditional_summary.get("log_loss", 0.0), "return_mae": unconditional_summary.get("return_mae", 0.0), "ece": unconditional_summary.get("expected_calibration_error", 0.0)},
                {"layer": f"context ({canonical_definition})", "brier": canonical_context.get("brier_score", 0.0), "log_loss": canonical_context.get("log_loss", 0.0), "return_mae": canonical_context.get("return_mae", 0.0), "ece": canonical_context.get("expected_calibration_error", 0.0)},
                {"layer": f"context+dna ({canonical_definition})", "brier": canonical_dna.get("brier_score", 0.0), "log_loss": canonical_dna.get("log_loss", 0.0), "return_mae": canonical_dna.get("return_mae", 0.0), "ece": canonical_dna.get("expected_calibration_error", 0.0)},
            ]
        )

        # --- Decision inputs (canonical definition drives the primary decision) ---
        canonical_paired = [r for r in paired_rows if r["context_definition"] == canonical_definition]
        canonical_bootstrap = next((b for b in bootstrap_rows if b["context_definition"] == canonical_definition), None)
        context_supported = (canonical_context.get("brier_skill_vs_prior") or -1) > 0.0
        dna_incremental_skill = canonical_dna.get("brier_skill_vs_prior")
        by_instrument_skill = [r["paired_brier_diff_mean"] for r in instrument_results if r["context_definition"] == canonical_definition]
        by_window_skill = [r["paired_brier_diff_mean"] for r in window_length_results if r["context_definition"] == canonical_definition]
        consistent_across_instruments = sum(1 for s in by_instrument_skill if s > 0) >= max(1, len(by_instrument_skill) - 1)
        consistent_across_window_scales = sum(1 for s in by_window_skill if s > 0) >= 2
        by_asset_skill = {r["asset_class"]: r["paired_brier_diff_mean"] for r in asset_class_results if r["context_definition"] == canonical_definition}
        mixed_by_asset = len(by_asset_skill) >= 2 and (max(by_asset_skill.values()) > 0) and (min(by_asset_skill.values()) <= 0)
        skills_by_def = [r["dna_incremental_brier_skill"] for r in context_definition_results if r["dna_incremental_brier_skill"] is not None]
        mixed_by_context_definition = len(skills_by_def) >= 2 and (max(skills_by_def) > 0.02) and (min(skills_by_def) <= 0.0)
        sufficient_evidence = len(canonical_paired) >= 30 and len(instrument_universe) >= 3

        decision_result = classify_context_dna_decision(
            context_supported=context_supported,
            dna_incremental_brier_skill=dna_incremental_skill,
            dna_ci_low=canonical_bootstrap["low"] if canonical_bootstrap else None,
            dna_ci_high=canonical_bootstrap["high"] if canonical_bootstrap else None,
            consistent_across_instruments=consistent_across_instruments,
            consistent_across_window_scales=consistent_across_window_scales,
            mixed_by_asset=mixed_by_asset,
            mixed_by_context_definition=mixed_by_context_definition,
            sufficient_evidence=sufficient_evidence,
        )

        run_row = ExperimentRun(
            experiment_code=cfg["experiment"]["code"], experiment_version="context_dna_v1", name=cfg["experiment"]["name"],
            hypothesis=protocol.hypothesis_text, status=ExperimentRunStatus.completed.value, dataset_hash=dataset_hash_value,
            code_version={"source": "local_and_vps_reconciled"}, configuration=cfg, configuration_hash=config_hash,
            run_nonce=f"context-dna-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}",
            similarity_method="dna_robust_cosine_v1", baseline_methods=["same_context_random_v1", "unconditional_outcome_v1"],
            outcome_set_code="forward_outcomes_v1", outcome_set_version="forward_outcomes_v1", outcome_horizons=[horizon],
            validation_method="context_matched_historical_as_of_v1", validation_configuration=cfg["validation"],
            instrument_scope=instrument_universe, timeframe_scope=[cfg["dataset"]["timeframe"]], window_length_scope=cfg["window_lengths"],
            parameter_grid={"context_definitions": context_defs, "k": k, "episode_cap": episode_cap, "horizon": horizon, "baseline_repetitions": repetitions},
            multiple_testing_family="context_dna_incremental_value_v1_predeclared_hierarchy", decision=decision_result.decision,
            summary={"classification": "FOLLOW_UP_CONFIRMATORY_DIAGNOSTIC", "protocol_id": protocol.id, "lock_id": lock.id, "record_id": record.id, "canonical_context_definition": canonical_definition, "source_mutation_check": source_before == source_after},
            started_at=datetime.now(UTC) - timedelta(seconds=time.monotonic() - started), completed_at=datetime.now(UTC),
            elapsed_seconds=round(time.monotonic() - started, 3),
        )
        session.add(run_row)
        session.flush()

        replication_service.decide(
            record.id, replication_experiment_id=run_row.id, decision=decision_result.decision,
            decision_rationale=decision_result.rationale,
            comparison={"canonical_context_definition": canonical_definition, "context_skill_vs_unconditional": canonical_context.get("brier_skill_vs_prior"), "dna_incremental_skill_vs_context": dna_incremental_skill},
            decision_vocabulary=CONTEXT_DNA_DECISIONS,
        )

        report_json = {
            "phase_status": "CONTEXT_DNA_TEST_COMPLETED", "experiment_id": run_row.id, "protocol_id": protocol.id, "lock_id": lock.id, "record_id": record.id,
            "configuration_hash": config_hash, "dataset_hash": dataset_hash_value, "decision": decision_result.decision, "decision_rationale": decision_result.rationale,
            "canonical_context_definition": canonical_definition, "information_layers": information_layers,
            "unconditional_summary": unconditional_summary, "context_only_results": context_only_results, "dna_within_context_results": dna_within_context_results,
            "dna_no_context_filter_reference": dna_no_filter_summary, "context_definition_results": context_definition_results,
            "instrument_universe": instrument_universe, "evaluation_rows": len(paired_rows),
            "source_counts_before": source_before, "source_counts_after": source_after, "source_layer_mutation_check": source_before == source_after,
            "resource_snapshots": resources + [resource_snapshot(output_root)],
            "final_test_lock": "NO", "trading_logic": "NO", "ai_ml_model": "NO",
        }
        report_md = [
            "# Context Signal Isolation and Market DNA Incremental-Value Test", "", f"Decision: `{decision_result.decision}`", "",
            decision_result.rationale, "", f"Canonical context definition: `{canonical_definition}`", "",
            f"Experiment ID: `{run_row.id}`", f"Protocol ID: `{protocol.id}`", f"Lock ID: `{lock.id}`",
            f"Configuration hash: `{config_hash}`", f"Dataset hash: `{dataset_hash_value}`", "",
            "No final-test lock, final test, model training, trading signal, or execution logic was run.", "",
            "## Information layer decomposition", "", json.dumps(information_layers, indent=2, sort_keys=True, default=str), "",
            "## Source-layer mutation check", "", f"Protected counts unchanged: `{source_before == source_after}`",
        ]
        (output_root / "report.md").write_text("\n".join(report_md), encoding="utf-8")
        artifacts = {
            "report.json": report_json,
            "protocol.json": protocol.configuration,
            "protocol_lock.json": lock.lock_payload,
            "decision.json": {"decision": decision_result.decision, "rationale": decision_result.rationale},
        }
        for name, payload in artifacts.items():
            (output_root / name).write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")
        write_csv(output_root / "information_layer_summary.csv", information_layers)
        write_csv(output_root / "context_only_results.csv", context_only_results)
        write_csv(output_root / "dna_within_context_results.csv", dna_within_context_results)
        write_csv(output_root / "paired_comparisons.csv", paired_rows)
        write_csv(output_root / "instrument_results.csv", instrument_results)
        write_csv(output_root / "asset_class_results.csv", asset_class_results)
        write_csv(output_root / "window_length_results.csv", window_length_results)
        write_csv(output_root / "context_definition_results.csv", context_definition_results)
        write_csv(output_root / "candidate_coverage.csv", candidate_coverage)
        write_csv(output_root / "episode_diversity.csv", episode_diversity_rows)
        write_csv(output_root / "calibration.csv", calibration_rows)
        write_csv(output_root / "outcome_dispersion.csv", [{"context_definition": r["context_definition"], "return_std_dna": r.get("mean_unique_episode_count")} for r in episode_diversity_rows])
        write_csv(output_root / "bootstrap_confidence.csv", bootstrap_rows)
        write_csv(output_root / "query_exclusions.csv", query_exclusions)
        write_csv(output_root / "resource_usage.csv", resources + [resource_snapshot(output_root)])
        for path in output_root.iterdir():
            if path.is_file():
                content = path.read_text(encoding="utf-8", errors="replace")
                session.add(
                    ExperimentArtifact(
                        experiment_run_id=run_row.id, artifact_type=path.suffix.lstrip(".") or "text", name=path.name,
                        content=content, artifact_metadata={"path": str(path)}, artifact_hash=sha256_canonical(content),
                    )
                )
        session.commit()
        print(json.dumps(report_json, indent=2, sort_keys=True, default=str))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("config", type=Path)
    parser.add_argument("--output-root", type=Path, default=Path("/opt/market-genome/reports/context_dna_incremental_value_v1"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    os.environ.setdefault("PYTHONHASHSEED", "0")
    return run(args.config, args.output_root, args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
