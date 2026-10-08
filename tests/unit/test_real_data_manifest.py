from __future__ import annotations

import json
from pathlib import Path

from market_genome_data_ingestion.manifest import (
    analyze_dataset_quality,
    import_manifest,
    load_data_manifest,
    manifest_hash,
)
from market_genome_domain.models import DataImport
from sqlalchemy.orm import Session


def _write_csv(path: Path, rows: list[str]) -> None:
    path.write_text("timestamp,open,high,low,close,volume\n" + "\n".join(rows) + "\n", encoding="utf-8")


def _manifest(path: Path, csv_path: Path, minimum_rows: int = 3) -> dict:
    payload = {
        "manifest": {"code": "unit_real_data", "version": "data_manifest_v1"},
        "quality_thresholds": {"extreme_return_threshold": 0.20, "split_event_threshold": 0.45, "bad_tick_threshold": 0.60},
        "datasets": [
            {
                "code": "AAA_D1",
                "symbol": "AAA",
                "name": "AAA",
                "asset_class": "equity",
                "exchange": "TEST",
                "currency": "USD",
                "timezone": "UTC",
                "timeframe": "D1",
                "timeframe_seconds": 86400,
                "source": "USER_CSV",
                "path": str(csv_path),
                "volume_type": "shares",
                "price_adjustment": "raw",
                "minimum_rows": minimum_rows,
            }
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return payload


def test_manifest_hash_and_validation(tmp_path: Path) -> None:
    csv_path = tmp_path / "AAA.csv"
    _write_csv(csv_path, ["2020-01-01,100,101,99,100,10", "2020-01-02,101,102,100,101,11", "2020-01-03,102,103,101,102,12"])
    manifest_path = tmp_path / "manifest.yaml"
    payload = _manifest(manifest_path, csv_path)

    loaded = load_data_manifest(manifest_path)

    assert loaded["manifest"]["code"] == "unit_real_data"
    assert loaded["_manifest_hash"] == manifest_hash(payload)


def test_batch_dry_run_and_import_idempotency(tmp_path: Path, db_session: Session) -> None:
    csv_path = tmp_path / "AAA.csv"
    _write_csv(csv_path, ["2020-01-01,100,101,99,100,10", "2020-01-02,101,102,100,101,11", "2020-01-03,102,103,101,102,12"])
    manifest_path = tmp_path / "manifest.yaml"
    _manifest(manifest_path, csv_path)
    manifest = load_data_manifest(manifest_path)

    dry = import_manifest(db_session, manifest, dry_run=True)
    first = import_manifest(db_session, manifest, dry_run=False)
    second = import_manifest(db_session, manifest, dry_run=False)

    assert dry[0].quality_decision == "ACCEPTED"
    assert first[0].import_id == second[0].import_id
    assert db_session.query(DataImport).filter(DataImport.dry_run.is_(False)).count() == 1


def test_quality_decisions_and_suspicious_discontinuities(tmp_path: Path) -> None:
    csv_path = tmp_path / "BAD.csv"
    _write_csv(
        csv_path,
        [
            "2020-01-01,100,101,99,100,10",
            "2020-01-01,100,101,99,100,10",
            "2020-01-03,100,80,99,200,",
            "2020-01-02,-1,101,99,100,0",
        ],
    )
    manifest_path = tmp_path / "manifest.yaml"
    manifest = _manifest(manifest_path, csv_path)
    loaded = {**manifest, "_manifest_path": str(manifest_path)}

    report = analyze_dataset_quality(loaded, loaded["datasets"][0])

    assert report.quality_decision in {"MANUAL_REVIEW_REQUIRED", "REJECTED"}
    assert report.duplicates >= 1
    assert report.invalid_ohlc >= 1
    assert report.non_positive_prices >= 1
    assert report.missing_volume_rate > 0
    assert report.extreme_one_bar_returns >= 1
