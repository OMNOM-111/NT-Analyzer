"""Practice trading — virtual money and Topstep-like mechanics (never NT live).

Isolated per-user store under ``data/runtime/practice_accounts.json``.
Never writes to live NT command queues.
"""
from __future__ import annotations

import json
import math
import os
import secrets
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import runtime_env


class PracticeTradingError(RuntimeError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = int(status)


_LOCK = threading.RLock()
_DEFAULT_MARKS = {
    "MNQ": 20150.0,
    "MES": 5420.0,
    "MGC": 2355.0,
}
_ALLOWED_SYMBOLS = frozenset(_DEFAULT_MARKS)
_ALLOWED_SIDES = {"buy": "Long", "long": "Long", "sell": "Short", "short": "Short"}
_ALLOWED_ORDER_TYPES = frozenset({"market", "limit"})
_ACCOUNT_STATUSES = frozenset({"active", "daily_locked", "failed"})


def _root() -> Path:
    return Path(__file__).resolve().parent.parent


def _store_path() -> Path:
    return runtime_env.data_root(_root()) / "runtime" / "practice_accounts.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _workspace(value: Any) -> str:
    raw = str(value or "").strip()
    if (len(raw) > 160
            or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_." for ch in raw)):
        raise PracticeTradingError("Некорректная рабочая область.")
    return raw


def _account_key(user_id: Any, workspace_id: Any = "") -> str:
    uid = int(user_id or 0)
    if uid <= 0:
        raise PracticeTradingError("Требуется вход.", 401)
    workspace = _workspace(workspace_id)
    return f"{workspace}:{uid}" if workspace else str(uid)


def _finite(value: Any, label: str, *, positive: bool = False,
            allow_zero: bool = True) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise PracticeTradingError(f"{label}: укажите число.") from exc
    if not math.isfinite(number):
        raise PracticeTradingError(f"{label}: число должно быть конечным.")
    if positive and (number < 0 or (not allow_zero and number == 0)):
        raise PracticeTradingError(f"{label}: значение должно быть больше нуля.")
    return number


def _symbol(value: Any) -> str:
    symbol = str(value or "").strip().upper()
    root = symbol.split()[0] if symbol else ""
    if root not in _ALLOWED_SYMBOLS:
        raise PracticeTradingError(
            f"Инструмент {symbol or '—'} недоступен. Доступны: {', '.join(sorted(_ALLOWED_SYMBOLS))}."
        )
    return root


def _side(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized not in _ALLOWED_SIDES:
        raise PracticeTradingError("Сторона должна быть buy/long или sell/short.")
    return _ALLOWED_SIDES[normalized]


def _order_type(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized not in _ALLOWED_ORDER_TYPES:
        raise PracticeTradingError("Тип ордера должен быть market или limit.")
    return normalized


def _load() -> Dict[str, Any]:
    path = _store_path()
    if not path.is_file():
        return {"version": 1, "accounts": {}}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"version": 1, "accounts": {}}
    return doc if isinstance(doc, dict) else {"version": 1, "accounts": {}}


def _save(doc: Dict[str, Any]) -> None:
    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _point_value(symbol: str) -> float:
    sym = str(symbol or "").upper()
    if sym.startswith("MNQ"):
        return 2.0
    if sym.startswith("MES"):
        return 5.0
    if sym.startswith("MGC"):
        return 10.0
    return 1.0


def _mark(symbol: str, accounts_marks: Dict[str, float]) -> float:
    """Return the last stored mark for PnL display only.

    A default value is deliberately *not* an executable quote.  It remains a
    compatibility fallback for an already persisted legacy position, while
    every new entry/exit is guarded by ``_tradable_mark`` below.
    """
    root = str(symbol or "").split()[0].upper()
    if root in accounts_marks:
        return float(accounts_marks[root])
    return float(_DEFAULT_MARKS.get(root, 100.0))


def _market_record(acct: Dict[str, Any], symbol: str) -> Dict[str, Any]:
    root = str(symbol or "").split()[0].upper()
    rows = acct.get("markets") if isinstance(acct.get("markets"), dict) else {}
    row = rows.get(root) if isinstance(rows, dict) else {}
    return dict(row) if isinstance(row, dict) else {}


def _tradable_mark(acct: Dict[str, Any], symbol: str) -> Optional[float]:
    """Return an independently verified, current virtual fill price only.

    The client never supplies this price.  A missing, stale, or legacy static
    mark may still be displayed as historic PnL context, but it must never be
    used to fill a new virtual order or close a position.
    """
    market = _market_record(acct, symbol)
    if not bool(market.get("tradable")):
        return None
    try:
        value = float(market.get("price"))
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) and value > 0 else None


def _normalize_market(symbol: str, price: float, market: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Keep a compact, public-safe market provenance record with each account."""
    root = _symbol(symbol)
    raw = dict(market) if isinstance(market, dict) else {}
    quote = raw.get("quote") if isinstance(raw.get("quote"), dict) else {}
    source = raw.get("source") if isinstance(raw.get("source"), dict) else {}
    freshness = raw.get("freshness") if isinstance(raw.get("freshness"), dict) else {}
    price_n = float(price or 0)
    explicit_tradable = raw.get("tradable")
    # Direct module callers are test/internal code.  The HTTP handler always
    # passes an explicit market record built from the server-side data plane.
    tradable = bool(price_n > 0 if explicit_tradable is None else explicit_tradable)
    if not math.isfinite(price_n) or price_n <= 0:
        tradable = False
        price_n = 0.0
    status = str(raw.get("status") or ("ready" if tradable else "unavailable"))[:80]
    reason = str(raw.get("reason") or "")[:300]
    source_out = {
        key: source.get(key)
        for key in ("kind", "provider", "active", "updated_at_utc", "age_sec", "runtime_state")
        if source.get(key) not in (None, "")
    }
    freshness_out = {
        key: freshness.get(key)
        for key in ("fresh", "stale", "age_sec", "max_age_sec", "data_as_of_utc")
        if freshness.get(key) not in (None, "")
    }
    quote_out: Dict[str, Any] = {}
    for key in ("bid", "ask", "last", "bid_ask_estimated"):
        if key in quote:
            quote_out[key] = quote.get(key)
    if price_n > 0:
        quote_out["last"] = price_n
    return {
        "symbol": root,
        "tradable": tradable,
        "available": bool(tradable),
        "price": round(price_n, 8) if price_n > 0 else 0.0,
        "status": status,
        "reason": reason,
        "quote": quote_out,
        "source": source_out,
        "freshness": freshness_out,
        "updated_at_utc": _now_iso(),
    }


def _market_unavailable_message(symbol: str) -> str:
    return (
        f"Нет актуальной подтверждённой котировки {symbol}. "
        "Учебный ордер не будет исполнен по вымышленной цене."
    )


def create_account(
    user_id: Any,
    *,
    deposit: float = 50000,
    commission: float = 2.0,
    daily_loss_limit: float = 1000,
    max_drawdown: float = 2000,
    position_limit: int = 4,
    symbol: str = "MNQ",
    workspace_id: str = "",
) -> Dict[str, Any]:
    uid = _account_key(user_id, workspace_id)
    workspace = _workspace(workspace_id)
    deposit = _finite(deposit, "Депозит", positive=True, allow_zero=False)
    if deposit < 1000 or deposit > 500000:
        raise PracticeTradingError("Депозит должен быть от $1 000 до $500 000.")
    commission = _finite(commission, "Комиссия", positive=True)
    daily_loss_limit = _finite(
        daily_loss_limit, "Дневной лимит убытка", positive=True, allow_zero=False,
    )
    max_drawdown = _finite(
        max_drawdown, "Максимальная просадка", positive=True, allow_zero=False,
    )
    position_limit_number = _finite(
        position_limit, "Лимит позиции", positive=True, allow_zero=False,
    )
    if not position_limit_number.is_integer():
        raise PracticeTradingError("Лимит позиции должен быть целым числом.")
    position_limit = int(position_limit_number)
    if position_limit < 1 or position_limit > 100:
        raise PracticeTradingError("Лимит позиции должен быть от 1 до 100.")
    symbol_n = _symbol(symbol)
    with _LOCK:
        doc = _load()
        acct = {
            "account_id": "prac_" + secrets.token_hex(6),
            "user_id": int(user_id),
            "workspace_id": workspace,
            "mode": "practice",
            "badge": "Учебный счёт · не реальные деньги",
            "created_at_utc": _now_iso(),
            "deposit": deposit,
            "balance": deposit,
            "equity": deposit,
            "commission": commission,
            "daily_loss_limit": daily_loss_limit,
            "max_drawdown": max_drawdown,
            "position_limit": position_limit,
            "symbol_default": symbol_n,
            "day_start_balance": deposit,
            "day_key": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "account_status": "active",
            "locked": False,
            "lock_reason": "",
            "positions": [],
            "orders": [],
            "executions": [],
            "trades": [],
            # A new account starts without an executable quote.  Static
            # defaults used by old accounts must never become a fake fill.
            "marks": {},
            "markets": {},
        }
        doc.setdefault("accounts", {})[uid] = acct
        _save(doc)
        return _public(acct)


def get_account(user_id: Any, *, workspace_id: str = "") -> Dict[str, Any]:
    uid = _account_key(user_id, workspace_id)
    with _LOCK:
        doc = _load()
        acct = (doc.get("accounts") or {}).get(uid)
        if not acct:
            raise PracticeTradingError("Учебный счёт не создан.", 404)
        _roll_day(acct)
        _mark_to_market(acct)
        _save(doc)
        return _public(acct)


def _roll_day(acct: Dict[str, Any]) -> None:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if str(acct.get("day_key") or "") != today:
        acct["day_key"] = today
        acct["day_start_balance"] = float(acct.get("equity") or acct.get("balance") or 0)
        if _account_status(acct) == "daily_locked":
            acct["locked"] = False
            acct["lock_reason"] = ""
            acct["account_status"] = "active"
            acct["daily_lock_released_at_utc"] = _now_iso()


def _account_status(acct: Dict[str, Any]) -> str:
    """Normalize legacy accounts into a small, explicit prop-account lifecycle."""
    status = str(acct.get("account_status") or "").strip().lower()
    if status not in _ACCOUNT_STATUSES:
        reason = str(acct.get("lock_reason") or "")
        if bool(acct.get("locked")):
            status = "failed" if reason in {"max_drawdown", "account_depleted"} else "daily_locked"
        else:
            status = "active"
        acct["account_status"] = status
    return status


def _lock_account(acct: Dict[str, Any], *, reason: str, status: str) -> None:
    was_locked = bool(acct.get("locked"))
    previous_reason = str(acct.get("lock_reason") or "")
    previous_status = _account_status(acct)
    acct["locked"] = True
    acct["lock_reason"] = reason
    acct["account_status"] = status
    if not was_locked or previous_reason != reason:
        acct["locked_at_utc"] = _now_iso()
    if status == "failed" and previous_status != "failed":
        acct["failed_at_utc"] = _now_iso()


def _mark_to_market(acct: Dict[str, Any]) -> None:
    unrealized = 0.0
    for pos in acct.get("positions") or []:
        mark = _mark(pos.get("symbol"), acct.get("marks") or {})
        qty = int(pos.get("quantity") or 0)
        side = str(pos.get("side") or "Long")
        entry = float(pos.get("avg_price") or 0)
        pv = _point_value(str(pos.get("symbol") or ""))
        direction = 1 if side == "Long" else -1
        pnl = (mark - entry) * direction * qty * pv
        pos["mark"] = mark
        pos["unrealized_pnl"] = round(pnl, 2)
        unrealized += pnl
    acct["unrealized_pnl"] = round(unrealized, 2)
    acct["equity"] = round(float(acct.get("balance") or 0) + unrealized, 2)
    _apply_risk(acct)


def _apply_risk(acct: Dict[str, Any]) -> None:
    day_start = float(acct.get("day_start_balance") or acct.get("deposit") or 0)
    equity = float(acct.get("equity") or 0)
    daily_pnl = equity - day_start
    dd = equity - float(acct.get("deposit") or 0)
    status = _account_status(acct)
    # A failed virtual prop account remains closed even if an open position
    # later marks back in profit.  The student deliberately opens a new
    # virtual account via reset, matching the intended evaluation lifecycle.
    if status == "failed":
        acct["locked"] = True
        return
    if equity <= 0:
        _lock_account(acct, reason="account_depleted", status="failed")
    elif dd <= -abs(float(acct.get("max_drawdown") or 0)):
        _lock_account(acct, reason="max_drawdown", status="failed")
    elif status == "daily_locked":
        acct["locked"] = True
    elif daily_pnl <= -abs(float(acct.get("daily_loss_limit") or 0)):
        _lock_account(acct, reason="daily_loss", status="daily_locked")
    else:
        acct["locked"] = False
        acct["lock_reason"] = ""
        acct["account_status"] = "active"


def _public(acct: Dict[str, Any]) -> Dict[str, Any]:
    reserved_quantity = _reserved_quantity(acct)
    equity = float(acct.get("equity") or 0)
    market_rows = acct.get("markets") if isinstance(acct.get("markets"), dict) else {}
    return {
        "ok": True,
        "mode": "practice",
        "badge": acct.get("badge") or "Учебный счёт · не реальные деньги",
        "account": {
            "account_id": acct.get("account_id"),
            "workspace_id": acct.get("workspace_id") or "",
            "balance": acct.get("balance"),
            "equity": acct.get("equity"),
            "deposit": acct.get("deposit"),
            "unrealized_pnl": acct.get("unrealized_pnl") or 0,
            "commission": acct.get("commission"),
            "daily_loss_limit": acct.get("daily_loss_limit"),
            "max_drawdown": acct.get("max_drawdown"),
            "position_limit": acct.get("position_limit"),
            "account_status": _account_status(acct),
            "locked": bool(acct.get("locked")),
            "lock_reason": acct.get("lock_reason") or "",
            "requires_new_account": _account_status(acct) == "failed",
            "symbol_default": acct.get("symbol_default"),
            "day_pnl": round(float(acct.get("equity") or 0) - float(acct.get("day_start_balance") or 0), 2),
            # This is explicitly virtual buying power, not broker margin.
            "buying_power": round(max(0.0, equity), 2),
            "contracts_available": max(0, int(acct.get("position_limit") or 4) - reserved_quantity),
        },
        "positions": list(acct.get("positions") or []),
        "orders": [o for o in (acct.get("orders") or []) if o.get("status") == "working"],
        "order_history": list(reversed(acct.get("orders") or []))[:100],
        "executions": list(reversed(acct.get("executions") or []))[:100],
        "trades": list(reversed(acct.get("trades") or []))[:100],
        "marks": dict(acct.get("marks") or {}),
        "markets": {
            str(symbol): dict(row)
            for symbol, row in market_rows.items()
            if isinstance(row, dict)
        },
        "layouts": [1, 2, 4],
    }


def reset_account(user_id: Any, *, workspace_id: str = "") -> Dict[str, Any]:
    """Delete only this user's virtual account; no live contour is touched."""
    uid = _account_key(user_id, workspace_id)
    with _LOCK:
        doc = _load()
        accounts = doc.setdefault("accounts", {})
        existed = uid in accounts
        accounts.pop(uid, None)
        _save(doc)
    return {"ok": True, "deleted": existed, "mode": "practice"}


def _validate_brackets(side: str, reference: float, stop_loss: float,
                       take_profit: float) -> None:
    if stop_loss:
        if side == "Long" and stop_loss >= reference:
            raise PracticeTradingError("Для Long Stop Loss должен быть ниже цены входа.")
        if side == "Short" and stop_loss <= reference:
            raise PracticeTradingError("Для Short Stop Loss должен быть выше цены входа.")
    if take_profit:
        if side == "Long" and take_profit <= reference:
            raise PracticeTradingError("Для Long Take Profit должен быть выше цены входа.")
        if side == "Short" and take_profit >= reference:
            raise PracticeTradingError("Для Short Take Profit должен быть ниже цены входа.")


def _is_marketable(side: str, limit_price: float, mark: float) -> bool:
    return mark <= limit_price if side == "Long" else mark >= limit_price


def _reserved_quantity(acct: Dict[str, Any]) -> int:
    opened = sum(int(p.get("quantity") or 0) for p in acct.get("positions") or [])
    working = sum(
        int(o.get("quantity") or 0)
        for o in acct.get("orders") or []
        if o.get("status") == "working"
    )
    return opened + working


def _fill_risk_reason(acct: Dict[str, Any], quantity: int) -> str:
    commission = float(acct.get("commission") or 0) * int(quantity)
    projected_equity = float(acct.get("equity") or 0) - commission
    day_start = float(acct.get("day_start_balance") or acct.get("deposit") or 0)
    if projected_equity - day_start <= -abs(float(acct.get("daily_loss_limit") or 0)):
        return "daily_loss"
    if projected_equity - float(acct.get("deposit") or 0) <= -abs(float(acct.get("max_drawdown") or 0)):
        return "max_drawdown"
    return ""


def _record_open_fill(acct: Dict[str, Any], order: Dict[str, Any],
                      fill_price: float) -> Dict[str, Any]:
    qty = int(order.get("quantity") or 0)
    symbol = str(order.get("symbol") or "")
    side = str(order.get("side") or "")
    commission = float(acct.get("commission") or 0) * qty
    order["status"] = "filled"
    order["filled_at_utc"] = _now_iso()
    order["fill_price"] = fill_price
    pos = next(
        (p for p in acct.get("positions") or []
         if p.get("symbol") == symbol and p.get("side") == side),
        None,
    )
    if pos is None:
        pos = {
            "position_id": "pos_" + secrets.token_hex(4),
            "symbol": symbol,
            "side": side,
            "quantity": qty,
            "avg_price": fill_price,
            "opened_at_utc": _now_iso(),
            "stop_loss": float(order.get("stop_loss") or 0),
            "take_profit": float(order.get("take_profit") or 0),
        }
        acct.setdefault("positions", []).append(pos)
    else:
        total = int(pos.get("quantity") or 0) + qty
        pos["avg_price"] = round(
            (float(pos.get("avg_price") or 0) * int(pos.get("quantity") or 0)
             + fill_price * qty) / total,
            4,
        )
        pos["quantity"] = total
        if order.get("stop_loss"):
            pos["stop_loss"] = float(order["stop_loss"])
        if order.get("take_profit"):
            pos["take_profit"] = float(order["take_profit"])
    acct["balance"] = round(float(acct.get("balance") or 0) - commission, 2)
    execution = {
        "execution_id": "exe_" + secrets.token_hex(5),
        "order_id": order.get("order_id"),
        "symbol": symbol,
        "side": side,
        "quantity": qty,
        "price": fill_price,
        "commission": commission,
        "kind": "entry",
        "at_utc": _now_iso(),
    }
    acct.setdefault("executions", []).append(execution)
    trade = {
        "trade_id": "tr_" + secrets.token_hex(4),
        "order_id": order.get("order_id"),
        "execution_id": execution["execution_id"],
        "symbol": symbol,
        "side": side,
        "quantity": qty,
        "price": fill_price,
        "commission": commission,
        "pnl": 0,
        "at_utc": execution["at_utc"],
        "action": "open",
    }
    acct.setdefault("trades", []).append(trade)
    _mark_to_market(acct)
    return trade


def place_order(
    user_id: Any,
    *,
    symbol: str,
    side: str,
    quantity: int = 1,
    order_type: str = "market",
    limit_price: float = 0,
    stop_loss: float = 0,
    take_profit: float = 0,
    workspace_id: str = "",
) -> Dict[str, Any]:
    uid = _account_key(user_id, workspace_id)
    side_n = _side(side)
    order_type_n = _order_type(order_type)
    quantity_number = _finite(
        quantity, "Количество", positive=True, allow_zero=False,
    )
    if not quantity_number.is_integer():
        raise PracticeTradingError("Количество должно быть целым числом.")
    qty = int(quantity_number)
    if qty < 1 or qty > 20:
        raise PracticeTradingError("Количество от 1 до 20.")
    symbol_n = _symbol(symbol)
    limit_n = _finite(limit_price, "Limit", positive=True)
    stop_n = _finite(stop_loss, "Stop Loss", positive=True)
    take_n = _finite(take_profit, "Take Profit", positive=True)
    with _LOCK:
        doc = _load()
        acct = (doc.get("accounts") or {}).get(uid)
        if not acct:
            raise PracticeTradingError("Сначала создайте учебный счёт.", 404)
        _roll_day(acct)
        _mark_to_market(acct)
        if acct.get("locked"):
            status = _account_status(acct)
            reason = str(acct.get("lock_reason") or "risk lock")
            detail = {
                "daily_loss": "достигнут дневной лимит; счёт станет доступен в следующий UTC-день",
                "max_drawdown": "достигнута максимальная просадка; откройте новый виртуальный счёт",
                "account_depleted": "виртуальный баланс исчерпан; откройте новый виртуальный счёт",
            }.get(reason, reason)
            raise PracticeTradingError(
                f"Учебная торговля остановлена ({status}): {detail}.",
                403,
            )
        if _reserved_quantity(acct) + qty > int(acct.get("position_limit") or 4):
            raise PracticeTradingError("Превышен лимит позиции.")
        executable_mark = _tradable_mark(acct, symbol_n)
        if order_type_n == "limit" and limit_n <= 0:
            raise PracticeTradingError("Для limit укажите цену.")
        if order_type_n == "market" and executable_mark is None:
            raise PracticeTradingError(_market_unavailable_message(symbol_n), 409)
        marketable = bool(
            order_type_n == "market"
            or (executable_mark is not None and _is_marketable(side_n, limit_n, executable_mark))
        )
        reference = executable_mark if marketable else limit_n
        assert reference is not None
        _validate_brackets(side_n, reference, stop_n, take_n)
        order = {
            "order_id": "ord_" + secrets.token_hex(4),
            "symbol": symbol_n,
            "side": side_n,
            "quantity": qty,
            "order_type": order_type_n,
            "limit_price": limit_n if order_type_n == "limit" else 0,
            "status": "working",
            "created_at_utc": _now_iso(),
            "stop_loss": stop_n,
            "take_profit": take_n,
        }
        acct.setdefault("orders", []).append(order)
        if not marketable:
            _save(doc)
            return {"ok": True, "filled": False, "order": order, **_public(acct)}
        risk_reason = _fill_risk_reason(acct, qty)
        if risk_reason:
            order["status"] = "rejected_risk"
            order["reject_reason"] = risk_reason
            _save(doc)
            raise PracticeTradingError(f"Ордер отклонён risk guard: {risk_reason}.", 403)
        # ``marketable`` guarantees a current trusted mark above.
        trade = _record_open_fill(acct, order, float(executable_mark))
        _save(doc)
        return {"ok": True, "filled": True, "order": order, "trade": trade, **_public(acct)}


def close_position(user_id: Any, position_id: str = "", *, symbol: str = "",
                   workspace_id: str = "") -> Dict[str, Any]:
    uid = _account_key(user_id, workspace_id)
    symbol_n = _symbol(symbol) if str(symbol or "").strip() else ""
    with _LOCK:
        doc = _load()
        acct = (doc.get("accounts") or {}).get(uid)
        if not acct:
            raise PracticeTradingError("Счёт не найден.", 404)
        _mark_to_market(acct)
        positions = list(acct.get("positions") or [])
        target = None
        for pos in positions:
            if position_id and pos.get("position_id") == position_id:
                target = pos
                break
            if symbol_n and pos.get("symbol") == symbol_n:
                target = pos
                break
        if target is None and not position_id and not symbol_n and positions:
            target = positions[0]
        if target is None:
            raise PracticeTradingError("Нет открытой позиции.", 404)
        mark = _tradable_mark(acct, str(target.get("symbol") or ""))
        if mark is None:
            raise PracticeTradingError(
                _market_unavailable_message(str(target.get("symbol") or "инструмента")),
                409,
            )
        qty = int(target.get("quantity") or 0)
        side = str(target.get("side") or "Long")
        entry = float(target.get("avg_price") or 0)
        pv = _point_value(str(target.get("symbol") or ""))
        direction = 1 if side == "Long" else -1
        pnl = round((mark - entry) * direction * qty * pv, 2)
        commission = float(acct.get("commission") or 0) * qty
        acct["balance"] = round(float(acct["balance"]) + pnl - commission, 2)
        acct["positions"] = [p for p in positions if p is not target]
        order = {
            "order_id": "ord_" + secrets.token_hex(4),
            "symbol": target.get("symbol"),
            "side": "Short" if side == "Long" else "Long",
            "quantity": qty,
            "order_type": "market",
            "status": "filled",
            "created_at_utc": _now_iso(),
            "filled_at_utc": _now_iso(),
            "fill_price": mark,
            "reduce_only": True,
        }
        acct.setdefault("orders", []).append(order)
        execution = {
            "execution_id": "exe_" + secrets.token_hex(5),
            "order_id": order["order_id"],
            "symbol": target.get("symbol"),
            "side": order["side"],
            "quantity": qty,
            "price": mark,
            "commission": commission,
            "kind": "exit",
            "at_utc": _now_iso(),
        }
        acct.setdefault("executions", []).append(execution)
        trade = {
            "trade_id": "tr_" + secrets.token_hex(4),
            "order_id": order["order_id"], "execution_id": execution["execution_id"],
            "symbol": target.get("symbol"), "side": side, "quantity": qty,
            "price": mark, "commission": commission, "pnl": pnl,
            "at_utc": _now_iso(), "action": "close",
        }
        acct.setdefault("trades", []).append(trade)
        _mark_to_market(acct)
        _save(doc)
        return {"ok": True, "trade": trade, **_public(acct)}


def cancel_order(user_id: Any, order_id: str, *, workspace_id: str = "") -> Dict[str, Any]:
    uid = _account_key(user_id, workspace_id)
    target_id = str(order_id or "").strip()
    if not target_id:
        raise PracticeTradingError("Укажите ордер.")
    with _LOCK:
        doc = _load()
        acct = (doc.get("accounts") or {}).get(uid)
        if not acct:
            raise PracticeTradingError("Счёт не найден.", 404)
        order = next(
            (row for row in acct.get("orders") or [] if str(row.get("order_id") or "") == target_id),
            None,
        )
        if order is None:
            raise PracticeTradingError("Ордер не найден.", 404)
        if order.get("status") != "working":
            raise PracticeTradingError("Отменить можно только рабочий ордер.", 409)
        order["status"] = "cancelled_by_user"
        order["cancelled_at_utc"] = _now_iso()
        _mark_to_market(acct)
        _save(doc)
        return {"ok": True, "cancelled_order_id": target_id, **_public(acct)}


def tick_marks(user_id: Any, *, symbol: str = "", price: float = 0,
               market: Optional[Dict[str, Any]] = None,
               workspace_id: str = "") -> Dict[str, Any]:
    """Apply a server-verified market update to the virtual account.

    ``price`` is never supplied by the browser.  A zero/missing value records
    an unavailable market state and deliberately performs no random walk, no
    fill, and no automatic SL/TP action.
    """
    uid = _account_key(user_id, workspace_id)
    price_n = _finite(price, "Цена", positive=True)
    with _LOCK:
        doc = _load()
        acct = (doc.get("accounts") or {}).get(uid)
        if not acct:
            raise PracticeTradingError("Счёт не найден.", 404)
        _roll_day(acct)
        root = _symbol(symbol or acct.get("symbol_default") or "MNQ")
        marks = dict(acct.get("marks") or {})
        markets = dict(acct.get("markets") or {})
        market_state = _normalize_market(root, price_n, market)
        if market_state["tradable"]:
            marks[root] = float(market_state["price"])
        markets[root] = market_state
        acct["marks"] = marks
        acct["markets"] = markets
        _mark_to_market(acct)

        # A risk lock cancels resting entry orders; exits remain available.
        if acct.get("locked"):
            for order in acct.get("orders") or []:
                if order.get("status") == "working":
                    order["status"] = "cancelled_risk"
                    order["cancelled_at_utc"] = _now_iso()
                    order["cancel_reason"] = acct.get("lock_reason") or "risk_lock"
        elif market_state["tradable"]:
            for order in acct.get("orders") or []:
                if order.get("status") != "working" or order.get("symbol") != root:
                    continue
                mark = _mark(root, marks)
                if not _is_marketable(
                    str(order.get("side") or ""),
                    float(order.get("limit_price") or 0),
                    mark,
                ):
                    continue
                qty = int(order.get("quantity") or 0)
                opened = sum(int(p.get("quantity") or 0) for p in acct.get("positions") or [])
                if opened + qty > int(acct.get("position_limit") or 4):
                    order["status"] = "rejected_position_limit"
                    order["rejected_at_utc"] = _now_iso()
                    continue
                risk_reason = _fill_risk_reason(acct, qty)
                if risk_reason:
                    order["status"] = "rejected_risk"
                    order["reject_reason"] = risk_reason
                    order["rejected_at_utc"] = _now_iso()
                    continue
                _record_open_fill(acct, order, mark)
                if acct.get("locked"):
                    break

            # SL/TP is evaluated only for the instrument that just received a
            # current, server-verified price.  An unavailable quote cannot
            # invent a stop fill for another symbol.
            still = []
            for pos in list(acct.get("positions") or []):
                if str(pos.get("symbol") or "") != root:
                    still.append(pos)
                    continue
                mark = float(market_state["price"])
                sl = float(pos.get("stop_loss") or 0)
                tp = float(pos.get("take_profit") or 0)
                side = str(pos.get("side") or "Long")
                hit = False
                if side == "Long":
                    hit = (sl and mark <= sl) or (tp and mark >= tp)
                else:
                    hit = (sl and mark >= sl) or (tp and mark <= tp)
                if hit:
                    qty = int(pos.get("quantity") or 0)
                    entry = float(pos.get("avg_price") or 0)
                    pv = _point_value(str(pos.get("symbol") or ""))
                    direction = 1 if side == "Long" else -1
                    pnl = round((mark - entry) * direction * qty * pv, 2)
                    commission = float(acct.get("commission") or 0) * qty
                    acct["balance"] = round(float(acct["balance"]) + pnl - commission, 2)
                    exit_order = {
                        "order_id": "ord_" + secrets.token_hex(4),
                        "symbol": pos.get("symbol"),
                        "side": "Short" if side == "Long" else "Long",
                        "quantity": qty,
                        "order_type": "stop" if sl and ((side == "Long" and mark <= sl) or (side == "Short" and mark >= sl)) else "take_profit",
                        "status": "filled",
                        "created_at_utc": _now_iso(),
                        "filled_at_utc": _now_iso(),
                        "fill_price": mark,
                        "reduce_only": True,
                    }
                    acct.setdefault("orders", []).append(exit_order)
                    execution = {
                        "execution_id": "exe_" + secrets.token_hex(5),
                        "order_id": exit_order["order_id"],
                        "symbol": pos.get("symbol"),
                        "side": exit_order["side"],
                        "quantity": qty,
                        "price": mark,
                        "commission": commission,
                        "kind": "exit",
                        "at_utc": _now_iso(),
                    }
                    acct.setdefault("executions", []).append(execution)
                    acct.setdefault("trades", []).append({
                        "trade_id": "tr_" + secrets.token_hex(4),
                        "order_id": exit_order["order_id"],
                        "execution_id": execution["execution_id"],
                        "symbol": pos.get("symbol"), "side": side, "quantity": qty,
                        "price": mark, "commission": commission, "pnl": pnl,
                        "at_utc": _now_iso(), "action": "sl_tp",
                    })
                else:
                    still.append(pos)
            acct["positions"] = still
        _mark_to_market(acct)
        _save(doc)
        return _public(acct)


def report(user_id: Any, *, workspace_id: str = "") -> Dict[str, Any]:
    acct_view = get_account(user_id, workspace_id=workspace_id)
    trades = acct_view.get("trades") or []
    closed = [t for t in trades if t.get("action") in {"close", "sl_tp"}]
    wins = [t for t in closed if float(t.get("pnl") or 0) > 0]
    return {
        "ok": True,
        "mode": "practice",
        "badge": acct_view.get("badge"),
        "account": acct_view.get("account"),
        "trade_count": len(closed),
        "winrate": round(100.0 * len(wins) / max(len(closed), 1), 1),
        "realized_pnl": round(sum(float(t.get("pnl") or 0) for t in closed), 2),
        "commissions": round(sum(float(t.get("commission") or 0) for t in trades), 2),
        "trades": closed[:50],
        "orders": acct_view.get("order_history") or [],
        "executions": acct_view.get("executions") or [],
    }
