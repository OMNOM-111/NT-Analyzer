// NTAMicroVwapRiskPilot.RiskManager.cs
// Private nested class RiskManager — encapsulates equity, daily limits, sizing, status guard.
// Part of partial class NTAMicroVwapRiskPilot.

using System;
using NinjaTrader.Cbi;
using NinjaTrader.NinjaScript.Strategies;

namespace NinjaTrader.NinjaScript.Strategies
{
    public partial class NTAMicroVwapRiskPilot
    {
        // =====================================================================
        // RiskManager — encapsulates equity, daily limits, sizing, status guard
        // =====================================================================
        private class RiskManager
        {
            private readonly NTAMicroVwapRiskPilot _s;

            public bool   PermanentlyStopped { get; private set; }
            public bool   SessionStopped     { get; private set; }
            public double CumulativeRealizedPnL { get; private set; }
            public double SessionRealizedPnL    { get; private set; }
            public double SessionStartEquity    { get; private set; }
            public int    TradesToday           { get; private set; }
            public int    ConsecutiveLosses     { get; private set; }
            public int    LastProcessedTradeCount { get; set; }

            public RiskManager(NTAMicroVwapRiskPilot s) { _s = s; }

            public void Init()
            {
                PermanentlyStopped       = false;
                SessionStopped           = false;
                CumulativeRealizedPnL    = 0.0;
                SessionRealizedPnL       = 0.0;
                SessionStartEquity       = _s.StartingCapital;
                TradesToday              = 0;
                ConsecutiveLosses        = 0;
                LastProcessedTradeCount  = 0;

                if (_s.StartingCapital <= 0.0)
                {
                    PermanentlyStopped = true;
                    _s.Print("[RISK:stop_trading] StartingCapital <= 0 — strategy disabled");
                }
                else if (string.Equals(_s.InstrumentStatus, "blocked",
                                       StringComparison.OrdinalIgnoreCase))
                {
                    PermanentlyStopped = true;
                    _s.Print("[RISK:stop_trading] InstrumentStatus = blocked — strategy disabled");
                }
                else if (string.Equals(_s.InstrumentStatus, "unknown",
                                       StringComparison.OrdinalIgnoreCase))
                {
                    PermanentlyStopped = true;
                    _s.Print("[RISK:stop_trading] InstrumentStatus = unknown — no margin info — strategy disabled");
                }
                else if (_s.ActiveMarginPerContract <= 0.0)
                {
                    PermanentlyStopped = true;
                    _s.Print("[RISK:stop_trading] ActiveMarginPerContract <= 0 — strategy disabled");
                }
                else if (_s.MaxContractsByCapital < 1)
                {
                    PermanentlyStopped = true;
                    _s.Print("[RISK:stop_trading] MaxContractsByCapital < 1 — strategy disabled");
                }
            }

            public string Describe()
            {
                return string.Format(
                    "capital={0:F2} margin={1:F2} maxC={2} status={3} broker={4} intradayOnly={5}",
                    _s.StartingCapital, _s.ActiveMarginPerContract, _s.MaxContractsByCapital,
                    _s.InstrumentStatus, _s.MarginSourceBroker, _s.IntradayOnly);
            }

            public double CurrentEquity()
            {
                double unreal = 0.0;
                if (_s.Position != null && _s.Position.MarketPosition != MarketPosition.Flat
                    && _s.Position.Quantity > 0)
                {
                    unreal = _s.Position.GetUnrealizedProfitLoss(
                                PerformanceUnit.Currency, _s.Close[0]);
                }
                return _s.StartingCapital + CumulativeRealizedPnL + unreal;
            }

            public void OnNewSession()
            {
                SessionRealizedPnL = 0.0;
                TradesToday        = 0;
                ConsecutiveLosses  = 0;
                SessionStopped     = false;
                SessionStartEquity = _s.StartingCapital + CumulativeRealizedPnL;
            }

            public void UpdateDailyStops()
            {
                if (SessionStopped || PermanentlyStopped) return;

                // Limits computed off SessionStartEquity for honest day risk.
                double dailyStopUsd   = SessionStartEquity * _s.MaxDailyLossPct   / 100.0;
                double dailyProfitUsd = SessionStartEquity * _s.MaxDailyProfitPct / 100.0;

                if (SessionRealizedPnL <= -dailyStopUsd)
                {
                    SessionStopped = true;
                    _s.Print(string.Format(
                        "[RISK:stop_trading] daily_loss {0:F2} <= -{1:F2} (sessionEq={2:F2})",
                        SessionRealizedPnL, dailyStopUsd, SessionStartEquity));
                    return;
                }
                if (_s.MaxDailyProfitPct > 0 && SessionRealizedPnL >= dailyProfitUsd)
                {
                    SessionStopped = true;
                    _s.Print(string.Format(
                        "[RISK:stop_trading] daily_profit {0:F2} >= {1:F2} (sessionEq={2:F2})",
                        SessionRealizedPnL, dailyProfitUsd, SessionStartEquity));
                    return;
                }
                if (ConsecutiveLosses >= _s.MaxConsecutiveLosses)
                {
                    SessionStopped = true;
                    _s.Print(string.Format(
                        "[RISK:stop_trading] consecutive_losses={0}", ConsecutiveLosses));
                    return;
                }
                if (TradesToday >= _s.MaxTradesPerDay)
                {
                    SessionStopped = true;
                    _s.Print(string.Format(
                        "[RISK:stop_trading] trades_today={0}", TradesToday));
                    return;
                }
            }

            public int ComputeQuantity(int stopTicks, double commissionPerRT, int slippageTicks)
            {
                if (PermanentlyStopped) return 0;
                double tickValue = (_s.Instrument != null && _s.Instrument.MasterInstrument != null)
                    ? _s.Instrument.MasterInstrument.PointValue * _s.TickSize
                    : 0.0;
                if (tickValue <= 0.0) return 0;

                double equity     = CurrentEquity();
                double riskBudget = equity * _s.RiskPerTradePct / 100.0;
                double contractRisk = stopTicks * tickValue
                                    + commissionPerRT
                                    + slippageTicks * tickValue;
                if (contractRisk <= 0.0) return 0;

                int byRisk   = (int)Math.Floor(riskBudget / contractRisk);
                int byMargin = (_s.ActiveMarginPerContract > 0.0)
                               ? (int)Math.Floor(equity / _s.ActiveMarginPerContract)
                               : 0;

                int q = byRisk;
                if (byMargin > 0)               q = Math.Min(q, byMargin);
                if (_s.MaxContractsByCapital > 0) q = Math.Min(q, _s.MaxContractsByCapital);
                if (_s.UserMaxContracts > 0)      q = Math.Min(q, _s.UserMaxContracts);
                return q < 1 ? 0 : q;
            }

            public void RecordClosedTrade(NinjaTrader.Cbi.Trade t, double commissionPerRT)
            {
                // NinjaTrader Strategy Analyzer here is run with commission_template="None",
                // so t.ProfitCurrency is GROSS. We subtract commission ONCE for risk math.
                double qty = Math.Max(1, t.Quantity);
                double pnl = t.ProfitCurrency - (commissionPerRT * qty);

                CumulativeRealizedPnL += pnl;
                SessionRealizedPnL    += pnl;
                TradesToday           += 1;
                if (pnl < 0) ConsecutiveLosses += 1;
                else         ConsecutiveLosses  = 0;

                _s.Print(string.Format(
                    "[EXIT] pnl={0:F2} cumPnL={1:F2} dayPnL={2:F2} trades={3} consecLoss={4}",
                    pnl, CumulativeRealizedPnL, SessionRealizedPnL, TradesToday, ConsecutiveLosses));
            }
        }
    }
}
