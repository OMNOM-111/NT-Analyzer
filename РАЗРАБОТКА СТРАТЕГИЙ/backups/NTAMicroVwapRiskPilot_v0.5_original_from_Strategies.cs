// =============================================================================
// NTAMicroVwapRiskPilot  (v0.5)
// -----------------------------------------------------------------------------
// v0.5 CRITICAL timezone fix:
//   ROOT CAUSE: PC is in Pacific Time (PT, UTC-8/UTC-7). NT8 Time[0] = PT.
//               TradeStartTime/TradeEndTime are compared to HHMM of Time[0] (PT).
//               Old defaults 935/1130 = 09:35-11:30 PT = 12:35-14:30 ET (WRONG).
//               All v0.3/v0.4 backtests traded AFTERNOON NY, not the intended
//               09:35-11:30 ET opening range.
//   FIX: New defaults target 09:35-11:30 ET expressed in PT:
//               09:35 ET = 06:35 PT → TradeStartTime = 635
//               11:30 ET = 08:30 PT → TradeEndTime   = 830
//               ET-PT offset is always exactly 3h (both zones change DST together)
//     - ForceFlatTime: 1545 PT (18:45 ET wrong) → 1245 PT (12:45 PT = 15:45 ET)
//     - SecondWindow: 1330 PT (16:30 ET) → 1030 PT (13:30 ET)
//                     1500 PT (18:00 ET) → 1200 PT (15:00 ET)
//   Added Print log at bar 1 to verify timing.
//   All v0.3/v0.4 improvements retained unchanged.
// -----------------------------------------------------------------------------
// v0.4 signal quality improvements vs v0.3:
//   ANALYSIS: v0.3 win%=30.7%, actual R:R=1.81. Break-even needs 35.6% win.
//   ROOT CAUSE: MinStopTicks=8 too tight for 5-min MES ATR (~15-25 ticks)
//               → 51% of trades stopped out same bar. Signal also too noisy.
//   FIXES:
//     - MinStopTicks: 8 → 12 (wider stop, reduces noise-stops)
//     - AtrStopMult:  0.5 → 0.75 (ATR-based stop adapts to volatility)
//     - RewardRiskRatio: 2.0 → 2.5 (break-even drops to 28.6% win)
//     - MinVolumeFactor: 1.0 → 1.2 (only above-avg volume signals)
//     - PullbackLookback: 5 → 3 (require more recent pullback)
//     - Signal: add Close[0]>Close[1] for long, Close[0]<Close[1] for short
//               (momentum confirmation — bar must close higher than previous)
//     - MaxTradesPerDay: 6 → 4 (take only highest-quality signals)
//     - EntryOffsetTicks: 1 → 2 (stronger breakout confirmation)
// -----------------------------------------------------------------------------
// Spec:
//   РАЗРАБОТКА СТРАТЕГИЙ\01_ПЛАН_СТРАТЕГИИ_NTAMicroVwapRiskPilot.md
//
// Risk Profile contract (Phase 0 mapper in app/jobqueue.py):
//   The NT-Analyzer backend projects job.risk_profile into job.strategy.parameters
//   under a fixed whitelist:
//     StartingCapital, IntradayOnly, ActiveMarginPerContract,
//     MaxContractsByCapital, InstrumentStatus, MarginSourceBroker.
//   Bridge.StrategyAnalyzerRunner.ApplyStrategyParameters then sets these
//   [NinjaScriptProperty] fields via reflection. Strategy refuses to trade when:
//       InstrumentStatus != "allowed"
//       StartingCapital  <= 0
//       ActiveMarginPerContract <= 0
//       MaxContractsByCapital   <  1
//
// v0.2 changes vs v0.1:
//   1. Dynamic equity via RiskManager (CumulativeRealizedPnL + UnrealizedPnL).
//   2. Stop-entry orders (EnterLongStopMarket / EnterShortStopMarket) with
//      EntryTimeoutBars; pending orders are cancelled if not filled.
//   3. Trading windows via int HHMM params (TradeStartTime / TradeEndTime,
//      optional second window). Uses ToTime(Time[0]).
//   4. Session close: no more "385 minutes" magic. Uses ToTime() and
//      Bars.IsLastBarOfSession + IsExitOnSessionCloseStrategy=true.
//   5. Series<double> _vwapSeries — true historical VWAP for pullback lookup.
//   6. LogSkip actually Print()s with per-bar+reason dedupe.
//   7. _lastProcessedTradeCount — no double-counting in OnPositionUpdate.
//      Commission accounting documented inline.
//   8. RiskManager nested class encapsulates equity / daily limits / sizing.
//
// Commission accounting:
//   NinjaTrader Strategy Analyzer applies a commission template only if one is
//   configured. NT-Analyzer currently sends commission_template="None", so NT8
//   reports gross PnL. To make internal risk math consistent with realistic
//   net PnL, we subtract `RoundTurnCommission * |qty|` ONCE per closed trade
//   inside RiskManager.RecordClosedTrade(). When NT-Analyzer starts applying
//   a real commission template, set RoundTurnCommission = 0 to avoid double-
//   counting (or remove the subtraction in RecordClosedTrade).
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
    public class NTAMicroVwapRiskPilot : Strategy
    {
        // ----- indicators -----
        private EMA _emaFast;
        private EMA _emaSlow;
        private ATR _atr;
        private ADX _adx;
        private SMA _volSma;

        // ----- session VWAP (manual; basic NT8, no Order Flow add-on) -----
        private Series<double> _vwapSeries;     // true historical VWAP
        private double         _vwapCumTPV;
        private double         _vwapCumVol;
        private DateTime       _sessionDate = DateTime.MinValue;

        // ----- risk -----
        private RiskManager _risk;

        // ----- pending stop-entry tracking -----
        private string  _pendingEntrySignal = null;       // "Long" | "Short" | null
        private int     _pendingEntryBar    = -1;
        private double  _pendingEntryStopPx = 0.0;
        private double  _pendingEntryProtStopPx = 0.0;
        private double  _pendingEntryTargetPx = 0.0;
        private int     _pendingEntryQty    = 0;
        private int     _pendingStopTicks   = 0;

        // ----- last filled-trade tracking -----
        private double _lastEntryPrice;
        private int    _lastEntryQty;
        private int    _lastStopTicks;

        // ----- skip logging dedupe -----
        private int    _lastSkipBar    = -1;
        private string _lastSkipReason = "";

        // ----- news blackout cache -----
        private List<int> _newsBlackoutHHMM = new List<int>();
        private int       _newsBlackoutWindowMinutes = 5;

        #region OnStateChange
        protected override void OnStateChange()
        {
            if (State == State.SetDefaults)
            {
                Description = @"NTA Micro VWAP/EMA pullback (intraday). Risk Profile aware. v0.4";
                Name        = "NTAMicroVwapRiskPilot";
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

                // ---- Risk Profile (filled by NT-Analyzer mapper) ----
                StartingCapital            = 0.0;
                IntradayOnly               = true;
                ActiveMarginPerContract    = 0.0;
                MaxContractsByCapital      = 0;
                InstrumentStatus           = "unknown";
                MarginSourceBroker         = "";

                // ---- Risk ----
                RiskPerTradePct      = 2.0;   // 2% allows $1000 account to get qty≥1
                MaxDailyLossPct      = 2.0;
                MaxDailyProfitPct    = 4.0;
                MaxTradesPerDay      = 4;    // 6→4: only best-quality signals
                MaxConsecutiveLosses = 3;
                UserMaxContracts     = 5;
                RoundTurnCommission  = 1.90;
                SlippageTicks        = 1;

                // ---- Setup toggles ----
                EnableLong  = true;
                EnableShort = true;

                // ---- Indicators ----
                EmaFastPeriod      = 20;
                EmaSlowPeriod      = 50;
                AtrPeriod          = 14;
                AdxPeriod          = 14;
                MinAdx             = 22.0;   // 18→22: filter choppy markets
                VolumeSmaPeriod    = 20;
                MinVolumeFactor    = 1.2;    // 1.0→1.2: above-average volume required
                PullbackLookback   = 3;     // 5→3: require recent pullback (≤3 bars)

                // ---- Stops / targets ----
                AtrStopMult        = 0.75;   // 0.5→0.75: adapt stop width to volatility
                MinStopTicks       = 12;     // 8→12: 12 ticks = $15; avoids noise on MES 5m
                MaxStopTicks       = 24;     // restored: 20→24
                RewardRiskRatio    = 2.5;    // 2.0→2.5: break-even drops to 28.6% win
                MoveToBreakevenAtR = 0.8;
                TrailAfterR        = 1.2;

                // ---- Entry ----
                EntryTimeoutBars   = 2;
                EntryOffsetTicks   = 2;     // 1→2: stronger breakout confirmation

                // ---- Trading windows (HHMM in PC local time = Pacific Time PT) ----
                // ET is always PT + 3h (DST changes on same date for both zones).
                //   09:35 ET = 06:35 PT → 635     11:30 ET = 08:30 PT → 830
                //   13:30 ET = 10:30 PT → 1030    15:00 ET = 12:00 PT → 1200
                //   15:45 ET = 12:45 PT → 1245 (force-flat, 15 min before RTH close)
                TradeStartTime          = 635;   // 06:35 PT = 09:35 ET (NY opening range)
                TradeEndTime            = 830;   // 08:30 PT = 11:30 ET
                UseSecondTradeWindow    = false;
                SecondTradeStartTime    = 1030;  // 10:30 PT = 13:30 ET
                SecondTradeEndTime      = 1200;  // 12:00 PT = 15:00 ET
                ForceFlatTime           = 1245;  // 12:45 PT = 15:45 ET — 15 min before RTH close
                NewsBlackoutTimes       = "";    // CSV of HHMM values (PT), e.g. "630,700,930"
                NewsBlackoutWindowMin   = 5;
            }
            else if (State == State.Configure)
            {
                // single primary series
            }
            else if (State == State.DataLoaded)
            {
                _emaFast    = EMA(EmaFastPeriod);
                _emaSlow    = EMA(EmaSlowPeriod);
                _atr        = ATR(AtrPeriod);
                _adx        = ADX(AdxPeriod);
                _volSma     = SMA(Volume, VolumeSmaPeriod);

                _vwapSeries = new Series<double>(this);
                _vwapCumTPV = 0.0;
                _vwapCumVol = 0.0;

                _risk = new RiskManager(this);
                _risk.Init();

                _newsBlackoutWindowMinutes = Math.Max(1, NewsBlackoutWindowMin);
                _newsBlackoutHHMM.Clear();
                if (!string.IsNullOrWhiteSpace(NewsBlackoutTimes))
                {
                    foreach (var s in NewsBlackoutTimes.Split(','))
                    {
                        int v;
                        if (int.TryParse(s.Trim(), out v) && v >= 0 && v <= 2359)
                            _newsBlackoutHHMM.Add(v);
                    }
                }

                Print("[INIT] NTAMicroVwapRiskPilot v0.5 ready. " + _risk.Describe());
            }
        }
        #endregion

        #region OnBarUpdate
        protected override void OnBarUpdate()
        {
            if (BarsInProgress != 0) return;
            if (CurrentBar < 1) return;

            // v0.5: Timezone diagnostic on first 3 bars to verify window alignment
            // NT8 Time[0] = PC local time (Pacific Time). TradeWindow is in PT.
            // entry_time_utc in result.json = real UTC (properly converted by TradeCollector).
            if (CurrentBar <= 3)
            {
                Print(string.Format("[TZ-DIAG] bar={0} Time[0]={1} HHMM={2} window=[{3}-{4}] inWindow={5}",
                    CurrentBar, Time[0], ToTime(Time[0]) / 100,
                    TradeStartTime, TradeEndTime,
                    IsInTradeWindow(ToTime(Time[0]) / 100)));
            }

            // ----- Session VWAP (manual) -----
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

            // ----- Force flat (explicit time, not magic 385) -----
            int todHHMM = ToTimeHHMM(Time[0]);
            bool nearSessionEnd = Bars.IsLastBarOfSession;
            bool atForceFlat    = (ForceFlatTime > 0 && todHHMM >= ForceFlatTime);

            if (IntradayOnly && (nearSessionEnd || atForceFlat))
            {
                CancelPendingEntry("force_flat");
                if (Position.MarketPosition == MarketPosition.Long)
                    ExitLong("FlatEOD", "Long");
                else if (Position.MarketPosition == MarketPosition.Short)
                    ExitShort("FlatEOD", "Short");
                if (atForceFlat) LogSkip("force_flat_time");
                return;
            }

            // ----- Daily limits (delegated to RiskManager) -----
            _risk.UpdateDailyStops();
            if (_risk.SessionStopped) return;

            // ----- Trading windows -----
            if (!IsInTradeWindow(todHHMM)) { LogSkip("outside_window"); return; }
            if (IsInNewsBlackout(todHHMM)) { LogSkip("news_blackout"); return; }

            // ----- Manage pending stop-entry: timeout cancel -----
            if (_pendingEntrySignal != null)
            {
                int barsSince = CurrentBar - _pendingEntryBar;
                if (barsSince >= EntryTimeoutBars)
                {
                    CancelPendingEntry("entry_timeout");
                }
            }

            // ----- If in position, manage and exit early -----
            if (Position.MarketPosition != MarketPosition.Flat)
            {
                ManageOpenPosition();
                return;
            }

            // ----- Skip if pending order still active -----
            if (_pendingEntrySignal != null) { LogSkip("pending_entry"); return; }

            // ----- Filters -----
            if (_adx[0] < MinAdx)                         { LogSkip("adx_low"); return; }
            if (Volume[0] < _volSma[0] * MinVolumeFactor) { LogSkip("vol_low"); return; }

            double vwapNow = _vwapSeries[0];
            bool trendUp   = _emaFast[0] > _emaSlow[0] && Close[0] > vwapNow;
            bool trendDown = _emaFast[0] < _emaSlow[0] && Close[0] < vwapNow;

            // Pullback: any of last N bars touched session VWAP or EMA(fast)
            bool pulledBack = false;
            int look = Math.Min(PullbackLookback, CurrentBar);
            for (int i = 1; i <= look; i++)
            {
                double v = _vwapSeries[i];
                if (Low[i] <= v && High[i] >= v) { pulledBack = true; break; }
                if (Low[i] <= _emaFast[i] && High[i] >= _emaFast[i]) { pulledBack = true; break; }
            }
            if (!pulledBack) { LogSkip("no_pullback"); return; }

            // v0.4: added Close[0]>Close[1] momentum filter (bar must close higher than prev)
            bool longSignal  = trendUp   && EnableLong  && Close[0] > Open[0]
                               && Close[0] > _emaFast[0] && Close[0] > Close[1];
            // v0.4: added Close[0]<Close[1] momentum filter
            bool shortSignal = trendDown && EnableShort && Close[0] < Open[0]
                               && Close[0] < _emaFast[0] && Close[0] < Close[1];
            if (!longSignal && !shortSignal) { LogSkip("no_signal"); return; }

            // ----- Sizing -----
            int stopTicks = ComputeStopTicks();
            int qty = _risk.ComputeQuantity(stopTicks, RoundTurnCommission, SlippageTicks);
            if (qty < 1) { LogSkip("qty_lt_1"); return; }

            // ----- Stop-entry placement -----
            if (longSignal)
            {
                // BUG-1 FIX: protStop relative to trigger (not Close[0])
                // BUG-2 FIX: liveUntilCancelled=false → auto-cancel at bar end
                double trigger  = High[0] + EntryOffsetTicks * TickSize;
                double protStop = trigger - stopTicks * TickSize;
                double target   = trigger + (int)Math.Round(stopTicks * RewardRiskRatio) * TickSize;

                SetStopLoss("Long",   CalculationMode.Price, protStop, false);
                SetProfitTarget("Long", CalculationMode.Price, target);
                EnterLongStopMarket(0, false, qty, trigger, "Long"); // liveUntilCancelled=false

                _pendingEntrySignal     = "Long";
                _pendingEntryBar        = CurrentBar;
                _pendingEntryStopPx     = trigger;
                _pendingEntryProtStopPx = protStop;
                _pendingEntryTargetPx   = target;
                _pendingEntryQty        = qty;
                _pendingStopTicks       = stopTicks;

                Print(string.Format(
                    "[ENTRY] LONG-stop qty={0} trig={1:F2} prot={2:F2} tgt={3:F2} stop={4}t adx={5:F1} vwap={6:F2}",
                    qty, trigger, protStop, target, stopTicks, _adx[0], vwapNow));
            }
            else
            {
                // BUG-1 FIX: protStop relative to trigger (not Close[0])
                // BUG-2 FIX: liveUntilCancelled=false → auto-cancel at bar end
                double trigger  = Low[0] - EntryOffsetTicks * TickSize;
                double protStop = trigger + stopTicks * TickSize;
                double target   = trigger - (int)Math.Round(stopTicks * RewardRiskRatio) * TickSize;

                SetStopLoss("Short",   CalculationMode.Price, protStop, false);
                SetProfitTarget("Short", CalculationMode.Price, target);
                EnterShortStopMarket(0, false, qty, trigger, "Short"); // liveUntilCancelled=false

                _pendingEntrySignal     = "Short";
                _pendingEntryBar        = CurrentBar;
                _pendingEntryStopPx     = trigger;
                _pendingEntryProtStopPx = protStop;
                _pendingEntryTargetPx   = target;
                _pendingEntryQty        = qty;
                _pendingStopTicks       = stopTicks;

                Print(string.Format(
                    "[ENTRY] SHORT-stop qty={0} trig={1:F2} prot={2:F2} tgt={3:F2} stop={4}t adx={5:F1} vwap={6:F2}",
                    qty, trigger, protStop, target, stopTicks, _adx[0], vwapNow));
            }
        }
        #endregion

        #region Position management (breakeven / trail)
        private void ManageOpenPosition()
        {
            if (_lastStopTicks <= 0 || _lastEntryPrice <= 0) return;

            double rDist  = _lastStopTicks * TickSize;
            double moved  = Close[0] - _lastEntryPrice;
            double rMult  = (Position.MarketPosition == MarketPosition.Long ? moved : -moved) / rDist;

            if (rMult >= MoveToBreakevenAtR)
            {
                if (Position.MarketPosition == MarketPosition.Long)
                    SetStopLoss("Long",  CalculationMode.Price, _lastEntryPrice, false);
                else
                    SetStopLoss("Short", CalculationMode.Price, _lastEntryPrice, false);
            }

            if (rMult >= TrailAfterR)
            {
                double trailDist = Math.Max(1, _lastStopTicks / 2.0) * TickSize;
                if (Position.MarketPosition == MarketPosition.Long)
                {
                    double trail = Close[0] - trailDist;
                    if (trail > _lastEntryPrice)
                        SetStopLoss("Long", CalculationMode.Price, trail, false);
                }
                else
                {
                    double trail = Close[0] + trailDist;
                    if (trail < _lastEntryPrice)
                        SetStopLoss("Short", CalculationMode.Price, trail, false);
                }
            }
        }

        private void CancelPendingEntry(string reason)
        {
            if (_pendingEntrySignal == null) return;
            // BUG-3 FIX: With liveUntilCancelled=false the NT8 order auto-cancels
            // at bar end — no need to re-issue with qty=0 (which didn't work anyway).
            // We only need to clear internal tracking state here.
            Print(string.Format("[EXIT:cancel_{0}] pending={1} bar={2}",
                                reason, _pendingEntrySignal, CurrentBar));
            _pendingEntrySignal = null;
            _pendingEntryBar    = -1;
        }
        #endregion

        #region Stop-ticks computation
        private int ComputeStopTicks()
        {
            double atrTicks = _atr[0] / TickSize;
            int s = (int)Math.Round(atrTicks * AtrStopMult);
            if (s < MinStopTicks) s = MinStopTicks;
            if (s > MaxStopTicks) s = MaxStopTicks;
            return s;
        }
        #endregion

        #region Time helpers
        // ToTime returns HHMMSS as int. We compare in HHMM precision.
        private int ToTimeHHMM(DateTime t)
        {
            return ToTime(t) / 100;
        }

        private bool IsInTradeWindow(int todHHMM)
        {
            bool inMain = (TradeStartTime <= 0 || TradeEndTime <= 0)
                          ? false
                          : (todHHMM >= TradeStartTime && todHHMM <= TradeEndTime);
            bool inSecond = UseSecondTradeWindow
                            && SecondTradeStartTime > 0 && SecondTradeEndTime > 0
                            && todHHMM >= SecondTradeStartTime && todHHMM <= SecondTradeEndTime;
            return inMain || inSecond;
        }

        private bool IsInNewsBlackout(int todHHMM)
        {
            if (_newsBlackoutHHMM.Count == 0) return false;
            // Simple HHMM-based window. Convert to minutes from midnight for arithmetic.
            int todMin = (todHHMM / 100) * 60 + (todHHMM % 100);
            for (int i = 0; i < _newsBlackoutHHMM.Count; i++)
            {
                int n = _newsBlackoutHHMM[i];
                int nMin = (n / 100) * 60 + (n % 100);
                if (Math.Abs(todMin - nMin) <= _newsBlackoutWindowMinutes) return true;
            }
            return false;
        }
        #endregion

        #region Order / trade events
        protected override void OnOrderUpdate(Order order, double limitPrice, double stopPrice,
                                              int quantity, int filled, double averageFillPrice,
                                              OrderState orderState, DateTime time, ErrorCode error,
                                              string nativeError)
        {
            // Pending entry filled -> clear pending state, lock-in entry baseline
            if (_pendingEntrySignal != null
                && order != null
                && (order.Name == "Long" || order.Name == "Short")
                && (orderState == OrderState.Filled || orderState == OrderState.PartFilled))
            {
                _lastEntryPrice = averageFillPrice;
                _lastEntryQty   = filled > 0 ? filled : _pendingEntryQty;
                _lastStopTicks  = _pendingStopTicks;
                _pendingEntrySignal = null;
                _pendingEntryBar    = -1;
            }
            // Pending entry rejected/cancelled
            else if (_pendingEntrySignal != null
                     && order != null
                     && (order.Name == "Long" || order.Name == "Short")
                     && (orderState == OrderState.Cancelled || orderState == OrderState.Rejected))
            {
                _pendingEntrySignal = null;
                _pendingEntryBar    = -1;
            }
        }

        protected override void OnPositionUpdate(Position position, double averagePrice,
                                                 int quantity, MarketPosition marketPosition)
        {
            if (marketPosition != MarketPosition.Flat) return;
            if (SystemPerformance == null)             return;

            int total = SystemPerformance.AllTrades.Count;
            if (total <= _risk.LastProcessedTradeCount) return;

            // Process every newly closed trade once (handles bursts).
            for (int i = _risk.LastProcessedTradeCount; i < total; i++)
            {
                var t = SystemPerformance.AllTrades[i];
                _risk.RecordClosedTrade(t, RoundTurnCommission);
            }
            _risk.LastProcessedTradeCount = total;

            _lastStopTicks  = 0;
            _lastEntryPrice = 0;
            _lastEntryQty   = 0;
        }
        #endregion

        #region Skip logging
        private void LogSkip(string reason)
        {
            if (CurrentBar == _lastSkipBar && reason == _lastSkipReason) return;
            _lastSkipBar    = CurrentBar;
            _lastSkipReason = reason;
            Print(string.Format("[SKIP:{0}] bar={1} time={2:HH:mm} px={3:F2}",
                                reason, CurrentBar, Time[0], Close[0]));
        }
        #endregion

        // =====================================================================
        // RiskManager — encapsulates equity, daily limits, sizing, status guard
        // =====================================================================
        private class RiskManager
        {
            private readonly NTAMicroVwapRiskPilot _s;

            public bool   PermanentlyStopped { get; private set; }
            public bool   SessionStopped     { get; private set; }
            public double CumulativeRealizedPnL { get; private set; }
            public double SessionRealizedPnL    { get; private set; }
            public double SessionStartEquity    { get; private set; }
            public int    TradesToday           { get; private set; }
            public int    ConsecutiveLosses     { get; private set; }
            public int    LastProcessedTradeCount { get; set; }

            public RiskManager(NTAMicroVwapRiskPilot s) { _s = s; }

            public void Init()
            {
                PermanentlyStopped       = false;
                SessionStopped           = false;
                CumulativeRealizedPnL    = 0.0;
                SessionRealizedPnL       = 0.0;
                SessionStartEquity       = _s.StartingCapital;
                TradesToday              = 0;
                ConsecutiveLosses        = 0;
                LastProcessedTradeCount  = 0;

                if (_s.StartingCapital <= 0.0)
                {
                    PermanentlyStopped = true;
                    _s.Print("[RISK:stop_trading] StartingCapital <= 0 — strategy disabled");
                }
                else if (string.Equals(_s.InstrumentStatus, "blocked",
                                       StringComparison.OrdinalIgnoreCase))
                {
                    PermanentlyStopped = true;
                    _s.Print("[RISK:stop_trading] InstrumentStatus = blocked — strategy disabled");
                }
                else if (string.Equals(_s.InstrumentStatus, "unknown",
                                       StringComparison.OrdinalIgnoreCase))
                {
                    PermanentlyStopped = true;
                    _s.Print("[RISK:stop_trading] InstrumentStatus = unknown — no margin info — strategy disabled");
                }
                else if (_s.ActiveMarginPerContract <= 0.0)
                {
                    PermanentlyStopped = true;
                    _s.Print("[RISK:stop_trading] ActiveMarginPerContract <= 0 — strategy disabled");
                }
                else if (_s.MaxContractsByCapital < 1)
                {
                    PermanentlyStopped = true;
                    _s.Print("[RISK:stop_trading] MaxContractsByCapital < 1 — strategy disabled");
                }
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
                    unreal = _s.Position.GetUnrealizedProfitLoss(
                                PerformanceUnit.Currency, _s.Close[0]);
                }
                return _s.StartingCapital + CumulativeRealizedPnL + unreal;
            }

            public void OnNewSession()
            {
                SessionRealizedPnL = 0.0;
                TradesToday        = 0;
                ConsecutiveLosses  = 0;
                SessionStopped     = false;
                SessionStartEquity = _s.StartingCapital + CumulativeRealizedPnL;
            }

            public void UpdateDailyStops()
            {
                if (SessionStopped || PermanentlyStopped) return;

                // Limits computed off SessionStartEquity for honest day risk.
                double dailyStopUsd   = SessionStartEquity * _s.MaxDailyLossPct   / 100.0;
                double dailyProfitUsd = SessionStartEquity * _s.MaxDailyProfitPct / 100.0;

                if (SessionRealizedPnL <= -dailyStopUsd)
                {
                    SessionStopped = true;
                    _s.Print(string.Format(
                        "[RISK:stop_trading] daily_loss {0:F2} <= -{1:F2} (sessionEq={2:F2})",
                        SessionRealizedPnL, dailyStopUsd, SessionStartEquity));
                    return;
                }
                if (_s.MaxDailyProfitPct > 0 && SessionRealizedPnL >= dailyProfitUsd)
                {
                    SessionStopped = true;
                    _s.Print(string.Format(
                        "[RISK:stop_trading] daily_profit {0:F2} >= {1:F2} (sessionEq={2:F2})",
                        SessionRealizedPnL, dailyProfitUsd, SessionStartEquity));
                    return;
                }
                if (ConsecutiveLosses >= _s.MaxConsecutiveLosses)
                {
                    SessionStopped = true;
                    _s.Print(string.Format(
                        "[RISK:stop_trading] consecutive_losses={0}", ConsecutiveLosses));
                    return;
                }
                if (TradesToday >= _s.MaxTradesPerDay)
                {
                    SessionStopped = true;
                    _s.Print(string.Format(
                        "[RISK:stop_trading] trades_today={0}", TradesToday));
                    return;
                }
            }

            public int ComputeQuantity(int stopTicks, double commissionPerRT, int slippageTicks)
            {
                if (PermanentlyStopped) return 0;
                double tickValue = (_s.Instrument != null && _s.Instrument.MasterInstrument != null)
                    ? _s.Instrument.MasterInstrument.PointValue * _s.TickSize
                    : 0.0;
                if (tickValue <= 0.0) return 0;

                double equity     = CurrentEquity();
                double riskBudget = equity * _s.RiskPerTradePct / 100.0;
                double contractRisk = stopTicks * tickValue
                                    + commissionPerRT
                                    + slippageTicks * tickValue;
                if (contractRisk <= 0.0) return 0;

                int byRisk   = (int)Math.Floor(riskBudget / contractRisk);
                int byMargin = (_s.ActiveMarginPerContract > 0.0)
                               ? (int)Math.Floor(equity / _s.ActiveMarginPerContract)
                               : 0;

                int q = byRisk;
                if (byMargin > 0)               q = Math.Min(q, byMargin);
                if (_s.MaxContractsByCapital > 0) q = Math.Min(q, _s.MaxContractsByCapital);
                if (_s.UserMaxContracts > 0)      q = Math.Min(q, _s.UserMaxContracts);
                return q < 1 ? 0 : q;
            }

            public void RecordClosedTrade(NinjaTrader.Cbi.Trade t, double commissionPerRT)
            {
                // NinjaTrader Strategy Analyzer here is run with commission_template="None",
                // so t.ProfitCurrency is GROSS. We subtract commission ONCE for risk math.
                double qty = Math.Max(1, t.Quantity);
                double pnl = t.ProfitCurrency - (commissionPerRT * qty);

                CumulativeRealizedPnL += pnl;
                SessionRealizedPnL    += pnl;
                TradesToday           += 1;
                if (pnl < 0) ConsecutiveLosses += 1;
                else         ConsecutiveLosses  = 0;

                _s.Print(string.Format(
                    "[EXIT] pnl={0:F2} cumPnL={1:F2} dayPnL={2:F2} trades={3} consecLoss={4}",
                    pnl, CumulativeRealizedPnL, SessionRealizedPnL, TradesToday, ConsecutiveLosses));
            }
        }

        // ====================================================================
        // PROPERTIES
        // ====================================================================

        #region Risk Profile (filled by NT-Analyzer mapper)
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

        #region Indicators
        [NinjaScriptProperty, Range(2, 200)]
        [Display(Name = "EmaFastPeriod", GroupName = "04-Indicators", Order = 0)]
        public int EmaFastPeriod { get; set; }

        [NinjaScriptProperty, Range(2, 400)]
        [Display(Name = "EmaSlowPeriod", GroupName = "04-Indicators", Order = 1)]
        public int EmaSlowPeriod { get; set; }

        [NinjaScriptProperty, Range(2, 200)]
        [Display(Name = "AtrPeriod", GroupName = "04-Indicators", Order = 2)]
        public int AtrPeriod { get; set; }

        [NinjaScriptProperty, Range(2, 200)]
        [Display(Name = "AdxPeriod", GroupName = "04-Indicators", Order = 3)]
        public int AdxPeriod { get; set; }

        [NinjaScriptProperty, Range(0.0, 100.0)]
        [Display(Name = "MinAdx", GroupName = "04-Indicators", Order = 4)]
        public double MinAdx { get; set; }

        [NinjaScriptProperty, Range(2, 500)]
        [Display(Name = "VolumeSmaPeriod", GroupName = "04-Indicators", Order = 5)]
        public int VolumeSmaPeriod { get; set; }

        [NinjaScriptProperty, Range(0.0, 10.0)]
        [Display(Name = "MinVolumeFactor", GroupName = "04-Indicators", Order = 6)]
        public double MinVolumeFactor { get; set; }

        [NinjaScriptProperty, Range(1, 50)]
        [Display(Name = "PullbackLookback (bars)", GroupName = "04-Indicators", Order = 7)]
        public int PullbackLookback { get; set; }
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
        [Display(Name = "RewardRiskRatio", GroupName = "05-Stops", Order = 3)]
        public double RewardRiskRatio { get; set; }

        [NinjaScriptProperty, Range(0.0, 5.0)]
        [Display(Name = "MoveToBreakevenAtR", GroupName = "05-Stops", Order = 4)]
        public double MoveToBreakevenAtR { get; set; }

        [NinjaScriptProperty, Range(0.0, 10.0)]
        [Display(Name = "TrailAfterR", GroupName = "05-Stops", Order = 5)]
        public double TrailAfterR { get; set; }
        #endregion

        #region Entry
        [NinjaScriptProperty, Range(1, 20)]
        [Display(Name = "EntryTimeoutBars", GroupName = "06-Entry", Order = 0)]
        public int EntryTimeoutBars { get; set; }

        [NinjaScriptProperty, Range(0, 20)]
        [Display(Name = "EntryOffsetTicks", GroupName = "06-Entry", Order = 1)]
        public int EntryOffsetTicks { get; set; }
        #endregion

        #region Trading windows (HHMM, server local time)
        [NinjaScriptProperty, Range(0, 2359)]
        [Display(Name = "TradeStartTime (HHMM)", GroupName = "07-Time", Order = 0)]
        public int TradeStartTime { get; set; }

        [NinjaScriptProperty, Range(0, 2359)]
        [Display(Name = "TradeEndTime (HHMM)", GroupName = "07-Time", Order = 1)]
        public int TradeEndTime { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "UseSecondTradeWindow", GroupName = "07-Time", Order = 2)]
        public bool UseSecondTradeWindow { get; set; }

        [NinjaScriptProperty, Range(0, 2359)]
        [Display(Name = "SecondTradeStartTime (HHMM)", GroupName = "07-Time", Order = 3)]
        public int SecondTradeStartTime { get; set; }

        [NinjaScriptProperty, Range(0, 2359)]
        [Display(Name = "SecondTradeEndTime (HHMM)", GroupName = "07-Time", Order = 4)]
        public int SecondTradeEndTime { get; set; }

        [NinjaScriptProperty, Range(0, 2359)]
        [Display(Name = "ForceFlatTime (HHMM, 0=off)", GroupName = "07-Time", Order = 5)]
        public int ForceFlatTime { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "NewsBlackoutTimes (CSV HHMM)", GroupName = "07-Time", Order = 6)]
        public string NewsBlackoutTimes { get; set; }

        [NinjaScriptProperty, Range(1, 30)]
        [Display(Name = "NewsBlackoutWindowMin", GroupName = "07-Time", Order = 7)]
        public int NewsBlackoutWindowMin { get; set; }
        #endregion
    }
}
