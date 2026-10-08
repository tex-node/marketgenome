from __future__ import annotations

from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from market_genome_context.definitions import (
    list_context_dimensions,
    list_context_producers,
)
from market_genome_context.service import ContextBuildService
from market_genome_data_ingestion.csv_import import CsvImportMetadata, persist_csv_import
from market_genome_diagnostics.definitions import (
    list_availability_policies,
    list_diagnostic_definitions,
    list_scaling_methods,
    list_weight_configurations,
)
from market_genome_diagnostics.service import RetrievalDiagnosticService
from market_genome_domain.database import get_session
from market_genome_domain.models import (
    ContextBuild,
    DataImport,
    DataImportIssue,
    DiagnosticArtifact,
    ExperimentFold,
    ExperimentMetric,
    ExperimentRun,
    FeatureBuild,
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
    QueryEvaluation,
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
from market_genome_prospective.definitions import list_prospective_protocol_definitions
from market_genome_shared.config import get_settings
from market_genome_similarity.definitions import get_similarity_method, list_similarity_methods
from market_genome_similarity.service import SimilaritySearchService
from market_genome_studies.definitions import list_study_definitions
from market_genome_studies.service import MultiAssetStudyService
from market_genome_validation.definitions import (
    list_baseline_methods,
    list_experiment_definitions,
    list_metric_definitions,
    list_validation_methods,
    list_weighting_methods,
)
from market_genome_validation.service import ValidationExperimentService
from market_genome_window_engine.service import (
    WindowBuildService,
    WindowQualityPolicy,
    list_window_bars,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from market_genome_api.schemas import (
    BaselineMethodResponse,
    ContextBuildRequest,
    ContextBuildResponse,
    ContextDimensionResponse,
    ContextProducerResponse,
    DataSourceCreate,
    DataSourceResponse,
    DiagnosticArtifactResponse,
    DiagnosticDefinitionResponse,
    DiagnosticExperimentCreateRequest,
    DiagnosticMethodResponse,
    EntityRef,
    ExperimentCreateRequest,
    ExperimentDefinitionResponse,
    ExperimentFoldResponse,
    ExperimentMetricResponse,
    ExperimentRunResponse,
    FeatureBuildRequest,
    FeatureBuildResponse,
    FeatureDefinitionResponse,
    FeatureSetResponse,
    ForwardPathResponse,
    ImportIssueResponse,
    ImportResponse,
    ImportSummary,
    InstrumentCreate,
    InstrumentResponse,
    MarketContextResponse,
    MarketDNAResponse,
    MarketDNAValuesResponse,
    MetricDefinitionResponse,
    NormalizationBuildRequest,
    NormalizationBuildResponse,
    NormalizationMethodResponse,
    NormalizedPatternResponse,
    NormalizedPatternValuesResponse,
    OutcomeBuildRequest,
    OutcomeBuildResponse,
    OutcomeDefinitionResponse,
    OutcomeObservationResponse,
    OutcomeSetResponse,
    OutcomeValuesResponse,
    PatternWindowResponse,
    PriceBarResponse,
    ProspectiveEvaluationSnapshotResponse,
    ProspectiveForecastResponse,
    ProspectiveProtocolResponse,
    QueryEvaluationResponse,
    SimilarityMatchResponse,
    SimilarityMethodResponse,
    SimilarityQueryResponse,
    SimilaritySearchRequest,
    StudyArmResponse,
    StudyCreateRequest,
    StudyDatasetEntryResponse,
    StudyDefinitionResponse,
    StudyEpisodeResponse,
    StudyManifestResponse,
    StudyPreflightResponse,
    TimeframeCreate,
    TimeframeResponse,
    ValidationMethodResponse,
    WindowBuildRequest,
    WindowBuildResponse,
)

router = APIRouter(prefix="/api/v1")
SessionDep = Annotated[Session, Depends(get_session)]


def _not_found(code: str) -> HTTPException:
    return HTTPException(status_code=404, detail={"code": code, "message": code, "details": {}})


def _import_response(data_import: DataImport) -> ImportResponse:
    return ImportResponse(
        import_id=data_import.id,
        status=data_import.status,
        dry_run=data_import.dry_run,
        source_hash=data_import.source_hash,
        instrument=EntityRef(id=data_import.instrument.id, symbol=data_import.instrument.symbol),
        timeframe=EntityRef(id=data_import.timeframe.id, code=data_import.timeframe.code),
        source=EntityRef(id=data_import.source.id, name=data_import.source.name),
        summary=ImportSummary(
            rows_read=data_import.rows_read,
            rows_valid=data_import.rows_valid,
            rows_inserted=data_import.rows_inserted,
            rows_updated=data_import.rows_updated,
            rows_skipped=data_import.rows_skipped,
            warnings=data_import.warnings_count,
            errors=data_import.errors_count,
        ),
        quality=data_import.quality_summary,
        created_at=data_import.created_at,
    )


def _build_response(build: WindowBuild) -> WindowBuildResponse:
    return WindowBuildResponse(
        id=build.id,
        status=build.status,
        instrument_id=build.instrument_id,
        timeframe_id=build.timeframe_id,
        requested_lengths=build.requested_lengths,
        stride=build.stride,
        mode=build.mode,
        window_version=build.window_version,
        configuration_hash=build.configuration_hash,
        source_bar_count=build.source_bar_count,
        candidate_windows=build.candidate_windows,
        created_windows=build.created_window_count,
        existing_windows=build.existing_window_count,
        skipped_windows=build.skipped_window_count,
        incomplete_windows=build.incomplete_window_count,
        quality_warning_windows=build.quality_warning_window_count,
        first_window_start=build.first_window_start,
        last_window_end=build.last_window_end,
        elapsed_seconds=float(build.elapsed_seconds) if build.elapsed_seconds is not None else None,
    )


def _normalization_build_response(build: NormalizationBuild) -> NormalizationBuildResponse:
    return NormalizationBuildResponse(
        id=build.id,
        status=build.status,
        normalization_method=build.normalization_method,
        normalization_version=build.normalization_version,
        resampling_method=build.resampling_method,
        resample_points=build.resample_points,
        source_window_version=build.source_window_version,
        configuration_hash=build.configuration_hash,
        source_window_count=build.source_window_count,
        created_representations=build.created_representation_count,
        existing_representations=build.existing_representation_count,
        skipped_representations=build.skipped_representation_count,
        failed_representations=build.failed_representation_count,
        elapsed_seconds=float(build.elapsed_seconds) if build.elapsed_seconds is not None else None,
    )


def _feature_build_response(build: FeatureBuild) -> FeatureBuildResponse:
    return FeatureBuildResponse(
        id=build.id,
        status=build.status,
        feature_set_code=build.feature_set_code,
        feature_set_version=build.feature_set_version,
        source_normalization_method=build.source_normalization_method,
        source_normalization_version=build.source_normalization_version,
        source_resampling_method=build.source_resampling_method,
        source_resample_points=build.source_resample_points,
        configuration_hash=build.configuration_hash,
        source_pattern_count=build.source_pattern_count,
        created_features=build.created_feature_count,
        existing_features=build.existing_feature_count,
        skipped_features=build.skipped_feature_count,
        failed_features=build.failed_feature_count,
        elapsed_seconds=float(build.elapsed_seconds) if build.elapsed_seconds is not None else None,
    )


def _context_build_response(build: ContextBuild) -> ContextBuildResponse:
    return ContextBuildResponse(
        id=build.id,
        status=build.status,
        context_producer_code=build.context_producer_code,
        context_producer_version=build.context_producer_version,
        feature_set_code=build.feature_set_code,
        feature_set_version=build.feature_set_version,
        configuration_hash=build.configuration_hash,
        source_market_dna_count=build.source_market_dna_count,
        created_contexts=build.created_context_count,
        existing_contexts=build.existing_context_count,
        partial_contexts=build.partial_context_count,
        skipped_contexts=build.skipped_context_count,
        failed_contexts=build.failed_context_count,
        elapsed_seconds=float(build.elapsed_seconds) if build.elapsed_seconds is not None else None,
    )


def _outcome_build_response(build: OutcomeBuild) -> OutcomeBuildResponse:
    return OutcomeBuildResponse(
        id=build.id,
        status=build.status,
        outcome_set_code=build.outcome_set_code,
        outcome_set_version=build.outcome_set_version,
        requested_horizons=build.requested_horizons,
        mode=build.mode,
        configuration_hash=build.configuration_hash,
        source_pattern_count=build.source_pattern_count,
        eligible_pattern_count=build.eligible_pattern_count,
        created_observations=build.created_observation_count,
        existing_observations=build.existing_observation_count,
        partial_observations=build.partial_observation_count,
        skipped_patterns=build.skipped_pattern_count,
        failed_observations=build.failed_observation_count,
        elapsed_seconds=float(build.elapsed_seconds) if build.elapsed_seconds is not None else None,
    )


def _similarity_query_response(query: SimilarityQuery) -> SimilarityQueryResponse:
    return SimilarityQueryResponse(
        id=query.id,
        query_window_id=query.query_window_id,
        query_normalized_pattern_id=query.query_normalized_pattern_id,
        query_market_dna_id=query.query_market_dna_id,
        similarity_method_code=query.similarity_method_code,
        similarity_method_version=query.similarity_method_version,
        feature_set_code=query.feature_set_code,
        feature_set_version=query.feature_set_version,
        top_k=query.top_k,
        candidate_count=query.candidate_count,
        returned_match_count=query.returned_match_count,
        temporal_policy=query.temporal_policy,
        configuration_hash=query.configuration_hash,
        query_hash=query.query_hash,
        status=query.status,
        elapsed_seconds=float(query.elapsed_seconds) if query.elapsed_seconds is not None else None,
        diagnostics=query.diagnostics,
        created_at=query.created_at,
    )


@router.get("/instruments", response_model=list[InstrumentResponse])
def list_instruments(session: SessionDep, symbol: str | None = None, limit: int = 100, offset: int = 0):
    return RegistryService(session).list_instruments(symbol=symbol, limit=limit, offset=offset)


@router.post("/instruments", response_model=InstrumentResponse)
def create_instrument(payload: InstrumentCreate, session: SessionDep):
    item = RegistryService(session).create_instrument(**payload.model_dump())
    session.commit()
    return item


@router.get("/instruments/{instrument_id}", response_model=InstrumentResponse)
def get_instrument(instrument_id: str, session: SessionDep):
    item = RegistryService(session).get_instrument(instrument_id)
    if item is None:
        raise _not_found("INSTRUMENT_NOT_FOUND")
    return item


@router.get("/timeframes", response_model=list[TimeframeResponse])
def list_timeframes(session: SessionDep, limit: int = 100, offset: int = 0):
    return RegistryService(session).list_timeframes(limit=limit, offset=offset)


@router.post("/timeframes", response_model=TimeframeResponse)
def create_timeframe(payload: TimeframeCreate, session: SessionDep):
    item = RegistryService(session).create_timeframe(**payload.model_dump())
    session.commit()
    return item


@router.get("/timeframes/{timeframe_id}", response_model=TimeframeResponse)
def get_timeframe(timeframe_id: str, session: SessionDep):
    item = RegistryService(session).get_timeframe(timeframe_id)
    if item is None:
        raise _not_found("TIMEFRAME_NOT_FOUND")
    return item


@router.get("/data-sources", response_model=list[DataSourceResponse])
def list_sources(session: SessionDep, limit: int = 100, offset: int = 0):
    return RegistryService(session).list_sources(limit=limit, offset=offset)


@router.post("/data-sources", response_model=DataSourceResponse)
def create_source(payload: DataSourceCreate, session: SessionDep):
    item = RegistryService(session).create_source(**payload.model_dump())
    session.commit()
    return item


@router.get("/data-sources/{source_id}", response_model=DataSourceResponse)
def get_source(source_id: str, session: SessionDep):
    item = RegistryService(session).get_source(source_id)
    if item is None:
        raise _not_found("SOURCE_NOT_FOUND")
    return item


@router.post("/data/imports/csv", response_model=ImportResponse)
async def import_csv(
    session: SessionDep,
    file: Annotated[UploadFile, File()],
    symbol: Annotated[str, Form()],
    instrument_name: Annotated[str | None, Form()] = None,
    asset_class: Annotated[str, Form()] = "other",
    exchange: Annotated[str | None, Form()] = None,
    currency: Annotated[str | None, Form()] = None,
    timezone: Annotated[str, Form()] = "UTC",
    timeframe: Annotated[str, Form()] = "M1",
    source_name: Annotated[str, Form()] = "csv",
    timeframe_seconds: Annotated[int | None, Form()] = None,
    dry_run: Annotated[bool, Form()] = False,
):
    if not file.filename or Path(file.filename).suffix.lower() not in {".csv", ".txt"}:
        raise HTTPException(status_code=415, detail={"code": "IMPORT_SCHEMA_INVALID", "message": "Only CSV files are supported."})
    settings = get_settings()
    total = 0
    with NamedTemporaryFile(delete=False, suffix=".csv") as tmp:
        tmp_path = Path(tmp.name)
        while chunk := await file.read(1024 * 1024):
            total += len(chunk)
            if total > settings.max_upload_bytes:
                tmp.close()
                tmp_path.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail={"code": "IMPORT_FILE_TOO_LARGE", "message": "Upload exceeds configured limit."})
            tmp.write(chunk)
    try:
        result = persist_csv_import(
            session,
            tmp_path,
            CsvImportMetadata(
                symbol=symbol,
                instrument_name=instrument_name,
                asset_class=asset_class,
                exchange=exchange,
                currency=currency,
                timezone=timezone,
                timeframe=timeframe,
                source_name=source_name,
                timeframe_seconds=timeframe_seconds,
                dry_run=dry_run,
            ),
        )
        return _import_response(result.data_import)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "IMPORT_SCHEMA_INVALID", "message": str(exc)}) from exc
    finally:
        tmp_path.unlink(missing_ok=True)


@router.get("/data/imports", response_model=list[ImportResponse])
def list_imports(
    session: SessionDep,
    status: str | None = None,
    instrument_id: str | None = None,
    timeframe_id: str | None = None,
    source_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
):
    query = select(DataImport).order_by(DataImport.created_at.desc()).limit(limit).offset(offset)
    if status:
        query = query.where(DataImport.status == status)
    if instrument_id:
        query = query.where(DataImport.instrument_id == instrument_id)
    if timeframe_id:
        query = query.where(DataImport.timeframe_id == timeframe_id)
    if source_id:
        query = query.where(DataImport.source_id == source_id)
    return [_import_response(item) for item in session.scalars(query)]


@router.get("/data/imports/{import_id}", response_model=ImportResponse)
def get_import(import_id: str, session: SessionDep):
    item = session.get(DataImport, import_id)
    if item is None:
        raise _not_found("IMPORT_NOT_FOUND")
    return _import_response(item)


@router.get("/data/imports/{import_id}/issues", response_model=list[ImportIssueResponse])
def get_import_issues(
    import_id: str,
    session: SessionDep,
    severity: str | None = None,
    issue_type: str | None = None,
    row_number: int | None = None,
    limit: int = 100,
    offset: int = 0,
):
    query = select(DataImportIssue).where(DataImportIssue.import_id == import_id).limit(limit).offset(offset)
    if severity:
        query = query.where(DataImportIssue.severity == severity)
    if issue_type:
        query = query.where(DataImportIssue.issue_type == issue_type)
    if row_number:
        query = query.where(DataImportIssue.row_number == row_number)
    return list(session.scalars(query.order_by(DataImportIssue.row_number)))


@router.post("/windows/builds", response_model=WindowBuildResponse)
def create_window_build(payload: WindowBuildRequest, session: SessionDep):
    estimated = 0
    for length in payload.window_lengths:
        estimated += max(0, length)
    if estimated > get_settings().max_sync_window_candidates:
        raise HTTPException(status_code=413, detail={"code": "WINDOW_BUILD_TOO_LARGE", "message": "Build exceeds synchronous limit."})
    try:
        result = WindowBuildService(session).build(
            instrument_id=payload.instrument_id,
            timeframe_id=payload.timeframe_id,
            window_lengths=payload.window_lengths,
            stride=payload.stride,
            mode=payload.mode,
            window_version=payload.window_version,
            start_timestamp=payload.start_timestamp,
            end_timestamp=payload.end_timestamp,
            quality_policy=WindowQualityPolicy(**payload.quality_policy.model_dump()),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": str(exc), "message": str(exc)}) from exc
    return _build_response(result.build)


@router.get("/windows/builds", response_model=list[WindowBuildResponse])
def list_window_builds(session: SessionDep, limit: int = 100, offset: int = 0, status: str | None = None):
    query = select(WindowBuild).order_by(WindowBuild.created_at.desc()).limit(limit).offset(offset)
    if status:
        query = query.where(WindowBuild.status == status)
    return [_build_response(item) for item in session.scalars(query)]


@router.get("/windows/builds/{build_id}", response_model=WindowBuildResponse)
def get_window_build(build_id: str, session: SessionDep):
    item = session.get(WindowBuild, build_id)
    if item is None:
        raise _not_found("WINDOW_BUILD_NOT_FOUND")
    return _build_response(item)


@router.get("/windows", response_model=list[PatternWindowResponse])
def list_windows(
    session: SessionDep,
    instrument_id: str | None = None,
    timeframe_id: str | None = None,
    window_length: int | None = None,
    window_version: str | None = None,
    source_data_hash: str | None = None,
    limit: int = 100,
    offset: int = 0,
):
    query = select(PatternWindow).order_by(PatternWindow.end_timestamp).limit(limit).offset(offset)
    if instrument_id:
        query = query.where(PatternWindow.instrument_id == instrument_id)
    if timeframe_id:
        query = query.where(PatternWindow.timeframe_id == timeframe_id)
    if window_length:
        query = query.where(PatternWindow.window_length == window_length)
    if window_version:
        query = query.where(PatternWindow.window_version == window_version)
    if source_data_hash:
        query = query.where(PatternWindow.source_data_hash == source_data_hash)
    return list(session.scalars(query))


@router.get("/windows/{window_id}", response_model=PatternWindowResponse)
def get_window(window_id: str, session: SessionDep):
    item = session.get(PatternWindow, window_id)
    if item is None:
        raise _not_found("WINDOW_NOT_FOUND")
    return item


@router.get("/windows/{window_id}/bars", response_model=list[PriceBarResponse])
def get_window_bars(window_id: str, session: SessionDep):
    item = session.get(PatternWindow, window_id)
    if item is None:
        raise _not_found("WINDOW_NOT_FOUND")
    return list_window_bars(session, item)


@router.get("/normalization/methods", response_model=list[NormalizationMethodResponse])
def normalization_methods():
    return [method.__dict__ for method in list_methods()]


@router.post("/normalization/builds", response_model=NormalizationBuildResponse)
def create_normalization_build(payload: NormalizationBuildRequest, session: SessionDep):
    try:
        result = NormalizationBuildService(session).build(
            normalization_method=payload.normalization_method,
            normalization_version=payload.normalization_version,
            resampling_method=payload.resampling_method,
            resample_points=payload.resample_points,
            mode=payload.mode,
            instrument_id=payload.instrument_id,
            timeframe_id=payload.timeframe_id,
            window_length=payload.window_length,
            start_timestamp=payload.start_timestamp,
            end_timestamp=payload.end_timestamp,
            source_window_version=payload.source_window_version,
            policies=NormalizationPolicies(**payload.policies.model_dump()),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": str(exc), "message": str(exc)}) from exc
    return _normalization_build_response(result.build)


@router.get("/normalization/builds", response_model=list[NormalizationBuildResponse])
def list_normalization_builds(session: SessionDep, limit: int = 100, offset: int = 0, status: str | None = None):
    query = select(NormalizationBuild).order_by(NormalizationBuild.created_at.desc()).limit(limit).offset(offset)
    if status:
        query = query.where(NormalizationBuild.status == status)
    return [_normalization_build_response(item) for item in session.scalars(query)]


@router.get("/normalization/builds/{build_id}", response_model=NormalizationBuildResponse)
def get_normalization_build(build_id: str, session: SessionDep):
    item = session.get(NormalizationBuild, build_id)
    if item is None:
        raise _not_found("NORMALIZATION_BUILD_NOT_FOUND")
    return _normalization_build_response(item)


@router.get("/normalized-patterns", response_model=list[NormalizedPatternResponse])
def list_normalized_patterns(
    session: SessionDep,
    normalization_method: str | None = None,
    resample_points: int | None = None,
    pattern_window_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
):
    query = select(NormalizedPattern).order_by(NormalizedPattern.created_at).limit(limit).offset(offset)
    if normalization_method:
        query = query.where(NormalizedPattern.normalization_method == normalization_method)
    if resample_points:
        query = query.where(NormalizedPattern.resample_points == resample_points)
    if pattern_window_id:
        query = query.where(NormalizedPattern.pattern_window_id == pattern_window_id)
    return list(session.scalars(query))


@router.get("/normalized-patterns/{normalized_pattern_id}", response_model=NormalizedPatternResponse)
def get_normalized_pattern(normalized_pattern_id: str, session: SessionDep):
    item = session.get(NormalizedPattern, normalized_pattern_id)
    if item is None:
        raise _not_found("NORMALIZED_PATTERN_NOT_FOUND")
    return item


@router.get("/normalized-patterns/{normalized_pattern_id}/values", response_model=NormalizedPatternValuesResponse)
def get_normalized_pattern_values(normalized_pattern_id: str, session: SessionDep):
    item = session.get(NormalizedPattern, normalized_pattern_id)
    if item is None:
        raise _not_found("NORMALIZED_PATTERN_NOT_FOUND")
    return NormalizedPatternValuesResponse(
        normalized_pattern_id=item.id,
        schema_=item.channel_schema["schema"],
        channels=item.channel_schema["channels"],
        points=item.channel_schema["points"],
        values=item.normalized_values,
    )


@router.get("/normalized-patterns/{normalized_pattern_id}/diagnostics")
def get_normalized_pattern_diagnostics(normalized_pattern_id: str, session: SessionDep):
    item = session.get(NormalizedPattern, normalized_pattern_id)
    if item is None:
        raise _not_found("NORMALIZED_PATTERN_NOT_FOUND")
    return item.diagnostics


@router.get("/features/definitions", response_model=list[FeatureDefinitionResponse])
def feature_definitions():
    return [definition.__dict__ for definition in list_feature_definitions()]


@router.get("/features/sets", response_model=list[FeatureSetResponse])
def feature_sets():
    return [item.__dict__ for item in list_feature_sets()]


@router.get("/features/sets/{feature_set_code}", response_model=FeatureSetResponse)
def feature_set_detail(feature_set_code: str):
    try:
        return get_feature_set(feature_set_code).__dict__
    except ValueError as exc:
        raise _not_found(str(exc)) from exc


@router.post("/features/builds", response_model=FeatureBuildResponse)
def create_feature_build(payload: FeatureBuildRequest, session: SessionDep):
    try:
        result = FeatureBuildService(session).build(
            feature_set_code=payload.feature_set_code,
            mode=payload.mode,
            instrument_id=payload.instrument_id,
            timeframe_id=payload.timeframe_id,
            window_length=payload.window_length,
            start_timestamp=payload.start_timestamp,
            end_timestamp=payload.end_timestamp,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": str(exc), "message": str(exc)}) from exc
    return _feature_build_response(result.build)


@router.get("/features/builds", response_model=list[FeatureBuildResponse])
def list_feature_builds(session: SessionDep, limit: int = 100, offset: int = 0, status: str | None = None):
    query = select(FeatureBuild).order_by(FeatureBuild.created_at.desc()).limit(limit).offset(offset)
    if status:
        query = query.where(FeatureBuild.status == status)
    return [_feature_build_response(item) for item in session.scalars(query)]


@router.get("/features/builds/{build_id}", response_model=FeatureBuildResponse)
def get_feature_build(build_id: str, session: SessionDep):
    item = session.get(FeatureBuild, build_id)
    if item is None:
        raise _not_found("FEATURE_BUILD_NOT_FOUND")
    return _feature_build_response(item)


@router.get("/market-dna", response_model=list[MarketDNAResponse])
def list_market_dna(
    session: SessionDep,
    feature_set_code: str | None = None,
    normalized_pattern_id: str | None = None,
    pattern_window_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
):
    query = select(MarketDNA).order_by(MarketDNA.created_at).limit(limit).offset(offset)
    if feature_set_code:
        query = query.where(MarketDNA.feature_set_code == feature_set_code)
    if normalized_pattern_id:
        query = query.where(MarketDNA.normalized_pattern_id == normalized_pattern_id)
    if pattern_window_id:
        query = query.where(MarketDNA.pattern_window_id == pattern_window_id)
    return list(session.scalars(query))


@router.get("/market-dna/{market_dna_id}", response_model=MarketDNAResponse)
def get_market_dna(market_dna_id: str, session: SessionDep):
    item = session.get(MarketDNA, market_dna_id)
    if item is None:
        raise _not_found("MARKET_DNA_NOT_FOUND")
    return item


@router.get("/market-dna/{market_dna_id}/values", response_model=MarketDNAValuesResponse)
def get_market_dna_values(market_dna_id: str, session: SessionDep):
    item = session.get(MarketDNA, market_dna_id)
    if item is None:
        raise _not_found("MARKET_DNA_NOT_FOUND")
    return MarketDNAValuesResponse(
        market_dna_id=item.id,
        ordered_features=item.feature_vector["ordered_features"],
        values=item.feature_vector["values"],
        availability_mask=item.feature_vector["availability_mask"],
        feature_values=item.feature_values,
    )


@router.get("/market-dna/{market_dna_id}/diagnostics")
def get_market_dna_diagnostics(market_dna_id: str, session: SessionDep):
    item = session.get(MarketDNA, market_dna_id)
    if item is None:
        raise _not_found("MARKET_DNA_NOT_FOUND")
    return item.diagnostics


@router.get("/context/producers", response_model=list[ContextProducerResponse])
def context_producers():
    return [producer.__dict__ for producer in list_context_producers()]


@router.get("/context/dimensions", response_model=list[ContextDimensionResponse])
def context_dimensions():
    return list_context_dimensions()


@router.post("/context/builds", response_model=ContextBuildResponse)
def create_context_build(payload: ContextBuildRequest, session: SessionDep):
    try:
        result = ContextBuildService(session).build(
            context_producer_code=payload.context_producer_code,
            feature_set_code=payload.feature_set_code,
            mode=payload.mode,
            instrument_id=payload.instrument_id,
            timeframe_id=payload.timeframe_id,
            window_length=payload.window_length,
            start_timestamp=payload.start_timestamp,
            end_timestamp=payload.end_timestamp,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": str(exc), "message": str(exc), "details": {}}) from exc
    return _context_build_response(result.build)


@router.get("/context/builds", response_model=list[ContextBuildResponse])
def list_context_builds(session: SessionDep, limit: int = 100, offset: int = 0, status: str | None = None):
    query = select(ContextBuild).order_by(ContextBuild.created_at.desc()).limit(limit).offset(offset)
    if status:
        query = query.where(ContextBuild.status == status)
    return [_context_build_response(item) for item in session.scalars(query)]


@router.get("/context/builds/{build_id}", response_model=ContextBuildResponse)
def get_context_build(build_id: str, session: SessionDep):
    item = session.get(ContextBuild, build_id)
    if item is None:
        raise _not_found("CONTEXT_BUILD_NOT_FOUND")
    return _context_build_response(item)


@router.get("/market-contexts", response_model=list[MarketContextResponse])
def list_market_contexts(
    session: SessionDep,
    instrument_id: str | None = None,
    timeframe_id: str | None = None,
    window_length: int | None = None,
    context_producer_code: str | None = None,
    context_producer_version: str | None = None,
    trend_state: str | None = None,
    volatility_state: str | None = None,
    volatility_phase_state: str | None = None,
    persistence_state: str | None = None,
    activity_state: str | None = None,
    shock_state: str | None = None,
    market_phase_state: str | None = None,
    multi_resolution_state: str | None = None,
    context_family_code: str | None = None,
    composite_context_code: str | None = None,
    minimum_composite_confidence: float | None = None,
    minimum_completeness: float | None = None,
    quality_flag: str | None = None,
    limit: int = 100,
    offset: int = 0,
):
    query = select(MarketContext).join(PatternWindow, PatternWindow.id == MarketContext.pattern_window_id)
    if instrument_id:
        query = query.where(PatternWindow.instrument_id == instrument_id)
    if timeframe_id:
        query = query.where(PatternWindow.timeframe_id == timeframe_id)
    if window_length:
        query = query.where(PatternWindow.window_length == window_length)
    filters = {
        MarketContext.context_producer_code: context_producer_code,
        MarketContext.context_producer_version: context_producer_version,
        MarketContext.trend_state: trend_state,
        MarketContext.volatility_state: volatility_state,
        MarketContext.volatility_phase_state: volatility_phase_state,
        MarketContext.persistence_state: persistence_state,
        MarketContext.activity_state: activity_state,
        MarketContext.shock_state: shock_state,
        MarketContext.market_phase_state: market_phase_state,
        MarketContext.multi_resolution_state: multi_resolution_state,
        MarketContext.context_family_code: context_family_code,
        MarketContext.composite_context_code: composite_context_code,
    }
    for column, value in filters.items():
        if value:
            query = query.where(column == value)
    if minimum_composite_confidence is not None:
        query = query.where(MarketContext.composite_confidence >= minimum_composite_confidence)
    if minimum_completeness is not None:
        query = query.where(MarketContext.completeness_score >= minimum_completeness)
    rows = list(session.scalars(query.order_by(MarketContext.created_at).limit(limit).offset(offset)))
    if quality_flag:
        rows = [row for row in rows if quality_flag in row.quality_flags]
    return rows


@router.get("/market-contexts/{market_context_id}", response_model=MarketContextResponse)
def get_market_context(market_context_id: str, session: SessionDep):
    item = session.get(MarketContext, market_context_id)
    if item is None:
        raise _not_found("MARKET_CONTEXT_NOT_FOUND")
    return item


@router.get("/market-contexts/{market_context_id}/dimensions")
def get_market_context_dimensions(market_context_id: str, session: SessionDep):
    item = session.get(MarketContext, market_context_id)
    if item is None:
        raise _not_found("MARKET_CONTEXT_NOT_FOUND")
    return {
        "states": {
            "trend": item.trend_state,
            "volatility": item.volatility_state,
            "volatility_phase": item.volatility_phase_state,
            "persistence": item.persistence_state,
            "activity": item.activity_state,
            "shock": item.shock_state,
            "market_phase": item.market_phase_state,
            "multi_resolution": item.multi_resolution_state,
        },
        "scores": item.dimension_scores,
    }


@router.get("/market-contexts/{market_context_id}/explanation")
def get_market_context_explanation(market_context_id: str, session: SessionDep):
    item = session.get(MarketContext, market_context_id)
    if item is None:
        raise _not_found("MARKET_CONTEXT_NOT_FOUND")
    return {"evidence": item.evidence, "opposing_evidence": item.opposing_evidence, "quality_flags": item.quality_flags}


@router.get("/market-contexts/{market_context_id}/diagnostics")
def get_market_context_diagnostics(market_context_id: str, session: SessionDep):
    item = session.get(MarketContext, market_context_id)
    if item is None:
        raise _not_found("MARKET_CONTEXT_NOT_FOUND")
    return item.diagnostics


@router.get("/market-contexts/{market_context_id}/multi-resolution")
def get_market_context_multi_resolution(market_context_id: str, session: SessionDep):
    item = session.get(MarketContext, market_context_id)
    if item is None:
        raise _not_found("MARKET_CONTEXT_NOT_FOUND")
    return item.multi_resolution_links


@router.get("/outcomes/definitions", response_model=list[OutcomeDefinitionResponse])
def outcome_definitions():
    return [item.__dict__ for item in list_outcome_definitions()]


@router.get("/outcomes/sets", response_model=list[OutcomeSetResponse])
def outcome_sets():
    return [item.__dict__ for item in list_outcome_sets()]


@router.get("/outcomes/sets/{outcome_set_code}", response_model=OutcomeSetResponse)
def outcome_set_detail(outcome_set_code: str):
    try:
        return get_outcome_set(outcome_set_code).__dict__
    except ValueError as exc:
        raise _not_found(str(exc)) from exc


@router.post("/outcomes/builds", response_model=OutcomeBuildResponse)
def create_outcome_build(payload: OutcomeBuildRequest, session: SessionDep):
    try:
        result = OutcomeBuildService(session).build(
            outcome_set_code=payload.outcome_set_code,
            horizons=payload.horizons,
            mode=payload.mode,
            instrument_id=payload.instrument_id,
            timeframe_id=payload.timeframe_id,
            window_length=payload.window_length,
            start_timestamp=payload.start_timestamp,
            end_timestamp=payload.end_timestamp,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": str(exc), "message": str(exc), "details": {}}) from exc
    return _outcome_build_response(result.build)


@router.get("/outcomes/builds", response_model=list[OutcomeBuildResponse])
def list_outcome_builds(session: SessionDep, limit: int = 100, offset: int = 0, status: str | None = None):
    query = select(OutcomeBuild).order_by(OutcomeBuild.created_at.desc()).limit(limit).offset(offset)
    if status:
        query = query.where(OutcomeBuild.status == status)
    return [_outcome_build_response(item) for item in session.scalars(query)]


@router.get("/outcomes/builds/{build_id}", response_model=OutcomeBuildResponse)
def get_outcome_build(build_id: str, session: SessionDep):
    item = session.get(OutcomeBuild, build_id)
    if item is None:
        raise _not_found("OUTCOME_BUILD_NOT_FOUND")
    return _outcome_build_response(item)


def _outcome_query(
    instrument_id: str | None = None,
    timeframe_id: str | None = None,
    window_length: int | None = None,
    horizon_bars: int | None = None,
    is_complete: bool | None = None,
    direction_class: str | None = None,
    continuation_reversal_class: str | None = None,
    first_barrier_hit: str | None = None,
):
    query = select(OutcomeObservation)
    filters = {
        OutcomeObservation.instrument_id: instrument_id,
        OutcomeObservation.timeframe_id: timeframe_id,
        OutcomeObservation.window_length: window_length,
        OutcomeObservation.horizon_bars: horizon_bars,
        OutcomeObservation.direction_class: direction_class,
        OutcomeObservation.continuation_reversal_class: continuation_reversal_class,
        OutcomeObservation.first_barrier_hit: first_barrier_hit,
    }
    for column, value in filters.items():
        if value is not None:
            query = query.where(column == value)
    if is_complete is not None:
        query = query.where(OutcomeObservation.is_complete.is_(is_complete))
    return query


@router.get("/outcome-observations", response_model=list[OutcomeObservationResponse])
def list_outcome_observations(
    session: SessionDep,
    instrument_id: str | None = None,
    timeframe_id: str | None = None,
    window_length: int | None = None,
    horizon_bars: int | None = None,
    is_complete: bool | None = None,
    direction_class: str | None = None,
    continuation_reversal_class: str | None = None,
    first_barrier_hit: str | None = None,
    quality_flag: str | None = None,
    limit: int = 100,
    offset: int = 0,
):
    query = _outcome_query(
        instrument_id,
        timeframe_id,
        window_length,
        horizon_bars,
        is_complete,
        direction_class,
        continuation_reversal_class,
        first_barrier_hit,
    )
    rows = list(session.scalars(query.order_by(OutcomeObservation.window_end_timestamp).limit(limit).offset(offset)))
    if quality_flag:
        rows = [row for row in rows if quality_flag in row.quality_flags]
    return rows


@router.get("/outcome-observations/{outcome_id}", response_model=OutcomeObservationResponse)
def get_outcome_observation(outcome_id: str, session: SessionDep):
    item = session.get(OutcomeObservation, outcome_id)
    if item is None:
        raise _not_found("OUTCOME_OBSERVATION_NOT_FOUND")
    return item


@router.get("/outcome-observations/{outcome_id}/values", response_model=OutcomeValuesResponse)
def get_outcome_values(outcome_id: str, session: SessionDep):
    item = session.get(OutcomeObservation, outcome_id)
    if item is None:
        raise _not_found("OUTCOME_OBSERVATION_NOT_FOUND")
    return OutcomeValuesResponse(outcome_observation_id=item.id, scalar_values=item.scalar_values)


@router.get("/outcome-observations/{outcome_id}/path", response_model=ForwardPathResponse)
def get_outcome_path(outcome_id: str, session: SessionDep):
    item = session.get(OutcomeObservation, outcome_id)
    if item is None:
        raise _not_found("OUTCOME_OBSERVATION_NOT_FOUND")
    return ForwardPathResponse(outcome_observation_id=item.id, forward_path=item.forward_path)


@router.get("/outcome-observations/{outcome_id}/barriers")
def get_outcome_barriers(outcome_id: str, session: SessionDep):
    item = session.get(OutcomeObservation, outcome_id)
    if item is None:
        raise _not_found("OUTCOME_OBSERVATION_NOT_FOUND")
    return item.barrier_results


@router.get("/outcome-observations/{outcome_id}/diagnostics")
def get_outcome_diagnostics(outcome_id: str, session: SessionDep):
    item = session.get(OutcomeObservation, outcome_id)
    if item is None:
        raise _not_found("OUTCOME_OBSERVATION_NOT_FOUND")
    return item.diagnostics


@router.get("/windows/{window_id}/outcomes", response_model=list[OutcomeObservationResponse])
def get_window_outcomes(
    window_id: str,
    session: SessionDep,
    horizon_bars: int | None = None,
    is_complete: bool | None = None,
    limit: int = 100,
    offset: int = 0,
):
    if session.get(PatternWindow, window_id) is None:
        raise _not_found("WINDOW_NOT_FOUND")
    query = select(OutcomeObservation).where(OutcomeObservation.pattern_window_id == window_id)
    if horizon_bars is not None:
        query = query.where(OutcomeObservation.horizon_bars == horizon_bars)
    if is_complete is not None:
        query = query.where(OutcomeObservation.is_complete.is_(is_complete))
    return list(session.scalars(query.order_by(OutcomeObservation.horizon_bars).limit(limit).offset(offset)))


@router.get("/similarity/methods", response_model=list[SimilarityMethodResponse])
def similarity_methods():
    return [item.__dict__ for item in list_similarity_methods()]


@router.get("/similarity/methods/{method_code}", response_model=SimilarityMethodResponse)
def similarity_method_detail(method_code: str):
    try:
        return get_similarity_method(method_code).__dict__
    except ValueError as exc:
        raise _not_found(str(exc)) from exc


@router.post("/similarity/search", response_model=SimilarityQueryResponse)
def create_similarity_search(payload: SimilaritySearchRequest, session: SessionDep):
    try:
        result = SimilaritySearchService(session).search(**payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": str(exc), "message": str(exc), "details": {}}) from exc
    return _similarity_query_response(result.query)


@router.get("/similarity/queries", response_model=list[SimilarityQueryResponse])
def list_similarity_queries(session: SessionDep, limit: int = 100, offset: int = 0, status: str | None = None):
    query = select(SimilarityQuery).order_by(SimilarityQuery.created_at.desc()).limit(limit).offset(offset)
    if status:
        query = query.where(SimilarityQuery.status == status)
    return [_similarity_query_response(item) for item in session.scalars(query)]


@router.get("/similarity/queries/{query_id}", response_model=SimilarityQueryResponse)
def get_similarity_query(query_id: str, session: SessionDep):
    item = session.get(SimilarityQuery, query_id)
    if item is None:
        raise _not_found("SIMILARITY_QUERY_NOT_FOUND")
    return _similarity_query_response(item)


@router.get("/similarity/queries/{query_id}/matches", response_model=list[SimilarityMatchResponse])
def get_similarity_matches(query_id: str, session: SessionDep, limit: int = 100, offset: int = 0):
    if session.get(SimilarityQuery, query_id) is None:
        raise _not_found("SIMILARITY_QUERY_NOT_FOUND")
    query = (
        select(SimilarityMatch)
        .where(SimilarityMatch.query_id == query_id)
        .order_by(SimilarityMatch.rank)
        .limit(limit)
        .offset(offset)
    )
    return list(session.scalars(query))


@router.get("/windows/{window_id}/similar", response_model=list[SimilarityMatchResponse])
def get_window_similar(
    window_id: str,
    session: SessionDep,
    method: str = "market_analogue_v1",
    top_k: int = 20,
    temporal_policy: str = "historical_only",
):
    try:
        result = SimilaritySearchService(session).search(
            query_window_id=window_id,
            similarity_method_code=method,
            top_k=top_k,
            temporal_policy=temporal_policy,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": str(exc), "message": str(exc), "details": {}}) from exc
    return list(
        session.scalars(
            select(SimilarityMatch).where(SimilarityMatch.query_id == result.query.id).order_by(SimilarityMatch.rank)
        )
    )


@router.get("/experiments/definitions", response_model=list[ExperimentDefinitionResponse])
def experiment_definitions():
    return [item.__dict__ for item in list_experiment_definitions()]


@router.get("/validation/methods", response_model=list[ValidationMethodResponse])
def validation_methods():
    return [item.__dict__ for item in list_validation_methods()]


@router.get("/validation/baselines", response_model=list[BaselineMethodResponse])
def validation_baselines():
    return [item.__dict__ for item in list_baseline_methods()]


@router.get("/validation/metrics", response_model=list[MetricDefinitionResponse])
def validation_metrics():
    return [item.__dict__ for item in list_metric_definitions()]


@router.get("/validation/weighting")
def validation_weighting_methods():
    return [item.__dict__ for item in list_weighting_methods()]


@router.post("/experiments/runs", response_model=ExperimentRunResponse)
def create_experiment_run(payload: ExperimentCreateRequest, session: SessionDep):
    try:
        result = ValidationExperimentService(session).run(payload.configuration)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": str(exc), "message": str(exc), "details": {}}) from exc
    return result.run


@router.get("/experiments/runs", response_model=list[ExperimentRunResponse])
def list_experiment_runs(session: SessionDep, limit: int = 100, offset: int = 0, status: str | None = None):
    query = select(ExperimentRun).order_by(ExperimentRun.created_at.desc()).limit(limit).offset(offset)
    if status:
        query = query.where(ExperimentRun.status == status)
    return list(session.scalars(query))


@router.get("/experiments/runs/{run_id}", response_model=ExperimentRunResponse)
def get_experiment_run(run_id: str, session: SessionDep):
    item = session.get(ExperimentRun, run_id)
    if item is None:
        raise _not_found("EXPERIMENT_NOT_FOUND")
    return item


@router.get("/experiments/runs/{run_id}/folds", response_model=list[ExperimentFoldResponse])
def get_experiment_folds(run_id: str, session: SessionDep):
    if session.get(ExperimentRun, run_id) is None:
        raise _not_found("EXPERIMENT_NOT_FOUND")
    return list(session.scalars(select(ExperimentFold).where(ExperimentFold.experiment_run_id == run_id).order_by(ExperimentFold.fold_number)))


@router.get("/experiments/runs/{run_id}/evaluations", response_model=list[QueryEvaluationResponse])
def get_experiment_evaluations(run_id: str, session: SessionDep, limit: int = 100, offset: int = 0):
    if session.get(ExperimentRun, run_id) is None:
        raise _not_found("EXPERIMENT_NOT_FOUND")
    return list(
        session.scalars(
            select(QueryEvaluation)
            .where(QueryEvaluation.experiment_run_id == run_id)
            .order_by(QueryEvaluation.created_at)
            .limit(limit)
            .offset(offset)
        )
    )


@router.get("/experiments/runs/{run_id}/metrics", response_model=list[ExperimentMetricResponse])
def get_experiment_metrics(run_id: str, session: SessionDep):
    if session.get(ExperimentRun, run_id) is None:
        raise _not_found("EXPERIMENT_NOT_FOUND")
    return list(session.scalars(select(ExperimentMetric).where(ExperimentMetric.experiment_run_id == run_id).order_by(ExperimentMetric.metric_code)))


@router.get("/experiments/runs/{run_id}/report")
def get_experiment_report(run_id: str, session: SessionDep):
    try:
        return {"report": ValidationExperimentService(session).generate_report(run_id)}
    except ValueError as exc:
        raise _not_found(str(exc)) from exc


@router.get("/diagnostics/definitions", response_model=list[DiagnosticDefinitionResponse])
def diagnostic_definitions():
    return [item.__dict__ for item in list_diagnostic_definitions()]


@router.get("/diagnostics/scaling-methods", response_model=list[DiagnosticMethodResponse])
def diagnostic_scaling_methods():
    return [item.__dict__ for item in list_scaling_methods()]


@router.get("/diagnostics/availability-policies")
def diagnostic_availability_policies():
    return [item.__dict__ for item in list_availability_policies()]


@router.get("/diagnostics/weight-configurations")
def diagnostic_weight_configurations():
    return [item.__dict__ for item in list_weight_configurations()]


@router.post("/diagnostics/experiments", response_model=ExperimentRunResponse)
def create_diagnostic_experiment(payload: DiagnosticExperimentCreateRequest, session: SessionDep):
    try:
        return RetrievalDiagnosticService(session).run(payload.configuration)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": str(exc), "message": str(exc), "details": {}}) from exc


@router.get("/diagnostics/experiments", response_model=list[ExperimentRunResponse])
def list_diagnostic_experiments(session: SessionDep, limit: int = 100, offset: int = 0):
    query = (
        select(ExperimentRun)
        .where(ExperimentRun.experiment_version == "diagnostic_v1")
        .order_by(ExperimentRun.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(session.scalars(query))


@router.get("/diagnostics/experiments/{experiment_id}", response_model=ExperimentRunResponse)
def get_diagnostic_experiment(experiment_id: str, session: SessionDep):
    run = session.get(ExperimentRun, experiment_id)
    if run is None or run.experiment_version != "diagnostic_v1":
        raise _not_found("DIAGNOSTIC_EXPERIMENT_NOT_FOUND")
    return run


def _diagnostic_artifact_payload(experiment_id: str, artifact_type: str, session: SessionDep):
    if session.get(ExperimentRun, experiment_id) is None:
        raise _not_found("DIAGNOSTIC_EXPERIMENT_NOT_FOUND")
    artifact = session.scalar(
        select(DiagnosticArtifact)
        .where(
            DiagnosticArtifact.experiment_run_id == experiment_id,
            DiagnosticArtifact.artifact_type == artifact_type,
        )
        .order_by(DiagnosticArtifact.created_at.desc())
    )
    if artifact is None:
        raise _not_found("DIAGNOSTIC_ARTIFACT_NOT_FOUND")
    return artifact.payload


@router.get("/diagnostics/experiments/{experiment_id}/feature-distributions")
def get_diagnostic_feature_distributions(experiment_id: str, session: SessionDep):
    return _diagnostic_artifact_payload(experiment_id, "FEATURE_DISTRIBUTION", session)


@router.get("/diagnostics/experiments/{experiment_id}/redundancy")
def get_diagnostic_redundancy(experiment_id: str, session: SessionDep):
    return _diagnostic_artifact_payload(experiment_id, "CORRELATION_MATRIX", session)


@router.get("/diagnostics/experiments/{experiment_id}/distance-outcome")
def get_diagnostic_distance_outcome(experiment_id: str, session: SessionDep):
    return _diagnostic_artifact_payload(experiment_id, "DISTANCE_OUTCOME_CURVE", session)


@router.get("/diagnostics/experiments/{experiment_id}/similarity-deciles")
def get_diagnostic_similarity_deciles(experiment_id: str, session: SessionDep):
    return _diagnostic_artifact_payload(experiment_id, "DISTANCE_OUTCOME_CURVE", session)


@router.get("/diagnostics/experiments/{experiment_id}/neighbour-dispersion")
def get_diagnostic_neighbour_dispersion(experiment_id: str, session: SessionDep):
    return _diagnostic_artifact_payload(experiment_id, "DISTANCE_OUTCOME_CURVE", session)


@router.get("/diagnostics/experiments/{experiment_id}/episode-concentration")
def get_diagnostic_episode_concentration(experiment_id: str, session: SessionDep):
    return _diagnostic_artifact_payload(experiment_id, "EPISODE_CONCENTRATION", session)


@router.get("/diagnostics/experiments/{experiment_id}/context-compatibility")
def get_diagnostic_context_compatibility(experiment_id: str, session: SessionDep):
    return _diagnostic_artifact_payload(experiment_id, "EPISODE_CONCENTRATION", session)


@router.get("/diagnostics/experiments/{experiment_id}/window-horizon")
def get_diagnostic_window_horizon(experiment_id: str, session: SessionDep):
    return _diagnostic_artifact_payload(experiment_id, "WINDOW_HORIZON_MATRIX", session)


@router.get("/diagnostics/experiments/{experiment_id}/artifacts", response_model=list[DiagnosticArtifactResponse])
def get_diagnostic_artifacts(experiment_id: str, session: SessionDep, limit: int = 100):
    if session.get(ExperimentRun, experiment_id) is None:
        raise _not_found("DIAGNOSTIC_EXPERIMENT_NOT_FOUND")
    return list(
        session.scalars(
            select(DiagnosticArtifact)
            .where(DiagnosticArtifact.experiment_run_id == experiment_id)
            .order_by(DiagnosticArtifact.created_at)
            .limit(limit)
        )
    )


@router.get("/diagnostics/experiments/{experiment_id}/report")
def get_diagnostic_report(experiment_id: str, session: SessionDep):
    payload = _diagnostic_artifact_payload(experiment_id, "DIAGNOSTIC_REPORT", session)
    return {"report": payload["report"]}


@router.get("/studies/definitions", response_model=list[StudyDefinitionResponse])
def study_definitions():
    return [item.__dict__ for item in list_study_definitions()]


@router.post("/studies", response_model=StudyManifestResponse)
def create_study(payload: StudyCreateRequest, session: SessionDep):
    try:
        return MultiAssetStudyService(session).create(payload.configuration)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": str(exc), "message": str(exc), "details": {}}) from exc


@router.get("/studies", response_model=list[StudyManifestResponse])
def list_studies(session: SessionDep, limit: int = 100, offset: int = 0):
    return list(session.scalars(select(StudyManifest).order_by(StudyManifest.created_at.desc()).limit(limit).offset(offset)))


@router.get("/studies/{study_id}", response_model=StudyManifestResponse)
def get_study(study_id: str, session: SessionDep):
    study = session.get(StudyManifest, study_id)
    if study is None:
        raise _not_found("STUDY_NOT_FOUND")
    return study


@router.get("/studies/{study_id}/datasets", response_model=list[StudyDatasetEntryResponse])
def get_study_datasets(study_id: str, session: SessionDep):
    if session.get(StudyManifest, study_id) is None:
        raise _not_found("STUDY_NOT_FOUND")
    return list(session.scalars(select(StudyDatasetEntry).where(StudyDatasetEntry.study_id == study_id)))


@router.get("/studies/{study_id}/preflight", response_model=list[StudyPreflightResponse])
def get_study_preflight(study_id: str, session: SessionDep):
    if session.get(StudyManifest, study_id) is None:
        raise _not_found("STUDY_NOT_FOUND")
    return list(session.scalars(select(StudyPreflight).where(StudyPreflight.study_id == study_id)))


@router.get("/studies/{study_id}/episodes", response_model=list[StudyEpisodeResponse])
def get_study_episodes(study_id: str, session: SessionDep, limit: int = 500, offset: int = 0):
    if session.get(StudyManifest, study_id) is None:
        raise _not_found("STUDY_NOT_FOUND")
    return list(
        session.scalars(
            select(StudyEpisode)
            .where(StudyEpisode.study_id == study_id)
            .order_by(StudyEpisode.episode_start)
            .limit(limit)
            .offset(offset)
        )
    )


@router.get("/studies/{study_id}/arms", response_model=list[StudyArmResponse])
def get_study_arms(study_id: str, session: SessionDep):
    if session.get(StudyManifest, study_id) is None:
        raise _not_found("STUDY_NOT_FOUND")
    return list(session.scalars(select(StudyArm).where(StudyArm.study_id == study_id).order_by(StudyArm.period_role, StudyArm.arm_code)))


@router.post("/studies/{study_id}/run-pilot", response_model=StudyManifestResponse)
def run_study_pilot(study_id: str, session: SessionDep):
    return MultiAssetStudyService(session).run_pilot(study_id)


@router.post("/studies/{study_id}/run-validation", response_model=StudyManifestResponse)
def run_study_validation(study_id: str, session: SessionDep):
    return MultiAssetStudyService(session).run_validation(study_id)


@router.post("/studies/{study_id}/lock-final-test", response_model=StudyManifestResponse)
def lock_study_final_test(study_id: str, session: SessionDep, payload: StudyCreateRequest | None = None):
    return MultiAssetStudyService(session).lock_final_test(study_id, payload.configuration if payload else None)


@router.post("/studies/{study_id}/run-final-test", response_model=StudyManifestResponse)
def run_study_final_test(study_id: str, session: SessionDep):
    try:
        return MultiAssetStudyService(session).run_final_test(study_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": str(exc), "message": str(exc), "details": {}}) from exc


@router.get("/studies/{study_id}/metrics")
def get_study_metrics(study_id: str, session: SessionDep):
    arms = list(session.scalars(select(StudyArm).where(StudyArm.study_id == study_id)))
    return [{"arm_code": arm.arm_code, "period_role": arm.period_role, "metrics": arm.metrics} for arm in arms]


@router.get("/studies/{study_id}/segments")
def get_study_segments(study_id: str, session: SessionDep):
    arms = list(session.scalars(select(StudyArm).where(StudyArm.study_id == study_id)))
    return [{"arm_code": arm.arm_code, "period_role": arm.period_role, "segments": arm.segments} for arm in arms]


@router.get("/studies/{study_id}/episode-diversity")
def get_study_episode_diversity(study_id: str, session: SessionDep):
    arms = list(session.scalars(select(StudyArm).where(StudyArm.study_id == study_id)))
    return [arm.metrics.get("episode_diversity", {}) for arm in arms]


@router.get("/studies/{study_id}/window-horizon")
def get_study_window_horizon(study_id: str, session: SessionDep):
    study = session.get(StudyManifest, study_id)
    if study is None:
        raise _not_found("STUDY_NOT_FOUND")
    return {"window_lengths": study.configuration["windows"]["lengths"], "outcome_horizons": study.configuration["outcomes"]["horizons"]}


@router.get("/studies/{study_id}/report")
def get_study_report(study_id: str, session: SessionDep):
    return {"report": MultiAssetStudyService(session).report(study_id)}


# --- Prospective Market Context forecasting ---------------------------------
# Research signals only. These endpoints never expose trading recommendations
# (buy/sell/entry/exit language); see ProspectiveForecastResponse's docstring.


@router.get("/prospective/protocols", response_model=list[ProspectiveProtocolResponse])
def prospective_protocol_definitions_and_frozen(session: SessionDep):
    frozen = list(session.scalars(select(ProspectiveProtocol).order_by(ProspectiveProtocol.created_at.desc())))
    if frozen:
        return frozen
    # No protocol frozen yet in this environment: surface the available definitions'
    # codes so a caller knows what could be frozen, without fabricating a DB row.
    return [
        {
            "id": "",
            "protocol_code": definition.protocol_code,
            "protocol_version": definition.protocol_version,
            "context_definition": definition.context_definition,
            "fallback_hierarchy": list(definition.fallback_hierarchy),
            "timeframe": definition.timeframe,
            "window_lengths": list(definition.window_lengths),
            "primary_horizon": definition.primary_horizon,
            "secondary_horizons": list(definition.secondary_horizons),
            "minimum_historical_sample": definition.minimum_historical_sample,
            "minimum_evidence_matured_forecasts": definition.minimum_evidence_matured_forecasts,
            "preferred_evidence_matured_forecasts": definition.preferred_evidence_matured_forecasts,
            "instrument_universe": list(definition.instrument_universe),
            "configuration_hash": "",
            "status": "NOT_YET_FROZEN",
            "frozen_at": None,
            "created_at": None,
        }
        for definition in list_prospective_protocol_definitions()
    ]


@router.get("/prospective/forecasts", response_model=list[ProspectiveForecastResponse])
def list_prospective_forecasts(
    session: SessionDep,
    protocol_id: str | None = None,
    instrument_id: str | None = None,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
):
    query = select(ProspectiveForecast).order_by(ProspectiveForecast.forecast_created_at.desc())
    if protocol_id:
        query = query.where(ProspectiveForecast.protocol_id == protocol_id)
    if instrument_id:
        query = query.where(ProspectiveForecast.instrument_id == instrument_id)
    if status:
        query = query.where(ProspectiveForecast.status == status)
    return list(session.scalars(query.limit(limit).offset(offset)))


@router.get("/prospective/forecasts/{forecast_id}", response_model=ProspectiveForecastResponse)
def get_prospective_forecast(forecast_id: str, session: SessionDep):
    forecast = session.get(ProspectiveForecast, forecast_id)
    if forecast is None:
        raise _not_found("PROSPECTIVE_FORECAST_NOT_FOUND")
    return forecast


@router.get("/prospective/latest", response_model=list[ProspectiveForecastResponse])
def latest_prospective_forecasts(session: SessionDep, protocol_id: str | None = None, limit: int = 20):
    query = select(ProspectiveForecast).order_by(ProspectiveForecast.forecast_created_at.desc())
    if protocol_id:
        query = query.where(ProspectiveForecast.protocol_id == protocol_id)
    return list(session.scalars(query.limit(limit)))


@router.get("/prospective/evaluation", response_model=list[ProspectiveEvaluationSnapshotResponse])
def prospective_evaluation_snapshots(session: SessionDep, protocol_id: str | None = None, limit: int = 20):
    query = select(ProspectiveEvaluationSnapshot).order_by(ProspectiveEvaluationSnapshot.created_at.desc())
    if protocol_id:
        query = query.where(ProspectiveEvaluationSnapshot.protocol_id == protocol_id)
    return list(session.scalars(query.limit(limit)))
