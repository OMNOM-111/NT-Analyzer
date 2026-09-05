"""Explicit publication with real isolated repositories, no owner data/network."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import replace
from types import SimpleNamespace
from uuid import UUID

import pytest

from app import community, preview_sandbox, runtime_env, storage_router
from app.ai_control_center import contracts as c
from app.ai_control_center.social_publication import SocialPublicationService
from app.ai_control_center.states import ContractError, EntityKind
from tests.test_agent_world_domain_service import env, model_service_fixture, act, decision, create
from tests.test_agent_world_storage import arguments, context, update


@pytest.fixture
def social(env, monkeypatch, tmp_path):
    monkeypatch.setenv("STRATFORGE_ENV", "development")
    monkeypatch.setattr(preview_sandbox, "enabled", lambda: False)
    monkeypatch.setattr(runtime_env, "is_development", lambda: True)
    monkeypatch.setattr(storage_router, "production_enabled", lambda: False)
    path = tmp_path / "isolated-social.json"
    monkeypatch.setattr(community, "_store_path", lambda: path)
    monkeypatch.setattr(community, "_account_registered_at", lambda _: "2026-09-05T00:00:00Z")
    service, ids, calls = model_service_fixture(env)
    task = service.start_task(context=env.ctx, model_id=ids[0], payload={"rubric_key": "json_arithmetic"},
                              idempotency_key="social-real-task-001")
    completed = service.execute(context=env.ctx, task_id=task["id"])
    return SimpleNamespace(env=env, models=service, model_ids=ids, calls=calls, source_id=completed["outcome_id"],
                           service=SocialPublicationService(env.repo), path=path, kind="outcome")


def prepare(social, **changes):
    args = dict(context=social.env.ctx, admit=social.env.admit, source_kind=social.kind, source_id=social.source_id)
    return social.service.prepare(**{**args, **changes})


def publish(social, prepared=None, **changes):
    prepared = prepared or prepare(social)
    args = dict(context=social.env.ctx, admit=social.env.admit, user_id=42,
                source_kind=social.kind, source_id=social.source_id, confirm_permanent=True,
                approved_snapshot_sha256=prepared["snapshot_sha256"], expected_revision=prepared["source_revision"],
                idempotency_key="social-publication-0001", text="My reviewed bounded observation", visibility="network")
    return social.service.publish(**{**args, **changes})


def counts(social):
    with sqlite3.connect(social.env.repo.path) as connection:
        return tuple(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                     for table in ("aw_records", "aw_revisions", "aw_events", "aw_artifacts"))


def test_prepare_is_read_only_allowlisted_and_not_an_automatic_post(social):
    before = counts(social)
    proposed = prepare(social)
    assert proposed["permanent"] and proposed["requires_explicit_confirmation"]
    assert proposed["source_revision"] == 2 and len(proposed["snapshot_sha256"]) == 64
    assert proposed["snapshot"]["source_kind"] == "real_model_response"
    assert proposed["snapshot"]["metrics"]["Observed score %"] == 100
    assert counts(social) == before and not social.path.exists()
    public = json.dumps(proposed)
    for private in ("fixture-placeholder-only", "[17, -4, 12, 9]", "api_key", '"response"', '"prompt"', '"input"', "requester_user_uuid"):
        assert private not in public
    assert len(social.calls) == 1


def test_explicit_publication_reuses_sf_social_permanence_private_approval_and_durable_replay(social):
    proposed = prepare(social)
    result = publish(social, proposed)
    assert result["ok"] and not result["deduplicated"] and result["published_to"] == "sf_social"
    assert result["post"]["permanent"] and not result["post"]["can_delete"]
    assert result["post"]["author"]["profile_id"] and result["post"]["is_author"]
    assert result["post"]["object"]["publication_approval"]["explicit_human"]
    approval = social.env.repo.get_artifact_by_id(context=social.env.ctx, artifact_id=UUID(result["approval"]["artifact_id"]))
    data = json.loads(approval[1])
    assert data["actor"] == c.primitive(social.env.ctx.actor)
    assert data["requester_user_uuid"] == str(social.env.ctx.user_uuid)
    assert "requester_user_uuid" not in json.dumps(result["post"])
    assert social.env.repo.get_artifact_by_id(context=context(user=2), artifact_id=approval[0].artifact_id) is None
    before = counts(social)
    social.service = SocialPublicationService(social.env.repo)
    duplicate = publish(social, proposed)
    assert duplicate["deduplicated"] and duplicate["post"]["post_id"] == result["post"]["post_id"]
    assert duplicate["approval"] == result["approval"] and counts(social) == before
    assert len(community._load()["posts"]) == 1 and len(social.calls) == 1


@pytest.mark.parametrize("changes,code", [
    ({"confirm_permanent": False}, "confirmation_required"),
    ({"confirm_permanent": "yes"}, "confirmation_required"),
    ({"approved_snapshot_sha256": "a" * 64}, "snapshot_changed"),
    ({"expected_revision": 999}, "snapshot_changed"),
    ({"expected_revision": True}, "snapshot_required"),
    ({"user_id": True}, "server_identity"),
    ({"idempotency_key": "tiny"}, "idempotency_required"),
    ({"visibility": "all_workspaces"}, "visibility_invalid"),
    ({"text": "api_key=accidental-private-key"}, "text_invalid"),
    ({"text": "Bearer veryprivatecredentialvalue123"}, "text_invalid"),
    ({"text": "x" * 4001}, "text_invalid"),
])
def test_publish_validation_is_explicit_and_never_creates_a_post(social, changes, code):
    with pytest.raises(ContractError, match=code):
        publish(social, **changes)
    assert not social.path.exists()


@pytest.mark.parametrize("kind", ["memory", "artifact", "execution", "persona", "unknown"])
def test_arbitrary_private_artifacts_and_memory_never_become_public_sources(social, kind):
    with pytest.raises(ContractError, match="source_kind_denied"):
        prepare(social, source_kind=kind)
    assert not social.path.exists()


@pytest.mark.parametrize("other", [context(user=2), context(workspace="ws_other12345")])
def test_foreign_user_and_workspace_sources_not_visible_or_publishable(social, other):
    with pytest.raises(ContractError, match="source_not_found"):
        prepare(social, context=other)
    assert not social.path.exists()


@pytest.mark.parametrize("mode", ["preview", "canary", "production", "agent", "denied"])
def test_preview_nonlocal_agent_and_revoked_admission_fail_closed(social, monkeypatch, mode):
    if mode == "preview":
        monkeypatch.setattr(preview_sandbox, "enabled", lambda: True)
    elif mode in {"canary", "production"}:
        monkeypatch.setattr(runtime_env, "is_development", lambda: False)
    elif mode == "agent":
        social.env.ctx = c.RequestContext(scope=social.env.ctx.scope, user_uuid=social.env.ctx.user_uuid,
            actor=c.ActorRef(kind=c.ActorKind.AGENT, actor_id=UUID(int=90), on_behalf_of=social.env.ctx.user_uuid))
    else:
        social.env.admit = lambda: False
    with pytest.raises(ContractError, match="admission"):
        prepare(social)
    assert not social.path.exists()


def test_same_key_changed_body_conflicts_without_duplicate_or_rewrite(social):
    result = publish(social)
    original = social.path.read_bytes()
    with pytest.raises(ContractError, match="idempotency_conflict"):
        publish(social, text="A different claim")
    assert social.path.read_bytes() == original
    assert community._load()["posts"][0]["post_id"] == result["post"]["post_id"]


def test_crash_after_post_commit_repairs_by_existing_community_idempotency(social):
    original = community.create_social_post

    def uncertain(*args, **kwargs):
        original(*args, **kwargs)
        raise OSError("fixture response lost after the actual store commit")

    social.service.community = SimpleNamespace(create_social_post=uncertain)
    with pytest.raises(OSError, match="response lost"):
        publish(social)
    social.service.community = community
    result = publish(social)
    assert result["deduplicated"] and len(community._load()["posts"]) == 1


def test_source_revocation_after_prepare_and_fresh_admission_before_effect(social):
    proposed = prepare(social)
    outcome = social.env.repo.get(context=social.env.ctx, kind=EntityKind.OUTCOME, entity_id=UUID(social.source_id))
    social.env.repo.commit(**arguments(update(outcome, status="disputed"), ctx=social.env.ctx))
    with pytest.raises(ContractError, match="verified_source_required"):
        publish(social, proposed)
    assert not social.path.exists()


def test_revocation_during_approval_prevents_social_effect(social, monkeypatch):
    original = social.env.repo.put_artifact

    def revoke(**kwargs):
        result = original(**kwargs)
        social.env.state.allowed = False
        return result

    monkeypatch.setattr(social.env.repo, "put_artifact", revoke)
    with pytest.raises(ContractError, match="access_revoked"):
        publish(social)
    assert not social.path.exists()


def test_corrupted_receipt_hash_is_never_attested(social):
    outcome = social.env.repo.get(context=social.env.ctx, kind=EntityKind.OUTCOME, entity_id=UUID(social.source_id))
    with sqlite3.connect(social.env.repo.path) as connection:
        connection.execute("UPDATE aw_artifacts SET content=? WHERE artifact_id=?", (b'{"tampered":true}', str(outcome.evidence[0].artifact_id)))
    with pytest.raises(ContractError, match="integrity"):
        prepare(social)
    assert not social.path.exists()


@pytest.mark.parametrize("target,changes,code", [
    ("checkpoint", {"synthetic": True}, "real_source_required"),
    ("checkpoint", {"source": "owner_preview"}, "real_source_required"),
    ("receipt", {"synthetic": True}, "receipt_mismatch"),
    ("receipt", {"request_sha256": "a" * 64}, "receipt_mismatch"),
    ("verification", {"self_scored": True}, "evaluation_mismatch"),
    ("verification", {"observed_score_pct": 1}, "evaluation_mismatch"),
])
def test_synthetic_or_mismatched_semantic_receipts_fail_even_with_readable_json(social, monkeypatch, target, changes, code):
    outcome = social.env.repo.get(context=social.env.ctx, kind=EntityKind.OUTCOME, entity_id=UUID(social.source_id))
    task = social.env.repo.get(context=social.env.ctx, kind=EntityKind.TASK, entity_id=outcome.task.entity_id)
    refs = {"checkpoint": task.checkpoint, "receipt": outcome.evidence[0], "verification": outcome.verification}
    original = social.service._json

    def changed(context, ref):
        value = original(context, ref)
        return {**value, **changes} if ref == refs[target] else value

    monkeypatch.setattr(social.service, "_json", changed)
    with pytest.raises(ContractError, match=code):
        prepare(social)
    assert not social.path.exists()


def test_real_court_receipts_publish_only_advisory_vote_counts_not_private_packet(social):
    social.env.service.judge_runner = social.models.judge
    item = decision(social.env)
    reviewed = act(social.env, item, "decisions", "review", {"model_ids": social.model_ids}, key="social-court-review-001")["item"]
    social.kind, social.source_id = "decision", reviewed["id"]
    proposed = prepare(social)
    assert proposed["snapshot"]["metrics"] == {"Approve": 2, "Reject": 1, "Abstain": 0}
    assert proposed["snapshot"]["execution_allowed"] is False
    public = json.dumps(publish(social)["post"])
    assert "Accept the historical analysis" not in public and "Isolated mocked transport" not in public
    assert '"rationale"' not in public and '"packet"' not in public


def test_internal_explicit_model_authorization_cannot_be_relabelled_as_court(social):
    decisions = social.env.service.list(context=social.env.ctx, admit=social.env.admit, domain="decisions")["items"]
    internal = next(row for row in decisions if row["decision_type"] == "explicit_task_authorization")
    with pytest.raises(ContractError, match="verified_decision_required"):
        prepare(social, source_kind="decision", source_id=internal["id"])


def test_application_outcome_requires_actual_bound_png_and_cannot_publish_only_model_plan(social):
    from tests.test_agent_world_live_charts import _png
    models, ctx = social.models, social.env.ctx
    spec = {"instrument": "MNQ 09-26", "timeframe": "5m"}
    planned = models.plan_application(context=ctx, model_id=social.model_ids[0], spec=spec, kind="chart",
        idempotency_key="social-chart-plan-001", conversation_id="social-chat", message_id="message-chart-001")
    models.executor = lambda **_: {"ok": True, "response": json.dumps(spec), "actual_model": "fixture",
        "elapsed_sec": .01, "cost_known": True, "cost_usd": 0, "application_cache_hit": False}
    planned = models.execute(context=ctx, task_id=planned["id"])
    assert planned["status"] == "waiting"
    with pytest.raises(ContractError, match="verified_source_required"):
        prepare(social, source_id=planned["outcome_id"])
    task = models._get(ctx, EntityKind.TASK, planned["id"])
    checkpoint = models._json(ctx, task.checkpoint)
    checkpoint["application_dispatch"] = {"source_id": "chart_social_001", "source_task_id": "chart-task-fixture"}
    models._change(ctx, task, checkpoint=models._put(ctx, checkpoint))
    artifact = models.repository.put_artifact(context=ctx, content=_png(), media_type="image/png")
    verification = {"verified": True, "synthetic": False, "source_kind": "desktop_chart", "source_id": "chart_social_001",
        "sha256": artifact.sha256, "source_sha256": artifact.sha256,
        "request_sha256": planned["application_request"]["request_sha256"]}
    result = models.record_application_result(context=ctx, task_id=planned["id"], source_id="chart_social_001",
                                               verification=verification, artifact_refs=(artifact,))
    social.source_id = result["outcome_id"]
    prepared = prepare(social)
    assert prepared["snapshot"]["source_kind"] == "desktop_chart"
    assert prepared["snapshot"]["metrics"] == {"Evidence files": 1}
    assert publish(social, prepared)["ok"]
    with pytest.raises(ContractError, match="evaluation_mismatch"):
        prepare(social, source_id=planned["outcome_id"])


def test_optional_existing_backtest_loader_must_attest_real_scoped_files(social):
    calls = []
    job_id = "awnt_real_local_001"
    detail = {"task": {"source_job_id": job_id, "source_kind": "ninjatrader_report", "synthetic": False,
                       "status": "succeeded", "source_status": "done", "updated_at": "2026-09-05T12:00:00Z"},
              "verification": {"passed": True, "reasons": [], "source_checksums": {
                  name: hashlib.sha256(name.encode()).hexdigest() for name in ("result.json", "trades.json", "bars.json", "job.json")}},
              "result": {"source_job_id": job_id, "synthetic": False, "metrics": {"net_profit": -20, "trade_count": 64},
                         "private_path": "DO_NOT_SHARE"}}

    def load(**kwargs):
        assert kwargs["context"] == social.env.ctx
        kwargs["admit"]()
        calls.append(kwargs)
        return detail

    social.kind, social.source_id = "backtest", job_id
    social.service.backtest_loader = load
    prepared = prepare(social)
    assert prepared["snapshot"]["metrics"]["Net P&L"] == -20
    assert "DO_NOT_SHARE" not in json.dumps(prepared)
    detail["verification"]["source_checksums"]["result.json"] = "b" * 64
    with pytest.raises(ContractError, match="snapshot_changed"):
        publish(social, prepared)
    assert not social.path.exists() and calls
    detail["task"]["synthetic"] = True
    with pytest.raises(ContractError, match="verified_source_required"):
        prepare(social)


@pytest.mark.parametrize("after_commission", [False, True])
def test_model_linked_backtest_outcome_publishes_frozen_allowlisted_metrics_not_source_files(social, after_commission):
    from tests.test_agent_world_live_backtests import _spec
    models, ctx, spec = social.models, social.env.ctx, _spec()
    planned = models.plan_application(context=ctx, model_id=social.model_ids[0], spec=spec, kind="backtest",
        idempotency_key="social-backtest-plan-001", conversation_id="social-chat", message_id="message-backtest-001")
    models.executor = lambda **_: {"ok": True, "response": json.dumps(spec), "actual_model": "fixture",
        "elapsed_sec": .01, "cost_known": True, "cost_usd": 0, "application_cache_hit": False}
    planned = models.execute(context=ctx, task_id=planned["id"])
    task = models._get(ctx, EntityKind.TASK, planned["id"])
    checkpoint = models._json(ctx, task.checkpoint)
    source_id = "awnt_social_fixture_001"
    checkpoint["application_dispatch"] = {"source_id": source_id, "source_task_id": "ninja-task-fixture"}
    models._change(ctx, task, checkpoint=models._put(ctx, checkpoint))
    checksums = {name: hashlib.sha256(name.encode()).hexdigest() for name in ("result.json", "trades.json", "bars.json", "job.json")}
    metrics = {"net_profit": -123, "trade_count": 64, "profit_factor": .7541}
    if after_commission:
        metrics.update(net_profit_after_commission=-969.7, profit_factor_after_commission=.725188)
    summary = {"representation": "verified_existing_report_summary", "source_kind": "ninjatrader_report", "source_id": source_id,
        "synthetic": False, "model_task_id": planned["id"], "request_sha256": planned["application_request"]["request_sha256"],
        "source_checksums": checksums, "result": {"metrics": metrics, "trades": "PRIVATE-TRADE-ROWS"}}
    artifact = models._put(ctx, summary)
    proof = {"verified": True, "synthetic": False, "source_kind": "ninjatrader_report", "source_id": source_id,
        "sha256": artifact.sha256, "source_sha256": checksums["result.json"], "source_checksums": checksums,
        "request_sha256": summary["request_sha256"]}
    result = models.record_application_result(context=ctx, task_id=planned["id"], source_id=source_id,
                                               verification=proof, artifact_refs=(artifact,))
    social.source_id = result["outcome_id"]
    prepared = prepare(social)
    basis = "after commission" if after_commission else "before commission"
    assert prepared["snapshot"]["metrics"][f"Net P&L ({basis})"] == (-969.7 if after_commission else -123)
    assert prepared["snapshot"]["metrics"][f"Profit factor ({basis})"] == (.7252 if after_commission else .7541)
    assert prepared["snapshot"]["metrics"]["Trades"] == 64
    assert social.models._json(ctx, artifact) == summary
    assert "PRIVATE-TRADE-ROWS" not in json.dumps(prepared)
    assert publish(social, prepared)["ok"]
