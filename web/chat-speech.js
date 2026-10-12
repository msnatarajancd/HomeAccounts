import {createDictation} from './dictation.js';
import {createVoice} from './voice.js';
import {createLiveVoice} from './live-voice.js';

// The three speech actions have independent consent and lifecycles.
export function createChatSpeech({getState, getScope, getPage, getDraft, setDraft, icon, escape: E, request, onRequest, onTranscript, changed}) {
  const $ = s => document.querySelector(s);
  let method = null, language = 'en-US', baseDraft = '', feedback = '', readConsent = false;
  let autoRead = false, reading = null, liveStatus = '', transcripts = [], consent = new Set();
  const updateDraft = text => {
    const next = [baseDraft.trimEnd(), text].filter(Boolean).join(' ');
    setDraft(next); // Preserve the full transcript; do not silently truncate a long recording.
    if (next.length > 6000) feedback = 'Your draft is over 6,000 characters. Shorten it before sending.';
    update();
  };
  const voice = createVoice({draft: updateDraft, status: text => {feedback = text;}, change: update});
  const recording = createDictation({draft: updateDraft, change: snapshot => {feedback = snapshot.message; update();},
    transcribe: (body, options) => request('/api/voice/transcribe', {...body, transcription_consent: true, provider_endpoint: getState().transcription?.endpoint}, options)});
  const live = createLiveVoice({status: text => {liveStatus = text;}, change: updateLive,
    transcript: message => {transcripts.push(message); onTranscript(message); updateLive();},
    requestSession: (body, options) => request('/api/voice/session', {...body, provider_endpoint: getState().live_voice?.endpoint}, options),
    onRequest: async (body, options) => {
      if (!live.active || options.signal.aborted) throw new Error('Voice stopped.');
      return onRequest(body, options);
    }});
  function selectedMethod() {return method || (getState().transcription?.configured && recording.supported ? 'openai' : 'browser');}
  function update() {
    const active = recording.active || voice.active, snapshot = recording.state;
    if ($('#voice-status')) $('#voice-status').textContent = getDraft().length > 6000 ? 'Your draft is over 6,000 characters. Shorten it before sending.' : feedback;
    if ($('#dictation-strip')) $('#dictation-strip').hidden = !active;
    if ($('#recording-label')) $('#recording-label').textContent = recording.active ? {permission:'Waiting for microphone', recording:'Recording', transcribing:'Transcribing…'}[snapshot.phase] || '' : voice.listening ? 'Listening…' : 'Waiting for microphone';
    if ($('#recording-time')) $('#recording-time').textContent = recording.active && snapshot.phase === 'recording' ? `${Math.floor(snapshot.elapsed / 60)}:${String(snapshot.elapsed % 60).padStart(2, '0')}` : '';
    if ($('#mic-level')) {$('#mic-level').hidden = !recording.active || snapshot.phase !== 'recording'; $('#mic-level').value = snapshot.level;}
    if ($('#dictation-done')) $('#dictation-done').disabled = recording.active ? snapshot.phase !== 'recording' : !voice.listening;
    if ($('#chat-text')) $('#chat-text').readOnly = active;
    if ($('#dictate')) {$('#dictate').disabled = active; $('#dictate').setAttribute('aria-pressed', String(active));}
    if ($('#stop-reading')) $('#stop-reading').hidden = !voice.speaking;
    document.querySelectorAll('[data-read-reply]').forEach(button => {
      const isReading = voice.speaking && Number(button.dataset.readReply) === reading;
      button.setAttribute('aria-label', isReading ? 'Stop reading reply' : 'Read reply aloud');
      button.innerHTML = icon(isReading ? 'stop' : 'speaker');
    });
    for (const id of ['dictation-method', 'voice-language']) if ($('#' + id)) $('#' + id).disabled = active;
    changed();
  }
  function confirmSpeech(title, description, label, run) {
    const dialog = $('#speech-dialog');
    dialog.innerHTML = `<div class="dialog-head"><h2 id="speech-title">${title}</h2><button type="button" id="speech-close" aria-label="Close speech options">${icon('close')}</button></div><div class="dialog-body"><p>${description}</p><div class="actions speech-confirm"><button type="button" id="speech-cancel">Cancel</button><button type="button" class="primary" id="speech-allow">${label}</button></div></div>`;
    $('#speech-close').onclick = $('#speech-cancel').onclick = () => dialog.close();
    $('#speech-allow').onclick = () => {dialog.close(); run();};
    dialog.showModal();
  }
  function startDictation() {
    if (recording.active || voice.active) return;
    live.stop(); voice.stop(); baseDraft = getDraft();
    const engine = selectedMethod();
    const start = () => {consent.add(engine); if (engine === 'openai') void recording.start({consent:true, language:language.split('-')[0]}); else voice.start(true, language);};
    if (consent.has(engine)) return start();
    confirmSpeech('Dictate a message', engine === 'openai'
      ? 'Speak for up to two minutes, then select Done. Your recording is sent to OpenAI to create an editable draft. API credits are required. Nothing is sent as a chat message until you select Send.'
      : 'Your browser’s speech service will turn your voice into an editable draft and may process audio remotely. Allow microphone access when asked. Select Done, review the words, then Send. If this browser cannot transcribe, choose OpenAI in chat settings.', 'Start dictation', start);
  }
  function cancelDictation() {
    const active = recording.active || voice.active;
    recording.cancel(); voice.stop();
    if (active) setDraft(baseDraft);
    feedback = 'Dictation cancelled. Your original draft is unchanged.'; update();
  }
  function read(text, index) {
    if (voice.speaking && reading === index) {voice.stop(); return;}
    const start = () => {readConsent = true; if (recording.active || voice.active) cancelDictation(); live.stop(); reading = index; voice.speak(text, true, language);};
    if (readConsent) start();
    else confirmSpeech('Read reply aloud', 'Read aloud uses your browser’s speech voices. Its speech provider may process the reply text. You can stop playback at any time.', 'Read aloud', start);
  }
  function updateLive() {
    if (!$('#voice-dialog').open) return;
    const active = live.active;
    $('#live-status').textContent = liveStatus || getState().live_voice?.error || 'Ready when you are.';
    $('#voice-orb').dataset.phase = live.muted ? 'muted' : live.phase;
    $('#voice-phase').textContent = live.muted ? 'Microphone muted' : {idle:'Let’s talk', connecting:'Connecting…', listening:'Listening', thinking:'Thinking', speaking:'Speaking'}[live.phase];
    $('#live-start').hidden = active; $('#voice-intro').hidden = active;
    $('#live-tools').hidden = !active;
    $('#live-mute').setAttribute('aria-pressed', String(live.muted));
    $('#live-mute').textContent = live.muted ? 'Unmute microphone' : 'Mute microphone';
    $('#live-play').hidden = !active || !/playback|Play voice/i.test(liveStatus);
    $('#live-transcript').innerHTML = transcripts.map(item => `<p><strong>${item.role === 'user' ? 'You' : 'Assistant'}:</strong> ${E(item.content)}</p>`).join('');
    $('#live-transcript').scrollTop = $('#live-transcript').scrollHeight;
    $('#live-transcript-details').hidden = !transcripts.length;
  }
  function openLive() {
    if (recording.active || voice.active) cancelDictation(); voice.stop();
    const dialog = $('#voice-dialog'), enabled = live.supported && getState().live_voice?.configured;
    liveStatus = enabled ? '' : getState().live_voice?.error || 'Voice conversation needs an OpenAI API key and a browser with microphone support.';
    transcripts = [];
    dialog.innerHTML = `<div class="dialog-head"><h2 id="voice-title">Voice conversation</h2><button type="button" id="voice-close" aria-label="Close voice mode">${icon('close')}</button></div><div class="voice-body"><div id="voice-orb" class="voice-orb" aria-hidden="true">${icon('voice')}</div><h3 id="voice-phase">Let’s talk</h3><p id="live-status" role="status"></p><div id="voice-intro"><p>Talk naturally and hear replies. OpenAI receives your audio and answers from the selected month and currency. API credits are required.</p><p class="field-hint">${E(getScope().month)} · ${E(getScope().currency)}. Any changes need your on-screen confirmation.</p></div><button id="live-start" class="primary" ${enabled ? '' : 'disabled'}>Start voice conversation</button><div id="live-tools" class="actions" hidden><button id="live-mute" aria-pressed="false">Mute microphone</button><button id="live-stop" class="danger">End conversation</button></div><button id="live-play" hidden>Play voice replies</button><details id="live-transcript-details" hidden><summary>Transcript</summary><div id="live-transcript" class="live-transcript"></div></details></div>`;
    $('#voice-close').onclick = () => dialog.close();
    dialog.onclose = () => {live.stop(); changed();};
    $('#live-start').onclick = () => {liveStatus = ''; void live.start({consent:true, context:{page:getPage(), ...getScope()}});};
    $('#live-mute').onclick = () => live.setMuted(!live.muted);
    $('#live-stop').onclick = () => {live.stop(); dialog.close();};
    $('#live-play').onclick = () => live.resumeAudio();
    dialog.showModal(); updateLive();
  }
  function stop() {
    if (recording.active) recording.cancel('Microphone off. Recording cancelled.');
    voice.stop(); live.stop(); $('#voice-dialog').close(); $('#speech-dialog').close();
  }
  function bind() {
    $('#dictate')?.addEventListener('click', startDictation);
    $('#dictation-cancel')?.addEventListener('click', cancelDictation);
    $('#dictation-done')?.addEventListener('click', () => recording.active ? recording.finish() : voice.finish());
    $('#stop-reading')?.addEventListener('click', () => voice.stop());
    $('#voice-mode')?.addEventListener('click', openLive);
    $('#dictation-method')?.addEventListener('change', event => {method = event.target.value; feedback = ''; update();});
    $('#voice-language')?.addEventListener('change', event => {language = event.target.value;});
    $('#speak-replies')?.addEventListener('change', event => {autoRead = event.target.checked; readConsent ||= autoRead; if (!autoRead) voice.stop();});
    update();
  }
  return {voice, live, bind, read, stop, update, get active() {return recording.active || voice.active;},
    readNew: (text, index) => {if (autoRead && readConsent && !recording.active && !voice.active) read(text, index);},
    get settings() {return {dictationMethod:selectedMethod(), language, speakReplies:autoRead, canSpeak:voice.canSpeak, browserSupported:voice.supported};}};
}
