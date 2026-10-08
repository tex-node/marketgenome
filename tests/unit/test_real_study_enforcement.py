from __future__ import annotations

from market_genome_studies.service import MultiAssetStudyService
from sqlalchemy.orm import Session


def _real_required_config() -> dict:
    return {
        "study": {"code": "multi_asset_episode_study_v1", "version": "study_v1", "name": "real_required"},
        "data_manifest_code": "unit_real_data",
        "runtime_requirements": {"require_postgres": True, "require_real_data": True},
        "provenance": {"postgres_verification_status": "NOT_VERIFIED", "database_revision": None},
        "universe": {"instruments": [{"symbol": "AAA", "asset_class": "equity", "timeframe": "D1", "source": "USER_CSV"}]},
        "data_requirements": {
            "minimum_bars": 3,
            "minimum_unique_episodes": 1,
            "preferred_unique_episodes": 1,
            "maximum_single_episode_share": 1.0,
            "maximum_top_three_episode_share": 1.0,
        },
        "windows": {"lengths": [2]},
        "outcomes": {"horizons": [1]},
        "retrieval": {"maximum_matches_per_episode": [1], "neighbour_counts": [1]},
        "study_quality_gate": {
            "minimum_instruments_overall": 1,
            "minimum_asset_classes": 1,
            "minimum_eligible_queries_overall": 1,
            "minimum_unique_episodes_overall": 1,
            "minimum_complete_outcome_rate": 0.1,
        },
    }


def test_real_data_requirement_blocks_formal_preflight(db_session: Session) -> None:
    service = MultiAssetStudyService(db_session)
    study = service.create(_real_required_config())

    result = service.preflight(study.id)
    status = service.status(study.id)

    assert result.status == "STUDY_NOT_READY"
    assert "postgres_runtime_verified" in result.blockers
    assert "real_datasets_imported" in result.blockers
    assert status["postgres_verification"] == "NOT_VERIFIED"


def test_final_test_lock_enforced_for_not_ready_study(db_session: Session) -> None:
    service = MultiAssetStudyService(db_session)
    study = service.create(_real_required_config())

    try:
        service.lock_final_test(study.id)
    except ValueError as exc:
        assert str(exc) == "STUDY_NOT_READY_FOR_FINAL_TEST_LOCK"
    else:
        raise AssertionError("final-test lock should be blocked")
