from __future__ import annotations

import pytest
from market_genome_cli.main import _redact_secrets


def test_redact_secrets_strips_configured_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "SECRETXYZ123")

    assert _redact_secrets("error fetching url with SECRETXYZ123 embedded") == "error fetching url with ***REDACTED*** embedded"


def test_redact_secrets_is_a_no_op_when_message_has_no_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "SECRETXYZ123")

    assert _redact_secrets("PROVIDER_UNAVAILABLE") == "PROVIDER_UNAVAILABLE"


def test_redact_secrets_is_a_no_op_when_key_not_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ALPHA_VANTAGE_API_KEY", raising=False)

    assert _redact_secrets("anything at all") == "anything at all"


def test_ledger_generator_never_references_the_api_key_env_var() -> None:
    """The forecast ledger and daily-run audit artifact are research evidence that
    gets copied around and sent to the user -- the generator must have no code path
    that could ever pull a secret into either file."""
    from pathlib import Path

    source = Path("scripts/generate_prospective_ledger.py").read_text(encoding="utf-8")
    assert "ALPHA_VANTAGE_API_KEY" not in source
    assert "os.environ" not in source


def test_timing_observation_recorder_never_references_the_api_key_env_var() -> None:
    """provider_timing_observations.csv and scheduler_timing_analysis.json are also
    research artifacts sent to the user -- the recorder must never read the key
    directly (the provider module reads it internally, but this script must not)."""
    from pathlib import Path

    source = Path("scripts/record_provider_timing_observation.py").read_text(encoding="utf-8")
    assert "ALPHA_VANTAGE_API_KEY" not in source
    assert "os.environ" not in source
