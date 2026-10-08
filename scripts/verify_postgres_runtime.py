from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text


def _head_revision_from_migration_scripts() -> str:
    """Read straight from the migration chain instead of a hardcoded literal, which
    has gone stale (and silently failed this check) every time a new migration was
    added -- see SESSION.md's Step 10A.3/10B-C incident notes."""
    repo_root = Path(__file__).resolve().parents[1]
    config = Config(str(repo_root / "infrastructure" / "alembic.ini"))
    config.set_main_option("script_location", str(repo_root / "infrastructure" / "migrations"))
    return ScriptDirectory.from_config(config).get_current_head()


EXPECTED_REVISION = os.environ.get(
    "MARKET_GENOME_EXPECTED_ALEMBIC_REVISION",
    _head_revision_from_migration_scripts(),
)
REQUIRED_TABLES = {
    "instruments",
    "timeframes",
    "data_sources",
    "price_bars",
    "data_imports",
    "pattern_windows",
    "normalized_patterns",
    "market_dna",
    "market_contexts",
    "outcome_observations",
    "similarity_queries",
    "experiment_runs",
    "diagnostic_artifacts",
    "study_manifests",
    "study_dataset_entries",
    "study_episodes",
    "study_preflights",
    "study_arms",
    "replication_protocols",
    "replication_locks",
    "replication_records",
    "prospective_protocols",
    "prospective_forecasts",
    "prospective_forecast_outcomes",
    "prospective_evaluation_snapshots",
}
REQUIRED_INDEXES = {
    "study_manifests": {"ix_study_manifests_status", "ix_study_manifests_configuration_hash"},
    "study_dataset_entries": {"ix_study_dataset_entries_study_id", "ix_study_dataset_entries_inclusion_status"},
    "study_episodes": {"ix_study_episodes_study_id", "ix_study_episodes_episode_id"},
    "study_preflights": {"ix_study_preflights_study_id", "ix_study_preflights_gate_code"},
    "study_arms": {"ix_study_arms_study_id", "ix_study_arms_period_role"},
    "replication_protocols": {"ix_replication_protocols_protocol_code", "ix_replication_protocols_status"},
    "replication_locks": {"ix_replication_locks_study_id", "ix_replication_locks_lock_hash"},
    "replication_records": {"ix_replication_records_lock_id", "ix_replication_records_decision"},
}


def redact_url(url: str) -> str:
    if "://" not in url or "@" not in url:
        return url
    scheme, rest = url.split("://", 1)
    auth, host = rest.split("@", 1)
    user = auth.split(":", 1)[0]
    return f"{scheme}://{user}:***@{host}"


def result(status: str, checks: dict[str, object], errors: list[str]) -> dict[str, object]:
    return {
        "status": status,
        "expected_revision": EXPECTED_REVISION,
        "checks": checks,
        "errors": errors,
    }


def main() -> int:
    url = os.environ.get("MARKET_GENOME_DATABASE_URL") or os.environ.get("DATABASE_URL")
    checks: dict[str, object] = {"configured": bool(url)}
    errors: list[str] = []
    if not url:
        errors.append("POSTGRES_DATABASE_URL_NOT_CONFIGURED")
        print(json.dumps(result("SKIPPED", checks, errors), indent=2, sort_keys=True))
        return 2
    checks["url"] = redact_url(url)
    engine = create_engine(url, pool_pre_ping=True)
    try:
        with engine.begin() as conn:
            checks["dialect"] = conn.dialect.name
            if conn.dialect.name != "postgresql":
                errors.append("DATABASE_DIALECT_NOT_POSTGRESQL")
            checks["connection"] = conn.execute(text("select 1")).scalar_one() == 1
            revision = conn.execute(text("select version_num from alembic_version")).scalar_one_or_none()
            checks["alembic_revision"] = revision
            if revision != EXPECTED_REVISION:
                errors.append("ALEMBIC_REVISION_MISMATCH")

            inspector = inspect(conn)
            tables = set(inspector.get_table_names())
            checks["required_tables"] = sorted(REQUIRED_TABLES.intersection(tables))
            missing_tables = sorted(REQUIRED_TABLES.difference(tables))
            if missing_tables:
                errors.append(f"MISSING_TABLES:{missing_tables}")
            index_checks = {}
            for table, required in REQUIRED_INDEXES.items():
                indexes = {item["name"] for item in inspector.get_indexes(table)} if table in tables else set()
                missing = sorted(required.difference(indexes))
                index_checks[table] = {"present": sorted(required.intersection(indexes)), "missing": missing}
                if missing:
                    errors.append(f"MISSING_INDEXES:{table}:{missing}")
            checks["indexes"] = index_checks
            constraint_checks = {}
            for table in ("price_bars", "data_imports"):
                uniques = {item["name"] for item in inspector.get_unique_constraints(table)}
                constraint_checks[table] = sorted(uniques)
            checks["key_constraints"] = constraint_checks

            probe_id = str(uuid4())
            now = datetime.now(UTC)
            payload = {"probe": probe_id, "nested": {"ok": True}}
            conn.execute(
                text("create temporary table mg_runtime_probe (id uuid primary key, ts timestamptz not null, payload jsonb not null)")
            )
            conn.execute(
                text("insert into mg_runtime_probe (id, ts, payload) values (:id, :ts, cast(:payload as jsonb))"),
                {"id": probe_id, "ts": now, "payload": json.dumps(payload)},
            )
            row = conn.execute(text("select id::text, ts, payload from mg_runtime_probe where id=:id"), {"id": probe_id}).one()
            checks["uuid_round_trip"] = row[0] == probe_id
            checks["timezone_timestamp_round_trip"] = row[1].tzinfo is not None
            checks["json_round_trip"] = row[2]["nested"]["ok"] is True
            conn.execute(
                text("insert into mg_runtime_probe (id, ts, payload) values (:id, :ts, cast(:payload as jsonb))"),
                [
                    {"id": str(uuid4()), "ts": now, "payload": json.dumps({"i": i})}
                    for i in range(5)
                ],
            )
            checks["bulk_insert_count"] = conn.execute(text("select count(*) from mg_runtime_probe")).scalar_one()
            checks["pagination_count"] = len(conn.execute(text("select id from mg_runtime_probe order by id limit 2 offset 1")).all())

        with engine.begin() as conn:
            conn.execute(text("create temporary table mg_commit_probe (id text primary key) on commit preserve rows"))
            conn.execute(text("insert into mg_commit_probe (id) values ('committed')"))
            checks["transaction_commit"] = True
        try:
            with engine.begin() as conn:
                conn.execute(text("create temporary table mg_rollback_probe (id text primary key)"))
                conn.execute(text("insert into mg_rollback_probe (id) values ('rolled_back')"))
                raise RuntimeError("force rollback")
        except RuntimeError:
            checks["transaction_rollback"] = True
    except Exception as exc:  # noqa: BLE001
        errors.append(type(exc).__name__)
    status = "PASSED" if not errors else "FAILED"
    print(json.dumps(result(status, checks, errors), indent=2, sort_keys=True, default=str))
    return 0 if status == "PASSED" else 1


if __name__ == "__main__":
    sys.exit(main())
