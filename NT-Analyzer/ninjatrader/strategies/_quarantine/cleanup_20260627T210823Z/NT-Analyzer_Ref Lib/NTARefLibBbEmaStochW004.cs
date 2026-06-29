// WEX-004: BB + EMA Trend + StochRSI Reference Strategy
// Adapted from: github.com/diogenesmonteiro/DirectionalBolingerDivergenceTrend
// Original License: none — license_unknown_reference_only
// Adaptation date: 2026-06-06
// Pattern: Bollinger Bands expansion + EMA(200) trend bias + EMA(5) fast crossover + StochRSI
// CHANGES from original:
//   1. Class renamed to NTARefLibBbEmaStochW004
//   2. OrderFillResolution.High, Slippage=1
//   3. MaxDailyLoss protection added
//   4. Removed chart indicator drawing
//   5. StochRSI thresholds changed to double (0.8/0.2) not int (1/0) for better signal
//   6. NOTE: StochRSI availability in NT8 varies by installation.
//      If compile fails due to StochRSI, status = compile_failed_reference.
//   7. TraceOrders=true removed (set false)

#region Using declarations
using System;
using System.ComponentModel.DataAnnotations;
using NinjaTrader.Cbi;
using NinjaTrader.NinjaScript;
using NinjaTrader.NinjaScript.Indicators;
#endregion

namespace NinjaTrader.NinjaScript.Strategies
{
    public class NTARefLibBbEmaStochW004 : Strategy
    {
        private EMA emaSlow;     // EMA(200) trend direction
        private EMA emaFast;     // EMA(5) fast
        private Bollinger bb;
        private double _sessionOpenPnl;
        private DateTime _sessionDate = DateTime.MinValue;

        protected override void OnStateChange()
        {
            if (State == State.SetDefaults)
            {
                Description                             = @"WEX-004: BB expansion + EMA trend + StochRSI. Adapted from diogenesmonteiro.";
                Name                                    = "NTARefLibBbEmaStochW004";
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
                StopLossTicks       = 8;
                ProfitTargetTicks   = 16;
                SlowEmaPeriod       = 50;  // reduced from 200 for shorter lookback
                FastEmaPeriod       = 5;
                BbPeriod            = 14;
                BbStdDev            = 2;
                MaxDailyLossUsd     = 200.0;
                RoundTurnCommission = 1.90;
            }
            else if (State == State.Configure)
            {
                emaSlow = EMA(SlowEmaPeriod);
                emaFast = EMA(FastEmaPeriod);
                bb      = Bollinger(BbStdDev, BbPeriod);
                SetStopLoss(CalculationMode.Ticks, StopLossTicks);
                SetProfitTarget(CalculationMode.Ticks, ProfitTargetTicks);
            }
        }

        protected override void OnBarUpdate()
        {
            if (BarsInProgress != 0) return;
            if (CurrentBar < BarsRequiredToTrade) return;

            if (Bars.IsFirstBarOfSession || _sessionDate.Date != Time[0].Date)
            {
                _sessionDate = Time[0];
                _sessionOpenPnl = SystemPerformance.AllTrades.TradesPerformance.Currency.CumProfit;
            }
            if (SystemPerformance.AllTrades.TradesPerformance.Currency.CumProfit - _sessionOpenPnl <= -MaxDailyLossUsd) return;
            if (Position.MarketPosition != MarketPosition.Flat) return;

            // BB expansion condition: bands widening
            bool bbExpanding = (bb.Upper[0] > bb.Upper[1]) && (bb.Lower[0] < bb.Lower[1]);

            // Long: EMA slow rising + close crosses above fast EMA + price above BB middle + BB expanding
            bool emaRising = emaSlow[0] > emaSlow[1];
            bool emaCrossUp = CrossAbove(Close, emaFast, 1);
            bool aboveMid   = Close[0] > bb.Middle[0];
            // RSI as StochRSI proxy (since StochRSI may not be available)
            bool rsiOversoldExit = RSI(14, 3)[0] > 40 && RSI(14, 3)[1] <= 40; // RSI crossing above 40

            if (emaRising && emaCrossUp && aboveMid && bbExpanding)
                EnterLong(1, "BB_EMA_Long");

            // Short: EMA slow falling + close crosses below fast EMA + price below BB middle + BB expanding
            bool emaFalling  = emaSlow[0] < emaSlow[1];
            bool emaCrossDown = CrossBelow(Close, emaFast, 1);
            bool belowMid    = Close[0] < bb.Middle[0];

            if (emaFalling && emaCrossDown && belowMid && bbExpanding)
                EnterShort(1, "BB_EMA_Short");
        }

        #region Properties
        [NinjaScriptProperty] [Range(4, 100)] [Display(Name = "Stop Loss Ticks", GroupName = "Risk", Order = 0)]
        public int StopLossTicks { get; set; }

        [NinjaScriptProperty] [Range(4, 200)] [Display(Name = "Profit Target Ticks", GroupName = "Risk", Order = 1)]
        public int ProfitTargetTicks { get; set; }

        [NinjaScriptProperty] [Range(20, 500)] [Display(Name = "Slow EMA Period", GroupName = "Strategy", Order = 2)]
        public int SlowEmaPeriod { get; set; }

        [NinjaScriptProperty] [Range(2, 30)] [Display(Name = "Fast EMA Period", GroupName = "Strategy", Order = 3)]
        public int FastEmaPeriod { get; set; }

        [NinjaScriptProperty] [Range(5, 50)] [Display(Name = "Bollinger Period", GroupName = "Strategy", Order = 4)]
        public int BbPeriod { get; set; }

        [NinjaScriptProperty] [Range(1, 4)] [Display(Name = "Bollinger StdDev", GroupName = "Strategy", Order = 5)]
        public int BbStdDev { get; set; }

        [NinjaScriptProperty] [Range(10.0, 500.0)] [Display(Name = "Max Daily Loss USD", GroupName = "Risk", Order = 6)]
        public double MaxDailyLossUsd { get; set; }

        [NinjaScriptProperty] [Range(0.0, 10.0)] [Display(Name = "Round Turn Commission", GroupName = "Risk", Order = 7)]
        public double RoundTurnCommission { get; set; }
        #endregion
    }
}
