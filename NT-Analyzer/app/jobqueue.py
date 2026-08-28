"""
NT-Analyzer file-queue helpers (shared by CLI and backend).

Contract mirrors docs/architecture/job-schema.md and tools/enqueue-smoke-job.ps1:

    pending/.staging/<job_id>/job.json.tmp -> job.json (rename)
                              ^
    pending/.staging/<job_id>/  --(Directory move)-->  pending/<job_id>/

The bridge AddOn picks up `pending/<job_id>/`, moves it to `running/`,
then to `done|failed|cancelled/`.

This module is read-mostly: the only mutating operation is `create_job`.
"""
from __future__ import annotations

import hashlib
import copy
import json
import os
import re
import shutil
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from . import governance
from . import durable
from . import marginrefresh  # informational margin catalog auto-refresh
from . import portfolio_cells
from . import report_assessment
from . import strategy_families
from . import strategy_lifecycle
from . import ninjatrader_ops
from . import runtime_env

# ---------------------------------------------------------------------------
# Whitelist + defaults. Strategy whitelist on the backend MUST match what the
# bridge accepts; the bridge has its own whitelist and rejects unknown classes,
# so this is just a UX guard rail to keep the UI honest.
# ---------------------------------------------------------------------------

# Conservative fallback used only when the bridge has not yet written
# data/catalog/strategies.json (e.g. NinjaTrader is offline). The bridge
# itself enforces the real whitelist on every job.
_FALLBACK_STRATEGIES: List[str] = ["SampleMACrossOver"]

# Public: kept for backwards-compatibility with /api/strategies and the
# pre-catalog UI. Always re-evaluated through `whitelisted_strategies()`.
WHITELISTED_STRATEGIES: List[str] = list(_FALLBACK_STRATEGIES)

JOB_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,127}$")
QUEUE_SUBDIRS = ("pending", "running", "done", "failed", "cancelled")
BATCH_ID_PATTERN = JOB_ID_PATTERN
_RESERVED_WINDOWS_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}

# Project-level validation status. The bridge path has been manually
# cross-checked against NinjaTrader Strategy Analyzer and is now the accepted
# baseline for future strategy work.
VALIDATED_AGAINST_STRATEGY_ANALYZER = True


# ---------------------------------------------------------------------------
# In-memory caches for queue/catalog performance:
#
#   `/api/jobs?limit=500` against a 720-job repo was ~30s because every call
#   re-read job.json + result.json + trades.json for every job. Done/failed
#   job folders never change once written, so we cache parsed summaries
#   keyed by (job_id, dir_mtime, status). Only changed folders are re-read.
#
# Cache invalidation is automatic: a folder's mtime changes when a status
# move (running -> done) happens or when the bridge writes new artefacts.
# The hot subset lives in memory. A compact derived snapshot is also persisted
# beside the jobs directory so global report sorting does not re-read thousands
# of immutable result files after every backend restart.
# ---------------------------------------------------------------------------

# job_id -> (signature, summary_dict).  signature == (status, mtime).
_JOB_SUMMARY_CACHE: Dict[str, Tuple[Tuple[str, float], Dict[str, Any]]] = {}
_JOB_SUMMARY_CACHE_LOADED = False
_JOB_SUMMARY_CACHE_DIRTY = False
_JOB_LOCATION_FP: Optional[Tuple[int, float]] = None
_JOB_LOCATION_INDEX: Dict[str, Tuple[str, Path, float]] = {}

# batch_id -> (signature, aggregate_dict).  signature combines bdir mtime,
# child status, and child mtime so aggregate refreshes whenever any child moves.
_BATCH_METRICS_CACHE: Dict[str, Tuple[Tuple[Any, ...], Dict[str, Any]]] = {}

# Chart historical fallback index: root -> [ {job_id, dir, instrument, timeframe}, ... ]
# newest-first.  Building it walks thousands of job dirs and reads job.json, so
# it is TTL-cached: the desktop chart grid calls read_instrument_bars for every
# "waiting" instrument on every poll tick and must never pay that scan per chart.
_INSTR_BARS_INDEX_LOCK = threading.Lock()
_INSTR_BARS_INDEX: Dict[str, List[Dict[str, Any]]] = {}
_INSTR_BARS_INDEX_AT: float = 0.0
_INSTR_BARS_INDEX_TTL: float = 20.0

# Last queue fingerprint that triggered a sync_report_numbers() call; reused
# until the queue itself changes.  Avoids the per-request full scan.
_REPORT_NUMBERS_FP: Optional[Tuple[int, float]] = None
_REPORT_NUMBERS_VALUE: Dict[str, int] = {}
_REPORT_NUMBERS_FILE_SIG: Optional[Tuple[int, int]] = None
_REPORT_FAVORITES_RAW_SIG: Optional[Tuple[int, int]] = None
_REPORT_FAVORITES_RAW_VALUE: Optional[Dict[str, Any]] = None
_REPORT_FAVORITE_KEYS_SIG: Optional[Tuple[int, int]] = None
_REPORT_FAVORITE_KEYS_VALUE: set[str] = set()
_JSON_ARRAY_ARTIFACT_CACHE: Dict[str, Tuple[Tuple[int, int], List[Any]]] = {}
_JSON_ARRAY_ARTIFACT_CACHE_ORDER: List[str] = []
_JSON_ARRAY_ARTIFACT_CACHE_BYTES: Dict[str, int] = {}
_JSON_ARRAY_ARTIFACT_CACHE_MAX_BYTES = 180 * 1024 * 1024
_PORTFOLIO_LAYOUT_FP: Optional[Tuple[int, float]] = None
_PORTFOLIO_LAYOUT_VALUE: Dict[str, Dict[Any, Dict[str, Any]]] = {
    "profiles": {},
    "lookup": {},
}


def _validate_safe_id(value: str, kind: str) -> str:
    value = str(value or "")
    if not JOB_ID_PATTERN.fullmatch(value):
        raise JobValidationError(f"invalid {kind}")
    if value in (".", "..") or value.startswith(".") or value.endswith("."):
        raise JobValidationError(f"invalid {kind}")
    stem = value.split(".", 1)[0].upper()
    if stem in _RESERVED_WINDOWS_NAMES:
        raise JobValidationError(f"invalid {kind}")
    return value


def _safe_child_path(parent: Path, child_name: str, kind: str) -> Path:
    child_name = _validate_safe_id(child_name, kind)
    base = parent.resolve()
    target = (base / child_name).resolve()
    try:
        target.relative_to(base)
    except ValueError as e:
        raise JobValidationError(f"invalid {kind}") from e
    if target.parent != base:
        raise JobValidationError(f"invalid {kind}")
    return target


def reset_caches() -> None:
    """Drop in-memory list_jobs/list_batches caches (used by tests)."""
    global _JOB_LOCATION_FP, _JOB_LOCATION_INDEX
    global _JOB_SUMMARY_CACHE_LOADED, _JOB_SUMMARY_CACHE_DIRTY
    global _REPORT_NUMBERS_FP, _REPORT_NUMBERS_VALUE, _REPORT_NUMBERS_FILE_SIG
    global _REPORT_FAVORITES_RAW_SIG, _REPORT_FAVORITES_RAW_VALUE
    global _REPORT_FAVORITE_KEYS_SIG, _REPORT_FAVORITE_KEYS_VALUE
    global _JSON_ARRAY_ARTIFACT_CACHE_BYTES
    global _PORTFOLIO_LAYOUT_FP, _PORTFOLIO_LAYOUT_VALUE
    _JOB_SUMMARY_CACHE.clear()
    _JOB_SUMMARY_CACHE_LOADED = False
    _JOB_SUMMARY_CACHE_DIRTY = False
    _BATCH_METRICS_CACHE.clear()
    _JSON_ARRAY_ARTIFACT_CACHE.clear()
    _JSON_ARRAY_ARTIFACT_CACHE_ORDER.clear()
    _JSON_ARRAY_ARTIFACT_CACHE_BYTES = {}
    _JOB_LOCATION_FP = None
    _JOB_LOCATION_INDEX = {}
    _REPORT_NUMBERS_FP = None
    _REPORT_NUMBERS_VALUE = {}
    _REPORT_NUMBERS_FILE_SIG = None
    _REPORT_FAVORITES_RAW_SIG = None
    _REPORT_FAVORITES_RAW_VALUE = None
    _REPORT_FAVORITE_KEYS_SIG = None
    _REPORT_FAVORITE_KEYS_VALUE = set()
    _PORTFOLIO_LAYOUT_FP = None
    _PORTFOLIO_LAYOUT_VALUE = {"profiles": {}, "lookup": {}}
    strategy_families.reset_caches()


def _report_summary_cache_path() -> Path:
    return jobs_dir().parent / "cache" / "report_summaries_v2.json"


def _load_persisted_report_summaries() -> None:
    global _JOB_SUMMARY_CACHE_LOADED, _JOB_SUMMARY_CACHE_DIRTY
    if _JOB_SUMMARY_CACHE_LOADED:
        return
    _JOB_SUMMARY_CACHE_LOADED = True
    path = _report_summary_cache_path()
    try:
        doc = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, TypeError):
        return
    jobs = doc.get("jobs") if isinstance(doc, dict) else None
    if not isinstance(jobs, dict):
        return
    for job_id, payload in jobs.items():
        if not isinstance(payload, dict) or not isinstance(payload.get("summary"), dict):
            continue
        signature = payload.get("signature")
        if not isinstance(signature, list) or len(signature) != 2:
            continue
        try:
            _JOB_SUMMARY_CACHE[str(job_id)] = (
                (str(signature[0]), float(signature[1])),
                payload["summary"],
            )
        except (TypeError, ValueError):
            continue
    _JOB_SUMMARY_CACHE_DIRTY = False


def _persist_report_summaries() -> None:
    global _JOB_SUMMARY_CACHE_DIRTY
    if not _JOB_SUMMARY_CACHE_DIRTY:
        return
    path = _report_summary_cache_path()
    payload = {
        "schema_version": 1,
        "updated_at_utc": utcnow_iso(),
        "jobs": {
            job_id: {"signature": [signature[0], signature[1]], "summary": summary}
            for job_id, (signature, summary) in _JOB_SUMMARY_CACHE.items()
        },
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        os.replace(tmp, path)
        _JOB_SUMMARY_CACHE_DIRTY = False
    except OSError:
        return


def cache_stats() -> Dict[str, int]:
    return {
        "jobs_cached":    len(_JOB_SUMMARY_CACHE),
        "batches_cached": len(_BATCH_METRICS_CACHE),
    }


def utcnow_iso(precision: str = "seconds") -> str:
    now = datetime.now(timezone.utc)
    if precision == "ms":
        return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"
    return now.strftime("%Y-%m-%dT%H:%M:%SZ")


def gen_job_id(prefix: str = "ui") -> str:
    return f"{prefix}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')[:-3]}Z"


def project_root() -> Path:
    """
    Resolve project root. Priority:
      1. env NT_ANALYZER_ROOT
      2. parent dir of this file (NT-Analyzer/app/jobqueue.py -> NT-Analyzer)
    """
    env = os.environ.get("NT_ANALYZER_ROOT")
    if env:
        p = Path(env).resolve()
        if (p / "jobs").exists():
            return p
    here = Path(__file__).resolve().parent.parent
    return here


def _bridge_config_path() -> Path:
    env = os.environ.get("NT_ANALYZER_BRIDGE_CONFIG")
    if env:
        return Path(env).expanduser()
    user_profile = Path(os.environ.get("USERPROFILE") or Path.home())
    return user_profile / "Documents" / "NinjaTrader 8" / "bin" / "Custom" / "NTAnalyzerBridge.config.json"


def _resolve_configured_jobs_dir(raw: Any) -> Optional[Path]:
    if not isinstance(raw, str) or not raw.strip():
        return None
    p = Path(raw.strip()).expanduser()
    if not p.is_absolute():
        p = project_root() / p
    return p.resolve()


def _configured_jobs_dir() -> Optional[Path]:
    env = os.environ.get("NT_ANALYZER_JOBS_DIR") or os.environ.get("NTA_JOBS_DIR")
    p = _resolve_configured_jobs_dir(env)
    if p is not None:
        return p

    cfg_path = _bridge_config_path()
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(cfg, dict):
        return None

    # Only honor the user's NinjaTrader bridge config when it points at this
    # project. Unit tests monkey-patch project_root(), and should keep using
    # the temporary <project_root>/jobs tree.
    cfg_project = cfg.get("project_root")
    if isinstance(cfg_project, str) and cfg_project.strip():
        try:
            if Path(cfg_project).expanduser().resolve() != project_root().resolve():
                return None
        except OSError:
            return None
    return _resolve_configured_jobs_dir(cfg.get("jobs_dir"))


def jobs_dir() -> Path:
    configured = _configured_jobs_dir()
    if runtime_env.is_staging():
        return runtime_env.data_path("jobs", project_root=project_root())
    return configured or (project_root() / "jobs")


def default_jobs_dir() -> Path:
    if runtime_env.is_staging():
        return runtime_env.data_path("jobs", project_root=project_root())
    return project_root() / "jobs"


# ---------------------------------------------------------------------------
# Catalog (bridge-generated metadata of strategies + instruments)
# ---------------------------------------------------------------------------

def catalog_dir() -> Path:
    return runtime_env.data_path("catalog", project_root=project_root())


def _environment_read_path(section: str, name: str) -> Path:
    """Read isolated data first, then safe checked-in baselines on staging.

    Mutable writes always target the active environment. This fallback keeps a
    clean staging root useful without copying or modifying production files.
    """
    active = runtime_env.data_path(section, name, project_root=project_root())
    if active.is_file() or not runtime_env.is_staging():
        return active
    baseline = project_root() / "data" / section / name
    return baseline if baseline.is_file() else active


def reports_dir() -> Path:
    return runtime_env.data_path("reports", project_root=project_root())


def report_numbers_file() -> Path:
    return reports_dir() / "report_numbers.json"


def report_favorites_file() -> Path:
    return reports_dir() / "favorites.json"


def _report_key(kind: str, report_id: str) -> str:
    return f"{kind}:{report_id}"


def _empty_report_favorites() -> Dict[str, Any]:
    return {"schema_version": "1.0", "favorites": {}}


def _file_cache_sig(path: Path) -> Optional[Tuple[int, int]]:
    try:
        st = path.stat()
    except OSError:
        return None
    return (st.st_size, st.st_mtime_ns)


def _invalidate_report_favorites_cache() -> None:
    global _REPORT_FAVORITES_RAW_SIG, _REPORT_FAVORITES_RAW_VALUE
    global _REPORT_FAVORITE_KEYS_SIG, _REPORT_FAVORITE_KEYS_VALUE
    _REPORT_FAVORITES_RAW_SIG = None
    _REPORT_FAVORITES_RAW_VALUE = None
    _REPORT_FAVORITE_KEYS_SIG = None
    _REPORT_FAVORITE_KEYS_VALUE = set()


def _write_report_favorites(data: Dict[str, Any]) -> None:
    _write_json_atomic(report_favorites_file(), data)
    _invalidate_report_favorites_cache()


def _normalize_report_ref(kind: str, report_id: str) -> Tuple[str, str]:
    kind = str(kind or "").strip().lower()
    if kind not in {"job", "batch"}:
        raise JobValidationError("report kind must be 'job' or 'batch'")
    report_id = _safe_job_id(report_id) if kind == "job" else _safe_batch_id(report_id)
    return kind, report_id


def _read_report_favorites_raw() -> Dict[str, Any]:
    global _REPORT_FAVORITES_RAW_SIG, _REPORT_FAVORITES_RAW_VALUE
    p = report_favorites_file()
    if not p.is_file():
        return _empty_report_favorites()
    sig = _file_cache_sig(p)
    if sig is not None and _REPORT_FAVORITES_RAW_SIG == sig and _REPORT_FAVORITES_RAW_VALUE is not None:
        return _REPORT_FAVORITES_RAW_VALUE
    try:
        with open(p, "r", encoding="utf-8-sig") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return _empty_report_favorites()
    if not isinstance(data, dict):
        return _empty_report_favorites()
    favorites = data.get("favorites")
    if isinstance(favorites, list):
        converted: Dict[str, Any] = {}
        for entry in favorites:
            if not isinstance(entry, dict):
                continue
            kind = str(entry.get("kind") or "").strip().lower()
            rid = str(entry.get("id") or entry.get("report_id") or "").strip()
            if kind in {"job", "batch"} and rid:
                converted[_report_key(kind, rid)] = entry
        data["favorites"] = converted
    elif not isinstance(favorites, dict):
        data["favorites"] = {}
    data["schema_version"] = "1.0"
    if sig is not None:
        _REPORT_FAVORITES_RAW_SIG = sig
        _REPORT_FAVORITES_RAW_VALUE = data
    return data


def _report_favorite_key_set() -> set[str]:
    global _REPORT_FAVORITE_KEYS_SIG, _REPORT_FAVORITE_KEYS_VALUE
    sig = _file_cache_sig(report_favorites_file())
    if sig is not None and _REPORT_FAVORITE_KEYS_SIG == sig:
        return set(_REPORT_FAVORITE_KEYS_VALUE)
    data = _read_report_favorites_raw()
    keys = {str(k) for k in (data.get("favorites") or {}).keys()}
    if sig is not None:
        _REPORT_FAVORITE_KEYS_SIG = sig
        _REPORT_FAVORITE_KEYS_VALUE = set(keys)
    return keys


def is_report_favorite(kind: str, report_id: str) -> bool:
    kind, report_id = _normalize_report_ref(kind, report_id)
    return _report_key(kind, report_id) in _report_favorite_key_set()


def _json_sha256(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _file_artifact_signature(path: Path) -> Optional[Dict[str, Any]]:
    if not path.is_file():
        return None
    try:
        st = path.stat()
    except OSError:
        return None
    out: Dict[str, Any] = {
        "name": path.name,
        "size": st.st_size,
        "mtime_ns": st.st_mtime_ns,
    }
    # Full bars/trades files can be large; metadata is enough to detect normal
    # report churn, while small JSON files get a content hash.
    if st.st_size <= 5 * 1024 * 1024:
        try:
            h = hashlib.sha256()
            with open(path, "rb") as fh:
                for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                    h.update(chunk)
            out["sha256"] = h.hexdigest()
        except OSError:
            pass
    return out


def _artifact_manifest_for_dir(path: Path) -> List[Dict[str, Any]]:
    if not path.is_dir():
        return []
    out: List[Dict[str, Any]] = []
    for child in sorted(path.glob("*.json"), key=lambda p: p.name):
        sig = _file_artifact_signature(child)
        if sig:
            out.append(sig)
    return out


def _snapshot_strategy_doc(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    if snapshot.get("kind") == "job":
        full = snapshot.get("full") if isinstance(snapshot.get("full"), dict) else {}
        job = full.get("job") if isinstance(full.get("job"), dict) else {}
        strategy = job.get("strategy") if isinstance(job.get("strategy"), dict) else {}
        return strategy if isinstance(strategy, dict) else {}
    batch = snapshot.get("batch") if isinstance(snapshot.get("batch"), dict) else {}
    strategy = batch.get("strategy") if isinstance(batch.get("strategy"), dict) else {}
    if isinstance(strategy, dict) and strategy:
        return strategy
    for child in snapshot.get("children_full") or []:
        if not isinstance(child, dict):
            continue
        job = child.get("job") if isinstance(child.get("job"), dict) else {}
        strategy = job.get("strategy") if isinstance(job.get("strategy"), dict) else {}
        if isinstance(strategy, dict) and strategy:
            return strategy
    return {}


def _build_job_favorite_snapshot(job_id: str) -> Optional[Dict[str, Any]]:
    job_id = _safe_job_id(job_id)
    located = find_job_dir(job_id)
    if not located:
        return None
    status, jdir = located
    summary = read_job_summary(job_id) or {}
    full = read_job_full(job_id) or {}
    artifacts = _artifact_manifest_for_dir(jdir)
    strategy = (summary.get("strategy_name") or summary.get("class_name")
                or ((full.get("job") or {}).get("strategy") or {}).get("class_name") or "")
    source_hash = _json_sha256({
        "kind": "job",
        "id": job_id,
        "status": status,
        "artifacts": artifacts,
    })
    return {
        "kind": "job",
        "id": job_id,
        "report_no": full.get("report_no") or summary.get("report_no"),
        "label": summary.get("instrument") or job_id,
        "strategy": strategy,
        "instrument": summary.get("instrument"),
        "timeframe": summary.get("timeframe"),
        "period": summary.get("period"),
        "status": summary.get("status") or status,
        "summary": summary,
        "full": full,
        "artifact_manifest": artifacts,
        "source_hash": source_hash,
    }


def _build_batch_favorite_snapshot(batch_id: str) -> Optional[Dict[str, Any]]:
    batch_id = _safe_batch_id(batch_id)
    bdir = _safe_child_path(batches_dir(), batch_id, "batch_id")
    if not bdir.is_dir():
        return None
    batch = read_batch_results(batch_id)
    if not batch:
        return None
    artifacts = _artifact_manifest_for_dir(bdir)
    children_full: List[Dict[str, Any]] = []
    child_artifacts: Dict[str, Any] = {}
    manifest = read_batch(batch_id) or {}
    for child in manifest.get("children") or []:
        if not isinstance(child, dict):
            continue
        jid = child.get("job_id")
        if not jid:
            continue
        full = read_job_full(jid)
        if full:
            children_full.append(full)
        located = find_job_dir(jid)
        if located:
            _status, jdir = located
            child_artifacts[jid] = _artifact_manifest_for_dir(jdir)
    insts = []
    for row in batch.get("rows") or []:
        inst = row.get("instrument") if isinstance(row, dict) else None
        if inst and inst not in insts:
            insts.append(inst)
    source_hash = _json_sha256({
        "kind": "batch",
        "id": batch_id,
        "batch_artifacts": artifacts,
        "child_artifacts": child_artifacts,
    })
    return {
        "kind": "batch",
        "id": batch_id,
        "report_no": batch.get("report_no"),
        "label": ", ".join(insts[:3]) + (f" +{len(insts) - 3}" if len(insts) > 3 else "") if insts else batch.get("name") or batch_id,
        "strategy": (batch.get("strategy") or {}).get("class_name"),
        "instrument": insts[0] if len(insts) == 1 else None,
        "instruments": insts,
        "timeframe": batch.get("timeframe"),
        "period": batch.get("period"),
        "status": None,
        "batch": batch,
        "children_full": children_full,
        "artifact_manifest": artifacts,
        "child_artifact_manifest": child_artifacts,
        "source_hash": source_hash,
    }


def _build_report_favorite_snapshot(kind: str, report_id: str) -> Optional[Dict[str, Any]]:
    kind, report_id = _normalize_report_ref(kind, report_id)
    if kind == "job":
        return _build_job_favorite_snapshot(report_id)
    return _build_batch_favorite_snapshot(report_id)


def _validate_report_favorite(entry: Dict[str, Any],
                              current: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    kind = str(entry.get("kind") or "").strip().lower()
    rid = str(entry.get("id") or "").strip()
    checked_at = utcnow_iso()
    if current is None:
        try:
            current = _build_report_favorite_snapshot(kind, rid)
        except JobValidationError:
            current = None
    saved_hash = entry.get("source_hash") or ((entry.get("snapshot") or {}).get("source_hash"))
    current_hash = current.get("source_hash") if isinstance(current, dict) else None
    report_exists = current is not None
    report_unchanged = bool(report_exists and saved_hash and current_hash == saved_hash)
    snapshot = current or (entry.get("snapshot") if isinstance(entry.get("snapshot"), dict) else {})
    strategy_doc = _snapshot_strategy_doc(snapshot)
    strategy_class = str(strategy_doc.get("class_name") or "").strip()
    params = strategy_doc.get("parameters") if isinstance(strategy_doc.get("parameters"), dict) else {}
    strategy_exists = False
    parameter_names: set[str] = set()
    unknown_params: List[str] = []
    if strategy_class:
        strategy_exists = strategy_class in set(whitelisted_strategies())
        try:
            parameter_names = _strategy_parameter_names(strategy_class)
        except Exception:
            parameter_names = set()
        if parameter_names:
            unknown_params = sorted(k for k in params.keys() if k not in parameter_names)
    parameters_match_catalog: Optional[bool]
    if not strategy_class or not parameter_names:
        parameters_match_catalog = None
    else:
        parameters_match_catalog = not unknown_params
    if not report_exists:
        status = "missing"
    elif not report_unchanged:
        status = "stale"
    elif strategy_class and not strategy_exists:
        status = "strategy_missing"
    elif parameters_match_catalog is False:
        status = "params_mismatch"
    else:
        status = "ok"
    return {
        "status": status,
        "checked_at_utc": checked_at,
        "report_exists": report_exists,
        "report_unchanged": report_unchanged,
        "saved_source_hash": saved_hash,
        "current_source_hash": current_hash,
        "strategy_class": strategy_class,
        "strategy_exists": strategy_exists if strategy_class else None,
        "parameters_match_catalog": parameters_match_catalog,
        "unknown_parameters": unknown_params,
        "validated_against_strategy_analyzer": VALIDATED_AGAINST_STRATEGY_ANALYZER,
    }


def _public_report_favorite(entry: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(entry)
    out.pop("snapshot", None)
    out.pop("source_hash", None)
    return out


def _ensure_report_favorite_allowed(kind: str, snapshot: Dict[str, Any]) -> None:
    if kind != "batch":
        return
    raise JobValidationError(
        "Пакетный отчёт нельзя добавлять в избранное. "
        "Выберите конкретный запуск в нижней таблице."
    )


def favorite_report(kind: str, report_id: str, description: Optional[str] = None) -> Dict[str, Any]:
    kind, report_id = _normalize_report_ref(kind, report_id)
    snapshot = _build_report_favorite_snapshot(kind, report_id)
    if not snapshot:
        raise JobValidationError(f"report not found: {kind}:{report_id}")
    _ensure_report_favorite_allowed(kind, snapshot)
    data = _read_report_favorites_raw()
    favorites = data.setdefault("favorites", {})
    key = _report_key(kind, report_id)
    existing = favorites.get(key) if isinstance(favorites.get(key), dict) else {}
    now = utcnow_iso()
    entry = dict(existing)
    entry.update({
        "key": key,
        "kind": kind,
        "id": report_id,
        "report_no": snapshot.get("report_no"),
        "label": snapshot.get("label"),
        "strategy": snapshot.get("strategy"),
        "instrument": snapshot.get("instrument"),
        "instruments": snapshot.get("instruments") or [],
        "timeframe": snapshot.get("timeframe"),
        "period": snapshot.get("period"),
        "snapshot": snapshot,
        "source_hash": snapshot.get("source_hash"),
        "updated_at_utc": now,
    })
    entry.setdefault("starred_at_utc", now)
    if description is not None:
        entry["description"] = str(description or "").strip()
    else:
        entry.setdefault("description", "")
    entry["validation"] = _validate_report_favorite(entry, current=snapshot)
    favorites[key] = entry
    data["schema_version"] = "1.0"
    _write_report_favorites(data)
    return {"ok": True, "favorite": _public_report_favorite(entry)}


def update_report_favorite(kind: str, report_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
    kind, report_id = _normalize_report_ref(kind, report_id)
    data = _read_report_favorites_raw()
    favorites = data.setdefault("favorites", {})
    key = _report_key(kind, report_id)
    entry = favorites.get(key)
    if not isinstance(entry, dict):
        raise JobValidationError(f"favorite not found: {key}")
    if "description" in (updates or {}):
        entry["description"] = str((updates or {}).get("description") or "").strip()
    entry["updated_at_utc"] = utcnow_iso()
    entry["validation"] = _validate_report_favorite(entry)
    favorites[key] = entry
    _write_report_favorites(data)
    return {"ok": True, "favorite": _public_report_favorite(entry)}


def unfavorite_report(kind: str, report_id: str) -> Dict[str, Any]:
    kind, report_id = _normalize_report_ref(kind, report_id)
    data = _read_report_favorites_raw()
    favorites = data.setdefault("favorites", {})
    key = _report_key(kind, report_id)
    removed = favorites.pop(key, None) is not None
    if removed:
        _write_report_favorites(data)
    return {"ok": True, "removed": removed, "key": key}


def read_report_favorites(validate: bool = False, *, workspace_id: str = "",
                          user_id: Any = "", allow_legacy: bool = False) -> Dict[str, Any]:
    data = _read_report_favorites_raw()
    out: List[Dict[str, Any]] = []
    changed = False
    for key, entry in (data.get("favorites") or {}).items():
        if not isinstance(entry, dict):
            continue
        kind = str(entry.get("kind") or "").strip().lower()
        rid = str(entry.get("id") or "").strip()
        if kind not in {"job", "batch"} or not rid:
            continue
        if (workspace_id or user_id) and not report_in_scope(
                kind, rid, workspace_id=workspace_id, user_id=user_id,
                allow_legacy=allow_legacy):
            continue
        item = dict(entry)
        item["key"] = key
        if validate:
            item["validation"] = _validate_report_favorite(item)
            if item.get("validation") != entry.get("validation"):
                changed = True
            entry["validation"] = item.get("validation")
            entry["updated_at_utc"] = utcnow_iso()
        else:
            item["validation"] = entry.get("validation") or {}
        out.append(_public_report_favorite(item))
    if validate and changed:
        _write_report_favorites(data)
    out.sort(key=lambda x: str(x.get("starred_at_utc") or ""), reverse=True)
    return {"schema_version": "1.0", "favorites": out}


def _favorite_timeframe_parts(doc: Dict[str, Any]) -> Tuple[str, int]:
    timeframe = doc.get("timeframe") if isinstance(doc.get("timeframe"), dict) else {}
    bars_period_type = str(timeframe.get("bars_period_type") or "Minute")
    raw_value = timeframe.get("value")
    if raw_value is None:
        raw_value = timeframe.get("bars_period_value")
    try:
        bars_period_value = int(raw_value or 1)
    except (TypeError, ValueError):
        raise JobValidationError("favorite snapshot has invalid timeframe value")
    return bars_period_type, bars_period_value


def repeat_report_favorite(kind: str, report_id: str, *,
                           origin_override: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    kind, report_id = _normalize_report_ref(kind, report_id)
    data = _read_report_favorites_raw()
    favorites = data.setdefault("favorites", {})
    key = _report_key(kind, report_id)
    entry = favorites.get(key)
    if not isinstance(entry, dict):
        raise JobValidationError(f"favorite not found: {key}")
    snapshot = entry.get("snapshot") if isinstance(entry.get("snapshot"), dict) else {}

    if kind == "batch":
        batch = snapshot.get("batch") if isinstance(snapshot.get("batch"), dict) else {}
        strategy = batch.get("strategy") if isinstance(batch.get("strategy"), dict) else {}
        execution = batch.get("execution") if isinstance(batch.get("execution"), dict) else {}
        risk_profile = batch.get("risk_profile") if isinstance(batch.get("risk_profile"), dict) else {}
        period = batch.get("period") if isinstance(batch.get("period"), dict) else {}
        bars_period_type, bars_period_value = _favorite_timeframe_parts(batch)
        instruments: List[str] = []
        for inst in entry.get("instruments") or snapshot.get("instruments") or []:
            name = str(inst or "").strip()
            if name and name not in instruments:
                instruments.append(name)
        if not instruments:
            for row in batch.get("rows") or []:
                if not isinstance(row, dict):
                    continue
                name = str(row.get("instrument") or "").strip()
                if name and name not in instruments:
                    instruments.append(name)
        class_name = str(strategy.get("class_name") or entry.get("strategy") or "").strip()
        if not class_name:
            raise JobValidationError("favorite snapshot is missing strategy class")
        if not instruments:
            raise JobValidationError("favorite snapshot is missing instruments")
        req = CreateBatchRequest(
            class_name=class_name,
            instruments=instruments,
            bars_period_type=bars_period_type,
            bars_period_value=bars_period_value,
            from_utc=str(period.get("from_utc") or ""),
            to_utc=str(period.get("to_utc") or ""),
            parameters=dict(strategy.get("parameters") or {}),
            risk_profile=dict(risk_profile or {}),
            calculate=str(execution.get("calculate") or "OnBarClose"),
            is_tick_replay=bool(execution.get("is_tick_replay") or False),
            order_fill_resolution=str(execution.get("order_fill_resolution") or "High"),
            slippage_ticks=int(execution.get("slippage_ticks") or 1),
            commission=float(execution.get("commission") or 0.0),
            commission_template=str(execution.get("commission_template") or "None"),
            session_template=str(execution.get("session_template") or "CME US Index Futures RTH"),
            timezone=str(execution.get("timezone") or "UTC"),
            name=(str(batch.get("name")) if batch.get("name") else None),
            role=str(execution.get("role") or "research"),
            origin=dict(origin_override or batch.get("origin") or {}),
        )
        batch_id, job_ids = create_batch(req)
        return {
            "ok": True,
            "kind": "batch",
            "batch_id": batch_id,
            "job_ids": job_ids,
            "total": len(job_ids),
            "source_favorite": key,
        }

    full = snapshot.get("full") if isinstance(snapshot.get("full"), dict) else {}
    job = full.get("job") if isinstance(full.get("job"), dict) else {}
    strategy = job.get("strategy") if isinstance(job.get("strategy"), dict) else {}
    execution = job.get("execution") if isinstance(job.get("execution"), dict) else {}
    risk_profile = job.get("risk_profile") if isinstance(job.get("risk_profile"), dict) else {}
    period = job.get("period") if isinstance(job.get("period"), dict) else {}
    bars_period_type, bars_period_value = _favorite_timeframe_parts(job)
    class_name = str(strategy.get("class_name") or entry.get("strategy") or "").strip()
    instrument = str(job.get("instrument") or entry.get("instrument") or "").strip()
    if not class_name:
        raise JobValidationError("favorite snapshot is missing strategy class")
    if not instrument:
        raise JobValidationError("favorite snapshot is missing instrument")
    req = CreateJobRequest(
        class_name=class_name,
        instrument=instrument,
        bars_period_type=bars_period_type,
        bars_period_value=bars_period_value,
        from_utc=str(period.get("from_utc") or ""),
        to_utc=str(period.get("to_utc") or ""),
        parameters=dict(strategy.get("parameters") or {}),
        risk_profile=dict(risk_profile or {}),
        calculate=str(execution.get("calculate") or "OnBarClose"),
        is_tick_replay=bool(execution.get("is_tick_replay") or False),
        order_fill_resolution=str(execution.get("order_fill_resolution") or "High"),
        slippage_ticks=int(execution.get("slippage_ticks") or 1),
        commission=float(execution.get("commission") or 0.0),
        commission_template=str(execution.get("commission_template") or "None"),
        session_template=str(execution.get("session_template") or "CME US Index Futures RTH"),
        timezone=str(execution.get("timezone") or "UTC"),
        role=str(execution.get("role") or "research"),
        job_id=None,
        origin=dict(origin_override or job.get("origin") or {}),
    )
    job_id, path = create_job(req)
    return {
        "ok": True,
        "kind": "job",
        "job_id": job_id,
        "path": str(path),
        "source_favorite": key,
    }


def _read_report_numbers() -> Dict[str, Any]:
    p = report_numbers_file()
    if not p.is_file():
        return {"schema_version": "1.0", "next_number": 1, "reports": {}}
    try:
        with open(p, "r", encoding="utf-8-sig") as fh:
            data = json.load(fh)
        if isinstance(data, dict) and isinstance(data.get("reports"), dict):
            try:
                data["next_number"] = int(data.get("next_number") or 1)
            except (TypeError, ValueError):
                data["next_number"] = 1
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return {"schema_version": "1.0", "next_number": 1, "reports": {}}


def _write_report_numbers(data: Dict[str, Any]) -> None:
    global _REPORT_NUMBERS_FILE_SIG
    p = report_numbers_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    os.replace(tmp, p)
    _REPORT_NUMBERS_FILE_SIG = None


def _report_numbers_mapping_from_data(data: Dict[str, Any]) -> Dict[str, int]:
    reports = data.get("reports") if isinstance(data, dict) else {}
    if not isinstance(reports, dict):
        return {}
    out: Dict[str, int] = {}
    for key, entry in reports.items():
        try:
            number = int(entry.get("number") if isinstance(entry, dict) else entry)
        except (TypeError, ValueError):
            continue
        out[str(key)] = number
    return out


def _read_report_numbers_mapping_cached() -> Dict[str, int]:
    """Read the existing report-number index without scanning every job folder."""
    global _REPORT_NUMBERS_FILE_SIG, _REPORT_NUMBERS_VALUE
    p = report_numbers_file()
    sig = _file_cache_sig(p)
    if sig is not None and _REPORT_NUMBERS_FILE_SIG == sig and _REPORT_NUMBERS_VALUE:
        return _REPORT_NUMBERS_VALUE
    mapping = _report_numbers_mapping_from_data(_read_report_numbers())
    _REPORT_NUMBERS_FILE_SIG = sig
    _REPORT_NUMBERS_VALUE = mapping
    return mapping


def _ensure_report_number(kind: str, report_id: str, created_at_utc: Optional[str] = None) -> None:
    """Assign a report number incrementally for newly-created UI reports.

    Full compaction is intentionally kept out of hot read paths; ordinary
    /api/reports calls must not rescan thousands of job folders.
    """
    global _REPORT_NUMBERS_VALUE, _REPORT_NUMBERS_FP, _REPORT_NUMBERS_FILE_SIG
    if kind not in {"job", "batch"}:
        return
    data = _read_report_numbers()
    reports = data.setdefault("reports", {})
    key = _report_key(kind, report_id)
    if isinstance(reports.get(key), dict) and isinstance(reports[key].get("number"), int):
        return
    mapping = _report_numbers_mapping_from_data(data)
    try:
        next_number = int(data.get("next_number") or 1)
    except (TypeError, ValueError):
        next_number = 1
    if mapping:
        next_number = max(next_number, max(mapping.values()) + 1)
    now = utcnow_iso()
    reports[key] = {
        "number": next_number,
        "kind": kind,
        "id": report_id,
        "created_at_utc": created_at_utc,
        "assigned_at_utc": now,
    }
    data["schema_version"] = "1.0"
    data["next_number"] = next_number + 1
    _write_report_numbers(data)
    _REPORT_NUMBERS_VALUE = _report_numbers_mapping_from_data(data)
    _REPORT_NUMBERS_FILE_SIG = _file_cache_sig(report_numbers_file())
    _REPORT_NUMBERS_FP = None


def _report_sort_time(created_at: Optional[str], fallback_mtime: float) -> float:
    if created_at:
        try:
            return datetime.fromisoformat(str(created_at).replace("Z", "+00:00")).timestamp()
        except ValueError:
            pass
    return float(fallback_mtime or 0.0)


def _collect_report_number_candidates() -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []
    for sub in QUEUE_SUBDIRS:
        d = jobs_dir() / sub
        if not d.is_dir():
            continue
        for child in d.iterdir():
            if not child.is_dir() or child.name.startswith("."):
                continue
            job = _read_json_safe(child / "job.json") or {}
            if job.get("batch"):
                continue
            try:
                mtime = child.stat().st_mtime
            except OSError:
                mtime = 0.0
            candidates.append({
                "key": _report_key("job", child.name),
                "kind": "job",
                "id": child.name,
                "created_at_utc": job.get("created_at_utc"),
                "sort_time": _report_sort_time(job.get("created_at_utc"), mtime),
            })
    bdir = batches_dir()
    if bdir.is_dir():
        for child in bdir.iterdir():
            if not child.is_dir() or child.name.startswith("."):
                continue
            meta = _read_json_safe(child / "batch.json") or {}
            try:
                mtime = child.stat().st_mtime
            except OSError:
                mtime = 0.0
            candidates.append({
                "key": _report_key("batch", child.name),
                "kind": "batch",
                "id": child.name,
                "created_at_utc": meta.get("created_at_utc"),
                "sort_time": _report_sort_time(meta.get("created_at_utc"), mtime),
            })
    candidates.sort(key=lambda x: (x.get("sort_time") or 0.0, x.get("key") or ""))
    return candidates


def sync_report_numbers() -> Dict[str, int]:
    data = _read_report_numbers()
    reports = data.setdefault("reports", {})
    candidates = _collect_report_number_candidates()
    candidate_keys = [str(c.get("key") or "") for c in candidates]
    candidate_key_set = set(candidate_keys)

    existing_numbers: Dict[str, int] = {}
    for key, entry in list(reports.items()):
        try:
            num = int(entry.get("number") if isinstance(entry, dict) else entry)
        except (TypeError, ValueError):
            continue
        existing_numbers[str(key)] = num

    visible_numbers = [existing_numbers.get(k) for k in candidate_keys]
    needs_compact = (
        set(reports.keys()) != candidate_key_set
        or any(n is None for n in visible_numbers)
        or len(set(n for n in visible_numbers if n is not None)) != len(candidate_keys)
        or sorted(n for n in visible_numbers if n is not None) != list(range(1, len(candidate_keys) + 1))
    )
    if needs_compact:
        now = utcnow_iso()
        compacted: Dict[str, Any] = {}
        for number, cand in enumerate(candidates, start=1):
            key = cand["key"]
            prev = reports.get(key)
            prev_assigned = prev.get("assigned_at_utc") if isinstance(prev, dict) else None
            compacted[key] = {
                "number": number,
                "kind": cand["kind"],
                "id": cand["id"],
                "created_at_utc": cand.get("created_at_utc"),
                "assigned_at_utc": prev_assigned or now,
            }
        data["reports"] = compacted
        data["next_number"] = len(compacted) + 1
        _write_report_numbers(data)
        return _report_numbers_mapping_from_data(data)

    reports = data.setdefault("reports", {})
    changed = False
    max_seen = 0
    for entry in reports.values():
        try:
            max_seen = max(max_seen, int(entry.get("number") if isinstance(entry, dict) else entry))
        except (TypeError, ValueError):
            continue
    next_number = max(int(data.get("next_number") or 1), max_seen + 1)
    for cand in candidates:
        key = cand["key"]
        entry = reports.get(key)
        if isinstance(entry, dict) and isinstance(entry.get("number"), int):
            continue
        if isinstance(entry, int):
            reports[key] = {"number": entry, "kind": cand["kind"], "id": cand["id"]}
            changed = True
            continue
        reports[key] = {
            "number": next_number,
            "kind": cand["kind"],
            "id": cand["id"],
            "created_at_utc": cand.get("created_at_utc"),
            "assigned_at_utc": utcnow_iso(),
        }
        next_number += 1
        changed = True
    if data.get("next_number") != next_number:
        data["next_number"] = next_number
        changed = True
    data["schema_version"] = "1.0"
    if changed:
        _write_report_numbers(data)
    return _report_numbers_mapping_from_data(data)


def _get_report_numbers_cached() -> Dict[str, int]:
    """Return stable report-number mapping, warming the in-process cache if needed."""
    global _REPORT_NUMBERS_FP, _REPORT_NUMBERS_VALUE
    if not _REPORT_NUMBERS_VALUE:
        _REPORT_NUMBERS_VALUE = _read_report_numbers_mapping_cached()
    if not _REPORT_NUMBERS_VALUE:
        _REPORT_NUMBERS_VALUE = sync_report_numbers()
        # Cheap sentinel; list_jobs/list_batches compute a stronger fingerprint.
        _REPORT_NUMBERS_FP = (0, 0.0)
    return _REPORT_NUMBERS_VALUE


def profiles_dir() -> Path:
    """Directory holding the curated Strategy Profiles registry."""
    return runtime_env.data_path("profiles", project_root=project_root())


def read_strategy_profiles() -> Dict[str, Any]:
    """Return the Strategy Profiles registry in the UI-facing schema.

    Profiles are user-curated "best-of" configurations (strategy + instrument +
    timeframe + locked params + status). The Backtesting page uses them as a
    second left-panel tab; the Trading page will compare live-running NT
    strategies against them to surface parameter drift.
    """
    p = _environment_read_path("profiles", "strategies.json")
    if not p.is_file():
        return {"schema_version": "1.0", "profiles": []}
    try:
        with open(p, "r", encoding="utf-8-sig") as fh:
            data = json.load(fh)
        if isinstance(data, dict) and isinstance(data.get("profiles"), list):
            out = dict(data)
            out["profiles"] = [
                _apply_portfolio_metadata_to_profile(_normalize_strategy_profile_for_ui(x))
                for x in data.get("profiles", [])
                if isinstance(x, dict)
            ]
            return out
    except (OSError, json.JSONDecodeError):
        pass
    return {"schema_version": "1.0", "profiles": []}


def read_strategy_families() -> Dict[str, Any]:
    """Return the root/strategy-family map used to annotate profiles."""
    return strategy_families.read_family_map(project_root())


def read_research_modes() -> Dict[str, Any]:
    """Return the Research Hub Mode registry."""
    path = _environment_read_path("profiles", "research_modes.json")
    try:
        with path.open("r", encoding="utf-8-sig") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    if not isinstance(data.get("modes"), list):
        data["modes"] = []
    data.setdefault("schema_version", "1.0")
    data.setdefault("source", "data/profiles/research_modes.json")
    return data


_PROFILE_STATUS_LABELS: Dict[str, str] = {
    "ready": "Готова",
    "in_progress": "В процессе",
    "paper_ready": "Готово к paper",
    "paper_candidate": "Кандидат",
    "demo_trial": "Испытательный срок demo",
    "research_baseline": "База исследования",
    "rejected": "Отклонено",
    "archived": "Архив",
}

_PROFILE_NAME_CLASS_PREFIXES: Dict[str, str] = {
    "NTAMicroVwapRiskPilot": "VWAP Short",
    "NTAMicroVwapRiskExplorer": "B1 ShortOnly",
    "B1ShortOnlyMGC5mV2": "B1 ShortOnly",
    "VWAPPullbackMGC5mV1": "Scalping Gold",
    "NTAMicroMnqScalpPilot": "Scalping",
    "NTAMnqResearchHub": "Session Edge",
    "NTAMnqSessionEdgeEngineC020": "Session Edge",
    "NTAMnqPostActiveScalpC017": "Scalping Post-Active",
    "NTAMnqDailyOpenScalpC018": "Scalping",
    "NTAMnqMicroOrbOpenScalp": "Scalping",
    "NTAMnqMicroOrbRetestScalpC013": "Scalping Orb Retest",
    "StrategiyaUrovney": "Levels",
}

_PROFILE_NAME_SETUP_MODE_PREFIXES: Dict[str, str] = {
    "VwapPullback": "VWAP Pullback",
    "OrbContinuation": "ORB Continuation",
    "FailedOrbReversal": "Failed ORB Reversal",
    "VwapMeanReversion": "VWAP Mean Reversion",
    "CompressionBreakout": "Compression Breakout",
    "RollingVwapCrypto": "Rolling VWAP Crypto",
}

_PROFILE_NAME_WORDS_RE = re.compile(
    r"^(?P<family>[A-Za-z][A-Za-z0-9]*(?:[ /&-][A-Za-z0-9]+)*) "
    r"(?P<root>[A-Z0-9]+) "
    r"(?P<tf>\d+[mhd]) "
    r"(?P<version>v\d+)"
    r"(?: (?P<cell>c\d{3}))?$"
)
_PROFILE_VERSION_TOKEN_RE = re.compile(r"(?:^|[^A-Za-z0-9_]|_)v\s*(\d+)(?:$|[^A-Za-z0-9_]|_)", re.IGNORECASE)
_INTERNAL_STRATEGY_CATALOG_CLASSES = frozenset({
    "NTAMicroSessionEdgeExplorer",
    "NTAMicroVwapRiskExplorer",
})


def _profile_timeframe_token(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    compact = text.lower().replace(" ", "")
    if re.fullmatch(r"\d+[mhd]", compact):
        return compact
    minute = re.fullmatch(r"(\d+)(?:minute|minutes|min|m)", compact)
    if minute:
        return f"{int(minute.group(1))}m"
    hour = re.fullmatch(r"(\d+)(?:hour|hours|hr|hrs|h)", compact)
    if hour:
        return f"{int(hour.group(1))}h"
    if compact in {"day", "daily", "1day", "1daily", "1d"}:
        return "1d"
    day = re.fullmatch(r"(\d+)(?:day|days|d)", compact)
    if day:
        return f"{int(day.group(1))}d"
    return ""


def _profile_version_token(profile: Dict[str, Any]) -> str:
    candidates: List[Any] = [
        profile.get("name"),
        profile.get("profile_id"),
        profile.get("runtime_strategy_id"),
        profile.get("stable_id"),
        profile.get("deploy_strategy_class"),
        profile.get("strategy_class"),
    ]
    for value in candidates:
        match = _PROFILE_VERSION_TOKEN_RE.search(str(value or ""))
        if match:
            return f"v{int(match.group(1))}"
    return "v1"


def _profile_cell_suffix(profile: Dict[str, Any], root: str) -> str:
    cell_id = str(profile.get("cell_id") or "").strip().upper()
    if not cell_id:
        slot = portfolio_cells.coerce_slot(profile.get("slot"))
        if slot is not None:
            cell_id = portfolio_cells.cell_id_for(root, slot)
    match = portfolio_cells.CELL_ID_PATTERN.match(cell_id)
    return f"c{match.group(1)}" if match else ""


def _clean_profile_family_candidate(text: Any, root: str) -> str:
    out = str(text or "").strip()
    if not out:
        return ""
    out = re.sub(r"\([^)]*\)", " ", out)
    out = re.sub(r"\bc\d{3}\b", " ", out, flags=re.IGNORECASE)
    out = re.sub(r"\bv\s*\d+\b", " ", out, flags=re.IGNORECASE)
    out = re.sub(r"\b\d+\s*(minute|minutes|min|m|hour|hours|hr|hrs|h|day|days|d)\b", " ", out, flags=re.IGNORECASE)
    out = re.sub(
        r"\b(paper_ready|paper_candidate|paper|locked|profile|research|baseline|current-source|stress|variant|rejected|archived|survivor|summary)\b",
        " ",
        out,
        flags=re.IGNORECASE,
    )
    out = out.replace("_", " ").replace("-", " ")
    if root:
        out = re.sub(rf"\b{re.escape(root)}\b", " ", out, flags=re.IGNORECASE)
    out = re.sub(r"\s+", " ", out).strip()
    return out


def _profile_family_prefix(profile: Dict[str, Any]) -> str:
    locked = profile.get("locked_parameters")
    if not isinstance(locked, dict):
        locked = {}
    for key in ("deploy_strategy_class", "strategy_class"):
        cls = str(profile.get(key) or "").strip()
        if cls and cls in _PROFILE_NAME_CLASS_PREFIXES:
            return _PROFILE_NAME_CLASS_PREFIXES[cls]
    for cls in profile.get("runtime_strategy_classes") or []:
        name = str(cls or "").strip()
        if name and name in _PROFILE_NAME_CLASS_PREFIXES:
            return _PROFILE_NAME_CLASS_PREFIXES[name]
    setup_mode = str(locked.get("SetupMode") or profile.get("setup_mode") or "").strip()
    if setup_mode and setup_mode in _PROFILE_NAME_SETUP_MODE_PREFIXES:
        return _PROFILE_NAME_SETUP_MODE_PREFIXES[setup_mode]
    root = portfolio_cells.normalize_root(profile.get("instrument") or profile.get("current_contract"))
    for candidate in (
        profile.get("name"),
        profile.get("display_name"),
        profile.get("runtime_strategy_id"),
        profile.get("stable_id"),
        profile.get("deploy_strategy_class"),
        profile.get("strategy_class"),
    ):
        cleaned = _clean_profile_family_candidate(candidate, root)
        if cleaned:
            return cleaned
    return "Strategy"


def _expected_profile_display_name(profile: Dict[str, Any]) -> str:
    root = portfolio_cells.normalize_root(profile.get("instrument") or profile.get("current_contract"))
    timeframe = _profile_timeframe_token(profile.get("timeframe"))
    version = _profile_version_token(profile)
    family = _profile_family_prefix(profile)
    if not root or not timeframe or not version or not family:
        return ""
    parts = [family, root, timeframe, version]
    cell = _profile_cell_suffix(profile, root)
    if cell:
        parts.append(cell)
    return " ".join(parts)


def _strategy_profiles_path() -> Path:
    return profiles_dir() / "strategies.json"


def _write_json_atomic(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    os.replace(tmp, path)


def _read_strategy_profiles_raw() -> Dict[str, Any]:
    path = _environment_read_path("profiles", "strategies.json")
    if not path.is_file():
        return {"schema_version": "1.1", "profiles": []}
    with open(path, "r", encoding="utf-8-sig") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise JobValidationError("profiles registry must be a JSON object")
    profiles = data.get("profiles")
    if not isinstance(profiles, list):
        data["profiles"] = []
    return data


def update_strategy_profile(profile_id: str,
                            updates: Dict[str, Any],
                            action: str = "update") -> Dict[str, Any]:
    """Mutate one Strategy Profile in data/profiles/strategies.json."""
    pid = str(profile_id or "").strip()
    if not pid:
        raise JobValidationError("profile_id is required")
    data = _read_strategy_profiles_raw()
    profiles = data.get("profiles") or []
    target: Optional[Dict[str, Any]] = None
    for profile in profiles:
        if isinstance(profile, dict) and str(profile.get("profile_id") or profile.get("id") or "") == pid:
            target = profile
            break
    if target is None:
        raise JobValidationError(f"profile not found: {pid}")

    allowed = {"name", "status", "status_label", "notes",
               "lifecycle", "origin", "trial_plan", "demo_plan", "failed_archive"}
    changed: Dict[str, Any] = {}
    for key, value in (updates or {}).items():
        if key not in allowed:
            continue
        if key == "failed_archive":
            if not isinstance(value, dict):
                raise JobValidationError("failed_archive must be an object")
            current = target.get("failed_archive") if isinstance(target.get("failed_archive"), dict) else {}
            current.update(value)
            target["failed_archive"] = current
            changed["failed_archive"] = current
            continue
        if key == "lifecycle":
            value = str(value or "").strip().lower()
            if value not in strategy_lifecycle.LIFECYCLE_SET:
                raise JobValidationError(f"unsupported lifecycle: {value}")
            target["lifecycle"] = value
            target["lifecycle_label"] = strategy_lifecycle.LIFECYCLE_LABELS[value]
            # Keep legacy status in sync so launch gate / coverage still work.
            synced_status = strategy_lifecycle.status_for_lifecycle(value)
            target["status"] = synced_status
            target["status_label"] = _PROFILE_STATUS_LABELS.get(synced_status, synced_status)
            changed["lifecycle"] = value
            changed["status"] = synced_status
            continue
        if key == "origin":
            value = str(value or "").strip().lower()
            if value not in (strategy_lifecycle.ORIGIN_PRODUCTION, strategy_lifecycle.ORIGIN_AI_LAB):
                raise JobValidationError(f"unsupported origin: {value}")
            target["origin"] = value
            changed["origin"] = value
            continue
        if key in ("trial_plan", "demo_plan"):
            if value in (None, {}, ""):
                target.pop(key, None)
                changed[key] = None
                continue
            if not isinstance(value, dict):
                raise JobValidationError(f"{key} must be an object")
            target[key] = value
            changed[key] = value
            continue
        if key == "status":
            value = str(value or "").strip()
            if value not in _PROFILE_STATUS_LABELS:
                raise JobValidationError(f"unsupported profile status: {value}")
            target["status"] = value
            target["status_label"] = _PROFILE_STATUS_LABELS[value]
            changed["status"] = value
            changed["status_label"] = target["status_label"]
            continue
        if key in ("name", "status_label", "notes"):
            value = str(value or "").strip()
            if not value and key == "name":
                raise JobValidationError("profile name cannot be empty")
            if key == "name":
                expected = _expected_profile_display_name(target)
                if expected:
                    if not _PROFILE_NAME_WORDS_RE.fullmatch(value):
                        raise JobValidationError(
                            "display name must use the template "
                            "'<Family> <InstrumentRoot> <TimeframeShort> vN cNNN'"
                        )
                    if value != expected:
                        raise JobValidationError(
                            f"display name for this profile must be exactly: {expected}"
                        )
            target[key] = value
            changed[key] = value

    if not changed:
        raise JobValidationError("no supported profile fields to update")

    archived_now = strategy_lifecycle.classify_lifecycle(target) == strategy_lifecycle.FAILED_ARCHIVED
    target["lifecycle"] = strategy_lifecycle.classify_lifecycle(target)
    target["lifecycle_label"] = strategy_lifecycle.LIFECYCLE_LABELS[target["lifecycle"]]
    if archived_now:
        target["matrix_hidden"] = True
        if not str(target.get("archive_reason") or "").strip():
            note = str((updates or {}).get("notes") or "").strip()
            if note:
                target["archive_reason"] = note
        archive_entry = record_archived_strategy(
            target,
            reason=str(target.get("archive_reason") or ""),
            removal_method=("ai_quarantine"
                            if strategy_lifecycle.is_ai_lab(target)
                            else "production_checklist"),
        )
        fa = target.get("failed_archive") if isinstance(target.get("failed_archive"), dict) else {}
        fa.update({
            "archived_at_utc": target.get("updated_at_utc") or utcnow_iso(),
            "fingerprint": archive_entry["fingerprint"],
            "removal_method": archive_entry["removal_method"],
            "reason": archive_entry["reason"],
            "removed_from_ninjatrader": bool(fa.get("removed_from_ninjatrader", False)),
        })
        target["failed_archive"] = fa
        changed["archived_fingerprint"] = archive_entry["fingerprint"]
    elif ("lifecycle" in changed or "status" in changed) and target.get("matrix_hidden"):
        # Re-activating a profile un-hides it from the portfolio matrix.
        target["matrix_hidden"] = False

    target["updated_at_utc"] = utcnow_iso()
    log = target.get("ui_decisions")
    if not isinstance(log, list):
        log = []
    log.append({
        "at_utc": target["updated_at_utc"],
        "action": str(action or "update"),
        "changes": changed,
    })
    target["ui_decisions"] = log[-20:]
    _write_json_atomic(_strategy_profiles_path(), data)

    cleanup: Optional[Dict[str, Any]] = None
    if archived_now:
        try:
            cleanup = remove_archived_from_ninjatrader(pid)
        except Exception as exc:  # noqa: BLE001
            cleanup = {"ok": False, "error": str(exc), "count": 0, "removed": 0, "results": []}
        refreshed = _read_strategy_profiles_raw().get("profiles") or []
        for profile in refreshed:
            if isinstance(profile, dict) and str(profile.get("profile_id") or profile.get("id") or "") == pid:
                target = profile
                break

    out = {"ok": True, "profile_id": pid, "profile": _normalize_strategy_profile_for_ui(target)}
    if cleanup is not None:
        out["ninjatrader_cleanup"] = cleanup
    return out


def delete_strategy_profile(profile_id: str) -> Dict[str, Any]:
    """Remove one Strategy Profile from the profile registry."""
    pid = str(profile_id or "").strip()
    if not pid:
        raise JobValidationError("profile_id is required")
    data = _read_strategy_profiles_raw()
    profiles = data.get("profiles") or []
    kept = [p for p in profiles if not (isinstance(p, dict) and str(p.get("profile_id") or p.get("id") or "") == pid)]
    if len(kept) == len(profiles):
        raise JobValidationError(f"profile not found: {pid}")
    data["profiles"] = kept
    data["updated_at_utc"] = utcnow_iso()
    _write_json_atomic(_strategy_profiles_path(), data)
    return {"ok": True, "profile_id": pid, "deleted": True}


def _archived_strategies_path() -> Path:
    return profiles_dir() / "archived_strategies.json"


def read_archived_strategies() -> Dict[str, Any]:
    """Do-not-recreate registry: ideas that already failed all trials.

    Keyed by a stable :func:`strategy_lifecycle.archive_fingerprint` so the UI
    can warn when an operator/AI tries to rebuild a previously-failed strategy.
    """
    path = _environment_read_path("profiles", "archived_strategies.json")
    if not path.is_file():
        return {"schema_version": "1.0", "entries": []}
    try:
        with open(path, "r", encoding="utf-8-sig") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {"schema_version": "1.0", "entries": []}
    if not isinstance(data, dict):
        return {"schema_version": "1.0", "entries": []}
    if not isinstance(data.get("entries"), list):
        data["entries"] = []
    data.setdefault("schema_version", "1.0")
    return data


def find_archived_by_fingerprint(fingerprint: str) -> Optional[Dict[str, Any]]:
    fp = str(fingerprint or "").strip()
    if not fp:
        return None
    for entry in read_archived_strategies().get("entries", []):
        if isinstance(entry, dict) and str(entry.get("fingerprint") or "") == fp:
            return entry
    return None


def record_archived_strategy(profile: Dict[str, Any],
                             reason: str = "",
                             failure_codes: Optional[List[str]] = None,
                             removal_method: str = "production_checklist") -> Dict[str, Any]:
    """Append/refresh a do-not-recreate entry for a failed strategy idea."""
    fingerprint = strategy_lifecycle.archive_fingerprint(profile)
    data = read_archived_strategies()
    entries = data.get("entries") or []
    now = utcnow_iso()
    entry = {
        "fingerprint": fingerprint,
        "profile_id": str(profile.get("profile_id") or profile.get("id") or "").strip(),
        "name": str(profile.get("name") or "").strip(),
        "strategy_class": str(profile.get("deploy_strategy_class")
                              or profile.get("strategy_class")
                              or profile.get("strategy") or "").strip(),
        "instrument": str(profile.get("instrument") or profile.get("current_contract") or "").strip(),
        "timeframe": str(profile.get("timeframe") or "").strip(),
        "origin": strategy_lifecycle.detect_origin(profile),
        "reason": str(reason or profile.get("archive_reason") or "").strip(),
        "failure_codes": [str(c).strip() for c in (failure_codes or []) if str(c).strip()],
        "removal_method": removal_method,
        "archived_at_utc": now,
    }
    existing_idx = next(
        (i for i, e in enumerate(entries)
         if isinstance(e, dict) and str(e.get("fingerprint") or "") == fingerprint),
        None,
    )
    if existing_idx is None:
        entries.append(entry)
    else:
        first_seen = entries[existing_idx].get("archived_at_utc") or now
        entry["first_archived_at_utc"] = first_seen
        entries[existing_idx] = entry
    data["entries"] = entries
    data["updated_at_utc"] = now
    _write_json_atomic(_archived_strategies_path(), data)
    return entry


def remove_archived_from_ninjatrader(profile_id: Optional[str] = None) -> Dict[str, Any]:
    """Quarantine the CELL ``.cs`` of failed/archived strategies out of NinjaTrader.

    Pass ``profile_id`` to remove a single archived profile, or omit it to process
    every ``failed_archived`` profile. Updates each profile's ``failed_archive``
    block with the result and persists the registry.
    """
    pid_filter = str(profile_id or "").strip()
    data = _read_strategy_profiles_raw()
    profiles = data.get("profiles") or []
    active_used = ninjatrader_ops.active_class_usage(profiles)
    results: List[Dict[str, Any]] = []
    changed = False
    for profile in profiles:
        if not isinstance(profile, dict):
            continue
        if strategy_lifecycle.classify_lifecycle(profile) != strategy_lifecycle.FAILED_ARCHIVED:
            continue
        pid = str(profile.get("profile_id") or profile.get("id") or "").strip()
        if pid_filter and pid != pid_filter:
            continue
        res = ninjatrader_ops.remove_strategy_from_ninjatrader(profile, active_used)
        fa = profile.get("failed_archive") if isinstance(profile.get("failed_archive"), dict) else {}
        fa["removed_from_ninjatrader"] = bool(res.get("removed"))
        fa["removal"] = {k: res[k] for k in
                         ("class_name", "reason", "source_reason", "source_removed",
                          "ui_state_reason", "ui_state_removed", "ui_nodes_removed",
                          "workspace_entries_removed", "moved_files", "quarantine_dir", "at_utc")
                         if k in res}
        profile["failed_archive"] = fa
        if res.get("removed"):
            profile["removed_from_ninjatrader_at_utc"] = res["at_utc"]
        results.append(res)
        changed = True
    if changed:
        data["updated_at_utc"] = utcnow_iso()
        _write_json_atomic(_strategy_profiles_path(), data)
    removed = sum(1 for r in results if r.get("removed"))
    return {"ok": True, "count": len(results), "removed": removed, "results": results}


def cleanup_ninjatrader_to_approved(dry_run: bool = True,
                                    include_ai_sandbox: bool = True,
                                    include_ref_lib: bool = True) -> Dict[str, Any]:
    """Quarantine every NinjaTrader strategy that is not approved (or its base).

    Leaves only approved (demo/live) strategies plus the engine classes they
    inherit from in the NinjaTrader Custom compile folders. ``dry_run=True``
    previews the plan without moving anything. The repo source tree is preserved.
    """
    data = _read_strategy_profiles_raw()
    profiles = data.get("profiles") or []
    return ninjatrader_ops.cleanup_to_approved(
        profiles,
        include_ai_sandbox=include_ai_sandbox,
        include_ref_lib=include_ref_lib,
        dry_run=dry_run,
    )


def read_instrument_coverage() -> Dict[str, Any]:
    """UI-facing instrument coverage payload.

    Reads the offline-generated `data/profiles/instrument_strategy_coverage.json`
    so the Coverage tab can show which symbols already have a strategy and at
    what readiness level. The file is regenerated by
    `tools/research/python/write_instrument_coverage.py`; we just expose it
    over HTTP without re-deriving here.
    """
    p = _environment_read_path("profiles", "instrument_strategy_coverage.json")
    if not p.is_file():
        return {"schema_version": "1.0", "instruments": [], "summary": {}}
    try:
        with open(p, "r", encoding="utf-8-sig") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            return {"schema_version": "1.0", "instruments": [], "summary": {}}

        profiles_doc = read_strategy_profiles()
        all_profiles = [
            x for x in profiles_doc.get("profiles", [])
            if isinstance(x, dict)
        ]
        # Coverage source files describe the best *individual* strategy and can
        # legitimately say ``ready`` while most portfolio cells are still empty.
        # The UI goal, however, is complete only when every active registry slot
        # has an approved profile.  Read the append-only cell registry directly
        # through project_root() so isolated tests and portable installations use
        # the same source of truth.
        registry_targets: Dict[str, int] = {}
        registry_path = runtime_env.data_path("portfolio", "cells.json", project_root=project_root())
        if registry_path.is_file():
            try:
                registry_doc = json.loads(registry_path.read_text(encoding="utf-8-sig"))
                for cell in registry_doc.get("cells") or []:
                    if not isinstance(cell, dict) or str(cell.get("status") or "active") != "active":
                        continue
                    cell_root = str(cell.get("root") or "").strip().upper()
                    if cell_root:
                        registry_targets[cell_root] = registry_targets.get(cell_root, 0) + 1
            except (OSError, json.JSONDecodeError):
                registry_targets = {}
        catalog_doc = read_strategies_catalog() or {}
        catalog_classes = {
            str(x.get("class_name") or "")
            for x in (catalog_doc.get("strategies") or [])
            if isinstance(x, dict) and x.get("class_name")
        }

        def _root_from_instrument(value: Any) -> str:
            s = str(value or "").strip().upper()
            m = re.match(r"^([A-Z0-9]+)", s)
            return m.group(1) if m else ""

        def _evidence_ids(profile: Dict[str, Any]) -> List[str]:
            ids: List[str] = []
            last = profile.get("last_job_id")
            if last:
                ids.append(str(last))
            for x in profile.get("evidence_job_ids") or []:
                sx = str(x or "")
                if sx and sx not in ids:
                    ids.append(sx)
            return ids

        by_root: Dict[str, List[Dict[str, Any]]] = {}
        for prof in all_profiles:
            root = _root_from_instrument(
                prof.get("instrument") or prof.get("current_contract")
            )
            if root:
                by_root.setdefault(root, []).append(prof)

        def _coverage_status(status: Any) -> str:
            return "ready" if str(status or "") in {"ready", "paper_ready"} else "in_progress"

        status_order = {
            "ready": 0,
            "paper_ready": 0,
            "in_progress": 1,
            "paper_candidate": 1,
            "research_baseline": 2,
            "rejected": 3,
            "archived": 4,
        }
        for profs in by_root.values():
            profs.sort(key=lambda p: (
                status_order.get(str(p.get("status") or ""), 9),
                str(p.get("name") or p.get("profile_id") or ""),
            ))

        def _profile_summary(profile: Dict[str, Any]) -> Dict[str, Any]:
            cls = str(profile.get("strategy_class") or "")
            return {
                "profile_id":       profile.get("profile_id") or "",
                "name":             profile.get("name") or profile.get("profile_id") or "",
                "status":           profile.get("status") or "",
                "strategy_class":   cls,
                "deploy_strategy_class": profile.get("deploy_strategy_class") or "",
                "runtime_strategy_classes": profile.get("runtime_strategy_classes") or [],
                "runtime_strategy_id": profile.get("runtime_strategy_id") or "",
                "instrument":       profile.get("instrument") or "",
                "instrument_root":  profile.get("instrument_root")
                                     or _root_from_instrument(profile.get("instrument") or profile.get("current_contract"))
                                     or "",
                "root_family":      profile.get("root_family") or "",
                "strategy_family":  profile.get("strategy_family") or "",
                "family_status":    profile.get("family_status") or "",
                "family_role":      profile.get("family_role") or "",
                "hub_class":        profile.get("hub_class") or "",
                "new_research_allowed": bool(profile.get("new_research_allowed")),
                "timeframe":        profile.get("timeframe") or "",
                "slot":             profile.get("slot"),
                "cell_id":          profile.get("cell_id") or "",
                "metrics":          profile.get("metrics") or {},
                "test_period":      profile.get("test_period") or profile.get("period") or {},
                "confidence_score": profile.get("confidence_score") or {},
                "demo_plan":        profile.get("demo_plan") or {},
                "last_job_id":      profile.get("last_job_id") or "",
                "evidence_job_ids": _evidence_ids(profile),
                "locked":           bool(profile.get("is_locked") or profile.get("locked")),
                "catalog_available": bool(cls and cls in catalog_classes),
            }

        def _status_counts(profiles: List[Dict[str, Any]]) -> Dict[str, int]:
            counts = {
                "total": len(profiles),
                "ready": 0,
                "in_progress": 0,
                "paper_ready": 0,
                "paper_candidate": 0,
                "research_baseline": 0,
                "rejected": 0,
                "archived": 0,
                "available": 0,
                "approved_available": 0,
            }
            for prof in profiles:
                status = str(prof.get("status") or "")
                coverage_key = _coverage_status(status)
                counts[coverage_key] += 1
                if status in counts and status != coverage_key:
                    counts[status] += 1
                cls = str(prof.get("strategy_class") or "")
                available = bool(cls and cls in catalog_classes)
                if available:
                    counts["available"] += 1
                if available and _coverage_status(status) == "ready":
                    counts["approved_available"] += 1
            return counts

        def _flatten(entry: Dict[str, Any]) -> Dict[str, Any]:
            groups = entry.get("groups") or []
            root = entry.get("root") or ""
            profs = by_root.get(str(root).upper(), [])
            best_id = entry.get("best_profile_id") or ""
            best = next(
                (p for p in profs if str(p.get("profile_id") or "") == str(best_id)),
                profs[0] if profs else None,
            )
            counts = _status_counts(profs)
            ready_count = int(counts.get("ready") or 0)
            target_slots = int(
                registry_targets.get(str(root).upper())
                or entry.get("target_slots")
                or portfolio_cells.TARGET_PORTFOLIO_SLOTS
            )
            goal_ready = bool(target_slots > 0 and ready_count >= target_slots)
            return {
                "root":           root,
                "group":          ", ".join(groups) if groups else "—",
                "strategy_count": counts["total"] if profs else int(entry.get("strategy_count") or 0),
                "ready_count":    ready_count,
                "target_slots":   target_slots,
                "remaining_slots": max(0, target_slots - ready_count),
                "progress_pct":   round(ready_count / target_slots * 100.0, 2) if target_slots else 0.0,
                "best_status":    "ready" if goal_ready else "in_progress",
                "status_label":   "Готово" if goal_ready else "В работе",
                "status_reason":  (
                    f"Все {target_slots} активных слотов имеют одобренный профиль."
                    if goal_ready else
                    f"Одобрено {ready_count} из {target_slots} активных слотов."
                ),
                "profile_name":   (best or {}).get("name") or entry.get("strategy_class") or "",
                "profile_id":     best_id,
                "instrument":     entry.get("current_contract") or "",
                "locked":         bool(entry.get("is_locked")),
                "next_action":    entry.get("next_action") or "",
                "status_counts":   counts,
                "profiles":        [_profile_summary(p) for p in profs],
            }

        rows: List[Dict[str, Any]] = []
        for entry in data.get("micros", []) or []:
            if isinstance(entry, dict):
                rows.append(_flatten(entry))
        for entry in data.get("non_micros_with_profiles", []) or []:
            if isinstance(entry, dict):
                rows.append(_flatten(entry))

        # Sort: ready first, then everything still being worked.
        order = {"ready": 0, "in_progress": 1}
        rows.sort(key=lambda r: (order.get(r["best_status"], 9), r["root"]))

        derived_summary = dict(data.get("summary") or {})
        micro_roots = {
            str(entry.get("root") or "").upper()
            for entry in (data.get("micros") or []) if isinstance(entry, dict)
        }
        micro_rows = [row for row in rows if str(row.get("root") or "").upper() in micro_roots]
        derived_summary.update({
            "ready": sum(1 for row in micro_rows if row.get("best_status") == "ready"),
            "in_progress": sum(1 for row in micro_rows if row.get("best_status") != "ready"),
            "total_micros": len(micro_rows),
            "approved_slots": sum(int(row.get("ready_count") or 0) for row in rows),
            "target_slots": sum(int(row.get("target_slots") or 0) for row in rows),
            "calculation": "approved_profiles_vs_active_portfolio_slots",
        })
        return {
            "schema_version":   data.get("schema_version", "1.0"),
            "generated_at_utc": data.get("generated_at_utc", ""),
            "summary":          derived_summary,
            "instruments":      rows,
        }
    except (OSError, json.JSONDecodeError):
        return {"schema_version": "1.0", "instruments": [], "summary": {}}


def _date_to_utc_midnight(value: Any) -> str:
    s = str(value or "").strip()
    if not s:
        return ""
    if "T" in s:
        return s
    return f"{s}T00:00:00Z"


def _normalize_strategy_profile_for_ui(profile: Dict[str, Any]) -> Dict[str, Any]:
    """Accept legacy and current profile JSON shapes.

    Older profile files stored profiles as id/strategy/parameters/period while
    the UI renders profile_id/strategy_class/locked_parameters/test_period.
    Keep the registry readable across both shapes so a stale or hand-edited
    profile file does not produce blank cards.
    """
    out = dict(profile)
    out = strategy_families.apply_family_metadata(out, project_root())
    if "profile_id" not in out and "id" in out:
        out["profile_id"] = out.get("id")
    if "strategy_class" not in out and "strategy" in out:
        out["strategy_class"] = out.get("strategy")
    if "locked_parameters" not in out and isinstance(out.get("parameters"), dict):
        out["locked_parameters"] = out.get("parameters")
    if "last_job_id" not in out:
        src = out.get("source")
        if isinstance(src, dict) and src.get("best_job_id"):
            out["last_job_id"] = src.get("best_job_id")

    if "test_period" not in out:
        period = out.get("period")
        if isinstance(period, dict):
            out["test_period"] = {
                "from_utc": _date_to_utc_midnight(period.get("from") or period.get("start")),
                "to_utc":   _date_to_utc_midnight(period.get("to") or period.get("end")),
            }

    metrics = out.get("metrics")
    if isinstance(metrics, dict):
        normalized = dict(metrics)
        if "trade_count" not in normalized and "trades" in metrics:
            normalized["trade_count"] = metrics.get("trades")
        if "winning_pct" not in normalized and "win_pct" in metrics:
            normalized["winning_pct"] = metrics.get("win_pct")
        if "net_profit_after_commission" not in normalized and "adj_net" in metrics:
            normalized["net_profit_after_commission"] = metrics.get("adj_net")
        if "profit_factor_after_commission" not in normalized and "adj_pf" in metrics:
            normalized["profit_factor_after_commission"] = metrics.get("adj_pf")
        if "max_drawdown" not in normalized and "adj_max_drawdown" in metrics:
            normalized["max_drawdown"] = metrics.get("adj_max_drawdown")
        out["metrics"] = normalized

    expected_name = _expected_profile_display_name(out)
    out["expected_name"] = expected_name
    if expected_name:
        out["name_matches_policy"] = str(out.get("name") or "").strip() == expected_name

    out = strategy_lifecycle.annotate(out)
    return out


_PORTFOLIO_READY_STATUSES = {"ready", "paper_ready"}


def _portfolio_layout_fingerprint() -> Tuple[int, float]:
    path = _strategy_profiles_path()
    if not path.is_file():
        return (0, 0.0)
    try:
        stat = path.stat()
    except OSError:
        return (0, 0.0)
    return (int(stat.st_size), round(stat.st_mtime, 3))


def _profile_counts_in_portfolio(profile: Dict[str, Any]) -> bool:
    return strategy_lifecycle.classify_lifecycle(profile) in strategy_lifecycle.PORTFOLIO_COUNTED


def _profile_portfolio_root(profile: Dict[str, Any]) -> str:
    return portfolio_cells.normalize_root(
        profile.get("instrument") or profile.get("current_contract")
    )


def _profile_portfolio_family_key(profile: Dict[str, Any]) -> str:
    for key in ("stable_id", "deploy_strategy_class", "strategy_class", "profile_id", "name"):
        value = str(profile.get(key) or "").strip().lower()
        if value:
            return value
    return ""


def _profile_portfolio_aliases(profile: Dict[str, Any]) -> List[str]:
    aliases: List[str] = []
    seen = set()

    def add(value: Any) -> None:
        alias = str(value or "").strip().lower()
        if not alias or alias in seen:
            return
        seen.add(alias)
        aliases.append(alias)

    for key in ("stable_id", "profile_id", "deploy_strategy_class", "strategy_class"):
        add(profile.get(key))
    for value in profile.get("runtime_strategy_classes") or []:
        add(value)
    return aliases


def _profile_portfolio_name(profile: Dict[str, Any]) -> str:
    for key in ("name", "display_name", "profile_id", "stable_id", "deploy_strategy_class", "strategy_class"):
        value = str(profile.get(key) or "").strip()
        if value:
            return value
    return ""


def _profile_explicit_slot(profile: Dict[str, Any], root: str) -> Optional[int]:
    slot = portfolio_cells.coerce_slot(profile.get("slot"))
    if slot is not None:
        return slot
    return portfolio_cells.slot_for_cell_id(profile.get("cell_id"), root)


def _build_portfolio_layout(profiles: List[Dict[str, Any]]) -> Dict[str, Dict[Any, Dict[str, Any]]]:
    families_by_root: Dict[str, Dict[str, Dict[str, Any]]] = {}
    profile_lookup: Dict[str, Dict[str, Any]] = {}
    match_lookup: Dict[Tuple[str, str], Dict[str, Any]] = {}

    for profile in profiles:
        if not isinstance(profile, dict) or not _profile_counts_in_portfolio(profile):
            continue
        root = _profile_portfolio_root(profile)
        family_key = _profile_portfolio_family_key(profile)
        if not root or root not in portfolio_cells.PORTFOLIO_ROOT_INDEX or not family_key:
            continue
        family = families_by_root.setdefault(root, {}).setdefault(family_key, {
            "family_key": family_key,
            "strategy_name": _profile_portfolio_name(profile),
            "aliases": [],
            "profiles": [],
            "explicit_slot": None,
        })
        family["profiles"].append(profile)
        for alias in _profile_portfolio_aliases(profile):
            if alias not in family["aliases"]:
                family["aliases"].append(alias)
        if not family["strategy_name"]:
            family["strategy_name"] = _profile_portfolio_name(profile)
        slot = _profile_explicit_slot(profile, root)
        if slot is not None and family["explicit_slot"] is None:
            family["explicit_slot"] = slot

    for root, families_map in families_by_root.items():
        families = sorted(families_map.values(), key=lambda item: item["family_key"])
        assigned: Dict[str, int] = {}
        used_slots = set()
        explicit_families = sorted(
            [item for item in families if item["explicit_slot"] is not None],
            key=lambda item: (item["explicit_slot"], item["family_key"]),
        )
        for family in explicit_families:
            slot = family["explicit_slot"]
            if slot in used_slots:
                continue
            used_slots.add(slot)
            assigned[family["family_key"]] = slot

        free_slots = [
            slot for slot in range(1, portfolio_cells.TARGET_PORTFOLIO_SLOTS + 1)
            if slot not in used_slots
        ]
        for family in families:
            if family["family_key"] in assigned or not free_slots:
                continue
            assigned[family["family_key"]] = free_slots.pop(0)

        for family in families:
            slot = assigned.get(family["family_key"])
            if slot is None:
                continue
            meta = portfolio_cells.portfolio_metadata(root, slot, family["strategy_name"])
            if not meta:
                continue
            for profile in family["profiles"]:
                profile_id = str(profile.get("profile_id") or profile.get("id") or "").strip()
                if profile_id:
                    profile_lookup[profile_id] = dict(meta)
            for alias in family["aliases"]:
                match_lookup[(root, alias)] = dict(meta)

    return {"profiles": profile_lookup, "lookup": match_lookup}


def _get_portfolio_layout() -> Dict[str, Dict[Any, Dict[str, Any]]]:
    global _PORTFOLIO_LAYOUT_FP, _PORTFOLIO_LAYOUT_VALUE

    fp = _portfolio_layout_fingerprint()
    if fp != _PORTFOLIO_LAYOUT_FP:
        try:
            data = _read_strategy_profiles_raw()
            profiles = [
                _normalize_strategy_profile_for_ui(x)
                for x in (data.get("profiles") or [])
                if isinstance(x, dict)
            ]
        except (JobValidationError, OSError, json.JSONDecodeError):
            profiles = []
        _PORTFOLIO_LAYOUT_VALUE = _build_portfolio_layout(profiles)
        _PORTFOLIO_LAYOUT_FP = fp
    return _PORTFOLIO_LAYOUT_VALUE


def _apply_portfolio_metadata_to_profile(profile: Dict[str, Any]) -> Dict[str, Any]:
    profile_id = str(profile.get("profile_id") or profile.get("id") or "").strip()
    if not profile_id:
        return profile
    meta = _get_portfolio_layout().get("profiles", {}).get(profile_id)
    if not meta:
        return profile
    out = dict(profile)
    out["instrument_root"] = meta.get("instrument") or ""
    out["slot"] = meta.get("slot")
    out["cell_id"] = meta.get("cell_id") or ""
    return out


def _resolve_portfolio_metadata(instrument: Any, *aliases: Any) -> Dict[str, Any]:
    root = portfolio_cells.normalize_root(instrument)
    if not root:
        return {}
    lookup = _get_portfolio_layout().get("lookup", {})
    for alias in aliases:
        key = str(alias or "").strip().lower()
        if not key:
            continue
        meta = lookup.get((root, key))
        if meta:
            return dict(meta)
    return {}


def _job_portfolio_metadata(job: Any) -> Dict[str, Any]:
    if not isinstance(job, dict):
        return {}
    strategy = job.get("strategy") or {}
    existing = job.get("portfolio")
    if isinstance(existing, dict):
        meta = portfolio_cells.portfolio_metadata(
            existing.get("instrument") or job.get("instrument"),
            existing.get("slot"),
            existing.get("strategy_name")
            or existing.get("display_name")
            or strategy.get("display_name")
            or strategy.get("class_name"),
        )
        if meta:
            return meta
    return _resolve_portfolio_metadata(
        job.get("instrument"),
        strategy.get("class_name"),
        strategy.get("display_name"),
        strategy.get("strategy_id"),
        strategy.get("stable_id"),
    )


def _persist_result_portfolio(jdir: Path, result_doc: Any, portfolio: Dict[str, Any]) -> None:
    if not isinstance(result_doc, dict) or not portfolio:
        return
    existing = result_doc.get("portfolio")
    if isinstance(existing, dict):
        existing_cell_id = str(existing.get("cell_id") or "").strip()
        existing_slot = portfolio_cells.coerce_slot(existing.get("slot"))
        if existing_cell_id == str(portfolio.get("cell_id") or "") and existing_slot == portfolio.get("slot"):
            return
    updated = dict(result_doc)
    updated["portfolio"] = dict(portfolio)
    try:
        _write_json_atomic(jdir / "result.json", updated)
    except OSError:
        return
    result_doc.clear()
    result_doc.update(updated)


def _read_catalog_file(name: str) -> Optional[Dict[str, Any]]:
    p = _environment_read_path("catalog", name)
    if not p.is_file():
        return None
    try:
        with open(p, "r", encoding="utf-8-sig") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return None


def read_strategies_catalog() -> Optional[Dict[str, Any]]:
    """Returns parsed data/catalog/strategies.json or None."""
    return _read_catalog_file("strategies.json")


def _merge_instruments_front_months(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Upsert preferred front-month contracts over the bridge catalog.

    Bridge rebuilds instruments.json from db\\minute only, so newly rolled
    contracts can be missing until NT accumulates local bars. The overlay
    file keeps Desktop rollover pointed at the live month across refreshes.
    """
    overlay = _read_catalog_file("instruments_front_months.json") or {}
    extras = overlay.get("contracts")
    if not isinstance(extras, list) or not extras:
        return doc
    instruments = list(doc.get("instruments") or [])
    by_name: Dict[str, Dict[str, Any]] = {}
    for ins in instruments:
        if isinstance(ins, dict):
            name = str(ins.get("instrument") or "")
            if name:
                by_name[name] = ins
    changed = False
    for row in extras:
        if not isinstance(row, dict):
            continue
        name = str(row.get("instrument") or "").strip()
        if not name:
            continue
        existing = by_name.get(name)
        if existing is None:
            instruments.append(dict(row))
            by_name[name] = instruments[-1]
            changed = True
            continue
        # Keep bridge metadata, but never let overlay lose a fresher data_last.
        overlay_last = str(row.get("data_last") or "")
        existing_last = str(existing.get("data_last") or "")
        if overlay_last and overlay_last > existing_last:
            existing["data_last"] = overlay_last
            if row.get("data_first") and not existing.get("data_first"):
                existing["data_first"] = row.get("data_first")
            existing["has_minute_data"] = True
            changed = True
        for key in ("tick_size", "point_value", "tick_value", "currency",
                    "exchange", "instrument_type", "master_instrument",
                    "asset_class", "root", "expiry"):
            if existing.get(key) in (None, "") and row.get(key) not in (None, ""):
                existing[key] = row.get(key)
                changed = True
    if not changed:
        return doc
    instruments.sort(key=lambda c: str((c or {}).get("instrument") or ""))
    out = dict(doc)
    out["instruments"] = instruments
    out["count"] = len(instruments)
    out["front_months_overlay"] = {
        "applied": True,
        "count": len(extras),
        "updated_at_utc": overlay.get("updated_at_utc"),
    }
    return out


def read_instruments_catalog() -> Optional[Dict[str, Any]]:
    """Returns parsed data/catalog/instruments.json (plus front-month overlay)."""
    doc = _read_catalog_file("instruments.json")
    if not isinstance(doc, dict):
        return None
    return _merge_instruments_front_months(doc)


def read_templates_catalog() -> Optional[Dict[str, Any]]:
    """Returns parsed data/catalog/templates.json (commission + trading hours)
    or None.
    """
    return _read_catalog_file("templates.json")


def read_margins_catalog() -> Optional[Dict[str, Any]]:
    """Returns parsed data/catalog/margins.json or None.

    The margin catalog is a manually-seeded broker reference (NinjaTrader
    futures intraday/overnight margins). It is informational only — bridge
    execution and the validated baseline backtest path do not consume it.
    """
    return _read_catalog_file("margins.json")


def read_instrument_groups_catalog() -> Optional[Dict[str, Any]]:
    """Returns parsed data/catalog/instrument_groups.json or None.

    The file holds *root* symbol prefixes ("MES", "6B", ...) per group.
    Resolution against the actual instruments.json catalog happens in
    build_catalog_response so the UI receives concrete contract symbols.
    """
    return _read_catalog_file("instrument_groups.json")


# ---------------------------------------------------------------------------
# Catalog refresh: detect staleness vs NinjaTrader.Custom.dll and trigger
# the bridge to rebuild the catalog without restarting NinjaTrader.
# ---------------------------------------------------------------------------

def commands_dir() -> Path:
    return runtime_env.data_path("commands", project_root=project_root())


def _custom_dll_path() -> Path:
    return ninjatrader_user_dir() / "bin" / "Custom" / "NinjaTrader.Custom.dll"


def _legacy_nt_strategies_dir() -> Path:
    return ninjatrader_user_dir() / "bin" / "Custom" / "Strategies"


def _nt_strategies_dir() -> Path:
    return _legacy_nt_strategies_dir() / "NT-Analyzer_strategies"


def _nt_strategy_search_roots() -> List[Path]:
    roots: List[Path] = []
    for path in (_nt_strategies_dir(), _legacy_nt_strategies_dir()):
        if path not in roots:
            roots.append(path)
    return roots


def _nonempty_file(path: Path) -> bool:
    try:
        return path.is_file() and path.stat().st_size > 0
    except OSError:
        return False


def _resolve_strategy_source_file(class_name: str,
                                  catalog_source_file: Any = None) -> Optional[str]:
    """Resolve the real .cs file from the active NinjaTrader strategy roots.

    The bridge catalog can be stale after folders were archived or after a
    zero-byte root stub existed. Prefer a non-empty catalog path, otherwise
    search NT-Analyzer_strategies first and then the legacy Strategies root
    for still-unmigrated standalone .cs files.
    """
    raw = str(catalog_source_file or "")
    if raw and _nonempty_file(Path(raw)):
        return raw

    safe = str(class_name or "").strip()
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", safe):
        return None
    for base in _nt_strategy_search_roots():
        for candidate in (base / safe / f"{safe}.cs", base / f"{safe}.cs"):
            if _nonempty_file(candidate):
                return str(candidate)
    return None


_NT_STRATEGY_NAME_RE = re.compile(r'^\s*Name\s*=\s*"([^"\r\n]+)"\s*;', re.MULTILINE)


def _resolve_strategy_display_name(source_file: Any,
                                   fallback_display_name: Any,
                                   class_name: Any = None) -> str:
    """Resolve the visible NinjaTrader strategy name from the .cs source.

    NinjaTrader's Strategies window shows the strategy ``Name`` assigned in
    ``State.SetDefaults``. The bridge catalog historically stored ``t.Name``
    (C# class name), which makes the UI disagree with NinjaTrader for classes
    like ``PullbackMNQ5mV2`` -> ``Pullback MNQ 5m v2``.

    Prefer the source-defined ``Name = "..."`` when available, otherwise keep
    the catalog/fallback display name.
    """
    fallback = str(fallback_display_name or class_name or "").strip()
    raw = str(source_file or "").strip()
    if not raw:
        return fallback
    p = Path(raw)
    if not _nonempty_file(p):
        return fallback
    try:
        text = p.read_text(encoding="utf-8-sig", errors="ignore")
    except OSError:
        return fallback
    m = _NT_STRATEGY_NAME_RE.search(text)
    if not m:
        return fallback
    value = str(m.group(1) or "").strip()
    return value or fallback


def _profile_class_candidates(profile: Dict[str, Any]) -> List[str]:
    seen: set[str] = set()
    out: List[str] = []

    def add(value: Any) -> None:
        cls = str(value or "").strip()
        if not cls:
            return
        key = cls.lower()
        if key in seen:
            return
        seen.add(key)
        out.append(cls)

    add(profile.get("deploy_strategy_class"))
    add(profile.get("strategy_class"))
    for value in profile.get("runtime_strategy_classes") or []:
        add(value)
    return out


def _catalog_rejected_classes() -> set[str]:
    """Classes explicitly removed from the working strategy surface.

    The bridge catalog is a technical inventory of compiled NinjaScript classes.
    A decommissioned class can remain in the DLL/source tree for audit history,
    but it must not be offered as a launch/backtest choice from the app.
    """
    path = runtime_env.data_path("ops", "scc_classes.json", project_root=project_root())
    try:
        with path.open("r", encoding="utf-8-sig") as fh:
            doc = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return set()
    rejected = doc.get("rejected") if isinstance(doc, dict) else None
    if not isinstance(rejected, list):
        return set()
    return {str(x or "").strip().lower() for x in rejected if str(x or "").strip()}


def _clone_strategy_parameters(raw: Any) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if not isinstance(raw, list):
        return out
    for item in raw:
        if isinstance(item, dict):
            out.append(dict(item))
    return out


def _visible_catalog_strategies(
    strat_doc: Optional[Dict[str, Any]],
    warnings: Optional[List[str]] = None,
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    if warnings is None:
        warnings = []
    if strat_doc is None:
        return ([{
            "class_name":   name,
            "display_name": name,
            "source_file":  None,
            "parameters":   [],
            "fallback":     True,
        } for name in _FALLBACK_STRATEGIES], None)

    raw_strategies = strat_doc.get("strategies") or []
    generated_at = strat_doc.get("generated_at_utc")
    normalized_by_class: Dict[str, Dict[str, Any]] = {}
    rejected_classes = _catalog_rejected_classes()

    for raw in raw_strategies:
        if not isinstance(raw, dict):
            continue
        cls_name = str(raw.get("class_name") or "").strip()
        if not cls_name:
            continue
        if cls_name.lower() in rejected_classes:
            continue
        sf = _resolve_strategy_source_file(cls_name, raw.get("source_file"))
        if not sf:
            warnings.append(
                f"Стратегия {cls_name} исключена из каталога: "
                "файл .cs удалён/архивирован, но класс ещё в DLL. "
                "Перекомпилируйте скрипты в NinjaTrader (Tools → Compile)."
            )
            continue
        entry = dict(
            raw,
            source_file=sf,
            display_name=_resolve_strategy_display_name(
                sf,
                raw.get("display_name"),
                cls_name,
            ),
        )
        if os.path.basename(sf).startswith("@"):
            entry = dict(entry, is_sample=True)
        normalized_by_class[cls_name.lower()] = entry

    visible: List[Dict[str, Any]] = []
    visible_keys: set[str] = set()
    for entry in normalized_by_class.values():
        cls_name = str(entry.get("class_name") or "").strip()
        if not cls_name or cls_name in _INTERNAL_STRATEGY_CATALOG_CLASSES:
            continue
        key = cls_name.lower()
        if key in visible_keys:
            continue
        visible_keys.add(key)
        visible.append(entry)

    profiles_doc = read_strategy_profiles()
    for raw_profile in profiles_doc.get("profiles") or []:
        if not isinstance(raw_profile, dict):
            continue
        deploy_cls = str(raw_profile.get("deploy_strategy_class") or "").strip()
        if not deploy_cls:
            continue
        deploy_key = deploy_cls.lower()
        if deploy_key in rejected_classes:
            continue
        if deploy_key in visible_keys or deploy_cls in _INTERNAL_STRATEGY_CATALOG_CLASSES:
            continue
        sf = _resolve_strategy_source_file(deploy_cls, None)
        if not sf:
            continue
        donor: Optional[Dict[str, Any]] = None
        for candidate in _profile_class_candidates(raw_profile):
            donor = normalized_by_class.get(candidate.lower())
            if donor:
                break
        entry = {
            "class_name": deploy_cls,
            "display_name": _resolve_strategy_display_name(
                sf,
                raw_profile.get("name") or raw_profile.get("display_name") or deploy_cls,
                deploy_cls,
            ),
            "source_file": sf,
            "parameters": _clone_strategy_parameters((donor or {}).get("parameters")),
            "synthesized_from_profile": True,
        }
        for key in ("description", "category"):
            if donor and donor.get(key):
                entry[key] = donor.get(key)
        visible.append(entry)
        visible_keys.add(deploy_key)

    return visible, generated_at


def _safe_mtime(p: Path) -> Optional[float]:
    try:
        return p.stat().st_mtime if p.is_file() else None
    except OSError:
        return None


def catalog_staleness() -> Dict[str, Any]:
    """Compare strategies.json mtime against NinjaTrader.Custom.dll mtime.

    If the DLL is newer (NinjaScript was recompiled after the bridge built
    the catalog), the catalog is stale and the user should refresh.
    """
    dll = _custom_dll_path()
    cat = _environment_read_path("catalog", "strategies.json")
    dll_mt = _safe_mtime(dll)
    cat_mt = _safe_mtime(cat)
    out: Dict[str, Any] = {
        "stale": False,
        "reason": None,
        "dll_mtime": dll_mt,
        "catalog_mtime": cat_mt,
        "dll_path": str(dll),
    }
    if cat_mt is None:
        out["stale"] = True
        out["reason"] = "catalog_missing"
        return out
    if dll_mt is None:
        return out  # DLL not found — leave catalog as-is, no actionable warning
    # Allow a small fudge factor (5s) for filesystem clock skew.
    if dll_mt - cat_mt > 5.0:
        out["stale"] = True
        out["reason"] = "dll_newer"
    return out


def request_catalog_refresh(timeout_s: float = 25.0) -> Dict[str, Any]:
    """Drop a refresh_catalog.request file the bridge polls for, then wait
    for refresh_catalog.response.

    The 25 s timeout accommodates NinjaTrader cold-startup: the AddOn's
    CatalogRefresher only starts once the assemblies are loaded, which can
    take 15–20 s on first launch. After that, refresh round-trips in ~1–2 s.

    Returns {ok, reason, strategies_count, error, request_id, timed_out}.
    """
    cdir = commands_dir()
    try:
        cdir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return {"ok": False, "reason": "cannot_create_commands_dir", "error": str(e)}

    request_id = uuid.uuid4().hex
    req_path  = cdir / "refresh_catalog.request"
    resp_path = cdir / "refresh_catalog.response"

    # Drop any stale response from a previous (timed-out) call.
    try:
        if resp_path.exists():
            resp_path.unlink()
    except OSError:
        pass

    payload = {
        "schema_version": "0.1",
        "request_id":     request_id,
        "requested_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")[:-4] + "Z",
    }
    try:
        # Write atomically so the bridge never sees a half-written request.
        tmp = req_path.with_suffix(".request.tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, req_path)
    except OSError as e:
        return {"ok": False, "reason": "cannot_write_request", "error": str(e)}

    # Poll for the matching response. The bridge is responsible for deleting
    # the request file after handling it; we delete the response after reading.
    deadline = time.monotonic() + max(0.5, timeout_s)
    while time.monotonic() < deadline:
        time.sleep(0.2)
        if not resp_path.is_file():
            continue
        try:
            with open(resp_path, "r", encoding="utf-8-sig") as fh:
                doc = json.load(fh)
        except (OSError, json.JSONDecodeError):
            continue
        # Tolerate older bridge that doesn't echo request_id back.
        rid = doc.get("request_id")
        if rid and rid != request_id:
            continue
        try: resp_path.unlink()
        except OSError: pass
        return {
            "ok":               bool(doc.get("ok")),
            "reason":           "bridge_responded",
            "request_id":       request_id,
            "strategies_count": int(doc.get("strategies_count") or 0),
            "error":            doc.get("error") or None,
            "responded_at_utc": doc.get("responded_at_utc"),
            "timed_out":        False,
        }

    # Timed out. Clean up our orphan request so the next click starts clean
    # and doesn't get answered by the bridge with our (now stale) request_id.
    request_still_pending = req_path.is_file()
    try:
        if req_path.is_file():
            req_path.unlink()
    except OSError:
        pass

    if request_still_pending:
        # Bridge never picked up the request -> AddOn is not running.
        msg = ("Bridge не отвечает: AddOn ещё не загружен или NinjaTrader не запущен. "
               "Если только что перезапустили NinjaTrader — подождите ~30 секунд и попробуйте ещё раз "
               "(холодный старт NinjaTrader долгий). Если NinjaTrader не открыт — запустите его.")
        reason = "bridge_not_running"
    else:
        # Bridge picked up the request but didn't write a response in time.
        msg = ("Bridge принял запрос, но не успел ответить за {:.0f} секунд. "
               "Попробуйте ещё раз; если повторится — посмотрите Bridge log в Диагностике.").format(timeout_s)
        reason = "bridge_slow"

    return {
        "ok":         False,
        "reason":     reason,
        "request_id": request_id,
        "timed_out":  True,
        "error":      msg,
    }




def _resolve_group_instruments(
    roots: List[str],
    instrument_index: Dict[str, List[Dict[str, Any]]],
) -> Tuple[List[str], List[str]]:
    """Resolve a list of symbol roots (e.g. ['MES','MNQ']) to concrete
    instrument names found in the catalog.

    Returns (all_instruments, current_instruments) where current is the
    front-month contract per root (max data_last among those with minute
    data; falls back to alphabetical first if no data). The UI exposes a
    "Only current contracts" toggle that picks the second list — without
    it Micros (~12 roots × 30 historical expiries) is unusable.
    """
    out_all: List[str] = []
    out_current: List[str] = []
    for root in roots:
        bucket = instrument_index.get(root.upper())
        if not bucket:
            continue
        bucket_sorted = sorted(
            bucket,
            key=lambda r: (
                0 if r.get("has_minute_data") else 1,
                # data_last desc -> use negation via reverse string order
                -(int((r.get("data_last") or "0000-00-00").replace("-", "")) or 0),
                str(r.get("instrument") or ""),
            ),
        )
        # Track the front-month: first row with minute data, else first row.
        front_name: Optional[str] = None
        for r in bucket_sorted:
            name = r.get("instrument")
            if not isinstance(name, str):
                continue
            if name not in out_all:
                out_all.append(name)
            if front_name is None and r.get("has_minute_data"):
                front_name = name
        if front_name is None and bucket_sorted:
            n = bucket_sorted[0].get("instrument")
            if isinstance(n, str):
                front_name = n
        if front_name and front_name not in out_current:
            out_current.append(front_name)
    return out_all, out_current


def whitelisted_strategies() -> List[str]:
    """Return the current strategy whitelist. Sourced from bridge catalog
    when available, otherwise the conservative fallback list. Result is also
    pushed back into module-level WHITELISTED_STRATEGIES so that older
    callers (incl. /api/strategies) see fresh values."""
    cat = read_strategies_catalog()
    names: List[str] = []
    if cat:
        visible, _generated_at = _visible_catalog_strategies(cat, warnings=[])
        for s in visible:
            cls_name = str(s.get("class_name") or "").strip()
            if cls_name:
                names.append(cls_name)
    if not names:
        names = list(_FALLBACK_STRATEGIES)
    # update mutable module-level reference
    WHITELISTED_STRATEGIES[:] = names
    return names


def build_catalog_response(
    device_catalog: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Aggregate response for GET /api/catalog. Combines strategies.json and
    instruments.json (bridge-written) with backend-side defaults and the
    explicit list of current bridge limitations so the UI does not have to
    hardcode anything.
    """
    warnings: List[str] = []

    # Lazy daily auto-refresh of the broker margin catalog. Non-blocking:
    # spawns a background daemon thread if the file is older than ~24h.
    try:
        marginrefresh.maybe_daily_refresh()
    except Exception:  # pragma: no cover — never fail catalog on this
        pass

    strat_doc = read_strategies_catalog()
    instr_doc = read_instruments_catalog()
    tmpl_doc  = read_templates_catalog()
    grp_doc   = read_instrument_groups_catalog()
    marg_doc  = read_margins_catalog()

    stale_info = catalog_staleness()
    if stale_info.get("stale") and stale_info.get("reason") == "dll_newer":
        warnings.append(
            "Каталог стратегий устарел: NinjaTrader.Custom.dll был "
            "перекомпилирован после последнего сканирования. "
            "Нажмите «Обновить каталог»."
        )

    if strat_doc is None:
        warnings.append(
            "strategies.json не найден — bridge ещё не запускался "
            "после старта NinjaTrader; показан резервный список."
        )
    strategies, strategies_generated_at = _visible_catalog_strategies(strat_doc, warnings)

    if instr_doc is None:
        warnings.append(
            "instruments.json не найден — bridge ещё не сканировал базу "
            "NinjaTrader; список инструментов пуст."
        )
        instruments = []
        instruments_generated_at = None
    else:
        instruments = instr_doc.get("instruments") or []
        instruments_generated_at = instr_doc.get("generated_at_utc")

    if tmpl_doc is None:
        warnings.append(
            "templates.json не найден — bridge ещё не сканировал шаблоны "
            "NinjaTrader; доступен только синтетический шаблон «None»."
        )
        commission_templates = [{
            "name": "None", "display": "None / 0 commission",
            "supported": True, "source": "synthetic-fallback",
        }]
        trading_hours_templates = []
        templates_generated_at = None
    else:
        commission_templates    = tmpl_doc.get("commission_templates") or []
        trading_hours_templates = tmpl_doc.get("trading_hours_templates") or []
        templates_generated_at  = tmpl_doc.get("generated_at_utc")
        # Surface any bridge-side notes.
        for n in (tmpl_doc.get("notes") or []):
            warnings.append(f"шаблоны: {n}")
        # If the catalog still contains explicitly-unsupported entries, surface
        # them — but a fully-supported list is silent.
        unsupported_names = [c.get("name") for c in commission_templates
                             if not c.get("supported") and c.get("name") != "None"]
        if unsupported_names:
            warnings.append(
                "Часть шаблонов комиссий не поддерживается bridge: " +
                ", ".join(unsupported_names)
            )

    # On a server the actual StrategyLoader and NinjaTrader templates live on
    # the enrolled Windows device. A signed snapshot is authoritative for that
    # installation; local server files are only a visibly labelled fallback.
    device_status = dict(device_catalog) if isinstance(device_catalog, Mapping) else None
    device_doc = (
        device_status.get("catalog")
        if isinstance(device_status, Mapping)
        and isinstance(device_status.get("catalog"), Mapping)
        else {}
    )
    if device_doc:
        remote_strategies = []
        for raw in device_doc.get("strategies") or []:
            if not isinstance(raw, Mapping) or not str(raw.get("class_name") or "").strip():
                continue
            remote_strategies.append({
                "class_name": str(raw.get("class_name") or ""),
                "display_name": str(raw.get("display_name") or raw.get("class_name") or ""),
                "stable_id": str(raw.get("stable_id") or ""),
                "source_file": None,
                "parameters": [],
                "device_backed": True,
                "parameter_schema_available": False,
            })
        remote_templates = [
            {
                "name": str(raw.get("name") or ""),
                "display": str(raw.get("display") or raw.get("name") or ""),
                "supported": bool(raw.get("supported")),
                "device_backed": True,
            }
            for raw in (device_doc.get("commission_templates") or [])
            if isinstance(raw, Mapping) and str(raw.get("name") or "").strip()
        ]
        strategies = remote_strategies
        commission_templates = remote_templates
        strategies_generated_at = str(device_doc.get("generated_at_utc") or "") or None
        templates_generated_at = strategies_generated_at
        if not device_status.get("fresh"):
            warnings.append(
                "Каталог NinjaTrader показан из последнего device snapshot; "
                f"текущее состояние: {device_status.get('state') or 'stale'}."
            )
        if device_doc.get("truncated"):
            warnings.append("Device catalog ограничен 16 KiB; список был усечён.")
        if not device_doc.get("parameter_schemas_included"):
            warnings.append(
                "Схемы параметров стратегий не переданы в bounded catalog; "
                "доступны реальные strategy IDs без вымышленных полей."
            )
    elif device_status is not None:
        warnings.append(
            "Device catalog ещё не получен; резервный список помечен явно и "
            "не считается каталогом VMNINJA."
        )

    preferred_commission = "NinjaTrader Brokerage Free"
    supported_commissions = {
        str(item.get("name") or "") for item in commission_templates
        if isinstance(item, Mapping) and item.get("supported") is not False
    }
    if preferred_commission not in supported_commissions:
        preferred_commission = "None"

    return {
        "strategies": strategies,
        "instruments": instruments,
        "timeframes": {
            "types": ["Minute", "Second", "Tick", "Day", "Volume"],
            "presets": [
                {"label": "1 Minute",  "type": "Minute", "value": 1},
                {"label": "5 Minute",  "type": "Minute", "value": 5},
                {"label": "15 Minute", "type": "Minute", "value": 15},
                {"label": "60 Minute", "type": "Minute", "value": 60},
            ],
        },
        "commission_templates":    commission_templates,
        "trading_hours_templates": trading_hours_templates,
        "execution_defaults": {
            "calculate":             "OnBarClose",
            "is_tick_replay":        False,
            "order_fill_resolution": "High",
            "slippage_ticks":        1,
            "commission":            0.0,
            "commission_template":   preferred_commission,
            "session_template":      "CME US Index Futures RTH",
            "timezone":              "UTC",
        },
        "supported_features": [
            "strategy_whitelist",
            "ninjascript_property_dynamic_form",
            "minute_data_instrument_scan",
            "period_invariant_check",
        ],
        "unsupported_features": [
            {"key": "trading_hours_template_other",
             "reason": "Bridge currently fixes session_template to CME US Index Futures RTH"},
            {"key": "break_at_eod",       "reason": "Not supported by the current bridge"},
            {"key": "exit_on_session_close", "reason": "Not supported by the current bridge"},
            {"key": "tick_replay",        "reason": "Not exposed by the current bridge (fixed false)"},
            {"key": "include_trade_history_in_backtest", "reason": "Always true in the current bridge"},
        ],
        "generated_at_utc": {
            "strategies":  strategies_generated_at,
            "instruments": instruments_generated_at,
            "templates":   templates_generated_at,
            "instrument_groups": (grp_doc or {}).get("generated_at_utc"),
        },
        "instrument_groups": _build_instrument_groups_block(
            grp_doc, instruments, warnings),
        "margin_catalog": _build_margin_catalog_block(marg_doc, warnings),
        "staleness": stale_info,
        "warnings": warnings,
        "device_catalog": ({
            key: copy.deepcopy(device_status.get(key))
            for key in (
                "present", "fresh", "stale", "state", "age_sec",
                "received_at_utc", "generated_at_utc", "installation_id",
                "connection_id", "workspace_id", "connector_version", "nt_version",
            )
        } if device_status is not None else None),
    }


def _build_margin_catalog_block(
    marg_doc: Optional[Dict[str, Any]],
    warnings: List[str],
) -> Dict[str, Any]:
    """Project margins.json into the /api/catalog response.

    The block is informational; if the file is missing or malformed we
    return an empty catalog and a warning so the UI can still render.
    The block also exposes the auto-refresh status so the UI can show
    last fetch time / errors next to the "Refresh now" button.
    """
    refresh_status = marginrefresh.last_status()
    if refresh_status.get("last_error") and not refresh_status.get("in_progress"):
        warnings.append(
            "Авто-обновление маржи не удалось: "
            f"{refresh_status['last_error']}. "
            "Используется предыдущий снимок margins.json."
        )

    if not isinstance(marg_doc, dict):
        warnings.append(
            "margins.json не найден — UI не сможет рассчитать "
            "доступность инструментов по марже (Account / Risk Profile)."
        )
        return {
            "schema_version": "0.1",
            "broker": "",
            "source": "missing",
            "source_url": "",
            "fetched_at_utc": "",
            "notes": [],
            "symbols": {},
            "warning": "margins_catalog_missing",
            "refresh": refresh_status,
        }

    symbols_in = marg_doc.get("symbols")
    symbols_out: Dict[str, Any] = {}
    if isinstance(symbols_in, dict):
        for root, rec in symbols_in.items():
            if not isinstance(root, str) or not isinstance(rec, dict):
                continue
            symbols_out[root.upper()] = {
                "display_name":       str(rec.get("display_name") or ""),
                "exchange":           str(rec.get("exchange") or ""),
                "intraday_margin":    rec.get("intraday_margin"),
                "initial_margin":     rec.get("initial_margin"),
                "maintenance_margin": rec.get("maintenance_margin"),
            }

    return {
        "schema_version": str(marg_doc.get("schema_version") or "0.1"),
        "broker":         str(marg_doc.get("broker") or ""),
        "source":         str(marg_doc.get("source") or ""),
        "source_url":     str(marg_doc.get("source_url") or ""),
        "fetched_at_utc": str(marg_doc.get("fetched_at_utc") or ""),
        "notes":          [str(n) for n in (marg_doc.get("notes") or [])
                           if isinstance(n, (str, int, float))],
        "symbols":        symbols_out,
        "refresh":        refresh_status,
    }


def _build_instrument_groups_block(
    grp_doc: Optional[Dict[str, Any]],
    instruments: List[Dict[str, Any]],
    warnings: List[str],
) -> Dict[str, Any]:
    """Resolve roots -> contract names against instruments catalog."""
    # Index instruments by root token (the first space-separated word, or the
    # whole symbol for non-futures naming like FOREX 6-letter codes).
    index: Dict[str, List[Dict[str, Any]]] = {}
    for r in instruments:
        name = r.get("instrument")
        if not isinstance(name, str):
            continue
        head = name.split(" ", 1)[0].upper()
        index.setdefault(head, []).append(r)
        # Also index on the full symbol so forex like "EURUSD" matches.
        index.setdefault(name.upper(), []).append(r)
    if not grp_doc or not isinstance(grp_doc.get("groups"), list):
        warnings.append(
            "instrument_groups.json не найден — панель групп скрыта.")
        return {
            "source": "missing",
            "warning": "instrument_groups.json missing",
            "groups": [],
        }
    src = grp_doc.get("source") or "fallback"
    out_groups: List[Dict[str, Any]] = []
    for g in grp_doc["groups"]:
        if not isinstance(g, dict):
            continue
        gname = str(g.get("group_name") or "").strip()
        roots = [str(x) for x in (g.get("roots") or [])]
        if not gname:
            continue
        all_inst, current_inst = _resolve_group_instruments(roots, index)
        out_groups.append({
            "group_name":          gname,
            "roots":               roots,
            "instruments":         all_inst,
            "current_instruments": current_inst,
            "count":               len(all_inst),
            "current_count":       len(current_inst),
            "note":                str(g.get("note") or ""),
        })
    if src == "fallback":
        warnings.append(
            "Группы: эвристика, не список NinjaTrader.")
    return {
        "source":  src,
        "warning": grp_doc.get("warning") or "",
        "groups":  out_groups,
    }


# ---------------------------------------------------------------------------
# Job creation
# ---------------------------------------------------------------------------

def _atomic_write_text(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.parent.mkdir(parents=True, exist_ok=True)
    with open(tmp, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)
    os.replace(tmp, path)


def _atomic_write_text_existing_parent(path: Path, text: str) -> None:
    parent = path.parent
    if not parent.is_dir():
        raise FileNotFoundError(str(parent))
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)
    os.replace(tmp, path)


@dataclass
class CreateJobRequest:
    class_name: str
    instrument: str
    bars_period_type: str
    bars_period_value: int
    from_utc: str
    to_utc: str
    parameters: Dict[str, Any]
    risk_profile: Dict[str, Any] = field(default_factory=dict)
    # execution defaults are validated/normalized below
    calculate: str = "OnBarClose"
    is_tick_replay: bool = False
    order_fill_resolution: str = "High"
    slippage_ticks: int = 1
    commission: float = 0.0
    commission_template: str = "None"
    session_template: str = "CME US Index Futures RTH"
    timezone: str = "UTC"
    job_id: Optional[str] = None
    # role gates the research-grade execution validator. Allowed:
    #   "research" (default) — High fill, slip>=1, commission honest.
    #   "smoke" / "debug"     — bypass research-grade checks.
    role: str = "research"
    # Batch membership (set by create_batch). For standalone /api/jobs POST
    # these stay None and the job behaves exactly as before.
    batch_id: Optional[str] = None
    batch_index: Optional[int] = None
    batch_total: Optional[int] = None
    # Optional provenance metadata, written atomically into job.json before
    # pending publication. This avoids post-publish races with the bridge.
    origin: Optional[Dict[str, Any]] = None
    # Server-only device snapshot selected in the authenticated workspace.
    # LOCAL leaves this unset and continues to use its local bridge catalog.
    runtime_catalog: Optional[Dict[str, Any]] = None


class JobValidationError(ValueError):
    pass


_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def _money(v: Any, name: str, min_value: float = 0.0,
           max_value: float = 100_000_000.0) -> float:
    try:
        n = float(v)
    except (TypeError, ValueError):
        raise JobValidationError(f"{name}: numeric value required")
    if not (min_value <= n <= max_value):
        raise JobValidationError(f"{name}: out of range {min_value}..{max_value}")
    return round(n, 2)


_RISK_STATUS_TEXT_INFORMATIONAL = (
    "Risk Profile сохранён в запуске; стратегия пока не ограничивается."
)


def _normalize_risk_profile(profile: Any) -> Dict[str, Any]:
    """Validate and normalize the optional informational account profile.

    Schema v0.1 (margin-catalog era):
        {
          "schema_version": "0.1",
          "mode": "informational",
          "currency": "USD",
          "starting_capital": 2000.0,
          "intraday_only": true,
          "margin_source": {"broker": "...", "source": "...", "fetched_at_utc": "..."},
          "instrument_margins": {
            "MES 06-26": {
              "root": "MES",
              "margin_type": "intraday",
              "margin_per_contract": 50.0,
              "max_contracts_by_capital": 40,
              "status": "allowed" | "blocked" | "unknown"
            }
          },
          "status": "informational_only",
          "status_text": "..."
        }

    The bridge stores this block in `result.context.risk_profile` and does
    NOT consume it for execution. The validated NinjaTrader Strategy Analyzer
    backtest path is unchanged.

    Legacy payloads (margin_per_contract.{intraday,overnight}) from older
    builds are accepted for read-back compatibility but are not required:
    the new UI never sends them.
    """
    if profile in (None, ""):
        return {}
    if not isinstance(profile, dict):
        raise JobValidationError("risk_profile must be an object")

    mode = str(profile.get("mode") or "informational")
    if mode != "informational":
        raise JobValidationError("risk_profile.mode unsupported")

    currency = str(profile.get("currency") or "USD").upper()
    if currency != "USD":
        raise JobValidationError("risk_profile.currency must be USD")

    starting = _money(profile.get("starting_capital", 0),
                      "risk_profile.starting_capital")
    intraday_only = bool(profile.get("intraday_only", True))

    msrc = profile.get("margin_source") or {}
    if not isinstance(msrc, dict):
        raise JobValidationError("risk_profile.margin_source must be an object")
    margin_source = {
        "broker":         str(msrc.get("broker") or ""),
        "source":         str(msrc.get("source") or ""),
        "fetched_at_utc": str(msrc.get("fetched_at_utc") or ""),
    }

    raw_margins = profile.get("instrument_margins") or {}
    if not isinstance(raw_margins, dict):
        raise JobValidationError(
            "risk_profile.instrument_margins must be an object")

    allowed_status = ("allowed", "blocked", "unknown")
    allowed_margin_type = ("intraday", "initial", "maintenance", "unknown")
    instrument_margins: Dict[str, Any] = {}
    for inst, info in raw_margins.items():
        if not isinstance(inst, str) or not isinstance(info, dict):
            continue
        root = str(info.get("root") or inst.split(" ", 1)[0]).upper()
        margin_type = str(info.get("margin_type") or
                          ("intraday" if intraday_only else "initial"))
        if margin_type not in allowed_margin_type:
            margin_type = "unknown"
        margin_val = info.get("margin_per_contract")
        if margin_val is None:
            margin_norm: Optional[float] = None
        else:
            margin_norm = _money(margin_val,
                                 f"risk_profile.instrument_margins[{inst}].margin_per_contract")
        max_c_raw = info.get("max_contracts_by_capital")
        if max_c_raw is None:
            max_c: Optional[int] = None
        else:
            try:
                max_c = max(0, int(max_c_raw))
            except (TypeError, ValueError):
                raise JobValidationError(
                    f"risk_profile.instrument_margins[{inst}].max_contracts_by_capital "
                    "must be an integer or null")
        status = str(info.get("status") or "unknown")
        if status not in allowed_status:
            status = "unknown"
        instrument_margins[inst] = {
            "root":                     root,
            "margin_type":              margin_type,
            "margin_per_contract":      margin_norm,
            "max_contracts_by_capital": max_c,
            "status":                   status,
        }

    return {
        "schema_version":     "0.1",
        "mode":               "informational",
        "currency":           "USD",
        "starting_capital":   starting,
        "intraday_only":      intraday_only,
        "margin_source":      margin_source,
        "instrument_margins": instrument_margins,
        "status":             "informational_only",
        "status_text":        _RISK_STATUS_TEXT_INFORMATIONAL,
    }


# ---------------------------------------------------------------------------
# Risk Profile -> strategy.parameters bridge contract
# ---------------------------------------------------------------------------
# B1 contract: inject risk profile fields into strategies that expose them.
#
# The bridge (StrategyAnalyzerRunner.ApplyStrategyParameters) only injects
# job.strategy.parameters into NinjaScriptProperty fields. The raw
# `risk_profile` block is preserved in result.context but never reaches the
# strategy. To let strategies consume capital / margin / intraday flag, we
# project the normalized Risk Profile into strategy.parameters under a fixed
# whitelist of names. UI-generated zero/unknown placeholders are overwritten
# by the normalized profile; real non-placeholder operator values are kept.
RISK_PROFILE_PARAM_KEYS = (
    "StartingCapital",
    "IntradayOnly",
    "ActiveMarginPerContract",
    "MaxContractsByCapital",
    "InstrumentStatus",
    "MarginSourceBroker",
)


def _research_runtime_defaults() -> Dict[str, Any]:
    return governance.runtime_defaults()


def _research_round_turn_commission() -> float:
    return float(_research_runtime_defaults().get("round_turn_commission", 1.90) or 1.90)


def _research_slippage_floor() -> int:
    return int(_research_runtime_defaults().get("slippage_ticks", 1) or 1)


def _research_fill_resolution() -> str:
    return str(_research_runtime_defaults().get("order_fill_resolution", "High") or "High")

LOCKED_B1_SHORTONLY_PARAMS: Dict[str, Any] = {
    "StartingCapital": 2000.0,
    "IntradayOnly": True,
    "ActiveMarginPerContract": 50.0,
    "MaxContractsByCapital": 40,
    "InstrumentStatus": "allowed",
    "MarginSourceBroker": "NinjaTrader",
    "EnableLong": False,
    "EnableShort": True,
    "UseDailyBiasFilter": False,
    "EmaFastPeriod": 50,
    "EmaSlowPeriod": 200,
    "TradeStartTime": 635,
    "TradeEndTime": 700,
    "MinStopTicks": 12,
    "MaxStopTicks": 12,
    "RewardRiskRatio": 3.5,
    "RiskPerTradePct": 2.0,
    "UserMaxContracts": 5,
    "RoundTurnCommission": 1.90,
    "SlippageTicks": 1,
}


def _strategy_parameter_names(
    class_name: str,
    runtime_catalog: Optional[Mapping[str, Any]] = None,
) -> set[str]:
    """Return tunable NinjaScriptProperty names for class_name from catalog.

    The bridge rejects unknown strategy.parameters. Backend-side injections
    therefore must only add fields the concrete strategy actually exposes.
    """
    if isinstance(runtime_catalog, Mapping):
        cat = runtime_catalog
    else:
        try:
            cat = read_strategies_catalog() or {}
        except Exception:
            cat = {}
    for s in cat.get("strategies") or []:
        if not isinstance(s, dict) or s.get("class_name") != class_name:
            continue
        names: set[str] = set()
        for p in s.get("parameters") or []:
            if isinstance(p, dict) and isinstance(p.get("name"), str):
                names.add(p["name"])
        return names
    return set()


def _effective_round_turn_commission(req: "CreateJobRequest") -> float:
    try:
        rtc = float((req.parameters or {}).get("RoundTurnCommission", 0.0) or 0.0)
    except (TypeError, ValueError):
        rtc = 0.0
    floor = _research_round_turn_commission()
    return rtc if rtc >= floor else floor


def _inject_research_accounting_parameters(req: "CreateJobRequest") -> None:
    """Inject honest accounting params only when the strategy exposes them.

    For older/sample strategies that do not have RoundTurnCommission or
    SlippageTicks properties, we keep those fields out of strategy.parameters
    so the strict NinjaTrader bridge can still run the backtest. The honest
    commission used for UI/report metrics is stored in execution instead.
    """
    if not isinstance(req.parameters, dict):
        req.parameters = {}
    exposed = _strategy_parameter_names(
        req.class_name, getattr(req, "runtime_catalog", None),
    )
    if "RoundTurnCommission" in exposed:
        try:
            cur = float(req.parameters.get("RoundTurnCommission", 0.0) or 0.0)
        except (TypeError, ValueError):
            cur = 0.0
        floor = _research_round_turn_commission()
        if cur < floor:
            req.parameters["RoundTurnCommission"] = floor
    if "SlippageTicks" in exposed:
        try:
            cur = int(req.parameters.get("SlippageTicks", 0) or 0)
        except (TypeError, ValueError):
            cur = 0
        floor = _research_slippage_floor()
        if cur < floor:
            req.parameters["SlippageTicks"] = max(floor, int(req.slippage_ticks))


def _strip_internal_strategy_parameters(req: "CreateJobRequest") -> None:
    """Remove profile-only metadata keys before publishing job parameters.

    Profile records may carry helper fields such as ``_session_template`` that
    document how the profile was selected. The bridge is intentionally strict:
    every key under ``strategy.parameters`` must be an exposed NinjaScript
    property. Internal keys belong in job/execution metadata, not in the
    parameter injection payload.
    """
    if not isinstance(req.parameters, dict):
        req.parameters = {}
        return
    req.parameters = {
        str(k): v
        for k, v in req.parameters.items()
        if not str(k).startswith("_")
    }


def _align_instrument_strategy_parameters(req: "CreateJobRequest") -> None:
    """Keep strategy-exposed instrument fields aligned with the job contract.

    Some deploy wrappers expose `ContractName` / `InstrumentName` as strategy
    parameters and older locked profiles can still point at an expired contract
    (for example `MNQ 06-26`). A job that says `instrument=MNQ 09-26` but passes
    `ContractName=MNQ 06-26` is not a reproducible current-contract rerun.
    """
    if not isinstance(req.parameters, dict):
        req.parameters = {}
        return
    instrument = str(req.instrument or "").strip()
    if not instrument:
        return
    root = instrument.split()[0].upper() if instrument.split() else instrument.upper()
    if "ContractName" in req.parameters:
        req.parameters["ContractName"] = instrument
    if "InstrumentName" in req.parameters:
        req.parameters["InstrumentName"] = root


def _apply_locked_strategy_parameters(req: "CreateJobRequest") -> None:
    """Enforce locked production/paper defaults for approved strategies.

    NTAMicroVwapRiskPilot is locked for smoke/debug queue paths only. Research
    jobs must keep caller/profile parameters so time-window audits and sweeps
    are not silently overwritten; paper runtime still autofills from profiles
    via runtime.submit_command.
    """
    if req.class_name != "NTAMicroVwapRiskPilot":
        return
    if str(req.role or "").strip().lower() == "research":
        return
    if not isinstance(req.parameters, dict):
        req.parameters = {}
    req.parameters.update(LOCKED_B1_SHORTONLY_PARAMS)


def _inject_risk_profile_parameters(req: "CreateJobRequest") -> None:
    """Project req.risk_profile -> req.parameters using RISK_PROFILE_PARAM_KEYS.

    Safe defaults when the instrument is missing from instrument_margins:
        ActiveMarginPerContract = 0.0
        MaxContractsByCapital   = 0
        InstrumentStatus        = "unknown"

    The strategy is responsible for refusing to trade when these are unsafe
    (status != "allowed", margin <= 0, max contracts < 1, capital <= 0).

    When a Risk Profile is present it is authoritative for account/margin
    values. Locked strategy defaults are trading-logic defaults, not a reason
    to keep stale margin assumptions (for example MNQ intraday margin moving
    from $50 to $100).
    """
    rp = req.risk_profile or {}
    if not isinstance(rp, dict) or not rp:
        return
    inst_map = rp.get("instrument_margins") or {}
    inst_info = inst_map.get(req.instrument) if isinstance(inst_map, dict) else None
    if not isinstance(inst_info, dict):
        inst_info = {}

    margin_val = inst_info.get("margin_per_contract")
    max_c      = inst_info.get("max_contracts_by_capital")
    status     = inst_info.get("status") or "unknown"
    broker     = ""
    msrc       = rp.get("margin_source")
    if isinstance(msrc, dict):
        broker = str(msrc.get("broker") or "")

    derived: Dict[str, Any] = {
        "StartingCapital":         float(rp.get("starting_capital") or 0.0),
        "IntradayOnly":            bool(rp.get("intraday_only", True)),
        "ActiveMarginPerContract": float(margin_val) if margin_val is not None else 0.0,
        "MaxContractsByCapital":   int(max_c) if max_c is not None else 0,
        "InstrumentStatus":        str(status),
        "MarginSourceBroker":      str(broker),
    }
    if not isinstance(req.parameters, dict):
        req.parameters = {}
    exposed = _strategy_parameter_names(
        req.class_name, getattr(req, "runtime_catalog", None),
    )
    for k in RISK_PROFILE_PARAM_KEYS:
        if k not in exposed:
            continue
        current = req.parameters.get(k)
        if k in req.parameters and not _risk_profile_param_is_placeholder(k, current):
            continue
        req.parameters[k] = derived[k]


def _risk_profile_param_is_placeholder(key: str, value: Any) -> bool:
    """Return True for empty UI defaults that should not block risk injection."""
    if value is None:
        return True
    if key in ("StartingCapital", "ActiveMarginPerContract"):
        try:
            return float(value) <= 0
        except (TypeError, ValueError):
            return True
    if key == "MaxContractsByCapital":
        try:
            return int(value) <= 0
        except (TypeError, ValueError):
            return True
    if key == "InstrumentStatus":
        return str(value or "").strip().lower() in ("", "unknown", "blocked")
    if key == "MarginSourceBroker":
        return str(value or "").strip() == ""
    return False


def _validate(req: CreateJobRequest) -> None:
    runtime_catalog = getattr(req, "runtime_catalog", None)
    if isinstance(runtime_catalog, Mapping):
        allowed = [
            str(item.get("class_name") or "").strip()
            for item in (runtime_catalog.get("strategies") or [])
            if isinstance(item, Mapping) and str(item.get("class_name") or "").strip()
        ]
    else:
        allowed = whitelisted_strategies()
    if req.class_name not in allowed:
        raise JobValidationError(
            f"strategy '{req.class_name}' is not whitelisted. "
            f"Allowed: {allowed}"
        )
    if not req.instrument or len(req.instrument) > 64:
        raise JobValidationError("instrument: required, max 64 chars")
    if req.bars_period_type not in ("Minute", "Day", "Tick", "Second", "Volume"):
        raise JobValidationError(f"bars_period_type unsupported: {req.bars_period_type}")
    if not (1 <= int(req.bars_period_value) <= 1440):
        raise JobValidationError("bars_period_value out of range 1..1440")
    if not _ISO_RE.match(req.from_utc) or not _ISO_RE.match(req.to_utc):
        raise JobValidationError("from_utc/to_utc must match YYYY-MM-DDTHH:MM:SSZ")
    if req.from_utc >= req.to_utc:
        raise JobValidationError("from_utc must be strictly before to_utc")
    if req.calculate not in ("OnBarClose", "OnEachTick", "OnPriceChange"):
        raise JobValidationError(f"calculate unsupported: {req.calculate}")
    if req.order_fill_resolution not in ("Standard", "High"):
        raise JobValidationError(f"order_fill_resolution unsupported: {req.order_fill_resolution}")
    if not (0 <= int(req.slippage_ticks) <= 100):
        raise JobValidationError("slippage_ticks out of range 0..100")
    # Numeric commission is informational only — bridge does NOT apply a
    # per-trade $ commission, only commission_template. Any non-zero numeric
    # commission would silently produce wrong metrics, so reject it.
    if float(req.commission) != 0.0:
        raise JobValidationError(
            "Числовая комиссия не поддерживается: используйте commission_template. "
            "Поле commission должно быть 0."
        )
    # commission_template: require it to exist in the catalog and be supported.
    # 'None' is always allowed (synthetic 0-commission). Real templates are
    # marked supported=true once bridge can apply them.
    if req.commission_template != "None":
        if isinstance(runtime_catalog, Mapping):
            tmpl_doc = runtime_catalog
        else:
            try:
                tmpl_doc = read_templates_catalog() or {}
            except Exception:
                tmpl_doc = {}
        templates = {t.get("name"): t
                     for t in (tmpl_doc.get("commission_templates") or [])}
        tmpl = templates.get(req.commission_template)
        if tmpl is None:
            raise JobValidationError(
                f"Шаблон комиссии «{req.commission_template}» не найден в каталоге. "
                "Перезапустите bridge, чтобы пересканировать templates/Commission."
            )
        if not tmpl.get("supported"):
            reason = tmpl.get("reason") or "не поддерживается bridge"
            raise JobValidationError(
                f"Шаблон комиссии «{req.commission_template}» найден, но "
                f"bridge пока не умеет его применять: {reason}"
            )
    # session_template: bridge calls TradingHours.Get(name) at runtime and
    # FATAL-fails the job if the name doesn't resolve. Backend used to hard-pin
    # this to "CME US Index Futures RTH"; that broke any non-index micro
    # research (metals/energy/FX/crypto). Now we accept any name that exists in
    # the local templates catalog. Templates marked supported=False are
    # accepted only for role in {"smoke","debug"} until proven by a smoke run.
    try:
        _th_doc = read_templates_catalog() or {}
    except Exception:
        _th_doc = {}
    _th_list = _th_doc.get("trading_hours_templates") or []
    _th_by_name = {t.get("name"): t for t in _th_list if isinstance(t, dict)}
    _requested_th = req.session_template
    if not _th_list:
        # No catalog yet (bridge offline) — fall back to the legacy hard pin.
        if _requested_th != "CME US Index Futures RTH":
            raise JobValidationError(
                "trading_hours catalog empty and session_template != "
                "'CME US Index Futures RTH'. Refresh catalog or use the index template."
            )
    else:
        _th_entry = _th_by_name.get(_requested_th)
        if _th_entry is None:
            raise JobValidationError(
                f"session_template '{_requested_th}' not found in templates catalog. "
                "Run /api/catalog/refresh after copying TradingHours templates."
            )
        # supported=False templates are 'experimental': bridge can still call
        # TradingHours.Get on them, but we have not confirmed end-to-end. Allow
        # only smoke/debug runs to use them until smoke promotes the entry.
        _role_for_th = (getattr(req, "role", "research") or "research").lower()
        if not _th_entry.get("supported") and _role_for_th == "research":
            raise JobValidationError(
                f"session_template '{_requested_th}' is present in catalog but "
                "marked supported=False (not yet smoke-validated). "
                "Run a role='smoke' job first to promote it, then retry as research."
            )
    if req.timezone != "UTC":
        raise JobValidationError("timezone must be 'UTC'")
    if not isinstance(req.parameters, dict):
        raise JobValidationError("parameters must be an object")
    for k, v in req.parameters.items():
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", k):
            raise JobValidationError(f"parameter name not identifier-safe: {k}")
        if not isinstance(v, (int, float, bool, str)):
            raise JobValidationError(f"parameter '{k}': only int/float/bool/string allowed")
    req.risk_profile = _normalize_risk_profile(req.risk_profile)
    if req.job_id is not None:
        _safe_job_id(req.job_id)

    # ------------------------------------------------------------------
    # Research-grade execution gate.
    # Any job tagged role="research" (default) MUST use realistic fill +
    # explicit honest commission. Standard fill / slip=0 / no commission
    # silently inflate edge by 3-5x; this gate prevents that ever again.
    # role="smoke" or "debug" bypasses the gate but is recorded in job.json
    # so post-hoc audits can exclude such runs from any acceptance verdict.
    # ------------------------------------------------------------------
    role = (getattr(req, "role", "research") or "research").lower()
    if role not in ("research", "smoke", "debug"):
        raise JobValidationError(
            f"role must be 'research'|'smoke'|'debug' (got {req.role!r})"
        )
    req.role = role
    if role == "research":
        errs: List[str] = []
        exposed_params = _strategy_parameter_names(req.class_name, runtime_catalog)
        required_fill = _research_fill_resolution()
        if req.order_fill_resolution != required_fill:
            errs.append(
                f"order_fill_resolution must be '{required_fill}' for research jobs "
                f"(got {req.order_fill_resolution!r}). Use role='smoke' to bypass."
            )
        slip_floor = _research_slippage_floor()
        if int(req.slippage_ticks) < slip_floor:
            errs.append(
                f"slippage_ticks must be >={slip_floor} for research jobs "
                f"(got {req.slippage_ticks!r})."
            )
        if req.commission_template != "None":
            # If a real template is set, _validate above already required
            # bridge support. For research we additionally require that
            # commission accounting is honest — currently NT bridge can only
            # post-adjust via parameters.RoundTurnCommission, so template
            # 'None' is the supported research path.
            pass
        if "RoundTurnCommission" in exposed_params:
            rtc = req.parameters.get("RoundTurnCommission")
            try:
                rtc_v = float(rtc) if rtc is not None else None
            except (TypeError, ValueError):
                rtc_v = None
            fee_floor = _research_round_turn_commission()
            if rtc_v is None or rtc_v < fee_floor:
                errs.append(
                    "parameters.RoundTurnCommission must be >="
                    f"{fee_floor:.2f} for research jobs "
                    f"(got {rtc!r}). Micro futures minimum honest round-turn."
                )
        if "SlippageTicks" in exposed_params:
            pst = req.parameters.get("SlippageTicks")
            try:
                pst_v = int(pst) if pst is not None else None
            except (TypeError, ValueError):
                pst_v = None
            if pst_v is None or pst_v < slip_floor:
                errs.append(
                    "parameters.SlippageTicks must be >="
                    f"{slip_floor} for research jobs "
                    f"(got {pst!r}). Must match top-level slippage_ticks."
                )
        if errs:
            raise JobValidationError(
                "research-grade gate failed: " + "; ".join(errs)
            )


def stage2_backtest_requirements(req: "CreateJobRequest") -> Dict[str, Any]:
    """Stage 2 runtime/backtest mismatch repair.

    Record — and warn about — the explicit assumptions a research backtest must
    carry to be honestly comparable against runtime: session template, timezone,
    fill model, slippage, commission and the exact contract. The historical data
    fingerprint itself is produced by the bridge at run time (and now feeds
    run_hash, contract 0.2); here we assert the job demanded it.
    """
    warnings: List[str] = []
    session = str(getattr(req, "session_template", "") or "")
    timezone_name = str(getattr(req, "timezone", "") or "")
    fill = str(getattr(req, "order_fill_resolution", "") or "")
    slip = int(getattr(req, "slippage_ticks", 0) or 0)
    commission_template = str(getattr(req, "commission_template", "") or "")
    instrument = str(getattr(req, "instrument", "") or "")

    if not session:
        warnings.append("session_template is empty; an explicit trading-hours template is required.")
    if not timezone_name:
        warnings.append("timezone is empty; an explicit timezone is required.")
    if fill != "High":
        warnings.append(f"order_fill_resolution={fill!r} is optimistic-unfriendly; runtime fills are real, prefer 'High'.")
    if slip < 2:
        warnings.append(f"slippage_ticks={slip} is optimistic for stop-market scalps; stress at 2-3 ticks.")
    if commission_template in ("", "None"):
        warnings.append("commission is synthetic 0 (commission_template=None); stress real commission >= $2.50 RT.")
    # An exact contract (root + month) is required so a contract roll cannot be
    # silently compared across runs (e.g. MNQ 06-26 backtest vs MNQ SEP26 runtime).
    has_contract_month = bool(re.search(r"\d", instrument)) and len(instrument.split()) > 1
    if not has_contract_month:
        warnings.append(f"instrument={instrument!r} lacks an explicit contract month; record exact contract + rollover policy.")

    return {
        "contract_version": "0.2",
        "session_template": session,
        "timezone": timezone_name,
        "order_fill_resolution": fill,
        "slippage_ticks": slip,
        "commission_template": commission_template,
        "instrument": instrument,
        "requires_runtime_historical_data_fingerprint": True,
        "warnings": warnings,
    }


def create_job(req: CreateJobRequest) -> Tuple[str, Path]:
    """Create a job in pending/. Returns (job_id, pending_job_dir)."""
    _apply_locked_strategy_parameters(req)
    _inject_research_accounting_parameters(req)
    _align_instrument_strategy_parameters(req)
    _strip_internal_strategy_parameters(req)
    # Risk Profile bridge contract (see _inject_risk_profile_parameters):
    # projects normalized risk_profile -> strategy.parameters so the strategy
    # can read capital/margin/intraday/status via [NinjaScriptProperty].
    _inject_risk_profile_parameters(req)
    _validate(req)

    job_id = req.job_id or gen_job_id("ui")
    pending = jobs_dir() / "pending"
    staging_root = pending / ".staging"
    staging_job = _safe_child_path(staging_root, job_id, "job_id")
    pending_job = _safe_child_path(pending, job_id, "job_id")

    if _job_id_exists_anywhere(job_id):
        raise JobValidationError(f"job_id {job_id} already exists")
    if staging_job.exists():
        shutil.rmtree(staging_job)

    staging_job.mkdir(parents=True, exist_ok=True)

    portfolio = _resolve_portfolio_metadata(req.instrument, req.class_name)
    strategy_doc = {
        "class_name": req.class_name,
        "source_file_hint": "",
        "parameters": dict(req.parameters),
    }
    if portfolio:
        strategy_doc["display_name"] = portfolio.get("strategy_name") or req.class_name
        strategy_doc["slot"] = portfolio.get("slot")
        strategy_doc["cell_id"] = portfolio.get("cell_id")

    created_at_utc = utcnow_iso()
    job_doc = {
        "schema_version": "0.1",
        "job_id": job_id,
        "created_at_utc": created_at_utc,
        "kind": "historical_backtest",
        "strategy": strategy_doc,
        "instrument": req.instrument,
        "timeframe": {
            "bars_period_type": req.bars_period_type,
            "value": int(req.bars_period_value),
        },
        "period": {"from_utc": req.from_utc, "to_utc": req.to_utc},
        "risk_profile": dict(req.risk_profile or {}),
        "execution": {
            "calculate": req.calculate,
            "is_tick_replay": bool(req.is_tick_replay),
            "order_fill_resolution": req.order_fill_resolution,
            "slippage_ticks": int(req.slippage_ticks),
            "commission": float(req.commission),
            "commission_template": req.commission_template,
            "session_template": req.session_template,
            "timezone": req.timezone,
            "role": getattr(req, "role", "research"),
            "round_turn_commission": _effective_round_turn_commission(req),
            "stage2_requirements": stage2_backtest_requirements(req),
        },
    }
    if portfolio:
        job_doc["portfolio"] = dict(portfolio)
    if isinstance(getattr(req, "origin", None), dict):
        job_doc["origin"] = dict(req.origin or {})
    if req.batch_id:
        job_doc["batch"] = {
            "batch_id":    req.batch_id,
            "batch_index": int(req.batch_index or 0),
            "batch_total": int(req.batch_total or 0),
        }

    _atomic_write_text(staging_job / "job.json",
                       json.dumps(job_doc, ensure_ascii=False, indent=2))

    # Atomic Directory.Move staging\<id> -> pending\<id>
    os.rename(staging_job, pending_job)
    # try cleanup empty staging
    try:
        if staging_root.exists() and not any(staging_root.iterdir()):
            staging_root.rmdir()
    except OSError:
        pass

    if not req.batch_id:
        _ensure_report_number("job", job_id, created_at_utc)

    _record_job_durable_best_effort(job_id, pending_job, job_doc)

    return job_id, pending_job


def _record_job_durable_best_effort(job_id: str, path: Path,
                                    job_doc: Dict[str, Any],
                                    status: str = "pending") -> None:
    strategy = job_doc.get("strategy") if isinstance(job_doc.get("strategy"), dict) else {}
    timeframe = job_doc.get("timeframe") if isinstance(job_doc.get("timeframe"), dict) else {}
    origin = job_doc.get("origin") if isinstance(job_doc.get("origin"), dict) else {}
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = 0.0
    try:
        durable.record_job(project_root(), {
            "job_id": job_id,
            "workspace_id": origin.get("workspace_id") or job_doc.get("workspace_id") or "",
            "user_id": origin.get("user_id") or job_doc.get("user_id") or "",
            "status": status,
            "kind": job_doc.get("kind") or "",
            "class_name": strategy.get("class_name") or "",
            "instrument": job_doc.get("instrument") or "",
            "timeframe": f"{timeframe.get('value', '')} {timeframe.get('bars_period_type', '')}".strip(),
            "created_at_utc": job_doc.get("created_at_utc") or "",
            "updated_at_utc": job_doc.get("created_at_utc") or "",
            "path": str(path),
            "dir_mtime": mtime,
            "origin": origin,
            "job": job_doc,
        })
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Read-side: list / get / metrics summary
# ---------------------------------------------------------------------------

def _safe_job_id(job_id: str) -> str:
    return _validate_safe_id(job_id, "job_id")


def _job_id_exists_anywhere(job_id: str) -> bool:
    job_id = _safe_job_id(job_id)
    for sub in QUEUE_SUBDIRS:
        if _safe_child_path(jobs_dir() / sub, job_id, "job_id").is_dir():
            return True
    return False


def _is_batch_child_job_dir(jdir: Path) -> bool:
    job = _read_json_safe(jdir / "job.json") or {}
    batch = job.get("batch")
    return isinstance(batch, dict) and bool(batch.get("batch_id"))


def find_job_dir(job_id: str) -> Optional[Tuple[str, Path]]:
    """Return (status, dir) or None."""
    job_id = _safe_job_id(job_id)
    for sub in QUEUE_SUBDIRS:
        p = _safe_child_path(jobs_dir() / sub, job_id, "job_id")
        if p.is_dir():
            return sub, p
    return None


def queue_counts() -> Dict[str, int]:
    out: Dict[str, int] = {}
    for sub in QUEUE_SUBDIRS:
        d = jobs_dir() / sub
        if not d.is_dir():
            out[sub] = 0
            continue
        n = 0
        for child in d.iterdir():
            if child.is_dir() and not child.name.startswith("."):
                n += 1
        out[sub] = n
    return out


def sync_durable_index() -> Dict[str, Any]:
    """Recover/update the SQLite WAL job index from queue directories."""
    return durable.sweep_job_queue(project_root(), jobs_dir(), QUEUE_SUBDIRS)


def _scan_job_location_index() -> Tuple[Tuple[int, float], Dict[str, Tuple[str, Path, float]]]:
    index: Dict[str, Tuple[str, Path, float]] = {}
    fp_count = 0
    fp_sum_mtime = 0.0
    for sub in QUEUE_SUBDIRS:
        d = jobs_dir() / sub
        if not d.is_dir():
            continue
        for child in d.iterdir():
            if not child.is_dir() or child.name.startswith("."):
                continue
            try:
                mtime = child.stat().st_mtime
            except OSError:
                continue
            index[child.name] = (sub, child, mtime)
            fp_count += 1
            fp_sum_mtime += mtime
    return (fp_count, round(fp_sum_mtime, 3)), index


def _get_job_location_index(force_scan: bool = False) -> Tuple[Tuple[int, float], Dict[str, Tuple[str, Path, float]]]:
    global _JOB_LOCATION_FP, _JOB_LOCATION_INDEX
    if not force_scan and _JOB_LOCATION_FP is not None:
        return _JOB_LOCATION_FP, _JOB_LOCATION_INDEX
    fp, index = _scan_job_location_index()
    if _JOB_LOCATION_FP != fp:
        _JOB_LOCATION_FP = fp
        _JOB_LOCATION_INDEX = index
    return _JOB_LOCATION_FP, _JOB_LOCATION_INDEX


def _job_loc_from_index(job_id: Any,
                        loc_index: Optional[Dict[str, Tuple[str, Path, float]]] = None
                        ) -> Optional[Tuple[str, Path]]:
    jid = str(job_id or "")
    if not jid:
        return None
    if loc_index is None:
        _fp, loc_index = _get_job_location_index()
    hit = loc_index.get(jid)
    if not hit:
        return None
    return hit[0], hit[1]


def listable_queue_counts(*, workspace_id: str = "", user_id: Any = "",
                          allow_legacy: bool = False) -> Dict[str, int]:
    out: Dict[str, int] = {}
    report_numbers = _get_report_numbers_cached()
    for sub in QUEUE_SUBDIRS:
        d = jobs_dir() / sub
        if not d.is_dir():
            out[sub] = 0
            continue
        n = 0
        for child in d.iterdir():
            if not child.is_dir() or child.name.startswith("."):
                continue
            if _report_key("job", child.name) not in report_numbers:
                continue
            if (workspace_id or user_id) and not job_in_scope(
                    child.name, workspace_id=workspace_id, user_id=user_id,
                    allow_legacy=allow_legacy):
                continue
            n += 1
        out[sub] = n
    return out


def _indexed_job_rows() -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """Return visible standalone/batch-child job rows plus current report numbers."""
    global _REPORT_NUMBERS_FP, _REPORT_NUMBERS_VALUE

    fp, loc_index = _get_job_location_index(force_scan=True)
    all_rows: List[Dict[str, Any]] = [
        {
            "job_id": jid,
            "status": status,
            "path": str(path),
            "mtime": mtime,
        }
        for jid, (status, path, mtime) in loc_index.items()
    ]
    if fp != _REPORT_NUMBERS_FP:
        # Ordinary report-list reads must stay cheap. Use the persisted
        # report_numbers index; creation paths assign new numbers incrementally.
        _REPORT_NUMBERS_VALUE = _read_report_numbers_mapping_cached()
        if not _REPORT_NUMBERS_VALUE:
            _REPORT_NUMBERS_VALUE = sync_report_numbers()
        _REPORT_NUMBERS_FP = fp
    report_numbers = _REPORT_NUMBERS_VALUE
    rows = [
        r for r in all_rows
        if _report_key("job", r["job_id"]) in report_numbers
    ]
    rows.sort(key=lambda r: r["mtime"], reverse=True)
    return rows, report_numbers


def _build_job_list_row(index_row: Dict[str, Any],
                        report_numbers: Dict[str, int],
                        favorite_keys: set[str]) -> Dict[str, Any]:
    global _JOB_SUMMARY_CACHE_DIRTY
    r = dict(index_row)
    sig = (r["status"], r["mtime"])
    cached = _JOB_SUMMARY_CACHE.get(r["job_id"])
    if cached and cached[0] == sig:
        meta = cached[1]
    else:
        meta = read_job_summary(r["job_id"], include_adjusted=False)
        if meta:
            _JOB_SUMMARY_CACHE[r["job_id"]] = (sig, meta)
            _JOB_SUMMARY_CACHE_DIRTY = True
    if meta:
        r.update(meta)
    if not (r.get("batch") or {}).get("batch_id"):
        r["report_no"] = report_numbers.get(_report_key("job", r["job_id"]))
    r["favorite"] = _report_key("job", r["job_id"]) in favorite_keys
    return r


def list_jobs(limit: int = 50, offset: int = 0, *, workspace_id: str = "",
              user_id: Any = "", allow_legacy: bool = False) -> List[Dict[str, Any]]:
    """Most recent first across all queues.

    Performance: walks all queue subdirs once to build (jid, status, mtime),
    then re-uses cached summaries for every (jid, status, mtime) we've seen
    before. Only changed entries hit disk via read_job_summary().
    """
    rows, report_numbers = _indexed_job_rows()
    if workspace_id or user_id:
        rows = [
            row for row in rows
            if job_in_scope(
                str(row.get("job_id") or ""), workspace_id=workspace_id,
                user_id=user_id, allow_legacy=allow_legacy,
            )
        ]
    favorite_keys = _report_favorite_key_set()
    offset = max(0, int(offset or 0))
    limit = max(1, int(limit or 50))
    return [
        _build_job_list_row(r, report_numbers, favorite_keys)
        for r in rows[offset: offset + limit]
    ]


def latest_job() -> Optional[Dict[str, Any]]:
    rows = list_jobs(limit=1)
    return rows[0] if rows else None


def _read_json_safe(path: Path) -> Optional[Any]:
    # utf-8-sig tolerates the BOM that PowerShell's Set-Content -Encoding UTF8
    # writes by default in Windows PowerShell 5.1.
    try:
        with open(path, "r", encoding="utf-8-sig") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None


def _origin_in_scope(origin: Any, *, workspace_id: str = "", user_id: Any = "",
                     allow_legacy: bool = False) -> bool:
    data = origin if isinstance(origin, dict) else {}
    actual_workspace = str(data.get("workspace_id") or "")
    actual_user = str(data.get("user_id") or "")
    expected_workspace = str(workspace_id or "")
    expected_user = str(user_id or "")
    if not actual_workspace and not actual_user:
        return bool(allow_legacy)
    if expected_workspace and actual_workspace != expected_workspace:
        return False
    if expected_user and actual_user and actual_user != expected_user:
        return False
    return True


def job_origin(job_id: str) -> Dict[str, Any]:
    located = find_job_dir(job_id)
    if not located:
        return {}
    doc = _read_json_safe(located[1] / "job.json") or {}
    return dict(doc.get("origin") or {}) if isinstance(doc, dict) else {}


def batch_origin(batch_id: str) -> Dict[str, Any]:
    batch_id = _safe_batch_id(batch_id)
    doc = _read_json_safe(_safe_child_path(batches_dir(), batch_id, "batch_id") / "batch.json") or {}
    return dict(doc.get("origin") or {}) if isinstance(doc, dict) else {}


def job_in_scope(job_id: str, *, workspace_id: str = "", user_id: Any = "",
                 allow_legacy: bool = False) -> bool:
    if not find_job_dir(job_id):
        return False
    return _origin_in_scope(
        job_origin(job_id), workspace_id=workspace_id, user_id=user_id,
        allow_legacy=allow_legacy,
    )


def batch_in_scope(batch_id: str, *, workspace_id: str = "", user_id: Any = "",
                   allow_legacy: bool = False) -> bool:
    path = _safe_child_path(batches_dir(), _safe_batch_id(batch_id), "batch_id")
    if not path.is_dir():
        return False
    return _origin_in_scope(
        batch_origin(batch_id), workspace_id=workspace_id, user_id=user_id,
        allow_legacy=allow_legacy,
    )


def report_in_scope(kind: str, report_id: str, *, workspace_id: str = "",
                    user_id: Any = "", allow_legacy: bool = False) -> bool:
    return (
        batch_in_scope(report_id, workspace_id=workspace_id, user_id=user_id,
                       allow_legacy=allow_legacy)
        if str(kind or "").lower() == "batch"
        else job_in_scope(report_id, workspace_id=workspace_id, user_id=user_id,
                          allow_legacy=allow_legacy)
    )


def _json_value_after_key(text: str, key: str) -> Optional[Any]:
    needle = f'"{key}"'
    pos = text.find(needle)
    if pos < 0:
        return None
    colon = text.find(":", pos + len(needle))
    if colon < 0:
        return None
    fragment = text[colon + 1:].lstrip()
    try:
        value, _end = json.JSONDecoder().raw_decode(fragment)
        return value
    except json.JSONDecodeError:
        return None


def _read_result_summary_fast(path: Path) -> Dict[str, Any]:
    """Read only list-view fields from result.json.

    Large Strategy Analyzer results can embed thousands of trades in
    result.json. Report lists need the header metrics only, so parsing the
    whole file for every table row creates multi-second stalls.
    """
    text = ""
    metrics: Optional[Any] = None
    try:
        with open(path, "rb") as fh:
            for size in (64 * 1024, 256 * 1024, 1024 * 1024):
                fh.seek(0)
                raw = fh.read(size)
                if not raw:
                    return {}
                text = raw.decode("utf-8-sig", errors="ignore")
                metrics = _json_value_after_key(text, "metrics")
                if isinstance(metrics, dict):
                    break
    except OSError:
        return {}
    if not isinstance(metrics, dict):
        full = _read_json_safe(path) or {}
        if not isinstance(full, dict):
            return {}
        return {
            "finished_at_utc": full.get("finished_at_utc"),
            "duration_ms": full.get("duration_ms"),
            "metrics": full.get("metrics") if isinstance(full.get("metrics"), dict) else {},
        }
    return {
        "finished_at_utc": _json_value_after_key(text, "finished_at_utc"),
        "duration_ms": _json_value_after_key(text, "duration_ms"),
        "metrics": metrics,
    }


def _read_json_array_cached(path: Path) -> Optional[List[Any]]:
    """Read a large JSON array artifact once per file signature.

    bars.json can be tens of megabytes. The UI pages through it, and parsing the
    full file for every page is the expensive part. Keep a tiny process-local LRU
    so repeated pages of the same report reuse the parsed array.
    """
    global _JSON_ARRAY_ARTIFACT_CACHE_BYTES
    if not path.is_file():
        return None
    sig = _file_cache_sig(path)
    if sig is None:
        data = _read_json_safe(path)
        return data if isinstance(data, list) else None
    key = str(path.resolve())
    cached = _JSON_ARRAY_ARTIFACT_CACHE.get(key)
    if cached and cached[0] == sig:
        try:
            _JSON_ARRAY_ARTIFACT_CACHE_ORDER.remove(key)
        except ValueError:
            pass
        _JSON_ARRAY_ARTIFACT_CACHE_ORDER.append(key)
        return cached[1]

    data = _read_json_safe(path)
    if not isinstance(data, list):
        return None

    _JSON_ARRAY_ARTIFACT_CACHE[key] = (sig, data)
    _JSON_ARRAY_ARTIFACT_CACHE_BYTES[key] = int(sig[0])
    try:
        _JSON_ARRAY_ARTIFACT_CACHE_ORDER.remove(key)
    except ValueError:
        pass
    _JSON_ARRAY_ARTIFACT_CACHE_ORDER.append(key)

    total_bytes = sum(_JSON_ARRAY_ARTIFACT_CACHE_BYTES.values())
    while (
        len(_JSON_ARRAY_ARTIFACT_CACHE_ORDER) > 1
        and total_bytes > _JSON_ARRAY_ARTIFACT_CACHE_MAX_BYTES
    ):
        old_key = _JSON_ARRAY_ARTIFACT_CACHE_ORDER.pop(0)
        total_bytes -= _JSON_ARRAY_ARTIFACT_CACHE_BYTES.pop(old_key, 0)
        _JSON_ARRAY_ARTIFACT_CACHE.pop(old_key, None)
    return data


def _compute_adjusted_metrics(trades: Optional[List[Any]],
                              parameters: Optional[Dict[str, Any]],
                              base_metrics: Optional[Dict[str, Any]] = None,
                              round_turn_commission: Optional[Any] = None
                              ) -> Optional[Dict[str, Any]]:
    """Compute commission-adjusted metrics from per-trade data.

    NinjaTrader runs use commission_template=None for backtests. Some
    strategies expose RoundTurnCommission as a NinjaScriptProperty, older/sample
    strategies do not. metrics.net_profit in result.json is therefore GROSS
    PnL; this helper recomputes adjusted metrics after paying the research
    round-turn commission per contract per trade.
    """
    if not isinstance(trades, list) or not trades:
        return None
    rtc = 0.0
    if isinstance(parameters, dict):
        try:
            rtc = float(parameters.get("RoundTurnCommission", 0.0) or 0.0)
        except (TypeError, ValueError):
            rtc = 0.0
    if rtc <= 0 and round_turn_commission is not None:
        try:
            rtc = float(round_turn_commission or 0.0)
        except (TypeError, ValueError):
            rtc = 0.0
    if rtc <= 0:
        return None

    n = 0
    gross_profit = 0.0
    gross_loss = 0.0
    commission_total = 0.0
    adjusted_pnls: List[float] = []
    wins = 0
    sum_w = 0.0
    sum_l = 0.0
    for t in trades:
        if not isinstance(t, dict):
            continue
        try:
            pnl = float(t.get("pnl_currency", 0.0) or 0.0)
            qty = float(t.get("quantity", 1) or 1)
        except (TypeError, ValueError):
            continue
        comm = qty * rtc
        adj = pnl - comm
        n += 1
        commission_total += comm
        if pnl > 0:
            gross_profit += pnl
        else:
            gross_loss += pnl
        if adj > 0:
            wins += 1
            sum_w += adj
        else:
            sum_l += abs(adj)
        adjusted_pnls.append(adj)

    if n == 0:
        return None

    gross_net = gross_profit + gross_loss
    net_after = gross_net - commission_total
    pf_after = (sum_w / sum_l) if sum_l > 0 else (None if sum_w == 0 else float("inf"))
    win_pct_after = round(wins / n * 100.0, 4)

    cum = 0.0
    peak = 0.0
    mdd = 0.0
    for x in adjusted_pnls:
        cum += x
        if cum > peak:
            peak = cum
        if cum - peak < mdd:
            mdd = cum - peak

    out = {
        "round_turn_commission": rtc,
        "commission_total_adjusted": round(commission_total, 4),
        "net_profit_after_commission": round(net_after, 4),
        "profit_factor_after_commission":
            (round(pf_after, 6) if isinstance(pf_after, float) and pf_after != float("inf") else pf_after),
        "max_drawdown_after_commission": round(mdd, 4),
        "win_pct_after_commission": win_pct_after,
        "trade_count_adjusted": n,
        "commission_template_used": "None (research round-turn commission)",
    }
    return out


def _compute_fast_adjusted_metrics(metrics: Dict[str, Any],
                                   parameters: Optional[Dict[str, Any]],
                                   round_turn_commission: Optional[Any] = None
                                   ) -> Optional[Dict[str, Any]]:
    rtc = 0.0
    if isinstance(parameters, dict):
        try:
            rtc = float(parameters.get("RoundTurnCommission", 0.0) or 0.0)
        except (TypeError, ValueError):
            rtc = 0.0
    if rtc <= 0 and round_turn_commission is not None:
        try:
            rtc = float(round_turn_commission or 0.0)
        except (TypeError, ValueError):
            rtc = 0.0
    if rtc <= 0:
        return None
    try:
        trade_count = int(metrics.get("trade_count") or 0)
        net_profit = float(metrics.get("net_profit") or 0.0)
    except (TypeError, ValueError):
        return None
    if trade_count <= 0:
        return None
    commission_total = trade_count * rtc
    return {
        "round_turn_commission": rtc,
        "commission_total_adjusted": round(commission_total, 4),
        "net_profit_after_commission": round(net_profit - commission_total, 4),
        "commission_template_used": "None (fast list estimate from trade_count)",
    }


def read_job_summary(job_id: str, include_adjusted: bool = True) -> Optional[Dict[str, Any]]:
    located = find_job_dir(job_id)
    if not located:
        return None
    status, jdir = located

    summary: Dict[str, Any] = {"status": status}

    job = _read_json_safe(jdir / "job.json") or {}
    summary["class_name"] = (job.get("strategy") or {}).get("class_name")
    summary["instrument"] = job.get("instrument")
    summary["timeframe"] = job.get("timeframe")
    summary["period"] = job.get("period")
    summary["created_at_utc"] = job.get("created_at_utc")
    summary["batch"] = job.get("batch")  # None for single jobs
    if isinstance(job.get("origin"), dict):
        summary["origin"] = job["origin"]
    portfolio = _job_portfolio_metadata(job)
    if portfolio:
        summary["portfolio"] = portfolio
        summary["slot"] = portfolio.get("slot")
        summary["cell_id"] = portfolio.get("cell_id")
        summary["strategy_name"] = portfolio.get("strategy_name")

    if status == "done":
        res = _read_result_summary_fast(jdir / "result.json")
        summary["finished_at_utc"] = res.get("finished_at_utc")
        summary["duration_ms"] = res.get("duration_ms")
        summary["metrics"] = res.get("metrics") or {}
        m = summary["metrics"]
        summary["trade_count"] = m.get("trade_count")
        summary["winning_pct"] = m.get("winning_pct")
        summary["net_profit"]  = m.get("net_profit")
        summary["gross_profit"] = m.get("gross_profit")
        summary["gross_loss"] = m.get("gross_loss")
        # Surface/fallback for the reports rating column.
        summary["profit_factor"] = m.get("profit_factor")
        if summary["profit_factor"] is None:
            pf = _profit_factor_from_gross(m.get("gross_profit"), m.get("gross_loss"))
            if pf is not None:
                summary["profit_factor"] = pf
        summary["max_drawdown"]  = m.get("max_drawdown")

        # --- Commission-adjusted metrics ---
        # NinjaTrader runs use commission_template=None so metrics.net_profit
        # is GROSS. Recompute "real" metrics from per-trade RoundTurnCommission.
        try:
            params = ((job.get("strategy") or {}).get("parameters") or {})
            execution = (job.get("execution") or {})
            if include_adjusted:
                trades_doc = _read_json_array_cached(jdir / "trades.json")
                adj = _compute_adjusted_metrics(
                    trades_doc,
                    params,
                    m,
                    execution.get("round_turn_commission"),
                )
            else:
                adj = _compute_fast_adjusted_metrics(
                    m,
                    params,
                    execution.get("round_turn_commission"),
                )
            if adj:
                m.update(adj)
                summary["net_profit_after_commission"] = adj.get("net_profit_after_commission")
                summary["profit_factor_after_commission"] = adj.get("profit_factor_after_commission")
                summary["commission_total_adjusted"] = adj.get("commission_total_adjusted")
                if adj.get("profit_factor_after_commission") is not None:
                    summary["profit_factor"] = adj.get("profit_factor_after_commission")
        except Exception:
            pass

        assessment = report_assessment.assess_report(summary.get("trade_count"), summary.get("period"), m)
        summary["assessment"] = assessment
        summary["frequency"] = assessment["frequency"]
        summary["confidence"] = assessment["confidence"]

        summary["validated_against_strategy_analyzer"] = VALIDATED_AGAINST_STRATEGY_ANALYZER
    elif status == "failed":
        err = _read_json_safe(jdir / "error.json") or {}
        summary["error_type"] = err.get("error_type")
        summary["error_message"] = (err.get("message") or "").splitlines()[0] if err.get("message") else None
        summary["finished_at_utc"] = err.get("finished_at_utc")
    elif status == "cancelled":
        res = _read_json_safe(jdir / "result.json") or {}
        summary["finished_at_utc"] = res.get("finished_at_utc") or res.get("cancelled_at_utc")
        summary["duration_ms"] = res.get("duration_ms")
        summary["metrics"] = res.get("metrics") or {}
        summary["trade_count"] = summary["metrics"].get("trade_count")
        assessment = report_assessment.assess_report(
            summary.get("trade_count"), summary.get("period"), summary["metrics"]
        )
        summary["assessment"] = assessment
        summary["frequency"] = assessment["frequency"]
        summary["confidence"] = assessment["confidence"]
        summary["cancel_reason"] = res.get("reason")
        summary["verification_warnings"] = res.get("verification_warnings") or []
    elif status == "running":
        hb = _read_json_safe(jdir / "heartbeat.json") or {}
        summary["heartbeat_at_utc"] = hb.get("updated_at_utc")
    return summary


def read_job_full(job_id: str) -> Optional[Dict[str, Any]]:
    located = find_job_dir(job_id)
    if not located:
        return None
    status, jdir = located
    report_numbers = _get_report_numbers_cached()
    out: Dict[str, Any] = {
        "job_id": job_id,
        "status": status,
        "report_no": report_numbers.get(_report_key("job", job_id)),
        "path": str(jdir),
        "files": [p.name for p in jdir.iterdir() if p.is_file()],
        "validated_against_strategy_analyzer": VALIDATED_AGAINST_STRATEGY_ANALYZER,
    }
    out["job"] = _read_json_safe(jdir / "job.json")
    # Lift the batch link (if any) to the top level so the UI can detect
    # batch membership without diving into the raw job.json sub-object.
    job_doc = out["job"]
    portfolio = _job_portfolio_metadata(job_doc)
    if portfolio:
        out["portfolio"] = portfolio
        out["slot"] = portfolio.get("slot")
        out["cell_id"] = portfolio.get("cell_id")
        if isinstance(job_doc, dict):
            strategy_doc = job_doc.get("strategy")
            if isinstance(strategy_doc, dict):
                strategy_doc.setdefault("display_name", portfolio.get("strategy_name") or strategy_doc.get("class_name"))
                strategy_doc.setdefault("slot", portfolio.get("slot"))
                strategy_doc.setdefault("cell_id", portfolio.get("cell_id"))
            job_doc.setdefault("portfolio", dict(portfolio))
    if isinstance(job_doc, dict) and isinstance(job_doc.get("batch"), dict):
        out["batch"] = job_doc["batch"]
    if status == "done":
        out["result"] = _read_json_safe(jdir / "result.json")
        if portfolio and isinstance(out.get("result"), dict):
            out["result"]["portfolio"] = dict(portfolio)
            _persist_result_portfolio(jdir, out["result"], portfolio)
        # Augment metrics with commission-adjusted view (real net etc).
        try:
            res = out["result"] or {}
            m = res.get("metrics") or {}
            trades_doc = _read_json_array_cached(jdir / "trades.json")
            params = ((job_doc.get("strategy") if isinstance(job_doc, dict) else None) or {}).get("parameters") or {}
            execution = ((job_doc.get("execution") if isinstance(job_doc, dict) else None) or {})
            adj = _compute_adjusted_metrics(
                trades_doc,
                params,
                m,
                execution.get("round_turn_commission"),
            )
            if adj and isinstance(m, dict):
                m.update(adj)
                res["metrics"] = m
                out["result"] = res
        except Exception:
            pass
    elif status == "failed":
        out["error"] = _read_json_safe(jdir / "error.json")
        out["result_partial"] = _read_json_safe(jdir / "result.partial.json")
    elif status == "cancelled":
        out["result"] = _read_json_safe(jdir / "result.json")
    elif status == "running":
        out["heartbeat"] = _read_json_safe(jdir / "heartbeat.json")
    return out


def read_trades(job_id: str, offset: int = 0, limit: int = 100) -> Dict[str, Any]:
    located = find_job_dir(job_id)
    if not located:
        return {"job_id": job_id, "found": False, "trades": [], "total": 0}
    status, jdir = located
    tj = jdir / "trades.json"
    if not tj.is_file():
        return {"job_id": job_id, "status": status, "trades": [], "total": 0,
                "note": "trades.json missing for this job"}
    arr = _read_json_array_cached(tj)
    if not isinstance(arr, list):
        return {"job_id": job_id, "status": status, "trades": [], "total": 0,
                "note": "trades.json malformed"}
    total = len(arr)
    if offset < 0:
        offset = 0
    if limit <= 0:
        limit = 100
    if limit > 1000:
        limit = 1000
    return {
        "job_id": job_id,
        "status": status,
        "total": total,
        "offset": offset,
        "limit": limit,
        "trades": arr[offset: offset + limit],
    }


def read_bars(job_id: str, offset: int = 0, limit: int = 5000) -> Dict[str, Any]:
    """Returns OHLCV bars artifact for a job.

    Older jobs have no bars.json — surface a 'note' instead of raising so
    the UI can render an "artifact missing" state cleanly.
    """
    located = find_job_dir(job_id)
    if not located:
        return {"job_id": job_id, "found": False, "bars": [], "total": 0}
    status, jdir = located
    bj = jdir / "bars.json"
    if not bj.is_file():
        return {"job_id": job_id, "status": status, "bars": [], "total": 0,
                "note": "bars.json missing for this job"}
    arr = _read_json_array_cached(bj)
    if not isinstance(arr, list):
        return {"job_id": job_id, "status": status, "bars": [], "total": 0,
                "note": "bars.json malformed"}
    total = len(arr)
    if offset < 0:
        offset = 0
    if limit <= 0:
        limit = 5000
    if limit > 200000:
        limit = 200000
    return {
        "job_id": job_id,
        "status": status,
        "total": total,
        "offset": offset,
        "limit": limit,
        "bars": arr[offset: offset + limit],
    }


def _timeframe_label(doc: Dict[str, Any]) -> str:
    """Compact timeframe token ('5m', '1h', '1D') from a job.json timeframe."""
    tf = doc.get("timeframe") if isinstance(doc.get("timeframe"), dict) else {}
    ptype = str(tf.get("bars_period_type") or "").strip()
    raw = tf.get("value")
    if raw is None:
        raw = tf.get("bars_period_value")
    try:
        val = int(raw)
    except (TypeError, ValueError):
        val = None
    if not val:
        return ""
    if ptype == "Day":
        return f"{val}D"
    abbr = {"Minute": "m", "Hour": "h", "Second": "s", "Tick": "t", "Week": "W", "Month": "M"}.get(ptype)
    return f"{val}{abbr}" if abbr else ""


def _instrument_bars_index() -> Dict[str, List[Dict[str, Any]]]:
    """TTL-cached map of instrument root -> newest-first jobs that carry a
    ``bars.json`` artifact.  Refreshed at most once per ``_INSTR_BARS_INDEX_TTL``
    seconds so a large chart grid does not re-scan the whole jobs tree per poll.
    """
    global _INSTR_BARS_INDEX, _INSTR_BARS_INDEX_AT
    now = time.monotonic()
    with _INSTR_BARS_INDEX_LOCK:
        if _INSTR_BARS_INDEX_AT and (now - _INSTR_BARS_INDEX_AT) < _INSTR_BARS_INDEX_TTL:
            return _INSTR_BARS_INDEX
    rows, _ = _indexed_job_rows()
    index: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows[:120]:
        jdir = Path(r["path"])
        if not (jdir / "bars.json").is_file():
            continue
        job = _read_json_safe(jdir / "job.json") or {}
        root = portfolio_cells.normalize_root(job.get("instrument"))
        if not root:
            continue
        index.setdefault(root, []).append({
            "job_id": r["job_id"], "dir": str(jdir),
            "instrument": job.get("instrument"), "timeframe": _timeframe_label(job),
        })
    with _INSTR_BARS_INDEX_LOCK:
        _INSTR_BARS_INDEX = index
        _INSTR_BARS_INDEX_AT = time.monotonic()
    return index


def read_instrument_bars(instrument: str, timeframe: str = "",
                         limit: int = 1500) -> Dict[str, Any]:
    """Return the most recent OHLCV bars for an instrument, sourced from
    NinjaTrader.

    There is no live market-data feed yet; the honest real source of NT bars
    are the ``bars.json`` artifacts produced by Strategy Analyzer runs. We pick
    the newest job whose instrument *root* matches the request, preferring an
    exact timeframe match and falling back to any timeframe available for that
    root. When nothing is available we return an honest-empty payload (never
    fabricated candles) so the chart can show a "waiting for NinjaTrader" state.
    """
    root = portfolio_cells.normalize_root(instrument)
    if not root:
        return {"instrument": instrument, "bars": [], "total": 0,
                "source": None, "live": False,
                "note": "инструмент не указан"}

    want_tf = str(timeframe or "").strip().lower()
    candidates = _instrument_bars_index().get(root, [])
    best: Optional[Dict[str, Any]] = None
    fallback: Optional[Dict[str, Any]] = None
    for candidate in candidates:
        label = str(candidate.get("timeframe") or "")
        if want_tf and label.lower() == want_tf:
            best = candidate
            break
        if fallback is None:
            fallback = candidate

    chosen = best or fallback
    if not chosen:
        return {"instrument": instrument, "root": root, "bars": [], "total": 0,
                "source": None, "live": False,
                "note": f"нет данных NinjaTrader по {root}"}

    arr = _read_json_array_cached(Path(chosen["dir"]) / "bars.json")
    if not isinstance(arr, list):
        arr = []
    total = len(arr)
    if limit <= 0:
        limit = 1500
    if limit > 20000:
        limit = 20000
    bars = arr[-limit:]
    note = ""
    if want_tf and not best and chosen.get("timeframe"):
        note = f"показан доступный ТФ {chosen['timeframe']}"
    return {
        "instrument": instrument, "root": root,
        "bars": bars, "total": total,
        "requested_timeframe": timeframe,
        "matched_timeframe": chosen.get("timeframe"),
        "source": {
            "job_id": chosen["job_id"],
            "instrument": chosen.get("instrument"),
            "timeframe": chosen.get("timeframe"),
        },
        "live": False,
        "note": note,
    }


def read_draw_objects(job_id: str) -> Dict[str, Any]:
    """Returns the strategy-draw-objects artifact for a job.

    Universal schema: {version, objects:[...], diagnostics:[...]}.
    Older jobs (or jobs run with a bridge that predates draw_objects.json)
    are reported as exported=false with a reason — UI shows a friendly hint
    instead of crashing.
    """
    located = find_job_dir(job_id)
    if not located:
        return {"job_id": job_id, "exported": False, "reason": "job_not_found",
                "objects": [], "diagnostics": []}
    status, jdir = located
    f = jdir / "draw_objects.json"
    if not f.is_file():
        return {"job_id": job_id, "status": status, "exported": False,
                "reason": "file_missing",
                "objects": [], "diagnostics": [
                    "draw_objects.json не найден — job выполнен старой версией bridge"
                ]}
    payload = _read_json_safe(f)
    if not isinstance(payload, dict):
        return {"job_id": job_id, "status": status, "exported": False,
                "reason": "malformed", "objects": [], "diagnostics": []}
    objs = payload.get("objects") or []
    return {
        "job_id": job_id,
        "status": status,
        "exported": True,
        "version": payload.get("version") or 1,
        "objects": objs if isinstance(objs, list) else [],
        "diagnostics": payload.get("diagnostics") or [],
    }


# ---------------------------------------------------------------------------
# Diagnostics: NinjaTrader process + bridge log tail.
# ---------------------------------------------------------------------------

def ninjatrader_user_dir() -> Path:
    env = os.environ.get("NT_USER_DIR")
    if env:
        return Path(env)
    return Path(os.path.expanduser("~")) / "Documents" / "NinjaTrader 8"


def bridge_log_tail(lines: int = 40) -> List[str]:
    log = ninjatrader_user_dir() / "log" / "NTAnalyzerBridge.log"
    if not log.is_file():
        return []
    try:
        with open(log, "r", encoding="utf-8", errors="replace") as fh:
            data = fh.readlines()
        return [s.rstrip() for s in data[-lines:]]
    except OSError:
        return []


_NT_RUNNING_CACHE: Dict[str, Any] = {"value": None, "checked_at": 0.0}
_NT_RUNNING_CACHE_LOCK = threading.Lock()
_NT_RUNNING_CACHE_TTL_SEC = 2.0


def ninjatrader_running(*, force: bool = False) -> Optional[bool]:
    """Best-effort cross-process check via tasklist (Windows only).

    Returns True/False on a confident match, or None ("unknown") when the
    detection itself failed (tasklist missing, timeout, OS not Windows).
    The case-insensitive substring scan also tolerates variations like
    "NinjaTrader 8.exe".

    Result is cached briefly: market-bars batch paths call this once per
    panel; spawning tasklist for every chart made Offline mode take ~1s/panel.
    """
    now = time.time()
    if not force:
        with _NT_RUNNING_CACHE_LOCK:
            cached_at = float(_NT_RUNNING_CACHE.get("checked_at") or 0.0)
            if cached_at and (now - cached_at) < _NT_RUNNING_CACHE_TTL_SEC:
                return _NT_RUNNING_CACHE.get("value")  # type: ignore[return-value]
    value: Optional[bool]
    if not sys.platform.startswith("win"):
        value = None
    else:
        try:
            import subprocess
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            tasklist = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "tasklist.exe"
            out = subprocess.run(
                [str(tasklist), "/FO", "CSV", "/NH"],
                capture_output=True,
                text=False,
                timeout=4,
                startupinfo=startupinfo,
                creationflags=creationflags,
            )
            if out.returncode != 0:
                value = None
            else:
                stdout = (out.stdout or b"").decode("utf-8", errors="ignore")
                stderr = (out.stderr or b"").decode("utf-8", errors="ignore")
                haystack = stdout.lower() + "\n" + stderr.lower()
                value = "ninjatrader" in haystack
        except Exception:
            value = None
    with _NT_RUNNING_CACHE_LOCK:
        _NT_RUNNING_CACHE["value"] = value
        _NT_RUNNING_CACHE["checked_at"] = time.time()
    return value


# ---------------------------------------------------------------------------
# Batches (multi-instrument runs).
#
# A batch is a thin metadata wrapper that owns N child jobs (one per
# instrument). Bridge does not need to know about batches at all: each child
# job is a normal /jobs/pending/<id>/job.json that the bridge picks up
# sequentially. Batch state is reconstructed at read time by aggregating the
# child jobs.
# ---------------------------------------------------------------------------

def batches_dir() -> Path:
    return runtime_env.data_path("batches", project_root=project_root())


def gen_batch_id(prefix: str = "batch") -> str:
    return f"{prefix}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')[:-3]}Z"


@dataclass
class CreateBatchRequest:
    class_name: str
    instruments: List[str]
    bars_period_type: str
    bars_period_value: int
    from_utc: str
    to_utc: str
    parameters: Dict[str, Any]
    risk_profile: Dict[str, Any] = field(default_factory=dict)
    calculate: str = "OnBarClose"
    is_tick_replay: bool = False
    order_fill_resolution: str = "High"
    slippage_ticks: int = 1
    commission: float = 0.0
    commission_template: str = "None"
    session_template: str = "CME US Index Futures RTH"
    timezone: str = "UTC"
    batch_id: Optional[str] = None
    name: Optional[str] = None  # display name for the batch
    # See CreateJobRequest.role.
    role: str = "research"
    origin: Optional[Dict[str, Any]] = None


def create_batch(req: CreateBatchRequest) -> Tuple[str, List[str]]:
    """Create a batch + N child jobs (one per instrument).

    Returns (batch_id, [job_id, ...]).
    """
    if not isinstance(req.instruments, list) or not req.instruments:
        raise JobValidationError("instruments: non-empty list required")
    # De-duplicate while preserving order.
    seen: List[str] = []
    for s in req.instruments:
        if not isinstance(s, str) or not s.strip():
            raise JobValidationError("instruments must be non-empty strings")
        s = s.strip()
        if s not in seen:
            seen.append(s)
    if len(seen) > 50:
        raise JobValidationError("batch capped at 50 instruments")

    risk_profile = _normalize_risk_profile(req.risk_profile)
    batch_id = req.batch_id or gen_batch_id("batch")
    batch_id = _safe_batch_id(batch_id)
    bdir = _safe_child_path(batches_dir(), batch_id, "batch_id")
    if bdir.exists():
        raise JobValidationError(f"batch {batch_id} already exists")

    total = len(seen)
    created_job_ids: List[str] = []
    children_meta: List[Dict[str, Any]] = []
    for idx, instrument in enumerate(seen):
        # Suffix the batch id into the job id so they sort together and are
        # easy to spot in jobs/pending.
        child_id = f"{batch_id}__{idx:02d}_{re.sub(r'[^A-Za-z0-9]+', '', instrument)[:16]}"
        child_req = CreateJobRequest(
            class_name=req.class_name,
            instrument=instrument,
            bars_period_type=req.bars_period_type,
            bars_period_value=req.bars_period_value,
            from_utc=req.from_utc,
            to_utc=req.to_utc,
            parameters=dict(req.parameters or {}),
            risk_profile=dict(risk_profile),
            calculate=req.calculate,
            is_tick_replay=req.is_tick_replay,
            order_fill_resolution=req.order_fill_resolution,
            slippage_ticks=req.slippage_ticks,
            commission=req.commission,
            commission_template=req.commission_template,
            session_template=req.session_template,
            timezone=req.timezone,
            job_id=child_id,
            role=getattr(req, "role", "research"),
            batch_id=batch_id,
            batch_index=idx,
            batch_total=total,
            origin=dict(req.origin or {}),
        )
        try:
            jid, _ = create_job(child_req)
        except JobValidationError as e:
            # Roll back already-created children so the batch is atomic.
            for done_id in created_job_ids:
                _try_remove_pending_job(done_id)
            raise JobValidationError(
                f"batch child {idx} ({instrument}): {e}") from e
        created_job_ids.append(jid)
        child_meta = {
            "batch_index": idx,
            "instrument":  instrument,
            "job_id":      jid,
        }
        child_portfolio = _resolve_portfolio_metadata(instrument, req.class_name)
        if child_portfolio:
            child_meta["portfolio"] = child_portfolio
        children_meta.append(child_meta)

    # Persist batch manifest.
    bdir.mkdir(parents=True, exist_ok=True)
    created_at_utc = utcnow_iso()
    manifest = {
        "schema_version": "0.1",
        "batch_id": batch_id,
        "name": req.name or f"{req.class_name} x{total}",
        "created_at_utc": created_at_utc,
        "strategy": {
            "class_name": req.class_name,
            "parameters": dict(req.parameters or {}),
        },
        "timeframe": {
            "bars_period_type": req.bars_period_type,
            "value": int(req.bars_period_value),
        },
        "period": {"from_utc": req.from_utc, "to_utc": req.to_utc},
        "risk_profile": dict(risk_profile),
        "execution": {
            "calculate": req.calculate,
            "is_tick_replay": bool(req.is_tick_replay),
            "order_fill_resolution": req.order_fill_resolution,
            "slippage_ticks": int(req.slippage_ticks),
            "commission": float(req.commission),
            "commission_template": req.commission_template,
            "session_template": req.session_template,
            "timezone": req.timezone,
            "role": getattr(req, "role", "research"),
        },
        "instruments": seen,
        "children": children_meta,
        "total": total,
    }
    if isinstance(req.origin, dict):
        manifest["origin"] = dict(req.origin)
    _atomic_write_text(bdir / "batch.json",
                       json.dumps(manifest, ensure_ascii=False, indent=2))
    _ensure_report_number("batch", batch_id, created_at_utc)
    return batch_id, created_job_ids


def _try_remove_pending_job(job_id: str) -> None:
    """Best-effort cleanup of a pending job dir (used to roll back partial
    batch creation)."""
    try:
        p = _safe_child_path(jobs_dir() / "pending", job_id, "job_id")
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
    except (OSError, JobValidationError):
        pass


def _safe_batch_id(batch_id: str) -> str:
    return _validate_safe_id(batch_id, "batch_id")


def count_batches(*, workspace_id: str = "", user_id: Any = "",
                  allow_legacy: bool = False) -> int:
    if workspace_id or user_id:
        return len(list_batches(
            limit=1_000_000, workspace_id=workspace_id, user_id=user_id,
            allow_legacy=allow_legacy,
        ))
    bdir = batches_dir()
    if not bdir.is_dir():
        return 0
    n = 0
    for child in bdir.iterdir():
        if child.is_dir() and not child.name.startswith("."):
            n += 1
    return n


def _indexed_batch_rows() -> List[Tuple[float, Path]]:
    rows: List[Tuple[float, Path]] = []
    bdir = batches_dir()
    if not bdir.is_dir():
        return rows
    for child in bdir.iterdir():
        if not child.is_dir() or child.name.startswith("."):
            continue
        try:
            rows.append((child.stat().st_mtime, child))
        except OSError:
            continue
    rows.sort(reverse=True)
    return rows


def _build_batch_list_row(bdir_mtime: float,
                          p: Path,
                          report_numbers: Dict[str, int],
                          favorite_keys: set[str],
                          include_metrics: bool = False) -> Dict[str, Any]:
    bid = p.name
    m = _read_json_safe(p / "batch.json") or {}
    children = m.get("children") or []
    _fp, loc_index = _get_job_location_index()
    # Compute child status/mtime signature for cache.  Status is part of
    # the signature because a job directory can move between queue folders
    # without changing its own mtime.
    max_child_mtime = 0.0
    child_status_parts: List[str] = []
    for c in children:
        jid = c.get("job_id")
        if not jid:
            continue
        loc = _job_loc_from_index(jid, loc_index)
        if not loc:
            child_status_parts.append(f"{jid}:missing:0")
            continue
        status, child_dir = loc
        try:
            cm = child_dir.stat().st_mtime
            if cm > max_child_mtime:
                max_child_mtime = cm
        except OSError:
            cm = 0.0
        child_status_parts.append(f"{jid}:{status}:{round(cm, 3)}")
    sig = (
        round(bdir_mtime, 3),
        round(max_child_mtime, 3),
        "|".join(child_status_parts),
        bool(include_metrics),
    )
    cached = _BATCH_METRICS_CACHE.get(bid)
    if cached and cached[0] == sig:
        agg_payload = cached[1]
    else:
        agg = _aggregate_batch_status(children, loc_index)
        instruments = m.get("instruments")
        if not instruments:
            seen, dedup = set(), []
            for c in children:
                inst = c.get("instrument")
                if inst and inst not in seen:
                    seen.add(inst)
                    dedup.append(inst)
            instruments = dedup
        period = m.get("period") or _aggregate_batch_period(children, loc_index)
        if include_metrics:
            agg_metrics = _aggregate_batch_metrics(children, loc_index)
            finished_at = _aggregate_batch_finished(children, loc_index)
        else:
            # Hot path for /api/reports and /api/batches list views: do not
            # parse every child result.json just to paint the report table.
            # Full per-child metrics are loaded by /api/batches/{id}/results
            # when the operator opens a concrete batch.
            agg_metrics = {}
            finished_at = m.get("finished_at_utc")
        agg_payload = {
            "name":            m.get("name") or bid,
            "created_at_utc":  m.get("created_at_utc"),
            "finished_at_utc": finished_at,
            "class_name":      (m.get("strategy") or {}).get("class_name"),
            "total":           m.get("total") or len(children),
            "counts":          agg,
            "instruments":     instruments,
            "period":          period,
            "trade_count":     agg_metrics.get("trade_count"),
            "winning_pct":     agg_metrics.get("winning_pct"),
            "net_profit":      agg_metrics.get("net_profit"),
            "gross_profit":    agg_metrics.get("gross_profit"),
            "gross_loss":      agg_metrics.get("gross_loss"),
            "profit_factor":   agg_metrics.get("profit_factor"),
            "max_drawdown":    agg_metrics.get("max_drawdown"),
            "origin":          dict(m.get("origin") or {}),
        }
        if include_metrics:
            assessment = report_assessment.assess_report(
                agg_payload.get("trade_count"), period, agg_metrics
            )
            agg_payload["assessment"] = assessment
            agg_payload["frequency"] = assessment["frequency"]
            agg_payload["confidence"] = assessment["confidence"]
        _BATCH_METRICS_CACHE[bid] = (sig, agg_payload)
    favorite_children_count = 0
    for c in children:
        if not isinstance(c, dict):
            continue
        jid = c.get("job_id")
        if jid and _report_key("job", str(jid)) in favorite_keys:
            favorite_children_count += 1

    return {
        "batch_id":  bid,
        "report_no": report_numbers.get(_report_key("batch", bid)),
        "favorite": _report_key("batch", bid) in favorite_keys,
        "favorite_children_count": favorite_children_count,
        "mtime": bdir_mtime,
        **agg_payload,
    }


def list_batches(limit: int = 50, offset: int = 0, *, workspace_id: str = "",
                 user_id: Any = "", allow_legacy: bool = False) -> List[Dict[str, Any]]:
    """Most recent batches first.

    Aggregate metrics + period + finished_at scans are O(N)
    across all child jobs and were re-run on every poll. Now cached per
    (batch_id, signature) where signature folds in bdir mtime + max child
    mtime, so polling refreshes are nearly free until something changes.
    """
    global _REPORT_NUMBERS_FP, _REPORT_NUMBERS_VALUE

    rows = _indexed_batch_rows()
    if workspace_id or user_id:
        rows = [
            row for row in rows
            if batch_in_scope(
                row[1].name, workspace_id=workspace_id, user_id=user_id,
                allow_legacy=allow_legacy,
            )
        ]
    if not rows:
        return []

    # Reuse cached report-numbers fingerprint computed by list_jobs (or
    # rebuild it cheaply here when the caller hits batches before jobs).
    if _REPORT_NUMBERS_FP is None:
        _REPORT_NUMBERS_VALUE = _read_report_numbers_mapping_cached()
        if not _REPORT_NUMBERS_VALUE:
            _REPORT_NUMBERS_VALUE = sync_report_numbers()
        # Approximate fingerprint that a subsequent list_jobs() will recompute
        # exactly if anything changed.
        _REPORT_NUMBERS_FP = (0, 0.0)
    report_numbers = _REPORT_NUMBERS_VALUE
    favorite_keys = _report_favorite_key_set()

    offset = max(0, int(offset or 0))
    limit = max(1, int(limit or 50))

    return [
        _build_batch_list_row(bdir_mtime, p, report_numbers, favorite_keys)
        for bdir_mtime, p in rows[offset: offset + limit]
    ]


def _summarize_report_batch_status(counts: Dict[str, int], total: int) -> str:
    done = int(counts.get("done") or 0)
    failed = int(counts.get("failed") or 0)
    cancelled = int(counts.get("cancelled") or 0)
    running = int(counts.get("running") or 0)
    pending = int(counts.get("pending") or 0)
    missing = int(counts.get("missing") or 0)
    total = max(0, int(total or 0))
    if running:
        return "running"
    if pending:
        return "pending"
    if failed and (done or cancelled):
        return "partial_failed"
    if cancelled and done:
        return "partial_cancelled"
    if failed or missing:
        return "failed"
    if cancelled:
        return "cancelled"
    if done or total == 0:
        return "done"
    return "pending"


def _report_status_matches(status: str, status_filter: str) -> bool:
    status = str(status or "")
    status_filter = str(status_filter or "all")
    if status_filter == "all":
        return True
    if status_filter == "failed":
        return status in {"failed", "partial_failed"}
    if status_filter == "cancelled":
        return status in {"cancelled", "partial_cancelled"}
    return status == status_filter


def _coerce_report_sort_col(value: str) -> str:
    allowed = {
        "report_no", "mtime", "label", "strategy", "kind", "status", "period",
        "trades", "winning_pct", "profit_factor", "net_profit", "frequency", "confidence",
    }
    col = str(value or "mtime").strip()
    return col if col in allowed else "mtime"


def _coerce_report_sort_dir(value: str) -> str:
    return "asc" if str(value or "").strip().lower() == "asc" else "desc"


def list_reports(limit: int = 100,
                 offset: int = 0,
                 sort_col: str = "mtime",
                 sort_dir: str = "desc",
                 status_filter: str = "all",
                 query: str = "",
                 report_no: str = "",
                 instrument: str = "",
                 frequency: str = "",
                 from_date: str = "",
                 to_date: str = "",
                 min_trades: Optional[float] = None,
                 min_win: Optional[float] = None,
                 min_pf: Optional[float] = None,
                 pnl_sign: str = "",
                 min_confidence: Optional[float] = None,
                 analysis_limit: int = 500,
                 workspace_id: str = "",
                 user_id: Any = "",
                 allow_legacy: bool = False) -> Dict[str, Any]:
    """Mixed reports feed with one shared server-side pagination stream.

    The UI scrolls by pages, so sorting must happen before slicing.  The
    default "created" sort uses the stable report number instead of directory
    mtime: opening a batch can update its folder mtime and otherwise makes old
    reports float above newer 4000+ reports.
    """
    _load_persisted_report_summaries()
    job_rows, report_numbers = _indexed_job_rows()
    batch_rows = _indexed_batch_rows()
    if workspace_id or user_id:
        job_rows = [
            row for row in job_rows
            if job_in_scope(
                str(row.get("job_id") or ""), workspace_id=workspace_id,
                user_id=user_id, allow_legacy=allow_legacy,
            )
        ]
        batch_rows = [
            row for row in batch_rows
            if batch_in_scope(
                row[1].name, workspace_id=workspace_id, user_id=user_id,
                allow_legacy=allow_legacy,
            )
        ]
    favorite_keys = _report_favorite_key_set()
    sort_col = _coerce_report_sort_col(sort_col)
    sort_dir = _coerce_report_sort_dir(sort_dir)
    status_filter = str(status_filter or "all").strip().lower()
    if status_filter not in {"all", "pending", "running", "done", "failed", "cancelled", "favorite"}:
        status_filter = "all"

    counts = {sub: 0 for sub in QUEUE_SUBDIRS}
    for row in job_rows:
        status = str(row.get("status") or "")
        if status in counts:
            counts[status] += 1

    indexed: List[Dict[str, Any]] = []
    for row in job_rows:
        job_id = str(row.get("job_id") or "")
        key = _report_key("job", job_id)
        indexed.append({
            "kind": "job",
            "mtime": float(row.get("mtime") or 0.0),
            "id": job_id,
            "key": key,
            "report_no": report_numbers.get(key),
            "status": str(row.get("status") or ""),
            "favorite": key in favorite_keys,
            "row": row,
        })
    for bdir_mtime, p in batch_rows:
        bid = p.name
        key = _report_key("batch", bid)
        indexed.append({
            "kind": "batch",
            "mtime": float(bdir_mtime or 0.0),
            "id": bid,
            "key": key,
            "report_no": report_numbers.get(key),
            "status": None,
            "favorite": key in favorite_keys,
            "row": (bdir_mtime, p),
        })

    full_sort_cols = {
        "label", "strategy", "period", "trades", "winning_pct", "profit_factor",
        "net_profit", "frequency", "confidence",
    }
    need_batch_status = status_filter not in {"all", "favorite"} or sort_col == "status"
    need_full_row = sort_col in full_sort_cols
    _fp, loc_index = _get_job_location_index()

    def materialized(item: Dict[str, Any], *, include_metrics: bool = False) -> Dict[str, Any]:
        cached = item.get("_full_row")
        if cached is not None and (not include_metrics or item.get("_full_row_has_metrics")):
            return cached
        if item["kind"] == "job":
            row = _build_job_list_row(item["row"], report_numbers, favorite_keys)
            item["_full_row"] = row
            item["_full_row_has_metrics"] = True
            item["status"] = str(row.get("status") or item.get("status") or "")
            item["favorite"] = bool(row.get("favorite"))
            return row
        bdir_mtime, p = item["row"]
        row = _build_batch_list_row(
            bdir_mtime,
            p,
            report_numbers,
            favorite_keys,
            include_metrics=include_metrics,
        )
        item["_full_row"] = row
        item["_full_row_has_metrics"] = include_metrics
        item["status"] = _summarize_report_batch_status(row.get("counts") or {}, int(row.get("total") or 0))
        item["favorite"] = bool(row.get("favorite")) or int(row.get("favorite_children_count") or 0) > 0
        return row

    def ensure_batch_status(item: Dict[str, Any]) -> str:
        if item["kind"] != "batch":
            return str(item.get("status") or "")
        if item.get("status"):
            return str(item.get("status") or "")
        bdir_mtime, p = item["row"]
        meta = _read_json_safe(p / "batch.json") or {}
        children = meta.get("children") or []
        counts_local = _aggregate_batch_status(children, loc_index)
        item["status"] = _summarize_report_batch_status(counts_local, int(meta.get("total") or len(children)))
        if status_filter == "favorite" and not item.get("favorite"):
            for child in children:
                jid = child.get("job_id") if isinstance(child, dict) else None
                if jid and _report_key("job", str(jid)) in favorite_keys:
                    item["favorite"] = True
                    break
        return str(item.get("status") or "")

    def sort_text(value: Any) -> str:
        return str(value or "").casefold()

    def metric_value(value: Any, default: float = -1.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def sort_key(item: Dict[str, Any]) -> Tuple[Any, ...]:
        rn = item.get("report_no")
        rn_val = int(rn) if isinstance(rn, int) else -1
        if sort_col in {"mtime", "report_no"}:
            primary: Any = rn_val
        elif sort_col == "kind":
            primary = item["kind"]
        elif sort_col == "status":
            primary = ensure_batch_status(item)
        else:
            include_metrics = sort_col in {
                "trades", "winning_pct", "profit_factor", "net_profit", "frequency", "confidence",
            }
            row = materialized(item, include_metrics=include_metrics)
            if item["kind"] == "job":
                label = row.get("instrument") or row.get("job_id") or ""
                strategy = row.get("class_name") or ""
                period = (row.get("period") or {}).get("from_utc") if isinstance(row.get("period"), dict) else ""
                trades = row.get("trade_count")
            else:
                insts = row.get("instruments") if isinstance(row.get("instruments"), list) else []
                label = ", ".join(str(x) for x in insts) or row.get("name") or row.get("batch_id") or ""
                strategy = row.get("class_name") or ""
                period = (row.get("period") or {}).get("from_utc") if isinstance(row.get("period"), dict) else ""
                trades = row.get("trade_count")
            if sort_col == "label":
                primary = sort_text(label)
            elif sort_col == "strategy":
                primary = sort_text(strategy)
            elif sort_col == "period":
                primary = sort_text(period)
            elif sort_col == "trades":
                primary = metric_value(trades)
            elif sort_col == "winning_pct":
                primary = metric_value(row.get("winning_pct"))
            elif sort_col == "profit_factor":
                primary = metric_value(
                    row.get("profit_factor_after_commission")
                    if row.get("profit_factor_after_commission") is not None
                    else row.get("profit_factor")
                )
            elif sort_col == "net_profit":
                primary = metric_value(
                    row.get("net_profit_after_commission")
                    if row.get("net_profit_after_commission") is not None
                    else row.get("net_profit"),
                    -10**18,
                )
            elif sort_col == "frequency":
                frequency = row.get("frequency") if isinstance(row.get("frequency"), dict) else {}
                primary = metric_value(frequency.get("trades_per_week"))
            else:
                confidence = row.get("confidence") if isinstance(row.get("confidence"), dict) else {}
                primary = metric_value(confidence.get("score"))
        return (primary, rn_val, item["kind"], str(item["id"]))

    if need_batch_status:
        for item in indexed:
            if item["kind"] == "batch":
                ensure_batch_status(item)
    if status_filter == "favorite":
        for item in indexed:
            if item["kind"] == "batch":
                ensure_batch_status(item)

    filtered: List[Dict[str, Any]] = []
    for item in indexed:
        if status_filter == "favorite":
            if item.get("favorite"):
                filtered.append(item)
            continue
        if status_filter != "all":
            status = ensure_batch_status(item) if item["kind"] == "batch" else str(item.get("status") or "")
            if not _report_status_matches(status, status_filter):
                continue
        filtered.append(item)

    query_key = str(query or "").strip().casefold()
    report_no_key = str(report_no or "").strip().casefold()
    instrument_key = str(instrument or "").strip().casefold()
    frequency_key = str(frequency or "").strip().lower()
    pnl_sign_key = str(pnl_sign or "").strip().lower()
    has_column_filters = any([
        query_key, report_no_key, instrument_key, frequency_key, from_date, to_date,
        min_trades is not None, min_win is not None, min_pf is not None,
        pnl_sign_key, min_confidence is not None,
    ])
    archive_total = len(filtered)
    scope_limited = False
    analysis_limit = max(0, min(int(analysis_limit or 0), 10000))
    if report_no_key:
        filtered = [item for item in filtered if report_no_key in str(item.get("report_no") or "").casefold()]
    if (need_full_row or has_column_filters) and analysis_limit and len(filtered) > analysis_limit:
        filtered.sort(key=lambda item: int(item.get("report_no") or -1), reverse=True)
        filtered = filtered[:analysis_limit]
        scope_limited = True
    if has_column_filters:
        refined: List[Dict[str, Any]] = []
        for item in filtered:
            row = materialized(item, include_metrics=True)
            instruments = row.get("instruments") if isinstance(row.get("instruments"), list) else []
            instrument_text = " ".join(str(value) for value in instruments) if instruments else str(row.get("instrument") or "")
            label = str(row.get("name") or row.get("label") or row.get("class_name") or row.get("job_id") or row.get("batch_id") or "")
            strategy = str(row.get("class_name") or "")
            searchable = " ".join([label, strategy, instrument_text, str(item.get("id") or "")]).casefold()
            if query_key and query_key not in searchable:
                continue
            if report_no_key and report_no_key not in str(row.get("report_no") or "").casefold():
                continue
            if instrument_key and instrument_key not in instrument_text.casefold():
                continue
            created = str(row.get("created_at_utc") or "")[:10]
            if from_date and created and created < str(from_date)[:10]:
                continue
            if to_date and created and created > str(to_date)[:10]:
                continue
            if min_trades is not None and metric_value(row.get("trade_count"), -1) < min_trades:
                continue
            if min_win is not None and metric_value(row.get("winning_pct"), -1) < min_win:
                continue
            pf_value = row.get("profit_factor_after_commission") if row.get("profit_factor_after_commission") is not None else row.get("profit_factor")
            if min_pf is not None and metric_value(pf_value, -1) < min_pf:
                continue
            net = metric_value(
                row.get("net_profit_after_commission")
                if row.get("net_profit_after_commission") is not None
                else row.get("net_profit"),
                0,
            )
            if pnl_sign_key == "positive" and net <= 0:
                continue
            if pnl_sign_key == "negative" and net >= 0:
                continue
            frequency_doc = row.get("frequency") if isinstance(row.get("frequency"), dict) else {}
            if frequency_key and frequency_doc.get("key") != frequency_key:
                continue
            confidence_doc = row.get("confidence") if isinstance(row.get("confidence"), dict) else {}
            if min_confidence is not None and metric_value(confidence_doc.get("score"), -1) < min_confidence:
                continue
            refined.append(item)
        filtered = refined

    if need_full_row:
        include_metrics = sort_col in {
            "trades", "winning_pct", "profit_factor", "net_profit", "frequency", "confidence",
        }
        for item in filtered:
            materialized(item, include_metrics=include_metrics)

    filtered.sort(key=sort_key, reverse=(sort_dir == "desc"))

    if need_full_row or has_column_filters:
        _persist_report_summaries()

    offset = max(0, int(offset or 0))
    limit = max(1, int(limit or 100))
    jobs: List[Dict[str, Any]] = []
    batches: List[Dict[str, Any]] = []
    for item in filtered[offset: offset + limit]:
        if item["kind"] == "job":
            jobs.append(materialized(item))
        else:
            batches.append(materialized(item))

    return {
        "counts": counts,
        "offset": offset,
        "limit": limit,
        "total": len(filtered),
        "archive_total": archive_total,
        "analysis_limit": analysis_limit,
        "scope_limited": scope_limited,
        "sort": sort_col,
        "dir": sort_dir,
        "filter": status_filter,
        "column_filters": {
            "query": query, "report_no": report_no, "instrument": instrument,
            "frequency": frequency, "from": from_date, "to": to_date,
            "min_trades": min_trades, "min_win": min_win, "min_pf": min_pf,
            "pnl_sign": pnl_sign, "min_confidence": min_confidence,
        },
        "jobs": jobs,
        "batches": batches,
    }


def _aggregate_batch_period(children: List[Dict[str, Any]],
                            loc_index: Optional[Dict[str, Tuple[str, Path, float]]] = None
                            ) -> Optional[Dict[str, str]]:
    """Derive the covering period for a batch from its children's job.json files.

    Returns {from_utc, to_utc} spanning min(child.from) → max(child.to), or None
    when no period data is available. Used as a fallback for older batches that
    were created before batch.json stored the period at the manifest level.
    """
    from_dates: List[str] = []
    to_dates:   List[str] = []
    for c in children:
        jid = c.get("job_id")
        if not jid:
            continue
        loc = _job_loc_from_index(jid, loc_index)
        if not loc:
            continue
        _, jdir = loc
        jmeta = _read_json_safe(jdir / "job.json") or {}
        p = jmeta.get("period") or {}
        if p.get("from_utc"):
            from_dates.append(p["from_utc"])
        if p.get("to_utc"):
            to_dates.append(p["to_utc"])
    if not from_dates or not to_dates:
        return None
    return {"from_utc": min(from_dates), "to_utc": max(to_dates)}


def _aggregate_batch_finished(children: List[Dict[str, Any]],
                              loc_index: Optional[Dict[str, Tuple[str, Path, float]]] = None
                              ) -> Optional[str]:
    """Return the latest finished_at_utc across terminal child jobs, or
    None if no child has finished. Used for the "Финиш / НВ" column on
    batch rows.
    """
    latest: Optional[str] = None
    for c in children:
        jid = c.get("job_id")
        if not jid:
            continue
        loc = _job_loc_from_index(jid, loc_index)
        if not loc:
            continue
        status, jdir = loc
        ts: Optional[str] = None
        if status == "done":
            res = _read_json_safe(jdir / "result.json") or {}
            ts = res.get("finished_at_utc")
        elif status == "cancelled":
            res = _read_json_safe(jdir / "result.json") or {}
            ts = res.get("finished_at_utc") or res.get("cancelled_at_utc")
        elif status == "failed":
            err = _read_json_safe(jdir / "error.json") or {}
            ts = err.get("finished_at_utc")
        if ts and (latest is None or ts > latest):
            latest = ts
    return latest


def _aggregate_batch_status(children: List[Dict[str, Any]],
                            loc_index: Optional[Dict[str, Tuple[str, Path, float]]] = None
                            ) -> Dict[str, int]:
    counts = {"pending": 0, "running": 0, "done": 0, "failed": 0, "cancelled": 0,
              "missing": 0}
    for c in children:
        jid = c.get("job_id")
        if not jid:
            counts["missing"] += 1
            continue
        loc = _job_loc_from_index(jid, loc_index)
        if not loc:
            counts["missing"] += 1
            continue
        counts[loc[0]] = counts.get(loc[0], 0) + 1
    return counts


def _aggregate_batch_metrics(children: List[Dict[str, Any]],
                             loc_index: Optional[Dict[str, Tuple[str, Path, float]]] = None
                             ) -> Dict[str, Any]:
    """Return {trade_count, winning_pct, net_profit, profit_factor, max_drawdown}
    aggregated across all done child jobs.

    profit_factor is recomputed from summed gross_profit/gross_loss; max_drawdown
    is the worst (most negative) value across children — a portfolio-level lower
    bound rather than a true blended drawdown, but sufficient for the
    confidence score and table display.
    """
    total_trades = 0
    total_winners = 0
    total_net = 0.0
    total_gross_profit = 0.0
    total_gross_loss = 0.0
    worst_dd = 0.0
    has_any = False
    has_net = False
    has_gross = False
    has_dd = False
    for c in children:
        jid = c.get("job_id")
        if not jid:
            continue
        loc = _job_loc_from_index(jid, loc_index)
        if not loc or loc[0] != "done":
            continue
        _, jdir = loc
        res = _read_json_safe(jdir / "result.json") or {}
        m = res.get("metrics") or {}
        tc = m.get("trade_count")
        wp = m.get("winning_pct")
        np_ = m.get("net_profit")
        gp = m.get("gross_profit")
        gl = m.get("gross_loss")
        dd = m.get("max_drawdown")
        if tc is None:
            continue
        has_any = True
        total_trades += int(tc)
        if wp is not None:
            total_winners += round(float(wp) * int(tc) / 100)
        if np_ is not None:
            try:
                total_net += float(np_); has_net = True
            except (TypeError, ValueError): pass
        if gp is not None and gl is not None:
            try:
                total_gross_profit += float(gp)
                total_gross_loss   += float(gl)
                has_gross = True
            except (TypeError, ValueError): pass
        if dd is not None:
            try:
                ddf = float(dd)
                if ddf < worst_dd: worst_dd = ddf
                has_dd = True
            except (TypeError, ValueError): pass
    if not has_any:
        return {}
    winning_pct = (total_winners / total_trades * 100) if total_trades > 0 else None
    pf = None
    if has_gross and total_gross_loss < 0:
        pf = total_gross_profit / abs(total_gross_loss)
    return {
        "trade_count":   total_trades,
        "winning_pct":   round(winning_pct, 2) if winning_pct is not None else None,
        "net_profit":    total_net if has_net else None,
        "gross_profit":  total_gross_profit if has_gross else None,
        "gross_loss":    total_gross_loss if has_gross else None,
        "profit_factor": round(pf, 4) if pf is not None else None,
        "max_drawdown":  worst_dd if has_dd else None,
    }


def _profit_factor_from_gross(gross_profit: Any, gross_loss: Any) -> Optional[float]:
    """Return finite PF from gross profit/loss, or None for no-loss/unknown cases.

    No-loss profitable runs have infinite PF; the frontend can display ∞ from
    gross_profit/gross_loss directly, while API JSON stays standards-compliant.
    """
    if gross_profit is None or gross_loss is None:
        return None
    try:
        gp = float(gross_profit)
        gl = float(gross_loss)
    except (TypeError, ValueError):
        return None
    if gl < 0:
        return round(gp / abs(gl), 6)
    return None


def read_batch(batch_id: str) -> Optional[Dict[str, Any]]:
    batch_id = _safe_batch_id(batch_id)
    p = _safe_child_path(batches_dir(), batch_id, "batch_id")
    if not p.is_dir():
        return None
    m = _read_json_safe(p / "batch.json")
    if not isinstance(m, dict):
        return None
    m["counts"] = _aggregate_batch_status(m.get("children") or [])
    return m


def read_batch_results(batch_id: str) -> Optional[Dict[str, Any]]:
    """Return one row per child with the metrics needed by the Result top
    table (instrument, status, metrics, period_check)."""
    m = read_batch(batch_id)
    if not m:
        return None
    report_numbers = _get_report_numbers_cached()
    favorite_keys = _report_favorite_key_set()
    rows: List[Dict[str, Any]] = []
    for c in m.get("children") or []:
        jid = c.get("job_id")
        instrument = c.get("instrument")
        row: Dict[str, Any] = {
            "batch_index": c.get("batch_index"),
            "instrument":  instrument,
            "job_id":      jid,
            "status":      "missing",
            "metrics":     None,
            "period_check": None,
            "error":       None,
            "favorite":    _report_key("job", str(jid)) in favorite_keys if jid else False,
        }
        if jid:
            loc = find_job_dir(jid)
            if loc:
                status, jdir = loc
                row["status"] = status
                # Read job.json to get created_at_utc + period.
                # for every status so the batch-details table can show them.
                jmeta = _read_json_safe(jdir / "job.json") or {}
                row["created_at_utc"] = jmeta.get("created_at_utc")
                row["period"]         = jmeta.get("period")
                row["class_name"]     = (jmeta.get("strategy") or {}).get("class_name")
                if status == "done":
                    res = _read_json_safe(jdir / "result.json") or {}
                    row["metrics"] = res.get("metrics") or {}
                    row["period_check"] = _extract_period_check(
                        res.get("verification_warnings") or [])
                elif status == "failed":
                    err = _read_json_safe(jdir / "error.json") or {}
                    row["error"] = (err.get("message") or "").splitlines()[0:1]
                elif status == "cancelled":
                    res = _read_json_safe(jdir / "result.json") or {}
                    row["result"] = res
                    msg = (res.get("reason") or "cancelled").splitlines()[0:1]
                    row["error"] = msg
        rows.append(row)
    return {
        "batch_id": batch_id,
        "report_no": report_numbers.get(_report_key("batch", batch_id)),
        "name":     m.get("name"),
        "created_at_utc": m.get("created_at_utc"),
        "strategy": m.get("strategy"),
        "timeframe": m.get("timeframe"),
        "period":    m.get("period"),
        "risk_profile": m.get("risk_profile"),
        "execution": m.get("execution"),
        "total":     m.get("total"),
        "counts":    m.get("counts"),
        "rows":      rows,
    }


def _extract_period_check(warnings: List[Any]) -> Optional[Dict[str, Any]]:
    """Parse the bridge-emitted `period_invariant: before_from=N after_to=M`
    line from verification_warnings into a structured dict.

    The bridge emits several `period_invariant:` lines (requested range,
    first/last trade, and finally before/after counts). We must scan ALL
    matching lines and pick the one that actually contains the numeric
    `before_from=` / `after_to=` pair — returning early on the first
    match would mask the answer.
    """
    last_raw = None
    for w in warnings:
        if not isinstance(w, str):
            continue
        if "period_invariant" not in w:
            continue
        last_raw = w
        m = re.search(r"before_from=(-?\d+).*?after_to=(-?\d+)", w)
        if m:
            bf = int(m.group(1)); at = int(m.group(2))
            return {"before_from": bf, "after_to": at,
                    "ok": bf == 0 and at == 0}
    if last_raw is not None:
        return {"raw": last_raw, "ok": None}
    return None


# ---------------------------------------------------------------------------
# Cancellation.
#
# Pending jobs are owned by the UI/CLI process (bridge has not picked them up
# yet) — we move the dir from pending/<id>/ to cancelled/<id>/ ourselves and
# write a small cancellation marker.
#
# Running jobs are owned by the bridge — we drop a `cancel.flag` file inside
# running/<id>/ that the bridge's CancelFlagChecker polls. The bridge then
# moves the directory to cancelled/<id>/ at its earliest checkpoint.
#
# Already-terminal statuses (done/failed/cancelled) are no-ops.
# ---------------------------------------------------------------------------

def cancel_job(job_id: str) -> Dict[str, Any]:
    """Idempotent cancel. Returns {job_id, status, action}.

    action ∈ {"cancelled_immediately", "cancel_requested", "noop_terminal",
              "not_found"}.
    """
    job_id = _safe_job_id(job_id)
    located = find_job_dir(job_id)
    if not located:
        return {"job_id": job_id, "status": "missing",
                "action": "not_found"}
    status, jdir = located
    if status in ("done", "failed", "cancelled"):
        return {"job_id": job_id, "status": status,
                "action": "noop_terminal"}

    if status == "pending":
        target_parent = jobs_dir() / "cancelled"
        target_parent.mkdir(parents=True, exist_ok=True)
        dest = target_parent / job_id
        # Resolve a unique destination if a same-named dir already exists.
        if dest.exists():
            dest = target_parent / f"{job_id}__{utcnow_iso('ms').replace(':','').replace('-','')}"
        try:
            os.rename(str(jdir), str(dest))
        except OSError as e:
            raise JobValidationError(
                f"failed to move pending job to cancelled: {e}") from e
        # Drop a small marker so downstream readers see why it landed in
        # cancelled/ without having to infer it.
        marker = {
            "schema_version":   "0.1",
            "status":           "cancelled",
            "cancelled_at_utc": utcnow_iso("ms"),
            "reason":           "cancelled before bridge picked it up",
            "verification_warnings": ["cancelled by user"],
        }
        try:
            _atomic_write_text(dest / "result.json",
                               json.dumps(marker, ensure_ascii=False, indent=2))
        except OSError:
            pass
        return {"job_id": job_id, "status": "cancelled",
                "action": "cancelled_immediately"}

    # status == "running": drop cancel.flag for the bridge to notice.
    flag = jdir / "cancel.flag"
    try:
        _atomic_write_text_existing_parent(flag, utcnow_iso("ms"))
    except OSError as e:
        relocated = find_job_dir(job_id)
        if relocated and relocated[0] in ("done", "failed", "cancelled"):
            return {"job_id": job_id, "status": relocated[0],
                    "action": "noop_terminal"}
        raise JobValidationError(
            f"failed to write cancel.flag: {e}") from e
    return {"job_id": job_id, "status": "running",
            "action": "cancel_requested"}


def cancel_batch(batch_id: str) -> Dict[str, Any]:
    """Cancel every child job of a batch. Returns {batch_id, results: [...]}."""
    batch_id = _safe_batch_id(batch_id)
    p = batches_dir() / batch_id
    if not p.is_dir():
        return {"batch_id": batch_id, "results": [], "found": False}
    m = _read_json_safe(p / "batch.json") or {}
    results: List[Dict[str, Any]] = []
    for c in m.get("children") or []:
        jid = c.get("job_id")
        if not jid:
            continue
        try:
            results.append(cancel_job(jid))
        except JobValidationError as e:
            results.append({"job_id": jid, "action": "error",
                            "error": str(e)})
    return {"batch_id": batch_id, "found": True, "results": results,
            "total": len(results)}


def delete_job(job_id: str) -> Dict[str, Any]:
    """Permanently remove a single job directory (all statuses)."""
    job_id = _safe_job_id(job_id)
    found = find_job_dir(job_id)
    if found is None:
        return {"job_id": job_id, "deleted": False, "reason": "not_found"}
    status, p = found
    if status == "running":
        return {"job_id": job_id, "deleted": False, "reason": "running"}
    if is_report_favorite("job", job_id):
        return {"job_id": job_id, "deleted": False, "reason": "favorite"}
    job_doc = _read_json_safe(p / "job.json") or {}
    batch_id = ((job_doc.get("batch") or {}).get("batch_id")
                if isinstance(job_doc, dict) else None)
    if batch_id and is_report_favorite("batch", str(batch_id)):
        return {"job_id": job_id, "deleted": False,
                "reason": "favorite_parent_batch", "batch_id": batch_id}
    shutil.rmtree(p, ignore_errors=True)
    return {"job_id": job_id, "deleted": True, "status": status}


def delete_batch(batch_id: str) -> Dict[str, Any]:
    """Permanently remove a batch directory and all its child job directories."""
    batch_id = _safe_batch_id(batch_id)
    p = _safe_child_path(batches_dir(), batch_id, "batch_id")
    if not p.is_dir():
        return {"batch_id": batch_id, "deleted": False, "reason": "not_found"}
    if is_report_favorite("batch", batch_id):
        return {"batch_id": batch_id, "deleted": False, "reason": "favorite"}
    m = _read_json_safe(p / "batch.json") or {}
    favorite_jobs: List[str] = []
    for c in m.get("children") or []:
        if not isinstance(c, dict):
            continue
        jid = c.get("job_id")
        if jid and is_report_favorite("job", jid):
            favorite_jobs.append(jid)
    if favorite_jobs:
        return {"batch_id": batch_id, "deleted": False,
                "reason": "has_favorite_jobs", "favorites": favorite_jobs}
    # Delete child jobs first (any status except running → skip).
    deleted_jobs: List[str] = []
    skipped_jobs: List[str] = []
    for c in m.get("children") or []:
        jid = c.get("job_id")
        if not jid:
            continue
        found = find_job_dir(jid)
        if found is None:
            continue
        status, jpath = found
        if status == "running":
            skipped_jobs.append(jid)
            continue
        shutil.rmtree(jpath, ignore_errors=True)
        deleted_jobs.append(jid)
    if skipped_jobs:
        # One or more child jobs are running: don't remove the batch dir.
        return {"batch_id": batch_id, "deleted": False,
                "reason": "has_running_jobs", "skipped": skipped_jobs}
    shutil.rmtree(p, ignore_errors=True)
    return {"batch_id": batch_id, "deleted": True,
            "deleted_jobs": deleted_jobs}
