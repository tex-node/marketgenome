# Yahoo Finance pilot study

Yahoo Finance is configured only as `PILOT_AND_RESEARCH_SOURCE`.

It is not treated as an authoritative institutional feed, and a Yahoo-backed study must remain `PILOT_ONLY` until replicated with a second independent source such as broker data, exchange APIs, licensed datasets, or another documented public dataset.

Provider manifest:

```text
research/data/manifests/yahoo_market_data_pilot_v1.yaml
```

Pilot study manifest:

```text
research/studies/yahoo_multi_asset_pilot_v1.yaml
```

Local dry run:

```powershell
market-genome data fetch-yahoo .\research\data\manifests\yahoo_market_data_pilot_v1.yaml --dry-run
```

Acquisition:

```powershell
market-genome data fetch-yahoo .\research\data\manifests\yahoo_market_data_pilot_v1.yaml
```

Import review:

```powershell
market-genome data import-manifest .\research\data\manifests\yahoo_market_data_pilot_v1.yaml --dry-run
market-genome data quality-report --manifest yahoo_market_data_pilot_v1
```

Guardrail:

Do not run validation, final-test lock, or final test from the Yahoo pilot script. The script stops after preflight.

Yahoo-specific warnings include:

- `PROVIDER_DATA_RESEARCH_ONLY`
- `POSSIBLE_RETROACTIVE_PROVIDER_REVISION`
- `PRICE_ADJUSTMENT_PROVIDER_CONTROLLED`
- `FUTURES_CONTINUOUS_CONTRACT_UNVERIFIED`
- `FOREX_VOLUME_UNAVAILABLE`
- `CRYPTO_SINGLE_VENUE_OR_AGGREGATED_SOURCE`

If a Yahoo pilot result appears promising, replicate it with a second independent data source before considering any formal out-of-sample claim.
