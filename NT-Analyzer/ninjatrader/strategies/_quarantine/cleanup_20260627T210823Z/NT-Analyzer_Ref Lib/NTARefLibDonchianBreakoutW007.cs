// WEX-007: Donchian Breakout (Turtle-style) Reference Strategy
// Pattern: Classic Donchian Channel breakout — enter on N-bar high/low break
// Source: Public domain concept (Richard Donchian / Turtle Trading)
// Built fresh for NT-Analyzer sandbox
// Adaptation date: 2026-06-06
// Safety: No ATM, no live account API, clean NT8 OnBarClose

#region Using declarations
using System;
using System.ComponentModel.DataAnnotations;
using NinjaTrader.Cbi;
using NinjaTrader.NinjaScript;
using NinjaTrader.NinjaScript.Indicators;
#endregion

namespace NinjaTrader.NinjaScript.Strategies
{
    public class NTARefLibDonchianBreakoutW007 : Strategy
    {
        private double _sessionOpenPnl;
        private DateTime _sessionDate = DateTime.MinValue;
        private int _tradesToday = 0;

        protected override void OnStateChange()
        {
            if (State == State.SetDefaults)
            {
                Description                             = @"WEX-007: Donchian N-bar high/low breakout. Long on new N-bar high, short on new N-bar low. ATR stop.";
                Name                                    = "NTARefLibDonchianBreakoutW007";
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
                BreakoutPeriod      = 20;
                ExitPeriod          = 10;
                AtrPeriod           = 14;
                AtrStopMult         = 2.0;
                MaxStopTicks        = 30;
                MaxDailyLossUsd     = 300.0;
                MaxTradesPerDay     = 2;
                RoundTurnCommission = 1.90;
            }
            else if (State == State.Configure)
            {
                // ATR-based stop set dynamically in OnBarUpdate
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

            double atr = ATR(AtrPeriod)[0];
            int dynamicStop = (int)Math.Min(MaxStopTicks, Math.Max(8, atr * AtrStopMult / TickSize));

            // Donchian channel: N-bar highest high and lowest low (exclude current bar)
            double donchianHigh = MAX(High, BreakoutPeriod)[1]; // [1] = prior bar so we don't count current
            double donchianLow  = MIN(Low,  BreakoutPeriod)[1];

            // Exit channel (shorter period)
            double exitHigh = MAX(High, ExitPeriod)[1];
            double exitLow  = MIN(Low,  ExitPeriod)[1];

            if (Position.MarketPosition == MarketPosition.Flat)
            {
                // Long: new N-bar high breakout
                if (Close[0] > donchianHigh)
                {
                    SetStopLoss(CalculationMode.Ticks, dynamicStop);
                    SetProfitTarget(CalculationMode.Ticks, dynamicStop * 2);
                    EnterLong(1, "Donchian_Long");
                    _tradesToday++;
                }
                // Short: new N-bar low breakout
                else if (Close[0] < donchianLow)
                {
                    SetStopLoss(CalculationMode.Ticks, dynamicStop);
                    SetProfitTarget(CalculationMode.Ticks, dynamicStop * 2);
                    EnterShort(1, "Donchian_Short");
                    _tradesToday++;
                }
            }
            else if (Position.MarketPosition == MarketPosition.Long)
            {
                // Exit long: new N/2-bar low
                if (Close[0] < exitLow)
                    ExitLong("Donchian_ExitLong", "Donchian_Long");
            }
            else if (Position.MarketPosition == MarketPosition.Short)
            {
                // Exit short: new N/2-bar high
                if (Close[0] > exitHigh)
                    ExitShort("Donchian_ExitShort", "Donchian_Short");
            }
        }

        #region Properties
        [NinjaScriptProperty] [Range(5, 100)] [Display(Name = "Breakout Period (N bars)", GroupName = "Strategy", Order = 0)]
        public int BreakoutPeriod { get; set; }

        [NinjaScriptProperty] [Range(3, 50)] [Display(Name = "Exit Period (N/2 bars)", GroupName = "Strategy", Order = 1)]
        public int ExitPeriod { get; set; }

        [NinjaScriptProperty] [Range(5, 30)] [Display(Name = "ATR Period", GroupName = "Strategy", Order = 2)]
        public int AtrPeriod { get; set; }

        [NinjaScriptProperty] [Range(0.5, 5.0)] [Display(Name = "ATR Stop Multiplier", GroupName = "Strategy", Order = 3)]
        public double AtrStopMult { get; set; }

        [NinjaScriptProperty] [Range(8, 100)] [Display(Name = "Max Stop Ticks", GroupName = "Risk", Order = 4)]
        public int MaxStopTicks { get; set; }

        [NinjaScriptProperty] [Range(10.0, 500.0)] [Display(Name = "Max Daily Loss USD", GroupName = "Risk", Order = 5)]
        public double MaxDailyLossUsd { get; set; }

        [NinjaScriptProperty] [Range(1, 10)] [Display(Name = "Max Trades Per Day", GroupName = "Risk", Order = 6)]
        public int MaxTradesPerDay { get; set; }

        [NinjaScriptProperty] [Range(0.0, 10.0)] [Display(Name = "Round Turn Commission", GroupName = "Risk", Order = 7)]
        public double RoundTurnCommission { get; set; }
        #endregion
    }
}
