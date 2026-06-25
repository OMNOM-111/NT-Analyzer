# License Notes for Reference Strategies

## License Risk Categories

| status | meaning |
|--------|---------|
| `permissive` | Public domain concept or permissive license; OK for adaptation |
| `reference_only` | Open source but unknown/restrictive; use for reference, not copy-paste |
| `license_unknown_reference_only` | License not confirmed; reference/study use only |
| `not_usable` | Proprietary or explicitly non-commercial; do not adapt code |

---

## Strategy-level License Analysis

### REF-001: SMA 9/21 Crossover
- **License:** Public domain concept (MA crossover)
- **Status:** `permissive`
- **Notes:** Basic mathematical concept; no copyright on the trading idea itself.
  Any NT8 implementation written from scratch is original work.

### REF-002: EMA 8/21 Crossover
- **License:** Public domain concept
- **Status:** `permissive`
- **Notes:** Same as REF-001. EMA calculation described in technical analysis textbooks since 1960s.

### REF-003: EMA Trend Pullback
- **License:** Public domain concept
- **Status:** `permissive`
- **Notes:** Common multi-timeframe trend pullback concept; no proprietary elements.

### REF-004: MACD Histogram Trend
- **License:** Gerald Appel (MACD concept, 1979); Thomas Aspray (histogram) — both public domain
- **Status:** `permissive`
- **Notes:** MACD as indicator is public domain. Any NT8 implementation written fresh is original.

### REF-005: SuperTrend Trend Following
- **License:** Olivier Seban (SuperTrend concept) — widely published, public domain concept
- **Status:** `permissive`
- **Notes:** Indicator concept is public; specific code implementations vary by author.
  Must write fresh NT8 implementation; do not copy existing code.

### REF-006: RSI(2) Mean Reversion
- **License:** Larry Connors & Cesar Alvarez — described in published books (2009)
- **Status:** `reference_only`
- **Notes:** Concepts published in books available for purchase.
  The STRATEGY RULES are described publicly but the exact backtested system is proprietary.
  Use the published rules only. Do not reproduce book tables verbatim.
  RSI indicator itself (J. Welles Wilder, 1978) is public domain.

### REF-007: Bollinger Bands Mean Reversion
- **License:** John Bollinger (Bollinger Bands) — trademark on "Bollinger Bands" name
- **Status:** `permissive`
- **Notes:** The concept and calculation are public domain.
  The name "Bollinger Bands" is trademarked by John Bollinger.
  Mean-reversion STRATEGY using BB is public domain. Fine for NT8 implementation.

### REF-008: VWAP Pullback
- **License:** VWAP as a concept is public domain (widely used since 1980s)
- **Status:** `permissive`
- **Notes:** Basic intraday VWAP pullback concept has no proprietary owner.
  NT8 implementation written from scratch is original work.

### REF-009: VWAP Mean Reversion
- **License:** Public domain concept
- **Status:** `permissive`
- **Notes:** Same as REF-008.

### REF-010: RSI Extremes Mean Reversion
- **License:** RSI indicator: J. Welles Wilder (1978, public domain)
- **Status:** `permissive`
- **Notes:** RSI-based entry/exit rules are generic and widely described. Original NT8 code is fine.

### REF-011: Opening Range Breakout
- **License:** Toby Crabel — published in "Day Trading With Short Term Price Patterns" (1990)
- **Status:** `reference_only`
- **Notes:** The ORB CONCEPT is described publicly and widely taught.
  Crabel's specific statistical work is proprietary.
  The general ORB idea (trade breakout of first N-bar range) is public domain.
  Do not reproduce Crabel's specific optimized parameters without verification.

### REF-012: Opening Range Retest
- **License:** Public domain concept (derived from ORB)
- **Status:** `permissive`
- **Notes:** Retest entry variation on ORB is a generic concept.

### REF-013: Donchian Channel Breakout
- **License:** Richard Donchian (public domain concept, ~1950s)
- **Status:** `permissive`
- **Notes:** Turtle Trading System rules were made public in 1983 (Curtis Faith).
  Full Turtle rules available at originalturtles.org as public document.
  NT8 implementation from scratch is fine.

### REF-014: Previous Day High/Low Breakout
- **License:** Public domain concept
- **Status:** `permissive`
- **Notes:** PDH/PDL breakout is a generic widely-taught concept with no proprietary owner.

### REF-015: Range Compression Breakout (NR7)
- **License:** Toby Crabel (NR7 concept, published 1990)
- **Status:** `reference_only`
- **Notes:** NR7 concept is published and widely known.
  General "narrow range leading to expansion" concept is public domain.
  Do not directly copy Crabel's specific system parameters.

### REF-016: Previous Day High/Low Reclaim
- **License:** Public domain concept
- **Status:** `permissive`
- **Notes:** Level reclaim as entry concept is generic. No proprietary owner.

### REF-017: Liquidity Sweep Reversal
- **License:** ICT / Inner Circle Trader (Michael Huddleston) — educational concepts
- **Status:** `license_unknown_reference_only`
- **Notes:** ICT concepts are widely distributed via YouTube/public education.
  The specific terminology is associated with ICT who has been involved in disputes.
  Use as conceptual reference ONLY. Do not attribute ICT-specific terminology in production.
  General "stop hunt reversal" concept is public domain.

### REF-018: ATR Breakout Momentum
- **License:** ATR: J. Welles Wilder (1978, public domain)
- **Status:** `permissive`
- **Notes:** ATR-based breakout concept is generic and widely used.

### REF-019: Gap Fill / Gap Fade
- **License:** Public domain concept
- **Status:** `permissive`
- **Notes:** Gap trading concepts have been public domain for decades.

### REF-020: Trend Continuation Pullback
- **License:** Public domain concept
- **Status:** `permissive`
- **Notes:** Classic pullback trading concept with no proprietary owner.

### REF-021: ORB + VWAP Filter
- **License:** Composite public domain concept
- **Status:** `permissive`
- **Notes:** Combination of ORB (Crabel concept, reference_only) and VWAP (public domain).
  The COMBINATION is a new adaptation; specific combination is permissive.

### REF-022: Breakout + Volume Filter
- **License:** Public domain concept
- **Status:** `permissive`
- **Notes:** Volume-filtered breakout is a standard technical analysis concept.

### REF-023: EMA Stack (3 EMA Alignment)
- **License:** Public domain concept
- **Status:** `permissive`
- **Notes:** Multiple EMA alignment is widely described in public trading education.

### REF-024: VWAP + RSI Combined
- **License:** Both VWAP and RSI are public domain concepts
- **Status:** `permissive`
- **Notes:** The combination is a new adaptation.

### REF-025: MACD + RSI Confirmation
- **License:** Both MACD and RSI are public domain concepts
- **Status:** `permissive`
- **Notes:** The combination is widely described in public trading education.

---

## General License Policy

1. **Public domain concepts** → `permissive` → can implement fresh NT8 code
2. **Published book strategies** → `reference_only` → use rules only, not code
3. **Forum code** → `license_unknown_reference_only` → study only, do not copy
4. **NinjaTrader official samples** → subject to NinjaTrader EULA → reference only
5. **TradingView Pine scripts** → license varies per script → adapt only, never copy code
6. **GitHub repositories** → check individual LICENSE file → varies

## CRITICAL RULE

**No code from ANY external source may be used as a production strategy**
without human review and explicit approval, regardless of license.

This applies even to MIT-licensed code.

---

*Last updated: 2026-06-06*
