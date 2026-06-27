"""Static safety validator for AI-generated NinjaTrader C# strategies.

This gate runs BEFORE the file ever hits the canonical NT sandbox path.
A strategy is auto-rejected if any required risk shell is missing, any
forbidden API is referenced, namespace/class naming violates AI-sandbox
conventions, or the file shows live/paper auto-start behavior.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List

REQUIRED_PATTERNS = {
    "stop_loss": re.compile(r"SetStopLoss\s*\(", re.I),
    "take_profit_or_time_stop": re.compile(r"(SetProfitTarget\s*\()|(time[_\s]?stop)|(TimeStop)", re.I),
    "max_daily_loss": re.compile(r"(max[_\s]?daily[_\s]?loss)|(MaxDailyLoss)|(DailyLossLimit)", re.I),
    "max_trades_per_day": re.compile(r"(max[_\s]?trades[_\s]?per[_\s]?day)|(MaxTradesPerDay)|(TradesToday)|(_tradesToday)", re.I),
    "force_flat": re.compile(r"(force[_\s]?flat)|(ForceFlat)|(ExitLong\s*\()|(ExitShort\s*\()", re.I),
}

FORBIDDEN_API = [
    (re.compile(r"\bSystem\.IO\.File\s*\."), "file IO via System.IO.File"),
    (re.compile(r"\bSystem\.Net\."), "network IO via System.Net"),
    (re.compile(r"\bHttpClient\b"), "HttpClient network access"),
    (re.compile(r"\bWebRequest\b"), "WebRequest network access"),
    (re.compile(r"\bSystem\.Diagnostics\.Process\b"), "shell/process spawning"),
    (re.compile(r"\bProcess\.Start\b"), "shell/process spawning"),
    (re.compile(r"\bRegistry\."), "Windows registry access"),
    (re.compile(r"\bunsafe\s*\{"), "unsafe block"),
    (re.compile(r"\bDllImport\b"), "P/Invoke DllImport"),
    (re.compile(r"\bEnvironment\.Exit\b"), "Environment.Exit"),
    (re.compile(r"\bState\s*==\s*State\.Realtime\b.*EnterLong\s*\(", re.S), "live auto-entry on State.Realtime"),
]

INVALID_NT8_PATTERNS = [
    (
        re.compile(r"\bHighest\s*\("),
        "invalid NT8 indicator helper Highest(...); use MAX(...) or explicit rolling logic",
    ),
    (
        re.compile(r"\bLowest\s*\("),
        "invalid NT8 indicator helper Lowest(...); use MIN(...) or explicit rolling logic",
    ),
    (
        re.compile(r"\bTradesPerformance\.Currency\.TradeCount\b"),
        "invalid TradesPerformance.Currency.TradeCount reference; track trade counts locally",
    ),
    (
        re.compile(r"\bNinjaTrader\.NinjaScript\.StrategyAnalyzer\b"),
        "invalid using NinjaTrader.NinjaScript.StrategyAnalyzer; strategies should inherit Strategy only",
    ),
    (
        re.compile(r"\bnamespace\s+NinjaTrader\.Strategy\b"),
        "invalid namespace NinjaTrader.Strategy; AI sources must use NinjaTrader.NinjaScript.Strategies",
    ),
    (
        re.compile(r"\busing\s+NinjaTrader\.Strategy\b"),
        "invalid using NinjaTrader.Strategy; AI sources must use NinjaTrader.NinjaScript.Strategies",
    ),
    (
        re.compile(r"\bIsExitOnSessionEnd\b"),
        "invalid NT8 Strategy property IsExitOnSessionEnd; use IsExitOnSessionCloseStrategy",
    ),
    (
        re.compile(r"\bSetCommission\s*\("),
        "invalid Strategy SetCommission(...); commission is enforced by the research job accounting layer",
    ),
    (
        re.compile(r"\bSetSlippage\s*\("),
        "invalid Strategy SetSlippage(...); slippage is enforced by the research job execution layer",
    ),
    (
        re.compile(r"\bForceCloseOnSessionEnd\b"),
        "invalid ForceCloseOnSessionEnd reference; use IsExitOnSessionCloseStrategy plus explicit ForceFlat",
    ),
    (
        re.compile(r"\bDateTime\s*\.\s*DayNumber\b|\.\s*DayNumber\b"),
        "invalid DateTime.DayNumber reference; use Date or DateTime.Date comparisons",
    ),
    (
        re.compile(r"\bIsInstantiatedOnEachTrade\b"),
        "invalid NT8 Strategy property IsInstantiatedOnEachTrade; use IsInstantiatedOnEachOptimizationIteration",
    ),
    (
        re.compile(r"\bAccount\s*\."),
        "invalid Strategy Account API access; use SystemPerformance/realized PnL tracking",
    ),
    (
        re.compile(r"\bAccount\s*\.\s*GetProfitLoss\s*\("),
        "invalid Strategy Account.GetProfitLoss call; use SystemPerformance/realized PnL tracking",
    ),
    (
        re.compile(r"\bGetAccountValue\s*\("),
        "invalid Strategy account value call; AI sandbox strategies cannot query live/account state",
    ),
    (
        re.compile(r"\bAccountItem\b"),
        "invalid AccountItem reference; AI sandbox strategies cannot query account state",
    ),
    (
        re.compile(r"\bEnabled\s*=", re.I),
        "invalid Strategy assignment Enabled=; use an internal tradingEnabled flag",
    ),
    (
        re.compile(r"\bIsFirstTickOfSession\b"),
        "invalid/ambiguous IsFirstTickOfSession usage; use Bars.IsFirstBarOfSession",
    ),
    (
        re.compile(r"\bToPacific\s*\("),
        "invalid ToPacific extension/helper pattern in strategy source; use TimeZoneInfo directly",
    ),
    (
        re.compile(r"\bTimeZones\.PacificStandardTime\b"),
        "invalid TimeZones.PacificStandardTime reference; use TimeZoneInfo.FindSystemTimeZoneById",
    ),
    (
        re.compile(
            r"\bOnPositionUpdate\s*\([^)]*\bstring\s+signalName\b",
            re.I | re.S,
        ),
        "invalid NT8 OnPositionUpdate override signature; remove signalName and use "
        "OnPositionUpdate(Position, double, int, MarketPosition)",
    ),
    (
        re.compile(r"(?m)^\s*BarsPeriodType\s*="),
        "invalid Strategy BarsPeriodType assignment; the historical job supplies the primary timeframe",
    ),
    (
        re.compile(r"(?m)^\s*BarsPeriodValue\s*="),
        "invalid Strategy BarsPeriodValue assignment; the historical job supplies the primary timeframe",
    ),
    (
        re.compile(r"\bAddDataSeries\s*\("),
        "AI Lab strategies must remain single instrument/single timeframe; remove AddDataSeries(...)",
    ),
    (
        re.compile(r"\bOnExecutionUpdate\s*\([^)]*\b(?:TradeType|string\s+filter)\b", re.I | re.S),
        "invalid NT8 OnExecutionUpdate override signature; use exactly "
        "OnExecutionUpdate(Execution, string, double, int, MarketPosition, string, DateTime)",
    ),
    (
        re.compile(r"\bprotected\s+override\s+void\s+OnExecutionUpdate\s*\(", re.I),
        "AI Lab deterministic risk shell forbids OnExecutionUpdate; configure "
        "SetStopLoss/SetProfitTarget before entry in OnStateChange/OnBarUpdate",
    ),
    (
        re.compile(r"\bExit(?:Long|Short)\s*\(\s*\"[^\"]+\"\s*,\s*Position\.Quantity\s*\)"),
        "invalid ExitLong/ExitShort overload with Position.Quantity as the second argument",
    ),
    (
        re.compile(r"\bSetStopLoss\s*\([^;\r\n]*,\s*0\s*\)\s*;"),
        "invalid SetStopLoss final argument 0; the final parameter is bool isSimulatedStop",
    ),
    (
        re.compile(
            r"DateTime\s+([A-Za-z_]\w*)\s*=\s*Time\s*\[\s*0\s*\]\s*;\s*"
            r"DateTime\s+[A-Za-z_]\w*\s*=\s*TimeZoneInfo\.ConvertTimeFromUtc\s*\(\s*\1\s*,",
            re.I | re.S,
        ),
        "Time[0] must not be assumed to be UTC before Pacific Time conversion",
    ),
]

OVERNIGHT_HINTS = [
    re.compile(r"//\s*overnight", re.I),
    re.compile(r"IsOvernight\s*\(", re.I),
]

SESSION_TIME_ACCESS = re.compile(r"ToTime\s*\(\s*Time\s*\[\s*0\s*\]\s*\)", re.I)
SESSION_START_IDENTIFIER = re.compile(
    r"\b(?:SessionStart\w*|TradeStart\w*|StartTimePT)\b",
    re.I,
)
SESSION_END_IDENTIFIER = re.compile(
    r"\b(?:SessionEnd\w*|TradeEnd\w*|EndTimePT|ForceFlatTime)\b",
    re.I,
)
DAILY_PNL_SNAPSHOT = re.compile(
    r"TradesPerformance\.Currency\.CumProfit\s*-\s*[A-Za-z_]\w*",
    re.I,
)


def _has_daily_pnl_snapshot(text: str) -> bool:
    """Accept the canonical expression and an equivalent named-current form."""
    if DAILY_PNL_SNAPSHOT.search(text):
        return True
    assigned_from_cum = set(re.findall(
        r"\b(?:double|var)\s+([A-Za-z_]\w*)\s*=\s*"
        r"SystemPerformance\.AllTrades\.TradesPerformance\.Currency\.CumProfit",
        text,
        re.I,
    ))
    if len(assigned_from_cum) < 2:
        return False
    for current_var in assigned_from_cum:
        if re.search(
            rf"\b{re.escape(current_var)}\s*-\s*"
            rf"(?:{'|'.join(re.escape(v) for v in assigned_from_cum if v != current_var)})\b",
            text,
            re.I,
        ):
            return True
    return False

# Do not treat the allowed ``AI-CELL-###`` audit identifier as a production
# ``CELL-###`` reference merely because the latter is its suffix.
PRODUCTION_NAMING = re.compile(r"(?<!AI-)\bCELL-\d{3}\b")
NTA_AI_CLASS_RE = re.compile(r"\bNTAAiSandbox[A-Z][A-Za-z0-9]+\b")
PRODUCTION_CLASS_PREFIX = re.compile(r"\bclass\s+(NTAMicro|NTAMnq|NTAMgc|NTAMes|NTAEs|NTANq|NTAGc|NTASi|NTAYm|NTACl)[A-Za-z0-9]*", re.I)
PUBLIC_INPUT_RE = re.compile(
    r"(?m)^\s*public\s+(?:int|long|double|float|decimal|bool|string)\s+([A-Za-z_][A-Za-z0-9_]*)\s*\{\s*get\s*;\s*set\s*;\s*\}"
)
RISK_IDENTIFIERS = (
    "StopLossTicks",
    "ProfitTargetTicks",
    "MaxDailyLoss",
    "MaxTradesPerDay",
)

MAX_FILE_BYTES = 200_000


@dataclass
class ValidationReport:
    ok: bool
    violations: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    class_name: str = ""

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "violations": self.violations,
            "warnings": self.warnings,
            "class_name": self.class_name,
        }


def _strip_comments(text: str) -> str:
    return re.sub(r"//.*?$|/\*.*?\*/", "", text, flags=re.M | re.S)


def _missing_ninjascript_property_inputs(text: str) -> List[str]:
    lines = text.splitlines()
    missing: List[str] = []
    for idx, line in enumerate(lines):
        m = PUBLIC_INPUT_RE.match(line)
        if not m:
            continue
        start = max(0, idx - 5)
        context = "\n".join(lines[start:idx + 1])
        if "NinjaScriptProperty" not in context:
            missing.append(m.group(1))
    return missing


def _undeclared_risk_identifiers(text: str) -> List[str]:
    stripped = _strip_comments(text)
    missing: List[str] = []
    for name in RISK_IDENTIFIERS:
        if not re.search(rf"\b{name}\b", stripped):
            continue
        declared = re.search(
            rf"\b(?:public|private|protected|internal)\s+(?:readonly\s+)?(?:int|long|double|float|decimal|bool|string)\s+{name}\b",
            stripped,
        )
        if not declared:
            missing.append(name)
    return missing


def validate_source(text: str, expected_class_name: str = "") -> ValidationReport:
    rep = ValidationReport(ok=True, class_name=expected_class_name)
    if not text or not text.strip():
        rep.ok = False
        rep.violations.append("empty source")
        return rep
    if len(text.encode("utf-8", errors="replace")) > MAX_FILE_BYTES:
        rep.ok = False
        rep.violations.append(f"source larger than {MAX_FILE_BYTES} bytes")
        return rep

    for key, pat in REQUIRED_PATTERNS.items():
        if not pat.search(text):
            rep.ok = False
            rep.violations.append(f"missing required risk shell: {key}")

    if not (
        SESSION_TIME_ACCESS.search(text)
        and SESSION_START_IDENTIFIER.search(text)
        and SESSION_END_IDENTIFIER.search(text)
    ):
        rep.ok = False
        rep.violations.append(
            "missing explicit intraday session window gate; block entries outside "
            "the configured Pacific Time start/end window"
        )

    if not _has_daily_pnl_snapshot(text):
        rep.ok = False
        rep.violations.append(
            "MaxDailyLoss must use session PnL: snapshot CumProfit at session start "
            "and compare CumProfit minus that baseline"
        )

    stripped = _strip_comments(text)
    entry_calls = list(re.finditer(
        r"\bEnter(?:Long|Short)(?:Limit|StopMarket|StopLimit)?\s*\((.*?)\)\s*;",
        stripped,
        re.I | re.S,
    ))
    first_entry = min(
        [pos for pos in (
            text.find("EnterLong("),
            text.find("EnterShort("),
        ) if pos >= 0],
        default=-1,
    )
    if first_entry >= 0:
        stop_pos = text.find("SetStopLoss(")
        target_pos = text.find("SetProfitTarget(")
        if stop_pos < 0 or target_pos < 0 or stop_pos > first_entry or target_pos > first_entry:
            rep.ok = False
            rep.violations.append(
                "deterministic risk shell requires SetStopLoss and "
                "SetProfitTarget to be configured before the first entry call"
            )
    if entry_calls and (
        any("TelemetrySignal(" not in match.group(1) for match in entry_calls)
        or not re.search(r"GetType\s*\(\s*\)\s*\.\s*Name", stripped)
    ):
        rep.ok = False
        rep.violations.append(
            "every entry signal must use TelemetrySignal(...), backed by "
            "GetType().Name + '.Long/.Short'"
        )

    forced_minimum_risk_patterns = (
        re.compile(r"byRisk\s*=\s*Math\.Max\s*\(\s*1\s*,", re.I),
        re.compile(r"return\s+Math\.Max\s*\(\s*1\s*,[^;\r\n]*\bbyRisk\b", re.I),
        re.compile(r"if\s*\([^)]*qty\s*==\s*0[^)]*\)\s*\{[^}]*qty\s*=\s*1\s*;", re.I | re.S),
        re.compile(r"^\s*qty\s*=\s*1\s*;", re.I | re.M),
    )
    if any(pattern.search(stripped) for pattern in forced_minimum_risk_patterns):
        rep.ok = False
        rep.violations.append(
            "position sizing must return qty=0 when one contract exceeds the "
            "per-trade risk budget; never force the minimum quantity to 1"
        )

    for value in re.findall(
        r"\bMaxTradesPerDay\s*=\s*(\d+)\s*;",
        _strip_comments(text),
    ):
        if int(value) > 3:
            rep.ok = False
            rep.violations.append("MaxTradesPerDay default must be <= 3")

    for pat, label in FORBIDDEN_API:
        if pat.search(text):
            rep.ok = False
            rep.violations.append(f"forbidden API: {label}")

    for pat, label in INVALID_NT8_PATTERNS:
        if pat.search(text):
            rep.ok = False
            rep.violations.append(f"compile-risk NT8 API: {label}")

    uses_data_annotations = "[Range" in text or "[Display" in text
    has_data_annotations_using = (
        "using System.ComponentModel.DataAnnotations;" in text
        or "System.ComponentModel.DataAnnotations.Range" in text
        or "System.ComponentModel.DataAnnotations.Display" in text
    )
    if uses_data_annotations and not has_data_annotations_using:
        rep.ok = False
        rep.violations.append(
            "uses [Range]/[Display] without System.ComponentModel.DataAnnotations"
        )
    if uses_data_annotations and "NinjaScriptProperty" not in text:
        rep.ok = False
        rep.violations.append(
            "exposed [Range]/[Display] inputs must include [NinjaScriptProperty]"
        )

    uses_indicator_helpers = bool(re.search(
        r"\b(?:ATR|Bollinger|EMA|MAX|MIN|RSI|SMA|StdDev)\s*\(",
        text,
    ))
    if (
        uses_indicator_helpers
        and "using NinjaTrader.NinjaScript.Indicators;" not in text
        and "NinjaTrader.NinjaScript.Indicators." not in text
    ):
        rep.ok = False
        rep.violations.append(
            "uses NT8 indicators without 'using NinjaTrader.NinjaScript.Indicators;'"
        )
    if (
        re.search(r"\bBarsPeriodType\b", text)
        and "using NinjaTrader.Data;" not in text
        and "NinjaTrader.Data.BarsPeriodType" not in text
    ):
        rep.ok = False
        rep.violations.append(
            "uses BarsPeriodType without 'using NinjaTrader.Data;'"
        )

    for name in _missing_ninjascript_property_inputs(text):
        rep.ok = False
        rep.violations.append(
            f"public input property {name} must include [NinjaScriptProperty]"
        )

    for name in _undeclared_risk_identifiers(text):
        rep.ok = False
        rep.violations.append(f"risk variable {name} is referenced but not declared")

    for pat in OVERNIGHT_HINTS:
        if pat.search(text):
            rep.warnings.append("possible overnight reference detected")

    if PRODUCTION_NAMING.search(text):
        rep.ok = False
        rep.violations.append("uses production CELL-### id; AI must use AI-CELL- ids only")

    if PRODUCTION_CLASS_PREFIX.search(text):
        rep.ok = False
        rep.violations.append("uses production class naming prefix; AI must use NTAAiSandbox*")

    if expected_class_name:
        if expected_class_name not in text:
            rep.ok = False
            rep.violations.append(f"declared class name {expected_class_name} not found in source")
        if not expected_class_name.startswith("NTAAiSandbox"):
            rep.ok = False
            rep.violations.append("expected class name must start with NTAAiSandbox")

    found_classes = NTA_AI_CLASS_RE.findall(text)
    if not found_classes:
        rep.warnings.append("no NTAAiSandbox* class match found via regex")

    if "namespace NinjaTrader.NinjaScript.Strategies" not in text:
        rep.ok = False
        rep.violations.append("missing 'namespace NinjaTrader.NinjaScript.Strategies'")

    if "OnBarUpdate" not in text:
        rep.ok = False
        rep.violations.append("missing OnBarUpdate")

    return rep
