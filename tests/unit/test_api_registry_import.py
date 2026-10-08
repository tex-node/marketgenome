from pathlib import Path

from fastapi.testclient import TestClient
from market_genome_api.main import app
from sqlalchemy.orm import Session


def test_registry_api_and_csv_import(api_session: Session) -> None:
    client = TestClient(app)

    instrument_response = client.post(
        "/api/v1/instruments",
        json={"symbol": "BTCUSDT", "exchange": "BINANCE", "asset_class": "crypto"},
    )
    assert instrument_response.status_code == 200
    assert client.get("/api/v1/instruments").json()[0]["symbol"] == "BTCUSDT"

    path = Path("tests/fixtures/sample_ohlcv.csv")
    with path.open("rb") as handle:
        response = client.post(
            "/api/v1/data/imports/csv",
            data={
                "symbol": "ETHUSDT",
                "asset_class": "crypto",
                "exchange": "BINANCE",
                "timezone": "UTC",
                "timeframe": "H1",
                "timeframe_seconds": "3600",
                "source_name": "BINANCE_CSV",
            },
            files={"file": ("sample_ohlcv.csv", handle, "text/csv")},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["rows_inserted"] == 20
    assert client.get("/api/v1/data/imports").status_code == 200

