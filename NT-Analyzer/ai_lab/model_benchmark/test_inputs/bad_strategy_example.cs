using System;
using NinjaTrader.Cbi;
using NinjaTrader.Strategy;

namespace NinjaTrader.Strategy
{
    public class BadBreakoutShort : Strategy
    {
        public int Fast = 20;
        public int Slow = 50;
        public int MaxTradesPerDay = 3;
        public double MaxDailyLoss = 250;

        protected override void Initialize()
        {
            CalculateOnBarClose = true;
            Add(PeriodType.Minute, 5);
        }

        protected override void OnBarUpdate()
        {
            if (CurrentBar < 50)
                return;

            if (Position.MarketPosition == MarketPosition.Flat
                && Close[0] < EMA(20)[0]
                && Close[0] < EMA(50)[0])
            {
                EnterLong(DefaultQuantity, "ShortEntry");
            }

            if (Position.MarketPosition == MarketPosition.Short
                && CrossAbove(Close, EMA(20), 1))
            {
                ExitShort("Cover", "ShortEntry");
            }
        }
    }
}