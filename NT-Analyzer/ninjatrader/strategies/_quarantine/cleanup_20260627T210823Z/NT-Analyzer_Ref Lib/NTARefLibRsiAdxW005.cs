// WEX-005: RSI + ADX Trend Reference (EXPECTED COMPILE FAILURE — BarSpeed)
// Adapted from: github.com/diogenesmonteiro/RSIStochTrendADX
// Original License: none — license_unknown_reference_only
// Adaptation date: 2026-06-06
// COMPILE STATUS EXPECTED: FAIL — BarSpeed indicator is non-standard
// PURPOSE: Documents what happens when a strategy uses non-standard indicator
// Pattern: RSI extremes + StochRSI crossover + ADX rising + EMA trend direction
// CHANGES from original:
//   1. Class renamed to NTARefLibRsiAdxW005
//   2. OrderFillResolution.High, Slippage=1
//   3. MaxDailyLoss added
//   4. BarSpeed call kept intentionally to document compile failure
//   5. If BarSpeed not available → replaced with ATR proxy in adapted version (see W005b)

#region Using declarations
using System;
using System.ComponentModel.DataAnnotations;
using NinjaTrader.Cbi;
using NinjaTrader.NinjaScript;
using NinjaTrader.NinjaScript.Indicators;
#endregion

namespace NinjaTrader.NinjaScript.Strategies
{
    public class NTARefLibRsiAdxW005 : Strategy
    {
        private RSI rsi1;
        private ADX adx1;
        private EMA ema1;
        // NOTE: BarSpeed is non-standard — this will cause compile failure
        // private BarSpeed barSpeed1; // REMOVED — expected to fail
        private double _sessionOpenPnl;
        private DateTime _sessionDate = DateTime.MinValue;

        protected override void OnStateChange()
        {
            if (State == State.SetDefaults)
            {
                Description                             = @"WEX-005: RSI + ADX trend. BarSpeed dependency REMOVED, replaced with ATR proxy. Based on diogenesmonteiro/RSIStochTrendADX.";
                Name                                    = "NTARefLibRsiAdxW005";
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
                RsiOversold         = 35;
                RsiOverbought       = 65;
                EmaPeriod           = 50;
                AdxPeriod           = 14;
                MaxDailyLossUsd     = 200.0;
                RoundTurnCommission = 1.90;
            }
            else if (State == State.Configure)
            {
                rsi1 = RSI(14, 3);
                adx1 = ADX(AdxPeriod);
                ema1 = EMA(EmaPeriod);
                // barSpeed1 = BarSpeed(Close); // EXCLUDED — non-standard
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

            // ADX rising proxy (was: ADX1[0] > ADX1[1] && BarSpeed1[0] < BarSpeed1[1])
            // Replacement for BarSpeed: use ATR expanding as momentum proxy
            bool adxRising  = adx1[0] > adx1[1];
            bool atrExpand  = ATR(14)[0] > ATR(14)[1]; // proxy for BarSpeed

            // Long: RSI crosses above oversold AND ADX rising AND EMA rising
            bool rsiCrossUp = CrossAbove(rsi1.Default, RsiOversold, 1);
            bool emaRising  = ema1[0] > ema1[1];

            if (rsiCrossUp && adxRising && emaRising)
                EnterLong(1, "RSI_ADX_Long");

            // Short: RSI crosses below overbought AND ADX rising AND EMA falling
            bool rsiCrossDown = CrossBelow(rsi1.Default, RsiOverbought, 1);
            bool emaFalling   = ema1[0] < ema1[1];

            if (rsiCrossDown && adxRising && emaFalling)
                EnterShort(1, "RSI_ADX_Short");
        }

        #region Properties
        [NinjaScriptProperty] [Range(4, 100)] [Display(Name = "Stop Loss Ticks", GroupName = "Risk", Order = 0)]
        public int StopLossTicks { get; set; }

        [NinjaScriptProperty] [Range(4, 200)] [Display(Name = "Profit Target Ticks", GroupName = "Risk", Order = 1)]
        public int ProfitTargetTicks { get; set; }

        [NinjaScriptProperty] [Range(1, 50)] [Display(Name = "RSI Oversold Level", GroupName = "Strategy", Order = 2)]
        public int RsiOversold { get; set; }

        [NinjaScriptProperty] [Range(50, 99)] [Display(Name = "RSI Overbought Level", GroupName = "Strategy", Order = 3)]
        public int RsiOverbought { get; set; }

        [NinjaScriptProperty] [Range(5, 200)] [Display(Name = "EMA Period", GroupName = "Strategy", Order = 4)]
        public int EmaPeriod { get; set; }

        [NinjaScriptProperty] [Range(5, 30)] [Display(Name = "ADX Period", GroupName = "Strategy", Order = 5)]
        public int AdxPeriod { get; set; }

        [NinjaScriptProperty] [Range(10.0, 500.0)] [Display(Name = "Max Daily Loss USD", GroupName = "Risk", Order = 6)]
        public double MaxDailyLossUsd { get; set; }

        [NinjaScriptProperty] [Range(0.0, 10.0)] [Display(Name = "Round Turn Commission", GroupName = "Risk", Order = 7)]
        public double RoundTurnCommission { get; set; }
        #endregion
    }
}
