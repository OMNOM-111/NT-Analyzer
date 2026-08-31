"""Pre-auth access to the official public legal documents.

A visitor must be able to read every legal document the registration screen
links to before accepting the agreement, while owner-only and internal files
stay invisible to anonymous visitors and ordinary authenticated users alike.
"""
from __future__ import annotations

import hashlib
import json
import threading
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from app import account_auth, community, google_auth, governance, practice_trading, subscriptions, workspaces
from app import server as server_mod


@pytest.fixture()
def legal_store(tmp_path, monkeypatch):
    monkeypatch.setenv("NTA_TELEGRAM_CHAT_ID", "999")
    monkeypatch.setenv("NTA_APP_ENV", "staging")
    monkeypatch.setenv("NTA_DUAL_AUTH_REQUIRED", "1")
    monkeypatch.delenv("NTA_TEST_BYPASS_AUTH", raising=False)
    for module in (account_auth, google_auth, practice_trading, community, subscriptions, workspaces):
        monkeypatch.setattr(module, "_root", lambda: tmp_path)
    monkeypatch.setattr(account_auth.secure_store, "_protect", lambda b: b)
    monkeypatch.setattr(account_auth.secure_store, "_unprotect", lambda b: b)
    monkeypatch.setattr(account_auth.secure_store, "available", lambda: True)
    monkeypatch.setattr(subscriptions.secure_store, "_protect", lambda b: b)
    monkeypatch.setattr(subscriptions.secure_store, "_unprotect", lambda b: b)
    monkeypatch.setattr(subscriptions.secure_store, "available", lambda: True)
    monkeypatch.setattr(workspaces.secure_store, "_protect", lambda b: b)
    monkeypatch.setattr(workspaces.secure_store, "_unprotect", lambda b: b)
    (tmp_path / "data" / "integrations").mkdir(parents=True)
    (tmp_path / "data" / "audit").mkdir(parents=True)
    (tmp_path / "data" / "runtime").mkdir(parents=True)
    account_auth._write_doc({
        "version": 1,
        "users": [
            {
                "user_id": 999, "username": "owner", "first_name": "Owner",
                "role": "owner", "status": "active", "is_owner": True,
            },
            {
                "user_id": 4242, "username": "visitor", "first_name": "Visitor",
                "role": "user", "status": "active", "is_owner": False,
                "ux_mode": "beginner",
            },
        ],
        "challenges": [],
        "sessions": [],
    })
    account_auth.set_auth_required(True)
    return tmp_path


@pytest.fixture()
def http_server(legal_store, monkeypatch):
    monkeypatch.setenv("NTA_DISABLE_RATE_LIMIT", "1")
    server = ThreadingHTTPServer(("127.0.0.1", 0), server_mod.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    yield base
    server.shutdown()


@pytest.fixture()
def user_token(legal_store):
    """An ordinary authenticated non-owner session."""
    token, csrf = "u" * 64, "c" * 48
    with account_auth._LOCK:
        doc = account_auth._read_doc()
        doc["sessions"].append({
            "session_id": "sess_visitor",
            "token_hash": hashlib.sha256(token.encode()).hexdigest(),
            "csrf_hash": hashlib.sha256(csrf.encode()).hexdigest(),
            "csrf_token": csrf,
            "user_id": 4242,
            "created_at_utc": "2026-07-15T00:00:00Z",
            "expires_at": 4_000_000_000,
            "revoked": False,
            "device_id": "dev",
            "client": "Chrome",
            "machine": "PC",
            "ip": "127.0.0.1",
        })
        account_auth._write_doc(doc)
    return token


def _get(base: str, path: str, *, token: str = ""):
    headers = {"Origin": base}
    if token:
        headers["Cookie"] = f"{account_auth.SESSION_COOKIE}={token}"
    req = urllib.request.Request(base + path, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            payload = {"error": raw}
        return exc.code, payload


# The identifiers a visitor must never be able to reach, in the shapes an
# attacker would actually try: bare name, registry-style slug, filename, and
# percent-encoded traversal into the legal directory.
FORBIDDEN_IDS = (
    "OWNER_LEGAL_CONFIGURATION",
    "owner-legal-configuration",
    "OWNER_LEGAL_CONFIGURATION.md",
    "legal-owner",
    "legal%2FOWNER_LEGAL_CONFIGURATION.md",
    "..%2Flegal%2FOWNER_LEGAL_CONFIGURATION.md",
    "..%2F..%2FAGENTS.md",
    "%2Fetc%2Fpasswd",
    "docs%2Flegal%2F01_TERMS_OF_SERVICE_EULA.md",
)


def test_allowlist_covers_published_user_facing_legal_documents() -> None:
    allowed = governance.public_legal_document_ids()
    assert allowed, "the registration screen needs at least one public legal document"
    for doc_id in allowed:
        item = governance._document_by_id(doc_id)
        assert item is not None
        assert str(item.get("category")).lower() == "legal"
        assert str(item.get("audience")).lower() == "user"
        assert not item.get("draft")


def test_allowlist_excludes_owner_and_internal_documents() -> None:
    allowed = governance.public_legal_document_ids()
    for doc_id in allowed:
        assert "owner" not in doc_id.lower()
    serialized = json.dumps(governance.public_legal_index(), ensure_ascii=False)
    assert "OWNER_LEGAL_CONFIGURATION" not in serialized


def test_public_index_is_readable_without_authentication(http_server) -> None:
    status, payload = _get(http_server, "/api/legal/documents")
    assert status == 200
    listed = {row["id"] for row in payload["documents"]}
    assert listed == set(governance.public_legal_document_ids())
    # No filesystem or owner metadata may leak into the pre-auth listing.
    serialized = json.dumps(payload, ensure_ascii=False)
    for leaked in ("abs_path", "rel_path", "path", "OWNER_LEGAL_CONFIGURATION"):
        assert leaked not in serialized


def test_every_public_legal_document_opens_before_authentication(http_server) -> None:
    _, index = _get(http_server, "/api/legal/documents")
    ids = [row["id"] for row in index["documents"]]
    assert ids, "empty allowlist would silently pass this test"
    for doc_id in ids:
        status, payload = _get(http_server, f"/api/legal/documents/{doc_id}")
        assert status == 200, f"{doc_id} must open on the registration screen"
        document = payload["document"]
        assert document["id"] == doc_id
        assert document["content"].strip(), f"{doc_id} returned empty content"
        assert "abs_path" not in document
        assert "rel_path" not in document


def test_owner_and_internal_documents_stay_hidden_from_anonymous(http_server) -> None:
    for candidate in FORBIDDEN_IDS:
        status, payload = _get(http_server, f"/api/legal/documents/{candidate}")
        assert status == 404, f"{candidate} must not be reachable pre-auth"
        assert "OWNER_LEGAL_CONFIGURATION" not in json.dumps(payload, ensure_ascii=False)


def test_owner_and_internal_documents_stay_hidden_from_ordinary_user(
    http_server, user_token,
) -> None:
    for candidate in FORBIDDEN_IDS:
        status, _ = _get(http_server, f"/api/legal/documents/{candidate}", token=user_token)
        assert status == 404, f"{candidate} must stay hidden from a normal account"
        for api in ("/api/governance/documents", "/api/documents"):
            status, payload = _get(http_server, f"{api}/{candidate}", token=user_token)
            # The privileged APIs deny an ordinary account before they resolve
            # the identifier: 403 refuses the endpoint outright, 404 refuses the
            # document. Either way nothing about the file may come back.
            assert status in {403, 404}
            assert "OWNER_LEGAL_CONFIGURATION" not in json.dumps(payload, ensure_ascii=False)


def test_public_reader_never_takes_a_path_from_the_caller() -> None:
    """The reader resolves IDs through the registry, never through the request."""
    for candidate in FORBIDDEN_IDS:
        assert governance.read_public_legal_document(candidate) is None
        assert governance.read_public_legal_document(urllib.parse.unquote(candidate)) is None
    assert governance.read_public_legal_document("") is None
    assert governance.read_public_legal_document("   ") is None


def test_every_registration_screen_link_is_publicly_openable(http_server) -> None:
    """The blocker this suite exists for: a link the visitor cannot open.

    Each notice advertised by the pre-auth terms payload must resolve through
    the public route, or the registration screen offers a dead link again.
    """
    from app import legal

    status, terms = _get(http_server, "/api/legal/terms")
    assert status == 200
    notices = terms["notices"]
    assert notices
    assert {row["id"] for row in notices} <= set(governance.public_legal_document_ids())
    for notice in notices:
        status, payload = _get(http_server, f"/api/legal/documents/{notice['id']}")
        assert status == 200, f"{notice['id']} ({notice['label']}) must open pre-auth"
        assert payload["document"]["content"].strip()
    assert {row["id"] for row in legal.TERMS_NOTICES} == {row["id"] for row in notices}


def test_stale_environment_registry_cannot_unpublish_the_package(monkeypatch) -> None:
    """A per-environment registry must not break the registration screen.

    Canary carried a legacy registry in which the legal package was still
    DRAFT, which emptied the pre-auth listing and left the visitor unable to
    open the documents the agreement links to.
    """
    stale = {
        "documents": [
            {**row, "draft": True, "audience": "owner"}
            for row in governance.load_documents_registry()["documents"]
        ],
    }
    monkeypatch.setattr(governance, "load_documents_registry", lambda: stale)
    monkeypatch.setattr(governance, "list_documents", lambda: stale["documents"])
    assert governance.public_legal_document_ids()
    assert governance.public_legal_index()
    assert governance.read_public_legal_document("legal-02")["content"].strip()


def test_environment_registry_cannot_redirect_a_public_document(monkeypatch) -> None:
    """An overridden path must never become readable before authentication."""
    hijacked = {
        "documents": [
            {**row, "path": "secrets.example.env"} if str(row.get("id")) == "legal-02" else row
            for row in governance.load_documents_registry()["documents"]
        ],
    }
    monkeypatch.setattr(governance, "load_documents_registry", lambda: hijacked)
    monkeypatch.setattr(governance, "list_documents", lambda: hijacked["documents"])
    document = governance.read_public_legal_document("legal-02")
    assert "path" not in document
    assert "Политика конфиденциальности" in document["title"]


def test_artifact_ships_public_legal_package_without_the_owner_file() -> None:
    import importlib.util
    from pathlib import Path

    root = Path(governance.__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(
        "build_server_release", root / "tools" / "build_server_release.py",
    )
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)

    assert "docs/legal" in builder._INCLUDED_TREES, (
        "an artifact without docs/legal cannot serve the registration documents"
    )
    assert "docs/legal/OWNER_LEGAL_CONFIGURATION.md" in builder._EXCLUDED_FILES

    selected = {path.as_posix() for path in builder._selected_files(root)}
    assert "docs/legal/OWNER_LEGAL_CONFIGURATION.md" not in selected
    for doc_id in governance.public_legal_document_ids():
        row = next(r for r in governance.DEFAULT_DOCUMENTS["documents"] if r["id"] == doc_id)
        assert row["path"] in selected, f"{doc_id} is not shipped in the artifact"
