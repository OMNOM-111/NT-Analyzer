"""Data-platform interfaces: Cache, EventBus, LockProvider, Repository.

Production target: Redis + PostgreSQL.
Local default: in-memory (+ existing file/SQLite paths elsewhere).
"""
from __future__ import annotations

import os
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any, Callable, Deque, Dict, Iterator, List, Optional, Protocol, Tuple


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

class Cache(Protocol):
    def get(self, key: str) -> Any: ...
    def set(self, key: str, value: Any, ttl_sec: Optional[float] = None) -> None: ...
    def delete(self, key: str) -> None: ...
    def stats(self) -> Dict[str, Any]: ...


@dataclass
class _Entry:
    value: Any
    expires_at: float  # 0 = never


class MemoryCache:
    def __init__(self, max_items: int = 50_000) -> None:
        self._max = max(100, max_items)
        self._data: Dict[str, _Entry] = {}
        self._lock = threading.RLock()
        self.hits = 0
        self.misses = 0

    def get(self, key: str) -> Any:
        with self._lock:
            row = self._data.get(key)
            if row is None:
                self.misses += 1
                return None
            if row.expires_at and row.expires_at < time.time():
                self._data.pop(key, None)
                self.misses += 1
                return None
            self.hits += 1
            return row.value

    def set(self, key: str, value: Any, ttl_sec: Optional[float] = None) -> None:
        expires = (time.time() + float(ttl_sec)) if ttl_sec else 0.0
        with self._lock:
            self._data[key] = _Entry(value=value, expires_at=expires)
            if len(self._data) > self._max:
                # Drop arbitrary oldest-ish keys (insertion order on CPython 3.7+).
                for old in list(self._data.keys())[: max(1, len(self._data) - self._max)]:
                    self._data.pop(old, None)

    def delete(self, key: str) -> None:
        with self._lock:
            self._data.pop(key, None)

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            total = self.hits + self.misses
            return {
                "backend": "memory",
                "items": len(self._data),
                "hits": self.hits,
                "misses": self.misses,
                "hit_rate": round(self.hits / total, 4) if total else 0.0,
            }


# ---------------------------------------------------------------------------
# Locks
# ---------------------------------------------------------------------------

class LockProvider(Protocol):
    def acquire(self, name: str, timeout_sec: float = 5.0) -> bool: ...
    def release(self, name: str) -> None: ...


class ThreadLockProvider:
    def __init__(self) -> None:
        self._locks: Dict[str, threading.Lock] = {}
        self._gate = threading.Lock()

    def _lock(self, name: str) -> threading.Lock:
        with self._gate:
            if name not in self._locks:
                self._locks[name] = threading.Lock()
            return self._locks[name]

    def acquire(self, name: str, timeout_sec: float = 5.0) -> bool:
        return self._lock(name).acquire(timeout=max(0.01, timeout_sec))

    def release(self, name: str) -> None:
        try:
            self._lock(name).release()
        except RuntimeError:
            pass


# ---------------------------------------------------------------------------
# Event bus
# ---------------------------------------------------------------------------

class EventBus(Protocol):
    def publish(self, topic: str, message: Dict[str, Any]) -> None: ...
    def subscribe(self, topic: str, callback: Callable[[Dict[str, Any]], None]) -> None: ...


class LocalEventBus:
    def __init__(self) -> None:
        self._subs: Dict[str, List[Callable[[Dict[str, Any]], None]]] = defaultdict(list)
        self._lock = threading.RLock()
        self.published = 0

    def publish(self, topic: str, message: Dict[str, Any]) -> None:
        with self._lock:
            callbacks = list(self._subs.get(topic, ()))
            wild = list(self._subs.get("*", ()))
            self.published += 1
        for cb in callbacks + wild:
            try:
                cb(message)
            except Exception:
                pass

    def subscribe(self, topic: str, callback: Callable[[Dict[str, Any]], None]) -> None:
        with self._lock:
            self._subs[topic].append(callback)


# ---------------------------------------------------------------------------
# Repository (minimal)
# ---------------------------------------------------------------------------

class Repository(Protocol):
    def put(self, collection: str, key: str, doc: Dict[str, Any]) -> None: ...
    def get(self, collection: str, key: str) -> Optional[Dict[str, Any]]: ...
    def list_keys(self, collection: str) -> List[str]: ...


class MemoryRepository:
    def __init__(self) -> None:
        self._data: Dict[str, Dict[str, Dict[str, Any]]] = defaultdict(dict)
        self._lock = threading.RLock()

    def put(self, collection: str, key: str, doc: Dict[str, Any]) -> None:
        with self._lock:
            self._data[collection][key] = dict(doc)

    def get(self, collection: str, key: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            row = self._data.get(collection, {}).get(key)
            return dict(row) if row else None

    def list_keys(self, collection: str) -> List[str]:
        with self._lock:
            return list(self._data.get(collection, {}).keys())


# ---------------------------------------------------------------------------
# Optional Redis / Postgres adapters (no hard dependency)
# ---------------------------------------------------------------------------

class RedisCache:
    """Thin wrapper; falls back construction error to caller."""

    def __init__(self, url: str) -> None:
        import redis  # type: ignore
        self._r = redis.Redis.from_url(url, decode_responses=True)
        self.hits = 0
        self.misses = 0
        self._r.ping()

    def get(self, key: str) -> Any:
        import json
        raw = self._r.get(key)
        if raw is None:
            self.misses += 1
            return None
        self.hits += 1
        try:
            return json.loads(raw)
        except Exception:
            return raw

    def set(self, key: str, value: Any, ttl_sec: Optional[float] = None) -> None:
        import json
        payload = json.dumps(value, ensure_ascii=False, default=str)
        if ttl_sec:
            self._r.setex(key, int(max(1, ttl_sec)), payload)
        else:
            self._r.set(key, payload)

    def delete(self, key: str) -> None:
        self._r.delete(key)

    def stats(self) -> Dict[str, Any]:
        total = self.hits + self.misses
        return {
            "backend": "redis",
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate": round(self.hits / total, 4) if total else 0.0,
        }


class PostgresRepository:
    def __init__(self, url: str) -> None:
        import psycopg  # type: ignore
        self._url = url
        self._conn = psycopg.connect(url, autocommit=True)
        with self._conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS dp_kv (
                  collection TEXT NOT NULL,
                  key TEXT NOT NULL,
                  doc JSONB NOT NULL,
                  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                  PRIMARY KEY (collection, key)
                )
                """
            )

    def put(self, collection: str, key: str, doc: Dict[str, Any]) -> None:
        import json
        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO dp_kv(collection, key, doc)
                VALUES (%s, %s, %s::jsonb)
                ON CONFLICT (collection, key)
                DO UPDATE SET doc = EXCLUDED.doc, updated_at = NOW()
                """,
                (collection, key, json.dumps(doc)),
            )

    def get(self, collection: str, key: str) -> Optional[Dict[str, Any]]:
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT doc FROM dp_kv WHERE collection=%s AND key=%s",
                (collection, key),
            )
            row = cur.fetchone()
            return dict(row[0]) if row else None

    def list_keys(self, collection: str) -> List[str]:
        with self._conn.cursor() as cur:
            cur.execute("SELECT key FROM dp_kv WHERE collection=%s", (collection,))
            return [r[0] for r in cur.fetchall()]


@dataclass
class Platform:
    cache: Any
    locks: Any
    bus: Any
    repo: Any
    mode: str


_PLATFORM: Optional[Platform] = None
_LOCK = threading.RLock()


def build_platform() -> Platform:
    mode = (os.environ.get("NTA_DATA_PLATFORM") or "memory").strip().lower()
    redis_url = (os.environ.get("NTA_REDIS_URL") or "").strip()
    db_url = (os.environ.get("NTA_DATABASE_URL") or "").strip()
    require_redis = os.environ.get("NTA_REQUIRE_REDIS", "0") == "1"
    require_pg = os.environ.get("NTA_REQUIRE_POSTGRES", "0") == "1"

    cache: Any = MemoryCache()
    repo: Any = MemoryRepository()
    locks: Any = ThreadLockProvider()
    bus: Any = LocalEventBus()

    if mode in {"redis", "postgres", "production"} or redis_url:
        if redis_url:
            try:
                cache = RedisCache(redis_url)
            except Exception as exc:
                if require_redis:
                    raise
                cache = MemoryCache()
                mode = f"memory_redis_unavailable:{exc.__class__.__name__}"
        elif require_redis:
            raise RuntimeError("NTA_REQUIRE_REDIS=1 but NTA_REDIS_URL is empty")

    if mode in {"postgres", "production"} or db_url:
        if db_url:
            try:
                repo = PostgresRepository(db_url)
            except Exception as exc:
                if require_pg:
                    raise
                repo = MemoryRepository()
                mode = f"{mode}|pg_unavailable:{exc.__class__.__name__}"
        elif require_pg:
            raise RuntimeError("NTA_REQUIRE_POSTGRES=1 but NTA_DATABASE_URL is empty")

    return Platform(cache=cache, locks=locks, bus=bus, repo=repo, mode=mode)


def get_platform() -> Platform:
    global _PLATFORM
    with _LOCK:
        if _PLATFORM is None:
            _PLATFORM = build_platform()
        return _PLATFORM


def reset_platform_for_tests() -> None:
    global _PLATFORM
    with _LOCK:
        _PLATFORM = None
