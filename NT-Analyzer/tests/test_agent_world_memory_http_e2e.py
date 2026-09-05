"""Real loopback HTTP Memory sharing with synthetic ordinary-session identities.

This is automated integration evidence, NOT live-human/browser acceptance.
Handler cookie/device/CSRF/permission gates, domain_gateway, DomainService and
the SQLite artifact/grant repository are unmodified. Only established identity,
session, membership and entitlement lookup boundaries are disposable fixtures.
No owner identity, provider key, live runtime, external socket or DB is used.
"""
from __future__ import annotations

import copy
import hashlib
import http.client
import json
import socket
import sqlite3
import threading
import time
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from app import account_auth, permissions, runtime_env, server, workspaces
from app.ai_control_center import contracts as c, domain_gateway, live_gateway
from app.ai_control_center.domain_service import DomainService
from app.ai_control_center.events import EventData, EventEnvelope, MutationIdentity
from app.ai_control_center.sqlite_repository import SQLiteAgentWorldRepository
from app.ai_control_center.states import EntityKind


WORKSPACE = "ws_synthetic_memory_shared"
FOREIGN_WORKSPACE = "ws_synthetic_memory_foreign"
PUBLISHER, CONSUMER, FOREIGN = "publisher", "consumer", "foreign"
_GET = object()
_CONNECT = socket.create_connection
_SOCKET_CONNECT = socket.socket.connect
MEMORY_CONTENT = "Synthetic HTTP lesson: preserve the verified report source."
PRIVATE_EVIDENCE = b'{"synthetic_private_evidence":"not published to members"}'


def _payload(**changes):
    return {"title": "Synthetic HTTP Memory", "content": MEMORY_CONTENT,
            "purpose": "report_review", "retention_days": 1, **changes}


def _context(identity, workspace=WORKSPACE):
    user_uuid = UUID(identity["user"]["user_uuid"])
    return c.RequestContext(scope=c.TenantScope(environment=c.Environment.DEVELOPMENT,
                                                workspace_id=workspace),
                            user_uuid=user_uuid,
                            actor=c.ActorRef(kind=c.ActorKind.HUMAN, actor_id=user_uuid))


def _logical_database(path):
    with sqlite3.connect("file:" + path.as_posix() + "?mode=ro", uri=True) as connection:
        return "\n".join(connection.iterdump())


@pytest.fixture
def memory_http(tmp_path, monkeypatch):
    for key, value in {
        "DEPLOYMENT_ENV": "development", "STRATFORGE_ENV": "development",
        "STRATFORGE_DEVELOPMENT_DATA_ROOT": str(tmp_path / "development"),
        "STRATFORGE_DATA_ROOT": str(tmp_path / "production-disabled"),
        "STRATFORGE_CANARY_DATA_ROOT": str(tmp_path / "canary-disabled"),
        "NT_ANALYZER_SQLITE_PATH": str(tmp_path / "auth-admission.sqlite3"),
        "STRATFORGE_PREVIEW_SANDBOX": "0", "STRATFORGE_PREVIEW_ID": "",
        "NTA_ENABLE_TEST_AUTH": "1", "NTA_DISABLE_RATE_LIMIT": "1",
        live_gateway.WORKSPACES_ENV: WORKSPACE + "," + FOREIGN_WORKSPACE,
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(live_gateway, "_SNAPSHOTS", {})

    identities = {}
    for index, name in enumerate((PUBLISHER, CONSUMER, FOREIGN), 1):
        identities[name] = {
            "user": {"user_id": 910100 + index, "user_uuid": str(UUID(int=910100 + index)),
                     "first_name": "Synthetic " + name, "username": "synthetic_memory_" + name,
                     "is_owner": False, "is_service_account": False, "is_preview_user": False,
                     "status": "active", "ux_mode": "professional"},
            "cookie": "synthetic-memory-cookie-" + name,
            "session_id": "synthetic-memory-session-" + name,
            "csrf": "synthetic-memory-csrf-" + name,
            "role": "read_only" if name == CONSUMER else "full_control",
            "workspace": FOREIGN_WORKSPACE if name == FOREIGN else WORKSPACE,
            "membership_role": "viewer" if name == CONSUMER else "owner",
            "session_active": True, "member_active": True, "device_state": "active",
            "return_stale_session": False,
        }
    by_uid = {row["user"]["user_id"]: row for row in identities.values()}
    by_cookie = {row["cookie"]: row for row in identities.values()}
    auth_calls, membership_calls = [], []

    def find_user(uid):
        row = by_uid.get(int(uid or 0))
        return copy.deepcopy(row["user"]) if row else None

    def session_active(session_id, uid):
        row = by_uid.get(int(uid or 0))
        return bool(row and row["session_active"] and row["session_id"] == session_id)

    def authenticate(cookie):
        row = by_cookie.get(cookie)
        auth_calls.append(cookie)
        if row is None or (not row["session_active"] and not row["return_stale_session"]):
            return None
        return {"source": "app", "is_owner": False, "user_id": row["user"]["user_id"],
                "user_uuid": row["user"]["user_uuid"], "user": copy.deepcopy(row["user"]),
                "role": row["role"], "session_id": row["session_id"],
                "csrf_hash": hashlib.sha256(row["csrf"].encode()).hexdigest(),
                "device_confirmation_state": row["device_state"], "device_confirmation_required": False,
                "device_trust_mode": "session"}

    def workspace_for(uid, workspace_id, *, writer=False):
        row = by_uid.get(int(uid or 0))
        membership_calls.append((uid, workspace_id, writer))
        if (not row or not row["member_active"] or row["workspace"] != workspace_id
                or (writer and row["membership_role"] not in workspaces.WRITE_ROLES)):
            raise workspaces.WorkspaceError("Synthetic membership denied", 403)
        owner_name = FOREIGN if workspace_id == FOREIGN_WORKSPACE else PUBLISHER
        return {"workspace_id": workspace_id, "kind": "personal", "status": "active",
                "owner_user_id": identities[owner_name]["user"]["user_id"], "uses_owner_runtime": False,
                "membership": {"workspace_id": workspace_id, "user_id": uid,
                               "role": row["membership_role"]}}

    def workspace_context(uid, **_kwargs):
        row = by_uid[int(uid)]
        # Keep the selected workspace snapshot even when membership is revoked;
        # domain admission must perform the independent fresh membership lookup.
        active = {"workspace_id": row["workspace"], "kind": "personal", "status": "active",
                  "uses_owner_runtime": False,
                  "owner_user_id": identities[FOREIGN if row["workspace"] == FOREIGN_WORKSPACE else PUBLISHER]["user"]["user_id"]}
        member = {"workspace_id": row["workspace"], "user_id": uid, "role": row["membership_role"]}
        return {"workspaces": [active], "active_workspace": active, "active_membership": member,
                "uses_owner_runtime": False}

    def entitlements(uid, _user):
        row = by_uid[int(uid)]
        return {"role": row["role"], "ux_mode": "professional", "capabilities": {"ai_lab": True},
                "admin_capabilities": {key: False for key in permissions.ADMIN_CAPABILITY_IDS}}

    def forbidden_owner(_handler):
        pytest.fail("Synthetic ordinary-user HTTP must not enter localhost owner bypass")

    monkeypatch.setattr(account_auth, "find_active_user", find_user)
    monkeypatch.setattr(account_auth, "authenticate_session", authenticate)
    monkeypatch.setattr(account_auth, "local_session_is_active", session_active)
    monkeypatch.setattr(account_auth, "session_auth_failure", lambda _cookie: {
        "error": "Synthetic test session inactive", "code": "synthetic_session_inactive"})
    monkeypatch.setattr(workspaces, "context_for_user", workspace_context)
    monkeypatch.setattr(workspaces, "require_workspace_access", lambda uid, *, workspace_id: workspace_for(uid, workspace_id))
    monkeypatch.setattr(workspaces, "require_workspace_writer", lambda uid, *, workspace_id: workspace_for(uid, workspace_id, writer=True))
    monkeypatch.setattr(permissions, "resolve_for_user_id", entitlements)
    monkeypatch.setattr(server.Handler, "_local_owner_context", forbidden_owner)

    # No service/DTO/artifact read is stubbed. This is the same file chosen by
    # unmodified domain_gateway.repository for every HTTP request.
    repo = SQLiteAgentWorldRepository(runtime_env.data_path("ai_lab", "agent-world.sqlite3"))
    publisher_context = _context(identities[PUBLISHER])
    private_evidence = repo.put_artifact(context=publisher_context, content=PRIVATE_EVIDENCE,
                                         media_type="application/json")
    monkeypatch.setattr(socket, "getfqdn", lambda _value="": "localhost")
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    address = ("127.0.0.1", httpd.server_address[1])

    def loopback_only(destination, *args, **kwargs):
        assert destination == address, "Only this disposable HTTP listener is allowed"
        return _CONNECT(destination, *args, **kwargs)

    def socket_loopback_only(sock, destination):
        assert destination == address, "External and other local socket connections are forbidden"
        return _SOCKET_CONNECT(sock, destination)

    monkeypatch.setattr(socket, "create_connection", loopback_only)
    monkeypatch.setattr(socket.socket, "connect", socket_loopback_only)
    thread = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
    thread.start()

    def request(name, route, body=_GET, *, csrf="same", cookie=None, query=""):
        row = identities[name]
        path = route if route.startswith("/") else live_gateway.PREFIX + route
        path += query
        headers = {"Cookie": runtime_env.session_cookie_name() + "=" + (row["cookie"] if cookie is None else cookie)}
        if body is not _GET:
            headers.update({"Content-Type": "application/json", "Origin": f"http://{address[0]}:{address[1]}"})
            if csrf is not None:
                headers["X-CSRF-Token"] = row["csrf"] if csrf == "same" else csrf
        connection = http.client.HTTPConnection(*address, timeout=10)
        try:
            connection.request("GET" if body is _GET else "POST", path,
                               body=None if body is _GET else json.dumps(body), headers=headers)
            response = connection.getresponse()
            raw = response.read()
            response_headers = {key.lower(): value for key, value in response.getheaders()}
            data = json.loads(raw) if "application/json" in response_headers.get("content-type", "") else None
            return SimpleNamespace(status=response.status, data=data, raw=raw, headers=response_headers, url=path)
        finally:
            connection.close()

    def mutate(name, item, action, payload, *, key=None, **kwargs):
        return request(name, "domains/memory/" + (item["id"] if item else "new") + "/" + action,
                       {"payload": payload, "expected_revision": item["revision"] if item else None,
                        "idempotency_key": key or "synthetic-memory-" + uuid4().hex}, **kwargs)

    env = SimpleNamespace(request=request, mutate=mutate, identities=identities, repo=repo,
                          publisher_context=publisher_context, private_evidence=private_evidence,
                          auth_calls=auth_calls, membership_calls=membership_calls, root=tmp_path)
    try:
        yield env
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=3)
        assert not thread.is_alive()


def _ok(response):
    assert response.status == 200, (response.status, response.data, response.raw[:200])
    return response.data


def _publish_http(env):
    created = _ok(env.mutate(PUBLISHER, None, "create", _payload(source_ids=[str(env.private_evidence.artifact_id)])))["item"]
    active = _ok(env.mutate(PUBLISHER, created, "promote", {"reason": "Synthetic author explicitly reviewed this note"}))["item"]
    shared = _ok(env.mutate(PUBLISHER, active, "publish_to_workspace", {"reason": "Synthetic author shares only this note"}))["item"]
    return active, shared


def _assert_unavailable(env, shared, known_urls, *, identity=CONSUMER):
    detail = env.request(identity, "domains/memory/" + shared["id"])
    assert detail.status == 409 and detail.data["code"] == "domain_record_not_found", detail.data
    listing = _ok(env.request(identity, "domains/memory"))
    assert shared["id"] not in {item["id"] for item in listing["items"]}
    for url in known_urls:
        response = env.request(identity, url)
        assert response.status == 404 and response.data["code"] == "memory_artifact_not_found", response.data
        assert MEMORY_CONTENT.encode() not in response.raw


def test_two_normal_cookie_sessions_share_only_explicit_published_content(memory_http):
    env = memory_http
    private = _ok(env.mutate(PUBLISHER, None, "create", _payload(source_ids=[str(env.private_evidence.artifact_id)])))["item"]
    assert _ok(env.request(CONSUMER, "domains/memory"))["items"] == []
    hidden = env.request(CONSUMER, "domains/memory/" + private["id"])
    assert hidden.status == 409 and hidden.data["code"] == "domain_record_not_found"
    assert env.request(CONSUMER, private["content_artifact_url"]).status == 404
    assert _ok(env.request(PUBLISHER, private["content_artifact_url"]))["content"] == MEMORY_CONTENT
    active = _ok(env.mutate(PUBLISHER, private, "promote", {"reason": "Synthetic private review reason"}))["item"]
    assert _ok(env.request(CONSUMER, "domains/memory"))["items"] == [], "Promotion alone must not share"
    shared = _ok(env.mutate(PUBLISHER, active, "publish_to_workspace", {"reason": "Synthetic sharing consent"}))["item"]
    read = _ok(env.request(CONSUMER, "domains/memory/" + shared["id"]))
    assert read["content"] == MEMORY_CONTENT and read["visibility"] == "workspace"
    assert read["actions"] == [] and read["owner_user_uuid"] == env.identities[PUBLISHER]["user"]["user_uuid"]
    assert "Synthetic private review reason" not in json.dumps(read)
    assert PRIVATE_EVIDENCE.decode() not in json.dumps(read)
    assert [row["id"] for row in _ok(env.request(CONSUMER, "domains/memory"))["items"]] == [shared["id"]]
    for field in ("content_artifact_url", "verification_artifact_url"):
        response = env.request(CONSUMER, read[field])
        _ok(response)
        assert response.headers["cache-control"] == "private, no-store"
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["content-security-policy"] == "default-src 'none'; sandbox"
        assert response.headers["etag"] == '"' + hashlib.sha256(response.raw).hexdigest() + '"'
    assert _ok(env.request(CONSUMER, read["content_artifact_url"]))["content"] == MEMORY_CONTENT
    assert _ok(env.request(CONSUMER, read["verification_artifact_url"]))["type"] == "workspace_memory_publication"
    assert all(not row["user"]["is_owner"] and not row["user"]["is_preview_user"] for row in env.identities.values())
    assert {env.identities[name]["cookie"] for name in (PUBLISHER, CONSUMER)} <= set(env.auth_calls)


def test_shared_artifact_route_does_not_grant_private_sources_or_private_api(memory_http):
    env = memory_http
    original, shared = _publish_http(env)
    read = _ok(env.request(CONSUMER, "domains/memory/" + shared["id"]))
    original_record = env.repo.get(context=env.publisher_context, kind=EntityKind.MEMORY, entity_id=UUID(original["id"]))
    private_ids = (env.private_evidence.artifact_id, original_record.provenance[0].artifact_id,
                   original_record.verification.artifact_id)
    for artifact_id in private_ids:
        assert env.request(CONSUMER, "artifacts/" + str(artifact_id)).status == 404
        response = env.request(CONSUMER, "memory-artifacts/" + shared["id"] + "/" + str(artifact_id))
        assert response.status == 404 and response.data["code"] == "memory_artifact_not_found"
        assert PRIVATE_EVIDENCE not in response.raw
    assert env.request(CONSUMER, original["content_artifact_url"]).status == 404
    assert _ok(env.request(CONSUMER, read["content_artifact_url"]))["content"] == MEMORY_CONTENT


@pytest.mark.parametrize("action", ["create", "update", "promote", "revoke", "publish_to_workspace"])
@pytest.mark.parametrize("role", ["read_only", "full_control"])
def test_readonly_membership_cannot_mutate_even_with_full_control_session(memory_http, action, role):
    env = memory_http
    _, shared = _publish_http(env)
    _ok(env.request(CONSUMER, "domains/memory/" + shared["id"]))
    env.identities[CONSUMER]["role"] = role
    before = _logical_database(env.repo.path)
    payload = _payload() if action in {"create", "update"} else {"reason": "Synthetic consumer must not gain write authority"}
    result = env.mutate(CONSUMER, None if action == "create" else shared, action, payload)
    assert result.status == 403, result.data
    assert _logical_database(env.repo.path) == before
    assert _ok(env.request(CONSUMER, "domains/memory/" + shared["id"]))["status"] == "active"


def test_published_source_is_immutable_via_http_and_failed_edit_keeps_original_grant(memory_http):
    env = memory_http
    original, shared = _publish_http(env)
    before = _logical_database(env.repo.path)
    result = env.mutate(PUBLISHER, original, "update", _payload(content="Must not replace published content"))
    assert result.status == 409 and result.data["code"] == "finalized_record_immutable", result.data
    assert _logical_database(env.repo.path) == before
    visible = _ok(env.request(CONSUMER, "domains/memory/" + shared["id"]))
    assert visible["content"] == MEMORY_CONTENT
    assert _ok(env.request(CONSUMER, visible["content_artifact_url"]))["content"] == MEMORY_CONTENT


@pytest.mark.parametrize("revocation", ["publication", "source", "source_superseded"])
def test_known_shared_urls_stop_working_after_publication_or_source_changes(memory_http, revocation):
    env = memory_http
    original, shared = _publish_http(env)
    visible = _ok(env.request(CONSUMER, "domains/memory/" + shared["id"]))
    urls = [visible[field] for field in ("content_artifact_url", "verification_artifact_url")]
    for url in urls:
        _ok(env.request(CONSUMER, url))
    if revocation == "source_superseded":
        # Canonical setup transition: active -> superseded changes the source
        # revision while preserving its old content/history. There is no public
        # active-Memory edit API, so do not invent or bypass one for this test.
        record = env.repo.get(context=env.publisher_context, kind=EntityKind.MEMORY, entity_id=UUID(original["id"]))
        changed = replace(record, status="superseded", header=replace(record.header, revision=record.header.revision + 1,
                                                                       updated_at=datetime.now(timezone.utc)))
        event = EventEnvelope(event_id=uuid4(), event_type="stratforge.ai.memory.changed",
                              time=changed.header.updated_at, subject=changed.ref(), actor=env.publisher_context.actor,
                              correlation_id=changed.header.correlation_id, policy=changed.header.policy,
                              data=EventData(references=(changed.header.policy,)))
        mutation = MutationIdentity.for_record(context=env.publisher_context, operation="record.write",
                                               idempotency_key="synthetic-source-revision", record=changed,
                                               expected_revision=record.header.revision, event=event)
        env.repo.commit(context=env.publisher_context, record=changed, expected_revision=record.header.revision,
                        event=event, mutation=mutation)
    else:
        target = shared if revocation == "publication" else original
        assert _ok(env.mutate(PUBLISHER, target, "revoke", {"reason": "Synthetic author withdraws grant"}))["item"]["status"] == "revoked"
    before = _logical_database(env.repo.path)
    _assert_unavailable(env, shared, urls)
    assert _logical_database(env.repo.path) == before, "Read-time denial must not rewrite grant/history"


def test_same_known_urls_expire_by_real_clock_without_get_mutations(memory_http):
    env = memory_http
    row = env.identities[PUBLISHER]
    authorized = domain_gateway.access({"user_id": row["user"]["user_id"], "user_uuid": row["user"]["user_uuid"],
                                        "workspace_id": WORKSPACE, "auth_session_id": row["session_id"]})
    # The existing injected setup clock backdates a normal one-day grant; HTTP
    # readers keep their real unmodified clocks. No sleeps longer than 50 ms.
    expires = datetime.now(timezone.utc) + timedelta(seconds=5)
    created_at = expires - timedelta(days=1)
    service = DomainService(env.repo, now=lambda: created_at)
    original = service.create(context=env.publisher_context, admit=authorized["admit"], domain="memory",
                              payload=_payload(), idempotency_key="synthetic-ttl-create")["item"]
    original = service.act(context=env.publisher_context, admit=authorized["admit"], domain="memory", entity_id=original["id"],
                           action="promote", payload={"reason": "Synthetic expiry fixture"},
                           expected_revision=original["revision"], idempotency_key="synthetic-ttl-promote")["item"]
    shared = service.act(context=env.publisher_context, admit=authorized["admit"], domain="memory", entity_id=original["id"],
                         action="publish_to_workspace", payload={"reason": "Synthetic short-lived grant"},
                         expected_revision=original["revision"], idempotency_key="synthetic-ttl-publish")["item"]
    read = _ok(env.request(CONSUMER, "domains/memory/" + shared["id"]))
    urls = [read[field] for field in ("content_artifact_url", "verification_artifact_url")]
    for url in urls:
        _ok(env.request(CONSUMER, url))
    before = _logical_database(env.repo.path)
    deadline = time.monotonic() + 7
    while datetime.now(timezone.utc) <= expires and time.monotonic() < deadline:
        time.sleep(0.05)
    assert datetime.now(timezone.utc) > expires
    _assert_unavailable(env, shared, urls)
    assert _logical_database(env.repo.path) == before


def test_foreign_workspace_cannot_read_known_shared_ids_or_artifacts(memory_http):
    env = memory_http
    _, shared = _publish_http(env)
    visible = _ok(env.request(CONSUMER, "domains/memory/" + shared["id"]))
    urls = [visible[field] for field in ("content_artifact_url", "verification_artifact_url")]
    before = _logical_database(env.repo.path)
    _assert_unavailable(env, shared, urls, identity=FOREIGN)
    for url in urls:
        denied = env.request(FOREIGN, url, query="?workspace_id=" + WORKSPACE)
        assert denied.status == 404, denied.data
    assert _logical_database(env.repo.path) == before


@pytest.mark.parametrize("mode", ["revoked_session", "stale_session_snapshot", "revoked_membership", "device_pending"])
def test_known_urls_recheck_session_membership_and_device_on_every_request(memory_http, mode):
    env = memory_http
    _, shared = _publish_http(env)
    visible = _ok(env.request(CONSUMER, "domains/memory/" + shared["id"]))
    routes = ["domains/memory/" + shared["id"], visible["content_artifact_url"], visible["verification_artifact_url"]]
    for route in routes:
        _ok(env.request(CONSUMER, route))
    consumer = env.identities[CONSUMER]
    if mode in {"revoked_session", "stale_session_snapshot"}:
        consumer["session_active"] = False
        consumer["return_stale_session"] = mode == "stale_session_snapshot"
    elif mode == "revoked_membership":
        consumer["member_active"] = False
    else:
        consumer["device_state"] = "pending"
    before = _logical_database(env.repo.path)
    for route in routes:
        result = env.request(CONSUMER, route)
        expected = 401 if mode == "revoked_session" else 409 if mode == "stale_session_snapshot" else 403
        assert result.status == expected, (mode, result.data)
        assert MEMORY_CONTENT.encode() not in result.raw and "content_artifact_url" not in (result.data or {})
    assert _logical_database(env.repo.path) == before
    assert _ok(env.request(PUBLISHER, "domains/memory/" + shared["id"]))["status"] == "active"


@pytest.mark.parametrize("csrf", [None, "wrong-csrf", "synthetic-memory-csrf-consumer"])
def test_publisher_mutation_requires_its_own_session_csrf(memory_http, csrf):
    env = memory_http
    original, shared = _publish_http(env)
    before = _logical_database(env.repo.path)
    response = env.mutate(PUBLISHER, original, "revoke", {"reason": "Must not revoke without session CSRF"}, csrf=csrf)
    assert response.status == 403, response.data
    assert _logical_database(env.repo.path) == before
    assert _ok(env.request(CONSUMER, "domains/memory/" + shared["id"]))["content"] == MEMORY_CONTENT


def test_unknown_cookie_is_not_replaced_by_local_owner_on_known_artifact_url(memory_http):
    env = memory_http
    _, shared = _publish_http(env)
    visible = _ok(env.request(CONSUMER, "domains/memory/" + shared["id"]))
    result = env.request(CONSUMER, visible["content_artifact_url"], cookie="unknown-synthetic-session")
    assert result.status == 401 and result.data["code"] == "synthetic_session_inactive"
    assert MEMORY_CONTENT.encode() not in result.raw
