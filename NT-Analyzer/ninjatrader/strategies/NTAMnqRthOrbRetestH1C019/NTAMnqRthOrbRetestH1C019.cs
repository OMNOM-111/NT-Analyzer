// =============================================================================
// NTAMnqRthOrbRetestH1C019
// -----------------------------------------------------------------------------
// Standalone MNQ CELL-019 strategy. Family: "RTH H1 Opening Range Breakout
// with Retest Entry". Engine #7 for CELL-019.
//
// Why this engine: Engine #6 (TrendDayH1) showed structural edge in 2024
// (PF 1.44) but 2025 was negative/near-breakeven (PF 1.07-1.18).
// Regime analysis revealed 2025 has more false breakouts that reverse back
// to the OR boundary. The ORB-Retest approach exploits exactly that:
//   * Wait for price to BREAK the OR boundary (close beyond H/L)
//   * Then wait for a RETEST (price returns within tolerance)
//   * Enter on close that confirms the level held
//
// This structure works in BOTH regimes:
//   * Trending (2024): clean break → quick retest → continuation
//   * Choppy (2025): fake break → retest acts as genuine S/R → real move
//
// Differences from Engine #6:
//   * Signal  = 2-bar OR (not single bar1 bias), requires break AND retest
//   * Entry   = confirmation close after retest (not immediate bar2 close)
//   * Stop    = below/above entire OR (structural), capped by MaxStopPoints
//   * No RequirePriorDayAlignment / RequireTrendRegime (removed — failed)
//   * Trade window slightly wider: 8:30 PT onward (bar 3+)
//
// Risk shell identical to Engine #6.
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
    public class NTAMnqRthOrbRetestH1C019 : Strategy
    {
        // Indicators
        private ATR _atr;
        private ADX _adx;
        private RSI _rsi;
        private EMA _biasEma;
        private SMA _volumeSma;

        // Session tracking
        private DateTime _currentSessionDate = DateTime.MinValue;
        private int _barsSinceSessionStart;
        private bool _enteredToday;

        // Opening Range state
        private double _orHigh = double.NaN;
        private double _orLow  = double.NaN;
        private bool   _orDefined;

        // Break / retest state machine
        private int    _breakDirection;  // 0=none  +1=long  -1=short
        private double _breakLevel = double.NaN;
        private bool   _retestOccurred;

        // Prior-day tracker (for potential future use; not used in signal)
        private DateTime _lastClosedDay = DateTime.MinValue;
        private double _runningDayHigh;
        private double _runningDayLow;
        private double _runningDayClose;

        // Risk accounting
        private double   _weeklyRealizedPnl;
        private DateTime _weekStartDate = DateTime.MinValue;
        private double   _cumulativeRealizedPnl;
        private double   _sessionRealizedPnl;
        private int      _tradesToday;
        private int      _consecutiveLosses;
        private int      _lastProcessedTradeCount;
        private DateTime _pauseUntil = DateTime.MinValue;
        private bool     _permanentlyStopped;
        private bool     _sessionStopped;

        // Active trade tracking
        private string _activeSignal = "";
        private int    _lastEntryBar = -1;
        private double _lastEntryPrice;
        private int    _lastStopTicks;
        private bool   _stopMovedToBreakeven;
        private bool   _trailActivated;
        private double _bestFavorableTicks;

        // =====================================================================
        protected override void OnStateChange()
        {
            if (State == State.SetDefaults)
            {
                Description = "MNQ CELL-019 RTH H1 Opening Range Breakout with Retest entry (Engine #7).";
                Name        = "RTH ORB Retest H1 MNQ v1 c019";
                Calculate   = Calculate.OnBarClose;
                EntriesPerDirection    = 1;
                EntryHandling          = EntryHandling.AllEntries;
                IsExitOnSessionCloseStrategy = true;
                ExitOnSessionCloseSeconds    = 30;
                IsFillLimitOnTouch     = false;
                MaximumBarsLookBack    = MaximumBarsLookBack.TwoHundredFiftySix;
                OrderFillResolution    = OrderFillResolution.Standard;
                Slippage               = 0;
                StartBehavior          = StartBehavior.WaitUntilFlat;
                TimeInForce            = TimeInForce.Day;
                TraceOrders            = false;
                RealtimeErrorHandling  = RealtimeErrorHandling.StopCancelClose;
                StopTargetHandling     = StopTargetHandling.PerEntryExecution;
                BarsRequiredToTrade    = 30;
                IsInstantiatedOnEachOptimizationIteration = true;

                // --- 01-Instrument ---
                InstrumentName      = "MNQ";
                ContractName        = "MNQ 06-26";
                SessionTemplateName = "CME US Index Futures RTH";
                BaseTimeframeSeconds = 3600;

                // --- 02-Risk Profile ---
                StartingCapital           = 2000.0;
                IntradayOnly              = true;
                ActiveMarginPerContract   = 100.0;
                MaxContractsByCapital     = 20;
                InstrumentStatus          = "allowed";
                MarginSourceBroker        = "NinjaTrader";

                // --- 03-Direction ---
                EnableLong  = true;
                EnableShort = true;

                // --- 04-Time ---
                // OR defined after 2 H1 bars (7:30 PT close).
                // First eligible entry bar = bar 3 (8:30 PT onward).
                // Stop entries at 11:30 PT, force-flat 12:30 PT.
                TradeStartTime = 830;
                TradeEndTime   = 1130;
                ForceFlatTime  = 1230;

                // --- 05-Signal ---
                BiasEmaPeriod        = 20;
                OrBarsToDefine       = 2;    // H1 bars defining the OR
                RetestToleranceTicks = 8;    // price must come within X ticks of break level
                MinOrRangeTicks      = 16;   // min OR size (filter chop)
                MaxOrRangeTicks      = 400;  // max OR size (filter runaway)

                // --- 06-Confirm ---
                AdxPeriod    = 14;
                MinAdxTrend  = 18.0;
                MaxAdxTrend  = 60.0;
                RsiPeriod    = 14;
                RsiLongMax   = 75.0;
                RsiShortMin  = 25.0;

                // --- 07-Filters ---
                AtrPeriod        = 14;
                VolumeSmaPeriod  = 20;
                VolCeilingFactor = 5.0;
                VolMinFactor     = 0.30;

                // --- 08-Orders ---
                StopBufferPoints    = 3.0;
                MinStopPoints       = 14.0;
                MaxStopPoints       = 50.0;
                AtrStopMult         = 1.0;
                RewardRiskRatio     = 1.6;
                MinTargetPoints     = 20.0;
                MoveToBreakevenAtR  = 0.7;
                BreakevenPlusTicks  = 4;
                UseTrailingStop     = true;
                TrailAfterR         = 1.0;
                TrailDistanceTicks  = 40;
                UseTimeStop         = false;
                TimeStopBars        = 4;
                MinProgressR        = 0.30;

                // --- 09-Risk ---
                RiskPerTradePct           = 0.60;
                UserMaxContracts          = 1;
                MaxOpenPositions          = 1;
                MaxDailyLossUsd           = 120.0;
                MaxWeeklyLossUsd          = 300.0;
                MaxTradesPerDay           = 1;
                HardMaxTradesPerDay       = 1;
                MaxConsecutiveLosses      = 4;
                PauseAfterConsecutiveLosses = 3;
                PauseMinutesAfterLosses   = 60;
                RoundTurnCommission       = 1.90;
                SlippageTicks             = 1;
            }
            else if (State == State.DataLoaded)
            {
                _atr        = ATR(AtrPeriod);
                _adx        = ADX(AdxPeriod);
                _rsi        = RSI(RsiPeriod, 3);
                _biasEma    = EMA(BiasEmaPeriod);
                _volumeSma  = SMA(Volume, VolumeSmaPeriod);

                _permanentlyStopped =
                    StartingCapital <= 0.0
                    || ActiveMarginPerContract <= 0.0
                    || MaxContractsByCapital < 1
                    || string.Equals(InstrumentStatus, "blocked",  StringComparison.OrdinalIgnoreCase)
                    || string.Equals(InstrumentStatus, "unknown",  StringComparison.OrdinalIgnoreCase);
            }
            else if (State == State.Realtime)
            {
                ResetRealtimeRiskAccounting();
            }
        }

        // =====================================================================
        protected override void OnBarUpdate()
        {
            if (BarsInProgress != 0) return;
            if (CurrentBar < 1) return;

            UpdateSessionState();
            UpdatePriorDay();
            UpdateOrState();        // Accumulate OR regardless of time window
            ManageOpenPosition();

            if (ForceFlatDue())
            {
                ForceFlat("time");
                return;
            }

            if (CurrentBar < BarsRequiredToTrade) return;
            if (!InTradeWindow()) return;
            if (!_orDefined) return;
            if (_enteredToday) return;
            if (!CanTrade()) return;
            if (Position.MarketPosition != MarketPosition.Flat) return;
            if (_activeSignal != "") return;
            if (MaxOpenPositions < 1) return;

            TryEnterOrbRetest();
        }

        // =====================================================================
        private void UpdateSessionState()
        {
            DateTime today = Time[0].Date;
            bool newSession = Bars != null && Bars.IsFirstBarOfSession;
            if (newSession || _currentSessionDate != today)
            {
                _currentSessionDate = today;
                _barsSinceSessionStart = 0;
                _enteredToday = false;

                // Reset OR state for new session
                _orHigh          = double.NaN;
                _orLow           = double.NaN;
                _orDefined       = false;
                _breakDirection  = 0;
                _breakLevel      = double.NaN;
                _retestOccurred  = false;

                ResetDailyRisk();
                ClearActiveTradeState();
            }
            _barsSinceSessionStart += 1;
        }

        private void UpdatePriorDay()
        {
            DateTime today = Time[0].Date;
            if (_lastClosedDay == DateTime.MinValue)
            {
                _lastClosedDay    = today;
                _runningDayHigh   = High[0];
                _runningDayLow    = Low[0];
                _runningDayClose  = Close[0];
                return;
            }
            if (today != _lastClosedDay)
            {
                _lastClosedDay    = today;
                _runningDayHigh   = High[0];
                _runningDayLow    = Low[0];
                _runningDayClose  = Close[0];
            }
            else
            {
                if (High[0] > _runningDayHigh) _runningDayHigh = High[0];
                if (Low[0]  < _runningDayLow)  _runningDayLow  = Low[0];
                _runningDayClose = Close[0];
            }
        }

        // =====================================================================
        // UpdateOrState — accumulate the Opening Range from the first
        // OrBarsToDefine bars of each session. Called unconditionally.
        // =====================================================================
        private void UpdateOrState()
        {
            if (_barsSinceSessionStart > OrBarsToDefine) return; // already done
            if (double.IsNaN(_orHigh) || High[0] > _orHigh) _orHigh = High[0];
            if (double.IsNaN(_orLow)  || Low[0]  < _orLow)  _orLow  = Low[0];
            if (_barsSinceSessionStart == OrBarsToDefine)
                _orDefined = true;
        }

        // =====================================================================
        // TryEnterOrbRetest — state machine: break → retest → entry
        // =====================================================================
        private void TryEnterOrbRetest()
        {
            // OR sanity check
            if (double.IsNaN(_orHigh) || double.IsNaN(_orLow)) return;
            double orRange = _orHigh - _orLow;
            if (orRange < MinOrRangeTicks * TickSize) return;
            if (orRange > MaxOrRangeTicks * TickSize) return;

            // Volume filter
            double volFactor = VolumeFactor();
            if (volFactor > VolCeilingFactor) return;
            if (volFactor < VolMinFactor)     return;

            // ---------- Phase 1: detect break ----------
            if (_breakDirection == 0)
            {
                double adxVal = _adx[0];
                if (adxVal < MinAdxTrend || adxVal > MaxAdxTrend) return;

                double ema = _biasEma[0];

                if (EnableLong
                    && Close[0] > _orHigh
                    && Close[0] > ema
                    && _rsi[0] <= RsiLongMax)
                {
                    _breakDirection = 1;
                    _breakLevel     = _orHigh;
                }
                else if (EnableShort
                    && Close[0] < _orLow
                    && Close[0] < ema
                    && _rsi[0] >= RsiShortMin)
                {
                    _breakDirection = -1;
                    _breakLevel     = _orLow;
                }

                if (_breakDirection == 0) return; // No break yet — allow retest check below in same bar
            }

            // ---------- Phase 2: detect retest ----------
            // A retest = this bar's shadow comes within RetestToleranceTicks of the break level.
            // Can fire in the same bar as the break (shadow-touch pattern).
            if (!_retestOccurred)
            {
                double tol = RetestToleranceTicks * TickSize;
                if (_breakDirection ==  1 && Low[0]  <= _breakLevel + tol) _retestOccurred = true;
                if (_breakDirection == -1 && High[0] >= _breakLevel - tol) _retestOccurred = true;
                if (!_retestOccurred) return;
            }

            // ---------- Phase 3: entry after retest ----------
            // Close must re-confirm the break direction.
            if (_breakDirection ==  1 && EnableLong  && Close[0] > _breakLevel)
            {
                EnterOrbRetest(isLong: true);
            }
            else if (_breakDirection == -1 && EnableShort && Close[0] < _breakLevel)
            {
                EnterOrbRetest(isLong: false);
            }
        }

        private double VolumeFactor()
        {
            double baseVol = _volumeSma[0];
            if (baseVol <= 0.0) return 0.0;
            return Volume[0] / baseVol;
        }

        // =====================================================================
        private void EnterOrbRetest(bool isLong)
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
            _activeSignal         = signal;
            _lastStopTicks        = stopTicks;
            _lastEntryBar         = CurrentBar;
            _lastEntryPrice       = Close[0];
            _stopMovedToBreakeven = false;
            _trailActivated       = false;
            _bestFavorableTicks   = 0.0;
            _enteredToday         = true;
            if (isLong) EnterLong(qty, signal);
            else        EnterShort(qty, signal);
        }

        // Stop geometry: place stop beyond the full OR on the opposite side.
        // Also consider ATR; take the larger and cap to [Min, Max].
        private double ComputeStopPoints(bool isLong)
        {
            double atrPts     = _atr[0];
            double atrStop    = atrPts * AtrStopMult;

            // Distance from current close to opposite OR boundary + buffer
            double geometryStop = isLong
                ? (Close[0] - _orLow)  + StopBufferPoints
                : (_orHigh - Close[0]) + StopBufferPoints;

            double stop = Math.Max(geometryStop, atrStop);
            stop = Math.Max(stop, MinStopPoints);
            stop = Math.Min(stop, MaxStopPoints);
            return stop;
        }

        // =====================================================================
        private void ManageOpenPosition()
        {
            if (Position.MarketPosition == MarketPosition.Flat) return;
            bool isLong = Position.MarketPosition == MarketPosition.Long;
            double entry = Position.AveragePrice;
            if (entry <= 0.0) entry = _lastEntryPrice;
            if (entry <= 0.0 || _lastStopTicks <= 0) return;

            double favorableTicks = isLong
                ? (High[0] - entry) / TickSize
                : (entry - Low[0])  / TickSize;
            _bestFavorableTicks = Math.Max(_bestFavorableTicks, favorableTicks);

            // Move to breakeven
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

            // Trailing stop
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
                    double floor = entry + BreakevenPlusTicks * TickSize;
                    if (trailPrice > floor)
                        SetStopLoss(_activeSignal, CalculationMode.Price, trailPrice, false);
                }
                else
                {
                    double ceiling = entry - BreakevenPlusTicks * TickSize;
                    if (trailPrice < ceiling)
                        SetStopLoss(_activeSignal, CalculationMode.Price, trailPrice, false);
                }
            }

            // Time stop
            if (UseTimeStop && TimeStopBars > 0 && _lastEntryBar >= 0)
            {
                int barsHeld = CurrentBar - _lastEntryBar;
                if (barsHeld >= TimeStopBars
                    && _bestFavorableTicks < _lastStopTicks * MinProgressR)
                {
                    if (isLong) ExitLong("TimeStop",  _activeSignal);
                    else        ExitShort("TimeStop", _activeSignal);
                }
            }
        }

        // =====================================================================
        private void ForceFlat(string reason)
        {
            if (Position.MarketPosition == MarketPosition.Long)
                ExitLong("ForceFlat_" + reason,  _activeSignal == "" ? TelemetrySignal("Long")  : _activeSignal);
            else if (Position.MarketPosition == MarketPosition.Short)
                ExitShort("ForceFlat_" + reason, _activeSignal == "" ? TelemetrySignal("Short") : _activeSignal);
        }

        private bool CanTrade()
        {
            if (_permanentlyStopped || _sessionStopped) return false;
            if (_pauseUntil != DateTime.MinValue && Time[0] < _pauseUntil) return false;
            if (MaxDailyLossUsd   > 0.0 && _sessionRealizedPnl  <= -MaxDailyLossUsd)   return false;
            if (MaxWeeklyLossUsd  > 0.0 && _weeklyRealizedPnl   <= -MaxWeeklyLossUsd)  return false;
            if (MaxTradesPerDay   > 0   && _tradesToday          >= MaxTradesPerDay)     return false;
            if (HardMaxTradesPerDay > 0 && _tradesToday          >= HardMaxTradesPerDay) return false;
            if (MaxConsecutiveLosses > 0 && _consecutiveLosses   >= MaxConsecutiveLosses) return false;
            return true;
        }

        private int ComputeQuantity(int stopTicks)
        {
            if (_permanentlyStopped) return 0;
            double tickVal = TickValue();
            if (tickVal <= 0.0) return 0;
            double equity       = CurrentEquity();
            double riskBudget   = equity * RiskPerTradePct / 100.0;
            double contractRisk = stopTicks * tickVal + RoundTurnCommission + SlippageTicks * tickVal;
            if (contractRisk <= 0.0) return 0;
            int byRisk   = (int)Math.Floor(riskBudget / contractRisk);
            int byMargin = ActiveMarginPerContract > 0.0
                ? (int)Math.Floor(equity / ActiveMarginPerContract)
                : MaxContractsByCapital;
            int byUser   = UserMaxContracts > 0 ? UserMaxContracts : MaxContractsByCapital;
            int qty      = Math.Min(Math.Min(byRisk, byMargin), Math.Min(byUser, MaxContractsByCapital));
            if (qty < 1
                && byMargin >= 1
                && byUser   >= 1
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
            if (Position != null
                && Position.MarketPosition != MarketPosition.Flat
                && Position.Quantity > 0)
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
            _activeSignal         = "";
            _lastEntryBar         = -1;
            _lastEntryPrice       = 0.0;
            _lastStopTicks        = 0;
            _stopMovedToBreakeven = false;
            _trailActivated       = false;
            _bestFavorableTicks   = 0.0;
        }

        private void ResetDailyRisk()
        {
            DateTime weekStart = WeekStart(Time[0].Date);
            if (_weekStartDate == DateTime.MinValue || _weekStartDate != weekStart)
            {
                _weekStartDate     = weekStart;
                _weeklyRealizedPnl = 0.0;
            }
            _sessionRealizedPnl = 0.0;
            _tradesToday        = 0;
            _consecutiveLosses  = 0;
            _sessionStopped     = false;
            _pauseUntil         = DateTime.MinValue;
        }

        private void ResetRealtimeRiskAccounting()
        {
            _cumulativeRealizedPnl = 0.0;
            _sessionRealizedPnl    = 0.0;
            _weeklyRealizedPnl     = 0.0;
            _tradesToday           = 0;
            _consecutiveLosses     = 0;
            _sessionStopped        = false;
            _pauseUntil            = DateTime.MinValue;
            _weekStartDate         = WeekStart(Time[0].Date);
            _lastProcessedTradeCount = SystemPerformance == null
                ? 0
                : Math.Max(0, SystemPerformance.AllTrades.Count);
            Print(string.Format(
                "[RISK:realtime_reset] historicalTrades={0}; live paper risk starts from zero",
                _lastProcessedTradeCount));
        }

        protected override void OnPositionUpdate(
            Position position, double averagePrice, int quantity, MarketPosition marketPosition)
        {
            if (marketPosition != MarketPosition.Flat) return;
            if (SystemPerformance == null) return;
            int total = SystemPerformance.AllTrades.Count;
            if (total <= _lastProcessedTradeCount) return;
            for (int i = _lastProcessedTradeCount; i < total; i++)
            {
                Trade trade = SystemPerformance.AllTrades[i];
                double qty  = Math.Max(1, trade.Quantity);
                double pnl  = trade.ProfitCurrency - RoundTurnCommission * qty;
                _cumulativeRealizedPnl += pnl;
                _sessionRealizedPnl    += pnl;
                _weeklyRealizedPnl     += pnl;
                _tradesToday           += 1;
                if (pnl < 0.0) _consecutiveLosses += 1;
                else           _consecutiveLosses  = 0;
                if (pnl < 0.0
                    && PauseAfterConsecutiveLosses > 0
                    && _consecutiveLosses >= PauseAfterConsecutiveLosses)
                    _pauseUntil = Time[0].AddMinutes(Math.Max(1, PauseMinutesAfterLosses));
            }
            if (MaxDailyLossUsd   > 0.0 && _sessionRealizedPnl  <= -MaxDailyLossUsd)   _sessionStopped = true;
            if (MaxWeeklyLossUsd  > 0.0 && _weeklyRealizedPnl   <= -MaxWeeklyLossUsd)  _sessionStopped = true;
            if (MaxConsecutiveLosses > 0 && _consecutiveLosses   >= MaxConsecutiveLosses) _sessionStopped = true;
            _lastProcessedTradeCount = total;
            ClearActiveTradeState();
        }

        // =====================================================================
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

        [NinjaScriptProperty, Range(1, 7200)]
        [Display(Name = "BaseTimeframeSeconds", GroupName = "01-Instrument", Order = 3)]
        public int BaseTimeframeSeconds { get; set; }

        // --- 02-Risk Profile ---
        [NinjaScriptProperty]
        [Display(Name = "StartingCapital", GroupName = "02-Risk Profile", Order = 0)]
        public double StartingCapital { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "IntradayOnly", GroupName = "02-Risk Profile", Order = 1)]
        public bool IntradayOnly { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "ActiveMarginPerContract", GroupName = "02-Risk Profile", Order = 2)]
        public double ActiveMarginPerContract { get; set; }

        [NinjaScriptProperty, Range(1, 100)]
        [Display(Name = "MaxContractsByCapital", GroupName = "02-Risk Profile", Order = 3)]
        public int MaxContractsByCapital { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "InstrumentStatus", GroupName = "02-Risk Profile", Order = 4)]
        public string InstrumentStatus { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "MarginSourceBroker", GroupName = "02-Risk Profile", Order = 5)]
        public string MarginSourceBroker { get; set; }

        // --- 03-Direction ---
        [NinjaScriptProperty]
        [Display(Name = "EnableLong", GroupName = "03-Direction", Order = 0)]
        public bool EnableLong { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "EnableShort", GroupName = "03-Direction", Order = 1)]
        public bool EnableShort { get; set; }

        // --- 04-Time ---
        [NinjaScriptProperty, Range(0, 2359)]
        [Display(Name = "TradeStartTime", GroupName = "04-Time", Order = 0)]
        public int TradeStartTime { get; set; }

        [NinjaScriptProperty, Range(0, 2359)]
        [Display(Name = "TradeEndTime", GroupName = "04-Time", Order = 1)]
        public int TradeEndTime { get; set; }

        [NinjaScriptProperty, Range(0, 2359)]
        [Display(Name = "ForceFlatTime", GroupName = "04-Time", Order = 2)]
        public int ForceFlatTime { get; set; }

        // --- 05-Signal ---
        [NinjaScriptProperty, Range(2, 500)]
        [Display(Name = "BiasEmaPeriod", GroupName = "05-Signal", Order = 0)]
        public int BiasEmaPeriod { get; set; }

        [NinjaScriptProperty, Range(1, 10)]
        [Display(Name = "OrBarsToDefine", GroupName = "05-Signal", Order = 1)]
        public int OrBarsToDefine { get; set; }

        [NinjaScriptProperty, Range(1, 200)]
        [Display(Name = "RetestToleranceTicks", GroupName = "05-Signal", Order = 2)]
        public int RetestToleranceTicks { get; set; }

        [NinjaScriptProperty, Range(1, 2000)]
        [Display(Name = "MinOrRangeTicks", GroupName = "05-Signal", Order = 3)]
        public int MinOrRangeTicks { get; set; }

        [NinjaScriptProperty, Range(1, 4000)]
        [Display(Name = "MaxOrRangeTicks", GroupName = "05-Signal", Order = 4)]
        public int MaxOrRangeTicks { get; set; }

        // --- 06-Confirm ---
        [NinjaScriptProperty, Range(2, 100)]
        [Display(Name = "AdxPeriod", GroupName = "06-Confirm", Order = 0)]
        public int AdxPeriod { get; set; }

        [NinjaScriptProperty, Range(0.0, 80.0)]
        [Display(Name = "MinAdxTrend", GroupName = "06-Confirm", Order = 1)]
        public double MinAdxTrend { get; set; }

        [NinjaScriptProperty, Range(0.0, 100.0)]
        [Display(Name = "MaxAdxTrend", GroupName = "06-Confirm", Order = 2)]
        public double MaxAdxTrend { get; set; }

        [NinjaScriptProperty, Range(2, 100)]
        [Display(Name = "RsiPeriod", GroupName = "06-Confirm", Order = 3)]
        public int RsiPeriod { get; set; }

        [NinjaScriptProperty, Range(0.0, 100.0)]
        [Display(Name = "RsiLongMax", GroupName = "06-Confirm", Order = 4)]
        public double RsiLongMax { get; set; }

        [NinjaScriptProperty, Range(0.0, 100.0)]
        [Display(Name = "RsiShortMin", GroupName = "06-Confirm", Order = 5)]
        public double RsiShortMin { get; set; }

        // --- 07-Filters ---
        [NinjaScriptProperty, Range(2, 200)]
        [Display(Name = "AtrPeriod", GroupName = "07-Filters", Order = 0)]
        public int AtrPeriod { get; set; }

        [NinjaScriptProperty, Range(2, 500)]
        [Display(Name = "VolumeSmaPeriod", GroupName = "07-Filters", Order = 1)]
        public int VolumeSmaPeriod { get; set; }

        [NinjaScriptProperty, Range(0.5, 20.0)]
        [Display(Name = "VolCeilingFactor", GroupName = "07-Filters", Order = 2)]
        public double VolCeilingFactor { get; set; }

        [NinjaScriptProperty, Range(0.0, 5.0)]
        [Display(Name = "VolMinFactor", GroupName = "07-Filters", Order = 3)]
        public double VolMinFactor { get; set; }

        // --- 08-Orders ---
        [NinjaScriptProperty, Range(0.0, 50.0)]
        [Display(Name = "StopBufferPoints", GroupName = "08-Orders", Order = 0)]
        public double StopBufferPoints { get; set; }

        [NinjaScriptProperty, Range(0.25, 200.0)]
        [Display(Name = "MinStopPoints", GroupName = "08-Orders", Order = 1)]
        public double MinStopPoints { get; set; }

        [NinjaScriptProperty, Range(0.25, 500.0)]
        [Display(Name = "MaxStopPoints", GroupName = "08-Orders", Order = 2)]
        public double MaxStopPoints { get; set; }

        [NinjaScriptProperty, Range(0.0, 10.0)]
        [Display(Name = "AtrStopMult", GroupName = "08-Orders", Order = 3)]
        public double AtrStopMult { get; set; }

        [NinjaScriptProperty, Range(0.1, 10.0)]
        [Display(Name = "RewardRiskRatio", GroupName = "08-Orders", Order = 4)]
        public double RewardRiskRatio { get; set; }

        [NinjaScriptProperty, Range(0.25, 500.0)]
        [Display(Name = "MinTargetPoints", GroupName = "08-Orders", Order = 5)]
        public double MinTargetPoints { get; set; }

        [NinjaScriptProperty, Range(0.0, 5.0)]
        [Display(Name = "MoveToBreakevenAtR", GroupName = "08-Orders", Order = 6)]
        public double MoveToBreakevenAtR { get; set; }

        [NinjaScriptProperty, Range(0, 50)]
        [Display(Name = "BreakevenPlusTicks", GroupName = "08-Orders", Order = 7)]
        public int BreakevenPlusTicks { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "UseTrailingStop", GroupName = "08-Orders", Order = 8)]
        public bool UseTrailingStop { get; set; }

        [NinjaScriptProperty, Range(0.0, 5.0)]
        [Display(Name = "TrailAfterR", GroupName = "08-Orders", Order = 9)]
        public double TrailAfterR { get; set; }

        [NinjaScriptProperty, Range(1, 400)]
        [Display(Name = "TrailDistanceTicks", GroupName = "08-Orders", Order = 10)]
        public int TrailDistanceTicks { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "UseTimeStop", GroupName = "08-Orders", Order = 11)]
        public bool UseTimeStop { get; set; }

        [NinjaScriptProperty, Range(1, 200)]
        [Display(Name = "TimeStopBars", GroupName = "08-Orders", Order = 12)]
        public int TimeStopBars { get; set; }

        [NinjaScriptProperty, Range(0.0, 2.0)]
        [Display(Name = "MinProgressR", GroupName = "08-Orders", Order = 13)]
        public double MinProgressR { get; set; }

        // --- 09-Risk ---
        [NinjaScriptProperty, Range(0.01, 10.0)]
        [Display(Name = "RiskPerTradePct", GroupName = "09-Risk", Order = 0)]
        public double RiskPerTradePct { get; set; }

        [NinjaScriptProperty, Range(0, 100)]
        [Display(Name = "UserMaxContracts", GroupName = "09-Risk", Order = 1)]
        public int UserMaxContracts { get; set; }

        [NinjaScriptProperty, Range(0, 100)]
        [Display(Name = "MaxOpenPositions", GroupName = "09-Risk", Order = 2)]
        public int MaxOpenPositions { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "MaxDailyLossUsd", GroupName = "09-Risk", Order = 3)]
        public double MaxDailyLossUsd { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "MaxWeeklyLossUsd", GroupName = "09-Risk", Order = 4)]
        public double MaxWeeklyLossUsd { get; set; }

        [NinjaScriptProperty, Range(0, 100)]
        [Display(Name = "MaxTradesPerDay", GroupName = "09-Risk", Order = 5)]
        public int MaxTradesPerDay { get; set; }

        [NinjaScriptProperty, Range(0, 100)]
        [Display(Name = "HardMaxTradesPerDay", GroupName = "09-Risk", Order = 6)]
        public int HardMaxTradesPerDay { get; set; }

        [NinjaScriptProperty, Range(0, 20)]
        [Display(Name = "MaxConsecutiveLosses", GroupName = "09-Risk", Order = 7)]
        public int MaxConsecutiveLosses { get; set; }

        [NinjaScriptProperty, Range(0, 20)]
        [Display(Name = "PauseAfterConsecutiveLosses", GroupName = "09-Risk", Order = 8)]
        public int PauseAfterConsecutiveLosses { get; set; }

        [NinjaScriptProperty, Range(0, 480)]
        [Display(Name = "PauseMinutesAfterLosses", GroupName = "09-Risk", Order = 9)]
        public int PauseMinutesAfterLosses { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "RoundTurnCommission", GroupName = "09-Risk", Order = 10)]
        public double RoundTurnCommission { get; set; }

        [NinjaScriptProperty, Range(0, 100)]
        [Display(Name = "SlippageTicks", GroupName = "09-Risk", Order = 11)]
        public int SlippageTicks { get; set; }

        #endregion
    }
}
