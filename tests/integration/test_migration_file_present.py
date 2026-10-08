from pathlib import Path


def test_foundation_migration_exists() -> None:
    migration = Path("infrastructure/migrations/versions/0001_foundation_schema.py")
    assert migration.exists()
    content = migration.read_text(encoding="utf-8")
    assert "price_bars" in content
    assert "uq_price_bar_identity" in content


def test_step_2_3_migration_exists() -> None:
    migration = Path("infrastructure/migrations/versions/0002_registry_imports_windows.py")
    assert migration.exists()
    content = migration.read_text(encoding="utf-8")
    assert "data_imports" in content
    assert "pattern_windows" in content
    assert "window_builds" in content
    assert "uq_pattern_window_identity" in content


def test_step_4_migration_exists() -> None:
    migration = Path("infrastructure/migrations/versions/0003_normalized_patterns.py")
    assert migration.exists()
    content = migration.read_text(encoding="utf-8")
    assert "normalization_builds" in content
    assert "normalized_patterns" in content
    assert "uq_normalized_pattern_identity" in content
