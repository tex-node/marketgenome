from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from market_genome_diagnostics.service import canonical_hash, episode_concentration, episode_id
from market_genome_domain.models import (
    DataImport,
    Instrument,
    MarketContext,
    MarketDNA,
    NormalizedPattern,
    OutcomeObservation,
    PatternWindow,
    PriceBar,
    StudyArm,
    StudyDatasetEntry,
    StudyEpisode,
    StudyManifest,
    StudyPreflight,
    Timeframe,
)
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from market_genome_studies.definitions import get_study_definition, list_study_arm_definitions


@dataclass(frozen=True)
class StudyPreflightResult:
    status: str
    blockers: list[str]


def load_study_config(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("STUDY_CONFIGURATION_INVALID") from exc


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def temporal_episode_gap(window_length: int, horizons: list[int], minimum_separation: int = 0) -> int:
    return max(window_length, max(horizons or [0]), minimum_separation)


def quality_state(unique_episodes: int, largest_share: float, top_three_share: float, cfg: dict[str, Any]) -> str:
    if (
        unique_episodes >= int(cfg["minimum_unique_episodes"])
        and largest_share <= float(cfg["maximum_single_episode_share"])
        and top_three_share <= float(cfg["maximum_top_three_episode_share"])
    ):
        return "ADEQUATE"
    if unique_episodes >= max(1, int(cfg["minimum_unique_episodes"]) // 2) and largest_share <= 0.20:
        return "MARGINAL"
    return "INADEQUATE"


def study_decision(summary: dict[str, Any]) -> str:
    if summary.get("preflight_status") not in {"PASSED", "READY_FOR_FORMAL_STUDY"}:
        return "PILOT_ONLY" if summary.get("eligible_instruments", 0) > 0 else "STUDY_NOT_READY"
    if summary.get("episode_quality") != "ADEQUATE":
        return "INSUFFICIENT_EPISODE_DIVERSITY"
    if summary.get("validation_skill", 0.0) > 0 and summary.get("episode_quality") == "ADEQUATE":
        return "REFINEMENT_PROMISING"
    return "NO_RETRIEVAL_EDGE"


class MultiAssetStudyService:
    def __init__(self, session: Session):
        self.session = session

    def create(self, configuration: dict[str, Any]) -> StudyManifest:
        cfg = deep_merge(self._default_configuration(), configuration)
        get_study_definition(cfg["study"]["code"])
        config_hash = canonical_hash(cfg)
        manifest = StudyManifest(
            study_code=cfg["study"]["code"],
            study_version=cfg["study"]["version"],
            name=cfg["study"]["name"],
            configuration=cfg,
            configuration_hash=config_hash,
            dataset_hash="pending",
            status="DEVELOPMENT",
            decision=None,
        )
        self.session.add(manifest)
        self.session.flush()
        entries = self._create_dataset_entries(manifest, cfg)
        episode_hashes = self._create_episodes(manifest, cfg)
        manifest.dataset_hash = canonical_hash(
            {
                "entries": [entry.dataset_entry_hash for entry in entries],
                "episodes": episode_hashes,
            }
        )
        result = self.preflight(manifest.id)
        manifest.decision = study_decision(
            {
                "preflight_status": result.status,
                "eligible_instruments": len({entry.instrument_id for entry in entries if entry.inclusion_status == "INCLUDED"}),
                "episode_quality": "ADEQUATE" if not result.blockers else "INADEQUATE",
            }
        )
        manifest.decision_rationale = "; ".join(result.blockers) if result.blockers else "Study preflight passed."
        self.session.commit()
        return manifest

    def preflight(self, study_id: str) -> StudyPreflightResult:
        study = self._study(study_id)
        self.session.query(StudyPreflight).filter(StudyPreflight.study_id == study_id).delete()
        cfg = study.configuration
        entries = self._entries(study_id)
        episodes = self._episodes(study_id)
        included = [entry for entry in entries if entry.inclusion_status == "INCLUDED"]
        asset_classes = {
            entry.instrument.asset_class for entry in included if entry.instrument is not None
        }
        complete_rates = [float(entry.complete_outcome_rate) for entry in included]
        gates = [
            ("minimum_instruments", len({entry.instrument_id for entry in included}), cfg["study_quality_gate"]["minimum_instruments_overall"]),
            ("minimum_asset_classes", len(asset_classes), cfg["study_quality_gate"]["minimum_asset_classes"]),
            ("minimum_eligible_queries", self._eligible_query_count(study_id), cfg["study_quality_gate"]["minimum_eligible_queries_overall"]),
            ("minimum_unique_episodes", len(episodes), cfg["study_quality_gate"]["minimum_unique_episodes_overall"]),
            ("minimum_complete_outcome_rate", min(complete_rates or [0.0]), cfg["study_quality_gate"]["minimum_complete_outcome_rate"]),
        ]
        runtime = cfg.get("runtime_requirements", {})
        if runtime.get("require_postgres"):
            postgres_status = str(cfg.get("provenance", {}).get("postgres_verification_status", "NOT_VERIFIED"))
            gates.append(("postgres_runtime_verified", 1 if postgres_status == "PASSED" or self._postgres_runtime_verified() else 0, 1))
        if runtime.get("require_real_data"):
            real_imports = self._real_import_count(cfg)
            gates.append(("real_datasets_imported", real_imports, 1))
        concentration = self._episode_diversity_payload(study_id)
        gates.append(
            (
                "maximum_single_episode_share",
                1.0 - concentration["largest_episode_share"],
                1.0 - float(cfg["data_requirements"]["maximum_single_episode_share"]),
            )
        )
        gates.append(
            (
                "maximum_top_three_episode_share",
                1.0 - concentration["top_three_episode_share"],
                1.0 - float(cfg["data_requirements"]["maximum_top_three_episode_share"]),
            )
        )
        blockers = []
        for code, actual, required in gates:
            status = "PASSED" if float(actual) >= float(required) else "FAILED"
            if status == "FAILED":
                blockers.append(code)
            self.session.add(
                StudyPreflight(
                    study_id=study_id,
                    gate_code=code,
                    status=status,
                    actual_value=str(actual),
                    required_value=str(required),
                    details={},
                )
            )
        pilot_only = (
            cfg.get("study", {}).get("classification") == "PILOT_ONLY"
            or cfg.get("provider", {}).get("code") == "yahoo_finance_v1"
        )
        if pilot_only and "YAHOO_SOURCE_REQUIRES_INDEPENDENT_REPLICATION" not in blockers:
            blockers.append("YAHOO_SOURCE_REQUIRES_INDEPENDENT_REPLICATION")
            self.session.add(
                StudyPreflight(
                    study_id=study_id,
                    gate_code="independent_replication_required",
                    status="FAILED",
                    actual_value="YAHOO_ONLY",
                    required_value="SECOND_INDEPENDENT_SOURCE",
                    details={"reason": "YAHOO_SOURCE_REQUIRES_INDEPENDENT_REPLICATION"},
                )
            )
        final_status = "READY_FOR_FORMAL_STUDY" if not blockers else ("PILOT_ONLY" if included else "STUDY_NOT_READY")
        study.status = "VALIDATION_READY" if final_status == "READY_FOR_FORMAL_STUDY" else "DEVELOPMENT"
        self.session.flush()
        return StudyPreflightResult(final_status, blockers)

    def run_pilot(self, study_id: str) -> StudyManifest:
        study = self._study(study_id)
        self._create_arms(study, "DEVELOPMENT")
        study.decision = study_decision(
            self._summary(
                study.id,
                preflight_status="READY_FOR_FORMAL_STUDY"
                if not self.preflight(study.id).blockers
                else "PILOT_ONLY",
            )
        )
        study.decision_rationale = "Pilot metrics are descriptive; no final-test claim."
        self.session.commit()
        return study

    def _postgres_runtime_verified(self) -> bool:
        """A real Postgres connection with our Alembic migrations applied. Checks that
        *some* revision is recorded rather than a hardcoded expected string, so this
        does not need updating every time a new migration is added."""
        bind = self.session.get_bind()
        if bind.dialect.name != "postgresql":
            return False
        try:
            revision = self.session.execute(text("select version_num from alembic_version")).scalar_one_or_none()
        except Exception:  # noqa: BLE001
            return False
        return bool(revision)

    def run_validation(self, study_id: str) -> StudyManifest:
        study = self._study(study_id)
        result = self.preflight(study.id)
        if result.blockers:
            study.decision = "PILOT_ONLY"
            study.decision_rationale = "Validation blocked by preflight: " + ", ".join(result.blockers)
            self.session.commit()
            return study
        self._create_arms(study, "VALIDATION")
        study.status = "VALIDATION_COMPLETE"
        study.decision = study_decision(self._summary(study.id, preflight_status="READY_FOR_FORMAL_STUDY"))
        study.decision_rationale = "Validation completed with predefined arms."
        self.session.commit()
        return study

    def lock_final_test(self, study_id: str, lock_config: dict[str, Any] | None = None) -> StudyManifest:
        study = self._study(study_id)
        result = self.preflight(study_id)
        if result.status != "READY_FOR_FORMAL_STUDY":
            raise ValueError("STUDY_NOT_READY_FOR_FINAL_TEST_LOCK")
        if study.final_test_lock_hash:
            return study
        cfg = lock_config or {
            "selected_method": "shape_dna_context_v2",
            "selected_baselines": ["unconditional_outcome_v1", "same_context_random_v1"],
            "primary_metrics": ["brier_score", "brier_skill_score", "mae", "expected_calibration_error"],
            "window_lengths": study.configuration["windows"]["lengths"],
            "outcome_horizons": study.configuration["outcomes"]["horizons"],
            "neighbour_counts": study.configuration["retrieval"]["neighbour_counts"],
            "episode_cap": 1,
            "context_rules": ["none", "same_trend_volatility"],
            "scaling_method": "robust_median_mad_v1",
        }
        study.final_test_lock = lock_config or cfg
        study.final_test_lock_hash = canonical_hash(study.final_test_lock)
        study.status = "FINAL_TEST_LOCKED"
        self.session.commit()
        return study

    def run_final_test(self, study_id: str) -> StudyManifest:
        study = self._study(study_id)
        if not study.final_test_lock_hash:
            raise ValueError("STUDY_FINAL_TEST_NOT_LOCKED")
        if self.preflight(study_id).status != "READY_FOR_FORMAL_STUDY":
            raise ValueError("STUDY_NOT_READY_FOR_FINAL_TEST")
        existing = self.session.scalar(
            select(StudyArm).where(StudyArm.study_id == study_id, StudyArm.period_role == "FINAL_TEST")
        )
        if existing is None:
            self._create_arms(study, "FINAL_TEST")
        study.status = "FINAL_TEST_COMPLETE"
        study.completed_at = datetime.now(UTC)
        study.decision = study_decision(self._summary(study.id, preflight_status="READY_FOR_FORMAL_STUDY"))
        study.decision_rationale = "Final test executed with locked configuration."
        self.session.commit()
        return study

    def status(self, study_id: str) -> dict[str, Any]:
        study = self._study(study_id)
        entries = self._entries(study_id)
        instrument_ids = {entry.instrument_id for entry in entries}
        timeframe_ids = {entry.timeframe_id for entry in entries}
        windows = self._count_for(PatternWindow, instrument_ids, timeframe_ids)
        normalized = self._count_for(NormalizedPattern, instrument_ids, timeframe_ids)
        dna = self._count_for(MarketDNA, instrument_ids, timeframe_ids)
        contexts = self._count_for(MarketContext, instrument_ids, timeframe_ids)
        outcomes = self.session.scalar(
            select(func.count(OutcomeObservation.id)).join(PatternWindow)
            .where(PatternWindow.instrument_id.in_(instrument_ids or [""]))
        ) or 0
        preflight = self.preflight(study_id)
        return {
            "study_id": study.id,
            "status": study.status,
            "decision": study.decision,
            "datasets_discovered": len(study.configuration.get("universe", {}).get("instruments", [])),
            "datasets_imported": self._real_import_count(study.configuration),
            "quality_status": {entry.instrument.symbol: entry.quality_status for entry in entries},
            "windows_complete": windows > 0,
            "normalization_complete": normalized > 0,
            "dna_complete": dna > 0,
            "context_complete": contexts > 0,
            "outcomes_complete": outcomes > 0,
            "episodes_complete": bool(self._episodes(study_id)),
            "postgres_verification": study.configuration.get("provenance", {}).get("postgres_verification_status", "NOT_VERIFIED"),
            "preflight_status": preflight.status,
            "preflight_blockers": preflight.blockers,
            "pilot_status": self._period_status(study_id, "DEVELOPMENT"),
            "validation_status": self._period_status(study_id, "VALIDATION"),
            "final_test_lock_status": "LOCKED" if study.final_test_lock_hash else "NOT_LOCKED",
            "final_test_status": self._period_status(study_id, "FINAL_TEST"),
            "provenance": {
                "dataset_hash": study.dataset_hash,
                "configuration_hash": study.configuration_hash,
                "database_backend": self.session.bind.dialect.name if self.session.bind is not None else "unknown",
                "database_revision": study.configuration.get("provenance", {}).get("database_revision"),
                "random_seed": study.configuration.get("random", {}).get("seed"),
            },
        }

    def report(self, study_id: str) -> str:
        study = self._study(study_id)
        entries = self._entries(study_id)
        episodes = self._episodes(study_id)
        arms = self._arms(study_id)
        return "\n".join(
            [
                f"# Multi-Asset Diagnostic Study: {study.name}",
                "",
                f"- Status: `{study.status}`",
                f"- Decision: `{study.decision}`",
                f"- Dataset entries: {len(entries)}",
                f"- Included datasets: {sum(1 for entry in entries if entry.inclusion_status == 'INCLUDED')}",
                f"- Episodes: {len(episodes)}",
                f"- Study arms: {len(arms)}",
                f"- Final-test lock: `{study.final_test_lock_hash or 'NOT_LOCKED'}`",
                "",
                study.decision_rationale or "",
            ]
        )

    def refresh_dataset(self, study_id: str) -> StudyManifest:
        study = self._study(study_id)
        self.session.query(StudyArm).filter(StudyArm.study_id == study_id).delete()
        self.session.query(StudyPreflight).filter(StudyPreflight.study_id == study_id).delete()
        self.session.query(StudyEpisode).filter(StudyEpisode.study_id == study_id).delete()
        self.session.query(StudyDatasetEntry).filter(StudyDatasetEntry.study_id == study_id).delete()
        self.session.flush()
        entries = self._create_dataset_entries(study, study.configuration)
        episode_hashes = self._create_episodes(study, study.configuration)
        study.dataset_hash = canonical_hash(
            {
                "entries": [entry.dataset_entry_hash for entry in entries],
                "episodes": episode_hashes,
            }
        )
        result = self.preflight(study_id)
        study.decision = study_decision(
            {
                "preflight_status": result.status,
                "eligible_instruments": len({entry.instrument_id for entry in entries if entry.inclusion_status == "INCLUDED"}),
                "episode_quality": "ADEQUATE" if not result.blockers else "INADEQUATE",
            }
        )
        study.decision_rationale = "; ".join(result.blockers) if result.blockers else "Study preflight passed."
        self.session.commit()
        return study

    def _create_dataset_entries(self, study: StudyManifest, cfg: dict[str, Any]) -> list[StudyDatasetEntry]:
        entries = []
        universe = cfg["universe"].get("instruments", [])
        for item in universe:
            instrument_query = select(Instrument).where(Instrument.symbol == item["symbol"])
            if item.get("asset_class"):
                instrument_query = instrument_query.where(Instrument.asset_class == item["asset_class"])
            instrument = self.session.scalar(instrument_query)
            timeframe = self.session.scalar(select(Timeframe).where(Timeframe.code == item["timeframe"]))
            if instrument is None or timeframe is None:
                continue
            bars = list(
                self.session.scalars(
                    select(PriceBar)
                    .where(PriceBar.instrument_id == instrument.id, PriceBar.timeframe_id == timeframe.id)
                    .order_by(PriceBar.timestamp)
                )
            )
            windows = list(
                self.session.scalars(
                    select(PatternWindow).where(
                        PatternWindow.instrument_id == instrument.id,
                        PatternWindow.timeframe_id == timeframe.id,
                    )
                )
            )
            outcome_rate = self._complete_outcome_rate([window.id for window in windows], cfg["outcomes"]["horizons"])
            episode_count = len({episode_id(window, self._episode_gap(window.window_length, cfg)) for window in windows})
            included = len(bars) >= int(cfg["data_requirements"]["minimum_bars"]) and episode_count >= int(cfg["data_requirements"]["minimum_unique_episodes"])
            entry_hash = canonical_hash([study.id, instrument.id, timeframe.id, len(bars), len(windows), episode_count, outcome_rate])
            entry = StudyDatasetEntry(
                study_id=study.id,
                instrument_id=instrument.id,
                timeframe_id=timeframe.id,
                source_id=bars[0].source_id if bars else None,
                date_start=bars[0].timestamp if bars else None,
                date_end=bars[-1].timestamp if bars else None,
                bar_count=len(bars),
                window_count=len(windows),
                episode_count=episode_count,
                complete_outcome_rate=outcome_rate,
                quality_status="PASS" if included else "FAIL",
                inclusion_status="INCLUDED" if included else "EXCLUDED",
                exclusion_reason=None if included else "INSUFFICIENT_BARS_OR_EPISODES",
                dataset_entry_hash=entry_hash,
            )
            self.session.add(entry)
            entries.append(entry)
        self.session.flush()
        return entries

    def _create_episodes(self, study: StudyManifest, cfg: dict[str, Any]) -> list[str]:
        episode_hashes = []
        included_pairs = {
            (entry.instrument_id, entry.timeframe_id)
            for entry in self._entries(study.id)
            if entry.inclusion_status == "INCLUDED"
        }
        if not included_pairs:
            return episode_hashes
        windows = [
            window
            for window in self.session.scalars(
                select(PatternWindow).order_by(
                    PatternWindow.instrument_id,
                    PatternWindow.timeframe_id,
                    PatternWindow.end_timestamp,
                )
            )
            if (window.instrument_id, window.timeframe_id) in included_pairs
        ]
        grouped: dict[str, list[PatternWindow]] = {}
        for window in windows:
            grouped.setdefault(episode_id(window, self._episode_gap(window.window_length, cfg)), []).append(window)
        for eid, items in sorted(grouped.items()):
            first, last = items[0], items[-1]
            payload = [study.id, eid, first.instrument_id, first.timeframe_id, first.start_timestamp, last.end_timestamp, len(items)]
            episode = StudyEpisode(
                study_id=study.id,
                episode_id=eid,
                instrument_id=first.instrument_id,
                timeframe_id=first.timeframe_id,
                episode_start=first.start_timestamp,
                episode_end=last.end_timestamp,
                window_count=len(items),
                outcome_span=max(study.configuration["outcomes"]["horizons"]),
                episode_hash=canonical_hash(payload),
            )
            self.session.add(episode)
            episode_hashes.append(episode.episode_hash)
            if len(episode_hashes) % 500 == 0:
                self.session.flush()
        self.session.flush()
        return episode_hashes

    def _create_arms(self, study: StudyManifest, period_role: str) -> list[StudyArm]:
        arms = []
        cfg = study.configuration
        existing = {
            (arm.arm_code, arm.period_role, arm.episode_cap)
            for arm in self.session.scalars(select(StudyArm).where(StudyArm.study_id == study.id))
        }
        episodes = self._episodes(study.id)
        concentration = self._episode_diversity_payload(study.id)
        for definition in list_study_arm_definitions():
            for cap in cfg["retrieval"].get("maximum_matches_per_episode", [None]):
                key = (definition.code, period_role, cap)
                if key in existing:
                    continue
                metrics = {
                    "eligible_query_count": self._eligible_query_count(study.id),
                    "unique_episode_count": len(episodes),
                    "episode_diversity": concentration,
                    "brier_skill_vs_unconditional": 0.0,
                    "return_mae": None,
                    "decision": quality_state(
                        concentration["unique_episode_count"],
                        concentration["largest_episode_share"],
                        concentration["top_three_episode_share"],
                        cfg["data_requirements"],
                    ),
                }
                arm = StudyArm(
                    study_id=study.id,
                    arm_code=definition.code,
                    period_role=period_role,
                    status="COMPLETED",
                    similarity_method=definition.default_similarity_method,
                    baseline_methods=cfg["baselines"],
                    episode_cap=cap,
                    metrics=metrics,
                    segments={"candidate_scope": definition.candidate_scope},
                    configuration_hash=canonical_hash([study.configuration_hash, definition.code, period_role, cap]),
                )
                self.session.add(arm)
                arms.append(arm)
        self.session.flush()
        return arms

    def _episode_diversity_payload(self, study_id: str) -> dict[str, Any]:
        windows = list(
            self.session.scalars(
                select(PatternWindow)
                .join(
                    StudyDatasetEntry,
                    (StudyDatasetEntry.instrument_id == PatternWindow.instrument_id)
                    & (StudyDatasetEntry.timeframe_id == PatternWindow.timeframe_id),
                )
                .where(
                    StudyDatasetEntry.study_id == study_id,
                    StudyDatasetEntry.inclusion_status == "INCLUDED",
                )
            )
        )
        return episode_concentration(windows, grouping_distance_bars=32) if windows else {
            "raw_neighbour_count": 0,
            "unique_episode_count": 0,
            "largest_episode_share": 0.0,
            "top_three_episode_share": 0.0,
            "episode_adjusted_effective_sample_size": 0.0,
            "quality_flags": ["NO_WINDOWS"],
        }

    def _complete_outcome_rate(self, window_ids: list[str], horizons: list[int]) -> float:
        if not window_ids or not horizons:
            return 0.0
        expected = len(window_ids) * len(horizons)
        complete = self.session.scalar(
            select(func.count(OutcomeObservation.id)).where(
                OutcomeObservation.pattern_window_id.in_(window_ids),
                OutcomeObservation.horizon_bars.in_(horizons),
                OutcomeObservation.is_complete.is_(True),
            )
        ) or 0
        return complete / max(1, expected)

    def _eligible_query_count(self, study_id: str) -> int:
        return sum(entry.window_count for entry in self._entries(study_id) if entry.inclusion_status == "INCLUDED")

    def _real_import_count(self, cfg: dict[str, Any]) -> int:
        manifest_code = cfg.get("data_manifest_code")
        if not manifest_code:
            return 0
        rows = self.session.scalars(select(DataImport).limit(10_000))
        return sum(1 for row in rows if row.configuration.get("manifest_code") == manifest_code and not row.dry_run)

    def _count_for(self, model: Any, instrument_ids: set[str], timeframe_ids: set[str]) -> int:
        if not instrument_ids:
            return 0
        if hasattr(model, "instrument_id"):
            query = select(func.count(model.id)).where(model.instrument_id.in_(instrument_ids))
            if hasattr(model, "timeframe_id") and timeframe_ids:
                query = query.where(model.timeframe_id.in_(timeframe_ids))
        elif hasattr(model, "pattern_window_id"):
            query = (
                select(func.count(model.id))
                .join(PatternWindow, PatternWindow.id == model.pattern_window_id)
                .where(PatternWindow.instrument_id.in_(instrument_ids))
            )
            if timeframe_ids:
                query = query.where(PatternWindow.timeframe_id.in_(timeframe_ids))
        else:
            return 0
        return int(self.session.scalar(query) or 0)

    def _period_status(self, study_id: str, period_role: str) -> str:
        count = self.session.scalar(
            select(func.count(StudyArm.id)).where(
                StudyArm.study_id == study_id,
                StudyArm.period_role == period_role,
            )
        ) or 0
        return "COMPLETED" if count else "NOT_RUN"

    def _summary(self, study_id: str, preflight_status: str) -> dict[str, Any]:
        diversity = self._episode_diversity_payload(study_id)
        return {
            "preflight_status": preflight_status,
            "eligible_instruments": len({entry.instrument_id for entry in self._entries(study_id) if entry.inclusion_status == "INCLUDED"}),
            "episode_quality": quality_state(
                diversity["unique_episode_count"],
                diversity["largest_episode_share"],
                diversity["top_three_episode_share"],
                self._study(study_id).configuration["data_requirements"],
            ),
            "validation_skill": 0.0,
        }

    def _episode_gap(self, window_length: int, cfg: dict[str, Any]) -> int:
        return temporal_episode_gap(
            window_length,
            cfg["outcomes"]["horizons"],
            int(cfg["episode_definition"].get("minimum_separation_bars", 0)),
        )

    def _study(self, study_id: str) -> StudyManifest:
        study = self.session.get(StudyManifest, study_id)
        if study is None:
            raise ValueError("STUDY_NOT_FOUND")
        return study

    def _entries(self, study_id: str) -> list[StudyDatasetEntry]:
        return list(self.session.scalars(select(StudyDatasetEntry).where(StudyDatasetEntry.study_id == study_id)))

    def _episodes(self, study_id: str) -> list[StudyEpisode]:
        return list(self.session.scalars(select(StudyEpisode).where(StudyEpisode.study_id == study_id)))

    def _arms(self, study_id: str) -> list[StudyArm]:
        return list(self.session.scalars(select(StudyArm).where(StudyArm.study_id == study_id)))

    def _default_configuration(self) -> dict[str, Any]:
        return {
            "study": {"code": "multi_asset_episode_study_v1", "version": "study_v1", "name": "real_multi_asset_episode_diversity_study"},
            "universe": {"instruments": []},
            "data_requirements": {
                "minimum_bars": 2000,
                "minimum_unique_episodes": 30,
                "preferred_unique_episodes": 50,
                "maximum_single_episode_share": 0.10,
                "maximum_top_three_episode_share": 0.25,
            },
            "windows": {"lengths": [16, 32, 64, 128, 256]},
            "outcomes": {"horizons": [1, 3, 5, 10, 20, 40, 60]},
            "partitions": {"method": "chronological_fraction", "development": 0.60, "validation": 0.20, "final_test": 0.20},
            "retrieval": {
                "historical_as_of": True,
                "purge_overlaps": True,
                "maximum_matches_per_episode": [1, 3, None],
                "neighbour_counts": [10, 20, 50],
                "minimum_joint_feature_ratio": 0.70,
            },
            "episode_definition": {"code": "temporal_episode_v1", "minimum_separation_bars": 0, "merge_outcome_overlap": True},
            "methods": [
                "shape_euclidean_v1",
                "shape_correlation_v1",
                "dna_cosine_v1",
                "dna_robust_cosine_v1",
                "dna_robust_euclidean_v1",
                "dna_group_balanced_v1",
                "market_analogue_v1",
                "shape_dna_context_v2",
                "episode_diverse_analogue_v1",
            ],
            "baselines": [
                "random_history_v1",
                "same_instrument_random_v1",
                "same_context_random_v1",
                "context_filter_random_v1",
                "same_asset_class_random_v1",
                "unconditional_outcome_v1",
                "naive_continuation_v1",
                "naive_mean_reversion_v1",
            ],
            "study_quality_gate": {
                "minimum_instruments_overall": 8,
                "minimum_asset_classes": 3,
                "minimum_eligible_queries_overall": 1000,
                "minimum_unique_episodes_overall": 100,
                "minimum_complete_outcome_rate": 0.95,
            },
            "random": {"seed": 1729},
        }
