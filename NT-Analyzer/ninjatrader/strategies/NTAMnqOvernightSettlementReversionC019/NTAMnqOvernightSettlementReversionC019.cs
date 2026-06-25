// =============================================================================
// NTAMnqOvernightSettlementReversionC019
// -----------------------------------------------------------------------------
// Standalone MNQ CELL-019 strategy. NEW family: "Overnight Settlement
// Reversion". Engine #3 for CELL-019 (engines #1 squeeze breakout and #2
// VWAP fade both rejected at smoke in the 13:00-15:30 PT post-cluster window).
//
// Hypothesis: After the RTH session closes (settlement print at 13:00 PT for
// CME US Index Futures RTH session), the overnight Globex/Asia/Europe tape
// often drifts away from settlement on thin liquidity, then mean-reverts as
// price discovery resumes near the next London/NY open. A 15-minute fade
// engine anchored to PRIOR RTH SETTLEMENT (not intraday VWAP) targets the
// reversion. Wider stops + targets dimensioned in points (not ticks-near-
// entry) escape the same-bar / commission-drag failure modes of the 5m VWAP
// fade engine.
//
// Engine is structurally NEW vs every existing strategy:
//   * Timeframe = 15 Minute on ETH session (overnight bars required).
//   * Window = 16:00-23:00 PT (after RTH close, before NY pre-cash). Truly
//     free, does NOT overlap MNQ active cluster (06:35-12:45 PT).
//   * Anchor = previous RTH settlement (close of last bar at/before 13:00 PT).
//     Stored at session boundary. Distinct from any VWAP/EMA/Bollinger
//     anchor.
//   * Signal = price is extended >= MinPointsFromSettlement points from
//     settlement, last N bars consistently extended (drift), RSI extreme
//     in the fade direction, ADX <= RangeAdxMax (regime filter).
//   * Stops dimensioned in POINTS (not ticks). MinStopPoints=5
//     (=20 ticks MNQ) up to MaxStopPoints=12 (=48 ticks). Gives the bar
//     room to breathe; ATR-floor sized too. Targets are settlement +-
//     SettlementBufferPoints OR RR multiple, whichever is closer.
//   * Trades expected: 1-2 per night, ~250 nights/yr -> 250-500 trades over
//     2y. Per-trade R economics clear commission floor.
//
// Risk shell identical pattern (OnPositionUpdate accrues realized pnl,
// ResetRealtimeRiskAccounting at State.Realtime, CanTrade gate,
// ComputeQuantity floor-to-1 when fractional budget rounds below one but
// margin and user caps allow). NOT a source of edge.
//
// Does NOT inherit any carrier; does NOT reuse squeeze / VWAP-fade /
// liquidity-sweep / open-pressure / opening-drive / pre-cash-compression /
// session-edge / OrbRetest signal logic.
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
    public class NTAMnqOvernightSettlementReversionC019 : Strategy
    {
        private ATR _atr;
        private ADX _adx;
        private RSI _rsi;
        private SMA _volumeSma;

        private double _settlementPrice;
        private bool _settlementCaptured;
        private DateTime _lastSettlementDate = DateTime.MinValue;
        private DateTime _overnightSessionDate = DateTime.MinValue;
        private double _maxAbsExtensionPoints;

        private double _weeklyRealizedPnl;
        private DateTime _weekStartDate = DateTime.MinValue;
        private double _cumulativeRealizedPnl;
        private double _sessionRealizedPnl;
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
                Description = "MNQ CELL-019 overnight settlement reversion (15m, mean-reversion to prior RTH settlement).";
                Name = "Overnight Settlement Reversion MNQ 15m v1 c019";
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
                BarsRequiredToTrade = 40;
                IsInstantiatedOnEachOptimizationIteration = true;

                InstrumentName = "MNQ";
                ContractName = "MNQ 06-26";
                SessionTemplateName = "CME US Index Futures ETH";
                BaseTimeframeSeconds = 900;

                StartingCapital = 2000.0;
                IntradayOnly = true;
                ActiveMarginPerContract = 100.0;
                MaxContractsByCapital = 20;
                InstrumentStatus = "allowed";
                MarginSourceBroker = "NinjaTrader";

                EnableLong = true;
                EnableShort = true;

                // Overnight window in PT clock (Globex evening through Asia).
                TradeStartTime = 1600;
                TradeEndTime = 2300;
                ForceFlatTime = 2330;
                // RTH settlement print time (close of bar AT/BEFORE this PT minute).
                SettlementTimePT = 1300;

                MinPointsFromSettlement = 18.0;
                MaxPointsFromSettlement = 80.0;
                DriftConsecutiveBars = 2;
                AdxPeriod = 14;
                RangeAdxMax = 32.0;
                RsiPeriod = 14;
                RsiShortMin = 58.0;
                RsiLongMax = 42.0;
                AtrPeriod = 14;
                VolumeSmaPeriod = 20;
                VolCeilingFactor = 2.50;
                VolMinFactor = 0.30;
                MinBarRangeTicks = 6;
                MaxBarRangeTicks = 320;
                RequireRejection = false;
                RejectionFractionOfRange = 0.40;

                StopBufferPoints = 1.5;
                MinStopPoints = 5.0;
                MaxStopPoints = 12.0;
                AtrStopMult = 1.2;
                TargetMode = "SettlementOrRR";
                SettlementBufferPoints = 2.0;
                RewardRiskRatio = 1.5;
                MinTargetPoints = 4.0;
                MoveToBreakevenAtR = 0.6;
                BreakevenPlusTicks = 2;
                UseTrailingStop = false;
                TrailAfterR = 1.0;
                TrailDistanceTicks = 12;
                UseTimeStop = true;
                TimeStopBars = 8;
                MinProgressR = 0.30;

                RiskPerTradePct = 0.60;
                UserMaxContracts = 1;
                MaxOpenPositions = 1;
                MaxDailyLossUsd = 80.0;
                MaxWeeklyLossUsd = 200.0;
                MaxTradesPerDay = 3;
                HardMaxTradesPerDay = 4;
                MaxConsecutiveLosses = 3;
                PauseAfterConsecutiveLosses = 2;
                PauseMinutesAfterLosses = 60;
                RoundTurnCommission = 1.90;
                SlippageTicks = 1;
            }
            else if (State == State.DataLoaded)
            {
                _atr = ATR(AtrPeriod);
                _adx = ADX(AdxPeriod);
                _rsi = RSI(RsiPeriod, 3);
                _volumeSma = SMA(Volume, VolumeSmaPeriod);

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

            CaptureSettlementIfHit();
            UpdateOvernightSession();
            ManageOpenPosition();

            if (ForceFlatDue())
            {
                ForceFlat("time");
                return;
            }

            if (CurrentBar < BarsRequiredToTrade) return;
            if (!InTradeWindow()) return;
            if (!_settlementCaptured) return;
            if (!CanTrade()) return;
            if (Position.MarketPosition != MarketPosition.Flat) return;
            if (_activeSignal != "") return;
            if (MaxOpenPositions < 1) return;

            TryEnterReversion();
        }

        private void CaptureSettlementIfHit()
        {
            // Capture the close of the bar whose CLOSE time is at or just
            // before SettlementTimePT for the current settlement day.
            int barHHMM = ToHHMM(Time[0]);
            int settleHHMM = SettlementTimePT;
            if (barHHMM <= settleHHMM && barHHMM >= Math.Max(1230, settleHHMM - 60))
            {
                _settlementPrice = Close[0];
                _settlementCaptured = true;
                DateTime today = Time[0].Date;
                if (_lastSettlementDate != today)
                {
                    // A new RTH settlement just printed: start a fresh
                    // overnight session (reset per-day risk + drift state).
                    _lastSettlementDate = today;
                    _overnightSessionDate = today;
                    _maxAbsExtensionPoints = 0.0;
                    ResetDailyRisk();
                    ClearActiveTradeState();
                }
            }
        }

        private void UpdateOvernightSession()
        {
            // Session reset now happens in CaptureSettlementIfHit when a
            // brand new daily settlement is recorded. Here we just track the
            // running extension peak.
            if (_settlementCaptured)
            {
                double ext = Math.Abs(Close[0] - _settlementPrice);
                if (ext > _maxAbsExtensionPoints) _maxAbsExtensionPoints = ext;
            }
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

        private void TryEnterReversion()
        {
            double extPoints = Close[0] - _settlementPrice;
            double absExt = Math.Abs(extPoints);
            if (absExt < MinPointsFromSettlement) return;
            if (absExt > MaxPointsFromSettlement) return;

            double rangeTicks = (High[0] - Low[0]) / TickSize;
            if (rangeTicks < MinBarRangeTicks) return;
            if (rangeTicks > MaxBarRangeTicks) return;
            double volFactor = VolumeFactor();
            if (volFactor > VolCeilingFactor) return;
            if (volFactor < VolMinFactor) return;
            double adxValue = _adx[0];
            if (adxValue > RangeAdxMax) return;

            // Drift confirmation: prior DriftConsecutiveBars closes also
            // beyond MinPointsFromSettlement on the SAME side.
            if (!DriftConfirmed(extPoints)) return;

            // Short fade: above settlement, RSI hot.
            if (extPoints > 0.0
                && EnableShort
                && _rsi[0] >= RsiShortMin
                && (!RequireRejection || RejectionDown(rangeTicks)))
            {
                EnterReversion(isLong: false);
                return;
            }
            if (extPoints < 0.0
                && EnableLong
                && _rsi[0] <= RsiLongMax
                && (!RequireRejection || RejectionUp(rangeTicks)))
            {
                EnterReversion(isLong: true);
                return;
            }
        }

        private bool DriftConfirmed(double currentExt)
        {
            if (DriftConsecutiveBars <= 0) return true;
            double sign = Math.Sign(currentExt);
            if (sign == 0) return false;
            for (int i = 1; i <= DriftConsecutiveBars; i++)
            {
                if (CurrentBar - i < 0) return false;
                double priorExt = Close[i] - _settlementPrice;
                if (Math.Sign(priorExt) != sign) return false;
                if (Math.Abs(priorExt) < MinPointsFromSettlement * 0.7) return false;
            }
            return true;
        }

        private bool RejectionDown(double rangeTicks)
        {
            if (rangeTicks <= 0.0) return false;
            double distFromHigh = (High[0] - Close[0]) / TickSize;
            return distFromHigh >= rangeTicks * RejectionFractionOfRange;
        }

        private bool RejectionUp(double rangeTicks)
        {
            if (rangeTicks <= 0.0) return false;
            double distFromLow = (Close[0] - Low[0]) / TickSize;
            return distFromLow >= rangeTicks * RejectionFractionOfRange;
        }

        private double VolumeFactor()
        {
            double baseVol = _volumeSma[0];
            if (baseVol <= 0.0) return 0.0;
            return Volume[0] / baseVol;
        }

        private void EnterReversion(bool isLong)
        {
            double stopPoints = ComputeStopPoints(isLong);
            int stopTicks = (int)Math.Round(stopPoints / TickSize);
            stopTicks = Math.Max(stopTicks, (int)Math.Round(MinStopPoints / TickSize));
            stopTicks = Math.Min(stopTicks, (int)Math.Round(MaxStopPoints / TickSize));

            // Target geometry: prefer settlement price (+- buffer) but never
            // accept less than MinTargetPoints. Compare with RR target.
            double settleTargetDistPoints = isLong
                ? (_settlementPrice - SettlementBufferPoints) - Close[0]
                : Close[0] - (_settlementPrice + SettlementBufferPoints);
            if (settleTargetDistPoints < MinTargetPoints) return;
            int targetTicksSettle = Math.Max(1, (int)Math.Round(settleTargetDistPoints / TickSize));
            int targetTicksRR = (int)Math.Round(stopTicks * RewardRiskRatio);
            int targetTicks;
            if (string.Equals(TargetMode, "RR", StringComparison.OrdinalIgnoreCase))
                targetTicks = targetTicksRR;
            else if (string.Equals(TargetMode, "Settlement", StringComparison.OrdinalIgnoreCase))
                targetTicks = targetTicksSettle;
            else // SettlementOrRR -> closer of the two
                targetTicks = Math.Min(targetTicksRR, targetTicksSettle);

            if (targetTicks * TickSize < MinTargetPoints) return;

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

        private double ComputeStopPoints(bool isLong)
        {
            double atrPts = _atr[0];
            double atrStopPts = atrPts * AtrStopMult;
            double geometryStopPts = isLong
                ? (Close[0] - Math.Min(Low[0], Low[1])) + StopBufferPoints
                : (Math.Max(High[0], High[1]) - Close[0]) + StopBufferPoints;
            double stop = Math.Max(geometryStopPts, atrStopPts);
            stop = Math.Max(stop, MinStopPoints);
            stop = Math.Min(stop, MaxStopPoints);
            return stop;
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
            if (qty < 1
                && byMargin >= 1
                && byUser >= 1
                && MaxContractsByCapital >= 1
                && (MaxDailyLossUsd <= 0.0 || contractRisk <= MaxDailyLossUsd))
            {
                qty = 1;
            }
            return Math.Max(0, qty);
        }

        private bool InTradeWindow()
        {
            int now = ToHHMM(Time[0]);
            return InWindow(now, TradeStartTime, TradeEndTime);
        }

        private bool ForceFlatDue()
        {
            int now = ToHHMM(Time[0]);
            // Force-flat applies inside the overnight envelope. Window may
            // straddle midnight; treat ForceFlatTime as belonging to the
            // night's tail.
            if (TradeStartTime <= TradeEndTime)
                return now >= ForceFlatTime && now < TradeStartTime;
            // Wrapping window: ForceFlatTime is between TradeEndTime and
            // TradeStartTime (next morning).
            return (now >= ForceFlatTime && now < TradeStartTime)
                || (TradeEndTime < ForceFlatTime && now >= ForceFlatTime);
        }

        private bool InWindow(int now, int start, int end)
        {
            if (start <= end) return now >= start && now <= end;
            return now >= start || now <= end;
        }

        private int ToHHMM(DateTime value) { return value.Hour * 100 + value.Minute; }

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

        private string TelemetrySignal(string side) { return GetType().Name + "." + side; }

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
            if (MaxDailyLossUsd > 0.0 && _sessionRealizedPnl <= -MaxDailyLossUsd) _sessionStopped = true;
            if (MaxWeeklyLossUsd > 0.0 && _weeklyRealizedPnl <= -MaxWeeklyLossUsd) _sessionStopped = true;
            if (MaxConsecutiveLosses > 0 && _consecutiveLosses >= MaxConsecutiveLosses) _sessionStopped = true;
            _lastProcessedTradeCount = total;
            ClearActiveTradeState();
        }

        #region Properties
        [NinjaScriptProperty] [Display(Name = "InstrumentName", GroupName = "01-Instrument", Order = 0)]
        public string InstrumentName { get; set; }
        [NinjaScriptProperty] [Display(Name = "ContractName", GroupName = "01-Instrument", Order = 1)]
        public string ContractName { get; set; }
        [NinjaScriptProperty] [Display(Name = "SessionTemplateName", GroupName = "01-Instrument", Order = 2)]
        public string SessionTemplateName { get; set; }
        [NinjaScriptProperty, Range(1, 3600)] [Display(Name = "BaseTimeframeSeconds", GroupName = "01-Instrument", Order = 3)]
        public int BaseTimeframeSeconds { get; set; }
        [NinjaScriptProperty] [Display(Name = "StartingCapital", GroupName = "02-Risk Profile", Order = 0)]
        public double StartingCapital { get; set; }
        [NinjaScriptProperty] [Display(Name = "IntradayOnly", GroupName = "02-Risk Profile", Order = 1)]
        public bool IntradayOnly { get; set; }
        [NinjaScriptProperty] [Display(Name = "ActiveMarginPerContract", GroupName = "02-Risk Profile", Order = 2)]
        public double ActiveMarginPerContract { get; set; }
        [NinjaScriptProperty] [Display(Name = "MaxContractsByCapital", GroupName = "02-Risk Profile", Order = 3)]
        public int MaxContractsByCapital { get; set; }
        [NinjaScriptProperty] [Display(Name = "InstrumentStatus", GroupName = "02-Risk Profile", Order = 4)]
        public string InstrumentStatus { get; set; }
        [NinjaScriptProperty] [Display(Name = "MarginSourceBroker", GroupName = "02-Risk Profile", Order = 5)]
        public string MarginSourceBroker { get; set; }
        [NinjaScriptProperty] [Display(Name = "EnableLong", GroupName = "03-Direction", Order = 0)]
        public bool EnableLong { get; set; }
        [NinjaScriptProperty] [Display(Name = "EnableShort", GroupName = "03-Direction", Order = 1)]
        public bool EnableShort { get; set; }
        [NinjaScriptProperty, Range(0, 2359)] [Display(Name = "TradeStartTime", GroupName = "04-Time", Order = 0)]
        public int TradeStartTime { get; set; }
        [NinjaScriptProperty, Range(0, 2359)] [Display(Name = "TradeEndTime", GroupName = "04-Time", Order = 1)]
        public int TradeEndTime { get; set; }
        [NinjaScriptProperty, Range(0, 2359)] [Display(Name = "ForceFlatTime", GroupName = "04-Time", Order = 2)]
        public int ForceFlatTime { get; set; }
        [NinjaScriptProperty, Range(0, 2359)] [Display(Name = "SettlementTimePT", GroupName = "04-Time", Order = 3)]
        public int SettlementTimePT { get; set; }
        [NinjaScriptProperty, Range(1.0, 500.0)] [Display(Name = "MinPointsFromSettlement", GroupName = "05-Signal", Order = 0)]
        public double MinPointsFromSettlement { get; set; }
        [NinjaScriptProperty, Range(1.0, 1000.0)] [Display(Name = "MaxPointsFromSettlement", GroupName = "05-Signal", Order = 1)]
        public double MaxPointsFromSettlement { get; set; }
        [NinjaScriptProperty, Range(0, 20)] [Display(Name = "DriftConsecutiveBars", GroupName = "05-Signal", Order = 2)]
        public int DriftConsecutiveBars { get; set; }
        [NinjaScriptProperty] [Display(Name = "RequireRejection", GroupName = "05-Signal", Order = 3)]
        public bool RequireRejection { get; set; }
        [NinjaScriptProperty, Range(0.0, 1.0)] [Display(Name = "RejectionFractionOfRange", GroupName = "05-Signal", Order = 4)]
        public double RejectionFractionOfRange { get; set; }
        [NinjaScriptProperty, Range(2, 100)] [Display(Name = "AdxPeriod", GroupName = "06-Confirm", Order = 0)]
        public int AdxPeriod { get; set; }
        [NinjaScriptProperty, Range(5.0, 80.0)] [Display(Name = "RangeAdxMax", GroupName = "06-Confirm", Order = 1)]
        public double RangeAdxMax { get; set; }
        [NinjaScriptProperty, Range(2, 100)] [Display(Name = "RsiPeriod", GroupName = "06-Confirm", Order = 2)]
        public int RsiPeriod { get; set; }
        [NinjaScriptProperty, Range(0.0, 100.0)] [Display(Name = "RsiShortMin", GroupName = "06-Confirm", Order = 3)]
        public double RsiShortMin { get; set; }
        [NinjaScriptProperty, Range(0.0, 100.0)] [Display(Name = "RsiLongMax", GroupName = "06-Confirm", Order = 4)]
        public double RsiLongMax { get; set; }
        [NinjaScriptProperty, Range(2, 200)] [Display(Name = "AtrPeriod", GroupName = "07-Filters", Order = 0)]
        public int AtrPeriod { get; set; }
        [NinjaScriptProperty, Range(2, 500)] [Display(Name = "VolumeSmaPeriod", GroupName = "07-Filters", Order = 1)]
        public int VolumeSmaPeriod { get; set; }
        [NinjaScriptProperty, Range(0.5, 10.0)] [Display(Name = "VolCeilingFactor", GroupName = "07-Filters", Order = 2)]
        public double VolCeilingFactor { get; set; }
        [NinjaScriptProperty, Range(0.0, 5.0)] [Display(Name = "VolMinFactor", GroupName = "07-Filters", Order = 3)]
        public double VolMinFactor { get; set; }
        [NinjaScriptProperty, Range(1, 1000)] [Display(Name = "MinBarRangeTicks", GroupName = "07-Filters", Order = 4)]
        public int MinBarRangeTicks { get; set; }
        [NinjaScriptProperty, Range(1, 2000)] [Display(Name = "MaxBarRangeTicks", GroupName = "07-Filters", Order = 5)]
        public int MaxBarRangeTicks { get; set; }
        [NinjaScriptProperty, Range(0.0, 50.0)] [Display(Name = "StopBufferPoints", GroupName = "08-Orders", Order = 0)]
        public double StopBufferPoints { get; set; }
        [NinjaScriptProperty, Range(0.25, 100.0)] [Display(Name = "MinStopPoints", GroupName = "08-Orders", Order = 1)]
        public double MinStopPoints { get; set; }
        [NinjaScriptProperty, Range(0.25, 200.0)] [Display(Name = "MaxStopPoints", GroupName = "08-Orders", Order = 2)]
        public double MaxStopPoints { get; set; }
        [NinjaScriptProperty, Range(0.0, 10.0)] [Display(Name = "AtrStopMult", GroupName = "08-Orders", Order = 3)]
        public double AtrStopMult { get; set; }
        [NinjaScriptProperty] [Display(Name = "TargetMode", GroupName = "08-Orders", Order = 4)]
        public string TargetMode { get; set; }
        [NinjaScriptProperty, Range(0.0, 100.0)] [Display(Name = "SettlementBufferPoints", GroupName = "08-Orders", Order = 5)]
        public double SettlementBufferPoints { get; set; }
        [NinjaScriptProperty, Range(0.1, 10.0)] [Display(Name = "RewardRiskRatio", GroupName = "08-Orders", Order = 6)]
        public double RewardRiskRatio { get; set; }
        [NinjaScriptProperty, Range(0.25, 200.0)] [Display(Name = "MinTargetPoints", GroupName = "08-Orders", Order = 7)]
        public double MinTargetPoints { get; set; }
        [NinjaScriptProperty, Range(0.0, 5.0)] [Display(Name = "MoveToBreakevenAtR", GroupName = "08-Orders", Order = 8)]
        public double MoveToBreakevenAtR { get; set; }
        [NinjaScriptProperty, Range(0, 50)] [Display(Name = "BreakevenPlusTicks", GroupName = "08-Orders", Order = 9)]
        public int BreakevenPlusTicks { get; set; }
        [NinjaScriptProperty] [Display(Name = "UseTrailingStop", GroupName = "08-Orders", Order = 10)]
        public bool UseTrailingStop { get; set; }
        [NinjaScriptProperty, Range(0.0, 5.0)] [Display(Name = "TrailAfterR", GroupName = "08-Orders", Order = 11)]
        public double TrailAfterR { get; set; }
        [NinjaScriptProperty, Range(1, 200)] [Display(Name = "TrailDistanceTicks", GroupName = "08-Orders", Order = 12)]
        public int TrailDistanceTicks { get; set; }
        [NinjaScriptProperty] [Display(Name = "UseTimeStop", GroupName = "08-Orders", Order = 13)]
        public bool UseTimeStop { get; set; }
        [NinjaScriptProperty, Range(1, 200)] [Display(Name = "TimeStopBars", GroupName = "08-Orders", Order = 14)]
        public int TimeStopBars { get; set; }
        [NinjaScriptProperty, Range(0.0, 2.0)] [Display(Name = "MinProgressR", GroupName = "08-Orders", Order = 15)]
        public double MinProgressR { get; set; }
        [NinjaScriptProperty, Range(0.01, 10.0)] [Display(Name = "RiskPerTradePct", GroupName = "09-Risk", Order = 0)]
        public double RiskPerTradePct { get; set; }
        [NinjaScriptProperty, Range(0, 100)] [Display(Name = "UserMaxContracts", GroupName = "09-Risk", Order = 1)]
        public int UserMaxContracts { get; set; }
        [NinjaScriptProperty, Range(0, 100)] [Display(Name = "MaxOpenPositions", GroupName = "09-Risk", Order = 2)]
        public int MaxOpenPositions { get; set; }
        [NinjaScriptProperty] [Display(Name = "MaxDailyLossUsd", GroupName = "09-Risk", Order = 3)]
        public double MaxDailyLossUsd { get; set; }
        [NinjaScriptProperty] [Display(Name = "MaxWeeklyLossUsd", GroupName = "09-Risk", Order = 4)]
        public double MaxWeeklyLossUsd { get; set; }
        [NinjaScriptProperty, Range(0, 100)] [Display(Name = "MaxTradesPerDay", GroupName = "09-Risk", Order = 5)]
        public int MaxTradesPerDay { get; set; }
        [NinjaScriptProperty, Range(0, 100)] [Display(Name = "HardMaxTradesPerDay", GroupName = "09-Risk", Order = 6)]
        public int HardMaxTradesPerDay { get; set; }
        [NinjaScriptProperty, Range(0, 20)] [Display(Name = "MaxConsecutiveLosses", GroupName = "09-Risk", Order = 7)]
        public int MaxConsecutiveLosses { get; set; }
        [NinjaScriptProperty, Range(0, 20)] [Display(Name = "PauseAfterConsecutiveLosses", GroupName = "09-Risk", Order = 8)]
        public int PauseAfterConsecutiveLosses { get; set; }
        [NinjaScriptProperty, Range(0, 480)] [Display(Name = "PauseMinutesAfterLosses", GroupName = "09-Risk", Order = 9)]
        public int PauseMinutesAfterLosses { get; set; }
        [NinjaScriptProperty] [Display(Name = "RoundTurnCommission", GroupName = "09-Risk", Order = 10)]
        public double RoundTurnCommission { get; set; }
        [NinjaScriptProperty, Range(0, 100)] [Display(Name = "SlippageTicks", GroupName = "09-Risk", Order = 11)]
        public int SlippageTicks { get; set; }
        #endregion
    }
}
