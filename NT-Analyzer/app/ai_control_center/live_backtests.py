"""Local-owner projection of the existing NinjaTrader job/report authority.

No worker, LLM, strategy generator, report ledger or permission system lives here.
The caller supplies fresh admission and (optionally) the existing transport
dispatcher. Completion publication is an idempotent callback to the existing
SF Chat store, invoked by its existing monitor, never by read-only projections.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid5

from .. import jobqueue, preview_sandbox, runtime_env
from .contracts import ActorKind, Environment, RequestContext
from .states import ContractError


_NAMESPACE = UUID("7a9c6d55-40fc-45ae-8a09-472d613526e8")
_SUBMIT_LOCK = threading.RLock()  # one Local process; not a distributed job lock
_HEX = re.compile(r"^(?:sha256:)?[0-9a-f]{64}$")
_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$")
MAX_PERIOD = timedelta(days=31)
MAX_SOURCE_BYTES = 32 * 1024 * 1024
_TERMINAL = {"done", "failed", "cancelled"}
_PERSONA = {"id": "tolik", "key": "tolik", "display_name": "Толик",
            "role": "Бэктестирование", "role_key": "backtest_researcher", "avatar_key": "tolik",
            "synthetic": False}


def _canonical(value) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
                          allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, OverflowError):
        raise ContractError("live_backtest_invalid_spec") from None


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _number(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def _valid_bars(rows, period):
    if not isinstance(rows, list) or not rows:
        return False
    try:
        start, end, previous = _utc(period["from_utc"]), _utc(period["to_utc"]), None
        for row in rows:
            if not isinstance(row, dict) or not all(_number(row.get(key)) for key in ("o", "h", "l", "c", "v")):
                return False
            at = _utc(row.get("t"))
            if (not start <= at <= end or previous is not None and at < previous
                    or row["v"] < 0 or row["h"] < max(row["o"], row["c"], row["l"])
                    or row["l"] > min(row["o"], row["c"], row["h"])):
                return False
            previous = at
        return True
    except (ContractError, KeyError, TypeError):
        return False


def _valid_trades(rows, period):
    if not isinstance(rows, list):
        return False
    try:
        start, end = _utc(period["from_utc"]), _utc(period["to_utc"])
        for row in rows:
            if (not isinstance(row, dict) or row.get("direction") not in {"long", "short"}
                    or type(row.get("quantity")) is not int or row["quantity"] <= 0
                    or not all(_number(row.get(key)) for key in ("entry_price", "exit_price", "pnl_currency"))
                    or not start <= _utc(row.get("entry_time_utc")) <= _utc(row.get("exit_time_utc")) <= end):
                return False
        return True
    except (ContractError, KeyError, TypeError):
        return False


def _token(value, code):
    if not isinstance(value, str) or not _TOKEN.fullmatch(value):
        raise ContractError(code)
    return value


def _utc(value):
    try:
        if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", value):
            raise ValueError
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        raise ContractError("live_backtest_explicit_utc_period_required") from None


def _spec(value):
    required = {"class_name", "instrument", "from_utc", "to_utc", "bars_period_type",
                "bars_period_value", "session_template", "commission_template", "slippage_ticks"}
    if not isinstance(value, dict) or not required <= value.keys() or value.keys() - required - {"parameters", "risk_profile"}:
        raise ContractError("live_backtest_explicit_spec_required")
    result = json.loads(_canonical(value))
    result.setdefault("parameters", {})
    result.setdefault("risk_profile", {})
    if not isinstance(result["parameters"], dict) or len(result["parameters"]) > 128 or not isinstance(result["risk_profile"], dict):
        raise ContractError("live_backtest_invalid_parameters")
    if len(_canonical(result)) > 32_768:
        raise ContractError("live_backtest_invalid_spec")
    for key, item in result["parameters"].items():
        if (not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", key)
                or type(item) not in (str, int, float, bool)
                or isinstance(item, str) and len(item) > 256):
            raise ContractError("live_backtest_invalid_parameters")
    for key in ("class_name", "instrument", "session_template", "commission_template"):
        if (not isinstance(result[key], str) or not result[key].strip() or len(result[key]) > 128
                or any(ord(char) < 32 for char in result[key])):
            raise ContractError("live_backtest_invalid_spec")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{2,126}", result["class_name"]):
        raise ContractError("live_backtest_registered_strategy_required")
    period = _utc(result["to_utc"]) - _utc(result["from_utc"])
    if period <= timedelta(0) or period > MAX_PERIOD:
        raise ContractError("live_backtest_period_limit")
    if (result["bars_period_type"] not in {"Minute", "Day", "Tick", "Second", "Volume"}
            or type(result["bars_period_value"]) is not int or not 1 <= result["bars_period_value"] <= 1440
            or type(result["slippage_ticks"]) is not int or not 1 <= result["slippage_ticks"] <= 100):
        raise ContractError("live_backtest_invalid_timeframe_or_slippage")
    return result


class LiveBacktestService:
    """Real jobs are the source of truth; Task UUIDs are stable projections."""

    def __init__(self, *, queue=None):
        self.queue = queue if queue is not None else jobqueue

    @staticmethod
    def _access(context, source_scope, chat_scope, admit):
        if (not isinstance(context, RequestContext) or context.scope.environment != Environment.DEVELOPMENT
                or not runtime_env.is_development() or preview_sandbox.enabled()
                or context.actor.kind != ActorKind.HUMAN):
            raise ContractError("live_backtest_local_owner_required")
        if not isinstance(source_scope, dict) or not isinstance(chat_scope, dict) or not callable(admit):
            raise ContractError("live_backtest_server_scope_required")
        uid = source_scope.get("user_id")
        if (type(uid) is not int or uid <= 0 or source_scope.get("workspace_id") != context.scope.workspace_id
                or chat_scope.get("workspace_id") != context.scope.workspace_id
                or str(chat_scope.get("user_id") or "") != str(uid)
                or str(chat_scope.get("user_uuid") or "") != str(context.user_uuid)
                or chat_scope.get("is_owner") is not True or chat_scope.get("uses_owner_runtime") is not True):
            raise ContractError("live_backtest_owner_scope_mismatch")
        if admit() is False:
            raise ContractError("live_backtest_admission_denied")
        return {"workspace_id": context.scope.workspace_id, "user_id": uid, "allow_legacy": False}

    def _registered(self, spec):
        catalog = self.queue.read_strategies_catalog() or {}
        entries = [entry for entry in catalog.get("strategies", [])
                   if isinstance(entry, dict) and entry.get("class_name") == spec["class_name"]]
        if len(entries) != 1 or spec["class_name"] not in self.queue.whitelisted_strategies():
            raise ContractError("live_backtest_registered_strategy_required")
        exposed = {entry.get("name") for entry in entries[0].get("parameters", []) if isinstance(entry, dict)}
        if spec["parameters"].keys() - exposed:
            raise ContractError("live_backtest_unknown_parameter")
        for entry in entries[0].get("parameters", []):
            if not isinstance(entry, dict) or entry.get("name") not in spec["parameters"]:
                continue
            value = spec["parameters"][entry["name"]]
            kind = str(entry.get("kind") or entry.get("type") or "").lower()
            if (kind == "unsupported"
                    or kind in {"int", "integer", "system.int32", "system.int64"} and (type(value) is not int or not _number(value))
                    or kind in {"number", "double", "float", "system.double", "system.single", "system.decimal"} and not _number(value)
                    or kind in {"bool", "boolean", "system.boolean"} and type(value) is not bool
                    or kind in {"string", "system.string"} and not isinstance(value, str)
                    or entry.get("enum_values") and value not in entry["enum_values"]
                    or _number(value) and _number(entry.get("min")) and value < entry["min"]
                    or _number(value) and _number(entry.get("max")) and value > entry["max"]):
                raise ContractError("live_backtest_catalog_parameter_invalid")
        instruments = self.queue.read_instruments_catalog() or {}
        if not any(isinstance(entry, dict) and entry.get("instrument") == spec["instrument"]
                   for entry in instruments.get("instruments", [])):
            raise ContractError("live_backtest_registered_instrument_required")
        templates = self.queue.read_templates_catalog() or {}
        if not any(isinstance(entry, dict) and entry.get("name") == spec["session_template"] and entry.get("supported")
                   for entry in templates.get("trading_hours_templates", [])):
            raise ContractError("live_backtest_supported_session_required")
        # The canonical validator owns current commission/slippage governance.
        # An explicit None template still receives its honest research fee floor.

    def _owned(self, job_id, context, source):
        if not self.queue.job_in_scope(job_id, **source):
            return None
        origin = self.queue.job_origin(job_id)
        marker = origin.get("agent_world")
        if (not isinstance(marker, dict) or marker.get("schema_version") != 1
                or marker.get("source_kind") != "ninjatrader_report" or marker.get("synthetic") is not False
                or origin.get("workspace_id") != context.scope.workspace_id
                or str(origin.get("user_id") or "") != str(source["user_id"])
                or marker.get("owner_user_uuid") != str(context.user_uuid)
                or marker.get("persona") != "tolik"
                or marker.get("task_id") != str(uuid5(_NAMESPACE, job_id))):
            return None
        return marker

    def start(self, *, spec, idempotency_key, context, source_scope, chat_scope,
              conversation_id, admit, dispatch=None):
        source = self._access(context, source_scope, chat_scope, admit)
        key = _token(idempotency_key, "live_backtest_idempotency_required")
        conversation_id = _token(conversation_id, "live_backtest_conversation_required")
        normalized = _spec(spec)
        identity = [context.scope.environment.value, context.scope.workspace_id, str(context.user_uuid), key]
        job_id = "awnt_" + _sha(_canonical(identity))[:48]
        request_sha = _sha(_canonical({"spec": normalized, "conversation_id": conversation_id}))
        task_id = str(uuid5(_NAMESPACE, job_id))
        with _SUBMIT_LOCK:
            replayed = self.queue.find_job_dir(job_id) is not None
            if replayed:
                marker = self._owned(job_id, context, source)
                if not marker or marker.get("request_sha256") != request_sha:
                    raise ContractError("live_backtest_idempotency_conflict")
            else:
                self._registered(normalized)
                marker = {"schema_version": 1, "source_kind": "ninjatrader_report", "synthetic": False,
                          "owner_user_uuid": str(context.user_uuid), "persona": "tolik", "task_id": task_id,
                          "request_id": key, "conversation_id": conversation_id, "request_sha256": request_sha,
                          "correlation_id": str(uuid5(_NAMESPACE, "correlation:" + job_id)), "requested_spec": normalized}
                request = self.queue.CreateJobRequest(
                    **normalized, calculate="OnBarClose", is_tick_replay=False,
                    order_fill_resolution="High", commission=0.0, timezone="UTC", role="research", job_id=job_id,
                    origin={"type": "ai_lab", "created_by": "ai", "stage": "agent_world_owner_requested",
                            "workspace_id": source["workspace_id"], "user_id": source["user_id"], "agent_world": marker},
                )
                self._access(context, source_scope, chat_scope, admit)
                try:
                    self.queue.create_job(request)
                except self.queue.JobValidationError:
                    # A canonical duplicate after a retry is not a second job.
                    existing = self._owned(job_id, context, source)
                    if not existing or existing.get("request_sha256") != request_sha:
                        raise ContractError("live_backtest_submission_rejected") from None
                    replayed = True
            if dispatch is not None and self.queue.find_job_dir(job_id)[0] == "pending":
                self._access(context, source_scope, chat_scope, admit)
                dispatch(job_id)  # trusted existing dispatcher, with its own job-key idempotency
        detail = self.get(context=context, source_scope=source_scope, chat_scope=chat_scope, admit=admit, job_id=job_id)
        return {"ok": True, "job_id": job_id, "task_id": task_id, "replayed": replayed, "synthetic": False,
                "source_kind": "ninjatrader_report", "task": detail["task"], "detail": detail}

    @staticmethod
    def _source(path: Path, filename: str):
        # Never follow a report-supplied path or expose host paths in a DTO.
        target = path / filename
        if target.is_symlink() or target.resolve().parent != path.resolve():
            raise ContractError("live_backtest_source_path_invalid")
        try:
            with target.open("rb") as stream:
                content = stream.read(MAX_SOURCE_BYTES + 1)
            if len(content) > MAX_SOURCE_BYTES:
                raise ContractError("live_backtest_source_too_large")
            document = json.loads(content.decode("utf-8-sig"), parse_constant=lambda value: (_ for _ in ()).throw(ValueError()))
            return document, _sha(content), content
        except ContractError:
            raise
        except (OSError, ValueError, UnicodeError):
            raise ContractError("live_backtest_source_unavailable") from None

    def _verification(self, job_id, status, path, job):
        reasons, checksums, result, trades = [], {}, {}, {}
        if status not in _TERMINAL:
            # Nothing has been read yet, so nothing about the origin is refuted.
            return ({"passed": False, "state": "pending", "reasons": [], "source_checksums": {},
                     "synthetic": False, "source_confirmed": True}, result, trades)
        filename = "error.json" if status == "failed" else "result.json"
        try:
            result, checksums[filename], _ = self._source(path, filename)
            if not isinstance(result, dict):
                raise ContractError("live_backtest_result_structure_invalid")
            if status == "done":
                context = result.get("context") or {}
                metrics = result.get("metrics") or {}
                fingerprint = context.get("historical_data_fingerprint") or {}
                if result.get("job_id") != job_id or (context.get("strategy") or {}).get("class_name") != (job.get("strategy") or {}).get("class_name"):
                    reasons.append("result_identity_mismatch")
                for field in ("instrument", "timeframe", "period"):
                    if context.get(field) != job.get(field):
                        reasons.append("result_" + field + "_mismatch")
                execution = context.get("execution") or {}
                for field in ("role", "calculate", "order_fill_resolution", "slippage_ticks", "commission_template", "session_template", "timezone"):
                    if execution.get(field) != (job.get("execution") or {}).get(field):
                        reasons.append("result_execution_mismatch")
                final_parameters = (context.get("strategy") or {}).get("final_parameters") or {}
                if any(final_parameters.get(key) != value for key, value in ((job.get("strategy") or {}).get("parameters") or {}).items()):
                    reasons.append("result_parameters_mismatch")
                source = result.get("source") or {}
                if (source.get("execution_source") != "ninjatrader" or result.get("synthetic") or source.get("synthetic") or context.get("synthetic")
                        or any(word in str(source.get("trades_source", "")).lower() for word in ("demo", "synthetic", "mock"))):
                    reasons.append("ninjatrader_source_required")
                if not _HEX.fullmatch(str(result.get("run_hash") or "")):
                    reasons.append("run_hash_required")
                if (fingerprint.get("method") != "sha256_of_primary_bar_series"
                        or not _HEX.fullmatch(str(fingerprint.get("value") or ""))):
                    reasons.append("historical_fingerprint_required")
                bars, checksums["bars.json"], raw_bars = self._source(path, "bars.json")
                if not isinstance(bars, list) or not bars or type(fingerprint.get("bar_count")) is not int or fingerprint.get("bar_count") != len(bars):
                    reasons.append("historical_bars_count_mismatch")
                if not _valid_bars(bars, job.get("period") or {}):
                    reasons.append("historical_bars_structure_invalid")
                # The bridge hashes precisely the compact UTF-8 bytes it writes.
                if str(fingerprint.get("value") or "").removeprefix("sha256:") != _sha(raw_bars.removeprefix(b"\xef\xbb\xbf")):
                    reasons.append("historical_bars_sha_mismatch")
                rows, checksums["trades.json"], _ = self._source(path, "trades.json")
                if not _valid_trades(rows, job.get("period") or {}):
                    reasons.append("trades_structure_invalid")
                trades = self.queue.read_trades(job_id, offset=0, limit=1)
                count = metrics.get("trade_count")
                transfer = result.get("trade_transfer") or {}
                if transfer.get("trades_truncated") or (transfer and transfer.get("trades_total") != transfer.get("trades_transferred")):
                    reasons.append("partial_trade_transfer")
                if type(count) is not int or count < 0 or not isinstance(rows, list) or len(rows) != count or trades.get("total") != count:
                    reasons.append("trades_count_mismatch")
                if (not all(_number(metrics.get(key)) for key in ("net_profit", "gross_profit", "gross_loss", "max_drawdown"))
                        or any(type(value) is float and not math.isfinite(value) for value in metrics.values())):
                    reasons.append("metrics_invalid")
                if any("barsarray[0] not found / null" in str(warning).lower() for warning in result.get("verification_warnings", [])):
                    reasons.append("historical_bars_missing")
        except (ContractError, TypeError, AttributeError) as exc:
            reasons.append(getattr(exc, "code", "live_backtest_result_structure_invalid"))
        state = "verified" if status == "done" and not reasons else "rejected" if status == "done" else status
        # Provenance is a finding, not a folder. Content that claims NinjaTrader
        # and fails that exact check is not described as a NinjaTrader result
        # anywhere downstream -- the reason it was refused would otherwise be
        # contradicted by the sentence printed beside it. A genuine run whose
        # evidence is merely damaged keeps its confirmed origin.
        source_confirmed = "ninjatrader_source_required" not in reasons
        return {"passed": state == "verified", "state": state, "reasons": list(dict.fromkeys(reasons)),
                "source_checksums": checksums, "source_kind": "ninjatrader_report",
                "result_sha256": checksums.get(filename), "synthetic": not source_confirmed,
                "source_confirmed": source_confirmed,
                "model_quality_assessed": False}, result, trades

    def get(self, *, context, source_scope, chat_scope, admit, job_id):
        source = self._access(context, source_scope, chat_scope, admit)
        marker = self._owned(job_id, context, source)
        if marker is None:
            return None
        located = self.queue.find_job_dir(job_id)
        if not located:
            return None
        status, path = located
        job, job_sha, _ = self._source(path, "job.json")
        verification, result, trades = self._verification(job_id, status, path, job)
        verification["source_checksums"]["job.json"] = job_sha
        # Existing Reports owns metric normalization, including commission. Do
        # not recalculate strategy performance from sampled trades here.
        try:
            summary = self.queue.read_job_summary(job_id, include_adjusted=True) or {}
            if not isinstance(summary.get("metrics", {}), dict):
                raise ValueError
        except (ValueError, TypeError, AttributeError, OSError):
            summary = {}
            verification["passed"] = False
            verification["state"] = "rejected" if status == "done" else status
            verification["reasons"].append("canonical_report_unreadable")
        if verification["passed"]:
            # The report view and the checked source must describe the same
            # snapshot even if a terminal artifact is unexpectedly replaced.
            try:
                if any(self._source(path, name)[1] != digest for name, digest in verification["source_checksums"].items()):
                    raise ContractError("live_backtest_source_changed_during_read")
            except ContractError as exc:
                verification["passed"] = False
                verification["state"] = "rejected"
                verification["reasons"].append(exc.code)
        metrics = summary.get("metrics") or {}
        mapped = {"pending": "ready", "running": "running", "cancel_requested": "blocked",
                  "failed": "failed", "cancelled": "cancelled", "done": "succeeded" if verification["passed"] else "review"}.get(status, "blocked")
        stage = {"pending": "Ожидание NinjaTrader", "running": "Выполняется в NinjaTrader",
                 "cancel_requested": "Отмена запрошена; ожидаем NinjaTrader", "failed": "NinjaTrader сообщил об ошибке",
                 "cancelled": "Отмена подтверждена NinjaTrader", "done": "Отчёт проверен" if verification["passed"] else "Отчёт требует проверки"}.get(status, "Состояние не подтверждено")
        report_url = "/ui/backtesting.html?job=" + job_id
        title = "Бэктест · " + str((job.get("strategy") or {}).get("class_name") or "") + " · " + str(job.get("instrument") or "")
        text = title + "\n" + stage + "."
        if verification["passed"]:
            text += ("\nСделок: " + str(metrics.get("trade_count"))
                     + ". Результат после комиссии: " + str(metrics.get("net_profit_after_commission", "не указан в отчёте"))
                     + ". Profit Factor отчёта: " + str(metrics.get("profit_factor_after_commission", metrics.get("profit_factor", "не указан"))) + ".")
        if verification["reasons"]:
            text += "\nПроверка исходных файлов не пройдена: " + ", ".join(verification["reasons"]) + "."
        text += "\nОригинальный отчёт: " + report_url
        text += ("\nЭто результат NinjaTrader; оценка качества LLM не выполнялась."
                 if verification.get("source_confirmed", True) else
                 "\nПроисхождение не подтверждено: содержимое не описывает запуск NinjaTrader "
                 "и результатом NinjaTrader не считается. Оценка качества LLM не выполнялась.")
        updated = summary.get("finished_at_utc") or summary.get("heartbeat_at_utc") or job.get("created_at_utc")
        task = {"id": marker["task_id"], "task_id": marker["task_id"], "title": title, "status": mapped,
                "stage": stage, "source_status": status, "progress_pct": 100 if status in _TERMINAL else None,
                "lead": dict(_PERSONA), "participants": [dict(_PERSONA)], "created_at": job.get("created_at_utc"),
                "updated_at": updated, "summary": stage, "task_class": "ninjatrader_historical_backtest",
                "synthetic": verification["synthetic"], "source_confirmed": verification.get("source_confirmed", True),
                "source": "ninjatrader", "source_kind": "ninjatrader_report", "executor": "NinjaTrader Strategy Analyzer",
                "source_job_id": job_id, "report_url": report_url, "evidence_count": len(verification["source_checksums"]),
                "cost_usd": None, "paid_calls": 0, "observed_score_pct": None,
                "correlation_id": marker.get("correlation_id"), "conversation_id": marker.get("conversation_id"), "dependencies": []}
        artifacts = [{"id": job_id + ":" + filename, "title": "NinjaTrader · " + filename, "mime_type": "application/json",
                      "sha256": digest, "synthetic": verification["synthetic"], "source_kind": "ninjatrader_report",
                      "source_confirmed": verification.get("source_confirmed", True),
                      "url": "/api/jobs/" + job_id + ({"trades.json": "/trades", "bars.json": "/bars"}.get(filename, "")),
                      "summary": "SHA256 относится к исходному файлу; API отдаёт существующее представление отчёта."}
                     for filename, digest in verification["source_checksums"].items()]
        activity = [{"type": "ninjatrader.job_submitted", "title": "Задание опубликовано в существующую очередь NinjaTrader",
                     "time": task["created_at"], "synthetic": verification["synthetic"]},
                    {"type": "ninjatrader." + status, "title": stage, "time": updated,
                     "synthetic": verification["synthetic"]}]
        return {"task": task, "task_id": marker["task_id"], "activity": activity, "timeline": activity,
                "contributions": [{"persona": dict(_PERSONA), "status": "accepted" if verification["passed"] else "submitted",
                                   "summary": stage, "synthetic": verification["synthetic"]}] if status in _TERMINAL else [],
                "outcomes": [{"status": verification["state"], "summary": stage}] if status in _TERMINAL else [],
                "evaluations": [verification] if status in _TERMINAL else [], "verification": verification,
                "artifacts": artifacts, "decisions": [], "result_text": text,
                "result": {"metrics": metrics, "source_job_id": job_id, "report_url": report_url,
                           "run_hash": result.get("run_hash") if isinstance(result, dict) else None,
                           "trades_available": trades.get("total"),
                           "trades_source": {"kind": "canonical_trades_json", "complete": verification["passed"],
                                             "sha256": verification["source_checksums"].get("trades.json"),
                                             "total": trades.get("total")}, "synthetic": False}, "report_url": report_url}

    def _job_ids(self, context, source):
        offset = 0
        while True:
            rows = self.queue.list_jobs(limit=100, offset=offset, **source)
            for row in rows:
                job_id = str(row.get("job_id") or "")
                if self._owned(job_id, context, source):
                    yield job_id
            if len(rows) < 100:
                return
            offset += len(rows)

    def work(self, *, context, source_scope, chat_scope, admit, limit=100):
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ContractError("live_backtest_invalid_limit")
        source = self._access(context, source_scope, chat_scope, admit)
        items = []
        for job_id in self._job_ids(context, source):
            detail = self.get(context=context, source_scope=source_scope, chat_scope=chat_scope, admit=admit, job_id=job_id)
            if detail:
                items.append(detail["task"])
            if len(items) >= limit:
                break
        return items

    def task_detail(self, *, context, source_scope, chat_scope, admit, entity_id):
        source = self._access(context, source_scope, chat_scope, admit)
        if not isinstance(entity_id, UUID):
            raise ContractError("invalid_uuid")
        for job_id in self._job_ids(context, source):
            if str(uuid5(_NAMESPACE, job_id)) == str(entity_id):
                return self.get(context=context, source_scope=source_scope, chat_scope=chat_scope, admit=admit, job_id=job_id)
        return None

    def overview(self, *, context, source_scope, chat_scope, admit):
        tasks = self.work(context=context, source_scope=source_scope, chat_scope=chat_scope, admit=admit)
        completed = sum(task["status"] == "succeeded" for task in tasks)
        failed = sum(task["status"] in {"failed", "cancelled", "review", "blocked"} for task in tasks)
        stats = {"tasks_total": len(tasks), "completed": completed, "running": sum(task["source_status"] in {"pending", "running", "cancel_requested"} for task in tasks),
                 "failed": failed, "evaluations": 0, "artifacts": sum(task["evidence_count"] for task in tasks), "paid_calls": 0, "cost_usd": None}
        agent = {**_PERSONA, "status": "working" if stats["running"] else "idle", "tasks_completed": completed,
                 "task_ids": [task["id"] for task in tasks], "model": None, "rank": None,
                 "evaluation": {"sample_size": 0, "score_pct": None, "observed_score_pct": None, "confidence": "insufficient",
                                "mode": "ninjatrader_report", "window_label": "Проверены исходные отчёты; качество LLM не оценивалось",
                                "verified_reports": completed, "model_quality_assessed": False, "routing_effect": "none"}}
        return {"schema_version": 1, "source": "ninjatrader", "source_kind": "ninjatrader_report", "synthetic": False,
                "stats": stats, "summary": stats, "work": {"items": tasks}, "agents": {"items": [agent]},
                "read_limit": 100, "read_limit_reached": len(tasks) == 100}

    def reconcile(self, *, context, source_scope, chat_scope, admit, publish):
        """Existing monitor calls this; publish MUST deduplicate request_id.

        No delivery cursor is kept here: replay after a crash asks the existing
        chat authority for the same append. Canonical report changes get a new
        source checksum and therefore an explicit updated-result message.
        """
        source = self._access(context, source_scope, chat_scope, admit)
        if not callable(publish):
            raise ContractError("live_backtest_publisher_required")
        delivered, errors = [], []
        for job_id in self._job_ids(context, source):
            detail = self.get(context=context, source_scope=source_scope, chat_scope=chat_scope, admit=admit, job_id=job_id)
            if not detail or detail["task"]["source_status"] not in _TERMINAL:
                continue
            verification = detail["verification"]
            evidence_sha = _sha(_canonical([detail["task"]["source_status"], verification]))
            envelope = {"request_id": "aw.nt." + job_id + "." + evidence_sha, "conversation_id": detail["task"]["conversation_id"],
                        "scope": dict(chat_scope), "text": detail["result_text"], "agent_id": "tolik", "agent_name": "Толик",
                        "task_id": detail["task_id"], "source_job_id": job_id, "report_url": detail["report_url"],
                        "verification": verification, "synthetic": False, "source_kind": "ninjatrader_report"}
            self._access(context, source_scope, chat_scope, admit)
            try:
                response = publish(envelope)
                if isinstance(response, dict) and response.get("ok") is False:
                    raise ContractError("live_backtest_publication_failed")
                delivered.append({"job_id": job_id, "request_id": envelope["request_id"], "response": response})
            except Exception:
                errors.append({"job_id": job_id, "code": "live_backtest_publication_failed"})
        return {"items": delivered, "delivered": len(delivered), "errors": errors}
