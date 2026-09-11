"""Native record storage checks, not Coordinator or browser acceptance."""
import pytest

from app.ai_control_center import contracts as c
from app.ai_control_center.external_agent_contracts import ExternalAgentConnection
from app.ai_control_center.external_agent_protocol import CAPABILITIES, PROTOCOL, Handshake
from app.ai_control_center.model_contracts import Evaluation
from app.ai_control_center.states import ContractError, EntityKind
from app.ai_control_center.sqlite_repository import SQLiteAgentWorldRepository
from tests.test_agent_world_storage import context, persona, arguments


def test_native_connection_revisions_event_replay_and_workspace_isolation(tmp_path):
    repo = SQLiteAgentWorldRepository(tmp_path / "external.sqlite3")
    ctx = context()
    base = persona(repo, ctx=ctx)
    caps = tuple(sorted(CAPABILITIES))
    row = ExternalAgentConnection(header=base.header, display_name="Native external",
        protocol=PROTOCOL, endpoint="https://agent.example/a2a", synthetic=True,
        credential=c.ExternalRef(authority=c.ExternalAuthority.CREDENTIAL,
            key="aw_external.synthetic-reference", scope=ctx.scope), requested_capabilities=caps)
    write = arguments(row, ctx=ctx, key="external-create")
    repo.commit(**write)
    assert repo.commit(**write).record == row
    assert repo.get(context=ctx, kind=row.KIND, entity_id=row.header.entity_id) == row
    assert repo.get(context=context(workspace="ws_other001"), kind=row.KIND, entity_id=row.header.entity_id) is None
    assert repo.get(context=context(user=2), kind=row.KIND, entity_id=row.header.entity_id) is None
    for status in ("verifying", "active", "revoked"):
        row = row.transition(status, now=row.header.updated_at,
            proof=Handshake(caps, caps, "a" * 64) if status == "active" else None)
        repo.commit(**arguments(row, ctx=ctx))
    restored = SQLiteAgentWorldRepository(tmp_path / "external.sqlite3")
    assert restored.get(context=ctx, kind=row.KIND, entity_id=row.header.entity_id).status == "revoked"
    assert restored.get_revision(context=ctx, kind=row.KIND, entity_id=row.header.entity_id, revision=3).status == "active"
    with pytest.raises(ContractError):
        row.transition("verifying", now=row.header.updated_at)


def test_external_subject_uses_shared_evaluation_not_model():
    from tests.test_agent_world_contracts import record, ref
    from app.ai_control_center.storage_codec import encode_record, decode_record
    evaluation = record(EntityKind.EVALUATION, subject=ref(EntityKind.EXTERNAL_AGENT_CONNECTION))
    assert isinstance(evaluation, Evaluation)
    assert decode_record(encode_record(evaluation)) == evaluation
    with pytest.raises(ContractError, match="evaluation_subject_not_a_model"):
        _ = evaluation.model
