# PAPER B1 ShortOnly — CHECKLIST

Companion to `PAPER_B1_SHORTONLY_RUNBOOK.md` and `PAPER_B1_SHORTONLY_PROFILE.json`.

---

## A. Pre-launch (one-time, before paper Day 1)

- [ ] Phase 15A archive complete — rejected strategies moved to `Strategies_ARCHIVE_REJECTED_20260501\`.
- [ ] `ARCHIVE_MANIFEST.md` reviewed.
- [ ] **NinjaTrader F5 compile passed** with no errors. (BLOCKER — user action)
- [ ] Strategy selector lists `NTAMicroVwapRiskPilot`.
- [ ] Strategy selector does NOT list `NTAMicroOrbPilot`, `NTAMicroVwapGapMirrorPilot`, `NTAMicroVwapMeanRevertPilot`.
- [ ] Phase 15B sverka PASS — 92 trades, Adj +$2 738.30, aPF 2.49, DD −$174 (within $1 / 0.02 PF tolerance).
- [ ] Locked parameter set saved as NinjaTrader strategy template `B1_ShortOnly_locked_v14R`.
- [ ] Sim101 (or equivalent) account selected, $2 000 starting balance.
- [ ] CME US Index Futures RTH session template confirmed.
- [ ] Active MNQ front-month contract identified (e.g., MNQ 06-26).
- [ ] Daily journal CSV + XLSX present in `PAPER_B1_SHORTONLY\`.
- [ ] Risk limits configured / acknowledged (daily −$200 / weekly −$400 / trailing −$300).
- [ ] Live trading explicitly disabled in NinjaTrader account settings or strategy mode.

---

## B. Daily pre-session (every trading day, 05:30–06:30 PT)

- [ ] No orphaned positions from prior session.
- [ ] No risk-limit breach carrying over (daily/weekly/trailing).
- [ ] Market data feed live for active MNQ front month.
- [ ] Strategy template loads with correct locked params.
- [ ] System clock synced (PT).
- [ ] Front-month roll check (T-2 days before expiry → switch).

---

## C. Daily intra-session

- [ ] Strategy enabled at 06:30 PT.
- [ ] Entry window 06:35–07:00 PT — no manual override.
- [ ] Position size respects `UserMaxContracts=5`.
- [ ] On any error / disconnect → log and follow incident procedure.

---

## D. Daily post-session (after 13:00 PT RTH close)

- [ ] Strategy disabled.
- [ ] Position flat (intraday-only).
- [ ] Daily journal row filled (XLSX preferred — formulas auto-populate cumulative metrics).
- [ ] Pass/fail flags reviewed (none should trip during normal day).
- [ ] If any kill switch tripped → strategy disabled accordingly, incident logged.

---

## E. Weekly review (Friday post-close PT)

- [ ] Weekly adjusted PnL acceptable (no breach of −$400).
- [ ] Median slippage ≤ 1.5 ticks for the week.
- [ ] No more than 4 consecutive losing days.
- [ ] Distribution sanity check vs backtest (avg trade ~$25–30, win % roughly tracking 50–55).
- [ ] Front-month roll calendar check (next 2 weeks).

---

## F. Paper duration gate

- [ ] ≥ 60 trading days completed.
- [ ] ≥ 25 completed trades.
- [ ] No live-review request before BOTH satisfied.

---

## G. Paper review — PASS (all required)

- [ ] adj PF ≥ 1.50
- [ ] win % ≥ 45 %
- [ ] max DD ≤ $300
- [ ] zero daily/weekly/trailing risk breaches
- [ ] zero recurring platform/data/fill issues
- [ ] median slippage acceptable (≤ 1.5 ticks)
- [ ] avg trade and distribution not obviously worse than backtest

→ PROMOTE to live-review (separate checklist; not in this document).

---

## H. Paper review — FAIL (any of)

- [ ] adj PF < 1.20
- [ ] DD > $300
- [ ] < 10 trades after 90 trading days
- [ ] repeated execution / platform issues
- [ ] strategy behavior differs from locked backtest

→ DISABLE strategy, document failure mode in `02_РЕЗУЛЬТАТЫ_ТЕСТОВ_v0.5.md` § 15-FAIL, return to research (Phase 16). Do NOT relax thresholds. Do NOT re-introduce archived strategies.

---

## I. Forbidden actions during paper

- [ ] Do NOT change any locked parameter.
- [ ] Do NOT add filters / EMAs / time windows.
- [ ] Do NOT enable Long side.
- [ ] Do NOT increase `UserMaxContracts`.
- [ ] Do NOT lower `RoundTurnCommission` below $1.90.
- [ ] Do NOT lower `SlippageTicks` below 1 in validation backtests.
- [ ] Do NOT switch to Standard fill resolution for any acceptance test.
- [ ] Do NOT promote to live without paper-review PASS.
