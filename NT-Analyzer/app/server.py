"""
NT-Analyzer local backend (stdlib only — no FastAPI, no pip install).

- Binds to 127.0.0.1 ONLY. Never to 0.0.0.0.
- Serves /api/* JSON and /ui/* static files (UI bundle).
- Reads/writes only via app.jobqueue (whitelisted ops on the file queue).

Endpoints:
    GET  /api/health
    GET  /api/strategies
    GET  /api/reports               mixed jobs + batches feed (shared pagination)
    GET  /api/jobs                  list recent jobs (limit query param)
    POST /api/jobs                  create a new job
    GET  /api/jobs/{job_id}         full job summary (job + result/error)
    GET  /api/jobs/{job_id}/trades  trades.json with offset/limit
    GET  /api/diagnostics           NinjaTrader process + bridge log tail
    GET  /                          redirect to /ui/
    GET  /ui/...                    static UI bundle
"""
from __future__ import annotations

import errno
import copy
import functools
import hashlib
import ipaddress
import json
import math
import os
import re
import signal
import socket
import subprocess
import sys
import threading
import time
import traceback
import urllib.parse
import urllib.request
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from email.utils import formatdate, parsedate_to_datetime
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

# Allow `python app/server.py` to import sibling module.
if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from app import jobqueue  # type: ignore[no-redef]
    from app import governance  # type: ignore[no-redef]
    from app import integrations  # type: ignore[no-redef]
    from app import telegram_service  # type: ignore[no-redef]
    from app import telegram_remote  # type: ignore[no-redef]
    from app import production_telegram  # type: ignore[no-redef]
    from app import tunnel_manager  # type: ignore[no-redef]
    from app import account_auth  # type: ignore[no-redef]
    from app import security_devices  # type: ignore[no-redef]
    from app import environment_registry  # type: ignore[no-redef]
    from app import user_card  # type: ignore[no-redef]
    from app import development_sync  # type: ignore[no-redef]
    from app import data_root_guard  # type: ignore[no-redef]
    from app import pipeline_view  # type: ignore[no-redef]
    from app import personal_nt_security  # type: ignore[no-redef]
    from app import ninjatrader_resources  # type: ignore[no-redef]
    from app import agent_allocation  # type: ignore[no-redef]
    from app import dev_preview  # type: ignore[no-redef]
    from app import dev_service_accounts  # type: ignore[no-redef]
    from app import release_center  # type: ignore[no-redef]
    from app import doc_specs  # type: ignore[no-redef]
    from app import subscriptions  # type: ignore[no-redef]
    from app import permissions  # type: ignore[no-redef]
    from app import admin_journal  # type: ignore[no-redef]
    from app import user_support  # type: ignore[no-redef]
    from app import invitations  # type: ignore[no-redef]
    from app import legal  # type: ignore[no-redef]
    from app import paypal  # type: ignore[no-redef]
    from app import workspaces  # type: ignore[no-redef]
    from app import market_data  # type: ignore[no-redef]
    from app import market_data_failover  # type: ignore[no-redef]
    from app import market_data_baseline  # type: ignore[no-redef]
    from app import market_data_ipc  # type: ignore[no-redef]
    from app import market_data_router  # type: ignore[no-redef]
    from app import market_data_gap_recovery  # type: ignore[no-redef]
    from app import market_data_ws_http  # type: ignore[no-redef]
    from app import market_data_cache_keys  # type: ignore[no-redef]
    from app import market_data_subscriptions  # type: ignore[no-redef]
    from app import market_data_live_supervisor  # type: ignore[no-redef]
    from app import owner_market_data_gateway  # type: ignore[no-redef]
    from app import data_platform  # type: ignore[no-redef]
    from app import secure_store as _secure_store  # type: ignore[no-redef]
    from app import marginrefresh  # type: ignore[no-redef]
    from app import ops  # type: ignore[no-redef]
    from app import performance  # type: ignore[no-redef]
    from app import account_ledger  # type: ignore[no-redef]
    from app import portfolio_registry  # type: ignore[no-redef]
    from app import runtime as ops_runtime  # type: ignore[no-redef]
    from app import worker_router as local_worker  # type: ignore[no-redef]
    from app import api_admission  # type: ignore[no-redef]
    from app import production_workers  # type: ignore[no-redef]
    from app import vitek  # type: ignore[no-redef]
    from app import in_app_notifications  # type: ignore[no-redef]
    from app.ai_lab import read_model as ai_read_model  # type: ignore[no-redef]
    from app.ai_lab import registry as ai_registry  # type: ignore[no-redef]
    from app.ai_lab import orchestrator as ai_orchestrator  # type: ignore[no-redef]
    from app.ai_lab import analysis_pack as ai_analysis_pack  # type: ignore[no-redef]
    from app.ai_lab import backtest as ai_backtest  # type: ignore[no-redef]
    from app.ai_lab import bootstrap as ai_bootstrap  # type: ignore[no-redef]
    from app.ai_lab import lm_studio as ai_lm_studio  # type: ignore[no-redef]
    from app.ai_lab import runner as ai_runner  # type: ignore[no-redef]
    from app.ai_lab import activity as ai_activity  # type: ignore[no-redef]
    from app.ai_lab import compile_errors as ai_compile_errors  # type: ignore[no-redef]
    from app.ai_lab import operator_notes as ai_operator_notes  # type: ignore[no-redef]
    from app.ai_lab import errors as ai_errors  # type: ignore[no-redef]
    from app.ai_lab import lessons as ai_lessons  # type: ignore[no-redef]
    from app.ai_lab import stale_sweep as ai_stale_sweep  # type: ignore[no-redef]
    from app.ai_lab import cloud_agents as ai_cloud_agents  # type: ignore[no-redef]
    from app.ai_lab import agent_registry as ai_agent_registry  # type: ignore[no-redef]
    from app.ai_lab import agent_router as ai_agent_router  # type: ignore[no-redef]
    from app.ai_lab import universal_llm as ai_universal_llm  # type: ignore[no-redef]
    from app.ai_lab import chief_agent as ai_chief_agent  # type: ignore[no-redef]
    from app.ai_lab import domain_agents as ai_domain_agents  # type: ignore[no-redef]
    from app.ai_lab import agent_tts as ai_agent_tts  # type: ignore[no-redef]
    from app.ai_lab import news_agent as ai_news_agent  # type: ignore[no-redef]
    from app.ai_lab import research_catalog as ai_research_catalog  # type: ignore[no-redef]
    from app import local_secrets as _local_secrets  # type: ignore[no-redef]
    from app import news_refresh  # type: ignore[no-redef]
    from app import runtime_env  # type: ignore[no-redef]
    from app import edge_security  # type: ignore[no-redef]
    from app import service_readiness  # type: ignore[no-redef]
    from app import observability  # type: ignore[no-redef]
    from app import ai_budgets  # type: ignore[no-redef]
    from app import audit_events  # type: ignore[no-redef]
    from app import market_data_ingestion  # type: ignore[no-redef]
    from app import connector_protocol  # type: ignore[no-redef]
    from app import connector_releases  # type: ignore[no-redef]
    from app import google_auth  # type: ignore[no-redef]
    from app import test_auth  # type: ignore[no-redef]
    from app import demo_backtest  # type: ignore[no-redef]
    from app import practice_trading  # type: ignore[no-redef]
    from app import community  # type: ignore[no-redef]
    from app.ai_lab import ai_ratings as ai_ratings  # type: ignore[no-redef]
else:
    from . import jobqueue
    from . import governance
    from . import integrations
    from . import telegram_service
    from . import telegram_remote
    from . import production_telegram
    from . import tunnel_manager
    from . import account_auth
    from . import security_devices
    from . import environment_registry
    from . import user_card
    from . import development_sync
    from . import data_root_guard
    from . import pipeline_view
    from . import personal_nt_security
    from . import ninjatrader_resources
    from . import agent_allocation
    from . import dev_preview
    from . import dev_service_accounts
    from . import release_center
    from . import doc_specs
    from . import subscriptions
    from . import permissions
    from . import admin_journal
    from . import user_support
    from . import invitations
    from . import legal
    from . import paypal
    from . import workspaces
    from . import market_data
    from . import market_data_failover
    from . import market_data_baseline
    from . import market_data_ipc
    from . import market_data_router
    from . import market_data_gap_recovery
    from . import market_data_ws_http
    from . import market_data_cache_keys
    from . import market_data_subscriptions
    from . import market_data_live_supervisor
    from . import owner_market_data_gateway
    from . import data_platform
    from . import secure_store as _secure_store
    from . import marginrefresh
    from . import ops
    from . import performance
    from . import account_ledger
    from . import portfolio_registry
    from . import runtime as ops_runtime
    from . import worker_router as local_worker
    from . import api_admission
    from . import production_workers
    from . import vitek
    from . import in_app_notifications
    from .ai_lab import read_model as ai_read_model
    from .ai_lab import registry as ai_registry
    from .ai_lab import orchestrator as ai_orchestrator
    from .ai_lab import analysis_pack as ai_analysis_pack
    from .ai_lab import backtest as ai_backtest
    from .ai_lab import bootstrap as ai_bootstrap
    from .ai_lab import lm_studio as ai_lm_studio
    from .ai_lab import runner as ai_runner
    from .ai_lab import activity as ai_activity
    from .ai_lab import compile_errors as ai_compile_errors
    from .ai_lab import operator_notes as ai_operator_notes
    from .ai_lab import errors as ai_errors
    from .ai_lab import lessons as ai_lessons
    from .ai_lab import stale_sweep as ai_stale_sweep
    from .ai_lab import cloud_agents as ai_cloud_agents
    from .ai_lab import agent_registry as ai_agent_registry
    from .ai_lab import agent_router as ai_agent_router
    from .ai_lab import universal_llm as ai_universal_llm
    from .ai_lab import chief_agent as ai_chief_agent
    from .ai_lab import domain_agents as ai_domain_agents
    from .ai_lab import agent_tts as ai_agent_tts
    from .ai_lab import news_agent as ai_news_agent
    from .ai_lab import research_catalog as ai_research_catalog
    from . import local_secrets as _local_secrets
    from . import news_refresh
    from . import runtime_env
    from . import edge_security
    from . import service_readiness
    from . import observability
    from . import ai_budgets
    from . import audit_events
    from . import market_data_ingestion
    from . import connector_protocol
    from . import connector_releases
    from . import google_auth
    from . import test_auth
    from . import demo_backtest
    from . import practice_trading
    from . import community
    from .ai_lab import ai_ratings as ai_ratings

_local_secrets.apply()


HOST = "127.0.0.1"
DEFAULT_PORT = 8765
STATIC_DIR = Path(__file__).resolve().parent / "static"
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _emit_financial_ledger_event(change: Dict[str, Any], *, source: str) -> None:
    """Wake Marina/Victor after a durable owner-ledger mutation.

    The ledger remains the source of truth; this event contains only stable IDs
    and never substitutes a model-generated financial classification.
    """
    if not isinstance(change, dict) or not change.get("ok", True):
        return
    event = change.get("event") if isinstance(change.get("event"), dict) else {}
    event_ids = [str(value) for value in change.get("event_ids") or change.get("new_event_ids") or [] if value]
    if event.get("event_id"):
        event_ids.append(str(event["event_id"]))
    event_ids = list(dict.fromkeys(event_ids))
    if not event_ids:
        return
    account_names = [
        str(row.get("account_name") or "")
        for row in change.get("new_events") or [] if isinstance(row, dict) and row.get("account_name")
    ]
    payload = {
        "event_ids": event_ids,
        "account_names": list(dict.fromkeys(account_names)),
        "change": str(source or "account_ledger"),
    }
    vitek.emit_event(
        "financial_event_changed", payload, source="account_ledger", severity="info",
        dedupe_key="ledger:" + hashlib.sha256(
            json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()[:24],
        dedupe_seconds=24 * 3600,
    )

# Uniform Content-Security-Policy for all served static UI (new Aurora + legacy).
# Both UIs externalize JS and use no inline <script>/onclick, so `script-src 'self'`
# blocks injected inline script while inline style attributes remain allowed.
STATIC_CSP = (
    "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
    "script-src 'self'; connect-src 'self' http://127.0.0.1:* http://localhost:*; media-src 'self' blob:; "
    "base-uri 'none'; form-action 'self'; "
    "object-src 'none'; frame-ancestors 'self' https://web.telegram.org https://*.telegram.org"
)

_SELF_SERVICE_POSTS = {
    "/api/billing/promo/preview",
    "/api/billing/promo/redeem",
    "/api/billing/subscribe",
    "/api/billing/checkout",
    "/api/billing/payment-request",
    "/api/workspaces/personal",
    "/api/workspaces/select",
    "/api/bridge/pair/start",
    "/api/bridge/pair/complete",
    "/api/auth/avatar/refresh",
    "/api/auth/ux-mode",
    # Chart data is a read that carries its request list in the body; viewers
    # (read_only) must be able to poll it so the desktop grid works in the
    # Telegram Mini App exactly like the local UI.
    "/api/ops/runtime/bars/batch",
    "/api/demo-backtests",
}


def _is_self_service_post(path: str) -> bool:
    """POSTs a read-only account may perform on its own behalf."""
    return (
        path in _SELF_SERVICE_POSTS
        or path.startswith("/api/support/")
        or path.startswith("/api/practice/")
        or path.startswith("/api/community/")
        or path.startswith("/api/auth/nt-confirm/")
        or path.startswith("/api/account/")
        or path.startswith("/api/ninjatrader/jobs")
        or path == "/api/demo-backtests"
        or path == "/api/ops/runtime/bars/batch"
    )


_OWNER_ONLY_API_PREFIXES = (
    "/api/telegram/",
    "/api/auth/users",
    "/api/owner/",
    "/api/worker/",
    "/api/vitek/",
    "/api/notifications",
    # Provider credentials, global routing policy and aggregate AI usage are
    # operator control-plane data.  A tenant entitlement may use AI through
    # scoped application routes, but must not inspect or mutate this registry.
    "/api/ai-agents",
    "/api/ai-lab/cloud-agents",
)


def _is_owner_only_api_path(path: str, method: str = "GET") -> bool:
    value = str(path or "")
    # A small, audited subset of the former owner-only surface is now governed
    # by explicit administrative capabilities.  Everything else under these
    # prefixes remains owner-only.
    if permissions.required_admin_capability(value, method):
        return False
    return value == "/api/server/restart" or value.startswith(_OWNER_ONLY_API_PREFIXES)


def _is_impersonation_exit(path: str, context: Any) -> bool:
    """The impersonation-exit endpoint must always be reachable by an active
    impersonation session, so "return to owner" can never get stuck behind the
    impersonated persona's workspace role, read-only role or the owner-only gate.
    The endpoint itself is loopback + Development gated and only ever restores
    the exact owner that started the impersonation, so this exemption cannot be
    used to escalate privileges."""
    if path != "/api/owner/impersonate/end":
        return False
    return bool(isinstance(context, dict) and context.get("impersonator_owner_id"))


_ADMIN_MODULES = (
    # Fourteen entries across five groups meant the panel was a directory to be
    # searched rather than a place to work. What merged, merged because the two
    # halves only ever answered one question together; what left Admin left
    # because it was never an operator tool.
    {"id": "overview", "label": "Обзор", "capability": "admin.view", "group": ""},

    # Monitoring folded in as a tab: who is online and which sessions exist are
    # facts about exactly the people this list is about, and answering "is this
    # account in use right now" should not require leaving the account.
    {"id": "users", "label": "Пользователи и сессии", "capability": "users.manage",
     "group": "Доступ и пользователи"},
    {"id": "requests", "label": "Запросы доступа", "capability": "admin.view",
     "owner_only": True, "group": "Доступ и пользователи"},
    {"id": "invites", "label": "Приглашения", "capability": "admin.view",
     "owner_only": True, "group": "Доступ и пользователи"},
    # Administrative subscriptions and grants live only here. The cabinet shows
    # a member what they hold; deciding what someone else holds is an operator
    # action and belongs on the operator's side of the boundary.
    {"id": "subscriptions", "label": "Подписки и гранты", "capability": "admin.view",
     "owner_only": True, "group": "Доступ и пользователи"},

    {"id": "connectors", "label": "Коннекторы и Telegram", "capability": "connectors.manage",
     "group": "Операции"},
    {"id": "operations", "label": "Операции и диагностика", "capability": "operations.view",
     "group": "Операции"},

    # Environments and releases were never two jobs -- the owner always had to
    # read both to answer a single question, which is why the promotion gates
    # could not live in either of them alone. Seeing what an environment runs
    # is the lower-privilege half and the release actions are gated again
    # inside, so either capability opens it rather than the stricter one hiding
    # status from an admin entitled to read it.
    {"id": "pipeline", "label": "Окружения и релизы", "capability": "releases.view",
     "capability_any": ("releases.view", "environment.switch"), "group": "Релизы и окружения"},

    {"id": "journal", "label": "Журнал владельца", "capability": "admin.view",
     "owner_only": True, "group": "Владелец"},
    {"id": "payment", "label": "Настройки оплаты", "capability": "admin.view",
     "owner_only": True, "group": "Владелец"},
    {"id": "ai-ratings", "label": "Оценки ИИ", "capability": "admin.view",
     "owner_only": True, "group": "Владелец"},
    # QA impersonation drives virtual users and View-As personas. Those are
    # unsafe test hooks that exist only in Development, so the module is not
    # offered elsewhere -- on a server it could only ever render "unavailable",
    # which reads as Admin being crippled rather than as one dev-only tool
    # being absent.
    {"id": "staging", "label": "Разработка / QA", "capability": "admin.view",
     "owner_only": True, "development_only": True, "group": "Владелец"},
)


# A source that hangs must not hold the page. Several of these reach a provider
# or the Telegram API, and a socket that never answers used to block the whole
# response -- which the operator experiences as a dashboard that spins forever
# and says nothing about any of the sources that were perfectly healthy.
_CONNECTOR_PROBE_TIMEOUT_SEC = 3.0


def _connector_probe(label: str, fn: Any,
                     timeout_sec: float = _CONNECTOR_PROBE_TIMEOUT_SEC) -> Dict[str, Any]:
    """One dashboard row, bounded in time.

    A source that raises degrades that row only; a source that hangs times out
    and degrades that row only. Either way the other rows still render, because
    a partial answer that names what is missing beats no answer at all.

    The worker is a daemon thread: if the underlying call never returns we stop
    waiting rather than stop serving, and the process can still exit.

    Every value here is a status, never a credential: the callers below pass
    booleans and identifiers, and nothing reads a token.
    """
    outcome: Dict[str, Any] = {}

    def run() -> None:
        started = time.time()
        try:
            outcome["value"] = fn()
        except Exception as exc:  # one broken source must not blank the dashboard
            outcome["error"] = type(exc).__name__
        finally:
            outcome["elapsed_ms"] = int((time.time() - started) * 1000)

    worker = threading.Thread(target=run, name=f"connector-probe-{label}", daemon=True)
    started = time.time()
    worker.start()
    worker.join(timeout=max(0.1, float(timeout_sec)))
    elapsed_ms = int((time.time() - started) * 1000)

    if worker.is_alive():
        return {
            "id": label, "state": "timeout", "elapsed_ms": elapsed_ms,
            "detail": "нет ответа за %.1f с" % float(timeout_sec),
        }
    if "error" in outcome:
        return {
            "id": label, "state": "error",
            "elapsed_ms": outcome.get("elapsed_ms", elapsed_ms),
            "detail": outcome["error"],
        }
    row = {"id": label, "state": "unknown",
           "elapsed_ms": outcome.get("elapsed_ms", elapsed_ms)}
    value = outcome.get("value")
    if isinstance(value, dict):
        row.update(value)
    return row


def _connectors_dashboard_payload(context: Dict[str, Any]) -> Dict[str, Any]:
    """Aggregated connector/integration status for the Admin panel.

    This exists so the ordinary question -- is Telegram up, is the webhook
    registered, which environment holds the market-data hub -- is answered on
    the Admin page itself instead of behind another screen.
    """
    from . import owner_market_data_gateway as gateway

    def telegram() -> Dict[str, Any]:
        status = telegram_service.status() or {}
        return {
            "label": "Telegram bot",
            "state": "healthy" if status.get("configured") else "not_configured",
            "configured": bool(status.get("configured")),
            "bot_username": str(status.get("bot_username") or ""),
            "detail": str(status.get("state") or status.get("mode") or ""),
        }

    def webhook() -> Dict[str, Any]:
        status = telegram_service.status() or {}
        hook = status.get("webhook") if isinstance(status.get("webhook"), dict) else {}
        registered = bool(hook.get("url") or hook.get("configured"))
        return {
            "label": "Telegram webhook",
            "state": "healthy" if registered else "not_configured",
            "configured": registered,
            "last_error": str(hook.get("last_error_message") or "")[:200],
            "pending_updates": hook.get("pending_update_count"),
        }

    def canary_routing() -> Dict[str, Any]:
        environment = runtime_env.deployment_environment()
        marker = runtime_env.telegram_environment_marker().strip()
        return {
            "label": "Canary routing",
            "state": "healthy",
            "environment": environment,
            "marker": marker or "(production, unmarked)",
            "detail": "Production accepts the webhook; [CANARY] is forwarded internally",
        }

    def market_gateway() -> Dict[str, Any]:
        role = gateway.effective_role()
        return {
            "label": "Owner market-data gateway",
            "state": "healthy" if role in {"hub", "consumer"} else "degraded",
            "role": role,
            "chart_source_mode": gateway.chart_source_mode(),
            "is_hub": gateway.is_hub(),
            "consuming": gateway.should_consume(),
            "token_configured": gateway.token_configured(),
        }

    def providers() -> Dict[str, Any]:
        from . import market_data_failover

        snapshot = market_data_failover.status(include_file=False)
        rows = []
        for row in (snapshot or {}).get("external_providers") or []:
            rows.append({
                "name": row.get("name"),
                "runtime_state": row.get("runtime_state"),
                "configured": bool(row.get("configured")),
                "live_eligible": bool(row.get("live_eligible")),
                "blocking_reasons": list(row.get("blocking_reasons") or [])[:4],
            })
        live = [r["name"] for r in rows if r.get("runtime_state") == "LIVE"]
        return {
            "label": "Market data providers",
            "state": "healthy" if live else "degraded",
            "providers": rows,
            "live": live,
            "preferred_primary": (snapshot or {}).get("preferred_primary"),
        }

    def connector_installations() -> Dict[str, Any]:
        out = connector_protocol.list_installations(context.get("user_id"))
        rows = list(out.get("installations") or [])
        online = [r for r in rows if str(r.get("status") or "") in {"online", "active"}]
        return {
            "label": "Windows Connector / NinjaTrader",
            "state": "healthy" if online else ("degraded" if rows else "not_configured"),
            "installations": len(rows),
            "online": len(online),
            "last_heartbeat_utc": max(
                [str(r.get("last_heartbeat_utc") or "") for r in rows] or [""]
            ),
        }

    # Concurrently, so the page is bounded by the slowest single source rather
    # than by their sum. Six sources at a three-second ceiling would otherwise
    # be eighteen seconds of spinner in the worst case, and the worst case is
    # exactly when an operator is looking at this page.
    sources = (
        ("telegram", telegram),
        ("webhook", webhook),
        ("canary_routing", canary_routing),
        ("market_gateway", market_gateway),
        ("providers", providers),
        ("connector", connector_installations),
    )
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=len(sources),
                            thread_name_prefix="connectors") as pool:
        rows = list(pool.map(lambda item: _connector_probe(item[0], item[1]), sources))

    stalled = [row["id"] for row in rows if row.get("state") in {"timeout", "error"}]
    return {
        "ok": True,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "environment": runtime_env.deployment_environment(),
        "sections": rows,
        # Said plainly rather than left for the client to infer from row states:
        # this answer is complete, or it is not and these are the sources that
        # did not report.
        "partial": bool(stalled),
        "unavailable_sources": stalled,
        "probe_timeout_sec": _CONNECTOR_PROBE_TIMEOUT_SEC,
        # Onboarding starts with getting the program, so the panel needs to know
        # whether there is a signed package to offer. An empty download_url
        # means there is not, and the reason travels with it -- a dead download
        # button teaches the reader that the page lies.
        "installer": connector_protocol.installer_status(),
        # Stated explicitly so the contract is visible to the client too.
        "secrets_exposed": False,
    }


def _backend_is_supervised() -> bool:
    """Whether something outside this process owns restart ordering."""
    return os.environ.get("NTA_BACKEND_SUPERVISED") == "1"


def _operations_actions() -> Dict[str, Dict[str, Any]]:
    """Which operations this environment actually permits, and why not.

    Capability alone was the whole gate, so every environment offered the same
    buttons and the reader could not tell a restart that a supervisor performs
    from one this process improvises. The unsupervised restart relaunches
    ``python -m app.server`` from the checkout, which on a server would replace
    a released artifact with whatever happens to be on disk -- the exact class
    of error the release pipeline exists to prevent.
    """
    development = runtime_env.is_development()
    supervised = _backend_is_supervised()
    restart_allowed = development or supervised
    if restart_allowed:
        restart_reason = ""
    else:
        restart_reason = (
            "Перезапуск недоступен: процесс не под супервизором, а "
            "самостоятельный respawn запустил бы код из checkout вместо "
            "выпущенного артефакта."
        )
    return {
        "restart": {
            "allowed": restart_allowed,
            "mode": "supervised" if supervised else ("respawn" if development else "blocked"),
            "reason": restart_reason,
        },
        # AI Lab is a development workbench; unloading its memory on a server
        # would be an action against something that is not running there.
        "ai_unload": {
            "allowed": development,
            "reason": "" if development else "AI Lab запускается только в Development.",
        },
        "catalog_refresh": {"allowed": True, "reason": ""},
        "margin_refresh": {"allowed": True, "reason": ""},
    }


def _admin_overview_payload(context: Dict[str, Any]) -> Dict[str, Any]:
    caps = context.get("admin_capabilities")
    caps = caps if isinstance(caps, dict) else {}
    development = runtime_env.is_development()
    modules = [
        dict(row) for row in _ADMIN_MODULES
        if any(caps.get(str(c)) for c in (row.get("capability_any") or (row["capability"],)))
        and (not row.get("owner_only") or context.get("is_owner"))
        and (not row.get("development_only") or development)
    ]
    return {
        "ok": True,
        "actor": {
            "user_id": context.get("user_id") or "",
            "is_owner": bool(context.get("is_owner")),
            "kind": "owner" if context.get("is_owner") else "delegated_admin",
        },
        "modules": modules,
        "admin_capabilities": {
            cid: bool(caps.get(cid)) for cid in permissions.ADMIN_CAPABILITY_IDS
        },
        "admin_capability_catalog": permissions.admin_capability_catalog(),
        "deployment": runtime_env.public_status(),
        "security_contract": {
            "secrets_exposed": False,
            "credentials_transfer_between_environments": False,
            "session_isolation": "origin-bound cookies, CSRF and browser storage",
        },
    }


def _validated_environment_origin(environment: str, value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        parsed = urllib.parse.urlsplit(raw)
        port = parsed.port
    except (TypeError, ValueError):
        return ""
    host = str(parsed.hostname or "").lower().rstrip(".")
    if (
        parsed.scheme not in {"http", "https"}
        or not host
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        return ""
    if environment in {runtime_env.CANARY, runtime_env.PRODUCTION} and (
        parsed.scheme != "https" or port not in {None, 443}
    ):
        return ""
    if environment == runtime_env.DEVELOPMENT and host not in {
        "127.0.0.1", "localhost", "::1",
    }:
        return ""
    default_port = (
        (parsed.scheme == "http" and port in {None, 80})
        or (parsed.scheme == "https" and port in {None, 443})
    )
    normalized_port = "" if default_port else f":{port}"
    bracketed_host = f"[{host}]" if ":" in host else host
    return f"{parsed.scheme}://{bracketed_host}{normalized_port}"


_DEFAULT_ENVIRONMENT_ORIGINS = {
    runtime_env.DEVELOPMENT: "http://127.0.0.1:8765",
    runtime_env.CANARY: "https://canary.stratforges.com",
    runtime_env.PRODUCTION: "https://app.stratforges.com",
}

_DEV_PREVIEW_MODE_COOKIE = "sf_dev_preview_mode"


def _server_environment_explicit() -> bool:
    return runtime_env.environment_explicit() and (
        runtime_env.is_server_environment() or runtime_env.is_production()
    )


def _admin_environment_targets() -> Dict[str, Any]:
    active = runtime_env.deployment_environment()
    deployment = runtime_env.public_status()
    configured = {
        runtime_env.DEVELOPMENT: os.environ.get("STRATFORGE_DEVELOPMENT_ORIGIN"),
        runtime_env.CANARY: os.environ.get("STRATFORGE_CANARY_ORIGIN"),
        runtime_env.PRODUCTION: os.environ.get("STRATFORGE_PRODUCTION_ORIGIN"),
    }
    rows = []
    for environment in (
        runtime_env.DEVELOPMENT, runtime_env.CANARY, runtime_env.PRODUCTION,
    ):
        current = environment == active
        supplied = str(configured.get(environment) or "").strip() or str(
            _DEFAULT_ENVIRONMENT_ORIGINS.get(environment) or ""
        )
        origin = _validated_environment_origin(environment, supplied)
        warnings = []
        if supplied and not origin:
            warnings.append("Настроенный origin отклонён политикой безопасности.")
        if not current and not origin:
            warnings.append("Origin для этой среды не настроен.")
        if environment == runtime_env.DEVELOPMENT and not current:
            warnings.append("Локальная разработка активируется только после проверки доступности в браузере.")
        if not current:
            warnings.append("Метаданные среды читаются только после её открытия по целевому origin.")
        rows.append({
            "environment": environment,
            "current": current,
            "configured": bool(current or origin),
            "origin": "" if current else origin,
            "open_allowed": bool(current or (origin and environment != runtime_env.DEVELOPMENT)),
            "requires_reachability_probe": bool(
                environment == runtime_env.DEVELOPMENT and not current and origin
            ),
            "health": "reachable" if current else "unknown",
            "readiness": "current_server" if current else "unknown",
            "version": str(deployment.get("app_version") or "") if current else "",
            "commit": str(deployment.get("git_commit_sha") or "") if current else "",
            "build_id": str(deployment.get("build_id") or "") if current else "",
            "release_channel": str(deployment.get("release_channel") or "") if current else "",
            "warnings": warnings,
        })
    return {
        "ok": True,
        "active_environment": active,
        "targets": rows,
        "transition_contract": {
            "new_tab": True,
            "credentials_transfer": False,
            "tokens_in_url": False,
            "local_storage_transfer": False,
        },
    }


_ENVIRONMENT_PROBE_MAX_BYTES = 128 * 1024


def _admin_environment_probe(environment: Any) -> Dict[str, Any]:
    """Read a target's public runtime identity without browser credentials.

    The Environment Switcher cannot safely rely on a cross-origin browser
    ``fetch``: the isolated origins intentionally do not share CORS/session
    state. The server probes only the validated, configured environment origin,
    sends no authentication material, and returns the small public identity
    subset that the switcher renders.
    """
    wanted = str(environment or "").strip().lower()
    if wanted not in {
        runtime_env.DEVELOPMENT, runtime_env.CANARY, runtime_env.PRODUCTION,
    }:
        raise ValueError("Неизвестное окружение.")

    payload = _admin_environment_targets()
    target = next(
        (row for row in payload["targets"] if row.get("environment") == wanted),
        None,
    )
    if not isinstance(target, dict):
        raise ValueError("Окружение не настроено.")
    if target.get("current"):
        return target

    origin = _validated_environment_origin(wanted, target.get("origin"))
    if not origin:
        raise ValueError("Origin окружения не настроен.")
    request = urllib.request.Request(
        origin + "/api/runtime/env",
        method="GET",
        headers={
            "Accept": "application/json",
            "User-Agent": "StratForge-Environment-Probe/1",
        },
    )
    with urllib.request.urlopen(request, timeout=4.5) as response:
        raw = response.read(_ENVIRONMENT_PROBE_MAX_BYTES + 1)
    if len(raw) > _ENVIRONMENT_PROBE_MAX_BYTES:
        raise ValueError("Ответ runtime identity слишком большой.")
    document = json.loads(raw.decode("utf-8"))
    deployment = document.get("deployment") if isinstance(document, dict) else None
    if not isinstance(deployment, dict):
        deployment = document if isinstance(document, dict) else {}
    reported = str(
        deployment.get("deployment_environment")
        or deployment.get("environment")
        or ""
    ).strip().lower()
    if reported != wanted:
        raise ValueError("Runtime identity не соответствует выбранному окружению.")

    target.update({
        "version": str(
            deployment.get("app_version") or deployment.get("build_version") or ""
        ),
        "commit": str(deployment.get("git_commit_sha") or ""),
        "build_id": str(deployment.get("build_id") or ""),
        # The artifact digest is what proves Canary and Production really run
        # the same immutable build, so the switcher shows it beside the commit.
        "artifact_sha256": str(deployment.get("artifact_sha256") or ""),
        "release_channel": str(deployment.get("release_channel") or ""),
        "health": "reachable",
        "readiness": "runtime endpoint reachable",
        "probe_ok": True,
    })
    target["warnings"] = [
        warning for warning in (target.get("warnings") or [])
        if "Метаданные среды" not in str(warning)
    ]
    return target


_BILLING_PROMO_POSTS = {
    "/api/billing/promo/preview",
    "/api/billing/promo/redeem",
}
_API_RATE_LOCK = threading.Lock()
_API_RATE: Dict[Tuple[str, str, str], Any] = defaultdict(deque)
_API_RATE_LIMITS = {"read": 600, "write": 120, "owner": 60, "auth": 45}
_CONNECTOR_RATE: Dict[Tuple[str, str], Any] = defaultdict(deque)
_CONNECTOR_RATE_LIMITS = {
    "enrollment": 30,
    "session": 60,
    "runtime": 300,
}


def _do_restart_server() -> None:
    """Spawn a helper that waits for the old process to exit, then starts a new one."""
    if os.environ.get("NTA_BACKEND_SUPERVISED") == "1":
        # The external supervisor owns restart ordering, crash telemetry and
        # backoff. A clean exit here is an explicit restart request, not a crash.
        os._exit(0)
    port = sys.argv[1] if len(sys.argv) > 1 else str(DEFAULT_PORT)
    cwd = str(_PROJECT_ROOT)
    exe = sys.executable
    helper = (
        "import time, subprocess, sys\n"
        f"time.sleep(1.2)\n"
        f"subprocess.Popen([{exe!r}, '-m', 'app.server', {port!r}], cwd={cwd!r})\n"
    )
    kw: dict = {}
    if hasattr(subprocess, "CREATE_NO_WINDOW"):
        kw["creationflags"] = subprocess.CREATE_NO_WINDOW
    subprocess.Popen([exe, "-c", helper], cwd=cwd, **kw)
    os._exit(0)

# Allowed origin hosts for mutating requests (POST). Browsers attach Origin
# automatically; non-browser clients (CLI, PowerShell Invoke-RestMethod) do
# not send it, which is also accepted (empty Origin == not a cross-site
# browser request). The current bind port is appended at runtime.
_ALLOWED_ORIGIN_HOSTS = ("127.0.0.1", "localhost")

_DESKTOP_INSTRUMENT_ROOTS = {
    "MBT", "MET", "RTY", "MES", "MNQ", "M2K", "MYM",
    "MCL", "MNG", "RB", "HO", "MGC", "SIL", "MHG",
    "6A", "6B", "6C", "6E", "6J", "6S", "E7", "6M", "6N",
    "HE", "LE", "ZC", "ZW", "ZS", "ZM", "ZL",
    "ZT", "ZF", "ZN", "TN", "ZB", "UB",
}
_DESKTOP_ROOT_FALLBACK_SOURCE = "desktop_root_fallback"


def apply_desktop_instrument_fallbacks(result: list, *, desktop: bool) -> list:
    """Keep Desktop root selection usable without a local NT catalog.

    The NinjaTrader instrument scan is local runtime data and is not part of a
    server artifact. Desktop charts can still request a supported futures root
    (for example ``MNQ``); the existing provider resolver selects the current
    TopstepX contract or the configured runtime fallback later in the bars
    pipeline. Trading selectors keep their catalog-only behavior.
    """
    if not desktop:
        return result

    out: list = []
    seen: set[str] = set()
    for row in result:
        if not isinstance(row, dict):
            continue
        root = str(row.get("root") or "").strip()
        if not root:
            continue
        seen.add(root)
        front = row.get("front_month") if isinstance(row.get("front_month"), dict) else {}
        if str(front.get("instrument") or "").strip():
            out.append(row)
            continue
        fallback = {
            "instrument": root,
            "root": root,
            "source": _DESKTOP_ROOT_FALLBACK_SOURCE,
        }
        patched = dict(row)
        patched["front_month"] = fallback
        contracts = [
            item for item in (patched.get("contracts") or []) if isinstance(item, dict)
        ]
        if not any(str(item.get("instrument") or "") == root for item in contracts):
            contracts = [dict(fallback), *contracts]
        patched["contracts"] = contracts
        out.append(patched)

    for root in sorted(_DESKTOP_INSTRUMENT_ROOTS - seen):
        fallback = {
            "instrument": root,
            "root": root,
            "source": _DESKTOP_ROOT_FALLBACK_SOURCE,
        }
        out.append({
            "root": root,
            "front_month": dict(fallback),
            "contracts": [dict(fallback)],
        })
    return out

_MARKET_BARS_PAYLOAD_CACHE_LOCK = threading.RLock()
_MARKET_BARS_PAYLOAD_CACHE: Dict[Tuple[Any, ...], Dict[str, Any]] = {}
_MARKET_BARS_PAYLOAD_CACHE_MAX = 512


def _market_bar_time(row: Dict[str, Any]) -> Optional[datetime]:
    raw = str(row.get("t") or row.get("time_utc") or row.get("time") or "")
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _refresh_market_payload_age(payload: Dict[str, Any]) -> Dict[str, Any]:
    source = payload.get("source") if isinstance(payload.get("source"), dict) else None
    # A TopstepX chart owns an independent Market SignalR feed.  Refresh its
    # actual transport state on every cache read; never reinterpret the age of
    # its final 5m/1h bar as a dead market or tie it to NinjaTrader's process.
    if source and str(source.get("provider") or "").lower() == "topstepx":
        payload = market_data_failover.TopstepXProvider().refresh_payload_liveness(payload)
        source = payload.get("source") if isinstance(payload.get("source"), dict) else None
    if source:
        updated = source.get("updated_at_utc")
        if updated:
            try:
                dt = datetime.fromisoformat(str(updated).replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                source["age_sec"] = max(0.0, (datetime.now(timezone.utc) - dt).total_seconds())
            except ValueError:
                pass
    if source and str(source.get("provider") or "").lower() == "topstepx":
        # The independent provider has already produced a factual LIVE /
        # CONNECTING / STALE state above.  Do not turn it OFFLINE solely because
        # a local NinjaTrader bridge is intentionally disabled.
        return payload
    # Remote Connector data has its own authenticated source clock and must
    # not be invalidated by the API host's local NinjaTrader process state.
    # Re-evaluate its bounded freshness window on every cache read so a payload
    # cannot remain LIVE after the Windows VM stops sending bars.
    if source and source.get("kind") == "connector_remote":
        now = datetime.now(timezone.utc)
        stale_after = None
        try:
            stale_after = datetime.fromisoformat(
                str(source.get("stale_after_utc") or "").replace("Z", "+00:00")
            )
            if stale_after.tzinfo is None:
                stale_after = None
        except ValueError:
            stale_after = None
        fresh = bool(stale_after and now <= stale_after.astimezone(timezone.utc))
        freshness = dict(payload.get("freshness") or {})
        freshness.update({
            "fresh": fresh,
            "stale": not fresh,
            "offline": not fresh,
            "live_eligible": fresh,
        })
        payload["freshness"] = freshness
        source.update({
            "fresh": fresh,
            "live_eligible": fresh,
            "runtime_state": "LIVE" if fresh else "OFFLINE",
        })
        if not fresh:
            return market_data_failover.mark_offline_snapshot(
                payload,
                reason="connector_remote_snapshot_expired",
                last_source="ninjatrader_connector",
                backup_providers_available=0,
            )
        payload.update({
            "live": True,
            "status": "live",
            "market_data_available": True,
            "strategy_blocked": False,
            "execution_blocked": False,
            "price_marker_live": True,
        })
        return payload
    # Never serve a cached LIVE payload while NinjaTrader is offline and no
    # credentialed live backup is active.
    try:
        heartbeat = ops_runtime.read_heartbeat()
        primary_healthy = bool(jobqueue.ninjatrader_running() and heartbeat.get("fresh"))
    except Exception:
        primary_healthy = True
    if not primary_healthy and payload.get("live"):
        return market_data_failover.mark_offline_snapshot(
            payload,
            reason="cached_payload_while_ninjatrader_offline",
            last_source=str((payload.get("source") or {}).get("provider")
                            or (payload.get("source") or {}).get("kind")
                            or "cache"),
            backup_providers_available=0,
        )
    if payload.get("status") == "offline" or (payload.get("freshness") or {}).get("offline"):
        payload["live"] = False
        payload["price_marker_live"] = False
    return payload


def _market_payload_cache_get(key: Tuple[Any, ...]) -> Optional[Dict[str, Any]]:
    with _MARKET_BARS_PAYLOAD_CACHE_LOCK:
        cached = _MARKET_BARS_PAYLOAD_CACHE.get(key)
    if cached is None:
        return None
    return _refresh_market_payload_age(copy.deepcopy(cached))


def _market_payload_cache_put(key: Tuple[Any, ...], payload: Dict[str, Any]) -> None:
    with _MARKET_BARS_PAYLOAD_CACHE_LOCK:
        _MARKET_BARS_PAYLOAD_CACHE[key] = copy.deepcopy(payload)
        while len(_MARKET_BARS_PAYLOAD_CACHE) > _MARKET_BARS_PAYLOAD_CACHE_MAX:
            try:
                oldest = next(iter(_MARKET_BARS_PAYLOAD_CACHE))
            except StopIteration:
                return
            _MARKET_BARS_PAYLOAD_CACHE.pop(oldest, None)


def _market_bars_payload(instrument: str, timeframe: str, limit: int,
                         range_days: int = 0, from_date: str = "",
                         to_date: str = "", register: bool = True,
                         snapshot_index: Optional[Dict[str, Any]] = None,
                         alerts_index: Optional[Dict[str, Any]] = None,
                         max_points: int = 0,
                         workspace_id: str = "",
                         connector_snapshot_index: Optional[Dict[str, Any]] = None,
                         from_ts: str = "", to_ts: str = "") -> Dict[str, Any]:
    with market_data_baseline.StageTimer(
        "backend.bars_payload_ms",
        instrument=str(instrument or ""),
        timeframe=str(timeframe or ""),
    ):
        return _market_bars_payload_impl(
            instrument, timeframe, limit, range_days, from_date, to_date,
            register, snapshot_index, alerts_index, max_points, workspace_id,
            connector_snapshot_index, from_ts, to_ts,
        )


def _market_bars_payload_impl(instrument: str, timeframe: str, limit: int,
                              range_days: int = 0, from_date: str = "",
                              to_date: str = "", register: bool = True,
                              snapshot_index: Optional[Dict[str, Any]] = None,
                              alerts_index: Optional[Dict[str, Any]] = None,
                              max_points: int = 0,
                              workspace_id: str = "",
                              connector_snapshot_index: Optional[Dict[str, Any]] = None,
                              from_ts: str = "", to_ts: str = "") -> Dict[str, Any]:
    requested_instrument = " ".join(str(instrument or "").strip().upper().split())
    resolved_instrument = market_data.resolve_chart_instrument(requested_instrument) or requested_instrument
    production_mode = _server_environment_explicit()
    # Timestamp ranges power viewport history paging. Date-only parameters are
    # preserved for existing callers; explicit timestamps win and remain UTC.
    start: Optional[datetime] = None
    end: Optional[datetime] = None
    try:
        if from_ts:
            start = datetime.fromisoformat(str(from_ts).replace("Z", "+00:00"))
            start = start.astimezone(timezone.utc) if start.tzinfo else start.replace(tzinfo=timezone.utc)
        elif from_date:
            start = datetime.fromisoformat(from_date).replace(tzinfo=timezone.utc)
        if to_ts:
            end = datetime.fromisoformat(str(to_ts).replace("Z", "+00:00"))
            end = end.astimezone(timezone.utc) if end.tzinfo else end.replace(tzinfo=timezone.utc)
        elif to_date:
            end = datetime.fromisoformat(to_date).replace(tzinfo=timezone.utc) + timedelta(days=1)
    except ValueError:
        start = end = None
    if not start and range_days > 0:
        end = end or datetime.now(timezone.utc)
        start = end - timedelta(days=range_days)
    remote_bars = None
    if workspace_id:
        remote_bars = market_data_ingestion.workspace_series(
            str(workspace_id), resolved_instrument, str(timeframe or "5m"), limit,
            snapshot_index=connector_snapshot_index,
        )
    # Local request files are Development transport only.  Production charts
    # consume authenticated Connector HTTPS snapshots and never use localhost
    # IPC/shared request files as an implicit cross-host control plane.
    if register and not production_mode and not market_data_failover.TopstepXProvider().configured():
        market_data.register_request(resolved_instrument, timeframe, limit, range_days, from_date, to_date)
    try:
        max_points = max(0, min(20000, int(max_points or 0)))
    except (TypeError, ValueError):
        max_points = 0
    cache_key = (
        str(workspace_id or ""),
        resolved_instrument,
        str(timeframe or "5m"),
        int(limit or 1500),
        int(range_days or 0),
        str(from_date or "")[:10],
        str(to_date or "")[:10],
        str(from_ts or "")[:40],
        str(to_ts or "")[:40],
        max_points,
        "" if production_mode else market_data.snapshot_source_signature(),
        "" if production_mode else market_data.alerts_source_signature(),
        str((connector_snapshot_index or {}).get("source_signature") or ""),
        str(((remote_bars or {}).get("source") or {}).get("source_signature") or ""),
        int(((remote_bars or {}).get("source") or {}).get("source_sequence") or 0),
    )
    cached = _market_payload_cache_get(cache_key)
    if cached is not None:
        market_data_baseline.mark("backend.bars_payload_cache_hit")
        return cached
    primary_healthy = False
    out: Optional[Dict[str, Any]] = None
    # Canonical chart order in every environment: TopstepX -> fresh NinjaTrader
    # Connector snapshot -> another credentialed live provider -> OFFLINE.
    # Production previously skipped TopstepX and returned an empty warning
    # object whenever the active workspace had no Connector snapshot.
    topstep = market_data_failover.TopstepXProvider()
    topstep_request = requested_instrument if " " not in requested_instrument else resolved_instrument
    if topstep.configured():
        out = market_data_failover.fetch_external_series(
            topstep_request, timeframe, limit, providers=[topstep],
            start_time=start, end_time=end,
        )
        if out is not None and " " not in requested_instrument:
            resolved_instrument = str(out.get("instrument") or resolved_instrument).upper()
    if out is None and remote_bars:
        primary_healthy = bool(
            remote_bars.get("live")
            and ((remote_bars.get("freshness") or {}).get("fresh"))
        )
        if primary_healthy:
            out = remote_bars
            freshness = market_data_failover.series_freshness(out.get("bars") or [], timeframe)
            source = dict(out.get("source") or {})
            selection = market_data_failover.remember_selected_provider(
                "ninjatrader", resolved_instrument, timeframe, reason="topstepx_unavailable",
            )
            source.update({
                "provider": "ninjatrader", "active": "ninjatrader",
                "fresh": True, "runtime_state": "LIVE",
                "failover_from": selection.get("transition_from") or "topstepx",
                "failover_status": "switched",
            })
            out.update({
                "source": source, "freshness": freshness, "live": True,
                "status": "failover_live", "market_data_available": True,
                "price_marker_live": True,
                "note": "NinjaTrader Connector is serving this chart while TopstepX is unavailable.",
            })
    if out is None and not production_mode:
        if snapshot_index is not None:
            runtime_bars = market_data.series_from_index(snapshot_index, resolved_instrument, timeframe, limit)
        else:
            with market_data_baseline.StageTimer("backend.read_runtime_series_ms"):
                runtime_bars = market_data.read_runtime_series(resolved_instrument, timeframe, limit)
        heartbeat = ops_runtime.read_heartbeat()
        primary_healthy = bool(jobqueue.ninjatrader_running() and heartbeat.get("fresh"))
        runtime_fresh = bool((runtime_bars or {}).get("bars") and market_data_failover.series_freshness(
            (runtime_bars or {}).get("bars") or [], timeframe,
        ).get("fresh"))
        if primary_healthy and runtime_fresh:
            out = runtime_bars
            freshness = market_data_failover.series_freshness(out.get("bars") or [], timeframe)
            source = dict(out.get("source") or {})
            selection = market_data_failover.remember_selected_provider(
                "ninjatrader", resolved_instrument, timeframe, reason="topstepx_unavailable",
            )
            source.update({"provider": "ninjatrader", "active": "ninjatrader",
                           "fresh": True, "runtime_state": "LIVE",
                           "failover_from": selection.get("transition_from") or "topstepx",
                           "failover_status": "switched"})
            out.update({"source": source, "freshness": freshness, "live": True,
                        "status": "failover_live", "market_data_available": True,
                        "price_marker_live": True,
                        "note": "NinjaTrader Connector is serving this chart while TopstepX is unavailable."})
        else:
            backups = [provider for provider in market_data_failover.live_backup_candidates()
                       if provider.name != "topstepx"]
            out = market_data_failover.fetch_external_series(
                resolved_instrument, timeframe, limit, providers=backups,
                start_time=start, end_time=end,
            ) if backups else None
            if out is not None:
                source = out.setdefault("source", {})
                source.setdefault("failover_from", "topstepx")
                source["failover_status"] = "switched"
                out.setdefault("gap_recovery", {
                    "attempted": True, "provider_available": True,
                    "mode": "independent_failover", "provider": source.get("provider") or "",
                    "recovered_bars": 0, "unresolved_gaps": 0,
                    "primary_healthy": False,
                })
            else:
                with market_data_baseline.StageTimer("backend.failover_ms"):
                    unified = market_data_failover.apply_failover(
                        runtime_bars, resolved_instrument, timeframe, limit,
                        primary_healthy=False, providers=[],
                    )
                if unified and (unified.get("bars") or unified.get("status") == "offline"):
                    out = unified
                else:
                    out = jobqueue.read_instrument_bars(resolved_instrument, timeframe, limit)
                    out["status"] = "historical_fallback" if out.get("bars") else ((runtime_bars or {}).get("status") or "waiting")
                    out["bridge"] = {"status": (runtime_bars or {}).get("status") or "subscription_requested", "error": (runtime_bars or {}).get("error") or ""}
                    if not out.get("bars"):
                        detail = out["bridge"]["error"]
                        out["note"] = detail or "Подписка отправлена в NinjaTrader Bridge. Проверьте подключение к провайдеру данных."
                    out["gap_recovery"] = {"attempted": True, "provider_available": False, "mode": "historical_artifact" if out.get("bars") else "unavailable", "recovered_bars": 0, "unresolved_gaps": 0, "primary_healthy": primary_healthy}
                    if not primary_healthy:
                        out = market_data_failover.mark_offline_snapshot(out, reason="all_live_providers_unavailable", last_source="historical_artifact" if out.get("bars") else "none", backup_providers_available=0)
    elif out is None:
        backups = [provider for provider in market_data_failover.live_backup_candidates()
                   if provider.name != "topstepx"]
        out = market_data_failover.fetch_external_series(
            resolved_instrument, timeframe, limit, providers=backups,
            start_time=start, end_time=end,
        ) if backups else None
        if out is not None:
            source = out.setdefault("source", {})
            source.setdefault("failover_from", "topstepx")
            source["failover_status"] = "switched"
            out.setdefault("gap_recovery", {
                "attempted": True, "provider_available": True,
                "mode": "independent_failover", "provider": source.get("provider") or "",
                "recovered_bars": 0, "unresolved_gaps": 0,
                "primary_healthy": False,
            })
        else:
            seed = remote_bars or {
                "instrument": resolved_instrument,
                "bars": [],
                "total": 0,
                "requested_timeframe": str(timeframe or "5m"),
                "matched_timeframe": str(timeframe or "5m"),
                "source": {
                    "kind": "connector_remote",
                    "provider": "ninjatrader",
                    "transport": "connector_https",
                },
            }
            out = market_data_failover.mark_offline_snapshot(
                seed,
                reason="all_live_providers_unavailable" if remote_bars else "no_workspace_connector_snapshot",
                last_source="ninjatrader_connector" if remote_bars else "none",
                backup_providers_available=0,
            )
    if start or end:
        out["bars"] = [row for row in (out.get("bars") or []) if isinstance(row, dict)
                       and (lambda dt: dt is not None and (start is None or dt >= start)
                            and (end is None or dt < end))(_market_bar_time(row))]
        out["total"] = len(out["bars"])
    if alerts_index is not None:
        symbol = " ".join(str(instrument or "").strip().upper().split())
        out["alerts"] = list(alerts_index.get(symbol, []))
    elif production_mode:
        # Development price-alert JSON is not a Production tenant store.
        out["alerts"] = []
    else:
        out["alerts"] = market_data.list_alerts(
            instrument=instrument, include_inactive=True)["alerts"]
    if max_points:
        out = market_data.downsample_series_payload(out, max_points) or out
    out["requested_instrument"] = requested_instrument
    out["resolved_instrument"] = resolved_instrument
    # Data-plane labels: chart source must not silently become execution authority.
    src_kind = str((out.get("source") or {}).get("kind") or (out.get("source") or {}).get("provider") or "")
    out["chart_source"] = src_kind or "ninjatrader_runtime"
    out["strategy_source"] = "ninjatrader"
    out["execution_source"] = "ninjatrader"
    out["data_planes"] = {
        "display": out["chart_source"],
        "strategy": out["strategy_source"],
        "execution": out["execution_source"],
        "note": "Chart source is never an automatic execution authority",
    }
    try:
        md_cache_key = market_data_cache_keys.market_cache_key(
            provider=out["chart_source"] or "ninjatrader",
            exchange="CME",
            exact_contract=resolved_instrument,
            channel="trades",
            sharing_scope="workspace" if workspace_id else "global",
            workspace_id=workspace_id,
            timeframe=str(timeframe or "5m"),
            source_epoch=int(
                (out.get("source") or {}).get("source_epoch")
                or (out.get("source") or {}).get("source_sequence")
                or 0
            ),
        )
        plat = data_platform.get_platform()
        cached = plat.cache.get(md_cache_key)
        cache_hit = cached is not None
        if not cache_hit and out.get("bars"):
            plat.cache.set(
                md_cache_key,
                {"bars_len": len(out.get("bars") or []), "ts": out.get("updated_at_utc")},
                ttl_sec=30,
            )
        existing = None
        if not production_mode:
            snap = market_data_subscriptions.get_subscription_registry().snapshot()
            existing = next(
                (
                    row for row in (snap.get("subscriptions") or [])
                    if row.get("exact_contract") == resolved_instrument
                ),
                None,
            )
        age = None
        try:
            age = float((out.get("freshness") or {}).get("age_sec"))
        except (TypeError, ValueError):
            age = None
        out["diagnostics"] = market_data_cache_keys.diagnostics_for_series(
            requested_symbol=requested_instrument,
            exact_contract=resolved_instrument,
            timeframe=str(timeframe or "5m"),
            provider=out["chart_source"],
            bars=out.get("bars") or [],
            cache_key=md_cache_key,
            cache_level="L2" if cache_hit else ("L1" if out.get("bars") else "MISS"),
            cache_hit=cache_hit,
            transport="http",
            ws_state="n/a",
            subscription_id=str((existing or {}).get("subscription_id") or ""),
            source_epoch=int(
                (out.get("source") or {}).get("source_epoch")
                or (out.get("source") or {}).get("source_sequence")
                or 0
            ),
            subscriber_count=int((existing or {}).get("refcount") or 0),
            last_event_age_sec=age,
            raw_provider_symbol=resolved_instrument,
        )
    except Exception as exc:
        out["diagnostics"] = {"error": str(exc)[:200]}
    if out.get("bars"):
        # Cache healthy LIVE primary; also cache explicit OFFLINE snapshots so a
        # 36-chart grid does not recompute the same offline payload 36×.
        if out.get("status") == "offline" or (
            primary_healthy
            and out.get("live")
            and (out.get("source") or {}).get("kind")
            in {"ninjatrader_runtime", "connector_remote"}
        ):
            _market_payload_cache_put(cache_key, out)
    return out


def _practice_market_quote(instrument: str, *, workspace_id: str = "") -> Dict[str, Any]:
    """Build the only quote allowed to fill an educational virtual order.

    The browser never supplies a price.  This intentionally shares the same
    server-side market payload used by charts, then requires an explicitly
    live and fresh source before marking it as tradable.  Historical/offline
    bars may still be shown to the student, but cannot silently become a
    virtual fill price.
    """
    requested = " ".join(str(instrument or "").strip().upper().split()) or "MNQ"
    try:
        series = _market_bars_payload(
            requested, "1m", 4, register=True, max_points=4,
            workspace_id=str(workspace_id or ""),
        )
    except Exception as exc:  # Fail closed: market availability is never an order error/500.
        return {
            "symbol": requested.split()[0], "tradable": False,
            "status": "error", "reason": f"Не удалось подтвердить котировку: {str(exc)[:180]}",
            "quote": {}, "source": {}, "freshness": {},
        }

    bars = series.get("bars") if isinstance(series.get("bars"), list) else []
    latest = bars[-1] if bars and isinstance(bars[-1], dict) else {}
    try:
        last = float(latest.get("c", latest.get("close")))
    except (TypeError, ValueError):
        last = 0.0
    if not math.isfinite(last) or last <= 0:
        last = 0.0
    freshness = dict(series.get("freshness") or {}) if isinstance(series.get("freshness"), dict) else {}
    if not freshness and bars:
        freshness = market_data_failover.series_freshness(bars, "1m")
    source = dict(series.get("source") or {}) if isinstance(series.get("source"), dict) else {}
    quote = dict(series.get("quote") or {}) if isinstance(series.get("quote"), dict) else {}
    if last and not quote.get("last"):
        quote["last"] = last
    live = bool(series.get("live"))
    fresh = bool(freshness.get("fresh"))
    blocked = bool(series.get("market_data_available") is False or series.get("execution_blocked"))
    tradable = bool(last and live and fresh and not blocked)
    status = str(series.get("status") or ("ready" if tradable else "unavailable"))[:80]
    if tradable:
        reason = ""
    elif not last:
        reason = "Нет подтверждённого последнего значения котировки."
    elif blocked:
        reason = "Рыночный контур сейчас OFFLINE или доступен только исторический источник."
    elif not fresh:
        reason = "Последняя котировка устарела; виртуальное исполнение остановлено."
    else:
        reason = "Источник котировки не подтверждён как live; виртуальное исполнение остановлено."
    return {
        "symbol": requested.split()[0],
        "tradable": tradable,
        "status": "ready" if tradable else status,
        "reason": reason,
        # Do not pass stale ``last`` as the fill price.  It remains in quote
        # solely for transparent display with the unavailable status.
        "price": last if tradable else 0.0,
        "quote": quote,
        "source": source,
        "freshness": freshness,
    }


# ---------------------------------------------------------------------------
# Strategy Control Center — real source from NinjaTrader Strategies folder
# ---------------------------------------------------------------------------

def _default_ninjatrader_user_dir() -> Path:
    override = os.environ.get("NINJATRADER_USER_DIR")
    if override:
        return Path(override)
    return Path.home() / "Documents" / "NinjaTrader 8"


_NT_USER_DIR = _default_ninjatrader_user_dir()
_NT_STRATEGIES_DIR = _NT_USER_DIR / "bin" / "Custom" / "Strategies" / "NT-Analyzer_strategies"
_NT_STRATEGIES_LEGACY_DIR = _NT_USER_DIR / "bin" / "Custom" / "Strategies"

# Strategy Control Center curated class lists.
#
# These used to be hard-coded sets that had to be edited in Python every time a
# strategy was promoted/rejected. They are now seeded from a JSON config so new
# strategies can be wired into SCC by editing data/ops/scc_classes.json (or by
# whatever tooling writes it) — no code change / server rebuild required.
#
# The built-in defaults below remain the fallback when the config file is
# missing or malformed, so behaviour is unchanged on a fresh checkout.
_SCC_CLASSES_CONFIG_PATH = _PROJECT_ROOT / "data" / "ops" / "scc_classes.json"

_SCC_ACTIVE_CLASSES_DEFAULT = {
    "PullbackMNQ5mV2",
    "VWAPPullbackMGC5mV1",
    "B1ShortOnlyMGC5mV2",
    "B1Stop24MGC5mC003",
    "B1Stop20MGC5mC004",
    "NTAMicroVwapRiskPilot",
    "NTAMicroMnqScalpPilot",
    "NTAMnqPostActiveScalpC017",
    "NTAMnqDailyOpenScalpC018",
    "NTAMnqMicroOrbOpenScalp",
    "NTAnalyzerEveryNBarLong",
    "StrategiyaUrovney",
}
_SCC_REJECTED_CLASSES_DEFAULT = {
    "NTAMicroOrbPilot",
    "NTAMicroVwapGapMirrorPilot",
    "NTAMicroVwapMeanRevertPilot",
    "NTAMnqLiquiditySweepReversalC015",
    "NTAMnqOpenDriveShortScalpC016",
    "NTAMnqLateVwapLongScalpC017",
}


def _load_scc_classes() -> "tuple[set, set]":
    """Return (active, rejected) SCC class sets.

    Starts from the built-in defaults and merges in data/ops/scc_classes.json
    when present. Config schema (all keys optional):
        {
          "active":   ["ClassA", ...],   # added to (or replacing) defaults
          "rejected": ["ClassB", ...],
          "replace_defaults": false       # when true, ignore built-in defaults
        }
    A class listed as rejected always wins over active. Read fresh on every
    call so edits take effect without restarting the backend.
    """
    active = set(_SCC_ACTIVE_CLASSES_DEFAULT)
    rejected = set(_SCC_REJECTED_CLASSES_DEFAULT)
    try:
        with open(_SCC_CLASSES_CONFIG_PATH, "r", encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, json.JSONDecodeError):
        doc = None
    if isinstance(doc, dict):
        if doc.get("replace_defaults"):
            active = set()
            rejected = set()
        a = doc.get("active")
        r = doc.get("rejected")
        if isinstance(a, list):
            active.update(str(x) for x in a if isinstance(x, str) and x)
        if isinstance(r, list):
            rejected.update(str(x) for x in r if isinstance(x, str) and x)
    active -= rejected  # rejected always wins
    return active, rejected


# Module-level snapshots (defaults merged with config present at import time).
# Kept for backward compatibility and external importers; request handlers call
# _load_scc_classes() directly so they pick up live config edits.
_SCC_ACTIVE_CLASSES, _SCC_REJECTED_CLASSES = _load_scc_classes()



def _iter_nt_strategy_entries():
    seen_roots = set()
    for root in (_NT_STRATEGIES_DIR, _NT_STRATEGIES_LEGACY_DIR):
        if root in seen_roots or not root.is_dir():
            continue
        seen_roots.add(root)
        for entry in sorted(root.iterdir()):
            if root == _NT_STRATEGIES_LEGACY_DIR and entry.is_dir() and entry.name == _NT_STRATEGIES_DIR.name:
                continue
            yield entry


def _build_scc_strategies() -> Dict[str, Any]:
    """Scan active NinjaTrader strategy roots + merge runtime telemetry."""
    active_classes, rejected_classes = _load_scc_classes()
    folder_strats: list = []
    seen_classes = set()
    for entry in _iter_nt_strategy_entries():
        if entry.name.startswith("_"):  # archived/rejected folders start with _
            continue
        if entry.is_dir():
            name = entry.name
            cs_files = sorted(entry.glob("*.cs"))
        elif entry.is_file() and entry.suffix.lower() == ".cs" and not entry.name.startswith("@"):
            name = entry.stem
            cs_files = [entry]
        else:
            continue
        if name in seen_classes:
            continue
        seen_classes.add(name)
        folder_strats.append({
            "class_name": name,
            "is_active":  name in active_classes,
            "is_rejected": name in rejected_classes,
            "cs_files":   [f.name for f in cs_files],
        })

    hb = ops_runtime.read_heartbeat()
    rt_raw = ops_runtime.read_strategies_raw()
    rt_by_cls = {str(r.get("strategy_class") or "").lower(): r for r in rt_raw if r.get("strategy_class")}
    cat = jobqueue.read_strategies_catalog() or {}
    cat_by_cls = {str(s.get("class_name") or ""): s for s in cat.get("strategies") or [] if isinstance(s, dict)}
    ops_by_cls = {str(s.get("class_name") or ""): s for s in ops.list_strategies()}

    # Some deploy wrappers live in nested source paths under their research
    # engine folder. Surface them anyway so SCC matches the real strategy
    # inventory instead of only the top-level directory layout.
    for cls in sorted(active_classes):
        if cls in seen_classes:
            continue
        sf = jobqueue._resolve_strategy_source_file(
            cls,
            (cat_by_cls.get(cls) or {}).get("source_file"),
        )
        if not sf:
            continue
        seen_classes.add(cls)
        folder_strats.append({
            "class_name": cls,
            "is_active": True,
            "is_rejected": cls in rejected_classes,
            "cs_files": [Path(sf).name],
        })

    active_strategies = []
    for fs in folder_strats:
        if not fs["is_active"]:
            continue
        cls = fs["class_name"]
        reg_s = ops_by_cls.get(cls)
        cat_s = cat_by_cls.get(cls) or {}
        source_file = jobqueue._resolve_strategy_source_file(cls, cat_s.get("source_file"))
        display_name = jobqueue._resolve_strategy_display_name(
            source_file,
            (reg_s or {}).get("display_name") or cat_s.get("display_name") or cls,
            cls,
        )
        rt = rt_by_cls.get(cls.lower())
        runtime_detected = bool(rt) and bool(hb.get("present")) and bool(hb.get("fresh"))
        runtime_enabled  = bool(rt and rt.get("enabled")) and runtime_detected
        acct_name = (rt or {}).get("account_name") or ""
        acct_mode = ops_runtime._classify_account_mode(acct_name, (rt or {}).get("account_mode"))
        active_strategies.append({
            **fs,
            "registry_id":      (reg_s or {}).get("strategy_id"),
            "registry_status":  (reg_s or {}).get("status", "unknown"),
            "display_name":     display_name,
            "locked_params":    (reg_s or {}).get("locked_params", {}),
            "runtime":          rt,
            "runtime_detected": runtime_detected,
            "runtime_enabled":  runtime_enabled,
            "account_name":     acct_name,
            "account_mode":     acct_mode,
            "instrument":       (rt or {}).get("instrument", ""),
            "timeframe":        (rt or {}).get("timeframe", ""),
        })

    rejected_running = [
        {"class_name": str(r.get("strategy_class")), "account_name": r.get("account_name")}
        for r in rt_raw
        if str(r.get("strategy_class") or "") in rejected_classes and r.get("enabled")
    ]

    try:
        from . import market_data_ipc
        ipc_metrics = market_data_ipc.metrics()
    except Exception:
        ipc_metrics = {}

    return {
        "strategies":       active_strategies,
        "rejected_running": rejected_running,
        "rejected_classes": sorted(rejected_classes),
        "heartbeat":        hb,
        "ipc":              ipc_metrics,
        "nt_strat_dir":     str(_NT_STRATEGIES_DIR),
        "nt_strat_dir_ok":  _NT_STRATEGIES_DIR.is_dir(),
    }


CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js":   "application/javascript; charset=utf-8",
    ".css":  "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg":  "image/svg+xml",
    ".ico":  "image/x-icon",
    ".png":  "image/png",
}

# `src="assets/ui.js?v=20260813-release-workflow2"` -> the ?v= value is
# replaced with the build stamp. Only local .js/.css references are touched;
# anything absolute or cross-origin is left exactly as authored.
_ASSET_REF_RE = re.compile(
    rb'(?P<head>(?:src|href)="(?!https?://|//)[^"?]+\.(?:js|css)\?v=)'
    rb'[^"]*'
    rb'(?P<tail>")'
)


@functools.lru_cache(maxsize=1)
def _asset_build_stamp() -> str:
    """Stable per-build stamp for asset URLs.

    Cached for the process lifetime: a build cannot change under a running
    server, and this runs on every HTML response.
    """
    try:
        status = runtime_env.status()
    except Exception:
        return ""
    for key in ("build_id", "git_commit_sha", "app_version"):
        value = re.sub(r"[^0-9A-Za-z._-]", "", str(status.get(key) or ""))[:64]
        if value:
            return value
    return ""


class Handler(BaseHTTPRequestHandler):
    server_version = "NTAnalyzer/0.1"

    def send_response(self, code: int, message: Optional[str] = None) -> None:
        self._response_status = int(code)
        super().send_response(code, message)

    # silence default access log
    def log_message(self, fmt: str, *args: Any) -> None:
        if os.environ.get("NTA_BACKEND_VERBOSE"):
            super().log_message(fmt, *args)

    def _begin_request_observation(self) -> None:
        self._request_started_mono = time.monotonic()
        self._response_status = 500

    def _finish_request_observation(self, method: str) -> None:
        started = float(getattr(self, "_request_started_mono", time.monotonic()))
        observability.record_http(
            method, str(getattr(self, "path", "/")),
            int(getattr(self, "_response_status", 500)),
            (time.monotonic() - started) * 1000.0,
        )

    # ------------- helpers -------------------------------------------------

    @staticmethod
    def _is_client_disconnect_error(err: BaseException) -> bool:
        # Browsers may cancel in-flight requests during navigation/reload.
        if isinstance(err, (BrokenPipeError, ConnectionResetError, ConnectionAbortedError)):
            return True
        if isinstance(err, OSError):
            winerror = getattr(err, "winerror", None)
            if winerror in {10053, 10054, 64}:
                return True
            if err.errno in {errno.EPIPE, errno.ECONNRESET}:
                return True
        return False

    def _json_safe(self, value: Any) -> Any:
        """Return JSON-standard-safe data.

        Python's json.dumps emits Infinity/NaN by default, but browser
        JSON.parse rejects those tokens. Backtests can legitimately produce
        infinite profit factor when there are no losses, so API responses must
        normalize non-finite floats before they reach the UI.
        """
        if isinstance(value, float):
            return value if math.isfinite(value) else None
        if isinstance(value, dict):
            return {k: self._json_safe(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self._json_safe(v) for v in value]
        if isinstance(value, tuple):
            return [self._json_safe(v) for v in value]
        return value

    def _json(self, status: int, body: Dict[str, Any], *,
              headers: Optional[Dict[str, str]] = None) -> None:
        data = json.dumps(
            self._json_safe(body),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            # CSP-ish hardening for a local UI
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "no-store")
            for name, value in (headers or {}).items():
                self.send_header(str(name), str(value))
            self.end_headers()
            self.wfile.write(data)
        except OSError as e:
            if self._is_client_disconnect_error(e):
                return
            raise

    def _err(self, status: int, msg: str, *,
             headers: Optional[Dict[str, str]] = None, code: str = "") -> None:
        payload: Dict[str, Any] = {"error": msg}
        if code:
            payload["code"] = str(code)
        self._json(status, payload, headers=headers)

    def _worker_queue_err(self, exc: BaseException) -> None:
        """Map queue/storage failures to stable, retry-aware HTTP responses."""
        headers: Dict[str, str] = {}
        message = str(exc) or "worker queue request failed"
        code = str(getattr(exc, "code", "") or "production_queue_error")
        if isinstance(exc, production_workers.QueueQuotaExceeded):
            status = HTTPStatus.TOO_MANY_REQUESTS
            headers["Retry-After"] = "1"
        elif isinstance(exc, production_workers.QueuePayloadTooLarge):
            status = HTTPStatus.REQUEST_ENTITY_TOO_LARGE
        elif isinstance(exc, production_workers.QueueIdempotencyConflict):
            status = HTTPStatus.CONFLICT
        elif isinstance(exc, production_workers.StorageUnavailableError):
            status = HTTPStatus.SERVICE_UNAVAILABLE
            headers["Retry-After"] = "5"
            message = "worker queue is temporarily unavailable"
        elif isinstance(exc, production_workers.ProductionQueueError):
            status = HTTPStatus.BAD_REQUEST
        else:
            status = HTTPStatus.SERVICE_UNAVAILABLE
            headers["Retry-After"] = "5"
            message = "worker queue is temporarily unavailable"
        self._err(status, message, headers=headers or None, code=code)

    def _bytes(self, status: int, data: bytes, content_type: str,
               download_name: Optional[str] = None,
               headers: Optional[Dict[str, str]] = None) -> None:
        try:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("X-Content-Type-Options", "nosniff")
            # A caller may opt a response out of no-store (an avatar is content
            # addressed by its ?v= stamp), but never by accident: it has to name
            # Cache-Control itself.
            if not (headers or {}).get("Cache-Control"):
                self.send_header("Cache-Control", "no-store")
            if download_name:
                quoted = urllib.parse.quote(download_name)
                self.send_header(
                    "Content-Disposition",
                    f"attachment; filename=\"{download_name}\"; filename*=UTF-8''{quoted}",
                )
            for name, value in (headers or {}).items():
                self.send_header(str(name), str(value))
            self.end_headers()
            self.wfile.write(data)
        except OSError as e:
            if self._is_client_disconnect_error(e):
                return
            raise

    def _read_raw_body(self) -> Optional[bytes]:
        """The exact bytes that were sent.

        A signature covers what was transmitted, not what a JSON round-trip
        happens to re-emit: key order, spacing and unicode escaping all survive
        parsing but would change the digest.
        """
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except (TypeError, ValueError):
            self._err(HTTPStatus.BAD_REQUEST, "invalid Content-Length")
            return None
        if n <= 0:
            return b""
        max_body = int(getattr(self.server, "max_body_bytes", 1 * 1024 * 1024))
        if n > max_body:
            self._err(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "body too large")
            return None
        recorder = getattr(self.server, "record_payload", None)
        if callable(recorder):
            recorder(n)
        return self.rfile.read(n)

    def _read_body(self) -> Optional[Dict[str, Any]]:
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except (TypeError, ValueError):
            self._err(HTTPStatus.BAD_REQUEST, "invalid Content-Length")
            return None
        if n <= 0:
            return {}
        max_body = int(getattr(self.server, "max_body_bytes", 1 * 1024 * 1024))
        if n > max_body:
            self._err(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "body too large")
            return None
        recorder = getattr(self.server, "record_payload", None)
        if callable(recorder):
            recorder(n)
        raw = self.rfile.read(n)
        try:
            body = json.loads(raw.decode("utf-8"))
        except Exception as e:
            self._err(HTTPStatus.BAD_REQUEST, f"invalid json: {e}")
            return None
        if not isinstance(body, dict):
            self._err(HTTPStatus.BAD_REQUEST, "json body must be an object")
            return None
        return body

    def _request_ips(self) -> Tuple[str, str]:
        tunnel_ip = str((self.client_address or ("", 0))[0] or "")
        forwarded = str(self.headers.get("X-Forwarded-For") or "").split(",", 1)[0].strip()
        return tunnel_ip, forwarded

    @staticmethod
    def _is_loopback_ip(value: str) -> bool:
        raw = str(value or "").strip().lower()
        if not raw:
            return False
        if raw in {"localhost", "::1", "0:0:0:0:0:0:0:1"}:
            return True
        try:
            return ipaddress.ip_address(raw).is_loopback
        except ValueError:
            return False

    def _self_origin(self) -> str:
        host = self._request_hostname(self.headers.get("Host") or "") or "127.0.0.1"
        scheme = "https" if (
            self._is_remote_api_request()
            or str(self.headers.get("X-Forwarded-Proto") or "").lower() == "https"
        ) else "http"
        raw_host = str(self.headers.get("Host") or host)
        return f"{scheme}://{raw_host}"

    def _connector_bearer_token(self) -> str:
        raw = str(self.headers.get("Authorization") or "").strip()
        match = re.fullmatch(r"Bearer ([A-Za-z0-9_-]{40,160})", raw)
        return str(match.group(1)) if match else ""

    def _check_connector_rate_limit(self, path: str) -> bool:
        if path.endswith("/enroll"):
            rate_class = "enrollment"
        elif path.endswith("/challenge") or path.endswith("/hello"):
            rate_class = "session"
        else:
            rate_class = "runtime"
        tunnel_ip, forwarded_ip = self._request_ips()
        client = forwarded_ip or tunnel_ip or "unknown"
        limit = _CONNECTOR_RATE_LIMITS[rate_class]
        if _server_environment_explicit():
            try:
                decision = production_workers.consume_rate_limit(
                    f"connector:{client}", f"connector.{rate_class}", limit=limit,
                )
            except production_workers.StorageError:
                self._err(
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    "Connector admission storage is unavailable.",
                    code="connector_rate_limit_unavailable",
                )
                return False
            if not decision["allowed"]:
                self._extra_headers.append(("Retry-After", str(decision["retry_after"])))
                self._err(
                    HTTPStatus.TOO_MANY_REQUESTS,
                    "Connector rate limit exceeded.",
                    code="connector_rate_limited",
                )
                return False
            return True
        now = time.monotonic()
        key = (client, rate_class)
        with _API_RATE_LOCK:
            bucket = _CONNECTOR_RATE[key]
            while bucket and bucket[0] <= now - 60:
                bucket.popleft()
            if len(bucket) >= limit:
                self._extra_headers.append(("Retry-After", "60"))
                self._err(
                    HTTPStatus.TOO_MANY_REQUESTS,
                    "Connector rate limit exceeded.",
                    code="connector_rate_limited",
                )
                return False
            bucket.append(now)
        return True

    def _cookie_value(self, name: str) -> str:
        try:
            cookie = SimpleCookie()
            cookie.load(str(self.headers.get("Cookie") or ""))
            return str(cookie[name].value) if name in cookie else ""
        except Exception:
            return ""

    def _set_session_cookie(self, token: str) -> None:
        secure = self._is_remote_api_request() or str(self.headers.get("X-Forwarded-Proto") or "").lower() == "https"
        # Canary uses an isolated cookie so cross-environment tokens are never
        # accepted; Development/Production keep the canonical name.
        value = (
            f"{runtime_env.session_cookie_name()}={token}; Path=/; Max-Age={account_auth.SESSION_TTL_SEC}; "
            f"HttpOnly; SameSite=Strict" + ("; Secure" if secure else "")
        )
        self._extra_headers.append(("Set-Cookie", value))

    def _device_cookie_name(self) -> str:
        return runtime_env.session_cookie_name() + "_device"

    def _device_credential(self) -> str:
        """Stable per-browser credential, minted on first contact.

        Only its digest is ever stored, and it is scoped per environment like
        the session cookie so one browser is a distinct device on Development,
        Canary and Production.  SameSite=Lax (not Strict) so the credential
        survives the return trip from Telegram and Google.
        """
        name = self._device_cookie_name()
        existing = str(self._cookie_value(name) or "").strip()
        if existing and 16 <= len(existing) <= 128 and re.fullmatch(r"[A-Za-z0-9_-]+", existing):
            return existing
        minted = getattr(self, "_minted_device_credential", "")
        if minted:
            return minted
        minted = account_auth.new_device_credential()
        self._minted_device_credential = minted
        secure = self._is_remote_api_request() or str(
            self.headers.get("X-Forwarded-Proto") or ""
        ).lower() == "https"
        self._extra_headers.append(("Set-Cookie", (
            f"{name}={minted}; Path=/; Max-Age={400 * 24 * 3600}; "
            "HttpOnly; SameSite=Lax" + ("; Secure" if secure else "")
        )))
        return minted

    def _set_dev_preview_mode_cookie(self, mode: str) -> None:
        secure = self._is_remote_api_request() or str(
            self.headers.get("X-Forwarded-Proto") or ""
        ).lower() == "https"
        value = (
            f"{_DEV_PREVIEW_MODE_COOKIE}={str(mode or '').strip()}; Path=/; Max-Age=300; "
            "HttpOnly; SameSite=Strict" + ("; Secure" if secure else "")
        )
        self._extra_headers.append(("Set-Cookie", value))

    def _clear_dev_preview_mode_cookie(self) -> None:
        secure = self._is_remote_api_request() or str(
            self.headers.get("X-Forwarded-Proto") or ""
        ).lower() == "https"
        value = (
            f"{_DEV_PREVIEW_MODE_COOKIE}=; Path=/; Max-Age=0; HttpOnly; SameSite=Strict"
            + ("; Secure" if secure else "")
        )
        self._extra_headers.append(("Set-Cookie", value))

    def _clear_session_cookie(self) -> None:
        secure = self._is_remote_api_request() or str(self.headers.get("X-Forwarded-Proto") or "").lower() == "https"
        value = f"{runtime_env.session_cookie_name()}=; Path=/; Max-Age=0; HttpOnly; SameSite=Strict" + ("; Secure" if secure else "")
        self._extra_headers.append(("Set-Cookie", value))

    @staticmethod
    def _request_hostname(value: str) -> str:
        raw = str(value or "").strip()
        if not raw:
            return ""
        try:
            parsed = urllib.parse.urlparse(raw if "://" in raw else "//" + raw)
            return str(parsed.hostname or "").lower()
        except (TypeError, ValueError):
            return ""

    def _is_remote_api_request(self) -> bool:
        if self.headers.get(telegram_remote.INIT_DATA_HEADER):
            return True
        hosts = [
            self._request_hostname(self.headers.get("Host") or ""),
            self._request_hostname(self.headers.get("X-Forwarded-Host") or ""),
            self._request_hostname(self.headers.get("Origin") or ""),
            self._request_hostname(self.headers.get("Referer") or ""),
        ]
        return any(host and host not in _ALLOWED_ORIGIN_HOSTS for host in hosts)

    def _local_owner_bypass_allowed(self) -> bool:
        """Whether this request may auto-resolve the owner/service without Telegram.

        This is the localhost convenience that lets the checked-out Development
        build open the real owner profile on 127.0.0.1 with no Telegram step and
        with the canonical data root. It is fail-closed for anything that is not
        physically local and is impossible in an explicitly-selected
        Canary/Production deployment:
          * the request must not be a remote/Mini App request (no Telegram
            initData, only loopback origin hosts), and
          * the transport peer and any forwarded-for must be a loopback IP, and
          * an explicitly-configured Canary/Production environment can never
            reach this path (hard invariant, independent of any flag or config),
          * otherwise it is allowed when the environment is Development (the
            local default, no flag needed) or the explicit test bypass is set.
        """
        if self._is_remote_api_request():
            return False
        tunnel_ip, forwarded_ip = self._request_ips()
        if not self._is_loopback_ip(tunnel_ip):
            return False
        if forwarded_ip and not self._is_loopback_ip(forwarded_ip):
            return False
        environment = runtime_env.deployment_environment()
        if (environment in (runtime_env.CANARY, runtime_env.PRODUCTION)
                and runtime_env.environment_explicit()):
            return False
        return environment == runtime_env.DEVELOPMENT or not account_auth.auth_required()

    def _local_owner_context(self) -> Dict[str, Any]:
        owner_env = str(os.environ.get(telegram_service.CHAT_ENV) or "").strip()
        user: Dict[str, Any] = {}
        owner_id = int(owner_env or 0)
        if owner_env:
            try:
                user = account_auth.ensure_owner(owner_env) or {}
            except account_auth.AccountAuthError:
                user = {}
        if not user:
            # Fall back to the canonical owner already saved in the local store
            # so a localhost dev session shows the real owner profile and data
            # (accounts, strategies, NinjaTrader, agents) instead of an empty
            # synthetic scope, even when NTA_TELEGRAM_CHAT_ID is not exported.
            resolved_id = account_auth.primary_owner_id()
            if resolved_id > 0:
                owner_id = resolved_id
                user = account_auth.primary_owner() or {}
        return self._decorate_workspace_context({
            "source": "local", "user_id": owner_id,
            "role": "owner", "is_owner": True,
            "csrf_token": "", "user": user,
            "_owner_scope_id": owner_id,
        })

    def _local_development_cookie_context(self) -> Optional[Dict[str, Any]]:
        """Resolve localhost Development access without letting stale cookies lock out owner."""
        if (
            runtime_env.is_development()
            and runtime_env.test_auth_enabled()
            and self._cookie_value(_DEV_PREVIEW_MODE_COOKIE) == "unauthenticated"
        ):
            # The explicit View-As persona must reach the genuine unauthenticated
            # path instead of being immediately converted back to local owner.
            return None
        cookie = self._cookie_value(runtime_env.session_cookie_name())
        if not cookie:
            return self._local_owner_context()
        try:
            session = account_auth.authenticate_session(cookie)
        except account_auth.AccountAuthError:
            session = None
        if session:
            if dev_service_accounts.available() and dev_service_accounts.is_service_uid(session.get("user_id")):
                return self._dev_service_context(session)
            # Keep real user sessions intact for local role/permission testing.
            return None
        if account_auth.session_auth_failure(cookie):
            return None
        self._clear_session_cookie()
        return self._local_owner_context()

    def _dev_service_context(self, session: Dict[str, Any]) -> Dict[str, Any]:
        """Context for a localhost Claude/GPT service session.

        Owner-equivalent authority over the owner's workspace/data (via the
        pre-established owner-role membership), but a distinct ``user_id`` so
        every action is audited under the service account, not the human owner.
        """
        uid = int(session.get("user_id") or 0)
        actor = dev_service_accounts.actor_for_uid(uid)
        spec = dev_service_accounts.SERVICE_ACCOUNTS.get(actor, {})
        user = account_auth.find_active_user(uid) or {
            "user_id": uid,
            "first_name": spec.get("first_name", "Service"),
            "last_name": spec.get("last_name", ""),
            "username": spec.get("username", ""),
            "role": "owner", "status": "active",
            "is_owner": False, "is_service_account": True,
            "ux_mode": "professional",
        }
        return self._decorate_workspace_context({
            "source": "dev_service", "user_id": uid,
            "role": "owner", "is_owner": True, "user": user,
            "session_id": str(session.get("session_id") or ""),
            "csrf_token": str(session.get("csrf_token") or ""),
            "service_actor": actor,
            "_owner_scope_id": 0,
        })

    def _decorate_workspace_context(self, context: Dict[str, Any]) -> Dict[str, Any]:
        scope_override = context.get("_owner_scope_id")
        if scope_override is None:
            owner_id = str(os.environ.get(telegram_service.CHAT_ENV) or "").strip()
        else:
            owner_id = str(scope_override or "")
        try:
            workspace_context = workspaces.context_for_user(
                context.get("user_id"),
                is_owner=bool(context.get("is_owner")),
                owner_id=owner_id,
            )
        except workspaces.WorkspaceError as exc:
            workspace_context = {"error": str(exc), "workspaces": [], "active_workspace": {}, "active_membership": {}}
        context["workspace_context"] = workspace_context
        context["workspaces"] = workspace_context.get("workspaces") or []
        context["active_workspace"] = workspace_context.get("active_workspace") or {}
        context["active_membership"] = workspace_context.get("active_membership") or {}
        if context.get("is_owner") and not context["active_workspace"]:
            # Local single-user mode may run before Telegram owner bootstrap.
            # Give it an explicit scope instead of emitting unowned writes.
            context["active_workspace"] = {
                "workspace_id": "ws_local_owner",
                "kind": "local_owner",
                "display_name": "Local owner",
                "uses_owner_runtime": True,
            }
            context["active_membership"] = {
                "workspace_id": "ws_local_owner",
                "user_id": context.get("user_id") or 0,
                "role": "owner",
            }
            context["workspace_context"] = {
                **workspace_context,
                "active_workspace": context["active_workspace"],
                "active_membership": context["active_membership"],
            }
        active = context["active_workspace"]
        membership = context["active_membership"]
        context["workspace_id"] = str(active.get("workspace_id") or "")
        context["membership_role"] = str(membership.get("role") or context.get("role") or "")
        try:
            resolved_user = dict(context.get("user") or {}) if isinstance(context.get("user"), dict) else {}
            if context.get("is_owner"):
                resolved_user["is_owner"] = True
            resolved = permissions.resolve_for_user_id(
                context.get("user_id"),
                resolved_user,
            )
        except Exception:
            # A damaged or temporarily unavailable entitlement store must not
            # turn an otherwise read-only request into HTTP 500.  Keep the
            # mandatory context shape and fail closed on every paid capability.
            resolved = {
                "capabilities": {
                    capability_id: bool(context.get("is_owner"))
                    for capability_id in permissions.CAPABILITY_IDS
                },
                "admin_capabilities": {
                    capability_id: bool(context.get("is_owner"))
                    for capability_id in permissions.ADMIN_CAPABILITY_IDS
                },
                "ux_mode": "professional" if context.get("is_owner") else str(
                    (context.get("user") or {}).get("ux_mode") or ""
                ),
            }
        if context.get("is_owner"):
            # The local/test owner can legitimately exist before the durable
            # account row is bootstrapped.  Permission lookup then returns a
            # fail-closed empty record even though the request is already
            # authenticated as owner.  Owner parity is authoritative here.
            context["capabilities"] = {
                capability_id: True for capability_id in permissions.CAPABILITY_IDS
            }
            context["admin_capabilities"] = {
                capability_id: True for capability_id in permissions.ADMIN_CAPABILITY_IDS
            }
            context["ux_mode"] = "professional"
        else:
            context["capabilities"] = dict(resolved.get("capabilities") or {})
            context["admin_capabilities"] = dict(
                resolved.get("admin_capabilities") or {}
            )
            context["ux_mode"] = str(resolved.get("ux_mode") or "")
        context["_permissions"] = resolved
        return context

    def _data_scope(self) -> Dict[str, Any]:
        context = getattr(self, "_remote_context", None) or {}
        return {
            "workspace_id": str(context.get("workspace_id") or ""),
            "user_id": context.get("user_id") or "",
            # Pre-workspace queue artifacts belong to the original local owner.
            "allow_legacy": bool(context.get("is_owner")),
        }

    def _require_data_scope(self) -> Optional[Dict[str, Any]]:
        scope = self._data_scope()
        if not scope["workspace_id"]:
            self._err(
                HTTPStatus.CONFLICT,
                "Для записи нужна активная рабочая область.",
                code="workspace_required",
            )
            return None
        return scope

    def _write_origin(self) -> Optional[Dict[str, Any]]:
        scope = self._require_data_scope()
        if scope is None:
            return None
        context = getattr(self, "_remote_context", None) or {}
        return {
            "workspace_id": scope["workspace_id"],
            "user_id": str(scope["user_id"] or ""),
            "membership_role": str(context.get("membership_role") or ""),
            "source": str(context.get("source") or "http"),
        }

    def _workspace_runtime_stubbed(self, path: str, qs: Dict[str, Any]) -> bool:
        context = getattr(self, "_remote_context", None) or {}
        payload = workspaces.runtime_stub(path, qs, context.get("workspace_context") or {})
        if payload is None:
            return False
        self._json(HTTPStatus.OK, payload)
        return True

    def _api_action_class(self, path: str, method: str) -> str:
        if permissions.required_admin_capability(path, method):
            return "owner"
        if path.startswith("/api/auth/"):
            # Session/profile reads are ordinary authenticated UI polling.
            # Keeping them in the small login/mutation bucket makes a healthy
            # long-lived session hit 429 even though account_auth applies its
            # own stricter IP limiter to actual login attempts.
            return "read" if method.upper() in {"GET", "HEAD"} else "auth"
        method_u = method.upper()
        # High-frequency owner UI polls must not share the tight "owner" bucket
        # (60/min) with mutating Viteк/Telegram actions — otherwise the Overview
        # + notifications + chat polling cascade trips HTTP 429.
        if method_u in {"GET", "HEAD"} and (
            path == "/api/notifications"
            or path == "/api/vitek/status"
            or path == "/api/vitek/time-windows"
        ):
            return "read"
        if (path.startswith("/api/owner/") or path.startswith("/api/telegram/")
                or path.startswith("/api/worker/") or path.startswith("/api/vitek/")
                or path.startswith("/api/notifications")):
            return "owner"
        return "read" if method_u in {"GET", "HEAD"} else "write"

    def _check_api_rate_limit(self, context: Dict[str, Any], path: str) -> bool:
        if runtime_env.rate_limits_disabled():
            return True
        action = self._api_action_class(path, self.command)
        limit = int(_API_RATE_LIMITS.get(action, 120))
        tunnel_ip, _forwarded_ip = self._request_ips()
        user_id = str(context.get("user_id") or "anonymous")
        key = (user_id, str(tunnel_ip or ""), action)
        now = time.time()
        if _server_environment_explicit():
            try:
                decision = production_workers.consume_rate_limit(
                    f"user:{user_id}|origin:{tunnel_ip or 'unknown'}",
                    f"api.{action}",
                    limit=limit,
                )
            except production_workers.StorageError:
                self._err(
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    "Request admission storage is unavailable.",
                    code="api_rate_limit_unavailable",
                )
                return False
            if not decision["allowed"]:
                self._err(
                    HTTPStatus.TOO_MANY_REQUESTS,
                    "Слишком много запросов. Повторите позже.",
                    headers={"Retry-After": str(decision["retry_after"])},
                )
                return False
            return True
        with _API_RATE_LOCK:
            q = _API_RATE[key]
            while q and q[0] <= now - 60:
                q.popleft()
            if len(q) >= limit:
                retry_after = max(1, int(math.ceil(q[0] + 60 - now)))
                self._err(
                    HTTPStatus.TOO_MANY_REQUESTS,
                    "Слишком много запросов. Повторите позже.",
                    headers={"Retry-After": str(retry_after)},
                )
                return False
            q.append(now)
        return True

    def _authorize_api(self, path: str) -> bool:
        # Internal owner market-data consumers authenticate with a shared
        # token on chart endpoints only.  This never grants Admin, Documents
        # or Release Center.  A consumer process rejects inbound consume
        # requests so Canary cannot recurse through another consumer.
        supplied_gateway_token = str(self.headers.get(owner_market_data_gateway.TOKEN_HEADER) or "").strip()
        if supplied_gateway_token and owner_market_data_gateway.request_is_chart_endpoint(self, path):
            if owner_market_data_gateway.loop_consume_rejected(self):
                self._err(
                    HTTPStatus.FORBIDDEN,
                    "Owner market-data gateway loop rejected.",
                    code="owner_gateway_loop_detected",
                )
                return False
            if owner_market_data_gateway.authorize_gateway_request(self, path):
                self._remote_context = owner_market_data_gateway.service_context()
                return True
            self._err(
                HTTPStatus.UNAUTHORIZED,
                "Owner market-data gateway token rejected.",
                code="owner_gateway_unauthorized",
            )
            return False
        # The local-owner bypass (no Telegram login) is ONLY safe for requests
        # that physically originate on the owner's machine: loopback, no Telegram
        # initData header and no public tunnel host. A remote request — the public
        # Mini App tunnel or anything carrying Telegram initData — must ALWAYS be
        # authenticated against the approved account allowlist, even when desktop
        # auth is disabled. Otherwise every Mini App visitor would inherit full
        # owner access (the reported "instant access" security hole). On the
        # checked-out Development build this path is the default (no flag needed);
        # Canary/Production can never reach it (see _local_owner_bypass_allowed).
        if self._local_owner_bypass_allowed():
            try:
                local_context = self._local_development_cookie_context()
            except account_auth.AccountAuthError as exc:
                self._err(exc.status, str(exc)); return False
            if local_context is not None:
                self._remote_context = local_context
                return True
            # A valid regular localhost session falls through to the normal
            # authenticated-session path so role/permission tests stay real.
        tunnel_ip, forwarded_ip = self._request_ips()
        init_data = str(self.headers.get(telegram_remote.INIT_DATA_HEADER) or "")
        if init_data:
            self._remote_attempt = True
            try:
                self._remote_context = telegram_remote.authorize(
                    init_data, str(os.environ.get(telegram_service.TOKEN_ENV) or ""),
                    method=self.command, path=path, tunnel_ip=tunnel_ip,
                    forwarded_ip=forwarded_ip,
                )
                # Telegram initData authenticates the Mini App request, while
                # the protected browser session carries device-scoped step-up
                # state. Merge it only when both identities are identical.
                remote_user_uuid = account_auth.user_uuid_for_legacy_id(
                    self._remote_context.get("user_id"),
                )
                if remote_user_uuid:
                    self._remote_context["user_uuid"] = remote_user_uuid
                browser_session = account_auth.authenticate_session(
                    self._cookie_value(runtime_env.session_cookie_name())
                )
                if (browser_session and str(browser_session.get("user_id") or "")
                        == str(self._remote_context.get("user_id") or "")
                        and remote_user_uuid
                        and str(browser_session.get("user_uuid") or "") == remote_user_uuid):
                    for key in (
                        "session_id", "device_id", "csrf_hash", "csrf_token",
                        "nt_elevated_until", "impersonating",
                        "impersonator_owner_id", "impersonation_started_at_utc",
                        "impersonation_preset",
                    ):
                        if key in browser_session:
                            self._remote_context[key] = browser_session[key]
                account: Dict[str, Any] = {}
                if (
                    "is_owner" not in self._remote_context
                    or not isinstance(self._remote_context.get("user"), dict)
                ):
                    account = account_auth.find_active_user(
                        self._remote_context.get("user_id"),
                    ) or {}
                    self._remote_context["is_owner"] = bool(account.get("is_owner"))
                # Populate the public profile so /api/auth/me and other handlers
                # that read context["user"] (name, e-mail, avatar, features) work
                # over the Telegram Mini App, exactly like the desktop session path.
                if account:
                    self._remote_context["user"] = account_auth._public_user(
                        account, include_contact=True)
                self._remote_context = self._decorate_workspace_context(self._remote_context)
                method = self.command.upper()
                admin_route = bool(permissions.required_admin_capability(path, method))
                role = str(self._remote_context.get("role") or "read_only")
                workspace = self._remote_context.get("active_workspace") if isinstance(self._remote_context.get("active_workspace"), dict) else {}
                membership_role = str(self._remote_context.get("membership_role") or "viewer")
                personal_statement_write = path.startswith("/api/ops/runtime/account-history/") and bool(workspace) and not workspace.get("uses_owner_runtime")
                impersonation_exit = _is_impersonation_exit(path, self._remote_context)
                if (method not in {"GET", "HEAD"} and workspace.get("uses_owner_runtime")
                        and membership_role not in workspaces.WRITE_ROLES
                        and not _is_self_service_post(path) and not admin_route and not impersonation_exit):
                    raise telegram_remote.RemoteAccessError(
                        "В этой рабочей области доступно только наблюдение.", 403,
                        self._remote_context,
                    )
                if (method not in {"GET", "HEAD"} and role == "read_only" and not _is_self_service_post(path)
                        and not admin_route and not impersonation_exit
                        and not path.startswith("/api/bridge/connections/") and not personal_statement_write):
                    raise telegram_remote.RemoteAccessError("Для этого действия нужна роль «полное управление».", 403, self._remote_context)
                if _is_owner_only_api_path(path, method) and not self._remote_context["is_owner"] and not impersonation_exit:
                    raise telegram_remote.RemoteAccessError(
                        "Это действие разрешено только владельцу.", 403,
                        self._remote_context,
                    )
                try:
                    self._remote_context["_request_method"] = method
                    if not impersonation_exit:
                        permissions.enforce(path, self._remote_context)
                except permissions.PermissionError as exc:
                    raise telegram_remote.RemoteAccessError(str(exc), exc.status, self._remote_context) from None
                if not impersonation_exit and account_auth.path_requires_nt_dual_auth(path, method):
                    try:
                        account_auth.require_nt_dual_auth(self._remote_context)
                    except account_auth.AccountAuthError as exc:
                        raise telegram_remote.RemoteAccessError(str(exc), exc.status, self._remote_context) from None
                if not self._check_api_rate_limit(self._remote_context, path):
                    return False
                return True
            except (telegram_remote.RemoteAccessError, account_auth.AccountAuthError) as exc:
                self._remote_context = getattr(exc, "context", None)
                self._remote_error = str(exc)
                self._err(getattr(exc, "status", 403), str(exc), code=getattr(exc, "code", "") or "")
                return False
        try:
            context = account_auth.authenticate_session(
                self._cookie_value(runtime_env.session_cookie_name()),
            )
        except account_auth.AccountAuthError as exc:
            self._err(exc.status, str(exc), code=getattr(exc, "code", "") or ""); return False
        if not context:
            self._err(HTTPStatus.UNAUTHORIZED, "Требуется вход через Telegram.")
            return False
        context = self._decorate_workspace_context(context)
        method = self.command.upper()
        admin_route = bool(permissions.required_admin_capability(path, method))
        role = str(context.get("role") or "read_only")
        workspace = context.get("active_workspace") if isinstance(context.get("active_workspace"), dict) else {}
        membership_role = str(context.get("membership_role") or "viewer")
        personal_statement_write = path.startswith("/api/ops/runtime/account-history/") and bool(workspace) and not workspace.get("uses_owner_runtime")
        impersonation_exit = _is_impersonation_exit(path, context)
        if (method not in {"GET", "HEAD"} and workspace.get("uses_owner_runtime")
                and membership_role not in workspaces.WRITE_ROLES
                and not _is_self_service_post(path) and not admin_route and not impersonation_exit):
            self._err(HTTPStatus.FORBIDDEN, "В этой рабочей области доступно только наблюдение.")
            return False
        if (method not in {"GET", "HEAD"} and role == "read_only" and not _is_self_service_post(path)
            and not admin_route and not impersonation_exit
            and not path.startswith("/api/bridge/connections/") and not personal_statement_write):
            self._err(HTTPStatus.FORBIDDEN, "Для этого действия нужна роль «полное управление».")
            return False
        if _is_owner_only_api_path(path, method) and not context.get("is_owner") and not impersonation_exit:
            self._err(HTTPStatus.FORBIDDEN, "Это действие разрешено только владельцу.")
            return False
        try:
            context["_request_method"] = method
            if not impersonation_exit:
                permissions.enforce(path, context)
        except permissions.PermissionError as exc:
            self._err(exc.status, str(exc)); return False
        if not impersonation_exit and account_auth.path_requires_nt_dual_auth(path, method):
            try:
                account_auth.require_nt_dual_auth(context)
            except account_auth.AccountAuthError as exc:
                self._err(exc.status, str(exc), code=getattr(exc, "code", "") or ""); return False
        if not self._check_api_rate_limit(context, path):
            return False
        self._remote_context = context
        return True

    def _check_local_post(self) -> bool:
        """Reject cross-site POSTs from a browser. Returns True if the request
        is allowed (and writes an error + returns False otherwise).

        Rules:
          - Content-Type must be application/json (case-insensitive, params ok).
          - Origin (preferred) or Referer, if present, must point to
            http://127.0.0.1:<this_port> or http://localhost:<this_port>.
          - Missing Origin AND Referer is allowed (CLI/PowerShell clients).
        """
        ct = (self.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
        if ct != "application/json":
            self._err(HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
                      "Content-Type must be application/json")
            return False
        return self._check_local_origin()

    def _check_json_content_type(self) -> bool:
        ct = (self.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
        if ct != "application/json":
            self._err(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "Content-Type must be application/json")
            return False
        return True

    def _connector_public_post(self, path: str) -> None:
        routes = {
            "/api/connector/v1/enroll",
            "/api/connector/v1/challenge",
            "/api/connector/v1/hello",
            "/api/connector/v1/heartbeat",
            "/api/connector/v1/market-data",
            "/api/connector/v1/commands/poll",
            "/api/connector/v1/commands/result",
        }
        if path not in routes:
            self._err(HTTPStatus.NOT_FOUND, "no connector route", code="connector_route_not_found")
            return
        if not self._check_json_content_type() or not self._check_connector_rate_limit(path):
            return
        body = self._read_body()
        if body is None:
            return
        if not isinstance(body, dict):
            self._err(HTTPStatus.BAD_REQUEST, "Connector body must be an object.", code="invalid_connector_body")
            return
        self._extra_headers.extend([
            ("Cache-Control", "no-store"),
            ("Pragma", "no-cache"),
        ])
        try:
            if path.endswith("/enroll"):
                out = connector_protocol.enroll_device(body)
            elif path.endswith("/challenge"):
                out = connector_protocol.issue_challenge(body)
            elif path.endswith("/hello"):
                out = connector_protocol.signed_hello(body)
            elif path.endswith("/heartbeat"):
                out = connector_protocol.heartbeat(self._connector_bearer_token(), body)
            elif path.endswith("/market-data"):
                out = connector_protocol.ingest_market_data(
                    self._connector_bearer_token(), body,
                )
            elif path.endswith("/commands/poll"):
                out = connector_protocol.poll_commands(
                    self._connector_bearer_token(),
                    connector_sequence=body.get("connector_sequence"),
                    wait_seconds=body.get("wait_seconds") or 0,
                    limit=body.get("limit") or 10,
                )
            else:
                out = connector_protocol.submit_result(
                    self._connector_bearer_token(), body,
                )
            self._json(HTTPStatus.OK, out)
        except connector_protocol.ConnectorProtocolError as exc:
            self._err(exc.status, str(exc), code=exc.code)

    def _check_public_auth_origin(self) -> bool:
        if not self._check_json_content_type():
            return False
        origin = self.headers.get("Origin")
        if not origin:
            self._err(HTTPStatus.FORBIDDEN, "Origin обязателен для входа.")
            return False
        origin_host = self._request_hostname(origin)
        request_host = self._request_hostname(self.headers.get("X-Forwarded-Host") or self.headers.get("Host") or "")
        if not origin_host or origin_host != request_host:
            self._err(HTTPStatus.FORBIDDEN, "Cross-origin запрос входа отклонён.")
            return False
        return True

    def _augment_permissions(self, context: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, Any]:
        """Attach the central authorization view (subscription-driven nav +
        capabilities + Free Preview state) to an auth payload."""
        user = payload.get("user") or {}
        is_owner = bool(payload.get("is_owner"))
        subscription: Dict[str, Any] = {}
        if not is_owner:
            try:
                subscription = subscriptions.active_entitlement(context.get("user_id"))
            except subscriptions.SubscriptionError:
                subscription = {}
        permission_user = {**user, "is_owner": True} if is_owner else user
        perm = permissions.resolve(permission_user, None if is_owner else subscription)
        if isinstance(user, dict):
            payload["user"] = {**user, "features": perm["nav"]}
        payload["features"] = perm["nav"]
        payload["capabilities"] = perm["capabilities"]
        payload["capability_catalog"] = permissions.capability_catalog()
        payload["admin_capabilities"] = perm["admin_capabilities"]
        payload["admin_capability_catalog"] = permissions.admin_capability_catalog()
        payload["plan_id"] = perm["plan_id"]
        payload["free_preview"] = perm["free_preview"]
        payload["locked_nav"] = perm["locked_nav"]
        payload["unlock_message"] = perm["unlock_message"]
        payload["ux_mode"] = perm.get("ux_mode") or (user.get("ux_mode") if isinstance(user, dict) else "") or ""
        payload["ux_pending"] = bool(perm.get("ux_pending"))
        payload["demo_tier"] = bool(perm.get("demo_tier"))
        return payload

    def _ai_conversation_scope(self) -> Dict[str, Any]:
        context = getattr(self, "_remote_context", None) or {}
        active = context.get("active_workspace") if isinstance(context.get("active_workspace"), dict) else {}
        membership = context.get("active_membership") if isinstance(context.get("active_membership"), dict) else {}
        user = context.get("user") if isinstance(context.get("user"), dict) else {}
        display = " ".join(
            str(user.get(key) or "").strip() for key in ("first_name", "last_name")
        ).strip() or str(user.get("username") or "")
        if not context.get("user_id"):
            if (
                context.get("is_owner")
                and str(context.get("source") or "") == "local"
                and not (
                    runtime_env.is_production()
                    and runtime_env.environment_explicit()
                )
            ):
                # A Development desktop may exist before Telegram owner
                # bootstrap. Keep its historical unscoped local path, while
                # explicit Production remains fail-closed.
                return {}
            raise ai_chief_agent.ChiefAgentError(
                "Для AI-чата нужна активная рабочая область пользователя."
            )
        if not active.get("workspace_id"):
            raise ai_chief_agent.ChiefAgentError("Для AI-чата нужна активная рабочая область пользователя.")
        workspace_context = context.get("workspace_context") if isinstance(context.get("workspace_context"), dict) else {
            "active_workspace": active,
            "active_membership": membership,
            "uses_owner_runtime": bool(active.get("uses_owner_runtime")),
        }
        scope = {
            "user_id": context.get("user_id"),
            "workspace_id": active.get("workspace_id"),
            "workspace_kind": active.get("kind") or "",
            "uses_owner_runtime": bool(active.get("uses_owner_runtime")),
            "runtime_dir": workspaces.runtime_storage_dir_for_context(workspace_context),
            "membership_role": membership.get("role") or context.get("role") or "",
            "is_owner": bool(context.get("is_owner")),
            "display_name": display,
            "capabilities": context.get("capabilities") if isinstance(context.get("capabilities"), dict) else {},
        }
        user_uuid = str(user.get("user_uuid") or user.get("id") or "").strip()
        if not user_uuid:
            user_uuid = account_auth.user_uuid_for_legacy_id(context.get("user_id"))
        if user_uuid:
            scope["user_uuid"] = user_uuid
        return scope

    def _auth_providers_payload(self) -> Dict[str, Any]:
        bot_username = telegram_service.bot_username()
        google = google_auth.status()
        email = account_auth.email_auth_status()
        return {
            "ok": True,
            "identity_model": "uuid",
            "owner_approval_required": True,
            "providers": {
                "telegram": {
                    "available": bool(bot_username),
                    "configured": bool(bot_username),
                    "bot_username": bot_username,
                },
                "google": {
                    "available": bool(google.get("configured")),
                    "configured": bool(google.get("configured")),
                    "test_auth_fallback": bool(google.get("test_auth_fallback")),
                },
                "email": email,
            },
        }

    def _auth_status(self) -> None:
        try:
            # Fast-path: the request is genuinely local (loopback desktop, no
            # Telegram initData, no public tunnel host) AND either the explicit
            # test bypass is active or this is the Development build. Return the
            # local-owner context so the desktop shell loads without a Telegram
            # login. Remote requests never take this path — they are always
            # authenticated below so Mini App visitors can't inherit owner.
            if self._local_owner_bypass_allowed():
                context = self._local_development_cookie_context()
                if context is not None:
                    self._json(HTTPStatus.OK, self._augment_permissions(context, {
                        "authenticated": True, "source": context.get("source"),
                        "role": context.get("role"), "is_owner": bool(context.get("is_owner")),
                        "csrf_token": "", "user": context.get("user") or {},
                        "workspaces": context.get("workspaces") or [],
                        "active_workspace": context.get("active_workspace") or {},
                        "active_membership": context.get("active_membership") or {},
                    }))
                    return
                # A valid regular localhost session falls through to the normal
                # status path below so its actual role/permissions are surfaced.
            owner_id = str(os.environ.get(telegram_service.CHAT_ENV) or "").strip()
            account_auth.ensure_owner(owner_id)
            init_data = str(self.headers.get(telegram_remote.INIT_DATA_HEADER) or "")
            context = None
            if init_data:
                tunnel_ip, forwarded_ip = self._request_ips()
                context = telegram_remote.authorize(
                    init_data, str(os.environ.get(telegram_service.TOKEN_ENV) or ""),
                    method="GET", path="/api/auth/status", tunnel_ip=tunnel_ip,
                    forwarded_ip=forwarded_ip,
                )
                user = account_auth.find_active_user(context.get("user_id"))
                context["user"] = account_auth._public_user(user or {}, include_contact=True)
                context["role"] = str((user or {}).get("role") or context.get("role") or "read_only")
                context["is_owner"] = bool((user or {}).get("is_owner"))
                # Record the Mini App session for the admin login history (throttled
                # so repeated status polls during one session don't spam the log).
                account_auth.record_login(
                    context.get("user_id"), source=telegram_remote.SOURCE,
                    ip=forwarded_ip or tunnel_ip,
                    user_agent=str(self.headers.get("User-Agent") or ""),
                    throttle_sec=6 * 3600)
            else:
                context = account_auth.authenticate_session(self._cookie_value(runtime_env.session_cookie_name()))
            if context:
                context = self._decorate_workspace_context(context)
            if not context:
                failure = account_auth.session_auth_failure(self._cookie_value(runtime_env.session_cookie_name()))
                if failure:
                    self._clear_session_cookie()
                    self._json(HTTPStatus.UNAUTHORIZED, {
                        **failure,
                        "authenticated": False,
                        "auth_required": account_auth.auth_required(),
                        "bot_username": telegram_service.bot_username(),
                        "storage": account_auth.storage_status(),
                        "providers": self._auth_providers_payload()["providers"],
                    })
                    return
                self._json(HTTPStatus.UNAUTHORIZED, {
                    "error": "Требуется вход.", "authenticated": False,
                    "auth_required": account_auth.auth_required(),
                    "bot_username": telegram_service.bot_username(),
                    "storage": account_auth.storage_status(),
                    "providers": self._auth_providers_payload()["providers"],
                })
                return
            payload = {
                "authenticated": True, "source": context.get("source"),
                "role": context.get("role"), "is_owner": bool(context.get("is_owner")),
                "csrf_token": str(context.get("csrf_token") or ""),
                "user": context.get("user") or {},
                "workspaces": context.get("workspaces") or [],
                "active_workspace": context.get("active_workspace") or {},
                "active_membership": context.get("active_membership") or {},
                "needs_google": bool(context.get("needs_google")),
                "dual_auth_complete": True,
                "nt_access": context.get("nt_access") or account_auth.nt_action_gate(None, context=context),
                "impersonating": bool(context.get("impersonating")),
                "impersonator_owner_id": context.get("impersonator_owner_id"),
                "impersonation_started_at_utc": context.get("impersonation_started_at_utc") or "",
                "impersonation_preset": context.get("impersonation_preset") or "",
                "runtime": runtime_env.status(),
                "google_oauth": google_auth.status(),
                "providers": self._auth_providers_payload()["providers"],
            }
            self._json(HTTPStatus.OK, self._augment_permissions(context, payload))
        except (account_auth.AccountAuthError, telegram_remote.RemoteAccessError) as exc:
            self._err(getattr(exc, "status", 503), str(exc))

    def _user_nt_info(self, user_id: Any, is_owner: bool = False) -> Dict[str, Any]:
        """NinjaTrader connection summary for one user: observing the owner's
        runtime vs. running their own bridge, plus the active workspace name."""
        owner_id = str(os.environ.get(telegram_service.CHAT_ENV) or "").strip()
        try:
            wc = workspaces.context_for_user(user_id, is_owner=is_owner, owner_id=owner_id)
        except workspaces.WorkspaceError:
            return {"uses_owner_runtime": True, "connected": bool(is_owner),
                    "connection_id": "", "mode": "observe_owner", "workspace": ""}
        active = wc.get("active_workspace") or {}
        uses_owner = bool(active.get("uses_owner_runtime"))
        conn_id = str(active.get("default_runtime_connection_id") or "")
        return {
            "uses_owner_runtime": uses_owner,
            "connection_id": conn_id,
            "connected": (is_owner and uses_owner) or (not uses_owner and bool(conn_id)),
            "mode": "observe_owner" if uses_owner else "own_ninjatrader",
            "workspace": str(active.get("display_name") or ""),
        }

    def _render_invite(self, out: Dict[str, Any]) -> Dict[str, Any]:
        voucher = out.get("voucher") or {}
        invite = out.get("invite") or {}
        code = str(voucher.get("code") or invite.get("code") or "")
        plan = subscriptions.PLANS.get(str(voucher.get("grant_plan_id") or "")) or {}
        plan_label = str(plan.get("label") or "")
        try:
            discount_percent = int(voucher.get("discount_percent") or 0)
        except (TypeError, ValueError):
            discount_percent = 0
        try:
            price_usd = float(plan.get("price_usd") or 0)
        except (TypeError, ValueError):
            price_usd = 0.0
        period = str(plan.get("period") or "")
        ctx = getattr(self, "_remote_context", None) or {}
        who = ctx.get("user") or {}
        inviter = (" ".join([str(who.get("first_name") or ""), str(who.get("last_name") or "")]).strip()
                   or str(who.get("username") or ""))
        rendered = invitations.render_invitation(
            code=code, telegram_link=str(invite.get("telegram") or ""),
            web_link=str(invite.get("web") or ""), plan_label=plan_label, inviter=inviter,
            discount_percent=discount_percent, price_usd=price_usd, period=period)
        rendered.pop("png_bytes", None)  # bytes are not JSON serialisable
        return rendered

    def _send_invite(self, body: Dict[str, Any]) -> Dict[str, Any]:
        import base64 as _b64
        text = str(body.get("text") or "")[:3500]
        image_data_url = str(body.get("image_data_url") or "")
        owner_chat = str(os.environ.get(telegram_service.CHAT_ENV) or "").strip()
        if not owner_chat:
            return {"ok": False, "error": "Telegram владельца не настроен."}
        png: Optional[bytes] = None
        if image_data_url.startswith("data:image/png;base64,") and len(image_data_url) < 4_000_000:
            try:
                png = _b64.b64decode(image_data_url.split(",", 1)[1], validate=True)
            except Exception:
                png = None
        sent = False
        if png and telegram_service.send_photo_bytes(owner_chat, png, caption=text[:1024], filename="invite.png"):
            sent = True
        else:
            try:
                telegram_service._send_raw(text or "Приглашение StratForge AI", chat_id=owner_chat)
                sent = True
            except telegram_service.TelegramServiceError:
                sent = False
        return {"ok": bool(sent), "sent_to": "owner"}

    def _admin_operations_payload(self) -> Dict[str, Any]:
        context = getattr(self, "_remote_context", None) or {}
        payload = observability.dashboard()
        payload["worker"] = (
            production_workers.status()
            if _server_environment_explicit()
            else local_worker.status()
        )
        try:
            payload["telegram"] = (
                production_telegram.get_queue().status()
                if _server_environment_explicit()
                else telegram_service.status()
            )
        except production_telegram.StorageError as exc:
            payload["telegram"] = {"ok": False, "code": exc.code}
        try:
            payload["connector"] = connector_protocol.list_installations(
                context.get("user_id"),
                workspace_id=str(context.get("workspace_id") or ""),
            )
        except connector_protocol.ConnectorProtocolError as exc:
            payload["connector"] = {"ok": False, "code": exc.code}
        payload["actions"] = _operations_actions()
        return payload

    def _cabinet_payload(self) -> Dict[str, Any]:
        context = getattr(self, "_remote_context", None) or {}
        uid = context.get("user_id")
        user = context.get("user") or {}
        is_owner = bool(context.get("is_owner"))
        try:
            subs = subscriptions.entitlements_for_user(uid)
        except subscriptions.SubscriptionError:
            subs = {"entitlements": []}
        entitlements = subs.get("entitlements") or []
        if is_owner:
            try:
                subscription = subscriptions.owner_entitlement()
            except subscriptions.SubscriptionError:
                subscription = {}
        else:
            subscription = next(
                (row for row in entitlements if row.get("active")),
                entitlements[0] if entitlements else {},
            )
        active = context.get("active_workspace") or {}
        membership = context.get("active_membership") or {}
        # The owner is NOT a learner: their contour is the real NinjaTrader with
        # full access. Only non-owner viewers are "observing" the owner account.
        owner_full_access = is_owner and bool(active.get("uses_owner_runtime"))
        # Central authorization: turn the plan (or Free Preview) + owner overrides
        # into concrete capabilities and navigation. The client gates the rail and
        # locks premium sections from this single source of truth.
        permission_user = {**user, "is_owner": True} if is_owner else user
        perm = (
            context.get("_permissions")
            if isinstance(context.get("_permissions"), dict) else {}
        )
        if not perm:
            perm = permissions.resolve(
                permission_user, None if is_owner else subscription,
            )
        admin_capabilities = perm.get("admin_capabilities")
        if not isinstance(admin_capabilities, dict):
            # Keep older/mocked request contexts compatible while still deriving
            # the new control-plane grants from the authenticated user record.
            admin_capabilities = permissions.resolve_admin_capabilities(permission_user)
        nav_features = perm["nav"]
        if isinstance(user, dict):
            user = {**user, "features": nav_features}
        return {
            "authenticated": True,
            "source": context.get("source"),
            "user": user,
            "role": context.get("role"),
            "is_owner": is_owner,
            "workspaces": context.get("workspaces") or [],
            "active_workspace": active,
            "active_membership": membership,
            "subscription": subscription,
            "entitlements": entitlements,
            "features": nav_features,
            "feature_catalog": account_auth.feature_catalog(),
            "capabilities": perm["capabilities"],
            "capability_catalog": permissions.capability_catalog(),
            "admin_capabilities": admin_capabilities,
            "admin_capability_catalog": permissions.admin_capability_catalog(),
            "plan_id": perm["plan_id"],
            "free_preview": perm["free_preview"],
            "locked_nav": perm["locked_nav"],
            "unlock_message": perm["unlock_message"],
            "demo_tier": bool(perm.get("demo_tier")),
            # Keep /api/auth/me consistent with /api/auth/status.  Mini App
            # clients use this cabinet endpoint after Telegram authorization,
            # so they must receive the mandatory UX-mode state as well.
            "ux_mode": str(perm.get("ux_mode") or ""),
            "ux_pending": bool(perm.get("ux_pending")),
            "payments_enabled": bool(subscriptions.payments_active()),
            "telegram_configured": bool(str(os.environ.get(telegram_service.TOKEN_ENV) or "").strip()),
            "needs_google": bool(context.get("needs_google") or (isinstance(user, dict) and user.get("needs_google"))),
            "dual_auth_complete": True,
            "nt_access": context.get("nt_access") or account_auth.nt_action_gate(user if isinstance(user, dict) else None, context=context),
            "impersonating": bool(context.get("impersonating")),
            "impersonator_owner_id": context.get("impersonator_owner_id"),
            "impersonation_started_at_utc": context.get("impersonation_started_at_utc") or "",
            "impersonation_preset": context.get("impersonation_preset") or "",
            "runtime": runtime_env.status(),
            "google_oauth": google_auth.status(),
            "nt_connection": {
                "uses_owner_runtime": bool(active.get("uses_owner_runtime")),
                "owner_full_access": owner_full_access,
                "connected": (owner_full_access
                              or (bool(active.get("default_runtime_connection_id")) and not active.get("uses_owner_runtime"))),
                "connection_id": str(active.get("default_runtime_connection_id") or ""),
            },
        }

    def _auth_me(self) -> None:
        self._json(HTTPStatus.OK, self._cabinet_payload())

    def _google_oauth_start(self) -> None:
        context = getattr(self, "_remote_context", None) or {}
        uid = int(context.get("user_id") or 0)
        if uid <= 0:
            self._err(HTTPStatus.UNAUTHORIZED, "Требуется вход."); return
        body = self._read_body() or {}
        try:
            out = google_auth.start_link(
                user_id=uid,
                redirect_uri=self._google_redirect_uri(body),
                return_path=str(body.get("return_path") or "/ui/"),
            )
            self._json(HTTPStatus.OK, out)
        except google_auth.GoogleAuthError as exc:
            self._err(exc.status, str(exc))

    def _google_redirect_uri(self, body: Dict[str, Any]) -> str:
        host = str(self.headers.get("X-Forwarded-Host") or self.headers.get("Host") or "").strip()
        proto = str(self.headers.get("X-Forwarded-Proto") or "http").split(",", 1)[0].strip() or "http"
        default_redirect = f"{proto}://{host}/api/auth/google/callback" if host else ""
        return str(body.get("redirect_uri") or google_auth.credentials().get("redirect_uri") or default_redirect)

    def _google_oauth_callback(self, qs: Dict[str, Any]) -> None:
        code = str((qs.get("code") or [""])[0] or "")
        state = str((qs.get("state") or [""])[0] or "")
        err = str((qs.get("error") or [""])[0] or "")
        if err:
            self._html_redirect("/ui/?google_error=" + urllib.parse.quote(err))
            return
        try:
            identity = google_auth.exchange_code(code=code, state=state)
            path = str(identity.get("return_path") or "/ui/")
            if identity.get("purpose") == "login":
                tunnel_ip, forwarded_ip = self._request_ips()
                out = account_auth.login_via_google_identity(
                    device_credential=self._device_credential(),
                    google_sub=identity["google_sub"],
                    google_email=identity.get("google_email") or "",
                    google_name=identity.get("google_name") or "",
                    email_verified=bool(identity.get("email_verified")),
                    accept_terms=bool(identity.get("accept_terms")),
                    ip=forwarded_ip or tunnel_ip,
                    user_agent=str(self.headers.get("User-Agent") or ""),
                    api_call=telegram_service._api_call,
                    owner_chat_id=str(os.environ.get(telegram_service.CHAT_ENV) or ""),
                )
                token = str(out.pop("session_token", ""))
                if token:
                    self._set_session_cookie(token)
                    suffix = "google_login=1"
                else:
                    suffix = "auth_challenge=" + urllib.parse.quote(str(out.get("challenge_id") or ""))
            else:
                account_auth.link_google_identity(
                    identity["user_id"],
                    google_sub=identity["google_sub"],
                    google_email=identity.get("google_email") or "",
                    google_name=identity.get("google_name") or "",
                    source="google_oauth",
                )
                suffix = "google_linked=1"
            self._html_redirect(path + ("&" if "?" in path else "?") + suffix)
        except (google_auth.GoogleAuthError, account_auth.AccountAuthError) as exc:
            self._html_redirect("/ui/?google_error=" + urllib.parse.quote(str(exc)[:180]))

    def _html_redirect(self, location: str) -> None:
        self.send_response(HTTPStatus.FOUND)
        self.send_header("Location", location)
        self.end_headers()

    def _respond_tts(self, result: Dict[str, Any]) -> None:
        """Send OpenAI MP3 bytes or a quiet browser-fallback JSON payload."""
        headers = ai_agent_tts.speak_result_headers(result)
        if result.get("fallback") == "browser":
            self._json(HTTPStatus.OK, {
                "ok": True,
                "fallback": "browser",
                "reason": result.get("reason") or "unavailable",
                "agent_id": result.get("agent_id"),
                "voice": result.get("voice"),
                "voice_gender": result.get("voice_gender") or "neutral",
                "language": result.get("language") or "ru-RU",
                "speed": result.get("speed") or 1.0,
                "fallback_voice": result.get("fallback_voice") or "ru-RU",
                "hint_ru": result.get("hint_ru") or "",
            }, headers=headers)
            return
        audio = result.get("audio") or b""
        if not isinstance(audio, (bytes, bytearray)) or not audio:
            raise ai_agent_tts.AgentTtsError("Пустой аудиоответ TTS.")
        self._bytes(
            HTTPStatus.OK,
            bytes(audio),
            str(result.get("content_type") or "audio/mpeg"),
            headers=headers,
        )

    def _require_owner_actor(self) -> Optional[Dict[str, Any]]:
        context = getattr(self, "_remote_context", None) or {}
        if not context.get("is_owner"):
            self._err(HTTPStatus.FORBIDDEN, "Только владелец.")
            return None
        return context

    def _test_create_virtual_user(self) -> None:
        if not self._require_owner_actor():
            return
        body = self._read_body() or {}
        try:
            out = test_auth.create_virtual_user(
                preset=str(body.get("preset") or "demo"),
                display_name=str(body.get("display_name") or ""),
                telegram_id=int(body.get("telegram_id") or 0),
                google_email=str(body.get("google_email") or ""),
            )
            self._json(HTTPStatus.OK, out)
        except (runtime_env.RuntimeEnvError, test_auth.TestAuthError, account_auth.AccountAuthError) as exc:
            self._err(getattr(exc, "status", 400), str(exc))

    def _test_login_virtual(self) -> None:
        if not self._require_owner_actor():
            return
        body = self._read_body() or {}
        tunnel_ip, forwarded_ip = self._request_ips()
        try:
            out = test_auth.login_virtual(
                user_id=int(body.get("user_id") or 0),
                ip=forwarded_ip or tunnel_ip,
                user_agent=str(self.headers.get("User-Agent") or "staging-test-auth"),
            )
            token = str(out.pop("session_token", ""))
            if token:
                self._set_session_cookie(token)
            self._json(HTTPStatus.OK, out)
        except (runtime_env.RuntimeEnvError, test_auth.TestAuthError, account_auth.AccountAuthError) as exc:
            self._err(getattr(exc, "status", 400), str(exc))

    def _test_google_link(self) -> None:
        context = getattr(self, "_remote_context", None) or {}
        body = self._read_body() or {}
        uid = int(body.get("user_id") or context.get("user_id") or 0)
        if not context.get("is_owner") and uid != int(context.get("user_id") or 0):
            self._err(HTTPStatus.FORBIDDEN, "Нельзя привязать Google другому пользователю."); return
        try:
            out = test_auth.link_fake_google(
                user_id=uid,
                google_sub=str(body.get("google_sub") or ""),
                email=str(body.get("email") or ""),
            )
            self._json(HTTPStatus.OK, out)
        except (runtime_env.RuntimeEnvError, test_auth.TestAuthError, account_auth.AccountAuthError, google_auth.GoogleAuthError) as exc:
            self._err(getattr(exc, "status", 400), str(exc))

    def _owner_impersonate(self) -> None:
        context = self._require_owner_actor()
        if not context:
            return
        body = self._read_body() or {}
        tunnel_ip, forwarded_ip = self._request_ips()
        try:
            out = account_auth.start_impersonation(
                context.get("user_id"),
                body.get("user_id"),
                ip=forwarded_ip or tunnel_ip,
                user_agent=str(self.headers.get("User-Agent") or "owner-impersonation"),
                preset=str(body.get("preset") or ""),
            )
            token = str(out.pop("session_token", ""))
            if token:
                self._set_session_cookie(token)
            self._json(HTTPStatus.OK, out)
        except (runtime_env.RuntimeEnvError, account_auth.AccountAuthError) as exc:
            self._err(getattr(exc, "status", 400), str(exc))

    def _owner_impersonate_end(self) -> None:
        context = getattr(self, "_remote_context", None) or {}
        owner_id = context.get("impersonator_owner_id") or context.get("user_id")
        if not owner_id:
            self._err(HTTPStatus.FORBIDDEN, "Нет активной impersonation-сессии."); return
        tunnel_ip, forwarded_ip = self._request_ips()
        try:
            out = account_auth.end_impersonation(
                self._cookie_value(runtime_env.session_cookie_name()),
                owner_id=owner_id,
                ip=forwarded_ip or tunnel_ip,
                user_agent=str(self.headers.get("User-Agent") or "owner-return"),
            )
            token = str(out.pop("session_token", ""))
            if token:
                self._set_session_cookie(token)
            self._json(HTTPStatus.OK, out)
        except (runtime_env.RuntimeEnvError, account_auth.AccountAuthError) as exc:
            self._err(getattr(exc, "status", 400), str(exc))

    def _owner_agent_team_grant(self) -> None:
        """Owner grants/revokes the full agent team capability for a user."""
        context = self._require_owner_actor()
        if not context:
            return
        body = self._read_body() or {}
        try:
            uid = int(body.get("user_id") or 0)
        except (TypeError, ValueError):
            uid = 0
        if uid <= 0:
            self._err(HTTPStatus.BAD_REQUEST, "user_id обязателен."); return
        capability = str(body.get("capability") or agent_allocation.TEAM_FULL_CAPABILITY)
        action = str(body.get("action") or "grant").strip().lower()
        try:
            if action == "revoke":
                out = agent_allocation.revoke_team_capability(uid, capability)
            else:
                out = agent_allocation.grant_team_capability(
                    uid, capability, granted_by=context.get("user_id"))
            self._json(HTTPStatus.OK, out)
        except ValueError as exc:
            self._err(HTTPStatus.BAD_REQUEST, str(exc))

    def _owner_google_secrets(self) -> None:
        if not self._require_owner_actor():
            return
        body = self._read_body() or {}
        try:
            out = google_auth.save_secrets(
                client_id=str(body.get("client_id") or ""),
                client_secret=str(body.get("client_secret") or ""),
                redirect_uri=str(body.get("redirect_uri") or ""),
            )
            self._json(HTTPStatus.OK, out)
        except google_auth.GoogleAuthError as exc:
            self._err(exc.status, str(exc))

    def _serve_avatar(self, target: str) -> None:
        context = getattr(self, "_remote_context", None) or {}
        try:
            target_id = int(target)
        except (TypeError, ValueError):
            self._err(HTTPStatus.NOT_FOUND, "avatar not found"); return
        requester = int(context.get("user_id") or 0)
        if not context.get("is_owner") and requester != target_id:
            self._err(HTTPStatus.FORBIDDEN, "Доступ к аватару запрещён."); return
        path = account_auth.avatar_file(target_id)
        if not path:
            self._err(HTTPStatus.NOT_FOUND, "avatar not found"); return
        try:
            blob = path.read_bytes()
        except OSError:
            self._err(HTTPStatus.NOT_FOUND, "avatar not found"); return
        ext = path.suffix.lstrip(".").lower()
        ctype = "image/png" if ext == "png" else "image/webp" if ext == "webp" else "image/jpeg"
        # avatar_url carries ?v=<avatar_updated_at_utc>, so a given URL always
        # names the same bytes and a new avatar produces a new URL. Private,
        # because the handler above authorised this requester for this avatar.
        self._bytes(HTTPStatus.OK, blob, ctype,
                    headers={"Cache-Control": "private, max-age=86400, immutable"})

    def _refresh_avatar(self) -> None:
        context = getattr(self, "_remote_context", None) or {}
        out = account_auth.refresh_avatar(context.get("user_id"), fetcher=telegram_service.fetch_user_avatar)
        self._json(HTTPStatus.OK, out)

    def _paypal_audit(self, event: Dict[str, Any], result: Dict[str, Any], verified: bool) -> None:
        try:
            path = runtime_env.data_path(
                "audit", "paypal-webhook.jsonl", project_root=_PROJECT_ROOT,
            )
            path.parent.mkdir(parents=True, exist_ok=True)
            row = {
                "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
                "event_type": str(event.get("event_type") or ""),
                "event_id": str(event.get("id") or ""),
                "verified": bool(verified),
                "result": result,
            }
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
        except OSError:
            pass

    def _paypal_webhook(self) -> None:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except (TypeError, ValueError):
            length = 0
        raw = self.rfile.read(length) if 0 < length <= 1_000_000 else b""
        try:
            event = json.loads(raw.decode("utf-8")) if raw else {}
        except ValueError:
            event = {}
        if not isinstance(event, dict) or not event.get("event_type"):
            # Return 200 so PayPal does not retry obviously-empty deliveries.
            self._json(HTTPStatus.OK, {"ok": False, "reason": "empty_event"})
            return
        headers = {str(key).lower(): str(value) for key, value in self.headers.items()}
        try:
            verified = paypal.verify_webhook(headers, event)
        except paypal.PayPalError:
            verified = False
        if not verified:
            self._paypal_audit(event, {"ok": False, "reason": "unverified"}, False)
            self._err(HTTPStatus.BAD_REQUEST, "PayPal webhook signature not verified.")
            return
        try:
            result = paypal.process_event(event)
        except Exception as exc:  # pragma: no cover - defensive
            result = {"ok": False, "error": str(exc)[:200]}
        self._paypal_audit(event, result, True)
        self._json(HTTPStatus.OK, result)

    def _notify_owner_payment_request(self, context: Dict[str, Any], request: Dict[str, Any]) -> None:
        try:
            if not request:
                return
            user = (context or {}).get("user") or {}
            name = " ".join([str(user.get("first_name") or ""), str(user.get("last_name") or "")]).strip() \
                or str(user.get("username") or context.get("user_id") or "")
            plan_id = str(request.get("plan_id") or "")
            plan = subscriptions.PLANS.get(plan_id) or {}
            lines = [
                f"Пользователь {name} (ID {context.get('user_id')}) сообщает об оплате.",
                f"Тариф: {plan.get('label') or plan_id} · ${request.get('amount_usd')}",
                "Проверьте платёж в PayPal и включите тариф: Кабинет → Заявки.",
            ]
            telegram_service.send_chief_report("💳 Заявка на оплату", lines, urgent=True)
        except Exception:  # pragma: no cover - notification is best-effort
            pass

    def _miniapp_register(self) -> None:
        if not self._check_public_auth_origin():
            return
        body = self._read_body()
        if body is None:
            return
        init_data = str(self.headers.get(telegram_remote.INIT_DATA_HEADER) or body.get("init_data") or "")
        try:
            verified = telegram_remote.validate_init_data(
                init_data, str(os.environ.get(telegram_service.TOKEN_ENV) or ""))
        except telegram_remote.RemoteAccessError as exc:
            self._err(getattr(exc, "status", 401), str(exc)); return
        owner_id = str(os.environ.get(telegram_service.CHAT_ENV) or "").strip()
        try:
            account_auth.ensure_owner(owner_id)
        except account_auth.AccountAuthError:
            pass
        try:
            out = account_auth.register_via_telegram(
                verified["user"],
                email=str(body.get("email") or ""),
                first_name=str(body.get("first_name") or ""),
                last_name=str(body.get("last_name") or ""),
                accept_terms=bool(body.get("accept_terms")),
                api_call=telegram_service._api_call, owner_chat_id=owner_id,
            )
            # New accounts return pending_owner until the owner confirms.
            self._json(HTTPStatus.OK, {
                "ok": True,
                "authenticated": bool(out.get("authenticated")),
                "status": str(out.get("status") or ""),
                "challenge_id": str(out.get("challenge_id") or ""),
                "user": out.get("user") or {},
            })
        except account_auth.AccountAuthError as exc:
            self._err(exc.status, str(exc))

    def _auth_public_post(self, path: str) -> None:
        if not self._check_public_auth_origin():
            return
        body = self._read_body()
        if body is None:
            return
        owner_id = str(os.environ.get(telegram_service.CHAT_ENV) or "").strip()
        tunnel_ip, forwarded_ip = self._request_ips()
        ip = forwarded_ip or tunnel_ip
        try:
            account_auth.ensure_owner(owner_id)
            if path == "/api/auth/login/start":
                out = account_auth.start_login(
                    bot_username=telegram_service.bot_username(),
                    ip=ip, user_agent=str(self.headers.get("User-Agent") or ""),
                )
            elif path == "/api/auth/login/status":
                out = account_auth.create_session_for_challenge(
                    str(body.get("challenge_id") or ""), ip=ip,
                    user_agent=str(self.headers.get("User-Agent") or ""),
                    device_credential=self._device_credential(),
                )
                if out.get("status") == "authenticated":
                    self._set_session_cookie(str(out.pop("session_token")))
            elif path == "/api/auth/profile":
                out = account_auth.complete_profile(
                    str(body.get("challenge_id") or ""), body.get("profile") or body,
                    api_call=telegram_service._api_call, owner_chat_id=owner_id,
                    ip=ip, user_agent=str(self.headers.get("User-Agent") or ""),
                )
            elif path == "/api/auth/google/login/start":
                out = google_auth.start_login(
                    redirect_uri=self._google_redirect_uri(body),
                    return_path=str(body.get("return_path") or "/ui/"),
                    accept_terms=bool(body.get("accept_terms")),
                )
            elif path == "/api/auth/email/start":
                out = account_auth.start_email_auth(
                    body.get("email"), ip=ip,
                    user_agent=str(self.headers.get("User-Agent") or ""),
                    purpose="login",
                )
            elif path == "/api/auth/email/verify":
                out = account_auth.verify_email_auth(
                    body.get("challenge_id"), code=body.get("code"),
                    device_credential=self._device_credential(),
                    magic_token=body.get("magic_token"),
                    profile=body.get("profile") or body,
                    ip=ip, user_agent=str(self.headers.get("User-Agent") or ""),
                    api_call=telegram_service._api_call, owner_chat_id=owner_id,
                )
                if out.get("status") == "authenticated":
                    self._set_session_cookie(str(out.pop("session_token")))
            elif path == "/api/auth/test/google-login":
                runtime_env.require_test_auth()
                identity = google_auth.fake_identity(
                    google_sub=str(body.get("google_sub") or ""),
                    email=str(body.get("email") or ""),
                )
                out = account_auth.login_via_google_identity(
                    device_credential=self._device_credential(),
                    google_sub=identity["google_sub"],
                    google_email=identity["google_email"],
                    google_name=str(body.get("google_name") or identity.get("google_name") or ""),
                    email_verified=True,
                    accept_terms=bool(body.get("accept_terms")),
                    ip=ip, user_agent=str(self.headers.get("User-Agent") or ""),
                    api_call=telegram_service._api_call, owner_chat_id=owner_id,
                )
                if out.get("status") == "authenticated":
                    self._set_session_cookie(str(out.pop("session_token")))
            else:
                self._err(HTTPStatus.NOT_FOUND, f"no auth route: {path}"); return
            self._json(HTTPStatus.OK, out)
        except (account_auth.AccountAuthError, google_auth.GoogleAuthError,
                runtime_env.RuntimeEnvError) as exc:
            self._err(getattr(exc, "status", 400), str(exc), code=getattr(exc, "code", "") or "")

    def _account_security_post(self, path: str) -> None:
        """Self-service trusted-device and step-up mutations (Phase 4).

        Every action is authenticated (session/CSRF), scoped to the caller's own
        account by ``user_id`` and re-checks device ownership server-side. Hiding
        a button is never the authorization boundary.
        """
        routes = {
            "/api/account/security/challenge",
            "/api/account/security/challenge/confirm",
            "/api/account/devices/approve",
            "/api/account/devices/reject",
            "/api/account/devices/revoke",
            # Machine level. Separate routes from the client ones on purpose:
            # revoking a machine cascades to every client on it, and that must
            # never be reachable by an extra flag on the client route.
            "/api/account/machines/revoke",
            "/api/account/machines/pair",
            "/api/account/machines/pair/redeem",
            "/api/account/sessions/revoke",
        }
        if path not in routes:
            self._err(HTTPStatus.NOT_FOUND, "no account route", code="account_route_not_found")
            return
        if not self._check_local_post():
            return
        body = self._read_body()
        if body is None:
            return
        if not isinstance(body, dict):
            self._err(HTTPStatus.BAD_REQUEST, "Тело запроса должно быть объектом.", code="invalid_body")
            return
        context = getattr(self, "_remote_context", None) or {}
        user_id = context.get("user_id")
        tunnel_ip, forwarded_ip = self._request_ips()
        ip = forwarded_ip or tunnel_ip
        try:
            if path == "/api/account/security/challenge":
                out = security_devices.create_challenge(
                    user_id=user_id,
                    purpose=str(body.get("purpose") or ""),
                    device_id=str(body.get("device_id") or ""),
                    provider=str(body.get("provider") or ""),
                    ip=ip,
                    user_agent=str(self.headers.get("User-Agent") or ""),
                )
            elif path == "/api/account/security/challenge/confirm":
                out = security_devices.confirm_challenge(
                    user_id=user_id,
                    challenge_id=str(body.get("challenge_id") or ""),
                    code=str(body.get("code") or ""),
                    ip=ip,
                )
            elif path == "/api/account/devices/approve":
                out = security_devices.approve_device(
                    user_id=user_id,
                    device_id=str(body.get("device_id") or ""),
                    challenge_id=str(body.get("challenge_id") or ""),
                    code=str(body.get("code") or ""),
                    ip=ip,
                )
            elif path == "/api/account/devices/reject":
                out = security_devices.reject_device(
                    user_id=user_id,
                    device_id=str(body.get("device_id") or ""),
                    ip=ip,
                )
            elif path == "/api/account/devices/revoke":
                out = security_devices.revoke_device(
                    user_id=user_id,
                    device_id=str(body.get("device_id") or ""),
                    ip=ip,
                )
            elif path == "/api/account/machines/revoke":
                out = security_devices.revoke_physical_device(
                    user_id=user_id,
                    physical_device_id=str(body.get("physical_device_id") or ""),
                    ip=ip,
                )
            elif path == "/api/account/machines/pair":
                out = security_devices.issue_pairing_code(
                    user_id=user_id,
                    device_id=str(body.get("device_id") or ""),
                    ip=ip,
                )
            elif path == "/api/account/machines/pair/redeem":
                out = security_devices.redeem_pairing_code(
                    user_id=user_id,
                    device_id=str(body.get("device_id") or ""),
                    code=str(body.get("code") or ""),
                    ip=ip,
                )
            else:
                # Ending one of your own sessions. The subject is the
                # authenticated caller, so a session id alone cannot reach
                # somebody else's login.
                try:
                    out = account_auth.revoke_own_session(
                        user_id, str(body.get("session_id") or ""),
                    )
                except account_auth.AccountAuthError as exc:
                    self._err(exc.status, str(exc), code="session_revoke_failed")
                    return
            self._json(HTTPStatus.OK, out)
        except security_devices.SecurityDeviceError as exc:
            self._err(exc.status, str(exc), code=exc.code)

    def _environment_heartbeat_post(self) -> None:
        """Accept one environment's self-reported runtime identity.

        The caller is another environment's server process. It authenticates
        with the shared registry token in a header — never a session cookie,
        never a token in the URL — and the payload is re-validated here rather
        than trusted because it arrived authenticated: the token says who sent
        it, not that what they sent is well formed.

        A wrong or missing token gets one generic 401 with no hint about which
        it was, and nothing about the token reaches the response or the log.
        """
        if not self._check_json_content_type():
            return
        raw = self._read_raw_body()
        if raw is None:
            return
        try:
            body = json.loads(raw.decode("utf-8"))
            if not isinstance(body, dict):
                raise ValueError("body must be an object")
        except Exception:
            # Unparseable bodies are refused before any key is touched, so a
            # malformed request cannot be used to probe signature behaviour.
            self._err(HTTPStatus.BAD_REQUEST, "invalid json", code="invalid_body")
            return

        try:
            verified = environment_registry.verify_publisher(
                body=raw,
                timestamp=self.headers.get(environment_registry.TIMESTAMP_HEADER),
                signature=self.headers.get(environment_registry.SIGNATURE_HEADER),
                claimed_environment=body.get("environment"),
                nonce=body.get("nonce"),
            )
        except environment_registry.EnvironmentRegistryError as exc:
            # Every authentication failure -- bad signature, stale timestamp,
            # replayed nonce, an environment signing as another -- collapses to
            # the same 401 with the same text. The specific reason is recorded
            # server-side and never told to the caller, so a prober cannot use
            # the response to work out which part it got wrong.
            if exc.status == HTTPStatus.UNAUTHORIZED:
                observability.event(
                    "environment_registry", "publish_rejected",
                    severity="warning",
                    payload={
                        "reason": exc.code,
                        # What it claimed to be, which is not what it was.
                        "claimed": str(body.get("environment") or "")[:32],
                    },
                )
                self._err(
                    HTTPStatus.UNAUTHORIZED, "Не авторизовано.",
                    code="registry_unauthorized",
                )
            else:
                self._err(exc.status, str(exc), code=exc.code)
            return

        try:
            row = environment_registry.record(body, verified_environment=verified)
        except environment_registry.EnvironmentRegistryError as exc:
            self._err(exc.status, str(exc), code=exc.code)
            return
        self._json(HTTPStatus.OK, {"ok": True, "environment": row})

    def _personal_nt_error(self, exc: "personal_nt_security.PersonalNtSecurityError") -> None:
        payload: Dict[str, Any] = {"error": str(exc), "code": exc.code}
        if exc.onboarding is not None:
            payload["onboarding"] = exc.onboarding
        if exc.action:
            payload["action"] = exc.action
        self._json(exc.status, payload)

    def _personal_nt_gate(
        self, action: str, *, require_ready: bool, challenge_id: str = "",
    ) -> bool:
        """Enforce personal-NT factors and/or a single-use step-up grant.

        Writes the error response and returns False when the gate is not met,
        so critical NinjaTrader actions cannot proceed without a fresh, bound
        confirmation (owner is exempt inside the security module).
        """
        context = getattr(self, "_remote_context", None) or {}
        _, forwarded_ip = self._request_ips()
        try:
            if require_ready:
                personal_nt_security.require_ready_and_step_up(
                    context.get("user_id"), action=action,
                    challenge_id=challenge_id, ip=forwarded_ip,
                )
            else:
                personal_nt_security.require_step_up(
                    context.get("user_id"), action=action,
                    challenge_id=challenge_id, ip=forwarded_ip,
                )
            return True
        except personal_nt_security.PersonalNtSecurityError as exc:
            self._personal_nt_error(exc)
            return False

    def _personal_nt_require_ready(self) -> bool:
        """Require both personal-NT factors without consuming a step-up grant."""
        context = getattr(self, "_remote_context", None) or {}
        try:
            personal_nt_security.require_ready(context.get("user_id"))
            return True
        except personal_nt_security.PersonalNtSecurityError as exc:
            self._personal_nt_error(exc)
            return False

    def _ninjatrader_post(self, path: str) -> None:
        """Phase 6: shared/personal NinjaTrader job queue and durable lease.

        User-facing routes (jobs enqueue/cancel) are self-service and scoped to
        the caller's own workspace. Worker routes (claim/heartbeat/release/
        recover) are capability-gated at ``_authorize_api``; heartbeat/release
        additionally prove possession of the server-issued lease token.
        """
        if not self._check_local_post():
            return
        body = self._read_body()
        if body is None:
            return
        if not isinstance(body, dict):
            self._err(HTTPStatus.BAD_REQUEST, "Тело запроса должно быть объектом.", code="invalid_body")
            return
        context = getattr(self, "_remote_context", None) or {}
        user_id = context.get("user_id")
        is_owner = bool(context.get("is_owner"))
        admin_caps = context.get("admin_capabilities") if isinstance(context.get("admin_capabilities"), dict) else {}
        can_admin = bool(is_owner or admin_caps.get("operations.execute") or admin_caps.get("operations.view"))
        parts = [urllib.parse.unquote(p) for p in path.split("/") if p]
        try:
            if path == "/api/ninjatrader/jobs":
                out = ninjatrader_resources.enqueue_job(
                    user_id,
                    operation_kind=str(body.get("operation_kind") or ""),
                    idempotency_key=str(body.get("idempotency_key") or ""),
                    workspace_id=str(body.get("workspace_id") or ""),
                    parallel_group=str(body.get("parallel_group") or "exclusive"),
                    is_owner=is_owner,
                )
            elif len(parts) == 4 and parts[2] == "jobs" and path.endswith("/cancel"):
                out = ninjatrader_resources.cancel_job(
                    user_id, job_id=parts[3], is_owner=is_owner, can_admin=can_admin,
                )
            elif path == "/api/ninjatrader/worker/claim":
                out = ninjatrader_resources.claim_next(str(body.get("resource_id") or ""))
            elif path == "/api/ninjatrader/worker/heartbeat":
                out = ninjatrader_resources.heartbeat(
                    str(body.get("job_id") or ""), lease_token=str(body.get("lease_token") or ""),
                )
            elif path == "/api/ninjatrader/worker/release":
                out = ninjatrader_resources.release(
                    str(body.get("job_id") or ""), lease_token=str(body.get("lease_token") or ""),
                    outcome=str(body.get("outcome") or "released"),
                )
            elif path == "/api/ninjatrader/worker/recover":
                out = ninjatrader_resources.recover_expired(str(body.get("resource_id") or ""))
            else:
                self._err(HTTPStatus.NOT_FOUND, "no ninjatrader route", code="nt_route_not_found")
                return
            self._json(HTTPStatus.OK, out)
        except ninjatrader_resources.NinjaTraderResourceError as exc:
            self._err(exc.status, str(exc), code=exc.code)
        except workspaces.WorkspaceError as exc:
            self._err(exc.status, str(exc), code=getattr(exc, "code", "") or "")

    def _dev_bootstrap_redeem(self, qs: Dict[str, Any]) -> None:
        """Public Development-only redeem: single-use loopback bootstrap link."""
        tunnel_ip, forwarded_ip = self._request_ips()
        client_ip = str(forwarded_ip or tunnel_ip or "")
        is_loopback = self._is_loopback_ip(client_ip) and not self._is_remote_api_request()
        token = str((qs.get("token") or [""])[0] or "")
        try:
            out = dev_preview.redeem_bootstrap_token(
                token, is_loopback=is_loopback, ip=client_ip or "127.0.0.1",
                user_agent=str(self.headers.get("User-Agent") or "dev-bootstrap"),
            )
        except dev_preview.DevPreviewError as exc:
            self._err(exc.status, str(exc), code=exc.code)
            return
        self._set_session_cookie(str(out.get("session_token") or ""))
        # Redirect to the app without leaving the token in the address bar.
        self.send_response(HTTPStatus.SEE_OTHER)
        for name, value in self._extra_headers:
            self.send_header(name, value)
        self.send_header("Location", "/ui/")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def _dev_preview_return(self) -> None:
        """Public Development-only, loopback-only return to the owner session."""
        tunnel_ip, forwarded_ip = self._request_ips()
        client_ip = str(forwarded_ip or tunnel_ip or "")
        is_loopback = self._is_loopback_ip(client_ip) and not self._is_remote_api_request()
        if not is_loopback:
            self._err(HTTPStatus.FORBIDDEN, "loopback required", code="loopback_required")
            return
        try:
            out = dev_preview.return_to_developer(
                ip=client_ip or "127.0.0.1",
                user_agent=str(self.headers.get("User-Agent") or "dev-return"),
            )
        except dev_preview.DevPreviewError as exc:
            self._err(exc.status, str(exc), code=exc.code)
            return
        self._set_session_cookie(str(out.get("session_token") or ""))
        self._clear_dev_preview_mode_cookie()
        self.send_response(HTTPStatus.SEE_OTHER)
        for name, value in self._extra_headers:
            self.send_header(name, value)
        self.send_header("Location", "/ui/")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def _dev_service_login(self) -> None:
        """Localhost-only Claude/GPT service login (Development only).

        Never available in Canary/Production (``dev_service_accounts.available``)
        and only from a loopback client. ``actor='owner'`` (or empty) clears the
        service session to return to the human owner.
        """
        if not self._check_local_post():
            return
        if not dev_service_accounts.available():
            self._err(HTTPStatus.FORBIDDEN, "Служебный вход доступен только в Development.",
                      code="dev_only")
            return
        tunnel_ip, forwarded_ip = self._request_ips()
        client_ip = str(forwarded_ip or tunnel_ip or "")
        is_loopback = self._is_loopback_ip(client_ip) and not self._is_remote_api_request()
        if not is_loopback:
            self._err(HTTPStatus.FORBIDDEN, "Служебный вход возможен только с localhost.",
                      code="loopback_required")
            return
        body = self._read_body()
        if body is None:
            return
        if not isinstance(body, dict):
            self._err(HTTPStatus.BAD_REQUEST, "Тело запроса должно быть объектом.", code="invalid_body")
            return
        actor = str(body.get("actor") or "").strip().lower()
        if actor in {"", "owner"}:
            self._clear_session_cookie()
            self._json(HTTPStatus.OK, {"ok": True, "actor": "owner"})
            return
        try:
            out = dev_service_accounts.login(
                actor, is_loopback=is_loopback, ip=client_ip or "127.0.0.1",
                user_agent=str(self.headers.get("User-Agent") or "dev-service"))
        except dev_service_accounts.DevServiceError as exc:
            self._err(exc.status, str(exc), code=exc.code)
            return
        token = str(out.pop("session_token", ""))
        if token:
            self._set_session_cookie(token)
        self._json(HTTPStatus.OK, out)

    def _dev_preview_post(self, path: str) -> None:
        """Developer-only View-As and bootstrap-mint (Development, owner-gated)."""
        if not self._check_local_post():
            return
        body = self._read_body()
        if body is None:
            return
        if not isinstance(body, dict):
            self._err(HTTPStatus.BAD_REQUEST, "Тело запроса должно быть объектом.", code="invalid_body")
            return
        context = getattr(self, "_remote_context", None) or {}
        user_id = context.get("user_id")
        tunnel_ip, forwarded_ip = self._request_ips()
        ip = str(forwarded_ip or tunnel_ip or "127.0.0.1")
        try:
            if path == "/api/dev/preview/view-as":
                out = dev_preview.start_view_as(
                    user_id, str(body.get("persona") or ""), ip=ip,
                    user_agent=str(self.headers.get("User-Agent") or "dev-preview"),
                )
                if out.get("clear_session"):
                    self._clear_session_cookie()
                    self._set_dev_preview_mode_cookie("unauthenticated")
                elif out.get("session_token"):
                    self._clear_dev_preview_mode_cookie()
                    self._set_session_cookie(str(out.get("session_token")))
                    out.pop("session_token", None)
            elif path == "/api/dev/preview/exit":
                out = dev_preview.exit_view_as(
                    user_id, self._cookie_value(runtime_env.session_cookie_name()), ip=ip,
                    user_agent=str(self.headers.get("User-Agent") or "dev-return"),
                )
                if out.get("session_token"):
                    self._clear_dev_preview_mode_cookie()
                    self._set_session_cookie(str(out.get("session_token")))
                    out.pop("session_token", None)
            elif path == "/api/dev/preview/reset-personas":
                out = dev_preview.reset_personas()
            elif path == "/api/dev/bootstrap/mint":
                out = dev_preview.mint_bootstrap_token(
                    user_id, origin=self._self_origin(),
                )
            else:
                self._err(HTTPStatus.NOT_FOUND, "no dev preview route", code="dev_route_not_found")
                return
            self._json(HTTPStatus.OK, out)
        except dev_preview.DevPreviewError as exc:
            self._err(exc.status, str(exc), code=exc.code)

    # ---- Release Center (Phase 8) -------------------------------------------
    def _release_context(self) -> Dict[str, Any]:
        context = getattr(self, "_remote_context", None) or {}
        caps = context.get("admin_capabilities")
        if not isinstance(caps, dict):
            caps = permissions.resolve_admin_capabilities(context.get("user") or {})
            context = {**context, "admin_capabilities": caps}
        return context

    def _require_release_capability(self, context: Dict[str, Any], capability: str) -> bool:
        if context.get("is_owner"):
            return True
        caps = context.get("admin_capabilities") if isinstance(context.get("admin_capabilities"), dict) else {}
        if caps.get(capability):
            return True
        self._err(HTTPStatus.FORBIDDEN, "Недостаточно прав для этого действия Release Center.",
                  code="release_capability_required")
        return False

    def _releases_get(self, path: str) -> None:
        try:
            if path == "/api/admin/releases":
                self._json(HTTPStatus.OK, release_center.list_releases())
                return
            prefix = "/api/admin/releases/"
            if path.startswith(prefix):
                candidate_id = path[len(prefix):].strip("/")
                self._json(HTTPStatus.OK, release_center.get_release(candidate_id))
                return
            self._err(HTTPStatus.NOT_FOUND, "no release route", code="release_route_not_found")
        except release_center.ReleaseCenterError as exc:
            self._err(exc.status, str(exc), code=exc.code)

    def _releases_post(self, path: str) -> None:
        if not self._check_local_post():
            return
        body = self._read_body()
        if body is None:
            return
        if not isinstance(body, dict):
            self._err(HTTPStatus.BAD_REQUEST, "Тело запроса должно быть объектом.", code="invalid_body")
            return
        context = self._release_context()
        actor = {"user_id": context.get("user_id"), "is_owner": bool(context.get("is_owner"))}
        parts = path[len("/api/admin/releases"):].strip("/").split("/")
        try:
            if path == "/api/admin/releases/candidates":
                if not self._require_release_capability(context, "releases.create"):
                    return
                self._json(HTTPStatus.OK, release_center.create_candidate(
                    actor=actor,
                    app_version=str(body.get("app_version") or ""),
                    release_channel=str(body.get("release_channel") or ""),
                    git_commit_sha=str(body.get("git_commit_sha") or ""),
                    idempotency_key=str(body.get("idempotency_key") or ""),
                ))
                return
            # /api/admin/releases/{id}/{action}
            if len(parts) != 2:
                self._err(HTTPStatus.NOT_FOUND, "no release route", code="release_route_not_found")
                return
            candidate_id, action = parts[0], parts[1]
            self._release_action(context, actor, candidate_id, action, body)
        except release_center.ReleaseCenterError as exc:
            self._err(exc.status, str(exc), code=exc.code)

    def _release_action(self, context, actor, candidate_id, action, body) -> None:
        idem = str(body.get("idempotency_key") or "")
        challenge = str(body.get("step_up_challenge_id") or "")
        if action == "build":
            if not self._require_release_capability(context, "releases.create"):
                return
            self._json(HTTPStatus.OK, release_center.build_release(
                actor=actor, candidate_id=candidate_id, idempotency_key=idem))
        elif action == "verify":
            if not self._require_release_capability(context, "releases.create"):
                return
            self._json(HTTPStatus.OK, release_center.verify_release(
                actor=actor, candidate_id=candidate_id, idempotency_key=idem))
        elif action == "deploy-canary":
            if not self._require_release_capability(context, "releases.deploy_canary"):
                return
            self._json(HTTPStatus.OK, release_center.deploy_canary(
                actor=actor, candidate_id=candidate_id, idempotency_key=idem,
                step_up_challenge_id=challenge))
        elif action == "record-canary-check":
            if not self._require_release_capability(context, "releases.deploy_canary"):
                return
            self._json(HTTPStatus.OK, release_center.record_canary_check(
                actor=actor, candidate_id=candidate_id,
                name=str(body.get("name") or ""), result=str(body.get("result") or ""),
                evidence=body.get("evidence") if isinstance(body.get("evidence"), dict) else None,
                final=bool(body.get("final")), idempotency_key=idem))
        elif action == "approve-production":
            if not self._require_release_capability(context, "releases.promote_production"):
                return
            self._json(HTTPStatus.OK, release_center.approve_production(
                actor=actor, candidate_id=candidate_id, idempotency_key=idem,
                step_up_challenge_id=challenge))
        elif action == "schedule-production":
            if not self._require_release_capability(context, "releases.promote_production"):
                return
            self._json(HTTPStatus.OK, release_center.schedule_production(
                actor=actor, candidate_id=candidate_id,
                mode=str(body.get("mode") or "now"), explicit_utc=str(body.get("explicit_utc") or ""),
                idempotency_key=idem))
        elif action == "promote-production":
            if not self._require_release_capability(context, "releases.promote_production"):
                return
            self._json(HTTPStatus.OK, release_center.promote_production(
                actor=actor, candidate_id=candidate_id, idempotency_key=idem,
                step_up_challenge_id=challenge))
        elif action == "mark-production-live":
            if not self._require_release_capability(context, "releases.promote_production"):
                return
            self._json(HTTPStatus.OK, release_center.mark_production_live(
                actor=actor, candidate_id=candidate_id, idempotency_key=idem))
        elif action == "rollback-production":
            if not self._require_release_capability(context, "releases.rollback_production"):
                return
            self._json(HTTPStatus.OK, release_center.rollback_production(
                actor=actor, candidate_id=candidate_id,
                to_artifact_id=str(body.get("to_artifact_id") or ""),
                reason=str(body.get("reason") or ""), idempotency_key=idem,
                step_up_challenge_id=challenge))
        elif action == "rehearse-bluegreen":
            if not self._require_release_capability(context, "releases.deploy_canary"):
                return
            self._json(HTTPStatus.OK, release_center.rehearse_blue_green(
                actor=actor, candidate_id=candidate_id,
                environment=str(body.get("environment") or "production"),
                drain=body.get("drain") if isinstance(body.get("drain"), dict) else None,
                idempotency_key=idem))
        elif action == "step-up":
            self._json(HTTPStatus.OK, release_center.begin_step_up(
                actor, action=str(body.get("action") or ""),
                provider=str(body.get("provider") or ""),
                ip=str(self._request_ips()[1] or self._request_ips()[0] or ""),
                user_agent=str(self.headers.get("User-Agent") or "release-center")))
        elif action == "cancel":
            if not self._require_release_capability(context, "releases.create"):
                return
            self._json(HTTPStatus.OK, release_center.cancel_release(
                actor=actor, candidate_id=candidate_id,
                reason=str(body.get("reason") or ""), idempotency_key=idem))
        else:
            self._err(HTTPStatus.NOT_FOUND, "no release action", code="release_action_not_found")

    # ---- Document specifications (Phase 11) ---------------------------------
    def _doc_context(self):
        context = self._release_context()
        actor = {"user_id": context.get("user_id"), "is_owner": bool(context.get("is_owner"))}
        caps = context.get("admin_capabilities") if isinstance(context.get("admin_capabilities"), dict) else {}
        ws = context.get("active_workspace") if isinstance(context.get("active_workspace"), dict) else {}
        workspace_id = str(context.get("workspace_id") or ws.get("workspace_id") or "")
        return actor, caps, workspace_id

    def _documents_get(self, path: str) -> None:
        actor, caps, aws = self._doc_context()
        try:
            if path == "/api/documents":
                qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                self._json(HTTPStatus.OK, doc_specs.list_documents(
                    actor=actor, admin_caps=caps, actor_workspace_id=aws,
                    scope_type=str(qs.get("scope_type", [""])[0] or ""),
                    workspace_id=str(qs.get("workspace_id", [""])[0] or "")))
                return
            prefix = "/api/documents/"
            if path.startswith(prefix):
                self._json(HTTPStatus.OK, doc_specs.get_document(
                    actor=actor, document_id=path[len(prefix):].strip("/"),
                    admin_caps=caps, actor_workspace_id=aws))
                return
            self._err(HTTPStatus.NOT_FOUND, "no document route", code="document_route_not_found")
        except doc_specs.DocSpecError as exc:
            self._err(exc.status, str(exc), code=exc.code)

    def _documents_post(self, path: str) -> None:
        if not self._check_local_post():
            return
        body = self._read_body()
        if body is None:
            return
        if not isinstance(body, dict):
            self._err(HTTPStatus.BAD_REQUEST, "Тело запроса должно быть объектом.", code="invalid_body")
            return
        actor, caps, aws = self._doc_context()
        kw = dict(admin_caps=caps, actor_workspace_id=aws)
        try:
            if path == "/api/documents":
                self._json(HTTPStatus.OK, doc_specs.create_document(
                    actor=actor, scope_type=str(body.get("scope_type") or ""),
                    slug=str(body.get("slug") or ""), title=str(body.get("title") or ""),
                    content=body.get("content"), workspace_id=str(body.get("workspace_id") or ""),
                    strategy_id=str(body.get("strategy_id") or ""), reason=str(body.get("reason") or ""), **kw))
                return
            parts = path[len("/api/documents/"):].strip("/").split("/")
            if len(parts) == 2 and parts[1] == "revisions":
                self._json(HTTPStatus.OK, doc_specs.create_revision(
                    actor=actor, document_id=parts[0], content=body.get("content"),
                    reason=str(body.get("reason") or ""), **kw))
                return
            if len(parts) == 2 and parts[1] == "revert":
                self._json(HTTPStatus.OK, doc_specs.revert_document(
                    actor=actor, document_id=parts[0], to_revision=int(body.get("to_revision") or 0),
                    reason=str(body.get("reason") or ""), **kw))
                return
            if len(parts) == 3 and parts[0] == "revisions":
                rid, act = parts[1], parts[2]
                if act == "submit":
                    self._json(HTTPStatus.OK, doc_specs.submit_revision(actor=actor, revision_id=rid, **kw)); return
                if act == "approve":
                    self._json(HTTPStatus.OK, doc_specs.approve_revision(actor=actor, revision_id=rid, **kw)); return
                if act == "publish":
                    self._json(HTTPStatus.OK, doc_specs.publish_revision(actor=actor, revision_id=rid, **kw)); return
            self._err(HTTPStatus.NOT_FOUND, "no document action", code="document_action_not_found")
        except doc_specs.DocSpecError as exc:
            self._err(exc.status, str(exc), code=exc.code)

    def _account_nt_security_post(self, path: str) -> None:
        """Self-service personal-NT security: step-up start/confirm, unlink."""
        if not self._check_local_post():
            return
        body = self._read_body()
        if body is None:
            return
        if not isinstance(body, dict):
            self._err(HTTPStatus.BAD_REQUEST, "Тело запроса должно быть объектом.", code="invalid_body")
            return
        context = getattr(self, "_remote_context", None) or {}
        user_id = context.get("user_id")
        _, forwarded_ip = self._request_ips()
        try:
            if path == "/api/account/nt-security/step-up/start":
                out = personal_nt_security.begin_step_up(
                    user_id, action=str(body.get("action") or ""),
                    provider=str(body.get("provider") or ""), ip=forwarded_ip,
                    user_agent=str(self.headers.get("User-Agent") or ""),
                )
            elif path == "/api/account/nt-security/step-up/confirm":
                out = security_devices.confirm_challenge(
                    user_id=user_id,
                    challenge_id=str(body.get("challenge_id") or ""),
                    code=str(body.get("code") or ""),
                    ip=forwarded_ip,
                )
                # A confirmed personal-NT step-up also refreshes this session's
                # NT elevation so the paired critical action clears the dual-auth
                # gate with a single confirmation.
                if out.get("purpose") == security_devices.PURPOSE_STEP_UP and context.get("session_id"):
                    try:
                        account_auth.elevate_session_for_nt(
                            str(context.get("session_id") or ""), user_id=user_id,
                        )
                    except account_auth.AccountAuthError:
                        pass
            elif path == "/api/account/identities/unlink":
                # Removing a login method is a critical action: require step-up.
                if not self._personal_nt_gate(
                    personal_nt_security.ACTION_UNLINK_METHOD, require_ready=False,
                    challenge_id=str(body.get("step_up_challenge_id") or ""),
                ):
                    return
                out = account_auth.unlink_identity_self(
                    user_id, identity_id=str(body.get("identity_id") or ""),
                )
            elif path == "/api/account/nt-security/step-up/staging":
                out = personal_nt_security.grant_step_up_staging(
                    user_id, action=str(body.get("action") or ""),
                )
            else:
                self._err(HTTPStatus.NOT_FOUND, "no account route", code="account_route_not_found")
                return
            self._json(HTTPStatus.OK, out)
        except personal_nt_security.PersonalNtSecurityError as exc:
            self._personal_nt_error(exc)
        except security_devices.SecurityDeviceError as exc:
            self._err(exc.status, str(exc), code=exc.code)
        except account_auth.AccountAuthError as exc:
            self._err(exc.status, str(exc), code=getattr(exc, "code", "") or "")
        except runtime_env.RuntimeEnvError as exc:
            self._err(getattr(exc, "status", 403), str(exc), code=getattr(exc, "code", "") or "")

    def _check_local_origin(self) -> bool:
        """Check Origin/Referer without requiring a Content-Type (used for DELETE)."""
        context = getattr(self, "_remote_context", None) or {}
        if context.get("source") == telegram_remote.SOURCE:
            return True
        if context.get("csrf_hash"):
            if not account_auth.verify_csrf(context, str(self.headers.get("X-CSRF-Token") or "")):
                self._err(HTTPStatus.FORBIDDEN, "CSRF token отсутствует или недействителен.")
                return False
            origin = self.headers.get("Origin")
            if not origin:
                self._err(HTTPStatus.FORBIDDEN, "Origin обязателен для изменения данных.")
                return False
            origin_host = self._request_hostname(origin)
            request_host = self._request_hostname(self.headers.get("X-Forwarded-Host") or self.headers.get("Host") or "")
            if not origin_host or not request_host or origin_host != request_host:
                self._err(HTTPStatus.FORBIDDEN, "Cross-origin запрос отклонён.")
                return False
            return True
        origin = self.headers.get("Origin") or self.headers.get("Referer")
        if not origin:
            return True  # non-browser client (CLI, Invoke-RestMethod)
        # A same-origin POST is never a cross-site (CSRF) request. Allow it when
        # the Origin host matches the host the request actually arrived on — this
        # covers the HTTPS Telegram Mini App tunnel (e.g. app.stratforges.com)
        # even when auth is disabled and the request is treated as local owner,
        # where the context source is "local" rather than the Mini App source.
        origin_host = self._request_hostname(origin)
        same_origin_hosts = {
            self._request_hostname(self.headers.get("X-Forwarded-Host") or ""),
            self._request_hostname(self.headers.get("Host") or ""),
        }
        if origin_host and origin_host in same_origin_hosts:
            return True
        try:
            u = urllib.parse.urlparse(origin)
        except Exception:
            self._err(HTTPStatus.FORBIDDEN, "bad Origin/Referer")
            return False
        if u.scheme != "http":
            self._err(HTTPStatus.FORBIDDEN, "non-http Origin/Referer rejected")
            return False
        if (u.hostname or "") not in _ALLOWED_ORIGIN_HOSTS:
            self._err(HTTPStatus.FORBIDDEN, f"Origin host not allowed: {u.hostname}")
            return False
        try:
            port = u.port or 80
        except ValueError:
            self._err(HTTPStatus.FORBIDDEN, "bad Origin port")
            return False
        bind_port = self.server.server_address[1]
        if port != bind_port:
            self._err(HTTPStatus.FORBIDDEN,
                      f"Origin port {port} != backend port {bind_port}")
            return False
        return True

    # ------------- static (UI bundle) -------------------------------------

    def _static_cache_control(self, target: Path) -> str:
        # Keep UI files fresh while still allowing the browser to reuse cached
        # responses via conditional requests and bfcache.
        if target.suffix.lower() == ".html":
            return "no-cache"
        return "public, max-age=120, must-revalidate"

    def _stamp_asset_refs(self, data: bytes) -> bytes:
        """Rewrite ``?v=`` on local asset references to this build's stamp.

        The stamps were hand-maintained per file and had drifted badly (nine
        different values across thirteen pages, the oldest from 20260629), so a
        release shipped new JS under a URL that had not changed since June. The
        CDN in front of the app caches those URLs for four hours, which is how
        a green deploy could still serve the previous bundle to browsers.

        Deriving the stamp from the build makes every release a new URL, which
        is what the long cache lifetime already assumes.
        """
        stamp = _asset_build_stamp()
        if not stamp:
            return data
        return _ASSET_REF_RE.sub(
            lambda m: m.group("head") + stamp.encode("ascii") + m.group("tail"),
            data,
        )

    def _not_modified(self, target: Path) -> bool:
        raw_ims = self.headers.get("If-Modified-Since")
        if not raw_ims:
            return False
        try:
            ims = parsedate_to_datetime(raw_ims)
        except (TypeError, ValueError, IndexError, OverflowError):
            return False
        if ims.tzinfo is None:
            ims = ims.replace(tzinfo=timezone.utc)
        try:
            mtime = target.stat().st_mtime
        except OSError:
            return False
        return int(ims.timestamp()) >= int(mtime)

    def _serve_static(self, rel: str) -> None:
        if not rel or rel == "/":
            rel = "index.html"
        rel = rel.lstrip("/")
        # Directory requests (e.g. "legacy/") serve the folder's index.html.
        if rel.endswith("/"):
            rel += "index.html"
        # Disallow path traversal: resolve and ensure inside STATIC_DIR.
        target = (STATIC_DIR / rel).resolve()
        try:
            target.relative_to(STATIC_DIR.resolve())
        except ValueError:
            self._err(HTTPStatus.FORBIDDEN, "path traversal blocked")
            return
        if not target.is_file():
            if target.suffix == "":
                html_target = target.with_suffix(".html")
                try:
                    html_target.relative_to(STATIC_DIR.resolve())
                except ValueError:
                    self._err(HTTPStatus.FORBIDDEN, "path traversal blocked")
                    return
                if html_target.is_file():
                    target = html_target
                    ct = CONTENT_TYPES.get(target.suffix.lower(), "application/octet-stream")
                    cache_control = self._static_cache_control(target)
                    last_modified = formatdate(target.stat().st_mtime, usegmt=True)
                else:
                    self._err(HTTPStatus.NOT_FOUND, f"static not found: {rel}")
                    return
            else:
                self._err(HTTPStatus.NOT_FOUND, f"static not found: {rel}")
                return
        ct = CONTENT_TYPES.get(target.suffix.lower(), "application/octet-stream")
        cache_control = self._static_cache_control(target)
        last_modified = formatdate(target.stat().st_mtime, usegmt=True)
        try:
            if self._not_modified(target):
                self.send_response(HTTPStatus.NOT_MODIFIED)
                self.send_header("Cache-Control", cache_control)
                self.send_header("Last-Modified", last_modified)
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Content-Security-Policy", STATIC_CSP)
                self.end_headers()
                return
            data = target.read_bytes()
            if target.suffix.lower() == ".html":
                data = self._stamp_asset_refs(data)
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", ct)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", cache_control)
            self.send_header("Last-Modified", last_modified)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", STATIC_CSP)
            self.end_headers()
            self.wfile.write(data)
        except OSError as e:
            if self._is_client_disconnect_error(e):
                return
            raise

    # ------------- routing -------------------------------------------------

    def send_response(self, code, message=None):  # type: ignore[override]
        # Track whether the response line has been emitted so the top-level
        # error guard knows if it can still send a clean 500 JSON body.
        self._response_started = True
        if getattr(self, "_remote_attempt", False) and not getattr(self, "_remote_audited", False):
            self._remote_audited = True
            tunnel_ip, forwarded_ip = self._request_ips()
            try:
                telegram_remote.audit(
                    method=self.command, path=urllib.parse.urlparse(self.path).path,
                    status=int(code), context=getattr(self, "_remote_context", None),
                    tunnel_ip=tunnel_ip, forwarded_ip=forwarded_ip,
                    error=str(getattr(self, "_remote_error", "") or ""),
                )
            except Exception:
                pass
        super().send_response(code, message)

    def end_headers(self):  # type: ignore[override]
        for name, value in getattr(self, "_extra_headers", []):
            self.send_header(name, value)
        self._extra_headers = []
        super().end_headers()

    def _handle_unexpected(self, method: str) -> None:
        """Turn an uncaught exception into a stable JSON response.

        Storage exhaustion is operationally actionable and has a dedicated
        507/code contract.  Other failures remain a generic 500 so internal
        exception details are never disclosed to the client.
        """
        exc = sys.exc_info()[1]
        tb = traceback.format_exc()
        try:
            sys.stderr.write(f"[NT-Analyzer] unhandled {method} error:\n{tb}")
        except Exception:
            pass
        if getattr(self, "_response_started", False):
            # Headers/body already (partially) sent — we can no longer emit a
            # well-formed error. Nothing safe left to do; connection closes.
            return
        try:
            storage_errnos = {errno.ENOSPC}
            if hasattr(errno, "EDQUOT"):
                storage_errnos.add(errno.EDQUOT)
            if isinstance(exc, OSError) and exc.errno in storage_errnos:
                self._err(
                    HTTPStatus.INSUFFICIENT_STORAGE,
                    "insufficient storage space",
                    code="storage_full",
                )
            else:
                self._err(HTTPStatus.INTERNAL_SERVER_ERROR, "internal server error")
        except OSError:
            pass

    def _check_deployment_edge(self) -> bool:
        """Enforce the real server's host/proxy contract before routing.

        Legacy unit tests construct a bare ThreadingHTTPServer directly.  The
        executable entrypoint attaches the validated deployment config, which
        is the signal to enable this fail-closed production boundary.
        """
        deployment = getattr(self.server, "deployment_config", None)
        if deployment is None:
            return True
        if owner_market_data_gateway.allows_loopback_chart_edge(self):
            return True
        decision = edge_security.evaluate_request(
            deployment,
            peer_ip=(self.client_address or ("", 0))[0],
            host=self.headers.get("Host") or "",
            forwarded_host=self.headers.get("X-Forwarded-Host") or "",
            forwarded_proto=self.headers.get("X-Forwarded-Proto") or "",
            forwarded_for=self.headers.get("X-Forwarded-For") or "",
        )
        if decision.allowed:
            return True
        self.close_connection = True
        status = (
            HTTPStatus.MISDIRECTED_REQUEST
            if decision.code == "invalid_host"
            else HTTPStatus.FORBIDDEN
        )
        self._err(status, "request rejected by deployment edge policy", code=decision.code)
        return False

    def do_GET(self) -> None:  # noqa: N802
        self._begin_request_observation()
        self._response_started = False
        self._remote_attempt = False
        self._remote_audited = False
        self._remote_context = None
        self._remote_error = ""
        self._extra_headers = []
        try:
            if not self._check_deployment_edge():
                return
            self._route_get()
        except Exception:
            self._handle_unexpected("GET")
        finally:
            self._finish_request_observation("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._begin_request_observation()
        self._response_started = False
        self._remote_attempt = False
        self._remote_audited = False
        self._remote_context = None
        self._remote_error = ""
        self._extra_headers = []
        try:
            if not self._check_deployment_edge():
                return
            self._route_post()
        except Exception:
            self._handle_unexpected("POST")
        finally:
            self._finish_request_observation("POST")

    def do_DELETE(self) -> None:  # noqa: N802
        self._begin_request_observation()
        self._response_started = False
        self._remote_attempt = False
        self._remote_audited = False
        self._remote_context = None
        self._remote_error = ""
        self._extra_headers = []
        try:
            if not self._check_deployment_edge():
                return
            self._route_delete()
        except Exception:
            self._handle_unexpected("DELETE")
        finally:
            self._finish_request_observation("DELETE")

    def _route_get(self) -> None:
        url = urllib.parse.urlparse(self.path)
        path = url.path
        qs = urllib.parse.parse_qs(url.query)

        if path in {"/api/live", "/api/health/live"}:
            deployment = getattr(self.server, "deployment_config", None)
            if deployment is None:
                deployment = runtime_env.deployment_config()
            self._json(
                HTTPStatus.OK,
                service_readiness.liveness_payload(deployment),
            )
            return

        if path in {"/api/ready", "/api/health/ready"}:
            deployment = getattr(self.server, "deployment_config", None)
            if deployment is None:
                deployment = runtime_env.deployment_config()
            payload = service_readiness.readiness_payload(
                deployment,
                probes=getattr(self.server, "readiness_probes", {}),
                optional_components=getattr(self.server, "readiness_optional_components", {}),
            )
            self._json(
                HTTPStatus.OK if payload["ok"] else HTTPStatus.SERVICE_UNAVAILABLE,
                payload,
            )
            return

        if path == "/api/auth/status":
            self._auth_status()
            return

        if path == "/api/auth/providers":
            self._json(HTTPStatus.OK, self._auth_providers_payload())
            return

        if path == "/api/legal/terms":
            # Public: the terms must be readable during registration, before auth.
            self._json(HTTPStatus.OK, legal.terms_payload())
            return

        if path == "/api/billing/access-options":
            # Public: pre-auth welcome screen needs donate tiers + PayPal handle.
            self._json(HTTPStatus.OK, subscriptions.donation_options())
            return

        if path == "/api/auth/google/callback":
            # Public browser redirect from Google OAuth.
            self._google_oauth_callback(qs)
            return

        if path == "/api/dev/bootstrap/redeem":
            # Public, Development-only, loopback-only single-use bootstrap link so
            # a separate automation browser can obtain a real owner session.
            self._dev_bootstrap_redeem(qs)
            return

        if path == "/api/dev/preview/return":
            # Loopback return to the developer session from any persona (works
            # even for the unauthenticated persona which holds no session).
            self._dev_preview_return()
            return

        if path == "/api/runtime/env":
            # Public, secret-free build identity for UI banners and the
            # credential-free Environment Switcher probe. Never return the
            # Development-only status payload here: it contains local paths and
            # operational flags that must not become cross-origin readable.
            self._json(
                HTTPStatus.OK,
                runtime_env.public_status(),
                # Public, secret-free build identity is intentionally readable
                # cross-origin by the credential-free Environment Switcher.
                # Wildcard CORS cannot carry cookies and this endpoint never
                # accepts credentials or mutates state.
                headers={"Access-Control-Allow-Origin": "*"},
            )
            return

        if path == "/ws/market-data":
            # Same-origin browser WebSocket (Cloudflare / Mini App safe).
            # Reuse charts_realtime capability gate.
            if not self._authorize_api("/api/ops/runtime/bars"):
                return
            if (
                str(self.headers.get("Upgrade") or "").lower() == "websocket"
                and self.headers.get("Sec-WebSocket-Key")
            ):
                promote = getattr(self.server, "promote_websocket_request", None)
                if callable(promote) and not promote():
                    self._err(
                        HTTPStatus.SERVICE_UNAVAILABLE,
                        "WebSocket capacity is temporarily full.",
                        code="websocket_admission_saturated",
                        headers={"Retry-After": "1"},
                    )
                    return
            market_data_ws_http.handle_websocket_upgrade(self)
            return

        if path.startswith("/api/") and not self._authorize_api(path):
            return

        if path == "/api/account/card":
            # The Cabinet's own view. Deliberately takes no subject parameter:
            # an account can only ask for its own card, so there is no id for a
            # caller to tamper with.
            context = getattr(self, "_remote_context", None) or {}
            try:
                self._json(HTTPStatus.OK, user_card.build(
                    actor_id=context.get("user_id"), scope=user_card.SCOPE_SELF,
                ))
            except user_card.UserCardError as exc:
                self._err(exc.status, str(exc), code=exc.code)
            except account_auth.AccountAuthError as exc:
                self._err(exc.status, str(exc))
            return

        if path in {"/api/account/security", "/api/account/devices", "/api/account/machines"}:
            context = getattr(self, "_remote_context", None) or {}
            try:
                if path.endswith("/security"):
                    payload = security_devices.account_security(context.get("user_id"))
                elif path.endswith("/machines"):
                    payload = security_devices.list_physical_devices(context.get("user_id"))
                else:
                    payload = security_devices.list_devices(context.get("user_id"))
                self._json(HTTPStatus.OK, payload)
            except security_devices.SecurityDeviceError as exc:
                self._err(exc.status, str(exc), code=exc.code)
            return

        if path == "/api/account/nt-security":
            context = getattr(self, "_remote_context", None) or {}
            try:
                self._json(HTTPStatus.OK, personal_nt_security.security_posture(context.get("user_id")))
            except personal_nt_security.PersonalNtSecurityError as exc:
                self._personal_nt_error(exc)
            return

        if path == "/api/account/identities":
            context = getattr(self, "_remote_context", None) or {}
            try:
                self._json(HTTPStatus.OK, account_auth.list_account_identities(context.get("user_id")))
            except account_auth.AccountAuthError as exc:
                self._err(exc.status, str(exc), code=getattr(exc, "code", "") or "")
            return

        if path == "/api/ninjatrader/resource":
            context = getattr(self, "_remote_context", None) or {}
            try:
                self._json(HTTPStatus.OK, ninjatrader_resources.resource_status(
                    context.get("user_id"),
                    workspace_id=str(qs.get("workspace_id", [""])[0] or ""),
                    is_owner=bool(context.get("is_owner")),
                ))
            except ninjatrader_resources.NinjaTraderResourceError as exc:
                self._err(exc.status, str(exc), code=exc.code)
            return

        if path == "/api/ninjatrader/allocation":
            context = getattr(self, "_remote_context", None) or {}
            self._json(HTTPStatus.OK, agent_allocation.allocation_status(context))
            return

        if path == "/api/admin/ninjatrader/resources":
            try:
                self._json(HTTPStatus.OK, ninjatrader_resources.admin_resource_detail(
                    resource_id=str(qs.get("resource_id", [""])[0] or ""),
                    workspace_id=str(qs.get("workspace_id", [""])[0] or ""),
                ))
            except ninjatrader_resources.NinjaTraderResourceError as exc:
                self._err(exc.status, str(exc), code=exc.code)
            return

        if path == "/api/dev/preview/status":
            context = getattr(self, "_remote_context", None) or {}
            try:
                self._json(HTTPStatus.OK, dev_preview.status(context.get("user_id")))
            except dev_preview.DevPreviewError as exc:
                self._err(exc.status, str(exc), code=exc.code)
            return

        if path == "/api/admin/releases" or path.startswith("/api/admin/releases/"):
            self._releases_get(path)
            return

        if path == "/api/documents" or path.startswith("/api/documents/"):
            self._documents_get(path)
            return

        if path == "/api/admin/overview":
            self._json(
                HTTPStatus.OK,
                _admin_overview_payload(
                    getattr(self, "_remote_context", None) or {},
                ),
            )
            return

        if path == "/api/admin/connectors":
            context = getattr(self, "_remote_context", None) or {}
            caps = context.get("admin_capabilities")
            if not (isinstance(caps, dict) and caps.get("connectors.manage")):
                self._err(HTTPStatus.FORBIDDEN, "Нет прав на коннекторы.",
                          code="capability_required")
                return
            self._json(HTTPStatus.OK, _connectors_dashboard_payload(context))
            return

        if path == "/api/admin/pipeline":
            # Environments and releases answered together. The owner should not
            # have to hold "which candidate is on Canary, and is it the same
            # artifact Production would get" in their head across two screens.
            try:
                registry = environment_registry.snapshot()
            except environment_registry.EnvironmentRegistryError:
                registry = {"environments": []}
            try:
                releases = release_center.list_releases()
            except release_center.ReleaseCenterError:
                releases = {}

            # The candidate summary says which state Canary and Production are
            # in but not when they got there, and "last deploy" is the field an
            # owner reads first. The deployment rows carry the timestamps.
            deployments = {}
            rows = releases.get("releases") or []
            if rows:
                try:
                    detail = release_center.get_release(str(rows[0].get("candidate_id") or ""))
                    for row in (detail.get("deployments") or []):
                        deployments[str(row.get("environment") or "")] = row
                except release_center.ReleaseCenterError:
                    deployments = {}

            tunnel_ip, forwarded_ip = self._request_ips()
            self._json(HTTPStatus.OK, pipeline_view.assemble(
                registry=registry,
                releases=releases,
                sync=development_sync.status(),
                deployments=deployments,
                is_local_request=self._is_loopback_ip(forwarded_ip or tunnel_ip),
            ))
            return

        if path == "/api/admin/development-sync":
            # Is the running LOCAL process the code in the checkout? The
            # project rule is that work happens on LOCAL first, and that rule
            # breaks silently whenever LOCAL keeps serving an old process
            # after a merge.
            self._json(HTTPStatus.OK, {"ok": True, "sync": development_sync.status()})
            return

        if path == "/api/admin/environments":
            # The registry, which is what environments reported about
            # themselves, plus the comparison across them. Distinct from
            # environment-targets, which is about where the switcher may send
            # the browser.
            try:
                self._json(HTTPStatus.OK, environment_registry.snapshot())
            except environment_registry.EnvironmentRegistryError as exc:
                self._err(exc.status, str(exc), code=exc.code)
            return

        if path == "/api/admin/environment-targets":
            probe = str(qs.get("probe", [""])[0] or "").strip().lower()
            if probe:
                try:
                    self._json(
                        HTTPStatus.OK,
                        {"ok": True, "target": _admin_environment_probe(probe)},
                    )
                except ValueError as exc:
                    self._err(HTTPStatus.BAD_REQUEST, str(exc), code="environment_probe_invalid")
                except Exception:
                    self._err(
                        HTTPStatus.BAD_GATEWAY,
                        f"Endpoint {probe} недоступен.",
                        code="environment_probe_failed",
                    )
                return
            payload = _admin_environment_targets()
            deployment = getattr(self.server, "deployment_config", None)
            if deployment is None:
                deployment = runtime_env.deployment_config()
            readiness = service_readiness.readiness_payload(
                deployment,
                probes=getattr(self.server, "readiness_probes", {}),
                optional_components=getattr(self.server, "readiness_optional_components", {}),
            )
            for target in payload["targets"]:
                if target.get("current"):
                    target["readiness"] = str(readiness.get("status") or "unknown")
                    target["health"] = "reachable"
                    target["warnings"].extend(
                        str(check.get("code") or name)
                        for name, check in (readiness.get("checks") or {}).items()
                        if not check.get("ok")
                    )
            self._json(HTTPStatus.OK, payload)
            return

        if path == "/api/admin/operations":
            self._json(HTTPStatus.OK, self._admin_operations_payload())
            return

        if path.startswith("/api/community/attachment/"):
            context = getattr(self, "_remote_context", None) or {}
            attachment_id = path.rsplit("/", 1)[-1]
            try:
                row = community.attachment(
                    attachment_id,
                    workspace_id=str(context.get("workspace_id") or ""),
                )
                payload = row["path"].read_bytes()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", row.get("mime_type") or "application/octet-stream")
                self.send_header("Content-Length", str(len(payload)))
                self.send_header("Cache-Control", "private, max-age=300")
                self.send_header("X-Content-Type-Options", "nosniff")
                filename = urllib.parse.quote(str(row.get("name") or "image"))
                self.send_header("Content-Disposition", "inline; filename*=UTF-8''" + filename)
                self.end_headers()
                self.wfile.write(payload)
            except community.CommunityError as exc:
                self._err(exc.status, str(exc))
            except OSError:
                self._err(HTTPStatus.NOT_FOUND, "Файл вложения недоступен.")
            return

        if path == "/" or path == "":
            self.send_response(HTTPStatus.FOUND)
            self.send_header("Location", "/ui/")
            self.end_headers()
            return

        if path.startswith("/ui"):
            rel = path[len("/ui"):] or "/"
            suffix = ("?" + url.query) if url.query else ""
            # Back-compat redirects: old page URLs → new Aurora pages (keep deep links).
            _aliases = {
                "/ai-strategy.html": "/ui/ai-lab.html", "/ai-strategy": "/ui/ai-lab.html",
                "/ops.html": "/ui/trading.html", "/ops": "/ui/trading.html",
                "/docs.html": "/ui/documents.html", "/docs": "/ui/documents.html",
                "/accounting.html": "/ui/performance.html", "/accounting": "/ui/performance.html",
            }
            if rel in _aliases:
                self.send_response(HTTPStatus.FOUND)
                self.send_header("Location", _aliases[rel] + suffix)
                self.end_headers()
                return
            # Canonicalise the old staging path /ui/aurora/* → /ui/*.
            if rel == "/aurora" or rel.startswith("/aurora/"):
                new_rel = rel[len("/aurora"):] or "/"
                self.send_response(HTTPStatus.FOUND)
                self.send_header("Location", "/ui" + new_rel + suffix)
                self.end_headers()
                return
            # Legacy (classic) UI lives at app/static/<file>; serve it under /ui/legacy/.
            if rel == "/legacy" or rel.startswith("/legacy/"):
                self._serve_static(rel[len("/legacy"):] or "/")
                return
            # New Aurora UI is primary: its pages + assets are served from app/static/aurora/.
            _new_pages = {
                "/", "/index.html", "/backtesting.html", "/trading.html",
                "/performance.html", "/strategies.html", "/ai-lab.html", "/ai-agents.html", "/documents.html",
                "/news.html", "/topstep.html", "/desktop.html", "/practice-trading.html", "/community.html",
                "/mode-entry.html",
            }
            if rel in _new_pages or rel.startswith("/assets/") or rel.startswith("/brand/"):
                self._serve_static("aurora/mode-entry.html" if rel == "/" else "aurora" + rel)
                return
            # Fallback: any other path resolves against the static root (legacy-named files).
            self._serve_static(rel)
            return

        if path == "/api/health":
            payload = {
                "ok": True,
                "host": str(self.server.server_address[0]),
                "deployment": runtime_env.public_status(),
                "ninjatrader_running": jobqueue.ninjatrader_running(),
                "worker": local_worker.status(),
                "admission": (
                    self.server.admission_metrics()
                    if callable(getattr(self.server, "admission_metrics", None)) else {}
                ),
                "vitek": vitek.status(),
            }
            # Absolute local paths are useful to the private developer but
            # should not be disclosed by a production health endpoint.
            if runtime_env.is_development():
                payload.update({
                    "project_root": str(jobqueue.project_root()),
                    "jobs_dir": str(jobqueue.jobs_dir()),
                })
            self._json(HTTPStatus.OK, payload)
            return

        if path == "/api/vitek/status":
            self._json(HTTPStatus.OK, vitek.status())
            return

        if path == "/api/vitek/time-windows":
            self._json(HTTPStatus.OK, vitek.build_time_windows())
            return

        if path == "/api/vitek/reconciliation":
            context = getattr(self, "_remote_context", None) or {}
            if not context.get("is_owner"):
                self._err(HTTPStatus.FORBIDDEN, "Это действие разрешено только владельцу.")
                return
            self._json(HTTPStatus.OK, vitek.reconcile_lifecycle(apply=False))
            return

        vitek_get_parts = [urllib.parse.unquote(p) for p in path.split("/") if p]
        if (
            len(vitek_get_parts) == 5 and vitek_get_parts[:3] == ["api", "vitek", "tasks"]
            and vitek_get_parts[4] == "choices"
        ):
            context = getattr(self, "_remote_context", None) or {}
            if not context.get("is_owner"):
                self._err(HTTPStatus.FORBIDDEN, "Это действие разрешено только владельцу.")
                return
            try:
                self._json(HTTPStatus.OK, vitek.task_input_choices(vitek_get_parts[3]))
            except vitek.VitekError as exc:
                self._err(HTTPStatus.BAD_REQUEST, str(exc))
            return

        if path == "/api/notifications":
            context = getattr(self, "_remote_context", None) or {}
            if not context.get("is_owner"):
                self._err(HTTPStatus.FORBIDDEN, "Это действие разрешено только владельцу.")
                return
            unread = str((qs.get("unread") or ["1"])[0] or "1").lower() not in {"0", "false", "no"}
            since = str((qs.get("since") or [""])[0] or "")
            try:
                limit = int((qs.get("limit") or ["30"])[0])
            except ValueError:
                limit = 30
            self._json(HTTPStatus.OK, in_app_notifications.list_notices(
                unread_only=unread, since=since, limit=limit,
            ))
            return

        if path == "/api/worker/jobs":
            context = getattr(self, "_remote_context", None) or {}
            if not context.get("is_owner"):
                self._err(HTTPStatus.FORBIDDEN, "Это действие разрешено только владельцу.")
                return
            try:
                limit = int((qs.get("limit") or ["100"])[0])
            except ValueError:
                limit = 100
            status_filter = str((qs.get("status") or [""])[0] or "")
            try:
                out = local_worker.list_jobs(
                    status=status_filter,
                    limit=limit,
                    workspace_id=str(context.get("workspace_id") or ""),
                    user_id=context.get("user_id") or 0,
                )
            except production_workers.StorageError as exc:
                self._worker_queue_err(exc)
                return
            self._json(HTTPStatus.OK, out)
            return

        if path == "/api/strategies":
            self._json(HTTPStatus.OK, {
                "strategies": jobqueue.whitelisted_strategies(),
                "note": "strategy whitelist is enforced on the bridge AddOn too",
            })
            return

        if path == "/api/portfolio/cells":
            self._json(HTTPStatus.OK, portfolio_registry.read_registry())
            return

        if path.startswith("/api/governance"):
            if self._governance_get(path, qs):
                return

        if path == "/api/catalog":
            self._json(HTTPStatus.OK, jobqueue.build_catalog_response())
            return

        # Phase 22e — Strategy Profiles registry (best-of/locked configs).
        if path == "/api/profiles":
            self._json(HTTPStatus.OK, jobqueue.read_strategy_profiles())
            return

        # Do-not-recreate registry: ideas that failed all trials.
        if path == "/api/profiles/archive":
            self._json(HTTPStatus.OK, jobqueue.read_archived_strategies())
            return

        if path == "/api/strategy-families":
            self._json(HTTPStatus.OK, jobqueue.read_strategy_families())
            return

        if path == "/api/research-modes":
            self._json(HTTPStatus.OK, jobqueue.read_research_modes())
            return

        # Phase 24 — Instrument coverage (which symbols have a strategy).
        if path == "/api/coverage":
            self._json(HTTPStatus.OK, jobqueue.read_instrument_coverage())
            return

        if path == "/api/performance/trades.csv":
            filename, data = performance.build_trades_csv(
                period=(qs.get("period") or ["month"])[0],
                from_date=(qs.get("from") or [None])[0],
                to_date=(qs.get("to") or [None])[0],
                account_name=(qs.get("account") or [None])[0],
            )
            self._bytes(HTTPStatus.OK, data, "text/csv; charset=utf-8", filename)
            return

        if path == "/api/performance/trades":
            try:
                offset = int((qs.get("offset") or ["0"])[0])
                limit = int((qs.get("limit") or ["200"])[0])
            except ValueError:
                offset, limit = 0, 200
            self._json(HTTPStatus.OK, performance.build_trades_response(
                period=(qs.get("period") or ["month"])[0],
                from_date=(qs.get("from") or [None])[0],
                to_date=(qs.get("to") or [None])[0],
                account_name=(qs.get("account") or [None])[0],
                offset=offset, limit=limit,
            ))
            return

        if path == "/api/performance":
            self._json(HTTPStatus.OK, performance.build_performance_response(
                period=(qs.get("period") or ["now"])[0],
                from_date=(qs.get("from") or [None])[0],
                to_date=(qs.get("to") or [None])[0],
                account_name=(qs.get("account") or [None])[0],
            ))
            return

        if path == "/api/report-favorites":
            validate = str((qs.get("validate") or ["0"])[0]).strip().lower() in {"1", "true", "yes"}
            self._json(HTTPStatus.OK, jobqueue.read_report_favorites(
                validate=validate, **self._data_scope()))
            return

        if path == "/api/reports":
            try:
                limit = int((qs.get("limit") or ["100"])[0])
            except ValueError:
                limit = 100
            try:
                offset = int((qs.get("offset") or ["0"])[0])
            except ValueError:
                offset = 0
            sort_col = str((qs.get("sort") or ["mtime"])[0] or "mtime")
            sort_dir = str((qs.get("dir") or ["desc"])[0] or "desc")
            status_filter = str((qs.get("filter") or ["all"])[0] or "all")
            def optional_float(name: str) -> Optional[float]:
                raw = str((qs.get(name) or [""])[0] or "").strip()
                if not raw:
                    return None
                try:
                    return float(raw)
                except ValueError:
                    return None
            limit = max(1, min(10000, limit))
            offset = max(0, offset)
            try:
                analysis_limit = int((qs.get("analysis_limit") or ["500"])[0])
            except ValueError:
                analysis_limit = 500
            self._json(HTTPStatus.OK, jobqueue.list_reports(
                limit=limit,
                offset=offset,
                sort_col=sort_col,
                sort_dir=sort_dir,
                status_filter=status_filter,
                query=str((qs.get("q") or [""])[0] or ""),
                report_no=str((qs.get("report_no") or [""])[0] or ""),
                instrument=str((qs.get("instrument") or [""])[0] or ""),
                frequency=str((qs.get("frequency") or [""])[0] or ""),
                from_date=str((qs.get("from") or [""])[0] or ""),
                to_date=str((qs.get("to") or [""])[0] or ""),
                min_trades=optional_float("min_trades"),
                min_win=optional_float("min_win"),
                min_pf=optional_float("min_pf"),
                pnl_sign=str((qs.get("pnl_sign") or [""])[0] or ""),
                min_confidence=optional_float("min_confidence"),
                analysis_limit=analysis_limit,
                **self._data_scope(),
            ))
            return

        if path == "/api/jobs":
            try:
                limit = int((qs.get("limit") or ["50"])[0])
            except ValueError:
                limit = 50
            try:
                offset = int((qs.get("offset") or ["0"])[0])
            except ValueError:
                offset = 0
            limit = max(1, min(10000, limit))
            offset = max(0, offset)
            scope = self._data_scope()
            jobs = jobqueue.list_jobs(limit=limit, offset=offset, **scope)
            counts = jobqueue.listable_queue_counts(**scope)
            caps = (getattr(self, "_remote_context", None) or {}).get("capabilities") or {}
            if not caps.get("backtesting") and caps.get("demo_backtest"):
                jobs = [
                    row for row in jobs
                    if str((row.get("origin") or {}).get("type") or "") == "demo"
                ]
                counts = {key: 0 for key in counts}
                for row in jobs:
                    status = str(row.get("status") or "")
                    if status in counts:
                        counts[status] += 1
            self._json(HTTPStatus.OK, {
                "counts": counts,
                "offset": offset,
                "limit": limit,
                "total": sum(int(v or 0) for v in counts.values()),
                "jobs": jobs,
            })
            return

        # /api/jobs/<job_id>(/trades)?
        parts = [p for p in path.split("/") if p]
        if len(parts) >= 3 and parts[0] == "api" and parts[1] == "jobs":
            job_id = parts[2]
            try:
                jobqueue._safe_job_id(job_id)
            except jobqueue.JobValidationError as e:
                self._err(HTTPStatus.BAD_REQUEST, str(e))
                return
            if not jobqueue.job_in_scope(job_id, **self._data_scope()):
                self._err(HTTPStatus.NOT_FOUND, f"job not found: {job_id}")
                return
            caps = (getattr(self, "_remote_context", None) or {}).get("capabilities") or {}
            if (not caps.get("backtesting") and caps.get("demo_backtest")
                    and str(jobqueue.job_origin(job_id).get("type") or "") != "demo"):
                self._err(HTTPStatus.NOT_FOUND, f"job not found: {job_id}")
                return
            if len(parts) == 3:
                full = jobqueue.read_job_full(job_id)
                if not full:
                    self._err(HTTPStatus.NOT_FOUND, f"job not found: {job_id}")
                    return
                self._json(HTTPStatus.OK, full)
                return
            if len(parts) == 4 and parts[3] == "trades":
                try:
                    offset = int((qs.get("offset") or ["0"])[0])
                    limit = int((qs.get("limit") or ["100"])[0])
                except ValueError:
                    offset, limit = 0, 100
                self._json(HTTPStatus.OK, jobqueue.read_trades(job_id, offset=offset, limit=limit))
                return
            if len(parts) == 4 and parts[3] == "bars":
                try:
                    offset = int((qs.get("offset") or ["0"])[0])
                    limit = int((qs.get("limit") or ["5000"])[0])
                except ValueError:
                    offset, limit = 0, 5000
                self._json(HTTPStatus.OK, jobqueue.read_bars(job_id, offset=offset, limit=limit))
                return
            if len(parts) == 4 and parts[3] == "draw_objects":
                self._json(HTTPStatus.OK, jobqueue.read_draw_objects(job_id))
                return

        if path == "/api/diagnostics":
            cat = jobqueue.build_catalog_response()
            self._json(HTTPStatus.OK, {
                "ninjatrader_running": jobqueue.ninjatrader_running(),
                "ninjatrader_user_dir": str(jobqueue.ninjatrader_user_dir()),
                "bridge_log_tail": jobqueue.bridge_log_tail(40),
                "catalog": {
                    "warnings":         cat.get("warnings") or [],
                    "strategies_count": len(cat.get("strategies") or []),
                    "instruments_count": len(cat.get("instruments") or []),
                    "generated_at_utc": cat.get("generated_at_utc") or {},
                    "staleness":        cat.get("staleness") or {},
                },
            })
            return

        if path == "/api/chart/snapshot":
            root = (qs.get("root") or qs.get("instrument") or [""])[0]
            timeframe = (qs.get("timeframe") or ["5m"])[0]
            try:
                saved = market_data.render_chart_snapshot(root, timeframe)
                found = market_data.read_snapshot(saved.get("file"))
                if not found:
                    raise market_data.MarketDataError("Сформированный снимок не найден.")
                data, mime = found
                self._bytes(HTTPStatus.OK, data, mime)
            except market_data.MarketDataError as exc:
                self._err(HTTPStatus.SERVICE_UNAVAILABLE, str(exc))
            return

        # /api/batches collection + per-batch detail/results.
        if path == "/api/batches":
            try:
                limit = int((qs.get("limit") or ["50"])[0])
            except ValueError:
                limit = 50
            try:
                offset = int((qs.get("offset") or ["0"])[0])
            except ValueError:
                offset = 0
            limit = max(1, min(10000, limit))
            offset = max(0, offset)
            scope = self._data_scope()
            self._json(HTTPStatus.OK, {
                "offset": offset,
                "limit": limit,
                "total": jobqueue.count_batches(**scope),
                "batches": jobqueue.list_batches(limit=limit, offset=offset, **scope),
            })
            return

        if len(parts) >= 3 and parts[0] == "api" and parts[1] == "batches":
            batch_id = parts[2]
            try:
                jobqueue._safe_batch_id(batch_id)
            except jobqueue.JobValidationError as e:
                self._err(HTTPStatus.BAD_REQUEST, str(e))
                return
            if not jobqueue.batch_in_scope(batch_id, **self._data_scope()):
                self._err(HTTPStatus.NOT_FOUND, f"batch not found: {batch_id}")
                return
            if len(parts) == 3:
                m = jobqueue.read_batch(batch_id)
                if not m:
                    self._err(HTTPStatus.NOT_FOUND, f"batch not found: {batch_id}")
                    return
                self._json(HTTPStatus.OK, m)
                return
            if len(parts) == 4 and parts[3] == "results":
                r = jobqueue.read_batch_results(batch_id)
                if not r:
                    self._err(HTTPStatus.NOT_FOUND, f"batch not found: {batch_id}")
                    return
                self._json(HTTPStatus.OK, r)
                return

        # /api/scc/* routes (Strategy Control Center v2)
        if path == "/api/scc/strategies":
            try:
                self._json(HTTPStatus.OK, _build_scc_strategies())
            except Exception as e:
                self._json(HTTPStatus.OK, {
                    "strategies": [], "rejected_running": [],
                    "rejected_classes": [], "heartbeat": {},
                    "error": str(e),
                })
            return

        # /api/ops/* routes (Strategy Control Center, read-only here)
        if path.startswith("/api/ops"):
            runtime_override = ""
            context = getattr(self, "_remote_context", None) or {}
            if path.startswith("/api/ops/runtime/"):
                runtime_override = workspaces.runtime_dir_for_context(context.get("workspace_context") or {})
            if runtime_override:
                with ops_runtime.runtime_dir_override(runtime_override):
                    handled = self._ops_get(path, qs)
            else:
                handled = self._ops_get(path, qs)
            if handled:
                return

        if path == "/api/integrations/status":
            self._json(HTTPStatus.OK, integrations.status())
            return

        if path == "/api/telegram/status":
            status = telegram_service.status()
            if _server_environment_explicit():
                try:
                    status["production_queue"] = production_telegram.get_queue().status()
                except production_telegram.StorageError as exc:
                    status["production_queue"] = {"ok": False, "code": exc.code}
            self._json(HTTPStatus.OK, status)
            return

        if path == "/api/practice/account":
            try:
                context = getattr(self, "_remote_context", None) or {}
                self._json(HTTPStatus.OK, practice_trading.get_account(
                    context.get("user_id"),
                    workspace_id=str(context.get("workspace_id") or ""),
                ))
            except practice_trading.PracticeTradingError as exc:
                self._err(exc.status, str(exc))
            return

        if path == "/api/practice/report":
            try:
                context = getattr(self, "_remote_context", None) or {}
                self._json(HTTPStatus.OK, practice_trading.report(
                    context.get("user_id"),
                    workspace_id=str(context.get("workspace_id") or ""),
                ))
            except practice_trading.PracticeTradingError as exc:
                self._err(exc.status, str(exc))
            return

        if path == "/api/ai-lab/ratings":
            context = getattr(self, "_remote_context", None) or {}
            if not context.get("is_owner"):
                self._err(HTTPStatus.FORBIDDEN, "Рейтинги ИИ доступны только владельцу.")
                return
            self._json(HTTPStatus.OK, ai_ratings.tables(
                workspace_id=str(context.get("workspace_id") or ""),
            ))
            return

        if path == "/api/community/feed":
            context = getattr(self, "_remote_context", None) or {}
            self._json(HTTPStatus.OK, community.feed(
                limit=(qs.get("limit") or ["50"])[0],
                workspace_id=str(context.get("workspace_id") or ""),
                channel_id=(qs.get("channel") or [""])[0],
            ))
            return

        if path == "/api/community/ratings":
            context = getattr(self, "_remote_context", None) or {}
            self._json(HTTPStatus.OK, {"ok": True, "ratings": community.ratings(
                workspace_id=str(context.get("workspace_id") or ""),
            )})
            return

        if path == "/api/demo-backtests/scenarios":
            self._json(HTTPStatus.OK, {
                "ok": True,
                "scenarios": demo_backtest.list_scenarios(),
                "watermark": "Демоверсия. Данные нереальные.",
            })
            return

        if path == "/api/owner/support/monitoring":
            try:
                actor = (getattr(self, "_remote_context", None) or {}).get("user_id")
                overview = user_support.owner_overview(actor)
                overview["auth_sessions"] = account_auth.active_sessions_overview(actor).get("sessions") or []
                overview["telemetry_note"] = (
                    "Показатели относятся к вкладке приложения. "
                    "Системные CPU/RAM других программ браузер не раскрывает."
                )
                overview["runtime"] = runtime_env.status()
                self._json(HTTPStatus.OK, overview)
            except (user_support.UserSupportError, account_auth.AccountAuthError) as exc:
                self._err(getattr(exc, "status", 400), str(exc))
            return

        if path == "/api/owner/sessions":
            try:
                actor = (getattr(self, "_remote_context", None) or {}).get("user_id")
                self._json(HTTPStatus.OK, account_auth.active_sessions_overview(actor))
            except account_auth.AccountAuthError as exc:
                self._err(exc.status, str(exc))
            return

        if path == "/api/owner/google-migration":
            try:
                actor = (getattr(self, "_remote_context", None) or {}).get("user_id")
                self._json(HTTPStatus.OK, account_auth.google_migration_users(actor))
            except account_auth.AccountAuthError as exc:
                self._err(exc.status, str(exc))
            return

        if path == "/api/auth/google/status":
            self._json(HTTPStatus.OK, google_auth.status())
            return

        if path == "/api/auth/test/status":
            try:
                self._json(HTTPStatus.OK, test_auth.status())
            except (runtime_env.RuntimeEnvError, test_auth.TestAuthError) as exc:
                self._err(getattr(exc, "status", 403), str(exc))
            return

        if path == "/api/auth/test/users":
            try:
                context = getattr(self, "_remote_context", None) or {}
                if not context.get("is_owner"):
                    self._err(HTTPStatus.FORBIDDEN, "Только владелец.")
                    return
                self._json(HTTPStatus.OK, test_auth.list_virtual_users())
            except (runtime_env.RuntimeEnvError, test_auth.TestAuthError, account_auth.AccountAuthError) as exc:
                self._err(getattr(exc, "status", 403), str(exc))
            return

        if path.startswith("/api/owner/support/users/"):
            parts_support = [urllib.parse.unquote(p) for p in path.split("/") if p]
            if len(parts_support) == 5:
                try:
                    context = getattr(self, "_remote_context", None) or {}
                    actor = context.get("user_id")
                    out = user_support.owner_status(actor, parts_support[4])
                    out["is_self"] = str(actor or "") == str(parts_support[4])
                    if out["is_self"]:
                        out["current_session_id"] = str(context.get("session_id") or "")
                    self._json(HTTPStatus.OK, out)
                except user_support.UserSupportError as exc:
                    self._err(exc.status, str(exc))
                return
            self._err(HTTPStatus.NOT_FOUND, f"no support route: {path}")
            return

        if path.startswith("/api/owner/support/screenshots/"):
            parts_support = [urllib.parse.unquote(p) for p in path.split("/") if p]
            if len(parts_support) == 5:
                try:
                    actor = (getattr(self, "_remote_context", None) or {}).get("user_id")
                    blob, content_type = user_support.screenshot_bytes(actor, parts_support[4])
                    self._bytes(HTTPStatus.OK, blob, content_type)
                except user_support.UserSupportError as exc:
                    self._err(exc.status, str(exc))
                return
            self._err(HTTPStatus.NOT_FOUND, f"no support route: {path}")
            return

        if path == "/api/auth/users":
            try:
                out = account_auth.list_users(
                    (getattr(self, "_remote_context", None) or {}).get("user_id"))
                out["admin_capability_catalog"] = permissions.admin_capability_catalog()
                for row in out.get("users") or []:
                    if row.get("is_owner"):
                        continue
                    try:
                        row["subscription"] = subscriptions.active_entitlement(row.get("user_id"))
                    except subscriptions.SubscriptionError:
                        row["subscription"] = {}
                self._json(HTTPStatus.OK, out)
            except account_auth.AccountAuthError as exc:
                self._err(exc.status, str(exc))
            return

        if path.startswith("/api/auth/users/"):
            uparts = [urllib.parse.unquote(p) for p in path.split("/") if p]
            if len(uparts) == 4:  # GET /api/auth/users/<id> — full admin detail
                try:
                    actor = (getattr(self, "_remote_context", None) or {}).get("user_id")
                    detail = account_auth.user_detail(actor, uparts[3])
                    user = detail.get("user") or {}
                    target = user.get("user_id")
                    try:
                        subscription = subscriptions.active_entitlement(target)
                    except subscriptions.SubscriptionError:
                        subscription = {}
                    try:
                        entitlements = (subscriptions.entitlements_for_user(target) or {}).get("entitlements") or []
                    except subscriptions.SubscriptionError:
                        entitlements = []
                    perm = permissions.resolve(user, subscription)
                    detail["subscription"] = subscription
                    detail["entitlements"] = entitlements
                    detail["capabilities"] = perm["capabilities"]
                    detail["capability_catalog"] = permissions.capability_catalog()
                    detail["admin_capabilities"] = perm["admin_capabilities"]
                    detail["admin_capability_catalog"] = permissions.admin_capability_catalog()
                    detail["nt_connection"] = self._user_nt_info(target, bool(user.get("is_owner")))
                    detail["public_plans"] = subscriptions.list_plans().get("public_plans") or []
                    self._json(HTTPStatus.OK, detail)
                except account_auth.AccountAuthError as exc:
                    self._err(exc.status, str(exc))
                return
            if len(uparts) == 5 and uparts[4] == "card":
                # GET /api/auth/users/<id>/card -- the same card the account
                # sees in its Cabinet, at admin detail. Same builder, same
                # facts; scope decides how much is returned, never what is
                # computed, so the two views cannot drift apart.
                context = getattr(self, "_remote_context", None) or {}
                try:
                    self._json(HTTPStatus.OK, user_card.build(
                        actor_id=context.get("user_id"),
                        target_id=uparts[3],
                        scope=user_card.SCOPE_ADMIN,
                    ))
                except user_card.UserCardError as exc:
                    self._err(exc.status, str(exc), code=exc.code)
                except account_auth.AccountAuthError as exc:
                    self._err(exc.status, str(exc))
                return
            self._err(HTTPStatus.NOT_FOUND, f"no auth route: {path}")
            return

        if path == "/api/auth/me":
            self._auth_me()
            return

        if path.startswith("/api/auth/avatar/"):
            self._serve_avatar(urllib.parse.unquote(path[len("/api/auth/avatar/"):]))
            return

        if path == "/api/billing/plans":
            self._json(HTTPStatus.OK, subscriptions.list_plans())
            return

        if path == "/api/billing/me":
            context = getattr(self, "_remote_context", None) or {}
            self._json(HTTPStatus.OK, subscriptions.entitlements_for_user(context.get("user_id")))
            return

        if path == "/api/billing/donate":
            self._json(HTTPStatus.OK, subscriptions.donation_options())
            return

        if path == "/api/owner/plans":
            try:
                self._json(HTTPStatus.OK, subscriptions.plan_matrix(
                    (getattr(self, "_remote_context", None) or {}).get("user_id")))
            except subscriptions.SubscriptionError as exc:
                self._err(exc.status, str(exc))
            return

        if path == "/api/owner/journal":
            raw_limit = (qs.get("limit") or ["200"])[0]
            self._json(HTTPStatus.OK, admin_journal.read_journal(
                category=(qs.get("category") or [""])[0],
                query=(qs.get("q") or [""])[0],
                limit=int(raw_limit) if str(raw_limit).isdigit() else 200,
                suspicious_only=(qs.get("suspicious") or [""])[0] in ("1", "true", "yes"),
                period=(qs.get("period") or [""])[0],
            ))
            return

        if path == "/api/owner/payment":
            try:
                self._json(HTTPStatus.OK, subscriptions.get_payment_config(
                    (getattr(self, "_remote_context", None) or {}).get("user_id")))
            except subscriptions.SubscriptionError as exc:
                self._err(exc.status, str(exc))
            return

        if path == "/api/owner/paypal":
            try:
                self._json(HTTPStatus.OK, subscriptions.get_paypal_config(
                    (getattr(self, "_remote_context", None) or {}).get("user_id")))
            except subscriptions.SubscriptionError as exc:
                self._err(exc.status, str(exc))
            return

        if path == "/api/owner/payment-requests":
            try:
                out = subscriptions.list_payment_requests(
                    (getattr(self, "_remote_context", None) or {}).get("user_id"),
                    status=(qs.get("status") or [""])[0])
                for row in out.get("requests") or []:
                    plan = subscriptions.PLANS.get(str(row.get("plan_id"))) or {}
                    row["plan_label"] = plan.get("label") or row.get("plan_id")
                    try:
                        who = account_auth.find_active_user(row.get("user_id")) or {}
                        row["user_label"] = (" ".join([
                            str(who.get("first_name") or ""), str(who.get("last_name") or "")]).strip()
                            or str(who.get("username") or ""))
                    except Exception:
                        row["user_label"] = ""
                self._json(HTTPStatus.OK, out)
            except subscriptions.SubscriptionError as exc:
                self._err(exc.status, str(exc))
            return

        if path == "/api/bridge/setup":
            context = getattr(self, "_remote_context", None) or {}
            try:
                use_connector = (
                    runtime_env.environment_explicit() and runtime_env.is_production()
                ) or str((qs.get("transport") or [""])[0]) == "production_connector"
                out = (
                    connector_protocol.setup_payload(
                        context.get("user_id"),
                        workspace_id=str((qs.get("workspace_id") or [""])[0]),
                    )
                    if use_connector
                    else workspaces.bridge_setup(context.get("user_id"))
                )
                self._json(HTTPStatus.OK, out)
            except (workspaces.WorkspaceError, connector_protocol.ConnectorProtocolError) as exc:
                self._err(exc.status, str(exc), code=getattr(exc, "code", "") or "")
            return

        if path == "/api/workspaces":
            context = getattr(self, "_remote_context", None) or {}
            workspace_context = context.get("workspace_context") or workspaces.context_for_user(
                context.get("user_id"), is_owner=bool(context.get("is_owner")),
                owner_id=str(os.environ.get(telegram_service.CHAT_ENV) or ""),
            )
            self._json(HTTPStatus.OK, workspace_context)
            return

        if path == "/api/bridge/connections":
            context = getattr(self, "_remote_context", None) or {}
            try:
                use_connector = (
                    runtime_env.environment_explicit() and runtime_env.is_production()
                ) or str((qs.get("transport") or [""])[0]) == "production_connector"
                out = (
                    connector_protocol.list_installations(
                        context.get("user_id"),
                        workspace_id=str((qs.get("workspace_id") or [""])[0]),
                    )
                    if use_connector
                    else workspaces.list_connections(context.get("user_id"))
                )
                self._json(HTTPStatus.OK, out)
            except (workspaces.WorkspaceError, connector_protocol.ConnectorProtocolError) as exc:
                self._err(exc.status, str(exc), code=getattr(exc, "code", "") or "")
            return

        if path == "/api/owner/operations":
            self._json(HTTPStatus.OK, self._admin_operations_payload())
            return

        if path.startswith("/api/bridge/commands/"):
            context = getattr(self, "_remote_context", None) or {}
            command_id = urllib.parse.unquote(path.rsplit("/", 1)[-1])
            try:
                self._json(HTTPStatus.OK, connector_protocol.command_status(
                    context.get("user_id"),
                    workspace_id=str((qs.get("workspace_id") or [""])[0]),
                    command_id=command_id,
                ))
            except (workspaces.WorkspaceError, connector_protocol.ConnectorProtocolError) as exc:
                self._err(exc.status, str(exc), code=getattr(exc, "code", "") or "")
            return

        if path == "/api/owner/vouchers":
            try:
                actor = (getattr(self, "_remote_context", None) or {}).get("user_id")
                out = subscriptions.list_vouchers(actor)
                # Enrich each redemption with the redeemer's label so the owner can
                # see who used an invite and jump straight to that account.
                for voucher in out.get("vouchers") or []:
                    for red in voucher.get("redemptions") or []:
                        try:
                            who = account_auth.find_active_user(red.get("user_id")) or {}
                        except Exception:
                            who = {}
                        red["user_label"] = (" ".join([
                            str(who.get("first_name") or ""), str(who.get("last_name") or "")]).strip()
                            or str(who.get("username") or "") or f"ID {red.get('user_id')}")
                        red["user_exists"] = bool(who)
                self._json(HTTPStatus.OK, out)
            except subscriptions.SubscriptionError as exc:
                self._err(exc.status, str(exc))
            return

        if path == "/api/telegram/remote/me":
            context = getattr(self, "_remote_context", None)
            if not context:
                self._err(HTTPStatus.BAD_REQUEST, "Этот endpoint предназначен для Telegram Mini App.")
                return
            self._json(HTTPStatus.OK, {
                "ok": True, "source": telegram_remote.SOURCE,
                "user_id": context.get("user_id"), "username": context.get("username"),
                "role": context.get("role"), "live_trading_allowed": False,
            })
            return

        if path == "/api/telegram/remote/access":
            self._json(HTTPStatus.OK, telegram_remote.admin_status())
            return

        if path == "/api/telegram/tunnel/status":
            try:
                self._json(HTTPStatus.OK, tunnel_manager.status(port=self.server.server_address[1]))
            except tunnel_manager.TunnelManagerError as exc:
                self._err(exc.status, str(exc))
            return

        if path == "/api/telegram/group":
            try:
                self._json(HTTPStatus.OK, telegram_service.group_status())
            except Exception as e:
                self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"telegram group status failed: {e}")
            return

        if path == "/api/topstep/status":
            self._json(HTTPStatus.OK, integrations.topstep_status())
            return

        if path == "/api/news":
            try:
                limit = int((qs.get("limit") or ["50"])[0])
            except ValueError:
                limit = 50
            self._json(HTTPStatus.OK, integrations.news(limit))
            return

        if path == "/api/news/live":
            try:
                max_age = int((qs.get("max_age_min") or ["60"])[0])
            except ValueError:
                max_age = 60
            try:
                limit = int((qs.get("limit") or ["40"])[0])
            except ValueError:
                limit = 40
            self._json(HTTPStatus.OK, integrations.live_news(max_age, limit))
            return

        if path == "/api/ai-lab/external-agents/status":
            self._json(HTTPStatus.OK, integrations.external_agents_status())
            return

        if path == "/api/ai-lab/cloud-agents/status":
            self._json(HTTPStatus.OK, ai_cloud_agents.status())
            return

        if path in {"/api/ai-agents", "/api/ai-agents/summary"}:
            payload = ai_agent_registry.summary()
            payload["routing"] = ai_agent_router.status()
            self._json(HTTPStatus.OK, payload)
            return

        if path == "/api/ai-agents/usage":
            try:
                limit = max(1, min(1000, int((qs.get("limit") or ["200"])[0])))
            except ValueError:
                limit = 200
            self._json(HTTPStatus.OK, {"usage": ai_agent_registry.usage_rows(limit=limit)})
            return

        if path.startswith("/api/ai-agents/"):
            agent_id = urllib.parse.unquote(path.rsplit("/", 1)[-1])
            try:
                self._json(HTTPStatus.OK, {"agent": ai_agent_registry.get_agent(agent_id)})
            except ai_agent_registry.AgentRegistryError as exc:
                self._err(HTTPStatus.NOT_FOUND, str(exc))
            return

        # /api/ai-lab/* read model
        if path.startswith("/api/ai-lab"):
            if self._ai_lab_get(path, qs):
                return

        self._err(HTTPStatus.NOT_FOUND, f"no route: {path}")

    def _governance_get(self, path: str, qs: Dict[str, Any]) -> bool:
        parts = [p for p in path.split("/") if p]
        if len(parts) < 2 or parts[0] != "api" or parts[1] != "governance":
            return False

        if path == "/api/governance/runtime-defaults":
            self._json(HTTPStatus.OK, governance.runtime_defaults())
            return True

        if path == "/api/governance/north-star":
            try:
                self._json(HTTPStatus.OK, governance.north_star_progress())
            except Exception as e:
                self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"north-star failed: {e}")
            return True

        if path == "/api/governance/summary":
            privileged = self._has_governance_read_privilege()
            documents = governance.list_documents()
            if not privileged:
                documents = [
                    governance.public_document(row)
                    for row in documents if governance.document_is_public(row)
                ]
            payload = {
                "documents": documents,
                "runtime_defaults": governance.runtime_defaults(),
                "history": governance.read_change_log(80) if privileged else [],
            }
            if privileged:
                payload.update({
                    "owner": governance.PROJECT_OWNER,
                    "consistency": governance.consistency_report(),
                })
            self._json(HTTPStatus.OK, payload)
            return True

        if path == "/api/governance/documents":
            privileged = self._has_governance_read_privilege()
            documents = governance.list_documents()
            if not privileged:
                documents = [
                    governance.public_document(row)
                    for row in documents if governance.document_is_public(row)
                ]
            payload = {"documents": documents}
            if privileged:
                payload["owner"] = governance.PROJECT_OWNER
            self._json(HTTPStatus.OK, payload)
            return True

        if path == "/api/governance/history":
            if not self._has_governance_read_privilege():
                self._json(HTTPStatus.OK, {"entries": []})
                return True
            try:
                limit = int((qs.get("limit") or ["80"])[0])
            except ValueError:
                limit = 80
            entity_id = (qs.get("entity_id") or [None])[0]
            document_id = (qs.get("document_id") or [None])[0]
            self._json(HTTPStatus.OK, {
                "entries": governance.read_change_log(limit, entity_id=entity_id, document_id=document_id),
            })
            return True

        if path == "/api/governance/document-revisions":
            document_id = (qs.get("document_id") or [None])[0]
            if not document_id:
                self._err(HTTPStatus.BAD_REQUEST, "document_id required"); return True
            if not self._has_governance_read_privilege():
                self._json(HTTPStatus.OK, {"document_id": document_id, "revisions": []})
                return True
            self._json(HTTPStatus.OK, governance.document_revisions(document_id))
            return True

        if path == "/api/governance/consistency":
            if not self._has_governance_read_privilege():
                self._err(HTTPStatus.FORBIDDEN, "governance diagnostics require docs privilege")
                return True
            self._json(HTTPStatus.OK, governance.consistency_report())
            return True

        if len(parts) == 4 and parts[2] == "documents":
            doc_id = urllib.parse.unquote(parts[3])
            doc = governance.read_document(doc_id)
            if not doc:
                self._err(HTTPStatus.NOT_FOUND, f"governance document not found: {doc_id}")
                return True
            if not self._has_governance_read_privilege():
                if not governance.document_is_public(doc):
                    self._err(HTTPStatus.NOT_FOUND, f"governance document not found: {doc_id}")
                    return True
                doc = governance.public_document(doc)
            self._json(HTTPStatus.OK, doc)
            return True

        return False

    # ------------- /api/ops/* GET dispatcher --------------------------------

    def _ops_get(self, path: str, qs: Dict[str, Any]) -> bool:
        parts = [p for p in path.split("/") if p]
        # /api/ops/...
        if len(parts) < 3:
            return False
        sub = parts[2]

        if path.startswith("/api/ops/runtime/") and self._workspace_runtime_stubbed(path, qs):
            return True

        if path == "/api/ops/strategies":
            self._json(HTTPStatus.OK, {"strategies": ops.list_strategies()})
            return True

        if path == "/api/ops/audit-log":
            try:
                limit = int((qs.get("limit") or ["200"])[0])
            except ValueError:
                limit = 200
            sid = (qs.get("strategy_id") or [None])[0]
            self._json(HTTPStatus.OK, {"entries": ops.read_audit_log(limit, sid)})
            return True

        if path == "/api/ops/live-lock-status":
            self._json(HTTPStatus.OK, ops.live_lock_status())
            return True

        # ---- Phase 17: NinjaTrader runtime read-only endpoints ----
        if path == "/api/ops/runtime/heartbeat":
            self._json(HTTPStatus.OK, ops_runtime.read_heartbeat())
            return True
        if path == "/api/ops/runtime/health":
            self._json(HTTPStatus.OK, ops_runtime.health())
            return True
        if path == "/api/ops/runtime/strategy-display":
            self._json(HTTPStatus.OK, ops_runtime.read_strategy_display_prefs())
            return True
        if path == "/api/ops/strategy-start-dates":
            p = runtime_env.data_path(
                "ops", "strategy_start_dates.json", project_root=_PROJECT_ROOT,
            )
            try:
                data = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {
                    "schema_version": 1,
                    "strategies": {},
                }
            except Exception:
                data = {"schema_version": 1, "strategies": {}}
            self._json(HTTPStatus.OK, data)
            return True
        if path == "/api/ops/runtime/strategy-history":
            try:
                limit_events = int((qs.get("limit_events") or ["500"])[0])
            except ValueError:
                limit_events = 500
            try:
                limit_sessions = int((qs.get("limit_sessions") or ["200"])[0])
            except ValueError:
                limit_sessions = 200
            self._json(HTTPStatus.OK, ops_runtime.read_strategy_history(
                limit_events=limit_events,
                limit_sessions=limit_sessions,
                strategy_id=(qs.get("strategy_id") or [None])[0],
                runtime_instance_id=(qs.get("runtime_instance_id") or [None])[0],
                class_name=(qs.get("class_name") or [None])[0],
            ))
            return True
        if path == "/api/ops/runtime/history":
            try:
                limit = int((qs.get("limit") or ["100"])[0])
            except ValueError:
                limit = 100
            sessions = ops_runtime.get_strategy_sessions(limit=limit)
            self._json(HTTPStatus.OK, {"sessions": sessions})
            return True
        if path == "/api/ops/runtime/strategies":
            # Trading Online expects the bridge to be the source of truth.
            # Always use merge_all_runtime_strategies() which iterates the raw
            # bridge strategies.json — never adds fake registry-only entries.
            sel_acct = (qs.get("selected_account")    or [None])[0]
            sel_inst = (qs.get("selected_instrument") or [None])[0]
            sel_tf   = (qs.get("selected_timeframe")  or [None])[0]
            runtime_list = ops_runtime.merge_all_runtime_strategies(
                selected_account=sel_acct,
                selected_instrument=sel_inst,
                selected_timeframe=sel_tf,
            )
            raw_list = ops_runtime.read_strategies_raw()
            self._json(HTTPStatus.OK, {
                "strategies": runtime_list,
                "raw":        raw_list,
                "source":     "runtime_bridge",
                "warnings":   [] if runtime_list else [
                    "NinjaTrader bridge не видит активных strategy instances. "
                    "Проверьте, что стратегия включена в NinjaTrader и bridge пересобран."
                ],
            })
            return True
        if sub == "runtime" and len(parts) >= 4 and parts[3] == "strategies" and len(parts) == 5:
            sid = parts[4]
            self._json(HTTPStatus.OK, ops_runtime.merge_strategy_view(sid))
            return True
        if path == "/api/ops/runtime/positions":
            self._json(HTTPStatus.OK, ops_runtime.read_positions())
            return True
        if path == "/api/ops/runtime/accounts":
            payload = ops_runtime.read_accounts_with_source()
            try:
                account_ledger.record_accounts(payload)
            except Exception:
                payload.setdefault("warnings", []).append("account ledger snapshot could not be recorded")
            self._json(HTTPStatus.OK, payload)
            return True
        if path == "/api/ops/runtime/account-history":
            account = (qs.get("account") or [""])[0]
            try:
                limit = int((qs.get("limit") or ["500"])[0])
            except ValueError:
                limit = 500
            context = getattr(self, "_remote_context", None) or {}
            workspace_context = context.get("workspace_context") or {}
            active_workspace = workspace_context.get("active_workspace") if isinstance(workspace_context, dict) else {}
            if isinstance(active_workspace, dict) and active_workspace and not active_workspace.get("uses_owner_runtime"):
                self._json(HTTPStatus.OK, workspaces.workspace_account_history(
                    str(active_workspace.get("workspace_id") or ""), account, limit,
                ))
                return True
            self._json(HTTPStatus.OK, account_ledger.account_history(account, limit))
            return True
        if path == "/api/ops/runtime/executions":
            sid = (qs.get("strategy_id") or [None])[0]
            acct = (qs.get("account_name") or [None])[0]
            iid = (qs.get("runtime_instance_id") or [None])[0]
            cls = (qs.get("class_name") or [None])[0]
            inst = (qs.get("instrument") or [None])[0]
            try: limit = int((qs.get("limit") or ["500"])[0])
            except ValueError: limit = 500
            limit = max(1, min(limit, 100_000))
            executions, dedupe_meta = ops_runtime.read_executions_with_meta(
                sid, limit,
                account_name=acct,
                runtime_instance_id=iid,
                class_name=cls,
                instrument=inst,
            )
            self._json(HTTPStatus.OK, {
                "strategy_id": sid,
                "account_name": acct,
                "runtime_instance_id": iid,
                "class_name": cls,
                "instrument": inst,
                "dedupe": dedupe_meta,
                "raw_count": dedupe_meta.get("raw_count"),
                "deduped_count": dedupe_meta.get("deduped_count"),
                "duplicate_count": dedupe_meta.get("duplicate_count"),
                "executions":  executions,
            })
            return True
        if path == "/api/ops/runtime/orders":
            sid = (qs.get("strategy_id") or [None])[0]
            acct = (qs.get("account_name") or [None])[0]
            iid = (qs.get("runtime_instance_id") or [None])[0]
            cls = (qs.get("class_name") or [None])[0]
            inst = (qs.get("instrument") or [None])[0]
            try: limit = int((qs.get("limit") or ["500"])[0])
            except ValueError: limit = 500
            limit = max(1, min(limit, 100_000))
            orders, dedupe_meta = ops_runtime.read_orders_with_meta(
                sid, limit,
                account_name=acct,
                runtime_instance_id=iid,
                class_name=cls,
                instrument=inst,
            )
            self._json(HTTPStatus.OK, {
                "strategy_id": sid,
                "account_name": acct,
                "runtime_instance_id": iid,
                "class_name": cls,
                "instrument": inst,
                "dedupe": dedupe_meta,
                "raw_count": dedupe_meta.get("raw_count"),
                "deduped_count": dedupe_meta.get("deduped_count"),
                "duplicate_count": dedupe_meta.get("duplicate_count"),
                "orders":      orders,
            })
            return True
        if path == "/api/ops/runtime/errors":
            try: limit = int((qs.get("limit") or ["100"])[0])
            except ValueError: limit = 100
            self._json(HTTPStatus.OK, {"errors": ops_runtime.read_errors(limit)})
            return True
        if path == "/api/ops/runtime/commands":
            try: limit = int((qs.get("limit") or ["200"])[0])
            except ValueError: limit = 200
            self._json(HTTPStatus.OK, {"commands": ops_runtime.read_commands(limit)})
            return True
        if path == "/api/ops/runtime/command-results":
            try: limit = int((qs.get("limit") or ["200"])[0])
            except ValueError: limit = 200
            self._json(HTTPStatus.OK, {"results": ops_runtime.read_command_results(limit)})
            return True
        if path == "/api/ops/runtime/command-status":
            try: timeout = int((qs.get("timeout_sec") or ["30"])[0])
            except ValueError: timeout = 30
            cid = (qs.get("command_id") or [None])[0]
            since = (qs.get("since_ts") or [None])[0]
            if cid:
                self._json(HTTPStatus.OK,
                           ops_runtime.get_command_status(cid, timeout_sec=timeout))
            else:
                self._json(HTTPStatus.OK, {
                    "statuses": ops_runtime.get_command_statuses_since(
                        since_ts=since, timeout_sec=timeout),
                })
            return True
        if path == "/api/ops/runtime/instruments":
            # Returns per-root current/all instruments for the Trading Online selector.
            # Each root entry has front_month (most recent), and all contracts.
            desktop = str((qs.get("desktop") or ["0"])[0]).lower() in {"1", "true", "yes"}
            instr_doc = jobqueue.read_instruments_catalog() or {}
            all_instr = instr_doc.get("instruments") or []
            root_map: dict = {}
            for ins in all_instr:
                if not isinstance(ins, dict):
                    continue
                name = str(ins.get("instrument") or ins.get("symbol") or ins.get("name") or "")
                root = str(ins.get("root") or name.split(" ", 1)[0])
                if not root:
                    continue
                if desktop and root not in _DESKTOP_INSTRUMENT_ROOTS:
                    continue
                root_map.setdefault(root, []).append(ins)
            result = []
            for root, contracts in sorted(root_map.items()):
                def _dl(c: dict) -> str:
                    return str(c.get("data_last") or "")
                contracts_sorted = sorted(contracts, key=_dl, reverse=True)
                # Front month = the most-recently-active *unexpired* contract.
                # Energy futures (and many others) expire during the preceding
                # calendar month, so a pure "expiry month >= now.month" check
                # wrongly keeps the expired contract for the whole calendar month.
                # Robust rule:
                # 1) among contracts with data in the last 30 days whose expiry
                #    month is still current/future, pick the freshest data_last;
                # 2) if only expired-month contracts are "live", prefer the
                #    nearest future expiry when the catalog has one;
                # 3) otherwise fall back to calendar-month proximity / freshest.
                now = datetime.now()
                def _days_since(c: dict) -> float:
                    raw = str(c.get("data_last") or "")
                    if not raw:
                        return float("inf")
                    try:
                        from datetime import datetime as _dt  # noqa: F811
                        return (now - _dt.strptime(raw[:10], "%Y-%m-%d")).days
                    except (ValueError, TypeError):
                        return float("inf")

                def _expiry_key(c: dict):
                    expiry = str(c.get("expiry") or "")
                    try:
                        month, year = expiry.split("-", 1)
                        return (2000 + int(year), int(month))
                    except (TypeError, ValueError):
                        return None

                future_contracts = []
                for contract in contracts:
                    key = _expiry_key(contract)
                    if key is not None and key >= (now.year, now.month):
                        future_contracts.append((key, contract))

                # Contracts with data within last 30 days are considered "live".
                live = [c for c in contracts if _days_since(c) <= 30]
                active = [c for c in live if (_expiry_key(c) or (0, 0)) >= (now.year, now.month)]
                def _front_rank(c: dict):
                    # Freshest data first; on a tie prefer the nearer expiry month.
                    key = _expiry_key(c) or (9999, 99)
                    return (_days_since(c), key)

                if active:
                    front = min(active, key=_front_rank)
                elif future_contracts:
                    # Prefer a still-listed future month over a recently-expired
                    # contract that still has bars within the 30-day window.
                    front = min(future_contracts, key=lambda item: item[0])[1]
                elif live:
                    front = min(live, key=_front_rank)
                else:
                    front = min(future_contracts, key=lambda item: item[0])[1] if future_contracts else (
                        contracts_sorted[0] if contracts_sorted else None)
                result.append({
                    "root": root,
                    "front_month": front,
                    "contracts": contracts_sorted,
                })
            self._json(
                HTTPStatus.OK,
                {"roots": apply_desktop_instrument_fallbacks(result, desktop=desktop)},
            )
            return True

        if path == "/api/ops/runtime/price-alerts":
            market_data.evaluate_alerts()
            instrument = (qs.get("instrument") or [""])[0]
            include_inactive = str((qs.get("include_inactive") or ["1"])[0]).lower() not in {"0", "false", "no"}
            self._json(HTTPStatus.OK, market_data.list_alerts(
                instrument=instrument, include_inactive=include_inactive))
            return True

        if path == "/api/ops/runtime/chart-commands":
            status = (qs.get("status") or ["pending"])[0]
            self._json(HTTPStatus.OK, market_data.list_chart_commands(status=status))
            return True

        if path == "/api/ops/runtime/snapshots":
            pattern = qs.get("pattern")[0] if qs.get("pattern") else None
            favorites_only = str((qs.get("favorites") or ["0"])[0]).lower() in {"1", "true", "yes"}
            try:
                limit = int((qs.get("limit") or ["300"])[0])
            except ValueError:
                limit = 300
            self._json(HTTPStatus.OK, market_data.list_snapshots(
                pattern=pattern, favorites_only=favorites_only, limit=limit))
            return True

        if len(parts) == 5 and parts[:4] == ["api", "ops", "runtime", "snapshots"]:
            found = market_data.read_snapshot(parts[4])
            if not found:
                self._err(HTTPStatus.NOT_FOUND, "snapshot not found")
                return True
            data, mime = found
            self._bytes(HTTPStatus.OK, data, mime)
            return True

        if path == "/api/ops/runtime/bars/status":
            status = market_data_failover.status()
            status["ninjatrader"] = {
                "running": bool(jobqueue.ninjatrader_running()),
                "heartbeat": ops_runtime.read_heartbeat(),
            }
            try:
                status["ipc"] = market_data_ipc.metrics()
                status["baseline"] = {
                    "stages": market_data_baseline.snapshot().get("stages") or [],
                }
            except Exception as exc:
                status["ipc"] = {"error": str(exc)[:200]}
            try:
                status["live_sources"] = market_data_live_supervisor.status()
            except Exception as exc:
                status["live_sources"] = {"error": str(exc)[:200]}
            self._json(HTTPStatus.OK, status)
            return True

        if path == "/api/ops/runtime/market-data/live-sources":
            self._json(HTTPStatus.OK, market_data_live_supervisor.status())
            return True

        if path == "/api/ops/runtime/market-data/baseline":
            self._json(HTTPStatus.OK, market_data_baseline.snapshot())
            return True

        if path == "/api/ops/runtime/market-data/ipc":
            self._json(HTTPStatus.OK, {
                "metrics": market_data_ipc.metrics(),
                "recent_events": market_data_ipc.recent_events(50),
            })
            return True

        if path == "/api/ops/runtime/market-data/router":
            self._json(HTTPStatus.OK, market_data_router.get_router().status())
            return True

        if path == "/api/ops/runtime/market-data/gaps":
            self._json(HTTPStatus.OK, market_data_gap_recovery.get_worker().status())
            return True

        if path == "/api/ops/runtime/market-data/diagnostics":
            plat = data_platform.get_platform()
            self._json(HTTPStatus.OK, {
                "status": "IMPLEMENTATION_PARTIAL",
                "platform_mode": plat.mode,
                "cache": plat.cache.stats() if hasattr(plat.cache, "stats") else {},
                "ipc": market_data_ipc.metrics(),
                "browser_ws": market_data_ws_http.metrics(),
                "subscriptions": market_data_subscriptions.get_subscription_registry().snapshot(),
                "router": market_data_router.get_router().status(),
                "gaps": market_data_gap_recovery.get_worker().status(),
                "transports": {
                    "bridge_ipc": "127.0.0.1 only",
                    "browser_ws": "same-origin /ws/market-data",
                },
            })
            return True

        if path == "/api/ops/runtime/bars":
            # Register a dynamic BarsRequest in the bridge, prefer its live
            # series and fall back to the newest real Strategy Analyzer artifact.
            instrument = (qs.get("instrument") or [""])[0]
            timeframe = (qs.get("timeframe") or [""])[0]
            try:
                limit = int((qs.get("limit") or ["1500"])[0])
            except ValueError:
                limit = 1500
            try:
                range_days = int((qs.get("range_days") or ["0"])[0])
            except ValueError:
                range_days = 0
            try:
                max_points = int((qs.get("max_points") or ["0"])[0])
            except ValueError:
                max_points = 0
            from_date = (qs.get("from") or [""])[0]
            to_date = (qs.get("to") or [""])[0]
            from_ts = (qs.get("from_ts") or [""])[0]
            to_ts = (qs.get("to_ts") or [""])[0]
            if not instrument:
                self._err(HTTPStatus.BAD_REQUEST, "instrument is required")
                return True
            try:
                context = getattr(self, "_remote_context", None) or {}
                effective_points = min(
                    max(1, int(limit or 1500)),
                    int(max_points) if int(max_points or 0) >= 3 else max(1, int(limit or 1500)),
                )
                if effective_points > 10000:
                    if (not _server_environment_explicit()
                            and not market_data_failover.TopstepXProvider().configured()):
                        market_data.register_request(
                            instrument, timeframe, limit, range_days, from_date, to_date,
                        )
                    queued = self._run_large_chart_batch([{
                        "instrument": instrument, "timeframe": timeframe,
                        "limit": limit, "range_days": range_days,
                        "from": from_date, "to": to_date,
                        "from_ts": from_ts, "to_ts": to_ts,
                        "max_points": max_points,
                    }], context)
                    if queued is None:
                        return True
                    payload = queued[0] if queued else {"bars": [], "status": "waiting"}
                else:
                    payload = _market_bars_payload(
                        instrument, timeframe, limit, range_days, from_date, to_date,
                        max_points=max_points,
                        workspace_id=str(context.get("workspace_id") or ""),
                        from_ts=from_ts, to_ts=to_ts,
                    )
            except market_data.MarketDataError as exc:
                self._err(HTTPStatus.BAD_REQUEST, str(exc))
                return True
            if not _server_environment_explicit():
                market_data.evaluate_alerts()
            self._json(HTTPStatus.OK, payload)
            return True

        if sub == "strategies" and len(parts) >= 4:
            sid = parts[3]
            tail = parts[4] if len(parts) >= 5 else None
            if tail == "notes":
                self._json(HTTPStatus.OK, ops.get_notes(sid))
                return True
            s = ops.get_strategy(sid)
            if not s:
                self._err(HTTPStatus.NOT_FOUND, f"strategy not found: {sid}")
                return True
            if len(parts) == 4:
                states = ops.load_states()
                self._json(HTTPStatus.OK, {
                    "strategy": s,
                    "state":    states.get(sid),
                    "metrics":  ops.compute_metrics_safe(s),
                    "runtime":  ops_runtime.merge_strategy_view(sid),
                })
                return True
            tail = parts[4]
            if tail == "metrics":
                self._json(HTTPStatus.OK, ops.compute_metrics_safe(s))
                return True
            if tail == "trades":
                self._json(HTTPStatus.OK, ops.get_trades(sid))
                return True
            if tail == "journal":
                self._json(HTTPStatus.OK, ops.get_journal(sid))
                return True
            if tail == "risk":
                m = ops.compute_metrics_safe(s)
                self._json(HTTPStatus.OK, {
                    "strategy_id": sid,
                    "risk_state": m.get("risk_state"),
                    "risk_reasons": m.get("risk_reasons"),
                    "limits": s.get("risk_profile"),
                    "today_adj_pnl": m.get("today_adj_pnl"),
                    "weekly_adj_pnl": m.get("weekly_adj_pnl"),
                    "current_drawdown": m.get("current_drawdown"),
                    "consec_losing_days": m.get("consec_losing_days"),
                })
                return True

        return False

    # ------------- /api/ai-lab/* GET dispatcher -----------------------------

    def _ai_lab_get(self, path: str, qs: Dict[str, Any]) -> bool:
        path = str(path or "").rstrip("/") or "/"
        parts = [p for p in path.split("/") if p]
        # parts[0]="api", parts[1]="ai-lab", parts[2..]=...
        if len(parts) < 3:
            self._err(HTTPStatus.NOT_FOUND, f"no ai-lab route: {path}")
            return True
        sub = parts[2]

        if sub == "orchestrator" and len(parts) == 5 and parts[3] == "jobs":
            context = getattr(self, "_remote_context", None) or {}
            job = local_worker.get(
                urllib.parse.unquote(parts[4]),
                workspace_id=str(context.get("workspace_id") or ""),
            )
            if (not job or (not context.get("is_owner")
                    and str(job.get("user_id") or "") != str(context.get("user_id") or ""))):
                self._err(HTTPStatus.NOT_FOUND, "AI worker job not found")
                return True
            self._json(HTTPStatus.OK, self._public_ai_worker_job(job))
            return True

        if path == "/api/ai-lab/domain-agents":
            self._json(HTTPStatus.OK, ai_domain_agents.list_personas())
            return True

        if path == "/api/ai-lab/domain-agents/voices":
            try:
                self._json(HTTPStatus.OK, ai_agent_tts.list_voice_profiles())
            except Exception as e:
                self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"voice profiles failed: {e}")
            return True

        if path in {"/api/ai-lab/tts/catalog", "/api/ai-lab/tts/voices"}:
            try:
                self._json(HTTPStatus.OK, {
                    "ok": True,
                    "catalog": ai_agent_tts.tts_catalog(),
                    "presets": ai_agent_tts.list_presets(),
                    **ai_agent_tts.tts_status(),
                })
            except Exception as e:
                self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"tts catalog failed: {e}")
            return True

        # GET /api/ai-lab/domain-agents/{id}/voice
        if sub == "domain-agents" and len(parts) == 5 and parts[4] == "voice":
            agent_id = urllib.parse.unquote(parts[3])
            try:
                profile = ai_agent_tts.get_voice_profile(agent_id)
                self._json(HTTPStatus.OK, {
                    "ok": True,
                    "agent": ai_agent_tts.staff_meta(agent_id),
                    "voice": profile,
                    "preview_phrase": ai_agent_tts.PREVIEW_PHRASES.get(
                        ai_agent_tts.normalize_agent_id(agent_id),
                        ai_agent_tts.PREVIEW_PHRASES["vitek"],
                    ),
                    "catalog": ai_agent_tts.tts_catalog(),
                    "presets": ai_agent_tts.list_presets(),
                })
            except ai_agent_tts.AgentTtsError as e:
                self._err(HTTPStatus.BAD_REQUEST, str(e))
            except Exception as e:
                self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"voice profile failed: {e}")
            return True

        if path == "/api/ai-lab/accounting":
            period = (qs.get("period") or ["month"])[0]
            account = (qs.get("account") or [""])[0]
            from_date = (qs.get("from") or [None])[0]
            to_date = (qs.get("to") or [None])[0]
            try:
                self._json(HTTPStatus.OK, ai_domain_agents.accounting_snapshot(
                    period, account, from_date=from_date, to_date=to_date,
                ))
            except Exception as e:
                self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"accounting report failed: {e}")
            return True

        if path == "/api/ai-lab/strategy-analysis":
            period = (qs.get("period") or ["month"])[0]
            try:
                self._json(HTTPStatus.OK, ai_domain_agents.strategy_snapshot(period))
            except Exception as e:
                self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"strategy analysis failed: {e}")
            return True

        if path == "/api/ai-lab/news-analysis":
            try:
                limit = int((qs.get("limit") or ["40"])[0])
                self._json(HTTPStatus.OK, ai_news_agent.snapshot(limit=limit))
            except ValueError:
                self._err(HTTPStatus.BAD_REQUEST, "limit must be an integer")
            except Exception as e:
                self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"news analysis failed: {e}")
            return True

        if path == "/api/ai-lab/summary":
            try:
                self._json(HTTPStatus.OK, ai_read_model.summary())
            except Exception as e:
                self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"summary error: {e}")
            return True

        if path == "/api/ai-lab/lifecycle":
            try:
                self._json(HTTPStatus.OK, ai_read_model.lifecycle_cards())
            except Exception as e:
                self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"lifecycle error: {e}")
            return True

        if path == "/api/ai-lab/cell-history":
            cell = (qs.get("cell") or [""])[0]
            try:
                self._json(HTTPStatus.OK, ai_read_model.cell_history(cell))
            except Exception as e:
                self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"cell-history error: {e}")
            return True

        if path == "/api/ai-lab/matrix":
            roots_q = (qs.get("roots") or [None])[0]
            roots = [r.strip().upper() for r in roots_q.split(",")] if roots_q else None
            try:
                self._json(HTTPStatus.OK, ai_read_model.matrix(roots=roots))
            except Exception as e:
                self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"matrix error: {e}")
            return True

        if path == "/api/ai-lab/performance":
            try:
                self._json(HTTPStatus.OK, ai_read_model.performance_board())
            except Exception as e:
                self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"performance error: {e}")
            return True

        if path == "/api/ai-lab/model-performance":
            try:
                days = int((qs.get("days") or ["30"])[0])
                self._json(HTTPStatus.OK, ai_read_model.model_performance(days=days))
            except ValueError:
                self._err(HTTPStatus.BAD_REQUEST, "days must be an integer")
            except Exception as e:
                self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"model performance error: {e}")
            return True

        if path == "/api/ai-lab/portfolio":
            try:
                self._json(HTTPStatus.OK, ai_read_model.portfolio_board())
            except Exception as e:
                self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"portfolio error: {e}")
            return True

        if path == "/api/ai-lab/calendar":
            try:
                self._json(HTTPStatus.OK, ai_read_model.calendar())
            except Exception as e:
                self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"calendar error: {e}")
            return True

        if path == "/api/ai-lab/lm-studio/health":
            try:
                self._json(HTTPStatus.OK, ai_lm_studio.lm_status(allow_probe=False))
            except Exception as e:
                self._json(HTTPStatus.OK, {
                    "available": False,
                    "ready": False,
                    "run_allowed": False,
                    "status": "server_unavailable",
                    "message_ru": "LM Studio недоступна — запустите сервер (порт 1234).",
                    "error": str(e),
                })
            return True

        if path == "/api/ai-lab/lm-studio/readiness":
            try:
                url = urllib.parse.urlparse(self.path)
                qs = urllib.parse.parse_qs(url.query or "")
                force = qs.get("force", ["0"])[0] in ("1", "true", "yes")
                self._json(
                    HTTPStatus.OK,
                    ai_lm_studio.lm_status(allow_probe=True, force=force),
                )
            except Exception as e:
                self._json(HTTPStatus.OK, {
                    "available": False,
                    "ready": False,
                    "run_allowed": False,
                    "status": "server_unavailable",
                    "message_ru": "Не удалось проверить AI-модели.",
                    "error": str(e),
                })
            return True

        if path == "/api/ai-lab/bootstrap/status":
            try:
                url = urllib.parse.urlparse(self.path)
                qs = urllib.parse.parse_qs(url.query or "")
                probe = qs.get("probe", ["0"])[0] in ("1", "true", "yes")
                self._json(HTTPStatus.OK, ai_bootstrap.status(probe=probe))
            except Exception as e:
                self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"bootstrap status failed: {e}")
            return True

        if path == "/api/ai-lab/current":
            self._json(
                HTTPStatus.OK,
                {"current": ai_runner.current(scope=self._ai_conversation_scope())},
            )
            return True

        if path == "/api/ai-lab/run/status":
            try:
                status = ai_runner.run_status(scope=self._ai_conversation_scope())
                self._json(HTTPStatus.OK, {"ok": True, "run": status})
            except Exception as e:
                self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"run status failed: {e}")
            return True

        if path in {"/api/ai-lab/chief-agent", "/api/ai-lab/orchestrator"}:
            try:
                self._json(
                    HTTPStatus.OK,
                    ai_chief_agent.status(scope=self._ai_conversation_scope()),
                )
            except Exception as e:
                self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"orchestrator status failed: {e}")
            return True

        if path == "/api/ai-lab/orchestrator/conversations":
            try:
                scope = self._ai_conversation_scope()
                self._json(HTTPStatus.OK, {"ok": True, "conversations": ai_chief_agent.list_conversations(scope=scope)})
            except Exception as e:
                self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"conversations list failed: {e}")
            return True

        # /api/ai-lab/orchestrator/conversations/{id}
        if sub == "orchestrator" and len(parts) == 5 and parts[3] == "conversations":
            conversation_id = parts[4]
            try:
                limit = int((qs.get("limit") or ["200"])[0])
            except ValueError:
                limit = 200
            try:
                scope = self._ai_conversation_scope()
                self._json(HTTPStatus.OK, {
                    "ok": True,
                    "conversation_id": conversation_id,
                    "messages": ai_chief_agent.conversation_messages(conversation_id, limit=limit, scope=scope),
                })
            except Exception as e:
                self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"conversation load failed: {e}")
            return True

        if path == "/api/ai-lab/errors/summary":
            try:
                payload = {
                    "patterns": ai_errors.top_repeated_patterns(threshold=1)[:30],
                    "recent_errors": ai_errors.recent_errors(limit=50),
                    "lessons_recent": ai_lessons.all_lessons(limit=20),
                    "global_operator_notes": ai_operator_notes.list_global_notes(limit=20),
                    "lessons_count": len(ai_lessons.all_lessons(limit=10_000)),
                }
                self._json(HTTPStatus.OK, payload)
            except Exception as e:
                self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"errors summary failed: {e}")
            return True

        if path == "/api/ai-lab/compile-source-status":
            try:
                self._json(HTTPStatus.OK, ai_compile_errors.source_status())
            except Exception as e:
                self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"source_status failed: {e}")
            return True

        if path == "/api/ai-lab/researches":
            try:
                self._json(HTTPStatus.OK, ai_research_catalog.list_researches())
            except Exception as e:
                self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"research list failed: {e}")
            return True

        if sub == "researches" and len(parts) == 4:
            try:
                self._json(HTTPStatus.OK, ai_research_catalog.detail(parts[3]))
            except ai_research_catalog.ResearchCatalogError as e:
                self._err(HTTPStatus.NOT_FOUND, str(e))
            except Exception as e:
                self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"research detail failed: {e}")
            return True

        # /api/ai-lab/experiments
        if path == "/api/ai-lab/experiments":
            root = (qs.get("root") or [None])[0]
            status = (qs.get("status") or [None])[0]
            try:
                limit = int((qs.get("limit") or ["200"])[0])
            except ValueError:
                limit = 200
            items = ai_registry.list_experiments(target_root=root, status=status, limit=limit)
            self._json(HTTPStatus.OK, {"experiments": items, "total": len(items)})
            return True

        # /api/ai-lab/experiments/{id}[/history]
        if sub == "experiments" and len(parts) >= 4:
            exp_id = parts[3]
            if len(parts) == 4:
                exp = ai_registry.read_experiment(exp_id)
                if not exp:
                    self._err(HTTPStatus.NOT_FOUND, f"experiment not found: {exp_id}")
                    return True
                self._json(HTTPStatus.OK, exp)
                return True
            if len(parts) == 5 and parts[4] == "history":
                self._json(HTTPStatus.OK, {"history": ai_registry.history_for(exp_id)})
                return True
            if len(parts) == 5 and parts[4] == "activity":
                try:
                    since = int((qs.get("since") or ["0"])[0])
                except ValueError:
                    since = 0
                try:
                    limit = int((qs.get("limit") or ["500"])[0])
                except ValueError:
                    limit = 500
                exp = ai_registry.read_experiment(exp_id) or {}
                data = ai_activity.tail(exp_id, since_line=since, limit=limit)
                data["status"] = exp.get("status")
                data["ai_cell_id"] = exp.get("ai_cell_id")
                data["class_name"] = exp.get("class_name")
                data["sandbox_path"] = (exp.get("strategy_source") or {}).get("sandbox_path")
                data["terminal"] = ai_registry.is_terminal(exp.get("status", "draft"))
                self._json(HTTPStatus.OK, data)
                return True
            if len(parts) == 5 and parts[4] == "notes":
                try:
                    self._json(HTTPStatus.OK, {"notes": ai_operator_notes.list_all(exp_id)})
                except Exception as e:
                    self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"notes list failed: {e}")
                return True
            if len(parts) == 5 and parts[4] == "backtest":
                try:
                    self._json(HTTPStatus.OK, ai_read_model.backtest_payload(exp_id))
                except Exception as e:
                    self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"backtest payload failed: {e}")
                return True

        # /api/ai-lab/jobs/{job_id}/analysis-pack
        if sub == "jobs" and len(parts) == 5 and parts[4] == "analysis-pack":
            job_id = parts[3]
            job_dir = ai_backtest.find_job_dir(job_id)
            if not job_dir:
                self._err(HTTPStatus.NOT_FOUND, f"job not found: {job_id}")
                return True
            try:
                capital = float((qs.get("capital") or ["5000"])[0])
            except ValueError:
                capital = 5000.0
            try:
                pack = ai_analysis_pack.build(job_dir, capital=capital)
                self._json(HTTPStatus.OK, pack)
            except Exception as e:
                self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"analysis-pack failed: {e}")
            return True

        self._err(HTTPStatus.NOT_FOUND, f"no ai-lab route: {path}")
        return True

    # ------------- /api/ai-lab/* POST dispatcher ----------------------------

    def _sse_write(self, event: str, data: Dict[str, Any]) -> bool:
        """Write one Server-Sent Event; return False if the client disconnected."""
        try:
            payload = json.dumps(self._json_safe(data), ensure_ascii=False, allow_nan=False)
            chunk = f"event: {event}\ndata: {payload}\n\n".encode("utf-8")
            self.wfile.write(chunk)
            self.wfile.flush()
            return True
        except OSError as e:
            if self._is_client_disconnect_error(e):
                return False
            raise

    def _sse_keepalive(self) -> bool:
        try:
            self.wfile.write(b": keepalive\n\n")
            self.wfile.flush()
            return True
        except OSError as e:
            if self._is_client_disconnect_error(e):
                return False
            raise

    def _enqueue_ai_message(self, body: Dict[str, Any], *, scope: Dict[str, Any],
                            mirror_to_telegram: bool = True) -> Dict[str, Any]:
        request_id = str(
            body.get("request_id") or self.headers.get("Idempotency-Key") or ""
        ).strip()
        if not request_id:
            request_id = "air_" + hashlib.sha256(
                f"{time.time_ns()}:{threading.get_ident()}:{os.urandom(16).hex()}".encode()
            ).hexdigest()[:32]
        # Self-heal a crashed worker before accepting more durable work.
        local_worker.start_background_worker(interval_sec=0.2)
        return local_worker.enqueue_ai_message(
            str(body.get("message") or body.get("text") or ""),
            request_id=request_id,
            conversation_id=str(body.get("conversation_id") or "default"),
            agent=str(body.get("agent") or body.get("agent_id") or ""),
            scope=scope,
            mirror_to_telegram=mirror_to_telegram,
            timeout_sec=600,
        )

    @staticmethod
    def _public_ai_worker_job(job: Dict[str, Any]) -> Dict[str, Any]:
        state = str(job.get("status") or "")
        out: Dict[str, Any] = {
            "worker_job_id": str(job.get("worker_job_id") or ""),
            "status": state,
            "attempts": int(job.get("attempts") or 0),
            "max_attempts": int(job.get("max_attempts") or 0),
            "queued_at_utc": str(job.get("queued_at_utc") or ""),
            "started_at_utc": str(job.get("started_at_utc") or ""),
            "finished_at_utc": str(job.get("finished_at_utc") or ""),
            "cancel_requested": bool(job.get("cancel_requested")),
        }
        if state == "succeeded" and isinstance(job.get("result"), dict):
            out["result"] = job["result"]
        if state in {"failed", "cancelled", "stale"}:
            out["error"] = str(job.get("error") or "")
        return out

    def _wait_ai_message(self, job: Dict[str, Any], *, workspace_id: str,
                         timeout_sec: float = 610.0) -> Optional[Dict[str, Any]]:
        job_id = str(job.get("worker_job_id") or "")
        deadline = time.monotonic() + max(1.0, float(timeout_sec))
        while time.monotonic() < deadline:
            row = local_worker.get(job_id, workspace_id=workspace_id)
            if row and str(row.get("status") or "") in {
                "succeeded", "failed", "cancelled", "stale",
            }:
                return row
            time.sleep(0.2)
        return None

    def _run_large_chart_batch(self, rows: list[Dict[str, Any]],
                               context: Dict[str, Any]) -> Optional[list[Dict[str, Any]]]:
        """Execute a large chart calculation in the durable worker process."""
        workspace_id = str(context.get("workspace_id") or "")
        scope = {
            "user_id": context.get("user_id"),
            "workspace_id": workspace_id,
            "membership_role": context.get("membership_role") or "",
        }
        runtime_dir = workspaces.runtime_dir_for_context(
            context.get("workspace_context") or {}
        )
        try:
            local_worker.start_background_worker(interval_sec=0.2)
            job = local_worker.enqueue_chart_batch(
                rows, scope=scope, runtime_dir=runtime_dir, timeout_sec=60,
            )
            terminal = self._wait_ai_message(
                job, workspace_id=workspace_id, timeout_sec=65,
            )
        except (TypeError, ValueError) as exc:
            self._err(HTTPStatus.BAD_REQUEST, str(exc))
            return None
        except Exception as exc:
            self._err(HTTPStatus.SERVICE_UNAVAILABLE, f"chart worker unavailable: {exc}")
            return None
        if terminal is None:
            self._err(
                HTTPStatus.GATEWAY_TIMEOUT,
                "chart worker did not finish before the request deadline",
                code="chart_worker_timeout",
            )
            return None
        if terminal.get("status") != "succeeded":
            self._err(
                HTTPStatus.BAD_GATEWAY,
                str(terminal.get("error") or "chart worker failed"),
                code=f"chart_worker_{terminal.get('status') or 'failed'}",
            )
            return None
        result = terminal.get("result") if isinstance(terminal.get("result"), dict) else {}
        series = result.get("series") if isinstance(result.get("series"), list) else None
        return [row for row in (series or []) if isinstance(row, dict)] if series is not None else None

    def _ai_lab_orchestrator_stream(self, body: Dict[str, Any], *, scope: Dict[str, Any]) -> None:
        """Stream status/final events while durable worker executes the turn.

        The HTTP handler never invokes an LLM or an allowlisted action. It only
        enqueues a workspace-bound SQLite job and observes its persisted state.
        """
        conversation_id = str(body.get("conversation_id") or "default")
        workspace_id = str(scope.get("workspace_id") or "")
        try:
            job = self._enqueue_ai_message(body, scope=scope, mirror_to_telegram=True)
        except (TypeError, ValueError) as exc:
            self._err(HTTPStatus.BAD_REQUEST, str(exc))
            return
        except Exception as exc:
            self._err(HTTPStatus.SERVICE_UNAVAILABLE, f"AI worker queue unavailable: {exc}")
            return
        job_id = str(job.get("worker_job_id") or "")

        try:
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Accel-Buffering", "no")
            self.send_header("Connection", "close")
            self.end_headers()
        except OSError as e:
            if self._is_client_disconnect_error(e):
                return
            raise

        if not self._sse_write("thinking_start", {
            "conversation_id": conversation_id,
            "worker_job_id": job_id,
            "durable": True,
        }):
            return

        # Fallback wait statuses for models that expose no native reasoning.
        wait_statuses = ["Определяю исполнителя…", "Работаю над запросом…"]
        status_idx = 0
        started_at = time.time()
        last_status = 0.0
        max_seconds = 610.0
        while True:
            if time.time() - started_at > max_seconds:
                local_worker.cancel(job_id, workspace_id=workspace_id)
                self._sse_write("error", {"error": "orchestrator stream timeout"})
                self._sse_write("done", {"ok": False})
                return
            row = local_worker.get(job_id, workspace_id=workspace_id)
            state = str((row or {}).get("status") or "queued")
            if state == "succeeded":
                out = (row or {}).get("result") if isinstance((row or {}).get("result"), dict) else {}
                msg = out.get("message") if isinstance(out.get("message"), dict) else {}
                self._sse_write("thinking_done", {"text": ""})
                self._sse_write("final", {
                    "reply": str(out.get("reply") or ""),
                    "conversation_id": str(out.get("conversation_id") or conversation_id),
                    "model": out.get("model"),
                    "provider": out.get("provider"),
                    "agent": out.get("agent"),
                    "doubts": out.get("doubts") or [],
                    "message_id": str(msg.get("message_id") or ""),
                    "timestamp_utc": str(msg.get("timestamp_utc") or ""),
                    "worker_job_id": job_id,
                })
                self._sse_write("done", {"ok": True})
                return
            if state in {"failed", "cancelled", "stale"}:
                error = str((row or {}).get("error") or f"AI worker job {state}")
                self._sse_write("error", {"error": error, "worker_job_id": job_id})
                self._sse_write("done", {"ok": False})
                return
            now = time.time()
            if now - last_status >= 8.0:
                last_status = now
                label = wait_statuses[status_idx % len(wait_statuses)]
                if state == "queued":
                    label = "Запрос в очереди…"
                if not self._sse_write("status", {
                    "text": label, "worker_status": state, "worker_job_id": job_id,
                }):
                    return
                status_idx += 1
            elif not self._sse_keepalive():
                return
            time.sleep(0.25)

    def _ai_lab_orchestrator_sync(self, body: Dict[str, Any], *,
                                  scope: Dict[str, Any],
                                  mirror_to_telegram: bool) -> None:
        workspace_id = str(scope.get("workspace_id") or "")
        try:
            job = self._enqueue_ai_message(
                body, scope=scope, mirror_to_telegram=mirror_to_telegram,
            )
        except (TypeError, ValueError) as exc:
            self._err(HTTPStatus.BAD_REQUEST, str(exc))
            return
        except Exception as exc:
            self._err(HTTPStatus.SERVICE_UNAVAILABLE, f"AI worker queue unavailable: {exc}")
            return
        row = self._wait_ai_message(job, workspace_id=workspace_id)
        if row is None:
            self._err(
                HTTPStatus.GATEWAY_TIMEOUT,
                "AI worker did not finish before the request deadline.",
                code="ai_worker_timeout",
            )
            return
        state = str(row.get("status") or "")
        if state == "succeeded":
            out = row.get("result") if isinstance(row.get("result"), dict) else {}
            self._json(HTTPStatus.OK, out)
            return
        self._err(
            HTTPStatus.CONFLICT if state == "cancelled" else HTTPStatus.BAD_GATEWAY,
            str(row.get("error") or f"AI worker job {state}"),
            code=f"ai_worker_{state or 'failed'}",
        )

    def _ai_lab_post(self, path: str, body: Dict[str, Any]) -> None:
        parts = [part for part in path.split("/") if part]
        if (len(parts) == 6 and parts[:4] == ["api", "ai-lab", "orchestrator", "jobs"]
                and parts[5] == "cancel"):
            context = getattr(self, "_remote_context", None) or {}
            job_id = urllib.parse.unquote(parts[4])
            workspace_id = str(context.get("workspace_id") or "")
            job = local_worker.get(job_id, workspace_id=workspace_id)
            if (not job or (not context.get("is_owner")
                    and str(job.get("user_id") or "") != str(context.get("user_id") or ""))):
                self._err(HTTPStatus.NOT_FOUND, "AI worker job not found")
                return
            cancelled = local_worker.cancel(job_id, workspace_id=workspace_id)
            self._json(
                HTTPStatus.OK,
                {"ok": bool(cancelled.get("ok")),
                 "job": self._public_ai_worker_job(cancelled.get("job") or job)},
            )
            return
        if path == "/api/ai-lab/researches":
            try:
                research = ai_research_catalog.create(body)
                self._json(HTTPStatus.CREATED, {
                    "ok": True,
                    "created": True,
                    "message": f"Добавлено исследование «{research.get('title') or research.get('research_id')}».",
                    "summary": research.get("summary"),
                    "automatic_conclusion": (research.get("evaluation") or {}).get("automatic_conclusion"),
                    "research": research,
                })
            except ai_research_catalog.ResearchCatalogError as e:
                self._err(HTTPStatus.BAD_REQUEST, str(e))
            except Exception as e:
                self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"research create failed: {e}")
            return

        if len(parts) == 4 and parts[0:3] == ["api", "ai-lab", "researches"]:
            try:
                research = ai_research_catalog.update(parts[3], body)
                self._json(HTTPStatus.OK, {
                    "ok": True, "updated": True,
                    "message": f"Исследование «{research.get('title') or parts[3]}» обновлено.",
                    "research": research,
                })
            except ai_research_catalog.ResearchCatalogError as e:
                status = HTTPStatus.NOT_FOUND if "не найдено" in str(e) else HTTPStatus.BAD_REQUEST
                self._err(status, str(e))
            except Exception as e:
                self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"research update failed: {e}")
            return

        if path.startswith("/api/ai-lab/cloud-agents/"):
            try:
                if path == "/api/ai-lab/cloud-agents/settings":
                    out = ai_cloud_agents.update_settings(body.get("settings") or body)
                elif path == "/api/ai-lab/cloud-agents/provider-key":
                    out = ai_cloud_agents.configure_provider(
                        str(body.get("provider") or ""), str(body.get("api_key") or "")
                    )
                elif path == "/api/ai-lab/cloud-agents/provider-test":
                    out = ai_cloud_agents.recheck_provider(str(body.get("provider") or ""))
                elif path == "/api/ai-lab/cloud-agents/provider-disconnect":
                    out = ai_cloud_agents.disconnect_provider(str(body.get("provider") or ""))
                else:
                    self._err(HTTPStatus.NOT_FOUND, f"no cloud-agents route: {path}")
                    return
            except ai_cloud_agents.CloudAgentsError as exc:
                self._err(HTTPStatus.BAD_REQUEST, str(exc))
                return
            self._json(HTTPStatus.OK, out)
            return

        if path == "/api/ai-lab/bootstrap/start":
            try:
                out = ai_bootstrap.start(
                    timeout_sec=max(30, min(900, int(body.get("timeout_sec", 300)))),
                    # Default OFF: launching NT before login causes account lockouts.
                    start_ninjatrader=bool(body.get("start_ninjatrader", False)),
                    start_lm_studio=bool(body.get("start_lm_studio", True)),
                    start_lm_server=bool(body.get("start_lm_server", True)),
                    load_models=bool(body.get("load_models", False)),
                    wait_readiness=bool(body.get("wait_readiness", False)),
                )
                self._json(HTTPStatus.OK, out)
            except Exception as e:
                self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"bootstrap start failed: {e}")
            return

        if path == "/api/ai-lab/bootstrap/unload":
            try:
                out = ai_bootstrap.unload_models(
                    stop_server=bool(body.get("stop_server", True))
                )
                self._json(HTTPStatus.OK, out)
            except Exception as e:
                self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"bootstrap unload failed: {e}")
            return

        if path == "/api/ai-lab/orchestrator/message/stream":
            self._ai_lab_orchestrator_stream(body, scope=self._ai_conversation_scope())
            return

        if path == "/api/ai-lab/orchestrator/message":
            self._ai_lab_orchestrator_sync(
                body, scope=self._ai_conversation_scope(), mirror_to_telegram=True,
            )
            return

        if path == "/api/ai-lab/orchestrator/speak":
            try:
                # Same workspace gate as chat history — TTS is part of the
                # Orchestrator surface, not a public anonymous endpoint.
                scope = self._ai_conversation_scope()
                result = ai_agent_tts.synthesize(
                    str(body.get("text") or body.get("message") or ""),
                    agent_id=str(body.get("agent_id") or body.get("agent") or "vitek"),
                    message_id=str(body.get("message_id") or ""),
                    profile_override=body.get("voice") if isinstance(body.get("voice"), dict) else None,
                    scope=scope,
                )
                self._respond_tts(result)
            except ai_chief_agent.ChiefAgentError as e:
                self._err(HTTPStatus.BAD_REQUEST, str(e))
            except ai_agent_tts.AgentTtsError as e:
                self._err(HTTPStatus.BAD_REQUEST, str(e), code="tts_failed")
            except Exception as e:
                self._err(HTTPStatus.BAD_GATEWAY, f"TTS failed: {e}", code="tts_failed")
            return

        if path == "/api/ai-lab/tts/openai-key":
            if not self._require_owner_actor():
                return
            try:
                action = str(body.get("action") or "save").strip().lower()
                if action in {"clear", "delete", "remove"}:
                    out = ai_agent_tts.clear_openai_tts_key()
                else:
                    out = ai_agent_tts.configure_openai_tts_key(str(body.get("api_key") or body.get("key") or ""))
                self._json(HTTPStatus.OK, out)
            except ai_agent_tts.AgentTtsError as e:
                self._err(HTTPStatus.BAD_REQUEST, str(e), code="tts_key_failed")
            except Exception as e:
                self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"tts key failed: {e}")
            return

        # Staff voice profiles: POST save / reset / preview
        # /api/ai-lab/domain-agents/{id}/voice[/(reset|preview)]
        if path.startswith("/api/ai-lab/domain-agents/") and "/voice" in path:
            parts = [urllib.parse.unquote(p) for p in path.split("/") if p]
            # api ai-lab domain-agents {id} voice [action]
            if len(parts) >= 5 and parts[3] and parts[4] == "voice":
                agent_id = parts[3]
                action = parts[5] if len(parts) >= 6 else "save"
                if not self._require_owner_actor():
                    return
                try:
                    if action == "save":
                        profile = ai_agent_tts.set_voice_profile(agent_id, body if isinstance(body, dict) else {})
                        self._json(HTTPStatus.OK, {"ok": True, "voice": profile})
                    elif action == "reset":
                        profile = ai_agent_tts.reset_voice_profile(agent_id)
                        self._json(HTTPStatus.OK, {"ok": True, "voice": profile})
                    elif action == "preview":
                        override = body.get("voice") if isinstance(body.get("voice"), dict) else body
                        if not isinstance(override, dict):
                            override = None
                        result = ai_agent_tts.preview_speech(
                            agent_id,
                            profile_override=override,
                            scope=self._ai_conversation_scope(),
                        )
                        self._respond_tts(result)
                    else:
                        self._err(HTTPStatus.NOT_FOUND, f"no route: {path}")
                except ai_agent_tts.AgentTtsError as e:
                    self._err(HTTPStatus.BAD_REQUEST, str(e), code="tts_failed")
                except Exception as e:
                    self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"voice action failed: {e}")
                return

        if path.startswith("/api/ai-lab/orchestrator/message/") and path.endswith("/rating"):
            try:
                scope = self._ai_conversation_scope()
                parts = path.strip("/").split("/")
                message_id = urllib.parse.unquote(parts[-2]) if len(parts) >= 6 else ""
                out = ai_chief_agent.rate_message(
                    str(body.get("conversation_id") or "default"),
                    message_id,
                    body.get("rating"),
                    str(body.get("feedback_comment") or body.get("comment") or ""),
                    source=str(body.get("feedback_source") or "owner"),
                    scope=scope,
                )
                self._json(HTTPStatus.OK, out)
            except ai_chief_agent.ChiefAgentError as e:
                self._err(HTTPStatus.BAD_REQUEST, str(e))
            return

        if path.startswith("/api/ai-lab/orchestrator/message/") and path.endswith("/fulfillment"):
            try:
                scope = self._ai_conversation_scope()
                parts = path.strip("/").split("/")
                message_id = urllib.parse.unquote(parts[-2]) if len(parts) >= 6 else ""
                out = ai_chief_agent.set_message_fulfillment(
                    str(body.get("conversation_id") or "default"),
                    message_id,
                    body.get("fulfillment") or body.get("status"),
                    source=str(body.get("fulfillment_source") or body.get("source") or "owner"),
                    scope=scope,
                )
                self._json(HTTPStatus.OK, out)
            except ai_chief_agent.ChiefAgentError as e:
                self._err(HTTPStatus.BAD_REQUEST, str(e))
            return

        if path == "/api/ai-lab/domain-agents/message":
            # Legacy specialist endpoint still enters through the same durable
            # Orchestrator gateway. ``agent_id`` is only a routing hint.
            self._ai_lab_orchestrator_sync(
                body, scope=self._ai_conversation_scope(),
                mirror_to_telegram=bool(body.get("mirror_to_telegram", False)),
            )
            return

        if path == "/api/ai-lab/orchestrator/conversations":
            try:
                scope = self._ai_conversation_scope()
                conv = ai_chief_agent.create_conversation(str(body.get("title") or ""), scope=scope)
                self._json(HTTPStatus.OK, {"ok": True, "conversation": conv})
            except ai_chief_agent.ChiefAgentError as e:
                self._err(HTTPStatus.BAD_REQUEST, str(e))
            return

        if path == "/api/ai-lab/orchestrator/chart-task":
            try:
                scope = self._ai_conversation_scope()
                out = ai_chief_agent.announce_chart_task(
                    conversation_id=str(body.get("conversation_id") or "default"),
                    instruction=str(body.get("instruction") or body.get("message") or ""),
                    agent_id=str(body.get("agent_id") or "ivan"),
                    instrument=str(body.get("instrument") or ""),
                    price=body.get("price"),
                    drawing_type=str(body.get("drawing_type") or body.get("type") or "line"),
                    label=str(body.get("label") or ""),
                    delay_seconds=int(body.get("delay_seconds") or 0),
                    duration_minutes=int(body.get("duration_minutes") or 0),
                    report_mode=str(body.get("report_mode") or "touch"),
                    action=str(body.get("action") or "snapshot"),
                    mirror_to_telegram=bool(body.get("mirror_to_telegram", True)),
                    scope=scope,
                )
                self._json(HTTPStatus.OK, out)
            except (ai_chief_agent.ChiefAgentError, ValueError, TypeError) as e:
                self._err(HTTPStatus.BAD_REQUEST, str(e))
            return

        if path == "/api/ai-lab/orchestrator/conversations/rename":
            try:
                scope = self._ai_conversation_scope()
                conv = ai_chief_agent.rename_conversation(
                    str(body.get("conversation_id") or ""), str(body.get("title") or ""),
                    scope=scope,
                )
                self._json(HTTPStatus.OK, {"ok": True, "conversation": conv})
            except ai_chief_agent.ChiefAgentError as e:
                self._err(HTTPStatus.BAD_REQUEST, str(e))
            return

        if path == "/api/ai-lab/orchestrator/conversations/pin":
            try:
                scope = self._ai_conversation_scope()
                conv = ai_chief_agent.pin_conversation(
                    str(body.get("conversation_id") or ""), bool(body.get("pinned", True)),
                    scope=scope,
                )
                self._json(HTTPStatus.OK, {"ok": True, "conversation": conv})
            except ai_chief_agent.ChiefAgentError as e:
                self._err(HTTPStatus.BAD_REQUEST, str(e))
            return

        if path == "/api/ai-lab/orchestrator/conversations/state":
            try:
                scope = self._ai_conversation_scope()
                state = str(body.get("state") or "").strip().lower()
                if state not in {"closed", "open"}:
                    raise ai_chief_agent.ChiefAgentError("state должен быть open или closed.")
                conv = ai_chief_agent.set_conversation_closed(
                    str(body.get("conversation_id") or "default"), state == "closed",
                    scope=scope,
                )
                self._json(HTTPStatus.OK, {"ok": True, "conversation": conv})
            except ai_chief_agent.ChiefAgentError as e:
                self._err(HTTPStatus.BAD_REQUEST, str(e))
            return

        if path == "/api/ai-lab/orchestrator/conversations/delete":
            try:
                scope = self._ai_conversation_scope()
                out = ai_chief_agent.delete_conversation(str(body.get("conversation_id") or ""), scope=scope)
                self._json(HTTPStatus.OK, out)
            except ai_chief_agent.ChiefAgentError as e:
                self._err(HTTPStatus.BAD_REQUEST, str(e))
            return

        if path == "/api/ai-lab/chief-agent/mission":
            try:
                mission_body = {
                    **body,
                    "conversation_scope": self._ai_conversation_scope(),
                }
                self._json(
                    HTTPStatus.OK,
                    {"ok": True, "mission": ai_chief_agent.start_mission(mission_body)},
                )
            except (ValueError, TypeError, ai_chief_agent.ChiefAgentError) as e:
                self._err(HTTPStatus.BAD_REQUEST, str(e))
            return

        if path == "/api/ai-lab/chief-agent/mission/state":
            try:
                self._json(HTTPStatus.OK, {"ok": True, "mission": ai_chief_agent.set_mission_state(
                    str(body.get("action") or ""), scope=self._ai_conversation_scope(),
                )})
            except ai_chief_agent.ChiefAgentError as e:
                self._err(HTTPStatus.BAD_REQUEST, str(e))
            return

        if path == "/api/ai-lab/chief-agent/tasks":
            try:
                task_body = {
                    **body,
                    "conversation_scope": self._ai_conversation_scope(),
                }
                self._json(
                    HTTPStatus.OK,
                    {"ok": True, "task": ai_chief_agent.add_task(task_body)},
                )
            except ai_chief_agent.ChiefAgentError as e:
                self._err(HTTPStatus.BAD_REQUEST, str(e))
            return

        if path == "/api/ai-lab/chief-agent/notes":
            try:
                note = ai_chief_agent.add_note(str(body.get("text") or ""), str(body.get("priority") or "normal"))
                self._json(HTTPStatus.OK, {"ok": True, "note": note})
            except ai_chief_agent.ChiefAgentError as e:
                self._err(HTTPStatus.BAD_REQUEST, str(e))
            return

        if path == "/api/ai-lab/chief-agent/audit":
            try:
                report = ai_chief_agent.audit_recent_backtests(
                    use_llm=bool(body.get("use_llm", True)),
                    send_telegram=bool(body.get("send_telegram", False)),
                    scope=self._ai_conversation_scope(),
                )
                self._json(HTTPStatus.OK, {"ok": True, "report": report})
            except (ai_chief_agent.ChiefAgentError, ai_agent_router.AgentRouterError) as e:
                self._err(HTTPStatus.BAD_REQUEST, str(e))
            return

        if path == "/api/ai-lab/chief-agent/proposals":
            try:
                proposal = ai_chief_agent.propose_action(
                    str(body.get("action") or ""),
                    body.get("payload") if isinstance(body.get("payload"), dict) else {},
                    str(body.get("reason") or ""),
                    scope=self._ai_conversation_scope(),
                )
                self._json(HTTPStatus.OK, {"ok": True, "proposal": proposal})
            except ai_chief_agent.ChiefAgentError as e:
                self._err(HTTPStatus.BAD_REQUEST, str(e))
            return

        if path == "/api/ai-lab/chief-agent/proposals/decision":
            if not self._require_owner_actor():
                return
            try:
                proposal = ai_chief_agent.decide_proposal(
                    str(body.get("proposal_id") or ""),
                    str(body.get("decision") or ""),
                    scope=self._ai_conversation_scope(),
                )
                self._json(HTTPStatus.OK, {"ok": True, "proposal": proposal})
            except (ai_chief_agent.ChiefAgentError, ops.OpsError) as e:
                self._err(HTTPStatus.BAD_REQUEST, str(e))
            return

        if path == "/api/ai-lab/run":
            try:
                research_id = str(body.get("research_id") or "").strip()
                selected_research: Dict[str, Any] = {}
                if research_id:
                    selected_research = ai_research_catalog.run_context(research_id)
                user_goal = str(body.get("goal") or body.get("user_goal") or "").strip()
                if selected_research:
                    user_goal = (selected_research["context"] + (
                        "\n\nCURRENT CYCLE INSTRUCTIONS:\n" + user_goal if user_goal else ""
                    ))[:12_000]
                capital_value = body.get("capital")
                if capital_value in (None, ""):
                    capital_value = body.get("user_capital")
                # New schema (preferred): strategy_count + iterations_per_strategy.
                # Legacy aliases (max_cells_per_run, max_mutations_per_cell) still
                # accepted; runner.start() normalizes them.
                strategy_count_raw = body.get("strategy_count")
                if strategy_count_raw in (None, ""):
                    strategy_count_raw = body.get("max_cells_per_run", 1)
                iterations_raw = body.get("iterations_per_strategy")
                iterations_unlimited = bool(body.get("iterations_unlimited", False))
                if iterations_raw in (None, "") and not iterations_unlimited:
                    legacy_mut = body.get("max_mutations_per_cell")
                    if legacy_mut in (None, ""):
                        iterations_raw = 3  # new sane default
                    else:
                        iterations_raw = max(1, int(legacy_mut) + 1)
                raw_runtime = body.get("max_total_runtime_minutes")
                # New ceiling: 1440 min (24h). 0 means unlimited.
                if raw_runtime in (None, "", 0):
                    normalized_runtime = None
                else:
                    normalized_runtime = max(1, min(1440, int(raw_runtime)))

                args = {
                    "user_pref_root": (
                        body.get("target_root") or body.get("root")
                        or body.get("user_pref_root") or body.get("instrument_root") or None
                    ),
                    "user_capital": (float(capital_value) if capital_value not in (None, "") else None),
                    "user_goal": user_goal or None,
                    "research_id": research_id,
                    "research_title": selected_research.get("research_title"),
                    "research_family_name": selected_research.get("family_name"),
                    "research_family_key": selected_research.get("family_key"),
                    "research_knowledge_ref": selected_research.get("knowledge_rel_path"),
                    "dry_run": bool(body.get("dry_run", False)),
                    "skip_compile": bool(body.get("skip_compile", False)),
                    "skip_backtest": bool(body.get("skip_backtest", False)),
                    "use_llm": bool(body.get("use_llm", True)),
                    "allow_template_fallback": bool(body.get("allow_template_fallback", False)),
                    "verify_poll_sec": int(body.get("verify_poll_sec", 0)),
                    "research_mode": body.get("research_mode") or "research_until_candidate_or_budget_exhausted",
                    "strategy_count": max(1, min(10, int(strategy_count_raw))),
                    "iterations_per_strategy": (
                        None if iterations_unlimited else max(1, min(20, int(iterations_raw)))
                    ),
                    "iterations_unlimited": iterations_unlimited,
                    "max_compile_fix_attempts_per_cell": max(1, min(10, int(body.get("max_compile_fix_attempts_per_cell", 5)))),
                    "max_total_runtime_minutes": normalized_runtime,
                    "stop_on_first_candidate": bool(body.get("stop_on_first_candidate", False)),
                    "target_candidate_count": max(1, min(5, int(body.get("target_candidate_count", 1)))),
                    "backtest_instrument": body.get("backtest_instrument") or body.get("instrument"),
                    "smoke_days": max(14, min(45, int(body.get("smoke_days", 30)))),
                    "smoke_timeout_sec": max(30, min(1800, int(body.get("smoke_timeout_sec", 180)))),
                    "min_signal_sanity": max(1, min(100, int(body.get("min_signal_sanity", 8)))),
                }
                conversation_scope = self._ai_conversation_scope()
                args.update({
                    "user_id": conversation_scope.get("user_id"),
                    "user_name": conversation_scope.get("display_name"),
                    "workspace_id": conversation_scope.get("workspace_id"),
                    "conversation_id": str(body.get("conversation_id") or "default"),
                    "conversation_scope": conversation_scope,
                })
            except ai_research_catalog.ResearchCatalogError as e:
                self._err(HTTPStatus.BAD_REQUEST, str(e))
                return
            except (TypeError, ValueError) as e:
                self._err(HTTPStatus.BAD_REQUEST, f"invalid run parameters: {e}")
                return
            try:
                out = ai_runner.start(args)
                self._json(HTTPStatus.OK, {"ok": True, **out})
            except ai_runner.RunBlockedLMStudio as e:
                self._json(HTTPStatus.CONFLICT,
                           {"ok": False, "blocked_lm_studio": True,
                            "preflight": e.preflight,
                            "hint": ("LM Studio preflight failed. Start LM Studio with the "
                                     "configured judge+coder models, or pass "
                                     "allow_template_fallback=true to proceed with the "
                                     "non-LLM template (research only).")})
            except ai_runner.RunScopeRequired as e:
                self._err(
                    HTTPStatus.BAD_REQUEST, str(e),
                    code="production_ai_scope_required",
                )
            except ai_runner.RunnerBusy as e:
                self._json(HTTPStatus.CONFLICT,
                           {"ok": False, "busy": True, "current": e.current})
            except Exception as e:
                self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"run failed: {e}")
            return

        if path == "/api/ai-lab/cancel":
            exp_id = body.get("experiment_id")
            if not exp_id:
                self._err(HTTPStatus.BAD_REQUEST, "experiment_id required")
                return
            try:
                self._json(
                    HTTPStatus.OK,
                    ai_runner.request_cancel(
                        exp_id, scope=self._ai_conversation_scope(),
                    ),
                )
            except Exception as e:
                self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"cancel failed: {e}")
            return

        if path == "/api/ai-lab/run/cancel":
            run_id = body.get("run_id")
            try:
                self._json(
                    HTTPStatus.OK,
                    ai_runner.request_run_cancel(
                        run_id, scope=self._ai_conversation_scope(),
                    ),
                )
            except Exception as e:
                self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"run cancel failed: {e}")
            return

        if path == "/api/ai-lab/maintenance/sweep-stale":
            try:
                ttl = float(body.get("heartbeat_ttl_hours") or 6.0)
                out = ai_stale_sweep.sweep_stale(heartbeat_ttl_hours=ttl)
                self._json(HTTPStatus.OK, out)
            except Exception as e:
                self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"sweep failed: {e}")
            return

        if path == "/api/ai-lab/lessons":
            text = str(body.get("text") or body.get("summary") or "").strip()
            if not text:
                self._err(HTTPStatus.BAD_REQUEST, "text required")
                return
            scope = str(body.get("scope") or "global")
            scope_key = body.get("scope_key")
            rule = body.get("rule")
            source = str(body.get("source") or "user_research")
            try:
                rec = ai_lessons.record_lesson(
                    summary=text, source=source,
                    scope=scope, scope_key=scope_key, rule=rule,
                )
                self._json(HTTPStatus.OK, {"ok": True, "lesson": rec})
            except ValueError as e:
                self._err(HTTPStatus.BAD_REQUEST, str(e))
            except Exception as e:
                self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"lesson save failed: {e}")
            return

        if path == "/api/ai-lab/operator-notes/global":
            text = str(body.get("text") or "").strip()
            if not text:
                self._err(HTTPStatus.BAD_REQUEST, "text required")
                return
            priority = str(body.get("priority") or "high")
            try:
                rec = ai_operator_notes.promote_to_global(
                    text=text, priority=priority,
                    source_experiment_id=body.get("experiment_id"),
                    trigger="ui_manual",
                )
                self._json(HTTPStatus.OK, {"ok": True, "note": rec})
            except Exception as e:
                self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"global note failed: {e}")
            return

        # /api/ai-lab/experiments/{id}/resume-compile
        parts = [p for p in path.split("/") if p]
        if (len(parts) == 5 and parts[1] == "ai-lab" and parts[2] == "experiments"
                and parts[4] == "cancel"):
            exp_id = parts[3]
            try:
                self._json(
                    HTTPStatus.OK,
                    ai_runner.request_cancel(
                        exp_id, scope=self._ai_conversation_scope(),
                    ),
                )
            except Exception as e:
                self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"cancel failed: {e}")
            return

        if (len(parts) == 5 and parts[1] == "ai-lab" and parts[2] == "experiments"
                and parts[4] == "notes"):
            exp_id = parts[3]
            text = str(body.get("text") or "").strip()
            if not text:
                self._err(HTTPStatus.BAD_REQUEST, "text required")
                return
            priority = str(body.get("priority") or "normal")
            try:
                entry = ai_operator_notes.add(exp_id, text, priority=priority)
                try:
                    ai_activity.log(
                        exp_id, "runner", "operator_note_received", level="info",
                        text_preview=text[:80], priority=priority,
                    )
                except Exception:
                    pass
                self._json(HTTPStatus.OK, {"ok": True, "index": entry.get("index"), "entry": entry})
            except Exception as e:
                self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"note failed: {e}")
            return

        if (len(parts) == 6 and parts[1] == "ai-lab" and parts[2] == "experiments"
                and parts[4] == "compile-errors" and parts[5] == "paste"):
            exp_id = parts[3]
            class_name = str(body.get("class_name") or "").strip()
            text = str(body.get("text") or "")
            if not class_name or not text.strip():
                self._err(HTTPStatus.BAD_REQUEST, "class_name and text required")
                return
            try:
                count = ai_compile_errors.append_manual(exp_id, class_name, text)
                try:
                    ai_activity.log(
                        exp_id, "compile", "errors_manual_paste",
                        level="warn", count=count, class_name=class_name,
                    )
                except Exception:
                    pass
                self._json(HTTPStatus.OK, {"ok": True, "count": count})
            except Exception as e:
                self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"paste failed: {e}")
            return

        if (len(parts) == 6 and parts[1] == "ai-lab" and parts[2] == "experiments"
                and parts[4] == "portfolio"):
            exp_id = parts[3]
            raw_action = parts[5].replace("-", "_")
            action_map = {
                "candidate": "candidate",
                "approve": "approve",
                "approved": "approve",
                "promote": "promote",
                "promoted": "promote",
                "paper_ready": "paper_ready",
                "remove": "remove",
            }
            action = action_map.get(raw_action)
            if not action:
                self._err(HTTPStatus.BAD_REQUEST, f"invalid portfolio action: {raw_action}")
                return
            approved_by = str(body.get("approved_by") or body.get("operator") or "ui")
            try:
                exp = ai_registry.set_portfolio_membership(
                    exp_id, action=action, approved_by=approved_by,
                )
                try:
                    ai_activity.log(
                        exp_id, "portfolio", action, level="success",
                        portfolio=exp.get("portfolio") or {},
                    )
                except Exception:
                    pass
                self._json(HTTPStatus.OK, {
                    "ok": True,
                    "experiment": ai_read_model.experiment_row(exp),
                })
            except ValueError as e:
                self._err(HTTPStatus.BAD_REQUEST, str(e))
            except Exception as e:
                self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"portfolio action failed: {e}")
            return

        if (len(parts) == 5 and parts[1] == "ai-lab" and parts[2] == "experiments"
                and parts[4] == "resume-compile"):
            exp_id = parts[3]
            exp = ai_registry.read_experiment(exp_id)
            if not exp:
                self._err(HTTPStatus.NOT_FOUND, f"experiment not found: {exp_id}")
                return
            if exp.get("status") != "awaiting_compile_timeout":
                self._err(HTTPStatus.BAD_REQUEST,
                          f"cannot resume from status {exp.get('status')}")
                return
            try:
                ai_registry.transition_status(exp_id, "awaiting_compile",
                                              reason="user requested extension")
                args = {"skip_compile": False, "skip_backtest": bool(body.get("skip_backtest", False))}
                # Best-effort re-entry: kick a new runner cycle that re-enters compile only.
                # Simpler: just transition; the bridge will refresh on next F5.
                self._json(HTTPStatus.OK, {"ok": True, "status": "awaiting_compile"})
            except Exception as e:
                self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"resume failed: {e}")
            return

        if path == "/api/ai-lab/finalize":
            exp_id = body.get("experiment_id")
            job_id = body.get("job_id")
            if not exp_id or not job_id:
                self._err(HTTPStatus.BAD_REQUEST, "experiment_id and job_id required")
                return
            try:
                result = ai_orchestrator.finalize_backtest(exp_id, job_id)
                self._json(HTTPStatus.OK, result)
            except Exception as e:
                self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"finalize failed: {e}")
            return

        if path == "/api/ai-lab/user-research/scan":
            try:
                from .ai_lab import user_research as ur  # type: ignore
            except Exception:
                from app.ai_lab import user_research as ur  # type: ignore
            try:
                self._json(HTTPStatus.OK, ur.scan())
            except Exception as e:
                self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"scan failed: {e}")
            return

        self._err(HTTPStatus.NOT_FOUND, f"no ai-lab POST route: {path}")

    # ------------- /api/ops/* POST dispatcher -------------------------------

    def _ops_post(self, path: str, body: Dict[str, Any]) -> None:
        parts = [p for p in path.split("/") if p]
        if path == "/api/ops/runtime/bars/batch":
            rows = body.get("requests") if isinstance(body.get("requests"), list) else []
            if len(rows) > 64:
                self._err(HTTPStatus.BAD_REQUEST, "Не более 64 графиков в одном пакете."); return
            result = []
            try:
                production_mode = _server_environment_explicit()
                if not production_mode and not market_data_failover.TopstepXProvider().configured():
                    market_data.register_requests(row for row in rows if isinstance(row, dict))
                normalized_rows: list[Dict[str, Any]] = []
                work_points = 0
                oversized = False
                for raw in rows:
                    if not isinstance(raw, dict):
                        continue
                    limit_value = max(1, min(50000, int(raw.get("limit") or 1500)))
                    max_value = max(0, min(20000, int(raw.get("max_points") or 0)))
                    effective = min(limit_value, max_value if max_value >= 3 else limit_value)
                    work_points += effective
                    oversized = oversized or effective > 10000
                    normalized_rows.append({
                        "instrument": str(raw.get("instrument") or ""),
                        "timeframe": str(raw.get("timeframe") or "5m"),
                        "limit": limit_value,
                        "range_days": int(raw.get("range_days") or 0),
                        "from": str(raw.get("from") or ""),
                        "to": str(raw.get("to") or ""),
                        "from_ts": str(raw.get("from_ts") or ""),
                        "to_ts": str(raw.get("to_ts") or ""),
                        "max_points": max_value,
                    })
                context = getattr(self, "_remote_context", None) or {}
                if oversized or work_points > 100000:
                    queued = self._run_large_chart_batch(normalized_rows, context)
                    if queued is None:
                        return
                    if not production_mode:
                        market_data.evaluate_alerts()
                    self._json(HTTPStatus.OK, {"series": queued})
                    return
                # Read the bridge snapshot and alerts ONCE for the whole batch —
                # a 64-chart grid must not re-parse market_bars.json/price_alerts.json
                # once per instrument on every poll tick.
                workspace_id = str(context.get("workspace_id") or "")
                snapshot_index = None if production_mode else market_data.read_snapshot_index()
                alerts_index = None if production_mode else market_data.read_alerts_index()
                connector_snapshot_index = (
                    market_data_ingestion.workspace_snapshot_index(workspace_id)
                    if production_mode and workspace_id else None
                )
                batch_cache: Dict[Tuple[str, str, int, int, str, str, str, str, int], Dict[str, Any]] = {}
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    req_key = (
                        str(row.get("instrument") or ""),
                        str(row.get("timeframe") or "5m"),
                        int(row.get("limit") or 1500),
                        int(row.get("range_days") or 0),
                        str(row.get("from") or ""),
                        str(row.get("to") or ""),
                        str(row.get("from_ts") or ""),
                        str(row.get("to_ts") or ""),
                        int(row.get("max_points") or 0),
                    )
                    payload = batch_cache.get(req_key)
                    if payload is None:
                        payload = _market_bars_payload(
                            req_key[0], req_key[1], req_key[2], req_key[3], req_key[4], req_key[5],
                            register=False, snapshot_index=snapshot_index, alerts_index=alerts_index,
                            max_points=req_key[8], workspace_id=workspace_id,
                            connector_snapshot_index=connector_snapshot_index,
                            from_ts=req_key[6], to_ts=req_key[7],
                        )
                        batch_cache[req_key] = payload
                    result.append(payload)
                if not production_mode:
                    market_data.evaluate_alerts()
            except (market_data.MarketDataError, TypeError, ValueError) as exc:
                self._err(HTTPStatus.BAD_REQUEST, str(exc)); return
            self._json(HTTPStatus.OK, {"series": result}); return
        if path == "/api/ops/runtime/price-alerts":
            try:
                self._json(HTTPStatus.OK, market_data.create_alert(body)); return
            except market_data.MarketDataError as exc:
                self._err(HTTPStatus.BAD_REQUEST, str(exc)); return
        if path == "/api/ops/runtime/chart-commands/ack":
            out = market_data.ack_chart_command(
                str(body.get("id") or ""),
                status=str(body.get("status") or "done"),
                result=body.get("result") if isinstance(body.get("result"), dict) else None,
            )
            self._json(HTTPStatus.OK, out); return
        if path == "/api/ops/runtime/snapshots/update":
            out = market_data.update_snapshot(
                str(body.get("id") or ""),
                favorite=body.get("favorite") if isinstance(body.get("favorite"), bool) else None,
                pattern=body.get("pattern") if body.get("pattern") is not None else None,
                caption=body.get("caption") if body.get("caption") is not None else None,
            )
            self._json(HTTPStatus.OK, out); return
        if path == "/api/ops/runtime/snapshots/clear":
            keep_favorites = bool(body.get("keep_favorites", True))
            self._json(HTTPStatus.OK, market_data.clear_snapshots(keep_favorites=keep_favorites)); return
        if path == "/api/ops/runtime/chart-snapshot":
            saved = None
            if str(body.get("image") or "").strip():
                try:
                    saved = market_data.save_snapshot(body.get("image"), meta={
                        "instrument": str(body.get("instrument") or ""),
                        "timeframe": str(body.get("timeframe") or ""),
                        "outcome": str(body.get("outcome") or ""),
                    })
                except market_data.MarketDataError as exc:
                    self._err(HTTPStatus.BAD_REQUEST, str(exc)); return
            conversation_id = str(body.get("conversation_id") or "").strip()
            report = None
            if conversation_id:
                text = str(body.get("text") or "Снимок графика.").strip()[:2000]
                try:
                    scope = self._ai_conversation_scope()
                    report = ai_chief_agent.report_chart_snapshot(
                        conversation_id=conversation_id, text=text,
                        image_url=(saved or {}).get("url") or "",
                        image_file=(saved or {}).get("file") or "",
                        caption=str(body.get("caption") or "")[:400],
                        mirror_to_telegram=bool(body.get("mirror_to_telegram", True)),
                        scope=scope,
                    )
                except Exception as exc:  # pragma: no cover - reporting is best-effort
                    report = {"ok": False, "error": str(exc)[:300]}
            self._json(HTTPStatus.OK, {"ok": True, "snapshot": saved, "report": report}); return
        # /api/ops/live/unlock-request
        if path == "/api/ops/live/unlock-request":
            out = ops.request_live_unlock(reason=str(body.get("reason") or ""))
            self._json(HTTPStatus.FORBIDDEN, out)
            return
        # /api/ops/runtime/command  (paper/demo/playback runtime command queue)
        if path == "/api/ops/runtime/command":
            try:
                out = ops_runtime.submit_command(
                    command=str(body.get("command") or ""),
                    strategy_id=str(body.get("strategy_id") or ""),
                    account_name=str(body.get("account_name") or ""),
                    quantity=body.get("quantity") or 1,
                    reason=str(body.get("reason") or ""),
                    operator=str(body.get("operator") or "ui"),
                    class_name=str(body.get("class_name") or ""),
                    instrument=str(body.get("instrument") or ""),
                    contract_month=str(body.get("contract_month") or ""),
                    timeframe=str(body.get("timeframe") or ""),
                    runtime_instance_id=str(body.get("runtime_instance_id") or ""),
                    params=body.get("params") if isinstance(body.get("params"), dict) else None,
                    connection_name=str(body.get("connection_name") or ""),
                )
                self._json(HTTPStatus.OK, out); return
            except ops.OpsError as e:
                self._err(e.status, str(e)); return
            except Exception as e:  # pragma: no cover
                self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"command error: {e}"); return
        if path == "/api/ops/runtime/strategy-display":
            try:
                out = ops_runtime.set_strategy_display_hidden(
                    class_name=str(body.get("class_name") or ""),
                    hidden=bool(body.get("hidden")),
                )
                self._json(HTTPStatus.OK, out); return
            except ops.OpsError as e:
                self._err(e.status, str(e)); return
            except Exception as e:  # pragma: no cover
                self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"display prefs error: {e}"); return
        # /api/profiles/archive/remove-from-nt  (batch or single via {"profile_id": ...})
        if parts == ["api", "profiles", "archive", "remove-from-nt"]:
            try:
                pid = str(body.get("profile_id") or "").strip() or None
                self._json(HTTPStatus.OK, jobqueue.remove_archived_from_ninjatrader(pid)); return
            except jobqueue.JobValidationError as e:
                self._err(HTTPStatus.BAD_REQUEST, str(e)); return
            except Exception as e:  # pragma: no cover
                self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"nt removal error: {e}"); return
        # /api/profiles/ninjatrader/cleanup  — keep only approved strategies in NT.
        if parts == ["api", "profiles", "ninjatrader", "cleanup"]:
            try:
                dry_run = bool(body.get("dry_run", True))
                include_ai = bool(body.get("include_ai_sandbox", True))
                include_ref = bool(body.get("include_ref_lib", True))
                self._json(HTTPStatus.OK, jobqueue.cleanup_ninjatrader_to_approved(
                    dry_run=dry_run, include_ai_sandbox=include_ai, include_ref_lib=include_ref)); return
            except Exception as e:  # pragma: no cover
                self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"nt cleanup error: {e}"); return
        # /api/ops/profiles/{profile_id}/{update|delete}
        if len(parts) == 5 and parts[0] == "api" and parts[1] == "ops" and parts[2] == "profiles":
            profile_id = urllib.parse.unquote(parts[3])
            action = parts[4]
            try:
                if action == "update":
                    updates = body.get("updates") if isinstance(body.get("updates"), dict) else {}
                    self._json(HTTPStatus.OK, jobqueue.update_strategy_profile(
                        profile_id,
                        updates,
                        action=str(body.get("action") or "update"),
                    )); return
                if action == "delete":
                    self._json(HTTPStatus.OK, jobqueue.delete_strategy_profile(profile_id)); return
            except jobqueue.JobValidationError as e:
                self._err(HTTPStatus.BAD_REQUEST, str(e)); return
            except Exception as e:  # pragma: no cover
                self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"profile update error: {e}"); return
        # /api/ops/strategies/{id}/{action}[/{sub}]
        if len(parts) >= 5 and parts[0] == "api" and parts[1] == "ops" and parts[2] == "strategies":
            sid = parts[3]
            action = "/".join(parts[4:])
            reason = str(body.get("reason") or "")
            try:
                if action == "paper/arm":
                    self._json(HTTPStatus.OK, ops.arm(sid, reason)); return
                if action == "paper/start-intent":
                    self._json(HTTPStatus.OK, ops.start_intent(sid, reason)); return
                if action == "paper/stop-intent":
                    self._json(HTTPStatus.OK, ops.stop_intent(sid, reason)); return
                if action == "paper/confirm-manual":
                    a = str(body.get("action") or "")
                    self._json(HTTPStatus.OK, ops.confirm_manual(sid, a, reason)); return
                if action == "paper/pause":
                    self._json(HTTPStatus.OK, ops.pause(sid, reason)); return
                if action == "paper/resume":
                    self._json(HTTPStatus.OK, ops.resume(sid, reason)); return
                if action == "paper/stop-today":
                    self._json(HTTPStatus.OK, ops.stop_today(sid, reason)); return
                if action == "paper/mark-passed":
                    self._json(HTTPStatus.OK, ops.mark_paper_passed(sid, reason)); return
                if action == "paper/evaluate-review":
                    self._json(HTTPStatus.OK, ops.evaluate_review_due(sid)); return
                if action == "journal/day":
                    self._json(HTTPStatus.OK, ops.append_journal_day(sid, body.get("row") or {})); return
                if action == "journal/autofill":
                    on_date = body.get("date_pt")
                    dry = bool(body.get("dry_run"))
                    self._json(HTTPStatus.OK,
                               ops_runtime.journal_autofill(sid, on_date, dry)); return
                if action == "runtime/confirm-started":
                    self._json(HTTPStatus.OK,
                               ops_runtime.confirm_runtime(sid, "started", reason)); return
                if action == "runtime/confirm-stopped":
                    self._json(HTTPStatus.OK,
                               ops_runtime.confirm_runtime(sid, "stopped", reason)); return
                if action == "notes":
                    self._json(HTTPStatus.OK, ops.append_note(sid, str(body.get("text") or ""))); return
            except ops.OpsError as e:
                self._err(e.status, str(e)); return
            except Exception as e:  # pragma: no cover
                self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"ops error: {e}"); return
        self._err(HTTPStatus.NOT_FOUND, f"no ops route: {path}")

    def _has_governance_read_privilege(self) -> bool:
        """Journal / owner-metadata reads are limited to owner or docs admins."""
        context = getattr(self, "_remote_context", None) or {}
        if context.get("is_owner"):
            return True
        caps = permissions.resolve_admin_capabilities(context.get("user") or {})
        if isinstance(caps, dict) and (caps.get("docs.manage_global") or caps.get("docs.manage_workspace")):
            return True
        return False

    def _governance_actor(self) -> Dict[str, str]:
        """Derive the amendment author from the authenticated session.

        A human editing through the app is always attributed to their own
        account. A localhost AI/dev service identity is fixed by its authenticated
        service account; neither author nor initiator is accepted from request data.
        """
        context = getattr(self, "_remote_context", None) or {}
        user = context.get("user") if isinstance(context.get("user"), dict) else {}
        is_service = bool(
            context.get("source") == "dev_service"
            or context.get("service_actor")
            or user.get("is_service_account")
        )
        if is_service:
            service_actor = str(
                context.get("service_actor")
                or dev_service_accounts.actor_for_uid(context.get("user_id"))
                or ""
            )
            spec = dev_service_accounts.SERVICE_ACCOUNTS.get(
                service_actor, {}
            )
            agent = str(spec.get("label") or "AI · служебный (dev)")
            return {
                "actor": agent,
                "author": agent,
                "author_id": f"service:{service_actor}",
                "author_kind": "ai",
                "initiator": governance.PROJECT_OWNER,
            }
        name = " ".join(
            str(part).strip()
            for part in (user.get("first_name"), user.get("last_name"))
            if str(part or "").strip()
        ).strip()
        display = name or str(user.get("username") or "").strip()
        if not display:
            display = governance.PROJECT_OWNER if context.get("is_owner") else f"user {context.get('user_id') or '—'}"
        author_id = str(user.get("user_uuid") or context.get("user_uuid") or context.get("user_id") or "")
        return {
            "actor": display,
            "author": display,
            "author_id": author_id,
            "author_kind": "human",
            "initiator": "",
        }

    def _require_governance_manage(self) -> bool:
        """Global governance mutations require owner or ``docs.manage_global``.

        GET reads stay at the read-level ``documents`` capability; only writes to
        the single global governance store (laws / markdown documents) are
        restricted. There is no workspace-scoped governance store, and strategy
        profile updates cannot reach governance, so this closes the last gap in
        the Phase 10 invariant: global governance can never be modified by a
        workspace or strategy override, only by the owner (or an explicitly
        delegated ``docs.manage_global`` administrator).
        """
        context = getattr(self, "_remote_context", None) or {}
        if context.get("is_owner"):
            return True
        caps = permissions.resolve_admin_capabilities(context.get("user") or {})
        if isinstance(caps, dict) and caps.get("docs.manage_global"):
            return True
        self._err(
            HTTPStatus.FORBIDDEN,
            "Изменение глобального управления доступно только владельцу или администратору с правом docs.manage_global.",
            code="governance_manage_required",
        )
        return False

    def _governance_post(self, path: str, body: Dict[str, Any]) -> None:
        if not self._require_governance_manage():
            return
        parts = [p for p in path.split("/") if p]
        if len(parts) == 4 and parts[0] == "api" and parts[1] == "governance":
            if parts[2] == "laws":
                law_id = urllib.parse.unquote(parts[3])
                identity = self._governance_actor()
                try:
                    result = governance.update_law(
                        law_id,
                        body if isinstance(body, dict) else {},
                        actor=identity["actor"],
                        author=identity["author"],
                        author_id=identity["author_id"],
                        author_kind=identity["author_kind"],
                        initiator=identity["initiator"],
                    )
                except KeyError as e:
                    self._err(HTTPStatus.NOT_FOUND, str(e)); return
                except ValueError as e:
                    self._err(HTTPStatus.BAD_REQUEST, str(e)); return
                except Exception as e:
                    self._err(HTTPStatus.INTERNAL_SERVER_ERROR,
                              f"governance law update failed: {e}"); return
                self._json(HTTPStatus.OK, result); return
            if parts[2] == "documents":
                doc_id = urllib.parse.unquote(parts[3])
                identity = self._governance_actor()
                try:
                    result = governance.update_markdown_document(
                        doc_id,
                        str(body.get("content") or ""),
                        actor=identity["actor"],
                        reason=str(body.get("reason") or ""),
                        author=identity["author"],
                        author_id=identity["author_id"],
                        author_kind=identity["author_kind"],
                        initiator=identity["initiator"],
                    )
                except KeyError as e:
                    self._err(HTTPStatus.NOT_FOUND, str(e)); return
                except ValueError as e:
                    self._err(HTTPStatus.BAD_REQUEST, str(e)); return
                except Exception as e:
                    self._err(HTTPStatus.INTERNAL_SERVER_ERROR,
                              f"governance document update failed: {e}"); return
                self._json(HTTPStatus.OK, result); return
        self._err(HTTPStatus.NOT_FOUND, f"no governance route: {path}")

    def _route_delete(self) -> None:
        """DELETE /api/jobs/<id>, /api/batches/<id>, or report favorite refs."""
        url = urllib.parse.urlparse(self.path)
        path = url.path
        parts = [p for p in path.split("/") if p]

        if not self._authorize_api(path):
            return

        is_del_job   = (len(parts) == 3 and parts[0] == "api"
                        and parts[1] == "jobs")
        is_del_batch = (len(parts) == 3 and parts[0] == "api"
                        and parts[1] == "batches")
        is_del_favorite = (len(parts) == 4 and parts[0] == "api"
                           and parts[1] == "report-favorites")
        is_del_price_alert = (len(parts) == 5 and parts[:4] ==
                              ["api", "ops", "runtime", "price-alerts"])
        is_del_snapshot = (len(parts) == 5 and parts[:4] ==
                           ["api", "ops", "runtime", "snapshots"])

        if not (is_del_job or is_del_batch or is_del_favorite or is_del_price_alert or is_del_snapshot):
            self._err(HTTPStatus.NOT_FOUND, f"no DELETE route: {path}")
            return

        if not self._check_local_origin():
            return

        if is_del_favorite:
            if not jobqueue.report_in_scope(
                    parts[2], parts[3], **self._data_scope()):
                self._err(HTTPStatus.NOT_FOUND, "report not found")
                return
            try:
                out = jobqueue.unfavorite_report(parts[2], parts[3])
            except jobqueue.JobValidationError as e:
                self._err(HTTPStatus.BAD_REQUEST, str(e))
                return
            self._json(HTTPStatus.OK, out)
            return

        if is_del_price_alert:
            try:
                out = market_data.delete_alert(urllib.parse.unquote(parts[4]))
            except market_data.MarketDataError as exc:
                self._err(HTTPStatus.BAD_REQUEST, str(exc)); return
            self._json(HTTPStatus.OK if out.get("deleted") else HTTPStatus.NOT_FOUND, out)
            return

        if is_del_snapshot:
            out = market_data.delete_snapshot(urllib.parse.unquote(parts[4]))
            self._json(HTTPStatus.OK if out.get("deleted") else HTTPStatus.NOT_FOUND, out)
            return

        if is_del_job:
            try:
                jobqueue._safe_job_id(parts[2])
            except jobqueue.JobValidationError as e:
                self._err(HTTPStatus.BAD_REQUEST, str(e))
                return
            if not jobqueue.job_in_scope(parts[2], **self._data_scope()):
                self._err(HTTPStatus.NOT_FOUND, f"job not found: {parts[2]}")
                return
            result = jobqueue.delete_job(parts[2])
            if not result.get("deleted"):
                reason = result.get("reason", "unknown")
                if reason == "not_found":
                    self._err(HTTPStatus.NOT_FOUND, f"job not found: {parts[2]}")
                elif reason == "running":
                    self._err(HTTPStatus.CONFLICT,
                              "Нельзя удалить запущенный job; сначала отмените.")
                elif reason in ("favorite", "favorite_parent_batch"):
                    self._err(HTTPStatus.CONFLICT,
                              "Отчёт находится в избранном. Сначала снимите звезду.")
                else:
                    self._err(HTTPStatus.INTERNAL_SERVER_ERROR, reason)
                return
            self._json(HTTPStatus.OK, result)
            return

        # is_del_batch
        try:
            jobqueue._safe_batch_id(parts[2])
        except jobqueue.JobValidationError as e:
            self._err(HTTPStatus.BAD_REQUEST, str(e))
            return
        if not jobqueue.batch_in_scope(parts[2], **self._data_scope()):
            self._err(HTTPStatus.NOT_FOUND, f"batch not found: {parts[2]}")
            return
        result = jobqueue.delete_batch(parts[2])
        if not result.get("deleted"):
            reason = result.get("reason", "unknown")
            if reason == "not_found":
                self._err(HTTPStatus.NOT_FOUND, f"batch not found: {parts[2]}")
            elif reason == "has_running_jobs":
                self._err(HTTPStatus.CONFLICT,
                          "Пакет содержит запущенные задачи; сначала отмените их.")
            elif reason in ("favorite", "has_favorite_jobs"):
                self._err(HTTPStatus.CONFLICT,
                          "Отчёт находится в избранном. Сначала снимите звезду.")
            else:
                self._err(HTTPStatus.INTERNAL_SERVER_ERROR, reason)
            return
        self._json(HTTPStatus.OK, result)

    def _route_post(self) -> None:
        url = urllib.parse.urlparse(self.path)
        path = url.path

        if path in {
            "/api/auth/login/start", "/api/auth/login/status", "/api/auth/profile",
            "/api/auth/google/login/start", "/api/auth/email/start",
            "/api/auth/email/verify", "/api/auth/test/google-login",
        }:
            self._auth_public_post(path)
            return

        if path == "/api/auth/miniapp/register":
            # Public: register/activate straight from a verified Telegram Mini App
            # identity (initData), no bot round-trip. initData HMAC is the auth.
            self._miniapp_register()
            return

        # PayPal webhook is a PUBLIC endpoint (PayPal cannot pass Telegram auth).
        # It is authenticated by verifying the PayPal signature instead.
        if path == "/api/billing/paypal/webhook":
            self._paypal_webhook()
            return

        if path == "/api/telegram/webhook":
            body = self._read_body()
            if body is None:
                return
            try:
                supplied_secret = str(
                    self.headers.get("X-Telegram-Bot-Api-Secret-Token") or ""
                )
                dispatch = (
                    production_telegram.accept_webhook(body, supplied_secret)
                    if _server_environment_explicit()
                    else telegram_service.process_webhook_update(body, supplied_secret)
                )
                self._json(HTTPStatus.OK, {"ok": True, "handler": dispatch.get("handler")})
            except production_telegram.StorageError as exc:
                self._err(
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    "production Telegram storage is unavailable",
                    code=getattr(exc, "code", "storage_unavailable"),
                )
            except (telegram_service.TelegramServiceError,
                    production_telegram.TelegramPayloadRejected) as exc:
                self._err(HTTPStatus.FORBIDDEN, str(exc))
            return

        # Connector nodes authenticate with one-time enrollment or their own
        # short-lived device session, never with a browser/Telegram cookie.
        if path.startswith("/api/connector/v1/"):
            self._connector_public_post(path)
            return

        # Environment heartbeat. Authenticated by a shared registry token, not
        # by a browser session: the caller is another environment's server
        # process, which has no session and must never be given one. It is
        # placed ahead of _authorize_api for that reason, and authenticates
        # itself immediately below.
        if path == environment_registry.HEARTBEAT_PATH:
            self._environment_heartbeat_post()
            return

        if not self._authorize_api(path):
            return

        if path in {
            "/api/account/nt-security/step-up/start",
            "/api/account/nt-security/step-up/confirm",
            "/api/account/nt-security/step-up/staging",
            "/api/account/identities/unlink",
        }:
            self._account_nt_security_post(path)
            return

        if path.startswith("/api/account/"):
            self._account_security_post(path)
            return

        if path.startswith("/api/ninjatrader/"):
            self._ninjatrader_post(path)
            return

        if path.startswith("/api/dev/preview/") or path == "/api/dev/bootstrap/mint":
            self._dev_preview_post(path)
            return

        if path == "/api/dev/service-login":
            self._dev_service_login()
            return

        if path.startswith("/api/admin/releases"):
            self._releases_post(path)
            return

        if path == "/api/documents" or path.startswith("/api/documents/"):
            self._documents_post(path)
            return

        if path == "/api/auth/google/start":
            if not self._check_local_post():
                return
            self._google_oauth_start()
            return

        if path in {"/api/auth/email/link/start", "/api/auth/email/link/verify"}:
            if not self._check_local_post():
                return
            body = self._read_body() or {}
            context = getattr(self, "_remote_context", None) or {}
            tunnel_ip, forwarded_ip = self._request_ips()
            try:
                if path.endswith("/start"):
                    out = account_auth.start_email_auth(
                        body.get("email"), ip=forwarded_ip or tunnel_ip,
                        user_agent=str(self.headers.get("User-Agent") or ""),
                        purpose="link", actor_user_id=context.get("user_id"),
                    )
                else:
                    out = account_auth.verify_email_auth(
                        body.get("challenge_id"), code=body.get("code"),
                        device_credential=self._device_credential(),
                        magic_token=body.get("magic_token"),
                        ip=forwarded_ip or tunnel_ip,
                        user_agent=str(self.headers.get("User-Agent") or ""),
                        actor_user_id=context.get("user_id"),
                    )
                self._json(HTTPStatus.OK, out)
            except account_auth.AccountAuthError as exc:
                self._err(exc.status, str(exc), code=getattr(exc, "code", "") or "")
            return

        if path == "/api/auth/nt-confirm/start":
            if not self._check_local_post():
                return
            context = getattr(self, "_remote_context", None) or {}
            try:
                out = account_auth.start_nt_telegram_confirm(
                    context.get("user_id"),
                    session_id=str(context.get("session_id") or ""),
                    api_call=telegram_service._api_call,
                )
                self._json(HTTPStatus.OK, out)
            except account_auth.AccountAuthError as exc:
                self._err(exc.status, str(exc), code=getattr(exc, "code", "") or "")
            return

        if path == "/api/auth/nt-confirm/status":
            if not self._check_local_post():
                return
            body = self._read_body() or {}
            context = getattr(self, "_remote_context", None) or {}
            try:
                out = account_auth.nt_confirm_status(
                    str(body.get("challenge_id") or ""),
                    user_id=context.get("user_id"),
                )
                # Refresh gate after possible confirm.
                out["nt_access"] = account_auth.nt_action_gate(None, context=context)
                if out.get("status") == "nt_confirmed" and context.get("session_id"):
                    # Ensure current session elevated even if challenge targeted another session id.
                    try:
                        elev = account_auth.elevate_session_for_nt(
                            str(context.get("session_id") or ""),
                            user_id=context.get("user_id"),
                        )
                        out["nt_elevated_until"] = elev.get("nt_elevated_until")
                        out["nt_access"] = account_auth.nt_action_gate(
                            None,
                            context={**context, "nt_elevated_until": elev.get("nt_elevated_until")},
                        )
                    except account_auth.AccountAuthError:
                        pass
                self._json(HTTPStatus.OK, out)
            except account_auth.AccountAuthError as exc:
                self._err(exc.status, str(exc), code=getattr(exc, "code", "") or "")
            return

        if path == "/api/auth/test/nt-elevate":
            if not self._check_local_post():
                return
            context = getattr(self, "_remote_context", None) or {}
            try:
                out = account_auth.grant_nt_elevation_staging(
                    context.get("user_id"),
                    session_id=str(context.get("session_id") or ""),
                )
                out["nt_access"] = account_auth.nt_action_gate(
                    None, context={**context, "nt_elevated_until": out.get("nt_elevated_until")},
                )
                self._json(HTTPStatus.OK, out)
            except (account_auth.AccountAuthError, runtime_env.RuntimeEnvError) as exc:
                self._err(getattr(exc, "status", 403), str(exc), code=getattr(exc, "code", "") or "")
            return

        if path == "/api/auth/test/virtual-user":
            if not self._check_local_post():
                return
            self._test_create_virtual_user()
            return

        if path == "/api/auth/test/login":
            if not self._check_local_post():
                return
            self._test_login_virtual()
            return

        if path == "/api/auth/test/google-link":
            if not self._check_local_post():
                return
            self._test_google_link()
            return

        if path == "/api/owner/impersonate":
            if not self._check_local_post():
                return
            self._owner_impersonate()
            return

        if path == "/api/owner/impersonate/end":
            if not self._check_local_post():
                return
            self._owner_impersonate_end()
            return

        if path == "/api/owner/agents/team-grant":
            if not self._check_local_post():
                return
            self._owner_agent_team_grant()
            return

        if path == "/api/owner/google/secrets":
            if not self._check_local_post():
                return
            self._owner_google_secrets()
            return

        if path == "/api/practice/account":
            if not self._check_local_post():
                return
            body = self._read_body() or {}
            context = getattr(self, "_remote_context", None) or {}
            try:
                out = practice_trading.create_account(
                    context.get("user_id"),
                    deposit=body.get("deposit", 50000),
                    commission=body.get("commission", 2),
                    daily_loss_limit=body.get("daily_loss_limit", 1000),
                    max_drawdown=body.get("max_drawdown", 2000),
                    position_limit=body.get("position_limit", 4),
                    symbol=str(body.get("symbol") or "MNQ"),
                    workspace_id=str(context.get("workspace_id") or ""),
                )
                self._json(HTTPStatus.OK, out)
            except practice_trading.PracticeTradingError as exc:
                self._err(exc.status, str(exc))
            return

        if path == "/api/practice/reset":
            if not self._check_local_post():
                return
            context = getattr(self, "_remote_context", None) or {}
            try:
                out = practice_trading.reset_account(
                    context.get("user_id"),
                    workspace_id=str(context.get("workspace_id") or ""),
                )
                self._json(HTTPStatus.OK, out)
            except practice_trading.PracticeTradingError as exc:
                self._err(exc.status, str(exc))
            return

        if path == "/api/community/message":
            if not self._check_local_post():
                return
            body = self._read_body() or {}
            context = getattr(self, "_remote_context", None) or {}
            user = context.get("user") or {}
            user_uuid = str(user.get("user_uuid") or user.get("id") or "").strip()
            try:
                out = community.post_message(
                    context.get("user_id"),
                    text=str(body.get("text") or ""),
                    display_name=str(user.get("first_name") or user.get("username") or ""),
                    workspace_id=str(context.get("workspace_id") or ""),
                    idempotency_key=str(self.headers.get("Idempotency-Key") or ""),
                    channel_id=str(body.get("channel_id") or "general"),
                    thread_root_id=str(body.get("thread_root_id") or ""),
                    attachments=body.get("attachments"),
                    user_uuid=user_uuid,
                )
                try:
                    out["telegram_mirror"] = bool(not out.get("deduplicated") and
                        telegram_service.mirror_community_message(
                            out["message"].get("text") or "",
                            display_name=out["message"].get("display_name") or "",
                            dedupe_key=str(out["message"].get("message_id") or ""),
                            workspace_id=str(context.get("workspace_id") or ""),
                        )
                    )
                except Exception:
                    out["telegram_mirror"] = False
                self._json(HTTPStatus.OK, out)
            except community.CommunityError as exc:
                self._err(exc.status, str(exc))
            return

        if path == "/api/community/share-report":
            if not self._check_local_post():
                return
            body = self._read_body() or {}
            context = getattr(self, "_remote_context", None) or {}
            user = context.get("user") or {}
            user_uuid = str(user.get("user_uuid") or user.get("id") or "").strip()
            try:
                out = community.share_report(
                    context.get("user_id"),
                    title=str(body.get("title") or ""),
                    summary=str(body.get("summary") or ""),
                    metrics=body.get("metrics") if isinstance(body.get("metrics"), dict) else {},
                    display_name=str(user.get("first_name") or user.get("username") or ""),
                    workspace_id=str(context.get("workspace_id") or ""),
                    channel_id=str(body.get("channel_id") or "reports"),
                    attachments=body.get("attachments"),
                    user_uuid=user_uuid,
                )
                self._json(HTTPStatus.OK, out)
            except community.CommunityError as exc:
                self._err(exc.status, str(exc))
            return

        if path == "/api/community/request":
            if not self._check_local_post():
                return
            body = self._read_body() or {}
            context = getattr(self, "_remote_context", None) or {}
            user = context.get("user") or {}
            user_uuid = str(user.get("user_uuid") or user.get("id") or "").strip()
            try:
                out = community.create_request(
                    context.get("user_id"),
                    title=str(body.get("title") or ""),
                    request_type=str(body.get("request_type") or "report"),
                    recipient_user_id=body.get("recipient_user_id"),
                    notes=str(body.get("notes") or ""),
                    display_name=str(user.get("first_name") or user.get("username") or ""),
                    workspace_id=str(context.get("workspace_id") or ""),
                    channel_id=str(body.get("channel_id") or "reports"),
                    user_uuid=user_uuid,
                )
                self._json(HTTPStatus.OK, out)
            except community.CommunityError as exc:
                self._err(exc.status, str(exc))
            return

        if path == "/api/community/strategies":
            if not self._check_local_post():
                return
            body = self._read_body() or {}
            context = getattr(self, "_remote_context", None) or {}
            user = context.get("user") or {}
            user_uuid = str(user.get("user_uuid") or user.get("id") or "").strip()
            try:
                out = community.publish_strategy(
                    context.get("user_id"),
                    title=str(body.get("title") or ""),
                    metrics=body.get("metrics") if isinstance(body.get("metrics"), dict) else {},
                    notes=str(body.get("notes") or ""),
                    display_name=str(user.get("first_name") or user.get("username") or ""),
                    workspace_id=str(context.get("workspace_id") or ""),
                    idempotency_key=str(self.headers.get("Idempotency-Key") or ""),
                    user_uuid=user_uuid,
                )
                self._json(HTTPStatus.OK, out)
            except community.CommunityError as exc:
                self._err(exc.status, str(exc))
            return

        if path == "/api/community/copy":
            if not self._check_local_post():
                return
            body = self._read_body() or {}
            context = getattr(self, "_remote_context", None) or {}
            user = context.get("user") or {}
            user_uuid = str(user.get("user_uuid") or user.get("id") or "").strip()
            try:
                out = community.copy_strategy(
                    context.get("user_id"),
                    str(body.get("strategy_id") or ""),
                    workspace_id=str(context.get("workspace_id") or ""),
                    idempotency_key=str(self.headers.get("Idempotency-Key") or ""),
                    user_uuid=user_uuid,
                )
                self._json(HTTPStatus.OK, out)
            except community.CommunityError as exc:
                self._err(exc.status, str(exc))
            return

        if path == "/api/community/report":
            if not self._check_local_post():
                return
            body = self._read_body() or {}
            context = getattr(self, "_remote_context", None) or {}
            user = context.get("user") or {}
            user_uuid = str(user.get("user_uuid") or user.get("id") or "").strip()
            try:
                out = community.report_abuse(
                    context.get("user_id"),
                    target_id=str(body.get("target_id") or ""),
                    reason=str(body.get("reason") or ""),
                    workspace_id=str(context.get("workspace_id") or ""),
                    user_uuid=user_uuid,
                )
                self._json(HTTPStatus.OK, out)
            except community.CommunityError as exc:
                self._err(exc.status, str(exc))
            return

        if path == "/api/practice/orders":
            if not self._check_local_post():
                return
            body = self._read_body() or {}
            context = getattr(self, "_remote_context", None) or {}
            try:
                out = practice_trading.place_order(
                    context.get("user_id"),
                    symbol=str(body.get("symbol") or "MNQ"),
                    side=str(body.get("side") or "buy"),
                    quantity=body.get("quantity", 1),
                    order_type=str(body.get("order_type") or "market"),
                    limit_price=body.get("limit_price", 0),
                    stop_loss=body.get("stop_loss", 0),
                    take_profit=body.get("take_profit", 0),
                    workspace_id=str(context.get("workspace_id") or ""),
                )
                self._json(HTTPStatus.OK, out)
            except practice_trading.PracticeTradingError as exc:
                self._err(exc.status, str(exc))
            return

        if path == "/api/practice/close":
            if not self._check_local_post():
                return
            body = self._read_body() or {}
            context = getattr(self, "_remote_context", None) or {}
            try:
                out = practice_trading.close_position(
                    context.get("user_id"),
                    str(body.get("position_id") or ""),
                    symbol=str(body.get("symbol") or ""),
                    workspace_id=str(context.get("workspace_id") or ""),
                )
                self._json(HTTPStatus.OK, out)
            except practice_trading.PracticeTradingError as exc:
                self._err(exc.status, str(exc))
            return

        if path == "/api/practice/tick":
            if not self._check_local_post():
                return
            body = self._read_body() or {}
            context = getattr(self, "_remote_context", None) or {}
            try:
                symbol = str(body.get("symbol") or "")
                runtime_override = workspaces.runtime_dir_for_context(
                    context.get("workspace_context") or {}
                )
                if runtime_override:
                    with ops_runtime.runtime_dir_override(runtime_override):
                        market = _practice_market_quote(
                            symbol,
                            workspace_id=str(context.get("workspace_id") or ""),
                        )
                else:
                    market = _practice_market_quote(
                        symbol,
                        workspace_id=str(context.get("workspace_id") or ""),
                    )
                out = practice_trading.tick_marks(
                    context.get("user_id"), symbol=symbol,
                    price=float(market.get("price") or 0), market=market,
                    workspace_id=str(context.get("workspace_id") or ""),
                )
                self._json(HTTPStatus.OK, out)
            except practice_trading.PracticeTradingError as exc:
                self._err(exc.status, str(exc))
            return

        if path == "/api/demo-backtests":
            if not self._check_local_post():
                return
            body = self._read_body() or {}
            context = getattr(self, "_remote_context", None) or {}
            caps = context.get("capabilities") if isinstance(context.get("capabilities"), dict) else {}
            # Allow demo for users with demo_backtest OR full backtesting (preview).
            if not (context.get("is_owner") or caps.get("demo_backtest") or caps.get("backtesting")):
                # Capabilities may live on augmented auth payload only — re-resolve.
                try:
                    user = context.get("user") or {}
                    sub = None
                    if not context.get("is_owner"):
                        try:
                            sub = subscriptions.active_entitlement(context.get("user_id"))
                        except Exception:
                            sub = None
                    if not isinstance(sub, dict) or not sub:
                        sub = None
                    perm = permissions.resolve(user, sub)
                    caps = perm.get("capabilities") or {}
                except Exception:
                    caps = {}
            if not (context.get("is_owner") or caps.get("demo_backtest") or caps.get("backtesting")):
                self._err(HTTPStatus.FORBIDDEN, "Демо-бэктест недоступен для этого аккаунта.")
                return
            try:
                limit = 3
                try:
                    plan = subscriptions.effective_plan(str((context.get("user") or {}).get("plan_id") or "free_preview"))
                    limit = int(((plan or {}).get("limits") or {}).get("max_demo_backtests_per_day") or 3)
                except Exception:
                    pass
                out = demo_backtest.create_demo_backtest(
                    context.get("user_id"),
                    scenario_id=str(body.get("scenario_id") or ""),
                    daily_limit=limit,
                    workspace_id=str(context.get("workspace_id") or ""),
                )
                self._json(HTTPStatus.OK, out)
            except demo_backtest.DemoBacktestError as exc:
                self._err(exc.status, str(exc))
            return

        if path == "/api/auth/ux-mode":
            if not self._check_local_post():
                return
            context = getattr(self, "_remote_context", None) or {}
            body = self._read_body() or {}
            try:
                result = account_auth.set_ux_mode(
                    context.get("user_id"),
                    str(body.get("ux_mode") or body.get("mode") or ""),
                    confirm_downgrade=bool(body.get("confirm_downgrade") or body.get("confirm")),
                )
                # Refresh auth payload so client gets new nav immediately.
                user = result.get("user") or {}
                payload = self._augment_permissions(context, {
                    "ok": True,
                    "authenticated": True,
                    "ux_mode": result.get("ux_mode"),
                    "previous": result.get("previous"),
                    "user": user,
                    "is_owner": bool(context.get("is_owner")),
                    "role": context.get("role"),
                    "user_id": context.get("user_id"),
                })
                self._json(HTTPStatus.OK, payload)
            except account_auth.AccountAuthError as exc:
                self._err(exc.status, str(exc), code=getattr(exc, "code", "") or "")
            return

        if path == "/api/auth/logout":
            if not self._check_local_post():
                return
            account_auth.revoke_session(self._cookie_value(runtime_env.session_cookie_name()))
            self._clear_session_cookie()
            self._json(HTTPStatus.OK, {"ok": True})
            return

        if path.startswith("/api/support/"):
            if not self._check_local_post():
                return
            body = self._read_body()
            if body is None:
                return
            context = getattr(self, "_remote_context", None) or {}
            try:
                if path == "/api/support/telemetry":
                    out = user_support.record_telemetry(
                        context.get("user_id"), str(context.get("session_id") or ""), body,
                    )
                elif path == "/api/support/poll":
                    out = user_support.poll(
                        context.get("user_id"), str(context.get("session_id") or ""),
                        body.get("client_id"),
                    )
                elif path == "/api/support/commands/ack":
                    out = user_support.ack_command(
                        context.get("user_id"), body.get("client_id"), body.get("command_id"),
                        status=str(body.get("status") or "done"), error=str(body.get("error") or ""),
                    )
                elif path == "/api/support/screenshots/respond":
                    out = user_support.respond_screenshot(
                        context.get("user_id"), body.get("client_id"), body.get("request_id"),
                        decision=str(body.get("decision") or ""), data_url=str(body.get("data_url") or ""),
                        width=body.get("width"), height=body.get("height"), error=str(body.get("error") or ""),
                    )
                    private = out.pop("private_request", {})
                    if private.get("status") == "completed" and private.get("conversation_id"):
                        try:
                            ai_chief_agent.report_user_screenshot(
                                conversation_id=str(private.get("conversation_id") or "default"),
                                text=f"Пользователь ID {private.get('user_id')} одобрил запрос и прислал снимок экрана.",
                                image_url=f"/api/owner/support/screenshots/{private.get('request_id')}",
                                caption="Снимок экрана пользователя — получен после явного согласия",
                                scope=private.get("owner_scope") if isinstance(private.get("owner_scope"), dict) else None,
                            )
                        except Exception:
                            pass
                else:
                    self._err(HTTPStatus.NOT_FOUND, f"no support route: {path}")
                    return
                self._json(HTTPStatus.OK, out)
            except user_support.UserSupportError as exc:
                self._err(exc.status, str(exc))
            return

        if path.startswith("/api/owner/support/"):
            if not self._check_local_post():
                return
            body = self._read_body()
            if body is None:
                return
            context = getattr(self, "_remote_context", None) or {}
            actor = context.get("user_id")
            parts_support = [urllib.parse.unquote(p) for p in path.split("/") if p]
            try:
                if len(parts_support) == 6 and parts_support[:4] == ["api", "owner", "support", "users"]:
                    if parts_support[5] == "screenshot":
                        out = user_support.request_screenshot(
                            actor, parts_support[4], note=str(body.get("note") or ""),
                            target_client_id=str(body.get("target_client_id") or ""),
                        )
                    elif parts_support[5] == "reload":
                        out = user_support.queue_reload(
                            actor, parts_support[4], session_id=str(body.get("session_id") or ""),
                            client_id=str(body.get("client_id") or ""),
                            all_sessions=bool(body.get("all_sessions")),
                        )
                    elif parts_support[5] == "device-name":
                        out = user_support.rename_device(
                            actor, parts_support[4], body.get("device_id"), body.get("name"),
                        )
                    else:
                        self._err(HTTPStatus.NOT_FOUND, f"no support route: {path}")
                        return
                elif len(parts_support) == 6 and parts_support[:4] == ["api", "owner", "support", "screenshots"] and parts_support[5] == "delete":
                    out = user_support.delete_screenshot(actor, parts_support[4])
                else:
                    self._err(HTTPStatus.NOT_FOUND, f"no support route: {path}")
                    return
                self._json(HTTPStatus.OK, out)
            except user_support.UserSupportError as exc:
                self._err(exc.status, str(exc))
            return

        if path == "/api/worker/jobs" or (
            path.startswith("/api/worker/jobs/") and path.endswith("/cancel")
        ):
            if not self._check_local_post():
                return
            context = getattr(self, "_remote_context", None) or {}
            if not context.get("is_owner"):
                self._err(HTTPStatus.FORBIDDEN, "Это действие разрешено только владельцу.")
                return
            body = self._read_body()
            if body is None:
                return
            if path == "/api/worker/jobs":
                kind = str(body.get("kind") or "").strip()
                if kind not in {"durable_sweep", "telemetry_index"}:
                    self._err(HTTPStatus.BAD_REQUEST, "unsupported worker job kind")
                    return
                try:
                    out = local_worker.enqueue(
                        kind,
                        body.get("payload") if isinstance(body.get("payload"), dict) else {},
                        priority=int(body.get("priority") or 100),
                        max_attempts=int(body.get("max_attempts") or 1),
                        timeout_sec=int(body.get("timeout_sec") or 300),
                        user_id=context.get("user_id") or "",
                        workspace_id=str(context.get("workspace_id") or ""),
                        idempotency_key=str(
                            self.headers.get("Idempotency-Key")
                            or body.get("idempotency_key") or ""
                        ),
                    )
                    self._json(HTTPStatus.ACCEPTED, {"ok": True, "job": out})
                except (TypeError, ValueError) as exc:
                    self._err(HTTPStatus.BAD_REQUEST, str(exc), code="invalid_worker_request")
                except production_workers.StorageError as exc:
                    self._worker_queue_err(exc)
                return
            parts_worker = [urllib.parse.unquote(p) for p in path.split("/") if p]
            if len(parts_worker) != 5:
                self._err(HTTPStatus.NOT_FOUND, f"no worker route: {path}")
                return
            try:
                out = local_worker.cancel(
                    parts_worker[3],
                    workspace_id=str(context.get("workspace_id") or ""),
                    user_id=context.get("user_id") or 0,
                )
            except production_workers.StorageError as exc:
                self._worker_queue_err(exc)
                return
            self._json(HTTPStatus.OK, out)
            return

        if path.startswith("/api/auth/users/"):
            if not self._check_local_post():
                return
            body = self._read_body()
            if body is None:
                return
            parts_auth = [urllib.parse.unquote(p) for p in path.split("/") if p]
            if len(parts_auth) != 5:
                self._err(HTTPStatus.NOT_FOUND, f"no auth route: {path}"); return
            try:
                actor = (getattr(self, "_remote_context", None) or {}).get("user_id")
                if parts_auth[4] == "role":
                    out = account_auth.update_user(actor, parts_auth[3], role=str(body.get("role") or ""))
                elif parts_auth[4] == "revoke":
                    out = account_auth.update_user(actor, parts_auth[3], revoke=True)
                elif parts_auth[4] == "features":
                    out = account_auth.set_user_feature(actor, parts_auth[3], str(body.get("feature") or ""), bool(body.get("enabled")))
                elif parts_auth[4] == "permission":
                    out = account_auth.set_user_permission(actor, parts_auth[3], str(body.get("capability") or ""), body.get("enabled"))
                elif parts_auth[4] == "admin-permission":
                    out = account_auth.set_user_admin_permission(
                        actor,
                        parts_auth[3],
                        str(body.get("capability") or ""),
                        body.get("enabled"),
                        expires_at_utc=body.get("expires_at_utc"),
                    )
                elif parts_auth[4] == "status":
                    out = account_auth.set_user_status(actor, parts_auth[3], str(body.get("status") or ""))
                elif parts_auth[4] == "sessions":
                    out = account_auth.revoke_user_sessions(
                        actor,
                        parts_auth[3],
                        session_id=str(body.get("session_id") or ""),
                        device_id=str(body.get("device_id") or ""),
                        all_sessions=bool(body.get("all_sessions")),
                    )
                elif parts_auth[4] == "delete":
                    user_support.purge_user(actor, parts_auth[3])
                    out = account_auth.delete_user(actor, parts_auth[3])
                else:
                    self._err(HTTPStatus.NOT_FOUND, f"no auth route: {path}"); return
                self._json(HTTPStatus.OK, out)
            except account_auth.AccountAuthError as exc:
                self._err(exc.status, str(exc))
            except user_support.UserSupportError as exc:
                self._err(exc.status, str(exc))
            return

        if path == "/api/auth/avatar/refresh":
            if not self._check_local_post():
                return
            body = self._read_body()
            if body is None:
                return
            self._refresh_avatar()
            return

        if path in _BILLING_PROMO_POSTS:
            if not self._check_local_post():
                return
            body = self._read_body()
            if body is None:
                return
            context = getattr(self, "_remote_context", None) or {}
            user_id = context.get("user_id")
            account = account_auth.find_active_user(user_id) or {}
            email = str(body.get("email") or account.get("email") or "")
            requested_plan = str(body.get("requested_plan_id") or body.get("plan_id") or "")
            try:
                if path == "/api/billing/promo/preview":
                    out = subscriptions.preview_voucher(
                        body.get("code"), user_id=user_id, email=email,
                        requested_plan_id=requested_plan,
                    )
                else:
                    out = subscriptions.redeem_voucher(
                        body.get("code"), user_id=user_id, email=email,
                        requested_plan_id=requested_plan,
                        workspace_id=str(body.get("workspace_id") or ""),
                    )
                    entitlement = out.get("entitlement") if isinstance(out, dict) else {}
                    plan = entitlement.get("plan") if isinstance(entitlement, dict) and isinstance(entitlement.get("plan"), dict) else {}
                    features = plan.get("features") if isinstance(plan.get("features"), dict) else {}
                    if features.get("personal_nt") and not out.get("checkout_required"):
                        out["personal_workspace"] = workspaces.ensure_personal_workspace(
                            user_id, entitlement_id=str(entitlement.get("entitlement_id") or ""), require_entitlement=False,
                        )
                self._json(HTTPStatus.OK, out)
            except subscriptions.SubscriptionError as exc:
                self._err(exc.status, str(exc))
            except workspaces.WorkspaceError as exc:
                self._err(exc.status, str(exc))
            return

        if path == "/api/workspaces/select":
            if not self._check_local_post():
                return
            body = self._read_body()
            if body is None:
                return
            context = getattr(self, "_remote_context", None) or {}
            try:
                self._json(HTTPStatus.OK, workspaces.select_workspace(context.get("user_id"), body.get("workspace_id")))
            except workspaces.WorkspaceError as exc:
                self._err(exc.status, str(exc))
            return

        if path == "/api/workspaces/personal":
            if not self._check_local_post():
                return
            body = self._read_body()
            if body is None:
                return
            context = getattr(self, "_remote_context", None) or {}
            try:
                out = workspaces.ensure_personal_workspace(
                    context.get("user_id"), display_name=str(body.get("display_name") or ""),
                    require_entitlement=not bool(context.get("is_owner")),
                )
                self._json(HTTPStatus.OK, {"ok": True, "workspace": out})
            except workspaces.WorkspaceError as exc:
                self._err(exc.status, str(exc))
            return

        if path == "/api/bridge/pair/start":
            if not self._check_local_post():
                return
            body = self._read_body()
            if body is None:
                return
            context = getattr(self, "_remote_context", None) or {}
            # Phase 5: personal-NT pairing needs both factors + a fresh step-up.
            if not self._personal_nt_gate(
                personal_nt_security.ACTION_PAIRING, require_ready=True,
                challenge_id=str(body.get("step_up_challenge_id") or ""),
            ):
                return
            try:
                use_connector = (
                    runtime_env.environment_explicit() and runtime_env.is_production()
                ) or str(body.get("transport") or "") == "production_connector"
                out = (
                    connector_protocol.start_enrollment(
                        context.get("user_id"),
                        workspace_id=str(body.get("workspace_id") or ""),
                        machine_label=str(body.get("machine_label") or ""),
                        capabilities=body.get("capabilities") or [],
                    )
                    if use_connector
                    else workspaces.start_bridge_pairing(
                        context.get("user_id"),
                        workspace_id=str(body.get("workspace_id") or ""),
                        machine_label=str(body.get("machine_label") or ""),
                    )
                )
                self._json(HTTPStatus.OK, out)
            except (workspaces.WorkspaceError, connector_protocol.ConnectorProtocolError) as exc:
                self._err(exc.status, str(exc), code=getattr(exc, "code", "") or "")
            return

        if path == "/api/bridge/pair/complete":
            if not self._check_local_post():
                return
            body = self._read_body()
            if body is None:
                return
            context = getattr(self, "_remote_context", None) or {}
            # Factors must still be present to finish binding a personal device.
            if not self._personal_nt_require_ready():
                return
            try:
                if runtime_env.environment_explicit() and runtime_env.is_production():
                    raise connector_protocol.ConnectorProtocolError(
                        "Production pairing завершается только device enroll + signed hello.",
                        HTTPStatus.GONE,
                        "legacy_pairing_disabled",
                    )
                out = workspaces.complete_bridge_pairing(
                    context.get("user_id"), code=body.get("code"), device_id=str(body.get("device_id") or ""),
                    bridge_instance_id=str(body.get("bridge_instance_id") or ""),
                    machine_label=str(body.get("machine_label") or ""), capabilities=body.get("capabilities") or [],
                )
                self._json(HTTPStatus.OK, out)
            except (workspaces.WorkspaceError, connector_protocol.ConnectorProtocolError) as exc:
                self._err(exc.status, str(exc), code=getattr(exc, "code", "") or "")
            return

        if path == "/api/bridge/commands":
            if not self._check_local_post():
                return
            body = self._read_body()
            if body is None:
                return
            context = getattr(self, "_remote_context", None) or {}
            try:
                out = connector_protocol.queue_command(
                    context.get("user_id"),
                    workspace_id=str(body.get("workspace_id") or context.get("workspace_id") or ""),
                    connection_id=body.get("connection_id"),
                    capability=body.get("capability"),
                    idempotency_key=(
                        body.get("idempotency_key")
                        or self.headers.get("Idempotency-Key")
                        or ""
                    ),
                    payload=body.get("payload") or {},
                    expires_in_sec=body.get("expires_in_sec") or 120,
                )
                self._json(HTTPStatus.ACCEPTED, out)
            except (workspaces.WorkspaceError, connector_protocol.ConnectorProtocolError) as exc:
                self._err(exc.status, str(exc), code=getattr(exc, "code", "") or "")
            return

        if path.startswith("/api/bridge/connections/"):
            if not self._check_local_post():
                return
            parts_bridge = [urllib.parse.unquote(p) for p in path.split("/") if p]
            if len(parts_bridge) != 5 or parts_bridge[4] not in {"revoke", "default", "capabilities"}:
                self._err(HTTPStatus.NOT_FOUND, f"no bridge route: {path}"); return
            action_kind = parts_bridge[4]
            connection_id = parts_bridge[3]
            context = getattr(self, "_remote_context", None) or {}
            body = self._read_body() or {}
            step_up_challenge = str(body.get("step_up_challenge_id") or "")
            # Phase 5 step-up: revoke, default-account and capability changes are
            # all critical NinjaTrader actions.
            if action_kind == "revoke":
                if not self._personal_nt_gate(
                    personal_nt_security.ACTION_CONNECTOR_REVOKE, require_ready=False,
                    challenge_id=step_up_challenge,
                ):
                    return
            elif action_kind == "default":
                if not self._personal_nt_gate(
                    personal_nt_security.ACTION_DEFAULT_ACCOUNT, require_ready=True,
                    challenge_id=step_up_challenge,
                ):
                    return
            else:  # capabilities
                requested_caps = [str(v) for v in (body.get("capabilities") or [])]
                raises_live = any(cap in {"live_commands", "live_read"} for cap in requested_caps)
                if raises_live and not self._personal_nt_gate(
                    personal_nt_security.ACTION_TRADING_CAPABILITY, require_ready=True,
                    challenge_id=step_up_challenge,
                ):
                    return
            try:
                use_connector = (
                    runtime_env.environment_explicit() and runtime_env.is_production()
                ) or str(body.get("transport") or "") == "production_connector"
                if action_kind == "revoke":
                    out = (
                        connector_protocol.revoke_installation(
                            context.get("user_id"),
                            connection_id,
                            workspace_id=str(body.get("workspace_id") or context.get("workspace_id") or ""),
                        )
                        if use_connector
                        else workspaces.revoke_connection(context.get("user_id"), connection_id)
                    )
                elif action_kind == "default":
                    out = workspaces.set_default_connection(context.get("user_id"), connection_id)
                else:
                    out = workspaces.set_connection_capabilities(
                        context.get("user_id"), connection_id, body.get("capabilities") or [],
                    )
                self._json(HTTPStatus.OK, out)
            except (workspaces.WorkspaceError, connector_protocol.ConnectorProtocolError) as exc:
                self._err(exc.status, str(exc), code=getattr(exc, "code", "") or "")
            return

        if path == "/api/owner/vouchers":
            if not self._check_local_post():
                return
            body = self._read_body()
            if body is None:
                return
            try:
                out = subscriptions.create_voucher(
                    (getattr(self, "_remote_context", None) or {}).get("user_id"), body,
                )
                self._json(HTTPStatus.OK, out)
            except subscriptions.SubscriptionError as exc:
                self._err(exc.status, str(exc))
            return

        if path == "/api/owner/invites":
            if not self._check_local_post():
                return
            body = self._read_body()
            if body is None:
                return
            try:
                bot_username = telegram_service.bot_username()
                try:
                    public_url = str(telegram_remote.admin_status().get("public_url") or "")
                except Exception:
                    public_url = ""
                out = subscriptions.create_invite(
                    (getattr(self, "_remote_context", None) or {}).get("user_id"), body,
                    bot_username=bot_username, public_url=public_url,
                )
                out["render"] = self._render_invite(out)
                self._json(HTTPStatus.OK, out)
            except subscriptions.SubscriptionError as exc:
                self._err(exc.status, str(exc))
            return

        if path.startswith("/api/owner/invites/"):
            if not self._check_local_post():
                return
            body = self._read_body()
            if body is None:
                return
            inv_parts = [urllib.parse.unquote(p) for p in path.split("/") if p]
            actor = (getattr(self, "_remote_context", None) or {}).get("user_id")
            # /api/owner/invites/send            -> 4 parts, [3]=="send"
            # /api/owner/invites/<id>/status     -> 5 parts, [3]=id, [4]=action
            # /api/owner/invites/<id>/delete     -> 5 parts, [3]=id, [4]=action
            try:
                if len(inv_parts) == 4 and inv_parts[3] == "send":
                    out = self._send_invite(body)
                elif len(inv_parts) == 5 and inv_parts[4] == "status":
                    out = subscriptions.set_voucher_status(actor, inv_parts[3], str(body.get("status") or ""))
                elif len(inv_parts) == 5 and inv_parts[4] == "delete":
                    out = subscriptions.delete_voucher(actor, inv_parts[3])
                else:
                    self._err(HTTPStatus.NOT_FOUND, f"no invite route: {path}"); return
                self._json(HTTPStatus.OK, out)
            except subscriptions.SubscriptionError as exc:
                self._err(exc.status, str(exc))
            return

        if path == "/api/owner/plans/feature":
            if not self._check_local_post():
                return
            body = self._read_body()
            if body is None:
                return
            try:
                out = subscriptions.set_plan_feature(
                    (getattr(self, "_remote_context", None) or {}).get("user_id"),
                    str(body.get("plan_id") or ""), str(body.get("feature") or ""), bool(body.get("enabled")),
                )
                self._json(HTTPStatus.OK, out)
            except subscriptions.SubscriptionError as exc:
                self._err(exc.status, str(exc))
            return

        if path == "/api/owner/payment":
            if not self._check_local_post():
                return
            body = self._read_body()
            if body is None:
                return
            try:
                out = subscriptions.set_payment_config(
                    (getattr(self, "_remote_context", None) or {}).get("user_id"), body,
                )
                self._json(HTTPStatus.OK, out)
            except subscriptions.SubscriptionError as exc:
                self._err(exc.status, str(exc))
            return

        if path == "/api/owner/paypal":
            if not self._check_local_post():
                return
            body = self._read_body()
            if body is None:
                return
            try:
                out = subscriptions.set_paypal_config(
                    (getattr(self, "_remote_context", None) or {}).get("user_id"), body,
                )
                self._json(HTTPStatus.OK, out)
            except subscriptions.SubscriptionError as exc:
                self._err(exc.status, str(exc))
            return

        if path == "/api/owner/paypal/plans":
            if not self._check_local_post():
                return
            body = self._read_body()
            if body is None:
                return
            try:
                out = paypal.ensure_plans((getattr(self, "_remote_context", None) or {}).get("user_id"))
                self._json(HTTPStatus.OK, out)
            except (paypal.PayPalError, subscriptions.SubscriptionError) as exc:
                self._err(getattr(exc, "status", 400), str(exc))
            return

        if path == "/api/billing/subscribe":
            if not self._check_local_post():
                return
            body = self._read_body()
            if body is None:
                return
            context = getattr(self, "_remote_context", None) or {}
            base = self.headers.get("Origin") or ("http://" + (self.headers.get("Host") or "127.0.0.1"))
            base = base.rstrip("/")
            try:
                out = paypal.create_subscription(
                    context.get("user_id"), str(body.get("plan_id") or ""),
                    return_url=f"{base}/ui/?paypal=success",
                    cancel_url=f"{base}/ui/?paypal=cancel",
                )
                self._json(HTTPStatus.OK, out)
            except paypal.PayPalError as exc:
                self._err(exc.status, str(exc))
            return

        if path == "/api/billing/checkout":
            if not self._check_local_post():
                return
            body = self._read_body()
            if body is None:
                return
            context = getattr(self, "_remote_context", None) or {}
            try:
                self._json(HTTPStatus.OK, subscriptions.manual_checkout(
                    context.get("user_id"), str(body.get("plan_id") or "")))
            except subscriptions.SubscriptionError as exc:
                self._err(exc.status, str(exc))
            return

        if path == "/api/billing/payment-request":
            if not self._check_local_post():
                return
            body = self._read_body()
            if body is None:
                return
            context = getattr(self, "_remote_context", None) or {}
            try:
                out = subscriptions.create_payment_request(
                    context.get("user_id"), str(body.get("plan_id") or ""), note=str(body.get("note") or ""))
                self._notify_owner_payment_request(context, out.get("request") or {})
                self._json(HTTPStatus.OK, out)
            except subscriptions.SubscriptionError as exc:
                self._err(exc.status, str(exc))
            return

        if path == "/api/owner/grant":
            if not self._check_local_post():
                return
            body = self._read_body()
            if body is None:
                return
            actor = (getattr(self, "_remote_context", None) or {}).get("user_id")
            try:
                if str(body.get("plan_id") or "").strip():
                    out = subscriptions.grant_plan(
                        actor, body.get("user_id"), str(body.get("plan_id") or ""),
                        duration_days=body.get("duration_days"), note=str(body.get("note") or ""))
                else:
                    out = subscriptions.clear_user_plan(actor, body.get("user_id"))
                self._json(HTTPStatus.OK, out)
            except subscriptions.SubscriptionError as exc:
                self._err(exc.status, str(exc))
            return

        if path == "/api/owner/payment-requests/resolve":
            if not self._check_local_post():
                return
            body = self._read_body()
            if body is None:
                return
            try:
                out = subscriptions.resolve_payment_request(
                    (getattr(self, "_remote_context", None) or {}).get("user_id"),
                    str(body.get("request_id") or ""), approve=bool(body.get("approve")),
                    duration_days=body.get("duration_days"))
                self._json(HTTPStatus.OK, out)
            except subscriptions.SubscriptionError as exc:
                self._err(exc.status, str(exc))
            return

        # /api/jobs/<id>/cancel and /api/batches/<id>/cancel
        parts = [p for p in path.split("/") if p]
        is_cancel_job = (len(parts) == 4 and parts[0] == "api"
                         and parts[1] == "jobs"     and parts[3] == "cancel")
        is_cancel_batch = (len(parts) == 4 and parts[0] == "api"
                           and parts[1] == "batches" and parts[3] == "cancel")
        is_catalog_refresh = (path == "/api/catalog/refresh")
        is_margins_refresh = (path == "/api/margins/refresh")
        is_server_restart = (path == "/api/server/restart")
        is_ops = path.startswith("/api/ops/")
        is_profiles = path.startswith("/api/profiles/")
        is_report_favorites = path == "/api/report-favorites" or path.startswith("/api/report-favorites/")
        is_ai_lab = path.startswith("/api/ai-lab/")
        is_governance = path.startswith("/api/governance/")
        is_portfolio = path.startswith("/api/portfolio/")
        is_telegram = path.startswith("/api/telegram/")
        is_vitek = path.startswith("/api/vitek/")
        is_notifications = path.startswith("/api/notifications")
        is_ai_agents = path == "/api/ai-agents" or path.startswith("/api/ai-agents/")

        if not (path in ("/api/jobs", "/api/batches")
                or is_cancel_job or is_cancel_batch
                or is_catalog_refresh or is_margins_refresh
                or is_server_restart
                or is_ops or is_profiles or is_report_favorites
                or is_ai_lab or is_governance or is_portfolio or is_telegram or is_vitek
                or is_notifications or is_ai_agents):
            self._err(HTTPStatus.NOT_FOUND, f"no route: {path}")
            return

        if not self._check_local_post():
            return  # _check_local_post already wrote an error

        if is_notifications:
            body = self._read_body()
            if body is None:
                return
            context = getattr(self, "_remote_context", None) or {}
            if not context.get("is_owner"):
                self._err(HTTPStatus.FORBIDDEN, "Это действие разрешено только владельцу.")
                return
            if path == "/api/notifications/ack":
                ids = body.get("ids") if isinstance(body.get("ids"), list) else []
                self._json(HTTPStatus.OK, in_app_notifications.ack(
                    ids=[str(x) for x in ids],
                    conversation_id=str(body.get("conversation_id") or ""),
                ))
                return
            if path == "/api/notifications/delete":
                ids = body.get("ids") if isinstance(body.get("ids"), list) else []
                self._json(HTTPStatus.OK, in_app_notifications.delete(ids=[str(x) for x in ids]))
                return
            if path == "/api/notifications/clear":
                self._json(HTTPStatus.OK, in_app_notifications.clear(
                    mode=str(body.get("mode") or "all"),
                ))
                return
            self._err(HTTPStatus.NOT_FOUND, f"no route: {path}")
            return

        if is_vitek:
            body = self._read_body()
            if body is None:
                return
            context = getattr(self, "_remote_context", None) or {}
            if not context.get("is_owner"):
                self._err(HTTPStatus.FORBIDDEN, "Это действие разрешено только владельцу.")
                return
            try:
                vitek_parts = [urllib.parse.unquote(p) for p in path.split("/") if p]
                if path == "/api/vitek/scan":
                    out = vitek.scan(notify=bool(body.get("notify", False)))
                elif path == "/api/vitek/rest":
                    out = {"ok": True, "rest": vitek.set_rest(
                        duration_minutes=body.get("duration_minutes") or 0,
                        until_utc=body.get("until_utc") or "",
                        reason=str(body.get("reason") or ""),
                    )}
                elif path == "/api/vitek/resume":
                    out = {"ok": True, "rest": vitek.resume()}
                elif path == "/api/vitek/reconcile":
                    out = vitek.reconcile_lifecycle(
                        apply=bool(body.get("apply", False)),
                        kinds=body.get("kinds") if isinstance(body.get("kinds"), list) else None,
                    )
                elif path == "/api/vitek/client-events":
                    out = {"ok": True, "event": vitek.record_client_telemetry(body)}
                elif (len(vitek_parts) == 5 and vitek_parts[:3] == ["api", "vitek", "tasks"]
                      and vitek_parts[4] == "answer"):
                    out = {"ok": True, "task": vitek.answer_task(
                        vitek_parts[3], str(body.get("answer") or ""),
                    )}
                elif (len(vitek_parts) == 5 and vitek_parts[:3] == ["api", "vitek", "tasks"]
                      and vitek_parts[4] == "progress"):
                    out = {"ok": True, "task": vitek.update_task_progress(
                        vitek_parts[3], stage=str(body.get("stage") or ""),
                        items_found=body.get("items_found"),
                        items_checked=body.get("items_checked"),
                        items_total=body.get("items_total"),
                        current_item=str(body.get("current_item") or ""),
                        completed_steps=body.get("completed_steps"),
                        total_steps=body.get("total_steps"),
                        checkpoint=body.get("checkpoint") if isinstance(body.get("checkpoint"), dict) else None,
                        worker_id=str(body.get("worker_id") or ""),
                    )}
                elif path == "/api/vitek/tasks":
                    out = {"ok": True, "task": vitek.add_task({
                        **body,
                        "conversation_scope": self._ai_conversation_scope(),
                    })}
                elif path == "/api/vitek/events":
                    out = vitek.emit_event(
                        str(body.get("event_type") or "app_event"),
                        body.get("payload") if isinstance(body.get("payload"), dict) else {},
                        source=str(body.get("source") or "app"),
                        severity=str(body.get("severity") or ""),
                        dedupe_key=str(body.get("dedupe_key") or ""),
                        scope=self._ai_conversation_scope(),
                    )
                elif path == "/api/vitek/plans":
                    out = {"ok": True, "plan": vitek.set_plan(body)}
                elif (len(vitek_parts) == 4 and vitek_parts[:3] == ["api", "vitek", "tasks"]):
                    out = {"ok": True, "task": vitek.update_task(vitek_parts[3], body)}
                elif (len(vitek_parts) == 5 and vitek_parts[:3] == ["api", "vitek", "incidents"]
                      and vitek_parts[4] == "decision"):
                    conversation_scope = self._ai_conversation_scope()
                    out = {"ok": True, "incident": vitek.decide_incident(
                        vitek_parts[3], str(body.get("decision") or ""),
                        note=str(body.get("note") or ""),
                        authorized_by=str(context.get("user_id") or "owner"),
                        authorization_scope=body.get("authorization_scope"),
                        conversation_scope=conversation_scope,
                    )}
                else:
                    self._err(HTTPStatus.NOT_FOUND, f"no Vitek route: {path}")
                    return
                self._json(HTTPStatus.OK, out)
            except vitek.VitekError as exc:
                self._err(HTTPStatus.BAD_REQUEST, str(exc))
            except Exception as exc:
                self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"Vitek action failed: {exc}")
            return

        if is_telegram:
            body = self._read_body()
            if body is None:
                return
            try:
                if path == "/api/telegram/token":
                    out = telegram_service.configure_token(str(body.get("token") or ""))
                elif path == "/api/telegram/pair/start":
                    out = telegram_service.start_pairing()
                elif path == "/api/telegram/pair/complete":
                    out = telegram_service.complete_pairing()
                elif path == "/api/telegram/settings":
                    out = telegram_service.update_settings(body.get("settings") or body)
                elif path == "/api/telegram/remote/settings":
                    out = telegram_remote.update_settings(body.get("settings") or body)
                elif path == "/api/telegram/remote/pair/start":
                    out = telegram_remote.start_pairing(
                        bot_username=telegram_service.bot_username(),
                        role=str(body.get("role") or "read_only"),
                        expected_user_id=body.get("expected_user_id") or 0,
                        require_phone=bool(body.get("require_phone", True)),
                    )
                elif path == "/api/telegram/remote/menu-button":
                    out = telegram_remote.configure_menu_button(telegram_service._api_call)
                elif path == "/api/telegram/tunnel/launch":
                    out = tunnel_manager.launch(
                        port=self.server.server_address[1],
                        enable_remote=bool(body.get("enable_remote", True)),
                    )
                elif path == "/api/telegram/tunnel/start":
                    out = tunnel_manager.start(port=self.server.server_address[1])
                elif path == "/api/telegram/tunnel/stop":
                    out = tunnel_manager.stop()
                elif path.startswith("/api/telegram/remote/users/"):
                    remote_parts = [urllib.parse.unquote(p) for p in path.split("/") if p]
                    if len(remote_parts) != 6:
                        self._err(HTTPStatus.NOT_FOUND, f"no Telegram route: {path}")
                        return
                    user_id, action = remote_parts[4], remote_parts[5]
                    if action == "role":
                        out = telegram_remote.set_user_role(user_id, str(body.get("role") or ""))
                    elif action == "revoke":
                        out = telegram_remote.revoke_user(user_id)
                    else:
                        self._err(HTTPStatus.NOT_FOUND, f"no Telegram route: {path}")
                        return
                elif path == "/api/telegram/test":
                    out = telegram_service.send_test()
                elif path == "/api/telegram/group":
                    out = telegram_service.configure_group(str(body.get("group_id") or ""))
                elif path == "/api/telegram/group/disconnect":
                    out = telegram_service.disconnect_group()
                elif path == "/api/telegram/disconnect":
                    if account_auth.auth_required():
                        raise telegram_service.TelegramServiceError(
                            "Нельзя отключить единственный способ входа, пока обязательна Telegram-авторизация."
                        )
                    out = telegram_service.disconnect()
                else:
                    self._err(HTTPStatus.NOT_FOUND, f"no Telegram route: {path}")
                    return
            except telegram_service.TelegramServiceError as exc:
                self._err(HTTPStatus.BAD_REQUEST, str(exc))
                return
            except telegram_remote.RemoteAccessError as exc:
                self._err(exc.status, str(exc))
                return
            except tunnel_manager.TunnelManagerError as exc:
                self._err(exc.status, str(exc))
                return
            self._json(HTTPStatus.OK, out)
            return

        if is_ai_agents:
            body = self._read_body()
            if body is None:
                return
            parts = [urllib.parse.unquote(part) for part in path.split("/") if part]
            try:
                if path == "/api/ai-agents":
                    out = {"agent": ai_agent_registry.create_agent(body.get("agent") or body)}
                elif len(parts) == 3 and parts[:2] == ["api", "ai-agents"]:
                    out = {"agent": ai_agent_registry.update_agent(parts[2], body.get("agent") or body)}
                elif len(parts) == 4 and parts[:2] == ["api", "ai-agents"] and parts[3] == "toggle":
                    out = {"agent": ai_agent_registry.set_enabled(parts[2], body.get("enabled"), reason="disabled_by_operator")}
                elif len(parts) == 4 and parts[:2] == ["api", "ai-agents"] and parts[3] == "test":
                    scope = self._ai_conversation_scope()
                    with ai_universal_llm.usage_scope({
                        "user_id": scope.get("user_id"),
                        "user_name": scope.get("display_name"),
                        "workspace_id": scope.get("workspace_id"),
                        "conversation_id": "agent_connection_test",
                        "request_source": "agent_connection_test",
                    }):
                        out = ai_universal_llm.test_connection(
                            parts[2], str(body.get("prompt") or ""),
                        )
                elif len(parts) == 4 and parts[:2] == ["api", "ai-agents"] and parts[3] == "sync-balance":
                    out = {"agent": ai_universal_llm.sync_credit_balance(parts[2])}
                elif len(parts) == 4 and parts[:2] == ["api", "ai-agents"] and parts[3] == "delete":
                    out = ai_agent_registry.delete_agent(parts[2])
                else:
                    self._err(HTTPStatus.NOT_FOUND, f"no AI agents route: {path}")
                    return
            except (ai_agent_registry.AgentRegistryError,
                    ai_universal_llm.UniversalLLMError,
                    _secure_store.SecureStoreError) as exc:
                self._err(HTTPStatus.BAD_REQUEST, str(exc))
                return
            self._json(HTTPStatus.OK, out)
            return

        if is_ai_lab:
            body = self._read_body()
            if body is None:
                return
            self._ai_lab_post(path, body)
            return

        if is_governance:
            body = self._read_body()
            if body is None:
                return
            self._governance_post(path, body)
            return

        if path.startswith("/api/ops/runtime/account-history/"):
            body = self._read_body()
            if body is None:
                return
            try:
                context = getattr(self, "_remote_context", None) or {}
                workspace_context = context.get("workspace_context") or {}
                active_workspace = workspace_context.get("active_workspace") if isinstance(workspace_context, dict) else {}
                if isinstance(active_workspace, dict) and active_workspace and not active_workspace.get("uses_owner_runtime"):
                    workspace_id = str(active_workspace.get("workspace_id") or "")
                    if path == "/api/ops/runtime/account-history/classify":
                        out = workspaces.workspace_classify_event(
                            workspace_id, str(body.get("account_name") or ""), str(body.get("event_id") or ""),
                            str(body.get("kind") or ""), str(body.get("actor") or "ui"), str(body.get("note") or ""),
                        )
                    elif path == "/api/ops/runtime/account-history/events":
                        out = workspaces.workspace_add_event(
                            workspace_id, str(body.get("account_name") or ""), str(body.get("kind") or ""), body.get("amount"),
                            str(body.get("actor") or "ui"), str(body.get("note") or ""), body.get("at_utc"),
                            str(body.get("source") or "manual"), str(body.get("source_id") or ""),
                        )
                    elif path == "/api/ops/runtime/account-history/import":
                        out = workspaces.workspace_import_events(
                            workspace_id, str(body.get("account_name") or ""), body.get("rows") or [],
                            str(body.get("actor") or "ui"), str(body.get("source") or "broker_statement"),
                        )
                    else:
                        self._err(HTTPStatus.NOT_FOUND, f"no account-history route: {path}"); return
                    self._json(HTTPStatus.OK, out); return
                if path == "/api/ops/runtime/account-history/classify":
                    out = account_ledger.classify_event(
                        str(body.get("account_name") or ""), str(body.get("event_id") or ""),
                        str(body.get("kind") or ""), str(body.get("actor") or "ui"), str(body.get("note") or ""),
                    )
                elif path == "/api/ops/runtime/account-history/events":
                    out = account_ledger.add_event(
                        str(body.get("account_name") or ""), str(body.get("kind") or ""), body.get("amount"),
                        str(body.get("actor") or "ui"), str(body.get("note") or ""), body.get("at_utc"),
                        str(body.get("source") or "manual"), str(body.get("source_id") or ""),
                    )
                elif path == "/api/ops/runtime/account-history/import":
                    out = account_ledger.import_events(
                        str(body.get("account_name") or ""), body.get("rows") or [],
                        str(body.get("actor") or "ui"), str(body.get("source") or "broker_statement"),
                    )
                else:
                    self._err(HTTPStatus.NOT_FOUND, f"no account-history route: {path}"); return
                self._json(HTTPStatus.OK, out); return
            except ValueError as e:
                self._err(HTTPStatus.BAD_REQUEST, str(e)); return
            except Exception as e:
                self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"account ledger error: {e}"); return

        if is_portfolio:
            body = self._read_body()
            if body is None:
                return
            try:
                if path == "/api/portfolio/roots":
                    out = portfolio_registry.add_root(body.get("root"), body.get("slots", 15), body.get("start_id"), str(body.get("actor") or "ui"))
                elif path == "/api/portfolio/cells":
                    out = portfolio_registry.add_cell(body.get("root"), body.get("cell_id"), str(body.get("actor") or "ui"))
                elif len(parts) == 5 and parts[:3] == ["api", "portfolio", "cells"] and parts[4] == "archive":
                    out = portfolio_registry.archive_cell(urllib.parse.unquote(parts[3]), str(body.get("actor") or "ui"))
                else:
                    self._err(HTTPStatus.NOT_FOUND, f"no portfolio route: {path}")
                    return
            except ValueError as exc:
                self._err(HTTPStatus.BAD_REQUEST, str(exc))
                return
            except Exception as exc:
                self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"portfolio registry error: {exc}")
                return
            self._json(HTTPStatus.OK, out)
            return

        if is_ops or is_profiles:
            body = self._read_body()
            if body is None:
                return
            context = getattr(self, "_remote_context", None) or {}
            runtime_override = ""
            if path.startswith("/api/ops/runtime/"):
                runtime_override = workspaces.runtime_storage_dir_for_context(
                    context.get("workspace_context") or {}
                )
            if runtime_override:
                with ops_runtime.runtime_dir_override(runtime_override):
                    self._ops_post(path, body)
            else:
                self._ops_post(path, body)
            return

        if is_catalog_refresh:
            out = jobqueue.request_catalog_refresh()
            status = HTTPStatus.OK if out.get("ok") else HTTPStatus.GATEWAY_TIMEOUT
            self._json(status, out)
            return

        if is_margins_refresh:
            out = marginrefresh.refresh_margins_now(trigger="manual")
            status = HTTPStatus.OK if out.get("ok") else HTTPStatus.BAD_GATEWAY
            self._json(status, out)
            return

        if is_server_restart:
            # Enforced here as well as described in the payload: a client that
            # ignores the descriptor must not be able to relaunch a server from
            # a checkout.
            restart = _operations_actions()["restart"]
            if not restart["allowed"]:
                self._err(HTTPStatus.CONFLICT, restart["reason"],
                          code="restart_not_supervised")
                return
            self._json(HTTPStatus.OK, {"status": "restarting", "mode": restart["mode"]})
            t = threading.Timer(0.6, _do_restart_server)
            t.daemon = True
            t.start()
            return

        if is_cancel_job:
            try:
                jobqueue._safe_job_id(parts[2])
            except jobqueue.JobValidationError as e:
                self._err(HTTPStatus.BAD_REQUEST, str(e))
                return
            if not jobqueue.job_in_scope(parts[2], **self._data_scope()):
                self._err(HTTPStatus.NOT_FOUND, f"job not found: {parts[2]}")
                return
            try:
                out = jobqueue.cancel_job(parts[2])
            except jobqueue.JobValidationError as e:
                self._err(HTTPStatus.BAD_REQUEST, str(e))
                return
            if out.get("action") == "not_found":
                self._err(HTTPStatus.NOT_FOUND, f"job not found: {parts[2]}")
                return
            self._json(HTTPStatus.OK, out)
            return

        if is_cancel_batch:
            try:
                jobqueue._safe_batch_id(parts[2])
            except jobqueue.JobValidationError as e:
                self._err(HTTPStatus.BAD_REQUEST, str(e))
                return
            if not jobqueue.batch_in_scope(parts[2], **self._data_scope()):
                self._err(HTTPStatus.NOT_FOUND, f"batch not found: {parts[2]}")
                return
            try:
                out = jobqueue.cancel_batch(parts[2])
            except jobqueue.JobValidationError as e:
                self._err(HTTPStatus.BAD_REQUEST, str(e))
                return
            if not out.get("found"):
                self._err(HTTPStatus.NOT_FOUND, f"batch not found: {parts[2]}")
                return
            self._json(HTTPStatus.OK, out)
            return

        body = self._read_body()
        if body is None:
            return  # _read_body already wrote an error

        if is_report_favorites:
            try:
                if path == "/api/report-favorites":
                    kind = str(body.get("kind") or "")
                    report_id = str(body.get("id") or body.get("report_id") or "")
                    if not jobqueue.report_in_scope(
                            kind, report_id, **self._data_scope()):
                        self._err(HTTPStatus.NOT_FOUND, "report not found")
                        return
                    out = jobqueue.favorite_report(
                        kind,
                        report_id,
                        description=(str(body["description"]) if "description" in body else None),
                    )
                    self._json(HTTPStatus.OK, out)
                    return
                fav_parts = [p for p in path.split("/") if p]
                if len(fav_parts) == 5 and fav_parts[0] == "api" and fav_parts[1] == "report-favorites" and fav_parts[4] == "repeat":
                    if not jobqueue.report_in_scope(
                            fav_parts[2], fav_parts[3], **self._data_scope()):
                        self._err(HTTPStatus.NOT_FOUND, "report not found")
                        return
                    origin = self._write_origin()
                    if origin is None:
                        return
                    out = jobqueue.repeat_report_favorite(
                        fav_parts[2], fav_parts[3], origin_override=origin)
                    self._json(HTTPStatus.CREATED, out)
                    return
                if len(fav_parts) == 5 and fav_parts[0] == "api" and fav_parts[1] == "report-favorites" and fav_parts[4] == "description":
                    if not jobqueue.report_in_scope(
                            fav_parts[2], fav_parts[3], **self._data_scope()):
                        self._err(HTTPStatus.NOT_FOUND, "report not found")
                        return
                    out = jobqueue.update_report_favorite(
                        fav_parts[2],
                        fav_parts[3],
                        {"description": body.get("description")},
                    )
                    self._json(HTTPStatus.OK, out)
                    return
            except jobqueue.JobValidationError as e:
                self._err(HTTPStatus.BAD_REQUEST, str(e))
                return
            except Exception as e:  # pragma: no cover
                self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"favorite error: {e}")
                return
            self._err(HTTPStatus.NOT_FOUND, f"no route: {path}")
            return

        if path == "/api/batches":
            origin = self._write_origin()
            if origin is None:
                return
            try:
                req = jobqueue.CreateBatchRequest(
                    class_name=str(body.get("class_name") or ""),
                    instruments=list(body.get("instruments") or []),
                    bars_period_type=str(body.get("bars_period_type") or "Minute"),
                    bars_period_value=int(body.get("bars_period_value") or 1),
                    from_utc=str(body.get("from_utc") or ""),
                    to_utc=str(body.get("to_utc") or ""),
                    parameters=body.get("parameters") or {},
                    risk_profile=body.get("risk_profile") or {},
                    calculate=str(body.get("calculate") or "OnBarClose"),
                    is_tick_replay=bool(body.get("is_tick_replay") or False),
                    order_fill_resolution=str(body.get("order_fill_resolution") or "High"),
                    slippage_ticks=int(body.get("slippage_ticks") or 1),
                    commission=float(body.get("commission") or 0.0),
                    commission_template=str(body.get("commission_template") or "None"),
                    session_template=str(body.get("session_template") or "CME US Index Futures RTH"),
                    timezone=str(body.get("timezone") or "UTC"),
                    role=str(body.get("role") or "research"),
                    name=(str(body["name"]) if body.get("name") else None),
                    origin=origin,
                )
            except (TypeError, ValueError) as e:
                self._err(HTTPStatus.BAD_REQUEST, f"bad request: {e}")
                return
            try:
                batch_id, job_ids = jobqueue.create_batch(req)
            except jobqueue.JobValidationError as e:
                self._err(HTTPStatus.BAD_REQUEST, str(e))
                return
            self._json(HTTPStatus.CREATED, {
                "batch_id": batch_id,
                "job_ids":  job_ids,
                "total":    len(job_ids),
            })
            return

        # Defensive whitelist of allowed top-level keys: never accept paths/ids
        # that could escape the queue.
        origin = self._write_origin()
        if origin is None:
            return

        if path == "/api/practice/orders/cancel":
            if not self._check_local_post():
                return
            body = self._read_body() or {}
            context = getattr(self, "_remote_context", None) or {}
            try:
                out = practice_trading.cancel_order(
                    context.get("user_id"), str(body.get("order_id") or ""),
                    workspace_id=str(context.get("workspace_id") or ""),
                )
                self._json(HTTPStatus.OK, out)
            except practice_trading.PracticeTradingError as exc:
                self._err(exc.status, str(exc))
            return
        try:
            req = jobqueue.CreateJobRequest(
                class_name=str(body.get("class_name") or ""),
                instrument=str(body.get("instrument") or ""),
                bars_period_type=str(body.get("bars_period_type") or "Minute"),
                bars_period_value=int(body.get("bars_period_value") or 1),
                from_utc=str(body.get("from_utc") or ""),
                to_utc=str(body.get("to_utc") or ""),
                parameters=body.get("parameters") or {},
                risk_profile=body.get("risk_profile") or {},
                calculate=str(body.get("calculate") or "OnBarClose"),
                is_tick_replay=bool(body.get("is_tick_replay") or False),
                order_fill_resolution=str(body.get("order_fill_resolution") or "High"),
                slippage_ticks=int(body.get("slippage_ticks") or 1),
                commission=float(body.get("commission") or 0.0),
                commission_template=str(body.get("commission_template") or "None"),
                session_template=str(body.get("session_template") or "CME US Index Futures RTH"),
                timezone=str(body.get("timezone") or "UTC"),
                role=str(body.get("role") or "research"),
                job_id=None,  # never trust client-supplied ids
                origin=origin,
            )
        except (TypeError, ValueError) as e:
            self._err(HTTPStatus.BAD_REQUEST, f"bad request: {e}")
            return

        try:
            job_id, path = jobqueue.create_job(req)
        except jobqueue.JobValidationError as e:
            self._err(HTTPStatus.BAD_REQUEST, str(e))
            return

        self._json(HTTPStatus.CREATED, {"job_id": job_id, "path": str(path)})


# ---------------------------------------------------------------------------

def _bind_or_pick_port(
    start_port: int = DEFAULT_PORT,
    attempts: int = 10,
    *,
    host: str = HOST,
) -> int:
    """Return a free port on the validated bind host."""
    for off in range(attempts):
        port = start_port + off
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((host, port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"no free port in {start_port}..{start_port+attempts-1}")


def create_http_server(
    deployment: runtime_env.DeploymentConfig,
    *,
    bind_port: int,
) -> api_admission.BoundedThreadingHTTPServer:
    """Build the same bounded HTTP contour used by the executable entrypoint.

    Keeping this construction in one place prevents integration/load probes
    from accidentally bypassing admission control or the deployment edge
    policy by instantiating a bare ``ThreadingHTTPServer``.
    """
    server = api_admission.BoundedThreadingHTTPServer(
        (deployment.bind_host, int(bind_port)), Handler,
        max_inflight=deployment.api_max_inflight,
        max_websockets=deployment.api_max_websockets,
        backlog=deployment.api_backlog,
        max_body_bytes=deployment.api_max_body_bytes,
    )
    server.deployment_config = deployment  # type: ignore[attr-defined]
    server.readiness_probes = {  # type: ignore[attr-defined]
        "connector_control": connector_protocol.readiness_status,
        "connector_releases": connector_releases.readiness_status,
    }
    server.readiness_optional_components = {}  # type: ignore[attr-defined]
    if deployment.environment in (runtime_env.PRODUCTION, runtime_env.CANARY):
        # Canary is held to the same readiness contract as Production (see
        # service_readiness.readiness_payload's PRODUCTION_COMPONENTS list),
        # so it needs the same real probes registered against its own
        # isolated database/storage/signing-key identity, not Production's.
        from . import storage_router
        from .production_storage.artifacts import object_storage_readiness
        server.readiness_probes.update({  # type: ignore[attr-defined]
            "database": storage_router.database_readiness,
            "object_storage": object_storage_readiness,
            "queue": production_workers.readiness_status,
            "signing_key": storage_router.signing_key_readiness,
        })
        telegram_configured = bool(
            str(os.environ.get(telegram_service.TOKEN_ENV) or "").strip()
        )
        if deployment.environment == runtime_env.PRODUCTION or telegram_configured:
            server.readiness_probes["telegram_consumer"] = (  # type: ignore[attr-defined]
                production_telegram.readiness_status
            )
        else:
            # A real Canary bot has not been provisioned yet (see
            # deploy/canary/README.md). Registering production_telegram's
            # probe here would check whether a consumer process is actively
            # leased -- one that architecturally cannot exist without a
            # token -- and misreport an honestly-disabled feature as a
            # broken/offline component. Readiness still surfaces this gap
            # (checks.telegram_consumer.ok stays False) but it no longer
            # forces the whole endpoint into a permanent 503; acceptance
            # tracking must keep reporting Telegram as PARTIAL, not PASS.
            server.readiness_optional_components["telegram_consumer"] = (  # type: ignore[attr-defined]
                "disabled_pending_canary_bot_provisioning"
            )

    # Environment registry heartbeat. Every environment publishes its own
    # identity, including LOCAL -- which is the whole reason the registry
    # exists, since nothing can reach a development machine behind NAT to ask.
    # Starting it needs no token: without one, publish_to declines and only the
    # local self-record happens, which is still useful and still honest.
    #
    # Readiness is supplied by the same code path /api/ready uses, probes and
    # all. Recomputing it without those registered probes reports a healthy
    # service as not_ready, which is worse than reporting nothing.
    def _publisher_readiness() -> Dict[str, Any]:
        return service_readiness.readiness_payload(
            server.deployment_config,  # type: ignore[attr-defined]
            probes=server.readiness_probes,  # type: ignore[attr-defined]
            optional_components=server.readiness_optional_components,  # type: ignore[attr-defined]
        )

    # Publish which data root this process is actually serving. Tooling checks
    # this instead of re-deriving it, because a maintenance script that
    # resolves a different directory reports confidently on a store nobody
    # serves -- which is exactly how a whole account inventory came back
    # fictional.
    data_root_guard.publish_active_root(deployment.environment)

    server.environment_publisher = environment_registry.HeartbeatPublisher(  # type: ignore[attr-defined]
        readiness=_publisher_readiness,
    )
    server.environment_publisher.start()  # type: ignore[attr-defined]
    return server


def run(port: Optional[int] = None) -> None:
    try:
        deployment = runtime_env.assert_startup_safe()
        if deployment.environment in {runtime_env.PRODUCTION, runtime_env.CANARY}:
            from . import storage_router
            storage_router.assert_production_storage_safe()
    except runtime_env.RuntimeEnvError as exc:
        print(f"[nta-backend] FATAL: {exc}")
        raise SystemExit(2) from exc
    except Exception as exc:
        from .production_storage import StorageError
        if not isinstance(exc, StorageError):
            raise
        print(f"[nta-backend] FATAL: server storage configuration invalid ({exc.code}).")
        raise SystemExit(2) from exc
    env = runtime_env.status()
    if (
        deployment.environment in {runtime_env.PRODUCTION, runtime_env.CANARY}
        and deployment.deployment_role not in {"api", "all-in-one"}
    ):
        print("[nta-backend] FATAL: HTTP server requires deployment role api/all-in-one.")
        raise SystemExit(2)
    print(
        "[nta-backend] "
        f"environment={deployment.environment} "
        f"profile={deployment.runtime_profile} "
        f"instance={deployment.instance_id} "
        f"role={deployment.deployment_role} "
        f"build={deployment.build_version} "
        f"build_id={deployment.build_id} "
        f"git={deployment.git_commit_sha[:12]} "
        f"channel={deployment.release_channel} "
        f"dirty={str(deployment.dirty).lower()} "
        f"test_auth={env['test_auth_enabled']} "
        f"impersonation={env['impersonation_enabled']}"
    )
    bind_host = deployment.bind_host
    bind_port = port or _bind_or_pick_port(DEFAULT_PORT, host=bind_host)
    # The owner market-data gateway refuses to consume an origin that resolves
    # back to this process; it needs the port we actually bound.
    owner_market_data_gateway.set_local_bind_port(bind_port)
    server = create_http_server(deployment, bind_port=bind_port)
    print(f"[nta-backend] listening on http://{bind_host}:{bind_port}/")
    print(f"[nta-backend] UI:           http://{bind_host}:{bind_port}/ui/")
    print(f"[nta-backend] project_root: {jobqueue.project_root()}")
    print(f"[nta-backend] jobs_dir: {jobqueue.jobs_dir()}")
    production_api = deployment.environment == runtime_env.PRODUCTION
    canary_api = deployment.environment == runtime_env.CANARY
    _heartbeat_emitter: Optional[observability.HeartbeatEmitter] = None
    try:
        _heartbeat_emitter = observability.HeartbeatEmitter(
            "api", interval_sec=10,
            details=lambda: {
                "admission": (
                    server.admission_metrics()
                    if callable(getattr(server, "admission_metrics", None)) else {}
                ),
            },
        )
        _heartbeat_emitter.start()
        print("[nta-backend] observability heartbeat emitter started (every 10 sec)")
    except Exception as e:
        print(f"[nta-backend] observability heartbeat NOT started: {e}")
    if production_api:
        print(
            "[nta-backend] Production background work is owned by "
            "stratforge-worker.service; Telegram by stratforge-telegram.service"
        )
    else:
        # Development keeps all local single-process helpers. Canary keeps the
        # legacy singleton schedulers here, but queue and Telegram consumers are
        # owned by the split Canary topology below.
        try:
            ai_stale_sweep.start_background_sweeper(
                interval_sec=1800, ttl_hours=6.0,
            )
            print("[nta-backend] ai-lab stale sweeper started (TTL=6h, every 30 min)")
        except Exception as e:
            print(f"[nta-backend] ai-lab stale sweeper NOT started: {e}")
        try:
            news_refresh.start_background_refresher()
            print("[nta-backend] news refresher started (live every 15 min)")
        except Exception as e:
            print(f"[nta-backend] news refresher NOT started: {e}")
        if canary_api:
            print("[nta-backend] Canary queue work is owned by worker-canary; local worker not started")
        else:
            try:
                local_worker.start_background_worker(interval_sec=2.0)
                print("[nta-backend] local worker process started")
            except Exception as e:
                print(f"[nta-backend] local worker process NOT started: {e}")
        if canary_api:
            print("[nta-backend] Canary Telegram is owned by the supervised server consumer when configured")
        else:
            try:
                telegram_service.start_background_notifier(interval_sec=30)
                print("[nta-backend] Telegram notifier started (every 30 sec)")
            except Exception as e:
                print(f"[nta-backend] Telegram notifier NOT started: {e}")
        try:
            ai_chief_agent.start_background_worker(interval_sec=30)
            print("[nta-backend] StratForge Orchestrator started (every 30 sec)")
        except Exception as e:
            print(f"[nta-backend] StratForge Orchestrator NOT started: {e}")
        try:
            vitek.start_background_worker(interval_sec=1)
            print("[nta-backend] Vitek duty controller started (event-driven)")
        except Exception as e:
            print(f"[nta-backend] Vitek duty controller NOT started: {e}")
        try:
            market_data.start_chart_worker(interval_sec=1.0)
            print("[nta-backend] headless chart scheduler started (every 1 sec)")
        except Exception as e:
            print(f"[nta-backend] headless chart scheduler NOT started: {e}")
        try:
            ipc = market_data_ipc.start_server()
            print(
                f"[nta-backend] market-data IPC listening on 127.0.0.1:{ipc.port} "
                f"(token_fp={market_data_ipc.token_fingerprint(market_data_ipc.auth_token())})"
            )
        except Exception as e:
            print(f"[nta-backend] market-data IPC NOT started: {e}")
        try:
            market_data_gap_recovery.start_background_worker(interval_sec=2.0)
            print("[nta-backend] market-data gap recovery worker started")
        except Exception as e:
            print(f"[nta-backend] market-data gap recovery NOT started: {e}")
        try:
            live_st = market_data_live_supervisor.start()
            print(
                "[nta-backend] market-data live sources: "
                f"credentialed={live_st.get('credentialed_providers')} "
                f"connected={live_st.get('live_providers_connected')} "
                f"blocked={live_st.get('production_blocked')}"
            )
        except Exception as e:
            print(f"[nta-backend] market-data live sources NOT started: {e}")
    sys.stdout.flush()
    prior_signal_handlers = {}

    def _graceful_stop(signum, _frame):
        print(f"[nta-backend] shutdown signal={signum}")
        threading.Thread(target=server.shutdown, daemon=True).start()

    if threading.current_thread() is threading.main_thread():
        for stop_signal in (signal.SIGTERM, signal.SIGINT):
            try:
                prior_signal_handlers[stop_signal] = signal.getsignal(stop_signal)
                signal.signal(stop_signal, _graceful_stop)
            except (AttributeError, OSError, ValueError):
                pass
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("[nta-backend] shutting down")
    finally:
        for stop_signal, prior_handler in prior_signal_handlers.items():
            try:
                signal.signal(stop_signal, prior_handler)
            except (OSError, ValueError):
                pass
        if _heartbeat_emitter:
            _heartbeat_emitter.stop()
        ai_stale_sweep.stop_background_sweeper()
        news_refresh.stop_background_refresher()
        ai_chief_agent.stop_background_worker()
        vitek.stop_background_worker()
        local_worker.stop_background_worker()
        telegram_service.stop_background_notifier()
        market_data.stop_chart_worker()
        try:
            market_data_gap_recovery.stop_background_worker()
        except Exception:
            pass
        try:
            market_data_ipc.stop_server()
        except Exception:
            pass
        try:
            market_data_live_supervisor.stop()
        except Exception:
            pass
        server.server_close()


if __name__ == "__main__":
    p = None
    if len(sys.argv) > 1:
        try:
            p = int(sys.argv[1])
        except ValueError:
            pass
    run(p)
