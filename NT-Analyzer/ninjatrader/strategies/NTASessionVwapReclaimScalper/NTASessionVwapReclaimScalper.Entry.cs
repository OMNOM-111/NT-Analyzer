using System;
using NinjaTrader.Cbi;
using NinjaTrader.NinjaScript;
using NinjaTrader.NinjaScript.Strategies;

namespace NinjaTrader.NinjaScript.Strategies
{
    public abstract partial class NTASessionVwapReclaimScalper
    {
        private void EvaluateReclaimSetup()
        {
            if (!_orbBuilt) { LogSkip("or_not_built"); return; }
            if (!CommonFiltersPass()) return;

            int orTicks = (int)Math.Round((_orbHigh - _orbLow) / TickSize);
            if (orTicks < MinOpeningRangeTicks) { LogSkip("or_too_small"); return; }
            if (orTicks > MaxOpeningRangeTicks) { LogSkip("or_too_large"); return; }

            if (_activeBias == VwapReclaimDirection.None)
            {
                DetectOpeningImpulse();
                if (_activeBias == VwapReclaimDirection.None) { LogSkip("no_impulse"); return; }
            }

            if (CurrentBar - _impulseBar > MaxBarsAfterImpulse)
            {
                LogSkip("impulse_expired");
                ResetSetupState();
                return;
            }

            if (!_pullbackArmed)
            {
                DetectControlledPullback();
                if (!_pullbackArmed) { LogSkip("no_pullback"); return; }
            }

            if (CurrentBar - _pullbackBar > MaxBarsAfterPullback)
            {
                LogSkip("pullback_expired");
                ResetSetupState();
                return;
            }

            ConfirmAndPlaceEntry();
        }

        private bool CommonFiltersPass()
        {
            if (MinAdx > 0.0 && _adx[0] < MinAdx) { LogSkip("adx_low"); return false; }
            if (VolumeFactor(0) < MinVolumeFactor) { LogSkip("volume_low"); return false; }
            if (CountVwapCrosses(VwapCrossLookback) > MaxVwapCrosses) { LogSkip("vwap_chop"); return false; }
            if (Math.Abs(_emaFast[0] - _emaSlow[0]) / TickSize < MinEmaSpreadTicks) { LogSkip("ema_spread_low"); return false; }
            if (!BarQualityPasses(0, VwapReclaimDirection.None)) { LogSkip("bar_quality_low"); return false; }
            return true;
        }

        private void DetectOpeningImpulse()
        {
            int look = Math.Min(Math.Max(1, ImpulseLookbackBars), CurrentBar);
            double vwap = _vwapSeries[0];
            double slopeTicks = VwapSlopeTicks();
            double moveTicks = (Close[0] - Close[look]) / TickSize;
            double distTicks = (Close[0] - vwap) / TickSize;
            double orBuffer = OpeningRangeBreakBufferTicks * TickSize;

            bool longImpulse = EnableLong
                && Close[0] > _orbHigh + orBuffer
                && Close[0] > _emaFast[0]
                && _emaFast[0] > _emaSlow[0]
                && distTicks >= VwapDistanceThresholdTicks
                && slopeTicks >= MinVwapSlopeTicks
                && moveTicks >= MinImpulseMoveTicks;

            bool shortImpulse = EnableShort
                && Close[0] < _orbLow - orBuffer
                && Close[0] < _emaFast[0]
                && _emaFast[0] < _emaSlow[0]
                && -distTicks >= VwapDistanceThresholdTicks
                && -slopeTicks >= MinVwapSlopeTicks
                && -moveTicks >= MinImpulseMoveTicks;

            if (longImpulse)
            {
                _activeBias = VwapReclaimDirection.Long;
                _impulseBar = CurrentBar;
                _impulseExtreme = High[0];
                _impulseVwapDistanceTicks = distTicks;
                PrintSetupState("impulse_long");
            }
            else if (shortImpulse)
            {
                _activeBias = VwapReclaimDirection.Short;
                _impulseBar = CurrentBar;
                _impulseExtreme = Low[0];
                _impulseVwapDistanceTicks = -distTicks;
                PrintSetupState("impulse_short");
            }
        }

        private void DetectControlledPullback()
        {
            double vwap = _vwapSeries[0];
            double chop = VwapChopBandTicks * TickSize;
            double vwapBand = PullbackMaxDistanceFromVwapTicks * TickSize;
            double emaBand = PullbackTouchEmaTicks * TickSize;

            if (_activeBias == VwapReclaimDirection.Long)
            {
                if (Low[0] < vwap - chop)
                {
                    LogSkip("pullback_invalid_below_vwap");
                    ResetSetupState();
                    return;
                }

                double depthTicks = (_impulseExtreme - Low[0]) / TickSize;
                bool touchedStructure = Low[0] <= vwap + vwapBand || Low[0] <= _emaFast[0] + emaBand;
                if (touchedStructure && depthTicks >= MinPullbackDepthTicks && depthTicks <= MaxPullbackDepthTicks)
                {
                    _pullbackArmed = true;
                    _pullbackBar = CurrentBar;
                    _pullbackExtreme = Low[0];
                    _pullbackDepthTicks = depthTicks;
                    PrintSetupState("pullback_long");
                }
            }
            else if (_activeBias == VwapReclaimDirection.Short)
            {
                if (High[0] > vwap + chop)
                {
                    LogSkip("pullback_invalid_above_vwap");
                    ResetSetupState();
                    return;
                }

                double depthTicks = (High[0] - _impulseExtreme) / TickSize;
                bool touchedStructure = High[0] >= vwap - vwapBand || High[0] >= _emaFast[0] - emaBand;
                if (touchedStructure && depthTicks >= MinPullbackDepthTicks && depthTicks <= MaxPullbackDepthTicks)
                {
                    _pullbackArmed = true;
                    _pullbackBar = CurrentBar;
                    _pullbackExtreme = High[0];
                    _pullbackDepthTicks = depthTicks;
                    PrintSetupState("pullback_short");
                }
            }
        }

        private void ConfirmAndPlaceEntry()
        {
            double vwap = _vwapSeries[0];
            double reclaimBuffer = VwapReclaimBufferTicks * TickSize;

            if (_activeBias == VwapReclaimDirection.Long)
            {
                if (_pullbackArmed && Low[0] < _pullbackExtreme)
                {
                    _pullbackExtreme = Low[0];
                    _pullbackDepthTicks = (_impulseExtreme - _pullbackExtreme) / TickSize;
                }

                bool confirmed = EnableLong
                    && Close[0] > Open[0]
                    && Close[0] > vwap + reclaimBuffer
                    && Close[0] > _emaFast[0]
                    && Close[0] >= Close[1]
                    && BarQualityPasses(0, VwapReclaimDirection.Long)
                    && OptionalOrderflowPasses(VwapReclaimDirection.Long);
                if (!confirmed) { LogSkip("no_long_confirm"); return; }

                double trigger = High[0] + EntryOffsetTicks * TickSize;
                double stopPrice = Math.Min(_pullbackExtreme, vwap) - StopBeyondPullbackTicks * TickSize;
                int stopTicks = ComputeStopTicks(trigger, stopPrice, VwapReclaimDirection.Long);
                int qty = _risk.ComputeQuantity(stopTicks, RoundTurnCommission, SlippageTicks);
                if (qty < 1) { LogSkip("qty_lt_1"); return; }
                PlaceLongStop(trigger, stopTicks, qty, "vwap_reclaim_long");
            }
            else if (_activeBias == VwapReclaimDirection.Short)
            {
                if (_pullbackArmed && High[0] > _pullbackExtreme)
                {
                    _pullbackExtreme = High[0];
                    _pullbackDepthTicks = (_pullbackExtreme - _impulseExtreme) / TickSize;
                }

                bool confirmed = EnableShort
                    && Close[0] < Open[0]
                    && Close[0] < vwap - reclaimBuffer
                    && Close[0] < _emaFast[0]
                    && Close[0] <= Close[1]
                    && BarQualityPasses(0, VwapReclaimDirection.Short)
                    && OptionalOrderflowPasses(VwapReclaimDirection.Short);
                if (!confirmed) { LogSkip("no_short_confirm"); return; }

                double trigger = Low[0] - EntryOffsetTicks * TickSize;
                double stopPrice = Math.Max(_pullbackExtreme, vwap) + StopBeyondPullbackTicks * TickSize;
                int stopTicks = ComputeStopTicks(trigger, stopPrice, VwapReclaimDirection.Short);
                int qty = _risk.ComputeQuantity(stopTicks, RoundTurnCommission, SlippageTicks);
                if (qty < 1) { LogSkip("qty_lt_1"); return; }
                PlaceShortStop(trigger, stopTicks, qty, "vwap_reclaim_short");
            }
        }

        private int ComputeStopTicks(double trigger, double geometryStop, VwapReclaimDirection dir)
        {
            double rawTicks = dir == VwapReclaimDirection.Long
                ? (trigger - geometryStop) / TickSize
                : (geometryStop - trigger) / TickSize;
            int geometryTicks = (int)Math.Ceiling(Math.Max(1.0, rawTicks));
            int atrTicks = (int)Math.Round((_atr[0] / TickSize) * AtrStopMult);
            int stopTicks = Math.Max(geometryTicks, atrTicks);

            if (stopTicks < StopMinTicks) stopTicks = StopMinTicks;
            if (stopTicks > StopMaxTicks) stopTicks = StopMaxTicks;

            int affordable = _risk != null ? _risk.MaxAffordableStopTicks(RoundTurnCommission, SlippageTicks) : 0;
            if (affordable >= StopMinTicks && stopTicks > affordable)
                stopTicks = affordable;
            return stopTicks;
        }

        private void PlaceLongStop(double trigger, int stopTicks, int qty, string tag)
        {
            double stop = trigger - stopTicks * TickSize;
            int targetTicks = Math.Max(1, (int)Math.Round(stopTicks * RewardRiskRatio));
            double target = trigger + targetTicks * TickSize;
            string signal = TelemetrySignal("Long");

            SetStopLoss(signal, CalculationMode.Price, stop, false);
            SetProfitTarget(signal, CalculationMode.Price, target);
            EnterLongStopMarket(0, false, qty, trigger, signal);

            SetPendingState(signal, tag, trigger, stop, target, stopTicks, qty);
            LogEntryPlan(tag, "Long", trigger, stop, target, stopTicks, qty);
            ResetSetupState();
        }

        private void PlaceShortStop(double trigger, int stopTicks, int qty, string tag)
        {
            double stop = trigger + stopTicks * TickSize;
            int targetTicks = Math.Max(1, (int)Math.Round(stopTicks * RewardRiskRatio));
            double target = trigger - targetTicks * TickSize;
            string signal = TelemetrySignal("Short");

            SetStopLoss(signal, CalculationMode.Price, stop, false);
            SetProfitTarget(signal, CalculationMode.Price, target);
            EnterShortStopMarket(0, false, qty, trigger, signal);

            SetPendingState(signal, tag, trigger, stop, target, stopTicks, qty);
            LogEntryPlan(tag, "Short", trigger, stop, target, stopTicks, qty);
            ResetSetupState();
        }

        private void SetPendingState(string signal, string tag, double trigger, double stop, double target, int stopTicks, int qty)
        {
            _pendingEntrySignal = signal;
            _pendingSetupTag = tag;
            _pendingEntryBar = CurrentBar;
            _pendingEntryStopPx = trigger;
            _pendingProtStopPx = stop;
            _pendingTargetPx = target;
            _pendingEntryQty = qty;
            _pendingStopTicks = stopTicks;
            _pendingEntryOrder = null;
            _pendingCancelRequested = false;
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
            if (!string.IsNullOrEmpty(_lastDirection)) return _lastDirection;
            if (Position.MarketPosition == MarketPosition.Long) return TelemetrySignal("Long");
            if (Position.MarketPosition == MarketPosition.Short) return TelemetrySignal("Short");
            return "";
        }

        private void CancelPendingEntry(string reason)
        {
            if (_pendingEntrySignal == null) return;
            if (_pendingCancelRequested) return;
            Print("[EXIT:cancel_" + reason + "] pending=" + _pendingEntrySignal
                + " setup=" + _pendingSetupTag
                + " bar=" + CurrentBar);

            if (_pendingEntryOrder != null)
            {
                try
                {
                    CancelOrder(_pendingEntryOrder);
                    _pendingCancelRequested = true;
                    return;
                }
                catch (Exception ex)
                {
                    Print("[WARN] CancelOrder failed: " + ex.Message);
                }
            }

            ClearPendingEntryState();
        }

        private void ClearPendingEntryState()
        {
            _pendingEntrySignal = null;
            _pendingSetupTag = "";
            _pendingEntryBar = -1;
            _pendingEntryStopPx = 0.0;
            _pendingProtStopPx = 0.0;
            _pendingTargetPx = 0.0;
            _pendingEntryQty = 0;
            _pendingStopTicks = 0;
            _pendingEntryOrder = null;
            _pendingCancelRequested = false;
        }

        private double VwapSlopeTicks()
        {
            int look = Math.Min(Math.Max(1, VwapSlopeLookback), CurrentBar);
            return (_vwapSeries[0] - _vwapSeries[look]) / TickSize;
        }

        private double VolumeFactor(int barsAgo)
        {
            double baseVol = _volSma[barsAgo];
            if (baseVol <= 0.0) return 0.0;
            return Volume[barsAgo] / baseVol;
        }

        private bool BarQualityPasses(int barsAgo, VwapReclaimDirection dir)
        {
            double range = High[barsAgo] - Low[barsAgo];
            if (range <= TickSize * 0.5) return false;
            double body = Math.Abs(Close[barsAgo] - Open[barsAgo]);
            if (body / range < MinBodyRangePct) return false;

            if (dir == VwapReclaimDirection.Long)
            {
                double closeLocation = (Close[barsAgo] - Low[barsAgo]) / range;
                return closeLocation >= MinCloseLocationPct;
            }
            if (dir == VwapReclaimDirection.Short)
            {
                double closeLocation = (High[barsAgo] - Close[barsAgo]) / range;
                return closeLocation >= MinCloseLocationPct;
            }
            return true;
        }

        private bool OptionalOrderflowPasses(VwapReclaimDirection dir)
        {
            _lastDeltaState = "off";
            if (!UseDeltaFilter && !UseImbalanceFilter) return true;

            bool directionalBar = dir == VwapReclaimDirection.Long
                ? Close[0] > Open[0]
                : Close[0] < Open[0];
            bool volumePulse = VolumeFactor(0) >= DeltaVolumeFactor;
            _lastDeltaState = directionalBar && volumePulse ? "proxy_pass" : "proxy_fail";
            return directionalBar && volumePulse;
        }

        private int CountVwapCrosses(int lookback)
        {
            int look = Math.Min(Math.Max(1, lookback), CurrentBar - 1);
            int crosses = 0;
            for (int i = 1; i <= look; i++)
            {
                double prev = Close[i] - _vwapSeries[i];
                double now = Close[i - 1] - _vwapSeries[i - 1];
                if ((prev > 0.0 && now < 0.0) || (prev < 0.0 && now > 0.0))
                    crosses++;
            }
            return crosses;
        }
    }
}
