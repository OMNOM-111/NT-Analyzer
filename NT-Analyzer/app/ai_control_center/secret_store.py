"""Agent World credential boundary selected by an authenticated environment.

The Local adapter retains Windows CurrentUser DPAPI.  Server environments
must use their own AEAD key and owner-scoped PostgreSQL/RLS ciphertext store;
there is deliberately no Linux or cross-environment fallback to Local data.
"""
from __future__ import annotations

from typing import Protocol

from .. import secure_store
from .contracts import Environment, RequestContext
from .states import ContractError


class SecretStore(Protocol):
    def available(self) -> bool: ...
    def get_secret(self, secret_id: str) -> str | None: ...
    def set_secret(self, secret_id: str, value: str) -> None: ...
    def delete_secret(self, secret_id: str) -> bool: ...


class LocalSecrets:
    """The legacy Windows DPAPI backend, never valid on a Linux server."""

    def available(self) -> bool:
        return secure_store.available()

    def get_secret(self, secret_id: str) -> str | None:
        return secure_store.get_secret(secret_id)

    def set_secret(self, secret_id: str, value: str) -> None:
        secure_store.set_secret(secret_id, value)

    def delete_secret(self, secret_id: str) -> bool:
        return bool(secure_store.delete_secret(secret_id))


def for_context(repository, context: RequestContext) -> SecretStore:
    """Select exactly one backend; never infer server scope from missing flags."""
    if not isinstance(context, RequestContext):
        raise ContractError("model_context_required")
    if context.scope.environment == Environment.DEVELOPMENT:
        return LocalSecrets()
    if context.scope.environment in {Environment.CANARY, Environment.PRODUCTION}:
        from .server_secrets import ServerSecrets
        return ServerSecrets(repository, context)
    raise ContractError("model_secure_storage_unavailable")
