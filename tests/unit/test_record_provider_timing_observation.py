from __future__ import annotations

import importlib.util
from pathlib import Path


def _module():
    path = Path("scripts/record_provider_timing_observation.py")
    spec = importlib.util.spec_from_file_location("record_provider_timing_observation", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_append_rows_writes_header_once_and_appends_thereafter(tmp_path) -> None:
    module = _module()
    output_path = tmp_path / "provider_timing_observations.csv"
    row = {field: None for field in module.FIELDS}
    row.update({"instrument": "EURUSD_AV", "provider_reachable": True, "new_completed_bar_available": False})

    module.append_rows(output_path, [row])
    module.append_rows(output_path, [row])

    with output_path.open(newline="", encoding="utf-8") as handle:
        lines = handle.readlines()
    assert lines[0].strip() == ",".join(module.FIELDS)
    assert len(lines) == 3  # header + 2 appended rows, no duplicate header


def test_write_timing_analysis_reads_back_appended_rows(tmp_path) -> None:
    module = _module()
    observations_path = tmp_path / "provider_timing_observations.csv"
    analysis_path = tmp_path / "scheduler_timing_analysis.json"
    row = {field: None for field in module.FIELDS}
    row.update(
        {
            "observation_timestamp_utc": "2026-08-24T06:00:00+00:00", "instrument": "EURUSD_AV", "day_of_week": "Monday",
            "provider_latest_date": "2026-08-23", "provider_reachable": True, "new_completed_bar_available": True,
        }
    )
    module.append_rows(observations_path, [row])

    result = module.write_timing_analysis(observations_path, analysis_path)

    assert analysis_path.exists()
    assert result["observation_count"] == 1
    assert result["weekday_observation_count"] == 1


def test_default_instruments_match_the_frozen_protocol_cohort() -> None:
    module = _module()
    assert set(module.DEFAULT_INSTRUMENTS) == {"EURUSD_AV", "GBPUSD_AV", "USDJPY_AV", "AUDUSD_AV", "BTCUSD_AV", "ETHUSD_AV"}
    assert module.DEFAULT_INSTRUMENTS["EURUSD_AV"] == ("EUR/USD", "forex")
    assert module.DEFAULT_INSTRUMENTS["BTCUSD_AV"] == ("BTC/USD", "crypto")
