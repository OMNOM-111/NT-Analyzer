"""JS lifecycle tests with fake device speech/audio. Not audible/browser acceptance."""
from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
HARNESS = r"""
const assert = require('node:assert/strict');
const PersonaAudio = require('./app/static/aurora/assets/persona-audio.js');
const persona = {id:'persona-one', revision:3, title:'My assistant',
  presentation:{resolved_voice_profile_id:'secretary', voice_mode:'browser', voice_label:'Secretary',
    voice_gender:'female', voice_speed:1.1, voice_language:'ru-RU', animation_mode:'auto'}};
const russian = {name:'Irina', voiceURI:'local-irina', lang:'ru-RU', localService:true};
function setup(options = {}) {
  const h = {voices:options.voices || [russian], utterances:[], states:[], faces:[], paused:[],
    cancelled:0, timers:new Map(), listeners:new Set(), audios:[], urls:[], revoked:[], requests:[], before:0};
  let sequence = 0;
  h.host = {
    setTimeout(fn) { const id = ++sequence; h.timers.set(id, fn); return id; },
    clearTimeout(id) { h.timers.delete(id); },
    matchMedia() { return {matches:!!options.reducedMotion}; },
    speechSynthesis:{getVoices() { if(h.voiceError) throw Error('device unavailable'); return h.voices; },
      speak(utter) { h.utterances.push(utter); }, cancel() { h.cancelled++; },
      addEventListener(_,fn) { h.listeners.add(fn); }, removeEventListener(_,fn) { h.listeners.delete(fn); }},
    SpeechSynthesisUtterance:class {constructor(text) {this.text = text;}},
    Blob,
    URL:{createObjectURL(value) { h.urls.push(value); return 'blob:fixture-' + h.urls.length; },
      revokeObjectURL(value) { h.revoked.push(value); }},
    Audio:class { constructor() { h.audios.push(this); } play() { return options.rejectAudio ? Promise.reject(Error('blocked')) : Promise.resolve(); }
      pause() { this.paused = true; } removeAttribute() {} load() {} }
  };
  if (options.noSpeech) delete h.host.speechSynthesis;
  const cfg = {host:h.host, onState:view => h.states.push(view), playFace:(face,opts) => h.faces.push([face,opts]),
    pauseFace:face => h.paused.push(face), beforeStart:() => h.before++};
  if ('response' in options) cfg.requestSpeech = req => { h.requests.push(req); return options.response; };
  if (options.requestSpeech) cfg.requestSpeech = options.requestSpeech;
  h.controller = PersonaAudio.create(cfg);
  h.play = (changes={}) => h.controller.play({persona,text:'A verified result.',face:'face-element',userInitiated:true,...changes});
  h.flushTimers = () => { const list = [...h.timers.values()]; h.timers.clear(); list.forEach(fn => fn()); };
  return h;
}
async function flush() { for(let i = 0; i < 8; i++) await Promise.resolve(); }
"""


CASES = {
    "explicit_user_action": r"""
        const h = setup({response:{fallback:'browser'}});
        assert.equal((await h.play({userInitiated:false})).state,'not_started');
        assert.equal(h.requests.length,0); assert.equal(h.utterances.length,0); assert.equal(h.before,0);
    """,
    "text_sanitized_and_bounded": r"""
        assert.equal(PersonaAudio.plainText('**Answer** [label](https://example.invalid) ```hidden``` https://example.invalid'), 'Answer label');
        assert.equal(PersonaAudio.plainText('x'.repeat(3000)).length,1200);
        const h = setup(); const done=h.play({text:'**Hello** ```secret snippet```'});
        assert.equal(h.utterances[0].text,'Hello'); h.utterances[0].onend(); await done;
    """,
    "no_random_voice_for_unconfigured_persona": r"""
        const h=setup(); const result=await h.play({persona:{id:'new',revision:1,presentation:{}}});
        assert.equal(result.state,'text_fallback'); assert.equal(h.utterances.length,0);
    """,
    "model_change_does_not_change_voice_identity": r"""
        assert.deepEqual(PersonaAudio.options({...persona,model:'provider-one'}),PersonaAudio.options({...persona,model:'provider-two'}));
        assert.equal(PersonaAudio.options(persona).lip_sync,'unavailable');
    """,
    "voice_selection_excludes_remote_or_unidentified": r"""
        const settings=PersonaAudio.options(persona);
        assert.equal(PersonaAudio.localVoice([{name:'Cloud Irina',lang:'ru-RU',localService:false}],settings),null);
        assert.equal(PersonaAudio.localVoice([{name:'Unknown Irina',lang:'ru-RU'}],settings),null);
        assert.equal(PersonaAudio.localVoice([{name:'English',lang:'en-US',localService:true}],settings),null);
        assert.equal(PersonaAudio.localVoice([{name:'Cloud Irina',lang:'ru-RU',localService:false},russian],settings),russian);
    """,
    "absent_speech_keeps_static_and_text": r"""
        const h=setup({noSpeech:true}); const result=await h.play();
        assert.equal(result.state,'text_fallback'); assert.equal(result.reason,'speech_unavailable'); assert.equal(h.faces.length,0);
    """,
    "empty_voice_catalog_times_out_to_text": r"""
        const h=setup({voices:[]}); const done=h.play(); assert.equal(h.listeners.size,1);
        h.flushTimers(); const result=await done;
        assert.equal(result.reason,'no_local_voice_for_language'); assert.equal(h.listeners.size,0);
        assert.equal(h.faces.length,0); assert.equal(h.utterances.length,0);
    """,
    "voiceschanged_timer_race_speaks_only_once": r"""
        const h=setup({voices:[]}); const done=h.play();
        const timer=[...h.timers.values()][0], changed=[...h.listeners][0];
        h.voices=[russian]; changed(); timer(); changed();
        assert.equal(h.utterances.length,1); assert.equal(h.listeners.size,0);
        h.utterances[0].onend(); assert.equal((await done).state,'finished');
    """,
    "late_device_exception_falls_back_without_stuck_promise": r"""
        const h=setup({voices:[]}); const done=h.play(); h.voiceError=true;
        h.flushTimers(); assert.equal((await done).reason,'browser_speech_failed');
        assert.equal(h.controller.activePersona(),null);
    """,
    "speaking_animation_only_after_actual_start": r"""
        const h=setup(); const done=h.play(); assert.equal(h.faces.length,0);
        const utter=h.utterances[0]; assert.equal(utter.voice,russian); assert.equal(utter.rate,1.1);
        utter.onstart(); assert.equal(h.faces.length,1);
        assert.equal(h.states.at(-1).animation,'speaking_loop'); assert.equal(h.states.at(-1).lip_sync,'unavailable');
        assert.equal(h.states.at(-1).voice,'Irina'); utter.onend();
        assert.equal((await done).state,'finished'); assert.equal(h.paused.at(-1),'face-element');
    """,
    "reduced_motion_is_static_during_speech": r"""
        const h=setup({reducedMotion:true}); const done=h.play(); h.utterances[0].onstart();
        assert.equal(h.faces.length,0); assert.equal(h.states.at(-1).animation,'static');
        h.utterances[0].onend(); await done;
    """,
    "configured_static_is_not_overridden": r"""
        const h=setup(); const done=h.play({persona:{...persona,presentation:{...persona.presentation,animation_mode:'static'}}});
        h.utterances[0].onstart(); assert.equal(h.faces.length,0); h.utterances[0].onend(); await done;
    """,
    "device_error_does_not_report_audio_success": r"""
        const h=setup(); const done=h.play(); h.utterances[0].onerror();
        assert.equal((await done).state,'text_fallback'); assert.equal(h.faces.length,0);
    """,
    "stop_cancels_own_playback_and_resolves": r"""
        const h=setup(); const done=h.play(); h.utterances[0].onstart(); h.controller.stop();
        assert.equal((await done).state,'stopped'); assert.equal(h.cancelled,1);
        assert.equal(h.utterances[0].onend,null); assert.equal(h.controller.activePersona(),null);
    """,
    "server_browser_response_uses_scoped_cleaned_text": r"""
        const h=setup({response:{fallback:'browser',text:'Server cleaned text',voice_fallback_reason:'own_tts_connection_required'}});
        const done=h.play(); await flush();
        assert.equal(h.requests[0].persona_id,persona.id); assert.equal(h.requests[0].expected_revision,3);
        assert.equal(h.utterances[0].text,'Server cleaned text'); h.utterances[0].onstart();
        assert.equal(h.states.at(-1).reason,'own_tts_connection_required'); h.utterances[0].onend(); await done;
    """,
    "invalid_audio_payload_is_not_claimed_as_audio": r"""
        const h=setup({response:new Blob(['fixture'],{type:'text/html'})}); const done=h.play(); await flush();
        assert.equal(h.audios.length,0); assert.equal(h.utterances.length,1); h.utterances[0].onend(); await done;
    """,
    "server_denial_is_not_bypassed_by_local_speech": r"""
        for (const status of [400,401,403,404,409,410]) {
          const h=setup({requestSpeech:() => Promise.reject({status})}); const result=await h.play();
          assert.equal(result.reason,'voice_access_not_confirmed'); assert.equal(h.utterances.length,0);
        }
    """,
    "explicit_server_error_never_looks_like_voice_success": r"""
        const h=setup({response:{ok:false,error:'persona_voice_inactive'}}); const result=await h.play();
        assert.equal(result.reason,'voice_access_not_confirmed'); assert.equal(h.utterances.length,0);
    """,
    "server_audio_lifecycle_and_object_url_cleanup": r"""
        // Deliberate transport fixture, not a playable audio file/evidence.
        const h=setup({response:new Blob(['fixture-audio-bytes'],{type:'audio/mpeg'})});
        const done=h.play(); await flush(); assert.equal(h.audios.length,1); assert.equal(h.faces.length,0);
        h.audios[0].onplaying(); assert.equal(h.faces.length,1); assert.equal(h.states.at(-1).mode,'server');
        h.audios[0].onended(); assert.equal((await done).state,'finished');
        assert.deepEqual(h.revoked,['blob:fixture-1']); assert.equal(h.audios[0].paused,true);
    """,
    "audio_play_rejection_falls_back_without_audio_claim": r"""
        const h=setup({response:new Blob(['fixture'],{type:'audio/mpeg'}),rejectAudio:true});
        const done=h.play(); await flush(); assert.equal(h.faces.length,0);
        assert.equal(h.utterances.length,1); assert.deepEqual(h.revoked,['blob:fixture-1']);
        h.utterances[0].onend(); assert.equal((await done).mode,'browser');
    """,
    "stale_transport_does_not_speak_after_persona_switch": r"""
        let deliver; let count=0;
        const h=setup({requestSpeech:() => ++count===1 ? new Promise(resolve => {deliver=resolve;}) : {fallback:'browser'}});
        const first=h.play(); await flush();
        const second=h.play({persona:{...persona,id:'persona-two',title:'Second'}}); await flush();
        assert.equal((await first).state,'stopped'); assert.equal(h.controller.activePersona(),'persona-two');
        deliver({fallback:'browser',text:'Old result must not speak'}); await flush(); assert.equal(h.utterances.length,1);
        h.utterances[0].onend(); await second;
    """,
    "dispose_removes_delayed_voice_listener": r"""
        const h=setup({voices:[]}); const done=h.play(); const delayed=[...h.listeners][0];
        h.controller.dispose(); assert.equal((await done).state,'stopped');
        h.voices=[russian]; delayed(); h.flushTimers(); assert.equal(h.utterances.length,0); assert.equal(h.listeners.size,0);
    """,
}


@pytest.mark.parametrize("case", CASES, ids=CASES)
def test_persona_audio_contract(case):
    script = HARNESS + "\n(async () => {\n" + CASES[case] + "\nprocess.stdout.write('PASS');\n})().catch(error => { console.error(error); process.exitCode=1; });"
    result = subprocess.run(["node", "-e", script], cwd=ROOT, capture_output=True, text=True,
                            encoding="utf-8", timeout=20)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "PASS", "The scenario promise did not reach a verified terminal state."
