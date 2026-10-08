from __future__ import annotations

from dataclasses import dataclass
from typing import Any

OUTCOME_DEFINITION_CODES = [
    "future_simple_return",
    "future_log_return",
    "maximum_favourable_excursion",
    "maximum_adverse_excursion",
    "time_to_mfe",
    "time_to_mae",
    "future_realized_volatility",
    "future_path_efficiency",
    "future_maximum_drawdown",
    "future_maximum_runup",
    "future_direction",
    "continuation_reversal_class",
    "first_barrier_hit",
    "gain_before_drawdown",
    "drawdown_before_gain",
    "normalized_forward_path",
]


@dataclass(frozen=True)
class OutcomeDefinition:
    code: str
    version: str
    label: str
    description: str
    input_source: str
    formula: str
    units: str
    required_horizon: str
    minimum_future_bars: int
    supports_partial: bool
    direction_convention: str
    missing_data_policy: str
    limitations: str


OUTCOME_DEFINITIONS = {
    code: OutcomeDefinition(
        code=code,
        version="forward_outcomes_v1",
        label=code.replace("_", " ").title(),
        description=f"{code} calculated after the source PatternWindow end.",
        input_source="future_price_bars",
        formula="See docs/research/outcome-definitions.md",
        units="anchor_return" if "return" in code or "excursion" in code else "bars_or_class",
        required_horizon="bar_count",
        minimum_future_bars=1,
        supports_partial=True,
        direction_convention="positive is upward from anchor; MAE/drawdown are negative",
        missing_data_policy="persist_partial_with_flag",
        limitations="Historical observation only; not a forecast or executable trade result.",
    )
    for code in OUTCOME_DEFINITION_CODES
}


@dataclass(frozen=True)
class OutcomeSetDefinition:
    code: str
    version: str
    label: str
    description: str
    ordered_outcome_definitions: list[str]
    default_horizons: list[int]
    anchor_method: str
    forward_path_method: str
    barrier_configuration: dict[str, Any]
    classification_configuration: dict[str, Any]
    precision_policy: dict[str, Any]
    configuration: dict[str, Any]


FORWARD_OUTCOMES_V1_CONFIG: dict[str, Any] = {
    "outcome_set_code": "forward_outcomes_v1",
    "outcome_set_version": "forward_outcomes_v1",
    "anchor": {"method": "source_window_final_close"},
    "horizons": [1, 3, 5, 10, 20, 40, 60, 80],
    "returns": {"method": "simple_and_log"},
    "forward_path": {
        "normalization_method": "anchored_log_return",
        "include_anchor_zero": True,
        "storage_mode": "observed_points",
        "path_schema": "forward_close_log_path_v1",
    },
    "volatility": {"return_type": "log", "standard_deviation_ddof": 1, "annualize": False},
    "classifications": {
        "direction": {"positive_threshold": 0.0, "negative_threshold": 0.0, "flat_tolerance": 0.000001},
        "continuation_reversal": {
            "minimum_source_displacement": 0.000001,
            "continuation_threshold": 0.0,
            "reversal_threshold": 0.0,
            "source_direction_feature": "normalized_endpoint_return",
        },
    },
    "barriers": {"units": "anchor_return", "upside": [0.005, 0.01, 0.02], "downside": [-0.005, -0.01, -0.02]},
    "sequencing": {"gain_threshold": 0.01, "drawdown_threshold": -0.01},
    "partial_horizon": {"policy": "persist_with_flag"},
    "precision": {"calculation_dtype": "float64", "storage_decimals": 12},
}


FORWARD_OUTCOMES_V1 = OutcomeSetDefinition(
    code="forward_outcomes_v1",
    version="forward_outcomes_v1",
    label="Forward outcomes v1",
    description="Initial immutable forward outcome observation set.",
    ordered_outcome_definitions=OUTCOME_DEFINITION_CODES,
    default_horizons=FORWARD_OUTCOMES_V1_CONFIG["horizons"],
    anchor_method="source_window_final_close",
    forward_path_method="anchored_log_return",
    barrier_configuration=FORWARD_OUTCOMES_V1_CONFIG["barriers"],
    classification_configuration=FORWARD_OUTCOMES_V1_CONFIG["classifications"],
    precision_policy=FORWARD_OUTCOMES_V1_CONFIG["precision"],
    configuration=FORWARD_OUTCOMES_V1_CONFIG,
)

OUTCOME_SETS = {FORWARD_OUTCOMES_V1.code: FORWARD_OUTCOMES_V1}


def list_outcome_definitions() -> list[OutcomeDefinition]:
    return [OUTCOME_DEFINITIONS[code] for code in OUTCOME_DEFINITION_CODES]


def get_outcome_definition(code: str) -> OutcomeDefinition:
    try:
        return OUTCOME_DEFINITIONS[code]
    except KeyError as exc:
        raise ValueError("OUTCOME_DEFINITION_NOT_FOUND") from exc


def list_outcome_sets() -> list[OutcomeSetDefinition]:
    return list(OUTCOME_SETS.values())


def get_outcome_set(code: str) -> OutcomeSetDefinition:
    try:
        return OUTCOME_SETS[code]
    except KeyError as exc:
        raise ValueError("OUTCOME_SET_NOT_FOUND") from exc
