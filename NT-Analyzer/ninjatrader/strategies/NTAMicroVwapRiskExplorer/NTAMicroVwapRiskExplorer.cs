// =============================================================================
// NTAMicroVwapRiskExplorer  (v0.5 — structural refactor)
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
// Structural refactor:
//   The single NTAMicroVwapRiskExplorer.cs has been split into partial class files:
//     NTAMicroVwapRiskExplorer.cs          — fields, OnStateChange, OnBarUpdate
//     NTAMicroVwapRiskExplorer.Properties.cs — all [NinjaScriptProperty] declarations
//     NTAMicroVwapRiskExplorer.RiskManager.cs — nested RiskManager class
//     NTAMicroVwapRiskExplorer.Entry.cs    — EvaluateEntry, ComputeStopTicks, CancelPending
//     NTAMicroVwapRiskExplorer.Position.cs — ManageOpenPosition
//     NTAMicroVwapRiskExplorer.Time.cs     — ToTimeHHMM, IsInTradeWindow, IsInNewsBlackout
//     NTAMicroVwapRiskExplorer.Events.cs   — OnOrderUpdate, OnPositionUpdate
//     NTAMicroVwapRiskExplorer.Diagnostics.cs — LogSkip
//   Trading logic is IDENTICAL to v0.5 — only file layout changed.
// -----------------------------------------------------------------------------
// Current profile:
//   NT-Analyzer/data/profiles/strategies.json
//
// Risk Profile contract:
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
    // Only this file declares the base class. All other files use:
    //   public partial class NTAMicroVwapRiskExplorer
    public abstract partial class NTAMicroVwapRiskExplorer : Strategy
    {
        // ----- indicators -----
        private EMA _emaFast;
        private EMA _emaSlow;
        private ATR _atr;
        private ADX _adx;
        private SMA _volSma;

        // ----- daily bias filter (BarsArray[1] = daily series, no lookahead) -----
        private EMA _dailyEmaFast;
        private EMA _dailyEmaSlow;

        // ----- session VWAP (manual; basic NT8, no Order Flow add-on) -----
        private Series<double> _vwapSeries;     // true historical VWAP
        private double         _vwapCumTPV;
        private double         _vwapCumVol;
        private DateTime       _sessionDate = DateTime.MinValue;

        // ----- risk -----
        private RiskManager _risk;

        // ----- pending stop-entry tracking -----
        private string  _pendingEntrySignal = null;
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
        private string _activeEntrySignal = null;

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
                Description = @"NTAMicroVwapRiskExplorer — research fork of NTAMicroVwapRiskPilot for non-MNQ Topstep micros. Same trading logic, used to find new instruments. NOT a paper-ready profile until validated.";
                Name        = "NTAMicroVwapRiskExplorer";
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

                // ---- Locked B1 ShortOnly paper profile defaults ----
                StartingCapital            = 2000.0;
                IntradayOnly               = true;
                ActiveMarginPerContract    = 50.0;
                MaxContractsByCapital      = 40;
                InstrumentStatus           = "allowed";
                MarginSourceBroker         = "NinjaTrader";

                // ---- Risk ----
                RiskPerTradePct      = 2.0;   // 2% allows $1000 account to get qty>=1
                MaxDailyLossPct      = 2.0;
                MaxDailyProfitPct    = 4.0;
                MaxTradesPerDay      = 4;    // 6->4: only best-quality signals
                MaxConsecutiveLosses = 3;
                UserMaxContracts     = 5;
                RoundTurnCommission  = 1.90;
                SlippageTicks        = 1;

                // ---- Setup toggles ----
                EnableLong  = false;
                EnableShort = true;

                // ---- Indicators ----
                EmaFastPeriod      = 50;     // B1 ShortOnly locked
                EmaSlowPeriod      = 200;    // B1 ShortOnly locked
                AtrPeriod          = 14;
                AdxPeriod          = 14;
                MinAdx             = 22.0;   // 18->22: filter choppy markets
                VolumeSmaPeriod    = 20;
                MinVolumeFactor    = 1.2;    // 1.0->1.2: above-average volume required
                PullbackLookback   = 3;     // 5->3: require recent pullback (<=3 bars)

                // ---- Stops / targets ----
                AtrStopMult        = 0.75;   // 0.5->0.75: adapt stop width to volatility
                MinStopTicks       = 12;     // 8->12: 12 ticks = $15; avoids noise on MES 5m
                MaxStopTicks       = 12;     // B1 ShortOnly locked
                RewardRiskRatio    = 3.5;    // B1 ShortOnly locked
                MoveToBreakevenAtR = 0.8;
                TrailAfterR        = 1.2;

                // ---- Entry ----
                EntryTimeoutBars   = 2;
                EntryOffsetTicks   = 2;     // 1->2: stronger breakout confirmation

                // ---- Trading windows (HHMM in PC local time = Pacific Time PT) ----
                // ET is always PT + 3h (DST changes on same date for both zones).
                //   09:35 ET = 06:35 PT -> 635     10:00 ET = 07:00 PT -> 700
                //   13:30 ET = 10:30 PT -> 1030    15:00 ET = 12:00 PT -> 1200
                //   15:45 ET = 12:45 PT -> 1245 (force-flat, 15 min before RTH close)
                TradeStartTime          = 635;   // 06:35 PT = 09:35 ET (NY opening range)
                TradeEndTime            = 700;   // 07:00 PT = 10:00 ET
                UseSecondTradeWindow    = false;
                SecondTradeStartTime    = 1030;  // 10:30 PT = 13:30 ET
                SecondTradeEndTime      = 1200;  // 12:00 PT = 15:00 ET
                ForceFlatTime           = 1245;  // 12:45 PT = 15:45 ET — 15 min before RTH close
                NewsBlackoutTimes       = "";    // CSV of HHMM values (PT), e.g. "630,700,930"
                NewsBlackoutWindowMin   = 5;

                // ---- Daily bias filter (default OFF for smoke / baseline verification) ----
                UseDailyBiasFilter          = false;
                DailyFastEmaPeriod          = 10;
                DailySlowEmaPeriod          = 30;
                BlockShortsWhenDailyBullish = true;
                BlockLongsWhenDailyBearish  = true;
            }
            else if (State == State.Configure)
            {
                // Primary 5-min series is added automatically.
                // Daily bars series only added when the daily bias filter is enabled.
                // Keeping the strategy single-series by default allows OrderFillResolution=High
                // for backtests. When UseDailyBiasFilter=true, BarsInProgress=1 is the daily series.
                if (UseDailyBiasFilter)
                    AddDataSeries(BarsPeriodType.Day, 1);
            }
            else if (State == State.DataLoaded)
            {
                _emaFast    = EMA(EmaFastPeriod);
                _emaSlow    = EMA(EmaSlowPeriod);
                _atr        = ATR(AtrPeriod);
                _adx        = ADX(AdxPeriod);
                _volSma     = SMA(Volume, VolumeSmaPeriod);

                // Daily bias EMAs — only created when the daily bias filter is enabled,
                // because BarsArray[1] only exists when AddDataSeries(Day,1) was called in Configure.
                // Leaving the strategy single-series by default keeps High OrderFillResolution available.
                if (UseDailyBiasFilter)
                {
                    _dailyEmaFast = EMA(BarsArray[1], DailyFastEmaPeriod);
                    _dailyEmaSlow = EMA(BarsArray[1], DailySlowEmaPeriod);
                }
                else
                {
                    _dailyEmaFast = null;
                    _dailyEmaSlow = null;
                }

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

                Print("[INIT] NTAMicroVwapRiskExplorer v0.5 ready. " + _risk.Describe());
            }
        }
        #endregion

        #region OnBarUpdate
        protected override void OnBarUpdate()
        {
            // Only act on the primary 5-min series. The daily series (BarsInProgress=1)
            // updates _dailyEmaFast/_dailyEmaSlow automatically but we do no trading there.
            if (BarsInProgress != 0) return;
            if (CurrentBars[0] < 1) return;

            // v0.5: Timezone diagnostic on first 3 bars to verify window alignment.
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
                    ExitLong("FlatEOD", ActiveEntrySignalForPosition());
                else if (Position.MarketPosition == MarketPosition.Short)
                    ExitShort("FlatEOD", ActiveEntrySignalForPosition());
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

            // ----- Daily bias warmup guard (need enough daily bars for EMA) -----
            if (UseDailyBiasFilter && CurrentBars[1] < DailySlowEmaPeriod + 1)
            {
                LogSkip("daily_warmup");
                return;
            }

            // ----- Entry evaluation (signal, sizing, stop-entry) -----
            EvaluateEntry(todHHMM);
        }
        #endregion
    }
}
