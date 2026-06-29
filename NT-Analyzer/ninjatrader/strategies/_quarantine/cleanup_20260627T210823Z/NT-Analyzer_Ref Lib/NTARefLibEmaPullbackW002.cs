// WEX-002: EMA Trend Pullback Scalping Reference
// Adapted from: github.com/kodalli/NT8-PAT-Strategy/futurePullbackScalping.cs
// Original License: MIT
// Adaptation date: 2026-06-06
// Changes from original:
//   1. Class renamed to NTARefLibEmaPullbackW002
//   2. REMOVED: AddDataSeries("ES 06-20", ...) — removed multi-instrument dependency
//      WARNING: original uses ES tick data for signal; adapted version uses primary instrument only
//   3. OrderFillResolution.Standard → OrderFillResolution.High
//   4. Slippage: 0 → 1
//   5. MaxDailyLoss tracking added
//   6. Short logic added (original was long-only)
//   7. BullishThreshhold renamed to BullishThreshold (spelling fix)
//   8. Removed commented-out code blocks
// Pattern: SMA trend + EMA21 pullback entry (long when pullback to EMA21 in uptrend)
// NOTE: This is an ADAPTATION. Original used secondary ES data series for signal confirmation.
//       This simplified version uses primary instrument bars only.

#region Using declarations
using System;
using System.ComponentModel.DataAnnotations;
using NinjaTrader.Cbi;
using NinjaTrader.NinjaScript;
using NinjaTrader.NinjaScript.Indicators;
#endregion

namespace NinjaTrader.NinjaScript.Strategies
{
    public class NTARefLibEmaPullbackW002 : Strategy
    {
        private double _sessionOpenPnl;
        private DateTime _sessionDate = DateTime.MinValue;

        protected override void OnStateChange()
        {
            if (State == State.SetDefaults)
            {
                Description                             = @"WEX-002: EMA21 pullback in SMA trend. Adapted from kodalli/NT8-PAT-Strategy.";
                Name                                    = "NTARefLibEmaPullbackW002";
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
                BarsRequiredToTrade                     = 50;
                IsInstantiatedOnEachOptimizationIteration = false;
                StopLossTicks       = 8;
                ProfitTargetTicks   = 16;
                FastPeriod          = 5;
                SlowPeriod          = 20;
                EmaPeriod           = 21;
                TicksForPullback    = 2;
                MaxDailyLossUsd     = 200.0;
                RoundTurnCommission = 1.90;
            }
            else if (State == State.Configure)
            {
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

            bool inUptrend = SMA(FastPeriod)[0] > SMA(SlowPeriod)[0];
            bool inDowntrend = SMA(FastPeriod)[0] < SMA(SlowPeriod)[0];

            // Long: uptrend AND price pulled back below EMA21 by at least TicksForPullback
            if (inUptrend)
            {
                double ema = EMA(EmaPeriod)[0];
                bool pullbackToEma = (ema - Close[0]) >= TicksForPullback * TickSize;
                bool bullishBar = (Close[1] - Open[1]) >= 0; // previous bar closed up
                if (pullbackToEma && bullishBar)
                    EnterLong(1, "EMA_Pull_Long");
            }

            // Short: downtrend AND price pulled back above EMA21 by at least TicksForPullback
            if (inDowntrend)
            {
                double ema = EMA(EmaPeriod)[0];
                bool pullbackToEma = (Close[0] - ema) >= TicksForPullback * TickSize;
                bool bearishBar = (Open[1] - Close[1]) >= 0; // previous bar closed down
                if (pullbackToEma && bearishBar)
                    EnterShort(1, "EMA_Pull_Short");
            }
        }

        #region Properties
        [NinjaScriptProperty] [Range(4, 100)] [Display(Name = "Stop Loss Ticks", GroupName = "Risk", Order = 0)]
        public int StopLossTicks { get; set; }

        [NinjaScriptProperty] [Range(4, 200)] [Display(Name = "Profit Target Ticks", GroupName = "Risk", Order = 1)]
        public int ProfitTargetTicks { get; set; }

        [NinjaScriptProperty] [Range(2, 50)] [Display(Name = "Fast SMA Period", GroupName = "Strategy", Order = 2)]
        public int FastPeriod { get; set; }

        [NinjaScriptProperty] [Range(5, 100)] [Display(Name = "Slow SMA Period", GroupName = "Strategy", Order = 3)]
        public int SlowPeriod { get; set; }

        [NinjaScriptProperty] [Range(5, 50)] [Display(Name = "EMA Period for Pullback", GroupName = "Strategy", Order = 4)]
        public int EmaPeriod { get; set; }

        [NinjaScriptProperty] [Range(1, 20)] [Display(Name = "Ticks For Pullback Confirmation", GroupName = "Strategy", Order = 5)]
        public int TicksForPullback { get; set; }

        [NinjaScriptProperty] [Range(10.0, 500.0)] [Display(Name = "Max Daily Loss USD", GroupName = "Risk", Order = 6)]
        public double MaxDailyLossUsd { get; set; }

        [NinjaScriptProperty] [Range(0.0, 10.0)] [Display(Name = "Round Turn Commission", GroupName = "Risk", Order = 7)]
        public double RoundTurnCommission { get; set; }
        #endregion
    }
}
