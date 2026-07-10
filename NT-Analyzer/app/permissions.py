"""Centralised authorization layer.

Authentication (``account_auth``) answers *who* the user is. Entitlements
(``subscriptions``) answer *which plan* they hold. This module is the single
place that turns a plan plus owner overrides into the concrete capabilities a
user has, maps those capabilities onto the Aurora navigation, and decides
whether a given API action is allowed.

Every feature and every future module must authorize through this layer rather
than re-deriving access rules, so that a subscription level, an owner grant or a
promo redemption consistently controls what a user can see and do.

Resolution order for a non-owner user's capability ``C``:

    1. Start from the capabilities of the user's *active* entitlement plan.
    2. If the user has no active entitlement, fall back to the Free Preview plan.
    3. Apply the owner's per-user ``permission_overrides`` (explicit grant/revoke
       of an individual capability) on top — these always win.
    The owner (``is_owner``) always has every capability.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import subscriptions


# The default contour for a brand-new, unpaid user.
FREE_PREVIEW_PLAN_ID = "free_preview"

# The canonical capability catalog IS the subscription privilege matrix. The
# owner edits it per-plan (subscriptions.set_plan_feature) and per-user
# (account_auth.set_user_permission).
CAPABILITIES = subscriptions.PLAN_FEATURES  # tuple of {"id","label","hint"?}
CAPABILITY_IDS = tuple(c["id"] for c in CAPABILITIES)

# Aurora left-nav sections (ui.js NAV ids). "overview" is always available.
NAV_SECTIONS = ("overview", "backtest", "trading", "desktop", "performance",
                "strategies", "ai", "agents", "news", "topstep", "docs")

# Which nav sections each subscription capability unlocks. A section is open
# when ANY of its contributing capabilities is granted.
CAPABILITY_NAV: Dict[str, tuple] = {
    "backtesting":     ("backtest",),
    "strategies":      ("strategies",),
    "charts_realtime": ("desktop",),
    "ai_lab":          ("ai",),
    "ai_pro_models":   ("agents",),
    "news":            ("news",),
    "documents":       ("docs",),
    "paper_commands":  ("trading",),
    "live_read":       ("performance",),
    "live_commands":   (),
    "personal_nt":     (),
}

# Nav sections not tied to any subscription capability. Locked for non-owners
# unless the owner grants them explicitly per user (feature_overrides).
_OWNER_ONLY_NAV = ("topstep",)

# Shown on a locked section in Free Preview.
UNLOCK_MESSAGE = (
    "Раздел откроется после активации подписки, ввода промокода "
    "или доступа от владельца."
)

# API action -> capability required (prefix match, longest prefix wins). The
# owner is always allowed. Any path not listed here is allowed for every
# authenticated user (self-service, auth, cabinet, read-only observation).
ROUTE_CAPABILITY = (
    ("/api/ai-lab/", "ai_lab"),
    ("/api/ai-agents", "ai_lab"),
    ("/api/ops/live/", "live_commands"),
)


class PermissionError(RuntimeError):
    def __init__(self, message: str, status: int = 403):
        super().__init__(message)
        self.status = int(status)


def capability_catalog() -> List[Dict[str, Any]]:
    return [dict(c) for c in CAPABILITIES]


def _features_from_plan(plan: Optional[Dict[str, Any]]) -> Dict[str, bool]:
    feats = (plan or {}).get("features") if isinstance(plan, dict) else None
    if isinstance(feats, dict) and feats:
        return {cid: bool(feats.get(cid, False)) for cid in CAPABILITY_IDS}
    return {}


def _free_preview_features() -> Dict[str, bool]:
    feats = _features_from_plan(subscriptions.effective_plan(FREE_PREVIEW_PLAN_ID))
    return feats or {cid: False for cid in CAPABILITY_IDS}


def resolve(user: Optional[Dict[str, Any]],
            entitlement: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Compute a user's effective capabilities + navigation from their plan.

    ``entitlement`` is the user's active entitlement row (as returned by
    ``subscriptions.active_entitlement``) or None/{} for a Free Preview user.
    Pure function: no I/O beyond reading the Free Preview plan matrix.
    """
    user = user or {}
    if user.get("is_owner"):
        caps = {cid: True for cid in CAPABILITY_IDS}
        nav = {nid: True for nid in NAV_SECTIONS}
        return {
            "is_owner": True, "plan_id": "founder", "free_preview": False,
            "capabilities": caps, "nav": nav, "locked_nav": [],
            "unlock_message": UNLOCK_MESSAGE,
        }

    plan_feats = _features_from_plan((entitlement or {}).get("plan"))
    plan_id = str((entitlement or {}).get("plan_id") or "")
    free_preview = not plan_feats
    if free_preview:
        plan_feats = _free_preview_features()
        plan_id = FREE_PREVIEW_PLAN_ID

    cap_ov = user.get("permission_overrides")
    cap_ov = cap_ov if isinstance(cap_ov, dict) else {}
    caps: Dict[str, bool] = {}
    for cid in CAPABILITY_IDS:
        override = cap_ov.get(cid)
        caps[cid] = bool(override) if isinstance(override, bool) else bool(plan_feats.get(cid, False))

    nav_ov = user.get("feature_overrides")
    nav_ov = nav_ov if isinstance(nav_ov, dict) else {}
    nav: Dict[str, bool] = {"overview": True}
    for nid in NAV_SECTIONS:
        if nid == "overview":
            continue
        enabled = any(caps.get(cid) for cid, sections in CAPABILITY_NAV.items() if nid in sections)
        if nid in _OWNER_ONLY_NAV:
            enabled = False
        section_override = nav_ov.get(nid)
        if isinstance(section_override, bool):
            enabled = section_override
        nav[nid] = enabled

    locked = [nid for nid in NAV_SECTIONS if nid != "overview" and not nav.get(nid)]
    return {
        "is_owner": False, "plan_id": plan_id, "free_preview": free_preview,
        "capabilities": caps, "nav": nav, "locked_nav": locked,
        "unlock_message": UNLOCK_MESSAGE,
    }


def resolve_for_user_id(user_id: Any, user: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Resolve permissions, fetching the active entitlement for ``user_id``."""
    try:
        entitlement = subscriptions.active_entitlement(user_id)
    except subscriptions.SubscriptionError:
        entitlement = {}
    return resolve(user or {}, entitlement)


def required_capability(path: str) -> Optional[str]:
    """The capability an API path requires, or None when unrestricted."""
    p = str(path or "")
    best: Optional[str] = None
    best_len = -1
    for prefix, cap in ROUTE_CAPABILITY:
        if p.startswith(prefix) and len(prefix) > best_len:
            best, best_len = cap, len(prefix)
    return best


def enforce(path: str, context: Optional[Dict[str, Any]]) -> None:
    """Raise ``PermissionError`` when the request's user lacks the capability
    that ``path`` requires. The owner is always allowed; unrestricted paths and
    missing users are no-ops (authentication is handled upstream)."""
    context = context or {}
    if context.get("is_owner"):
        return
    cap = required_capability(path)
    if not cap:
        return
    caps = context.get("capabilities")
    if not isinstance(caps, dict):
        caps = resolve_for_user_id(context.get("user_id"), context.get("user") or {})["capabilities"]
    if not caps.get(cap):
        label = next((c.get("label") for c in CAPABILITIES if c.get("id") == cap), cap)
        raise PermissionError(
            f"«{label}» недоступно в вашем тарифе. Активируйте подписку, "
            "введите промокод или получите доступ у владельца.", 403)
