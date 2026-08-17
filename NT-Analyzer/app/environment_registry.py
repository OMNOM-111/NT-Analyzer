"""Environment registry: environments publish, they are not polled.

The Environment Switcher used to learn about an environment only by reaching
out and asking it over HTTP, right then. That produced two wrong answers.

**LOCAL was permanently unknown.** The owner's development machine sits behind
NAT. No server-side probe can reach it, so LOCAL reported "unknown" the entire
time it was up and serving.

**A momentary network failure erased the truth.** An environment that could not
be reached this second reported "unknown" for its version, commit and artifact
-- facts that were true a minute ago and were still the best information
anyone had. A dash is not more honest than a timestamped fact; it is less.

So each environment pushes an authenticated heartbeat carrying its own runtime
identity, and the registry keeps the most recent one. Two consequences follow,
and they are the whole design:

* **Reachability is derived from time, never from the metadata.** ``live``,
  ``stale`` and ``offline`` come from ``last_seen_at`` alone. The build fields
  are what was last reported and are never blanked out because the environment
  went quiet.
* **Every reading is stamped.** An offline environment shows its last-known
  build *as of* a specific moment, so nobody mistakes a stale fact for a
  current one.

The heartbeat carries no secrets and is authenticated by a shared token that is
compared in constant time and never logged, echoed or returned.
"""
from __future__ import annotations

import hmac
import os
import re
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from . import runtime_env


ENVIRONMENTS = (runtime_env.DEVELOPMENT, runtime_env.CANARY, runtime_env.PRODUCTION)

# An environment is expected to beat well inside this. Two thresholds rather
# than one, because "quiet for 90 seconds" and "quiet since yesterday" are
# genuinely different situations and collapsing them loses the distinction the
# operator actually needs.
LIVE_WINDOW_SEC = 90
STALE_WINDOW_SEC = 15 * 60
HEARTBEAT_MIN_INTERVAL_SEC = 20

STATE_LIVE = "live"
STATE_STALE = "stale"
STATE_OFFLINE = "offline"
STATE_NEVER_SEEN = "never_seen"

_TOKEN_ENV = "STRATFORGE_ENVIRONMENT_REGISTRY_TOKEN"
_MIN_TOKEN_LEN = 32

_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_READINESS = ("", "ready", "degraded", "not_ready")
_DETAILS_MAX_KEYS = 20
_DETAILS_MAX_VALUE = 200


class EnvironmentRegistryError(RuntimeError):
    def __init__(self, message: str, status: int = 400, *, code: str = ""):
        super().__init__(message)
        self.status = int(status)
        self.code = str(code or "")


# --------------------------------------------------------------------------- #
# Authentication.
# --------------------------------------------------------------------------- #
def token() -> str:
    return str(os.environ.get(_TOKEN_ENV) or "").strip()


def token_configured() -> bool:
    return len(token()) >= _MIN_TOKEN_LEN


def token_matches(supplied: Any) -> bool:
    """Constant-time comparison. Never logs, echoes or returns either value."""
    expected = token()
    value = str(supplied or "").strip()
    if len(expected) < _MIN_TOKEN_LEN or len(value) != len(expected):
        return False
    return hmac.compare_digest(value, expected)


# --------------------------------------------------------------------------- #
# Validation.
#
# A heartbeat is input from another host, so every field is checked here rather
# than trusted because it arrived over an authenticated channel. Authentication
# says who sent it, not that what they sent is well formed.
# --------------------------------------------------------------------------- #
def _text(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit]


def _normalize_details(raw: Any) -> Dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    out: Dict[str, str] = {}
    for key in sorted(raw)[:_DETAILS_MAX_KEYS]:
        name = _text(key, 40)
        if not name:
            continue
        out[name] = _text(raw[key], _DETAILS_MAX_VALUE)
    return out


def normalize_heartbeat(payload: Any) -> Dict[str, Any]:
    """Validate a reported runtime identity into exactly the stored shape."""
    if not isinstance(payload, dict):
        raise EnvironmentRegistryError(
            "Тело heartbeat должно быть объектом.", 400, code="heartbeat_invalid",
        )
    environment = str(payload.get("environment") or "").strip().lower()
    if environment not in ENVIRONMENTS:
        raise EnvironmentRegistryError(
            "Неизвестное окружение.", 400, code="environment_unknown",
        )
    artifact = str(payload.get("artifact_sha256") or "").strip()
    if artifact and not _SHA256_RE.match(artifact):
        raise EnvironmentRegistryError(
            "artifact_sha256 должен быть sha256.", 400, code="artifact_invalid",
        )
    readiness = str(payload.get("readiness") or "").strip().lower()
    if readiness not in _READINESS:
        raise EnvironmentRegistryError(
            "Недопустимое значение readiness.", 400, code="readiness_invalid",
        )
    try:
        schema_version = int(payload.get("schema_version") or 0)
    except (TypeError, ValueError):
        schema_version = -1
    if schema_version < 0:
        raise EnvironmentRegistryError(
            "schema_version должен быть неотрицательным.", 400, code="schema_version_invalid",
        )
    return {
        "environment": environment,
        "app_version": _text(payload.get("app_version"), 64),
        "git_commit_sha": _text(payload.get("git_commit_sha"), 64),
        "build_id": _text(payload.get("build_id"), 128),
        "artifact_sha256": artifact.lower(),
        "release_channel": _text(payload.get("release_channel"), 32),
        "schema_version": schema_version,
        "readiness": readiness,
        "details": _normalize_details(payload.get("details")),
    }


# --------------------------------------------------------------------------- #
# Derived reachability.
# --------------------------------------------------------------------------- #
def _now() -> float:
    return time.time()


def _epoch(value: Any) -> float:
    if isinstance(value, datetime):
        moment = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return moment.timestamp()
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _iso(value: Any) -> str:
    epoch = _epoch(value)
    if epoch <= 0:
        return ""
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat(
        timespec="seconds").replace("+00:00", "Z")


def liveness(last_seen: Any, *, now: Optional[float] = None) -> Dict[str, Any]:
    """Reachability from time alone.

    Deliberately independent of the reported metadata: an environment that has
    not checked in is not an environment whose version has become unknown.
    """
    moment = _now() if now is None else float(now)
    seen = _epoch(last_seen)
    if seen <= 0:
        return {"state": STATE_NEVER_SEEN, "age_sec": None}
    age = max(0.0, moment - seen)
    if age <= LIVE_WINDOW_SEC:
        state = STATE_LIVE
    elif age <= STALE_WINDOW_SEC:
        state = STATE_STALE
    else:
        state = STATE_OFFLINE
    return {"state": state, "age_sec": int(age)}


def public_row(row: Dict[str, Any], *, now: Optional[float] = None) -> Dict[str, Any]:
    """One environment as the switcher renders it.

    ``metadata_is_current`` exists so the UI never has to infer whether it is
    looking at a fact or a memory: an offline environment still shows its build,
    and this says plainly that the build is as of ``last_seen_at_utc``.
    """
    live = liveness(row.get("last_seen_at"), now=now)
    known = live["state"] != STATE_NEVER_SEEN
    return {
        "environment": str(row.get("environment") or ""),
        "state": live["state"],
        "age_sec": live["age_sec"],
        "first_seen_at_utc": _iso(row.get("first_seen_at")),
        "last_seen_at_utc": _iso(row.get("last_seen_at")),
        "heartbeat_count": int(row.get("heartbeat_count") or 0),
        # Last known, never blanked because the environment went quiet.
        "app_version": str(row.get("app_version") or ""),
        "git_commit_sha": str(row.get("git_commit_sha") or ""),
        "build_id": str(row.get("build_id") or ""),
        "artifact_sha256": str(row.get("artifact_sha256") or ""),
        "release_channel": str(row.get("release_channel") or ""),
        "schema_version": int(row.get("schema_version") or 0),
        "readiness": str(row.get("readiness") or ""),
        "details": row.get("details") if isinstance(row.get("details"), dict) else {},
        "metadata_is_current": live["state"] == STATE_LIVE,
        "metadata_known": known,
    }


def empty_row(environment: str) -> Dict[str, Any]:
    """An environment that has never reported.

    Still listed, and still distinguishable from one that reported and went
    quiet -- ``never_seen`` and ``offline`` are different facts.
    """
    return {
        "environment": environment,
        "app_version": "",
        "git_commit_sha": "",
        "build_id": "",
        "artifact_sha256": "",
        "release_channel": "",
        "schema_version": 0,
        "readiness": "",
        "first_seen_at": None,
        "last_seen_at": None,
        "heartbeat_count": 0,
        "details": {},
    }


# --------------------------------------------------------------------------- #
# Storage.
#
# Canary and Production keep the registry in PostgreSQL. Development keeps it in
# memory: LOCAL is a single process on the owner's machine, it is the publisher
# rather than the collector, and giving it a persistent registry would only
# create a third place where "what is Canary running" is written down.
# --------------------------------------------------------------------------- #
_LOCAL: Dict[str, Dict[str, Any]] = {}


def _authoritative() -> bool:
    from . import storage_router

    return storage_router.production_enabled()


def record(payload: Any) -> Dict[str, Any]:
    """Validate and store one heartbeat. Returns the public view of the row."""
    heartbeat = normalize_heartbeat(payload)
    if _authoritative():
        from . import storage_router
        from .production_storage import StorageError

        try:
            row = storage_router.record_environment_heartbeat(heartbeat)
        except StorageError as exc:
            raise EnvironmentRegistryError(
                f"Реестр окружений недоступен ({exc.code}).", 503, code=exc.code,
            ) from None
        return public_row(row)

    now = _now()
    existing = _LOCAL.get(heartbeat["environment"]) or {}
    row = dict(heartbeat)
    row["first_seen_at"] = existing.get("first_seen_at") or now
    row["last_seen_at"] = now
    row["heartbeat_count"] = int(existing.get("heartbeat_count") or 0) + 1
    _LOCAL[heartbeat["environment"]] = row
    return public_row(row)


def snapshot() -> Dict[str, Any]:
    """Every environment, with its liveness and its last-known build.

    Environments that have never reported are listed too, as ``never_seen``,
    rather than omitted -- a missing row would read as "there is no such
    environment" instead of "we have not heard from it".
    """
    if _authoritative():
        from . import storage_router
        from .production_storage import StorageError

        try:
            stored = storage_router.read_environment_registry()
        except StorageError as exc:
            raise EnvironmentRegistryError(
                f"Реестр окружений недоступен ({exc.code}).", 503, code=exc.code,
            ) from None
    else:
        stored = list(_LOCAL.values())

    by_env = {str(row.get("environment") or ""): row for row in stored}
    now = _now()
    rows = [
        public_row(by_env.get(environment) or empty_row(environment), now=now)
        for environment in ENVIRONMENTS
    ]
    return {
        "ok": True,
        "environments": rows,
        "compare": compare(rows),
        "policy": {
            "live_window_sec": LIVE_WINDOW_SEC,
            "stale_window_sec": STALE_WINDOW_SEC,
            "heartbeat_min_interval_sec": HEARTBEAT_MIN_INTERVAL_SEC,
        },
    }


def reset_for_tests() -> None:
    _LOCAL.clear()
    _PUBLISH_STATE.clear()


# --------------------------------------------------------------------------- #
# Publishing.
#
# What an environment says about itself, and where it says it.
# --------------------------------------------------------------------------- #
def self_heartbeat(*, readiness: Optional[Any] = None) -> Dict[str, Any]:
    """This process's own runtime identity, in heartbeat shape.

    Everything comes from the deployment config the process was started with.
    Nothing is asked of the caller, so an environment cannot be made to
    misreport itself by anything arriving over the network.

    ``readiness`` is the supplier the HTTP server uses for ``/api/ready``. It
    has to be passed in: readiness is only meaningful with the component probes
    the server registered at startup, and computing it here without them
    reported a perfectly healthy Production as ``not_ready``.
    """
    deployment = runtime_env.public_status()
    payload = {
        "environment": runtime_env.deployment_environment(),
        "app_version": deployment.get("app_version") or deployment.get("build_version"),
        "git_commit_sha": deployment.get("git_commit_sha"),
        "build_id": deployment.get("build_id"),
        "artifact_sha256": deployment.get("artifact_sha256"),
        "release_channel": deployment.get("release_channel"),
        "schema_version": _schema_version(),
        "readiness": _readiness(readiness),
        "details": {
            "runtime_profile": deployment.get("runtime_profile"),
            "region": deployment.get("region"),
            "build_timestamp_utc": deployment.get("build_timestamp_utc"),
        },
    }
    return normalize_heartbeat(payload)


def _schema_version() -> int:
    """Applied migration version, or 0 where there is no relational store.

    Reported rather than probed from outside, because it is the one field in the
    comparison that an external HTTP probe genuinely cannot see.
    """
    try:
        from . import storage_router

        if not storage_router.production_enabled():
            return 0
        return int(storage_router.applied_schema_version())
    except Exception:
        return 0


def _readiness(supplier: Optional[Any] = None) -> str:
    """Readiness as this process actually reports it, or nothing at all.

    Without the server's registered component probes the answer is not merely
    approximate, it is wrong: the required components look absent and a healthy
    service reports ``not_ready``. So when there is no supplier the field is
    left empty, and the compare view shows it as "not reported" rather than as
    a fault that does not exist.
    """
    if supplier is None:
        return ""
    try:
        payload = supplier()
        status = str((payload or {}).get("status") or "").strip().lower()
        return status if status in _READINESS else ""
    except Exception:
        return ""


# Per-target throttle, so a busy process cannot turn the registry into a write
# loop. Keyed by target so a slow peer never starves the others.
_PUBLISH_STATE: Dict[str, float] = {}


def _due(key: str, *, now: Optional[float] = None) -> bool:
    moment = _now() if now is None else float(now)
    last = _PUBLISH_STATE.get(key, 0.0)
    if moment - last < HEARTBEAT_MIN_INTERVAL_SEC:
        return False
    _PUBLISH_STATE[key] = moment
    return True


def publish_local(*, force: bool = False, readiness: Optional[Any] = None) -> Optional[Dict[str, Any]]:
    """Record this environment's own identity in its own registry."""
    if not force and not _due("self"):
        return None
    return record(self_heartbeat(readiness=readiness))


HEARTBEAT_PATH = "/api/environments/heartbeat"
_PUBLISH_TIMEOUT_SEC = 4.0


def publish_to(origin: str, *, force: bool = False,
               readiness: Optional[Any] = None) -> Dict[str, Any]:
    """Push this environment's identity to one peer.

    Returns a result rather than raising: a peer being down is an ordinary
    condition, and one unreachable peer must not stop the others from being
    told. The token goes in a header, never in the URL -- query strings end up
    in access logs and proxy caches.
    """
    import json
    import urllib.error
    import urllib.request

    target = str(origin or "").strip().rstrip("/")
    if not target:
        return {"ok": False, "code": "origin_missing"}
    if not token_configured():
        return {"ok": False, "code": "token_not_configured"}
    if not force and not _due("peer:" + target):
        return {"ok": False, "code": "throttled"}

    body = json.dumps(self_heartbeat(readiness=readiness), ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        target + HEARTBEAT_PATH,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-StratForge-Registry-Token": token(),
            "User-Agent": "StratForge-Environment-Heartbeat/1",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=_PUBLISH_TIMEOUT_SEC) as response:
            response.read(64 * 1024)
        return {"ok": True, "code": "published"}
    except urllib.error.HTTPError as exc:
        # The status is useful; the body is a remote host's text and is not
        # propagated.
        return {"ok": False, "code": "http_%d" % int(exc.code)}
    except Exception as exc:
        return {"ok": False, "code": type(exc).__name__}


def peer_origins() -> List[str]:
    """Where this environment publishes, from configuration only.

    Never from a heartbeat or any other network input: an environment that
    could name its own peers could redirect every other environment's identity
    report to a host of its choosing.
    """
    raw = str(os.environ.get("STRATFORGE_ENVIRONMENT_REGISTRY_PEERS") or "")
    origins = []
    for chunk in re.split(r"[,\s]+", raw):
        origin = chunk.strip().rstrip("/")
        if origin.startswith("https://") or origin.startswith("http://127.0.0.1:"):
            if origin not in origins:
                origins.append(origin)
    return origins


def publish_round(*, force: bool = False, readiness: Optional[Any] = None) -> Dict[str, Any]:
    """One publishing pass: record locally, then tell every configured peer."""
    results: Dict[str, Any] = {"local": None, "peers": {}}
    try:
        results["local"] = publish_local(force=force, readiness=readiness)
    except EnvironmentRegistryError as exc:
        results["local"] = {"error": exc.code}
    for origin in peer_origins():
        results["peers"][origin] = publish_to(origin, force=force, readiness=readiness)
    return results


class HeartbeatPublisher:
    """Publishes this environment's identity on a timer.

    Failures are swallowed by design: an unreachable peer must not take the
    server down or spam the log on every tick. What went wrong is visible in the
    registry itself, as the peer's ``last_seen_at`` falling behind.
    """

    def __init__(self, interval_sec: float = 30.0,
                 readiness: Optional[Any] = None) -> None:
        self.interval_sec = max(5.0, float(interval_sec))
        # The same supplier /api/ready uses, so the two can never disagree.
        self.readiness = readiness
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.last_result: Dict[str, Any] = {}

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name="environment-heartbeat", daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.last_result = publish_round(force=True, readiness=self.readiness)
            except Exception:
                pass
            self._stop.wait(self.interval_sec)


# --------------------------------------------------------------------------- #
# Compare.
# --------------------------------------------------------------------------- #
_COMPARED_FIELDS = (
    ("app_version", "Версия"),
    ("git_commit_sha", "Commit"),
    ("artifact_sha256", "Артефакт"),
    ("release_channel", "Канал"),
    ("schema_version", "Схема БД"),
)


def compare(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Field-by-field comparison across environments.

    Only environments that have actually reported take part. An environment
    nobody has ever heard from would otherwise contribute an empty string and
    make every field look like a disagreement, which is the opposite of useful.

    A field is ``differs`` when the environments that reported it disagree.
    Blank values are excluded from that judgement: "Canary has not told us its
    schema version" is missing data, not a mismatch, and calling it one would
    train the operator to ignore the whole panel.
    """
    known = [row for row in rows if row.get("metadata_known")]
    fields = []
    for key, label in _COMPARED_FIELDS:
        values = {row["environment"]: row.get(key) for row in known}
        stated = [v for v in values.values() if v not in ("", 0, None)]
        fields.append({
            "field": key,
            "label": label,
            "values": values,
            "differs": len(set(stated)) > 1,
            "missing": [env for env, value in values.items() if value in ("", 0, None)],
        })
    return {
        "fields": fields,
        "environments": [row["environment"] for row in known],
        # Canary and Production running the same immutable artifact is the one
        # comparison this project actually gates releases on, so it is answered
        # directly rather than left for the reader to spot in the table.
        "canary_production_parity": _parity(known),
    }


def _parity(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_env = {row["environment"]: row for row in rows}
    canary = by_env.get(runtime_env.CANARY)
    production = by_env.get(runtime_env.PRODUCTION)
    if not canary or not production:
        return {"known": False, "match": False, "reason": "not_both_reported"}
    left = str(canary.get("artifact_sha256") or "")
    right = str(production.get("artifact_sha256") or "")
    if not left or not right:
        return {"known": False, "match": False, "reason": "artifact_not_reported"}
    return {
        "known": True,
        "match": left.lower() == right.lower(),
        "reason": "",
        # Both readings are stamped: parity between two stale reports is a
        # weaker statement than parity between two live ones, and the caller
        # must be able to tell which it has.
        "canary_as_of_utc": canary.get("last_seen_at_utc"),
        "production_as_of_utc": production.get("last_seen_at_utc"),
        "both_current": bool(canary.get("metadata_is_current")
                             and production.get("metadata_is_current")),
    }
