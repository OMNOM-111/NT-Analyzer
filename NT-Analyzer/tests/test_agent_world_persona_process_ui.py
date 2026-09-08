"""Same-page Persona/PI contracts: real handlers, isolated transport/device.

No browser, provider request, owner key, live workspace or audible output. The
existing domain harness owns all temporary records. Fake speech events establish
lifecycle behavior only; they are not a claim that a voice device was heard.
"""
from __future__ import annotations

import json

import pytest

from tests import test_agent_world_ui as base


AUDIO = base.AURORA / "assets" / "persona-audio.js"
PERSONA_ID = "11111111-1111-1111-1111-111111111111"
CANDIDATE_ID = "a" * 64
SOURCE_SHA = "b" * 64


def candidate(domain="routines"):
    return {
        "id": CANDIDATE_ID, "domain": domain, "source_sha256": SOURCE_SHA,
        "title": "Review chart snapshots", "description": "Three stored results",
        "source_kind": "desktop_chart", "task_class": "chart", "sample_size": 3,
        "pending_source_reviews": 2, "interval_minutes": 1440,
        "first_at": "2026-09-04T12:00:00Z", "last_at": "2026-09-06T12:00:00Z",
        "starts_at": "2026-09-08T12:00:00Z", "ends_at": "2026-09-08T12:30:00Z",
        "confidence": "low", "automation_enabled": False, "quality_claim": False,
        "actions": ["propose"], "sources": [],
    }


def persona():
    return {
        "id": PERSONA_ID, "title": "Saved Persona", "status": "active", "revision": 7,
        "description": "Displayed description", "avatar_key": "marina",
        "presentation": {
            "version": "persona-presentation-v1", "avatar_key": "marina",
            "voice_profile_id": "marina", "resolved_voice_profile_id": "marina",
            "voice_label": "Marina preset", "voice_mode": "browser",
            "voice_language": "ru-RU", "voice_speed": 1.2,
            "animation_mode": "static", "expression_preset": "neutral", "lip_sync_mode": "off",
        },
    }


def run_ui(monkeypatch, scenario, setup=""):
    """Reuse the existing handler harness, injecting only a pre-boot fixture."""
    evaluate = base.evaluate

    def injected(expression):
        needle = "vm.runInNewContext("
        assert expression.count(needle) == 1
        return evaluate(expression.replace(needle, setup + "\n" + needle, 1))

    monkeypatch.setattr(base, "evaluate", injected)
    return base.run_domain_ui(scenario)


def test_audio_script_is_local_and_precedes_page_code_without_new_page():
    html = base.PAGE.read_text(encoding="utf-8")
    assert html.index('src="assets/persona-audio.js') < html.index('src="assets/pages/ai-command-center.js')
    assert html.count('data-aw-tab="') == 3
    assert AUDIO.is_file()
    script = base.SCRIPT.read_text(encoding="utf-8")
    assert "fetch(" not in script
    assert "localStorage" not in script and "document.cookie" not in script
    assert "API.aiControlCenterPersonaSpeak(request.persona_id" in script
    assert "PersonaAudio?.create" in script
    assert "speechSynthesis.speak(" not in script


def test_persona_form_uses_safe_defaults_and_server_catalog_labels():
    result = base.evaluate("ui.domainFormFields('personas','create',{version:'persona-presentation-v1',profiles:[{id:'marina',label:'Saved catalog label'},{id:'../../owner',label:'must-not-appear'}]})")
    fields = {field["key"]: field for field in result}
    assert fields["voice_profile_id"]["options"] == [["", "Профиль выбранного лица (если есть)"], ["marina", "Saved catalog label"]]
    assert fields["voice_mode"]["default"] == "browser"
    assert fields["voice_speed"]["default"] == 1
    assert fields["voice_speed"]["step"] == .1
    assert fields["voice_language"]["default"] == "ru-RU"
    assert fields["animation_mode"]["default"] == "auto"
    assert fields["lip_sync_mode"]["default"] == "auto"
    assert "недоступна" in fields["lip_sync_mode"]["options"][0][1]
    assert {"voice_profile_id", "voice_mode", "voice_speed", "voice_language", "animation_mode", "expression_preset", "lip_sync_mode"} <= fields.keys()


def test_new_persona_fields_are_additive_to_old_clients_not_model_or_authority():
    old = base.evaluate("ui.domainPayload('personas','update',{name:'Rename',avatar_key:'marina'})")
    assert old == {"name": "Rename", "avatar_key": "marina", "application_role": ""}
    values = {
        "name": "Rename", "avatar_key": "marina", "voice_profile_id": "deputy",
        "voice_mode": "browser", "voice_speed": "1.2", "voice_language": "en-US",
        "animation_mode": "static", "expression_preset": "speaking", "lip_sync_mode": "off",
        "model_id": "injected", "api_key": "never-copy", "is_owner": True,
    }
    result = base.evaluate(f"ui.domainPayload('personas','update',{json.dumps(values)})")
    assert result["voice_speed"] == 1.2 and result["avatar_key"] == "marina"
    assert result["voice_profile_id"] == "deputy"
    assert not {"model_id", "api_key", "is_owner"} & result.keys()


@pytest.mark.parametrize("speed", [.49, 1.81, "Infinity", "NaN", True, [1.2]])
def test_persona_speed_validation_is_bounded_and_routine_integer_rules_survive(speed):
    values = {"name": "Persona", "voice_speed": speed}
    assert base.evaluate(f"(() => {{try {{ui.domainPayload('personas','create',{json.dumps(values)}); return false;}} catch (_) {{return true;}}}})()")
    assert base.evaluate("(() => {try {ui.domainPayload('routines','create',{title:'No decimals',interval_minutes:'5.5'});return false;}catch(_){return true;}})()")


@pytest.mark.parametrize("key,value", [
    ("voice_profile_id", "owner-secret"), ("voice_mode", "production"),
    ("voice_language", "xx"), ("animation_mode", "realistic_lipsync"),
    ("expression_preset", "invented_emotion"), ("lip_sync_mode", "verified"),
])
def test_persona_unknown_voice_options_are_rejected(key, value):
    values = {"name": "Persona", key: value}
    assert base.evaluate(f"(() => {{try {{ui.domainPayload('personas','create',{json.dumps(values)});return false;}}catch(_){{return true;}}}})()")


def test_persona_description_and_card_do_not_read_task_payloads_or_claim_lipsync():
    value = persona()
    value.update(title="<script>name</script>", description="Displayed <purpose>", result_text="private-result", api_key="private-key", model="private-model", history=["private-chat"])
    card = base.evaluate(f"ui.personaPresentationCard({json.dumps(value)})")
    assert "&lt;script&gt;name&lt;/script&gt;" in card and "&lt;purpose&gt;" in card
    assert "<script>" not in card
    assert not any(secret in card for secret in ["private-result", "private-key", "private-model", "private-chat"])
    assert "Прочитать описание" in card and "Синхронизация губ" in card
    assert "Недоступна: фонемы" in card and "Статичный аватар" in card
    assert "Звук ещё не проверен" in card


@pytest.mark.parametrize("change", [
    {"status": "suspended"}, {"status": "archived"}, {"revision": None},
    {"revision": "7"}, {"id": "../foreign"}, {"presentation": {}},
])
def test_persona_speech_button_is_not_enabled_for_unresolved_snapshot(change):
    value = persona() | change
    assert base.evaluate(f"ui.personaCanSpeak({json.dumps(value)})") is False


def test_speech_request_uses_exact_revision_and_narrow_envelope():
    request = {"persona_id": PERSONA_ID, "expected_revision": 7, "text": "Description",
               "voice_mode": "existing_tts", "workspace_id": "foreign", "is_owner": True}
    value = base.evaluate(f"ui.personaSpeechEnvelope({json.dumps(request)},'explicit-click-key')")
    assert value == {"payload": {"text": "Description"}, "expected_revision": 7, "idempotency_key": "explicit-click-key"}
    assert base.evaluate(f"ui.personaSpeechEnvelope({{persona_id:{json.dumps(PERSONA_ID)},expected_revision:7,text:'a'.repeat(5000)}},'key').payload.text.length") == 1200


@pytest.mark.parametrize("state,expected", [
    ({"state": "speaking", "mode": "browser", "voice": "Local Irina"}, "Local Irina"),
    ({"state": "speaking", "mode": "server"}, "серверный звук"),
    ({"state": "text_fallback", "reason": "voice_access_not_confirmed"}, "ревизия"),
    ({"state": "text_fallback", "reason": "no_local_voice_for_language"}, "нет локального голоса"),
    ({"state": "text_fallback", "reason": "never-echo-private-error"}, "Звук сейчас недоступен"),
])
def test_audio_status_is_truthful_and_never_echoes_opaque_errors(state, expected):
    result = base.evaluate(f"ui.personaAudioStatus({json.dumps(state)})")
    assert expected in result and "never-echo-private-error" not in result


@pytest.mark.parametrize("change", [
    {"id": "../candidate"}, {"source_sha256": "not-a-proof"}, {"domain": "memory"},
    {"automation_enabled": True}, {"quality_claim": True}, {"actions": ["accept"]},
])
def test_process_candidate_mutation_is_narrow_and_fail_closed(change):
    value = candidate() | change
    assert base.evaluate(f"(() => {{try {{ui.processCandidatePayload({json.dumps(value)},'routines');return false;}}catch(_){{return true;}}}})()")


def test_process_candidate_keeps_pending_reviews_and_quality_separate():
    value = candidate() | {"api_key": "never-expose-key", "title": "<script>Stored pattern</script>"}
    result = base.evaluate(f"({{payload:ui.processCandidatePayload({json.dumps(value)},'routines'),html:ui.processCandidateCard({json.dumps(value)},'routines',true)}})")
    assert result["payload"] == {"source_sha256": SOURCE_SHA}
    card = result["html"]
    assert "Ещё ждут вашей проверки" in card and "Выборка результатов" in card
    assert "Низкая · медиана" in card and "не оценка профессионального качества" in card
    assert "<script>" not in card and "never-expose-key" not in card
    assert "data-aw-process-propose" in card and "data-aw-domain-action=\"accept\"" not in card


@pytest.mark.parametrize("override", [{"incomplete": True}, {"version": "future-schema"}, {"automation_enabled": True}])
def test_incomplete_process_scan_cannot_offer_action_or_silently_hide_exclusions(override):
    process = {"version": "process-intelligence-v1", "automation_enabled": False, "candidates": [candidate()], "excluded": {"provider_plan_only": 3}, "suppressed": [{"domain": "routines", "reason": "cooldown"}]} | override
    card = base.evaluate(f"ui.processIntelligencePanel({json.dumps({'enabled': True, 'process_intelligence': process})},'routines')")
    assert "data-aw-process-propose" not in card
    assert "не подтверждён" in card and "provider_plan_only" in card and "cooldown" in card
    assert "не ошибки задач" in card


def test_process_panels_only_show_their_domain_without_new_pages():
    candidates = [candidate(), candidate("calendar") | {"title": "Calendar-only candidate"}]
    data = {"enabled": True, "process_intelligence": {"version": "process-intelligence-v1", "automation_enabled": False, "candidates": candidates}}
    routine = base.evaluate(f"ui.processIntelligencePanel({json.dumps(data)},'routines')")
    calendar = base.evaluate(f"ui.processIntelligencePanel({json.dumps(data)},'calendar')")
    assert "Calendar-only candidate" not in routine and "Calendar-only candidate" in calendar
    assert "Предлагаемое время (местное)" in calendar
    assert base.evaluate(f"ui.processIntelligencePanel({json.dumps(data)},'models')") == ""


def test_readonly_process_candidate_does_not_claim_bad_evidence_or_offer_mutation():
    value = candidate() | {"actions": []}
    card = base.evaluate(f"ui.processCandidateCard({json.dumps(value)},'routines',true)")
    assert "только для чтения" in card
    assert "data-aw-process-propose" not in card and "Данные предложения не подтверждены" not in card


def test_persona_actual_form_preserves_avatar_and_presentation_preferences(monkeypatch):
    data = persona()
    setup = f"Object.assign(domains.personas.items[0],{json.dumps(data)});"
    result = run_ui(monkeypatch, """
      await click({awDomain:'personas'},'shell');
      await click({awDomainAction:'update',awEntity:ids.persona});
      const html=drawer.innerHTML;
      await submit(form({name:'Renamed',description:'Displayed description',style:'Concise',avatar_key:'marina',voice_profile_id:'marina',voice_mode:'browser',voice_speed:'1.2',voice_language:'ru-RU',animation_mode:'static',expression_preset:'neutral',lip_sync_mode:'off'}));
      return {html,posts:calls.filter(call=>call.method==='post')};
    """, setup)
    assert 'value="marina" selected' in result["html"]
    assert 'type="number" value="1.2" min="0.5" max="1.8" step="0.1"' in result["html"]
    assert 'value="static" selected' in result["html"] and 'value="off" selected' in result["html"]
    assert result["posts"][0]["body"]["expected_revision"] == 7
    assert result["posts"][0]["body"]["payload"]["avatar_key"] == "marina"
    assert result["posts"][0]["body"]["payload"]["voice_speed"] == 1.2


def test_persona_create_is_browser_default_and_does_not_start_audio(monkeypatch):
    result = run_ui(monkeypatch, """
      await click({awDomain:'personas'},'shell');await click({awDomainAction:'create',awEntity:'new'});
      return {html:drawer.innerHTML,posts:calls.filter(call=>call.method==='post')};
    """)
    assert 'value="browser" selected' in result["html"]
    assert 'value="ru-RU" selected' in result["html"]
    assert result["posts"] == []


def process_setup():
    data = {"version": "process-intelligence-v1", "automation_enabled": False, "candidates": [candidate()], "excluded": {"provider_plan_only": 3}, "suppressed": []}
    return f"""
      domains.routines.process_intelligence={json.dumps(data)};
      const oldMutation=http.aiControlCenterDomainAction;
      http.aiControlCenterDomainAction=async (domain,id,action,body)=>{{
        if(domain==='routines'&&action==='propose'){{
          calls.push({{method:'post',domain,id,action,body:JSON.parse(JSON.stringify(body))}});
          if(failPost)throw {{status:500,message:'private-secret'}};
          const item={{id:ids.task,title:'Saved suggestion',status:'proposed',revision:1,actions:['accept','dismiss']}};
          domains.routines.items=[item];domains.routines.process_intelligence.candidates=[];
          return {{item,replayed:false}};
        }}
        return oldMutation(domain,id,action,body);
      }};
    """


def test_process_propose_handlers_do_not_accept_enable_or_close_reviews(monkeypatch):
    result = run_ui(monkeypatch, f"""
      await click({{awDomain:'routines'}},'shell');const list=drawer.innerHTML;
      await click({{awProcessPropose:{json.dumps(CANDIDATE_ID)}}});const proposal=drawer.innerHTML;
      const before=calls.filter(call=>call.method==='post').length;
      await submit(form());
      return {{list,proposal,before,after:drawer.innerHTML,posts:calls.filter(call=>call.method==='post')}};
    """, process_setup())
    assert result["before"] == 0
    assert "Ещё ждут вашей проверки" in result["list"] and "Сохранить предложение" in result["proposal"]
    assert len(result["posts"]) == 1
    post = result["posts"][0]
    assert (post["domain"], post["id"], post["action"]) == ("routines", CANDIDATE_ID, "propose")
    assert post["body"]["payload"] == {"source_sha256": SOURCE_SHA}
    assert set(post["body"]) == {"payload", "idempotency_key"}
    assert 'data-aw-domain-action="accept"' in result["after"]
    assert all(post["action"] not in ["accept", "enable", "review_result"] for post in result["posts"])


def test_process_retry_reuses_snapshot_and_idempotency_key(monkeypatch):
    result = run_ui(monkeypatch, f"""
      await click({{awDomain:'routines'}},'shell');await click({{awProcessPropose:{json.dumps(CANDIDATE_ID)}}});
      failPost=true;const first=form();await submit(first);const error=first.error.textContent;
      failPost=false;await submit(form());
      return {{error,posts:calls.filter(call=>call.method==='post')}};
    """, process_setup())
    assert len(result["posts"]) == 2
    assert result["posts"][0]["body"] == result["posts"][1]["body"]
    assert "private-secret" not in result["error"]


def audio_setup():
    return f"""
      Object.assign(domains.personas.items[0],{json.dumps(persona())});
      const audioEvents=[], utterances=[], rootListeners={{}};let leaveHandler, speechFailure=null, delayedSpeech=null, mediaReadyState=2;
      const makeDrawer=window.UI.drawer;
      window.UI.drawer=(title,html)=>{{
        const result=makeDrawer(title,html), oldQuery=result.querySelector;
        result.audioStatus={{textContent:''}};result.audioDetails={{textContent:''}};
        result.startButton={{disabled:false}};result.stopButton={{disabled:true}};
        const classes=new Set();
        result.video={{readyState:mediaReadyState,handlers:{{}},addEventListener(type,fn){{this.handlers[type]=fn;}}}};
        result.face={{dataset:{{}},classList:{{contains:k=>classes.has(k),add:k=>classes.add(k),remove:k=>classes.delete(k)}},
          querySelector:()=>result.video}};
        result.visual={{querySelectorAll:()=>[result.face]}};
        result.querySelector=selector=>{{
          if(!html.includes('aw-persona-presentation'))return oldQuery(selector);
          return ({{'.aw-persona-presentation':{{}},'#aw-persona-audio-status':result.audioStatus,'#aw-persona-audio-details':result.audioDetails,
            '[data-aw-persona-speak]':result.startButton,'[data-aw-persona-stop]':result.stopButton,
            '[data-aw-persona-visual]':result.visual,'[data-aw-persona-visual] .agent-face':result.face}})[selector]||oldQuery(selector);
        }};return result;
      }};
      tabs.forEach(tab=>{{tab.focus=()=>{{}};tab.getAttribute=()=>tab.dataset.awTab==='overview'?'true':'false';}});
      window.UI.onLeave=fn=>{{leaveHandler=fn;}};
      window.UI.agentSpeakStop=()=>audioEvents.push('legacy-stopped');
      window.UI.agentFacePlay=(face)=>{{if(face)face.classList.add('playing');audioEvents.push('face-play');}};
      window.UI.agentFacePause=(face)=>{{if(face)face.classList.remove('playing');audioEvents.push('face-pause');}};
      window.addEventListener=(type,fn)=>{{rootListeners[type]=fn;}};
      window.removeEventListener=(type)=>{{delete rootListeners[type];}};
      window.setTimeout=setTimeout;window.clearTimeout=clearTimeout;
      window.PersonaAudio=require({json.dumps(str(AUDIO))});
      window.SpeechSynthesisUtterance=class {{constructor(text){{this.text=text;}}}};
      window.speechSynthesis={{getVoices:()=>[{{name:'Device Irina',lang:'ru-RU',localService:true}}],
        speak:utter=>{{utterances.push(utter);utter.onstart();}},cancel:()=>audioEvents.push('speech-cancel')}};
      http.aiControlCenterPersonaSpeak=async(id,body)=>{{
        calls.push({{method:'speech',id,body}});if(speechFailure)throw speechFailure;
        if(delayedSpeech)return delayedSpeech;
        return {{fallback:'browser',text:body.payload.text}};
      }};
    """


def test_persona_actual_audio_requires_click_then_uses_only_scoped_speech(monkeypatch):
    result = run_ui(monkeypatch, """
      await click({awDomain:'personas'},'shell');await click({awDomainItem:ids.persona});
      const before=calls.filter(call=>call.method==='speech').length;
      const faceWired=drawer.face.dataset.faceWired;
      await click({awPersonaSpeak:ids.persona});
      return {before,faceWired,posts:calls.filter(call=>call.method==='speech'),audioEvents,
        status:drawer.audioStatus.textContent,text:utterances[0]?.text,mode:utterances[0]?.voice.name,stopEnabled:!drawer.stopButton.disabled};
    """, audio_setup())
    assert result["before"] == 0 and result["faceWired"] == "1"
    assert len(result["posts"]) == 1
    assert result["posts"][0]["id"] == PERSONA_ID
    assert result["posts"][0]["body"]["expected_revision"] == 7
    assert set(result["posts"][0]["body"]) == {"payload", "expected_revision", "idempotency_key"}
    assert result["text"] == "Saved Persona. Displayed description"
    assert result["mode"] == "Device Irina" and "Device Irina" in result["status"]
    assert result["stopEnabled"] and "legacy-stopped" in result["audioEvents"]
    assert "face-play" not in result["audioEvents"]  # persisted static preference


@pytest.mark.parametrize("status", [400, 401, 403, 404, 409, 410])
def test_persona_route_denial_does_not_bypass_into_local_voice(monkeypatch, status):
    result = run_ui(monkeypatch, f"""
      await click({{awDomain:'personas'}},'shell');await click({{awDomainItem:ids.persona}});
      speechFailure={{status:{status},message:'never-show-secret'}};await click({{awPersonaSpeak:ids.persona}});
      return {{utterances:utterances.length,status:drawer.audioStatus.textContent,stop:drawer.stopButton.disabled}};
    """, audio_setup())
    assert result["utterances"] == 0 and result["stop"]
    assert "ревизия" in result["status"] and "never-show-secret" not in result["status"]


@pytest.mark.parametrize("close", [
    "listeners.keydown({key:'Escape',target:{closest:()=>null},preventDefault(){}});",
    "document.hidden=true;listeners.visibilitychange();",
    "rootListeners.pagehide();", "rootListeners.hashchange();", "rootListeners.popstate();",
    "await click({awDomain:'memory'});", "await click({awTab:'work'},'shell');", "leaveHandler();",
    "listeners.click({target:{closest:selector=>selector==='.drawer-back, [data-close-drawer]'?{}:null}});",
])
def test_persona_audio_stops_on_close_leave_hidden_and_navigation(monkeypatch, close):
    result = run_ui(monkeypatch, f"""
      await click({{awDomain:'personas'}},'shell');await click({{awDomainItem:ids.persona}});
      await click({{awPersonaSpeak:ids.persona}});{close}await settle();
      return {{utterances:utterances.length,audioEvents}};
    """, audio_setup())
    assert result["utterances"] == 1 and "speech-cancel" in result["audioEvents"]


def test_persona_late_audio_response_does_not_play_after_navigation(monkeypatch):
    result = run_ui(monkeypatch, """
      await click({awDomain:'personas'},'shell');await click({awDomainItem:ids.persona});
      let resolveSpeech;delayedSpeech=new Promise(resolve=>{resolveSpeech=resolve;});
      await click({awPersonaSpeak:ids.persona});await click({awDomain:'memory'});
      resolveSpeech({fallback:'browser'});await settle();
      return {utterances:utterances.length,html:drawer.innerHTML};
    """, audio_setup())
    assert result["utterances"] == 0 and "Память" in result["html"]


def test_explicit_stop_button_only_stops_audio_not_task_or_persona(monkeypatch):
    result = run_ui(monkeypatch, """
      await click({awDomain:'personas'},'shell');await click({awDomainItem:ids.persona});
      await click({awPersonaSpeak:ids.persona});
      const target={dataset:{},area:'drawer',closest:selector=>selector==='button, a'?target:selector==='.aw-inspector'?{}:null,hasAttribute:attr=>attr==='data-aw-persona-stop'};
      listeners.click({target});await settle();
      return {audioEvents,status:drawer.audioStatus.textContent,posts:calls.filter(call=>call.method==='post')};
    """, audio_setup())
    assert "speech-cancel" in result["audioEvents"] and "остановлено" in result["status"]
    assert result["posts"] == []


def test_finished_audio_is_a_playback_observation_not_model_evaluation(monkeypatch):
    result = run_ui(monkeypatch, """
      await click({awDomain:'personas'},'shell');await click({awDomainItem:ids.persona});
      await click({awPersonaSpeak:ids.persona});utterances[0].onend();await settle();
      return {status:drawer.audioStatus.textContent,startEnabled:!drawer.startButton.disabled,stopDisabled:drawer.stopButton.disabled,posts:calls.filter(call=>call.method==='post')};
    """, audio_setup())
    assert "Озвучивание завершено" in result["status"] and "не оценка качества модели" in result["status"]
    assert result["startEnabled"] and result["stopDisabled"] and result["posts"] == []


def test_late_face_media_cannot_animate_after_stopping_persona(monkeypatch):
    result = run_ui(monkeypatch, """
      domains.personas.items[0].presentation.animation_mode='auto';mediaReadyState=0;
      await click({awDomain:'personas'},'shell');await click({awDomainItem:ids.persona});
      await click({awPersonaSpeak:ids.persona});const oldVideo=drawer.video;
      await click({awDomain:'memory'});oldVideo.readyState=2;oldVideo.handlers.loadeddata();await settle();
      return {audioEvents,utterances:utterances.length};
    """, audio_setup())
    assert result["utterances"] == 1
    assert "speech-cancel" in result["audioEvents"] and "face-play" not in result["audioEvents"]


def test_ready_face_uses_existing_clip_only_during_opt_in_speech(monkeypatch):
    result = run_ui(monkeypatch, """
      domains.personas.items[0].presentation.animation_mode='auto';
      await click({awDomain:'personas'},'shell');await click({awDomainItem:ids.persona});
      const before=audioEvents.filter(event=>event==='face-play').length;
      await click({awPersonaSpeak:ids.persona});const during=audioEvents.filter(event=>event==='face-play').length;
      utterances[0].onend();return {before,during,playing:drawer.face.classList.contains('playing')};
    """, audio_setup())
    assert result == {"before": 0, "during": 1, "playing": False}
