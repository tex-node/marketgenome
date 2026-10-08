from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProspectiveProtocolDefinition:
    protocol_code: str
    protocol_version: str
    hypothesis_text: str
    context_definition: str
    context_producer_code: str
    context_producer_version: str
    fallback_hierarchy: tuple[str, ...]
    timeframe: str
    window_lengths: tuple[int, ...]
    primary_horizon: int
    secondary_horizons: tuple[int, ...]
    probability_method: str
    smoothing_method: str
    smoothing_parameters: dict[str, float]
    minimum_historical_sample: int
    calibration_method: str
    refresh_policy: str
    provider_code: str
    instrument_universe: tuple[str, ...]
    success_criteria: dict[str, object]
    minimum_evidence_matured_forecasts: int
    preferred_evidence_matured_forecasts: int


# Context definition selected from completed Step 10A.4 historical evidence only
# (no prospective data existed at selection time):
#   trend_volatility:  context Brier 0.2561, skill vs unconditional +0.218, coverage
#                       850-856/900 (94-95%) per window length, consistent across all
#                       6 instruments/2 asset classes/3 window lengths.
#   context_family:    context Brier 0.2542, skill vs unconditional +0.224, coverage
#                       876-887/900 (97-99%).
# The two are materially equivalent in performance (skill difference ~0.006, both
# well above zero). trend_volatility is chosen as primary because it is the more
# directly explainable two-dimension representation (trend state + volatility state,
# matching the illustrative example in the phase spec), it was already the Step 10A.4
# canonical definition, and per the phase's own instruction to "prefer the simplest
# definition whose performance is materially equivalent." context_family remains
# available as a secondary descriptive definition and as a fallback-hierarchy rung.
MARKET_CONTEXT_FORECAST_V1 = ProspectiveProtocolDefinition(
    protocol_code="market_context_forecast_v1",
    protocol_version="protocol_v1",
    hypothesis_text=(
        "D1 Market Context state (trend + volatility) provides forward 20-bar directional "
        "probability estimates with positive Brier skill relative to unconditional historical "
        "probabilities when evaluated prospectively on observations that occur after the "
        "protocol freeze."
    ),
    context_definition="trend_volatility",
    context_producer_code="transparent_context_v1",
    context_producer_version="transparent_context_v1",
    fallback_hierarchy=("trend_volatility", "trend_only", "unconditional"),
    timeframe="D1",
    window_lengths=(16, 32, 64),
    primary_horizon=20,
    secondary_horizons=(5, 10),
    probability_method="context_conditioned_historical_frequency_v1",
    smoothing_method="beta_binomial_laplace_v1",
    smoothing_parameters={"alpha": 1.0, "beta": 1.0},
    minimum_historical_sample=30,
    calibration_method="none",
    refresh_policy="daily_d1_completed_bars",
    provider_code="alpha_vantage_v1",
    instrument_universe=("EURUSD_AV", "GBPUSD_AV", "USDJPY_AV", "AUDUSD_AV", "BTCUSD_AV", "ETHUSD_AV"),
    success_criteria={
        "minimum_evidence_matured_forecasts": 100,
        "preferred_evidence_matured_forecasts": 250,
        "brier_skill_vs_unconditional_gt": 0.0,
        "bootstrap_ci_low_gt_zero_for_support": True,
        "no_trading_logic": True,
        "no_ai_model": True,
    },
    minimum_evidence_matured_forecasts=100,
    preferred_evidence_matured_forecasts=250,
)

PROSPECTIVE_PROTOCOLS = {
    MARKET_CONTEXT_FORECAST_V1.protocol_code: MARKET_CONTEXT_FORECAST_V1,
}

# Candidate protocol: a complete, pre-registered specification that is deliberately NOT
# part of the active registry. It cannot be listed as available, resolved by code, or
# frozen through the normal CLI/API path until explicitly promoted (see
# docs/research/prospective-protocol-v2-candidate.md). This keeps "drafted" structurally
# distinct from "activated" -- a candidate can never be frozen by accident.
#
# Motivation (recorded, not outcome-fitted): v1 hard-switches between context levels at a
# 30-sample minimum and Laplace-smooths toward 0.5. v2 replaces that single estimator with
# a hierarchical Beta-Binomial that shrinks the most specific context frequency toward the
# as-of unconditional base rate by a fixed pseudo-count. Every other choice (context
# definition, horizons, window lengths, instruments, provider, target) is identical to v1,
# so a v2-vs-v1 difference is attributable to the estimator alone.
MARKET_CONTEXT_FORECAST_V2 = ProspectiveProtocolDefinition(
    protocol_code="market_context_forecast_v2",
    protocol_version="protocol_v2",
    hypothesis_text=(
        "D1 Market Context state (trend + volatility), with its conditional frequency "
        "hierarchically shrunk toward the as-of unconditional base rate by a fixed "
        "pseudo-count, provides forward 20-bar directional probability estimates with "
        "positive Brier skill relative to the as-of unconditional historical probability "
        "when evaluated prospectively on observations after the v2 protocol freeze -- and "
        "improves on the v1 hard-switch/Laplace estimator."
    ),
    context_definition="trend_volatility",
    context_producer_code="transparent_context_v1",
    context_producer_version="transparent_context_v1",
    fallback_hierarchy=("trend_volatility", "trend_only", "unconditional"),
    timeframe="D1",
    window_lengths=(16, 32, 64),
    primary_horizon=20,
    secondary_horizons=(5, 10),
    probability_method="context_conditioned_hierarchical_shrinkage_v2",
    smoothing_method="beta_binomial_hierarchical_shrinkage_v2",
    # prior_strength is the pseudo-count of the as-of unconditional prior; fixed here and
    # never fitted against prospective outcomes.
    smoothing_parameters={"prior_strength": 20.0},
    # 0: shrinkage (not a hard minimum) handles small context samples, so the most specific
    # level is always used and the estimate degrades smoothly to the unconditional rate.
    minimum_historical_sample=0,
    calibration_method="none",
    refresh_policy="daily_d1_completed_bars",
    provider_code="alpha_vantage_v1",
    instrument_universe=("EURUSD_AV", "GBPUSD_AV", "USDJPY_AV", "AUDUSD_AV", "BTCUSD_AV", "ETHUSD_AV"),
    success_criteria={
        "minimum_evidence_matured_forecasts": 100,
        "preferred_evidence_matured_forecasts": 250,
        "brier_skill_vs_unconditional_gt": 0.0,
        "bootstrap_ci_low_gt_zero_for_support": True,
        "must_beat_v1_estimator": True,
        "no_trading_logic": True,
        "no_ai_model": True,
    },
    minimum_evidence_matured_forecasts=100,
    preferred_evidence_matured_forecasts=250,
)

CANDIDATE_PROSPECTIVE_PROTOCOLS = {
    MARKET_CONTEXT_FORECAST_V2.protocol_code: MARKET_CONTEXT_FORECAST_V2,
}


def list_prospective_protocol_definitions() -> list[ProspectiveProtocolDefinition]:
    return list(PROSPECTIVE_PROTOCOLS.values())


def list_candidate_prospective_protocol_definitions() -> list[ProspectiveProtocolDefinition]:
    return list(CANDIDATE_PROSPECTIVE_PROTOCOLS.values())


def get_prospective_protocol_definition(code: str) -> ProspectiveProtocolDefinition:
    try:
        return PROSPECTIVE_PROTOCOLS[code]
    except KeyError as exc:
        raise ValueError("PROSPECTIVE_PROTOCOL_DEFINITION_NOT_FOUND") from exc
