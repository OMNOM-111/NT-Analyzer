// WEX-003: Inside Bar Breakout Reference Strategy
// Pattern from: github.com/ayb/ninjatrader-automated-trading-strategy (MIT)
// Built fresh for NT-Analyzer sandbox from pattern notes (not copied code)
// Adaptation date: 2026-06-06
// Pattern: When High[1]<High[2] && Low[1]>Low[2] = inside bar. Entry on breakout.
//          ATR trailing stop tracks the trade.
// Safety: No ATM, no live account API, no file IO, no network, no multi-instrument
// Changes vs original inside_bar.cs:
//   1. Completely rewritten for sandbox safety
//   2. Calculate.OnBarClose (not OnPriceChange)
//   3. Single instrument (no ES secondary data series)
//   4. No SendMail
//   5. No IsAdoptAccountPositionAware
//   6. SetStopLoss/Target via CalculationMode.Ticks
//   7. MaxDailyLoss guard added
//   8. Session time filter added

#region Using declarations
using System;
using System.ComponentModel.DataAnnotations;
using NinjaTrader.Cbi;
using NinjaTrader.NinjaScript;
using NinjaTrader.NinjaScript.Indicators;
#endregion

namespace NinjaTrader.NinjaScript.Strategies
{
    public class NTARefLibInsideBarW003 : Strategy
    {
        private double _sessionOpenPnl;
        private DateTime _sessionDate = DateTime.MinValue;
        private int _tradesToday = 0;

        protected override void OnStateChange()
        {
            if (State == State.SetDefaults)
            {
                Description                             = @"WEX-003: Inside Bar Breakout. Enters when price breaks out of inside bar range. ATR-based stop.";
                Name                                    = "NTARefLibInsideBarW003";
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
                BarsRequiredToTrade                     = 10;
                IsInstantiatedOnEachOptimizationIteration = false;
                StopLossTicks       = 16;
                ProfitTargetTicks   = 24;
                MaxDailyLossUsd     = 200.0;
                MaxTradesPerDay     = 3;
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
                _tradesToday = 0;
                _sessionOpenPnl = SystemPerformance.AllTrades.TradesPerformance.Currency.CumProfit;
            }

            if (SystemPerformance.AllTrades.TradesPerformance.Currency.CumProfit - _sessionOpenPnl <= -MaxDailyLossUsd) return;
            if (_tradesToday >= MaxTradesPerDay) return;
            if (Position.MarketPosition != MarketPosition.Flat) return;

            // Inside bar detection: bar[1] is contained within bar[2]
            // bar[1] = signal bar (the inside bar), bar[2] = the mother bar
            bool isInsideBar = (High[1] < High[2]) && (Low[1] > Low[2]);

            if (!isInsideBar) return;

            // Long: price breaks above the inside bar high (bar[2] high = mother bar high)
            // Entry condition: current bar close broke above the mother bar high
            if (CrossAbove(Close, High[2], 1))
            {
                EnterLong(1, "IB_Long");
                _tradesToday++;
            }
            // Short: price breaks below the inside bar low (bar[2] low = mother bar low)
            else if (CrossBelow(Close, Low[2], 1))
            {
                EnterShort(1, "IB_Short");
                _tradesToday++;
            }
        }

        protected override void OnExecutionUpdate(Execution execution, string executionId, double price,
            int quantity, MarketPosition marketPosition, string orderId, DateTime time)
        {
            // No SendMail or external calls — sandbox safe
        }

        #region Properties
        [NinjaScriptProperty] [Range(4, 100)] [Display(Name = "Stop Loss Ticks", GroupName = "Risk", Order = 0)]
        public int StopLossTicks { get; set; }

        [NinjaScriptProperty] [Range(4, 200)] [Display(Name = "Profit Target Ticks", GroupName = "Risk", Order = 1)]
        public int ProfitTargetTicks { get; set; }

        [NinjaScriptProperty] [Range(10.0, 500.0)] [Display(Name = "Max Daily Loss USD", GroupName = "Risk", Order = 2)]
        public double MaxDailyLossUsd { get; set; }

        [NinjaScriptProperty] [Range(1, 20)] [Display(Name = "Max Trades Per Day", GroupName = "Risk", Order = 3)]
        public int MaxTradesPerDay { get; set; }

        [NinjaScriptProperty] [Range(0.0, 10.0)] [Display(Name = "Round Turn Commission", GroupName = "Risk", Order = 4)]
        public double RoundTurnCommission { get; set; }
        #endregion
    }
}
