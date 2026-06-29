using System;
using System.ComponentModel.DataAnnotations;
using NinjaTrader.Cbi;
using NinjaTrader.NinjaScript;
using NinjaTrader.NinjaScript.Strategies;

namespace NinjaTrader.NinjaScript.Strategies
{
    public class NTAAiSandboxVolatilityMnq011 : Strategy
    {
        // --------------------------------------------------------------------
        // User inputs (exposed to the UI)
        // --------------------------------------------------------------------

        [NinjaScriptProperty]
        [Range(1, int.MaxValue), Display(Name = "Quantity", Order = 0)]
        public int Quantity { get; set; }

        [NinjaScriptProperty]
        [Range(1, 1000), Display(Name = "Stop Loss (Ticks)", Order = 1)]
        public int StopLossTicks { get; set; }

        [NinjaScriptProperty]
        [Range(1, 2000), Display(Name = "Profit Target (Ticks)", Order = 2)]
        public int ProfitTargetTicks { get; set; }

        [NinjaScriptProperty]
        [Range(10, 10000), Display(Name = "Max Daily Loss", Order = 3)]
        public double MaxDailyLoss { get; set; }

        [NinjaScriptProperty]
        [Range(1, 200), Display(Name = "Breakout Lookback Bars", Order = 4)]
        public int BreakoutLookback { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "Session Start (PT)", Order = 5)]
        public string SessionStartPT { get; set; } // e.g., "06:30"

        [NinjaScriptProperty]
        [Display(Name = "Session End (PT)", Order = 6)]
        public string SessionEndPT { get; set; }   // e.g., "12:30"

        [NinjaScriptProperty]
        [Display(Name = "Trade Start Time (PT)", Order = 7)]
        public string TradeStartTimePT { get; set; } // e.g., "13:00"

        [NinjaScriptProperty]
        [Display(Name = "Trade End Time (PT)", Order = 8)]
        public string TradeEndTimePT { get; set; }   // e.g., "16:00"

        [NinjaScriptProperty]
        [Display(Name = "News Event Type", Order = 9)]
        public string NewsEventType { get; set; }

        [NinjaScriptProperty]
        [Range(1, int.MaxValue), Display(Name = "Max Trades Per Day", Order = 10)]
        public int MaxTradesPerDay { get; set; }

        // --------------------------------------------------------------------
        // Internal state
        // --------------------------------------------------------------------

        private bool tradingEnabled;
        private TimeZoneInfo pacificTz;

        // Daily tracking
        private DateTime currentSessionDate = DateTime.MinValue;
        private int tradesToday;
        private double sessionStartCumProfit;

        protected override void OnStateChange()
        {
            if (State == State.SetDefaults)
            {
                Description = "MNQ volatility breakout strategy for afternoon session.";
                Name = "NTAAiSandboxVolatilityMnq011";
                Calculate = Calculate.OnBarClose;
                IsExitOnSessionCloseStrategy = true; // Force flat at session close
                IsInstantiatedOnEachOptimizationIteration = false;

                Quantity = 1;
                StopLossTicks = 20;
                ProfitTargetTicks = 30;
                MaxDailyLoss = 400;
                BreakoutLookback = 25;
                SessionStartPT = "06:30";
                SessionEndPT = "12:30";
                TradeStartTimePT = "13:00";
                TradeEndTimePT = "16:00";
                NewsEventType = "economic_indicator";
                MaxTradesPerDay = 10;

                pacificTz = TimeZoneInfo.FindSystemTimeZoneById("Pacific Standard Time");
            }
            else if (State == State.Configure)
            {
                // Set default stop loss / profit target for all orders
                SetStopLoss(CalculationMode.Ticks, StopLossTicks);
                SetProfitTarget(CalculationMode.Ticks, ProfitTargetTicks);
            }
        }

        protected override void OnBarUpdate()
        {
            // --------------------------------------------------------------------
            // Session/day reset logic (robust)
            // --------------------------------------------------------------------
            DateTime barUtc = Bars.GetTime(0);
            DateTime barPacific = TimeZoneInfo.ConvertTimeFromUtc(barUtc, pacificTz);

            bool newSessionOrDay =
                Bars.IsFirstBarOfSession ||
                currentSessionDate == DateTime.MinValue ||
                barPacific.Date != currentSessionDate;

            if (newSessionOrDay)
            {
                currentSessionDate = barPacific.Date;
                tradesToday = 0;
                sessionStartCumProfit = SystemPerformance.AllTrades.TradesPerformance.Currency.CumProfit;
                tradingEnabled = true; // start each day with trading enabled
            }

            // --------------------------------------------------------------------
            // Force flat at session end or trade window end
            // --------------------------------------------------------------------
            if (Bars.IsLastBarOfSession || IsAtTradeEndTime(barPacific))
            {
                ForceFlat();
                return;
            }

            // --------------------------------------------------------------------
            // Enforce daily loss and max trades limits on every bar
            // --------------------------------------------------------------------
            double currentCumProfit = SystemPerformance.AllTrades.TradesPerformance.Currency.CumProfit;
            if (currentCumProfit - sessionStartCumProfit <= -MaxDailyLoss || tradesToday >= MaxTradesPerDay)
                tradingEnabled = false;

            // If we are not allowed to trade, exit early
            if (!tradingEnabled)
                return;

            // Ensure we have a flat position before attempting new entries
            if (Position.MarketPosition != MarketPosition.Flat)
                return;

            // --------------------------------------------------------------------
            // Check if within trade window
            // --------------------------------------------------------------------
            if (!IsWithinTradeWindow(barPacific))
                return;

            // --------------------------------------------------------------------
            // Breakout logic using NT8‑safe MAX/MIN functions
            // --------------------------------------------------------------------
            double highestHigh = MAX(High, BreakoutLookback)[1];
            double lowestLow   = MIN(Low,  BreakoutLookback)[1];

            if (Close[0] > highestHigh)
            {
                EnterLong(Quantity, "LongBreakout");
                tradesToday++;
            }
            else if (Close[0] < lowestLow)
            {
                EnterShort(Quantity, "ShortBreakout");
                tradesToday++;
            }

            // After each entry check daily loss limit again
            currentCumProfit = SystemPerformance.AllTrades.TradesPerformance.Currency.CumProfit;
            if (currentCumProfit - sessionStartCumProfit <= -MaxDailyLoss)
                tradingEnabled = false;
        }

        private bool IsWithinTradeWindow(DateTime pacificTime)
        {
            TimeSpan start = TimeSpan.Parse(TradeStartTimePT);
            TimeSpan end   = TimeSpan.Parse(TradeEndTimePT);
            return pacificTime.TimeOfDay >= start && pacificTime.TimeOfDay <= end;
        }

        private bool IsAtTradeEndTime(DateTime pacificNow)
        {
            TimeSpan tradeEnd = TimeSpan.Parse(TradeEndTimePT);
            return pacificNow.TimeOfDay >= tradeEnd;
        }

        private void ForceFlat()
        {
            if (Position.MarketPosition == MarketPosition.Long)
                ExitLong("ForceFlat", "LongBreakout");
            else if (Position.MarketPosition == MarketPosition.Short)
                ExitShort("ForceFlat", "ShortBreakout");
        }
    }
}