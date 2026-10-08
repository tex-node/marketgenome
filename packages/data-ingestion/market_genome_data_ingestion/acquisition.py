from __future__ import annotations

import json
import os
from dataclasses import replace
from pathlib import Path
from typing import Any

from market_genome_shared.hashing import sha256_canonical

from market_genome_data_ingestion.providers import (
    HistoricalDataRequest,
    get_provider,
    list_providers,
)

SUPPORTED_PROVIDER_CODES = {"yahoo_finance_v1", "alpha_vantage_v1"}


def load_provider_manifest(path: Path) -> dict[str, Any]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    validate_provider_manifest(manifest)
    manifest["_manifest_path"] = str(path)
    manifest["_manifest_hash"] = provider_manifest_hash(manifest)
    return manifest


def provider_manifest_hash(manifest: dict[str, Any]) -> str:
    return sha256_canonical({key: value for key, value in manifest.items() if not key.startswith("_")})


def validate_provider_manifest(manifest: dict[str, Any]) -> None:
    provider = manifest.get("provider", {}).get("code")
    if provider not in SUPPORTED_PROVIDER_CODES:
        raise ValueError("UNSUPPORTED_PROVIDER")
    acquisition = manifest.get("acquisition", {})
    if acquisition.get("interval") != "1d":
        raise ValueError("UNSUPPORTED_INTERVAL")
    if acquisition.get("start") >= acquisition.get("end"):
        raise ValueError("INVALID_DATE_RANGE")
    instruments = manifest.get("instruments")
    if not isinstance(instruments, list) or not instruments:
        raise ValueError("PROVIDER_MANIFEST_INSTRUMENTS_REQUIRED")


def requests_from_manifest(
    manifest: dict[str, Any],
    *,
    symbol: str | None = None,
    start: str | None = None,
    end: str | None = None,
    output_directory: Path | None = None,
    delay_seconds: float | None = None,
    maximum_retries: int | None = None,
    new_version: str | None = None,
    force_refresh: bool = False,
) -> list[HistoricalDataRequest]:
    acquisition = manifest["acquisition"]
    manifest_path = Path(manifest.get("_manifest_path", ".")).resolve()
    data_root = os.environ.get("MARKET_GENOME_DATA_ROOT")
    output = output_directory or (
        (Path(data_root) / "raw" / manifest["manifest"]["code"]).resolve()
        if data_root
        else (manifest_path.parent / ".." / "raw" / manifest["manifest"]["code"]).resolve()
    )
    requests = []
    for item in manifest["instruments"]:
        if not item.get("enabled", True):
            continue
        if symbol and symbol not in {item["provider_symbol"], item["canonical_symbol"]}:
            continue
        asset = item["asset_class"]
        basis = item.get("price_adjustment_basis")
        if basis is None:
            basis = "provider_auto_adjusted" if acquisition.get("auto_adjust", True) else "provider_unadjusted"
        requests.append(
            HistoricalDataRequest(
                provider_symbol=item["provider_symbol"],
                canonical_symbol=item["canonical_symbol"],
                instrument_name=item["name"],
                asset_class=asset,
                exchange=item["exchange"],
                currency=item["currency"],
                timezone=item["timezone"],
                timeframe=item["timeframe"],
                start=start or acquisition["start"],
                end=end or acquisition["end"],
                auto_adjust=bool(acquisition.get("auto_adjust", True)),
                include_actions=bool(acquisition.get("actions", True)),
                volume_type=item["volume_type"],
                price_adjustment_basis=basis,
                output_directory=output,
                dataset_version=new_version or str(acquisition.get("dataset_version", "v1")),
                delay_seconds=float(delay_seconds if delay_seconds is not None else acquisition.get("delay_seconds", 2)),
                maximum_retries=int(maximum_retries if maximum_retries is not None else acquisition.get("retries", 3)),
                force_refresh=force_refresh,
                new_version=new_version,
            )
        )
    return requests


def acquisition_plan(manifest: dict[str, Any], **kwargs: Any) -> list[dict[str, Any]]:
    provider = get_provider(manifest["provider"]["code"])
    return [
        provider.dry_run(request) if hasattr(provider, "dry_run") else request.__dict__
        for request in requests_from_manifest(manifest, **kwargs)
    ]


def fetch_manifest(manifest: dict[str, Any], **kwargs: Any) -> list[dict[str, Any]]:
    provider = get_provider(manifest["provider"]["code"])
    results = []
    for request in requests_from_manifest(manifest, **kwargs):
        try:
            results.append(provider.fetch(request).as_dict())
        except Exception as exc:  # noqa: BLE001
            results.append(
                {
                    "provider_code": manifest["provider"]["code"],
                    "provider_symbol": request.provider_symbol,
                    "canonical_symbol": request.canonical_symbol,
                    "status": classify_provider_error(exc),
                    "error": str(exc),
                }
            )
    return results


def classify_provider_error(exc: Exception) -> str:
    message = str(exc)
    if "EMPTY_RESPONSE" in message:
        return "EMPTY_RESPONSE"
    if "UNSUPPORTED_INTERVAL" in message:
        return "UNSUPPORTED_INTERVAL"
    if "NON_POSITIVE_PRICES" in message:
        return "CANONICALIZATION_FAILED"
    if "HASH" in message:
        return "HASH_FAILED"
    if "IMMUTABLE" in message:
        return "IMMUTABLE_ACQUISITION_REJECTED"
    if "YFINANCE_NOT_INSTALLED" in message:
        return "PROVIDER_UNAVAILABLE"
    if "RATE_LIMITED" in message:
        return "PROVIDER_RATE_LIMITED"
    if "PREMIUM_ENDPOINT_REQUIRED" in message:
        return "PROVIDER_ENDPOINT_REQUIRES_PREMIUM"
    if "ALPHA_VANTAGE_API_KEY_NOT_CONFIGURED" in message:
        return "PROVIDER_API_KEY_NOT_CONFIGURED"
    if "UNSUPPORTED_ASSET_CLASS" in message:
        return "UNSUPPORTED_ASSET_CLASS"
    return "PROVIDER_UNAVAILABLE"


def provider_catalog() -> list[dict[str, str]]:
    return list_providers()


def with_output_directory(request: HistoricalDataRequest, output_directory: Path) -> HistoricalDataRequest:
    return replace(request, output_directory=output_directory)
