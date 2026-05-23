// NTAMicroVwapRiskExplorer.Properties.cs
// All [NinjaScriptProperty] / [Display] / [Range] declarations.
// Part of partial class NTAMicroVwapRiskExplorer.

using System.ComponentModel.DataAnnotations;
using NinjaTrader.NinjaScript;
using NinjaTrader.NinjaScript.Strategies;

namespace NinjaTrader.NinjaScript.Strategies
{
    public abstract partial class NTAMicroVwapRiskExplorer
    {
        // ====================================================================
        // PROPERTIES
        // ====================================================================

        #region Risk Profile (filled by NT-Analyzer mapper — Phase 0 bridge contract)
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

        [NinjaScriptProperty, Range(0.0, 100.0)]
        [Display(Name = "MaxDailyProfitPct (0=off)", GroupName = "02-Risk", Order = 2)]
        public double MaxDailyProfitPct { get; set; }

        [NinjaScriptProperty, Range(1, 50)]
        [Display(Name = "MaxTradesPerDay", GroupName = "02-Risk", Order = 3)]
        public int MaxTradesPerDay { get; set; }

        [NinjaScriptProperty, Range(1, 20)]
        [Display(Name = "MaxConsecutiveLosses", GroupName = "02-Risk", Order = 4)]
        public int MaxConsecutiveLosses { get; set; }

        [NinjaScriptProperty, Range(1, 100)]
        [Display(Name = "UserMaxContracts", GroupName = "02-Risk", Order = 5)]
        public int UserMaxContracts { get; set; }

        [NinjaScriptProperty, Range(0.0, 100.0)]
        [Display(Name = "RoundTurnCommission ($)", GroupName = "02-Risk", Order = 6)]
        public double RoundTurnCommission { get; set; }

        [NinjaScriptProperty, Range(0, 20)]
        [Display(Name = "SlippageTicks", GroupName = "02-Risk", Order = 7)]
        public int SlippageTicks { get; set; }
        #endregion

        #region Setup toggles
        [NinjaScriptProperty]
        [Display(Name = "EnableLong", GroupName = "03-Setup", Order = 0)]
        public bool EnableLong { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "EnableShort", GroupName = "03-Setup", Order = 1)]
        public bool EnableShort { get; set; }
        #endregion

        #region Indicators
        [NinjaScriptProperty, Range(2, 200)]
        [Display(Name = "EmaFastPeriod", GroupName = "04-Indicators", Order = 0)]
        public int EmaFastPeriod { get; set; }

        [NinjaScriptProperty, Range(2, 400)]
        [Display(Name = "EmaSlowPeriod", GroupName = "04-Indicators", Order = 1)]
        public int EmaSlowPeriod { get; set; }

        [NinjaScriptProperty, Range(2, 200)]
        [Display(Name = "AtrPeriod", GroupName = "04-Indicators", Order = 2)]
        public int AtrPeriod { get; set; }

        [NinjaScriptProperty, Range(2, 200)]
        [Display(Name = "AdxPeriod", GroupName = "04-Indicators", Order = 3)]
        public int AdxPeriod { get; set; }

        [NinjaScriptProperty, Range(0.0, 100.0)]
        [Display(Name = "MinAdx", GroupName = "04-Indicators", Order = 4)]
        public double MinAdx { get; set; }

        [NinjaScriptProperty, Range(2, 500)]
        [Display(Name = "VolumeSmaPeriod", GroupName = "04-Indicators", Order = 5)]
        public int VolumeSmaPeriod { get; set; }

        [NinjaScriptProperty, Range(0.0, 10.0)]
        [Display(Name = "MinVolumeFactor", GroupName = "04-Indicators", Order = 6)]
        public double MinVolumeFactor { get; set; }

        [NinjaScriptProperty, Range(1, 50)]
        [Display(Name = "PullbackLookback (bars)", GroupName = "04-Indicators", Order = 7)]
        public int PullbackLookback { get; set; }
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

        #region Entry
        [NinjaScriptProperty, Range(1, 20)]
        [Display(Name = "EntryTimeoutBars", GroupName = "06-Entry", Order = 0)]
        public int EntryTimeoutBars { get; set; }

        [NinjaScriptProperty, Range(0, 20)]
        [Display(Name = "EntryOffsetTicks", GroupName = "06-Entry", Order = 1)]
        public int EntryOffsetTicks { get; set; }
        #endregion

        #region Trading windows (HHMM, PC local / Pacific Time on this machine)
        [NinjaScriptProperty, Range(0, 2359)]
        [Display(Name = "TradeStartTime (HHMM)", GroupName = "07-Time", Order = 0)]
        public int TradeStartTime { get; set; }

        [NinjaScriptProperty, Range(0, 2359)]
        [Display(Name = "TradeEndTime (HHMM)", GroupName = "07-Time", Order = 1)]
        public int TradeEndTime { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "UseSecondTradeWindow", GroupName = "07-Time", Order = 2)]
        public bool UseSecondTradeWindow { get; set; }

        [NinjaScriptProperty, Range(0, 2359)]
        [Display(Name = "SecondTradeStartTime (HHMM)", GroupName = "07-Time", Order = 3)]
        public int SecondTradeStartTime { get; set; }

        [NinjaScriptProperty, Range(0, 2359)]
        [Display(Name = "SecondTradeEndTime (HHMM)", GroupName = "07-Time", Order = 4)]
        public int SecondTradeEndTime { get; set; }

        [NinjaScriptProperty, Range(0, 2359)]
        [Display(Name = "ForceFlatTime (HHMM, 0=off)", GroupName = "07-Time", Order = 5)]
        public int ForceFlatTime { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "NewsBlackoutTimes (CSV HHMM)", GroupName = "07-Time", Order = 6)]
        public string NewsBlackoutTimes { get; set; }

        [NinjaScriptProperty, Range(1, 30)]
        [Display(Name = "NewsBlackoutWindowMin", GroupName = "07-Time", Order = 7)]
        public int NewsBlackoutWindowMin { get; set; }
        #endregion

        #region Daily bias filter (08-Daily)
        // No-lookahead: intraday decisions use _dailyEmaFast[1] and _dailyEmaSlow[1],
        // which are the values of the PREVIOUS completed daily bar only.
        [NinjaScriptProperty]
        [Display(Name = "UseDailyBiasFilter", GroupName = "08-Daily", Order = 0)]
        public bool UseDailyBiasFilter { get; set; }

        [NinjaScriptProperty, Range(2, 100)]
        [Display(Name = "DailyFastEmaPeriod", GroupName = "08-Daily", Order = 1)]
        public int DailyFastEmaPeriod { get; set; }

        [NinjaScriptProperty, Range(2, 400)]
        [Display(Name = "DailySlowEmaPeriod", GroupName = "08-Daily", Order = 2)]
        public int DailySlowEmaPeriod { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "BlockShortsWhenDailyBullish", GroupName = "08-Daily", Order = 3)]
        public bool BlockShortsWhenDailyBullish { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "BlockLongsWhenDailyBearish", GroupName = "08-Daily", Order = 4)]
        public bool BlockLongsWhenDailyBearish { get; set; }
        #endregion
    }
}
