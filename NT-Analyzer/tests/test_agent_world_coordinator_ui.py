"""Coordinator, Router and System handlers with isolated in-memory transport.

These are DOM/Node contracts, not browser, model quality, real dispatch or
provider acceptance. Production page sources are owned by the integrator.
"""
from __future__ import annotations

import json
import subprocess

import pytest

from tests import test_agent_world_ui as base


COORDINATOR = "55555555-5555-5555-5555-555555555555"
ROOT_MODEL = "22222222-2222-2222-2222-222222222222"
TARGETS = ["66666666-6666-6666-6666-666666666666", "77777777-7777-7777-7777-777777777777",
           "88888888-8888-8888-8888-888888888888"]
PLAN_SHA = "a" * 64
SOURCE_TASK = "33333333-3333-3333-3333-333333333333"
STARTED_TASK = "99999999-9999-9999-9999-999999999999"


def test_clarify_existing_intent_uses_same_public_payload_seam():
    values = {"goal": "Уточнённая цель", "input_text": "[1,2,3]",
              "coordinator_model_id": ROOT_MODEL, "target_model_ids": TARGETS,
              "topology": "chain", "operation": "client_must_not_choose"}
    result = base.evaluate(f"ui.domainPayload('automation','clarify_commission',{json.dumps(values)})")
    assert result["parent_indices"] == [-1, 0, 1]
    assert result["goal"] == values["goal"] and "operation" not in result


def router_prepared():
    return {"task_id": SOURCE_TASK, "source_revision": 7,
        "preview_ref": {"artifact_id": TARGETS[2], "sha256": "b" * 64,
            "media_type": "application/json", "scope": {"environment": "development", "workspace_id": "own"}},
        "source_request_sha256": "c" * 64, "selection_sha256": PLAN_SHA,
        "selected_model_id": TARGETS[0], "actual_model_id": ROOT_MODEL,
        "applied": False, "requires_explicit_apply": True, "creates_new_task": True,
        "status": "selected", "actions": ["apply"], "synthetic": False}


def schedule_values():
    return {"source_task_id": SOURCE_TASK, "model_id": ROOT_MODEL, "rubric_key": "json_arithmetic",
        "input_text": "[1,2,3]", "local_start": "2026-09-09T12:00", "occurrences": "2",
        "interval_minutes": "60", "grace_minutes": "5", "grant_hours": "4", "max_call_cost_usd": "0"}


def source():
    return {"id": COORDINATOR, "revision": 7, "goal": "Reviewed numeric goal", "status": "review",
        "stage": "awaiting_approval", "root_task_id": "33333333-3333-3333-3333-333333333333",
        "actions": ["preview_commission"]}


def prepared():
    return {"coordinator_id": COORDINATOR, "approved_plan_sha256": PLAN_SHA,
        "approved": False, "dispatches": 0, "actions": ["approve_commission"],
        "goal": "Reviewed <scope> goal", "limitation": "Checks facts, not professional trading skill",
        "plan": {"coordinator_id": COORDINATOR, "max_depth": 2, "synthetic": False, "nodes": [
            {"index": 0, "parent_index": -1, "depth": 1, "model_id": TARGETS[0], "connection_sha256": "b" * 64},
            {"index": 1, "parent_index": 0, "depth": 2, "model_id": TARGETS[1], "connection_sha256": "c" * 64}]}}


def commission(topology="chain", targets=None):
    return {"goal": "Check numeric facts", "input_text": "[17, -4, 12, 9]", "coordinator_model_id": ROOT_MODEL,
        "target_model_ids": TARGETS[:2] if targets is None else targets, "topology": topology}


def throws(expression):
    return base.evaluate(f"(() => {{try {{{expression};return false;}}catch(_){{return true;}}}})()")


def run_ui(monkeypatch, scenario, setup=""):
    """Use the accepted real-handler harness; inject fixture before page boot."""
    evaluate = base.evaluate
    fixture = f"""
      const coordinatorSource={json.dumps(source())}, coordinatorPrepared={json.dumps(prepared())};
      let previewResultOverride={{}}, approvalResult={{ok:true}}, approvalError=null, previewError=null;
      let commissionResult={{ok:true,item:coordinatorSource}};
      let clock=Date.parse('2026-09-08T12:00:00Z');
      class ClockDate extends Date {{static now(){{return clock;}}}}
      domains.automation={{enabled:true,actions:['commission'],items:[],commissions:[coordinatorSource],
        schedules:[],delegations:[],flags:{{AI_SCHEDULER_V1:false}},capability_admin:{{granted:true,can_manage:false}}}};
      domains.models.items.push(...{json.dumps(TARGETS)}.map((id,index)=>({{id,label:'Child '+index,model:'model-'+index,
        status:'active',connected:index!==0,can_execute_test_only:index===0,test_executor_verified:index===0}})));
      const originalAction=http.aiControlCenterDomainAction;
      http.aiControlCenterDomainAction=async(domain,id,action,body)=>{{
        if(domain==='automation'&&['preview_commission','approve_commission','commission'].includes(action)){{
          calls.push({{method:'post',domain,id,action,body:JSON.parse(JSON.stringify(body))}});
          if(action==='preview_commission'){{if(previewError)throw previewError;return JSON.parse(JSON.stringify({{...coordinatorPrepared,...previewResultOverride}}));}}
          if(action==='approve_commission'){{if(approvalError)throw approvalError;return JSON.parse(JSON.stringify(approvalResult));}}
          return JSON.parse(JSON.stringify(commissionResult));
        }}
        return originalAction(domain,id,action,body);
      }};
      {setup}
    """
    def injected(expression):
        needle = "vm.runInNewContext("
        assert expression.count(needle) == 1
        assert ",URLSearchParams,Date}" in expression
        expression = expression.replace(",URLSearchParams,Date}", ",URLSearchParams,Date:ClockDate}", 1)
        try:
            return evaluate(expression.replace(needle, fixture + "\n" + needle, 1))
        except subprocess.CalledProcessError as error:
            raise AssertionError("Real page harness failed: " + str(error.stderr)) from None
    monkeypatch.setattr(base, "evaluate", injected)
    return base.run_domain_ui(scenario)


def run_router_ui(monkeypatch, scenario, setup=""):
    # Detail links live in a visible Router listing, never an absent drawer.
    if "awRouterTask:ids.task" in scenario:
        scenario = "await click({awDomain:'router'},'shell');\n" + scenario
    fixture = f"""
      Object.assign(task,{{model_id:ids.model,conversation_id:'owned-chat',rubric_key:'json_arithmetic'}});
      Object.assign(response,task);
      domains.models.items[0].persona_id=ids.persona;
      domains.router={{enabled:true,items:[],actions:[],task_classes:['json_arithmetic','extract_facts','backtest_spec','chart_spec']}};
      let routingResponse={{...{json.dumps(router_prepared())}}}, routingApply={{ok:true,applied:true,started_task_id:{json.dumps(STARTED_TASK)}}};
      let routingError=null, routingDetail={{enabled:true,task,actions:['preview'],items:[{{model_id:{json.dumps(TARGETS[0])},label:'Candidate label',score_basis:'fixture facts'}}],
        actual_choice:{{routing_applied:false,decided_by:'request',actual_model:'original-provider-model'}},flags:{{AI_ROUTER_SHADOW_V2:true,AI_ROUTER_V2:true}}}};
      const routeDetail=http.aiControlCenterDomainItem, routeAction=http.aiControlCenterDomainAction;
      http.aiControlCenterDomainItem=async(domain,id)=>{{
        if(domain==='router'){{calls.push({{method:'detail',domain,id}});return JSON.parse(JSON.stringify(routingDetail));}}
        return routeDetail(domain,id);
      }};
      http.aiControlCenterDomainAction=async(domain,id,action,body)=>{{
        if(domain==='router'){{
          calls.push({{method:'post',domain,id,action,body:JSON.parse(JSON.stringify(body))}});
          if(routingError)throw routingError;
          return JSON.parse(JSON.stringify(action==='preview'?routingResponse:routingApply));
        }}
        return routeAction(domain,id,action,body);
      }};
      {setup}
    """
    return run_ui(monkeypatch, scenario, fixture)


def test_coordinator_helpers_are_exported_without_adding_a_page():
    assert base.evaluate("['validCoordinatorPreview','coordinatorApproval','connectionLabel'].every(key=>typeof ui[key]==='function')")
    assert base.PAGE.read_text(encoding="utf-8").count('data-aw-tab="') == 3


def test_valid_coordinator_preview_is_unapproved_bounded_and_source_bound():
    assert base.evaluate(f"ui.validCoordinatorPreview({json.dumps(prepared())},{json.dumps(source())})") is True
    assert not base.evaluate(f"ui.validCoordinatorPreview({json.dumps(prepared())},{{id:{json.dumps(TARGETS[0])}}})")


@pytest.mark.parametrize("change", [
    {"approved": True}, {"approved": 0}, {"dispatches": 1}, {"dispatches": "0"},
    {"approved_plan_sha256": "not-a-proof"}, {"approved_plan_sha256": "A" * 64},
    {"coordinator_id": "../other"}, {"actions": []}, {"actions": ["apply"]},
    {"plan": None}, {"plan": {"nodes": []}}, {"plan": {"nodes": [None]}},
    {"plan": {"nodes": ["unchecked"]}}, {"plan": {"nodes": [[-1, 1]]}},
    {"plan": {"nodes": [{"parent_index": -1, "depth": 1}] * 4}},
    {"plan": {"nodes": [{"parent_index": 0, "depth": 1}]}},
    {"plan": {"nodes": [{"parent_index": -2, "depth": 1}]}},
    {"plan": {"nodes": [{"parent_index": "-1", "depth": 1}]}},
    {"plan": {"nodes": [{"parent_index": -1, "depth": 4}]}},
    {"plan": {"nodes": [{"parent_index": -1, "depth": "1"}]}},
])
def test_malformed_preview_cannot_offer_approval(change):
    value = prepared() | change
    assert not base.evaluate(f"ui.validCoordinatorPreview({json.dumps(value)},{json.dumps(source())})")


def test_approval_payload_is_exact_hash_expiry_zero_cost_not_client_authority():
    values = {"grant_hours": "2", "max_call_cost_usd": "0", "workspace_id": "foreign", "is_owner": True,
        "api_key": "never-send", "approved_plan_sha256": "f" * 64, "expires_at": "2099-01-01T00:00:00Z"}
    result = base.evaluate(f"ui.coordinatorApproval({json.dumps(prepared())},{json.dumps(source())},{json.dumps(values)},Date.parse('2026-09-08T12:00:00Z'))")
    assert result == {"approved_plan_sha256": PLAN_SHA, "expires_at": "2026-09-08T14:00:00.000Z", "max_call_cost_usd": 0}


@pytest.mark.parametrize("change", [
    {"grant_hours": "0"}, {"grant_hours": "721"}, {"grant_hours": "1.5"}, {"grant_hours": "Infinity"},
    {"max_call_cost_usd": ".01"}, {"max_call_cost_usd": "-1"}, {"max_call_cost_usd": "NaN"},
    {"max_call_cost_usd": True}, {"grant_hours": [1]},
])
def test_approval_duration_and_zero_cost_ceiling_fail_closed(change):
    values = {"grant_hours": "1", "max_call_cost_usd": "0"} | change
    assert throws(f"ui.coordinatorApproval({json.dumps(prepared())},{json.dumps(source())},{json.dumps(values)},Date.now())")


@pytest.mark.parametrize("topology,count,parents,depth", [
    ("parallel", 1, [-1], 1), ("parallel", 2, [-1, -1], 1),
    ("chain", 1, [-1], 1), ("chain", 2, [-1, 0], 2), ("chain", 3, [-1, 0, 1], 3),
])
def test_commission_payload_matches_server_graph_boundaries(topology, count, parents, depth):
    values = commission(topology, TARGETS[:count]) | {"parent_indices": [99], "max_depth": 999, "api_key": "never-send"}
    result = base.evaluate(f"ui.domainPayload('automation','commission',{json.dumps(values)})")
    assert result["parent_indices"] == parents and result["max_depth"] == depth
    assert result["target_model_ids"] == TARGETS[:count]
    assert not {"topology", "api_key"} & result.keys()
    assert result["input_text"] == "[17, -4, 12, 9]"


@pytest.mark.parametrize("change", [
    {"target_model_ids": []}, {"target_model_ids": [ROOT_MODEL]},
    {"target_model_ids": ["foreign-model"]}, {"target_model_ids": TARGETS + [COORDINATOR]},
    {"topology": "unlimited"}, {"coordinator_model_id": "owner-key"},
    {"topology": "parallel", "target_model_ids": TARGETS},
])
def test_invalid_commission_selection_or_parallel_fanout_is_blocked(change):
    assert throws(f"ui.domainPayload('automation','commission',{json.dumps(commission() | change)})")


@pytest.mark.parametrize("model,text", [
    ({"can_execute_test_only": True, "connected": True}, "SYNTHETIC · только локальный тестовый исполнитель"),
    ({"connected": True}, "Реальное соединение проверено"),
    ({"test_executor_verified": True, "connected": False}, "Локальный тест сохранён; реальное соединение не проверено"),
    ({"connected": "true", "test_executor_verified": "true"}, "Реальное соединение не проверено"),
    ({"connected": False}, "Реальное соединение не проверено"),
    ({}, "Реальное соединение не проверено"),
])
def test_connection_labels_distinguish_real_verified_and_synthetic(model, text):
    assert base.evaluate(f"ui.connectionLabel({json.dumps(model)})") == text


def test_actual_commission_form_requires_user_gesture_and_narrow_graph_payload(monkeypatch):
    result = run_ui(monkeypatch, f"""
      await click({{awDomain:'automation'}},'shell');
      await click({{awDomainAction:'commission',awEntity:'new'}});
      const html=drawer.innerHTML, values={json.dumps(commission('chain', TARGETS))};
      await submit(form(values,false));const before=calls.filter(x=>x.method==='post').length;
      await submit(form(values,true));
      return {{html,before,posts:calls.filter(x=>x.method==='post')}};
    """)
    assert result["before"] == 0 and len(result["posts"]) == 1
    assert 'name="confirmation" required' in result["html"]
    assert "SYNTHETIC" in result["html"] and "Реальное соединение проверено" in result["html"]
    assert result["posts"][0]["action"] == "commission"
    assert result["posts"][0]["body"]["payload"]["parent_indices"] == [-1, 0, 1]
    assert result["posts"][0]["body"]["payload"]["max_depth"] == 3
    assert not any(post["action"] in {"approve_commission", "apply", "enable"} for post in result["posts"])


def test_public_commission_clarifies_meaning_before_any_task(monkeypatch):
    plan = {"status": "clarification_required", "goal": "Разобрать данные", "question": "Какой результат нужен?",
            "plan_sha256": PLAN_SHA, "choices": [{"id": "1", "label": "Проверить передачу", "available": True},
                                                  {"id": "2", "label": "Разобрать участки", "available": True}]}
    result = run_ui(monkeypatch, f"""
      await click({{awDomain:'automation'}},'shell');
      await click({{awDomainAction:'commission',awEntity:'new'}});
      await submit(form({json.dumps(commission('parallel', TARGETS[:1]))},true));
      const clarification=drawer.innerHTML;
      commissionResult={{ok:true,item:coordinatorSource}};
      await submit(form({{intent_choice:'2'}},true));
      return {{clarification,posts:calls.filter(x=>x.method==='post')}};
    """, "commissionResult=" + json.dumps(plan) + ";")
    assert "Задания ещё не запущены" in result["clarification"]
    assert "Разобрать участки" in result["clarification"]
    assert len(result["posts"]) == 2
    first, confirmed = [post["body"] for post in result["posts"]]
    assert "selection" not in first["payload"] and "operation" not in first["payload"]
    assert confirmed["payload"] == first["payload"] | {"selection": {"id": "2", "plan_sha256": PLAN_SHA}}
    assert first["idempotency_key"] == confirmed["idempotency_key"]


def test_open_plan_has_no_auto_dispatch_and_confirmation_starts_unchecked(monkeypatch):
    result = run_ui(monkeypatch, """
      await click({awDomain:'automation'},'shell');const listing=drawer.innerHTML;
      await click({awDomainAction:'preview_commission',awEntity:coordinatorSource.id});
      const before=calls.filter(x=>x.method==='post').length;
      await submit(form({}));const shown=drawer.innerHTML;
      await submit(form({grant_hours:'1',max_call_cost_usd:'0'},false));
      const noConsent=calls.filter(x=>x.method==='post').length;
      await submit(form({grant_hours:'1',max_call_cost_usd:'0'},true));
      return {listing,before,shown,noConsent,posts:calls.filter(x=>x.method==='post')};
    """)
    assert "Исходная задача и SF Chat" in result["listing"]
    assert result["before"] == 0 and result["noConsent"] == 1
    assert [row["action"] for row in result["posts"]] == ["preview_commission", "approve_commission"]
    assert 'type="checkbox" name="confirmation" required' in result["shown"]
    assert 'name="confirmation" required checked' not in result["shown"]
    assert "ДОЧЕРНИХ ЗАПУСКОВ НЕТ" in result["shown"] and "Reviewed &lt;scope&gt; goal" in result["shown"]
    assert "Каждый результат и общий вывод потребуют отдельной проверки" in result["shown"]
    approval = result["posts"][1]
    assert approval["id"] == COORDINATOR and approval["body"]["expected_revision"] == 7
    assert approval["body"]["payload"] == {"approved_plan_sha256": PLAN_SHA,
        "expires_at": "2026-09-08T13:00:00.000Z", "max_call_cost_usd": 0}


def test_forged_approve_action_cannot_skip_preview_even_if_list_contains_it(monkeypatch):
    result = run_ui(monkeypatch, """
      await click({awDomain:'automation'},'shell');const shown=drawer.innerHTML;
      await click({awDomainAction:'approve_commission',awEntity:coordinatorSource.id});
      return {unchanged:shown===drawer.innerHTML,posts:calls.filter(x=>x.method==='post')};
    """, "coordinatorSource.actions.push('approve_commission');")
    assert result == {"unchanged": True, "posts": []}


def test_approval_retry_freezes_expiry_and_key_and_blocks_changed_form(monkeypatch):
    result = run_ui(monkeypatch, """
      await click({awDomain:'automation'},'shell');
      await click({awDomainAction:'preview_commission',awEntity:coordinatorSource.id});await submit(form({}));
      approvalError={status:500,message:'must-not-render-private-secret'};
      const first=form({grant_hours:'1',max_call_cost_usd:'0'},true);await submit(first);
      clock+=25*60000;
      const second=form({grant_hours:'1',max_call_cost_usd:'0'},true);await submit(second);
      const before=calls.filter(x=>x.action==='approve_commission').length;
      const changed=form({grant_hours:'2',max_call_cost_usd:'0'},true);await submit(changed);
      return {before,posts:calls.filter(x=>x.action==='approve_commission'),firstError:first.error.textContent,
        changedError:changed.error.textContent};
    """)
    assert result["before"] == len(result["posts"]) == 2
    assert result["posts"][0]["body"] == result["posts"][1]["body"]
    assert result["posts"][0]["body"]["payload"]["expires_at"] == "2026-09-08T13:00:00.000Z"
    assert "откройте план заново" in result["changedError"]
    assert "must-not-render-private-secret" not in result["firstError"]


@pytest.mark.parametrize("response", [{"ok": False}, {"approved": True}, {"dispatches": 1},
    {"coordinator_id": TARGETS[0]}, {"plan": {"nodes": [None]}}])
def test_bad_or_source_changed_preview_never_opens_approval_form(monkeypatch, response):
    result = run_ui(monkeypatch, """
      await click({awDomain:'automation'},'shell');
      await click({awDomainAction:'preview_commission',awEntity:coordinatorSource.id});
      const attempt=form({});await submit(attempt);
      return {html:drawer.innerHTML,error:attempt.error.textContent,posts:calls.filter(x=>x.method==='post')};
    """, "previewResultOverride=" + json.dumps(response) + ";")
    assert len(result["posts"]) == 1 and result["posts"][0]["action"] == "preview_commission"
    assert 'name="grant_hours"' not in result["html"] and result["error"]


def test_source_changed_approval_response_does_not_refresh_or_apply(monkeypatch):
    result = run_ui(monkeypatch, """
      await click({awDomain:'automation'},'shell');
      await click({awDomainAction:'preview_commission',awEntity:coordinatorSource.id});await submit(form({}));
      const before=calls.filter(x=>x.method==='overview').length;
      const attempt=form({grant_hours:'1',max_call_cost_usd:'0'},true);await submit(attempt);
      return {before,after:calls.filter(x=>x.method==='overview').length,error:attempt.error.textContent,
        html:drawer.innerHTML,posts:calls.filter(x=>x.method==='post')};
    """, "approvalResult={ok:false,code:'coordinator_root_changed'};")
    assert result["before"] == result["after"] and result["error"]
    assert [row["action"] for row in result["posts"]] == ["preview_commission", "approve_commission"]
    assert "ДОЧЕРНИХ ЗАПУСКОВ НЕТ" in result["html"]


def test_system_separates_legacy_worker_from_disabled_execution_and_hides_payload(monkeypatch):
    setup = """
      domains.system.items=[
        {id:'worker',title:'Legacy worker',status:'active',implemented:true,enabled:true,available:true,mode:'legacy-local',note:'Only this worker is observed'},
        {id:'execution_v2',title:'Execution V2',status:'disabled',implemented:true,enabled:false,available:false,mode:'not_active',note:'Legacy worker does not enable Execution V2',fields:{secret:'hidden-system-key',mode:'technical-raw-payload'}},
        {id:'court',title:'Future component',status:'planned',implemented:false,enabled:false,available:false,mode:'not_implemented'}];
      domains.system.flags={AI_EXECUTION_ENGINE_V2:false};
    """
    result = run_ui(monkeypatch, """
      await click({awDomain:'system'},'shell');return {html:drawer.innerHTML,posts:calls.filter(x=>x.method==='post')};
    """, setup)
    text = result["html"]
    assert "Legacy worker" in text and "Execution V2" in text
    # Four separate facts per component, in plain words.
    assert "Реализовано" in text and "Как работает сейчас" in text and "Отвечает" in text
    assert "<dt>Отвечает</dt><dd>Нет</dd>" in text and "Выключен" in text and "not_active" in text
    assert "Legacy worker does not enable Execution V2" in text
    assert "hidden-system-key" not in text and "technical-raw-payload" in text
    assert text.index("Технические детали") < text.index("technical-raw-payload")
    assert result["posts"] == []


@pytest.mark.parametrize("enabled,actions,capability,expected", [
    (True, [], True, False), (True, ["seed_preview"], True, True),
    (False, ["seed_preview"], True, False), (True, [], False, False),
])
def test_seed_preview_is_explicit_and_only_the_server_action_authorizes_ui(monkeypatch, enabled, actions, capability, expected):
    setup = "domains.system=" + json.dumps({"enabled": enabled, "actions": [],
        "items": [{"id": "agent-world-domains-v1", "title": "Synthetic fixture", "revision": 0,
                   "status": "manual_only", "synthetic": True, "actions": actions}],
        "capabilities": {"can_seed_preview_dataset": capability},
        "preview_dataset": {"id": "agent-world-domains-v1", "operator_required": True}}) + ";"
    result = run_ui(monkeypatch, """
      await click({awDomain:'system'},'shell');const html=drawer.innerHTML;
      const before=calls.filter(x=>x.method==='post').length;
      await click({awDomainAction:'seed_preview',awEntity:'agent-world-domains-v1'});
      const formShown=drawer.innerHTML.includes('id="aw-domain-form"');
      if(formShown)await submit(form({},true));
      return {html,before,formShown,posts:calls.filter(x=>x.method==='post')};
    """, setup)
    assert result["before"] == 0 and result["formShown"] is expected
    assert ('data-aw-domain-action="seed_preview"' in result["html"]) is expected
    if expected:
        assert len(result["posts"]) == 1
        post = result["posts"][0]
        assert post["domain"] == "system" and post["action"] == "seed_preview"
        assert post["body"]["payload"] == {} and post["body"]["expected_revision"] == 0
    else:
        assert result["posts"] == []


def test_schedule_source_is_an_actual_task_selector_not_a_persona_or_free_text():
    fields = base.evaluate("ui.domainFormFields('automation','propose')")
    field = next(item for item in fields if item["key"] == "source_task_id")
    assert field["type"] == "source_task" and field["required"] is True
    assert "SF Chat" in field["label"]
    result = base.evaluate(f"ui.domainPayload('automation','propose',{json.dumps(schedule_values() | {'persona_id': TARGETS[0], 'is_owner': True, 'workspace_id': 'foreign'})})")
    assert result["source_task_id"] == SOURCE_TASK and result["model_id"] == ROOT_MODEL
    assert not {"persona_id", "is_owner", "workspace_id"} & result.keys()


@pytest.mark.parametrize("identity", ["", "not-a-task", "../outside", "owner-key"])
def test_schedule_source_invalid_task_ids_fail_before_network(identity):
    assert throws(f"ui.domainPayload('automation','propose',{json.dumps(schedule_values() | {'source_task_id': identity})})")


def test_schedule_form_loads_scoped_tasks_and_excludes_missing_chat_and_graphs(monkeypatch):
    setup = """
      coordinatorSource.actions.push('propose');
      domains.model_tasks.items.push(
        {...response,id:'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',title:'No chat source',conversation_id:null},
        {...response,id:'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',title:'No model source',model_id:null},
        {...response,id:'cccccccc-cccc-cccc-cccc-cccccccccccc',title:'Aggregate graph source',source_kind:'bounded_delegation_result'});
    """
    result = run_router_ui(monkeypatch, """
      await click({awDomain:'automation'},'shell');
      await click({awDomainAction:'propose',awEntity:coordinatorSource.id});
      return {html:drawer.innerHTML,calls};
    """, setup)
    assert f'value="{SOURCE_TASK}"' in result["html"] and "Actual task" in result["html"]
    assert not any(value in result["html"] for value in ("No chat source", "No model source", "Aggregate graph source"))
    assert f'<select id="aw-field-source_task_id" name="source_task_id" required>' in result["html"]
    assert any(call["method"] == "list" and call["domain"] == "model_tasks" and call["params"]["limit"] == 100 for call in result["calls"])
    assert not any(call["method"] == "post" for call in result["calls"])


def test_schedule_without_source_tasks_explains_missing_request_not_missing_model(monkeypatch):
    result = run_router_ui(monkeypatch, """
      await click({awDomain:'automation'},'shell');
      await click({awDomainAction:'propose',awEntity:coordinatorSource.id});return {html:drawer.innerHTML,calls};
    """, "coordinatorSource.actions.push('propose');domains.model_tasks.items=[];")
    assert "Наличие модели не заменяет исходную задачу" in result["html"]
    assert f'value="{SOURCE_TASK}"' not in result["html"]
    assert not any(call["method"] == "post" for call in result["calls"])


def test_router_listing_filters_supported_scoped_source_tasks_and_does_not_preview_on_get(monkeypatch):
    result = run_router_ui(monkeypatch, """
      await click({awDomain:'router'},'shell');return {html:drawer.innerHTML,calls};
    """, """
      domains.model_tasks.items.push(
        {...response,id:'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',title:'Connection-only diagnostic',rubric_key:'connection_exact'},
        {...response,id:'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',title:'Missing conversation',conversation_id:null},
        {...response,id:'cccccccc-cccc-cccc-cccc-cccccccccccc',title:'Missing model',model_id:null});
    """)
    assert "Actual task" in result["html"] and f'data-aw-router-task="{SOURCE_TASK}"' in result["html"]
    assert not any(text in result["html"] for text in ("Connection-only diagnostic", "Missing conversation", "Missing model"))
    assert "не заменит старый результат" in result["html"]
    assert not any(call["method"] == "post" for call in result["calls"])


def test_disabled_router_does_not_fetch_source_tasks_or_offer_launch(monkeypatch):
    result = run_router_ui(monkeypatch, """
      await click({awDomain:'router'},'shell');return {html:drawer.innerHTML,calls};
    """, "domains.router.enabled=false;domains.router.actions=['preview','apply'];")
    assert 'data-aw-router-task=' not in result["html"]
    assert not any(call["method"] == "list" and call["domain"] == "model_tasks" for call in result["calls"])
    assert not any(call["method"] == "post" for call in result["calls"])


@pytest.mark.parametrize("applied,label,not_label", [
    (False, "В исходной задаче подключение выбрано явно, не Router", "Эту задачу создал Router"),
    (True, "Эту задачу создал Router по подтверждённому выбору", "В исходной задаче подключение выбрано явно"),
])
def test_router_drawer_distinguishes_actual_choice_from_candidate_evidence(monkeypatch, applied, label, not_label):
    result = run_router_ui(monkeypatch, """
      await click({awRouterTask:ids.task});return {html:drawer.innerHTML,calls};
    """, "routingDetail.actual_choice.routing_applied=" + json.dumps(applied) + ";")
    assert label in result["html"] and not_label not in result["html"]
    assert 'data-aw-domain-action="preview"' in result["html"] and 'data-aw-domain-action="apply"' not in result["html"]
    assert "original-provider-model" in result["html"] and "Candidate label" in result["html"]
    assert result["html"].index("Фактический выбор, кандидаты и основания") < result["html"].index("original-provider-model")
    assert not any(call["method"] == "post" for call in result["calls"])


def test_router_detail_must_match_requested_source_task(monkeypatch):
    result = run_router_ui(monkeypatch, """
      await click({awRouterTask:ids.task});return {html:drawer.innerHTML,calls};
    """, "routingDetail.task={...task,id:'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'};")
    assert 'data-aw-domain-action="preview"' not in result["html"]
    assert not any(call["method"] == "post" for call in result["calls"])


def test_router_preview_requires_separate_unchecked_apply_and_opens_only_new_task(monkeypatch):
    result = run_router_ui(monkeypatch, """
      await click({awRouterTask:ids.task});
      await click({awDomainAction:'preview',awEntity:ids.task});
      const before=calls.filter(x=>x.method==='post').length;
      await submit(form({}));const html=drawer.innerHTML;
      await submit(form({},false));const unchecked=calls.filter(x=>x.method==='post').length;
      await submit(form({preview_ref:'forged-client-proof',workspace_id:'foreign'},true));
      return {before,unchecked,html,calls,source:{...task}};
    """)
    assert result["before"] == 0 and result["unchecked"] == 1
    assert 'type="checkbox" name="confirmation" required' in result["html"]
    assert 'name="confirmation" required checked' not in result["html"]
    assert "Исходный результат сохраняется" in result["html"]
    posts = [row for row in result["calls"] if row["method"] == "post"]
    assert [row["action"] for row in posts] == ["preview", "apply"]
    assert posts[0]["body"]["payload"] == {}
    assert posts[1]["body"]["payload"] == {"preview_ref": router_prepared()["preview_ref"]}
    assert posts[1]["body"]["expected_revision"] == 7 and posts[1]["id"] == SOURCE_TASK
    assert posts[0]["body"]["idempotency_key"] != posts[1]["body"]["idempotency_key"]
    assert any(row["method"] == "task" and row["id"] == STARTED_TASK for row in result["calls"])
    assert result["source"]["id"] == SOURCE_TASK and result["source"]["model_id"] == ROOT_MODEL
    assert result["source"]["status"] == "ready" and result["source"]["revision"] == 7


def test_forged_router_apply_click_cannot_skip_preview(monkeypatch):
    result = run_router_ui(monkeypatch, """
      await click({awRouterTask:ids.task});const html=drawer.innerHTML;
      await click({awDomainAction:'apply',awEntity:ids.task});
      return {unchanged:html===drawer.innerHTML,calls};
    """, "routingDetail.actions.push('apply');")
    assert result["unchanged"] is True
    assert not any(call["method"] == "post" for call in result["calls"])


def test_router_uncertain_apply_retry_preserves_exact_ref_revision_and_idempotency(monkeypatch):
    result = run_router_ui(monkeypatch, """
      await click({awRouterTask:ids.task});await click({awDomainAction:'preview',awEntity:ids.task});
      await submit(form({}));routingError={status:500,message:'router-private-key-do-not-render'};
      const first=form({},true);await submit(first);clock+=35*60000;
      const second=form({},true);await submit(second);
      return {posts:calls.filter(x=>x.action==='apply'),error:first.error.textContent,calls};
    """)
    assert len(result["posts"]) == 2 and result["posts"][0]["body"] == result["posts"][1]["body"]
    assert result["posts"][0]["body"]["expected_revision"] == 7
    assert "router-private-key-do-not-render" not in result["error"]
    assert not any(call["method"] == "task" for call in result["calls"])


@pytest.mark.parametrize("change", [
    {"ok": False}, {"applied": True}, {"applied": 0}, {"requires_explicit_apply": False},
    {"requires_explicit_apply": "true"}, {"creates_new_task": False},
    {"task_id": TARGETS[0]}, {"preview_ref": None}, {"selection_sha256": "unverified"},
    {"source_revision": "7"}, {"source_revision": None},
    {"source_revision": -1}, {"source_revision": 0}, {"preview_ref": "unverified"},
    {"preview_ref": []}, {"preview_ref": {}},
])
def test_malformed_or_source_changed_router_preview_never_opens_apply(monkeypatch, change):
    result = run_router_ui(monkeypatch, """
      await click({awRouterTask:ids.task});await click({awDomainAction:'preview',awEntity:ids.task});
      const attempt=form({});await submit(attempt);
      return {html:drawer.innerHTML,error:attempt.error.textContent,calls};
    """, "Object.assign(routingResponse," + json.dumps(change) + ");")
    assert "Разрешить новый запуск" not in result["html"] and result["error"]
    assert [call["action"] for call in result["calls"] if call["method"] == "post"] == ["preview"]


@pytest.mark.parametrize("change", [{"status": "no_candidate", "actions": []}, {"actions": []}, {"status": "blocked"}])
def test_router_without_allowed_selection_keeps_read_only_preview(monkeypatch, change):
    result = run_router_ui(monkeypatch, """
      await click({awRouterTask:ids.task});await click({awDomainAction:'preview',awEntity:ids.task});
      await submit(form({}));return {html:drawer.innerHTML,calls};
    """, "Object.assign(routingResponse," + json.dumps(change) + ");")
    assert "Нет доступного разрешённого выбора" in result["html"]
    assert 'id="aw-domain-form"' not in result["html"]
    assert [call["action"] for call in result["calls"] if call["method"] == "post"] == ["preview"]


def test_router_source_changed_apply_preserves_error_and_does_not_report_a_started_task(monkeypatch):
    result = run_router_ui(monkeypatch, """
      await click({awRouterTask:ids.task});await click({awDomainAction:'preview',awEntity:ids.task});
      await submit(form({}));const before=calls.filter(x=>x.method==='overview').length;
      const attempt=form({},true);await submit(attempt);
      return {before,after:calls.filter(x=>x.method==='overview').length,error:attempt.error.textContent,html:drawer.innerHTML,calls};
    """, "routingApply={ok:false,code:'routing_source_revision_conflict',started_task_id:'must-not-open'};")
    assert result["before"] == result["after"] and result["error"]
    assert "Выбор подготовлен" in result["html"]
    assert not any(call["method"] == "task" for call in result["calls"])


def test_aggregate_task_links_each_required_review_without_claiming_acceptance(monkeypatch):
    result = run_router_ui(monkeypatch, """
      await click({awTask:ids.task},'shell');return {html:drawer.innerHTML,calls};
    """, """
      task.source_kind=response.source_kind='bounded_delegation_result';
      response.graph={human_review:{status:'pending',required_reviews:[
        {task_id:ids.task,status:'accepted'},
        {task_id:'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',status:'pending'},
        {task_id:'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',status:'rejected'},
        {task_id:'cccccccc-cccc-cccc-cccc-cccccccccccc',status:'stale'}]}};
    """)
    assert "Участники и обязательные проверки" in result["html"]
    assert "Ожидается отдельная проверка" in result["html"] and "Источник изменился" in result["html"]
    assert "Отклонён" in result["html"] and "Принят" in result["html"]
    assert result["html"].count("Открыть результат и проверку") == 4
    assert "не означает приёмку всех вкладов" in result["html"]
    assert not any(call["method"] == "post" for call in result["calls"])
