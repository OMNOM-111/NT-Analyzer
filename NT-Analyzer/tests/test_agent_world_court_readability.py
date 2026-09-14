"""Render shipped Court cards: truthful local provenance, collapsed identities."""
from pathlib import Path
import subprocess
import json

from tests.test_agent_world_court_development_e2e import court, world, decision, review  # noqa: F401


def test_court_synthetic_provenance_and_identifiers_are_distinct():
    root = Path(__file__).resolve().parents[1]
    script = r'''
const assert=require('node:assert/strict'),fs=require('node:fs');
const file='./app/static/aurora/assets/pages/ai-command-center.js';
const ui=require(file),source=fs.readFileSync(file,'utf8');
const body=source.split('function courtPanel(item) {')[1].split('\n  }')[0];
const render=new Function('item','rows','esc','badge',body);
const vote={verdict:'approve',confidence:0,rationale:'Diagnostic vote',provider_key:'deepseek',
 model_key:'development-court-approve',model_version:'agent-world-local-test-executor-v1',
 failure_domain:'local_test_executor:agent-world-local-test-executor-v1',session_id:'private-session-id',packet_sha256:'private-packet-hash'};
const card=render({court_cases:[{verdict:'approved',quorum:'2/3',packet_sha256:'case-packet-hash',votes:[vote]}]},ui.rows,ui.esc,ui.badge);
const main=card.replace(/<details\b[\s\S]*?<\/details>/g,'');
assert.ok(main.includes('SYNTHETIC'));
assert.ok(main.includes('внешний провайдер не вызывался'));
assert.ok(main.includes('Уверенность: 0'));
assert.ok(main.includes('кворум 2/3'));
for(const token of ['deepseek','private-session-id','private-packet-hash','case-packet-hash','development-court-approve']) {
 assert.ok(card.includes(token)); assert.ok(!main.includes(token));
}
const unknown=render({votes:[{...vote,model_version:'not-known',failure_domain:'not-known'}]},ui.rows,ui.esc,ui.badge);
assert.ok(!unknown.includes('внешний провайдер не вызывался'));
assert.ok(!unknown.includes('SYNTHETIC'));
const missing=render({},ui.rows,ui.esc,ui.badge);
assert.ok(missing.includes('Отсутствие голосов не является одобрением'));
'''
    result = subprocess.run(["node", "-e", script], cwd=root, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr


def test_stored_native_court_gateway_read_renders_actual_local_provenance(court):
    from app.ai_control_center import domain_gateway as gateway
    from app.ai_control_center.test_executor import EXECUTOR
    created = decision(court)
    review(court, created)
    # Fresh GET projection from stored records, not the mutation response/fixture DTO.
    result = gateway.list_domain(court.auth, "decisions", identity=created["id"])
    votes = result["court_cases"][0]["votes"]
    assert len(votes) == 3
    assert all(vote["model_version"] == EXECUTOR for vote in votes)
    assert {vote["failure_domain"] for vote in votes} == {"local_test_executor:" + EXECUTOR}
    root = Path(__file__).resolve().parents[1]
    script = r'''
const fs=require('node:fs'),assert=require('node:assert/strict');
const file='./app/static/aurora/assets/pages/ai-command-center.js',ui=require(file);
const body=fs.readFileSync(file,'utf8').split('function courtPanel(item) {')[1].split('\n  }')[0];
const item=JSON.parse(fs.readFileSync(0,'utf8'));
const html=new Function('item','rows','esc','badge',body)(item,ui.rows,ui.esc,ui.badge);
const main=html.replace(/<details\b[\s\S]*?<\/details>/g,'');
assert.equal((main.match(/Локальный проверяющий · SYNTHETIC/g)||[]).length,3);
assert.equal((main.match(/внешний провайдер не вызывался/g)||[]).length,3);
for(const vote of item.court_cases[0].votes) {
 assert.ok(html.includes(vote.session_id)); assert.ok(!main.includes(vote.session_id));
 assert.ok(html.includes(vote.packet_sha256)); assert.ok(!main.includes(vote.packet_sha256));
}
assert.ok(!main.includes('deepseek'));
'''
    process = subprocess.run(["node", "-e", script], cwd=root, input=json.dumps(result),
        capture_output=True, text=True, timeout=15)
    assert process.returncode == 0, process.stdout + process.stderr
