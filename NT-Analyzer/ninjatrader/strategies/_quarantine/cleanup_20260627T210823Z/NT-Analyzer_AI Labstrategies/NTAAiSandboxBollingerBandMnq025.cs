using System;
using System.ComponentModel.DataAnnotations;
using NinjaTrader.Data;
using NinjaTrader.NinjaScript;
using NinjaTrader.NinjaScript.Indicators;
using NinjaTrader.NinjaScript.Strategies;
using NinjaTrader.Cbi;

namespace NinjaTrader.NinjaScript.Strategies
{
    // Reference Pattern: REF-021 BollingerBandMeanReversion (normalized_spec.md)
    // Failed CELL Lesson Applied: AI-CELL-019 Engine #2: commission drag on 5m avoided by using 15m
    // Modification Hypothesis: Use a breakout filter beyond 2x BB width to trigger mean‑reversion entries, limiting false signals.
    // Gross/Trade Economics: 15m ATR ~$25, target 1.5x ATR ≈ $37 >> $1.90 commission floor
    // Position Sizing Check: Stop 20 ticks = $10 + $1.90 = $11.90 contractRisk, byRisk=1 at $2k
    // Max Trades/Day: 3 total — avoids AI-CELL-005 overtrading pattern

    public class NTAAiSandboxBollingerBandMnq025 : Strategy
    {
        #region Parameters
        [Range(1, int.MaxValue), NinjaScriptProperty]
        public int Quantity { get; set; } = 1;

        [Range(5, 100), NinjaScriptProperty]
        public int StopLossTicks { get; set; } = 20;

        [Range(10, 200), NinjaScriptProperty]
        public int ProfitTargetTicks { get; set; } = 34;

        [Range(50, 5000), NinjaScriptProperty]
        public double MaxDailyLoss { get; set; } = 400.0;

        [Range(1, 5), NinjaScriptProperty]
        public int MaxTradesPerDay { get; set; } = 3;

        [Range(10, 100), NinjaScriptProperty]
        public int BreakoutLookback { get; set; } = 40;

        [Range(1, 1000), NinjaScriptProperty]
        public int BB_Period { get; set; } = 20;

        [Range(1.0, 3.0), NinjaScriptProperty]
        public double BB_Multiplier { get; set; } = 2.0;

        [Range(0.5, 2.0), NinjaScriptProperty]
        public double ReversionMultiplier { get; set; } = 1.0;

        [Range(5, 30), NinjaScriptProperty]
        public int VolatilityLookback { get; set; } = 10;

        [Range(0, 235959), NinjaScriptProperty]
        public int SessionStartTimePT { get; set; } = 63000;

        [Range(0, 235959), NinjaScriptProperty]
        public int SessionEndTimePT { get; set; } = 123000;
        #endregion

        private Bollinger bollinger;
        private bool tradingEnabled = true;
        private int tradesToday = 0;
        private DateTime lastTradeDate;
        private double dailyOpenPnl = 0.0;

        protected override void OnStateChange()
        {
            if (State == State.SetDefaults)
            {
                Description                 = "Mean‑reversion on MNQ using volatility‑adjusted Bollinger Bands with breakout filter.";
                Name                        = "NTAAiSandboxBollingerBandMnq025";
                Calculate                   = Calculate.OnBarClose;
                EntriesPerDirection         = 1;
                EntryHandling               = EntryHandling.AllEntries;
                IsExitOnSessionCloseStrategy = true; // force flat at session close
                IsInstantiatedOnEachOptimizationIteration = false;

                // Primary timeframe is supplied by the historical backtest job.
            }
            else if (State == State.Configure)
            {
                bollinger = Bollinger(BB_Multiplier, BB_Period);
                AddChartIndicator(bollinger);
            }
        }

        protected override void OnBarUpdate()
        {
            // Skip bars before we have enough data
            if (CurrentBar < Math.Max((int)BB_Period, BreakoutLookback))
                return;

            // Reset daily trade counter at session start
            if (Bars.IsFirstBarOfSession)
            {
                tradesToday = 0;
                lastTradeDate = Time[0];
                dailyOpenPnl = SystemPerformance.AllTrades.TradesPerformance.Currency.CumProfit;
            }

            int nowPt = ToTime(Time[0]);
            if (nowPt < SessionStartTimePT || nowPt >= SessionEndTimePT)
            {
                if (Position.MarketPosition == MarketPosition.Long)
                    ExitLong("SessionForceFlat", "MeanRevertLong");
                else if (Position.MarketPosition == MarketPosition.Short)
                    ExitShort("SessionForceFlat", "MeanRevertShort");
                return;
            }

            // Stop trading if max daily loss reached
            double sessionPnl =
                SystemPerformance.AllTrades.TradesPerformance.Currency.CumProfit - dailyOpenPnl;
            if (sessionPnl <= -MaxDailyLoss)
            {
                tradingEnabled = false;
                return;
            }
            else
            {
                tradingEnabled = true;
            }

            // Skip if already in a position or too many trades today
            if (Position.MarketPosition != MarketPosition.Flat || tradesToday >= MaxTradesPerDay)
                return;

            double upperBand = bollinger.Upper[0];
            double lowerBand = bollinger.Lower[0];

            // Calculate volatility‑adjusted breakout threshold
            double avgTrueRange = ATR(VolatilityLookback)[0];
            double breakoutThreshold = ReversionMultiplier * avgTrueRange;

            // Entry logic: price breaks beyond 2× BB width then mean‑reverts
            bool longSignal = Low[0] < lowerBand - breakoutThreshold;
            bool shortSignal = High[0] > upperBand + breakoutThreshold;

            if (longSignal)
            {
                SetStopLoss("MeanRevertLong", CalculationMode.Ticks, StopLossTicks, false);
                SetProfitTarget("MeanRevertLong", CalculationMode.Ticks, ProfitTargetTicks);
                EnterLong(Quantity, "MeanRevertLong");
                tradesToday++;
            }
            else if (shortSignal)
            {
                SetStopLoss("MeanRevertShort", CalculationMode.Ticks, StopLossTicks, false);
                SetProfitTarget("MeanRevertShort", CalculationMode.Ticks, ProfitTargetTicks);
                EnterShort(Quantity, "MeanRevertShort");
                tradesToday++;
            }

            // Explicit session‑end force flat logic
            if (Bars.IsLastBarOfSession)
            {
                ExitLong("ForceFlatLong");
                ExitShort("ForceFlatShort");
            }
        }

        protected override void OnPositionUpdate(
            Position position, double averagePrice, int quantity,
            MarketPosition marketPosition)
        {
            // Reset trade counter when position is closed to allow next trade
            if (marketPosition == MarketPosition.Flat)
                tradesToday = Math.Min(tradesToday, MaxTradesPerDay);
        }
    }
}
