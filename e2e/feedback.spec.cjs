const {test, expect} = require('@playwright/test');
const fs = require('node:fs/promises');
const path = require('node:path');

const snapshot = async request => (await request.get('/api/state')).json();
test.beforeEach(async ({page, request}) => {
  const initial = await snapshot(request);
  expect((await request.post('/api/test/reset', {headers:{'X-HomeAccounts-Token':initial.csrf},data:{seed:true}})).ok()).toBeTruthy();
  page.on('pageerror', error => { throw error; });
  await page.route('**/*', route => new URL(route.request().url()).hostname === '127.0.0.1' ? route.continue() : route.abort());
});

test('currency searches countries and month selection works without records', async ({page,request}) => {
  const before = await snapshot(request);
  await page.goto('/overview');
  await expect(page.getByRole('button',{name:'Change visual mode'})).toHaveAttribute('title',/Switch visual mode/);
  const currency = page.getByRole('combobox',{name:'Reporting currency'});
  await currency.fill('United States');
  await page.getByRole('option',{name:/^USD/}).click();
  await expect(currency).toHaveValue('USD');
  await page.getByLabel('Reporting month').fill('2032-05');
  await expect(page).toHaveURL(/month=2032-05/);
  await expect(page.getByRole('heading',{name:'No records in this selection'})).toBeVisible();
  expect((await snapshot(request)).revision).toBe(before.revision);
  expect(await page.locator('label[for=scope-month]').evaluate(node=>parseFloat(getComputedStyle(node).fontSize))).toBeGreaterThanOrEqual(14);
});

test('chat expands and help preserves an unsaved full-page transaction', async ({page}) => {
  await page.goto('/entry');
  await page.locator('#entry_amount').fill('33.50');
  await page.locator('#entry_description').fill('Keep this unfinished entry');
  await expect(page.locator('.sidebar').getByRole('link',{name:'Coach',exact:true})).toHaveCount(0);
  await page.getByRole('button',{name:'Open chat',exact:true}).click();
  await page.getByLabel('Your message').fill('Keep my chat draft');
  await page.getByRole('button',{name:'Expand chat',exact:true}).click();
  await expect(page.locator('#chat-drawer')).toHaveClass(/expanded/);
  await expect(page.getByLabel('Your message')).toHaveValue('Keep my chat draft');
  await page.getByRole('button',{name:'Collapse chat',exact:true}).click();
  await page.getByRole('button',{name:'Close chat',exact:true}).click();
  await expect(page.locator('#entry_amount')).toHaveValue('33.50');
  await page.getByRole('button',{name:'Help walkthrough',exact:true}).click();
  await page.getByRole('button',{name:'Guide me through this page',exact:true}).click();
  await expect(page.locator('#walkthrough')).toContainText('Record what happened');
  await page.getByRole('button',{name:'End walkthrough',exact:true}).click();
  await expect(page.locator('#entry_description')).toHaveValue('Keep this unfinished entry');
  await expect(page).toHaveURL(/\/entry$/);
});

test('overview Add opens a dialog, saves only after review, and highlights the record', async ({page,request}) => {
  const before = await snapshot(request);
  await page.goto('/overview');
  await page.getByRole('button',{name:'Add transaction',exact:true}).click();
  const form = page.locator('#entry-dialog');
  await expect(form).toBeVisible();
  await form.locator('[name=date]').fill('2026-10-11');
  await form.locator('[name=amount]').fill('41.25');
  await form.locator('[name=description]').fill('Fictional modal purchase');
  await form.locator('[name=category]').selectOption('Household');
  await form.getByRole('button',{name:'Review transaction',exact:true}).click();
  await expect(page.locator('#review')).toBeVisible();
  expect((await snapshot(request)).revision).toBe(before.revision);
  await page.locator('#review').getByRole('button',{name:'Confirm save',exact:true}).click();
  await expect(form).toBeHidden();
  await expect(page.locator('.saved-records')).toContainText('1 transaction saved');
  expect((await snapshot(request)).transactions).toHaveLength(before.transactions.length+1);
  await page.getByRole('link',{name:'View saved transaction'}).click();
  await expect(page.locator('tr.just-added')).toHaveCount(1);
  await page.locator('.sidebar').getByRole('link',{name:'Add transaction',exact:true}).click();
  await expect(page).toHaveURL(/\/entry$/);
  await expect(page.locator('#entry-form')).toBeVisible();
  await expect(form).toBeHidden();
});

test('column filters and numeric sorting match the exported records', async ({page,request}) => {
  const before = await snapshot(request);
  await page.goto('/transactions?currency=EUR&month=2026-10');
  await page.locator('#filter-category').fill('Household');
  await page.locator('[data-sort=amount]').click();
  const shown = await page.locator('#transaction-grid tbody tr[data-transaction-id]').evaluateAll(rows=>rows.map(row=>({id:row.dataset.transactionId,amount:Number(row.children[5].textContent)})));
  expect(shown.length).toBeGreaterThan(0);
  expect(shown.map(row=>row.amount)).toEqual([...shown.map(row=>row.amount)].sort((a,b)=>a-b));
  const query = new URL(page.url()).searchParams; query.set('kind','transactions');
  const response = await request.get('/api/export?'+query);
  expect(response.ok()).toBeTruthy();
  const csv = await response.text();
  const ids = csv.trim().split(/\r?\n/).slice(1).map(line=>line.split(',')[0]);
  expect(ids).toEqual(shown.map(row=>row.id));
  await page.locator('#filter-description').fill('no such fictional record');
  await expect(page.locator('#grid-count')).toContainText('0 of');
  await page.getByRole('button',{name:'Clear column filters',exact:true}).click();
  await expect(page.locator('#transaction-grid tbody tr[data-transaction-id]')).not.toHaveCount(0);
  expect((await snapshot(request)).revision).toBe(before.revision);
});

test('clear all requires acknowledgment, keeps budgets, and is undoable', async ({page,request}) => {
  const before = await snapshot(request);
  await page.goto('/overview');
  await page.locator('.page-head').getByRole('button',{name:'Clear all transactions',exact:true}).click();
  const confirm = page.getByRole('button',{name:'Confirm clear all transactions',exact:true});
  await expect(confirm).toBeDisabled();
  expect((await snapshot(request)).revision).toBe(before.revision);
  await page.locator('#confirm-clear').check();
  await confirm.click();
  await expect(page.locator('#review')).toBeHidden();
  const cleared = await snapshot(request);
  expect(cleared.transactions).toHaveLength(0);
  expect(cleared.budgets).toEqual(before.budgets);
  await page.getByRole('link',{name:'Review undo'}).click();
  await page.locator('#undo-review').click();
  await page.getByRole('button',{name:'Confirm undo',exact:true}).click();
  await expect(page.locator('#review')).toBeHidden();
  expect((await snapshot(request)).transactions).toEqual(before.transactions);
});

test('US demo choices prepare correctly mapped transactions and budgets without saving', async ({page,request}) => {
  const before = await snapshot(request);
  await page.goto('/import');
  await page.getByRole('button',{name:'US demo: 462 transactions',exact:true}).click();
  await expect(page.locator('#import-mapping [name=currency]')).toHaveValue('USD');
  await page.getByRole('button',{name:'Prepare import review',exact:false}).click();
  await expect(page.locator('#import-preview')).toContainText('462');
  expect((await snapshot(request)).revision).toBe(before.revision);
  await page.getByRole('button',{name:'US demo: 324 budgets',exact:true}).click();
  await expect(page.locator('#import-mapping [name=kind]')).toHaveValue('Budgets');
  await expect(page.locator('#import-mapping [name=map_budget]')).toHaveValue('amount');
  await page.getByRole('button',{name:'Prepare import review',exact:false}).click();
  await expect(page.locator('#import-preview')).toContainText('324');
  expect((await snapshot(request)).revision).toBe(before.revision);
});

test('feedback visual candidates', async ({page}) => {
  test.skip(!process.env.CAPTURE_FEEDBACK, 'Manual review captures only');
  const folder=path.resolve('test-results/feedback-candidates'); await fs.mkdir(folder,{recursive:true});
  for (const width of [1440,390]) {
    await page.setViewportSize({width,height:1000});
    await page.goto('/overview');
    await page.screenshot({path:path.join(folder,`overview-${width}.png`),fullPage:true});
    await page.getByRole('button',{name:'Open chat',exact:true}).click();
    await page.screenshot({path:path.join(folder,`chat-${width}.png`),fullPage:false});
    await page.getByRole('button',{name:'Close chat',exact:true}).click();
    await page.getByRole('button',{name:'Add transaction',exact:true}).click();
    await page.screenshot({path:path.join(folder,`entry-${width}.png`),fullPage:false});
    await page.goto('/transactions');
    await page.screenshot({path:path.join(folder,`grid-${width}.png`),fullPage:true});
  }
});
