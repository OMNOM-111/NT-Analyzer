"""Trusted-process Local owner model snapshot and server-side re-encryption.

This module is not an HTTP route.  A deployment transport must deliver its
in-memory package over an authenticated encrypted channel to a freshly
authorized owner-scoped server process.  Never print, persist or log a package:
it contains provider credentials until ``ServerSecrets.set_secret`` encrypts
them under the destination environment's key.
"""
from __future__ import annotations

import hashlib
import json
import re
from urllib.parse import urlsplit
from uuid import UUID

from ..ai_lab import agent_registry
from . import contracts as c
from .connection_protocol import CHAT_PROTOCOL
from .repositories import PageRequest
from .states import ContractError, EntityKind


def _uuid(value):
    try:
        return UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        raise ContractError("model_migration_invalid") from None


def _json_artifact(repository, context, reference):
    found = repository.get_artifact(context=context, reference=reference)
    if not found or found[1] != "application/json":
        raise ContractError("model_migration_source_invalid")
    try:
        value = json.loads(found[0])
    except (TypeError, ValueError):
        raise ContractError("model_migration_source_invalid") from None
    if not isinstance(value, dict):
        raise ContractError("model_migration_source_invalid")
    return value


def _owned(repository, context, kind):
    cursor = None
    while True:
        page = repository.list(context=context, kind=kind, page=PageRequest(limit=100, cursor=cursor))
        for record in page.items:
            if record.header.owner_user_uuid == context.user_uuid:
                yield record
        if not page.next_cursor:
            return
        cursor = page.next_cursor


def _owner_actor(context):
    return ((context.actor.kind == c.ActorKind.HUMAN and context.actor.actor_id == context.user_uuid)
            or (context.actor.kind == c.ActorKind.SERVICE
                and context.actor.on_behalf_of == context.user_uuid))


def prepare_local_snapshot(*, repository, context, local_secrets, resolve_registry, resolve_share,
                           source_commit: str, migration_id: str):
    """Return an ephemeral package to the trusted caller, never to a browser.

    The caller must pipe the serialized package directly to the destination's
    one-time authenticated importer.  This function does not write a file.
    """
    if (context.scope.environment != c.Environment.DEVELOPMENT
            or not _owner_actor(context)
            or not re.fullmatch(r"[0-9a-f]{40}", source_commit)
            or _uuid(migration_id).int == 0):
        raise ContractError("model_migration_scope_denied")
    items = []
    for model in _owned(repository, context, EntityKind.MODEL):
        profile = _json_artifact(repository, context, model.profile)
        if profile.get("source") != "private_model_connection":
            continue
        account_id = _uuid(profile.get("provider_account_id"))
        persona_id = _uuid(profile.get("persona_id"))
        account = repository.get(context=context, kind=EntityKind.PROVIDER_ACCOUNT, entity_id=account_id)
        persona = repository.get(context=context, kind=EntityKind.PERSONA, entity_id=persona_id)
        if (not isinstance(account, c.ProviderAccount) or not isinstance(persona, c.Persona)
                or account.header.owner_user_uuid != context.user_uuid
                or persona.header.owner_user_uuid != context.user_uuid
                or account.provider_key != model.provider_key):
            raise ContractError("model_migration_source_invalid")
        registry_id = profile.get("existing_registry_id")
        source = profile.get("credential_source")
        if source == "owner_registry_binding":
            if not isinstance(registry_id, str) or not re.fullmatch(r"AGT-[A-Z0-9]{12}", registry_id):
                raise ContractError("model_migration_source_invalid")
            binding = resolve_registry(registry_id)
            if (binding.get("id") != registry_id or binding.get("provider") != model.provider_key
                    or binding.get("model") != model.model_key):
                raise ContractError("model_migration_source_invalid")
            if model.status == "active" and (binding.get("base_url") != profile.get("base_url")
                    or not binding.get("enabled") or not binding.get("key_configured")
                    or binding.get("endpoint_type") != "chat"):
                raise ContractError("model_migration_source_changed")
            secret = binding.get("api_key")
        elif source == "user_supplied":
            secret = local_secrets.get_secret(account.credential.key)
        else:
            raise ContractError("model_migration_source_invalid")
        if model.status == "active" and (type(secret) is not str or not 8 <= len(secret) <= 4096):
            raise ContractError("model_migration_credential_unavailable")
        share = resolve_share(str(model.header.entity_id))
        if share and (share.get("owner_user_uuid") != str(context.user_uuid)
                      or share.get("owner_workspace_id") != context.scope.workspace_id):
            raise ContractError("model_migration_source_invalid")
        items.append({"model_id": str(model.header.entity_id), "account_id": str(account_id),
            "persona_id": str(persona_id), "persona_name": persona.display_name,
            "persona_profile": _json_artifact(repository, context, persona.profile),
            "persona_status": persona.status, "model_status": model.status,
            "account_status": account.status, "label": profile.get("label"),
            "provider": model.provider_key, "model": model.model_key,
            "base_url": profile.get("base_url"), "registry_id": registry_id,
            "shared": bool(share and share.get("shared")), "secret": secret or "",
            "local_created_at": model.header.created_at.isoformat()})
    if not items or len(items) > 64:
        raise ContractError("model_migration_source_invalid")
    return {"schema_version": 1, "migration_id": str(_uuid(migration_id)),
        "source_environment": "development", "source_commit": source_commit,
        "owner_uuid": str(context.user_uuid), "owner_workspace_id": context.scope.workspace_id,
        "models": items}


def _validate_item(item):
    expected = {"model_id", "account_id", "persona_id", "persona_name", "persona_profile",
                "persona_status", "model_status", "account_status", "label", "provider", "model",
                "base_url", "registry_id", "shared", "secret", "local_created_at"}
    if type(item) is not dict or set(item) != expected:
        raise ContractError("model_migration_invalid")
    for field in ("model_id", "account_id", "persona_id"):
        _uuid(item[field])
    provider = item["provider"]
    if provider not in agent_registry.PROVIDERS or provider == "custom":
        raise ContractError("model_migration_provider_denied")
    c.require_text(item["persona_name"], limit=120)
    c.require_text(item["label"], limit=80)
    c.require_text(item["model"], limit=120)
    if type(item["local_created_at"]) is not str or not re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?\+00:00", item["local_created_at"]):
        raise ContractError("model_migration_invalid")
    if (type(item["persona_profile"]) is not dict or type(item["shared"]) is not bool
            or item["persona_status"] not in {"active", "suspended", "retired"}
            or item["model_status"] not in {"active", "suspended", "retired"}
            or item["account_status"] not in {"active", "suspended", "retired"}):
        raise ContractError("model_migration_invalid")
    if item["registry_id"] is not None and not re.fullmatch(r"AGT-[A-Z0-9]{12}", str(item["registry_id"])):
        raise ContractError("model_migration_invalid")
    endpoint = item["base_url"]
    if type(endpoint) is not str or len(endpoint) > 250:
        raise ContractError("model_migration_endpoint_denied")
    parsed = urlsplit(endpoint)
    azure_selector = (provider == "azure_foundry" and
                      re.fullmatch(r"api-version=\d{4}-\d{2}-\d{2}(?:-preview)?", parsed.query or ""))
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.fragment or parsed.port not in (None, 443)
            or parsed.query and not azure_selector or any(ch in endpoint for ch in "\\\r\n")):
        raise ContractError("model_migration_endpoint_denied")
    if provider != "azure_foundry" and endpoint.rstrip("/") != str(agent_registry.PROVIDERS[provider].get("base_url") or "").rstrip("/"):
        raise ContractError("model_migration_endpoint_denied")
    if provider == "azure_foundry" and not parsed.hostname.endswith(
            (".openai.azure.com", ".cognitiveservices.azure.com")):
        raise ContractError("model_migration_endpoint_denied")
    secret = item["secret"]
    if (type(secret) is not str or (secret and (not 8 <= len(secret) <= 4096
            or any(ord(ch) < 33 or ord(ch) > 126 for ch in secret)))
            or item["model_status"] == "active" and not secret):
        raise ContractError("model_migration_credential_unavailable")
    if secret and any(secret in json.dumps(item[field], ensure_ascii=False) for field in
            ("persona_name", "persona_profile", "label", "model", "base_url")):
        raise ContractError("model_migration_credential_in_metadata")
    if item["shared"] and (item["model_status"] != "active" or item["account_status"] != "active"):
        raise ContractError("model_migration_invalid")


def import_server_snapshot(*, service, context, snapshot, assert_owner):
    """Owner-only, idempotent import through typed repository and server vault.

    The caller must enforce a one-time authenticated transport before invoking
    this method.  No plaintext is returned or recorded in its receipt.
    """
    if (context.scope.environment not in {c.Environment.CANARY, c.Environment.PRODUCTION}
            or not _owner_actor(context) or not callable(assert_owner)
            or not assert_owner(context)):
        raise ContractError("model_migration_scope_denied")
    if (type(snapshot) is not dict or set(snapshot) != {"schema_version", "migration_id",
            "source_environment", "source_commit", "owner_uuid", "owner_workspace_id", "models"}
            or snapshot["schema_version"] != 1 or snapshot["source_environment"] != "development"
            or snapshot["owner_uuid"] != str(context.user_uuid)
            or snapshot["owner_workspace_id"] != context.scope.workspace_id
            or not re.fullmatch(r"[0-9a-f]{40}", str(snapshot["source_commit"]))
            or _uuid(snapshot["migration_id"]).int == 0
            or type(snapshot["models"]) is not list or not 1 <= len(snapshot["models"]) <= 64):
        raise ContractError("model_migration_invalid")
    from .server_secrets import ServerSecrets
    if not isinstance(service.secrets, ServerSecrets) or not service.secrets.available():
        raise ContractError("model_secure_storage_unavailable")
    model_ids, account_ids = set(), set()
    for item in snapshot["models"]:
        _validate_item(item)
        model_id, account_id = _uuid(item["model_id"]), _uuid(item["account_id"])
        if model_id in model_ids or account_id in account_ids:
            raise ContractError("model_migration_invalid")
        service._endpoint(item["provider"], item["base_url"])
        model_ids.add(model_id)
        account_ids.add(account_id)
    metadata = [{k: v for k, v in item.items() if k != "secret"} for item in snapshot["models"]]
    digest = hashlib.sha256(json.dumps(metadata, sort_keys=True, separators=(",", ":"),
                                   ensure_ascii=True).encode()).hexdigest()
    service._access(context, "connect")
    imported = []
    for item in snapshot["models"]:
        imported.append(_import_one(service, context, item, snapshot["migration_id"]))
    return {"ok": True, "migration_id": snapshot["migration_id"],
            "metadata_sha256": digest, "models": imported}


def _import_one(service, context, item, migration_id):
    model_id, account_id, persona_id = (_uuid(item[key]) for key in ("model_id", "account_id", "persona_id"))
    profile = {"schema_version": 1, "source": "private_model_connection", "label": item["label"],
        "provider": item["provider"], "model": item["model"], "base_url": item["base_url"],
        "connection_kind": "model", "provider_account_id": str(account_id),
        "persona_id": str(persona_id), "protocol": CHAT_PROTOCOL, "credential_source": "user_supplied",
        "local_registry_id": item["registry_id"], "migration_source": "local_owner_registry",
        "migration_id": migration_id, "local_created_at": item["local_created_at"],
        "migration_share_imported": False, "connected": False}
    existing = service.repository.get(context=context, kind=EntityKind.MODEL, entity_id=model_id)
    if existing is not None:
        if existing.header.owner_user_uuid != context.user_uuid:
            raise ContractError("model_migration_conflict")
        prior = service._json(context, existing.profile)
        if any(prior.get(key) != value for key, value in profile.items()
               if key not in {"connected", "migration_share_imported"}):
            raise ContractError("model_migration_conflict")
        if prior.get("migration_share_imported") is True:
            # A replay never re-enables a share the owner may since have revoked.
            if item["secret"] and service.secrets.get_secret("aw_provider." + str(account_id)) != item["secret"]:
                raise ContractError("model_migration_conflict")
            return {"model_id": str(model_id), "status": "already_imported"}
    policy = service._put(context, {"version": "owner-model-migration-v1",
        "source": "development", "migration_id": migration_id})
    persona = service._ensure(context, c.Persona, persona_id, model_id, policy,
        display_name=item["persona_name"], profile=service._put(context, item["persona_profile"]))
    if (persona.display_name != item["persona_name"]
            or service._json(context, persona.profile) != item["persona_profile"]):
        raise ContractError("model_migration_conflict")
    if persona.status == "draft" and item["persona_status"] == "suspended":
        persona = service._walk(context, persona, "active")
    if persona.status == "draft":
        persona = service._walk(context, persona, item["persona_status"])
    if persona.status != item["persona_status"]:
        raise ContractError("model_migration_conflict")
    if item["secret"]:
        service.secrets.set_secret("aw_provider." + str(account_id), item["secret"])
    account = service._ensure(context, c.ProviderAccount, account_id, model_id, policy,
        provider_key=item["provider"], credential=c.ExternalRef(authority=c.ExternalAuthority.CREDENTIAL,
            key="aw_provider." + str(account_id), scope=context.scope))
    if (account.provider_key != item["provider"] or account.credential.key != "aw_provider." + str(account_id)):
        raise ContractError("model_migration_conflict")
    if account.status == "draft" and item["account_status"] == "suspended":
        account = service._walk(context, account, "active")
    account = service._walk(context, account, item["account_status"])
    model = existing or service._ensure(context, c.Model, model_id, model_id, policy,
        provider_key=item["provider"], model_key=item["model"],
        profile=service._put(context, profile), modalities=("text",))
    if model.provider_key != item["provider"] or model.model_key != item["model"]:
        raise ContractError("model_migration_conflict")
    if model.status == "draft" and item["model_status"] == "suspended":
        model = service._walk(context, model, "active")
    model = service._walk(context, model, item["model_status"])
    if model.status != item["model_status"] or account.status != item["account_status"]:
        raise ContractError("model_migration_conflict")
    if model.status != "retired":
        if item["shared"]:
            service._write_share(context, model, profile, True)
        # A typed model revision is the durable completion marker. It makes
        # interrupted import resumable without ever resurrecting a later
        # owner-initiated share-off on replay.
        completed = {**service._json(context, model.profile), "migration_share_imported": True}
        model = service._change(context, model, profile=service._put(context, completed))
    return {"model_id": str(model_id), "status": "imported"}
