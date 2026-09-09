"""The bounded private endpoint contract, not an arbitrary remote-agent bridge."""
from .states import ContractError

CHAT_PROTOCOL = "chat_completions_v1"


def validate(profile):
    # Existing owner-registry bindings retain their existing transport. They
    # are not private external-agent connections and are never reconfigured.
    if profile.get("credential_source") == "owner_registry_binding":
        return "existing_owner_registry"
    protocol = profile.get("protocol", CHAT_PROTOCOL)
    if protocol != CHAT_PROTOCOL:
        raise ContractError("model_protocol_not_supported")
    return protocol


def describe(profile):
    try:
        protocol, supported = validate(profile), True
    except ContractError:
        protocol, supported = str(profile.get("protocol") or "unavailable"), False
    return {"protocol": protocol, "protocol_supported": supported,
            "capabilities": {"text": supported, "remote_tools": False,
                "remote_tasks": False, "mcp": False, "a2a": False, "artifacts": False}}
