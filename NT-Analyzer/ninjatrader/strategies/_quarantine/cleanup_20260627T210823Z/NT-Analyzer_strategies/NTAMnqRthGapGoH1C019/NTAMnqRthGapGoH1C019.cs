// =============================================================================
// NTAMnqRthGapGoH1C019
// -----------------------------------------------------------------------------
// Standalone MNQ CELL-019 strategy. Family: "RTH H1 Gap-and-Go Retest".
// Engine #9 for CELL-019.
//
// Why this engine: Engines #7/#8 (ORB Retest H1/15m) showed cross-year
// positive PnL but could not pass the dd gate (-$300). Root cause: stops
// of 25-50 points = $50-100 per trade → 3 consecutive losses = -$150-300.
// With 60-90 trades/year, such streaks are nearly certain.
//
// Engine #9 fix: use STRUCTURAL TIGHT STOP at the gap level.
//
// Signal hypothesis:
//   On RTH gap days (today opens above prior day HIGH or below prior day LOW),
//   the gap level (priorDayHigh / priorDayLow) becomes a key S/R level.
//   Price often retests that level before continuing in the gap direction.
//   Enter on a close that confirms the level held (retest → continuation).
//   Stop: just below/above the gap level (2-4 pts buffer = 8-16 ticks).
//   Target: 2× stop (RR=2.0) → min viable PF even at 40% WR.
//
// Why this passes the dd gate:
//   MaxStopPoints=20 pts = $40/trade. With MaxDailyLossUsd=$120, one
//   losing day costs at most $40+$1.90 ≈ $42. Even 7 consecutive losing
//   days (extreme): 7 × $42 = $294 — still within -$300 gate.
//   And with only 15-30 trades/year (gap days are selective), long losing
//   streaks are structurally unlikely.
//
// Gap-day selectivity:
//   RTH gap-up/down days (open vs prior-day extreme, not just prior close)
//   occur ~15-25% of trading days → ~38-63 potential days/year. After
//   filtering by retest occurrence + ADX + EMA, actual trades ≈ 15-35/year.
//
// Differences from Engine #7 (ORB Retest):
//   * No "Opening Range" concept — gap level IS the structural break level
//   * Stop anchored to gap level (structural), NOT to ATR or OR width
//   * MaxStopPoints=20 (vs 50); MinStopPoints=8 (vs 14)
//   * RR=2.0 (vs 1.4) — tighter stop needs higher reward
//   * Trades only on gap days → 15-35 trades/year (vs 60-90)
//   * Signal: gap detection + retest of priorDayH/L (not OR H/L)
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
    public class NTAMnqRthGapGoH1C019 : Strategy
    {
        // Indicators
        private ATR _atr;
        private ADX _adx;
        private RSI _rsi;
        private EMA _biasEma;
        private SMA _volumeSma;

        // Session tracking
        private DateTime _currentSessionDate = DateTime.MinValue;
        private int    _barsSinceSessionStart;
        private bool   _enteredToday;
        private double _sessionOpen = double.NaN;

        // Gap state (set at session open, cleared on new session)
        private int    _gapDirection;    // 0=none  +1=gapUp  -1=gapDown
        private double _gapLevel = double.NaN;  // priorDayHigh (gapUp) or priorDayLow (gapDown)

        // Retest state machine
        private bool   _retestOccurred;
        private int    _pendingEntryDirection;
        private int    _pendingEntryBar = -1;

        // Prior-day rolling tracker
        private bool     _hasRunningSession;
        private bool     _hasPriorSession;
        private double   _runningSessionHigh;
        private double   _runningSessionLow;
        private double   _runningSessionClose;
        private double   _priorDayHigh;
        private double   _priorDayLow;
        private double   _priorDayClose;

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
                Description = "MNQ CELL-019 RTH H1 Gap-and-Go with Retest at prior-day extreme (Engine #9).";
                Name        = "RTH Gap-Go Retest H1 MNQ v1 c019";
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
                InstrumentName       = "MNQ";
                ContractName         = "MNQ 06-26";
                SessionTemplateName  = "CME US Index Futures RTH";
                BaseTimeframeSeconds = 3600;

                // --- 02-Risk Profile ---
                StartingCapital         = 2000.0;
                IntradayOnly            = true;
                ActiveMarginPerContract = 100.0;
                MaxContractsByCapital   = 20;
                InstrumentStatus        = "allowed";
                MarginSourceBroker      = "NinjaTrader";

                // --- 03-Direction ---
                EnableLong  = true;
                EnableShort = true;

                // --- 04-Time ---
                // After bar 1 (07:30 PT) first eligible entry on bar 2+.
                // Stop entries 11:30 PT, force flat 12:30 PT.
                TradeStartTime = 730;
                TradeEndTime   = 1130;
                ForceFlatTime  = 1230;

                // --- 05-Signal (Gap) ---
                BiasEmaPeriod          = 20;
                GapMinPoints           = 4.0;     // minimum gap above priorDayHigh
                GapMaxPoints           = 100.0;   // filter runaway gaps
                RetestToleranceTicks   = 8;       // must come within 8 ticks of gap level

                // --- 06-Confirm ---
                AdxPeriod    = 14;
                MinAdxTrend  = 16.0;
                MaxAdxTrend  = 60.0;
                RsiPeriod    = 14;
                RsiLongMax   = 78.0;
                RsiShortMin  = 22.0;

                // --- 07-Filters ---
                AtrPeriod        = 14;
                VolumeSmaPeriod  = 20;
                VolCeilingFactor = 6.0;
                VolMinFactor     = 0.20;

                // --- 08-Orders (TIGHT stops = core of the design) ---
                StopBufferPoints   = 2.0;    // tight buffer below gap level
                MinStopPoints      = 8.0;    // 32 ticks minimum
                MaxStopPoints      = 20.0;   // 80 ticks maximum — KEY: small per-trade risk
                AtrStopMult        = 0.5;    // ATR used only as floor, capped by Max
                RewardRiskRatio    = 2.0;    // RR=2 to be viable at lower WR
                MinTargetPoints    = 16.0;
                MoveToBreakevenAtR = 1.0;    // move BE at 1R (after full stop risked)
                BreakevenPlusTicks = 2;
                UseTrailingStop    = true;
                TrailAfterR        = 1.5;
                TrailDistanceTicks = 24;
                UseTimeStop        = false;
                TimeStopBars       = 3;
                MinProgressR       = 0.30;

                // --- 09-Risk ---
                RiskPerTradePct             = 1.0;    // slightly higher since stops are tight
                UserMaxContracts            = 1;
                MaxOpenPositions            = 1;
                MaxDailyLossUsd             = 80.0;   // reduced from 120 → tighter daily cap
                MaxWeeklyLossUsd            = 200.0;
                MaxTradesPerDay             = 1;
                HardMaxTradesPerDay         = 1;
                MaxConsecutiveLosses        = 5;
                PauseAfterConsecutiveLosses = 3;
                PauseMinutesAfterLosses     = 60;
                RoundTurnCommission         = 1.90;
                SlippageTicks               = 1;
            }
            else if (State == State.DataLoaded)
            {
                _atr       = ATR(AtrPeriod);
                _adx       = ADX(AdxPeriod);
                _rsi       = RSI(RsiPeriod, 3);
                _biasEma   = EMA(BiasEmaPeriod);
                _volumeSma = SMA(Volume, VolumeSmaPeriod);

                _permanentlyStopped =
                    StartingCapital <= 0.0
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

        // =====================================================================
        protected override void OnBarUpdate()
        {
            if (BarsInProgress != 0) return;
            if (CurrentBar < 1) return;

            UpdatePriorDay();       // must run BEFORE UpdateSessionState to capture rollover
            UpdateSessionState();
            ManageOpenPosition();

            if (ForceFlatDue())
            {
                ForceFlat("time");
                return;
            }

            if (CurrentBar < BarsRequiredToTrade) return;
            if (!InTradeWindow()) return;
            if (_gapDirection == 0) return;  // not a gap day
            if (_barsSinceSessionStart < 2) return;  // need at least bar 1 complete
            if (_enteredToday) return;
            if (!CanTrade()) return;
            if (Position.MarketPosition != MarketPosition.Flat) return;
            if (_activeSignal != "") return;
            if (MaxOpenPositions < 1) return;

            if (TryEnterPendingGapGo()) return;
            TryEnterGapGo();
        }

        // =====================================================================
        private void UpdatePriorDay()
        {
            bool firstBarOfSession = Bars != null && Bars.IsFirstBarOfSession;
            if (!_hasRunningSession)
            {
                _runningSessionHigh  = High[0];
                _runningSessionLow   = Low[0];
                _runningSessionClose = Close[0];
                _hasRunningSession   = true;
                return;
            }

            if (firstBarOfSession)
            {
                // Save the completed RTH session before starting a new one.
                _priorDayHigh   = _runningSessionHigh;
                _priorDayLow    = _runningSessionLow;
                _priorDayClose  = _runningSessionClose;
                _hasPriorSession = true;

                _runningSessionHigh  = High[0];
                _runningSessionLow   = Low[0];
                _runningSessionClose = Close[0];
                return;
            }

            if (High[0] > _runningSessionHigh) _runningSessionHigh = High[0];
            if (Low[0]  < _runningSessionLow)  _runningSessionLow  = Low[0];
            _runningSessionClose = Close[0];
        }

        private void UpdateSessionState()
        {
            DateTime today = Time[0].Date;
            bool newSession = Bars != null && Bars.IsFirstBarOfSession;
            if (newSession || _currentSessionDate != today)
            {
                _currentSessionDate   = today;
                _barsSinceSessionStart = 0;
                _enteredToday          = false;
                _retestOccurred        = false;
                ClearPendingEntry();

                // Detect gap on first bar of new session
                _gapDirection = 0;
                _gapLevel     = double.NaN;
                if (_hasPriorSession && _priorDayHigh > 0.0 && _priorDayLow > 0.0)
                {
                    _sessionOpen = Open[0];
                    double gapUp   = _sessionOpen - _priorDayHigh;
                    double gapDown = _priorDayLow  - _sessionOpen;
                    if (EnableLong && gapUp >= GapMinPoints && gapUp <= GapMaxPoints)
                    {
                        _gapDirection = 1;
                        _gapLevel     = _priorDayHigh;
                    }
                    else if (EnableShort && gapDown >= GapMinPoints && gapDown <= GapMaxPoints)
                    {
                        _gapDirection = -1;
                        _gapLevel     = _priorDayLow;
                    }
                }

                ResetDailyRisk();
                ClearActiveTradeState();
            }
            _barsSinceSessionStart += 1;
        }

        // =====================================================================
        // TryEnterGapGo — retest of the gap level then entry
        // =====================================================================
        private void TryEnterGapGo()
        {
            if (double.IsNaN(_gapLevel)) return;
            if (_pendingEntryDirection != 0) return;

            // Confirm ADX and volume conditions
            double adxVal = _adx[0];
            if (adxVal > MaxAdxTrend) return;   // no upper-bound filter on ADX for gap entries
            // (MinAdxTrend not applied — gap itself IS the trend signal)

            double volFactor = VolumeFactor();
            if (volFactor > VolCeilingFactor) return;
            if (volFactor < VolMinFactor)     return;

            // EMA bias agreement
            double ema = _biasEma[0];
            if (_gapDirection ==  1 && !(Close[0] > ema)) return;
            if (_gapDirection == -1 && !(Close[0] < ema)) return;

            // Phase 1: detect retest of gap level
            if (!_retestOccurred)
            {
                double tol = RetestToleranceTicks * TickSize;
                if (_gapDirection ==  1 && Low[0]  <= _gapLevel + tol) _retestOccurred = true;
                if (_gapDirection == -1 && High[0] >= _gapLevel - tol) _retestOccurred = true;
                if (!_retestOccurred) return;
            }

            // Phase 2: re-confirm close above/below gap level after retest
            if (_gapDirection ==  1 && Close[0] > _gapLevel && _rsi[0] <= RsiLongMax)
            {
                ArmPendingEntry(1);
            }
            else if (_gapDirection == -1 && Close[0] < _gapLevel && _rsi[0] >= RsiShortMin)
            {
                ArmPendingEntry(-1);
            }
        }

        private bool TryEnterPendingGapGo()
        {
            if (_pendingEntryDirection == 0) return false;
            if (CurrentBar <= _pendingEntryBar) return false;

            bool isLong = _pendingEntryDirection > 0;
            bool confirmed = isLong
                ? Close[0] > _gapLevel && _rsi[0] <= RsiLongMax
                : Close[0] < _gapLevel && _rsi[0] >= RsiShortMin;

            ClearPendingEntry();
            if (!confirmed) return false;

            EnterGapGo(isLong);
            return true;
        }

        private void ArmPendingEntry(int direction)
        {
            _pendingEntryDirection = direction;
            _pendingEntryBar       = CurrentBar;
        }

        private double VolumeFactor()
        {
            double baseVol = _volumeSma[0];
            if (baseVol <= 0.0) return 0.0;
            return Volume[0] / baseVol;
        }

        // =====================================================================
        private void EnterGapGo(bool isLong)
        {
            // Stop is structural: distance from close to gap level + buffer
            // Capped by [MinStopPoints, MaxStopPoints]
            double geometryStop = isLong
                ? (Close[0] - _gapLevel) + StopBufferPoints
                : (_gapLevel - Close[0]) + StopBufferPoints;
            double atrStop  = _atr[0] * AtrStopMult;
            double stopPts  = Math.Max(geometryStop, atrStop);
            stopPts = Math.Max(stopPts, MinStopPoints);
            stopPts = Math.Min(stopPts, MaxStopPoints);
            int stopTicks = (int)Math.Round(stopPts / TickSize);

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
            ClearPendingEntry();
        }

        private void ClearPendingEntry()
        {
            _pendingEntryDirection = 0;
            _pendingEntryBar       = -1;
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

        [NinjaScriptProperty, Range(0.0, 500.0)]
        [Display(Name = "GapMinPoints", GroupName = "05-Signal", Order = 1)]
        public double GapMinPoints { get; set; }

        [NinjaScriptProperty, Range(0.0, 5000.0)]
        [Display(Name = "GapMaxPoints", GroupName = "05-Signal", Order = 2)]
        public double GapMaxPoints { get; set; }

        [NinjaScriptProperty, Range(1, 200)]
        [Display(Name = "RetestToleranceTicks", GroupName = "05-Signal", Order = 3)]
        public int RetestToleranceTicks { get; set; }

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
