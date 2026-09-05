from __future__ import annotations

import hashlib
import json
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from types import SimpleNamespace

import pytest

from app import account_auth, secure_store, server as server_mod, subscriptions, workspaces


@pytest.fixture
def subscription_store(monkeypatch, tmp_path):
    monkeypatch.setattr(account_auth, "_root", lambda: tmp_path)
    monkeypatch.setattr(subscriptions, "_root", lambda: tmp_path)
    monkeypatch.setattr(secure_store, "available", lambda: True)
    monkeypatch.setattr(secure_store, "backend_name", lambda: "test DPAPI")
    monkeypatch.setattr(secure_store, "_protect", lambda value: value[::-1])
    monkeypatch.setattr(secure_store, "_unprotect", lambda value: value[::-1])
    return tmp_path


@pytest.fixture
def billing_server_store(monkeypatch, tmp_path):
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


def _request_json(base: str, path: str, *, method: str = "GET", body: dict | None = None,
                  token: str = "", csrf: str = "") -> dict:
    data = None if body is None else json.dumps(body).encode("utf-8")
    headers = {"Cookie": f"{account_auth.SESSION_COOKIE}={token}"} if token else {}
    if body is not None:
        headers.update({"Content-Type": "application/json", "Origin": base})
    if csrf:
        headers["X-CSRF-Token"] = csrf
    request = urllib.request.Request(base + path, data=data, method=method, headers=headers)
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def test_entitlement_store_read_cache_is_isolated_and_updates_on_write(subscription_store, monkeypatch) -> None:
    subscriptions._clear_doc_cache()
    subscriptions._write_doc({
        "version": 1,
        "vouchers": [],
        "entitlements": [{"entitlement_id": "e1", "user_id": 42, "plan_id": "basic"}],
        "plan_overrides": {},
        "payment_config": {},
        "paypal": {},
        "payment_requests": [],
    })
    subscriptions._clear_doc_cache()
    original_unprotect = secure_store._unprotect
    decrypts = []

    def counting_unprotect(value):
        decrypts.append(True)
        return original_unprotect(value)

    monkeypatch.setattr(secure_store, "_unprotect", counting_unprotect)
    first = subscriptions._read_doc()
    second = subscriptions._read_doc()
    assert len(decrypts) == 1
    first["entitlements"][0]["plan_id"] = "tampered"
    assert second["entitlements"][0]["plan_id"] == "basic"

    updated = subscriptions._read_doc()
    updated["entitlements"][0]["plan_id"] = "pro"
    subscriptions._write_doc(updated)
    assert subscriptions._read_doc()["entitlements"][0]["plan_id"] == "pro"
    assert len(decrypts) == 1


def test_phase3_entitlement_identity_backfill_preserves_legacy_references(subscription_store) -> None:
    owner_uuid = "5d9a7d97-22f6-44ad-8ddd-77f0f390d0a3"
    user_uuid = "c3fafab6-551e-4f39-b641-1e8675504ce7"
    account_auth._write_doc({
        "version": 3,
        "users": [
            {"user_id": 999, "legacy_user_id": 999, "user_uuid": owner_uuid,
             "first_name": "Owner", "status": "active", "is_owner": True},
            {"user_id": 42, "legacy_user_id": 42, "user_uuid": user_uuid,
             "first_name": "Ada", "status": "active", "is_owner": False},
        ],
        "auth_identities": [], "challenges": [], "sessions": [],
    })
    subscriptions._write_doc({
        "version": 1,
        "vouchers": [{
            "voucher_id": "vch_phase3", "created_by_user_id": 999,
            "allowed_telegram_ids": [42],
            "redemptions": [{"user_id": 42, "entitlement_id": "ent_phase3"}],
        }],
        "entitlements": [{"entitlement_id": "ent_phase3", "user_id": 42, "plan_id": "pro"}],
        "plan_overrides": {}, "payment_config": {}, "paypal": {},
        "payment_requests": [{
            "request_id": "pr_phase3", "user_id": 42, "resolver_user_id": 999,
        }],
    })

    migrated = subscriptions._read_doc()

    assert migrated["entitlements"][0]["user_id"] == 42
    assert migrated["entitlements"][0]["user_uuid"] == user_uuid
    assert migrated["vouchers"][0]["created_by_user_id"] == 999
    assert migrated["vouchers"][0]["created_by_user_uuid"] == owner_uuid
    assert migrated["vouchers"][0]["allowed_user_uuids"] == [user_uuid]
    assert migrated["vouchers"][0]["redemptions"][0]["user_uuid"] == user_uuid
    assert migrated["payment_requests"][0]["user_uuid"] == user_uuid
    assert migrated["payment_requests"][0]["resolver_user_uuid"] == owner_uuid


def test_phase3_entitlement_creation_dual_writes_uuid_companions(subscription_store) -> None:
    owner_uuid = "a079ebcd-59b3-497a-a92e-b6b3af1eb85d"
    user_uuid = "ae44650f-d71d-4696-a931-2894d7b0ea79"
    account_auth._write_doc({
        "version": 3,
        "users": [
            {"user_id": 999, "legacy_user_id": 999, "user_uuid": owner_uuid,
             "first_name": "Owner", "status": "active", "is_owner": True},
            {"user_id": 42, "legacy_user_id": 42, "user_uuid": user_uuid,
             "first_name": "Ada", "status": "active", "is_owner": False},
        ],
        "auth_identities": [], "challenges": [], "sessions": [],
    })

    voucher = subscriptions.create_voucher(999, {
        "label": "Phase 3", "grant_plan_id": "pro", "allowed_telegram_ids": [42],
    })["voucher"]
    entitlement = subscriptions.grant_plan(999, 42, "pro")["entitlement"]

    assert voucher["created_by_user_uuid"] == owner_uuid
    assert voucher["allowed_user_uuids"] == [user_uuid]
    assert entitlement["user_id"] == 42
    assert entitlement["user_uuid"] == user_uuid


def test_owner_creates_and_user_redeems_developer_free_voucher(subscription_store) -> None:
    created = subscriptions.create_voucher(999, {
        "label": "Developer seats",
        "grant_plan_id": "developer_free",
        "usage_limit": 5,
        "code_prefix": "DEV",
    })
    voucher = created["voucher"]
    code = voucher["code"]

    assert code.startswith("DEV-")
    assert "code_hash" not in voucher
    assert voucher["discount_percent"] == 100

    preview = subscriptions.preview_voucher(code, user_id=42, email="dev@example.com")
    assert preview["grant_plan_id"] == "developer_free"
    assert preview["checkout_required"] is False
    assert preview["card_required"] is False

    redeemed = subscriptions.redeem_voucher(code, user_id=42, email="dev@example.com")
    entitlement = redeemed["entitlement"]
    assert redeemed["already_redeemed"] is False
    assert entitlement["plan_id"] == "developer_free"
    assert entitlement["status"] == "promo_grant"
    assert entitlement["source"] == "promo_code"

    user_entitlements = subscriptions.entitlements_for_user(42)["entitlements"]
    assert [row["entitlement_id"] for row in user_entitlements] == [entitlement["entitlement_id"]]

    raw = subscriptions._store_path().read_bytes()
    assert code.encode("utf-8") not in raw


def test_voucher_lifecycle_pause_archive_delete(subscription_store) -> None:
    created = subscriptions.create_voucher(999, {
        "label": "Invite", "grant_plan_id": "developer_free", "usage_limit": 3, "code_prefix": "REF",
    })
    voucher_id = created["voucher"]["voucher_id"]
    code = created["voucher"]["code"]

    # Pausing (cancel) blocks redemption.
    subscriptions.set_voucher_status(999, voucher_id, "paused")
    with pytest.raises(subscriptions.SubscriptionError):
        subscriptions.redeem_voucher(code, user_id=42, email="a@b.com")

    # Re-activating restores redemption.
    subscriptions.set_voucher_status(999, voucher_id, "active")
    assert subscriptions.redeem_voucher(code, user_id=42, email="a@b.com")["already_redeemed"] is False

    # A non-owner actor is rejected.
    with pytest.raises(subscriptions.SubscriptionError):
        subscriptions.set_voucher_status(0, voucher_id, "archived")

    # Delete removes it entirely.
    subscriptions.delete_voucher(999, voucher_id)
    assert all(v["voucher_id"] != voucher_id for v in subscriptions.list_vouchers(999)["vouchers"])
    with pytest.raises(subscriptions.SubscriptionError):
        subscriptions.delete_voucher(999, voucher_id)


def test_redeem_is_idempotent_for_same_user_but_usage_limit_blocks_others(subscription_store) -> None:
    code = subscriptions.create_voucher(999, {
        "label": "Single dev seat",
        "grant_plan_id": "developer_free",
        "usage_limit": 1,
    })["voucher"]["code"]

    first = subscriptions.redeem_voucher(code, user_id=42, email="dev@example.com")
    second = subscriptions.redeem_voucher(code, user_id=42, email="dev@example.com")

    assert second["already_redeemed"] is True
    assert second["entitlement"]["entitlement_id"] == first["entitlement"]["entitlement_id"]

    with pytest.raises(subscriptions.SubscriptionError) as exc:
        subscriptions.redeem_voucher(code, user_id=43, email="other@example.com")
    assert exc.value.status == 409


def test_discount_voucher_requires_checkout_and_does_not_consume_usage(subscription_store) -> None:
    code = subscriptions.create_voucher(999, {
        "label": "Half off pro",
        "discount_percent": 50,
        "usage_limit": 2,
    })["voucher"]["code"]

    preview = subscriptions.preview_voucher(
        code, user_id=42, email="buyer@example.com", requested_plan_id="personal_pro",
    )
    assert preview["checkout_required"] is True
    assert preview["card_required"] is True
    assert preview["discount_percent"] == 50

    redeemed = subscriptions.redeem_voucher(
        code, user_id=42, email="buyer@example.com", requested_plan_id="personal_pro",
    )
    assert redeemed["checkout_required"] is True
    assert subscriptions.entitlements_for_user(42)["entitlements"] == []

    vouchers = subscriptions.list_vouchers(999)["vouchers"]
    assert vouchers[0]["used_count"] == 0


def test_voucher_can_be_restricted_to_email_domain(subscription_store) -> None:
    code = subscriptions.create_voucher(999, {
        "label": "Internal dev",
        "grant_plan_id": "developer_free",
        "allowed_email_domains": ["example.com"],
    })["voucher"]["code"]

    with pytest.raises(subscriptions.SubscriptionError) as exc:
        subscriptions.preview_voucher(code, user_id=42, email="dev@other.test")
    assert exc.value.status == 403

    assert subscriptions.preview_voucher(code, user_id=42, email="dev@example.com")["ok"] is True


def test_billing_api_allows_read_only_user_to_redeem_promo(billing_server_store, monkeypatch) -> None:
    monkeypatch.delenv("NTA_TEST_BYPASS_AUTH", raising=False)
    account_auth.set_auth_required(True)
    owner_token = "o" * 64
    owner_csrf = "p" * 48
    user_token = "u" * 64
    user_csrf = "v" * 48
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

    server = ThreadingHTTPServer((server_mod.HOST, 0), server_mod.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://{server.server_address[0]}:{server.server_address[1]}"
    try:
        created = _request_json(base, "/api/owner/vouchers", method="POST", token=owner_token, csrf=owner_csrf, body={
            "label": "Developer API seats",
            "grant_plan_id": "developer_free",
            "usage_limit": 2,
        })
        code = created["voucher"]["code"]

        redeemed = _request_json(base, "/api/billing/promo/redeem", method="POST", token=user_token, csrf=user_csrf, body={
            "code": code,
        })
        assert redeemed["entitlement"]["plan_id"] == "developer_free"

        mine = _request_json(base, "/api/billing/me", token=user_token)
        assert [row["plan_id"] for row in mine["entitlements"]] == ["developer_free"]

        with pytest.raises(urllib.error.HTTPError) as exc:
            _request_json(base, "/api/owner/vouchers", method="POST", token=user_token, csrf=user_csrf, body={
                "label": "Should fail",
                "grant_plan_id": "developer_free",
            })
        assert exc.value.code == 403
    finally:
        server.shutdown()
        server.server_close()


def test_plan_matrix_edit_and_founder_protected(subscription_store) -> None:
    plans = subscriptions.list_plans()
    ids = {p["plan_id"] for p in plans["plans"]}
    assert {"founder", "donate_1", "donate_3", "donate_5", "basic", "standard", "pro"} <= ids
    assert plans["feature_catalog"]
    public_ids = {p["plan_id"] for p in plans["public_plans"]}
    assert "founder" not in public_ids and {"basic", "standard", "pro"} <= public_ids

    basic = next(p for p in plans["plans"] if p["plan_id"] == "basic")
    assert basic["features"]["ai_lab"] is False
    subscriptions.set_plan_feature(999, "basic", "ai_lab", True)
    basic2 = next(p for p in subscriptions.list_plans()["plans"] if p["plan_id"] == "basic")
    assert basic2["features"]["ai_lab"] is True

    with pytest.raises(subscriptions.SubscriptionError):
        subscriptions.set_plan_feature(999, "founder", "ai_lab", False)


def test_payment_config_and_donation_options(subscription_store) -> None:
    subscriptions.set_payment_config(999, {"paypal_me": "@myHandle!!", "card_url": "https://pay.example/x", "enabled": True})
    config = subscriptions.get_payment_config(999)["payment"]
    assert config["paypal_me"] == "myHandle"

    donate = subscriptions.donation_options()
    prices = sorted(t["price_usd"] for t in donate["tiers"])
    assert prices == [1.0, 3.0, 5.0]
    one = next(t for t in donate["tiers"] if t["price_usd"] == 1.0)
    assert one["paypal_url"].endswith("/1")

    with pytest.raises(subscriptions.SubscriptionError):
        subscriptions.set_payment_config(999, {"card_url": "http://insecure"})


def test_create_invite_builds_links(subscription_store) -> None:
    out = subscriptions.create_invite(
        999, {"label": "Ref", "grant_plan_id": "standard", "usage_limit": 5},
        bot_username="StratForge_bot", public_url="https://sf.example",
    )
    code = out["voucher"]["code"]
    assert out["invite"]["telegram"].endswith("start=ref_" + code)
    assert out["invite"]["web"] == "https://sf.example/ui/?ref=" + code
    assert code in out["invite"]["message"]


def test_owner_entitlement_is_founder(subscription_store) -> None:
    ent = subscriptions.owner_entitlement()
    assert ent["plan_id"] == "founder" and ent["status"] == "founder"
    assert all(ent["plan"]["features"].values())


def test_manual_checkout_builds_paypal_link(subscription_store) -> None:
    subscriptions.set_payment_config(999, {"paypal_me": "myHandle", "enabled": True})
    out = subscriptions.manual_checkout(42, "pro")
    assert out["plan_id"] == "pro"
    assert out["amount_usd"] == 25.0
    assert out["paypal_url"].endswith("/25")
    assert "Я оплатил" in out["instructions"]


def test_grant_plan_sets_active_and_supersedes(subscription_store) -> None:
    first = subscriptions.grant_plan(999, 42, "basic", duration_days=30)
    assert first["entitlement"]["plan_id"] == "basic"
    active = subscriptions.active_entitlement(42)
    assert active["plan_id"] == "basic" and active["active"] is True
    assert active["expires_at_utc"]

    subscriptions.grant_plan(999, 42, "pro", duration_days=0)
    rows = subscriptions.entitlements_for_user(42)["entitlements"]
    active_rows = [r for r in rows if r["active"]]
    assert len(active_rows) == 1 and active_rows[0]["plan_id"] == "pro"
    assert active_rows[0]["expires_at_utc"] == ""

    with pytest.raises(subscriptions.SubscriptionError) as exc:
        subscriptions.grant_plan(0, 42, "pro")
    assert exc.value.status == 403


def test_is_expired_detects_past_and_empty() -> None:
    assert subscriptions._is_expired("") is False
    assert subscriptions._is_expired("2000-01-01T00:00:00+00:00") is True
    assert subscriptions._is_expired("bad-date") is True


def test_clear_user_plan_revokes_active(subscription_store) -> None:
    subscriptions.grant_plan(999, 42, "standard", duration_days=10)
    assert subscriptions.active_entitlement(42)["plan_id"] == "standard"
    cleared = subscriptions.clear_user_plan(999, 42)
    assert cleared["ok"] is True
    assert subscriptions.active_entitlement(42) == {}


def test_donation_access_request_grants_donation_plan(subscription_store) -> None:
    """UI flow: user donates via PayPal.me, then asks owner to unlock a donation tier."""
    subscriptions.set_payment_config(999, {"paypal_me": "sfOwner", "enabled": True})
    donate = subscriptions.donation_options()
    assert [t["price_usd"] for t in donate["tiers"]] == [1.0, 3.0, 5.0]
    assert all(t["paypal_url"] for t in donate["tiers"])
    five = next(t for t in donate["tiers"] if t["price_usd"] == 5.0)
    assert five["paypal_url"].endswith("/5")

    created = subscriptions.create_payment_request(
        42, five["plan_id"], note="Донат $5 через PayPal")
    assert created["duplicate"] is False
    assert created["request"]["kind"] == "donation"
    assert created["request"]["amount_usd"] == 5.0
    assert created["request"]["note"] == "Донат $5 через PayPal"

    request_id = created["request"]["request_id"]
    resolved = subscriptions.resolve_payment_request(999, request_id, approve=True, duration_days=0)
    assert resolved["entitlement"]["plan_id"] == five["plan_id"]
    active = subscriptions.active_entitlement(42)
    assert active["plan_id"] == five["plan_id"] and active["active"] is True


def test_payment_request_requires_configured_paypal(subscription_store) -> None:
    with pytest.raises(subscriptions.SubscriptionError) as exc:
        subscriptions.create_payment_request(42, "donate_1")
    assert exc.value.status == 409
    assert subscriptions.list_payment_requests(999)["pending"] == 0


def test_custom_donation_amount_maps_to_highest_affordable_tier(subscription_store) -> None:
    """Mirrors ui.js donationPlanForAmount: custom $4 → donate_3, $7 → donate_5."""
    tiers = [
        {"plan_id": "donate_1", "price_usd": 1.0},
        {"plan_id": "donate_3", "price_usd": 3.0},
        {"plan_id": "donate_5", "price_usd": 5.0},
    ]

    def pick(amount: float):
        sorted_tiers = sorted(tiers, key=lambda t: t["price_usd"])
        chosen = sorted_tiers[0]
        for row in sorted_tiers:
            if amount >= row["price_usd"]:
                chosen = row
        return chosen["plan_id"]

    assert pick(1) == "donate_1"
    assert pick(2.5) == "donate_1"
    assert pick(3) == "donate_3"
    assert pick(4) == "donate_3"
    assert pick(7) == "donate_5"
    subscriptions.set_payment_config(999, {"paypal_me": "sfOwner", "enabled": True})
    created = subscriptions.create_payment_request(42, "pro", note="paid via PayPal")
    assert created["duplicate"] is False
    assert created["request"]["status"] == "pending"
    assert created["request"]["amount_usd"] == 25.0

    duplicate = subscriptions.create_payment_request(42, "pro")
    assert duplicate["duplicate"] is True

    listed = subscriptions.list_payment_requests(999)
    assert listed["pending"] == 1
    request_id = listed["requests"][0]["request_id"]

    resolved = subscriptions.resolve_payment_request(999, request_id, approve=True, duration_days=30)
    assert resolved["entitlement"]["plan_id"] == "pro"
    assert subscriptions.active_entitlement(42)["plan_id"] == "pro"

    again = subscriptions.resolve_payment_request(999, request_id, approve=True, duration_days=30)
    assert again["already_resolved"] is True

    with pytest.raises(subscriptions.SubscriptionError) as exc:
        subscriptions.list_payment_requests(0)
    assert exc.value.status == 403


def test_subscription_store_retries_transient_windows_replace(
    subscription_store, monkeypatch,
) -> None:
    subscriptions.set_payment_config(999, {"paypal_me": "sfOwner", "enabled": True})
    real_os = subscriptions.os
    real_replace = real_os.replace
    calls = {"count": 0}

    def flaky_replace(source, target):
        calls["count"] += 1
        if calls["count"] < 3:
            raise PermissionError(5, "simulated Windows sharing violation")
        return real_replace(source, target)

    # os is shared by every importer, including background Preview writers.
    # Inject failures only through this module's reference, never process-wide.
    isolated_os = SimpleNamespace(**vars(real_os))
    isolated_os.replace = flaky_replace
    monkeypatch.setattr(subscriptions, "os", isolated_os)
    assert real_os.replace is real_replace
    with pytest.raises(FileNotFoundError):
        real_os.replace(subscription_store / "unrelated-missing-source",
                        subscription_store / "unrelated-target")
    assert calls["count"] == 0
    subscriptions.create_payment_request(42, "pro", note="retry contract")

    assert calls["count"] == 3
    assert subscriptions.list_payment_requests(999)["pending"] == 1


def test_reject_payment_request_grants_nothing(subscription_store) -> None:
    subscriptions.set_payment_config(999, {"paypal_me": "sfOwner", "enabled": True})
    created = subscriptions.create_payment_request(42, "standard")
    request_id = created["request"]["request_id"]
    resolved = subscriptions.resolve_payment_request(999, request_id, approve=False)
    assert resolved["entitlement"] is None
    assert resolved["request"]["status"] == "rejected"
    assert subscriptions.active_entitlement(42) == {}


def test_manual_payment_http_flow(billing_server_store, monkeypatch) -> None:
    monkeypatch.delenv("NTA_TEST_BYPASS_AUTH", raising=False)
    account_auth.set_auth_required(True)
    owner_token = "o" * 64
    owner_csrf = "p" * 48
    user_token = "u" * 64
    user_csrf = "v" * 48
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
    subscriptions.set_payment_config(999, {"paypal_me": "myHandle", "enabled": True})

    server = ThreadingHTTPServer((server_mod.HOST, 0), server_mod.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://{server.server_address[0]}:{server.server_address[1]}"
    try:
        checkout = _request_json(base, "/api/billing/checkout", method="POST", token=user_token, csrf=user_csrf, body={"plan_id": "pro"})
        assert checkout["amount_usd"] == 25.0
        assert checkout["paypal_url"].endswith("/25")

        req = _request_json(base, "/api/billing/payment-request", method="POST", token=user_token, csrf=user_csrf, body={"plan_id": "pro"})
        assert req["request"]["status"] == "pending"

        listed = _request_json(base, "/api/owner/payment-requests", token=owner_token)
        assert listed["pending"] == 1
        request_id = listed["requests"][0]["request_id"]
        assert listed["requests"][0]["plan_label"]

        resolved = _request_json(base, "/api/owner/payment-requests/resolve", method="POST", token=owner_token, csrf=owner_csrf, body={"request_id": request_id, "approve": True, "duration_days": 30})
        assert resolved["entitlement"]["plan_id"] == "pro"

        mine = _request_json(base, "/api/billing/me", token=user_token)
        assert any(row["plan_id"] == "pro" and row["active"] for row in mine["entitlements"])

        granted = _request_json(base, "/api/owner/grant", method="POST", token=owner_token, csrf=owner_csrf, body={"user_id": 42, "plan_id": "standard", "duration_days": 0})
        assert granted["entitlement"]["plan_id"] == "standard"

        cleared = _request_json(base, "/api/owner/grant", method="POST", token=owner_token, csrf=owner_csrf, body={"user_id": 42, "plan_id": ""})
        assert cleared["ok"] is True

        with pytest.raises(urllib.error.HTTPError) as exc:
            _request_json(base, "/api/owner/payment-requests", token=user_token)
        assert exc.value.code == 403
    finally:
        server.shutdown()
        server.server_close()
