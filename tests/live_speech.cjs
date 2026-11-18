// Opt-in test against a running local app: node tests/live_speech.cjs [base URL]
// Measures real generation plus the JS handoff of cached WAV to a simulated
// audio element. Physical/browser playback latency is not measured here.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const base = process.argv[2] || 'http://127.0.0.1:8000';
const calls = [];
const tick = () => new Promise(resolve => setImmediate(resolve));
class Audio {
  play() { this.onplay?.(); return Promise.resolve(); }
  pause() {}
  removeAttribute() {}
  load() {}
}
async function synthesize(text, language, signal) {
  const response = await fetch(base + '/api/speech/synthesize', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text, language }), signal,
  });
  assert.equal(response.status, 200, await response.clone().text());
  const blob = await response.blob();
  const bytes = Buffer.from(await blob.arrayBuffer());
  assert.equal(bytes.toString('ascii', 0, 4), 'RIFF');
  assert(bytes.length > 1000);
  return blob;
}
const context = { Audio, URL, Blob, AbortController, navigator: {}, setTimeout, clearTimeout,
  API: { synthesize: (...args) => { const task = synthesize(...args); calls.push(task); return task; } } };
context.window = context;
vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../frontend/speech.js'), 'utf8'), context);

(async () => {
  for (const [language, text] of [['en', 'The building opens at nine thirty.'], ['fr', 'Le bâtiment ouvre à neuf heures trente.']]) {
    const start = performance.now();
    context.Speech.prepare(text, language);
    await tick(); await calls.at(-1); await tick();
    const preparedMs = performance.now() - start;
    const before = calls.length;
    const click = performance.now();
    await new Promise((resolve, reject) => context.Speech.speak(text, language, { onStart: resolve, onError: reject }));
    console.log(JSON.stringify({ language, generationMs: Math.round(preparedMs), cachedAudioHandoffMs: Math.round(performance.now() - click), additionalGenerationRequests: calls.length - before }));
    assert.equal(calls.length, before);
    context.Speech.stop();
  }
  context.Speech.clear();
  await Promise.all([synthesize('One request is speaking.', 'en'), synthesize('The second request waits instead of failing.', 'en')]);
  console.log('Overlapping speech requests both returned valid audio.');
})().catch(error => { console.error(error); process.exitCode = 1; });
