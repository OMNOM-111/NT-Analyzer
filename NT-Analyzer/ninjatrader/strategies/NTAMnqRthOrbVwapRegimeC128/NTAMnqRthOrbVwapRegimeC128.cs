// =============================================================================
// NTAMnqRthOrbVwapRegimeC128
// -----------------------------------------------------------------------------
// Reference Pattern: REF-021 ORB + VWAP Direction Filter
// Урок провального AI-CELL: CELL-019 ORB Retest без VWAP/режимного фильтра не прошел OOS; 5m mean-reversion съедалась комиссией.
// Гипотеза модификации: 15m RTH ORB + session VWAP + EMA20/EMA50 + ADX снизит ложные пробои и сохранит gross_per_trade выше комиссии.
// Экономика сделки: default target 60 ticks MNQ = $30 gross против $1.90 комиссии и 1 tick slippage.
// Проверка размера позиции: default stop 24 ticks = $12 + $1.90 + $0.50 = $14.40 риска; при $2k и 0.8% риск-бюджете допускается 1 контракт.
// Макс. сделок в день: 1 total by default, чтобы избежать overtrading из CELL-005.
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
    public class NTAMnqRthOrbVwapRegimeC128 : Strategy
    {
        private EMA emaFast;
        private EMA emaSlow;
        private ADX adx;
        private ATR atr;

        private DateTime currentSessionDate = DateTime.MinValue;
        private double sessionStartCumProfit;
        private int tradesToday;
        private bool tradingEnabled;

        private double openingRangeHigh;
        private double openingRangeLow;
        private bool openingRangeComplete;
        private bool longTakenToday;
        private bool shortTakenToday;

        private double sessionPv;
        private double sessionVolume;
        private double sessionVwap;
        private double previousSessionVwap;

        protected override void OnStateChange()
        {
            if (State == State.SetDefaults)
            {
                Name = "RTH ORB VWAP Regime MNQ v1 c128";
                Description = "MNQ CELL-128 15m RTH ORB breakout with session VWAP, EMA regime and ADX filter.";
                Calculate = Calculate.OnBarClose;
                EntriesPerDirection = 1;
                EntryHandling = EntryHandling.AllEntries;
                IsExitOnSessionCloseStrategy = true;
                ExitOnSessionCloseSeconds = 30;
                IsFillLimitOnTouch = false;
                MaximumBarsLookBack = MaximumBarsLookBack.TwoHundredFiftySix;
                OrderFillResolution = OrderFillResolution.High;
                Slippage = 1;
                StartBehavior = StartBehavior.WaitUntilFlat;
                TimeInForce = TimeInForce.Day;
                TraceOrders = false;
                RealtimeErrorHandling = RealtimeErrorHandling.StopCancelClose;
                StopTargetHandling = StopTargetHandling.PerEntryExecution;
                BarsRequiredToTrade = 60;
                IsInstantiatedOnEachOptimizationIteration = true;

                Quantity = 1;
                StopLossTicks = 24;
                ProfitTargetTicks = 60;
                MaxDailyLoss = 90.0;
                MaxTradesPerDay = 1;
                RiskPerTradePct = 0.8;
                StartingCapital = 2000.0;
                RoundTurnCommission = 1.90;
                SlippageTicks = 1;

                EnableLong = true;
                EnableShort = true;
                SessionStartTimePT = 63000;
                OrbEndTimePT = 70000;
                EntryEndTimePT = 113000;
                SessionEndTimePT = 123000;

                FastEmaPeriod = 20;
                SlowEmaPeriod = 50;
                AdxPeriod = 14;
                MinAdx = 18.0;
                AtrPeriod = 14;
                MinAtrTicks = 18;
                MaxAtrTicks = 120;
                MinOrbRangeTicks = 20;
                MaxOrbRangeTicks = 220;
                BreakoutBufferTicks = 2;
                MinVwapDistanceTicks = 2;
                RequireVwapSlope = true;
                VwapSlopeToleranceTicks = 1;
            }
            else if (State == State.DataLoaded)
            {
                emaFast = EMA(FastEmaPeriod);
                emaSlow = EMA(SlowEmaPeriod);
                adx = ADX(AdxPeriod);
                atr = ATR(AtrPeriod);
            }
        }

        protected override void OnBarUpdate()
        {
            if (BarsInProgress != 0)
                return;
            if (CurrentBar < BarsRequiredToTrade)
                return;

            int nowPt = ToTime(Time[0]);
            if (Bars.IsFirstBarOfSession || currentSessionDate.Date != Time[0].Date)
                ResetSessionState();

            double sessionPnl = SystemPerformance.AllTrades.TradesPerformance.Currency.CumProfit - sessionStartCumProfit;

            if (nowPt < SessionStartTimePT)
                return;

            UpdateSessionVwap();

            if (nowPt >= SessionEndTimePT)
            {
                ForceFlat();
                return;
            }

            if (sessionPnl <= -MaxDailyLoss)
            {
                tradingEnabled = false;
                ForceFlat();
                return;
            }

            UpdateOpeningRange(nowPt);

            if (nowPt <= OrbEndTimePT)
                return;
            if (nowPt > EntryEndTimePT)
                return;
            if (!tradingEnabled || !openingRangeComplete)
                return;
            if (Position.MarketPosition != MarketPosition.Flat)
                return;
            if (tradesToday >= MaxTradesPerDay)
                return;

            TryEnterBreakout();
        }

        private void ResetSessionState()
        {
            currentSessionDate = Time[0].Date;
            sessionStartCumProfit = SystemPerformance.AllTrades.TradesPerformance.Currency.CumProfit;
            tradesToday = 0;
            tradingEnabled = true;
            openingRangeHigh = double.NaN;
            openingRangeLow = double.NaN;
            openingRangeComplete = false;
            longTakenToday = false;
            shortTakenToday = false;
            sessionPv = 0.0;
            sessionVolume = 0.0;
            sessionVwap = Close[0];
            previousSessionVwap = Close[0];
        }

        private void UpdateSessionVwap()
        {
            previousSessionVwap = sessionVwap;
            double volume = Math.Max(1.0, Volume[0]);
            double typical = (High[0] + Low[0] + Close[0]) / 3.0;
            sessionPv += typical * volume;
            sessionVolume += volume;
            if (sessionVolume > 0.0)
                sessionVwap = sessionPv / sessionVolume;
        }

        private void UpdateOpeningRange(int nowPt)
        {
            if (nowPt < SessionStartTimePT || nowPt > OrbEndTimePT)
                return;

            if (double.IsNaN(openingRangeHigh) || High[0] > openingRangeHigh)
                openingRangeHigh = High[0];
            if (double.IsNaN(openingRangeLow) || Low[0] < openingRangeLow)
                openingRangeLow = Low[0];

            if (nowPt >= OrbEndTimePT && !double.IsNaN(openingRangeHigh) && !double.IsNaN(openingRangeLow))
                openingRangeComplete = true;
        }

        private void TryEnterBreakout()
        {
            double orRangeTicks = (openingRangeHigh - openingRangeLow) / TickSize;
            if (orRangeTicks < MinOrbRangeTicks || orRangeTicks > MaxOrbRangeTicks)
                return;

            double atrTicks = atr[0] / TickSize;
            if (atrTicks < MinAtrTicks || atrTicks > MaxAtrTicks)
                return;
            if (adx[0] < MinAdx)
                return;

            int quantity = ComputeQuantity();
            if (quantity < 1)
                return;

            double buffer = BreakoutBufferTicks * TickSize;
            double vwapDistance = MinVwapDistanceTicks * TickSize;
            bool vwapRising = sessionVwap >= previousSessionVwap - VwapSlopeToleranceTicks * TickSize;
            bool vwapFalling = sessionVwap <= previousSessionVwap + VwapSlopeToleranceTicks * TickSize;

            bool longBreak = EnableLong
                && !longTakenToday
                && Close[0] > openingRangeHigh + buffer
                && Close[1] <= openingRangeHigh + buffer
                && Close[0] > sessionVwap + vwapDistance
                && emaFast[0] > emaSlow[0]
                && (!RequireVwapSlope || vwapRising);

            bool shortBreak = EnableShort
                && !shortTakenToday
                && Close[0] < openingRangeLow - buffer
                && Close[1] >= openingRangeLow - buffer
                && Close[0] < sessionVwap - vwapDistance
                && emaFast[0] < emaSlow[0]
                && (!RequireVwapSlope || vwapFalling);

            if (longBreak)
            {
                string signal = TelemetrySignal("Long");
                SetStopLoss(signal, CalculationMode.Ticks, StopLossTicks, false);
                SetProfitTarget(signal, CalculationMode.Ticks, ProfitTargetTicks);
                tradesToday++;
                longTakenToday = true;
                EnterLong(quantity, signal);
            }
            else if (shortBreak)
            {
                string signal = TelemetrySignal("Short");
                SetStopLoss(signal, CalculationMode.Ticks, StopLossTicks, false);
                SetProfitTarget(signal, CalculationMode.Ticks, ProfitTargetTicks);
                tradesToday++;
                shortTakenToday = true;
                EnterShort(quantity, signal);
            }
        }

        private int ComputeQuantity()
        {
            double tickValue = Instrument.MasterInstrument.PointValue * TickSize;
            double contractRisk = StopLossTicks * tickValue + RoundTurnCommission + SlippageTicks * tickValue;
            double riskBudget = StartingCapital * RiskPerTradePct / 100.0;
            int byRisk = (int)Math.Floor(riskBudget / Math.Max(contractRisk, 0.01));
            return Math.Max(0, Math.Min(Quantity, byRisk));
        }

        private string TelemetrySignal(string side)
        {
            return GetType().Name + "." + side;
        }

        private void ForceFlat()
        {
            if (Position.MarketPosition == MarketPosition.Long)
                ExitLong();
            else if (Position.MarketPosition == MarketPosition.Short)
                ExitShort();
        }

        #region Properties
        [NinjaScriptProperty]
        [Range(1, 5)]
        [Display(Name = "Quantity", GroupName = "01-Risk", Order = 1)]
        public int Quantity { get; set; }

        [NinjaScriptProperty]
        [Range(4, 80)]
        [Display(Name = "StopLossTicks", GroupName = "01-Risk", Order = 2)]
        public int StopLossTicks { get; set; }

        [NinjaScriptProperty]
        [Range(8, 200)]
        [Display(Name = "ProfitTargetTicks", GroupName = "01-Risk", Order = 3)]
        public int ProfitTargetTicks { get; set; }

        [NinjaScriptProperty]
        [Range(10.0, 500.0)]
        [Display(Name = "MaxDailyLoss", GroupName = "01-Risk", Order = 4)]
        public double MaxDailyLoss { get; set; }

        [NinjaScriptProperty]
        [Range(1, 4)]
        [Display(Name = "MaxTradesPerDay", GroupName = "01-Risk", Order = 5)]
        public int MaxTradesPerDay { get; set; }

        [NinjaScriptProperty]
        [Range(0.1, 3.0)]
        [Display(Name = "RiskPerTradePct", GroupName = "01-Risk", Order = 6)]
        public double RiskPerTradePct { get; set; }

        [NinjaScriptProperty]
        [Range(500.0, 100000.0)]
        [Display(Name = "StartingCapital", GroupName = "01-Risk", Order = 7)]
        public double StartingCapital { get; set; }

        [NinjaScriptProperty]
        [Range(0.0, 20.0)]
        [Display(Name = "RoundTurnCommission", GroupName = "01-Risk", Order = 8)]
        public double RoundTurnCommission { get; set; }

        [NinjaScriptProperty]
        [Range(0, 10)]
        [Display(Name = "SlippageTicks", GroupName = "01-Risk", Order = 9)]
        public int SlippageTicks { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "EnableLong", GroupName = "02-Direction", Order = 1)]
        public bool EnableLong { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "EnableShort", GroupName = "02-Direction", Order = 2)]
        public bool EnableShort { get; set; }

        [NinjaScriptProperty]
        [Range(0, 235959)]
        [Display(Name = "SessionStartTimePT", GroupName = "03-Time", Order = 1)]
        public int SessionStartTimePT { get; set; }

        [NinjaScriptProperty]
        [Range(0, 235959)]
        [Display(Name = "OrbEndTimePT", GroupName = "03-Time", Order = 2)]
        public int OrbEndTimePT { get; set; }

        [NinjaScriptProperty]
        [Range(0, 235959)]
        [Display(Name = "EntryEndTimePT", GroupName = "03-Time", Order = 3)]
        public int EntryEndTimePT { get; set; }

        [NinjaScriptProperty]
        [Range(0, 235959)]
        [Display(Name = "SessionEndTimePT", GroupName = "03-Time", Order = 4)]
        public int SessionEndTimePT { get; set; }

        [NinjaScriptProperty]
        [Range(2, 100)]
        [Display(Name = "FastEmaPeriod", GroupName = "04-Regime", Order = 1)]
        public int FastEmaPeriod { get; set; }

        [NinjaScriptProperty]
        [Range(5, 200)]
        [Display(Name = "SlowEmaPeriod", GroupName = "04-Regime", Order = 2)]
        public int SlowEmaPeriod { get; set; }

        [NinjaScriptProperty]
        [Range(2, 100)]
        [Display(Name = "AdxPeriod", GroupName = "04-Regime", Order = 3)]
        public int AdxPeriod { get; set; }

        [NinjaScriptProperty]
        [Range(0.0, 80.0)]
        [Display(Name = "MinAdx", GroupName = "04-Regime", Order = 4)]
        public double MinAdx { get; set; }

        [NinjaScriptProperty]
        [Range(2, 100)]
        [Display(Name = "AtrPeriod", GroupName = "04-Regime", Order = 5)]
        public int AtrPeriod { get; set; }

        [NinjaScriptProperty]
        [Range(1, 300)]
        [Display(Name = "MinAtrTicks", GroupName = "04-Regime", Order = 6)]
        public int MinAtrTicks { get; set; }

        [NinjaScriptProperty]
        [Range(1, 500)]
        [Display(Name = "MaxAtrTicks", GroupName = "04-Regime", Order = 7)]
        public int MaxAtrTicks { get; set; }

        [NinjaScriptProperty]
        [Range(1, 500)]
        [Display(Name = "MinOrbRangeTicks", GroupName = "05-ORB", Order = 1)]
        public int MinOrbRangeTicks { get; set; }

        [NinjaScriptProperty]
        [Range(1, 1000)]
        [Display(Name = "MaxOrbRangeTicks", GroupName = "05-ORB", Order = 2)]
        public int MaxOrbRangeTicks { get; set; }

        [NinjaScriptProperty]
        [Range(0, 40)]
        [Display(Name = "BreakoutBufferTicks", GroupName = "05-ORB", Order = 3)]
        public int BreakoutBufferTicks { get; set; }

        [NinjaScriptProperty]
        [Range(0, 80)]
        [Display(Name = "MinVwapDistanceTicks", GroupName = "06-VWAP", Order = 1)]
        public int MinVwapDistanceTicks { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "RequireVwapSlope", GroupName = "06-VWAP", Order = 2)]
        public bool RequireVwapSlope { get; set; }

        [NinjaScriptProperty]
        [Range(0, 20)]
        [Display(Name = "VwapSlopeToleranceTicks", GroupName = "06-VWAP", Order = 3)]
        public int VwapSlopeToleranceTicks { get; set; }
        #endregion
    }
}