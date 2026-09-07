"""NEW Agent World PG acceptance, not the historical 41 relational tests.

Opt-in requires a NEW disposable loopback database (aw_disposable_*), separate
explicit URLs, and an application role that is neither owner nor BYPASSRLS.
No ordinary project/Production database variables are read. Missing opt-in is
SKIPPED, never evidence of PostgreSQL acceptance. Auth/membership admission is
upstream: these tests exercise repository contracts and actual database RLS.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import fields, is_dataclass, replace
from datetime import datetime, timedelta, timezone
import json
import os
import re
from threading import Barrier
from urllib.parse import urlparse
from uuid import UUID, uuid4

import pytest

from app.ai_control_center import contracts as c
from app.ai_control_center.events import EventData, EventEnvelope, MutationIdentity
from app.ai_control_center.postgres_repository import PostgresAgentWorldRepository, _TABLES
from app.ai_control_center.repositories import PageRequest
from app.ai_control_center.states import ContractError, EntityKind
from app.ai_control_center.storage_codec import encode_record
from app.production_storage.core import PostgresClient, Scope, StorageConstraintError
from tests import test_agent_world_storage as parity
from tests.test_agent_world_storage import arguments, artifact, context, memory, persona, update
from tests.test_agent_world_contracts import record as example_record


@pytest.fixture(scope="module")
def database():
    if os.environ.get("STRATFORGE_TEST_AGENT_WORLD_POSTGRES_ALLOW") != "1":
        pytest.skip("New disposable Agent World PostgreSQL acceptance not configured")
    app_url = os.environ.get("STRATFORGE_TEST_AGENT_WORLD_POSTGRES_URL", "")
    admin_url = os.environ.get("STRATFORGE_TEST_AGENT_WORLD_POSTGRES_ADMIN_URL", "")
    for url in (app_url, admin_url):
        parsed = urlparse(url)
        if (parsed.scheme != "postgresql" or parsed.hostname != "127.0.0.1" or not parsed.port
                or not re.fullmatch(r"/aw_disposable_[a-z0-9]{8,32}", parsed.path)):
            pytest.fail("Refusing non-disposable or non-loopback PostgreSQL acceptance target")
    left, right = urlparse(app_url), urlparse(admin_url)
    assert (left.hostname, left.port, left.path) == (right.hostname, right.port, right.path)
    assert left.username == "stratforge_app" and right.username != left.username
    app, admin = PostgresClient(app_url), PostgresClient(admin_url)
    with app.transaction(Scope.workspace_scope("ws_example01"), read_only=True) as conn:
        role = conn.execute("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user").fetchone()
        assert not role["rolsuper"] and not role["rolbypassrls"]
        assert conn.execute("SELECT count(*) AS n FROM pg_tables WHERE schemaname='public' AND tableowner=current_user").fetchone()["n"] == 0
    with admin.transaction(Scope.global_service_scope(), read_only=True) as conn:
        assert conn.execute("SELECT max(version) AS version FROM sf_schema_migrations").fetchone()["version"] == 23
    return app, admin


@pytest.fixture
def repo(database):
    app, admin = database
    # Exact NEW disposable tables only, outside RLS because TRUNCATE is a schema
    # owner fixture operation. No TRUNCATE privilege is granted to the app role.
    with admin.transaction(Scope.global_service_scope()) as conn:
        conn.execute("TRUNCATE " + ",".join(_TABLES) + " RESTART IDENTITY")
    return PostgresAgentWorldRepository(app, environment=c.Environment.DEVELOPMENT)


@contextmanager
def raw(client, ctx=None, *, missing=None, read_only=False):
    ctx = ctx or context()
    with client.transaction(Scope.workspace_scope(ctx.scope.workspace_id), read_only=read_only) as conn:
        values = {"stratforge.aw_user_uuid": str(ctx.user_uuid),
                  "stratforge.aw_environment": ctx.scope.environment.value,
                  "stratforge.aw_memory_read_id": ""}
        if missing:
            values[missing] = ""
        for name, value in values.items():
            conn.execute("SELECT set_config(%s,%s,true)", (name, value))
        yield conn


def counts(repo):
    with raw(repo.client, read_only=True) as conn:
        return {table: conn.execute(f"SELECT count(*) AS n FROM {table}").fetchone()["n"] for table in _TABLES}


def test_constructor_does_no_database_io_ddl_or_fallback(monkeypatch):
    monkeypatch.setenv("STRATFORGE_ALLOW_INSECURE_LOCAL_POSTGRES", "1")
    client = PostgresClient("postgresql://stratforge_app@127.0.0.1:1/aw_disposable_missing?sslmode=disable")
    monkeypatch.setattr(client, "_connect", lambda **_: pytest.fail("Constructor must not connect"))
    result = PostgresAgentWorldRepository(client, environment=c.Environment.DEVELOPMENT)
    assert result.client is client and not hasattr(result, "path")
    with pytest.raises(ContractError, match="tls_required"):
        PostgresAgentWorldRepository(client, environment=c.Environment.PRODUCTION)
    with pytest.raises(ContractError, match="context_required"):
        result.get(context=None, kind=EntityKind.PERSONA, entity_id=uuid4())


def test_create_revision_replay_restart_and_atomic_outbox(repo):
    first = persona(repo)
    args = arguments(first, key="original-request")
    assert repo.commit(**args).replayed is False
    second = update(first)
    repo.commit(**arguments(second))
    restarted = PostgresAgentWorldRepository(repo.client, environment=repo.environment)
    assert restarted.get(context=context(), kind=first.KIND, entity_id=first.header.entity_id) == second
    assert restarted.get_revision(context=context(), kind=first.KIND, entity_id=first.header.entity_id, revision=1) == first
    replay = restarted.commit(**args)
    assert replay.replayed and replay.record == first and replay.event == args["event"]
    assert restarted.lookup_mutation(context=context(), operation="record.write", idempotency_key="original-request") == replay
    result = counts(repo)
    assert all(result[name] == 2 for name in ("sf_aw_revisions", "sf_aw_events", "sf_aw_outbox", "sf_aw_mutations"))
    assert result["sf_aw_records"] == 1


@pytest.mark.parametrize("check", [
    parity.test_same_key_different_payload_conflicts_and_forged_digest_cannot_replay,
    parity.test_private_owner_cannot_be_bypassed_with_creation_or_replay,
    parity.test_current_private_visibility_revokes_old_page_and_event_access,
    parity.test_safe_svg_is_accepted_without_side_effects,
    parity.test_nonexistent_and_other_owner_artifacts_cannot_be_committed_as_evidence,
    parity.test_dangling_entity_reference_cannot_be_committed,
    parity.test_entity_evidence_resolves_exact_historical_revision,
    parity.test_duplicate_event_id_does_not_leave_second_entity,
    parity.test_terminal_state_remains_immutable_through_storage,
    parity.test_maximum_scope_length_still_has_bounded_cursor,
], ids=lambda check: check.__name__.removeprefix("test_"))
def test_existing_repository_behavior_on_real_postgres(repo, check):
    check(repo)


def test_snapshot_cursor_restart_binding_and_new_rows(repo):
    items = [persona(repo, number=n) for n in (10, 20, 30)]
    for item in items:
        repo.commit(**arguments(item))
    first = repo.list(context=context(), kind=EntityKind.PERSONA, page=PageRequest(limit=1))
    repo.commit(**arguments(update(items[1], display_name="Newer revision")))
    repo.commit(**arguments(persona(repo, number=15)))
    restarted = PostgresAgentWorldRepository(repo.client, environment=repo.environment)
    follow = restarted.list(context=context(), kind=EntityKind.PERSONA, page=PageRequest(cursor=first.next_cursor))
    assert first.items == (items[0],) and follow.items == tuple(items[1:])
    for ctx, kind in ((context(user=2), EntityKind.PERSONA), (context(workspace="ws_example02"), EntityKind.PERSONA),
                      (context(), EntityKind.MEMORY)):
        with pytest.raises(ContractError, match="invalid_cursor"):
            repo.list(context=ctx, kind=kind, page=PageRequest(cursor=first.next_cursor))
    with pytest.raises(ContractError, match="invalid_cursor"):
        repo.list(context=context(), kind=EntityKind.PERSONA, page=PageRequest(cursor=first.next_cursor + "0"))


def test_concurrent_cas_and_duplicate_replay_have_one_effect(repo):
    item = persona(repo)
    repo.commit(**arguments(item))
    barrier = Barrier(2)
    def attempt(name):
        args = arguments(update(item, display_name=name))
        barrier.wait()
        try:
            return repo.commit(**args)
        except ContractError as exc:
            return exc.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, ("one", "two")))
    assert results.count("revision_conflict") == 1
    assert len(repo.events.list(context=context(), page=PageRequest()).items) == 2
    args = arguments(persona(repo), key="concurrent-same-request")
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: repo.commit(**args), range(4)))
    assert sum(not row.replayed for row in results) == 1
    assert counts(repo)["sf_aw_outbox"] == 3


def test_injected_outbox_failure_rolls_back_all_parts(repo, database):
    _, admin = database
    item = persona(repo)
    before = counts(repo)
    with admin.transaction(Scope.global_service_scope()) as conn:
        conn.execute("""CREATE FUNCTION aw_test_failure() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'disposable failure' USING ERRCODE='23514'; END $$""")
        conn.execute("CREATE TRIGGER aw_test_failure BEFORE INSERT ON sf_aw_outbox FOR EACH ROW EXECUTE FUNCTION aw_test_failure()")
    try:
        with pytest.raises(ContractError, match="storage_conflict"):
            repo.commit(**arguments(item))
        assert counts(repo) == before
        assert repo.get(context=context(), kind=item.KIND, entity_id=item.header.entity_id) is None
    finally:
        with admin.transaction(Scope.global_service_scope()) as conn:
            conn.execute("DROP TRIGGER aw_test_failure ON sf_aw_outbox")
            conn.execute("DROP FUNCTION aw_test_failure()")
    assert not repo.commit(**arguments(item)).replayed


def test_event_pagination_and_owned_consumer_receipts(repo):
    committed = [repo.commit(**arguments(persona(repo))) for _ in range(3)]
    first = repo.events.list(context=context(), page=PageRequest(limit=1))
    repo.commit(**arguments(persona(repo)))
    rest = repo.events.list(context=context(), page=PageRequest(cursor=first.next_cursor))
    assert first.items + rest.items == tuple(row.event for row in committed)
    event_id = first.items[0].event_id
    assert not repo.events.is_acknowledged(context=context(), consumer="projection-a", event_id=event_id)
    assert repo.events.acknowledge(context=context(), consumer="projection-a", event_id=event_id)
    restarted = PostgresAgentWorldRepository(repo.client, environment=repo.environment)
    assert restarted.events.is_acknowledged(context=context(), consumer="projection-a", event_id=event_id)
    assert not restarted.events.acknowledge(context=context(), consumer="projection-a", event_id=event_id)
    for other in (context(user=2), context(workspace="ws_example02")):
        assert not restarted.events.acknowledge(context=other, consumer="projection-a", event_id=event_id)
        assert not restarted.events.is_acknowledged(context=other, consumer="projection-a", event_id=event_id)


def test_artifact_hash_private_access_and_real_binary_parity(repo):
    proof = artifact(repo)
    assert artifact(repo) == proof
    assert artifact(repo, context(user=2)) != proof
    assert repo.get_artifact(context=context(user=2), reference=proof) is None
    assert repo.get_artifact_by_id(context=context(user=2), artifact_id=proof.artifact_id) is None
    assert repo.get_artifact_by_id(context=context(), artifact_id=proof.artifact_id) == (proof, b'{"policy":"local-safe-v1"}', "application/json")
    with pytest.raises(ContractError, match="integrity_mismatch"):
        repo.get_artifact(context=context(), reference=replace(proof, sha256="a" * 64))
    png = b"\x89PNG\r\n\x1a\n" + b"disposable-contract-binary"
    image = repo.put_artifact(context=context(), content=png, media_type="image/png")
    assert repo.get_artifact(context=context(), reference=image) == (png, "image/png")
    # Storage validates the existing signature/size contract, NOT visual PNG decoding.


def test_read_only_never_initializes_or_writes(repo):
    before = counts(repo)
    reader = PostgresAgentWorldRepository(repo.client, environment=repo.environment, read_only=True)
    assert reader.list(context=context(), kind=EntityKind.PERSONA, page=PageRequest()).items == ()
    assert reader.get_artifact_by_id(context=context(), artifact_id=uuid4()) is None
    assert counts(repo) == before
    with pytest.raises(ContractError, match="repository_read_only"):
        reader.put_artifact(context=context(), content=b"{}", media_type="application/json")
    with pytest.raises(ContractError, match="repository_read_only"):
        reader.events.acknowledge(context=context(), consumer="projection", event_id=uuid4())


@pytest.mark.parametrize("setting", ["stratforge.aw_user_uuid", "stratforge.aw_environment", "stratforge.workspace_id", "stratforge.service_scope"])
def test_rls_missing_any_context_denies_read_and_insert(repo, setting):
    item = persona(repo)
    repo.commit(**arguments(item))
    with raw(repo.client, missing=setting) as conn:
        for table in _TABLES:
            assert conn.execute(f"SELECT count(*) AS n FROM {table}").fetchone()["n"] == 0
    with pytest.raises(StorageConstraintError):
        with raw(repo.client, missing=setting) as conn:
            conn.execute("""INSERT INTO sf_aw_artifacts(environment,workspace_id,owner_uuid,artifact_id,sha256,media_type,content)
                VALUES('development','ws_example01',%s,%s,%s,'application/json',%s)""",
                         (context().user_uuid, uuid4(), "a" * 64, b"{}"))


@pytest.mark.parametrize("other", [context(workspace="ws_example02"), context(environment=c.Environment.CANARY),
                                     context(environment=c.Environment.PRODUCTION)])
def test_rls_cross_workspace_and_environment_select_insert_update(repo, other):
    item = persona(repo)
    repo.commit(**arguments(item))
    with raw(repo.client, other) as conn:
        for table in _TABLES:
            assert conn.execute(f"SELECT count(*) AS n FROM {table}").fetchone()["n"] == 0
        assert conn.execute("UPDATE sf_aw_records SET revision=revision WHERE entity_id=%s", (item.header.entity_id,)).rowcount == 0
    with pytest.raises(StorageConstraintError):
        with raw(repo.client, other) as conn:
            conn.execute("""INSERT INTO sf_aw_artifacts(environment,workspace_id,owner_uuid,artifact_id,sha256,media_type,content)
                VALUES('development','ws_example01',%s,%s,%s,'application/json',%s)""",
                         (other.user_uuid, uuid4(), "a" * 64, b"{}"))


def test_rls_same_workspace_user_private_data_and_write_check(repo):
    public = persona(repo)
    private = memory(repo)
    committed = repo.commit(**arguments(public))
    repo.commit(**arguments(private))
    other = context(user=2)
    assert repo.get(context=other, kind=public.KIND, entity_id=public.header.entity_id) == public
    assert repo.get_revision(context=other, kind=public.KIND, entity_id=public.header.entity_id, revision=1) is None
    with raw(repo.client, other) as conn:
        assert conn.execute("SELECT count(*) AS n FROM sf_aw_records").fetchone()["n"] == 1
        for name in ("sf_aw_events", "sf_aw_artifacts", "sf_aw_inbox", "sf_aw_mutations", "sf_aw_outbox"):
            assert conn.execute(f"SELECT count(*) AS n FROM {name}").fetchone()["n"] == 0
        assert conn.execute("UPDATE sf_aw_records SET revision=revision WHERE entity_id=%s", (public.header.entity_id,)).rowcount == 0
    with pytest.raises(StorageConstraintError):
        with raw(repo.client, other) as conn:
            conn.execute("""INSERT INTO sf_aw_inbox(environment,workspace_id,user_uuid,consumer,event_id)
                VALUES('development','ws_example01',%s,'foreign-read',%s)""", (context().user_uuid, committed.event.event_id))


@pytest.mark.parametrize("statement", ["DELETE FROM sf_aw_revisions", "UPDATE sf_aw_revisions SET revision=revision",
                                        "DELETE FROM sf_aw_events", "UPDATE sf_aw_artifacts SET sha256=sha256", "TRUNCATE sf_aw_records"])
def test_app_cannot_rewrite_immutable_evidence_or_truncate(repo, statement):
    repo.commit(**arguments(persona(repo)))
    with pytest.raises(StorageConstraintError):
        with raw(repo.client) as conn:
            conn.execute(statement)


def test_force_rls_even_for_schema_owner_and_repository_rejects_owner(repo, database):
    repo.commit(**arguments(persona(repo)))
    _, admin = database
    with admin.transaction(Scope.global_service_scope(), read_only=True) as conn:
        for table in _TABLES:
            assert conn.execute(f"SELECT count(*) AS n FROM {table}").fetchone()["n"] == 0
    unsafe = PostgresAgentWorldRepository(admin, environment=c.Environment.DEVELOPMENT)
    with pytest.raises(ContractError, match="unsafe_role"):
        unsafe.list(context=context(), kind=EntityKind.PERSONA, page=PageRequest())


def test_transaction_context_does_not_leak_to_next_connection(repo):
    repo.commit(**arguments(persona(repo)))
    with repo.client.transaction(Scope.workspace_scope("ws_example01"), read_only=True) as conn:
        assert conn.execute("SELECT sf_aw_user_uuid() AS user_uuid").fetchone()["user_uuid"] is None
        assert conn.execute("SELECT count(*) AS n FROM sf_aw_artifacts").fetchone()["n"] == 0


def materialize(repo, kind, *, ctx=None):
    """All reviewed DTOs with real persisted refs; no dummy/missing evidence."""
    ctx = ctx or context()
    proof = artifact(repo, ctx)
    cache = {}
    def save(current_kind, identity):
        key = current_kind, identity
        if key in cache:
            return cache[key]
        base = example_record(current_kind)
        def bind(value):
            if isinstance(value, c.SnapshotRef):
                return proof
            if isinstance(value, c.EntityRef):
                return save(value.kind, value.entity_id).ref()
            if isinstance(value, c.ExternalRef):
                return replace(value, scope=ctx.scope)
            if isinstance(value, tuple):
                return tuple(bind(item) for item in value)
            if is_dataclass(value):
                return replace(value, **{field.name: bind(getattr(value, field.name)) for field in fields(value)})
            return value
        header = replace(persona(repo, ctx=ctx).header, entity_id=identity)
        item = replace(base, **{field.name: bind(getattr(base, field.name)) for field in fields(base) if field.name != "header"}, header=header)
        suffix = "recorded" if current_kind in {EntityKind.EVALUATION, EntityKind.COURT_VOTE} else "changed"
        event = EventEnvelope(event_id=uuid4(), event_type=f"stratforge.ai.{current_kind.value}.{suffix}",
                              time=header.updated_at, subject=item.ref(), actor=ctx.actor,
                              correlation_id=header.correlation_id, policy=proof, data=EventData(references=(proof,)))
        mutation = MutationIdentity.for_record(context=ctx, operation="record.write", idempotency_key=str(uuid4()),
                                               record=item, expected_revision=0, event=event)
        repo.commit(context=ctx, record=item, expected_revision=0, event=event, mutation=mutation)
        cache[key] = item
        return item
    return save(kind, uuid4())


@pytest.mark.parametrize("kind", list(EntityKind))
def test_all_seventeen_reviewed_contracts_persist_with_real_references(repo, kind):
    item = materialize(repo, kind)
    assert repo.get(context=context(), kind=kind, entity_id=item.header.entity_id) == item
    assert item in repo.list(context=context(), kind=kind, page=PageRequest()).items
    assert repo.get_revision(context=context(), kind=kind, entity_id=item.header.entity_id, revision=1) == item


@pytest.mark.parametrize("environment", list(c.Environment))
def test_actual_tls_adapter_environment_separation(repo, environment):
    # The runner provisions fresh TLS only for this disposable cluster. These
    # are environment labels under the same RLS, not deployment acceptance.
    client = PostgresClient(repo.client.url, production=True)
    typed = PostgresAgentWorldRepository(client, environment=environment)
    ctx = context(environment=environment)
    item = persona(typed, ctx=ctx)
    typed.commit(**arguments(item, ctx=ctx))
    assert typed.get(context=ctx, kind=item.KIND, entity_id=item.header.entity_id) == item
    with raw(client, ctx, read_only=True) as conn:
        assert conn.execute("SELECT ssl FROM pg_stat_ssl WHERE pid=pg_backend_pid()").fetchone()["ssl"]
    for other_env in set(c.Environment) - {environment}:
        other = PostgresAgentWorldRepository(client, environment=other_env)
        assert other.list(context=context(environment=other_env), kind=item.KIND, page=PageRequest()).items == ()


def test_foreign_same_key_replay_cannot_leak_or_create_partial_entity(repo):
    owner = persona(repo)
    repo.commit(**arguments(owner, key="cross-user-identical-key"))
    other = context(user=2)
    item = persona(repo, ctx=other)
    assert repo.lookup_mutation(context=other, operation="record.write", idempotency_key="cross-user-identical-key") is None
    with pytest.raises(ContractError, match="idempotency_conflict"):
        repo.commit(**arguments(item, ctx=other, key="cross-user-identical-key"))
    assert repo.get(context=other, kind=item.KIND, entity_id=item.header.entity_id) is None
    assert repo.events.list(context=other, page=PageRequest()).items == ()


def test_persona_role_assignment_remains_serialized_and_owned(repo):
    proof = artifact(repo, content=b'{"application_role":"chart_researcher"}')
    first, second = (replace(persona(repo), profile=proof) for _ in range(2))
    repo.commit(**arguments(first))
    repo.commit(**arguments(second))
    repo.commit(**arguments(update(first)))
    with pytest.raises(ContractError, match="application_role_already_assigned"):
        repo.commit(**arguments(update(second)))
    other = context(user=2)
    public = replace(persona(repo, ctx=other), profile=artifact(repo, other, b'{"application_role":"chart_researcher"}'))
    repo.commit(**arguments(public, ctx=other))
    assert repo.commit(**arguments(update(public), ctx=other))


@pytest.mark.parametrize("field", ["kind", "environment", "workspace_id", "entity_id", "owner_user_uuid", "revision"])
def test_sql_payload_identity_binding_rejects_mismatched_or_missing_header(repo, field):
    item = persona(repo)
    data = json.loads(encode_record(item))
    if field == "kind":
        data.pop("kind")
    elif field in {"environment", "workspace_id"}:
        data["header"]["scope"].pop(field)
    else:
        data["header"].pop(field)
    with pytest.raises(StorageConstraintError):
        with raw(repo.client) as conn:
            conn.execute("""INSERT INTO sf_aw_revisions(environment,workspace_id,kind,entity_id,revision,owner_uuid,visibility,payload)
                VALUES('development','ws_example01','persona',%s,1,%s,'workspace',%s)""",
                         (item.header.entity_id, context().user_uuid, json.dumps(data)))


def test_existing_worker_leases_remain_outside_agent_world_storage(repo):
    with raw(repo.client, read_only=True) as conn:
        names = {row["relname"] for row in conn.execute("SELECT relname FROM pg_class WHERE relname LIKE 'sf_aw_%%' AND relkind='r'").fetchall()}
    assert names == set(_TABLES)
    assert not any("lease" in name or "job" in name for name in names)
    assert not hasattr(repo, "enqueue") and not hasattr(repo, "claim")
    # Atomic commits/inbox are domain effects. The existing worker job/lease
    # adapter owns external dispatch and must not be replaced by an AW queue.


def _published(repo, *, lesson=False):
    stamp = datetime.now(timezone.utc)
    original = replace(memory(repo), retention_until=stamp + timedelta(days=1), memory_class=c.MemoryClass.PRIVATE)
    if lesson:
        outcome = materialize(repo, EntityKind.OUTCOME)
        outcome = update(outcome, status="verified", verification=original.content)
        repo.commit(**arguments(outcome))
        content = artifact(repo, content=json.dumps({"verified_outcome_id": str(outcome.header.entity_id)}).encode())
        original = replace(original, memory_class=c.MemoryClass.VERIFIED_LESSON, content=content, verification=outcome.verification)
    repo.commit(**arguments(original))
    original = update(original)
    repo.commit(**arguments(original))
    target = replace(memory(repo, visibility=c.Visibility.WORKSPACE), content=original.content,
                     retention_until=stamp + timedelta(hours=12))
    data = {"type": "workspace_memory_publication", "memory_id": str(target.header.entity_id),
            "owner_user_uuid": str(context().user_uuid), "content_sha256": original.content.sha256,
            "source_memory_id": str(original.header.entity_id), "source_revision": original.header.revision}
    proof = artifact(repo, content=json.dumps(data).encode())
    target = replace(target, verification=proof)
    repo.commit(**arguments(target))
    target = update(target)
    repo.commit(**arguments(target))
    return original, target


def test_published_memory_grant_is_explicit_and_private_api_stays_private(repo):
    original, published = _published(repo)
    other = context(user=2)
    for reference in (published.content, published.verification):
        value = repo.read_memory_artifact(context=other, memory_id=published.header.entity_id, artifact_id=reference.artifact_id)
        assert value and value[0] == reference
        assert repo.get_artifact(context=other, reference=reference) is None
        assert repo.get_artifact_by_id(context=other, artifact_id=reference.artifact_id) is None
    assert repo.read_memory_artifact(context=other, memory_id=original.header.entity_id, artifact_id=original.content.artifact_id) is None
    assert repo.read_memory_artifact(context=other, memory_id=published.header.entity_id, artifact_id=uuid4()) is None
    assert repo.read_memory_artifact(context=context(workspace="ws_example02"), memory_id=published.header.entity_id,
                                     artifact_id=published.content.artifact_id) is None


@pytest.mark.parametrize("source", ["original", "publication"])
def test_memory_source_change_atomically_revokes_existing_grant(repo, source):
    original, published = _published(repo)
    args = dict(context=context(user=2), memory_id=published.header.entity_id, artifact_id=published.content.artifact_id)
    assert repo.read_memory_artifact(**args)
    revoked = update(original if source == "original" else published, status="revoked")
    repo.commit(**arguments(revoked))
    assert repo.read_memory_artifact(**args) is None
    with raw(repo.client) as conn:
        assert not conn.execute("SELECT valid FROM sf_aw_memory_grants WHERE memory_id=%s", (published.header.entity_id,)).fetchone()["valid"]


def test_memory_ttl_enforced_at_database_time_even_with_forged_past_now(repo, database):
    original, published = _published(repo)
    _, admin = database
    # Disposable schema-owner failure injection: publication/source contracts
    # remain valid; the derived index expiry must still fail closed in SQL.
    with raw(admin) as conn:
        conn.execute("UPDATE sf_aw_memory_grants SET retention_until=clock_timestamp()-interval '1 second'")
    assert repo.read_memory_artifact(context=context(user=2), memory_id=published.header.entity_id,
                                     artifact_id=published.content.artifact_id,
                                     now=datetime(2026, 1, 1, tzinfo=timezone.utc)) is None


def test_record_trigger_revokes_grant_when_writer_omits_application_refresh(repo):
    original, published = _published(repo)
    with raw(repo.client) as conn:
        conn.execute("UPDATE sf_aw_records SET revision=revision WHERE entity_id=%s", (original.header.entity_id,))
    assert repo.read_memory_artifact(context=context(user=2), memory_id=published.header.entity_id,
                                     artifact_id=published.content.artifact_id) is None


def test_verified_lesson_grant_tracks_current_outcome_and_revalidation(repo):
    original, published = _published(repo, lesson=True)
    payload = json.loads(repo.get_artifact(context=context(), reference=original.content)[0])
    outcome = repo.get(context=context(), kind=EntityKind.OUTCOME, entity_id=UUID(payload["verified_outcome_id"]))
    args = dict(context=context(user=2), memory_id=published.header.entity_id, artifact_id=published.content.artifact_id)
    assert repo.read_memory_artifact(**args)
    disputed = update(outcome, status="disputed")
    repo.commit(**arguments(disputed))
    assert repo.read_memory_artifact(**args) is None
    verified = update(disputed, status="verified")
    repo.commit(**arguments(verified))
    assert repo.read_memory_artifact(**args)


def test_bogus_publication_never_creates_a_valid_grant(repo):
    original, publication = _published(repo)
    draft = replace(memory(repo, visibility=c.Visibility.WORKSPACE), content=original.content,
                    verification=publication.verification, retention_until=datetime.now(timezone.utc) + timedelta(days=1))
    repo.commit(**arguments(draft))
    active = update(draft)
    repo.commit(**arguments(active))
    assert repo.read_memory_artifact(context=context(user=2), memory_id=active.header.entity_id, artifact_id=active.content.artifact_id) is None
    with raw(repo.client, read_only=True) as conn:
        assert conn.execute("SELECT count(*) AS n FROM sf_aw_memory_grants WHERE memory_id=%s", (active.header.entity_id,)).fetchone()["n"] == 0
