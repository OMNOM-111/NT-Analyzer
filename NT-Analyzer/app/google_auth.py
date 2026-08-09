"""Google OAuth identity provider for StratForge authentication and linking.

Secrets come from environment / DPAPI integrations — never from git:
  NTA_GOOGLE_CLIENT_ID
  NTA_GOOGLE_CLIENT_SECRET
  NTA_GOOGLE_REDIRECT_URI  (optional; defaults to /api/auth/google/callback)

On staging without real Google credentials, ``test_auth`` can bind a fake
Google identity. Production requires real OAuth client credentials.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from . import runtime_env, secure_store


class GoogleAuthError(RuntimeError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = int(status)


_MAGIC = b"STRATFORGE-GOOGLE-OAUTH-DPAPI-1\n"
_STATE_TTL_SEC = 15 * 60
_TOKEN_URL = "https://oauth2.googleapis.com/token"
_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_SCOPES = "openid email profile"


def _root() -> Path:
    return Path(__file__).resolve().parent.parent


def _secrets_path() -> Path:
    return runtime_env.data_path("integrations", "google_oauth.dpapi", project_root=_root())


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _read_secret_file() -> Dict[str, Any]:
    path = _secrets_path()
    if not path.is_file():
        return {}
    try:
        raw = path.read_bytes()
        if not raw.startswith(_MAGIC):
            return {}
        blob = base64_b64decode(raw[len(_MAGIC):])
        plain = secure_store._unprotect(blob)
        doc = json.loads(plain.decode("utf-8"))
        return dict(doc) if isinstance(doc, dict) else {}
    except Exception:
        return {}


def base64_b64decode(data: bytes) -> bytes:
    import base64
    return base64.b64decode(data, validate=True)


def base64_b64encode(data: bytes) -> bytes:
    import base64
    return base64.b64encode(data)


def save_secrets(*, client_id: str, client_secret: str, redirect_uri: str = "") -> Dict[str, Any]:
    """Owner-only helper to persist Google OAuth secrets via DPAPI."""
    cid = str(client_id or "").strip()
    secret = str(client_secret or "").strip()
    if not cid or not secret:
        raise GoogleAuthError("client_id и client_secret обязательны.")
    doc = {
        "client_id": cid,
        "client_secret": secret,
        "redirect_uri": str(redirect_uri or "").strip(),
        "updated_at_utc": _now_iso(),
    }
    payload = json.dumps(doc, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    encrypted = secure_store._protect(payload)
    path = _secrets_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(_MAGIC + base64_b64encode(encrypted))
    os.replace(tmp, path)
    return {"ok": True, "configured": True, "client_id_suffix": cid[-8:] if len(cid) >= 8 else cid}


def credentials() -> Dict[str, str]:
    file_doc = _read_secret_file()
    client_id = str(os.environ.get("NTA_GOOGLE_CLIENT_ID") or file_doc.get("client_id") or "").strip()
    client_secret = str(
        os.environ.get("NTA_GOOGLE_CLIENT_SECRET") or file_doc.get("client_secret") or ""
    ).strip()
    redirect = str(
        os.environ.get("NTA_GOOGLE_REDIRECT_URI") or file_doc.get("redirect_uri") or ""
    ).strip()
    return {
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect,
    }


def is_configured() -> bool:
    creds = credentials()
    return bool(creds["client_id"] and creds["client_secret"])


def status() -> Dict[str, Any]:
    creds = credentials()
    cid = creds["client_id"]
    try:
        redirect = resolve_redirect_uri("") if is_configured() else ""
        redirect_ready = bool(redirect)
        code = "ok" if redirect_ready else "credentials_not_configured"
    except (GoogleAuthError, runtime_env.RuntimeEnvError):
        redirect = ""
        redirect_ready = False
        code = "redirect_uri_invalid"
    return {
        "configured": bool(is_configured() and redirect_ready),
        "credentials_configured": is_configured(),
        "client_id_suffix": (cid[-8:] if len(cid) >= 8 else cid) if cid else "",
        "redirect_uri": redirect,
        "redirect_ready": redirect_ready,
        "code": code,
        "staging": runtime_env.is_staging(),
        "test_auth_fallback": runtime_env.test_auth_enabled() and not is_configured(),
    }


def _valid_absolute_redirect(value: Any) -> str:
    raw = str(value or "").strip()
    try:
        parsed = urllib.parse.urlsplit(raw)
        _ = parsed.port
    except (TypeError, ValueError):
        return ""
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path != "/api/auth/google/callback"
    ):
        return ""
    host = str(parsed.hostname or "").lower().rstrip(".")
    port = f":{parsed.port}" if parsed.port else ""
    return f"{parsed.scheme}://{host}{port}{parsed.path}"


def resolve_redirect_uri(requested: Any = "") -> str:
    """Resolve one canonical callback, never trusting request headers remotely."""
    creds = credentials()
    configured = _valid_absolute_redirect(creds.get("redirect_uri"))
    public_origin = str(runtime_env.deployment_config(strict=False).public_origin or "").rstrip("/")
    canonical = _valid_absolute_redirect(f"{public_origin}/api/auth/google/callback")
    if not runtime_env.is_development():
        if not canonical or not canonical.startswith("https://"):
            raise GoogleAuthError("Canonical Google redirect URI не настроен.", 503)
        if creds.get("redirect_uri") and configured != canonical:
            raise GoogleAuthError(
                "NTA_GOOGLE_REDIRECT_URI не совпадает со STRATFORGE_PUBLIC_ORIGIN.", 503,
            )
        return canonical
    candidate = configured or _valid_absolute_redirect(requested) or canonical
    if not candidate:
        raise GoogleAuthError("redirect_uri не задан или некорректен.", 503)
    return candidate


def _state_key() -> bytes:
    creds = credentials()
    material = str(
        os.environ.get("NTA_GOOGLE_STATE_SECRET") or creds.get("client_secret") or ""
    ).encode("utf-8")
    if not material:
        raise GoogleAuthError("Google OAuth signing secret не настроен.", 503)
    return hashlib.sha256(b"StratForge/google-oauth-state/v1\x00" + material).digest()


def _b64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    raw = str(value or "").encode("ascii", errors="strict")
    return base64.urlsafe_b64decode(raw + b"=" * (-len(raw) % 4))


def _encode_state(row: Dict[str, Any]) -> str:
    payload = json.dumps(
        row, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    encoded = _b64url_encode(payload)
    signature = _b64url_encode(hmac.new(_state_key(), encoded.encode("ascii"), hashlib.sha256).digest())
    return f"v1.{encoded}.{signature}"


def _decode_state(value: Any) -> Dict[str, Any]:
    state = str(value or "").strip()
    try:
        version, encoded, supplied_signature = state.split(".", 2)
        if version != "v1" or len(state) > 2048:
            raise ValueError
        expected_signature = _b64url_encode(
            hmac.new(_state_key(), encoded.encode("ascii"), hashlib.sha256).digest()
        )
        if not hmac.compare_digest(supplied_signature, expected_signature):
            raise ValueError
        row = json.loads(_b64url_decode(encoded).decode("utf-8"))
    except (ValueError, UnicodeError, json.JSONDecodeError, base64.binascii.Error):
        raise GoogleAuthError("OAuth state недействителен. Начните вход через Google заново.", 410) from None
    if not isinstance(row, dict) or int(row.get("exp") or 0) <= int(time.time()):
        raise GoogleAuthError("OAuth state истёк. Начните вход через Google заново.", 410)
    if str(row.get("purpose") or "") not in {"login", "link"}:
        raise GoogleAuthError("OAuth state содержит неверную цель.", 410)
    if resolve_redirect_uri(row.get("redirect_uri")) != str(row.get("redirect_uri") or ""):
        raise GoogleAuthError("OAuth redirect URI изменился. Начните вход заново.", 410)
    return row


def state_cookie_token(state: Any) -> str:
    """Bind a signed state to the browser that initiated the login flow."""
    value = str(state or "").strip()
    if not value:
        return ""
    return hashlib.sha256(("StratForge/google-state-cookie/v1\x00" + value).encode("utf-8")).hexdigest()


def state_cookie_matches(state: Any, supplied_token: Any) -> bool:
    expected = state_cookie_token(state)
    supplied = str(supplied_token or "").strip().lower()
    return bool(expected and len(supplied) == len(expected) and hmac.compare_digest(expected, supplied))


def _safe_return_path(value: Any) -> str:
    """Keep OAuth redirects on the local Aurora UI and reject open redirects."""
    raw = str(value or "/ui/").strip()
    try:
        parsed = urllib.parse.urlsplit(raw)
    except ValueError:
        return "/ui/"
    if parsed.scheme or parsed.netloc or parsed.fragment:
        return "/ui/"
    if parsed.path != "/ui" and not parsed.path.startswith("/ui/"):
        return "/ui/"
    if any(ord(ch) < 32 for ch in raw):
        return "/ui/"
    return urllib.parse.urlunsplit(("", "", parsed.path or "/ui/", parsed.query, ""))


def _start(
    *, purpose: str, user_id: int, redirect_uri: str,
    return_path: str = "", accept_terms: bool = False,
) -> Dict[str, Any]:
    purpose_id = str(purpose or "").strip().lower()
    if purpose_id not in {"link", "login"}:
        raise GoogleAuthError("Некорректная цель Google OAuth.")
    if purpose_id == "link" and int(user_id or 0) <= 0:
        raise GoogleAuthError("Для привязки Google требуется активная сессия.", 401)
    if not is_configured():
        if runtime_env.test_auth_enabled():
            raise GoogleAuthError(
                "Google OAuth не настроен. В Development используйте явный test-auth endpoint.",
                503,
            )
        raise GoogleAuthError(
            "Google OAuth не настроен. Задайте NTA_GOOGLE_CLIENT_ID / SECRET (или DPAPI store).",
            503,
        )
    creds = credentials()
    uri = resolve_redirect_uri(redirect_uri)
    state = _encode_state({
        "user_id": int(user_id),
        "purpose": purpose_id,
        "accept_terms": bool(accept_terms),
        "redirect_uri": uri,
        "return_path": _safe_return_path(return_path)[:200],
        "exp": int(time.time()) + _STATE_TTL_SEC,
        "nonce": secrets.token_urlsafe(16),
    })
    params = {
        "client_id": creds["client_id"],
        "redirect_uri": uri,
        "response_type": "code",
        "scope": _SCOPES,
        "state": state,
        "access_type": "online",
        "prompt": "select_account consent",
        "include_granted_scopes": "true",
    }
    return {
        "ok": True,
        "state": state,
        "auth_url": f"{_AUTH_URL}?{urllib.parse.urlencode(params)}",
        "expires_in_sec": _STATE_TTL_SEC,
    }


def start_link(*, user_id: int, redirect_uri: str, return_path: str = "") -> Dict[str, Any]:
    """Begin Google OAuth for an already authenticated user."""
    return _start(
        purpose="link", user_id=int(user_id), redirect_uri=redirect_uri,
        return_path=return_path,
    )


def start_login(
    *, redirect_uri: str, return_path: str = "", accept_terms: bool = False,
) -> Dict[str, Any]:
    """Begin Google OAuth as a first-login provider."""
    return _start(
        purpose="login", user_id=0, redirect_uri=redirect_uri,
        return_path=return_path, accept_terms=accept_terms,
    )


def _http_json(url: str, *, data: Optional[Dict[str, str]] = None, bearer: str = "") -> Dict[str, Any]:
    headers = {"Accept": "application/json", "User-Agent": "StratForge/1.0"}
    body = None
    if data is not None:
        body = urllib.parse.urlencode(data).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    req = urllib.request.Request(url, data=body, headers=headers, method="POST" if body else "GET")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8")[:300]
        except Exception:
            pass
        raise GoogleAuthError(f"Google OAuth ошибка HTTP {exc.code}: {detail or exc.reason}", 502) from None
    except urllib.error.URLError as exc:
        raise GoogleAuthError(f"Не удалось связаться с Google: {exc.reason}", 502) from None
    try:
        parsed = json.loads(raw)
    except ValueError as exc:
        raise GoogleAuthError("Некорректный ответ Google OAuth.", 502) from exc
    if not isinstance(parsed, dict):
        raise GoogleAuthError("Некорректный ответ Google OAuth.", 502)
    return parsed


def exchange_code(*, code: str, state: str) -> Dict[str, Any]:
    """Exchange a one-use code and return identity plus the signed OAuth intent."""
    code = str(code or "").strip()
    state = str(state or "").strip()
    if not code or not state:
        raise GoogleAuthError("code и state обязательны.")
    row = _decode_state(state)
    creds = credentials()
    token_doc = _http_json(
        _TOKEN_URL,
        data={
            "code": code,
            "client_id": creds["client_id"],
            "client_secret": creds["client_secret"],
            "redirect_uri": str(row.get("redirect_uri") or ""),
            "grant_type": "authorization_code",
        },
    )
    access = str(token_doc.get("access_token") or "")
    if not access:
        raise GoogleAuthError("Google не вернул access_token.", 502)
    info = _http_json(_USERINFO_URL, bearer=access)
    google_sub = str(info.get("sub") or "").strip()
    email = str(info.get("email") or "").strip().lower()
    if not google_sub:
        raise GoogleAuthError("Google не вернул идентификатор пользователя (sub).", 502)
    if info.get("email_verified") is not True or not email or "@" not in email:
        raise GoogleAuthError("Email Google не подтверждён. Используйте другой аккаунт.", 403)
    return {
        "ok": True,
        "purpose": str(row.get("purpose") or "link"),
        "user_id": int(row.get("user_id") or 0),
        "accept_terms": bool(row.get("accept_terms")),
        "google_sub": google_sub,
        "google_email": email,
        "google_name": str(info.get("name") or ""),
        "google_picture": str(info.get("picture") or ""),
        "return_path": _safe_return_path(row.get("return_path")),
        "email_verified": True,
    }


def fake_identity(*, google_sub: str = "", email: str = "") -> Dict[str, str]:
    """Staging-only identity for test_auth linking."""
    runtime_env.require_test_auth()
    sub = str(google_sub or "").strip() or f"test-google-{secrets.token_hex(8)}"
    mail = str(email or "").strip().lower() or f"{sub}@staging.stratforge.local"
    return {
        "google_sub": sub,
        "google_email": mail,
        "google_name": "Staging Google User",
        "google_picture": "",
    }


def identity_fingerprint(google_sub: str) -> str:
    return hashlib.sha256(str(google_sub or "").encode("utf-8")).hexdigest()
