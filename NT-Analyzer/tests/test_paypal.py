from __future__ import annotations

import hashlib
import json
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from app import account_auth, paypal, secure_store, server as server_mod, subscriptions, workspaces


@pytest.fixture
def paypal_store(monkeypatch, tmp_path):
    monkeypatch.setenv("NTA_TELEGRAM_CHAT_ID", "999")
    monkeypatch.setattr(account_auth, "_root", lambda: tmp_path)
    monkeypatch.setattr(subscriptions, "_root", lambda: tmp_path)
    monkeypatch.setattr(workspaces, "_root", lambda: tmp_path)
    monkeypatch.setattr(secure_store, "available", lambda: True)
    monkeypatch.setattr(secure_store, "backend_name", lambda: "test DPAPI")
    monkeypatch.setattr(secure_store, "_protect", lambda value: value[::-1])
    monkeypatch.setattr(secure_store, "_unprotect", lambda value: value[::-1])
    with account_auth._RATE_LOCK:
        account_auth._LOGIN_RATE.clear()
    return tmp_path


def _request(base, path, *, method="GET", body=None, token="", csrf=""):
    data = None if body is None else json.dumps(body).encode("utf-8")
    headers = {"Cookie": f"{account_auth.SESSION_COOKIE}={token}"} if token else {}
    if body is not None:
        headers.update({"Content-Type": "application/json", "Origin": base})
    if csrf:
        headers["X-CSRF-Token"] = csrf
    request = urllib.request.Request(base + path, data=data, method=method, headers=headers)
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def test_paypal_config_masks_secret(paypal_store) -> None:
    subscriptions.set_paypal_config(999, {"mode": "sandbox", "client_id": "cid", "secret": "shh", "webhook_id": "wh", "enabled": True})
    pub = subscriptions.get_paypal_config(999)["paypal"]
    assert pub["client_id"] == "cid" and pub["secret_set"] is True and "secret" not in pub
    assert pub["mode"] == "sandbox" and pub["enabled"] is True
    # The secret stays available for internal API calls only.
    assert subscriptions.paypal_config_raw()["secret"] == "shh"


def test_activate_and_cancel_paid_idempotent(paypal_store) -> None:
    first = subscriptions.activate_paid(42, "standard", provider="paypal", provider_subscription_id="I-SUB1")
    assert first["entitlement"]["plan_id"] == "standard" and first["entitlement"]["status"] == "active"
    assert first["entitlement"]["provider"] == "paypal"
    assert len(subscriptions.entitlements_for_user(42)["entitlements"]) == 1

    subscriptions.activate_paid(42, "standard", provider="paypal", provider_subscription_id="I-SUB1")
    assert len(subscriptions.entitlements_for_user(42)["entitlements"]) == 1

    subscriptions.cancel_paid(provider_subscription_id="I-SUB1")
    assert subscriptions.entitlements_for_user(42)["entitlements"][0]["status"] == "cancelled"


def test_process_event_activates_and_cancels(paypal_store) -> None:
    activated = paypal.process_event({
        "event_type": "BILLING.SUBSCRIPTION.ACTIVATED",
        "resource": {"id": "I-XYZ", "custom_id": "42:pro"},
    })
    assert activated["action"] == "activated"
    ent = subscriptions.entitlements_for_user(42)["entitlements"][0]
    assert ent["plan_id"] == "pro" and ent["provider"] == "paypal"

    paypal.process_event({
        "event_type": "BILLING.SUBSCRIPTION.CANCELLED",
        "resource": {"id": "I-XYZ", "custom_id": "42:pro"},
    })
    assert subscriptions.entitlements_for_user(42)["entitlements"][0]["status"] == "cancelled"


def test_create_subscription_builds_approval_url(paypal_store, monkeypatch) -> None:
    subscriptions.set_paypal_config(999, {
        "mode": "sandbox", "client_id": "cid", "secret": "s", "webhook_id": "wh",
        "enabled": True, "plans": {"standard": "P-STD"},
    })

    def fake_http(method, url, *, headers, body=None, timeout=20.0):
        if url.endswith("/v1/oauth2/token"):
            return {"access_token": "tok"}
        if url.endswith("/v1/billing/subscriptions"):
            return {"id": "I-NEW", "status": "APPROVAL_PENDING",
                    "links": [{"rel": "approve", "href": "https://paypal/approve"}]}
        return {}

    monkeypatch.setattr(paypal, "_http", fake_http)
    out = paypal.create_subscription(42, "standard", return_url="https://x/ok", cancel_url="https://x/no")
    assert out["approval_url"] == "https://paypal/approve" and out["subscription_id"] == "I-NEW"

    with pytest.raises(paypal.PayPalError):
        paypal.create_subscription(42, "basic", return_url="https://x/ok", cancel_url="https://x/no")


def test_verify_webhook_calls_paypal(paypal_store, monkeypatch) -> None:
    subscriptions.set_paypal_config(999, {"client_id": "c", "secret": "s", "webhook_id": "WH", "enabled": True})
    monkeypatch.setattr(paypal, "_http", lambda method, url, *, headers, body=None, timeout=20.0:
                        {"access_token": "t"} if url.endswith("token") else {"verification_status": "SUCCESS"})
    assert paypal.verify_webhook({"paypal-transmission-id": "x"}, {"event_type": "X"}) is True


def test_webhook_and_subscribe_over_http(paypal_store, monkeypatch) -> None:
    monkeypatch.delenv("NTA_TEST_BYPASS_AUTH", raising=False)
    account_auth.set_auth_required(True)
    subscriptions.set_paypal_config(999, {
        "mode": "sandbox", "client_id": "c", "secret": "s", "webhook_id": "WH",
        "enabled": True, "plans": {"standard": "P-STD"},
    })

    owner_token, owner_csrf = "o" * 64, "p" * 48
    user_token, user_csrf = "u" * 64, "v" * 48
    account_auth._write_doc({
        "version": 1,
        "users": [
            {"user_id": 999, "first_name": "Owner", "last_name": "One", "email": "owner@example.com", "role": "owner", "status": "active", "is_owner": True},
            {"user_id": 42, "first_name": "Dev", "last_name": "Two", "email": "dev@example.com", "role": "read_only", "status": "active", "is_owner": False},
        ],
        "challenges": [],
        "sessions": [
            {"user_id": 999, "token_hash": hashlib.sha256(owner_token.encode()).hexdigest(), "csrf_hash": hashlib.sha256(owner_csrf.encode()).hexdigest(), "csrf_token": owner_csrf, "expires_at": time.time() + 3600, "revoked": False},
            {"user_id": 42, "token_hash": hashlib.sha256(user_token.encode()).hexdigest(), "csrf_hash": hashlib.sha256(user_csrf.encode()).hexdigest(), "csrf_token": user_csrf, "expires_at": time.time() + 3600, "revoked": False},
        ],
    })

    monkeypatch.setattr(paypal, "create_subscription",
                        lambda uid, plan, *, return_url, cancel_url: {"ok": True, "subscription_id": "I-1", "approval_url": "https://paypal/approve", "status": "APPROVAL_PENDING"})

    server = ThreadingHTTPServer((server_mod.HOST, 0), server_mod.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://{server.server_address[0]}:{server.server_address[1]}"
    try:
        # A read-only user can self-serve a subscription (returns PayPal approval url).
        sub = _request(base, "/api/billing/subscribe", method="POST", token=user_token, csrf=user_csrf, body={"plan_id": "standard"})
        assert sub["approval_url"] == "https://paypal/approve"

        # A verified webhook activates the tier automatically (no auth cookie).
        monkeypatch.setattr(paypal, "verify_webhook", lambda headers, event: True)
        event = {"event_type": "BILLING.SUBSCRIPTION.ACTIVATED", "id": "WH-1", "resource": {"id": "I-1", "custom_id": "42:standard"}}
        req = urllib.request.Request(base + "/api/billing/paypal/webhook", data=json.dumps(event).encode("utf-8"),
                                     method="POST", headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as response:
            out = json.loads(response.read().decode("utf-8"))
        assert out["action"] == "activated"
        assert subscriptions.entitlements_for_user(42)["entitlements"][0]["plan_id"] == "standard"

        # An unverified webhook is rejected and does nothing.
        monkeypatch.setattr(paypal, "verify_webhook", lambda headers, event: False)
        bad = urllib.request.Request(base + "/api/billing/paypal/webhook", data=json.dumps(event).encode("utf-8"),
                                     method="POST", headers={"Content-Type": "application/json"})
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(bad, timeout=5)
        assert exc.value.code == 400
    finally:
        server.shutdown()
        server.server_close()
