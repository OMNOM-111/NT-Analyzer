"""Connection identity and technical task details stay accurate and unobtrusive."""
from pathlib import Path
import subprocess

from tests.test_agent_world_domain_service import env, model_service_fixture  # noqa: F401


def test_connection_metadata_comes_from_owned_record(env):
    service, ids, _ = model_service_fixture(env)
    from app.ai_control_center.states import EntityKind
    model = service._get(env.ctx, EntityKind.MODEL, ids[0])
    detail = service.model_detail(context=env.ctx, model_id=ids[0])
    assert detail["revision"] == model.header.revision
    assert detail["updated_at"] == model.header.updated_at.isoformat()
    assert detail["created_at"] == model.header.created_at.isoformat()
    persona = service._get(env.ctx, EntityKind.PERSONA, detail["persona_id"])
    assert detail["persona_name"] == persona.display_name


def test_task_technical_codes_are_retained_inside_collapsed_details():
    root = Path(__file__).resolve().parents[1]
    script = r'''
const assert=require('node:assert/strict');
const ui=require('./app/static/aurora/assets/pages/ai-command-center.js');
const html=ui.intentPanel({status:'accepted',revision:2,scope:{workspace_id:'ws_private_technical'},
 required_evidence:{verified_by:'independent_local_evidence_verifier',rubric_label:'Арифметика'}});
const details=html.match(/<details class="aw-technical"><summary>Технические сведения поручения<\/summary>[\s\S]*?<\/details>/)[0];
assert.ok(details.includes('ws_private_technical'));
assert.ok(details.includes('independent_local_evidence_verifier'));
const main=html.replace(details,'');
assert.ok(!main.includes('ws_private_technical'));
assert.ok(!main.includes('independent_local_evidence_verifier'));
assert.ok(main.includes('Независимая проверка сохранённых доказательств'));
'''
    result = subprocess.run(["node", "-e", script], cwd=root, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
    source = (root / "app/static/aurora/assets/pages/ai-command-center.js").read_text(encoding="utf-8")
    assert "spec.type === 'persona' ? (item.persona_name || 'Persona недоступна')" in source
    assert '<summary>Идентификатор Persona</summary>' in source
