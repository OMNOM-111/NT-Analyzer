"""Static safety checks for production NinjaTrader strategy sources."""
from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
STRATEGY_ROOT = ROOT / "ninjatrader" / "strategies"
BRIDGE_EXPORTER = ROOT / "bridge" / "src" / "Runtime" / "RuntimeTelemetryExporter.cs"


def _sources() -> list[Path]:
    return sorted(STRATEGY_ROOT.rglob("*.cs"))


def _assert_no_forced_minimum_contract() -> None:
    violations: list[str] = []
    patterns = (
        re.compile(r"byRisk\s*=\s*Math\.Max\(1\s*,"),
        re.compile(r"return\s+Math\.Max\(1\s*,[^;\r\n]*\bbyRisk\b"),
        re.compile(r"^\s*qty\s*=\s*1\s*;"),
    )
    for path in _sources():
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            if any(pattern.search(line) for pattern in patterns):
                violations.append(f"{path.relative_to(ROOT)}:{lineno}: {line.strip()}")
    assert not violations, (
        "risk sizing must return zero when one contract exceeds the risk budget:\n"
        + "\n".join(violations)
    )


def _assert_entry_signals_carry_concrete_class() -> None:
    violations: list[str] = []
    assignment = re.compile(r"\bstring\s+signal\s*=\s*(.+)")
    allowed = ("TelemetrySignal(", "ActiveEntrySignalForPosition(")
    for path in _sources():
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            match = assignment.search(line)
            if match and not any(token in match.group(1) for token in allowed):
                violations.append(f"{path.relative_to(ROOT)}:{lineno}: {line.strip()}")
    assert not violations, (
        "entry signal variables must encode the concrete runtime class:\n"
        + "\n".join(violations)
    )


def _assert_legacy_signal_bridge_coverage() -> None:
    text = BRIDGE_EXPORTER.read_text(encoding="utf-8")
    assert "LegacyStrategyClassFromSignal(s)" in text
    for signal, strategy_class in (
        ("CapSnapS", "NTAMgcCapitulationSnapbackC007"),
        ("EntFieldS", "NTAMnqEntropyTransitionFieldC127"),
        ("GPP_Short", "NTAGeodesicPhasePressurePilot"),
    ):
        assert signal in text, signal
        assert strategy_class in text, strategy_class


def main() -> int:
    checks = (
        _assert_no_forced_minimum_contract,
        _assert_entry_signals_carry_concrete_class,
        _assert_legacy_signal_bridge_coverage,
    )
    failed = 0
    for check in checks:
        try:
            check()
            print(f"  PASS  {check.__name__}")
        except Exception as exc:
            failed += 1
            print(f"  FAIL  {check.__name__}: {exc}")
    print(f"\n{len(checks) - failed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
