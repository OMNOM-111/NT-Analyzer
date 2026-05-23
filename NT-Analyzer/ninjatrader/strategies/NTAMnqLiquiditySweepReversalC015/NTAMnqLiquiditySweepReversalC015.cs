// =============================================================================
// NTAMnqLiquiditySweepReversalC015
// -----------------------------------------------------------------------------
// Standalone MNQ CELL-015 strategy.
//
// Hypothesis:
//   1m MNQ often over-runs the last few minutes' local liquidity, then quickly
//   rejects the sweep back toward session VWAP. The class also includes a
//   standalone opening-pressure score mode for CELL-015 research: it combines
//   VWAP loss, EMA pressure, failed local highs, and opening-range breakdown
//   evidence without inheriting any carrier strategy.
//
// This class intentionally does not inherit from NTAMicroMnqScalpPilot and does
// not use the CELL-016 opening-drive module stack.
// =============================================================================

#region Using declarations
using System;
using System.ComponentModel.DataAnnotations;
using NinjaTrader.Cbi;
using NinjaTrader.NinjaScript;
using NinjaTrader.NinjaScript.Indicators;
using NinjaTrader.NinjaScript.Strategies;
#endregion

namespace NinjaTrader.NinjaScript.Strategies
{
    public class NTAMnqLiquiditySweepReversalC015 : Strategy
    {
        private EMA _emaFast;
        private EMA _emaSlow;
        private ATR _atr;
        private ADX _adx;
        private SMA _volumeSma;
        private Series<double> _vwapSeries;

        private DateTime _sessionDate = DateTime.MinValue;
        private double _vwapCumPV;
        private double _vwapCumVol;
        private double _orHigh;
        private double _orLow;
        private bool _orStarted;
        private bool _orBuilt;

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

        private string _activeSignal = "";
        private int _lastEntryBar = -1;
        private double _lastEntryPrice;
        private int _lastStopTicks;
        private bool _stopMovedToBreakeven;
        private double _bestFavorableTicks;
        private Order _pendingEntryOrder;
        private string _pendingEntrySignal = "";
        private int _pendingEntryBar = -1;

        protected override void OnStateChange()
        {
            if (State == State.SetDefaults)
            {
                Description = "MNQ CELL-015 standalone opening-pressure stop-entry short scalper.";
                Name = "Scalping Open Pressure Stop MNQ 1m v1 c015";
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
                BarsRequiredToTrade = 50;
                IsInstantiatedOnEachOptimizationIteration = true;

                InstrumentName = "MNQ";
                ContractName = "MNQ 06-26";
                SessionTemplateName = "CME US Index Futures RTH";
                BaseTimeframeSeconds = 60;

                StartingCapital = 2000.0;
                IntradayOnly = true;
                ActiveMarginPerContract = 100.0;
                MaxContractsByCapital = 20;
                InstrumentStatus = "allowed";
                MarginSourceBroker = "NinjaTrader";

                EnableLong = false;
                EnableShort = true;
                SignalMode = "OpenPressureStopShort";

                TradeStartTime = 635;
                TradeEndTime = 830;
                UseSecondTradeWindow = false;
                SecondTradeStartTime = 1030;
                SecondTradeEndTime = 1200;
                ForceFlatTime = 1300;

                EmaFastPeriod = 9;
                EmaSlowPeriod = 34;
                AtrPeriod = 14;
                AdxPeriod = 14;
                VolumeSmaPeriod = 20;
                MinVolumeFactor = 0.0;
                MinAdx = 0.0;
                MaxAdx = 80.0;
                UseEmaStretchFilter = false;
                MinEmaStretchTicks = 0;

                SweepLookbackBars = 3;
                FadeSweeps = true;
                SweepDistanceTicks = 0;
                ReclaimTicks = 2;
                UseVwapDistanceFilter = false;
                MinVwapDistanceTicks = 8;
                MaxVwapDistanceTicks = 120;
                RequireCloseAgainstSweep = true;
                MinBarRangeTicks = 2;
                MinBodyRangePct = 0.0;
                MinCloseLocationPct = 0.20;
                MomentumLookbackBars = 1;
                MomentumBreakTicks = 0;
                RequireMomentumBreak = false;
                OpenPressureMinScore = 1;
                OpeningRangeStartTime = 630;
                OpeningRangeMinutes = 3;
                OpeningRangeBreakBufferTicks = 1;
                MinOpeningRangeTicks = 4;
                MaxOpeningRangeTicks = 160;

                StopBufferTicks = 1;
                MinStopTicks = 4;
                MaxStopTicks = 10;
                AtrStopMult = 0.0;
                RewardRiskRatio = 4.0;
                MinTargetTicks = 6;
                EntryOffsetTicks = 0;
                EntryTimeoutBars = 2;
                MoveToBreakevenAtR = 0.0;
                BreakevenPlusTicks = 1;
                UseTrailingStop = false;
                TrailAfterR = 1.0;
                TrailDistanceTicks = 6;
                UseTimeStop = true;
                TimeStopBars = 3;
                MinProgressR = 0.20;

                RiskPerTradePct = 0.50;
                UserMaxContracts = 1;
                MaxOpenPositions = 1;
                DailyLossLimit = 45.0;
                WeeklyLossLimit = 120.0;
                MaxTradesPerDay = 20;
                HardMaxTradesPerDay = 25;
                MaxConsecutiveLosses = 3;
                PauseAfterConsecutiveLosses = 2;
                PauseMinutesAfterLosses = 20;
                RoundTurnCommission = 1.90;
                SlippageTicks = 1;
            }
            else if (State == State.DataLoaded)
            {
                _emaFast = EMA(EmaFastPeriod);
                _emaSlow = EMA(EmaSlowPeriod);
                _atr = ATR(AtrPeriod);
                _adx = ADX(AdxPeriod);
                _volumeSma = SMA(Volume, VolumeSmaPeriod);
                _vwapSeries = new Series<double>(this);

                _permanentlyStopped = StartingCapital <= 0.0
                    || ActiveMarginPerContract <= 0.0
                    || MaxContractsByCapital < 1
                    || string.Equals(InstrumentStatus, "blocked", StringComparison.OrdinalIgnoreCase)
                    || string.Equals(InstrumentStatus, "unknown", StringComparison.OrdinalIgnoreCase);
            }
        }

        protected override void OnBarUpdate()
        {
            if (BarsInProgress != 0) return;
            if (CurrentBar < 1) return;

            UpdateSessionState();
            UpdateVwap();
            UpdateOpeningRange();
            ManageOpenPosition();
            ManagePendingEntry();

            if (ForceFlatDue())
            {
                ForceFlat("time");
                return;
            }

            if (CurrentBar < BarsRequiredToTrade) return;
            if (!InTradeWindow()) return;
            if (!CanTrade()) return;
            if (Position.MarketPosition != MarketPosition.Flat) return;
            if (_activeSignal != "") return;
            if (_pendingEntrySignal != "") return;
            if (MaxOpenPositions < 1) return;

            if (IsMomentumMode())
                TryEnterMomentum();
            else if (IsOrbFailureMode())
                TryEnterOrbFailure();
            else if (IsOpenPressureMode())
                TryEnterOpenPressure();
            else
                TryEnterLiquiditySweep();
        }

        private void UpdateSessionState()
        {
            DateTime currentDate = Time[0].Date;
            if (_sessionDate == currentDate) return;

            _sessionDate = currentDate;
            _vwapCumPV = 0.0;
            _vwapCumVol = 0.0;
            _orHigh = 0.0;
            _orLow = 0.0;
            _orStarted = false;
            _orBuilt = false;
            ResetDailyRisk();
            ClearActiveTradeState();
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

        private void TryEnterLiquiditySweep()
        {
            if (!CommonFiltersPass()) return;

            double priorHigh = HighestHigh(SweepLookbackBars);
            double priorLow = LowestLow(SweepLookbackBars);
            bool canShort = EnableShort
                && (FadeSweeps
                    ? priorHigh > 0.0 && ShortSweepPasses(priorHigh)
                    : priorLow > 0.0 && ShortContinuationPasses(priorLow));
            bool canLong = EnableLong
                && (FadeSweeps
                    ? priorLow > 0.0 && LongSweepPasses(priorLow)
                    : priorHigh > 0.0 && LongContinuationPasses(priorHigh));

            if (canShort && canLong)
            {
                double shortDistance = FadeSweeps ? Math.Abs(High[0] - priorHigh) : Math.Abs(priorLow - Low[0]);
                double longDistance = FadeSweeps ? Math.Abs(priorLow - Low[0]) : Math.Abs(High[0] - priorHigh);
                if (shortDistance >= longDistance)
                    EnterSweep(false, FadeSweeps ? priorHigh : priorLow);
                else
                    EnterSweep(true, FadeSweeps ? priorLow : priorHigh);
                return;
            }

            if (canShort) EnterSweep(false, FadeSweeps ? priorHigh : priorLow);
            else if (canLong) EnterSweep(true, FadeSweeps ? priorLow : priorHigh);
        }

        private void TryEnterMomentum()
        {
            if (!CommonFiltersPass()) return;

            bool canShort = EnableShort && ShortMomentumPasses();
            bool canLong = EnableLong && LongMomentumPasses();
            if (canShort && canLong)
            {
                double shortBody = Open[0] - Close[0];
                double longBody = Close[0] - Open[0];
                if (shortBody >= longBody)
                    EnterSweep(false, High[0]);
                else
                    EnterSweep(true, Low[0]);
                return;
            }

            if (canShort) EnterSweep(false, High[0]);
            else if (canLong) EnterSweep(true, Low[0]);
        }

        private void TryEnterOrbFailure()
        {
            if (!OpeningRangeUsable()) return;
            if (!CommonFiltersPass()) return;

            bool canShort = EnableShort && ShortOrbFailurePasses();
            bool canLong = EnableLong && LongOrbFailurePasses();
            if (canShort && canLong)
            {
                double shortDistance = High[0] - _orHigh;
                double longDistance = _orLow - Low[0];
                if (shortDistance >= longDistance)
                    EnterSweep(false, _orHigh);
                else
                    EnterSweep(true, _orLow);
                return;
            }

            if (canShort) EnterSweep(false, _orHigh);
            else if (canLong) EnterSweep(true, _orLow);
        }

        private void TryEnterOpenPressure()
        {
            if (!EnableShort) return;
            if (!CommonFiltersPass()) return;

            double range = Math.Max(TickSize, High[0] - Low[0]);
            bool weakBody = Close[0] < Open[0];
            bool weakClose = (High[0] - Close[0]) / range >= MinCloseLocationPct;
            if (RequireCloseAgainstSweep && !weakBody) return;
            if (!weakClose) return;

            int score = 0;
            double reclaimBand = Math.Max(0, ReclaimTicks) * TickSize;

            bool vwapLoss = Close[0] < _vwapSeries[0]
                && (Close[1] > _vwapSeries[1] || High[0] >= _vwapSeries[0] - reclaimBand);
            if (vwapLoss) score += 1;

            bool emaPressure = Close[0] < _emaFast[0]
                && (Close[0] < Close[1] || _emaFast[0] <= _emaFast[1] || _emaFast[0] <= _emaSlow[0]);
            if (emaPressure) score += 1;

            double priorHigh = HighestHigh(SweepLookbackBars);
            bool failedHigh = High[0] >= priorHigh + SweepDistanceTicks * TickSize
                && Close[0] < priorHigh;
            bool failedPreviousHigh = High[0] > High[1] && Close[0] < High[1];
            if (failedHigh || failedPreviousHigh) score += 1;

            double priorLow = LowestLow(MomentumLookbackBars);
            bool downsidePush = Close[0] <= priorLow - MomentumBreakTicks * TickSize
                || Low[0] < Low[1] - TickSize;
            if (downsidePush) score += 1;

            bool orBreakdown = OpeningRangeUsable()
                && Close[0] < _orLow - OpeningRangeBreakBufferTicks * TickSize;
            if (orBreakdown) score += 1;

            if (score < Math.Max(1, OpenPressureMinScore)) return;
            if (IsOpenPressureStopMode())
                PlaceShortStopEntry(High[0]);
            else
                EnterSweep(false, High[0]);
        }

        private bool CommonFiltersPass()
        {
            if (MinAdx > 0.0 && _adx[0] < MinAdx) return false;
            if (MaxAdx > 0.0 && _adx[0] > MaxAdx) return false;
            if (VolumeFactor() < MinVolumeFactor) return false;

            double rangeTicks = (High[0] - Low[0]) / TickSize;
            if (rangeTicks < MinBarRangeTicks) return false;
            if (rangeTicks <= 0.0) return false;

            double body = Math.Abs(Close[0] - Open[0]);
            if (body / (High[0] - Low[0]) < MinBodyRangePct) return false;
            return true;
        }

        private bool ShortSweepPasses(double priorHigh)
        {
            if (High[0] < priorHigh + SweepDistanceTicks * TickSize) return false;
            if (Close[0] > priorHigh - ReclaimTicks * TickSize) return false;
            if (RequireCloseAgainstSweep && Close[0] > Open[0]) return false;

            double closeLocation = (High[0] - Close[0]) / Math.Max(TickSize, High[0] - Low[0]);
            if (closeLocation < MinCloseLocationPct) return false;

            if (UseVwapDistanceFilter)
            {
                double distanceTicks = (Close[0] - _vwapSeries[0]) / TickSize;
                if (distanceTicks < MinVwapDistanceTicks) return false;
                if (MaxVwapDistanceTicks > 0 && distanceTicks > MaxVwapDistanceTicks) return false;
            }

            if (UseEmaStretchFilter)
            {
                double stretchTicks = (Close[0] - _emaFast[0]) / TickSize;
                if (stretchTicks < MinEmaStretchTicks) return false;
            }

            return true;
        }

        private bool LongSweepPasses(double priorLow)
        {
            if (Low[0] > priorLow - SweepDistanceTicks * TickSize) return false;
            if (Close[0] < priorLow + ReclaimTicks * TickSize) return false;
            if (RequireCloseAgainstSweep && Close[0] < Open[0]) return false;

            double closeLocation = (Close[0] - Low[0]) / Math.Max(TickSize, High[0] - Low[0]);
            if (closeLocation < MinCloseLocationPct) return false;

            if (UseVwapDistanceFilter)
            {
                double distanceTicks = (_vwapSeries[0] - Close[0]) / TickSize;
                if (distanceTicks < MinVwapDistanceTicks) return false;
                if (MaxVwapDistanceTicks > 0 && distanceTicks > MaxVwapDistanceTicks) return false;
            }

            if (UseEmaStretchFilter)
            {
                double stretchTicks = (_emaFast[0] - Close[0]) / TickSize;
                if (stretchTicks < MinEmaStretchTicks) return false;
            }

            return true;
        }

        private bool ShortContinuationPasses(double priorLow)
        {
            if (Low[0] > priorLow - SweepDistanceTicks * TickSize) return false;
            if (Close[0] > priorLow - ReclaimTicks * TickSize) return false;
            if (RequireCloseAgainstSweep && Close[0] > Open[0]) return false;

            double closeLocation = (High[0] - Close[0]) / Math.Max(TickSize, High[0] - Low[0]);
            if (closeLocation < MinCloseLocationPct) return false;

            if (UseVwapDistanceFilter)
            {
                double distanceTicks = (_vwapSeries[0] - Close[0]) / TickSize;
                if (distanceTicks < MinVwapDistanceTicks) return false;
                if (MaxVwapDistanceTicks > 0 && distanceTicks > MaxVwapDistanceTicks) return false;
            }

            if (UseEmaStretchFilter)
            {
                double stretchTicks = (_emaFast[0] - Close[0]) / TickSize;
                if (stretchTicks < MinEmaStretchTicks) return false;
            }

            return true;
        }

        private bool LongContinuationPasses(double priorHigh)
        {
            if (High[0] < priorHigh + SweepDistanceTicks * TickSize) return false;
            if (Close[0] < priorHigh + ReclaimTicks * TickSize) return false;
            if (RequireCloseAgainstSweep && Close[0] < Open[0]) return false;

            double closeLocation = (Close[0] - Low[0]) / Math.Max(TickSize, High[0] - Low[0]);
            if (closeLocation < MinCloseLocationPct) return false;

            if (UseVwapDistanceFilter)
            {
                double distanceTicks = (Close[0] - _vwapSeries[0]) / TickSize;
                if (distanceTicks < MinVwapDistanceTicks) return false;
                if (MaxVwapDistanceTicks > 0 && distanceTicks > MaxVwapDistanceTicks) return false;
            }

            if (UseEmaStretchFilter)
            {
                double stretchTicks = (Close[0] - _emaFast[0]) / TickSize;
                if (stretchTicks < MinEmaStretchTicks) return false;
            }

            return true;
        }

        private bool ShortMomentumPasses()
        {
            if (RequireCloseAgainstSweep && Close[0] > Open[0]) return false;
            if (RequireMomentumBreak)
            {
                double priorLow = LowestLow(MomentumLookbackBars);
                if (Close[0] > priorLow - MomentumBreakTicks * TickSize) return false;
            }

            double closeLocation = (High[0] - Close[0]) / Math.Max(TickSize, High[0] - Low[0]);
            if (closeLocation < MinCloseLocationPct) return false;

            if (UseVwapDistanceFilter)
            {
                double distanceTicks = (_vwapSeries[0] - Close[0]) / TickSize;
                if (distanceTicks < MinVwapDistanceTicks) return false;
                if (MaxVwapDistanceTicks > 0 && distanceTicks > MaxVwapDistanceTicks) return false;
            }

            if (UseEmaStretchFilter)
            {
                double stretchTicks = (_emaFast[0] - Close[0]) / TickSize;
                if (stretchTicks < MinEmaStretchTicks) return false;
            }

            return true;
        }

        private bool LongMomentumPasses()
        {
            if (RequireCloseAgainstSweep && Close[0] < Open[0]) return false;
            if (RequireMomentumBreak)
            {
                double priorHigh = HighestHigh(MomentumLookbackBars);
                if (Close[0] < priorHigh + MomentumBreakTicks * TickSize) return false;
            }

            double closeLocation = (Close[0] - Low[0]) / Math.Max(TickSize, High[0] - Low[0]);
            if (closeLocation < MinCloseLocationPct) return false;

            if (UseVwapDistanceFilter)
            {
                double distanceTicks = (Close[0] - _vwapSeries[0]) / TickSize;
                if (distanceTicks < MinVwapDistanceTicks) return false;
                if (MaxVwapDistanceTicks > 0 && distanceTicks > MaxVwapDistanceTicks) return false;
            }

            if (UseEmaStretchFilter)
            {
                double stretchTicks = (Close[0] - _emaFast[0]) / TickSize;
                if (stretchTicks < MinEmaStretchTicks) return false;
            }

            return true;
        }

        private bool ShortOrbFailurePasses()
        {
            if (High[0] < _orHigh + OpeningRangeBreakBufferTicks * TickSize) return false;
            if (Close[0] > _orHigh - ReclaimTicks * TickSize) return false;
            if (RequireCloseAgainstSweep && Close[0] > Open[0]) return false;

            double closeLocation = (High[0] - Close[0]) / Math.Max(TickSize, High[0] - Low[0]);
            if (closeLocation < MinCloseLocationPct) return false;

            if (UseVwapDistanceFilter)
            {
                double distanceTicks = (Close[0] - _vwapSeries[0]) / TickSize;
                if (distanceTicks < MinVwapDistanceTicks) return false;
                if (MaxVwapDistanceTicks > 0 && distanceTicks > MaxVwapDistanceTicks) return false;
            }

            if (UseEmaStretchFilter)
            {
                double stretchTicks = (Close[0] - _emaFast[0]) / TickSize;
                if (stretchTicks < MinEmaStretchTicks) return false;
            }

            return true;
        }

        private bool LongOrbFailurePasses()
        {
            if (Low[0] > _orLow - OpeningRangeBreakBufferTicks * TickSize) return false;
            if (Close[0] < _orLow + ReclaimTicks * TickSize) return false;
            if (RequireCloseAgainstSweep && Close[0] < Open[0]) return false;

            double closeLocation = (Close[0] - Low[0]) / Math.Max(TickSize, High[0] - Low[0]);
            if (closeLocation < MinCloseLocationPct) return false;

            if (UseVwapDistanceFilter)
            {
                double distanceTicks = (_vwapSeries[0] - Close[0]) / TickSize;
                if (distanceTicks < MinVwapDistanceTicks) return false;
                if (MaxVwapDistanceTicks > 0 && distanceTicks > MaxVwapDistanceTicks) return false;
            }

            if (UseEmaStretchFilter)
            {
                double stretchTicks = (_emaFast[0] - Close[0]) / TickSize;
                if (stretchTicks < MinEmaStretchTicks) return false;
            }

            return true;
        }

        private void EnterSweep(bool isLong, double sweptLevel)
        {
            int stopTicks = ComputeStopTicks(isLong, sweptLevel);
            int targetTicks = (int)Math.Round(stopTicks * RewardRiskRatio);
            if (stopTicks < MinStopTicks || targetTicks < MinTargetTicks) return;

            int qty = ComputeQuantity(stopTicks);
            if (qty < 1) return;

            string signal = TelemetrySignal(isLong ? "Long" : "Short");
            SetStopLoss(signal, CalculationMode.Ticks, stopTicks, false);
            SetProfitTarget(signal, CalculationMode.Ticks, targetTicks);
            _activeSignal = signal;
            _lastStopTicks = stopTicks;
            _lastEntryBar = CurrentBar;
            _lastEntryPrice = Close[0];
            _stopMovedToBreakeven = false;
            _bestFavorableTicks = 0.0;

            if (isLong) EnterLong(qty, signal);
            else EnterShort(qty, signal);
        }

        private void PlaceShortStopEntry(double referenceHigh)
        {
            double trigger = Low[0] - Math.Max(0, EntryOffsetTicks) * TickSize;
            if (trigger >= Close[0])
                trigger = Close[0] - TickSize;
            trigger = RoundToTick(trigger);

            int stopTicks = ComputeStopTicksForEntry(false, referenceHigh, trigger);
            int targetTicks = (int)Math.Round(stopTicks * RewardRiskRatio);
            if (stopTicks < MinStopTicks || targetTicks < MinTargetTicks) return;

            int qty = ComputeQuantity(stopTicks);
            if (qty < 1) return;

            double stopPrice = RoundToTick(trigger + stopTicks * TickSize);
            double targetPrice = RoundToTick(trigger - targetTicks * TickSize);

            double bid = GetCurrentBid();
            double ask = GetCurrentAsk();
            Print(string.Format(
                "[ENTRY:short_stop] bar={0} trigger={1:F2} low={2:F2} close={3:F2} bid={4:F2} ask={5:F2}",
                CurrentBar, trigger, Low[0], Close[0], bid, ask));

            if (bid > 0.0 && trigger >= bid - 2.0 * TickSize)
            {
                Print(string.Format(
                    "[SKIP:short_stop] trigger={0:F2} bid={1:F2} (market at/below stop)",
                    trigger, bid));
                return;
            }

            string signal = TelemetrySignal("Short");
            SetStopLoss(signal, CalculationMode.Price, stopPrice, false);
            SetProfitTarget(signal, CalculationMode.Price, targetPrice);

            _activeSignal = signal;
            _lastStopTicks = stopTicks;
            _lastEntryBar = CurrentBar;
            _lastEntryPrice = trigger;
            _stopMovedToBreakeven = false;
            _bestFavorableTicks = 0.0;
            _pendingEntrySignal = signal;
            _pendingEntryBar = CurrentBar;
            _pendingEntryOrder = null;

            EnterShortStopMarket(0, false, qty, trigger, signal);
        }

        private double RoundToTick(double price)
        {
            if (Instrument != null && Instrument.MasterInstrument != null)
                return Instrument.MasterInstrument.RoundToTickSize(price);
            return price;
        }

        private int ComputeStopTicks(bool isLong, double sweptLevel)
        {
            double geometryPrice = isLong
                ? Math.Min(Low[0], sweptLevel) - StopBufferTicks * TickSize
                : Math.Max(High[0], sweptLevel) + StopBufferTicks * TickSize;
            double geometryTicks = isLong
                ? (Close[0] - geometryPrice) / TickSize
                : (geometryPrice - Close[0]) / TickSize;
            int rawTicks = (int)Math.Ceiling(Math.Max(1.0, geometryTicks));
            int atrTicks = (int)Math.Round((_atr[0] / TickSize) * AtrStopMult);
            int stopTicks = Math.Max(rawTicks, atrTicks);
            stopTicks = Math.Max(stopTicks, MinStopTicks);
            stopTicks = Math.Min(stopTicks, MaxStopTicks);
            return stopTicks;
        }

        private int ComputeStopTicksForEntry(bool isLong, double referenceLevel, double entryPrice)
        {
            double geometryPrice = isLong
                ? Math.Min(Low[0], referenceLevel) - StopBufferTicks * TickSize
                : Math.Max(High[0], referenceLevel) + StopBufferTicks * TickSize;
            double geometryTicks = isLong
                ? (entryPrice - geometryPrice) / TickSize
                : (geometryPrice - entryPrice) / TickSize;
            int rawTicks = (int)Math.Ceiling(Math.Max(1.0, geometryTicks));
            int atrTicks = (int)Math.Round((_atr[0] / TickSize) * AtrStopMult);
            int stopTicks = Math.Max(rawTicks, atrTicks);
            stopTicks = Math.Max(stopTicks, MinStopTicks);
            stopTicks = Math.Min(stopTicks, MaxStopTicks);
            return stopTicks;
        }

        private void ManageOpenPosition()
        {
            if (Position.MarketPosition == MarketPosition.Flat) return;

            bool isLong = Position.MarketPosition == MarketPosition.Long;
            double entry = Position.AveragePrice;
            if (entry <= 0.0) entry = _lastEntryPrice;
            if (entry <= 0.0 || _lastStopTicks <= 0) return;

            double favorableTicks = isLong
                ? (High[0] - entry) / TickSize
                : (entry - Low[0]) / TickSize;
            _bestFavorableTicks = Math.Max(_bestFavorableTicks, favorableTicks);

            if (!_stopMovedToBreakeven
                && MoveToBreakevenAtR > 0.0
                && _bestFavorableTicks >= _lastStopTicks * MoveToBreakevenAtR)
            {
                double bePrice = isLong
                    ? entry + BreakevenPlusTicks * TickSize
                    : entry - BreakevenPlusTicks * TickSize;
                SetStopLoss(_activeSignal, CalculationMode.Price, bePrice, false);
                _stopMovedToBreakeven = true;
            }

            if (UseTrailingStop
                && TrailAfterR > 0.0
                && _bestFavorableTicks >= _lastStopTicks * TrailAfterR)
            {
                double trailPrice = isLong
                    ? Close[0] - TrailDistanceTicks * TickSize
                    : Close[0] + TrailDistanceTicks * TickSize;
                if (_stopMovedToBreakeven)
                    SetStopLoss(_activeSignal, CalculationMode.Price, trailPrice, false);
            }

            if (UseTimeStop && TimeStopBars > 0 && _lastEntryBar >= 0)
            {
                int barsHeld = CurrentBar - _lastEntryBar;
                if (barsHeld >= TimeStopBars
                    && _bestFavorableTicks < _lastStopTicks * MinProgressR)
                {
                    if (isLong) ExitLong("TimeStop", _activeSignal);
                    else ExitShort("TimeStop", _activeSignal);
                }
            }
        }

        private void ManagePendingEntry()
        {
            if (_pendingEntrySignal == "") return;
            if (Position.MarketPosition != MarketPosition.Flat) return;
            if (_pendingEntryBar < 0) return;
            if (CurrentBar - _pendingEntryBar < Math.Max(1, EntryTimeoutBars)) return;

            if (_pendingEntryOrder != null)
            {
                try { CancelOrder(_pendingEntryOrder); }
                catch { }
            }
            ClearPendingEntryState();
        }

        private void ForceFlat(string reason)
        {
            if (_pendingEntrySignal != "" && _pendingEntryOrder != null)
            {
                try { CancelOrder(_pendingEntryOrder); }
                catch { }
            }
            ClearPendingEntryState();

            if (Position.MarketPosition == MarketPosition.Long)
                ExitLong("ForceFlat_" + reason, _activeSignal == "" ? TelemetrySignal("Long") : _activeSignal);
            else if (Position.MarketPosition == MarketPosition.Short)
                ExitShort("ForceFlat_" + reason, _activeSignal == "" ? TelemetrySignal("Short") : _activeSignal);
        }

        private bool CanTrade()
        {
            if (_permanentlyStopped || _sessionStopped) return false;
            if (_pauseUntil != DateTime.MinValue && Time[0] < _pauseUntil) return false;
            if (DailyLossLimit > 0.0 && _sessionRealizedPnl <= -DailyLossLimit) return false;
            if (WeeklyLossLimit > 0.0 && _weeklyRealizedPnl <= -WeeklyLossLimit) return false;
            if (MaxTradesPerDay > 0 && _tradesToday >= MaxTradesPerDay) return false;
            if (HardMaxTradesPerDay > 0 && _tradesToday >= HardMaxTradesPerDay) return false;
            if (MaxConsecutiveLosses > 0 && _consecutiveLosses >= MaxConsecutiveLosses) return false;
            return true;
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
                : MaxContractsByCapital;
            int byUser = UserMaxContracts > 0 ? UserMaxContracts : MaxContractsByCapital;
            int qty = Math.Min(Math.Min(byRisk, byMargin), Math.Min(byUser, MaxContractsByCapital));
            return Math.Max(0, qty);
        }

        private double HighestHigh(int lookback)
        {
            int bars = Math.Min(Math.Max(1, lookback), CurrentBar);
            double value = High[1];
            for (int barsAgo = 2; barsAgo <= bars; barsAgo++)
                value = Math.Max(value, High[barsAgo]);
            return value;
        }

        private double LowestLow(int lookback)
        {
            int bars = Math.Min(Math.Max(1, lookback), CurrentBar);
            double value = Low[1];
            for (int barsAgo = 2; barsAgo <= bars; barsAgo++)
                value = Math.Min(value, Low[barsAgo]);
            return value;
        }

        private double VolumeFactor()
        {
            double baseVolume = _volumeSma[0];
            if (baseVolume <= 0.0) return 0.0;
            return Volume[0] / baseVolume;
        }

        private bool InTradeWindow()
        {
            int now = ToHHMM(Time[0]);
            if (InWindow(now, TradeStartTime, TradeEndTime)) return true;
            return UseSecondTradeWindow && InWindow(now, SecondTradeStartTime, SecondTradeEndTime);
        }

        private bool ForceFlatDue()
        {
            return ToHHMM(Time[0]) >= ForceFlatTime;
        }

        private bool IsMomentumMode()
        {
            return string.Equals(SignalMode, "Momentum", StringComparison.OrdinalIgnoreCase)
                || string.Equals(SignalMode, "BreakdownMomentum", StringComparison.OrdinalIgnoreCase);
        }

        private bool IsOrbFailureMode()
        {
            return string.Equals(SignalMode, "OrbFailure", StringComparison.OrdinalIgnoreCase)
                || string.Equals(SignalMode, "OpeningRangeFailure", StringComparison.OrdinalIgnoreCase);
        }

        private bool IsOpenPressureMode()
        {
            return string.Equals(SignalMode, "OpenPressureShort", StringComparison.OrdinalIgnoreCase)
                || string.Equals(SignalMode, "OpenPressureStopShort", StringComparison.OrdinalIgnoreCase)
                || string.Equals(SignalMode, "OpeningPressureShort", StringComparison.OrdinalIgnoreCase);
        }

        private bool IsOpenPressureStopMode()
        {
            return string.Equals(SignalMode, "OpenPressureStopShort", StringComparison.OrdinalIgnoreCase);
        }

        private bool OpeningRangeUsable()
        {
            if (!_orBuilt) return false;
            int ticks = (int)Math.Round((_orHigh - _orLow) / TickSize);
            return ticks >= MinOpeningRangeTicks && ticks <= MaxOpeningRangeTicks;
        }

        private DateTime HhmmOnDate(DateTime date, int hhmm)
        {
            int hour = Math.Max(0, Math.Min(23, hhmm / 100));
            int minute = Math.Max(0, Math.Min(59, hhmm % 100));
            return date.Date.AddHours(hour).AddMinutes(minute);
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

        private string TelemetrySignal(string side)
        {
            return GetType().Name + "." + side;
        }

        private bool IsEntrySignalName(string name)
        {
            if (string.IsNullOrEmpty(name)) return false;
            if (_pendingEntrySignal != "" && name == _pendingEntrySignal) return true;
            return name == TelemetrySignal("Long") || name == TelemetrySignal("Short")
                || name == "Long" || name == "Short";
        }

        private void ClearActiveTradeState()
        {
            _activeSignal = "";
            _lastEntryBar = -1;
            _lastEntryPrice = 0.0;
            _lastStopTicks = 0;
            _stopMovedToBreakeven = false;
            _bestFavorableTicks = 0.0;
            ClearPendingEntryState();
        }

        private void ClearPendingEntryState()
        {
            _pendingEntryOrder = null;
            _pendingEntrySignal = "";
            _pendingEntryBar = -1;
        }

        protected override void OnOrderUpdate(Order order, double limitPrice, double stopPrice,
            int quantity, int filled, double averageFillPrice, OrderState orderState,
            DateTime time, ErrorCode error, string nativeError)
        {
            if (order == null) return;
            bool isEntry = IsEntrySignalName(order.Name);
            if (!isEntry) return;

            if (orderState == OrderState.Accepted || orderState == OrderState.Working)
                _pendingEntryOrder = order;

            if (orderState == OrderState.Cancelled || orderState == OrderState.Rejected)
            {
                ClearPendingEntryState();
                return;
            }

            if (orderState != OrderState.Filled) return;

            _activeSignal = order.Name;
            _lastEntryPrice = averageFillPrice > 0.0 ? averageFillPrice : Close[0];
            _lastEntryBar = CurrentBar;
            _stopMovedToBreakeven = false;
            _bestFavorableTicks = 0.0;
            ClearPendingEntryState();
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
                    _pauseUntil = Time[0].AddMinutes(Math.Max(1, PauseMinutesAfterLosses));
            }

            if (DailyLossLimit > 0.0 && _sessionRealizedPnl <= -DailyLossLimit)
                _sessionStopped = true;
            if (WeeklyLossLimit > 0.0 && _weeklyRealizedPnl <= -WeeklyLossLimit)
                _sessionStopped = true;
            if (MaxConsecutiveLosses > 0 && _consecutiveLosses >= MaxConsecutiveLosses)
                _sessionStopped = true;

            _lastProcessedTradeCount = total;
            ClearActiveTradeState();
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
        [Display(Name = "SignalMode", GroupName = "03-Direction", Order = 2)]
        public string SignalMode { get; set; }

        [NinjaScriptProperty, Range(0, 2359)]
        [Display(Name = "TradeStartTime", GroupName = "04-Time", Order = 0)]
        public int TradeStartTime { get; set; }

        [NinjaScriptProperty, Range(0, 2359)]
        [Display(Name = "TradeEndTime", GroupName = "04-Time", Order = 1)]
        public int TradeEndTime { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "UseSecondTradeWindow", GroupName = "04-Time", Order = 2)]
        public bool UseSecondTradeWindow { get; set; }

        [NinjaScriptProperty, Range(0, 2359)]
        [Display(Name = "SecondTradeStartTime", GroupName = "04-Time", Order = 3)]
        public int SecondTradeStartTime { get; set; }

        [NinjaScriptProperty, Range(0, 2359)]
        [Display(Name = "SecondTradeEndTime", GroupName = "04-Time", Order = 4)]
        public int SecondTradeEndTime { get; set; }

        [NinjaScriptProperty, Range(0, 2359)]
        [Display(Name = "ForceFlatTime", GroupName = "04-Time", Order = 5)]
        public int ForceFlatTime { get; set; }

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

        [NinjaScriptProperty, Range(0.0, 10.0)]
        [Display(Name = "MinVolumeFactor", GroupName = "05-Filters", Order = 5)]
        public double MinVolumeFactor { get; set; }

        [NinjaScriptProperty, Range(0.0, 100.0)]
        [Display(Name = "MinAdx", GroupName = "05-Filters", Order = 6)]
        public double MinAdx { get; set; }

        [NinjaScriptProperty, Range(0.0, 100.0)]
        [Display(Name = "MaxAdx", GroupName = "05-Filters", Order = 7)]
        public double MaxAdx { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "UseEmaStretchFilter", GroupName = "05-Filters", Order = 8)]
        public bool UseEmaStretchFilter { get; set; }

        [NinjaScriptProperty, Range(0, 200)]
        [Display(Name = "MinEmaStretchTicks", GroupName = "05-Filters", Order = 9)]
        public int MinEmaStretchTicks { get; set; }

        [NinjaScriptProperty, Range(1, 50)]
        [Display(Name = "SweepLookbackBars", GroupName = "06-Setup", Order = 0)]
        public int SweepLookbackBars { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "FadeSweeps", GroupName = "06-Setup", Order = 1)]
        public bool FadeSweeps { get; set; }

        [NinjaScriptProperty, Range(0, 100)]
        [Display(Name = "SweepDistanceTicks", GroupName = "06-Setup", Order = 2)]
        public int SweepDistanceTicks { get; set; }

        [NinjaScriptProperty, Range(0, 100)]
        [Display(Name = "ReclaimTicks", GroupName = "06-Setup", Order = 3)]
        public int ReclaimTicks { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "UseVwapDistanceFilter", GroupName = "06-Setup", Order = 4)]
        public bool UseVwapDistanceFilter { get; set; }

        [NinjaScriptProperty, Range(0, 400)]
        [Display(Name = "MinVwapDistanceTicks", GroupName = "06-Setup", Order = 5)]
        public int MinVwapDistanceTicks { get; set; }

        [NinjaScriptProperty, Range(0, 800)]
        [Display(Name = "MaxVwapDistanceTicks", GroupName = "06-Setup", Order = 6)]
        public int MaxVwapDistanceTicks { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "RequireCloseAgainstSweep", GroupName = "06-Setup", Order = 7)]
        public bool RequireCloseAgainstSweep { get; set; }

        [NinjaScriptProperty, Range(1, 200)]
        [Display(Name = "MinBarRangeTicks", GroupName = "06-Setup", Order = 8)]
        public int MinBarRangeTicks { get; set; }

        [NinjaScriptProperty, Range(0.0, 1.0)]
        [Display(Name = "MinBodyRangePct", GroupName = "06-Setup", Order = 9)]
        public double MinBodyRangePct { get; set; }

        [NinjaScriptProperty, Range(0.0, 1.0)]
        [Display(Name = "MinCloseLocationPct", GroupName = "06-Setup", Order = 10)]
        public double MinCloseLocationPct { get; set; }

        [NinjaScriptProperty, Range(1, 20)]
        [Display(Name = "MomentumLookbackBars", GroupName = "06-Setup", Order = 11)]
        public int MomentumLookbackBars { get; set; }

        [NinjaScriptProperty, Range(0, 100)]
        [Display(Name = "MomentumBreakTicks", GroupName = "06-Setup", Order = 12)]
        public int MomentumBreakTicks { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "RequireMomentumBreak", GroupName = "06-Setup", Order = 13)]
        public bool RequireMomentumBreak { get; set; }

        [NinjaScriptProperty, Range(1, 5)]
        [Display(Name = "OpenPressureMinScore", GroupName = "06-Setup", Order = 14)]
        public int OpenPressureMinScore { get; set; }

        [NinjaScriptProperty, Range(0, 2359)]
        [Display(Name = "OpeningRangeStartTime", GroupName = "06-Setup", Order = 15)]
        public int OpeningRangeStartTime { get; set; }

        [NinjaScriptProperty, Range(1, 120)]
        [Display(Name = "OpeningRangeMinutes", GroupName = "06-Setup", Order = 16)]
        public int OpeningRangeMinutes { get; set; }

        [NinjaScriptProperty, Range(0, 100)]
        [Display(Name = "OpeningRangeBreakBufferTicks", GroupName = "06-Setup", Order = 17)]
        public int OpeningRangeBreakBufferTicks { get; set; }

        [NinjaScriptProperty, Range(1, 400)]
        [Display(Name = "MinOpeningRangeTicks", GroupName = "06-Setup", Order = 18)]
        public int MinOpeningRangeTicks { get; set; }

        [NinjaScriptProperty, Range(1, 800)]
        [Display(Name = "MaxOpeningRangeTicks", GroupName = "06-Setup", Order = 19)]
        public int MaxOpeningRangeTicks { get; set; }

        [NinjaScriptProperty, Range(0, 100)]
        [Display(Name = "StopBufferTicks", GroupName = "07-Orders", Order = 0)]
        public int StopBufferTicks { get; set; }

        [NinjaScriptProperty, Range(1, 200)]
        [Display(Name = "MinStopTicks", GroupName = "07-Orders", Order = 1)]
        public int MinStopTicks { get; set; }

        [NinjaScriptProperty, Range(1, 300)]
        [Display(Name = "MaxStopTicks", GroupName = "07-Orders", Order = 2)]
        public int MaxStopTicks { get; set; }

        [NinjaScriptProperty, Range(0.0, 10.0)]
        [Display(Name = "AtrStopMult", GroupName = "07-Orders", Order = 3)]
        public double AtrStopMult { get; set; }

        [NinjaScriptProperty, Range(0.1, 10.0)]
        [Display(Name = "RewardRiskRatio", GroupName = "07-Orders", Order = 4)]
        public double RewardRiskRatio { get; set; }

        [NinjaScriptProperty, Range(1, 300)]
        [Display(Name = "MinTargetTicks", GroupName = "07-Orders", Order = 5)]
        public int MinTargetTicks { get; set; }

        [NinjaScriptProperty, Range(0, 20)]
        [Display(Name = "EntryOffsetTicks", GroupName = "07-Orders", Order = 6)]
        public int EntryOffsetTicks { get; set; }

        [NinjaScriptProperty, Range(1, 20)]
        [Display(Name = "EntryTimeoutBars", GroupName = "07-Orders", Order = 7)]
        public int EntryTimeoutBars { get; set; }

        [NinjaScriptProperty, Range(0.0, 5.0)]
        [Display(Name = "MoveToBreakevenAtR", GroupName = "07-Orders", Order = 8)]
        public double MoveToBreakevenAtR { get; set; }

        [NinjaScriptProperty, Range(0, 50)]
        [Display(Name = "BreakevenPlusTicks", GroupName = "07-Orders", Order = 9)]
        public int BreakevenPlusTicks { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "UseTrailingStop", GroupName = "07-Orders", Order = 10)]
        public bool UseTrailingStop { get; set; }

        [NinjaScriptProperty, Range(0.0, 5.0)]
        [Display(Name = "TrailAfterR", GroupName = "07-Orders", Order = 11)]
        public double TrailAfterR { get; set; }

        [NinjaScriptProperty, Range(1, 100)]
        [Display(Name = "TrailDistanceTicks", GroupName = "07-Orders", Order = 12)]
        public int TrailDistanceTicks { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "UseTimeStop", GroupName = "07-Orders", Order = 13)]
        public bool UseTimeStop { get; set; }

        [NinjaScriptProperty, Range(1, 100)]
        [Display(Name = "TimeStopBars", GroupName = "07-Orders", Order = 14)]
        public int TimeStopBars { get; set; }

        [NinjaScriptProperty, Range(0.0, 2.0)]
        [Display(Name = "MinProgressR", GroupName = "07-Orders", Order = 15)]
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
