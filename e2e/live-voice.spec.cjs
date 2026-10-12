const {test, expect} = require('@playwright/test');
const sdp = 'v=0\r\no=- 1 1 IN IP4 127.0.0.1\r\ns=-\r\nt=0 0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\n';

test.beforeEach(async ({page}) => {
  await page.route('**/*', route => {
    const url = new URL(route.request().url());
    return url.hostname === '127.0.0.1' ? route.continue() : route.abort();
  });
  await page.route('**/voice-test-harness', route => route.fulfill({contentType:'text/html', body:'<!doctype html><title>Isolated voice test</title><main>Fictional live voice test</main>'}));
  await page.addInitScript(sdp => {
    const mock = window.__rtc = {pending:[], peers:[], tracks:[], sent:[], requests:[], statuses:[], transcripts:[], calls:[], toolSignals:[], deferredRequests:[], deferSession:false, localResult:{answer:'Confirmed 2026-10 (EUR): Net expenses: 12.50.',reviewNeedsConfirmation:false}};
    class Track extends EventTarget {
      constructor(){super();this.stops=0;mock.tracks.push(this);}
      stop(){this.stops++;}
    }
    class Channel extends EventTarget {
      constructor(){super();this.readyState='open';}
      send(value){mock.sent.push(JSON.parse(value));}
      close(){this.readyState='closed';this.dispatchEvent(new Event('close'));}
      message(data){this.dispatchEvent(new MessageEvent('message',{data:JSON.stringify(data)}));}
    }
    class Peer extends EventTarget {
      constructor(){super();this.connectionState='new';this.closed=false;mock.peers.push(this);}
      addTrack(){}
      createDataChannel(){this.channel=new Channel();return this.channel;}
      async createOffer(){return {type:'offer',sdp};}
      async setLocalDescription(offer){this.localDescription=offer;}
      async setRemoteDescription(answer){this.answer=answer;}
      getReceivers(){return [];}
      close(){this.closed=true;this.connectionState='closed';this.dispatchEvent(new Event('connectionstatechange'));}
    }
    window.RTCPeerConnection=Peer;
    Object.defineProperty(navigator,'mediaDevices',{configurable:true,value:{getUserMedia(){return new Promise((resolve,reject)=>mock.pending.push({resolve,reject}));}}});
    HTMLMediaElement.prototype.play=()=>Promise.resolve();
    HTMLMediaElement.prototype.pause=()=>{};
    mock.allow=()=>{const track=new Track();mock.pending.shift().resolve({getTracks:()=>[track],getAudioTracks:()=>[track]});};
    mock.emit=(event,index=mock.peers.length-1)=>mock.peers[index].channel.message(event);
    mock.functionCall=(id,text,name='home_accounts_request')=>mock.emit({type:'response.done',response:{status:'completed',output:[{type:'function_call',name,call_id:id,arguments:typeof text==='string'?JSON.stringify({text}):JSON.stringify(text)}]}});
  },sdp);
});

async function harness(page) {
  await page.goto('/voice-test-harness');
  await page.evaluate(async sdp => {
    const {createLiveVoice}=await import('/assets/live-voice.js');
    const mock=window.__rtc;
    mock.voice=createLiveVoice({
      status:text=>mock.statuses.push(text),transcript:message=>mock.transcripts.push(message),
      requestSession:(body,{signal})=>{
        mock.requests.push({body,signal});
        return mock.deferSession?new Promise(resolve=>mock.deferredRequests.push(resolve)):Promise.resolve({sdp});
      },
      onRequest:async(args,{signal})=>{mock.calls.push(args);mock.toolSignals.push(signal);return mock.localHandler?mock.localHandler(args):mock.localResult;},
    });
    mock.start=()=>{mock.startResult=mock.voice.start({consent:true,context:{page:'/overview',month:'2026-10',currency:'EUR',records:['must not send']}});};
  },sdp);
}

async function start(page) {
  await page.evaluate(()=>{__rtc.start();__rtc.allow();});
  await expect.poll(()=>page.evaluate(()=>Boolean(__rtc.peers[0]?.answer))).toBe(true);
  await page.evaluate(()=>__rtc.emit({type:'session.created'}));
}

test('live voice requires consent and cancels microphone permission races',async({page})=>{
  await harness(page);
  expect(await page.evaluate(()=>__rtc.voice.start({consent:false}))).toBe(false);
  expect(await page.evaluate(()=>__rtc.pending.length)).toBe(0);
  await page.evaluate(()=>{__rtc.start();__rtc.voice.stop();__rtc.allow();});
  expect(await page.evaluate(()=>__rtc.startResult)).toBe(false);
  expect(await page.evaluate(()=>__rtc.tracks[0].stops)).toBe(1);
  expect(await page.evaluate(()=>__rtc.requests.length)).toBe(0);
  await page.evaluate(()=>{__rtc.start();__rtc.pending.shift().reject(new DOMException('denied','NotAllowedError'));});
  expect(await page.evaluate(()=>__rtc.startResult)).toBe(false);
  expect(await page.evaluate(()=>__rtc.statuses.at(-1))).toContain('permission was denied');
  await page.evaluate(()=>__rtc.voice.dispose());
});

test('late signalling and transcript callbacks cannot revive a stopped session',async({page})=>{
  await harness(page);
  await page.evaluate(()=>{__rtc.deferSession=true;__rtc.start();__rtc.allow();});
  await expect.poll(()=>page.evaluate(()=>__rtc.requests.length)).toBe(1);
  await page.evaluate(sdp=>{
    __rtc.voice.stop();
    __rtc.deferredRequests.shift()({sdp});
    __rtc.emit({type:'conversation.item.input_audio_transcription.completed',item_id:'late',transcript:'Must be ignored'});
    __rtc.emit({type:'session.created'});
  },sdp);
  expect(await page.evaluate(()=>__rtc.startResult)).toBe(false);
  expect(await page.evaluate(()=>__rtc.requests[0].signal.aborted)).toBe(true);
  expect(await page.evaluate(()=>__rtc.tracks[0].stops)).toBe(1);
  expect(await page.evaluate(()=>__rtc.peers[0].closed)).toBe(true);
  expect(await page.evaluate(()=>__rtc.transcripts)).toEqual([]);
  expect(await page.evaluate(()=>__rtc.voice.active)).toBe(false);
  await page.evaluate(()=>__rtc.voice.dispose());
});

test('local voice tools are scoped, deduplicated and only return the permitted summary',async({page})=>{
  await harness(page);await start(page);
  await page.evaluate(()=>{
    __rtc.localResult={answer:'Review the proposed expense.',reviewNeedsConfirmation:true,records:['private record'],token:'private-token'};
    __rtc.functionCall('first','Add a fictional expense');
  });
  await expect.poll(()=>page.evaluate(()=>__rtc.sent.length)).toBe(2);
  const output=await page.evaluate(()=>JSON.parse(__rtc.sent[0].item.output));
  expect(output).toEqual({answer:'Review the proposed expense.',reviewNeedsConfirmation:true,scope:{month:'2026-10',currency:'EUR'}});
  const call=await page.evaluate(()=>__rtc.calls[0]);
  expect(call).toEqual({text:'Add a fictional expense',context:{page:'/overview',month:'2026-10',currency:'EUR'}});
  expect(await page.evaluate(()=>__rtc.requests[0].body.context)).toEqual(call.context);
  await page.evaluate(()=>{
    __rtc.functionCall('first','Duplicate');
    __rtc.functionCall('unknown','Clear everything','confirm');
    __rtc.functionCall('invalid',{text:'A request',confirm:true});
    __rtc.emit({type:'response.output_audio_transcript.done',item_id:'reply',transcript:'Review this first.'});
    __rtc.emit({type:'response.output_audio_transcript.done',item_id:'reply',transcript:'Review this first.'});
  });
  expect(await page.evaluate(()=>__rtc.calls.length)).toBe(1);
  expect(await page.evaluate(()=>__rtc.transcripts.length)).toBe(1);
  await page.evaluate(()=>window.dispatchEvent(new Event('popstate')));
  expect(await page.evaluate(()=>__rtc.voice.active)).toBe(false);
  expect(await page.evaluate(()=>__rtc.tracks[0].stops)).toBe(1);
  await page.evaluate(()=>__rtc.voice.dispose());
});

test('voice can prepare an actual local review but cannot confirm or save it',async({page,request})=>{
  const initial=await (await request.get('/api/state')).json();
  await request.post('/api/test/reset',{headers:{'X-HomeAccounts-Token':initial.csrf},data:{seed:true}});
  const before=await (await request.get('/api/state')).json();
  await harness(page);await start(page);
  await page.evaluate(csrf=>{
    __rtc.localHandler=async({text,context})=>{
      const response=await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json','X-HomeAccounts-Token':csrf},body:JSON.stringify({text,month:context.month,currency:context.currency,reference_date:'2026-10-11',use_ai:false})});
      const result=await response.json();
      __rtc.review=result.review;
      return {answer:result.answer,reviewNeedsConfirmation:Boolean(result.review)};
    };
    __rtc.functionCall('proposal','Spent 7 EUR on coffee today');
  },before.csrf);
  await expect.poll(()=>page.evaluate(()=>Boolean(__rtc.review))).toBe(true);
  await expect.poll(()=>page.evaluate(()=>__rtc.sent.length)).toBe(2);
  const after=await (await request.get('/api/state')).json();
  expect(after.transactions).toEqual(before.transactions);
  expect(after.revision).toBe(before.revision);
  expect(await page.evaluate(()=>JSON.parse(__rtc.sent[0].item.output).reviewNeedsConfirmation)).toBe(true);
  expect(await page.evaluate(()=>JSON.stringify(__rtc.sent))).not.toContain('source_ref');
  await page.evaluate(()=>__rtc.voice.dispose());
});

test('ending voice aborts pending local answers and cannot send them afterward',async({page})=>{
  await harness(page);await start(page);
  await page.evaluate(()=>{
    __rtc.localHandler=()=>new Promise(resolve=>{__rtc.resolveLocal=resolve;});
    __rtc.functionCall('waiting','Monthly summary');
  });
  await expect.poll(()=>page.evaluate(()=>__rtc.calls.length)).toBe(1);
  await page.evaluate(()=>{
    __rtc.voice.stop();
    __rtc.resolveLocal({answer:'A late private answer',reviewNeedsConfirmation:true});
  });
  expect(await page.evaluate(()=>__rtc.toolSignals[0].aborted)).toBe(true);
  expect(await page.evaluate(()=>__rtc.sent)).toEqual([]);
  expect(await page.evaluate(()=>__rtc.statuses.at(-1))).toContain('microphone is off');
  await page.evaluate(()=>__rtc.voice.dispose());
});

async function application(page,request) {
  const original=await (await request.get('/api/state')).json();
  const reset=await request.post('/api/test/reset',{headers:{'X-HomeAccounts-Token':original.csrf},data:{seed:true}});
  expect(reset.ok()).toBe(true);
  const before=await (await request.get('/api/state')).json();
  const signalling=[];
  page.on('pageerror',error=>{throw error;});
  // The real app and local Coach run against the fictional store. Only WebRTC and
  // the upstream session exchange are mocked; no microphone or paid API is used.
  await page.route('**/api/state',async route=>{
    const response=await route.fetch();
    const state=await response.json();
    state.live_voice={supported:true,configured:true,provider:'OpenAI',model:'fictional-voice-model',endpoint:'https://api.openai.com/v1/realtime/calls',mode:'local-coach',error:null};
    await route.fulfill({response,json:state});
  });
  await page.route('**/api/voice/session',async route=>{
    signalling.push(route.request().postDataJSON());
    await route.fulfill({json:{sdp,model:'fictional-voice-model',mode:'local-coach'}});
  });
  await page.goto('/overview?month=2026-10&currency=EUR');
  await page.getByRole('button',{name:'Open chat',exact:true}).click();
  await page.getByRole('button',{name:'Open voice mode',exact:true}).click();
  expect(await page.evaluate(()=>__rtc.pending.length)).toBe(0);
  await page.getByRole('button',{name:'Start voice conversation',exact:true}).click();
  await expect.poll(()=>page.evaluate(()=>__rtc.pending.length)).toBe(1);
  await page.evaluate(()=>__rtc.allow());
  await expect.poll(()=>page.evaluate(()=>Boolean(__rtc.peers[0]?.answer))).toBe(true);
  await page.evaluate(()=>__rtc.emit({type:'session.created'}));
  await expect(page.locator('#live-status')).toContainText('Live voice connected');
  expect(signalling).toHaveLength(1);
  expect(signalling[0]).toMatchObject({live_consent:true,provider_endpoint:'https://api.openai.com/v1/realtime/calls',context:{page:'/overview',month:'2026-10',currency:'EUR'}});
  return {before,signalling};
}

test('actual chat drawer live voice uses the captured scope and a string request for local figures',async({page,request})=>{
  const {before}=await application(page,request);
  let body,localAnswer;
  await page.route('**/api/chat',async route=>{
    body=route.request().postDataJSON();
    const response=await route.fetch();
    const result=await response.json();
    localAnswer=result.answer;
    await route.fulfill({response,json:result});
  });
  await page.evaluate(()=>__rtc.functionCall('actual-summary','monthly summary'));
  await expect.poll(()=>page.evaluate(()=>__rtc.sent.length)).toBe(2);
  expect(body).toMatchObject({text:'monthly summary',month:'2026-10',currency:'EUR',use_ai:false});
  expect(typeof body.text).toBe('string');
  expect(localAnswer).toContain('3250.00');
  expect(await page.evaluate(()=>JSON.parse(__rtc.sent[0].item.output))).toEqual({answer:localAnswer,reviewNeedsConfirmation:false,scope:{month:'2026-10',currency:'EUR'}});
  await expect(page.locator('#review')).not.toBeVisible();
  const after=await (await request.get('/api/state')).json();
  expect(after.revision).toBe(before.revision);
  expect(after.transactions).toEqual(before.transactions);
  await page.locator('#live-stop').click();
  expect(await page.evaluate(()=>__rtc.tracks[0].stops)).toBe(1);
});

test('actual chat drawer live expense proposal opens review without confirming or saving',async({page,request})=>{
  const {before}=await application(page,request);
  const writes=[];
  page.on('request',req=>{if(req.url().endsWith('/api/proposal/confirm'))writes.push(req);});
  await page.evaluate(()=>__rtc.functionCall('actual-expense','Spent 7 EUR on coffee today'));
  await expect(page.locator('#review')).toBeVisible();
  await expect(page.locator('#review')).toContainText('7.00');
  await expect(page.locator('#review').getByRole('button',{name:'Confirm save',exact:true})).toBeVisible();
  await expect.poll(()=>page.evaluate(()=>__rtc.sent.length)).toBe(2);
  expect(await page.evaluate(()=>JSON.parse(__rtc.sent[0].item.output).reviewNeedsConfirmation)).toBe(true);
  expect(await page.evaluate(()=>JSON.stringify(__rtc.sent))).not.toContain('source_ref');
  expect(writes).toHaveLength(0);
  const after=await (await request.get('/api/state')).json();
  expect(after.revision).toBe(before.revision);
  expect(after.transactions).toEqual(before.transactions);
  await page.locator('#review').getByRole('button',{name:'Keep reviewing',exact:true}).click();
  await page.locator('#live-stop').click();
});

for(const end of ['Stop','navigation','close voice mode']) {
  test(`actual app ${end} prevents a late live proposal from opening review`,async({page,request})=>{
    const {before}=await application(page,request);
    let release,finished,prepared;
    const gate=new Promise(resolve=>{release=resolve;});
    const delivered=new Promise(resolve=>{finished=resolve;});
    await page.route('**/api/chat',async route=>{
      try {
        const response=await route.fetch();
        prepared=await response.json();
        await gate;
        // An aborted browser fetch can reject fulfillment. Both paths must leave
        // its late proposal hidden and keep the confirmed store unchanged.
        try {await route.fulfill({response,json:prepared});} catch {}
      } finally {finished();}
    });
    await page.evaluate(()=>__rtc.functionCall('delayed-expense','Spent 7 EUR on coffee today'));
    await expect.poll(()=>Boolean(prepared?.review)).toBe(true);
    const aborted=page.waitForEvent('requestfailed',{predicate:req=>req.url().endsWith('/api/chat'),timeout:5000});
    try {
      if(end==='Stop')await page.locator('#live-stop').click();
      else if(end==='close voice mode')await page.getByRole('button',{name:'Close voice mode',exact:true}).click();
      else await page.evaluate(()=>{history.pushState({},'', '/transactions');window.dispatchEvent(new PopStateEvent('popstate'));});
      await aborted;
    } finally {release();await delivered;}
    await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
    await expect(page.locator('#review')).not.toBeVisible();
    expect(await page.evaluate(()=>__rtc.sent)).toEqual([]);
    expect(await page.evaluate(()=>__rtc.tracks[0].stops)).toBe(1);
    if(end==='navigation')await expect(page).toHaveURL(/\/transactions/);
    const after=await (await request.get('/api/state')).json();
    expect(after.revision).toBe(before.revision);
    expect(after.transactions).toEqual(before.transactions);
  });
}
