"""Actual serialized A2A exchange with a disposable deterministic HTTP agent.

The loopback transport exists only in this test, never in a request field or
the shipped remote transport. This is not a credentialed-provider benchmark,
native Coordinator wiring, or durable registry acceptance.
"""
from __future__ import annotations

import copy
import hashlib
import http.client
import json
import threading
from dataclasses import replace
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from uuid import uuid4

import pytest

from app.ai_control_center import contracts as c
from app.ai_control_center import external_agent_protocol as p
from app.ai_control_center.external_agent_contracts import ExternalAgentConnection, candidate
from app.ai_control_center.model_evaluation import prepare, evaluate
from app.ai_control_center.states import ContractError


ENDPOINT = "https://agent.example/a2a"
KEY = "explicitly-not-a-real-test-credential"
CAP = "stratforge.json_arithmetic.v1"


def card():
    return {"protocolVersion": "0.3.0", "url": ENDPOINT, "name": "Deterministic test agent",
        "description": "SYNTHETIC; no model, tools, trading or external provider", "version": "1",
        "preferredTransport": "JSONRPC", "supportsAuthenticatedExtendedCard": True,
        "securitySchemes": {"bearer": {"type": "http", "scheme": "bearer"}}, "security": [{"bearer": []}],
        "defaultInputModes": ["application/json"], "defaultOutputModes": ["application/json"],
        "skills": [{"id": CAP, "name": "Numeric summary", "description": "Count and sum", "tags": ["synthetic"]}],
        "capabilities": {"streaming": False, "pushNotifications": False}}


@pytest.fixture
def agent():
    records, requests = {}, []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            if self.headers.get("Authorization") != "Bearer " + KEY:
                self.send_response(401); self.end_headers(); return
            packet = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append(packet)
            method, params = packet["method"], packet.get("params", {})
            result = None
            error = None
            if method == "agent/getAuthenticatedExtendedCard":
                result = card()
            elif method == "message/send":
                message = params["message"]
                data = message["parts"][0]["data"]
                if data["capability"] != CAP:
                    error = {"code": -32602, "message": "Unsupported"}
                else:
                    tid = message["messageId"]
                    fingerprint = hashlib.sha256(json.dumps(message, sort_keys=True).encode()).hexdigest()
                    if tid in records and records[tid][0] != fingerprint:
                        error = {"code": -32602, "message": "Same ID with different input"}
                    elif tid in records:
                        result = records[tid][1]
                    else:
                        values = data["values"]
                        result = {"kind": "task", "id": tid, "contextId": message["contextId"],
                            "status": {"state": "working"}, "artifacts": [{"artifactId": "summary", "parts": [{"kind": "data", "data": {
                                "count": len(values), "sum": sum(values), "min": min(values), "max": max(values), "mean": sum(values) / len(values)}}]}]}
                        records[tid] = [fingerprint, result]
            elif method in {"tasks/get", "tasks/cancel"}:
                row = records.get(params["id"])
                if not row:
                    error = {"code": -32001, "message": "Absent"}
                else:
                    result = row[1]
                    result["status"]["state"] = "canceled" if method == "tasks/cancel" else "completed"
            else:
                error = {"code": -32601, "message": "Unsupported"}
            output = {"jsonrpc": "2.0", "id": packet["id"], **({"error": error} if error else {"result": result})}
            raw = json.dumps(output).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()

    def transport(endpoint, *, credential, packet, timeout):
        assert endpoint == ENDPOINT
        wire = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=timeout)
        try:
            wire.request("POST", "/a2a", body=json.dumps(packet), headers={"Authorization": "Bearer " + credential})
            response = wire.getresponse()
            if response.status == 401:
                raise ContractError("external_agent_credential_denied")
            assert response.status == 200
            return p._json(response.read(p.MAX_BYTES + 1))
        finally:
            wire.close()

    yield p.A2AClient(transport), records, requests
    server.shutdown(); server.server_close(); thread.join(timeout=2)


def connection():
    now, owner = datetime.now(timezone.utc), uuid4()
    scope = c.TenantScope(environment=c.Environment.DEVELOPMENT, workspace_id="ws_external_agent_test")
    actor = c.ActorRef(kind=c.ActorKind.HUMAN, actor_id=owner)
    context = c.RequestContext(scope=scope, user_uuid=owner, actor=actor)
    snapshot = c.SnapshotRef(scope=scope, artifact_id=uuid4(), sha256="a" * 64)
    header = c.RecordHeader(entity_id=uuid4(), scope=scope, owner_user_uuid=owner, revision=1,
        created_at=now, updated_at=now, created_by=actor, correlation_id=uuid4(), policy=snapshot)
    row = ExternalAgentConnection(header=header, display_name="External QA", protocol=p.PROTOCOL,
        endpoint=ENDPOINT, credential=c.ExternalRef(authority=c.ExternalAuthority.CREDENTIAL,
        key="aw_external.test-opaque-reference", scope=scope), requested_capabilities=(CAP,), synthetic=True)
    role = c.AgentRole(header=replace(header, entity_id=uuid4()), status="active", role_key="model_response",
        responsibilities=snapshot, capability_ceiling=("ai_pro_models",), autonomy_ceiling=c.Autonomy.ADVICE)
    return row, context, role


def test_real_wire_handshake_task_poll_independent_verifier_and_cancel(agent):
    client, records, requests = agent
    proof = client.verify(ENDPOINT, KEY, allowed=(CAP,), request_id="verify-1")
    row, context, role = connection()
    verifying = row.transition("verifying", now=row.header.updated_at)
    active = verifying.transition("active", now=row.header.updated_at, proof=proof, latency_ms=1)
    assert candidate(active, context=context, role=role, capability=CAP)
    tid, intent = str(uuid4()), str(uuid4())
    sent = client.send(ENDPOINT, KEY, task_id=tid, intent_id=intent, capability=CAP,
                       values=[3, 6, 9], request_id="send-1")
    assert sent.state == "working" and sent.data_json is None
    final = client.get(ENDPOINT, KEY, task_id=sent.task_id, context_id=intent, request_id="read-1")
    assert final.state == "completed"
    observation = evaluate(prepare("json_arithmetic", "[3,6,9]"), final.data_json)
    assert observation["passed"] is True and observation["self_scored"] is False
    assert not evaluate(prepare("json_arithmetic", "[3,6,10]"), final.data_json)["passed"]
    assert len(records) == 1
    revoked = active.transition("revoked", now=row.header.updated_at)
    assert not candidate(revoked, context=context, role=role, capability=CAP)
    with pytest.raises(ContractError, match="transition_denied"):
        revoked.transition("verifying", now=row.header.updated_at)
    assert revoked.public()["model_id"] is None
    assert "aw_external" not in json.dumps(revoked.public()) and KEY not in json.dumps(requests)
    tid2 = str(uuid4())
    sent2 = client.send(ENDPOINT, KEY, task_id=tid2, intent_id=intent, capability=CAP,
                        values=[3, 6, 9], request_id="send-2")
    assert client.cancel(ENDPOINT, KEY, task_id=sent2.task_id, context_id=intent, request_id="cancel-2").state == "canceled"


def test_duplicate_request_is_same_task_and_changed_input_refused(agent):
    client, records, _ = agent
    args = dict(task_id=str(uuid4()), intent_id=str(uuid4()), capability=CAP, values=[1, 2, 3], request_id="same-request")
    first = client.send(ENDPOINT, KEY, **args)
    assert client.send(ENDPOINT, KEY, **args) == first and len(records) == 1
    with pytest.raises(ContractError, match="rpc_refused"):
        client.send(ENDPOINT, KEY, **{**args, "values": [4, 5, 6]})
    assert len(records) == 1


def test_wrong_credential_really_refused_by_http_agent(agent):
    with pytest.raises(ContractError, match="credential_denied"):
        agent[0].verify(ENDPOINT, "not-the-test-credential", allowed=(CAP,), request_id="verify-wrong")


@pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.1", "172.16.1.1", "192.168.1.1", "169.254.169.254", "0.0.0.0", "224.0.0.1", "::1", "fc00::1", "fe80::1"])
def test_production_transport_has_no_private_endpoint_exception(address):
    with pytest.raises(ContractError, match="endpoint_denied"):
        p.target(ENDPOINT, resolver=lambda *a, **k: [(None, None, None, None, (address, 443))])


@pytest.mark.parametrize("url", ["http://agent.example/a2a", "https://agent.example:8443/a2a", "https://user:secret@agent.example/a2a",
    "https://agent.example/a2a?key=x", "https://agent.example/a2a#x", "https://agent.example/%2fadmin",
    "https://agent.example/../admin", "https://agent.example/a2a\n", "https://agent.example/a2a\\x"])
def test_url_rejects_credentials_encoded_paths_and_ambiguous_targets(url):
    with pytest.raises(ContractError, match="endpoint_denied"):
        p.target(url, resolver=lambda *a, **k: [(None, None, None, None, ("8.8.8.8", 443))])


@pytest.mark.parametrize("changes", [{"protocolVersion": "1.0"}, {"url": "https://other.example/a2a"},
    {"preferredTransport": "GRPC"}, {"security": []}, {"supportsAuthenticatedExtendedCard": False},
    {"defaultOutputModes": ["text/html"]}, {"defaultInputModes": None}, {"defaultOutputModes": None},
    {"skills": [{"id": "trading.execute"}]}])
def test_handshake_rejects_incompatible_contract_instead_of_manual_verified(changes):
    client = p.A2AClient(lambda endpoint, **kw: {"jsonrpc": "2.0", "id": kw["packet"]["id"], "result": {**card(), **changes}})
    with pytest.raises(ContractError):
        client.verify(ENDPOINT, KEY, allowed=(CAP,), request_id="verify-incompatible")


def test_advertised_capabilities_never_grant_admin_or_trading():
    data = card(); data["skills"] += [{"id": "trading.execute"}, {"id": "admin.release"}]
    client = p.A2AClient(lambda endpoint, **kw: {"jsonrpc": "2.0", "id": kw["packet"]["id"], "result": data})
    proof = client.verify(ENDPOINT, KEY, allowed=(CAP,), request_id="verify-advertised")
    assert proof.allowed == (CAP,) and "trading.execute" in proof.advertised
    with pytest.raises(ContractError, match="capability_denied"):
        client.verify(ENDPOINT, KEY, allowed=(CAP, "trading.execute"), request_id="deny-grant")


@pytest.mark.parametrize("kind", ["workspace", "principal", "role_scope", "role_owner", "authority", "capability"])
def test_candidate_scope_and_role_ceiling_are_not_self_claims(kind):
    row, context, role = connection()
    row = row.transition("verifying", now=row.header.updated_at).transition("active", now=row.header.updated_at,
        proof=p.Handshake((CAP,), (CAP,), "a" * 64))
    if kind == "workspace":
        context = replace(context, scope=replace(context.scope, workspace_id="ws_foreign_agent_test"))
    elif kind == "principal":
        owner = uuid4(); context = replace(context, user_uuid=owner, actor=c.ActorRef(kind=c.ActorKind.HUMAN, actor_id=owner))
    elif kind == "role_scope":
        other = replace(context.scope, workspace_id="ws_foreign_agent_test")
        role = replace(role, header=replace(role.header, scope=other, policy=replace(role.header.policy, scope=other)), responsibilities=replace(role.responsibilities, scope=other))
    elif kind == "role_owner":
        role = replace(role, header=replace(role.header, owner_user_uuid=uuid4()))
    elif kind == "authority":
        role = replace(role, autonomy_ceiling=c.Autonomy.REVERSIBLE_EXECUTION)
    if kind in {"workspace", "principal", "role_scope", "role_owner"}:
        with pytest.raises(ContractError): candidate(row, context=context, role=role, capability=CAP)
    else:
        assert not candidate(row, context=context, role=role, capability="trading.execute" if kind == "capability" else CAP)


@pytest.mark.parametrize("mutation", ["duplicate", "non_object", "input_text", "output_text", "null_modes"])
def test_matching_skill_id_is_not_sufficient_negotiation(mutation):
    data = card()
    if mutation == "duplicate":
        data["skills"].append(copy.deepcopy(data["skills"][0]))
    elif mutation == "non_object":
        data["skills"].append(None)
    elif mutation == "input_text":
        data["skills"][0]["inputModes"] = ["text/plain"]
    elif mutation == "output_text":
        data["skills"][0]["outputModes"] = ["text/plain"]
    else:
        data["skills"][0]["inputModes"] = None
    client = p.A2AClient(lambda endpoint, **kw: {"jsonrpc": "2.0", "id": kw["packet"]["id"], "result": data})
    with pytest.raises(ContractError):
        client.verify(ENDPOINT, KEY, allowed=(CAP,), request_id="verify-skill-contract")


@pytest.mark.parametrize("raw", [b'{"id":1,"id":2}', b'{"x":NaN}', b'[]', b'x', b'{"x":"' + b'x' * p.MAX_BYTES + b'"}'], ids=["duplicate", "nan", "array", "invalid", "oversize"])
def test_untrusted_json_is_strict_and_bounded(raw):
    with pytest.raises(ContractError, match="response_invalid"):
        p._json(raw)


def test_cancel_does_not_claim_remote_stopped_when_server_already_completed():
    tid, intent = str(uuid4()), str(uuid4())
    data = {"kind": "task", "id": tid, "contextId": intent, "status": {"state": "completed"},
        "artifacts": [{"parts": [{"kind": "data", "data": {"count": 3}}]}]}
    client = p.A2AClient(lambda endpoint, **kw: {"jsonrpc": "2.0", "id": kw["packet"]["id"], "result": data})
    assert client.cancel(ENDPOINT, KEY, task_id=tid, context_id=intent, request_id="cancel-race").state == "completed"


@pytest.mark.parametrize("changes", [{"contextId": "foreign"}, {"id": "foreign"}, {"kind": "message"}, {"status": {"state": "invented"}}])
def test_remote_task_identity_and_status_binding(changes):
    data = {"kind": "task", "id": "task-one", "contextId": "context-one", "status": {"state": "working"}, **changes}
    with pytest.raises(ContractError, match="binding_invalid"):
        p.A2AClient._task(data, context_id="context-one", task_id="task-one")


def test_malicious_credential_echo_is_not_exposed():
    client = p.A2AClient(lambda endpoint, **kw: {"jsonrpc": "2.0", "id": kw["packet"]["id"], "result": {**card(), "description": KEY}})
    with pytest.raises(ContractError, match="credential_echo_denied") as error:
        client.verify(ENDPOINT, KEY, allowed=(CAP,), request_id="echo-denied")
    assert KEY not in str(error.value)


def test_pinned_transport_times_out_without_automatic_resend(monkeypatch):
    seen = []
    class Wire:
        def __init__(self, host, address, timeout): seen.append((host, address, timeout))
        def request(self, *args, **kwargs): seen.append("send")
        def getresponse(self): raise TimeoutError("must not expose raw details")
        def close(self): seen.append("close")
    monkeypatch.setattr(p, "target", lambda _: ("agent.example", "/a2a", "8.8.8.8"))
    monkeypatch.setattr(p.model_transport, "_PinnedHTTPSConnection", Wire)
    with pytest.raises(ContractError, match="outcome_unknown"):
        p.request(ENDPOINT, credential=KEY, packet={"method": "message/send"}, timeout=3)
    assert seen == [("agent.example", "8.8.8.8", 3), "send", "close"]
