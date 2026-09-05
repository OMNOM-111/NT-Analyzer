"""Characterization at actual legacy boundaries, without connecting new paths."""
from __future__ import annotations

import ast
import copy
import json
import re
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from uuid import UUID

import pytest

from app import durable
from app.ai_lab import chief_agent, domain_agents, registry
from app.ai_control_center import adapters as a, contracts as c, flags as f
from app.ai_control_center.states import ContractError


SCOPE = c.TenantScope(environment=c.Environment.DEVELOPMENT, workspace_id="ws_example01")
USER = UUID(int=1)
APP = Path(__file__).resolve().parents[1] / "app"


def binding(source="agent_registry", source_id="source-1", scope=SCOPE):
    return a.LegacyBinding(scope=scope, owner_user_uuid=USER, source=source, source_id=source_id,
                           evidence=c.SnapshotRef(artifact_id=UUID(int=90), sha256="a" * 64, scope=scope))


def rule(flag=f.Flag.AI_CONTROL_CENTER_READ_MODEL, *, scope=SCOPE, workspace=False, enabled=True):
    return f.FlagRule(environment=scope.environment, flag=flag, enabled=enabled,
                      workspace_id=scope.workspace_id if workspace else None)


def config(*rules):
    return f.FlagSnapshot(revision="reviewed-test-config", rules=rules, audit_ref=UUID(int=91))


def enabled(*flags, scope=SCOPE):
    return config(*(row for flag in flags for row in
                    (rule(flag, scope=scope), rule(flag, scope=scope, workspace=True))))


@pytest.mark.parametrize("environment", list(c.Environment))
@pytest.mark.parametrize("flag", list(f.Flag))
def test_every_new_path_defaults_off_in_each_environment(environment, flag, monkeypatch):
    # A conventional env var cannot accidentally turn on a new runtime path.
    monkeypatch.setenv(flag.value, "true")
    decision = f.resolve(flag, scope=replace(SCOPE, environment=environment))
    assert not decision.enabled
    assert decision.reason == "environment_disabled"
    assert decision.revision == "disabled-v1"
    assert f.REGISTRY[flag].default is False


def test_enable_requires_both_exact_workspace_and_environment_gate():
    flag = f.Flag.AI_CONTROL_CENTER_READ_MODEL
    assert f.resolve(flag, scope=SCOPE, snapshot=config(rule())).reason == "workspace_disabled"
    assert f.resolve(flag, scope=SCOPE, snapshot=config(rule(workspace=True))).reason == "environment_disabled"
    active = enabled(flag)
    assert f.resolve(flag, scope=SCOPE, snapshot=active).enabled
    for foreign in (replace(SCOPE, environment=c.Environment.CANARY),
                    replace(SCOPE, environment=c.Environment.PRODUCTION),
                    replace(SCOPE, workspace_id="ws_example02")):
        assert not f.resolve(flag, scope=foreign, snapshot=active).enabled
    killed = config(rule(enabled=False), rule(workspace=True))
    assert f.resolve(flag, scope=SCOPE, snapshot=killed).reason == "environment_disabled"


def test_dependencies_use_same_scope_and_kill_switch_is_transitive():
    read, task, consensus, court = (f.Flag.AI_CONTROL_CENTER_READ_MODEL, f.Flag.AI_TASK_GRAPH_V2,
                                    f.Flag.AI_CONSENSUS_V2, f.Flag.AI_COURT_V1)
    partial = enabled(task, consensus, court)
    decision = f.resolve(court, scope=SCOPE, snapshot=partial)
    assert not decision.enabled and decision.blocked_by == consensus
    active = enabled(read, task, consensus, court)
    assert f.resolve(court, scope=SCOPE, snapshot=active).enabled
    killed = replace(active, rules=tuple(replace(row, enabled=False) if row.flag == read
                                         and row.workspace_id is None else row for row in active.rules))
    assert not f.resolve(court, scope=SCOPE, snapshot=killed).enabled
    assert not f.resolve(f.Flag.AI_EXECUTION_V2, scope=SCOPE, snapshot=active).enabled


@pytest.mark.parametrize("bad", ["false", "true", 0, 1, None])
def test_flag_boolean_coercion_is_forbidden(bad):
    with pytest.raises(ContractError, match="flag_boolean_required"):
        rule(enabled=bad)


def test_flag_configuration_is_typed_immutable_audited_and_unambiguous():
    with pytest.raises(ContractError, match="flag_audit_reference_required"):
        f.FlagSnapshot(rules=(rule(),))
    with pytest.raises(ContractError, match="duplicate_flag_rule"):
        config(rule(), rule(enabled=False))
    with pytest.raises(ContractError, match="immutable_tuple_required"):
        f.FlagSnapshot(rules=[rule()], audit_ref=UUID(int=91))
    with pytest.raises(ContractError, match="invalid_enum"):
        f.resolve("AI_COURT_V1", scope=SCOPE)
    with pytest.raises(ContractError, match="flag_scope_and_snapshot_required"):
        f.resolve(f.Flag.AI_COURT_V1, scope=None)
    with pytest.raises(ContractError, match="invalid_workspace"):
        f.FlagRule(environment=c.Environment.DEVELOPMENT, flag=f.Flag.AI_COURT_V1,
                   workspace_id="*", enabled=True)
    with pytest.raises(TypeError):
        f.REGISTRY[f.Flag.AI_COURT_V1] = None
    with pytest.raises(FrozenInstanceError):
        f.DISABLED.rules = (rule(),)


def test_projection_ids_are_stable_separate_and_tenant_bound():
    first = a.legacy_uuid(SCOPE, "persona", "same-id")
    assert first == a.legacy_uuid(SCOPE, "persona", "same-id")
    assert first != a.legacy_uuid(SCOPE, "agent_role", "same-id")
    for foreign in (replace(SCOPE, environment=c.Environment.CANARY),
                    replace(SCOPE, workspace_id="ws_example02")):
        assert first != a.legacy_uuid(foreign, "persona", "same-id")
    assert a.legacy_uuid(SCOPE, "a:b", "c") != a.legacy_uuid(SCOPE, "a", "b:c")


def test_actual_persona_roster_and_management_tiers_are_not_rewritten():
    roster = {**domain_agents.PERSONAS, **domain_agents.MANAGEMENT}
    original = copy.deepcopy(roster)
    for source_id, row in roster.items():
        projected = a.project_persona_role(row, binding=binding("domain_agents", source_id))
        assert projected.display_name == row["name"]
        assert projected.role_key == row["role"]
        assert projected.persona_id != projected.role_id
        assert projected.legacy_management_level == row.get("level")
        assert "capabilities" not in c.primitive(projected)  # Legacy prose is not a grant.
    assert roster == original


def test_provider_projection_cannot_export_credentials_endpoints_or_prompts():
    sentinel = "DO-NOT-EXPORT-THIS-PRIVATE-FIXTURE"
    row = dict(id="source-1", provider="example_provider", model="family/model-v1", enabled=True,
               endpoint_type="chat", api_key=sentinel, api_key_masked=sentinel,
               base_url=sentinel, purpose=sentinel, usage={"private": sentinel}, role="coder")
    original = copy.deepcopy(row)
    projected = a.project_provider_model(row, binding=binding())
    serialized = json.dumps(c.primitive(projected))
    assert sentinel not in serialized
    assert row == original
    assert projected.provider_account_id != projected.model_id
    another_account = a.project_provider_model({**row, "id": "source-2"},
                                               binding=binding(source_id="source-2"))
    assert another_account.model_id == projected.model_id
    assert another_account.provider_account_id != projected.provider_account_id
    foreign = replace(SCOPE, workspace_id="ws_example02")
    assert a.project_provider_model(row, binding=binding(scope=foreign)).model_id != projected.model_id


@pytest.mark.parametrize("field,value", [
    ("workspace_id", "ws_example02"), ("workspace_id", ""),
    ("environment", "production"), ("user_uuid", str(UUID(int=99))),
    ("owner_user_uuid", str(UUID(int=99))),
])
def test_binding_never_overrides_explicit_legacy_ownership(field, value):
    row = dict(id="source-1", provider="example", model="model", enabled=False, endpoint_type="chat")
    with pytest.raises(ContractError, match="legacy_scope_mismatch"):
        a.project_provider_model({**row, field: value}, binding=binding())


def test_global_sources_require_trusted_binding_not_an_implicit_owner():
    row = dict(id="source-1", provider="example", model="model", enabled=False, endpoint_type="chat")
    with pytest.raises(ContractError, match="legacy_binding_required"):
        a.project_provider_model(row, binding=None)
    with pytest.raises(ContractError, match="legacy_source_mismatch"):
        a.project_provider_model(row, binding=binding(source_id="other-source"))
    with pytest.raises(ContractError, match="binding_evidence_required"):
        replace(binding(), evidence=None)


def test_every_actual_experiment_status_preserves_source_without_claiming_outcome():
    assert set(a.STATUS_MAP["experiment"]) == registry.VALID_STATUSES
    for status in registry.VALID_STATUSES:
        row = {"experiment_id": "EXP-20260904-0001", "status": status, "notes": "private fixture"}
        original = dict(row)
        projected = a.project_work(row, binding=binding("experiment", row["experiment_id"]))
        assert projected.status.legacy_status == status
        assert projected.status.phase != a.Phase.UNKNOWN
        assert projected.status.phase != a.Phase.SUCCEEDED
        assert row == original
    for status in registry.PORTFOLIO_ELIGIBLE_STATUSES | {"backtest_done", "analysis_ready"}:
        assert a.project_status("experiment", status).review_required


def test_actual_chat_work_lifecycle_keeps_owner_decision_and_completion_distinct():
    assert set(a.STATUS_MAP["conversation_work"]) == chief_agent._CONVERSATION_WORK_STATES
    scenarios = (([], "Уточните цель?", a.Phase.REVIEW),
                 ([{"name": "start_research", "status": "queued"}], "Принято", a.Phase.RUNNING),
                 ([{"name": "mission_completed"}], "Готово", a.Phase.SUCCEEDED),
                 ([{"name": "start_research", "status": "blocked"}], "Нет доступа", a.Phase.BLOCKED))
    for actions, reply, expected in scenarios:
        status, _detail = chief_agent._conversation_work_state(actions, reply)
        assert a.project_status("conversation_work", status).phase == expected


@pytest.mark.parametrize("table,source", [("sf_jobs", "postgres_job"), ("sf_commands", "command")])
def test_postgres_compatibility_map_matches_existing_schema_not_a_new_queue(table, source):
    schema = (APP / "production_storage/migrations/0001_authoritative_storage.sql").read_text(encoding="utf-8")
    declaration = schema.split(f"CREATE TABLE IF NOT EXISTS {table} (", 1)[1].split("\n);", 1)[0]
    statuses = re.search(r"CHECK \(status IN \(([^)]+)\)\)", declaration)
    assert statuses is not None
    assert set(re.findall(r"'([^']+)'", statuses.group(1))) == set(a.STATUS_MAP[source])
    # A completed command is only a transport receipt, never independent verification.
    assert a.project_status(source, "completed").source == source


def test_existing_local_queue_results_are_projected_without_dispatch_or_rewrite(tmp_path, monkeypatch):
    monkeypatch.setenv("NT_ANALYZER_SQLITE_PATH", str(tmp_path / "worker.sqlite3"))
    row = durable.enqueue_worker_job(tmp_path, worker_job_id="worker-projection", kind="noop",
                                     workspace_id=SCOPE.workspace_id, user_id=1)
    source = binding("local_worker", row["worker_job_id"])
    assert a.project_work(row, binding=source).status.phase == a.Phase.READY
    running = durable.claim_worker_job(tmp_path, worker_id="characterization-worker")
    assert a.project_work(running, binding=source).status.phase == a.Phase.RUNNING
    complete = durable.finish_worker_job(tmp_path, row["worker_job_id"], {"ok": True},
                                          worker_id="characterization-worker")
    before = durable.get_worker_job(tmp_path, row["worker_job_id"])
    projected = a.project_work(complete, binding=source)
    assert projected.status.phase == a.Phase.SUCCEEDED
    assert projected.status.source == "local_worker"  # Never an Outcome or domain Task.
    assert durable.get_worker_job(tmp_path, row["worker_job_id"]) == before
    with pytest.raises(ContractError, match="legacy_scope_mismatch"):
        a.project_work(complete, binding=binding("local_worker", row["worker_job_id"],
                                                 scope=replace(SCOPE, workspace_id="ws_example02")))


@pytest.mark.parametrize("source,status", [("postgres_job", "dead_letter"), ("local_worker", "stale"),
                                           ("new_source", "completed"), ("command", "new_status")])
def test_unresolved_legacy_states_require_review(source, status):
    result = a.project_status(source, status)
    assert result.review_required
    assert result.phase in {a.Phase.REVIEW, a.Phase.UNKNOWN}


def test_foundation_core_stays_pure_and_runtime_composition_is_narrow():
    # Stage 2+ enables only the reviewed HTTP composition. Core contracts still
    # do not own IO, permissions, execution, queues or runtime configuration.
    violations = []
    pure_modules = {"contracts.py", "states.py", "events.py", "flags.py", "repositories.py", "adapters.py"}
    for path in APP.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        foundation = "ai_control_center" in path.parts
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""] + [alias.name for alias in node.names]
            else:
                continue
            if not foundation and path.name not in {"server.py", "chief_agent.py"} and any("ai_control_center" in name for name in names):
                violations.append(f"{path.name}: runtime importer")
            if foundation and path.name in pure_modules and any(name.split(".")[0] in {
                "os", "pathlib", "socket", "requests", "urllib", "sqlite3", "subprocess", "threading", "asyncio",
            } for name in names):
                violations.append(f"{path.name}: IO dependency")
    assert violations == []
