// WEX-001: SMA Crossover Reference Strategy
// Adapted from: github.com/kodalli/NT8-PAT-Strategy/SimpleMovingAverageCrossover.cs
// Original License: MIT
// Adaptation date: 2026-06-06
// Changes from original:
//   1. Class renamed to NTARefLibSmaCrossoverW001
//   2. SetStopLoss: CalculationMode.Currency → CalculationMode.Ticks (16 ticks)
//   3. SetProfitTarget: CalculationMode.Currency → CalculationMode.Ticks (24 ticks)
//   4. OrderFillResolution.Standard → OrderFillResolution.High
//   5. Slippage: 0 → 1
//   6. RoundTurnCommission property added (1.90)
//   7. Removed AddChartIndicator calls (not needed in backtest)
//   8. MaxDailyLoss tracking added (minimal safe shell)
// Pattern: SMA 9/21 Crossover — long on golden cross, short on death cross
// Safety: no ATM, no live account API, no file IO, no network

#region Using declarations
using System;
using System.ComponentModel.DataAnnotations;
using NinjaTrader.Cbi;
using NinjaTrader.NinjaScript;
using NinjaTrader.NinjaScript.Indicators;
#endregion

namespace NinjaTrader.NinjaScript.Strategies
{
    public class NTARefLibSmaCrossoverW001 : Strategy
    {
        private SMA fastSMA, slowSMA;
        private double _sessionOpenPnl;
        private DateTime _sessionDate = DateTime.MinValue;

        protected override void OnStateChange()
        {
            if (State == State.SetDefaults)
            {
                Description                             = @"WEX-001: SMA 9/21 crossover reference. Long on golden cross, short on death cross.";
                Name                                    = "NTARefLibSmaCrossoverW001";
                Calculate                               = Calculate.OnBarClose;
                EntriesPerDirection                     = 1;
                EntryHandling                           = EntryHandling.AllEntries;
                IsExitOnSessionCloseStrategy            = true;
                ExitOnSessionCloseSeconds               = 30;
                IsFillLimitOnTouch                      = false;
                MaximumBarsLookBack                     = MaximumBarsLookBack.TwoHundredFiftySix;
                OrderFillResolution                     = OrderFillResolution.High;
                Slippage                                = 1;
                StartBehavior                           = StartBehavior.WaitUntilFlat;
                TimeInForce                             = TimeInForce.Gtc;
                TraceOrders                             = false;
                RealtimeErrorHandling                   = RealtimeErrorHandling.StopCancelClose;
                StopTargetHandling                      = StopTargetHandling.PerEntryExecution;
                BarsRequiredToTrade                     = 25;
                IsInstantiatedOnEachOptimizationIteration = false;
                // Strategy parameters
                FastPeriod          = 9;
                SlowPeriod          = 21;
                StopLossTicks       = 16;
                ProfitTargetTicks   = 24;
                MaxDailyLossUsd     = 200.0;
                RoundTurnCommission = 1.90;
            }
            else if (State == State.Configure)
            {
                fastSMA = SMA(FastPeriod);
                slowSMA = SMA(SlowPeriod);
                SetStopLoss(CalculationMode.Ticks, StopLossTicks);
                SetProfitTarget(CalculationMode.Ticks, ProfitTargetTicks);
            }
        }

        protected override void OnBarUpdate()
        {
            if (BarsInProgress != 0) return;
            if (CurrentBar < BarsRequiredToTrade) return;

            // Session daily loss guard
            if (Bars.IsFirstBarOfSession || _sessionDate.Date != Time[0].Date)
            {
                _sessionDate = Time[0];
                _sessionOpenPnl = SystemPerformance.AllTrades.TradesPerformance.Currency.CumProfit;
            }
            double sessionPnl = SystemPerformance.AllTrades.TradesPerformance.Currency.CumProfit - _sessionOpenPnl;
            if (sessionPnl <= -MaxDailyLossUsd) return;

            // SMA crossover entries
            if (CrossAbove(fastSMA, slowSMA, 1) && Position.MarketPosition == MarketPosition.Flat)
                EnterLong(1, "SMA_Long");
            else if (CrossBelow(fastSMA, slowSMA, 1) && Position.MarketPosition == MarketPosition.Flat)
                EnterShort(1, "SMA_Short");

            // SMA crossover exits
            if (Position.MarketPosition == MarketPosition.Long && CrossBelow(fastSMA, slowSMA, 1))
                ExitLong("SMA_ExitLong", "SMA_Long");
            else if (Position.MarketPosition == MarketPosition.Short && CrossAbove(fastSMA, slowSMA, 1))
                ExitShort("SMA_ExitShort", "SMA_Short");
        }

        #region Properties
        [NinjaScriptProperty]
        [Range(2, 50)]
        [Display(Name = "Fast SMA Period", GroupName = "Strategy", Order = 0)]
        public int FastPeriod { get; set; }

        [NinjaScriptProperty]
        [Range(5, 100)]
        [Display(Name = "Slow SMA Period", GroupName = "Strategy", Order = 1)]
        public int SlowPeriod { get; set; }

        [NinjaScriptProperty]
        [Range(4, 100)]
        [Display(Name = "Stop Loss Ticks", GroupName = "Risk", Order = 2)]
        public int StopLossTicks { get; set; }

        [NinjaScriptProperty]
        [Range(4, 200)]
        [Display(Name = "Profit Target Ticks", GroupName = "Risk", Order = 3)]
        public int ProfitTargetTicks { get; set; }

        [NinjaScriptProperty]
        [Range(10.0, 500.0)]
        [Display(Name = "Max Daily Loss USD", GroupName = "Risk", Order = 4)]
        public double MaxDailyLossUsd { get; set; }

        [NinjaScriptProperty]
        [Range(0.0, 10.0)]
        [Display(Name = "Round Turn Commission", GroupName = "Risk", Order = 5)]
        public double RoundTurnCommission { get; set; }
        #endregion
    }
}
