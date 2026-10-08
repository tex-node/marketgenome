from __future__ import annotations

import pytest
from market_genome_prospective.definitions import (
    CANDIDATE_PROSPECTIVE_PROTOCOLS,
    MARKET_CONTEXT_FORECAST_V2,
    PROSPECTIVE_PROTOCOLS,
    get_prospective_protocol_definition,
    list_candidate_prospective_protocol_definitions,
    list_prospective_protocol_definitions,
)

V2_CODE = "market_context_forecast_v2"


def test_candidate_v2_is_not_in_the_active_registry() -> None:
    """A drafted protocol must be structurally distinct from an activated one: it cannot
    appear in the active registry that drives the CLI/API listing and `freeze_protocol`."""
    assert V2_CODE not in PROSPECTIVE_PROTOCOLS
    assert all(definition.protocol_code != V2_CODE for definition in list_prospective_protocol_definitions())


def test_candidate_v2_cannot_be_resolved_through_the_active_lookup() -> None:
    """`get_prospective_protocol_definition` is the only path `freeze_protocol` uses, so a
    candidate that cannot be resolved here cannot be frozen by accident."""
    with pytest.raises(ValueError, match="PROSPECTIVE_PROTOCOL_DEFINITION_NOT_FOUND"):
        get_prospective_protocol_definition(V2_CODE)


def test_candidate_v2_is_listed_separately() -> None:
    assert list_candidate_prospective_protocol_definitions() == [MARKET_CONTEXT_FORECAST_V2]
    assert CANDIDATE_PROSPECTIVE_PROTOCOLS[V2_CODE] is MARKET_CONTEXT_FORECAST_V2


def test_candidate_v2_differs_from_v1_only_in_the_estimator() -> None:
    """A v2-vs-v1 difference must be attributable to the estimator alone, so every other
    frozen choice (context, horizons, windows, instruments, provider) is identical."""
    v1 = get_prospective_protocol_definition("market_context_forecast_v1")
    v2 = MARKET_CONTEXT_FORECAST_V2
    for field in (
        "context_definition",
        "context_producer_code",
        "context_producer_version",
        "fallback_hierarchy",
        "timeframe",
        "window_lengths",
        "primary_horizon",
        "secondary_horizons",
        "provider_code",
        "instrument_universe",
        "minimum_evidence_matured_forecasts",
        "preferred_evidence_matured_forecasts",
    ):
        assert getattr(v2, field) == getattr(v1, field), field
    assert v2.probability_method != v1.probability_method
    assert v2.smoothing_method != v1.smoothing_method
    assert v2.smoothing_parameters == {"prior_strength": 20.0}
