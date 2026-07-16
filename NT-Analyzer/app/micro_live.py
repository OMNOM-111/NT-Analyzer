"""Micro Live — scaled-money ledger with fail-closed provider/broker gates.

Staging uses a physically separate data root and server-generated simulated
fills.  Production deposits and fills are recorded only from verified results
supplied by an internal payment/broker adapter; the public HTTP payload is not
treated as a source of PnL or payment truth.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import secrets
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from . import runtime_env


class MicroLiveError(RuntimeError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = int(status)


_LOCK = threading.RLock()
_FREE_TRADES_DEFAULT = 5
_DEFAULT_SCALE = 100
_DEFAULT_MAX_NOTIONAL_FULL = 5000.0
_DEFAULT_MAX_DAILY_LOSS = 25.0
_DEFAULT_MAX_CONSECUTIVE_LOSSES = 3
_ALLOWED_SYMBOLS = frozenset({"MNQ", "MES", "MGC"})
_ALLOWED_SIDES = {"buy": "Long", "long": "Long", "sell": "Short", "short": "Short"}


def _root() -> Path:
    return Path(__file__).resolve().parent.parent


def _store_path() -> Path:
    return runtime_env.data_root(_root()) / "runtime" / "micro_live.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _day_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _workspace(value: Any) -> str:
    raw = str(value or "").strip()
    if (len(raw) > 160
            or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_." for ch in raw)):
        raise MicroLiveError("Некорректная рабочая область.")
    return raw


def _account_key(user_id: Any, workspace_id: Any = "") -> Tuple[str, int, str]:
    try:
        user = int(user_id or 0)
    except (TypeError, ValueError, OverflowError) as exc:
        raise MicroLiveError("Требуется вход.", 401) from exc
    if user <= 0:
        raise MicroLiveError("Требуется вход.", 401)
    workspace = _workspace(workspace_id)
    return (f"{workspace}:{user}" if workspace else str(user)), user, workspace


def _finite(value: Any, label: str, *, positive: bool = False,
            allow_zero: bool = True) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise MicroLiveError(f"{label}: укажите число.") from exc
    if not math.isfinite(number):
        raise MicroLiveError(f"{label}: число должно быть конечным.")
    if positive and (number < 0 or (not allow_zero and number == 0)):
        raise MicroLiveError(f"{label}: значение должно быть больше нуля.")
    return number


def _symbol(value: Any) -> str:
    raw = str(value or "").strip().upper()
    root = raw.split()[0] if raw else ""
    if root not in _ALLOWED_SYMBOLS:
        raise MicroLiveError(
            f"Инструмент {raw or '—'} недоступен. Доступны: {', '.join(sorted(_ALLOWED_SYMBOLS))}."
        )
    return root


def _side(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized not in _ALLOWED_SIDES:
        raise MicroLiveError("Сторона должна быть buy/long или sell/short.")
    return _ALLOWED_SIDES[normalized]


def _load() -> Dict[str, Any]:
    path = _store_path()
    if not path.is_file():
        return {"version": 2, "accounts": {}}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"version": 2, "accounts": {}}
    return doc if isinstance(doc, dict) else {"version": 2, "accounts": {}}


def _save(doc: Dict[str, Any]) -> None:
    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _roll_day(acct: Dict[str, Any]) -> None:
    today = _day_key()
    acct.setdefault("max_daily_loss", _DEFAULT_MAX_DAILY_LOSS)
    acct.setdefault("max_notional_full", _DEFAULT_MAX_NOTIONAL_FULL)
    acct.setdefault("max_consecutive_losses", _DEFAULT_MAX_CONSECUTIVE_LOSSES)
    acct.setdefault("consecutive_losses", 0)
    acct.setdefault("ledger", [])
    acct.setdefault("equity", float(acct.get("balance") or 0))
    acct.setdefault("day_start_equity", float(acct.get("equity") or 0))
    if str(acct.get("day_key") or "") == today:
        return
    acct["day_key"] = today
    acct["day_start_equity"] = float(acct.get("equity") or acct.get("balance") or 0)
    acct["consecutive_losses"] = 0
    if acct.get("lock_reason") in {"daily_loss", "circuit_breaker"}:
        acct["locked"] = False
        acct["lock_reason"] = ""


def _new_account(user: int, workspace: str, scale: int) -> Dict[str, Any]:
    return {
        "user_id": user,
        "workspace_id": workspace,
        "mode": "micro_live",
        "badge": f"Реальные деньги · масштаб 1:{scale}",
        "scale": scale,
        "free_trades_left": _FREE_TRADES_DEFAULT,
        "balance": 0.0,
        "equity": 0.0,
        "locked": False,
        "lock_reason": "",
        "max_daily_loss": _DEFAULT_MAX_DAILY_LOSS,
        "max_notional_full": _DEFAULT_MAX_NOTIONAL_FULL,
        "max_consecutive_losses": _DEFAULT_MAX_CONSECUTIVE_LOSSES,
        "consecutive_losses": 0,
        "day_start_equity": 0.0,
        "day_key": _day_key(),
        "trades": [],
        "ledger": [],
        "warnings_accepted_at_utc": "",
        "created_at_utc": _now_iso(),
    }


def _ensure_locked(doc: Dict[str, Any], key: str, user: int,
                   workspace: str, scale: int) -> Dict[str, Any]:
    accounts = doc.setdefault("accounts", {})
    acct = accounts.get(key)
    if acct is None:
        acct = _new_account(user, workspace, scale)
        accounts[key] = acct
    _roll_day(acct)
    return acct


def ensure_account(user_id: Any, *, scale: int = _DEFAULT_SCALE,
                   workspace_id: str = "") -> Dict[str, Any]:
    key, user, workspace = _account_key(user_id, workspace_id)
    scale_number = _finite(scale, "Масштаб", positive=True, allow_zero=False)
    if not scale_number.is_integer():
        raise MicroLiveError("Масштаб должен быть целым числом.")
    scale_n = int(scale_number)
    if scale_n < 1 or scale_n > 10000:
        raise MicroLiveError("Масштаб должен быть от 1 до 10 000.")
    with _LOCK:
        doc = _load()
        acct = _ensure_locked(doc, key, user, workspace, scale_n)
        _save(doc)
        return _public(acct)


def accept_warnings(user_id: Any, *, workspace_id: str = "") -> Dict[str, Any]:
    key, user, workspace = _account_key(user_id, workspace_id)
    with _LOCK:
        doc = _load()
        acct = _ensure_locked(doc, key, user, workspace, _DEFAULT_SCALE)
        acct["warnings_accepted_at_utc"] = _now_iso()
        _save(doc)
        return _public(acct)


def _verified_payment(result: Optional[Dict[str, Any]], requested: float) -> Tuple[str, float]:
    row = result if isinstance(result, dict) else {}
    if row.get("verified") is not True or str(row.get("status") or "").lower() not in {
        "captured", "settled", "succeeded",
    }:
        raise MicroLiveError("Нет подтверждённого результата платёжного провайдера.", 403)
    provider_id = str(row.get("provider_payment_id") or row.get("payment_id") or "").strip()
    if not provider_id:
        raise MicroLiveError("Платёжный провайдер не вернул id операции.", 403)
    settled = _finite(row.get("amount"), "Подтверждённая сумма", positive=True, allow_zero=False)
    if abs(settled - requested) > 0.0001:
        raise MicroLiveError("Сумма провайдера не совпадает с запросом.", 409)
    return provider_id, settled


def deposit(user_id: Any, amount: float, *, workspace_id: str = "",
            provider_result: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    key, user, workspace = _account_key(user_id, workspace_id)
    requested = _finite(amount, "Сумма депозита", positive=True, allow_zero=False)
    if requested > 10000:
        raise MicroLiveError("Сумма депозита некорректна.")
    if runtime_env.is_staging():
        provider_id = "staging_" + secrets.token_hex(8)
        settled = requested
        event_type = "deposit_stub"
    else:
        if not runtime_env.allow_real_payments():
            raise MicroLiveError("Реальные платежи отключены до явного разрешения владельца.", 403)
        provider_id, settled = _verified_payment(provider_result, requested)
        event_type = "deposit"
    with _LOCK:
        doc = _load()
        acct = _ensure_locked(doc, key, user, workspace, _DEFAULT_SCALE)
        existing = next(
            (event for event in acct.get("ledger") or []
             if event.get("provider_payment_id") == provider_id),
            None,
        )
        if existing:
            return _public(acct)
        acct["balance"] = round(float(acct.get("balance") or 0) + settled, 4)
        acct["equity"] = acct["balance"]
        # Deposits are cash flows, not trading PnL.
        acct["day_start_equity"] = round(float(acct.get("day_start_equity") or 0) + settled, 4)
        acct.setdefault("ledger", []).append({
            "event_id": "led_" + secrets.token_hex(6),
            "type": event_type,
            "provider_payment_id": provider_id,
            "amount": settled,
            "balance_after": acct["balance"],
            "at_utc": _now_iso(),
        })
        _save(doc)
        return _public(acct)


def _simulate_pnl_full(acct: Dict[str, Any], symbol: str, side: str,
                       notional_full: float) -> float:
    """Deterministic staging outcome; intentionally ignores client PnL."""
    sequence = len(acct.get("trades") or []) + 1
    seed = f"{acct.get('workspace_id')}:{acct.get('user_id')}:{sequence}:{symbol}:{side}:{notional_full:.4f}"
    value = int(hashlib.sha256(seed.encode("utf-8")).hexdigest()[:8], 16)
    basis_points = (value % 401) - 200  # -2.00% .. +2.00%
    return round(notional_full * basis_points / 10000.0, 4)


def _verified_broker_fill(result: Optional[Dict[str, Any]], *, symbol: str,
                          side: str, notional_full: float) -> Tuple[str, float]:
    row = result if isinstance(result, dict) else {}
    if row.get("verified") is not True or str(row.get("status") or "").lower() != "filled":
        raise MicroLiveError("Нет подтверждённого broker fill.", 403)
    broker_id = str(row.get("broker_order_id") or row.get("fill_id") or "").strip()
    if not broker_id:
        raise MicroLiveError("Broker fill не содержит id.", 403)
    if row.get("symbol") and _symbol(row.get("symbol")) != symbol:
        raise MicroLiveError("Инструмент broker fill не совпадает с запросом.", 409)
    if row.get("side") and _side(row.get("side")) != side:
        raise MicroLiveError("Сторона broker fill не совпадает с запросом.", 409)
    confirmed_notional = _finite(
        row.get("notional_full"), "Broker notional", positive=True, allow_zero=False,
    )
    if abs(confirmed_notional - notional_full) > 0.0001:
        raise MicroLiveError("Notional broker fill не совпадает с запросом.", 409)
    pnl_full = _finite(row.get("realized_pnl_full"), "Broker PnL")
    return broker_id, pnl_full


def place_scaled_trade(
    user_id: Any,
    *,
    symbol: str = "MNQ",
    side: str = "buy",
    notional_full: float = 100.0,
    pnl_full: float = 0.0,
    workspace_id: str = "",
    broker_result: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Record one scaled trade from a server simulation or verified broker fill.

    ``pnl_full`` remains in the signature for older callers but is never trusted.
    Staging generates its own result; production requires ``broker_result`` from
    an internal adapter and therefore current public API calls fail closed.
    """
    key, user, workspace = _account_key(user_id, workspace_id)
    symbol_n = _symbol(symbol)
    side_n = _side(side)
    notional_n = _finite(
        notional_full, "Notional", positive=True, allow_zero=False,
    )
    # Validate legacy input so NaN/Infinity cannot leak into logs, but never use it.
    _finite(pnl_full, "Client PnL")
    with _LOCK:
        doc = _load()
        acct = _ensure_locked(doc, key, user, workspace, _DEFAULT_SCALE)
        if not acct.get("warnings_accepted_at_utc"):
            raise MicroLiveError("Примите риск-предупреждение перед первой сделкой.", 403)
        if acct.get("locked"):
            raise MicroLiveError(f"Micro Live заблокирован: {acct.get('lock_reason')}", 403)
        max_notional = float(acct.get("max_notional_full") or _DEFAULT_MAX_NOTIONAL_FULL)
        if notional_n > max_notional:
            raise MicroLiveError(f"Notional превышает лимит ${max_notional:.2f}.", 403)
        scale = max(1, int(acct.get("scale") or _DEFAULT_SCALE))
        notional_micro = round(notional_n / scale, 4)
        free_left = int(acct.get("free_trades_left") or 0)
        used_free = free_left > 0
        if not used_free and float(acct.get("balance") or 0) < notional_micro:
            raise MicroLiveError(
                f"Недостаточно средств: для сделки нужно ${notional_micro:.4f}.", 402,
            )

        if runtime_env.is_staging():
            simulated = True
            broker_id = "staging_" + secrets.token_hex(8)
            verified_pnl_full = _simulate_pnl_full(acct, symbol_n, side_n, notional_n)
        else:
            if not runtime_env.allow_live_orders():
                raise MicroLiveError("Live-ордера отключены до явного разрешения владельца.", 403)
            simulated = False
            broker_id, verified_pnl_full = _verified_broker_fill(
                broker_result, symbol=symbol_n, side=side_n, notional_full=notional_n,
            )
            existing = next(
                (trade for trade in acct.get("trades") or []
                 if trade.get("broker_order_id") == broker_id),
                None,
            )
            if existing:
                return {"ok": True, "trade": existing, **_public(acct)}

        scaled_pnl = round(verified_pnl_full / scale, 4)
        wallet_delta = 0.0 if used_free else scaled_pnl
        projected_equity = round(float(acct.get("equity") or 0) + wallet_delta, 4)
        day_start = float(acct.get("day_start_equity") or 0)
        max_daily_loss = abs(float(acct.get("max_daily_loss") or _DEFAULT_MAX_DAILY_LOSS))
        if projected_equity - day_start <= -max_daily_loss:
            acct["locked"] = True
            acct["lock_reason"] = "daily_loss"
            acct.setdefault("ledger", []).append({
                "event_id": "led_" + secrets.token_hex(6),
                "type": "risk_reject",
                "reason": "daily_loss",
                "notional_full": notional_n,
                "projected_day_pnl": round(projected_equity - day_start, 4),
                "at_utc": _now_iso(),
            })
            _save(doc)
            raise MicroLiveError("Сделка отклонена: превышен дневной лимит убытка.", 403)

        if used_free:
            acct["free_trades_left"] = free_left - 1
        acct["balance"] = round(float(acct.get("balance") or 0) + wallet_delta, 4)
        acct["equity"] = acct["balance"]
        if not used_free:
            if verified_pnl_full < 0:
                acct["consecutive_losses"] = int(acct.get("consecutive_losses") or 0) + 1
            else:
                acct["consecutive_losses"] = 0
        comparison = (
            f"Вы {'заработали' if verified_pnl_full >= 0 else 'потеряли'} "
            f"${abs(scaled_pnl):.4f} ≈ ${abs(verified_pnl_full):.2f} "
            f"на полном объёме при 1:{scale}"
        )
        if used_free:
            comparison += " · FREE: баланс не списывается"
        trade = {
            "trade_id": "ml_" + secrets.token_hex(5),
            "broker_order_id": broker_id,
            "symbol": symbol_n,
            "side": side_n,
            "scale": scale,
            "notional_full": notional_n,
            "notional_micro": notional_micro,
            "pnl_full": verified_pnl_full,
            "pnl_micro": scaled_pnl,
            "wallet_delta": wallet_delta,
            "free_trade": used_free,
            "simulated": simulated,
            "at_utc": _now_iso(),
            "comparison": comparison,
        }
        acct.setdefault("trades", []).append(trade)
        acct.setdefault("ledger", []).append({
            "event_id": "led_" + secrets.token_hex(6),
            "type": "trade_fill_simulated" if simulated else "trade_fill",
            "trade_id": trade["trade_id"],
            "broker_order_id": broker_id,
            "wallet_delta": wallet_delta,
            "balance_after": acct["balance"],
            "at_utc": trade["at_utc"],
        })
        if int(acct.get("consecutive_losses") or 0) >= int(
            acct.get("max_consecutive_losses") or _DEFAULT_MAX_CONSECUTIVE_LOSSES
        ):
            acct["locked"] = True
            acct["lock_reason"] = "circuit_breaker"
        _save(doc)
        return {"ok": True, "trade": trade, **_public(acct)}


def _public(acct: Dict[str, Any]) -> Dict[str, Any]:
    _roll_day(acct)
    scale = int(acct.get("scale") or _DEFAULT_SCALE)
    equity = float(acct.get("equity") or 0)
    day_start = float(acct.get("day_start_equity") or 0)
    gate = availability()
    return {
        "ok": True,
        "mode": "micro_live",
        "badge": (
            acct.get("badge") or f"Реальные деньги · масштаб 1:{scale}"
            if gate["available"]
            else "Micro Live · недоступно до подключения реальных adapters"
        ),
        "account": {
            "workspace_id": acct.get("workspace_id") or "",
            "scale": scale,
            "balance": acct.get("balance"),
            "equity": acct.get("equity"),
            "day_pnl": round(equity - day_start, 4),
            "free_trades_left": acct.get("free_trades_left"),
            "locked": bool(acct.get("locked")),
            "lock_reason": acct.get("lock_reason") or "",
            "warnings_accepted": bool(acct.get("warnings_accepted_at_utc")),
            "max_daily_loss": acct.get("max_daily_loss"),
            "max_notional_full": acct.get("max_notional_full"),
            "consecutive_losses": acct.get("consecutive_losses"),
            "max_consecutive_losses": acct.get("max_consecutive_losses"),
        },
        "trades": list(reversed(acct.get("trades") or []))[:100],
        "ledger": list(reversed(acct.get("ledger") or []))[:100],
        "staging_stub": runtime_env.is_staging(),
        "available": gate["available"],
        "availability": gate,
    }


def availability() -> Dict[str, Any]:
    """Truthful product gate; flags alone do not pretend adapters exist."""
    if runtime_env.is_staging():
        return {
            "available": True,
            "mode": "staging_simulator",
            "real_money": False,
            "payment_adapter": "staging_stub",
            "broker_adapter": "staging_stub",
            "blocking_reasons": [],
            "note": "Staging simulator: ни платежи, ни сделки не выходят во внешние системы.",
        }
    payment_adapter = str(os.environ.get("NTA_MICRO_LIVE_PAYMENT_ADAPTER") or "").strip()
    broker_adapter = str(os.environ.get("NTA_MICRO_LIVE_BROKER_ADAPTER") or "").strip()
    blockers = []
    if not payment_adapter:
        blockers.append("payment_adapter_not_configured")
    if not broker_adapter:
        blockers.append("broker_adapter_not_configured")
    if not runtime_env.allow_real_payments():
        blockers.append("real_payments_disabled")
    if not runtime_env.allow_live_orders():
        blockers.append("live_orders_disabled")
    return {
        "available": not blockers,
        "mode": "live" if not blockers else "coming_soon",
        "real_money": not blockers,
        "payment_adapter": payment_adapter or "",
        "broker_adapter": broker_adapter or "",
        "blocking_reasons": blockers,
        "note": (
            "Live-контур подключён и явно разрешён владельцем."
            if not blockers else
            "Micro Live скрыт за fail-closed gate до подключения и проверки payment/broker adapters."
        ),
    }
