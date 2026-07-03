from __future__ import annotations

from datetime import datetime, timezone

from app.ai_lab import activity, backtest, chief_agent, compile_pipeline, generator, orchestrator, registry, runner, signal_sanity


def test_deterministic_strategy_has_compact_backtest_logging() -> None:
    source = generator.fallback_template(
        "NTATestLogged", "AI-CELL-MNQ-001", "MNQ", {},
        family="vwap_pullback", hypothesis="test", reference_id="REF-008",
    )

    assert "EnableBacktestLog   = true" in source
    assert "[NTA-LAB] READY" in source
    assert "[NTA-LAB] SESSION_END" in source
    assert "[NTA-LAB] ENTRY" in source
    assert "Print" not in source.split("protected override void OnBarUpdate()", 1)[1].split("private void ForceFlat", 1)[0].split("if (EnableBacktestLog", 1)[0]


def test_staged_planner_prepares_distinct_next_experiment(monkeypatch) -> None:
    source = {
        "experiment_id": "EXP-20260702-0001", "status": "backtesting",
        "family": "vwap_pullback", "hypothesis": "prior VWAP idea",
    }
    monkeypatch.setattr(registry, "read_experiment", lambda _eid: dict(source))
    monkeypatch.setattr(runner, "_is_run_cancelled", lambda: False)
    states = []
    monkeypatch.setattr(runner, "_update_run_state", lambda **kwargs: states.append(kwargs))
    captured = {}
    monkeypatch.setattr(orchestrator, "prepare_strategy_draft", lambda args: captured.update(args) or {
        "experiment_id": "EXP-20260702-0002", "status": "draft_ready",
        "family": "trend_following", "staged_pipeline": {"model": "deepseek-v4-flash"},
    })
    holder = {}

    runner._prepare_next_during_backtest(
        "EXP-20260702-0001", {"goal": "find robust strategies"}, holder, "RUN-1",
    )

    assert holder["experiment"]["status"] == "draft_ready"
    assert "Avoid copying family=vwap_pullback" in captured["user_goal"]
    assert captured["avoid_families"] == ["vwap_pullback"]
    assert states[-1]["staged_pipeline"]["state"] == "ready"


def test_staged_feedback_carries_metrics_and_optimizer(monkeypatch) -> None:
    saved = []
    monkeypatch.setattr(registry, "write_experiment", lambda row: saved.append(dict(row)))
    target = {"experiment_id": "EXP-20260702-0002", "status": "draft_ready"}
    source = {
        "experiment_id": "EXP-20260702-0001", "status": "rejected", "family": "vwap_pullback",
        "analysis": {"trades_total": 135, "net_after_commission": -188.5,
                     "pf_after_commission": 0.81, "dd_after_commission": -270.6},
        "verdict": {"outcome": "reject", "rejection_code": "LOW_QUALITY"},
        "agent_committee": {"reports": {"optimizer": {"content": "Use a volatility regime filter."}}},
    }

    out = runner._attach_staged_feedback(target, source)

    assert out["staged_feedback"]["source_experiment_id"] == source["experiment_id"]
    assert out["staged_feedback"]["source_metrics"]["pf_after_commission"] == 0.81
    assert "volatility" in out["staged_feedback"]["optimizer_advice"]
    assert saved


def test_staged_activity_stage_is_a_real_supported_contract() -> None:
    assert "staged" in activity.STAGES
    assert activity.STAGE_RU["staged"]


def test_hypothesis_parameters_must_be_an_object(monkeypatch) -> None:
    monkeypatch.setattr(activity, "log", lambda *args, **kwargs: None)
    monkeypatch.setattr(orchestrator.agent_router, "invoke_messages", lambda *args, **kwargs: {
        "content": '{"reference_id":"REF-008","hypothesis":"x","family":"vwap_pullback",'
                   '"market_regime":"trend","entry_trigger":"pullback",'
                   '"why_not_generic":"regime","parameters":"not-an-object"}',
        "model": "mock", "provider": "mock",
    })
    intake = {
        "reference_shortlist": [{"reference_id": "REF-008", "family": "vwap_pullback"}],
        "model_health": {"idea_generator": {"ok": False}},
    }
    result = orchestrator.choose_hypothesis(
        "MNQ", intake, "EXP-20260702-9998", allow_paid_agents=False,
    )
    assert isinstance(result["parameters"], dict)
    assert result["_source"] == "fallback"


def test_current_contract_wins_over_expired_mature_contract(monkeypatch) -> None:
    monkeypatch.setattr(orchestrator, "_catalog_contracts", lambda root: [
        {"instrument": "MNQ 09-26", "data_first": "2026-06-11", "data_last": "2026-07-02"},
        {"instrument": "MNQ 06-26", "data_first": "2026-03-11", "data_last": "2026-06-18"},
    ])
    assert orchestrator._backtest_instrument("MNQ", {}) == "MNQ 09-26"


def test_backtest_period_is_clamped_to_proven_catalog_data(monkeypatch) -> None:
    monkeypatch.setattr(orchestrator, "_catalog_contracts", lambda root: [
        {"instrument": "MGC 08-26", "data_first": "2026-05-26", "data_last": "2026-07-02"},
    ])
    plan = orchestrator._bounded_period_for_instrument(
        "MGC 08-26",
        datetime(2026, 1, 1, tzinfo=timezone.utc),
        datetime(2026, 7, 2, tzinfo=timezone.utc),
    )
    assert plan["ok"] is True
    assert plan["from_utc"].startswith("2026-05-26")
    assert plan["to_utc"].startswith("2026-07-02")


def test_zero_trade_result_without_bars_is_infrastructure_failure() -> None:
    result = backtest.validate_result_integrity({
        "status": "done",
        "result": {
            "metrics": {"trade_count": 0},
            "context": {"historical_data_fingerprint": {
                "method": "placeholder", "value": "sha256:placeholder",
            }},
            "artifacts": {"bars_file": None},
            "verification_warnings": ["bars_collector: BarsArray[0] not found / null"],
        },
    })
    assert result["ok"] is False
    assert "strategy_bars_array_null" in result["reasons"]


def test_run_circuit_breaker_stops_repeated_systemic_failure() -> None:
    exp = {"status": "blocked_by_real_environment_issue", "verdict": {
        "rejection_code": "SMOKE_DATA_UNVERIFIED", "structural": True,
    }}
    signature = runner._failure_signature(exp)
    assert signature == "SMOKE_DATA_UNVERIFIED"
    assert runner._breaker_threshold(signature) == 2


def test_mission_breaker_prevents_restarting_same_failed_cycle(monkeypatch) -> None:
    monkeypatch.setattr(chief_agent.registry, "list_experiments", lambda limit=1000: [
        {"experiment_id": "EXP-20260702-0001", "created_at_utc": "2026-07-02T01:00:00Z",
         "verdict": {"rejection_code": "PIPELINE_EXCEPTION"}},
        {"experiment_id": "EXP-20260702-0002", "created_at_utc": "2026-07-02T01:01:00Z",
         "verdict": {"rejection_code": "PIPELINE_EXCEPTION"}},
    ])
    breaker = chief_agent._mission_failure_breaker({"started_at_utc": "2026-07-02T00:00:00Z"})
    assert breaker["open"] is True
    assert breaker["signature"] == "PIPELINE_EXCEPTION"


def test_compile_detects_dll_change_that_happened_immediately_after_source_write(monkeypatch) -> None:
    monkeypatch.setattr(activity, "log", lambda *args, **kwargs: None)
    monkeypatch.setattr(compile_pipeline, "_dll_mtime", lambda: 101.0)
    monkeypatch.setattr(compile_pipeline, "quarantine_unrelated_editor_failures", lambda **kwargs: [])
    monkeypatch.setattr(
        compile_pipeline, "trigger_ninjascript_editor_compile",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("F5 must be skipped")),
    )
    monkeypatch.setattr(compile_pipeline, "trigger_catalog_refresh", lambda *args, **kwargs: {"ok": True})
    monkeypatch.setattr(compile_pipeline, "await_class_in_catalog", lambda *args, **kwargs: True)
    monkeypatch.setattr(compile_pipeline, "class_in_whitelist", lambda *args, **kwargs: True)

    result = compile_pipeline.run_compile_chain(
        "EXP-20260702-9997", "NTAAiSandboxRace", baseline_mtime=100.0,
    )
    assert result["ok"] is True
    assert result["steps"][0]["status"] == "compile_already_observed_after_source_write"


def test_cross_contract_signal_sanity_is_advisory_not_rejection(tmp_path, monkeypatch) -> None:
    job = tmp_path / "job.json"
    bars = tmp_path / "bars.json"
    job.write_text('{"instrument":"MGC 06-26"}', encoding="utf-8")
    bars.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(signal_sanity, "find_bars_file", lambda root, instrument="": bars)
    monkeypatch.setattr(signal_sanity, "load_bars", lambda path: [])
    monkeypatch.setattr(signal_sanity, "estimate_family_signals", lambda *args, **kwargs: {
        "ok": False, "reason": "overtrading_risk", "theoretical_signals": 999,
        "environment_blocker": False,
    })
    result = signal_sanity.check_experiment(
        {"target_root": "MGC", "parameters": {}, "family": "mean_reversion"},
        instrument="MGC 08-26",
    )
    assert result["ok"] is True
    assert result["advisory_only"] is True
    assert result["original_reason"] == "overtrading_risk"
