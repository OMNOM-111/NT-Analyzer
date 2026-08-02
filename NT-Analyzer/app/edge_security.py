"""Fail-closed HTTP edge validation for a real StratForge deployment.

The backend only trusts forwarded headers from exact proxy IP addresses from
the typed deployment configuration.  This keeps Host and scheme decisions
independent from user-controlled X-Forwarded-* headers and makes the rootless
Cloudflare Tunnel topology enforceable in application code as well as at the
network boundary.
"""
from __future__ import annotations

from dataclasses import dataclass
import ipaddress
from typing import Any
import urllib.parse


@dataclass(frozen=True)
class EdgeDecision:
    allowed: bool
    code: str
    effective_host: str = ""
    trusted_proxy: bool = False


def _normalized_ip(value: Any) -> str:
    raw = str(value or "").strip().split("%", 1)[0]
    try:
        address = ipaddress.ip_address(raw)
    except ValueError:
        return ""
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        return str(address.ipv4_mapped)
    return str(address)


def _hostname(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw or "," in raw or any(ch in raw for ch in "\r\n\t"):
        return ""
    try:
        parsed = urllib.parse.urlsplit(raw if "://" in raw else "//" + raw)
        return str(parsed.hostname or "").lower().rstrip(".")
    except (TypeError, ValueError):
        return ""


def evaluate_request(
    config: Any,
    *,
    peer_ip: Any,
    host: Any,
    forwarded_host: Any = "",
    forwarded_proto: Any = "",
    forwarded_for: Any = "",
) -> EdgeDecision:
    """Validate one request without logging or returning sensitive values."""
    peer = _normalized_ip(peer_ip)
    trusted = peer in {
        _normalized_ip(value) for value in config.trusted_proxy_ips
    }
    has_forwarded = any(
        str(value or "").strip()
        for value in (forwarded_host, forwarded_proto, forwarded_for)
    )
    if has_forwarded and not trusted:
        return EdgeDecision(False, "untrusted_forwarded_headers")

    direct_host = _hostname(host)
    proxy_host = _hostname(forwarded_host) if forwarded_host else ""
    effective_host = proxy_host or direct_host
    if not effective_host or effective_host not in set(config.allowed_hosts):
        return EdgeDecision(False, "invalid_host", effective_host, trusted)

    if config.environment == "production":
        if config.edge_mode != "direct-local" and not trusted:
            return EdgeDecision(False, "origin_bypass", effective_host, trusted)
        proto_values = [
            value.strip().lower()
            for value in str(forwarded_proto or "").split(",")
            if value.strip()
        ]
        if proto_values != ["https"]:
            return EdgeDecision(False, "https_required", effective_host, trusted)

    return EdgeDecision(True, "ok", effective_host, trusted)
