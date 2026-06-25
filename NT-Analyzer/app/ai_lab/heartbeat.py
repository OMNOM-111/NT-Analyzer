"""Heartbeat helper: emits ``heartbeat=True`` activity entries while a
long-running stage (LM Studio HTTP, compile wait, etc.) is in flight."""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from typing import Iterator

from . import activity


@contextmanager
def heartbeat(
    experiment_id: str,
    stage: str,
    action: str,
    *,
    every_sec: float = 10.0,
) -> Iterator[None]:
    stop = threading.Event()
    started = time.time()

    def _beat() -> None:
        while not stop.wait(every_sec):
            try:
                activity.log(
                    experiment_id,
                    stage,
                    action,
                    level="info",
                    heartbeat=True,
                    elapsed_sec=int(time.time() - started),
                )
            except Exception:
                # Heartbeat must never break the host stage.
                pass

    t = threading.Thread(target=_beat, daemon=True, name=f"hb-{experiment_id[:16]}")
    t.start()
    try:
        yield
    finally:
        stop.set()
