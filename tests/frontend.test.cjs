const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = path.join(__dirname, '../frontend');

function page(extract, language = 'en', options = {}) {
  const all = [];
  function element() {
    const node = {
      value: '', textContent: '', hidden: false, files: [], handlers: {}, dataset: {},
      children: [], className: '', style: {}, attributes: {},
      set innerHTML(value) { this.children = []; },
      addEventListener(name, callback) { this.handlers[name] = callback; },
      setAttribute(name, value) { this.attributes[name] = value; },
      removeAttribute(name) { delete this.attributes[name]; },
      append(...children) { children.forEach(child => child.parent = this); this.children.push(...children); },
      closest(selector) { return this.className.split(' ').includes(selector.slice(1)) ? this : this.parent?.closest(selector); },
      querySelector(selector) { return this.children.find(child => child.className?.split(' ').includes(selector.slice(1))); },
      scrollIntoView() {}, focus() {},
      classList: { add() {}, remove() {}, toggle() {} },
    };
    all.push(node);
    return node;
  }
  const html = fs.readFileSync(path.join(source, 'index.html'), 'utf8');
  const elements = new Map([...html.matchAll(/id="([^"]+)"/g)].map(match => [match[1], element()]));
  elements.get('reading-view').hidden = true;
  const stages = [element(), element(), element()];
  const document = {
    documentElement: { lang: language, style: { setProperty() {} } },
    getElementById(id) { assert(elements.has(id), 'Missing element in original HTML: ' + id); return elements.get(id); },
    querySelectorAll(selector) {
      if (selector === '#extract-loading li') return stages;
      if (selector.startsWith('.')) return all.filter(node => node.className.split(' ').includes(selector.slice(1)));
      return [];
    },
    createElement: element,
    createTextNode: text => ({ textContent: text }),
    addEventListener() {},
  };
  const context = {
    document, API: { extract, closeSession: async () => {}, chat: options.chat, health: async () => ({ status: 'ok' }) },
    AbortController, crypto: require('node:crypto').webcrypto,
    URL: { createObjectURL: () => 'blob:test', revokeObjectURL() {} },
    navigator: { language }, localStorage: { getItem: () => null, setItem() {} },
    matchMedia: () => ({ matches: false }),
    Speech: { supported: false, paused: false, stop() {}, ...options.speech },
    console: { error() {} }, addEventListener() {},
    setInterval: () => 1, clearInterval() {}, setTimeout: callback => setImmediate(callback), clearTimeout: clearImmediate,
  };
  context.window = context;
  vm.createContext(context);
  for (const file of ['config.js', 'i18n.js', 'app.js']) {
    vm.runInContext(fs.readFileSync(path.join(source, file), 'utf8'), context);
  }
  return {
    get: id => document.getElementById(id),
    upload(file) { elements.get('file-input').handlers.change({ target: { files: [file], value: '' } }); },
    reset() { elements.get('new-session').handlers.click(); },
    send(text) { elements.get('chat-input').value = text; elements.get('chat-form').handlers.submit({ preventDefault() {} }); },
  };
}
const photo = { name: 'photo.png', type: 'image/png', size: 128 };
const tick = async () => { for (let i = 0; i < 4; i++) await new Promise(resolve => setImmediate(resolve)); };

test('original upload control displays real text and summary in the original text box', async () => {
  let received;
  const ui = page(async file => { received = file; return { text: 'Avis\nEntrée fermée', summary: 'A closed entrance.' }; });
  ui.upload(photo);
  await tick();
  assert.equal(received, photo);
  assert.equal(ui.get('extracted-text').value, 'Extracted text:\nAvis\nEntrée fermée\n\nSummary of the image:\nA closed entrance.');
  assert.equal(ui.get('extracted-text').disabled, false);
  assert.equal(ui.get('play-btn').disabled, false);
});

test('a second image is blocked until New session; stale results cannot cross sessions', async () => {
  const pending = [];
  const ui = page((file, session, signal) => new Promise(resolve => pending.push({ resolve, signal })));
  ui.upload(photo);
  ui.upload({ ...photo, name: 'second.png' });
  assert.equal(pending.length, 1);
  assert.match(ui.get('extract-error').textContent, /New session/);
  ui.reset();
  ui.upload({ ...photo, name: 'second.png' });
  assert(pending[0].signal.aborted);
  pending[1].resolve({ text: 'Second', summary: 'Second summary' });
  await tick();
  pending[0].resolve({ text: 'First', summary: 'First summary' });
  await tick();
  assert.match(ui.get('extracted-text').value, /Second summary/);
  assert.doesNotMatch(ui.get('extracted-text').value, /First/);
});

test('the original New session button cancels an in-flight extraction', async () => {
  let resolve, signal;
  const ui = page((file, session, currentSignal) => {
    signal = currentSignal;
    return new Promise(done => { resolve = done; });
  });
  ui.upload(photo);
  ui.reset();
  assert(signal.aborted);
  resolve({ text: 'Old result', summary: 'Old summary' });
  await tick();
  assert.equal(ui.get('extracted-text').value, '');
  assert.equal(ui.get('extract-card').dataset.state, 'empty');
});

test('failed extraction clears old text and uses the original error area', async () => {
  let fail = false;
  const ui = page(async () => {
    if (fail) throw new Error('Connection failed');
    return { text: 'Old text', summary: 'Old summary' };
  });
  ui.upload(photo);
  await tick();
  fail = true;
  ui.reset();
  ui.upload(photo);
  await tick();
  assert.equal(ui.get('extracted-text').value, '');
  assert.equal(ui.get('extract-error').hidden, false);
  assert.equal(ui.get('extract-card').dataset.state, 'empty');
});

test('symbol-only results keep the summary and original read-aloud controls', async () => {
  const ui = page(async () => ({ text: '', summary: 'A no-entry symbol.' }));
  ui.upload(photo);
  await tick();
  assert.match(ui.get('extracted-text').value, /\[No text extracted\]/);
  assert.match(ui.get('extracted-text').value, /A no-entry symbol\./);
  assert.equal(ui.get('play-btn').disabled, false);
});

test('the original French interface uses French headings for the result', async () => {
  const ui = page(async () => ({ text: 'Entrée', summary: 'An entrance sign.' }), 'fr');
  ui.upload(photo);
  await tick();
  assert.match(ui.get('extracted-text').value, /^Texte extrait:/);
  assert.match(ui.get('extracted-text').value, /Résumé de l'image:/);
});

test('API sends the single image to the working multipart endpoint', async () => {
  let request;
  const window = { APP_CONFIG: { API_BASE_URL: '' } };
  vm.runInNewContext(fs.readFileSync(path.join(source, 'api.js'), 'utf8'), {
    window, FormData,
    fetch: async (url, options) => {
      request = { url, options };
      return { ok: true, json: async () => ({ text: 'Text', summary: 'Summary', language: 'en', session_id: 'local-session' }) };
    },
  });
  const image = new File(['image bytes'], 'photo.png', { type: 'image/png' });
  const signal = new AbortController().signal;
  await window.API.extract(image, 'local-session', signal);
  assert.equal(request.url, '/api/extract');
  assert.equal(request.options.method, 'POST');
  assert.equal(request.options.body.get('image').name, 'photo.png');
  assert.equal(request.options.body.get('session_id'), 'local-session');
  assert.equal(request.options.signal, signal);
});

test('API sends a follow-up to the backend without trusting client history', async () => {
  let request;
  const window = { APP_CONFIG: { API_BASE_URL: '' } };
  vm.runInNewContext(fs.readFileSync(path.join(source, 'api.js'), 'utf8'), {
    window, fetch: async (url, options) => { request = { url, options }; return { ok: true, json: async () => ({ reply: 'Real model reply' }) }; },
  });
  const signal = new AbortController().signal;
  const response = await window.API.chat({ sessionId: 'session', message: 'When?', contextText: 'The displayed text', language: 'en', history: [{ role: 'system', content: 'Fake' }] }, signal);
  assert.equal(response.reply, 'Real model reply');
  assert.equal(request.url, '/api/chat');
  assert.equal(request.options.signal, signal);
  assert.deepEqual(JSON.parse(request.options.body), { session_id: 'session', message: 'When?', context_text: 'The displayed text', language: 'en' });
});

test('chat requires successful extraction and displays returned answers in the existing panel', async () => {
  const calls = [];
  const ui = page(async () => ({ text: 'Open 9 am', summary: 'Opening time' }), 'en', {
    chat: async data => { calls.push(data); return { reply: 'At 9 am.', language: 'en' }; },
  });
  ui.send('When?'); await tick();
  assert.equal(calls.length, 0);
  ui.upload(photo); await tick();
  ui.send('When?'); await tick();
  assert.equal(calls.length, 1);
  assert.equal(calls[0].contextText, '', 'the model already has the unedited reading');
  assert.equal(ui.get('messages').children.at(-1).querySelector('.msg-body').textContent, 'At 9 am.');
  assert.equal(ui.get('send-btn').disabled, false);
  const edited = ui.get('extracted-text').value.replace('9 am', '10 am');
  ui.get('extracted-text').handlers.input({ target: { value: edited } });
  ui.send('When now?'); await tick();
  assert.equal(calls[1].contextText, edited, 'user corrections are sent');
});

test('New session aborts pending chat and prevents an old reply or autoplay', async () => {
  let resolve, signal, spoken = 0;
  const ui = page(async () => ({ text: 'Sign', summary: 'Old image' }), 'en', {
    chat: (data, currentSignal) => { signal = currentSignal; return new Promise(done => { resolve = done; }); },
    speech: { speak() { spoken++; } },
  });
  ui.get('auto-read').checked = true;
  ui.upload(photo); await tick();
  ui.send('Explain');
  ui.reset();
  assert(signal.aborted);
  resolve({ reply: 'Old reply', language: 'en' }); await tick();
  assert.equal(spoken, 0);
  assert.equal(ui.get('messages').children.length, 1);
  assert.equal(ui.get('send-btn').disabled, false);
});

test('microphone transcript follows the same chat path and reset cancels recording', async () => {
  let callbacks, cancelled = 0;
  const calls = [];
  const ui = page(async () => ({ text: 'Open 9 am', summary: 'Hours' }), 'en', {
    chat: async data => { calls.push(data); return { reply: 'At 9 am.' }; },
    speech: { canListen: true, listen(lang, handlers) { callbacks = handlers; const stop = () => {}; stop.abort = () => cancelled++; return stop; } },
  });
  ui.upload(photo); await tick();
  ui.get('mic-btn').handlers.click();
  ui.send('Do not send during recording'); await tick();
  assert.equal(calls.length, 0);
  callbacks.onResult('When does it open?'); callbacks.onEnd(); await tick();
  assert.equal(calls[0].message, 'When does it open?');
  ui.get('mic-btn').handlers.click();
  const stale = callbacks;
  ui.reset();
  assert.equal(cancelled, 1);
  stale.onResult('Old recording'); await tick();
  assert.equal(calls.length, 1);
});

test('speech API refuses a remote backend instead of sending audio off-device', async () => {
  let fetched = false;
  const window = { APP_CONFIG: { API_BASE_URL: 'https://remote.example' }, location: { href: 'http://localhost:8000/' } };
  vm.runInNewContext(fs.readFileSync(path.join(source, 'api.js'), 'utf8'), {
    window, URL, FormData, fetch: async () => { fetched = true; },
  });
  await assert.rejects(window.API.synthesize('Private text', 'en'), /localhost/);
  await assert.rejects(window.API.transcribe(new Blob(['Private recording']), 'en'), /localhost/);
  assert.equal(fetched, false);
});

for (const language of ['en', 'fr', 'mixed', 'none']) {
  test('language dropdown follows the image: ' + language, async () => {
    const ui = page(async () => ({ text: language === 'none' ? '' : 'Document text', summary: 'English summary', language }), 'en');
    assert.equal(ui.get('lang-select').value, 'none');
    ui.upload(photo); await tick();
    assert.equal(ui.get('lang-select').value, language);
    ui.reset();
    assert.equal(ui.get('lang-select').value, 'none');
  });
}

test('chat messages use the name Lumen in both interface languages', async () => {
  for (const language of ['en', 'fr']) {
    const ui = page(async () => ({}), language);
    assert.equal(ui.get('messages').children[0].querySelector('.msg-who').textContent, 'Lumen');
  }
});

test('read-aloud keeps the document language separate from its summary', async () => {
  let request;
  const ui = page(async () => ({ text: 'Sortie.', summary: 'An exit sign.', language: 'fr', summary_language: 'en' }), 'en', {
    speech: { speak(text, language, options) { request = { text, language, options }; } },
  });
  ui.upload(photo); await tick();
  ui.get('play-btn').handlers.click();
  assert.equal(request.language, 'fr');
  assert.equal(request.options.languageRanges.length, 2);
  assert.equal(request.options.languageRanges[0].language, 'fr');
  assert.equal(request.options.languageRanges[1].language, 'en');
  assert.equal(request.text.slice(request.options.languageRanges[0].start, request.options.languageRanges[0].end), 'Sortie.');
  assert.equal(request.text.slice(request.options.languageRanges[1].start), 'An exit sign.');
  ui.get('stop-btn').handlers.click();
  ui.get('extracted-text').handlers.input({ target: { value: 'Edited text' } });
  ui.get('play-btn').handlers.click();
  assert.equal(request.options.languageRanges, null, 'Manual edits cannot use stale character ranges');
});

test('source and reply audio are prepared as soon as their text becomes available', async () => {
  const prepared = [];
  let cleared = 0, unlocked = 0;
  const ui = page(async () => ({ text: 'Sortie.', summary: 'An exit sign.', language: 'fr', summary_language: 'en' }), 'en', {
    chat: async () => ({ reply: 'Use this exit.', language: 'en' }),
    speech: { prepare(text, lang, options) { prepared.push({ text, lang, options }); }, clear() { cleared++; }, unlock() { unlocked++; } },
  });
  assert.equal(prepared.length, 0, 'The welcome message must not delay document audio');
  ui.upload(photo); await tick();
  const report = prepared.find(item => item.text.includes('An exit sign.'));
  assert.equal(report.lang, 'fr');
  assert.equal(report.options.languageRanges.at(-1).language, 'en');
  ui.send('Where should I go?'); await tick();
  assert.equal(unlocked, 1);
  assert(prepared.some(item => item.text === 'Use this exit.'));
  ui.reset();
  assert.equal(cleared, 2);
});

test('clicking Read aloud twice during loading cannot silently pause pending speech', async () => {
  let paused = 0, spoken = 0;
  const ui = page(async () => ({ text: 'Text', summary: 'Summary', language: 'en' }), 'en', {
    speech: { loading: true, speak() { spoken++; }, pause() { paused++; } },
  });
  ui.upload(photo); await tick();
  ui.get('play-btn').handlers.click();
  ui.get('play-btn').handlers.click();
  assert.equal(spoken, 1);
  assert.equal(paused, 0);
  assert.equal(ui.get('play-label').textContent, 'Preparing audio…');
});

test('editing a report recalculates spoken content offsets and still skips its headings', async () => {
  let request;
  const ui = page(async () => ({ text: 'Sortie.', summary: 'An exit sign.', language: 'fr', summary_language: 'en' }), 'en', {
    speech: { speak(text, language, options) { request = { text, language, options }; } },
  });
  ui.upload(photo); await tick();
  const corrected = ui.get('extracted-text').value.replace('Sortie.', 'Veuillez utiliser cette sortie.');
  ui.get('extracted-text').handlers.input({ target: { value: corrected } });
  ui.get('play-btn').handlers.click();
  const ranges = request.options.languageRanges;
  assert.equal(ranges.length, 2);
  assert.equal(request.text.slice(ranges[0].start, ranges[0].end), 'Veuillez utiliser cette sortie.');
  assert.equal(request.text.slice(ranges[1].start, ranges[1].end), 'An exit sign.');
});

test('background audio preparation stays hidden until Read aloud is pressed', async () => {
  let ready, prepared = 0;
  const preparation = new Promise(resolve => ready = resolve);
  const ui = page(async () => ({ text: 'Sortie.', summary: 'An exit sign.', language: 'fr', summary_language: 'en' }), 'en', {
    speech: { prepare() { prepared++; return preparation; } },
  });
  ui.upload(photo); await tick();
  assert.ok(prepared >= 1);
  assert.equal(ui.get('play-label').textContent, 'Read aloud');
  assert.notEqual(ui.get('play-btn').attributes['aria-busy'], 'true');
  ready(); await tick();
  assert.equal(ui.get('play-label').textContent, 'Read aloud');
});

test('confidence beside step 02 updates from the model response and clears on New session', async () => {
  let finish;
  const ui = page(() => new Promise(resolve => finish = resolve));
  assert.equal(ui.get('confidence').textContent, 'Confidence (est.): —');
  ui.upload(photo);
  assert.match(ui.get('confidence').textContent, /Assessing/);
  finish({ text: 'Open at nine.', summary: 'Opening time.', language: 'en',
    confidence: { text: 96, summary: 91, method: 'model_estimate' } }); await tick();
  assert.equal(ui.get('confidence').textContent, 'Confidence (est.): 91%');
  assert.match(ui.get('confidence').title, /Text 96% · Summary 91%/);
  assert.match(ui.get('confidence').title, /not verified accuracy/);
  assert(!ui.get('extracted-text').value.includes('96%'), 'Confidence is separate from document/speech content');
  ui.reset();
  assert(!ui.get('confidence').textContent.includes('96%'));
  assert.equal(ui.get('confidence').textContent, 'Confidence (est.): —');
});

test('missing estimates and a real zero are distinct, including in French', async () => {
  const ui = page(async () => ({ text: '', summary: 'A symbol.', language: 'none',
    confidence: { text: null, summary: 0, method: 'model_estimate' } }), 'fr');
  ui.upload(photo); await tick();
  assert.equal(ui.get('confidence').textContent, 'Confiance (est.): —');
  assert.match(ui.get('confidence').title, /Texte — · Résumé 0%/);
});

test('confidence does not continue to describe edited text and returns on an exact revert', async () => {
  const ui = page(async () => ({ text: 'Open.', summary: 'A notice.', language: 'en',
    confidence: { text: 90, summary: 80, method: 'model_estimate' } }));
  ui.upload(photo); await tick();
  const original = ui.get('extracted-text').value;
  ui.get('extracted-text').handlers.input({ target: { value: original + ' edited' } });
  assert.match(ui.get('confidence').textContent, /Edited — not reassessed/);
  assert(!ui.get('confidence').textContent.includes('90%'));
  ui.get('extracted-text').handlers.input({ target: { value: original } });
  assert.equal(ui.get('confidence').textContent, 'Confidence (est.): 80%');
});

test('a failed new extraction never retains the previous image confidence', async () => {
  let attempt = 0;
  const ui = page(async () => {
    if (attempt++) throw new Error('Model unavailable');
    return { text: 'Open.', summary: 'A notice.', language: 'en', confidence: { text: 90, summary: 80, method: 'model_estimate' } };
  });
  ui.upload(photo); await tick(); ui.reset(); ui.upload(photo); await tick();
  assert(!ui.get('confidence').textContent.includes('90%'));
  assert.equal(ui.get('confidence').textContent, 'Confidence (est.): —');
});

test('API rejects invalid confidence instead of displaying a fabricated percentage', async () => {
  for (const confidence of [null, { text: '95%', summary: 80, method: 'model_estimate' },
    { text: 101, summary: 80, method: 'model_estimate' }, { text: true, summary: 80, method: 'model_estimate' },
    { text: 90, summary: 80, method: 'verified_accuracy' }]) {
    const window = { APP_CONFIG: { API_BASE_URL: '' } };
    vm.runInNewContext(fs.readFileSync(path.join(source, 'api.js'), 'utf8'), { window, FormData,
      fetch: async () => ({ ok: true, json: async () => ({ text: 'Text', summary: 'Summary', language: 'en', session_id: 'session', confidence }) }),
    });
    await assert.rejects(window.API.extract(new File(['x'], 'image.png'), 'session'), /invalid confidence/);
  }
});

test('confidence never renders NaN, Infinity or coerced object/string percentages', async () => {
  for (const confidence of [NaN, 0.95, {}, { text: NaN, summary: 90, method: 'model_estimate' },
    { text: 90, summary: Infinity, method: 'model_estimate' }, { text: '95%', summary: 90, method: 'model_estimate' },
    { text: { value: 95 }, summary: 90, method: 'model_estimate' }]) {
    const ui = page(async () => ({ text: 'Open.', summary: 'A notice.', language: 'en', confidence }));
    ui.upload(photo); await tick();
    assert.equal(ui.get('confidence').textContent, 'Confidence (est.): —');
    assert(!/NaN|Infinity/.test(ui.get('confidence').attributes['aria-label']));
  }
});

test('zero overall confidence remains a numeric zero rather than becoming unavailable', async () => {
  const ui = page(async () => ({ text: 'Open.', summary: 'A notice.', language: 'en',
    confidence: { text: 95, summary: 0, method: 'model_estimate' } }));
  ui.upload(photo); await tick();
  assert.equal(ui.get('confidence').textContent, 'Confidence (est.): 0%');
});

// ---------- live results (streamed model output) ----------
// A response like the server's: one JSON object per line, delivered in small
// chunks that split lines and multi-byte characters.
function liveResponse(lines, chunkSize = 7) {
  const bytes = new TextEncoder().encode(lines.map(line => JSON.stringify(line) + '\n').join(''));
  let offset = 0;
  return {
    ok: true,
    headers: { get: name => (name.toLowerCase() === 'content-type' ? 'application/x-ndjson' : null) },
    body: { getReader: () => ({ read: async () => {
      if (offset >= bytes.length) return { done: true };
      offset += chunkSize;
      return { done: false, value: bytes.slice(offset - chunkSize, offset) };
    } }) },
  };
}
function liveApi(lines, requests = []) {
  const window = { APP_CONFIG: { API_BASE_URL: '' } };
  vm.runInNewContext(fs.readFileSync(path.join(source, 'api.js'), 'utf8'), {
    window, FormData, TextDecoder,
    fetch: async (url, options) => { requests.push({ url, options }); return liveResponse(lines); },
  });
  return window.API;
}
const plain = value => JSON.parse(JSON.stringify(value));

test('API shows the reading while it is written and returns the final result', async () => {
  const requests = [], seen = [];
  const api = liveApi([
    { partial: { text: 'Entrée' } },
    { partial: { text: 'Entrée fermée', summary: 'A cl' } },
    { result: { text: 'Entrée fermée', summary: 'A closed entrance.', language: 'fr', session_id: 's',
                confidence: { text: 90, summary: 80, method: 'model_estimate' } } },
  ], requests);
  const result = await api.extract(new File(['x'], 'p.png', { type: 'image/png' }), 's', undefined, p => seen.push(p));
  assert.equal(requests[0].options.headers.Accept, 'application/x-ndjson');
  assert.deepEqual(plain(seen), [{ text: 'Entrée' }, { text: 'Entrée fermée', summary: 'A cl' }]);
  assert.equal(result.summary, 'A closed entrance.');
  assert.equal(result.language, 'fr');
});

test('API turns a streamed failure into an error with its status', async () => {
  const api = liveApi([{ partial: { text: 'Av' } }, { error: 'Cannot reach the local model.', status: 503 }]);
  await assert.rejects(api.extract(new File(['x'], 'p.png', { type: 'image/png' }), 's'),
    error => error.message === 'Cannot reach the local model.' && error.status === 503);
});

test('API streams chat answers', async () => {
  const seen = [];
  const api = liveApi([{ partial: 'It op' }, { partial: 'It opens at 9 am.' }, { reply: 'It opens at 9 am.', language: 'en' }]);
  const result = await api.chat({ sessionId: 's', message: 'When?', contextText: '', language: 'en' }, undefined, t => seen.push(t));
  assert.deepEqual(seen, ['It op', 'It opens at 9 am.']);
  assert.equal(result.reply, 'It opens at 9 am.');
});

test('the reading appears in the text box while the model writes it', async () => {
  let progress, resolve;
  const ui = page((file, session, signal, onProgress) => { progress = onProgress; return new Promise(done => { resolve = done; }); });
  ui.upload(photo);
  await tick();
  assert.equal(ui.get('extracted-text').hidden, true, 'progress steps until the first words');
  progress({ text: 'Avis' });
  assert.equal(ui.get('extracted-text').hidden, false);
  assert.equal(ui.get('extract-loading').hidden, true);
  assert.equal(ui.get('extracted-text').value, 'Extracted text:\nAvis');
  assert.equal(ui.get('extracted-text').disabled, true, 'read-only until complete');
  assert.equal(ui.get('play-btn').disabled, true);
  progress({ text: 'Avis\nEntrée fermée', summary: 'A closed' });
  assert.equal(ui.get('extracted-text').value, 'Extracted text:\nAvis\nEntrée fermée\n\nSummary of the image:\nA closed');
  progress({});  // the server retried: start over
  assert.equal(ui.get('extracted-text').value, '');
  assert.equal(ui.get('extract-loading').hidden, false);
  resolve({ text: 'Avis\nEntrée fermée', summary: 'A closed entrance.' });
  await tick();
  assert.equal(ui.get('extracted-text').value, 'Extracted text:\nAvis\nEntrée fermée\n\nSummary of the image:\nA closed entrance.');
  assert.equal(ui.get('extracted-text').disabled, false);
  assert.equal(ui.get('play-btn').disabled, false);
});

test('a failed or abandoned reading never leaves partial text behind', async () => {
  let progress, reject;
  const ui = page((file, session, signal, onProgress) => {
    progress = onProgress;
    return new Promise((_, fail) => { reject = fail; });
  });
  ui.upload(photo);
  await tick();
  progress({ text: 'Half a sen' });
  reject(new Error('The model could not process this image.'));
  await tick();
  assert.equal(ui.get('extracted-text').value, '');
  assert.equal(ui.get('extract-card').dataset.state, 'empty');
  ui.upload(photo);
  await tick();
  const late = progress;
  ui.reset();
  late({ text: 'Words from the old image' });
  assert.equal(ui.get('extracted-text').value, '');
});

test('chat answers appear while they are written and get their speaker only when complete', async () => {
  let progress, resolve;
  const ui = page(async () => ({ text: 'Open 9 am', summary: 'Opening time' }), 'en', {
    chat: (data, signal, onProgress) => { progress = onProgress; return new Promise(done => { resolve = done; }); },
  });
  ui.upload(photo);
  await tick();
  ui.send('When?');
  await tick();
  const bubble = ui.get('messages').children.at(-1);
  progress('It opens');
  assert.equal(bubble.querySelector('.msg-body').textContent, 'It opens');
  progress('It opens at 9 am.');
  assert.equal(bubble.querySelector('.msg-body').textContent, 'It opens at 9 am.');
  assert.equal(ui.get('send-btn').disabled, true, 'still busy until the answer is complete');
  assert(!bubble.children.some(child => child.className === 'msg-speak'));
  resolve({ reply: 'It opens at 9 am.', language: 'en' });
  await tick();
  assert.equal(bubble.querySelector('.msg-body').textContent, 'It opens at 9 am.');
  assert.equal(ui.get('send-btn').disabled, false);
  assert(bubble.children.some(child => child.className === 'msg-speak'));
});
