"""Reproducible disposable PG + HTTP + spawned-worker acceptance (no providers).

Only this tool's ignored workdir, generated credentials and loopback endpoints
are used. Run `suites` before `runtime`: the repository suites truncate their
disposable tables. No real owner data is imported and no application API is
patched. The test executor is separately opt-in and its output stays synthetic.

The standard application Local-owner entry authenticates a *fresh test owner*;
it is not an ordinary-human registration or BYOK acceptance result. PostgreSQL
connections always use the ordinary NOSUPERUSER/NOBYPASSRLS application role.
"""
from __future__ import annotations

import argparse
import hashlib
import http.cookiejar
import importlib.util
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import socket
import subprocess
import sys
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

CODE = Path(__file__).resolve().parents[2]
TOOL = Path(__file__).resolve()
OWNER_ID = 991880501
WORKSPACE = "ws_owner_training_" + hashlib.sha256(str(OWNER_ID).encode("ascii")).hexdigest()[:12]
FOREIGN = "ws_pg_acceptance_foreign_0001"
TABLES = ("sf_aw_meta", "sf_aw_records", "sf_aw_revisions", "sf_aw_events", "sf_aw_outbox",
          "sf_aw_mutations", "sf_aw_inbox", "sf_aw_artifacts", "sf_aw_memory_grants", "sf_aw_memory_grant_anchors")
APP_ENV = "STRATFORGE_TEST_AGENT_WORLD_POSTGRES_URL"
ADMIN_ENV = "STRATFORGE_TEST_AGENT_WORLD_POSTGRES_ADMIN_URL"


def require(value, code):
    if not value:
        raise RuntimeError(code)


def clean_environment():
    # Never inherit operator/provider/Production settings into this process.
    allowed = {"systemroot", "windir", "comspec", "path", "pathext", "temp", "tmp", "userprofile",
               "appdata", "localappdata", "homedrive", "homepath", "username", "computername",
               "programfiles", "programfiles(x86)", "programdata", "allusersprofile", "systemdrive"}
    return {key: value for key, value in os.environ.items() if key.lower() in allowed}


def loopback_guard(event, args):
    address = None
    if event == "socket.connect":
        address = args[1]
    elif event == "socket.getaddrinfo":
        address = (args[0], args[1])
    elif event == "socket.sendto":
        address = args[-1]
    if not isinstance(address, tuple) or not address:
        return
    host = address[0]
    if isinstance(host, bytes):
        host = host.decode("ascii", "replace")
    if host == "localhost":
        return
    try:
        allowed = ipaddress.ip_address(host).is_loopback
    except ValueError:
        allowed = False
    if not allowed:
        raise OSError("disposable_acceptance_external_network_denied")


# Spawned workers re-import this real __main__ module. The network boundary is
# installed there too, not just in the HTTP parent. Application guards remain.
if os.environ.get("STRATFORGE_AW_ACCEPTANCE_NETWORK_GUARD") == "1":
    sys.addaudithook(loopback_guard)


def checked_workdir(value):
    result = Path(value).resolve()
    anchor = (CODE / ".artifacts").resolve()
    require(result.is_relative_to(anchor) and result != anchor
            and result.name.startswith("pg-runtime-acceptance-"), "acceptance_workdir_outside_ignored_scope")
    return result


def read_env(workdir):
    path = workdir / "cluster" / "acceptance.env"
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.startswith("#"):
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    allowed = {APP_ENV, ADMIN_ENV, "STRATFORGE_TEST_AGENT_WORLD_POSTGRES_ALLOW", "STRATFORGE_ALLOW_INSECURE_LOCAL_POSTGRES"}
    require(set(values) <= allowed and values.get("STRATFORGE_TEST_AGENT_WORLD_POSTGRES_ALLOW") == "1",
            "acceptance_environment_invalid")
    parsed = [urllib.parse.urlsplit(values[key]) for key in (APP_ENV, ADMIN_ENV)]
    for item in parsed:
        require(item.scheme == "postgresql" and item.hostname == "127.0.0.1" and item.port
                and re.fullmatch(r"/aw_disposable_[a-z0-9]{8,32}", item.path)
                and item.password and item.query == "sslmode=require", "acceptance_database_not_disposable_tls")
    require(parsed[0].username == "stratforge_app" and parsed[1].username == "aw_test_admin"
            and (parsed[0].port, parsed[0].path) == (parsed[1].port, parsed[1].path), "acceptance_roles_invalid")
    return values


def save(workdir, name, value):
    require("/" not in name and "\\" not in name, "evidence_filename_invalid")
    (workdir / name).write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def finish_bootstrap(workdir):
    """Resume only our empty fresh cluster after an old pg_ctl capture hang."""
    import psycopg
    from psycopg import sql
    cluster = workdir / "cluster"
    require(not (cluster / "acceptance.env").exists(), "bootstrap_already_finished")
    config = (cluster / "pgdata" / "postgresql.auto.conf").read_text(encoding="utf-8")
    require("listen_addresses = '127.0.0.1'" in config and "ssl = on" in config, "bootstrap_not_loopback_tls")
    port = int(re.search(r"^port = (\d+)$", config, re.M)[1])
    boot = (cluster / ".superpw").read_text(encoding="utf-8").strip()
    dbname = "aw_disposable_" + secrets.token_hex(6)
    admin_pw, app_pw = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    options = {"host": "127.0.0.1", "port": port, "user": "pgboot", "password": boot,
               "sslmode": "require", "autocommit": True}
    with psycopg.connect(dbname="postgres", **options) as connection:
        require(connection.execute("SELECT count(*) FROM pg_roles WHERE rolname IN ('aw_test_admin','stratforge_app')").fetchone()[0] == 0,
                "bootstrap_is_not_empty")
        connection.execute(sql.SQL("CREATE ROLE aw_test_admin LOGIN CREATEDB PASSWORD {}").format(sql.Literal(admin_pw)))
        connection.execute(sql.SQL("CREATE ROLE stratforge_app LOGIN NOSUPERUSER NOCREATEDB NOBYPASSRLS PASSWORD {}").format(sql.Literal(app_pw)))
        connection.execute(sql.SQL("CREATE DATABASE {} OWNER aw_test_admin").format(sql.Identifier(dbname)))
        connection.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO stratforge_app").format(sql.Identifier(dbname)))
    with psycopg.connect(dbname=dbname, **options) as connection:
        connection.execute("GRANT USAGE, CREATE ON SCHEMA public TO aw_test_admin")
        connection.execute("GRANT USAGE ON SCHEMA public TO stratforge_app")
    values = {"STRATFORGE_TEST_AGENT_WORLD_POSTGRES_ALLOW": "1",
        ADMIN_ENV: f"postgresql://aw_test_admin:{admin_pw}@127.0.0.1:{port}/{dbname}?sslmode=require",
        APP_ENV: f"postgresql://stratforge_app:{app_pw}@127.0.0.1:{port}/{dbname}?sslmode=require",
        "STRATFORGE_ALLOW_INSECURE_LOCAL_POSTGRES": "1"}
    (cluster / "acceptance.env").write_text("".join(key + "=" + value + "\n" for key, value in values.items()), encoding="utf-8")
    (cluster / ".superpw").unlink()
    print(json.dumps({"cluster": "ready", "port": port, "database": dbname, "tls": True}), flush=True)


def suites(workdir):
    require(not (workdir / "runtime-state.json").exists(), "suite_would_truncate_runtime_evidence")
    values = read_env(workdir)
    env = clean_environment()
    env.update(values)
    env.update(STRATFORGE_TEST_POSTGRES_URL=values[APP_ENV], STRATFORGE_TEST_POSTGRES_ADMIN_URL=values[ADMIN_ENV],
               PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
    sys.path.insert(0, str(CODE))
    from app.production_storage.core import MigrationRunner
    migrated = MigrationRunner(values[ADMIN_ENV]).apply()
    save(workdir, "migration-evidence.json", migrated)
    result = {"migration": migrated}
    for name, files in (("agent-world", ["tests/test_agent_world_postgres.py"]),
             ("legacy", ["tests/test_production_storage.py", "tests/test_production_workers.py",
                         "tests/test_sf_chat_relational_postgres.py", "tests/test_stage8_postgresql.py"])):
        command = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *files,
                   "--junitxml=" + str(workdir / (name + ".xml"))]
        started = time.monotonic()
        with (workdir / (name + ".log")).open("w", encoding="utf-8") as output:
            run = subprocess.run(command, cwd=CODE, env=env, stdout=output, stderr=subprocess.STDOUT,
                                 timeout=900, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        rows = ET.parse(workdir / (name + ".xml")).getroot().findall("testsuite")
        counts = {key: sum(int(row.attrib.get(key, "0")) for row in rows)
                  for key in ("tests", "failures", "errors", "skipped")}
        result[name] = {**counts, "elapsed_seconds": round(time.monotonic() - started, 2), "exit_code": run.returncode}
        save(workdir, "suite-evidence.json", result)
        print(json.dumps({name: result[name]}), flush=True)
        require(run.returncode == 0 and counts["skipped"] == 0, name + "_acceptance_not_passed")


def configure(workdir, port):
    values = read_env(workdir)
    env = clean_environment()
    env.update(DEPLOYMENT_ENV="development", STRATFORGE_ENV="development",
               STRATFORGE_DEVELOPMENT_DATA_ROOT=str(workdir / "app-data"),
               STRATFORGE_DATA_ROOT=str(workdir / "production-disabled"),
               STRATFORGE_CANARY_DATA_ROOT=str(workdir / "canary-disabled"))
    os.environ.clear()
    os.environ.update(env)
    os.chdir(CODE)
    sys.path.insert(0, str(CODE))
    from app.backend_supervisor import configure_development_profile
    profile = configure_development_profile(CODE, apply_environment=False)
    profile.update({"STRATFORGE_INSTANCE_ID": "aw-pg-acceptance-" + str(port),
        "STRATFORGE_DEVELOPMENT_DATA_ROOT": str(workdir / "app-data"),
        "STRATFORGE_DATA_ROOT": str(workdir / "production-disabled"),
        "STRATFORGE_CANARY_DATA_ROOT": str(workdir / "canary-disabled"),
        "STRATFORGE_COOKIE_NAMESPACE": "sf-aw-pg-acceptance-" + str(port),
        "STRATFORGE_DEVELOPMENT_ORIGIN": "http://127.0.0.1:" + str(port),
        "STRATFORGE_DATABASE_ID": "disposable-agent-world-postgres",
        "STRATFORGE_QUEUE_ID": "disposable-existing-local-worker",
        "NTA_TELEGRAM_CHAT_ID": str(OWNER_ID), "NTA_STAGING_ALLOW_OWNER_TELEGRAM": "0",
        "NTA_VITEK_BACKGROUND": "0", "NTA_MARKET_DATA_IPC_PORT": str(port + 1000),
        "NTA_MARKET_DATA_IPC_PIPE": "stratforge-aw-acceptance-" + str(port),
        "STRATFORGE_AGENT_WORLD_LOCAL_WORKSPACES": WORKSPACE,
        "STRATFORGE_AGENT_WORLD_LOCAL_MECHANISMS": json.dumps({"environment": "development", "flags": {"AI_EXECUTION_V2": [WORKSPACE]}}),
        "STRATFORGE_AGENT_WORLD_TEST_EXECUTOR": WORKSPACE,
        "STRATFORGE_AGENT_WORLD_MODEL_ORIGINS": "https://api.deepseek.com",
        "STRATFORGE_AGENT_WORLD_STORAGE": "postgres",
        "STRATFORGE_AGENT_WORLD_DATABASE_URL": values[APP_ENV],
        "STRATFORGE_AW_ACCEPTANCE_NETWORK_GUARD": "1",
        "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"})
    os.environ.update(profile)
    sys.addaudithook(loopback_guard)
    from app import runtime_env, preview_sandbox
    require(runtime_env.data_root() == (workdir / "app-data").resolve() and not preview_sandbox.enabled(), "runtime_not_isolated")
    runtime_env.assert_startup_safe()
    return profile


class Client:
    def __init__(self, port):
        self.base = "http://127.0.0.1:" + str(port)
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),
                     urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.csrf = ""

    def call(self, path, payload=None, expected=200):
        data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(self.base + path, data=data,
            headers={"Origin": self.base, "Content-Type": "application/json", "X-CSRF-Token": self.csrf})
        try:
            with self.opener.open(request, timeout=45) as response:
                status, body = response.status, json.load(response)
        except urllib.error.HTTPError as error:
            status, body = error.code, json.load(error)
        if expected is not None:
            require(status == expected, "http_" + str(status) + "_" + str(body.get("code", "")) + "_" + path)
        return status, body

    def action(self, domain, identity, action, payload, key, revision=None):
        body = {"payload": payload, "idempotency_key": key}
        if revision is not None:
            body["expected_revision"] = revision
        _, result = self.call(f"/api/ai-control-center/domains/{domain}/{identity}/{action}", body)
        return result.get("item") or result

    def task(self, identity):
        _, detail = self.call("/api/ai-control-center/tasks/" + identity)
        task = dict(detail.get("task") or detail)
        # The public response intentionally keeps the raw receipt alongside,
        # not inside, the presentation DTO. Preserve that distinction while
        # making the evidence fields convenient to assert. Never hide a
        # disagreement between the two public lifecycle projections.
        for key in ("id", "status", "display_status", "revision"):
            if key in task and key in detail:
                require(task[key] == detail[key], "task_public_projection_mismatch")
        for key in ("result_text", "actual_model", "executor", "external_call"):
            if key in detail:
                task[key] = detail[key]
        return task, detail

    def wait_task(self, identity):
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            task, detail = self.task(identity)
            if task.get("display_status") not in {None, "queued", "running", "waiting_result", "planned"}:
                return task, detail
            time.sleep(.5)
        raise RuntimeError("worker_task_timeout")


def identity():
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=CODE, text=True).strip()
    dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=CODE, text=True).strip())
    files = sorted((CODE / "app").rglob("*.py"))
    digest = hashlib.sha256()
    manifest = {}
    for path in files:
        name, checksum = path.relative_to(CODE).as_posix(), hashlib.sha256(path.read_bytes())
        manifest[name] = checksum.hexdigest()
        digest.update(name.encode())
        digest.update(checksum.digest())
    return {"git_sha": sha, "dirty": dirty, "app_python_tree_sha256": digest.hexdigest(),
            "app_python_files": manifest,
            "tool_sha256": hashlib.sha256(TOOL.read_bytes()).hexdigest()}


def start_server(workdir, port, suffix):
    import psutil
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", port))
    log = (workdir / (suffix + ".log")).open("wb")
    process = subprocess.Popen([sys.executable, str(TOOL), "serve", "--workdir", str(workdir), "--port", str(port)],
                cwd=CODE, env=clean_environment(), stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    process.acceptance_started = psutil.Process(process.pid).create_time()
    process.acceptance_log = log
    client = Client(port)
    try:
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            require(process.poll() is None, "isolated_server_exited")
            try:
                _, health = client.call("/api/health")
                break
            except (OSError, urllib.error.URLError):
                time.sleep(.5)
        else:
            raise RuntimeError("isolated_server_start_timeout")
        _, auth = client.call("/api/auth/status")
        client.csrf = str(auth.get("csrf_token") or "")
        require(auth.get("authenticated") and auth.get("is_owner") and auth.get("user", {}).get("id"),
                "test_owner_not_authenticated")
        require(auth["active_workspace"]["workspace_id"] == WORKSPACE, "runtime_workspace_mismatch")
        return process, client, auth, health
    except BaseException:
        stop_server(process, workdir)
        raise


def process_tree(process):
    import psutil
    owner = psutil.Process(process.pid)
    return [{"pid": item.pid, "parent_pid": item.ppid(), "created_at": item.create_time(), "name": item.name()}
            for item in [owner, *owner.children(recursive=True)]]


def stop_server(process, workdir):
    import psutil
    if process.poll() is not None:
        process.acceptance_log.close()
        return []
    target = psutil.Process(process.pid)
    argv = target.cmdline()
    require(target.create_time() == process.acceptance_started and str(TOOL) in argv
            and str(workdir) in argv and "serve" in argv, "refusing_unowned_process_tree")
    tree = process_tree(process)
    target.suspend()  # The supervisor cannot respawn while children are stopped.
    try:
        for child in target.children(recursive=True):
            try:
                child.kill()
                child.wait(timeout=8)
            except psutil.NoSuchProcess:
                pass
    finally:
        # Even a failed child wait must not strand our parent suspended.
        try:
            target.kill()
        except psutil.NoSuchProcess:
            pass
        process.wait(timeout=10)
        process.acceptance_log.close()
    for row in tree:
        try:
            require(psutil.Process(row["pid"]).create_time() != row["created_at"], "owned_process_survived_stop")
        except psutil.NoSuchProcess:
            pass
    return tree


def worker_evidence(client, process, workdir, task_ids, previous_attempts=()):
    _, health = client.call("/api/health")
    worker = health["worker"]
    tree = process_tree(process)
    require(worker["process_alive"] and worker["supervisor_alive"]
            and worker["pid"] in {row["pid"] for row in tree[1:]}, "worker_not_owned_child")
    require(Path(worker["db_path"]).resolve().is_relative_to((workdir / "app-data").resolve()),
            "worker_queue_outside_disposable_root")
    _, payload = client.call("/api/worker/jobs?limit=100")
    owned_child_ids = {row["pid"] for row in tree[1:]}
    for attempt in previous_attempts:
        # An idempotent retry must keep the original job and its old worker
        # receipt. That worker was verified/stopped by the recorded attempt;
        # it must not be relabelled with the current worker's identity.
        for old_tree in (attempt.get("first_tree") or [], attempt.get("last_tree_stopped") or []):
            owned_child_ids.update(row["pid"] for row in old_tree[1:])
    evidence = []
    for task_id in task_ids:
        matching = [row for row in payload["jobs"] if row.get("kind") == "agent_world_model"
                    and row.get("payload", {}).get("task_id") == task_id
                    and not row.get("payload", {}).get("phase")]
        require(len(matching) == 1, "worker_source_job_not_unique")
        row = matching[0]
        require(row["status"] == "succeeded" and row["worker_id"] in {"proc-" + str(pid) for pid in owned_child_ids},
                "worker_source_not_executed_by_owned_child")
        require(row["workspace_id"] == WORKSPACE and str(row["user_id"]) == str(OWNER_ID),
                "worker_source_scope_mismatch")
        evidence.append({key: row[key] for key in ("worker_job_id", "kind", "status", "worker_id",
                         "workspace_id", "user_id", "attempts", "queued_at_utc", "finished_at_utc")})
    return {"pid": worker["pid"], "queue_path": worker["db_path"], "source_jobs": evidence}


def sql_evidence(workdir, user_uuid):
    import psycopg
    from psycopg import sql
    from psycopg.rows import dict_row
    values = read_env(workdir)
    with psycopg.connect(values[APP_ENV], row_factory=dict_row) as connection:
        role = connection.execute("SELECT current_user AS name,rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user").fetchone()
        require(role == {"name": "stratforge_app", "rolsuper": False, "rolbypassrls": False}, "postgres_role_not_constrained")
        tables = connection.execute("SELECT c.relname,c.relrowsecurity,c.relforcerowsecurity,pg_get_userbyid(c.relowner) AS owner FROM pg_class c WHERE c.relname=ANY(%s)", (list(TABLES),)).fetchall()
        require(len(tables) == 10 and all(row["relrowsecurity"] and row["relforcerowsecurity"] and row["owner"] != "stratforge_app" for row in tables), "postgres_rls_not_forced")
        ssl = connection.execute("SELECT ssl FROM pg_stat_ssl WHERE pid=pg_backend_pid()").fetchone()["ssl"]
        require(ssl, "postgres_runtime_tls_off")
        connection.commit()
        scopes = {}
        for name, workspace, principal, environment in (("own", WORKSPACE, user_uuid, "development"),
                ("foreign_workspace", FOREIGN, user_uuid, "development"), ("empty_scope", "", "", ""),
                ("foreign_principal", WORKSPACE, "33899fbd-eab8-430f-9b81-8e7d4de11391", "development"),
                ("foreign_environment", WORKSPACE, user_uuid, "canary")):
            with connection.transaction():
                for key, value in {"stratforge.service_scope": "scoped", "stratforge.workspace_id": workspace,
                        "stratforge.aw_user_uuid": principal, "stratforge.aw_environment": environment,
                        "stratforge.aw_memory_read_id": ""}.items():
                    connection.execute("SELECT set_config(%s,%s,true)", (key, value))
                scopes[name] = {table: connection.execute(sql.SQL("SELECT count(*) AS n FROM {}").format(sql.Identifier(table))).fetchone()["n"] for table in TABLES}
                if name == "own":
                    event = connection.execute("SELECT event_id,environment,workspace_id,user_uuid,kind,entity_id,revision,payload FROM sf_aw_events LIMIT 1").fetchone()
                if name == "foreign_principal":
                    require(connection.execute("SELECT count(*) AS n FROM sf_aw_records WHERE visibility='private'").fetchone()["n"] == 0,
                            "postgres_private_record_visible")
        require(all(scopes["own"][table] > 0 for table in ("sf_aw_records", "sf_aw_revisions", "sf_aw_events", "sf_aw_artifacts")), "postgres_app_rows_missing")
        require(all(not any(rows.values()) for name, rows in scopes.items() if name not in {"own", "foreign_principal"}), "postgres_cross_scope_visible")
        require(all(scopes["foreign_principal"][table] == 0 for table in
                ("sf_aw_events", "sf_aw_artifacts", "sf_aw_inbox", "sf_aw_mutations", "sf_aw_outbox")),
                "postgres_other_principal_owned_evidence_visible")
        rejected = None
        try:
            with connection.transaction():
                for key, value in {"stratforge.service_scope": "scoped", "stratforge.workspace_id": WORKSPACE,
                        "stratforge.aw_user_uuid": user_uuid, "stratforge.aw_environment": "development"}.items():
                    connection.execute("SELECT set_config(%s,%s,true)", (key, value))
                event["workspace_id"] = FOREIGN
                event["payload"] = psycopg.types.json.Jsonb(event["payload"])
                keys = list(event)
                connection.execute(sql.SQL("INSERT INTO sf_aw_events ({}) VALUES ({})").format(
                    sql.SQL(",").join(map(sql.Identifier, keys)), sql.SQL(",").join(sql.Placeholder() for _ in keys)), tuple(event.values()))
        except psycopg.errors.InsufficientPrivilege as error:
            rejected = error.sqlstate
        require(rejected == "42501", "postgres_foreign_insert_not_rejected")
    return {"role": role, "tls": ssl, "rls_tables": tables, "scopes": scopes, "foreign_insert_sqlstate": rejected}


def runtime(workdir, port, *, resume=False):
    require(port not in {8765, 8802, 8803, 8804} and 1024 <= port < 64000, "acceptance_port_protected")
    before = identity()
    if (workdir / "app-data").exists():
        require(resume and (workdir / "runtime-state.json").is_file(), "runtime_data_already_exists")
        state = json.loads((workdir / "runtime-state.json").read_text(encoding="utf-8"))
        require(state.get("status") == "FAIL" and state.get("port") == port and state.get("workspace_id") == WORKSPACE,
                "refusing_unrecorded_runtime_resume")
        require(state["source"]["app_python_tree_sha256"] == before["app_python_tree_sha256"], "app_code_changed_before_resume")
        state.setdefault("harness_failures", []).append({key: state.get(key) for key in
                ("error", "error_locations", "first_tree", "last_tree_stopped")})
        state["resumed_source"] = before
    else:
        require(not resume, "runtime_resume_data_missing")
        state = {"source": before, "port": port, "workspace_id": WORKSPACE, "synthetic": True,
                 "external_calls": 0, "owner_registration_acceptance": False, "byok_acceptance": False}
    save(workdir, "runtime-state.json", state)
    process = None
    try:
        process, client, auth, _ = start_server(workdir, port, "runtime-first")
        state["first_tree"] = process_tree(process)
        require(not state.get("user_uuid") or state["user_uuid"] == auth["user"]["id"], "test_owner_changed_on_resume")
        state["user_uuid"] = auth["user"]["id"]
        if state.get("model_id"):
            model = {"id": state["model_id"]}
        else:
            persona = client.action("personas", "new", "create", {"name": "PG acceptance persona",
                        "description": "Disposable synthetic executor acceptance", "style": "кратко"}, "pg-runtime-persona")
            persona = client.action("personas", persona["id"], "activate", {}, "pg-runtime-activate", persona["revision"])
            model = client.action("models", "new", "connect", {"label": "Synthetic PG acceptance only",
                    "connection_kind": "model", "provider": "deepseek", "model": "deepseek-v4-flash",
                    "api_key": "not-a-provider-key-" + secrets.token_hex(16), "persona_id": persona["id"]}, "pg-runtime-connect")
            state.update(persona_id=persona["id"], model_id=model["id"])
        checked = client.action("models", model["id"], "test", {}, "pg-runtime-connection")
        check_id = checked.get("task_id") or checked["id"]
        check, _ = client.wait_task(check_id)
        require(check["display_status"] == "verified_automatically", "connection_not_verified")
        pending = client.action("models", model["id"], "task", {"rubric_key": "json_arithmetic", "input_text": "[11,7,3,5]"}, "pg-runtime-task")
        task_id = pending.get("task_id") or pending["id"]
        task, detail = client.wait_task(task_id)
        require(task["display_status"] == "awaiting_review", "result_not_waiting_for_human")
        require(json.loads(task["result_text"]) == {"count": 4, "sum": 26, "min": 3, "max": 11, "mean": 6.5}, "wrong_bounded_result")
        require(task.get("actual_model") == "agent-world-local-test-executor-v1" and task.get("cost_usd") == 0, "synthetic_provenance_missing")
        require(task.get("executor") == task["actual_model"] and task.get("external_call") is False,
                "external_provider_not_disproved")
        require(detail.get("evaluations"), "independent_evaluation_missing")
        replay = client.action("models", model["id"], "task", {"rubric_key": "json_arithmetic", "input_text": "[11,7,3,5]"}, "pg-runtime-task")
        require((replay.get("task_id") or replay["id"]) == task_id, "duplicate_http_ingress")
        sqlite_file = workdir / "app-data" / "ai_lab" / "agent-world.sqlite3"
        require(not sqlite_file.exists(), "agent_world_sqlite_fallback")
        state.update(check_task_id=check_id, task_id=task_id, result_text=task["result_text"],
                     display_status=task["display_status"], evaluation_count=len(detail["evaluations"]),
                     actual_model=task["actual_model"], executor=task["executor"],
                     external_call=task["external_call"], worker=worker_evidence(client, process, workdir, (check_id, task_id), state.get("harness_failures", ())),
                     sql_before=sql_evidence(workdir, state["user_uuid"]))
        state["first_tree_stopped"] = stop_server(process, workdir)
        process = None
        save(workdir, "runtime-state.json", state)
        process, client, auth, _ = start_server(workdir, port, "runtime-restarted")
        state["restarted_tree"] = process_tree(process)
        require(state["first_tree"][0]["pid"] != process.pid, "process_not_restarted")
        restored, restored_detail = client.task(task_id)
        require(all(restored[key] == state[key] for key in ("result_text", "display_status", "actual_model")), "history_changed_after_restart")
        require(len(restored_detail.get("evaluations", [])) == state["evaluation_count"], "evaluation_lost_after_restart")
        _, models = client.call("/api/ai-control-center/domains/models")
        found = next(row for row in models["items"] if row["id"] == model["id"])
        require(found.get("connected") and found["status"] == "active", "connection_lost_after_restart")
        status, _ = client.call("/api/ai-control-center/domains/models?workspace_id=" + FOREIGN, expected=None)
        require(status in {400, 403, 409}, "client_workspace_override_accepted")
        state["api_foreign_workspace_query_status"] = status
        status, _ = client.call("/api/workspaces/select", {"workspace_id": FOREIGN}, expected=None)
        require(status in {403, 404}, "foreign_workspace_membership_accepted")
        state["api_foreign_workspace_select_status"] = status
        state["sql_after"] = sql_evidence(workdir, state["user_uuid"])
        require(not sqlite_file.exists(), "agent_world_sqlite_fallback_after_restart")
        state["sqlite_fallback"] = False
        state["end_source"] = identity()
        require(state["source"]["app_python_tree_sha256"] == state["end_source"]["app_python_tree_sha256"], "app_code_changed_during_acceptance")
        state["status"] = "PASS"
    except Exception as error:
        state["status"] = "FAIL"
        state["error"] = str(error) if isinstance(error, RuntimeError) else type(error).__name__
        state["error_locations"] = [{"file": frame.filename, "line": frame.lineno, "function": frame.name}
                                    for frame in traceback.extract_tb(error.__traceback__)]
        raise
    finally:
        if process is not None:
            state["last_tree_stopped"] = stop_server(process, workdir)
        save(workdir, "runtime-state.json", state)
    print(json.dumps({"runtime": state["status"], "port": port, "synthetic": True, "task_id": state["task_id"],
                      "sql_records": state["sql_after"]["scopes"]["own"]["sf_aw_records"], "sqlite_fallback": False}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("finish-bootstrap", "suites", "runtime", "serve"))
    parser.add_argument("--workdir", required=True)
    parser.add_argument("--port", type=int, default=8805)
    parser.add_argument("--resume", action="store_true", help="Continue only this tool's recorded failed runtime; preserve its history")
    args = parser.parse_args()
    workdir = checked_workdir(args.workdir)
    require(workdir.is_dir(), "acceptance_workdir_missing")
    if args.mode == "finish-bootstrap":
        finish_bootstrap(workdir)
    elif args.mode == "suites":
        suites(workdir)
    elif args.mode == "runtime":
        runtime(workdir, args.port, resume=args.resume)
    else:
        require(args.port not in {8765, 8802, 8803, 8804}, "acceptance_port_protected")
        import multiprocessing
        multiprocessing.freeze_support()
        profile = configure(workdir, args.port)
        print(json.dumps({"storage": "postgres", "port": args.port, "workspace_id": WORKSPACE,
                          "source_sha": profile["STRATFORGE_GIT_COMMIT_SHA"], "external_network": "denied"}), flush=True)
        from app import server
        server.run(args.port)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        # No exception repr/DSN/payload: logs carry only a neutral error code.
        code = str(error) if isinstance(error, RuntimeError) else type(error).__name__
        print("ACCEPTANCE FAIL: " + code, file=sys.stderr, flush=True)
        raise SystemExit(1)
