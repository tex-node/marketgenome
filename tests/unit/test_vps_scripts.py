from __future__ import annotations

from pathlib import Path


def test_vps_scripts_have_safe_flags_and_required_commands() -> None:
    for path in Path("scripts/vps").glob("*.sh"):
        text = path.read_text(encoding="utf-8")
        assert "set -euo pipefail" in text
        assert "docker compose" in text
    assert "pg_dump" in Path("scripts/vps/backup_market_genome.sh").read_text(encoding="utf-8")
    assert "stopped_before" in Path("scripts/vps/run_yahoo_pilot.sh").read_text(encoding="utf-8")
