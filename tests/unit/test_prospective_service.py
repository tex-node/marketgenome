from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from market_genome_domain.models import (
    ExperimentRun,
    MarketContext,
    OutcomeObservation,
    PatternWindow,
    ProspectiveForecast,
    ProspectiveForecastOutcome,
    ReplicationProtocol,
    ReplicationRecord,
)
from market_genome_prospective.service import (
    ProspectiveContextForecastService,
    ProspectiveProtocolImmutableError,
    RetroactiveForecastError,
)
from sqlalchemy.orm import Session

INSTRUMENT_ID = "instrument-eurusd"
TIMEFRAME_ID = "timeframe-d1"
WINDOW_LENGTH = 16
HORIZON = 20


def _add_outcome(session: Session, window: PatternWindow, *, future_return: float) -> OutcomeObservation:
    outcome = OutcomeObservation(
        pattern_window_id=window.id, instrument_id=INSTRUMENT_ID, timeframe_id=TIMEFRAME_ID,
        window_length=WINDOW_LENGTH, window_start_timestamp=window.start_timestamp, window_end_timestamp=window.end_timestamp,
        outcome_set_code="forward_outcomes_v1", outcome_set_version="forward_outcomes_v1", horizon_bars=HORIZON,
        available_future_bars=HORIZON, is_complete=True, anchor_timestamp=window.end_timestamp, anchor_price=1.0,
        future_simple_return=future_return, direction_class="UP" if future_return > 0 else "DOWN",
        continuation_reversal_class="CONTINUATION", first_barrier_hit="NONE", gain_before_drawdown="NA",
        drawdown_before_gain="NA", source_window_hash="swh", future_bar_hash=f"fbh-{window.id}",
        configuration_hash="cfgh", outcome_hash=f"oh-{window.id}",
    )
    session.add(outcome)
    return outcome


def _window(
    session: Session, end: datetime, *, trend: str, volatility: str, future_return: float | None, with_outcome: bool = True
) -> PatternWindow:
    window_id = str(uuid4())
    window = PatternWindow(
        id=window_id, instrument_id=INSTRUMENT_ID, timeframe_id=TIMEFRAME_ID,
        start_timestamp=end - timedelta(days=WINDOW_LENGTH), end_timestamp=end,
        start_bar_id=f"b-{window_id}-start", end_bar_id=f"b-{window_id}-end",
        window_length=WINDOW_LENGTH, bar_count=WINDOW_LENGTH,
        source_data_hash=f"h-{window_id}", build_configuration_hash="cfg",
        is_complete=True, quality_flags=[],
    )
    session.add(window)
    context = MarketContext(
        pattern_window_id=window_id, normalized_pattern_id=str(uuid4()), market_dna_id=str(uuid4()),
        context_producer_code="transparent_context_v1", context_producer_version="transparent_context_v1",
        feature_set_code="market_dna_v1", feature_set_version="market_dna_v1",
        source_window_hash="swh", source_representation_hash="srh", source_feature_vector_hash="sfvh",
        configuration_hash="cfgh", context_hash=f"ctx-{window_id}",
        trend_state=trend, volatility_state=volatility, volatility_phase_state="STABLE",
        persistence_state="PERSISTENT", activity_state="NORMAL", shock_state="NONE", market_phase_state="MID",
        multi_resolution_state="ALIGNED",
        trend_confidence=0.8, volatility_confidence=0.8, volatility_phase_confidence=0.8, persistence_confidence=0.8,
        activity_confidence=0.8, shock_confidence=0.8, market_phase_confidence=0.8, multi_resolution_confidence=0.8,
        composite_context_code=f"{trend}|{volatility}", context_family_code=f"{trend}_{volatility}_FAMILY",
        composite_confidence=0.8, completeness_score=1.0,
    )
    session.add(context)
    if with_outcome:
        assert future_return is not None
        _add_outcome(session, window, future_return=future_return)
    return window


def _seed_history(session: Session, *, as_of: datetime, matching_positive: int, matching_negative: int, other_total: int) -> None:
    day = as_of - timedelta(days=365)
    for _ in range(matching_positive):
        _window(session, day, trend="UP", volatility="HIGH", future_return=0.01)
        day += timedelta(days=1)
    for _ in range(matching_negative):
        _window(session, day, trend="UP", volatility="HIGH", future_return=-0.01)
        day += timedelta(days=1)
    for _ in range(other_total):
        _window(session, day, trend="DOWN", volatility="LOW", future_return=0.01)
        day += timedelta(days=1)
    session.commit()


def _freeze_protocol(session: Session) -> tuple[ExperimentRun, ReplicationProtocol, ProspectiveContextForecastService]:
    source_experiment = ExperimentRun(
        experiment_code="context_dna_incremental_value_v1", experiment_version="context_dna_v1", name="source",
        dataset_hash="d" * 64, configuration_hash="c" * 64, similarity_method="dna_robust_cosine_v1",
        outcome_set_code="forward_outcomes_v1", outcome_set_version="forward_outcomes_v1",
        validation_method="context_matched_historical_as_of_v1",
    )
    session.add(source_experiment)
    session.flush()
    replication_protocol = ReplicationProtocol(
        protocol_code="context_dna_incremental_value_v1", protocol_version="protocol_v1",
        source_experiment_id=source_experiment.id, source_config_hash="c" * 64, source_dataset_hash="d" * 64,
        hypothesis_text="h", primary_method="dna_robust_cosine_v1", study_arm="same_instrument", timeframe="D1",
        window_lengths=[16, 32, 64], primary_horizon=20, neighbour_count=10, weighting="uniform_v1", episode_cap=1,
        primary_metrics=[], controls=[], success_criteria={}, failure_criteria={},
        independent_source_requirement="FOLLOW_UP_CONFIRMATORY_DIAGNOSTIC", configuration={}, configuration_hash="p" * 64,
        status="FROZEN", frozen_at=datetime.now(UTC),
    )
    session.add(replication_protocol)
    session.flush()
    record = ReplicationRecord(
        protocol_id=replication_protocol.id, lock_id=str(uuid4()), source_experiment_id=source_experiment.id,
        replication_experiment_id=source_experiment.id, provider_independence="CONFIRMED", decision="CONTEXT_SIGNAL_SUPPORTED_DNA_NO_INCREMENTAL_VALUE",
    )
    session.add(record)
    session.commit()
    service = ProspectiveContextForecastService(session)
    return source_experiment, replication_protocol, service


def test_freeze_protocol_is_idempotent_and_sources_from_step_10a4(db_session: Session) -> None:
    source_experiment, _replication_protocol, service = _freeze_protocol(db_session)

    first = service.freeze_protocol("market_context_forecast_v1", frozen_by="tester")
    second = service.freeze_protocol("market_context_forecast_v1")

    assert first.id == second.id
    assert first.status == "FROZEN"
    assert first.source_replication_experiment_id == source_experiment.id
    assert first.context_definition == "trend_volatility"
    assert first.fallback_hierarchy == ["trend_volatility", "trend_only", "unconditional"]


def test_frozen_protocol_configuration_cannot_be_silently_changed(db_session: Session) -> None:
    _source_experiment, _replication_protocol, service = _freeze_protocol(db_session)
    protocol = service.freeze_protocol("market_context_forecast_v1")

    protocol.configuration_hash = "tampered" * 8
    db_session.commit()

    with pytest.raises(ProspectiveProtocolImmutableError):
        service.freeze_protocol("market_context_forecast_v1")


def test_historical_probability_uses_most_specific_level_when_sufficient(db_session: Session) -> None:
    _source_experiment, _replication_protocol, service = _freeze_protocol(db_session)
    protocol = service.freeze_protocol("market_context_forecast_v1")
    as_of = datetime.now(UTC)
    _seed_history(db_session, as_of=as_of, matching_positive=25, matching_negative=15, other_total=50)

    estimate = service.historical_probability(
        protocol, instrument_id=INSTRUMENT_ID, timeframe_id=TIMEFRAME_ID, window_length=WINDOW_LENGTH,
        horizon_bars=HORIZON, as_of=as_of, context_values={"trend_state": "UP", "volatility_state": "HIGH"},
    )

    assert estimate["level_used"] == "trend_volatility"
    assert estimate["sample_count"] == 40
    assert estimate["positive_count"] == 25
    assert estimate["sufficiency"] == "FORECAST_AVAILABLE"
    assert 0.0 < estimate["probability_positive"] < 1.0
    assert estimate["confidence_lower"] < estimate["probability_positive"] < estimate["confidence_upper"]


def test_historical_probability_falls_back_when_specific_level_insufficient(db_session: Session) -> None:
    _source_experiment, _replication_protocol, service = _freeze_protocol(db_session)
    protocol = service.freeze_protocol("market_context_forecast_v1")
    as_of = datetime.now(UTC)
    # Few UP+HIGH rows (insufficient for trend_volatility) but many more UP+LOW rows,
    # so trend_only (matching on trend_state alone) has enough to avoid falling all
    # the way back to unconditional.
    day = as_of - timedelta(days=365)
    for _ in range(3):
        _window(db_session, day, trend="UP", volatility="HIGH", future_return=0.01)
        day += timedelta(days=1)
    for _ in range(2):
        _window(db_session, day, trend="UP", volatility="HIGH", future_return=-0.01)
        day += timedelta(days=1)
    for _ in range(40):
        _window(db_session, day, trend="UP", volatility="LOW", future_return=0.01)
        day += timedelta(days=1)
    for _ in range(100):
        _window(db_session, day, trend="DOWN", volatility="LOW", future_return=0.01)
        day += timedelta(days=1)
    db_session.commit()

    estimate = service.historical_probability(
        protocol, instrument_id=INSTRUMENT_ID, timeframe_id=TIMEFRAME_ID, window_length=WINDOW_LENGTH,
        horizon_bars=HORIZON, as_of=as_of, context_values={"trend_state": "UP", "volatility_state": "HIGH"},
    )

    assert estimate["level_used"] == "trend_only"
    assert estimate["fallback_reason"] == "FALLBACK_FROM_TREND_VOLATILITY"
    assert estimate["sample_count"] == 45  # all trend=UP rows regardless of volatility


def test_historical_probability_enforces_historical_as_of(db_session: Session) -> None:
    """Future matching windows (end_timestamp >= as_of) must never leak into the count."""
    _source_experiment, _replication_protocol, service = _freeze_protocol(db_session)
    protocol = service.freeze_protocol("market_context_forecast_v1")
    as_of = datetime.now(UTC)
    _seed_history(db_session, as_of=as_of, matching_positive=25, matching_negative=15, other_total=10)
    # A "future" matching window that must be excluded from the as-of count.
    _window(db_session, as_of + timedelta(days=5), trend="UP", volatility="HIGH", future_return=0.01)
    db_session.commit()

    estimate = service.historical_probability(
        protocol, instrument_id=INSTRUMENT_ID, timeframe_id=TIMEFRAME_ID, window_length=WINDOW_LENGTH,
        horizon_bars=HORIZON, as_of=as_of, context_values={"trend_state": "UP", "volatility_state": "HIGH"},
    )

    assert estimate["sample_count"] == 40  # unchanged by the future window


def test_create_forecast_is_idempotent(db_session: Session) -> None:
    _source_experiment, _replication_protocol, service = _freeze_protocol(db_session)
    protocol = service.freeze_protocol("market_context_forecast_v1")
    as_of = datetime.now(UTC) - timedelta(days=30)
    _seed_history(db_session, as_of=as_of, matching_positive=25, matching_negative=15, other_total=10)
    forecast_timestamp = as_of
    dummy_window_id = str(uuid4())

    first = service.create_forecast(
        protocol, instrument_id=INSTRUMENT_ID, timeframe_id=TIMEFRAME_ID, window_length=WINDOW_LENGTH,
        pattern_window_id=dummy_window_id, horizon_bars=HORIZON, forecast_timestamp=forecast_timestamp, data_cutoff_timestamp=as_of,
        context_code="UP|HIGH", context_values={"trend_state": "UP", "volatility_state": "HIGH"},
        source_hash="s" * 64, context_hash="c" * 64, now=as_of,
    )
    second = service.create_forecast(
        protocol, instrument_id=INSTRUMENT_ID, timeframe_id=TIMEFRAME_ID, window_length=WINDOW_LENGTH,
        pattern_window_id=dummy_window_id, horizon_bars=HORIZON, forecast_timestamp=forecast_timestamp, data_cutoff_timestamp=as_of,
        context_code="UP|HIGH", context_values={"trend_state": "UP", "volatility_state": "HIGH"},
        source_hash="s" * 64, context_hash="c" * 64, now=as_of,
    )

    assert first.id == second.id
    assert first.status == "PENDING_OUTCOME"
    assert first.provenance_class == "TRUE_PROSPECTIVE"


def test_create_forecast_rejects_retroactive_creation_before_cutoff(db_session: Session) -> None:
    _source_experiment, _replication_protocol, service = _freeze_protocol(db_session)
    protocol = service.freeze_protocol("market_context_forecast_v1")
    cutoff = datetime.now(UTC)

    with pytest.raises(RetroactiveForecastError):
        service.create_forecast(
            protocol, instrument_id=INSTRUMENT_ID, timeframe_id=TIMEFRAME_ID, window_length=WINDOW_LENGTH,
            pattern_window_id=str(uuid4()), horizon_bars=HORIZON, forecast_timestamp=cutoff, data_cutoff_timestamp=cutoff,
            context_code="UP|HIGH", context_values={"trend_state": "UP", "volatility_state": "HIGH"},
            source_hash="s" * 64, context_hash="c" * 64, now=cutoff - timedelta(days=1),
        )


def test_create_forecast_rejects_true_prospective_when_outcome_already_exists(db_session: Session) -> None:
    """Section 32: cannot backdate a TRUE_PROSPECTIVE forecast to a timestamp whose
    outcome is already known -- that would require BACKFILL_SIMULATION instead."""
    _source_experiment, _replication_protocol, service = _freeze_protocol(db_session)
    protocol = service.freeze_protocol("market_context_forecast_v1")
    as_of = datetime.now(UTC) - timedelta(days=100)
    _seed_history(db_session, as_of=as_of, matching_positive=25, matching_negative=15, other_total=10)
    # The window created by _seed_history for the final matching row already has a
    # completed OutcomeObservation -- pick it directly.
    known_window = db_session.query(PatternWindow).filter(PatternWindow.instrument_id == INSTRUMENT_ID).order_by(PatternWindow.end_timestamp.desc()).first()

    with pytest.raises(RetroactiveForecastError, match="RETROACTIVE_PROSPECTIVE_FORECAST_REJECTED.*outcome already exists"):
        service.create_forecast(
            protocol, instrument_id=INSTRUMENT_ID, timeframe_id=TIMEFRAME_ID, window_length=WINDOW_LENGTH,
            pattern_window_id=known_window.id, horizon_bars=HORIZON, forecast_timestamp=known_window.end_timestamp,
            data_cutoff_timestamp=known_window.end_timestamp,
            context_code="DOWN|LOW", context_values={"trend_state": "DOWN", "volatility_state": "LOW"},
            source_hash="s" * 64, context_hash="c" * 64, now=known_window.end_timestamp,
        )


def test_backfill_simulation_is_exempt_from_retroactive_guard(db_session: Session) -> None:
    _source_experiment, _replication_protocol, service = _freeze_protocol(db_session)
    protocol = service.freeze_protocol("market_context_forecast_v1")
    as_of = datetime.now(UTC) - timedelta(days=100)
    _seed_history(db_session, as_of=as_of, matching_positive=25, matching_negative=15, other_total=10)
    known_window = db_session.query(PatternWindow).filter(PatternWindow.instrument_id == INSTRUMENT_ID).order_by(PatternWindow.end_timestamp.desc()).first()

    forecast = service.create_forecast(
        protocol, instrument_id=INSTRUMENT_ID, timeframe_id=TIMEFRAME_ID, window_length=WINDOW_LENGTH,
        pattern_window_id=known_window.id, horizon_bars=HORIZON, forecast_timestamp=known_window.end_timestamp,
        data_cutoff_timestamp=known_window.end_timestamp,
        context_code="DOWN|LOW", context_values={"trend_state": "DOWN", "volatility_state": "LOW"},
        source_hash="s" * 64, context_hash="c" * 64, provenance_class="BACKFILL_SIMULATION", now=known_window.end_timestamp,
    )
    assert forecast.provenance_class == "BACKFILL_SIMULATION"


def test_mature_forecast_attaches_outcome_and_evaluation_snapshot_scores_it(db_session: Session) -> None:
    _source_experiment, _replication_protocol, service = _freeze_protocol(db_session)
    protocol = service.freeze_protocol("market_context_forecast_v1")
    as_of = datetime.now(UTC) - timedelta(days=100)
    _seed_history(db_session, as_of=as_of, matching_positive=25, matching_negative=15, other_total=10)
    db_session.commit()

    # A brand-new query window with no outcome yet -- this is the "PENDING_OUTCOME"
    # state a real prospective forecast starts in, before its horizon has elapsed.
    query_window = _window(db_session, as_of + timedelta(days=1), trend="UP", volatility="HIGH", future_return=None, with_outcome=False)
    db_session.commit()

    forecast = service.create_forecast(
        protocol, instrument_id=INSTRUMENT_ID, timeframe_id=TIMEFRAME_ID, window_length=WINDOW_LENGTH,
        pattern_window_id=query_window.id, horizon_bars=HORIZON, forecast_timestamp=query_window.end_timestamp,
        data_cutoff_timestamp=query_window.end_timestamp,
        context_code="UP|HIGH", context_values={"trend_state": "UP", "volatility_state": "HIGH"},
        source_hash="s" * 64, context_hash="c" * 64, now=query_window.end_timestamp,
    )
    assert forecast.status == "PENDING_OUTCOME"

    # Not yet maturable: no matching OutcomeObservation exists for this window yet.
    not_yet = service.mature_forecast(forecast, as_of=datetime.now(UTC))
    assert not_yet is None

    # Simulate the horizon elapsing: the outcome becomes available.
    _add_outcome(db_session, query_window, future_return=0.02)
    db_session.commit()

    outcome = service.mature_forecast(forecast, as_of=datetime.now(UTC))
    assert outcome is not None
    assert outcome.actual_direction == "POSITIVE"
    db_session.refresh(forecast)
    assert forecast.status == "MATURED"

    # Maturing an already-matured forecast is a no-op, not a duplicate outcome.
    again = service.mature_forecast(forecast, as_of=datetime.now(UTC))
    assert again is None

    snapshot = service.create_evaluation_snapshot(protocol)
    assert snapshot.matured_count == 1
    assert snapshot.forecast_count == 1
    assert snapshot.status == "PROSPECTIVE_EVIDENCE_ACCUMULATING"  # far below minimum_evidence_matured_forecasts


def test_create_forecast_rejects_unsupported_provenance_class(db_session: Session) -> None:
    _source_experiment, _replication_protocol, service = _freeze_protocol(db_session)
    protocol = service.freeze_protocol("market_context_forecast_v1")
    as_of = datetime.now(UTC) - timedelta(days=30)

    with pytest.raises(ValueError, match="UNSUPPORTED_PROVENANCE_CLASS"):
        service.create_forecast(
            protocol, instrument_id=INSTRUMENT_ID, timeframe_id=TIMEFRAME_ID, window_length=WINDOW_LENGTH,
            pattern_window_id=str(uuid4()), horizon_bars=HORIZON, forecast_timestamp=as_of, data_cutoff_timestamp=as_of,
            context_code="UP|HIGH", context_values={"trend_state": "UP", "volatility_state": "HIGH"},
            source_hash="s" * 64, context_hash="c" * 64, provenance_class="SPECULATIVE_GUESS", now=as_of,
        )


def test_retroactive_rejection_errors_carry_the_exact_error_code(db_session: Session) -> None:
    """Downstream callers (CLI/API) match on this literal code, not the full message."""
    _source_experiment, _replication_protocol, service = _freeze_protocol(db_session)
    protocol = service.freeze_protocol("market_context_forecast_v1")
    cutoff = datetime.now(UTC)

    with pytest.raises(RetroactiveForecastError, match="RETROACTIVE_PROSPECTIVE_FORECAST_REJECTED"):
        service.create_forecast(
            protocol, instrument_id=INSTRUMENT_ID, timeframe_id=TIMEFRAME_ID, window_length=WINDOW_LENGTH,
            pattern_window_id=str(uuid4()), horizon_bars=HORIZON, forecast_timestamp=cutoff, data_cutoff_timestamp=cutoff,
            context_code="UP|HIGH", context_values={"trend_state": "UP", "volatility_state": "HIGH"},
            source_hash="s" * 64, context_hash="c" * 64, now=cutoff - timedelta(days=1),
        )


def test_create_forecast_identity_is_scoped_by_provenance_class(db_session: Session) -> None:
    """The same pattern_window/horizon may carry one TRUE_PROSPECTIVE forecast and,
    separately, one BACKFILL_SIMULATION forecast without colliding -- but two calls
    with the same provenance_class are idempotent (return the same row)."""
    _source_experiment, _replication_protocol, service = _freeze_protocol(db_session)
    protocol = service.freeze_protocol("market_context_forecast_v1")
    as_of = datetime.now(UTC) - timedelta(days=100)
    _seed_history(db_session, as_of=as_of, matching_positive=25, matching_negative=15, other_total=10)
    known_window = db_session.query(PatternWindow).filter(PatternWindow.instrument_id == INSTRUMENT_ID).order_by(PatternWindow.end_timestamp.desc()).first()

    backfill_first = service.create_forecast(
        protocol, instrument_id=INSTRUMENT_ID, timeframe_id=TIMEFRAME_ID, window_length=WINDOW_LENGTH,
        pattern_window_id=known_window.id, horizon_bars=HORIZON, forecast_timestamp=known_window.end_timestamp,
        data_cutoff_timestamp=known_window.end_timestamp,
        context_code="DOWN|LOW", context_values={"trend_state": "DOWN", "volatility_state": "LOW"},
        source_hash="s" * 64, context_hash="c" * 64, provenance_class="BACKFILL_SIMULATION", now=known_window.end_timestamp,
    )
    backfill_second = service.create_forecast(
        protocol, instrument_id=INSTRUMENT_ID, timeframe_id=TIMEFRAME_ID, window_length=WINDOW_LENGTH,
        pattern_window_id=known_window.id, horizon_bars=HORIZON, forecast_timestamp=known_window.end_timestamp,
        data_cutoff_timestamp=known_window.end_timestamp,
        context_code="DOWN|LOW", context_values={"trend_state": "DOWN", "volatility_state": "LOW"},
        source_hash="s" * 64, context_hash="c" * 64, provenance_class="BACKFILL_SIMULATION", now=known_window.end_timestamp,
    )
    historical = service.create_forecast(
        protocol, instrument_id=INSTRUMENT_ID, timeframe_id=TIMEFRAME_ID, window_length=WINDOW_LENGTH,
        pattern_window_id=known_window.id, horizon_bars=HORIZON, forecast_timestamp=known_window.end_timestamp,
        data_cutoff_timestamp=known_window.end_timestamp,
        context_code="DOWN|LOW", context_values={"trend_state": "DOWN", "volatility_state": "LOW"},
        source_hash="s" * 64, context_hash="c" * 64, provenance_class="HISTORICAL_VALIDATION", now=known_window.end_timestamp,
    )

    assert backfill_first.id == backfill_second.id
    assert historical.id != backfill_first.id
    assert {backfill_first.provenance_class, historical.provenance_class} == {"BACKFILL_SIMULATION", "HISTORICAL_VALIDATION"}


def test_mature_forecast_populates_source_forward_outcome_reference(db_session: Session) -> None:
    _source_experiment, _replication_protocol, service = _freeze_protocol(db_session)
    protocol = service.freeze_protocol("market_context_forecast_v1")
    as_of = datetime.now(UTC) - timedelta(days=100)
    _seed_history(db_session, as_of=as_of, matching_positive=25, matching_negative=15, other_total=10)
    query_window = _window(db_session, as_of + timedelta(days=1), trend="UP", volatility="HIGH", future_return=None, with_outcome=False)
    db_session.commit()

    forecast = service.create_forecast(
        protocol, instrument_id=INSTRUMENT_ID, timeframe_id=TIMEFRAME_ID, window_length=WINDOW_LENGTH,
        pattern_window_id=query_window.id, horizon_bars=HORIZON, forecast_timestamp=query_window.end_timestamp,
        data_cutoff_timestamp=query_window.end_timestamp,
        context_code="UP|HIGH", context_values={"trend_state": "UP", "volatility_state": "HIGH"},
        source_hash=query_window.source_data_hash, context_hash="c" * 64, now=query_window.end_timestamp,
    )
    added_outcome = _add_outcome(db_session, query_window, future_return=0.02)
    db_session.commit()

    outcome = service.mature_forecast(forecast, as_of=datetime.now(UTC))

    assert outcome is not None
    assert outcome.source_forward_outcome_id == added_outcome.id
    assert outcome.source_outcome_hash == added_outcome.outcome_hash
    assert outcome.data_revision_detected is False


def test_mature_forecast_detects_data_revision_without_mutating_forecast(db_session: Session) -> None:
    """If the query window's source_data_hash changes after the forecast was created
    (e.g. the provider retroactively revised history), maturation must flag it on the
    outcome and must never rewrite the forecast's own frozen source_hash."""
    _source_experiment, _replication_protocol, service = _freeze_protocol(db_session)
    protocol = service.freeze_protocol("market_context_forecast_v1")
    as_of = datetime.now(UTC) - timedelta(days=100)
    _seed_history(db_session, as_of=as_of, matching_positive=25, matching_negative=15, other_total=10)
    query_window = _window(db_session, as_of + timedelta(days=1), trend="UP", volatility="HIGH", future_return=None, with_outcome=False)
    db_session.commit()

    forecast = service.create_forecast(
        protocol, instrument_id=INSTRUMENT_ID, timeframe_id=TIMEFRAME_ID, window_length=WINDOW_LENGTH,
        pattern_window_id=query_window.id, horizon_bars=HORIZON, forecast_timestamp=query_window.end_timestamp,
        data_cutoff_timestamp=query_window.end_timestamp,
        context_code="UP|HIGH", context_values={"trend_state": "UP", "volatility_state": "HIGH"},
        source_hash=query_window.source_data_hash, context_hash="c" * 64, now=query_window.end_timestamp,
    )
    original_source_hash = forecast.source_hash
    _add_outcome(db_session, query_window, future_return=0.02)
    # Simulate a retroactive provider data revision: the window's source hash changes
    # after the forecast was already created and frozen.
    query_window.source_data_hash = "revised-" + query_window.source_data_hash
    db_session.commit()

    outcome = service.mature_forecast(forecast, as_of=datetime.now(UTC))

    assert outcome is not None
    assert outcome.data_revision_detected is True
    db_session.refresh(forecast)
    assert forecast.source_hash == original_source_hash  # never silently mutated


def test_evaluation_snapshot_excludes_non_true_prospective_forecasts(db_session: Session) -> None:
    """A BACKFILL_SIMULATION forecast (created for testing/calibration) must never be
    counted toward the genuinely prospective evidence base."""
    _source_experiment, _replication_protocol, service = _freeze_protocol(db_session)
    protocol = service.freeze_protocol("market_context_forecast_v1")
    as_of = datetime.now(UTC) - timedelta(days=100)
    _seed_history(db_session, as_of=as_of, matching_positive=25, matching_negative=15, other_total=10)
    known_window = db_session.query(PatternWindow).filter(PatternWindow.instrument_id == INSTRUMENT_ID).order_by(PatternWindow.end_timestamp.desc()).first()

    service.create_forecast(
        protocol, instrument_id=INSTRUMENT_ID, timeframe_id=TIMEFRAME_ID, window_length=WINDOW_LENGTH,
        pattern_window_id=known_window.id, horizon_bars=HORIZON, forecast_timestamp=known_window.end_timestamp,
        data_cutoff_timestamp=known_window.end_timestamp,
        context_code="DOWN|LOW", context_values={"trend_state": "DOWN", "volatility_state": "LOW"},
        source_hash="s" * 64, context_hash="c" * 64, provenance_class="BACKFILL_SIMULATION", now=known_window.end_timestamp,
    )

    snapshot = service.create_evaluation_snapshot(protocol)

    assert snapshot.forecast_count == 0
    assert snapshot.matured_count == 0


def _insert_matured_forecast(
    session: Session,
    protocol,
    *,
    horizon: int,
    probability_positive: float,
    actual_positive: bool,
    forecast_timestamp: datetime,
) -> ProspectiveForecast:
    """Insert an already-matured forecast plus its outcome directly, bypassing the
    forecast/maturation pipeline -- the evaluation snapshot only reads these rows."""
    forecast = ProspectiveForecast(
        protocol_id=protocol.id, instrument_id=INSTRUMENT_ID, timeframe_id=TIMEFRAME_ID, window_length=WINDOW_LENGTH,
        pattern_window_id=str(uuid4()), forecast_timestamp=forecast_timestamp, data_cutoff_timestamp=forecast_timestamp,
        forecast_created_at=forecast_timestamp, horizon_bars=horizon, context_code="UP|HIGH",
        context_level_used="trend_volatility", probability_positive=probability_positive,
        probability_negative=1.0 - probability_positive, sample_count=100, positive_count=50, negative_count=50,
        confidence_lower=0.0, confidence_upper=1.0, provenance_class="TRUE_PROSPECTIVE", status="MATURED",
        source_hash="s" * 64, context_hash="c" * 64, historical_reference_hash="h" * 64, forecast_hash="f" * 64,
        provider_code="alpha_vantage_v1",
    )
    session.add(forecast)
    session.flush()
    session.add(
        ProspectiveForecastOutcome(
            forecast_id=forecast.id, source_forward_outcome_id=str(uuid4()), source_outcome_hash="o" * 64,
            actual_return=0.01 if actual_positive else -0.01,
            actual_direction="POSITIVE" if actual_positive else "NEGATIVE",
            future_bar_count=horizon, outcome_hash="p" * 64, data_revision_detected=False, matured_at=forecast_timestamp,
        )
    )
    return forecast


def test_evaluation_headline_and_evidence_gate_use_the_primary_horizon(db_session: Session) -> None:
    """Many matured secondary-horizon forecasts must not satisfy the frozen hypothesis,
    which is about the primary horizon. The headline metrics and the decision both come
    from the primary horizon; secondary horizons remain visible in per_horizon_metrics."""
    _source_experiment, _replication_protocol, service = _freeze_protocol(db_session)
    protocol = service.freeze_protocol("market_context_forecast_v1")
    as_of = datetime.now(UTC)
    _seed_history(db_session, as_of=as_of, matching_positive=50, matching_negative=50, other_total=0)
    for index in range(300):
        actual_positive = index % 2 == 0
        _insert_matured_forecast(
            db_session, protocol, horizon=5, probability_positive=0.9 if actual_positive else 0.1,
            actual_positive=actual_positive, forecast_timestamp=as_of - timedelta(days=200) + timedelta(hours=index),
        )
    db_session.commit()

    snapshot = service.create_evaluation_snapshot(protocol)

    assert snapshot.matured_count == 300
    assert snapshot.primary_horizon == HORIZON
    assert snapshot.primary_horizon_matured_count == 0
    assert snapshot.brier_score is None  # nothing matured at the primary horizon yet
    assert snapshot.status == "PROSPECTIVE_EVIDENCE_ACCUMULATING"
    assert set(snapshot.per_horizon_metrics) == {"5"}


def test_evaluation_reaches_supported_once_primary_horizon_evidence_and_ci_allow_it(db_session: Session) -> None:
    """The freeze's `SUPPORTED` branch was previously unreachable because
    `bootstrap_ci_low` was always None. With the paired block-bootstrap wired in, a
    sufficiently large primary-horizon sample with genuine skill must reach it."""
    _source_experiment, _replication_protocol, service = _freeze_protocol(db_session)
    protocol = service.freeze_protocol("market_context_forecast_v1")
    as_of = datetime.now(UTC)
    # Unconditional base rate for horizon 20 = 50 / 200 = 0.25.
    _seed_history(db_session, as_of=as_of, matching_positive=50, matching_negative=50, other_total=100)
    for index in range(260):
        actual_positive = index % 2 == 0
        _insert_matured_forecast(
            db_session, protocol, horizon=HORIZON, probability_positive=0.95 if actual_positive else 0.05,
            actual_positive=actual_positive, forecast_timestamp=as_of - timedelta(days=100) + timedelta(hours=index),
        )
    db_session.commit()

    snapshot = service.create_evaluation_snapshot(protocol)

    assert snapshot.primary_horizon_matured_count == 260
    assert snapshot.matured_count == 260
    assert snapshot.brier_skill_vs_unconditional > 0.0
    assert snapshot.bootstrap_ci_low is not None and snapshot.bootstrap_ci_low > 0.0
    assert snapshot.bootstrap_ci_high is not None
    assert snapshot.status == "PROSPECTIVE_CONTEXT_SIGNAL_SUPPORTED"
    assert snapshot.per_horizon_metrics[str(HORIZON)]["sample_count"] == 260


def test_evaluation_baseline_is_as_of_each_forecasts_own_cutoff(db_session: Session) -> None:
    """The unconditional baseline must be evaluated as-of the forecast's own data cutoff,
    not as-of evaluation time -- otherwise it sees outcomes the forecast never could and
    understates skill."""
    _source_experiment, _replication_protocol, service = _freeze_protocol(db_session)
    protocol = service.freeze_protocol("market_context_forecast_v1")
    now = datetime.now(UTC)
    cutoff = now - timedelta(days=101)

    # History strictly BEFORE the cutoff: all negative -> as-of-cutoff base rate 0.0.
    for offset in range(300, 200, -1):
        _window(db_session, now - timedelta(days=offset), trend="UP", volatility="HIGH", future_return=-0.01)
    # History AFTER the cutoff but before evaluation time: all positive -> an as-of-now
    # baseline would instead read 0.5.
    for offset in range(101, 1, -1):
        _window(db_session, now - timedelta(days=offset), trend="UP", volatility="HIGH", future_return=0.01)
    db_session.commit()

    _insert_matured_forecast(
        db_session, protocol, horizon=HORIZON, probability_positive=0.5, actual_positive=True, forecast_timestamp=cutoff
    )
    _insert_matured_forecast(
        db_session, protocol, horizon=HORIZON, probability_positive=0.5, actual_positive=False, forecast_timestamp=cutoff
    )
    db_session.commit()

    snapshot = service.create_evaluation_snapshot(protocol, as_of=now)

    # Model Brier 0.25; as-of-cutoff baseline (p0=0.0) Brier 0.5 -> skill 0.5.
    # An as-of-now baseline (p0=0.5) would give Brier 0.25 -> skill 0.0.
    assert snapshot.primary_horizon_matured_count == 2
    assert snapshot.per_horizon_metrics[str(HORIZON)]["brier_skill_vs_unconditional"] == pytest.approx(0.5)
