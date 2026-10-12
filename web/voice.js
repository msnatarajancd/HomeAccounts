// Browser dictation and read-aloud. Browser speech services may process speech remotely.
export function createVoice({draft, status, change = () => {}}) {
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  const supported = Boolean(Recognition), canSpeak = Boolean(window.speechSynthesis && window.SpeechSynthesisUtterance);
  let recognition = null, listening = false, muted = false, spoken = null, lastMessage = '';
  const publish = text => {lastMessage = text; status(text); change();};
  function cancelSpeech() {spoken = null; window.speechSynthesis?.cancel();}
  function stop() {
    const previous = recognition; recognition = null; listening = false;
    try {previous?.abort();} catch {}
    cancelSpeech(); publish('Microphone off. Your draft is ready to edit.');
  }
  function start(consent, language = 'en-US') {
    if (recognition) return;
    if (!supported) return publish('Browser dictation is unavailable here. Choose OpenAI in chat settings or use your keyboard.');
    if (!consent) return publish('Allow browser speech before dictating.');
    cancelSpeech();
    let session;
    try {session = new Recognition();} catch {return publish('Browser dictation could not start. Choose OpenAI in chat settings or type.');}
    recognition = session; session.lang = language; session.continuous = true; session.interimResults = true;
    session.onstart = () => {if (recognition !== session) return; listening = true; publish('Listening… Speak, then select Done.');};
    session.onresult = event => {
      if (recognition !== session) return;
      let transcript = '';
      for (let i = 0; i < event.results.length; i++) transcript += event.results[i][0].transcript + ' ';
      draft(transcript.trim());
    };
    session.onerror = event => {
      if (recognition !== session) return;
      recognition = null; listening = false;
      const messages = {
        'not-allowed': 'Microphone permission was denied. Allow microphone access for this site in browser settings.',
        'service-not-allowed': 'This browser cannot use its speech service. Choose OpenAI dictation in chat settings.',
        'audio-capture': 'No usable microphone was found. Check your selected input device.',
        'no-speech': 'No speech was detected. Check your microphone, then try again.',
        'network': 'The browser speech service could not connect. Choose OpenAI dictation in chat settings.',
        'aborted': 'Dictation stopped. Your draft is still here.',
      };
      publish(messages[event.error] || 'Browser dictation failed. Choose OpenAI dictation in chat settings or type.');
    };
    session.onend = () => {if (recognition !== session) return; recognition = null; listening = false; publish('Dictation finished. Review your draft, then Send.');};
    publish('Waiting for microphone permission…');
    try {session.start();} catch {recognition = null; listening = false; publish('Browser dictation could not start. Try OpenAI dictation or type.');}
  }
  function finish() {
    if (!recognition) return;
    const session = recognition;
    if (typeof session.stop === 'function') {
      session.stop(); setTimeout(() => {if (recognition === session) stop();}, 1500);
    } else stop();
  }
  function speak(text, enabled, language = 'en-US') {
    if (!canSpeak || !enabled || muted) return false;
    stop();
    const utterance = new SpeechSynthesisUtterance(text); spoken = utterance; utterance.lang = language;
    const voices = window.speechSynthesis.getVoices();
    const match = voices.find(v => v.localService && v.lang === language) || voices.find(v => v.lang === language);
    if (match) utterance.voice = match;
    utterance.onend = () => {if (spoken !== utterance) return; spoken = null; publish('Finished reading aloud.');};
    utterance.onerror = () => {if (spoken !== utterance) return; spoken = null; publish('Read aloud is unavailable. Check your browser audio settings.');};
    publish('Reading aloud…');
    try {window.speechSynthesis.speak(utterance);} catch {utterance.onerror();}
    return true;
  }
  function mute() {muted = !muted; if (muted) cancelSpeech(); publish(muted ? 'Spoken replies muted.' : 'Spoken replies unmuted.'); return muted;}
  document.addEventListener('visibilitychange', () => {if (document.hidden) stop();});
  window.addEventListener('pagehide', stop);
  return {supported, canSpeak, start, stop, finish, speak, mute,
    get active() {return Boolean(recognition);}, get listening() {return listening;}, get speaking() {return Boolean(spoken);},
    get muted() {return muted;}, get message() {return lastMessage;}};
}
