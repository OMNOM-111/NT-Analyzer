// =============================================================================
// NTAMnqSessionEdgeEngineC020
// -----------------------------------------------------------------------------
// Standalone MNQ multi-family research engine for an EMPTY MNQ slot (CELL-020).
// ONE class, several genuinely different entry families selectable by `Mode`,
// so the whole search ladder can be explored with a single NinjaTrader restart.
//
// This class does NOT inherit NTAMicroMnqScalpPilot and is NOT a clone of the
// C011-C018 1m scalp logic, nor of the rejected C019 compression-breakout family
// (the compression engine is intentionally excluded here). Every family below is
// designed to live multiple bars and does NOT depend on same-bar stop/target
// ordering.
//
// Daily anchor range:
//   During [RangeStartTime, RangeEndTime] (PT clock, within a single calendar
//   day) the engine records the session high/low = the "anchor range". After
//   RangeEndTime the range is locked and used as structural support/resistance.
//
// Families (Mode):
//   1. "OrRangeReclaim"  - Overnight/pre-session RANGE reclaim CONTINUATION.
//        A bar closes through the locked anchor edge (fresh cross) in trend
//        direction -> continuation breakout of a time-defined range.
//   2. "FailedBreak"     - FAILED breakout REVERSAL.
//        Price first extends beyond an anchor edge, then a later bar closes
//        back inside by FailReturnTicks -> fade back into the range.
//   3. "VwapPullback"    - VWAP pullback CONTINUATION.
//        In an EMA-stacked trend, price pulls back to session VWAP and the bar
//        closes back through it in trend direction -> trend resumption.
//   4. "RangeReject"     - Previous/anchor high-low REJECTION.
//        A bar wicks into an anchor edge but closes rejected by RejectWickTicks
//        -> fade the level (no prior breakout required; pure wick rejection).
//   5. "EmaPullback"     - EMA-stack trend pullback CONTINUATION.
//        In a stacked EMA trend, price pulls back to the mid EMA and closes
//        back through it in trend direction (no anchor range required).
//   6. "OpenDrive"       - OPEN-DRIVE continuation.
//        The first DriveTicks push after the trade window opens defines the
//        drive direction; resume on the first pullback to the fast EMA.
//   7. "PrevDayBreak"    - PREVIOUS-SESSION high/low breakout CONTINUATION.
//        A fresh close beyond the prior full-session high/low -> continuation.
//   8. "PrevDayReject"   - PREVIOUS-SESSION high/low REJECTION.
//        A wick into the prior full-session high/low that closes rejected.
//   9. "HeadAndShoulders" - RIGHT-SHOULDER reversal with RSI divergence.
//        Bearish H&S shorts from the right shoulder toward the neckline with a
//        stop above the head. Inverse H&S mirrors the same logic for longs.
//
// Shared shell (reused, proven): real $2000 risk profile, intraday-only,
// MaxDailyLossUsd / MaxWeeklyLossUsd / MaxTradesPerDay / HardMaxTradesPerDay /
// ForceFlatTime, ATR-aware stop geometry, breakeven + optional trail + time
// stop, quantity sizing with a single-micro floor (UserMaxContracts caps it).
// =============================================================================

#region Using declarations
using System;
using System.ComponentModel.DataAnnotations;
using NinjaTrader.Cbi;
using NinjaTrader.NinjaScript;
using NinjaTrader.NinjaScript.Indicators;
using NinjaTrader.NinjaScript.Strategies;
#endregion

namespace NinjaTrader.NinjaScript.Strategies
{
    public class NTAMnqSessionEdgeEngineC020 : Strategy
    {
        private EMA _emaFast;
        private EMA _emaMid;
        private EMA _emaSlow;
        private ATR _atr;
        private SMA _volumeSma;
        private RSI _rsi;
        private Series<double> _vwapSeries;

        private DateTime _sessionDate = DateTime.MinValue;
        private double _vwapCumPV;
        private double _vwapCumVol;

        // Daily anchor-range state.
        private double _anchorHigh;
        private double _anchorLow;
        private bool _anchorValid;
        private bool _pokedAbove;
        private bool _pokedBelow;

        // Prior-session extremes (full session H/L of the previous day).
        private double _curSessHigh = double.MinValue;
        private double _curSessLow = double.MaxValue;
        private double _prevSessHigh;
        private double _prevSessLow;
        private bool _prevSessValid;

        // Open-drive state (first directional push after the trade window opens).
        private double _windowOpenPrice;
        private bool _windowOpenSet;
        private int _driveDir;

        private DateTime _weekStartDate = DateTime.MinValue;
        private double _cumulativeRealizedPnl;
        private double _sessionRealizedPnl;
        private double _weeklyRealizedPnl;
        private int _tradesToday;
        private int _consecutiveLosses;
        private int _lastProcessedTradeCount;
        private DateTime _pauseUntil = DateTime.MinValue;
        private bool _permanentlyStopped;
        private bool _sessionStopped;

        private string _activeSignal = "";
        private int _lastEntryBar = -1;
        private double _lastEntryPrice;
        private int _lastStopTicks;
        private bool _stopMovedToBreakeven;
        private double _bestFavorableTicks;
        private bool _patternTargetActive;
        private bool _patternTargetIsLong;
        private double _patternTargetPrice;

        protected override void OnStateChange()
        {
            if (State == State.SetDefaults)
            {
                Description = "MNQ multi-family Research Hub engine (session edge + HeadAndShoulders mode).";
                Name = "Session Edge Engine MNQ v1 c020";
                Calculate = Calculate.OnBarClose;
                EntriesPerDirection = 1;
                EntryHandling = EntryHandling.AllEntries;
                IsExitOnSessionCloseStrategy = true;
                ExitOnSessionCloseSeconds = 30;
                IsFillLimitOnTouch = false;
                MaximumBarsLookBack = MaximumBarsLookBack.TwoHundredFiftySix;
                OrderFillResolution = OrderFillResolution.Standard;
                Slippage = 0;
                StartBehavior = StartBehavior.WaitUntilFlat;
                TimeInForce = TimeInForce.Day;
                TraceOrders = false;
                RealtimeErrorHandling = RealtimeErrorHandling.StopCancelClose;
                StopTargetHandling = StopTargetHandling.PerEntryExecution;
                BarsRequiredToTrade = 30;
                IsInstantiatedOnEachOptimizationIteration = true;

                InstrumentName = "MNQ";
                ContractName = "MNQ 06-26";
                SessionTemplateName = "CME US Index Futures ETH";
                BaseTimeframeSeconds = 300;

                StartingCapital = 2000.0;
                IntradayOnly = true;
                ActiveMarginPerContract = 100.0;
                MaxContractsByCapital = 20;
                InstrumentStatus = "allowed";
                MarginSourceBroker = "NinjaTrader";

                EnableLong = true;
                EnableShort = true;

                // Family selector + family-specific knobs.
                Mode = "OrRangeReclaim";
                RangeStartTime = 0;
                RangeEndTime = 315;
                ReclaimBufferTicks = 3;
                FailReturnTicks = 3;
                RejectWickTicks = 4;
                PullbackTicks = 6;
                DriveTicks = 20;
                RequireEmaStack = true;

                // Default trade window: free pre-cash ETH window (03:20-05:55 PT).
                TradeStartTime = 320;
                TradeEndTime = 555;
                UseSecondTradeWindow = false;
                SecondTradeStartTime = 100;
                SecondTradeEndTime = 300;
                ForceFlatTime = 559;
                AllowedWeekdayMask = 0;

                EmaFastPeriod = 9;
                EmaMidPeriod = 21;
                EmaSlowPeriod = 50;
                AtrPeriod = 14;
                VolumeSmaPeriod = 20;
                MinVolumeFactor = 0.6;
                RequireVwapAgreement = true;
                RequireEmaAgreement = true;
                RequireEmaSlope = false;

                StopBufferTicks = 4;
                MinStopTicks = 16;
                MaxStopTicks = 44;
                AtrStopMult = 1.0;
                RewardRiskRatio = 1.6;
                MinTargetTicks = 16;
                EntryOffsetTicks = 0;
                EntryTimeoutBars = 3;
                MoveToBreakevenAtR = 1.0;
                BreakevenPlusTicks = 2;
                UseTrailingStop = false;
                TrailAfterR = 1.5;
                TrailDistanceTicks = 12;
                UseTimeStop = true;
                TimeStopBars = 8;
                MinProgressR = 0.30;

                RiskPerTradePct = 0.75;
                UserMaxContracts = 1;
                MaxOpenPositions = 1;
                MaxDailyLossUsd = 80.0;
                MaxWeeklyLossUsd = 200.0;
                MaxTradesPerDay = 4;
                HardMaxTradesPerDay = 6;
                MaxConsecutiveLosses = 3;
                PauseAfterConsecutiveLosses = 2;
                PauseMinutesAfterLosses = 60;
                RoundTurnCommission = 1.90;
                SlippageTicks = 1;
            }
            else if (State == State.DataLoaded)
            {
                _emaFast = EMA(EmaFastPeriod);
                _emaMid = EMA(EmaMidPeriod);
                _emaSlow = EMA(EmaSlowPeriod);
                _atr = ATR(AtrPeriod);
                _volumeSma = SMA(Volume, VolumeSmaPeriod);
                _rsi = RSI(AtrPeriod, 3);
                _vwapSeries = new Series<double>(this);

                _permanentlyStopped = StartingCapital <= 0.0
                    || ActiveMarginPerContract <= 0.0
                    || MaxContractsByCapital < 1
                    || string.Equals(InstrumentStatus, "blocked", StringComparison.OrdinalIgnoreCase)
                    || string.Equals(InstrumentStatus, "unknown", StringComparison.OrdinalIgnoreCase);
            }
            else if (State == State.Realtime)
            {
                ResetRealtimeRiskAccounting();
            }
        }

        protected override void OnBarUpdate()
        {
            if (BarsInProgress != 0) return;
            if (CurrentBar < 1) return;

            UpdateSessionState();
            UpdateSessionExtremes();
            UpdateVwap();
            UpdateAnchor();
            UpdateOpenDrive();
            ManageOpenPosition();

            if (ForceFlatDue())
            {
                ForceFlat("time");
                return;
            }

            if (CurrentBar < BarsRequiredToTrade) return;

            if (!InTradeWindow()) return;
            if (!WeekdayAllowed()) return;
            if (!CanTrade()) return;
            if (Position.MarketPosition != MarketPosition.Flat) return;
            if (_activeSignal != "") return;
            if (MaxOpenPositions < 1) return;

            TryEnter();
        }

        private void UpdateSessionState()
        {
            DateTime currentDate = Time[0].Date;
            if (_sessionDate == currentDate) return;

            _sessionDate = currentDate;
            _vwapCumPV = 0.0;
            _vwapCumVol = 0.0;
            _anchorHigh = double.MinValue;
            _anchorLow = double.MaxValue;
            _anchorValid = false;
            _pokedAbove = false;
            _pokedBelow = false;

            // Roll prior-session extremes before resetting the running ones.
            if (_curSessHigh > double.MinValue && _curSessLow < double.MaxValue && _curSessHigh > _curSessLow)
            {
                _prevSessHigh = _curSessHigh;
                _prevSessLow = _curSessLow;
                _prevSessValid = true;
            }
            _curSessHigh = High[0];
            _curSessLow = Low[0];
            _windowOpenSet = false;
            _driveDir = 0;

            ResetDailyRisk();
            ClearActiveTradeState();
        }

        private void ResetDailyRisk()
        {
            DateTime weekStart = WeekStart(Time[0].Date);
            if (_weekStartDate == DateTime.MinValue || _weekStartDate != weekStart)
            {
                _weekStartDate = weekStart;
                _weeklyRealizedPnl = 0.0;
            }

            _sessionRealizedPnl = 0.0;
            _tradesToday = 0;
            _consecutiveLosses = 0;
            _sessionStopped = false;
            _pauseUntil = DateTime.MinValue;
        }

        private void ResetRealtimeRiskAccounting()
        {
            _cumulativeRealizedPnl = 0.0;
            _sessionRealizedPnl = 0.0;
            _weeklyRealizedPnl = 0.0;
            _tradesToday = 0;
            _consecutiveLosses = 0;
            _sessionStopped = false;
            _pauseUntil = DateTime.MinValue;
            _weekStartDate = WeekStart(Time[0].Date);
            _lastProcessedTradeCount = SystemPerformance == null
                ? 0
                : Math.Max(0, SystemPerformance.AllTrades.Count);
            Print(string.Format(
                "[RISK:realtime_reset] historicalTrades={0}; live paper risk starts from zero",
                _lastProcessedTradeCount));
        }

        private void UpdateVwap()
        {
            double volume = Math.Max(1.0, Volume[0]);
            double typical = (High[0] + Low[0] + Close[0]) / 3.0;
            _vwapCumPV += typical * volume;
            _vwapCumVol += volume;
            _vwapSeries[0] = _vwapCumVol > 0.0 ? _vwapCumPV / _vwapCumVol : Close[0];
        }

        private void UpdateAnchor()
        {
            int now = ToHHMM(Time[0]);
            if (!InWindow(now, RangeStartTime, RangeEndTime)) return;
            _anchorHigh = _anchorValid ? Math.Max(_anchorHigh, High[0]) : High[0];
            _anchorLow = _anchorValid ? Math.Min(_anchorLow, Low[0]) : Low[0];
            _anchorValid = true;
        }

        private void UpdateSessionExtremes()
        {
            _curSessHigh = _curSessHigh > double.MinValue ? Math.Max(_curSessHigh, High[0]) : High[0];
            _curSessLow = _curSessLow < double.MaxValue ? Math.Min(_curSessLow, Low[0]) : Low[0];
        }

        // Capture the price at the first bar of the trade window, then mark the
        // first directional push of DriveTicks as the "open drive" direction.
        private void UpdateOpenDrive()
        {
            if (!InTradeWindow()) return;
            if (!_windowOpenSet)
            {
                _windowOpenPrice = Open[0];
                _windowOpenSet = true;
                _driveDir = 0;
            }
            if (_driveDir == 0)
            {
                double driveUp = _windowOpenPrice + DriveTicks * TickSize;
                double driveDn = _windowOpenPrice - DriveTicks * TickSize;
                if (High[0] >= driveUp) _driveDir = 1;
                else if (Low[0] <= driveDn) _driveDir = -1;
            }
        }

        // --------------------------------------------------------------------
        // Multi-family entry dispatcher
        // --------------------------------------------------------------------
        private void TryEnter()
        {
            string mode = (Mode ?? "").Trim();

            // Families that do NOT require the intraday anchor range.
            if (mode.Equals("VwapPullback", StringComparison.OrdinalIgnoreCase))
            {
                TryVwapPullback();
                return;
            }
            if (mode.Equals("EmaPullback", StringComparison.OrdinalIgnoreCase))
            {
                TryEmaPullback();
                return;
            }
            if (mode.Equals("OpenDrive", StringComparison.OrdinalIgnoreCase))
            {
                TryOpenDrive();
                return;
            }
            if (mode.Equals("PrevDayBreak", StringComparison.OrdinalIgnoreCase))
            {
                if (_prevSessValid && _prevSessHigh > _prevSessLow) TryPrevDayBreak();
                return;
            }
            if (mode.Equals("PrevDayReject", StringComparison.OrdinalIgnoreCase))
            {
                if (_prevSessValid && _prevSessHigh > _prevSessLow) TryPrevDayReject();
                return;
            }
            if (mode.StartsWith("HeadAndShoulders", StringComparison.OrdinalIgnoreCase))
            {
                TryHeadAndShoulders(mode);
                return;
            }

            // The remaining families need a locked anchor range and a trade window
            // that begins after the range-build window completes.
            if (!_anchorValid || _anchorHigh <= _anchorLow) return;
            if (InWindow(ToHHMM(Time[0]), RangeStartTime, RangeEndTime)) return;

            if (mode.Equals("FailedBreak", StringComparison.OrdinalIgnoreCase))
                TryFailedBreak();
            else if (mode.Equals("RangeReject", StringComparison.OrdinalIgnoreCase))
                TryRangeReject();
            else
                TryRangeReclaim();
        }

        // Family 5: EMA-stack trend pullback to the mid EMA (continuation).
        private void TryEmaPullback()
        {
            bool upTrend = _emaFast[0] > _emaMid[0] && _emaMid[0] > _emaSlow[0];
            bool downTrend = _emaFast[0] < _emaMid[0] && _emaMid[0] < _emaSlow[0];

            if (EnableLong && upTrend
                && Low[0] <= _emaMid[0] + PullbackTicks * TickSize
                && Close[0] > _emaMid[0]
                && Close[0] > Open[0]
                && VolumeFactor() >= MinVolumeFactor)
            {
                EnterTrade(true, Low[0]);
                return;
            }
            if (EnableShort && downTrend
                && High[0] >= _emaMid[0] - PullbackTicks * TickSize
                && Close[0] < _emaMid[0]
                && Close[0] < Open[0]
                && VolumeFactor() >= MinVolumeFactor)
            {
                EnterTrade(false, High[0]);
            }
        }

        // Family 6: open-drive continuation. After the window's first DriveTicks
        // push, fade-resume on the first pullback to the fast EMA in drive dir.
        private void TryOpenDrive()
        {
            if (!_windowOpenSet || _driveDir == 0) return;

            if (_driveDir == 1 && EnableLong
                && Low[0] <= _emaFast[0]
                && Close[0] > _emaFast[0]
                && Close[0] > Open[0]
                && VolumeFactor() >= MinVolumeFactor)
            {
                EnterTrade(true, Low[0]);
                return;
            }
            if (_driveDir == -1 && EnableShort
                && High[0] >= _emaFast[0]
                && Close[0] < _emaFast[0]
                && Close[0] < Open[0]
                && VolumeFactor() >= MinVolumeFactor)
            {
                EnterTrade(false, High[0]);
            }
        }

        // Family 7: previous-session high/low breakout continuation.
        private void TryPrevDayBreak()
        {
            double up = _prevSessHigh + ReclaimBufferTicks * TickSize;
            double dn = _prevSessLow - ReclaimBufferTicks * TickSize;

            if (EnableLong
                && Close[1] <= up
                && Close[0] > up
                && Close[0] > Open[0]
                && ContinuationLongOk())
            {
                EnterTrade(true, _prevSessHigh);
                return;
            }
            if (EnableShort
                && Close[1] >= dn
                && Close[0] < dn
                && Close[0] < Open[0]
                && ContinuationShortOk())
            {
                EnterTrade(false, _prevSessLow);
            }
        }

        // Family 8: previous-session high/low rejection (fade the prior extreme).
        private void TryPrevDayReject()
        {
            double upTag = _prevSessHigh - RejectWickTicks * TickSize;
            double dnTag = _prevSessLow + RejectWickTicks * TickSize;

            if (EnableShort
                && High[0] >= upTag
                && Close[0] <= upTag
                && Close[0] < Open[0]
                && VolumeFactor() >= MinVolumeFactor)
            {
                EnterTrade(false, _prevSessHigh);
                return;
            }
            if (EnableLong
                && Low[0] <= dnTag
                && Close[0] >= dnTag
                && Close[0] > Open[0]
                && VolumeFactor() >= MinVolumeFactor)
            {
                EnterTrade(true, _prevSessLow);
            }
        }

        // Family 9: Head & Shoulders / inverse Head & Shoulders.
        // Existing generic knobs are intentionally reused to keep the Hub
        // property surface stable:
        //   EntryTimeoutBars   -> pivot strength
        //   PullbackTicks      -> max shoulder-height mismatch
        //   DriveTicks         -> minimum head-vs-shoulder separation
        //   FailReturnTicks    -> minimum RSI divergence points
        //   RejectWickTicks    -> right-shoulder rejection/confirmation
        //   ReclaimBufferTicks -> minimum neckline distance buffer
        //   EntryOffsetTicks   -> entry style; +10 means bar-close managed target
        //   Mode contains Live -> current-bar right shoulder, no pivot-confirm delay
        private void TryHeadAndShoulders(string mode)
        {
            int strength = Math.Max(2, Math.Min(8, EntryTimeoutBars));
            int maxWidthBars = Math.Max(45, Math.Min(240, EmaSlowPeriod * 3));
            if (CurrentBar < maxWidthBars + strength + 5) return;
            if (VolumeFactor() < MinVolumeFactor) return;

            int entryStyle = EntryOffsetTicks % 10;
            bool closeManagedTarget = EntryOffsetTicks >= 10;
            if (mode.IndexOf("Close", StringComparison.OrdinalIgnoreCase) >= 0)
                closeManagedTarget = true;
            if (mode.IndexOf("NeckBreak", StringComparison.OrdinalIgnoreCase) >= 0)
            {
                entryStyle = 1;
                closeManagedTarget = true;
            }
            else if (mode.IndexOf("NeckRetest", StringComparison.OrdinalIgnoreCase) >= 0)
            {
                entryStyle = 2;
                closeManagedTarget = true;
            }
            else if (mode.IndexOf("NeckGo", StringComparison.OrdinalIgnoreCase) >= 0)
            {
                entryStyle = 3;
                closeManagedTarget = true;
            }
            bool liveRightShoulder = mode.IndexOf("Live", StringComparison.OrdinalIgnoreCase) >= 0;
            if (liveRightShoulder)
                entryStyle = 4;

            double stopPrice;
            double targetPrice;

            if (liveRightShoulder)
            {
                if (EnableShort && FindBearishLiveHeadAndShoulders(strength, maxWidthBars, out stopPrice, out targetPrice))
                {
                    EnterPatternTrade(false, stopPrice, targetPrice, closeManagedTarget);
                    return;
                }

                if (EnableLong && FindBullishLiveHeadAndShoulders(strength, maxWidthBars, out stopPrice, out targetPrice))
                    EnterPatternTrade(true, stopPrice, targetPrice, closeManagedTarget);
                return;
            }

            if (EnableShort && FindBearishHeadAndShoulders(strength, maxWidthBars, entryStyle, out stopPrice, out targetPrice))
            {
                EnterPatternTrade(false, stopPrice, targetPrice, closeManagedTarget);
                return;
            }

            if (EnableLong && FindBullishHeadAndShoulders(strength, maxWidthBars, entryStyle, out stopPrice, out targetPrice))
                EnterPatternTrade(true, stopPrice, targetPrice, closeManagedTarget);
        }

        private bool FindBearishLiveHeadAndShoulders(int strength, int maxWidthBars, out double stopPrice, out double targetPrice)
        {
            stopPrice = 0.0;
            targetPrice = 0.0;

            double shoulderTolerance = Math.Max(1, PullbackTicks) * TickSize;
            double minHeadBreak = Math.Max(1, DriveTicks) * TickSize;
            double minDivergence = Math.Max(0, FailReturnTicks);
            double setupBuffer = Math.Max(0, ReclaimBufferTicks) * TickSize;
            double rejectBuffer = Math.Max(0, RejectWickTicks) * TickSize;

            double rightShoulder = High[0];
            if (Close[0] >= Open[0]) return false;
            if (Close[0] > rightShoulder - rejectBuffer) return false;

            double bestScore = double.MinValue;
            double bestHead = 0.0;
            double bestTarget = 0.0;

            int maxAgo = Math.Min(CurrentBar - strength - 1, maxWidthBars);
            for (int headAgo = strength + 2; headAgo <= maxAgo; headAgo++)
            {
                if (!IsPivotHigh(headAgo, strength)) continue;
                double head = High[headAgo];
                if (head < rightShoulder + minHeadBreak) continue;
                if (_rsi[0] > _rsi[headAgo] - minDivergence) continue;

                for (int leftAgo = headAgo + strength + 1; leftAgo <= maxAgo; leftAgo++)
                {
                    if (!IsPivotHigh(leftAgo, strength)) continue;
                    double leftShoulder = High[leftAgo];
                    if (Math.Abs(leftShoulder - rightShoulder) > shoulderTolerance) continue;
                    if (head < leftShoulder + minHeadBreak) continue;
                    if (_rsi[headAgo] > _rsi[leftAgo] - minDivergence) continue;
                    if (!BearishLiveHeadAndShouldersFiltersOk(headAgo, rightShoulder)) continue;

                    double leftNeck = LowestLowBetween(leftAgo, headAgo);
                    double rightNeck = LowestLowBetween(headAgo, 0);
                    double neckline = (leftNeck + rightNeck) / 2.0;
                    if (neckline <= 0.0) continue;
                    if (Close[0] <= neckline + setupBuffer) continue;

                    double stopCandidate = head + StopBufferTicks * TickSize;
                    double targetCandidate = neckline;
                    double stopTicks = (stopCandidate - Close[0]) / TickSize;
                    double targetTicks = (Close[0] - targetCandidate) / TickSize;
                    if (stopTicks <= 0.0 || targetTicks <= 0.0) continue;
                    if (targetTicks < MinTargetTicks) continue;
                    if (RewardRiskRatio > 0.0 && targetTicks < stopTicks * RewardRiskRatio) continue;

                    double symmetryPenalty = Math.Abs(leftShoulder - rightShoulder) / TickSize
                        + Math.Abs(leftNeck - rightNeck) / TickSize * 0.25;
                    double score = targetTicks - stopTicks * 0.35
                        + (head - Math.Max(leftShoulder, rightShoulder)) / TickSize
                        - symmetryPenalty;
                    if (score > bestScore)
                    {
                        bestScore = score;
                        bestHead = head;
                        bestTarget = targetCandidate;
                    }
                }
            }

            if (bestScore == double.MinValue) return false;
            stopPrice = RoundPrice(bestHead + StopBufferTicks * TickSize);
            targetPrice = RoundPrice(bestTarget);
            return true;
        }

        private bool FindBullishLiveHeadAndShoulders(int strength, int maxWidthBars, out double stopPrice, out double targetPrice)
        {
            stopPrice = 0.0;
            targetPrice = 0.0;

            double shoulderTolerance = Math.Max(1, PullbackTicks) * TickSize;
            double minHeadBreak = Math.Max(1, DriveTicks) * TickSize;
            double minDivergence = Math.Max(0, FailReturnTicks);
            double setupBuffer = Math.Max(0, ReclaimBufferTicks) * TickSize;
            double rejectBuffer = Math.Max(0, RejectWickTicks) * TickSize;

            double rightShoulder = Low[0];
            if (Close[0] <= Open[0]) return false;
            if (Close[0] < rightShoulder + rejectBuffer) return false;

            double bestScore = double.MinValue;
            double bestHead = 0.0;
            double bestTarget = 0.0;

            int maxAgo = Math.Min(CurrentBar - strength - 1, maxWidthBars);
            for (int headAgo = strength + 2; headAgo <= maxAgo; headAgo++)
            {
                if (!IsPivotLow(headAgo, strength)) continue;
                double head = Low[headAgo];
                if (head > rightShoulder - minHeadBreak) continue;
                if (_rsi[0] < _rsi[headAgo] + minDivergence) continue;

                for (int leftAgo = headAgo + strength + 1; leftAgo <= maxAgo; leftAgo++)
                {
                    if (!IsPivotLow(leftAgo, strength)) continue;
                    double leftShoulder = Low[leftAgo];
                    if (Math.Abs(leftShoulder - rightShoulder) > shoulderTolerance) continue;
                    if (head > leftShoulder - minHeadBreak) continue;
                    if (_rsi[headAgo] < _rsi[leftAgo] + minDivergence) continue;
                    if (!BullishLiveHeadAndShouldersFiltersOk(headAgo, rightShoulder)) continue;

                    double leftNeck = HighestHighBetween(leftAgo, headAgo);
                    double rightNeck = HighestHighBetween(headAgo, 0);
                    double neckline = (leftNeck + rightNeck) / 2.0;
                    if (neckline <= 0.0) continue;
                    if (Close[0] >= neckline - setupBuffer) continue;

                    double stopCandidate = head - StopBufferTicks * TickSize;
                    double targetCandidate = neckline;
                    double stopTicks = (Close[0] - stopCandidate) / TickSize;
                    double targetTicks = (targetCandidate - Close[0]) / TickSize;
                    if (stopTicks <= 0.0 || targetTicks <= 0.0) continue;
                    if (targetTicks < MinTargetTicks) continue;
                    if (RewardRiskRatio > 0.0 && targetTicks < stopTicks * RewardRiskRatio) continue;

                    double symmetryPenalty = Math.Abs(leftShoulder - rightShoulder) / TickSize
                        + Math.Abs(leftNeck - rightNeck) / TickSize * 0.25;
                    double score = targetTicks - stopTicks * 0.35
                        + (Math.Min(leftShoulder, rightShoulder) - head) / TickSize
                        - symmetryPenalty;
                    if (score > bestScore)
                    {
                        bestScore = score;
                        bestHead = head;
                        bestTarget = targetCandidate;
                    }
                }
            }

            if (bestScore == double.MinValue) return false;
            stopPrice = RoundPrice(bestHead - StopBufferTicks * TickSize);
            targetPrice = RoundPrice(bestTarget);
            return true;
        }

        private bool FindBearishHeadAndShoulders(int strength, int maxWidthBars, int entryStyle, out double stopPrice, out double targetPrice)
        {
            stopPrice = 0.0;
            targetPrice = 0.0;

            double shoulderTolerance = Math.Max(1, PullbackTicks) * TickSize;
            double minHeadBreak = Math.Max(1, DriveTicks) * TickSize;
            double minDivergence = Math.Max(0, FailReturnTicks);
            double setupBuffer = Math.Max(0, ReclaimBufferTicks) * TickSize;

            double bestScore = double.MinValue;
            double bestHead = 0.0;
            double bestTarget = 0.0;

            int rightMaxAgo = entryStyle == 0
                ? strength
                : Math.Min(Math.Max(strength, strength + Math.Max(3, TimeStopBars)), maxWidthBars / 2);

            for (int rightAgo = strength; rightAgo <= rightMaxAgo; rightAgo++)
            {
                if (!IsPivotHigh(rightAgo, strength)) continue;
                double rightShoulder = High[rightAgo];

                int maxAgo = Math.Min(CurrentBar - strength - 1, rightAgo + maxWidthBars);
                for (int headAgo = rightAgo + strength + 1; headAgo <= maxAgo; headAgo++)
                {
                    if (!IsPivotHigh(headAgo, strength)) continue;
                    double head = High[headAgo];
                    if (head < rightShoulder + minHeadBreak) continue;

                    for (int leftAgo = headAgo + strength + 1; leftAgo <= maxAgo; leftAgo++)
                    {
                        if (!IsPivotHigh(leftAgo, strength)) continue;
                        double leftShoulder = High[leftAgo];
                        if (Math.Abs(leftShoulder - rightShoulder) > shoulderTolerance) continue;
                        if (head < leftShoulder + minHeadBreak) continue;
                        if (_rsi[headAgo] > _rsi[leftAgo] - minDivergence) continue;

                        double leftNeck = LowestLowBetween(leftAgo, headAgo);
                        double rightNeck = LowestLowBetween(headAgo, rightAgo);
                        double neckline = (leftNeck + rightNeck) / 2.0;
                        if (neckline <= 0.0) continue;
                        if (entryStyle == 0 && neckline >= Close[0] - setupBuffer) continue;
                        if (entryStyle > 0 && Math.Abs(leftNeck - rightNeck) > Math.Max(8, PullbackTicks) * TickSize) continue;
                        if (!BearishHeadAndShouldersEntryOk(entryStyle, rightShoulder, neckline)) continue;
                        if (!BearishHeadAndShouldersFiltersOk()) continue;

                        double patternHeight = Math.Max(TickSize, head - neckline);
                        double targetCandidate = BearishHeadAndShouldersTarget(entryStyle, neckline, patternHeight);
                        double stopCandidate = head + StopBufferTicks * TickSize;
                        double stopTicks = (stopCandidate - Close[0]) / TickSize;
                        double targetTicks = (Close[0] - targetCandidate) / TickSize;
                        if (stopTicks <= 0.0 || targetTicks <= 0.0) continue;
                        if (targetTicks < MinTargetTicks) continue;
                        if (RewardRiskRatio > 0.0 && targetTicks < stopTicks * RewardRiskRatio) continue;

                        double symmetryPenalty = Math.Abs(leftShoulder - rightShoulder) / TickSize
                            + Math.Abs(leftNeck - rightNeck) / TickSize * 0.35
                            + rightAgo * 0.20;
                        double score = targetTicks - stopTicks * 0.45
                            + (head - Math.Max(leftShoulder, rightShoulder)) / TickSize
                            - symmetryPenalty;
                        if (score > bestScore)
                        {
                            bestScore = score;
                            bestHead = head;
                            bestTarget = targetCandidate;
                        }
                    }
                }
            }

            if (bestScore == double.MinValue) return false;
            stopPrice = RoundPrice(bestHead + StopBufferTicks * TickSize);
            targetPrice = RoundPrice(bestTarget);
            return true;
        }

        private bool FindBullishHeadAndShoulders(int strength, int maxWidthBars, int entryStyle, out double stopPrice, out double targetPrice)
        {
            stopPrice = 0.0;
            targetPrice = 0.0;

            double shoulderTolerance = Math.Max(1, PullbackTicks) * TickSize;
            double minHeadBreak = Math.Max(1, DriveTicks) * TickSize;
            double minDivergence = Math.Max(0, FailReturnTicks);
            double setupBuffer = Math.Max(0, ReclaimBufferTicks) * TickSize;

            double bestScore = double.MinValue;
            double bestHead = 0.0;
            double bestTarget = 0.0;

            int rightMaxAgo = entryStyle == 0
                ? strength
                : Math.Min(Math.Max(strength, strength + Math.Max(3, TimeStopBars)), maxWidthBars / 2);

            for (int rightAgo = strength; rightAgo <= rightMaxAgo; rightAgo++)
            {
                if (!IsPivotLow(rightAgo, strength)) continue;
                double rightShoulder = Low[rightAgo];

                int maxAgo = Math.Min(CurrentBar - strength - 1, rightAgo + maxWidthBars);
                for (int headAgo = rightAgo + strength + 1; headAgo <= maxAgo; headAgo++)
                {
                    if (!IsPivotLow(headAgo, strength)) continue;
                    double head = Low[headAgo];
                    if (head > rightShoulder - minHeadBreak) continue;

                    for (int leftAgo = headAgo + strength + 1; leftAgo <= maxAgo; leftAgo++)
                    {
                        if (!IsPivotLow(leftAgo, strength)) continue;
                        double leftShoulder = Low[leftAgo];
                        if (Math.Abs(leftShoulder - rightShoulder) > shoulderTolerance) continue;
                        if (head > leftShoulder - minHeadBreak) continue;
                        if (_rsi[headAgo] < _rsi[leftAgo] + minDivergence) continue;

                        double leftNeck = HighestHighBetween(leftAgo, headAgo);
                        double rightNeck = HighestHighBetween(headAgo, rightAgo);
                        double neckline = (leftNeck + rightNeck) / 2.0;
                        if (neckline <= 0.0) continue;
                        if (entryStyle == 0 && neckline <= Close[0] + setupBuffer) continue;
                        if (entryStyle > 0 && Math.Abs(leftNeck - rightNeck) > Math.Max(8, PullbackTicks) * TickSize) continue;
                        if (!BullishHeadAndShouldersEntryOk(entryStyle, rightShoulder, neckline)) continue;
                        if (!BullishHeadAndShouldersFiltersOk()) continue;

                        double patternHeight = Math.Max(TickSize, neckline - head);
                        double targetCandidate = BullishHeadAndShouldersTarget(entryStyle, neckline, patternHeight);
                        double stopCandidate = head - StopBufferTicks * TickSize;
                        double stopTicks = (Close[0] - stopCandidate) / TickSize;
                        double targetTicks = (targetCandidate - Close[0]) / TickSize;
                        if (stopTicks <= 0.0 || targetTicks <= 0.0) continue;
                        if (targetTicks < MinTargetTicks) continue;
                        if (RewardRiskRatio > 0.0 && targetTicks < stopTicks * RewardRiskRatio) continue;

                        double symmetryPenalty = Math.Abs(leftShoulder - rightShoulder) / TickSize
                            + Math.Abs(leftNeck - rightNeck) / TickSize * 0.35
                            + rightAgo * 0.20;
                        double score = targetTicks - stopTicks * 0.45
                            + (Math.Min(leftShoulder, rightShoulder) - head) / TickSize
                            - symmetryPenalty;
                        if (score > bestScore)
                        {
                            bestScore = score;
                            bestHead = head;
                            bestTarget = targetCandidate;
                        }
                    }
                }
            }

            if (bestScore == double.MinValue) return false;
            stopPrice = RoundPrice(bestHead - StopBufferTicks * TickSize);
            targetPrice = RoundPrice(bestTarget);
            return true;
        }

        private bool BearishHeadAndShouldersEntryOk(int entryStyle, double rightShoulder, double neckline)
        {
            double setupBuffer = Math.Max(0, ReclaimBufferTicks) * TickSize;
            double rejectBuffer = Math.Max(0, RejectWickTicks) * TickSize;

            if (entryStyle == 1)
                return Close[0] < neckline - setupBuffer
                    && Close[1] >= neckline - setupBuffer
                    && Close[0] < Open[0];
            if (entryStyle == 2)
                return Close[1] < neckline - setupBuffer
                    && High[0] >= neckline - rejectBuffer
                    && Close[0] < neckline - setupBuffer
                    && Close[0] < Open[0];
            if (entryStyle == 3)
                return Close[0] < neckline - setupBuffer
                    && Close[0] < Close[1]
                    && Close[0] < Open[0];

            return Close[0] <= rightShoulder - rejectBuffer
                && Close[0] < Open[0];
        }

        private bool BullishHeadAndShouldersEntryOk(int entryStyle, double rightShoulder, double neckline)
        {
            double setupBuffer = Math.Max(0, ReclaimBufferTicks) * TickSize;
            double rejectBuffer = Math.Max(0, RejectWickTicks) * TickSize;

            if (entryStyle == 1)
                return Close[0] > neckline + setupBuffer
                    && Close[1] <= neckline + setupBuffer
                    && Close[0] > Open[0];
            if (entryStyle == 2)
                return Close[1] > neckline + setupBuffer
                    && Low[0] <= neckline + rejectBuffer
                    && Close[0] > neckline + setupBuffer
                    && Close[0] > Open[0];
            if (entryStyle == 3)
                return Close[0] > neckline + setupBuffer
                    && Close[0] > Close[1]
                    && Close[0] > Open[0];

            return Close[0] >= rightShoulder + rejectBuffer
                && Close[0] > Open[0];
        }

        private bool BearishHeadAndShouldersFiltersOk()
        {
            if (RequireVwapAgreement && Close[0] > _vwapSeries[0]) return false;
            if (RequireEmaAgreement && Close[0] > _emaFast[0]) return false;
            if (RequireEmaSlope && _emaFast[0] >= _emaFast[1]) return false;
            if (RequireEmaStack && (_emaFast[0] >= _emaMid[0] || _emaMid[0] >= _emaSlow[0])) return false;
            return true;
        }

        private bool BullishHeadAndShouldersFiltersOk()
        {
            if (RequireVwapAgreement && Close[0] < _vwapSeries[0]) return false;
            if (RequireEmaAgreement && Close[0] < _emaFast[0]) return false;
            if (RequireEmaSlope && _emaFast[0] <= _emaFast[1]) return false;
            if (RequireEmaStack && (_emaFast[0] <= _emaMid[0] || _emaMid[0] <= _emaSlow[0])) return false;
            return true;
        }

        private bool BearishLiveHeadAndShouldersFiltersOk(int headAgo, double rightShoulder)
        {
            if (RequireVwapAgreement && rightShoulder < _vwapSeries[0]) return false;
            if (RequireEmaAgreement && Close[0] > _emaFast[0]) return false;
            if (RequireEmaSlope && _emaFast[0] >= _emaFast[1]) return false;
            if (RequireEmaStack && _emaFast[headAgo] < _emaMid[headAgo]) return false;
            return true;
        }

        private bool BullishLiveHeadAndShouldersFiltersOk(int headAgo, double rightShoulder)
        {
            if (RequireVwapAgreement && rightShoulder > _vwapSeries[0]) return false;
            if (RequireEmaAgreement && Close[0] < _emaFast[0]) return false;
            if (RequireEmaSlope && _emaFast[0] <= _emaFast[1]) return false;
            if (RequireEmaStack && _emaFast[headAgo] > _emaMid[headAgo]) return false;
            return true;
        }

        private double BearishHeadAndShouldersTarget(int entryStyle, double neckline, double patternHeight)
        {
            if (entryStyle == 0)
                return neckline;
            double extension = patternHeight * Math.Max(0.5, Math.Min(2.0, RewardRiskRatio));
            return neckline - extension;
        }

        private double BullishHeadAndShouldersTarget(int entryStyle, double neckline, double patternHeight)
        {
            if (entryStyle == 0)
                return neckline;
            double extension = patternHeight * Math.Max(0.5, Math.Min(2.0, RewardRiskRatio));
            return neckline + extension;
        }

        private void EnterPatternTrade(bool isLong, double stopPrice, double targetPrice, bool closeManagedTarget)
        {
            stopPrice = RoundPrice(stopPrice);
            targetPrice = RoundPrice(targetPrice);

            if (isLong)
            {
                stopPrice = Math.Min(stopPrice, RoundPrice(Close[0] - MinStopTicks * TickSize));
                if (targetPrice <= Close[0]) return;
            }
            else
            {
                stopPrice = Math.Max(stopPrice, RoundPrice(Close[0] + MinStopTicks * TickSize));
                if (targetPrice >= Close[0]) return;
            }

            int stopTicks = (int)Math.Ceiling(Math.Abs(Close[0] - stopPrice) / TickSize);
            int targetTicks = (int)Math.Floor(Math.Abs(targetPrice - Close[0]) / TickSize);
            if (stopTicks < MinStopTicks || stopTicks > MaxStopTicks) return;
            if (targetTicks < MinTargetTicks) return;
            if (RewardRiskRatio > 0.0 && targetTicks < stopTicks * RewardRiskRatio) return;

            int qty = ComputeQuantity(stopTicks);
            if (qty < 1) return;

            string signal = TelemetrySignal(isLong
                ? (closeManagedTarget ? "LongCT" : "Long")
                : (closeManagedTarget ? "ShortCT" : "Short"));
            SetStopLoss(signal, CalculationMode.Price, stopPrice, false);
            _patternTargetActive = closeManagedTarget;
            _patternTargetIsLong = isLong;
            _patternTargetPrice = closeManagedTarget ? targetPrice : 0.0;
            if (!closeManagedTarget)
                SetProfitTarget(signal, CalculationMode.Price, targetPrice);
            _activeSignal = signal;
            _lastStopTicks = stopTicks;
            _lastEntryBar = CurrentBar;
            _lastEntryPrice = Close[0];
            _stopMovedToBreakeven = false;
            _bestFavorableTicks = 0.0;

            if (isLong) EnterLong(qty, signal);
            else EnterShort(qty, signal);
        }

        private bool IsPivotHigh(int ago, int strength)
        {
            if (ago < strength || ago + strength > CurrentBar) return false;
            double pivot = High[ago];
            for (int i = 1; i <= strength; i++)
            {
                if (pivot <= High[ago - i]) return false;
                if (pivot < High[ago + i]) return false;
            }
            return true;
        }

        private bool IsPivotLow(int ago, int strength)
        {
            if (ago < strength || ago + strength > CurrentBar) return false;
            double pivot = Low[ago];
            for (int i = 1; i <= strength; i++)
            {
                if (pivot >= Low[ago - i]) return false;
                if (pivot > Low[ago + i]) return false;
            }
            return true;
        }

        private double LowestLowBetween(int olderAgo, int newerAgo)
        {
            int start = Math.Min(olderAgo, newerAgo);
            int end = Math.Max(olderAgo, newerAgo);
            double lowest = double.MaxValue;
            for (int ago = start; ago <= end; ago++)
                lowest = Math.Min(lowest, Low[ago]);
            return lowest == double.MaxValue ? 0.0 : lowest;
        }

        private double HighestHighBetween(int olderAgo, int newerAgo)
        {
            int start = Math.Min(olderAgo, newerAgo);
            int end = Math.Max(olderAgo, newerAgo);
            double highest = double.MinValue;
            for (int ago = start; ago <= end; ago++)
                highest = Math.Max(highest, High[ago]);
            return highest == double.MinValue ? 0.0 : highest;
        }

        private double RoundPrice(double price)
        {
            if (Instrument != null && Instrument.MasterInstrument != null)
                return Instrument.MasterInstrument.RoundToTickSize(price);
            return Math.Round(price / TickSize) * TickSize;
        }

        // Family 1: time-defined range reclaim / continuation.
        private void TryRangeReclaim()
        {
            double upLevel = _anchorHigh + ReclaimBufferTicks * TickSize;
            double dnLevel = _anchorLow - ReclaimBufferTicks * TickSize;

            if (EnableLong
                && Close[1] <= upLevel
                && Close[0] > upLevel
                && Close[0] > Open[0]
                && ContinuationLongOk())
            {
                EnterTrade(true, _anchorLow);
                return;
            }
            if (EnableShort
                && Close[1] >= dnLevel
                && Close[0] < dnLevel
                && Close[0] < Open[0]
                && ContinuationShortOk())
            {
                EnterTrade(false, _anchorHigh);
            }
        }

        // Family 2: failed breakout reversal (fade back into the range).
        private void TryFailedBreak()
        {
            if (High[0] > _anchorHigh) _pokedAbove = true;
            if (Low[0] < _anchorLow) _pokedBelow = true;

            double upReturn = _anchorHigh - FailReturnTicks * TickSize;
            double dnReturn = _anchorLow + FailReturnTicks * TickSize;

            // Poked above then closed back inside -> short the failure.
            if (EnableShort
                && _pokedAbove
                && Close[0] <= upReturn
                && Close[0] < Open[0]
                && VolumeFactor() >= MinVolumeFactor)
            {
                _pokedAbove = false;
                EnterTrade(false, _anchorHigh);
                return;
            }
            // Poked below then closed back inside -> long the failure.
            if (EnableLong
                && _pokedBelow
                && Close[0] >= dnReturn
                && Close[0] > Open[0]
                && VolumeFactor() >= MinVolumeFactor)
            {
                _pokedBelow = false;
                EnterTrade(true, _anchorLow);
            }
        }

        // Family 3: VWAP pullback continuation in an EMA-stacked trend.
        private void TryVwapPullback()
        {
            double vwap = _vwapSeries[0];
            if (vwap <= 0.0) return;

            bool upTrend = !RequireEmaStack || (_emaFast[0] > _emaMid[0] && _emaMid[0] > _emaSlow[0]);
            bool downTrend = !RequireEmaStack || (_emaFast[0] < _emaMid[0] && _emaMid[0] < _emaSlow[0]);

            if (EnableLong
                && upTrend
                && Low[0] <= vwap + PullbackTicks * TickSize
                && Close[0] > vwap
                && Close[0] > Open[0]
                && VolumeFactor() >= MinVolumeFactor)
            {
                EnterTrade(true, Low[0]);
                return;
            }
            if (EnableShort
                && downTrend
                && High[0] >= vwap - PullbackTicks * TickSize
                && Close[0] < vwap
                && Close[0] < Open[0]
                && VolumeFactor() >= MinVolumeFactor)
            {
                EnterTrade(false, High[0]);
            }
        }

        // Family 4: anchor high/low wick rejection (no prior breakout required).
        private void TryRangeReject()
        {
            double upTag = _anchorHigh - RejectWickTicks * TickSize;
            double dnTag = _anchorLow + RejectWickTicks * TickSize;

            // Wick into resistance, close rejected below it -> short.
            if (EnableShort
                && High[0] >= upTag
                && Close[0] <= upTag
                && Close[0] < Open[0]
                && VolumeFactor() >= MinVolumeFactor)
            {
                EnterTrade(false, _anchorHigh);
                return;
            }
            // Wick into support, close rejected above it -> long.
            if (EnableLong
                && Low[0] <= dnTag
                && Close[0] >= dnTag
                && Close[0] > Open[0]
                && VolumeFactor() >= MinVolumeFactor)
            {
                EnterTrade(true, _anchorLow);
            }
        }

        private bool ContinuationLongOk()
        {
            if (VolumeFactor() < MinVolumeFactor) return false;
            if (RequireVwapAgreement && Close[0] < _vwapSeries[0]) return false;
            if (RequireEmaAgreement && _emaFast[0] <= _emaMid[0]) return false;
            if (RequireEmaSlope && _emaFast[0] <= _emaFast[1]) return false;
            return true;
        }

        private bool ContinuationShortOk()
        {
            if (VolumeFactor() < MinVolumeFactor) return false;
            if (RequireVwapAgreement && Close[0] > _vwapSeries[0]) return false;
            if (RequireEmaAgreement && _emaFast[0] >= _emaMid[0]) return false;
            if (RequireEmaSlope && _emaFast[0] >= _emaFast[1]) return false;
            return true;
        }

        private void EnterTrade(bool isLong, double oppositeReference)
        {
            int stopTicks = ComputeStopTicks(isLong, oppositeReference);
            int targetTicks = (int)Math.Round(stopTicks * RewardRiskRatio);
            if (stopTicks < MinStopTicks || targetTicks < MinTargetTicks) return;

            int qty = ComputeQuantity(stopTicks);
            if (qty < 1) return;

            string signal = TelemetrySignal(isLong ? "Long" : "Short");
            SetStopLoss(signal, CalculationMode.Ticks, stopTicks, false);
            SetProfitTarget(signal, CalculationMode.Ticks, targetTicks);
            _activeSignal = signal;
            _lastStopTicks = stopTicks;
            _lastEntryBar = CurrentBar;
            _lastEntryPrice = Close[0];
            _stopMovedToBreakeven = false;
            _bestFavorableTicks = 0.0;

            if (isLong) EnterLong(qty, signal);
            else EnterShort(qty, signal);
        }

        private int ComputeStopTicks(bool isLong, double oppositeReference)
        {
            double geometryPrice = isLong
                ? Math.Min(Low[0], oppositeReference) - StopBufferTicks * TickSize
                : Math.Max(High[0], oppositeReference) + StopBufferTicks * TickSize;
            double geometryTicks = isLong
                ? (Close[0] - geometryPrice) / TickSize
                : (geometryPrice - Close[0]) / TickSize;
            int rawTicks = (int)Math.Ceiling(Math.Max(1.0, geometryTicks));
            int atrTicks = (int)Math.Round((_atr[0] / TickSize) * AtrStopMult);
            int stopTicks = Math.Max(rawTicks, atrTicks);
            stopTicks = Math.Max(stopTicks, MinStopTicks);
            stopTicks = Math.Min(stopTicks, MaxStopTicks);
            return stopTicks;
        }

        private void ManageOpenPosition()
        {
            if (Position.MarketPosition == MarketPosition.Flat) return;

            bool isLong = Position.MarketPosition == MarketPosition.Long;
            double entry = Position.AveragePrice;
            if (entry <= 0.0) entry = _lastEntryPrice;
            if (entry <= 0.0 || _lastStopTicks <= 0) return;

            double favorableTicks = isLong
                ? (High[0] - entry) / TickSize
                : (entry - Low[0]) / TickSize;
            _bestFavorableTicks = Math.Max(_bestFavorableTicks, favorableTicks);

            if (_patternTargetActive
                && CurrentBar > _lastEntryBar
                && _patternTargetPrice > 0.0)
            {
                if (_patternTargetIsLong && Close[0] >= _patternTargetPrice)
                {
                    ExitLong("PatternTarget", _activeSignal);
                    return;
                }
                if (!_patternTargetIsLong && Close[0] <= _patternTargetPrice)
                {
                    ExitShort("PatternTarget", _activeSignal);
                    return;
                }
            }

            if (!_stopMovedToBreakeven
                && MoveToBreakevenAtR > 0.0
                && _bestFavorableTicks >= _lastStopTicks * MoveToBreakevenAtR)
            {
                double bePrice = isLong
                    ? entry + BreakevenPlusTicks * TickSize
                    : entry - BreakevenPlusTicks * TickSize;
                SetStopLoss(_activeSignal, CalculationMode.Price, bePrice, false);
                _stopMovedToBreakeven = true;
            }

            if (UseTrailingStop
                && TrailAfterR > 0.0
                && _bestFavorableTicks >= _lastStopTicks * TrailAfterR
                && _stopMovedToBreakeven)
            {
                double trailPrice = isLong
                    ? Close[0] - TrailDistanceTicks * TickSize
                    : Close[0] + TrailDistanceTicks * TickSize;
                SetStopLoss(_activeSignal, CalculationMode.Price, trailPrice, false);
            }

            if (UseTimeStop && TimeStopBars > 0 && _lastEntryBar >= 0)
            {
                int barsHeld = CurrentBar - _lastEntryBar;
                if (barsHeld >= TimeStopBars
                    && _bestFavorableTicks < _lastStopTicks * MinProgressR)
                {
                    if (isLong) ExitLong("TimeStop", _activeSignal);
                    else ExitShort("TimeStop", _activeSignal);
                }
            }
        }

        private void ForceFlat(string reason)
        {
            if (Position.MarketPosition == MarketPosition.Long)
                ExitLong("ForceFlat_" + reason, _activeSignal == "" ? TelemetrySignal("Long") : _activeSignal);
            else if (Position.MarketPosition == MarketPosition.Short)
                ExitShort("ForceFlat_" + reason, _activeSignal == "" ? TelemetrySignal("Short") : _activeSignal);
        }

        private bool CanTrade()
        {
            if (_permanentlyStopped || _sessionStopped) return false;
            if (_pauseUntil != DateTime.MinValue && Time[0] < _pauseUntil) return false;
            if (MaxDailyLossUsd > 0.0 && _sessionRealizedPnl <= -MaxDailyLossUsd) return false;
            if (MaxWeeklyLossUsd > 0.0 && _weeklyRealizedPnl <= -MaxWeeklyLossUsd) return false;
            if (MaxTradesPerDay > 0 && _tradesToday >= MaxTradesPerDay) return false;
            if (HardMaxTradesPerDay > 0 && _tradesToday >= HardMaxTradesPerDay) return false;
            if (MaxConsecutiveLosses > 0 && _consecutiveLosses >= MaxConsecutiveLosses) return false;
            return true;
        }

        private int ComputeQuantity(int stopTicks)
        {
            if (_permanentlyStopped) return 0;
            double tickValue = TickValue();
            if (tickValue <= 0.0) return 0;

            double equity = CurrentEquity();
            double riskBudget = equity * RiskPerTradePct / 100.0;
            double contractRisk = stopTicks * tickValue + RoundTurnCommission + SlippageTicks * tickValue;
            if (contractRisk <= 0.0) return 0;

            int byRisk = (int)Math.Floor(riskBudget / contractRisk);
            int byMargin = ActiveMarginPerContract > 0.0
                ? (int)Math.Floor(equity / ActiveMarginPerContract)
                : MaxContractsByCapital;
            int byUser = UserMaxContracts > 0 ? UserMaxContracts : MaxContractsByCapital;
            int qty = Math.Min(Math.Min(byRisk, byMargin), Math.Min(byUser, MaxContractsByCapital));

            // Floor to a single permitted contract when the fractional risk budget
            // rounds below one but the account can margin one contract and the
            // trade's absolute dollar risk stays within the hard daily-loss cap.
            if (qty < 1
                && byMargin >= 1
                && byUser >= 1
                && MaxContractsByCapital >= 1
                && (MaxDailyLossUsd <= 0.0 || contractRisk <= MaxDailyLossUsd))
            {
                qty = 1;
            }

            return Math.Max(0, qty);
        }

        private double VolumeFactor()
        {
            double baseVolume = _volumeSma[0];
            if (baseVolume <= 0.0) return 0.0;
            return Volume[0] / baseVolume;
        }

        private bool InTradeWindow()
        {
            int now = ToHHMM(Time[0]);
            if (InWindow(now, TradeStartTime, TradeEndTime)) return true;
            return UseSecondTradeWindow && InWindow(now, SecondTradeStartTime, SecondTradeEndTime);
        }

        private bool ForceFlatDue()
        {
            return ToHHMM(Time[0]) >= ForceFlatTime;
        }

        private bool InWindow(int now, int start, int end)
        {
            if (start <= end) return now >= start && now <= end;
            return now >= start || now <= end;
        }

        private int ToHHMM(DateTime value)
        {
            return value.Hour * 100 + value.Minute;
        }

        private bool WeekdayAllowed()
        {
            int mask = AllowedWeekdayMask;
            string mode = (Mode ?? "").Trim();
            if (mask <= 0 && mode.IndexOf("Dow", StringComparison.OrdinalIgnoreCase) >= 0)
                mask = RangeStartTime;
            if (mask <= 0) return true;

            int bit = 0;
            switch (Time[0].DayOfWeek)
            {
                case DayOfWeek.Monday: bit = 1; break;
                case DayOfWeek.Tuesday: bit = 2; break;
                case DayOfWeek.Wednesday: bit = 4; break;
                case DayOfWeek.Thursday: bit = 8; break;
                case DayOfWeek.Friday: bit = 16; break;
                case DayOfWeek.Saturday: bit = 32; break;
                case DayOfWeek.Sunday: bit = 64; break;
            }
            return (mask & bit) != 0;
        }

        private double CurrentEquity()
        {
            double unrealized = 0.0;
            if (Position != null && Position.MarketPosition != MarketPosition.Flat && Position.Quantity > 0)
                unrealized = Position.GetUnrealizedProfitLoss(PerformanceUnit.Currency, Close[0]);
            return StartingCapital + _cumulativeRealizedPnl + unrealized;
        }

        private double TickValue()
        {
            if (Instrument == null || Instrument.MasterInstrument == null) return 0.0;
            return Instrument.MasterInstrument.PointValue * TickSize;
        }

        private static DateTime WeekStart(DateTime date)
        {
            int diff = ((int)date.DayOfWeek + 6) % 7;
            return date.Date.AddDays(-diff);
        }

        private string TelemetrySignal(string side)
        {
            return GetType().Name + "." + side;
        }

        private void ClearActiveTradeState()
        {
            _activeSignal = "";
            _lastEntryBar = -1;
            _lastEntryPrice = 0.0;
            _lastStopTicks = 0;
            _stopMovedToBreakeven = false;
            _bestFavorableTicks = 0.0;
            _patternTargetActive = false;
            _patternTargetIsLong = false;
            _patternTargetPrice = 0.0;
        }

        protected override void OnPositionUpdate(Position position, double averagePrice,
            int quantity, MarketPosition marketPosition)
        {
            if (marketPosition != MarketPosition.Flat) return;
            if (SystemPerformance == null) return;

            int total = SystemPerformance.AllTrades.Count;
            if (total <= _lastProcessedTradeCount) return;

            for (int index = _lastProcessedTradeCount; index < total; index++)
            {
                Trade trade = SystemPerformance.AllTrades[index];
                double qty = Math.Max(1, trade.Quantity);
                double pnl = trade.ProfitCurrency - RoundTurnCommission * qty;
                _cumulativeRealizedPnl += pnl;
                _sessionRealizedPnl += pnl;
                _weeklyRealizedPnl += pnl;
                _tradesToday += 1;

                if (pnl < 0.0) _consecutiveLosses += 1;
                else _consecutiveLosses = 0;

                if (pnl < 0.0
                    && PauseAfterConsecutiveLosses > 0
                    && _consecutiveLosses >= PauseAfterConsecutiveLosses)
                    _pauseUntil = Time[0].AddMinutes(Math.Max(1, PauseMinutesAfterLosses));
            }

            if (MaxDailyLossUsd > 0.0 && _sessionRealizedPnl <= -MaxDailyLossUsd)
                _sessionStopped = true;
            if (MaxWeeklyLossUsd > 0.0 && _weeklyRealizedPnl <= -MaxWeeklyLossUsd)
                _sessionStopped = true;
            if (MaxConsecutiveLosses > 0 && _consecutiveLosses >= MaxConsecutiveLosses)
                _sessionStopped = true;

            _lastProcessedTradeCount = total;
            ClearActiveTradeState();
        }

        #region Properties
        [NinjaScriptProperty]
        [Display(Name = "InstrumentName", GroupName = "01-Instrument", Order = 0)]
        public string InstrumentName { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "ContractName", GroupName = "01-Instrument", Order = 1)]
        public string ContractName { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "SessionTemplateName", GroupName = "01-Instrument", Order = 2)]
        public string SessionTemplateName { get; set; }

        [NinjaScriptProperty, Range(1, 3600)]
        [Display(Name = "BaseTimeframeSeconds", GroupName = "01-Instrument", Order = 3)]
        public int BaseTimeframeSeconds { get; set; }

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

        [NinjaScriptProperty]
        [Display(Name = "EnableLong", GroupName = "03-Direction", Order = 0)]
        public bool EnableLong { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "EnableShort", GroupName = "03-Direction", Order = 1)]
        public bool EnableShort { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "Mode", GroupName = "03-Direction", Order = 2)]
        public string Mode { get; set; }

        [NinjaScriptProperty, Range(0, 2359)]
        [Display(Name = "RangeStartTime", GroupName = "04-Time", Order = 0)]
        public int RangeStartTime { get; set; }

        [NinjaScriptProperty, Range(0, 2359)]
        [Display(Name = "RangeEndTime", GroupName = "04-Time", Order = 1)]
        public int RangeEndTime { get; set; }

        [NinjaScriptProperty, Range(0, 2359)]
        [Display(Name = "TradeStartTime", GroupName = "04-Time", Order = 2)]
        public int TradeStartTime { get; set; }

        [NinjaScriptProperty, Range(0, 2359)]
        [Display(Name = "TradeEndTime", GroupName = "04-Time", Order = 3)]
        public int TradeEndTime { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "UseSecondTradeWindow", GroupName = "04-Time", Order = 4)]
        public bool UseSecondTradeWindow { get; set; }

        [NinjaScriptProperty, Range(0, 2359)]
        [Display(Name = "SecondTradeStartTime", GroupName = "04-Time", Order = 5)]
        public int SecondTradeStartTime { get; set; }

        [NinjaScriptProperty, Range(0, 2359)]
        [Display(Name = "SecondTradeEndTime", GroupName = "04-Time", Order = 6)]
        public int SecondTradeEndTime { get; set; }

        [NinjaScriptProperty, Range(0, 2359)]
        [Display(Name = "ForceFlatTime", GroupName = "04-Time", Order = 7)]
        public int ForceFlatTime { get; set; }

        [NinjaScriptProperty, Range(0, 127)]
        [Display(Name = "AllowedWeekdayMask", GroupName = "04-Time", Order = 8)]
        public int AllowedWeekdayMask { get; set; }

        [NinjaScriptProperty, Range(2, 200)]
        [Display(Name = "EmaFastPeriod", GroupName = "05-Filters", Order = 0)]
        public int EmaFastPeriod { get; set; }

        [NinjaScriptProperty, Range(2, 300)]
        [Display(Name = "EmaMidPeriod", GroupName = "05-Filters", Order = 1)]
        public int EmaMidPeriod { get; set; }

        [NinjaScriptProperty, Range(2, 400)]
        [Display(Name = "EmaSlowPeriod", GroupName = "05-Filters", Order = 2)]
        public int EmaSlowPeriod { get; set; }

        [NinjaScriptProperty, Range(2, 200)]
        [Display(Name = "AtrPeriod", GroupName = "05-Filters", Order = 3)]
        public int AtrPeriod { get; set; }

        [NinjaScriptProperty, Range(2, 500)]
        [Display(Name = "VolumeSmaPeriod", GroupName = "05-Filters", Order = 4)]
        public int VolumeSmaPeriod { get; set; }

        [NinjaScriptProperty, Range(0.0, 10.0)]
        [Display(Name = "MinVolumeFactor", GroupName = "05-Filters", Order = 5)]
        public double MinVolumeFactor { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "RequireVwapAgreement", GroupName = "05-Filters", Order = 6)]
        public bool RequireVwapAgreement { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "RequireEmaAgreement", GroupName = "05-Filters", Order = 7)]
        public bool RequireEmaAgreement { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "RequireEmaSlope", GroupName = "05-Filters", Order = 8)]
        public bool RequireEmaSlope { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "RequireEmaStack", GroupName = "05-Filters", Order = 9)]
        public bool RequireEmaStack { get; set; }

        [NinjaScriptProperty, Range(0, 100)]
        [Display(Name = "ReclaimBufferTicks", GroupName = "06-Setup", Order = 0)]
        public int ReclaimBufferTicks { get; set; }

        [NinjaScriptProperty, Range(0, 100)]
        [Display(Name = "FailReturnTicks", GroupName = "06-Setup", Order = 1)]
        public int FailReturnTicks { get; set; }

        [NinjaScriptProperty, Range(0, 100)]
        [Display(Name = "RejectWickTicks", GroupName = "06-Setup", Order = 2)]
        public int RejectWickTicks { get; set; }

        [NinjaScriptProperty, Range(0, 200)]
        [Display(Name = "PullbackTicks", GroupName = "06-Setup", Order = 3)]
        public int PullbackTicks { get; set; }

        [NinjaScriptProperty, Range(0, 400)]
        [Display(Name = "DriveTicks", GroupName = "06-Setup", Order = 4)]
        public int DriveTicks { get; set; }

        [NinjaScriptProperty, Range(0, 100)]
        [Display(Name = "StopBufferTicks", GroupName = "07-Orders", Order = 0)]
        public int StopBufferTicks { get; set; }

        [NinjaScriptProperty, Range(1, 400)]
        [Display(Name = "MinStopTicks", GroupName = "07-Orders", Order = 1)]
        public int MinStopTicks { get; set; }

        [NinjaScriptProperty, Range(1, 600)]
        [Display(Name = "MaxStopTicks", GroupName = "07-Orders", Order = 2)]
        public int MaxStopTicks { get; set; }

        [NinjaScriptProperty, Range(0.0, 10.0)]
        [Display(Name = "AtrStopMult", GroupName = "07-Orders", Order = 3)]
        public double AtrStopMult { get; set; }

        [NinjaScriptProperty, Range(0.1, 10.0)]
        [Display(Name = "RewardRiskRatio", GroupName = "07-Orders", Order = 4)]
        public double RewardRiskRatio { get; set; }

        [NinjaScriptProperty, Range(1, 400)]
        [Display(Name = "MinTargetTicks", GroupName = "07-Orders", Order = 5)]
        public int MinTargetTicks { get; set; }

        [NinjaScriptProperty, Range(0, 40)]
        [Display(Name = "EntryOffsetTicks", GroupName = "07-Orders", Order = 6)]
        public int EntryOffsetTicks { get; set; }

        [NinjaScriptProperty, Range(1, 30)]
        [Display(Name = "EntryTimeoutBars", GroupName = "07-Orders", Order = 7)]
        public int EntryTimeoutBars { get; set; }

        [NinjaScriptProperty, Range(0.0, 5.0)]
        [Display(Name = "MoveToBreakevenAtR", GroupName = "07-Orders", Order = 8)]
        public double MoveToBreakevenAtR { get; set; }

        [NinjaScriptProperty, Range(0, 50)]
        [Display(Name = "BreakevenPlusTicks", GroupName = "07-Orders", Order = 9)]
        public int BreakevenPlusTicks { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "UseTrailingStop", GroupName = "07-Orders", Order = 10)]
        public bool UseTrailingStop { get; set; }

        [NinjaScriptProperty, Range(0.0, 5.0)]
        [Display(Name = "TrailAfterR", GroupName = "07-Orders", Order = 11)]
        public double TrailAfterR { get; set; }

        [NinjaScriptProperty, Range(1, 200)]
        [Display(Name = "TrailDistanceTicks", GroupName = "07-Orders", Order = 12)]
        public int TrailDistanceTicks { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "UseTimeStop", GroupName = "07-Orders", Order = 13)]
        public bool UseTimeStop { get; set; }

        [NinjaScriptProperty, Range(1, 100)]
        [Display(Name = "TimeStopBars", GroupName = "07-Orders", Order = 14)]
        public int TimeStopBars { get; set; }

        [NinjaScriptProperty, Range(0.0, 2.0)]
        [Display(Name = "MinProgressR", GroupName = "07-Orders", Order = 15)]
        public double MinProgressR { get; set; }

        [NinjaScriptProperty, Range(0.01, 10.0)]
        [Display(Name = "RiskPerTradePct", GroupName = "08-Risk", Order = 0)]
        public double RiskPerTradePct { get; set; }

        [NinjaScriptProperty, Range(0, 100)]
        [Display(Name = "UserMaxContracts", GroupName = "08-Risk", Order = 1)]
        public int UserMaxContracts { get; set; }

        [NinjaScriptProperty, Range(0, 100)]
        [Display(Name = "MaxOpenPositions", GroupName = "08-Risk", Order = 2)]
        public int MaxOpenPositions { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "MaxDailyLossUsd", GroupName = "08-Risk", Order = 3)]
        public double MaxDailyLossUsd { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "MaxWeeklyLossUsd", GroupName = "08-Risk", Order = 4)]
        public double MaxWeeklyLossUsd { get; set; }

        [NinjaScriptProperty, Range(0, 100)]
        [Display(Name = "MaxTradesPerDay", GroupName = "08-Risk", Order = 5)]
        public int MaxTradesPerDay { get; set; }

        [NinjaScriptProperty, Range(0, 100)]
        [Display(Name = "HardMaxTradesPerDay", GroupName = "08-Risk", Order = 6)]
        public int HardMaxTradesPerDay { get; set; }

        [NinjaScriptProperty, Range(0, 20)]
        [Display(Name = "MaxConsecutiveLosses", GroupName = "08-Risk", Order = 7)]
        public int MaxConsecutiveLosses { get; set; }

        [NinjaScriptProperty, Range(0, 20)]
        [Display(Name = "PauseAfterConsecutiveLosses", GroupName = "08-Risk", Order = 8)]
        public int PauseAfterConsecutiveLosses { get; set; }

        [NinjaScriptProperty, Range(0, 480)]
        [Display(Name = "PauseMinutesAfterLosses", GroupName = "08-Risk", Order = 9)]
        public int PauseMinutesAfterLosses { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "RoundTurnCommission", GroupName = "08-Risk", Order = 10)]
        public double RoundTurnCommission { get; set; }

        [NinjaScriptProperty, Range(0, 100)]
        [Display(Name = "SlippageTicks", GroupName = "08-Risk", Order = 11)]
        public int SlippageTicks { get; set; }
        #endregion
    }
}
