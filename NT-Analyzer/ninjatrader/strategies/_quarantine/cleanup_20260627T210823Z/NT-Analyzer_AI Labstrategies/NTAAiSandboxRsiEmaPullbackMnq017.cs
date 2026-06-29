using NinjaTrader.NinjaScript;
using NinjaTrader.NinjaScript.Strategies;
using NinjaTrader.Data;
using NinjaTrader.Cbi;
using System;

namespace NinjaTrader.NinjaScript.Strategies
{
    public class NTAAiSandboxRsiEmaPullbackMnq017 : Strategy
    {
        // --------------------------------------------------------------------
        // Parameters (public properties with NinjaScriptProperty attribute)
        // --------------------------------------------------------------------
        [NinjaTrader.NinjaScript.NinjaScriptProperty]
        public int Quantity { get; set; } = 1;

        [NinjaTrader.NinjaScript.NinjaScriptProperty]
        public int StopLossTicks { get; set; } = 20;

        [NinjaTrader.NinjaScript.NinjaScriptProperty]
        public int ProfitTargetTicks { get; set; } = 44;

        [NinjaTrader.NinjaScript.NinjaScriptProperty]
        public double MaxDailyLoss { get; set; } = 300.0;

        [NinjaTrader.NinjaScript.NinjaScriptProperty]
        public int MaxTradesPerDay { get; set; } = 2;

        [NinjaTrader.NinjaScript.NinjaScriptProperty]
        public int FastEmaPeriod { get; set; } = 21;

        [NinjaTrader.NinjaScript.NinjaScriptProperty]
        public int SlowEmaPeriod { get; set; } = 55;

        [NinjaTrader.NinjaScript.NinjaScriptProperty]
        public int RsiPeriod { get; set; } = 14;

        [NinjaTrader.NinjaScript.NinjaScriptProperty]
        public int RsiSmoothing { get; set; } = 3;

        [NinjaTrader.NinjaScript.NinjaScriptProperty]
        public double LongRsiMax { get; set; } = 48.0;

        [NinjaTrader.NinjaScript.NinjaScriptProperty]
        public double ShortRsiMin { get; set; } = 52.0;

        [NinjaTrader.NinjaScript.NinjaScriptProperty]
        public int MinEmaSpreadTicks { get; set; } = 4;

        [NinjaTrader.NinjaScript.NinjaScriptProperty]
        public int MaxBarsInTrade { get; set; } = 12;

        [NinjaTrader.NinjaScript.NinjaScriptProperty]
        public string SessionStartPT { get; set; } = "06:35";

        [NinjaTrader.NinjaScript.NinjaScriptProperty]
        public string SessionEndPT { get; set; } = "11:30";

        [NinjaTrader.NinjaScript.NinjaScriptProperty]
        public double RoundTurnCommission { get; set; } = 1.9;

        [NinjaTrader.NinjaScript.NinjaScriptProperty]
        public int SlippageTicks { get; set; } = 1;

        // --------------------------------------------------------------------
        // Internal state
        // --------------------------------------------------------------------
        private int _tradesToday;
        private DateTime _currentSessionStart;
        private DateTime _currentSessionEnd;
        private DateTime _sessionDate = DateTime.MinValue;
        private double _sessionStartCumProfit;
        private bool _sessionActive;

        // --------------------------------------------------------------------
        // OnStateChange: initialize indicators and parameters
        // --------------------------------------------------------------------
        protected override void OnStateChange()
        {
            if (State == State.SetDefaults)
            {
                Name = "NTAAiSandboxRsiEmaPullbackMnq017";
                Calculate = Calculate.OnBarClose;
                IsOverlay = false;

                // Set default values for properties
                Quantity = 1;
                StopLossTicks = 20;
                ProfitTargetTicks = 44;
                MaxDailyLoss = 300.0;
                MaxTradesPerDay = 2;
                FastEmaPeriod = 21;
                SlowEmaPeriod = 55;
                RsiPeriod = 14;
                RsiSmoothing = 3;
                LongRsiMax = 48.0;
                ShortRsiMin = 52.0;
                MinEmaSpreadTicks = 4;
                MaxBarsInTrade = 12;
                SessionStartPT = "06:35";
                SessionEndPT = "11:30";
                RoundTurnCommission = 1.9;
                SlippageTicks = 1;
            }
            else if (State == State.Configure)
            {
                // Add indicators
                EMA(FastEmaPeriod);
                EMA(SlowEmaPeriod);
                RSI(RsiPeriod, RsiSmoothing);

                // Set stop loss and profit target in ticks
                SetStopLoss(CalculationMode.Ticks, StopLossTicks);
                SetProfitTarget(CalculationMode.Ticks, ProfitTargetTicks);
            }
        }

        // --------------------------------------------------------------------
        // OnBarUpdate: main logic
        // --------------------------------------------------------------------
        protected override void OnBarUpdate()
        {
            if (CurrentBar < Math.Max(FastEmaPeriod, SlowEmaPeriod))
                return;

            // Session handling
            DateTime barTime = Time[0];
            if (_sessionDate.Date != barTime.Date)
            {
                DateTime today = barTime.Date;
                _currentSessionStart = DateTime.ParseExact(SessionStartPT, "HH:mm", System.Globalization.CultureInfo.InvariantCulture);
                _currentSessionEnd = DateTime.ParseExact(SessionEndPT, "HH:mm", System.Globalization.CultureInfo.InvariantCulture);

                // Combine with today's date
                _currentSessionStart = today.Add(_currentSessionStart.TimeOfDay);
                _currentSessionEnd = today.Add(_currentSessionEnd.TimeOfDay);
                _sessionDate = today;
                _tradesToday = 0;
                _sessionStartCumProfit = SystemPerformance.AllTrades.TradesPerformance.Currency.CumProfit;
            }

            _sessionActive = barTime >= _currentSessionStart && barTime < _currentSessionEnd;

            if (!_sessionActive)
            {
                // Outside session: force flat
                ForceFlat();
                return;
            }

            // Max daily loss guard using SystemPerformance
            double sessionPnl = SystemPerformance.AllTrades.TradesPerformance.Currency.CumProfit - _sessionStartCumProfit;
            if (sessionPnl <= -MaxDailyLoss)
            {
                ForceFlat();
                return;
            }

            // Max trades per day guard
            if (_tradesToday >= MaxTradesPerDay)
            {
                ForceFlat();
                return;
            }

            // Calculate EMA spread in ticks
            double fastEma = EMA(FastEmaPeriod)[0];
            double slowEma = EMA(SlowEmaPeriod)[0];
            double emaSpreadTicks = Math.Abs(fastEma - slowEma) / TickSize;

            // RSI value
            double rsiVal = RSI(RsiPeriod, RsiSmoothing)[0];

            // Entry logic
            if (Position.MarketPosition == MarketPosition.Flat)
            {
                // Long condition
                if (fastEma > slowEma && emaSpreadTicks >= MinEmaSpreadTicks &&
                    rsiVal <= LongRsiMax && Close[0] >= fastEma && Close[0] > Open[0])
                {
                    EnterLong(Quantity, "Long");
                    _tradesToday++;
                }
                // Short condition
                else if (fastEma < slowEma && emaSpreadTicks >= MinEmaSpreadTicks &&
                         rsiVal >= ShortRsiMin && Close[0] <= fastEma && Close[0] < Open[0])
                {
                    EnterShort(Quantity, "Short");
                    _tradesToday++;
                }
            }

            // Exit logic for existing positions
            if (Position.MarketPosition == MarketPosition.Long)
            {
                // Force flat after MaxBarsInTrade bars
                if (BarsSinceEntryExecution(0, "Long", 0) >= MaxBarsInTrade)
                {
                    ExitLong();
                    return;
                }

                // Pullback exit: close above fast EMA with bullish close
                if (Close[0] > fastEma && Close[0] > Open[0])
                {
                    ExitLong();
                }
            }
            else if (Position.MarketPosition == MarketPosition.Short)
            {
                // Force flat after MaxBarsInTrade bars
                if (BarsSinceEntryExecution(0, "Short", 0) >= MaxBarsInTrade)
                {
                    ExitShort();
                    return;
                }

                // Pullback exit: close below fast EMA with bearish close
                if (Close[0] < fastEma && Close[0] < Open[0])
                {
                    ExitShort();
                }
            }
        }

        private void ForceFlat()
        {
            if (Position.MarketPosition == MarketPosition.Long)
                ExitLong();
            else if (Position.MarketPosition == MarketPosition.Short)
                ExitShort();
        }
    }
}