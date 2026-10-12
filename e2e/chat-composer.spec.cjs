const {test,expect}=require('@playwright/test');
const fs=require('node:fs/promises');
const path=require('node:path');
test.beforeEach(async({page,request})=>{
  const state=await (await request.get('/api/state')).json();
  await request.post('/api/test/reset',{headers:{'X-HomeAccounts-Token':state.csrf},data:{seed:true}});
  page.on('pageerror',error=>{throw error;});
  await page.route('**/*',route=>new URL(route.request().url()).hostname==='127.0.0.1'?route.continue():route.abort());
  await page.route('**/api/state',async route=>{const response=await route.fetch(),data=await response.json();data.transcription={configured:true,endpoint:'https://api.openai.com/v1/audio/transcriptions'};await route.fulfill({response,json:data});});
  await page.addInitScript(()=>{
    window.__mic={calls:0,stops:0};
    const track={stop(){__mic.stops++;},addEventListener(){}};
    Object.defineProperty(navigator,'mediaDevices',{configurable:true,value:{getUserMedia:async()=>{__mic.calls++;return {getTracks:()=>[track],getAudioTracks:()=>[track]};}}});
    window.MediaRecorder=class{static isTypeSupported(){return true;}constructor(stream,options){this.mimeType=options.mimeType;this.state='inactive';}start(){this.state='recording';}stop(){if(this.state==='inactive')return;this.state='inactive';this.ondataavailable?.({data:new Blob([new Uint8Array([26,69,223,163,1,2,3,4])],{type:this.mimeType})});this.onstop?.();}};
  });
});

test('composer records after opt-in, preserves typed draft and never auto-sends the transcript',async({page})=>{
  const messages=[],audio=[];
  page.on('request',request=>{if(request.url().endsWith('/api/chat'))messages.push(request);});
  await page.route('**/api/voice/transcribe',async route=>{audio.push(route.request().postDataJSON());await route.fulfill({json:{text:'groceries this week'}});});
  await page.goto('/overview');await page.getByRole('button',{name:'Open chat',exact:true}).click();
  await page.getByLabel('Your message').fill('Review');
  await page.getByRole('button',{name:'Dictate a message',exact:true}).click();
  expect(await page.evaluate(()=>__mic.calls)).toBe(0);
  await page.getByRole('button',{name:'Start dictation',exact:true}).click();
  await expect(page.locator('#recording-label')).toHaveText('Recording');
  await expect(page.getByRole('button',{name:'Send',exact:true})).toBeDisabled();
  await page.getByRole('button',{name:'Done',exact:true}).click();
  await expect(page.getByLabel('Your message')).toHaveValue('Review groceries this week');
  await expect(page.locator('#dictation-strip')).toBeHidden();
  expect(await page.evaluate(()=>__mic.stops)).toBe(1);
  expect(audio).toHaveLength(1);expect(audio[0]).toMatchObject({transcription_consent:true,language:'en',mime:'audio/webm;codecs=opus',provider_endpoint:'https://api.openai.com/v1/audio/transcriptions'});
  expect(messages).toHaveLength(0);
  await page.getByLabel('Your message').fill('Monthly summary');
  await page.getByLabel('Your message').press('Enter');
  await expect(page.locator('.message.assistant')).toContainText('3250.00');
});

test('transcription credit error leaves the original draft and microphone off without retry',async({page})=>{
  let requests=0;
  await page.route('**/api/voice/transcribe',async route=>{requests++;await route.fulfill({status:400,json:{error:'OpenAI API credits are exhausted. Add API credits, then try again.'}});});
  await page.goto('/coach');await page.getByLabel('Your message').fill('Keep this draft');
  await page.getByRole('button',{name:'Dictate a message',exact:true}).click();await page.getByRole('button',{name:'Start dictation',exact:true}).click();
  await expect(page.locator('#recording-label')).toHaveText('Recording');await page.getByRole('button',{name:'Done',exact:true}).click();
  await expect(page.locator('#voice-status')).toContainText('Add API credits');
  await expect(page.getByLabel('Your message')).toHaveValue('Keep this draft');
  expect(await page.evaluate(()=>__mic.stops)).toBeGreaterThanOrEqual(1);expect(requests).toBe(1);
  await expect(page.getByRole('button',{name:'Send',exact:true})).toBeEnabled();
});

test('chat keyboard sends once and Shift Enter keeps a newline',async({page})=>{
  let calls=0;
  await page.route('**/api/chat',async route=>{calls++;await new Promise(resolve=>setTimeout(resolve,180));await route.fulfill({json:{answer:'Fictional answer'}});});
  await page.goto('/coach');const input=page.getByLabel('Your message');
  await input.fill('First line');await input.press('Shift+Enter');await input.type('Second line');
  await expect(input).toHaveValue('First line\nSecond line');expect(calls).toBe(0);
  await input.press('Enter');await page.getByLabel('Your message').press('Enter');
  await expect(page.locator('.message.assistant')).toHaveText('Fictional answer');expect(calls).toBe(1);
});

test('compact chat and voice dialog fit phone and desktop',async({page})=>{
  for(const [name,width,height] of [['desktop',1440,1000],['phone',390,844]]){
    await page.setViewportSize({width,height});await page.goto('/overview');await page.getByRole('button',{name:'Open chat',exact:true}).click();
    const box=await page.locator('#chat-form').boundingBox();expect(box.y+box.height).toBeLessThanOrEqual(height);
    await expect(page.getByRole('button',{name:'Dictate a message',exact:true})).toBeVisible();
    if(process.env.CAPTURE_CHAT){await fs.mkdir('test-results/chat-candidates',{recursive:true});await page.screenshot({path:path.join('test-results/chat-candidates',`chat-${name}.png`)});}
    await page.getByRole('button',{name:'Open voice mode',exact:true}).click();
    await expect(page.getByRole('dialog',{name:'Voice conversation',exact:true})).toBeVisible();
    expect(await page.evaluate(()=>__mic.calls)).toBe(0);
    if(process.env.CAPTURE_CHAT)await page.screenshot({path:path.join('test-results/chat-candidates',`voice-${name}.png`)});
    await page.keyboard.press('Escape');await expect(page.locator('#voice-dialog')).toBeHidden();
  }
});
