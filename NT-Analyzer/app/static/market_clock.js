/* Phase 19+ hotfix5: top-right Pacific clock + CME equity-futures market status.

   Schedule (CME Globex, MES/ES):
     Sun 15:00 PT → Fri 14:00 PT (continuous, almost 24/5),
     daily maintenance halt 14:00–15:00 PT,
     Saturday closed all day,
     Sunday closed until 15:00 PT.

   Approximate; does not account for US holidays / early closes.
   Bridge does not currently expose market state, so this is computed from
   the user's clock rendered in America/Los_Angeles tz via Intl APIs.

   Required DOM: #chip-clock and #chip-market (any other parent is fine).
*/
(function () {
  if (window.__nta_marketClockInit) return;
  window.__nta_marketClockInit = true;

  function getClockEl()  { return document.getElementById("chip-clock"); }
  function getMarketEl() { return document.getElementById("chip-market"); }
  if (!getClockEl() && !getMarketEl()) return;

  // Inject minimal style so chip colors work on any page that includes us.
  if (!document.getElementById("nta-market-clock-style")) {
    const st = document.createElement("style");
    st.id = "nta-market-clock-style";
    st.textContent = `
      #chip-clock { font-variant-numeric: tabular-nums; }
      #chip-market.ok   { background:#1f6b3a !important; color:#dfffea !important; }
      #chip-market.bad  { background:#7a1f1f !important; color:#ffd6d6 !important; }
      #chip-market.warn { background:#a07a1f !important; color:#fff2cc !important; }
    `;
    document.head.appendChild(st);
  }

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

  function tick() {
    const now = new Date();
    const clockEl = getClockEl();
    const mktEl   = getMarketEl();
    if (clockEl) clockEl.textContent = fmtClock.format(now) + " PT";
    if (mktEl) {
      const s = marketState(now);
      if (s.open) {
        const close = nextBoundary(now, false);
        const left = close ? fmtDelta(close - now) : "?";
        mktEl.className = "status-chip ok";
        mktEl.textContent = `🟢 Рынок открыт · до закрытия ${left}`;
      } else {
        const open = nextBoundary(now, true);
        const left = open ? fmtDelta(open - now) : "?";
        const reason = REASON_RU[s.reason] || s.reason;
        mktEl.className = "status-chip bad";
        mktEl.textContent = `🔴 Рынок закрыт (${reason}) · до открытия ${left}`;
      }
    }
  }
  tick();
  setInterval(tick, 1000);
})();
