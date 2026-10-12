// OpenAI Realtime audio uses WebRTC. Dictation is separately implemented in voice.js.
// This module never stores audio or puts a permanent API key in the browser.
export function createLiveVoice({status = () => {}, transcript = () => {}, requestSession, onRequest, change = () => {}}) {
  const supported = Boolean(window.isSecureContext && window.RTCPeerConnection && navigator.mediaDevices?.getUserMedia);
  let current = null;
  let disposed = false;
  let phase = 'idle';
  const emitStatus = text => {status(text); change();};

  function cleanup(session) {
    clearTimeout(session.timeout);
    session.abort.abort();
    // Invalidate first: closing transports can synchronously dispatch events.
    try { session.channel?.close(); } catch {}
    for (const track of session.stream?.getTracks() || []) { try { track.stop(); } catch {} }
    for (const receiver of session.peer?.getReceivers?.() || []) { try { receiver.track?.stop(); } catch {} }
    try { session.peer?.close(); } catch {}
    if (session.audio) {
      session.audio.pause();
      session.audio.srcObject = null;
      session.audio.remove();
    }
  }

  function stop(message = 'Live voice stopped. The microphone is off.') {
    const session = current;
    current = null; phase = 'idle';
    if (session) cleanup(session);
    if (session && typeof message === 'string') emitStatus(message);
  }

  function fail(session, message) {
    if (current !== session) return;
    stop(message);
  }

  async function localRequest(session, call) {
    if (current !== session || typeof call.call_id !== 'string' || !call.call_id || call.call_id.length > 200 || session.calls.has(call.call_id)) return;
    session.calls.add(call.call_id);
    let result = {answer: 'This request could not be handled. Please use typed Chat or the transaction form.', reviewNeedsConfirmation: false};
    let args;
    try { args = JSON.parse(call.arguments); } catch {}
    const valid = call.name === 'home_accounts_request' && args && typeof args === 'object' && !Array.isArray(args)
      && Object.keys(args).length === 1 && typeof args.text === 'string' && args.text.trim() && args.text.length <= 6000;
    if (valid && typeof onRequest === 'function') {
      try {
        phase = 'thinking'; emitStatus('Checking the selected account scope locally…');
        const local = await onRequest({text: args.text.trim(), context: {...session.context}}, {signal: session.abort.signal});
        if (current !== session) return;
        if (typeof local?.answer === 'string') {
          result = {answer: local.answer.slice(0, 12000), reviewNeedsConfirmation: local.reviewNeedsConfirmation === true,
            scope: {month: session.context.month || '', currency: session.context.currency || ''}};
        }
      } catch { /* Never forward raw API errors, records or review tokens. */ }
    }
    if (current !== session || session.channel?.readyState !== 'open') return;
    try {
      session.channel.send(JSON.stringify({type: 'conversation.item.create', item: {type: 'function_call_output', call_id: call.call_id, output: JSON.stringify(result)}}));
      session.channel.send(JSON.stringify({type: 'response.create'}));
      emitStatus(result.reviewNeedsConfirmation ? 'A proposal is ready. Review and confirm it in the app to save.' : 'Live voice connected. The local answer is ready.');
    } catch { fail(session, 'Live voice disconnected. The microphone is off.'); }
  }

  function onEvent(session, raw) {
    if (current !== session) return;
    let event;
    try { event = JSON.parse(raw); } catch { return; }
    if (!event || typeof event !== 'object') return;
    if (event.type === 'session.created') {
      session.ready = true; phase = 'listening';
      clearTimeout(session.timeout);
      emitStatus('Live voice connected. Ask about the selected month or how to use this page. Changes require review and confirmation.');
    } else if (event.type === 'input_audio_buffer.speech_started') {
      phase = 'listening'; emitStatus('Listening…');
    } else if (event.type === 'input_audio_buffer.speech_stopped' || event.type === 'response.created') {
      phase = 'thinking'; emitStatus('Thinking…');
    } else if (event.type === 'response.output_audio.delta' || event.type === 'output_audio_buffer.started') {
      phase = 'speaking'; emitStatus('Speaking… You can interrupt.');
    } else if (event.type === 'output_audio_buffer.stopped') {
      phase = 'listening'; emitStatus('Listening…');
    } else if (event.type === 'conversation.item.input_audio_transcription.completed' || event.type === 'response.output_audio_transcript.done') {
      const content = typeof event.transcript === 'string' ? event.transcript.trim().slice(0, 12000) : '';
      const role = event.type.startsWith('conversation.') ? 'user' : 'assistant';
      const id = event.item_id ? role + ':' + event.item_id + ':' + (event.content_index || 0) : event.event_id;
      if (content && (!id || !session.seen.has(id))) {
        if (id) session.seen.add(id);
        transcript({role, content});
      }
    } else if (event.type === 'conversation.item.input_audio_transcription.failed') {
      emitStatus('Live voice is connected, but this turn could not be transcribed. You can keep speaking or stop.');
    } else if (event.type === 'error' || (event.type === 'response.done' && event.response?.status === 'failed')) {
      // Provider errors are untrusted; don't reflect raw messages or credentials.
      fail(session, 'Live voice encountered a service error. The microphone is off. Start again or use typed chat.');
    } else if (event.type === 'response.done' && event.response?.status === 'completed') {
      // Wait for the full response so response.create cannot race an active response.
      phase = 'listening'; emitStatus('Listening…');
      const calls = (Array.isArray(event.response.output) ? event.response.output : []).filter(item => item?.type === 'function_call');
      // A single local request per response prevents overlapping review dialogs.
      if (calls.length > 1) { fail(session, 'Live voice requested several actions at once. Please handle one request at a time in typed Chat.'); return; }
      if (calls[0]) void localRequest(session, calls[0]);
    }
  }

  async function start({consent = false, context = {}} = {}) {
    if (disposed) return false;
    if (current) { emitStatus('Live voice is already connecting or active. Stop before starting again.'); return false; }
    if (!supported) { emitStatus('Live voice requires a browser with microphone and WebRTC support on localhost or HTTPS. Typed chat remains available.'); return false; }
    if (consent !== true) { emitStatus('Enable live voice consent first. Your microphone audio goes to OpenAI and API usage is billed.'); return false; }
    const selected = {page: typeof context?.page === 'string' ? context.page : ''};
    if (/^\d{4}-(0[1-9]|1[0-2])$/.test(context?.month || '') && /^[A-Z]{3}$/.test(context?.currency || '')) {
      selected.month = context.month; selected.currency = context.currency;
    }
    const session = {abort: new AbortController(), ready: false, seen: new Set(), calls: new Set(), context: selected, peer: null, channel: null, stream: null, audio: null, timeout: null};
    current = session; phase = 'connecting';
    session.timeout = setTimeout(() => fail(session, 'Microphone permission timed out. Allow microphone access in your browser, then start again.'), 45000);
    emitStatus('Requesting microphone access for OpenAI live voice. You can stop while waiting.');
    try {
      const stream = await navigator.mediaDevices.getUserMedia({audio: true});
      // Permission may resolve after Stop, navigation, consent withdrawal or restart.
      if (current !== session) { for (const track of stream.getTracks()) track.stop(); return false; }
      clearTimeout(session.timeout);
      session.stream = stream;
      for (const track of stream.getAudioTracks()) track.enabled = !session.muted;
      for (const track of stream.getAudioTracks()) track.addEventListener('ended', () => fail(session, 'The microphone became unavailable. Live voice stopped.'));
      session.peer = new RTCPeerConnection();
      session.audio = document.createElement('audio');
      session.audio.autoplay = true;
      session.audio.setAttribute('playsinline', '');
      session.peer.addEventListener('track', event => {
        if (current !== session) { event.track?.stop(); return; }
        session.audio.srcObject = event.streams[0] || new MediaStream([event.track]);
        session.audio.play().catch(() => {
          if (current === session) emitStatus('Live voice connected. Use Play voice replies to allow audio playback, or read the transcript.');
        });
      });
      session.peer.addEventListener('connectionstatechange', () => {
        if (['failed', 'disconnected', 'closed'].includes(session.peer.connectionState)) fail(session, 'Live voice disconnected. The microphone is off. Start again or type.');
      });
      for (const track of stream.getAudioTracks()) session.peer.addTrack(track, stream);
      session.channel = session.peer.createDataChannel('oai-events');
      session.channel.addEventListener('message', event => onEvent(session, event.data));
      session.channel.addEventListener('close', () => fail(session, 'Live voice disconnected. The microphone is off.'));
      session.channel.addEventListener('error', () => fail(session, 'Live voice could not connect. The microphone is off.'));
      session.timeout = setTimeout(() => fail(session, 'Live voice connection timed out. The microphone is off. Start again or type.'), 45000);
      emitStatus('Connecting to OpenAI live voice…');
      const offer = await session.peer.createOffer();
      if (current !== session) return false;
      await session.peer.setLocalDescription(offer);
      if (current !== session) return false;
      // Only the page and selected scope enter signalling; no records or chat history.
      const result = await requestSession({sdp: offer.sdp, live_consent: true, context: selected}, {signal: session.abort.signal});
      if (current !== session) return false;
      if (!result || typeof result.sdp !== 'string' || !result.sdp.startsWith('v=0')) throw new Error('Invalid voice connection response.');
      await session.peer.setRemoteDescription({type: 'answer', sdp: result.sdp});
      return current === session;
    } catch (error) {
      if (current !== session) return false;
      const denied = error?.name === 'NotAllowedError' || error?.name === 'SecurityError';
      const noMic = error?.name === 'NotFoundError' || error?.name === 'NotReadableError';
      const message = error?.userMessage || (denied ? 'Microphone permission was denied. Allow it in browser settings or use typed chat.'
        : noMic ? 'No usable microphone was found. Check the microphone or use typed chat.'
        : 'Live voice could not connect. Check OpenAI API access, billing and your connection, then start again. Typed chat remains available.');
      fail(session, message);
      return false;
    }
  }

  async function resumeAudio() {
    const session = current;
    if (!session?.audio) return false;
    try { await session.audio.play(); return current === session; }
    catch { if (current === session) emitStatus('Voice playback is blocked. Check browser audio permissions or read the transcript.'); return false; }
  }

  function setMuted(muted) {
    if (!current) return false;
    current.muted = Boolean(muted);
    for (const track of current.stream?.getAudioTracks() || []) track.enabled = !current.muted;
    emitStatus(current.muted ? 'Microphone muted. You can still hear replies.' : 'Microphone on. Listening…');
    return current.muted;
  }

  const onHidden = () => { if (document.hidden) stop(); };
  const onLeave = () => stop();
  document.addEventListener('visibilitychange', onHidden);
  window.addEventListener('pagehide', onLeave);
  window.addEventListener('popstate', onLeave);
  function dispose() {
    stop(); disposed = true;
    document.removeEventListener('visibilitychange', onHidden);
    window.removeEventListener('pagehide', onLeave);
    window.removeEventListener('popstate', onLeave);
  }
  return {supported, start, stop, resumeAudio, dispose, setMuted, get phase() {return phase;}, get muted() {return Boolean(current?.muted);}, get active() { return current !== null; }};
}
