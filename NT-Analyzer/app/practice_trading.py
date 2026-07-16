"""Practice trading — virtual money, Topstep-like mechanics (not Micro Live / not NT live).

Isolated per-user store under ``data/runtime/practice_accounts.json``.
Never writes to live NT command queues.
"""
from __future__ import annotations

import json
import os
import secrets
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


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


def _root() -> Path:
    return Path(__file__).resolve().parent.parent


def _store_path() -> Path:
    return _root() / "data" / "runtime" / "practice_accounts.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


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
    root = str(symbol or "").split()[0].upper()
    if root in accounts_marks:
        return float(accounts_marks[root])
    return float(_DEFAULT_MARKS.get(root, 100.0))


def create_account(
    user_id: Any,
    *,
    deposit: float = 50000,
    commission: float = 2.0,
    daily_loss_limit: float = 1000,
    max_drawdown: float = 2000,
    position_limit: int = 4,
    symbol: str = "MNQ",
) -> Dict[str, Any]:
    uid = str(int(user_id or 0))
    if int(user_id or 0) <= 0:
        raise PracticeTradingError("Требуется вход.", 401)
    deposit = float(deposit)
    if deposit < 1000 or deposit > 500000:
        raise PracticeTradingError("Депозит должен быть от $1 000 до $500 000.")
    with _LOCK:
        doc = _load()
        acct = {
            "account_id": "prac_" + secrets.token_hex(6),
            "user_id": int(user_id),
            "mode": "practice",
            "badge": "Учебный счёт · не реальные деньги",
            "created_at_utc": _now_iso(),
            "deposit": deposit,
            "balance": deposit,
            "equity": deposit,
            "commission": float(commission),
            "daily_loss_limit": float(daily_loss_limit),
            "max_drawdown": float(max_drawdown),
            "position_limit": int(position_limit),
            "symbol_default": str(symbol or "MNQ").upper(),
            "day_start_balance": deposit,
            "day_key": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "locked": False,
            "lock_reason": "",
            "positions": [],
            "orders": [],
            "trades": [],
            "marks": dict(_DEFAULT_MARKS),
        }
        doc.setdefault("accounts", {})[uid] = acct
        _save(doc)
        return _public(acct)


def get_account(user_id: Any) -> Dict[str, Any]:
    uid = str(int(user_id or 0))
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
        if acct.get("locked") and acct.get("lock_reason") == "daily_loss":
            acct["locked"] = False
            acct["lock_reason"] = ""


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
    if daily_pnl <= -abs(float(acct.get("daily_loss_limit") or 0)):
        acct["locked"] = True
        acct["lock_reason"] = "daily_loss"
    if dd <= -abs(float(acct.get("max_drawdown") or 0)):
        acct["locked"] = True
        acct["lock_reason"] = "max_drawdown"


def _public(acct: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "ok": True,
        "mode": "practice",
        "badge": acct.get("badge") or "Учебный счёт · не реальные деньги",
        "account": {
            "account_id": acct.get("account_id"),
            "balance": acct.get("balance"),
            "equity": acct.get("equity"),
            "deposit": acct.get("deposit"),
            "unrealized_pnl": acct.get("unrealized_pnl") or 0,
            "commission": acct.get("commission"),
            "daily_loss_limit": acct.get("daily_loss_limit"),
            "max_drawdown": acct.get("max_drawdown"),
            "position_limit": acct.get("position_limit"),
            "locked": bool(acct.get("locked")),
            "lock_reason": acct.get("lock_reason") or "",
            "symbol_default": acct.get("symbol_default"),
            "day_pnl": round(float(acct.get("equity") or 0) - float(acct.get("day_start_balance") or 0), 2),
        },
        "positions": list(acct.get("positions") or []),
        "orders": [o for o in (acct.get("orders") or []) if o.get("status") == "working"],
        "trades": list(reversed(acct.get("trades") or []))[:100],
        "marks": dict(acct.get("marks") or {}),
        "layouts": [1, 2, 4],
    }


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
) -> Dict[str, Any]:
    uid = str(int(user_id or 0))
    side_n = "Long" if str(side or "").lower() in {"buy", "long"} else "Short"
    order_type_n = str(order_type or "market").lower()
    qty = int(quantity or 0)
    if qty < 1 or qty > 20:
        raise PracticeTradingError("Количество от 1 до 20.")
    symbol_n = str(symbol or "MNQ").upper()
    with _LOCK:
        doc = _load()
        acct = (doc.get("accounts") or {}).get(uid)
        if not acct:
            raise PracticeTradingError("Сначала создайте учебный счёт.", 404)
        _roll_day(acct)
        _mark_to_market(acct)
        if acct.get("locked"):
            raise PracticeTradingError(
                f"Торговля заблокирована: {acct.get('lock_reason') or 'risk lock'}.",
                403,
            )
        open_qty = sum(int(p.get("quantity") or 0) for p in acct.get("positions") or [])
        if open_qty + qty > int(acct.get("position_limit") or 4):
            raise PracticeTradingError("Превышен лимит позиции.")
        mark = _mark(symbol_n, acct.get("marks") or {})
        fill_price = mark if order_type_n == "market" else float(limit_price or 0)
        if order_type_n == "limit" and fill_price <= 0:
            raise PracticeTradingError("Для limit укажите цену.")
        # Instant fill for MVP (market always; limit fills if within 0.5% of mark).
        if order_type_n == "limit" and abs(fill_price - mark) / max(mark, 1) > 0.005:
            order = {
                "order_id": "ord_" + secrets.token_hex(4),
                "symbol": symbol_n, "side": side_n, "quantity": qty,
                "order_type": "limit", "limit_price": fill_price,
                "status": "working", "created_at_utc": _now_iso(),
                "stop_loss": float(stop_loss or 0), "take_profit": float(take_profit or 0),
            }
            acct.setdefault("orders", []).append(order)
            _save(doc)
            return {"ok": True, "filled": False, "order": order, **_public(acct)}
        commission = float(acct.get("commission") or 0) * qty
        pos = next((p for p in acct.get("positions") or [] if p.get("symbol") == symbol_n and p.get("side") == side_n), None)
        if pos is None:
            pos = {
                "position_id": "pos_" + secrets.token_hex(4),
                "symbol": symbol_n, "side": side_n, "quantity": qty,
                "avg_price": fill_price, "opened_at_utc": _now_iso(),
                "stop_loss": float(stop_loss or 0), "take_profit": float(take_profit or 0),
            }
            acct.setdefault("positions", []).append(pos)
        else:
            total = int(pos["quantity"]) + qty
            pos["avg_price"] = round((float(pos["avg_price"]) * int(pos["quantity"]) + fill_price * qty) / total, 4)
            pos["quantity"] = total
            if stop_loss:
                pos["stop_loss"] = float(stop_loss)
            if take_profit:
                pos["take_profit"] = float(take_profit)
        acct["balance"] = round(float(acct["balance"]) - commission, 2)
        trade = {
            "trade_id": "tr_" + secrets.token_hex(4),
            "symbol": symbol_n, "side": side_n, "quantity": qty,
            "price": fill_price, "commission": commission,
            "pnl": 0, "at_utc": _now_iso(), "action": "open",
        }
        acct.setdefault("trades", []).append(trade)
        _mark_to_market(acct)
        _save(doc)
        return {"ok": True, "filled": True, "trade": trade, **_public(acct)}


def close_position(user_id: Any, position_id: str = "", *, symbol: str = "") -> Dict[str, Any]:
    uid = str(int(user_id or 0))
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
            if symbol and pos.get("symbol") == str(symbol).upper():
                target = pos
                break
        if target is None and positions:
            target = positions[0]
        if target is None:
            raise PracticeTradingError("Нет открытой позиции.", 404)
        mark = _mark(target.get("symbol"), acct.get("marks") or {})
        qty = int(target.get("quantity") or 0)
        side = str(target.get("side") or "Long")
        entry = float(target.get("avg_price") or 0)
        pv = _point_value(str(target.get("symbol") or ""))
        direction = 1 if side == "Long" else -1
        pnl = round((mark - entry) * direction * qty * pv, 2)
        commission = float(acct.get("commission") or 0) * qty
        acct["balance"] = round(float(acct["balance"]) + pnl - commission, 2)
        acct["positions"] = [p for p in positions if p is not target]
        trade = {
            "trade_id": "tr_" + secrets.token_hex(4),
            "symbol": target.get("symbol"), "side": side, "quantity": qty,
            "price": mark, "commission": commission, "pnl": pnl,
            "at_utc": _now_iso(), "action": "close",
        }
        acct.setdefault("trades", []).append(trade)
        _mark_to_market(acct)
        _save(doc)
        return {"ok": True, "trade": trade, **_public(acct)}


def tick_marks(user_id: Any, *, symbol: str = "", price: float = 0) -> Dict[str, Any]:
    """Owner/test helper or client sim: update mark and evaluate SL/TP."""
    uid = str(int(user_id or 0))
    with _LOCK:
        doc = _load()
        acct = (doc.get("accounts") or {}).get(uid)
        if not acct:
            raise PracticeTradingError("Счёт не найден.", 404)
        root = str(symbol or acct.get("symbol_default") or "MNQ").split()[0].upper()
        marks = dict(acct.get("marks") or _DEFAULT_MARKS)
        if price > 0:
            marks[root] = float(price)
        else:
            # tiny random walk for UI liveliness
            cur = float(marks.get(root) or _DEFAULT_MARKS.get(root) or 100)
            marks[root] = round(cur * (1 + ((time.time() % 7) - 3) * 0.00015), 2)
        acct["marks"] = marks
        # SL/TP
        still = []
        for pos in list(acct.get("positions") or []):
            mark = _mark(pos.get("symbol"), marks)
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
                acct.setdefault("trades", []).append({
                    "trade_id": "tr_" + secrets.token_hex(4),
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


def report(user_id: Any) -> Dict[str, Any]:
    acct_view = get_account(user_id)
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
    }
