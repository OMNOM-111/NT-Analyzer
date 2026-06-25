# Pattern Effectiveness Analysis

## Based on Reference Library + CELL-019 Results

## Tier 1: Highest Potential (Recommended for AI-CELL-007/008)

### 1. ORB + VWAP Filter (REF-021)
- **Why:** ORB is robust on equity index futures; VWAP filter adds institutional alignment
- **Evidence:** ORB concept is academically documented; VWAP widely used by institutions
- **Risk:** Fake breakouts (VWAP filter reduces this)
- **Recommended TF:** 15m RTH
- **Target instrument:** MNQ, MES
- **Key constraint:** Max 2 trades/day; 30-min ORB window; VWAP alignment required

### 2. EMA Trend Pullback (REF-003)
- **Why:** Higher R:R than crossovers; natural support/resistance entries
- **Evidence:** Classical concept proven across instruments and timeframes
- **Risk:** 2025 regime has more reversals; needs regime filter
- **Recommended TF:** 15m, 1H RTH
- **Target instrument:** MNQ, MGC
- **Key constraint:** ADX > 25 required; max 2 trades/day

### 3. Previous Day H/L Breakout + ATR Buffer (REF-014)
- **Why:** Clean levels, self-fulfilling, simple to code correctly in NT8
- **Evidence:** Widely used level; good institutional reference point
- **Risk:** Fake breakouts on choppy days
- **Recommended TF:** 5m-15m entry after 10:00 ET
- **Key constraint:** ATR buffer on level; volume filter optional but helpful

---

## Tier 2: Good Reference, Needs Careful Adaptation

### 4. EMA 8/21 Crossover (REF-002)
- **Potential:** Simple, few parameters, low overfit risk
- **Limitation:** Laggy signals; poor in choppy 2025 environment
- **Use as:** Baseline benchmark for testing framework

### 5. VWAP Pullback RTH (REF-008)
- **Potential:** Near-passed CELL-019 gates (MGC PF 1.171 Full)
- **Limitation:** OOS PF 1.052 < 1.25 gate; needs additional filter
- **Use as:** Foundation for combined signal strategies

### 6. Liquidity Sweep Reversal (REF-017)
- **Potential:** CELL-015 was ACCEPTED — this pattern works on pre-RTH MNQ
- **Limitation:** Hard to codify precisely; requires tight stop range (4-10 ticks)
- **Use as:** Primary reference for pre-RTH strategies

### 7. Range Compression Breakout with Directional Filter (REF-015)
- **Potential:** Could work with EMA bias added
- **Limitation:** CELL-019 PreCash failed without directional filter
- **Use as:** Only with mandatory EMA+VWAP directional confirmation

---

## Tier 3: Educational / Cautionary Reference

### 8. Gap Fill Strategy (REF-019)
- **Lesson:** Gap fade structurally hard on 2024-2025 equity index micros
- **Use as:** Warning reference; test on MGC/MCL only

### 9. VWAP Mean Reversion 5m (REF-009)
- **Lesson:** Commission drag structural problem at $1.90/RT on micros
- **Use as:** Demonstrates why 5m mean reversion fails for $2k account

### 10. RSI(2) Mean Reversion (REF-006)
- **Lesson:** No stop = disqualified for futures; daily TF not suitable for intraday pipeline
- **Use as:** Shows RSI(2) as signal component; add stop always

---

## Anti-Patterns (Do Not Use Standalone)

| Pattern | Reason | Reference |
|---------|--------|-----------|
| High-frequency mean reversion 5m | Commission drag structural | REF-009 |
| Gap fade without regime filter | Structurally fails 2024-2025 MNQ | REF-019 |
| Compression breakout without direction | Random direction → negative | REF-015 |
| No stop loss system | Disqualified for futures | REF-006 |
| Unlimited daily trades | Overtrading in trend | CELL-005 lesson |

---

## Effective Filter Combinations (Proven in Literature)

| Base Strategy | Add Filter | Expected Improvement |
|---------------|-----------|---------------------|
| Any breakout | VWAP alignment | ~30-40% false breakout reduction |
| Any trend entry | ADX > 25 | Filters choppy days |
| Any breakout | Volume > avg * 1.5 | ~20-30% false breakout reduction |
| Mean reversion | ADX < 25 | Avoids trending market entries |
| ORB | VWAP side alignment | Higher quality breakouts |
| EMA pullback | RSI not extreme | Better R:R entries |

---

## Position Sizing Guide for $2k Account on MNQ

| Stop (ticks) | contractRisk | byRisk (budget=$12) | Viable? |
|------|--------|--------|--------|
| 4 | $3.90 | 3 ✓ | Yes |
| 8 | $5.90 | 2 ✓ | Yes |
| 12 | $7.90 | 1 ✓ | Yes (minimum) |
| 16 | $9.90 | 1 ✓ | Yes (marginal) |
| 20 | $11.90 | 1 ✓ | Yes (floor=1) |
| 30 | $16.90 | 0 ✗ | Need floor=1 |
| 40 | $21.90 | 0 ✗ | Need floor=1 |

*contractRisk = stopTicks * $0.50 + $1.90 commission + $0.50 slippage*
*riskBudget = $2000 * 0.6% = $12 (approximate)*
*Floor fix required when stopTicks > 24*

---

*Last updated: 2026-06-06*
