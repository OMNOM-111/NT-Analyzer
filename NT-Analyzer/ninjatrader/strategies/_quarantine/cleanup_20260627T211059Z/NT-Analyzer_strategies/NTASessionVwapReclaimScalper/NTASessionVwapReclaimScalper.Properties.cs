using System.ComponentModel.DataAnnotations;
using NinjaTrader.NinjaScript;
using NinjaTrader.NinjaScript.Strategies;

namespace NinjaTrader.NinjaScript.Strategies
{
    public abstract partial class NTASessionVwapReclaimScalper
    {
        #region 01-Instrument
        [NinjaScriptProperty]
        [Display(Name = "InstrumentName", GroupName = "01-Instrument", Order = 0)]
        public string InstrumentName { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "ContractName", GroupName = "01-Instrument", Order = 1)]
        public string ContractName { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "SessionTemplateName", GroupName = "01-Instrument", Order = 2)]
        public string SessionTemplateName { get; set; }

        [NinjaScriptProperty, Range(1, 300)]
        [Display(Name = "BaseTimeframeSeconds", GroupName = "01-Instrument", Order = 3)]
        public int BaseTimeframeSeconds { get; set; }
        #endregion

        #region 02-Risk Profile
        [NinjaScriptProperty]
        [Display(Name = "StartingCapital", GroupName = "02-Risk Profile", Order = 0)]
        public double StartingCapital { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "IntradayOnly", GroupName = "02-Risk Profile", Order = 1)]
        public bool IntradayOnly { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "ActiveMarginPerContract", GroupName = "02-Risk Profile", Order = 2)]
        public double ActiveMarginPerContract { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "MaxContractsByCapital", GroupName = "02-Risk Profile", Order = 3)]
        public int MaxContractsByCapital { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "InstrumentStatus", GroupName = "02-Risk Profile", Order = 4)]
        public string InstrumentStatus { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "MarginSourceBroker", GroupName = "02-Risk Profile", Order = 5)]
        public string MarginSourceBroker { get; set; }
        #endregion

        #region 03-Direction
        [NinjaScriptProperty]
        [Display(Name = "EnableLong", GroupName = "03-Direction", Order = 0)]
        public bool EnableLong { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "EnableShort", GroupName = "03-Direction", Order = 1)]
        public bool EnableShort { get; set; }
        #endregion

        #region 04-Time
        [NinjaScriptProperty, Range(0, 2359)]
        [Display(Name = "TradeStartTime (HHMM)", GroupName = "04-Time", Order = 0)]
        public int TradeStartTime { get; set; }

        [NinjaScriptProperty, Range(0, 2359)]
        [Display(Name = "TradeEndTime (HHMM)", GroupName = "04-Time", Order = 1)]
        public int TradeEndTime { get; set; }

        [NinjaScriptProperty, Range(0, 2359)]
        [Display(Name = "ForceFlatTime (HHMM)", GroupName = "04-Time", Order = 2)]
        public int ForceFlatTime { get; set; }

        [NinjaScriptProperty, Range(0, 2359)]
        [Display(Name = "OpeningRangeStartTime (HHMM)", GroupName = "04-Time", Order = 3)]
        public int OpeningRangeStartTime { get; set; }

        [NinjaScriptProperty, Range(1, 120)]
        [Display(Name = "OpeningRangeMinutes", GroupName = "04-Time", Order = 4)]
        public int OpeningRangeMinutes { get; set; }
        #endregion

        #region 05-Indicators
        [NinjaScriptProperty, Range(2, 200)]
        [Display(Name = "EmaFastPeriod", GroupName = "05-Indicators", Order = 0)]
        public int EmaFastPeriod { get; set; }

        [NinjaScriptProperty, Range(2, 400)]
        [Display(Name = "EmaSlowPeriod", GroupName = "05-Indicators", Order = 1)]
        public int EmaSlowPeriod { get; set; }

        [NinjaScriptProperty, Range(2, 200)]
        [Display(Name = "AtrPeriod", GroupName = "05-Indicators", Order = 2)]
        public int AtrPeriod { get; set; }

        [NinjaScriptProperty, Range(2, 200)]
        [Display(Name = "AdxPeriod", GroupName = "05-Indicators", Order = 3)]
        public int AdxPeriod { get; set; }

        [NinjaScriptProperty, Range(0.0, 100.0)]
        [Display(Name = "MinAdx", GroupName = "05-Indicators", Order = 4)]
        public double MinAdx { get; set; }

        [NinjaScriptProperty, Range(2, 500)]
        [Display(Name = "VolumeSmaPeriod", GroupName = "05-Indicators", Order = 5)]
        public int VolumeSmaPeriod { get; set; }

        [NinjaScriptProperty, Range(0.0, 10.0)]
        [Display(Name = "MinVolumeFactor", GroupName = "05-Indicators", Order = 6)]
        public double MinVolumeFactor { get; set; }

        [NinjaScriptProperty, Range(0.0, 1.0)]
        [Display(Name = "MinBodyRangePct", GroupName = "05-Indicators", Order = 7)]
        public double MinBodyRangePct { get; set; }

        [NinjaScriptProperty, Range(0.0, 1.0)]
        [Display(Name = "MinCloseLocationPct", GroupName = "05-Indicators", Order = 8)]
        public double MinCloseLocationPct { get; set; }
        #endregion

        #region 06-VWAP
        [NinjaScriptProperty]
        [Display(Name = "VwapMode", GroupName = "06-VWAP", Order = 0)]
        public SessionVwapMode VwapMode { get; set; }

        [NinjaScriptProperty, Range(0, 500)]
        [Display(Name = "VwapDistanceThresholdTicks", GroupName = "06-VWAP", Order = 1)]
        public int VwapDistanceThresholdTicks { get; set; }

        [NinjaScriptProperty, Range(1, 100)]
        [Display(Name = "VwapSlopeLookback", GroupName = "06-VWAP", Order = 2)]
        public int VwapSlopeLookback { get; set; }

        [NinjaScriptProperty, Range(0.0, 100.0)]
        [Display(Name = "MinVwapSlopeTicks", GroupName = "06-VWAP", Order = 3)]
        public double MinVwapSlopeTicks { get; set; }

        [NinjaScriptProperty, Range(0, 50)]
        [Display(Name = "VwapReclaimBufferTicks", GroupName = "06-VWAP", Order = 4)]
        public int VwapReclaimBufferTicks { get; set; }

        [NinjaScriptProperty, Range(0, 100)]
        [Display(Name = "VwapChopBandTicks", GroupName = "06-VWAP", Order = 5)]
        public int VwapChopBandTicks { get; set; }

        [NinjaScriptProperty, Range(1, 100)]
        [Display(Name = "VwapCrossLookback", GroupName = "06-VWAP", Order = 6)]
        public int VwapCrossLookback { get; set; }

        [NinjaScriptProperty, Range(0, 20)]
        [Display(Name = "MaxVwapCrosses", GroupName = "06-VWAP", Order = 7)]
        public int MaxVwapCrosses { get; set; }

        [NinjaScriptProperty, Range(0, 100)]
        [Display(Name = "MinEmaSpreadTicks", GroupName = "06-VWAP", Order = 8)]
        public int MinEmaSpreadTicks { get; set; }
        #endregion

        #region 07-Impulse
        [NinjaScriptProperty, Range(1, 50)]
        [Display(Name = "ImpulseLookbackBars", GroupName = "07-Impulse", Order = 0)]
        public int ImpulseLookbackBars { get; set; }

        [NinjaScriptProperty, Range(0, 500)]
        [Display(Name = "MinImpulseMoveTicks", GroupName = "07-Impulse", Order = 1)]
        public int MinImpulseMoveTicks { get; set; }

        [NinjaScriptProperty, Range(0, 500)]
        [Display(Name = "MinOpeningRangeTicks", GroupName = "07-Impulse", Order = 2)]
        public int MinOpeningRangeTicks { get; set; }

        [NinjaScriptProperty, Range(1, 1000)]
        [Display(Name = "MaxOpeningRangeTicks", GroupName = "07-Impulse", Order = 3)]
        public int MaxOpeningRangeTicks { get; set; }

        [NinjaScriptProperty, Range(0, 100)]
        [Display(Name = "OpeningRangeBreakBufferTicks", GroupName = "07-Impulse", Order = 4)]
        public int OpeningRangeBreakBufferTicks { get; set; }

        [NinjaScriptProperty, Range(1, 200)]
        [Display(Name = "MaxBarsAfterImpulse", GroupName = "07-Impulse", Order = 5)]
        public int MaxBarsAfterImpulse { get; set; }
        #endregion

        #region 08-Pullback
        [NinjaScriptProperty, Range(1, 100)]
        [Display(Name = "PullbackLookbackBars", GroupName = "08-Pullback", Order = 0)]
        public int PullbackLookbackBars { get; set; }

        [NinjaScriptProperty, Range(0, 500)]
        [Display(Name = "MinPullbackDepthTicks", GroupName = "08-Pullback", Order = 1)]
        public int MinPullbackDepthTicks { get; set; }

        [NinjaScriptProperty, Range(1, 1000)]
        [Display(Name = "MaxPullbackDepthTicks", GroupName = "08-Pullback", Order = 2)]
        public int MaxPullbackDepthTicks { get; set; }

        [NinjaScriptProperty, Range(0, 500)]
        [Display(Name = "PullbackMaxDistanceFromVwapTicks", GroupName = "08-Pullback", Order = 3)]
        public int PullbackMaxDistanceFromVwapTicks { get; set; }

        [NinjaScriptProperty, Range(0, 100)]
        [Display(Name = "PullbackTouchEmaTicks", GroupName = "08-Pullback", Order = 4)]
        public int PullbackTouchEmaTicks { get; set; }

        [NinjaScriptProperty, Range(1, 100)]
        [Display(Name = "MaxBarsAfterPullback", GroupName = "08-Pullback", Order = 5)]
        public int MaxBarsAfterPullback { get; set; }
        #endregion

        #region 09-Orderflow Optional
        [NinjaScriptProperty]
        [Display(Name = "UseDeltaFilter", GroupName = "09-Orderflow Optional", Order = 0)]
        public bool UseDeltaFilter { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "UseImbalanceFilter", GroupName = "09-Orderflow Optional", Order = 1)]
        public bool UseImbalanceFilter { get; set; }

        [NinjaScriptProperty, Range(0.0, 10.0)]
        [Display(Name = "DeltaVolumeFactor", GroupName = "09-Orderflow Optional", Order = 2)]
        public double DeltaVolumeFactor { get; set; }
        #endregion

        #region 10-Stops Targets
        [NinjaScriptProperty, Range(0.05, 5.0)]
        [Display(Name = "AtrStopMult", GroupName = "10-Stops Targets", Order = 0)]
        public double AtrStopMult { get; set; }

        [NinjaScriptProperty, Range(1, 200)]
        [Display(Name = "StopMinTicks", GroupName = "10-Stops Targets", Order = 1)]
        public int StopMinTicks { get; set; }

        [NinjaScriptProperty, Range(1, 1000)]
        [Display(Name = "StopMaxTicks", GroupName = "10-Stops Targets", Order = 2)]
        public int StopMaxTicks { get; set; }

        [NinjaScriptProperty, Range(0, 100)]
        [Display(Name = "StopBeyondPullbackTicks", GroupName = "10-Stops Targets", Order = 3)]
        public int StopBeyondPullbackTicks { get; set; }

        [NinjaScriptProperty, Range(0.1, 10.0)]
        [Display(Name = "RewardRiskRatio", GroupName = "10-Stops Targets", Order = 4)]
        public double RewardRiskRatio { get; set; }

        [NinjaScriptProperty, Range(0.0, 5.0)]
        [Display(Name = "BreakEvenTriggerR", GroupName = "10-Stops Targets", Order = 5)]
        public double BreakEvenTriggerR { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "TrailMode", GroupName = "10-Stops Targets", Order = 6)]
        public ReclaimTrailMode TrailMode { get; set; }

        [NinjaScriptProperty, Range(0.0, 10.0)]
        [Display(Name = "TrailTriggerR", GroupName = "10-Stops Targets", Order = 7)]
        public double TrailTriggerR { get; set; }

        [NinjaScriptProperty, Range(1, 100)]
        [Display(Name = "TimeStopBars", GroupName = "10-Stops Targets", Order = 8)]
        public int TimeStopBars { get; set; }

        [NinjaScriptProperty, Range(0.0, 5.0)]
        [Display(Name = "MinProgressR", GroupName = "10-Stops Targets", Order = 9)]
        public double MinProgressR { get; set; }

        [NinjaScriptProperty, Range(0, 20)]
        [Display(Name = "EntryOffsetTicks", GroupName = "10-Stops Targets", Order = 10)]
        public int EntryOffsetTicks { get; set; }

        [NinjaScriptProperty, Range(1, 20)]
        [Display(Name = "EntryTimeoutBars", GroupName = "10-Stops Targets", Order = 11)]
        public int EntryTimeoutBars { get; set; }
        #endregion

        #region 11-Risk
        [NinjaScriptProperty, Range(0.01, 10.0)]
        [Display(Name = "RiskPerTradePct", GroupName = "11-Risk", Order = 0)]
        public double RiskPerTradePct { get; set; }

        [NinjaScriptProperty, Range(1, 100)]
        [Display(Name = "UserMaxContracts", GroupName = "11-Risk", Order = 1)]
        public int UserMaxContracts { get; set; }

        [NinjaScriptProperty, Range(1, 10)]
        [Display(Name = "MaxOpenPositions", GroupName = "11-Risk", Order = 2)]
        public int MaxOpenPositions { get; set; }

        [NinjaScriptProperty, Range(0.0, 10000.0)]
        [Display(Name = "DailyLossLimit", GroupName = "11-Risk", Order = 3)]
        public double DailyLossLimit { get; set; }

        [NinjaScriptProperty, Range(0.0, 10000.0)]
        [Display(Name = "WeeklyLossLimit", GroupName = "11-Risk", Order = 4)]
        public double WeeklyLossLimit { get; set; }

        [NinjaScriptProperty, Range(1, 100)]
        [Display(Name = "MaxTradesPerDay", GroupName = "11-Risk", Order = 5)]
        public int MaxTradesPerDay { get; set; }

        [NinjaScriptProperty, Range(1, 200)]
        [Display(Name = "HardMaxTradesPerDay", GroupName = "11-Risk", Order = 6)]
        public int HardMaxTradesPerDay { get; set; }

        [NinjaScriptProperty, Range(1, 20)]
        [Display(Name = "MaxConsecutiveLosses", GroupName = "11-Risk", Order = 7)]
        public int MaxConsecutiveLosses { get; set; }

        [NinjaScriptProperty, Range(1, 20)]
        [Display(Name = "PauseAfterConsecutiveLosses", GroupName = "11-Risk", Order = 8)]
        public int PauseAfterConsecutiveLosses { get; set; }

        [NinjaScriptProperty, Range(1, 240)]
        [Display(Name = "PauseMinutesAfterLosses", GroupName = "11-Risk", Order = 9)]
        public int PauseMinutesAfterLosses { get; set; }

        [NinjaScriptProperty, Range(0.0, 100.0)]
        [Display(Name = "RoundTurnCommission", GroupName = "11-Risk", Order = 10)]
        public double RoundTurnCommission { get; set; }

        [NinjaScriptProperty, Range(0, 20)]
        [Display(Name = "SlippageTicks", GroupName = "11-Risk", Order = 11)]
        public int SlippageTicks { get; set; }
        #endregion
    }
}
