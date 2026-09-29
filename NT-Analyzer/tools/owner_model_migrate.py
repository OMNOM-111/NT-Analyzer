"""One-shot, owner-scoped Local DPAPI -> server vault migration over pinned SSH.

The sender never writes or prints its snapshot.  The receiver accepts one
bounded stdin message, authenticates the target owner against the destination
database, and returns only a secret-free receipt.  Run with the active Local
or destination environment already loaded by the respective trusted process.
"""
from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
from pathlib import Path
from uuid import UUID, uuid5

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import account_auth, audit_events, runtime_env, secure_store, workspaces
from app.ai_control_center import contracts as c, model_sharing, owner_model_migration
from app.ai_control_center.model_service import ModelService
from app.ai_control_center.secret_store import LocalSecrets
from app.ai_control_center.states import ContractError

_MAX_BYTES = 750_000
_WORKSPACE = re.compile(r"ws_[A-Za-z0-9_-]{8,80}\Z")
_SSH_TARGET = re.compile(r"[A-Za-z0-9._-]+@[A-Za-z0-9._-]+\Z")
_REMOTE_PATH = re.compile(r"/[A-Za-z0-9_./-]+\Z")
_MIGRATION_ACTOR = uuid5(UUID("687a625f-1254-452c-883b-f1fac8348d22"), "owner-model-maintenance-ssh")


def _identity(args, *, environment):
    try:
        user_uuid = UUID(args.owner_uuid)
        migration_id = UUID(args.migration_id)
        if migration_id.int == 0 or not _WORKSPACE.fullmatch(args.workspace_id):
            raise ValueError()
    except (TypeError, ValueError):
        raise ContractError("model_migration_scope_denied") from None
    user = account_auth.find_active_user_by_uuid(user_uuid)
    if not user or user.get("is_owner") is not True or user.get("is_service_account"):
        raise ContractError("model_migration_scope_denied")
    user_id = int(user.get("user_id") or user.get("id") or 0)
    workspace = workspaces.require_workspace_writer(user_id, workspace_id=args.workspace_id)
    if (workspace.get("status") != "active" or int(workspace.get("owner_user_id") or 0) != user_id
            or (workspace.get("membership") or {}).get("role") != "owner"):
        raise ContractError("model_migration_scope_denied")
    context = c.RequestContext(scope=c.TenantScope(environment=environment, workspace_id=args.workspace_id),
        user_uuid=user_uuid, actor=c.ActorRef(kind=c.ActorKind.SERVICE,
            actor_id=_MIGRATION_ACTOR, on_behalf_of=user_uuid))
    return context


def _source_snapshot(args):
    if not runtime_env.is_development() or not secure_store.available():
        raise ContractError("model_migration_source_unavailable")
    context = _identity(args, environment=c.Environment.DEVELOPMENT)
    from app.ai_control_center.sqlite_repository import SQLiteAgentWorldRepository
    repository = SQLiteAgentWorldRepository(runtime_env.data_path("ai_lab", "agent-world.sqlite3"),
        read_only=True)
    revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=Path(__file__).resolve().parent.parent,
        capture_output=True, text=True, check=True).stdout.strip()
    from app.ai_lab import agent_registry

    def resolve_registry(registry_id):
        binding = agent_registry.get_agent(registry_id)
        return {**binding, "api_key": agent_registry.get_api_key(registry_id)}

    return owner_model_migration.prepare_local_snapshot(repository=repository, context=context,
        local_secrets=LocalSecrets(), resolve_registry=resolve_registry,
        resolve_share=lambda model_id: model_sharing.get(model_id, context=context),
        source_commit=revision, migration_id=args.migration_id)


def _receiver(args):
    if (runtime_env.deployment_environment() != args.environment or
            args.environment not in {"canary", "production"} or sys.stdin.isatty()):
        raise ContractError("model_migration_scope_denied")
    environment = c.Environment(args.environment)
    context = _identity(args, environment=environment)
    raw = sys.stdin.buffer.read(_MAX_BYTES + 1)
    if not raw or len(raw) > _MAX_BYTES:
        raise ContractError("model_migration_invalid")
    try:
        snapshot = json.loads(raw)
    except (UnicodeError, ValueError):
        raise ContractError("model_migration_invalid") from None
    if (not isinstance(snapshot, dict) or snapshot.get("migration_id") != args.migration_id or
            snapshot.get("owner_uuid") != args.owner_uuid or
            snapshot.get("owner_workspace_id") != args.workspace_id):
        raise ContractError("model_migration_scope_denied")
    from app.production_storage.core import PostgresClient
    from app.ai_control_center.postgres_repository import PostgresAgentWorldRepository
    from app.ai_control_center.server_secrets import ServerSecrets
    from os import environ
    repository = PostgresAgentWorldRepository(PostgresClient(
        environ.get("STRATFORGE_DATABASE_URL", ""), production=True), environment=environment)

    def owner(ctx):
        return ctx == context and _identity(args, environment=environment) == context

    def admit(ctx, _operation, _estimate=0):
        if not owner(ctx):
            raise ContractError("model_migration_scope_denied")

    service = ModelService(repository, admit=admit, secrets=ServerSecrets(repository, context))
    receipt = owner_model_migration.import_server_snapshot(service=service, context=context,
        snapshot=snapshot, assert_owner=owner)
    audit_events.record(str(context.user_uuid), "agent_world.owner_model_migration", "agent_world",
        workspace_id=context.scope.workspace_id, resource_id=args.migration_id,
        details={"environment": args.environment, "metadata_sha256": receipt["metadata_sha256"],
                 "model_count": len(receipt["models"]), "authenticated_actor": "maintenance_ssh_service",
                 "requester_user_uuid": str(context.user_uuid)})
    return receipt


def _sender(args):
    if (not _SSH_TARGET.fullmatch(args.ssh_target) or
            not _REMOTE_PATH.fullmatch(args.remote_app_dir) or
            not _REMOTE_PATH.fullmatch(args.remote_env_file) or
            not _REMOTE_PATH.fullmatch(args.remote_python) or
            args.environment not in {"canary", "production"}):
        raise ContractError("model_migration_transport_denied")
    snapshot = _source_snapshot(args)
    payload = json.dumps(snapshot, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    if len(payload) > _MAX_BYTES:
        raise ContractError("model_migration_invalid")
    command = " ".join(["set -eu; unset STRATFORGE_AGENT_WORLD_CREDENTIAL_KEY; set -a; .",
        shlex.quote(args.remote_env_file), "; set +a; cd",
        shlex.quote(args.remote_app_dir), "; exec", shlex.quote(args.remote_python),
        "tools/owner_model_migrate.py receive",
        "--environment", shlex.quote(args.environment), "--owner-uuid", shlex.quote(args.owner_uuid),
        "--workspace-id", shlex.quote(args.workspace_id), "--migration-id", shlex.quote(args.migration_id)])
    result = subprocess.run(["ssh", "-T", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
        args.ssh_target, "sh -c " + shlex.quote(command)], input=payload, capture_output=True, timeout=120)
    if result.returncode or len(result.stdout) > 8192:
        raise ContractError("model_migration_transport_failed")
    try:
        receipt = json.loads(result.stdout)
    except ValueError:
        raise ContractError("model_migration_receipt_invalid") from None
    if (not isinstance(receipt, dict) or receipt.get("ok") is not True or
            receipt.get("migration_id") != args.migration_id or
            not re.fullmatch(r"[0-9a-f]{64}", str(receipt.get("metadata_sha256") or ""))):
        raise ContractError("model_migration_receipt_invalid")
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description="One-shot owner model migration; no plaintext output")
    parser.add_argument("mode", choices=("send", "receive"))
    parser.add_argument("--environment", choices=("canary", "production"), required=True)
    parser.add_argument("--owner-uuid", required=True)
    parser.add_argument("--workspace-id", required=True)
    parser.add_argument("--migration-id", required=True)
    parser.add_argument("--ssh-target", default="")
    parser.add_argument("--remote-app-dir", default="")
    parser.add_argument("--remote-env-file", default="")
    parser.add_argument("--remote-python", default="")
    args = parser.parse_args(argv)
    try:
        receipt = _sender(args) if args.mode == "send" else _receiver(args)
        print(json.dumps(receipt, ensure_ascii=True, separators=(",", ":")))
        return 0
    except Exception as exc:
        # Never print a subprocess stderr, provider response, or snapshot.
        code = exc.code if isinstance(exc, ContractError) else "model_migration_unavailable"
        print(json.dumps({"ok": False, "code": code}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
