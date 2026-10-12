export function renderCoachUI({E, icon, link, state, scope, chat, chatDraft, useAI, drawer,
  settingsOpen, pending, dictationMethod, language, speakReplies, canSpeak, browserSupported}) {
  const options = ['en-US', 'en-IN', 'en-GB', 'ta-IN'];
  const names = ['English (US)', 'English (India)', 'English (UK)', 'Tamil'];
  return `<section class="chat-layout simple-chat">
    <div class="chat-context"><span class="coach-mode">${useAI ? E(state.ai.provider || 'OpenAI') : 'Local assistant'}</span>
      <span>${E(scope.month)} · ${E(scope.currency)}</span>
      <button type="button" id="chat-settings-toggle" class="icon-button" title="Chat settings" aria-label="Chat settings" aria-expanded="${settingsOpen}">${icon('settings')}</button></div>
    <section class="chat-options" ${settingsOpen ? '' : 'hidden'} aria-label="Chat settings">
      <label class="check"><input id="coach-ai" type="checkbox" ${useAI ? 'checked' : ''} ${state.ai.configured ? '' : 'disabled'}>Enable connected ${E(state.ai.provider || 'OpenAI')}</label>
      <p class="field-hint">Connected chat shares your message, recent chat and up to 50 records with verified totals for this month and currency with ${E(state.ai.provider || 'OpenAI')}. API billing is separate. Local mode uses simple rules.</p>
      <div class="form-grid"><div><label for="dictation-method">Dictation</label><select id="dictation-method"><option value="openai" ${dictationMethod === 'openai' ? 'selected' : ''} ${state.transcription?.configured ? '' : 'disabled'}>OpenAI transcription</option><option value="browser" ${dictationMethod === 'browser' ? 'selected' : ''} ${browserSupported ? '' : 'disabled'}>Browser speech</option></select></div>
      <div><label for="voice-language">Speech language</label><select id="voice-language">${options.map((value, index) => `<option value="${value}" ${language === value ? 'selected' : ''}>${names[index]}</option>`).join('')}</select></div></div>
      <p class="field-hint">OpenAI turns a recording into a draft after Done. Browser speech transcribes as you talk, where supported. Neither sends the message for you.</p>
      <label class="check"><input id="speak-replies" type="checkbox" ${speakReplies ? 'checked' : ''} ${canSpeak ? '' : 'disabled'}>Read new replies aloud</label>
      <p class="field-hint">Read aloud uses your browser’s speech voices; its provider may process reply text.</p>
    </section>
    <div class="chat-scroll" id="chat-scroll">
      ${!chat.length ? `<div class="chat-welcome"><div class="empty-icon">${icon('coach')}</div>${drawer ? '<h3>How can I help?</h3>' : '<h1 tabindex="-1">How can I help?</h1>'}<p>Ask about your spending, plan a budget,<br>or describe a transaction.</p><div class="chat-suggestions">${['Monthly summary', 'Show me the budgets', 'Open compound growth'].map(text => `<button type="button" data-prompt="${text}" ${pending ? 'disabled' : ''}>${text}</button>`).join('')}</div></div>` : ''}
      <div class="chat-log" id="chat-log" aria-live="polite">${chat.map((message, index) => `<article class="message ${message.role}"><div class="message-content"><div class="bubble">${E(message.content)}${message.links?.length ? `<div class="actions">${message.links.map(item => link(item.label, item.href)).join('')}</div>` : ''}${message.review ? `<div class="actions"><button class="primary" data-chat-review="${index}">Review proposed change</button></div>` : ''}</div>${message.role === 'assistant' && canSpeak ? `<div class="message-actions"><button type="button" class="read-reply" data-read-reply="${index}" title="Read this reply aloud" aria-label="Read reply aloud">${icon('speaker')}</button></div>` : ''}</div></article>`).join('')}
      ${pending ? '<div class="chat-thinking" role="status"><span></span>Thinking…</div>' : ''}</div>
    </div>
    <div class="chat-composer-wrap"><form class="composer" id="chat-form">
      <label for="chat-text" class="sr-only">Your message</label><textarea id="chat-text" required maxlength="6000" rows="2" placeholder="Message Home Accounts…">${E(chatDraft)}</textarea>
      <div class="dictation-strip" id="dictation-strip" hidden><div><span class="recording-dot" aria-hidden="true"></span><span id="recording-label">Recording</span> <span id="recording-time"></span><meter id="mic-level" min="0" max="1" value="0" aria-label="Microphone input level"></meter></div><div class="actions"><button type="button" id="dictation-cancel">Cancel</button><button type="button" id="dictation-done">Done</button></div></div>
      <div class="composer-foot"><span class="keyboard-hint">Enter to send · Shift + Enter for a new line</span><div class="composer-tools">
        <button type="button" id="dictate" class="icon-button" title="Dictate a message" aria-label="Dictate a message">${icon('mic')}</button>
        <button type="button" id="voice-mode" class="voice-mode-button" title="Talk with the assistant" aria-label="Open voice mode">${icon('voice')}<span>Voice</span></button>
        <button class="primary icon-button" id="chat-send" title="Send message" aria-label="Send" ${pending ? 'disabled' : ''}>${icon('arrow')}</button></div></div>
      <div class="speech-feedback"><p id="voice-status" class="voice-status" role="status"></p><button type="button" id="stop-reading" hidden>Stop reading</button></div>
    </form><p class="chat-caption">Check the details. Changes are saved only after you confirm.</p></div>
  </section>`;
}
