"""LM Studio HTTP client.

Talks to a local LM Studio OpenAI-compatible server. Routes requests to
specific roles -> model ids. Logs every prompt/response to
``ai_lab/registry/prompts_log/<date>.jsonl`` for full audit.

Roles:
    - "judge"     -> qwen/qwen3.6-35b-a3b      (analyst, reasoning, scoring)
    - "coder"     -> gpt-oss-20b               (code drafter / reviewer)
    - "embedder"  -> text-embedding-nomic-embed-text-v1.5
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Dict, List, Optional

from . import paths
from .io_utils import append_jsonl

# LM Studio is intentionally bound to IPv4 loopback by the local launcher.
# On Windows, ``localhost`` may resolve to ``::1`` first; urllib can then sit
# on an unreachable IPv6 socket until the model-probe timeout even though
# 127.0.0.1:1234 is healthy.
DEFAULT_BASE_URL = "http://127.0.0.1:1234/v1"
DEFAULT_CHAT_TIMEOUT = int(os.environ.get("LM_STUDIO_CHAT_TIMEOUT", "120"))
DEFAULT_JUDGE_TIMEOUT = int(os.environ.get("LM_STUDIO_JUDGE_TIMEOUT", "180"))
DEFAULT_CODER_TIMEOUT = int(os.environ.get("LM_STUDIO_CODER_TIMEOUT", "480"))
DEFAULT_CHAT_RETRIES = int(os.environ.get("LM_STUDIO_CHAT_RETRIES", "0"))
DEFAULT_MODEL_PROBE_TIMEOUT = int(os.environ.get("AI_LAB_MODEL_PROBE_TIMEOUT", "60"))
READINESS_CACHE_TTL_SEC = int(os.environ.get("AI_LAB_READINESS_CACHE_SEC", "60"))
RUN_REQUIRED_ROLES = ("judge", "coder", "compile_error_fixer")

_READINESS_CACHE: Optional[Dict[str, Any]] = None
_READINESS_CACHE_AT: float = 0.0

MODEL_ROUTES = {
    "judge": "qwen/qwen3.6-35b-a3b",
    "coder": "openai/gpt-oss-20b",
    "code_reviewer": "openai/gpt-oss-20b",
    "compile_error_fixer": "openai/gpt-oss-20b",
    "embedder": "text-embedding-nomic-embed-text-v1.5",
}

MODEL_ROLE_ALIASES = {
    # The current orchestrator calls the hypothesis stage "judge"; the user
    # editable role file calls that lane "idea_generator".
    "judge": "idea_generator",
    "coder": "code_writer",
    "embedder": "embedding_model",
}


class LMStudioError(RuntimeError):
    pass


class LMStudioCancelled(LMStudioError):
    """Raised when the caller's cancel_event was set before/between attempts."""


class LMStudioGenerationFailed(LMStudioError):
    """The server answered/was reachable, but no contract-valid artifact was returned."""


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _today_log() -> Any:
    paths.ensure_dirs()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return paths.PROMPTS_LOG_DIR / f"{today}.jsonl"


def _post(url: str, payload: Dict[str, Any], timeout: int) -> Dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST",
                                  headers={"Content-Type": "application/json", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise LMStudioError(f"Non-JSON response: {raw[:400]}") from e


def _get(url: str, timeout: int) -> Dict[str, Any]:
    req = urllib.request.Request(url, method="GET", headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise LMStudioError(f"Non-JSON response: {raw[:400]}") from e


def base_url() -> str:
    return os.environ.get("LM_STUDIO_BASE_URL", DEFAULT_BASE_URL).rstrip("/")


@lru_cache(maxsize=1)
def model_roles() -> Dict[str, str]:
    p = paths.AI_LAB_DIR / "model_roles.json"
    try:
        data = json.loads(p.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items() if isinstance(v, str) and v.strip()}


def model_for(role: str) -> str:
    override = os.environ.get(f"LM_STUDIO_MODEL_{role.upper()}")
    if override:
        return override
    configured = model_roles()
    if role in configured:
        return configured[role]
    alias = MODEL_ROLE_ALIASES.get(role)
    if alias and alias in configured:
        return configured[alias]
    if role in MODEL_ROUTES:
        return MODEL_ROUTES[role]
    raise LMStudioError(f"Unknown model role: {role}")


def list_models(timeout: int = 10) -> List[str]:
    try:
        data = _get(f"{base_url()}/models", timeout=timeout)
    except (urllib.error.URLError, urllib.error.HTTPError, LMStudioError) as e:
        raise LMStudioError(f"models list failed: {e}") from e
    return [m.get("id") for m in data.get("data", []) if m.get("id")]


def health(timeout: int = 5) -> Dict[str, Any]:
    out: Dict[str, Any] = {"base_url": base_url(), "available": False, "models": [], "missing_roles": []}
    try:
        models = list_models(timeout=timeout)
    except LMStudioError as e:
        out["error"] = str(e)
        return out
    out["available"] = True
    out["models"] = models
    configured = model_roles()
    if configured:
        for role, mid in configured.items():
            if role == "embedding_model":
                continue
            if mid not in models:
                out["missing_roles"].append({"role": role, "expected_model": mid})
    else:
        for role, mid in MODEL_ROUTES.items():
            if mid not in models and os.environ.get(f"LM_STUDIO_MODEL_{role.upper()}") not in models:
                out["missing_roles"].append({"role": role, "expected_model": mid})
    out["timeouts"] = {
        "chat_sec": DEFAULT_CHAT_TIMEOUT,
        "judge_sec": DEFAULT_JUDGE_TIMEOUT,
        "coder_sec": DEFAULT_CODER_TIMEOUT,
        "retries": DEFAULT_CHAT_RETRIES,
    }
    return out


def reset_readiness_cache_for_tests() -> None:
    """Clear cached UI/run readiness probe (tests only)."""
    global _READINESS_CACHE, _READINESS_CACHE_AT
    _READINESS_CACHE = None
    _READINESS_CACHE_AT = 0.0


def _missing_run_roles(health_out: Dict[str, Any]) -> List[Dict[str, str]]:
    """Roles required to start a run that are absent from /v1/models."""
    models = set(health_out.get("models") or [])
    missing: List[Dict[str, str]] = []
    for role in RUN_REQUIRED_ROLES:
        try:
            model_id = model_for(role)
        except LMStudioError as exc:
            missing.append({"role": role, "model": "", "error": str(exc)})
            continue
        if model_id not in models:
            missing.append({"role": role, "model": model_id})
    return missing


def _readiness_message(status: str, *, missing_run: Optional[List[Dict[str, str]]] = None) -> str:
    if status == "server_unavailable":
        return "LM Studio недоступна — запустите сервер (порт 1234)."
    if status == "models_not_listed":
        parts = [f"{m.get('role')} ({m.get('model')})" for m in (missing_run or [])]
        detail = ", ".join(parts) if parts else "judge + coder"
        return (
            f"В LM Studio нет моделей для запуска: {detail}. "
            "Проверьте model_roles.json и загрузите модели."
        )
    if status == "models_not_loaded":
        return (
            "Модели найдены, но chat ещё не ответил. Подождите завершения "
            "загрузки/обработки в LM Studio; очередь не создаётся до успешного ответа."
        )
    if status == "ready":
        return "AI-модели готовы — можно запускать цикл."
    if status == "pending_check":
        return "Проверяем готовность AI-моделей…"
    return "Статус AI-моделей неизвестен."


def lm_status(
    *,
    allow_probe: bool = False,
    force: bool = False,
) -> Dict[str, Any]:
    """Health + cached chat preflight for UI gating.

    ``allow_probe=False`` (summary, fast health): never blocks on chat; returns
    cached readiness or ``status=pending_check``. ``allow_probe=True`` runs
    ``preflight_all_required_roles`` when cache is stale. Cold model startup can
    take close to a minute on the local workstation.
    """
    global _READINESS_CACHE, _READINESS_CACHE_AT

    h = health()
    out: Dict[str, Any] = {
        **h,
        "ready": False,
        "run_allowed": False,
        "status": "server_unavailable",
        "message_ru": _readiness_message("server_unavailable"),
        "preflight": None,
        "preflight_checked_at_utc": None,
        "preflight_cache_ttl_sec": READINESS_CACHE_TTL_SEC,
        "probe_pending": False,
        "missing_run_roles": [],
    }

    if not h.get("available"):
        return out

    missing_run = _missing_run_roles(h)
    out["missing_run_roles"] = missing_run
    if missing_run:
        out["status"] = "models_not_listed"
        out["message_ru"] = _readiness_message("models_not_listed", missing_run=missing_run)
        return out

    now = time.time()
    cache_fresh = (
        _READINESS_CACHE is not None
        and not force
        and (now - _READINESS_CACHE_AT) < READINESS_CACHE_TTL_SEC
    )
    if cache_fresh:
        out.update(_READINESS_CACHE or {})
        return out

    if not allow_probe:
        out["status"] = "pending_check"
        out["message_ru"] = _readiness_message("pending_check")
        out["probe_pending"] = True
        return out

    preflight = preflight_all_required_roles(
        list(RUN_REQUIRED_ROLES),
        purpose="ui_readiness",
    )
    ready = bool(preflight.get("ok"))
    status = "ready" if ready else "models_not_loaded"
    snap = {
        "ready": ready,
        "run_allowed": ready,
        "status": status,
        "message_ru": _readiness_message(status),
        "preflight": preflight,
        "preflight_checked_at_utc": preflight.get("checked_at_utc"),
        "probe_pending": False,
    }
    _READINESS_CACHE = snap
    _READINESS_CACHE_AT = now
    out.update(snap)
    return out


def select_available_model(
    primary_role: str,
    fallback_roles: Optional[List[str]] = None,
    *,
    timeout: int = DEFAULT_MODEL_PROBE_TIMEOUT,
    max_tokens: int = 32,
    attempts: int = 1,
    experiment_id: Optional[str] = None,
    purpose: str = "model_role_selection",
) -> Dict[str, Any]:
    """Select the first role whose configured chat model answers a probe.

    This verifies `/chat/completions`, not just `/models`. The returned dict is
    safe to persist in the experiment record as model health evidence.
    """
    roles = [primary_role] + list(fallback_roles or [])
    seen_roles: List[str] = []
    probes: List[Dict[str, Any]] = []
    primary_model = ""
    try:
        primary_model = model_for(primary_role)
    except LMStudioError as exc:
        probes.append({
            "role": primary_role,
            "ok": False,
            "status": "role_unconfigured",
            "error": str(exc),
        })

    seen_models: set[str] = set()
    for role in roles:
        if role in seen_roles:
            continue
        seen_roles.append(role)
        try:
            model = model_for(role)
        except LMStudioError as exc:
            probes.append({
                "role": role,
                "ok": False,
                "status": "role_unconfigured",
                "error": str(exc),
            })
            continue
        if model in seen_models:
            continue
        seen_models.add(model)
        probe = probe_chat_completion(
            model,
            timeout=timeout,
            max_tokens=max_tokens,
            attempts=attempts,
            experiment_id=experiment_id,
            purpose=purpose,
            role=role,
        )
        row = {"role": role, **probe}
        probes.append(row)
        if probe.get("ok"):
            return {
                "ok": True,
                "primary_role": primary_role,
                "primary_model": primary_model or model,
                "selected_role": role,
                "selected_model": model,
                "fallback_used": role != primary_role,
                "primary_model_failed": role != primary_role,
                "probes": probes,
                "checked_via": "chat/completions",
            }
    return {
        "ok": False,
        "primary_role": primary_role,
        "primary_model": primary_model,
        "selected_role": None,
        "selected_model": None,
        "fallback_used": False,
        "primary_model_failed": bool(probes),
        "probes": probes,
        "checked_via": "chat/completions",
    }


def preflight_all_required_roles(
    required: Optional[List[str]] = None,
    *,
    timeout: int = DEFAULT_MODEL_PROBE_TIMEOUT,
    experiment_id: Optional[str] = None,
    purpose: str = "preflight_all_required_roles",
) -> Dict[str, Any]:
    """Probe every required role through /chat/completions.

    Returns ``{ok, missing_roles, role_health}``. ``ok`` is True only if every
    required role responds. Used by the runner as a hard gate before any
    ``start_skeleton`` call, so the lab never writes a fallback_template
    while the user thinks LLM ran.
    """
    required = list(required or ["judge", "coder"])
    role_health: Dict[str, Any] = {}
    missing: List[Dict[str, Any]] = []
    for role in required:
        try:
            model_id = model_for(role)
        except LMStudioError as exc:
            role_health[role] = {
                "ok": False,
                "status": "role_unconfigured",
                "error": str(exc),
            }
            missing.append({"role": role, "reason": "role_unconfigured", "error": str(exc)})
            continue
        probe = probe_chat_completion(
            model_id,
            timeout=timeout,
            max_tokens=32,
            attempts=1,
            experiment_id=experiment_id,
            purpose=purpose,
            role=role,
        )
        role_health[role] = {
            "ok": bool(probe.get("ok")),
            "model": model_id,
            "status": probe.get("status"),
            "elapsed_sec": probe.get("elapsed_sec"),
        }
        if not probe.get("ok"):
            missing.append({
                "role": role,
                "reason": probe.get("status") or "unavailable",
                "model": model_id,
            })
    return {
        "ok": not missing,
        "missing_roles": missing,
        "role_health": role_health,
        "checked_via": "chat/completions",
        "base_url": base_url(),
        "checked_at_utc": _now(),
    }


class LMStudioUnavailable(LMStudioError):
    """Raised when LM Studio (or one required role) is unavailable before/during a run.

    Carries a ``preflight`` payload with ``missing_roles`` for UI reporting.
    """

    def __init__(self, message: str, preflight: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message)
        self.preflight = preflight or {}


def chat(
    role: str,
    messages: List[Dict[str, str]],
    *,
    temperature: float = 0.2,
    max_tokens: int = 2048,
    response_format: Optional[Dict[str, Any]] = None,
    timeout: int = DEFAULT_CHAT_TIMEOUT,
    retries: int = DEFAULT_CHAT_RETRIES,
    experiment_id: Optional[str] = None,
    purpose: Optional[str] = None,
    cancel_event: Optional[threading.Event] = None,
    model_override: Optional[str] = None,
) -> Dict[str, Any]:
    """OpenAI-compatible chat completion. Logs the round-trip.

    Cancel semantics: cooperative. The ``cancel_event`` is checked at entry
    and between retry attempts. We never interrupt mid-``urlopen`` — the
    per-attempt ``timeout`` bounds the wait.
    """
    if cancel_event is not None and cancel_event.is_set():
        raise LMStudioCancelled("cancelled before first attempt")
    url = f"{base_url()}/chat/completions"
    payload: Dict[str, Any] = {
        "model": model_override or model_for(role),
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if response_format:
        payload["response_format"] = response_format

    started = time.time()
    last_exc: Optional[BaseException] = None
    for attempt in range(retries + 1):
        if cancel_event is not None and cancel_event.is_set():
            raise LMStudioCancelled(f"cancelled before attempt {attempt}")
        try:
            resp = _post(url, payload, timeout=timeout)
            elapsed = time.time() - started
            content = ""
            try:
                content = resp["choices"][0]["message"]["content"]
            except (KeyError, IndexError, TypeError):
                content = json.dumps(resp)[:400]
            _log_round_trip(
                experiment_id=experiment_id, purpose=purpose, role=role,
                model=payload["model"], messages=messages, response=resp,
                content=content, attempt=attempt, elapsed_sec=elapsed, error=None,
            )
            return {
                "content": content,
                "model": payload["model"],
                "raw": resp,
                "elapsed_sec": elapsed,
                "attempt": attempt,
            }
        except (urllib.error.URLError, urllib.error.HTTPError, LMStudioError, TimeoutError) as e:
            last_exc = e
            time.sleep(min(2 ** attempt, 5))
    elapsed = time.time() - started
    _log_round_trip(
        experiment_id=experiment_id, purpose=purpose, role=role,
        model=payload["model"], messages=messages, response=None, content="",
        attempt=retries, elapsed_sec=elapsed, error=str(last_exc),
    )
    raise LMStudioError(f"chat failed after {retries + 1} attempts: {last_exc}")


def probe_chat_completion(
    model: str,
    *,
    timeout: int = 90,
    max_tokens: int = 100,
    attempts: int = 2,
    experiment_id: Optional[str] = None,
    purpose: str = "model_health_probe",
    role: str = "model_health",
) -> Dict[str, Any]:
    """Probe a concrete model id through /chat/completions.

    ``/v1/models`` only proves the model is registered. This helper verifies
    that the model can actually answer a short chat completion before a long
    AI-Lab role call depends on it.
    """
    messages = [
        {"role": "system", "content": "You are a health-check responder."},
        {"role": "user", "content": "Reply with OK and one sentence."},
    ]
    url = f"{base_url()}/chat/completions"
    payload: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": 0.0,
        "max_tokens": max_tokens,
    }
    child_script = r'''
import json
import sys
import urllib.request

cfg = json.loads(sys.stdin.read())
data = json.dumps(cfg["payload"]).encode("utf-8")
req = urllib.request.Request(
    cfg["url"],
    data=data,
    method="POST",
    headers={"Content-Type": "application/json", "Accept": "application/json"},
)
with urllib.request.urlopen(req, timeout=int(cfg["timeout"])) as resp:
    raw = resp.read().decode("utf-8", errors="replace")
print(raw)
'''.strip()
    started = time.time()
    attempt_rows: List[Dict[str, Any]] = []
    for idx in range(1, max(1, attempts) + 1):
        attempt_started = time.time()
        try:
            completed = subprocess.run(
                [sys.executable, "-c", child_script],
                input=json.dumps({"url": url, "payload": payload, "timeout": timeout}),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=max(1, timeout + 10),
            )
            elapsed_attempt = time.time() - attempt_started
            if completed.returncode != 0:
                error = (completed.stderr or completed.stdout or f"subprocess returncode {completed.returncode}").strip()
                _log_round_trip(
                    experiment_id=experiment_id, purpose=purpose, role=role,
                    model=model, messages=messages, response=None, content="",
                    attempt=idx - 1, elapsed_sec=elapsed_attempt, error=error[:400],
                )
                attempt_rows.append({
                    "attempt": idx,
                    "ok": False,
                    "elapsed_sec": round(elapsed_attempt, 3),
                    "error": error[:500],
                })
                continue
            raw = (completed.stdout or "").strip()
            resp = json.loads(raw)
            try:
                content = str(resp["choices"][0]["message"]["content"] or "").strip()
            except (KeyError, IndexError, TypeError):
                content = json.dumps(resp)[:400]
            _log_round_trip(
                experiment_id=experiment_id, purpose=purpose, role=role,
                model=model, messages=messages, response=resp, content=content,
                attempt=idx - 1, elapsed_sec=elapsed_attempt, error=None,
            )
            row = {
                "attempt": idx,
                "ok": bool(content),
                "elapsed_sec": round(elapsed_attempt, 3),
                "content_preview": content[:200],
            }
            attempt_rows.append(row)
            if content:
                return {
                    "model": model,
                    "status": "available",
                    "ok": True,
                    "attempts": attempt_rows,
                    "elapsed_sec": round(time.time() - started, 3),
                    "timeout_sec": timeout,
                    "max_tokens": max_tokens,
                    "prompt": "Reply with OK and one sentence.",
                }
        except subprocess.TimeoutExpired as exc:
            elapsed_attempt = time.time() - attempt_started
            error = f"hard timeout after {max(1, timeout + 10)} sec"
            _log_round_trip(
                experiment_id=experiment_id, purpose=purpose, role=role,
                model=model, messages=messages, response=None, content="",
                attempt=idx - 1, elapsed_sec=elapsed_attempt, error=error,
            )
            attempt_rows.append({
                "attempt": idx,
                "ok": False,
                "elapsed_sec": round(elapsed_attempt, 3),
                "error": error,
            })
        except (json.JSONDecodeError, OSError, ValueError) as exc:
            elapsed_attempt = time.time() - attempt_started
            _log_round_trip(
                experiment_id=experiment_id, purpose=purpose, role=role,
                model=model, messages=messages, response=None, content="",
                attempt=idx - 1, elapsed_sec=elapsed_attempt, error=str(exc)[:400],
            )
            attempt_rows.append({
                "attempt": idx,
                "ok": False,
                "elapsed_sec": round(elapsed_attempt, 3),
                "error": str(exc),
            })
    errors = " ".join(str(row.get("error") or "") for row in attempt_rows).lower()
    status = "model_unavailable_timeout" if "timed out" in errors or "timeout" in errors else "model_unavailable_error"
    return {
        "model": model,
        "status": status,
        "ok": False,
        "attempts": attempt_rows,
        "elapsed_sec": round(time.time() - started, 3),
        "timeout_sec": timeout,
        "max_tokens": max_tokens,
        "prompt": "Reply with OK and one sentence.",
    }


def embed(
    texts: List[str],
    *,
    timeout: int = 120,
    retries: int = 1,
    experiment_id: Optional[str] = None,
    purpose: Optional[str] = None,
) -> List[List[float]]:
    url = f"{base_url()}/embeddings"
    payload = {"model": model_for("embedder"), "input": texts}
    last_exc: Optional[BaseException] = None
    started = time.time()
    for attempt in range(retries + 1):
        try:
            resp = _post(url, payload, timeout=timeout)
            elapsed = time.time() - started
            vecs = [item.get("embedding", []) for item in resp.get("data", [])]
            _log_round_trip(
                experiment_id=experiment_id, purpose=purpose, role="embedder",
                model=payload["model"],
                messages=[{"role": "system", "content": f"embed {len(texts)} texts"}],
                response={"vectors": len(vecs)}, content=f"vectors={len(vecs)}",
                attempt=attempt, elapsed_sec=elapsed, error=None,
            )
            return vecs
        except (urllib.error.URLError, urllib.error.HTTPError, LMStudioError, TimeoutError) as e:
            last_exc = e
            time.sleep(min(2 ** attempt, 5))
    raise LMStudioError(f"embed failed: {last_exc}")


def _log_round_trip(
    experiment_id: Optional[str],
    purpose: Optional[str],
    role: str,
    model: str,
    messages: List[Dict[str, str]],
    response: Any,
    content: str,
    attempt: int,
    elapsed_sec: float,
    error: Optional[str],
) -> None:
    rec = {
        "timestamp_utc": _now(),
        "experiment_id": experiment_id,
        "purpose": purpose,
        "role": role,
        "model": model,
        "attempt": attempt,
        "elapsed_sec": round(elapsed_sec, 3),
        "messages_preview": [
            {"role": m.get("role"), "content": (m.get("content") or "")[:1200]} for m in messages
        ],
        "response_preview": (content or "")[:1200] if content else None,
        "error": error,
    }
    try:
        append_jsonl(_today_log(), rec)
    except OSError:
        pass


def extract_json_block(text: str) -> Optional[Any]:
    """Best-effort: find first {...} JSON object in a model response."""
    if not text:
        return None
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if esc:
            esc = False
            continue
        if ch == "\\":
            esc = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                blob = text[start:i + 1]
                try:
                    return json.loads(blob)
                except json.JSONDecodeError:
                    return None
    return None
