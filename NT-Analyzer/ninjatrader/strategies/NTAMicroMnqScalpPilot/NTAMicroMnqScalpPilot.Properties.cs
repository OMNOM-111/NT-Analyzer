// NTAMicroMnqScalpPilot.Properties.cs
// All [NinjaScriptProperty] / [Display] / [Range] declarations.

using System.ComponentModel.DataAnnotations;
using NinjaTrader.NinjaScript;
using NinjaTrader.NinjaScript.Strategies;

namespace NinjaTrader.NinjaScript.Strategies
{
    public partial class NTAMicroMnqScalpPilot
    {
        #region Risk Profile
        [NinjaScriptProperty]
        [Display(Name = "StartingCapital", GroupName = "01-Risk Profile", Order = 0)]
        public double StartingCapital { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "IntradayOnly", GroupName = "01-Risk Profile", Order = 1)]
        public bool IntradayOnly { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "ActiveMarginPerContract", GroupName = "01-Risk Profile", Order = 2)]
        public double ActiveMarginPerContract { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "MaxContractsByCapital", GroupName = "01-Risk Profile", Order = 3)]
        public int MaxContractsByCapital { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "InstrumentStatus", GroupName = "01-Risk Profile", Order = 4)]
        public string InstrumentStatus { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "MarginSourceBroker", GroupName = "01-Risk Profile", Order = 5)]
        public string MarginSourceBroker { get; set; }
        #endregion

        #region Risk
        [NinjaScriptProperty, Range(0.01, 10.0)]
        [Display(Name = "RiskPerTradePct", GroupName = "02-Risk", Order = 0)]
        public double RiskPerTradePct { get; set; }

        [NinjaScriptProperty, Range(0.1, 50.0)]
        [Display(Name = "MaxDailyLossPct", GroupName = "02-Risk", Order = 1)]
        public double MaxDailyLossPct { get; set; }

        [NinjaScriptProperty, Range(0.0, 10000.0)]
        [Display(Name = "MaxDailyLossUsd (0=use pct)", GroupName = "02-Risk", Order = 2)]
        public double MaxDailyLossUsd { get; set; }

        [NinjaScriptProperty, Range(0.0, 10000.0)]
        [Display(Name = "MaxWeeklyLossUsd (0=off)", GroupName = "02-Risk", Order = 3)]
        public double MaxWeeklyLossUsd { get; set; }

        [NinjaScriptProperty, Range(0.0, 100.0)]
        [Display(Name = "MaxDailyProfitPct (0=off)", GroupName = "02-Risk", Order = 4)]
        public double MaxDailyProfitPct { get; set; }

        [NinjaScriptProperty, Range(1, 100)]
        [Display(Name = "MaxTradesPerDay", GroupName = "02-Risk", Order = 5)]
        public int MaxTradesPerDay { get; set; }

        [NinjaScriptProperty, Range(1, 200)]
        [Display(Name = "HardMaxTradesPerDay", GroupName = "02-Risk", Order = 6)]
        public int HardMaxTradesPerDay { get; set; }

        [NinjaScriptProperty, Range(1, 20)]
        [Display(Name = "MaxConsecutiveLosses", GroupName = "02-Risk", Order = 7)]
        public int MaxConsecutiveLosses { get; set; }

        [NinjaScriptProperty, Range(1, 20)]
        [Display(Name = "PauseAfterConsecutiveLosses", GroupName = "02-Risk", Order = 8)]
        public int PauseAfterConsecutiveLosses { get; set; }

        [NinjaScriptProperty, Range(1, 240)]
        [Display(Name = "PauseMinutesAfterLosses", GroupName = "02-Risk", Order = 9)]
        public int PauseMinutesAfterLosses { get; set; }

        [NinjaScriptProperty, Range(1, 100)]
        [Display(Name = "UserMaxContracts", GroupName = "02-Risk", Order = 10)]
        public int UserMaxContracts { get; set; }

        [NinjaScriptProperty, Range(1, 10)]
        [Display(Name = "MaxOpenPositions", GroupName = "02-Risk", Order = 11)]
        public int MaxOpenPositions { get; set; }

        [NinjaScriptProperty, Range(0.0, 100.0)]
        [Display(Name = "RoundTurnCommission ($)", GroupName = "02-Risk", Order = 12)]
        public double RoundTurnCommission { get; set; }

        [NinjaScriptProperty, Range(0, 20)]
        [Display(Name = "SlippageTicks", GroupName = "02-Risk", Order = 13)]
        public int SlippageTicks { get; set; }
        #endregion

        #region SetupMode + toggles
        [NinjaScriptProperty]
        [Display(Name = "SetupMode (legacy single-module selector)", GroupName = "03-Setup", Order = 0)]
        public MnqScalpSetupMode SetupMode { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "UseSetupModeFilter", GroupName = "03-Setup", Order = 1)]
        public bool UseSetupModeFilter { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "EnableVwapReclaim", GroupName = "03-Setup", Order = 2)]
        public bool EnableVwapReclaim { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "EnableEmaMomentum", GroupName = "03-Setup", Order = 3)]
        public bool EnableEmaMomentum { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "EnableMicroOrb", GroupName = "03-Setup", Order = 4)]
        public bool EnableMicroOrb { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "EnableFailedBreakout", GroupName = "03-Setup", Order = 5)]
        public bool EnableFailedBreakout { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "EnableLong", GroupName = "03-Setup", Order = 6)]
        public bool EnableLong { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "EnableShort", GroupName = "03-Setup", Order = 7)]
        public bool EnableShort { get; set; }
        #endregion

        #region Indicators
        [NinjaScriptProperty, Range(2, 200)]
        [Display(Name = "EmaFastPeriod", GroupName = "04-Indicators", Order = 0)]
        public int EmaFastPeriod { get; set; }

        [NinjaScriptProperty, Range(2, 400)]
        [Display(Name = "EmaMidPeriod", GroupName = "04-Indicators", Order = 1)]
        public int EmaMidPeriod { get; set; }

        [NinjaScriptProperty, Range(2, 400)]
        [Display(Name = "EmaSlowPeriod", GroupName = "04-Indicators", Order = 2)]
        public int EmaSlowPeriod { get; set; }

        [NinjaScriptProperty, Range(2, 200)]
        [Display(Name = "AtrPeriod", GroupName = "04-Indicators", Order = 3)]
        public int AtrPeriod { get; set; }

        [NinjaScriptProperty, Range(2, 200)]
        [Display(Name = "AdxPeriod", GroupName = "04-Indicators", Order = 4)]
        public int AdxPeriod { get; set; }

        [NinjaScriptProperty, Range(0.0, 100.0)]
        [Display(Name = "MinAdx", GroupName = "04-Indicators", Order = 5)]
        public double MinAdx { get; set; }

        [NinjaScriptProperty, Range(2, 500)]
        [Display(Name = "VolumeSmaPeriod", GroupName = "04-Indicators", Order = 6)]
        public int VolumeSmaPeriod { get; set; }

        [NinjaScriptProperty, Range(0.0, 10.0)]
        [Display(Name = "MinVolumeFactor", GroupName = "04-Indicators", Order = 7)]
        public double MinVolumeFactor { get; set; }

        [NinjaScriptProperty, Range(1, 50)]
        [Display(Name = "PullbackLookback (bars)", GroupName = "04-Indicators", Order = 8)]
        public int PullbackLookback { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "RequireSlowTrend (Mid vs Slow alignment)", GroupName = "04-Indicators", Order = 9)]
        public bool RequireSlowTrend { get; set; }
        #endregion

        #region Stops / targets
        [NinjaScriptProperty, Range(0.05, 5.0)]
        [Display(Name = "AtrStopMult", GroupName = "05-Stops", Order = 0)]
        public double AtrStopMult { get; set; }

        [NinjaScriptProperty, Range(1, 200)]
        [Display(Name = "MinStopTicks", GroupName = "05-Stops", Order = 1)]
        public int MinStopTicks { get; set; }

        [NinjaScriptProperty, Range(1, 1000)]
        [Display(Name = "MaxStopTicks", GroupName = "05-Stops", Order = 2)]
        public int MaxStopTicks { get; set; }

        [NinjaScriptProperty, Range(0.1, 10.0)]
        [Display(Name = "RewardRiskRatio", GroupName = "05-Stops", Order = 3)]
        public double RewardRiskRatio { get; set; }

        [NinjaScriptProperty, Range(0.0, 5.0)]
        [Display(Name = "MoveToBreakevenAtR", GroupName = "05-Stops", Order = 4)]
        public double MoveToBreakevenAtR { get; set; }

        [NinjaScriptProperty, Range(0.0, 10.0)]
        [Display(Name = "TrailAfterR", GroupName = "05-Stops", Order = 5)]
        public double TrailAfterR { get; set; }
        #endregion

        #region Time-stop
        [NinjaScriptProperty]
        [Display(Name = "UseTimeStop", GroupName = "06-TimeStop", Order = 0)]
        public bool UseTimeStop { get; set; }

        [NinjaScriptProperty, Range(1, 50)]
        [Display(Name = "TimeStopBars", GroupName = "06-TimeStop", Order = 1)]
        public int TimeStopBars { get; set; }

        [NinjaScriptProperty, Range(0.0, 5.0)]
        [Display(Name = "MinProgressR (exit if |R|<thr at TimeStopBars)", GroupName = "06-TimeStop", Order = 2)]
        public double MinProgressR { get; set; }
        #endregion

        #region Entry
        [NinjaScriptProperty, Range(1, 20)]
        [Display(Name = "EntryTimeoutBars", GroupName = "07-Entry", Order = 0)]
        public int EntryTimeoutBars { get; set; }

        [NinjaScriptProperty, Range(0, 20)]
        [Display(Name = "EntryOffsetTicks", GroupName = "07-Entry", Order = 1)]
        public int EntryOffsetTicks { get; set; }
        #endregion

        #region Trading windows (HHMM PT)
        [NinjaScriptProperty, Range(0, 2359)]
        [Display(Name = "TradeStartTime (HHMM)", GroupName = "08-Time", Order = 0)]
        public int TradeStartTime { get; set; }

        [NinjaScriptProperty, Range(0, 2359)]
        [Display(Name = "TradeEndTime (HHMM)", GroupName = "08-Time", Order = 1)]
        public int TradeEndTime { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "UseSecondTradeWindow", GroupName = "08-Time", Order = 2)]
        public bool UseSecondTradeWindow { get; set; }

        [NinjaScriptProperty, Range(0, 2359)]
        [Display(Name = "SecondTradeStartTime (HHMM)", GroupName = "08-Time", Order = 3)]
        public int SecondTradeStartTime { get; set; }

        [NinjaScriptProperty, Range(0, 2359)]
        [Display(Name = "SecondTradeEndTime (HHMM)", GroupName = "08-Time", Order = 4)]
        public int SecondTradeEndTime { get; set; }

        [NinjaScriptProperty, Range(0, 2359)]
        [Display(Name = "ForceFlatTime (HHMM, 0=off)", GroupName = "08-Time", Order = 5)]
        public int ForceFlatTime { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "NewsBlackoutTimes (CSV HHMM)", GroupName = "08-Time", Order = 6)]
        public string NewsBlackoutTimes { get; set; }

        [NinjaScriptProperty, Range(1, 30)]
        [Display(Name = "NewsBlackoutWindowMin", GroupName = "08-Time", Order = 7)]
        public int NewsBlackoutWindowMin { get; set; }
        #endregion

        #region ORB
        [NinjaScriptProperty, Range(0, 2359)]
        [Display(Name = "OrbStartTime (HHMM)", GroupName = "09-ORB", Order = 0)]
        public int OrbStartTime { get; set; }

        [NinjaScriptProperty, Range(1, 240)]
        [Display(Name = "OrbDurationMinutes", GroupName = "09-ORB", Order = 1)]
        public int OrbDurationMinutes { get; set; }

        [NinjaScriptProperty, Range(0, 50)]
        [Display(Name = "OrbBreakoutBuffer (ticks)", GroupName = "09-ORB", Order = 2)]
        public int OrbBreakoutBuffer { get; set; }

        [NinjaScriptProperty, Range(1, 30)]
        [Display(Name = "OrbRetestBars (max bars after break to retest)", GroupName = "09-ORB", Order = 3)]
        public int OrbRetestBars { get; set; }

        [NinjaScriptProperty, Range(1, 20)]
        [Display(Name = "FailedBreakoutLookback (bars)", GroupName = "09-ORB", Order = 4)]
        public int OrbFailedLookback { get; set; }
        #endregion

        #region EMA Impulse
        [NinjaScriptProperty, Range(2, 10)]
        [Display(Name = "EmaImpulseLookback (bars of momentum)", GroupName = "10-EmaImpulse", Order = 0)]
        public int EmaImpulseLookback { get; set; }
        #endregion
    }
}
