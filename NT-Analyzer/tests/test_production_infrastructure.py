from __future__ import annotations

from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import threading
import urllib.error
import urllib.request

import pytest

from app import edge_security
from app import runtime_env
from app import server as server_mod
from app import service_readiness


PRODUCTION_ENV = {
    "STRATFORGE_ENV": "production",
    "STRATFORGE_INSTANCE_ID": "stratforge-prod-test",
    "STRATFORGE_DEPLOYMENT_ROLE": "all-in-one",
    "STRATFORGE_CONFIG_PROFILE": "production-primary",
    "STRATFORGE_BUILD_VERSION": "1.0.0-test",
    "STRATFORGE_BUILD_DATE": "2026-07-21",
    "STRATFORGE_RELEASE_CHANNEL": "stable",
    "STRATFORGE_REGION": "primary",
    "STRATFORGE_BIND_HOST": "127.0.0.1",
    "STRATFORGE_ALLOWED_HOSTS": "app.stratforges.com",
    "STRATFORGE_PUBLIC_ORIGIN": "https://app.stratforges.com",
    "STRATFORGE_EDGE_MODE": "cloudflare-tunnel",
    "STRATFORGE_TRUSTED_PROXY_IPS": "127.0.0.1,::1",
    "STRATFORGE_DATABASE_ID": "postgres-primary",
    "STRATFORGE_QUEUE_ID": "production-jobs",
    "STRATFORGE_OBJECT_STORAGE_ID": "production-artifacts",
    "STRATFORGE_TELEGRAM_BOT_ID": "production-main",
    "STRATFORGE_COOKIE_NAMESPACE": "sf-prod",
    "STRATFORGE_SIGNING_KEY_ID": "production-key-v1",
    "STRATFORGE_LOG_NAMESPACE": "production",
    "STRATFORGE_LIVE_TRADING_ALLOWED": "0",
    "STRATFORGE_REAL_PAYMENTS_ALLOWED": "0",
}


@pytest.fixture
def production_config(monkeypatch, tmp_path: Path):
    root = tmp_path / "production"
    root.mkdir()
    for key in (
        "NTA_APP_ENV",
        "NTA_ENV",
        "NTA_TEST_BYPASS_AUTH",
        "NTA_ENABLE_TEST_AUTH",
        "NTA_ENABLE_IMPERSONATION",
        "NTA_DISABLE_RATE_LIMIT",
        "NTA_ALLOW_LIVE_ORDERS",
        "NTA_ALLOW_REAL_PAYMENTS",
    ):
        monkeypatch.delenv(key, raising=False)
    values = {**PRODUCTION_ENV, "STRATFORGE_DATA_ROOT": str(root)}
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    return runtime_env.assert_startup_safe()


def test_edge_policy_rejects_origin_bypass_and_spoofed_forwarding(
    production_config,
) -> None:
    cfg = production_config
    assert edge_security.evaluate_request(
        cfg,
        peer_ip="203.0.113.10",
        host="app.stratforges.com",
        forwarded_host="app.stratforges.com",
        forwarded_proto="https",
    ).code == "untrusted_forwarded_headers"
    assert edge_security.evaluate_request(
        cfg, peer_ip="203.0.113.10", host="app.stratforges.com",
    ).code == "origin_bypass"
    assert edge_security.evaluate_request(
        cfg,
        peer_ip="127.0.0.1",
        host="app.stratforges.com",
        forwarded_proto="http",
    ).code == "https_required"
    assert edge_security.evaluate_request(
        cfg,
        peer_ip="127.0.0.1",
        host="app.stratforges.com",
        forwarded_host="app.stratforges.com",
        forwarded_proto="https",
        forwarded_for="198.51.100.20",
    ).allowed is True


def test_readiness_is_false_until_all_production_probes_are_real(
    production_config,
) -> None:
    blocked = service_readiness.readiness_payload(
        production_config, minimum_free_mb=1,
    )
    assert blocked["ok"] is False
    assert blocked["checks"]["database"]["code"] == "probe_not_registered"

    ready = service_readiness.readiness_payload(
        production_config,
        minimum_free_mb=1,
        probes={name: (lambda: True) for name in service_readiness.PRODUCTION_COMPONENTS},
    )
    assert ready["ok"] is True
    assert ready["status"] == "ready"


def test_real_handler_enforces_host_and_exposes_safe_health(
    production_config,
) -> None:
    srv = ThreadingHTTPServer(("127.0.0.1", 0), server_mod.Handler)
    srv.deployment_config = production_config
    srv.readiness_probes = {}
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    good_headers = {
        "Host": "app.stratforges.com",
        "X-Forwarded-Host": "app.stratforges.com",
        "X-Forwarded-Proto": "https",
        "X-Forwarded-For": "198.51.100.25",
    }
    try:
        with pytest.raises(urllib.error.HTTPError) as wrong_host:
            urllib.request.urlopen(
                urllib.request.Request(
                    base + "/api/health/live", headers={"Host": "evil.example"},
                ),
                timeout=5,
            )
        assert wrong_host.value.code == 421

        with urllib.request.urlopen(
            urllib.request.Request(
                base + "/api/health/live", headers=good_headers,
            ),
            timeout=5,
        ) as response:
            live = json.loads(response.read())
        assert live["status"] == "alive"
        assert "data_root" not in live["deployment"]

        with pytest.raises(urllib.error.HTTPError) as not_ready:
            urllib.request.urlopen(
                urllib.request.Request(
                    base + "/api/health/ready", headers=good_headers,
                ),
                timeout=5,
            )
        assert not_ready.value.code == 503
        ready_body = json.loads(not_ready.value.read())
        assert ready_body["status"] == "not_ready"
        assert production_config.data_root not in json.dumps(ready_body)

        with urllib.request.urlopen(
            urllib.request.Request(base + "/api/runtime/env", headers=good_headers),
            timeout=5,
        ) as response:
            runtime = json.loads(response.read())
        assert runtime["environment"] == "production"
        assert "data_root" not in runtime
        assert "signing_key_id" not in runtime
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=5)
