// =============================================================================
// NTAMicroSessionEdgeExplorer  (v0.1 — multi-mode research strategy)
// -----------------------------------------------------------------------------
// PURPOSE
//   Modular research strategy for non-MNQ local micro futures. Exposes a
//   `SetupMode` parameter that dispatches to different entry families:
//
//     VwapPullback        — bit-for-bit equivalent to NTAMicroVwapRiskExplorer
//                           v0.5 entry logic. Default. Compile-safe baseline.
//     OrbContinuation     — Opening Range Breakout in trade direction.
//     FailedOrbReversal   — Reversal back through OR after failed breakout.
//     VwapMeanReversion   — Fade extension from session VWAP (metals).
//     CompressionBreakout — Break out of low-volatility regime (energy).
//     RollingVwapCrypto   — 24h rolling VWAP cross + momentum (MBT/MET).
//
//   Risk shell (RiskManager, sizing, daily limits, position management,
//   session VWAP, stops/targets, trailing) is identical to the Explorer.
//
// LOCKED PILOT NOT TOUCHED
//   NTAMicroVwapRiskPilot (and its locked B1 ShortOnly MNQ profile) is the
//   ONLY paper-ready strategy. This new class lives alongside it as research.
//   MNQ is excluded from this strategy's research universe.
//
// COMMISSION ACCOUNTING
//   commission_template="None" upstream → NT8 reports gross PnL; we subtract
//   RoundTurnCommission * |qty| once per closed trade in RiskManager. Same
//   convention as the Pilot/Explorer.
//
// TIMEZONE
//   PC = Pacific Time. NT8 Time[0] = PT. All HHMM windows in PT.
//   ET = PT + 3h (constant; both observe DST on same dates).
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
    public enum SessionEdgeSetupMode
    {
        VwapPullback        = 0,
        OrbContinuation     = 1,
        FailedOrbReversal   = 2,
        VwapMeanReversion   = 3,
        CompressionBreakout = 4,
        RollingVwapCrypto   = 5
    }

    public abstract partial class NTAMicroSessionEdgeExplorer : Strategy
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
        private Series<double> _vwapSeries;
        private double         _vwapCumTPV;
        private double         _vwapCumVol;
        private DateTime       _sessionDate = DateTime.MinValue;

        // ----- rolling 24h VWAP for crypto (ring buffer) -----
        // 24h of 5-min bars = 288. Generic for any periodicity, sized by RollingVwapBars.
        private double[] _ringTPV;
        private double[] _ringVol;
        private int      _ringIdx;
        private int      _ringFilled;
        private double   _ringSumTPV;
        private double   _ringSumVol;
        private Series<double> _rollingVwapSeries;

        // ----- ORB state (per session) -----
        private double _orbHigh;
        private double _orbLow;
        private bool   _orbBuilt;          // true once OR window has closed
        private bool   _orbBreakoutLong;   // breakout above OR high already happened today
        private bool   _orbBreakoutShort;  // breakout below OR low already happened today
        private int    _orbBreakoutBar;    // bar index of the breakout (for failed-reversal lookback)
        private double _orbBreakoutPrice;  // close at breakout bar

        // ----- compression state -----
        private double _recentHigh;        // rolling high over CompressionLookback bars
        private double _recentLow;         // rolling low over CompressionLookback bars

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
                Description = @"NTAMicroSessionEdgeExplorer v0.1 — multi-SetupMode research strategy for non-MNQ micros. Default SetupMode=VwapPullback is identical to NTAMicroVwapRiskExplorer baseline.";
                Name        = "NTAMicroSessionEdgeExplorer";
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
                ActiveMarginPerContract    = 50.0;
                MaxContractsByCapital      = 40;
                InstrumentStatus           = "allowed";
                MarginSourceBroker         = "NinjaTrader";

                // ---- Risk ----
                RiskPerTradePct      = 2.0;
                MaxDailyLossPct      = 2.0;
                MaxDailyProfitPct    = 4.0;
                MaxTradesPerDay      = 4;
                MaxConsecutiveLosses = 3;
                UserMaxContracts     = 5;
                RoundTurnCommission  = 1.90;
                SlippageTicks        = 1;

                // ---- SetupMode ----
                SetupMode = SessionEdgeSetupMode.VwapPullback;

                // ---- Setup toggles ----
                EnableLong  = false;
                EnableShort = true;

                // ---- Indicators ----
                EmaFastPeriod      = 50;
                EmaSlowPeriod      = 200;
                AtrPeriod          = 14;
                AdxPeriod          = 14;
                MinAdx             = 22.0;
                VolumeSmaPeriod    = 20;
                MinVolumeFactor    = 1.2;
                PullbackLookback   = 3;

                // ---- Stops / targets ----
                AtrStopMult        = 0.75;
                MinStopTicks       = 12;
                MaxStopTicks       = 12;
                RewardRiskRatio    = 3.5;
                MoveToBreakevenAtR = 0.8;
                TrailAfterR        = 1.2;

                // ---- Entry ----
                EntryTimeoutBars   = 2;
                EntryOffsetTicks   = 2;

                // ---- Trading windows (PT) ----
                TradeStartTime          = 635;
                TradeEndTime            = 700;
                UseSecondTradeWindow    = false;
                SecondTradeStartTime    = 1030;
                SecondTradeEndTime      = 1200;
                ForceFlatTime           = 1245;
                NewsBlackoutTimes       = "";
                NewsBlackoutWindowMin   = 5;

                // ---- Daily bias filter ----
                UseDailyBiasFilter          = false;
                DailyFastEmaPeriod          = 10;
                DailySlowEmaPeriod          = 30;
                BlockShortsWhenDailyBullish = true;
                BlockLongsWhenDailyBearish  = true;

                // ---- ORB ----
                OrbDurationMinutes  = 30;   // build OR over first 30 min after TradeStartTime
                OrbBreakoutBuffer   = 1;    // ticks beyond OR for breakout confirmation
                OrbFailedLookback   = 3;    // bars after breakout to detect failed move

                // ---- Mean reversion ----
                MeanRevExtensionAtr = 1.5;  // |Close - VWAP| / ATR threshold
                MeanRevTargetVwap   = true; // exit at VWAP (overrides RewardRiskRatio target)

                // ---- Compression ----
                CompressionLookback = 30;   // bars used for ATR percentile + recent extreme
                CompressionAtrPct   = 0.30; // current ATR must be in lowest 30% of lookback

                // ---- Rolling VWAP (crypto) ----
                RollingVwapBars     = 288;  // 24h of 5-min bars
                Use24hSession       = false;// when true, ignore TradeStartTime/TradeEndTime/ForceFlatTime
            }
            else if (State == State.Configure)
            {
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

                int rb = Math.Max(10, RollingVwapBars);
                _ringTPV    = new double[rb];
                _ringVol    = new double[rb];
                _ringIdx    = 0;
                _ringFilled = 0;
                _ringSumTPV = 0.0;
                _ringSumVol = 0.0;
                _rollingVwapSeries = new Series<double>(this);

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

                Print("[INIT] NTAMicroSessionEdgeExplorer v0.1 mode=" + SetupMode + " " + _risk.Describe());
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

            // ----- Session VWAP (manual) -----
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

            // ----- Rolling 24h VWAP (used by RollingVwapCrypto, harmless otherwise) -----
            int rb = _ringTPV.Length;
            double evictTPV = _ringTPV[_ringIdx];
            double evictVol = _ringVol[_ringIdx];
            _ringSumTPV += (tp * vol) - evictTPV;
            _ringSumVol += vol - evictVol;
            _ringTPV[_ringIdx] = tp * vol;
            _ringVol[_ringIdx] = vol;
            _ringIdx = (_ringIdx + 1) % rb;
            if (_ringFilled < rb) _ringFilled++;
            _rollingVwapSeries[0] = (_ringSumVol > 0.0) ? (_ringSumTPV / _ringSumVol) : Close[0];

            // ----- Update ORB state every bar (cheap; only meaningful for ORB modes) -----
            UpdateOrbState();

            // ----- Update rolling extreme for compression -----
            int cl = Math.Max(2, CompressionLookback);
            int look = Math.Min(cl, CurrentBar);
            double rh = High[0]; double rl = Low[0];
            for (int i = 1; i <= look; i++)
            {
                if (High[i] > rh) rh = High[i];
                if (Low[i]  < rl) rl = Low[i];
            }
            _recentHigh = rh;
            _recentLow  = rl;

            if (CurrentBar < BarsRequiredToTrade) return;
            if (_risk.PermanentlyStopped) return;

            int todHHMM = ToTimeHHMM(Time[0]);
            bool nearSessionEnd = Bars.IsLastBarOfSession;
            bool atForceFlat    = (ForceFlatTime > 0 && todHHMM >= ForceFlatTime);
            bool intradayActive = IntradayOnly && !Use24hSession;

            if (intradayActive && (nearSessionEnd || atForceFlat))
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

            if (!Use24hSession)
            {
                if (!IsInTradeWindow(todHHMM)) { LogSkip("outside_window"); return; }
                if (IsInNewsBlackout(todHHMM)) { LogSkip("news_blackout"); return; }
            }

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

            if (UseDailyBiasFilter && CurrentBars[1] < DailySlowEmaPeriod + 1)
            {
                LogSkip("daily_warmup");
                return;
            }

            // ----- Dispatch by SetupMode -----
            switch (SetupMode)
            {
                case SessionEdgeSetupMode.VwapPullback:
                    EvaluateEntry_VwapPullback(todHHMM);
                    break;
                case SessionEdgeSetupMode.OrbContinuation:
                    EvaluateEntry_OrbContinuation(todHHMM);
                    break;
                case SessionEdgeSetupMode.FailedOrbReversal:
                    EvaluateEntry_FailedOrbReversal(todHHMM);
                    break;
                case SessionEdgeSetupMode.VwapMeanReversion:
                    EvaluateEntry_VwapMeanReversion(todHHMM);
                    break;
                case SessionEdgeSetupMode.CompressionBreakout:
                    EvaluateEntry_CompressionBreakout(todHHMM);
                    break;
                case SessionEdgeSetupMode.RollingVwapCrypto:
                    EvaluateEntry_RollingVwapCrypto(todHHMM);
                    break;
                default:
                    EvaluateEntry_VwapPullback(todHHMM);
                    break;
            }
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
            _orbBreakoutBar   = -1;
            _orbBreakoutPrice = 0.0;
        }

        // OR window = [TradeStartTime, TradeStartTime + OrbDurationMinutes].
        // Built only on the primary trading window. Times are HHMM PT.
        private void UpdateOrbState()
        {
            if (_orbBuilt) return;
            if (TradeStartTime <= 0) return;

            int todMin = HhmmToMin(ToTimeHHMM(Time[0]));
            int orStartMin = HhmmToMin(TradeStartTime);
            int orEndMin   = orStartMin + Math.Max(1, OrbDurationMinutes);

            if (todMin < orStartMin) return;

            if (todMin <= orEndMin)
            {
                if (double.IsNaN(_orbHigh) || High[0] > _orbHigh) _orbHigh = High[0];
                if (double.IsNaN(_orbLow)  || Low[0]  < _orbLow)  _orbLow  = Low[0];
            }
            else
            {
                if (!double.IsNaN(_orbHigh) && !double.IsNaN(_orbLow))
                    _orbBuilt = true;
            }
        }

        private static int HhmmToMin(int hhmm)
        {
            return (hhmm / 100) * 60 + (hhmm % 100);
        }
        #endregion
    }
}
