# Rejected Strategies List

## Strategies Disqualified from Reference Library

These strategies are documented here so AI knows to AVOID their patterns.

---

## REJECTED-001: Martingale / Grid Averaging

**Pattern:** After each losing trade, double position size to recover losses.
**Why rejected:**
- Exponential loss exposure on consecutive losing streak
- Single large trade can blow $2k account
- Disqualified under NT-Analyzer hard rules
**Risk flag:** `martingale`
**Do not use reason:** Catastrophic loss risk; prohibited in NT-Analyzer

---

## REJECTED-002: No-Stop Loss Systems

**Pattern:** Any strategy that operates without a hard stop loss.
**Examples:** Original Connors RSI(2) system, some grid systems
**Why rejected:**
- NT8 bridge executes in Historical mode; no circuit breaker except hard stop
- Trend continuation = unlimited loss
- All NT-Analyzer strategies MUST have SetStopLoss
**Risk flag:** `no_stop_in_original`
**Do not use reason:** Mandatory stop loss in all NT-Analyzer strategies

---

## REJECTED-003: Live Account API Access

**Pattern:** Strategies that use broker account API (real equity, live P&L) for signals.
**Why rejected:**
- NT-Analyzer is historical backtest only
- Live account API calls in Historical mode = errors or wrong data
- Security risk: strategy could access real account state
**Risk flag:** `uses_live_account_api`
**Do not use reason:** Historical backtest only; no live account access permitted

---

## REJECTED-004: Overnight Hold Strategies (for current pipeline)

**Pattern:** Strategies designed to hold positions overnight (multi-day holds).
**Why rejected for current pipeline:**
- NT-Analyzer intraday pipeline requires IsExitOnSessionCloseStrategy = true
- Overnight risk is not modeled in $2k account calculations
- Margin requirements change overnight
**Risk flag:** `requires_overnight_hold`
**Current limitation:** Not supported; may be added in future pipeline version

---

## REJECTED-005: Gap-And-Go Settlement Fade (2024-2025 Regime)

**Pattern:** Fade overnight settlement gap at RTH open.
**Reason for rejection:**
- CELL-019 Engine #3 and #4: deeply negative on MNQ/MES in 2024-2025
- Smoke mirage observed (M2K smoke +446.7 → Full -31.6)
- 2024-2025 equity index regime: gaps CONTINUE more than fill
**Applicable instruments:** MNQ, MES, MYM, M2K
**May work:** MGC, MCL (commodity gap dynamics differ)
**Risk flag:** `wrong_regime_2024_2025`

---

## REJECTED-006: 5m High-Frequency Mean Reversion on Micros

**Pattern:** Mean reversion on 5m bars with $1.90/RT commission.
**Reason for rejection:**
- CELL-019 Engine #2: 518 trades gross $756 = $1.46/trade < $1.90 commission
- Structural commission drag: strategy cannot be profitable at this frequency
- Same-bar% 76-93% → stops too tight
**Applicable instruments:** All micros (MNQ, MES, MYM, etc.)
**May work:** Same concept on 15m+ with larger targets
**Risk flag:** `commission_drag_structural`

---

## REJECTED-007: NR7 Compression Without Directional Filter

**Pattern:** Trade breakout from narrowest range bar in 7 bars, both directions.
**Reason for rejection:**
- CELL-019 PreCash Compression: near-zero/negative, almost no trades
- Without directional filter: random direction → expected 0 PF by chance
- Compression is a SETUP condition, not a direction signal
**Fix required:** Add EMA bias + VWAP confirmation before using
**Risk flag:** `no_directional_filter`

---

## REJECTED-008: Unlimited Daily Trade Count

**Pattern:** No limit on daily entries, allowing 10-20 trades per day.
**Reason for rejection:**
- CELL-005 overtrading lesson: multiple entries in trending day = successive losses
- Commission drag: 10 trades/day = $19/day minimum in commission
- Risk accumulation beyond daily loss cap
**Fix required:** MaxTradesPerDay = 2-3 hard limit
**Risk flag:** `overtrading`

---

## REJECTED-009: Breakout Without Volume or Level Confirmation

**Pattern:** Enter any breakout of any level without requiring volume confirmation.
**Reason for rejection:**
- High false breakout rate without confirmation
- Random noise can trigger breakout signal (thin liquidity)
- CELL-019 shows filters dramatically improve signal quality
**Fix required:** Add either volume expansion filter OR require close beyond level

---

## REJECTED-010: VWAP Strategies Outside RTH Without Recalculation

**Pattern:** Use session VWAP during ETH hours without reset or recalculation.
**Reason for rejection:**
- VWAP resets at RTH open; ETH VWAP is based on thin overnight volume
- ETH VWAP is meaningless as institutional benchmark
- Anchor VWAP to RTH session open for valid institutional reference
**Fix required:** Use anchored VWAP starting from RTH open; or use daily VWAP only during RTH

---

*Last updated: 2026-06-06*
