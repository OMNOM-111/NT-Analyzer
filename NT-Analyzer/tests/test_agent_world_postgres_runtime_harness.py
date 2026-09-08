"""Pure safety contracts of the disposable PG runtime acceptance tool."""
import importlib.util
from pathlib import Path

import pytest


@pytest.fixture
def harness():
    path = Path(__file__).resolve().parents[1] / "deploy/testing/agent-world-postgres-runtime-acceptance.py"
    spec = importlib.util.spec_from_file_location("aw_pg_acceptance_tool", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_clean_environment_never_inherits_owner_or_production_credentials(harness, monkeypatch):
    monkeypatch.setenv("STRATFORGE_DATABASE_URL", "fixture-production-not-a-real-key")
    monkeypatch.setenv("OPENAI_API_KEY", "fixture-only")
    monkeypatch.setenv("AZURE_API_KEY", "fixture-only")
    monkeypatch.setenv("NTA_TELEGRAM_TOKEN", "fixture-only")
    monkeypatch.setenv("STRATFORGE_DEVELOPMENT_DATA_ROOT", "fixture-owner-data")
    monkeypatch.setenv("PATH", "fixture-runtime-path")
    assert harness.clean_environment()["PATH"] == "fixture-runtime-path"
    assert not any(key in harness.clean_environment() for key in (
        "STRATFORGE_DATABASE_URL", "OPENAI_API_KEY", "AZURE_API_KEY", "NTA_TELEGRAM_TOKEN",
        "STRATFORGE_DEVELOPMENT_DATA_ROOT"))


@pytest.mark.parametrize("host", ["8.8.8.8", "192.168.1.1", "api.deepseek.com", "::", "0.0.0.0"])
@pytest.mark.parametrize("event", ["socket.connect", "socket.getaddrinfo", "socket.sendto"])
def test_external_egress_is_denied_instead_of_using_a_provider(harness, event, host):
    args = (host, 443) if event == "socket.getaddrinfo" else (None, (host, 443))
    with pytest.raises(OSError, match="external_network_denied"):
        harness.loopback_guard(event, args)


@pytest.mark.parametrize("host", ["127.0.0.1", "::1", "localhost"])
def test_own_loopback_http_and_postgres_are_permitted(harness, host):
    harness.loopback_guard("socket.connect", (None, (host, 8805)))
    harness.loopback_guard("socket.getaddrinfo", (host, 55387))


def test_workdir_is_a_named_child_of_the_ignored_acceptance_directory(harness, monkeypatch, tmp_path):
    monkeypatch.setattr(harness, "CODE", tmp_path)
    allowed = tmp_path / ".artifacts" / "pg-runtime-acceptance-fixture"
    assert harness.checked_workdir(allowed) == allowed.resolve()
    for path in (tmp_path, tmp_path / ".artifacts", tmp_path / "data",
                 tmp_path / ".artifacts" / "other-runtime", tmp_path.parent):
        with pytest.raises(RuntimeError, match="outside_ignored_scope"):
            harness.checked_workdir(path)


@pytest.fixture
def environment(tmp_path):
    cluster = tmp_path / "cluster"
    cluster.mkdir()
    values = {
        "STRATFORGE_TEST_AGENT_WORLD_POSTGRES_ALLOW": "1",
        "STRATFORGE_TEST_AGENT_WORLD_POSTGRES_URL": "postgresql://stratforge_app:fixture@127.0.0.1:55400/aw_disposable_12345678?sslmode=require",
        "STRATFORGE_TEST_AGENT_WORLD_POSTGRES_ADMIN_URL": "postgresql://aw_test_admin:fixture@127.0.0.1:55400/aw_disposable_12345678?sslmode=require",
        "STRATFORGE_ALLOW_INSECURE_LOCAL_POSTGRES": "1",
    }
    def write(changes=None):
        current = {**values, **(changes or {})}
        (cluster / "acceptance.env").write_text("".join(key + "=" + value + "\n" for key, value in current.items()), encoding="utf-8")
        return current
    return tmp_path, write


def test_the_generated_env_requires_separate_ordinary_and_admin_roles(harness, environment):
    root, write = environment
    expected = write()
    assert harness.read_env(root) == expected


@pytest.mark.parametrize("change", [
    {"STRATFORGE_DATABASE_URL": "foreign-source"},
    {"STRATFORGE_TEST_AGENT_WORLD_POSTGRES_ALLOW": "0"},
    {"STRATFORGE_TEST_AGENT_WORLD_POSTGRES_URL": "postgresql://stratforge_app:fixture@remote.invalid:55400/aw_disposable_12345678?sslmode=require"},
    {"STRATFORGE_TEST_AGENT_WORLD_POSTGRES_URL": "postgresql://stratforge_app:fixture@127.0.0.1:55400/production?sslmode=require"},
    {"STRATFORGE_TEST_AGENT_WORLD_POSTGRES_URL": "postgresql://stratforge_app:fixture@127.0.0.1:55400/aw_disposable_12345678?sslmode=disable"},
    {"STRATFORGE_TEST_AGENT_WORLD_POSTGRES_URL": "postgresql://aw_test_admin:fixture@127.0.0.1:55400/aw_disposable_12345678?sslmode=require"},
    {"STRATFORGE_TEST_AGENT_WORLD_POSTGRES_ADMIN_URL": "postgresql://aw_test_admin:fixture@127.0.0.1:55401/aw_disposable_12345678?sslmode=require"},
])
def test_no_foreign_or_unsafe_database_can_be_used(harness, environment, change):
    root, write = environment
    write(change)
    with pytest.raises(RuntimeError):
        harness.read_env(root)


@pytest.mark.parametrize("port", [8765, 8802, 8803, 8804, 80, 65535])
def test_runtime_refuses_protected_or_out_of_range_ports_before_starting(harness, tmp_path, port):
    with pytest.raises(RuntimeError, match="port_protected"):
        harness.runtime(tmp_path, port)


def test_suite_refuses_to_truncate_a_recorded_runtime_acceptance(harness, tmp_path):
    (tmp_path / "runtime-state.json").write_text("{}", encoding="utf-8")
    with pytest.raises(RuntimeError, match="truncate_runtime_evidence"):
        harness.suites(tmp_path)


def test_task_receipt_evidence_is_not_assumed_to_be_inside_presentation_dto(harness, monkeypatch):
    client = harness.Client(8805)
    detail = {"task": {"id": "one", "display_status": "awaiting_review"},
              "id": "one", "display_status": "awaiting_review", "actual_model": "local-fixture",
              "result_text": "fixture", "executor": "local-fixture", "external_call": False}
    monkeypatch.setattr(client, "call", lambda path: (200, detail))
    task, original = client.task("one")
    assert original is detail
    assert task["actual_model"] == "local-fixture" and task["external_call"] is False
    assert "actual_model" not in detail["task"]


def test_conflicting_public_task_status_is_a_failure_not_silently_normalized(harness, monkeypatch):
    client = harness.Client(8805)
    monkeypatch.setattr(client, "call", lambda path: (200, {
        "task": {"display_status": "awaiting_review"}, "display_status": "verified_automatically"}))
    with pytest.raises(RuntimeError, match="projection_mismatch"):
        client.task("one")


def test_runtime_never_reuses_existing_data_without_explicit_failed_resume(harness, monkeypatch, tmp_path):
    (tmp_path / "app-data").mkdir()
    monkeypatch.setattr(harness, "identity", lambda: {"app_python_tree_sha256": "same"})
    with pytest.raises(RuntimeError, match="data_already_exists"):
        harness.runtime(tmp_path, 8805)


@pytest.mark.parametrize("state,expected", [
    ({"status": "PASS"}, "unrecorded_runtime_resume"),
    ({"status": "FAIL", "workspace_id": "other"}, "unrecorded_runtime_resume"),
    ({"status": "FAIL", "port": 8804}, "unrecorded_runtime_resume"),
    ({"status": "FAIL", "source": {"app_python_tree_sha256": "changed"}}, "code_changed_before_resume"),
])
def test_resume_does_not_relabel_other_or_changed_runtime_evidence(harness, monkeypatch, tmp_path, state, expected):
    import json
    (tmp_path / "app-data").mkdir()
    saved = {"status": "FAIL", "port": 8805, "workspace_id": harness.WORKSPACE,
             "source": {"app_python_tree_sha256": "same"}, **state}
    (tmp_path / "runtime-state.json").write_text(json.dumps(saved), encoding="utf-8")
    monkeypatch.setattr(harness, "identity", lambda: {"app_python_tree_sha256": "same"})
    with pytest.raises(RuntimeError, match=expected):
        harness.runtime(tmp_path, 8805, resume=True)
