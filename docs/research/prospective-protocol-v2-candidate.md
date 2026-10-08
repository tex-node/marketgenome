# Prospective Protocol v2 — Candidate (NOT ACTIVATED)

**Status: CANDIDATE / PRE-REGISTERED ON PAPER ONLY.** `market_context_forecast_v2` is defined in code (`packages/prospective/market_genome_prospective/definitions.py`) but is held in a **separate candidate registry** (`CANDIDATE_PROSPECTIVE_PROTOCOLS`). It is not in `PROSPECTIVE_PROTOCOLS`, is not returned by `list_prospective_protocol_definitions()`, is not exposed by the CLI `prospective protocols` or the API, and `get_prospective_protocol_definition()` raises for it — so it **cannot be frozen or listed through any normal path** until deliberately promoted. Regression-guarded by `tests/unit/test_prospective_definitions.py`.

This document exists so a v2 can be ready to freeze if/when the v1 verdict lands. It is **not** an activation and must not be treated as evidence of anything.

## Why v2 exists

- v1 (`market_context_forecast_v1`) hard-switches between context levels at a 30-sample minimum, then Laplace-smooths the chosen level toward 0.5.
- Step 10A.4 (historical) showed context carries real information (skill vs unconditional ≈ +0.22) while Market DNA adds none. The prospective primary-horizon readout, however, is ≈ 0/slightly negative.
- A plausible, principled explanation is **estimator variance**, not absence of signal: with `minimum_historical_sample=30`, the most specific context level (`trend_volatility`) is either used from a noisy count or discarded entirely. v2 replaces the hard switch + Laplace prior with a single **hierarchical shrinkage** estimator. This rationale is statistical and was chosen **without** fitting to prospective outcomes.

## The single change (v2 relative to v1)

Everything else is frozen identically, so a v2-vs-v1 difference is attributable to the estimator alone.

Estimator: **Beta-Binomial hierarchical shrinkage**

```
p_hat = (k + m * p0) / (n + m)
```

- `k`, `n` — positive / total count at the most specific context level (`trend_volatility`), evaluated strictly **as-of the forecast's own data cutoff**.
- `p0` — the unconditional base rate, also as-of the forecast's cutoff.
- `m = 20.0` — fixed `prior_strength` (pseudo-count), declared here and never tuned against outcomes.

Consequences: the estimate degrades smoothly toward the unconditional rate as `n → 0` and approaches the raw context frequency as `n → ∞`; there is no discontinuity at any sample threshold, so `minimum_historical_sample = 0`. The fallback hierarchy remains declared for provenance/diagnostics only.

## Frozen configuration (identical to v1 except the estimator)

| Field | Value |
|---|---|
| Context definition | `trend_volatility` |
| Fallback hierarchy | `trend_volatility -> trend_only -> unconditional` |
| Timeframe | `D1` |
| Window lengths | 16, 32, 64 |
| Primary horizon | 20 (secondary: 5, 10 — transparency only) |
| Probability method | `context_conditioned_hierarchical_shrinkage_v2` |
| Smoothing method | `beta_binomial_hierarchical_shrinkage_v2` (`prior_strength=20.0`) |
| Minimum historical sample | 0 (shrinkage replaces the hard minimum) |
| Calibration | `none` |
| Provider | `alpha_vantage_v1` |
| Instruments | `EURUSD_AV, GBPUSD_AV, USDJPY_AV, AUDUSD_AV, BTCUSD_AV, ETHUSD_AV` |
| Evidence gates | 100 minimum / 250 preferred matured primary-horizon forecasts |

## Success / failure criteria (pre-registered)

- **SUPPORTED** only if, on **primary-horizon** matured forecasts: `matured_count >= 250`, `brier_skill_vs_unconditional > 0`, and the paired block-bootstrap `ci_low > 0`.
- **Confirmatory secondary**: v2's primary-horizon Brier skill must exceed v1's on the same evaluation basis (`must_beat_v1_estimator`). If v2 does not beat v1, the estimator change is not supported even if v2 clears its own bar.
- **NOT_SUPPORTED** if `brier_skill_vs_unconditional <= 0` at the evidence gate; `WEAK` for positive-but-unconfirmed; `ACCUMULATING` below the minimum.
- No Market DNA, no AI/ML model, no trading/execution logic — unchanged from v1.

## Prerequisites before v2 may be frozen (none of these exist yet)

1. **Estimator implementation.** `historical_probability` currently always applies Laplace smoothing from `smoothing_parameters` regardless of `smoothing_method`; a v2 shrinkage path keyed off the method name must be implemented and unit-tested before freezing.
2. **Freeze lineage.** `freeze_protocol` today hardcodes the Step 10A.4 `context_dna_incremental_value_v1` replication protocol/record as the source. v2's lineage should instead be the **v1 prospective protocol and its verdict**, so the freeze path must be generalized.
3. **Baseline-as-of-cutoff.** `create_evaluation_snapshot` must compute the unconditional baseline as-of each forecast's own cutoff, as the protocol specifies. **Done 2026-09-15** (`service.py` now uses `forecast.data_cutoff_timestamp`; regression-tested). Its effect on the current readout was small (primary-horizon skill -0.0917 -> -0.0904), confirming the historical-vs-prospective gap is not a baseline-timing artifact.

## Alternatives considered and deferred

- **`context_family` as primary** — near-identical Step 10A.4 performance; deferred as a v3 variant, not bundled into v2.
- **Extra context dimensions** (`persistence`, `market_phase`) — changes the representation, not just the estimator; deferred.
- **Post-hoc calibration layer** — improves reliability (ECE) but not Brier skill vs unconditional; deferred to a separate protocol.
- **Expected-return magnitude** — still `null`; a separate, explicitly-reviewed decision.

## Promotion procedure (when authorized)

1. Satisfy the prerequisites above; correct the baseline timing.
2. Move `MARKET_CONTEXT_FORECAST_V2` into `PROSPECTIVE_PROTOCOLS` and update the candidate/inertness tests.
3. `market-genome prospective create-protocol --protocol market_context_forecast_v2` (freeze).
4. The v2 evidence clock starts at freeze; v1 evidence and its verdict are left untouched and must never be re-scored under v2 rules.
