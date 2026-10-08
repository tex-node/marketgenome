from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from market_genome_domain.models import (
    ExperimentRun,
    ProspectiveEvaluationSnapshot,
    ProspectiveForecast,
    ProspectiveForecastOutcome,
    ProspectiveProtocol,
    ReplicationProtocol,
    ReplicationRecord,
)
from market_genome_shared.hashing import sha256_canonical
from sqlalchemy import text
from sqlalchemy.orm import Session

from market_genome_prospective.definitions import (
    ProspectiveProtocolDefinition,
    get_prospective_protocol_definition,
)
from market_genome_prospective.forecast_analysis import (
    PROVENANCE_CLASSES,
    FallbackLevelStats,
    ProspectiveDecisionResult,
    classify_prospective_decision,
    classify_sample_sufficiency,
    detect_data_revision,
    laplace_smoothed_probability,
    per_horizon_evaluation,
    select_fallback_level,
    wilson_confidence_interval,
)

FALLBACK_LEVEL_DIMENSIONS: dict[str, tuple[str, ...]] = {
    "trend_volatility": ("trend_state", "volatility_state"),
    "trend_only": ("trend_state",),
    "unconditional": (),
}


class ProspectiveProtocolImmutableError(ValueError):
    pass


class RetroactiveForecastError(ValueError):
    pass


class ProspectiveContextForecastService:
    def __init__(self, session: Session):
        self.session = session

    # ------------------------------------------------------------------ protocol

    def freeze_protocol(self, protocol_code: str, *, frozen_by: str | None = None) -> ProspectiveProtocol:
        definition = get_prospective_protocol_definition(protocol_code)
        replication_protocol = (
            self.session.query(ReplicationProtocol)
            .filter(ReplicationProtocol.protocol_code == "context_dna_incremental_value_v1")
            .order_by(ReplicationProtocol.created_at.desc())
            .first()
        )
        if replication_protocol is None:
            raise ValueError("SOURCE_REPLICATION_PROTOCOL_NOT_FOUND")
        record = (
            self.session.query(ReplicationRecord)
            .filter(ReplicationRecord.protocol_id == replication_protocol.id)
            .order_by(ReplicationRecord.created_at.desc())
            .first()
        )
        if record is None or record.replication_experiment_id is None:
            raise ValueError("SOURCE_REPLICATION_EXPERIMENT_NOT_FOUND")
        source_experiment = self.session.get(ExperimentRun, record.replication_experiment_id)
        if source_experiment is None:
            raise ValueError("SOURCE_REPLICATION_EXPERIMENT_NOT_FOUND")

        configuration = self._protocol_configuration(definition)
        configuration_hash = sha256_canonical(configuration)

        existing = (
            self.session.query(ProspectiveProtocol)
            .filter(
                ProspectiveProtocol.protocol_code == definition.protocol_code,
                ProspectiveProtocol.protocol_version == definition.protocol_version,
            )
            .one_or_none()
        )
        if existing is not None:
            if existing.status == "FROZEN" and existing.configuration_hash != configuration_hash:
                raise ProspectiveProtocolImmutableError("PROSPECTIVE_PROTOCOL_ALREADY_FROZEN_CONFIGURATION_IMMUTABLE")
            return existing

        protocol = ProspectiveProtocol(
            protocol_code=definition.protocol_code,
            protocol_version=definition.protocol_version,
            source_replication_protocol_id=replication_protocol.id,
            source_replication_experiment_id=source_experiment.id,
            hypothesis_text=definition.hypothesis_text,
            context_definition=definition.context_definition,
            context_producer_code=definition.context_producer_code,
            context_producer_version=definition.context_producer_version,
            fallback_hierarchy=list(definition.fallback_hierarchy),
            timeframe=definition.timeframe,
            window_lengths=list(definition.window_lengths),
            primary_horizon=definition.primary_horizon,
            secondary_horizons=list(definition.secondary_horizons),
            probability_method=definition.probability_method,
            smoothing_method=definition.smoothing_method,
            smoothing_parameters=definition.smoothing_parameters,
            minimum_historical_sample=definition.minimum_historical_sample,
            calibration_method=definition.calibration_method,
            refresh_policy=definition.refresh_policy,
            provider_code=definition.provider_code,
            instrument_universe=list(definition.instrument_universe),
            success_criteria=definition.success_criteria,
            minimum_evidence_matured_forecasts=definition.minimum_evidence_matured_forecasts,
            preferred_evidence_matured_forecasts=definition.preferred_evidence_matured_forecasts,
            configuration=configuration,
            configuration_hash=configuration_hash,
            status="FROZEN",
            frozen_at=datetime.now(UTC),
            frozen_by=frozen_by,
        )
        self.session.add(protocol)
        self.session.commit()
        return protocol

    def _protocol_configuration(self, definition: ProspectiveProtocolDefinition) -> dict[str, Any]:
        return {
            "protocol_code": definition.protocol_code,
            "protocol_version": definition.protocol_version,
            "hypothesis_text": definition.hypothesis_text,
            "context_definition": definition.context_definition,
            "context_producer_code": definition.context_producer_code,
            "context_producer_version": definition.context_producer_version,
            "fallback_hierarchy": list(definition.fallback_hierarchy),
            "timeframe": definition.timeframe,
            "window_lengths": list(definition.window_lengths),
            "primary_horizon": definition.primary_horizon,
            "secondary_horizons": list(definition.secondary_horizons),
            "probability_method": definition.probability_method,
            "smoothing_method": definition.smoothing_method,
            "smoothing_parameters": definition.smoothing_parameters,
            "minimum_historical_sample": definition.minimum_historical_sample,
            "calibration_method": definition.calibration_method,
            "refresh_policy": definition.refresh_policy,
            "provider_code": definition.provider_code,
            "instrument_universe": list(definition.instrument_universe),
            "success_criteria": definition.success_criteria,
        }

    # ------------------------------------------------------------- estimation

    def _level_stats(
        self,
        *,
        instrument_id: str,
        timeframe_id: str,
        window_length: int,
        horizon_bars: int,
        as_of: datetime,
        dims: tuple[str, ...],
        context_values: dict[str, Any],
    ) -> tuple[int, int]:
        """Historical-as-of positive/total counts for one fallback level. Empty dims
        means unconditional (no context filter at all)."""
        filters = ["pw.instrument_id = :instrument_id", "pw.timeframe_id = :timeframe_id", "pw.window_length = :window_length", "pw.end_timestamp < :as_of", "oo.horizon_bars = :horizon_bars", "oo.is_complete is true"]
        params: dict[str, Any] = {
            "instrument_id": instrument_id, "timeframe_id": timeframe_id, "window_length": window_length,
            "as_of": as_of, "horizon_bars": horizon_bars,
        }
        joins = "join market_contexts mc on mc.pattern_window_id = pw.id" if dims else ""
        for dim in dims:
            filters.append(f"mc.{dim} = :{dim}")
            params[dim] = context_values.get(dim)
        sql = text(
            f"""
            select
              count(*) filter (where oo.future_simple_return > 0) as positive_count,
              count(*) as total_count
            from pattern_windows pw
            join outcome_observations oo on oo.pattern_window_id = pw.id
            {joins}
            where {' and '.join(filters)}
            """
        )
        row = self.session.execute(sql, params).mappings().one()
        return int(row["positive_count"] or 0), int(row["total_count"] or 0)

    def historical_probability(
        self,
        protocol: ProspectiveProtocol,
        *,
        instrument_id: str,
        timeframe_id: str,
        window_length: int,
        horizon_bars: int,
        as_of: datetime,
        context_values: dict[str, Any],
    ) -> dict[str, Any]:
        levels = []
        for level_name in protocol.fallback_hierarchy:
            dims = FALLBACK_LEVEL_DIMENSIONS.get(level_name)
            if dims is None:
                raise ValueError(f"UNSUPPORTED_FALLBACK_LEVEL:{level_name}")
            positive, total = self._level_stats(
                instrument_id=instrument_id, timeframe_id=timeframe_id, window_length=window_length,
                horizon_bars=horizon_bars, as_of=as_of, dims=dims, context_values=context_values,
            )
            levels.append(FallbackLevelStats(level_name, positive, total))
        selection = select_fallback_level(levels, minimum=protocol.minimum_historical_sample)
        sufficiency = classify_sample_sufficiency(selection.total_count, minimum=protocol.minimum_historical_sample)
        params = protocol.smoothing_parameters
        probability_positive = laplace_smoothed_probability(
            selection.positive_count, selection.total_count, alpha=float(params.get("alpha", 1.0)), beta=float(params.get("beta", 1.0))
        )
        ci_low, ci_high = wilson_confidence_interval(selection.positive_count, selection.total_count)
        return {
            "level_used": selection.level_used,
            "fallback_reason": selection.fallback_reason,
            "sample_count": selection.total_count,
            "positive_count": selection.positive_count,
            "negative_count": selection.total_count - selection.positive_count,
            "probability_positive": probability_positive,
            "probability_negative": 1.0 - probability_positive,
            "confidence_lower": ci_low,
            "confidence_upper": ci_high,
            "sufficiency": sufficiency,
            "levels": [{"level": item.level, "positive_count": item.positive_count, "total_count": item.total_count} for item in levels],
        }

    # -------------------------------------------------------------- forecast

    def create_forecast(
        self,
        protocol: ProspectiveProtocol,
        *,
        instrument_id: str,
        timeframe_id: str,
        window_length: int,
        pattern_window_id: str,
        horizon_bars: int,
        forecast_timestamp: datetime,
        data_cutoff_timestamp: datetime,
        context_code: str,
        context_values: dict[str, Any],
        source_hash: str,
        context_hash: str,
        provenance_class: str = "TRUE_PROSPECTIVE",
        now: datetime | None = None,
    ) -> ProspectiveForecast:
        if provenance_class not in PROVENANCE_CLASSES:
            raise ValueError(f"UNSUPPORTED_PROVENANCE_CLASS:{provenance_class}")
        forecast_created_at = now or datetime.now(UTC)
        if provenance_class == "TRUE_PROSPECTIVE":
            if forecast_created_at < data_cutoff_timestamp:
                raise RetroactiveForecastError(
                    "RETROACTIVE_PROSPECTIVE_FORECAST_REJECTED: TRUE_PROSPECTIVE forecast cannot be created "
                    "before its own data cutoff timestamp"
                )
            outcome_already_known = self.session.execute(
                text(
                    """
                    select 1 from outcome_observations oo
                    where oo.pattern_window_id = :pattern_window_id
                      and oo.horizon_bars = :horizon_bars and oo.is_complete is true
                    limit 1
                    """
                ),
                {"pattern_window_id": pattern_window_id, "horizon_bars": horizon_bars},
            ).first()
            if outcome_already_known is not None:
                raise RetroactiveForecastError(
                    "RETROACTIVE_PROSPECTIVE_FORECAST_REJECTED: outcome already exists for this "
                    "instrument/window/horizon -- a TRUE_PROSPECTIVE forecast cannot be created for a timestamp "
                    "whose future is already known; use BACKFILL_SIMULATION or HISTORICAL_VALIDATION instead"
                )

        existing = (
            self.session.query(ProspectiveForecast)
            .filter(
                ProspectiveForecast.protocol_id == protocol.id,
                ProspectiveForecast.pattern_window_id == pattern_window_id,
                ProspectiveForecast.horizon_bars == horizon_bars,
                ProspectiveForecast.provenance_class == provenance_class,
            )
            .one_or_none()
        )
        if existing is not None:
            return existing

        estimate = self.historical_probability(
            protocol, instrument_id=instrument_id, timeframe_id=timeframe_id, window_length=window_length,
            horizon_bars=horizon_bars, as_of=data_cutoff_timestamp, context_values=context_values,
        )
        historical_reference_payload = {"protocol_id": protocol.id, "as_of": data_cutoff_timestamp.isoformat(), "levels": estimate["levels"]}
        historical_reference_hash = sha256_canonical(historical_reference_payload)
        forecast_payload = {
            "protocol_id": protocol.id, "instrument_id": instrument_id, "timeframe_id": timeframe_id,
            "window_length": window_length, "forecast_timestamp": forecast_timestamp.isoformat(),
            "horizon_bars": horizon_bars, "context_code": context_code, "probability_positive": estimate["probability_positive"],
            "source_hash": source_hash, "context_hash": context_hash, "historical_reference_hash": historical_reference_hash,
        }
        status = "INSUFFICIENT_CONTEXT_HISTORY" if estimate["sufficiency"] == "INSUFFICIENT_CONTEXT_HISTORY" else "PENDING_OUTCOME"

        forecast = ProspectiveForecast(
            protocol_id=protocol.id, instrument_id=instrument_id, timeframe_id=timeframe_id, window_length=window_length,
            pattern_window_id=pattern_window_id,
            forecast_timestamp=forecast_timestamp, data_cutoff_timestamp=data_cutoff_timestamp, forecast_created_at=forecast_created_at,
            horizon_bars=horizon_bars, context_code=context_code, context_level_used=estimate["level_used"],
            fallback_reason=estimate["fallback_reason"], probability_positive=estimate["probability_positive"],
            probability_negative=estimate["probability_negative"], sample_count=estimate["sample_count"],
            positive_count=estimate["positive_count"], negative_count=estimate["negative_count"],
            confidence_lower=estimate["confidence_lower"], confidence_upper=estimate["confidence_upper"],
            provenance_class=provenance_class, status=status, source_hash=source_hash, context_hash=context_hash,
            historical_reference_hash=historical_reference_hash, forecast_hash=sha256_canonical(forecast_payload),
            provider_code=protocol.provider_code,
        )
        self.session.add(forecast)
        self.session.commit()
        return forecast

    # -------------------------------------------------------------- maturation

    def mature_forecast(self, forecast: ProspectiveForecast, *, as_of: datetime) -> ProspectiveForecastOutcome | None:
        if forecast.status != "PENDING_OUTCOME":
            return None
        sql = text(
            """
            select oo.id as observation_id, oo.future_simple_return, oo.maximum_favourable_excursion,
                   oo.maximum_adverse_excursion, oo.available_future_bars, oo.future_bar_hash, oo.outcome_hash
            from outcome_observations oo
            where oo.pattern_window_id = :pattern_window_id
              and oo.horizon_bars = :horizon_bars and oo.is_complete is true
            """
        )
        row = self.session.execute(
            sql, {"pattern_window_id": forecast.pattern_window_id, "horizon_bars": forecast.horizon_bars}
        ).mappings().one_or_none()
        if row is None:
            return None  # outcome not yet matured

        # Data-revision guard: if the query window's source data hash has changed since
        # this forecast was created (e.g. a provider retroactively revised history and
        # the window was rebuilt), flag it -- never silently rewrite the forecast.
        current_source_hash = self.session.execute(
            text("select source_data_hash from pattern_windows where id = :id"), {"id": forecast.pattern_window_id}
        ).scalar_one_or_none()
        revision_detected = current_source_hash is not None and detect_data_revision(forecast.source_hash, current_source_hash)

        actual_return = float(row["future_simple_return"])
        outcome_payload = {"forecast_id": forecast.id, "actual_return": actual_return, "future_bar_hash": row["future_bar_hash"]}
        outcome = ProspectiveForecastOutcome(
            forecast_id=forecast.id, source_forward_outcome_id=row["observation_id"], source_outcome_hash=row["outcome_hash"],
            actual_return=actual_return,
            actual_direction="POSITIVE" if actual_return > 0 else "NEGATIVE",
            maximum_favourable_excursion=float(row["maximum_favourable_excursion"]) if row["maximum_favourable_excursion"] is not None else None,
            maximum_adverse_excursion=float(row["maximum_adverse_excursion"]) if row["maximum_adverse_excursion"] is not None else None,
            future_bar_count=int(row["available_future_bars"]), outcome_hash=sha256_canonical(outcome_payload),
            data_revision_detected=revision_detected, matured_at=as_of,
        )
        forecast.status = "MATURED"
        self.session.add(outcome)
        self.session.commit()
        return outcome

    def mature_eligible(self, protocol_id: str, *, as_of: datetime, limit: int = 10_000) -> list[ProspectiveForecastOutcome]:
        pending = (
            self.session.query(ProspectiveForecast)
            .filter(ProspectiveForecast.protocol_id == protocol_id, ProspectiveForecast.status == "PENDING_OUTCOME")
            .limit(limit)
            .all()
        )
        matured = []
        for forecast in pending:
            outcome = self.mature_forecast(forecast, as_of=as_of)
            if outcome is not None:
                matured.append(outcome)
        return matured

    # ------------------------------------------------------------- evaluation

    def create_evaluation_snapshot(self, protocol: ProspectiveProtocol, *, as_of: datetime | None = None) -> ProspectiveEvaluationSnapshot:
        """Primary evaluation is restricted to provenance_class == TRUE_PROSPECTIVE --
        BACKFILL_SIMULATION and HISTORICAL_VALIDATION forecasts exist for testing and
        calibration and must never be mixed into the genuinely prospective evidence base.

        Metrics are computed **per horizon**, and each forecast is scored against the
        historical unconditional base rate for its OWN instrument/window-length/horizon,
        **evaluated as-of that forecast's own `data_cutoff_timestamp`** (exactly what the
        forecast itself was permitted to know) -- so a pooled sample can neither compare one
        horizon's/instrument's forecasts against another's base rate, nor let the baseline
        see data the forecast did not. The snapshot's headline scalar fields and the
        decision both use the protocol's declared primary horizon (the horizon the frozen
        hypothesis is actually about); every horizon's full metric set, including its
        paired block-bootstrap interval, is persisted in `per_horizon_metrics`."""
        as_of = as_of or datetime.now(UTC)
        forecasts = (
            self.session.query(ProspectiveForecast)
            .filter(ProspectiveForecast.protocol_id == protocol.id, ProspectiveForecast.provenance_class == "TRUE_PROSPECTIVE")
            .all()
        )
        matured = [f for f in forecasts if f.status == "MATURED"]
        rows: list[dict[str, Any]] = []
        baseline_cache: dict[tuple[str, str, int, int, datetime], float | None] = {}
        for forecast in matured:
            outcome = (
                self.session.query(ProspectiveForecastOutcome)
                .filter(ProspectiveForecastOutcome.forecast_id == forecast.id)
                .one_or_none()
            )
            if outcome is None:
                continue
            key = (
                forecast.instrument_id, forecast.timeframe_id, forecast.window_length,
                forecast.horizon_bars, forecast.data_cutoff_timestamp,
            )
            if key not in baseline_cache:
                positive, total = self._level_stats(
                    instrument_id=forecast.instrument_id, timeframe_id=forecast.timeframe_id,
                    window_length=forecast.window_length, horizon_bars=forecast.horizon_bars,
                    as_of=forecast.data_cutoff_timestamp, dims=(), context_values={},
                )
                baseline_cache[key] = positive / total if total > 0 else None
            rows.append(
                {
                    "horizon_bars": forecast.horizon_bars,
                    "forecast_timestamp": forecast.forecast_timestamp,
                    "probability_positive": float(forecast.probability_positive),
                    "actual_positive": outcome.actual_direction == "POSITIVE",
                    "unconditional_probability": baseline_cache[key],
                }
            )
        rows.sort(key=lambda row: row["forecast_timestamp"])

        seed = int(sha256_canonical({"protocol_id": protocol.id, "primary_horizon": protocol.primary_horizon})[:16], 16)
        per_horizon = per_horizon_evaluation(rows, seed=seed)
        primary_metrics = per_horizon.get(str(protocol.primary_horizon), {"sample_count": 0})
        primary_matured_count = int(primary_metrics.get("sample_count", 0))

        decision = classify_prospective_decision(
            matured_count=primary_matured_count,
            minimum_evidence=protocol.minimum_evidence_matured_forecasts,
            preferred_evidence=protocol.preferred_evidence_matured_forecasts,
            brier_skill_vs_unconditional=primary_metrics.get("brier_skill_vs_unconditional"),
            bootstrap_ci_low=primary_metrics.get("bootstrap_ci_low"),
        )
        snapshot_payload = {
            "protocol_id": protocol.id,
            "as_of": as_of.isoformat(),
            "primary_horizon": protocol.primary_horizon,
            "primary_horizon_matured_count": primary_matured_count,
            "evaluation": primary_metrics,
            "per_horizon_metrics": per_horizon,
            "decision": decision.decision,
        }
        snapshot = ProspectiveEvaluationSnapshot(
            protocol_id=protocol.id, as_of=as_of, forecast_count=len(forecasts), matured_count=len(rows),
            primary_horizon=protocol.primary_horizon, primary_horizon_matured_count=primary_matured_count,
            brier_score=primary_metrics.get("brier_score"),
            brier_skill_vs_unconditional=primary_metrics.get("brier_skill_vs_unconditional"),
            log_loss=primary_metrics.get("log_loss"), expected_calibration_error=primary_metrics.get("expected_calibration_error"),
            direction_accuracy=primary_metrics.get("direction_accuracy"), calibration_bins=primary_metrics.get("calibration_bins", []),
            balanced_accuracy=primary_metrics.get("balanced_accuracy"), mcc=primary_metrics.get("mcc"),
            bootstrap_ci_low=primary_metrics.get("bootstrap_ci_low"), bootstrap_ci_high=primary_metrics.get("bootstrap_ci_high"),
            per_horizon_metrics=per_horizon,
            status=decision.decision, snapshot_hash=sha256_canonical(snapshot_payload),
        )
        self.session.add(snapshot)
        self.session.commit()
        return snapshot


__all__ = [
    "FALLBACK_LEVEL_DIMENSIONS",
    "ProspectiveContextForecastService",
    "ProspectiveDecisionResult",
    "ProspectiveProtocolImmutableError",
    "RetroactiveForecastError",
    "detect_data_revision",
]
