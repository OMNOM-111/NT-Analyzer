// =============================================================================
// NTAMnqPreCashCompressionBreakoutC019
// -----------------------------------------------------------------------------
// Standalone MNQ CELL-019 strategy. NEW family: "Compression Breakout".
//
// Hypothesis (one clear idea):
//   In a FREE pre-cash ETH window (default 03:20-05:55 PT, outside the active
//   06:35-12:45 PT cluster), MNQ 5-minute price often coils into a tight
//   compression box (range contraction vs ATR). When that box breaks and the
//   break is *confirmed* by a controlled retest/reclaim (or a volume-expanding
//   continuation that holds), the move tends to follow through for several
//   bars. The trade is designed to live multiple bars; the edge does NOT rely
//   on same-bar stop/target ordering (the failure mode that sank the 1m
//   CELL-015/016/017/018 scalp family).
//
// Mechanics:
//   1. Compression: over CompressionLookbackBars closed bars the box range is
//      both below an absolute cap (MaxCompressionRangeTicks) and contracted
//      relative to ATR (boxRange <= CompressionAtrMult * ATR).
//   2. Breakout: a bar closes beyond the box edge by BreakoutBufferTicks.
//   3. Confirmation (ConfirmMode):
//        - Retest: arm the breakout, then enter only when price pulls back to
//          the broken edge (within RetestTicks) and a later bar reclaims it.
//        - Continuation: enter on a breakout bar that closes strong beyond the
//          edge WITH volume expansion (controlled continuation, not raw break).
//        - ReclaimOrContinuation: accept either path.
//   4. Filters: VWAP regime agreement, EMA fast/mid agreement + slope, volume
//      expansion, dead-volume floor, minimum bar range.
//   5. Stop/target are real-sized (5m geometry, MinStopTicks floor), entries
//      via market on a confirmed closed bar.
//
// This class intentionally does NOT inherit from NTAMicroMnqScalpPilot and is
// not a clone of the C015/C016/C017/C018 logic.
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
    public class NTAMnqPreCashCompressionBreakoutC019 : Strategy
    {
        private EMA _emaFast;
        private EMA _emaMid;
        private EMA _emaSlow;
        private ATR _atr;
        private SMA _volumeSma;
        private Series<double> _vwapSeries;

        private DateTime _sessionDate = DateTime.MinValue;
        private double _vwapCumPV;
        private double _vwapCumVol;

        // Pending-breakout state machine.
        private int _pendingDir;            // +1 long break, -1 short break, 0 none
        private int _pendingBreakoutBar = -1;
        private double _pendingEdge;        // broken box edge (reclaim level)
        private double _pendingOppEdge;     // opposite box edge (stop reference)
        private bool _pendingRetested;      // price tagged the edge after break

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

        protected override void OnStateChange()
        {
            if (State == State.SetDefaults)
            {
                Description = "MNQ CELL-019 standalone pre-cash compression-breakout (retest/continuation).";
                Name = "Compression Breakout MNQ 5m v1 c019";
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

                InstrumentName = "MNQ";
                ContractName = "MNQ 06-26";
                SessionTemplateName = "CME US Index Futures ETH";
                BaseTimeframeSeconds = 300;

                StartingCapital = 2000.0;
                IntradayOnly = true;
                ActiveMarginPerContract = 100.0;
                MaxContractsByCapital = 20;
                InstrumentStatus = "allowed";
                MarginSourceBroker = "NinjaTrader";

                EnableLong = true;
                EnableShort = true;
                ConfirmMode = "ReclaimOrContinuation";

                // Pre-cash free window (PT clock as configured on the chart).
                TradeStartTime = 320;
                TradeEndTime = 555;
                UseSecondTradeWindow = false;
                SecondTradeStartTime = 100;
                SecondTradeEndTime = 300;
                ForceFlatTime = 559;

                EmaFastPeriod = 9;
                EmaMidPeriod = 21;
                EmaSlowPeriod = 50;
                AtrPeriod = 14;
                VolumeSmaPeriod = 20;
                MinVolumeFactor = 0.6;
                RequireVwapAgreement = true;
                RequireEmaAgreement = true;
                RequireEmaSlope = true;

                CompressionLookbackBars = 8;
                MaxCompressionRangeTicks = 60;
                CompressionAtrMult = 1.30;
                MinCompressionRangeTicks = 8;
                BreakoutBufferTicks = 2;
                RetestTicks = 4;
                RetestTimeoutBars = 4;
                ReclaimTicks = 1;
                VolExpansionFactor = 1.20;
                MinBarRangeTicks = 4;

                StopBufferTicks = 4;
                MinStopTicks = 16;
                MaxStopTicks = 40;
                AtrStopMult = 1.0;
                RewardRiskRatio = 1.6;
                MinTargetTicks = 16;
                EntryOffsetTicks = 0;
                EntryTimeoutBars = 3;
                MoveToBreakevenAtR = 1.0;
                BreakevenPlusTicks = 2;
                UseTrailingStop = false;
                TrailAfterR = 1.5;
                TrailDistanceTicks = 12;
                UseTimeStop = true;
                TimeStopBars = 6;
                MinProgressR = 0.30;

                RiskPerTradePct = 0.75;
                UserMaxContracts = 1;
                MaxOpenPositions = 1;
                MaxDailyLossUsd = 80.0;
                MaxWeeklyLossUsd = 200.0;
                MaxTradesPerDay = 4;
                HardMaxTradesPerDay = 6;
                MaxConsecutiveLosses = 3;
                PauseAfterConsecutiveLosses = 2;
                PauseMinutesAfterLosses = 60;
                RoundTurnCommission = 1.90;
                SlippageTicks = 1;
            }
            else if (State == State.DataLoaded)
            {
                _emaFast = EMA(EmaFastPeriod);
                _emaMid = EMA(EmaMidPeriod);
                _emaSlow = EMA(EmaSlowPeriod);
                _atr = ATR(AtrPeriod);
                _volumeSma = SMA(Volume, VolumeSmaPeriod);
                _vwapSeries = new Series<double>(this);

                _permanentlyStopped = StartingCapital <= 0.0
                    || ActiveMarginPerContract <= 0.0
                    || MaxContractsByCapital < 1
                    || string.Equals(InstrumentStatus, "blocked", StringComparison.OrdinalIgnoreCase)
                    || string.Equals(InstrumentStatus, "unknown", StringComparison.OrdinalIgnoreCase);
            }
            else if (State == State.Realtime)
            {
                ResetRealtimeRiskAccounting();
            }
        }

        protected override void OnBarUpdate()
        {
            if (BarsInProgress != 0) return;
            if (CurrentBar < 1) return;

            UpdateSessionState();
            UpdateVwap();
            ManageOpenPosition();

            if (ForceFlatDue())
            {
                ForceFlat("time");
                _pendingDir = 0;
                return;
            }

            if (CurrentBar < BarsRequiredToTrade) return;

            if (!InTradeWindow())
            {
                _pendingDir = 0;
                return;
            }
            if (!CanTrade()) return;
            if (Position.MarketPosition != MarketPosition.Flat) return;
            if (_activeSignal != "") return;
            if (MaxOpenPositions < 1) return;

            TryEnterCompressionBreakout();
        }

        private void UpdateSessionState()
        {
            DateTime currentDate = Time[0].Date;
            if (_sessionDate == currentDate) return;

            _sessionDate = currentDate;
            _vwapCumPV = 0.0;
            _vwapCumVol = 0.0;
            ResetDailyRisk();
            ClearActiveTradeState();
            _pendingDir = 0;
            _pendingBreakoutBar = -1;
            _pendingRetested = false;
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

        private void ResetRealtimeRiskAccounting()
        {
            _cumulativeRealizedPnl = 0.0;
            _sessionRealizedPnl = 0.0;
            _weeklyRealizedPnl = 0.0;
            _tradesToday = 0;
            _consecutiveLosses = 0;
            _sessionStopped = false;
            _pauseUntil = DateTime.MinValue;
            _weekStartDate = WeekStart(Time[0].Date);
            _lastProcessedTradeCount = SystemPerformance == null
                ? 0
                : Math.Max(0, SystemPerformance.AllTrades.Count);
            Print(string.Format(
                "[RISK:realtime_reset] historicalTrades={0}; live paper risk starts from zero",
                _lastProcessedTradeCount));
        }

        private void UpdateVwap()
        {
            double volume = Math.Max(1.0, Volume[0]);
            double typical = (High[0] + Low[0] + Close[0]) / 3.0;
            _vwapCumPV += typical * volume;
            _vwapCumVol += volume;
            _vwapSeries[0] = _vwapCumVol > 0.0 ? _vwapCumPV / _vwapCumVol : Close[0];
        }

        // --------------------------------------------------------------------
        // Compression-breakout engine
        // --------------------------------------------------------------------
        private void TryEnterCompressionBreakout()
        {
            int lookback = Math.Min(Math.Max(2, CompressionLookbackBars), CurrentBar - 1);
            if (lookback < 2) return;

            double boxHigh = HighestHigh(lookback);
            double boxLow = LowestLow(lookback);
            if (boxHigh <= boxLow) return;

            double boxRangeTicks = (boxHigh - boxLow) / TickSize;
            double atrTicks = _atr[0] / TickSize;
            bool compressed = boxRangeTicks >= MinCompressionRangeTicks
                && boxRangeTicks <= MaxCompressionRangeTicks
                && (CompressionAtrMult <= 0.0 || boxRangeTicks <= CompressionAtrMult * atrTicks);

            // 1. Continue/expire any armed breakout (retest path).
            if (_pendingDir != 0)
            {
                if (CurrentBar - _pendingBreakoutBar > Math.Max(1, RetestTimeoutBars))
                {
                    _pendingDir = 0;
                    _pendingRetested = false;
                }
                else
                {
                    if (_pendingDir > 0)
                    {
                        if (Low[0] <= _pendingEdge + RetestTicks * TickSize)
                            _pendingRetested = true;
                        if (_pendingRetested
                            && Close[0] >= _pendingEdge + ReclaimTicks * TickSize
                            && Close[0] > Open[0]
                            && LongFiltersPass())
                        {
                            EnterBreakout(true, _pendingOppEdge);
                            _pendingDir = 0;
                            return;
                        }
                    }
                    else
                    {
                        if (High[0] >= _pendingEdge - RetestTicks * TickSize)
                            _pendingRetested = true;
                        if (_pendingRetested
                            && Close[0] <= _pendingEdge - ReclaimTicks * TickSize
                            && Close[0] < Open[0]
                            && ShortFiltersPass())
                        {
                            EnterBreakout(false, _pendingOppEdge);
                            _pendingDir = 0;
                            return;
                        }
                    }
                }
            }

            if (!compressed) return;

            double rangeTicks = (High[0] - Low[0]) / TickSize;
            if (rangeTicks < MinBarRangeTicks) return;

            bool brokeUp = Close[0] >= boxHigh + BreakoutBufferTicks * TickSize;
            bool brokeDown = Close[0] <= boxLow - BreakoutBufferTicks * TickSize;

            // 2. Continuation entry on a strong, volume-expanding breakout bar.
            bool allowContinuation = !IsRetestOnlyMode();
            if (allowContinuation && EnableLong && brokeUp && VolumeExpanded() && LongFiltersPass())
            {
                EnterBreakout(true, boxLow);
                _pendingDir = 0;
                return;
            }
            if (allowContinuation && EnableShort && brokeDown && VolumeExpanded() && ShortFiltersPass())
            {
                EnterBreakout(false, boxHigh);
                _pendingDir = 0;
                return;
            }

            // 3. Arm a retest if continuation did not fire (or in retest-only mode).
            bool allowRetest = !IsContinuationOnlyMode();
            if (allowRetest && _pendingDir == 0)
            {
                if (EnableLong && brokeUp)
                {
                    _pendingDir = 1;
                    _pendingEdge = boxHigh;
                    _pendingOppEdge = boxLow;
                    _pendingBreakoutBar = CurrentBar;
                    _pendingRetested = false;
                }
                else if (EnableShort && brokeDown)
                {
                    _pendingDir = -1;
                    _pendingEdge = boxLow;
                    _pendingOppEdge = boxHigh;
                    _pendingBreakoutBar = CurrentBar;
                    _pendingRetested = false;
                }
            }
        }

        private bool LongFiltersPass()
        {
            if (VolumeFactor() < MinVolumeFactor) return false;
            if (RequireVwapAgreement && Close[0] < _vwapSeries[0]) return false;
            if (RequireEmaAgreement && _emaFast[0] <= _emaMid[0]) return false;
            if (RequireEmaSlope && _emaFast[0] <= _emaFast[1]) return false;
            return true;
        }

        private bool ShortFiltersPass()
        {
            if (VolumeFactor() < MinVolumeFactor) return false;
            if (RequireVwapAgreement && Close[0] > _vwapSeries[0]) return false;
            if (RequireEmaAgreement && _emaFast[0] >= _emaMid[0]) return false;
            if (RequireEmaSlope && _emaFast[0] >= _emaFast[1]) return false;
            return true;
        }

        private bool VolumeExpanded()
        {
            if (VolExpansionFactor <= 0.0) return true;
            return VolumeFactor() >= VolExpansionFactor;
        }

        private void EnterBreakout(bool isLong, double oppositeEdge)
        {
            int stopTicks = ComputeStopTicks(isLong, oppositeEdge);
            int targetTicks = (int)Math.Round(stopTicks * RewardRiskRatio);
            if (stopTicks < MinStopTicks || targetTicks < MinTargetTicks) { return; }

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

        private int ComputeStopTicks(bool isLong, double oppositeEdge)
        {
            double geometryPrice = isLong
                ? Math.Min(Low[0], oppositeEdge) - StopBufferTicks * TickSize
                : Math.Max(High[0], oppositeEdge) + StopBufferTicks * TickSize;
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
                && _bestFavorableTicks >= _lastStopTicks * TrailAfterR
                && _stopMovedToBreakeven)
            {
                double trailPrice = isLong
                    ? Close[0] - TrailDistanceTicks * TickSize
                    : Close[0] + TrailDistanceTicks * TickSize;
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

        private void ForceFlat(string reason)
        {
            if (Position.MarketPosition == MarketPosition.Long)
                ExitLong("ForceFlat_" + reason, _activeSignal == "" ? TelemetrySignal("Long") : _activeSignal);
            else if (Position.MarketPosition == MarketPosition.Short)
                ExitShort("ForceFlat_" + reason, _activeSignal == "" ? TelemetrySignal("Short") : _activeSignal);
        }

        private bool CanTrade()
        {
            if (_permanentlyStopped || _sessionStopped) return false;
            if (_pauseUntil != DateTime.MinValue && Time[0] < _pauseUntil) return false;
            if (MaxDailyLossUsd > 0.0 && _sessionRealizedPnl <= -MaxDailyLossUsd) return false;
            if (MaxWeeklyLossUsd > 0.0 && _weeklyRealizedPnl <= -MaxWeeklyLossUsd) return false;
            if (MaxTradesPerDay > 0 && _tradesToday >= MaxTradesPerDay) return false;
            if (HardMaxTradesPerDay > 0 && _tradesToday >= HardMaxTradesPerDay) return false;
            if (MaxConsecutiveLosses > 0 && _consecutiveLosses >= MaxConsecutiveLosses) return false;
            return true;
        }

        private int ComputeQuantity(int stopTicks)
        {
            if (_permanentlyStopped) { return 0; }
            double tickValue = TickValue();
            if (tickValue <= 0.0) { return 0; }

            double equity = CurrentEquity();
            double riskBudget = equity * RiskPerTradePct / 100.0;
            double contractRisk = stopTicks * tickValue + RoundTurnCommission + SlippageTicks * tickValue;
            if (contractRisk <= 0.0) { return 0; }

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

        private bool IsRetestOnlyMode()
        {
            return string.Equals(ConfirmMode, "Retest", StringComparison.OrdinalIgnoreCase)
                || string.Equals(ConfirmMode, "RetestOnly", StringComparison.OrdinalIgnoreCase);
        }

        private bool IsContinuationOnlyMode()
        {
            return string.Equals(ConfirmMode, "Continuation", StringComparison.OrdinalIgnoreCase)
                || string.Equals(ConfirmMode, "ContinuationOnly", StringComparison.OrdinalIgnoreCase);
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

        private void ClearActiveTradeState()
        {
            _activeSignal = "";
            _lastEntryBar = -1;
            _lastEntryPrice = 0.0;
            _lastStopTicks = 0;
            _stopMovedToBreakeven = false;
            _bestFavorableTicks = 0.0;
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

            if (MaxDailyLossUsd > 0.0 && _sessionRealizedPnl <= -MaxDailyLossUsd)
                _sessionStopped = true;
            if (MaxWeeklyLossUsd > 0.0 && _weeklyRealizedPnl <= -MaxWeeklyLossUsd)
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

        [NinjaScriptProperty, Range(1, 3600)]
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
        [Display(Name = "ConfirmMode", GroupName = "03-Direction", Order = 2)]
        public string ConfirmMode { get; set; }

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

        [NinjaScriptProperty, Range(2, 300)]
        [Display(Name = "EmaMidPeriod", GroupName = "05-Filters", Order = 1)]
        public int EmaMidPeriod { get; set; }

        [NinjaScriptProperty, Range(2, 400)]
        [Display(Name = "EmaSlowPeriod", GroupName = "05-Filters", Order = 2)]
        public int EmaSlowPeriod { get; set; }

        [NinjaScriptProperty, Range(2, 200)]
        [Display(Name = "AtrPeriod", GroupName = "05-Filters", Order = 3)]
        public int AtrPeriod { get; set; }

        [NinjaScriptProperty, Range(2, 500)]
        [Display(Name = "VolumeSmaPeriod", GroupName = "05-Filters", Order = 4)]
        public int VolumeSmaPeriod { get; set; }

        [NinjaScriptProperty, Range(0.0, 10.0)]
        [Display(Name = "MinVolumeFactor", GroupName = "05-Filters", Order = 5)]
        public double MinVolumeFactor { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "RequireVwapAgreement", GroupName = "05-Filters", Order = 6)]
        public bool RequireVwapAgreement { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "RequireEmaAgreement", GroupName = "05-Filters", Order = 7)]
        public bool RequireEmaAgreement { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "RequireEmaSlope", GroupName = "05-Filters", Order = 8)]
        public bool RequireEmaSlope { get; set; }

        [NinjaScriptProperty, Range(2, 80)]
        [Display(Name = "CompressionLookbackBars", GroupName = "06-Compression", Order = 0)]
        public int CompressionLookbackBars { get; set; }

        [NinjaScriptProperty, Range(2, 600)]
        [Display(Name = "MaxCompressionRangeTicks", GroupName = "06-Compression", Order = 1)]
        public int MaxCompressionRangeTicks { get; set; }

        [NinjaScriptProperty, Range(0.0, 10.0)]
        [Display(Name = "CompressionAtrMult", GroupName = "06-Compression", Order = 2)]
        public double CompressionAtrMult { get; set; }

        [NinjaScriptProperty, Range(0, 400)]
        [Display(Name = "MinCompressionRangeTicks", GroupName = "06-Compression", Order = 3)]
        public int MinCompressionRangeTicks { get; set; }

        [NinjaScriptProperty, Range(0, 100)]
        [Display(Name = "BreakoutBufferTicks", GroupName = "06-Compression", Order = 4)]
        public int BreakoutBufferTicks { get; set; }

        [NinjaScriptProperty, Range(0, 200)]
        [Display(Name = "RetestTicks", GroupName = "06-Compression", Order = 5)]
        public int RetestTicks { get; set; }

        [NinjaScriptProperty, Range(1, 30)]
        [Display(Name = "RetestTimeoutBars", GroupName = "06-Compression", Order = 6)]
        public int RetestTimeoutBars { get; set; }

        [NinjaScriptProperty, Range(0, 100)]
        [Display(Name = "ReclaimTicks", GroupName = "06-Compression", Order = 7)]
        public int ReclaimTicks { get; set; }

        [NinjaScriptProperty, Range(0.0, 10.0)]
        [Display(Name = "VolExpansionFactor", GroupName = "06-Compression", Order = 8)]
        public double VolExpansionFactor { get; set; }

        [NinjaScriptProperty, Range(1, 200)]
        [Display(Name = "MinBarRangeTicks", GroupName = "06-Compression", Order = 9)]
        public int MinBarRangeTicks { get; set; }

        [NinjaScriptProperty, Range(0, 100)]
        [Display(Name = "StopBufferTicks", GroupName = "07-Orders", Order = 0)]
        public int StopBufferTicks { get; set; }

        [NinjaScriptProperty, Range(1, 400)]
        [Display(Name = "MinStopTicks", GroupName = "07-Orders", Order = 1)]
        public int MinStopTicks { get; set; }

        [NinjaScriptProperty, Range(1, 600)]
        [Display(Name = "MaxStopTicks", GroupName = "07-Orders", Order = 2)]
        public int MaxStopTicks { get; set; }

        [NinjaScriptProperty, Range(0.0, 10.0)]
        [Display(Name = "AtrStopMult", GroupName = "07-Orders", Order = 3)]
        public double AtrStopMult { get; set; }

        [NinjaScriptProperty, Range(0.1, 10.0)]
        [Display(Name = "RewardRiskRatio", GroupName = "07-Orders", Order = 4)]
        public double RewardRiskRatio { get; set; }

        [NinjaScriptProperty, Range(1, 400)]
        [Display(Name = "MinTargetTicks", GroupName = "07-Orders", Order = 5)]
        public int MinTargetTicks { get; set; }

        [NinjaScriptProperty, Range(0, 40)]
        [Display(Name = "EntryOffsetTicks", GroupName = "07-Orders", Order = 6)]
        public int EntryOffsetTicks { get; set; }

        [NinjaScriptProperty, Range(1, 30)]
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

        [NinjaScriptProperty, Range(1, 200)]
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
        [Display(Name = "MaxDailyLossUsd", GroupName = "08-Risk", Order = 3)]
        public double MaxDailyLossUsd { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "MaxWeeklyLossUsd", GroupName = "08-Risk", Order = 4)]
        public double MaxWeeklyLossUsd { get; set; }

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

        [NinjaScriptProperty, Range(0, 480)]
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
