"""Background refresh lifecycle for calendar and live market headlines."""
from __future__ import annotations

import os
import threading
import time
from typing import Optional

from app import market_events, market_news


_start_lock = threading.Lock()
_thread: Optional[threading.Thread] = None


def _seconds(name: str, default: int, minimum: int) -> int:
    try:
        return max(minimum, int(os.environ.get(name, str(default))))
    except (TypeError, ValueError):
        return default


def _worker(live_interval_sec: int, calendar_interval_sec: int) -> None:
    next_calendar = time.monotonic() + calendar_interval_sec
    while True:
        try:
            market_news.write_live_news()
        except Exception as exc:  # pragma: no cover - network/filesystem dependent
            print(f"[nta-news] live refresh failed: {exc}")
        now = time.monotonic()
        if now >= next_calendar:
            try:
                market_events.write_news_json()
            except Exception as exc:  # pragma: no cover - filesystem dependent
                print(f"[nta-news] calendar refresh failed: {exc}")
            next_calendar = now + calendar_interval_sec
        time.sleep(live_interval_sec)


def start_background_refresher() -> threading.Thread:
    """Refresh the local calendar now and live headlines on a daemon thread."""
    global _thread
    with _start_lock:
        if _thread is not None and _thread.is_alive():
            return _thread
        # Calendar generation is local and fast; complete it before the first
        # UI request so a restart never serves stale guessed dates.
        market_events.write_news_json()
        live_interval = _seconds("NTA_NEWS_REFRESH_SEC", 900, 60)
        calendar_interval = _seconds("NTA_CALENDAR_REFRESH_SEC", 21600, 300)
        _thread = threading.Thread(
            target=_worker,
            args=(live_interval, calendar_interval),
            name="nta-news-refresh",
            daemon=True,
        )
        _thread.start()
        return _thread
