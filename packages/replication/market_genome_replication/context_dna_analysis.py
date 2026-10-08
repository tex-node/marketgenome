from __future__ import annotations

import hashlib
import json
import math
import random
import statistics
from dataclasses import dataclass
from typing import Any

CONTEXT_DEFINITIONS: dict[str, tuple[str, ...]] = {
    "trend_volatility": ("trend_state", "volatility_state"),
    "trend_volatility_persistence": ("trend_state", "volatility_state", "persistence_state"),
    "core_context": ("trend_state", "volatility_state", "persistence_state", "shock_state"),
    "context_family": ("context_family_code",),
}
MINIMUM_WITHIN_CONTEXT_CANDIDATES = 20
PREFERRED_WITHIN_CONTEXT_CANDIDATES = 30
CONTEXT_DNA_DECISIONS = (
    "CONTEXT_SIGNAL_SUPPORTED_DNA_ADDS_VALUE",
    "CONTEXT_SIGNAL_SUPPORTED_DNA_INCREMENTAL_VALUE_WEAK",
    "CONTEXT_SIGNAL_SUPPORTED_DNA_NO_INCREMENTAL_VALUE",
    "CONTEXT_SIGNAL_NOT_SUPPORTED",
    "RESULT_MIXED_BY_ASSET",
    "RESULT_MIXED_BY_CONTEXT",
    "INCONCLUSIVE_SAMPLE_LIMITED",
)


def context_dimensions_for(definition: str) -> tuple[str, ...]:
    try:
        return CONTEXT_DEFINITIONS[definition]
    except KeyError as exc:
        raise ValueError("UNSUPPORTED_CONTEXT_DEFINITION") from exc


def matches_context(query_context: dict[str, Any], candidate_context: dict[str, Any], dims: tuple[str, ...]) -> bool:
    return all(
        query_context.get(dim) is not None and query_context.get(dim) == candidate_context.get(dim)
        for dim in dims
    )


def filter_by_context(
    candidate_ids: list[str],
    candidate_contexts: list[dict[str, Any]],
    query_context: dict[str, Any],
    dims: tuple[str, ...],
) -> list[str]:
    return [
        candidate_id
        for candidate_id, context in zip(candidate_ids, candidate_contexts, strict=True)
        if matches_context(query_context, context, dims)
    ]


def classify_candidate_sufficiency(
    count: int,
    *,
    minimum: int = MINIMUM_WITHIN_CONTEXT_CANDIDATES,
    preferred: int = PREFERRED_WITHIN_CONTEXT_CANDIDATES,
) -> str:
    if count < minimum:
        return "INSUFFICIENT_WITHIN_CONTEXT_SAMPLE"
    if count < preferred:
        return "MARGINAL_WITHIN_CONTEXT_SAMPLE"
    return "ADEQUATE_WITHIN_CONTEXT_SAMPLE"


def candidate_universe_hash(candidate_ids: list[str]) -> str:
    payload = json.dumps(sorted(candidate_ids), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class CandidateUniverseMismatchError(ValueError):
    """Raised when the DNA-ranking and context-random populations for one query
    diverge -- they must be drawn from the exact same within-context candidate set,
    differing only in selection mechanism (ranked vs. randomly sampled)."""


def assert_candidate_universe_equality(dna_candidate_ids: list[str], random_candidate_ids: list[str]) -> str:
    """Returns the shared candidate-universe hash if the two populations are
    identical (order-independent); raises CandidateUniverseMismatchError otherwise.
    This is the runtime guard behind BASELINE_UNIVERSE_MISMATCH query exclusions."""
    dna_hash = candidate_universe_hash(dna_candidate_ids)
    random_hash = candidate_universe_hash(random_candidate_ids)
    if dna_hash != random_hash:
        raise CandidateUniverseMismatchError("BASELINE_UNIVERSE_MISMATCH")
    return dna_hash


def deterministic_context_random_draws(
    candidate_ids: list[str],
    k: int,
    repetitions: int,
    seed_base: int,
) -> list[list[str]]:
    """Deterministic seeded repeated draws of k ids (without replacement per draw)
    from the same within-context candidate universe used by DNA ranking."""
    draws = []
    for repetition in range(repetitions):
        rng = random.Random(seed_base * 1_000_003 + repetition)
        pool = list(candidate_ids)
        rng.shuffle(pool)
        draws.append(sorted(pool[:k]) if len(pool) <= k else pool[:k])
    return draws


@dataclass(frozen=True)
class PairedBootstrapResult:
    mean: float
    median: float
    low: float
    high: float
    standard_error: float


def paired_differences_summary(differences: list[float]) -> dict[str, float]:
    if not differences:
        return {"mean": 0.0, "median": 0.0}
    return {"mean": statistics.fmean(differences), "median": statistics.median(differences)}


def paired_block_bootstrap(
    differences: list[float],
    *,
    seed: int,
    iterations: int = 1000,
    confidence: float = 0.95,
    block_size: int | None = None,
) -> PairedBootstrapResult:
    if not differences:
        return PairedBootstrapResult(0.0, 0.0, 0.0, 0.0, 0.0)
    block = block_size or max(1, int(math.sqrt(len(differences))))
    blocks = [differences[i : i + block] for i in range(0, len(differences), block)]
    rng = random.Random(seed)
    samples = []
    for _ in range(iterations):
        sample: list[float] = []
        while len(sample) < len(differences):
            sample.extend(rng.choice(blocks))
        samples.append(statistics.fmean(sample[: len(differences)]))
    samples.sort()
    alpha = 1.0 - confidence
    low = samples[int((alpha / 2) * (iterations - 1))]
    high = samples[int((1 - alpha / 2) * (iterations - 1))]
    se = statistics.pstdev(samples) if len(samples) > 1 else 0.0
    summary = paired_differences_summary(differences)
    return PairedBootstrapResult(mean=summary["mean"], median=summary["median"], low=low, high=high, standard_error=se)


def information_layer_table(levels: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """levels: ordered list of {"layer": name, "brier": .., "log_loss": .., "return_mae": .., "ece": ..}
    Returns the same rows with an added "skill_vs_prior_layer" (None for the first row)."""
    table = []
    previous_brier: float | None = None
    for level in levels:
        skill = None if previous_brier is None else 1.0 - float(level["brier"]) / max(1e-12, previous_brier)
        table.append({**level, "skill_vs_prior_layer": skill})
        previous_brier = float(level["brier"])
    return table


@dataclass(frozen=True)
class ContextDnaDecisionResult:
    decision: str
    rationale: str


def classify_context_dna_decision(
    *,
    context_supported: bool,
    dna_incremental_brier_skill: float | None,
    dna_ci_low: float | None,
    dna_ci_high: float | None,
    consistent_across_instruments: bool,
    consistent_across_window_scales: bool,
    mixed_by_asset: bool,
    mixed_by_context_definition: bool,
    sufficient_evidence: bool,
) -> ContextDnaDecisionResult:
    if decision := _decision_for_unsupported_or_inconclusive(
        context_supported, sufficient_evidence, dna_incremental_brier_skill
    ):
        return decision
    if mixed_by_asset:
        return ContextDnaDecisionResult(
            "RESULT_MIXED_BY_ASSET",
            "Context signal is supported, but DNA incremental value differs materially by asset class.",
        )
    if mixed_by_context_definition:
        return ContextDnaDecisionResult(
            "RESULT_MIXED_BY_CONTEXT",
            "Context signal is supported, but DNA incremental value differs materially by context definition.",
        )
    ci_favors_dna = dna_ci_low is not None and dna_ci_low > 0.0
    ci_overlaps_zero = dna_ci_low is not None and dna_ci_high is not None and dna_ci_low <= 0.0 <= dna_ci_high
    if dna_incremental_brier_skill <= 0.0:
        return ContextDnaDecisionResult(
            "CONTEXT_SIGNAL_SUPPORTED_DNA_NO_INCREMENTAL_VALUE",
            "Context reproducibly beats unconditional history, but DNA-within-context performs "
            "approximately equal to or worse than context-random sampling from the same context.",
        )
    if (
        ci_favors_dna
        and consistent_across_instruments
        and consistent_across_window_scales
        and dna_incremental_brier_skill > 0.02
    ):
        return ContextDnaDecisionResult(
            "CONTEXT_SIGNAL_SUPPORTED_DNA_ADDS_VALUE",
            "Context beats unconditional history, and DNA-within-context improves on context-random "
            "by a non-trivial, confidence-interval-supported, cross-instrument, cross-scale amount.",
        )
    if ci_overlaps_zero or not consistent_across_instruments or not consistent_across_window_scales:
        return ContextDnaDecisionResult(
            "CONTEXT_SIGNAL_SUPPORTED_DNA_INCREMENTAL_VALUE_WEAK",
            "Context beats unconditional history; DNA shows a positive but small incremental effect "
            "whose confidence interval overlaps little/no improvement, or is inconsistent across "
            "instruments or window scales.",
        )
    return ContextDnaDecisionResult(
        "CONTEXT_SIGNAL_SUPPORTED_DNA_INCREMENTAL_VALUE_WEAK",
        "Context beats unconditional history; DNA incremental effect is positive but did not meet "
        "the bar for a clearly supported non-trivial improvement.",
    )


def _decision_for_unsupported_or_inconclusive(
    context_supported: bool, sufficient_evidence: bool, dna_incremental_brier_skill: float | None
) -> ContextDnaDecisionResult | None:
    if not sufficient_evidence:
        return ContextDnaDecisionResult(
            "INCONCLUSIVE_SAMPLE_LIMITED",
            "Insufficient within-context candidates, eligible queries, or episode diversity to reach a conclusion.",
        )
    if not context_supported:
        return ContextDnaDecisionResult(
            "CONTEXT_SIGNAL_NOT_SUPPORTED",
            "same_context_random_v1 did not improve over unconditional history on this independent "
            "dataset; this would require revisiting the Step 10A.3 interpretation.",
        )
    if dna_incremental_brier_skill is None:
        return ContextDnaDecisionResult(
            "INCONCLUSIVE_SAMPLE_LIMITED", "DNA-within-context incremental metrics could not be computed."
        )
    return None
