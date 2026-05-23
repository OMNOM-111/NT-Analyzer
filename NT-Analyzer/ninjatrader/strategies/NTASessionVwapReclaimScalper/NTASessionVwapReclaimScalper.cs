// =============================================================================
// NTASessionVwapReclaimScalper
// -----------------------------------------------------------------------------
// Single-series intraday Session VWAP Reclaim scalper family.
//
// Architecture:
//   - Primary series only. No AddDataSeries, no Tick Replay dependency.
//   - Designed for honest NT-Analyzer research jobs with High Order Fill
//     Resolution, slippage >= 1, and explicit RoundTurnCommission accounting.
//   - Concrete instrument/direction wrappers lock deployment defaults.
// =============================================================================

#region Using declarations
using System;
using NinjaTrader.Cbi;
using NinjaTrader.Data;
using NinjaTrader.NinjaScript;
using NinjaTrader.NinjaScript.Indicators;
using NinjaTrader.NinjaScript.Strategies;
#endregion

namespace NinjaTrader.NinjaScript.Strategies
{
    public enum VwapReclaimDirection
    {
        None  = 0,
        Long  = 1,
        Short = -1
    }

    public enum SessionVwapMode
    {
        TypicalPrice = 0,
        ClosePrice   = 1
    }

    public enum ReclaimTrailMode
    {
        Off      = 0,
        HalfStop = 1,
        EmaFast  = 2
    }

    public abstract partial class NTASessionVwapReclaimScalper : Strategy
    {
        private EMA _emaFast;
        private EMA _emaSlow;
        private ATR _atr;
        private ADX _adx;
        private SMA _volSma;

        private Series<double> _vwapSeries;
        private double _vwapCumPV;
        private double _vwapCumVol;
        private DateTime _sessionDate = DateTime.MinValue;

        private double _orbHigh;
        private double _orbLow;
        private bool _orbBuilt;
        private int _orbBuiltBar;

        private VwapReclaimDirection _activeBias = VwapReclaimDirection.None;
        private int _impulseBar = -1;
        private double _impulseExtreme = 0.0;
        private double _impulseVwapDistanceTicks = 0.0;

        private bool _pullbackArmed;
        private int _pullbackBar = -1;
        private double _pullbackExtreme = 0.0;
        private double _pullbackDepthTicks = 0.0;

        private RiskManager _risk;

        private string _pendingEntrySignal = null;
        private string _pendingSetupTag = "";
        private int _pendingEntryBar = -1;
        private double _pendingEntryStopPx = 0.0;
        private double _pendingProtStopPx = 0.0;
        private double _pendingTargetPx = 0.0;
        private int _pendingEntryQty = 0;
        private int _pendingStopTicks = 0;
        private Order _pendingEntryOrder = null;
        private bool _pendingCancelRequested = false;

        private double _lastEntryPrice = 0.0;
        private int _lastEntryQty = 0;
        private int _lastStopTicks = 0;
        private int _lastEntryBar = -1;
        private string _lastDirection = "";
        private string _lastSetupTag = "";
        private DateTime _lastEntryTime = DateTime.MinValue;
        private double _lastEntryVwapDistanceTicks = 0.0;
        private double _lastEntryEmaSpreadTicks = 0.0;
        private double _lastEntryVolumeFactor = 0.0;
        private string _lastEntryOrbState = "";
        private string _lastDeltaState = "off";
        private double _tradeMfeTicks = 0.0;
        private double _tradeMaeTicks = 0.0;

        private int _lastSkipBar = -1;
        private string _lastSkipReason = "";

        #region OnStateChange
        protected override void OnStateChange()
        {
            if (State == State.SetDefaults)
            {
                Description = "Session VWAP Reclaim Scalper - single-series intraday production/research family.";
                Name = "NTASessionVwapReclaimScalper";
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
                BarsRequiredToTrade = 10;
                IsInstantiatedOnEachOptimizationIteration = true;

                InstrumentName = "MNQ";
                ContractName = "MNQ 06-26";
                SessionTemplateName = "CME US Index Futures RTH";
                BaseTimeframeSeconds = 60;

                StartingCapital = 2000.0;
                IntradayOnly = true;
                ActiveMarginPerContract = 100.0;
                MaxContractsByCapital = 20;
                InstrumentStatus = "allowed";
                MarginSourceBroker = "NinjaTrader";

                EnableLong = true;
                EnableShort = false;

                TradeStartTime = 635;
                TradeEndTime = 830;
                ForceFlatTime = 1245;
                OpeningRangeStartTime = 630;
                OpeningRangeMinutes = 5;

                EmaFastPeriod = 9;
                EmaSlowPeriod = 34;
                AtrPeriod = 14;
                AdxPeriod = 14;
                MinAdx = 0.0;
                VolumeSmaPeriod = 20;
                MinVolumeFactor = 1.10;
                MinBodyRangePct = 0.45;
                MinCloseLocationPct = 0.60;

                VwapMode = SessionVwapMode.TypicalPrice;
                VwapDistanceThresholdTicks = 16;
                VwapSlopeLookback = 8;
                MinVwapSlopeTicks = 1.0;
                VwapReclaimBufferTicks = 1;
                VwapChopBandTicks = 4;
                VwapCrossLookback = 12;
                MaxVwapCrosses = 3;
                MinEmaSpreadTicks = 2;

                ImpulseLookbackBars = 4;
                MinImpulseMoveTicks = 14;
                MinOpeningRangeTicks = 8;
                MaxOpeningRangeTicks = 80;
                OpeningRangeBreakBufferTicks = 2;

                PullbackLookbackBars = 6;
                MinPullbackDepthTicks = 4;
                MaxPullbackDepthTicks = 24;
                PullbackMaxDistanceFromVwapTicks = 10;
                PullbackTouchEmaTicks = 3;
                MaxBarsAfterImpulse = 18;
                MaxBarsAfterPullback = 6;

                UseDeltaFilter = false;
                UseImbalanceFilter = false;
                DeltaVolumeFactor = 1.25;

                AtrStopMult = 0.40;
                StopMinTicks = 8;
                StopMaxTicks = 18;
                StopBeyondPullbackTicks = 2;
                RewardRiskRatio = 1.60;
                BreakEvenTriggerR = 0.80;
                TrailMode = ReclaimTrailMode.HalfStop;
                TrailTriggerR = 1.10;
                TimeStopBars = 5;
                MinProgressR = 0.25;
                EntryOffsetTicks = 1;
                EntryTimeoutBars = 2;

                RiskPerTradePct = 0.35;
                UserMaxContracts = 1;
                MaxOpenPositions = 1;
                DailyLossLimit = 60.0;
                WeeklyLossLimit = 150.0;
                MaxTradesPerDay = 6;
                HardMaxTradesPerDay = 8;
                MaxConsecutiveLosses = 3;
                PauseAfterConsecutiveLosses = 2;
                PauseMinutesAfterLosses = 15;
                RoundTurnCommission = 1.90;
                SlippageTicks = 1;
            }
            else if (State == State.Configure)
            {
                // Intentionally single-series. The NT-Analyzer job controls the
                // primary bar type/value so High Order Fill Resolution remains valid.
            }
            else if (State == State.DataLoaded)
            {
                _emaFast = EMA(EmaFastPeriod);
                _emaSlow = EMA(EmaSlowPeriod);
                _atr = ATR(AtrPeriod);
                _adx = ADX(AdxPeriod);
                _volSma = SMA(Volume, VolumeSmaPeriod);
                _vwapSeries = new Series<double>(this);

                ResetSessionState();
                _risk = new RiskManager(this);
                _risk.Init();

                Print("[INIT] " + Name
                    + " instrument=" + InstrumentName
                    + " contract=" + ContractName
                    + " tfSec=" + BaseTimeframeSeconds
                    + " long=" + EnableLong
                    + " short=" + EnableShort
                    + " " + _risk.Describe());
            }
        }
        #endregion

        #region OnBarUpdate
        protected override void OnBarUpdate()
        {
            if (BarsInProgress != 0) return;
            if (CurrentBars[0] < 1) return;

            DateTime today = Time[0].Date;
            if (Bars.IsFirstBarOfSession || today != _sessionDate)
            {
                ResetSessionState();
                _sessionDate = today;
                if (_risk != null) _risk.OnNewSession();
            }

            UpdateSessionVwap();
            UpdateOpeningRange();

            if (CurrentBar < BarsRequiredToTrade) return;
            if (_risk == null || _risk.PermanentlyStopped) return;

            int todHHMM = ToTime(Time[0]) / 100;
            bool atForceFlat = ForceFlatTime > 0 && todHHMM >= ForceFlatTime;
            if (IntradayOnly && (Bars.IsLastBarOfSession || atForceFlat))
            {
                CancelPendingEntry("force_flat");
                if (Position.MarketPosition == MarketPosition.Long)
                    ExitLong("FlatEOD", ActiveEntrySignalForPosition());
                else if (Position.MarketPosition == MarketPosition.Short)
                    ExitShort("FlatEOD", ActiveEntrySignalForPosition());
                if (atForceFlat) LogSkip("force_flat_time");
                return;
            }

            _risk.UpdateStops();
            if (_risk.SessionStopped) return;

            if (_pendingEntrySignal != null && CurrentBar - _pendingEntryBar >= EntryTimeoutBars)
                CancelPendingEntry("entry_timeout");

            if (Position.MarketPosition != MarketPosition.Flat)
            {
                ManageOpenPosition();
                return;
            }

            if (!IsInTradeWindow(todHHMM)) { LogSkip("outside_window"); return; }
            if (_risk.IsPaused(Time[0])) { LogSkip("loss_pause"); return; }
            if (_pendingEntrySignal != null) { LogSkip("pending_entry"); return; }

            EvaluateReclaimSetup();
        }
        #endregion

        private void ResetSessionState()
        {
            _vwapCumPV = 0.0;
            _vwapCumVol = 0.0;
            _orbHigh = double.NaN;
            _orbLow = double.NaN;
            _orbBuilt = false;
            _orbBuiltBar = -1;
            ResetSetupState();
        }

        private void ResetSetupState()
        {
            _activeBias = VwapReclaimDirection.None;
            _impulseBar = -1;
            _impulseExtreme = 0.0;
            _impulseVwapDistanceTicks = 0.0;
            _pullbackArmed = false;
            _pullbackBar = -1;
            _pullbackExtreme = 0.0;
            _pullbackDepthTicks = 0.0;
        }

        private void UpdateSessionVwap()
        {
            double price = VwapMode == SessionVwapMode.ClosePrice
                ? Close[0]
                : (High[0] + Low[0] + Close[0]) / 3.0;
            double vol = Math.Max(0.0, Volume[0]);
            _vwapCumPV += price * vol;
            _vwapCumVol += vol;
            _vwapSeries[0] = _vwapCumVol > 0.0 ? _vwapCumPV / _vwapCumVol : Close[0];
        }

        private void UpdateOpeningRange()
        {
            int startHHMM = OpeningRangeStartTime > 0 ? OpeningRangeStartTime : TradeStartTime;
            int todMin = HhmmToMin(ToTime(Time[0]) / 100);
            int startMin = HhmmToMin(startHHMM);
            int endMin = startMin + Math.Max(1, OpeningRangeMinutes);

            if (todMin < startMin) return;

            if (!_orbBuilt && todMin <= endMin)
            {
                if (double.IsNaN(_orbHigh) || High[0] > _orbHigh) _orbHigh = High[0];
                if (double.IsNaN(_orbLow) || Low[0] < _orbLow) _orbLow = Low[0];
            }
            else if (!_orbBuilt && !double.IsNaN(_orbHigh) && !double.IsNaN(_orbLow))
            {
                _orbBuilt = true;
                _orbBuiltBar = CurrentBar;
            }
        }

        private bool IsInTradeWindow(int todHHMM)
        {
            return todHHMM >= TradeStartTime && todHHMM <= TradeEndTime;
        }

        private static int HhmmToMin(int hhmm)
        {
            return (hhmm / 100) * 60 + (hhmm % 100);
        }
    }
}
