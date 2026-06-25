// =============================================================================
// NTAMicroMnqScalpPilot  (v0.1 — high-frequency MNQ intraday scalp)
// -----------------------------------------------------------------------------
// PURPOSE
//   Independent intraday scalping family for MNQ ($2000 capital, 1-Minute
//   primary timeframe). Lives ALONGSIDE the locked NTAMicroVwapRiskPilot B1
//   ShortOnly profile — does NOT replace, modify or share state with it.
//
//   Exposes four independent scalp modules, each with its own enable flag:
//
//     EnableVwapReclaim     — VWAP reclaim scalp.
//     EnableEmaMomentum     — EMA9/21/50 momentum burst after pullback.
//     EnableMicroOrb        — 3-minute OR break, retest, continuation.
//     EnableFailedBreakout  — local failed high/low breakout reversal.
//
//   SetupMode remains as an optional single-module research filter.
//
//   Risk shell mirrors NTAMicroVwapRiskPilot / NTAMicroSessionEdgeExplorer:
//   sizing, daily limits, position management, BE+trail, ATR-bounded stops.
//
// LOCKED PILOT NOT TOUCHED
//   NTAMicroVwapRiskPilot (B1 ShortOnly MNQ paper_ready) is read-only.
//
// COMMISSION ACCOUNTING
//   commission_template="None" upstream → NT8 reports gross PnL; we subtract
//   RoundTurnCommission * |qty| once per closed trade in RiskManager.
//
// TIMEZONE
//   PC = Pacific Time. NT8 Time[0] = PT. All HHMM windows in PT.
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
    public enum MnqScalpSetupMode
    {
        VwapPullbackScalp      = 0,
        OrbContinuationScalp   = 1,
        OrbRetestScalp         = 2,
        EmaImpulseScalp        = 3,
        FailedOrbReversalScalp = 4
    }

    public partial class NTAMicroMnqScalpPilot : Strategy
    {
        // ----- indicators -----
        private EMA _emaFast;       // default 9
        private EMA _emaMid;        // default 21
        private EMA _emaSlow;       // default 50 (optional trend filter)
        private ATR _atr;
        private ADX _adx;
        private SMA _volSma;

        // ----- session VWAP (manual; basic NT8) -----
        private Series<double> _vwapSeries;
        private double         _vwapCumTPV;
        private double         _vwapCumVol;
        private DateTime       _sessionDate = DateTime.MinValue;

        // ----- ORB state (per session) -----
        private double _orbHigh;
        private double _orbLow;
        private bool   _orbBuilt;
        private bool   _orbBreakoutLong;   // up-breakout already used
        private bool   _orbBreakoutShort;  // down-breakout already used
        private int    _orbBreakHighBar;   // bar idx of first close above orbHigh
        private int    _orbBreakLowBar;    // bar idx of first close below orbLow

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
        private Order   _pendingEntryOrder  = null;
        private bool    _pendingEntryCancelRequested = false;

        // ----- last filled-trade tracking -----
        private double _lastEntryPrice;
        private int    _lastEntryQty;
        private int    _lastStopTicks;
        private double _lastProtectiveStopPrice;
        private int    _lastEntryBar;     // for time-stop
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
                Description = @"NTAMicroMnqScalpPilot v0.4 — multi-mode high-frequency intraday scalp for MNQ. Independent from locked B1 ShortOnly Pilot.";
                Name        = "NTAMicroMnqScalpPilot";
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
                StartingCapital            = 2000.0;
                IntradayOnly               = true;
                ActiveMarginPerContract    = 100.0;
                MaxContractsByCapital      = 20;
                InstrumentStatus           = "allowed";
                MarginSourceBroker         = "NinjaTrader";

                // ---- Risk (scalp-tuned: more trades allowed, tighter daily loss) ----
                RiskPerTradePct      = 0.35;
                MaxDailyLossPct      = 3.0;   // fallback when MaxDailyLossUsd = 0
                MaxDailyLossUsd      = 60.0;
                MaxWeeklyLossUsd     = 150.0;
                MaxDailyProfitPct    = 0.0;   // off by default for high-freq
                MaxTradesPerDay      = 20;
                HardMaxTradesPerDay  = 25;
                MaxConsecutiveLosses = 3;
                PauseAfterConsecutiveLosses = 2;
                PauseMinutesAfterLosses     = 15;
                UserMaxContracts     = 1;     // 1 contract for $2000 MNQ
                MaxOpenPositions     = 1;
                RoundTurnCommission  = 1.90;
                SlippageTicks        = 1;

                // ---- SetupMode ----
                SetupMode = MnqScalpSetupMode.VwapPullbackScalp;
                UseSetupModeFilter = false;
                EnableVwapReclaim    = true;
                EnableEmaMomentum    = true;
                EnableMicroOrb       = true;
                EnableFailedBreakout = true;

                // ---- Direction ----
                EnableLong  = true;
                EnableShort = true;

                // ---- Indicators (scalp EMA stack 9/21/50) ----
                EmaFastPeriod      = 9;
                EmaMidPeriod       = 21;
                EmaSlowPeriod      = 50;
                AtrPeriod          = 14;
                AdxPeriod          = 14;
                MinAdx             = 0.0;     // off by default; explore in grid
                VolumeSmaPeriod    = 20;
                MinVolumeFactor    = 0.8;
                PullbackLookback   = 3;
                RequireSlowTrend   = false;   // EmaMid vs EmaSlow alignment for impulse

                // ---- Stops / targets (1m MNQ tick = $0.50) ----
                AtrStopMult        = 0.35;
                MinStopTicks       = 8;
                MaxStopTicks       = 16;
                RewardRiskRatio    = 1.25;
                MoveToBreakevenAtR = 0.7;
                TrailAfterR        = 1.0;

                // ---- Time-stop (scalp essential) ----
                UseTimeStop        = true;
                TimeStopBars       = 3;
                MinProgressR       = 0.30;

                // ---- Entry ----
                EntryTimeoutBars   = 2;
                EntryOffsetTicks   = 1;

                // ---- Trading windows (PT) — high-freq scalp uses both windows ----
                TradeStartTime          = 635;
                TradeEndTime            = 830;
                UseSecondTradeWindow    = true;
                SecondTradeStartTime    = 1030;
                SecondTradeEndTime      = 1200;
                ForceFlatTime           = 1245;
                NewsBlackoutTimes       = "";
                NewsBlackoutWindowMin   = 5;

                // ---- ORB (3-min micro ORB per ГПТ + retest) ----
                OrbStartTime        = 630;
                OrbDurationMinutes  = 3;
                OrbBreakoutBuffer   = 1;
                OrbRetestBars       = 5;
                OrbFailedLookback   = 3;

                // ---- EMA impulse ----
                EmaImpulseLookback  = 3;  // last N bars must be directional
            }
            else if (State == State.Configure)
            {
                // No daily series for scalp by default.
            }
            else if (State == State.DataLoaded)
            {
                _emaFast = EMA(EmaFastPeriod);
                _emaMid  = EMA(EmaMidPeriod);
                _emaSlow = EMA(EmaSlowPeriod);
                _atr     = ATR(AtrPeriod);
                _adx     = ADX(AdxPeriod);
                _volSma  = SMA(Volume, VolumeSmaPeriod);

                _vwapSeries = new Series<double>(this);
                _vwapCumTPV = 0.0;
                _vwapCumVol = 0.0;

                ResetOrbState();

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

                Print("[INIT] NTAMicroMnqScalpPilot v0.4 modules="
                    + "vwap=" + EnableVwapReclaim
                    + ",ema=" + EnableEmaMomentum
                    + ",orb=" + EnableMicroOrb
                    + ",fail=" + EnableFailedBreakout
                    + ",filter=" + UseSetupModeFilter
                    + ",mode=" + SetupMode + " " + _risk.Describe());
            }
            else if (State == State.Realtime)
            {
                int historicalTrades = (SystemPerformance == null)
                    ? 0
                    : SystemPerformance.AllTrades.Count;
                if (_risk != null)
                    _risk.ResetForRealtime(historicalTrades);
            }
        }
        #endregion

        #region OnBarUpdate
        protected override void OnBarUpdate()
        {
            if (BarsInProgress != 0) return;
            if (CurrentBars[0] < 1) return;

            if (CurrentBar <= 3)
            {
                Print(string.Format("[TZ-DIAG] bar={0} Time[0]={1} HHMM={2} mode={3} window=[{4}-{5}] inWindow={6}",
                    CurrentBar, Time[0], ToTime(Time[0]) / 100, SetupMode,
                    TradeStartTime, TradeEndTime,
                    IsInTradeWindow(ToTime(Time[0]) / 100)));
            }

            // ----- Session VWAP -----
            DateTime today = Time[0].Date;
            if (Bars.IsFirstBarOfSession || today != _sessionDate)
            {
                _vwapCumTPV = 0.0;
                _vwapCumVol = 0.0;
                _sessionDate = today;
                _risk.OnNewSession();
                ResetOrbState();
            }
            double tp  = (High[0] + Low[0] + Close[0]) / 3.0;
            double vol = Volume[0];
            _vwapCumTPV += tp * vol;
            _vwapCumVol += vol;
            _vwapSeries[0] = (_vwapCumVol > 0.0) ? (_vwapCumTPV / _vwapCumVol) : Close[0];

            // ----- Update ORB state -----
            UpdateOrbState();

            if (IsLiveHistoricalWarmup()) return;

            if (CurrentBar < BarsRequiredToTrade) return;
            if (_risk.PermanentlyStopped) return;

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

            _risk.UpdateDailyStops();
            if (_risk.SessionStopped) return;

            if (!IsInTradeWindow(todHHMM)) { LogSkip("outside_window"); return; }
            if (IsInNewsBlackout(todHHMM)) { LogSkip("news_blackout"); return; }
            if (_risk.IsPaused(Time[0])) { LogSkip("loss_pause"); return; }

            if (_pendingEntrySignal != null)
            {
                int barsSince = CurrentBar - _pendingEntryBar;
                if (barsSince >= EntryTimeoutBars)
                    CancelPendingEntry("entry_timeout");
            }

            if (Position.MarketPosition != MarketPosition.Flat)
            {
                ManageOpenPosition();
                return;
            }

            if (_pendingEntrySignal != null) { LogSkip("pending_entry"); return; }

            EvaluateEnabledModules(todHHMM);
        }
        #endregion

        #region Module dispatch
        private void EvaluateEnabledModules(int todHHMM)
        {
            if (UseSetupModeFilter)
            {
                switch (SetupMode)
                {
                    case MnqScalpSetupMode.VwapPullbackScalp:
                        if (EnableVwapReclaim) EvaluateEntry_VwapPullbackScalp(todHHMM);
                        break;
                    case MnqScalpSetupMode.OrbContinuationScalp:
                        if (EnableMicroOrb) EvaluateEntry_OrbContinuationScalp(todHHMM);
                        break;
                    case MnqScalpSetupMode.OrbRetestScalp:
                        if (EnableMicroOrb) EvaluateEntry_OrbRetestScalp(todHHMM);
                        break;
                    case MnqScalpSetupMode.EmaImpulseScalp:
                        if (EnableEmaMomentum) EvaluateEntry_EmaImpulseScalp(todHHMM);
                        break;
                    case MnqScalpSetupMode.FailedOrbReversalScalp:
                        if (EnableFailedBreakout) EvaluateEntry_FailedOrbReversalScalp(todHHMM);
                        break;
                    default:
                        if (EnableVwapReclaim) EvaluateEntry_VwapPullbackScalp(todHHMM);
                        break;
                }
                return;
            }

            if (EnableVwapReclaim)
            {
                EvaluateEntry_VwapPullbackScalp(todHHMM);
                if (_pendingEntrySignal != null) return;
            }
            if (EnableEmaMomentum)
            {
                EvaluateEntry_EmaImpulseScalp(todHHMM);
                if (_pendingEntrySignal != null) return;
            }
            if (EnableMicroOrb)
            {
                EvaluateEntry_OrbContinuationScalp(todHHMM);
                if (_pendingEntrySignal != null) return;
                EvaluateEntry_OrbRetestScalp(todHHMM);
                if (_pendingEntrySignal != null) return;
            }
            if (EnableFailedBreakout)
                EvaluateEntry_FailedOrbReversalScalp(todHHMM);
        }
        #endregion

        #region ORB state helpers
        private void ResetOrbState()
        {
            _orbHigh = double.NaN;
            _orbLow  = double.NaN;
            _orbBuilt = false;
            _orbBreakoutLong  = false;
            _orbBreakoutShort = false;
            _orbBreakHighBar = -1;
            _orbBreakLowBar  = -1;
        }

        // OR window = [OrbStartTime, OrbStartTime + OrbDurationMinutes].
        private void UpdateOrbState()
        {
            int startHHMM = OrbStartTime > 0 ? OrbStartTime : TradeStartTime;
            if (startHHMM <= 0) return;

            int todMin = HhmmToMin(ToTimeHHMM(Time[0]));
            int orStartMin = HhmmToMin(startHHMM);
            int orEndMin   = orStartMin + Math.Max(1, OrbDurationMinutes);

            if (todMin < orStartMin) return;

            if (!_orbBuilt && todMin <= orEndMin)
            {
                if (double.IsNaN(_orbHigh) || High[0] > _orbHigh) _orbHigh = High[0];
                if (double.IsNaN(_orbLow)  || Low[0]  < _orbLow)  _orbLow  = Low[0];
            }
            else if (!_orbBuilt)
            {
                if (!double.IsNaN(_orbHigh) && !double.IsNaN(_orbLow))
                    _orbBuilt = true;
            }

            // Track first break-bar after OR built (for retest mode).
            if (_orbBuilt)
            {
                if (_orbBreakHighBar < 0 && Close[0] > _orbHigh) _orbBreakHighBar = CurrentBar;
                if (_orbBreakLowBar  < 0 && Close[0] < _orbLow)  _orbBreakLowBar  = CurrentBar;
            }
        }

        private static int HhmmToMin(int hhmm)
        {
            return (hhmm / 100) * 60 + (hhmm % 100);
        }
        #endregion
    }
}
