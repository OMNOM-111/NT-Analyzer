/* Phase 19+ hotfix5: top-right Pacific clock + CME equity-futures market status.

   Schedule (CME Globex, MES/ES):
     Sun 15:00 PT → Fri 14:00 PT (continuous, almost 24/5),
     daily maintenance halt 14:00–15:00 PT,
     Saturday closed all day,
     Sunday closed until 15:00 PT.

   Approximate; does not account for US holidays / early closes.
   Bridge does not currently expose market state, so this is computed from
   the user's clock rendered in America/Los_Angeles tz via Intl APIs.

   DOM (optional): #chip-clock, #chip-market, #cal-market-countdown.

   Shared API for trading calendar: window.NTAMarketClock
*/
(function () {
  const fmtClock = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/Los_Angeles", weekday: "short", month: "short",
    day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit",
    hour12: true
  });
  const fmtParts = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/Los_Angeles",
    weekday: "short", hour: "2-digit", minute: "2-digit",
    hour12: false
  });
  const fmtPtYmd = new Intl.DateTimeFormat("sv-SE", {
    timeZone: "America/Los_Angeles",
    year: "numeric", month: "2-digit", day: "2-digit",
  });
  const partsToObj = d => Object.fromEntries(
    fmtParts.formatToParts(d).map(p => [p.type, p.value])
  );
  const wdayIdx = { Sun:0, Mon:1, Tue:2, Wed:3, Thu:4, Fri:5, Sat:6 };

  const REASON_RU = {
    "weekend":           "выходной",
    "pre-open Sunday":   "до открытия в Вс",
    "daily maintenance halt": "тех. пауза 14:00–15:00 PT",
    "weekend close":     "пятничное закрытие",
    "unknown":           "—"
  };

  function marketState(now) {
    const p = partsToObj(now);
    const wd = wdayIdx[p.weekday];
    const h = parseInt(p.hour, 10);
    const m = parseInt(p.minute, 10);
    const mins = h * 60 + m;
    if (wd === 6) return { open: false, reason: "weekend" };
    if (wd === 0) {
      if (mins < 15 * 60) return { open: false, reason: "pre-open Sunday" };
      return { open: true };
    }
    if (wd >= 1 && wd <= 4) {
      if (mins >= 14 * 60 && mins < 15 * 60) return { open: false, reason: "daily maintenance halt" };
      return { open: true };
    }
    if (wd === 5) {
      if (mins < 14 * 60) return { open: true };
      return { open: false, reason: "weekend close" };
    }
    return { open: false, reason: "unknown" };
  }

  function nextBoundary(now, lookingForOpen) {
    for (let step = 1; step <= 60 * 24 * 4; step++) {
      const t = new Date(now.getTime() + step * 60_000);
      const s = marketState(t);
      if (lookingForOpen && s.open) return t;
      if (!lookingForOpen && !s.open) return t;
    }
    return null;
  }

  function fmtDelta(deltaMs) {
    if (deltaMs < 0) deltaMs = 0;
    const totalMin = Math.round(deltaMs / 60000);
    const h = Math.floor(totalMin / 60);
    const m = totalMin % 60;
    if (h >= 24) {
      const d = Math.floor(h / 24);
      return `${d}д ${h % 24}ч`;
    }
    return `${h}ч ${m.toString().padStart(2,"0")}м`;
  }

  function ptCalendarDate(d) {
    if (!d || isNaN(d.getTime())) return "";
    try {
      return fmtPtYmd.format(d);
    } catch (_) {
      return "";
    }
  }

  /** Trading day key aligned with CME Globex segment boundaries (same model as chip). */
  function timestampSessionDatePt(iso) {
    const d = new Date(String(iso || ""));
    if (isNaN(d.getTime())) return "";
    const s = marketState(d);
    if (s.open) {
      const close = nextBoundary(d, false);
      if (close) return ptCalendarDate(close);
    }
    return ptCalendarDate(d);
  }

  function nowSessionDatePt() {
    return timestampSessionDatePt(new Date().toISOString());
  }

  function buildMarketChip(now) {
    const s = marketState(now);
    if (s.open) {
      const close = nextBoundary(now, false);
      const left = close ? fmtDelta(close - now) : "?";
      return { open: true, text: `🟢 Рынок открыт · до закрытия ${left}` };
    }
    const open = nextBoundary(now, true);
    const left = open ? fmtDelta(open - now) : "?";
    const reason = REASON_RU[s.reason] || s.reason;
    return { open: false, text: `🔴 Рынок закрыт (${reason}) · до открытия ${left}` };
  }

  window.NTAMarketClock = {
    marketState,
    nextBoundary,
    fmtDelta,
    ptCalendarDate,
    timestampSessionDatePt,
    nowSessionDatePt,
    buildMarketChip,
  };

  function tick() {
    const now = new Date();
    const chip = buildMarketChip(now);
    const clockEl = document.getElementById("chip-clock");
    const mktEl = document.getElementById("chip-market");
    const calEl = document.getElementById("cal-market-countdown");
    if (clockEl) clockEl.textContent = fmtClock.format(now) + " PT";
    if (mktEl) {
      mktEl.className = chip.open ? "status-chip ok" : "status-chip bad";
      mktEl.textContent = chip.text;
    }
    if (calEl) {
      calEl.textContent = chip.text;
      calEl.classList.remove("eta-open", "eta-closed");
      calEl.classList.add(chip.open ? "eta-open" : "eta-closed");
    }
  }

  const hasTickTarget = () =>
    document.getElementById("chip-clock") ||
    document.getElementById("chip-market") ||
    document.getElementById("cal-market-countdown");

  if (window.__nta_marketClockDomBound) return;
  if (!hasTickTarget()) return;
  window.__nta_marketClockDomBound = true;

  if (!document.getElementById("nta-market-clock-style")) {
    const st = document.createElement("style");
    st.id = "nta-market-clock-style";
    st.textContent = `
      #chip-clock { font-variant-numeric: tabular-nums; }
      #chip-market.ok   { background:#1f6b3a !important; color:#dfffea !important; }
      #chip-market.bad  { background:#7a1f1f !important; color:#ffd6d6 !important; }
      #chip-market.warn { background:#a07a1f !important; color:#fff2cc !important; }
      #cal-market-countdown {
        font-size: 10px; font-weight: 600; font-variant-numeric: tabular-nums;
        max-width: min(240px, 38vw); white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
        flex-shrink: 1; min-width: 0; text-align: right;
      }
      #cal-market-countdown.eta-open { color: #73e59a; }
      #cal-market-countdown.eta-closed { color: #ff9b9b; }
    `;
    document.head.appendChild(st);
  }

  tick();
  setInterval(tick, 1000);
})();
