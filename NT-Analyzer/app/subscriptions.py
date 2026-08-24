"""Subscription entitlements and owner-issued promo vouchers.

This module deliberately stays separate from ``account_auth``.  Authentication
answers who the user is; entitlements answer what the user may access after
login.  Payment cards are never stored here: paid checkout providers should keep
card data and send only provider ids / statuses back to this layer.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Tuple

from . import runtime_env, secure_store


_MAGIC = b"STRATFORGE-ENTITLEMENTS-DPAPI-1\n"
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_LOCK = threading.RLock()
# Multiple authenticated endpoint checks resolve the same entitlement document
# during one screen load. Cache only the exact on-disk version and return deep
# copies so callers cannot mutate privilege state without an explicit write.
_DOC_CACHE_KEY: Optional[Tuple[str, int, int]] = None
_DOC_CACHE_DOC: Optional[Dict[str, Any]] = None
ENTITLEMENT_STORE_VERSION = 3
INITIAL_TRIAL_DAYS = 7
TRIAL_PLAN_ID = "trial_full"

# Canonical subscription privilege catalog. Owner edits the plan matrix over
# these ids; each plan enables a subset. Ordered for display.
PLAN_FEATURES: Tuple[Dict[str, str], ...] = (
    {"id": "backtesting",     "label": "Бэктест-движок"},
    {"id": "demo_backtest",   "label": "Демо-бэктест (синтетика)", "hint": "1-click демо без NinjaTrader"},
    {"id": "strategies",      "label": "Портфель стратегий"},
    {"id": "charts_realtime", "label": "Онлайн-графики (реалтайм)", "hint": "Дорогой ресурс рыночных данных"},
    {"id": "ai_lab",          "label": "AI Lab (исследования)"},
    {"id": "ai_pro_models",   "label": "Pro-модели ИИ", "hint": "Дорогие облачные модели"},
    {"id": "news",            "label": "Новости и календарь"},
    {"id": "documents",       "label": "Документы"},
    {"id": "personal_nt",     "label": "Свой NinjaTrader"},
    {"id": "paper_commands",  "label": "Paper/Demo команды"},
    {"id": "practice_trading","label": "Учебная торговля (виртуальные деньги)"},
    {"id": "community",       "label": "Сообщество пользователей"},
    {"id": "live_read",       "label": "Live-чтение счёта"},
    {"id": "live_commands",   "label": "Live-управление"},
)
_ALL_FEATURE_IDS: Tuple[str, ...] = tuple(f["id"] for f in PLAN_FEATURES)

# Automatic/paid subscription checkout is not live yet (no business payment
# account). While False, the UI shows paid plans as "Coming Soon". Promo codes
# and owner-granted access stay fully functional regardless of this flag.
PAYMENTS_ENABLED = False


def _feat(*enabled: str) -> Dict[str, bool]:
    return {fid: (fid in enabled) for fid in _ALL_FEATURE_IDS}


def _feat_all() -> Dict[str, bool]:
    return {fid: True for fid in _ALL_FEATURE_IDS}


PLANS: Dict[str, Dict[str, Any]] = {
    # Owner golden-star tier — set once, never sold.
    "founder": {
        "label": "Founder", "badge": "★ Основатель", "category": "owner", "tier": "founder",
        "price_usd": 0.0, "period": "навсегда", "public": False,
        "tagline": "Полный доступ владельца — устанавливается один раз",
        "features": _feat_all(),
        "limits": {"max_backtests_per_day": 1000000, "max_charts": 1000},
    },
    # One automatic, non-renewing trial per canonical human account.  It is an
    # internal access grant rather than a sellable plan; repeated logins and
    # additional linked identities must never mint another seven-day window.
    TRIAL_PLAN_ID: {
        "label": "Полный пробный доступ", "badge": "7 дней", "category": "trial", "tier": "trial",
        "price_usd": 0.0, "period": "7 дней", "public": False,
        "tagline": "Полный доступ к возможностям StratForge на пробный период",
        "features": _feat_all(),
        "limits": {"max_backtests_per_day": 1000, "max_charts": 32},
    },
    # Authenticated account baseline after the full trial expires.  The account
    # and provider-setup surfaces remain available, while shared live market data
    # is decided separately by the market-source entitlement resolver.
    "authenticated_basic": {
        "label": "Базовый доступ аккаунта", "badge": "Аккаунт", "category": "baseline", "tier": "baseline",
        "price_usd": 0.0, "period": "без срока", "public": False,
        "tagline": "Профиль, документы, практика и подключение собственного market-data источника",
        "features": _feat("demo_backtest", "news", "documents", "personal_nt", "practice_trading", "community"),
        "limits": {"max_backtests_per_day": 0, "max_demo_backtests_per_day": 3, "max_charts": 2},
    },
    # Legacy only. New authorization must never fall back to this blurred
    # unauthenticated preview contour.
    "free_preview": {
        "label": "Free Preview", "badge": "Демо", "category": "free", "tier": "free",
        "price_usd": 0.0, "period": "ознакомление", "public": False,
        "tagline": "Устаревший preview-контур; новые аккаунты не используют",
        "deprecated": True, "replacement_plan_id": "authenticated_basic",
        "features": _feat("news", "documents", "demo_backtest", "practice_trading", "community"),
        "limits": {"max_backtests_per_day": 0, "max_demo_backtests_per_day": 3, "max_charts": 2},
    },
    # Donations "для своих" — symbolic support, generous access.
    "donate_1": {
        "label": "Символ ★", "badge": "Донат $1", "category": "donation", "tier": "donation",
        "price_usd": 1.0, "period": "разовый донат", "public": True,
        "tagline": "Символическая поддержка — для своих",
        "features": _feat("backtesting", "strategies", "news", "documents", "personal_nt", "paper_commands", "ai_lab"),
        "limits": {"max_backtests_per_day": 50, "max_charts": 4},
    },
    "donate_3": {
        "label": "Друг ★★", "badge": "Донат $3", "category": "donation", "tier": "donation",
        "price_usd": 3.0, "period": "разовый донат", "public": True,
        "tagline": "Поддержка проекта — для своих",
        "features": _feat("backtesting", "strategies", "news", "documents", "personal_nt", "paper_commands", "ai_lab", "charts_realtime", "live_read"),
        "limits": {"max_backtests_per_day": 150, "max_charts": 8},
    },
    "donate_5": {
        "label": "Патрон ★★★", "badge": "Донат $5", "category": "donation", "tier": "donation",
        "price_usd": 5.0, "period": "разовый донат", "public": True,
        "tagline": "Максимальная благодарность — для своих",
        "features": _feat_all(),
        "limits": {"max_backtests_per_day": 500, "max_charts": 16},
    },
    # Regular subscriptions.
    "basic": {
        "label": "Базовый", "badge": "", "category": "subscription", "tier": "basic",
        "price_usd": 4.99, "period": "мес", "public": True,
        "tagline": "Половина возможностей: анализ без реалтайма и ИИ",
        "features": _feat("backtesting", "strategies", "news", "documents"),
        "limits": {"max_backtests_per_day": 30, "max_charts": 2},
    },
    "standard": {
        "label": "Стандарт", "badge": "Популярный", "category": "subscription", "tier": "standard",
        "price_usd": 9.99, "period": "мес", "public": True,
        "tagline": "Стандартный набор: реалтайм, ИИ и свой NinjaTrader",
        "features": _feat("backtesting", "strategies", "news", "documents", "ai_lab", "personal_nt", "paper_commands", "charts_realtime", "live_read"),
        "limits": {"max_backtests_per_day": 100, "max_charts": 6},
    },
    "pro": {
        "label": "Pro", "badge": "Pro-модели", "category": "subscription", "tier": "pro",
        "price_usd": 25.0, "period": "мес", "public": True,
        "tagline": "Всё включено + Pro-модели ИИ и Live-управление",
        "features": _feat_all(),
        "limits": {"max_backtests_per_day": 1000, "max_charts": 32},
    },
    # Internal / legacy plans (not shown publicly; used for dev grants & tests).
    "developer_free": {
        "label": "Developer Free", "category": "internal", "tier": "dev",
        "price_usd": 0.0, "period": "", "public": False, "tagline": "Бесплатный доступ для разработчиков",
        "features": _feat("backtesting", "strategies", "ai_lab", "personal_nt", "paper_commands", "charts_realtime", "news", "documents"),
        "limits": {"max_backtests_per_day": 250, "max_charts": 16},
    },
    "learner_viewer": {
        "label": "Наблюдатель", "category": "internal", "tier": "viewer",
        "price_usd": 0.0, "period": "", "public": False, "tagline": "Только наблюдение",
        "features": _feat("news"),
        "limits": {"max_backtests_per_day": 0, "max_charts": 1},
    },
    "personal_basic": {
        "label": "Personal Basic", "category": "internal", "tier": "basic",
        "price_usd": 4.99, "period": "мес", "public": False, "tagline": "",
        "features": _feat("backtesting", "strategies", "ai_lab", "personal_nt", "paper_commands", "live_read"),
        "limits": {"max_backtests_per_day": 50, "max_charts": 4},
    },
    "personal_pro": {
        "label": "Personal Pro", "category": "internal", "tier": "pro",
        "price_usd": 25.0, "period": "мес", "public": False, "tagline": "",
        "features": _feat_all(),
        "limits": {"max_backtests_per_day": 500, "max_charts": 32},
    },
}


class SubscriptionError(RuntimeError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = int(status)


def _root() -> Path:
    return _PROJECT_ROOT


def _store_path() -> Path:
    return runtime_env.data_path("integrations", "entitlements.dpapi", project_root=_root())


def _doc_cache_key(path: Path) -> Optional[Tuple[str, int, int]]:
    try:
        stat = path.stat()
    except OSError:
        return None
    identity = path if path.is_absolute() else path.resolve()
    return (str(identity), int(stat.st_mtime_ns), int(stat.st_size))


def _clear_doc_cache() -> None:
    global _DOC_CACHE_KEY, _DOC_CACHE_DOC
    with _LOCK:
        _DOC_CACHE_KEY = None
        _DOC_CACHE_DOC = None


def _cache_doc(path: Path, doc: Dict[str, Any]) -> None:
    global _DOC_CACHE_KEY, _DOC_CACHE_DOC
    key = _doc_cache_key(path)
    if key is None:
        _clear_doc_cache()
        return
    with _LOCK:
        _DOC_CACHE_KEY = key
        _DOC_CACHE_DOC = copy.deepcopy(doc)


def _audit_path() -> Path:
    return runtime_env.data_path("audit", "subscriptions.jsonl", project_root=_root())


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _default_doc() -> Dict[str, Any]:
    return {
        "version": ENTITLEMENT_STORE_VERSION,
        "vouchers": [],
        "entitlements": [],
        "plan_overrides": {},
        "payment_config": {},
        "paypal": {},
        "payment_requests": [],
        "access_history": [],
        "identity_schema": {"stage": "dual_write", "canonical_key": "user_uuid"},
    }


def _user_uuid_for_legacy_id(user_id: Any) -> str:
    try:
        from . import account_auth
        return account_auth.user_uuid_for_legacy_id(user_id)
    except Exception:
        return ""


def _backfill_user_uuid(row: Dict[str, Any], legacy_key: str, uuid_key: str) -> bool:
    user_uuid = _user_uuid_for_legacy_id(row.get(legacy_key))
    if not user_uuid or row.get(uuid_key) == user_uuid:
        return False
    row[uuid_key] = user_uuid
    return True


def _resolved_user_uuids(values: Iterable[Any]) -> list[str]:
    resolved: list[str] = []
    for value in values:
        user_uuid = _user_uuid_for_legacy_id(value)
        if user_uuid and user_uuid not in resolved:
            resolved.append(user_uuid)
    return resolved


def _migrate_doc(doc: Dict[str, Any]) -> tuple[Dict[str, Any], bool]:
    changed = False
    for key in ("vouchers", "entitlements", "payment_requests", "access_history"):
        if not isinstance(doc.get(key), list):
            doc[key] = []
            changed = True
    for key in ("plan_overrides", "payment_config", "paypal"):
        if not isinstance(doc.get(key), dict):
            doc[key] = {}
            changed = True
    for row in doc["entitlements"]:
        if isinstance(row, dict):
            changed = _backfill_user_uuid(row, "user_id", "user_uuid") or changed
    for row in doc["vouchers"]:
        if not isinstance(row, dict):
            continue
        changed = _backfill_user_uuid(row, "created_by_user_id", "created_by_user_uuid") or changed
        existing_allowed = [str(value) for value in row.get("allowed_user_uuids") or [] if str(value)]
        resolved_allowed = _resolved_user_uuids(row.get("allowed_telegram_ids") or [])
        allowed_uuids = list(dict.fromkeys([*existing_allowed, *resolved_allowed]))
        if allowed_uuids != existing_allowed:
            row["allowed_user_uuids"] = allowed_uuids
            changed = True
        for redemption in row.get("redemptions") or []:
            if isinstance(redemption, dict):
                changed = _backfill_user_uuid(redemption, "user_id", "user_uuid") or changed
    for row in doc["payment_requests"]:
        if isinstance(row, dict):
            changed = _backfill_user_uuid(row, "user_id", "user_uuid") or changed
            changed = _backfill_user_uuid(row, "resolver_user_id", "resolver_user_uuid") or changed
    for row in doc["access_history"]:
        if isinstance(row, dict):
            changed = _backfill_user_uuid(row, "user_id", "user_uuid") or changed
            changed = _backfill_user_uuid(row, "actor_user_id", "actor_user_uuid") or changed
    identity_schema = doc.get("identity_schema") if isinstance(doc.get("identity_schema"), dict) else {}
    expected_schema = dict(identity_schema)
    expected_schema.update({
        "stage": "dual_write",
        "canonical_key": "user_uuid",
        "legacy_key": "user_id",
    })
    if expected_schema != identity_schema:
        expected_schema.setdefault("migrated_at_utc", _now_iso())
        doc["identity_schema"] = expected_schema
        changed = True
    try:
        version = int(doc.get("version") or 1)
    except (TypeError, ValueError):
        version = 1
    if version < ENTITLEMENT_STORE_VERSION:
        doc["version"] = ENTITLEMENT_STORE_VERSION
        changed = True
    return doc, changed


def _read_doc() -> Dict[str, Any]:
    if runtime_env.is_production() and runtime_env.environment_explicit():
        from . import storage_router
        from .production_storage import StorageError
        try:
            doc = storage_router.read_document("entitlements", _default_doc())
        except StorageError as exc:
            raise SubscriptionError(
                f"Production entitlement repository unavailable ({exc.code}).", 503,
            ) from None
        if not isinstance(doc, dict):
            raise SubscriptionError("Production entitlement repository returned invalid data.", 500)
        for key in ("vouchers", "entitlements", "access_history"):
            if not isinstance(doc.get(key), list):
                doc[key] = []
        if not isinstance(doc.get("plan_overrides"), dict):
            doc["plan_overrides"] = {}
        if not isinstance(doc.get("payment_config"), dict):
            doc["payment_config"] = {}
        if not isinstance(doc.get("paypal"), dict):
            doc["paypal"] = {}
        if not isinstance(doc.get("payment_requests"), list):
            doc["payment_requests"] = []
        return _migrate_doc(doc)[0]
    path = _store_path()
    cache_key = _doc_cache_key(path)
    if cache_key is None:
        _clear_doc_cache()
        return _default_doc()
    with _LOCK:
        if _DOC_CACHE_KEY == cache_key and _DOC_CACHE_DOC is not None:
            cached, changed = _migrate_doc(copy.deepcopy(_DOC_CACHE_DOC))
            if changed:
                _write_doc(cached)
            return cached
    try:
        raw = path.read_bytes()
        if not raw.startswith(_MAGIC):
            raise SubscriptionError("Неизвестный формат хранилища подписок.", 500)
        encrypted = base64.b64decode(raw[len(_MAGIC):], validate=True)
        doc = json.loads(secure_store._unprotect(encrypted).decode("utf-8"))
    except SubscriptionError:
        raise
    except secure_store.SecureStoreError as exc:
        raise SubscriptionError(str(exc), 503) from None
    except Exception as exc:
        raise SubscriptionError(f"Не удалось прочитать подписки: {exc}", 500) from None
    if not isinstance(doc, dict):
        raise SubscriptionError("Хранилище подписок повреждено.", 500)
    for key in ("vouchers", "entitlements", "access_history"):
        if not isinstance(doc.get(key), list):
            doc[key] = []
    if not isinstance(doc.get("plan_overrides"), dict):
        doc["plan_overrides"] = {}
    if not isinstance(doc.get("payment_config"), dict):
        doc["payment_config"] = {}
    if not isinstance(doc.get("paypal"), dict):
        doc["paypal"] = {}
    if not isinstance(doc.get("payment_requests"), list):
        doc["payment_requests"] = []
    doc, changed = _migrate_doc(doc)
    if changed:
        _write_doc(doc)
        return doc
    _cache_doc(path, doc)
    return doc


def _read_doc_reference() -> Dict[str, Any]:
    """Return an internal read-only cache view while the caller holds _LOCK."""
    global _DOC_CACHE_KEY, _DOC_CACHE_DOC
    if runtime_env.is_production() and runtime_env.environment_explicit():
        return _read_doc()
    path = _store_path()
    key = _doc_cache_key(path)
    with _LOCK:
        if key is None:
            absent_key = (str(path), 0, 0)
            if _DOC_CACHE_KEY == absent_key and _DOC_CACHE_DOC is not None:
                return _DOC_CACHE_DOC
            _DOC_CACHE_KEY = absent_key
            _DOC_CACHE_DOC = _default_doc()
            return _DOC_CACHE_DOC
        if key is not None and _DOC_CACHE_KEY == key and _DOC_CACHE_DOC is not None:
            return _DOC_CACHE_DOC
        loaded = _read_doc()
        if key is not None and _DOC_CACHE_KEY == _doc_cache_key(path) and _DOC_CACHE_DOC is not None:
            return _DOC_CACHE_DOC
        return loaded


def _write_doc(doc: Dict[str, Any]) -> None:
    doc, _ = _migrate_doc(doc)
    if runtime_env.is_production() and runtime_env.environment_explicit():
        from . import storage_router
        from .production_storage import StorageError
        try:
            storage_router.write_document("entitlements", doc)
            _clear_doc_cache()
            return
        except StorageError as exc:
            raise SubscriptionError(
                f"Production entitlement repository write denied ({exc.code}).", 503,
            ) from None
    if not secure_store.available():
        raise SubscriptionError("Windows DPAPI недоступен; подписки не могут быть сохранены.", 503)
    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    plaintext = json.dumps(doc, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    try:
        payload = _MAGIC + base64.b64encode(secure_store._protect(plaintext))
    except secure_store.SecureStoreError as exc:
        raise SubscriptionError(str(exc), 503) from None
    # A production backend, worker and maintenance/test process can all touch
    # the encrypted store. Use a writer-unique temp file and retry Windows
    # sharing violations during the final atomic replace.
    tmp = path.with_suffix(path.suffix + f".{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_bytes(payload)
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        last_error: Optional[OSError] = None
        for attempt in range(8):
            try:
                os.replace(tmp, path)
                last_error = None
                break
            except PermissionError as exc:
                last_error = exc
                time.sleep(0.02 * (attempt + 1))
        if last_error is not None:
            raise last_error
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        _cache_doc(path, doc)
    except OSError as exc:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise SubscriptionError(f"Не удалось сохранить подписки: {exc}", 500) from None


def storage_status() -> Dict[str, Any]:
    if runtime_env.is_production() and runtime_env.environment_explicit():
        from . import storage_router
        return storage_router.storage_status()
    return {
        "available": secure_store.available(),
        "backend": secure_store.backend_name(),
        "encrypted": _store_path().is_file(),
    }


def _effective_plan(plan_id: str, overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    base = PLANS.get(plan_id)
    if not base:
        return {}
    plan = dict(base)
    src = dict(base.get("features") or {})
    feats = {fid: bool(src.get(fid, False)) for fid in _ALL_FEATURE_IDS}
    plan_ov = (overrides or {}).get(plan_id) if isinstance(overrides, dict) else None
    if isinstance(plan_ov, dict):
        for fid, value in plan_ov.items():
            if fid in feats:
                feats[fid] = bool(value)
    plan["features"] = feats
    plan["plan_id"] = plan_id
    return plan


def list_plans() -> Dict[str, Any]:
    with _LOCK:
        overrides = _read_doc_reference().get("plan_overrides") or {}
    plans = [_effective_plan(pid, overrides) for pid in PLANS]
    return {
        "plans": plans,
        "public_plans": [p for p in plans if p.get("public")],
        "feature_catalog": [dict(f) for f in PLAN_FEATURES],
    }


def effective_plan(plan_id: str) -> Dict[str, Any]:
    """Public: the plan with owner per-plan overrides applied (or {} if unknown)."""
    with _LOCK:
        overrides = _read_doc_reference().get("plan_overrides") or {}
    return _effective_plan(str(plan_id or ""), overrides)


def plan_matrix(actor_user_id: Any) -> Dict[str, Any]:
    try:
        actor = int(actor_user_id or 0)
    except (TypeError, ValueError):
        actor = 0
    if actor <= 0:
        raise SubscriptionError("Owner identity обязательна.", 403)
    return list_plans()


def set_plan_feature(actor_user_id: Any, plan_id: str, feature: str, enabled: bool) -> Dict[str, Any]:
    try:
        actor = int(actor_user_id or 0)
    except (TypeError, ValueError):
        actor = 0
    if actor <= 0:
        raise SubscriptionError("Owner identity обязательна.", 403)
    pid = str(plan_id or "")
    if pid not in PLANS:
        raise SubscriptionError("Неизвестный тарифный план.")
    if pid in {"founder", TRIAL_PLAN_ID}:
        raise SubscriptionError("Системный план изменять нельзя.", 400)
    if feature not in _ALL_FEATURE_IDS:
        raise SubscriptionError("Неизвестная привилегия.")
    with _LOCK:
        doc = _read_doc()
        overrides = doc.get("plan_overrides") or {}
        plan_ov = overrides.get(pid) if isinstance(overrides.get(pid), dict) else {}
        plan_ov[feature] = bool(enabled)
        overrides[pid] = plan_ov
        doc["plan_overrides"] = overrides
        _write_doc(doc)
    _audit("plan_feature_changed", owner_id=actor, plan_id=pid, feature=feature, enabled=bool(enabled))
    return list_plans()


def _mask_tail(value: str, keep: int = 4) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return ("•••• " + text[-keep:]) if len(text) > keep else text


def _public_payment(config: Dict[str, Any]) -> Dict[str, Any]:
    config = config or {}
    return {
        "enabled": bool(config.get("enabled")),
        "paypal_me": str(config.get("paypal_me") or ""),
        "card_url": str(config.get("card_url") or ""),
        "card_note": str(config.get("card_note") or ""),
        "crypto_note": str(config.get("crypto_note") or ""),
        "updated_at_utc": str(config.get("updated_at_utc") or ""),
    }


def get_payment_config(actor_user_id: Any) -> Dict[str, Any]:
    try:
        actor = int(actor_user_id or 0)
    except (TypeError, ValueError):
        actor = 0
    if actor <= 0:
        raise SubscriptionError("Owner identity обязательна.", 403)
    with _LOCK:
        config = _read_doc().get("payment_config") or {}
    return {"payment": _public_payment(config), "storage": storage_status()}


def set_payment_config(actor_user_id: Any, body: Dict[str, Any]) -> Dict[str, Any]:
    try:
        actor = int(actor_user_id or 0)
    except (TypeError, ValueError):
        actor = 0
    if actor <= 0:
        raise SubscriptionError("Owner identity обязательна.", 403)
    paypal = re.sub(r"[^A-Za-z0-9_.\-]", "", str(body.get("paypal_me") or "").strip().lstrip("@"))[:64]
    card_url = str(body.get("card_url") or "").strip()[:400]
    if card_url and not re.match(r"^https://", card_url, re.IGNORECASE):
        raise SubscriptionError("Ссылка для оплаты должна быть HTTPS.")
    config = {
        "enabled": bool(body.get("enabled", True)),
        "paypal_me": paypal,
        "card_url": card_url,
        "card_note": str(body.get("card_note") or "").strip()[:400],
        "crypto_note": str(body.get("crypto_note") or "").strip()[:400],
        "updated_at_utc": _now_iso(),
    }
    with _LOCK:
        doc = _read_doc()
        doc["payment_config"] = config
        _write_doc(doc)
    _audit("payment_config_updated", owner_id=actor)
    return {"payment": _public_payment(config), "storage": storage_status()}


def payments_active() -> bool:
    """Whether paid plan / donation buttons should be shown to users.

    Driven by the owner's payment settings so the flag is toggled from the
    cabinet without editing code: payments go live when the owner enabled the
    payment panel *and* provided at least one payment target (PayPal.me handle
    or a ready payment link). The module-level ``PAYMENTS_ENABLED`` still forces
    it on for tests / emergency overrides.
    """
    if PAYMENTS_ENABLED:
        return True
    with _LOCK:
        config = _read_doc_reference().get("payment_config") or {}
    if not config.get("enabled"):
        return False
    return bool(str(config.get("paypal_me") or "").strip()
                or str(config.get("card_url") or "").strip())


def _paypal_link(handle: str, amount: float) -> str:
    handle = re.sub(r"[^A-Za-z0-9_.\-]", "", str(handle or "").lstrip("@"))
    if not handle:
        return ""
    if amount and amount > 0:
        return f"https://www.paypal.com/paypalme/{handle}/{amount:g}"
    return f"https://www.paypal.com/paypalme/{handle}"


def donation_options() -> Dict[str, Any]:
    with _LOCK:
        doc = _read_doc()
        overrides = doc.get("plan_overrides") or {}
        config = doc.get("payment_config") or {}
    payment = _public_payment(config)
    tiers = []
    for pid, plan in PLANS.items():
        if plan.get("category") != "donation":
            continue
        eff = _effective_plan(pid, overrides)
        amount = float(plan.get("price_usd") or 0)
        tiers.append({
            "plan_id": pid,
            "label": eff.get("label"),
            "badge": eff.get("badge"),
            "tagline": eff.get("tagline"),
            "price_usd": amount,
            "paypal_url": _paypal_link(payment.get("paypal_me"), amount) if payment.get("paypal_me") else "",
            "features": eff.get("features"),
        })
    tiers.sort(key=lambda row: float(row.get("price_usd") or 0))
    return {"tiers": tiers, "payment": payment, "paypal_generic": _paypal_link(payment.get("paypal_me"), 0) if payment.get("paypal_me") else ""}


def owner_entitlement() -> Dict[str, Any]:
    with _LOCK:
        overrides = _read_doc_reference().get("plan_overrides") or {}
    return {
        "entitlement_id": "founder", "user_id": None, "workspace_id": "",
        "plan_id": "founder", "plan": _effective_plan("founder", overrides),
        "status": "founder", "source": "owner", "source_voucher_id": "",
        "starts_at_utc": "", "expires_at_utc": "", "created_at_utc": "",
    }


# ---------------------------------------------------------------------------
# PayPal Subscriptions configuration + paid entitlement activation.
# The owner's PayPal API credentials live inside the DPAPI-encrypted doc; the
# secret is never exposed through the API. No payer card data is ever stored.
# ---------------------------------------------------------------------------

_PAYPAL_PLAN_IDS = ("basic", "standard", "pro")


def paypal_config_raw() -> Dict[str, Any]:
    with _LOCK:
        cfg = dict(_read_doc().get("paypal") or {})
    cfg.setdefault("mode", "sandbox")
    cfg.setdefault("plans", {})
    return cfg


def _public_paypal(cfg: Dict[str, Any]) -> Dict[str, Any]:
    cfg = cfg or {}
    return {
        "enabled": bool(cfg.get("enabled")),
        "mode": str(cfg.get("mode") or "sandbox"),
        "client_id": str(cfg.get("client_id") or ""),
        "secret_set": bool(cfg.get("secret")),
        "webhook_id": str(cfg.get("webhook_id") or ""),
        "product_id": str(cfg.get("product_id") or ""),
        "plans": {pid: str((cfg.get("plans") or {}).get(pid) or "") for pid in _PAYPAL_PLAN_IDS},
        "updated_at_utc": str(cfg.get("updated_at_utc") or ""),
    }


def get_paypal_config(actor_user_id: Any) -> Dict[str, Any]:
    try:
        actor = int(actor_user_id or 0)
    except (TypeError, ValueError):
        actor = 0
    if actor <= 0:
        raise SubscriptionError("Owner identity обязательна.", 403)
    return {"paypal": _public_paypal(paypal_config_raw()), "storage": storage_status()}


def set_paypal_config(actor_user_id: Any, body: Dict[str, Any]) -> Dict[str, Any]:
    try:
        actor = int(actor_user_id or 0)
    except (TypeError, ValueError):
        actor = 0
    if actor <= 0:
        raise SubscriptionError("Owner identity обязательна.", 403)
    mode = str(body.get("mode") or "sandbox").strip().lower()
    if mode not in ("sandbox", "live"):
        raise SubscriptionError("PayPal mode: sandbox или live.")
    with _LOCK:
        doc = _read_doc()
        cfg = dict(doc.get("paypal") or {})
        cfg["mode"] = mode
        cfg["enabled"] = bool(body.get("enabled", cfg.get("enabled", False)))
        cfg["client_id"] = str(body.get("client_id") or cfg.get("client_id") or "").strip()[:200]
        secret = str(body.get("secret") or "").strip()
        if secret:
            cfg["secret"] = secret[:200]
        elif body.get("clear_secret"):
            cfg["secret"] = ""
        cfg["webhook_id"] = str(body.get("webhook_id") or cfg.get("webhook_id") or "").strip()[:120]
        if isinstance(body.get("plans"), dict):
            plans = dict(cfg.get("plans") or {})
            for pid in _PAYPAL_PLAN_IDS:
                value = body["plans"].get(pid)
                if value is not None:
                    plans[pid] = str(value or "").strip()[:120]
            cfg["plans"] = plans
        cfg.setdefault("plans", {})
        cfg["updated_at_utc"] = _now_iso()
        doc["paypal"] = cfg
        _write_doc(doc)
    _audit("paypal_config_updated", owner_id=actor, mode=mode)
    return {"paypal": _public_paypal(cfg), "storage": storage_status()}


def set_paypal_plans(actor_user_id: Any, product_id: str, plans: Dict[str, str]) -> Dict[str, Any]:
    try:
        actor = int(actor_user_id or 0)
    except (TypeError, ValueError):
        actor = 0
    if actor <= 0:
        raise SubscriptionError("Owner identity обязательна.", 403)
    with _LOCK:
        doc = _read_doc()
        cfg = dict(doc.get("paypal") or {})
        if product_id:
            cfg["product_id"] = str(product_id)[:120]
        merged = dict(cfg.get("plans") or {})
        for pid in _PAYPAL_PLAN_IDS:
            if plans.get(pid):
                merged[pid] = str(plans[pid])[:120]
        cfg["plans"] = merged
        cfg["updated_at_utc"] = _now_iso()
        doc["paypal"] = cfg
        _write_doc(doc)
    _audit("paypal_plans_saved", owner_id=actor)
    return {"paypal": _public_paypal(cfg), "storage": storage_status()}


def activate_paid(user_id: Any, plan_id: Any, *, provider: str = "paypal",
                  provider_subscription_id: str = "", status: str = "active") -> Dict[str, Any]:
    try:
        uid = int(user_id or 0)
    except (TypeError, ValueError):
        uid = 0
    if uid <= 0:
        raise SubscriptionError("Пользователь обязателен.", 400)
    pid = _clean_plan(plan_id, required=True)
    sub_id = str(provider_subscription_id or "")
    with _LOCK:
        doc = _read_doc()
        overrides = doc.get("plan_overrides") or {}
        ent = None
        if sub_id:
            ent = next((row for row in doc["entitlements"] if str(row.get("provider_subscription_id") or "") == sub_id), None)
        if ent is None:
            ent = next((row for row in doc["entitlements"]
                        if int(row.get("user_id") or 0) == uid and str(row.get("plan_id")) == pid
                        and str(row.get("source")) == provider and str(row.get("status")) in ("active", "promo_grant")), None)
        if ent is None:
            ent = {
                "entitlement_id": "ent_" + secrets.token_urlsafe(12),
                "user_id": uid, "workspace_id": "", "plan_id": pid,
                "status": status, "source": provider, "provider": provider,
                "provider_subscription_id": sub_id, "source_voucher_id": "",
                "starts_at_utc": _now_iso(), "expires_at_utc": "", "created_at_utc": _now_iso(),
            }
            doc["entitlements"].append(ent)
        else:
            ent.update({
                "user_id": uid, "plan_id": pid, "status": status, "source": provider, "provider": provider,
                "provider_subscription_id": sub_id or str(ent.get("provider_subscription_id") or ""),
                "updated_at_utc": _now_iso(),
            })
        _write_doc(doc)
        snapshot = dict(ent)
    _audit("paid_activated", user_id=uid, plan_id=pid, provider=provider, provider_subscription_id=sub_id)
    return {"ok": True, "entitlement": _public_entitlement(snapshot, overrides)}


def cancel_paid(*, provider_subscription_id: str, status: str = "cancelled") -> Dict[str, Any]:
    sub_id = str(provider_subscription_id or "")
    if not sub_id:
        return {"ok": False, "reason": "no_subscription_id"}
    with _LOCK:
        doc = _read_doc()
        changed = False
        for row in doc["entitlements"]:
            if str(row.get("provider_subscription_id") or "") == sub_id:
                row["status"] = status
                row["updated_at_utc"] = _now_iso()
                changed = True
        if changed:
            _write_doc(doc)
    _audit("paid_cancelled", provider_subscription_id=sub_id, status=status)
    return {"ok": changed}


# ---------------------------------------------------------------------------
# Manual PayPal flow (MVP): one-off PayPal.me / payment-link payments, owner
# verifies in PayPal and grants the tier. No PayPal Business / webhooks needed.
# ---------------------------------------------------------------------------

_ACTIVE_STATUSES = {"active", "promo_grant", "manual", "founder"}


def _is_expired(expires_at_utc: Any) -> bool:
    text = str(expires_at_utc or "").strip()
    if not text:
        return False
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")) <= datetime.now(timezone.utc)
    except ValueError:
        return True


def _entitlement_active(row: Dict[str, Any]) -> bool:
    return str(row.get("status")) in _ACTIVE_STATUSES and not _is_expired(row.get("expires_at_utc"))


def manual_checkout(user_id: Any, plan_id: Any) -> Dict[str, Any]:
    pid = _clean_plan(plan_id, required=True)
    plan = _effective_plan(pid)
    amount = float(plan.get("price_usd") or 0)
    with _LOCK:
        config = _read_doc().get("payment_config") or {}
    payment = _public_payment(config)
    paypal_url = _paypal_link(payment.get("paypal_me"), amount) if payment.get("paypal_me") else ""
    return {
        "ok": True,
        "plan_id": pid,
        "label": plan.get("label"),
        "amount_usd": amount,
        "currency": "USD",
        "paypal_url": paypal_url,
        "card_url": payment.get("card_url") or "",
        "card_note": payment.get("card_note") or "",
        "instructions": (
            "1. Оплатите указанную сумму через PayPal.\n"
            "2. Нажмите «Я оплатил» — заявка уйдёт владельцу.\n"
            "3. Владелец проверит платёж в PayPal и включит тариф."
        ),
    }


def _canonical_user_uuid(user_id: int, supplied: Any = "") -> str:
    raw = str(supplied or "").strip()
    if raw:
        try:
            return str(uuid.UUID(raw))
        except (ValueError, AttributeError, TypeError):
            raise SubscriptionError("Canonical user UUID некорректен.", 400) from None
    return _user_uuid_for_legacy_id(user_id)


def _trial_row(doc: Dict[str, Any], *, user_id: int, user_uuid: str = "") -> Optional[Dict[str, Any]]:
    """Return the account's one canonical initial-trial row, regardless of state."""
    canonical = str(user_uuid or "")
    matches = []
    for row in doc.get("entitlements") or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("plan_id") or "") != TRIAL_PLAN_ID and str(row.get("access_kind") or "") != "initial_trial":
            continue
        same_user = int(row.get("user_id") or 0) == user_id
        same_uuid = bool(canonical) and str(row.get("user_uuid") or "") == canonical
        if same_user or same_uuid:
            matches.append(row)
    if not matches:
        return None
    matches.sort(key=lambda row: str(row.get("created_at_utc") or ""))
    return matches[0]


def _access_state(row: Dict[str, Any]) -> str:
    status = str(row.get("status") or "")
    if status in _ACTIVE_STATUSES:
        return "expired" if _is_expired(row.get("expires_at_utc")) else "active"
    return status or "unknown"


def _public_access_history(row: Dict[str, Any]) -> Dict[str, Any]:
    return {key: row.get(key) for key in (
        "history_id", "event", "user_id", "user_uuid", "entitlement_id",
        "actor_user_id", "actor_user_uuid", "source", "reason",
        "idempotency_key", "at_utc", "before", "after",
    )}


def _trial_access_payload(
    doc: Dict[str, Any], row: Optional[Dict[str, Any]], *, user_id: int,
    user_uuid: str = "", include_history: bool = True,
) -> Dict[str, Any]:
    history_with_order = []
    if include_history:
        for index, event in enumerate(doc.get("access_history") or []):
            if not isinstance(event, dict):
                continue
            same_user = int(event.get("user_id") or 0) == user_id
            same_uuid = bool(user_uuid) and str(event.get("user_uuid") or "") == user_uuid
            if same_user or same_uuid:
                history_with_order.append((index, _public_access_history(event)))
        history_with_order.sort(
            key=lambda item: (str(item[1].get("at_utc") or ""), item[0]),
            reverse=True,
        )
    history = [event for _index, event in history_with_order]
    if row is None:
        return {
            "kind": "initial_trial", "state": "not_granted", "plan_id": TRIAL_PLAN_ID,
            "starts_at_utc": "", "expires_at_utc": "", "history": history,
        }
    return {
        "kind": "initial_trial",
        "state": _access_state(row),
        "plan_id": TRIAL_PLAN_ID,
        "entitlement_id": str(row.get("entitlement_id") or ""),
        "starts_at_utc": str(row.get("starts_at_utc") or ""),
        "expires_at_utc": str(row.get("expires_at_utc") or ""),
        "created_at_utc": str(row.get("created_at_utc") or ""),
        "updated_at_utc": str(row.get("updated_at_utc") or ""),
        "history": history,
    }


def trial_access_for_user(user_id: Any, *, include_history: bool = True) -> Dict[str, Any]:
    """Return the canonical trial state without changing or renewing it."""
    try:
        uid = int(user_id or 0)
    except (TypeError, ValueError):
        uid = 0
    if uid <= 0:
        raise SubscriptionError("Пользователь обязателен.", 400)
    canonical = _canonical_user_uuid(uid)
    with _LOCK:
        doc = _read_doc_reference()
        row = _trial_row(doc, user_id=uid, user_uuid=canonical)
        return _trial_access_payload(
            doc, row, user_id=uid, user_uuid=canonical,
            include_history=include_history,
        )


def ensure_initial_trial(
    user_id: Any, *, user_uuid: Any = "", source: str = "verified_registration",
    duration_days: Any = INITIAL_TRIAL_DAYS,
) -> Dict[str, Any]:
    """Mint the one non-renewing full trial for a verified human account.

    Idempotency is keyed by the canonical account (UUID when available, legacy
    id during migration).  A repeated login or a newly-linked identity returns
    the original row and never moves its expiry.  If a paid/owner grant already
    exists, the trial clock is still recorded from registration time but marked
    superseded so it cannot unexpectedly start after that grant expires.
    """
    try:
        uid = int(user_id or 0)
    except (TypeError, ValueError):
        uid = 0
    if uid <= 0:
        raise SubscriptionError("Пользователь обязателен.", 400)
    days = _clean_positive_int(
        duration_days, default=INITIAL_TRIAL_DAYS, maximum=3650,
        field="trial duration",
    )
    canonical = _canonical_user_uuid(uid, user_uuid)
    event_snapshot: Dict[str, Any] = {}
    with _LOCK:
        doc = _read_doc()
        existing = _trial_row(doc, user_id=uid, user_uuid=canonical)
        if existing is not None:
            return {
                "ok": True, "created": False,
                "entitlement": _public_entitlement(existing, doc.get("plan_overrides") or {}),
                "access": _trial_access_payload(doc, existing, user_id=uid, user_uuid=canonical),
            }
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat(timespec="seconds").replace("+00:00", "Z")
        expiry = (now + timedelta(days=days)).isoformat(timespec="seconds").replace("+00:00", "Z")
        has_other_active = any(
            isinstance(other, dict)
            and str(other.get("plan_id") or "") != TRIAL_PLAN_ID
            and int(other.get("user_id") or 0) == uid
            and _entitlement_active(other)
            for other in doc.get("entitlements") or []
        )
        entitlement = {
            "entitlement_id": "ent_" + secrets.token_urlsafe(12),
            "user_id": uid, "user_uuid": canonical, "workspace_id": "",
            "plan_id": TRIAL_PLAN_ID,
            "status": "superseded" if has_other_active else "active",
            "source": str(source or "verified_registration")[:80],
            "provider": "registration", "provider_subscription_id": "",
            "source_voucher_id": "", "note": "Automatic initial full trial",
            "access_kind": "initial_trial", "trial_days": days,
            "starts_at_utc": now_iso, "expires_at_utc": expiry,
            "created_at_utc": now_iso, "updated_at_utc": now_iso,
        }
        doc["entitlements"].append(entitlement)
        event_snapshot = {
            "history_id": "ach_" + secrets.token_urlsafe(12),
            "event": "initial_trial_granted",
            "user_id": uid, "user_uuid": canonical,
            "entitlement_id": entitlement["entitlement_id"],
            "actor_user_id": uid, "actor_user_uuid": canonical,
            "source": str(source or "verified_registration")[:80],
            "reason": "verified_registration", "idempotency_key": "",
            "at_utc": now_iso, "before": None,
            "after": {
                "status": entitlement["status"],
                "starts_at_utc": now_iso, "expires_at_utc": expiry,
            },
        }
        doc["access_history"].append(event_snapshot)
        _write_doc(doc)
        public = _public_entitlement(entitlement, doc.get("plan_overrides") or {})
        access = _trial_access_payload(doc, entitlement, user_id=uid, user_uuid=canonical)
    _audit(
        "initial_trial_granted", user_id=uid,
        entitlement_id=event_snapshot.get("entitlement_id"),
        expires_at_utc=(event_snapshot.get("after") or {}).get("expires_at_utc"),
        source=str(source or "verified_registration")[:80],
    )
    return {"ok": True, "created": True, "entitlement": public, "access": access}


def _future_utc(value: Any, *, now: datetime) -> datetime:
    raw = str(value or "").strip()
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        raise SubscriptionError("Дата окончания trial должна быть UTC ISO-8601.") from None
    if parsed.tzinfo is None:
        raise SubscriptionError("Дата окончания trial должна содержать UTC offset.")
    normalized = parsed.astimezone(timezone.utc)
    if normalized <= now:
        raise SubscriptionError("Дата окончания trial должна быть в будущем.")
    return normalized


def extend_trial_access(
    actor_user_id: Any, user_id: Any, *, days: Any = None,
    expires_at_utc: Any = "", reason: str = "", idempotency_key: Any = "",
) -> Dict[str, Any]:
    """Owner extension by whole days or by an exact UTC date, with history."""
    try:
        actor = int(actor_user_id or 0)
    except (TypeError, ValueError):
        actor = 0
    try:
        uid = int(user_id or 0)
    except (TypeError, ValueError):
        uid = 0
    if actor <= 0:
        raise SubscriptionError("Owner identity обязательна.", 403)
    if uid <= 0:
        raise SubscriptionError("Пользователь обязателен.", 400)
    has_days = days not in (None, "")
    has_date = bool(str(expires_at_utc or "").strip())
    if has_days == has_date:
        raise SubscriptionError("Укажите либо количество дней, либо точную UTC-дату.")
    extension_days = (
        _clean_positive_int(days, default=1, maximum=3650, field="extension days")
        if has_days else 0
    )
    request_key = str(idempotency_key or "").strip()[:120]
    note = " ".join(str(reason or "").strip().split())[:300]
    canonical = _canonical_user_uuid(uid)
    actor_uuid = _canonical_user_uuid(actor)
    audit_snapshot: Dict[str, Any] = {}
    with _LOCK:
        doc = _read_doc()
        row = _trial_row(doc, user_id=uid, user_uuid=canonical)
        if request_key:
            replay = next((
                event for event in doc.get("access_history") or []
                if isinstance(event, dict)
                and str(event.get("event") or "") in {"trial_extended", "trial_created_by_owner"}
                and str(event.get("idempotency_key") or "") == request_key
                and int(event.get("user_id") or 0) == uid
            ), None)
            if replay is not None:
                return {
                    "ok": True, "replayed": True,
                    "access": _trial_access_payload(doc, row, user_id=uid, user_uuid=canonical),
                }
        conflicting = next((
            other for other in doc.get("entitlements") or []
            if isinstance(other, dict)
            and int(other.get("user_id") or 0) == uid
            and str(other.get("plan_id") or "") != TRIAL_PLAN_ID
            and _entitlement_active(other)
        ), None)
        if conflicting is not None:
            raise SubscriptionError("У пользователя уже действует другой план доступа.", 409)
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat(timespec="seconds").replace("+00:00", "Z")
        event_name = "trial_extended"
        if row is None:
            row = {
                "entitlement_id": "ent_" + secrets.token_urlsafe(12),
                "user_id": uid, "user_uuid": canonical, "workspace_id": "",
                "plan_id": TRIAL_PLAN_ID, "status": "active",
                "source": "owner_extension", "provider": "owner",
                "provider_subscription_id": "", "source_voucher_id": "",
                "note": note, "access_kind": "initial_trial", "trial_days": 0,
                "starts_at_utc": now_iso, "expires_at_utc": "",
                "created_at_utc": now_iso, "updated_at_utc": now_iso,
            }
            doc["entitlements"].append(row)
            event_name = "trial_created_by_owner"
        before = {
            "status": str(row.get("status") or ""),
            "starts_at_utc": str(row.get("starts_at_utc") or ""),
            "expires_at_utc": str(row.get("expires_at_utc") or ""),
        }
        current_expiry = _parse_iso(row.get("expires_at_utc"))
        if current_expiry is not None and current_expiry.tzinfo is None:
            current_expiry = current_expiry.replace(tzinfo=timezone.utc)
        if has_days:
            base = current_expiry if current_expiry and current_expiry > now else now
            new_expiry = base + timedelta(days=extension_days)
        else:
            new_expiry = _future_utc(expires_at_utc, now=now)
            if current_expiry and current_expiry > now and new_expiry <= current_expiry:
                raise SubscriptionError("Новая дата должна продлевать текущий trial.", 409)
        expiry_iso = new_expiry.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        row.update({
            "status": "active", "expires_at_utc": expiry_iso,
            "updated_at_utc": now_iso, "last_extended_at_utc": now_iso,
            "last_extended_by_user_id": actor,
            "last_extended_by_user_uuid": actor_uuid,
        })
        if note:
            row["note"] = note
        after = {
            "status": "active",
            "starts_at_utc": str(row.get("starts_at_utc") or ""),
            "expires_at_utc": expiry_iso,
        }
        audit_snapshot = {
            "history_id": "ach_" + secrets.token_urlsafe(12),
            "event": event_name, "user_id": uid, "user_uuid": canonical,
            "entitlement_id": row["entitlement_id"],
            "actor_user_id": actor, "actor_user_uuid": actor_uuid,
            "source": "owner", "reason": note,
            "idempotency_key": request_key, "at_utc": now_iso,
            "before": before, "after": after,
        }
        doc["access_history"].append(audit_snapshot)
        _write_doc(doc)
        access = _trial_access_payload(doc, row, user_id=uid, user_uuid=canonical)
    _audit(
        audit_snapshot["event"], owner_id=actor, user_id=uid,
        entitlement_id=audit_snapshot["entitlement_id"],
        before=audit_snapshot["before"], after=audit_snapshot["after"],
        reason=note,
    )
    return {"ok": True, "replayed": False, "access": access}


def grant_plan(actor_user_id: Any, user_id: Any, plan_id: Any, *, duration_days: Any = 0,
               note: str = "", source: str = "manual") -> Dict[str, Any]:
    try:
        actor = int(actor_user_id or 0)
    except (TypeError, ValueError):
        actor = 0
    if actor <= 0:
        raise SubscriptionError("Owner identity обязательна.", 403)
    try:
        uid = int(user_id or 0)
    except (TypeError, ValueError):
        uid = 0
    if uid <= 0:
        raise SubscriptionError("Пользователь обязателен.", 400)
    pid = _clean_plan(plan_id, required=True)
    days = _clean_duration(duration_days)
    with _LOCK:
        doc = _read_doc()
        overrides = doc.get("plan_overrides") or {}
        for row in doc["entitlements"]:
            if int(row.get("user_id") or 0) == uid and str(row.get("status")) in _ACTIVE_STATUSES:
                row["status"] = "superseded"
                row["updated_at_utc"] = _now_iso()
        ent = {
            "entitlement_id": "ent_" + secrets.token_urlsafe(12),
            "user_id": uid, "workspace_id": "", "plan_id": pid,
            "status": "active", "source": source, "provider": source,
            "provider_subscription_id": "", "source_voucher_id": "",
            "note": str(note or "")[:300],
            "starts_at_utc": _now_iso(), "expires_at_utc": _entitlement_expiry(days),
            "created_at_utc": _now_iso(),
        }
        doc["entitlements"].append(ent)
        _write_doc(doc)
        snapshot = dict(ent)
    _audit("plan_granted", owner_id=actor, user_id=uid, plan_id=pid, duration_days=days)
    return {"ok": True, "entitlement": _public_entitlement(snapshot, overrides)}


def clear_user_plan(actor_user_id: Any, user_id: Any) -> Dict[str, Any]:
    try:
        actor = int(actor_user_id or 0)
    except (TypeError, ValueError):
        actor = 0
    if actor <= 0:
        raise SubscriptionError("Owner identity обязательна.", 403)
    uid = int(user_id or 0)
    with _LOCK:
        doc = _read_doc()
        changed = False
        for row in doc["entitlements"]:
            if int(row.get("user_id") or 0) == uid and str(row.get("status")) in _ACTIVE_STATUSES:
                row["status"] = "revoked"
                row["updated_at_utc"] = _now_iso()
                changed = True
        if changed:
            _write_doc(doc)
    _audit("plan_cleared", owner_id=actor, user_id=uid)
    return {"ok": changed}


def _public_request(row: Dict[str, Any]) -> Dict[str, Any]:
    return {key: row.get(key) for key in (
        "request_id", "user_id", "plan_id", "kind", "amount_usd", "note",
        "status", "created_at_utc", "resolved_at_utc", "resolver_user_id",
    )}


def create_payment_request(user_id: Any, plan_id: Any, *, note: str = "") -> Dict[str, Any]:
    try:
        uid = int(user_id or 0)
    except (TypeError, ValueError):
        uid = 0
    if uid <= 0:
        raise SubscriptionError("Пользователь обязателен.", 403)
    pid = _clean_plan(plan_id, required=True)
    plan = _effective_plan(pid)
    request = {
        "request_id": "pr_" + secrets.token_urlsafe(10),
        "user_id": uid, "plan_id": pid,
        "kind": "donation" if plan.get("category") == "donation" else "subscription",
        "amount_usd": float(plan.get("price_usd") or 0),
        "note": str(note or "")[:300],
        "status": "pending", "created_at_utc": _now_iso(),
        "resolved_at_utc": "", "resolver_user_id": 0,
    }
    with _LOCK:
        doc = _read_doc()
        payment = doc.get("payment_config") if isinstance(doc.get("payment_config"), dict) else {}
        if not payment.get("enabled") or not str(payment.get("paypal_me") or "").strip():
            raise SubscriptionError(
                "PayPal владельца ещё не настроен; заявку после оплаты отправить нельзя.",
                409,
            )
        existing = next((row for row in doc["payment_requests"]
                         if int(row.get("user_id") or 0) == uid and str(row.get("plan_id")) == pid
                         and row.get("status") == "pending"), None)
        if existing is not None:
            return {"ok": True, "request": _public_request(existing), "duplicate": True}
        doc["payment_requests"] = (doc["payment_requests"] + [request])[-500:]
        _write_doc(doc)
    _audit("payment_request_created", user_id=uid, plan_id=pid)
    return {"ok": True, "request": _public_request(request), "duplicate": False}


def list_payment_requests(actor_user_id: Any, *, status: str = "") -> Dict[str, Any]:
    try:
        actor = int(actor_user_id or 0)
    except (TypeError, ValueError):
        actor = 0
    if actor <= 0:
        raise SubscriptionError("Owner identity обязательна.", 403)
    with _LOCK:
        rows = list(_read_doc()["payment_requests"])
    pending = sum(1 for row in rows if row.get("status") == "pending")
    rows.sort(key=lambda row: str(row.get("created_at_utc") or ""), reverse=True)
    if status:
        rows = [row for row in rows if str(row.get("status")) == status]
    return {"requests": [_public_request(row) for row in rows], "pending": pending}


def resolve_payment_request(actor_user_id: Any, request_id: str, *, approve: bool, duration_days: Any = 0) -> Dict[str, Any]:
    try:
        actor = int(actor_user_id or 0)
    except (TypeError, ValueError):
        actor = 0
    if actor <= 0:
        raise SubscriptionError("Owner identity обязательна.", 403)
    rid = str(request_id or "")
    with _LOCK:
        doc = _read_doc()
        request = next((row for row in doc["payment_requests"] if str(row.get("request_id")) == rid), None)
        if request is None:
            raise SubscriptionError("Заявка не найдена.", 404)
        if request.get("status") != "pending":
            return {"ok": True, "request": _public_request(request), "already_resolved": True}
        request["status"] = "approved" if approve else "rejected"
        request["resolved_at_utc"] = _now_iso()
        request["resolver_user_id"] = actor
        _write_doc(doc)
        uid = int(request.get("user_id") or 0)
        pid = str(request.get("plan_id"))
        snapshot = _public_request(request)
    entitlement = None
    if approve:
        entitlement = grant_plan(actor, uid, pid, duration_days=duration_days,
                                 note="Оплата PayPal (ручная проверка)").get("entitlement")
    _audit("payment_request_resolved", owner_id=actor, request_id=rid, approve=bool(approve))
    return {"ok": True, "request": snapshot, "entitlement": entitlement}


def _invite_links(code: str, *, bot_username: str = "", public_url: str = "") -> Dict[str, Any]:
    bot = re.sub(r"[^A-Za-z0-9_]", "", str(bot_username or "").lstrip("@"))
    pub = str(public_url or "").rstrip("/")
    out: Dict[str, Any] = {"code": code}
    if bot:
        out["telegram"] = f"https://t.me/{bot}?start=ref_{code}"
    if pub:
        out["web"] = f"{pub}/ui/?ref={code}"
    primary = out.get("telegram") or out.get("web") or ""
    out["message"] = (
        "Приглашаю в StratForge AI — платформу разработки и контроля "
        f"NinjaTrader-стратегий с ИИ.\nПромокод: {code}" + (f"\n{primary}" if primary else "")
    )
    return out


def create_invite(actor_user_id: Any, body: Dict[str, Any], *, bot_username: str = "", public_url: str = "") -> Dict[str, Any]:
    created = create_voucher(actor_user_id, body)
    code = str((created.get("voucher") or {}).get("code") or "")
    created["invite"] = _invite_links(code, bot_username=bot_username, public_url=public_url)
    return created


def _normalize_code(value: Any) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def _code_hash(value: Any) -> str:
    code = _normalize_code(value)
    if len(code) < 8:
        raise SubscriptionError("Промокод слишком короткий.")
    return hashlib.sha256(("promo:v1:" + code).encode("ascii")).hexdigest()


def _generate_code(prefix: str = "SF") -> str:
    clean_prefix = re.sub(r"[^A-Z0-9]", "", str(prefix or "SF").upper())[:8] or "SF"
    token = secrets.token_hex(6).upper()
    return f"{clean_prefix}-{token[:4]}-{token[4:8]}-{token[8:12]}"


def _clean_label(value: Any) -> str:
    label = " ".join(str(value or "").strip().split())
    if not 1 <= len(label) <= 120:
        raise SubscriptionError("Название промокода обязательно.")
    return label


def _clean_plan(plan_id: Any, *, required: bool = False) -> str:
    plan = str(plan_id or "").strip()
    if not plan:
        if required:
            raise SubscriptionError("Укажите тарифный план.")
        return ""
    if plan not in PLANS:
        raise SubscriptionError("Неизвестный тарифный план.")
    return plan


def _clean_percent(value: Any) -> int:
    if value in (None, ""):
        return 0
    try:
        percent = int(value)
    except (TypeError, ValueError):
        raise SubscriptionError("Скидка должна быть целым процентом.") from None
    if not 0 <= percent <= 100:
        raise SubscriptionError("Скидка должна быть от 0 до 100%.")
    return percent


def _clean_positive_int(value: Any, *, default: int, maximum: int, field: str) -> int:
    if value in (None, ""):
        return default
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise SubscriptionError(f"Поле {field} должно быть числом.") from None
    if not 1 <= number <= maximum:
        raise SubscriptionError(f"Поле {field} должно быть от 1 до {maximum}.")
    return number


def _clean_duration(value: Any) -> int:
    if value in (None, ""):
        return 0
    try:
        days = int(value)
    except (TypeError, ValueError):
        raise SubscriptionError("Срок grant должен быть числом дней.") from None
    if not 0 <= days <= 3650:
        raise SubscriptionError("Срок grant должен быть от 0 до 3650 дней.")
    return days


def _clean_telegram_ids(values: Optional[Iterable[Any]]) -> list[int]:
    out: list[int] = []
    for raw in values or []:
        try:
            user_id = int(raw)
        except (TypeError, ValueError):
            raise SubscriptionError("Telegram id в ограничении промокода некорректен.") from None
        if user_id > 0 and user_id not in out:
            out.append(user_id)
    return out[:1000]


def _clean_domains(values: Optional[Iterable[Any]]) -> list[str]:
    out: list[str] = []
    for raw in values or []:
        domain = str(raw or "").strip().lower().lstrip("@")
        if not domain:
            continue
        if not re.fullmatch(r"[a-z0-9.-]+\.[a-z]{2,}", domain):
            raise SubscriptionError("Домен e-mail в ограничении промокода некорректен.")
        if domain not in out:
            out.append(domain)
    return out[:100]


def _parse_iso(value: Any) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        raise SubscriptionError("Дата окончания промокода должна быть ISO timestamp.") from None


def _email_domain(email: Any) -> str:
    text = str(email or "").strip().lower()
    return text.rsplit("@", 1)[1] if "@" in text else ""


def _public_voucher(row: Dict[str, Any]) -> Dict[str, Any]:
    out = {key: row.get(key) for key in (
        "voucher_id", "label", "status", "grant_plan_id", "discount_percent",
        "grant_duration_days", "usage_limit", "used_count", "per_user_limit",
        "expires_at_utc", "allowed_telegram_ids", "allowed_user_uuids", "allowed_email_domains",
        "created_by_user_id", "created_by_user_uuid", "created_at_utc", "paused_at_utc", "revoked_at_utc",
    )}
    redemptions = row.get("redemptions") if isinstance(row.get("redemptions"), list) else []
    out["redemptions"] = [
        {"user_id": r.get("user_id"), "user_uuid": r.get("user_uuid") or "", "entitlement_id": r.get("entitlement_id"),
         "redeemed_at_utc": r.get("redeemed_at_utc")}
        for r in redemptions if isinstance(r, dict)
    ]
    return out


def _public_entitlement(row: Dict[str, Any], overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    plan_id = str(row.get("plan_id") or "")
    return {
        "entitlement_id": row.get("entitlement_id"),
        "user_id": row.get("user_id"),
        "user_uuid": row.get("user_uuid") or "",
        "workspace_id": row.get("workspace_id") or "",
        "plan_id": plan_id,
        "plan": _effective_plan(plan_id, overrides),
        "status": row.get("status"),
        "source": row.get("source"),
        "provider": row.get("provider") or "",
        "provider_subscription_id": row.get("provider_subscription_id") or "",
        "source_voucher_id": row.get("source_voucher_id") or "",
        "access_kind": row.get("access_kind") or "",
        "starts_at_utc": row.get("starts_at_utc") or "",
        "expires_at_utc": row.get("expires_at_utc") or "",
        "created_at_utc": row.get("created_at_utc") or "",
        "updated_at_utc": row.get("updated_at_utc") or "",
    }


def _voucher_by_hash(doc: Dict[str, Any], code_hash: str) -> Optional[Dict[str, Any]]:
    return next((row for row in doc["vouchers"] if hmac.compare_digest(str(row.get("code_hash") or ""), code_hash)), None)


def _existing_entitlement(doc: Dict[str, Any], *, voucher_id: str, user_id: int) -> Optional[Dict[str, Any]]:
    return next((row for row in doc["entitlements"]
                 if int(row.get("user_id") or 0) == int(user_id)
                 and str(row.get("source_voucher_id") or "") == str(voucher_id)), None)


def _validate_voucher(row: Dict[str, Any], *, user_id: int, email: str) -> None:
    if str(row.get("status") or "") != "active":
        raise SubscriptionError("Промокод не активен.", 409)
    expires = _parse_iso(row.get("expires_at_utc"))
    if expires and expires <= datetime.now(timezone.utc):
        raise SubscriptionError("Срок действия промокода истёк.", 409)
    if int(row.get("used_count") or 0) >= int(row.get("usage_limit") or 1):
        raise SubscriptionError("Лимит использований промокода исчерпан.", 409)
    allowed_ids = {int(value) for value in row.get("allowed_telegram_ids") or []}
    if allowed_ids and int(user_id) not in allowed_ids:
        raise SubscriptionError("Этот промокод не предназначен для данного пользователя.", 403)
    allowed_domains = {str(value).lower() for value in row.get("allowed_email_domains") or []}
    if allowed_domains and _email_domain(email) not in allowed_domains:
        raise SubscriptionError("Этот промокод ограничен другим e-mail доменом.", 403)


def _entitlement_expiry(duration_days: int) -> str:
    if duration_days <= 0:
        return ""
    return (datetime.now(timezone.utc) + timedelta(days=duration_days)).isoformat(timespec="seconds").replace("+00:00", "Z")


def _audit(event: str, **values: Any) -> None:
    if runtime_env.is_production() and runtime_env.environment_explicit():
        from . import storage_router
        from .production_storage import StorageError
        try:
            storage_router.append_audit("subscription_entitlements", event, values)
            return
        except StorageError as exc:
            raise SubscriptionError(
                f"Production subscription audit unavailable ({exc.code}).", 503,
            ) from None
    row = {"timestamp": _now_iso(), "source": "subscription_entitlements", "event": event, **values}
    path = _audit_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def create_voucher(actor_user_id: Any, body: Dict[str, Any]) -> Dict[str, Any]:
    try:
        actor = int(actor_user_id or 0)
    except (TypeError, ValueError):
        actor = 0
    if actor <= 0:
        raise SubscriptionError("Owner identity обязательна.", 403)

    label = _clean_label(body.get("label"))
    grant_plan_id = _clean_plan(body.get("grant_plan_id") or body.get("plan_id"))
    discount_percent = _clean_percent(body.get("discount_percent"))
    if not grant_plan_id and discount_percent <= 0:
        raise SubscriptionError("Промокод должен выдавать план или скидку.")
    if grant_plan_id and discount_percent <= 0:
        discount_percent = 100

    voucher = {
        "voucher_id": "vch_" + secrets.token_urlsafe(12),
        "label": label,
        "status": "active",
        "grant_plan_id": grant_plan_id,
        "discount_percent": discount_percent,
        "grant_duration_days": _clean_duration(body.get("grant_duration_days")),
        "usage_limit": _clean_positive_int(body.get("usage_limit"), default=1, maximum=100000, field="usage_limit"),
        "used_count": 0,
        "per_user_limit": _clean_positive_int(body.get("per_user_limit"), default=1, maximum=1000, field="per_user_limit"),
        "expires_at_utc": str(body.get("expires_at_utc") or "").strip(),
        "allowed_telegram_ids": _clean_telegram_ids(body.get("allowed_telegram_ids") or []),
        "allowed_email_domains": _clean_domains(body.get("allowed_email_domains") or []),
        "created_by_user_id": actor,
        "created_at_utc": _now_iso(),
        "paused_at_utc": "",
        "revoked_at_utc": "",
        "redemptions": [],
    }
    _parse_iso(voucher["expires_at_utc"])

    with _LOCK:
        doc = _read_doc()
        for _attempt in range(20):
            code = _generate_code(body.get("code_prefix") or "SF")
            code_hash = _code_hash(code)
            if _voucher_by_hash(doc, code_hash) is None:
                voucher["code_hash"] = code_hash
                break
        if not voucher.get("code_hash"):
            raise SubscriptionError("Не удалось сгенерировать уникальный промокод.", 500)
        doc["vouchers"].append(voucher)
        _write_doc(doc)

    _audit("voucher_created", owner_id=actor, voucher_id=voucher["voucher_id"], grant_plan_id=grant_plan_id)
    public = _public_voucher(voucher)
    public["code"] = code
    return {"ok": True, "voucher": public, "storage": storage_status()}


def list_vouchers(actor_user_id: Any) -> Dict[str, Any]:
    try:
        actor = int(actor_user_id or 0)
    except (TypeError, ValueError):
        actor = 0
    if actor <= 0:
        raise SubscriptionError("Owner identity обязательна.", 403)
    with _LOCK:
        doc = _read_doc()
        vouchers = sorted(doc["vouchers"], key=lambda row: str(row.get("created_at_utc") or ""), reverse=True)
        return {"vouchers": [_public_voucher(row) for row in vouchers], "storage": storage_status()}


_VOUCHER_STATUSES = ("active", "paused", "archived", "revoked")


def set_voucher_status(actor_user_id: Any, voucher_id: str, status: str) -> Dict[str, Any]:
    """Owner invitation lifecycle: active / paused (cancel) / archived / revoked.
    Only ``active`` vouchers can be redeemed, so any other status disables the
    invite without deleting its audit trail."""
    try:
        actor = int(actor_user_id or 0)
    except (TypeError, ValueError):
        actor = 0
    if actor <= 0:
        raise SubscriptionError("Owner identity обязательна.", 403)
    new_status = str(status or "")
    if new_status not in _VOUCHER_STATUSES:
        raise SubscriptionError("Недопустимый статус приглашения.")
    vid = str(voucher_id or "")
    with _LOCK:
        doc = _read_doc()
        voucher = next((row for row in doc["vouchers"] if str(row.get("voucher_id") or "") == vid), None)
        if voucher is None:
            raise SubscriptionError("Приглашение не найдено.", 404)
        voucher["status"] = new_status
        now = _now_iso()
        voucher["updated_at_utc"] = now
        if new_status == "paused":
            voucher["paused_at_utc"] = now
        elif new_status == "revoked":
            voucher["revoked_at_utc"] = now
        elif new_status == "active":
            voucher["paused_at_utc"] = ""
            voucher["revoked_at_utc"] = ""
        _write_doc(doc)
    _audit("voucher_status_changed", actor=actor, voucher_id=vid, status=new_status)
    return list_vouchers(actor_user_id)


def delete_voucher(actor_user_id: Any, voucher_id: str) -> Dict[str, Any]:
    """Permanently remove an invitation voucher."""
    try:
        actor = int(actor_user_id or 0)
    except (TypeError, ValueError):
        actor = 0
    if actor <= 0:
        raise SubscriptionError("Owner identity обязательна.", 403)
    vid = str(voucher_id or "")
    with _LOCK:
        doc = _read_doc()
        before = len(doc["vouchers"])
        doc["vouchers"] = [row for row in doc["vouchers"] if str(row.get("voucher_id") or "") != vid]
        if len(doc["vouchers"]) == before:
            raise SubscriptionError("Приглашение не найдено.", 404)
        _write_doc(doc)
    _audit("voucher_deleted", actor=actor, voucher_id=vid)
    return list_vouchers(actor_user_id)


def voucher_by_id(actor_user_id: Any, voucher_id: str) -> Dict[str, Any]:
    try:
        actor = int(actor_user_id or 0)
    except (TypeError, ValueError):
        actor = 0
    if actor <= 0:
        raise SubscriptionError("Owner identity обязательна.", 403)
    vid = str(voucher_id or "")
    with _LOCK:
        doc = _read_doc()
        voucher = next((row for row in doc["vouchers"] if str(row.get("voucher_id") or "") == vid), None)
        if voucher is None:
            raise SubscriptionError("Приглашение не найдено.", 404)
        return _public_voucher(voucher)


def preview_voucher(code: Any, *, user_id: Any = 0, email: str = "", requested_plan_id: str = "") -> Dict[str, Any]:
    code_hash = _code_hash(code)
    user = int(user_id or 0)
    requested_plan = _clean_plan(requested_plan_id)
    with _LOCK:
        doc = _read_doc()
        voucher = _voucher_by_hash(doc, code_hash)
        if voucher is None:
            raise SubscriptionError("Промокод не найден.", 404)
        _validate_voucher(voucher, user_id=user, email=email)
        grant_plan_id = str(voucher.get("grant_plan_id") or "")
        checkout_required = not grant_plan_id and int(voucher.get("discount_percent") or 0) < 100
        if checkout_required and not requested_plan:
            raise SubscriptionError("Для скидочного промокода выберите тариф.")
        return {
            "ok": True,
            "voucher": _public_voucher(voucher),
            "grant_plan_id": grant_plan_id,
            "requested_plan_id": requested_plan,
            "discount_percent": int(voucher.get("discount_percent") or 0),
            "checkout_required": checkout_required,
            "card_required": checkout_required,
        }


def redeem_voucher(code: Any, *, user_id: Any, email: str = "", requested_plan_id: str = "",
                   workspace_id: str = "") -> Dict[str, Any]:
    code_hash = _code_hash(code)
    try:
        user = int(user_id or 0)
    except (TypeError, ValueError):
        user = 0
    if user <= 0:
        raise SubscriptionError("Пользователь обязателен для активации промокода.", 403)
    requested_plan = _clean_plan(requested_plan_id)

    with _LOCK:
        doc = _read_doc()
        voucher = _voucher_by_hash(doc, code_hash)
        if voucher is None:
            raise SubscriptionError("Промокод не найден.", 404)
        existing = _existing_entitlement(doc, voucher_id=str(voucher.get("voucher_id") or ""), user_id=user)
        if existing is not None:
            return {"ok": True, "already_redeemed": True, "entitlement": _public_entitlement(existing), "voucher": _public_voucher(voucher)}

        _validate_voucher(voucher, user_id=user, email=email)
        grant_plan_id = str(voucher.get("grant_plan_id") or "")
        discount_percent = int(voucher.get("discount_percent") or 0)
        if not grant_plan_id and discount_percent < 100:
            if not requested_plan:
                raise SubscriptionError("Для скидочного промокода выберите тариф.")
            return {
                "ok": True,
                "checkout_required": True,
                "card_required": True,
                "voucher": _public_voucher(voucher),
                "requested_plan_id": requested_plan,
                "discount_percent": discount_percent,
            }

        plan_id = grant_plan_id or requested_plan
        if not plan_id:
            raise SubscriptionError("Промокод не указывает тарифный план.")
        _clean_plan(plan_id, required=True)
        entitlement = {
            "entitlement_id": "ent_" + secrets.token_urlsafe(12),
            "user_id": user,
            "workspace_id": str(workspace_id or ""),
            "plan_id": plan_id,
            "status": "promo_grant",
            "source": "promo_code",
            "source_voucher_id": str(voucher.get("voucher_id") or ""),
            "starts_at_utc": _now_iso(),
            "expires_at_utc": _entitlement_expiry(int(voucher.get("grant_duration_days") or 0)),
            "created_at_utc": _now_iso(),
        }
        doc["entitlements"].append(entitlement)
        voucher["used_count"] = int(voucher.get("used_count") or 0) + 1
        redemptions = voucher.setdefault("redemptions", [])
        if isinstance(redemptions, list):
            redemptions.append({"user_id": user, "entitlement_id": entitlement["entitlement_id"], "redeemed_at_utc": _now_iso()})
        _write_doc(doc)

    _audit("voucher_redeemed", user_id=user, voucher_id=voucher.get("voucher_id"), entitlement_id=entitlement["entitlement_id"])
    return {"ok": True, "already_redeemed": False, "entitlement": _public_entitlement(entitlement), "voucher": _public_voucher(voucher)}


def entitlements_for_user(user_id: Any) -> Dict[str, Any]:
    try:
        user = int(user_id or 0)
    except (TypeError, ValueError):
        user = 0
    if user <= 0:
        return {"entitlements": [], "storage": storage_status()}
    with _LOCK:
        doc = _read_doc_reference()
        overrides = doc.get("plan_overrides") or {}
        rows = [row for row in doc["entitlements"] if int(row.get("user_id") or 0) == user]
        rows.sort(key=lambda row: str(row.get("created_at_utc") or ""), reverse=True)
        return {
            "entitlements": [{**_public_entitlement(row, overrides), "active": _entitlement_active(row)} for row in rows],
            "storage": storage_status(),
        }


def active_entitlement(user_id: Any) -> Dict[str, Any]:
    for row in entitlements_for_user(user_id).get("entitlements") or []:
        if row.get("active"):
            return row
    return {}
