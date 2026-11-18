const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const script = fs.readFileSync(path.join(__dirname, '../frontend/speech.js'), 'utf8');
const tick = async () => { for (let i = 0; i < 5; i++) await new Promise(resolve => setImmediate(resolve)); };

function wav(samples = 24000, rate = 24000, value = 100) {
  const buffer = new ArrayBuffer(44 + samples * 2), view = new DataView(buffer);
  const write = (offset, text) => [...text].forEach((c, i) => view.setUint8(offset + i, c.charCodeAt(0)));
  write(0, 'RIFF'); view.setUint32(4, 36 + samples * 2, true); write(8, 'WAVEfmt ');
  view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true);
  view.setUint32(24, rate, true); view.setUint32(28, rate * 2, true);
  view.setUint16(32, 2, true); view.setUint16(34, 16, true); write(36, 'data'); view.setUint32(40, samples * 2, true);
  for (let i = 0; i < samples; i++) view.setInt16(44 + i * 2, value, true);
  return new Blob([buffer], { type: 'audio/wav' });
}

function speechPage(overrides = {}) {
  const audios = [], recorders = [], calls = [], revoked = [], blobs = [];
  let stoppedTracks = 0, voicePlays = 0, playCalls = 0;
  class Audio {
    constructor(url) { this.url = url; this.duration = 2; this.currentTime = 0; audios.push(this); }
    play() {
      playCalls++;
      if (this.src?.startsWith('blob:')) voicePlays++;
      if (overrides.play) return overrides.play(this, playCalls);
      this.playing = true; this.onplay?.(); return Promise.resolve();
    }
    pause() { this.playing = false; }
    removeAttribute() {}
    load() {}
  }
  class MediaRecorder {
    static isTypeSupported(type) { return type.startsWith('audio/webm'); }
    constructor(stream, options) { this.mimeType = options.mimeType; recorders.push(this); }
    start() { this.state = 'recording'; }
    stop() {
      this.state = 'inactive';
      this.ondataavailable?.({ data: new Blob(['local recording']) });
      this.onstop?.();
    }
  }
  const stream = { getTracks: () => [{ stop() { stoppedTracks++; } }] };
  const context = {
    Audio, MediaRecorder, AbortController, Blob,
    navigator: { mediaDevices: { getUserMedia: overrides.getUserMedia || (async () => stream) } },
    API: {
      synthesize: overrides.synthesize || (async (text, lang, signal) => { calls.push({ text, lang, signal }); return wav(); }),
      transcribe: overrides.transcribe || (async () => ({ text: 'When is it open?' })),
    },
    URL: { createObjectURL: blob => { blobs.push(blob); return 'blob:local'; }, revokeObjectURL: url => revoked.push(url) },
    setTimeout: overrides.setTimeout || (() => 1), clearTimeout() {},
    performance: overrides.performance,
  };
  context.window = context;
  vm.runInNewContext(script, context);
  return { speech: context.Speech, audios, recorders, calls, revoked, blobs, stream, stopped: () => stoppedTracks,
    voicePlays: () => voicePlays, playCalls: () => playCalls };
}

test('local voice joins all chunks into one playback with pause, resume, rate and cleanup', async () => {
  let ended = 0;
  const ui = speechPage();
  ui.speech.speak('First '.repeat(40) + 'sentence. ' + 'Second '.repeat(40) + 'sentence.', 'en', { rate: 1.2, onEnd: () => ended++ });
  await tick();
  assert.equal(ui.audios[0].playbackRate, 1.2);
  ui.speech.pause(); assert.equal(ui.speech.paused, true); assert.equal(ui.audios[0].playing, false);
  ui.speech.resume(); assert.equal(ui.audios[0].playing, true);
  ui.audios[0].onended(); await tick();
  assert.equal(ui.audios.length, 1, 'One audio element retains the click permission across phrases');
  while (ui.speech.speaking) { ui.audios[0].onended(); await tick(); }
  assert(ui.calls.length > 1);
  assert.equal(ended, 1);
  assert.equal(ui.speech.speaking, false);
  assert.equal(ui.revoked.length, ui.voicePlays() - 1, 'Resume replays the same clip without allocating a new URL');
});

test('stopping a pending voice request prevents late playback', async () => {
  let resolve, signal;
  const ui = speechPage({ synthesize: (text, lang, currentSignal) => { signal = currentSignal; return new Promise(done => { resolve = done; }); } });
  ui.speech.speak('Private text', 'en');
  await tick();
  ui.speech.stop();
  assert.equal(signal.aborted, false, 'Keep the in-flight result for a quick retry instead of regenerating it');
  resolve(wav()); await tick();
  assert.equal(ui.voicePlays(), 0);
});

test('speech failures are reported and never fall back to an online voice', async () => {
  let error, ended = 0;
  const ui = speechPage({ synthesize: async () => { throw new Error('Local model missing'); } });
  ui.speech.speak('Hello', 'en', { onError: value => error = value, onEnd: () => ended++ });
  await tick();
  assert.match(error.message, /Local model missing/);
  assert.equal(ended, 1);
  assert.equal(ui.speech.speaking, false);
});

test('mixed-language playback chooses the local French voice for French text', async () => {
  const ui = speechPage();
  ui.speech.speak('Hello. Veuillez attendre.', 'mixed'); await tick();
  assert.equal(ui.calls[0].lang, 'en');
  assert.equal(ui.calls[1].lang, 'fr');
  ui.speech.stop();
});

test('recording uses local transcription and closes microphone tracks before sending', async () => {
  let text, ended = 0;
  const ui = speechPage({ transcribe: async (blob, lang) => {
    assert(ui.stopped() > 0); assert.equal(lang, 'en'); assert(blob.size > 0);
    return { text: 'When is it open?' };
  } });
  const finish = ui.speech.listen('en', { onResult: value => text = value, onEnd: () => ended++ });
  await tick(); finish(); await tick();
  assert.equal(text, 'When is it open?'); assert.equal(ended, 1);
});

test('reset while microphone permission is pending releases late microphone access', async () => {
  let allow, ended = 0;
  const ui = speechPage({ getUserMedia: () => new Promise(resolve => allow = resolve) });
  const finish = ui.speech.listen('en', { onEnd: () => ended++ });
  finish.abort(); allow(ui.stream); await tick();
  assert(ui.stopped() > 0); assert.equal(ui.recorders.length, 0); assert.equal(ended, 1);
});

test('reset during transcription aborts the request and discards a late transcript', async () => {
  let complete, signal, result = 0;
  const ui = speechPage({ transcribe: (blob, lang, currentSignal) => { signal = currentSignal; return new Promise(resolve => complete = resolve); } });
  const finish = ui.speech.listen('en', { onResult: () => result++ });
  await tick(); finish(); await tick(); finish.abort();
  assert(signal.aborted); complete({ text: 'Old question' }); await tick();
  assert.equal(result, 0);
});

test('short sentences share voice context and decimals are not split into clips', async () => {
  const ui = speechPage();
  const text = 'Hello, I am Lumen. The fare is $2.50. Doors open at 9:30.';
  ui.speech.speak(text, 'en'); await tick();
  assert.equal(ui.calls.length, 1);
  assert.equal(ui.calls[0].text, text);
  ui.speech.stop();
});

test('a French source and English summary use separate voices with original text offsets', async () => {
  const ui = speechPage();
  const text = 'Sortie.\nAn exit sign.';
  const boundaries = [];
  ui.speech.speak(text, 'fr', { languageRanges: [
    { start: 0, end: 7, language: 'fr' }, { start: 7, end: text.length, language: 'en' },
  ], onBoundary: index => boundaries.push(index) });
  await tick();
  assert.equal(ui.calls[0].lang, 'fr');
  assert.equal(ui.calls[0].text, 'Sortie.');
  assert.equal(ui.calls[1].lang, 'en');
  assert.equal(ui.calls[1].text, 'An exit sign.');
  ui.audios[0].currentTime = 1.1; ui.audios[0].ontimeupdate();
  assert.deepEqual(boundaries, [0, 8]);
  ui.speech.stop();
});

test('prepared audio is reused on a click and on replay without new generation', async () => {
  const ui = speechPage();
  ui.speech.prepare('Ready before you click.', 'en'); await tick();
  assert.equal(ui.calls.length, 1);
  assert.equal(ui.audios.length, 0, 'Preparation must not start playback');
  ui.speech.speak('Ready before you click.', 'en'); await tick();
  assert.equal(ui.calls.length, 1);
  assert.equal(ui.voicePlays(), 1);
  ui.speech.stop();
  ui.speech.speak('Ready before you click.', 'en'); await tick();
  assert.equal(ui.calls.length, 1);
  assert.equal(ui.voicePlays(), 2);
  ui.speech.stop();
});

test('clicking while preparation is pending joins the existing request', async () => {
  let finish, generated = 0;
  const ui = speechPage({ synthesize: () => { generated++; return new Promise(resolve => finish = resolve); } });
  ui.speech.prepare('Still being generated.', 'en'); await tick();
  ui.speech.speak('Still being generated.', 'en'); await tick();
  assert.equal(generated, 1);
  assert.equal(ui.speech.loading, true);
  finish(wav()); await tick();
  assert.equal(ui.voicePlays(), 1);
  assert.equal(ui.speech.loading, false);
  ui.speech.stop();
});

test('reset clears private cached audio and aborts queued preparation', async () => {
  const ui = speechPage();
  ui.speech.prepare('Old session.', 'en'); await tick();
  ui.speech.clear();
  ui.speech.speak('Old session.', 'en'); await tick();
  assert.equal(ui.calls.length, 2, 'Old session audio must be regenerated');
  ui.speech.clear();
});

test('browser playback is unlocked synchronously before waiting for generated audio', async () => {
  let finish;
  const ui = speechPage({ synthesize: () => new Promise(resolve => finish = resolve) });
  ui.speech.speak('Click to speak.', 'en');
  assert.equal(ui.playCalls(), 1, 'The permission request must occur inside the click handler');
  assert.equal(ui.voicePlays(), 0);
  await tick(); finish(wav()); await tick();
  assert.equal(ui.audios.length, 1);
  assert.equal(ui.voicePlays(), 1);
  ui.speech.stop();
});

test('timed-out preparation reports an error and clears the playing state', async () => {
  let expire, error;
  const ui = speechPage({
    setTimeout: (callback, ms) => { if (ms === 120000) expire = callback; return 1; },
    synthesize: (text, lang, signal) => new Promise((resolve, reject) => {
      signal.addEventListener('abort', () => reject(Object.assign(new Error('Aborted'), { name: 'AbortError' })));
    }),
  });
  ui.speech.speak('Timeout test.', 'en', { onError: value => error = value }); await tick();
  expire(); await tick();
  assert.match(error.message, /too long/);
  assert.equal(ui.speech.speaking, false);
  assert.equal(ui.speech.loading, false);
});

test('a long answer is completely generated before its single audio track starts', async () => {
  const ui = speechPage();
  const opening = 'The building opens at nine thirty. ';
  const text = opening + 'Please enter through the main doors. ' + 'More details about the notice. '.repeat(8);
  ui.speech.speak(text, 'en'); await tick();
  assert(ui.calls[0].text.startsWith(opening.trim()));
  assert.equal(ui.calls[0].text, opening.trim());
  assert(ui.calls[0].text.endsWith('.'));
  assert.equal(ui.voicePlays(), 1);
  const generated = ui.calls.length;
  ui.audios[0].currentTime = 2; ui.audios[0].ontimeupdate?.(); await tick();
  assert.equal(ui.calls.length, generated, 'Playback cannot trigger later generation or buffering pauses');
  ui.speech.stop();
});

test('a browser audio-permission refusal can be retried using already-prepared audio', async () => {
  let refuse = true, error, starts = 0;
  const ui = speechPage({ play: player => {
    if (player.src?.startsWith('blob:') && refuse) {
      refuse = false;
      return Promise.reject(Object.assign(new Error('Permission denied'), { name: 'NotAllowedError' }));
    }
    player.onplay?.(); return Promise.resolve();
  } });
  ui.speech.speak('Try the speaker.', 'en', { onError: value => error = value }); await tick();
  assert.match(error.message, /speaker again/);
  assert.equal(ui.speech.speaking, false);
  ui.speech.speak('Try the speaker.', 'en', { onStart: () => starts++ }); await tick();
  assert.equal(starts, 1);
  assert.equal(ui.calls.length, 1);
  ui.speech.stop();
});

test('a long unpunctuated sentence starts within a short phrase without losing text or offsets', async () => {
  const text = 'Please use the entrance on the left side of the building and follow the signs to the reception desk where staff will help you find your room '.repeat(5).trim();
  const boundaries = [];
  const ui = speechPage();
  ui.speech.speak(text, 'en', { onBoundary: index => boundaries.push(index) }); await tick();
  assert(ui.calls[0].text.length <= 80);
  assert.equal(ui.calls.map(call => call.text).join(' '), text);
  assert(ui.calls.every(call => call.text.length <= 120));
  ui.calls.forEach((call, i) => {
    ui.audios[0].currentTime = i + 0.001; ui.audios[0].ontimeupdate();
    assert.equal(text.slice(boundaries.at(-1), boundaries.at(-1) + call.text.length), call.text);
  });
  ui.speech.stop();
});

test('preparation generates the complete reading before a click', async () => {
  const ui = speechPage();
  const opening = 'The building opens at nine thirty.';
  ui.speech.prepare(opening + ' Please enter through the main doors. ' + 'Further details. '.repeat(20), 'en');
  await tick();
  assert(ui.calls.length > 3);
  assert.equal(ui.calls[0].text, opening);
  assert(ui.calls.every(call => call.text.length <= 120));
});

test('report preparation and playback start with actual content and omit UI headings', async () => {
  const source = 'Please use the entrance on the left side of the building. ' + 'Reception staff will show you where to go. '.repeat(8);
  const summary = 'This notice provides directions to reception.';
  const text = 'Extracted text:\n' + source + '\n\nSummary:\n' + summary;
  const sourceStart = text.indexOf(source), summaryStart = text.indexOf(summary);
  const languageRanges = [{ start: sourceStart, end: sourceStart + source.length, language: 'en' },
    { start: summaryStart, end: text.length, language: 'en' }];
  const ui = speechPage();
  ui.speech.prepare(text, 'en', { languageRanges }); await tick();
  assert(ui.calls[0].text.startsWith('Please use'));
  assert(ui.calls.length > 3);
  assert(ui.calls.every(call => !/Extracted text:|Summary:/.test(call.text)));
  const generated = ui.calls.length, boundaries = [];
  ui.speech.speak(text, 'en', { languageRanges, onBoundary: index => boundaries.push(index) }); await tick();
  assert.equal(ui.calls.length, generated, 'Prepared continuation must be reused');
  assert.equal(ui.voicePlays(), 1, 'The entire document is one track');
  const trackClips = (ui.blobs[0].size - 44) / 48000;
  ui.audios[0].currentTime = trackClips - 1 + 0.001; ui.audios[0].ontimeupdate();
  assert.equal(boundaries[0], sourceStart);
  assert(boundaries.includes(summaryStart));
  assert(ui.calls.every(call => !/Extracted text:|Summary:/.test(call.text)));
  ui.speech.stop();
});

test('an instant short heading cannot play while the body is still generating', async () => {
  const jobs = [];
  const ui = speechPage({ synthesize: text => new Promise(resolve => jobs.push({ text, resolve })) });
  ui.speech.speak('Start here. ' + 'The next step is to walk to reception. '.repeat(10), 'en'); await tick();
  jobs[0].resolve(wav()); await tick();
  assert(jobs[1].text.startsWith('The next step'));
  assert.equal(jobs[0].text, 'Start here.');
  assert.equal(ui.voicePlays(), 0, 'No title-then-silence false start');
  assert.equal(ui.speech.loading, true);
  ui.speech.clear();
  jobs[1].resolve(wav()); await tick();
  assert.equal(ui.voicePlays(), 0);
});

test('selected speech continues before queued background messages', async () => {
  const jobs = [];
  const ui = speechPage({ synthesize: text => new Promise(resolve => jobs.push({ text, resolve })) });
  const text = 'The building opens at nine thirty. ' + 'Please use the entrance on the left. '.repeat(4);
  ui.speech.speak(text, 'en'); await tick();
  ui.speech.prepare('Another message.', 'en');
  jobs[0].resolve(wav()); await tick();
  assert.equal(jobs.length, 2);
  assert(jobs[1].text.startsWith('Please use'));
  jobs[1].resolve(wav()); await tick();
  assert.equal(jobs.length, 2, 'Background generation waits while the selected complete track plays');
  assert.equal(ui.voicePlays(), 1);
  ui.speech.clear();
});

test('the joined WAV preserves all PCM samples and plays as a single source', async () => {
  let generated = 0;
  const ui = speechPage({ synthesize: async () => wav(4, 24000, ++generated * 100) });
  ui.speech.speak('Sortie.\nAn exit sign.', 'fr', { languageRanges: [
    { start: 0, end: 7, language: 'fr' }, { start: 7, end: 21, language: 'en' },
  ] }); await tick();
  assert.equal(ui.blobs.length, 1);
  const buffer = await ui.blobs[0].arrayBuffer(), view = new DataView(buffer);
  assert.equal(view.getUint32(4, true), buffer.byteLength - 8);
  assert.equal(view.getUint32(40, true), 16);
  assert.deepEqual([...new Int16Array(buffer.slice(44))], [100, 100, 100, 100, 200, 200, 200, 200]);
  assert.equal(ui.voicePlays(), 1);
  ui.speech.stop();
});

test('malformed generated WAV is reported before any part of the document plays', async () => {
  let error;
  const ui = speechPage({ synthesize: async () => new Blob(['RIFFbroken']) });
  ui.speech.speak('Invalid audio.', 'en', { onError: value => error = value }); await tick();
  assert.match(error.message, /invalid audio/);
  assert.equal(ui.voicePlays(), 0);
  assert.equal(ui.speech.speaking, false);
});

function timedEngine() {
  const clock = { t: 0 }, jobs = [];
  const ui = speechPage({ performance: { now: () => clock.t }, synthesize: text => new Promise(resolve => jobs.push({ text, resolve })) });
  return { ui, jobs, finish: async (index, ms) => { clock.t += ms; jobs[index].resolve(wav()); await tick(); } };
}
const TWO_CLIPS = 'The building opens at nine thirty. Please use the entrance on the left.';

test('a fast local voice starts reading after the first clip while the rest generates', async () => {
  const { ui, jobs, finish } = timedEngine();
  const states = [], boundaries = [];
  let starts = 0;
  ui.speech.speak(TWO_CLIPS, 'en', { onStart: () => starts++, onState: s => states.push(s), onBoundary: i => boundaries.push(i) });
  await tick();
  await finish(0, 100);
  assert.equal(jobs.length, 2, 'The second clip is still generating');
  assert.equal(ui.voicePlays(), 1, 'Playback starts without waiting for the whole document');
  assert.equal(ui.speech.loading, false);
  await finish(1, 100);
  ui.audios[0].onended(); await tick();
  assert.equal(ui.voicePlays(), 2);
  assert.equal(starts, 1);
  assert.equal(boundaries.at(-1), TWO_CLIPS.indexOf('Please use'));
  ui.audios[0].onended(); await tick();
  assert.equal(ui.speech.speaking, false);
  assert.deepEqual(states, ['loading', 'playing']);
});

test('a slow local voice keeps waiting so a short heading never plays then stalls', async () => {
  const { ui, jobs, finish } = timedEngine();
  ui.speech.speak('Start here. ' + 'The next step is to walk to reception. '.repeat(10), 'en'); await tick();
  await finish(0, 3000);
  assert.equal(ui.voicePlays(), 0);
  assert.equal(ui.speech.loading, true);
  for (let i = 1; i < jobs.length; i++) await finish(i, 3000);
  assert.equal(ui.voicePlays(), 1);
  assert.equal(ui.blobs.length, 1, 'Fully generated before playback: one joined track');
  ui.speech.stop();
});

test('an unexpected stall between clips shows loading and then continues', async () => {
  const { ui, finish } = timedEngine();
  const states = [];
  ui.speech.speak(TWO_CLIPS, 'en', { onState: s => states.push(s) }); await tick();
  await finish(0, 100);
  ui.audios[0].onended(); await tick();
  assert.equal(ui.speech.loading, true);
  assert.deepEqual(states, ['loading', 'playing', 'loading']);
  await finish(1, 5000);
  assert.equal(ui.voicePlays(), 2);
  assert.equal(ui.speech.loading, false);
  assert.equal(states.at(-1), 'playing');
  ui.speech.stop();
});

test('chat answers use the French voice for French sentences and quoted French sign text', async () => {
  const ui = speechPage();
  const quoted = 'The sign says « Veuillez utiliser la sortie de secours » so please use the side exit.';
  ui.speech.speak(quoted, 'auto:en'); await tick();
  const french = ui.calls.find(call => call.lang === 'fr');
  assert(french, 'The quotation is spoken in French');
  assert.match(french.text, /Veuillez utiliser la sortie de secours/);
  assert(ui.calls.some(call => call.lang === 'en' && call.text.startsWith('The sign says')));
  ui.speech.stop();

  const ui2 = speechPage();
  ui2.speech.speak('Cette affiche indique que la sortie est fermée le dimanche.', 'auto:en'); await tick();
  assert.deepEqual(ui2.calls.map(call => call.lang), ['fr'], 'A French answer is not read with the English voice');
  ui2.speech.stop();

  const ui3 = speechPage();
  ui3.speech.speak('The café is open from nine. Please use the entrance on the left.', 'auto:fr'); await tick();
  assert(ui3.calls.every(call => call.lang === 'en'), 'An accent in an English sentence does not switch voice');
  ui3.speech.stop();

  const ui4 = speechPage();
  ui4.speech.speak('OK.', 'auto:fr'); await tick();
  assert.deepEqual(ui4.calls.map(call => call.lang), ['fr'], 'No signal falls back to the requested language');
  ui4.speech.stop();
});
