// Local HTTP + real generated WAV durations, with a simulated audio element.
// Reports full preparation and verifies one continuous track, with no synthesis
// after playback starts. Does not test physical speakers.
// Run: node tests/live_document_speech.cjs [http://127.0.0.1:8000] [extraction.json]
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const base = process.argv[2] || 'http://127.0.0.1:8000';
const calls = [];
let endedAt = null, waits = [], voiceStarts = 0, callsAtStart = 0;
class Audio {
  async play() {
    if (!this.src?.startsWith('blob:')) return;
    const bytes = await (await fetch(this.src)).arrayBuffer();
    const wav = new DataView(bytes);
    assert.equal(Buffer.from(bytes).toString('ascii', 0, 4), 'RIFF');
    this.duration = (wav.getUint32(40, true) / wav.getUint32(28, true));
    if (endedAt !== null) waits.push(performance.now() - endedAt);
    voiceStarts++; callsAtStart = calls.length;
    this.onplay?.();
    this.timer = setTimeout(() => { endedAt = performance.now(); this.onended?.(); }, this.duration * 1000);
  }
  pause() { clearTimeout(this.timer); }
  removeAttribute() {}
  load() {}
}
const context = { Audio, URL, Blob, AbortController, navigator: {}, setTimeout, clearTimeout,
  API: { synthesize: async (text, language, signal) => {
    calls.push({ text, language });
    assert(!/Extracted text:|Summary:/.test(text), 'UI headings must not occupy the speech buffer');
    const response = await fetch(base + '/api/speech/synthesize', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, language }), signal,
    });
    assert.equal(response.status, 200, await response.clone().text());
    return response.blob();
  } } };
context.window = context;
vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../frontend/speech.js'), 'utf8'), context);

(async () => {
  const cases = [
    ['en', 'The building opens at nine thirty. Please use the entrance on the left side of the building. Reception staff will show you where to go. Bring your booking confirmation with you.'],
    ['fr', 'Le bâtiment ouvre à neuf heures trente. Veuillez utiliser la porte principale. Le personnel vous aidera à trouver votre salle. Merci de présenter votre confirmation à la réception.'],
  ].map(([language, source]) => ({ language, source, summary: 'This notice gives opening hours and visitor directions.' }));
  if (process.argv[3]) {
    const extraction = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
    cases.splice(0, cases.length, { language: extraction.language, source: extraction.text, summary: extraction.summary });
  }
  for (const { language, source, summary } of cases) {
    const text = 'Extracted text:\n' + source + '\n\nSummary:\n' + summary;
    const languageRanges = [
      { start: text.indexOf(source), end: text.indexOf(source) + source.length, language },
      { start: text.indexOf(summary), end: text.length, language: 'en' },
    ];
    const begin = performance.now();
    const from = calls.length;
    context.Speech.prepare(text, language, { languageRanges });
    endedAt = null; waits = []; voiceStarts = 0;
    let firstContentMs;
    await new Promise((resolve, reject) => context.Speech.speak(text, language, {
      languageRanges, onStart: () => { firstContentMs ??= Math.round(performance.now() - begin); },
      onError: reject, onEnd: resolve,
    }));
    assert(source.startsWith(calls[from].text));
    assert(calls.slice(from).some(call => call.language === 'en' && summary.startsWith(call.text)));
    assert.equal(voiceStarts, 1, 'The reading must play as one continuous track');
    assert.equal(calls.length, callsAtStart, 'No generation may run after playback starts');
    console.log(JSON.stringify({ language, firstActualContentMs: firstContentMs,
      maximumInterClipWaitMs: Math.round(Math.max(0, ...waits)), generatedClips: calls.length - from, playbackTracks: voiceStarts }));
    const beforeReplay = calls.length;
    const click = performance.now();
    await new Promise((resolve, reject) => context.Speech.speak(text, language, { languageRanges, onStart: resolve, onError: reject }));
    assert.equal(calls.length, beforeReplay, 'Replay must use the prepared document');
    console.log(JSON.stringify({ language, cachedContentHandoffMs: Math.round(performance.now() - click) }));
    context.Speech.clear();
  }
})().catch(error => { context.Speech.clear(); console.error(error); process.exitCode = 1; });
