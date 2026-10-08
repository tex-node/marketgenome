# Market Genome session

Date: 2026-08-21

## NEXT CHECKPOINT — decision-point review when primary-horizon evidence reaches 250

- **Trigger:** latest `prospective_evaluation_snapshots` has `primary_horizon_matured_count >= 250` (protocol `market_context_forecast_v1`).
- **Expected date:** ~2026-10-05/06 (at ~18-21 matured/day; it was 201 on 2026-10-02). The daily systemd timer continues to 250 automatically; no human intervention should happen *before* this gate.
- **At the gate — execute the pre-registered review (do NOT rationalize after seeing the CI):**
  1. Record the final `status`, `brier_skill_vs_unconditional`, `bootstrap_ci_low`, `bootstrap_ci_high`, `expected_calibration_error`, `direction_accuracy`, `balanced_accuracy`, `mcc` at the 250 snapshot.
  2. Pull per-instrument and per-asset-class breakdowns: 6 instruments (EURUSD/GBPUSD/USDJPY/AUDUSD/BTCUSD/ETHUSD_AV) and 2 asset classes (FX/crypto), each independently evaluated at the primary horizon against its own as-of-cutoff unconditional base rate; confirm the skill is **consistent across instruments/classes**, not driven by one.
  3. Check episode/diversity integrity as in prior cohorts: confirm matured forecasts are genuine `TRUE_PROSPECTIVE`, chain-of-custody and temporal integrity hold across the whole matured set, and `data_revision_detected = false` throughout.
  4. Apply the frozen `classify_prospective_decision` rule verbatim to the recorded verdict; do not re-derive it.
- **Pre-agreed verdict mapping (decided 2026-09-27, before reaching 250):**
  - `SUPPORTED` (CI-low crosses 0 at >=250) -> context signal validated prospectively; v2 candidate may then be promoted for *improvement* research on its own fresh clock.
  - `NOT_SUPPORTED` (CI-high <= 0 at >=250) -> context signal is not better than the base rate prospectively; v2 shrinkage candidate (or other hypothesis) becomes the primary research path.
  - Still `WEAK` (CI spans 0 at 250) -> inconclusive; **extend the evidence gate** (e.g. to 350/500) rather than re-specify the estimator; no methodology change.
- **What must NOT happen:** changing the protocol, context definition, horizons, window lengths, or any frozen config in response to the 250 outcome. That is the early-result firewall; the verdict governs what research comes *next*, not what we re-tune *now*.
- **On this session's close:** if a new day's snapshot has already been pulled, re-run the checkpoint procedure at the first snapshot >= 250.
- **Reference commands:**
  - snapshot row: `docker exec -i market-genome-postgres-1 psql -U market_genome -d market_genome -At -c "select ... from prospective_evaluation_snapshots order by created_at desc limit 1"`
  - latest per-horizon: read `prospective_report.md` (auto-regenerated daily).

## Latest state — Phase 1 Step 10A.3 Independent Data Replication infrastructure (engineering complete, acquisition blocked pending credential)

- Provider chosen for independent replication: Alpha Vantage (`alpha_vantage_v1`), classified `INDEPENDENT_PUBLIC_MARKET_DATA_PROVIDER` / `provider_independence=CONFIRMED`. Stooq was ruled out: its download endpoint now sits behind a JavaScript proof-of-work bot-detection challenge, which was not bypassed.
- Confirmatory universe is 10 of the original 13 Yahoo-pilot instruments: SPY, QQQ, DIA, IWM (equity ETFs), EURUSD, GBPUSD, USDJPY, AUDUSD (FX), BTCUSD, ETHUSD (crypto), all suffixed `_AV`. Gold, Silver, and Copper are explicitly excluded from the primary replication universe and documented as such: Alpha Vantage has no daily OHLC series for gold/silver at all, and its free-tier `COPPER` series is a monthly global price index, not daily continuous-futures OHLC — this is a declared exclusion per the protocol's own rule, not a silent substitution.
- Added `alpha_vantage_v1` provider adapter at `packages/data-ingestion/market_genome_data_ingestion/providers/alpha_vantage.py`: `TIME_SERIES_DAILY` for equity ETFs (raw/unadjusted, `price_adjustment_basis=provider_unadjusted_raw`), `FX_DAILY` for forex (volume unavailable, flagged), `DIGITAL_CURRENCY_DAILY` for crypto (flagged as provider-composite/unspecified venue); commodity asset classes raise `UNSUPPORTED_ASSET_CLASS_ALPHA_VANTAGE_NO_DAILY_OHLC` rather than silently degrading. Uses stdlib `urllib` (no new dependency). Detects and distinguishes rate-limit vs premium-endpoint vs empty responses without retrying definitive provider-level rejections. Reuses the same immutable-acquisition (hash/provenance sidecar) pattern as the Yahoo provider.
- Generalized the provider registry (`providers/base.py`, `acquisition.py`) from Yahoo-only to a `SUPPORTED_PROVIDER_CODES` set; `classify_provider_error` extended with Alpha Vantage-specific codes.
- Added `research/data/manifests/independent_replication_v1.yaml` (10-instrument Alpha Vantage manifest, excluded-instrument list with reasons) and `research/studies/independent_robust_dna_replication_v1.yaml` (new, separate `StudyManifest`; `independent_replication_required: false` since this study itself is the independent replication; links to the Yahoo source study/experiment IDs via a `provenance` block).
- Added new package `packages/replication/market_genome_replication` (`definitions.py`, `service.py`) implementing the frozen `ReplicationProtocolDefinition` for `independent_robust_dna_replication_v1` (hypothesis text, primary config: `dna_robust_cosine_v1`/`same_instrument`/K=10/`uniform_v1`/episode_cap=1/horizon=20/windows=[16,32,64], 4 frozen controls, success/failure criteria) and a `ReplicationService` with `freeze_protocol()`, `create_lock()`, `create_record()`, `decide()` — all idempotent and immutability-guarded (a frozen protocol's configuration cannot be silently changed; a decided record cannot be retuned by calling `decide()` again). Added a pure `classify_replication_decision()` function implementing the `REPLICATION_SUPPORTED` / `REPLICATION_PARTIAL` / `REPLICATION_NOT_SUPPORTED` / `REPLICATION_INCONCLUSIVE` vocabulary, unit-tested independently of the database.
- Added persisted `ReplicationProtocol`, `ReplicationLock`, `ReplicationRecord` models and Alembic migration `0012_independent_replication` (linear after `0011_window_continuity_policy_identity`).
- Added `market-genome replication ...` CLI group: `definitions`, `freeze-protocol`, `lock`, `record`, `inspect`.
- Extended `market-genome data provider-smoke` to support `alpha_vantage_v1` (bounded, unpersisted fetch through the real provider abstraction) alongside the existing Yahoo path.
- Added descriptive cross-provider QA at `packages/data-ingestion/market_genome_data_ingestion/cross_provider_qa.py` (`compare_price_series` / `compare_canonical_files`: matched/missing timestamps, close-return correlation, median/p95 absolute return difference, price-scale ratio, large-discrepancy count, `OK`/`REVIEW_REQUIRED`/`INSUFFICIENT_OVERLAP` quality flag) and `market-genome data compare-providers` CLI command.
- Added `research/experiments/independent_replication_v1.yaml` (narrow confirmatory config: 1 primary method + 4 controls, single arm `same_instrument`, single horizon 20, K=10 only, weighting uniform only, episode cap 1 only — deliberately not a parameter search) and `scripts/run_independent_replication.py`, a narrower sibling of `scripts/run_yahoo_pilot_validation.py` that freezes the protocol/lock/record before evaluation, runs the primary method and 4 controls only, reports per-window-length and pooled-across-windows results separately, computes a Yahoo-vs-independent comparison by reading the Yahoo experiment's persisted `method_summary.csv` artifact, and applies `classify_replication_decision`. Not yet executed (requires real data + Postgres).
- Expanded tests from 134 to 160 passing: `test_alpha_vantage_provider.py` (10), `test_replication_service.py` (12), `test_cross_provider_qa.py` (4).
- Latest verification: `python -m pytest -q` passed with 160 tests; `python -m ruff check .` passed; `python -m alembic -c infrastructure/alembic.ini history` shows a linear chain through `0012_independent_replication (head)`; `docker compose config --quiet` passed; CLI smoke checks passed for `--help` on `data`, `studies`, `experiments`, `similarity`, `replication`; `market-genome data provider-show alpha_vantage_v1` and a dry-run `fetch-manifest` against the new manifest both succeeded and correctly reported `DRY_RUN_MISSING_API_KEY` (no key configured yet).
- PostgreSQL migration `0011 -> 0012` was NOT verified against real PostgreSQL (Docker Desktop still unavailable locally); this remains pending VPS verification.
- VPS `raivstream` checked read-only: `/opt/market-genome/app` is not a git repository (was deployed by direct file sync, not `git clone`), disk free is now ~19GB (down from ~22GB after the Yahoo pilot), memory has ~3.7GB free / ~5.7GB available, and no Market Genome containers are currently running there. No code was deployed or synced to the VPS this session.
- No Alpha Vantage API key is configured anywhere (checked `.env.example`, local shell env, and the VPS `.env`) — none was found. No data was acquired. No Postgres-backed run occurred locally or on the VPS.

## Latest Step 10A.3 update — real acquisition and cross-provider QA completed locally

- User supplied a free Alpha Vantage API key (via local `env.txt`, now covered by `.gitignore`; key never committed, never printed in any output/artifact).
- Discovery: this key's free tier gates `outputsize=full` on `TIME_SERIES_DAILY` (equities/ETFs) behind a premium plan; the free `outputsize=compact` fallback returns only the last 100 daily bars, far short of study requirements. `FX_DAILY` and `DIGITAL_CURRENCY_DAILY` are NOT similarly gated — both returned full multi-year history on the free key.
- User decision: proceed with FX + crypto only. Equity ETFs (SPY/QQQ/DIA/IWM) were moved to `excluded_instruments`/`excluded_from_universe` in `research/data/manifests/independent_replication_v1.yaml` and `research/studies/independent_robust_dna_replication_v1.yaml` with reason `ALPHA_VANTAGE_FREE_TIER_REQUIRES_PREMIUM_FOR_OUTPUTSIZE_FULL_ON_TIME_SERIES_DAILY`. `study_quality_gate.minimum_asset_classes` relaxed 3 -> 2 and `minimum_instruments_overall` 8 -> 5, decided from a pre-acquisition dry-run before any real replication data was touched, not after seeing results.
- Fixed a real generalization gap found along the way: `datasets_from_provider_manifest` and `analyze_dataset_quality` in `packages/data-ingestion/market_genome_data_ingestion/manifest.py` were hardcoded to `yahoo_finance_v1`; generalized both to also recognize `alpha_vantage_v1` (new `PROVIDER_SOURCE_NAMES` map, asset-class-driven warning flags instead of Yahoo ticker-suffix sniffing). All 160 tests still pass after this change.
- Acquired real data for the 6-instrument confirmatory universe (EURUSD, GBPUSD, USDJPY, AUDUSD, BTCUSD, ETHUSD, all `_AV` suffixed) into `research/data/raw/independent_replication_v1/`: 5000 rows each for the 4 FX pairs (2007-06-21 to 2026-08-20), 5880 rows for BTCUSD (2010-07-17 start), 4032 rows for ETHUSD (2015-08-08 start). All COMPLETED, immutable-acquisition provenance sidecars written.
- Ran local (DB-independent) data-quality analysis via `analyze_manifest_quality`: all 6 datasets `ACCEPTED_WITH_WARNINGS`, zero hard rejections (no duplicates, no out-of-order rows, no invalid OHLC, no non-positive prices). Warnings are all expected/benign categories (research-only provider, provider-controlled adjustment, forex volume unavailable, crypto single-venue/aggregated, some extreme-return/split-event/bad-tick flags on BTC/ETH consistent with known crypto volatility history).
- Also fetched the 6 Yahoo-side equivalents locally (already cached from an earlier session) and ran real cross-provider QA (`market-genome data compare-providers`) for all 6 pairs, saved under `research/reports/independent_replication_v1/cross_provider_qa/`:
  - **Crypto: OK.** BTCUSD and ETHUSD show close-return correlation ~0.99-0.995 same-day, price-scale ratio ~1.000, consistent with both providers sourcing genuine aggregated-market daily closes.
  - **FX: REVIEW_REQUIRED, diagnosed as a benign day-boundary/session convention difference, not a data-integrity problem.** All 4 FX pairs show price-scale ratios extremely close to 1.0 (0.9997-1.0001, strong evidence it is genuinely the same instrument) but same-day close-return correlation only 0.27-0.44. A lag-correlation test (EURUSD) showed correlation rises to 0.52 when Alpha Vantage's series is shifted by +1 day relative to Yahoo's, indicating the two providers snapshot "the daily close" at different points in the continuous 24/5 FX session (Yahoo and Alpha Vantage evidently use different daily-bar timestamp conventions for FX) -- not fully resolved by a clean integer shift, so genuine session-timing differences remain beyond a single day's misalignment. This does not invalidate the replication: the same-instrument retrieval methodology only requires each provider's own series to be an internally consistent representation of that instrument, not bar-for-bar alignment with Yahoo's.
- No Postgres-backed step (window/normalization/DNA/context/outcome build, study preflight, or `run_independent_replication.py`) has been run yet -- these require Postgres, which is unavailable locally, so they must run on the VPS. No code or data has been synced to the VPS this session; VPS deployment/execution is pending explicit go-ahead.

## Phase 1 Step 10A.3 completion — INDEPENDENT_REPLICATION_COMPLETED, decision REPLICATION_PARTIAL

- Yahoo source study ID: `d608a16b-b586-44ea-bcdc-d930957bdeeb`. Yahoo source experiment ID: `a9390628-2efd-48ed-bcae-90bbd161d74f`. Both verified intact and unmodified before and after this phase (`decision=PILOT_RETRIEVAL_PROMISING` unchanged).
- Replication protocol ID: `67953fda-137b-4f7d-a77b-14135e845d74`, frozen 2026-08-21T17:21:21Z, configuration hash `eaa109eddc8cc7e19f448ba2135aaace1d80608e895ac6847a1ad244300902b7`, immutability-guarded (verified in local tests that a second freeze attempt with a tampered hash is rejected).
- Independent provider: Alpha Vantage (`alpha_vantage_v1`), `provider_independence=CONFIRMED`.
- Independent study ID: `7b2e3649-0d69-4135-890c-b8db698b59e2`. Dataset hash `bdbc31a31596afc9590f709cd8a83ef6d58767d10b6c567087158898f9921209`.
- Instrument universe: 6 instruments, 2 asset classes -- EURUSD_AV, GBPUSD_AV, USDJPY_AV, AUDUSD_AV (forex), BTCUSD_AV, ETHUSD_AV (crypto). Equity ETFs (SPY/QQQ/DIA/IWM) and commodities (Gold/Silver/Copper) excluded with documented reasons (Alpha Vantage free-tier `outputsize=full` requires premium for equities; no daily gold/silver OHLC exists at all; free-tier copper is a monthly index). `study_quality_gate.minimum_asset_classes` relaxed 3->2 and `minimum_instruments_overall` 8->5 before any data was touched.
- Replication lock ID: `3d43d19a-dd20-4381-af6e-15d7322aeb71`.
- Replication experiment ID: `bf59b66f-334a-4f7e-954d-b29d0938a8f6`. Replication record ID: `15673493-ccbc-4c23-a85d-4f204fc84280`.
- Representation versions matched the frozen protocol exactly: window_v1, normalization_v1 (anchored_log_return, 64 points, linear resampling), market_dna_v1, transparent_context_v1, forward_outcomes_v1. Primary method `dna_robust_cosine_v1`, arm `same_instrument`, K=10, weighting `uniform_v1`, episode cap 1, horizon 20 bars, window lengths [16, 32, 64].
- Query sampling density (`query_sample_per_instrument_window`) raised from the Yahoo config's value of 1 to 150 after the pre-evaluation dry-run showed only 6 total queries per window length under the narrow 1-primary+4-control design (vs the Yahoo validation's ~20-method broad grid, where 1 query/instrument still produced thousands of rows). This was a statistical-power correction made from dry-run *counts* only, before any outcome/effect metric was inspected -- not a post-hoc retune.
- Preflight: `READY_FOR_FORMAL_STUDY`, zero blockers. 146,614 eligible queries, 115,751 unique episodes, largest-episode-share ~0.003% (excellent diversity), complete-outcome rate 99.5%.
- Primary evaluation: 2,700 pooled query-horizon evaluations (900 per window length x 3 window lengths).

**Primary pooled result:**
- Brier score: 0.28193
- Brier skill vs unconditional: **+0.1204** (positive, same direction as Yahoo's +0.2477, attenuated to about half the magnitude)
- Brier skill vs same-context random: **-0.0050** (essentially zero -- fails to beat the context-only baseline)
- Direction accuracy: 0.5156 (vs Yahoo's 0.6410 -- barely above chance)
- Expected calibration error: 0.1349

**Per-asset-class:** in both FX (1,800 rows) and crypto (900 rows) separately, `dna_robust_cosine_v1` clearly beat `unconditional_outcome_v1` (FX skill +0.117, crypto skill +0.127) but was statistically indistinguishable from `same_context_random_v1` (FX skill -0.010, crypto skill +0.004). This is the same pattern in both asset classes independently, not an artifact of pooling.

**Per-instrument:** positive skill vs unconditional in 5 of 6 instruments (AUDUSD +0.017, BTCUSD +0.163, ETHUSD +0.023, EURUSD +0.229, USDJPY +0.225; GBPUSD essentially flat at +0.007) -- not driven by a single instrument.

**Decision: `REPLICATION_PARTIAL`.** Rationale: positive, same-direction skill vs unconditional history replicated cleanly across both independent asset classes and 5 of 6 instruments; the additional value of DNA-shape-based similarity over simple same-context conditioning did not replicate on independent data. Interpretation: conditioning retrieval on market context (trend/volatility state) carries real, reproducible information; the specific contribution of `dna_robust_cosine_v1`'s vector similarity on top of that context did not clearly hold up independently.

**Known reporting gap:** the primary metric's time-block bootstrap confidence interval was computed internally (`bootstrap_ci`) and used correctly in the decision logic, but was not persisted as a `bootstrap_confidence.csv` artifact or separate report field -- per-query evaluation rows aren't persisted to the database (only aggregates), so recovering the exact interval now would require a full rerun against the same untouched dataset. Flagged as a known limitation of this run's reporting, not a defect in the decision itself.

**Verification:** source-layer mutation check passed (`price_bars`, `pattern_windows`, `normalized_patterns`, `market_dna`, `market_contexts`, `outcome_observations`, `study_episodes` counts identical before/after). Pre-run backup `market_genome_20260821T102104Z.sql`, SHA-256 `b6bc61a8f72ae726e3f14c426c55fc719c9e9d44b2be8aad643aafb692024662`. Post-run backup `market_genome_20260821T172925Z.sql`, SHA-256 `b46e578448feeffb9908b4fd5e2397b890f81dc593945b853d3f33655fb56a02`.

**Infrastructure notes from this run:**
- Fixed two more hardcoded-revision bugs found along the way (matching the earlier `datasets_from_provider_manifest` fix): `scripts/verify_postgres_runtime.py` and `MultiAssetStudyService._postgres_runtime_verified()` both pinned `"0011_window_continuity_policy_identity"` as the expected head; updated both to `0012_independent_replication` and added the three new replication tables/indexes to the verification script's required set.
- VPS disk hit 98% full (3.9GB free) mid-session from 62GB of accumulated Postgres backup dumps (unrelated to this session's own additions). With authorization, deleted two superseded same-day Aug-16 backups (~28.6GB), keeping the final Aug-16 state and this session's pre-sync backup. Also cleared 1.9GB of Docker build cache. VPS disk is tight again after this session's own post-run backup (~7.4GB free as of completion) -- worth proactive attention before the next heavy VPS operation.
- `studies prepare-data --batch-size N` does not skip already-built instruments; it always restarts from the top of the instrument list and stops after N items, so batching across multiple invocations requires the explicit `--instrument <symbol>` flag, not repeated `--batch-size 1` calls. Used correctly here after discovering this; not a code defect worth fixing given `--instrument` already exists as the correct mechanism.
- `worker`/`api` Docker images bake source in at build time (`COPY` in `Dockerfile`, no bind mount for `app`/`packages`/`research`); every code or config change requires `docker compose build worker` before it takes effect in a `docker compose run` invocation.

## Phase 1 Step 10A.4 completion — CONTEXT_DNA_TEST_COMPLETED, decision CONTEXT_SIGNAL_SUPPORTED_DNA_NO_INCREMENTAL_VALUE

- Storage inventory before starting: 7.4GB free (97% full), driven by 54GB of accumulated Postgres backup dumps (5 files) plus the 23GB live DB. With authorization, deleted 3 superseded same-day/prior backups (~37.4GB: `20260816T080833Z` 8.76GB, `20260816T170018Z` 14.3GB, `20260821T102104Z` 14.3GB), keeping only the tiny original milestone (`20260802T095444Z`, 116KB) and the latest, most complete backup (`20260821T172925Z`, 19.77GB). Cleared ~1.9GB Docker build cache (safe, transient). Disk after: 43GB free -- well above the 15-20GB gate.
- Verified Step 10A.3 evidence fully intact before starting: Yahoo experiment `a9390628…` (decision unchanged, `PILOT_RETRIEVAL_PROMISING`), independent replication experiment `bf59b66f…` (`REPLICATION_PARTIAL`), replication protocol `67953fda…` (`FROZEN`), replication lock `3d43d19a…` (`LOCKED`), replication record `15673493…` (`REPLICATION_PARTIAL`) -- all present and unmodified.
- Reused the existing `market_genome_replication` schema/service for this phase's protocol rather than adding new tables: new protocol definition `context_dna_incremental_value_v1` in `packages/replication/market_genome_replication/definitions.py`, sourced from the independent replication experiment (not Yahoo) this time. Generalized `ReplicationService.decide()` to accept a `decision_vocabulary` parameter so a different protocol family (`CONTEXT_DNA_DECISIONS`: `CONTEXT_SIGNAL_SUPPORTED_DNA_ADDS_VALUE` / `..._INCREMENTAL_VALUE_WEAK` / `..._NO_INCREMENTAL_VALUE` / `CONTEXT_SIGNAL_NOT_SUPPORTED` / `RESULT_MIXED_BY_ASSET` / `RESULT_MIXED_BY_CONTEXT` / `INCONCLUSIVE_SAMPLE_LIMITED`) can reuse the same immutable freeze/lock/decide mechanism without weakening the original vocabulary's enforcement.
- New testable analysis module `packages/replication/market_genome_replication/context_dna_analysis.py`: context-dimension definitions, context matching/filtering, candidate-universe hashing, deterministic seeded repeated-draw sampling, paired block bootstrap, information-layer decomposition table, and the decision classifier. New execution script `scripts/run_context_dna_incremental_value.py`, structurally similar to the Step 10A.3 script but reusing the *already-prepared* independent study/dataset (study `7b2e3649…`) rather than acquiring or building anything new.
- **Fixed the Step 10A.3 reporting gap**: `bootstrap_confidence.csv` is now always written on every real run (added a regression test, `tests/unit/test_context_dna_script_artifacts.py`, asserting every required artifact filename is referenced outside the dry-run early-return branch). No rerun of Step 10A.3 was needed or performed to backfill this.
- No new Alembic migration -- the existing `replication_protocols`/`replication_locks`/`replication_records` schema from Step 10A.3 covers this phase too. Migration head unchanged at `0012_independent_replication`.
- Canonical context definition for the headline 3-level decomposition was chosen from the pre-evaluation dry-run's *candidate-coverage counts only* (no outcome metric inspected): `trend_volatility` excluded just 1-6% of queries for insufficient within-context sample across all 3 window lengths, vs 16-21% for `trend_volatility_persistence` and 21-34% for `core_context`. Recorded explicitly in the experiment config (`canonical_context_definition: trend_volatility`) before the real run, per the protocol's own preference for the simplest reproducible context.
- Query sampling density carried over from Step 10A.3 (150/instrument/window-length -> 2,700 total base queries); 1,730 query-context pairs excluded for `INSUFFICIENT_WITHIN_CONTEXT_SAMPLE` (no other exclusion reasons occurred). Baseline repetitions: 50 deterministic seeded draws per query per context definition.

**Three-level information decomposition (canonical: `trend_volatility`), 2,700 base queries:**

| Layer | Brier | Skill vs prior layer |
|---|---|---|
| Unconditional history | 0.3277 | -- |
| + Market Context (trend + volatility) | 0.2561 | **+0.218** |
| + Market DNA (within that context) | 0.2822 | **-0.102** |

Reference: `dna_robust_cosine_v1` *without* context filtering (the Step 10A.3 primary method, recomputed fresh on this same dataset): Brier 0.2824, skill vs unconditional +0.138 -- worse than context alone, confirming DNA's apparent value in Step 10A.3 was largely re-deriving context information rather than adding to it.

**Consistency of the DNA-within-context deficit (paired Brier: context-random minus DNA; negative means DNA is worse):**
- All 4 predeclared context definitions: -0.102 (trend_volatility), -0.113 (trend_volatility_persistence), -0.103 (core_context), -0.113 (context_family) -- all with 95% paired block-bootstrap CIs entirely below zero (e.g. trend_volatility: [-0.035, -0.017]).
- All 6 instruments individually negative (AUDUSD -0.031, BTCUSD -0.026, ETHUSD -0.015, EURUSD -0.027, GBPUSD -0.015, USDJPY -0.041).
- Both asset classes negative (forex -0.029, crypto -0.021).
- All 3 window lengths negative (16: -0.023, 32: -0.024, 64: -0.031).
- Episode diversity was excellent throughout: mean unique episode count exactly 10.0 (of K=10), largest-episode-share exactly 0.1 -- no concentration artifact could explain the result.

**Decision: `CONTEXT_SIGNAL_SUPPORTED_DNA_NO_INCREMENTAL_VALUE`.** This is one of the cleanest, most consistent results produced in this project so far -- zero heterogeneity by instrument, asset class, window scale, or context definition. Per the phase's own framing (section 52), this is not a Market Genome failure: it identifies the transparent Market Context engine as the strongest supported information layer to date, and shows that robust Market DNA similarity, once context is controlled for, does not merely fail to add value but appears to select mildly *worse* analogues than random sampling from the same context.

**Verification:** source-layer mutation check passed (all 7 protected table counts identical before/after). Pre-experiment backup: reused the existing verified `market_genome_20260821T172925Z.sql` (SHA-256 `b46e578448feeffb9908b4fd5e2397b890f81dc593945b853d3f33655fb56a02`) rather than take a near-duplicate ~20GB dump, since this phase's writes were limited to small experiment/protocol/lock/record rows and text artifacts (`PREVIOUS_VERIFIED_BACKUP_REUSED`). Local test suite: 183 passed (up from 160), ruff clean, no migration change, `docker compose config --quiet` passed. VPS `verify_market_genome.sh`: PASSED. Local/VPS file hashes reconciled for every changed file (identical on both sides).

**Known limitations:** episode-diversity numbers are trivially uniform (10.0 / 0.1) because episode cap=1 with K=10 mechanically forces exactly 10 distinct episodes per query -- this confirms no concentration artifact but isn't informative variation. Context-family definition wasn't independently validated for semantic stability beyond assuming the existing `context_family_code` is already versioned, per the phase's instruction to reuse rather than redesign it.

## Step 10A.4 compliance re-audit (post-completion, same phase, no re-evaluation)

A more detailed version of the Step 10A.4 spec arrived after the phase above had already completed and been reported. Audited the existing implementation against it point-by-point rather than re-running anything (the protocol/lock were already frozen and the dataset already fully consumed for this diagnostic):

- Confirmed already compliant: primary baseline is `same_context_random_v1` (not `unconditional_outcome_v1`, which is Level 0 reference only); frozen configuration (D1, windows [16,32,64], horizon 20, `dna_robust_cosine_v1`, K=10, `uniform_v1`, episode cap 1) and the exact 4-definition context hierarchy are hardcoded correctly; baseline repetition seeds are derived from `sha256_canonical([seed, query_id, context_definition])`, never Python's process-randomized built-in `hash()`.
- Found and fixed one real gap: the candidate-universe equality check (`BASELINE_UNIVERSE_MISMATCH`) was computing both hashes from the literal same variable, making it an unreachable tautology rather than a real guard. Refactored into a dedicated `assert_candidate_universe_equality()` / `CandidateUniverseMismatchError` in `context_dna_analysis.py`, called from two independently-derived population lists in the script. Numerically identical result (both lists were always equal in content), but now a real, testable regression guard. Added tests: `test_assert_candidate_universe_equality_passes_for_identical_populations`, `test_assert_candidate_universe_equality_raises_on_divergence`, `test_candidate_universe_equality_is_enforced_before_ranking_or_sampling`, plus `test_primary_baseline_is_same_context_random_not_unconditional` and `test_frozen_primary_configuration_values_are_hardcoded_correctly`.
- Found and documented (without re-running) a sign-convention ambiguity: this phase's own artifacts define `brier_diff = context_random_brier - dna_brier` (positive = DNA better), which is the *opposite* sign from a `delta_Brier = Brier_DNA - Brier_ContextRandom` convention requested after the run completed. Added `research/reports/context_dna_incremental_value_v1/compliance_and_sign_convention_addendum.md` (also persisted as an `ExperimentArtifact` DB row on experiment `db1fd567-fb83-4e87-bcec-cdd94cf421d7`) documenting both conventions explicitly so the sign is never ambiguous to a future reader. The finding itself is unaffected by which sign convention describes it: DNA-within-context scored a consistently *worse* Brier than context-random.
- Tests: 189 passing (up from 183), ruff clean, migration head unchanged at `0012_independent_replication`, `docker compose config --quiet` passed.
- Verified after resyncing: all 7 protected source-layer table counts unchanged (`price_bars` 107518, `pattern_windows`/`normalized_patterns`/`market_dna` 528261, `market_contexts` 528259, `outcome_observations` 3697827, `study_episodes` 417520). VPS `verify_market_genome.sh`: PASSED. Local/VPS file hashes reconciled for every changed file. Disk unchanged at ~42GB free; memory/swap nominal for a long-uptime shared box.
- No new backup taken (would have been a near-duplicate of the existing verified `market_genome_20260821T172925Z.sql`, and no protected data changed); reused per `PREVIOUS_VERIFIED_BACKUP_REUSED`.
- The original decision, `CONTEXT_SIGNAL_SUPPORTED_DNA_NO_INCREMENTAL_VALUE`, and all reported numbers stand unchanged.

## Phase 1 Step 10B-C completion — Market Context Forecasting Baseline and Prospective Validation infrastructure

Evidence-driven pivot: since Step 10A.4 found `CONTEXT_SIGNAL_SUPPORTED_DNA_NO_INCREMENTAL_VALUE`, this phase builds a prospective (not retrospective) validation system for the transparent Market Context engine alone -- no Market DNA, no AI/ML, no trading logic. Engineering-complete and functionally proven end-to-end with one real (unscheduled) daily iteration.

- Verified all frozen Step 10A.3/10A.4 evidence intact before starting (Yahoo study/experiment, independent study/replication experiment, both replication protocols/locks, the 10A.4 compliance addendum) -- none modified.
- Storage guard: started at 42GB free (from Step 10A.4's end state); ended at 41GB free after a new backup + authorized pruning of the now-superseded previous one.
- New package `packages/prospective/market_genome_prospective/`: `forecast_analysis.py` (Wilson confidence intervals, Beta-Binomial/Laplace smoothing, fallback-hierarchy selection, historical-as-of verification, data-revision detection, Brier/log-loss/ECE evaluation, decision classifier for `PROSPECTIVE_CONTEXT_SIGNAL_SUPPORTED`/`..._WEAK`/`..._NOT_SUPPORTED`/`PROSPECTIVE_EVIDENCE_ACCUMULATING`), `definitions.py` (frozen `market_context_forecast_v1` protocol), `service.py` (`ProspectiveContextForecastService`: protocol freeze, historical-as-of context-conditioned probability estimation with fallback, immutable idempotent forecast creation with retroactive-forecast rejection, outcome maturation, evaluation snapshots).
- **Primary context definition selected from Step 10A.4 evidence alone** (coverage/stability, not just best metric): `trend_volatility` over `context_family` -- materially equivalent performance (skill +0.218 vs +0.224), but `trend_volatility` is the more directly explainable two-dimension representation and was already the Step 10A.4 canonical definition. Fallback hierarchy: `trend_volatility -> trend_only -> unconditional`.
- Frozen hypothesis: D1 Market Context state (trend+volatility) gives forward 20-bar directional probability with positive Brier skill vs unconditional history, evaluated prospectively on observations after protocol freeze. Primary horizon 20; secondary 5, 10. Minimum historical sample 30; Beta-Binomial(alpha=1, beta=1) smoothing; Wilson 95% CI; minimum evidence 100 matured forecasts, preferred 250.
- New schema (migration `0013_prospective_context_validation`, linear after `0012`): `ProspectiveProtocol`, `ProspectiveForecast` (keyed on `pattern_window_id`, not a datetime-equality join -- see below), `ProspectiveForecastOutcome`, `ProspectiveEvaluationSnapshot`. Forecast identity: `(protocol_id, instrument_id, timeframe_id, window_length, forecast_timestamp, horizon_bars)`.
- New CLI group `market-genome prospective {protocols, create-protocol, latest, run-daily, mature, evaluate, status}`; `run-daily` supports `--dry-run` and performs one deterministic iteration (ensure latest bars -> build derived state only if new bars arrived -> create TRUE_PROSPECTIVE forecasts from latest available context -> mature eligible pending forecasts -> refresh evaluation snapshot).
- New read-only API endpoints (no trading language) at `/api/v1/prospective/{protocols,forecasts,forecasts/{id},latest,evaluation}`.
- **Design fix found via local testing (not a production bug, but real):** SQLite doesn't preserve timezone info through raw-SQL datetime-parameter binding, making exact-equality datetime joins fragile in tests. Rather than rely on Postgres-only correctness, added an explicit `pattern_window_id` FK to `ProspectiveForecast` so maturation joins on a primary key, never a timestamp -- more robust in production too, not just test-compatible.
- **Real incident found and fixed during the live proof run:** `run-daily`'s outcome-rebuild step requested only the protocol's 3 horizons `[5,10,20]` instead of the full research set `[1,3,5,10,20,40,60]`. Since the outcome build's identity hash includes the exact requested-horizons list, this created **267,246 duplicate rows** in the protected `outcome_observations` table (18 groups: 6 instruments x 3 window lengths, numerically identical to existing data, just under a new config hash). Identified precisely via `configuration_hash`/timestamp, confirmed nothing referenced them (0 forecasts had matured yet), got explicit user authorization, and deleted them -- protected-table counts verified restored to the exact pre-incident baseline. Root-caused and fixed: `run-daily` now (a) only rebuilds derived state when new price bars actually arrived (`bars_after > bars_before`), and (b) always requests the full `RESEARCH_OUTCOME_HORIZONS` set for outcome builds, never a narrower subset. Added regression tests (`test_prospective_cli_safety.py`) guarding both fixes by source inspection.
- Also fixed, proactively this time: the recurring hardcoded-Alembic-head-string bug (hit in Step 10A.3 twice) was finally root-caused in `MultiAssetStudyService._postgres_runtime_verified()` -- now checks "some revision exists" instead of an exact string, so it never needs updating again. `scripts/verify_postgres_runtime.py`'s expected revision and required-tables set were updated to `0013`/the 4 new tables as usual.
- Protocol frozen: `23393946-1095-46b2-b296-ad3ad853dc94`. One real (manually triggered, not scheduled) `run-daily` iteration produced **54 TRUE_PROSPECTIVE forecasts** (6 instruments x 3 window lengths x 3 horizons), all `PENDING_OUTCOME`, all with populated `source_hash`/`context_hash`/`historical_reference_hash`/`forecast_hash` and Wilson confidence intervals (e.g. USDJPY_AV, window 64, horizon 10: P(positive)=53.4%, 95% CI [49.9%, 56.8%], sample_count=802, context `WEAK_UPTREND|HIGH`). A second dry-run confirmed idempotency: all 54 already-existing forecasts correctly reported `would_create: false`.
- **Known limitation:** `ALPHA_VANTAGE_API_KEY` is not persisted in the VPS's `market-genome.env` (it was only ever exported ad hoc in SSH sessions), so today's run-daily's acquisition step failed cleanly with `PROVIDER_API_KEY_NOT_CONFIGURED` for the 4 FX instruments (crypto wasn't stale, so no fetch was attempted there either) and fell back to forecasting from the latest already-imported bar. The system degraded gracefully rather than crashing, but genuinely automated daily runs need the key persisted into the deployment env first -- not done yet, pending the user's decision on whether to store it there.
- Local tests: 220 passing (up from 218 pre-fix / 189 at Step 10A.4 start), ruff clean, migration head `0013_prospective_context_validation`, `docker compose config --quiet` passed. VPS `verify_market_genome.sh`: PASSED (before and after the incident cleanup). API and worker images rebuilt and API restarted successfully. Local/VPS file hashes reconciled for every changed file.
- Current status: `PROSPECTIVE_EVIDENCE_ACCUMULATING` (54 of 100 minimum matured forecasts needed -- expected initial state, not yet interpretable).

## Phase 1 Step 10B-C refinement completion — Complete Prospective Forecast Lifecycle, Migration, Tests, CLI/API, and VPS Readiness

Continuation of the same phase, refining the already-engineering-complete prospective system per a more detailed follow-up spec. No redesign; no Market DNA added to the primary forecast; no trading logic; no AI/ML model; scheduler not activated.

- **Forecast identity finalized to its smallest non-redundant boundary**: `(protocol_id, pattern_window_id, horizon_bars, provenance_class)`, replacing the prior 6-field identity that repeated information already implied by `pattern_window_id` (instrument, timeframe, window length, query timestamp) and relied on a datetime-equality join. `provenance_class` is included so the same pattern window/horizon can carry one `TRUE_PROSPECTIVE` forecast and, separately, one `BACKFILL_SIMULATION`/`HISTORICAL_VALIDATION` forecast without colliding.
- **`ProspectiveForecastOutcome` now references the existing immutable `OutcomeObservation`** via a new `source_forward_outcome_id` FK + `source_outcome_hash`, in addition to its own snapshot fields -- traceable to source, not just a duplicated computation.
- **Data-revision detection wired into maturation**: `mature_forecast` compares the query window's current `source_data_hash` against the hash frozen at forecast creation; a mismatch sets `data_revision_detected=True` on the outcome and never mutates the forecast itself. Interpretation of a flagged forecast is left to explicit protocol policy, not automatic exclusion.
- **`provenance_class` validated against an explicit enum** (`TRUE_PROSPECTIVE`, `BACKFILL_SIMULATION`, `HISTORICAL_VALIDATION`); an unsupported value raises `UNSUPPORTED_PROVENANCE_CLASS:<value>`.
- **Retroactive-rejection errors now carry the exact literal code** `RETROACTIVE_PROSPECTIVE_FORECAST_REJECTED:` as a message prefix, so callers can match on the code rather than free text.
- **Evaluation restricted to genuine prospective evidence**: `create_evaluation_snapshot` now filters `provenance_class == "TRUE_PROSPECTIVE"` -- a `BACKFILL_SIMULATION`/`HISTORICAL_VALIDATION` forecast can never be counted toward the evidence base (added a dedicated regression test).
- **Evaluation metrics extended**: added `balanced_accuracy` and `mcc` (Matthews correlation coefficient) alongside the existing Brier score/skill, log loss, ECE, and direction accuracy -- both correctly return `None` (not 0) when a class is entirely absent from the matured sample, since they're undefined rather than degenerate in that case.
- **New CLI command `market-genome prospective forecast-only`**: creates forecasts from whatever windows/contexts already exist, fully decoupled from acquisition (no provider fetch, no CSV import, no derived-state rebuild); accepts `--provenance-class` for smoke/calibration runs. Also fixed a real drift bug found in the process: `run-daily`'s `--dry-run` existence check still used the old timestamp-equality identity fields after the identity change -- it now uses the same `pattern_window_id`+`provenance_class` lookup as `create_forecast`'s real idempotency check, so a dry run's `would_create` can never disagree with what a real run actually does.
- **New migration `0014_prospective_forecast_identity_refinement`** (linear after `0013`): recreates the unique constraint on `prospective_forecasts`; adds `source_forward_outcome_id`/`source_outcome_hash` (NOT NULL, table was confirmed empty) + FK + 2 indexes to `prospective_forecast_outcomes`; adds `balanced_accuracy`/`mcc` to `prospective_evaluation_snapshots`. Applied cleanly on the VPS's real PostgreSQL (not just SQLite).
- **Root-caused the recurring hardcoded-Alembic-head-string bug a further time** (previously hit and patched in Step 10A.3 x2 and root-caused for `MultiAssetStudyService` in Step 10B-C's first pass, but `scripts/verify_postgres_runtime.py`'s `EXPECTED_REVISION` was still a literal string and immediately went stale against `0014`, failing VPS verification with `ALEMBIC_REVISION_MISMATCH`). Fixed properly this time: `EXPECTED_REVISION` now reads the actual current head from the Alembic script directory via `ScriptDirectory.from_config(...).get_current_head()` (env-var override still supported), so it can never go stale again. Added a permanent regression test (`test_expected_revision_is_read_from_the_migration_chain_not_hardcoded`).
- Added 13 new tests (provenance validation, exact error-code matching, identity scoping by provenance class, `source_forward_outcome_id`/`source_outcome_hash` population, data-revision detection without forecast mutation, evaluation provenance filtering, balanced-accuracy/MCC correctness including the degenerate-class case, `forecast-only` CLI existence/decoupling/provenance-override via source inspection, `run-daily` dry-run identity-consistency, and the Alembic-head regression guard) plus updated one existing test whose expected error text was stale after the message-prefix change.
- Added 5 documentation files (`docs/architecture/prospective-context-forecasting.md`, `docs/architecture/prospective-forecast-provenance.md`, `docs/research/prospective-validation-protocol.md`, `docs/operations/prospective-daily-run.md`, `docs/api/prospective-api.md`) and updated `README.md` (capability summary, API list, CLI list, `forecast-only`).
- Local verification: `python -m pytest -q` -- 233 passed (up from 232 pre-refinement / 220 at the phase's first pass). `python -m ruff check .` -- clean. `python -m alembic -c infrastructure/alembic.ini history` -- linear, head `0014_prospective_forecast_identity_refinement`. `docker compose config --quiet` -- passed.
- VPS deployment: synced 16 changed files via tar+scp to `/opt/market-genome/app`, reconciled every file's SHA-256 hash local-vs-VPS (all matched, including a follow-up sync for the `verify_postgres_runtime.py` fix). Rebuilt `api` and `worker` images (twice for `worker`, to pick up the Alembic-head fix). Applied migration `0014` directly against the VPS's real PostgreSQL -- succeeded cleanly. Restarted only the `api` container. `scripts/vps/verify_market_genome.sh`: **PASSED** (`expected_revision: 0014_prospective_forecast_identity_refinement`, zero errors) after the dynamic-revision fix; failed once beforehand with `ALEMBIC_REVISION_MISMATCH` against the still-stale hardcoded `0013` literal, which is exactly the bug just described.
- Source-layer mutation guard: captured `price_bars` (107,518), `pattern_windows`/`normalized_patterns`/`market_dna` (528,261 each), `market_contexts` (528,259), `outcome_observations` (3,697,827), `study_episodes` (417,520), `prospective_forecasts` (54), `prospective_forecast_outcomes` (0), `prospective_evaluation_snapshots` (1) before and after running `prospective run-daily --dry-run` and `prospective forecast-only --dry-run` on the VPS -- every count identical; both dry runs correctly reported `would_create: false` for all 54 pre-existing forecasts, confirming the new identity is genuinely idempotent in production, not just in tests.
- `prospective status` on the VPS: 54 total forecasts, 0 matured, 54 pending, `PROSPECTIVE_EVIDENCE_ACCUMULATING` (protocol `23393946-1095-46b2-b296-ad3ad853dc94`, still `FROZEN`). Unchanged from the phase's first pass -- horizon-20 forecasts from ~August 16-21 have not yet had 20 D1 bars elapse.
- **No new TRUE_PROSPECTIVE iteration was run this round.** Per explicit instruction, a fresh live iteration requires separate authorization beyond what already covered the one prior manual run; only `--dry-run` invocations of `run-daily` and the new `forecast-only` command were executed against the VPS. The 54 existing forecasts are unchanged. Finishing with `PROSPECTIVE_ENGINE_READY_NOT_STARTED` for any *new* iteration -- to advance, run (with explicit authorization): `market-genome prospective run-daily` (acquisition + forecast + maturation + evaluation) or `market-genome prospective forecast-only` (forecast step only) via the VPS worker container.
- **Backup note**: reused the same-day pre-existing backup (`market_genome_20260822T063154Z.sql`, taken ~08:38 that morning) rather than taking a new one after migration `0014` -- the migration is purely additive (2 new nullable/NOT-NULL-on-empty-table columns on an empty table, 2 new columns on the evaluation-snapshot table, one constraint recreation) and touches zero existing data rows, and disk is at 40GB free (down from 41GB after two image rebuilds). No new backup was taken; flagged here rather than assumed.
- Local/VPS file hashes reconciled for every changed file (16 files: schema/service/CLI/API/docs/README/tests, plus the follow-up `verify_postgres_runtime.py` fix and its test).

## Phase 1 Step 10B-C.1 completion — First TRUE_PROSPECTIVE Run and Prospective Evidence Accumulation

Authorized first genuine live prospective iteration. No methodology change, no Market DNA in the primary forecast, no trading logic, no AI/ML model, scheduler not activated.

- **Protocol drift check**: re-ran `create-protocol` against the frozen `market_context_forecast_v1` (id `23393946-1095-46b2-b296-ad3ad853dc94`, `protocol_v1`, hash `441bdec1...`) -- identical id and configuration_hash returned, confirming zero drift since the definition was frozen. No `PROSPECTIVE_PROTOCOL_DRIFT_DETECTED`.
- **Pre-flight integrity audit of the existing 54 forecasts**: all 54 were `TRUE_PROSPECTIVE`/`PENDING_OUTCOME` (6 instruments x 3 window lengths x 3 horizons); 0 violated `forecast_created_at >= data_cutoff_timestamp`; 0 had a complete `OutcomeObservation` already existing for their `pattern_window_id`+`horizon_bars` at any point; 0 had a missing required hash field. No invalidation needed.
- **Known-gap resolution, user-authorized**: `ALPHA_VANTAGE_API_KEY` was still not persisted anywhere reachable by acquisition. User chose "persist into VPS env" when asked. Appended it to `/opt/market-genome/config/market-genome.env` (value never printed to any log). **Found a second, deeper gap while doing this**: even with the key in the env file, `docker-compose.vps.yml`'s `worker` service never passed it through to the container's `environment:` block (compose `--env-file` only feeds `${VAR}` substitution in the YAML, it does not auto-inject into containers) -- acquisition would have still failed. Fixed by adding `ALPHA_VANTAGE_API_KEY: ${ALPHA_VANTAGE_API_KEY:-}` to the worker service's `environment:` block. Verified via `data provider-smoke alpha_vantage_v1 --symbol EUR/USD --asset-class forex`: reachable, credentials valid, 5000 rows returned, latest completed bar `2026-08-21`.
- **Dry-run gap found and fixed before the live run**: `run-daily --dry-run` previously skipped acquisition entirely, so its `would_create` preview reflected only pre-existing windows and never reported what acquisition would actually do -- not a faithful preview for an integrity gate. Fixed: dry run now always computes the staleness check and, for stale instruments, previews the exact provider requests via the pure/local `requests_from_manifest()` builder (no network call, no write) -- reports `would_fetch`, `provider_requests_preview`, `new_completed_bars_expected` (honestly `"UNKNOWN_UNTIL_ACQUISITION_RUNS"` rather than guessed), plus `current_forecast_count`/`current_matured_count`/`pending_forecasts_eligible_to_mature_preview`. Verified zero mutation across two dry runs (all 10 protected-table counts identical before/after both times).
- **Dry-run integrity gate**: no disqualifying condition reported (no retroactive creation, no protocol mismatch, no resource-guard failure, no data-revision). Resource gate at execution time: 38GB free disk, 6.1GiB available memory, all 3 Market Genome containers healthy. Cleared to proceed.
- **Executed exactly one live `market-genome prospective run-daily` iteration** (no loop, not scheduled). Result: 6 new completed D1 bars imported (1 per instrument, the `2026-08-21` FX close / `2026-08-21`-`2026-08-22` crypto close), 18 new `PatternWindow`s (6 x 3 window lengths), 18 new `MarketContext`s, **54 new `TRUE_PROSPECTIVE` forecasts** (bringing the total to 108) -- all with `context_level_used = trend_volatility` (no fallback triggered), sample counts 205-3731, probability_positive 0.377-0.644, confidence intervals within [0.312, 0.684]. 0 skipped duplicates, 0 retroactive rejections, 0 insufficient-context-history cases. All new forecasts passed the same integrity checks as the pre-flight audit (0 violations of any kind).
- **Investigated an apparent second incident, confirmed it was not one**: the live run added 2,628 new `outcome_observations` rows, including 2,502 rows sharing identity (`pattern_window_id`+`horizon_bars`+`outcome_set_code`+`configuration_hash`) with a pre-existing row. Traced this fully before taking any action: `OutcomeBuildService` deliberately never mutates a persisted outcome row -- per `docs/architecture/partial-outcome-versioning.md`, when more future bars arrive and a previously-partial (`is_complete=false`) outcome becomes complete (or gains more, still-insufficient future bars), a **new immutable row is appended** rather than the old one being updated. Verified: all 126 newly-complete rows correctly set `supersedes_observation_id` pointing at their superseded partial; the remaining 2,376 incomplete-to-incomplete rows are successive partial versions (not chained via `supersedes_observation_id`, matching the documented design's stated scope, which only tracks the completion transition). Confirmed via direct row inspection, not assumption. No rows deleted, no user authorization needed, no fix applied -- this is intended behavior, not the 267,246-row-incident failure mode (which was a differing `configuration_hash` from a narrower requested-horizon set; here every duplicate pair shares the identical hash).
- **Maturation**: 0 eligible (all 108 forecasts too recent -- horizon-20 needs ~20 D1 bars). Re-ran `mature` explicitly afterward: 0 matured, confirming idempotency (no duplicate `ProspectiveForecastOutcome` rows possible when nothing is eligible).
- **Evaluation**: fresh snapshot `b42a716d-8001-4d4b-a2d8-790a490e9671`, forecast_count=108, matured_count=0, all metrics (Brier/skill/log loss/ECE/direction/balanced accuracy/MCC) correctly `null` -- status `PROSPECTIVE_EVIDENCE_ACCUMULATING`.
- **Known gap surfaced, not fixed**: `ProspectiveForecast.expected_return` is a real nullable column but nothing in the pipeline has ever computed it -- grepped the entire `prospective`/CLI/API code and found zero writes to it. No frozen methodology for an expected-return magnitude exists yet (only a directional probability estimator was ever frozen). Left `null` rather than inventing a calculation outside the frozen protocol; flagged for a future, explicitly-reviewed decision if return-magnitude reporting is wanted.
- **Artifacts**: `scripts/generate_prospective_ledger.py` (new, reproducible from DB records) writes `research/reports/prospective_context_validation/forecast_ledger.csv` (108 rows) and `prospective_daily_run_<timestamp>.json` (this run: 54 new forecast IDs, run hash `35d7bf38...`) -- generated on the VPS, copied back to the local repo for parity.
- Local verification after the dry-run/CLI fixes: `python -m pytest -q` -- 235 passed (up from 233). `python -m ruff check .` -- clean. Migration head unchanged at `0014` (no schema change this round). `docker compose config --quiet` -- passed.
- VPS: synced 3 changed files (`docker-compose.vps.yml`, `main.py`, `test_prospective_cli_safety.py`) plus the new ledger script, hash-reconciled every one. Rebuilt the `worker` image 3 times total this round (env passthrough, dry-run fix, ledger script). `scripts/vps/verify_market_genome.sh`: **PASSED**. All 3 Market Genome containers healthy throughout and after.
- Resource state: disk 38GB free before the live run, 37GB after (down 1GB from image rebuilds + new data -- still comfortably above the 15GB floor). Memory: 6.1GiB available before, 6.7GiB available after (Postgres RSS peaked around 2.05GiB during the outcome rebuild, back to normal after). All health checks green throughout.
- `SCHEDULER_READY = YES` on mechanism-safety grounds (idempotent identity, provider-failure-safe acquisition, resource guard wired, forecast/maturation/evaluation all guarded and verified idempotent) -- **this is not an activation**; no cron/systemd was configured, per explicit instruction.
- Next manual iteration command: `docker compose -p market-genome --env-file /opt/market-genome/config/market-genome.env -f infrastructure/deployment/vps/docker-compose.vps.yml run --rm worker market-genome prospective run-daily` (run from `/opt/market-genome/app/infrastructure/deployment/vps` on `raivstream`).

## Phase 1 Step 10B-C.3 continued — Week Catch-Up Cycle, Preferred Evidence Threshold Reached, Classification flips to `PROSPECTIVE_CONTEXT_SIGNAL_WEAK` (2026-09-12)

Catch-up cycle after a ~1-week operational gap (last run 2026-09-05). No methodology change, no Market DNA in the primary forecast, no trading logic, no AI/ML model, scheduler not activated.

- **Pre-flight**: protocol `23393946…` still `FROZEN` (no drift). Dry-run integrity gate clean — all 6 instruments stale (FX db-latest `2026-09-04`, crypto `2026-09-05`), acquisition correctly previewed via `requests_from_manifest()` (no network/write), no disqualifying condition (no retroactive creation, no protocol mismatch, no resource-guard failure, no data-revision). Resource gate at execution: 21GB free disk, ~4.3-4.7GB available memory, all 3 containers healthy.
- **Live run** (one iteration, not scheduled): 34 new completed D1 bars imported (FX +5 each, crypto +7 each), 54 new forecasts (621 -> 675), **183 matured (174 -> 357)**. Evaluation snapshot `940c4f27-ca64-46f8-8a22-c77e46374111`; run hash `60df3330…`.
- **Largest maturation cohort by far (183 in one cycle)** — the missed week accumulated bars, so the remaining horizon-5 and horizon-10 forecasts across all 6 instruments matured together, and the cohort also contained the **first-ever horizon-20 maturations (18, all crypto)**. This was initially mis-read as "no horizon-20 maturation" because `prospective status`'s `horizon_readiness` only breaks down *pending* forecasts by horizon, not matured ones — corrected later the same day when the evaluation-layer fix below began reporting `primary_horizon_matured_count` (see "Evaluation-layer correction"). Full bulk verification repeated across all 357: chain-of-custody, temporal integrity, immutability, idempotency — **357/357 pass every check** (see below).
- **First formal classification change (as produced by the pre-fix evaluation)**: `PROSPECTIVE_CONTEXT_SIGNAL_NOT_SUPPORTED` -> **`PROSPECTIVE_CONTEXT_SIGNAL_WEAK`**, via the frozen `classify_prospective_decision` rule (`matured_count` 357 >= preferred 250, skill crossed zero to +0.01276). This was a genuine run, but the same-day evaluation-layer correction showed the +0.01276 was a **pooling artifact** (mixed horizons scored against a single horizon-20 baseline) and that per-horizon skill was in fact slightly negative; see below. `SUPPORTED` was also unreachable by construction (`bootstrap_ci_low` hardcoded `None`). Per the early-result firewall, this was recorded, **not reacted to**; the frozen protocol/lock and all methodology were unchanged.
- **Mixed signal, recorded without interpretation**: the threshold-independent metric improved (Brier 0.25075 -> 0.25155, skill -0.01276 -> +0.01276, ECE 0.12335 -> 0.10757), while the 0.5-threshold classification metrics weakened (balanced_accuracy 0.63766 -> 0.59069, MCC 0.30968 -> 0.20450, direction_accuracy 0.59195 -> 0.55462). Both directions are noted as what the pre-registered metrics actually produced; neither is spun.
- **Integrity, verified by direct inspection not assumption**: a read-only verifier (chain-of-custody SQL join, temporal integrity, `forecast_hash`/`outcome_hash` recomputation) executed against the live DB reported zero violations across all 357 matured outcomes — 0 unresolvable `source_forward_outcome_id`, 0 window/horizon mismatches, 0 source-hash/return/MFE/MAE/bar-count mismatches, 0 incomplete sources, 0 temporal violations, 0 data-revision flags, 0 hashes that failed recomputation. Broadened to **all 675 forecasts** (matured + pending), every `forecast_hash` recomputes byte-exactly (immutability proven, not assumed). Maturation idempotency re-confirmed: re-running `mature` returned `{"matured_count": 0}`; 0 duplicate `forecast_id`s, 0 `PENDING_OUTCOME` rows with an outcome, 0 `MATURED` rows without one.
- **Source-layer deltas** matched expectations exactly: `price_bars` 107,592 -> 107,626 (+34); `pattern_windows`/`normalized_patterns`/`market_dna` 528,483 -> 528,585 (+102 each); `market_contexts` 528,481 -> 528,583 (+102); `outcome_observations` 3,725,652 -> 3,728,868 (+3,216); `study_episodes` unchanged (417,520); `prospective_forecasts` +54; `prospective_forecast_outcomes` +183; `prospective_evaluation_snapshots` +1 (26 -> 27).
- **Artifacts**: `forecast_ledger.csv` (675 rows), `run_history.csv` (13 rows), new `prospective_daily_run_20260912T015015Z.json` — all regenerated on the VPS, copied back to the local repo, and SHA-256 reconciled local-vs-VPS (all matched).
- **Verification**: VPS `scripts/vps/verify_market_genome.sh` **PASSED** (`expected_revision: 0014_prospective_forecast_identity_refinement`, zero errors). Local `python -m pytest -q` — 272 passed (no code changed this cycle, so count unchanged from Step 10B-C.3's last local run). `python -m ruff check .` — clean. Migration head unchanged at `0014` (no schema change). Disk 21GB free (90%), all 3 containers healthy throughout and after. No new backup taken (routine `run-daily` iteration; the previous verified backup practice applies to migrations/formal runs, and no schema or protected-data-repair change occurred).
- **Disclosure**: the integrity verifier is an ad-hoc, read-only harness run via a bind-mounted file inside the disposable worker container (never written to the repo, and the image was not rebuilt); it makes no database writes and persists nothing. The underlying verification queries are the same join/recomputation logic used in prior cohorts, just packaged for one pass.
- **Known limitations carried forward**: `SUPPORTED` was unreachable while `bootstrap_ci_low` was never computed (fixed immediately afterward — see next section); `expected_return` remains `null` (no frozen magnitude methodology). Recommended next action: resume regular manual `run-daily` iterations (a single catch-up iteration only forecasts from each instrument's latest bar — intermediate missed days have no forecasts, by design); watch whether per-horizon skill (see corrected readout) holds with more primary-horizon evidence.

## Daily prospective report — new generated artifact, updated automatically each scheduled run (2026-09-22)

- Added `scripts/generate_prospective_report.py`: reads the latest frozen protocol, the latest evaluation snapshot (per-horizon metrics + bootstrap CIs), the snapshot history, and the newest daily-run artifact, then overwrites `prospective_report.md` with a human-readable report (status; headline primary-horizon metrics; per-horizon table; trend; a factual "Reading" that does not interpret while ACCUMULATING; sources note).
- The scheduled wrapper `scripts/vps/run_prospective_daily.sh` now runs **three** steps: `prospective run-daily` -> ledger/run-history regeneration -> report regeneration. The `set -e` chain means the report is always regenerated from the latest successful run; a resource-guard pause still aborts the unit with exit 75.
- Tests: `tests/unit/test_prospective_report.py` (6 tests: sections, per-horizon rows, ACCUMULATING non-interpretation, decision-specific reading, missing-snapshot graceful handling, wrapper references the generator). Local suite: 290 passed (+6), ruff clean.
- Deployed: synced report script + wrapper (SHA-256 reconciled), rebuilt the `worker` image, and ran the full service once to validate all three steps end to end (exit 0, ~15 min, 54 new forecasts, 30 matured). VPS `verify_market_genome.sh` PASSED.
- First report generated (`prospective_report.md`, 2026-09-22 05:58 UTC): snapshot `87a1df99…`, primary-horizon matured **84** of 100 minimum, skill -0.0353, CI [-0.157, +0.086], status `PROSPECTIVE_EVIDENCE_ACCUMULATING`. Pulled the report + refreshed ledger/run-history + three daily-run artifacts (09-20/09-21/09-22) back to the local repo; SHA-256 reconciled local-vs-VPS for all six (matched).
- From now on the report is updated automatically by each scheduled daily run (11:16 UTC), alongside the ledger.

## Scheduled daily runs 2026-09-17 to 2026-09-19 (2026-09-19)

- The daily timer is firing consistently. 09-17 ran automatically; **09-18 fired but was paused by the resource guard on a new axis** (`FREE_SWAP_MB_BELOW_THRESHOLD:298<512`, exit 75, no artifact written); **09-19 ran automatically and succeeded**. The guard is working as designed (no in-day retry); a single-day pause is not a scheduler defect.
- Today's (09-19) scheduled iteration: 12 new bars (2 per instrument), 54 new forecasts (855 -> 909), 66 matured (438 -> 504). Snapshot `2026-09-19 11:33:59 UTC`: primary-horizon matured **66** (was 30 three days ago), skill -0.0936, status `PROSPECTIVE_EVIDENCE_ACCUMULATING`. Resource state healthy (~4 GB available RAM, 36 GB free disk).
- Pulled `prospective_daily_run_20260917T113316Z.json` and `prospective_daily_run_20260919T113359Z.json` plus the refreshed ledger/run-history back to the local repo; SHA-256 reconciled local-vs-VPS (all matched).

## Evaluation-layer fix — baseline now evaluated as-of each forecast's own cutoff (2026-09-15)

- Corrected a third evaluation-layer discrepancy: the frozen protocol specifies the unconditional baseline is "evaluated as-of each forecast's own cutoff", but `create_evaluation_snapshot` computed it as-of evaluation time (`as_of=now`). `service.py` now uses `forecast.data_cutoff_timestamp` per row (cache key includes the cutoff). Evaluation-layer only; no forecast/probability/context/outcome change.
- Test added: `test_evaluation_baseline_is_as_of_each_forecasts_own_cutoff` (history before the cutoff is all-negative, history after it is all-positive; the baseline must read the pre-cutoff rate). Local suite: 284 passed (+1), ruff clean.
- Deployed: synced `service.py` (SHA-256 reconciled), rebuilt the `worker` image, regenerated the snapshot. VPS `verify_market_genome.sh` PASSED.
- **Result: the fix is correct but its effect is small.** Same matured set (primary n=30, total 399): primary-horizon Brier skill moved only from -0.0917 to **-0.0904** (CI [-0.1995, +0.0089]); h5 (n=207) -0.0004, h10 (n=162) -0.0351. Post-fix snapshot `d467f91c-33bc-4682-9833-67d0a3bf11eb`, status `PROSPECTIVE_EVIDENCE_ACCUMULATING`.
- **Interpretation**: the hypothesis that the baseline-timing bug explained the historical-vs-prospective gap (historical ≈ +0.22 vs prospective ≈ 0) is **not supported** -- the unconditional base rate is stable enough that as-of-now and as-of-cutoff baselines barely differ. The gap must be explained otherwise (e.g. the historical evaluation's in-sample nature), and the primary-horizon prospective signal remains ≈ 0 to negative. No methodology change; v2 candidate prerequisite (3) is now satisfied.
- New snapshot appended; prior snapshots untouched. No schema/migration change, no new backup (one evaluation row only).

## Candidate v2 protocol drafted (pre-registered, NOT activated); baseline-timing discrepancy found (2026-09-15)

- Drafted `market_context_forecast_v2` as a **paper pre-registration only**, structurally inert: it lives in a separate `CANDIDATE_PROSPECTIVE_PROTOCOLS` registry in `definitions.py`, is absent from `PROSPECTIVE_PROTOCOLS`, is not exposed by the CLI/API, and `get_prospective_protocol_definition()` raises for its code -- so it cannot be listed or frozen through any normal path. Regression-guarded by `tests/unit/test_prospective_definitions.py` (4 tests: not in active registry, not resolvable, listed separately, and identical to v1 except the estimator).
- **The single change**: replace v1's hard-switch-at-30 + Laplace-toward-0.5 estimator with a Beta-Binomial hierarchical shrinkage `p_hat = (k + m*p0)/(n + m)` (`m = 20.0` fixed, `p0` = as-of unconditional base rate). Rationale is statistical (variance reduction for small context samples), chosen without fitting to prospective outcomes; all other frozen choices (context definition, horizons, window lengths, instruments, provider, evidence gates) are identical to v1, so any v2-vs-v1 difference is attributable to the estimator.
- Success criteria: primary-horizon skill > 0 with bootstrap CI low > 0 at >= 250 matured, plus a confirmatory secondary requiring v2 to beat v1's estimator on the same basis. Full spec: `docs/research/prospective-protocol-v2-candidate.md`.
- **Prerequisites before v2 may be frozen** (documented, none implemented): (1) implement the shrinkage estimator (`historical_probability` currently always applies Laplace regardless of `smoothing_method`); (2) generalize `freeze_protocol`'s lineage (currently hardcoded to the Step 10A.4 replication record; v2 should lineage from the v1 prospective protocol and its verdict); (3) correct the baseline timing below.
- **New evaluation finding (not fixed, flagged for authorization)**: the protocol specifies the unconditional baseline is "evaluated as-of each forecast's own cutoff", but `create_evaluation_snapshot` computes it as-of evaluation time (`as_of=now`). The baseline therefore uses more data than the forecast did -- including the evaluation period itself -- which biases measured Brier skill **downward**. This affects the v1 verdict too and should be corrected before the decision point at 250. Evaluation-layer only; no forecast/methodology change.
- Repo-only: definition, tests and doc were **not** synced/deployed to the VPS and the worker image was not rebuilt (the candidate is inert; promotion will require a rebuild). Local suite: 283 passed (+4), `python -m ruff check .` clean.

## Scheduler ops follow-up — wrapper now refreshes ledger artifacts (2026-09-14)

- `scripts/vps/run_prospective_daily.sh` now runs two steps: `prospective run-daily`, then `generate_prospective_ledger.py --output-dir /opt/market-genome/reports/prospective_context_validation` (refresh `forecast_ledger.csv` + `run_history.csv`). `set -e` guarantees step 2 runs only after a successful run-daily (a resource-guard pause still aborts the unit with exit 75), and a step-2 failure fails the unit rather than passing silently.
- Validated end-to-end via `systemctl start`: exit `status=0/SUCCESS`; new snapshot `9f8209fe-de49-440a-961b-24de1aaf217f` and artifact `prospective_daily_run_20260914T125809Z.json`; `forecast_ledger.csv` (693 forecasts) and `run_history.csv` regenerated at 14:58:14Z. Pulled updated files back to the local repo; SHA-256 reconciled local-vs-VPS (all matched).
- Docs updated: `prospective-scheduler-readiness.md` (wrapper description + artifact note) and `prospective-daily-run.md` (scheduling/ledger wording).

## Scheduler ops — first daily fires paused by disk guard; stale backup compressed; catch-up run (2026-09-14)

- The daily timer fired on time on 2026-09-12 11:16 UTC (successful; snapshot `c687e406…`), then the **2026-09-13 and 2026-09-14 fires were paused by the resource guard** with exit code 75: `FREE_DISK_MB_BELOW_THRESHOLD:15159<15360` (Sun) and `14575<15360` (Mon). The guard behaved exactly as designed -- it refuses to run when free space is too low for an outcome rebuild -- and systemd correctly recorded each as a failed run (no in-day retry). This is not a scheduler defect.
- **Root cause**: the shared VPS disk had fallen to ~14-15 GB free (93%). Largest project-owned consumer was a **19 GB uncompressed full DB dump** (`market_genome_20260822T063154Z.sql`, 3 weeks old). Docker reported ~21 GB of images as "reclaimable", but nearly all belong to unrelated tenants on this shared box and were deliberately left untouched.
- **With authorization**: verified the dump's SHA-256 (`03d63e1f…` OK, 58s), then **gzipped it in place** 19 GB -> 2.7 GB (85.5% reduction, ~16 GB reclaimed; disk 15 GB -> 30 GB free). Wrote `market_genome_20260822T063154Z.sql.gz.sha256` (verified OK) and retained the original uncompressed hash as `market_genome_20260822T063154Z.sql.gz.original-sql.sha256`. The backup remains recoverable (compressed), not deleted.
- **Catch-up run** (manually triggered the service once): exit `status=0/SUCCESS`, ~8.5 min (two days of accumulated bars drove an outcome rebuild). Report `prospective_daily_run_20260914T122306Z.json` (`run_hash 7e14bb76…`): 18 new bars (BTC/ETH +2 each; FX 0 over the weekend), 18 new forecasts (675 -> 693), 18 matured (357 -> 375). New snapshot `a213dfcf-bee3-4921-ba84-1f5dfa8ea270`: primary horizon 20 matured **18 -> 24**, skill -0.0591, 95% CI [-0.1498, +0.0361], status `PROSPECTIVE_EVIDENCE_ACCUMULATING`. Resource state after: 30 GB free / ~3.9 GB RAM.
- Regenerated `forecast_ledger.csv` (693 rows) and `run_history.csv` (16 rows) on the VPS; pulled the two newer daily-run artifacts and both files back to the local repo; SHA-256 reconciled local-vs-VPS for all five (all matched).
- Tomorrow's 11:16 UTC fire will proceed normally (free space comfortably above the 15 GB floor). **Note for a future enhancement**: the timer runs `run-daily` only; `forecast_ledger.csv`/`run_history.csv` are regenerated by a separate command, so the scheduled job does not refresh them -- candidate follow-up if a fully self-maintaining artifact set is wanted.

## Scheduler activated — daily prospective run on a systemd timer (2026-09-12)

Explicitly authorized activation of the scheduler that had been "READY but not activated" since Step 10B-C.2. No methodology change, no forecast logic change.

- **Mechanism**: systemd timer + oneshot service on the VPS host `raivstream` (not a sleep loop). `market-genome-prospective.timer` fires at **11:16 UTC daily** (`OnCalendar=*-*-* 11:16:00 UTC`, `Persistent=true`, `AccuracySec=1min`) and triggers `market-genome-prospective.service`, which runs the version-controlled wrapper `scripts/vps/run_prospective_daily.sh` -> `docker compose ... run --rm -T worker market-genome prospective run-daily`.
- Units are version-controlled at `infrastructure/deployment/vps/systemd/market-genome-prospective.{service,timer}`, installed at `/etc/systemd/system/`; `systemd-analyze verify` clean; timer enabled and active with next fire `2026-09-12 11:16 UTC`.
- **Service hardening**: `Type=oneshot`, `TimeoutStartSec=2400`, `Restart=no` (no in-day auto-retry, so a restart can never race the database advisory lock). Existing layers remain authoritative: `pg_try_advisory_lock`, the RAM/swap/disk guard (non-zero exit 75 on failure), provider-failure-safe and rate-limit-safe acquisition, incremental-only rebuild.
- **End-to-end validation**: manually triggered the service once. Exit `status=0/SUCCESS`; run report `prospective_daily_run_20260912T022220Z.json` (`run_hash a99886d9…`): 0 new bars, 0 new forecasts, 0 matured, 0 warnings; evaluation snapshot `85fe613c-52c6-47aa-add6-09a3bfad666d`. Idempotent as designed -- protected-table mutation check: only `prospective_evaluation_snapshots` 28 -> 29, every other table identical.
- **Operational notes**: `worker`/`api` images bake source at build time, so any code change requires `docker compose build worker` before the next fire. Logs via `journalctl -u market-genome-prospective.service`. Alpha Vantage free-tier usage is 6 requests/day, well within quota.
- Updated `docs/operations/prospective-scheduler-readiness.md` from "proposed / not activated" to the activated design (and corrected its stale `SCHEDULER_TIMING_NOT_YET_VALIDATED` note; timing has been `VALIDATED` at 11:16 UTC since 2026-08-31).
- No database/schema change this step; no new backup needed.

## Evaluation-layer correction — per-horizon metrics, primary-horizon headline, and a real bootstrap CI (2026-09-12, same day)

Prompted by the observation that the catch-up cycle's classification changed but the underlying evaluation pooled horizons and could not reach `SUPPORTED`. This is a **measurement-layer fix only** — no forecast, probability, context, outcome, or maturation behavior changed, and no methodology was altered.

- **Three real defects identified in `create_evaluation_snapshot` and fixed**:
  1. All horizons were pooled into one Brier score, but the unconditional baseline was computed only at the primary horizon — so e.g. horizon-5 forecasts were scored against a horizon-20 base rate.
  2. The baseline was computed for a single arbitrary instrument (`matured[0].instrument_id`), then applied to all 6 pooled instruments, though base rates differ by instrument.
  3. `bootstrap_ci_low` was hardcoded `None`, making the frozen protocol's `SUPPORTED` branch unreachable regardless of skill.
- **Fix**: metrics are now computed **per horizon**; each forecast is scored against a **per-row** unconditional base rate for its own instrument/timeframe/window-length/horizon (cached per combination); and a **paired block-bootstrap** (block size `floor(sqrt(n))`, deterministic seed derived from `sha256_canonical({protocol_id, primary_horizon})`, matching the project's existing paired-block-bootstrap convention in `context_dna_analysis.py`) produces a confidence interval for `brier_skill_vs_unconditional`. The snapshot's headline scalar fields and the evidence gate now use the **primary horizon (20)** — the horizon the frozen hypothesis is actually about; every horizon's full metric set is persisted in the new `per_horizon_metrics` column.
- **Files**: `forecast_analysis.py` (`_baseline_values`, per-row `brier_evaluation`, `paired_brier_skill_bootstrap`, `per_horizon_evaluation`), `service.py` (`create_evaluation_snapshot` rewritten), `models.py` + migration `0015_primary_horizon_evaluation` (5 nullable columns on `prospective_evaluation_snapshots`: `primary_horizon`, `primary_horizon_matured_count`, `bootstrap_ci_low`, `bootstrap_ci_high`, `per_horizon_metrics`), API schema, CLI `evaluate` output, and three docs. No new package, no change to any frozen protocol definition.
- **Tests**: 279 passing (up from 272) — `test_prospective_forecast_analysis.py` adds per-row-baseline, missing-baseline, deterministic-bootstrap, and per-horizon-grouping tests; `test_prospective_service.py` adds a primary-horizon-gate test (300 matured secondary forecasts must not satisfy the primary hypothesis) and a `SUPPORTED`-reachability test (260 primary-horizon matured with genuine skill reaches `SUPPORTED` with `bootstrap_ci_low > 0`). `python -m ruff check .` clean. Alembic head now `0015_primary_horizon_evaluation`.
- **Deployed verified**: 6 runtime files synced to the VPS with SHA-256 reconciled local-vs-VPS (all matched); `worker` and `api` images rebuilt; migration `0015` applied against the real PostgreSQL (`Running upgrade 0014 -> 0015`); `api` container recreated. VPS `scripts/vps/verify_market_genome.sh` **PASSED** (`expected_revision: 0015_primary_horizon_evaluation`, zero errors).
- **Corrected live readout** (new snapshot `f59e8043-3b87-482d-9928-32ec5a9eac73`, appended; the 27 prior snapshots are untouched): `primary_horizon=20`, `primary_horizon_matured_count=18`, `status=PROSPECTIVE_EVIDENCE_ACCUMULATING`.

  | Horizon | Matured | Brier skill vs unconditional | 95% bootstrap CI |
  |---|---|---|---|
  | 5 | 207 | -0.0009 | [-0.0412, +0.0372] |
  | 10 | 132 | -0.0247 | [-0.0838, +0.0366] |
  | **20 (primary)** | **18** | **-0.0032** | **[-0.0829, +0.0651]** |

- **Interpretation, stated plainly**: the earlier `WEAK` classification and the near-symmetric +0.0128 skill were artifacts of pooling and of a mismatched baseline. Per horizon, skill is slightly negative at every horizon, none distinguishable from zero, and the primary horizon has only 18 matured forecasts — far below the 100 minimum. The honest status is `PROSPECTIVE_EVIDENCE_ACCUMULATING`. This is a correction of the measurement, not new market evidence, and it is **not** a reason to change the forecast methodology (early-result firewall intact).
- **Mutation check**: only `prospective_evaluation_snapshots` changed (27 -> 28); `price_bars` (107,626), `pattern_windows`/`normalized_patterns`/`market_dna` (528,585), `market_contexts` (528,583), `outcome_observations` (3,728,868), `study_episodes` (417,520), `prospective_forecasts` (675), `prospective_forecast_outcomes` (357) all identical. No new backup taken: migration `0015` is purely additive (5 nullable columns) and touches zero existing data rows; disk 21GB free.

## Phase 1 Step 10B-C.3 continued — Weekend Cycle, All Instruments Fully Mature at Horizon-5/10 (2026-09-05)

Weekend cycle (Saturday) -- a mixed-calendar observation, not a weekday one. No methodology change.

- **Timing observation**: all 6 instruments genuinely advanced (FX to Friday's close `2026-09-04`, crypto to today `2026-09-05`). This is the 2nd weekend observation; weekday count stays at 9 (weekend observations don't count toward the weekday minimum/preferred, by design). `SCHEDULER_TIMING_VALIDATED` held, candidate unchanged at `11:16 UTC`.
- **Live run**: 54 new forecasts, 567 -> 621.
- **Ninth maturation cohort: 36 more matured** (174 total) -- the largest single cohort yet, horizon-5 AND horizon-10 for all 6 instruments in the same run. All 6 instruments have now matured at both horizons; **no instrument has yet reached horizon-20**. Full bulk verification repeated across all 174: chain-of-custody, temporal integrity, immutability, idempotency -- **174/174 pass everything**.
- **Classification remains `PROSPECTIVE_CONTEXT_SIGNAL_NOT_SUPPORTED`**, but the skill estimate moved noticeably toward zero -- snapshot `9aee56f2-bd90-4126-ba60-1733dc3ce5dd`: Brier 0.2508, skill **-0.0128** (up from -0.0501 yesterday), balanced_accuracy 0.638, MCC 0.310. Still negative, so the classification itself hasn't flipped, but the trend is worth simply recording -- not interpreting -- per the early-result firewall.
- Regenerated `forecast_ledger.csv` (621 rows) and `run_history.csv` (12 rows). All artifacts hash-reconciled local-vs-VPS. Resource/health: 28GB disk free (stable), all containers healthy, `verify_market_genome.sh` PASSED.

## Phase 1 Step 10B-C.3 continued — Ninth Weekday Cycle, Classification Stable (2026-09-04)

Ninth weekday cycle. No methodology change.

- **Timing observation (weekday #9)**: 5 of 6 instruments genuinely advanced (EURUSD_AV had no new bar today -- it was one day ahead of the other FX pairs as of yesterday, so nothing new to report for it this cycle; correctly no forced/fabricated forecast for it). `SCHEDULER_TIMING_VALIDATED` held, candidate unchanged at `11:16 UTC`.
- **Live run**: 45 new forecasts (5 instruments x 3 window lengths x 3 horizons, EURUSD_AV excluded since it had no new data), 522 -> 567.
- **Eighth maturation cohort: 18 more matured** (138 total) -- the remaining 3 FX pairs (GBPUSD/USDJPY/AUDUSD) reached horizon-10 maturity, joining EURUSD_AV and the crypto pair; all 6 instruments have now matured at both horizon-5 and horizon-10. Full bulk verification repeated across all 138: chain-of-custody, temporal integrity, immutability, idempotency -- **138/138 pass everything**.
- **Classification remains `PROSPECTIVE_CONTEXT_SIGNAL_NOT_SUPPORTED`** -- snapshot `4e11f5c6-6a9f-4f20-b197-f55d9977eb46`: Brier 0.2585, skill -0.0501 (roughly stable vs -0.0528 yesterday), balanced_accuracy 0.645, MCC 0.318. No protocol change made; this remains research evidence, not a trigger for action.
- Regenerated `forecast_ledger.csv` (567 rows) and `run_history.csv` (11 rows). All artifacts hash-reconciled local-vs-VPS. Resource/health: 28GB disk free (stable), all containers healthy, `verify_market_genome.sh` PASSED.

## Phase 1 Step 10B-C.3 continued — Minimum Evidence Threshold Crossed, First Formal Classification (2026-09-03)

Eighth weekday cycle. No methodology change. **This is the first cycle where the frozen protocol's own decision classifier produces a real (non-`ACCUMULATING`) classification.**

- **Timing observation (weekday #8)**: all 6 instruments genuinely advanced (EURUSD_AV one day ahead of the other 3 FX pairs at `2026-09-03`; GBPUSD/USDJPY/AUDUSD at `2026-09-02`; crypto at `2026-09-03`). `SCHEDULER_TIMING_VALIDATED` held, candidate unchanged at `11:16 UTC`.
- **Live run**: 54 new forecasts, 468 -> 522.
- **Seventh maturation cohort: 24 more matured** (120 total, crossing the 100-minimum for the first time) -- includes **the first-ever FX horizon-10 maturation** (EURUSD_AV, 3 window lengths), plus more horizon-5 across the FX cohort. Full bulk verification repeated across all 120: chain-of-custody, temporal integrity, immutability, idempotency -- **120/120 pass everything**.
- **First formal classification**: `market-genome prospective evaluate` returned `status: "PROSPECTIVE_CONTEXT_SIGNAL_NOT_SUPPORTED"` -- not `PROSPECTIVE_EVIDENCE_ACCUMULATING`, for the first time. This is the frozen `classify_prospective_decision` rule actually firing (matured_count=120 >= minimum_evidence=100, and brier_skill_vs_unconditional=-0.0528 <= 0.0), not an informal read. Snapshot `a42da72f-ae4a-4088-862b-12a3ac404f4a`: Brier 0.2594, skill -0.0528, balanced_accuracy 0.653, MCC 0.339.
  - **Per the early-result firewall, no protocol/methodology change was made.** This is reported as the actual output of the pre-registered classifier, not spun positive or negative.
  - **Caveat worth recording**: 120 is just over the 100 *minimum*, well short of the 250 *preferred* target the protocol itself designates for a confident call. The classifier's "SUPPORTED" branch additionally requires `bootstrap_ci_low > 0.0`, but `create_evaluation_snapshot` has always hardcoded `bootstrap_ci_low=None` (bootstrap confidence intervals were never wired into this evaluation path) -- so "SUPPORTED" is currently unreachable regardless of the skill sign; only "NOT_SUPPORTED"/"WEAK"/"ACCUMULATING" can ever be returned by the current implementation. This is a pre-existing implementation gap, not something introduced today, and is noted here rather than silently accepted.
- Regenerated `forecast_ledger.csv` (522 rows) and `run_history.csv` (10 rows). All artifacts hash-reconciled local-vs-VPS. Resource/health: 29GB disk free (stable), all containers healthy, `verify_market_genome.sh` PASSED.

## Phase 1 Step 10B-C.3 continued — Seventh Weekday Cycle, Approaching the Minimum Threshold (2026-09-02)

Seventh weekday cycle. No methodology change.

- **Timing observation (weekday #7)**: all 6 instruments genuinely advanced (FX to `2026-09-01`, crypto to `2026-09-02`). `SCHEDULER_TIMING_VALIDATED` held, candidate time unchanged at `11:16 UTC`.
- **Live run**: 54 new forecasts, 414 -> 468.
- **Sixth maturation cohort: 24 more matured** (96 total) -- horizon-5 across all 6 instruments plus horizon-10 for BTCUSD_AV/ETHUSD_AV again (FX horizon-10 still pending). Full bulk verification repeated across all 96: chain-of-custody, temporal integrity, immutability, idempotency -- **96/96 pass everything**.
- **Interim evaluation** (n=96, still `INTERIM_ONLY`): snapshot `581a82db-df1e-40cb-943b-d1e246259b29` -- Brier 0.2566, skill vs. unconditional **-0.0335** (first negative reading, down from +0.045 at n=72), balanced_accuracy 0.643, MCC 0.349. Per the early-result firewall, this fluctuation is not reacted to -- still far too small a sample, and the metric has swung both directions already as evidence accumulated. Status correctly stayed `PROSPECTIVE_EVIDENCE_ACCUMULATING`.
- **96/100 matured -- next cycle will likely cross the minimum interpretation threshold for the first time.** This is not itself a trigger to interpret results; 100 is the frozen protocol's minimum, not a target to react to the moment it's crossed, and 250 remains the preferred threshold.
- Regenerated `forecast_ledger.csv` (468 rows) and `run_history.csv` (9 rows). All artifacts hash-reconciled local-vs-VPS. Resource/health: 29GB disk free (stable), all containers healthy, `verify_market_genome.sh` PASSED.

## Phase 1 Step 10B-C.3 continued — Sixth Weekday Cycle (2026-09-01)

Sixth weekday cycle. No methodology change.

- **Timing observation (weekday #6)**: all 6 instruments genuinely advanced (FX to `2026-08-31`, crypto to `2026-09-01`). `SCHEDULER_TIMING_VALIDATED` held, candidate time unchanged at `11:16 UTC`.
- **Live run**: 54 new forecasts, 360 -> 414.
- **Fifth maturation cohort: 12 more matured** (72 total) -- 3 horizon-5 + 3 horizon-10 for each of BTCUSD_AV/ETHUSD_AV (crypto continues to lead; FX horizon-10 hasn't reached maturity yet). Full bulk verification repeated across all 72: chain-of-custody, temporal integrity, immutability, idempotency -- **72/72 pass everything**.
- **Interim evaluation** (n=72, still `INTERIM_ONLY`): snapshot `6808df9a-f531-4641-9666-dfbd071d21e9` -- Brier 0.2402, skill vs. unconditional +0.0450 (down from +0.103 at n=60), balanced_accuracy 0.641, MCC 0.365 (down from 0.527). Metrics moved with more evidence, as expected at this sample size -- per the early-result firewall, no reaction, no protocol change. Status correctly stayed `PROSPECTIVE_EVIDENCE_ACCUMULATING` (72/100).
- Regenerated `forecast_ledger.csv` (414 rows) and `run_history.csv` (8 rows). All artifacts hash-reconciled local-vs-VPS. Resource/health: 29GB disk free (stable), all containers healthy, `verify_market_genome.sh` PASSED.

## Phase 1 Step 10B-C.3 continued — Preferred Timing Threshold Reached, First 10-Bar Maturations (2026-08-31)

Fifth weekday cycle, first real session after the weekend. No methodology change.

- **Timing observation (weekday #5 of 5 preferred)**: all 6 instruments genuinely advanced (FX to `2026-08-28`, the last trading day before the weekend; crypto to `2026-08-31`, today). `SCHEDULER_TIMING_VALIDATED` -- **preferred evidence threshold now fully met**: 5/5 distinct weekday observations, `limitations: []` (the "below preferred 5" note is gone), candidate time unchanged and stable across every observation so far at `11:16 UTC` (40 total observations, 5 weekday, 1 weekend).
- **Live run**: genuinely new data confirmed for all 6 instruments (crypto had 3 new bars each, since the weekend gap meant Sat/Sun/Mon all accumulated since Friday's check). 54 new forecasts, 306 -> 360.
- **Fourth maturation cohort: 30 more forecasts matured** (total 30 -> 60) -- includes **the first-ever 10-bar maturations** (BTCUSD_AV + ETHUSD_AV, 3 each, one per window length), alongside 24 more horizon-5 maturations (crypto got 6 each from the weekend's accumulated bars; FX got 3 each). Full bulk verification repeated across all 60: chain-of-custody (hash/return/MFE/MAE/bar-count/window/horizon linkage), temporal integrity (0 retroactive violations), immutability (forecast_hash recomputation), and idempotency (re-ran `mature`, 0 new, 0 duplicates) -- **60/60 pass everything**.
- **Interim evaluation** (n=60, still `INTERIM_ONLY`): snapshot `2919a1df-39af-4434-a1c7-6a42a54cde6f` -- Brier 0.2274, skill vs. unconditional +0.1026, balanced_accuracy 0.715, MCC 0.527. Status correctly stayed `PROSPECTIVE_EVIDENCE_ACCUMULATING` (60/100) -- still not near the interpretation threshold, nothing changed as a result.
- Regenerated `forecast_ledger.csv` (360 rows) and `run_history.csv` (7 rows). All artifacts hash-reconciled local-vs-VPS. Resource/health: 29GB disk free (stable), all containers healthy, `verify_market_genome.sh` PASSED.
- **Milestone**: scheduler-timing evidence gathering is now complete at the preferred standard (not just the bare minimum) with a stable, repeatedly-confirmed recommendation of `11:16 UTC`. Scheduler remains **not activated** -- this is evidence, not an authorization.

## Phase 1 Step 10B-C.3 continued — First FX Maturations, 4th Weekday Observation (2026-08-28)

Fourth weekday cycle. No methodology change. Two SSH connection resets occurred mid-command during this session (transient network, not a VPS resource issue -- disk/memory were stable throughout) -- both underlying remote operations were launched via `nohup`+background and continued running server-side; verified directly via `docker ps` rather than assumed, and both completed successfully.

- **Timing observation (weekday #4 of 5 preferred)**: all 6 instruments genuinely advanced (FX to `2026-08-27`, crypto to `2026-08-28`). `SCHEDULER_TIMING_VALIDATED` held, candidate time unchanged at `11:16 UTC` (34 total observations, 4 distinct weekdays, 1 weekend).
- **Live run**: genuinely new data confirmed for all 6 instruments. 54 new forecasts, 252 -> 306.
- **Third maturation cohort: 18 more forecasts matured** (total 12 -> 30) -- **the first time FX forecasts have ever matured**, not just crypto. All 18 are horizon-5, 3 per instrument across all 6 instruments (previously only BTCUSD_AV/ETHUSD_AV had reached maturity; FX needed more trading days to accumulate 5 bars). Full verification repeated across all 30 matured forecasts (bulk SQL check this time, not just the new 18): chain-of-custody (hash/return/MFE/MAE/bar-count/window/horizon linkage), temporal integrity (0 retroactive violations, all created before maturing), immutability (forecast_hash recomputation), and idempotency (re-ran `mature`, 0 new, 0 duplicates) -- **30/30 pass everything**.
- **Interim evaluation** (n=30, still `INTERIM_ONLY`): snapshot `d696b2f4-97f2-4688-9655-5a00754b58a7` -- Brier 0.2198, skill vs. unconditional +0.1435, balanced_accuracy 0.754, MCC now computable at 0.582 (first time both classes are well-represented enough). Status correctly stayed `PROSPECTIVE_EVIDENCE_ACCUMULATING` (30/100) -- these numbers remain far too small a sample to mean anything and are not driving any change.
- Regenerated `forecast_ledger.csv` (306 rows) and `run_history.csv` (6 rows). All artifacts hash-reconciled local-vs-VPS. Resource/health: 29GB disk free (stable), all containers healthy, `verify_market_genome.sh` PASSED.

## Phase 1 Step 10B-C.3 continued — Scheduler Timing Validated (With a Bug Caught First), Second Maturation Cohort (2026-08-27)

Third weekday cycle. No methodology change.

- **Timing observation (weekday #3 of 3)**: all 6 instruments genuinely advanced (FX to `2026-08-26`, crypto to `2026-08-27`). Initial analysis reported `SCHEDULER_TIMING_VALIDATED` with `candidate_safe_time_utc: "06:38"` -- **caught and did not report this before checking it**. Root cause: the very first (Sunday) observation was a *stale* check (FX still showing Friday's already-known close, `new_completed_bar_available=False`), but the analysis was using its timestamp (04:36-04:38 UTC) as the "earliest observed availability" for every instrument, including FX, even though that specific check never observed a genuinely new bar. Fixed `timing_analysis.py` to only anchor earliest/latest-observed-availability (and thus the candidate safe time) on rows where `new_completed_bar_available` is genuinely true, and to require every observed instrument have at least one such genuine observation before validating at all. **Corrected result: `candidate_safe_time_utc: "11:16"`** (FX's real earliest-observed genuine availability is 09:16 UTC, not 04:36) -- materially later and safer than the buggy figure. Added two regression tests reproducing the exact scenario (stale-carryover must never anchor the calculation; an instrument with zero genuine observations must block validation entirely). `SCHEDULER_TIMING_VALIDATED = YES` now holds correctly with 3/3 minimum (still below the preferred 5).
- **Live run**: genuinely new data confirmed for all 6 instruments. 54 new forecasts, 198 -> 252.
- **Second maturation cohort: 6 more forecasts matured** (same pattern as the first cohort -- all horizon-5, BTCUSD_AV/ETHUSD_AV, window lengths 16/32/64 -- this time from the 2026-08-22 forecast batch reaching its 5-bar maturity). Total matured: 6 -> 12. Full chain-of-custody/temporal-integrity/immutability/idempotency verification repeated with the same rigor as the first cohort -- **all 12 (not just the new 6) re-verified end to end, 12/12 pass** on every check (source hash, return, MFE, MAE, bar count, window/horizon linkage, no retroactive violations, recomputed forecast_hash matches stored value for every one).
- **Interim evaluation** (n=12, still `INTERIM_ONLY`): snapshot `dbacd350-7c1c-4221-8d16-15446d9e29cc` -- Brier 0.2199, skill vs. unconditional +0.0121 (now positive, but at n=12 this is not remotely conclusive), balanced_accuracy now computable (0.5, since a negative-direction outcome finally appeared), MCC still null. Status correctly stayed `PROSPECTIVE_EVIDENCE_ACCUMULATING` (12/100).
- Regenerated `forecast_ledger.csv` (252 rows) and `run_history.csv` (5 rows). All artifacts hash-reconciled local-vs-VPS. Resource/health: 29GB disk free, all containers healthy, `verify_market_genome.sh` PASSED.
- Local verification: `python -m pytest -q` -- 272 passed (up from 270, +2 for the timing-analysis regression tests). `python -m ruff check .` -- clean.

## Phase 1 Step 10B-C.3 continued — First Genuine Maturation, Chain-of-Custody Verified (2026-08-26)

Makeup cycle for a missed Tuesday (2026-08-25), run Wednesday. No methodology change.

- **Timing observation (weekday #2)**: all 6 instruments showed genuinely new data -- FX advanced to `2026-08-25` (Monday+Tuesday closes both newly published), crypto to `2026-08-26`. 2 of the required 3 distinct weekday dates now recorded; `SCHEDULER_TIMING_NOT_YET_VALIDATED`.
- **Live run**: genuinely new data confirmed for all 6 instruments via dry-run before proceeding. One live iteration: 54 new forecasts (6 instruments x 3 window lengths x 3 horizons, since every instrument advanced this time, unlike prior partial rounds) -- forecast count 144 -> 198. All protected-table deltas matched expectations exactly (price_bars +12, pattern_windows/normalized_patterns/market_dna +36, market_contexts +36, prospective_forecast_outcomes +6, evaluation_snapshots +1).
- **First genuine maturation: 6 forecasts** (all horizon-5, BTCUSD_AV + ETHUSD_AV, window lengths 16/32/64 each) -- the first time any prospective forecast in this project has reached a real outcome. Per explicit priority, verified chain-of-custody and immutability *before* looking at any metric:
  - **Chain of custody, independently verified via SQL join (not asserted)**: every `source_forward_outcome_id` resolves to a real, complete `OutcomeObservation` matching the same `pattern_window_id`+`horizon_bars`; `source_outcome_hash`, `actual_return`, MFE, MAE, and `future_bar_count` byte-match that row's own values for all 6/6.
  - **Temporal integrity**: all 6 forecasts created 2026-08-21 23:18-23:20 UTC, ~4.4 days before maturation (2026-08-26 09:35 UTC) -- zero retroactive violations.
  - **Immutability, empirically proven not just assumed from code**: recomputed each forecast's `forecast_hash` from its *current* field values (probability, source/context/historical-reference hashes, identifiers) and compared to the hash stored at creation -- matched exactly for all 6. (First attempt showed a false MISMATCH caused by a `Decimal`-vs-`float` type artifact in the verification script itself, not real data drift; caught and corrected before drawing any conclusion, by casting to `float()` to match the type used when the hash was originally computed.)
  - **Maturation idempotency**: re-ran `mature` immediately -- `matured_count: 0`, outcome count still exactly 6, zero duplicate groups. **PASS**.
  - All 6 provenance_class=TRUE_PROSPECTIVE, `data_revision_detected=false` for all.
- **Interim evaluation** (only after the above, exactly per instruction): snapshot `c21c52f5-5d0d-46fa-bdee-eb881b238574`, Brier 0.2000, skill vs. unconditional -0.0453, balanced_accuracy/MCC correctly null (all 6 outcomes were the same direction -- no negative class in this tiny sample). Status correctly stayed `PROSPECTIVE_EVIDENCE_ACCUMULATING` (6 of 100 minimum). Explicitly labeled `INTERIM_ONLY` everywhere; not used to change anything.
- New artifacts: `first_maturation_report.json` + `.md` (full verification detail + the 6 forecasts' hashes/values), regenerated `forecast_ledger.csv` (198 rows) and `run_history.csv` (4 rows, this time with the daily-run artifact correctly resolving to the persistent path per the Aug 24 fix). All hash-reconciled local-vs-VPS.
- Resource/health: 30GB disk free (maintenance held), all 3 containers healthy, `verify_market_genome.sh` PASSED.

## VPS maintenance — authorized Docker cleanup (2026-08-24, same day)

User-authorized, tightly-scoped maintenance in response to the disk-trend flag above. Instruction: prune only build cache and unused/dangling image layers *not referenced by any running or intentionally retained stopped container*; stop if Docker cannot prove an object is unused.

- **Read-only inventory first**: `docker system df -v` showed 26 tagged images, 55 containers (many belonging to unrelated projects sharing this VPS -- supabase-\*, powervend-\*, hotchocolate-\*, elliott-wave-detector-\*, slink-supabase-\*, gammagic-bpm-\*, ultraos-postgres, several raivstream-phase\* stacks). Only `market-genome-worker:latest` showed 0 containers (expected -- it's only ever run via `docker compose run --rm`, so between invocations nothing references it). Every other image had >=1 container reference, including several tied to *stopped* containers (`hotchocolate-web`/`hotchocolate-backend`/`hotchocolate-db` exited 7 days ago, `elliott-wave-detector-app` exited 2 months ago, multiple `slink-supabase-*` exited 2 months ago) belonging to other projects entirely. `docker images -f dangling=true` found **zero** dangling images.
- **Scope decision, reasoned explicitly before acting**: Docker's own "reclaimable" accounting (98% of image size) counts images not used by a *running* container, which is a materially looser bar than the user's own stop condition ("Stop if Docker cannot prove an object is unused"). A stopped container's image is not provably abandoned -- only its owner could say whether it's intentionally kept for a quick restart. Since I have no way to contact or verify intent for those other projects' stopped containers, and the user's directive explicitly required proof, I limited the prune to what's unconditionally, provably safe regardless of any other project's intent: build cache (never referenced by any container, by construction) and true dangling images (zero references, of which there were none). I did **not** run `docker image prune -a`, which would have removed images tied to those other projects' stopped containers without any way to confirm they're disposable.
- **Actions taken**: `docker builder prune -af` (removed 100% of build cache, 89 cache objects, all timestamped to our own worker/api rebuild history over the last ~2 days -- 7.499GB reclaimed). `docker image prune -f` (bare, dangling-only -- 0B reclaimed, none existed).
- **Before/after**: disk 24GB -> 30GB free (+6GB; image "size" also dropped 26.86GB -> 21.09GB in `docker system df`'s own accounting, likely shared-layer content-addressable storage overlap between BuildKit cache and image layers -- still entirely from our own build history, not from any other project's data). Container count unchanged at 55, image count unchanged at 26 -- **nothing besides build cache was removed**.
- **Verification**: all 3 `market-genome-*` containers confirmed healthy; spot-checked 6 other projects' containers (`supabase-db`, `powervend-db`, `ultraos-postgres`, `gammagic-bpm-postgres-1`, `raivstream-phase8b2-postgres`, `marketgenome-postgres-1`) all still running, untouched. `scripts/vps/verify_market_genome.sh`: **PASSED**.
- **Disclosure**: recovered ~6GB, not the full ~34GB `docker system df` had implied was "reclaimable" -- the remaining ~20GB is tied to other projects' images (mostly Supabase stacks and a few stopped containers from unrelated projects), which were deliberately left untouched per the scope above. If more headroom is ever needed, that would require the other projects' owners to confirm which stopped containers are safe to remove, not a unilateral Market Genome decision.

## Phase 1 Step 10B-C.3 continued — Second Timing Observation, Live Run, and Two Real Bugs Found Same-Day (2026-08-24)

Same phase, next real day (Monday -- first genuine weekday timing observation). No methodology change.

- **Bug #1, found immediately and fixed before reporting anything**: the first Monday observation (6 rows, one per instrument, all same day) initially reported `SCHEDULER_TIMING_VALIDATED` with `weekday_observation_count: 6` -- `analyze_timing_observations` was counting raw observation *rows*, not distinct calendar *dates*, so checking all 6 instruments once on one day trivially satisfied the 3-observation minimum meant to represent evidence spread across multiple different real days. Fixed `timing_analysis.py` to count distinct dates; added a permanent regression test (`test_multiple_instruments_checked_once_on_the_same_day_count_as_one_observation`) reproducing the exact scenario. Corrected result: `weekday_observation_count: 1`, `SCHEDULER_TIMING_NOT_YET_VALIDATED` -- honest.
- **Timing observation (corrected)**: FX unchanged at `2026-08-21` (Monday morning, not yet published); crypto advanced to `2026-08-24`. 16 total observation rows, 1 distinct weekday date, 1 distinct weekend date.
- **Live run authorized and executed**: crypto had genuinely new data (DB `2026-08-23` vs provider `2026-08-24`); FX did not. 18 new forecasts (2 crypto x 3 window lengths x 3 horizons), forecast count 126 -> 144. All protected-table deltas matched expectations exactly (price_bars +2, pattern_windows/normalized_patterns/market_dna +6, market_contexts +6, evaluation_snapshots +1).
- **First maturation check, independently verified**: 0 of 144 forecasts have a matching complete `OutcomeObservation`. `FIRST_MATURATION_PENDING` continues.
- **Bug #2, found immediately after the live run**: the run's own report claimed `"daily_run_artifact_path": "research/reports/prospective_context_validation/prospective_daily_run_20260824T053654Z.json"`, but the file did not exist anywhere on the VPS host. Root cause: `run-daily`'s new (Step 10B-C.2) artifact-writing code used a bare relative path, which resolves against the *worker container's* working directory, not the repo root -- and since the container runs with `--rm`, anything written outside the mounted `/opt/market-genome/reports` volume is destroyed the instant the container exits. This means the Step 10B-C.2 completion report's claim that "run-daily writes its own audit artifact" was never actually verified for persistence (only the JSON field was checked, not the file on disk) -- a real gap in that round's own verification rigor, now corrected. **Fixed**: `audit_dir` now resolves via `MARKET_GENOME_REPORT_ROOT` (the env var `docker-compose.vps.yml` already sets and mounts at `/opt/market-genome/reports` for exactly this purpose), falling back to the old relative path only for local/dev use. Added a permanent regression test. **Recovery**: the lost artifact's full content was still available from the live run's own captured stdout (nothing about the underlying database evidence was ever at risk -- only this convenience file). Reconstructed it faithfully from that capture, explicitly labeled with a `_recovery_note` field disclosing exactly what happened, and placed it at the correct path. Verified going forward: `MARKET_GENOME_REPORT_ROOT` inside the container now correctly resolves to `/opt/market-genome/reports` (confirmed via direct container inspection).
- Local verification: `python -m pytest -q` -- 270 passed (up from 268, +2 for the two regression tests). `python -m ruff check .` -- clean. Migration head unchanged at `0014`.
- VPS: synced 4 changed files (`timing_analysis.py`, `main.py`, and their 2 test files), rebuilt `worker` twice (counting fix, then path fix). `scripts/vps/verify_market_genome.sh`: **PASSED**.
- Regenerated `forecast_ledger.csv` (144 rows) and `run_history.csv` (3 rows -- the recovered artifact's row has some blank fields since it's in the older CLI-report shape rather than the newer audit_payload shape; honestly reflects what's actually in that file rather than fabricating the missing fields).
- **Operational flag, not yet acted on**: VPS disk down to 24GB free (from 34GB two days ago) -- `docker system df` shows 26.86GB in images (98% reclaimable) and 7.5GB in build cache (100% reclaimable), from repeated `worker` image rebuilds across sessions without cleanup. Still above the 15GB floor, but the trend is worth addressing soon; flagged to the user rather than pruning unprompted (this is a heavily shared multi-tenant box).

## Phase 1 Step 10B-C.3 completion — Scheduler Timing Observation, Continued Evidence Accumulation, and First-Maturation Check

Observation-only phase, no methodology change. No Market DNA, no trading logic, no AI/ML model.

- **Pre-flight audit**: protocol id/hash/FROZEN status unchanged; 126 forecasts, all `TRUE_PROSPECTIVE`/`PENDING_OUTCOME`; distribution reconciled exactly (108 from 2026-08-22, +18 crypto-only from 2026-08-23); all prior artifacts (ledger, run history, scheduler-readiness doc, both daily-run artifacts) intact and hash-reconciled.
- **New pure module** `packages/prospective/market_genome_prospective/timing_analysis.py` (`is_weekend`, `analyze_timing_observations`, `result_to_dict`): weekday/weekend classification, per-instrument earliest/latest observed-availability tracking (explicitly a lower bound, never a claim about the true publication instant), and a conservative candidate-safe-time calculation (slowest instrument's earliest observed time + a fixed margin) gated on a minimum of 3 weekday observations.
- **New script** `scripts/record_provider_timing_observation.py`: bounded, append-only provider check across all 6 instruments, writing durable `provider_timing_observations.csv` rows and regenerating `scheduler_timing_analysis.json` from the complete observation history each time (never just the new rows) -- never persists market data to the database (the underlying `provider.fetch()` call only writes a discarded temp-directory CSV).
- **Real bug found and fixed during first live use**: the new script initially fired all 6 provider requests back-to-back with no delay, self-inflicting `PROVIDER_RATE_LIMITED` on 2 of 6 instruments (Alpha Vantage's free tier enforces ~5 requests/minute; the production acquisition manifest already spaces requests 15s apart for exactly this reason, which the new script had not matched). Fixed by adding the same 15s inter-instrument delay; re-ran cleanly with all 6 succeeding.
- **Timing observations recorded for 2026-08-23 (Sunday)**: 10 total observations (0 weekday, 10 weekend -- the 4 partial/rate-limited ones from the first attempt were kept as an honest historical record, not deleted). FX instruments' provider-latest-date stayed at `2026-08-21` (correct weekend behavior); crypto at `2026-08-23`. `SCHEDULER_TIMING_NOT_YET_VALIDATED` (0 of the required minimum 3 weekday observations) -- correctly not claimed validated from a single weekend day.
- **Dry-run + no-new-data determination**: `run-daily --dry-run` showed FX still stale locally (`would_fetch: true`) but the timing observation already confirmed the *provider* has nothing newer than `2026-08-21` for FX either -- genuinely `NO_NEW_COMPLETED_BAR` for all 6 instruments. **No live run was performed** -- forcing one would have been manufacturing activity against unchanged provider state, explicitly prohibited this phase.
- **First-maturation check, verified by direct inspection, not assumption**: independently queried `outcome_observations` for every horizon-5 forecast's `(pattern_window_id, horizon_bars)` pair -- 0 have a complete match. Traced the reason precisely: the oldest FX windows (end `2026-08-20`) have only 1 available future bar so far (needs 5; next FX close is Monday `2026-08-24`); the oldest crypto windows (end `2026-08-21`) have 2 available future bars (needs 5, three more days out). **Result: `NO_FORECASTS_READY_TO_MATURE` / `FIRST_MATURATION_PENDING`** -- genuinely not yet eligible, not manufactured or estimated from calendar days alone.
- Source-layer integrity: every protected table identical to Step 10B-C.2's final state (126 forecasts, 0 outcomes, 7 evaluation snapshots) -- correctly zero mutation, since no live run occurred this phase.
- Local verification: `python -m pytest -q` -- 268 passed (up from 258). `python -m ruff check .` -- clean. Migration head unchanged at `0014` (file-based artifacts only, no schema change needed). `docker compose config --quiet` -- passed.
- VPS: synced 6 new/changed files, hash-reconciled every one; rebuilt `worker` twice (initial deploy, then the rate-limit-delay fix). `scripts/vps/verify_market_genome.sh`: **PASSED**. Disk 34GB free (down from 36GB -- image-rebuild accumulation is worth watching over future rounds, still comfortably above the 15GB floor).
- Artifacts updated: `provider_timing_observations.csv` (new, 10 rows), `scheduler_timing_analysis.json` (new), copied back to the local repo and hash-reconciled. `forecast_ledger.csv`/`run_history.csv` unchanged this round (nothing new to reflect, since no live run occurred).

## Phase 1 Step 10B-C.2 completion — Prospective Daily Operations Hardening, Maturation Readiness, and Scheduler Qualification

Hardening pass, no methodology change. No Market DNA in the primary forecast, no trading logic, no AI/ML model.

- **Protocol drift check**: re-verified `market_context_forecast_v1` (same id, same configuration_hash as Step 10B-C.1) -- zero drift.
- **Pre-flight audit of the 108 existing forecasts**: all `TRUE_PROSPECTIVE`/`PENDING_OUTCOME` (2 per instrument/window/horizon combo from the two prior live runs); confirmed all 54 forecast IDs from the prior daily-run artifact exist in Postgres and the artifact's `run_hash` matches.
- **Secret-handling audit**: confirmed the Alpha Vantage key exists in the worker's environment, reaches the provider client, and appears nowhere else on the VPS filesystem (full recursive grep, zero matches outside the env file). Added defensive `_redact_secrets()` at the two CLI call sites that echo raw provider exception text, even though tracing confirmed no current path actually embeds the key (`urllib` exceptions never include the request URL; `AlphaVantageProviderError` messages are built only from response payload content).
- **New pure module** `packages/prospective/market_genome_prospective/daily_operations.py`: `is_stale`, `detect_provider_date_regression`, `InstrumentDailyPlan` -- the shared logic dry-run preview and the real run now both use, so "stale" can never be defined two different ways.
- **Provider-date regression guard** added to `run-daily`'s acquisition step: if a provider's latest date for an instrument is ever older than what's already persisted, that instrument's fetch is skipped and `PROVIDER_DATE_REGRESSION` is recorded -- never deletes or overwrites newer local data.
- **Postgres advisory run-lock** added around real (non-dry-run) `run-daily` executions (`pg_try_advisory_lock`/`pg_advisory_unlock`, scoped to real runs only). **Verified live, twice**: first two attempts to prove rejection used a flawed multi-connection test methodology and incorrectly appeared to pass through (each ran to full completion); root-caused as a test-harness timing/connection issue, not a code bug; re-tested properly (single-session 60s hold, verified via `pg_locks`) and confirmed correct rejection (`PROSPECTIVE_RUN_ALREADY_ACTIVE`).
- **Crash recovery verified live**: forcibly terminated (`pg_terminate_backend`) a session holding the lock to simulate an abrupt worker crash -- the advisory lock released immediately, confirming a crashed run never leaves a stale lock behind.
- **Disk-free guard** added to the resource guard (`ResourceSnapshot.free_disk_mb`, `evaluate_resource_guard(..., min_free_disk_mb=...)`), opt-in so the existing `studies prepare-data` caller is unaffected; wired into `run-daily` with a 15GB default (`--min-free-disk-mb`).
- **Dry-run/real-run divergence found and fixed a second time**: `--dry-run` reported `database_latest_date` per instrument (via the shared `is_stale` helper) for the first time this round, unifying the staleness decision the preview and the real run both rely on.
- **Precise new-forecast-ID tracking**: `run-daily` now captures a before/after set diff of forecast IDs scoped to the exact protocol, replacing a fuzzy "created in the last 2 hours" heuristic that could double-count or miss forecasts depending on when a report was generated.
- **`run-daily` now writes its own `prospective_daily_run_<UTC timestamp>.json` audit artifact directly** at the end of every real invocation (provider code, instrument universe, new bars by instrument, precise new forecast IDs, matured count, evaluation snapshot ID, per-instrument warnings, resource state, run hash) -- no longer dependent on a separately-invoked script guessing a time window after the fact.
- **`scripts/generate_prospective_ledger.py` refactored**: still regenerates `forecast_ledger.csv` from the database; the old imprecise `write_daily_run_audit` (2-hour lookback) was removed since `run-daily` now does this precisely itself; added `write_run_history` producing a compact `run_history.csv` by reading the existing daily-run artifacts (operational provenance -- which days ran, which instruments updated, forecast/matured counts, warnings -- not a performance dashboard).
- **Horizon readiness** added to `market-genome prospective status`: pending-forecast count and oldest forecast timestamp per horizon, explicitly flagged as a calendar-day lower bound, not a trading-bar-accurate maturation date.
- **Live operational verification (real-world, not simulated)**:
  - Provider health check: both FX (`EUR/USD`) and crypto (`BTC/USD`) reachable, credentials valid.
  - **Mixed FX/crypto calendar handled correctly in one real run**: FX instruments' latest date stayed at `2026-08-21` (weekend, no new close) while crypto's advanced to `2026-08-23` -- all 6 instruments processed independently in the same invocation with zero errors, zero forced/fabricated forecasts.
  - Live iteration created 18 new `TRUE_PROSPECTIVE` forecasts (2 crypto instruments x 3 window lengths x 3 horizons), bringing the total to 126; forecast count before/after: 108 -> 126.
  - **Idempotency verified via real repeated execution** (not just a unit test): an immediate second real run against unchanged provider state reported `new_bars_imported: 0` for all 6 instruments, and every protected table (`price_bars`, `pattern_windows`, `normalized_patterns`, `market_dna`, `market_contexts`, `outcome_observations`, `prospective_forecasts`, `prospective_forecast_outcomes`) was byte-identical before/after -- only `prospective_evaluation_snapshots` grew (a snapshot is intentionally refreshed every real run).
  - **Disclosure**: debugging the run-lock test methodology (see above) accidentally triggered two additional real `run-daily` invocations beyond the intended one-plus-repeat. All were harmless -- confirmed via the same protected-table check, forecast count stayed at 126 throughout, only evaluation snapshots grew (7 total exist now). This is disclosed rather than omitted; it also strengthens the idempotency evidence (four consecutive real invocations, zero unintended mutation).
- Regenerated `research/reports/prospective_context_validation/forecast_ledger.csv` (126 rows) and the new `run_history.csv`; both copied back to the local repo and hash-reconciled with the VPS.
- New docs: `docs/operations/prospective-scheduler-readiness.md` (full A-P gate checklist, all PASS; proposed systemd-timer scheduler design, not activated; `SCHEDULER_TIMING_NOT_YET_VALIDATED` -- only one day's provider-availability observation exists so far). Updated `docs/architecture/prospective-context-forecasting.md` (Market DNA/shared-pipeline distinction) and `docs/operations/prospective-daily-run.md` (lock/disk-guard/regression-guard/artifact-writing behavior).
- Local verification: `python -m pytest -q` -- 258 passed (up from 254 at the start of this round / 233 at the end of Step 10B-C.1). `python -m ruff check .` -- clean. Migration head unchanged at `0014` (no schema change this round). `docker compose config --quiet` -- passed.
- VPS: synced 10 changed/new files, hash-reconciled every one; rebuilt the `worker` image 3 times (env/lock code, artifact-writing refactor, doc-only changes needed no rebuild). `scripts/vps/verify_market_genome.sh`: **PASSED**. Final resource state: 36GB disk free, 6.2GiB available memory, all 3 Market Genome containers healthy.
- `SCHEDULER_READY = YES` (all 16 checklist gates PASS, several verified live rather than only by unit test) -- **not activated**; `SCHEDULER_TIMING_NOT_YET_VALIDATED` (insufficient repeated observation to commit to a specific run time).

## Latest Step 10B-C.3 decision (updated 2026-09-12, after evaluation-layer correction)

**`PROSPECTIVE_EVIDENCE_ACCUMULATING`** (primary horizon). The mid-day `PROSPECTIVE_CONTEXT_SIGNAL_WEAK` reading was produced by the pre-fix evaluation and is superseded: that evaluation pooled horizons against a single horizon-20 baseline. Corrected per-horizon, per-row-baseline results are Brier skill -0.0009 (h5, n=207), -0.0247 (h10, n=132), and -0.0032 (h20/primary, n=18), all with 95% bootstrap CIs spanning zero; the primary horizon is well below the 100 minimum. Forecast count 675, matured 357 total (18 at the primary horizon). `SUPPORTED` is now genuinely reachable (bootstrap CI wired in) but is nowhere near being reached. `TRADING_LOGIC: NO`, `AI_MODEL: NO`, scheduler not activated. **No forecast methodology change** — evaluation/measurement only (migration `0015`). The daily cycle is now **scheduled** (systemd timer, `11:16 UTC`, activated 2026-09-12; see the scheduler section above), so primary-horizon evidence will accumulate automatically; it is still tiny, so keep letting it grow toward the 100 minimum before reading anything into horizon-20 skill.

## Latest Step 10B-C.2 decision

`PROSPECTIVE_EVIDENCE_ACCUMULATING` -- 126 real `TRUE_PROSPECTIVE` forecasts, 0 matured (0 of 100 minimum). Daily workflow hardened and live-verified across mixed calendars, idempotency (4 consecutive real runs, zero unintended mutation), run-lock (verified live including crash-recovery via forced backend termination), and provider-date-regression guarding. `SCHEDULER_READY = YES` on engineering grounds; scheduler **not activated**, `SCHEDULER_TIMING_NOT_YET_VALIDATED`. Recommended next action: continue periodic manual `run-daily` iterations; once several more days of provider-availability observations accumulate, revisit scheduler timing; separately decide on an expected-return methodology (still unpopulated).

## Latest Step 10B-C.1 decision

`PROSPECTIVE_EVIDENCE_ACCUMULATING` -- 108 real `TRUE_PROSPECTIVE` forecasts now exist (54 from the first proof iteration, 54 new from this round's authorized live run), 0 matured (0 of 100 minimum). No final test, no trading logic, no AI model. Scheduler not activated -- exactly one live iteration was run, per instruction. The Alpha Vantage key gap from the prior round is now resolved (persisted + compose passthrough fixed and verified working). Recommended next action: repeat `market-genome prospective run-daily` periodically (manually, or on a schedule if separately authorized) until enough forecasts mature -- horizon-20 outcomes won't mature for ~20 D1 bars from each forecast's date, so reaching the 100-minimum/250-preferred evidence threshold will take repeated iterations over several weeks. Separately: decide whether an expected-return-magnitude methodology should be frozen and wired up (currently `null` on every forecast, by omission rather than by design).

## Latest Step 10A.4 decision

`CONTEXT_DNA_TEST_COMPLETED`. No final-test lock, no final test, no model training, no trading logic, no AI/ML model. Per the phase's own next-step logic: since context is supported but DNA adds no meaningful (in fact slightly negative) incremental value, the recommended next phase is **Phase 1 Step 10B-C: Market Context Forecasting Baseline and Prospective Validation** -- the project should simplify toward the Market Context engine as the primary information layer rather than continue investing in Market DNA similarity refinement. Not started automatically, per instruction.

## Latest Step 10A.3 decision

`INDEPENDENT_REPLICATION_COMPLETED`. Classification: `REPLICATION_PARTIAL`. No final-test lock, no final test, no model training, no trading logic, no AI/ML model. Recommended next phase: diagnose whether the context-vs-DNA distinction holds under the excluded asset classes (equities, precious metals) if/when a provider covering them becomes available, and/or treat "does robust DNA similarity add value beyond context matching" as the next explicit, narrow hypothesis to test -- not a broad re-search of the original Step 10A parameter space.

## Latest state — Phase 1 Step 10A.2A Yahoo Finance Pilot Data Acquisition and VPS Study Environment

- Added optional Yahoo provider dependency group: `.[yahoo]` with `yfinance>=0.2.40,<0.3`.
- Installed and verified local optional provider runtime with `yfinance 0.2.66`.
- Added provider abstraction under `market_genome_data_ingestion.providers`.
- Added `yahoo_finance_v1` provider with D1-only interval support, canonical CSV generation, immutable acquisition sidecars, provenance, retry/backoff, pacing, and provider-specific warnings.
- Added provider acquisition service with dry-run planning, symbol filtering, provider manifest validation, and fetch orchestration.
- Added Yahoo pilot manifest:
  - `research/data/manifests/yahoo_market_data_pilot_v1.yaml`
- Added Yahoo pilot study manifest:
  - `research/studies/yahoo_multi_asset_pilot_v1.yaml`
- Added CLI commands:
  - `market-genome data providers`
  - `market-genome data provider-show yahoo_finance_v1`
  - `market-genome data fetch-manifest <manifest-path>`
  - `market-genome data fetch-yahoo <manifest-path>`
  - `market-genome data provider-smoke yahoo_finance_v1 --symbol SPY`
- Added Yahoo-specific quality warnings and provider manifest support to the existing manifest workflow.
- Enforced Yahoo-backed studies as `PILOT_ONLY` through `YAHOO_SOURCE_REQUIRES_INDEPENDENT_REPLICATION`.
- Added isolated VPS deployment package:
  - `infrastructure/deployment/vps/docker-compose.vps.yml`
  - `infrastructure/deployment/vps/.env.example`
  - `scripts/vps/bootstrap_market_genome.sh`
  - `scripts/vps/verify_market_genome.sh`
  - `scripts/vps/backup_market_genome.sh`
  - `scripts/vps/run_yahoo_pilot.sh`
- Added operations docs:
  - `docs/operations/vps-deployment.md`
  - `docs/operations/yahoo-pilot-study.md`
- Latest verification: `python -m pytest -q` collected 128 tests, all passed.
- Latest Ruff result: `python -m ruff check .` passed.
- Alembic history remains linear through `0010_multi_asset_diagnostic_study (head)`.
- `docker compose config --quiet` passed.
- VPS compose config passed with `.env.example`.
- CLI smoke checks passed for `market-genome --help`, `market-genome data --help`, `market-genome data providers`, `market-genome data provider-show yahoo_finance_v1`, `market-genome data fetch-yahoo --help`, and `market-genome studies --help`.
- Git Bash syntax checks passed for all VPS shell scripts.
- Live bounded Yahoo smoke test was run without persistence: `SPY`, 2024-01-01 to 2024-01-10, 6 rows returned, provider reachable, status `COMPLETED`.
- No Yahoo acquisition files were persisted, no VPS deployment occurred, no validation/final-test lock/final test was run.

## Latest Step 10A.2A decision

Yahoo provider and VPS preparation are locally implemented and verified. The next action is to review the local implementation, then explicitly authorize isolated VPS deployment and Yahoo pilot acquisition.

## Latest state — Phase 1 Step 10A.2 Real-Market Dataset Acquisition, PostgreSQL Verification, and Formal Multi-Asset Study Execution

- Added PostgreSQL runtime verification script at `scripts/verify_postgres_runtime.py`.
- Added real-data manifest service with manifest hashing, schema validation, dataset quality analysis, dry-run support, idempotent manifest import, and persisted import provenance.
- Added real-data manifests:
  - `research/data/manifests/real_market_data_v1.yaml`
  - `research/studies/real_multi_asset_episode_study_v1.yaml`
- Added `.gitignore` protections for `research/data/raw/` and `research/reports/`.
- Added CLI commands:
  - `market-genome data import-manifest <manifest-path> --dry-run`
  - `market-genome data import-manifest <manifest-path>`
  - `market-genome data quality-report --manifest <manifest-code>`
  - `market-genome studies refresh-dataset <study-id>`
  - `market-genome studies prepare-data <study-id>`
  - `market-genome studies status <study-id>`
  - `market-genome studies write-report-artifacts <study-id>`
- Added real-study preflight blockers for PostgreSQL runtime verification and real imported datasets when the study manifest requires them.
- Added final-test lock enforcement so not-ready or pilot-only studies cannot lock or run final tests.
- Added stage-appropriate local blocker artifacts under `research/reports/real_multi_asset_episode_study_v1/`.
- Latest verification: `python -m pytest -q` collected 116 tests, all passed.
- Latest Ruff result: `python -m ruff check .` passed.
- Alembic history remains linear with `0010_multi_asset_diagnostic_study (head)`.
- `docker compose config --quiet` passed.
- CLI smoke checks passed for `market-genome --help`, `market-genome data --help`, and `market-genome studies --help`.
- Docker daemon remains unavailable locally: `dockerDesktopLinuxEngine` pipe missing.
- PostgreSQL verification script returned structured `SKIPPED` because no explicit `MARKET_GENOME_DATABASE_URL` or `DATABASE_URL` was configured in the process environment.
- Real-data manifest dry-run discovered zero local raw files and returned `REAL_DATA_REQUIRED` for all configured datasets.

## Latest Step 10A.2 decision

`BLOCKED_PENDING_POSTGRES_AND_REAL_DATA`.

No real files were imported, no pilot was run, no validation comparison was run, no method was selected, no final-test lock was created, and no final test was run.

## Latest state — Phase 1 Step 10A.1 Real Multi-Asset Diagnostic and Episode-Diversity Study completion

- Added versioned multi-asset study definitions with `multi_asset_episode_study_v1`, `temporal_episode_v1`, and `episode_diverse_analogue_v1`.
- Implemented `market_genome_studies` package with study manifest loading, dataset inclusion checks, temporal episode assignment, episode-diversity quality gates, pilot/validation/final-test study phases, immutable final-test lock hashing, conservative study decisions, and Markdown study reports.
- Added persisted study models: `StudyManifest`, `StudyDatasetEntry`, `StudyEpisode`, `StudyPreflight`, and `StudyArm`.
- Added Alembic migration `0010_multi_asset_diagnostic_study`.
- Added the real-study manifest template at `research/studies/multi_asset_episode_study_v1.yaml`.
- Added API endpoints under `/api/v1/studies/...` for definitions, create/list/detail, datasets, preflight gates, episodes, arms, pilot/validation/final-test execution, metrics, segments, episode diversity, window/horizon matrix, and report retrieval.
- Added `market-genome studies ...` CLI commands for the same workflow.
- Added `same_asset_class_random_v1` baseline registration and baseline filtering behavior.
- Added benchmark script `scripts/benchmark_multi_asset_study.py`.
- Added architecture, research, API, and operations docs for study manifests, final-test locks, episode assignment, multi-asset studies, episode-diversity criteria, same-asset vs cross-asset comparisons, success criteria, and final-test runs.
- Expanded tests from 98 to 110 passing tests.
- Latest verification: `python -m pytest -q` collected 110 tests, all passed.
- Latest Ruff result: `python -m ruff check .` passed.
- Alembic history shows `0009_retrieval_diagnostics -> 0010_multi_asset_diagnostic_study (head)`.
- CLI smoke tests passed via bundled runtime script path for `market-genome --help`, `market-genome studies --help`, `market-genome diagnostics --help`, `market-genome experiments --help`, and `market-genome similarity --help`.
- `docker compose config --quiet` passed.
- Docker daemon is unavailable locally (`dockerDesktopLinuxEngine` pipe missing), and online PostgreSQL `alembic upgrade head` / `alembic current` remain pending because `localhost:5432` connection attempts timed out.
- Bounded multi-asset study benchmark on SQLite in-memory with 3 synthetic instruments and 60 bars each: 222 episodes, 48 study arms, status `FINAL_TEST_COMPLETE`, decision `NO_RETRIEVAL_EDGE`, elapsed 18.000 seconds.

## Latest study conclusion

Step 10A.1 now has the infrastructure to run a real multi-asset diagnostic study with episode-diversity controls and a final-test lock. The benchmark result is synthetic plumbing evidence only. No real multi-asset market dataset has been imported in this local workspace, so there is not yet real-market evidence supporting a predictive edge or escalation to learned representations.

## Latest recommended next phase

Import the real daily multi-asset universe named in `research/studies/multi_asset_episode_study_v1.yaml`, build windows/features/context/outcomes for those instruments, create the study manifest, run preflight, and stop if preflight reports insufficient instruments, asset classes, eligible queries, complete outcomes, or unique non-overlapping episodes.

## Latest state — Phase 1 Step 10A Retrieval Diagnosis and Representation Refinement completion

- Added diagnostic experiment registry with required Step 10A definitions, scaling methods, availability policies, and bounded weight configurations.
- Implemented `market_genome_diagnostics` package with feature distribution diagnostics, robust scale statistics, availability-aware distances, deterministic redundancy clusters, distance/outcome monotonicity, similarity deciles, neighbour dispersion helpers, episode grouping/capping, context compatibility, window/horizon alignment, diagnostic decisions, and immutable report generation.
- Added transparent refined similarity methods while preserving existing methods:
  - `dna_robust_cosine_v1`
  - `dna_robust_euclidean_v1`
  - `dna_group_balanced_v1`
  - `shape_dna_context_v2`
- Added persisted `DiagnosticArtifact` and `FeatureScalingSnapshot` models.
- Added Alembic migration `0009_retrieval_diagnostics`.
- Added diagnostics API endpoints for definitions, scaling methods, availability policies, weight configurations, diagnostic run creation/list/detail, artifact inspection, and report retrieval.
- Added `market-genome diagnostics ...` CLI commands.
- Added example configurations:
  - `research/experiments/representation_diagnostic.yaml`
  - `research/experiments/synthetic_motif_recovery.yaml`
  - `research/experiments/refined_similarity_validation.yaml`
- Added benchmark script `scripts/benchmark_retrieval_diagnostics.py`.
- Added architecture, research, API, and operations documentation for retrieval diagnostics, feature-scaling snapshots, availability-aware similarity, episode diversity, representation quality, redundancy, distance/outcome monotonicity, neighbour dispersion, window/horizon alignment, synthetic motif recovery, and refined similarity methods.
- Expanded tests from 84 to 98 passing tests.
- Latest verification: `python -m pytest -q` collected 98 tests, all passed.
- Latest Ruff result: `python -m ruff check .` passed.
- Alembic history shows `0008_validation_experiments -> 0009_retrieval_diagnostics (head)`.
- CLI smoke tests passed via bundled runtime script path for `market-genome --help`, `market-genome diagnostics --help`, `market-genome similarity --help`, and `market-genome experiments --help`.
- `docker compose config --quiet` passed.
- Online PostgreSQL `alembic upgrade head` and `alembic current` remain pending because localhost PostgreSQL is unreachable and Docker Desktop is unavailable locally.
- Bounded diagnostics benchmark on SQLite in-memory with 90 synthetic bars:
  - motif case: 26 candidates, 20 matches, decision `EPISODE_CONCENTRATION_FAILURE`, total 10.656 seconds.
  - noise case: 26 candidates, 20 matches, decision `EPISODE_CONCENTRATION_FAILURE`, total 10.235 seconds.

## Latest diagnostic conclusion

Initial Step 9 `NO_SUPPORTED_EDGE` should be treated as insufficient evidence from a small synthetic smoke benchmark, not a real-market failure. Step 10A’s bounded benchmark primarily exposes `EPISODE_CONCENTRATION_FAILURE`: overlapping/nearby episodes dominate the small synthetic candidate universe. There is not yet evidence supporting escalation to learned embeddings or deep learning.

## Latest recommended next phase

Phase 1 Step 10A.1 — Real multi-asset diagnostic study. The next useful work is to run these diagnostics on larger multi-instrument data with enough non-overlapping episodes to distinguish representation failure from dataset concentration.

## Latest state — Phase 1 Step 9 Validation, Baselines, and Walk-Forward Experiment Engine completion

- Added versioned validation experiment definitions, validation methods, baseline methods, metric definitions, and weighting methods.
- Implemented separate `market_genome_validation` package with deterministic hashes, fold generation, historical-as-of candidate eligibility, purge/embargo controls, neighbour weighting, outcome aggregation, calibration metrics, bootstrap intervals, multiple-testing helpers, and conservative experiment decisions.
- Added persisted `ExperimentRun`, `ExperimentFold`, `QueryEvaluation`, `ExperimentMetric`, and `ExperimentArtifact` models.
- Added Alembic migration `0008_validation_experiments`.
- Added validation/experiment API endpoints for definitions, methods, baselines, metrics, weighting, run creation, folds, evaluations, metrics, and report retrieval.
- Added `market-genome validation ...` and `market-genome experiments ...` CLI command groups.
- Added example experiment config at `research/experiments/baseline_market_analogue.yaml`.
- Added benchmark script `scripts/benchmark_validation_experiment.py`.
- Added architecture, research, API, and operations documentation for validation, walk-forward methods, purging/embargo, experiment storage, historical-as-of retrieval, baselines, metrics, calibration, bootstrap confidence, multiple testing, retrieval stability, context ablation, cross-asset validation, decisions, and experiment reports.
- Expanded tests from 73 to 84 passing tests.
- Latest verification: `python -m pytest -q` collected 84 tests, all passed.
- Latest Ruff result: `python -m ruff check .` passed.
- Alembic history shows `0007_similarity_retrieval -> 0008_validation_experiments (head)`.
- CLI smoke tests passed when invoked via the bundled runtime script path: `market-genome --help`, `market-genome validation --help`, and `market-genome experiments --help`.
- Validation benchmark on SQLite in-memory with 150 synthetic bars: 2 folds, 160 evaluations, 96 metrics, 1 artifact, decision `NO_SUPPORTED_EDGE`, 14.656 seconds.
- `docker compose config --quiet` passed.
- Local PostgreSQL runtime verification remains pending because Docker Desktop is unavailable locally (`dockerDesktopLinuxEngine` pipe missing).

## Latest recommended next phase

Phase 1, Step 10A — Diagnose and refine retrieval representations without adding trading logic. The first validation benchmark produced `NO_SUPPORTED_EDGE`, so the next useful step is research diagnostics rather than adding strategy/execution behavior.

## Latest state — Phase 1 Step 8 Historical Similarity and Analogue Retrieval Engine completion

- Added versioned similarity method registry with `shape_euclidean_v1`, `shape_correlation_v1`, `dna_cosine_v1`, and `market_analogue_v1`.
- Implemented separate `market_genome_similarity` package.
- Added historical-only analogue retrieval service using normalized paths, Market DNA vectors, and Market Context compatibility.
- Added explicit no-lookahead behavior: similarity methods declare `uses_future_outcomes = false`, default candidate filtering is `historical_only`, and match diagnostics record that future outcomes were not used.
- Added persisted `SimilarityQuery` and `SimilarityMatch` models.
- Added Alembic migration `0007_similarity_retrieval`.
- Added similarity method/search/query/match API endpoints and per-window similar lookup.
- Added `market-genome similarity ...` CLI commands.
- Added architecture, research, API, and operations documentation for similarity retrieval.
- Added benchmark script `scripts/benchmark_similarity_search.py`.
- Expanded tests from 66 to 73 passing tests.
- Latest verification: `python -m pytest -q` collected 73 tests, all passed.
- Latest Ruff result: `python -m ruff check .` passed.
- Alembic history shows `0006_forward_outcomes -> 0007_similarity_retrieval (head)`.
- Similarity benchmark on SQLite in-memory with 120 synthetic bars and `top_k=20`: 112 candidates, 20 matches, 7.828 seconds.
- Local PostgreSQL runtime verification remains pending because Docker Desktop is unavailable locally.

## Latest recommended next phase

Phase 1, Step 9 — Validation, Baselines, and Walk-Forward Experiment Engine.

## Latest state — Phase 1 Step 7 Forward Outcome Engine completion

- Added `forward_outcomes_v1` outcome definitions and outcome-set registry.
- Implemented separate `market_genome_outcomes` package.
- Added strictly future-only outcome computation anchored to `PatternWindow.end_timestamp` final close.
- Added future simple/log return, MFE/MAE, time-to-MFE/MAE, realized future volatility, path efficiency, max drawdown/runup, direction, continuation/reversal, barrier, sequencing, and normalized forward path calculations.
- Added deterministic configuration, future-bar, forward-path, and outcome hashes.
- Added immutable `OutcomeBuild` and `OutcomeObservation` models.
- Added Alembic migration `0006_forward_outcomes`.
- Added full/incremental/range-capable outcome build service with source-window hash verification and partial-horizon persistence.
- Added partial outcome versioning with `is_complete`, `available_future_bars`, quality flags, and `supersedes_observation_id`.
- Added outcome registry/build/observation/path/barrier/diagnostic API endpoints and per-window outcome lookup.
- Added `market-genome outcomes ...`, `market-genome outcome ...`, and `market-genome windows outcomes` CLI commands.
- Added architecture, research, API, and operations documentation for outcomes.
- Added benchmark script `scripts/benchmark_outcome_build.py`.
- Expanded tests from 57 to 66 passing tests.
- Latest verification: `python -m pytest -q` collected 66 tests, all passed.
- Latest Ruff result: `python -m ruff check .` passed.
- Local PostgreSQL runtime verification remains pending because Docker Desktop is unavailable locally.

## Latest recommended next phase

Phase 1, Step 8 — Historical Similarity and Analogue Retrieval Engine.

## Latest state — Phase 1 Step 6 Market Context Engine completion

- Added `transparent_context_v1` context producer registry and context dimension/state registry.
- Implemented separate Market Context layer from Market DNA.
- Added trend, volatility, volatility phase, persistence, activity, shock, market phase, and multi-resolution classifications.
- Added dimension confidence, composite confidence, completeness score, evidence, opposing evidence, diagnostics, quality flags, composite context code, and context family code.
- Added deterministic context configuration hashes and context hashes.
- Added source-window, source-representation, and source-feature-vector hash verification before context extraction.
- Added full/incremental/range-capable context build service.
- Added persisted `ContextBuild` and `MarketContext` models.
- Added Alembic migration `0005_market_context`.
- Added context producer/build API endpoints and Market Context list/detail/dimensions/explanation/diagnostics/multi-resolution endpoints.
- Added `market-genome context ...` and `market-genome contexts ...` CLI commands.
- Added docs for context engine, Market Context, confidence, multi-resolution context, methods, thresholds, API, and operations.
- Added benchmark script `scripts/benchmark_context_build.py`.
- Expanded tests from 38 to 57 passing tests.
- Latest verification: `python -m pytest` collected 57 tests, all passed.
- Latest Ruff result: `python -m ruff check .` passed.
- Context benchmark on SQLite in-memory with 150 synthetic bars and lengths `[8, 16, 32, 64, 128, 256]`: full-volume case built 507 contexts in 31.256 seconds; missing-volume case built 507 contexts in 24.021 seconds.
- Local PostgreSQL runtime verification remains pending because Docker Desktop is unavailable locally.

## Latest recommended next phase

Phase 1, Step 7 — Forward Outcome Engine.

## Existing state

The GitHub repository was empty when cloned into `C:\MarketGenome`.

## First delivery implemented

- Created modular monorepo structure.
- Added Python packaging and dependency metadata.
- Added Docker Compose for PostgreSQL/TimescaleDB and Redis.
- Added Alembic migration environment and foundation schema migration.
- Added SQLAlchemy domain models for instruments, timeframes, data sources, and price bars.
- Added FastAPI health and readiness endpoints.
- Added CSV OHLCV validation and import service.
- Added architecture, research, ADR, API, and operations documentation.
- Added unit/integration test foundations.
- Recorded intended production URL as `https://genome.fothlog.com`.
- Set up VPS directory at `/opt/marketgenome` on `raivstream`.
- Started VPS Docker services for Market Genome PostgreSQL and Redis.
- Created and migrated the `market_genome` database to `0001_foundation_schema`.

## Known limitations

- Normalization, feature extraction, regimes, outcomes, similarity search, dashboard, and validation engine are not implemented yet.
- Tests require project dependencies to be installed in the active Python environment.
- VPS app service/reverse proxy is not configured yet; only the project directory and backing services are in place.

## Phase 1 Step 2/3 continuation

- Added registry service operations for instruments, timeframes, data sources, and idempotent standard timeframe seeding.
- Added persisted import audit models: `DataImport` and `DataImportIssue`.
- Added CSV import API and CLI.
- Added registry API and CLI inspection commands.
- Added `PatternWindow` and `WindowBuild` models.
- Added deterministic SHA-256 source-data and build-configuration hashing.
- Added idempotent full, incremental, and range-capable window build service.
- Added window build/list/detail/source-bar API and CLI commands.
- Added Alembic migration `0002_registry_imports_windows`.
- Added deterministic synthetic sample data under `tests/fixtures/sample_ohlcv.csv`.
- Added window benchmark script under `scripts/benchmark_window_build.py`.
- Expanded tests from 5 to 14 passing tests.
- Latest verification: `python -m pytest` collected 14 tests, all passed.
- Latest Ruff result: `python -m ruff check .` passed.
- Alembic history shows `0001_foundation_schema -> 0002_registry_imports_windows (head)`.
- `docker compose config` passed.
- Local PostgreSQL execution remains unverified because Docker Desktop is unavailable (`dockerDesktopLinuxEngine` pipe missing).
- CLI syntax smoke tests passed for documented command help.
- Benchmark script result on SQLite in-memory: 10,000 synthetic bars, lengths `[8, 16, 32, 64]`, 39,884 windows, 50.812 seconds.
- Integration sample result: imported 20 synthetic OHLCV rows and built 18 windows for lengths `[8, 16]`.

## Recommended next phase

Phase 1, Step 4 — scale-invariant normalization and fixed-point resampling.
 
## Phase 1 Step 4 normalization/resampling completion

- Added code-based normalization method registry for `normalization_v1`.
- Implemented methods: `anchored_simple_return`, `anchored_log_return`, `anchored_ohlc`, `zscore_close`, `range_close`, `volatility_targeted_return`, `atr_anchored_ohlc`, and `volume_relative_mean`.
- Added fixed-point resampling with `linear` and `previous` interpolation.
- Added persisted `NormalizationBuild` and `NormalizedPattern` records.
- Added deterministic normalization configuration hashes and representation hashes.
- Added source-window hash verification before normalization.
- Added idempotent full/incremental/range-capable normalization build service.
- Added normalization API endpoints and CLI commands.
- Added Alembic migration `0003_normalized_patterns`.
- Added benchmark script `scripts/benchmark_normalization_build.py`.
- Added docs for normalization architecture, resampling, methods, API, and operations.
- Expanded tests from 14 to 32 passing tests.
- Latest verification: `python -m pytest` collected 32 tests, all passed.
- Latest Ruff result: `python -m ruff check .` passed.
- Alembic history shows `0002_registry_imports_windows -> 0003_normalized_patterns (head)`.
- `docker compose config` passed.
- CLI syntax smoke tests passed for `market-genome normalization --help` and `market-genome normalized --help`.
- Local PostgreSQL execution remains unverified because Docker Desktop is unavailable (`dockerDesktopLinuxEngine` pipe missing).
- Normalization benchmark on SQLite in-memory: 10,000 bars, 39,884 windows, anchored log return to 64 points created 39,884 representations in 93.177 seconds, anchored OHLC to 64 points created 39,884 representations in 163.668 seconds.
- Performance observation: the first benchmark attempt timed out due to one source-bar query per window. A targeted normalization-service cache now loads ordered bars once per instrument/timeframe and slices in memory. Tests passed after this change. Window generation itself remains a major SQLite benchmark cost.
- Integration sample result: imported 20 synthetic OHLCV rows, built 18 windows for lengths `[8, 16]`, normalized 18 anchored-log-return representations idempotently, and retrieved values/diagnostics through the API.

## Phase 1 Step 5 Market DNA feature engine completion

- Added `market_dna_v1` feature-set registry with 75 ordered feature definitions.
- Implemented deterministic Market DNA feature calculation across path, trend, momentum, volatility, distribution, persistence, complexity, swing structure, candle, and volume groups.
- Added persisted `FeatureBuild` and `MarketDNA` models.
- Added deterministic feature configuration hashes and feature-vector hashes.
- Added source-window and source-representation hash verification before feature extraction.
- Added idempotent full/incremental/range-capable feature build service.
- Added feature registry/build API endpoints and Market DNA list/detail/values/diagnostics endpoints.
- Added `market-genome features ...` and `market-genome dna ...` CLI commands.
- Added Alembic migration `0004_market_dna_features`.
- Added docs for the feature engine, Market DNA, feature API, operations, feature selection, persistence/complexity, and swing structure.
- Added benchmark script `scripts/benchmark_feature_build.py`.
- Expanded tests from 32 to 38 passing tests.
- Latest verification: `python -m pytest` collected 38 tests, all passed.
- Latest Ruff result: `python -m ruff check .` passed.
- Local PostgreSQL runtime verification remains pending because Docker Desktop is unavailable locally.

## Updated recommended next phase

Phase 1, Step 6 — transparent market regime engine.

## Updated recommended next phase

Phase 1, Step 5 — Market DNA feature engine.
## Phase 1 Step 10A.2B VPS Yahoo pilot completion

- Deployed and ran the isolated Yahoo pilot under `/opt/market-genome` on VPS `raivstream`.
- Stabilized only the Market Genome stack:
  - reduced isolated Postgres runtime settings from oversized defaults to conservative VPS values;
  - added bounded Market Genome swapfile `/opt/market-genome/swap/market-genome.swap`;
  - added a CLI resource guard for `studies prepare-data`;
  - raised only the CLI worker memory cap to `2800m` after confirming refresh failed from worker cgroup OOM, not host OOM.
- PostgreSQL runtime verification passed at Alembic head `0011_window_continuity_policy_identity`.
- All 13 accepted Yahoo pilot instruments completed windows, normalization, Market DNA, context, outcomes, and episode refresh:
  - SPY, QQQ, DIA, IWM
  - GOLD_FUTURES_YAHOO, SILVER_FUTURES_YAHOO, COPPER_FUTURES_YAHOO
  - EURUSD, GBPUSD, USDJPY_YAHOO, AUDUSD
  - BTCUSD_YAHOO, ETHUSD_YAHOO
- WTI remained excluded/rejected because historical Yahoo data contained non-positive prices; it was not repaired or imported silently.
- Study ID: `d608a16b-b586-44ea-bcdc-d930957bdeeb`.
- Final preflight result: `PILOT_ONLY`.
- Only remaining blocker: `YAHOO_SOURCE_REQUIRES_INDEPENDENT_REPLICATION`.
- Validation, final-test locking, model training, and trading/execution work were not run.
- Final report artifacts: `/opt/market-genome/reports/yahoo_pilot_final_20260816T104219Z_0011`.
- Post-preflight backup: `/opt/market-genome/data/backups/market_genome_20260816T104340Z.sql` with SHA-256 sidecar.
- Latest local verification after hotfixes: `python -m pytest -q` passed with 134 tests; `python -m ruff check .` passed.

## Phase 1 Step 10A.2C bounded Yahoo pilot validation completion

- Ran a bounded Yahoo-only historical-as-of pilot validation on VPS `raivstream`.
- Study ID: `d608a16b-b586-44ea-bcdc-d930957bdeeb`.
- Experiment ID: `a9390628-2efd-48ed-bcae-90bbd161d74f`.
- Configuration: `research/experiments/yahoo_pilot_validation_v1.yaml`.
- Validation runner: `scripts/run_yahoo_pilot_validation.py`.
- Configuration hash: `bc1ef6568f8c3923d2a7d189062c404413e1c17e1e8fa3f03b322be13ad7b20e`.
- Dataset hash: `c592377dabfc341ef2e5de1bef77adf222b383c2a72b599e75f706b93a9015cd`.
- Dry-run accepted a bounded grid of 102 method/baseline configurations, 39 query windows, and 117 query-horizon cases.
- Validation produced 11,934 evaluation rows in report artifacts.
- Pilot decision: `PILOT_RETRIEVAL_PROMISING`.
- Best descriptive method in this bounded run: `dna_robust_cosine_v1`, same-instrument arm, horizon 20, K=10, uniform weighting.
- Best-method headline metrics:
  - Brier score: `0.22897435897435897`
  - Brier skill vs unconditional: `0.24768323504633538`
  - Brier skill vs same-context random: `0.06589958158995812`
  - Direction accuracy: `0.6410256410256411`
  - Return MAE: `0.047806908929466665`
  - Expected calibration error: `0.19743589743589746`
  - Raw p-value: `0.005834574490554626`
  - Benjamini-Hochberg adjusted p-value: `0.05759289658418437`
- The result remains `PILOT_ONLY`; Yahoo evidence is not formal support.
- Required blocker remains `YAHOO_SOURCE_REQUIRES_INDEPENDENT_REPLICATION`.
- No final-test lock, final test, model training, trading signal, position sizing, or execution logic was run.
- Source-layer mutation check passed; protected source/artifact counts were unchanged for `price_bars`, `pattern_windows`, `normalized_patterns`, `market_dna`, `market_contexts`, `outcome_observations`, and `study_episodes`.
- Validation report artifacts: `/opt/market-genome/reports/yahoo_pilot_validation_v1`.
- Pre-validation backup: `/opt/market-genome/data/backups/market_genome_20260816T165005Z.sql` with SHA-256 sidecar.
- Post-validation backup: `/opt/market-genome/data/backups/market_genome_20260816T170018Z.sql` with SHA-256 sidecar.
- VPS final state: PostgreSQL, Redis, and API healthy; no Market Genome worker running; Alembic at `0011_window_continuity_policy_identity (head)`.
- Latest local verification after validation runner changes: `python -m pytest -q` passed with 134 tests; `python -m ruff check .` passed.
