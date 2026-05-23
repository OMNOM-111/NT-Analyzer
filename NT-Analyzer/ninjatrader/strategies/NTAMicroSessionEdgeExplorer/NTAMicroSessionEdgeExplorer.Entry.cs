// NTAMicroSessionEdgeExplorer.Entry.cs
// All entry methods + shared helpers (PlaceLong/PlaceShort/ComputeStopTicks/CancelPendingEntry).
//
// Each EvaluateEntry_<Mode> is independent and uses the shared helpers below.
// Default SetupMode=VwapPullback is intentionally identical to
// NTAMicroVwapRiskExplorer v0.5 entry logic.

using System;
using NinjaTrader.Cbi;
using NinjaTrader.NinjaScript;
using NinjaTrader.NinjaScript.Strategies;

namespace NinjaTrader.NinjaScript.Strategies
{
    public abstract partial class NTAMicroSessionEdgeExplorer
    {
        // =====================================================================
        // 1. VwapPullback — identical to NTAMicroVwapRiskExplorer v0.5
        // =====================================================================
        private void EvaluateEntry_VwapPullback(int todHHMM)
        {
            if (_adx[0] < MinAdx)                         { LogSkip("adx_low"); return; }
            if (Volume[0] < _volSma[0] * MinVolumeFactor) { LogSkip("vol_low"); return; }

            double vwapNow = _vwapSeries[0];
            bool trendUp   = _emaFast[0] > _emaSlow[0] && Close[0] > vwapNow;
            bool trendDown = _emaFast[0] < _emaSlow[0] && Close[0] < vwapNow;

            bool pulledBack = false;
            int look = Math.Min(PullbackLookback, CurrentBar);
            for (int i = 1; i <= look; i++)
            {
                double v = _vwapSeries[i];
                if (Low[i] <= v && High[i] >= v) { pulledBack = true; break; }
                if (Low[i] <= _emaFast[i] && High[i] >= _emaFast[i]) { pulledBack = true; break; }
            }
            if (!pulledBack) { LogSkip("no_pullback"); return; }

            bool longSignal  = trendUp   && EnableLong  && Close[0] > Open[0]
                               && Close[0] > _emaFast[0] && Close[0] > Close[1];
            bool shortSignal = trendDown && EnableShort && Close[0] < Open[0]
                               && Close[0] < _emaFast[0] && Close[0] < Close[1];
            if (!longSignal && !shortSignal) { LogSkip("no_signal"); return; }

            if (UseDailyBiasFilter)
            {
                bool dailyBullish = _dailyEmaFast[1] > _dailyEmaSlow[1];
                if (shortSignal && dailyBullish && BlockShortsWhenDailyBullish)
                { LogSkip("daily_bias_blocks_short"); return; }
                if (longSignal && !dailyBullish && BlockLongsWhenDailyBearish)
                { LogSkip("daily_bias_blocks_long"); return; }
            }

            int stopTicks = ComputeStopTicks();
            int qty = _risk.ComputeQuantity(stopTicks, RoundTurnCommission, SlippageTicks);
            if (qty < 1) { LogSkip("qty_lt_1"); return; }

            if (longSignal) PlaceLongStop(High[0] + EntryOffsetTicks * TickSize, stopTicks, qty, "vwap_pb");
            else            PlaceShortStop(Low[0]  - EntryOffsetTicks * TickSize, stopTicks, qty, "vwap_pb");
        }

        // =====================================================================
        // 2. OrbContinuation — break ABOVE OR high (long) / BELOW OR low (short)
        // =====================================================================
        private void EvaluateEntry_OrbContinuation(int todHHMM)
        {
            if (!_orbBuilt) { LogSkip("orb_not_built"); return; }
            if (Volume[0] < _volSma[0] * MinVolumeFactor) { LogSkip("vol_low"); return; }

            double bufPx = OrbBreakoutBuffer * TickSize;
            bool longBreak  = EnableLong  && !_orbBreakoutLong  && Close[0] > _orbHigh + bufPx;
            bool shortBreak = EnableShort && !_orbBreakoutShort && Close[0] < _orbLow  - bufPx;
            if (!longBreak && !shortBreak) { LogSkip("no_orb_break"); return; }

            int stopTicks = ComputeStopTicks();
            // Stop on opposite side of the OR for ORB continuation.
            double orMid = (_orbHigh + _orbLow) / 2.0;
            double orRange = (_orbHigh - _orbLow);
            int orRangeTicks = (int)Math.Round(orRange / TickSize);
            if (orRangeTicks > stopTicks && orRangeTicks <= MaxStopTicks)
                stopTicks = orRangeTicks;

            int qty = _risk.ComputeQuantity(stopTicks, RoundTurnCommission, SlippageTicks);
            if (qty < 1) { LogSkip("qty_lt_1"); return; }

            if (longBreak)
            {
                _orbBreakoutLong  = true;
                _orbBreakoutBar   = CurrentBar;
                _orbBreakoutPrice = Close[0];
                PlaceLongStop(High[0] + EntryOffsetTicks * TickSize, stopTicks, qty, "orb_cont");
            }
            else
            {
                _orbBreakoutShort = true;
                _orbBreakoutBar   = CurrentBar;
                _orbBreakoutPrice = Close[0];
                PlaceShortStop(Low[0] - EntryOffsetTicks * TickSize, stopTicks, qty, "orb_cont");
            }
        }

        // =====================================================================
        // 3. FailedOrbReversal — breakout fails (price returns inside OR within
        //    OrbFailedLookback bars) → reverse against the breakout direction.
        // =====================================================================
        private void EvaluateEntry_FailedOrbReversal(int todHHMM)
        {
            if (!_orbBuilt) { LogSkip("orb_not_built"); return; }

            // Detect failure of a prior up-breakout: high broke above _orbHigh in last
            // OrbFailedLookback bars, but current close is back inside [orbLow, orbHigh]
            // and momentum is down (Close[0]<Close[1]).
            int look = Math.Min(OrbFailedLookback, CurrentBar);
            bool brokeUp = false, brokeDown = false;
            for (int i = 1; i <= look; i++)
            {
                if (High[i] > _orbHigh) brokeUp = true;
                if (Low[i]  < _orbLow ) brokeDown = true;
            }

            bool failedUp   = brokeUp   && Close[0] < _orbHigh && Close[0] < Close[1];
            bool failedDown = brokeDown && Close[0] > _orbLow  && Close[0] > Close[1];

            bool wantShort = EnableShort && failedUp   && !_orbBreakoutShort;
            bool wantLong  = EnableLong  && failedDown && !_orbBreakoutLong;

            if (!wantShort && !wantLong) { LogSkip("no_failed_orb"); return; }

            int stopTicks = ComputeStopTicks();
            int qty = _risk.ComputeQuantity(stopTicks, RoundTurnCommission, SlippageTicks);
            if (qty < 1) { LogSkip("qty_lt_1"); return; }

            if (wantLong)
            {
                _orbBreakoutLong = true;
                PlaceLongStop(High[0] + EntryOffsetTicks * TickSize, stopTicks, qty, "orb_fail_rev");
            }
            else
            {
                _orbBreakoutShort = true;
                PlaceShortStop(Low[0] - EntryOffsetTicks * TickSize, stopTicks, qty, "orb_fail_rev");
            }
        }

        // =====================================================================
        // 4. VwapMeanReversion — fade extension from session VWAP after spike.
        //    Long: Close >= MeanRevExtensionAtr ATRs BELOW VWAP, momentum up.
        //    Short: Close >= MeanRevExtensionAtr ATRs ABOVE VWAP, momentum down.
        // =====================================================================
        private void EvaluateEntry_VwapMeanReversion(int todHHMM)
        {
            double vwapNow = _vwapSeries[0];
            double atr     = _atr[0];
            if (atr <= 0.0) { LogSkip("atr_zero"); return; }

            double extAtr = (Close[0] - vwapNow) / atr; // positive = above VWAP

            bool wantShort = EnableShort && extAtr >=  MeanRevExtensionAtr && Close[0] < Close[1];
            bool wantLong  = EnableLong  && extAtr <= -MeanRevExtensionAtr && Close[0] > Close[1];

            if (!wantShort && !wantLong) { LogSkip("no_meanrev"); return; }

            int stopTicks = ComputeStopTicks();
            int qty = _risk.ComputeQuantity(stopTicks, RoundTurnCommission, SlippageTicks);
            if (qty < 1) { LogSkip("qty_lt_1"); return; }

            // Target = VWAP if MeanRevTargetVwap, else default RR.
            if (wantShort)
            {
                double trigger  = Low[0] - EntryOffsetTicks * TickSize;
                double protStop = trigger + stopTicks * TickSize;
                double target;
                if (MeanRevTargetVwap)
                {
                    int distTicks = (int)Math.Round((trigger - vwapNow) / TickSize);
                    if (distTicks < stopTicks) distTicks = stopTicks; // ensure 1R minimum
                    target = trigger - distTicks * TickSize;
                }
                else target = trigger - (int)Math.Round(stopTicks * RewardRiskRatio) * TickSize;

                PlaceShortStopExplicit(trigger, protStop, target, stopTicks, qty, "meanrev_short");
            }
            else
            {
                double trigger  = High[0] + EntryOffsetTicks * TickSize;
                double protStop = trigger - stopTicks * TickSize;
                double target;
                if (MeanRevTargetVwap)
                {
                    int distTicks = (int)Math.Round((vwapNow - trigger) / TickSize);
                    if (distTicks < stopTicks) distTicks = stopTicks;
                    target = trigger + distTicks * TickSize;
                }
                else target = trigger + (int)Math.Round(stopTicks * RewardRiskRatio) * TickSize;

                PlaceLongStopExplicit(trigger, protStop, target, stopTicks, qty, "meanrev_long");
            }
        }

        // =====================================================================
        // 5. CompressionBreakout — current ATR in lowest CompressionAtrPct of
        //    last CompressionLookback bars. On break of recent extreme, enter.
        // =====================================================================
        private void EvaluateEntry_CompressionBreakout(int todHHMM)
        {
            int cl = Math.Max(5, CompressionLookback);
            int look = Math.Min(cl, CurrentBar - 1);
            if (look < 5) { LogSkip("compress_warmup"); return; }

            double atrNow = _atr[0];
            // Count how many of last `look` ATR values are <= atrNow.
            int below = 0;
            for (int i = 1; i <= look; i++) if (_atr[i] <= atrNow) below++;
            double pct = (double)below / look;
            // Compression = atrNow is in the BOTTOM CompressionAtrPct fraction
            // → number of bars with ATR <= atrNow (including this bar) is
            //   small. Equivalent: pct <= CompressionAtrPct.
            if (pct > CompressionAtrPct) { LogSkip("no_compression"); return; }

            // Recent extremes (excluding current bar)
            double rh = High[1]; double rl = Low[1];
            for (int i = 2; i <= look; i++)
            {
                if (High[i] > rh) rh = High[i];
                if (Low[i]  < rl) rl = Low[i];
            }

            double bufPx = EntryOffsetTicks * TickSize;
            bool longBreak  = EnableLong  && Close[0] > rh - TickSize && Close[0] > Close[1];
            bool shortBreak = EnableShort && Close[0] < rl + TickSize && Close[0] < Close[1];
            if (!longBreak && !shortBreak) { LogSkip("no_compress_break"); return; }

            int stopTicks = ComputeStopTicks();
            int qty = _risk.ComputeQuantity(stopTicks, RoundTurnCommission, SlippageTicks);
            if (qty < 1) { LogSkip("qty_lt_1"); return; }

            if (longBreak) PlaceLongStop(High[0] + bufPx, stopTicks, qty, "compress");
            else           PlaceShortStop(Low[0]  - bufPx, stopTicks, qty, "compress");
        }

        // =====================================================================
        // 6. RollingVwapCrypto — 24h rolling VWAP cross with momentum + volume.
        //    Designed for 24/7 markets (MBT/MET). Set Use24hSession=true to
        //    bypass intraday window/force-flat logic.
        // =====================================================================
        private void EvaluateEntry_RollingVwapCrypto(int todHHMM)
        {
            if (_ringFilled < _ringTPV.Length / 4) { LogSkip("rvwap_warmup"); return; }
            // Looser volume filter for crypto.
            if (Volume[0] <= 0) { LogSkip("vol_zero"); return; }

            double rv = _rollingVwapSeries[0];
            double rvPrev = _rollingVwapSeries[1];

            // Cross detection on Close vs rolling VWAP.
            bool crossUp   = Close[1] <= rvPrev && Close[0] > rv && Close[0] > Close[1];
            bool crossDown = Close[1] >= rvPrev && Close[0] < rv && Close[0] < Close[1];

            bool wantLong  = EnableLong  && crossUp;
            bool wantShort = EnableShort && crossDown;
            if (!wantLong && !wantShort) { LogSkip("no_rvwap_cross"); return; }

            int stopTicks = ComputeStopTicks();
            int qty = _risk.ComputeQuantity(stopTicks, RoundTurnCommission, SlippageTicks);
            if (qty < 1) { LogSkip("qty_lt_1"); return; }

            if (wantLong) PlaceLongStop(High[0] + EntryOffsetTicks * TickSize, stopTicks, qty, "rvwap_long");
            else          PlaceShortStop(Low[0]  - EntryOffsetTicks * TickSize, stopTicks, qty, "rvwap_short");
        }

        // =====================================================================
        // Shared helpers
        // =====================================================================
        private int ComputeStopTicks()
        {
            double atrTicks = _atr[0] / TickSize;
            int s = (int)Math.Round(atrTicks * AtrStopMult);
            if (s < MinStopTicks) s = MinStopTicks;
            if (s > MaxStopTicks) s = MaxStopTicks;
            return s;
        }

        private void PlaceLongStop(double trigger, int stopTicks, int qty, string tag)
        {
            double protStop = trigger - stopTicks * TickSize;
            double target   = trigger + (int)Math.Round(stopTicks * RewardRiskRatio) * TickSize;
            PlaceLongStopExplicit(trigger, protStop, target, stopTicks, qty, tag);
        }

        private void PlaceShortStop(double trigger, int stopTicks, int qty, string tag)
        {
            double protStop = trigger + stopTicks * TickSize;
            double target   = trigger - (int)Math.Round(stopTicks * RewardRiskRatio) * TickSize;
            PlaceShortStopExplicit(trigger, protStop, target, stopTicks, qty, tag);
        }

        private void PlaceLongStopExplicit(double trigger, double protStop, double target,
                                           int stopTicks, int qty, string tag)
        {
            string signal = TelemetrySignal("Long");
            SetStopLoss(signal, CalculationMode.Price, protStop, false);
            SetProfitTarget(signal, CalculationMode.Price, target);
            EnterLongStopMarket(0, false, qty, trigger, signal);

            _pendingEntrySignal     = signal;
            _pendingEntryBar        = CurrentBar;
            _pendingEntryStopPx     = trigger;
            _pendingEntryProtStopPx = protStop;
            _pendingEntryTargetPx   = target;
            _pendingEntryQty        = qty;
            _pendingStopTicks       = stopTicks;

            Print(string.Format("[ENTRY:{0}] LONG-stop qty={1} trig={2:F2} prot={3:F2} tgt={4:F2} stop={5}t",
                                 tag, qty, trigger, protStop, target, stopTicks));
        }

        private void PlaceShortStopExplicit(double trigger, double protStop, double target,
                                            int stopTicks, int qty, string tag)
        {
            string signal = TelemetrySignal("Short");
            SetStopLoss(signal, CalculationMode.Price, protStop, false);
            SetProfitTarget(signal, CalculationMode.Price, target);
            EnterShortStopMarket(0, false, qty, trigger, signal);

            _pendingEntrySignal     = signal;
            _pendingEntryBar        = CurrentBar;
            _pendingEntryStopPx     = trigger;
            _pendingEntryProtStopPx = protStop;
            _pendingEntryTargetPx   = target;
            _pendingEntryQty        = qty;
            _pendingStopTicks       = stopTicks;

            Print(string.Format("[ENTRY:{0}] SHORT-stop qty={1} trig={2:F2} prot={3:F2} tgt={4:F2} stop={5}t",
                                 tag, qty, trigger, protStop, target, stopTicks));
        }

        private void CancelPendingEntry(string reason)
        {
            if (_pendingEntrySignal == null) return;
            Print(string.Format("[EXIT:cancel_{0}] pending={1} bar={2}",
                                reason, _pendingEntrySignal, CurrentBar));
            _pendingEntrySignal = null;
            _pendingEntryBar    = -1;
        }

        private string TelemetrySignal(string side)
        {
            return GetType().Name + "." + side;
        }

        private bool IsEntrySignalName(string name)
        {
            if (string.IsNullOrEmpty(name)) return false;
            if (_pendingEntrySignal != null && name == _pendingEntrySignal) return true;
            return name == TelemetrySignal("Long") || name == TelemetrySignal("Short")
                || name == "Long" || name == "Short";
        }

        private string ActiveEntrySignalForPosition()
        {
            if (!string.IsNullOrEmpty(_activeEntrySignal)) return _activeEntrySignal;
            if (Position.MarketPosition == MarketPosition.Long) return TelemetrySignal("Long");
            if (Position.MarketPosition == MarketPosition.Short) return TelemetrySignal("Short");
            return "";
        }
    }
}
