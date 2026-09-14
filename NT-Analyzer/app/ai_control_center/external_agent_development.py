"""Bounded serialized Development adapter; not a public network exception."""
import json
from .external_agent_protocol import A2AClient, CAPABILITIES
from .flags import Flag, current_snapshot, resolve
from .states import ContractError
from .contracts import Environment
from .. import preview_sandbox, runtime_env

ENDPOINT = "https://development-agent.invalid/a2a"
CREDENTIAL = "synthetic-no-real-credential"


def enabled(authorized):
    ctx = authorized["context"]
    return (ctx.scope.environment == Environment.DEVELOPMENT and runtime_env.is_development()
        and not preview_sandbox.enabled() and resolve(Flag.AI_EXTERNAL_AGENT_TEST_V1,
            scope=ctx.scope, snapshot=current_snapshot(authorized)).enabled)


def client(authorized):
    def transport(endpoint, *, credential, packet, timeout):
        if not enabled(authorized) or endpoint != ENDPOINT:
            raise ContractError("external_agent_test_disabled")
        if credential != CREDENTIAL:
            raise ContractError("external_agent_credential_denied")
        request = json.loads(json.dumps(packet))
        if request["method"] == "agent/getAuthenticatedExtendedCard":
            result = {"protocolVersion": "0.3.0", "url": ENDPOINT, "preferredTransport": "JSONRPC",
                "supportsAuthenticatedExtendedCard": True, "securitySchemes": {"bearer": {"type": "http", "scheme": "bearer"}},
                "security": [{"bearer": []}], "defaultInputModes": ["application/json"], "defaultOutputModes": ["application/json"],
                "name": "Development diagnostic", "version": "1", "description": "Synthetic, no Model",
                "skills": [{"id": cap, "name": "Numeric summary", "description": "Synthetic", "tags": ["diagnostic"]} for cap in CAPABILITIES]}
        elif request["method"] == "message/send":
            message = request["params"]["message"]
            data = message["parts"][0]["data"]
            if data["capability"] not in CAPABILITIES:
                raise ContractError("external_agent_task_unsupported")
            values = data["values"]
            result = {"kind": "task", "id": message["messageId"], "contextId": message["contextId"],
                "status": {"state": "completed"}, "artifacts": [{"artifactId": "diagnostic", "parts": [{"kind": "data", "data": {
                    "count": len(values), "sum": sum(values), "min": min(values), "max": max(values), "mean": sum(values)/len(values)}}]}]}
        else:
            raise ContractError("external_agent_task_not_found")
        return json.loads(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result}))
    return A2AClient(transport)
