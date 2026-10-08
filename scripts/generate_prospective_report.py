"""Reproducible prospective evaluation report generator.

Reads the latest frozen protocol, the latest evaluation snapshot (with its per-horizon
metrics and bootstrap intervals), the snapshot history, and the newest daily-run audit
artifact -- entirely derived from the database and existing artifacts, never a source of
truth itself. Safe to re-run at any time; always overwrites `prospective_report.md` with
the current state, so the scheduled daily cycle (via scripts/vps/run_prospective_daily.sh)
keeps the report current with no manual step.
"""
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from market_genome_domain.database import SessionLocal
from market_genome_domain.models import (
    ProspectiveEvaluationSnapshot,
    ProspectiveProtocol,
)
from sqlalchemy.orm import Session

REPORT_FILENAME = "prospective_report.md"


def _num(value: Any) -> str:
    return f"{float(value):.4f}" if value is not None else "—"


def _pct(value: Any) -> str:
    return f"{float(value):.1%}" if value is not None else "—"


def _newest_daily_run_artifact(output_dir: Path) -> dict[str, Any]:
    artifacts = sorted(output_dir.glob("prospective_daily_run_*.json"))
    if not artifacts:
        return {}
    try:
        return json.loads(artifacts[-1].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def gather_report_data(session: Session, protocol_code: str, output_dir: Path) -> dict[str, Any]:
    protocol = (
        session.query(ProspectiveProtocol)
        .filter(ProspectiveProtocol.protocol_code == protocol_code, ProspectiveProtocol.status == "FROZEN")
        .order_by(ProspectiveProtocol.created_at.desc())
        .first()
    )
    if protocol is None:
        raise SystemExit(f"NO_FROZEN_PROTOCOL:{protocol_code}")

    snapshot = (
        session.query(ProspectiveEvaluationSnapshot)
        .filter(ProspectiveEvaluationSnapshot.protocol_id == protocol.id)
        .order_by(ProspectiveEvaluationSnapshot.created_at.desc())
        .first()
    )

    history = (
        session.query(ProspectiveEvaluationSnapshot)
        .filter(
            ProspectiveEvaluationSnapshot.protocol_id == protocol.id,
            ProspectiveEvaluationSnapshot.primary_horizon_matured_count.isnot(None),
        )
        .order_by(ProspectiveEvaluationSnapshot.created_at.desc())
        .limit(30)
        .all()
    )
    history = list(reversed(history))

    artifact = _newest_daily_run_artifact(output_dir)
    return {
        "generated_at": datetime.now(UTC),
        "protocol": {
            "id": protocol.id,
            "code": protocol.protocol_code,
            "status": protocol.status,
            "frozen_at": protocol.frozen_at,
            "hypothesis": protocol.hypothesis_text,
            "primary_horizon": protocol.primary_horizon,
            "minimum_evidence": protocol.minimum_evidence_matured_forecasts,
            "preferred_evidence": protocol.preferred_evidence_matured_forecasts,
        },
        "snapshot": {
            "id": snapshot.id if snapshot else None,
            "as_of": snapshot.as_of if snapshot else None,
            "forecast_count": snapshot.forecast_count if snapshot else None,
            "matured_count": snapshot.matured_count if snapshot else None,
            "primary_horizon_matured_count": snapshot.primary_horizon_matured_count if snapshot else None,
            "brier_score": snapshot.brier_score if snapshot else None,
            "brier_skill_vs_unconditional": snapshot.brier_skill_vs_unconditional if snapshot else None,
            "log_loss": snapshot.log_loss if snapshot else None,
            "expected_calibration_error": snapshot.expected_calibration_error if snapshot else None,
            "direction_accuracy": snapshot.direction_accuracy if snapshot else None,
            "balanced_accuracy": snapshot.balanced_accuracy if snapshot else None,
            "mcc": snapshot.mcc if snapshot else None,
            "bootstrap_ci_low": snapshot.bootstrap_ci_low if snapshot else None,
            "bootstrap_ci_high": snapshot.bootstrap_ci_high if snapshot else None,
            "status": snapshot.status if snapshot else None,
            "per_horizon_metrics": (dict(snapshot.per_horizon_metrics) if snapshot and snapshot.per_horizon_metrics else {}),
        },
        "history": [
            {
                "as_of": row.as_of,
                "forecast_count": row.forecast_count,
                "matured_count": row.matured_count,
                "primary_horizon_matured_count": row.primary_horizon_matured_count,
                "brier_skill_vs_unconditional": row.brier_skill_vs_unconditional,
            }
            for row in history
        ],
        "latest_run": artifact,
    }


def render_markdown(data: dict[str, Any]) -> str:
    protocol = data["protocol"]
    snapshot = data["snapshot"]
    per_horizon = snapshot["per_horizon_metrics"]
    latest_run = data["latest_run"]

    lines: list[str] = []
    lines.append("# Market Genome — Prospective Context Forecast Report")
    lines.append("")
    lines.append(f"- Generated (UTC): `{data['generated_at'].isoformat()}`")
    lines.append(f"- Snapshot: `{snapshot['id']}` — as of `{snapshot['as_of']}`")
    lines.append(f"- Protocol: `{protocol['code']}` (status `{protocol['status']}`, frozen `{protocol['frozen_at']}`)")
    lines.append(
        f"- Latest daily run: `{latest_run.get('run_timestamp')}` — "
        f"{latest_run.get('new_forecast_count', 0)} new forecasts, "
        f"{latest_run.get('matured_count_this_run', 0)} matured"
    )
    lines.append("")

    lines.append(f"## Status: **`{snapshot['status']}`**")
    lines.append("")
    lines.append(
        f"Primary-horizon ({protocol['primary_horizon']}-bar) matured forecasts: "
        f"**{snapshot['primary_horizon_matured_count']}** "
        f"of {protocol['minimum_evidence']} minimum / {protocol['preferred_evidence']} preferred."
    )
    lines.append("")

    lines.append("## Headline metrics (primary horizon)")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|---|---|")
    lines.append(f"| Brier score | {_num(snapshot['brier_score'])} |")
    lines.append(f"| Brier skill vs unconditional | {_num(snapshot['brier_skill_vs_unconditional'])} |")
    lines.append(f"| Bootstrap 95% CI | [{_num(snapshot['bootstrap_ci_low'])}, {_num(snapshot['bootstrap_ci_high'])}] |")
    lines.append(f"| Log loss | {_num(snapshot['log_loss'])} |")
    lines.append(f"| Expected calibration error | {_num(snapshot['expected_calibration_error'])} |")
    lines.append(f"| Direction accuracy | {_pct(snapshot['direction_accuracy'])} |")
    lines.append(f"| Balanced accuracy | {_pct(snapshot['balanced_accuracy'])} |")
    lines.append(f"| MCC | {_num(snapshot['mcc'])} |")
    lines.append("")

    lines.append("## Per-horizon metrics")
    lines.append("")
    lines.append("| Horizon | Matured | Brier | Skill vs unconditional | Bootstrap 95% CI |")
    lines.append("|---|---|---|---|---|")
    if per_horizon:
        for horizon in sorted(per_horizon, key=lambda h: int(h)):
            metrics = per_horizon[horizon]
            lines.append(
                f"| {horizon} | {metrics.get('sample_count', 0)} | {_num(metrics.get('brier_score'))} "
                f"| {_num(metrics.get('brier_skill_vs_unconditional'))} "
                f"| [{_num(metrics.get('bootstrap_ci_low'))}, {_num(metrics.get('bootstrap_ci_high'))}] |"
            )
    else:
        lines.append("| _no matured forecasts yet_ |")
    lines.append("")

    lines.append("## Trend (primary-horizon matured / skill)")
    lines.append("")
    lines.append("| As of | Forecasts | Matured | Primary horizon | Skill |")
    lines.append("|---|---|---|---|---|")
    for row in data["history"]:
        lines.append(
            f"| {row['as_of'].strftime('%Y-%m-%d %H:%M') if row['as_of'] else '—'} "
            f"| {row['forecast_count']} | {row['matured_count']} "
            f"| {row['primary_horizon_matured_count']} | {_num(row['brier_skill_vs_unconditional'])} |"
        )
    lines.append("")

    lines.append("## Reading")
    lines.append("")
    status = snapshot["status"]
    primary_n = snapshot["primary_horizon_matured_count"] or 0
    minimum = protocol["minimum_evidence"]
    skill = snapshot["brier_skill_vs_unconditional"]
    ci_low = snapshot["bootstrap_ci_low"]
    if status == "PROSPECTIVE_EVIDENCE_ACCUMULATING":
        lines.append(
            f"Evidence is still accumulating ({primary_n} of {minimum} minimum matured at the primary horizon). "
            "Per the early-result firewall this is not interpreted yet."
        )
    elif status == "PROSPECTIVE_CONTEXT_SIGNAL_NOT_SUPPORTED":
        lines.append("Brier skill vs unconditional is not positive; the frozen hypothesis is not supported.")
    elif status == "PROSPECTIVE_CONTEXT_SIGNAL_WEAK":
        lines.append("Brier skill is positive but the confidence interval does not clearly exclude zero.")
    else:
        lines.append("Brier skill is positive with a confidence interval excluding zero.")
    if skill is not None:
        lines.append(
            f"Primary-horizon skill is {_num(skill)} with a 95% bootstrap CI "
            f"[{_num(ci_low)}, {_num(snapshot['bootstrap_ci_high'])}]."
        )
    lines.append(
        "No Market DNA, no AI/ML model, no trading logic. The protocol is frozen; the v2 candidate "
        "(hierarchical-shrinkage estimator) is pre-registered and not activated."
    )
    lines.append("")

    lines.append("## Sources")
    lines.append("")
    lines.append("- This report is derived from the database (protocol, evaluation snapshot) and the newest "
                 "`prospective_daily_run_*.json` audit artifact; it is not itself a source of truth.")
    lines.append("- Companion artifacts: `forecast_ledger.csv` and `run_history.csv` in the same directory.")
    lines.append("")

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--protocol", default="market_context_forecast_v1")
    parser.add_argument("--output-dir", default="research/reports/prospective_context_validation")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    with SessionLocal() as session:
        data = gather_report_data(session, args.protocol, output_dir)
    markdown = render_markdown(data)

    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / REPORT_FILENAME
    report_path.write_text(markdown, encoding="utf-8")
    print(json.dumps({"report_path": str(report_path), "as_of": str(data["snapshot"]["as_of"]), "status": data["snapshot"]["status"]}, indent=2))


if __name__ == "__main__":
    main()