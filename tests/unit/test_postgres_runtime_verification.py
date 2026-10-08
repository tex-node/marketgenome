from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


def _module():
    path = Path("scripts/verify_postgres_runtime.py")
    spec = importlib.util.spec_from_file_location("verify_postgres_runtime", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_verify_postgres_runtime_skips_without_database_url(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.delenv("MARKET_GENOME_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    module = _module()

    code = module.main()
    output = capsys.readouterr().out

    assert code == 2
    assert "POSTGRES_DATABASE_URL_NOT_CONFIGURED" in output
    assert "market_genome:market_genome" not in output


def test_expected_revision_is_read_from_the_migration_chain_not_hardcoded() -> None:
    """Regression guard: EXPECTED_REVISION used to be a literal migration-id string
    that went stale (and silently broke VPS verification with ALEMBIC_REVISION_MISMATCH)
    every time a new migration was added -- it must always track the actual current
    Alembic head instead."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    module = _module()
    repo_root = Path(__file__).resolve().parents[2]
    config = Config(str(repo_root / "infrastructure" / "alembic.ini"))
    config.set_main_option("script_location", str(repo_root / "infrastructure" / "migrations"))
    actual_head = ScriptDirectory.from_config(config).get_current_head()

    assert module.EXPECTED_REVISION == actual_head
