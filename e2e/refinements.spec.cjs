const {test, expect} = require('@playwright/test');

async function state(request) {
  return (await request.get('/api/state')).json();
}

test.beforeEach(async ({page, request}) => {
  const initial = await state(request);
  const reset = await request.post('/api/test/reset', {
    headers: {'X-HomeAccounts-Token': initial.csrf}, data: {seed: true},
  });
  expect(reset.ok()).toBeTruthy();
  page.on('pageerror', error => { throw error; });
  await page.route('**/*', route => {
    const url = new URL(route.request().url());
    return url.hostname === '127.0.0.1' || url.protocol === 'data:' ? route.continue() : route.abort();
  });
});

async function mockSpeech(page) {
  await page.addInitScript(() => {
    window.__speech = {instances: [], cancels: 0};
    class Recognition {
      constructor() { window.__speech.instances.push(this); }
      start() { this.starts = (this.starts || 0) + 1; }
      abort() { this.aborts = (this.aborts || 0) + 1; }
    }
    window.SpeechRecognition = Recognition;
    Object.defineProperty(window, 'speechSynthesis', {value: {
      cancel() { window.__speech.cancels++; }, getVoices() { return []; }, speak() {},
    }});
  });
  await page.goto('/coach');
  await page.getByRole('button', {name: 'Chat settings', exact: true}).click();
  await page.getByLabel('Dictation', {exact: true}).selectOption('browser');
}

async function startBrowserDictation(page) {
  await page.getByRole('button', {name: 'Dictate a message', exact: true}).click();
  const allow = page.getByRole('button', {name: 'Start dictation', exact: true});
  if (await allow.isVisible()) await allow.click();
}

test('speech permission errors survive the subsequent end event', async ({page}) => {
  await mockSpeech(page);
  await startBrowserDictation(page);
  await page.evaluate(() => {
    const session = window.__speech.instances[0];
    session.onerror({error: 'not-allowed'});
    session.onend();
  });
  await expect(page.locator('#voice-status')).toContainText('Microphone permission was denied');
  await expect(page.getByLabel('Your message')).toBeEditable();
});

test('pending and stopped speech sessions cannot overlap or replace a typed draft', async ({page}) => {
  await mockSpeech(page);
  await startBrowserDictation(page);
  const start = page.getByRole('button', {name: 'Dictate a message', exact: true});
  await expect(start).toBeDisabled();
  await start.evaluate(button => button.click());
  expect(await page.evaluate(() => window.__speech.instances.length)).toBe(1);
  await page.locator('#dictation-cancel').click();
  await page.getByLabel('Your message').fill('Keep this typed draft');
  await startBrowserDictation(page);
  await page.evaluate(() => {
    const [old, current] = window.__speech.instances;
    current.onstart(); old.onstart();
    old.onresult({results: [[{transcript: 'Stale transcript'}]]}); old.onend();
  });
  await expect(page.getByLabel('Your message')).toHaveValue('Keep this typed draft');
  await expect(page.locator('#voice-status')).toContainText('Listening…');
  await page.evaluate(() => window.__speech.instances[1].onresult({results: [[{transcript: 'Monthly summary'}]]}));
  await expect(page.getByLabel('Your message')).toHaveValue('Keep this typed draft Monthly summary');
  await expect(page.locator('.message.user')).toHaveCount(0);
  await page.locator('#dictation-cancel').click();
  await page.evaluate(() => window.__speech.instances[1].onresult({results: [[{transcript: 'After cancellation'}]]}));
  await expect(page.getByLabel('Your message')).toHaveValue('Keep this typed draft');
  await expect(page.getByLabel('Your message')).toBeEditable();
});

test('chat merchant names still produce a review and closing it saves nothing', async ({page, request}) => {
  const before = await state(request);
  await page.goto('/coach');
  await page.getByLabel('Your message').fill('I spent 45 at Springfield yesterday');
  await page.getByRole('button', {name: 'Send', exact: true}).click();
  await expect(page.getByRole('dialog')).toBeVisible();
  await expect(page.getByRole('dialog')).toContainText('Springfield');
  await page.getByRole('button', {name: 'Keep reviewing', exact: true}).click();
  expect((await state(request)).revision).toBe(before.revision);
});

async function chatReview(page, request, text) {
  const before = await state(request);
  await page.getByLabel('Your message').fill(text);
  await page.getByRole('button', {name: 'Send', exact: true}).click();
  await expect(page.getByRole('dialog')).toBeVisible();
  expect((await state(request)).revision).toBe(before.revision);
  return page.getByRole('dialog');
}

async function confirm(page, name = 'Confirm save') {
  const additions = page.getByLabel('I reviewed and want to add these shared categories.', {exact: true});
  if (await additions.count()) await additions.check();
  await page.getByRole('button', {name, exact: true}).click();
  await expect(page.getByRole('dialog')).toBeHidden();
}

test('chat edits, deletes, budget corrections and undo preserve confirmation gates', async ({page, request}) => {
  const original = await state(request);
  const target = original.transactions.find(row => row.currency === 'EUR' && row.date.startsWith('2026-10') && row.category === 'Household' && Number(row.amount) > 0);
  await page.goto('/coach');
  await chatReview(page, request, `change transaction ${target.id} amount to 25`);
  await confirm(page);
  expect((await state(request)).transactions.find(row => row.id === target.id).amount).toBe('25.00');

  await chatReview(page, request, `delete transaction ${target.id}`);
  await confirm(page);
  expect((await state(request)).transactions.some(row => row.id === target.id)).toBe(false);
  await chatReview(page, request, 'undo');
  await confirm(page, 'Confirm undo');
  expect((await state(request)).transactions.find(row => row.id === target.id).amount).toBe('25.00');

  const beforeBudget = await state(request);
  await chatReview(page, request, 'set Household budget to 300 for 2026-10');
  await page.getByText('Correct the proposed details', {exact: true}).click();
  await page.locator('#correct-proposal').getByLabel('Month (YYYY-MM)').fill('2026-11');
  await page.locator('#correct-proposal').getByLabel('Category', {exact: true}).fill('Insurance');
  await page.getByRole('button', {name: 'Update preview', exact: true}).click();
  await expect(page.getByRole('dialog')).toContainText('Insurance');
  await expect(page.getByRole('dialog')).toContainText('2026-11');
  expect((await state(request)).revision).toBe(beforeBudget.revision);
  await page.getByRole('button', {name: 'Keep reviewing', exact: true}).click();
  // Reopening the chat proposal must use its corrected server token.
  await page.locator('.message.assistant').last().getByRole('button', {name: 'Review proposed change'}).click();
  await expect(page.getByRole('dialog')).toContainText('Insurance');
  await expect(page.getByLabel('I reviewed and want to add these shared categories.', {exact: true})).toBeVisible();
  await page.getByRole('button', {name: 'Confirm save', exact: true}).click();
  await expect(page.locator('#review-error')).toBeVisible();
  expect((await state(request)).revision).toBe(beforeBudget.revision);
  await confirm(page);
  const saved = await state(request);
  expect(saved.budgets.filter(row => row.period === '2026-10' && row.currency === 'EUR' && row.category === 'Household' && row.subcategory === '')).toHaveLength(0);
  expect(saved.budgets.filter(row => row.subcategory !== '')).toEqual(beforeBudget.budgets.filter(row => row.subcategory !== ''));
  expect(saved.budgets.find(row => row.period === '2026-11' && row.category === 'Insurance').amount).toBe('300.00');
  await chatReview(page, request, 'undo');
  await confirm(page, 'Confirm undo');
  expect((await state(request)).budgets).toEqual(beforeBudget.budgets);
});

test('navigation and late read-aloud events cannot revive stopped speech', async ({page}) => {
  await mockSpeech(page);
  await page.evaluate(() => {window.speechSynthesis.speak = utterance => {window.__speech.utterance = utterance;};});
  await page.getByLabel('Your message').fill('Monthly summary');
  await page.getByRole('button', {name: 'Send', exact: true}).click();
  await expect(page.locator('.message.assistant')).toContainText('3250.00');
  await page.getByRole('button', {name: 'Read reply aloud', exact: true}).click();
  await page.getByRole('button', {name: 'Read aloud', exact: true}).click();
  await expect(page.getByRole('button', {name: 'Stop reading', exact: true})).toBeVisible();
  await page.getByRole('button', {name: 'Stop reading', exact: true}).click();
  await page.evaluate(() => window.__speech.utterance.onend());
  await expect(page.getByRole('button', {name: 'Stop reading', exact: true})).toBeHidden();
  await expect(page.locator('#voice-status')).not.toContainText('Finished reading aloud');
  await startBrowserDictation(page);
  await page.evaluate(() => window.__speech.instances[0].onstart());
  await page.locator('.sidebar').getByRole('link', {name: 'Overview', exact: true}).click();
  expect(await page.evaluate(() => window.__speech.instances[0].aborts)).toBe(1);
  await page.evaluate(() => window.__speech.instances[0].onresult({results: [[{transcript: 'Late navigation transcript'}]]}));
  await page.getByRole('button', {name: 'Open chat', exact: true}).click();
  await expect(page.getByLabel('Your message')).toHaveValue('');
});
