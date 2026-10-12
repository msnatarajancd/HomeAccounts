// Record only after explicit consent. Audio stays in memory and is discarded on cancel.
export function createDictation({transcribe, draft, change = () => {}}) {
  const supported = Boolean(window.isSecureContext && window.MediaRecorder && navigator.mediaDevices?.getUserMedia);
  let current = null, phase = 'idle', message = '', elapsed = 0, level = 0;
  const snapshot = () => ({phase, message, elapsed, level, active: Boolean(current)});
  function publish(next, text) {phase = next; message = text; change(snapshot());}
  function release(session) {
    clearInterval(session.timer); clearTimeout(session.timeout); cancelAnimationFrame(session.frame);
    const stream = session.stream, audioContext = session.audioContext;
    session.stream = null; session.audioContext = null;
    for (const track of stream?.getTracks() || []) track.stop();
    try {audioContext?.close()?.catch(() => {});} catch {}
  }
  function cancel(text = 'Recording cancelled. Your original draft is unchanged.') {
    const session = current; current = null;
    if (session) {
      session.abort.abort();
      try {if (session.recorder?.state !== 'inactive') session.recorder?.stop();} catch {}
      release(session); session.chunks = [];
    }
    level = 0; publish('idle', text);
  }
  function fail(session, text) {if (current !== session) return; cancel(text); publish('error', text);}
  async function complete(session) {
    if (current !== session) return;
    release(session); level = 0;
    const blob = new Blob(session.chunks, {type: session.recorder.mimeType || session.mime}); session.chunks = [];
    if (!blob.size) return fail(session, 'No audio was captured. Check your microphone, then try again.');
    if (blob.size > 8 * 1024 * 1024) return fail(session, 'That recording is too large. Try a shorter message.');
    publish('transcribing', 'Transcribing… You can cancel at any time.');
    try {
      const buffer = new Uint8Array(await blob.arrayBuffer());
      if (current !== session) return;
      let binary = '';
      for (let i = 0; i < buffer.length; i += 32768) binary += String.fromCharCode(...buffer.subarray(i, i + 32768));
      const result = await transcribe({audio: btoa(binary), mime: blob.type, language: session.language}, {signal: session.abort.signal});
      if (current !== session) return;
      current = null;
      if (typeof result.text !== 'string' || !result.text.trim()) return publish('error', 'No words were detected. Try speaking closer to your microphone.');
      draft(result.text.trim()); publish('idle', 'Draft ready. Review it, then Send.');
    } catch (error) {
      if (current !== session) return;
      fail(session, error.userMessage || 'Transcription could not connect. Check your connection or try browser dictation in chat settings.');
    }
  }
  function finish() {
    const session = current;
    if (!session || phase !== 'recording') return;
    publish('transcribing', 'Finishing your recording…');
    try {session.recorder.stop();} catch {fail(session, 'Could not finish the recording. Try again.');}
  }
  async function start({consent = false, language = 'en'} = {}) {
    if (current) return false;
    if (!supported) {publish('error', 'Audio recording is unavailable in this browser. Choose browser dictation in chat settings or type.'); return false;}
    if (!consent) {publish('error', 'Allow audio transcription before recording.'); return false;}
    const session = {abort: new AbortController(), chunks: [], language, stream: null, recorder: null, timer: null, timeout: null, frame: null, bytes: 0};
    current = session; elapsed = 0; level = 0; publish('permission', 'Allow microphone access in your browser to begin.');
    session.timeout = setTimeout(() => fail(session, 'Microphone permission timed out. Try again and allow this site to use your microphone.'), 30000);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({audio: {echoCancellation: true, noiseSuppression: true}});
      if (current !== session) {stream.getTracks().forEach(track => track.stop()); return false;}
      clearTimeout(session.timeout); session.stream = stream;
      session.mime = ['audio/webm;codecs=opus', 'audio/mp4', 'audio/ogg;codecs=opus', 'audio/webm'].find(type => MediaRecorder.isTypeSupported(type));
      if (!session.mime) throw new Error('Unsupported recording format');
      session.recorder = new MediaRecorder(stream, {mimeType: session.mime});
      session.recorder.ondataavailable = event => {
        if (current !== session || !event.data.size) return;
        session.bytes += event.data.size;
        if (session.bytes > 8 * 1024 * 1024) return fail(session, 'That recording is too large. Try a shorter message.');
        session.chunks.push(event.data);
      };
      session.recorder.onstop = () => void complete(session);
      session.recorder.onerror = () => fail(session, 'Microphone recording failed. Check your input device and try again.');
      stream.getAudioTracks().forEach(track => track.addEventListener('ended', () => {
        if (current === session && phase === 'recording') fail(session, 'Your microphone disconnected. Reconnect it and try again.');
      }));
      session.recorder.start(1000); publish('recording', 'Recording… Speak, then select Done.');
      const started = Date.now();
      session.timer = setInterval(() => {
        if (current !== session || phase !== 'recording') return;
        elapsed = Math.floor((Date.now() - started) / 1000); change(snapshot());
        if (elapsed >= 120) finish();
      }, 250);
      try {
        const AudioContext = window.AudioContext || window.webkitAudioContext;
        session.audioContext = new AudioContext();
        const source = session.audioContext.createMediaStreamSource(stream), analyser = session.audioContext.createAnalyser();
        analyser.fftSize = 256; source.connect(analyser);
        const samples = new Uint8Array(analyser.frequencyBinCount);
        const measure = () => {
          if (current !== session || phase !== 'recording') return;
          analyser.getByteTimeDomainData(samples);
          level = Math.min(1, Math.sqrt(samples.reduce((sum, value) => sum + ((value - 128) / 128) ** 2, 0) / samples.length) * 5);
          change(snapshot()); session.frame = requestAnimationFrame(measure);
        };
        measure();
      } catch { /* Recording works even where an audio meter is unavailable. */ }
      return true;
    } catch (error) {
      if (current !== session) return false;
      fail(session, ['NotAllowedError', 'SecurityError'].includes(error.name)
        ? 'Microphone permission was denied. Allow microphone access for this site in browser settings.'
        : ['NotFoundError', 'NotReadableError'].includes(error.name)
          ? 'No usable microphone was found. Check that it is connected and not being used by another app.'
          : 'Audio recording could not start. Try browser dictation in chat settings or type.');
      return false;
    }
  }
  document.addEventListener('visibilitychange', () => {if (document.hidden) cancel('Microphone off. Recording cancelled when the page was hidden.');});
  window.addEventListener('pagehide', () => cancel());
  return {supported, start, finish, cancel, get active() {return Boolean(current);}, get state() {return snapshot();}};
}
