"""AI Strategy Lab unit tests.

Covers the modules that have no external dependencies (no LM Studio HTTP,
no NinjaTrader compile). Network-bound modules are tested at a structural
level only.

Run: python -m tests.test_ai_lab
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.ai_lab import (  # noqa: E402
    activity, analysis_pack, arbitration, backtest, errors, generator, guards, paths,
    goal_parser, knowledge, registry, runner, signal_sanity, validator,
)
from app.ai_lab import compile_pipeline as ai_compile_pipeline  # noqa: E402
from app.ai_lab import compile_errors as ai_compile_errors  # noqa: E402
from app.ai_lab import bootstrap as ai_bootstrap  # noqa: E402
from app.ai_lab import operator_notes as ai_operator_notes  # noqa: E402
from app.ai_lab import heartbeat as ai_heartbeat  # noqa: E402
from app.ai_lab import lm_studio as ai_lm_studio  # noqa: E402
from app.ai_lab import read_model as ai_read_model  # noqa: E402

PASSED: List[str] = []
FAILED: List[Tuple[str, str]] = []


def _record(name: str, fn) -> None:
    data_root = Path(tempfile.mkdtemp(prefix="ai_lab_data_test_"))
    previous_data_root = os.environ.get("NTA_DATA_ROOT")
    previous_dev_root = os.environ.get("NTA_STAGING_DATA_ROOT")
    os.environ["NTA_DATA_ROOT"] = str(data_root / "production-data")
    os.environ["NTA_STAGING_DATA_ROOT"] = str(data_root / "development-data")
    try:
        fn()
        PASSED.append(name)
        print(f"  PASS  {name}")
    except Exception as e:  # noqa: BLE001
        FAILED.append((name, f"{e}\n{traceback.format_exc()}"))
        print(f"  FAIL  {name}: {e}")
    finally:
        if previous_data_root is None:
            os.environ.pop("NTA_DATA_ROOT", None)
        else:
            os.environ["NTA_DATA_ROOT"] = previous_data_root
        if previous_dev_root is None:
            os.environ.pop("NTA_STAGING_DATA_ROOT", None)
        else:
            os.environ["NTA_STAGING_DATA_ROOT"] = previous_dev_root
        shutil.rmtree(data_root, ignore_errors=True)


def _redirect_paths(tmp: Path) -> None:
    os.environ["AI_LAB_SANDBOX_DIR"] = str(tmp / "nt-custom" / "Strategies" / "NT-Analyzer_AI Labstrategies")
    paths.PROJECT_ROOT = tmp
    paths.AI_LAB_DIR = tmp / "ai_lab"
    paths.REGISTRY_DIR = paths.AI_LAB_DIR / "registry"
    paths.EXPERIMENTS_DIR = paths.REGISTRY_DIR / "experiments"
    paths.POSTMORTEMS_DIR = paths.REGISTRY_DIR / "strategy_postmortems"
    paths.KNOWLEDGE_CARDS_DIR = paths.REGISTRY_DIR / "knowledge_cards"
    paths.RUNS_DIR = paths.REGISTRY_DIR / "runs"
    paths.PROMPTS_LOG_DIR = paths.REGISTRY_DIR / "prompts_log"
    paths.ACTIVITY_DIR = paths.REGISTRY_DIR / "activity"
    paths.REFERENCE_STRATEGIES_DIR = paths.AI_LAB_DIR / "reference_strategies"
    paths.USER_RESEARCH_DIR = paths.AI_LAB_DIR / "user_research"
    paths.PROMPTS_DIR = paths.AI_LAB_DIR / "prompts"
    paths.SCHEMAS_DIR = paths.AI_LAB_DIR / "schemas"
    paths.MIRRORS_DIR = paths.AI_LAB_DIR / "mirrors"
    paths.SOURCE_SNAPSHOTS_DIR = paths.MIRRORS_DIR / "source_snapshots"
    paths.QUARANTINE_DIR = paths.AI_LAB_DIR / "quarantine" / "compile_failed"
    paths.MODEL_BENCHMARK_PATH = paths.REGISTRY_DIR / "model_benchmark_latest.json"
    paths.INDEX_PATH = paths.REGISTRY_DIR / "index.json"
    paths.ERROR_LOG_PATH = paths.REGISTRY_DIR / "error_log.jsonl"
    paths.ERROR_PATTERNS_PATH = paths.REGISTRY_DIR / "error_patterns.json"
    paths.LESSON_LOG_PATH = paths.REGISTRY_DIR / "lesson_log.jsonl"
    paths.REJECTED_HYPOTHESES_PATH = paths.REGISTRY_DIR / "rejected_hypotheses.jsonl"
    paths.DEMO_MISMATCH_PATH = paths.REGISTRY_DIR / "demo_mismatch_registry.jsonl"
    paths.COMPILE_FAIL_PATH = paths.REGISTRY_DIR / "compile_fail_registry.jsonl"
    paths.INFRA_FAIL_PATH = paths.REGISTRY_DIR / "infra_fail_registry.jsonl"
    paths.ensure_dirs()


# ---------------- arbitration ----------------

def t_arbitration_high_growth_scores_well() -> None:
    out = arbitration.compute(
        analysis={
            "monthly_growth_pct": 30.0,
            "pf_after_commission": 2.5,
            "dd_after_commission": 500.0,
            "profitable_months_pct": 75.0,
            "profitable_quarters_pct": 80.0,
            "profitable_years_pct": 100.0,
            "years_tested": 3.0,
            "trades_total": 800,
            "trades_per_day": 4.0,
        },
        risk_profile={"max_daily_loss": 200},
    )
    assert out["score"] > 100, f"expected strong score, got {out['score']}"
    assert "growth_score" in out and out["growth_score"] > 50


def t_arbitration_repeat_mistake_penalizes() -> None:
    base = {"monthly_growth_pct": 10.0, "pf_after_commission": 1.5,
            "dd_after_commission": 800.0, "trades_total": 200, "years_tested": 2.0}
    clean = arbitration.compute(base)
    dirty = arbitration.compute(base, similar_rejected_count=5, similar_compile_fail_count=5)
    assert dirty["score"] < clean["score"], "repeat-mistake history must reduce score"


def t_arbitration_no_trades_rejects() -> None:
    out = arbitration.compute({"monthly_growth_pct": 100.0, "trades_total": 0})
    assert out["score"] == 0.0
    assert "нет завершенных сделок" in out["rationale"]


def t_arbitration_quality_classification_is_calibrated() -> None:
    candidate = arbitration.classify_quality(
        {
            "trades_total": 120, "net_after_commission": 800,
            "pf_after_commission": 1.25, "dd_after_commission": -600,
            "trades_per_day": 1.1, "profitable_months_pct": 60,
        },
        score=55,
        capital=5000,
    )
    assert candidate["decision"] == "candidate", candidate
    near = arbitration.classify_quality(
        {
            "trades_total": 90, "net_after_commission": -50,
            "pf_after_commission": 0.96, "dd_after_commission": -500,
            "trades_per_day": 0.8,
        },
        score=10,
        capital=5000,
    )
    assert near["decision"] == "mutate", near
    weak = arbitration.classify_quality(
        {
            "trades_total": 300, "net_after_commission": -1500,
            "pf_after_commission": 0.55, "dd_after_commission": -1600,
            "trades_per_day": 2.8,
        },
        score=-30,
        capital=5000,
    )
    assert weak["decision"] == "reject", weak
    assert arbitration.repeat_mistake_penalty(10, 0) < 30


# ---------------- validator ----------------

VALID_SAMPLE = """
namespace NinjaTrader.NinjaScript.Strategies
{
    public class NTAAiSandboxFoo : Strategy
    {
        private double dailyOpenPnl;
        private const int SessionStartTimePT = 63000;
        private const int SessionEndTimePT = 123000;
        protected override void OnBarUpdate() {
            int nowPt = ToTime(Time[0]);
            double sessionPnl = SystemPerformance.AllTrades.TradesPerformance.Currency.CumProfit - dailyOpenPnl;
        }
        void Stuff() {
            SetStopLoss(...);
            SetProfitTarget(...);
            // MaxDailyLoss enforced
            // MaxTradesPerDay enforced
            ExitLong();
        }
    }
}
"""


def t_validator_accepts_minimal_ok() -> None:
    rep = validator.validate_source(VALID_SAMPLE, expected_class_name="NTAAiSandboxFoo")
    assert rep.ok, f"expected ok, violations={rep.violations}"


def t_validator_blocks_production_class_prefix() -> None:
    bad = VALID_SAMPLE.replace("NTAAiSandboxFoo", "NTAMicroFoo")
    rep = validator.validate_source(bad, expected_class_name="NTAMicroFoo")
    assert not rep.ok
    assert any("production class naming prefix" in v or "NTAAiSandbox" in v for v in rep.violations)


def t_validator_blocks_forbidden_api() -> None:
    bad = VALID_SAMPLE.replace("ExitLong();", "ExitLong(); System.IO.File.WriteAllText(\"x\", \"y\");")
    rep = validator.validate_source(bad, expected_class_name="NTAAiSandboxFoo")
    assert not rep.ok
    assert any("forbidden API" in v for v in rep.violations)


def t_validator_requires_risk_shell() -> None:
    bad = VALID_SAMPLE.replace("SetStopLoss(...);", "")
    rep = validator.validate_source(bad, expected_class_name="NTAAiSandboxFoo")
    assert not rep.ok
    assert any("stop_loss" in v for v in rep.violations)


def t_validator_requires_explicit_session_and_daily_pnl_snapshot() -> None:
    no_session = VALID_SAMPLE.replace("int nowPt = ToTime(Time[0]);", "int nowPt = 0;")
    rep = validator.validate_source(no_session, expected_class_name="NTAAiSandboxFoo")
    assert not rep.ok
    assert any("session window gate" in v for v in rep.violations)

    no_snapshot = VALID_SAMPLE.replace(
        "SystemPerformance.AllTrades.TradesPerformance.Currency.CumProfit - dailyOpenPnl",
        "SystemPerformance.AllTrades.TradesPerformance.Currency.CumProfit",
    )
    rep = validator.validate_source(no_snapshot, expected_class_name="NTAAiSandboxFoo")
    assert not rep.ok
    assert any("session PnL" in v for v in rep.violations)


def t_validator_blocks_production_cell_id() -> None:
    bad = VALID_SAMPLE.replace("// MaxDailyLoss enforced", "// belongs to CELL-014")
    rep = validator.validate_source(bad, expected_class_name="NTAAiSandboxFoo")
    assert not rep.ok
    assert any("production CELL" in v for v in rep.violations)


def t_validator_blocks_known_nt8_compile_errors() -> None:
    bad = """
using System;
using NinjaTrader.Cbi;
using NinjaTrader.NinjaScript;
using NinjaTrader.NinjaScript.StrategyAnalyzer;
using NinjaTrader.NinjaScript.Strategies;

namespace NinjaTrader.NinjaScript.Strategies
{
    public class NTAAiSandboxFoo : Strategy
    {
        [NinjaScriptProperty]
        [Range(1, 100)]
        public int Quantity { get; set; }

        protected override void OnStateChange()
        {
            IsExitOnSessionEnd = false;
            IsInstantiatedOnEachTrade = false;
            ForceCloseOnSessionEnd = true;
            SetCommission(CalculationMode.Currency, 1.90);
            SetSlippage(CalculationMode.Ticks, 1);
        }

        protected override void OnBarUpdate()
        {
            int dayNo = DateTime.DayNumber;
            if (IsFirstTickOfSession) { }
            SetStopLoss(CalculationMode.Ticks, 10);
            SetProfitTarget(CalculationMode.Ticks, 20);
            double pnl = Account.GetProfitLoss(0, PerformanceUnit.Currency);
            double cash = GetAccountValue(AccountItem.CashValue);
            DateTime pt = Time[0].ToPacific();
            if (pnl < -MaxDailyLoss) { Enabled = false; ExitLong(); }
        }

        private DateTime ToPacific(this DateTime utc)
        {
            return TimeZoneInfo.ConvertTimeFromUtc(utc, TimeZones.PacificStandardTime);
        }

        public int MaxDailyLoss { get; set; }
    }
}
"""
    rep = validator.validate_source(bad, expected_class_name="NTAAiSandboxFoo")
    assert not rep.ok
    joined = "\n".join(rep.violations)
    assert "IsExitOnSessionEnd" in joined
    assert "IsInstantiatedOnEachTrade" in joined
    assert "SetCommission" in joined
    assert "SetSlippage" in joined
    assert "ForceCloseOnSessionEnd" in joined
    assert "DateTime.DayNumber" in joined
    assert "Account.GetProfitLoss" in joined
    assert "AccountItem" in joined
    assert "DataAnnotations" in joined
    assert "StrategyAnalyzer" in joined
    assert "Enabled" in joined
    assert "IsFirstTickOfSession" in joined
    assert "ToPacific" in joined
    assert "TimeZones.PacificStandardTime" in joined


def t_generator_fallback_template_validates() -> None:
    class_name = generator.class_name_for("MNQ", "AI-CELL-MNQ-001", family="OrbBreakout")
    assert class_name == "NTAAiSandboxOrbBreakoutMnq001"
    src = generator.fallback_template(class_name, "AI-CELL-MNQ-001", "MNQ")
    rep = validator.validate_source(src, expected_class_name=class_name)
    assert rep.ok, f"fallback must validate, violations={rep.violations}"
    assert "public int SessionStartTimePT" in src
    assert "public int SessionEndTimePT" in src
    assert "ToTime(Time[0])" in src
    assert "public int MaxTradesPerDay" in src
    assert "public double RoundTurnCommission" in src
    assert "public int SlippageTicks" in src
    assert 'TelemetrySignal("Long")' in src
    assert 'TelemetrySignal("Short")' in src
    assert 'GetType().Name + "." + side' in src


def t_validator_blocks_anonymous_signals_and_forced_minimum_risk() -> None:
    class_name = "NTAAiSandboxRiskIdentity"
    src = generator.fallback_template(class_name, "AI-CELL-MNQ-098", "MNQ")

    anonymous = src.replace('TelemetrySignal("Long")', '"AnonymousLong"', 1)
    rep = validator.validate_source(anonymous, expected_class_name=class_name)
    assert not rep.ok
    assert any("every entry signal" in value for value in rep.violations), rep.violations

    forced = src.replace(
        "private void ForceFlat()",
        "private int ComputeQuantity(int byRisk) { return Math.Max(1, byRisk); }\n\n"
        "private void ForceFlat()",
    )
    rep = validator.validate_source(forced, expected_class_name=class_name)
    assert not rep.ok
    assert any("never force the minimum quantity" in value for value in rep.violations), rep.violations


def t_validator_allows_ai_cell_identifier_suffix() -> None:
    class_name = "NTAAiSandboxAllowedCell"
    src = generator.fallback_template(class_name, "AI-CELL-MNQ-005", "MNQ")
    rep = validator.validate_source(src, expected_class_name=class_name)
    assert rep.ok, rep.violations
    assert not any("production CELL" in v for v in rep.violations)


def t_static_autofix_prompt_contains_prior_source_and_identity() -> None:
    prior = (
        "namespace NinjaTrader.NinjaScript.Strategies { "
        "public class NTAAiSandboxRepairMe : Strategy { "
        "double x = Highest(High, 20)[0]; } }"
    )
    prompt = generator._build_static_validation_autofix_prompt(
        class_name="NTAAiSandboxRepairMe",
        violations=["invalid Highest", "missing force_flat"],
        prior_source=prior,
    )
    assert "NTAAiSandboxRepairMe" in prompt
    assert prior in prompt
    assert "ExitLong" in prompt and "ExitShort" in prompt
    assert "MAX(...)" in prompt and "MIN(...)" in prompt


def t_generator_repairs_common_nt8_source_slips() -> None:
    source = """
using System;
using NinjaTrader.NinjaScript;
using NinjaTrader.NinjaScript.Strategies;
namespace NinjaTrader.NinjaScript.Strategies {
public class NTAAiSandboxRepairCommon : Strategy {
private Bollinger bollinger;
private int BB_Period = 20;
private double BB_Multiplier = 2.0;
[Range(0.5, 5.0), NinjaScriptProperty]
public double SignalPeriod { get; set; } = 20.0;
protected override void OnStateChange() {
BarsPeriodType = BarsPeriodType.Minute;
BarsPeriodValue = 15;
AddDataSeries(BarsPeriodType.Minute, 5);
bollinger = Bollinger(BB_Period, BB_Multiplier);
}
protected override void OnPositionUpdate(Position position) { }
protected override void OnExecutionUpdate(Execution execution, string executionId,
double price, int quantity, MarketPosition marketPosition, string orderId,
DateTime time, TradeType tradeType, string filter) { }
void SessionClock() {
DateTime utcNow = Time[0];
DateTime pacificNow = TimeZoneInfo.ConvertTimeFromUtc(utcNow, pacificTz);
SetStopLoss("LongEntry", CalculationMode.Price, 100.0, 0);
EnterLong(1, "LongEntry");
ExitLong("ForceFlat", Position.Quantity);
}
}}
"""
    repaired, repairs = generator.repair_common_nt8_source(source)
    assert "using NinjaTrader.Cbi;" in repaired
    assert "using NinjaTrader.Data;" in repaired
    assert "using NinjaTrader.NinjaScript.Indicators;" in repaired
    assert "BarsPeriodValue =" not in repaired
    assert "BarsPeriodType =" not in repaired
    assert "AddDataSeries(" not in repaired
    assert "Bollinger(BB_Multiplier, BB_Period)" in repaired
    assert "MarketPosition marketPosition" in repaired
    assert "OnExecutionUpdate" not in repaired
    assert "ConvertTimeFromUtc(utcNow" not in repaired
    assert "TimeZoneInfo.ConvertTime(Time[0], pacificTz)" in repaired
    assert 'SetStopLoss("LongEntry", CalculationMode.Price, 100.0, false);' in repaired
    assert 'ExitLong("ForceFlat", "LongEntry")' in repaired
    assert "public int SignalPeriod" in repaired
    assert "[Range(1, 1000), NinjaScriptProperty]" in repaired
    assert "normalized_integer_period_range" in repairs
    assert len(repairs) >= 5, repairs


def t_generator_normalizes_drifted_production_cell_id() -> None:
    source, changed = generator.normalize_ai_cell_id(
        "// CELL-999\nDescription = \"CELL-999\";\n// AI-CELL-001",
        "AI-CELL-MNQ-999",
    )
    assert changed is True
    assert "CELL-999" not in source.replace("AI-CELL-MNQ-999", "")
    assert "AI-CELL-001" in source


def t_deterministic_vwap_renderer_validates_without_generic_breakout() -> None:
    source, report, meta = generator.render_deterministic_strategy(
        class_name="NTAAiSandboxVwapRenderer",
        ai_cell_id="AI-CELL-MNQ-998",
        instrument="MNQ",
        family="vwap_pullback",
        hypothesis="VWAP liquidity reversal",
        reference_id="REF-008",
        parameters={
            "Quantity": 1, "StopLossTicks": 20, "ProfitTargetTicks": 34,
            "MaxDailyLoss": 300, "MaxTradesPerDay": 2,
            "BreakoutLookback": 20, "RoundTurnCommission": 1.9,
            "SlippageTicks": 1, "SessionStartTimePT": 63000,
            "SessionEndTimePT": 123000, "volume_multiplier": 1.7,
            "vwap_window": 17, "ema_slope_filter": 23,
        },
    )
    assert report.ok, report.violations
    assert meta["path"] == "deterministic_family_renderer"
    assert "sessionVwap" in source
    assert "Math.Min(17, CurrentBar)" in source
    assert "avgVolume * 1.700" in source
    assert "EMA(23)[3]" in source
    assert "Close[0] > hi" not in source


def t_goal_parser_extracts_user_constraints() -> None:
    out = goal_parser.parse_user_goal(
        "Создай intraday стратегию для MNQ под бюджет $10,000 с Head and Shoulders, не overtrade"
    )
    assert out["target_root"] == "MNQ", out
    assert out["capital"] == 10000.0, out
    assert out["pattern"] == "HeadAndShoulders", out
    assert out["trade_frequency"] == "lower", out
    assert out["requires_knowledge_context"] is True


def t_goal_parser_ignores_substrings_and_negated_patterns() -> None:
    out = goal_parser.parse_user_goal(
        "MNQ: не повторяй RSI/EMA momentum, базовую Bollinger mean-reversion "
        "и старые Donchian-варианты."
    )
    assert out["pattern"] is None, out
    requested = goal_parser.parse_user_goal("MNQ RSI EMA pullback")
    assert requested["pattern"] == "RsiEmaPullback", requested
    without = goal_parser.parse_user_goal(
        "MNQ VWAP liquidity reversal без Donchian/Bollinger/EMA crossover"
    )
    assert without["pattern"] == "VwapPullback", without


def t_knowledge_context_reads_reference_library_and_sources() -> None:
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        _redirect_paths(tmp)
        ref = paths.REFERENCE_STRATEGIES_DIR
        (ref / "ai_lessons").mkdir(parents=True, exist_ok=True)
        (ref / "WORKING_STRATEGIES_RESULTS_TABLE.md").write_text(
            "| WEX-007 | Donchian Breakout | public | fresh | OK | 496 | $5370 | $467 | 1.095 | -$475 | 0.914 | -$928 | 36% | working_losing |\n",
            encoding="utf-8",
        )
        (ref / "ai_lessons" / "LESSONS_SUMMARY.md").write_text(
            "AI-CELL-005 lost after commission. WEX-006 overtrading disaster.",
            encoding="utf-8",
        )
        src_dir = tmp / "ninjatrader" / "strategies" / "Sample"
        src_dir.mkdir(parents=True, exist_ok=True)
        (src_dir / "Sample.cs").write_text(
            "namespace NinjaTrader.NinjaScript.Strategies { public class NTASample : Strategy { void X(){ EMA(20); SetStopLoss(0,0); SetProfitTarget(0,0); } } }",
            encoding="utf-8",
        )
        ctx = knowledge.build_context(
            "MNQ",
            user_goal="MNQ $10,000",
            goal_constraints={"target_root": "MNQ", "capital": 10000, "trade_frequency": "lower"},
            experiment_id="EXP-20260604-9700",
        )
        assert ctx["context_required"] is True
        assert ctx["path"] and Path(ctx["path"]).exists()
        joined = ctx["prompt_context"]
        assert "KNOWLEDGE_CONTEXT" in joined
        assert "WEX-007" in joined
        assert "AI-CELL-005" in joined
        assert any(s["class_name"] == "NTASample" for s in ctx["project_strategy_examples"])


def t_knowledge_reference_shortlist_excludes_forbidden_refs() -> None:
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        _redirect_paths(tmp)
        paths.REFERENCE_STRATEGIES_DIR.mkdir(parents=True, exist_ok=True)
        (paths.REFERENCE_STRATEGIES_DIR / "reference_registry.json").write_text(
            json.dumps([
                {
                    "strategy_id": "REF-GOOD", "name": "VWAP Pullback",
                    "strategy_family": "vwap_pullback",
                    "instrument_candidates": ["MNQ"],
                    "timeframe": ["5m"],
                    "usable_as_reference": True,
                    "candidate_for_adaptation": True,
                    "do_not_use_reason": None,
                    "risk_flags": [],
                    "notes": "near-passed with direction bias",
                },
                {
                    "strategy_id": "REF-BAD", "name": "Generic Fade",
                    "strategy_family": "generic_breakout",
                    "instrument_candidates": ["MNQ"],
                    "timeframe": ["5m"],
                    "usable_as_reference": True,
                    "candidate_for_adaptation": True,
                    "do_not_use_reason": "commission drag",
                    "risk_flags": [],
                    "notes": "",
                },
            ], ensure_ascii=False),
            encoding="utf-8",
        )
        ctx = knowledge.build_context("MNQ", max_prompt_chars=20_000)
        ids = [row["reference_id"] for row in ctx["reference_shortlist"]]
        assert ids == ["REF-GOOD"], ids
        assert "choose exactly one reference_id" in ctx["prompt_context"].lower()
        assert "REF-GOOD" in ctx["prompt_context"]
        assert "REF-BAD" not in ctx["prompt_context"]


def t_knowledge_context_keeps_reading_existing_user_research() -> None:
    from app.ai_lab import user_research

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        _redirect_paths(tmp)
        paths.USER_RESEARCH_DIR.mkdir(parents=True, exist_ok=True)
        research_file = paths.USER_RESEARCH_DIR / "curated" / "owner_findings.md"
        research_file.parent.mkdir(parents=True, exist_ok=True)
        research_file.write_text(
            "Owner finding: MNQ opening range needs VWAP confirmation and at most two trades.",
            encoding="utf-8",
        )
        first_scan = user_research.scan()
        assert "curated/owner_findings.md" in first_scan["new"]
        second_scan = user_research.scan()
        assert second_scan["new"] == [] and second_scan["changed"] == []

        ctx = knowledge.build_context("MNQ", max_prompt_chars=20_000)

        assert "curated/owner_findings.md" in ctx["user_research_refs"]
        assert any("Owner finding" in row for row in ctx["source_excerpt_summaries"])


def t_generator_prompt_includes_knowledge_context() -> None:
    prompt = generator.build_user_prompt(
        class_name="NTAAiSandboxFoo",
        ai_cell_id="AI-CELL-MNQ-001",
        instrument="MNQ",
        hypothesis="test",
        parameters={},
        memory_intake={"knowledge_prompt_context": "KNOWLEDGE_CONTEXT: do not repeat AI-CELL-005"},
        user_research_excerpts=[],
        rejected_patterns=[],
    )
    assert "KNOWLEDGE_CONTEXT: do not repeat AI-CELL-005" in prompt
    assert "MISSING_KNOWLEDGE_CONTEXT" not in prompt


def t_runner_research_loop_continues_after_rejected() -> None:
    rejected = {"status": "rejected", "analysis": {"trades_total": 0}, "verdict": {"outcome": "reject"}}
    assert runner._should_continue_loop(
        rejected,
        {"target_candidate_count": 1, "stop_on_first_candidate": True},
        research_mode="research_until_candidate_or_budget_exhausted",
        attempt_index=1,
        max_cells=2,
        candidate_count=0,
        deadline=10**12,
    ) is True
    candidate = {
        "status": "sandbox_candidate",
        "analysis": {"trades_total": 12},
        "verdict": {"outcome": "candidate"},
    }
    assert runner._should_continue_loop(
        candidate,
        {"target_candidate_count": 1, "stop_on_first_candidate": True},
        research_mode="research_until_candidate_or_budget_exhausted",
        attempt_index=1,
        max_cells=2,
        candidate_count=1,
        deadline=10**12,
    ) is False


def t_signal_sanity_counts_breakout_signals() -> None:
    bars = []
    for i in range(40):
        close = 100.0 + i
        bars.append({
            "t": f"2026-01-05T{15 + (i // 60):02d}:{i % 60:02d}:00Z",
            "o": close - 0.5,
            "h": close,
            "l": close - 1.0,
            "c": close,
            "v": 100,
        })
    out = signal_sanity.estimate_breakout_signals(
        bars,
        {"BreakoutLookback": 5, "MaxTradesPerDay": 3, "SessionStartPT": "06:30", "SessionEndPT": "12:30"},
        min_signals=1,
        data_source="synthetic",
    )
    assert out["ok"] is False, out
    assert out["reason"] == "overtrading_risk", out
    assert out["theoretical_signals"] > 0, out
    assert out["long_signals"] > 0, out


def t_compile_quarantine_moves_only_ai_sandbox_source() -> None:
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        _redirect_paths(tmp)
        sandbox = tmp / "nt-custom" / "Strategies" / "NT-Analyzer_AI Labstrategies"
        sandbox.mkdir(parents=True, exist_ok=True)
        source = sandbox / "NTAAiSandboxBroken.cs"
        source.write_text("// broken", encoding="utf-8")
        original = paths.ai_sandbox_strategies_dir
        paths.ai_sandbox_strategies_dir = lambda: sandbox  # type: ignore[assignment]
        try:
            result = ai_compile_pipeline.quarantine_source(
                experiment_id="EXP-20260622-9001",
                class_name="NTAAiSandboxBroken",
                reason="CS1002",
            )
        finally:
            paths.ai_sandbox_strategies_dir = original  # type: ignore[assignment]
        assert result["ok"] is True, result
        target = Path(result["quarantine_path"])
        assert not source.exists()
        assert target.exists()
        assert target.with_suffix(".json").exists()


def t_signal_sanity_dispatches_family_and_flags_overtrading() -> None:
    bars = []
    start = 1_767_225_600  # 2026-01-01 UTC
    for idx in range(1200):
        day_wave = (idx % 20) - 10
        close = 100 + day_wave * 0.5
        bars.append({
            "t": datetime.fromtimestamp(start + idx * 300, tz=timezone.utc).isoformat(),
            "o": close - 0.2, "h": close + 1.0, "l": close - 1.0,
            "c": close, "v": 1000 + (idx % 3) * 500,
        })
    out = signal_sanity.estimate_family_signals(
        bars,
        {"MaxTradesPerDay": 3, "SessionStartPT": "06:30", "SessionEndPT": "12:30"},
        family="VolumeWeightedMomentum",
        hypothesis="high-volume VWAP pullback",
        min_signals=1,
        data_source="synthetic",
    )
    assert out["estimator"] == "volume_vwap", out
    assert "raw_signals_per_day" in out


def t_backtest_submit_uses_queue_commission_contract() -> None:
    from app import jobqueue

    captured = {}
    old_create_job = jobqueue.create_job
    old_param_names = jobqueue._strategy_parameter_names
    with tempfile.TemporaryDirectory() as td:
        job_dir = Path(td) / "pending" / "job_ai_test"
        job_dir.mkdir(parents=True)

        def fake_create_job(req):
            captured["commission"] = req.commission
            captured["commission_template"] = req.commission_template
            captured["slippage_ticks"] = req.slippage_ticks
            captured["parameters"] = dict(req.parameters)
            captured["origin"] = dict(req.origin or {})
            return "job_ai_test", job_dir

        jobqueue.create_job = fake_create_job  # type: ignore[assignment]
        jobqueue._strategy_parameter_names = lambda class_name: {"Quantity"}  # type: ignore[assignment]
        try:
            out = backtest.submit(
                experiment_id="EXP-20260604-0001",
                ai_cell_id="AI-CELL-MNQ-001",
                class_name="NTAAiSandboxFoo",
                instrument="MNQ 12-26",
                from_utc="2026-01-01T00:00:00Z",
                to_utc="2026-02-01T00:00:00Z",
                parameters={"Quantity": 1, "SessionStartPT": "06:30"},
                risk_profile={},
            )
        finally:
            jobqueue.create_job = old_create_job  # type: ignore[assignment]
            jobqueue._strategy_parameter_names = old_param_names  # type: ignore[assignment]

    assert out["ok"], out
    assert captured["commission"] == 0.0
    assert captured["commission_template"] == "None"
    assert captured["slippage_ticks"] >= backtest.AI_SLIPPAGE_FLOOR
    assert captured["parameters"] == {"Quantity": 1}
    assert captured["origin"]["type"] == "ai_lab"
    assert captured["origin"]["experiment_id"] == "EXP-20260604-0001"


def t_backtest_maps_llm_parameter_names_to_nt8_properties() -> None:
    mapped = backtest._map_parameters_to_exposed(
        {
            "bb_period": 20,
            "stop_loss_ticks": 15,
            "take_profit_ticks": 10,
            "max_daily_trades": 2,
            "unknown_filter": 1.2,
        },
        {
            "BB_Period",
            "StopLossTicks",
            "ProfitTargetTicks",
            "MaxTradesPerDay",
        },
    )
    assert mapped == {
        "BB_Period": 20,
        "StopLossTicks": 15,
        "ProfitTargetTicks": 10,
        "MaxTradesPerDay": 2,
    }


# ---------------- registry ----------------

def t_registry_skeleton_and_write_roundtrip() -> None:
    with tempfile.TemporaryDirectory() as td:
        _redirect_paths(Path(td))
        exp = registry.new_experiment_skeleton(
            target_root="MNQ",
            class_name="NTAAiSandboxTest",
            hypothesis="hypothesis text",
        )
        assert registry.EXP_ID_RE.match(exp["experiment_id"]), exp["experiment_id"]
        assert registry.AI_CELL_RE.match(exp["ai_cell_id"]), exp["ai_cell_id"]
        assert exp["lab_namespace"] == "AI_SANDBOX"
        registry.write_experiment(exp)
        loaded = registry.read_experiment(exp["experiment_id"])
        assert loaded is not None
        assert loaded["target_root"] == "MNQ"
        idx = registry.load_index()
        assert any(e["experiment_id"] == exp["experiment_id"] for e in idx["experiments"])
        assert "MNQ" in idx["by_root"]


def t_registry_rejects_bad_namespace() -> None:
    with tempfile.TemporaryDirectory() as td:
        _redirect_paths(Path(td))
        exp = registry.new_experiment_skeleton("MNQ", "NTAAiSandboxFoo", "h")
        exp["lab_namespace"] = "PRODUCTION"
        try:
            registry.write_experiment(exp)
            raise AssertionError("should have refused non-AI_SANDBOX namespace")
        except ValueError:
            pass


def t_registry_cell_id_increments_per_root() -> None:
    with tempfile.TemporaryDirectory() as td:
        _redirect_paths(Path(td))
        e1 = registry.new_experiment_skeleton("MNQ", "NTAAiSandboxA", "h1")
        registry.write_experiment(e1)
        e2 = registry.new_experiment_skeleton("MNQ", "NTAAiSandboxB", "h2")
        assert e2["ai_cell_id"] != e1["ai_cell_id"], "AI-CELL ids must be unique per root"
        e3 = registry.new_experiment_skeleton("MGC", "NTAAiSandboxC", "h3")
        assert e3["ai_cell_id"].startswith("AI-CELL-MGC-"), e3["ai_cell_id"]


def t_portfolio_excludes_rejected_and_zero_trade_experiments() -> None:
    with tempfile.TemporaryDirectory() as td:
        _redirect_paths(Path(td))
        rejected = registry.new_experiment_skeleton("MNQ", "NTAAiSandboxRejected", "h")
        rejected["status"] = "rejected"
        rejected["analysis"] = {"trades_total": 0}
        rejected["verdict"] = {"outcome": "reject", "reasons": ["0 trades"], "rejection_code": "NO_TRADES"}
        rejected["portfolio"] = {"is_portfolio_member": True, "portfolio_status": "approved"}
        registry.write_experiment(rejected)

        board = ai_read_model.performance_board()
        row = next(r for r in board["rows"] if r["experiment_id"] == rejected["experiment_id"])
        assert row["history_status"] == "zero_trades"
        assert row["is_portfolio_member"] is False
        assert row["portfolio_eligible"] is False
        assert any("0 trades" in b for b in row["portfolio_blockers"])
        assert ai_read_model.portfolio_board()["rows"] == []
        try:
            registry.set_portfolio_membership(rejected["experiment_id"], action="promote")
            raise AssertionError("rejected 0-trade experiment must not be promotable")
        except ValueError as e:
            assert "0 trades" in str(e)


def t_portfolio_requires_manual_membership_action() -> None:
    with tempfile.TemporaryDirectory() as td:
        _redirect_paths(Path(td))
        candidate = registry.new_experiment_skeleton("MNQ", "NTAAiSandboxCandidate", "h")
        candidate["status"] = "sandbox_candidate"
        candidate["analysis"] = {"trades_total": 25}
        candidate["arbitration"] = {"score": 42.0}
        candidate["verdict"] = {"outcome": "candidate", "reasons": [], "rejection_code": None}
        registry.write_experiment(candidate)

        row = next(r for r in ai_read_model.performance_board()["rows"]
                   if r["experiment_id"] == candidate["experiment_id"])
        assert row["portfolio_eligible"] is True
        assert row["is_portfolio_member"] is False
        assert ai_read_model.portfolio_board()["rows"] == []

        registry.set_portfolio_membership(candidate["experiment_id"], action="approve", approved_by="test")
        rows = ai_read_model.portfolio_board()["rows"]
        assert len(rows) == 1
        assert rows[0]["experiment_id"] == candidate["experiment_id"]
        assert rows[0]["portfolio_status"] == "approved"
        assert rows[0]["approved_by"] == "test"

        registry.set_portfolio_membership(candidate["experiment_id"], action="remove", approved_by="test")
        assert ai_read_model.portfolio_board()["rows"] == []


# ---------------- errors ----------------

def t_errors_normalize_collapses_volatile_bits() -> None:
    s = errors._normalize("error CS0103 at C:\\foo\\bar.cs(12,5) addr 0x1F line 42")
    assert "<PATH>" in s
    assert "<HEX>" in s
    assert "<N>" in s


def t_errors_pattern_counts_aggregate() -> None:
    with tempfile.TemporaryDirectory() as td:
        _redirect_paths(Path(td))
        for _ in range(3):
            errors.log_error("EXP-20260603-0001", "compile", "csc_error",
                              "error CS0103: foo at (12,5)", severity="error")
        pats = errors.pattern_counts()
        assert any(p.get("count", 0) >= 3 for p in pats), pats


# ---------------- LM Studio client (offline structural) ----------------

def t_lm_studio_extract_json_block() -> None:
    from app.ai_lab import lm_studio
    raw = "preamble {\"k\": 1, \"nested\": {\"a\": [1, 2, 3]}} trailing"
    out = lm_studio.extract_json_block(raw)
    assert out == {"k": 1, "nested": {"a": [1, 2, 3]}}


def t_lm_studio_model_routes_have_all_roles() -> None:
    from app.ai_lab import lm_studio
    for role in ("judge", "coder", "embedder"):
        assert role in lm_studio.MODEL_ROUTES
        assert lm_studio.model_for(role)


# ---------------- runner / activity / status lifecycle ----------------

def t_activity_log_uses_line_offset() -> None:
    with tempfile.TemporaryDirectory() as td:
        _redirect_paths(Path(td))
        eid = "EXP-20260604-9001"
        n1 = activity.log(eid, "intake", "skeleton", level="info", foo="bar")
        n2 = activity.log(eid, "generate", "started", level="info")
        n3 = activity.log(eid, "validate", "ok", level="success")
        assert (n1, n2, n3) == (1, 2, 3)
        tail = activity.tail(eid, since_line=1)
        assert tail["next_line"] == 3
        assert [e["action"] for e in tail["entries"]] == ["started", "ok"]
        assert tail["total_lines"] == 3


def t_status_lifecycle_no_fake_ready() -> None:
    from app.ai_lab import orchestrator
    with tempfile.TemporaryDirectory() as td:
        _redirect_paths(Path(td))
        runner.reset_for_tests()
        skeleton = orchestrator.start_skeleton({"user_pref_root": "MNQ", "user_capital": 5000})
        eid = skeleton["experiment_id"]
        try:
            orchestrator.run_pipeline(eid, {
                "skip_compile": True, "skip_backtest": True, "user_pref_root": "MNQ",
                "use_llm": False,
            })
        except Exception:
            pass
        exp = registry.read_experiment(eid)
        assert exp is not None
        # MUST NOT be the old fake "ready"; with skip_compile we leave it at awaiting_compile
        # (or validation_failed if generation went bad).
        assert exp["status"] in {"awaiting_compile", "validation_failed"}, exp["status"]


def t_runner_single_flight() -> None:
    with tempfile.TemporaryDirectory() as td:
        _redirect_paths(Path(td))
        runner.reset_for_tests()
        # Manufacture a busy state without touching threads.
        runner._CURRENT = {"experiment_id": "EXP-20260604-9999", "status": "generating"}
        exp = registry.new_experiment_skeleton("MNQ", "NTAAiSandboxX", "h")
        exp["experiment_id"] = "EXP-20260604-9999"
        exp["status"] = "generating"
        registry.write_experiment(exp)
        try:
            runner.start({"dry_run": True})
            raise AssertionError("should have raised RunnerBusy")
        except runner.RunnerBusy as e:
            assert e.current["experiment_id"] == "EXP-20260604-9999"
            assert "cancel_event" not in e.current
        finally:
            runner.reset_for_tests()


def t_runner_busy_current_is_json_safe() -> None:
    import threading as th
    ev = th.Event()
    try:
        raise runner.RunnerBusy({"experiment_id": "EXP-busy", "cancel_event": ev})
    except runner.RunnerBusy as e:
        json.dumps(e.current)
        assert "cancel_event" not in e.current


def t_runner_busy_rejects_before_lm_preflight() -> None:
    from app.ai_lab import lm_studio as ai_lm_studio

    with tempfile.TemporaryDirectory() as td:
        _redirect_paths(Path(td))
        runner.reset_for_tests()
        exp = registry.new_experiment_skeleton(
            "MNQ", "NTAAiSandboxBusyEarly", "busy-early"
        )
        exp["status"] = "generating"
        registry.write_experiment(exp)
        runner._CURRENT = {
            "experiment_id": exp["experiment_id"],
            "status": "generating",
        }
        calls = {"preflight": 0}
        original = ai_lm_studio.preflight_all_required_roles

        def fake_preflight(*args, **kwargs):
            calls["preflight"] += 1
            return {"ok": True}

        ai_lm_studio.preflight_all_required_roles = fake_preflight  # type: ignore[assignment]
        try:
            try:
                runner.start({"use_llm": True, "dry_run": False})
                raise AssertionError("should have raised RunnerBusy")
            except runner.RunnerBusy:
                pass
            assert calls["preflight"] == 0, calls
        finally:
            ai_lm_studio.preflight_all_required_roles = original  # type: ignore[assignment]
            runner.reset_for_tests()


# ---------------- guards / invariant ----------------

def t_guards_block_production_writes() -> None:
    with tempfile.TemporaryDirectory() as td:
        _redirect_paths(Path(td))
        # A path that clearly isn't in the AI sandbox or mirror.
        bogus = Path(td) / "ninjatrader" / "strategies" / "Production.cs"
        try:
            guards.assert_sandbox_only(bogus)
            raise AssertionError("guard should have raised")
        except guards.SandboxBreachError:
            pass
        # Sandbox path itself is allowed.
        allowed = paths.SOURCE_SNAPSHOTS_DIR / "X.cs"
        guards.assert_sandbox_only(allowed)


def t_generator_refuses_invalid_write() -> None:
    with tempfile.TemporaryDirectory() as td:
        _redirect_paths(Path(td))
        bad = "class Foo {}"  # fails every static check
        try:
            generator.write_to_sandbox("NTAAiSandboxBad", bad)
            raise AssertionError("write_to_sandbox should have refused invalid source")
        except ValueError:
            pass


# ---------------- Phase E: compile_errors / heartbeat / operator_notes ----

def t_compile_errors_read_since() -> None:
    import datetime as _dt
    with tempfile.TemporaryDirectory() as td:
        _redirect_paths(Path(td))
        p = ai_compile_errors.jsonl_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        records = [
            {"timestamp_utc": "2026-06-04T10:00:00Z", "code": "CS0103",
             "class_name": "NTAAiSandboxA", "file": "A.cs", "line": 1, "message": "old1"},
            {"timestamp_utc": "2026-06-04T10:00:01Z", "code": "CS0103",
             "class_name": "NTAAiSandboxB", "file": "B.cs", "line": 2, "message": "old2"},
            {"timestamp_utc": "2026-06-04T12:00:00Z", "code": "CS0246",
             "class_name": "NTAAiSandboxA", "file": "A.cs", "line": 3, "message": "new1"},
            {"timestamp_utc": "2026-06-04T12:00:01Z", "code": "CS0246",
             "class_name": "NTAAiSandboxB", "file": "B.cs", "line": 4, "message": "new2"},
        ]
        with p.open("w", encoding="utf-8") as fh:
            for r in records:
                fh.write(json.dumps(r) + "\n")
        baseline = _dt.datetime(2026, 6, 4, 11, 0, 0, tzinfo=_dt.timezone.utc)
        all_new = ai_compile_errors.read_since(baseline)
        assert len(all_new) == 2, all_new
        assert {r["message"] for r in all_new} == {"new1", "new2"}
        only_a = ai_compile_errors.read_since(baseline, class_name="NTAAiSandboxA")
        assert len(only_a) == 1
        assert only_a[0]["message"] == "new1"
        # substring match in file field
        only_b = ai_compile_errors.read_since(baseline, class_name="B")
        assert any(r["message"] == "new2" for r in only_b)


def t_compile_errors_append_manual() -> None:
    with tempfile.TemporaryDirectory() as td:
        _redirect_paths(Path(td))
        pasted = (
            "noise line\n"
            "C:\\foo\\NTAAiSandboxX.cs(47,31) : error CS0103: The name 'foo' does not exist\n"
            "warning CS0162: ignored\n"
            "C:\\foo\\NTAAiSandboxX.cs(48,5) : error CS0246: Type 'Bar' not found\n"
            "NTAAiSandboxOrbBreakoutMes001.cs\tThe name 'Enabled' does not exist in the current context\tCS0103\t102\t17\n"
        )
        count = ai_compile_errors.append_manual("EXP-20260604-9100", "NTAAiSandboxX", pasted)
        assert count == 3, count
        path = ai_compile_errors.jsonl_path()
        lines = [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
        assert {r["source"] for r in lines} == {"manual_paste", "manual_paste_table"}, lines
        assert {r["code"] for r in lines} == {"CS0103", "CS0246"}
        assert any(r["line"] == 102 and r["column"] == 17 for r in lines), lines


def t_compile_pipeline_parses_ninjascript_editor_grid() -> None:
    from app.ai_lab import compile_pipeline

    cells = [
        {"automation_id": "RecordRow0_Файл NinjaScript ", "name": "NTAAiSandboxGrid.cs"},
        {"automation_id": "RecordRow0_Ошибка", "name": "Execution could not be found"},
        {"automation_id": "RecordRow0_Код", "name": "CS0246"},
        {"automation_id": "RecordRow0_Линия", "name": "140"},
        {"automation_id": "RecordRow0_Колонка", "name": "51"},
        {"automation_id": "RecordRow1_Файл NinjaScript ", "name": "OtherStrategy.cs"},
        {"automation_id": "RecordRow1_Ошибка", "name": "unrelated"},
        {"automation_id": "RecordRow1_Код", "name": "CS0103"},
    ]
    out = compile_pipeline._parse_ninjascript_error_cells(
        cells, class_name="NTAAiSandboxGrid"
    )
    assert len(out) == 1, out
    assert out[0]["code"] == "CS0246"
    assert out[0]["line"] == 140
    assert out[0]["column"] == 51
    assert out[0]["source"] == "ninjatrader_editor_uia"


def t_lmstudio_default_timeouts_are_bounded() -> None:
    import inspect
    sig = inspect.signature(ai_lm_studio.chat)
    # quality_over_speed policy: chat default must be >= 180 (was 120 before the policy)
    assert sig.parameters["timeout"].default >= 180, sig.parameters["timeout"].default
    assert ai_lm_studio.DEFAULT_JUDGE_TIMEOUT >= 180
    assert ai_lm_studio.DEFAULT_CODER_TIMEOUT >= 300
    assert ai_lm_studio.DEFAULT_MODEL_PROBE_TIMEOUT >= 60
    assert sig.parameters["retries"].default == 0, sig.parameters["retries"].default


def t_llm_timeouts_config() -> None:
    """Unified timeout config must satisfy quality_over_speed policy invariants."""
    from app.ai_lab import llm_timeouts

    # Low-level probes stay short: must not block long when model is absent.
    assert llm_timeouts.CONNECTION_TEST <= 60, llm_timeouts.CONNECTION_TEST
    assert llm_timeouts.MODEL_PROBE <= 120, llm_timeouts.MODEL_PROBE
    assert llm_timeouts.LIST_MODELS <= 30, llm_timeouts.LIST_MODELS

    # Analysis and review need enough time for thinking tokens.
    assert llm_timeouts.ANALYSIS >= 240, llm_timeouts.ANALYSIS
    assert llm_timeouts.REVIEW >= 240, llm_timeouts.REVIEW

    # Code generation is the longest cloud operation; must not be cut short.
    assert llm_timeouts.CODE_GENERATION >= 600, llm_timeouts.CODE_GENERATION
    assert llm_timeouts.CODE_AUTOFIX >= 600, llm_timeouts.CODE_AUTOFIX

    # Orchestrator / chief with repair pass need even more headroom.
    assert llm_timeouts.ORCHESTRATOR_PLAN >= 360, llm_timeouts.ORCHESTRATOR_PLAN
    assert llm_timeouts.CHIEF_DIALOGUE >= 420, llm_timeouts.CHIEF_DIALOGUE

    # Local LM Studio coder: generous ceiling (GPT-OSS p95 ~ 5 min).
    assert llm_timeouts.LOCAL_CODER >= 600, llm_timeouts.LOCAL_CODER
    assert llm_timeouts.LOCAL_JUDGE >= 240, llm_timeouts.LOCAL_JUDGE
    assert llm_timeouts.LOCAL_CHAT >= 180, llm_timeouts.LOCAL_CHAT

    # All entries must return int and resolve without error.
    for op in [
        "connection_test", "model_probe", "list_models", "embedding",
        "light_chat", "analysis", "review", "code_generation", "code_autofix",
        "orchestrator_plan", "chief_dialogue", "periodic_report",
        "local_judge", "local_coder", "local_chat_default",
    ]:
        val = llm_timeouts.resolve_timeout(op)
        assert isinstance(val, int) and val > 0, f"{op}: {val!r}"

    # policy key must be present.
    cfg = llm_timeouts.policy()
    assert cfg.get("policy") == "quality_over_speed", cfg.get("policy")


def t_lmstudio_default_base_url_uses_ipv4_loopback() -> None:
    """Windows may resolve localhost to ::1 while LM Studio binds 127.0.0.1."""
    assert ai_lm_studio.DEFAULT_BASE_URL == "http://127.0.0.1:1234/v1"


def t_ai_strategy_ui_preserves_ready_state_during_background_probe() -> None:
    js = (Path(__file__).resolve().parents[1] / "legacy_viewer" / "static" / "ai-strategy.js").read_text(
        encoding="utf-8"
    )
    assert "previousLm?.run_allowed === true" in js
    assert "summary.lm_studio = { ...incomingLm, ...previousLm }" in js
    assert "if (_lmReadinessPromise) return _lmReadinessPromise" in js
    assert "if (_lmReadinessTimer) return" in js
    assert "if (STATE.runActive) return STATE.summary?.lm_studio || {}" in js
    assert "STATE.runActive = true" in js
    assert "const disableRun = STATE.runActive || !runAllowed;" in js


def t_ai_strategy_ui_hides_terminal_heartbeat() -> None:
    js = (Path(__file__).resolve().parents[1] / "legacy_viewer" / "static" / "ai-strategy.js").read_text(
        encoding="utf-8"
    )
    assert "appendActivity(data.entries || [], { showHeartbeat: !data.terminal })" in js
    assert "if (latestHeartbeat && options.showHeartbeat !== false)" in js
    assert "STATE.activityTimer = setInterval(tick, 2000);\n    tick();" in js


def t_bootstrap_status_shape_without_side_effects() -> None:
    original_lm_status = ai_bootstrap.lm_studio.lm_status
    original_tasklist = ai_bootstrap._tasklist_contains
    original_lms = ai_bootstrap._lms_cli
    original_nt = ai_bootstrap._ninjatrader_exe
    original_lm = ai_bootstrap._lm_studio_exe

    def fake_lm_status(*, allow_probe=False, force=False):
        return {
            "available": True,
            "ready": True,
            "run_allowed": True,
            "status": "ready",
            "models": ["qwen3-coder-30b-a3b-instruct", "openai/gpt-oss-20b"],
        }

    try:
        ai_bootstrap.lm_studio.lm_status = fake_lm_status  # type: ignore[assignment]
        ai_bootstrap._tasklist_contains = lambda needle: needle == "ninjatrader"  # type: ignore[assignment]
        ai_bootstrap._lms_cli = lambda: "lms"  # type: ignore[assignment]
        ai_bootstrap._ninjatrader_exe = lambda: r"C:\NT\NinjaTrader.exe"  # type: ignore[assignment]
        ai_bootstrap._lm_studio_exe = lambda: r"C:\LM Studio\LM Studio.exe"  # type: ignore[assignment]
        out = ai_bootstrap.status()
        assert out["ok"] is True
        assert out["components"]["ninjatrader"]["running"] is True
        assert out["components"]["lms_cli"]["available"] is True
        assert out["components"]["lm_studio_server"]["run_allowed"] is True
        assert isinstance(out["required_models"], list)
        assert out["required_models"], out
        assert out.get("ninjatrader_autostart_allowed") is False
        assert out["components"]["ninjatrader"].get("autostart_allowed") is False
    finally:
        ai_bootstrap.lm_studio.lm_status = original_lm_status  # type: ignore[assignment]
        ai_bootstrap._tasklist_contains = original_tasklist  # type: ignore[assignment]
        ai_bootstrap._lms_cli = original_lms  # type: ignore[assignment]
        ai_bootstrap._ninjatrader_exe = original_nt  # type: ignore[assignment]
        ai_bootstrap._lm_studio_exe = original_lm  # type: ignore[assignment]


def t_bootstrap_never_autostarts_ninjatrader_without_env_opt_in() -> None:
    """Even start_ninjatrader=True must not Popen NT.exe without NTA_ALLOW_AUTOSTART_NINJATRADER."""
    calls: list = []

    def fake_start(exe: str, label: str):
        calls.append((exe, label))
        return {"ok": True, "status": "started", "exe": exe}

    def fake_lm_status(*, allow_probe=False, force=False):
        return {
            "available": True, "ready": False, "run_allowed": False,
            "status": "offline", "missing_run_roles": [],
        }

    original = {
        "tasklist": ai_bootstrap._tasklist_contains,
        "start": ai_bootstrap._start_process,
        "lm": ai_bootstrap.lm_studio.lm_status,
        "lms": ai_bootstrap._lms_cli,
        "run_lms": ai_bootstrap._run_lms,
        "nt": ai_bootstrap._ninjatrader_exe,
        "lm_exe": ai_bootstrap._lm_studio_exe,
        "deploy": ai_bootstrap._deploy_bridge_if_safe,
    }
    old_env = os.environ.pop(ai_bootstrap.AUTOSTART_NT_ENV, None)
    try:
        ai_bootstrap._tasklist_contains = lambda needle: False  # type: ignore[assignment]
        ai_bootstrap._start_process = fake_start  # type: ignore[assignment]
        ai_bootstrap.lm_studio.lm_status = fake_lm_status  # type: ignore[assignment]
        ai_bootstrap._lms_cli = lambda: ""  # type: ignore[assignment]
        ai_bootstrap._run_lms = lambda *a, **k: {"ok": True, "status": "skipped"}  # type: ignore[assignment]
        ai_bootstrap._ninjatrader_exe = lambda: r"C:\NT\NinjaTrader.exe"  # type: ignore[assignment]
        ai_bootstrap._lm_studio_exe = lambda: ""  # type: ignore[assignment]
        ai_bootstrap._deploy_bridge_if_safe = lambda *_a, **_k: {"ok": True, "status": "up_to_date"}  # type: ignore[assignment]

        blocked = ai_bootstrap.start(
            start_ninjatrader=True, start_lm_studio=False, start_lm_server=False,
            load_models=False, wait_readiness=False, timeout_sec=30,
        )
        nt_step = next(s for s in blocked["steps"] if s.get("component") == "ninjatrader")
        assert nt_step["status"] == "manual_login_required"
        assert not any(label == "NinjaTrader" for _, label in calls)

        defaulted = ai_bootstrap.start(
            start_lm_studio=False, start_lm_server=False,
            load_models=False, wait_readiness=False, timeout_sec=30,
        )
        nt_default = next(s for s in defaulted["steps"] if s.get("component") == "ninjatrader")
        assert nt_default["status"] == "skipped_default_off"
        assert not any(label == "NinjaTrader" for _, label in calls)
    finally:
        ai_bootstrap._tasklist_contains = original["tasklist"]  # type: ignore[assignment]
        ai_bootstrap._start_process = original["start"]  # type: ignore[assignment]
        ai_bootstrap.lm_studio.lm_status = original["lm"]  # type: ignore[assignment]
        ai_bootstrap._lms_cli = original["lms"]  # type: ignore[assignment]
        ai_bootstrap._run_lms = original["run_lms"]  # type: ignore[assignment]
        ai_bootstrap._ninjatrader_exe = original["nt"]  # type: ignore[assignment]
        ai_bootstrap._lm_studio_exe = original["lm_exe"]  # type: ignore[assignment]
        ai_bootstrap._deploy_bridge_if_safe = original["deploy"]  # type: ignore[assignment]
        if old_env is None:
            os.environ.pop(ai_bootstrap.AUTOSTART_NT_ENV, None)
        else:
            os.environ[ai_bootstrap.AUTOSTART_NT_ENV] = old_env


def t_ai_strategy_ui_has_bootstrap_controls() -> None:
    root = Path(__file__).resolve().parents[1]
    html = (root / "legacy_viewer" / "static" / "ai-strategy.html").read_text(encoding="utf-8")
    js = (root / "legacy_viewer" / "static" / "ai-strategy.js").read_text(encoding="utf-8")
    assert 'id="ai-bootstrap-btn"' in html
    assert 'id="ai-unload-lm-btn"' in html
    assert 'id="ai-bootstrap-wrap"' in html
    assert "/api/ai-lab/bootstrap/status" in js
    assert "/api/ai-lab/bootstrap/start" in js
    assert "/api/ai-lab/bootstrap/unload" in js
    assert "load_models: false" in js
    assert "start_ninjatrader: false" in js
    assert "startBootstrap" in js
    assert "unloadLmStudio" in js


def t_heartbeat_emits_during_long_stage() -> None:
    import time
    with tempfile.TemporaryDirectory() as td:
        _redirect_paths(Path(td))
        eid = "EXP-20260604-9200"
        with ai_heartbeat.heartbeat(eid, "compile", "waiting for F5", every_sec=0.5):
            time.sleep(1.4)
        tail = activity.tail(eid, since_line=0)
        hb = [e for e in tail["entries"] if e.get("heartbeat") is True]
        assert len(hb) >= 2, f"expected >=2 heartbeat rows, got {len(hb)}"
        assert all(e.get("action") == "waiting for F5" for e in hb)


def t_operator_notes_roundtrip() -> None:
    with tempfile.TemporaryDirectory() as td:
        _redirect_paths(Path(td))
        eid = "EXP-20260604-9300"
        e1 = ai_operator_notes.add(eid, "use larger SL")
        e2 = ai_operator_notes.add(eid, "prefer breakout over fade", priority="high")
        assert e1["index"] == 0 and e2["index"] == 1
        pend = ai_operator_notes.pending(eid)
        assert len(pend) == 2
        rendered = ai_operator_notes.render_for_prompt(eid)
        assert "OPERATOR NOTES" in rendered
        assert "use larger SL" in rendered
        assert "prefer breakout over fade" in rendered
        ai_operator_notes.mark_applied(eid, [0, 1], "coder")
        assert ai_operator_notes.pending(eid) == []
        all_notes = ai_operator_notes.list_all(eid)
        assert all(n.get("applied_at_stage") == "coder" for n in all_notes)


def t_operator_notes_apply_checkpoint_logs_and_marks() -> None:
    with tempfile.TemporaryDirectory() as td:
        _redirect_paths(Path(td))
        eid = "EXP-20260604-9301"
        ai_operator_notes.add(eid, "tighten profit target")
        applied = ai_operator_notes.apply_checkpoint(eid, "autofix")
        assert len(applied) == 1
        assert ai_operator_notes.pending(eid) == []
        assert "tighten profit target" in ai_operator_notes.render_entries(applied)
        notes = ai_operator_notes.list_all(eid)
        assert notes[0]["applied_at_stage"] == "autofix"
        tail = activity.tail(eid, since_line=0)
        actions = [e.get("action") for e in tail["entries"]]
        assert "operator_note_applied" in actions, actions


def t_autofix_prompt_includes_errors_and_notes() -> None:
    """generator.generate(mode='autofix', use_llm=True) → capture lm prompt."""
    with tempfile.TemporaryDirectory() as td:
        _redirect_paths(Path(td))
        captured = {}

        def fake_chat(role, messages, **kwargs):
            captured["role"] = role
            captured["messages"] = messages
            captured["kwargs"] = kwargs
            # Return a valid sandbox source so generator accepts it.
            src = generator.fallback_template(
                class_name="NTAAiSandboxAutofix", ai_cell_id="AI-CELL-MNQ-901",
                instrument="MNQ", parameters={},
            )
            return {"content": "```csharp\n" + src + "\n```", "model": "fake", "elapsed_sec": 0.1}

        original = ai_lm_studio.chat
        ai_lm_studio.chat = fake_chat
        try:
            src, report, meta = generator.generate(
                class_name="NTAAiSandboxAutofix",
                ai_cell_id="AI-CELL-MNQ-901",
                instrument="MNQ",
                hypothesis="x",
                parameters={},
                use_llm=True,
                mode="autofix",
                prior_compile_errors=[
                    {"file": "C:\\foo\\NTAAiSandboxAutofix.cs", "line": 47,
                     "column": 31, "code": "CS0103", "message": "name 'foo' missing"},
                ],
                prior_source="// previous content",
                operator_notes="## OPERATOR NOTES (newest last)\n- [normal] use MAX(High,30)",
            )
        finally:
            ai_lm_studio.chat = original
        assert meta["mode"] == "autofix"
        assert meta["role"] == "coder-autofix"
        joined = "\n".join(m["content"] for m in captured["messages"])
        assert "CS0103" in joined
        assert "name 'foo' missing" in joined
        assert "OPERATOR NOTES" in joined
        assert "use MAX(High,30)" in joined
        assert "// previous content" in joined
        # autofix kwargs include cancel_event slot (may be None)
        assert "cancel_event" in captured["kwargs"]


def t_compile_autofix_prompt_adds_cbi_hint() -> None:
    prompt = generator._build_autofix_prompt(
        class_name="NTAAiSandboxCbiFix",
        prior_compile_errors=[{
            "file": "NTAAiSandboxCbiFix.cs",
            "line": 140,
            "column": 50,
            "code": "CS0246",
            "message": "The type or namespace name 'Position' could not be found",
        }],
        prior_source="public class NTAAiSandboxCbiFix {}",
        operator_notes=None,
    )
    assert "using NinjaTrader.Cbi;" in prompt
    assert "instead of deleting required overrides" in prompt


def t_validator_blocks_wrong_on_position_update_signature() -> None:
    class_name = "NTAAiSandboxPositionSignature"
    src = generator.fallback_template(class_name, "AI-CELL-MNQ-099", "MNQ")
    src = src.replace(
        "\n    }\n}",
        """
        protected override void OnPositionUpdate(
            NinjaTrader.Cbi.Position position, double averagePrice, int quantity,
            NinjaTrader.Cbi.MarketPosition marketPosition, string signalName)
        {
        }
    }
}""",
    )
    rep = validator.validate_source(src, expected_class_name=class_name)
    assert not rep.ok
    assert any("OnPositionUpdate" in v for v in rep.violations), rep.violations


def t_cancel_request_sets_event_and_terminal() -> None:
    import threading
    with tempfile.TemporaryDirectory() as td:
        _redirect_paths(Path(td))
        runner.reset_for_tests()
        eid = "EXP-20260604-9400"
        # Manually seed a running pipeline so request_cancel works.
        skel = registry.new_experiment_skeleton("MNQ", "NTAAiSandboxCancel", "h")
        skel["experiment_id"] = eid
        skel["status"] = "generating"
        registry.write_experiment(skel)
        runner._CURRENT = {
            "experiment_id": eid, "status": "generating",
            "cancel_event": threading.Event(),
        }
        try:
            assert runner.is_cancelled(eid) is False
            out = runner.request_cancel(eid)
            assert out["ok"] is True and out["cancelled"] is True
            assert runner.is_cancelled(eid) is True
            ev = runner.cancel_event_for(eid)
            assert ev is not None and ev.is_set()
            # Wrong eid → no-op
            out2 = runner.request_cancel("EXP-bogus")
            assert out2["ok"] is False
        finally:
            runner.reset_for_tests()
        # cancelled is now in TERMINAL_STATUSES
        assert "cancelled" in registry.TERMINAL_STATUSES


def t_registry_cancelled_is_terminal() -> None:
    with tempfile.TemporaryDirectory() as td:
        _redirect_paths(Path(td))
        skel = registry.new_experiment_skeleton("MNQ", "NTAAiSandboxCx", "h")
        skel["status"] = "generating"
        registry.write_experiment(skel)
        eid = skel["experiment_id"]
        registry.transition_status(eid, "cancelled", reason="test")
        exp = registry.read_experiment(eid)
        assert exp["status"] == "cancelled"
    assert registry.is_terminal("cancelled") is True
    assert registry.is_terminal("pipeline_failed") is True


def t_backtest_payload_shape() -> None:
    """Seed jobs/done/<job>/result.json and verify backtest_payload."""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        _redirect_paths(tmp)
        # Build a fake jobs/done/<id>/result.json by monkey-patching find_job_dir.
        job_id = "JOB-TEST-001"
        job_dir = tmp / "jobs" / "done" / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        (job_dir / "result.json").write_text(json.dumps({
            "metrics": {"net_profit": 1234.5, "trade_count": 250, "profit_factor": 1.6,
                        "max_drawdown": -200.0, "winning_pct": 55.0, "sharpe": 1.2},
        }), encoding="utf-8")
        # 250 fake trades — payload must trim to last 200.
        trades = [{"entry_time_utc": f"2026-01-{i%28+1:02d}T09:30:00Z",
                   "exit_time_utc": f"2026-01-{i%28+1:02d}T09:35:00Z",
                   "side": "long", "entry_price": 100.0+i, "exit_price": 101.0+i,
                   "pnl_currency": 5.0}
                  for i in range(250)]
        (job_dir / "trades.json").write_text(json.dumps({"trades": trades}), encoding="utf-8")
        (job_dir / "job.json").write_text(json.dumps({"id": job_id, "status": "done"}), encoding="utf-8")

        # Seed an experiment whose last backtest references JOB-TEST-001
        skel = registry.new_experiment_skeleton("MNQ", "NTAAiSandboxBT", "h")
        skel["status"] = "backtest_done"
        skel["backtests"] = [{"job_id": job_id, "status": "done"}]
        registry.write_experiment(skel)
        eid = skel["experiment_id"]

        # Monkey-patch find_job_dir to point to our fake dir
        original = backtest.find_job_dir
        backtest.find_job_dir = lambda jid: job_dir if jid == job_id else None
        try:
            payload = ai_read_model.backtest_payload(eid)
        finally:
            backtest.find_job_dir = original
        assert payload["ok"] is True, payload
        assert payload["job_id"] == job_id
        assert payload["metrics"]["net_pnl"] == 1234.5
        assert payload["metrics"]["trades_total"] == 250
        assert payload["metrics"]["profit_factor"] == 1.6
        assert payload["metrics"]["max_drawdown"] == -200.0
        assert payload["metrics"]["win_rate_pct"] == 55.0
        assert payload["daily"], payload
        assert payload["equity_curve"][0]["points"], payload
        assert payload["drawdown_series"], payload
        assert len(payload["trades"]) <= 200
        assert payload["trades"][-1]["pnl"] == 5.0
        assert payload["job_url"].endswith(job_id)
        for k in ("summary", "metrics", "daily", "equity_curve", "drawdown_series", "trades"):
            assert k in payload, k


def t_analysis_pack_reads_bridge_trade_fields_and_metrics() -> None:
    with tempfile.TemporaryDirectory() as td:
        job_dir = Path(td)
        (job_dir / "job.json").write_text(json.dumps({
            "job_id": "JOB-ANALYSIS-001",
            "period": {"from_utc": "2026-01-01T00:00:00Z", "to_utc": "2026-01-03T00:00:00Z"},
        }), encoding="utf-8")
        (job_dir / "result.json").write_text(json.dumps({
            "metrics": {"profit_factor": 1.25, "max_drawdown": -75.5},
        }), encoding="utf-8")
        (job_dir / "trades.json").write_text(json.dumps({"trades": [
            {"exit_time_utc": "2026-01-01T10:00:00Z", "pnl_currency": 100.0},
            {"exit_time_utc": "2026-01-02T10:00:00Z", "pnl_currency": -25.0},
        ]}), encoding="utf-8")

        pack = analysis_pack.build(job_dir, capital=5000.0)

    assert pack["totals"]["trades_total"] == 2
    assert pack["totals"]["net_pnl"] == 75.0
    assert pack["stability"]["pf_after_commission"] == 1.25
    assert pack["stability"]["dd_after_commission"] == -75.5
    assert pack["breakdown"]["by_month"]["2026-01"] == 75.0


def t_analysis_pack_uses_round_turn_commission_adjustment() -> None:
    with tempfile.TemporaryDirectory() as td:
        job_dir = Path(td)
        (job_dir / "job.json").write_text(json.dumps({
            "job_id": "JOB-ANALYSIS-ADJ",
            "period": {"from_utc": "2026-01-01T00:00:00Z", "to_utc": "2026-01-03T00:00:00Z"},
            "execution": {"round_turn_commission": 2.0},
            "strategy": {"parameters": {"RoundTurnCommission": 2.0}},
        }), encoding="utf-8")
        (job_dir / "result.json").write_text(json.dumps({
            "metrics": {"profit_factor": 99.0, "max_drawdown": 0.0},
        }), encoding="utf-8")
        (job_dir / "trades.json").write_text(json.dumps({"trades": [
            {"exit_time_utc": "2026-01-01T10:00:00Z", "pnl_currency": 10.0, "quantity": 1},
            {"exit_time_utc": "2026-01-02T10:00:00Z", "pnl_currency": -5.0, "quantity": 1},
        ]}), encoding="utf-8")

        pack = analysis_pack.build(job_dir, capital=5000.0)

    assert pack["totals"]["gross_net_pnl"] == 5.0
    assert pack["totals"]["net_pnl"] == 1.0
    assert round(pack["stability"]["pf_after_commission"], 6) == round(8.0 / 7.0, 6)
    assert pack["stability"]["dd_after_commission"] == -7.0


def t_generator_propagates_lmstudio_cancelled() -> None:
    def fake_chat(role, messages, **kwargs):
        raise ai_lm_studio.LMStudioCancelled("test cancel")

    original = ai_lm_studio.chat
    ai_lm_studio.chat = fake_chat
    try:
        try:
            generator.generate(
                class_name="NTAAiSandboxCancelProp",
                ai_cell_id="AI-CELL-MNQ-950",
                instrument="MNQ",
                hypothesis="x",
                parameters={},
                use_llm=True,
            )
        except ai_lm_studio.LMStudioCancelled:
            return
        raise AssertionError("LMStudioCancelled must propagate out of generator.generate")
    finally:
        ai_lm_studio.chat = original


def t_generator_does_not_fallback_after_cancelled_lm_error() -> None:
    import threading

    cancel_event = threading.Event()

    def fake_chat(role, messages, **kwargs):
        cancel_event.set()
        raise ai_lm_studio.LMStudioError("timed out")

    original = ai_lm_studio.chat
    ai_lm_studio.chat = fake_chat
    try:
        try:
            generator.generate(
                class_name="NTAAiSandboxCancelNoFallback",
                ai_cell_id="AI-CELL-MNQ-951",
                instrument="MNQ",
                hypothesis="x",
                parameters={},
                use_llm=True,
                cancel_event=cancel_event,
            )
        except ai_lm_studio.LMStudioCancelled:
            return
        raise AssertionError("cancelled LM error must not fall back to source generation")
    finally:
        ai_lm_studio.chat = original


def t_auto_compile_hook_can_be_disabled() -> None:
    import os
    old = os.environ.get("AI_LAB_AUTO_COMPILE")
    os.environ["AI_LAB_AUTO_COMPILE"] = "0"
    try:
        out = ai_compile_pipeline.trigger_ninjascript_editor_compile(
            "EXP-20260604-9600", class_name="NTAAiSandboxDisabled"
        )
    finally:
        if old is None:
            os.environ.pop("AI_LAB_AUTO_COMPILE", None)
        else:
            os.environ["AI_LAB_AUTO_COMPILE"] = old
    assert out["ok"] is False
    assert out["reason"] == "disabled_by_AI_LAB_AUTO_COMPILE"


# ===== Phase F: outer/inner loops, uniqueness, error memory, stale sweep =====

def t_lm_studio_preflight_blocks_run_without_models() -> None:
    """runner.start() must raise RunBlockedLMStudio when preflight fails and
    NO experiment must be created."""
    with tempfile.TemporaryDirectory() as td:
        _redirect_paths(Path(td))
        runner.reset_for_tests()
        old_lazy = os.environ.get("AI_LAB_LAZY_LM_STUDIO")
        old_bootstrap = os.environ.get("AI_LAB_AUTO_BOOTSTRAP")
        os.environ["AI_LAB_LAZY_LM_STUDIO"] = "0"
        os.environ["AI_LAB_AUTO_BOOTSTRAP"] = "0"

        def fake_preflight(*args, **kwargs):
            return {"ok": False, "missing_roles": [
                {"role": "judge", "reason": "model_unavailable_timeout"},
                {"role": "coder", "reason": "role_unconfigured"},
            ], "role_health": {}}

        original = ai_lm_studio.preflight_all_required_roles
        ai_lm_studio.preflight_all_required_roles = fake_preflight  # type: ignore[assignment]
        try:
            try:
                runner.start({"user_pref_root": "MNQ", "user_capital": 5000,
                              "use_llm": True, "allow_template_fallback": False,
                              "strategy_count": 1})
            except runner.RunBlockedLMStudio as e:
                assert "judge" in str(e) or e.preflight.get("missing_roles")
            else:
                raise AssertionError("RunBlockedLMStudio must be raised")
            # No experiment file should have been created.
            assert list(paths.EXPERIMENTS_DIR.glob("EXP-*.json")) == [], \
                "experiment must NOT be created when preflight fails"
        finally:
            ai_lm_studio.preflight_all_required_roles = original  # type: ignore[assignment]
            if old_lazy is None:
                os.environ.pop("AI_LAB_LAZY_LM_STUDIO", None)
            else:
                os.environ["AI_LAB_LAZY_LM_STUDIO"] = old_lazy
            if old_bootstrap is None:
                os.environ.pop("AI_LAB_AUTO_BOOTSTRAP", None)
            else:
                os.environ["AI_LAB_AUTO_BOOTSTRAP"] = old_bootstrap
            runner.reset_for_tests()


def t_generator_blocks_lm_studio_when_template_fallback_disabled() -> None:
    """When LM returns no usable code AND allow_template_fallback=False, the
    generator must raise LMStudioGenerationFailed instead of silently shipping the
    boilerplate template."""

    def fake_chat(role, messages, **kwargs):
        # Return nothing extractable (no csharp fence, no namespace match).
        return {"content": "sorry, model is busy", "model": "fake", "elapsed_sec": 0.0}

    original = ai_lm_studio.chat
    ai_lm_studio.chat = fake_chat
    try:
        try:
            generator.generate(
                class_name="NTAAiSandboxBlocked",
                ai_cell_id="AI-CELL-MNQ-960",
                instrument="MNQ",
                hypothesis="x",
                parameters={},
                use_llm=True,
                allow_template_fallback=False,
            )
        except ai_lm_studio.LMStudioGenerationFailed:
            return
        raise AssertionError("LMStudioGenerationFailed must be raised when no fallback allowed")
    finally:
        ai_lm_studio.chat = original


def t_generator_uses_template_when_fallback_explicitly_enabled() -> None:
    """allow_template_fallback=True restores the legacy behaviour."""

    def fake_chat(role, messages, **kwargs):
        return {"content": "", "model": "fake", "elapsed_sec": 0.0}

    original = ai_lm_studio.chat
    ai_lm_studio.chat = fake_chat
    try:
        src, report, meta = generator.generate(
            class_name="NTAAiSandboxFallback",
            ai_cell_id="AI-CELL-MNQ-961",
            instrument="MNQ",
            hypothesis="x",
            parameters={},
            use_llm=True,
            allow_template_fallback=True,
        )
        assert meta["path"] == "fallback_template"
        assert "NTAAiSandboxFallback" in src
        assert report.ok is True
    finally:
        ai_lm_studio.chat = original


def t_blocked_lm_studio_is_terminal_status() -> None:
    assert "blocked_lm_studio" in registry.TERMINAL_STATUSES
    assert "blocked_lm_studio" in registry.PORTFOLIO_BLOCKED_STATUSES
    assert "blocked_lm_studio" not in registry.PORTFOLIO_ELIGIBLE_STATUSES


def t_lm_status_pending_without_probe() -> None:
  """Summary/health must not block on chat in lazy mode."""
  import time as _time
  judge = ai_lm_studio.model_for("judge")
  coder = ai_lm_studio.model_for("coder")
  fixer = ai_lm_studio.model_for("compile_error_fixer")
  original_health = ai_lm_studio.health
  ai_lm_studio.reset_readiness_cache_for_tests()
  ai_lm_studio.health = lambda timeout=5: {  # type: ignore[assignment]
      "base_url": "http://localhost:1234/v1",
      "available": True,
      "models": [judge, coder, fixer],
      "missing_roles": [],
      "timeouts": {},
  }
  try:
      out = ai_lm_studio.lm_status(allow_probe=False)
      assert out["probe_pending"] is False
      assert out["run_allowed"] is True
      assert out["status"] == "standby_lazy"
      assert "lazy-режиме" in out["message_ru"]
      ai_lm_studio._READINESS_CACHE = {  # type: ignore[attr-defined]
          "ready": True,
          "run_allowed": True,
          "status": "ready",
          "message_ru": "AI-модели готовы — можно запускать цикл.",
          "preflight": {"ok": True},
          "preflight_checked_at_utc": "2026-06-18T00:00:00Z",
          "probe_pending": False,
      }
      ai_lm_studio._READINESS_CACHE_AT = _time.time()  # type: ignore[attr-defined]
      cached = ai_lm_studio.lm_status(allow_probe=False)
      assert cached["run_allowed"] is True
      assert cached["status"] == "standby_lazy"
  finally:
      ai_lm_studio.health = original_health  # type: ignore[assignment]
      ai_lm_studio.reset_readiness_cache_for_tests()


def t_lm_status_blocks_when_server_down() -> None:
  original_health = ai_lm_studio.health
  ai_lm_studio.reset_readiness_cache_for_tests()
  ai_lm_studio.health = lambda timeout=5: {  # type: ignore[assignment]
      "base_url": "http://localhost:1234/v1",
      "available": False,
      "models": [],
      "missing_roles": [],
      "error": "down",
  }
  try:
      out = ai_lm_studio.lm_status(allow_probe=True)
      assert out["run_allowed"] is False
      assert out["status"] == "server_unavailable"
      assert "недоступна" in out["message_ru"].lower()
  finally:
      ai_lm_studio.health = original_health  # type: ignore[assignment]
      ai_lm_studio.reset_readiness_cache_for_tests()


def t_read_model_summary_includes_lm_run_allowed() -> None:
  from app.ai_lab import read_model
  judge = ai_lm_studio.model_for("judge")
  coder = ai_lm_studio.model_for("coder")
  fixer = ai_lm_studio.model_for("compile_error_fixer")
  original_health = ai_lm_studio.health
  ai_lm_studio.reset_readiness_cache_for_tests()
  ai_lm_studio.health = lambda timeout=5: {  # type: ignore[assignment]
      "base_url": "http://localhost:1234/v1",
      "available": True,
      "models": [judge, coder, fixer],
      "missing_roles": [],
      "timeouts": {},
  }
  try:
      s = read_model.summary()
      lm = s.get("lm_studio") or {}
      assert "run_allowed" in lm
      assert "message_ru" in lm
      assert lm.get("probe_pending") is False
      assert lm.get("status") == "standby_lazy"
  finally:
      ai_lm_studio.health = original_health  # type: ignore[assignment]
      ai_lm_studio.reset_readiness_cache_for_tests()


def t_inner_should_continue_handles_budget_and_status() -> None:
    """The internal mutation loop must:
       - continue when verdict=reject and iterations budget remains;
       - stop when iterations exhausted;
       - stop when status is structural (compile_failed_after_fix_loop)."""
    reject_exp = {"status": "rejected", "verdict": {"outcome": "reject"}}
    assert runner._inner_should_continue(
        reject_exp, iter_idx=1,
        iterations_per_strategy=3, iterations_unlimited=False, deadline=None,
    ) is True
    assert runner._inner_should_continue(
        reject_exp, iter_idx=3,
        iterations_per_strategy=3, iterations_unlimited=False, deadline=None,
    ) is False
    structural_exp = {"status": "compile_failed_after_fix_loop",
                       "verdict": {"outcome": "reject"}}
    assert runner._inner_should_continue(
        structural_exp, iter_idx=1,
        iterations_per_strategy=3, iterations_unlimited=False, deadline=None,
    ) is False
    candidate_exp = {"status": "sandbox_candidate",
                      "verdict": {"outcome": "candidate"}}
    assert runner._inner_should_continue(
        candidate_exp, iter_idx=1,
        iterations_per_strategy=3, iterations_unlimited=False, deadline=None,
    ) is False


def t_inner_should_continue_respects_unlimited_and_deadline() -> None:
    import time as _t
    reject_exp = {"status": "rejected", "verdict": {"outcome": "reject"}}
    # iterations_unlimited=True ignores the numeric cap.
    assert runner._inner_should_continue(
        reject_exp, iter_idx=999,
        iterations_per_strategy=None, iterations_unlimited=True, deadline=None,
    ) is True
    # Past deadline always stops.
    past = _t.time() - 1
    assert runner._inner_should_continue(
        reject_exp, iter_idx=1,
        iterations_per_strategy=None, iterations_unlimited=True, deadline=past,
    ) is False


def t_uniqueness_fingerprint_is_value_independent() -> None:
    """The fingerprint must collapse parameter VALUES but keep their NAMES,
    so a 'tune SL from 20 to 25' tweak is still treated as the same idea."""
    from app.ai_lab import uniqueness as ai_uniqueness
    fp1 = ai_uniqueness.fingerprint_for_source(
        family="SessionEdgeBreakout",
        hypothesis="Breakout on MNQ with EMA filter",
        source="EMA(20) MAX(High,30) EnterLong",
        parameters={"StopLossTicks": 20, "ProfitTargetTicks": 30, "BreakoutLookback": 30},
    )
    fp2 = ai_uniqueness.fingerprint_for_source(
        family="SessionEdgeBreakout",
        hypothesis="Breakout on MNQ with EMA filter",  # same words
        source="EMA(50) MAX(High,40) EnterLong",
        parameters={"StopLossTicks": 25, "ProfitTargetTicks": 40, "BreakoutLookback": 40},
    )
    assert fp1 == fp2, "value drift must not change the fingerprint"
    fp3 = ai_uniqueness.fingerprint_for_source(
        family="VWAPFade",
        hypothesis="VWAP fade against extremes with RSI",
        source="VWAP() RSI(14) EnterShort",
        parameters={"StopLossTicks": 20},
    )
    assert fp3 != fp1, "different family/hypothesis/indicators must yield a different fp"


def t_uniqueness_anti_duplicate_detects_immediate_repeat() -> None:
    from app.ai_lab import uniqueness as ai_uniqueness
    with tempfile.TemporaryDirectory() as td:
        _redirect_paths(Path(td))
        fp = "deadbeef" * 8
        ai_uniqueness.record_fingerprint(fp, experiment_id="EXP-20260617-0001",
                                          root="MNQ", family="X", iteration=1)
        out = ai_uniqueness.check_anti_duplicate(fp, root="MNQ", lookback_n=30)
        assert out["ok"] is False
        assert out["conflict"]["reason"] in {"same_fingerprint_same_root", "immediate_repeat"}
        # Different root → not flagged as duplicate by the same-root rule (still
        # caught as immediate_repeat since it's the last record).
        ai_uniqueness.record_fingerprint("c0ffee" * 10, experiment_id="EXP-20260617-0002",
                                          root="MGC", family="Y", iteration=1)
        out2 = ai_uniqueness.check_anti_duplicate(fp, root="MNQ", lookback_n=30)
        assert out2["ok"] is False, "fingerprint still present in lookback window"


def t_reject_creates_lesson_for_next_iteration() -> None:
    """After a LOW_SCORE rejection, lesson_log must contain a record so
    knowledge.build_context surfaces it in the next prompt."""
    from app.ai_lab import orchestrator, lessons
    with tempfile.TemporaryDirectory() as td:
        _redirect_paths(Path(td))
        # Seed a fake experiment with a finished backtest and seed result files
        # so finalize_backtest can compute a low score.
        skel = registry.new_experiment_skeleton("MNQ", "NTAAiSandboxRej", "h")
        skel["status"] = "backtest_done"
        skel["family"] = "TestFamily"
        skel["primary_capital"] = 5000
        job_id = "JOB-REJ-001"
        job_dir = Path(td) / "jobs" / "done" / job_id
        job_dir.mkdir(parents=True)
        (job_dir / "result.json").write_text(json.dumps({
            "metrics": {"net_profit": -500.0, "trade_count": 5,
                         "profit_factor": 0.5, "max_drawdown": -800.0},
            "context": {"historical_data_fingerprint": {
                "method": "sha256_of_primary_bar_series", "value": "sha256:test",
                "bar_count": 100,
            }},
            "artifacts": {"bars_file": "bars.json"},
        }), encoding="utf-8")
        (job_dir / "bars.json").write_text("[]", encoding="utf-8")
        (job_dir / "trades.json").write_text(json.dumps({"trades": [
            {"exit_time_utc": "2026-01-01T10:00:00Z", "pnl_currency": -100.0}
            for _ in range(5)
        ]}), encoding="utf-8")
        (job_dir / "job.json").write_text(json.dumps({"id": job_id, "status": "done"}), encoding="utf-8")
        skel["backtests"] = [{"job_id": job_id, "status": "done"}]
        registry.write_experiment(skel)

        original = backtest.find_job_dir
        backtest.find_job_dir = lambda jid: job_dir if jid == job_id else None
        try:
            out = orchestrator.finalize_backtest(skel["experiment_id"], job_id)
        finally:
            backtest.find_job_dir = original
        assert out["ok"] is True
        # If the arbitration score landed in the reject band, a lesson must exist.
        if out["status"] == "rejected":
            all_l = lessons.all_lessons(limit=20)
            assert any("TestFamily" in (l.get("summary") or "") for l in all_l), \
                f"expected family lesson, got {all_l}"


def t_operator_note_high_priority_promoted_to_global() -> None:
    with tempfile.TemporaryDirectory() as td:
        _redirect_paths(Path(td))
        eid = "EXP-20260617-9700"
        # priority=high must promote unconditionally.
        ai_operator_notes.add(eid, "use VWAP filter on MNQ breakouts", priority="high")
        globals_after = ai_operator_notes.list_global_notes(limit=10)
        assert any("VWAP filter" in (g.get("text") or "") for g in globals_after), globals_after
        # keyword 'не повторяй' must also promote at normal priority.
        ai_operator_notes.add(eid, "не повторяй family SessionEdgeBreakout")
        globals_after2 = ai_operator_notes.list_global_notes(limit=10)
        assert any("не повторяй" in (g.get("text") or "") for g in globals_after2), globals_after2
        # Plain note without keywords stays local only.
        ai_operator_notes.add(eid, "normal hint about something")
        globals_after3 = ai_operator_notes.list_global_notes(limit=10)
        assert not any("normal hint about something" in (g.get("text") or "")
                       for g in globals_after3), globals_after3


def t_global_operator_notes_appear_in_knowledge_context() -> None:
    with tempfile.TemporaryDirectory() as td:
        _redirect_paths(Path(td))
        ai_operator_notes.promote_to_global(
            text="никогда не используй MaxTradesPerDay > 3", priority="high",
            source_experiment_id="EXP-MANUAL", trigger="explicit",
        )
        ctx = knowledge.build_context("MNQ", user_goal="test")
        assert any("MaxTradesPerDay" in (n.get("text") or "")
                   for n in ctx.get("global_operator_notes", []))
        assert "Global operator rules" in ctx.get("prompt_context", "")
        assert "MaxTradesPerDay" in ctx.get("prompt_context", "")


def t_stale_sweep_cancels_quiet_experiments() -> None:
    from app.ai_lab import stale_sweep
    with tempfile.TemporaryDirectory() as td:
        _redirect_paths(Path(td))
        # Two experiments: one stale (activity 10h ago), one fresh (now).
        stale = registry.new_experiment_skeleton("MNQ", "NTAAiSandboxStale", "h")
        stale["status"] = "generating"
        registry.write_experiment(stale)
        activity.log(stale["experiment_id"], "runner", "pipeline_started",
                     level="info")
        # Rewrite the activity file with a ts 10 hours in the past.
        p = paths.ACTIVITY_DIR / f"{stale['experiment_id']}.jsonl"
        rec = json.loads(p.read_text(encoding="utf-8").strip())
        from datetime import datetime as _dt, timezone as _tz, timedelta as _td
        rec["ts"] = (_dt.now(_tz.utc) - _td(hours=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
        p.write_text(json.dumps(rec) + "\n", encoding="utf-8")

        fresh = registry.new_experiment_skeleton("MNQ", "NTAAiSandboxFresh", "h")
        fresh["status"] = "generating"
        registry.write_experiment(fresh)
        activity.log(fresh["experiment_id"], "runner", "pipeline_started", level="info")

        out = stale_sweep.sweep_stale(heartbeat_ttl_hours=6.0)
        cancelled_ids = [c["experiment_id"] for c in out["cancelled"]]
        assert stale["experiment_id"] in cancelled_ids
        assert fresh["experiment_id"] not in cancelled_ids
        stale_exp = registry.read_experiment(stale["experiment_id"])
        assert stale_exp["status"] == "cancelled"
        assert (stale_exp.get("stale_sweep") or {}).get("ttl_hours") == 6.0


def t_errors_summary_endpoint_payload_shape() -> None:
    """The /api/ai-lab/errors/summary response shape — uses the same data
    sources as the HTTP handler does."""
    with tempfile.TemporaryDirectory() as td:
        _redirect_paths(Path(td))
        # Seed a pattern, a lesson and a global note.
        errors.log_error("EXP-20260617-0010", "compile", "csc_error",
                          "error CS0103: foo (12,5)", severity="error")
        from app.ai_lab import lessons as _lessons
        _lessons.record_lesson(summary="avoid X on MNQ", source="rejection",
                               scope="family", scope_key="X", rule="avoid: X")
        ai_operator_notes.promote_to_global(text="rule: example", priority="high")

        payload = {
            "patterns": errors.top_repeated_patterns(threshold=1)[:30],
            "recent_errors": errors.recent_errors(limit=50),
            "lessons_recent": _lessons.all_lessons(limit=20),
            "global_operator_notes": ai_operator_notes.list_global_notes(limit=20),
            "lessons_count": len(_lessons.all_lessons(limit=10_000)),
        }
        assert payload["lessons_count"] >= 1
        assert any("avoid X" in (l.get("summary") or "") for l in payload["lessons_recent"])
        assert any("example" in (n.get("text") or "") for n in payload["global_operator_notes"])
        assert any(p.get("error_type") == "csc_error" for p in payload["patterns"])


def t_runner_run_status_returns_active_run_snapshot() -> None:
    """run_status reflects RUN-id, indices, and clears after reset."""
    import threading as _th
    with tempfile.TemporaryDirectory() as td:
        _redirect_paths(Path(td))
        runner.reset_for_tests()
        assert runner.run_status() is None
        # Manually seed _RUN_STATE as the worker would.
        runner._RUN_STATE = {
            "run_id": "RUN-test01",
            "started_utc": "2026-06-17T00:00:00Z",
            "strategy_count": 2,
            "iterations_per_strategy": 3,
            "iterations_unlimited": False,
            "max_total_runtime_minutes": 60,
            "deadline_epoch": None,
            "strategy_idx": 1,
            "iteration_idx": 2,
            "current_experiment_id": None,
            "experiments": [],
            "candidate_count": 0,
            "cancelled": False,
            "stop_on_first_candidate": False,
            "use_llm": True,
            "allow_template_fallback": False,
            "preflight": {"ok": True},
            "cancel_event": _th.Event(),
        }
        snap = runner.run_status()
        assert snap is not None
        assert snap["run_id"] == "RUN-test01"
        assert snap["strategy_idx"] == 1
        assert snap["iteration_idx"] == 2
        assert "cancel_event" not in snap, "cancel_event must not leak through API"
        runner.reset_for_tests()
        assert runner.run_status() is None


def t_runner_request_run_cancel_sets_flag() -> None:
    import threading as _th
    with tempfile.TemporaryDirectory() as td:
        _redirect_paths(Path(td))
        runner.reset_for_tests()
        # No active run.
        out = runner.request_run_cancel()
        assert out["ok"] is False
        # Active run with cancel event.
        runner._RUN_STATE = {
            "run_id": "RUN-cancel01",
            "current_experiment_id": None,
            "cancelled": False,
            "cancel_event": _th.Event(),
            "strategy_idx": 1,
            "iteration_idx": 1,
        }
        out2 = runner.request_run_cancel()
        assert out2["ok"] is True
        assert runner._RUN_STATE["cancelled"] is True
        assert runner._RUN_STATE["cancel_event"].is_set()
        runner.reset_for_tests()


def t_runner_updates_provisional_iteration_with_final_outcome() -> None:
    with tempfile.TemporaryDirectory() as td:
        _redirect_paths(Path(td))
        exp = registry.new_experiment_skeleton(
            "MNQ", "NTAAiSandboxIterationFinal", "iteration-final"
        )
        exp["status"] = "rejected"
        exp["strategy_source"]["sha256"] = "final-sha"
        exp["verdict"] = {
            "outcome": "reject",
            "rejection_code": "LOW_SCORE",
        }
        exp["analysis"] = {
            "pf_after_commission": 0.81,
            "trades_total": 17,
        }
        exp["arbitration"] = {"score": -4.2}
        exp["iteration_history"] = [{
            "iteration": 2,
            "sha256": "provisional-sha",
            "status": "generated",
            "mirror_history_path": "v1.cs",
        }]
        registry.write_experiment(exp)

        runner._record_iteration_in_experiment(exp, 2)
        saved = registry.read_experiment(exp["experiment_id"])
        rows = saved.get("iteration_history") or []
        assert len(rows) == 1, rows
        row = rows[0]
        assert row["sha256"] == "final-sha"
        assert row["status"] == "rejected"
        assert row["verdict"] == "reject"
        assert row["rejection_code"] == "LOW_SCORE"
        assert row["pf_after_commission"] == 0.81
        assert row["trades_total"] == 17
        assert row["score"] == -4.2
        assert row["mirror_history_path"] == "v1.cs"


def t_runner_stops_after_failed_mutation_and_clears_run_state() -> None:
    import threading as _th
    from app.ai_lab import mutation

    with tempfile.TemporaryDirectory() as td:
        _redirect_paths(Path(td))
        runner.reset_for_tests()
        exp = registry.new_experiment_skeleton(
            "MNQ", "NTAAiSandboxMutationStop", "mutation-stop"
        )
        exp["status"] = "rejected"
        exp["verdict"] = {
            "outcome": "reject",
            "rejection_code": "LOW_SCORE",
        }
        registry.write_experiment(exp)
        event = _th.Event()
        runner._CURRENT = {
            "experiment_id": exp["experiment_id"],
            "cancel_event": event,
        }
        runner._RUN_STATE = {
            "run_id": "RUN-mutation-stop",
            "strategy_count": 1,
            "iterations_per_strategy": 3,
            "iterations_unlimited": False,
            "max_total_runtime_minutes": None,
            "strategy_idx": 1,
            "iteration_idx": 1,
            "current_experiment_id": exp["experiment_id"],
            "experiments": [exp["experiment_id"]],
            "candidate_count": 0,
            "cancelled": False,
            "stop_on_first_candidate": False,
            "cancel_event": event,
        }

        calls = {"execute": 0, "mutation": 0}
        original_execute = runner._execute_one_cell
        original_prepare = mutation.prepare_next

        def fake_execute(experiment_id, args):
            calls["execute"] += 1

        def fake_prepare(experiment_id, prev_iteration_idx):
            calls["mutation"] += 1
            return {"ok": False, "error": "duplicate"}

        runner._execute_one_cell = fake_execute  # type: ignore[assignment]
        mutation.prepare_next = fake_prepare  # type: ignore[assignment]
        try:
            runner._run_pipeline_worker(
                exp["experiment_id"],
                {
                    "strategy_count": 1,
                    "iterations_per_strategy": 3,
                    "iterations_unlimited": False,
                    "max_total_runtime_minutes": None,
                    "stop_on_first_candidate": False,
                },
                "RUN-mutation-stop",
            )
        finally:
            runner._execute_one_cell = original_execute  # type: ignore[assignment]
            mutation.prepare_next = original_prepare  # type: ignore[assignment]
            runner.reset_for_tests()

        assert calls == {"execute": 1, "mutation": 1}, calls
        assert runner.run_status() is None


def t_mutation_archives_versioned_copy_and_plans_next_pass() -> None:
    """Mutation archives v1 and prepares one normal judge/coder pass.

    It must not invoke a second standalone coder call whose result would be
    overwritten immediately by orchestrator.run_pipeline.
    """
    from app.ai_lab import mutation
    with tempfile.TemporaryDirectory() as td:
        _redirect_paths(Path(td))
        # Build a valid prior source via fallback_template, write to sandbox.
        ai_cell = "AI-CELL-MNQ-901"
        class_name = "NTAAiSandboxMut"
        prior = generator.fallback_template(
            class_name=class_name, ai_cell_id=ai_cell,
            instrument="MNQ", parameters={},
        )
        sandbox_path, mirror_path = generator.write_to_sandbox(class_name, prior)
        skel = registry.new_experiment_skeleton("MNQ", class_name, "x")
        skel["ai_cell_id"] = ai_cell
        skel["status"] = "rejected"
        skel["family"] = "TestFam"
        skel["hypothesis"] = "previous hypothesis"
        skel["parameters"] = {"StopLossTicks": 20}
        skel["strategy_source"] = {"sandbox_path": str(sandbox_path),
                                    "mirror_path": str(mirror_path)}
        skel["iteration_history"] = [{"iteration": 1, "sha256": "abc"}]
        registry.write_experiment(skel)

        captured = {}

        def fake_chat(role, messages, **kwargs):
            captured["called"] = True
            raise AssertionError("prepare_next must not call LM Studio")

        original = ai_lm_studio.chat
        ai_lm_studio.chat = fake_chat
        try:
            out = mutation.prepare_next(skel["experiment_id"], prev_iteration_idx=1)
        finally:
            ai_lm_studio.chat = original
        assert captured.get("called") is not True
        assert out["ok"] is True, out
        assert out["iteration"] == 2
        assert out["pending_context"] is True
        # History file v1.cs must exist under mirrors/{cell}/history/.
        hist_dir = paths.MIRRORS_DIR / ai_cell / "history"
        assert (hist_dir / "v1.cs").exists(), f"missing {hist_dir / 'v1.cs'}"
        # Experiment iteration_history must contain the new iteration entry.
        exp = registry.read_experiment(skel["experiment_id"])
        iters = exp.get("iteration_history") or []
        assert any(int(h.get("iteration") or 0) == 2 for h in iters), iters
        assert exp.get("current_iteration") == 2
        assert exp.get("status") == "generated"  # re-armed for next pipeline
        assert "Previous iteration outcome" in exp.get("pending_mutation_context", "")
        row = next(h for h in iters if int(h.get("iteration") or 0) == 2)
        assert row["status"] == "mutation_planned"
        assert row["sha256"] is None


def t_runner_normalizes_legacy_max_cells_to_strategy_count() -> None:
    """The new schema accepts legacy max_cells_per_run as an alias.
    runner.start should fail with RunBlockedLMStudio (preflight is gated),
    but only AFTER normalization computes the right strategy_count internally."""
    with tempfile.TemporaryDirectory() as td:
        _redirect_paths(Path(td))
        runner.reset_for_tests()
        old_lazy = os.environ.get("AI_LAB_LAZY_LM_STUDIO")
        old_bootstrap = os.environ.get("AI_LAB_AUTO_BOOTSTRAP")
        os.environ["AI_LAB_LAZY_LM_STUDIO"] = "0"
        os.environ["AI_LAB_AUTO_BOOTSTRAP"] = "0"

        captured = {}
        original_skel = None  # we won't reach start_skeleton

        def fake_preflight(*args, **kwargs):
            # Capture and refuse.
            captured["called"] = True
            return {"ok": False, "missing_roles": [{"role": "judge", "reason": "x"}],
                    "role_health": {}}

        original = ai_lm_studio.preflight_all_required_roles
        ai_lm_studio.preflight_all_required_roles = fake_preflight  # type: ignore[assignment]
        try:
            try:
                runner.start({"use_llm": True, "max_cells_per_run": 5,
                              "max_mutations_per_cell": 2,
                              "max_total_runtime_minutes": 30})
            except runner.RunBlockedLMStudio:
                pass
            assert captured.get("called") is True
        finally:
            ai_lm_studio.preflight_all_required_roles = original  # type: ignore[assignment]
            if old_lazy is None:
                os.environ.pop("AI_LAB_LAZY_LM_STUDIO", None)
            else:
                os.environ["AI_LAB_LAZY_LM_STUDIO"] = old_lazy
            if old_bootstrap is None:
                os.environ.pop("AI_LAB_AUTO_BOOTSTRAP", None)
            else:
                os.environ["AI_LAB_AUTO_BOOTSTRAP"] = old_bootstrap
            runner.reset_for_tests()


def main() -> int:
    print("test_ai_lab")
    tests = [
        ("t01 arbitration scores high-growth strategy", t_arbitration_high_growth_scores_well),
        ("t02 arbitration penalizes repeat mistakes", t_arbitration_repeat_mistake_penalizes),
        ("t03 arbitration rejects no-trade results", t_arbitration_no_trades_rejects),
        ("t03b arbitration calibrates reject/mutate/candidate",
         t_arbitration_quality_classification_is_calibrated),
        ("t04 validator accepts compliant source", t_validator_accepts_minimal_ok),
        ("t05 validator blocks production class prefix", t_validator_blocks_production_class_prefix),
        ("t06 validator blocks forbidden API", t_validator_blocks_forbidden_api),
        ("t07 validator requires risk shell", t_validator_requires_risk_shell),
        ("t07b validator requires session gate and daily PnL snapshot",
         t_validator_requires_explicit_session_and_daily_pnl_snapshot),
        ("t08 validator blocks production CELL id", t_validator_blocks_production_cell_id),
        ("t09 validator blocks known NT8 compile errors", t_validator_blocks_known_nt8_compile_errors),
        ("t10 generator fallback template validates", t_generator_fallback_template_validates),
        ("t10a validator blocks anonymous signals and forced minimum risk",
         t_validator_blocks_anonymous_signals_and_forced_minimum_risk),
        ("t10b validator allows AI-CELL identifier suffix",
         t_validator_allows_ai_cell_identifier_suffix),
        ("t10c static autofix prompt contains prior source and identity",
         t_static_autofix_prompt_contains_prior_source_and_identity),
        ("t10d generator repairs common NT8 source slips",
         t_generator_repairs_common_nt8_source_slips),
        ("t10e generator normalizes drifted production CELL id",
         t_generator_normalizes_drifted_production_cell_id),
        ("t10f deterministic VWAP renderer validates",
         t_deterministic_vwap_renderer_validates_without_generic_breakout),
        ("t11 goal parser extracts user constraints", t_goal_parser_extracts_user_constraints),
        ("t11b goal parser ignores substrings and negated patterns",
         t_goal_parser_ignores_substrings_and_negated_patterns),
        ("t12 knowledge context reads reference library and sources", t_knowledge_context_reads_reference_library_and_sources),
        ("t12b knowledge shortlist excludes forbidden references",
         t_knowledge_reference_shortlist_excludes_forbidden_refs),
        ("t12c knowledge keeps reading existing user research",
         t_knowledge_context_keeps_reading_existing_user_research),
        ("t13 generator prompt includes knowledge context", t_generator_prompt_includes_knowledge_context),
        ("t14 runner research loop continues after rejected", t_runner_research_loop_continues_after_rejected),
        ("t15 signal sanity counts breakout signals", t_signal_sanity_counts_breakout_signals),
        ("t15b signal sanity dispatches family estimator",
         t_signal_sanity_dispatches_family_and_flags_overtrading),
        ("t16 backtest submit uses queue commission contract", t_backtest_submit_uses_queue_commission_contract),
        ("t16b backtest maps LLM parameter names",
         t_backtest_maps_llm_parameter_names_to_nt8_properties),
        ("t17 registry skeleton+write roundtrip", t_registry_skeleton_and_write_roundtrip),
        ("t18 registry refuses non-AI_SANDBOX namespace", t_registry_rejects_bad_namespace),
        ("t19 registry AI-CELL increments per root", t_registry_cell_id_increments_per_root),
        ("t20 portfolio excludes rejected and 0-trade experiments", t_portfolio_excludes_rejected_and_zero_trade_experiments),
        ("t21 portfolio requires manual membership action", t_portfolio_requires_manual_membership_action),
        ("t22 errors normalize collapses volatile bits", t_errors_normalize_collapses_volatile_bits),
        ("t23 errors pattern_counts aggregate", t_errors_pattern_counts_aggregate),
        ("t24 lm_studio extract_json_block", t_lm_studio_extract_json_block),
        ("t25 lm_studio model routes complete", t_lm_studio_model_routes_have_all_roles),
        ("t26 activity log uses line offset", t_activity_log_uses_line_offset),
        ("t27 status lifecycle no fake ready", t_status_lifecycle_no_fake_ready),
        ("t28 runner single-flight", t_runner_single_flight),
        ("t29 guards block production writes", t_guards_block_production_writes),
        ("t30 generator refuses invalid write", t_generator_refuses_invalid_write),
        ("t31 compile_errors read_since filters by ts + class", t_compile_errors_read_since),
        ("t32 compile_errors append_manual parses CS lines", t_compile_errors_append_manual),
        ("t32b compile pipeline parses NinjaScript Editor grid",
         t_compile_pipeline_parses_ninjascript_editor_grid),
        ("t32c compile quarantine moves broken AI source",
         t_compile_quarantine_moves_only_ai_sandbox_source),
        ("t33 lm_studio default timeouts are bounded/no retries", t_lmstudio_default_timeouts_are_bounded),
        ("t33a llm_timeouts config quality_over_speed invariants", t_llm_timeouts_config),
        ("t33b lm_studio default URL uses IPv4 loopback",
         t_lmstudio_default_base_url_uses_ipv4_loopback),
        ("t33c AI UI preserves ready state during background probe",
         t_ai_strategy_ui_preserves_ready_state_during_background_probe),
        ("t33d AI UI hides terminal heartbeat",
         t_ai_strategy_ui_hides_terminal_heartbeat),
        ("t33e bootstrap status shape without side effects",
         t_bootstrap_status_shape_without_side_effects),
        ("t33e2 bootstrap never autostarts NinjaTrader without env opt-in",
         t_bootstrap_never_autostarts_ninjatrader_without_env_opt_in),
        ("t33f AI UI has bootstrap controls",
         t_ai_strategy_ui_has_bootstrap_controls),
        ("t34 heartbeat emits during long stage", t_heartbeat_emits_during_long_stage),
        ("t35 operator notes roundtrip", t_operator_notes_roundtrip),
        ("t36 operator notes apply_checkpoint logs+marks", t_operator_notes_apply_checkpoint_logs_and_marks),
        ("t37 autofix prompt includes errors+notes", t_autofix_prompt_includes_errors_and_notes),
        ("t37b compile autofix prompt adds NinjaTrader.Cbi hint",
         t_compile_autofix_prompt_adds_cbi_hint),
        ("t37c validator blocks wrong OnPositionUpdate signature",
         t_validator_blocks_wrong_on_position_update_signature),
        ("t38 cancel request sets event + cancelled terminal", t_cancel_request_sets_event_and_terminal),
        ("t39 registry cancelled is terminal", t_registry_cancelled_is_terminal),
        ("t40 backtest_payload shape", t_backtest_payload_shape),
        ("t41 analysis_pack reads bridge trade fields+metrics", t_analysis_pack_reads_bridge_trade_fields_and_metrics),
        ("t42 analysis_pack uses round-turn commission adjustment", t_analysis_pack_uses_round_turn_commission_adjustment),
        ("t43 generator propagates LMStudioCancelled", t_generator_propagates_lmstudio_cancelled),
        ("t44 generator does not fallback after cancelled LM error", t_generator_does_not_fallback_after_cancelled_lm_error),
        ("t45 auto compile hook can be disabled", t_auto_compile_hook_can_be_disabled),
        ("t46 LM Studio preflight blocks run without models",
         t_lm_studio_preflight_blocks_run_without_models),
        ("t47 generator blocks when fallback disabled",
         t_generator_blocks_lm_studio_when_template_fallback_disabled),
        ("t48 generator uses template when fallback explicitly enabled",
         t_generator_uses_template_when_fallback_explicitly_enabled),
        ("t49 blocked_lm_studio is terminal", t_blocked_lm_studio_is_terminal_status),
        ("t49b lm_status pending without probe", t_lm_status_pending_without_probe),
        ("t49c lm_status blocks when server down", t_lm_status_blocks_when_server_down),
        ("t49d summary includes lm run_allowed", t_read_model_summary_includes_lm_run_allowed),
        ("t50 inner_should_continue handles budget and status",
         t_inner_should_continue_handles_budget_and_status),
        ("t51 inner_should_continue respects unlimited and deadline",
         t_inner_should_continue_respects_unlimited_and_deadline),
        ("t52 uniqueness fingerprint is value-independent",
         t_uniqueness_fingerprint_is_value_independent),
        ("t53 uniqueness anti-duplicate detects immediate repeat",
         t_uniqueness_anti_duplicate_detects_immediate_repeat),
        ("t54 reject creates lesson for next iteration",
         t_reject_creates_lesson_for_next_iteration),
        ("t55 operator note high-priority promoted to global",
         t_operator_note_high_priority_promoted_to_global),
        ("t56 global operator notes appear in knowledge context",
         t_global_operator_notes_appear_in_knowledge_context),
        ("t57 stale sweep cancels quiet experiments",
         t_stale_sweep_cancels_quiet_experiments),
        ("t58 errors/summary payload shape", t_errors_summary_endpoint_payload_shape),
        ("t59 runner.run_status returns active run snapshot",
         t_runner_run_status_returns_active_run_snapshot),
        ("t60 runner.request_run_cancel sets flag",
         t_runner_request_run_cancel_sets_flag),
        ("t60b runner updates provisional iteration with final outcome",
         t_runner_updates_provisional_iteration_with_final_outcome),
        ("t60c runner stops after failed mutation and clears run state",
         t_runner_stops_after_failed_mutation_and_clears_run_state),
        ("t61 mutation archives version and plans one next pass",
         t_mutation_archives_versioned_copy_and_plans_next_pass),
        ("t62 runner normalizes legacy max_cells_per_run",
         t_runner_normalizes_legacy_max_cells_to_strategy_count),
        ("t63 runner busy current is JSON-safe",
         t_runner_busy_current_is_json_safe),
        ("t64 runner busy rejects before LM preflight",
         t_runner_busy_rejects_before_lm_preflight),
    ]
    for name, fn in tests:
        _record(name, fn)
    print(f"\n{len(PASSED)}/{len(PASSED) + len(FAILED)} passed")
    if FAILED:
        for n, err in FAILED:
            print(f"\n--- {n} ---\n{err}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
