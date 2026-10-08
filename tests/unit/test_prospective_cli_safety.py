from __future__ import annotations

from pathlib import Path

CLI_PATH = Path(__file__).resolve().parents[2] / "apps" / "research-cli" / "market_genome_cli" / "main.py"


def _prospective_run_daily_source() -> str:
    source = CLI_PATH.read_text(encoding="utf-8")
    start = source.index("def prospective_run_daily")
    end = source.index("\n@prospective_app.command(\"mature\")")
    return source[start:end]


def test_run_daily_rebuilds_derived_state_only_when_new_bars_actually_imported() -> None:
    """Regression guard for the Step 10B-C incident: run-daily used to rebuild
    windows/normalization/DNA/context/outcomes unconditionally every invocation, even
    when acquisition found no new bars (or failed outright), which is wasted work and
    -- combined with the horizon-subset bug below -- created 267,246 duplicate rows."""
    section = _prospective_run_daily_source()
    assert "if bars_after > bars_before:" in section


def test_run_daily_rebuilds_outcomes_with_the_full_research_horizon_set() -> None:
    """Regression guard: the outcome build's identity hash includes the exact
    requested-horizons list, so requesting a narrower subset than the original research
    build (e.g. just the protocol's primary+secondary horizons) creates duplicate
    OutcomeObservation rows under a new configuration_hash instead of recognizing the
    ones that already exist. Must always request RESEARCH_OUTCOME_HORIZONS here, not
    the protocol's own (narrower) `horizons` variable."""
    section = _prospective_run_daily_source()
    assert 'OutcomeBuildService(session).build(outcome_set_code="forward_outcomes_v1", horizons=RESEARCH_OUTCOME_HORIZONS' in section

    full_source = CLI_PATH.read_text(encoding="utf-8")
    assert "RESEARCH_OUTCOME_HORIZONS = [1, 3, 5, 10, 20, 40, 60]" in full_source


def test_run_daily_dry_run_identity_check_matches_the_true_prospective_unique_constraint() -> None:
    """The dry-run existence check must use the same identity fields as create_forecast's
    idempotency lookup (protocol_id, pattern_window_id, horizon_bars, provenance_class) --
    not the old timestamp-equality identity -- or a dry run's 'would_create' would drift
    out of sync with what a real run actually does."""
    section = _prospective_run_daily_source()
    assert "ProspectiveForecast.pattern_window_id == latest_window.id" in section
    assert 'ProspectiveForecast.provenance_class == "TRUE_PROSPECTIVE"' in section
    assert "ProspectiveForecast.forecast_timestamp == latest_window.end_timestamp" not in section


def _prospective_forecast_only_source() -> str:
    full_source = CLI_PATH.read_text(encoding="utf-8")
    start = full_source.index('@prospective_app.command("forecast-only")')
    end = full_source.index('\n@prospective_app.command("mature")')
    return full_source[start:end]


def test_forecast_only_command_exists_and_is_decoupled_from_acquisition() -> None:
    """forecast-only must create forecasts from whatever windows/contexts already
    exist without touching acquisition (no provider fetch, no CSV import, no derived
    state rebuild) -- callers that already ran acquisition separately (or don't need
    it) should be able to advance just the forecast step."""
    section = _prospective_forecast_only_source()
    assert "def prospective_forecast_only" in section
    for forbidden in ("get_provider(", "persist_csv_import(", "WindowBuildService(", "NormalizationBuildService(", "OutcomeBuildService("):
        assert forbidden not in section


def test_forecast_only_command_supports_provenance_class_override() -> None:
    section = _prospective_forecast_only_source()
    assert '"--provenance-class"' in section
    assert "provenance_class=provenance_class" in section


def test_run_daily_dry_run_previews_acquisition_without_executing_it() -> None:
    """A dry run must report what acquisition would do (staleness, provider requests)
    so the dry-run integrity gate is meaningful -- previously it skipped acquisition
    reporting entirely and only ever reflected pre-existing windows. The preview must
    stay read-only: request construction (requests_from_manifest) is a pure local
    builder, but provider.fetch()/persist_csv_import() must never run under --dry-run."""
    section = _prospective_run_daily_source()
    assert '"would_fetch"' in section
    assert '"provider_requests_preview"' in section
    assert '"new_completed_bars_expected"' in section

    dry_run_branch_start = section.index("if dry_run:", section.index("stale = is_stale("))
    dry_run_branch_end = section.index("else:", dry_run_branch_start)
    dry_run_branch_code_only = "\n".join(
        line for line in section[dry_run_branch_start:dry_run_branch_end].splitlines() if not line.strip().startswith("#")
    )
    assert "provider.fetch(" not in dry_run_branch_code_only
    assert "persist_csv_import(" not in dry_run_branch_code_only


def test_run_daily_reports_current_forecast_and_matured_counts() -> None:
    section = _prospective_run_daily_source()
    assert '"current_forecast_count"' in section
    assert '"current_matured_count"' in section


def test_run_daily_holds_a_postgres_advisory_lock_for_real_runs_only() -> None:
    """Two real run-daily invocations against the same database must never overlap.
    The lock is scoped to `not dry_run` -- concurrent dry runs are harmless previews
    and must not be blocked by this guard."""
    section = _prospective_run_daily_source()
    assert "pg_try_advisory_lock(hashtext(:name))" in section
    assert "pg_advisory_unlock(hashtext(:name))" in section
    assert '"status": "PROSPECTIVE_RUN_ALREADY_ACTIVE"' in section
    assert "not dry_run and session.get_bind().dialect.name" in section


def test_run_daily_enforces_a_disk_free_guard() -> None:
    section = _prospective_run_daily_source()
    assert "min_free_disk_mb" in section


def test_run_daily_detects_provider_date_regression_and_skips_persisting() -> None:
    """A provider date older than what's already persisted must never delete or
    overwrite newer local data -- only skip persisting for that instrument and record
    a warning, leaving every other instrument's processing untouched."""
    section = _prospective_run_daily_source()
    assert "detect_provider_date_regression(latest_bar_date, provider_latest_date)" in section
    assert '"PROVIDER_DATE_REGRESSION"' in section

    regression_branch_start = section.index("if detect_provider_date_regression(")
    regression_branch_end = section.index("if result.csv_path", regression_branch_start)
    regression_branch = section[regression_branch_start:regression_branch_end]
    assert "persist_csv_import(" not in regression_branch


def test_run_daily_uses_shared_is_stale_helper() -> None:
    """The staleness decision must come from the same pure helper the dry-run preview
    and the real acquisition step both rely on, so they can never define "stale"
    differently from each other."""
    section = _prospective_run_daily_source()
    assert "stale = is_stale(latest_bar_date, today)" in section


def test_run_daily_isolates_per_instrument_acquisition_failures() -> None:
    """One instrument's provider/import failure must never abort processing of the
    other instruments in the same run -- the try/except around a single request must
    live inside the per-instrument loop, not wrap (or be wrapped by) the whole loop."""
    section = _prospective_run_daily_source()
    for_symbol_start = section.index("for symbol in protocol.instrument_universe:")
    try_start = section.index("try:", for_symbol_start)
    except_start = section.index("except Exception as exc:  # noqa: BLE001", try_start)
    acquisition_error_line = section[except_start : except_start + 200]
    assert '"acquisition_error"' in acquisition_error_line
    # The except block must be nested well inside the outer per-instrument loop, not
    # at its own top level (i.e. indented further than the `for symbol` line itself).
    for_symbol_indent = len(section[for_symbol_start - 100 : for_symbol_start].splitlines()[-1])
    except_indent = len(section[except_start - 100 : except_start].splitlines()[-1])
    assert except_indent > for_symbol_indent


def test_run_daily_tracks_new_forecast_ids_by_precise_set_diff() -> None:
    """new_forecast_ids must come from a before/after set diff scoped to this exact
    protocol, not a fuzzy 'created in the last N hours' time window that could
    double-count across close-together runs or miss forecasts entirely if the report
    is generated well after the run."""
    section = _prospective_run_daily_source()
    assert "forecast_ids_before = {" in section
    assert "forecast_ids_after = {" in section
    assert "new_forecast_ids = sorted(forecast_ids_after - forecast_ids_before)" in section
    assert "interval '2 hours'" not in section


def test_run_daily_writes_its_own_daily_run_artifact() -> None:
    """Every real run-daily invocation must produce prospective_daily_run_<UTC
    timestamp>.json directly -- not rely on a separately-invoked script run at some
    unknown later time, which cannot know the run's precise boundaries."""
    section = _prospective_run_daily_source()
    assert '"prospective_context_validation"' in section
    assert '"run_hash"' in section
    assert "ALPHA_VANTAGE_API_KEY" not in section
    assert "apikey" not in section


def test_run_daily_artifact_path_resolves_against_the_mounted_report_root() -> None:
    """Regression guard for a real bug caught live on 2026-08-24: a bare relative path
    resolves against the *process* working directory, not the repo root -- inside a
    `docker compose run --rm` worker container that differs from the host, and the
    container is removed on exit, so the artifact was silently destroyed before it
    could ever be copied out. MARKET_GENOME_REPORT_ROOT is the env var
    docker-compose.vps.yml already sets and mounts at /opt/market-genome/reports for
    exactly this purpose -- the audit directory must be resolved from it."""
    section = _prospective_run_daily_source()
    assert 'os.environ.get("MARKET_GENOME_REPORT_ROOT"' in section
    assert 'audit_dir = Path("research/reports/prospective_context_validation")' not in section


def test_status_command_reports_horizon_readiness() -> None:
    full_source = CLI_PATH.read_text(encoding="utf-8")
    start = full_source.index('@prospective_app.command("status")')
    section = full_source[start:]
    assert '"horizon_readiness"' in section
    assert "pending_count" in section
    assert "oldest_forecast_timestamp" in section
