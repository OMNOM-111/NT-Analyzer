"""Server BYOK vault: authenticated owner scope, PostgreSQL RLS and AEAD.

The deployment key stays in the environment's external platform-secret store;
only encrypted per-account values are kept in the environment's database.
"""
from __future__ import annotations

import base64
import binascii
import os
import re
from uuid import UUID

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .. import platform_secrets
from .contracts import Environment, RequestContext
from .states import ContractError

_ID = re.compile(r"aw_provider\.([0-9a-f-]{36})\Z")
_MASTER = "STRATFORGE_AGENT_WORLD_CREDENTIAL_KEY"


def _key():
    try:
        value = base64.b64decode(platform_secrets.get(_MASTER), validate=True)
    except (ValueError, binascii.Error, platform_secrets.PlatformSecretError):
        return None
    return value if len(value) == 32 else None


class ServerSecrets:
    def __init__(self, repository, context: RequestContext):
        if context.scope.environment not in {Environment.CANARY, Environment.PRODUCTION}:
            raise ContractError("model_server_scope_required")
        self.repository, self.context = repository, context

    def available(self):
        return _key() is not None

    def for_owner(self, context):
        # Called by ModelExecutor only after a live share grant was checked.
        return ServerSecrets(self.repository, context)

    def _identity(self, secret_id):
        match = _ID.fullmatch(str(secret_id or ""))
        if not match:
            raise ContractError("model_credential_invalid")
        try:
            return UUID(match[1])
        except ValueError:
            raise ContractError("model_credential_invalid") from None

    def _cipher(self):
        key = _key()
        if key is None:
            raise ContractError("model_secure_storage_unavailable")
        return AESGCM(key)

    def _aad(self, identity):
        return (self.context.scope.environment.value + ":" + self.context.scope.workspace_id +
                ":" + str(self.context.user_uuid) + ":" + str(identity)).encode()

    def _transaction(self, *, write=False):
        from .server_model_sharing import _db
        return _db(self.context, write=write)

    def get_secret(self, secret_id):
        identity = self._identity(secret_id)
        with self._transaction() as conn:
            row = conn.execute("""SELECT nonce,ciphertext FROM sf_aw_credentials
                WHERE environment=%s AND workspace_id=%s AND owner_uuid=%s AND account_id=%s""",
                (self.context.scope.environment.value, self.context.scope.workspace_id,
                 self.context.user_uuid, identity)).fetchone()
        if row is None:
            return None
        try:
            return self._cipher().decrypt(bytes(row["nonce"]), bytes(row["ciphertext"]),
                self._aad(identity)).decode()
        except Exception:
            raise ContractError("model_secure_storage_unavailable") from None

    def set_secret(self, secret_id, value):
        identity = self._identity(secret_id)
        if type(value) is not str or not 8 <= len(value) <= 4096:
            raise ContractError("model_credential_invalid")
        nonce = os.urandom(12)
        ciphertext = self._cipher().encrypt(nonce, value.encode(), self._aad(identity))
        with self._transaction(write=True) as conn:
            conn.execute("""INSERT INTO sf_aw_credentials
                (environment,workspace_id,owner_uuid,account_id,nonce,ciphertext)
                VALUES (%s,%s,%s,%s,%s,%s)
                ON CONFLICT (environment,workspace_id,account_id) DO NOTHING""",
                (self.context.scope.environment.value, self.context.scope.workspace_id,
                 self.context.user_uuid, identity, nonce, ciphertext))
            row = conn.execute("""SELECT nonce,ciphertext FROM sf_aw_credentials
                WHERE environment=%s AND workspace_id=%s AND owner_uuid=%s AND account_id=%s""",
                (self.context.scope.environment.value, self.context.scope.workspace_id,
                 self.context.user_uuid, identity)).fetchone()
        if row is None:
            raise ContractError("model_secure_storage_unavailable")
        try:
            previous = self._cipher().decrypt(bytes(row["nonce"]), bytes(row["ciphertext"]),
                self._aad(identity)).decode()
        except Exception:
            raise ContractError("model_secure_storage_unavailable") from None
        if previous != value:
            raise ContractError("model_connection_idempotency_conflict")

    def delete_secret(self, secret_id):
        identity = self._identity(secret_id)
        with self._transaction(write=True) as conn:
            row = conn.execute("""DELETE FROM sf_aw_credentials
                WHERE environment=%s AND workspace_id=%s AND owner_uuid=%s AND account_id=%s
                RETURNING account_id""", (self.context.scope.environment.value,
                    self.context.scope.workspace_id, self.context.user_uuid, identity)).fetchone()
        return row is not None
