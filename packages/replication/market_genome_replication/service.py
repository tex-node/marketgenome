from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from market_genome_domain.models import (
    ExperimentRun,
    ReplicationLock,
    ReplicationProtocol,
    ReplicationRecord,
    StudyManifest,
)
from market_genome_shared.hashing import sha256_canonical
from sqlalchemy.orm import Session

from market_genome_replication.definitions import (
    REPLICATION_DECISIONS,
    ReplicationProtocolDefinition,
    get_replication_protocol_definition,
)


class ReplicationProtocolImmutableError(ValueError):
    pass


@dataclass(frozen=True)
class ReplicationDecisionResult:
    decision: str
    rationale: str


class ReplicationService:
    def __init__(self, session: Session):
        self.session = session

    def freeze_protocol(
        self,
        protocol_code: str,
        source_experiment_id: str,
        *,
        frozen_by: str | None = None,
    ) -> ReplicationProtocol:
        definition = get_replication_protocol_definition(protocol_code)
        source_experiment = self.session.get(ExperimentRun, source_experiment_id)
        if source_experiment is None:
            raise ValueError("SOURCE_EXPERIMENT_NOT_FOUND")

        configuration = self._protocol_configuration(definition)
        configuration_hash = sha256_canonical(configuration)

        existing = (
            self.session.query(ReplicationProtocol)
            .filter(
                ReplicationProtocol.protocol_code == definition.protocol_code,
                ReplicationProtocol.protocol_version == definition.protocol_version,
            )
            .one_or_none()
        )
        if existing is not None:
            if existing.status == "FROZEN" and existing.configuration_hash != configuration_hash:
                raise ReplicationProtocolImmutableError(
                    "REPLICATION_PROTOCOL_ALREADY_FROZEN_CONFIGURATION_IMMUTABLE"
                )
            return existing

        protocol = ReplicationProtocol(
            protocol_code=definition.protocol_code,
            protocol_version=definition.protocol_version,
            source_experiment_id=source_experiment.id,
            source_config_hash=source_experiment.configuration_hash,
            source_dataset_hash=source_experiment.dataset_hash,
            hypothesis_text=definition.hypothesis_text,
            primary_method=definition.primary_method,
            study_arm=definition.study_arm,
            timeframe=definition.timeframe,
            window_lengths=list(definition.window_lengths),
            primary_horizon=definition.primary_horizon,
            neighbour_count=definition.neighbour_count,
            weighting=definition.weighting,
            episode_cap=definition.episode_cap,
            primary_metrics=list(definition.primary_metrics),
            controls=list(definition.controls),
            success_criteria=definition.success_criteria,
            failure_criteria=definition.failure_criteria,
            independent_source_requirement=definition.independent_source_requirement,
            configuration=configuration,
            configuration_hash=configuration_hash,
            status="FROZEN",
            frozen_at=datetime.now(UTC),
            frozen_by=frozen_by,
        )
        self.session.add(protocol)
        self.session.commit()
        return protocol

    def _protocol_configuration(self, definition: ReplicationProtocolDefinition) -> dict[str, Any]:
        return {
            "protocol_code": definition.protocol_code,
            "protocol_version": definition.protocol_version,
            "hypothesis_text": definition.hypothesis_text,
            "primary_method": definition.primary_method,
            "study_arm": definition.study_arm,
            "timeframe": definition.timeframe,
            "window_lengths": list(definition.window_lengths),
            "primary_horizon": definition.primary_horizon,
            "neighbour_count": definition.neighbour_count,
            "weighting": definition.weighting,
            "episode_cap": definition.episode_cap,
            "primary_metrics": list(definition.primary_metrics),
            "controls": list(definition.controls),
            "success_criteria": definition.success_criteria,
            "failure_criteria": definition.failure_criteria,
            "independent_source_requirement": definition.independent_source_requirement,
        }

    def create_lock(
        self,
        protocol_id: str,
        *,
        study_id: str,
        source_study_id: str,
        dataset_hash: str,
        provider_code: str,
        provider_provenance_hash: str,
        instrument_universe: list[str],
        date_range: dict[str, Any],
        locked_by: str | None = None,
    ) -> ReplicationLock:
        protocol = self.session.get(ReplicationProtocol, protocol_id)
        if protocol is None:
            raise ValueError("REPLICATION_PROTOCOL_NOT_FOUND")
        if protocol.status != "FROZEN":
            raise ValueError("REPLICATION_PROTOCOL_NOT_FROZEN")
        if self.session.get(StudyManifest, study_id) is None:
            raise ValueError("STUDY_NOT_FOUND")
        if self.session.get(StudyManifest, source_study_id) is None:
            raise ValueError("SOURCE_STUDY_NOT_FOUND")

        existing = (
            self.session.query(ReplicationLock)
            .filter(ReplicationLock.protocol_id == protocol_id, ReplicationLock.study_id == study_id)
            .one_or_none()
        )
        if existing is not None:
            return existing

        payload = {
            "protocol_id": protocol_id,
            "protocol_configuration_hash": protocol.configuration_hash,
            "study_id": study_id,
            "source_study_id": source_study_id,
            "dataset_hash": dataset_hash,
            "provider_code": provider_code,
            "provider_provenance_hash": provider_provenance_hash,
            "instrument_universe": sorted(instrument_universe),
            "date_range": date_range,
        }
        lock = ReplicationLock(
            protocol_id=protocol_id,
            study_id=study_id,
            source_study_id=source_study_id,
            dataset_hash=dataset_hash,
            provider_code=provider_code,
            provider_provenance_hash=provider_provenance_hash,
            instrument_universe=sorted(instrument_universe),
            date_range=date_range,
            lock_payload=payload,
            lock_hash=sha256_canonical(payload),
            status="LOCKED",
            locked_at=datetime.now(UTC),
            locked_by=locked_by,
        )
        self.session.add(lock)
        self.session.commit()
        return lock

    def create_record(
        self,
        lock_id: str,
        *,
        provider_independence: str,
        independence_notes: str | None = None,
    ) -> ReplicationRecord:
        lock = self.session.get(ReplicationLock, lock_id)
        if lock is None:
            raise ValueError("REPLICATION_LOCK_NOT_FOUND")
        existing = self.session.query(ReplicationRecord).filter(ReplicationRecord.lock_id == lock_id).one_or_none()
        if existing is not None:
            return existing
        record = ReplicationRecord(
            protocol_id=lock.protocol_id,
            lock_id=lock.id,
            source_experiment_id=self.session.get(ReplicationProtocol, lock.protocol_id).source_experiment_id,
            provider_independence=provider_independence,
            independence_notes=independence_notes,
            decision="PENDING",
        )
        self.session.add(record)
        self.session.commit()
        return record

    def decide(
        self,
        record_id: str,
        *,
        replication_experiment_id: str,
        decision: str,
        decision_rationale: str,
        comparison: dict[str, Any],
        decision_vocabulary: tuple[str, ...] = REPLICATION_DECISIONS,
    ) -> ReplicationRecord:
        if decision not in decision_vocabulary:
            raise ValueError("UNSUPPORTED_REPLICATION_DECISION")
        record = self.session.get(ReplicationRecord, record_id)
        if record is None:
            raise ValueError("REPLICATION_RECORD_NOT_FOUND")
        if record.decision != "PENDING":
            return record
        record.replication_experiment_id = replication_experiment_id
        record.decision = decision
        record.decision_rationale = decision_rationale
        record.comparison = comparison
        record.completed_at = datetime.now(UTC)
        self.session.commit()
        return record


def classify_replication_decision(
    *,
    brier_skill_vs_unconditional: float | None,
    brier_skill_vs_same_context_random: float | None,
    effect_direction_consistent: bool,
    adequate_episode_diversity: bool,
    single_instrument_dependent: bool,
    acceptable_calibration: bool,
    bootstrap_ci_low: float | None,
    provider_independence: str,
    sufficient_evidence: bool,
) -> ReplicationDecisionResult:
    """Pure decision function mirroring the frozen success/partial/failure/inconclusive
    criteria in ReplicationProtocolDefinition. Kept separate from persistence so it can
    be unit tested without a database."""
    if not sufficient_evidence:
        return ReplicationDecisionResult(
            "REPLICATION_INCONCLUSIVE",
            "Insufficient independent episodes, instruments, or coverage to reach a conclusion.",
        )
    if brier_skill_vs_unconditional is None or brier_skill_vs_same_context_random is None:
        return ReplicationDecisionResult(
            "REPLICATION_INCONCLUSIVE", "Primary metrics could not be computed for the independent dataset."
        )
    if brier_skill_vs_unconditional <= 0.0 or not effect_direction_consistent:
        return ReplicationDecisionResult(
            "REPLICATION_NOT_SUPPORTED",
            "Brier skill vs unconditional is not positive, or the effect direction reversed relative to Yahoo.",
        )
    strong = (
        brier_skill_vs_unconditional > 0.0
        and brier_skill_vs_same_context_random > 0.0
        and effect_direction_consistent
        and adequate_episode_diversity
        and not single_instrument_dependent
        and acceptable_calibration
        and (bootstrap_ci_low is not None and bootstrap_ci_low > 0.0)
        and provider_independence == "CONFIRMED"
    )
    if strong:
        return ReplicationDecisionResult(
            "REPLICATION_SUPPORTED",
            "All frozen success criteria were met on independent, provider-confirmed data.",
        )
    return ReplicationDecisionResult(
        "REPLICATION_PARTIAL",
        "Some but not all frozen success criteria were met; see per-instrument and per-asset-class detail.",
    )
