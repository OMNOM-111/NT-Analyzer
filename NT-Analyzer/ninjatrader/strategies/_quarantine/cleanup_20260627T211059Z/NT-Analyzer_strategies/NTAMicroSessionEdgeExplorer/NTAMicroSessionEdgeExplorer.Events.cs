// NTAMicroSessionEdgeExplorer.Events.cs
using System;
using NinjaTrader.Cbi;
using NinjaTrader.NinjaScript.Strategies;

namespace NinjaTrader.NinjaScript.Strategies
{
    public abstract partial class NTAMicroSessionEdgeExplorer
    {
        protected override void OnOrderUpdate(Order order, double limitPrice, double stopPrice,
                                              int quantity, int filled, double averageFillPrice,
                                              OrderState orderState, DateTime time, ErrorCode error,
                                              string nativeError)
        {
            if (_pendingEntrySignal != null
                && order != null
                && IsEntrySignalName(order.Name)
                && (orderState == OrderState.Filled || orderState == OrderState.PartFilled))
            {
                _lastEntryPrice = averageFillPrice;
                _lastEntryQty   = filled > 0 ? filled : _pendingEntryQty;
                _lastStopTicks  = _pendingStopTicks;
                _activeEntrySignal = order.Name;
                _pendingEntrySignal = null;
                _pendingEntryBar    = -1;
            }
            else if (_pendingEntrySignal != null
                     && order != null
                     && IsEntrySignalName(order.Name)
                     && (orderState == OrderState.Cancelled || orderState == OrderState.Rejected))
            {
                _pendingEntrySignal = null;
                _pendingEntryBar    = -1;
            }
        }

        protected override void OnPositionUpdate(Position position, double averagePrice,
                                                 int quantity, MarketPosition marketPosition)
        {
            if (marketPosition != MarketPosition.Flat) return;
            if (SystemPerformance == null)             return;

            int total = SystemPerformance.AllTrades.Count;
            if (total <= _risk.LastProcessedTradeCount) return;

            for (int i = _risk.LastProcessedTradeCount; i < total; i++)
            {
                var t = SystemPerformance.AllTrades[i];
                _risk.RecordClosedTrade(t, RoundTurnCommission);
            }
            _risk.LastProcessedTradeCount = total;

            _lastStopTicks  = 0;
            _lastEntryPrice = 0;
            _lastEntryQty   = 0;
            _activeEntrySignal = null;
        }
    }
}
