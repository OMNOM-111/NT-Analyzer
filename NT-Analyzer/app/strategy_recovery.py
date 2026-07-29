"""Evidence-bound recovery of an archived NinjaTrader strategy.

This module is intentionally narrower than the generic AI executor.  It can
only restore an exact class/profile pair from the reversible production
quarantine, prove NinjaTrader compilation, and enqueue two predefined research
runs (OOS and slippage stress).  Model prose never supplies paths or commands.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from . import jobqueue, runtime_env
from .ai_lab import compile_pipeline, paths


_CLASS_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")


class StrategyRecoveryError(RuntimeError):
    """A recovery precondition failed before a trustworthy test was queued."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _run_id(task_id: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9]+", "", str(task_id or ""))[-12:] or "task"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"recovery_{safe}_{stamp}_{uuid.uuid4().hex[:6]}"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _manifest(root: Path) -> Dict[str, str]:
    return {
        path.name: _sha256(path)
        for path in sorted(root.iterdir())
        if path.is_file() and path.suffix.lower() in {".cs", ".md"}
    }


def _candidate_roots(record: Dict[str, Any], class_name: str) -> List[Path]:
    quarantine_root = (paths.PROJECT_ROOT / "ninjatrader" / "strategies" / "_quarantine").resolve()
    roots: List[Path] = []
    for raw in record.get("source_paths") or []:
        source = Path(str(raw or ""))
        try:
            resolved = source.resolve()
            resolved.relative_to(quarantine_root)
        except (OSError, ValueError):
            continue
        search_root = resolved if resolved.is_dir() else resolved.parent
        candidates = [search_root, *[path.parent for path in search_root.rglob(f"{class_name}.cs")]]
        for candidate in candidates:
            if (candidate / f"{class_name}.cs").is_file() and candidate not in roots:
                roots.append(candidate)
    return roots


def exact_source(record: Dict[str, Any], class_name: str, profile_id: str) -> Tuple[Path, Dict[str, str]]:
    """Return one verified source tree; reject mismatching quarantine copies."""
    if not _CLASS_RE.fullmatch(str(class_name or "")):
        raise StrategyRecoveryError("Некорректное имя класса стратегии.")
    if str(record.get("class_name") or "") != class_name:
        raise StrategyRecoveryError("Класс в карантине не совпадает с поручением.")
    recorded_profile = str(record.get("profile_id") or "")
    if profile_id and recorded_profile not in {"", profile_id}:
        raise StrategyRecoveryError("Профиль в карантине не совпадает с поручением.")
    roots = _candidate_roots(record, class_name)
    if not roots:
        raise StrategyRecoveryError("Точная копия исходника в карантине не найдена.")
    manifests = [_manifest(root) for root in roots]
    # Removal can nest the repository and NinjaTrader copies under one folder.
    # They must be byte-identical before either is trusted as the source.
    baseline = manifests[0]
    if not baseline or any(manifest != baseline for manifest in manifests[1:]):
        raise StrategyRecoveryError("Сохранённые копии исходника различаются; автоматическое восстановление остановлено.")
    source = max(roots, key=lambda root: len(root.parts))
    main_text = (source / f"{class_name}.cs").read_text(encoding="utf-8-sig", errors="replace")
    if not re.search(rf"\bclass\s+{re.escape(class_name)}\b", main_text):
        raise StrategyRecoveryError("В исходнике не подтверждён ожидаемый класс стратегии.")
    return source, baseline


def _restore_destinations(class_name: str) -> List[Path]:
    return [
        paths.PROJECT_ROOT / "ninjatrader" / "strategies" / class_name,
        paths.nt_custom_dir() / "Strategies" / class_name,
    ]


def _copy_verified_tree(source: Path, manifest: Dict[str, str], destination: Path,
                        run_id: str) -> Tuple[bool, Path]:
    if destination.exists():
        if destination.is_dir() and _manifest(destination) == manifest:
            return False, destination
        raise StrategyRecoveryError(
            f"В каталоге {destination.name} уже есть другая версия; перезапись запрещена."
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = destination.with_name(f".{destination.name}.{run_id}.tmp")
    if staging.exists():
        shutil.rmtree(staging)
    shutil.copytree(source, staging)
    if _manifest(staging) != manifest:
        shutil.rmtree(staging, ignore_errors=True)
        raise StrategyRecoveryError("Хэш восстановленной копии не совпал с карантином.")
    os.replace(staging, destination)
    return True, destination


def _rollback_created(rows: Iterable[Tuple[bool, Path]], manifest: Dict[str, str]) -> None:
    for created, destination in reversed(list(rows)):
        if not created or not destination.is_dir():
            continue
        # Never delete a path that changed after we created it.
        if _manifest(destination) == manifest:
            shutil.rmtree(destination, ignore_errors=True)


def _audit_path(run_id: str) -> Path:
    return runtime_env.data_path(
        "operations", "strategy-recovery", f"{run_id}.json",
        project_root=paths.PROJECT_ROOT,
    )


def _write_audit(run_id: str, document: Dict[str, Any]) -> None:
    path = _audit_path(run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(document, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    os.replace(tmp, path)


def _timeframe(profile: Dict[str, Any]) -> Tuple[str, int]:
    text = str(profile.get("timeframe") or "5 Minute").strip()
    match = re.search(r"(\d+)\s*([A-Za-zА-Яа-я]+)", text)
    value = int(match.group(1)) if match else 5
    unit = (match.group(2) if match else "Minute").lower()
    kind = "Second" if unit.startswith(("sec", "сек")) else "Day" if unit.startswith(("day", "дн")) else "Minute"
    return kind, value


def _oos_period(profile: Dict[str, Any]) -> Tuple[str, str]:
    period = profile.get("test_period") if isinstance(profile.get("test_period"), dict) else {}
    end = str(period.get("to_utc") or "2025-12-31T00:00:00Z")
    # Existing production profiles name the hold-out explicitly as OOS 2025.
    # Keep its exact boundary and never infer it from a model response.
    return "2025-01-01T00:00:00Z", end


def _enqueue_validation_jobs(profile: Dict[str, Any], class_name: str, run_id: str,
                             task_id: str) -> List[str]:
    instrument = str(profile.get("instrument") or "").strip()
    if not instrument:
        raise StrategyRecoveryError("В профиле не указан точный контракт для проверки.")
    period_from, period_to = _oos_period(profile)
    bars_type, bars_value = _timeframe(profile)
    execution = profile.get("execution") if isinstance(profile.get("execution"), dict) else {}
    base_parameters = dict(profile.get("locked_parameters") or {})
    base_slippage = max(1, int(execution.get("slippage_ticks") or base_parameters.get("SlippageTicks") or 1))
    variants = [("oos", base_slippage), ("stress", max(2, base_slippage + 1))]
    created: List[str] = []
    try:
        for label, slippage in variants:
            parameters = dict(base_parameters)
            if "SlippageTicks" in parameters:
                parameters["SlippageTicks"] = slippage
            request = jobqueue.CreateJobRequest(
                class_name=class_name,
                instrument=instrument,
                bars_period_type=bars_type,
                bars_period_value=bars_value,
                from_utc=period_from,
                to_utc=period_to,
                parameters=parameters,
                calculate=str(execution.get("calculate") or "OnBarClose"),
                order_fill_resolution=str(execution.get("order_fill_resolution") or "High"),
                slippage_ticks=slippage,
                commission=0.0,
                commission_template=str(execution.get("commission_template") or "None"),
                session_template=str(execution.get("session_template") or "CME US Index Futures RTH"),
                timezone="UTC",
                job_id=jobqueue.gen_job_id(f"{run_id}_{label}"),
                role="research",
                origin={
                    "kind": "approved_strategy_recovery",
                    "recovery_run_id": run_id,
                    "task_id": str(task_id or ""),
                    "profile_id": str(profile.get("profile_id") or ""),
                    "variant": label,
                },
            )
            job_id, _ = jobqueue.create_job(request)
            created.append(job_id)
    except Exception as exc:
        for job_id in created:
            try:
                jobqueue._try_remove_pending_job(job_id)  # atomic rollback before Bridge claim
            except Exception:
                pass
        raise StrategyRecoveryError(f"Не удалось создать проверочные прогоны: {exc}") from exc
    return created


def begin(profile: Dict[str, Any], quarantine_record: Dict[str, Any], *,
          task_id: str, compile_wait_sec: int = 300) -> Dict[str, Any]:
    """Restore, compile and enqueue evidence jobs for an approved task."""
    if (
        runtime_env.app_env() == runtime_env.STAGING
        or (runtime_env.is_production() and runtime_env.environment_explicit())
    ):
        raise StrategyRecoveryError(
            "Восстановление исходников NinjaTrader запрещено в выбранном окружении."
        )
    class_name = str(profile.get("strategy_class") or "")
    profile_id = str(profile.get("profile_id") or "")
    run_id = _run_id(task_id)
    audit: Dict[str, Any] = {
        "schema_version": 1,
        "run_id": run_id,
        "task_id": str(task_id or ""),
        "profile_id": profile_id,
        "class_name": class_name,
        "started_at_utc": _now(),
        "status": "validating_source",
    }
    source, manifest = exact_source(quarantine_record, class_name, profile_id)
    audit["source"] = str(source)
    audit["source_manifest"] = manifest
    baseline = compile_pipeline.capture_dll_baseline()
    restored: List[Tuple[bool, Path]] = []
    try:
        for destination in _restore_destinations(class_name):
            restored.append(_copy_verified_tree(source, manifest, destination, run_id))
        audit["restored_paths"] = [str(path) for _, path in restored]
        audit["status"] = "compiling"
        _write_audit(run_id, audit)
        compile_result = compile_pipeline.run_compile_chain(
            run_id, class_name, baseline_mtime=baseline,
            dll_wait_sec=max(5, int(compile_wait_sec)), catalog_wait_sec=30,
        )
        audit["compile"] = compile_result
        if not compile_result.get("ok"):
            _rollback_created(restored, manifest)
            audit["status"] = "compile_failed_rolled_back"
            audit["finished_at_utc"] = _now()
            _write_audit(run_id, audit)
            return {
                "ok": False, "run_id": run_id, "reason": "compile_not_confirmed",
                "compile": compile_result,
            }
        job_ids = _enqueue_validation_jobs(profile, class_name, run_id, task_id)
        audit["status"] = "tests_queued"
        audit["job_ids"] = job_ids
        audit["finished_at_utc"] = _now()
        _write_audit(run_id, audit)
        return {
            "ok": True, "run_id": run_id, "job_ids": job_ids,
            "restored_paths": [str(path) for _, path in restored],
            "compile": compile_result,
        }
    except StrategyRecoveryError as exc:
        _rollback_created(restored, manifest)
        audit["status"] = "blocked_rolled_back"
        audit["error"] = str(exc)
        audit["finished_at_utc"] = _now()
        _write_audit(run_id, audit)
        return {"ok": False, "run_id": run_id, "reason": "recovery_blocked", "error": str(exc)}
    except Exception as exc:
        _rollback_created(restored, manifest)
        audit["status"] = "failed_rolled_back"
        audit["error"] = str(exc)[:1000]
        audit["finished_at_utc"] = _now()
        _write_audit(run_id, audit)
        return {"ok": False, "run_id": run_id, "reason": "recovery_failed", "error": str(exc)[:1000]}
