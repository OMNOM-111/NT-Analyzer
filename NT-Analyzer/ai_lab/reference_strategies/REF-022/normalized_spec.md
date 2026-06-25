# Normalized Spec: REF-022 — Breakout + Volume Expansion Filter

## Strategy Family
`breakout_filtered`

## Hypothesis
Price breakouts without volume expansion are often false: price moves beyond a level but
few participants back the move, leading to quick reversals. A genuine breakout has volume
expansion: more contracts traded than average, confirming institutional participation.
The volume filter improves breakout quality by requiring confirmation.

## Instrument Candidates
- MNQ (primary — good volume data quality on major exchanges)
- MES (secondary)
- MYM (tertiary)
- Note: MCL, MGC volumes are thinner but still useful

## Timeframe
- Primary: 5m, 15m
- Volume averaging period: typically 20 bars

## Session
- RTH: 09:30–15:00 ET
- Note: volume profiles vary by session (less volume ETH)
- Use RTH-normalized volume averages

## Indicators
1. Volume — current bar volume
2. VolumeAvg(20) = EMA or SMA of volume over 20 bars
3. VolExpansionFactor: trigger when Volume > VolumeAvg * factor
4. Any breakout level: ORB, PDH/PDL, compression, etc.
5. ATR(14) — stop sizing

## Entry Rules
**Long volume-confirmed breakout:**
1. Price breaks above key level (ORB High, PDH, resistance)
2. Current bar volume > VolumeAvg(20) * 1.5 (volume expansion)
3. Close > breakout level (not just wick)
4. Enter at next bar open

**Short volume-confirmed breakout:**
1. Price breaks below key level
2. Volume expansion confirmed
3. Close < breakout level
4. Enter at next bar open

## Exit Rules
- Same as corresponding breakout strategy (REF-011, REF-014, etc.)
- Volume is entry filter only, not exit criteria

## Parameters
| Parameter | Default | Range |
|-----------|---------|-------|
| VolumeAvgPeriod | 20 | [10, 30] |
| VolExpansionFactor | 1.5 | [1.2, 2.5] |
| AtrStopMult | 1.0 | [0.5, 2.0] |

## Expected Signal Frequency
- Reduces any breakout frequency by ~30-50%
- Monthly: depends on base strategy

## Failure Modes
1. Low-volume environments (pre-RTH, holidays) → filter rejects valid signals
2. Volume data can have data feed issues with some brokers
3. Volume expansion can be large on NEWS events (not technical) → enters on news breakout
4. VolumeAvg can lag → too-high or too-low baseline

## Why Volume Expansion Is A Good Filter
- Confirms institutional participation
- Reduces false breakouts by ~30-50% in theory
- Simple to implement in NT8 (Volume series is built-in)

## NT8 Implementation Note
```csharp
// NT8 Volume access
double currentVolume = Volume[0];
double avgVolume = SMA(Volume, VolAvgPeriod)[0]; // or EMA
bool volumeExpansion = currentVolume > avgVolume * VolExpansionFactor;
```

## Market Regimes
- All regimes: volume filter is regime-agnostic
- Works best when volume patterns are stable (avoid major holiday weeks)

## Overfit Risk
**LOW** — VolExpansionFactor (1.5) is a standard threshold. Keep at 1.5 unless
clear reason to change. Volume patterns are stable enough not to require optimization.
