// NTAMicroMnqScalpPilot.Entry.cs
// 5 scalp setups dispatched from NTAMicroMnqScalpPilot.cs:
//   1. VwapPullbackScalp     — VWAP reclaim scalp
//   2. OrbContinuationScalp  — legacy immediate OR break
//   3. OrbRetestScalp        — 3-minute OR break + retest + continuation
//   4. EmaImpulseScalp       — EMA stack + pullback + momentum signal
//   5. FailedOrbReversalScalp- local failed high/low breakout reversal
//
// Shared helpers (PlaceLongStop/PlaceShortStop/ComputeStopTicks/CancelPendingEntry).

using System;
using NinjaTrader.Cbi;
using NinjaTrader.NinjaScript;
using NinjaTrader.NinjaScript.Strategies;

namespace NinjaTrader.NinjaScript.Strategies
{
    public partial class NTAMicroMnqScalpPilot
    {
        // =====================================================================
        // 1. VwapPullbackScalp
        //    Long: price was below VWAP, reclaims and closes above it.
        //    Short: price was above VWAP, loses and closes below it.
        // =====================================================================
        private void EvaluateEntry_VwapPullbackScalp(int todHHMM)
        {
            if (MinAdx > 0 && _adx[0] < MinAdx)           { LogSkip("adx_low"); return; }
            if (Volume[0] < _volSma[0] * MinVolumeFactor) { LogSkip("vol_low"); return; }

            double vwapNow = _vwapSeries[0];
            double vwapPrev = _vwapSeries[1];
            bool fastRising  = _emaFast[0] > _emaFast[1];
            bool fastFalling = _emaFast[0] < _emaFast[1];

            double reclaimBand = 2 * TickSize;
            bool reclaimedLong = Close[1] < vwapPrev || Low[0] <= vwapNow + reclaimBand;
            bool reclaimedShort = Close[1] > vwapPrev || High[0] >= vwapNow - reclaimBand;
            bool closesStrong = Close[0] >= (High[0] + Low[0]) / 2.0;
            bool closesWeak = Close[0] <= (High[0] + Low[0]) / 2.0;

            bool longSignal  = EnableLong
                                && reclaimedLong
                                && Close[0] > vwapNow
                                && Close[0] > Open[0]
                                && closesStrong
                                && (_emaFast[0] >= _emaMid[0] || fastRising);
            bool shortSignal = EnableShort
                                && reclaimedShort
                                && Close[0] < vwapNow
                                && Close[0] < Open[0]
                                && closesWeak
                                && (_emaFast[0] <= _emaMid[0] || fastFalling);
            if (!longSignal && !shortSignal) { LogSkip("no_signal"); return; }

            int stopTicks = ComputeStopTicks();
            int qty = _risk.ComputeQuantity(stopTicks, RoundTurnCommission, SlippageTicks);
            if (qty < 1) { LogSkip("qty_lt_1"); return; }

            if (longSignal) PlaceLongStop(High[0] + EntryOffsetTicks * TickSize, stopTicks, qty, "vwap_reclaim");
            else            PlaceShortStop(Low[0]  - EntryOffsetTicks * TickSize, stopTicks, qty, "vwap_reclaim");
        }

        // =====================================================================
        // 2. OrbContinuationScalp — break ABOVE OR high (long) / BELOW OR low (short)
        // =====================================================================
        private void EvaluateEntry_OrbContinuationScalp(int todHHMM)
        {
            if (!_orbBuilt) { LogSkip("orb_not_built"); return; }
            if (Volume[0] < _volSma[0] * MinVolumeFactor) { LogSkip("vol_low"); return; }

            double bufPx = OrbBreakoutBuffer * TickSize;
            bool longBreak  = EnableLong  && !_orbBreakoutLong  && Close[0] > _orbHigh + bufPx;
            bool shortBreak = EnableShort && !_orbBreakoutShort && Close[0] < _orbLow  - bufPx;
            if (!longBreak && !shortBreak) { LogSkip("no_orb_break"); return; }

            int stopTicks = ComputeStopTicks();
            // Optional widen: stop on opposite side of the OR if OR range >= MinStop and <= MaxStop.
            double orRange = (_orbHigh - _orbLow);
            int orRangeTicks = (int)Math.Round(orRange / TickSize);
            if (orRangeTicks > stopTicks && orRangeTicks <= MaxStopTicks)
                stopTicks = orRangeTicks;

            int qty = _risk.ComputeQuantity(stopTicks, RoundTurnCommission, SlippageTicks);
            if (qty < 1) { LogSkip("qty_lt_1"); return; }

            if (longBreak)
            {
                _orbBreakoutLong  = true;
                PlaceLongStop(High[0] + EntryOffsetTicks * TickSize, stopTicks, qty, "orb_cont");
            }
            else
            {
                _orbBreakoutShort = true;
                PlaceShortStop(Low[0] - EntryOffsetTicks * TickSize, stopTicks, qty, "orb_cont");
            }
        }

        // =====================================================================
        // 3. OrbRetestScalp — break OR; price retests OR level (within
        //    OrbRetestBars after first break); a new closing bar in trade
        //    direction confirms the hold. Triggers on the confirmation bar.
        // =====================================================================
        private void EvaluateEntry_OrbRetestScalp(int todHHMM)
        {
            if (!_orbBuilt) { LogSkip("orb_not_built"); return; }
            if (Volume[0] < _volSma[0] * MinVolumeFactor) { LogSkip("vol_low"); return; }

            // LONG retest: prior break above orbHigh (within OrbRetestBars), current
            // bar's Low touched orbHigh from above (retest), close back above orbHigh
            // with bullish momentum.
            bool wantLong = EnableLong
                            && !_orbBreakoutLong
                            && _orbBreakHighBar > 0
                            && (CurrentBar - _orbBreakHighBar) <= OrbRetestBars
                            && Low[0]   <= _orbHigh + (OrbBreakoutBuffer * TickSize)
                            && Close[0] >  _orbHigh
                            && Close[0] >  Open[0];

            bool wantShort = EnableShort
                             && !_orbBreakoutShort
                             && _orbBreakLowBar > 0
                             && (CurrentBar - _orbBreakLowBar) <= OrbRetestBars
                             && High[0]  >= _orbLow - (OrbBreakoutBuffer * TickSize)
                             && Close[0] <  _orbLow
                             && Close[0] <  Open[0];

            if (!wantLong && !wantShort) { LogSkip("no_orb_retest"); return; }

            int stopTicks = ComputeStopTicks();
            int qty = _risk.ComputeQuantity(stopTicks, RoundTurnCommission, SlippageTicks);
            if (qty < 1) { LogSkip("qty_lt_1"); return; }

            if (wantLong)
            {
                _orbBreakoutLong = true;
                PlaceLongStop(High[0] + EntryOffsetTicks * TickSize, stopTicks, qty, "orb_retest");
            }
            else
            {
                _orbBreakoutShort = true;
                PlaceShortStop(Low[0] - EntryOffsetTicks * TickSize, stopTicks, qty, "orb_retest");
            }
        }

        // =====================================================================
        // 4. EmaImpulseScalp — EMA stack alignment, pullback into EMA9/21,
        //    then bullish/bearish signal bar.
        // =====================================================================
        private void EvaluateEntry_EmaImpulseScalp(int todHHMM)
        {
            if (MinAdx > 0 && _adx[0] < MinAdx)           { LogSkip("adx_low"); return; }
            if (Volume[0] < _volSma[0] * MinVolumeFactor) { LogSkip("vol_low"); return; }

            int look = Math.Min(Math.Max(2, PullbackLookback), CurrentBar);
            bool stackUp   = _emaFast[0] > _emaMid[0] && (!RequireSlowTrend || _emaMid[0] > _emaSlow[0]);
            bool stackDown = _emaFast[0] < _emaMid[0] && (!RequireSlowTrend || _emaMid[0] < _emaSlow[0]);

            bool pulledLong = false;
            bool pulledShort = false;
            for (int i = 0; i <= look; i++)
            {
                if (Low[i] <= _emaFast[i] + TickSize || Low[i] <= _emaMid[i] + TickSize) pulledLong = true;
                if (High[i] >= _emaFast[i] - TickSize || High[i] >= _emaMid[i] - TickSize) pulledShort = true;
            }

            bool bullishBreak = Close[0] > High[1] || (Close[0] > Close[1] && _emaFast[0] >= _emaFast[1]);
            bool bearishBreak = Close[0] < Low[1]  || (Close[0] < Close[1] && _emaFast[0] <= _emaFast[1]);
            bool bullishSignal = Close[0] > Open[0] && Close[0] > _emaFast[0] && bullishBreak;
            bool bearishSignal = Close[0] < Open[0] && Close[0] < _emaFast[0] && bearishBreak;

            bool wantLong  = EnableLong  && stackUp   && pulledLong  && bullishSignal;
            bool wantShort = EnableShort && stackDown && pulledShort && bearishSignal;
            if (!wantLong && !wantShort) { LogSkip("no_impulse"); return; }

            int stopTicks = ComputeStopTicks();
            int qty = _risk.ComputeQuantity(stopTicks, RoundTurnCommission, SlippageTicks);
            if (qty < 1) { LogSkip("qty_lt_1"); return; }

            if (wantLong) PlaceLongStop(High[0] + EntryOffsetTicks * TickSize, stopTicks, qty, "ema_impulse");
            else          PlaceShortStop(Low[0]  - EntryOffsetTicks * TickSize, stopTicks, qty, "ema_impulse");
        }

        // =====================================================================
        // 5. FailedOrbReversalScalp — local high/low breakout fails and
        //    closes back through the broken level.
        // =====================================================================
        private void EvaluateEntry_FailedOrbReversalScalp(int todHHMM)
        {
            int look = Math.Min(OrbFailedLookback, CurrentBar);
            if (look < 2) { LogSkip("fail_warmup"); return; }

            double localHigh = High[1];
            double localLow  = Low[1];
            for (int i = 1; i <= look; i++)
            {
                if (High[i] > localHigh) localHigh = High[i];
                if (Low[i]  < localLow)  localLow  = Low[i];
            }

            double bufPx = OrbBreakoutBuffer * TickSize;
            bool failedUp   = High[0] >= localHigh + bufPx && Close[0] < localHigh && Close[0] < Open[0];
            bool failedDown = Low[0]  <= localLow  - bufPx && Close[0] > localLow  && Close[0] > Open[0];

            // Scalp variant: failed probe of the immediately previous bar's
            // extreme. This is intentionally narrower than a full swing-failure
            // pattern, but fires often enough for intraday research.
            failedUp   = failedUp   || (High[0] > High[1] && Close[0] < High[1] && Close[0] < Open[0]);
            failedDown = failedDown || (Low[0]  < Low[1]  && Close[0] > Low[1]  && Close[0] > Open[0]);

            bool wantShort = EnableShort && failedUp;
            bool wantLong  = EnableLong  && failedDown;

            if (!wantShort && !wantLong) { LogSkip("no_failed_breakout"); return; }

            int stopTicks = ComputeStopTicks();
            int qty = _risk.ComputeQuantity(stopTicks, RoundTurnCommission, SlippageTicks);
            if (qty < 1) { LogSkip("qty_lt_1"); return; }

            if (wantLong)
            {
                PlaceLongStop(High[0] + EntryOffsetTicks * TickSize, stopTicks, qty, "failed_breakout");
            }
            else
            {
                PlaceShortStop(Low[0] - EntryOffsetTicks * TickSize, stopTicks, qty, "failed_breakout");
            }
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

            int affordable = _risk != null
                ? _risk.MaxAffordableStopTicks(RoundTurnCommission, SlippageTicks)
                : 0;
            if (affordable >= MinStopTicks && s > affordable)
                s = affordable;

            return s;
        }

        private bool IsLiveHistoricalWarmup()
        {
            if (State != State.Historical) return false;
            if (Account == null || string.IsNullOrEmpty(Account.Name)) return false;
            return !string.Equals(Account.Name, "Backtest", StringComparison.OrdinalIgnoreCase);
        }

        private double RoundToValidTick(double price)
        {
            if (Instrument != null && Instrument.MasterInstrument != null)
                return Instrument.MasterInstrument.RoundToTickSize(price);
            if (TickSize > 0)
                return Math.Round(price / TickSize) * TickSize;
            return price;
        }

        private double SafeCurrentBid()
        {
            double bid = GetCurrentBid();
            if (bid <= 0 || double.IsNaN(bid) || double.IsInfinity(bid))
                bid = Close[0];
            return bid;
        }

        private double SafeCurrentAsk()
        {
            double ask = GetCurrentAsk();
            if (ask <= 0 || double.IsNaN(ask) || double.IsInfinity(ask))
                ask = Close[0];
            return ask;
        }

        private bool ValidateRealtimeEntryStop(bool isLong, double trigger, string tag)
        {
            if (State != State.Realtime) return true;

            double bid = SafeCurrentBid();
            double ask = SafeCurrentAsk();
            double refPx = isLong ? ask : bid;
            double distTicks = TickSize > 0 ? Math.Abs(trigger - refPx) / TickSize : 0.0;
            double maxDistTicks = Math.Max(8.0, Math.Max(MinStopTicks, MaxStopTicks) * 2.0);
            bool sideOk = isLong
                ? trigger >= RoundToValidTick(ask + TickSize)
                : trigger <= RoundToValidTick(bid - TickSize);

            if (!sideOk || distTicks > maxDistTicks)
            {
                Print(string.Format(
                    "[SKIP:live_entry_stop_invalid] tag={0} side={1} trigger={2:F2} bid={3:F2} ask={4:F2} distTicks={5:F1} maxTicks={6:F1}",
                    tag, isLong ? "long" : "short", trigger, bid, ask, distTicks, maxDistTicks));
                return false;
            }

            return true;
        }

        private void SetProtectiveStopLoss(string signal, double desiredStop, string reason)
        {
            double stop = RoundToValidTick(desiredStop);

            if (_lastProtectiveStopPrice > 0)
            {
                if (Position.MarketPosition == MarketPosition.Long
                    && stop <= _lastProtectiveStopPrice + (TickSize / 2.0))
                    return;
                if (Position.MarketPosition == MarketPosition.Short
                    && stop >= _lastProtectiveStopPrice - (TickSize / 2.0))
                    return;
            }

            if (State == State.Realtime)
            {
                double bid = SafeCurrentBid();
                double ask = SafeCurrentAsk();

                if (Position.MarketPosition == MarketPosition.Long)
                {
                    double maxSellStop = RoundToValidTick(bid - TickSize);
                    if (stop > maxSellStop)
                    {
                        Print(string.Format(
                            "[EXIT:live_stop_guard] reason={0} long desiredStop={1:F2} bid={2:F2} ask={3:F2}; market exit instead of invalid sell stop",
                            reason, stop, bid, ask));
                        ExitLong("LiveStopGuard", signal);
                        return;
                    }
                }
                else if (Position.MarketPosition == MarketPosition.Short)
                {
                    double minBuyStop = RoundToValidTick(ask + TickSize);
                    if (stop < minBuyStop)
                    {
                        Print(string.Format(
                            "[EXIT:live_stop_guard] reason={0} short desiredStop={1:F2} bid={2:F2} ask={3:F2}; market exit instead of invalid buy stop",
                            reason, stop, bid, ask));
                        ExitShort("LiveStopGuard", signal);
                        return;
                    }
                }
            }

            SetStopLoss(signal, CalculationMode.Price, stop, false);
            _lastProtectiveStopPrice = stop;
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
            trigger = RoundToValidTick(trigger);
            protStop = RoundToValidTick(protStop);
            target = RoundToValidTick(target);
            if (!ValidateRealtimeEntryStop(true, trigger, tag)) return;

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
            _pendingEntryOrder      = null;
            _pendingEntryCancelRequested = false;

            Print(string.Format("[ENTRY:{0}] LONG-stop qty={1} trig={2:F2} prot={3:F2} tgt={4:F2} stop={5}t",
                                 tag, qty, trigger, protStop, target, stopTicks));
        }

        private void PlaceShortStopExplicit(double trigger, double protStop, double target,
                                            int stopTicks, int qty, string tag)
        {
            trigger = RoundToValidTick(trigger);
            protStop = RoundToValidTick(protStop);
            target = RoundToValidTick(target);
            if (!ValidateRealtimeEntryStop(false, trigger, tag)) return;

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
            _pendingEntryOrder      = null;
            _pendingEntryCancelRequested = false;

            Print(string.Format("[ENTRY:{0}] SHORT-stop qty={1} trig={2:F2} prot={3:F2} tgt={4:F2} stop={5}t",
                                 tag, qty, trigger, protStop, target, stopTicks));
        }

        private void CancelPendingEntry(string reason)
        {
            if (_pendingEntrySignal == null) return;
            if (_pendingEntryCancelRequested) return;
            Print(string.Format("[EXIT:cancel_{0}] pending={1} bar={2}",
                                reason, _pendingEntrySignal, CurrentBar));

            if (_pendingEntryOrder != null)
            {
                try
                {
                    CancelOrder(_pendingEntryOrder);
                    _pendingEntryCancelRequested = true;
                    return;
                }
                catch (Exception ex)
                {
                    Print("[WARN] CancelOrder failed for pending entry: " + ex.Message);
                }
            }

            ClearPendingEntryState();
        }

        private void ClearPendingEntryState()
        {
            _pendingEntrySignal = null;
            _pendingEntryBar    = -1;
            _pendingEntryStopPx = 0.0;
            _pendingEntryProtStopPx = 0.0;
            _pendingEntryTargetPx = 0.0;
            _pendingEntryQty = 0;
            _pendingStopTicks = 0;
            _pendingEntryOrder = null;
            _pendingEntryCancelRequested = false;
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
