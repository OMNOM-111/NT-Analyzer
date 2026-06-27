// =============================================================================
// NTAGeodesicPhasePressurePilot
// -----------------------------------------------------------------------------
// Cross-instrument research pilot for an original signal engine.
//
// Method:
//   Treat the last bars as a path through a compact 3D phase space:
//     x = normalized signed price displacement
//     y = normalized bar body balance
//     z = capped log participation pressure
//
//   Consecutive triples of phase vectors create a local torsion field. The
//   strategy projects that field back onto the price axis and trades only when
//   the path spent enough energy, moved inefficiently, and produced a coherent
//   phase-pressure forecast that clears explicit transaction-cost hurdles.
//
// This is not an MA/RSI combo and does not use named chart patterns as the entry
// premise. It is a discrete path-geometry model with after-cost gates and a
// conservative intraday risk shell.
// =============================================================================

#region Using declarations
using System;
using System.ComponentModel.DataAnnotations;
using NinjaTrader.Cbi;
using NinjaTrader.Data;
using NinjaTrader.NinjaScript;
using NinjaTrader.NinjaScript.Strategies;
#endregion

namespace NinjaTrader.NinjaScript.Strategies
{
    public class NTAGeodesicPhasePressurePilot : Strategy
    {
        private struct PhaseForecast
        {
            public bool Valid;
            public int Direction;
            public double Pressure;
            public double AbsPressure;
            public double Coherence;
            public double ArcTicks;
            public double NetTicks;
            public double Inefficiency;
            public double AverageAbsTicks;
            public double ForecastTicks;
        }

        private DateTime _sessionDate = DateTime.MinValue;
        private int _weekKey = -1;
        private double _sessionStartCumProfit;
        private double _weekStartCumProfit;
        private double _peakCumProfit;
        private int _tradesToday;
        private int _lastEntryBar = -1000000;
        private double _lastEntryPrice;
        private int _lastStopTicks;
        private string _activeSignal = "";

        protected override void OnStateChange()
        {
            if (State == State.SetDefaults)
            {
                Name = "NTAGeodesicPhasePressurePilot";
                Description = "Cross-root research pilot: discrete path-geodesic phase-pressure forecast with transaction-cost gates.";
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
                BarsRequiredToTrade = 120;
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
                MaxWeeklyLossPct = 6.0;
                MaxStrategyDrawdownPct = 15.0;
                MaxTradesPerDay = 8;
                UserMaxContracts = 5;
                RoundTurnCommission = 1.90;
                SlippageTicks = 1;

                EnableLong = true;
                EnableShort = true;
                TradeStartTime = 600;
                TradeEndTime = 1230;
                ForceFlatTime = 1325;

                PhaseLookback = 14;
                ParticipationLookback = 34;
                ReturnScaleTicks = 8.0;
                VolumeLogCap = 1.75;
                TorsionDecay = 0.86;
                InertiaBlend = 0.35;
                MinArcTicks = 24.0;
                MinPathInefficiency = 1.90;
                MinPhasePressure = 0.45;
                MinPressureCoherence = 0.24;
                MinNetTicks = 0.0;
                MinForecastTicks = 2.0;
                PressureToForecastTicks = 9.0;
                CostMultiple = 1.00;
                PolarityMode = 0;
                MinBarsBetweenEntries = 2;

                MinStopTicks = 6;
                MaxStopTicks = 120;
                StopEnergyMult = 1.65;
                RewardRiskRatio = 1.20;
                MoveToBreakevenAtR = 0.90;
                TrailAfterR = 1.80;
                MaxHoldBars = 14;
            }
        }

        protected override void OnBarUpdate()
        {
            if (BarsInProgress != 0)
                return;

            UpdateSessionState();

            if (CurrentBar < RequiredBars())
                return;

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

            EvaluatePhasePressureEntry();
        }

        private int RequiredBars()
        {
            int phase = Math.Max(4, PhaseLookback) + 4;
            int participation = Math.Max(5, ParticipationLookback) + Math.Max(4, PhaseLookback) + 4;
            return Math.Max(phase, participation);
        }

        private void UpdateSessionState()
        {
            if (_sessionDate == Time[0].Date)
            {
                UpdatePeakProfit();
                return;
            }

            _sessionDate = Time[0].Date;
            _tradesToday = 0;
            _sessionStartCumProfit = SystemPerformance.AllTrades.TradesPerformance.Currency.CumProfit;
            _lastEntryBar = -1000000;
            UpdateWeekState();
            UpdatePeakProfit();
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
            if (CurrentBar - _lastEntryBar < MinBarsBetweenEntries)
                return false;

            double dailyPnl = SystemPerformance.AllTrades.TradesPerformance.Currency.CumProfit - _sessionStartCumProfit;
            if (MaxDailyLossPct > 0.0 && dailyPnl <= -StartingCapital * MaxDailyLossPct / 100.0)
                return false;
            if (MaxDailyProfitPct > 0.0 && dailyPnl >= StartingCapital * MaxDailyProfitPct / 100.0)
                return false;

            double weeklyPnl = SystemPerformance.AllTrades.TradesPerformance.Currency.CumProfit - _weekStartCumProfit;
            if (MaxWeeklyLossPct > 0.0 && weeklyPnl <= -StartingCapital * MaxWeeklyLossPct / 100.0)
                return false;

            double strategyDrawdown = SystemPerformance.AllTrades.TradesPerformance.Currency.CumProfit - _peakCumProfit;
            if (MaxStrategyDrawdownPct > 0.0 && strategyDrawdown <= -StartingCapital * MaxStrategyDrawdownPct / 100.0)
                return false;

            return true;
        }

        private void UpdateWeekState()
        {
            int key = Time[0].Year * 1000 + (Time[0].DayOfYear / 7);
            if (_weekKey == key)
                return;

            _weekKey = key;
            _weekStartCumProfit = SystemPerformance.AllTrades.TradesPerformance.Currency.CumProfit;
        }

        private void UpdatePeakProfit()
        {
            double cumProfit = SystemPerformance.AllTrades.TradesPerformance.Currency.CumProfit;
            if (cumProfit > _peakCumProfit)
                _peakCumProfit = cumProfit;
        }

        private void EvaluatePhasePressureEntry()
        {
            PhaseForecast forecast = BuildPhaseForecast();
            if (!forecast.Valid)
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
            double entryPrice = Close[0];

            if (forecast.Direction > 0)
            {
                string signal = TelemetrySignal("Long");
                SetStopLoss(signal, CalculationMode.Price, entryPrice - stopTicks * TickSize, false);
                SetProfitTarget(signal, CalculationMode.Price, entryPrice + targetTicks * TickSize);
                TrackEntry(signal, entryPrice, stopTicks);
                EnterLong(qty, signal);
            }
            else
            {
                string signal = TelemetrySignal("Short");
                SetStopLoss(signal, CalculationMode.Price, entryPrice + stopTicks * TickSize, false);
                SetProfitTarget(signal, CalculationMode.Price, entryPrice - targetTicks * TickSize);
                TrackEntry(signal, entryPrice, stopTicks);
                EnterShort(qty, signal);
            }
        }

        private void TrackEntry(string signal, double entryPrice, int stopTicks)
        {
            _activeSignal = signal;
            _lastEntryPrice = entryPrice;
            _lastStopTicks = stopTicks;
            _lastEntryBar = CurrentBar;
            _tradesToday++;
        }

        private PhaseForecast BuildPhaseForecast()
        {
            PhaseForecast empty = new PhaseForecast { Valid = false };
            int lookback = Math.Max(4, PhaseLookback);
            if (CurrentBar < lookback + ParticipationLookback + 4)
                return empty;

            double pressure = 0.0;
            double absPressure = 0.0;
            double arcTicks = 0.0;
            double netTicks = 0.0;
            double absTickSum = 0.0;

            for (int i = 1; i <= lookback; i++)
            {
                double ret = (Close[i] - Close[i + 1]) / TickSize;
                arcTicks += Math.Abs(ret);
                netTicks += ret;
                absTickSum += Math.Abs(ret);

                double x0, y0, z0;
                double x1, y1, z1;
                double x2, y2, z2;
                PhaseVector(i, out x0, out y0, out z0);
                PhaseVector(i + 1, out x1, out y1, out z1);
                PhaseVector(i + 2, out x2, out y2, out z2);

                double crossX = y1 * z2 - z1 * y2;
                double crossY = z1 * x2 - x1 * z2;
                double crossZ = x1 * y2 - y1 * x2;
                double triple = x0 * crossX + y0 * crossY + z0 * crossZ;

                double handedness = triple >= 0.0 ? 1.0 : -1.0;
                double inertia = (x0 - x1) * Math.Abs(crossZ);
                double samplePressure = crossX * handedness + InertiaBlend * inertia;
                double weight = Math.Pow(Math.Max(0.1, Math.Min(1.0, TorsionDecay)), i - 1);

                pressure += weight * samplePressure;
                absPressure += weight * Math.Abs(samplePressure);
            }

            double coherence = absPressure > 0.000001 ? Math.Abs(pressure) / absPressure : 0.0;
            double inefficiency = arcTicks / Math.Max(1.0, Math.Abs(netTicks));
            double averageAbsTicks = absTickSum / Math.Max(1, lookback);

            if (arcTicks < MinArcTicks)
                return empty;
            if (inefficiency < MinPathInefficiency)
                return empty;
            if (Math.Abs(pressure) < MinPhasePressure)
                return empty;
            if (coherence < MinPressureCoherence)
                return empty;
            if (Math.Abs(netTicks) < MinNetTicks)
                return empty;

            int pressureDirection = pressure > 0.0 ? 1 : -1;
            int direction = ResolveDirection(pressureDirection, netTicks);
            if (direction == 0)
                return empty;

            double forecastTicks = Math.Abs(pressure) * PressureToForecastTicks;
            double requiredTicks = RequiredForecastTicks();
            if (forecastTicks < Math.Max(MinForecastTicks, requiredTicks))
                return empty;

            return new PhaseForecast
            {
                Valid = true,
                Direction = direction,
                Pressure = pressure,
                AbsPressure = absPressure,
                Coherence = coherence,
                ArcTicks = arcTicks,
                NetTicks = netTicks,
                Inefficiency = inefficiency,
                AverageAbsTicks = averageAbsTicks,
                ForecastTicks = forecastTicks,
            };
        }

        private int ResolveDirection(int pressureDirection, double netTicks)
        {
            int netDirection = netTicks > 0.0 ? 1 : (netTicks < 0.0 ? -1 : 0);

            if (PolarityMode == 1)
                return netDirection == 0 ? 0 : -netDirection;

            if (PolarityMode == 2)
            {
                if (netDirection == 0 || netDirection != pressureDirection)
                    return 0;
                return pressureDirection;
            }

            if (PolarityMode == 3)
            {
                if (netDirection == 0 || netDirection == pressureDirection)
                    return 0;
                return pressureDirection;
            }

            return pressureDirection;
        }

        private double RequiredForecastTicks()
        {
            double tickValue = Instrument.MasterInstrument.PointValue * TickSize;
            if (tickValue <= 0.0)
                return MinForecastTicks;

            double costTicks = RoundTurnCommission / tickValue + 2.0 * SlippageTicks;
            return costTicks * CostMultiple;
        }

        private void PhaseVector(int barsAgo, out double x, out double y, out double z)
        {
            double retTicks = (Close[barsAgo] - Close[barsAgo + 1]) / TickSize;
            x = Clamp(retTicks / Math.Max(0.25, ReturnScaleTicks), -3.0, 3.0);

            double range = High[barsAgo] - Low[barsAgo];
            if (range > TickSize * 0.1)
                y = Clamp((Close[barsAgo] - Open[barsAgo]) / range, -1.0, 1.0);
            else
                y = 0.0;

            double baselineVolume = BaselineVolume(barsAgo);
            double ratio = baselineVolume > 0.0 ? Convert.ToDouble(Volume[barsAgo]) / baselineVolume : 1.0;
            ratio = Math.Max(0.05, ratio);
            z = Clamp(Math.Log(ratio), -VolumeLogCap, VolumeLogCap);
        }

        private double BaselineVolume(int barsAgo)
        {
            int n = Math.Max(1, ParticipationLookback);
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

        private int ComputeStopTicks(PhaseForecast forecast)
        {
            double raw = forecast.AverageAbsTicks * StopEnergyMult + forecast.ForecastTicks * 0.20;
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
            double contractRisk = stopTicks * tickValue
                + RoundTurnCommission
                + SlippageTicks * tickValue;
            if (riskDollars <= 0.0 || contractRisk <= 0.0)
                return 0;

            int byRisk = (int)Math.Floor(riskDollars / contractRisk);
            int byMargin = ActiveMarginPerContract > 0.0
                ? (int)Math.Floor(StartingCapital / ActiveMarginPerContract)
                : MaxContractsByCapital;
            int cap = Math.Min(UserMaxContracts, Math.Min(MaxContractsByCapital, byMargin));
            return Math.Max(0, Math.Min(byRisk, cap));
        }

        private string TelemetrySignal(string side)
        {
            return GetType().Name + "." + side;
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

        private double Clamp(double value, double min, double max)
        {
            if (value < min)
                return min;
            if (value > max)
                return max;
            return value;
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

        [NinjaScriptProperty, Range(0.0, 100.0)]
        [Display(Name = "MaxWeeklyLossPct", GroupName = "02-Risk", Order = 3)]
        public double MaxWeeklyLossPct { get; set; }

        [NinjaScriptProperty, Range(0.0, 100.0)]
        [Display(Name = "MaxStrategyDrawdownPct", GroupName = "02-Risk", Order = 4)]
        public double MaxStrategyDrawdownPct { get; set; }

        [NinjaScriptProperty, Range(1, 50)]
        [Display(Name = "MaxTradesPerDay", GroupName = "02-Risk", Order = 5)]
        public int MaxTradesPerDay { get; set; }

        [NinjaScriptProperty, Range(1, 100)]
        [Display(Name = "UserMaxContracts", GroupName = "02-Risk", Order = 6)]
        public int UserMaxContracts { get; set; }

        [NinjaScriptProperty, Range(0.0, 100.0)]
        [Display(Name = "RoundTurnCommission", GroupName = "02-Risk", Order = 7)]
        public double RoundTurnCommission { get; set; }

        [NinjaScriptProperty, Range(0, 20)]
        [Display(Name = "SlippageTicks", GroupName = "02-Risk", Order = 8)]
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

        [NinjaScriptProperty, Range(4, 200)]
        [Display(Name = "PhaseLookback", GroupName = "05-Geodesic Phase", Order = 0)]
        public int PhaseLookback { get; set; }

        [NinjaScriptProperty, Range(5, 500)]
        [Display(Name = "ParticipationLookback", GroupName = "05-Geodesic Phase", Order = 1)]
        public int ParticipationLookback { get; set; }

        [NinjaScriptProperty, Range(0.25, 1000.0)]
        [Display(Name = "ReturnScaleTicks", GroupName = "05-Geodesic Phase", Order = 2)]
        public double ReturnScaleTicks { get; set; }

        [NinjaScriptProperty, Range(0.10, 10.0)]
        [Display(Name = "VolumeLogCap", GroupName = "05-Geodesic Phase", Order = 3)]
        public double VolumeLogCap { get; set; }

        [NinjaScriptProperty, Range(0.10, 1.0)]
        [Display(Name = "TorsionDecay", GroupName = "05-Geodesic Phase", Order = 4)]
        public double TorsionDecay { get; set; }

        [NinjaScriptProperty, Range(0.0, 5.0)]
        [Display(Name = "InertiaBlend", GroupName = "05-Geodesic Phase", Order = 5)]
        public double InertiaBlend { get; set; }

        [NinjaScriptProperty, Range(1.0, 10000.0)]
        [Display(Name = "MinArcTicks", GroupName = "06-Pressure Gate", Order = 0)]
        public double MinArcTicks { get; set; }

        [NinjaScriptProperty, Range(1.0, 100.0)]
        [Display(Name = "MinPathInefficiency", GroupName = "06-Pressure Gate", Order = 1)]
        public double MinPathInefficiency { get; set; }

        [NinjaScriptProperty, Range(0.0, 100.0)]
        [Display(Name = "MinPhasePressure", GroupName = "06-Pressure Gate", Order = 2)]
        public double MinPhasePressure { get; set; }

        [NinjaScriptProperty, Range(0.0, 1.0)]
        [Display(Name = "MinPressureCoherence", GroupName = "06-Pressure Gate", Order = 3)]
        public double MinPressureCoherence { get; set; }

        [NinjaScriptProperty, Range(0.0, 10000.0)]
        [Display(Name = "MinNetTicks", GroupName = "06-Pressure Gate", Order = 4)]
        public double MinNetTicks { get; set; }

        [NinjaScriptProperty, Range(0.0, 1000.0)]
        [Display(Name = "MinForecastTicks", GroupName = "06-Pressure Gate", Order = 5)]
        public double MinForecastTicks { get; set; }

        [NinjaScriptProperty, Range(0.10, 1000.0)]
        [Display(Name = "PressureToForecastTicks", GroupName = "06-Pressure Gate", Order = 6)]
        public double PressureToForecastTicks { get; set; }

        [NinjaScriptProperty, Range(0.0, 20.0)]
        [Display(Name = "CostMultiple", GroupName = "06-Pressure Gate", Order = 7)]
        public double CostMultiple { get; set; }

        [NinjaScriptProperty, Range(0, 3)]
        [Display(Name = "PolarityMode", GroupName = "06-Pressure Gate", Order = 8)]
        public int PolarityMode { get; set; }

        [NinjaScriptProperty, Range(0, 100)]
        [Display(Name = "MinBarsBetweenEntries", GroupName = "06-Pressure Gate", Order = 9)]
        public int MinBarsBetweenEntries { get; set; }

        [NinjaScriptProperty, Range(1, 1000)]
        [Display(Name = "MinStopTicks", GroupName = "07-Exits", Order = 0)]
        public int MinStopTicks { get; set; }

        [NinjaScriptProperty, Range(1, 5000)]
        [Display(Name = "MaxStopTicks", GroupName = "07-Exits", Order = 1)]
        public int MaxStopTicks { get; set; }

        [NinjaScriptProperty, Range(0.10, 20.0)]
        [Display(Name = "StopEnergyMult", GroupName = "07-Exits", Order = 2)]
        public double StopEnergyMult { get; set; }

        [NinjaScriptProperty, Range(0.10, 20.0)]
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
