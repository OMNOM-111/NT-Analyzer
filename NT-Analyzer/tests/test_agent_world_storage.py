from __future__ import annotations

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from threading import Barrier
from uuid import UUID, uuid4

import pytest

from app.ai_control_center import contracts as c
from app.ai_control_center.events import EventData, EventEnvelope, MutationIdentity
from app.ai_control_center.repositories import PageRequest
from app.ai_control_center.sqlite_repository import MAX_ARTIFACT_BYTES, SQLiteAgentWorldRepository
from app.ai_control_center.states import ContractError, EntityKind
from app.ai_control_center.storage_codec import decode_event, decode_record, encode_event, encode_record
from tests.test_agent_world_contracts import event_for, record as example_record


NOW = datetime(2026, 9, 4, 22, tzinfo=timezone.utc)


def context(*, user=1, workspace="ws_example01", environment=c.Environment.DEVELOPMENT):
    return c.RequestContext(scope=c.TenantScope(environment=environment, workspace_id=workspace),
                            user_uuid=UUID(int=user), actor=c.ActorRef(kind=c.ActorKind.HUMAN, actor_id=UUID(int=user)))


@pytest.fixture
def repo(tmp_path):
    return SQLiteAgentWorldRepository(tmp_path / "isolated" / "agent-world.sqlite3")


def artifact(repo, ctx=None, content=b'{"policy":"local-safe-v1"}'):
    return repo.put_artifact(context=ctx or context(), content=content, media_type="application/json")


def persona(repo, *, ctx=None, number=None):
    ctx = ctx or context()
    proof = artifact(repo, ctx)
    header = c.RecordHeader(entity_id=UUID(int=number) if number else uuid4(), scope=ctx.scope,
                            owner_user_uuid=ctx.user_uuid, revision=1, created_at=NOW, updated_at=NOW,
                            created_by=ctx.actor, correlation_id=uuid4(), policy=proof)
    return c.Persona(header=header, status="draft", display_name="Марина", profile=proof)


def memory(repo, *, ctx=None, number=None, visibility=c.Visibility.PRIVATE):
    profile = persona(repo, ctx=ctx, number=number)
    return c.Memory(header=profile.header, status="draft", memory_class=c.MemoryClass.WORKSPACE,
                    visibility=visibility, sensitivity=c.Sensitivity.CONFIDENTIAL, content=profile.profile,
                    provenance=(profile.profile,), retention_until=NOW + timedelta(days=1))


def arguments(item, *, ctx=None, key=None, event_id=None):
    ctx = ctx or context()
    expected = item.header.revision - 1
    event = EventEnvelope(event_id=event_id or uuid4(), event_type=f"stratforge.ai.{item.KIND.value}.changed",
                          time=item.header.updated_at, subject=item.ref(), actor=ctx.actor,
                          correlation_id=item.header.correlation_id, policy=item.header.policy,
                          data=EventData(references=(item.header.policy,)), causation_id=item.header.causation_id)
    mutation = MutationIdentity.for_record(context=ctx, operation="record.write", idempotency_key=key or str(uuid4()),
                                           record=item, expected_revision=expected, event=event)
    return dict(context=ctx, record=item, expected_revision=expected, event=event, mutation=mutation)


def update(item, *, status="active", **changes):
    return replace(item, status=status, header=replace(item.header, revision=item.header.revision + 1,
                                                      updated_at=item.header.updated_at + timedelta(seconds=1)), **changes)


@pytest.mark.parametrize("kind", list(EntityKind))
def test_codec_roundtrips_every_reviewed_record_and_event(kind):
    item = example_record(kind)
    assert decode_record(encode_record(item)) == item
    event = event_for(item)
    assert decode_event(encode_event(event)) == event


@pytest.mark.parametrize("change", [lambda p: p.update(kind="unknown"), lambda p: p.update(unexpected=1),
                                     lambda p: p["header"].update(revision=True),
                                     lambda p: p["header"].update(schema_version=9),
                                     lambda p: p["header"].update(owner_user_uuid=0)])
def test_codec_rejects_corrupt_or_extended_stored_contract(change):
    payload = json.loads(encode_record(example_record()))
    change(payload)
    with pytest.raises(ContractError, match="stored_contract_invalid"):
        decode_record(json.dumps(payload))


def test_codec_rejects_duplicate_json_keys():
    raw = encode_record(example_record())
    with pytest.raises(ContractError, match="stored_contract_invalid"):
        decode_record(raw.replace('"kind":"task"', '"kind":"task","kind":"task"', 1))


@pytest.mark.parametrize("environment", [c.Environment.CANARY, c.Environment.PRODUCTION, "development", None])
def test_non_development_rejected_before_filesystem_touch(tmp_path, environment):
    path = tmp_path / "must-not-create" / "store.sqlite3"
    with pytest.raises(ContractError, match="development_only"):
        SQLiteAgentWorldRepository(path, environment=environment)
    assert not path.parent.exists()


def test_existing_unrelated_database_is_not_migrated(tmp_path):
    path = tmp_path / "owner-auth.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE owner_data(value TEXT)")
    before = path.read_bytes()
    with pytest.raises(ContractError, match="storage_identity_mismatch"):
        SQLiteAgentWorldRepository(path)
    assert path.read_bytes() == before


def test_create_update_restart_and_original_replay(repo):
    first = persona(repo)
    args = arguments(first)
    assert repo.commit(**args).replayed is False
    second = update(first)
    repo.commit(**arguments(second))
    restarted = SQLiteAgentWorldRepository(repo.path)
    assert restarted.get(context=context(), kind=first.KIND, entity_id=first.header.entity_id) == second
    replay = restarted.commit(**args)
    assert replay.replayed is True and replay.record == first and replay.event == args["event"]
    with sqlite3.connect(repo.path) as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert connection.execute("SELECT COUNT(*) FROM aw_revisions").fetchone()[0] == 2
        assert connection.execute("SELECT COUNT(*) FROM aw_events").fetchone()[0] == 2
        assert connection.execute("SELECT COUNT(*) FROM aw_outbox").fetchone()[0] == 2
        assert connection.execute("SELECT COUNT(*) FROM aw_mutations").fetchone()[0] == 2


def test_same_key_different_payload_conflicts_and_forged_digest_cannot_replay(repo):
    item = persona(repo)
    args = arguments(item, key="same-request-key")
    repo.commit(**args)
    changed = replace(item, display_name="Иван")
    with pytest.raises(ContractError, match="idempotency_conflict"):
        repo.commit(**arguments(changed, key="same-request-key", event_id=args["event"].event_id))
    with pytest.raises(ContractError, match="mutation_payload_mismatch"):
        repo.commit(**{**args, "record": changed})


def test_private_owner_cannot_be_bypassed_with_creation_or_replay(repo):
    item = memory(repo)
    args = arguments(item, key="private-owner-write")
    repo.commit(**args)
    other = context(user=2)
    assert repo.get(context=other, kind=item.KIND, entity_id=item.header.entity_id) is None
    assert repo.get(context=other, kind=item.KIND, entity_id=uuid4()) is None
    assert not repo.list(context=other, kind=item.KIND, page=PageRequest()).items
    assert not repo.events.list(context=other, page=PageRequest()).items
    assert repo.events.acknowledge(context=other, consumer="read-model", event_id=args["event"].event_id) is False
    with pytest.raises(ContractError, match="private_memory_denied"):
        repo.commit(**{**args, "context": other})


@pytest.mark.parametrize("other", [context(workspace="ws_example02"),
                                    context(environment=c.Environment.CANARY),
                                    context(environment=c.Environment.PRODUCTION)])
def test_cross_scope_read_write_and_artifact_isolation(repo, other):
    item = persona(repo)
    repo.commit(**arguments(item))
    if other.scope.environment is c.Environment.DEVELOPMENT:
        assert repo.get(context=other, kind=item.KIND, entity_id=item.header.entity_id) is None
        assert not repo.list(context=other, kind=item.KIND, page=PageRequest()).items
    else:
        with pytest.raises(ContractError, match="scope_mismatch"):
            repo.get(context=other, kind=item.KIND, entity_id=item.header.entity_id)
    with pytest.raises(ContractError, match="scope_mismatch"):
        repo.commit(**{**arguments(item), "context": other})
    with pytest.raises(ContractError, match="scope_mismatch"):
        repo.get_artifact(context=other, reference=item.profile)


def test_snapshot_pagination_excludes_new_rows_and_uses_original_revision(repo):
    items = [persona(repo, number=i) for i in (10, 20, 30)]
    for item in items:
        repo.commit(**arguments(item))
    first = repo.list(context=context(), kind=EntityKind.PERSONA, page=PageRequest(limit=1))
    assert first.items == (items[0],)
    repo.commit(**arguments(update(items[1], display_name="Changed after snapshot")))
    repo.commit(**arguments(persona(repo, number=15)))
    restarted = SQLiteAgentWorldRepository(repo.path)
    following = restarted.list(context=context(), kind=EntityKind.PERSONA,
                                page=PageRequest(limit=2, cursor=first.next_cursor))
    assert following.items == tuple(items[1:]) and following.next_cursor is None


def test_cursor_is_bound_to_scope_user_filter_signature_and_database(repo, tmp_path):
    for i in (10, 20):
        repo.commit(**arguments(persona(repo, number=i)))
    cursor = repo.list(context=context(), kind=EntityKind.PERSONA, page=PageRequest(limit=1)).next_cursor
    assert len(cursor) <= 512
    for ctx, kind in [(context(user=2), EntityKind.PERSONA),
                      (context(workspace="ws_example02"), EntityKind.PERSONA),
                      (context(), EntityKind.MEMORY)]:
        with pytest.raises(ContractError, match="invalid_cursor"):
            repo.list(context=ctx, kind=kind, page=PageRequest(cursor=cursor))
    with pytest.raises(ContractError, match="invalid_cursor"):
        repo.list(context=context(), kind=EntityKind.PERSONA, page=PageRequest(cursor=cursor[:-1] + ("0" if cursor[-1] != "0" else "1")))
    with pytest.raises(ContractError, match="invalid_cursor"):
        repo.events.list(context=context(), page=PageRequest(cursor=cursor))
    second = SQLiteAgentWorldRepository(tmp_path / "another.sqlite3")
    with pytest.raises(ContractError, match="invalid_cursor"):
        second.list(context=context(), kind=EntityKind.PERSONA, page=PageRequest(cursor=cursor))


def test_current_private_visibility_revokes_old_page_and_event_access(repo):
    # A former workspace snapshot is not a way around the current ACL.
    other = context(user=2)
    for i in (10, 20):
        repo.commit(**arguments(memory(repo, number=i, visibility=c.Visibility.WORKSPACE)))
    first = repo.list(context=other, kind=EntityKind.MEMORY, page=PageRequest(limit=1))
    item = repo.get(context=context(), kind=EntityKind.MEMORY, entity_id=UUID(int=20))
    repo.commit(**arguments(update(item, status="draft", visibility=c.Visibility.PRIVATE)))
    assert not repo.list(context=other, kind=EntityKind.MEMORY,
                         page=PageRequest(cursor=first.next_cursor)).items


def test_cas_race_has_exactly_one_winner_and_stale_revision_cannot_commit(repo):
    item = persona(repo)
    repo.commit(**arguments(item))
    barrier = Barrier(2)

    def attempt(name):
        worker_repo = SQLiteAgentWorldRepository(repo.path)
        args = arguments(update(item, display_name=name))
        barrier.wait()
        try:
            return worker_repo.commit(**args)
        except ContractError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(attempt, ("First", "Second")))
    assert sum(result == "revision_conflict" for result in results) == 1
    assert sum(not isinstance(result, str) for result in results) == 1
    assert len(repo.events.list(context=context(), page=PageRequest()).items) == 2


def test_outbox_failure_rolls_back_every_part_of_commit(repo):
    item = persona(repo)
    args = arguments(item)
    with sqlite3.connect(repo.path) as connection:
        connection.execute("CREATE TRIGGER injected_failure BEFORE INSERT ON aw_outbox BEGIN SELECT RAISE(ABORT,'test failure'); END")
    with pytest.raises(ContractError, match="storage_conflict"):
        repo.commit(**args)
    assert repo.get(context=context(), kind=item.KIND, entity_id=item.header.entity_id) is None
    with sqlite3.connect(repo.path) as connection:
        for table in ("aw_records", "aw_revisions", "aw_events", "aw_outbox", "aw_mutations"):
            assert connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
        connection.execute("DROP TRIGGER injected_failure")
    assert repo.commit(**args).replayed is False


def test_event_pagination_and_consumer_inbox_survive_restart(repo):
    committed = [repo.commit(**arguments(persona(repo))) for _ in range(3)]
    first = repo.events.list(context=context(), page=PageRequest(limit=1))
    repo.commit(**arguments(persona(repo)))
    remaining = repo.events.list(context=context(), page=PageRequest(cursor=first.next_cursor))
    assert first.items + remaining.items == tuple(item.event for item in committed)
    event_id = committed[0].event.event_id
    assert repo.events.acknowledge(context=context(), consumer="projection-a", event_id=event_id) is True
    restarted = SQLiteAgentWorldRepository(repo.path)
    assert restarted.events.acknowledge(context=context(), consumer="projection-a", event_id=event_id) is False
    assert restarted.events.acknowledge(context=context(), consumer="projection-b", event_id=event_id) is True
    assert restarted.events.acknowledge(context=context(), consumer="projection-a", event_id=uuid4()) is False


def test_artifacts_are_content_addressed_private_durable_and_hash_verified(repo):
    proof = artifact(repo)
    assert artifact(repo) == proof
    assert artifact(repo, context(user=2)) != proof
    assert repo.get_artifact(context=context(user=2), reference=proof) is None
    assert repo.get_artifact_by_id(context=context(user=2), artifact_id=proof.artifact_id) is None
    assert repo.get_artifact_by_id(context=context(workspace="ws_example02"), artifact_id=proof.artifact_id) is None
    assert repo.get_artifact_by_id(context=context(), artifact_id=uuid4()) is None
    restarted = SQLiteAgentWorldRepository(repo.path)
    assert restarted.get_artifact(context=context(), reference=proof) == (b'{"policy":"local-safe-v1"}', "application/json")
    assert restarted.get_artifact_by_id(context=context(), artifact_id=proof.artifact_id) == (proof, b'{"policy":"local-safe-v1"}', "application/json")
    with sqlite3.connect(repo.path) as connection:
        connection.execute("UPDATE aw_artifacts SET content=? WHERE artifact_id=?", (b"{}", str(proof.artifact_id)))
    with pytest.raises(ContractError, match="artifact_integrity_mismatch"):
        restarted.get_artifact(context=context(), reference=proof)
    with pytest.raises(ContractError, match="artifact_integrity_mismatch"):
        restarted.get_artifact_by_id(context=context(), artifact_id=proof.artifact_id)
    with pytest.raises(ContractError, match="artifact_integrity_mismatch"):
        artifact(repo)


@pytest.mark.parametrize("content,mime", [
    (b"", "application/json"), (b"x" * (MAX_ARTIFACT_BYTES + 1), "application/json"),
    (b"{}", "text/html"), (b"NaN", "application/json"),
    (b"<svg><script>alert(1)</script></svg>", "image/svg+xml"),
    (b'<svg><image href="https://example.com"/></svg>', "image/svg+xml"),
    (b'<svg><rect onclick="alert(1)"/></svg>', "image/svg+xml"),
    (b'<!DOCTYPE svg><svg/>', "image/svg+xml"), (b"not-png", "image/png"),
], ids=("empty", "oversized", "html", "nan", "script", "external_image", "event_handler", "doctype", "invalid_png"))
def test_artifact_content_is_bounded_and_inert(repo, content, mime):
    with pytest.raises(ContractError):
        repo.put_artifact(context=context(), content=content, media_type=mime)


def test_safe_svg_is_accepted_without_side_effects(repo):
    content = b'<svg xmlns="http://www.w3.org/2000/svg" width="200" height="100"><path d="M0 0 L100 20" stroke="blue"/><text x="3" y="50">Sample</text></svg>'
    proof = repo.put_artifact(context=context(), content=content, media_type="image/svg+xml")
    assert repo.get_artifact(context=context(), reference=proof) == (content, "image/svg+xml")


@pytest.mark.parametrize("content,mime", [
    (b'{"value":1e400}', "application/json"),
    (b'<svg xml:base="https://example.com"><rect fill="url(#x)"/></svg>', "image/svg+xml"),
    (b'<svg><rect fill="url(#x) url(https://example.com)"/></svg>', "image/svg+xml"),
    (b'<svg><rect fill="u\\72l(https://example.com)"/></svg>', "image/svg+xml"),
])
def test_numeric_and_svg_obfuscation_is_rejected(repo, content, mime):
    with pytest.raises(ContractError, match="invalid_artifact_content"):
        repo.put_artifact(context=context(), content=content, media_type=mime)


def test_nonexistent_and_other_owner_artifacts_cannot_be_committed_as_evidence(repo):
    item = persona(repo)
    missing = replace(item.profile, artifact_id=uuid4())
    foreign = artifact(repo, context(user=2))
    for proof in (missing, foreign):
        with pytest.raises(ContractError, match="artifact_reference_unavailable"):
            repo.commit(**arguments(replace(item, profile=proof)))
    assert not repo.events.list(context=context(), page=PageRequest()).items


def test_dangling_entity_reference_cannot_be_committed(repo):
    item = persona(repo)
    fake = c.EntityRef(kind=EntityKind.TASK, entity_id=uuid4(), revision=1, scope=context().scope)
    result = c.Outcome(header=item.header, status="pending", task=fake, evidence=(item.profile,))
    with pytest.raises(ContractError, match="entity_reference_unavailable"):
        repo.commit(**arguments(result))


def test_entity_evidence_resolves_exact_historical_revision(repo):
    profile = persona(repo)
    repo.commit(**arguments(profile))
    repo.commit(**arguments(update(profile)))
    item = persona(repo)
    args = arguments(item)
    event = replace(args["event"], data=EventData(references=(profile.ref(),)))
    mutation = MutationIdentity.for_record(context=context(), operation="record.write", idempotency_key=str(uuid4()),
                                           record=item, expected_revision=0, event=event)
    repo.commit(**{**args, "event": event, "mutation": mutation})
    invalid = persona(repo)
    args = arguments(invalid)
    event = replace(args["event"], data=EventData(references=(replace(profile.ref(), revision=3),)))
    mutation = MutationIdentity.for_record(context=context(), operation="record.write", idempotency_key=str(uuid4()),
                                           record=invalid, expected_revision=0, event=event)
    with pytest.raises(ContractError, match="entity_reference_unavailable"):
        repo.commit(**{**args, "event": event, "mutation": mutation})


def test_missing_and_future_schema_refuse_implicit_upgrade(repo):
    with sqlite3.connect(repo.path) as connection:
        connection.execute("PRAGMA user_version=999")
    with pytest.raises(ContractError, match="schema_unsupported"):
        SQLiteAgentWorldRepository(repo.path)


def test_cursor_exposes_gap_after_restore_not_silent_empty_page(repo):
    for number in (10, 20):
        repo.commit(**arguments(persona(repo, number=number)))
    cursor = repo.list(context=context(), kind=EntityKind.PERSONA, page=PageRequest(limit=1)).next_cursor
    # Simulate an earlier SQLite backup retaining the same store cursor key.
    with sqlite3.connect(repo.path) as connection:
        connection.execute("DELETE FROM aw_revisions WHERE seq=2")
    with pytest.raises(ContractError, match="cursor_gap"):
        repo.list(context=context(), kind=EntityKind.PERSONA, page=PageRequest(cursor=cursor))


def test_duplicate_event_id_does_not_leave_second_entity(repo):
    first = repo.commit(**arguments(persona(repo)))
    second = persona(repo)
    with pytest.raises(ContractError, match="storage_conflict"):
        repo.commit(**arguments(second, event_id=first.event.event_id))
    assert repo.get(context=context(), kind=second.KIND, entity_id=second.header.entity_id) is None


def test_terminal_state_remains_immutable_through_storage(repo):
    item = persona(repo)
    repo.commit(**arguments(item))
    retired = update(item, status="retired")
    repo.commit(**arguments(retired))
    with pytest.raises(ContractError, match="finalized_record_immutable"):
        repo.commit(**arguments(update(retired, status="retired", display_name="Cannot edit")))


def test_maximum_scope_length_still_has_bounded_cursor(repo):
    ctx = context(workspace="ws_" + "x" * 80)
    for i in (10, 20):
        repo.commit(**arguments(persona(repo, ctx=ctx, number=i), ctx=ctx))
    first = repo.list(context=ctx, kind=EntityKind.PERSONA, page=PageRequest(limit=1))
    assert len(first.next_cursor) <= 512
    assert len(repo.list(context=ctx, kind=EntityKind.PERSONA, page=PageRequest(cursor=first.next_cursor)).items) == 1
