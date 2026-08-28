from __future__ import annotations

import hashlib
from contextlib import contextmanager
from decimal import Decimal

from app import account_auth, permissions, server as server_mod
from app import production_storage


class _Cursor:
    def __init__(self, *, one=None, rows=None):
        self._one = one
        self._rows = list(rows or [])

    def fetchone(self):
        return self._one

    def fetchall(self):
        return list(self._rows)


class _Connection:
    def __init__(self, *, one=None, rows=None):
        self.one = one
        self.rows = list(rows or [])
        self.calls = []

    def execute(self, sql, params=()):
        self.calls.append((" ".join(str(sql).split()), tuple(params)))
        return _Cursor(one=self.one, rows=self.rows)


class _Client:
    def __init__(self, connection):
        self.connection = connection
        self.transactions = []

    @contextmanager
    def transaction(self, scope, *, read_only=False):
        self.transactions.append((scope, read_only))
        yield self.connection


def test_authoritative_session_lookup_is_one_fresh_relational_read(monkeypatch) -> None:
    raw = "s" * 48
    digest = hashlib.sha256(raw.encode()).hexdigest()
    row = {
        "session_id": "sess_relational",
        "user_id": 999,
        "user_uuid": "70de0735-01ea-4e94-bace-83a7d9ef556c",
        "expires_at_epoch": 2_000_000_000,
        "session_document": {
            "session_id": "sess_relational", "user_id": 999,
            "source": "telegram_login", "device_id": "dev_1",
            "csrf_hash": "hash", "csrf_token": "csrf",
            "nt_elevated_until": 0,
        },
        "canonical_user_uuid": "70de0735-01ea-4e94-bace-83a7d9ef556c",
        "user_status": "active",
        "is_owner": True,
        "user_document": {
            "user_id": 999, "status": "active", "is_owner": True,
            "role": "owner", "first_name": "Owner", "ux_mode": "professional",
        },
    }
    connection = _Connection(one=row)
    client = _Client(connection)
    monkeypatch.setattr(account_auth, "_authoritative_storage", lambda: True)
    monkeypatch.setattr(production_storage, "get_client", lambda **_kwargs: client)
    monkeypatch.setattr(
        account_auth, "_read_doc",
        lambda: (_ for _ in ()).throw(AssertionError("full auth document must not load")),
    )

    context = account_auth.authenticate_session(raw)

    assert context and context["user_id"] == 999
    assert context["user_uuid"] == row["canonical_user_uuid"]
    assert context["is_owner"] is True
    assert len(client.transactions) == 1
    assert client.transactions[0][1] is True
    assert len(connection.calls) == 1
    sql, params = connection.calls[0]
    assert "FROM sf_auth_sessions AS s" in sql
    assert "s.revoked=FALSE" in sql
    assert "s.expires_at > clock_timestamp()" in sql
    assert "u.status='active'" in sql
    assert params == (digest,)


def test_authoritative_session_rejection_never_falls_back_to_document(monkeypatch) -> None:
    connection = _Connection(one=None)
    client = _Client(connection)
    monkeypatch.setattr(account_auth, "_authoritative_storage", lambda: True)
    monkeypatch.setattr(production_storage, "get_client", lambda **_kwargs: client)
    monkeypatch.setattr(
        account_auth, "_read_doc",
        lambda: (_ for _ in ()).throw(AssertionError("revoked session must fail closed")),
    )
    assert account_auth.authenticate_session("x" * 48) is None
    assert len(connection.calls) == 1


def test_owner_permissions_skip_entitlement_repository(monkeypatch) -> None:
    monkeypatch.setattr(
        permissions.subscriptions, "active_entitlement",
        lambda _user_id: (_ for _ in ()).throw(
            AssertionError("owner entitlement must not load")
        ),
    )
    resolved = permissions.resolve_for_user_id(
        999, {"user_id": 999, "is_owner": True, "role": "owner"},
    )
    assert resolved["is_owner"] is True
    assert all(resolved["capabilities"].values())


def test_http_json_safe_normalizes_postgresql_decimal_values() -> None:
    handler = object.__new__(server_mod.Handler)
    payload = handler._json_safe({
        "integer": Decimal("12"),
        "fraction": Decimal("12.50"),
        "nan": Decimal("NaN"),
        "infinity": Decimal("Infinity"),
    })
    assert payload == {
        "integer": 12, "fraction": 12.5, "nan": None, "infinity": None,
    }
