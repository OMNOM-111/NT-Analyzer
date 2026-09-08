/* Persona audio is opt-in presentation, never task execution or acceptance.
 * Existing face clips are speech activity loops, not phoneme-synchronised lips.
 * The host supplies the same scoped TTS transport and face play/pause helpers.
 */
(function (root, factory) {
  'use strict';
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.PersonaAudio = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';
  const MAX_CHARS = 1200;
  const clamp = value => typeof value === 'number' && Number.isFinite(value) ? Math.max(.5, Math.min(1.8, value)) : 1;
  function plainText(value) {
    return String(value || '').replace(/```[\s\S]*?```/g, ' ').replace(/`([^`]+)`/g, '$1')
      .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1').replace(/https?:\/\/\S+/gi, ' ')
      .replace(/[*_~]/g, '').replace(/\s+/g, ' ').trim().slice(0, MAX_CHARS);
  }
  function options(persona) {
    const view = persona && persona.presentation || {};
    return {persona_id: String(persona && persona.id || ''), revision: persona && persona.revision,
      name: String(persona && (persona.title || persona.display_name) || ''),
      voice_profile_id: String(view.resolved_voice_profile_id || view.voice_profile_id || ''),
      voice_mode: view.voice_mode === 'existing_tts' ? 'existing_tts' : 'browser',
      voice_label: String(view.voice_label || 'Голос устройства'),
      voice_gender: view.voice_gender, language: view.voice_language === 'en-US' ? 'en-US' : 'ru-RU',
      speed: clamp(view.voice_speed), animation_mode: view.animation_mode === 'static' ? 'static' : 'auto',
      expression_preset: view.expression_preset === 'speaking' ? 'speaking' : 'neutral',
      lip_sync: 'unavailable'};
  }
  function localVoice(voices, settings) {
    const language = settings.language.toLowerCase();
    const candidates = Array.from(voices || []).filter(voice => voice.localService === true
      && String(voice.lang || '').toLowerCase().split('-')[0] === language.split('-')[0]);
    const gender = settings.voice_gender;
    const pattern = gender === 'female' ? /female|жен|zira|irina|natalia|helena|katya|samantha|eva|anna/i
      : gender === 'male' ? /\bmale\b|муж|david|paul|mark|yuri|dmitri|pavel|george|daniel/i : null;
    return (pattern && candidates.find(voice => pattern.test(`${voice.name} ${voice.voiceURI || ''}`)))
      || candidates.find(voice => String(voice.lang || '').toLowerCase() === language) || candidates[0] || null;
  }
  function create(configuration) {
    const config = configuration || {}, host = config.host || globalThis;
    const delay = (callback, ms) => host.setTimeout(callback, ms);
    const cancelDelay = timer => { if (timer != null) host.clearTimeout(timer); };
    let generation = 0, current = null;
    function notify(state, extra) {
      const view = {state, persona_id: current && current.settings.persona_id || null,
        lip_sync: 'unavailable', expression: state === 'speaking' ? 'speaking' : 'neutral',
        ...(extra || {})};
      if (typeof config.onState === 'function') config.onState(view);
      return view;
    }
    function reduceMotion() {
      return !!(typeof config.reducedMotion === 'function' && config.reducedMotion())
        || !!(host.matchMedia && host.matchMedia('(prefers-reduced-motion: reduce)').matches);
    }
    function pauseFace(playback) {
      if (playback && typeof config.pauseFace === 'function') config.pauseFace(playback.face);
    }
    function playFace(playback) {
      if (playback.settings.animation_mode !== 'static' && !reduceMotion() && typeof config.playFace === 'function') {
        config.playFace(playback.face, {loop: true});
      }
    }
    function clean(playback) {
      if (!playback) return;
      cancelDelay(playback.timer); playback.timer = null;
      if (playback.voicesChanged && host.speechSynthesis && host.speechSynthesis.removeEventListener) {
        host.speechSynthesis.removeEventListener('voiceschanged', playback.voicesChanged);
      }
      playback.voicesChanged = null;
      if (playback.audio) {
        playback.audio.onplaying = playback.audio.onended = playback.audio.onerror = null;
        try { playback.audio.pause(); playback.audio.removeAttribute('src'); playback.audio.load(); } catch (_) { /* inert cleanup */ }
        playback.audio = null;
      }
      if (playback.url) { host.URL.revokeObjectURL(playback.url); playback.url = null; }
      if (playback.utter) {
        playback.utter.onstart = playback.utter.onend = playback.utter.onerror = null;
        playback.utter = null;
        try { host.speechSynthesis.cancel(); } catch (_) { /* no active audio */ }
      }
      pauseFace(playback);
    }
    function stop() {
      generation += 1;
      const previous = current;
      if (previous) {
        clean(previous);
        const result = notify('stopped', {mode: previous.mode || 'text'});
        previous.resolve(result); current = null;
      }
    }
    function valid(playback) { return current === playback && generation === playback.generation; }
    function finish(playback, state, extra) {
      if (!valid(playback)) return;
      clean(playback);
      const result = notify(state, extra);
      playback.resolve(result); current = null;
    }
    function browser(playback, reason) {
      if (!valid(playback) || playback.browserStarted) return;
      playback.browserStarted = true;
      const speech = host.speechSynthesis;
      if (!speech || typeof host.SpeechSynthesisUtterance !== 'function') {
        finish(playback, 'text_fallback', {mode: 'text', reason: 'speech_unavailable'}); return;
      }
      const start = () => {
        try { startSpeech(); } catch (_) { finish(playback, 'text_fallback', {mode: 'text', reason: 'browser_speech_failed'}); }
      };
      const startSpeech = () => {
        if (!valid(playback) || playback.utter) return;
        const voice = localVoice(speech.getVoices(), playback.settings);
        if (!voice) return;
        cancelDelay(playback.timer); playback.timer = null;
        if (playback.voicesChanged && speech.removeEventListener) speech.removeEventListener('voiceschanged', playback.voicesChanged);
        playback.voicesChanged = null;
        const utter = new host.SpeechSynthesisUtterance(playback.text);
        utter.voice = voice; utter.lang = playback.settings.language; utter.rate = playback.settings.speed;
        playback.utter = utter; playback.mode = 'browser';
        utter.onstart = () => {
          if (!valid(playback)) return;
          playFace(playback);
          notify('speaking', {mode: 'browser', voice: voice.name, requested_voice: playback.settings.voice_label,
            reason, local_voice_only: true, animation: reduceMotion() || playback.settings.animation_mode === 'static' ? 'static' : 'speaking_loop'});
        };
        utter.onend = () => finish(playback, 'finished', {mode: 'browser', voice: voice.name, local_voice_only: true});
        utter.onerror = () => finish(playback, 'text_fallback', {mode: 'text', reason: 'browser_speech_failed'});
        try { speech.speak(utter); } catch (_) { finish(playback, 'text_fallback', {mode: 'text', reason: 'browser_speech_failed'}); }
      };
      try {
        start();
        if (valid(playback) && !playback.utter) {
          if (speech.addEventListener) {
            playback.voicesChanged = start;
            speech.addEventListener('voiceschanged', start);
          }
          playback.timer = delay(() => {
            start();
            if (valid(playback) && !playback.utter) finish(playback, 'text_fallback', {mode: 'text', reason: 'no_local_voice_for_language'});
          }, 400);
        }
      } catch (_) { finish(playback, 'text_fallback', {mode: 'text', reason: 'browser_speech_failed'}); }
    }
    async function serverAudio(playback, result) {
      if (!valid(playback)) return;
      if (result && (result.ok === false || result.error)) {
        finish(playback, 'text_fallback', {mode: 'text', reason: 'voice_access_not_confirmed'}); return;
      }
      if (result && result.fallback === 'browser') {
        playback.text = plainText(result.text || playback.text);
        browser(playback, result.voice_fallback_reason || result.reason || 'browser_requested'); return;
      }
      if (typeof host.Blob !== 'function' || !(result instanceof host.Blob) || !result.size
          || result.size > 10 * 1024 * 1024 || !/^audio\//i.test(result.type) || typeof host.Audio !== 'function') {
        browser(playback, 'server_audio_unavailable'); return;
      }
      const audio = new host.Audio();
      playback.audio = audio; playback.mode = 'server';
      playback.url = host.URL.createObjectURL(result);
      const fallback = () => {
        if (!valid(playback) || playback.browserStarted) return;
        clean(playback); browser(playback, 'server_audio_failed');
      };
      audio.onplaying = () => {
        if (!valid(playback)) return;
        playFace(playback);
        notify('speaking', {mode: 'server', animation: reduceMotion() || playback.settings.animation_mode === 'static' ? 'static' : 'speaking_loop'});
      };
      audio.onended = () => finish(playback, 'finished', {mode: 'server'});
      audio.onerror = fallback; audio.src = playback.url;
      try { await audio.play(); } catch (_) { fallback(); }
    }
    function play(request) {
      const value = request || {}, settings = options(value.persona);
      if (value.userInitiated !== true) return Promise.resolve({state: 'not_started', reason: 'explicit_user_action_required'});
      stop();
      if (typeof config.beforeStart === 'function') config.beforeStart();
      const text = plainText(value.text);
      if (!text || !settings.persona_id || !settings.voice_profile_id) {
        return Promise.resolve(notify('text_fallback', {mode: 'text', reason: !text ? 'empty_text' : 'voice_not_configured'}));
      }
      return new Promise(resolve => {
        const playback = {generation, settings, text, face: value.face || null, resolve};
        current = playback;
        notify('preparing', {mode: settings.voice_mode});
        if (typeof config.requestSpeech !== 'function') { browser(playback, 'no_server_transport'); return; }
        Promise.resolve().then(() => config.requestSpeech({persona_id: settings.persona_id,
          expected_revision: settings.revision, text, voice_mode: settings.voice_mode}))
          .then(result => serverAudio(playback, result)).catch(error => {
            const status = Number(error && (error.status || error.statusCode || error.status_code || error.response && error.response.status));
            if ([400, 401, 403, 404, 409, 410].includes(status)) {
              finish(playback, 'text_fallback', {mode: 'text', reason: 'voice_access_not_confirmed'});
            } else browser(playback, 'server_unavailable');
          });
      });
    }
    return Object.freeze({play, stop, dispose: stop, activePersona: () => current && current.settings.persona_id || null});
  }
  return Object.freeze({create, options, localVoice, plainText});
});
