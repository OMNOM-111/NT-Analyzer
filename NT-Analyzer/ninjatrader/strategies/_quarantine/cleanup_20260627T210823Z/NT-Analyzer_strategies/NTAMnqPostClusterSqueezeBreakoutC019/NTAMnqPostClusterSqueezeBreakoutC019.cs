// =============================================================================
// NTAMnqPostClusterSqueezeBreakoutC019
// -----------------------------------------------------------------------------
// Standalone MNQ CELL-019 strategy. NEW family: "Post-Cluster Squeeze Breakout".
//
// Engine is structurally NEW vs every existing strategy in the project:
//   * Timeframe = 15 Minute (no other MNQ strategy uses 15m; the active 1m
//     cluster strategies and the 5m C019 pre-cash compression engine cannot
//     produce the same signals).
//   * Indicators = BollingerBands + KeltnerChannel + ADX + RSI on the primary
//     series, plus session VWAP / EMA-trend filter. None of the existing
//     strategies (Scalp Pilot family, LiquiditySweep C015/C019, OpenDrive
//     C016/C020, OrbRetest C013/C014, PreCashCompression C019,
//     SessionEdgeEngine C020) use the BB+Keltner squeeze release pattern.
//   * Window = 13:00-15:30 PT (post the active 06:35-12:45 MNQ cluster).
//     ForceFlat 15:45 PT. Long & short. RTH template, intraday-only.
//   * Signal = TTM-style "squeeze fire": BB band exits Keltner channel after
//     N bars inside, in the direction confirmed by ADX strength and RSI bias,
//     filtered by EMA trend slope, VWAP side, volume expansion.
//
// Risk shell mirrors the validated C019 pre-cash shell (per-bar realized PnL
// accrual via OnPositionUpdate, ResetRealtimeRiskAccounting at State.Realtime,
// CanTrade gate, ComputeQuantity floor-to-1 when budget rounds below one but
// margin & user caps allow). The shell is shared safety boilerplate; it is not
// the source of edge and is reused intentionally for honest backtests.
//
// This class does NOT inherit from NTAMicroMnqScalpPilot, NTAMicroVwapRiskExplorer,
// NTAMicroSessionEdgeExplorer, or any other carrier. It does NOT reuse the
// liquidity-sweep / open-pressure / opening-drive / pre-cash-compression /
// session-edge-engine signal logic.
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
    public class NTAMnqPostClusterSqueezeBreakoutC019 : Strategy
    {
        private Bollinger _bb;
        private KeltnerChannel _kc;
        private ADX _adx;
        private RSI _rsi;
        private EMA _emaFast;
        private EMA _emaTrend;
        private ATR _atr;
        private SMA _volumeSma;
        private Series<double> _vwapSeries;
        private Series<bool> _squeezeOn;

        private DateTime _sessionDate = DateTime.MinValue;
        private double _vwapCumPV;
        private double _vwapCumVol;
        private int _squeezeBarsAccum;

        private DateTime _weekStartDate = DateTime.MinValue;
        private double _cumulativeRealizedPnl;
        private double _sessionRealizedPnl;
        private double _weeklyRealizedPnl;
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
        private double _bestFavorableTicks;

        protected override void OnStateChange()
        {
            if (State == State.SetDefaults)
            {
                Description = "MNQ CELL-019 standalone post-cluster squeeze breakout (15m, BB+Keltner+ADX+RSI).";
                Name = "Post-Cluster Squeeze MNQ 15m v1 c019";
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
                SessionTemplateName = "CME US Index Futures RTH";
                BaseTimeframeSeconds = 900;

                StartingCapital = 2000.0;
                IntradayOnly = true;
                ActiveMarginPerContract = 100.0;
                MaxContractsByCapital = 20;
                InstrumentStatus = "allowed";
                MarginSourceBroker = "NinjaTrader";

                EnableLong = true;
                EnableShort = true;

                // Post-cluster free window, PT clock as configured on chart.
                TradeStartTime = 1300;
                TradeEndTime = 1530;
                ForceFlatTime = 1545;

                BbPeriod = 20;
                BbStdDev = 2.0;
                KcPeriod = 20;
                KcAtrMult = 1.5;
                SqueezeMinBars = 4;
                FireMaxLagBars = 3;

                AdxPeriod = 14;
                AdxMinFire = 18.0;
                RsiPeriod = 14;
                RsiLongMin = 52.0;
                RsiShortMax = 48.0;

                EmaFastPeriod = 9;
                EmaTrendPeriod = 50;
                AtrPeriod = 14;
                VolumeSmaPeriod = 20;
                VolExpansionFactor = 1.10;
                MinBarRangeTicks = 8;
                RequireVwapAgreement = true;
                RequireEmaTrend = true;
                RequireBbWidthExpansion = true;
                BbWidthExpansionFactor = 1.10;

                StopBufferTicks = 4;
                MinStopTicks = 20;
                MaxStopTicks = 60;
                AtrStopMult = 1.4;
                RewardRiskRatio = 1.7;
                MinTargetTicks = 24;
                EntryOffsetTicks = 0;
                MoveToBreakevenAtR = 1.0;
                BreakevenPlusTicks = 2;
                UseTrailingStop = false;
                TrailAfterR = 1.5;
                TrailDistanceTicks = 16;
                UseTimeStop = true;
                TimeStopBars = 6;
                MinProgressR = 0.30;

                RiskPerTradePct = 0.60;
                UserMaxContracts = 1;
                MaxOpenPositions = 1;
                MaxDailyLossUsd = 90.0;
                MaxWeeklyLossUsd = 220.0;
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
                _bb = Bollinger(BbStdDev, BbPeriod);
                _kc = KeltnerChannel(KcAtrMult, KcPeriod);
                _adx = ADX(AdxPeriod);
                _rsi = RSI(RsiPeriod, 3);
                _emaFast = EMA(EmaFastPeriod);
                _emaTrend = EMA(EmaTrendPeriod);
                _atr = ATR(AtrPeriod);
                _volumeSma = SMA(Volume, VolumeSmaPeriod);
                _vwapSeries = new Series<double>(this);
                _squeezeOn = new Series<bool>(this);

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

            UpdateSessionState();
            UpdateVwap();
            UpdateSqueezeState();
            ManageOpenPosition();

            if (ForceFlatDue())
            {
                ForceFlat("time");
                return;
            }

            if (CurrentBar < BarsRequiredToTrade) return;
            if (!InTradeWindow()) return;
            if (!CanTrade()) return;
            if (Position.MarketPosition != MarketPosition.Flat) return;
            if (_activeSignal != "") return;
            if (MaxOpenPositions < 1) return;

            TryEnterSqueezeFire();
        }

        private void UpdateSessionState()
        {
            DateTime currentDate = Time[0].Date;
            if (_sessionDate == currentDate) return;
            _sessionDate = currentDate;
            _vwapCumPV = 0.0;
            _vwapCumVol = 0.0;
            _squeezeBarsAccum = 0;
            ResetDailyRisk();
            ClearActiveTradeState();
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

        private void UpdateVwap()
        {
            double volume = Math.Max(1.0, Volume[0]);
            double typical = (High[0] + Low[0] + Close[0]) / 3.0;
            _vwapCumPV += typical * volume;
            _vwapCumVol += volume;
            _vwapSeries[0] = _vwapCumVol > 0.0 ? _vwapCumPV / _vwapCumVol : Close[0];
        }

        // TTM-style squeeze tracker: BB upper inside Keltner upper AND BB lower
        // inside Keltner lower means volatility compressed inside the Keltner
        // envelope. We require SqueezeMinBars consecutive bars in compression
        // before we will recognise a "fire" (BB band escaping Keltner). The
        // fire bar must occur within FireMaxLagBars after the squeeze ends.
        private void UpdateSqueezeState()
        {
            bool inSqueeze = _bb.Upper[0] <= _kc.Upper[0]
                && _bb.Lower[0] >= _kc.Lower[0];
            _squeezeOn[0] = inSqueeze;
            if (inSqueeze) _squeezeBarsAccum += 1;
            else _squeezeBarsAccum = 0;
        }

        private void TryEnterSqueezeFire()
        {
            // Need a window where N consecutive bars of squeeze just ended in
            // the past 1..FireMaxLagBars bars (current bar is the fire candidate
            // — i.e. squeeze recently released, not in squeeze right now).
            if (_squeezeOn[0]) return;
            int barsSinceSqueeze = BarsSinceSqueezeEnded();
            if (barsSinceSqueeze < 1 || barsSinceSqueeze > FireMaxLagBars) return;
            int priorSqueezeLen = SqueezeLengthBefore(barsSinceSqueeze);
            if (priorSqueezeLen < SqueezeMinBars) return;

            double rangeTicks = (High[0] - Low[0]) / TickSize;
            if (rangeTicks < MinBarRangeTicks) return;
            if (!VolumeExpanded()) return;
            if (RequireBbWidthExpansion && !BbWidthExpanding()) return;

            double adxValue = _adx[0];
            if (adxValue < AdxMinFire) return;

            bool bbBreakUp = Close[0] > _bb.Upper[0];
            bool bbBreakDown = Close[0] < _bb.Lower[0];

            // Long fire: BB upper breach + RSI bullish + EMA-trend agreement +
            //            optional VWAP-side agreement.
            if (EnableLong && bbBreakUp && _rsi[0] >= RsiLongMin && LongFiltersPass())
            {
                EnterFire(true);
                return;
            }
            if (EnableShort && bbBreakDown && _rsi[0] <= RsiShortMax && ShortFiltersPass())
            {
                EnterFire(false);
                return;
            }
        }

        private int BarsSinceSqueezeEnded()
        {
            // Returns the number of bars (>=1) since _squeezeOn was true.
            // If the prior bar was a squeeze, returns 1.
            for (int i = 1; i <= FireMaxLagBars + 2; i++)
            {
                if (i > CurrentBar) return -1;
                if (_squeezeOn[i]) return i;
            }
            return -1;
        }

        private int SqueezeLengthBefore(int barsBack)
        {
            int len = 0;
            for (int i = barsBack; i <= CurrentBar; i++)
            {
                if (!_squeezeOn[i]) break;
                len += 1;
            }
            return len;
        }

        private bool BbWidthExpanding()
        {
            if (CurrentBar < 2) return false;
            double widthNow = _bb.Upper[0] - _bb.Lower[0];
            double widthPrev = _bb.Upper[1] - _bb.Lower[1];
            if (widthPrev <= 0.0) return widthNow > 0.0;
            return widthNow >= widthPrev * BbWidthExpansionFactor;
        }

        private bool LongFiltersPass()
        {
            if (RequireVwapAgreement && Close[0] < _vwapSeries[0]) return false;
            if (RequireEmaTrend)
            {
                if (Close[0] <= _emaTrend[0]) return false;
                if (_emaTrend[0] <= _emaTrend[1]) return false;
            }
            if (_emaFast[0] <= _emaFast[1]) return false;
            return true;
        }

        private bool ShortFiltersPass()
        {
            if (RequireVwapAgreement && Close[0] > _vwapSeries[0]) return false;
            if (RequireEmaTrend)
            {
                if (Close[0] >= _emaTrend[0]) return false;
                if (_emaTrend[0] >= _emaTrend[1]) return false;
            }
            if (_emaFast[0] >= _emaFast[1]) return false;
            return true;
        }

        private bool VolumeExpanded()
        {
            double baseVolume = _volumeSma[0];
            if (baseVolume <= 0.0) return true;
            return Volume[0] >= baseVolume * VolExpansionFactor;
        }

        private void EnterFire(bool isLong)
        {
            int stopTicks = ComputeStopTicks(isLong);
            int targetTicks = (int)Math.Round(stopTicks * RewardRiskRatio);
            if (stopTicks < MinStopTicks || targetTicks < MinTargetTicks) return;

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
            _bestFavorableTicks = 0.0;

            if (isLong) EnterLong(qty, signal);
            else EnterShort(qty, signal);
        }

        private int ComputeStopTicks(bool isLong)
        {
            double atrTicks = _atr[0] / TickSize;
            int atrStopTicks = (int)Math.Round(atrTicks * AtrStopMult);
            double geometryPrice = isLong
                ? Math.Min(Low[0], Low[1]) - StopBufferTicks * TickSize
                : Math.Max(High[0], High[1]) + StopBufferTicks * TickSize;
            double geometryTicks = isLong
                ? (Close[0] - geometryPrice) / TickSize
                : (geometryPrice - Close[0]) / TickSize;
            int rawTicks = (int)Math.Ceiling(Math.Max(1.0, geometryTicks));
            int stopTicks = Math.Max(rawTicks, atrStopTicks);
            stopTicks = Math.Max(stopTicks, MinStopTicks);
            stopTicks = Math.Min(stopTicks, MaxStopTicks);
            return stopTicks;
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
                && _bestFavorableTicks >= _lastStopTicks * TrailAfterR
                && _stopMovedToBreakeven)
            {
                double trailPrice = isLong
                    ? Close[0] - TrailDistanceTicks * TickSize
                    : Close[0] + TrailDistanceTicks * TickSize;
                SetStopLoss(_activeSignal, CalculationMode.Price, trailPrice, false);
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

            return Math.Max(0, qty);
        }

        private bool InTradeWindow()
        {
            int now = ToHHMM(Time[0]);
            return InWindow(now, TradeStartTime, TradeEndTime);
        }

        private bool ForceFlatDue()
        {
            return ToHHMM(Time[0]) >= ForceFlatTime;
        }

        private bool InWindow(int now, int start, int end)
        {
            if (start <= end) return now >= start && now <= end;
            return now >= start || now <= end;
        }

        private int ToHHMM(DateTime value)
        {
            return value.Hour * 100 + value.Minute;
        }

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

        private string TelemetrySignal(string side)
        {
            return GetType().Name + "." + side;
        }

        private void ClearActiveTradeState()
        {
            _activeSignal = "";
            _lastEntryBar = -1;
            _lastEntryPrice = 0.0;
            _lastStopTicks = 0;
            _stopMovedToBreakeven = false;
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

            if (MaxDailyLossUsd > 0.0 && _sessionRealizedPnl <= -MaxDailyLossUsd)
                _sessionStopped = true;
            if (MaxWeeklyLossUsd > 0.0 && _weeklyRealizedPnl <= -MaxWeeklyLossUsd)
                _sessionStopped = true;
            if (MaxConsecutiveLosses > 0 && _consecutiveLosses >= MaxConsecutiveLosses)
                _sessionStopped = true;

            _lastProcessedTradeCount = total;
            ClearActiveTradeState();
        }

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

        [NinjaScriptProperty, Range(1, 3600)]
        [Display(Name = "BaseTimeframeSeconds", GroupName = "01-Instrument", Order = 3)]
        public int BaseTimeframeSeconds { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "StartingCapital", GroupName = "02-Risk Profile", Order = 0)]
        public double StartingCapital { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "IntradayOnly", GroupName = "02-Risk Profile", Order = 1)]
        public bool IntradayOnly { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "ActiveMarginPerContract", GroupName = "02-Risk Profile", Order = 2)]
        public double ActiveMarginPerContract { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "MaxContractsByCapital", GroupName = "02-Risk Profile", Order = 3)]
        public int MaxContractsByCapital { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "InstrumentStatus", GroupName = "02-Risk Profile", Order = 4)]
        public string InstrumentStatus { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "MarginSourceBroker", GroupName = "02-Risk Profile", Order = 5)]
        public string MarginSourceBroker { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "EnableLong", GroupName = "03-Direction", Order = 0)]
        public bool EnableLong { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "EnableShort", GroupName = "03-Direction", Order = 1)]
        public bool EnableShort { get; set; }

        [NinjaScriptProperty, Range(0, 2359)]
        [Display(Name = "TradeStartTime", GroupName = "04-Time", Order = 0)]
        public int TradeStartTime { get; set; }

        [NinjaScriptProperty, Range(0, 2359)]
        [Display(Name = "TradeEndTime", GroupName = "04-Time", Order = 1)]
        public int TradeEndTime { get; set; }

        [NinjaScriptProperty, Range(0, 2359)]
        [Display(Name = "ForceFlatTime", GroupName = "04-Time", Order = 2)]
        public int ForceFlatTime { get; set; }

        [NinjaScriptProperty, Range(5, 200)]
        [Display(Name = "BbPeriod", GroupName = "05-Squeeze", Order = 0)]
        public int BbPeriod { get; set; }

        [NinjaScriptProperty, Range(0.5, 4.0)]
        [Display(Name = "BbStdDev", GroupName = "05-Squeeze", Order = 1)]
        public double BbStdDev { get; set; }

        [NinjaScriptProperty, Range(5, 200)]
        [Display(Name = "KcPeriod", GroupName = "05-Squeeze", Order = 2)]
        public int KcPeriod { get; set; }

        [NinjaScriptProperty, Range(0.5, 5.0)]
        [Display(Name = "KcAtrMult", GroupName = "05-Squeeze", Order = 3)]
        public double KcAtrMult { get; set; }

        [NinjaScriptProperty, Range(1, 50)]
        [Display(Name = "SqueezeMinBars", GroupName = "05-Squeeze", Order = 4)]
        public int SqueezeMinBars { get; set; }

        [NinjaScriptProperty, Range(1, 10)]
        [Display(Name = "FireMaxLagBars", GroupName = "05-Squeeze", Order = 5)]
        public int FireMaxLagBars { get; set; }

        [NinjaScriptProperty, Range(2, 100)]
        [Display(Name = "AdxPeriod", GroupName = "06-Confirm", Order = 0)]
        public int AdxPeriod { get; set; }

        [NinjaScriptProperty, Range(0.0, 60.0)]
        [Display(Name = "AdxMinFire", GroupName = "06-Confirm", Order = 1)]
        public double AdxMinFire { get; set; }

        [NinjaScriptProperty, Range(2, 100)]
        [Display(Name = "RsiPeriod", GroupName = "06-Confirm", Order = 2)]
        public int RsiPeriod { get; set; }

        [NinjaScriptProperty, Range(0.0, 100.0)]
        [Display(Name = "RsiLongMin", GroupName = "06-Confirm", Order = 3)]
        public double RsiLongMin { get; set; }

        [NinjaScriptProperty, Range(0.0, 100.0)]
        [Display(Name = "RsiShortMax", GroupName = "06-Confirm", Order = 4)]
        public double RsiShortMax { get; set; }

        [NinjaScriptProperty, Range(2, 200)]
        [Display(Name = "EmaFastPeriod", GroupName = "07-Filters", Order = 0)]
        public int EmaFastPeriod { get; set; }

        [NinjaScriptProperty, Range(2, 400)]
        [Display(Name = "EmaTrendPeriod", GroupName = "07-Filters", Order = 1)]
        public int EmaTrendPeriod { get; set; }

        [NinjaScriptProperty, Range(2, 200)]
        [Display(Name = "AtrPeriod", GroupName = "07-Filters", Order = 2)]
        public int AtrPeriod { get; set; }

        [NinjaScriptProperty, Range(2, 500)]
        [Display(Name = "VolumeSmaPeriod", GroupName = "07-Filters", Order = 3)]
        public int VolumeSmaPeriod { get; set; }

        [NinjaScriptProperty, Range(0.0, 10.0)]
        [Display(Name = "VolExpansionFactor", GroupName = "07-Filters", Order = 4)]
        public double VolExpansionFactor { get; set; }

        [NinjaScriptProperty, Range(1, 400)]
        [Display(Name = "MinBarRangeTicks", GroupName = "07-Filters", Order = 5)]
        public int MinBarRangeTicks { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "RequireVwapAgreement", GroupName = "07-Filters", Order = 6)]
        public bool RequireVwapAgreement { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "RequireEmaTrend", GroupName = "07-Filters", Order = 7)]
        public bool RequireEmaTrend { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "RequireBbWidthExpansion", GroupName = "07-Filters", Order = 8)]
        public bool RequireBbWidthExpansion { get; set; }

        [NinjaScriptProperty, Range(1.0, 5.0)]
        [Display(Name = "BbWidthExpansionFactor", GroupName = "07-Filters", Order = 9)]
        public double BbWidthExpansionFactor { get; set; }

        [NinjaScriptProperty, Range(0, 100)]
        [Display(Name = "StopBufferTicks", GroupName = "08-Orders", Order = 0)]
        public int StopBufferTicks { get; set; }

        [NinjaScriptProperty, Range(1, 400)]
        [Display(Name = "MinStopTicks", GroupName = "08-Orders", Order = 1)]
        public int MinStopTicks { get; set; }

        [NinjaScriptProperty, Range(1, 600)]
        [Display(Name = "MaxStopTicks", GroupName = "08-Orders", Order = 2)]
        public int MaxStopTicks { get; set; }

        [NinjaScriptProperty, Range(0.0, 10.0)]
        [Display(Name = "AtrStopMult", GroupName = "08-Orders", Order = 3)]
        public double AtrStopMult { get; set; }

        [NinjaScriptProperty, Range(0.1, 10.0)]
        [Display(Name = "RewardRiskRatio", GroupName = "08-Orders", Order = 4)]
        public double RewardRiskRatio { get; set; }

        [NinjaScriptProperty, Range(1, 400)]
        [Display(Name = "MinTargetTicks", GroupName = "08-Orders", Order = 5)]
        public int MinTargetTicks { get; set; }

        [NinjaScriptProperty, Range(0, 40)]
        [Display(Name = "EntryOffsetTicks", GroupName = "08-Orders", Order = 6)]
        public int EntryOffsetTicks { get; set; }

        [NinjaScriptProperty, Range(0.0, 5.0)]
        [Display(Name = "MoveToBreakevenAtR", GroupName = "08-Orders", Order = 7)]
        public double MoveToBreakevenAtR { get; set; }

        [NinjaScriptProperty, Range(0, 50)]
        [Display(Name = "BreakevenPlusTicks", GroupName = "08-Orders", Order = 8)]
        public int BreakevenPlusTicks { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "UseTrailingStop", GroupName = "08-Orders", Order = 9)]
        public bool UseTrailingStop { get; set; }

        [NinjaScriptProperty, Range(0.0, 5.0)]
        [Display(Name = "TrailAfterR", GroupName = "08-Orders", Order = 10)]
        public double TrailAfterR { get; set; }

        [NinjaScriptProperty, Range(1, 200)]
        [Display(Name = "TrailDistanceTicks", GroupName = "08-Orders", Order = 11)]
        public int TrailDistanceTicks { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "UseTimeStop", GroupName = "08-Orders", Order = 12)]
        public bool UseTimeStop { get; set; }

        [NinjaScriptProperty, Range(1, 100)]
        [Display(Name = "TimeStopBars", GroupName = "08-Orders", Order = 13)]
        public int TimeStopBars { get; set; }

        [NinjaScriptProperty, Range(0.0, 2.0)]
        [Display(Name = "MinProgressR", GroupName = "08-Orders", Order = 14)]
        public double MinProgressR { get; set; }

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
