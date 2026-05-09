// NTAMicroVwapRiskExplorer.Entry.cs
// Signal evaluation, stop-entry placement, CancelPendingEntry, ComputeStopTicks.
// EvaluateEntry() is called from OnBarUpdate in the main file.
// Part of partial class NTAMicroVwapRiskExplorer.

using System;
using NinjaTrader.NinjaScript;
using NinjaTrader.NinjaScript.Strategies;

namespace NinjaTrader.NinjaScript.Strategies
{
    public partial class NTAMicroVwapRiskExplorer
    {
        // ----- Signal evaluation + stop-entry placement -----
        private void EvaluateEntry(int todHHMM)
        {
            // ----- Filters -----
            if (_adx[0] < MinAdx)                         { LogSkip("adx_low"); return; }
            if (Volume[0] < _volSma[0] * MinVolumeFactor) { LogSkip("vol_low"); return; }

            double vwapNow = _vwapSeries[0];
            bool trendUp   = _emaFast[0] > _emaSlow[0] && Close[0] > vwapNow;
            bool trendDown = _emaFast[0] < _emaSlow[0] && Close[0] < vwapNow;

            // Pullback: any of last N bars touched session VWAP or EMA(fast)
            bool pulledBack = false;
            int look = Math.Min(PullbackLookback, CurrentBar);
            for (int i = 1; i <= look; i++)
            {
                double v = _vwapSeries[i];
                if (Low[i] <= v && High[i] >= v) { pulledBack = true; break; }
                if (Low[i] <= _emaFast[i] && High[i] >= _emaFast[i]) { pulledBack = true; break; }
            }
            if (!pulledBack) { LogSkip("no_pullback"); return; }

            // v0.4: added Close[0]>Close[1] momentum filter (bar must close higher than prev)
            bool longSignal  = trendUp   && EnableLong  && Close[0] > Open[0]
                               && Close[0] > _emaFast[0] && Close[0] > Close[1];
            // v0.4: added Close[0]<Close[1] momentum filter
            bool shortSignal = trendDown && EnableShort && Close[0] < Open[0]
                               && Close[0] < _emaFast[0] && Close[0] < Close[1];
            if (!longSignal && !shortSignal) { LogSkip("no_signal"); return; }

            // ----- Daily bias filter (no-lookahead: [1] = yesterday's completed daily bar) -----
            // UseDailyBiasFilter=false → skip this block entirely (smoke / baseline parity).
            if (UseDailyBiasFilter)
            {
                bool dailyBullish = _dailyEmaFast[1] > _dailyEmaSlow[1];
                if (shortSignal && dailyBullish && BlockShortsWhenDailyBullish)
                {
                    LogSkip("daily_bias_blocks_short");
                    return;
                }
                if (longSignal && !dailyBullish && BlockLongsWhenDailyBearish)
                {
                    LogSkip("daily_bias_blocks_long");
                    return;
                }
            }

            // ----- Sizing -----
            int stopTicks = ComputeStopTicks();
            int qty = _risk.ComputeQuantity(stopTicks, RoundTurnCommission, SlippageTicks);
            if (qty < 1) { LogSkip("qty_lt_1"); return; }

            // ----- Stop-entry placement -----
            if (longSignal)
            {
                // BUG-1 FIX: protStop relative to trigger (not Close[0])
                // BUG-2 FIX: liveUntilCancelled=false -> auto-cancel at bar end
                double trigger  = High[0] + EntryOffsetTicks * TickSize;
                double protStop = trigger - stopTicks * TickSize;
                double target   = trigger + (int)Math.Round(stopTicks * RewardRiskRatio) * TickSize;

                SetStopLoss("Long",   CalculationMode.Price, protStop, false);
                SetProfitTarget("Long", CalculationMode.Price, target);
                EnterLongStopMarket(0, false, qty, trigger, "Long"); // liveUntilCancelled=false

                _pendingEntrySignal     = "Long";
                _pendingEntryBar        = CurrentBar;
                _pendingEntryStopPx     = trigger;
                _pendingEntryProtStopPx = protStop;
                _pendingEntryTargetPx   = target;
                _pendingEntryQty        = qty;
                _pendingStopTicks       = stopTicks;

                Print(string.Format(
                    "[ENTRY] LONG-stop qty={0} trig={1:F2} prot={2:F2} tgt={3:F2} stop={4}t adx={5:F1} vwap={6:F2}",
                    qty, trigger, protStop, target, stopTicks, _adx[0], vwapNow));
            }
            else
            {
                // BUG-1 FIX: protStop relative to trigger (not Close[0])
                // BUG-2 FIX: liveUntilCancelled=false -> auto-cancel at bar end
                double trigger  = Low[0] - EntryOffsetTicks * TickSize;
                double protStop = trigger + stopTicks * TickSize;
                double target   = trigger - (int)Math.Round(stopTicks * RewardRiskRatio) * TickSize;

                SetStopLoss("Short",   CalculationMode.Price, protStop, false);
                SetProfitTarget("Short", CalculationMode.Price, target);
                EnterShortStopMarket(0, false, qty, trigger, "Short"); // liveUntilCancelled=false

                _pendingEntrySignal     = "Short";
                _pendingEntryBar        = CurrentBar;
                _pendingEntryStopPx     = trigger;
                _pendingEntryProtStopPx = protStop;
                _pendingEntryTargetPx   = target;
                _pendingEntryQty        = qty;
                _pendingStopTicks       = stopTicks;

                Print(string.Format(
                    "[ENTRY] SHORT-stop qty={0} trig={1:F2} prot={2:F2} tgt={3:F2} stop={4}t adx={5:F1} vwap={6:F2}",
                    qty, trigger, protStop, target, stopTicks, _adx[0], vwapNow));
            }
        }

        private int ComputeStopTicks()
        {
            double atrTicks = _atr[0] / TickSize;
            int s = (int)Math.Round(atrTicks * AtrStopMult);
            if (s < MinStopTicks) s = MinStopTicks;
            if (s > MaxStopTicks) s = MaxStopTicks;
            return s;
        }

        private void CancelPendingEntry(string reason)
        {
            if (_pendingEntrySignal == null) return;
            // BUG-3 FIX: With liveUntilCancelled=false the NT8 order auto-cancels
            // at bar end — no need to re-issue with qty=0 (which didn't work anyway).
            // We only need to clear internal tracking state here.
            Print(string.Format("[EXIT:cancel_{0}] pending={1} bar={2}",
                                reason, _pendingEntrySignal, CurrentBar));
            _pendingEntrySignal = null;
            _pendingEntryBar    = -1;
        }
    }
}
