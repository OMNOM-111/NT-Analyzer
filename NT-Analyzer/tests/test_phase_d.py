"""Micro Live + AI star ratings tests."""
from __future__ import annotations

import pytest

from app import micro_live, permissions, runtime_env
from app.ai_lab import ai_ratings, agent_router


@pytest.fixture()
def micro_store(tmp_path, monkeypatch):
    monkeypatch.setenv("NTA_APP_ENV", "staging")
    monkeypatch.delenv("NTA_STAGING_ALLOW_REAL_PAYMENTS", raising=False)
    monkeypatch.delenv("NTA_STAGING_ALLOW_LIVE_ORDERS", raising=False)
    monkeypatch.setattr(micro_live, "_root", lambda: tmp_path)
    (tmp_path / "data" / "runtime").mkdir(parents=True)
    return tmp_path


@pytest.fixture()
def ratings_store(tmp_path, monkeypatch):
    monkeypatch.setattr(ai_ratings, "_root", lambda: tmp_path)
    (tmp_path / "ai_lab" / "registry").mkdir(parents=True)
    return tmp_path


def test_micro_live_free_trades_and_scale(micro_store):
    acct = micro_live.ensure_account(42, scale=100)
    assert acct["mode"] == "micro_live"
    assert acct["account"]["free_trades_left"] == 5
    with pytest.raises(micro_live.MicroLiveError):
        micro_live.place_scaled_trade(42, pnl_full=85)
    micro_live.accept_warnings(42)
    t1 = micro_live.place_scaled_trade(42, pnl_full=85, notional_full=100)
    assert t1["trade"]["free_trade"] is True
    assert t1["account"]["free_trades_left"] == 4
    assert "1:100" in t1["trade"]["comparison"]
    assert t1["trade"]["pnl_full"] != 85  # client PnL is never trusted
    assert t1["trade"]["wallet_delta"] == 0
    for _ in range(4):
        micro_live.place_scaled_trade(42, pnl_full=10)
    with pytest.raises(micro_live.MicroLiveError) as exc:
        micro_live.place_scaled_trade(42, pnl_full=100)
    assert exc.value.status == 402
    micro_live.deposit(42, 50)
    paid = micro_live.place_scaled_trade(42, pnl_full=100)
    assert paid["trade"]["free_trade"] is False
    assert paid["trade"]["wallet_delta"] == paid["trade"]["pnl_micro"]
    assert paid["ledger"]


def test_micro_live_limits_daily_loss_before_fill(micro_store, monkeypatch):
    micro_live.ensure_account(43)
    micro_live.accept_warnings(43)
    for _ in range(5):
        micro_live.place_scaled_trade(43, notional_full=100)
    micro_live.deposit(43, 50)
    monkeypatch.setattr(micro_live, "_simulate_pnl_full", lambda *args: -3000.0)
    with pytest.raises(micro_live.MicroLiveError) as exc:
        micro_live.place_scaled_trade(43, notional_full=100)
    assert exc.value.status == 403
    account = micro_live.ensure_account(43)
    assert account["account"]["balance"] == 50
    assert account["account"]["locked"] is True
    assert account["account"]["lock_reason"] == "daily_loss"
    assert account["trades"][0]["free_trade"] is True
    assert account["ledger"][0]["type"] == "risk_reject"


def test_micro_live_max_notional_circuit_breaker_and_validation(micro_store, monkeypatch):
    micro_live.ensure_account(44)
    micro_live.accept_warnings(44)
    with pytest.raises(micro_live.MicroLiveError):
        micro_live.place_scaled_trade(44, side="invalid")
    with pytest.raises(micro_live.MicroLiveError):
        micro_live.place_scaled_trade(44, notional_full=float("nan"))
    with pytest.raises(micro_live.MicroLiveError) as exc:
        micro_live.place_scaled_trade(44, notional_full=5001)
    assert exc.value.status == 403
    for _ in range(5):
        micro_live.place_scaled_trade(44, notional_full=100)
    micro_live.deposit(44, 100)
    monkeypatch.setattr(micro_live, "_simulate_pnl_full", lambda *args: -100.0)
    for _ in range(3):
        last = micro_live.place_scaled_trade(44, notional_full=100)
    assert last["account"]["locked"] is True
    assert last["account"]["lock_reason"] == "circuit_breaker"
    with pytest.raises(micro_live.MicroLiveError):
        micro_live.place_scaled_trade(44, notional_full=100)


def test_micro_live_workspace_isolation(micro_store):
    micro_live.ensure_account(45, workspace_id="ws_a")
    micro_live.ensure_account(45, workspace_id="ws_b")
    micro_live.deposit(45, 25, workspace_id="ws_a")
    a = micro_live.ensure_account(45, workspace_id="ws_a")
    b = micro_live.ensure_account(45, workspace_id="ws_b")
    assert a["account"]["workspace_id"] == "ws_a"
    assert a["account"]["balance"] == 25
    assert b["account"]["workspace_id"] == "ws_b"
    assert b["account"]["balance"] == 0


def test_production_requires_explicit_flags_and_verified_results(micro_store, monkeypatch):
    monkeypatch.setenv("NTA_APP_ENV", "production")
    monkeypatch.delenv("NTA_ALLOW_REAL_PAYMENTS", raising=False)
    monkeypatch.delenv("NTA_ALLOW_LIVE_ORDERS", raising=False)
    with pytest.raises(micro_live.MicroLiveError):
        micro_live.deposit(46, 10)
    monkeypatch.setenv("NTA_ALLOW_REAL_PAYMENTS", "1")
    with pytest.raises(micro_live.MicroLiveError):
        micro_live.deposit(46, 10)
    deposited = micro_live.deposit(46, 10, provider_result={
        "verified": True, "status": "captured", "provider_payment_id": "pay_1", "amount": 10,
    })
    assert deposited["account"]["balance"] == 10
    micro_live.accept_warnings(46)
    with pytest.raises(micro_live.MicroLiveError):
        micro_live.place_scaled_trade(46, pnl_full=999, notional_full=100)
    monkeypatch.setenv("NTA_ALLOW_LIVE_ORDERS", "1")
    with pytest.raises(micro_live.MicroLiveError):
        micro_live.place_scaled_trade(46, pnl_full=999, notional_full=100)
    filled = micro_live.place_scaled_trade(46, pnl_full=999, notional_full=100, broker_result={
        "verified": True, "status": "filled", "broker_order_id": "broker_1",
        "symbol": "MNQ", "side": "buy", "notional_full": 100, "realized_pnl_full": 25,
    })
    assert filled["trade"]["simulated"] is False
    assert filled["trade"]["pnl_full"] == 25


def test_micro_live_ui_gate_is_coming_soon_without_real_adapters(micro_store, monkeypatch):
    monkeypatch.setenv("NTA_APP_ENV", "production")
    monkeypatch.delenv("NTA_ALLOW_REAL_PAYMENTS", raising=False)
    monkeypatch.delenv("NTA_ALLOW_LIVE_ORDERS", raising=False)
    monkeypatch.delenv("NTA_MICRO_LIVE_PAYMENT_ADAPTER", raising=False)
    monkeypatch.delenv("NTA_MICRO_LIVE_BROKER_ADAPTER", raising=False)

    doc = micro_live.ensure_account(47)

    assert doc["available"] is False
    assert doc["availability"]["mode"] == "coming_soon"
    assert doc["availability"]["real_money"] is False
    assert "payment_adapter_not_configured" in doc["availability"]["blocking_reasons"]
    assert "broker_adapter_not_configured" in doc["availability"]["blocking_reasons"]


def test_staging_data_root_is_separate_by_construction(micro_store, monkeypatch):
    monkeypatch.setenv("NTA_APP_ENV", "production")
    production = micro_live._store_path()
    monkeypatch.setenv("NTA_APP_ENV", "staging")
    staging = micro_live._store_path()
    assert staging != production
    assert staging.parent.parent.name == "staging"
    monkeypatch.setenv("NTA_STAGING_DATA_ROOT", str(production.parent.parent))
    with pytest.raises(runtime_env.RuntimeEnvError):
        runtime_env.data_root(micro_live._root())


def test_micro_live_not_on_free_preview():
    perm = permissions.resolve({"ux_mode": "professional"}, None)
    assert perm["capabilities"].get("micro_live") is False
    assert perm["nav"].get("micro_live") is False
    assert perm["capabilities"].get("practice_trading") is True
    assert perm["capabilities"].get("demo_backtest") is True


def test_star_ratings_influence_order(ratings_store, monkeypatch):
    ai_ratings.record_rating(role_id="coder", model_id="good-model", rating=3)
    ai_ratings.record_rating(role_id="coder", model_id="good-model", rating=3)
    ai_ratings.record_rating(role_id="coder", model_id="weak-model", rating=1)
    tables = ai_ratings.tables()
    assert tables["role_model"]
    assert tables["roles"]
    assert tables["models"]
    agents = [
        {"model": "weak-model", "provider": "x", "key_configured": True, "enabled": True, "endpoint_type": "chat", "priority": 1, "requests_today": 0},
        {"model": "good-model", "provider": "y", "key_configured": True, "enabled": True, "endpoint_type": "chat", "priority": 1, "requests_today": 0},
    ]
    monkeypatch.setattr(ai_ratings, "EXPLORATION_RATE", 0.0)
    ranked = ai_ratings.rank_agents("coder", agents, explore=False)
    assert ranked[0]["model"] == "good-model"


def test_star_rating_event_is_idempotent_upsert_with_scope(ratings_store):
    ai_ratings.record_rating(
        event_id="message_rating:ws-a:MSG-1", message_id="MSG-1",
        role_id="coder", model_id="model-a", provider="test",
        rating=1, workspace_id="ws-a", user_id="42", source="owner",
    )
    ai_ratings.record_rating(
        event_id="message_rating:ws-a:MSG-1", message_id="MSG-1",
        role_id="coder", model_id="model-a", provider="test",
        rating=3, workspace_id="ws-a", user_id="42", source="owner",
    )

    pair = ai_ratings.tables(workspace_id="ws-a")["role_model"][0]
    assert pair["count"] == 1
    assert pair["avg"] == 3.0
    assert ai_ratings.tables(workspace_id="ws-b")["role_model"] == []
    event = ai_ratings._load()["events"][0]
    assert event["message_id"] == "MSG-1"
    assert event["workspace_id"] == "ws-a"
    assert event["user_id"] == "42"
    assert event["source"] == "owner"


def test_rank_agents_does_not_resurrect_ungated(ratings_store, monkeypatch):
    """Ratings only reorder; callers must already filter keys/budget."""
    ai_ratings.record_rating(role_id="general", model_id="no-key", rating=3)
    gated = [{"model": "safe", "provider": "a"}]
    ranked = ai_ratings.rank_agents("general", gated, explore=False)
    assert [a["model"] for a in ranked] == ["safe"]


def test_candidates_still_require_key(monkeypatch, ratings_store):
    """agent_router.candidates keeps key_configured gate before rating sort."""
    monkeypatch.setattr(
        agent_router.agent_registry,
        "list_agents",
        lambda: [
            {
                "model": "starred", "provider": "x", "key_configured": False, "enabled": True,
                "endpoint_type": "chat", "priority": 1, "requests_today": 0,
                "billing_mode": "free_tier", "role": "general",
            },
            {
                "model": "ready", "provider": "y", "key_configured": True, "enabled": True,
                "endpoint_type": "chat", "priority": 1, "requests_today": 0,
                "billing_mode": "free_tier", "role": "general",
            },
        ],
    )
    ai_ratings.record_rating(role_id="general", model_id="starred", rating=3)
    rows = agent_router.candidates("general", endpoint_type="chat", allow_paid=True)
    assert all(r.get("key_configured") for r in rows)
    assert all(r.get("model") != "starred" for r in rows)
