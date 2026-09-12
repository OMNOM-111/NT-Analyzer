"""Real Handler + disposable Preview stores; no live keys, network or workers."""
from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from app import account_auth, preview_sandbox, runtime_env, server, workspaces
from app.ai_control_center import gateway, preview_domains
from app.ai_control_center.flags import Flag, FlagSnapshot
from app.ai_control_center.states import ContractError
from tests.test_preview_sandbox import preview_env
from tests.test_agent_world_gateway import active, http_preview


PREFIX = gateway.PREFIX + "domains/"


def handler(active, *, control=True):
    return SimpleNamespace(_remote_context=active["raw"],
        _preview_control_authorized=lambda: control,
        _cookie_value=lambda _: active["token"],
        _decorate_workspace_context=lambda raw: server.Handler._decorate_workspace_context(object(), raw))


def envelope(payload=None, *, key="preview-domains-test-001", revision=0):
    return {"payload": {} if payload is None else payload, "expected_revision": revision, "idempotency_key": key}


def activate(active, scenario="agent_world_operator"):
    result = preview_sandbox.activate_scenario(scenario, device_credential="preview-domains-isolated-device")
    active["token"] = result["session_token"]
    active["raw"] = server.Handler._decorate_workspace_context(object(), account_auth.authenticate_session(active["token"]))
    return result


def test_reads_are_empty_and_never_seed_or_grant_operators(http_preview, active):
    for domain in preview_domains.SUPPORTED:
        status, data = http_preview(PREFIX + domain)
        assert status == 200, data
        assert data["enabled"] and data["items"] == [] and data["synthetic"]
        assert data["capabilities"]["can_create"] is True
        assert not data["capabilities"]["can_accept_suggestion"]
    status, system = http_preview(PREFIX + "system")
    assert status == 200, system
    assert not system["capabilities"]["can_seed_preview_dataset"]
    assert system["items"][0]["actions"] == []
    assert preview_sandbox.synthetic_operator_access_allowed(active["raw"]) is False
    assert system["mechanisms"]["execution_v2"] == "disabled"
    assert system["mechanisms"]["postgres_rls"] == "not_used_in_preview"
    enabled = {key for key, value in system["flags"].items() if value}
    assert enabled == {flag.value for flag in gateway._PREVIEW_FLAGS}


def test_persona_http_create_update_replay_preserves_face_and_voice(http_preview):
    payload = {"name": "Synthetic profile", "avatar_key": "marina", "description": "Synthetic only",
        "voice_profile_id": "marina", "voice_speed": .8, "voice_language": "en-US", "voice_mode": "browser"}
    status, created = http_preview(PREFIX + "personas/new/create", envelope(payload))
    assert status == 200, created
    first = created["item"]
    assert first["status"] == "draft" and first["synthetic"]
    assert first["presentation"]["capabilities"]["server_speech"] == "disabled_in_preview"
    status, updated = http_preview(PREFIX + "personas/" + first["id"] + "/update",
        envelope({"name": "Renamed"}, key="preview-persona-update-001", revision=first["revision"]))
    assert status == 200, updated
    current = updated["item"]
    assert current["title"] == "Renamed" and current["avatar_key"] == "marina"
    assert current["voice_speed"] == .8 and current["voice_language"] == "en-US"
    assert current["voice_profile_id"] == "marina"
    status, replay = http_preview(PREFIX + "personas/" + first["id"] + "/update",
        envelope({"name": "Renamed"}, key="preview-persona-update-001", revision=first["revision"]))
    assert status == 200 and replay["replayed"] and replay["item"]["revision"] == current["revision"]
    status, stale = http_preview(PREFIX + "personas/" + first["id"] + "/update",
        envelope({"name": "Stale"}, key="preview-persona-stale-001", revision=first["revision"]))
    assert status == 409 and stale["code"] == "revision_conflict"
    status, detail = http_preview(PREFIX + "personas/" + first["id"])
    assert status == 200 and detail["title"] == "Renamed" and detail["revision"] == current["revision"]


def test_memory_requires_explicit_review_and_revoke_preserves_history(http_preview, active):
    payload = {"title": "Synthetic note", "content": "Synthetic content", "purpose": "preview-check", "retention_days": 7}
    status, created = http_preview(PREFIX + "memory/new/create", envelope(payload))
    assert status == 200, created
    item = created["item"]
    assert item["status"] == "draft" and item["verification"] is None
    status, rejected = http_preview(PREFIX + "memory/" + item["id"] + "/promote", envelope(revision=1))
    assert status == 409 and rejected["code"] == "invalid_domain_fields"
    status, accepted = http_preview(PREFIX + "memory/" + item["id"] + "/promote",
        envelope({"reason": "Explicit synthetic review"}, key="preview-memory-review-001", revision=1))
    assert status == 200, accepted
    assert accepted["item"]["status"] == "active"
    assert accepted["item"]["verification"]["method"] == "explicit_user_review"
    assert accepted["item"]["model_quality_evidence"] is False
    service = gateway.domain_service_for(handler(active))
    assert service.service.retrieve_memory(context=service.context, admit=service._admit,
        purpose="preview-check")["items"][0]["content"] == payload["content"]
    status, revoked = http_preview(PREFIX + "memory/" + item["id"] + "/revoke",
        envelope({"reason": "Synthetic revoke"}, key="preview-memory-revoke-001", revision=2))
    assert status == 200, revoked
    assert revoked["item"]["status"] == "revoked" and "content" not in revoked["item"]
    assert service.service.retrieve_memory(context=service.context, admit=service._admit, purpose="preview-check")["items"] == []
    from app.ai_control_center.states import EntityKind
    prior = service.service.repository.get_revision(context=service.context, kind=EntityKind.MEMORY,
        entity_id=UUID(item["id"]), revision=2)
    assert prior.status == "active", "revocation must not delete the reviewed revision"


def test_projects_version_and_proposals_use_same_core_without_enqueue(http_preview):
    status, project = http_preview(PREFIX + "projects/new/create", envelope({"title": "Synthetic project",
        "description": "No strategy executed", "strategy_key": "preview_strategy"}))
    assert status == 200, project
    status, version = http_preview(PREFIX + "projects/" + project["item"]["id"] + "/version",
        envelope({"notes": "Synthetic revision", "parameters": {"period": 10}}, key="preview-project-version-001", revision=1))
    assert status == 200 and version["item"]["version_count"] == 1, version
    for domain, fields in (("routines", {"interval_minutes": 1440}), ("calendar", {
            "starts_at": "2026-01-01T10:00:00Z", "ends_at": "2026-01-01T10:30:00Z"})):
        status, result = http_preview(PREFIX + domain + "/new/create", envelope({"title": "Synthetic proposal",
            "description": "Historical manual fixture", **fields}, key="preview-create-" + domain))
        assert status == 200, result
        item = result["item"]
        assert item["status"] == "proposed" and item["actions"] == ["dismiss"] and item["handoff"] is None
        status, denied = http_preview(PREFIX + domain + "/" + item["id"] + "/accept", envelope(revision=1))
        assert status == 403 and denied["code"] == "agent_world_preview_followup_disabled"
        status, listing = http_preview(PREFIX + domain)
        assert status == 200 and listing["process_intelligence"]["candidates"] == []
        assert not listing["process_intelligence"]["enabled"]
        status, dismissed = http_preview(PREFIX + domain + "/" + item["id"] + "/dismiss", envelope(revision=1))
        assert status == 200 and dismissed["item"]["status"] == "dismissed", dismissed
        assert dismissed["item"]["handoff"] is None


def test_operator_is_separate_non_owner_and_dataset_is_explicit_repeatable(http_preview, active):
    old_id = active["raw"]["user_id"]
    old_uuid = active["raw"]["user_uuid"]
    old_raw = deepcopy(active["raw"])
    status, denied = http_preview(PREFIX + "system/" + preview_domains.DATASET_ID + "/seed_preview", envelope())
    assert status == 403 and denied["code"] == "agent_world_preview_operator_required"
    activate(active)
    assert active["raw"]["user_uuid"] != old_uuid and not active["raw"]["is_owner"]
    assert preview_sandbox.synthetic_operator_access_allowed(active["raw"])
    assert not preview_sandbox.synthetic_operator_access_allowed(old_raw)
    with account_auth._LOCK:
        prior = account_auth._user(account_auth._read_doc(), old_id)
        assert not prior.get("is_preview_operator") and not prior.get("is_owner")
    for domain in preview_domains.SUPPORTED:
        status, empty = http_preview(PREFIX + domain)
        assert status == 200 and empty["items"] == []
    status, system = http_preview(PREFIX + "system")
    assert status == 200 and system["items"][0]["actions"] == ["seed_preview"]
    route = PREFIX + "system/" + preview_domains.DATASET_ID + "/seed_preview"
    status, result = http_preview(route, envelope())
    assert status == 200, result
    assert result["created_count"] == 6 and result["replayed_count"] == 0
    assert all(item["synthetic"] and not item["model_quality_evidence"] for item in result["items"])
    assert {item["status"] for item in result["items"]} == {"draft", "proposed"}
    status, manifest = http_preview(result["manifest_artifact_url"])
    assert status == 200 and manifest["source_kind"] == "preview_fixture" and manifest["synthetic"]
    persona = next(item for item in result["items"] if item["domain"] == "personas")
    status, changed = http_preview(PREFIX + "personas/" + persona["id"] + "/update",
        envelope({"name": "Owner edited fixture"}, key="preview-edit-seed-001", revision=1))
    assert status == 200, changed
    status, repeated = http_preview(route, envelope(key="preview-seed-different-key"))
    assert status == 200 and repeated["replayed"] and repeated["created_count"] == 0, repeated
    current = next(item for item in repeated["items"] if item["id"] == persona["id"])
    assert current["title"] == "Owner edited fixture" and current["revision"] == 2
    assert {item["id"] for item in repeated["items"]} == {item["id"] for item in result["items"]}


def test_dataset_resume_after_partial_failure_is_not_duplication(active, monkeypatch):
    activate(active)
    service = gateway.domain_service_for(handler(active))
    create = service.service.create
    calls = []
    def interrupt(**kwargs):
        calls.append(kwargs["domain"])
        if len(calls) == 4:
            raise ContractError("injected_test_failure")
        return create(**kwargs)
    monkeypatch.setattr(service.service, "create", interrupt)
    with pytest.raises(ContractError, match="injected_test_failure"):
        service.mutate("system", preview_domains.DATASET_ID, "seed_preview", envelope())
    monkeypatch.setattr(service.service, "create", create)
    result = service.mutate("system", preview_domains.DATASET_ID, "seed_preview", envelope())
    assert result["created_count"] == 3 and result["replayed_count"] == 3
    assert len(result["items"]) == len({row["id"] for row in result["items"]}) == 6


def test_operator_forged_marker_and_stale_scenario_do_not_grant_authority(active):
    forged = deepcopy(active["raw"])
    forged["user"]["is_preview_operator"] = True
    assert not preview_sandbox.synthetic_operator_access_allowed(forged)
    activate(active)
    old = deepcopy(active["raw"])
    assert preview_sandbox.synthetic_operator_access_allowed(old)
    activate(active, "trusted_device")
    assert not preview_sandbox.synthetic_operator_access_allowed(old)
    assert not preview_sandbox.synthetic_operator_access_allowed(active["raw"])


@pytest.mark.parametrize("change", [
    {"is_owner": True}, {"device_confirmation_state": "pending"}, {"role": "read_only"},
    {"capabilities": {"ai_lab": False}}, {"ux_mode": "beginner"}, {"active_membership": {}},
    {"workspace_id": "ws_foreign"}, {"user_uuid": str(uuid4())},
    {"user": {"is_preview_user": True, "preview_sandbox_id": "b" * 24}},
])
def test_direct_factory_rejects_forged_scope_or_identity_before_storage(active, change):
    fake = handler(active)
    fake._remote_context = {**active["raw"], **change}
    with pytest.raises(ContractError):
        gateway.domain_service_for(fake)
    assert not (active["root"] / "agent-world.sqlite3").exists()


@pytest.mark.parametrize("environment", ["canary", "production"])
def test_direct_factory_never_opens_non_development_data(active, monkeypatch, environment):
    monkeypatch.setenv("DEPLOYMENT_ENV", environment)
    with pytest.raises(ContractError, match="agent_world_preview_required"):
        gateway.domain_service_for(handler(active))
    assert not (active["root"] / "agent-world.sqlite3").exists()


def test_disabled_preview_missing_control_and_unconfirmed_session_fail_closed(active, monkeypatch):
    with pytest.raises(ContractError, match="agent_world_preview_required"):
        gateway.domain_service_for(handler(active, control=False))
    with monkeypatch.context() as changes:
        changes.setenv("STRATFORGE_PREVIEW_SANDBOX", "0")
        with pytest.raises(ContractError, match="agent_world_preview_required"):
            gateway.domain_service_for(handler(active))
    activate(active, "pending_access")
    with pytest.raises(ContractError, match="agent_world_confirmed_device_required"):
        gateway.domain_service_for(handler(active))
    assert not (active["root"] / "agent-world.sqlite3").exists()


def test_current_session_revocation_and_root_change_invalidate_cached_service(active, monkeypatch, tmp_path):
    service = gateway.domain_service_for(handler(active))
    account_auth.revoke_session(active["token"])
    with pytest.raises(ContractError, match="agent_world_session_expired"):
        service.list("memory")
    activate(active)
    service = gateway.domain_service_for(handler(active))
    with monkeypatch.context() as changes:
        changes.setattr(preview_sandbox, "isolated_root", lambda: tmp_path / "foreign-root")
        with pytest.raises(ContractError, match="agent_world_context_changed"):
            service.list("personas")


def test_flag_revocation_revalidated_and_executor_cannot_be_injected(active, monkeypatch):
    service = gateway.domain_service_for(handler(active))
    monkeypatch.setattr(gateway, "flag_snapshot", lambda _: FlagSnapshot())
    with pytest.raises(ContractError, match="agent_world_disabled"):
        service.list("personas")
    service.service.enqueue = lambda **_: {"job_id": "fake"}
    with pytest.raises(ContractError, match="agent_world_preview_executor_denied"):
        service.mutate("routines", "new", "create", envelope({"title": "No job", "description": "", "interval_minutes": 60}))


def test_foreign_user_list_detail_and_artifacts_are_private(active):
    one = gateway.domain_service_for(handler(active))
    result = one.mutate("memory", "new", "create", envelope({"title": "Private synthetic", "content": "private preview note",
        "purpose": "preview-private", "retention_days": 7}))
    memory = result["item"]
    activate(active, "trusted_device")
    two = gateway.domain_service_for(handler(active))
    assert two.context.user_uuid != one.context.user_uuid
    assert two.list("memory")["items"] == []
    with pytest.raises(ContractError, match="domain_record_not_found"):
        two.list("memory", identity=memory["id"])
    with pytest.raises(ContractError, match="domain_record_not_found"):
        two.mutate("memory", memory["id"], "revoke", envelope({"reason": "Not mine"}, revision=1))
    artifact_id = UUID(memory["content_artifact_url"].rsplit("/", 1)[1])
    assert two.service.repository.get_artifact_by_id(context=two.context, artifact_id=artifact_id) is None


def test_same_workspace_private_and_shared_memory_require_real_scoped_grant(active):
    # Two genuine synthetic sessions, one disposable workspace, existing ledger
    # membership (not a mocked RequestContext or elevated global owner).
    first = dict(active)
    one = gateway.domain_service_for(handler(first))
    created = one.mutate("memory", "new", "create", envelope({"title": "Private fixture",
        "content": "Synthetic scoped content", "purpose": "preview-share", "retention_days": 7}))
    identity = created["item"]["id"]
    activate(active, "trusted_device")
    with workspaces._LOCK:
        doc = workspaces._read_doc()
        workspaces._ensure_membership(doc, workspace_id=one.context.scope.workspace_id,
            user_id=active["raw"]["user_id"], role="operator", created_by=first["raw"]["user_id"])
        workspaces._write_doc(doc)
    workspaces.select_workspace(active["raw"]["user_id"], one.context.scope.workspace_id)
    active["raw"] = server.Handler._decorate_workspace_context(object(), account_auth.authenticate_session(active["token"]))
    two = gateway.domain_service_for(handler(active))
    assert two.context.scope == one.context.scope and not active["raw"]["is_owner"]
    assert two.list("memory")["items"] == []
    with pytest.raises(ContractError, match="domain_record_not_found"):
        two.list("memory", identity=identity)
    one.mutate("memory", identity, "promote", envelope({"reason": "Explicit synthetic review"}, revision=1))
    published = one.mutate("memory", identity, "publish_to_workspace",
        envelope({"reason": "Explicit scoped test publication"}, key="preview-memory-share-001", revision=2))
    shared = published["item"]
    assert shared["visibility"] == "workspace" and shared["synthetic"]
    visible = two.list("memory", identity=shared["id"])
    assert visible["content"] == "Synthetic scoped content" and visible["actions"] == []
    ref = visible["content_artifact_url"].rsplit("/", 1)[1]
    assert two.memory_artifact(shared["id"], ref) is not None
    assert two.service.repository.get_artifact_by_id(context=two.context, artifact_id=UUID(ref)) is None
    one.mutate("memory", identity, "revoke", envelope({"reason": "Withdraw fixture source"},
        key="preview-memory-source-revoke", revision=2))
    assert two.memory_artifact(shared["id"], ref) is None
    assert two.list("memory")["items"] == []


def test_http_guards_reject_missing_control_csrf_origin_and_scope_injection(http_preview):
    route = PREFIX + "personas/new/create"
    body = envelope({"name": "Synthetic"})
    for options in ({"control": False}, {"csrf": False}, {"origin": "https://foreign.invalid"}):
        status, result = http_preview(route, body, **options)
        assert status == 403, result
    for evil in ({**body, "user_uuid": str(uuid4())}, {**body, "workspace_id": "ws_foreign"},
                 {**body, "payload": {"name": "Synthetic", "is_owner": True}},
                 {**body, "payload": {"name": "Synthetic", "api_key": "not-a-real-key"}}):
        status, result = http_preview(route, evil)
        assert status in {400, 403, 409}, result
    status, result = http_preview(PREFIX + "personas?workspace_id=ws_foreign")
    assert status == 409 and result["code"] == "invalid_domain_request"


def test_unsupported_domains_are_honest_and_do_not_execute(http_preview):
    for domain in preview_domains.DOMAINS - preview_domains.SUPPORTED - {"system"}:
        status, data = http_preview(PREFIX + domain)
        assert status == 200 and not data["enabled"] and data["status"] == "EXTERNAL BLOCKED", data
        assert data["items"] == [] and data["actions"] == []
        assert not data["capabilities"]["execution_allowed"]
        status, denied = http_preview(PREFIX + domain + "/new/create", envelope())
        assert status == 403 and denied["code"] == "agent_world_preview_domain_disabled", denied


def test_persona_browser_voice_never_reads_owner_profiles_or_external_backend(http_preview, monkeypatch):
    from app.ai_lab import agent_tts
    def forbidden(*args, **kwargs):
        pytest.fail("Preview must not read owner voice profiles, keys or external TTS")
    monkeypatch.setattr(agent_tts, "get_voice_profile", forbidden)
    monkeypatch.setattr(agent_tts, "resolve_speech_backend", forbidden)
    status, created = http_preview(PREFIX + "personas/new/create", envelope({"name": "Synthetic voice",
        "avatar_key": "ivan", "voice_profile_id": "ivan", "voice_mode": "existing_tts"}))
    assert status == 200, created
    route = PREFIX + "personas/" + created["item"]["id"] + "/speak"
    status, spoken = http_preview(route, envelope({"text": "Это синтетический текст."}, revision=1))
    assert status == 200, spoken
    assert spoken["fallback"] == "browser" and spoken["synthetic"] and not spoken.get("audio")
    assert not spoken["owner_tts_authorized"]
    assert spoken["voice_fallback_reason"] == "own_tts_connection_required"
    status, stale = http_preview(route, envelope({"text": "Stale"}, revision=2))
    assert status == 409 and stale["code"] == "persona_voice_revision_changed"


def test_dataset_operator_scope_session_marker_revocation(active):
    activate(active)
    service = gateway.domain_service_for(handler(active))
    with account_auth._LOCK:
        doc = account_auth._read_doc()
        account_auth._user(doc, active["raw"]["user_id"])["is_preview_operator"] = False
        account_auth._write_doc(doc)
    assert service.list("system")["preview_dataset"]["actions"] == []
    with pytest.raises(ContractError, match="agent_world_preview_operator_required"):
        service.mutate("system", preview_domains.DATASET_ID, "seed_preview", envelope())
    assert service.list("personas")["items"] == []


def test_new_user_scenario_stays_manual_and_has_no_agent_world_dataset(active):
    result = preview_sandbox.activate_scenario("new_user", device_credential="preview-manual-registration-device")
    assert not result["authenticated"] and "session_token" not in result
    assert preview_sandbox._STATE["current_user_id"] == 0
    assert not (active["root"] / "agent-world.sqlite3").exists()


def test_malformed_mutations_and_pagination_fail_without_records(active):
    service = gateway.domain_service_for(handler(active))
    for malformed in (None, [], {"payload": []}, {"payload": {}, "idempotency_key": "short"},
            envelope({"name": "No write"}, revision=True), envelope({"name": "No write"}, revision=0.0),
            envelope({"name": "No write"}, revision=-1), envelope({"name": "No write"}, revision="0"),
            {**envelope({"name": "No write"}), "capabilities": {"is_owner": True}}):
        with pytest.raises(ContractError):
            service.mutate("personas", "new", "create", malformed)
    for params in ({"limit": 0}, {"limit": 101}, {"limit": True}, {"cursor": "not a cursor"}):
        with pytest.raises(ContractError):
            service.list("system", **params)
    assert service.list("personas")["items"] == []


def test_fixture_domains_and_existing_demo_tasks_coexist_without_fake_task_counts(http_preview, active):
    activate(active)
    status, seeded = http_preview(PREFIX + "system/" + preview_domains.DATASET_ID + "/seed_preview", envelope())
    assert status == 200 and seeded["created_count"] == 6, seeded
    status, before = http_preview(gateway.PREFIX + "overview")
    assert status == 200 and before["stats"]["tasks_total"] == 0, before
    status, run = http_preview(gateway.PREFIX + "demo-runs", {"idempotency_key": "preview-domain-demo-coexist"})
    assert status == 200, run
    status, after = http_preview(gateway.PREFIX + "overview")
    assert status == 200 and after["stats"]["tasks_total"] == 4, after
    assert after["stats"]["paid_calls"] == 0
    status, personas = http_preview(PREFIX + "personas")
    assert status == 200 and len(personas["items"]) == 6, personas
    assert all(item["synthetic"] for item in personas["items"])
    assert all(not row["evaluation"]["model_quality_assessed"] for row in after["agents"])
