"""Micro Live — real money × scale (separate from Demo and Practice).

MVP on staging simulates ledger fills. Production real broker hooks stay
behind ``runtime_env.allow_live_orders`` / ``allow_real_payments``.
"""
from __future__ import annotations

import json
import os
import secrets
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from . import runtime_env


class MicroLiveError(RuntimeError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = int(status)


_LOCK = threading.RLock()
_FREE_TRADES_DEFAULT = 5
_DEFAULT_SCALE = 100  # 1:100


def _root() -> Path:
    return Path(__file__).resolve().parent.parent


def _store_path() -> Path:
    return _root() / "data" / "runtime" / "micro_live.json"


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


def ensure_account(user_id: Any, *, scale: int = _DEFAULT_SCALE) -> Dict[str, Any]:
    uid = str(int(user_id or 0))
    if int(user_id or 0) <= 0:
        raise MicroLiveError("Требуется вход.", 401)
    with _LOCK:
        doc = _load()
        acct = (doc.get("accounts") or {}).get(uid)
        if acct is None:
            acct = {
                "user_id": int(user_id),
                "mode": "micro_live",
                "badge": f"Реальные деньги · масштаб 1:{int(scale)}",
                "scale": int(scale) or _DEFAULT_SCALE,
                "free_trades_left": _FREE_TRADES_DEFAULT,
                "balance": 0.0,
                "equity": 0.0,
                "locked": False,
                "lock_reason": "",
                "max_daily_loss": 25.0,
                "day_start_equity": 0.0,
                "day_key": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                "trades": [],
                "warnings_accepted_at_utc": "",
                "created_at_utc": _now_iso(),
            }
            doc.setdefault("accounts", {})[uid] = acct
            _save(doc)
        return _public(acct)


def accept_warnings(user_id: Any) -> Dict[str, Any]:
    uid = str(int(user_id or 0))
    with _LOCK:
        doc = _load()
        acct = (doc.get("accounts") or {}).get(uid) or ensure_account(user_id)
        # ensure_account may have written; reload
        doc = _load()
        acct = doc["accounts"][uid]
        acct["warnings_accepted_at_utc"] = _now_iso()
        _save(doc)
        return _public(acct)


def deposit(user_id: Any, amount: float) -> Dict[str, Any]:
    if runtime_env.is_staging() and not runtime_env.allow_real_payments():
        # Staging stub credit.
        pass
    elif not runtime_env.allow_real_payments():
        raise MicroLiveError("Реальные платежи отключены.", 403)
    uid = str(int(user_id or 0))
    amt = float(amount or 0)
    if amt <= 0 or amt > 10000:
        raise MicroLiveError("Сумма депозита некорректна.")
    with _LOCK:
        doc = _load()
        if uid not in (doc.get("accounts") or {}):
            ensure_account(user_id)
            doc = _load()
        acct = doc["accounts"][uid]
        acct["balance"] = round(float(acct.get("balance") or 0) + amt, 2)
        acct["equity"] = float(acct["balance"])
        acct.setdefault("ledger", []).append({
            "type": "deposit_stub" if runtime_env.is_staging() else "deposit",
            "amount": amt, "at": _now_iso(),
        })
        _save(doc)
        return _public(acct)


def place_scaled_trade(
    user_id: Any,
    *,
    symbol: str = "MNQ",
    side: str = "buy",
    notional_full: float = 100.0,
    pnl_full: float = 0.0,
) -> Dict[str, Any]:
    """Record a micro trade. ``notional_full`` / ``pnl_full`` are full-size equivalents."""
    if runtime_env.is_staging() and not runtime_env.allow_live_orders():
        simulated = True
    elif not runtime_env.allow_live_orders():
        raise MicroLiveError("Live-ордера отключены в этой среде.", 403)
    else:
        simulated = False
    uid = str(int(user_id or 0))
    with _LOCK:
        doc = _load()
        if uid not in (doc.get("accounts") or {}):
            ensure_account(user_id)
            doc = _load()
        acct = doc["accounts"][uid]
        if not acct.get("warnings_accepted_at_utc"):
            raise MicroLiveError("Примите риск-предупреждение перед первой сделкой.", 403)
        if acct.get("locked"):
            raise MicroLiveError(f"Micro Live заблокирован: {acct.get('lock_reason')}", 403)
        scale = max(1, int(acct.get("scale") or _DEFAULT_SCALE))
        free_left = int(acct.get("free_trades_left") or 0)
        used_free = False
        if free_left > 0:
            acct["free_trades_left"] = free_left - 1
            used_free = True
            micro_pnl = 0.0  # free trades don't debit user wallet
        else:
            micro_pnl = round(float(pnl_full) / scale, 4)
            if float(acct.get("balance") or 0) + micro_pnl < -abs(float(acct.get("max_daily_loss") or 25)):
                acct["locked"] = True
                acct["lock_reason"] = "daily_loss"
            acct["balance"] = round(float(acct.get("balance") or 0) + micro_pnl, 4)
            acct["equity"] = acct["balance"]
        trade = {
            "trade_id": "ml_" + secrets.token_hex(5),
            "symbol": str(symbol or "MNQ").upper(),
            "side": "Long" if str(side).lower() in {"buy", "long"} else "Short",
            "scale": scale,
            "notional_full": float(notional_full),
            "notional_micro": round(float(notional_full) / scale, 4),
            "pnl_full": float(pnl_full),
            "pnl_micro": micro_pnl,
            "free_trade": used_free,
            "simulated": simulated or runtime_env.is_staging(),
            "at_utc": _now_iso(),
            "comparison": (
                f"Вы {'заработали' if float(pnl_full) >= 0 else 'потеряли'} "
                f"${abs(micro_pnl):.4f} ≈ ${abs(float(pnl_full)):.2f} на полном объёме при 1:{scale}"
            ),
        }
        acct.setdefault("trades", []).append(trade)
        _save(doc)
        return {"ok": True, "trade": trade, **_public(acct)}


def _public(acct: Dict[str, Any]) -> Dict[str, Any]:
    scale = int(acct.get("scale") or _DEFAULT_SCALE)
    return {
        "ok": True,
        "mode": "micro_live",
        "badge": acct.get("badge") or f"Реальные деньги · масштаб 1:{scale}",
        "account": {
            "scale": scale,
            "balance": acct.get("balance"),
            "equity": acct.get("equity"),
            "free_trades_left": acct.get("free_trades_left"),
            "locked": bool(acct.get("locked")),
            "lock_reason": acct.get("lock_reason") or "",
            "warnings_accepted": bool(acct.get("warnings_accepted_at_utc")),
            "max_daily_loss": acct.get("max_daily_loss"),
        },
        "trades": list(reversed(acct.get("trades") or []))[:50],
        "staging_stub": runtime_env.is_staging() and not runtime_env.allow_real_payments(),
    }
