// =============================================================================
// NTACapitulationSnapbackPilot
// -----------------------------------------------------------------------------
// Cross-instrument research pilot for a new strategy family.
//
// Hypothesis:
//   A large intraday displacement bar with abnormal volume often represents
//   forced liquidity/stop-flow rather than clean trend discovery. When the next
//   bar confirms a snapback toward session VWAP, enter the reversal with fixed
//   after-cost risk controls.
//
// This is intentionally not a B1/VWAP pullback, ORB, H&S, or existing MNQ scalp
// wrapper. It is a standalone research class used for cross-root scanning before
// any deploy cell is selected.
// =============================================================================

#region Using declarations
using System;
using System.ComponentModel.DataAnnotations;
using NinjaTrader.Cbi;
using NinjaTrader.Data;
using NinjaTrader.NinjaScript;
using NinjaTrader.NinjaScript.Indicators;
using NinjaTrader.NinjaScript.Strategies;
#endregion

namespace NinjaTrader.NinjaScript.Strategies
{
    public class NTACapitulationSnapbackPilot : Strategy
    {
        private ATR _atr;
        private ADX _adx;
        private EMA _ema;
        private SMA _volSma;
        private Series<double> _vwapSeries;

        private DateTime _sessionDate = DateTime.MinValue;
        private double _cumTpv;
        private double _cumVol;
        private double _sessionStartCumProfit;
        private int _tradesToday;

        private int _lastEntryBar = -1;
        private double _lastEntryPrice;
        private int _lastStopTicks;
        private string _activeSignal = "";

        protected override void OnStateChange()
        {
            if (State == State.SetDefaults)
            {
                Name = "NTACapitulationSnapbackPilot";
                Description = "Cross-root research pilot: abnormal volume displacement bar, then confirmed snapback toward session VWAP.";
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
                BarsRequiredToTrade = 80;
                IsInstantiatedOnEachOptimizationIteration = true;

                StartingCapital = 2000.0;
                IntradayOnly = true;
                ActiveMarginPerContract = 50.0;
                MaxContractsByCapital = 40;
                InstrumentStatus = "allowed";
                MarginSourceBroker = "NinjaTrader";

                RiskPerTradePct = 1.0;
                MaxDailyLossPct = 3.0;
                MaxDailyProfitPct = 0.0;
                MaxTradesPerDay = 8;
                UserMaxContracts = 5;
                RoundTurnCommission = 1.90;
                SlippageTicks = 1;

                EnableLong = true;
                EnableShort = true;
                TradeStartTime = 600;
                TradeEndTime = 1230;
                ForceFlatTime = 1325;

                AtrPeriod = 14;
                AdxPeriod = 14;
                EmaPeriod = 50;
                VolumeSmaPeriod = 20;
                MinAdx = 0.0;
                MaxAdx = 100.0;
                MinVolumeFactor = 1.8;
                ShockAtrMult = 1.20;
                ExtensionAtr = 0.90;
                MinBodyFraction = 0.55;
                ReclaimFraction = 0.35;
                ExtremeLookbackBars = 12;
                MinConfirmBodyFraction = 0.0;
                RequireNoExtremeBreak = false;
                RequireReclaimPrevOpen = false;
                RequireVwapReclaim = false;

                MinStopTicks = 8;
                MaxStopTicks = 80;
                StopBufferTicks = 2;
                RewardRiskRatio = 1.25;
                MoveToBreakevenAtR = 0.80;
                TrailAfterR = 1.60;
                MaxHoldBars = 18;
            }
            else if (State == State.DataLoaded)
            {
                _atr = ATR(AtrPeriod);
                _adx = ADX(AdxPeriod);
                _ema = EMA(EmaPeriod);
                _volSma = SMA(Volume, VolumeSmaPeriod);
                _vwapSeries = new Series<double>(this);
            }
        }

        protected override void OnBarUpdate()
        {
            if (BarsInProgress != 0)
                return;

            UpdateSessionState();
            UpdateSessionVwap();

            if (CurrentBar < RequiredBars())
                return;

            int hhmm = ToTimeHHMM(Time[0]);

            if (ForceFlatTime > 0 && hhmm >= ForceFlatTime)
            {
                FlattenOpenPosition("ForceFlat");
                return;
            }

            if (Position.MarketPosition != MarketPosition.Flat)
            {
                ManageOpenPosition();
                return;
            }

            if (!CanTradeNow(hhmm))
                return;

            EvaluateSnapbackEntry();
        }

        private int RequiredBars()
        {
            return Math.Max(Math.Max(AtrPeriod, VolumeSmaPeriod), Math.Max(EmaPeriod, ExtremeLookbackBars)) + 5;
        }

        private void UpdateSessionState()
        {
            if (_sessionDate == Time[0].Date)
                return;

            _sessionDate = Time[0].Date;
            _cumTpv = 0.0;
            _cumVol = 0.0;
            _tradesToday = 0;
            _sessionStartCumProfit = SystemPerformance.AllTrades.TradesPerformance.Currency.CumProfit;
        }

        private void UpdateSessionVwap()
        {
            double volume = Math.Max(1.0, Convert.ToDouble(Volume[0]));
            double typical = (High[0] + Low[0] + Close[0]) / 3.0;
            _cumTpv += typical * volume;
            _cumVol += volume;
            _vwapSeries[0] = _cumVol > 0.0 ? _cumTpv / _cumVol : Close[0];
        }

        private bool CanTradeNow(int hhmm)
        {
            if (InstrumentStatus != null && InstrumentStatus.ToLowerInvariant() != "allowed")
                return false;
            if (StartingCapital <= 0.0 || ActiveMarginPerContract <= 0.0 || MaxContractsByCapital < 1)
                return false;
            if (hhmm < TradeStartTime || hhmm > TradeEndTime)
                return false;
            if (_tradesToday >= MaxTradesPerDay)
                return false;

            double dailyPnl = SystemPerformance.AllTrades.TradesPerformance.Currency.CumProfit - _sessionStartCumProfit;
            if (MaxDailyLossPct > 0.0 && dailyPnl <= -StartingCapital * MaxDailyLossPct / 100.0)
                return false;
            if (MaxDailyProfitPct > 0.0 && dailyPnl >= StartingCapital * MaxDailyProfitPct / 100.0)
                return false;

            return true;
        }

        private void EvaluateSnapbackEntry()
        {
            double atr = _atr[1];
            double vwap = _vwapSeries[1];
            double volBase = _volSma[1];
            if (atr <= 0.0 || vwap <= 0.0 || volBase <= 0.0)
                return;
            if (MinAdx > 0.0 && _adx[1] < MinAdx)
                return;
            if (MaxAdx < 100.0 && _adx[1] > MaxAdx)
                return;

            double prevRange = High[1] - Low[1];
            if (prevRange <= TickSize)
                return;

            double body = Math.Abs(Close[1] - Open[1]);
            double bodyFraction = body / prevRange;
            double volFactor = Convert.ToDouble(Volume[1]) / volBase;
            double extension = Math.Abs(Close[1] - vwap) / atr;
            bool shock = prevRange >= atr * ShockAtrMult
                         && bodyFraction >= MinBodyFraction
                         && volFactor >= MinVolumeFactor
                         && extension >= ExtensionAtr;
            if (!shock)
                return;

            double reclaimPx = prevRange * ReclaimFraction;
            bool madeLowExtreme = Low[1] <= LowestLow(2, ExtremeLookbackBars);
            bool madeHighExtreme = High[1] >= HighestHigh(2, ExtremeLookbackBars);
            double confirmRange = High[0] - Low[0];
            if (confirmRange <= TickSize)
                return;

            double confirmBodyFraction = Math.Abs(Close[0] - Open[0]) / confirmRange;
            if (MinConfirmBodyFraction > 0.0 && confirmBodyFraction < MinConfirmBodyFraction)
                return;

            if (EnableLong
                && Close[1] < Open[1]
                && Close[1] < vwap
                && madeLowExtreme
                && Close[0] > Open[0]
                && Close[0] >= Low[1] + reclaimPx
                && Close[0] > Close[1]
                && (!RequireNoExtremeBreak || Low[0] >= Low[1])
                && (!RequireReclaimPrevOpen || Close[0] >= Open[1])
                && (!RequireVwapReclaim || Close[0] >= vwap))
            {
                EnterSnapback(true);
                return;
            }

            if (EnableShort
                && Close[1] > Open[1]
                && Close[1] > vwap
                && madeHighExtreme
                && Close[0] < Open[0]
                && Close[0] <= High[1] - reclaimPx
                && Close[0] < Close[1]
                && (!RequireNoExtremeBreak || High[0] <= High[1])
                && (!RequireReclaimPrevOpen || Close[0] <= Open[1])
                && (!RequireVwapReclaim || Close[0] <= vwap))
            {
                EnterSnapback(false);
            }
        }

        private void EnterSnapback(bool isLong)
        {
            double entry = Close[0];
            double stopPrice = isLong
                ? Math.Min(Low[0], Low[1]) - StopBufferTicks * TickSize
                : Math.Max(High[0], High[1]) + StopBufferTicks * TickSize;
            double stopDist = Math.Abs(entry - stopPrice);
            int stopTicks = (int)Math.Ceiling(stopDist / TickSize);
            stopTicks = Math.Max(MinStopTicks, Math.Min(MaxStopTicks, stopTicks));
            int targetTicks = Math.Max(1, (int)Math.Round(stopTicks * RewardRiskRatio));
            int qty = ComputeQuantity(stopTicks);
            if (qty < 1)
                return;

            string signal = TelemetrySignal(isLong ? "Long" : "Short");
            SetStopLoss(signal, CalculationMode.Ticks, stopTicks, false);
            SetProfitTarget(signal, CalculationMode.Ticks, targetTicks);

            _lastEntryBar = CurrentBar;
            _lastEntryPrice = entry;
            _lastStopTicks = stopTicks;
            _activeSignal = signal;
            _tradesToday++;

            if (isLong)
                EnterLong(qty, signal);
            else
                EnterShort(qty, signal);
        }

        private int ComputeQuantity(int stopTicks)
        {
            double tickValue = Instrument.MasterInstrument.PointValue * TickSize;
            if (tickValue <= 0.0 || stopTicks < 1)
                return 0;

            double riskDollars = StartingCapital * RiskPerTradePct / 100.0;
            double contractRisk = stopTicks * tickValue
                + RoundTurnCommission
                + SlippageTicks * tickValue;
            if (riskDollars <= 0.0 || contractRisk <= 0.0)
                return 0;

            int byRisk = (int)Math.Floor(riskDollars / contractRisk);
            int byMargin = ActiveMarginPerContract > 0.0
                ? (int)Math.Floor(StartingCapital / ActiveMarginPerContract)
                : MaxContractsByCapital;
            int cap = Math.Min(UserMaxContracts, Math.Min(MaxContractsByCapital, byMargin));
            return Math.Max(0, Math.Min(byRisk, cap));
        }

        private string TelemetrySignal(string side)
        {
            return GetType().Name + "." + side;
        }

        private void ManageOpenPosition()
        {
            if (_lastEntryBar >= 0 && MaxHoldBars > 0 && CurrentBar - _lastEntryBar >= MaxHoldBars)
            {
                FlattenOpenPosition("TimeExit");
                return;
            }

            if (_lastStopTicks <= 0 || _lastEntryPrice <= 0.0)
                return;

            double rDist = _lastStopTicks * TickSize;
            double moved = Close[0] - _lastEntryPrice;
            double rMult = Position.MarketPosition == MarketPosition.Long ? moved / rDist : -moved / rDist;

            if (rMult >= MoveToBreakevenAtR)
                SetStopLoss(_activeSignal, CalculationMode.Price, _lastEntryPrice, false);

            if (rMult >= TrailAfterR)
            {
                double trailDist = Math.Max(1.0, _lastStopTicks / 2.0) * TickSize;
                if (Position.MarketPosition == MarketPosition.Long)
                {
                    double trail = Close[0] - trailDist;
                    if (trail > _lastEntryPrice)
                        SetStopLoss(_activeSignal, CalculationMode.Price, trail, false);
                }
                else if (Position.MarketPosition == MarketPosition.Short)
                {
                    double trail = Close[0] + trailDist;
                    if (trail < _lastEntryPrice)
                        SetStopLoss(_activeSignal, CalculationMode.Price, trail, false);
                }
            }
        }

        private void FlattenOpenPosition(string label)
        {
            if (Position.MarketPosition == MarketPosition.Long)
                ExitLong(label, _activeSignal);
            else if (Position.MarketPosition == MarketPosition.Short)
                ExitShort(label, _activeSignal);
        }

        private double LowestLow(int startAgo, int bars)
        {
            double value = Low[startAgo];
            int maxAgo = Math.Min(CurrentBar, startAgo + Math.Max(1, bars) - 1);
            for (int ago = startAgo + 1; ago <= maxAgo; ago++)
                value = Math.Min(value, Low[ago]);
            return value;
        }

        private double HighestHigh(int startAgo, int bars)
        {
            double value = High[startAgo];
            int maxAgo = Math.Min(CurrentBar, startAgo + Math.Max(1, bars) - 1);
            for (int ago = startAgo + 1; ago <= maxAgo; ago++)
                value = Math.Max(value, High[ago]);
            return value;
        }

        private int ToTimeHHMM(DateTime t)
        {
            return t.Hour * 100 + t.Minute;
        }

        #region Properties
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

        [NinjaScriptProperty, Range(0.01, 10.0)]
        [Display(Name = "RiskPerTradePct", GroupName = "02-Risk", Order = 0)]
        public double RiskPerTradePct { get; set; }

        [NinjaScriptProperty, Range(0.1, 50.0)]
        [Display(Name = "MaxDailyLossPct", GroupName = "02-Risk", Order = 1)]
        public double MaxDailyLossPct { get; set; }

        [NinjaScriptProperty, Range(0.0, 100.0)]
        [Display(Name = "MaxDailyProfitPct", GroupName = "02-Risk", Order = 2)]
        public double MaxDailyProfitPct { get; set; }

        [NinjaScriptProperty, Range(1, 50)]
        [Display(Name = "MaxTradesPerDay", GroupName = "02-Risk", Order = 3)]
        public int MaxTradesPerDay { get; set; }

        [NinjaScriptProperty, Range(1, 100)]
        [Display(Name = "UserMaxContracts", GroupName = "02-Risk", Order = 4)]
        public int UserMaxContracts { get; set; }

        [NinjaScriptProperty, Range(0.0, 100.0)]
        [Display(Name = "RoundTurnCommission", GroupName = "02-Risk", Order = 5)]
        public double RoundTurnCommission { get; set; }

        [NinjaScriptProperty, Range(0, 20)]
        [Display(Name = "SlippageTicks", GroupName = "02-Risk", Order = 6)]
        public int SlippageTicks { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "EnableLong", GroupName = "03-Setup", Order = 0)]
        public bool EnableLong { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "EnableShort", GroupName = "03-Setup", Order = 1)]
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

        [NinjaScriptProperty, Range(2, 200)]
        [Display(Name = "AtrPeriod", GroupName = "05-Signal", Order = 0)]
        public int AtrPeriod { get; set; }

        [NinjaScriptProperty, Range(2, 200)]
        [Display(Name = "AdxPeriod", GroupName = "05-Signal", Order = 1)]
        public int AdxPeriod { get; set; }

        [NinjaScriptProperty, Range(2, 400)]
        [Display(Name = "EmaPeriod", GroupName = "05-Signal", Order = 2)]
        public int EmaPeriod { get; set; }

        [NinjaScriptProperty, Range(2, 500)]
        [Display(Name = "VolumeSmaPeriod", GroupName = "05-Signal", Order = 3)]
        public int VolumeSmaPeriod { get; set; }

        [NinjaScriptProperty, Range(0.0, 100.0)]
        [Display(Name = "MinAdx", GroupName = "05-Signal", Order = 4)]
        public double MinAdx { get; set; }

        [NinjaScriptProperty, Range(0.0, 100.0)]
        [Display(Name = "MaxAdx", GroupName = "05-Signal", Order = 5)]
        public double MaxAdx { get; set; }

        [NinjaScriptProperty, Range(0.0, 20.0)]
        [Display(Name = "MinVolumeFactor", GroupName = "05-Signal", Order = 6)]
        public double MinVolumeFactor { get; set; }

        [NinjaScriptProperty, Range(0.1, 10.0)]
        [Display(Name = "ShockAtrMult", GroupName = "05-Signal", Order = 7)]
        public double ShockAtrMult { get; set; }

        [NinjaScriptProperty, Range(0.1, 10.0)]
        [Display(Name = "ExtensionAtr", GroupName = "05-Signal", Order = 8)]
        public double ExtensionAtr { get; set; }

        [NinjaScriptProperty, Range(0.1, 1.0)]
        [Display(Name = "MinBodyFraction", GroupName = "05-Signal", Order = 9)]
        public double MinBodyFraction { get; set; }

        [NinjaScriptProperty, Range(0.05, 1.0)]
        [Display(Name = "ReclaimFraction", GroupName = "05-Signal", Order = 10)]
        public double ReclaimFraction { get; set; }

        [NinjaScriptProperty, Range(3, 100)]
        [Display(Name = "ExtremeLookbackBars", GroupName = "05-Signal", Order = 11)]
        public int ExtremeLookbackBars { get; set; }

        [NinjaScriptProperty, Range(0.0, 1.0)]
        [Display(Name = "MinConfirmBodyFraction", GroupName = "05-Signal", Order = 12)]
        public double MinConfirmBodyFraction { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "RequireNoExtremeBreak", GroupName = "05-Signal", Order = 13)]
        public bool RequireNoExtremeBreak { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "RequireReclaimPrevOpen", GroupName = "05-Signal", Order = 14)]
        public bool RequireReclaimPrevOpen { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "RequireVwapReclaim", GroupName = "05-Signal", Order = 15)]
        public bool RequireVwapReclaim { get; set; }

        [NinjaScriptProperty, Range(1, 1000)]
        [Display(Name = "MinStopTicks", GroupName = "06-Exits", Order = 0)]
        public int MinStopTicks { get; set; }

        [NinjaScriptProperty, Range(1, 5000)]
        [Display(Name = "MaxStopTicks", GroupName = "06-Exits", Order = 1)]
        public int MaxStopTicks { get; set; }

        [NinjaScriptProperty, Range(0, 100)]
        [Display(Name = "StopBufferTicks", GroupName = "06-Exits", Order = 2)]
        public int StopBufferTicks { get; set; }

        [NinjaScriptProperty, Range(0.1, 20.0)]
        [Display(Name = "RewardRiskRatio", GroupName = "06-Exits", Order = 3)]
        public double RewardRiskRatio { get; set; }

        [NinjaScriptProperty, Range(0.0, 10.0)]
        [Display(Name = "MoveToBreakevenAtR", GroupName = "06-Exits", Order = 4)]
        public double MoveToBreakevenAtR { get; set; }

        [NinjaScriptProperty, Range(0.0, 20.0)]
        [Display(Name = "TrailAfterR", GroupName = "06-Exits", Order = 5)]
        public double TrailAfterR { get; set; }

        [NinjaScriptProperty, Range(1, 200)]
        [Display(Name = "MaxHoldBars", GroupName = "06-Exits", Order = 6)]
        public int MaxHoldBars { get; set; }
        #endregion
    }
}
