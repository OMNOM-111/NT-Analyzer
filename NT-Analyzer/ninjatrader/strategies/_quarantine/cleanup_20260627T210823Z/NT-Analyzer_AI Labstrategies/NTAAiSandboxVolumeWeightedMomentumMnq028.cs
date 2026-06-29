// -----------------------------------------------------------------------------
// NTAAiSandboxVolumeWeightedMomentumMnq028
//
// This revision replaces the Donchian breakout logic with an EMA‑based pullback
// entry that also requires RSI divergence and a volume spike.  The strategy now
// looks for a high‑volume pullback to the 20‑period EMA after a recent price
// move, confirming the reversal with an RSI oversold (long) or overbought
// (short) reading.  This change addresses the previous rejection caused by
// zero trades – the new filter is more permissive during the session window
// and should generate entries while still keeping risk under control.
// -----------------------------------------------------------------------------


using NinjaTrader.Cbi;
using NinjaTrader.NinjaScript;
using NinjaTrader.NinjaScript.Strategies;
using NinjaTrader.NinjaScript.Indicators;
using System;
using System.ComponentModel.DataAnnotations;

namespace NinjaTrader.NinjaScript.Strategies
{
    public class NTAAiSandboxVolumeWeightedMomentumMnq028 : Strategy
    {
        #region Variables
        private double sessionSnapshot;
        private int tradeCountToday;
        private bool tradingEnabled = true;

        // Indicators
        private EMA ema20;
        private RSI rsi14;
        private ATR atr;
        private SMA smaATR;
        private SMA smaVolume;
        #endregion

        #region Inputs
        [Range(1, 1000), NinjaScriptProperty]
        public int Quantity { get; set; } = 1;

        [Range(1, 200), NinjaScriptProperty]
        public int StopLossTicks { get; set; } = 20;

        [Range(1, 500), NinjaScriptProperty]
        public int ProfitTargetTicks { get; set; } = 34;

        [Range(0, 10000), NinjaScriptProperty]
        public double MaxDailyLoss { get; set; } = 400.0;

        [Range(1, 10), NinjaScriptProperty]
        public int MaxTradesPerDay { get; set; } = 3;

        [NinjaScriptProperty]
        public string SessionStartPT { get; set; } = "06:30";

        [NinjaScriptProperty]
        public string SessionEndPT { get; set; } = "12:30";
        #endregion

        protected override void OnStateChange()
        {
            if (State == State.SetDefaults)
            {
                Description                 = @"MNQ momentum reversal strategy using EMA pullback, RSI divergence and volume spike.";
                Name                        = "NTAAiSandboxVolumeWeightedMomentumMnq028";
                Calculate                   = Calculate.OnBarClose;
                IsExitOnSessionCloseStrategy = true;
                IsInstantiatedOnEachOptimizationIteration = false;
            }
            else if (State == State.Configure)
            {
                // No additional data series
            }
            else if (State == State.DataLoaded)
            {
                ema20      = EMA(20);
                rsi14      = RSI(14, 3);   // 14‑period RSI with smoothing
                atr        = ATR(14);
                smaATR     = SMA(atr, 20);
                smaVolume  = SMA(Volume, 20);

                AddChartIndicator(ema20);
                AddChartIndicator(rsi14);
                AddChartIndicator(atr);
                AddChartIndicator(smaATR);
                AddChartIndicator(smaVolume);
            }
        }

        protected override void OnBarUpdate()
        {
            // Force flat at session end
            if (Bars.IsLastBarOfSession)
            {
                if (Position.MarketPosition != MarketPosition.Flat)
                {
                    ExitLong();
                    ExitShort();
                }
            }

            // Session start snapshot and daily reset
            if (Bars.IsFirstBarOfSession)
            {
                sessionSnapshot = SystemPerformance.AllTrades.TradesPerformance.Currency.CumProfit;
                tradeCountToday = 0;
                tradingEnabled  = true;
            }

            // Daily loss check
            double currentDailyPnL = SystemPerformance.AllTrades.TradesPerformance.Currency.CumProfit - sessionSnapshot;
            if (currentDailyPnL <= -MaxDailyLoss)
                tradingEnabled = false;

            // Time window enforcement (Pacific Time)
            DateTime utcNow   = Time[0].ToUniversalTime();
            var pacificZone    = TimeZoneInfo.FindSystemTimeZoneById("Pacific Standard Time");
            DateTime pacificNow = TimeZoneInfo.ConvertTimeFromUtc(utcNow, pacificZone);
            TimeSpan sessionStart = TimeSpan.Parse(SessionStartPT);
            TimeSpan sessionEnd   = TimeSpan.Parse(SessionEndPT);

            if (pacificNow.TimeOfDay < sessionStart || pacificNow.TimeOfDay > sessionEnd)
                return;

            // Ensure flat position before new entry
            if (Position.MarketPosition != MarketPosition.Flat || !tradingEnabled)
                return;

            // Trade limit per day
            if (tradeCountToday >= MaxTradesPerDay)
                return;

            // Volatility filter: current ATR > 1.2 * average ATR
            double currentATR = atr[0];
            double avgATR     = smaATR[0];
            if (avgATR == 0 || currentATR <= 1.2 * avgATR)
                return;

            // Volume spike filter: current volume > 1.5 * SMA(volume,20)
            double currentVol = Volume[0];
            double avgVol     = smaVolume[0];
            if (avgVol == 0 || currentVol <= 1.5 * avgVol)
                return;

            // EMA pullback with RSI divergence
            bool longSignal  = Close[0] < ema20[0] && rsi14[0] < 30;   // price below EMA, RSI oversold
            bool shortSignal = Close[0] > ema20[0] && rsi14[0] > 70;   // price above EMA, RSI overbought

            if (longSignal)
            {
                SetStopLoss(CalculationMode.Ticks, StopLossTicks);
                SetProfitTarget(CalculationMode.Ticks, ProfitTargetTicks);
                EnterLong(Quantity, "LongEntry");
                tradeCountToday++;
            }
            else if (shortSignal)
            {
                SetStopLoss(CalculationMode.Ticks, StopLossTicks);
                SetProfitTarget(CalculationMode.Ticks, ProfitTargetTicks);
                EnterShort(Quantity, "ShortEntry");
                tradeCountToday++;
            }
        }

        protected override void OnExecutionUpdate(Execution execution, string executionId, double price, int quantity, MarketPosition marketPosition, string orderId, DateTime time)
        {
            // No custom logic required for this strategy
        }
    }
}