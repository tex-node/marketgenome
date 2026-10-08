from __future__ import annotations

import shutil
from dataclasses import dataclass


class ResourceGuardError(RuntimeError):
    """Raised when host resources are below the configured safety floor."""


@dataclass(frozen=True)
class ResourceSnapshot:
    available_ram_mb: int | None
    free_swap_mb: int | None
    free_disk_mb: int | None = None


@dataclass(frozen=True)
class ResourceGuardResult:
    ok: bool
    reasons: tuple[str, ...]
    snapshot: ResourceSnapshot


def _kb_to_mb(value: int) -> int:
    return value // 1024


def parse_meminfo(text: str) -> ResourceSnapshot:
    values: dict[str, int] = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, raw_value = line.split(":", 1)
        parts = raw_value.strip().split()
        if not parts:
            continue
        try:
            values[key] = int(parts[0])
        except ValueError:
            continue
    mem_available_kb = values.get("MemAvailable")
    swap_free_kb = values.get("SwapFree")
    return ResourceSnapshot(
        available_ram_mb=_kb_to_mb(mem_available_kb) if mem_available_kb is not None else None,
        free_swap_mb=_kb_to_mb(swap_free_kb) if swap_free_kb is not None else None,
    )


def read_resource_snapshot(meminfo_path: str = "/proc/meminfo", disk_path: str = "/") -> ResourceSnapshot:
    with open(meminfo_path, encoding="utf-8") as handle:
        base = parse_meminfo(handle.read())
    try:
        free_disk_mb = shutil.disk_usage(disk_path).free // (1024 * 1024)
    except OSError:
        free_disk_mb = None
    return ResourceSnapshot(available_ram_mb=base.available_ram_mb, free_swap_mb=base.free_swap_mb, free_disk_mb=free_disk_mb)


def evaluate_resource_guard(
    snapshot: ResourceSnapshot,
    *,
    min_available_ram_mb: int,
    min_free_swap_mb: int,
    min_free_disk_mb: int | None = None,
) -> ResourceGuardResult:
    reasons: list[str] = []
    if snapshot.available_ram_mb is None:
        reasons.append("MEM_AVAILABLE_UNAVAILABLE")
    elif snapshot.available_ram_mb < min_available_ram_mb:
        reasons.append(
            f"AVAILABLE_RAM_MB_BELOW_THRESHOLD:{snapshot.available_ram_mb}<{min_available_ram_mb}"
        )
    if snapshot.free_swap_mb is None:
        reasons.append("SWAP_FREE_UNAVAILABLE")
    elif snapshot.free_swap_mb < min_free_swap_mb:
        reasons.append(f"FREE_SWAP_MB_BELOW_THRESHOLD:{snapshot.free_swap_mb}<{min_free_swap_mb}")
    # Disk is opt-in (min_free_disk_mb=None skips it) so existing callers that never
    # cared about disk (e.g. studies prepare-data) keep their exact prior behavior.
    if min_free_disk_mb is not None:
        if snapshot.free_disk_mb is None:
            reasons.append("DISK_FREE_UNAVAILABLE")
        elif snapshot.free_disk_mb < min_free_disk_mb:
            reasons.append(f"FREE_DISK_MB_BELOW_THRESHOLD:{snapshot.free_disk_mb}<{min_free_disk_mb}")
    return ResourceGuardResult(ok=not reasons, reasons=tuple(reasons), snapshot=snapshot)
