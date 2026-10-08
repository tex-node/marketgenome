from __future__ import annotations

import importlib.util
from datetime import UTC, datetime
from pathlib import Path

from market_genome_prospective.definitions import (
    get_prospective_protocol_definition,
)

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "generate_prospective_report.py"
WRAPPER_PATH = Path(__file__).resolve().parents[2] / "scripts" / "vps" / "run_prospective_daily.sh"


def _load_report_module():
    spec = importlib.util.spec_from_file_location("generate_prospective_report", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MODULE = _load_report_module()
render_markdown = MODULE.render_markdown


def _protocol_data() -> dict:
    definition = get_prospective_protocol_definition("market_context_forecast_v1")
    return {
        "id": "proto-1",
        "code": definition.protocol_code,
        "status": "FROZEN",
        "frozen_at": datetime(2026, 9, 1, tzinfo=UTC),
        "hypothesis": definition.hypothesis_text,
        "primary_horizon": definition.primary_horizon,
        "minimum_evidence": definition.minimum_evidence_matured_forecasts,
        "preferred_evidence": definition.preferred_evidence_matured_forecasts,
    }


def _report_data(*, status: str = "PROSPECTIVE_EVIDENCE_ACCUMULATING", primary_n: int = 78) -> dict:
    return {
        "generated_at": datetime(2026, 9, 21, 12, 0, tzinfo=UTC),
        "protocol": _protocol_data(),
        "snapshot": {
            "id": "snap-1",
            "as_of": datetime(2026, 9, 21, 11, 22, tzinfo=UTC),
            "forecast_count": 945,
            "matured_count": 528,
            "primary_horizon_matured_count": primary_n,
            "brier_score": 0.269641441225046,
            "brier_skill_vs_unconditional": -0.0537463800163256,
            "log_loss": 0.737669157480744,
            "expected_calibration_error": 0.178914493912036,
            "direction_accuracy": 0.5,
            "balanced_accuracy": 0.55,
            "mcc": 0.106693013873853,
            "bootstrap_ci_low": -0.16418276269231,
            "bootstrap_ci_high": 0.0525738484731184,
            "status": status,
            "per_horizon_metrics": {
                "5": {"sample_count": 243, "brier_score": 0.2470, "brier_skill_vs_unconditional": -0.0025, "bootstrap_ci_low": -0.0401, "bootstrap_ci_high": 0.0348},
                "20": {"sample_count": 78, "brier_score": 0.2696, "brier_skill_vs_unconditional": -0.0537, "bootstrap_ci_low": -0.1642, "bootstrap_ci_high": 0.0526},
            },
        },
        "history": [
            {
                "as_of": datetime(2026, 9, 17, 11, 33, tzinfo=UTC),
                "forecast_count": 855,
                "matured_count": 438,
                "primary_horizon_matured_count": 42,
                "brier_skill_vs_unconditional": -0.1733,
            },
            {
                "as_of": datetime(2026, 9, 21, 11, 22, tzinfo=UTC),
                "forecast_count": 945,
                "matured_count": 528,
                "primary_horizon_matured_count": 78,
                "brier_skill_vs_unconditional": -0.0537,
            },
        ],
        "latest_run": {"run_timestamp": "2026-09-21T11:22:47Z", "new_forecast_count": 36, "matured_count_this_run": 12},
    }


def test_report_includes_expected_sections() -> None:
    markdown = render_markdown(_report_data())
    for section in (
        "# Market Genome — Prospective Context Forecast Report",
        "## Status:",
        "## Headline metrics (primary horizon)",
        "## Per-horizon metrics",
        "## Trend (primary-horizon matured / skill)",
        "## Reading",
        "## Sources",
    ):
        assert section in markdown


def test_report_lists_each_horizon_with_skill() -> None:
    markdown = render_markdown(_report_data())
    assert "| 5 | 243 |" in markdown
    assert "| 20 | 78 |" in markdown
    assert "−0.0537" in markdown or "-0.0537" in markdown


def test_report_accumulating_reading_is_not_interpreted() -> None:
    markdown = render_markdown(_report_data(primary_n=78))
    assert "still accumulating" in markdown.lower()
    assert "not interpreted yet" in markdown.lower()


def test_report_reading_reflects_decision_status() -> None:
    markdown = render_markdown(_report_data(status="PROSPECTIVE_CONTEXT_SIGNAL_NOT_SUPPORTED"))
    assert "not supported" in markdown.lower()


def test_report_handles_missing_snapshot_data_gracefully() -> None:
    data = _report_data()
    data["snapshot"] = {
        "id": None,
        "as_of": None,
        "forecast_count": None,
        "matured_count": None,
        "primary_horizon_matured_count": None,
        "brier_score": None,
        "brier_skill_vs_unconditional": None,
        "log_loss": None,
        "expected_calibration_error": None,
        "direction_accuracy": None,
        "balanced_accuracy": None,
        "mcc": None,
        "bootstrap_ci_low": None,
        "bootstrap_ci_high": None,
        "status": "PROSPECTIVE_EVIDENCE_ACCUMULATING",
        "per_horizon_metrics": {},
    }
    markdown = render_markdown(data)
    assert "| _no matured forecasts yet_ |" in markdown


def test_scheduled_wrapper_runs_the_report_generator() -> None:
    """The daily wrapper must regenerate the report so the daily cycle is self-contained."""
    wrapper = WRAPPER_PATH.read_text(encoding="utf-8")
    assert "generate_prospective_report.py" in wrapper