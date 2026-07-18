"""Unit tests for User-Owned Market Data Entitlements and Registry."""
from __future__ import annotations

import json
import pytest
from app import secure_store
from app.market_data_cache_keys import market_cache_key
from app.market_data_entitlements import (
    UserMarketDataEntitlement,
    get_connector_registry,
    NinjaTraderLocalConnector,
    TopstepXConnector,
    RithmicConnector,
    CQGTradovateConnector,
)


def test_entitlement_credentials_dpapi_isolation(monkeypatch) -> None:
    # Set up mock DPAPI memory storage in secure_store
    storage = {}
    monkeypatch.setattr(secure_store, "set_secret", lambda k, v: storage.update({k: v}))
    monkeypatch.setattr(secure_store, "get_secret", lambda k: storage.get(k))

    ent = UserMarketDataEntitlement(
        workspace_id="ws_abc",
        user_id="user_123",
        provider="rithmic",
        account_id="acc_apex_99",
        entitlement_type="live",
        live_eligible=True,
    )

    # Save credentials
    creds = {"username": "trader99", "password": "securepassword", "firm": "Apex"}
    ent.save_credentials(creds)

    # Check that it's present in storage, but DPAPI key does not leak plaintext in health
    assert ent.get_credential_key() in storage
    h = ent.health()
    assert h["credentials_present"] is True
    # Ensure plaintext is not exposed in health
    assert "trader99" not in str(h)
    assert "securepassword" not in str(h)

    # Load credentials back
    loaded = ent.load_credentials()
    assert loaded == creds


def test_entitlement_expiration() -> None:
    ent = UserMarketDataEntitlement(
        workspace_id="ws_abc",
        user_id="user_123",
        provider="topstep",
        account_id="ts_acc_1",
        expiration="2020-01-01T00:00:00Z",  # already expired
    )
    assert ent.is_expired() is True
    assert ent.health()["live_eligible"] is False

    ent_valid = UserMarketDataEntitlement(
        workspace_id="ws_abc",
        user_id="user_123",
        provider="topstep",
        account_id="ts_acc_1",
        expiration="2099-01-01T00:00:00Z",  # future expiration
    )
    assert ent_valid.is_expired() is False

    ent_malformed = UserMarketDataEntitlement(
        workspace_id="ws_abc",
        user_id="user_123",
        provider="topstep",
        account_id="ts_acc_1",
        expiration="not-a-timestamp",
        live_eligible=True,
    )
    assert ent_malformed.is_expired() is True
    assert ent_malformed.health()["live_eligible"] is False


def test_connector_registry_lifecycle(monkeypatch) -> None:
    # Clean registry instances
    registry = get_connector_registry()

    ent = UserMarketDataEntitlement(
        workspace_id="ws_abc",
        user_id="user_123",
        provider="ninjatrader",
        account_id="nt_local_1",
        entitlement_type="live",
    )

    conn = registry.create_connector(ent)
    assert isinstance(conn, NinjaTraderLocalConnector)

    retrieved = registry.get_connector("ws_abc", "user_123", "ninjatrader", "nt_local_1")
    assert retrieved is conn

    # Remove connector
    registry.remove_connector("ws_abc", "user_123", "ninjatrader", "nt_local_1")
    assert registry.get_connector("ws_abc", "user_123", "ninjatrader", "nt_local_1") is None


def test_individual_connector_authentications(monkeypatch) -> None:
    # 1. NinjaTrader Local Loopback Connector
    ent_nt = UserMarketDataEntitlement("ws_a", "u_1", "ninjatrader", "acc_nt")
    conn_nt = NinjaTraderLocalConnector(ent_nt)
    assert conn_nt.authenticate() is True

    # 2. TopstepX Connector
    storage = {}
    monkeypatch.setattr(secure_store, "set_secret", lambda k, v: storage.update({k: v}))
    monkeypatch.setattr(secure_store, "get_secret", lambda k: storage.get(k))

    ent_ts = UserMarketDataEntitlement("ws_a", "u_1", "topstep", "acc_ts")
    conn_ts = TopstepXConnector(ent_ts)
    assert conn_ts.authenticate() is False  # missing credentials

    ent_ts.save_credentials({"username": "user", "api_key": "key"})
    assert conn_ts.authenticate() is True
    assert conn_ts.connect()["runtime_state"] == "CONFIGURED_UNVERIFIED"

    # 3. Rithmic Connector
    ent_rit = UserMarketDataEntitlement("ws_a", "u_1", "rithmic", "acc_rit")
    conn_rit = RithmicConnector(ent_rit)
    assert conn_rit.authenticate() is False

    ent_rit.save_credentials({"username": "user", "password": "pass", "firm": "Apex"})
    assert conn_rit.authenticate() is True
    assert conn_rit.connect()["runtime_state"] == "CONFIGURED_UNVERIFIED"

    # 4. CQG/Tradovate Connector
    ent_cqg = UserMarketDataEntitlement("ws_a", "u_1", "cqg_tradovate", "acc_cqg")
    conn_cqg = CQGTradovateConnector(ent_cqg)
    assert conn_cqg.authenticate() is False

    ent_cqg.save_credentials({"username": "user", "password": "pass"})
    assert conn_cqg.authenticate() is True
    assert conn_cqg.connect()["runtime_state"] == "CONFIGURED_UNVERIFIED"


def test_per_user_cache_isolation_key_format() -> None:
    workspace_id = "ws_demo"
    user_id = "user_456"
    provider = "rithmic"
    account_id = "rithmic_acc_2"
    exact_contract = "MNQU6"
    channel = "trades"
    timeframe = "1m"
    source_epoch = 1

    # Isolated user cache key formulation matching specification
    key = market_cache_key(
        provider=provider,
        exchange="CME",
        exact_contract=exact_contract,
        channel=channel,
        timeframe=timeframe,
        source_epoch=source_epoch,
        sharing_scope="private",
        workspace_id=workspace_id,
        user_id=user_id,
        account_id=account_id,
    )
    assert ":private:ws_demo:user_456:rithmic_acc_2:rithmic:CME:MNQU6:trades:1m:" in key
