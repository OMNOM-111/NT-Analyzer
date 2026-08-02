"""Practice trading virtual account tests."""
from __future__ import annotations

import pytest

from app import practice_trading


@pytest.fixture()
def practice_store(tmp_path, monkeypatch):
    monkeypatch.setattr(practice_trading, "_root", lambda: tmp_path)
    (tmp_path / "data" / "runtime").mkdir(parents=True)
    return tmp_path


def _prime_market(user_id, *, symbol="MNQ", price=20000, workspace_id=""):
    """A trusted server-side tick for unit tests; browser prices are never used."""
    return practice_trading.tick_marks(
        user_id, symbol=symbol, price=price, workspace_id=workspace_id,
        market={
            "tradable": True, "status": "ready", "price": price,
            "quote": {"last": price},
            "source": {"kind": "test_trusted_feed", "fresh": True},
            "freshness": {"fresh": True, "stale": False, "age_sec": 0},
        },
    )


def test_practice_open_close_and_daily_loss_lock(practice_store):
    acct = practice_trading.create_account(42, deposit=10000, daily_loss_limit=200, max_drawdown=5000)
    assert acct["mode"] == "practice"
    assert "не реальные" in acct["badge"]
    _prime_market(42)
    opened = practice_trading.place_order(42, symbol="MNQ", side="buy", quantity=2, order_type="market")
    assert opened["filled"] is True
    assert opened["positions"]
    closed = practice_trading.close_position(42)
    assert closed["trade"]["action"] == "close"
    # Force daily loss lock
    practice_trading.create_account(42, deposit=10000, daily_loss_limit=50, max_drawdown=5000)
    mark = _prime_market(42)["marks"]["MNQ"]
    practice_trading.place_order(42, symbol="MNQ", side="buy", quantity=1)
    # Small move: hits the daily rule without reaching the trailing max DD.
    locked = practice_trading.tick_marks(42, symbol="MNQ", price=mark - 30)
    assert locked["account"]["account_status"] == "daily_locked"
    assert locked["account"]["requires_new_account"] is False
    with pytest.raises(practice_trading.PracticeTradingError) as exc:
        practice_trading.place_order(42, symbol="MNQ", side="buy", quantity=1)
    assert exc.value.status == 403
    rep = practice_trading.report(42)
    assert rep["ok"] is True
    assert rep["mode"] == "practice"


def test_failed_virtual_account_stays_closed_until_student_opens_new_one(practice_store):
    created = practice_trading.create_account(43, deposit=10000, daily_loss_limit=5000, max_drawdown=100)
    assert created["marks"] == {}
    mark = _prime_market(43)["marks"]["MNQ"]
    practice_trading.place_order(43, symbol="MNQ", side="buy", quantity=1)
    failed = practice_trading.tick_marks(43, symbol="MNQ", price=mark - 100)
    assert failed["account"]["account_status"] == "failed"
    assert failed["account"]["requires_new_account"] is True

    # Even a recovered mark cannot reopen an already failed evaluation account.
    recovered_mark = practice_trading.tick_marks(43, symbol="MNQ", price=mark + 100)
    assert recovered_mark["account"]["account_status"] == "failed"
    with pytest.raises(practice_trading.PracticeTradingError) as exc:
        practice_trading.place_order(43, symbol="MNQ", side="buy")
    assert exc.value.status == 403

    assert practice_trading.reset_account(43)["deleted"] is True
    replacement = practice_trading.create_account(43, deposit=25000)
    assert replacement["account"]["account_status"] == "active"


def test_sl_tp_triggers(practice_store):
    practice_trading.create_account(7, deposit=20000)
    mark = _prime_market(7)["marks"]["MNQ"]
    practice_trading.place_order(
        7, symbol="MNQ", side="buy", quantity=1, order_type="market",
        stop_loss=mark - 50, take_profit=mark + 5,
    )
    out = practice_trading.tick_marks(7, symbol="MNQ", price=mark + 10)
    assert out["positions"] == [] or any(t.get("action") == "sl_tp" for t in out["trades"])


def test_working_limit_fills_on_cross_and_records_execution(practice_store):
    practice_trading.create_account(8, deposit=20000)
    mark = _prime_market(8)["marks"]["MNQ"]
    resting = practice_trading.place_order(
        8, symbol="MNQ", side="buy", quantity=1,
        order_type="limit", limit_price=mark - 100,
    )
    assert resting["filled"] is False
    assert len(resting["orders"]) == 1
    filled = practice_trading.tick_marks(8, symbol="MNQ", price=mark - 100)
    assert filled["orders"] == []
    assert len(filled["positions"]) == 1
    assert filled["order_history"][0]["status"] == "filled"
    assert filled["executions"][0]["kind"] == "entry"


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"side": "???", "order_type": "market"}, "Сторона"),
        ({"side": "buy", "order_type": "bogus"}, "Тип ордера"),
        ({"side": "buy", "order_type": "market", "quantity": 1.5}, "целым"),
        ({"side": "buy", "order_type": "limit", "limit_price": float("nan")}, "конечным"),
        ({"side": "buy", "order_type": "market", "stop_loss": 999999}, "Stop Loss"),
    ],
)
def test_order_validation_is_fail_closed(practice_store, kwargs, message):
    practice_trading.create_account(9, deposit=20000)
    _prime_market(9)
    request = dict(kwargs)
    quantity = request.pop("quantity", 1)
    with pytest.raises(practice_trading.PracticeTradingError) as exc:
        practice_trading.place_order(9, symbol="MNQ", quantity=quantity, **request)
    assert message in str(exc.value)
    assert practice_trading.get_account(9)["positions"] == []


def test_workspace_accounts_are_isolated(practice_store):
    a = practice_trading.create_account(10, workspace_id="ws_a", deposit=10000)
    b = practice_trading.create_account(10, workspace_id="ws_b", deposit=25000)
    assert a["account"]["workspace_id"] == "ws_a"
    assert b["account"]["workspace_id"] == "ws_b"
    _prime_market(10, workspace_id="ws_a")
    practice_trading.place_order(
        10, workspace_id="ws_a", symbol="MNQ", side="buy", order_type="market",
    )
    assert practice_trading.get_account(10, workspace_id="ws_a")["positions"]
    assert practice_trading.get_account(10, workspace_id="ws_b")["positions"] == []


def test_close_with_unknown_selector_does_not_close_first_position(practice_store):
    practice_trading.create_account(11, deposit=20000)
    _prime_market(11)
    practice_trading.place_order(11, symbol="MNQ", side="buy", order_type="market")
    with pytest.raises(practice_trading.PracticeTradingError) as exc:
        practice_trading.close_position(11, "missing-position")
    assert exc.value.status == 404
    assert practice_trading.get_account(11)["positions"]


def test_cancel_working_order_releases_virtual_buying_power(practice_store):
    created = practice_trading.create_account(12, deposit=20000, position_limit=4)
    assert created["account"]["buying_power"] == 20000
    mark = _prime_market(12)["marks"]["MNQ"]
    resting = practice_trading.place_order(
        12, symbol="MNQ", side="buy", quantity=2,
        order_type="limit", limit_price=mark - 100,
    )
    assert resting["account"]["contracts_available"] == 2

    cancelled = practice_trading.cancel_order(12, resting["order"]["order_id"])

    assert cancelled["orders"] == []
    assert cancelled["account"]["contracts_available"] == 4
    assert cancelled["order_history"][0]["status"] == "cancelled_by_user"


def test_reset_account_really_deletes_only_selected_workspace(practice_store):
    practice_trading.create_account(13, workspace_id="ws_a", deposit=10000)
    practice_trading.create_account(13, workspace_id="ws_b", deposit=25000)

    result = practice_trading.reset_account(13, workspace_id="ws_a")

    assert result["deleted"] is True
    with pytest.raises(practice_trading.PracticeTradingError) as exc:
        practice_trading.get_account(13, workspace_id="ws_a")
    assert exc.value.status == 404
    assert practice_trading.get_account(13, workspace_id="ws_b")["account"]["balance"] == 25000


def test_unavailable_quote_never_invents_a_fill_or_exit(practice_store):
    practice_trading.create_account(14, deposit=20000)
    with pytest.raises(practice_trading.PracticeTradingError) as exc:
        practice_trading.place_order(14, symbol="MNQ", side="buy", order_type="market")
    assert exc.value.status == 409
    assert "вымышленной цене" in str(exc.value)

    ready = _prime_market(14, price=20100)
    practice_trading.place_order(14, symbol="MNQ", side="buy", order_type="market")
    unavailable = practice_trading.tick_marks(
        14, symbol="MNQ", price=0,
        market={"tradable": False, "status": "offline", "reason": "feed unavailable"},
    )
    assert unavailable["marks"]["MNQ"] == ready["marks"]["MNQ"]
    assert unavailable["markets"]["MNQ"]["tradable"] is False
    with pytest.raises(practice_trading.PracticeTradingError) as exc:
        practice_trading.close_position(14)
    assert exc.value.status == 409
    assert practice_trading.get_account(14)["positions"]
