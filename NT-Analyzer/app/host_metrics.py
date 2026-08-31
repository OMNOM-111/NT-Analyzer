"""CPU, memory and disk of the host, measured by the host itself.

The release panel needs load an owner can read at a glance, and the only
honest way to show CPU and RAM is to measure them. Nothing in this system did,
so this reads them from the operating system directly.

No dependency is added. Both platforms this product runs on are covered by
what the standard library already reaches: Linux through ``/proc`` — the
interface those figures come from anyway — and Windows through two documented
kernel32 calls. An unsupported platform returns nothing at all, so the caller
renders "Данные недоступны" instead of a number nobody measured.

CPU is a rate, so it needs two samples. The first call after start has no
previous sample and reports ``None`` rather than the meaningless
since-boot average; the second and later calls report the interval between
them.
"""
from __future__ import annotations

import os
import shutil
import sys
import threading
import time
from typing import Any, Dict, Optional

# One sample is kept so CPU can be a rate rather than a since-boot average.
_LOCK = threading.Lock()
_PREVIOUS: Optional[Dict[str, float]] = None
# Two reads closer together than this cannot produce a meaningful rate.
_MIN_INTERVAL_SEC = 0.2
_CACHE: Optional[Dict[str, Any]] = None
_CACHE_AT = 0.0
_CACHE_TTL_SEC = 2.0


def _linux_cpu_totals() -> Optional[Dict[str, float]]:
    try:
        with open("/proc/stat", "r", encoding="ascii", errors="replace") as handle:
            for line in handle:
                if not line.startswith("cpu "):
                    continue
                parts = [float(value) for value in line.split()[1:]]
                if len(parts) < 4:
                    return None
                idle = parts[3] + (parts[4] if len(parts) > 4 else 0.0)
                return {"total": sum(parts), "idle": idle}
    except (OSError, ValueError):
        return None
    return None


def _linux_memory_percent() -> Optional[float]:
    values: Dict[str, float] = {}
    try:
        with open("/proc/meminfo", "r", encoding="ascii", errors="replace") as handle:
            for line in handle:
                name, _, rest = line.partition(":")
                chunk = rest.strip().split()
                if chunk:
                    try:
                        values[name] = float(chunk[0])
                    except ValueError:
                        continue
    except OSError:
        return None
    total = values.get("MemTotal")
    available = values.get("MemAvailable")
    if not total:
        return None
    if available is None:
        free = values.get("MemFree", 0.0)
        cached = values.get("Cached", 0.0)
        buffers = values.get("Buffers", 0.0)
        available = free + cached + buffers
    return max(0.0, min(100.0, (1.0 - available / total) * 100.0))


def _windows_cpu_totals() -> Optional[Dict[str, float]]:
    try:
        import ctypes

        idle = ctypes.c_ulonglong()
        kernel = ctypes.c_ulonglong()
        user = ctypes.c_ulonglong()
        ok = ctypes.windll.kernel32.GetSystemTimes(  # type: ignore[attr-defined]
            ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user))
        if not ok:
            return None
        # Kernel time already includes idle time.
        return {"total": float(kernel.value + user.value), "idle": float(idle.value)}
    except Exception:
        return None


def _windows_memory_percent() -> Optional[float]:
    try:
        import ctypes

        class _Status(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = _Status()
        status.dwLength = ctypes.sizeof(_Status)
        ok = ctypes.windll.kernel32.GlobalMemoryStatusEx(  # type: ignore[attr-defined]
            ctypes.byref(status))
        if not ok:
            return None
        return max(0.0, min(100.0, float(status.dwMemoryLoad)))
    except Exception:
        return None


def _cpu_totals() -> Optional[Dict[str, float]]:
    if sys.platform.startswith("linux"):
        return _linux_cpu_totals()
    if sys.platform == "win32":
        return _windows_cpu_totals()
    return None


def memory_percent() -> Optional[float]:
    if sys.platform.startswith("linux"):
        return _linux_memory_percent()
    if sys.platform == "win32":
        return _windows_memory_percent()
    return None


def disk_percent(path: Any) -> Optional[float]:
    try:
        usage = shutil.disk_usage(str(path))
    except (OSError, ValueError):
        return None
    if not usage.total:
        return None
    return max(0.0, min(100.0, ((usage.total - usage.free) / usage.total) * 100.0))


def cpu_percent() -> Optional[float]:
    """Busy percentage since the previous call, or None until there is one."""
    global _PREVIOUS
    totals = _cpu_totals()
    if totals is None:
        return None
    now = time.monotonic()
    with _LOCK:
        previous = _PREVIOUS
        if previous is not None and now - previous["at"] < _MIN_INTERVAL_SEC:
            return previous.get("value")
        _PREVIOUS = {"total": totals["total"], "idle": totals["idle"], "at": now,
                     "value": previous.get("value") if previous else None}
        if previous is None:
            return None
        total_delta = totals["total"] - previous["total"]
        idle_delta = totals["idle"] - previous["idle"]
        if total_delta <= 0:
            return previous.get("value")
        value = max(0.0, min(100.0, (1.0 - idle_delta / total_delta) * 100.0))
        _PREVIOUS["value"] = value
        return value


def source() -> str:
    if sys.platform.startswith("linux"):
        return "proc"
    if sys.platform == "win32":
        return "kernel32"
    return ""


def sample(data_root: Any = None) -> Dict[str, Any]:
    """Host load for this environment, with absent keys where nothing was read.

    Keys are omitted rather than set to a placeholder: a consumer must not be
    able to mistake "not measured" for a reading.
    """
    global _CACHE, _CACHE_AT
    now = time.monotonic()
    with _LOCK:
        cached, cached_at = _CACHE, _CACHE_AT
    if cached is not None and now - cached_at < _CACHE_TTL_SEC:
        return dict(cached)

    out: Dict[str, Any] = {}
    origin = source()
    if origin:
        out["source"] = origin
    cpu = cpu_percent()
    if cpu is not None:
        out["cpu_percent"] = round(cpu, 1)
    memory = memory_percent()
    if memory is not None:
        out["memory_percent"] = round(memory, 1)
    root = data_root if data_root is not None else os.getcwd()
    disk = disk_percent(root)
    if disk is not None:
        out["disk_percent"] = round(disk, 1)

    with _LOCK:
        _CACHE, _CACHE_AT = dict(out), now
    return out
