from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from app import runtime_env
from app import server as server_mod
from app import service_readiness
from app.production_storage.core import DocumentRepository


PRODUCTION_ENV = {
    "DEPLOYMENT_ENV": "production",
    "STRATFORGE_INSTANCE_ID": "stratforge-prod-test",
    "STRATFORGE_DEPLOYMENT_ROLE": "all-in-one",
    "STRATFORGE_CONFIG_PROFILE": "production-primary",
    "APP_VERSION": "1.0.0-test",
    "RELEASE_CHANNEL": "stable",
    "BUILD_ID": "sf-1.0.0-test-infra",
    "GIT_COMMIT_SHA": "a" * 40,
    "ARTIFACT_SHA256": "B" * 64,
    "BUILD_TIMESTAMP_UTC": "2026-07-21T12:34:56Z",
    "DIRTY": "0",
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
        "STRATFORGE_ENV",
        "STRATFORGE_BUILD_VERSION",
        "STRATFORGE_BUILD_DATE",
        "STRATFORGE_RELEASE_CHANNEL",
        "STRATFORGE_BUILD_TIMESTAMP_UTC",
        "STRATFORGE_BUILD_ID",
        "STRATFORGE_GIT_COMMIT_SHA",
        "STRATFORGE_ARTIFACT_SHA256",
        "STRATFORGE_BUILD_DIRTY",
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


def test_document_repository_ping_does_not_load_json() -> None:
    import inspect
    source = DocumentRepository.ping.__doc__ or ""
    body = inspect.getsource(DocumentRepository.ping)
    assert "SELECT 1 FROM sf_repository_documents" in body
    assert "SELECT revision, document FROM" not in body
    assert "do not load or migrate the JSON document" in source


def test_hanging_probe_fails_closed_within_timeout(production_config) -> None:
    service_readiness.clear_readiness_cache()

    def hang() -> bool:
        time.sleep(8)
        return True

    probes = {
        name: (lambda: True) for name in service_readiness.PRODUCTION_COMPONENTS
    }
    probes["connector_control"] = hang
    started = time.monotonic()
    payload = service_readiness.readiness_payload(
        production_config,
        probes=probes,
        minimum_free_mb=1,
        probe_timeout_sec=0.4,
        cache_ttl_sec=0,
    )
    elapsed = time.monotonic() - started
    assert elapsed < 2.0
    assert payload["ok"] is False
    assert payload["checks"]["connector_control"]["code"] == "probe_timeout"
    assert payload["checks"]["database"]["ok"] is True


def test_overlapping_readiness_calls_share_one_compute(production_config) -> None:
    service_readiness.clear_readiness_cache()
    calls = {"n": 0}
    lock = threading.Lock()

    def slow_ok() -> bool:
        with lock:
            calls["n"] += 1
        time.sleep(0.4)
        return True

    probes = {
        name: slow_ok for name in service_readiness.PRODUCTION_COMPONENTS
    }
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [
            pool.submit(
                lambda: service_readiness.readiness_payload(
                    production_config,
                    probes=probes,
                    minimum_free_mb=1,
                    probe_timeout_sec=2.0,
                    cache_ttl_sec=2.0,
                )
            )
            for _ in range(8)
        ]
        payloads = [future.result() for future in as_completed(futures)]
    elapsed = time.monotonic() - started
    assert elapsed < 2.5
    assert calls["n"] == len(service_readiness.PRODUCTION_COMPONENTS)
    assert all(item["ok"] is True for item in payloads)


def test_ready_http_stays_bounded_under_hanging_probe(production_config) -> None:
    service_readiness.clear_readiness_cache()
    srv = ThreadingHTTPServer(("127.0.0.1", 0), server_mod.Handler)
    srv.deployment_config = production_config
    srv.readiness_probes = {
        name: (lambda: True) for name in service_readiness.PRODUCTION_COMPONENTS
    }
    srv.readiness_probes["connector_control"] = lambda: time.sleep(8) or True
    srv.readiness_optional_components = {}
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    headers = {
        "Host": "app.stratforges.com",
        "X-Forwarded-Host": "app.stratforges.com",
        "X-Forwarded-Proto": "https",
        "X-Forwarded-For": "198.51.100.25",
    }
    try:
        started = time.monotonic()
        with pytest.raises(urllib.error.HTTPError) as not_ready:
            urllib.request.urlopen(
                urllib.request.Request(base + "/api/health/ready", headers=headers),
                timeout=5,
            )
        elapsed = time.monotonic() - started
        assert elapsed < 3.5
        assert not_ready.value.code == 503
        body = json.loads(not_ready.value.read())
        assert body["checks"]["connector_control"]["code"] == "probe_timeout"

        with urllib.request.urlopen(
            urllib.request.Request(base + "/api/health/live", headers=headers),
            timeout=2,
        ) as response:
            live = json.loads(response.read())
        assert live["status"] == "alive"
        assert live["deployment"]["git_commit_sha"] == "a" * 40
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=5)
