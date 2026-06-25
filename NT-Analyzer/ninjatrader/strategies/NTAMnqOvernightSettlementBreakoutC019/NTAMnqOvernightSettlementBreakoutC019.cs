// =============================================================================
// NTAMnqOvernightSettlementBreakoutC019
// -----------------------------------------------------------------------------
// Standalone MNQ CELL-019 strategy. NEW family: "Overnight Settlement
// Breakout / Momentum Continuation". Engine #4 for CELL-019.
//
// Why this engine: Engine #3 (Overnight Settlement Reversion) was deployed,
// daily-reset bug fixed, and the full 24-variant smoke sweep on MNQ 2025
// returned uniformly negative results (all variants PF 0.76-0.82, net
// approximately -$1900). PF<1 across the entire param grid implies the
// inverse signal (breakout / momentum AWAY from prior settlement) has a
// positive structural edge in 2025 MNQ overnight tape.
//
// Hypothesis: After the 13:00 PT RTH settlement print, the overnight
// Globex/Asia/Europe tape often initiates a directional drive on news
// (Asia open, European pre-cash) that pushes price progressively further
// away from prior settlement. A 15-minute breakout engine that buys
// strength / sells weakness when price is BOTH extended from settlement
// AND breaks a recent N-bar high/low in a trending regime should capture
// this drift before the NY pre-cash mean-reversion phase begins.
//
// Engine is structurally NEW vs every existing strategy (including #3
// Reversion sibling):
//   * Direction = WITH the extension (long above settlement, short below).
//   * Trigger  = N-bar Donchian breakout in the extension direction.
//   * Regime   = ADX >= MinAdxTrend (trending), opposite of reversion.
//   * RSI      = confirms trend (RSI >= long_min for long, <= short_max
//                for short).
//   * Window   = 16:00 PT - 04:00 PT (wraps midnight; covers Asia drive
//                + European pre-open). Distinct from reversion window
//                tail and ALL other intraday engines.
//   * Targets  = RR-multiple of stop (fat tail 2.0-3.0). Trail after
//                TrailAfterR. NO settlement-anchor target (trends extend
//                past settlement, not back to it).
//   * Stops    = ATR-based with min/max points cap.
//
// Risk shell identical pattern to other CELL-019 engines.
// Does NOT inherit any carrier; does NOT reuse squeeze / VWAP-fade /
// settlement-reversion / liquidity-sweep / open-pressure / opening-drive
// / pre-cash-compression / session-edge / OrbRetest signal logic.
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
    public class NTAMnqOvernightSettlementBreakoutC019 : Strategy
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
        private bool _trailActivated;
        private double _bestFavorableTicks;

        protected override void OnStateChange()
        {
            if (State == State.SetDefaults)
            {
                Description = "MNQ CELL-019 overnight settlement breakout (15m, momentum continuation past prior RTH settlement).";
                Name = "Overnight Settlement Breakout MNQ 15m v1 c019";
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

                // Overnight window in PT clock. Wraps midnight: starts 16:00 PT
                // after RTH close, ends 04:00 PT before NY pre-cash phase. This
                // covers Asia drive + European pre-open momentum.
                TradeStartTime = 1600;
                TradeEndTime = 400;
                ForceFlatTime = 430;
                SettlementTimePT = 1300;

                MinPointsFromSettlement = 6.0;
                MaxPointsFromSettlement = 120.0;
                BreakoutLookback = 6;
                AdxPeriod = 14;
                MinAdxTrend = 20.0;
                RsiPeriod = 14;
                RsiLongMin = 52.0;
                RsiShortMax = 48.0;
                AtrPeriod = 14;
                VolumeSmaPeriod = 20;
                VolCeilingFactor = 4.00;
                VolMinFactor = 0.40;
                MinBarRangeTicks = 6;
                MaxBarRangeTicks = 400;

                StopBufferPoints = 2.0;
                MinStopPoints = 6.0;
                MaxStopPoints = 18.0;
                AtrStopMult = 1.5;
                RewardRiskRatio = 2.0;
                MinTargetPoints = 8.0;
                MoveToBreakevenAtR = 0.8;
                BreakevenPlusTicks = 2;
                UseTrailingStop = true;
                TrailAfterR = 1.2;
                TrailDistanceTicks = 16;
                UseTimeStop = true;
                TimeStopBars = 12;
                MinProgressR = 0.40;

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

            TryEnterBreakout();
        }

        private void CaptureSettlementIfHit()
        {
            int barHHMM = ToHHMM(Time[0]);
            int settleHHMM = SettlementTimePT;
            if (barHHMM <= settleHHMM && barHHMM >= Math.Max(1230, settleHHMM - 60))
            {
                _settlementPrice = Close[0];
                _settlementCaptured = true;
                DateTime today = Time[0].Date;
                if (_lastSettlementDate != today)
                {
                    // New RTH settlement -> fresh overnight session.
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

        private void TryEnterBreakout()
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
            if (adxValue < MinAdxTrend) return;

            // Donchian breakout in the extension direction over the last
            // BreakoutLookback bars. Use HIGHS / LOWS of bars [1..N], not
            // including current bar.
            if (BreakoutLookback < 1) return;
            if (CurrentBar < BreakoutLookback + 2) return;
            double hi = double.MinValue;
            double lo = double.MaxValue;
            for (int i = 1; i <= BreakoutLookback; i++)
            {
                if (High[i] > hi) hi = High[i];
                if (Low[i] < lo) lo = Low[i];
            }

            // Long breakout: above settlement, current close breaks N-bar high,
            // RSI confirms momentum.
            if (extPoints > 0.0
                && EnableLong
                && Close[0] > hi
                && _rsi[0] >= RsiLongMin)
            {
                EnterBreakout(isLong: true);
                return;
            }
            // Short breakout: below settlement, current close breaks N-bar low.
            if (extPoints < 0.0
                && EnableShort
                && Close[0] < lo
                && _rsi[0] <= RsiShortMax)
            {
                EnterBreakout(isLong: false);
                return;
            }
        }

        private double VolumeFactor()
        {
            double baseVol = _volumeSma[0];
            if (baseVol <= 0.0) return 0.0;
            return Volume[0] / baseVol;
        }

        private void EnterBreakout(bool isLong)
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
                && _bestFavorableTicks >= _lastStopTicks * TrailAfterR)
            {
                _trailActivated = true;
                double trailPrice = isLong
                    ? Close[0] - TrailDistanceTicks * TickSize
                    : Close[0] + TrailDistanceTicks * TickSize;
                // Only ratchet in favorable direction.
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
            // Wrapping window: ForceFlatTime is between TradeEndTime and
            // TradeStartTime (we want to flatten at/after the end-of-night
            // boundary, before the start-of-next-night boundary).
            if (TradeStartTime <= TradeEndTime)
                return now >= ForceFlatTime && now < TradeStartTime;
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
        [NinjaScriptProperty, Range(1, 50)] [Display(Name = "BreakoutLookback", GroupName = "05-Signal", Order = 2)]
        public int BreakoutLookback { get; set; }
        [NinjaScriptProperty, Range(2, 100)] [Display(Name = "AdxPeriod", GroupName = "06-Confirm", Order = 0)]
        public int AdxPeriod { get; set; }
        [NinjaScriptProperty, Range(0.0, 80.0)] [Display(Name = "MinAdxTrend", GroupName = "06-Confirm", Order = 1)]
        public double MinAdxTrend { get; set; }
        [NinjaScriptProperty, Range(2, 100)] [Display(Name = "RsiPeriod", GroupName = "06-Confirm", Order = 2)]
        public int RsiPeriod { get; set; }
        [NinjaScriptProperty, Range(0.0, 100.0)] [Display(Name = "RsiLongMin", GroupName = "06-Confirm", Order = 3)]
        public double RsiLongMin { get; set; }
        [NinjaScriptProperty, Range(0.0, 100.0)] [Display(Name = "RsiShortMax", GroupName = "06-Confirm", Order = 4)]
        public double RsiShortMax { get; set; }
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
