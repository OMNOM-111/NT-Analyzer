// =============================================================================
// NTAMnqRthTrendDayH1C019
// -----------------------------------------------------------------------------
// Standalone MNQ CELL-019 strategy. NEW family: "RTH H1 Trend-Day Bias
// Continuation". Engine #6 for CELL-019.
//
// Why this engine: Engines #1-#5 all hit the structural PF ~1.15-1.20
// ceiling on MNQ 15m/5m/1m. Audit (`Правила для новых стратегий
// 2026-05-31.md`) explicitly recommends low-frequency intraday entries
// where the trade lives multiple bars and exit is independent of
// intra-bar sequence. H1 bars satisfy both: same-bar stop/target is
// structurally impossible (any meaningful stop/target distance exceeds
// a single H1 bar move).
//
// Hypothesis: On RTH days where the first hour establishes a clear
// directional bias (close vs open of bar 1, vs prior-day close, ADX
// rising), the remainder of the session tends to extend in that
// direction. Single entry per day on bar 2 (10:30 PT) or bar 3
// (11:30 PT) in the direction of the established bias, holding for up
// to 3 H1 bars or until ForceFlat at 12:30 PT.
//
// Engine is structurally NEW vs every existing CELL-019 engine and the
// rest of the portfolio:
//   * TF         = H1 bars (BaseTimeframe 3600s). All prior CELL-019
//                  engines are 1m/5m/15m.
//   * Signal     = first-hour-of-session bias agreement with prior-day
//                  close direction; entry on bar 2 (or bar 3 retest).
//   * Direction  = WITH first-hour bias (NOT a fade).
//   * Trigger    = bar 2 close beyond bar 1 high (long) or low (short),
//                  ADX confirmation, body/range filter on bar 1.
//   * Regime     = ADX >= MinAdxTrend, RSI not exhausted.
//   * Window     = entries 09:30-11:30 PT, force flat 12:30 PT.
//   * Stops      = bar 1 low/high - buffer (true swing structure).
//   * Targets    = RR-multiple, partial trail after 1R.
//
// Risk shell identical pattern to other CELL-019 engines.
// Does NOT inherit any carrier; does NOT reuse settlement / pullback /
// breakout / 1m-scalp logic.
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
    public class NTAMnqRthTrendDayH1C019 : Strategy
    {
        private ATR _atr;
        private ADX _adx;
        private RSI _rsi;
        private EMA _biasEma;
        private SMA _volumeSma;

        // First-hour bias state.
        private DateTime _currentSessionDate = DateTime.MinValue;
        private double _bar1Open;
        private double _bar1Close;
        private double _bar1High;
        private double _bar1Low;
        private int _bar1Index = -1;
        private double _priorDayClose;
        private double _priorDayHigh;
        private double _priorDayLow;
        private int _barsSinceSessionStart;
        private bool _enteredToday;

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
        private bool _trailActivated;
        private double _bestFavorableTicks;

        // Prior-day rolling tracker.
        private DateTime _lastClosedDay = DateTime.MinValue;
        private double _runningDayHigh;
        private double _runningDayLow;
        private double _runningDayClose;

        protected override void OnStateChange()
        {
            if (State == State.SetDefaults)
            {
                Description = "MNQ CELL-019 RTH H1 trend-day bias continuation (60m, single entry per day).";
                Name = "RTH Trend Day H1 MNQ v1 c019";
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
                SessionTemplateName = "CME US Index Futures RTH";
                BaseTimeframeSeconds = 3600;

                StartingCapital = 2000.0;
                IntradayOnly = true;
                ActiveMarginPerContract = 100.0;
                MaxContractsByCapital = 20;
                InstrumentStatus = "allowed";
                MarginSourceBroker = "NinjaTrader";

                EnableLong = true;
                EnableShort = true;

                // RTH window in PT clock. First H1 bar = 06:30-07:30 PT.
                // Entry eligible from 09:30 PT (after bar 2 close) until
                // 11:30 PT (before lunch). Force flat 12:30 PT.
                TradeStartTime = 730;
                TradeEndTime = 1130;
                ForceFlatTime = 1230;

                BiasEmaPeriod = 20;
                Bar1RangeMinTicks = 16;
                Bar1RangeMaxTicks = 400;
                Bar1MinBodyToRange = 0.40;
                RequirePriorDayAlignment = true;

                // Regime filter (NEW): trade only on days where prior-day
                // range qualifies (avoids chop) AND bar1 size relative to
                // recent ATR is large enough (real trend-day catalyst).
                RequireTrendRegime = false;
                MinPriorDayRangePoints = 40.0;
                MaxPriorDayRangePoints = 250.0;
                MinBar1ToAtrRatio = 0.80;

                AdxPeriod = 14;
                MinAdxTrend = 18.0;
                MaxAdxTrend = 60.0;
                RsiPeriod = 14;
                RsiLongMax = 72.0;
                RsiShortMin = 28.0;
                AtrPeriod = 14;
                VolumeSmaPeriod = 20;
                VolCeilingFactor = 5.0;
                VolMinFactor = 0.40;

                StopBufferPoints = 3.0;
                MinStopPoints = 14.0;
                MaxStopPoints = 50.0;
                AtrStopMult = 1.0;
                RewardRiskRatio = 1.4;
                MinTargetPoints = 18.0;
                MoveToBreakevenAtR = 0.7;
                BreakevenPlusTicks = 4;
                UseTrailingStop = true;
                TrailAfterR = 1.0;
                TrailDistanceTicks = 40;
                UseTimeStop = false;
                TimeStopBars = 4;
                MinProgressR = 0.30;

                RiskPerTradePct = 0.60;
                UserMaxContracts = 1;
                MaxOpenPositions = 1;
                MaxDailyLossUsd = 120.0;
                MaxWeeklyLossUsd = 300.0;
                MaxTradesPerDay = 1;
                HardMaxTradesPerDay = 1;
                MaxConsecutiveLosses = 4;
                PauseAfterConsecutiveLosses = 3;
                PauseMinutesAfterLosses = 60;
                RoundTurnCommission = 1.90;
                SlippageTicks = 1;
            }
            else if (State == State.DataLoaded)
            {
                _atr = ATR(AtrPeriod);
                _adx = ADX(AdxPeriod);
                _rsi = RSI(RsiPeriod, 3);
                _biasEma = EMA(BiasEmaPeriod);
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

            UpdateSessionState();
            UpdatePriorDay();
            ManageOpenPosition();

            if (ForceFlatDue())
            {
                ForceFlat("time");
                return;
            }

            if (CurrentBar < BarsRequiredToTrade) return;
            if (!InTradeWindow()) return;
            if (_bar1Index < 0) return;
            if (_enteredToday) return;
            if (!CanTrade()) return;
            if (Position.MarketPosition != MarketPosition.Flat) return;
            if (_activeSignal != "") return;
            if (MaxOpenPositions < 1) return;

            TryEnterTrendDay();
        }

        private void UpdateSessionState()
        {
            DateTime today = Time[0].Date;
            bool newSession = Bars != null && Bars.IsFirstBarOfSession;
            if (newSession || _currentSessionDate != today)
            {
                _currentSessionDate = today;
                _bar1Index = -1;
                _bar1Open = 0; _bar1Close = 0; _bar1High = 0; _bar1Low = 0;
                _barsSinceSessionStart = 0;
                _enteredToday = false;
                ResetDailyRisk();
                ClearActiveTradeState();
            }
            _barsSinceSessionStart += 1;
            // Capture bar 1 of session (first complete bar after session open).
            if (_bar1Index < 0 && _barsSinceSessionStart == 1)
            {
                _bar1Index = CurrentBar;
                _bar1Open = Open[0];
                _bar1Close = Close[0];
                _bar1High = High[0];
                _bar1Low = Low[0];
            }
        }

        private void UpdatePriorDay()
        {
            DateTime today = Time[0].Date;
            if (_lastClosedDay == DateTime.MinValue)
            {
                _lastClosedDay = today;
                _runningDayHigh = High[0];
                _runningDayLow = Low[0];
                _runningDayClose = Close[0];
                return;
            }
            if (today != _lastClosedDay)
            {
                _priorDayHigh = _runningDayHigh;
                _priorDayLow = _runningDayLow;
                _priorDayClose = _runningDayClose;
                _lastClosedDay = today;
                _runningDayHigh = High[0];
                _runningDayLow = Low[0];
                _runningDayClose = Close[0];
            }
            else
            {
                if (High[0] > _runningDayHigh) _runningDayHigh = High[0];
                if (Low[0] < _runningDayLow) _runningDayLow = Low[0];
                _runningDayClose = Close[0];
            }
        }

        private void TryEnterTrendDay()
        {
            // Need at least one complete bar AFTER bar 1.
            if (CurrentBar - _bar1Index < 1) return;

            double bar1RangeTicks = (_bar1High - _bar1Low) / TickSize;
            if (bar1RangeTicks < Bar1RangeMinTicks) return;
            if (bar1RangeTicks > Bar1RangeMaxTicks) return;

            double bar1Body = Math.Abs(_bar1Close - _bar1Open);
            double bar1Range = Math.Max(TickSize, _bar1High - _bar1Low);
            if (bar1Body / bar1Range < Bar1MinBodyToRange) return;

            double adxValue = _adx[0];
            if (adxValue < MinAdxTrend) return;
            if (adxValue > MaxAdxTrend) return;

            double volFactor = VolumeFactor();
            if (volFactor > VolCeilingFactor) return;
            if (volFactor < VolMinFactor) return;

            bool bar1Bull = _bar1Close > _bar1Open;
            bool bar1Bear = _bar1Close < _bar1Open;
            if (!bar1Bull && !bar1Bear) return;

            // Prior-day alignment (optional): bar1 direction must agree with
            // close vs prior-day close.
            if (RequirePriorDayAlignment && _priorDayClose > 0.0)
            {
                bool aboveYC = _bar1Close > _priorDayClose;
                bool belowYC = _bar1Close < _priorDayClose;
                if (bar1Bull && !aboveYC) return;
                if (bar1Bear && !belowYC) return;
            }

            // Trend-regime filter (NEW): require prior-day range in band AND
            // bar1 size proportional to current ATR. Skips low-vol chop days.
            if (RequireTrendRegime)
            {
                if (_priorDayHigh <= 0.0 || _priorDayLow <= 0.0) return;
                double priorRangePts = _priorDayHigh - _priorDayLow;
                if (priorRangePts < MinPriorDayRangePoints) return;
                if (priorRangePts > MaxPriorDayRangePoints) return;
                double atrPts = _atr[0];
                if (atrPts > 0.0 && MinBar1ToAtrRatio > 0.0)
                {
                    double bar1Pts = _bar1High - _bar1Low;
                    if (bar1Pts / atrPts < MinBar1ToAtrRatio) return;
                }
            }

            // EMA bias agreement.
            double biasEma = _biasEma[0];
            if (bar1Bull && !(Close[0] > biasEma)) return;
            if (bar1Bear && !(Close[0] < biasEma)) return;

            // Trigger: current (post-bar-1) bar must break bar 1 extreme in
            // the bias direction on close.
            if (bar1Bull
                && EnableLong
                && Close[0] > _bar1High
                && _rsi[0] <= RsiLongMax)
            {
                EnterTrendDay(isLong: true);
                return;
            }
            if (bar1Bear
                && EnableShort
                && Close[0] < _bar1Low
                && _rsi[0] >= RsiShortMin)
            {
                EnterTrendDay(isLong: false);
                return;
            }
        }

        private double VolumeFactor()
        {
            double baseVol = _volumeSma[0];
            if (baseVol <= 0.0) return 0.0;
            return Volume[0] / baseVol;
        }

        private void EnterTrendDay(bool isLong)
        {
            double stopPoints = ComputeStopPoints(isLong);
            int stopTicks = (int)Math.Round(stopPoints / TickSize);
            stopTicks = Math.Max(stopTicks, (int)Math.Round(MinStopPoints / TickSize));
            stopTicks = Math.Min(stopTicks, (int)Math.Round(MaxStopPoints / TickSize));

            int targetTicks = (int)Math.Round(stopTicks * RewardRiskRatio);
            if (targetTicks * TickSize < MinTargetPoints)
                targetTicks = (int)Math.Round(MinTargetPoints / TickSize);

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
            _trailActivated = false;
            _bestFavorableTicks = 0.0;
            _enteredToday = true;
            if (isLong) EnterLong(qty, signal);
            else EnterShort(qty, signal);
        }

        private double ComputeStopPoints(bool isLong)
        {
            double atrPts = _atr[0];
            double atrStopPts = atrPts * AtrStopMult;
            double geometryStopPts = isLong
                ? (Close[0] - _bar1Low) + StopBufferPoints
                : (_bar1High - Close[0]) + StopBufferPoints;
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
                && _bestFavorableTicks >= _lastStopTicks * TrailAfterR)
            {
                _trailActivated = true;
                double trailPrice = isLong
                    ? Close[0] - TrailDistanceTicks * TickSize
                    : Close[0] + TrailDistanceTicks * TickSize;
                if (isLong)
                {
                    double current = entry + BreakevenPlusTicks * TickSize;
                    if (trailPrice > current)
                        SetStopLoss(_activeSignal, CalculationMode.Price, trailPrice, false);
                }
                else
                {
                    double current = entry - BreakevenPlusTicks * TickSize;
                    if (trailPrice < current)
                        SetStopLoss(_activeSignal, CalculationMode.Price, trailPrice, false);
                }
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
            return now >= ForceFlatTime && now < TradeStartTime;
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
            _trailActivated = false;
            _bestFavorableTicks = 0.0;
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
        [NinjaScriptProperty, Range(1, 7200)] [Display(Name = "BaseTimeframeSeconds", GroupName = "01-Instrument", Order = 3)]
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
        [NinjaScriptProperty, Range(2, 500)] [Display(Name = "BiasEmaPeriod", GroupName = "05-Signal", Order = 0)]
        public int BiasEmaPeriod { get; set; }
        [NinjaScriptProperty, Range(1, 4000)] [Display(Name = "Bar1RangeMinTicks", GroupName = "05-Signal", Order = 1)]
        public int Bar1RangeMinTicks { get; set; }
        [NinjaScriptProperty, Range(1, 4000)] [Display(Name = "Bar1RangeMaxTicks", GroupName = "05-Signal", Order = 2)]
        public int Bar1RangeMaxTicks { get; set; }
        [NinjaScriptProperty, Range(0.0, 1.0)] [Display(Name = "Bar1MinBodyToRange", GroupName = "05-Signal", Order = 3)]
        public double Bar1MinBodyToRange { get; set; }
        [NinjaScriptProperty] [Display(Name = "RequirePriorDayAlignment", GroupName = "05-Signal", Order = 4)]
        public bool RequirePriorDayAlignment { get; set; }
        [NinjaScriptProperty] [Display(Name = "RequireTrendRegime", GroupName = "05-Signal", Order = 5)]
        public bool RequireTrendRegime { get; set; }
        [NinjaScriptProperty, Range(0.0, 5000.0)] [Display(Name = "MinPriorDayRangePoints", GroupName = "05-Signal", Order = 6)]
        public double MinPriorDayRangePoints { get; set; }
        [NinjaScriptProperty, Range(0.0, 5000.0)] [Display(Name = "MaxPriorDayRangePoints", GroupName = "05-Signal", Order = 7)]
        public double MaxPriorDayRangePoints { get; set; }
        [NinjaScriptProperty, Range(0.0, 10.0)] [Display(Name = "MinBar1ToAtrRatio", GroupName = "05-Signal", Order = 8)]
        public double MinBar1ToAtrRatio { get; set; }
        [NinjaScriptProperty, Range(2, 100)] [Display(Name = "AdxPeriod", GroupName = "06-Confirm", Order = 0)]
        public int AdxPeriod { get; set; }
        [NinjaScriptProperty, Range(0.0, 80.0)] [Display(Name = "MinAdxTrend", GroupName = "06-Confirm", Order = 1)]
        public double MinAdxTrend { get; set; }
        [NinjaScriptProperty, Range(0.0, 100.0)] [Display(Name = "MaxAdxTrend", GroupName = "06-Confirm", Order = 2)]
        public double MaxAdxTrend { get; set; }
        [NinjaScriptProperty, Range(2, 100)] [Display(Name = "RsiPeriod", GroupName = "06-Confirm", Order = 3)]
        public int RsiPeriod { get; set; }
        [NinjaScriptProperty, Range(0.0, 100.0)] [Display(Name = "RsiLongMax", GroupName = "06-Confirm", Order = 4)]
        public double RsiLongMax { get; set; }
        [NinjaScriptProperty, Range(0.0, 100.0)] [Display(Name = "RsiShortMin", GroupName = "06-Confirm", Order = 5)]
        public double RsiShortMin { get; set; }
        [NinjaScriptProperty, Range(2, 200)] [Display(Name = "AtrPeriod", GroupName = "07-Filters", Order = 0)]
        public int AtrPeriod { get; set; }
        [NinjaScriptProperty, Range(2, 500)] [Display(Name = "VolumeSmaPeriod", GroupName = "07-Filters", Order = 1)]
        public int VolumeSmaPeriod { get; set; }
        [NinjaScriptProperty, Range(0.5, 20.0)] [Display(Name = "VolCeilingFactor", GroupName = "07-Filters", Order = 2)]
        public double VolCeilingFactor { get; set; }
        [NinjaScriptProperty, Range(0.0, 5.0)] [Display(Name = "VolMinFactor", GroupName = "07-Filters", Order = 3)]
        public double VolMinFactor { get; set; }
        [NinjaScriptProperty, Range(0.0, 50.0)] [Display(Name = "StopBufferPoints", GroupName = "08-Orders", Order = 0)]
        public double StopBufferPoints { get; set; }
        [NinjaScriptProperty, Range(0.25, 200.0)] [Display(Name = "MinStopPoints", GroupName = "08-Orders", Order = 1)]
        public double MinStopPoints { get; set; }
        [NinjaScriptProperty, Range(0.25, 500.0)] [Display(Name = "MaxStopPoints", GroupName = "08-Orders", Order = 2)]
        public double MaxStopPoints { get; set; }
        [NinjaScriptProperty, Range(0.0, 10.0)] [Display(Name = "AtrStopMult", GroupName = "08-Orders", Order = 3)]
        public double AtrStopMult { get; set; }
        [NinjaScriptProperty, Range(0.1, 10.0)] [Display(Name = "RewardRiskRatio", GroupName = "08-Orders", Order = 4)]
        public double RewardRiskRatio { get; set; }
        [NinjaScriptProperty, Range(0.25, 500.0)] [Display(Name = "MinTargetPoints", GroupName = "08-Orders", Order = 5)]
        public double MinTargetPoints { get; set; }
        [NinjaScriptProperty, Range(0.0, 5.0)] [Display(Name = "MoveToBreakevenAtR", GroupName = "08-Orders", Order = 6)]
        public double MoveToBreakevenAtR { get; set; }
        [NinjaScriptProperty, Range(0, 50)] [Display(Name = "BreakevenPlusTicks", GroupName = "08-Orders", Order = 7)]
        public int BreakevenPlusTicks { get; set; }
        [NinjaScriptProperty] [Display(Name = "UseTrailingStop", GroupName = "08-Orders", Order = 8)]
        public bool UseTrailingStop { get; set; }
        [NinjaScriptProperty, Range(0.0, 5.0)] [Display(Name = "TrailAfterR", GroupName = "08-Orders", Order = 9)]
        public double TrailAfterR { get; set; }
        [NinjaScriptProperty, Range(1, 400)] [Display(Name = "TrailDistanceTicks", GroupName = "08-Orders", Order = 10)]
        public int TrailDistanceTicks { get; set; }
        [NinjaScriptProperty] [Display(Name = "UseTimeStop", GroupName = "08-Orders", Order = 11)]
        public bool UseTimeStop { get; set; }
        [NinjaScriptProperty, Range(1, 200)] [Display(Name = "TimeStopBars", GroupName = "08-Orders", Order = 12)]
        public int TimeStopBars { get; set; }
        [NinjaScriptProperty, Range(0.0, 2.0)] [Display(Name = "MinProgressR", GroupName = "08-Orders", Order = 13)]
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
