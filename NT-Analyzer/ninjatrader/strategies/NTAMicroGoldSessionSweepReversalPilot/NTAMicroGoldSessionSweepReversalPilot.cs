// =============================================================================
// NTAMicroGoldSessionSweepReversalPilot
// -----------------------------------------------------------------------------
// Narrow MGC intraday research engine for CELL-004 backup path.
// =============================================================================

#region Using declarations
using System;
using System.ComponentModel.DataAnnotations;
using NinjaTrader.Cbi;
using NinjaTrader.Data;
using NinjaTrader.NinjaScript;
using NinjaTrader.NinjaScript.Indicators;
using NinjaTrader.NinjaScript.Strategies;
#endregion

namespace NinjaTrader.NinjaScript.Strategies
{
    public enum GoldSweepAnchorMode
    {
        PriorSession = 0,
        OpeningRange = 1,
        Both = 2
    }

    public enum GoldSweepTargetMode
    {
        FixedRR = 0,
        VwapThenRR = 1,
        VwapOnly = 2
    }

    public class NTAMicroGoldSessionSweepReversalPilot : Strategy
    {
        private EMA _emaFast;
        private EMA _emaSlow;
        private ATR _atr;
        private ADX _adx;
        private SMA _volSma;
        private Series<double> _vwapSeries;

        private DateTime _sessionDate = DateTime.MinValue;
        private double _sessionHigh;
        private double _sessionLow;
        private double _priorSessionHigh;
        private double _priorSessionLow;
        private bool _hasPriorSession;

        private double _vwapCumPV;
        private double _vwapCumVol;

        private double _orHigh;
        private double _orLow;
        private bool _orStarted;
        private bool _orBuilt;

        private bool _longArmed;
        private bool _shortArmed;
        private int _longSweepBar = -1;
        private int _shortSweepBar = -1;
        private double _longSweepLevel;
        private double _shortSweepLevel;
        private double _longSweepExtreme;
        private double _shortSweepExtreme;
        private string _longAnchorTag = "";
        private string _shortAnchorTag = "";

        private string _pendingEntrySignal = null;
        private string _activeEntrySignal = null;
        private string _pendingSetupTag = "";
        private int _pendingEntryBar = -1;
        private int _pendingEntryQty;
        private int _pendingStopTicks;
        private Order _pendingEntryOrder = null;
        private bool _pendingCancelRequested;

        private double _lastEntryPrice;
        private int _lastEntryBar = -1;
        private int _lastStopTicks;

        private DateTime _weekStartDate = DateTime.MinValue;
        private double _cumulativeRealizedPnl;
        private double _sessionRealizedPnl;
        private double _weeklyRealizedPnl;
        private int _tradesToday;
        private int _consecutiveLosses;
        private int _lastProcessedTradeCount;
        private DateTime _pauseUntil = DateTime.MinValue;
        private bool _permanentlyStopped;
        private bool _sessionStopped;

        private int _lastSkipBar = -1;
        private string _lastSkipReason = "";

        protected override void OnStateChange()
        {
            if (State == State.SetDefaults)
            {
                Description = "MGC session sweep reversal pilot for NT-Analyzer CELL-004 research.";
                Name = "NTAMicroGoldSessionSweepReversalPilot";
                Calculate = Calculate.OnBarClose;
                EntriesPerDirection = 1;
                EntryHandling = EntryHandling.AllEntries;
                IsExitOnSessionCloseStrategy = true;
                ExitOnSessionCloseSeconds = 30;
                IsFillLimitOnTouch = false;
                MaximumBarsLookBack = MaximumBarsLookBack.TwoHundredFiftySix;
                OrderFillResolution = OrderFillResolution.Standard;
                Slippage = 0;
                StartBehavior = StartBehavior.WaitUntilFlat;
                TimeInForce = TimeInForce.Day;
                TraceOrders = false;
                RealtimeErrorHandling = RealtimeErrorHandling.StopCancelClose;
                StopTargetHandling = StopTargetHandling.PerEntryExecution;
                BarsRequiredToTrade = 30;
                IsInstantiatedOnEachOptimizationIteration = true;

                InstrumentName = "MGC";
                ContractName = "MGC 06-26";
                SessionTemplateName = "Nymex Metals RTH1";
                BaseTimeframeSeconds = 300;

                StartingCapital = 2000.0;
                IntradayOnly = true;
                ActiveMarginPerContract = 1000.0;
                MaxContractsByCapital = 20;
                InstrumentStatus = "allowed";
                MarginSourceBroker = "NinjaTrader";

                EnableLong = true;
                EnableShort = true;
                AnchorMode = GoldSweepAnchorMode.Both;
                TargetMode = GoldSweepTargetMode.FixedRR;

                TradeStartTime = 600;
                TradeEndTime = 1000;
                ForceFlatTime = 1245;
                OpeningRangeStartTime = 600;
                OpeningRangeMinutes = 30;

                EmaFastPeriod = 9;
                EmaSlowPeriod = 34;
                AtrPeriod = 14;
                AdxPeriod = 14;
                VolumeSmaPeriod = 20;
                MinAdx = 0.0;
                MinVolumeFactor = 1.05;
                MinBodyRangePct = 0.25;
                MinCloseLocationPct = 0.55;
                UseTrendFilter = false;
                UseVwapSideFilter = true;
                MinDistanceToVwapTicks = 4;

                SweepDistanceTicks = 2;
                ReturnInsideTicks = 1;
                SweepMaxBarsToReturn = 3;
                MinOpeningRangeTicks = 6;
                MaxOpeningRangeTicks = 80;
                StopBeyondSweepTicks = 2;
                ClampStopToMaxTicks = true;
                MinStopTicks = 10;
                MaxStopTicks = 18;
                AtrStopMult = 0.35;
                RewardRiskRatio = 2.0;
                EntryOffsetTicks = 1;
                EntryTimeoutBars = 2;
                MinTargetTicks = 8;
                VwapTargetOffsetTicks = 1;
                TimeStopBars = 6;
                MinProgressR = 0.15;

                RiskPerTradePct = 1.0;
                UserMaxContracts = 1;
                MaxOpenPositions = 1;
                DailyLossLimit = 60.0;
                WeeklyLossLimit = 150.0;
                MaxTradesPerDay = 5;
                HardMaxTradesPerDay = 7;
                MaxConsecutiveLosses = 3;
                PauseAfterConsecutiveLosses = 2;
                PauseMinutesAfterLosses = 15;
                RoundTurnCommission = 1.90;
                SlippageTicks = 1;
            }
            else if (State == State.Configure)
            {
            }
            else if (State == State.DataLoaded)
            {
                _emaFast = EMA(EmaFastPeriod);
                _emaSlow = EMA(EmaSlowPeriod);
                _atr = ATR(AtrPeriod);
                _adx = ADX(AdxPeriod);
                _volSma = SMA(Volume, VolumeSmaPeriod);
                _vwapSeries = new Series<double>(this);

                _permanentlyStopped = StartingCapital <= 0.0
                    || ActiveMarginPerContract <= 0.0
                    || MaxContractsByCapital < 1
                    || string.Equals(InstrumentStatus, "blocked", StringComparison.OrdinalIgnoreCase)
                    || string.Equals(InstrumentStatus, "unknown", StringComparison.OrdinalIgnoreCase);

                Print("[INIT] " + Name
                    + " instrument=" + InstrumentName
                    + " contract=" + ContractName
                    + " anchor=" + AnchorMode
                    + " target=" + TargetMode);
            }
        }

        protected override void OnBarUpdate()
        {
            if (BarsInProgress != 0) return;
            if (CurrentBar < 1) return;

            UpdateSessionState();
            UpdateVwap();
            UpdateOpeningRange();
            UpdateRiskStops();
            ManagePendingEntry();
            ManageOpenPosition();

            if (CurrentBar < BarsRequiredToTrade) return;
            if (ForceFlatDue()) return;
            if (!InTradeWindow()) return;
            if (!CanTrade()) return;
            if (Position.MarketPosition != MarketPosition.Flat) return;
            if (_pendingEntrySignal != null) return;

            DetectSweeps();
            ConfirmSweeps();
        }

        private void UpdateSessionState()
        {
            DateTime currentDate = Time[0].Date;
            if (_sessionDate == currentDate)
            {
                _sessionHigh = Math.Max(_sessionHigh, High[0]);
                _sessionLow = Math.Min(_sessionLow, Low[0]);
                return;
            }

            if (_sessionDate != DateTime.MinValue)
            {
                _priorSessionHigh = _sessionHigh;
                _priorSessionLow = _sessionLow;
                _hasPriorSession = _priorSessionHigh > _priorSessionLow;
            }

            _sessionDate = currentDate;
            _sessionHigh = High[0];
            _sessionLow = Low[0];
            _vwapCumPV = 0.0;
            _vwapCumVol = 0.0;
            _orHigh = 0.0;
            _orLow = 0.0;
            _orStarted = false;
            _orBuilt = false;
            ResetSetupState();
            ResetDailyRisk();
        }

        private void ResetDailyRisk()
        {
            DateTime weekStart = WeekStart(Time[0].Date);
            if (_weekStartDate == DateTime.MinValue || _weekStartDate != weekStart)
            {
                _weekStartDate = weekStart;
                _weeklyRealizedPnl = 0.0;
            }

            _sessionRealizedPnl = 0.0;
            _tradesToday = 0;
            _consecutiveLosses = 0;
            _sessionStopped = false;
            _pauseUntil = DateTime.MinValue;
        }

        private void UpdateVwap()
        {
            double volume = Math.Max(1.0, Volume[0]);
            double typical = (High[0] + Low[0] + Close[0]) / 3.0;
            _vwapCumPV += typical * volume;
            _vwapCumVol += volume;
            _vwapSeries[0] = _vwapCumVol > 0.0 ? _vwapCumPV / _vwapCumVol : Close[0];
        }

        private void UpdateOpeningRange()
        {
            DateTime start = HhmmOnDate(Time[0].Date, OpeningRangeStartTime);
            DateTime end = start.AddMinutes(Math.Max(1, OpeningRangeMinutes));

            if (Time[0] >= start && Time[0] < end)
            {
                if (!_orStarted)
                {
                    _orHigh = High[0];
                    _orLow = Low[0];
                    _orStarted = true;
                }
                else
                {
                    _orHigh = Math.Max(_orHigh, High[0]);
                    _orLow = Math.Min(_orLow, Low[0]);
                }
            }

            if (_orStarted && !_orBuilt && Time[0] >= end)
                _orBuilt = _orHigh > _orLow;
        }

        private void DetectSweeps()
        {
            ExpireOldSweeps();
            if (UsePriorSessionAnchor() && _hasPriorSession)
            {
                TryArmLong(_priorSessionLow, "prior_low");
                TryArmShort(_priorSessionHigh, "prior_high");
            }

            if (UseOpeningRangeAnchor() && OpeningRangeUsable())
            {
                TryArmLong(_orLow, "or_low");
                TryArmShort(_orHigh, "or_high");
            }
        }

        private void TryArmLong(double level, string anchorTag)
        {
            if (!EnableLong) return;
            if (level <= 0.0) return;
            if (Low[0] > level - SweepDistanceTicks * TickSize) return;

            if (!_longArmed || CurrentBar == _longSweepBar || level > _longSweepLevel)
            {
                _longArmed = true;
                _longSweepBar = CurrentBar;
                _longSweepLevel = level;
                _longSweepExtreme = Low[0];
                _longAnchorTag = anchorTag;
                PrintSetup("arm_long", anchorTag, level, Low[0]);
            }
            else if (Low[0] < _longSweepExtreme)
            {
                _longSweepExtreme = Low[0];
                _longSweepBar = CurrentBar;
            }
        }

        private void TryArmShort(double level, string anchorTag)
        {
            if (!EnableShort) return;
            if (level <= 0.0) return;
            if (High[0] < level + SweepDistanceTicks * TickSize) return;

            if (!_shortArmed || CurrentBar == _shortSweepBar || level < _shortSweepLevel)
            {
                _shortArmed = true;
                _shortSweepBar = CurrentBar;
                _shortSweepLevel = level;
                _shortSweepExtreme = High[0];
                _shortAnchorTag = anchorTag;
                PrintSetup("arm_short", anchorTag, level, High[0]);
            }
            else if (High[0] > _shortSweepExtreme)
            {
                _shortSweepExtreme = High[0];
                _shortSweepBar = CurrentBar;
            }
        }

        private void ConfirmSweeps()
        {
            if (_longArmed)
            {
                _longSweepExtreme = Math.Min(_longSweepExtreme, Low[0]);
                bool returnedInside = Close[0] >= _longSweepLevel + ReturnInsideTicks * TickSize;
                if (returnedInside && CommonFiltersPass(true) && DirectionFiltersPass(true))
                    PlaceLongSweep();
            }

            if (_shortArmed && _pendingEntrySignal == null && Position.MarketPosition == MarketPosition.Flat)
            {
                _shortSweepExtreme = Math.Max(_shortSweepExtreme, High[0]);
                bool returnedInside = Close[0] <= _shortSweepLevel - ReturnInsideTicks * TickSize;
                if (returnedInside && CommonFiltersPass(false) && DirectionFiltersPass(false))
                    PlaceShortSweep();
            }
        }

        private bool CommonFiltersPass(bool isLong)
        {
            if (MinAdx > 0.0 && _adx[0] < MinAdx) { LogSkip("adx_low"); return false; }
            if (VolumeFactor() < MinVolumeFactor) { LogSkip("volume_low"); return false; }
            if (!BarQualityPasses(isLong)) { LogSkip("bar_quality"); return false; }
            if (UseTrendFilter)
            {
                if (isLong && _emaFast[0] < _emaSlow[0]) { LogSkip("trend_short"); return false; }
                if (!isLong && _emaFast[0] > _emaSlow[0]) { LogSkip("trend_long"); return false; }
            }
            return true;
        }

        private bool DirectionFiltersPass(bool isLong)
        {
            double vwap = _vwapSeries[0];
            if (UseVwapSideFilter)
            {
                double distanceTicks = isLong ? (vwap - Close[0]) / TickSize : (Close[0] - vwap) / TickSize;
                if (distanceTicks < MinDistanceToVwapTicks) { LogSkip("vwap_distance"); return false; }
            }

            if (isLong && Close[0] < Open[0]) { LogSkip("long_close_down"); return false; }
            if (!isLong && Close[0] > Open[0]) { LogSkip("short_close_up"); return false; }
            return true;
        }

        private void PlaceLongSweep()
        {
            double trigger = High[0] + EntryOffsetTicks * TickSize;
            double geometryStop = _longSweepExtreme - StopBeyondSweepTicks * TickSize;
            int stopTicks = ComputeStopTicks(trigger, geometryStop, true);
            if (stopTicks < MinStopTicks) { LogSkip("stop_too_small"); return; }

            double target = ComputeTarget(trigger, stopTicks, true);
            if (target <= trigger + MinTargetTicks * TickSize) { LogSkip("target_too_close"); return; }

            int qty = ComputeQuantity(stopTicks);
            if (qty < 1) { LogSkip("qty_lt_1"); return; }

            double stop = trigger - stopTicks * TickSize;
            string signal = TelemetrySignal("Long");
            SetStopLoss(signal, CalculationMode.Price, stop, false);
            SetProfitTarget(signal, CalculationMode.Price, target);
            EnterLongStopMarket(0, false, qty, trigger, signal);
            SetPendingState(signal, "sweep_" + _longAnchorTag, qty, stopTicks);
            PrintEntry("Long", trigger, stop, target, qty, stopTicks, _longAnchorTag);
            ResetSetupState();
        }

        private void PlaceShortSweep()
        {
            double trigger = Low[0] - EntryOffsetTicks * TickSize;
            double geometryStop = _shortSweepExtreme + StopBeyondSweepTicks * TickSize;
            int stopTicks = ComputeStopTicks(trigger, geometryStop, false);
            if (stopTicks < MinStopTicks) { LogSkip("stop_too_small"); return; }

            double target = ComputeTarget(trigger, stopTicks, false);
            if (target >= trigger - MinTargetTicks * TickSize) { LogSkip("target_too_close"); return; }

            int qty = ComputeQuantity(stopTicks);
            if (qty < 1) { LogSkip("qty_lt_1"); return; }

            double stop = trigger + stopTicks * TickSize;
            string signal = TelemetrySignal("Short");
            SetStopLoss(signal, CalculationMode.Price, stop, false);
            SetProfitTarget(signal, CalculationMode.Price, target);
            EnterShortStopMarket(0, false, qty, trigger, signal);
            SetPendingState(signal, "sweep_" + _shortAnchorTag, qty, stopTicks);
            PrintEntry("Short", trigger, stop, target, qty, stopTicks, _shortAnchorTag);
            ResetSetupState();
        }

        private int ComputeStopTicks(double trigger, double geometryStop, bool isLong)
        {
            double geometryTicks = isLong
                ? (trigger - geometryStop) / TickSize
                : (geometryStop - trigger) / TickSize;
            int rawTicks = (int)Math.Ceiling(Math.Max(1.0, geometryTicks));
            if (rawTicks > MaxStopTicks && !ClampStopToMaxTicks) return 0;

            int atrTicks = (int)Math.Round((_atr[0] / TickSize) * AtrStopMult);
            int stopTicks = Math.Max(rawTicks, atrTicks);
            stopTicks = Math.Max(stopTicks, MinStopTicks);
            stopTicks = Math.Min(stopTicks, MaxStopTicks);
            return stopTicks;
        }

        private double ComputeTarget(double trigger, int stopTicks, bool isLong)
        {
            double fixedTarget = isLong
                ? trigger + stopTicks * RewardRiskRatio * TickSize
                : trigger - stopTicks * RewardRiskRatio * TickSize;
            if (TargetMode == GoldSweepTargetMode.FixedRR)
                return fixedTarget;

            double vwapTarget = isLong
                ? _vwapSeries[0] - VwapTargetOffsetTicks * TickSize
                : _vwapSeries[0] + VwapTargetOffsetTicks * TickSize;

            bool vwapUsable = isLong
                ? vwapTarget > trigger + MinTargetTicks * TickSize
                : vwapTarget < trigger - MinTargetTicks * TickSize;

            if (TargetMode == GoldSweepTargetMode.VwapOnly)
                return vwapUsable ? vwapTarget : trigger;

            return vwapUsable ? vwapTarget : fixedTarget;
        }

        private int ComputeQuantity(int stopTicks)
        {
            if (_permanentlyStopped) return 0;
            double tickValue = TickValue();
            if (tickValue <= 0.0) return 0;

            double equity = CurrentEquity();
            double riskBudget = equity * RiskPerTradePct / 100.0;
            double contractRisk = stopTicks * tickValue + RoundTurnCommission + SlippageTicks * tickValue;
            if (contractRisk <= 0.0) return 0;

            int byRisk = (int)Math.Floor(riskBudget / contractRisk);
            int byMargin = ActiveMarginPerContract > 0.0
                ? (int)Math.Floor(equity / ActiveMarginPerContract)
                : 0;

            int qty = byRisk;
            if (byMargin > 0) qty = Math.Min(qty, byMargin);
            if (MaxContractsByCapital > 0) qty = Math.Min(qty, MaxContractsByCapital);
            if (UserMaxContracts > 0) qty = Math.Min(qty, UserMaxContracts);
            if (MaxOpenPositions > 0) qty = Math.Min(qty, MaxOpenPositions);
            return qty < 1 ? 0 : qty;
        }

        private void ManagePendingEntry()
        {
            if (_pendingEntrySignal == null) return;
            if (CurrentBar - _pendingEntryBar <= EntryTimeoutBars) return;
            CancelPendingEntry("timeout");
        }

        private void ManageOpenPosition()
        {
            if (Position.MarketPosition == MarketPosition.Flat) return;

            if (ForceFlatDue())
            {
                if (Position.MarketPosition == MarketPosition.Long) ExitLong("ForceFlat", ActiveEntrySignalForPosition());
                else if (Position.MarketPosition == MarketPosition.Short) ExitShort("ForceFlat", ActiveEntrySignalForPosition());
                return;
            }

            if (TimeStopBars <= 0 || _lastEntryBar < 0 || _lastStopTicks <= 0) return;
            if (CurrentBar - _lastEntryBar < TimeStopBars) return;

            double progressTicks = Position.MarketPosition == MarketPosition.Long
                ? (Close[0] - _lastEntryPrice) / TickSize
                : (_lastEntryPrice - Close[0]) / TickSize;
            double progressR = progressTicks / _lastStopTicks;
            if (progressR < MinProgressR)
            {
                if (Position.MarketPosition == MarketPosition.Long) ExitLong("TimeStop", ActiveEntrySignalForPosition());
                else if (Position.MarketPosition == MarketPosition.Short) ExitShort("TimeStop", ActiveEntrySignalForPosition());
            }
        }

        private void UpdateRiskStops()
        {
            if (_permanentlyStopped || _sessionStopped) return;

            if (DailyLossLimit > 0.0 && _sessionRealizedPnl <= -DailyLossLimit)
            {
                _sessionStopped = true;
                Print("[RISK:stop] daily_loss=" + _sessionRealizedPnl.ToString("F2"));
                return;
            }

            if (WeeklyLossLimit > 0.0 && _weeklyRealizedPnl <= -WeeklyLossLimit)
            {
                _sessionStopped = true;
                Print("[RISK:stop] weekly_loss=" + _weeklyRealizedPnl.ToString("F2"));
                return;
            }

            if (MaxConsecutiveLosses > 0 && _consecutiveLosses >= MaxConsecutiveLosses)
            {
                _sessionStopped = true;
                Print("[RISK:stop] consecutive_losses=" + _consecutiveLosses);
                return;
            }

            if (HardMaxTradesPerDay > 0 && _tradesToday >= HardMaxTradesPerDay)
            {
                _sessionStopped = true;
                Print("[RISK:stop] hard_trades=" + _tradesToday);
                return;
            }

            if (MaxTradesPerDay > 0 && _tradesToday >= MaxTradesPerDay)
            {
                _sessionStopped = true;
                Print("[RISK:stop] trades=" + _tradesToday);
            }
        }

        private bool CanTrade()
        {
            if (_permanentlyStopped || _sessionStopped) return false;
            if (_pauseUntil != DateTime.MinValue && Time[0] < _pauseUntil) return false;
            return true;
        }

        private void SetPendingState(string signal, string tag, int qty, int stopTicks)
        {
            _pendingEntrySignal = signal;
            _pendingSetupTag = tag;
            _pendingEntryBar = CurrentBar;
            _pendingEntryQty = qty;
            _pendingStopTicks = stopTicks;
            _pendingEntryOrder = null;
            _pendingCancelRequested = false;
        }

        private void CancelPendingEntry(string reason)
        {
            if (_pendingEntrySignal == null) return;
            if (_pendingCancelRequested) return;

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
                    Print("[WARN] cancel failed " + ex.Message);
                }
            }

            Print("[EXIT:cancel_" + reason + "] pending=" + _pendingEntrySignal + " tag=" + _pendingSetupTag);
            ClearPendingEntryState();
        }

        private void ClearPendingEntryState()
        {
            _pendingEntrySignal = null;
            _pendingSetupTag = "";
            _pendingEntryBar = -1;
            _pendingEntryQty = 0;
            _pendingStopTicks = 0;
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
            if (!string.IsNullOrEmpty(_activeEntrySignal)) return _activeEntrySignal;
            if (Position.MarketPosition == MarketPosition.Long) return TelemetrySignal("Long");
            if (Position.MarketPosition == MarketPosition.Short) return TelemetrySignal("Short");
            return "";
        }

        private void ResetSetupState()
        {
            _longArmed = false;
            _shortArmed = false;
            _longSweepBar = -1;
            _shortSweepBar = -1;
            _longSweepLevel = 0.0;
            _shortSweepLevel = 0.0;
            _longSweepExtreme = 0.0;
            _shortSweepExtreme = 0.0;
            _longAnchorTag = "";
            _shortAnchorTag = "";
        }

        private void ExpireOldSweeps()
        {
            if (_longArmed && CurrentBar - _longSweepBar > SweepMaxBarsToReturn)
                _longArmed = false;
            if (_shortArmed && CurrentBar - _shortSweepBar > SweepMaxBarsToReturn)
                _shortArmed = false;
        }

        private bool OpeningRangeUsable()
        {
            if (!_orBuilt) return false;
            int orTicks = (int)Math.Round((_orHigh - _orLow) / TickSize);
            return orTicks >= MinOpeningRangeTicks && orTicks <= MaxOpeningRangeTicks;
        }

        private bool UsePriorSessionAnchor()
        {
            return AnchorMode == GoldSweepAnchorMode.PriorSession || AnchorMode == GoldSweepAnchorMode.Both;
        }

        private bool UseOpeningRangeAnchor()
        {
            return AnchorMode == GoldSweepAnchorMode.OpeningRange || AnchorMode == GoldSweepAnchorMode.Both;
        }

        private bool BarQualityPasses(bool isLong)
        {
            double range = High[0] - Low[0];
            if (range <= TickSize) return false;
            double body = Math.Abs(Close[0] - Open[0]);
            if (body / range < MinBodyRangePct) return false;

            double closeLocation = (Close[0] - Low[0]) / range;
            if (isLong) return closeLocation >= MinCloseLocationPct;
            return (1.0 - closeLocation) >= MinCloseLocationPct;
        }

        private double VolumeFactor()
        {
            double baseVolume = _volSma[0];
            if (baseVolume <= 0.0) return 0.0;
            return Volume[0] / baseVolume;
        }

        private bool InTradeWindow()
        {
            int now = ToHHMM(Time[0]);
            return InWindow(now, TradeStartTime, TradeEndTime);
        }

        private bool ForceFlatDue()
        {
            return ToHHMM(Time[0]) >= ForceFlatTime;
        }

        private bool InWindow(int now, int start, int end)
        {
            if (start <= end) return now >= start && now <= end;
            return now >= start || now <= end;
        }

        private int ToHHMM(DateTime value)
        {
            return value.Hour * 100 + value.Minute;
        }

        private DateTime HhmmOnDate(DateTime date, int hhmm)
        {
            int hour = Math.Max(0, Math.Min(23, hhmm / 100));
            int minute = Math.Max(0, Math.Min(59, hhmm % 100));
            return date.Date.AddHours(hour).AddMinutes(minute);
        }

        private double CurrentEquity()
        {
            double unrealized = 0.0;
            if (Position != null && Position.MarketPosition != MarketPosition.Flat && Position.Quantity > 0)
                unrealized = Position.GetUnrealizedProfitLoss(PerformanceUnit.Currency, Close[0]);
            return StartingCapital + _cumulativeRealizedPnl + unrealized;
        }

        private double TickValue()
        {
            if (Instrument == null || Instrument.MasterInstrument == null) return 0.0;
            return Instrument.MasterInstrument.PointValue * TickSize;
        }

        private static DateTime WeekStart(DateTime date)
        {
            int diff = ((int)date.DayOfWeek + 6) % 7;
            return date.Date.AddDays(-diff);
        }

        private void LogSkip(string reason)
        {
            if (_lastSkipBar == CurrentBar && _lastSkipReason == reason) return;
            _lastSkipBar = CurrentBar;
            _lastSkipReason = reason;
        }

        private void PrintSetup(string action, string anchor, double level, double extreme)
        {
            Print("[SETUP:" + action + "] anchor=" + anchor
                + " level=" + level.ToString("F2")
                + " extreme=" + extreme.ToString("F2")
                + " time=" + Time[0].ToString("yyyy-MM-dd HH:mm"));
        }

        private void PrintEntry(string side, double trigger, double stop, double target, int qty, int stopTicks, string anchor)
        {
            Print("[ENTRY] side=" + side
                + " anchor=" + anchor
                + " trigger=" + trigger.ToString("F2")
                + " stop=" + stop.ToString("F2")
                + " target=" + target.ToString("F2")
                + " qty=" + qty
                + " stopTicks=" + stopTicks);
        }

        protected override void OnOrderUpdate(Order order, double limitPrice, double stopPrice,
            int quantity, int filled, double averageFillPrice, OrderState orderState,
            DateTime time, ErrorCode error, string nativeError)
        {
            bool isEntry = order != null && IsEntrySignalName(order.Name);
            if (_pendingEntrySignal != null && isEntry)
                _pendingEntryOrder = order;

            if (_pendingEntrySignal != null
                && isEntry
                && (orderState == OrderState.Filled || orderState == OrderState.PartFilled))
            {
                _activeEntrySignal = order.Name;
                _lastEntryPrice = averageFillPrice;
                _lastEntryBar = CurrentBar;
                _lastStopTicks = _pendingStopTicks;
                ClearPendingEntryState();
            }
            else if (_pendingEntrySignal != null
                && isEntry
                && (orderState == OrderState.Cancelled || orderState == OrderState.Rejected))
            {
                ClearPendingEntryState();
            }
        }

        protected override void OnPositionUpdate(Position position, double averagePrice,
            int quantity, MarketPosition marketPosition)
        {
            if (marketPosition != MarketPosition.Flat) return;
            if (SystemPerformance == null) return;

            int total = SystemPerformance.AllTrades.Count;
            if (total <= _lastProcessedTradeCount) return;

            for (int index = _lastProcessedTradeCount; index < total; index++)
            {
                Trade trade = SystemPerformance.AllTrades[index];
                double qty = Math.Max(1, trade.Quantity);
                double pnl = trade.ProfitCurrency - RoundTurnCommission * qty;
                _cumulativeRealizedPnl += pnl;
                _sessionRealizedPnl += pnl;
                _weeklyRealizedPnl += pnl;
                _tradesToday += 1;

                if (pnl < 0.0) _consecutiveLosses += 1;
                else _consecutiveLosses = 0;

                if (pnl < 0.0
                    && PauseAfterConsecutiveLosses > 0
                    && _consecutiveLosses >= PauseAfterConsecutiveLosses)
                {
                    _pauseUntil = Time[0].AddMinutes(Math.Max(1, PauseMinutesAfterLosses));
                }

                Print("[EXIT] pnl=" + pnl.ToString("F2")
                    + " dayPnL=" + _sessionRealizedPnl.ToString("F2")
                    + " trades=" + _tradesToday
                    + " consec=" + _consecutiveLosses);
            }

            _lastProcessedTradeCount = total;
            _lastEntryPrice = 0.0;
            _lastEntryBar = -1;
            _lastStopTicks = 0;
            _activeEntrySignal = null;
        }

        #region Properties
        [NinjaScriptProperty]
        [Display(Name = "InstrumentName", GroupName = "01-Instrument", Order = 0)]
        public string InstrumentName { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "ContractName", GroupName = "01-Instrument", Order = 1)]
        public string ContractName { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "SessionTemplateName", GroupName = "01-Instrument", Order = 2)]
        public string SessionTemplateName { get; set; }

        [NinjaScriptProperty, Range(1, 300)]
        [Display(Name = "BaseTimeframeSeconds", GroupName = "01-Instrument", Order = 3)]
        public int BaseTimeframeSeconds { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "StartingCapital", GroupName = "02-Risk Profile", Order = 0)]
        public double StartingCapital { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "IntradayOnly", GroupName = "02-Risk Profile", Order = 1)]
        public bool IntradayOnly { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "ActiveMarginPerContract", GroupName = "02-Risk Profile", Order = 2)]
        public double ActiveMarginPerContract { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "MaxContractsByCapital", GroupName = "02-Risk Profile", Order = 3)]
        public int MaxContractsByCapital { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "InstrumentStatus", GroupName = "02-Risk Profile", Order = 4)]
        public string InstrumentStatus { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "MarginSourceBroker", GroupName = "02-Risk Profile", Order = 5)]
        public string MarginSourceBroker { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "EnableLong", GroupName = "03-Direction", Order = 0)]
        public bool EnableLong { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "EnableShort", GroupName = "03-Direction", Order = 1)]
        public bool EnableShort { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "AnchorMode", GroupName = "03-Direction", Order = 2)]
        public GoldSweepAnchorMode AnchorMode { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "TargetMode", GroupName = "03-Direction", Order = 3)]
        public GoldSweepTargetMode TargetMode { get; set; }

        [NinjaScriptProperty, Range(0, 2359)]
        [Display(Name = "TradeStartTime", GroupName = "04-Time", Order = 0)]
        public int TradeStartTime { get; set; }

        [NinjaScriptProperty, Range(0, 2359)]
        [Display(Name = "TradeEndTime", GroupName = "04-Time", Order = 1)]
        public int TradeEndTime { get; set; }

        [NinjaScriptProperty, Range(0, 2359)]
        [Display(Name = "ForceFlatTime", GroupName = "04-Time", Order = 2)]
        public int ForceFlatTime { get; set; }

        [NinjaScriptProperty, Range(0, 2359)]
        [Display(Name = "OpeningRangeStartTime", GroupName = "04-Time", Order = 3)]
        public int OpeningRangeStartTime { get; set; }

        [NinjaScriptProperty, Range(1, 120)]
        [Display(Name = "OpeningRangeMinutes", GroupName = "04-Time", Order = 4)]
        public int OpeningRangeMinutes { get; set; }

        [NinjaScriptProperty, Range(2, 200)]
        [Display(Name = "EmaFastPeriod", GroupName = "05-Filters", Order = 0)]
        public int EmaFastPeriod { get; set; }

        [NinjaScriptProperty, Range(2, 400)]
        [Display(Name = "EmaSlowPeriod", GroupName = "05-Filters", Order = 1)]
        public int EmaSlowPeriod { get; set; }

        [NinjaScriptProperty, Range(2, 200)]
        [Display(Name = "AtrPeriod", GroupName = "05-Filters", Order = 2)]
        public int AtrPeriod { get; set; }

        [NinjaScriptProperty, Range(2, 200)]
        [Display(Name = "AdxPeriod", GroupName = "05-Filters", Order = 3)]
        public int AdxPeriod { get; set; }

        [NinjaScriptProperty, Range(2, 500)]
        [Display(Name = "VolumeSmaPeriod", GroupName = "05-Filters", Order = 4)]
        public int VolumeSmaPeriod { get; set; }

        [NinjaScriptProperty, Range(0.0, 100.0)]
        [Display(Name = "MinAdx", GroupName = "05-Filters", Order = 5)]
        public double MinAdx { get; set; }

        [NinjaScriptProperty, Range(0.0, 10.0)]
        [Display(Name = "MinVolumeFactor", GroupName = "05-Filters", Order = 6)]
        public double MinVolumeFactor { get; set; }

        [NinjaScriptProperty, Range(0.0, 1.0)]
        [Display(Name = "MinBodyRangePct", GroupName = "05-Filters", Order = 7)]
        public double MinBodyRangePct { get; set; }

        [NinjaScriptProperty, Range(0.0, 1.0)]
        [Display(Name = "MinCloseLocationPct", GroupName = "05-Filters", Order = 8)]
        public double MinCloseLocationPct { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "UseTrendFilter", GroupName = "05-Filters", Order = 9)]
        public bool UseTrendFilter { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "UseVwapSideFilter", GroupName = "05-Filters", Order = 10)]
        public bool UseVwapSideFilter { get; set; }

        [NinjaScriptProperty, Range(0, 200)]
        [Display(Name = "MinDistanceToVwapTicks", GroupName = "05-Filters", Order = 11)]
        public int MinDistanceToVwapTicks { get; set; }

        [NinjaScriptProperty, Range(0, 100)]
        [Display(Name = "SweepDistanceTicks", GroupName = "06-Setup", Order = 0)]
        public int SweepDistanceTicks { get; set; }

        [NinjaScriptProperty, Range(0, 100)]
        [Display(Name = "ReturnInsideTicks", GroupName = "06-Setup", Order = 1)]
        public int ReturnInsideTicks { get; set; }

        [NinjaScriptProperty, Range(1, 20)]
        [Display(Name = "SweepMaxBarsToReturn", GroupName = "06-Setup", Order = 2)]
        public int SweepMaxBarsToReturn { get; set; }

        [NinjaScriptProperty, Range(1, 200)]
        [Display(Name = "MinOpeningRangeTicks", GroupName = "06-Setup", Order = 3)]
        public int MinOpeningRangeTicks { get; set; }

        [NinjaScriptProperty, Range(1, 400)]
        [Display(Name = "MaxOpeningRangeTicks", GroupName = "06-Setup", Order = 4)]
        public int MaxOpeningRangeTicks { get; set; }

        [NinjaScriptProperty, Range(0, 100)]
        [Display(Name = "StopBeyondSweepTicks", GroupName = "07-Orders", Order = 0)]
        public int StopBeyondSweepTicks { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "ClampStopToMaxTicks", GroupName = "07-Orders", Order = 1)]
        public bool ClampStopToMaxTicks { get; set; }

        [NinjaScriptProperty, Range(1, 200)]
        [Display(Name = "MinStopTicks", GroupName = "07-Orders", Order = 2)]
        public int MinStopTicks { get; set; }

        [NinjaScriptProperty, Range(1, 300)]
        [Display(Name = "MaxStopTicks", GroupName = "07-Orders", Order = 3)]
        public int MaxStopTicks { get; set; }

        [NinjaScriptProperty, Range(0.0, 10.0)]
        [Display(Name = "AtrStopMult", GroupName = "07-Orders", Order = 4)]
        public double AtrStopMult { get; set; }

        [NinjaScriptProperty, Range(0.1, 10.0)]
        [Display(Name = "RewardRiskRatio", GroupName = "07-Orders", Order = 5)]
        public double RewardRiskRatio { get; set; }

        [NinjaScriptProperty, Range(0, 50)]
        [Display(Name = "EntryOffsetTicks", GroupName = "07-Orders", Order = 6)]
        public int EntryOffsetTicks { get; set; }

        [NinjaScriptProperty, Range(1, 20)]
        [Display(Name = "EntryTimeoutBars", GroupName = "07-Orders", Order = 7)]
        public int EntryTimeoutBars { get; set; }

        [NinjaScriptProperty, Range(1, 200)]
        [Display(Name = "MinTargetTicks", GroupName = "07-Orders", Order = 8)]
        public int MinTargetTicks { get; set; }

        [NinjaScriptProperty, Range(0, 100)]
        [Display(Name = "VwapTargetOffsetTicks", GroupName = "07-Orders", Order = 9)]
        public int VwapTargetOffsetTicks { get; set; }

        [NinjaScriptProperty, Range(0, 100)]
        [Display(Name = "TimeStopBars", GroupName = "07-Orders", Order = 10)]
        public int TimeStopBars { get; set; }

        [NinjaScriptProperty, Range(0.0, 2.0)]
        [Display(Name = "MinProgressR", GroupName = "07-Orders", Order = 11)]
        public double MinProgressR { get; set; }

        [NinjaScriptProperty, Range(0.01, 10.0)]
        [Display(Name = "RiskPerTradePct", GroupName = "08-Risk", Order = 0)]
        public double RiskPerTradePct { get; set; }

        [NinjaScriptProperty, Range(0, 100)]
        [Display(Name = "UserMaxContracts", GroupName = "08-Risk", Order = 1)]
        public int UserMaxContracts { get; set; }

        [NinjaScriptProperty, Range(0, 100)]
        [Display(Name = "MaxOpenPositions", GroupName = "08-Risk", Order = 2)]
        public int MaxOpenPositions { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "DailyLossLimit", GroupName = "08-Risk", Order = 3)]
        public double DailyLossLimit { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "WeeklyLossLimit", GroupName = "08-Risk", Order = 4)]
        public double WeeklyLossLimit { get; set; }

        [NinjaScriptProperty, Range(0, 100)]
        [Display(Name = "MaxTradesPerDay", GroupName = "08-Risk", Order = 5)]
        public int MaxTradesPerDay { get; set; }

        [NinjaScriptProperty, Range(0, 100)]
        [Display(Name = "HardMaxTradesPerDay", GroupName = "08-Risk", Order = 6)]
        public int HardMaxTradesPerDay { get; set; }

        [NinjaScriptProperty, Range(0, 20)]
        [Display(Name = "MaxConsecutiveLosses", GroupName = "08-Risk", Order = 7)]
        public int MaxConsecutiveLosses { get; set; }

        [NinjaScriptProperty, Range(0, 20)]
        [Display(Name = "PauseAfterConsecutiveLosses", GroupName = "08-Risk", Order = 8)]
        public int PauseAfterConsecutiveLosses { get; set; }

        [NinjaScriptProperty, Range(0, 240)]
        [Display(Name = "PauseMinutesAfterLosses", GroupName = "08-Risk", Order = 9)]
        public int PauseMinutesAfterLosses { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "RoundTurnCommission", GroupName = "08-Risk", Order = 10)]
        public double RoundTurnCommission { get; set; }

        [NinjaScriptProperty, Range(0, 100)]
        [Display(Name = "SlippageTicks", GroupName = "08-Risk", Order = 11)]
        public int SlippageTicks { get; set; }
        #endregion
    }
}
