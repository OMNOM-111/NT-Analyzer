"""Route a canonical backtest job to the NinjaTrader the server cannot reach.

There is one product, not two. The browser posts a backtest to ``/api/jobs``
and reads it back from the report API, exactly as it always has; what differs
is only how the job reaches NinjaTrader. Development runs beside it and drops
the job in the local queue. A server has no NinjaTrader of its own, so the same
canonical job travels to the enrolled Connector as a ``run_backtest`` command
and comes back as the same report.

Keeping that difference here rather than in the page is the point. A browser
that decided "I am Production, so I call a Connector command" would grow a
second backtest with its own status model and its own report, and the two would
drift until they were different products.

Nothing in this module relaxes the Connector contract. The command is queued
through the same path every paper command uses, so workspace scope, capability,
idempotency, sequence and expiry are enforced unchanged, and the payload is a
strict projection of a job the canonical validator has already accepted.
"""
from __future__ import annotations

import json
import re
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple

from . import runtime_env


COMMAND = "run_backtest"
CANCEL_COMMAND = "cancel_backtest"
CAPABILITY = "paper_commands"

# What may cross to the Connector. A strict projection, not a filter of a
# larger object: a field that is not named here cannot reach NinjaTrader, so
# no path, assembly, file reference or free-form type name can ride along with
# a backtest request.
JOB_FIELDS = (
    "schema_version", "job_id", "kind", "instrument", "created_at_utc",
    "timeframe", "period", "execution",
)

# Risk profile travels flattened. The stored document nests a margin_source
# block whose own "source" key the command validator forbids outright, and the
# strategy never reads it there anyway: capital and margin reach the run through
# strategy.parameters. Projecting the scalars keeps the run identical and keeps
# a nested shape from carrying a name the transport refuses.
RISK_FIELDS = (
    "mode", "currency", "starting_capital", "intraday_only", "status",
)
STRATEGY_FIELDS = ("class_name", "parameters")

# A NinjaScript class name, and nothing that could be read as a path, a
# namespace-qualified type or an expression. The AddOn additionally resolves it
# through its own whitelist, so this is the outer of two gates rather than the
# only one.
_CLASS_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{2,63}$")

MAX_PARAMETERS = 200
MAX_PARAMETER_NAME = 64
MAX_PARAMETER_VALUE = 256
MAX_TRADES_IN_RESULT = 200

# A freshly-created pending directory is the job currently being dispatched,
# or a concurrent request doing the same thing.  Treating every directory that
# does not have dispatch.json *yet* as legacy races the ordinary create ->
# queue -> record sequence and cancels real UI runs before the Connector can
# collect them.  Five minutes is the protocol's bounded delivery window; after
# it elapses an unrecorded job can no longer be an in-flight dispatch and is
# safe to close with the explicit legacy reason.
UNDISPATCHED_RECOVERY_GRACE_SEC = 300.0


class BacktestDispatchError(RuntimeError):
    """The job cannot be routed to a Connector, stated in plain terms."""


def routes_through_connector() -> bool:
    """Whether a backtest here has to travel to reach NinjaTrader.

    Decided by where the code runs, not by what happens to be enrolled -- the
    same rule the runtime reads follow, so a Development machine with a
    Connector of its own still uses its local queue.
    """
    return runtime_env.deployment_environment() in {
        runtime_env.CANARY, runtime_env.PRODUCTION,
    }


def _scalar(value: Any) -> Any:
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float)):
        return value
    text = str(value)
    if len(text) > MAX_PARAMETER_VALUE:
        raise BacktestDispatchError("Значение параметра стратегии превышает лимит.")
    return text


def _parameters(raw: Any) -> Dict[str, Any]:
    if not isinstance(raw, Mapping):
        return {}
    if len(raw) > MAX_PARAMETERS:
        raise BacktestDispatchError("Слишком много параметров стратегии.")
    clean: Dict[str, Any] = {}
    for name, value in raw.items():
        key = str(name)
        if not key or len(key) > MAX_PARAMETER_NAME:
            raise BacktestDispatchError("Некорректное имя параметра стратегии.")
        if isinstance(value, (Mapping, list, tuple, set)):
            raise BacktestDispatchError(
                "Параметр стратегии должен быть скаляром."
            )
        clean[key] = _scalar(value)
    return clean


def command_payload(job_doc: Mapping[str, Any]) -> Dict[str, Any]:
    """Project an already-validated job into the Connector command payload."""
    if not isinstance(job_doc, Mapping):
        raise BacktestDispatchError("Job document отсутствует.")
    strategy = job_doc.get("strategy")
    if not isinstance(strategy, Mapping):
        raise BacktestDispatchError("Job document не содержит стратегию.")
    class_name = str(strategy.get("class_name") or "")
    if not _CLASS_NAME_RE.fullmatch(class_name):
        raise BacktestDispatchError(
            "Имя класса стратегии недопустимо для удалённого запуска."
        )
    job: Dict[str, Any] = {
        field: job_doc[field] for field in JOB_FIELDS if field in job_doc
    }
    job["strategy"] = {
        "class_name": class_name,
        "parameters": _parameters(strategy.get("parameters")),
    }
    risk = job_doc.get("risk_profile")
    if isinstance(risk, Mapping):
        flattened = {
            field: _scalar(risk[field]) for field in RISK_FIELDS if field in risk
        }
        if flattened:
            job["risk_profile"] = flattened
    return {"command": COMMAND, "job": job}


# --------------------------------------------------------------------------- #
# Bringing a result home as an ordinary report.
# --------------------------------------------------------------------------- #
def _trades(raw: Any) -> list:
    if not isinstance(raw, list):
        return []
    return [row for row in raw[:MAX_TRADES_IN_RESULT] if isinstance(row, Mapping)]


def trade_transfer(safe_result: Mapping[str, Any]) -> Dict[str, Any]:
    """How many trades the run had, and how many actually crossed.

    A strategy may produce thousands of trades and the result channel is 16
    KiB. Letting the payload simply outgrow that would turn a successful
    backtest into a transport error, and silently keeping the first N would be
    worse: the report would show a real number of trades that is not the run's
    number, and every metric derived from it would look sound.

    So the count is carried separately from the rows, and truncation is stated.
    """
    rows = _trades(safe_result.get("trades"))
    declared = safe_result.get("trades_total")
    try:
        total = int(declared)
    except (TypeError, ValueError):
        total = len(rows)
    total = max(total, len(rows))
    truncated = bool(safe_result.get("trades_truncated")) or total > len(rows)
    return {
        "trades_total": total,
        "trades_transferred": len(rows),
        "trades_truncated": truncated,
    }


def result_document(job_doc: Mapping[str, Any],
                    safe_result: Mapping[str, Any]) -> Dict[str, Any]:
    """The canonical result.json a report is rendered from.

    The same schema the local runner writes, so the report API, the reports
    table and the drawer need to know nothing about where the run happened.

    The price series is deliberately absent. NinjaTrader ran the backtest on
    the historical bars it holds, and this server does not have those exact
    bars; drawing the chart from the live market-data channel instead would
    produce a picture that does not belong to the run it claims to show. The
    trades and the metrics are the real ones, and the report says outright that
    the series was not transferred.
    """
    metrics = safe_result.get("metrics")
    # The Connector protocol forbids the generic field name `source` anywhere
    # on the wire. The device therefore sends `execution_details`; only after
    # the strict result validator accepts it do we restore the canonical report
    # field expected by the existing report UI. Keep the fallback for local
    # materialization/tests that never crossed the protocol boundary.
    source = safe_result.get("execution_details")
    if not isinstance(source, Mapping):
        source = safe_result.get("source")
    document: Dict[str, Any] = {
        "schema_version": "0.1",
        "job_id": str(job_doc.get("job_id") or ""),
        "run_hash": str(safe_result.get("run_hash") or ""),
        "started_at_utc": str(safe_result.get("started_at_utc") or ""),
        "finished_at_utc": str(safe_result.get("finished_at_utc") or ""),
        "duration_ms": safe_result.get("duration_ms"),
        "source": dict(source) if isinstance(source, Mapping) else {},
        "metrics": dict(metrics) if isinstance(metrics, Mapping) else {},
        "trades": _trades(safe_result.get("trades")),
        "trade_transfer": trade_transfer(safe_result),
        "artifacts": {
            "price_series": "not_transferred",
            "price_series_reason": (
                "Backtest выполнен на сервере через Connector: ценовой ряд "
                "остался на машине NinjaTrader и не передавался."
            ),
        },
        "result_command_id": str(safe_result.get("command_id") or ""),
        "verification_warnings": [
            str(item)[:400]
            for item in (safe_result.get("verification_warnings") or [])[:200]
        ],
    }
    document["source"].setdefault("execution_source", "ninjatrader")
    document["source"].setdefault("execution_transport", "production_connector")
    return document


def materialize(job_dir: Path, job_doc: Mapping[str, Any],
                safe_result: Mapping[str, Any]) -> Dict[str, Any]:
    """Write the canonical report artifacts beside the job."""
    document = result_document(job_doc, safe_result)
    payload = json.dumps(document, ensure_ascii=False, indent=2)
    (job_dir / "result.json").write_text(payload, encoding="utf-8")
    (job_dir / "raw.json").write_text(payload, encoding="utf-8")
    (job_dir / "trades.json").write_text(
        json.dumps(document["trades"], ensure_ascii=False), encoding="utf-8",
    )
    return document


class ConflictingResultError(RuntimeError):
    """A second, different terminal result arrived for one job."""


def existing_result(job_dir: Path) -> Dict[str, Any]:
    try:
        return json.loads((job_dir / "result.json").read_text(encoding="utf-8"))
    except Exception:
        return {}


def result_fingerprint(document: Mapping[str, Any]) -> str:
    """What makes two results the same result.

    Deliberately the outcome rather than the whole document: timestamps of the
    delivery differ between a send and its retry, and treating that as a
    conflict would turn an ordinary network retry into an alarm.
    """
    metrics = document.get("metrics") if isinstance(document.get("metrics"), Mapping) else {}
    transfer = document.get("trade_transfer") if isinstance(document.get("trade_transfer"), Mapping) else {}
    return json.dumps(
        {
            "job_id": document.get("job_id") or "",
            "run_hash": document.get("run_hash") or "",
            "metrics": {key: metrics[key] for key in sorted(metrics)},
            "trades_total": transfer.get("trades_total"),
        },
        ensure_ascii=False, sort_keys=True,
    )


def settle(jobs_root: Path, job_id: str, status: str,
           safe_result: Mapping[str, Any]) -> Dict[str, Any]:
    """Apply one device-reported status to the canonical job, exactly once.

    ``submit_result`` can be retried after a network failure, so the same
    terminal result may arrive twice. One job must produce one report and one
    terminal transition: a repeat of the same outcome is a no-op that returns
    the report already on disk, and a *different* terminal outcome for a job
    that has already finished is refused and audited rather than silently
    overwriting what was reported.

    A job the operator cancelled stays cancelled. A late result must not
    resurrect it as done.
    """
    located = locate(jobs_root, job_id)
    if located is None:
        return {"action": "unknown_job", "job_id": job_id}
    current, job_dir = located

    if status == "accepted":
        # The device has the work. It has not started it, and saying otherwise
        # would show "выполняется" for a Connector that has gone silent.
        return {"action": "acknowledged", "status": current, "job_id": job_id}

    if status == "running":
        if current != "pending":
            # A job already in cancel_requested stays there: the device having
            # started is not news that changes what the operator asked for.
            return {"action": "noop", "status": current, "job_id": job_id}
        move_job(job_dir, jobs_root, "running")
        return {"action": "started", "status": "running", "job_id": job_id}

    if status == "cancelled":
        # The device reached a boundary its runner could honour and stopped
        # there. This is the only thing that makes a job cancelled.
        if current in {"done", "failed", "cancelled"}:
            return {"action": "noop_terminal", "status": current, "job_id": job_id}
        move_job(job_dir, jobs_root, "cancelled")
        write_cancelled_marker(jobs_root / "cancelled" / job_id,
                               "runner stopped at a cancellation boundary")
        return {"action": "cancelled", "status": "cancelled", "job_id": job_id}

    if status not in {"completed", "failed", "rejected"}:
        return {"action": "ignored", "status": current, "job_id": job_id}

    if current == "cancelled":
        return {"action": "stays_cancelled", "status": "cancelled", "job_id": job_id}

    job_doc = read_job_document(job_dir)
    if status == "completed":
        incoming = result_document(job_doc, safe_result)
    else:
        incoming = None

    if current in {"done", "failed"}:
        previous = existing_result(job_dir)
        if incoming is not None and previous:
            if result_fingerprint(previous) == result_fingerprint(incoming):
                return {"action": "duplicate", "status": current, "job_id": job_id}
            raise ConflictingResultError(
                f"job {job_id} already finished as {current} with a different result",
            )
        return {"action": "duplicate", "status": current, "job_id": job_id}

    if status == "completed":
        materialize(job_dir, job_doc, safe_result)
        move_job(job_dir, jobs_root, "done")
        if current == "cancel_requested":
            # The run finished before any boundary could take effect. The
            # result is real and is kept; presenting it as a cancellation
            # would be a lie in the other direction.
            return {"action": "cancel_race_completed_before_abort_boundary",
                    "status": "done", "job_id": job_id}
        return {"action": "completed", "status": "done", "job_id": job_id}

    fail_job(jobs_root, job_id,
             str(safe_result.get("message") or "backtest failed on NinjaTrader"))
    return {"action": "failed", "status": "failed", "job_id": job_id}


def write_cancelled_marker(job_dir: Path, reason: str) -> None:
    """Say why a job landed in cancelled/ without making a reader infer it."""
    try:
        (job_dir / "result.json").write_text(json.dumps({
            "schema_version": "0.1",
            "status": "cancelled",
            "cancelled_at_utc": datetime.now(timezone.utc).isoformat(
                timespec="milliseconds").replace("+00:00", "Z"),
            "reason": reason,
            "verification_warnings": ["cancelled by user"],
        }, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def record_dispatch(job_dir: Path, *, command_id: str, connection_id: str,
                    idempotency_key: str, queued_at_utc: str) -> None:
    """Leave proof beside the job that it was handed to a device.

    Without it a job sitting in pending is ambiguous: it may be waiting for a
    device that has it, or it may predate dispatch entirely and be waiting for
    nothing. That difference decides whether an operator should keep waiting.
    """
    try:
        (job_dir / "dispatch.json").write_text(
            json.dumps({
                "transport": "production_connector",
                "command_id": command_id,
                "connection_id": connection_id,
                "idempotency_key": idempotency_key,
                "queued_at_utc": queued_at_utc,
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass


def dispatch_record(job_dir: Path) -> Dict[str, Any]:
    try:
        return json.loads((job_dir / "dispatch.json").read_text(encoding="utf-8"))
    except Exception:
        return {}


def recover_undispatched(
    jobs_root: Path,
    *,
    min_age_sec: float = UNDISPATCHED_RECOVERY_GRACE_SEC,
) -> list:
    """Close out jobs that were queued before a transport existed.

    A job created when this environment had no way to reach NinjaTrader will
    never run: nothing was told about it and nothing ever will be. Leaving it
    in pending shows the operator a queue that is not moving for a reason the
    queue cannot express, so it is moved to a terminal state that says exactly
    what happened, rather than deleted as if it had never been asked for.
    """
    recovered = []
    pending_root = jobs_root / "pending"
    if not pending_root.is_dir():
        return recovered
    for job_dir in sorted(pending_root.iterdir()):
        if not job_dir.is_dir() or job_dir.name.startswith("."):
            continue
        if dispatch_record(job_dir):
            continue
        try:
            job_mtime = (job_dir / "job.json").stat().st_mtime
            age_sec = max(0.0, time.time() - job_mtime)
        except OSError:
            # A concurrently-created directory whose job document is not yet
            # visible is not legacy evidence.  The next bounded sweep can
            # reconsider it once creation has settled.
            continue
        if age_sec < max(0.0, float(min_age_sec)):
            continue
        try:
            (job_dir / "result.json").write_text(
                json.dumps({
                    "schema_version": "0.1",
                    "job_id": job_dir.name,
                    "metrics": {},
                    "trades": [],
                    "error": (
                        "Задача создана до появления серверной отправки в "
                        "NinjaTrader и никогда не была передана устройству "
                        "(legacy pre-dispatch job)."
                    ),
                    "source": {"execution_transport": "none"},
                }, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            continue
        move_job(job_dir, jobs_root, "cancelled")
        recovered.append(job_dir.name)
    return recovered


def cancel_payload(job_id: str) -> Dict[str, Any]:
    """The command that stops a run already handed to the device."""
    return {"command": CANCEL_COMMAND, "job": {"job_id": str(job_id)}}


def move_job(job_dir: Path, jobs_root: Path, status: str) -> Path:
    """Move a job directory into its canonical status directory.

    Status stays the ordinary pending/running/done/failed a report already
    understands. The Connector's own command lifecycle is an implementation
    detail of the transport and never reaches the browser.
    """
    if status not in {"pending", "running", "cancel_requested",
                      "done", "failed", "cancelled"}:
        raise BacktestDispatchError(f"Недопустимый статус задачи: {status}")
    if status in {"done", "failed", "cancelled"}:
        # cancel.flag is how a *local* AddOn is asked to stop; it means nothing
        # once the job is over. Leaving it behind makes a finished report look
        # like it is still being cancelled, and a recovered directory carry a
        # request nobody will ever read.
        try:
            (job_dir / "cancel.flag").unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass
    target_parent = jobs_root / status
    target_parent.mkdir(parents=True, exist_ok=True)
    destination = target_parent / job_dir.name
    if destination.resolve() == job_dir.resolve():
        return job_dir
    if destination.exists():
        shutil.rmtree(destination, ignore_errors=True)
    shutil.move(str(job_dir), str(destination))
    return destination


def fail_job(jobs_root: Path, job_id: str, reason: str) -> Optional[Path]:
    """Record why a job could not run, and stop it waiting for a device.

    A dispatch that failed must not leave the job sitting in pending against a
    NinjaTrader that will never be told about it: the operator would watch a
    queue that is not a queue.
    """
    located = locate(jobs_root, job_id)
    if located is None:
        return None
    _, job_dir = located
    try:
        (job_dir / "result.json").write_text(
            json.dumps({
                "schema_version": "0.1",
                "job_id": job_id,
                "metrics": {},
                "trades": [],
                "error": str(reason)[:800],
                "source": {"execution_transport": "production_connector"},
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass
    return move_job(job_dir, jobs_root, "failed")


def read_job_document(job_dir: Path) -> Dict[str, Any]:
    try:
        return json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
    except Exception:
        return {}


def locate(jobs_root: Path, job_id: str) -> Optional[Tuple[str, Path]]:
    for status in ("running", "cancel_requested", "pending",
                   "done", "failed", "cancelled"):
        candidate = jobs_root / status / job_id
        if candidate.is_dir():
            return status, candidate
    return None
