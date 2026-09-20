"""Private HTTPS transport guard; no redirects, proxy or DNS-rebind fallback.

Only used by the trusted registry_scope. Legacy/global transport is unchanged.
The TLS certificate/SNI is validated for the original host while the connection
is pinned to one already-validated public address for this request.
"""
from __future__ import annotations

import http.client
import ipaddress
import json
import socket
import ssl
from urllib.parse import urlsplit


class PrivateTransportError(RuntimeError):
    pass


MAX_RESPONSE_BYTES = 1024 * 1024
_PREFIXES = ("", "/v1", "/api/v1", "/openai/v1", "/api/paas/v4", "/inference")
_PATHS = frozenset(prefix + suffix for prefix in _PREFIXES for suffix in ("/chat/completions", "/responses"))


def validate_target(url, *, resolver=None):
    resolver = resolver or socket.getaddrinfo
    try:
        parsed = urlsplit(url)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
                or parsed.port not in (None, 443) or parsed.query or parsed.fragment
                or parsed.path not in _PATHS or "%" in url or "\\" in url
                or len(url) > 350 or any(ord(c) < 33 or ord(c) > 126 for c in url)):
            raise ValueError()
        addresses = sorted({row[4][0] for row in resolver(parsed.hostname, 443, type=socket.SOCK_STREAM)})
        parsed_addresses = [ipaddress.ip_address(address) for address in addresses]
        if not addresses or any(not address.is_global or address.is_multicast or address.is_reserved
                or address.is_unspecified or (isinstance(address, ipaddress.IPv6Address)
                    and (address.sixtofour is not None or address.teredo is not None)) for address in parsed_addresses):
            raise ValueError()
    except (ValueError, OSError, TypeError, IndexError):
        raise PrivateTransportError("Private provider target denied.") from None
    return parsed.hostname, parsed.path, addresses[0]


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host, address, timeout):
        super().__init__(host, port=443, timeout=timeout, context=ssl.create_default_context())
        self._approved_address = address

    def connect(self):
        raw = socket.create_connection((self._approved_address, 443), timeout=self.timeout)
        try:
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
        except BaseException:
            raw.close()
            raise


def request_json(url, *, method="POST", payload=None, headers=None, timeout=60):
    if method != "POST":
        raise PrivateTransportError("Private provider method denied.")
    host, path, address = validate_target(url)
    data = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
    if len(data) > 128 * 1024:
        raise PrivateTransportError("Private provider request too large.")
    connection = _PinnedHTTPSConnection(host, address, max(1, min(int(timeout), 60)))
    try:
        connection.request("POST", path, body=data, headers={"Accept": "application/json",
            "Content-Type": "application/json", **(headers or {})})
        response = connection.getresponse()
        if response.status != 200:
            # Do not inspect or log arbitrary provider error bodies or Location.
            raise PrivateTransportError(f"Private provider HTTP {response.status}.")
        raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise PrivateTransportError("Private provider response too large.")
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise ValueError()
        return result
    except PrivateTransportError:
        raise
    except (OSError, ValueError, http.client.HTTPException):
        raise PrivateTransportError("Private provider unavailable or invalid response.") from None
    finally:
        connection.close()
