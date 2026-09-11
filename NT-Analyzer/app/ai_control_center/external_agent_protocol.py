"""Bounded A2A 0.3 JSON-RPC client; not a model endpoint or authority source.

The integrator supplies already-admitted requests and an opaque credential.
No registry, queue, permission or budget is implemented in this module.
"""
from __future__ import annotations

import hashlib
import http.client
import json
import re
from dataclasses import dataclass
from urllib.parse import urlsplit
from uuid import UUID

from . import model_transport
from .states import ContractError

PROTOCOL = "a2a-0.3-jsonrpc-bounded"
CAPABILITIES = frozenset({"stratforge.json_arithmetic.v1"})
MAX_BYTES = 64 * 1024
METHODS = frozenset({"agent/getAuthenticatedExtendedCard", "message/send", "tasks/get", "tasks/cancel"})
REMOTE_STATES = frozenset({"submitted", "working", "input-required", "auth-required", "completed", "canceled", "failed", "rejected", "unknown"})


def target(endpoint, *, resolver=None):
    """Reuse the existing public-IP/DNS-rebind/TLS guard, with A2A paths.

    Agent-card URLs, redirects and artifact URLs never select another target.
    No URL credentials, query secrets, encoded paths or network-local targets.
    """
    try:
        parsed = urlsplit(endpoint)
        if (type(endpoint) is not str or len(endpoint) > 350 or parsed.scheme != "https"
                or not parsed.hostname or parsed.username or parsed.password
                or parsed.port not in (None, 443) or parsed.query or parsed.fragment
                or not re.fullmatch(r"/(?:[A-Za-z0-9_-]+/?)*", parsed.path)
                or any(ord(ch) < 33 or ord(ch) > 126 for ch in endpoint)):
            raise ValueError()
        host, _, address = model_transport.validate_target(
            "https://" + parsed.netloc + "/v1/chat/completions", resolver=resolver)
        return host, parsed.path, address
    except (ValueError, TypeError, AttributeError, model_transport.PrivateTransportError):
        raise ContractError("external_agent_endpoint_denied") from None


def _json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError()
            result[key] = value
        return result
    try:
        if len(raw) > MAX_BYTES:
            raise ValueError()
        result = json.loads(raw, object_pairs_hook=unique,
                            parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        if type(result) is not dict:
            raise ValueError()
        return result
    except (ValueError, TypeError, RecursionError, UnicodeError):
        raise ContractError("external_agent_response_invalid") from None


def request(endpoint, *, credential, packet, timeout):
    """One pinned HTTPS request, bounded bytes/time, no proxies or redirects."""
    if type(credential) is not str or not 8 <= len(credential) <= 4096 or any(
            ord(ch) < 33 or ord(ch) > 126 for ch in credential):
        raise ContractError("external_agent_credential_invalid")
    if type(timeout) is not int or not 1 <= timeout <= 30:
        raise ContractError("external_agent_timeout_invalid")
    if packet.get("method") not in METHODS:
        raise ContractError("external_agent_method_denied")
    host, path, address = target(endpoint)
    raw = json.dumps(packet, ensure_ascii=True, allow_nan=False).encode()
    if len(raw) > MAX_BYTES:
        raise ContractError("external_agent_request_too_large")
    connection = model_transport._PinnedHTTPSConnection(host, address, timeout)
    try:
        connection.request("POST", path, body=raw, headers={"Content-Type": "application/json",
            "Accept": "application/json", "Authorization": "Bearer " + credential})
        response = connection.getresponse()
        if response.status in {401, 403}:
            raise ContractError("external_agent_credential_denied")
        if response.status != 200:
            raise ContractError("external_agent_http_failure")
        return _json(response.read(MAX_BYTES + 1))
    except TimeoutError:
        # Transmission may have occurred; the caller must NOT automatically resend.
        raise ContractError("external_agent_outcome_unknown") from None
    except (OSError, http.client.HTTPException):
        raise ContractError("external_agent_outcome_unknown") from None
    finally:
        connection.close()


def _token(value):
    if type(value) is not str or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", value):
        raise ContractError("external_agent_reference_invalid")
    return value


@dataclass(frozen=True)
class Handshake:
    advertised: tuple[str, ...]
    allowed: tuple[str, ...]
    card_sha256: str
    protocol: str = PROTOCOL
    model: str = "unknown / externally managed"


@dataclass(frozen=True)
class RemoteTask:
    task_id: str
    context_id: str
    state: str
    data_json: str | None
    response_sha256: str


class A2AClient:
    """Explicit 0.3 subset: authenticated card, finite JSON tasks, get/cancel.

    No SSE/push/file download/tools/OAuth negotiation or automatic retry. The
    transport seam is a trusted composition dependency, never request JSON.
    """
    def __init__(self, transport=request):
        self.transport = transport

    def _rpc(self, endpoint, credential, method, params, request_id, timeout):
        _token(request_id)
        if method not in METHODS:
            raise ContractError("external_agent_method_denied")
        packet = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            packet["params"] = params
        result = self.transport(endpoint, credential=credential, packet=packet, timeout=timeout)
        if credential and credential in json.dumps(result, ensure_ascii=False):
            raise ContractError("external_agent_credential_echo_denied")
        if (type(result) is not dict or result.get("jsonrpc") != "2.0" or result.get("id") != request_id
                or ("result" in result) == ("error" in result)):
            raise ContractError("external_agent_response_invalid")
        if "error" in result:
            # Never surface untrusted error messages, which can echo credentials.
            raise ContractError("external_agent_rpc_refused")
        if type(result["result"]) is not dict:
            raise ContractError("external_agent_response_invalid")
        return result["result"]

    def verify(self, endpoint, credential, *, allowed, request_id, timeout=10):
        if not allowed or not set(allowed) <= CAPABILITIES:
            raise ContractError("external_agent_capability_denied")
        card = self._rpc(endpoint, credential, "agent/getAuthenticatedExtendedCard", None, request_id, timeout)
        schemes = card.get("securitySchemes", {})
        security = card.get("security", [])
        input_modes = card.get("defaultInputModes")
        output_modes = card.get("defaultOutputModes")
        if (card.get("protocolVersion") != "0.3.0" or card.get("url") != endpoint
                or card.get("preferredTransport", "JSONRPC") != "JSONRPC"
                or card.get("supportsAuthenticatedExtendedCard") is not True
                or type(schemes) is not dict or type(security) is not list
                or not any(type(item) is dict and len(item) == 1 and any(
                    isinstance(schemes.get(key), dict) and schemes[key].get("type") == "http"
                    and schemes[key].get("scheme") == "bearer" for key in item) for item in security)
                or type(input_modes) is not list or type(output_modes) is not list
                or "application/json" not in input_modes
                or "application/json" not in output_modes):
            raise ContractError("external_agent_protocol_incompatible")
        skills = card.get("skills")
        if type(skills) is not list or not 1 <= len(skills) <= 32:
            raise ContractError("external_agent_card_invalid")
        advertised_ids = []
        compatible_ids = set()
        for skill in skills:
            if type(skill) is not dict:
                raise ContractError("external_agent_card_invalid")
            identity = _token(skill.get("id"))
            if identity in advertised_ids:
                raise ContractError("external_agent_card_invalid")
            advertised_ids.append(identity)
            # Per-skill modes override card defaults; a matching ID alone does
            # not prove that this JSON-only adapter can execute the skill.
            incoming = skill.get("inputModes", input_modes)
            outgoing = skill.get("outputModes", output_modes)
            if type(incoming) is not list or type(outgoing) is not list:
                raise ContractError("external_agent_card_invalid")
            if "application/json" in incoming and "application/json" in outgoing:
                compatible_ids.add(identity)
        advertised = tuple(sorted(advertised_ids))
        granted = tuple(sorted(compatible_ids & set(allowed) & CAPABILITIES))
        if not granted:
            raise ContractError("external_agent_capability_incompatible")
        # Persist a digest and validated skill IDs, not arbitrary card text/URLs.
        digest = hashlib.sha256(json.dumps(card, sort_keys=True, allow_nan=False).encode()).hexdigest()
        return Handshake(advertised, granted, digest)

    def send(self, endpoint, credential, *, task_id, intent_id, capability, values, request_id, timeout=10):
        if capability not in CAPABILITIES or type(values) is not list or not 3 <= len(values) <= 20 or any(
                type(value) is not int or abs(value) > 1000000 for value in values):
            raise ContractError("external_agent_task_unsupported")
        try:
            UUID(task_id); UUID(intent_id)
        except (ValueError, TypeError, AttributeError):
            raise ContractError("external_agent_reference_invalid") from None
        # A Task reference is data, not an imported role/capability/authority.
        result = self._rpc(endpoint, credential, "message/send", {"message": {
            "kind": "message", "role": "user", "messageId": task_id, "contextId": intent_id,
            "parts": [{"kind": "data", "data": {"capability": capability, "values": values}}]},
            "configuration": {"blocking": False, "acceptedOutputModes": ["application/json"]}}, request_id, timeout)
        return self._task(result, context_id=intent_id)

    def get(self, endpoint, credential, *, task_id, context_id, request_id, timeout=10):
        result = self._rpc(endpoint, credential, "tasks/get", {"id": _token(task_id), "historyLength": 0}, request_id, timeout)
        return self._task(result, context_id=context_id, task_id=task_id)

    def cancel(self, endpoint, credential, *, task_id, context_id, request_id, timeout=10):
        result = self._rpc(endpoint, credential, "tasks/cancel", {"id": _token(task_id)}, request_id, timeout)
        # A cancel request is NOT cancellation. Return actual remote state.
        return self._task(result, context_id=context_id, task_id=task_id)

    @staticmethod
    def _task(result, *, context_id, task_id=None):
        if (result.get("kind") != "task" or result.get("contextId") != context_id
                or (task_id is not None and result.get("id") != task_id)
                or type(result.get("status")) is not dict or result["status"].get("state") not in REMOTE_STATES):
            raise ContractError("external_agent_task_binding_invalid")
        remote_id = _token(result.get("id"))
        data = None
        if result["status"]["state"] == "completed":
            artifacts = result.get("artifacts")
            if type(artifacts) is not list or len(artifacts) != 1 or type(artifacts[0]) is not dict:
                raise ContractError("external_agent_artifact_invalid")
            parts = artifacts[0].get("parts")
            if type(parts) is not list or len(parts) != 1 or type(parts[0]) is not dict or parts[0].get("kind") != "data" or type(parts[0].get("data")) is not dict:
                raise ContractError("external_agent_artifact_invalid")
            data = json.dumps(parts[0]["data"], sort_keys=True, allow_nan=False)
            if len(data.encode()) > 4096:
                raise ContractError("external_agent_artifact_invalid")
        digest = hashlib.sha256(json.dumps(result, sort_keys=True, allow_nan=False).encode()).hexdigest()
        return RemoteTask(remote_id, context_id, result["status"]["state"], data, digest)
