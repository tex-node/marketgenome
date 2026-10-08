from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column, relationship

from market_genome_domain.database import Base

UUIDString = postgresql.UUID(as_uuid=False).with_variant(String(36), "sqlite")


class AssetClass(str, Enum):
    equity = "equity"
    forex = "forex"
    crypto = "crypto"
    commodity = "commodity"
    index = "index"
    futures = "futures"
    rates = "rates"
    other = "other"


class Instrument(Base):
    __tablename__ = "instruments"
    __table_args__ = (UniqueConstraint("symbol", "exchange", name="uq_instrument_symbol_exchange"),)

    id: Mapped[str] = mapped_column(UUIDString, primary_key=True, default=lambda: str(uuid4()))
    symbol: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str | None] = mapped_column(String(255))
    asset_class: Mapped[str] = mapped_column(String(32), default=AssetClass.other.value)
    exchange: Mapped[str | None] = mapped_column(String(64))
    currency: Mapped[str | None] = mapped_column(String(16))
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    tick_size: Mapped[float | None] = mapped_column(Numeric)
    price_precision: Mapped[int | None] = mapped_column(Integer)
    volume_type: Mapped[str | None] = mapped_column(String(32))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    instrument_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))

    price_bars: Mapped[list["PriceBar"]] = relationship(back_populates="instrument")
    imports: Mapped[list["DataImport"]] = relationship(back_populates="instrument")
    pattern_windows: Mapped[list["PatternWindow"]] = relationship(back_populates="instrument")


class Timeframe(Base):
    __tablename__ = "timeframes"

    id: Mapped[str] = mapped_column(UUIDString, primary_key=True, default=lambda: str(uuid4()))
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    seconds: Mapped[int | None] = mapped_column(Integer)
    label: Mapped[str] = mapped_column(String(64))
    is_intraday: Mapped[bool] = mapped_column(Boolean)

    price_bars: Mapped[list["PriceBar"]] = relationship(back_populates="timeframe")
    imports: Mapped[list["DataImport"]] = relationship(back_populates="timeframe")
    pattern_windows: Mapped[list["PatternWindow"]] = relationship(back_populates="timeframe")


class DataSource(Base):
    __tablename__ = "data_sources"

    id: Mapped[str] = mapped_column(UUIDString, primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    source_type: Mapped[str] = mapped_column(String(64), default="csv")
    configuration_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    price_bars: Mapped[list["PriceBar"]] = relationship(back_populates="source")
    imports: Mapped[list["DataImport"]] = relationship(back_populates="source")


class PriceBar(Base):
    __tablename__ = "price_bars"
    __table_args__ = (
        UniqueConstraint(
            "instrument_id",
            "timeframe_id",
            "timestamp",
            "source_id",
            name="uq_price_bar_identity",
        ),
    )

    id: Mapped[str] = mapped_column(UUIDString, primary_key=True, default=lambda: str(uuid4()))
    instrument_id: Mapped[str] = mapped_column(ForeignKey("instruments.id"), index=True)
    timeframe_id: Mapped[str] = mapped_column(ForeignKey("timeframes.id"), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    open: Mapped[float] = mapped_column(Numeric)
    high: Mapped[float] = mapped_column(Numeric)
    low: Mapped[float] = mapped_column(Numeric)
    close: Mapped[float] = mapped_column(Numeric)
    volume: Mapped[float] = mapped_column(Numeric)
    source_id: Mapped[str] = mapped_column(ForeignKey("data_sources.id"), index=True)
    data_quality_flags: Mapped[list[str]] = mapped_column(JSON, default=list)

    instrument: Mapped[Instrument] = relationship(back_populates="price_bars")
    timeframe: Mapped[Timeframe] = relationship(back_populates="price_bars")
    source: Mapped[DataSource] = relationship(back_populates="price_bars")


class DataImport(Base):
    __tablename__ = "data_imports"
    __table_args__ = (
        UniqueConstraint(
            "source_hash",
            "configuration_hash",
            name="uq_data_import_source_configuration",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    instrument_id: Mapped[str] = mapped_column(ForeignKey("instruments.id"), index=True)
    timeframe_id: Mapped[str] = mapped_column(ForeignKey("timeframes.id"), index=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("data_sources.id"), index=True)
    source_hash: Mapped[str] = mapped_column(String(64), index=True)
    configuration_hash: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(64), index=True)
    dry_run: Mapped[bool] = mapped_column(Boolean, default=False)
    rows_read: Mapped[int] = mapped_column(Integer, default=0)
    rows_valid: Mapped[int] = mapped_column(Integer, default=0)
    rows_inserted: Mapped[int] = mapped_column(Integer, default=0)
    rows_updated: Mapped[int] = mapped_column(Integer, default=0)
    rows_skipped: Mapped[int] = mapped_column(Integer, default=0)
    warnings_count: Mapped[int] = mapped_column(Integer, default=0)
    errors_count: Mapped[int] = mapped_column(Integer, default=0)
    quality_summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    configuration: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))

    instrument: Mapped[Instrument] = relationship(back_populates="imports")
    timeframe: Mapped[Timeframe] = relationship(back_populates="imports")
    source: Mapped[DataSource] = relationship(back_populates="imports")
    issues: Mapped[list["DataImportIssue"]] = relationship(
        back_populates="data_import", cascade="all, delete-orphan"
    )


class DataImportIssue(Base):
    __tablename__ = "data_import_issues"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    import_id: Mapped[str] = mapped_column(ForeignKey("data_imports.id"), index=True)
    row_number: Mapped[int] = mapped_column(Integer, index=True)
    severity: Mapped[str] = mapped_column(String(16), index=True)
    issue_type: Mapped[str] = mapped_column(String(64), index=True)
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))

    data_import: Mapped[DataImport] = relationship(back_populates="issues")


class WindowBuildStatus(str, Enum):
    pending = "PENDING"
    running = "RUNNING"
    completed = "COMPLETED"
    completed_with_warnings = "COMPLETED_WITH_WARNINGS"
    failed = "FAILED"
    cancelled = "CANCELLED"


class NormalizationBuildStatus(str, Enum):
    pending = "PENDING"
    running = "RUNNING"
    completed = "COMPLETED"
    completed_with_warnings = "COMPLETED_WITH_WARNINGS"
    failed = "FAILED"
    cancelled = "CANCELLED"


class FeatureBuildStatus(str, Enum):
    pending = "PENDING"
    running = "RUNNING"
    completed = "COMPLETED"
    completed_with_warnings = "COMPLETED_WITH_WARNINGS"
    failed = "FAILED"
    cancelled = "CANCELLED"


class ContextBuildStatus(str, Enum):
    pending = "PENDING"
    running = "RUNNING"
    completed = "COMPLETED"
    completed_with_warnings = "COMPLETED_WITH_WARNINGS"
    failed = "FAILED"
    cancelled = "CANCELLED"


class OutcomeBuildStatus(str, Enum):
    pending = "PENDING"
    running = "RUNNING"
    completed = "COMPLETED"
    completed_with_warnings = "COMPLETED_WITH_WARNINGS"
    failed = "FAILED"
    cancelled = "CANCELLED"


class SimilarityQueryStatus(str, Enum):
    pending = "PENDING"
    running = "RUNNING"
    completed = "COMPLETED"
    completed_with_warnings = "COMPLETED_WITH_WARNINGS"
    failed = "FAILED"
    cancelled = "CANCELLED"


class ExperimentRunStatus(str, Enum):
    pending = "PENDING"
    running = "RUNNING"
    completed = "COMPLETED"
    completed_with_warnings = "COMPLETED_WITH_WARNINGS"
    failed = "FAILED"
    cancelled = "CANCELLED"


class PatternWindow(Base):
    __tablename__ = "pattern_windows"
    __table_args__ = (
        UniqueConstraint(
            "instrument_id",
            "timeframe_id",
            "end_timestamp",
            "window_length",
            "window_version",
            "source_data_hash",
            "build_configuration_hash",
            name="uq_pattern_window_identity",
        ),
        Index(
            "ix_pattern_windows_lookup",
            "instrument_id",
            "timeframe_id",
            "end_timestamp",
            "window_length",
            "window_version",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    instrument_id: Mapped[str] = mapped_column(ForeignKey("instruments.id"), index=True)
    timeframe_id: Mapped[str] = mapped_column(ForeignKey("timeframes.id"), index=True)
    start_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    end_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    start_bar_id: Mapped[str] = mapped_column(String(36), index=True)
    end_bar_id: Mapped[str] = mapped_column(String(36), index=True)
    window_length: Mapped[int] = mapped_column(Integer, index=True)
    stride: Mapped[int] = mapped_column(Integer, default=1)
    bar_count: Mapped[int] = mapped_column(Integer)
    window_version: Mapped[str] = mapped_column(String(64), default="window_v1", index=True)
    source_data_hash: Mapped[str] = mapped_column(String(64), index=True)
    build_configuration_hash: Mapped[str] = mapped_column(String(64), index=True)
    is_complete: Mapped[bool] = mapped_column(Boolean, default=True)
    quality_flags: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))

    instrument: Mapped[Instrument] = relationship(back_populates="pattern_windows")
    timeframe: Mapped[Timeframe] = relationship(back_populates="pattern_windows")


class WindowBuild(Base):
    __tablename__ = "window_builds"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    instrument_id: Mapped[str] = mapped_column(ForeignKey("instruments.id"), index=True)
    timeframe_id: Mapped[str] = mapped_column(ForeignKey("timeframes.id"), index=True)
    requested_lengths: Mapped[list[int]] = mapped_column(JSON)
    stride: Mapped[int] = mapped_column(Integer, default=1)
    start_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    window_version: Mapped[str] = mapped_column(String(64), default="window_v1")
    mode: Mapped[str] = mapped_column(String(32), default="incremental")
    configuration: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    configuration_hash: Mapped[str] = mapped_column(String(64), index=True)
    source_bar_count: Mapped[int] = mapped_column(Integer, default=0)
    candidate_windows: Mapped[int] = mapped_column(Integer, default=0)
    created_window_count: Mapped[int] = mapped_column(Integer, default=0)
    existing_window_count: Mapped[int] = mapped_column(Integer, default=0)
    skipped_window_count: Mapped[int] = mapped_column(Integer, default=0)
    incomplete_window_count: Mapped[int] = mapped_column(Integer, default=0)
    quality_warning_window_count: Mapped[int] = mapped_column(Integer, default=0)
    first_window_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_window_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(64), index=True, default=WindowBuildStatus.pending.value)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    elapsed_seconds: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True)


class NormalizationBuild(Base):
    __tablename__ = "normalization_builds"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    normalization_method: Mapped[str] = mapped_column(String(64), index=True)
    normalization_version: Mapped[str] = mapped_column(String(64))
    resampling_method: Mapped[str] = mapped_column(String(32))
    resample_points: Mapped[int] = mapped_column(Integer)
    source_window_version: Mapped[str] = mapped_column(String(64))
    instrument_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    timeframe_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    window_length: Mapped[int | None] = mapped_column(Integer, nullable=True)
    start_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    mode: Mapped[str] = mapped_column(String(32), default="incremental")
    configuration: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    configuration_hash: Mapped[str] = mapped_column(String(64), index=True)
    source_window_count: Mapped[int] = mapped_column(Integer, default=0)
    created_representation_count: Mapped[int] = mapped_column(Integer, default=0)
    existing_representation_count: Mapped[int] = mapped_column(Integer, default=0)
    skipped_representation_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_representation_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(64), index=True, default=NormalizationBuildStatus.pending.value)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    elapsed_seconds: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True)


class NormalizedPattern(Base):
    __tablename__ = "normalized_patterns"
    __table_args__ = (
        UniqueConstraint(
            "pattern_window_id",
            "normalization_method",
            "normalization_version",
            "resampling_method",
            "resample_points",
            "configuration_hash",
            "source_window_hash",
            name="uq_normalized_pattern_identity",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    pattern_window_id: Mapped[str] = mapped_column(ForeignKey("pattern_windows.id"), index=True)
    normalization_method: Mapped[str] = mapped_column(String(64), index=True)
    normalization_version: Mapped[str] = mapped_column(String(64), index=True)
    resampling_method: Mapped[str] = mapped_column(String(32))
    resample_points: Mapped[int] = mapped_column(Integer, index=True)
    source_window_hash: Mapped[str] = mapped_column(String(64))
    configuration_hash: Mapped[str] = mapped_column(String(64), index=True)
    representation_hash: Mapped[str] = mapped_column(String(64), index=True)
    channel_schema: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    normalized_values: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    diagnostics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    quality_flags: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True)

    pattern_window: Mapped[PatternWindow] = relationship()


class FeatureBuild(Base):
    __tablename__ = "feature_builds"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    feature_set_code: Mapped[str] = mapped_column(String(64), index=True)
    feature_set_version: Mapped[str] = mapped_column(String(64))
    source_normalization_method: Mapped[str] = mapped_column(String(64))
    source_normalization_version: Mapped[str] = mapped_column(String(64))
    source_resampling_method: Mapped[str] = mapped_column(String(32))
    source_resample_points: Mapped[int] = mapped_column(Integer)
    instrument_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    timeframe_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    window_length: Mapped[int | None] = mapped_column(Integer, nullable=True)
    start_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    mode: Mapped[str] = mapped_column(String(32), default="incremental")
    configuration: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    configuration_hash: Mapped[str] = mapped_column(String(64), index=True)
    source_pattern_count: Mapped[int] = mapped_column(Integer, default=0)
    created_feature_count: Mapped[int] = mapped_column(Integer, default=0)
    existing_feature_count: Mapped[int] = mapped_column(Integer, default=0)
    skipped_feature_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_feature_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(64), index=True, default=FeatureBuildStatus.pending.value)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    elapsed_seconds: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True)


class MarketDNA(Base):
    __tablename__ = "market_dna"
    __table_args__ = (
        UniqueConstraint(
            "pattern_window_id",
            "normalized_pattern_id",
            "feature_set_code",
            "feature_set_version",
            "configuration_hash",
            "source_window_hash",
            "source_representation_hash",
            name="uq_market_dna_identity",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    pattern_window_id: Mapped[str] = mapped_column(ForeignKey("pattern_windows.id"), index=True)
    normalized_pattern_id: Mapped[str] = mapped_column(ForeignKey("normalized_patterns.id"), index=True)
    feature_set_code: Mapped[str] = mapped_column(String(64), index=True)
    feature_set_version: Mapped[str] = mapped_column(String(64), index=True)
    source_window_hash: Mapped[str] = mapped_column(String(64))
    source_representation_hash: Mapped[str] = mapped_column(String(64))
    configuration_hash: Mapped[str] = mapped_column(String(64), index=True)
    feature_vector_hash: Mapped[str] = mapped_column(String(64), index=True)
    feature_count: Mapped[int] = mapped_column(Integer)
    available_feature_count: Mapped[int] = mapped_column(Integer)
    unavailable_feature_count: Mapped[int] = mapped_column(Integer)
    feature_vector: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    feature_values: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    availability: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    diagnostics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    quality_flags: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True)

    pattern_window: Mapped[PatternWindow] = relationship()
    normalized_pattern: Mapped[NormalizedPattern] = relationship()


class ContextBuild(Base):
    __tablename__ = "context_builds"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    context_producer_code: Mapped[str] = mapped_column(String(64), index=True)
    context_producer_version: Mapped[str] = mapped_column(String(64), index=True)
    feature_set_code: Mapped[str] = mapped_column(String(64), index=True)
    feature_set_version: Mapped[str] = mapped_column(String(64))
    instrument_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    timeframe_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    window_length: Mapped[int | None] = mapped_column(Integer, nullable=True)
    start_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    mode: Mapped[str] = mapped_column(String(32), default="incremental")
    configuration: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    configuration_hash: Mapped[str] = mapped_column(String(64), index=True)
    source_market_dna_count: Mapped[int] = mapped_column(Integer, default=0)
    created_context_count: Mapped[int] = mapped_column(Integer, default=0)
    existing_context_count: Mapped[int] = mapped_column(Integer, default=0)
    partial_context_count: Mapped[int] = mapped_column(Integer, default=0)
    skipped_context_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_context_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(64), index=True, default=ContextBuildStatus.pending.value)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    elapsed_seconds: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True)


class MarketContext(Base):
    __tablename__ = "market_contexts"
    __table_args__ = (
        UniqueConstraint(
            "pattern_window_id",
            "normalized_pattern_id",
            "market_dna_id",
            "context_producer_code",
            "context_producer_version",
            "configuration_hash",
            "source_window_hash",
            "source_representation_hash",
            "source_feature_vector_hash",
            name="uq_market_context_identity",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    pattern_window_id: Mapped[str] = mapped_column(ForeignKey("pattern_windows.id"), index=True)
    normalized_pattern_id: Mapped[str] = mapped_column(ForeignKey("normalized_patterns.id"), index=True)
    market_dna_id: Mapped[str] = mapped_column(ForeignKey("market_dna.id"), index=True)
    context_producer_code: Mapped[str] = mapped_column(String(64), index=True)
    context_producer_version: Mapped[str] = mapped_column(String(64), index=True)
    feature_set_code: Mapped[str] = mapped_column(String(64), index=True)
    feature_set_version: Mapped[str] = mapped_column(String(64))
    source_window_hash: Mapped[str] = mapped_column(String(64))
    source_representation_hash: Mapped[str] = mapped_column(String(64))
    source_feature_vector_hash: Mapped[str] = mapped_column(String(64))
    configuration_hash: Mapped[str] = mapped_column(String(64), index=True)
    context_hash: Mapped[str] = mapped_column(String(64), index=True)
    trend_state: Mapped[str] = mapped_column(String(64), index=True)
    volatility_state: Mapped[str] = mapped_column(String(64), index=True)
    volatility_phase_state: Mapped[str] = mapped_column(String(64), index=True)
    persistence_state: Mapped[str] = mapped_column(String(64), index=True)
    activity_state: Mapped[str] = mapped_column(String(64), index=True)
    shock_state: Mapped[str] = mapped_column(String(64), index=True)
    market_phase_state: Mapped[str] = mapped_column(String(64), index=True)
    multi_resolution_state: Mapped[str] = mapped_column(String(64), index=True)
    trend_confidence: Mapped[float] = mapped_column(Numeric)
    volatility_confidence: Mapped[float] = mapped_column(Numeric)
    volatility_phase_confidence: Mapped[float] = mapped_column(Numeric)
    persistence_confidence: Mapped[float] = mapped_column(Numeric)
    activity_confidence: Mapped[float] = mapped_column(Numeric)
    shock_confidence: Mapped[float] = mapped_column(Numeric)
    market_phase_confidence: Mapped[float] = mapped_column(Numeric)
    multi_resolution_confidence: Mapped[float] = mapped_column(Numeric)
    composite_context_code: Mapped[str] = mapped_column(String(512), index=True)
    context_family_code: Mapped[str] = mapped_column(String(128), index=True)
    composite_confidence: Mapped[float] = mapped_column(Numeric, index=True)
    completeness_score: Mapped[float] = mapped_column(Numeric, index=True)
    dimension_scores: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    opposing_evidence: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    diagnostics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    multi_resolution_links: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    quality_flags: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True)

    pattern_window: Mapped[PatternWindow] = relationship()
    normalized_pattern: Mapped[NormalizedPattern] = relationship()
    market_dna: Mapped[MarketDNA] = relationship()


class OutcomeBuild(Base):
    __tablename__ = "outcome_builds"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    outcome_set_code: Mapped[str] = mapped_column(String(64), index=True)
    outcome_set_version: Mapped[str] = mapped_column(String(64), index=True)
    instrument_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    timeframe_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    window_length: Mapped[int | None] = mapped_column(Integer, nullable=True)
    start_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    requested_horizons: Mapped[list[int]] = mapped_column(JSON)
    mode: Mapped[str] = mapped_column(String(32), default="incremental")
    configuration: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    configuration_hash: Mapped[str] = mapped_column(String(64), index=True)
    source_pattern_count: Mapped[int] = mapped_column(Integer, default=0)
    eligible_pattern_count: Mapped[int] = mapped_column(Integer, default=0)
    created_observation_count: Mapped[int] = mapped_column(Integer, default=0)
    existing_observation_count: Mapped[int] = mapped_column(Integer, default=0)
    partial_observation_count: Mapped[int] = mapped_column(Integer, default=0)
    skipped_pattern_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_observation_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(64), index=True, default=OutcomeBuildStatus.pending.value)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    elapsed_seconds: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True)


class OutcomeObservation(Base):
    __tablename__ = "outcome_observations"
    __table_args__ = (
        UniqueConstraint(
            "pattern_window_id",
            "outcome_set_code",
            "outcome_set_version",
            "horizon_bars",
            "source_window_hash",
            "future_bar_hash",
            "configuration_hash",
            "is_complete",
            name="uq_outcome_observation_identity",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    pattern_window_id: Mapped[str] = mapped_column(ForeignKey("pattern_windows.id"), index=True)
    instrument_id: Mapped[str] = mapped_column(String(36), index=True)
    timeframe_id: Mapped[str] = mapped_column(String(36), index=True)
    window_length: Mapped[int] = mapped_column(Integer, index=True)
    window_start_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    window_end_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    outcome_set_code: Mapped[str] = mapped_column(String(64), index=True)
    outcome_set_version: Mapped[str] = mapped_column(String(64), index=True)
    horizon_bars: Mapped[int] = mapped_column(Integer, index=True)
    available_future_bars: Mapped[int] = mapped_column(Integer)
    is_complete: Mapped[bool] = mapped_column(Boolean, index=True)
    anchor_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    anchor_price: Mapped[float] = mapped_column(Numeric)
    first_future_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_future_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    future_simple_return: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    future_log_return: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    maximum_favourable_excursion: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    maximum_adverse_excursion: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    time_to_mfe_bars: Mapped[int | None] = mapped_column(Integer, nullable=True)
    time_to_mae_bars: Mapped[int | None] = mapped_column(Integer, nullable=True)
    future_realized_volatility: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    future_path_efficiency: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    future_maximum_drawdown: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    future_maximum_runup: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    direction_class: Mapped[str] = mapped_column(String(32), index=True)
    continuation_reversal_class: Mapped[str] = mapped_column(String(64), index=True)
    first_barrier_hit: Mapped[str] = mapped_column(String(64), index=True)
    gain_before_drawdown: Mapped[str] = mapped_column(String(64))
    drawdown_before_gain: Mapped[str] = mapped_column(String(64))
    source_window_hash: Mapped[str] = mapped_column(String(64), index=True)
    future_bar_hash: Mapped[str] = mapped_column(String(64), index=True)
    configuration_hash: Mapped[str] = mapped_column(String(64), index=True)
    outcome_hash: Mapped[str] = mapped_column(String(64), index=True)
    scalar_values: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    forward_path: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    barrier_results: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    diagnostics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    quality_flags: Mapped[list[str]] = mapped_column(JSON, default=list)
    supersedes_observation_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True)

    pattern_window: Mapped[PatternWindow] = relationship()


class SimilarityQuery(Base):
    __tablename__ = "similarity_queries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    query_window_id: Mapped[str] = mapped_column(ForeignKey("pattern_windows.id"), index=True)
    query_normalized_pattern_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    query_market_dna_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    similarity_method_code: Mapped[str] = mapped_column(String(64), index=True)
    similarity_method_version: Mapped[str] = mapped_column(String(64), index=True)
    feature_set_code: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    feature_set_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    normalization_method: Mapped[str | None] = mapped_column(String(64), nullable=True)
    normalization_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    resampling_method: Mapped[str | None] = mapped_column(String(32), nullable=True)
    resample_points: Mapped[int | None] = mapped_column(Integer, nullable=True)
    top_k: Mapped[int] = mapped_column(Integer)
    candidate_count: Mapped[int] = mapped_column(Integer, default=0)
    returned_match_count: Mapped[int] = mapped_column(Integer, default=0)
    temporal_policy: Mapped[str] = mapped_column(String(64), default="historical_only")
    configuration: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    configuration_hash: Mapped[str] = mapped_column(String(64), index=True)
    query_hash: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(64), index=True, default=SimilarityQueryStatus.pending.value)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    elapsed_seconds: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    diagnostics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True)

    query_window: Mapped[PatternWindow] = relationship()


class SimilarityMatch(Base):
    __tablename__ = "similarity_matches"
    __table_args__ = (
        UniqueConstraint(
            "query_id",
            "candidate_window_id",
            "similarity_method_code",
            "configuration_hash",
            name="uq_similarity_match_identity",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    query_id: Mapped[str] = mapped_column(ForeignKey("similarity_queries.id"), index=True)
    query_window_id: Mapped[str] = mapped_column(ForeignKey("pattern_windows.id"), index=True)
    candidate_window_id: Mapped[str] = mapped_column(ForeignKey("pattern_windows.id"), index=True)
    candidate_normalized_pattern_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    candidate_market_dna_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    rank: Mapped[int] = mapped_column(Integer, index=True)
    distance: Mapped[float] = mapped_column(Numeric, index=True)
    similarity_score: Mapped[float] = mapped_column(Numeric, index=True)
    similarity_method_code: Mapped[str] = mapped_column(String(64), index=True)
    similarity_method_version: Mapped[str] = mapped_column(String(64), index=True)
    configuration_hash: Mapped[str] = mapped_column(String(64), index=True)
    query_source_hash: Mapped[str] = mapped_column(String(64))
    candidate_source_hash: Mapped[str] = mapped_column(String(64))
    query_vector_hash: Mapped[str] = mapped_column(String(64))
    candidate_vector_hash: Mapped[str] = mapped_column(String(64))
    component_scores: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    diagnostics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    quality_flags: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True)

    query: Mapped[SimilarityQuery] = relationship()


class ExperimentRun(Base):
    __tablename__ = "experiment_runs"
    __table_args__ = (
        UniqueConstraint(
            "experiment_code",
            "experiment_version",
            "dataset_hash",
            "configuration_hash",
            "run_nonce",
            name="uq_experiment_run_identity",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    experiment_code: Mapped[str] = mapped_column(String(64), index=True)
    experiment_version: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(255))
    hypothesis: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(64), index=True, default=ExperimentRunStatus.pending.value)
    dataset_version: Mapped[str] = mapped_column(String(64), default="dataset_snapshot_v1")
    dataset_hash: Mapped[str] = mapped_column(String(64), index=True)
    code_version: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    configuration: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    configuration_hash: Mapped[str] = mapped_column(String(64), index=True)
    run_nonce: Mapped[str] = mapped_column(String(64), default="default")
    similarity_method: Mapped[str] = mapped_column(String(64), index=True)
    baseline_methods: Mapped[list[str]] = mapped_column(JSON, default=list)
    outcome_set_code: Mapped[str] = mapped_column(String(64), index=True)
    outcome_set_version: Mapped[str] = mapped_column(String(64))
    outcome_horizons: Mapped[list[int]] = mapped_column(JSON, default=list)
    validation_method: Mapped[str] = mapped_column(String(64), index=True)
    validation_configuration: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    instrument_scope: Mapped[list[str]] = mapped_column(JSON, default=list)
    timeframe_scope: Mapped[list[str]] = mapped_column(JSON, default=list)
    window_length_scope: Mapped[list[int]] = mapped_column(JSON, default=list)
    date_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    date_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    parameter_grid: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    multiple_testing_family: Mapped[str | None] = mapped_column(String(128), nullable=True)
    decision: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    elapsed_seconds: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True)


class ExperimentFold(Base):
    __tablename__ = "experiment_folds"
    __table_args__ = (UniqueConstraint("experiment_run_id", "fold_number", name="uq_experiment_fold_number"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    experiment_run_id: Mapped[str] = mapped_column(ForeignKey("experiment_runs.id"), index=True)
    fold_number: Mapped[int] = mapped_column(Integer, index=True)
    index_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    index_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    validation_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    validation_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    test_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    test_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    purge_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    purge_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    embargo_bars: Mapped[int] = mapped_column(Integer, default=0)
    eligible_index_count: Mapped[int] = mapped_column(Integer, default=0)
    eligible_query_count: Mapped[int] = mapped_column(Integer, default=0)
    excluded_overlap_count: Mapped[int] = mapped_column(Integer, default=0)
    excluded_future_count: Mapped[int] = mapped_column(Integer, default=0)
    excluded_quality_count: Mapped[int] = mapped_column(Integer, default=0)
    configuration: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    fold_hash: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(64), index=True, default=ExperimentRunStatus.pending.value)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True)

    experiment_run: Mapped[ExperimentRun] = relationship()


class QueryEvaluation(Base):
    __tablename__ = "query_evaluations"
    __table_args__ = (
        UniqueConstraint(
            "experiment_run_id",
            "fold_id",
            "query_window_id",
            "similarity_method",
            "baseline_method",
            "horizon_bars",
            "neighbour_count",
            "weighting_method",
            "configuration_hash",
            name="uq_query_evaluation_identity",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    experiment_run_id: Mapped[str] = mapped_column(ForeignKey("experiment_runs.id"), index=True)
    fold_id: Mapped[str] = mapped_column(ForeignKey("experiment_folds.id"), index=True)
    query_window_id: Mapped[str] = mapped_column(ForeignKey("pattern_windows.id"), index=True)
    query_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    horizon_bars: Mapped[int] = mapped_column(Integer, index=True)
    similarity_method: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    baseline_method: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    neighbour_count: Mapped[int] = mapped_column(Integer)
    weighting_method: Mapped[str] = mapped_column(String(64), index=True)
    eligible_candidate_count: Mapped[int] = mapped_column(Integer)
    retrieved_match_count: Mapped[int] = mapped_column(Integer)
    effective_match_count: Mapped[float] = mapped_column(Numeric)
    predicted_direction_probability: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    predicted_return_mean: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    predicted_return_median: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    predicted_return_quantiles: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    predicted_mfe_mean: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    predicted_mae_mean: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    scenario_probabilities: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    actual_direction: Mapped[str | None] = mapped_column(String(32), nullable=True)
    actual_return: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    actual_mfe: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    actual_mae: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    direction_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    brier_component: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    log_loss_component: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    absolute_error: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    squared_error: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    quantile_losses: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    query_context: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    retrieved_context_distribution: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    retrieval_diagnostics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    quality_flags: Mapped[list[str]] = mapped_column(JSON, default=list)
    configuration_hash: Mapped[str] = mapped_column(String(64), index=True)
    evaluation_hash: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True)


class ExperimentMetric(Base):
    __tablename__ = "experiment_metrics"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    experiment_run_id: Mapped[str] = mapped_column(ForeignKey("experiment_runs.id"), index=True)
    fold_id: Mapped[str | None] = mapped_column(ForeignKey("experiment_folds.id"), index=True, nullable=True)
    metric_code: Mapped[str] = mapped_column(String(64), index=True)
    metric_version: Mapped[str] = mapped_column(String(64))
    value: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    sample_count: Mapped[int] = mapped_column(Integer)
    segment_type: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    segment_value: Mapped[str | None] = mapped_column(String(255), index=True, nullable=True)
    horizon_bars: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    similarity_method: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    baseline_method: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    confidence_interval_low: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    confidence_interval_high: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    standard_error: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    p_value: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    effect_size: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    metric_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    metric_hash: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True)


class ExperimentArtifact(Base):
    __tablename__ = "experiment_artifacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    experiment_run_id: Mapped[str] = mapped_column(ForeignKey("experiment_runs.id"), index=True)
    artifact_type: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(255))
    content: Mapped[str] = mapped_column(Text)
    artifact_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    artifact_hash: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True)


class DiagnosticArtifact(Base):
    __tablename__ = "diagnostic_artifacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    experiment_run_id: Mapped[str] = mapped_column(ForeignKey("experiment_runs.id"), index=True)
    diagnostic_code: Mapped[str] = mapped_column(String(64), index=True)
    artifact_type: Mapped[str] = mapped_column(String(64), index=True)
    schema_version: Mapped[str] = mapped_column(String(64), default="diagnostic_artifact_v1")
    configuration_hash: Mapped[str] = mapped_column(String(64), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    artifact_hash: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True)

    experiment_run: Mapped[ExperimentRun] = relationship()


class FeatureScalingSnapshot(Base):
    __tablename__ = "feature_scaling_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "feature_set_code",
            "feature_set_version",
            "historical_mode",
            "configuration_hash",
            "snapshot_hash",
            name="uq_feature_scaling_snapshot_identity",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    experiment_run_id: Mapped[str | None] = mapped_column(ForeignKey("experiment_runs.id"), index=True, nullable=True)
    scope: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    feature_set_code: Mapped[str] = mapped_column(String(64), index=True)
    feature_set_version: Mapped[str] = mapped_column(String(64), index=True)
    date_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    date_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    historical_mode: Mapped[str] = mapped_column(String(64), index=True)
    record_count: Mapped[int] = mapped_column(Integer, default=0)
    feature_statistics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    feature_availability: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    configuration: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    configuration_hash: Mapped[str] = mapped_column(String(64), index=True)
    snapshot_hash: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True)

    experiment_run: Mapped[ExperimentRun | None] = relationship()


class StudyManifest(Base):
    __tablename__ = "study_manifests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    study_code: Mapped[str] = mapped_column(String(64), index=True)
    study_version: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(255))
    configuration: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    configuration_hash: Mapped[str] = mapped_column(String(64), index=True)
    dataset_hash: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(64), index=True, default="DEVELOPMENT")
    decision: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    decision_rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    final_test_lock: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    final_test_lock_hash: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class StudyDatasetEntry(Base):
    __tablename__ = "study_dataset_entries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    study_id: Mapped[str] = mapped_column(ForeignKey("study_manifests.id"), index=True)
    instrument_id: Mapped[str] = mapped_column(ForeignKey("instruments.id"), index=True)
    timeframe_id: Mapped[str] = mapped_column(ForeignKey("timeframes.id"), index=True)
    source_id: Mapped[str | None] = mapped_column(UUIDString, index=True, nullable=True)
    date_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    date_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    bar_count: Mapped[int] = mapped_column(Integer, default=0)
    window_count: Mapped[int] = mapped_column(Integer, default=0)
    episode_count: Mapped[int] = mapped_column(Integer, default=0)
    complete_outcome_rate: Mapped[float] = mapped_column(Numeric, default=0.0)
    quality_status: Mapped[str] = mapped_column(String(64), index=True, default="UNKNOWN")
    inclusion_status: Mapped[str] = mapped_column(String(64), index=True, default="EXCLUDED")
    exclusion_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    dataset_entry_hash: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True)

    study: Mapped[StudyManifest] = relationship()
    instrument: Mapped[Instrument] = relationship()
    timeframe: Mapped[Timeframe] = relationship()


class StudyEpisode(Base):
    __tablename__ = "study_episodes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    study_id: Mapped[str] = mapped_column(ForeignKey("study_manifests.id"), index=True)
    episode_id: Mapped[str] = mapped_column(String(64), index=True)
    instrument_id: Mapped[str] = mapped_column(ForeignKey("instruments.id"), index=True)
    timeframe_id: Mapped[str] = mapped_column(ForeignKey("timeframes.id"), index=True)
    episode_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    episode_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    window_count: Mapped[int] = mapped_column(Integer, default=0)
    outcome_span: Mapped[int] = mapped_column(Integer, default=0)
    episode_hash: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True)

    study: Mapped[StudyManifest] = relationship()
    instrument: Mapped[Instrument] = relationship()
    timeframe: Mapped[Timeframe] = relationship()


class StudyPreflight(Base):
    __tablename__ = "study_preflights"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    study_id: Mapped[str] = mapped_column(ForeignKey("study_manifests.id"), index=True)
    gate_code: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(64), index=True)
    actual_value: Mapped[str] = mapped_column(String(255))
    required_value: Mapped[str] = mapped_column(String(255))
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True)

    study: Mapped[StudyManifest] = relationship()


class StudyArm(Base):
    __tablename__ = "study_arms"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    study_id: Mapped[str] = mapped_column(ForeignKey("study_manifests.id"), index=True)
    arm_code: Mapped[str] = mapped_column(String(64), index=True)
    period_role: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(64), index=True, default="PENDING")
    similarity_method: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    baseline_methods: Mapped[list[str]] = mapped_column(JSON, default=list)
    episode_cap: Mapped[int | None] = mapped_column(Integer, nullable=True)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    segments: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    configuration_hash: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True)

    study: Mapped[StudyManifest] = relationship()


class ReplicationProtocol(Base):
    __tablename__ = "replication_protocols"
    __table_args__ = (
        UniqueConstraint("protocol_code", "protocol_version", name="uq_replication_protocol_identity"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    protocol_code: Mapped[str] = mapped_column(String(64), index=True)
    protocol_version: Mapped[str] = mapped_column(String(64), index=True)
    source_experiment_id: Mapped[str] = mapped_column(ForeignKey("experiment_runs.id"), index=True)
    source_config_hash: Mapped[str] = mapped_column(String(64), index=True)
    source_dataset_hash: Mapped[str] = mapped_column(String(64), index=True)
    hypothesis_text: Mapped[str] = mapped_column(Text)
    primary_method: Mapped[str] = mapped_column(String(64), index=True)
    study_arm: Mapped[str] = mapped_column(String(64), index=True)
    timeframe: Mapped[str] = mapped_column(String(32))
    window_lengths: Mapped[list[int]] = mapped_column(JSON, default=list)
    primary_horizon: Mapped[int] = mapped_column(Integer)
    neighbour_count: Mapped[int] = mapped_column(Integer)
    weighting: Mapped[str] = mapped_column(String(64))
    episode_cap: Mapped[int] = mapped_column(Integer)
    primary_metrics: Mapped[list[str]] = mapped_column(JSON, default=list)
    controls: Mapped[list[str]] = mapped_column(JSON, default=list)
    success_criteria: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    failure_criteria: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    independent_source_requirement: Mapped[str] = mapped_column(String(64))
    configuration: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    configuration_hash: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(64), index=True, default="DRAFT")
    frozen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    frozen_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True)

    source_experiment: Mapped[ExperimentRun] = relationship()


class ReplicationLock(Base):
    __tablename__ = "replication_locks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    protocol_id: Mapped[str] = mapped_column(ForeignKey("replication_protocols.id"), index=True)
    study_id: Mapped[str] = mapped_column(ForeignKey("study_manifests.id"), index=True)
    source_study_id: Mapped[str] = mapped_column(ForeignKey("study_manifests.id"), index=True)
    dataset_hash: Mapped[str] = mapped_column(String(64), index=True)
    provider_code: Mapped[str] = mapped_column(String(64), index=True)
    provider_provenance_hash: Mapped[str] = mapped_column(String(64), index=True)
    instrument_universe: Mapped[list[str]] = mapped_column(JSON, default=list)
    date_range: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    lock_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    lock_hash: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(64), index=True, default="LOCKED")
    locked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    locked_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True)

    protocol: Mapped[ReplicationProtocol] = relationship()
    study: Mapped[StudyManifest] = relationship(foreign_keys=[study_id])
    source_study: Mapped[StudyManifest] = relationship(foreign_keys=[source_study_id])


class ReplicationRecord(Base):
    __tablename__ = "replication_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    protocol_id: Mapped[str] = mapped_column(ForeignKey("replication_protocols.id"), index=True)
    lock_id: Mapped[str] = mapped_column(ForeignKey("replication_locks.id"), index=True)
    source_experiment_id: Mapped[str] = mapped_column(ForeignKey("experiment_runs.id"), index=True)
    replication_experiment_id: Mapped[str | None] = mapped_column(ForeignKey("experiment_runs.id"), index=True, nullable=True)
    provider_independence: Mapped[str] = mapped_column(String(32), index=True, default="UNKNOWN")
    independence_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    decision: Mapped[str] = mapped_column(String(64), index=True, default="PENDING")
    decision_rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    comparison: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    protocol: Mapped[ReplicationProtocol] = relationship()
    lock: Mapped[ReplicationLock] = relationship()


class ProspectiveProtocol(Base):
    __tablename__ = "prospective_protocols"
    __table_args__ = (
        UniqueConstraint("protocol_code", "protocol_version", name="uq_prospective_protocol_identity"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    protocol_code: Mapped[str] = mapped_column(String(64), index=True)
    protocol_version: Mapped[str] = mapped_column(String(64), index=True)
    source_replication_protocol_id: Mapped[str] = mapped_column(ForeignKey("replication_protocols.id"), index=True)
    source_replication_experiment_id: Mapped[str] = mapped_column(ForeignKey("experiment_runs.id"), index=True)
    hypothesis_text: Mapped[str] = mapped_column(Text)
    context_definition: Mapped[str] = mapped_column(String(64), index=True)
    context_producer_code: Mapped[str] = mapped_column(String(64))
    context_producer_version: Mapped[str] = mapped_column(String(64))
    fallback_hierarchy: Mapped[list[str]] = mapped_column(JSON, default=list)
    timeframe: Mapped[str] = mapped_column(String(32))
    window_lengths: Mapped[list[int]] = mapped_column(JSON, default=list)
    primary_horizon: Mapped[int] = mapped_column(Integer)
    secondary_horizons: Mapped[list[int]] = mapped_column(JSON, default=list)
    probability_method: Mapped[str] = mapped_column(String(64))
    smoothing_method: Mapped[str] = mapped_column(String(64))
    smoothing_parameters: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    minimum_historical_sample: Mapped[int] = mapped_column(Integer)
    calibration_method: Mapped[str] = mapped_column(String(64), default="none")
    refresh_policy: Mapped[str] = mapped_column(String(64), default="daily_d1_completed_bars")
    provider_code: Mapped[str] = mapped_column(String(64))
    instrument_universe: Mapped[list[str]] = mapped_column(JSON, default=list)
    success_criteria: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    minimum_evidence_matured_forecasts: Mapped[int] = mapped_column(Integer, default=100)
    preferred_evidence_matured_forecasts: Mapped[int] = mapped_column(Integer, default=250)
    configuration: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    configuration_hash: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(64), index=True, default="DRAFT")
    frozen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    frozen_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True)

    source_replication_protocol: Mapped[ReplicationProtocol] = relationship()
    source_replication_experiment: Mapped[ExperimentRun] = relationship()


class ProspectiveForecast(Base):
    __tablename__ = "prospective_forecasts"
    __table_args__ = (
        # pattern_window_id already uniquely implies instrument, timeframe, window
        # length, and query timestamp (it references one immutable PatternWindow row),
        # so the identity boundary need not repeat those fields. provenance_class is
        # included because the same pattern_window/horizon may legitimately be
        # forecast once as TRUE_PROSPECTIVE and, separately, once as a
        # BACKFILL_SIMULATION or HISTORICAL_VALIDATION run without colliding.
        UniqueConstraint(
            "protocol_id", "pattern_window_id", "horizon_bars", "provenance_class",
            name="uq_prospective_forecast_identity",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    protocol_id: Mapped[str] = mapped_column(ForeignKey("prospective_protocols.id"), index=True)
    instrument_id: Mapped[str] = mapped_column(String(36), index=True)
    timeframe_id: Mapped[str] = mapped_column(String(36), index=True)
    window_length: Mapped[int] = mapped_column(Integer, index=True)
    pattern_window_id: Mapped[str] = mapped_column(ForeignKey("pattern_windows.id"), index=True)
    # forecast_timestamp/data_cutoff_timestamp/created_at are provenance, not identity:
    #   forecast_timestamp    -- market timestamp associated with the forecast/state
    #                            (equal to the referenced PatternWindow.end_timestamp)
    #   data_cutoff_timestamp -- latest source market data permitted in the forecast
    #   forecast_created_at   -- actual system time the forecast record was persisted
    forecast_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    data_cutoff_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    forecast_created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True)
    horizon_bars: Mapped[int] = mapped_column(Integer, index=True)
    context_code: Mapped[str] = mapped_column(String(512))
    context_level_used: Mapped[str] = mapped_column(String(64), index=True)
    fallback_reason: Mapped[str | None] = mapped_column(String(128), nullable=True)
    probability_positive: Mapped[float] = mapped_column(Numeric)
    probability_negative: Mapped[float] = mapped_column(Numeric)
    expected_return: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    sample_count: Mapped[int] = mapped_column(Integer)
    positive_count: Mapped[int] = mapped_column(Integer)
    negative_count: Mapped[int] = mapped_column(Integer)
    confidence_lower: Mapped[float] = mapped_column(Numeric)
    confidence_upper: Mapped[float] = mapped_column(Numeric)
    provenance_class: Mapped[str] = mapped_column(String(32), index=True, default="TRUE_PROSPECTIVE")
    status: Mapped[str] = mapped_column(String(32), index=True, default="PENDING_OUTCOME")
    source_hash: Mapped[str] = mapped_column(String(64), index=True)
    context_hash: Mapped[str] = mapped_column(String(64), index=True)
    historical_reference_hash: Mapped[str] = mapped_column(String(64), index=True)
    forecast_hash: Mapped[str] = mapped_column(String(64), index=True)
    provider_code: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True)

    protocol: Mapped[ProspectiveProtocol] = relationship()


class ProspectiveForecastOutcome(Base):
    __tablename__ = "prospective_forecast_outcomes"
    __table_args__ = (
        UniqueConstraint("forecast_id", name="uq_prospective_forecast_outcome_identity"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    forecast_id: Mapped[str] = mapped_column(ForeignKey("prospective_forecasts.id"), index=True)
    # Prefer referencing the existing immutable ForwardOutcome (OutcomeObservation)
    # rather than duplicating its computation; the scalar fields below are still
    # persisted as an immutable snapshot so this prospective record survives even if
    # the source row is ever superseded (e.g. a future full outcome rebuild).
    source_forward_outcome_id: Mapped[str] = mapped_column(ForeignKey("outcome_observations.id"), index=True)
    source_outcome_hash: Mapped[str] = mapped_column(String(64), index=True)
    actual_return: Mapped[float] = mapped_column(Numeric)
    actual_direction: Mapped[str] = mapped_column(String(16), index=True)
    maximum_favourable_excursion: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    maximum_adverse_excursion: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    future_bar_count: Mapped[int] = mapped_column(Integer)
    outcome_hash: Mapped[str] = mapped_column(String(64), index=True)
    data_revision_detected: Mapped[bool] = mapped_column(Boolean, default=False)
    matured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True)

    forecast: Mapped[ProspectiveForecast] = relationship()


class ProspectiveEvaluationSnapshot(Base):
    __tablename__ = "prospective_evaluation_snapshots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    protocol_id: Mapped[str] = mapped_column(ForeignKey("prospective_protocols.id"), index=True)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    forecast_count: Mapped[int] = mapped_column(Integer)
    matured_count: Mapped[int] = mapped_column(Integer)
    brier_score: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    brier_skill_vs_unconditional: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    log_loss: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    expected_calibration_error: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    direction_accuracy: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    balanced_accuracy: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    mcc: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    calibration_bins: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    primary_horizon: Mapped[int | None] = mapped_column(Integer, nullable=True)
    primary_horizon_matured_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bootstrap_ci_low: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    bootstrap_ci_high: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    per_horizon_metrics: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(64), index=True, default="PROSPECTIVE_EVIDENCE_ACCUMULATING")
    snapshot_hash: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True)

    protocol: Mapped[ProspectiveProtocol] = relationship()
