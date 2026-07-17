"""Recorded and fault-injection market-data providers (tests / replay only).

RecordedProvider is NEVER a production failover source.
FaultInjectionProvider deliberately breaks streams for chaos tests.
"""
from __future__ import annotations

import copy
import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

from .canonical_event import make_canonical_event


class ProviderError(RuntimeError):
    pass


class MarketDataProviderBase:
    name = "base"
    data_plane_default = "display"
    production_failover_eligible = False

    def connect(self) -> None:
        return None

    def disconnect(self) -> None:
        return None

    def subscribe(self, exact_contract: str, channel: str = "trades") -> str:
        raise NotImplementedError

    def unsubscribe(self, subscription_id: str) -> None:
        return None

    def capabilities(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "production_failover_eligible": self.production_failover_eligible,
            "channels": ["trades", "bid_ask"],
            "historical": False,
            "live": False,
            "implementation_state": "TESTED_WITH_RECORDED_DATA",
            "runtime_state": "DISABLED",
            "capability": "TEST_ONLY",
            "REALTIME_PRODUCTION": False,
        }

    def health(self) -> Dict[str, Any]:
        return {"name": self.name, "ok": True}


class RecordedProvider(MarketDataProviderBase):
    """Replay a JSONL/JSON fixture of canonical-ish events."""

    name = "recorded"
    production_failover_eligible = False

    def __init__(self, path: Optional[Path] = None, events: Optional[List[Dict[str, Any]]] = None) -> None:
        self.path = Path(path) if path else None
        self._events = list(events or [])
        self._subs: Dict[str, str] = {}
        self._cursor = 0
        if self.path and self.path.is_file() and not self._events:
            self._events = self._load(self.path)

    @staticmethod
    def _load(path: Path) -> List[Dict[str, Any]]:
        text = path.read_text(encoding="utf-8-sig").strip()
        if not text:
            return []
        if path.suffix.lower() == ".jsonl":
            rows = []
            for line in text.splitlines():
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
            return rows
        doc = json.loads(text)
        if isinstance(doc, list):
            return [row for row in doc if isinstance(row, dict)]
        if isinstance(doc, dict) and isinstance(doc.get("events"), list):
            return [row for row in doc["events"] if isinstance(row, dict)]
        return []

    def subscribe(self, exact_contract: str, channel: str = "trades") -> str:
        sub_id = f"recorded:{exact_contract}:{channel}:{len(self._subs)+1}"
        self._subs[sub_id] = str(exact_contract).upper()
        return sub_id

    def replay(self, exact_contract: str = "") -> List[Dict[str, Any]]:
        wanted = str(exact_contract or "").upper()
        out: List[Dict[str, Any]] = []
        for idx, raw in enumerate(self._events):
            contract = str(raw.get("exact_contract") or raw.get("instrument") or "").upper()
            if wanted and contract and contract != wanted:
                continue
            out.append(make_canonical_event(
                event_type=str(raw.get("type") or "trade"),
                provider="recorded",
                raw_symbol=str(raw.get("raw_symbol") or contract),
                exact_contract=contract or wanted,
                canonical_symbol=str(raw.get("canonical_symbol") or ""),
                price=raw.get("price"),
                bid=raw.get("bid"),
                ask=raw.get("ask"),
                volume=raw.get("volume"),
                exchange_sequence=raw.get("exchange_sequence"),
                provider_sequence=raw.get("provider_sequence", idx + 1),
                generated_sequence=raw.get("generated_sequence", idx + 1),
                ts_event=raw.get("ts_event") or raw.get("t"),
                ts_provider=raw.get("ts_provider"),
                quality={"recorded_replay": True},
                data_plane="history_replay",
            ))
        return out

    def capabilities(self) -> Dict[str, Any]:
        caps = super().capabilities()
        caps.update({"historical": True, "live": False, "replay": True})
        return caps


class FaultInjectionProvider(MarketDataProviderBase):
    """Wraps another provider and injects delays/dupes/gaps/bad prices."""

    name = "fault_injection"
    production_failover_eligible = False

    def __init__(
        self,
        inner: Optional[MarketDataProviderBase] = None,
        *,
        delay_sec: float = 0.0,
        drop_every: int = 0,
        duplicate_every: int = 0,
        bad_price_every: int = 0,
        out_of_order_every: int = 0,
    ) -> None:
        self.inner = inner or RecordedProvider(events=[])
        self.delay_sec = float(delay_sec)
        self.drop_every = int(drop_every)
        self.duplicate_every = int(duplicate_every)
        self.bad_price_every = int(bad_price_every)
        self.out_of_order_every = int(out_of_order_every)
        self._seen = 0

    def subscribe(self, exact_contract: str, channel: str = "trades") -> str:
        return self.inner.subscribe(exact_contract, channel)

    def transform(self, events: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        pending_ooo: Optional[Dict[str, Any]] = None
        for event in events:
            self._seen += 1
            if self.delay_sec > 0:
                time.sleep(self.delay_sec)
            if self.drop_every and self._seen % self.drop_every == 0:
                continue
            row = copy.deepcopy(event)
            row["provider"] = "fault_injection"
            q = dict(row.get("quality") or {})
            q["fault_injection"] = True
            if self.bad_price_every and self._seen % self.bad_price_every == 0:
                row["price"] = -1.0
                q["bad_price"] = True
            row["quality"] = q
            if self.out_of_order_every and self._seen % self.out_of_order_every == 0:
                pending_ooo = row
                continue
            out.append(row)
            if self.duplicate_every and self._seen % self.duplicate_every == 0:
                out.append(copy.deepcopy(row))
            if pending_ooo is not None:
                out.append(pending_ooo)
                pending_ooo = None
        if pending_ooo is not None:
            out.append(pending_ooo)
        return out

    def capabilities(self) -> Dict[str, Any]:
        caps = super().capabilities()
        caps.update({
            "wraps": getattr(self.inner, "name", "unknown"),
            "delay_sec": self.delay_sec,
            "drop_every": self.drop_every,
            "duplicate_every": self.duplicate_every,
            "bad_price_every": self.bad_price_every,
            "out_of_order_every": self.out_of_order_every,
        })
        return caps
