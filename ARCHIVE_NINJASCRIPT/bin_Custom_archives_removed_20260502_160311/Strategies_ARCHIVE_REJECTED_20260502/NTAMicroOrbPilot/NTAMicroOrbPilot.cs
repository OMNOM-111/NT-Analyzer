// =============================================================================
// NTAMicroOrbPilot  v0.1
// -----------------------------------------------------------------------------
// Independent Opening Range Breakout (ORB) module. Phase 9b second strategy.
// Designed to be COMPLEMENTARY to NTAMicroVwapRiskPilot (B1 short-only edge),
// NOT an extension of it. Single-series so OrderFillResolution=High works.
//
// Logic (close-confirmation, v0.1):
//   1. During ORRangeStart..ORRangeEnd (HHMM, PT) capture session High/Low.
//   2. After OR finalised, inside entry window TradeStartTime..TradeEndTime:
//        - Long  if Close[0] > ORHigh + EntryOffsetTicks*TickSize
//        - Short if Close[0] < ORLow  - EntryOffsetTicks*TickSize
//      Submit market entry (EnterLong/EnterShort) -> fills at NEXT bar open.
//   3. Only one entry per day (MaxORBTradesPerDay, default 1).
//   4. NO simultaneous stop-entry orders. Single managed market order only.
//   5. StopTicks  = clamp(round(ORRangeTicks * StopFraction), MinStopTicks, MaxStopTicks).
//   6. TargetTicks = StopTicks * RewardRiskRatio.
//   7. SetStopLoss / SetProfitTarget use CalculationMode.Ticks (anchored to fill price).
//   8. ForceFlatTime / IntradayOnly / SessionClose handling.
//
// Risk Profile contract is the same as NTAMicroVwapRiskPilot: NT-Analyzer mapper
// projects starting_capital / margins / status into:
//   StartingCapital, IntradayOnly, ActiveMarginPerContract,
//   MaxContractsByCapital, InstrumentStatus, MarginSourceBroker.
// Strategy refuses to trade when:
//   InstrumentStatus != "allowed" OR StartingCapital <= 0
//   OR ActiveMarginPerContract <= 0 OR MaxContractsByCapital < 1.
//
// Commission: NT-Analyzer sends commission_template=None and computes Adj metrics
// (gross - qty*RoundTurnCommission). The strategy itself does NOT subtract
// commission internally (avoids double counting).
//
// All times HHMM are in PC LOCAL time (Pacific Time on this machine).
// PT + 3h = ET (DST aligned). Default: OR=06:30-06:45 PT (09:30-09:45 ET),
// Entry=06:45-08:00 PT (09:45-11:00 ET), ForceFlat=12:45 PT (15:45 ET).
// =============================================================================

#region Using declarations
using System;
using System.ComponentModel;
using System.ComponentModel.DataAnnotations;
using NinjaTrader.Cbi;
using NinjaTrader.Data;
using NinjaTrader.NinjaScript;
using NinjaTrader.NinjaScript.Strategies;
#endregion

namespace NinjaTrader.NinjaScript.Strategies
{
    public class NTAMicroOrbPilot : Strategy
    {
        // ----- session tracking -----
        private DateTime _sessionDate  = DateTime.MinValue;
        private double   _orHigh       = double.NaN;
        private double   _orLow        = double.NaN;
        private bool     _orFinalized  = false;
        private int      _orBarCount   = 0;       // smoke: expect 3 bars for 15-min OR on 5-min chart
        private int      _trades_today = 0;
        private bool     _refusalLogged = false;

        // ----- per-day entry guard (close-confirmation, single market entry) -----
        // ----- per-day entry guard (close-confirmation, single market entry) -----
        private bool _entrySubmittedToday = false;

        #region OnStateChange
        protected override void OnStateChange()
        {
            if (State == State.SetDefaults)
            {
                Description = @"NTA Opening Range Breakout (intraday). Risk Profile aware. v0.1";
                Name        = "NTAMicroOrbPilot";
                Calculate                                 = Calculate.OnBarClose;
                EntriesPerDirection                       = 1;
                EntryHandling                             = EntryHandling.AllEntries;
                IsExitOnSessionCloseStrategy              = true;
                ExitOnSessionCloseSeconds                 = 30;
                IsFillLimitOnTouch                        = false;
                MaximumBarsLookBack                       = MaximumBarsLookBack.TwoHundredFiftySix;
                OrderFillResolution                       = OrderFillResolution.Standard;
                Slippage                                  = 0;
                StartBehavior                             = StartBehavior.WaitUntilFlat;
                TimeInForce                               = TimeInForce.Day;
                TraceOrders                               = false;
                RealtimeErrorHandling                     = RealtimeErrorHandling.StopCancelClose;
                StopTargetHandling                        = StopTargetHandling.PerEntryExecution;
                BarsRequiredToTrade                       = 5;
                IsInstantiatedOnEachOptimizationIteration = true;

                // ---- Risk Profile (filled by NT-Analyzer mapper) ----
                StartingCapital            = 0.0;
                IntradayOnly               = true;
                ActiveMarginPerContract    = 0.0;
                MaxContractsByCapital      = 0;
                InstrumentStatus           = "unknown";
                MarginSourceBroker         = "";

                // ---- Risk ----
                RiskPerTradePct      = 2.0;
                UserMaxContracts     = 5;
                RoundTurnCommission  = 1.90;
                SlippageTicks        = 1;
                MaxORBTradesPerDay   = 1;

                // ---- Setup toggles ----
                EnableLong  = true;
                EnableShort = true;

                // ---- Stops / targets ----
                StopFraction       = 0.5;
                MinStopTicks       = 12;
                MaxStopTicks       = 24;
                RewardRiskRatio    = 2.0;
                MinORRangeTicks    = 4;
                MaxORRangeTicks    = 200;

                // ---- Entry ----
                EntryOffsetTicks   = 1;
                EntryTimeoutBars   = 2;

                // ---- Trading windows (HHMM PT) ----
                // Defaults map to:
                //   OR window: 06:30-06:45 PT = 09:30-09:45 ET (15-min OR)
                //   Entry:     06:45-08:00 PT = 09:45-11:00 ET
                //   ForceFlat: 12:45 PT       = 15:45 ET (15 min before RTH close)
                ORRangeStartTime    = 630;
                ORRangeEndTime      = 645;
                TradeStartTime      = 645;
                TradeEndTime        = 800;
                ForceFlatTime       = 1245;
            }
            else if (State == State.Configure)
            {
                // Single-series. No AddDataSeries -> High OrderFillResolution available.
            }
            else if (State == State.DataLoaded)
            {
                _refusalLogged = false;
                Print("[INIT] NTAMicroOrbPilot v0.1 ready. " +
                      string.Format("Cap={0:F0} Inst={1} Margin={2:F0} MaxByCap={3} OR=[{4}-{5}] Entry=[{6}-{7}] FlatAt={8} TickSize={9}",
                          StartingCapital, InstrumentStatus, ActiveMarginPerContract, MaxContractsByCapital,
                          ORRangeStartTime, ORRangeEndTime, TradeStartTime, TradeEndTime, ForceFlatTime,
                          TickSize));
            }
        }
        #endregion

        #region OnBarUpdate
        protected override void OnBarUpdate()
        {
            if (BarsInProgress != 0) return;
            if (CurrentBar < BarsRequiredToTrade) return;

            // Risk Profile gate (refuse to trade if profile is invalid).
            if (!RiskProfileValid())
            {
                if (!_refusalLogged)
                {
                    Print(string.Format("[REFUSE] Risk profile invalid. Status={0} Cap={1} Margin={2} MaxByCap={3}",
                        InstrumentStatus, StartingCapital, ActiveMarginPerContract, MaxContractsByCapital));
                    _refusalLogged = true;
                }
                return;
            }

            int hhmm = ToHHMM(Time[0]);

            // ----- New session -----
            DateTime today = Time[0].Date;
            if (Bars.IsFirstBarOfSession || today != _sessionDate)
            {
                _sessionDate         = today;
                _orHigh              = double.NaN;
                _orLow               = double.NaN;
                _orFinalized         = false;
                _orBarCount          = 0;
                _trades_today        = 0;
                _entrySubmittedToday = false;
            }

            // ----- ForceFlat / EOD -----
            bool atForceFlat = (ForceFlatTime > 0 && hhmm >= ForceFlatTime);
            if (IntradayOnly && (Bars.IsLastBarOfSession || atForceFlat))
            {
                if (Position.MarketPosition == MarketPosition.Long)
                    ExitLong("FlatEOD", "OrbLong");
                else if (Position.MarketPosition == MarketPosition.Short)
                    ExitShort("FlatEOD", "OrbShort");
                return;
            }

            // ----- OR window: build range (inclusive on both ends) -----
            // For 5-min bars Calculate.OnBarClose: Time[0] is the bar close time.
            // [630, 645] inclusive captures 3 bars: close at 635, 640, 645 -> 15-min OR.
            if (hhmm >= ORRangeStartTime && hhmm <= ORRangeEndTime)
            {
                if (double.IsNaN(_orHigh) || High[0] > _orHigh) _orHigh = High[0];
                if (double.IsNaN(_orLow)  || Low[0]  < _orLow)  _orLow  = Low[0];
                _orBarCount++;
                return;
            }

            // ----- Finalize OR on first bar AFTER OR window closes -----
            if (!_orFinalized && hhmm > ORRangeEndTime && !double.IsNaN(_orHigh))
            {
                _orFinalized = true;
                int rTicks = (int)Math.Round((_orHigh - _orLow) / TickSize);
                Print(string.Format("[OR] {0:yyyy-MM-dd} H={1} L={2} rangeTicks={3} orBars={4} (expect 3 for 15-min/5-min)",
                    today, _orHigh, _orLow, rTicks, _orBarCount));
            }

            if (!_orFinalized) return;
            if (_entrySubmittedToday) return;
            if (_trades_today >= MaxORBTradesPerDay) return;

            // ----- Entry window guard -----
            if (!IsInRange(hhmm, TradeStartTime, TradeEndTime)) return;

            // ----- Already in position: skip -----
            if (Position.MarketPosition != MarketPosition.Flat) return;

            // ----- OR range filter -----
            int orTicks = (int)Math.Round((_orHigh - _orLow) / TickSize);
            if (orTicks < MinORRangeTicks || orTicks > MaxORRangeTicks) return;

            // ----- Close-confirmation breakout -----
            double upTrigger   = _orHigh + EntryOffsetTicks * TickSize;
            double downTrigger = _orLow  - EntryOffsetTicks * TickSize;

            bool longSig  = EnableLong  && Close[0] > upTrigger;
            bool shortSig = EnableShort && Close[0] < downTrigger;

            // If both fire on same close (rare wide bar), prefer none: ambiguous.
            if (longSig && shortSig) return;
            if (!longSig && !shortSig) return;

            int stopTicks = ComputeStopTicks(orTicks);
            int tgtTicks  = (int)Math.Max(1, Math.Round(stopTicks * RewardRiskRatio));
            int qty       = ComputeQty(stopTicks);
            if (qty < 1) return;

            if (longSig)
            {
                SetStopLoss("OrbLong",     CalculationMode.Ticks, stopTicks, false);
                SetProfitTarget("OrbLong", CalculationMode.Ticks, tgtTicks);
                EnterLong(qty, "OrbLong");
                _entrySubmittedToday = true;
                Print(string.Format("[SIGNAL_LONG] close={0} upTrigger={1} stopTicks={2} tgtTicks={3} qty={4}",
                    Close[0], upTrigger, stopTicks, tgtTicks, qty));
            }
            else
            {
                SetStopLoss("OrbShort",     CalculationMode.Ticks, stopTicks, false);
                SetProfitTarget("OrbShort", CalculationMode.Ticks, tgtTicks);
                EnterShort(qty, "OrbShort");
                _entrySubmittedToday = true;
                Print(string.Format("[SIGNAL_SHORT] close={0} dnTrigger={1} stopTicks={2} tgtTicks={3} qty={4}",
                    Close[0], downTrigger, stopTicks, tgtTicks, qty));
            }
        }
        #endregion

        #region Helpers
        private bool RiskProfileValid()
        {
            if (string.IsNullOrEmpty(InstrumentStatus)) return false;
            if (!string.Equals(InstrumentStatus, "allowed", StringComparison.OrdinalIgnoreCase)) return false;
            if (StartingCapital <= 0.0) return false;
            if (ActiveMarginPerContract <= 0.0) return false;
            if (MaxContractsByCapital < 1) return false;
            return true;
        }

        private int ToHHMM(DateTime t)
        {
            return t.Hour * 100 + t.Minute;
        }

        // True when start <= hhmm < end (handles equal start/end as empty).
        private bool IsInRange(int hhmm, int start, int end)
        {
            if (start == end) return false;
            if (start < end) return hhmm >= start && hhmm < end;
            // wraps midnight (rare in RTH); treat as union
            return hhmm >= start || hhmm < end;
        }

        private int ComputeStopTicks(int orTicks)
        {
            int s = (int)Math.Round(orTicks * StopFraction);
            if (s < MinStopTicks) s = MinStopTicks;
            if (s > MaxStopTicks) s = MaxStopTicks;
            return s;
        }

        private int ComputeQty(int stopTicks)
        {
            double tickValueDollars = Instrument.MasterInstrument.PointValue * TickSize;
            if (tickValueDollars <= 0.0) return 0;
            double riskDollars = StartingCapital * (RiskPerTradePct / 100.0);
            double slippageCost = Math.Max(0, SlippageTicks) * 2.0 * tickValueDollars;
            double riskPerContract = stopTicks * tickValueDollars + RoundTurnCommission + slippageCost;
            if (riskPerContract <= 0.0) return 0;

            int qtyByRisk = (int)Math.Floor(riskDollars / riskPerContract);
            if (qtyByRisk < 1) return 0;

            int qty = qtyByRisk;
            if (qty > UserMaxContracts) qty = UserMaxContracts;
            if (qty > MaxContractsByCapital) qty = MaxContractsByCapital;
            return qty;
        }

        private double NormalizePx(double px)
        {
            return Instrument.MasterInstrument.RoundToTickSize(px);
        }
        #endregion

        #region Events
        protected override void OnExecutionUpdate(Execution execution, string executionId, double price,
                                                  int quantity, MarketPosition marketPosition,
                                                  string orderId, DateTime time)
        {
            if (execution == null || execution.Order == null) return;
            string sig = execution.Order.Name;
            if ((sig == "OrbLong" || sig == "OrbShort") &&
                execution.Order.OrderState == OrderState.Filled)
            {
                bool isEntry = (sig == "OrbLong"  && marketPosition == MarketPosition.Long) ||
                               (sig == "OrbShort" && marketPosition == MarketPosition.Short);
                if (isEntry)
                {
                    _trades_today++;
                    Print(string.Format("[FILL] {0} qty={1} px={2} day_trades={3}",
                        sig, quantity, price, _trades_today));
                }
            }
        }
        #endregion

        // ====================================================================
        // PROPERTIES
        // ====================================================================

        #region Risk Profile (filled by NT-Analyzer mapper - Phase 0 bridge contract)
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

        [NinjaScriptProperty, Range(1, 100)]
        [Display(Name = "UserMaxContracts", GroupName = "02-Risk", Order = 1)]
        public int UserMaxContracts { get; set; }

        [NinjaScriptProperty, Range(0.0, 100.0)]
        [Display(Name = "RoundTurnCommission ($)", GroupName = "02-Risk", Order = 2)]
        public double RoundTurnCommission { get; set; }

        [NinjaScriptProperty, Range(0, 20)]
        [Display(Name = "SlippageTicks", GroupName = "02-Risk", Order = 3)]
        public int SlippageTicks { get; set; }

        [NinjaScriptProperty, Range(1, 10)]
        [Display(Name = "MaxORBTradesPerDay", GroupName = "02-Risk", Order = 4)]
        public int MaxORBTradesPerDay { get; set; }
        #endregion

        #region Setup
        [NinjaScriptProperty]
        [Display(Name = "EnableLong", GroupName = "03-Setup", Order = 0)]
        public bool EnableLong { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "EnableShort", GroupName = "03-Setup", Order = 1)]
        public bool EnableShort { get; set; }
        #endregion

        #region Stops
        [NinjaScriptProperty, Range(0.05, 5.0)]
        [Display(Name = "StopFraction (of OR range)", GroupName = "05-Stops", Order = 0)]
        public double StopFraction { get; set; }

        [NinjaScriptProperty, Range(1, 200)]
        [Display(Name = "MinStopTicks", GroupName = "05-Stops", Order = 1)]
        public int MinStopTicks { get; set; }

        [NinjaScriptProperty, Range(1, 1000)]
        [Display(Name = "MaxStopTicks", GroupName = "05-Stops", Order = 2)]
        public int MaxStopTicks { get; set; }

        [NinjaScriptProperty, Range(0.1, 10.0)]
        [Display(Name = "RewardRiskRatio", GroupName = "05-Stops", Order = 3)]
        public double RewardRiskRatio { get; set; }

        [NinjaScriptProperty, Range(1, 1000)]
        [Display(Name = "MinORRangeTicks", GroupName = "05-Stops", Order = 4)]
        public int MinORRangeTicks { get; set; }

        [NinjaScriptProperty, Range(1, 1000)]
        [Display(Name = "MaxORRangeTicks", GroupName = "05-Stops", Order = 5)]
        public int MaxORRangeTicks { get; set; }
        #endregion

        #region Entry
        [NinjaScriptProperty, Range(0, 20)]
        [Display(Name = "EntryOffsetTicks", GroupName = "06-Entry", Order = 0)]
        public int EntryOffsetTicks { get; set; }

        [NinjaScriptProperty, Range(1, 50)]
        [Display(Name = "EntryTimeoutBars (reserved, unused v0.1)", GroupName = "06-Entry", Order = 1)]
        public int EntryTimeoutBars { get; set; }
        #endregion

        #region Trading windows (HHMM PT)
        [NinjaScriptProperty, Range(0, 2359)]
        [Display(Name = "ORRangeStartTime (HHMM)", GroupName = "07-Time", Order = 0)]
        public int ORRangeStartTime { get; set; }

        [NinjaScriptProperty, Range(0, 2359)]
        [Display(Name = "ORRangeEndTime (HHMM)", GroupName = "07-Time", Order = 1)]
        public int ORRangeEndTime { get; set; }

        [NinjaScriptProperty, Range(0, 2359)]
        [Display(Name = "TradeStartTime (HHMM)", GroupName = "07-Time", Order = 2)]
        public int TradeStartTime { get; set; }

        [NinjaScriptProperty, Range(0, 2359)]
        [Display(Name = "TradeEndTime (HHMM)", GroupName = "07-Time", Order = 3)]
        public int TradeEndTime { get; set; }

        [NinjaScriptProperty, Range(0, 2359)]
        [Display(Name = "ForceFlatTime (HHMM, 0=off)", GroupName = "07-Time", Order = 4)]
        public int ForceFlatTime { get; set; }
        #endregion
    }
}
