// WEX-006: MACD + RSI Multi-Indicator Trend Reference
// Adapted from: github.com/njmathews/AlgoTrading (MIT)
// Original file: strategy/EminiSP500Strategy.cs
// Adaptation date: 2026-06-06
// MAJOR CHANGES from original:
//   1. Class renamed to NTARefLibMacdRsiTrendW006
//   2. Fixed namespace: NinjaTrader.Custom.Strategies → NinjaTrader.NinjaScript.Strategies
//   3. Calculate.OnEachTick → Calculate.OnBarClose
//   4. REMOVED: SUPERTREND indicator (non-standard NT8 — replaced with EMA slope)
//   5. REMOVED: Bollinger().Upper (redundant), replaced BB overbought check with RSI
//   6. REMOVED: AddDataSeries(BarsPeriodType.Minute, 1) — secondary data series
//   7. REMOVED: OnRender method (drawing only)
//   8. REMOVED: dailyStats Dictionary tracking (complex state)
//   9. REMOVED: Draw.ArrowUp, Draw.Line, etc. (not needed in backtest)
//   10. SetStopLoss: CalculationMode.Price → CalculationMode.Ticks
//   11. OrderFillResolution.High, Slippage=1
//   12. MaxDailyLoss added
//   13. SIMPLIFIED: 4-indicator logic preserved (EMA + MACD + RSI for entry/exit)
// Pattern: EMA9 > EMA21 trend bias + MACD histogram positive + RSI > 50 → enter long

#region Using declarations
using System;
using System.ComponentModel.DataAnnotations;
using NinjaTrader.Cbi;
using NinjaTrader.NinjaScript;
using NinjaTrader.NinjaScript.Indicators;
#endregion

namespace NinjaTrader.NinjaScript.Strategies
{
    public class NTARefLibMacdRsiTrendW006 : Strategy
    {
        private EMA emaShort, emaLong;
        private MACD macd;
        private RSI rsi;
        private double _sessionOpenPnl;
        private DateTime _sessionDate = DateTime.MinValue;

        protected override void OnStateChange()
        {
            if (State == State.SetDefaults)
            {
                Description                             = @"WEX-006: EMA9/21 + MACD + RSI trend. Adapted from njmathews/AlgoTrading (SuperTrend replaced with EMA slope).";
                Name                                    = "NTARefLibMacdRsiTrendW006";
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
                BarsRequiredToTrade                     = 30;
                IsInstantiatedOnEachOptimizationIteration = false;
                EmaShortPeriod      = 9;
                EmaLongPeriod       = 21;
                MacdFast            = 12;
                MacdSlow            = 26;
                MacdSignal          = 9;
                RsiPeriod           = 14;
                RsiSmoothing        = 3;
                StopLossTicks       = 20;
                ProfitTargetTicks   = 40;
                MaxDailyLossUsd     = 300.0;
                RoundTurnCommission = 1.90;
            }
            else if (State == State.Configure)
            {
                emaShort = EMA(EmaShortPeriod);
                emaLong  = EMA(EmaLongPeriod);
                macd     = MACD(MacdFast, MacdSlow, MacdSignal);
                rsi      = RSI(RsiPeriod, RsiSmoothing);
                // SUPERTREND replaced: use EMA slope as trend proxy
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

            // ENTRY LOGIC (from original, SuperTrend replaced with EMA slope)
            // Original: emaShort > emaLong && macd.Diff[0] > 0 && rsi[0] > 50 && superTrend[0] > Close[0]
            // Adaptation: emaShort > emaLong && macd.Diff[0] > 0 && rsi[0] > 50 && emaLong rising
            bool isBullishTrend = emaShort[0] > emaLong[0]
                                && macd.Diff[0] > 0
                                && rsi[0] > 50
                                && emaLong[0] > emaLong[2];  // EMA long rising = SuperTrend proxy

            // OVERBOUGHT check (from original Bollinger.Upper → simplified to RSI > 65)
            bool isBearishReversal = rsi[0] > 65;

            // TREND SHIFT negative (from original)
            bool isTrendShiftNegative = emaShort[0] < emaLong[0] && macd.Diff[0] < 0;

            if (Position.MarketPosition == MarketPosition.Flat)
            {
                if (isBullishTrend)
                    EnterLong(1, "MACD_RSI_Long");
            }
            else if (Position.MarketPosition == MarketPosition.Long)
            {
                if (isBearishReversal || isTrendShiftNegative)
                    ExitLong("MACD_RSI_Exit", "MACD_RSI_Long");
            }
        }

        #region Properties
        [NinjaScriptProperty] [Range(2, 30)] [Display(Name = "EMA Short Period", GroupName = "Strategy", Order = 0)]
        public int EmaShortPeriod { get; set; }

        [NinjaScriptProperty] [Range(5, 100)] [Display(Name = "EMA Long Period", GroupName = "Strategy", Order = 1)]
        public int EmaLongPeriod { get; set; }

        [NinjaScriptProperty] [Range(2, 30)] [Display(Name = "MACD Fast Period", GroupName = "Strategy", Order = 2)]
        public int MacdFast { get; set; }

        [NinjaScriptProperty] [Range(5, 50)] [Display(Name = "MACD Slow Period", GroupName = "Strategy", Order = 3)]
        public int MacdSlow { get; set; }

        [NinjaScriptProperty] [Range(2, 20)] [Display(Name = "MACD Signal Period", GroupName = "Strategy", Order = 4)]
        public int MacdSignal { get; set; }

        [NinjaScriptProperty] [Range(2, 30)] [Display(Name = "RSI Period", GroupName = "Strategy", Order = 5)]
        public int RsiPeriod { get; set; }

        [NinjaScriptProperty] [Range(1, 10)] [Display(Name = "RSI Smoothing", GroupName = "Strategy", Order = 6)]
        public int RsiSmoothing { get; set; }

        [NinjaScriptProperty] [Range(4, 100)] [Display(Name = "Stop Loss Ticks", GroupName = "Risk", Order = 7)]
        public int StopLossTicks { get; set; }

        [NinjaScriptProperty] [Range(4, 200)] [Display(Name = "Profit Target Ticks", GroupName = "Risk", Order = 8)]
        public int ProfitTargetTicks { get; set; }

        [NinjaScriptProperty] [Range(10.0, 500.0)] [Display(Name = "Max Daily Loss USD", GroupName = "Risk", Order = 9)]
        public double MaxDailyLossUsd { get; set; }

        [NinjaScriptProperty] [Range(0.0, 10.0)] [Display(Name = "Round Turn Commission", GroupName = "Risk", Order = 10)]
        public double RoundTurnCommission { get; set; }
        #endregion
    }
}
