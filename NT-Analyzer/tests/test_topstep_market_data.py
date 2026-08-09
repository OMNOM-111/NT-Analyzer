from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app import integrations, market_data_failover as failover
from app import market_data_live_adapters as live_adapters
from app import server


def _local_topstep_env(monkeypatch) -> None:
    failover.TopstepXProvider._adapter_instance = None
    failover.TopstepXProvider._credential_fingerprint = ""
    monkeypatch.setenv("NTA_APP_ENV", "staging")
    monkeypatch.setenv("NTA_ENABLE_TOPSTEPX_MARKET_DATA", "1")
    monkeypatch.setenv("NTA_TOPSTEPX_USERNAME", "owner_user")
    # Legacy key is intentionally supported because the previous status page
    # checked this name while the adapter checked a different one.
    monkeypatch.setenv("NTA_TOPSTEP_API_KEY", "real-projectx-key")
    monkeypatch.delenv("NTA_TOPSTEPX_API_KEY", raising=False)
    monkeypatch.setenv("NTA_TOPSTEPX_DATA_MODE", "sim")
    monkeypatch.delenv("NTA_ENABLE_TOPSTEPX_LIVE", raising=False)
    monkeypatch.delenv("NTA_TOPSTEPX_REMOTE_SERVER_AUTHORIZED", raising=False)
    monkeypatch.delenv("NTA_TOPSTEPX_REDISTRIBUTION_AUTHORIZED", raising=False)


def _reset_adapter() -> None:
    failover.TopstepXProvider._adapter_instance = None
    failover.TopstepXProvider._credential_fingerprint = ""


def test_topstep_provider_auth_search_and_bars_contract(monkeypatch) -> None:
    _local_topstep_env(monkeypatch)
    _reset_adapter()
    calls = []
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)

    def post(url, payload, **_kwargs):
        calls.append((url, dict(payload)))
        if url.endswith("/Auth/loginKey"):
            assert payload == {"userName": "owner_user", "apiKey": "real-projectx-key"}
            return {"success": True, "token": "session-token"}
        if url.endswith("/Contract/search"):
            assert payload == {"searchText": "MNQ", "live": False}
            return {"success": True, "contracts": [
                {
                    "id": "CON.F.US.ENQ.U26", "name": "NQU6",
                    "symbolId": "F.US.ENQ", "activeContract": True,
                },
                {
                    "id": "CON.F.US.MNQ.Z26", "name": "MNQZ6",
                    "symbolId": "F.US.MNQ", "activeContract": False,
                },
                {
                    "id": "CON.F.US.MNQ.U26", "name": "MNQU6",
                    "symbolId": "F.US.MNQ", "activeContract": True,
                },
            ]}
        if url.endswith("/History/retrieveBars"):
            assert payload["contractId"] == "CON.F.US.MNQ.U26"
            assert payload["live"] is False
            assert payload["includePartialBar"] is True
            assert payload["startTime"] < payload["endTime"]
            return {"success": True, "bars": [{
                "t": now.isoformat().replace("+00:00", "Z"),
                "o": 21000.0, "h": 21002.0, "l": 20999.0, "c": 21001.0, "v": 12,
            }]}
        raise AssertionError(url)

    monkeypatch.setattr(live_adapters, "_post_json", post)
    provider = failover.TopstepXProvider()
    # A root-only chart request must resolve the active ProjectX contract even
    # when NinjaTrader and its instrument catalog are unavailable.
    payload = provider.fetch("MNQ", "1m", 20)

    assert provider.configured() is True
    assert payload["live"] is True
    assert payload["instrument"] == "MNQ 09-26"
    assert payload["source"]["provider"] == "topstepx"
    assert payload["source"]["read_only"] is True
    assert payload["source"]["trade_routing"] is False
    assert [url.rsplit("/", 1)[-1] for url, _ in calls] == [
        "loginKey", "search", "retrieveBars",
    ]


def test_topstep_remote_server_and_redistribution_are_fail_closed(monkeypatch) -> None:
    _local_topstep_env(monkeypatch)
    monkeypatch.setenv("NTA_APP_ENV", "production")
    cfg = live_adapters.TopstepXProjectXAdapter.settings()
    provider = failover.TopstepXProvider().public_status()

    assert cfg["credentials_present"] is True
    assert cfg["policy_allowed"] is False
    assert provider["configured"] is False
    assert provider["runtime_state"] == "POLICY_BLOCKED"
    assert "remote_server_authorization_missing" in provider["blocking_reasons"]
    assert "market_data_redistribution_authorization_missing" in provider["blocking_reasons"]


def test_topstep_status_reports_exact_configuration_not_obsolete_account_id(monkeypatch) -> None:
    _local_topstep_env(monkeypatch)
    status = integrations.topstep_status()
    assert status["configured"] is True
    assert status["username_configured"] is True
    assert status["api_key_configured"] is True
    assert status["read_only"] is True
    assert status["trade_routing_enabled"] is False
    assert status["status"] == "ready_to_initialize"


class _ProductionBackup(failover.MarketDataProvider):
    name = "licensed_backup"
    tier = "test"

    def fetch(self, instrument: str, timeframe: str, limit: int):
        stamp = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat().replace("+00:00", "Z")
        bars = [{"t": stamp, "o": 100, "h": 101, "l": 99, "c": 100.5, "v": 10}]
        freshness = failover.series_freshness(bars, timeframe)
        return {
            "instrument": instrument,
            "bars": bars,
            "total": 1,
            "live": True,
            "status": "external_live",
            "source": {
                "kind": "external_provider", "provider": self.name,
                "independent": True, "live_eligible": True,
            },
            "freshness": freshness,
            "quote": {"last": 100.5, "bid": 100.25, "ask": 100.75},
        }


def test_production_chart_uses_licensed_backup_without_connector(monkeypatch) -> None:
    failover.reset_runtime_state()
    with server._MARKET_BARS_PAYLOAD_CACHE_LOCK:
        server._MARKET_BARS_PAYLOAD_CACHE.clear()
    provider = _ProductionBackup()
    monkeypatch.setattr(server.runtime_env, "is_production", lambda: True)
    monkeypatch.setattr(server.runtime_env, "environment_explicit", lambda: True)
    monkeypatch.setattr(server.market_data, "resolve_chart_instrument", lambda value: "MNQ 09-26")
    monkeypatch.setattr(server.market_data_ingestion, "workspace_series", lambda *a, **k: None)
    monkeypatch.setattr(server.market_data_failover, "configured_providers", lambda: [provider])

    payload = server._market_bars_payload("MNQ", "1m", 20, workspace_id="workspace-1")

    assert payload["live"] is True
    assert payload["source"]["provider"] == "licensed_backup"
    assert payload["chart_source"] == "external_provider"
    assert payload["execution_source"] == "ninjatrader"


def test_chart_payload_cache_expires_so_provider_recovery_is_retried(monkeypatch) -> None:
    with server._MARKET_BARS_PAYLOAD_CACHE_LOCK:
        server._MARKET_BARS_PAYLOAD_CACHE.clear()
    monkeypatch.setenv("NTA_MARKET_PAYLOAD_CACHE_TTL_SEC", "0.25")
    clock = {"value": 100.0}
    monkeypatch.setattr(server.time, "monotonic", lambda: clock["value"])
    key = ("workspace-1", "MNQ 09-26", "1m")
    payload = {
        "status": "offline",
        "live": False,
        "bars": [{"t": "2026-08-08T00:00:00Z", "c": 1}],
        "source": {"kind": "external_provider", "provider": "topstepx"},
    }

    server._market_payload_cache_put(key, payload)
    assert server._market_payload_cache_get(key) is not None

    clock["value"] += 0.26
    assert server._market_payload_cache_get(key) is None


def test_market_data_readiness_requires_and_records_real_provider_response() -> None:
    failover.reset_runtime_state()
    provider = _ProductionBackup()

    before = failover.independent_market_data_readiness(providers=[provider])
    assert before["ok"] is False
    assert before["code"] == "provider_not_verified"

    verified = failover.verify_independent_market_data(providers=[provider])
    assert verified["ok"] is True
    assert verified["verified_provider"] == "licensed_backup"
    assert verified["data_live_at_last_probe"] is True


def test_market_data_readiness_accepts_reachable_stale_bars_when_market_closed() -> None:
    class ClosedMarketBackup(_ProductionBackup):
        name = "closed_market_backup"

        def fetch(self, instrument: str, timeframe: str, limit: int):
            payload = super().fetch(instrument, timeframe, limit)
            payload["live"] = False
            payload["status"] = "external_stale"
            payload["source"]["provider"] = self.name
            return payload

    failover.reset_runtime_state()
    verified = failover.verify_independent_market_data(providers=[ClosedMarketBackup()])

    assert verified["ok"] is True
    assert verified["verified_provider"] == "closed_market_backup"
    assert verified["data_live_at_last_probe"] is False
