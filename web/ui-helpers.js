const escape = value => String(value ?? '').replace(/[&<>"']/g, character => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[character]));

export function bindCurrencyPicker(root, currencies, selected, choose) {
  const input = root.querySelector('#scope-currency');
  const list = root.querySelector('#currency-options');
  if (!input || !list) return;
  let matches = [], active = -1;
  const close = () => { list.hidden = true; input.setAttribute('aria-expanded', 'false'); input.removeAttribute('aria-activedescendant'); };
  const select = currency => { close(); input.value = currency.code; choose(currency.code); };
  function paint() {
    const query = input.value.trim().toLowerCase();
    matches = currencies.filter(currency => `${currency.code} ${currency.label} ${currency.search_terms || ''}`.toLowerCase().includes(query)).slice(0, 40);
    active = -1;
    list.innerHTML = matches.length ? matches.map((currency, index) => `<button type="button" role="option" id="currency-option-${index}" aria-selected="false" data-currency-index="${index}"><strong>${escape(currency.code)}</strong><span>${escape(currency.label.replace(currency.code + ' — ', ''))}</span></button>`).join('') : '<p role="status">No matching currency. Try a country, name or code.</p>';
    list.hidden = false;
    input.setAttribute('aria-expanded', 'true');
    input.removeAttribute('aria-activedescendant');
  }
  input.addEventListener('focus', () => { input.select(); paint(); });
  input.addEventListener('input', paint);
  input.addEventListener('keydown', event => {
    if (event.key === 'Escape') { close(); input.value = selected || ''; return; }
    if (['ArrowDown', 'ArrowUp'].includes(event.key)) {
      event.preventDefault(); if (list.hidden) paint();
      if (!matches.length) return;
      active = (active + (event.key === 'ArrowDown' ? 1 : -1) + matches.length) % matches.length;
      list.querySelectorAll('[role=option]').forEach((option, index) => option.setAttribute('aria-selected', String(index === active)));
      const option = list.children[active];
      input.setAttribute('aria-activedescendant', option.id); option.scrollIntoView({block:'nearest'});
    }
    if (event.key === 'Enter') {
      event.preventDefault();
      const match = matches[active] || currencies.find(currency => currency.code.toLowerCase() === input.value.trim().toLowerCase()) || (matches.length === 1 ? matches[0] : null);
      if (match) select(match);
    }
  });
  list.addEventListener('mousedown', event => event.preventDefault());
  list.addEventListener('click', event => { const option = event.target.closest('[data-currency-index]'); if (option) select(matches[Number(option.dataset.currencyIndex)]); });
  input.addEventListener('blur', () => { close(); input.value = selected || ''; });
}

function distance(left, right) {
  let row = Array.from({length:right.length + 1}, (_, index) => index);
  for (let i = 0; i < left.length; i++) {
    const next = [i + 1];
    for (let j = 0; j < right.length; j++) next.push(Math.min(next[j]+1, row[j+1]+1, row[j]+(left[i] === right[j] ? 0 : 1)));
    row = next;
  }
  return row[right.length];
}

export function bindEntrySuggestions(form, records) {
  for (const input of form.querySelectorAll('input[data-suggest]')) {
    const values = [...new Set(records.map(row => row[input.name]).filter(Boolean))].slice(-500);
    const list = document.createElement('datalist'); list.id = input.id + '-history';
    list.innerHTML = values.map(value => `<option value="${escape(value)}"></option>`).join('');
    input.setAttribute('list', list.id); input.setAttribute('spellcheck', 'true'); input.after(list);
    const suggestions = document.createElement('div'); suggestions.className = 'spelling-suggestions'; suggestions.setAttribute('aria-live', 'polite'); list.after(suggestions);
    let timer;
    const offer = () => {
      const raw = input.value.trim(), text = raw.toLocaleLowerCase(); suggestions.replaceChildren();
      if (text.length < 3 || text.length > 120 || values.some(value => value.toLocaleLowerCase() === text)) return;
      const closest = values.map(value => ({value, score:distance(text, value.toLocaleLowerCase())})).filter(item => item.score > 0 && item.score <= (text.length > 8 ? 3 : 2) && item.score/text.length <= .4).sort((a,b) => a.score-b.score).slice(0,2);
      if (!closest.length) return;
      const hint = document.createElement('span'); hint.textContent = 'Did you mean '; suggestions.append(hint);
      for (const {value} of closest) {
        const button = document.createElement('button'); button.type = 'button'; button.textContent = value; button.setAttribute('aria-label', 'Use suggestion: ' + value);
        button.addEventListener('click', () => { input.value = value; suggestions.replaceChildren(); input.dispatchEvent(new Event('input', {bubbles:true})); input.focus(); }); suggestions.append(button);
      }
      const note = document.createElement('span'); note.textContent = '? Your entry stays as typed unless you choose a suggestion.'; suggestions.append(note);
    };
    input.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(offer, 250); });
    input.addEventListener('blur', offer);
  }
}

const guides = {
  overview: [ ['.scope', 'Choose the month and currency', 'Search for a currency by country, name or code. Choose any month and year. Set currency here once; forms refer to it as read-only. Existing records keep their original currency. Choose a month to update the report.'], ['.page-head .actions', 'Add or import your records', 'Add transaction opens a form here. Check its preview, then confirm to save. Use Import data for a file of transactions.'], ['.stats, .empty', 'Read your confirmed totals', 'Income, net expenses and remaining budget use confirmed records in this selection. Empty selections do not mean zero spending.'], ['[data-overview-charts]', 'Explore monthly or yearly charts', 'Choose Monthly for daily expenses, budget comparison or categories. Choose Yearly for all twelve months and the expenses versus recorded-surplus split. Exact chart data includes links to the underlying records.'], ['.reset-transactions', 'Start again when you need to', 'Clear all transactions includes every month and currency. It needs an explicit review and acknowledgement. Budgets and settings are kept, and Undo can restore the records.'] ],
  transactions: [ ['#filters', 'Find a record', 'Search particulars, merchant or record ID. Choose a category or transaction type, then Apply filters. Turn on All recorded months to search beyond the current month.'], ['.page-head .actions', 'Add a transaction', 'Enter a transaction in a dialog without leaving this page. Nothing is saved until you confirm the review.'], ['.table-wrap', 'Correct or export records', 'Edit and Remove each open a preview. Export filtered CSV downloads the records matching your filters. Newly saved transactions are highlighted.'] ],
  budgets: [ ['#new-budget, #new-budget-mobile', 'Set a monthly spending limit', 'Choose a month, amount and expense category. Budgets and transactions use the same category and subcategory list.'], ['.stats', 'Compare the plan with actual spending', 'Net expenses include refunds. Parent category limits include their subcategories and are not counted twice.'], ['.budget-row, .empty', 'Adjust a limit deliberately', 'Adjust opens a preview for your confirmation. Recording overspending never raises a budget automatically.'] ],
  entry: [ ['#entry-form', 'Record what happened', 'Enter the date, type and amount. Currency comes from the page header and is read-only here. Particulars can suggest text from confirmed history. Spelling suggestions change your text only when you choose them.'], ['[name=category]', 'Use matching categories', 'Choose the same expense category and subcategory used in your budget. A new category needs explicit acknowledgement in the review.'], ['#entry-form .actions, #sentence-tab', 'Review before saving', 'Use the form or describe one transaction. The preview shows the exact records and effect on your monthly totals. Confirm save makes the change.'] ],
  import: [ ['#import-file', 'Choose your transaction file', 'Choose CSV, TSV or XLSX. Uploading a file and reviewing field mappings does not save transactions.'], ['#import-body', 'Map, inspect, then confirm', 'Match source columns to fields, prepare the normalized records and fix reported issues. Continue to confirmation before saving. Balances and wish lists are not transaction history.'] ],
  coach: [ ['#chat-form', 'Ask or describe a transaction', 'Type a question or one transaction and Send. Local rules can answer confirmed totals or prepare a change for review.'], ['#chat-settings-toggle', 'Choose whether to connect AI', 'Connected AI is optional. Its disclosure explains exactly what is shared and that API usage can be charged.'], ['#dictate', 'Dictate, listen or talk', 'The microphone creates an editable draft. Select Done, check the words, then Send. Use the speaker under a reply to read it aloud. Voice opens a separate conversation with OpenAI; start it only after reviewing the disclosure.'] ],
  planning: [ ['.tabs', 'Choose a calculator', 'Select a planning tool, then enter your own assumptions. These are scenarios, not financial transactions.'], ['#planning-form', 'Calculate and explore', 'Calculate scenario shows results from your inputs. Changing assumptions never changes your recorded transactions or budgets.'] ],
  settings: [ ['.segmented', 'Choose a visual mode', 'Light, Dark and Bright change the palette. Your selection stays on this computer.'], ['#home-form', 'Choose your starting page', 'Choose Overview or Coach and save your preference. All other pages remain in the navigation.'], ['#undo-review', 'Review the last change', 'Undo previews the previous financial revision before restoring it. Field and visual settings are separate.'] ],
  setup: [ ['.tabs', 'Choose how to define your fields', 'Upload a sample or describe the fields you need. Confirming fields prepares the workspace; it does not import transactions.'], ['#schema-proposal', 'Review your fields and categories', 'Choose a default currency and review the suggested fields. You can edit shared categories here; existing records are preserved.'] ],
  learn: [ ['.learning', 'Learn the concepts', 'Open a topic to understand the report terms, planning assumptions or external learning resources. Use Help walkthrough on any page for its controls.'] ],
};

export function createWalkthrough({page, navigate, speak, stopSpeech}) {
  let index = 0, steps = [], target, narration = false, active = false;
  const panel = document.createElement('dialog'); panel.id = 'walkthrough'; panel.setAttribute('aria-labelledby', 'walkthrough-title'); document.body.append(panel);
  const unhighlight = () => { target?.classList.remove('tour-target'); target = null; };
  function stop() { active = false; stopSpeech(); unhighlight(); panel.close(); document.querySelector('#help-walkthrough')?.focus(); }
  async function show() {
    unhighlight(); stopSpeech(); const step = steps[index];
    if (step.page !== page()) await navigate('/' + step.page);
    if (!active) return;
    target = document.querySelector(step.selector);
    if (target && target.getClientRects().length) { target.classList.add('tour-target'); target.scrollIntoView({block:'center',behavior:'instant'}); }
    panel.innerHTML = `<div class="dialog-head"><div><p class="eyebrow">Guided walkthrough · ${index+1} of ${steps.length}</p><h2 id="walkthrough-title">${escape(step.title)}</h2></div><button type="button" data-tour="close" aria-label="End walkthrough">×</button></div><div class="dialog-body"><p>${escape(step.text)}</p></div><div class="dialog-actions"><button data-tour="back" ${index === 0 ? 'disabled' : ''}>Back</button><button data-tour="next" class="primary">${index === steps.length - 1 ? 'Finish' : 'Next'}</button></div>`;
    if (!panel.open) panel.show(); panel.querySelector('[data-tour=next]').focus();
    if (narration) speak(step.title + '. ' + step.text);
  }
  panel.addEventListener('click', async event => { const action = event.target.closest('[data-tour]')?.dataset.tour; if (action === 'close' || action === 'next' && index === steps.length-1) stop(); else if (action === 'next' || action === 'back') { index += action === 'next' ? 1 : -1; await show(); } });
  panel.addEventListener('cancel', event => { event.preventDefault(); stop(); });
  return {stop, get active(){return active;}, start(full = false, spoken = false) {
    narration = spoken; index = 0; active = true;
    const pages = full ? ['overview','transactions','budgets','import','coach','planning','settings'] : [page()];
    steps = pages.flatMap(name => (guides[name] || guides.overview).map(([selector,title,text]) => ({page:name,selector,title,text})));
    return show();
  }};
}
