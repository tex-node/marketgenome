from __future__ import annotations

from market_genome_cli.resource_guard import (
    ResourceSnapshot,
    evaluate_resource_guard,
    parse_meminfo,
)


def test_parse_meminfo_reads_available_ram_and_free_swap() -> None:
    snapshot = parse_meminfo(
        """MemTotal:       11963040 kB
MemAvailable:    1536000 kB
SwapTotal:       4194304 kB
SwapFree:         786432 kB"""
    )

    assert snapshot.available_ram_mb == 1500
    assert snapshot.free_swap_mb == 768


def test_resource_guard_passes_when_thresholds_are_met() -> None:
    result = evaluate_resource_guard(
        ResourceSnapshot(available_ram_mb=1500, free_swap_mb=768),
        min_available_ram_mb=1024,
        min_free_swap_mb=512,
    )

    assert result.ok
    assert result.reasons == ()


def test_resource_guard_reports_ram_and_swap_threshold_failures() -> None:
    result = evaluate_resource_guard(
        ResourceSnapshot(available_ram_mb=900, free_swap_mb=128),
        min_available_ram_mb=1024,
        min_free_swap_mb=512,
    )

    assert not result.ok
    assert result.reasons == (
        "AVAILABLE_RAM_MB_BELOW_THRESHOLD:900<1024",
        "FREE_SWAP_MB_BELOW_THRESHOLD:128<512",
    )


def test_resource_guard_skips_disk_check_when_threshold_not_requested() -> None:
    """Existing callers (e.g. studies prepare-data) never passed min_free_disk_mb and
    must keep their exact prior behavior -- disk is opt-in, not silently enforced."""
    result = evaluate_resource_guard(
        ResourceSnapshot(available_ram_mb=1500, free_swap_mb=768, free_disk_mb=1000),
        min_available_ram_mb=1024,
        min_free_swap_mb=512,
    )

    assert result.ok
    assert result.reasons == ()


def test_resource_guard_reports_disk_threshold_failure_when_requested() -> None:
    result = evaluate_resource_guard(
        ResourceSnapshot(available_ram_mb=1500, free_swap_mb=768, free_disk_mb=10_000),
        min_available_ram_mb=1024,
        min_free_swap_mb=512,
        min_free_disk_mb=15_000,
    )

    assert not result.ok
    assert result.reasons == ("FREE_DISK_MB_BELOW_THRESHOLD:10000<15000",)


def test_resource_guard_reports_disk_unavailable_when_requested_but_unknown() -> None:
    result = evaluate_resource_guard(
        ResourceSnapshot(available_ram_mb=1500, free_swap_mb=768, free_disk_mb=None),
        min_available_ram_mb=1024,
        min_free_swap_mb=512,
        min_free_disk_mb=15_000,
    )

    assert not result.ok
    assert result.reasons == ("DISK_FREE_UNAVAILABLE",)
