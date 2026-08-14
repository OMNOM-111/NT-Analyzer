from __future__ import annotations

import json
import os
import tempfile
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from types import SimpleNamespace

from app import market_data_failover as failover
from app import market_data_live_adapters as live_adapters
from app import owner_market_data_gateway as gw
from app import server as server_mod


TOKEN = "owner-gateway-token-16"
GATEWAY = "http://127.0.0.1:18767"


def _lease_env(monkeypatch) -> Path:
    path = Path(tempfile.gettempdir()) / f"sf-md-hub-lease-{os.getpid()}-gw.json"
    monkeypatch.setenv("NTA_OWNER_MARKET_DATA_GATEWAY_LEASE_PATH", str(path))
    gw.reset_lease_for_tests()
    if path.exists():
        path.unlink()
    return path


def _reset_provider() -> None:
    failover.TopstepXProvider._adapter_instance = None
    failover.TopstepXProvider._credential_fingerprint = ""
    live_adapters.topstepx_session_manager().reset_for_tests()


def _consumer_env(monkeypatch) -> None:
    _reset_provider()
    _lease_env(monkeypatch)
    monkeypatch.setattr(live_adapters.secure_store, "available", lambda: False)
    monkeypatch.setenv("NTA_APP_ENV", "staging")
    monkeypatch.setenv("STRATFORGE_DEPLOYMENT_ROLE", "api")
    monkeypatch.setenv("NTA_OWNER_MARKET_DATA_GATEWAY_ROLE", "consumer")
    monkeypatch.setenv("NTA_OWNER_MARKET_DATA_GATEWAY_URL", GATEWAY)
    monkeypatch.setenv("NTA_OWNER_MARKET_DATA_GATEWAY_TOKEN", TOKEN)
    monkeypatch.setenv("NTA_ENABLE_TOPSTEPX_MARKET_DATA", "1")
    monkeypatch.setenv("NTA_TOPSTEPX_USERNAME", "owner_user")
    monkeypatch.setenv("NTA_TOPSTEPX_API_KEY", "real-projectx-key")
    monkeypatch.setenv("NTA_TOPSTEPX_DATA_MODE", "sim")
    monkeypatch.delenv("NTA_ENABLE_TOPSTEPX_LIVE", raising=False)


def _hub_env(monkeypatch) -> None:
    _reset_provider()
    _lease_env(monkeypatch)
    monkeypatch.setattr(live_adapters.secure_store, "available", lambda: False)
    monkeypatch.setenv("NTA_APP_ENV", "staging")
    monkeypatch.setenv("STRATFORGE_DEPLOYMENT_ROLE", "api")
    monkeypatch.setenv("NTA_OWNER_MARKET_DATA_GATEWAY_ROLE", "hub")
    monkeypatch.setenv("NTA_OWNER_MARKET_DATA_GATEWAY_TOKEN", TOKEN)
    monkeypatch.delenv("NTA_OWNER_MARKET_DATA_GATEWAY_URL", raising=False)
    monkeypatch.setenv("NTA_ENABLE_TOPSTEPX_MARKET_DATA", "1")
    monkeypatch.setenv("NTA_TOPSTEPX_USERNAME", "owner_user")
    monkeypatch.setenv("NTA_TOPSTEPX_API_KEY", "real-projectx-key")
    monkeypatch.setenv("NTA_TOPSTEPX_DATA_MODE", "sim")


class _FakeResponse:
    def __init__(self, payload: dict, status: int = 200) -> None:
        self.status = status
        self._payload = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._payload

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *_args) -> bool:
        return False


def test_normalize_origin_allowlist() -> None:
    assert gw.normalize_gateway_origin("http://127.0.0.1:18767") == "http://127.0.0.1:18767"
    assert gw.normalize_gateway_origin("https://app.stratforges.com") == "https://app.stratforges.com"
    assert gw.normalize_gateway_origin("https://canary.stratforges.com/") == "https://canary.stratforges.com"
    assert gw.normalize_gateway_origin("http://evil.example:80") == ""
    assert gw.normalize_gateway_origin("https://app.stratforges.com/api") == ""
    assert gw.normalize_gateway_origin("http://user:pass@127.0.0.1:18767") == ""


def test_consumer_does_not_open_projectx_hub(monkeypatch) -> None:
    _consumer_env(monkeypatch)
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    projectx_calls = []

    def post(url, payload, **_kwargs):
        projectx_calls.append(url)
        raise AssertionError(f"consumer must not call ProjectX: {url}")

    def urlopen(request, timeout=None):
        url = str(getattr(request, "full_url", "") or request.get_full_url())
        assert "/api/ops/runtime/bars" in url
        headers = {str(key).lower(): str(value) for key, value in request.header_items()}
        assert headers.get("x-stratforge-owner-market-gateway-token") == TOKEN
        assert headers.get("x-stratforge-owner-market-gateway") == "consume"
        return _FakeResponse({
            "instrument": "MNQ 09-26",
            "bars": [{
                "t": now.isoformat().replace("+00:00", "Z"),
                "o": 21000.0, "h": 21002.0, "l": 20999.0, "c": 21001.0, "v": 12,
            }],
            "live": False,
            "status": "external_connecting",
            "source": {"provider": "topstepx", "runtime_state": "CONNECTING", "direct_market_hub": True},
            "freshness": {"market_feed_fresh": False, "market_feed_stale": False},
        })

    monkeypatch.setattr(live_adapters, "_post_json", post)
    monkeypatch.setattr(gw.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(gw.OwnerGatewayChartAdapter, "connect", lambda self: self.health())

    assert gw.should_consume() is True
    assert gw.should_open_direct_hub() is False
    assert live_adapters.TopstepXProjectXAdapter.enabled() is False
    provider = failover.TopstepXProvider()
    assert provider.configured() is True
    payload = provider.fetch("MNQ", "1m", 20)
    assert projectx_calls == []
    assert payload["source"]["provider"] == "topstepx"
    assert payload["source"]["via"] == "owner_gateway"
    assert payload["source"]["direct_market_hub"] is False
    assert payload["instrument"] == "MNQ 09-26"
    # The hub serves already-normalised t/o/h/l/c/v rows; they must survive the
    # consumer hop unchanged, otherwise charts render empty behind the gateway.
    assert [row["c"] for row in payload["bars"]] == [21001.0]
    assert payload["bars"][0]["v"] == 12
    health = provider._adapter().health()
    assert health["session_audit"]["login_key_calls"] == 0
    assert isinstance(provider._adapter(), gw.OwnerGatewayChartAdapter)


def test_hub_keeps_direct_projectx_when_role_is_hub(monkeypatch) -> None:
    _hub_env(monkeypatch)
    monkeypatch.setattr(live_adapters.runtime_env, "is_development", lambda: True)
    assert gw.should_open_direct_hub() is True
    assert gw.should_consume() is False
    assert live_adapters.TopstepXProjectXAdapter.enabled() is True
    provider = failover.TopstepXProvider()
    assert provider.configured() is True


def test_worker_never_opens_direct_hub(monkeypatch) -> None:
    _hub_env(monkeypatch)
    monkeypatch.setenv("STRATFORGE_DEPLOYMENT_ROLE", "worker")
    monkeypatch.delenv("NTA_OWNER_MARKET_DATA_GATEWAY_ROLE", raising=False)
    assert gw.should_open_direct_hub() is False
    assert gw.should_consume() is False
    assert live_adapters.TopstepXProjectXAdapter.enabled() is False
    assert failover.TopstepXProvider().configured() is False


def test_fail_closed_auto_does_not_open_hub_with_credentials(monkeypatch) -> None:
    _reset_provider()
    _lease_env(monkeypatch)
    monkeypatch.setenv("NTA_APP_ENV", "staging")
    monkeypatch.setenv("STRATFORGE_DEPLOYMENT_ROLE", "api")
    monkeypatch.setenv("NTA_OWNER_MARKET_DATA_GATEWAY_ROLE", "auto")
    monkeypatch.delenv("NTA_OWNER_MARKET_DATA_GATEWAY_URL", raising=False)
    monkeypatch.delenv("NTA_OWNER_MARKET_DATA_GATEWAY_TOKEN", raising=False)
    monkeypatch.setenv("NTA_TOPSTEPX_USERNAME", "owner_user")
    monkeypatch.setenv("NTA_TOPSTEPX_API_KEY", "real-projectx-key")
    monkeypatch.setenv("NTA_ENABLE_TOPSTEPX_MARKET_DATA", "1")
    monkeypatch.setenv("NTA_TOPSTEPX_DATA_MODE", "sim")
    assert gw.effective_role() == "isolated"
    assert gw.should_open_direct_hub() is False
    assert gw.should_consume() is False
    assert gw.chart_source_mode() == "internal_cache_or_runtime"
    assert live_adapters.TopstepXProjectXAdapter.enabled() is False
    assert failover.TopstepXProvider().configured() is False
    status = gw.public_status()
    assert "owner_credentials_present_but_direct_hub_forbidden" in status["warnings"]
    assert status["observability"]["direct_provider_connections"] == 0
    assert status["owner"]["pid"] == os.getpid()


def test_self_url_auto_is_isolated(monkeypatch) -> None:
    _reset_provider()
    monkeypatch.setenv("NTA_APP_ENV", "staging")
    monkeypatch.setenv("STRATFORGE_DEPLOYMENT_ROLE", "api")
    monkeypatch.setenv("STRATFORGE_BIND_PORT", "18767")
    monkeypatch.setenv("NTA_OWNER_MARKET_DATA_GATEWAY_ROLE", "auto")
    monkeypatch.setenv("NTA_OWNER_MARKET_DATA_GATEWAY_URL", "http://127.0.0.1:18767")
    monkeypatch.setenv("NTA_OWNER_MARKET_DATA_GATEWAY_TOKEN", TOKEN)
    assert gw.points_at_self("http://127.0.0.1:18767") is True
    assert gw.should_consume() is False
    assert gw.should_open_direct_hub() is False
    assert gw.effective_role() == "isolated"


def test_self_loop_guard_uses_the_port_the_server_actually_bound(monkeypatch) -> None:
    # The deployment host starts the API as `python -m app.server 18767`, so
    # STRATFORGE_BIND_PORT is absent and the default 8765 is wrong.
    _reset_provider()
    monkeypatch.setattr(gw, "_LOCAL_BIND_PORT", 0)
    monkeypatch.delenv("STRATFORGE_BIND_PORT", raising=False)
    monkeypatch.setenv("STRATFORGE_DEPLOYMENT_ROLE", "api")
    monkeypatch.setenv("NTA_OWNER_MARKET_DATA_GATEWAY_ROLE", "consumer")
    monkeypatch.setenv("NTA_OWNER_MARKET_DATA_GATEWAY_URL", "http://127.0.0.1:18767")
    monkeypatch.setenv("NTA_OWNER_MARKET_DATA_GATEWAY_TOKEN", TOKEN)
    assert gw.points_at_self("http://127.0.0.1:18767") is False
    assert gw.should_consume() is True
    gw.set_local_bind_port(18767)
    assert gw.points_at_self("http://127.0.0.1:18767") is True
    assert gw.should_consume() is False
    assert gw.effective_role() == "isolated"


def test_production_auto_is_fail_closed(monkeypatch) -> None:
    monkeypatch.setenv("DEPLOYMENT_ENV", "production")
    monkeypatch.setenv("STRATFORGE_DEPLOYMENT_ROLE", "api")
    monkeypatch.setenv("NTA_OWNER_MARKET_DATA_GATEWAY_ROLE", "auto")
    monkeypatch.setenv("NTA_OWNER_MARKET_DATA_GATEWAY_URL", "http://127.0.0.1:18765")
    monkeypatch.setenv("NTA_OWNER_MARKET_DATA_GATEWAY_TOKEN", TOKEN)
    monkeypatch.setattr(gw, "_environment", lambda: "production")
    monkeypatch.setattr(gw, "_api_role", lambda: True)
    assert gw.gateway_url() == ""
    assert gw.should_consume() is False
    assert gw.is_hub() is False
    assert gw.effective_role() == "isolated"


def test_canary_auto_consumes_production_internal_origin(monkeypatch) -> None:
    monkeypatch.setenv("STRATFORGE_DEPLOYMENT_ROLE", "api")
    monkeypatch.setenv("NTA_OWNER_MARKET_DATA_GATEWAY_ROLE", "auto")
    monkeypatch.delenv("NTA_OWNER_MARKET_DATA_GATEWAY_URL", raising=False)
    monkeypatch.setenv("STRATFORGE_PRODUCTION_INTERNAL_ORIGIN", "http://127.0.0.1:18767")
    monkeypatch.setenv("NTA_OWNER_MARKET_DATA_GATEWAY_TOKEN", TOKEN)
    monkeypatch.setenv("STRATFORGE_BIND_PORT", "18765")
    monkeypatch.setattr(gw, "_environment", lambda: "canary")
    monkeypatch.setattr(gw, "_api_role", lambda: True)
    monkeypatch.setattr(gw, "_own_listen_targets", lambda: [("127.0.0.1", 18765)])
    assert gw.gateway_url() == "http://127.0.0.1:18767"
    assert gw.should_consume() is True
    assert gw.should_open_direct_hub() is False


def test_explicit_consumer_uses_the_environment_hub_origin(monkeypatch) -> None:
    # Naming the role must not leave Canary with fewer ways to reach the hub
    # than ROLE=auto: without this, a deployed consumer went isolated and
    # served empty charts.
    monkeypatch.setenv("STRATFORGE_DEPLOYMENT_ROLE", "api")
    monkeypatch.setenv("NTA_OWNER_MARKET_DATA_GATEWAY_ROLE", "consumer")
    monkeypatch.delenv("NTA_OWNER_MARKET_DATA_GATEWAY_URL", raising=False)
    monkeypatch.setenv("STRATFORGE_PRODUCTION_INTERNAL_ORIGIN", "http://127.0.0.1:18767")
    monkeypatch.setenv("NTA_OWNER_MARKET_DATA_GATEWAY_TOKEN", TOKEN)
    monkeypatch.setattr(gw, "_environment", lambda: "canary")
    monkeypatch.setattr(gw, "_api_role", lambda: True)
    monkeypatch.setattr(gw, "_own_listen_targets", lambda: [("127.0.0.1", 18765)])
    assert gw.gateway_url() == "http://127.0.0.1:18767"
    assert gw.should_consume() is True
    assert gw.effective_role() == "consumer"
    assert gw.chart_source_mode() == "owner_gateway_consumer"


def test_explicit_consumer_without_any_hub_origin_stays_isolated(monkeypatch) -> None:
    monkeypatch.setenv("STRATFORGE_DEPLOYMENT_ROLE", "api")
    monkeypatch.setenv("NTA_OWNER_MARKET_DATA_GATEWAY_ROLE", "consumer")
    monkeypatch.delenv("NTA_OWNER_MARKET_DATA_GATEWAY_URL", raising=False)
    monkeypatch.delenv("STRATFORGE_PRODUCTION_INTERNAL_ORIGIN", raising=False)
    monkeypatch.setenv("NTA_OWNER_MARKET_DATA_GATEWAY_TOKEN", TOKEN)
    monkeypatch.setattr(gw, "_environment", lambda: "canary")
    monkeypatch.setattr(gw, "_api_role", lambda: True)
    assert gw.gateway_url() == ""
    assert gw.should_consume() is False
    assert gw.should_open_direct_hub() is False
    assert gw.effective_role() == "isolated"


def _auth_request(headers: dict, path: str = "/api/ops/runtime/bars"):
    errors = []

    class Request:
        def __init__(self) -> None:
            self.path = path
            self.command = "GET"
            self.headers = headers
            self._remote_context = None

        def _local_owner_bypass_allowed(self):
            return False

        def _request_ips(self):
            return "", ""

        def _cookie_value(self, _name):
            return ""

        def _err(self, status, message, **kwargs):
            errors.append((int(status), message, str(kwargs.get("code") or "")))

    return Request(), errors


def test_gateway_token_authorizes_chart_path_only(monkeypatch) -> None:
    _hub_env(monkeypatch)
    request, errors = _auth_request({
        gw.TOKEN_HEADER: TOKEN,
        gw.MODE_HEADER: gw.MODE_CONSUME,
    })
    assert server_mod.Handler._authorize_api(request, "/api/ops/runtime/bars") is True
    assert request._remote_context["owner_market_gateway"] is True
    assert request._remote_context["is_owner"] is True
    assert errors == []

    admin, admin_errors = _auth_request({gw.TOKEN_HEADER: TOKEN}, "/api/release-center/status")
    admin.path = "/api/release-center/status"
    monkeypatch.setattr(server_mod.account_auth, "authenticate_session", lambda _token: None)
    assert server_mod.Handler._authorize_api(admin, "/api/release-center/status") is False
    assert admin_errors and admin_errors[-1][0] == 401


def test_gateway_token_mismatch_is_unauthorized(monkeypatch) -> None:
    _hub_env(monkeypatch)
    request, errors = _auth_request({gw.TOKEN_HEADER: "wrong-token-value-16"})
    assert server_mod.Handler._authorize_api(request, "/api/ops/runtime/bars") is False
    assert errors and errors[-1][0] == 401
    assert errors[-1][2] == "owner_gateway_unauthorized"


def test_consumer_rejects_inbound_consume_loop(monkeypatch) -> None:
    _consumer_env(monkeypatch)
    request, errors = _auth_request({
        gw.TOKEN_HEADER: TOKEN,
        gw.MODE_HEADER: gw.MODE_CONSUME,
    })
    assert server_mod.Handler._authorize_api(request, "/api/ops/runtime/bars") is False
    assert errors and errors[-1][0] == 403
    assert errors[-1][2] == "owner_gateway_loop_detected"


def test_loopback_edge_allows_token_on_chart_path(monkeypatch) -> None:
    _hub_env(monkeypatch)
    handler = SimpleNamespace(
        client_address=("127.0.0.1", 54321),
        path="/api/ops/runtime/bars?instrument=MNQ",
        headers={gw.TOKEN_HEADER: TOKEN},
    )
    assert gw.allows_loopback_chart_edge(handler) is True
    handler.client_address = ("203.0.113.10", 443)
    assert gw.allows_loopback_chart_edge(handler) is False
    handler.client_address = ("127.0.0.1", 54321)
    handler.path = "/api/admin/users"
    assert gw.allows_loopback_chart_edge(handler) is False


def test_isolated_token_does_not_authorize_charts(monkeypatch) -> None:
    _reset_provider()
    _lease_env(monkeypatch)
    monkeypatch.setenv("NTA_OWNER_MARKET_DATA_GATEWAY_ROLE", "auto")
    monkeypatch.setenv("NTA_OWNER_MARKET_DATA_GATEWAY_TOKEN", TOKEN)
    monkeypatch.setenv("STRATFORGE_DEPLOYMENT_ROLE", "api")
    request, errors = _auth_request({
        gw.TOKEN_HEADER: TOKEN,
        gw.MODE_HEADER: gw.MODE_CONSUME,
    })
    assert server_mod.Handler._authorize_api(request, "/api/ops/runtime/bars") is False
    assert errors and errors[-1][0] == 401


def test_hub_lease_blocks_duplicate_owner(monkeypatch) -> None:
    _hub_env(monkeypatch)
    path = Path(os.environ["NTA_OWNER_MARKET_DATA_GATEWAY_LEASE_PATH"])
    first = gw.acquire_hub_lease()
    assert first["held"] is True
    assert first["duplicate_blocked"] is False
    gw.reset_lease_for_tests()
    other_pid = os.getppid() or 4
    if other_pid == os.getpid() or not gw._pid_alive(other_pid):
        other_pid = 4
    expires = (datetime.now(timezone.utc) + timedelta(seconds=60)).isoformat().replace("+00:00", "Z")
    path.write_text(json.dumps({
        "lease_id": "other-hub",
        "pid": other_pid,
        "environment": "production",
        "instance_id": "stratforge-prod-01",
        "public_origin": "https://app.stratforges.com",
        "hostname": "other-host",
        "heartbeat_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "expires_at_utc": expires,
    }), encoding="utf-8")
    second = gw.acquire_hub_lease()
    assert second["held"] is False
    assert second["duplicate_blocked"] is True
    assert second["warning"] == "duplicate_owner_market_data_hub_blocked"
    assert "stratforge-prod-01" in str(second["owner"])
    obs = gw.connection_observability()
    assert "duplicate_owner_market_data_hub_blocked" in obs["warnings"]
    assert obs["fanout"]["internal_clients_do_not_multiply_provider_connections"] is True


def test_pid_liveness_probe_never_signals_the_target(monkeypatch) -> None:
    # On Windows signal 0 is CTRL_C_EVENT: probing a lease holder with
    # os.kill(pid, 0) delivers a Ctrl+C to that console group instead of
    # reporting liveness, which killed the test run itself.
    if os.name == "nt":
        def refuse(*_args, **_kwargs):
            raise AssertionError("os.kill must not be used to probe pid liveness")

        monkeypatch.setattr(gw.os, "kill", refuse)
    assert gw._pid_alive(os.getpid()) is True
    assert gw._pid_alive(0) is False
    assert gw._pid_alive(-1) is False
    assert gw._pid_alive(4_000_000_000) is False


def test_lease_from_another_host_is_never_stolen_on_local_pid(monkeypatch) -> None:
    _hub_env(monkeypatch)
    path = Path(os.environ["NTA_OWNER_MARKET_DATA_GATEWAY_LEASE_PATH"])
    expires = (datetime.now(timezone.utc) + timedelta(seconds=60)).isoformat().replace("+00:00", "Z")
    path.write_text(json.dumps({
        "lease_id": "remote-hub",
        # A pid that is certainly not running locally; it belongs to the other
        # host and must not be probed for liveness here.
        "pid": 4_000_000_000,
        "environment": "production",
        "instance_id": "stratforge-prod-01",
        "public_origin": "https://app.stratforges.com",
        "hostname": "some-other-host",
        "heartbeat_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "expires_at_utc": expires,
    }), encoding="utf-8")
    blocked = gw.acquire_hub_lease()
    assert blocked["held"] is False
    assert blocked["duplicate_blocked"] is True
    assert gw._read_lease(path)["lease_id"] == "remote-hub"
    gw.reset_lease_for_tests()


def test_hub_lease_is_renewed_before_it_expires(monkeypatch) -> None:
    _hub_env(monkeypatch)
    monkeypatch.setattr(gw, "_LEASE_RENEW_INTERVAL_SEC", 0.05)
    path = Path(os.environ["NTA_OWNER_MARKET_DATA_GATEWAY_LEASE_PATH"])
    try:
        first = gw.acquire_hub_lease()
        assert first["held"] is True
        assert first["renewal_running"] is True
        initial = str(gw._read_lease(path).get("expires_at_utc") or "")
        assert initial
        deadline = time.time() + 5.0
        renewed = initial
        while time.time() < deadline:
            time.sleep(0.05)
            renewed = str(gw._read_lease(path).get("expires_at_utc") or "")
            if renewed and renewed != initial:
                break
        assert renewed != initial, "hub lease must be renewed inside its TTL"
        assert gw.lease_status()["held"] is True
    finally:
        gw.reset_lease_for_tests()
    assert gw._LEASE_HEARTBEAT_THREAD is None


def test_expired_lease_is_not_reported_as_held(monkeypatch) -> None:
    _hub_env(monkeypatch)
    path = Path(os.environ["NTA_OWNER_MARKET_DATA_GATEWAY_LEASE_PATH"])
    assert gw.acquire_hub_lease()["held"] is True
    gw._stop_lease_heartbeat()
    row = gw._read_lease(path)
    row["expires_at_utc"] = (
        datetime.now(timezone.utc) - timedelta(seconds=5)
    ).isoformat().replace("+00:00", "Z")
    path.write_text(json.dumps(row), encoding="utf-8")
    status = gw.lease_status()
    assert status["held"] is False
    assert status["duplicate_blocked"] is False
    assert "hub_lease_not_held" in gw.connection_observability()["warnings"]
    gw.reset_lease_for_tests()


def test_consumer_subscriptions_dedupe_same_instrument(monkeypatch) -> None:
    _consumer_env(monkeypatch)
    monkeypatch.setattr(gw.OwnerGatewayChartAdapter, "connect", lambda self: self.health())
    monkeypatch.setattr(gw.OwnerGatewayChartAdapter, "_send_ws", lambda self, message: None)
    adapter = gw.OwnerGatewayChartAdapter()
    first = adapter.subscribe("MNQ 09-26", "quotes", timeframe="1m", consumer_id="chart-a")
    second = adapter.subscribe("MNQ 09-26", "quotes", timeframe="1m", consumer_id="chart-b")
    assert first == second
    health = adapter.health()
    assert health["wire_subscriptions"] == 1
    assert health["logical_subscription_refcount"] == 2
    adapter.release_subscription("MNQ 09-26", "quotes", timeframe="1m", consumer_id="chart-a")
    health = adapter.health()
    assert health["wire_subscriptions"] == 1
    assert health["logical_subscription_refcount"] == 1
