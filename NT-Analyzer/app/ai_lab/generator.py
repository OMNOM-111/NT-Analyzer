"""AI strategy code generator.

Uses LM Studio coder model with a deterministic prompt + a fallback template.
The fallback ensures the lab can run end-to-end even if LM Studio is offline
(orchestrator records the fallback path in the experiment record).
"""

from __future__ import annotations

import hashlib
import re
import threading
from pathlib import Path
from textwrap import dedent
from typing import Any, Dict, List, Optional, Tuple

from .. import governance
from . import activity, agent_router, cloud_agents, lm_studio, paths
from .guards import assert_sandbox_only
from .validator import ValidationReport, validate_source


def _read_system_prompt() -> str:
    p = paths.PROMPTS_DIR / "system_coder.txt"
    if p.exists():
        return p.read_text(encoding="utf-8")
    return "You write safe NinjaTrader 8 C# strategies."


def _preview(text: str, limit: int = 220) -> str:
    return re.sub(r"\s+", " ", text or "").strip()[:limit]


def _log_activity(experiment_id: Optional[str], action: str, **fields: Any) -> None:
    if not experiment_id:
        return
    try:
        activity.log(experiment_id, "generate", action, level="info", **fields)
    except Exception:
        pass


def _runtime_defaults() -> Dict[str, Any]:
    return governance.runtime_defaults()


def _default_ai_session_bounds() -> Tuple[str, str, int, int]:
    raw = str(_runtime_defaults().get("ai_lab_session_window_pt", "06:30-12:30 PT") or "")
    match = re.search(r"(\d{2}:\d{2})\s*-\s*(\d{2}:\d{2})", raw)
    start_text, end_text = ("06:30", "12:30")
    if match:
        start_text, end_text = match.group(1), match.group(2)

    def hhmmss(value: str, fallback: int) -> int:
        digits = re.sub(r"[^0-9]", "", value or "")
        if len(digits) == 4:
            digits += "00"
        try:
            parsed = int(digits)
        except ValueError:
            return fallback
        return parsed if 0 <= parsed <= 235959 else fallback

    return start_text, end_text, hhmmss(start_text, 63000), hhmmss(end_text, 123000)


def class_name_for(target_root: str, ai_cell_id: str, family: str = "OrbFade") -> str:
    seq = ai_cell_id.split("-")[-1]
    root = target_root.title()
    fam = "".join(
        token[:1].upper() + token[1:]
        for token in re.split(r"[^A-Za-z0-9]+", family)
        if token
    )
    return f"NTAAiSandbox{fam}{root}{seq}"


def _extract_csharp(text: str) -> Optional[str]:
    if not text:
        return None
    fence_start = text.find("```csharp")
    if fence_start >= 0:
        body = text[fence_start + len("```csharp"):]
        end = body.find("```")
        if end >= 0:
            return body[:end].strip()
    fence_start = text.find("```")
    if fence_start >= 0:
        body = text[fence_start + 3:]
        end = body.find("```")
        if end >= 0:
            return body[:end].strip()
    if "namespace NinjaTrader.NinjaScript.Strategies" in text:
        return text
    return None


def normalize_ai_cell_id(source: str, ai_cell_id: str) -> Tuple[str, bool]:
    """Replace model-drifted production CELL ids with the assigned AI id."""
    normalized, count = re.subn(
        r"(?<!AI-)\bCELL-\d{3}\b",
        ai_cell_id,
        source or "",
    )
    return normalized, bool(count)


def repair_common_nt8_source(source: str) -> Tuple[str, List[str]]:
    """Apply narrow, semantics-preserving repairs for recurring NT8 API slips."""
    text = source or ""
    repairs: List[str] = []

    def remove_override_method(method_name: str) -> int:
        """Remove a forbidden override, including its balanced method body."""
        nonlocal text
        removed = 0
        pattern = re.compile(
            rf"protected\s+override\s+void\s+{re.escape(method_name)}\s*\([^)]*\)\s*\{{",
            re.I | re.S,
        )
        while True:
            match = pattern.search(text)
            if not match:
                break
            depth = 1
            idx = match.end()
            in_string = False
            escaped = False
            while idx < len(text) and depth:
                ch = text[idx]
                if escaped:
                    escaped = False
                elif ch == "\\" and in_string:
                    escaped = True
                elif ch == '"':
                    in_string = not in_string
                elif not in_string:
                    if ch == "{":
                        depth += 1
                    elif ch == "}":
                        depth -= 1
                idx += 1
            if depth:
                break
            text = text[:match.start()] + text[idx:]
            removed += 1
        return removed

    def ensure_using(namespace: str, *, when: bool, label: str) -> None:
        nonlocal text
        using_line = f"using {namespace};"
        if not when or using_line in text:
            return
        match = re.search(r"(?m)^(using\s+[^;]+;\s*)+", text)
        if match:
            text = text[:match.end()] + using_line + "\n" + text[match.end():]
        else:
            text = using_line + "\n" + text
        repairs.append(label)

    ensure_using(
        "NinjaTrader.Cbi",
        when=bool(re.search(r"\b(?:Execution|MarketPosition|Order|Position)\b", text)),
        label="added_using_ninjatrader_cbi",
    )
    ensure_using(
        "NinjaTrader.NinjaScript.Indicators",
        when=bool(re.search(
            r"\b(?:ATR|Bollinger|EMA|MAX|MIN|RSI|SMA|StdDev)\s*\(",
            text,
        )),
        label="added_using_ninjascript_indicators",
    )
    ensure_using(
        "NinjaTrader.Data",
        when="BarsPeriodType" in text,
        label="added_using_ninjatrader_data",
    )

    new_text, count = re.subn(
        r"(?m)^\s*BarsPeriod(?:Type|Value)\s*=.*?;\s*(?:\r?\n)?",
        "",
        text,
    )
    if count:
        text = new_text
        repairs.append("removed_invalid_primary_bars_period_assignment")

    new_text, count = re.subn(
        r"(?m)^\s*AddDataSeries\s*\([^;]*\);\s*(?:\r?\n)?",
        "",
        text,
    )
    if count:
        text = new_text
        repairs.append("removed_secondary_data_series")

    position_pattern = re.compile(
        r"protected\s+override\s+void\s+OnPositionUpdate\s*\([^)]*\)",
        re.I | re.S,
    )
    if position_pattern.search(text):
        canonical = (
            "protected override void OnPositionUpdate("
            "Position position, double averagePrice, int quantity, "
            "MarketPosition marketPosition)"
        )
        new_text, count = position_pattern.subn(canonical, text, count=1)
        if count and new_text != text:
            text = new_text
            repairs.append("normalized_on_position_update_signature")

    if remove_override_method("OnExecutionUpdate"):
        repairs.append("removed_forbidden_on_execution_update")

    new_text, count = re.subn(
        r"DateTime\s+([A-Za-z_]\w*)\s*=\s*Time\s*\[\s*0\s*\]\s*;\s*"
        r"DateTime\s+([A-Za-z_]\w*)\s*=\s*TimeZoneInfo\.ConvertTimeFromUtc"
        r"\s*\(\s*\1\s*,\s*([A-Za-z_]\w*)\s*\)\s*;",
        r"DateTime \2 = TimeZoneInfo.ConvertTime(Time[0], \3);",
        text,
        flags=re.I | re.S,
    )
    if count:
        text = new_text
        repairs.append("corrected_pacific_time_conversion")

    new_text, count = re.subn(
        r"(?m)(SetStopLoss\s*\([^;\r\n]*),\s*0\s*\)\s*;",
        r"\1, false);",
        text,
    )
    if count:
        text = new_text
        repairs.append("corrected_set_stop_loss_simulated_flag")

    long_signals = re.findall(
        r"\bEnterLong\s*\(\s*(?:[^,\r\n]+,\s*)?\"([^\"]+)\"\s*\)",
        text,
    )
    if long_signals:
        new_text, count = re.subn(
            r"\bExitLong\s*\(\s*(\"[^\"]+\")\s*,\s*Position\.Quantity\s*\)",
            rf'ExitLong(\1, "{long_signals[-1]}")',
            text,
        )
        if count:
            text = new_text
            repairs.append("corrected_exit_long_from_entry_signal")

    short_signals = re.findall(
        r"\bEnterShort\s*\(\s*(?:[^,\r\n]+,\s*)?\"([^\"]+)\"\s*\)",
        text,
    )
    if short_signals:
        new_text, count = re.subn(
            r"\bExitShort\s*\(\s*(\"[^\"]+\")\s*,\s*Position\.Quantity\s*\)",
            rf'ExitShort(\1, "{short_signals[-1]}")',
            text,
        )
        if count:
            text = new_text
            repairs.append("corrected_exit_short_from_entry_signal")

    bollinger_pattern = re.compile(
        r"\bBollinger\s*\(\s*([A-Za-z_]\w*(?:Period|Length))\s*,\s*"
        r"([A-Za-z_]\w*(?:Multiplier|StdDev|Deviation))\s*\)"
    )
    new_text, count = bollinger_pattern.subn(r"Bollinger(\2, \1)", text)
    if count:
        text = new_text
        repairs.append("corrected_bollinger_argument_order")

    new_text, count = re.subn(
        r"\bpublic\s+double\s+([A-Za-z_]\w*(?:Period|Lookback))"
        r"(\s*\{\s*get\s*;\s*set\s*;\s*\}\s*=\s*)(\d+)\.0\s*;",
        r"public int \1\2\3;",
        text,
    )
    if count:
        text = new_text
        repairs.append("normalized_period_property_to_int")

    new_text, count = re.subn(
        r"\[Range\(\s*\d+\.\d+\s*,\s*\d+\.\d+\s*\),\s*NinjaScriptProperty\]"
        r"(\s*public\s+int\s+[A-Za-z_]\w*(?:Period|Lookback)\b)",
        r"[Range(1, 1000), NinjaScriptProperty]\1",
        text,
    )
    if count:
        text = new_text
        repairs.append("normalized_integer_period_range")

    return text, repairs


def fallback_template(
    class_name: str,
    ai_cell_id: str,
    instrument: str,
    parameters: Optional[Dict[str, Any]] = None,
    *,
    family: str = "",
    hypothesis: str = "",
    reference_id: str = "",
) -> str:
    def _hhmmss(value: Any, fallback: int) -> int:
        digits = re.sub(r"\D", "", str(value or ""))
        if len(digits) == 4:
            digits += "00"
        try:
            parsed = int(digits)
        except ValueError:
            return fallback
        return parsed if 0 <= parsed <= 235959 else fallback

    p = parameters or {}
    quantity = int(p.get("Quantity", 1))
    sl = int(p.get("StopLossTicks", 20))
    tp = int(p.get("ProfitTargetTicks", 30))
    mdl = int(p.get("MaxDailyLoss", 400))
    max_trades = int(p.get("MaxTradesPerDay", 3))
    breakout_lookback = int(p.get("BreakoutLookback", 20))
    defaults = _runtime_defaults()
    round_turn_commission = float(
        p.get("RoundTurnCommission", defaults.get("round_turn_commission", 1.90))
    )
    slippage_ticks = int(p.get("SlippageTicks", defaults.get("slippage_ticks", 1)))
    default_start_pt, default_end_pt, default_start_time, default_end_time = _default_ai_session_bounds()
    session_start_pt = p.get("SessionStartPT", default_start_pt)
    session_end_pt = p.get("SessionEndPT", default_end_pt)
    session_start_time = _hhmmss(
        p.get("SessionStartTimePT", session_start_pt), default_start_time
    )
    session_end_time = _hhmmss(
        p.get("SessionEndTimePT", session_end_pt), default_end_time
    )
    family_text = f"{family} {hypothesis}".lower()
    deterministic_mode = "breakout"
    extra_fields = ""
    reset_family_state = ""
    update_family_state = ""
    if any(token in family_text for token in ("vwap", "volume")):
        deterministic_mode = "vwap_liquidity_reversal"
        try:
            volume_window = max(5, min(50, int(float(
                p.get("volume_window", p.get("vwap_window", 20))
            ))))
        except (TypeError, ValueError):
            volume_window = 20
        try:
            volume_multiplier = max(1.0, min(3.0, float(
                p.get("volume_multiplier", p.get("MinVolumeFactor", 1.20))
            )))
        except (TypeError, ValueError):
            volume_multiplier = 1.20
        try:
            trend_ema_period = max(5, min(50, int(float(
                p.get("ema_slope_filter", p.get("TrendEmaPeriod", 20))
            ))))
        except (TypeError, ValueError):
            trend_ema_period = 20
        extra_fields = """
                private double _sessionPriceVolume;
                private double _sessionVolume;
"""
        reset_family_state = """
                        _sessionPriceVolume = 0.0;
                        _sessionVolume = 0.0;
"""
        update_family_state = """
                    double typicalPrice = (High[0] + Low[0] + Close[0]) / 3.0;
                    _sessionPriceVolume += typicalPrice * Math.Max(1.0, Volume[0]);
                    _sessionVolume += Math.Max(1.0, Volume[0]);
"""
        signal_logic = """
                    if (_sessionVolume <= 0.0) return;
                    double sessionVwap = _sessionPriceVolume / _sessionVolume;
                    double avgVolume = 0.0;
                    int volumeBars = Math.Min(__VOLUME_WINDOW__, CurrentBar);
                    for (int i = 1; i <= volumeBars; i++)
                        avgVolume += Volume[i];
                    avgVolume /= Math.Max(1, volumeBars);
                    bool volumeConfirmed = Volume[0] >= avgVolume * __VOLUME_MULTIPLIER__;
                    double trendEma = EMA(__TREND_EMA_PERIOD__)[0];
                    double priorTrendEma = EMA(__TREND_EMA_PERIOD__)[3];

                    if (volumeConfirmed && Low[0] < sessionVwap
                        && Close[0] > sessionVwap && Close[0] > Open[0]
                        && Close[1] <= sessionVwap
                        && Close[0] > trendEma && trendEma > priorTrendEma)
                    {
                        _tradesToday++;
                        EnterLong(Quantity, TelemetrySignal("Long"));
                    }
                    else if (volumeConfirmed && High[0] > sessionVwap
                        && Close[0] < sessionVwap && Close[0] < Open[0]
                        && Close[1] >= sessionVwap
                        && Close[0] < trendEma && trendEma < priorTrendEma)
                    {
                        _tradesToday++;
                        EnterShort(Quantity, TelemetrySignal("Short"));
                    }
"""
        signal_logic = (
            signal_logic
            .replace("__VOLUME_WINDOW__", str(volume_window))
            .replace("__VOLUME_MULTIPLIER__", f"{volume_multiplier:.3f}")
            .replace("__TREND_EMA_PERIOD__", str(trend_ema_period))
        )
    elif any(token in family_text for token in ("liquidity", "sweep", "reversal")):
        deterministic_mode = "liquidity_sweep_reversal"
        signal_logic = """
                    double priorHigh = MAX(High, BreakoutLookback)[1];
                    double priorLow = MIN(Low, BreakoutLookback)[1];
                    if (Low[0] < priorLow && Close[0] > priorLow && Close[0] > Open[0])
                    {
                        _tradesToday++;
                        EnterLong(Quantity, TelemetrySignal("Long"));
                    }
                    else if (High[0] > priorHigh && Close[0] < priorHigh && Close[0] < Open[0])
                    {
                        _tradesToday++;
                        EnterShort(Quantity, TelemetrySignal("Short"));
                    }
"""
    elif any(token in family_text for token in ("pullback", "trend", "momentum")):
        deterministic_mode = "trend_pullback"
        signal_logic = """
                    double fast = EMA(9)[0];
                    double slow = EMA(21)[0];
                    if (fast > slow && Low[0] <= fast && Close[0] > fast && Close[0] > Open[0])
                    {
                        _tradesToday++;
                        EnterLong(Quantity, TelemetrySignal("Long"));
                    }
                    else if (fast < slow && High[0] >= fast && Close[0] < fast && Close[0] < Open[0])
                    {
                        _tradesToday++;
                        EnterShort(Quantity, TelemetrySignal("Short"));
                    }
"""
    else:
        signal_logic = """
                    double hi = MAX(High, BreakoutLookback)[1];
                    double lo = MIN(Low,  BreakoutLookback)[1];
                    if (Close[0] > hi)
                    {
                        _tradesToday++;
                        EnterLong(Quantity, TelemetrySignal("Long"));
                    }
                    else if (Close[0] < lo)
                    {
                        _tradesToday++;
                        EnterShort(Quantity, TelemetrySignal("Short"));
                    }
"""
    return dedent(f'''\
        // AI-SANDBOX strategy generated by NT-Analyzer AI Strategy Lab.
        // AI Cell: {ai_cell_id}
        // Class:   {class_name}
        // Instrument: {instrument}
        // Reference Pattern: {reference_id or "approved shortlist"}
        // Deterministic Family Renderer: {deterministic_mode}
        // Modification Hypothesis: {hypothesis[:240]}
        // Session window (Pacific Time): {session_start_pt} - {session_end_pt}
        // Risk shell: SetStopLoss + SetProfitTarget + MaxDailyLoss + MaxTradesPerDay + force-flat at session end.
        #region Using declarations
        using System;
        using NinjaTrader.Cbi;
        using NinjaTrader.NinjaScript;
        using NinjaTrader.NinjaScript.Indicators;
        using NinjaTrader.NinjaScript.Strategies;
        #endregion

        namespace NinjaTrader.NinjaScript.Strategies
        {{
            public class {class_name} : Strategy
            {{
                private double _dailyOpenPnl;
                private DateTime _currentSessionDate = DateTime.MinValue;
                private int _tradesToday;
                private bool _sessionCloseLogged;
                private bool _riskStopLogged;
{extra_fields}

                protected override void OnStateChange()
                {{
                    if (State == State.SetDefaults)
                    {{
                        Name                            = "{class_name}";
                        Description                     = "AI sandbox strategy generated by NT-Analyzer AI Lab.";
                        Calculate                       = Calculate.OnBarClose;
                        EntriesPerDirection             = 1;
                        EntryHandling                   = EntryHandling.AllEntries;
                        IsExitOnSessionCloseStrategy    = true;
                        ExitOnSessionCloseSeconds       = 30;
                        IsFillLimitOnTouch              = false;
                        MaximumBarsLookBack             = MaximumBarsLookBack.TwoHundredFiftySix;
                        OrderFillResolution             = OrderFillResolution.High;
                        Slippage                        = {slippage_ticks};
                        StartBehavior                   = StartBehavior.WaitUntilFlat;
                        TimeInForce                     = TimeInForce.Gtc;
                        TraceOrders                     = false;
                        RealtimeErrorHandling           = RealtimeErrorHandling.StopCancelClose;
                        StopTargetHandling              = StopTargetHandling.PerEntryExecution;
                        IsInstantiatedOnEachOptimizationIteration = false;
                        BarsRequiredToTrade             = {breakout_lookback + 5};

                        Quantity            = {quantity};
                        StopLossTicks       = {sl};
                        ProfitTargetTicks   = {tp};
                        MaxDailyLoss        = {mdl};
                        MaxTradesPerDay     = {max_trades};
                        BreakoutLookback    = {breakout_lookback};
                        RoundTurnCommission = {round_turn_commission:.2f};
                        SlippageTicks       = {slippage_ticks};
                        SessionStartTimePT  = {session_start_time};
                        SessionEndTimePT    = {session_end_time};
                        EnableBacktestLog   = true;
                    }}
                    else if (State == State.Configure)
                    {{
                        SetStopLoss(CalculationMode.Ticks, StopLossTicks);
                        SetProfitTarget(CalculationMode.Ticks, ProfitTargetTicks);
                    }}
                    else if (State == State.DataLoaded && EnableBacktestLog)
                    {{
                        Print("[NTA-LAB] READY " + Name + " cell={ai_cell_id} instrument={instrument}");
                    }}
                }}

                protected override void OnBarUpdate()
                {{
                    if (CurrentBar < BarsRequiredToTrade) return;
                    if (BarsInProgress != 0) return;

                    if (Bars.IsFirstBarOfSession || _currentSessionDate.Date != Time[0].Date)
                    {{
                        _currentSessionDate = Time[0].Date;
                        _dailyOpenPnl = SystemPerformance.AllTrades.TradesPerformance.Currency.CumProfit;
                        _tradesToday = 0;
                        _sessionCloseLogged = false;
                        _riskStopLogged = false;
                        if (EnableBacktestLog)
                            Print(string.Format("[NTA-LAB] SESSION {{0}} date={{1:yyyy-MM-dd}}", Name, Time[0]));
{reset_family_state}
                    }}

{update_family_state}
                    var sessionPnl = SystemPerformance.AllTrades.TradesPerformance.Currency.CumProfit - _dailyOpenPnl;
                    if (sessionPnl <= -MaxDailyLoss)
                    {{
                        if (EnableBacktestLog && !_riskStopLogged)
                        {{
                            Print(string.Format("[NTA-LAB] RISK_STOP {{0}} pnl={{1:F2}} trades={{2}}", Name, sessionPnl, _tradesToday));
                            _riskStopLogged = true;
                        }}
                        ForceFlat();
                        return;
                    }}

                    int nowPt = ToTime(Time[0]);
                    if (nowPt < SessionStartTimePT)
                    {{
                        return;
                    }}

                    if (nowPt >= SessionEndTimePT)
                    {{
                        if (EnableBacktestLog && !_sessionCloseLogged)
                        {{
                            Print(string.Format("[NTA-LAB] SESSION_END {{0}} pnl={{1:F2}} trades={{2}}", Name, sessionPnl, _tradesToday));
                            _sessionCloseLogged = true;
                        }}
                        ForceFlat();
                        return;
                    }}

                    if (Position.MarketPosition != MarketPosition.Flat) return;
                    if (_tradesToday >= MaxTradesPerDay) return;

{signal_logic}
                }}

                private void ForceFlat()
                {{
                    if (Position.MarketPosition == MarketPosition.Long)
                        ExitLong();
                    else if (Position.MarketPosition == MarketPosition.Short)
                        ExitShort();
                }}

                private string TelemetrySignal(string side)
                {{
                    if (EnableBacktestLog)
                        Print(string.Format("[NTA-LAB] ENTRY {{0}} side={{1}} time={{2:yyyy-MM-dd HH:mm}}", Name, side, Time[0]));
                    return GetType().Name + "." + side;
                }}

                #region Properties
                [NinjaTrader.NinjaScript.NinjaScriptProperty]
                public int Quantity {{ get; set; }}

                [NinjaTrader.NinjaScript.NinjaScriptProperty]
                public int StopLossTicks {{ get; set; }}

                [NinjaTrader.NinjaScript.NinjaScriptProperty]
                public int ProfitTargetTicks {{ get; set; }}

                [NinjaTrader.NinjaScript.NinjaScriptProperty]
                public int MaxDailyLoss {{ get; set; }}

                [NinjaTrader.NinjaScript.NinjaScriptProperty]
                public int MaxTradesPerDay {{ get; set; }}

                [NinjaTrader.NinjaScript.NinjaScriptProperty]
                public int BreakoutLookback {{ get; set; }}

                [NinjaTrader.NinjaScript.NinjaScriptProperty]
                public double RoundTurnCommission {{ get; set; }}

                [NinjaTrader.NinjaScript.NinjaScriptProperty]
                public int SlippageTicks {{ get; set; }}

                [NinjaTrader.NinjaScript.NinjaScriptProperty]
                public int SessionStartTimePT {{ get; set; }}

                [NinjaTrader.NinjaScript.NinjaScriptProperty]
                public int SessionEndTimePT {{ get; set; }}

                [NinjaTrader.NinjaScript.NinjaScriptProperty]
                public bool EnableBacktestLog {{ get; set; }}
                #endregion
            }}
        }}
        ''')


def render_deterministic_strategy(
    *,
    class_name: str,
    ai_cell_id: str,
    instrument: str,
    family: str,
    hypothesis: str,
    reference_id: str,
    parameters: Dict[str, Any],
) -> Tuple[str, ValidationReport, Dict[str, Any]]:
    """Render model-selected signal semantics inside the fixed NT8 shell."""
    src = fallback_template(
        class_name,
        ai_cell_id,
        instrument,
        parameters,
        family=family,
        hypothesis=hypothesis,
        reference_id=reference_id,
    )
    src, repairs = repair_common_nt8_source(src)
    src, normalized_cell = normalize_ai_cell_id(src, ai_cell_id)
    if normalized_cell:
        repairs.append("normalized_ai_cell_identifier")
    report = validate_source(src, expected_class_name=class_name)
    return src, report, {
        "path": "deterministic_family_renderer",
        "role": "deterministic_nt8_shell",
        "model": None,
        "attempts": 0,
        "deterministic_repairs": repairs,
        "sha256": hashlib.sha256(src.encode("utf-8")).hexdigest(),
        "bytes": len(src.encode("utf-8")),
    }


def build_user_prompt(
    class_name: str,
    ai_cell_id: str,
    instrument: str,
    hypothesis: str,
    parameters: Dict[str, Any],
    memory_intake: Dict[str, Any],
    user_research_excerpts: List[Dict[str, str]],
    rejected_patterns: List[Dict[str, Any]],
) -> str:
    _start_text, _end_text, _start_time, _end_time = _default_ai_session_bounds()
    parts = [
        "Russian-language reporting contract:",
        "- Write the strategy header comment and all human-readable comments in Russian.",
        "- Keep C# identifiers, NinjaTrader API names, property names, paths, and error codes in English.",
        "- Do not reveal hidden chain-of-thought; use only concise final summaries in comments.",
        "",
        "Deterministic NT8 shell contract (copy this behavior exactly):",
        "- Single primary series only; no AddDataSeries and no OnExecutionUpdate override.",
        "- Expose Quantity, StopLossTicks, ProfitTargetTicks, MaxDailyLoss, "
        f"MaxTradesPerDay (default <= 3), SessionStartTimePT={_start_time}, "
        f"SessionEndTimePT={_end_time} ({_start_text}-{_end_text} PT).",
        "- Configure SetStopLoss(CalculationMode.Ticks, StopLossTicks) and "
        "SetProfitTarget(CalculationMode.Ticks, ProfitTargetTicks) before any entry.",
        "- Every entry signal must be TelemetrySignal(\"Long\"/\"Short\"), where "
        "TelemetrySignal returns GetType().Name + \".\" + side.",
        "- Add compact NinjaTrader Output logging only for READY, session start/end, "
        "entry submission and first risk stop. Never Print on every bar. Expose "
        "EnableBacktestLog=true so the operator can disable it.",
        "- If position sizing is dynamic, return qty=0 when one contract exceeds "
        "the per-trade risk budget. Never force byRisk or qty up to 1.",
        "- At Bars.IsFirstBarOfSession snapshot CumProfit and reset tradesToday.",
        "- Use int nowPt = ToTime(Time[0]); block entries before start; at/after "
        "end call ForceFlat and return.",
        "- Session PnL = current CumProfit minus session-start snapshot.",
        "- Copy this shell literally, changing only field names if necessary:\n"
        "  if (Bars.IsFirstBarOfSession) { sessionStartCumProfit = "
        "SystemPerformance.AllTrades.TradesPerformance.Currency.CumProfit; "
        "tradesToday = 0; }\n"
        "  double sessionPnl = "
        "SystemPerformance.AllTrades.TradesPerformance.Currency.CumProfit "
        "- sessionStartCumProfit;\n"
        "  int nowPt = ToTime(Time[0]);\n"
        "  if (nowPt < SessionStartTimePT) return;\n"
        "  if (nowPt >= SessionEndTimePT) { ForceFlat(); return; }",
        "- Model freedom is limited to indicators, market-regime filter, and entry trigger.",
        "",
        "Knowledge context (mandatory; use this before writing code):",
        (memory_intake.get("knowledge_prompt_context") or "MISSING_KNOWLEDGE_CONTEXT")[:8000],
        "",
        "Memory intake (read carefully, do NOT repeat these mistakes):",
    ]
    for p in rejected_patterns[:10]:
        parts.append(f"- repeated {p.get('phase')}/{p.get('error_type')} (x{p.get('count')}): {p.get('normalized_pattern')[:200]}")
    if memory_intake.get("similar_rejected"):
        parts.append(f"- similar rejected experiments: {memory_intake['similar_rejected']}")
    if memory_intake.get("similar_demo_mismatch"):
        parts.append(f"- similar demo-mismatch families: {memory_intake['similar_demo_mismatch']}")
    parts.append("")
    parts.append("User research excerpts (high priority):")
    for ex in user_research_excerpts[:8]:
        parts.append(f"# {ex.get('rel_path')}")
        parts.append(ex.get("snippet", "")[:1500])
        parts.append("")
    parts.append("")
    parts.append(lm_studio.prompt_cache_marker())
    parts.append("")
    parts.extend([
        "Dynamic strategy request:",
        f"AI Cell:   {ai_cell_id}",
        f"Class:     {class_name}",
        f"Instrument: {instrument}",
        f"Hypothesis: {hypothesis}",
        f"Parameter hints: {parameters}",
        "",
    ])
    parts.append(
        "Now produce the single C# strategy file. Output only csharp inside a code fence. "
        "Human-readable comments inside the file must be in Russian."
    )
    return "\n".join(parts)


def generate(
    *,
    class_name: str,
    ai_cell_id: str,
    instrument: str,
    hypothesis: str,
    parameters: Dict[str, Any],
    memory_intake: Optional[Dict[str, Any]] = None,
    user_research_excerpts: Optional[List[Dict[str, str]]] = None,
    rejected_patterns: Optional[List[Dict[str, Any]]] = None,
    experiment_id: Optional[str] = None,
    use_llm: bool = True,
    mode: str = "initial",
    prior_compile_errors: Optional[List[Dict[str, Any]]] = None,
    prior_source: Optional[str] = None,
    operator_notes: Optional[str] = None,
    cancel_event: Optional[threading.Event] = None,
    allow_template_fallback: bool = False,
    allow_cloud_fallback: bool = False,
) -> Tuple[str, ValidationReport, Dict[str, Any]]:
    """Returns (source, validation_report, meta).

    ``mode`` controls which prompt is built:
      - "initial": fresh strategy from hypothesis + memory + user research.
        ``operator_notes`` are appended after the cacheable prefix if non-empty.
      - "autofix": rewrite of ``prior_source`` to clear ``prior_compile_errors``.
        Class/namespace must not be renamed. ``operator_notes`` are included.
    """
    meta: Dict[str, Any] = {"path": "llm", "attempts": 0, "mode": mode,
                            "role": "coder-autofix" if mode == "autofix" else "coder"}
    src: Optional[str] = None

    def _raise_if_cancelled() -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise lm_studio.LMStudioCancelled("cancelled before fallback/write")

    if mode == "autofix":
        _raise_if_cancelled()
        if not use_llm:
            meta["path"] = "autofix_skipped_no_llm"
            report = validate_source(prior_source or "", expected_class_name=class_name)
            return prior_source or "", report, meta
        sys_prompt = _read_system_prompt()
        user_prompt = _build_autofix_prompt(
            class_name=class_name,
            prior_compile_errors=prior_compile_errors or [],
            prior_source=prior_source or "",
            operator_notes=operator_notes,
        )
        messages = [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user_prompt},
        ]
        # Critical compile repair is routed to the benchmark winner first.
        # Local GPT-OSS remains the no-cost fallback below.
        try:
            external_resp = agent_router.invoke_messages(
                "compile_error_fixer", messages,
                max_output_tokens=2200, timeout=240,
                purpose="autofix_compile",
            )
            src = _extract_csharp(external_resp.get("content", "")) or None
            if src:
                meta.update({
                    "path": "external_primary",
                    "provider": external_resp.get("provider"),
                    "model": external_resp.get("actual_model") or external_resp.get("model"),
                    "elapsed_sec": external_resp.get("elapsed_sec"),
                    "cost_usd": external_resp.get("cost_usd"),
                    "attempts": 1,
                })
                _log_activity(
                    experiment_id, "coder_external_primary",
                    role="compile_error_fixer", provider=external_resp.get("provider"),
                    model=meta.get("model"), cost_usd=external_resp.get("cost_usd"),
                )
        except agent_router.AgentRouterError as exc:
            meta["external_primary_error"] = str(exc)[:300]
        if allow_cloud_fallback:
            try:
                cloud_resp = cloud_agents.invoke(
                    "compile_error_fixer_fallback", messages,
                    fallback_reason="local_compile_fix_failed_repeatedly",
                    experiment_id=experiment_id, purpose="autofix_compile_fallback",
                    temperature=0.1, max_tokens=2200, timeout=240,
                )
                src = _extract_csharp(cloud_resp.get("content", "")) or None
                if src:
                    meta.update({
                        "path": "cloud_fallback",
                        "provider": cloud_resp.get("provider"),
                        "model": cloud_resp.get("model"),
                        "elapsed_sec": cloud_resp.get("elapsed_sec"),
                        "cost_usd": cloud_resp.get("cost_usd"),
                        "attempts": 1,
                    })
                    _log_activity(
                        experiment_id, "coder_cloud_fallback", role="compile_error_fixer_fallback",
                        provider=cloud_resp.get("provider"), model=cloud_resp.get("model"),
                        cost_usd=cloud_resp.get("cost_usd"),
                        response_summary_ru="Облачный fallback вернул C# после повторных локальных ошибок компиляции.",
                    )
            except cloud_agents.CloudAgentBlocked as exc:
                meta["cloud_fallback_blocked"] = str(exc)
                _log_activity(
                    experiment_id, "coder_cloud_blocked", role="compile_error_fixer_fallback",
                    reason=str(exc)[:300],
                )
            except cloud_agents.CloudAgentsError as exc:
                meta["cloud_fallback_error"] = str(exc)
                _log_activity(
                    experiment_id, "coder_cloud_failed", role="compile_error_fixer_fallback",
                    error=str(exc)[:300],
                )
        if not src:
            try:
                _log_activity(
                    experiment_id,
                    "coder_prompt",
                    role=meta["role"],
                    purpose="autofix_compile",
                    prompt_preview="Fix compile errors and return one complete C# file with Russian human-readable comments.",
                    prompt_preview_ru="Исправить ошибки компиляции и вернуть полный C# файл с русскими поясняющими комментариями.",
                )
                resp = lm_studio.chat(
                    role="compile_error_fixer",
                    messages=messages,
                    temperature=0.1,
                    max_tokens=2200,
                    experiment_id=experiment_id,
                    purpose="autofix_compile",
                    timeout=lm_studio.DEFAULT_CODER_TIMEOUT,
                    cancel_event=cancel_event,
                )
                meta["model"] = resp.get("model")
                meta["elapsed_sec"] = resp.get("elapsed_sec")
                src = _extract_csharp(resp.get("content", "")) or None
                meta["attempts"] = 1
                _log_activity(
                    experiment_id,
                    "coder_response",
                    role=meta["role"],
                    model=resp.get("model"),
                    response_summary="Model returned a corrected strategy; extracting C# and validating it.",
                    response_summary_ru="Модель вернула исправленный вариант стратегии; выполняется извлечение C# и проверка.",
                )
            except lm_studio.LMStudioCancelled:
                raise
            except lm_studio.LMStudioError as e:
                meta["llm_error"] = str(e)
                _raise_if_cancelled()
        _raise_if_cancelled()
        if not src:
            # Autofix failed. Return the previous source for audit only, but
            # mark validation failed so callers do not silently rewrite the
            # same broken file and call it a successful repair.
            meta["path"] = "autofix_no_csharp_returned"
            report = ValidationReport(
                ok=False,
                violations=["autofix model did not return a C# source file"],
                class_name=class_name,
            )
            return prior_source or "", report, meta
        src, deterministic_repairs = repair_common_nt8_source(src)
        src, normalized_cell = normalize_ai_cell_id(src, ai_cell_id)
        if normalized_cell:
            deterministic_repairs.append("normalized_ai_cell_identifier")
        if deterministic_repairs:
            meta["deterministic_repairs"] = deterministic_repairs
        report = validate_source(src, expected_class_name=class_name)
        meta["sha256"] = hashlib.sha256(src.encode("utf-8")).hexdigest()
        meta["bytes"] = len(src.encode("utf-8"))
        return src, report, meta

    if use_llm:
        _raise_if_cancelled()
        try:
            sys_prompt = _read_system_prompt()
            user_prompt = build_user_prompt(
                class_name=class_name, ai_cell_id=ai_cell_id, instrument=instrument,
                hypothesis=hypothesis, parameters=parameters,
                memory_intake=memory_intake or {},
                user_research_excerpts=user_research_excerpts or [],
                rejected_patterns=rejected_patterns or [],
            )
            if operator_notes:
                user_prompt = (
                    user_prompt
                    + "\n\nOperator notes for this dynamic request:\n"
                    + operator_notes
                )
            _log_activity(
                experiment_id,
                "coder_prompt",
                role=meta["role"],
                purpose="generate_strategy",
                prompt_preview="Generate a NinjaTrader 8 strategy from the hypothesis; keep C# APIs untranslated.",
                prompt_preview_ru="Сгенерировать стратегию NinjaTrader 8 по гипотезе; C# API не переводить.",
            )
            messages = [
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": user_prompt},
            ]
            try:
                resp = agent_router.invoke_messages(
                    "coder", messages, max_output_tokens=2200, timeout=240,
                    purpose="generate_strategy",
                )
                meta["path"] = "external_primary"
                meta["provider"] = resp.get("provider")
                meta["cost_usd"] = resp.get("cost_usd")
            except agent_router.AgentRouterError as external_error:
                meta["external_primary_error"] = str(external_error)[:300]
                resp = lm_studio.chat(
                    role="coder", messages=messages, temperature=0.2,
                    max_tokens=1500, experiment_id=experiment_id,
                    purpose="generate_strategy", timeout=lm_studio.DEFAULT_CODER_TIMEOUT,
                    cancel_event=cancel_event,
                )
                meta["path"] = "local_fallback"
            meta["model"] = resp.get("model")
            meta["elapsed_sec"] = resp.get("elapsed_sec")
            src = _extract_csharp(resp.get("content", "")) or None
            meta["attempts"] = 1
            _log_activity(
                experiment_id,
                "coder_response",
                role=meta["role"],
                model=resp.get("model"),
                response_summary="Model returned strategy code; extracting C# and running static validation.",
                response_summary_ru="Модель вернула код стратегии; выполняется извлечение C# и статическая проверка.",
            )
        except lm_studio.LMStudioCancelled:
            raise
        except lm_studio.LMStudioError as e:
            meta["llm_error"] = str(e)
            _raise_if_cancelled()

    _raise_if_cancelled()
    if not src:
        if allow_template_fallback or not use_llm:
            meta["path"] = "fallback_template"
            src = fallback_template(class_name=class_name, ai_cell_id=ai_cell_id,
                                     instrument=instrument, parameters=parameters)
        else:
            # Hard gate: LM Studio did not return a usable strategy and the
            # user has not opted in to the template fallback. Refuse rather
            # than silently shipping the boilerplate clone.
            raise lm_studio.LMStudioGenerationFailed(
                "LM Studio coder did not return a strategy and "
                "allow_template_fallback=False; refusing silent fallback_template. "
                f"Last model error: {meta.get('llm_error') or 'no C# in response'}",
            )

    src, deterministic_repairs = repair_common_nt8_source(src)
    src, normalized_cell = normalize_ai_cell_id(src, ai_cell_id)
    if normalized_cell:
        deterministic_repairs.append("normalized_ai_cell_identifier")
    if deterministic_repairs:
        meta["deterministic_repairs"] = deterministic_repairs
    report = validate_source(src, expected_class_name=class_name)

    # Repair static defects against the actual prior source.  The former
    # prompt omitted the source entirely, so the model invented a different
    # class and often repeated the same invalid APIs.  Two focused repair
    # passes are cheaper and more reliable than abandoning the whole cell.
    while not report.ok and use_llm and meta["attempts"] < 3:
        try:
            fix_prompt = _build_static_validation_autofix_prompt(
                class_name=class_name,
                violations=report.violations,
                prior_source=src,
            )
            _log_activity(
                experiment_id,
                "coder_prompt",
                role=meta["role"],
                purpose="static_validation_autofix",
                prompt_preview="Fix static-validation violations without renaming the class or namespace.",
                prompt_preview_ru="Исправить нарушения статической проверки без переименования класса и namespace.",
            )
            messages = [
                {"role": "system", "content": _read_system_prompt()},
                {"role": "user", "content": fix_prompt},
            ]
            try:
                resp = agent_router.invoke_messages(
                    "code_reviewer", messages, max_output_tokens=2200,
                    timeout=240, purpose="autofix_strategy",
                )
            except agent_router.AgentRouterError:
                resp = lm_studio.chat(
                    role="code_reviewer", messages=messages, temperature=0.1,
                    max_tokens=2200, experiment_id=experiment_id,
                    purpose="autofix_strategy", timeout=lm_studio.DEFAULT_CODER_TIMEOUT,
                    cancel_event=cancel_event,
                )
            meta["attempts"] += 1
            fixed = _extract_csharp(resp.get("content", "")) or None
            _log_activity(
                experiment_id,
                "coder_response",
                role=meta["role"],
                model=resp.get("model"),
                response_summary="Model returned a static-validation fix; code will be checked again.",
                response_summary_ru="Модель вернула исправление после статической проверки; код будет перепроверен.",
            )
            if fixed:
                src, more_repairs = repair_common_nt8_source(fixed)
                src, normalized_cell = normalize_ai_cell_id(src, ai_cell_id)
                if normalized_cell:
                    more_repairs.append("normalized_ai_cell_identifier")
                if more_repairs:
                    meta.setdefault("deterministic_repairs", []).extend(more_repairs)
                report = validate_source(src, expected_class_name=class_name)
            else:
                break
        except lm_studio.LMStudioCancelled:
            raise
        except lm_studio.LMStudioError as e:
            meta["autofix_error"] = str(e)
            _raise_if_cancelled()
            break

    _raise_if_cancelled()
    if not report.ok:
        if allow_template_fallback or not use_llm:
            meta["fell_back_after_validation_fail"] = True
            src = fallback_template(class_name=class_name, ai_cell_id=ai_cell_id,
                                     instrument=instrument, parameters=parameters)
            report = validate_source(src, expected_class_name=class_name)
        else:
            # Caller (orchestrator) will record the violations and mark
            # validation_failed. Returning the broken source plus !ok report
            # is the contract the orchestrator already understands.
            meta["fell_back_after_validation_fail"] = False

    meta["sha256"] = hashlib.sha256(src.encode("utf-8")).hexdigest()
    meta["bytes"] = len(src.encode("utf-8"))
    return src, report, meta


def _build_static_validation_autofix_prompt(
    *,
    class_name: str,
    violations: List[str],
    prior_source: str,
) -> str:
    return (
        f"Repair the complete strategy below. The public class MUST remain "
        f"exactly {class_name} and the namespace MUST remain "
        "NinjaTrader.NinjaScript.Strategies.\n\n"
        "Keep C# identifiers, NinjaTrader API names, property names, paths, and "
        "error codes in English. Write human-readable comments in Russian only.\n\n"
        "Fix every static-validation violation:\n- "
        + "\n- ".join(violations)
        + "\n\nRequired concrete fixes:\n"
        "- Replace Highest(...) / Lowest(...) with valid MAX(...) / MIN(...) "
        "indicator usage or explicit rolling loops.\n"
        "- Include explicit session-end force-flat logic using ExitLong(...) "
        "and ExitShort(...).\n"
        "- Add an explicit Pacific Time start/end entry gate; do not rely only "
        "on the backtest session template or Bars.IsLastBarOfSession.\n"
        "- Snapshot CumProfit at Bars.IsFirstBarOfSession and compare the "
        "current CumProfit minus that baseline to -MaxDailyLoss.\n"
        "- Use this exact shape: `double sessionPnl = "
        "SystemPerformance.AllTrades.TradesPerformance.Currency.CumProfit "
        "- sessionStartCumProfit;` and `int nowPt = ToTime(Time[0]);`.\n"
        "- Gate exactly with `if (nowPt < SessionStartTimePT) return;` and "
        "`if (nowPt >= SessionEndTimePT) { ForceFlat(); return; }`.\n"
        "- Keep one instrument and one timeframe; remove AddDataSeries(...).\n"
        "- Remove OnExecutionUpdate entirely; the AI Lab deterministic shell "
        "configures stop/target before entry.\n"
        "- Set stop loss and profit target before EnterLong/EnterShort.\n"
        "- Do not assume Time[0] is UTC before converting to Pacific Time.\n"
        "- Keep AI-CELL identifiers; never introduce a production CELL-### id.\n"
        "- Preserve all required risk parameters and [NinjaScriptProperty] attributes.\n"
        "- Return the entire corrected file, not a patch or explanation.\n\n"
        "```csharp\n"
        + prior_source
        + "\n```"
    )


def _build_autofix_prompt(
    *,
    class_name: str,
    prior_compile_errors: List[Dict[str, Any]],
    prior_source: str,
    operator_notes: Optional[str],
) -> str:
    header = (
        f"Your prior strategy {class_name} failed to compile. Below are the NT8 "
        "compiler diagnostics. Produce ONE corrected C# file in a ```csharp "
        "fence. Do not rename the class or namespace. Keep identifiers and APIs "
        "in English, but write human-readable comments in Russian."
    )
    err_lines = []
    for e in (prior_compile_errors or [])[:30]:
        f = (e.get("file") or "")[-80:]
        ln = e.get("line", "?")
        col = e.get("column", "?")
        code = e.get("code", "?")
        msg = (e.get("message") or "")[:200]
        err_lines.append(f"- {f}({ln},{col}): {code}: {msg}")
    parts = [header, "", "## Compile errors:"] + (err_lines or ["- (no diagnostics captured)"])
    joined_errors = " ".join(
        str(e.get("message") or "") for e in (prior_compile_errors or [])
    ).lower()
    if any(name in joined_errors for name in ("'execution'", "'position'", "'marketposition'")):
        parts.extend([
            "",
            "## Known NT8 fix hint:",
            "- Execution, Position, and MarketPosition are NinjaTrader.Cbi types; "
            "add `using NinjaTrader.Cbi;` instead of deleting required overrides.",
        ])
    if "onpositionupdate" in joined_errors and "no suitable method" in joined_errors:
        parts.extend([
            "",
            "## Known NT8 override hint:",
            "- Use exactly `protected override void OnPositionUpdate(Position position, "
            "double averagePrice, int quantity, MarketPosition marketPosition)`; "
            "there is no `signalName` parameter in this override.",
        ])
    if "could not be found" in joined_errors and any(
        name in joined_errors for name in ("'bollinger'", "'ema'", "'rsi'", "'atr'")
    ):
        parts.extend([
            "",
            "## Known NT8 indicator hint:",
            "- Add `using NinjaTrader.NinjaScript.Indicators;` for built-in "
            "indicator types and helpers.",
        ])
    if "barsperiodtype" in joined_errors and "does not exist" in joined_errors:
        parts.extend([
            "",
            "## Known NT8 data hint:",
            "- Add `using NinjaTrader.Data;` for BarsPeriodType.",
        ])
    if "cannot convert from 'int' to 'string'" in joined_errors:
        parts.extend([
            "",
            "## Known NT8 exit overload hint:",
            "- ExitLong/ExitShort second argument is the string fromEntrySignal, "
            "not Position.Quantity. Use the exact entry signal name.",
        ])
    if "argument 4" in joined_errors and "cannot convert from 'int' to 'bool'" in joined_errors:
        parts.extend([
            "",
            "## Known NT8 stop hint:",
            "- SetStopLoss(..., CalculationMode.Price, value, false) uses a bool "
            "as its final isSimulatedStop argument; never pass 0.",
        ])
    if operator_notes:
        parts.extend(["", operator_notes])
    parts.extend(["", "// --- previous source ---", prior_source])
    return "\n".join(parts)


def write_to_sandbox(class_name: str, source: str) -> Tuple[Path, Path]:
    """Write source to the canonical NT sandbox path and mirror it in the repo.

    Refuses to write source that fails static validation, and refuses any path
    outside the sandbox or repo mirror (raises :class:`SandboxBreachError`).
    """
    pre = validate_source(source, expected_class_name=class_name)
    if not pre.ok:
        raise ValueError(
            f"refusing to write invalid source for {class_name}: {pre.violations[:3]}"
        )
    sandbox = paths.ai_sandbox_strategies_dir()
    sandbox.mkdir(parents=True, exist_ok=True)
    sandbox_file = sandbox / f"{class_name}.cs"
    assert_sandbox_only(sandbox_file)
    sandbox_file.write_text(source, encoding="utf-8")

    mirror = paths.SOURCE_SNAPSHOTS_DIR / f"{class_name}.cs"
    mirror.parent.mkdir(parents=True, exist_ok=True)
    assert_sandbox_only(mirror)
    mirror.write_text(source, encoding="utf-8")
    return sandbox_file, mirror
