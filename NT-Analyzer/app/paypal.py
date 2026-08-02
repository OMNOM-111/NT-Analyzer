"""PayPal Subscriptions integration (server-side, MVP).

Only the owner's PayPal REST API credentials are stored (inside the DPAPI-
encrypted subscriptions document). Payer card data is never touched — PayPal
hosts the entire checkout. Paid tiers are activated automatically from the
``BILLING.SUBSCRIPTION.*`` webhook, verified via PayPal's
``verify-webhook-signature`` API.

The HTTP layer (:func:`_http`) is intentionally small and monkeypatchable so
the subscription/webhook logic can be unit-tested without network access.
"""
from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request
from typing import Any, Dict, Optional

from . import subscriptions


SANDBOX_BASE = "https://api-m.sandbox.paypal.com"
LIVE_BASE = "https://api-m.paypal.com"

PLAN_PRICES = {"basic": "4.99", "standard": "9.99", "pro": "25.00"}
PLAN_TITLES = {"basic": "StratForge Базовый", "standard": "StratForge Стандарт", "pro": "StratForge Pro"}


class PayPalError(RuntimeError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = int(status)


def _base(cfg: Dict[str, Any]) -> str:
    return LIVE_BASE if str(cfg.get("mode") or "sandbox").lower() == "live" else SANDBOX_BASE


def _http(method: str, url: str, *, headers: Dict[str, str], body: Optional[bytes] = None,
          timeout: float = 20.0) -> Dict[str, Any]:
    """Minimal JSON HTTP call. Raises PayPalError on transport/HTTP failure."""
    request = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            payload = json.loads(exc.read().decode("utf-8", errors="replace"))
            detail = str(payload.get("message") or payload.get("error_description") or "")
        except Exception:
            detail = ""
        raise PayPalError(detail or f"PayPal HTTP {exc.code}", 502) from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise PayPalError(f"PayPal недоступен: {exc}", 502) from None
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except ValueError:
        return {}


def _access_token(cfg: Dict[str, Any]) -> str:
    client_id = str(cfg.get("client_id") or "").strip()
    secret = str(cfg.get("secret") or "").strip()
    if not client_id or not secret:
        raise PayPalError("PayPal client_id и secret не заданы.", 400)
    auth = base64.b64encode(f"{client_id}:{secret}".encode("utf-8")).decode("ascii")
    result = _http(
        "POST", f"{_base(cfg)}/v1/oauth2/token",
        headers={"Authorization": f"Basic {auth}", "Content-Type": "application/x-www-form-urlencoded"},
        body=b"grant_type=client_credentials",
    )
    token = str(result.get("access_token") or "")
    if not token:
        raise PayPalError("PayPal не выдал access_token — проверьте client_id/secret и режим.", 502)
    return token


def _auth_headers(token: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def create_subscription(user_id: Any, plan_id: str, *, return_url: str, cancel_url: str) -> Dict[str, Any]:
    cfg = subscriptions.paypal_config_raw()
    if not cfg.get("enabled"):
        raise PayPalError("Оплата PayPal выключена владельцем.", 400)
    plan_id = str(plan_id or "")
    if plan_id not in PLAN_PRICES:
        raise PayPalError("Этот тариф нельзя оплатить подпиской.", 400)
    paypal_plan = str((cfg.get("plans") or {}).get(plan_id) or "")
    if not paypal_plan:
        raise PayPalError("Для этого тарифа ещё не создан план подписки PayPal.", 400)
    token = _access_token(cfg)
    body = json.dumps({
        "plan_id": paypal_plan,
        "custom_id": f"{int(user_id)}:{plan_id}",
        "application_context": {
            "brand_name": "StratForge AI",
            "shipping_preference": "NO_SHIPPING",
            "user_action": "SUBSCRIBE_NOW",
            "return_url": return_url,
            "cancel_url": cancel_url,
        },
    }).encode("utf-8")
    result = _http("POST", f"{_base(cfg)}/v1/billing/subscriptions", headers=_auth_headers(token), body=body)
    approval = ""
    for link in result.get("links") or []:
        if str(link.get("rel")).lower() == "approve":
            approval = str(link.get("href") or "")
            break
    if not approval:
        raise PayPalError("PayPal не вернул ссылку на оплату.", 502)
    return {"ok": True, "subscription_id": str(result.get("id") or ""), "approval_url": approval, "status": str(result.get("status") or "")}


def ensure_plans(actor_user_id: Any) -> Dict[str, Any]:
    """Create (idempotently) a PayPal product + monthly billing plans and store their ids."""
    cfg = subscriptions.paypal_config_raw()
    token = _access_token(cfg)
    product_id = str(cfg.get("product_id") or "")
    if not product_id:
        product = _http("POST", f"{_base(cfg)}/v1/catalogs/products", headers=_auth_headers(token), body=json.dumps({
            "name": "StratForge AI",
            "description": "Подписка на платформу StratForge AI",
            "type": "SERVICE",
            "category": "SOFTWARE",
        }).encode("utf-8"))
        product_id = str(product.get("id") or "")
        if not product_id:
            raise PayPalError("PayPal не создал продукт.", 502)
    plans = dict(cfg.get("plans") or {})
    for plan_id, price in PLAN_PRICES.items():
        if plans.get(plan_id):
            continue
        created = _http("POST", f"{_base(cfg)}/v1/billing/plans", headers=_auth_headers(token), body=json.dumps({
            "product_id": product_id,
            "name": PLAN_TITLES[plan_id],
            "status": "ACTIVE",
            "billing_cycles": [{
                "frequency": {"interval_unit": "MONTH", "interval_count": 1},
                "tenure_type": "REGULAR",
                "sequence": 1,
                "total_cycles": 0,
                "pricing_scheme": {"fixed_price": {"value": price, "currency_code": "USD"}},
            }],
            "payment_preferences": {
                "auto_bill_outstanding": True,
                "setup_fee_failure_action": "CANCEL",
                "payment_failure_threshold": 2,
            },
        }).encode("utf-8"))
        plan_paypal_id = str(created.get("id") or "")
        if plan_paypal_id:
            plans[plan_id] = plan_paypal_id
    return subscriptions.set_paypal_plans(actor_user_id, product_id, plans)


def verify_webhook(headers: Dict[str, str], event: Dict[str, Any]) -> bool:
    cfg = subscriptions.paypal_config_raw()
    webhook_id = str(cfg.get("webhook_id") or "")
    if not webhook_id:
        return False
    token = _access_token(cfg)

    def _h(name: str) -> str:
        return str(headers.get(name) or headers.get(name.lower()) or headers.get(name.title()) or "")

    body = json.dumps({
        "auth_algo": _h("paypal-auth-algo"),
        "cert_url": _h("paypal-cert-url"),
        "transmission_id": _h("paypal-transmission-id"),
        "transmission_sig": _h("paypal-transmission-sig"),
        "transmission_time": _h("paypal-transmission-time"),
        "webhook_id": webhook_id,
        "webhook_event": event,
    }).encode("utf-8")
    result = _http("POST", f"{_base(cfg)}/v1/notifications/verify-webhook-signature",
                   headers=_auth_headers(token), body=body)
    return str(result.get("verification_status") or "").upper() == "SUCCESS"


_ACTIVATE_EVENTS = {
    "BILLING.SUBSCRIPTION.ACTIVATED",
    "BILLING.SUBSCRIPTION.CREATED",
    "BILLING.SUBSCRIPTION.RE-ACTIVATED",
    "PAYMENT.SALE.COMPLETED",
}
_CANCEL_EVENTS = {
    "BILLING.SUBSCRIPTION.CANCELLED",
    "BILLING.SUBSCRIPTION.EXPIRED",
    "BILLING.SUBSCRIPTION.SUSPENDED",
    "BILLING.SUBSCRIPTION.PAYMENT.FAILED",
}


def process_event(event: Dict[str, Any]) -> Dict[str, Any]:
    """Apply a verified PayPal webhook event to the entitlement store."""
    event_type = str((event or {}).get("event_type") or "")
    resource = (event or {}).get("resource") or {}
    subscription_id = str(resource.get("id") or resource.get("billing_agreement_id") or "")
    custom_id = str(resource.get("custom_id") or "")
    user_part, _, plan_part = custom_id.partition(":")
    if event_type in _ACTIVATE_EVENTS:
        if user_part and plan_part:
            try:
                subscriptions.activate_paid(user_part, plan_part, provider="paypal",
                                            provider_subscription_id=subscription_id, status="active")
            except subscriptions.SubscriptionError:
                return {"ok": False, "event_type": event_type, "reason": "activation_failed"}
            return {"ok": True, "event_type": event_type, "action": "activated"}
        return {"ok": True, "event_type": event_type, "action": "ignored_no_custom_id"}
    if event_type in _CANCEL_EVENTS:
        status = "suspended" if "SUSPENDED" in event_type else "cancelled"
        subscriptions.cancel_paid(provider_subscription_id=subscription_id, status=status)
        return {"ok": True, "event_type": event_type, "action": "cancelled"}
    return {"ok": True, "event_type": event_type, "action": "ignored"}
