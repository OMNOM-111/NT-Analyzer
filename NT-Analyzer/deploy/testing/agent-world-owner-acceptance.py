"""Reusable isolated Aurora owner review; no new authentication routes.

Use existing Development QA impersonation to inspect two ordinary users. All
provider access is denied by a process audit hook, including spawned workers.
The seeded accounts are fixtures, not evidence of registration acceptance.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import socket
import sys

CODE = Path(__file__).resolve().parents[2]
MARKER = "owner-acceptance-identity.json"
OWNER = 991881401
USERS = (991881402, 991881403)
OWNER_UUID = "ab000000-0000-4000-8000-000991881401"
MECHANISMS = ("AI_EXECUTION_V2", "AI_DELEGATION_V2", "AI_ROUTER_SHADOW_V2", "AI_ROUTER_V2",
              "AI_EXTERNAL_AGENT_V1", "AI_EXTERNAL_AGENT_TEST_V1", "AI_SCHEDULER_V1")

# Reuse reviewed environment and network boundaries, not an ignored old build.
_spec = importlib.util.spec_from_file_location("aw_acceptance_boundaries",
    Path(__file__).with_name("agent-world-postgres-runtime-acceptance.py"))
_boundaries = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_boundaries)
clean_environment = _boundaries.clean_environment
loopback_guard = _boundaries.loopback_guard
if os.environ.get("STRATFORGE_AW_OWNER_ACCEPTANCE_NETWORK_GUARD") == "1":
    sys.addaudithook(loopback_guard)


def checked_root(value, port):
    if not isinstance(port, int) or not 8814 <= port <= 8899:
        raise RuntimeError("acceptance_port_protected")
    root = Path(value).resolve()
    anchor = (CODE / ".artifacts").resolve()
    if root.parent != anchor or not root.name.startswith("owner-acceptance-"):
        raise RuntimeError("acceptance_root_outside_exact_ignored_scope")
    expected = {"schema": 1, "owner_id": OWNER, "user_ids": list(USERS), "port": port}
    marker = root / MARKER
    if marker.exists():
        if json.loads(marker.read_text(encoding="utf-8")) != expected:
            raise RuntimeError("acceptance_marker_mismatch")
    elif root.exists() and any(root.iterdir()):
        raise RuntimeError("acceptance_unmarked_existing_data")
    return root, expected


def configure(root, port):
    root, marker = checked_root(root, port)
    root.mkdir(parents=True, exist_ok=True)
    if not (root / MARKER).exists():
        (root / MARKER).write_text(json.dumps(marker, indent=2) + "\n", encoding="utf-8")
    env = clean_environment()
    env.update(DEPLOYMENT_ENV="development", STRATFORGE_ENV="development",
        STRATFORGE_DEVELOPMENT_DATA_ROOT=str(root / "app-data"),
        STRATFORGE_DATA_ROOT=str(root / "production-disabled"),
        STRATFORGE_CANARY_DATA_ROOT=str(root / "canary-disabled"))
    os.environ.clear()
    os.environ.update(env)
    os.chdir(CODE)
    sys.path.insert(0, str(CODE))
    from app.backend_supervisor import configure_development_profile
    profile = configure_development_profile(CODE, apply_environment=False)
    profile.update({"STRATFORGE_INSTANCE_ID": "aw-owner-acceptance-" + str(port),
        "STRATFORGE_DEVELOPMENT_DATA_ROOT": str(root / "app-data"),
        "STRATFORGE_DATA_ROOT": str(root / "production-disabled"),
        "STRATFORGE_CANARY_DATA_ROOT": str(root / "canary-disabled"),
        "NT_ANALYZER_SQLITE_PATH": str(root / "durable.sqlite3"),
        "STRATFORGE_COOKIE_NAMESPACE": "sf-aw-owner-acceptance-" + str(port),
        "STRATFORGE_DEVELOPMENT_ORIGIN": "http://127.0.0.1:" + str(port),
        "STRATFORGE_DATABASE_ID": "disposable-owner-acceptance",
        "STRATFORGE_QUEUE_ID": "disposable-owner-existing-worker",
        "NTA_TELEGRAM_CHAT_ID": str(OWNER), "STRATFORGE_CANONICAL_OWNER_UUID": OWNER_UUID,
        "NTA_ENABLE_TEST_AUTH": "1", "NTA_ENABLE_IMPERSONATION": "1",
        "NTA_STAGING_ALLOW_OWNER_TELEGRAM": "0", "NTA_VITEK_BACKGROUND": "0",
        "NTA_MARKET_DATA_IPC_PORT": str(port + 1000),
        "NTA_MARKET_DATA_IPC_PIPE": "stratforge-owner-acceptance-" + str(port),
        "STRATFORGE_AGENT_WORLD_STORAGE": "sqlite",
        "STRATFORGE_AW_OWNER_ACCEPTANCE_NETWORK_GUARD": "1",
        "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"})
    os.environ.update(profile)
    sys.addaudithook(loopback_guard)
    from app import runtime_env, preview_sandbox
    if runtime_env.data_root() != root / "app-data" or preview_sandbox.enabled():
        raise RuntimeError("acceptance_runtime_not_isolated")
    runtime_env.assert_startup_safe()
    return profile


def seed(root):
    from app import account_auth, test_auth, workspaces
    owner = account_auth.ensure_owner(OWNER)
    if not owner or owner.get("id") != OWNER_UUID:
        raise RuntimeError("acceptance_owner_identity_invalid")
    owner_workspace = workspaces.ensure_owner_workspace(OWNER)["workspace_id"]
    people = []
    for index, uid in enumerate(USERS, 1):
        user = account_auth.find_active_user(uid)
        created = user is None
        if user is None:
            test_auth.create_virtual_user(preset="ordinary", display_name=f"Acceptance User {index}",
                telegram_id=uid, google_email=f"acceptance{index}@example.invalid")
            user = account_auth.find_active_user(uid)
        if not user:
            raise RuntimeError("acceptance_ordinary_profile_incomplete")
        if user.get("is_owner") or not user.get("is_virtual", user.get("virtual", False)):
            raise RuntimeError("acceptance_ordinary_identity_invalid")
        workspace = workspaces.ensure_personal_workspace(uid, require_entitlement=False)["workspace_id"]
        # A restart must retain an owner's later revocation in this QA dataset.
        # Seed initial capabilities only for a freshly created disposable user.
        if created:
            for capability in ("ai_lab", "ai_pro_models"):
                account_auth.set_user_permission(OWNER, uid, capability, True)
        people.append({"user_id": uid, "user_uuid": user["user_uuid"], "workspace_id": workspace,
                       "label": f"Acceptance User {index}", "is_owner": False})
    scopes = [owner_workspace, *(person["workspace_id"] for person in people)]
    if len(set(scopes)) != 3:
        raise RuntimeError("acceptance_workspace_collision")
    os.environ.update(STRATFORGE_AGENT_WORLD_LOCAL_WORKSPACES=",".join(scopes),
        STRATFORGE_AGENT_WORLD_TEST_EXECUTOR=",".join(scopes),
        STRATFORGE_AGENT_WORLD_LOCAL_MECHANISMS=json.dumps({"environment": "development",
            "flags": {name: scopes for name in MECHANISMS}}))
    metadata = {"source_sha": os.environ["STRATFORGE_GIT_COMMIT_SHA"],
        "build_dirty": os.environ["STRATFORGE_BUILD_DIRTY"], "synthetic": True,
        "owner_id": OWNER, "owner_workspace": owner_workspace, "ordinary_users": people,
        "mechanisms": list(MECHANISMS), "allowlisted_workspaces": scopes,
        "budget_policy": "existing Development policy, network denied", "external_call_cost": 0,
        "registration_acceptance": "not tested; seeded QA fixtures",
        "origin": os.environ["STRATFORGE_DEVELOPMENT_ORIGIN"]}
    (root / "acceptance-metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8814)
    parser.add_argument("--data-root", type=Path, required=True)
    args = parser.parse_args()
    root, _ = checked_root(args.data_root, args.port)
    # Check occupancy before creating fixtures or changing process environment.
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", args.port))
    configure(root, args.port)
    metadata = seed(root)
    print(json.dumps(metadata, ensure_ascii=False), flush=True)
    from app import server
    server.run(args.port)


if __name__ == "__main__":
    main()
