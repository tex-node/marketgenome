from __future__ import annotations

import pytest
from market_genome_domain.models import ExperimentRun, StudyManifest
from market_genome_replication.context_dna_analysis import CONTEXT_DNA_DECISIONS
from market_genome_replication.definitions import (
    CONTEXT_DNA_INCREMENTAL_VALUE_V1,
    INDEPENDENT_ROBUST_DNA_REPLICATION_V1,
    get_replication_protocol_definition,
    list_replication_protocol_definitions,
)
from market_genome_replication.service import (
    ReplicationProtocolImmutableError,
    ReplicationService,
    classify_replication_decision,
)
from sqlalchemy.orm import Session


def _experiment_run(**overrides) -> ExperimentRun:
    values = {
        "experiment_code": "yahoo_pilot_validation_v1",
        "experiment_version": "pilot_validation_v1",
        "name": "Yahoo pilot validation",
        "dataset_hash": "d" * 64,
        "configuration_hash": "c" * 64,
        "similarity_method": "dna_robust_cosine_v1",
        "outcome_set_code": "forward_outcomes_v1",
        "outcome_set_version": "forward_outcomes_v1",
        "validation_method": "anchored_holdout_bounded_historical_as_of_v1",
    }
    values.update(overrides)
    return ExperimentRun(**values)


def _study_manifest(**overrides) -> StudyManifest:
    values = {
        "study_code": "multi_asset_episode_study_v1",
        "study_version": "study_v1",
        "name": "study",
        "configuration_hash": "s" * 64,
        "dataset_hash": "d" * 64,
    }
    values.update(overrides)
    return StudyManifest(**values)


def test_protocol_definition_registry() -> None:
    definitions = list_replication_protocol_definitions()
    assert any(item.protocol_code == "independent_robust_dna_replication_v1" for item in definitions)
    fetched = get_replication_protocol_definition("independent_robust_dna_replication_v1")
    assert fetched.primary_method == "dna_robust_cosine_v1"
    assert fetched.study_arm == "same_instrument"
    assert fetched.episode_cap == 1
    assert fetched.primary_horizon == 20
    with pytest.raises(ValueError, match="REPLICATION_PROTOCOL_DEFINITION_NOT_FOUND"):
        get_replication_protocol_definition("missing")


def test_freeze_protocol_requires_source_experiment(db_session: Session) -> None:
    service = ReplicationService(db_session)
    with pytest.raises(ValueError, match="SOURCE_EXPERIMENT_NOT_FOUND"):
        service.freeze_protocol("independent_robust_dna_replication_v1", "missing-id")


def test_freeze_protocol_is_idempotent(db_session: Session) -> None:
    source = _experiment_run()
    db_session.add(source)
    db_session.commit()
    service = ReplicationService(db_session)

    first = service.freeze_protocol("independent_robust_dna_replication_v1", source.id, frozen_by="tester")
    second = service.freeze_protocol("independent_robust_dna_replication_v1", source.id)

    assert first.id == second.id
    assert first.status == "FROZEN"
    assert first.frozen_at is not None
    assert first.configuration_hash == second.configuration_hash
    assert first.hypothesis_text == INDEPENDENT_ROBUST_DNA_REPLICATION_V1.hypothesis_text


def test_lock_requires_frozen_protocol_and_existing_studies(db_session: Session) -> None:
    source = _experiment_run()
    db_session.add(source)
    db_session.commit()
    service = ReplicationService(db_session)
    protocol = service.freeze_protocol("independent_robust_dna_replication_v1", source.id)

    with pytest.raises(ValueError, match="STUDY_NOT_FOUND"):
        service.create_lock(
            protocol.id,
            study_id="missing",
            source_study_id="missing",
            dataset_hash="x" * 64,
            provider_code="alpha_vantage_v1",
            provider_provenance_hash="p" * 64,
            instrument_universe=["SPY_AV"],
            date_range={"start": "2020-01-01", "end": "2026-01-01"},
        )


def test_lock_is_idempotent_per_protocol_and_study(db_session: Session) -> None:
    source = _experiment_run()
    yahoo_study = _study_manifest(name="yahoo")
    independent_study = _study_manifest(name="independent")
    db_session.add_all([source, yahoo_study, independent_study])
    db_session.commit()
    service = ReplicationService(db_session)
    protocol = service.freeze_protocol("independent_robust_dna_replication_v1", source.id)

    kwargs = {
        "study_id": independent_study.id,
        "source_study_id": yahoo_study.id,
        "dataset_hash": "x" * 64,
        "provider_code": "alpha_vantage_v1",
        "provider_provenance_hash": "p" * 64,
        "instrument_universe": ["SPY_AV", "QQQ_AV"],
        "date_range": {"start": "2020-01-01", "end": "2026-01-01"},
    }
    first = service.create_lock(protocol.id, **kwargs)
    second = service.create_lock(protocol.id, **kwargs)

    assert first.id == second.id
    assert first.status == "LOCKED"
    assert first.lock_hash == second.lock_hash


def test_record_and_decide_are_idempotent_once_decided(db_session: Session) -> None:
    source = _experiment_run()
    replication_experiment = _experiment_run(experiment_code="independent_robust_dna_replication_v1")
    yahoo_study = _study_manifest(name="yahoo")
    independent_study = _study_manifest(name="independent")
    db_session.add_all([source, replication_experiment, yahoo_study, independent_study])
    db_session.commit()
    service = ReplicationService(db_session)
    protocol = service.freeze_protocol("independent_robust_dna_replication_v1", source.id)
    lock = service.create_lock(
        protocol.id,
        study_id=independent_study.id,
        source_study_id=yahoo_study.id,
        dataset_hash="x" * 64,
        provider_code="alpha_vantage_v1",
        provider_provenance_hash="p" * 64,
        instrument_universe=["SPY_AV"],
        date_range={"start": "2020-01-01", "end": "2026-01-01"},
    )

    record = service.create_record(lock.id, provider_independence="CONFIRMED")
    assert record.decision == "PENDING"

    decided = service.decide(
        record.id,
        replication_experiment_id=replication_experiment.id,
        decision="REPLICATION_SUPPORTED",
        decision_rationale="All frozen criteria met.",
        comparison={"brier_skill_vs_unconditional": 0.1},
    )
    assert decided.decision == "REPLICATION_SUPPORTED"

    # A second decide() call must not overwrite an already-decided record, even with
    # different arguments -- this prevents retuning against the same independent dataset.
    retuned = service.decide(
        record.id,
        replication_experiment_id="different-experiment",
        decision="REPLICATION_NOT_SUPPORTED",
        decision_rationale="attempted retune",
        comparison={},
    )
    assert retuned.decision == "REPLICATION_SUPPORTED"
    assert retuned.replication_experiment_id == replication_experiment.id


def test_decide_rejects_unsupported_decision_vocabulary(db_session: Session) -> None:
    source = _experiment_run()
    yahoo_study = _study_manifest(name="yahoo")
    independent_study = _study_manifest(name="independent")
    db_session.add_all([source, yahoo_study, independent_study])
    db_session.commit()
    service = ReplicationService(db_session)
    protocol = service.freeze_protocol("independent_robust_dna_replication_v1", source.id)
    lock = service.create_lock(
        protocol.id,
        study_id=independent_study.id,
        source_study_id=yahoo_study.id,
        dataset_hash="x" * 64,
        provider_code="alpha_vantage_v1",
        provider_provenance_hash="p" * 64,
        instrument_universe=["SPY_AV"],
        date_range={"start": "2020-01-01", "end": "2026-01-01"},
    )
    record = service.create_record(lock.id, provider_independence="CONFIRMED")

    with pytest.raises(ValueError, match="UNSUPPORTED_REPLICATION_DECISION"):
        service.decide(
            record.id,
            replication_experiment_id="x",
            decision="TRADING_EDGE_PROVEN",
            decision_rationale="",
            comparison={},
        )


def test_frozen_protocol_configuration_cannot_be_silently_changed(db_session: Session) -> None:
    source = _experiment_run()
    db_session.add(source)
    db_session.commit()
    service = ReplicationService(db_session)
    protocol = service.freeze_protocol("independent_robust_dna_replication_v1", source.id)

    # Simulate a would-be configuration change reaching the frozen row (e.g. a bug that
    # tried to alter the protocol definition after freezing) and confirm it is rejected.
    protocol.configuration_hash = "tampered" * 8
    db_session.commit()

    with pytest.raises(ReplicationProtocolImmutableError, match="REPLICATION_PROTOCOL_ALREADY_FROZEN_CONFIGURATION_IMMUTABLE"):
        service.freeze_protocol("independent_robust_dna_replication_v1", source.id)


@pytest.mark.parametrize(
    ("kwargs", "expected_decision"),
    [
        (
            {
                "brier_skill_vs_unconditional": 0.2,
                "brier_skill_vs_same_context_random": 0.05,
                "effect_direction_consistent": True,
                "adequate_episode_diversity": True,
                "single_instrument_dependent": False,
                "acceptable_calibration": True,
                "bootstrap_ci_low": 0.01,
                "provider_independence": "CONFIRMED",
                "sufficient_evidence": True,
            },
            "REPLICATION_SUPPORTED",
        ),
        (
            {
                "brier_skill_vs_unconditional": 0.2,
                "brier_skill_vs_same_context_random": -0.02,
                "effect_direction_consistent": True,
                "adequate_episode_diversity": True,
                "single_instrument_dependent": False,
                "acceptable_calibration": True,
                "bootstrap_ci_low": 0.01,
                "provider_independence": "CONFIRMED",
                "sufficient_evidence": True,
            },
            "REPLICATION_PARTIAL",
        ),
        (
            {
                "brier_skill_vs_unconditional": -0.1,
                "brier_skill_vs_same_context_random": -0.1,
                "effect_direction_consistent": False,
                "adequate_episode_diversity": True,
                "single_instrument_dependent": False,
                "acceptable_calibration": True,
                "bootstrap_ci_low": None,
                "provider_independence": "CONFIRMED",
                "sufficient_evidence": True,
            },
            "REPLICATION_NOT_SUPPORTED",
        ),
        (
            {
                "brier_skill_vs_unconditional": None,
                "brier_skill_vs_same_context_random": None,
                "effect_direction_consistent": True,
                "adequate_episode_diversity": False,
                "single_instrument_dependent": False,
                "acceptable_calibration": True,
                "bootstrap_ci_low": None,
                "provider_independence": "CONFIRMED",
                "sufficient_evidence": False,
            },
            "REPLICATION_INCONCLUSIVE",
        ),
    ],
)
def test_classify_replication_decision(kwargs: dict, expected_decision: str) -> None:
    result = classify_replication_decision(**kwargs)
    assert result.decision == expected_decision
    assert result.rationale


def test_context_dna_protocol_definition_reuses_independent_replication_configuration() -> None:
    definition = get_replication_protocol_definition("context_dna_incremental_value_v1")
    assert definition is CONTEXT_DNA_INCREMENTAL_VALUE_V1
    assert definition.primary_method == "dna_robust_cosine_v1"
    assert definition.study_arm == "same_instrument"
    assert definition.window_lengths == (16, 32, 64)
    assert definition.primary_horizon == 20
    assert definition.neighbour_count == 10
    assert definition.episode_cap == 1
    assert definition.independent_source_requirement == "FOLLOW_UP_CONFIRMATORY_DIAGNOSTIC"


def test_freeze_context_dna_protocol_can_source_from_independent_replication_experiment(db_session: Session) -> None:
    independent_replication_experiment = _experiment_run(
        experiment_code="independent_robust_dna_replication_v1", experiment_version="replication_v1"
    )
    db_session.add(independent_replication_experiment)
    db_session.commit()
    service = ReplicationService(db_session)

    protocol = service.freeze_protocol(
        "context_dna_incremental_value_v1", independent_replication_experiment.id, frozen_by="tester"
    )

    assert protocol.status == "FROZEN"
    assert protocol.source_experiment_id == independent_replication_experiment.id
    assert protocol.primary_method == "dna_robust_cosine_v1"


def test_decide_accepts_a_custom_decision_vocabulary(db_session: Session) -> None:
    source = _experiment_run(experiment_code="independent_robust_dna_replication_v1", experiment_version="replication_v1")
    study = _study_manifest(name="independent_study")
    db_session.add_all([source, study])
    db_session.commit()
    service = ReplicationService(db_session)
    protocol = service.freeze_protocol("context_dna_incremental_value_v1", source.id)
    lock = service.create_lock(
        protocol.id,
        study_id=study.id,
        source_study_id=study.id,
        dataset_hash="x" * 64,
        provider_code="alpha_vantage_v1",
        provider_provenance_hash="p" * 64,
        instrument_universe=["EURUSD_AV"],
        date_range={"start": "2020-01-01", "end": "2026-01-01"},
    )
    record = service.create_record(lock.id, provider_independence="CONFIRMED")

    with pytest.raises(ValueError, match="UNSUPPORTED_REPLICATION_DECISION"):
        service.decide(
            record.id,
            replication_experiment_id="x",
            decision="REPLICATION_SUPPORTED",
            decision_rationale="wrong vocabulary for this protocol family",
            comparison={},
            decision_vocabulary=CONTEXT_DNA_DECISIONS,
        )

    decided = service.decide(
        record.id,
        replication_experiment_id="x",
        decision="CONTEXT_SIGNAL_SUPPORTED_DNA_NO_INCREMENTAL_VALUE",
        decision_rationale="context beats unconditional; DNA does not beat context-random",
        comparison={},
        decision_vocabulary=CONTEXT_DNA_DECISIONS,
    )
    assert decided.decision == "CONTEXT_SIGNAL_SUPPORTED_DNA_NO_INCREMENTAL_VALUE"
