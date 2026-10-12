const {test, expect} = require('@playwright/test');

test.beforeEach(async ({page}) => {
  page.on('pageerror', error => { throw error; });
  await page.route('**/*', route => {
    const url = new URL(route.request().url());
    return url.hostname === '127.0.0.1' ? route.continue() : route.abort();
  });
  await page.route('**/dictation-test-harness', route => route.fulfill({
    contentType: 'text/html',
    body: '<!doctype html><title>Isolated dictation test</title><main>Fictional recorded dictation</main>',
  }));
  await page.addInitScript(() => {
    const mock = window.__dictation = {
      pending: [], tracks: [], recorders: [], changes: [], drafts: [], requests: [], deferred: [],
      currentDraft: 'Existing typed draft', defer: false, transcript: 'Fictional household entry',
      error: null, bytes: [0x1a, 0x45, 0xdf, 0xa3, ...new TextEncoder().encode('fictional-webm')],
    };
    class Track extends EventTarget {
      constructor() { super(); this.stops = 0; mock.tracks.push(this); }
      stop() { this.stops++; }
    }
    class Recorder {
      static isTypeSupported(type) { return type === 'audio/webm;codecs=opus'; }
      constructor(stream, options) {
        this.stream = stream; this.mimeType = options.mimeType;
        this.state = 'inactive'; this.starts = 0; this.stops = 0;
        mock.recorders.push(this);
      }
      start(interval) { this.starts++; this.interval = interval; this.state = 'recording'; }
      stop() {
        this.stops++; this.state = 'inactive';
        queueMicrotask(() => {
          this.ondataavailable?.({data: new Blob([new Uint8Array(mock.bytes)], {type: this.mimeType})});
          this.onstop?.();
        });
      }
    }
    window.MediaRecorder = Recorder;
    window.AudioContext = undefined;
    window.webkitAudioContext = undefined;
    Object.defineProperty(navigator, 'mediaDevices', {configurable: true, value: {
      getUserMedia(options) {
        mock.lastMediaOptions = options;
        return new Promise((resolve, reject) => mock.pending.push({resolve, reject}));
      },
    }});
    mock.allow = () => {
      const track = new Track();
      mock.pending.shift().resolve({getTracks: () => [track], getAudioTracks: () => [track]});
    };
  });
});

async function harness(page) {
  await page.goto('/dictation-test-harness');
  await page.evaluate(async () => {
    const {createDictation} = await import('/assets/dictation.js');
    const mock = window.__dictation;
    mock.voice = createDictation({
      change: state => mock.changes.push(state),
      draft: text => { mock.drafts.push(text); mock.currentDraft = text; },
      transcribe: (body, {signal}) => {
        mock.requests.push({body, signal});
        if (mock.error) return Promise.reject(mock.error);
        return mock.defer ? new Promise(resolve => mock.deferred.push(resolve)) : Promise.resolve({text: mock.transcript});
      },
    });
    mock.start = (options = {consent: true, language: 'en'}) => { mock.startResult = mock.voice.start(options); };
  });
}

async function start(page, options) {
  await page.evaluate(options => { __dictation.start(options); __dictation.allow(); }, options);
  expect(await page.evaluate(() => __dictation.startResult)).toBe(true);
  await expect.poll(() => page.evaluate(() => __dictation.voice.state.phase)).toBe('recording');
}

test('dictation requires consent before requesting a microphone or transcription', async ({page}) => {
  await harness(page);
  expect(await page.evaluate(() => __dictation.voice.start({consent: false}))).toBe(false);
  const state = await page.evaluate(() => ({...__dictation.voice.state, pending: __dictation.pending.length, requests: __dictation.requests.length}));
  expect(state.phase).toBe('error');
  expect(state.message).toContain('Allow audio transcription');
  expect(state.active).toBe(false);
  expect(state.pending).toBe(0);
  expect(state.requests).toBe(0);
  expect(await page.evaluate(() => __dictation.currentDraft)).toBe('Existing typed draft');
});

test('permission denial keeps the original draft and allows an explicit retry', async ({page}) => {
  await harness(page);
  await page.evaluate(() => {
    __dictation.start();
    __dictation.pending.shift().reject(new DOMException('private browser detail', 'NotAllowedError'));
  });
  expect(await page.evaluate(() => __dictation.startResult)).toBe(false);
  expect(await page.evaluate(() => __dictation.voice.state.phase)).toBe('error');
  expect(await page.evaluate(() => __dictation.voice.state.message)).toContain('Microphone permission was denied');
  expect(await page.evaluate(() => JSON.stringify(__dictation.changes))).not.toContain('private browser detail');
  expect(await page.evaluate(() => __dictation.requests.length)).toBe(0);
  expect(await page.evaluate(() => __dictation.currentDraft)).toBe('Existing typed draft');
  await start(page);
  await page.evaluate(() => __dictation.voice.cancel());
  expect(await page.evaluate(() => __dictation.tracks[0].stops)).toBe(1);
});

test('cancelled pending permission stops a late microphone without starting recording', async ({page}) => {
  await harness(page);
  await page.evaluate(() => { __dictation.start(); __dictation.voice.cancel(); __dictation.allow(); });
  expect(await page.evaluate(() => __dictation.startResult)).toBe(false);
  expect(await page.evaluate(() => __dictation.tracks[0].stops)).toBe(1);
  expect(await page.evaluate(() => __dictation.recorders.length)).toBe(0);
  expect(await page.evaluate(() => __dictation.requests.length)).toBe(0);
  expect(await page.evaluate(() => __dictation.voice.active)).toBe(false);
  expect(await page.evaluate(() => __dictation.currentDraft)).toBe('Existing typed draft');
});

test('Done releases the microphone and returns only an editable transcription draft', async ({page}) => {
  await harness(page);
  await page.evaluate(() => { __dictation.defer = true; });
  await start(page, {consent: true, language: 'ta'});
  expect(await page.evaluate(() => __dictation.requests.length)).toBe(0);
  await page.evaluate(() => __dictation.voice.finish());
  await expect.poll(() => page.evaluate(() => __dictation.requests.length)).toBe(1);
  expect(await page.evaluate(() => __dictation.tracks[0].stops)).toBe(1);
  expect(await page.evaluate(() => __dictation.recorders[0].stops)).toBe(1);
  expect(await page.evaluate(() => __dictation.voice.state.phase)).toBe('transcribing');
  expect(await page.evaluate(() => __dictation.drafts)).toEqual([]);
  const request = await page.evaluate(() => __dictation.requests[0].body);
  expect(request.language).toBe('ta');
  expect(request.mime).toBe('audio/webm;codecs=opus');
  expect([...Buffer.from(request.audio, 'base64')]).toEqual(await page.evaluate(() => __dictation.bytes));
  expect(Object.keys(request).sort()).toEqual(['audio', 'language', 'mime']);
  await page.evaluate(() => __dictation.deferred.shift()({text: '  தமிழில் ஒரு சோதனை  '}));
  await expect.poll(() => page.evaluate(() => __dictation.currentDraft)).toBe('தமிழில் ஒரு சோதனை');
  expect(await page.evaluate(() => __dictation.drafts)).toEqual(['தமிழில் ஒரு சோதனை']);
  expect(await page.evaluate(() => __dictation.voice.active)).toBe(false);
  expect(await page.evaluate(() => __dictation.voice.state.message)).toContain('Review it, then Send');
});

test('cancel during transcription aborts the request and ignores a late transcript', async ({page}) => {
  await harness(page);
  await page.evaluate(() => { __dictation.defer = true; });
  await start(page);
  await page.evaluate(() => __dictation.voice.finish());
  await expect.poll(() => page.evaluate(() => __dictation.requests.length)).toBe(1);
  await page.evaluate(() => { __dictation.voice.cancel(); __dictation.deferred.shift()({text: 'Must not overwrite my draft'}); });
  expect(await page.evaluate(() => __dictation.requests[0].signal.aborted)).toBe(true);
  expect(await page.evaluate(() => __dictation.voice.active)).toBe(false);
  expect(await page.evaluate(() => __dictation.drafts)).toEqual([]);
  expect(await page.evaluate(() => __dictation.currentDraft)).toBe('Existing typed draft');
  expect(await page.evaluate(() => __dictation.voice.state.message)).toContain('Recording cancelled');
});

test('sanitized backend credit guidance is shown without leaking the raw error', async ({page}) => {
  await harness(page);
  await page.evaluate(() => {
    __dictation.error = Object.assign(new Error('raw provider payload fictional-secret'), {
      userMessage: 'OpenAI prepaid credit balance is exhausted. Add API credits, then try again.',
    });
  });
  await start(page);
  await page.evaluate(() => __dictation.voice.finish());
  await expect.poll(() => page.evaluate(() => __dictation.voice.state.phase)).toBe('error');
  expect(await page.evaluate(() => __dictation.voice.state.message)).toContain('prepaid credit balance is exhausted');
  expect(await page.evaluate(() => JSON.stringify(__dictation.changes))).not.toContain('fictional-secret');
  expect(await page.evaluate(() => __dictation.tracks[0].stops)).toBeGreaterThan(0);
  expect(await page.evaluate(() => __dictation.voice.active)).toBe(false);
  expect(await page.evaluate(() => __dictation.currentDraft)).toBe('Existing typed draft');
});

test('page hiding and pagehide both discard recordings and stop their microphones', async ({page}) => {
  await harness(page);
  for (const [index, event] of ['visibilitychange', 'pagehide'].entries()) {
    await page.evaluate(() => Object.defineProperty(document, 'hidden', {configurable: true, get: () => false}));
    await start(page);
    await page.evaluate(event => {
      if (event === 'visibilitychange') {
        Object.defineProperty(document, 'hidden', {configurable: true, get: () => true});
        document.dispatchEvent(new Event(event));
      } else window.dispatchEvent(new Event(event));
    }, event);
    expect(await page.evaluate(index => __dictation.tracks[index].stops, index)).toBe(1);
    expect(await page.evaluate(() => __dictation.voice.active)).toBe(false);
    expect(await page.evaluate(() => __dictation.requests.length)).toBe(0);
    expect(await page.evaluate(() => __dictation.currentDraft)).toBe('Existing typed draft');
  }
});

test('empty recordings and disconnected devices never create a transcription request', async ({page}) => {
  await harness(page);
  await start(page);
  await page.evaluate(() => { __dictation.bytes = []; __dictation.voice.finish(); });
  await expect.poll(() => page.evaluate(() => __dictation.voice.state.phase)).toBe('error');
  expect(await page.evaluate(() => __dictation.voice.state.message)).toContain('No audio was captured');
  expect(await page.evaluate(() => __dictation.requests.length)).toBe(0);
  await start(page);
  await page.evaluate(() => __dictation.tracks[1].dispatchEvent(new Event('ended')));
  expect(await page.evaluate(() => __dictation.voice.state.message)).toContain('microphone disconnected');
  expect(await page.evaluate(() => __dictation.voice.active)).toBe(false);
  expect(await page.evaluate(() => __dictation.requests.length)).toBe(0);
});
