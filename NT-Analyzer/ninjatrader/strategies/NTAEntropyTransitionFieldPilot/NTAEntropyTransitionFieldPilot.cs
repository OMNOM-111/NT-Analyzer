// =============================================================================
// NTAEntropyTransitionFieldPilot
// -----------------------------------------------------------------------------
// Cross-instrument research pilot for an original signal engine.
//
// Method:
//   Each closed bar is encoded into a small discrete "market atom" built from
//   signed displacement, body balance, close location, relative participation,
//   and session clock phase. The strategy keeps a rolling empirical transition
//   book: state(now-1) -> return(now). When the current state has a statistically
//   asymmetric, low-entropy next-return field after estimated costs, it trades
//   in that direction.
//
// This is not an MA/RSI combo and does not use named chart patterns as an entry
// premise. It is a local transition-physics model with explicit entropy and cost
// gates.
// =============================================================================

#region Using declarations
using System;
using System.Collections.Generic;
using System.ComponentModel.DataAnnotations;
using NinjaTrader.Cbi;
using NinjaTrader.Data;
using NinjaTrader.NinjaScript;
using NinjaTrader.NinjaScript.Strategies;
#endregion

namespace NinjaTrader.NinjaScript.Strategies
{
    public class NTAEntropyTransitionFieldPilot : Strategy
    {
        private const int ReturnBuckets = 3;
        private const int BodyBuckets = 3;
        private const int LocationBuckets = 3;
        private const int VolumeBuckets = 3;
        private const int TimeBuckets = 4;
        private const int StateCount = ReturnBuckets * BodyBuckets * LocationBuckets * VolumeBuckets * TimeBuckets;

        private struct TransitionObservation
        {
            public int State;
            public double Ticks;
            public int Direction;
        }

        private struct Forecast
        {
            public bool Valid;
            public int Direction;
            public int Samples;
            public double MeanTicks;
            public double SigmaTicks;
            public double DirectionProbability;
            public double Entropy;
            public double EdgeScore;
        }

        private readonly Queue<TransitionObservation> _observations = new Queue<TransitionObservation>();
        private readonly Queue<TransitionObservation> _consensusObservations = new Queue<TransitionObservation>();
        private int[] _counts;
        private int[] _upCounts;
        private int[] _downCounts;
        private int[] _flatCounts;
        private double[] _sumTicks;
        private double[] _sumSqTicks;
        private int[] _consensusCounts;
        private int[] _consensusUpCounts;
        private int[] _consensusDownCounts;
        private int[] _consensusFlatCounts;
        private double[] _consensusSumTicks;
        private double[] _consensusSumSqTicks;

        private DateTime _sessionDate = DateTime.MinValue;
        private double _sessionStartCumProfit;
        private int _tradesToday;
        private int _lastObservedBar = -1;
        private int _lastEntryBar = -1000000;
        private double _lastEntryPrice;
        private int _lastStopTicks;
        private string _activeSignal = "";

        protected override void OnStateChange()
        {
            if (State == State.SetDefaults)
            {
                Name = "NTAEntropyTransitionFieldPilot";
                Description = "Cross-root research pilot: entropy-gated empirical state-transition field for next-bar signal prediction.";
                Calculate = Calculate.OnBarClose;
                EntriesPerDirection = 1;
                EntryHandling = EntryHandling.AllEntries;
                IsExitOnSessionCloseStrategy = true;
                ExitOnSessionCloseSeconds = 30;
                IsFillLimitOnTouch = false;
                MaximumBarsLookBack = MaximumBarsLookBack.Infinite;
                OrderFillResolution = OrderFillResolution.Standard;
                Slippage = 0;
                StartBehavior = StartBehavior.WaitUntilFlat;
                TimeInForce = TimeInForce.Day;
                TraceOrders = false;
                RealtimeErrorHandling = RealtimeErrorHandling.StopCancelClose;
                StopTargetHandling = StopTargetHandling.PerEntryExecution;
                BarsRequiredToTrade = 90;
                IsInstantiatedOnEachOptimizationIteration = true;

                StartingCapital = 2000.0;
                IntradayOnly = true;
                ActiveMarginPerContract = 100.0;
                MaxContractsByCapital = 20;
                InstrumentStatus = "allowed";
                MarginSourceBroker = "NinjaTrader";

                RiskPerTradePct = 1.0;
                MaxDailyLossPct = 3.0;
                MaxDailyProfitPct = 0.0;
                MaxTradesPerDay = 8;
                UserMaxContracts = 5;
                RoundTurnCommission = 1.90;
                SlippageTicks = 1;

                EnableLong = true;
                EnableShort = true;
                TradeStartTime = 600;
                TradeEndTime = 1230;
                ForceFlatTime = 1325;

                StateWindow = 260;
                MinStateSamples = 6;
                NeutralMoveTicks = 1.0;
                ReturnBucketTicks = 4.0;
                BodyBalanceThreshold = 0.25;
                VolumeLookback = 30;
                VolumeLowFactor = 0.75;
                VolumeHighFactor = 1.50;
                UseTimeState = true;
                MinForecastTicks = 2.0;
                MinDirectionalProbability = 0.58;
                MaxEntropy = 0.88;
                MinEdgeScore = 0.70;
                CostMultiple = 1.00;
                MinBarsBetweenEntries = 1;
                ShrinkageSamples = 0.0;
                UseConsensusField = false;
                ConsensusWindow = 1040;
                ConsensusMinStateSamples = 20;
                ConsensusMinDirectionalProbability = 0.58;
                ConsensusMaxEntropy = 0.92;
                ConsensusMinEdgeScore = 0.40;
                FieldMode = 0;

                MinStopTicks = 6;
                MaxStopTicks = 80;
                StopSigmaMult = 1.40;
                RewardRiskRatio = 1.25;
                MoveToBreakevenAtR = 0.80;
                TrailAfterR = 1.60;
                MaxHoldBars = 12;
            }
            else if (State == State.DataLoaded)
            {
                ResetTransitionBook();
            }
        }

        protected override void OnBarUpdate()
        {
            if (BarsInProgress != 0)
                return;

            UpdateSessionState();

            if (CurrentBar < RequiredBars())
                return;

            ObserveLatestTransition();

            int hhmm = ToTimeHHMM(Time[0]);
            if (ForceFlatTime > 0 && hhmm >= ForceFlatTime)
            {
                FlattenOpenPosition("ForceFlat");
                return;
            }

            if (Position.MarketPosition != MarketPosition.Flat)
            {
                ManageOpenPosition();
                return;
            }

            if (!CanTradeNow(hhmm))
                return;

            EvaluateEntropyFieldEntry();
        }

        private int RequiredBars()
        {
            return Math.Max(VolumeLookback + 5, 20);
        }

        private void ResetTransitionBook()
        {
            _observations.Clear();
            _consensusObservations.Clear();
            _counts = new int[StateCount];
            _upCounts = new int[StateCount];
            _downCounts = new int[StateCount];
            _flatCounts = new int[StateCount];
            _sumTicks = new double[StateCount];
            _sumSqTicks = new double[StateCount];
            _consensusCounts = new int[StateCount];
            _consensusUpCounts = new int[StateCount];
            _consensusDownCounts = new int[StateCount];
            _consensusFlatCounts = new int[StateCount];
            _consensusSumTicks = new double[StateCount];
            _consensusSumSqTicks = new double[StateCount];
            _lastObservedBar = -1;
        }

        private void UpdateSessionState()
        {
            if (_sessionDate == Time[0].Date)
                return;

            _sessionDate = Time[0].Date;
            _tradesToday = 0;
            _sessionStartCumProfit = SystemPerformance.AllTrades.TradesPerformance.Currency.CumProfit;
            _lastEntryBar = -1000000;
        }

        private void ObserveLatestTransition()
        {
            if (_lastObservedBar == CurrentBar)
                return;

            int state = EncodeState(1);
            if (state < 0 || state >= StateCount)
                return;

            double ticks = (Close[0] - Close[1]) / TickSize;
            int direction = 0;
            if (ticks > NeutralMoveTicks)
                direction = 1;
            else if (ticks < -NeutralMoveTicks)
                direction = -1;

            TransitionObservation obs = new TransitionObservation
            {
                State = state,
                Ticks = ticks,
                Direction = direction,
            };

            AddObservation(
                _observations, _counts, _upCounts, _downCounts, _flatCounts,
                _sumTicks, _sumSqTicks, obs, Math.Max(10, StateWindow));
            AddObservation(
                _consensusObservations, _consensusCounts, _consensusUpCounts,
                _consensusDownCounts, _consensusFlatCounts, _consensusSumTicks,
                _consensusSumSqTicks, obs, Math.Max(Math.Max(10, StateWindow), ConsensusWindow));
            _lastObservedBar = CurrentBar;
        }

        private void AddObservation(
            Queue<TransitionObservation> queue,
            int[] counts,
            int[] upCounts,
            int[] downCounts,
            int[] flatCounts,
            double[] sumTicks,
            double[] sumSqTicks,
            TransitionObservation obs,
            int maxWindow)
        {
            queue.Enqueue(obs);
            AddToBook(counts, upCounts, downCounts, flatCounts, sumTicks, sumSqTicks, obs, 1);
            while (queue.Count > maxWindow)
            {
                TransitionObservation old = queue.Dequeue();
                AddToBook(counts, upCounts, downCounts, flatCounts, sumTicks, sumSqTicks, old, -1);
            }
        }

        private void AddToBook(
            int[] counts,
            int[] upCounts,
            int[] downCounts,
            int[] flatCounts,
            double[] sumTicks,
            double[] sumSqTicks,
            TransitionObservation obs,
            int sign)
        {
            int state = obs.State;
            counts[state] += sign;
            sumTicks[state] += sign * obs.Ticks;
            sumSqTicks[state] += sign * obs.Ticks * obs.Ticks;
            if (obs.Direction > 0)
                upCounts[state] += sign;
            else if (obs.Direction < 0)
                downCounts[state] += sign;
            else
                flatCounts[state] += sign;
        }

        private void EvaluateEntropyFieldEntry()
        {
            if (CurrentBar - _lastEntryBar < MinBarsBetweenEntries)
                return;

            int state = EncodeState(0);
            Forecast forecast = BuildForecast(
                state, _counts, _upCounts, _downCounts, _flatCounts, _sumTicks, _sumSqTicks,
                MinStateSamples, MinDirectionalProbability, MaxEntropy, MinEdgeScore,
                MinForecastTicks, true);
            if (!forecast.Valid)
                return;

            if (UseConsensusField)
            {
                Forecast consensus = BuildForecast(
                    state, _consensusCounts, _consensusUpCounts, _consensusDownCounts,
                    _consensusFlatCounts, _consensusSumTicks, _consensusSumSqTicks,
                    ConsensusMinStateSamples, ConsensusMinDirectionalProbability,
                    ConsensusMaxEntropy, ConsensusMinEdgeScore, 0.0, false);
                if (!consensus.Valid || consensus.Direction != forecast.Direction)
                    return;
            }

            double currentTicks = (Close[0] - Close[1]) / TickSize;
            if (FieldMode == 1 && currentTicks * forecast.Direction > -NeutralMoveTicks)
                return;
            if (FieldMode == 2 && currentTicks * forecast.Direction < NeutralMoveTicks)
                return;

            if (forecast.Direction > 0 && !EnableLong)
                return;
            if (forecast.Direction < 0 && !EnableShort)
                return;

            int stopTicks = ComputeStopTicks(forecast);
            int qty = ComputeQuantity(stopTicks);
            if (qty < 1)
                return;

            int targetTicks = Math.Max(1, (int)Math.Round(stopTicks * RewardRiskRatio));
            string signal = forecast.Direction > 0 ? "EntFieldL" : "EntFieldS";
            SetStopLoss(signal, CalculationMode.Ticks, stopTicks, false);
            SetProfitTarget(signal, CalculationMode.Ticks, targetTicks);

            _lastEntryBar = CurrentBar;
            _lastEntryPrice = Close[0];
            _lastStopTicks = stopTicks;
            _activeSignal = signal;
            _tradesToday++;

            if (forecast.Direction > 0)
                EnterLong(qty, signal);
            else
                EnterShort(qty, signal);
        }

        private Forecast BuildForecast(
            int state,
            int[] counts,
            int[] upCounts,
            int[] downCounts,
            int[] flatCounts,
            double[] sumTicks,
            double[] sumSqTicks,
            int minSamples,
            double minDirectionalProbability,
            double maxEntropy,
            double minEdgeScore,
            double minForecastTicks,
            bool applyCostGate)
        {
            Forecast empty = new Forecast { Valid = false };
            if (state < 0 || state >= StateCount)
                return empty;

            int count = counts[state];
            if (count < minSamples)
                return empty;

            double shrink = Math.Max(0.0, ShrinkageSamples);
            double rawMean = sumTicks[state] / count;
            double mean = sumTicks[state] / (count + shrink);
            double variance = (sumSqTicks[state] / count) - rawMean * rawMean;
            double sigma = Math.Sqrt(Math.Max(0.000001, variance));
            int direction = mean > 0.0 ? 1 : -1;

            double up = upCounts[state] + shrink / 3.0;
            double down = downCounts[state] + shrink / 3.0;
            double flat = flatCounts[state] + shrink / 3.0;
            double total = count + shrink;
            double directionProbability = (direction > 0 ? up : down) / Math.Max(1.0, total);
            double entropy = Entropy3(up, down, flat, total);
            double edgeScore = Math.Abs(mean) * Math.Sqrt(count) / Math.Max(0.25, sigma);

            double tickValue = Instrument.MasterInstrument.PointValue * TickSize;
            double costTicks = tickValue > 0.0 ? RoundTurnCommission / tickValue + (2.0 * SlippageTicks) : 0.0;
            double requiredMean = applyCostGate ? Math.Max(minForecastTicks, costTicks * CostMultiple) : minForecastTicks;

            if (Math.Abs(mean) < requiredMean)
                return empty;
            if (directionProbability < minDirectionalProbability)
                return empty;
            if (entropy > maxEntropy)
                return empty;
            if (edgeScore < minEdgeScore)
                return empty;

            return new Forecast
            {
                Valid = true,
                Direction = direction,
                Samples = count,
                MeanTicks = mean,
                SigmaTicks = sigma,
                DirectionProbability = directionProbability,
                Entropy = entropy,
                EdgeScore = edgeScore,
            };
        }

        private double Entropy3(double up, double down, double flat, double total)
        {
            if (total <= 0)
                return 1.0;

            double entropy = 0.0;
            entropy += EntropyTerm(up, total);
            entropy += EntropyTerm(down, total);
            entropy += EntropyTerm(flat, total);
            return entropy / Math.Log(3.0);
        }

        private double EntropyTerm(double n, double total)
        {
            if (n <= 0 || total <= 0)
                return 0.0;
            double p = n / (double)total;
            return -p * Math.Log(p);
        }

        private int EncodeState(int barsAgo)
        {
            if (CurrentBar <= barsAgo + VolumeLookback + 1)
                return -1;

            double retTicks = (Close[barsAgo] - Close[barsAgo + 1]) / TickSize;
            int retBucket = retTicks > ReturnBucketTicks ? 2 : (retTicks < -ReturnBucketTicks ? 0 : 1);

            double range = High[barsAgo] - Low[barsAgo];
            int bodyBucket = 1;
            int locationBucket = 1;
            if (range > TickSize * 0.1)
            {
                double bodyBalance = (Close[barsAgo] - Open[barsAgo]) / range;
                bodyBucket = bodyBalance > BodyBalanceThreshold ? 2 : (bodyBalance < -BodyBalanceThreshold ? 0 : 1);

                double closeLocation = (Close[barsAgo] - Low[barsAgo]) / range;
                locationBucket = closeLocation > 0.66 ? 2 : (closeLocation < 0.34 ? 0 : 1);
            }

            double baselineVolume = BaselineVolume(barsAgo);
            double volumeRatio = baselineVolume > 0.0 ? Convert.ToDouble(Volume[barsAgo]) / baselineVolume : 1.0;
            int volumeBucket = volumeRatio > VolumeHighFactor ? 2 : (volumeRatio < VolumeLowFactor ? 0 : 1);

            int timeBucket = UseTimeState ? TimeBucketFor(ToTimeHHMM(Time[barsAgo])) : 0;

            return (((retBucket * BodyBuckets + bodyBucket) * LocationBuckets + locationBucket)
                    * VolumeBuckets + volumeBucket) * TimeBuckets + timeBucket;
        }

        private double BaselineVolume(int barsAgo)
        {
            int n = Math.Max(1, VolumeLookback);
            double sum = 0.0;
            int used = 0;
            for (int i = 1; i <= n; i++)
            {
                int ago = barsAgo + i;
                if (CurrentBar < ago)
                    break;
                sum += Math.Max(1.0, Convert.ToDouble(Volume[ago]));
                used++;
            }
            return used > 0 ? sum / used : Math.Max(1.0, Convert.ToDouble(Volume[barsAgo]));
        }

        private int TimeBucketFor(int hhmm)
        {
            if (hhmm < 800)
                return 0;
            if (hhmm < 1000)
                return 1;
            if (hhmm < 1200)
                return 2;
            return 3;
        }

        private bool CanTradeNow(int hhmm)
        {
            if (InstrumentStatus != null && InstrumentStatus.ToLowerInvariant() != "allowed")
                return false;
            if (StartingCapital <= 0.0 || ActiveMarginPerContract <= 0.0 || MaxContractsByCapital < 1)
                return false;
            if (hhmm < TradeStartTime || hhmm > TradeEndTime)
                return false;
            if (_tradesToday >= MaxTradesPerDay)
                return false;

            double dailyPnl = SystemPerformance.AllTrades.TradesPerformance.Currency.CumProfit - _sessionStartCumProfit;
            if (MaxDailyLossPct > 0.0 && dailyPnl <= -StartingCapital * MaxDailyLossPct / 100.0)
                return false;
            if (MaxDailyProfitPct > 0.0 && dailyPnl >= StartingCapital * MaxDailyProfitPct / 100.0)
                return false;

            return true;
        }

        private int ComputeStopTicks(Forecast forecast)
        {
            double raw = forecast.SigmaTicks * StopSigmaMult + Math.Abs(forecast.MeanTicks) * 0.25;
            int stopTicks = (int)Math.Round(raw);
            stopTicks = Math.Max(MinStopTicks, stopTicks);
            stopTicks = Math.Min(MaxStopTicks, stopTicks);
            return Math.Max(1, stopTicks);
        }

        private int ComputeQuantity(int stopTicks)
        {
            double tickValue = Instrument.MasterInstrument.PointValue * TickSize;
            if (tickValue <= 0.0 || stopTicks < 1)
                return 0;

            double riskDollars = StartingCapital * RiskPerTradePct / 100.0;
            int byRisk = Math.Max(1, (int)Math.Floor(riskDollars / (stopTicks * tickValue)));
            int byMargin = ActiveMarginPerContract > 0.0
                ? Math.Max(1, (int)Math.Floor(StartingCapital / ActiveMarginPerContract))
                : 1;
            int cap = Math.Max(1, Math.Min(UserMaxContracts, Math.Min(MaxContractsByCapital, byMargin)));
            return Math.Max(1, Math.Min(byRisk, cap));
        }

        private void ManageOpenPosition()
        {
            if (_lastEntryBar >= 0 && MaxHoldBars > 0 && CurrentBar - _lastEntryBar >= MaxHoldBars)
            {
                FlattenOpenPosition("TimeExit");
                return;
            }

            if (_lastStopTicks <= 0 || _lastEntryPrice <= 0.0)
                return;

            double rDist = _lastStopTicks * TickSize;
            double moved = Close[0] - _lastEntryPrice;
            double rMult = Position.MarketPosition == MarketPosition.Long ? moved / rDist : -moved / rDist;

            if (rMult >= MoveToBreakevenAtR)
                SetStopLoss(_activeSignal, CalculationMode.Price, _lastEntryPrice, false);

            if (rMult >= TrailAfterR)
            {
                double trailDist = Math.Max(1.0, _lastStopTicks / 2.0) * TickSize;
                if (Position.MarketPosition == MarketPosition.Long)
                {
                    double trail = Close[0] - trailDist;
                    if (trail > _lastEntryPrice)
                        SetStopLoss(_activeSignal, CalculationMode.Price, trail, false);
                }
                else if (Position.MarketPosition == MarketPosition.Short)
                {
                    double trail = Close[0] + trailDist;
                    if (trail < _lastEntryPrice)
                        SetStopLoss(_activeSignal, CalculationMode.Price, trail, false);
                }
            }
        }

        private void FlattenOpenPosition(string label)
        {
            if (Position.MarketPosition == MarketPosition.Long)
                ExitLong(label, _activeSignal);
            else if (Position.MarketPosition == MarketPosition.Short)
                ExitShort(label, _activeSignal);
        }

        private int ToTimeHHMM(DateTime t)
        {
            return t.Hour * 100 + t.Minute;
        }

        #region Properties
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

        [NinjaScriptProperty, Range(0.01, 10.0)]
        [Display(Name = "RiskPerTradePct", GroupName = "02-Risk", Order = 0)]
        public double RiskPerTradePct { get; set; }

        [NinjaScriptProperty, Range(0.1, 50.0)]
        [Display(Name = "MaxDailyLossPct", GroupName = "02-Risk", Order = 1)]
        public double MaxDailyLossPct { get; set; }

        [NinjaScriptProperty, Range(0.0, 100.0)]
        [Display(Name = "MaxDailyProfitPct", GroupName = "02-Risk", Order = 2)]
        public double MaxDailyProfitPct { get; set; }

        [NinjaScriptProperty, Range(1, 50)]
        [Display(Name = "MaxTradesPerDay", GroupName = "02-Risk", Order = 3)]
        public int MaxTradesPerDay { get; set; }

        [NinjaScriptProperty, Range(1, 100)]
        [Display(Name = "UserMaxContracts", GroupName = "02-Risk", Order = 4)]
        public int UserMaxContracts { get; set; }

        [NinjaScriptProperty, Range(0.0, 100.0)]
        [Display(Name = "RoundTurnCommission", GroupName = "02-Risk", Order = 5)]
        public double RoundTurnCommission { get; set; }

        [NinjaScriptProperty, Range(0, 20)]
        [Display(Name = "SlippageTicks", GroupName = "02-Risk", Order = 6)]
        public int SlippageTicks { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "EnableLong", GroupName = "03-Direction", Order = 0)]
        public bool EnableLong { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "EnableShort", GroupName = "03-Direction", Order = 1)]
        public bool EnableShort { get; set; }

        [NinjaScriptProperty, Range(0, 2359)]
        [Display(Name = "TradeStartTime", GroupName = "04-Time", Order = 0)]
        public int TradeStartTime { get; set; }

        [NinjaScriptProperty, Range(0, 2359)]
        [Display(Name = "TradeEndTime", GroupName = "04-Time", Order = 1)]
        public int TradeEndTime { get; set; }

        [NinjaScriptProperty, Range(0, 2359)]
        [Display(Name = "ForceFlatTime", GroupName = "04-Time", Order = 2)]
        public int ForceFlatTime { get; set; }

        [NinjaScriptProperty, Range(20, 10000)]
        [Display(Name = "StateWindow", GroupName = "05-Transition Field", Order = 0)]
        public int StateWindow { get; set; }

        [NinjaScriptProperty, Range(2, 200)]
        [Display(Name = "MinStateSamples", GroupName = "05-Transition Field", Order = 1)]
        public int MinStateSamples { get; set; }

        [NinjaScriptProperty, Range(0.0, 20.0)]
        [Display(Name = "NeutralMoveTicks", GroupName = "05-Transition Field", Order = 2)]
        public double NeutralMoveTicks { get; set; }

        [NinjaScriptProperty, Range(0.25, 1000.0)]
        [Display(Name = "ReturnBucketTicks", GroupName = "05-Transition Field", Order = 3)]
        public double ReturnBucketTicks { get; set; }

        [NinjaScriptProperty, Range(0.01, 0.95)]
        [Display(Name = "BodyBalanceThreshold", GroupName = "05-Transition Field", Order = 4)]
        public double BodyBalanceThreshold { get; set; }

        [NinjaScriptProperty, Range(2, 500)]
        [Display(Name = "VolumeLookback", GroupName = "05-Transition Field", Order = 5)]
        public int VolumeLookback { get; set; }

        [NinjaScriptProperty, Range(0.05, 5.0)]
        [Display(Name = "VolumeLowFactor", GroupName = "05-Transition Field", Order = 6)]
        public double VolumeLowFactor { get; set; }

        [NinjaScriptProperty, Range(0.05, 20.0)]
        [Display(Name = "VolumeHighFactor", GroupName = "05-Transition Field", Order = 7)]
        public double VolumeHighFactor { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "UseTimeState", GroupName = "05-Transition Field", Order = 8)]
        public bool UseTimeState { get; set; }

        [NinjaScriptProperty, Range(0.0, 1000.0)]
        [Display(Name = "MinForecastTicks", GroupName = "06-Forecast Gate", Order = 0)]
        public double MinForecastTicks { get; set; }

        [NinjaScriptProperty, Range(0.0, 1.0)]
        [Display(Name = "MinDirectionalProbability", GroupName = "06-Forecast Gate", Order = 1)]
        public double MinDirectionalProbability { get; set; }

        [NinjaScriptProperty, Range(0.0, 1.0)]
        [Display(Name = "MaxEntropy", GroupName = "06-Forecast Gate", Order = 2)]
        public double MaxEntropy { get; set; }

        [NinjaScriptProperty, Range(0.0, 50.0)]
        [Display(Name = "MinEdgeScore", GroupName = "06-Forecast Gate", Order = 3)]
        public double MinEdgeScore { get; set; }

        [NinjaScriptProperty, Range(0.0, 20.0)]
        [Display(Name = "CostMultiple", GroupName = "06-Forecast Gate", Order = 4)]
        public double CostMultiple { get; set; }

        [NinjaScriptProperty, Range(0, 100)]
        [Display(Name = "MinBarsBetweenEntries", GroupName = "06-Forecast Gate", Order = 5)]
        public int MinBarsBetweenEntries { get; set; }

        [NinjaScriptProperty, Range(0.0, 200.0)]
        [Display(Name = "ShrinkageSamples", GroupName = "06-Forecast Gate", Order = 6)]
        public double ShrinkageSamples { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "UseConsensusField", GroupName = "06-Forecast Gate", Order = 7)]
        public bool UseConsensusField { get; set; }

        [NinjaScriptProperty, Range(20, 20000)]
        [Display(Name = "ConsensusWindow", GroupName = "06-Forecast Gate", Order = 8)]
        public int ConsensusWindow { get; set; }

        [NinjaScriptProperty, Range(2, 500)]
        [Display(Name = "ConsensusMinStateSamples", GroupName = "06-Forecast Gate", Order = 9)]
        public int ConsensusMinStateSamples { get; set; }

        [NinjaScriptProperty, Range(0.0, 1.0)]
        [Display(Name = "ConsensusMinDirectionalProbability", GroupName = "06-Forecast Gate", Order = 10)]
        public double ConsensusMinDirectionalProbability { get; set; }

        [NinjaScriptProperty, Range(0.0, 1.0)]
        [Display(Name = "ConsensusMaxEntropy", GroupName = "06-Forecast Gate", Order = 11)]
        public double ConsensusMaxEntropy { get; set; }

        [NinjaScriptProperty, Range(0.0, 50.0)]
        [Display(Name = "ConsensusMinEdgeScore", GroupName = "06-Forecast Gate", Order = 12)]
        public double ConsensusMinEdgeScore { get; set; }

        [NinjaScriptProperty, Range(0, 2)]
        [Display(Name = "FieldMode", GroupName = "06-Forecast Gate", Order = 13)]
        public int FieldMode { get; set; }

        [NinjaScriptProperty, Range(1, 1000)]
        [Display(Name = "MinStopTicks", GroupName = "07-Exits", Order = 0)]
        public int MinStopTicks { get; set; }

        [NinjaScriptProperty, Range(1, 5000)]
        [Display(Name = "MaxStopTicks", GroupName = "07-Exits", Order = 1)]
        public int MaxStopTicks { get; set; }

        [NinjaScriptProperty, Range(0.1, 20.0)]
        [Display(Name = "StopSigmaMult", GroupName = "07-Exits", Order = 2)]
        public double StopSigmaMult { get; set; }

        [NinjaScriptProperty, Range(0.1, 20.0)]
        [Display(Name = "RewardRiskRatio", GroupName = "07-Exits", Order = 3)]
        public double RewardRiskRatio { get; set; }

        [NinjaScriptProperty, Range(0.0, 10.0)]
        [Display(Name = "MoveToBreakevenAtR", GroupName = "07-Exits", Order = 4)]
        public double MoveToBreakevenAtR { get; set; }

        [NinjaScriptProperty, Range(0.0, 20.0)]
        [Display(Name = "TrailAfterR", GroupName = "07-Exits", Order = 5)]
        public double TrailAfterR { get; set; }

        [NinjaScriptProperty, Range(1, 200)]
        [Display(Name = "MaxHoldBars", GroupName = "07-Exits", Order = 6)]
        public int MaxHoldBars { get; set; }
        #endregion
    }
}
