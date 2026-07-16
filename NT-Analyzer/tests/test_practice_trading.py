"""Practice trading virtual account tests."""
from __future__ import annotations

import pytest

from app import practice_trading


@pytest.fixture()
def practice_store(tmp_path, monkeypatch):
    monkeypatch.setattr(practice_trading, "_root", lambda: tmp_path)
    (tmp_path / "data" / "runtime").mkdir(parents=True)
    return tmp_path


def test_practice_open_close_and_daily_loss_lock(practice_store):
    acct = practice_trading.create_account(42, deposit=10000, daily_loss_limit=200, max_drawdown=5000)
    assert acct["mode"] == "practice"
    assert "не реальные" in acct["badge"]
    opened = practice_trading.place_order(42, symbol="MNQ", side="buy", quantity=2, order_type="market")
    assert opened["filled"] is True
    assert opened["positions"]
    closed = practice_trading.close_position(42)
    assert closed["trade"]["action"] == "close"
    # Force daily loss lock
    practice_trading.create_account(42, deposit=1000, daily_loss_limit=50, max_drawdown=5000)
    practice_trading.place_order(42, symbol="MNQ", side="buy", quantity=1)
    # Crash mark
    practice_trading.tick_marks(42, symbol="MNQ", price=1.0)
    with pytest.raises(practice_trading.PracticeTradingError) as exc:
        practice_trading.place_order(42, symbol="MNQ", side="buy", quantity=1)
    assert exc.value.status == 403
    rep = practice_trading.report(42)
    assert rep["ok"] is True
    assert rep["mode"] == "practice"


def test_sl_tp_triggers(practice_store):
    practice_trading.create_account(7, deposit=20000)
    mark = practice_trading.get_account(7)["marks"]["MNQ"]
    practice_trading.place_order(
        7, symbol="MNQ", side="buy", quantity=1, order_type="market",
        stop_loss=mark - 50, take_profit=mark + 5,
    )
    out = practice_trading.tick_marks(7, symbol="MNQ", price=mark + 10)
    assert out["positions"] == [] or any(t.get("action") == "sl_tp" for t in out["trades"])
