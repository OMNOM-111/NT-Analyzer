// =============================================================================
// NTAMnqRthVwapPullbackC019
// -----------------------------------------------------------------------------
// Standalone MNQ CELL-019 strategy. NEW family: "RTH VWAP-Pullback
// Continuation". Engine #5 for CELL-019.
//
// Why this engine: Engines #1-#4 (1m scalp, overnight settlement reversion,
// overnight settlement breakout, RTH settlement breakout) all failed
// promotion gates. Common failure pattern on MNQ index futures: 15m
// breakout-style entries suffer from a high same-bar stop/target rate
// (62-71% in audit), inflating backtest PF but collapsing on demo. Per
// project rules `Правила для новых стратегий 2026-05-31.md`, candidate
// must have same-bar ratio <= 50% to be promotable.
//
// Hypothesis: The structural edge available on MNQ RTH 15m is a
// MEAN-REVERSION entry inside an established intraday trend: when price
// extends away from session VWAP, ADX-confirmed trend is intact, and price
// PULLS BACK to or through VWAP, the next bar that closes back in the
// trend direction tends to continue. Stop sits past prior swing low (or
// high for short), which is structurally further than current bar range,
// so target taken on a later bar rather than within the entry bar.
//
// Engine is structurally NEW vs every existing CELL-019 engine and the
// rest of the portfolio:
//   * Signal     = pullback-to-VWAP rejection (NOT breakout, NOT
//                  settlement-distance, NOT Donchian, NOT carrier).
//   * Direction  = WITH the intraday trend (EMA50 slope + VWAP slope).
//   * Trigger    = current bar closes back in trend direction after touch
//                  to VWAP within PullbackToleranceTicks.
//   * Regime     = ADX >= MinAdxTrend (trending, but NOT extreme), RSI not
//                  exhausted on entry side.
//   * Window     = 07:00 PT - 11:30 PT RTH (post-open establishment phase
//                  + lunch fade; force-flat 12:30 PT).
//   * Stops      = max(prior N-bar swing low - buffer, ATR*mult,
//                  MinStopPoints) capped at MaxStopPoints.
//   * Targets    = RR-multiple of stop, breakeven after 0.8R, trail after
//                  1.2R. Time-stop after TimeStopBars if no progress.
//   * VWAP       = session-cumulative (reset on Bars.IsFirstBarOfSession).
//
// Risk shell identical pattern to other CELL-019 engines.
// Does NOT inherit any carrier; does NOT reuse settlement / breakout /
// 1m-scalp logic.
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
    public class NTAMnqRthVwapPullbackC019 : Strategy
    {
        private ATR _atr;
        private ADX _adx;
        private RSI _rsi;
        private EMA _biasEma;
        private SMA _volumeSma;

        // Session VWAP state (reset on first bar of session).
        private double _cumTpv;
        private double _cumVol;
        private double _vwap;
        private double[] _vwapHistory;
        private int _vwapHistoryCount;
        private DateTime _currentSessionDate = DateTime.MinValue;

        // Pullback state.
        private int _lastTouchBar = -1;  // bar index of most recent VWAP touch
        private int _lastTouchSide = 0;  // +1 = touched from above (long bias), -1 = below

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

        protected override void OnStateChange()
        {
            if (State == State.SetDefaults)
            {
                Description = "MNQ CELL-019 RTH VWAP-pullback continuation (15m, mean-revert entry inside intraday trend).";
                Name = "RTH VWAP Pullback MNQ 15m v1 c019";
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
                BarsRequiredToTrade = 60;
                IsInstantiatedOnEachOptimizationIteration = true;

                InstrumentName = "MNQ";
                ContractName = "MNQ 06-26";
                SessionTemplateName = "CME US Index Futures RTH";
                BaseTimeframeSeconds = 900;

                StartingCapital = 2000.0;
                IntradayOnly = true;
                ActiveMarginPerContract = 100.0;
                MaxContractsByCapital = 20;
                InstrumentStatus = "allowed";
                MarginSourceBroker = "NinjaTrader";

                EnableLong = true;
                EnableShort = true;

                // RTH window in PT clock (CME index RTH: 06:30 PT open).
                // Wait 30m after cash open for VWAP to stabilize and trend
                // to establish. End 11:30 PT to avoid lunch chop. Force-flat
                // at 12:30 PT (1h before settlement print).
                TradeStartTime = 700;
                TradeEndTime = 1130;
                ForceFlatTime = 1230;

                BiasEmaPeriod = 50;
                VwapSlopeBars = 6;
                PullbackToleranceTicks = 4;
                PullbackLookbackBars = 6;
                SwingLookback = 5;

                AdxPeriod = 14;
                MinAdxTrend = 20.0;
                MaxAdxTrend = 45.0;
                RsiPeriod = 14;
                RsiLongMax = 70.0;
                RsiShortMin = 30.0;
                AtrPeriod = 14;
                VolumeSmaPeriod = 20;
                VolCeilingFactor = 5.0;
                VolMinFactor = 0.40;
                MinBarRangeTicks = 4;
                MaxBarRangeTicks = 600;
                MinBodyToRange = 0.40;

                StopBufferPoints = 2.0;
                MinStopPoints = 8.0;
                MaxStopPoints = 24.0;
                AtrStopMult = 1.0;
                RewardRiskRatio = 1.5;
                MinTargetPoints = 10.0;
                MoveToBreakevenAtR = 0.8;
                BreakevenPlusTicks = 2;
                UseTrailingStop = true;
                TrailAfterR = 1.2;
                TrailDistanceTicks = 20;
                UseTimeStop = true;
                TimeStopBars = 6;
                MinProgressR = 0.30;

                RiskPerTradePct = 0.60;
                UserMaxContracts = 1;
                MaxOpenPositions = 1;
                MaxDailyLossUsd = 100.0;
                MaxWeeklyLossUsd = 250.0;
                MaxTradesPerDay = 2;
                HardMaxTradesPerDay = 3;
                MaxConsecutiveLosses = 4;
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
                _biasEma = EMA(BiasEmaPeriod);
                _volumeSma = SMA(Volume, VolumeSmaPeriod);
                _vwapHistory = new double[Math.Max(64, VwapSlopeBars + 8)];
                _vwapHistoryCount = 0;

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

            UpdateSessionVwap();
            UpdatePullbackState();
            ManageOpenPosition();

            if (ForceFlatDue())
            {
                ForceFlat("time");
                return;
            }

            if (CurrentBar < BarsRequiredToTrade) return;
            if (!InTradeWindow()) return;
            if (_cumVol <= 0.0) return;
            if (!CanTrade()) return;
            if (Position.MarketPosition != MarketPosition.Flat) return;
            if (_activeSignal != "") return;
            if (MaxOpenPositions < 1) return;

            TryEnterPullback();
        }

        private void UpdateSessionVwap()
        {
            DateTime today = Time[0].Date;
            bool newSession = Bars != null && Bars.IsFirstBarOfSession;
            if (newSession || _currentSessionDate != today)
            {
                _cumTpv = 0.0;
                _cumVol = 0.0;
                _vwap = 0.0;
                _vwapHistoryCount = 0;
                _lastTouchBar = -1;
                _lastTouchSide = 0;
                _currentSessionDate = today;
                ResetDailyRisk();
                ClearActiveTradeState();
            }
            double tp = (High[0] + Low[0] + Close[0]) / 3.0;
            double v = Volume[0];
            if (v > 0.0)
            {
                _cumTpv += tp * v;
                _cumVol += v;
                _vwap = _cumTpv / _cumVol;
            }
            // shift history
            for (int i = _vwapHistory.Length - 1; i > 0; i--) _vwapHistory[i] = _vwapHistory[i - 1];
            _vwapHistory[0] = _vwap;
            if (_vwapHistoryCount < _vwapHistory.Length) _vwapHistoryCount++;
        }

        private void UpdatePullbackState()
        {
            if (_cumVol <= 0.0) return;
            // Touch event: bar's range crosses VWAP. Direction = side of CLOSE.
            bool crossed = Low[0] <= _vwap && High[0] >= _vwap;
            if (crossed)
            {
                _lastTouchBar = CurrentBar;
                _lastTouchSide = Close[0] >= _vwap ? 1 : -1;
            }
        }

        private void TryEnterPullback()
        {
            if (_lastTouchBar < 0) return;
            int barsSinceTouch = CurrentBar - _lastTouchBar;
            if (barsSinceTouch > PullbackLookbackBars) return;
            if (barsSinceTouch < 0) return;

            double rangeTicks = (High[0] - Low[0]) / TickSize;
            if (rangeTicks < MinBarRangeTicks) return;
            if (rangeTicks > MaxBarRangeTicks) return;
            double volFactor = VolumeFactor();
            if (volFactor > VolCeilingFactor) return;
            if (volFactor < VolMinFactor) return;
            double adxValue = _adx[0];
            if (adxValue < MinAdxTrend) return;
            if (adxValue > MaxAdxTrend) return;
            double body = Math.Abs(Close[0] - Open[0]);
            double rangePts = High[0] - Low[0];
            if (rangePts > 0.0 && body / rangePts < MinBodyToRange) return;

            double biasEma = _biasEma[0];
            double vwapPast = VwapHistoryAt(VwapSlopeBars);
            bool vwapUp = vwapPast > 0.0 && _vwap > vwapPast;
            bool vwapDn = vwapPast > 0.0 && _vwap < vwapPast;
            bool emaUp = Close[0] > biasEma && biasEma > _biasEma[Math.Min(VwapSlopeBars, CurrentBar)];
            bool emaDn = Close[0] < biasEma && biasEma < _biasEma[Math.Min(VwapSlopeBars, CurrentBar)];

            double tolPts = PullbackToleranceTicks * TickSize;

            // LONG: bullish bias, recent touch from above (or through), current
            // bar closes above VWAP and above its open, RSI not overbought.
            if (EnableLong && vwapUp && emaUp
                && Low[0] <= _vwap + tolPts
                && Close[0] > _vwap
                && Close[0] > Open[0]
                && _rsi[0] <= RsiLongMax
                && _lastTouchSide >= 0)
            {
                EnterPullback(isLong: true);
                return;
            }

            // SHORT: bearish bias, recent touch from below (or through), current
            // bar closes below VWAP and below its open, RSI not oversold.
            if (EnableShort && vwapDn && emaDn
                && High[0] >= _vwap - tolPts
                && Close[0] < _vwap
                && Close[0] < Open[0]
                && _rsi[0] >= RsiShortMin
                && _lastTouchSide <= 0)
            {
                EnterPullback(isLong: false);
                return;
            }
        }

        private double VwapHistoryAt(int barsBack)
        {
            int idx = Math.Min(barsBack, _vwapHistoryCount - 1);
            if (idx < 0) return 0.0;
            return _vwapHistory[idx];
        }

        private double VolumeFactor()
        {
            double baseVol = _volumeSma[0];
            if (baseVol <= 0.0) return 0.0;
            return Volume[0] / baseVol;
        }

        private void EnterPullback(bool isLong)
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
            if (isLong) EnterLong(qty, signal);
            else EnterShort(qty, signal);
        }

        private double ComputeStopPoints(bool isLong)
        {
            double atrPts = _atr[0];
            double atrStopPts = atrPts * AtrStopMult;
            // Swing low/high over last SwingLookback bars (incl. current).
            int lb = Math.Max(2, SwingLookback);
            double swingLow = Low[0];
            double swingHigh = High[0];
            for (int i = 1; i <= Math.Min(lb, CurrentBar); i++)
            {
                if (Low[i] < swingLow) swingLow = Low[i];
                if (High[i] > swingHigh) swingHigh = High[i];
            }
            double geometryStopPts = isLong
                ? (Close[0] - swingLow) + StopBufferPoints
                : (swingHigh - Close[0]) + StopBufferPoints;
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
        [NinjaScriptProperty, Range(2, 500)] [Display(Name = "BiasEmaPeriod", GroupName = "05-Signal", Order = 0)]
        public int BiasEmaPeriod { get; set; }
        [NinjaScriptProperty, Range(1, 100)] [Display(Name = "VwapSlopeBars", GroupName = "05-Signal", Order = 1)]
        public int VwapSlopeBars { get; set; }
        [NinjaScriptProperty, Range(0, 100)] [Display(Name = "PullbackToleranceTicks", GroupName = "05-Signal", Order = 2)]
        public int PullbackToleranceTicks { get; set; }
        [NinjaScriptProperty, Range(1, 50)] [Display(Name = "PullbackLookbackBars", GroupName = "05-Signal", Order = 3)]
        public int PullbackLookbackBars { get; set; }
        [NinjaScriptProperty, Range(2, 50)] [Display(Name = "SwingLookback", GroupName = "05-Signal", Order = 4)]
        public int SwingLookback { get; set; }
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
        [NinjaScriptProperty, Range(1, 1000)] [Display(Name = "MinBarRangeTicks", GroupName = "07-Filters", Order = 4)]
        public int MinBarRangeTicks { get; set; }
        [NinjaScriptProperty, Range(1, 2000)] [Display(Name = "MaxBarRangeTicks", GroupName = "07-Filters", Order = 5)]
        public int MaxBarRangeTicks { get; set; }
        [NinjaScriptProperty, Range(0.0, 1.0)] [Display(Name = "MinBodyToRange", GroupName = "07-Filters", Order = 6)]
        public double MinBodyToRange { get; set; }
        [NinjaScriptProperty, Range(0.0, 50.0)] [Display(Name = "StopBufferPoints", GroupName = "08-Orders", Order = 0)]
        public double StopBufferPoints { get; set; }
        [NinjaScriptProperty, Range(0.25, 100.0)] [Display(Name = "MinStopPoints", GroupName = "08-Orders", Order = 1)]
        public double MinStopPoints { get; set; }
        [NinjaScriptProperty, Range(0.25, 200.0)] [Display(Name = "MaxStopPoints", GroupName = "08-Orders", Order = 2)]
        public double MaxStopPoints { get; set; }
        [NinjaScriptProperty, Range(0.0, 10.0)] [Display(Name = "AtrStopMult", GroupName = "08-Orders", Order = 3)]
        public double AtrStopMult { get; set; }
        [NinjaScriptProperty, Range(0.1, 10.0)] [Display(Name = "RewardRiskRatio", GroupName = "08-Orders", Order = 4)]
        public double RewardRiskRatio { get; set; }
        [NinjaScriptProperty, Range(0.25, 200.0)] [Display(Name = "MinTargetPoints", GroupName = "08-Orders", Order = 5)]
        public double MinTargetPoints { get; set; }
        [NinjaScriptProperty, Range(0.0, 5.0)] [Display(Name = "MoveToBreakevenAtR", GroupName = "08-Orders", Order = 6)]
        public double MoveToBreakevenAtR { get; set; }
        [NinjaScriptProperty, Range(0, 50)] [Display(Name = "BreakevenPlusTicks", GroupName = "08-Orders", Order = 7)]
        public int BreakevenPlusTicks { get; set; }
        [NinjaScriptProperty] [Display(Name = "UseTrailingStop", GroupName = "08-Orders", Order = 8)]
        public bool UseTrailingStop { get; set; }
        [NinjaScriptProperty, Range(0.0, 5.0)] [Display(Name = "TrailAfterR", GroupName = "08-Orders", Order = 9)]
        public double TrailAfterR { get; set; }
        [NinjaScriptProperty, Range(1, 200)] [Display(Name = "TrailDistanceTicks", GroupName = "08-Orders", Order = 10)]
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
