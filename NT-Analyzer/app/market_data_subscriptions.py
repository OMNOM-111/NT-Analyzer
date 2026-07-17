"""Upstream subscription registry with reference counting (fan-in).

One upstream stream per (provider, exact_contract, channel), independent of
users, windows, and timeframes.
"""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional, Tuple

UpstreamKey = Tuple[str, str, str]


@dataclass
class UpstreamSubscription:
    provider: str
    exact_contract: str
    channel: str
    subscription_id: str
    refcount: int = 0
    created_at_mono: float = field(default_factory=time.monotonic)
    last_release_mono: float = 0.0
    active: bool = True

    def key(self) -> UpstreamKey:
        return (self.provider, self.exact_contract.upper(), self.channel)


class SubscriptionRegistry:
    def __init__(self, cooldown_sec: float = 5.0) -> None:
        self.cooldown_sec = cooldown_sec
        self._lock = threading.RLock()
        self._subs: Dict[UpstreamKey, UpstreamSubscription] = {}
        self._create_hook: Optional[Callable[[UpstreamSubscription], None]] = None
        self._close_hook: Optional[Callable[[UpstreamSubscription], None]] = None
        self.stats = {
            "acquires": 0,
            "releases": 0,
            "creates": 0,
            "closes": 0,
            "joins": 0,
        }

    def set_hooks(
        self,
        on_create: Optional[Callable[[UpstreamSubscription], None]] = None,
        on_close: Optional[Callable[[UpstreamSubscription], None]] = None,
    ) -> None:
        self._create_hook = on_create
        self._close_hook = on_close

    def acquire(self, provider: str, exact_contract: str, channel: str = "trades") -> UpstreamSubscription:
        key = (str(provider).lower(), str(exact_contract).upper(), str(channel).lower())
        with self._lock:
            self.stats["acquires"] += 1
            sub = self._subs.get(key)
            if sub and sub.active:
                sub.refcount += 1
                self.stats["joins"] += 1
                return sub
            sub = UpstreamSubscription(
                provider=key[0],
                exact_contract=key[1],
                channel=key[2],
                subscription_id=f"ups-{uuid.uuid4().hex[:12]}",
                refcount=1,
                active=True,
            )
            self._subs[key] = sub
            self.stats["creates"] += 1
            hook = self._create_hook
        if hook:
            try:
                hook(sub)
            except Exception:
                pass
        return sub

    def release(self, provider: str, exact_contract: str, channel: str = "trades") -> Optional[UpstreamSubscription]:
        key = (str(provider).lower(), str(exact_contract).upper(), str(channel).lower())
        close_sub = None
        with self._lock:
            self.stats["releases"] += 1
            sub = self._subs.get(key)
            if not sub:
                return None
            sub.refcount = max(0, sub.refcount - 1)
            sub.last_release_mono = time.monotonic()
            if sub.refcount == 0:
                # Cooldown: mark inactive now; physical close after cooldown via sweep.
                sub.active = False
                close_sub = sub
                self.stats["closes"] += 1
                self._subs.pop(key, None)
            else:
                return sub
        if close_sub and self._close_hook:
            try:
                self._close_hook(close_sub)
            except Exception:
                pass
        return close_sub

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            rows = [
                {
                    "provider": s.provider,
                    "exact_contract": s.exact_contract,
                    "channel": s.channel,
                    "subscription_id": s.subscription_id,
                    "refcount": s.refcount,
                    "active": s.active,
                }
                for s in self._subs.values()
            ]
            return {
                "upstream_count": len(rows),
                "subscriptions": rows,
                "stats": dict(self.stats),
            }


_REGISTRY: Optional[SubscriptionRegistry] = None
_GATE = threading.Lock()


def get_subscription_registry() -> SubscriptionRegistry:
    global _REGISTRY
    with _GATE:
        if _REGISTRY is None:
            _REGISTRY = SubscriptionRegistry()
        return _REGISTRY


def reset_subscription_registry_for_tests() -> None:
    global _REGISTRY
    with _GATE:
        _REGISTRY = None
