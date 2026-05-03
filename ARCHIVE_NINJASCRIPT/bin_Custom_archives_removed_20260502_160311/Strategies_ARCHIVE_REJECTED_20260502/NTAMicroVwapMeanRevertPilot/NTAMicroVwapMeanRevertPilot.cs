// =============================================================================
// NTAMicroVwapMeanRevertPilot v0.1
// -----------------------------------------------------------------------------
// Phase 13E: NEW family — post-open MNQ VWAP mean-reversion.
// Independent class. Does NOT modify NTAMicroVwapRiskPilot (B1 baseline).
//
// Idea:
//   After 07:00 PT (10:00 ET) the cash session is in full swing. When price
//   has overextended away from session VWAP, fade the move back toward VWAP.
//   Stop is ATR-based; target is VWAP itself (mean reversion).
//
// Single-series strategy → OrderFillResolution=High supported.
//
// Time semantics: HHMM in Pacific Time (PC local). Reports use PT.
//   07:00 PT = 10:00 ET   -> TradeStartTime = 700
//   08:30 PT = 11:30 ET   -> TradeEndTime   = 830 (default)
//   10:00 PT = 13:00 ET   -> alt TradeEndTime = 1000
//   12:45 PT = 15:45 ET   -> ForceFlatTime = 1245
//
// Risk Profile contract identical to B1: StartingCapital, IntradayOnly,
// ActiveMarginPerContract, MaxContractsByCapital, InstrumentStatus,
// MarginSourceBroker — all set by NT-Analyzer mapper.
// Validator-enforced execution: High fill, slip>=1, RTC>=1.90.
// =============================================================================

#region Using declarations
using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.ComponentModel.DataAnnotations;
using System.Linq;
using NinjaTrader.Cbi;
using NinjaTrader.Data;
using NinjaTrader.NinjaScript;
using NinjaTrader.NinjaScript.Indicators;
using NinjaTrader.NinjaScript.Strategies;
#endregion

namespace NinjaTrader.NinjaScript.Strategies
{
    public class NTAMicroVwapMeanRevertPilot : Strategy
    {
        // ------------- indicators -------------
        private ATR _atr;

        // ------------- session VWAP (manual, single-series safe) -------------
        private Series<double> _vwapSeries;
        private double         _vwapCumTPV;
        private double         _vwapCumVol;
        private DateTime       _sessionDate = DateTime.MinValue;

        // ------------- risk -------------
        private MRRiskManager _risk;

        // ------------- pending entry tracking -------------
        private string _pendingEntrySignal      = null; // "Long"|"Short"
        private int    _pendingEntryBar         = -1;
        private int    _pendingEntryQty         = 0;
        private double _pendingEntryStopPx      = 0.0;
        private double _pendingEntryTargetPx    = 0.0;
        private int    _pendingStopTicks        = 0;

        // ------------- trade journal -------------
        private int _lastSkipBar = -1;
        private string _lastSkipReason = "";

        // ====================================================================
        // PROPERTIES
        // ====================================================================

        #region Risk Profile (filled by NT-Analyzer mapper — Phase 0 contract)
        [NinjaScriptProperty]
        [Display(Name = "StartingCapital", GroupName = "01-Risk Profile", Order = 0)]
        public double StartingCapital { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "IntradayOnly", GroupName = "01-Risk Profile", Order = 1)]
        public bool IntradayOnly { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "ActiveMarginPerContract", GroupName = "01-Risk Profile", Order = 2)]
        public double ActiveMarginPerContract { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "MaxContractsByCapital", GroupName = "01-Risk Profile", Order = 3)]
        public int MaxContractsByCapital { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "InstrumentStatus", GroupName = "01-Risk Profile", Order = 4)]
        public string InstrumentStatus { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "MarginSourceBroker", GroupName = "01-Risk Profile", Order = 5)]
        public string MarginSourceBroker { get; set; }
        #endregion

        #region Risk
        [NinjaScriptProperty, Range(0.01, 10.0)]
        [Display(Name = "RiskPerTradePct", GroupName = "02-Risk", Order = 0)]
        public double RiskPerTradePct { get; set; }

        [NinjaScriptProperty, Range(0.1, 50.0)]
        [Display(Name = "MaxDailyLossPct", GroupName = "02-Risk", Order = 1)]
        public double MaxDailyLossPct { get; set; }

        [NinjaScriptProperty, Range(0.0, 100.0)]
        [Display(Name = "MaxDailyProfitPct (0=off)", GroupName = "02-Risk", Order = 2)]
        public double MaxDailyProfitPct { get; set; }

        [NinjaScriptProperty, Range(1, 50)]
        [Display(Name = "MaxTradesPerDay", GroupName = "02-Risk", Order = 3)]
        public int MaxTradesPerDay { get; set; }

        [NinjaScriptProperty, Range(1, 20)]
        [Display(Name = "MaxConsecutiveLosses", GroupName = "02-Risk", Order = 4)]
        public int MaxConsecutiveLosses { get; set; }

        [NinjaScriptProperty, Range(1, 100)]
        [Display(Name = "UserMaxContracts", GroupName = "02-Risk", Order = 5)]
        public int UserMaxContracts { get; set; }

        [NinjaScriptProperty, Range(0.0, 100.0)]
        [Display(Name = "RoundTurnCommission ($)", GroupName = "02-Risk", Order = 6)]
        public double RoundTurnCommission { get; set; }

        [NinjaScriptProperty, Range(0, 20)]
        [Display(Name = "SlippageTicks", GroupName = "02-Risk", Order = 7)]
        public int SlippageTicks { get; set; }
        #endregion

        #region Setup toggles
        [NinjaScriptProperty]
        [Display(Name = "EnableLong", GroupName = "03-Setup", Order = 0)]
        public bool EnableLong { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "EnableShort", GroupName = "03-Setup", Order = 1)]
        public bool EnableShort { get; set; }
        #endregion

        #region Mean-reversion signal params
        [NinjaScriptProperty, Range(1, 200)]
        [Display(Name = "AtrPeriod", GroupName = "04-Signal", Order = 0)]
        public int AtrPeriod { get; set; }

        [NinjaScriptProperty, Range(1, 500)]
        [Display(Name = "MinVwapDistanceTicks", GroupName = "04-Signal", Order = 1)]
        public int MinVwapDistanceTicks { get; set; }

        [NinjaScriptProperty, Range(1, 10)]
        [Display(Name = "ReversalConfirmBars", GroupName = "04-Signal", Order = 2)]
        public int ReversalConfirmBars { get; set; }

        // 0=VWAP target ; 1=R-multiple
        [NinjaScriptProperty, Range(0, 1)]
        [Display(Name = "TargetMode (0=VWAP,1=R)", GroupName = "04-Signal", Order = 3)]
        public int TargetMode { get; set; }
        #endregion

        #region Stops / targets
        [NinjaScriptProperty, Range(0.05, 5.0)]
        [Display(Name = "AtrStopMult", GroupName = "05-Stops", Order = 0)]
        public double AtrStopMult { get; set; }

        [NinjaScriptProperty, Range(1, 200)]
        [Display(Name = "MinStopTicks", GroupName = "05-Stops", Order = 1)]
        public int MinStopTicks { get; set; }

        [NinjaScriptProperty, Range(1, 1000)]
        [Display(Name = "MaxStopTicks", GroupName = "05-Stops", Order = 2)]
        public int MaxStopTicks { get; set; }

        [NinjaScriptProperty, Range(0.1, 10.0)]
        [Display(Name = "RewardRiskRatio (used if TargetMode=1)", GroupName = "05-Stops", Order = 3)]
        public double RewardRiskRatio { get; set; }
        #endregion

        #region Trading windows (HHMM PT)
        [NinjaScriptProperty, Range(0, 2359)]
        [Display(Name = "TradeStartTime (HHMM PT)", GroupName = "07-Time", Order = 0)]
        public int TradeStartTime { get; set; }

        [NinjaScriptProperty, Range(0, 2359)]
        [Display(Name = "TradeEndTime (HHMM PT)", GroupName = "07-Time", Order = 1)]
        public int TradeEndTime { get; set; }

        [NinjaScriptProperty, Range(0, 2359)]
        [Display(Name = "ForceFlatTime (HHMM PT, 0=off)", GroupName = "07-Time", Order = 2)]
        public int ForceFlatTime { get; set; }
        #endregion

        // ====================================================================
        // OnStateChange
        // ====================================================================
        protected override void OnStateChange()
        {
            if (State == State.SetDefaults)
            {
                Description = @"NTA Micro VWAP Mean-Revert (post-open intraday). Risk Profile aware. v0.1";
                Name        = "NTAMicroVwapMeanRevertPilot";
                Calculate   = Calculate.OnBarClose;
                EntriesPerDirection                  = 1;
                EntryHandling                        = EntryHandling.AllEntries;
                IsExitOnSessionCloseStrategy         = true;
                ExitOnSessionCloseSeconds            = 30;
                IsFillLimitOnTouch                   = false;
                MaximumBarsLookBack                  = MaximumBarsLookBack.TwoHundredFiftySix;
                OrderFillResolution                  = OrderFillResolution.Standard;
                Slippage                             = 0;
                StartBehavior                        = StartBehavior.WaitUntilFlat;
                TimeInForce                          = TimeInForce.Day;
                TraceOrders                          = false;
                RealtimeErrorHandling                = RealtimeErrorHandling.StopCancelClose;
                StopTargetHandling                   = StopTargetHandling.PerEntryExecution;
                BarsRequiredToTrade                  = 60;
                IsInstantiatedOnEachOptimizationIteration = true;

                StartingCapital            = 0.0;
                IntradayOnly               = true;
                ActiveMarginPerContract    = 0.0;
                MaxContractsByCapital      = 0;
                InstrumentStatus           = "unknown";
                MarginSourceBroker         = "";

                RiskPerTradePct      = 2.0;
                MaxDailyLossPct      = 2.0;
                MaxDailyProfitPct    = 4.0;
                MaxTradesPerDay      = 4;
                MaxConsecutiveLosses = 3;
                UserMaxContracts     = 5;
                RoundTurnCommission  = 1.90;
                SlippageTicks        = 1;

                EnableLong  = true;
                EnableShort = true;

                AtrPeriod              = 14;
                MinVwapDistanceTicks   = 16;   // ~4 pts on MNQ ($8)
                ReversalConfirmBars    = 1;
                TargetMode             = 0;    // 0=VWAP

                AtrStopMult        = 1.0;
                MinStopTicks       = 12;
                MaxStopTicks       = 32;
                RewardRiskRatio    = 1.5;

                TradeStartTime          = 700;   // 07:00 PT = 10:00 ET
                TradeEndTime            = 830;   // 08:30 PT = 11:30 ET
                ForceFlatTime           = 1245;  // 12:45 PT = 15:45 ET
            }
            else if (State == State.Configure)
            {
                // Single-series. No AddDataSeries → OrderFillResolution=High supported.
            }
            else if (State == State.DataLoaded)
            {
                _atr        = ATR(AtrPeriod);
                _vwapSeries = new Series<double>(this);
                _vwapCumTPV = 0.0;
                _vwapCumVol = 0.0;

                _risk = new MRRiskManager(this);
                _risk.Init();

                Print("[INIT] NTAMicroVwapMeanRevertPilot v0.1 ready. " + _risk.Describe());
            }
        }

        // ====================================================================
        // OnBarUpdate
        // ====================================================================
        protected override void OnBarUpdate()
        {
            if (BarsInProgress != 0) return;
            if (CurrentBars[0] < 1) return;

            // ----- Session VWAP -----
            DateTime today = Time[0].Date;
            if (Bars.IsFirstBarOfSession || today != _sessionDate)
            {
                _vwapCumTPV = 0.0;
                _vwapCumVol = 0.0;
                _sessionDate = today;
                _risk.OnNewSession();
            }
            double tp  = (High[0] + Low[0] + Close[0]) / 3.0;
            double vol = Volume[0];
            _vwapCumTPV += tp * vol;
            _vwapCumVol += vol;
            _vwapSeries[0] = (_vwapCumVol > 0.0) ? (_vwapCumTPV / _vwapCumVol) : Close[0];

            if (CurrentBar < BarsRequiredToTrade) return;
            if (_risk.PermanentlyStopped) return;

            int todHHMM = ToTime(Time[0]) / 100;

            // TZ diag
            if (CurrentBar <= 3)
            {
                Print(string.Format("[TZ-DIAG] bar={0} Time[0]={1} HHMM={2} window=[{3}-{4}]",
                    CurrentBar, Time[0], todHHMM, TradeStartTime, TradeEndTime));
            }

            // Force flat
            bool nearSessionEnd = Bars.IsLastBarOfSession;
            bool atForceFlat    = (ForceFlatTime > 0 && todHHMM >= ForceFlatTime);
            if (IntradayOnly && (nearSessionEnd || atForceFlat))
            {
                CancelPendingEntry("force_flat");
                if (Position.MarketPosition == MarketPosition.Long)
                    ExitLong("FlatEOD", "MR_Long");
                else if (Position.MarketPosition == MarketPosition.Short)
                    ExitShort("FlatEOD", "MR_Short");
                return;
            }

            _risk.UpdateDailyStops();
            if (_risk.SessionStopped) return;

            // Window
            if (todHHMM < TradeStartTime || todHHMM > TradeEndTime) { LogSkip("outside_window"); return; }

            // If in position: handle VWAP-target exit
            if (Position.MarketPosition != MarketPosition.Flat)
            {
                ManageOpenPosition();
                return;
            }

            if (_pendingEntrySignal != null)
            {
                int barsSince = CurrentBar - _pendingEntryBar;
                if (barsSince >= 2) CancelPendingEntry("entry_timeout");
                else { LogSkip("pending_entry"); return; }
            }

            EvaluateEntry();
        }

        // ====================================================================
        // Entry evaluation
        // ====================================================================
        private void EvaluateEntry()
        {
            double vwap = _vwapSeries[0];
            double distTicks = (Close[0] - vwap) / TickSize;

            // ATR in ticks
            double atrTicks = _atr[0] / TickSize;
            int stopTicks = (int)Math.Round(atrTicks * AtrStopMult);
            if (stopTicks < MinStopTicks) stopTicks = MinStopTicks;
            if (stopTicks > MaxStopTicks) stopTicks = MaxStopTicks;

            bool overextLong  = distTicks <= -MinVwapDistanceTicks; // price below VWAP → fade short move → BUY
            bool overextShort = distTicks >=  MinVwapDistanceTicks; // price above VWAP → fade long move → SELL

            // Reversal confirmation:
            //   For LONG: last ReversalConfirmBars bars include at least one bull bar (Close>Open) and Close[0]>Close[1].
            //   For SHORT: mirror.
            bool revLong  = (Close[0] > Open[0]) && (Close[0] > Close[1]);
            bool revShort = (Close[0] < Open[0]) && (Close[0] < Close[1]);

            string sig = null;
            if (EnableLong  && overextLong  && revLong  && Close[0] < vwap) sig = "Long";
            if (sig == null && EnableShort && overextShort && revShort && Close[0] > vwap) sig = "Short";
            if (sig == null) { LogSkip("no_signal"); return; }

            int qty = _risk.ComputeQuantity(stopTicks, RoundTurnCommission, SlippageTicks);
            if (qty <= 0) { LogSkip("qty_zero"); return; }

            double entryPx = Close[0];
            double stopPx  = sig == "Long" ? entryPx - stopTicks * TickSize : entryPx + stopTicks * TickSize;
            double tgtPx;
            if (TargetMode == 0)
            {
                // VWAP target
                tgtPx = vwap;
            }
            else
            {
                double rTicks = stopTicks * RewardRiskRatio;
                tgtPx = sig == "Long" ? entryPx + rTicks * TickSize : entryPx - rTicks * TickSize;
            }

            // safety: target must be in the right direction
            if (sig == "Long" && tgtPx <= entryPx) { LogSkip("target_invalid"); return; }
            if (sig == "Short" && tgtPx >= entryPx) { LogSkip("target_invalid"); return; }

            _pendingEntrySignal   = sig;
            _pendingEntryBar      = CurrentBar;
            _pendingEntryQty      = qty;
            _pendingEntryStopPx   = stopPx;
            _pendingEntryTargetPx = tgtPx;
            _pendingStopTicks     = stopTicks;

            string sigName = sig == "Long" ? "MR_Long" : "MR_Short";
            SetStopLoss(sigName, CalculationMode.Price, stopPx, false);
            SetProfitTarget(sigName, CalculationMode.Price, tgtPx);

            if (sig == "Long")
                EnterLong(qty, sigName);
            else
                EnterShort(qty, sigName);

            Print(string.Format("[ENTRY] {0} qty={1} @={2:F2} stop={3:F2} ({4} ticks) tgt={5:F2} vwap={6:F2} dist={7:F1}t",
                sig, qty, entryPx, stopPx, stopTicks, tgtPx, vwap, distTicks));
        }

        private void ManageOpenPosition()
        {
            // VWAP-target mode: explicit exit when price crosses VWAP intra-bar.
            if (TargetMode != 0) return;
            double vwap = _vwapSeries[0];
            if (Position.MarketPosition == MarketPosition.Long && Close[0] >= vwap)
            {
                ExitLong("ExitVWAP", "MR_Long");
            }
            else if (Position.MarketPosition == MarketPosition.Short && Close[0] <= vwap)
            {
                ExitShort("ExitVWAP", "MR_Short");
            }
        }

        private void CancelPendingEntry(string reason)
        {
            if (_pendingEntrySignal == null) return;
            string sigName = _pendingEntrySignal == "Long" ? "MR_Long" : "MR_Short";
            // Best-effort cancel via overwriting submission (we used market entry; nothing to cancel server-side)
            _pendingEntrySignal = null;
            _pendingEntryBar = -1;
            _pendingEntryQty = 0;
        }

        private void LogSkip(string reason)
        {
            if (_lastSkipBar == CurrentBar && _lastSkipReason == reason) return;
            _lastSkipBar = CurrentBar; _lastSkipReason = reason;
        }

        // ====================================================================
        // Order / position events
        // ====================================================================
        protected override void OnExecutionUpdate(Execution execution, string executionId,
            double price, int quantity, MarketPosition marketPosition,
            string orderId, DateTime time)
        {
            if (execution == null || execution.Order == null) return;
            // Clear pending signal once entry fills.
            if (execution.Order.OrderState == OrderState.Filled)
            {
                if (_pendingEntrySignal != null &&
                    (execution.Order.Name == "MR_Long" || execution.Order.Name == "MR_Short"))
                {
                    _pendingEntrySignal = null;
                    _pendingEntryBar = -1;
                }
            }
        }

        protected override void OnPositionUpdate(Position position, double averagePrice,
            int quantity, MarketPosition marketPosition)
        {
            // Process realized trades for risk accounting.
            if (_risk == null) return;
            if (SystemPerformance == null || SystemPerformance.AllTrades == null) return;
            int n = SystemPerformance.AllTrades.Count;
            while (_risk.LastProcessedTradeCount < n)
            {
                var t = SystemPerformance.AllTrades[_risk.LastProcessedTradeCount];
                _risk.RecordClosedTrade(t, RoundTurnCommission);
                _risk.LastProcessedTradeCount++;
            }
        }

        // ====================================================================
        // RiskManager (nested) — copy of B1 RiskManager pattern, slimmed.
        // ====================================================================
        private class MRRiskManager
        {
            private readonly NTAMicroVwapMeanRevertPilot _s;

            public bool   PermanentlyStopped { get; private set; }
            public bool   SessionStopped     { get; private set; }
            public double CumulativeRealizedPnL { get; private set; }
            public double SessionRealizedPnL    { get; private set; }
            public double SessionStartEquity    { get; private set; }
            public int    TradesToday           { get; private set; }
            public int    ConsecutiveLosses     { get; private set; }
            public int    LastProcessedTradeCount { get; set; }

            public MRRiskManager(NTAMicroVwapMeanRevertPilot s) { _s = s; }

            public void Init()
            {
                PermanentlyStopped = false;
                SessionStopped = false;
                CumulativeRealizedPnL = 0.0;
                SessionRealizedPnL = 0.0;
                SessionStartEquity = _s.StartingCapital;
                TradesToday = 0;
                ConsecutiveLosses = 0;
                LastProcessedTradeCount = 0;

                if (_s.StartingCapital <= 0.0)
                { PermanentlyStopped = true; _s.Print("[RISK:stop] StartingCapital<=0"); }
                else if (string.Equals(_s.InstrumentStatus, "blocked", StringComparison.OrdinalIgnoreCase))
                { PermanentlyStopped = true; _s.Print("[RISK:stop] InstrumentStatus=blocked"); }
                else if (string.Equals(_s.InstrumentStatus, "unknown", StringComparison.OrdinalIgnoreCase))
                { PermanentlyStopped = true; _s.Print("[RISK:stop] InstrumentStatus=unknown"); }
                else if (_s.ActiveMarginPerContract <= 0.0)
                { PermanentlyStopped = true; _s.Print("[RISK:stop] ActiveMarginPerContract<=0"); }
                else if (_s.MaxContractsByCapital < 1)
                { PermanentlyStopped = true; _s.Print("[RISK:stop] MaxContractsByCapital<1"); }
            }

            public string Describe()
            {
                return string.Format(
                    "capital={0:F2} margin={1:F2} maxC={2} status={3} broker={4} intradayOnly={5}",
                    _s.StartingCapital, _s.ActiveMarginPerContract, _s.MaxContractsByCapital,
                    _s.InstrumentStatus, _s.MarginSourceBroker, _s.IntradayOnly);
            }

            public double CurrentEquity()
            {
                double unreal = 0.0;
                if (_s.Position != null && _s.Position.MarketPosition != MarketPosition.Flat
                    && _s.Position.Quantity > 0)
                {
                    unreal = _s.Position.GetUnrealizedProfitLoss(PerformanceUnit.Currency, _s.Close[0]);
                }
                return _s.StartingCapital + CumulativeRealizedPnL + unreal;
            }

            public void OnNewSession()
            {
                SessionRealizedPnL = 0.0;
                TradesToday = 0;
                ConsecutiveLosses = 0;
                SessionStopped = false;
                SessionStartEquity = _s.StartingCapital + CumulativeRealizedPnL;
            }

            public void UpdateDailyStops()
            {
                if (SessionStopped || PermanentlyStopped) return;
                double dailyStopUsd   = SessionStartEquity * _s.MaxDailyLossPct   / 100.0;
                double dailyProfitUsd = SessionStartEquity * _s.MaxDailyProfitPct / 100.0;
                if (SessionRealizedPnL <= -dailyStopUsd) { SessionStopped = true; return; }
                if (_s.MaxDailyProfitPct > 0 && SessionRealizedPnL >= dailyProfitUsd) { SessionStopped = true; return; }
                if (ConsecutiveLosses >= _s.MaxConsecutiveLosses) { SessionStopped = true; return; }
                if (TradesToday >= _s.MaxTradesPerDay) { SessionStopped = true; return; }
            }

            public int ComputeQuantity(int stopTicks, double commissionPerRT, int slippageTicks)
            {
                if (PermanentlyStopped) return 0;
                double tickValue = (_s.Instrument != null && _s.Instrument.MasterInstrument != null)
                    ? _s.Instrument.MasterInstrument.PointValue * _s.TickSize
                    : 0.0;
                if (tickValue <= 0.0) return 0;

                double equity = CurrentEquity();
                double riskBudget = equity * _s.RiskPerTradePct / 100.0;
                double contractRisk = stopTicks * tickValue + commissionPerRT + slippageTicks * tickValue;
                if (contractRisk <= 0.0) return 0;

                int byRisk   = (int)Math.Floor(riskBudget / contractRisk);
                int byMargin = (_s.ActiveMarginPerContract > 0.0)
                               ? (int)Math.Floor(equity / _s.ActiveMarginPerContract) : 0;

                int q = byRisk;
                if (byMargin > 0)                  q = Math.Min(q, byMargin);
                if (_s.MaxContractsByCapital > 0)  q = Math.Min(q, _s.MaxContractsByCapital);
                if (_s.UserMaxContracts > 0)       q = Math.Min(q, _s.UserMaxContracts);
                return q < 1 ? 0 : q;
            }

            public void RecordClosedTrade(NinjaTrader.Cbi.Trade t, double commissionPerRT)
            {
                double qty = Math.Max(1, t.Quantity);
                double pnl = t.ProfitCurrency - (commissionPerRT * qty);
                CumulativeRealizedPnL += pnl;
                SessionRealizedPnL    += pnl;
                TradesToday           += 1;
                if (pnl < 0) ConsecutiveLosses += 1;
                else         ConsecutiveLosses  = 0;
                _s.Print(string.Format("[EXIT] pnl={0:F2} cumPnL={1:F2} dayPnL={2:F2} tradesToday={3}",
                    pnl, CumulativeRealizedPnL, SessionRealizedPnL, TradesToday));
            }
        }
    }
}
