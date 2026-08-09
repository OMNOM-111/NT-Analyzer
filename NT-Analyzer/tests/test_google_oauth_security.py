from __future__ import annotations

from types import SimpleNamespace

import pytest

from app import google_auth, server


def _google_env(monkeypatch) -> None:
    monkeypatch.setenv("NTA_APP_ENV", "staging")
    monkeypatch.setenv("NTA_GOOGLE_CLIENT_ID", "client.apps.googleusercontent.com")
    monkeypatch.setenv("NTA_GOOGLE_CLIENT_SECRET", "google-client-secret")
    monkeypatch.setenv(
        "NTA_GOOGLE_REDIRECT_URI",
        "http://127.0.0.1:8123/api/auth/google/callback",
    )


def test_oauth_state_is_signed_self_contained_and_tamper_evident(monkeypatch) -> None:
    _google_env(monkeypatch)
    started = google_auth.start_login(
        redirect_uri="http://attacker.test/api/auth/google/callback",
        return_path="/ui/cabinet?tab=security",
        accept_terms=True,
    )
    row = google_auth._decode_state(started["state"])
    assert row["purpose"] == "login"
    assert row["accept_terms"] is True
    assert row["return_path"] == "/ui/cabinet?tab=security"
    assert row["redirect_uri"] == "http://127.0.0.1:8123/api/auth/google/callback"

    replacement = "A" if started["state"][-1] != "A" else "B"
    with pytest.raises(google_auth.GoogleAuthError) as exc:
        google_auth._decode_state(started["state"][:-1] + replacement)
    assert exc.value.status == 410

    browser_token = google_auth.state_cookie_token(started["state"])
    assert google_auth.state_cookie_matches(started["state"], browser_token) is True
    assert google_auth.state_cookie_matches(started["state"] + "x", browser_token) is False


def test_google_userinfo_requires_explicit_verified_email(monkeypatch) -> None:
    _google_env(monkeypatch)
    started = google_auth.start_login(
        redirect_uri="", return_path="/ui/", accept_terms=True,
    )

    def http_json(url, **_kwargs):
        if url == google_auth._TOKEN_URL:
            return {"access_token": "access"}
        return {"sub": "google-42", "email": "person@example.test"}

    monkeypatch.setattr(google_auth, "_http_json", http_json)
    with pytest.raises(google_auth.GoogleAuthError) as exc:
        google_auth.exchange_code(code="authorization-code", state=started["state"])
    assert exc.value.status == 403

    def verified_http_json(url, **_kwargs):
        if url == google_auth._TOKEN_URL:
            return {"access_token": "access"}
        return {
            "sub": "google-42",
            "email": "person@example.test",
            "email_verified": True,
        }

    monkeypatch.setattr(google_auth, "_http_json", verified_http_json)
    identity = google_auth.exchange_code(code="authorization-code-2", state=started["state"])
    assert identity["email_verified"] is True
    assert identity["google_sub"] == "google-42"


def test_remote_redirect_uses_canonical_public_origin(monkeypatch) -> None:
    monkeypatch.setenv("NTA_GOOGLE_CLIENT_ID", "client.apps.googleusercontent.com")
    monkeypatch.setenv("NTA_GOOGLE_CLIENT_SECRET", "google-client-secret")
    monkeypatch.delenv("NTA_GOOGLE_REDIRECT_URI", raising=False)
    monkeypatch.setattr(google_auth.runtime_env, "is_development", lambda: False)
    monkeypatch.setattr(
        google_auth.runtime_env,
        "deployment_config",
        lambda strict=False: SimpleNamespace(public_origin="https://app.stratforges.com"),
    )

    assert google_auth.resolve_redirect_uri(
        "https://attacker.test/api/auth/google/callback"
    ) == "https://app.stratforges.com/api/auth/google/callback"


def test_server_oauth_cookie_is_http_only_lax_and_callback_scoped(monkeypatch) -> None:
    handler = object.__new__(server.Handler)
    handler.headers = {}
    handler._extra_headers = []
    monkeypatch.setattr(handler, "_is_remote_api_request", lambda: True)
    monkeypatch.setattr(server.runtime_env, "session_cookie_name", lambda: "sf_production_session")

    handler._set_google_oauth_cookie("signed-state")

    name, value = handler._extra_headers[-1]
    assert name == "Set-Cookie"
    assert value.startswith("sf_production_session_google_oauth=")
    assert "Path=/api/auth/google/callback" in value
    assert "HttpOnly" in value
    assert "SameSite=Lax" in value
    assert "Secure" in value
    assert "signed-state" not in value
