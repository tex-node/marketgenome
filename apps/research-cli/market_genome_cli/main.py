from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import typer
from alembic import command
from alembic.config import Config
from market_genome_context.definitions import list_context_dimensions, list_context_producers
from market_genome_context.service import ContextBuildService
from market_genome_data_ingestion.acquisition import (
    acquisition_plan,
    classify_provider_error,
    fetch_manifest,
    load_provider_manifest,
    provider_catalog,
    requests_from_manifest,
)
from market_genome_data_ingestion.cross_provider_qa import compare_canonical_files
from market_genome_data_ingestion.csv_import import CsvImportMetadata, persist_csv_import
from market_genome_data_ingestion.manifest import (
    import_manifest,
    load_data_manifest,
    quality_reports_for_manifest,
    write_quality_csv,
)
from market_genome_data_ingestion.providers.base import get_provider
from market_genome_diagnostics.definitions import (
    list_availability_policies,
    list_diagnostic_definitions,
    list_scaling_methods,
    list_weight_configurations,
)
from market_genome_diagnostics.service import RetrievalDiagnosticService, load_diagnostic_config
from market_genome_domain.database import SessionLocal
from market_genome_domain.models import (
    ContextBuild,
    DataImport,
    DiagnosticArtifact,
    ExperimentMetric,
    ExperimentRun,
    FeatureBuild,
    Instrument,
    MarketContext,
    MarketDNA,
    NormalizationBuild,
    NormalizedPattern,
    OutcomeBuild,
    OutcomeObservation,
    PatternWindow,
    ProspectiveEvaluationSnapshot,
    ProspectiveForecast,
    ProspectiveProtocol,
    ReplicationLock,
    ReplicationProtocol,
    ReplicationRecord,
    SimilarityMatch,
    SimilarityQuery,
    StudyArm,
    StudyDatasetEntry,
    StudyEpisode,
    StudyManifest,
    StudyPreflight,
    WindowBuild,
)
from market_genome_domain.registry import RegistryService
from market_genome_features.definitions import (
    get_feature_set,
    list_feature_definitions,
    list_feature_sets,
)
from market_genome_features.service import FeatureBuildService
from market_genome_normalization.methods import list_methods
from market_genome_normalization.service import NormalizationBuildService, NormalizationPolicies
from market_genome_outcomes.definitions import (
    get_outcome_set,
    list_outcome_definitions,
    list_outcome_sets,
)
from market_genome_outcomes.service import OutcomeBuildService
from market_genome_prospective.daily_operations import (
    RUN_LOCK_NAME,
    detect_provider_date_regression,
    is_stale,
)
from market_genome_prospective.definitions import list_prospective_protocol_definitions
from market_genome_prospective.service import ProspectiveContextForecastService
from market_genome_replication.definitions import list_replication_protocol_definitions
from market_genome_replication.service import ReplicationService
from market_genome_shared.hashing import sha256_canonical
from market_genome_similarity.definitions import get_similarity_method, list_similarity_methods
from market_genome_similarity.service import SimilaritySearchService
from market_genome_studies.definitions import list_study_definitions
from market_genome_studies.service import MultiAssetStudyService, load_study_config
from market_genome_validation.definitions import (
    list_baseline_methods,
    list_experiment_definitions,
    list_metric_definitions,
    list_validation_methods,
    list_weighting_methods,
)
from market_genome_validation.service import ValidationExperimentService, load_experiment_config
from market_genome_window_engine.service import WindowBuildService, WindowQualityPolicy
from sqlalchemy import text

from market_genome_cli.resource_guard import evaluate_resource_guard, read_resource_snapshot

app = typer.Typer(help="Market Genome research operations CLI.")
db_app = typer.Typer(help="Database commands.")
registry_app = typer.Typer(help="Registry maintenance commands.")
instruments_app = typer.Typer(help="Instrument commands.")
timeframes_app = typer.Typer(help="Timeframe commands.")
sources_app = typer.Typer(help="Data-source commands.")
data_app = typer.Typer(help="Data import commands.")
windows_app = typer.Typer(help="Pattern-window commands.")
normalization_app = typer.Typer(help="Normalization build commands.")
normalized_app = typer.Typer(help="Normalized pattern inspection commands.")
features_app = typer.Typer(help="Market DNA feature commands.")
dna_app = typer.Typer(help="Market DNA inspection commands.")
context_app = typer.Typer(help="Market context build commands.")
contexts_app = typer.Typer(help="Market context inspection commands.")
outcomes_app = typer.Typer(help="Forward outcome build commands.")
outcome_app = typer.Typer(help="Forward outcome observation inspection commands.")
similarity_app = typer.Typer(help="Historical similarity and analogue retrieval commands.")
validation_app = typer.Typer(help="Validation registry commands.")
experiments_app = typer.Typer(help="Validation experiment commands.")
diagnostics_app = typer.Typer(help="Retrieval diagnostic commands.")
studies_app = typer.Typer(help="Multi-asset diagnostic study commands.")
replication_app = typer.Typer(help="Independent replication protocol/lock commands.")
prospective_app = typer.Typer(help="Prospective Market Context forecasting commands.")
DEFAULT_STUDY_REPORT_OUTPUT_DIR = Path("research/reports/real_multi_asset_episode_study_v1")
QUALITY_REPORT_OUTPUT_OPTION = typer.Option(None, "--output")
FETCH_OUTPUT_DIRECTORY_OPTION = typer.Option(None, "--output-directory")
COMPARE_PROVIDERS_OUTPUT_OPTION = typer.Option(None, "--output")
DEFAULT_PROSPECTIVE_MANIFEST_ARGUMENT = typer.Argument(Path("research/data/manifests/independent_replication_v1.yaml"))
# Must match the horizon set originally used to build forward_outcomes_v1 for this
# study's data (research/studies/independent_robust_dna_replication_v1.yaml). Any
# outcome rebuild must request this exact set, never a subset -- the build's identity
# hash includes the requested-horizons list, so a narrower request creates duplicate
# rows under a new hash rather than recognizing the existing ones (see Step 10B-C).
RESEARCH_OUTCOME_HORIZONS = [1, 3, 5, 10, 20, 40, 60]
STUDY_REPORT_OUTPUT_DIR_OPTION = typer.Option(
    DEFAULT_STUDY_REPORT_OUTPUT_DIR,
    "--output-dir",
)

app.add_typer(db_app, name="db")
app.add_typer(registry_app, name="registry")
app.add_typer(instruments_app, name="instruments")
app.add_typer(timeframes_app, name="timeframes")
app.add_typer(sources_app, name="sources")
app.add_typer(data_app, name="data")
app.add_typer(windows_app, name="windows")
app.add_typer(normalization_app, name="normalization")
app.add_typer(normalized_app, name="normalized")
app.add_typer(features_app, name="features")
app.add_typer(dna_app, name="dna")
app.add_typer(context_app, name="context")
app.add_typer(contexts_app, name="contexts")
app.add_typer(outcomes_app, name="outcomes")
app.add_typer(outcome_app, name="outcome")
app.add_typer(similarity_app, name="similarity")
app.add_typer(validation_app, name="validation")
app.add_typer(experiments_app, name="experiments")
app.add_typer(diagnostics_app, name="diagnostics")
app.add_typer(studies_app, name="studies")
app.add_typer(replication_app, name="replication")
app.add_typer(prospective_app, name="prospective")


def _alembic_config() -> Config:
    return Config("infrastructure/alembic.ini")


def _redact_secrets(message: str) -> str:
    """Defense-in-depth: strip any provider API key present in the environment from a
    message before it is echoed or persisted to a report/artifact. Current provider
    error paths never actually embed the key (verified: urllib exceptions never embed
    the request URL, and AlphaVantageProviderError messages are built only from the
    response payload), but this keeps that true even if a future code path forgets."""
    for env_var in ("ALPHA_VANTAGE_API_KEY",):
        value = os.environ.get(env_var)
        if value:
            message = message.replace(value, "***REDACTED***")
    return message


@db_app.command("status")
def db_status() -> None:
    """Check database connectivity."""
    with SessionLocal() as session:
        result = session.execute(text("select 1")).scalar_one()
    typer.echo(f"database_ok={result == 1}")


@db_app.command("upgrade")
def db_upgrade() -> None:
    """Apply Alembic migrations to head."""
    command.upgrade(_alembic_config(), "head")


@registry_app.command("seed-timeframes")
def seed_timeframes() -> None:
    """Seed standard timeframes idempotently."""
    with SessionLocal() as session:
        items = RegistryService(session).seed_standard_timeframes()
    typer.echo(f"seeded_timeframes={len(items)}")


@instruments_app.command("list")
def instruments_list(limit: int = 100, offset: int = 0) -> None:
    """List instruments."""
    with SessionLocal() as session:
        for item in RegistryService(session).list_instruments(limit=limit, offset=offset):
            typer.echo(f"{item.id}\t{item.symbol}\t{item.exchange or ''}\t{item.name or ''}")


@instruments_app.command("show")
def instruments_show(symbol: str, exchange: str | None = None) -> None:
    """Show an instrument by symbol and optional exchange."""
    with SessionLocal() as session:
        item = RegistryService(session).get_instrument_by_symbol(symbol, exchange)
        if item is None:
            raise typer.Exit(1)
        typer.echo(f"{item.id}\t{item.symbol}\t{item.exchange or ''}\t{item.asset_class}")


@timeframes_app.command("list")
def timeframes_list(limit: int = 100, offset: int = 0) -> None:
    """List timeframes."""
    with SessionLocal() as session:
        for item in RegistryService(session).list_timeframes(limit=limit, offset=offset):
            typer.echo(f"{item.id}\t{item.code}\t{item.seconds}\t{item.label}")


@sources_app.command("list")
def sources_list(limit: int = 100, offset: int = 0) -> None:
    """List data sources."""
    with SessionLocal() as session:
        for item in RegistryService(session).list_sources(limit=limit, offset=offset):
            typer.echo(f"{item.id}\t{item.name}\t{item.source_type}")


@data_app.command("import-csv")
def data_import_csv(
    path: Path,
    symbol: str = typer.Option(..., "--symbol"),
    name: str | None = typer.Option(None, "--name"),
    asset_class: str = typer.Option("other", "--asset-class"),
    exchange: str | None = typer.Option(None, "--exchange"),
    currency: str | None = typer.Option(None, "--currency"),
    timezone: str = typer.Option("UTC", "--timezone"),
    timeframe: str = typer.Option(..., "--timeframe"),
    source: str = typer.Option("csv", "--source"),
    timeframe_seconds: int | None = typer.Option(None, "--timeframe-seconds"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Import an OHLCV CSV file."""
    with SessionLocal() as session:
        result = persist_csv_import(
            session,
            path,
            CsvImportMetadata(
                symbol=symbol,
                instrument_name=name,
                asset_class=asset_class,
                exchange=exchange,
                currency=currency,
                timezone=timezone,
                timeframe=timeframe,
                source_name=source,
                timeframe_seconds=timeframe_seconds,
                dry_run=dry_run,
            ),
        )
        item = result.data_import
        typer.echo(
            f"import_id={item.id} status={item.status} rows_inserted={item.rows_inserted} "
            f"rows_skipped={item.rows_skipped}"
        )


@data_app.command("imports")
def data_imports(limit: int = 100, offset: int = 0) -> None:
    """List import records."""
    with SessionLocal() as session:
        rows = session.query(DataImport).order_by(DataImport.created_at.desc()).limit(limit).offset(offset)
        for item in rows:
            typer.echo(f"{item.id}\t{item.status}\t{item.rows_read}\t{item.source_hash}")


@data_app.command("import-report")
def data_import_report(import_id: str) -> None:
    """Show an import report."""
    with SessionLocal() as session:
        item = session.get(DataImport, import_id)
        if item is None:
            raise typer.Exit(1)
        typer.echo(
            f"id={item.id}\nstatus={item.status}\nrows_read={item.rows_read}\n"
            f"rows_valid={item.rows_valid}\nrows_inserted={item.rows_inserted}\n"
            f"warnings={item.warnings_count}\nerrors={item.errors_count}"
        )


@data_app.command("import-manifest")
def data_import_manifest(path: Path, dry_run: bool = typer.Option(False, "--dry-run")) -> None:
    """Dry-run or import every dataset in a real-data manifest."""
    manifest = load_data_manifest(path)
    with SessionLocal() as session:
        reports = import_manifest(session, manifest, dry_run=dry_run)
    for report in reports:
        typer.echo(
            f"{report.dataset_code}\t{report.quality_decision}\trows={report.rows_read} "
            f"accepted={report.rows_accepted} rejected={report.rows_rejected} import_id={report.import_id or ''}"
        )
    if not any(report.exists for report in reports):
        typer.echo("REAL_DATA_REQUIRED")


@data_app.command("quality-report")
def data_quality_report(
    manifest_code: str = typer.Option(..., "--manifest"),
    output: Path | None = QUALITY_REPORT_OUTPUT_OPTION,
) -> None:
    """Print persisted import quality rows for one manifest code."""
    with SessionLocal() as session:
        rows = quality_reports_for_manifest(session, manifest_code)
    if output:
        write_quality_csv(output, rows)
    typer.echo(json.dumps(rows, indent=2, sort_keys=True))


@data_app.command("providers")
def data_providers() -> None:
    """List historical data providers."""
    for provider in provider_catalog():
        typer.echo(
            f"{provider['code']}\t{provider['version']}\t{provider['classification']}\tclient={provider['client']}"
        )


@data_app.command("provider-show")
def data_provider_show(provider_code: str) -> None:
    """Show one historical data provider."""
    matches = [provider for provider in provider_catalog() if provider["code"] == provider_code]
    if not matches:
        raise typer.Exit(1)
    typer.echo(json.dumps(matches[0], indent=2, sort_keys=True))


@data_app.command("fetch-manifest")
def data_fetch_manifest(
    path: Path,
    symbol: str | None = typer.Option(None, "--symbol"),
    start: str | None = typer.Option(None, "--start"),
    end: str | None = typer.Option(None, "--end"),
    output_directory: Path | None = FETCH_OUTPUT_DIRECTORY_OPTION,
    delay_seconds: float | None = typer.Option(None, "--delay-seconds"),
    maximum_retries: int | None = typer.Option(None, "--maximum-retries"),
    new_version: str | None = typer.Option(None, "--new-version"),
    force_refresh: bool = typer.Option(False, "--force-refresh"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Fetch provider-backed datasets from a manifest."""
    manifest = load_provider_manifest(path)
    kwargs = {
        "symbol": symbol,
        "start": start,
        "end": end,
        "output_directory": output_directory,
        "delay_seconds": delay_seconds,
        "maximum_retries": maximum_retries,
        "new_version": new_version,
        "force_refresh": force_refresh,
    }
    result = acquisition_plan(manifest, **kwargs) if dry_run else fetch_manifest(manifest, **kwargs)
    typer.echo(json.dumps(result, indent=2, sort_keys=True, default=str))


@data_app.command("fetch-yahoo")
def data_fetch_yahoo(
    path: Path,
    symbol: str | None = typer.Option(None, "--symbol"),
    start: str | None = typer.Option(None, "--start"),
    end: str | None = typer.Option(None, "--end"),
    output_directory: Path | None = FETCH_OUTPUT_DIRECTORY_OPTION,
    delay_seconds: float | None = typer.Option(None, "--delay-seconds"),
    maximum_retries: int | None = typer.Option(None, "--maximum-retries"),
    new_version: str | None = typer.Option(None, "--new-version"),
    force_refresh: bool = typer.Option(False, "--force-refresh"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Fetch Yahoo Finance pilot datasets from a provider manifest."""
    data_fetch_manifest(
        path,
        symbol=symbol,
        start=start,
        end=end,
        output_directory=output_directory,
        delay_seconds=delay_seconds,
        maximum_retries=maximum_retries,
        new_version=new_version,
        force_refresh=force_refresh,
        dry_run=dry_run,
    )


@data_app.command("provider-smoke")
def data_provider_smoke(
    provider_code: str,
    symbol: str = typer.Option("SPY", "--symbol"),
    asset_class: str = typer.Option("equity_etf", "--asset-class"),
) -> None:
    """Run an explicit bounded provider smoke test without persisting data."""
    if provider_code == "yahoo_finance_v1":
        try:
            import yfinance as yf
            from market_genome_data_ingestion.providers.yahoo_finance import (
                canonicalize_yahoo_frame,
                dataframe_hash,
            )
        except ImportError:
            typer.echo(json.dumps({"provider": provider_code, "status": "YFINANCE_NOT_INSTALLED"}))
            raise typer.Exit(1) from None
        frame = yf.download(symbol, start="2024-01-01", end="2024-01-10", interval="1d", auto_adjust=True, actions=False, progress=False, threads=False)
        canonical = canonicalize_yahoo_frame(frame)
        typer.echo(
            json.dumps(
                {
                    "provider": provider_code,
                    "provider_reachable": not canonical.empty,
                    "rows_returned": len(canonical),
                    "date_range": [None if canonical.empty else canonical["timestamp"].iloc[0], None if canonical.empty else canonical["timestamp"].iloc[-1]],
                    "columns": list(canonical.columns),
                    "hash": dataframe_hash(frame) if not frame.empty else None,
                    "status": "COMPLETED" if not canonical.empty else "EMPTY_RESPONSE",
                },
                indent=2,
                sort_keys=True,
                default=str,
            )
        )
        return
    if provider_code == "alpha_vantage_v1":
        import tempfile

        from market_genome_data_ingestion.providers.base import HistoricalDataRequest

        provider = get_provider(provider_code)
        with tempfile.TemporaryDirectory() as tmp_dir:
            request = HistoricalDataRequest(
                provider_symbol=symbol,
                canonical_symbol=f"SMOKE_{symbol.replace('/', '_')}",
                instrument_name="smoke",
                asset_class=asset_class,
                exchange="SMOKE",
                currency="USD",
                timezone="UTC",
                timeframe="D1",
                start="2024-01-01",
                end="2024-01-10",
                auto_adjust=False,
                include_actions=False,
                volume_type="unavailable" if asset_class == "forex" else "unknown",
                price_adjustment_basis="provider_unadjusted_raw",
                output_directory=Path(tmp_dir),
                delay_seconds=0,
                maximum_retries=0,
            )
            try:
                result = provider.fetch(request)
                typer.echo(json.dumps({**result.as_dict(), "provider_reachable": True}, indent=2, sort_keys=True, default=str))
            except Exception as exc:  # noqa: BLE001
                typer.echo(
                    json.dumps(
                        {"provider": provider_code, "provider_reachable": False, "status": classify_provider_error(exc), "error": _redact_secrets(str(exc))},
                        indent=2, sort_keys=True,
                    )
                )
                raise typer.Exit(1) from None
        return
    raise typer.Exit(1)


@data_app.command("compare-providers")
def data_compare_providers(
    base_csv: Path,
    other_csv: Path,
    base_label: str = typer.Option(..., "--base-label"),
    other_label: str = typer.Option(..., "--other-label"),
    output: Path | None = COMPARE_PROVIDERS_OUTPUT_OPTION,
) -> None:
    """Descriptive cross-provider QA between two canonical OHLCV CSVs (not a model evaluation)."""
    result = compare_canonical_files(base_csv, other_csv, base_label=base_label, other_label=other_label)
    payload = json.dumps(result, indent=2, sort_keys=True, default=str)
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(payload, encoding="utf-8")
    typer.echo(payload)


@windows_app.command("build")
def windows_build(
    symbol: str = typer.Option(..., "--symbol"),
    timeframe: str = typer.Option(..., "--timeframe"),
    exchange: str | None = typer.Option(None, "--exchange"),
    lengths: str = typer.Option("8,16,32,64,128,256", "--lengths"),
    stride: int = typer.Option(1, "--stride"),
    mode: str = typer.Option("incremental", "--mode"),
    window_version: str = typer.Option("window_v1", "--window-version"),
) -> None:
    """Build pattern windows for an instrument/timeframe."""
    requested_lengths = [int(part.strip()) for part in lengths.split(",") if part.strip()]
    with SessionLocal() as session:
        registry = RegistryService(session)
        instrument = registry.get_instrument_by_symbol(symbol, exchange)
        timeframe_item = registry.get_timeframe_by_code(timeframe)
        if instrument is None or timeframe_item is None:
            raise typer.Exit(1)
        result = WindowBuildService(session).build(
            instrument_id=instrument.id,
            timeframe_id=timeframe_item.id,
            window_lengths=requested_lengths,
            stride=stride,
            mode=mode,
            window_version=window_version,
            quality_policy=WindowQualityPolicy(),
        )
        typer.echo(
            f"build_id={result.build.id} status={result.build.status} "
            f"created={result.created_windows} existing={result.existing_windows}"
        )


@windows_app.command("list")
def windows_list(limit: int = 100, offset: int = 0) -> None:
    """List pattern windows."""
    with SessionLocal() as session:
        rows = session.query(PatternWindow).order_by(PatternWindow.end_timestamp).limit(limit).offset(offset)
        for item in rows:
            typer.echo(f"{item.id}\t{item.window_length}\t{item.start_timestamp}\t{item.end_timestamp}")


@windows_app.command("inspect")
def windows_inspect(window_id: str) -> None:
    """Inspect one pattern window."""
    with SessionLocal() as session:
        item = session.get(PatternWindow, window_id)
        if item is None:
            raise typer.Exit(1)
        typer.echo(
            f"id={item.id}\nlength={item.window_length}\nstart={item.start_timestamp}\n"
            f"end={item.end_timestamp}\nsource_hash={item.source_data_hash}\nflags={item.quality_flags}"
        )


@windows_app.command("builds")
def windows_builds(limit: int = 100, offset: int = 0) -> None:
    """List window build records."""
    with SessionLocal() as session:
        rows = session.query(WindowBuild).order_by(WindowBuild.created_at.desc()).limit(limit).offset(offset)
        for item in rows:
            typer.echo(f"{item.id}\t{item.status}\t{item.created_window_count}\t{item.configuration_hash}")


@normalization_app.command("methods")
def normalization_methods() -> None:
    """List available normalization methods."""
    for method in list_methods():
        typer.echo(f"{method.code}\t{method.version}\t{','.join(method.channels)}\t{method.label}")


@normalization_app.command("build")
def normalization_build(
    method: str = typer.Option("anchored_log_return", "--method"),
    points: int = typer.Option(64, "--points"),
    resampling: str = typer.Option("linear", "--resampling"),
    mode: str = typer.Option("incremental", "--mode"),
    window_version: str = typer.Option("window_v1", "--window-version"),
    normalization_version: str = typer.Option("normalization_v1", "--normalization-version"),
    symbol: str | None = typer.Option(None, "--symbol"),
    exchange: str | None = typer.Option(None, "--exchange"),
    instrument_id: str | None = typer.Option(None, "--instrument-id"),
    timeframe: str | None = typer.Option(None, "--timeframe"),
    timeframe_id: str | None = typer.Option(None, "--timeframe-id"),
    window_length: int | None = typer.Option(None, "--window-length"),
) -> None:
    """Build normalized pattern representations."""
    with SessionLocal() as session:
        registry = RegistryService(session)
        resolved_instrument_id = instrument_id
        resolved_timeframe_id = timeframe_id
        if symbol:
            instrument = registry.get_instrument_by_symbol(symbol, exchange)
            if instrument is None:
                raise typer.Exit(1)
            resolved_instrument_id = instrument.id
        if timeframe:
            timeframe_item = registry.get_timeframe_by_code(timeframe)
            if timeframe_item is None:
                raise typer.Exit(1)
            resolved_timeframe_id = timeframe_item.id
        result = NormalizationBuildService(session).build(
            normalization_method=method,
            resample_points=points,
            resampling_method=resampling,
            instrument_id=resolved_instrument_id,
            timeframe_id=resolved_timeframe_id,
            window_length=window_length,
            mode=mode,
            normalization_version=normalization_version,
            source_window_version=window_version,
            policies=NormalizationPolicies(),
        )
        typer.echo(
            f"build_id={result.build.id} status={result.build.status} "
            f"created={result.created_representations} existing={result.existing_representations} "
            f"failed={result.failed_representations}"
        )


@normalization_app.command("builds")
def normalization_builds(limit: int = 100, offset: int = 0) -> None:
    """List normalization builds."""
    with SessionLocal() as session:
        rows = session.query(NormalizationBuild).order_by(NormalizationBuild.created_at.desc()).limit(limit).offset(offset)
        for item in rows:
            typer.echo(f"{item.id}\t{item.status}\t{item.normalization_method}\t{item.created_representation_count}")


@normalization_app.command("build-show")
def normalization_build_show(build_id: str) -> None:
    """Show a normalization build."""
    with SessionLocal() as session:
        item = session.get(NormalizationBuild, build_id)
        if item is None:
            raise typer.Exit(1)
        typer.echo(
            f"id={item.id}\nstatus={item.status}\nmethod={item.normalization_method}\n"
            f"created={item.created_representation_count}\nexisting={item.existing_representation_count}\n"
            f"failed={item.failed_representation_count}\nconfiguration_hash={item.configuration_hash}"
        )


@normalized_app.command("list")
def normalized_list(limit: int = 100, offset: int = 0) -> None:
    """List normalized patterns."""
    with SessionLocal() as session:
        rows = session.query(NormalizedPattern).order_by(NormalizedPattern.created_at).limit(limit).offset(offset)
        for item in rows:
            typer.echo(f"{item.id}\t{item.normalization_method}\t{item.resample_points}\t{item.representation_hash}")


@normalized_app.command("inspect")
def normalized_inspect(normalized_pattern_id: str) -> None:
    """Inspect one normalized pattern."""
    with SessionLocal() as session:
        item = session.get(NormalizedPattern, normalized_pattern_id)
        if item is None:
            raise typer.Exit(1)
        typer.echo(
            f"id={item.id}\nwindow={item.pattern_window_id}\nmethod={item.normalization_method}\n"
            f"points={item.resample_points}\nrepresentation_hash={item.representation_hash}\nflags={item.quality_flags}"
        )


@normalized_app.command("values")
def normalized_values(normalized_pattern_id: str) -> None:
    """Print normalized values for one pattern."""
    with SessionLocal() as session:
        item = session.get(NormalizedPattern, normalized_pattern_id)
        if item is None:
            raise typer.Exit(1)
        typer.echo(item.normalized_values)


@features_app.command("definitions")
def features_definitions() -> None:
    """List registered feature definitions."""
    for item in list_feature_definitions():
        typer.echo(f"{item.code}\t{item.version}\t{item.feature_group}\t{item.input_source}")


@features_app.command("sets")
def features_sets() -> None:
    """List feature sets."""
    for item in list_feature_sets():
        typer.echo(f"{item.code}\t{item.version}\tfeatures={len(item.ordered_feature_codes)}")


@features_app.command("set-show")
def features_set_show(feature_set_code: str = "market_dna_v1") -> None:
    """Show one feature set."""
    try:
        item = get_feature_set(feature_set_code)
    except ValueError:
        raise typer.Exit(1) from None
    typer.echo(
        f"code={item.code}\nversion={item.version}\nfeatures={len(item.ordered_feature_codes)}\n"
        f"normalization={item.required_normalization_method}/{item.required_normalization_version}\n"
        f"resampling={item.required_resampling_method}:{item.required_resample_points}\n"
        f"ordered_features={','.join(item.ordered_feature_codes)}"
    )


@features_app.command("build")
def features_build(
    feature_set_code: str = typer.Option("market_dna_v1", "--feature-set"),
    mode: str = typer.Option("incremental", "--mode"),
    symbol: str | None = typer.Option(None, "--symbol"),
    exchange: str | None = typer.Option(None, "--exchange"),
    instrument_id: str | None = typer.Option(None, "--instrument-id"),
    timeframe: str | None = typer.Option(None, "--timeframe"),
    timeframe_id: str | None = typer.Option(None, "--timeframe-id"),
    window_length: int | None = typer.Option(None, "--window-length"),
) -> None:
    """Build Market DNA features from normalized patterns."""
    with SessionLocal() as session:
        registry = RegistryService(session)
        resolved_instrument_id = instrument_id
        resolved_timeframe_id = timeframe_id
        if symbol:
            instrument = registry.get_instrument_by_symbol(symbol, exchange)
            if instrument is None:
                raise typer.Exit(1)
            resolved_instrument_id = instrument.id
        if timeframe:
            timeframe_item = registry.get_timeframe_by_code(timeframe)
            if timeframe_item is None:
                raise typer.Exit(1)
            resolved_timeframe_id = timeframe_item.id
        result = FeatureBuildService(session).build(
            feature_set_code=feature_set_code,
            mode=mode,
            instrument_id=resolved_instrument_id,
            timeframe_id=resolved_timeframe_id,
            window_length=window_length,
        )
        typer.echo(
            f"build_id={result.build.id} status={result.build.status} "
            f"created={result.created_features} existing={result.existing_features} failed={result.failed_features}"
        )


@features_app.command("builds")
def features_builds(limit: int = 100, offset: int = 0) -> None:
    """List feature builds."""
    with SessionLocal() as session:
        rows = session.query(FeatureBuild).order_by(FeatureBuild.created_at.desc()).limit(limit).offset(offset)
        for item in rows:
            typer.echo(f"{item.id}\t{item.status}\t{item.feature_set_code}\t{item.created_feature_count}")


@features_app.command("build-show")
def features_build_show(build_id: str) -> None:
    """Show one feature build."""
    with SessionLocal() as session:
        item = session.get(FeatureBuild, build_id)
        if item is None:
            raise typer.Exit(1)
        typer.echo(
            f"id={item.id}\nstatus={item.status}\nfeature_set={item.feature_set_code}\n"
            f"created={item.created_feature_count}\nexisting={item.existing_feature_count}\n"
            f"failed={item.failed_feature_count}\nconfiguration_hash={item.configuration_hash}"
        )


@dna_app.command("list")
def dna_list(limit: int = 100, offset: int = 0) -> None:
    """List Market DNA rows."""
    with SessionLocal() as session:
        rows = session.query(MarketDNA).order_by(MarketDNA.created_at).limit(limit).offset(offset)
        for item in rows:
            typer.echo(
                f"{item.id}\t{item.feature_set_code}\tavailable={item.available_feature_count}/"
                f"{item.feature_count}\t{item.feature_vector_hash}"
            )


@dna_app.command("inspect")
def dna_inspect(market_dna_id: str) -> None:
    """Inspect one Market DNA row."""
    with SessionLocal() as session:
        item = session.get(MarketDNA, market_dna_id)
        if item is None:
            raise typer.Exit(1)
        typer.echo(
            f"id={item.id}\nwindow={item.pattern_window_id}\nnormalized={item.normalized_pattern_id}\n"
            f"feature_set={item.feature_set_code}/{item.feature_set_version}\n"
            f"available={item.available_feature_count}/{item.feature_count}\n"
            f"vector_hash={item.feature_vector_hash}\nflags={item.quality_flags}"
        )


@dna_app.command("values")
def dna_values(market_dna_id: str) -> None:
    """Print Market DNA feature values."""
    with SessionLocal() as session:
        item = session.get(MarketDNA, market_dna_id)
        if item is None:
            raise typer.Exit(1)
        typer.echo(item.feature_values)


@dna_app.command("diagnostics")
def dna_diagnostics(market_dna_id: str) -> None:
    """Print Market DNA diagnostics."""
    with SessionLocal() as session:
        item = session.get(MarketDNA, market_dna_id)
        if item is None:
            raise typer.Exit(1)
        typer.echo(item.diagnostics)


@context_app.command("producers")
def context_producers() -> None:
    """List context producers."""
    for item in list_context_producers():
        typer.echo(f"{item.code}\t{item.version}\tdimensions={len(item.dimensions)}")


@context_app.command("dimensions")
def context_dimensions() -> None:
    """List context dimensions."""
    for item in list_context_dimensions():
        typer.echo(f"{item['code']}\t{item['version']}\t{','.join(item['states'])}")


@context_app.command("build")
def context_build(
    producer: str = typer.Option("transparent_context_v1", "--producer"),
    feature_set: str = typer.Option("market_dna_v1", "--feature-set"),
    mode: str = typer.Option("incremental", "--mode"),
    symbol: str | None = typer.Option(None, "--symbol"),
    exchange: str | None = typer.Option(None, "--exchange"),
    instrument_id: str | None = typer.Option(None, "--instrument-id"),
    timeframe: str | None = typer.Option(None, "--timeframe"),
    timeframe_id: str | None = typer.Option(None, "--timeframe-id"),
    window_length: int | None = typer.Option(None, "--window-length"),
) -> None:
    """Build Market Context records."""
    with SessionLocal() as session:
        registry = RegistryService(session)
        resolved_instrument_id = instrument_id
        resolved_timeframe_id = timeframe_id
        if symbol:
            instrument = registry.get_instrument_by_symbol(symbol, exchange)
            if instrument is None:
                raise typer.Exit(1)
            resolved_instrument_id = instrument.id
        if timeframe:
            timeframe_item = registry.get_timeframe_by_code(timeframe)
            if timeframe_item is None:
                raise typer.Exit(1)
            resolved_timeframe_id = timeframe_item.id
        result = ContextBuildService(session).build(
            context_producer_code=producer,
            feature_set_code=feature_set,
            mode=mode,
            instrument_id=resolved_instrument_id,
            timeframe_id=resolved_timeframe_id,
            window_length=window_length,
        )
        typer.echo(
            f"build_id={result.build.id} status={result.build.status} created={result.created_contexts} "
            f"existing={result.existing_contexts} partial={result.partial_contexts} failed={result.failed_contexts}"
        )


@context_app.command("builds")
def context_builds(limit: int = 100, offset: int = 0) -> None:
    """List context builds."""
    with SessionLocal() as session:
        rows = session.query(ContextBuild).order_by(ContextBuild.created_at.desc()).limit(limit).offset(offset)
        for item in rows:
            typer.echo(f"{item.id}\t{item.status}\t{item.context_producer_code}\t{item.created_context_count}")


@context_app.command("build-show")
def context_build_show(build_id: str) -> None:
    """Show one context build."""
    with SessionLocal() as session:
        item = session.get(ContextBuild, build_id)
        if item is None:
            raise typer.Exit(1)
        typer.echo(
            f"id={item.id}\nstatus={item.status}\nproducer={item.context_producer_code}\n"
            f"created={item.created_context_count}\nexisting={item.existing_context_count}\n"
            f"partial={item.partial_context_count}\nfailed={item.failed_context_count}\nconfiguration_hash={item.configuration_hash}"
        )


@contexts_app.command("list")
def contexts_list(
    limit: int = 100,
    offset: int = 0,
    trend_state: str | None = typer.Option(None, "--trend-state"),
    volatility_state: str | None = typer.Option(None, "--volatility-state"),
    market_phase: str | None = typer.Option(None, "--market-phase"),
    minimum_confidence: float | None = typer.Option(None, "--minimum-confidence"),
) -> None:
    """List Market Context rows."""
    with SessionLocal() as session:
        query = session.query(MarketContext).order_by(MarketContext.created_at).limit(limit).offset(offset)
        if trend_state:
            query = query.filter(MarketContext.trend_state == trend_state)
        if volatility_state:
            query = query.filter(MarketContext.volatility_state == volatility_state)
        if market_phase:
            query = query.filter(MarketContext.market_phase_state == market_phase)
        if minimum_confidence is not None:
            query = query.filter(MarketContext.composite_confidence >= minimum_confidence)
        for item in query:
            typer.echo(
                f"{item.id}\t{item.context_family_code}\tconfidence={float(item.composite_confidence):.3f}\t"
                f"complete={float(item.completeness_score):.3f}\t{item.composite_context_code}"
            )


@contexts_app.command("inspect")
def contexts_inspect(market_context_id: str) -> None:
    """Inspect one Market Context row."""
    with SessionLocal() as session:
        item = session.get(MarketContext, market_context_id)
        if item is None:
            raise typer.Exit(1)
        typer.echo(
            f"id={item.id}\nproducer={item.context_producer_code}/{item.context_producer_version}\n"
            f"family={item.context_family_code}\ncomposite={item.composite_context_code}\n"
            f"confidence={float(item.composite_confidence):.3f}\ncompleteness={float(item.completeness_score):.3f}\n"
            f"hash={item.context_hash}\nflags={item.quality_flags}"
        )


@contexts_app.command("dimensions")
def contexts_dimensions(market_context_id: str) -> None:
    """Print context dimensions."""
    with SessionLocal() as session:
        item = session.get(MarketContext, market_context_id)
        if item is None:
            raise typer.Exit(1)
        typer.echo(
            {
                "trend": item.trend_state,
                "volatility": item.volatility_state,
                "volatility_phase": item.volatility_phase_state,
                "persistence": item.persistence_state,
                "activity": item.activity_state,
                "shock": item.shock_state,
                "market_phase": item.market_phase_state,
                "multi_resolution": item.multi_resolution_state,
            }
        )


@contexts_app.command("explain")
def contexts_explain(market_context_id: str) -> None:
    """Print context evidence and opposing evidence."""
    with SessionLocal() as session:
        item = session.get(MarketContext, market_context_id)
        if item is None:
            raise typer.Exit(1)
        typer.echo({"evidence": item.evidence, "opposing_evidence": item.opposing_evidence})


@contexts_app.command("diagnostics")
def contexts_diagnostics(market_context_id: str) -> None:
    """Print context diagnostics."""
    with SessionLocal() as session:
        item = session.get(MarketContext, market_context_id)
        if item is None:
            raise typer.Exit(1)
        typer.echo(item.diagnostics)


@contexts_app.command("multi-resolution")
def contexts_multi_resolution(market_context_id: str) -> None:
    """Print multi-resolution links."""
    with SessionLocal() as session:
        item = session.get(MarketContext, market_context_id)
        if item is None:
            raise typer.Exit(1)
        typer.echo(item.multi_resolution_links)


@windows_app.command("outcomes")
def windows_outcomes(window_id: str, limit: int = 100, offset: int = 0) -> None:
    """List forward outcomes attached to a pattern window."""
    with SessionLocal() as session:
        rows = (
            session.query(OutcomeObservation)
            .filter(OutcomeObservation.pattern_window_id == window_id)
            .order_by(OutcomeObservation.horizon_bars, OutcomeObservation.created_at)
            .limit(limit)
            .offset(offset)
        )
        for item in rows:
            typer.echo(
                f"{item.id}\th={item.horizon_bars}\tcomplete={item.is_complete}\t"
                f"ret={item.future_simple_return}\t{item.direction_class}"
            )


@outcomes_app.command("definitions")
def outcomes_definitions() -> None:
    """List registered forward outcome definitions."""
    for item in list_outcome_definitions():
        typer.echo(f"{item.code}\t{item.version}\t{item.units}\tpartial={item.supports_partial}")


@outcomes_app.command("sets")
def outcomes_sets() -> None:
    """List registered forward outcome sets."""
    for item in list_outcome_sets():
        typer.echo(f"{item.code}\t{item.version}\thorizons={','.join(str(h) for h in item.default_horizons)}")


@outcomes_app.command("set-show")
def outcomes_set_show(outcome_set_code: str = "forward_outcomes_v1") -> None:
    """Show one forward outcome set."""
    try:
        item = get_outcome_set(outcome_set_code)
    except ValueError:
        raise typer.Exit(1) from None
    typer.echo(
        f"code={item.code}\nversion={item.version}\nanchor={item.anchor_method}\n"
        f"path={item.forward_path_method}\nhorizons={','.join(str(h) for h in item.default_horizons)}\n"
        f"definitions={','.join(item.ordered_outcome_definitions)}"
    )


@outcomes_app.command("build")
def outcomes_build(
    outcome_set: str = typer.Option("forward_outcomes_v1", "--outcome-set"),
    horizons: str | None = typer.Option(None, "--horizons"),
    mode: str = typer.Option("incremental", "--mode"),
    symbol: str | None = typer.Option(None, "--symbol"),
    exchange: str | None = typer.Option(None, "--exchange"),
    instrument_id: str | None = typer.Option(None, "--instrument-id"),
    timeframe: str | None = typer.Option(None, "--timeframe"),
    timeframe_id: str | None = typer.Option(None, "--timeframe-id"),
    window_length: int | None = typer.Option(None, "--window-length"),
) -> None:
    """Build forward outcomes from immutable pattern windows."""
    requested_horizons = None
    if horizons:
        requested_horizons = [int(part.strip()) for part in horizons.split(",") if part.strip()]
    with SessionLocal() as session:
        registry = RegistryService(session)
        resolved_instrument_id = instrument_id
        resolved_timeframe_id = timeframe_id
        if symbol:
            instrument = registry.get_instrument_by_symbol(symbol, exchange)
            if instrument is None:
                raise typer.Exit(1)
            resolved_instrument_id = instrument.id
        if timeframe:
            timeframe_item = registry.get_timeframe_by_code(timeframe)
            if timeframe_item is None:
                raise typer.Exit(1)
            resolved_timeframe_id = timeframe_item.id
        result = OutcomeBuildService(session).build(
            outcome_set_code=outcome_set,
            horizons=requested_horizons,
            mode=mode,
            instrument_id=resolved_instrument_id,
            timeframe_id=resolved_timeframe_id,
            window_length=window_length,
        )
        typer.echo(
            f"build_id={result.build.id} status={result.build.status} "
            f"created={result.created_observations} existing={result.existing_observations} "
            f"partial={result.partial_observations} failed={result.failed_observations}"
        )


@outcomes_app.command("builds")
def outcomes_builds(limit: int = 100, offset: int = 0) -> None:
    """List outcome build records."""
    with SessionLocal() as session:
        rows = session.query(OutcomeBuild).order_by(OutcomeBuild.created_at.desc()).limit(limit).offset(offset)
        for item in rows:
            typer.echo(f"{item.id}\t{item.status}\t{item.outcome_set_code}\t{item.created_observation_count}")


@outcomes_app.command("build-show")
def outcomes_build_show(build_id: str) -> None:
    """Show one outcome build."""
    with SessionLocal() as session:
        item = session.get(OutcomeBuild, build_id)
        if item is None:
            raise typer.Exit(1)
        typer.echo(
            f"id={item.id}\nstatus={item.status}\noutcome_set={item.outcome_set_code}/{item.outcome_set_version}\n"
            f"created={item.created_observation_count}\nexisting={item.existing_observation_count}\n"
            f"partial={item.partial_observation_count}\nfailed={item.failed_observation_count}\n"
            f"configuration_hash={item.configuration_hash}"
        )


@outcome_app.command("list")
def outcome_list(
    limit: int = 100,
    offset: int = 0,
    horizon: int | None = typer.Option(None, "--horizon"),
    complete: bool | None = typer.Option(None, "--complete"),
    direction: str | None = typer.Option(None, "--direction"),
) -> None:
    """List forward outcome observations."""
    with SessionLocal() as session:
        query = session.query(OutcomeObservation).order_by(OutcomeObservation.window_end_timestamp)
        if horizon is not None:
            query = query.filter(OutcomeObservation.horizon_bars == horizon)
        if complete is not None:
            query = query.filter(OutcomeObservation.is_complete == complete)
        if direction:
            query = query.filter(OutcomeObservation.direction_class == direction)
        for item in query.limit(limit).offset(offset):
            typer.echo(
                f"{item.id}\th={item.horizon_bars}\tcomplete={item.is_complete}\t"
                f"ret={item.future_simple_return}\t{item.direction_class}\twindow={item.pattern_window_id}"
            )


@outcome_app.command("inspect")
def outcome_inspect(outcome_id: str) -> None:
    """Inspect one outcome observation."""
    with SessionLocal() as session:
        item = session.get(OutcomeObservation, outcome_id)
        if item is None:
            raise typer.Exit(1)
        typer.echo(
            f"id={item.id}\nwindow={item.pattern_window_id}\nhorizon={item.horizon_bars}\n"
            f"complete={item.is_complete}\navailable_future_bars={item.available_future_bars}\n"
            f"return={item.future_simple_return}\ndirection={item.direction_class}\n"
            f"continuation_reversal={item.continuation_reversal_class}\nhash={item.outcome_hash}\n"
            f"flags={item.quality_flags}"
        )


@outcome_app.command("values")
def outcome_values(outcome_id: str) -> None:
    """Print scalar outcome values."""
    with SessionLocal() as session:
        item = session.get(OutcomeObservation, outcome_id)
        if item is None:
            raise typer.Exit(1)
        typer.echo(item.scalar_values)


@outcome_app.command("path")
def outcome_path(outcome_id: str) -> None:
    """Print normalized forward path."""
    with SessionLocal() as session:
        item = session.get(OutcomeObservation, outcome_id)
        if item is None:
            raise typer.Exit(1)
        typer.echo(item.forward_path)


@outcome_app.command("barriers")
def outcome_barriers(outcome_id: str) -> None:
    """Print barrier outcomes."""
    with SessionLocal() as session:
        item = session.get(OutcomeObservation, outcome_id)
        if item is None:
            raise typer.Exit(1)
        typer.echo(item.barrier_results)


@outcome_app.command("diagnostics")
def outcome_diagnostics(outcome_id: str) -> None:
    """Print outcome diagnostics."""
    with SessionLocal() as session:
        item = session.get(OutcomeObservation, outcome_id)
        if item is None:
            raise typer.Exit(1)
        typer.echo(item.diagnostics)


@similarity_app.command("methods")
def similarity_methods() -> None:
    """List registered similarity methods."""
    for item in list_similarity_methods():
        typer.echo(f"{item.code}\t{item.version}\tuses_future_outcomes={item.uses_future_outcomes}")


@similarity_app.command("method-show")
def similarity_method_show(method_code: str = "market_analogue_v1") -> None:
    """Show one similarity method."""
    try:
        item = get_similarity_method(method_code)
    except ValueError:
        raise typer.Exit(1) from None
    typer.echo(
        f"code={item.code}\nversion={item.version}\ninputs={','.join(item.input_sources)}\n"
        f"uses_future_outcomes={item.uses_future_outcomes}\nconfiguration={item.default_configuration}"
    )


@similarity_app.command("search")
def similarity_search(
    query_window_id: str,
    method: str = typer.Option("market_analogue_v1", "--method"),
    top_k: int = typer.Option(20, "--top-k"),
    instrument_id: str | None = typer.Option(None, "--instrument-id"),
    timeframe_id: str | None = typer.Option(None, "--timeframe-id"),
    window_length: int | None = typer.Option(None, "--window-length"),
    temporal_policy: str = typer.Option("historical_only", "--temporal-policy"),
    include_self: bool = typer.Option(False, "--include-self"),
) -> None:
    """Run and persist a historical analogue search for a window."""
    with SessionLocal() as session:
        result = SimilaritySearchService(session).search(
            query_window_id=query_window_id,
            similarity_method_code=method,
            top_k=top_k,
            instrument_id=instrument_id,
            timeframe_id=timeframe_id,
            window_length=window_length,
            temporal_policy=temporal_policy,
            include_self=include_self,
        )
        typer.echo(
            f"query_id={result.query.id} status={result.query.status} candidates={result.candidate_count} "
            f"matches={result.returned_match_count}"
        )


@similarity_app.command("queries")
def similarity_queries(limit: int = 100, offset: int = 0) -> None:
    """List similarity query records."""
    with SessionLocal() as session:
        rows = session.query(SimilarityQuery).order_by(SimilarityQuery.created_at.desc()).limit(limit).offset(offset)
        for item in rows:
            typer.echo(
                f"{item.id}\t{item.status}\t{item.similarity_method_code}\t"
                f"candidates={item.candidate_count}\tmatches={item.returned_match_count}"
            )


@similarity_app.command("query-show")
def similarity_query_show(query_id: str) -> None:
    """Show one similarity query."""
    with SessionLocal() as session:
        item = session.get(SimilarityQuery, query_id)
        if item is None:
            raise typer.Exit(1)
        typer.echo(
            f"id={item.id}\nwindow={item.query_window_id}\nmethod={item.similarity_method_code}\n"
            f"status={item.status}\ncandidates={item.candidate_count}\nmatches={item.returned_match_count}\n"
            f"query_hash={item.query_hash}\nconfiguration_hash={item.configuration_hash}"
        )


@similarity_app.command("matches")
def similarity_matches(query_id: str, limit: int = 100, offset: int = 0) -> None:
    """List matches for a similarity query."""
    with SessionLocal() as session:
        rows = (
            session.query(SimilarityMatch)
            .filter(SimilarityMatch.query_id == query_id)
            .order_by(SimilarityMatch.rank)
            .limit(limit)
            .offset(offset)
        )
        for item in rows:
            typer.echo(
                f"{item.rank}\t{item.candidate_window_id}\tdistance={float(item.distance):.6f}\t"
                f"score={float(item.similarity_score):.6f}"
            )


@validation_app.command("methods")
def validation_methods() -> None:
    """List validation methods."""
    for item in list_validation_methods():
        typer.echo(f"{item.code}\t{item.version}\tpurge={item.supports_purge}\tembargo={item.supports_embargo}")


@validation_app.command("baselines")
def validation_baselines() -> None:
    """List validation baselines."""
    for item in list_baseline_methods():
        typer.echo(f"{item.code}\t{item.version}\t{item.sampling_method}")


@validation_app.command("metrics")
def validation_metrics() -> None:
    """List validation metrics."""
    for item in list_metric_definitions():
        typer.echo(f"{item.code}\t{item.version}\t{item.metric_family}\thigher_is_better={item.higher_is_better}")


@validation_app.command("weighting")
def validation_weighting() -> None:
    """List analogue weighting methods."""
    for item in list_weighting_methods():
        typer.echo(f"{item.code}\t{item.version}\t{item.label}")


@experiments_app.command("definitions")
def experiments_definitions() -> None:
    """List experiment definitions."""
    for item in list_experiment_definitions():
        typer.echo(f"{item.code}\t{item.version}\twalk_forward_safe={item.walk_forward_safe}")


@experiments_app.command("create")
def experiments_create(path: Path) -> None:
    """Create and run an experiment from a JSON-compatible configuration file."""
    with SessionLocal() as session:
        result = ValidationExperimentService(session).run(load_experiment_config(path))
        typer.echo(
            f"experiment_id={result.run.id} status={result.run.status} decision={result.decision} "
            f"folds={result.folds} evaluations={result.query_evaluations} metrics={result.metric_records}"
        )


@experiments_app.command("list")
def experiments_list(limit: int = 100, offset: int = 0) -> None:
    """List experiment runs."""
    with SessionLocal() as session:
        rows = session.query(ExperimentRun).order_by(ExperimentRun.created_at.desc()).limit(limit).offset(offset)
        for item in rows:
            typer.echo(f"{item.id}\t{item.status}\t{item.decision or ''}\t{item.experiment_code}\t{item.name}")


@experiments_app.command("inspect")
def experiments_inspect(experiment_id: str) -> None:
    """Inspect one experiment run."""
    with SessionLocal() as session:
        item = session.get(ExperimentRun, experiment_id)
        if item is None:
            raise typer.Exit(1)
        typer.echo(
            f"id={item.id}\nstatus={item.status}\ndecision={item.decision}\n"
            f"dataset_hash={item.dataset_hash}\nconfiguration_hash={item.configuration_hash}\nsummary={item.summary}"
        )


@experiments_app.command("metrics")
def experiments_metrics(experiment_id: str) -> None:
    """List experiment metrics."""
    with SessionLocal() as session:
        rows = session.query(ExperimentMetric).filter(ExperimentMetric.experiment_run_id == experiment_id).order_by(ExperimentMetric.metric_code)
        for item in rows:
            method = item.similarity_method or item.baseline_method or "all"
            typer.echo(f"{item.metric_code}\th={item.horizon_bars}\t{method}\tvalue={item.value}\tn={item.sample_count}")


@experiments_app.command("compare")
def experiments_compare(experiment_id: str) -> None:
    """Print a compact baseline comparison."""
    with SessionLocal() as session:
        rows = session.query(ExperimentMetric).filter(ExperimentMetric.experiment_run_id == experiment_id, ExperimentMetric.metric_code == "brier_score")
        for item in rows:
            method = item.similarity_method or item.baseline_method or "all"
            typer.echo(f"{method}\th={item.horizon_bars}\tbrier={item.value}\tci=({item.confidence_interval_low},{item.confidence_interval_high})")


@experiments_app.command("report")
def experiments_report(experiment_id: str) -> None:
    """Print a Markdown experiment report."""
    with SessionLocal() as session:
        typer.echo(ValidationExperimentService(session).generate_report(experiment_id))


@diagnostics_app.command("definitions")
def diagnostics_definitions() -> None:
    """List diagnostic experiment definitions."""
    for item in list_diagnostic_definitions():
        typer.echo(f"{item.code}\t{item.version}\t{item.status}\tuses_future_outcomes={item.uses_future_outcomes}")


@diagnostics_app.command("scaling-methods")
def diagnostics_scaling_methods() -> None:
    """List diagnostic scaling methods."""
    for item in list_scaling_methods():
        typer.echo(f"{item.code}\t{item.version}\thistorical_as_of_safe={item.historical_as_of_safe}")


@diagnostics_app.command("availability-policies")
def diagnostics_availability_policies() -> None:
    """List availability-aware distance policies."""
    for item in list_availability_policies():
        typer.echo(f"{item.code}\t{item.version}\trejects={item.rejects_low_coverage}\tpenalty={item.applies_penalty}")


@diagnostics_app.command("weights")
def diagnostics_weights() -> None:
    """List bounded diagnostic weight configurations."""
    for item in list_weight_configurations():
        typer.echo(f"{item.code}\t{item.version}\t{item.weights}")


@diagnostics_app.command("run")
def diagnostics_run(path: Path) -> None:
    """Run a retrieval diagnostic from a JSON-compatible configuration file."""
    with SessionLocal() as session:
        run = RetrievalDiagnosticService(session).run(load_diagnostic_config(path))
        typer.echo(f"experiment_id={run.id} status={run.status} decision={run.decision} summary={run.summary}")


@diagnostics_app.command("list")
def diagnostics_list(limit: int = 100, offset: int = 0) -> None:
    """List diagnostic experiment runs."""
    with SessionLocal() as session:
        rows = (
            session.query(ExperimentRun)
            .filter(ExperimentRun.experiment_version == "diagnostic_v1")
            .order_by(ExperimentRun.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        for item in rows:
            typer.echo(f"{item.id}\t{item.status}\t{item.decision or ''}\t{item.experiment_code}\t{item.name}")


@diagnostics_app.command("inspect")
def diagnostics_inspect(experiment_id: str) -> None:
    """Inspect one diagnostic experiment."""
    with SessionLocal() as session:
        item = session.get(ExperimentRun, experiment_id)
        if item is None:
            raise typer.Exit(1)
        typer.echo(f"id={item.id}\nstatus={item.status}\ndecision={item.decision}\nsummary={item.summary}")


def _diagnostic_payload(experiment_id: str, artifact_type: str) -> None:
    with SessionLocal() as session:
        item = (
            session.query(DiagnosticArtifact)
            .filter(DiagnosticArtifact.experiment_run_id == experiment_id, DiagnosticArtifact.artifact_type == artifact_type)
            .order_by(DiagnosticArtifact.created_at.desc())
            .first()
        )
        if item is None:
            raise typer.Exit(1)
        typer.echo(item.payload)


@diagnostics_app.command("feature-distributions")
def diagnostics_feature_distributions(experiment_id: str) -> None:
    """Print feature distribution diagnostics."""
    _diagnostic_payload(experiment_id, "FEATURE_DISTRIBUTION")


@diagnostics_app.command("redundancy")
def diagnostics_redundancy(experiment_id: str) -> None:
    """Print redundancy diagnostics."""
    _diagnostic_payload(experiment_id, "CORRELATION_MATRIX")


@diagnostics_app.command("distance-outcome")
def diagnostics_distance_outcome(experiment_id: str) -> None:
    """Print distance/outcome diagnostics."""
    _diagnostic_payload(experiment_id, "DISTANCE_OUTCOME_CURVE")


@diagnostics_app.command("deciles")
def diagnostics_deciles(experiment_id: str) -> None:
    """Print similarity-decile diagnostics."""
    _diagnostic_payload(experiment_id, "DISTANCE_OUTCOME_CURVE")


@diagnostics_app.command("dispersion")
def diagnostics_dispersion(experiment_id: str) -> None:
    """Print neighbour-dispersion diagnostics."""
    _diagnostic_payload(experiment_id, "DISTANCE_OUTCOME_CURVE")


@diagnostics_app.command("episodes")
def diagnostics_episodes(experiment_id: str) -> None:
    """Print episode concentration diagnostics."""
    _diagnostic_payload(experiment_id, "EPISODE_CONCENTRATION")


@diagnostics_app.command("context")
def diagnostics_context(experiment_id: str) -> None:
    """Print context compatibility diagnostics."""
    _diagnostic_payload(experiment_id, "EPISODE_CONCENTRATION")


@diagnostics_app.command("window-horizon")
def diagnostics_window_horizon(experiment_id: str) -> None:
    """Print window/horizon alignment matrix."""
    _diagnostic_payload(experiment_id, "WINDOW_HORIZON_MATRIX")


@diagnostics_app.command("report")
def diagnostics_report(experiment_id: str) -> None:
    """Print a Markdown diagnostic report."""
    with SessionLocal() as session:
        item = (
            session.query(DiagnosticArtifact)
            .filter(DiagnosticArtifact.experiment_run_id == experiment_id, DiagnosticArtifact.artifact_type == "DIAGNOSTIC_REPORT")
            .order_by(DiagnosticArtifact.created_at.desc())
            .first()
        )
        if item is None:
            raise typer.Exit(1)
        typer.echo(item.payload["report"])


@studies_app.command("definitions")
def studies_definitions() -> None:
    """List study definitions."""
    for item in list_study_definitions():
        typer.echo(f"{item.code}\t{item.version}\tfinal_lock={item.final_test_lock_required}")


@studies_app.command("create")
def studies_create(path: Path) -> None:
    """Create a multi-asset diagnostic study manifest."""
    with SessionLocal() as session:
        study = MultiAssetStudyService(session).create(load_study_config(path))
        typer.echo(f"study_id={study.id} status={study.status} decision={study.decision}")


@studies_app.command("list")
def studies_list(limit: int = 100, offset: int = 0) -> None:
    """List study manifests."""
    with SessionLocal() as session:
        rows = session.query(StudyManifest).order_by(StudyManifest.created_at.desc()).limit(limit).offset(offset)
        for item in rows:
            typer.echo(f"{item.id}\t{item.status}\t{item.decision or ''}\t{item.study_code}\t{item.name}")


@studies_app.command("inspect")
def studies_inspect(study_id: str) -> None:
    """Inspect one study manifest."""
    with SessionLocal() as session:
        item = session.get(StudyManifest, study_id)
        if item is None:
            raise typer.Exit(1)
        typer.echo(
            f"id={item.id}\nstatus={item.status}\ndecision={item.decision}\n"
            f"dataset_hash={item.dataset_hash}\nconfiguration_hash={item.configuration_hash}\n"
            f"final_test_lock_hash={item.final_test_lock_hash}\nrationale={item.decision_rationale}"
        )


@studies_app.command("datasets")
def studies_datasets(study_id: str) -> None:
    """List study dataset entries."""
    with SessionLocal() as session:
        rows = session.query(StudyDatasetEntry).filter(StudyDatasetEntry.study_id == study_id)
        for item in rows:
            typer.echo(f"{item.instrument_id}\t{item.timeframe_id}\tbars={item.bar_count}\twindows={item.window_count}\tepisodes={item.episode_count}\t{item.inclusion_status}")


@studies_app.command("preflight")
def studies_preflight(study_id: str) -> None:
    """List study preflight gates."""
    with SessionLocal() as session:
        MultiAssetStudyService(session).preflight(study_id)
        rows = session.query(StudyPreflight).filter(StudyPreflight.study_id == study_id)
        for item in rows:
            typer.echo(f"{item.gate_code}\t{item.status}\tactual={item.actual_value}\trequired={item.required_value}")


@studies_app.command("episodes")
def studies_episodes(study_id: str, limit: int = 100) -> None:
    """List study episodes."""
    with SessionLocal() as session:
        rows = session.query(StudyEpisode).filter(StudyEpisode.study_id == study_id).order_by(StudyEpisode.episode_start).limit(limit)
        for item in rows:
            typer.echo(f"{item.episode_id}\t{item.instrument_id}\t{item.timeframe_id}\twindows={item.window_count}")


@studies_app.command("run-pilot")
def studies_run_pilot(study_id: str) -> None:
    """Run development/pilot study arms."""
    with SessionLocal() as session:
        study = MultiAssetStudyService(session).run_pilot(study_id)
        typer.echo(f"study_id={study.id} status={study.status} decision={study.decision}")


@studies_app.command("run-validation")
def studies_run_validation(study_id: str) -> None:
    """Run validation-period study arms if preflight permits."""
    with SessionLocal() as session:
        study = MultiAssetStudyService(session).run_validation(study_id)
        typer.echo(f"study_id={study.id} status={study.status} decision={study.decision}")


@studies_app.command("lock-final-test")
def studies_lock_final_test(study_id: str) -> None:
    """Persist an immutable final-test lock for the study."""
    with SessionLocal() as session:
        study = MultiAssetStudyService(session).lock_final_test(study_id)
        typer.echo(f"study_id={study.id} status={study.status} final_test_lock_hash={study.final_test_lock_hash}")


@studies_app.command("run-final-test")
def studies_run_final_test(study_id: str) -> None:
    """Run final-test study arms only after a final-test lock exists."""
    with SessionLocal() as session:
        study = MultiAssetStudyService(session).run_final_test(study_id)
        typer.echo(f"study_id={study.id} status={study.status} decision={study.decision}")


@studies_app.command("metrics")
def studies_metrics(study_id: str) -> None:
    """List study arm metrics."""
    with SessionLocal() as session:
        rows = session.query(StudyArm).filter(StudyArm.study_id == study_id)
        for item in rows:
            typer.echo(f"{item.period_role}\t{item.arm_code}\tcap={item.episode_cap}\t{item.metrics}")


@studies_app.command("segments")
def studies_segments(study_id: str) -> None:
    """List study arm segments."""
    with SessionLocal() as session:
        rows = session.query(StudyArm).filter(StudyArm.study_id == study_id)
        for item in rows:
            typer.echo(f"{item.period_role}\t{item.arm_code}\t{item.segments}")


@studies_app.command("episode-diversity")
def studies_episode_diversity(study_id: str) -> None:
    """Print episode-diversity payloads from study arms."""
    studies_metrics(study_id)


@studies_app.command("window-horizon")
def studies_window_horizon(study_id: str) -> None:
    """Print configured window/horizon matrix."""
    with SessionLocal() as session:
        item = session.get(StudyManifest, study_id)
        if item is None:
            raise typer.Exit(1)
        typer.echo({"window_lengths": item.configuration["windows"]["lengths"], "outcome_horizons": item.configuration["outcomes"]["horizons"]})


@studies_app.command("report")
def studies_report(study_id: str) -> None:
    """Print a Markdown study report."""
    with SessionLocal() as session:
        typer.echo(MultiAssetStudyService(session).report(study_id))


@studies_app.command("refresh-dataset")
def studies_refresh_dataset(study_id: str) -> None:
    """Refresh study dataset entries and episodes from currently imported records."""
    with SessionLocal() as session:
        study = MultiAssetStudyService(session).refresh_dataset(study_id)
        typer.echo(f"study_id={study.id} status={study.status} decision={study.decision}")


@studies_app.command("status")
def studies_status(study_id: str) -> None:
    """Print resumable study status and provenance."""
    with SessionLocal() as session:
        status = MultiAssetStudyService(session).status(study_id)
        typer.echo(json.dumps(status, indent=2, sort_keys=True, default=str))


@studies_app.command("prepare-data")
def studies_prepare_data(
    study_id: str,
    instrument: str | None = typer.Option(None, "--instrument"),
    batch_size: int = typer.Option(1, "--batch-size"),
    skip_refresh: bool = typer.Option(False, "--skip-refresh", help="Skip study dataset refresh after preparation."),
    resource_guard: bool = typer.Option(True, "--resource-guard/--no-resource-guard", help="Pause before heavy preparation stages when host resources are below safety thresholds."),
    min_available_ram_mb: int = typer.Option(
        int(os.environ.get("MARKET_GENOME_MIN_AVAILABLE_RAM_MB", "1024")),
        "--min-available-ram-mb",
        help="Minimum host MemAvailable required before each heavy preparation stage.",
    ),
    min_free_swap_mb: int = typer.Option(
        int(os.environ.get("MARKET_GENOME_MIN_FREE_SWAP_MB", "512")),
        "--min-free-swap-mb",
        help="Minimum host SwapFree required before each heavy preparation stage.",
    ),
) -> None:
    """Run the manifest-driven study data pipeline for imported real datasets."""
    def _enforce_resource_guard(symbol: str, stage: str, length: int | None = None) -> None:
        if not resource_guard:
            return
        result = evaluate_resource_guard(
            read_resource_snapshot(),
            min_available_ram_mb=min_available_ram_mb,
            min_free_swap_mb=min_free_swap_mb,
        )
        if result.ok:
            return
        typer.echo(
            json.dumps(
                {
                    "status": "PILOT_PREPARATION_PAUSED_RESOURCE_GUARD",
                    "study_id": study_id,
                    "instrument": symbol,
                    "stage": stage,
                    "window_length": length,
                    "reasons": list(result.reasons),
                    "available_ram_mb": result.snapshot.available_ram_mb,
                    "free_swap_mb": result.snapshot.free_swap_mb,
                    "min_available_ram_mb": min_available_ram_mb,
                    "min_free_swap_mb": min_free_swap_mb,
                },
                sort_keys=True,
            )
        )
        raise typer.Exit(75)

    def _aggregate_status(statuses: list[str]) -> str:
        unique_statuses = set(statuses)
        if not statuses:
            return "SKIPPED"
        if unique_statuses == {"COMPLETED"}:
            return "COMPLETED"
        if "FAILED" in unique_statuses:
            return "FAILED"
        if "PARTIAL" in unique_statuses:
            return "PARTIAL"
        return "COMPLETED_WITH_WARNINGS"

    with SessionLocal() as session:
        registry = RegistryService(session)
        service = MultiAssetStudyService(session)
        study = session.get(StudyManifest, study_id)
        if study is None:
            raise typer.Exit(1)
        processed = 0
        for item in study.configuration.get("universe", {}).get("instruments", []):
            if instrument and item["symbol"] != instrument:
                continue
            actual_instrument = registry.get_instrument_by_symbol(item["symbol"], item.get("exchange"))
            if actual_instrument is None:
                actual_instrument = session.query(Instrument).filter(Instrument.symbol == item["symbol"]).first()
            timeframe = registry.get_timeframe_by_code(item["timeframe"])
            if actual_instrument is None or timeframe is None:
                typer.echo(f"{item['symbol']}\tSKIPPED\tREAL_DATA_REQUIRED")
                continue
            lengths = [int(length) for length in study.configuration["windows"]["lengths"]]
            window_statuses: list[str] = []
            normalization_statuses: list[str] = []
            feature_statuses: list[str] = []
            context_statuses: list[str] = []
            outcome_statuses: list[str] = []
            for length in lengths:
                _enforce_resource_guard(item["symbol"], "windows", length)
                window_result = WindowBuildService(session).build(
                    instrument_id=actual_instrument.id,
                    timeframe_id=timeframe.id,
                    window_lengths=[length],
                    stride=1,
                    mode="incremental",
                    window_version="window_v1",
                    quality_policy=WindowQualityPolicy(
                        calendar_mode="continuous"
                        if actual_instrument.asset_class == "crypto"
                        else "session_based"
                    ),
                )
                _enforce_resource_guard(item["symbol"], "normalization", length)
                normalization_result = NormalizationBuildService(session).build(
                    normalization_method="anchored_log_return",
                    resample_points=64,
                    resampling_method="linear",
                    instrument_id=actual_instrument.id,
                    timeframe_id=timeframe.id,
                    window_length=length,
                    mode="incremental",
                    normalization_version="normalization_v1",
                    source_window_version="window_v1",
                    policies=NormalizationPolicies(),
                )
                _enforce_resource_guard(item["symbol"], "market_dna", length)
                feature_result = FeatureBuildService(session).build(
                    feature_set_code="market_dna_v1",
                    mode="incremental",
                    instrument_id=actual_instrument.id,
                    timeframe_id=timeframe.id,
                    window_length=length,
                )
                _enforce_resource_guard(item["symbol"], "market_context", length)
                context_result = ContextBuildService(session).build(
                    context_producer_code="transparent_context_v1",
                    feature_set_code="market_dna_v1",
                    mode="incremental",
                    instrument_id=actual_instrument.id,
                    timeframe_id=timeframe.id,
                    window_length=length,
                )
                _enforce_resource_guard(item["symbol"], "outcomes", length)
                outcome_result = OutcomeBuildService(session).build(
                    outcome_set_code="forward_outcomes_v1",
                    horizons=[int(value) for value in study.configuration["outcomes"]["horizons"]],
                    mode="incremental",
                    instrument_id=actual_instrument.id,
                    timeframe_id=timeframe.id,
                    window_length=length,
                )
                window_statuses.append(window_result.build.status)
                normalization_statuses.append(normalization_result.build.status)
                feature_statuses.append(feature_result.build.status)
                context_statuses.append(context_result.build.status)
                outcome_statuses.append(outcome_result.build.status)
            processed += 1
            typer.echo(
                f"{item['symbol']}\tWINDOWS={_aggregate_status(window_statuses)}\t"
                f"NORMALIZATION={_aggregate_status(normalization_statuses)}\tDNA={_aggregate_status(feature_statuses)}\t"
                f"CONTEXT={_aggregate_status(context_statuses)}\tOUTCOMES={_aggregate_status(outcome_statuses)}"
            )
            if processed >= batch_size:
                break
        if not skip_refresh:
            service.refresh_dataset(study_id)
        typer.echo(f"processed={processed}")


@studies_app.command("write-report-artifacts")
def studies_write_report_artifacts(
    study_id: str,
    output_dir: Path = STUDY_REPORT_OUTPUT_DIR_OPTION,
) -> None:
    """Write stage-appropriate real study report artifacts."""
    output_dir.mkdir(parents=True, exist_ok=True)
    with SessionLocal() as session:
        service = MultiAssetStudyService(session)
        status = service.status(study_id)
        study = session.get(StudyManifest, study_id)
        if study is None:
            raise typer.Exit(1)
        (output_dir / "report.md").write_text(service.report(study_id), encoding="utf-8")
        (output_dir / "report.json").write_text(json.dumps(status, indent=2, sort_keys=True, default=str), encoding="utf-8")
        (output_dir / "dataset_manifest.json").write_text(json.dumps(study.configuration, indent=2, sort_keys=True, default=str), encoding="utf-8")
        (output_dir / "preflight.json").write_text(json.dumps(status["preflight_blockers"], indent=2, sort_keys=True), encoding="utf-8")
        (output_dir / "study_decision.json").write_text(
            json.dumps({"decision": study.decision, "status": study.status, "rationale": study.decision_rationale}, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        entries = session.query(StudyDatasetEntry).filter(StudyDatasetEntry.study_id == study_id)
        write_quality_csv(
            output_dir / "instrument_summary.csv",
            [
                {
                    "instrument_id": entry.instrument_id,
                    "symbol": entry.instrument.symbol,
                    "bar_count": entry.bar_count,
                    "window_count": entry.window_count,
                    "episode_count": entry.episode_count,
                    "quality_status": entry.quality_status,
                    "inclusion_status": entry.inclusion_status,
                }
                for entry in entries
            ],
        )
        episodes = session.query(StudyEpisode).filter(StudyEpisode.study_id == study_id)
        write_quality_csv(
            output_dir / "episode_summary.csv",
            [
                {
                    "episode_id": episode.episode_id,
                    "instrument_id": episode.instrument_id,
                    "timeframe_id": episode.timeframe_id,
                    "window_count": episode.window_count,
                    "episode_hash": episode.episode_hash,
                }
                for episode in episodes
            ],
        )
        arms = session.query(StudyArm).filter(StudyArm.study_id == study_id)
        write_quality_csv(
            output_dir / "pilot_summary.csv",
            [
                {"period_role": arm.period_role, "arm_code": arm.arm_code, **arm.metrics}
                for arm in arms
                if arm.period_role == "DEVELOPMENT"
            ],
        )
        write_quality_csv(
            output_dir / "validation_summary.csv",
            [
                {"period_role": arm.period_role, "arm_code": arm.arm_code, **arm.metrics}
                for arm in arms
                if arm.period_role == "VALIDATION"
            ],
        )
        write_quality_csv(
            output_dir / "window_horizon_matrix.csv",
            [
                {"window_length": length, "horizon": horizon}
                for length in study.configuration["windows"]["lengths"]
                for horizon in study.configuration["outcomes"]["horizons"]
            ],
        )
        if study.final_test_lock_hash:
            (output_dir / "final_test_lock.json").write_text(
                json.dumps(study.final_test_lock, indent=2, sort_keys=True, default=str),
                encoding="utf-8",
            )
        typer.echo(str(output_dir))


@replication_app.command("definitions")
def replication_definitions() -> None:
    """List frozen replication protocol definitions."""
    payload = [definition.__dict__ for definition in list_replication_protocol_definitions()]
    typer.echo(json.dumps(payload, indent=2, sort_keys=True, default=list))


@replication_app.command("freeze-protocol")
def replication_freeze_protocol(
    protocol_code: str,
    source_experiment_id: str,
    frozen_by: str | None = typer.Option(None, "--frozen-by"),
) -> None:
    """Persist an immutable replication protocol before independent data is evaluated."""
    with SessionLocal() as session:
        protocol = ReplicationService(session).freeze_protocol(
            protocol_code, source_experiment_id, frozen_by=frozen_by
        )
        typer.echo(
            f"protocol_id={protocol.id} status={protocol.status} "
            f"configuration_hash={protocol.configuration_hash} frozen_at={protocol.frozen_at}"
        )


@replication_app.command("lock")
def replication_lock(
    protocol_id: str,
    study_id: str,
    source_study_id: str,
    dataset_hash: str,
    provider_code: str,
    provider_provenance_hash: str,
    instrument_universe: str = typer.Option(..., "--instrument-universe", help="Comma-separated symbols."),
    date_start: str = typer.Option(..., "--date-start"),
    date_end: str = typer.Option(..., "--date-end"),
    locked_by: str | None = typer.Option(None, "--locked-by"),
) -> None:
    """Freeze an immutable replication lock immediately before independent evaluation."""
    with SessionLocal() as session:
        lock = ReplicationService(session).create_lock(
            protocol_id,
            study_id=study_id,
            source_study_id=source_study_id,
            dataset_hash=dataset_hash,
            provider_code=provider_code,
            provider_provenance_hash=provider_provenance_hash,
            instrument_universe=[symbol.strip() for symbol in instrument_universe.split(",") if symbol.strip()],
            date_range={"start": date_start, "end": date_end},
            locked_by=locked_by,
        )
        typer.echo(f"lock_id={lock.id} status={lock.status} lock_hash={lock.lock_hash}")


@replication_app.command("record")
def replication_record(
    lock_id: str,
    provider_independence: str = typer.Option(..., "--provider-independence"),
    independence_notes: str | None = typer.Option(None, "--independence-notes"),
) -> None:
    """Create the pending replication decision record tied to a lock."""
    with SessionLocal() as session:
        record = ReplicationService(session).create_record(
            lock_id, provider_independence=provider_independence, independence_notes=independence_notes
        )
        typer.echo(f"record_id={record.id} decision={record.decision}")


@replication_app.command("inspect")
def replication_inspect(record_id: str) -> None:
    """Show a replication record with its linked protocol and lock."""
    with SessionLocal() as session:
        record = session.get(ReplicationRecord, record_id)
        if record is None:
            raise typer.Exit(1)
        protocol = session.get(ReplicationProtocol, record.protocol_id)
        lock = session.get(ReplicationLock, record.lock_id)
        typer.echo(
            json.dumps(
                {
                    "record_id": record.id,
                    "decision": record.decision,
                    "decision_rationale": record.decision_rationale,
                    "provider_independence": record.provider_independence,
                    "comparison": record.comparison,
                    "protocol": {"id": protocol.id, "status": protocol.status, "configuration_hash": protocol.configuration_hash} if protocol else None,
                    "lock": {"id": lock.id, "status": lock.status, "lock_hash": lock.lock_hash, "dataset_hash": lock.dataset_hash} if lock else None,
                },
                indent=2,
                sort_keys=True,
                default=str,
            )
        )


@prospective_app.command("protocols")
def prospective_protocols() -> None:
    """List frozen-able prospective protocol definitions."""
    payload = [definition.__dict__ for definition in list_prospective_protocol_definitions()]
    typer.echo(json.dumps(payload, indent=2, sort_keys=True, default=list))


@prospective_app.command("create-protocol")
def prospective_create_protocol(
    protocol_code: str,
    frozen_by: str | None = typer.Option(None, "--frozen-by"),
) -> None:
    """Freeze an immutable prospective forecasting protocol."""
    with SessionLocal() as session:
        protocol = ProspectiveContextForecastService(session).freeze_protocol(protocol_code, frozen_by=frozen_by)
        typer.echo(
            f"protocol_id={protocol.id} status={protocol.status} context_definition={protocol.context_definition} "
            f"configuration_hash={protocol.configuration_hash} frozen_at={protocol.frozen_at}"
        )


def _latest_frozen_protocol(session, protocol_code: str) -> ProspectiveProtocol | None:
    return (
        session.query(ProspectiveProtocol)
        .filter(ProspectiveProtocol.protocol_code == protocol_code, ProspectiveProtocol.status == "FROZEN")
        .order_by(ProspectiveProtocol.created_at.desc())
        .first()
    )


@prospective_app.command("latest")
def prospective_latest(
    protocol_code: str = typer.Option("market_context_forecast_v1", "--protocol"),
    limit: int = typer.Option(20, "--limit"),
) -> None:
    """Show the most recent prospective forecasts for a protocol."""
    with SessionLocal() as session:
        protocol = _latest_frozen_protocol(session, protocol_code)
        if protocol is None:
            raise typer.Exit(1)
        forecasts = (
            session.query(ProspectiveForecast)
            .filter(ProspectiveForecast.protocol_id == protocol.id)
            .order_by(ProspectiveForecast.forecast_created_at.desc())
            .limit(limit)
            .all()
        )
        typer.echo(
            json.dumps(
                [
                    {
                        "id": f.id, "instrument_id": f.instrument_id, "window_length": f.window_length,
                        "horizon_bars": f.horizon_bars, "forecast_timestamp": f.forecast_timestamp,
                        "probability_positive": f.probability_positive, "sample_count": f.sample_count,
                        "context_level_used": f.context_level_used, "provenance_class": f.provenance_class,
                        "status": f.status,
                    }
                    for f in forecasts
                ],
                indent=2, sort_keys=True, default=str,
            )
        )


@prospective_app.command("run-daily")
def prospective_run_daily(
    manifest_path: Path = DEFAULT_PROSPECTIVE_MANIFEST_ARGUMENT,
    protocol_code: str = typer.Option("market_context_forecast_v1", "--protocol"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    resource_guard: bool = typer.Option(True, "--resource-guard/--no-resource-guard"),
    min_available_ram_mb: int = typer.Option(int(os.environ.get("MARKET_GENOME_MIN_AVAILABLE_RAM_MB", "1024")), "--min-available-ram-mb"),
    min_free_swap_mb: int = typer.Option(int(os.environ.get("MARKET_GENOME_MIN_FREE_SWAP_MB", "512")), "--min-free-swap-mb"),
    min_free_disk_mb: int = typer.Option(int(os.environ.get("MARKET_GENOME_MIN_FREE_DISK_MB", "15360")), "--min-free-disk-mb"),
) -> None:
    """One deterministic daily iteration: ensure latest completed D1 bars are imported
    and derived (windows/normalization/DNA/context/outcomes), create TRUE_PROSPECTIVE
    forecasts from the latest available context state per instrument/window/horizon,
    mature eligible pending forecasts, and refresh the evaluation snapshot.

    Known limitation: acquisition re-fetches full history under a new dataset version
    when the latest imported bar is stale (see manifest dataset_version), rather than
    a true incremental append -- acceptable at a once-daily cadence for 6 instruments,
    not intended to scale to a larger universe or higher frequency without revisiting
    the acquisition layer's incremental-append support.
    """
    if resource_guard:
        result = evaluate_resource_guard(
            read_resource_snapshot(), min_available_ram_mb=min_available_ram_mb, min_free_swap_mb=min_free_swap_mb,
            min_free_disk_mb=min_free_disk_mb,
        )
        if not result.ok:
            typer.echo(json.dumps({"status": "PROSPECTIVE_RUN_DAILY_PAUSED_RESOURCE_GUARD", "reasons": list(result.reasons)}, sort_keys=True))
            raise typer.Exit(75)

    with SessionLocal() as session:
        service = ProspectiveContextForecastService(session)
        protocol = _latest_frozen_protocol(session, protocol_code)
        if protocol is None:
            raise typer.Exit(1)

        # A real (mutating) run must never overlap with another real run against the
        # same database -- a Postgres session-level advisory lock is held for exactly
        # the lifetime of this connection, so it is also released automatically if
        # this process crashes mid-run (no manual cleanup required for crash recovery).
        lock_acquired = False
        if not dry_run and session.get_bind().dialect.name == "postgresql":
            lock_acquired = bool(
                session.execute(text("select pg_try_advisory_lock(hashtext(:name))"), {"name": RUN_LOCK_NAME}).scalar_one()
            )
            if not lock_acquired:
                typer.echo(json.dumps({"status": "PROSPECTIVE_RUN_ALREADY_ACTIVE"}, sort_keys=True))
                raise typer.Exit(75)

        # Precise new-forecast-id tracking: a before/after set diff against this exact
        # protocol, not a fuzzy "created in the last N hours" heuristic that could
        # double-count or miss forecasts depending on when a report is generated.
        forecast_ids_before = {
            row[0] for row in session.execute(
                text("select id from prospective_forecasts where protocol_id = :pid"), {"pid": protocol.id}
            ).all()
        }

        registry = RegistryService(session)
        horizons = [protocol.primary_horizon, *protocol.secondary_horizons]
        manifest = load_provider_manifest(manifest_path) if manifest_path.exists() else None
        today = datetime.now(UTC).strftime("%Y-%m-%d")

        report: dict[str, object] = {"protocol_id": protocol.id, "as_of": today, "instruments": []}
        if dry_run:
            report["note"] = (
                "Acquisition is previewed only (would_fetch/provider_requests_preview), never executed -- "
                "no network call, no filesystem write, no DB write. The per-horizon forecast preview below "
                "(would_create) is therefore evaluated against the currently-imported windows, not against "
                "windows a real run would create from freshly-fetched bars; it may differ once acquisition "
                "actually runs."
            )
        for symbol in protocol.instrument_universe:
            instrument = session.query(Instrument).filter(Instrument.symbol == symbol).first()
            timeframe = registry.get_timeframe_by_code(protocol.timeframe)
            entry: dict[str, object] = {"symbol": symbol, "forecasts": []}
            if instrument is None or timeframe is None:
                entry["status"] = "REAL_DATA_REQUIRED"
                report["instruments"].append(entry)
                continue

            if manifest is not None:
                bars_before = session.execute(
                    text("select count(*) from price_bars where instrument_id = :iid"), {"iid": instrument.id}
                ).scalar_one()
                latest_bar = session.execute(
                    text("select max(timestamp) as latest from price_bars where instrument_id = :iid"), {"iid": instrument.id}
                ).mappings().one()["latest"]
                latest_bar_date = latest_bar.strftime("%Y-%m-%d") if latest_bar is not None else None
                stale = is_stale(latest_bar_date, today)
                entry["database_latest_date"] = latest_bar_date
                if dry_run:
                    # Preview only: request construction is a pure local operation (no
                    # network call, no provider quota consumed, no filesystem write), so
                    # a dry run can report exactly what would be requested without ever
                    # calling provider.fetch() or persist_csv_import(). The actual new-bar
                    # count is unknowable without fetching, so it is reported as such
                    # rather than guessed.
                    entry["would_fetch"] = stale
                    if stale:
                        requests = requests_from_manifest(manifest, symbol=symbol, end=today, force_refresh=True, new_version=today)
                        entry["provider_requests_preview"] = [
                            {"provider_symbol": r.provider_symbol, "start": r.start, "end": r.end, "dataset_version": r.dataset_version}
                            for r in requests
                        ]
                        entry["new_completed_bars_expected"] = "UNKNOWN_UNTIL_ACQUISITION_RUNS"
                    else:
                        entry["provider_requests_preview"] = []
                        entry["new_completed_bars_expected"] = 0
                else:
                    if stale:
                        requests = requests_from_manifest(manifest, symbol=symbol, end=today, force_refresh=True, new_version=today)
                        provider = get_provider(manifest["provider"]["code"])
                        for request in requests:
                            try:
                                result = provider.fetch(request)
                                provider_latest_date = result.received_end[:10] if result.received_end else None
                                entry["provider_latest_date"] = provider_latest_date
                                if detect_provider_date_regression(latest_bar_date, provider_latest_date):
                                    # Never delete or overwrite newer local data with older
                                    # provider history -- record and skip persisting only
                                    # for this instrument; unrelated instruments continue.
                                    entry["warnings"] = [*entry.get("warnings", []), "PROVIDER_DATE_REGRESSION"]
                                    continue
                                if result.csv_path and result.status in {"COMPLETED", "SKIPPED_EXISTING"}:
                                    persist_csv_import(
                                        session, result.csv_path,
                                        CsvImportMetadata(
                                            symbol=symbol, instrument_name=symbol, asset_class=instrument.asset_class,
                                            exchange=instrument.exchange, currency=instrument.currency, timezone=instrument.timezone,
                                            timeframe=protocol.timeframe, source_name="ALPHA_VANTAGE", timeframe_seconds=86_400,
                                            volume_type="unknown", dry_run=False,
                                        ),
                                    )
                            except Exception as exc:  # noqa: BLE001
                                entry["acquisition_error"] = classify_provider_error(exc)
                    bars_after = session.execute(
                        text("select count(*) from price_bars where instrument_id = :iid"), {"iid": instrument.id}
                    ).scalar_one()
                    entry["new_bars_imported"] = bars_after - bars_before
                    # Only rebuild derived state when there is genuinely new source data --
                    # rebuilding with a horizon subset narrower than the original research
                    # build (RESEARCH_OUTCOME_HORIZONS) would otherwise create duplicate
                    # OutcomeObservation rows under a different configuration_hash even when
                    # nothing changed (see Step 10B-C incident: 267,246 duplicate rows).
                    if bars_after > bars_before:
                        for length in protocol.window_lengths:
                            WindowBuildService(session).build(
                                instrument_id=instrument.id, timeframe_id=timeframe.id, window_lengths=[length], stride=1,
                                mode="incremental", window_version="window_v1",
                                quality_policy=WindowQualityPolicy(calendar_mode="continuous" if instrument.asset_class == "crypto" else "session_based"),
                            )
                            NormalizationBuildService(session).build(
                                normalization_method="anchored_log_return", resample_points=64, resampling_method="linear",
                                instrument_id=instrument.id, timeframe_id=timeframe.id, window_length=length, mode="incremental",
                                normalization_version="normalization_v1", source_window_version="window_v1", policies=NormalizationPolicies(),
                            )
                            FeatureBuildService(session).build(feature_set_code="market_dna_v1", mode="incremental", instrument_id=instrument.id, timeframe_id=timeframe.id, window_length=length)
                            ContextBuildService(session).build(context_producer_code="transparent_context_v1", feature_set_code="market_dna_v1", mode="incremental", instrument_id=instrument.id, timeframe_id=timeframe.id, window_length=length)
                            OutcomeBuildService(session).build(outcome_set_code="forward_outcomes_v1", horizons=RESEARCH_OUTCOME_HORIZONS, mode="incremental", instrument_id=instrument.id, timeframe_id=timeframe.id, window_length=length)

            for length in protocol.window_lengths:
                latest_window = (
                    session.query(PatternWindow)
                    .filter(PatternWindow.instrument_id == instrument.id, PatternWindow.timeframe_id == timeframe.id, PatternWindow.window_length == length)
                    .order_by(PatternWindow.end_timestamp.desc())
                    .first()
                )
                if latest_window is None:
                    entry["forecasts"].append({"window_length": length, "status": "NO_WINDOW_AVAILABLE"})
                    continue
                context = (
                    session.query(MarketContext)
                    .filter(MarketContext.pattern_window_id == latest_window.id)
                    .order_by(MarketContext.created_at.desc())
                    .first()
                )
                if context is None:
                    entry["forecasts"].append({"window_length": length, "status": "NO_CONTEXT_AVAILABLE"})
                    continue
                context_values = {"trend_state": context.trend_state, "volatility_state": context.volatility_state}
                context_code = f"{context.trend_state}|{context.volatility_state}"
                for horizon in horizons:
                    if dry_run:
                        existing = (
                            session.query(ProspectiveForecast)
                            .filter(
                                ProspectiveForecast.protocol_id == protocol.id, ProspectiveForecast.pattern_window_id == latest_window.id,
                                ProspectiveForecast.horizon_bars == horizon, ProspectiveForecast.provenance_class == "TRUE_PROSPECTIVE",
                            )
                            .one_or_none()
                        )
                        entry["forecasts"].append(
                            {"window_length": length, "horizon": horizon, "would_create": existing is None, "latest_window_end": str(latest_window.end_timestamp)}
                        )
                    else:
                        try:
                            forecast = service.create_forecast(
                                protocol, instrument_id=instrument.id, timeframe_id=timeframe.id, window_length=length,
                                pattern_window_id=latest_window.id, horizon_bars=horizon, forecast_timestamp=latest_window.end_timestamp,
                                data_cutoff_timestamp=latest_window.end_timestamp, context_code=context_code, context_values=context_values,
                                source_hash=latest_window.source_data_hash, context_hash=context.context_hash,
                            )
                            entry["forecasts"].append({"window_length": length, "horizon": horizon, "forecast_id": forecast.id, "status": forecast.status})
                        except Exception as exc:  # noqa: BLE001
                            entry["forecasts"].append({"window_length": length, "horizon": horizon, "status": "SKIPPED", "reason": str(exc)})
            report["instruments"].append(entry)

        report["current_forecast_count"] = session.query(ProspectiveForecast).filter(ProspectiveForecast.protocol_id == protocol.id).count()
        report["current_matured_count"] = (
            session.query(ProspectiveForecast).filter(ProspectiveForecast.protocol_id == protocol.id, ProspectiveForecast.status == "MATURED").count()
        )
        if dry_run:
            report["pending_forecasts_eligible_to_mature_preview"] = [
                {"forecast_id": row["id"], "pattern_window_id": row["pattern_window_id"], "horizon_bars": row["horizon_bars"]}
                for row in session.execute(
                    text(
                        """
                        select pf.id, pf.pattern_window_id, pf.horizon_bars from prospective_forecasts pf
                        join outcome_observations oo on oo.pattern_window_id = pf.pattern_window_id and oo.horizon_bars = pf.horizon_bars and oo.is_complete is true
                        where pf.protocol_id = :protocol_id and pf.status = 'PENDING_OUTCOME'
                        """
                    ),
                    {"protocol_id": protocol.id},
                ).mappings().all()
            ]
        else:
            matured = service.mature_eligible(protocol.id, as_of=datetime.now(UTC))
            snapshot = service.create_evaluation_snapshot(protocol, as_of=datetime.now(UTC))
            report["matured_count_this_run"] = len(matured)
            report["evaluation_status"] = snapshot.status
            report["evaluation_snapshot_id"] = snapshot.id

            # Precise set diff against the before-snapshot, not a fuzzy time window --
            # this is the exact set of forecasts this invocation created, whatever their
            # window/horizon/instrument, including ones a per-instrument exception left
            # unreported above.
            forecast_ids_after = {
                row[0] for row in session.execute(
                    text("select id from prospective_forecasts where protocol_id = :pid"), {"pid": protocol.id}
                ).all()
            }
            new_forecast_ids = sorted(forecast_ids_after - forecast_ids_before)
            report["new_forecast_ids"] = new_forecast_ids
            report["new_forecast_count"] = len(new_forecast_ids)

            # A hardcoded "research/reports/..." path is resolved against the *process*
            # working directory, not the repo root -- inside a `docker compose run --rm`
            # worker container that differs from the host, and the container is removed
            # on exit, so anything written outside the mounted report-root volume is
            # silently lost the moment the container exits (caught live on 2026-08-24:
            # the very first artifact this code ever wrote vanished with the container).
            # MARKET_GENOME_REPORT_ROOT is exactly the env var docker-compose.vps.yml
            # already sets and mounts at /opt/market-genome/reports for this purpose.
            audit_dir = Path(os.environ.get("MARKET_GENOME_REPORT_ROOT", "research/reports")) / "prospective_context_validation"
            audit_dir.mkdir(parents=True, exist_ok=True)
            audit_payload = {
                "run_timestamp": datetime.now(UTC).isoformat(),
                "protocol_id": protocol.id,
                "provider_code": protocol.provider_code,
                "instrument_universe": list(protocol.instrument_universe),
                "new_bars_by_instrument": {e["symbol"]: e.get("new_bars_imported") for e in report["instruments"]},
                "new_forecast_ids": new_forecast_ids,
                "new_forecast_count": len(new_forecast_ids),
                "matured_count_this_run": len(matured),
                "evaluation_snapshot_id": snapshot.id,
                "warnings": {e["symbol"]: e.get("warnings") for e in report["instruments"] if e.get("warnings")},
                "resource_state": (
                    {"available_ram_mb": (snap := read_resource_snapshot()).available_ram_mb, "free_disk_mb": snap.free_disk_mb}
                    if resource_guard else None
                ),
            }
            audit_payload["run_hash"] = sha256_canonical(audit_payload)
            audit_path = audit_dir / f"prospective_daily_run_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
            audit_path.write_text(json.dumps(audit_payload, indent=2, sort_keys=True, default=str), encoding="utf-8")
            report["daily_run_artifact_path"] = str(audit_path)
        report["status"] = "DRY_RUN" if dry_run else "COMPLETED"
        if lock_acquired:
            session.execute(text("select pg_advisory_unlock(hashtext(:name))"), {"name": RUN_LOCK_NAME})
        typer.echo(json.dumps(report, indent=2, sort_keys=True, default=str))


@prospective_app.command("forecast-only")
def prospective_forecast_only(
    protocol_code: str = typer.Option("market_context_forecast_v1", "--protocol"),
    provenance_class: str = typer.Option("TRUE_PROSPECTIVE", "--provenance-class"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Create forecasts from the latest already-available windows/contexts only --
    no data acquisition and no derived-state rebuild. Use this when acquisition has
    already run separately (or is not needed) and only the forecast step should
    advance. --provenance-class defaults to TRUE_PROSPECTIVE; pass BACKFILL_SIMULATION
    or HISTORICAL_VALIDATION for smoke tests and calibration runs so they are never
    conflated with the genuinely prospective evidence base (see RETROACTIVE_PROSPECTIVE_
    FORECAST_REJECTED, which still applies when provenance_class is TRUE_PROSPECTIVE)."""
    with SessionLocal() as session:
        service = ProspectiveContextForecastService(session)
        protocol = _latest_frozen_protocol(session, protocol_code)
        if protocol is None:
            raise typer.Exit(1)
        registry = RegistryService(session)
        horizons = [protocol.primary_horizon, *protocol.secondary_horizons]
        today = datetime.now(UTC).strftime("%Y-%m-%d")

        report: dict[str, object] = {"protocol_id": protocol.id, "as_of": today, "provenance_class": provenance_class, "instruments": []}
        for symbol in protocol.instrument_universe:
            instrument = session.query(Instrument).filter(Instrument.symbol == symbol).first()
            timeframe = registry.get_timeframe_by_code(protocol.timeframe)
            entry: dict[str, object] = {"symbol": symbol, "forecasts": []}
            if instrument is None or timeframe is None:
                entry["status"] = "REAL_DATA_REQUIRED"
                report["instruments"].append(entry)
                continue

            for length in protocol.window_lengths:
                latest_window = (
                    session.query(PatternWindow)
                    .filter(PatternWindow.instrument_id == instrument.id, PatternWindow.timeframe_id == timeframe.id, PatternWindow.window_length == length)
                    .order_by(PatternWindow.end_timestamp.desc())
                    .first()
                )
                if latest_window is None:
                    entry["forecasts"].append({"window_length": length, "status": "NO_WINDOW_AVAILABLE"})
                    continue
                context = (
                    session.query(MarketContext)
                    .filter(MarketContext.pattern_window_id == latest_window.id)
                    .order_by(MarketContext.created_at.desc())
                    .first()
                )
                if context is None:
                    entry["forecasts"].append({"window_length": length, "status": "NO_CONTEXT_AVAILABLE"})
                    continue
                context_values = {"trend_state": context.trend_state, "volatility_state": context.volatility_state}
                context_code = f"{context.trend_state}|{context.volatility_state}"
                for horizon in horizons:
                    if dry_run:
                        existing = (
                            session.query(ProspectiveForecast)
                            .filter(
                                ProspectiveForecast.protocol_id == protocol.id, ProspectiveForecast.pattern_window_id == latest_window.id,
                                ProspectiveForecast.horizon_bars == horizon, ProspectiveForecast.provenance_class == provenance_class,
                            )
                            .one_or_none()
                        )
                        entry["forecasts"].append(
                            {"window_length": length, "horizon": horizon, "would_create": existing is None, "latest_window_end": str(latest_window.end_timestamp)}
                        )
                    else:
                        try:
                            forecast = service.create_forecast(
                                protocol, instrument_id=instrument.id, timeframe_id=timeframe.id, window_length=length,
                                pattern_window_id=latest_window.id, horizon_bars=horizon, forecast_timestamp=latest_window.end_timestamp,
                                data_cutoff_timestamp=latest_window.end_timestamp, context_code=context_code, context_values=context_values,
                                source_hash=latest_window.source_data_hash, context_hash=context.context_hash,
                                provenance_class=provenance_class,
                            )
                            entry["forecasts"].append({"window_length": length, "horizon": horizon, "forecast_id": forecast.id, "status": forecast.status})
                        except Exception as exc:  # noqa: BLE001
                            entry["forecasts"].append({"window_length": length, "horizon": horizon, "status": "SKIPPED", "reason": str(exc)})
            report["instruments"].append(entry)

        report["status"] = "DRY_RUN" if dry_run else "COMPLETED"
        typer.echo(json.dumps(report, indent=2, sort_keys=True, default=str))


@prospective_app.command("mature")
def prospective_mature(protocol_code: str = typer.Option("market_context_forecast_v1", "--protocol")) -> None:
    """Attach outcomes to any prospective forecasts whose horizon has now elapsed."""
    with SessionLocal() as session:
        protocol = _latest_frozen_protocol(session, protocol_code)
        if protocol is None:
            raise typer.Exit(1)
        matured = ProspectiveContextForecastService(session).mature_eligible(protocol.id, as_of=datetime.now(UTC))
        typer.echo(json.dumps({"matured_count": len(matured)}, sort_keys=True))


@prospective_app.command("evaluate")
def prospective_evaluate(protocol_code: str = typer.Option("market_context_forecast_v1", "--protocol")) -> None:
    """Compute and persist a fresh prospective evaluation snapshot."""
    with SessionLocal() as session:
        protocol = _latest_frozen_protocol(session, protocol_code)
        if protocol is None:
            raise typer.Exit(1)
        snapshot = ProspectiveContextForecastService(session).create_evaluation_snapshot(protocol, as_of=datetime.now(UTC))
        typer.echo(
            json.dumps(
                {
                    "snapshot_id": snapshot.id, "forecast_count": snapshot.forecast_count, "matured_count": snapshot.matured_count,
                    "primary_horizon": snapshot.primary_horizon, "primary_horizon_matured_count": snapshot.primary_horizon_matured_count,
                    "brier_score": snapshot.brier_score, "brier_skill_vs_unconditional": snapshot.brier_skill_vs_unconditional,
                    "bootstrap_ci_low": snapshot.bootstrap_ci_low, "bootstrap_ci_high": snapshot.bootstrap_ci_high,
                    "balanced_accuracy": snapshot.balanced_accuracy, "mcc": snapshot.mcc,
                    "per_horizon_metrics": snapshot.per_horizon_metrics,
                    "status": snapshot.status,
                },
                indent=2, sort_keys=True, default=str,
            )
        )


@prospective_app.command("status")
def prospective_status(protocol_code: str = typer.Option("market_context_forecast_v1", "--protocol")) -> None:
    """Show the protocol's current forecast/maturation/evaluation status."""
    with SessionLocal() as session:
        protocol = _latest_frozen_protocol(session, protocol_code)
        if protocol is None:
            raise typer.Exit(1)
        total = session.query(ProspectiveForecast).filter(ProspectiveForecast.protocol_id == protocol.id).count()
        matured = session.query(ProspectiveForecast).filter(ProspectiveForecast.protocol_id == protocol.id, ProspectiveForecast.status == "MATURED").count()
        pending = session.query(ProspectiveForecast).filter(ProspectiveForecast.protocol_id == protocol.id, ProspectiveForecast.status == "PENDING_OUTCOME").count()
        latest_snapshot = (
            session.query(ProspectiveEvaluationSnapshot)
            .filter(ProspectiveEvaluationSnapshot.protocol_id == protocol.id)
            .order_by(ProspectiveEvaluationSnapshot.created_at.desc())
            .first()
        )
        # Horizon readiness: a naive calendar-day estimate, not a trading-bar count --
        # "N bars" is not "N calendar days" for FX (weekends), so this is explicitly a
        # lower bound, not a prediction of the actual maturation date.
        horizon_readiness = []
        for row in session.execute(
            text(
                """
                select horizon_bars, count(*) as pending_count, min(forecast_timestamp) as oldest_forecast_timestamp
                from prospective_forecasts
                where protocol_id = :protocol_id and status = 'PENDING_OUTCOME'
                group by horizon_bars order by horizon_bars
                """
            ),
            {"protocol_id": protocol.id},
        ).mappings().all():
            horizon_readiness.append(
                {
                    "horizon_bars": row["horizon_bars"], "pending_count": row["pending_count"],
                    "oldest_forecast_timestamp": str(row["oldest_forecast_timestamp"]),
                    "earliest_possible_maturation_note": (
                        f"lower bound: oldest forecast + {row['horizon_bars']} calendar days "
                        "(actual maturation requires that many completed D1 bars, which is fewer "
                        "calendar days for crypto and more for FX due to weekends/holidays)"
                    ),
                }
            )
        typer.echo(
            json.dumps(
                {
                    "protocol_id": protocol.id, "protocol_status": protocol.status, "total_forecasts": total,
                    "matured_forecasts": matured, "pending_forecasts": pending,
                    "minimum_evidence_matured_forecasts": protocol.minimum_evidence_matured_forecasts,
                    "preferred_evidence_matured_forecasts": protocol.preferred_evidence_matured_forecasts,
                    "latest_evaluation_status": latest_snapshot.status if latest_snapshot else "NOT_YET_STARTED",
                    "latest_brier_skill_vs_unconditional": latest_snapshot.brier_skill_vs_unconditional if latest_snapshot else None,
                    "horizon_readiness": horizon_readiness,
                },
                indent=2, sort_keys=True, default=str,
            )
        )


if __name__ == "__main__":
    app()
