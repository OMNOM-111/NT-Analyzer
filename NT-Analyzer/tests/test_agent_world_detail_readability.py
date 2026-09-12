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


def test_external_task_html_uses_native_status_and_historical_cost_and_chat_truth():
    root = Path(__file__).resolve().parents[1]
    script = r'''
const assert=require('node:assert/strict'), fs=require('node:fs');
const source=fs.readFileSync('./app/static/aurora/assets/pages/ai-command-center.js','utf8');
const body=source.split('function externalTaskProvenance(task) {')[1].split('\n  }')[0];
const render=new Function('task',body);
const old=render({source_kind:'external_agent_task_v1',external_call:false,cost_usd:null});
assert.ok(old.includes('не записана')); assert.ok(old.includes('не заменяется нулём'));
assert.ok(!render({source_kind:'external_agent_task_v1',external_call:false,cost_usd:0}).includes('не записана'));
assert.equal(render({source_kind:'real_model_response'}),'');
const ui=require('./app/static/aurora/assets/pages/ai-command-center.js');
const html=ui.externalAgentCard({id:'connection',status:'active',statistics:{results_received:1,reviews_completed:1,awaiting_review:0},
 tasks:[{id:'task',status:'review',ledger_status:'review',display_status:'completed',display_status_label:'Проверка завершена',synthetic:true}]});
assert.ok(html.includes('Проверка завершена')); assert.ok(!html.includes('Нужна проверка'));
assert.ok(html.includes('ledger_status'));
assert.ok(source.includes("detailTab === 'summary' && task.source_kind === 'bounded_delegation_result' && detail.graph"));
assert.ok(source.includes('task.conversation_id ? `<button class="btn" data-aw-task-chat='));
assert.ok(source.includes('У исторической задачи нет связанного диалога.'));
'''
    result = subprocess.run(["node", "-e", script], cwd=root, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
