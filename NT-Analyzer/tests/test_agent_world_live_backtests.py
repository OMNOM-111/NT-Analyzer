"""Real jobqueue/report contract in disposable roots; never start NinjaTrader."""
from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID

import pytest

from app import jobqueue
from app.ai_control_center import live_backtests as live
from app.ai_control_center.contracts import ActorKind, ActorRef, Environment, RequestContext, TenantScope
from app.ai_control_center.states import ContractError


def _context(user="17447f4a-5100-45fb-b3dc-e059e9215c94", workspace="ws_live_owner_001"):
    identity = UUID(user)
    return RequestContext(scope=TenantScope(environment=Environment.DEVELOPMENT, workspace_id=workspace),
                          user_uuid=identity, actor=ActorRef(kind=ActorKind.HUMAN, actor_id=identity))


def _args(context=None, user_id=123):
    context = context or _context()
    return {"context": context, "source_scope": {"workspace_id": context.scope.workspace_id, "user_id": user_id, "allow_legacy": True},
            "chat_scope": {"workspace_id": context.scope.workspace_id, "user_id": user_id, "user_uuid": str(context.user_uuid),
                           "is_owner": True, "uses_owner_runtime": True}, "admit": lambda: None}


def _spec():
    return {"class_name": "AWRegisteredStrategy", "instrument": "MNQ 09-26", "from_utc": "2026-08-24T00:00:00Z",
            "to_utc": "2026-08-29T00:00:00Z", "bars_period_type": "Minute", "bars_period_value": 5,
            "parameters": {"Period": 5}, "risk_profile": {}, "session_template": "CME US Index Futures RTH",
            "commission_template": "None", "slippage_ticks": 1}


@pytest.fixture
def service(monkeypatch, tmp_path):
    monkeypatch.setattr(live.runtime_env, "is_development", lambda: True)
    monkeypatch.setattr(live.preview_sandbox, "enabled", lambda: False)
    monkeypatch.setattr(jobqueue, "project_root", lambda: tmp_path)
    root = tmp_path / "jobs"
    monkeypatch.setattr(jobqueue, "jobs_dir", lambda: root)
    monkeypatch.setattr(jobqueue, "_resolve_portfolio_metadata", lambda *args: None)
    monkeypatch.setattr(jobqueue, "read_strategies_catalog", lambda: {"strategies": [{
        "class_name": "AWRegisteredStrategy", "parameters": [{"name": "Period", "kind": "int", "min": 1, "max": 100},
            {"name": "RoundTurnCommission"}, {"name": "SlippageTicks"}]}]})
    monkeypatch.setattr(jobqueue, "whitelisted_strategies", lambda: ["AWRegisteredStrategy"])
    monkeypatch.setattr(jobqueue, "read_instruments_catalog", lambda: {"instruments": [{"instrument": "MNQ 09-26"}]})
    monkeypatch.setattr(jobqueue, "read_templates_catalog", lambda: {
        "trading_hours_templates": [{"name": "CME US Index Futures RTH", "supported": True}],
        "commission_templates": [{"name": "None", "supported": True}],
    })
    jobqueue.reset_caches()
    import socket
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: pytest.fail("external connection forbidden"))
    yield live.LiveBacktestService()
    jobqueue.reset_caches()


def _start(service, *, key="request.1", args=None, spec=None, conversation="AW-real-test", dispatch=None):
    return service.start(**(args or _args()), spec=spec or _spec(), idempotency_key=key,
                         conversation_id=conversation, dispatch=dispatch)


def _write(path, value, *, compact=False):
    path.write_text(json.dumps(value, separators=(",", ":") if compact else None), encoding="utf-8")


def _terminal(out, *, status="done", count=2):
    located = jobqueue.find_job_dir(out["job_id"])
    source = located[1]
    target = jobqueue.jobs_dir() / status / out["job_id"]
    target.parent.mkdir(parents=True, exist_ok=True)
    source.rename(target)
    job = json.loads((target / "job.json").read_text(encoding="utf-8"))
    bars = [{"t": "2026-08-24T00:00:00Z", "o": 20000, "h": 20004, "l": 19998, "c": 20001, "v": 100},
            {"t": "2026-08-24T00:05:00Z", "o": 20001, "h": 20005, "l": 20000, "c": 20004, "v": 101}]
    _write(target / "bars.json", bars, compact=True)
    rows = [{"trade_no": index + 1, "direction": "long", "quantity": 1, "entry_time_utc": "2026-08-24T00:00:00Z",
             "exit_time_utc": "2026-08-24T00:05:00Z", "entry_price": 20000.0, "exit_price": 19987.5,
             "pnl_currency": -25.0, "pnl_ticks": -50, "commission": 0.0} for index in range(count)]
    _write(target / "trades.json", rows)
    result = {"job_id": out["job_id"], "run_hash": "sha256:" + "a" * 64, "finished_at_utc": "2026-09-04T23:59:00Z",
              "source": {"execution_source": "ninjatrader"},
              "context": {key: job[key] for key in ("instrument", "timeframe", "period", "execution")},
              "metrics": {"trade_count": count, "net_profit": -50.0, "gross_profit": 0.0, "gross_loss": -50.0,
                          "profit_factor": 0.0, "max_drawdown": 50.0}, "trades": rows,
              "artifacts": {"trades_file": "trades.json", "bars_file": "bars.json"}}
    result["context"]["strategy"] = {"class_name": job["strategy"]["class_name"], "final_parameters": job["strategy"]["parameters"]}
    result["context"]["historical_data_fingerprint"] = {
        "method": "sha256_of_primary_bar_series", "value": "sha256:" + hashlib.sha256((target / "bars.json").read_bytes()).hexdigest(),
        "bar_count": len(bars), "files": ["bars.json"]}
    _write(target / "result.json", result)
    if status == "failed":
        _write(target / "error.json", {"job_id": out["job_id"], "error_type": "nt_error", "message": "NinjaTrader failed"})
    jobqueue.reset_caches()
    return target, result


def _get(service, out):
    return service.get(**_args(), job_id=out["job_id"])


def test_start_uses_canonical_queue_and_server_origin_not_completed(service):
    out = _start(service)
    assert out["task"]["status"] == "ready"
    assert out["task"]["source_status"] == "pending"
    assert out["task"]["progress_pct"] is None
    assert out["task"]["synthetic"] is False
    path = jobqueue.find_job_dir(out["job_id"])[1]
    job = json.loads((path / "job.json").read_text(encoding="utf-8"))
    assert job["execution"]["role"] == "research"
    assert job["execution"]["order_fill_resolution"] == "High"
    assert job["execution"]["round_turn_commission"] >= 1.90
    assert job["origin"]["workspace_id"] == _context().scope.workspace_id
    assert job["origin"]["user_id"] == 123
    assert job["origin"]["agent_world"]["conversation_id"] == "AW-real-test"
    assert job["origin"]["agent_world"]["task_id"] == out["task_id"]
    assert out["detail"]["evaluations"] == []


def test_replay_after_restart_and_catalog_removed_returns_same_job(service, monkeypatch):
    first = _start(service)
    monkeypatch.setattr(jobqueue, "read_strategies_catalog", lambda: None)
    second = _start(live.LiveBacktestService())
    assert second["job_id"] == first["job_id"] and second["replayed"] is True
    assert len(list((jobqueue.jobs_dir() / "pending").glob("awnt_*"))) == 1


@pytest.mark.parametrize("change", ["spec", "conversation"])
def test_changed_request_is_not_idempotent_replay(service, change):
    _start(service)
    changed = _spec()
    changed["parameters"]["Period"] = 6
    with pytest.raises(ContractError, match="idempotency_conflict"):
        _start(service, spec=changed if change == "spec" else None,
               conversation="another" if change == "conversation" else "AW-real-test")


def test_concurrent_identical_submit_creates_one_canonical_job(service):
    with ThreadPoolExecutor(max_workers=4) as pool:
        replies = list(pool.map(lambda unused: _start(service), range(4)))
    assert len({reply["job_id"] for reply in replies}) == 1
    assert sum(not reply["replayed"] for reply in replies) == 1


@pytest.mark.parametrize("change,code", [
    ({"class_name": "DoesNotExist"}, "registered_strategy_required"),
    ({"instrument": "MNQ"}, "registered_instrument_required"),
    ({"parameters": {"Unknown": 5}}, "unknown_parameter"),
    ({"parameters": {"Period": "five"}}, "catalog_parameter_invalid"),
    ({"parameters": {"Period": 101}}, "catalog_parameter_invalid"),
    ({"to_utc": "2026-10-24T00:00:00Z"}, "period_limit"),
    ({"to_utc": "2026-08-24T00:00:00Z"}, "period_limit"),
    ({"from_utc": "2026-02-31T00:00:00Z"}, "explicit_utc_period_required"),
    ({"bars_period_value": True}, "invalid_timeframe"),
    ({"slippage_ticks": 0}, "invalid_timeframe"),
    ({"session_template": "Unregistered"}, "supported_session_required"),
    ({"commission_template": "Missing"}, "submission_rejected"),
    ({"role": "smoke"}, "explicit_spec_required"),
    ({"origin": {"user_id": 999}}, "explicit_spec_required"),
    ({"parameters": {"Period": float("nan")}}, "invalid_spec"),
])
def test_invalid_requests_never_reach_pending(service, change, code):
    spec = {**_spec(), **change}
    with pytest.raises(ContractError, match=code):
        _start(service, spec=spec)
    assert jobqueue.find_job_dir("awnt_" + "1" * 48) is None
    assert not list(jobqueue.jobs_dir().glob("pending/awnt_*"))


@pytest.mark.parametrize("case", ["preview", "production", "canary", "other_workspace", "other_uuid", "no_owner", "owner_runtime", "denied"])
def test_admission_and_scope_fail_closed(service, monkeypatch, case):
    args = _args()
    if case == "preview":
        monkeypatch.setattr(live.preview_sandbox, "enabled", lambda: True)
    elif case in {"production", "canary"}:
        monkeypatch.setattr(live.runtime_env, "is_development", lambda: False)
    elif case == "other_workspace":
        args["source_scope"]["workspace_id"] = "ws_another_001"
    elif case == "other_uuid":
        args["chat_scope"]["user_uuid"] = "wrong"
    elif case == "no_owner":
        args["chat_scope"]["is_owner"] = False
    elif case == "owner_runtime":
        args["chat_scope"]["uses_owner_runtime"] = False
    else:
        args["admit"] = lambda: False
    with pytest.raises(ContractError):
        _start(service, args=args)
    assert not list(jobqueue.jobs_dir().glob("pending/awnt_*"))


def test_admission_revalidated_immediately_before_publish_to_queue(service):
    attempts = []
    def admit():
        attempts.append(1)
        if len(attempts) > 1:
            raise ContractError("access_revoked")
    with pytest.raises(ContractError, match="access_revoked"):
        _start(service, args={**_args(), "admit": admit})
    assert not list(jobqueue.jobs_dir().glob("pending/awnt_*"))


def test_no_dispatch_except_supplied_existing_transport(service):
    seen = []
    out = _start(service, dispatch=seen.append)
    assert seen == [out["job_id"]]
    _terminal(out)
    _start(service, dispatch=seen.append)
    assert seen == [out["job_id"]]


def test_completed_report_verifies_actual_sources_with_no_invented_score(service):
    out = _start(service)
    path, raw = _terminal(out)
    before = {item.name: item.read_bytes() for item in path.iterdir() if item.is_file()}
    detail = _get(service, out)
    assert detail["verification"]["passed"] is True
    assert detail["task"]["status"] == "succeeded"
    assert detail["verification"]["result_sha256"] == hashlib.sha256((path / "result.json").read_bytes()).hexdigest()
    assert detail["result"]["metrics"]["trade_count"] == 2
    assert detail["result"]["metrics"] == jobqueue.read_job_summary(out["job_id"])["metrics"]
    assert raw["metrics"]["net_profit"] == -50.0
    assert "/ui/backtesting.html?job=" + out["job_id"] == detail["report_url"]
    assert service.task_detail(**_args(), entity_id=UUID(out["task_id"])) == detail
    overview = service.overview(**_args())
    assert overview["stats"]["completed"] == 1
    rating = overview["agents"]["items"][0]["evaluation"]
    assert rating["sample_size"] == 0 and rating["score_pct"] is None
    assert rating["verified_reports"] == 1
    assert {item.name: item.read_bytes() for item in path.iterdir() if item.is_file()} == before


@pytest.mark.parametrize("mutation,reason", [
    ("bars_tamper", "historical_bars_sha_mismatch"), ("missing_bars", "source_unavailable"),
    ("missing_trades", "source_unavailable"), ("wrong_job", "result_identity_mismatch"),
    ("wrong_instrument", "result_instrument_mismatch"), ("synthetic", "ninjatrader_source_required"),
    ("placeholder", "historical_fingerprint_required"), ("wrong_count", "trades_count_mismatch"),
    ("partial", "partial_trade_transfer"), ("missing_hash", "run_hash_required"),
    ("wrong_execution", "result_execution_mismatch"), ("wrong_parameters", "result_parameters_mismatch"),
    ("invalid_metrics", "result_structure_invalid"),
])
def test_done_is_not_verified_without_matching_real_artifacts(service, mutation, reason):
    out = _start(service)
    path, result = _terminal(out)
    if mutation == "bars_tamper":
        bars = json.loads((path / "bars.json").read_text())
        bars[0]["c"] += 1
        _write(path / "bars.json", bars, compact=True)
    elif mutation in {"missing_bars", "missing_trades"}:
        (path / ("bars.json" if mutation == "missing_bars" else "trades.json")).unlink()
    elif mutation == "wrong_job":
        result["job_id"] = "someone_else"
    elif mutation == "wrong_instrument":
        result["context"]["instrument"] = "MGC 12-26"
    elif mutation == "synthetic":
        result["source"]["execution_source"] = "synthetic"
    elif mutation == "placeholder":
        result["context"]["historical_data_fingerprint"]["method"] = "placeholder"
    elif mutation == "wrong_count":
        result["metrics"]["trade_count"] = 3
    elif mutation == "partial":
        result["trade_transfer"] = {"trades_truncated": True, "trades_total": 200, "trades_transferred": 2}
    elif mutation == "wrong_execution":
        result["context"]["execution"]["order_fill_resolution"] = "Standard"
    elif mutation == "wrong_parameters":
        result["context"]["strategy"]["final_parameters"]["Period"] = 10
    elif mutation == "invalid_metrics":
        result["metrics"] = ["invalid"]
    else:
        result.pop("run_hash")
    _write(path / "result.json", result)
    detail = _get(service, out)
    assert detail["task"]["status"] == "review"
    assert detail["verification"]["passed"] is False
    assert any(reason in found for found in detail["verification"]["reasons"])
    assert "Результат после комиссии" not in detail["result_text"]


def test_true_zero_trade_report_with_real_bars_is_not_strategy_failure(service):
    out = _start(service)
    _terminal(out, count=0)
    assert _get(service, out)["verification"]["passed"] is True


@pytest.mark.parametrize("artifact", ["bars", "trades"])
def test_structurally_invalid_source_is_rejected_even_with_rehashed_report(service, artifact):
    out = _start(service)
    path, result = _terminal(out)
    if artifact == "bars":
        rows = [{"fake_bar": 1}, {"fake_bar": 2}]
        _write(path / "bars.json", rows, compact=True)
        result["context"]["historical_data_fingerprint"]["value"] = "sha256:" + hashlib.sha256((path / "bars.json").read_bytes()).hexdigest()
        _write(path / "result.json", result)
    else:
        _write(path / "trades.json", [{"fake_trade": 1}, {"fake_trade": 2}])
    detail = _get(service, out)
    assert detail["task"]["status"] == "review"
    assert any("structure_invalid" in reason for reason in detail["verification"]["reasons"])


def test_oversized_source_is_review_not_unbounded_read(service, monkeypatch):
    out = _start(service)
    path, result = _terminal(out)
    original_source = service._source
    def bounded(path, filename):
        if filename == "result.json":
            with monkeypatch.context() as patch:
                patch.setattr(live, "MAX_SOURCE_BYTES", 10)
                return original_source(path, filename)
        return original_source(path, filename)
    monkeypatch.setattr(service, "_source", bounded)
    detail = _get(service, out)
    assert detail["task"]["status"] == "review"
    assert "live_backtest_source_too_large" in detail["verification"]["reasons"]


@pytest.mark.parametrize("status", ["failed", "cancelled", "cancel_requested", "running"])
def test_actual_non_success_states_not_completed_or_verified(service, status):
    out = _start(service)
    _terminal(out, status=status)
    detail = _get(service, out)
    assert detail["task"]["source_status"] == status
    assert detail["task"]["status"] != "succeeded"
    assert detail["verification"]["passed"] is False
    assert service.overview(**_args())["stats"]["completed"] == 0


def test_foreign_unmarked_and_uuid_spoof_jobs_are_not_agent_evidence(service):
    out = _start(service)
    other = _args(_context("a8d95445-0cfd-4e21-916f-8f1b14e8feef"), user_id=456)
    assert service.get(**other, job_id=out["job_id"]) is None
    assert service.work(**other) == []
    assert service.task_detail(**other, entity_id=UUID(out["task_id"])) is None
    path = jobqueue.find_job_dir(out["job_id"])[1]
    job = json.loads((path / "job.json").read_text(encoding="utf-8"))
    job["origin"].pop("agent_world")
    _write(path / "job.json", job)
    assert service.get(**_args(), job_id=out["job_id"]) is None
    assert service.work(**_args()) == []


def test_completion_callback_uses_stable_source_key_and_same_chat_scope(service):
    out = _start(service)
    assert service.reconcile(**_args(), publish=lambda envelope: pytest.fail("pending cannot publish"))["delivered"] == 0
    path, result = _terminal(out)
    published = {}
    def publish(envelope):
        published.setdefault(envelope["request_id"], envelope)
        return {"ok": True}
    service.reconcile(**_args(), publish=publish)
    service.reconcile(**_args(), publish=publish)
    assert len(published) == 1
    envelope = next(iter(published.values()))
    assert envelope["conversation_id"] == "AW-real-test" and envelope["scope"] == _args()["chat_scope"]
    assert envelope["source_job_id"] == out["job_id"] and envelope["verification"]["passed"]
    assert len(envelope["request_id"]) <= 160
    result["metrics"]["net_profit"] -= 1
    _write(path / "result.json", result)
    service.reconcile(**_args(), publish=publish)
    assert len(published) == 2


def test_failed_delivery_retries_existing_callback_not_second_job(service):
    out = _start(service)
    _terminal(out, status="failed")
    result = service.reconcile(**_args(), publish=lambda envelope: {"ok": False})
    assert result["delivered"] == 0 and result["errors"][0]["code"] == "live_backtest_publication_failed"
    assert service.reconcile(**_args(), publish=lambda envelope: {"ok": True})["delivered"] == 1
    assert len(list(jobqueue.jobs_dir().glob("*/awnt_*"))) == 1


def test_projection_rejects_a_report_changed_between_source_and_canonical_view(service, monkeypatch):
    out = _start(service)
    path, result = _terminal(out)
    original = jobqueue.read_job_summary
    def racing_summary(*args, **kwargs):
        summary = original(*args, **kwargs)
        result["metrics"]["net_profit"] -= 1
        _write(path / "result.json", result)
        return summary
    monkeypatch.setattr(jobqueue, "read_job_summary", racing_summary)
    detail = _get(service, out)
    assert detail["task"]["status"] == "review"
    assert "live_backtest_source_changed_during_read" in detail["verification"]["reasons"]


def test_read_paginates_past_unmarked_jobs_in_the_same_owner_scope(service):
    out = _start(service)
    path = jobqueue.find_job_dir(out["job_id"])[1]
    source = json.loads((path / "job.json").read_text(encoding="utf-8"))
    source["origin"].pop("agent_world")
    for index in range(105):
        target = jobqueue.jobs_dir() / "pending" / ("manual_" + str(index))
        target.mkdir()
        source["job_id"] = target.name
        _write(target / "job.json", source)
    jobqueue.reset_caches()
    assert [task["id"] for task in service.work(**_args())] == [out["task_id"]]


@pytest.mark.parametrize("claim", [
    {"execution_source": "isolated_test_report", "synthetic": True},
    {"execution_source": "ninjatrader", "synthetic": True},
    {"execution_source": "ninjatrader", "trades_source": "synthetic_generator"},
    {},
])
def test_unconfirmed_content_is_not_a_ninjatrader_result_just_for_claiming_one(service, claim):
    """Saying `execution_source: ninjatrader` does not make a report authoritative.

    The refusal already existed; what is pinned here is that nothing downstream
    then goes on describing the same content as a NinjaTrader result.
    """
    out = _start(service)
    path, result = _terminal(out)
    result["source"] = claim
    _write(path / "result.json", result)
    detail = _get(service, out)

    assert detail["verification"]["passed"] is False
    assert "ninjatrader_source_required" in detail["verification"]["reasons"]
    assert detail["verification"]["source_confirmed"] is False
    assert detail["verification"]["synthetic"] is True
    assert detail["task"]["source_confirmed"] is False
    assert detail["task"]["synthetic"] is True
    assert all(row["synthetic"] is True for row in detail["artifacts"])
    assert all(row["synthetic"] is True for row in detail["activity"])
    assert all(row["synthetic"] is True for row in detail["contributions"])
    assert "Это результат NinjaTrader" not in detail["result_text"]
    assert "Происхождение не подтверждено" in detail["result_text"]


def test_a_real_run_with_damaged_evidence_keeps_its_confirmed_origin(service):
    """Damaged evidence and a refuted origin are different findings.

    A genuine run whose bars no longer match their fingerprint is still a
    NinjaTrader run; it is the evidence that failed, not the provenance.
    """
    out = _start(service)
    path, result = _terminal(out)
    result["context"]["historical_data_fingerprint"]["value"] = "sha256:" + "b" * 64
    _write(path / "result.json", result)
    detail = _get(service, out)

    assert detail["verification"]["passed"] is False
    assert detail["verification"]["reasons"] == ["historical_bars_sha_mismatch"]
    assert detail["verification"]["source_confirmed"] is True
    assert detail["verification"]["synthetic"] is False
    assert detail["task"]["synthetic"] is False
    assert "Это результат NinjaTrader" in detail["result_text"]


def test_a_running_job_asserts_nothing_about_its_origin_yet(service):
    """Before a terminal state there is no file to have refuted anything."""
    out = _start(service)
    detail = _get(service, out)
    assert detail["verification"]["state"] == "pending"
    assert detail["verification"]["source_confirmed"] is True
    assert detail["task"]["synthetic"] is False
    assert detail["contributions"] == []
