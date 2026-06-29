// =============================================================================
// NTAMnqPostClusterVwapFadeC019
// -----------------------------------------------------------------------------
// Standalone MNQ CELL-019 strategy. NEW family: "Post-Cluster VWAP Fade".
//
// Engine #2 for CELL-019 (engine #1 NTAMnqPostClusterSqueezeBreakoutC019 was
// rejected at smoke because squeeze-breakout fights the regime in the
// 13:00-15:30 PT free window). Mean-reversion hypothesis: in the post-cluster
// MNQ window volume drops, large institutional orders are mostly done, and
// price tends to revert toward session VWAP after stretching to a Bollinger
// (StdDev) band.
//
// Engine is structurally NEW vs every existing strategy:
//   * Timeframe = 5 Minute on the post-cluster RTH window.
//   * Indicators = session VWAP + StdDev bands (k * stddev of typical price)
//     + RSI extreme + ADX upper cap (range filter) + Bollinger Width
//     compression baseline. No EMA-trend filter (we are explicitly fading).
//   * Signal = price closes beyond VWAP +/- BandStdDev * sigma AND the bar
//     shows a rejection (close-back-toward-VWAP relative to bar extreme),
//     RSI confirms exhaustion (>= RsiShortMin for short, <= RsiLongMax for
//     long), ADX is below RangeAdxMax (range regime, NOT a strong trend),
//     volume is NOT exploding (Volume <= VolCeilingFactor * SMA volume).
//   * Target = back to VWAP (PriceMode) or RR-multiple. Stop beyond bar
//     extreme + StopBufferTicks, ATR-floor capped.
//   * Long & short. Force flat 15:45 PT.
//
// Risk shell mirrors the validated C019 pre-cash shell (per-bar realized PnL
// accrual via OnPositionUpdate, ResetRealtimeRiskAccounting at State.Realtime,
// CanTrade gate, ComputeQuantity floor-to-1 when fractional budget rounds
// below one but margin and user caps allow). Shared safety boilerplate, not
// the source of edge.
//
// This class does NOT inherit any carrier and does NOT reuse the squeeze /
// liquidity-sweep / open-pressure / opening-drive / pre-cash-compression /
// session-edge-engine / OrbRetest signal logic.
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
    public class NTAMnqPostClusterVwapFadeC019 : Strategy
    {
        private ATR _atr;
        private ADX _adx;
        private RSI _rsi;
        private SMA _volumeSma;
        private Series<double> _vwapSeries;
        private Series<double> _vwapStdDev;

        private double _vwapCumPV;
        private double _vwapCumVol;
        // For online variance: maintain typical-price running sums.
        private double _vwapCumTP;
        private double _vwapCumTP2;
        private int _vwapBars;
        private DateTime _sessionDate = DateTime.MinValue;

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
                Description = "MNQ CELL-019 standalone post-cluster VWAP-fade (5m, mean-reversion).";
                Name = "Post-Cluster VWAP Fade MNQ 5m v1 c019";
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
                BaseTimeframeSeconds = 300;

                StartingCapital = 2000.0;
                IntradayOnly = true;
                ActiveMarginPerContract = 100.0;
                MaxContractsByCapital = 20;
                InstrumentStatus = "allowed";
                MarginSourceBroker = "NinjaTrader";

                EnableLong = true;
                EnableShort = true;

                // Post-cluster free window (PT clock).
                TradeStartTime = 1300;
                TradeEndTime = 1530;
                ForceFlatTime = 1545;

                BandStdDev = 2.0;
                MinVwapBarsBeforeFade = 6;
                MinDistanceFromVwapTicks = 16;
                RequireRejection = true;
                RejectionFractionOfRange = 0.45;
                AdxPeriod = 14;
                RangeAdxMax = 28.0;
                RsiPeriod = 14;
                RsiShortMin = 60.0;
                RsiLongMax = 40.0;
                AtrPeriod = 14;
                VolumeSmaPeriod = 20;
                VolCeilingFactor = 1.80;
                VolMinFactor = 0.50;
                MinBarRangeTicks = 6;
                MaxBarRangeTicks = 200;

                StopBufferTicks = 4;
                MinStopTicks = 12;
                MaxStopTicks = 32;
                AtrStopMult = 1.0;
                // Target VWAP or RR; whichever yields the lower (closer) target.
                TargetMode = "VwapOrRR";
                RewardRiskRatio = 1.3;
                MinTargetTicks = 8;
                MoveToBreakevenAtR = 0.7;
                BreakevenPlusTicks = 1;
                UseTrailingStop = false;
                TrailAfterR = 1.0;
                TrailDistanceTicks = 8;
                UseTimeStop = true;
                TimeStopBars = 4;
                MinProgressR = 0.40;

                RiskPerTradePct = 0.50;
                UserMaxContracts = 1;
                MaxOpenPositions = 1;
                MaxDailyLossUsd = 80.0;
                MaxWeeklyLossUsd = 200.0;
                MaxTradesPerDay = 4;
                HardMaxTradesPerDay = 5;
                MaxConsecutiveLosses = 3;
                PauseAfterConsecutiveLosses = 2;
                PauseMinutesAfterLosses = 45;
                RoundTurnCommission = 1.90;
                SlippageTicks = 1;
            }
            else if (State == State.DataLoaded)
            {
                _atr = ATR(AtrPeriod);
                _adx = ADX(AdxPeriod);
                _rsi = RSI(RsiPeriod, 3);
                _volumeSma = SMA(Volume, VolumeSmaPeriod);
                _vwapSeries = new Series<double>(this);
                _vwapStdDev = new Series<double>(this);

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
            UpdateVwapAndBands();
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

            TryEnterFade();
        }

        private void UpdateSessionState()
        {
            DateTime currentDate = Time[0].Date;
            if (_sessionDate == currentDate) return;
            _sessionDate = currentDate;
            _vwapCumPV = 0.0;
            _vwapCumVol = 0.0;
            _vwapCumTP = 0.0;
            _vwapCumTP2 = 0.0;
            _vwapBars = 0;
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

        private void UpdateVwapAndBands()
        {
            double volume = Math.Max(1.0, Volume[0]);
            double typical = (High[0] + Low[0] + Close[0]) / 3.0;
            _vwapCumPV += typical * volume;
            _vwapCumVol += volume;
            _vwapCumTP += typical;
            _vwapCumTP2 += typical * typical;
            _vwapBars += 1;
            double vwap = _vwapCumVol > 0.0 ? _vwapCumPV / _vwapCumVol : Close[0];
            _vwapSeries[0] = vwap;
            // Use unweighted std-dev of typical prices for band width — robust
            // and avoids floor effects when intraday volume is uneven.
            double mean = _vwapBars > 0 ? _vwapCumTP / _vwapBars : typical;
            double variance = _vwapBars > 1
                ? Math.Max(0.0, _vwapCumTP2 / _vwapBars - mean * mean)
                : 0.0;
            _vwapStdDev[0] = Math.Sqrt(variance);
        }

        private void TryEnterFade()
        {
            if (_vwapBars < MinVwapBarsBeforeFade) return;
            double rangeTicks = (High[0] - Low[0]) / TickSize;
            if (rangeTicks < MinBarRangeTicks) return;
            if (rangeTicks > MaxBarRangeTicks) return;
            double volFactor = VolumeFactor();
            if (volFactor > VolCeilingFactor) return;
            if (volFactor < VolMinFactor) return;
            double adxValue = _adx[0];
            if (adxValue > RangeAdxMax) return;

            double vwap = _vwapSeries[0];
            double sigma = _vwapStdDev[0];
            if (sigma <= 0.0) return;
            double upperBand = vwap + BandStdDev * sigma;
            double lowerBand = vwap - BandStdDev * sigma;

            // Short fade: close above upper band, RSI hot, bar rejects (close
            // is in the LOWER part of the bar range = sellers won the bar).
            if (EnableShort
                && Close[0] >= upperBand
                && (Close[0] - vwap) / TickSize >= MinDistanceFromVwapTicks
                && _rsi[0] >= RsiShortMin)
            {
                if (!RequireRejection || RejectionDown(rangeTicks))
                {
                    EnterFade(isLong: false, vwap: vwap);
                    return;
                }
            }
            if (EnableLong
                && Close[0] <= lowerBand
                && (vwap - Close[0]) / TickSize >= MinDistanceFromVwapTicks
                && _rsi[0] <= RsiLongMax)
            {
                if (!RequireRejection || RejectionUp(rangeTicks))
                {
                    EnterFade(isLong: true, vwap: vwap);
                    return;
                }
            }
        }

        private bool RejectionDown(double rangeTicks)
        {
            // Sellers absorbed the high: close in the LOWER RejectionFraction
            // of the bar's range.
            if (rangeTicks <= 0.0) return false;
            double distFromHigh = (High[0] - Close[0]) / TickSize;
            return distFromHigh >= rangeTicks * RejectionFractionOfRange;
        }

        private bool RejectionUp(double rangeTicks)
        {
            if (rangeTicks <= 0.0) return false;
            double distFromLow = (Close[0] - Low[0]) / TickSize;
            return distFromLow >= rangeTicks * RejectionFractionOfRange;
        }

        private double VolumeFactor()
        {
            double baseVol = _volumeSma[0];
            if (baseVol <= 0.0) return 0.0;
            return Volume[0] / baseVol;
        }

        private void EnterFade(bool isLong, double vwap)
        {
            int stopTicks = ComputeStopTicks(isLong);
            int targetTicksRR = (int)Math.Round(stopTicks * RewardRiskRatio);
            int targetTicksVwap = isLong
                ? Math.Max(1, (int)Math.Round((vwap - Close[0]) / TickSize))
                : Math.Max(1, (int)Math.Round((Close[0] - vwap) / TickSize));
            int targetTicks;
            if (string.Equals(TargetMode, "RR", StringComparison.OrdinalIgnoreCase))
                targetTicks = targetTicksRR;
            else if (string.Equals(TargetMode, "Vwap", StringComparison.OrdinalIgnoreCase))
                targetTicks = targetTicksVwap;
            else // VwapOrRR -> take the closer (smaller) target so fades exit faster
                targetTicks = Math.Min(targetTicksRR, targetTicksVwap);

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

        private int ToHHMM(DateTime value) { return value.Hour * 100 + value.Minute; }

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

        private string TelemetrySignal(string side) { return GetType().Name + "." + side; }

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
            if (MaxDailyLossUsd > 0.0 && _sessionRealizedPnl <= -MaxDailyLossUsd) _sessionStopped = true;
            if (MaxWeeklyLossUsd > 0.0 && _weeklyRealizedPnl <= -MaxWeeklyLossUsd) _sessionStopped = true;
            if (MaxConsecutiveLosses > 0 && _consecutiveLosses >= MaxConsecutiveLosses) _sessionStopped = true;
            _lastProcessedTradeCount = total;
            ClearActiveTradeState();
        }

        #region Properties
        [NinjaScriptProperty] [Display(Name = "InstrumentName", GroupName = "01-Instrument", Order = 0)]
        public string InstrumentName { get; set; }
        [NinjaScriptProperty] [Display(Name = "ContractName", GroupName = "01-Instrument", Order = 1)]
        public string ContractName { get; set; }
        [NinjaScriptProperty] [Display(Name = "SessionTemplateName", GroupName = "01-Instrument", Order = 2)]
        public string SessionTemplateName { get; set; }
        [NinjaScriptProperty, Range(1, 3600)] [Display(Name = "BaseTimeframeSeconds", GroupName = "01-Instrument", Order = 3)]
        public int BaseTimeframeSeconds { get; set; }
        [NinjaScriptProperty] [Display(Name = "StartingCapital", GroupName = "02-Risk Profile", Order = 0)]
        public double StartingCapital { get; set; }
        [NinjaScriptProperty] [Display(Name = "IntradayOnly", GroupName = "02-Risk Profile", Order = 1)]
        public bool IntradayOnly { get; set; }
        [NinjaScriptProperty] [Display(Name = "ActiveMarginPerContract", GroupName = "02-Risk Profile", Order = 2)]
        public double ActiveMarginPerContract { get; set; }
        [NinjaScriptProperty] [Display(Name = "MaxContractsByCapital", GroupName = "02-Risk Profile", Order = 3)]
        public int MaxContractsByCapital { get; set; }
        [NinjaScriptProperty] [Display(Name = "InstrumentStatus", GroupName = "02-Risk Profile", Order = 4)]
        public string InstrumentStatus { get; set; }
        [NinjaScriptProperty] [Display(Name = "MarginSourceBroker", GroupName = "02-Risk Profile", Order = 5)]
        public string MarginSourceBroker { get; set; }
        [NinjaScriptProperty] [Display(Name = "EnableLong", GroupName = "03-Direction", Order = 0)]
        public bool EnableLong { get; set; }
        [NinjaScriptProperty] [Display(Name = "EnableShort", GroupName = "03-Direction", Order = 1)]
        public bool EnableShort { get; set; }
        [NinjaScriptProperty, Range(0, 2359)] [Display(Name = "TradeStartTime", GroupName = "04-Time", Order = 0)]
        public int TradeStartTime { get; set; }
        [NinjaScriptProperty, Range(0, 2359)] [Display(Name = "TradeEndTime", GroupName = "04-Time", Order = 1)]
        public int TradeEndTime { get; set; }
        [NinjaScriptProperty, Range(0, 2359)] [Display(Name = "ForceFlatTime", GroupName = "04-Time", Order = 2)]
        public int ForceFlatTime { get; set; }
        [NinjaScriptProperty, Range(0.5, 5.0)] [Display(Name = "BandStdDev", GroupName = "05-Signal", Order = 0)]
        public double BandStdDev { get; set; }
        [NinjaScriptProperty, Range(1, 60)] [Display(Name = "MinVwapBarsBeforeFade", GroupName = "05-Signal", Order = 1)]
        public int MinVwapBarsBeforeFade { get; set; }
        [NinjaScriptProperty, Range(1, 200)] [Display(Name = "MinDistanceFromVwapTicks", GroupName = "05-Signal", Order = 2)]
        public int MinDistanceFromVwapTicks { get; set; }
        [NinjaScriptProperty] [Display(Name = "RequireRejection", GroupName = "05-Signal", Order = 3)]
        public bool RequireRejection { get; set; }
        [NinjaScriptProperty, Range(0.0, 1.0)] [Display(Name = "RejectionFractionOfRange", GroupName = "05-Signal", Order = 4)]
        public double RejectionFractionOfRange { get; set; }
        [NinjaScriptProperty, Range(2, 100)] [Display(Name = "AdxPeriod", GroupName = "06-Confirm", Order = 0)]
        public int AdxPeriod { get; set; }
        [NinjaScriptProperty, Range(5.0, 80.0)] [Display(Name = "RangeAdxMax", GroupName = "06-Confirm", Order = 1)]
        public double RangeAdxMax { get; set; }
        [NinjaScriptProperty, Range(2, 100)] [Display(Name = "RsiPeriod", GroupName = "06-Confirm", Order = 2)]
        public int RsiPeriod { get; set; }
        [NinjaScriptProperty, Range(0.0, 100.0)] [Display(Name = "RsiShortMin", GroupName = "06-Confirm", Order = 3)]
        public double RsiShortMin { get; set; }
        [NinjaScriptProperty, Range(0.0, 100.0)] [Display(Name = "RsiLongMax", GroupName = "06-Confirm", Order = 4)]
        public double RsiLongMax { get; set; }
        [NinjaScriptProperty, Range(2, 200)] [Display(Name = "AtrPeriod", GroupName = "07-Filters", Order = 0)]
        public int AtrPeriod { get; set; }
        [NinjaScriptProperty, Range(2, 500)] [Display(Name = "VolumeSmaPeriod", GroupName = "07-Filters", Order = 1)]
        public int VolumeSmaPeriod { get; set; }
        [NinjaScriptProperty, Range(0.5, 10.0)] [Display(Name = "VolCeilingFactor", GroupName = "07-Filters", Order = 2)]
        public double VolCeilingFactor { get; set; }
        [NinjaScriptProperty, Range(0.0, 5.0)] [Display(Name = "VolMinFactor", GroupName = "07-Filters", Order = 3)]
        public double VolMinFactor { get; set; }
        [NinjaScriptProperty, Range(1, 400)] [Display(Name = "MinBarRangeTicks", GroupName = "07-Filters", Order = 4)]
        public int MinBarRangeTicks { get; set; }
        [NinjaScriptProperty, Range(1, 1000)] [Display(Name = "MaxBarRangeTicks", GroupName = "07-Filters", Order = 5)]
        public int MaxBarRangeTicks { get; set; }
        [NinjaScriptProperty, Range(0, 100)] [Display(Name = "StopBufferTicks", GroupName = "08-Orders", Order = 0)]
        public int StopBufferTicks { get; set; }
        [NinjaScriptProperty, Range(1, 400)] [Display(Name = "MinStopTicks", GroupName = "08-Orders", Order = 1)]
        public int MinStopTicks { get; set; }
        [NinjaScriptProperty, Range(1, 600)] [Display(Name = "MaxStopTicks", GroupName = "08-Orders", Order = 2)]
        public int MaxStopTicks { get; set; }
        [NinjaScriptProperty, Range(0.0, 10.0)] [Display(Name = "AtrStopMult", GroupName = "08-Orders", Order = 3)]
        public double AtrStopMult { get; set; }
        [NinjaScriptProperty] [Display(Name = "TargetMode", GroupName = "08-Orders", Order = 4)]
        public string TargetMode { get; set; }
        [NinjaScriptProperty, Range(0.1, 10.0)] [Display(Name = "RewardRiskRatio", GroupName = "08-Orders", Order = 5)]
        public double RewardRiskRatio { get; set; }
        [NinjaScriptProperty, Range(1, 400)] [Display(Name = "MinTargetTicks", GroupName = "08-Orders", Order = 6)]
        public int MinTargetTicks { get; set; }
        [NinjaScriptProperty, Range(0.0, 5.0)] [Display(Name = "MoveToBreakevenAtR", GroupName = "08-Orders", Order = 7)]
        public double MoveToBreakevenAtR { get; set; }
        [NinjaScriptProperty, Range(0, 50)] [Display(Name = "BreakevenPlusTicks", GroupName = "08-Orders", Order = 8)]
        public int BreakevenPlusTicks { get; set; }
        [NinjaScriptProperty] [Display(Name = "UseTrailingStop", GroupName = "08-Orders", Order = 9)]
        public bool UseTrailingStop { get; set; }
        [NinjaScriptProperty, Range(0.0, 5.0)] [Display(Name = "TrailAfterR", GroupName = "08-Orders", Order = 10)]
        public double TrailAfterR { get; set; }
        [NinjaScriptProperty, Range(1, 200)] [Display(Name = "TrailDistanceTicks", GroupName = "08-Orders", Order = 11)]
        public int TrailDistanceTicks { get; set; }
        [NinjaScriptProperty] [Display(Name = "UseTimeStop", GroupName = "08-Orders", Order = 12)]
        public bool UseTimeStop { get; set; }
        [NinjaScriptProperty, Range(1, 100)] [Display(Name = "TimeStopBars", GroupName = "08-Orders", Order = 13)]
        public int TimeStopBars { get; set; }
        [NinjaScriptProperty, Range(0.0, 2.0)] [Display(Name = "MinProgressR", GroupName = "08-Orders", Order = 14)]
        public double MinProgressR { get; set; }
        [NinjaScriptProperty, Range(0.01, 10.0)] [Display(Name = "RiskPerTradePct", GroupName = "09-Risk", Order = 0)]
        public double RiskPerTradePct { get; set; }
        [NinjaScriptProperty, Range(0, 100)] [Display(Name = "UserMaxContracts", GroupName = "09-Risk", Order = 1)]
        public int UserMaxContracts { get; set; }
        [NinjaScriptProperty, Range(0, 100)] [Display(Name = "MaxOpenPositions", GroupName = "09-Risk", Order = 2)]
        public int MaxOpenPositions { get; set; }
        [NinjaScriptProperty] [Display(Name = "MaxDailyLossUsd", GroupName = "09-Risk", Order = 3)]
        public double MaxDailyLossUsd { get; set; }
        [NinjaScriptProperty] [Display(Name = "MaxWeeklyLossUsd", GroupName = "09-Risk", Order = 4)]
        public double MaxWeeklyLossUsd { get; set; }
        [NinjaScriptProperty, Range(0, 100)] [Display(Name = "MaxTradesPerDay", GroupName = "09-Risk", Order = 5)]
        public int MaxTradesPerDay { get; set; }
        [NinjaScriptProperty, Range(0, 100)] [Display(Name = "HardMaxTradesPerDay", GroupName = "09-Risk", Order = 6)]
        public int HardMaxTradesPerDay { get; set; }
        [NinjaScriptProperty, Range(0, 20)] [Display(Name = "MaxConsecutiveLosses", GroupName = "09-Risk", Order = 7)]
        public int MaxConsecutiveLosses { get; set; }
        [NinjaScriptProperty, Range(0, 20)] [Display(Name = "PauseAfterConsecutiveLosses", GroupName = "09-Risk", Order = 8)]
        public int PauseAfterConsecutiveLosses { get; set; }
        [NinjaScriptProperty, Range(0, 480)] [Display(Name = "PauseMinutesAfterLosses", GroupName = "09-Risk", Order = 9)]
        public int PauseMinutesAfterLosses { get; set; }
        [NinjaScriptProperty] [Display(Name = "RoundTurnCommission", GroupName = "09-Risk", Order = 10)]
        public double RoundTurnCommission { get; set; }
        [NinjaScriptProperty, Range(0, 100)] [Display(Name = "SlippageTicks", GroupName = "09-Risk", Order = 11)]
        public int SlippageTicks { get; set; }
        #endregion
    }
}
