using System;
using NinjaTrader.Cbi;
using NinjaTrader.NinjaScript.Strategies;

namespace NinjaTrader.NinjaScript.Strategies
{
    public abstract partial class NTASessionVwapReclaimScalper
    {
        protected override void OnOrderUpdate(Order order, double limitPrice, double stopPrice,
            int quantity, int filled, double averageFillPrice, OrderState orderState,
            DateTime time, ErrorCode error, string nativeError)
        {
            bool isEntryOrder = order != null && IsEntrySignalName(order.Name);
            if (_pendingEntrySignal != null && isEntryOrder)
                _pendingEntryOrder = order;

            if (_pendingEntrySignal != null
                && isEntryOrder
                && (orderState == OrderState.Filled || orderState == OrderState.PartFilled))
            {
                _lastEntryPrice = averageFillPrice;
                _lastEntryQty = filled > 0 ? filled : _pendingEntryQty;
                _lastStopTicks = _pendingStopTicks;
                _lastEntryBar = CurrentBar;
                _lastDirection = _pendingEntrySignal;
                _lastSetupTag = _pendingSetupTag;
                _lastEntryTime = time;
                _tradeMfeTicks = 0.0;
                _tradeMaeTicks = 0.0;
                ClearPendingEntryState();
            }
            else if (_pendingEntrySignal != null
                && isEntryOrder
                && (orderState == OrderState.Cancelled || orderState == OrderState.Rejected))
            {
                ClearPendingEntryState();
            }
        }

        protected override void OnPositionUpdate(Position position, double averagePrice,
            int quantity, MarketPosition marketPosition)
        {
            if (marketPosition != MarketPosition.Flat) return;
            if (SystemPerformance == null || _risk == null) return;

            int total = SystemPerformance.AllTrades.Count;
            if (total <= _risk.LastProcessedTradeCount) return;

            for (int i = _risk.LastProcessedTradeCount; i < total; i++)
            {
                Trade trade = SystemPerformance.AllTrades[i];
                double adjustedPnl = _risk.RecordClosedTrade(trade, RoundTurnCommission);
                LogClosedTrade(trade, adjustedPnl);
            }
            _risk.LastProcessedTradeCount = total;

            _lastEntryPrice = 0.0;
            _lastEntryQty = 0;
            _lastStopTicks = 0;
            _lastEntryBar = -1;
            _lastDirection = "";
            _lastSetupTag = "";
            _lastEntryTime = DateTime.MinValue;
            _tradeMfeTicks = 0.0;
            _tradeMaeTicks = 0.0;
        }
    }
}
