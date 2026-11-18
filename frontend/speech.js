// Microphone -> local Whisper; text -> local Kokoro. No browser/cloud recognition.
(function () {
  let current = null;
  let player = null, unlocked = false, unlocking = null;
  const SILENCE = "data:audio/wav;base64,UklGRiYAAABXQVZFZm10IBAAAAABAAEARKwAAIhYAQACABAAZGF0YQIAAAAAAA==";
  const cache = new Map(), queue = [];
  const MAX_CACHE_BYTES = 24 * 1024 * 1024;
  const MAX_PHRASE_CHARS = 120;
  let generating = false, cacheBytes = 0, cacheEpoch = 0;
  const recordings = new Map();
  let recordingBytes = 0;
  // Measured local voice performance: how much audio one character produces
  // and how many seconds of audio the engine generates per wall-clock second.
  const stats = { secPerChar: 0, speed: 0 };
  const now = () => (typeof performance !== "undefined" && performance.now ? performance.now() : Date.now());
  function learn(chars, seconds, ms) {
    if (!chars || !(seconds > 0) || !(ms > 0)) return;
    const speed = seconds / (ms / 1000);
    if (speed > 25) return; // a server cache hit says nothing about generation speed
    const blend = (old, value) => (old ? 0.6 * old + 0.4 * value : value);
    stats.speed = blend(stats.speed, speed);
    stats.secPerChar = blend(stats.secPerChar, seconds / chars);
  }

  function unlock() {
    if (!player) player = new Audio();
    if (unlocked || current?.url) return Promise.resolve();
    if (unlocking) return unlocking;
    // Call play during the actual click/submit gesture, before awaiting speech.
    // Reuse this element for every phrase to retain the browser's permission.
    player.src = SILENCE;
    unlocking = player.play().then(() => {
      unlocked = true;
      if (!current?.url) player.pause();
    }).catch(() => {}).finally(() => { unlocking = null; });
    return unlocking;
  }

  function pump() {
    if (generating || !queue.length) return;
    // Do not let another message's background preparation get ahead of the
    // next phrase of the speech the user actually selected.
    const index = current ? queue.findIndex(entry => entry.priority) : 0;
    if (index < 0) return;
    const [entry] = queue.splice(index, 1);
    generating = true;
    entry.started = true;
    entry.startedAt = now();
    let timedOut = false;
    const timer = setTimeout(() => { timedOut = true; entry.controller.abort(); }, 120000);
    Promise.resolve().then(() => API.synthesize(entry.part.text, entry.part.language, entry.controller.signal))
      .then(async blob => {
        const elapsed = now() - entry.startedAt;
        const clip = await parseClip(blob);
        if (entry.epoch !== cacheEpoch) return;
        learn(entry.part.text.length, clip.duration, elapsed);
        entry.clip = clip;
        entry.blob = blob;
        cacheBytes += blob.size;
        for (const [key, value] of cache) {
          if (cacheBytes <= MAX_CACHE_BYTES && cache.size <= 128) break;
          if (value.blob && value !== entry) { cacheBytes -= value.blob.size; cache.delete(key); }
        }
        entry.resolve(blob);
      }).catch(error => {
        if (cache.get(entry.key) === entry) cache.delete(entry.key);
        entry.reject(timedOut ? new Error("Speech took too long to prepare. Please try the speaker again.") : error);
      }).finally(() => { clearTimeout(timer); generating = false; pump(); });
  }

  function audioFor(part, priority = false, start = true) {
    const key = JSON.stringify([part.language, part.text]);
    let entry = cache.get(key);
    if (!entry) {
      entry = { key, part, epoch: cacheEpoch, controller: new AbortController() };
      entry.promise = new Promise((resolve, reject) => { entry.resolve = resolve; entry.reject = reject; });
      entry.promise.catch(() => {});
      cache.set(key, entry); queue.push(entry);
    } else { cache.delete(key); cache.set(key, entry); }
    if (priority) entry.priority = true;
    if (priority && !entry.started) {
      const index = queue.indexOf(entry);
      if (index >= 0) { queue.splice(index, 1); queue.unshift(entry); }
    }
    if (start) pump();
    return entry;
  }

  function clear() {
    stop(); cacheEpoch++;
    for (const entry of cache.values()) {
      entry.controller.abort();
      entry.reject(Object.assign(new Error("Session ended"), { name: "AbortError" }));
    }
    queue.length = 0; cache.clear(); cacheBytes = 0;
    recordings.clear(); recordingBytes = 0;
  }
  // Score-based language detection for text whose language is not known per
  // sentence (mixed OCR text, chat answers that quote a French sign).
  const word = list => new RegExp(`(?<![\\p{L}'’])(?:${list})(?![\\p{L}])`, "giu");
  const FR_WORDS = word("le|la|les|l[’']|d[’']|qu[’']|un|une|des|du|de|et|est|sont|pour|avec|dans|sur|aux|au|vous|nous|je|il|elle|ils|ce|cette|ces|qui|que|pas|ne|mais|où|ou|très|veuillez|merci|bonjour|sortie|entrée|fermé|ouvert|interdit|défense|attention|tous|jours|heures");
  const EN_WORDS = word("the|and|is|are|to|of|in|for|with|this|that|it|you|we|be|was|not|please|at|from|by|or|your|will|can|has|have|says|sign|means|which|there|here|open|closed|exit|entrance");
  const ACCENTS = /[àâçéèêëîïôûùüÿœ]/giu;
  function detect(text, fallback) {
    const fr = (text.match(FR_WORDS) || []).length + Math.min(2, (text.match(ACCENTS) || []).length) * 0.75;
    const en = (text.match(EN_WORDS) || []).length;
    return fr > en ? "fr" : en > fr ? "en" : fallback;
  }
  // Quoted passages ("Sortie de secours") are detected on their own, so a
  // French quotation inside an English answer is spoken with the French voice.
  const QUOTED = /[«“"„]\s*[^«»“”"„\n]{2,}?\s*[»”"]/gu;
  function languageRuns(sentence, offset, language, fallback) {
    if (language !== "mixed" && language !== "auto") return [{ text: sentence, offset, language }];
    const base = detect(sentence, fallback), runs = [];
    let last = 0;
    for (const quote of sentence.matchAll(QUOTED)) {
      if (quote.index > last) runs.push({ text: sentence.slice(last, quote.index), offset: offset + last, language: base });
      runs.push({ text: quote[0], offset: offset + quote.index, language: detect(quote[0], base) });
      last = quote.index + quote[0].length;
    }
    if (last < sentence.length) runs.push({ text: sentence.slice(last), offset: offset + last, language: base });
    return runs;
  }
  // language: "en", "fr", "mixed" (OCR text) or "auto:<en|fr>" (detect per
  // sentence, defaulting to the given language when the text gives no signal).
  function chunksFor(text, language) {
    let fallback = "en";
    if (String(language).startsWith("auto")) { fallback = language === "auto:fr" ? "fr" : "en"; language = "auto"; }
    const parts = [];
    const locale = language === "fr" ? "fr" : language === "auto" ? fallback : "en";
    const segmenter = typeof Intl.Segmenter === "function" ? new Intl.Segmenter(locale, { granularity: "sentence" }) : null;
    // Keep short sentences together so the voice can carry intonation across
    // them. Intl segmentation preserves decimals and abbreviations such as Dr.
    for (const line of text.matchAll(/[^\n]+/g)) {
      const sentences = segmenter ? segmenter.segment(line[0]) : [{ segment: line[0], index: 0 }];
      for (const sentence of sentences) {
       for (const run of languageRuns(sentence.segment, line.index + sentence.index, language, language === "auto" ? fallback : "en")) {
        let offset = run.offset, rest = run.text;
        const spokenLanguage = run.language;
        while (rest.length) {
          let end = Math.min(MAX_PHRASE_CHARS, rest.length);
          if (end < rest.length) { const space = rest.lastIndexOf(" ", end); if (space > 0) end = space; }
          const segment = rest.slice(0, end), trimmed = segment.trim();
          if (trimmed) {
            const start = offset + segment.indexOf(trimmed), finish = start + trimmed.length;
            const previous = parts.at(-1);
            if (previous && previous.language === spokenLanguage && finish - previous.offset <= MAX_PHRASE_CHARS) {
              previous.text = text.slice(previous.offset, finish);
            } else parts.push({ text: trimmed, offset: start, language: spokenLanguage });
          }
          rest = rest.slice(end); offset += end;
        }
       }
      }
    }
    return parts;
  }
  function stop() {
    const token = current; current = null;
    if (!token) return;
    if (player) {
      player.onplay = player.onended = player.onerror = player.ontimeupdate = null;
      player.pause(); player.removeAttribute("src"); player.load();
    }
    token.release?.();
    if (token.url) URL.revokeObjectURL(token.url);
  }
  function partsFor(text, language, languageRanges) {
    const rawParts = languageRanges
      ? languageRanges.flatMap(range => chunksFor(text.slice(range.start, range.end), range.language)
        .map(part => ({ ...part, offset: part.offset + range.start })))
      : chunksFor(text, language);
    const parts = [];
    for (const part of rawParts) {
      const previous = parts.at(-1), end = part.offset + part.text.length;
      const gap = previous ? text.slice(previous.offset + previous.text.length, part.offset) : "";
      if (previous && previous.language === part.language && !gap.trim() && end - previous.offset <= MAX_PHRASE_CHARS) {
        previous.text = text.slice(previous.offset, end);
      } else parts.push({ ...part });
    }
    // Bound the first inference even for a long sentence with no punctuation.
    // Prefer its first complete sentence or clause to keep natural phrasing.
    const first = parts[0];
    if (first?.text.length > 64) {
      const sentence = typeof Intl.Segmenter === "function"
        ? [...new Intl.Segmenter(first.language, { granularity: "sentence" }).segment(first.text)][0]
        : null;
      let end = 0;
      if (sentence && sentence.segment.trimEnd().length <= 80) end = sentence.segment.length;
      if (!end) {
        for (const clause of first.text.slice(0, 80).matchAll(/[,;:]\s+/g)) {
          if (clause.index >= 24) end = clause.index + clause[0].length;
        }
      }
      if (!end) end = first.text.lastIndexOf(" ", 64);
      if (end > 0 && end < first.text.length) {
        const rest = first.text.slice(end), trimmed = rest.trimStart();
        parts.splice(0, 1, { ...first, text: first.text.slice(0, end).trimEnd() },
          { ...first, text: trimmed, offset: first.offset + end + rest.length - trimmed.length });
      }
    }
    return parts;
  }
  async function parseClip(blob) {
    const buffer = await blob.arrayBuffer(), view = new DataView(buffer);
    const id = offset => String.fromCharCode(...new Uint8Array(buffer, offset, 4));
    if (buffer.byteLength < 44 || id(0) !== "RIFF" || id(8) !== "WAVE") throw new Error("The local voice returned invalid audio.");
    let data, format;
    for (let offset = 12; offset + 8 <= buffer.byteLength;) {
      const size = view.getUint32(offset + 4, true), start = offset + 8;
      if (start + size > buffer.byteLength) throw new Error("The local voice returned incomplete audio.");
      if (id(offset) === "fmt " && size >= 16) format = {
        codec: view.getUint16(start, true), channels: view.getUint16(start + 2, true),
        rate: view.getUint32(start + 4, true), bits: view.getUint16(start + 14, true),
      };
      if (id(offset) === "data") data = new Uint8Array(buffer, start, size);
      offset = start + size + (size % 2);
    }
    if (!data || !format || format.codec !== 1 || format.channels !== 1 || format.bits !== 16 || !format.rate) {
      throw new Error("The local voice returned an unsupported audio format.");
    }
    return { data, format, duration: data.byteLength / (format.rate * 2) };
  }
  async function wholeTrack(blobs, parts) {
    const pcm = [], segments = [];
    let format = null, seconds = 0, bytes = 0;
    for (let i = 0; i < blobs.length; i++) {
      const { data, format: clipFormat, duration } = await parseClip(blobs[i]);
      if (format && JSON.stringify(format) !== JSON.stringify(clipFormat)) throw new Error("Voice clips used incompatible audio formats.");
      format = clipFormat;
      segments.push({ start: seconds, end: seconds + duration, offset: parts[i].offset, text: parts[i].text });
      seconds += duration; bytes += data.byteLength; pcm.push(data);
    }
    if (blobs.length === 1) return { blob: blobs[0], segments };
    const header = new ArrayBuffer(44), view = new DataView(header);
    const write = (offset, value) => [...value].forEach((char, index) => view.setUint8(offset + index, char.charCodeAt(0)));
    write(0, "RIFF"); view.setUint32(4, 36 + bytes, true); write(8, "WAVEfmt ");
    view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true);
    view.setUint32(24, format.rate, true); view.setUint32(28, format.rate * 2, true);
    view.setUint16(32, 2, true); view.setUint16(34, 16, true); write(36, "data"); view.setUint32(40, bytes, true);
    return { blob: new Blob([header, ...pcm], { type: "audio/wav" }), segments };
  }
  function recordingFor(text, language, languageRanges, priority = false) {
    const key = JSON.stringify([text, language, languageRanges]);
    let recording = recordings.get(key);
    if (!recording) {
      const parts = partsFor(text, language, languageRanges), epoch = cacheEpoch;
      const entries = parts.map(part => audioFor(part, false, false));
      recording = { entries, parts };
      recording.promise = Promise.all(entries.map(entry => entry.promise))
        .then(blobs => wholeTrack(blobs, parts)).then(result => {
          if (epoch !== cacheEpoch) throw Object.assign(new Error("Session ended"), { name: "AbortError" });
          recording.result = result; recordingBytes += result.blob.size;
          // The joined track replaces the temporary clips in memory.
          for (const entry of entries) {
            if (cache.get(entry.key) === entry) { cache.delete(entry.key); cacheBytes -= entry.blob?.size || 0; }
          }
          recording.entries = [];
          for (const [oldKey, old] of recordings) {
            if (recordingBytes <= MAX_CACHE_BYTES && recordings.size <= 16) break;
            if (old.result) { recordings.delete(oldKey); recordingBytes -= old.result.blob.size; }
          }
          return result;
        }).catch(error => { if (recordings.get(key) === recording) recordings.delete(key); throw error; });
      recording.promise.catch(() => {});
      recordings.set(key, recording);
    } else { recordings.delete(key); recordings.set(key, recording); }
    if (priority) {
      for (const entry of [...recording.entries].reverse()) {
        entry.priority = true;
        const index = queue.indexOf(entry);
        if (index >= 0) { queue.splice(index, 1); queue.unshift(entry); }
      }
    }
    pump();
    return recording;
  }
  window.Speech = {
    supported: typeof Audio !== "undefined",
    canListen: !!navigator.mediaDevices?.getUserMedia && typeof MediaRecorder !== "undefined",
    hasVoice: (lang) => ["en", "fr", "mixed"].includes(lang),
    unlock,
    clear,
    prepare(text, language, { languageRanges } = {}) {
      if (text.trim()) return recordingFor(text, language, languageRanges).promise;
    },
    speak(text, language, { rate = 1, languageRanges, onStart, onEnd, onBoundary, onError, onState } = {}) {
      stop();
      const readyToPlay = unlock();
      const token = { paused: false, loading: true };
      current = token;
      if (!text.trim()) { current = null; onEnd?.(); return; }
      const recording = recordingFor(text, language, languageRanges, true);
      const playbackRate = Math.min(1.6, Math.max(0.6, rate));
      onState?.("loading");
      // Play one blob on the shared (unlocked) audio element; resolves when it ends.
      const playClip = async (blob, segments) => {
        await readyToPlay;
        if (current !== token) return false;
        token.url = URL.createObjectURL(blob);
        player.src = token.url;
        player.playbackRate = playbackRate;
        player.preservesPitch = true;
        await new Promise((resolve, reject) => {
          token.release = resolve;
          player.onended = resolve;
          player.onerror = () => reject(new Error("Audio playback failed. Please try again."));
          player.onplay = () => {
            if (current !== token) return;
            if (token.loading) { token.loading = false; onState?.("playing"); }
            if (!token.started) { token.started = true; onStart?.(); }
            onBoundary?.(segments[0].offset);
          };
          // Estimated visual progress, not forced-aligned word timestamps.
          player.ontimeupdate = () => {
            if (current !== token || !Number.isFinite(player.duration)) return;
            const part = segments.find(segment => player.currentTime < segment.end) || segments.at(-1);
            const progress = (player.currentTime - part.start) / Math.max(0.001, part.end - part.start);
            const char = Math.floor(part.text.length * Math.max(0, Math.min(1, progress)));
            onBoundary?.(part.offset + Math.max(0, part.text.lastIndexOf(" ", char) + 1));
          };
          token.play = () => player.play().catch(error => {
            if (error.name === "NotAllowedError") {
              unlocked = false;
              reject(new Error("Click the speaker again to allow audio playback."));
            } else reject(error);
          });
          if (!token.paused) token.play();
        });
        if (current !== token) return false;
        URL.revokeObjectURL(token.url); token.url = null;
        player.onplay = player.onended = player.onerror = player.ontimeupdate = null;
        token.play = null; token.release = null;
        return true;
      };
      const playWhole = async ({ blob, segments }) => playClip(blob, segments);
      // Start before the whole document is generated only when the measured
      // generation speed predicts every later clip will be ready before
      // playback reaches it, so a short title never plays and then waits.
      const safeFrom = (entries, i) => {
        let k = i, buffered = 0;
        while (k < entries.length && entries[k].clip) buffered += entries[k++].clip.duration;
        if (k === i) return false;
        if (k === entries.length) return true;
        if (!stats.speed || !stats.secPerChar) return false;
        const speed = stats.speed * 0.85, time = now();
        let readyAt = 0, reachedAt = buffered / playbackRate;
        for (let j = k; j < entries.length; j++) {
          const audio = entries[j].part.text.length * stats.secPerChar;
          const elapsed = j === k && entries[j].startedAt ? (time - entries[j].startedAt) / 1000 : 0;
          readyAt += Math.max(0.05, audio / speed - elapsed);
          if (readyAt + 0.3 > reachedAt) return false;
          reachedAt += audio / playbackRate;
        }
        return true;
      };
      const waitForProgress = (entries, i) => {
        const pending = entries.slice(i).find(entry => !entry.clip);
        return Promise.race([pending.promise, new Promise(resolve => setTimeout(resolve, 250))]);
      };
      (async () => {
        try {
          if (recording.result) {
            if (!await playWhole(recording.result)) return;
          } else {
            const entries = recording.entries.slice(), parts = recording.parts;
            for (let i = 0; i < entries.length; i++) {
              // Mid-reading, a ready clip plays immediately. At the start or
              // after a stall, wait until enough audio is buffered.
              if (!(token.started && entries[i].clip)) {
                let whole = false;
                while (true) {
                  // Everything generated before playback starts: joining is
                  // instant, so play the single gapless track instead.
                  if (!token.started && (recording.result || entries.every(entry => entry.clip))) { whole = true; break; }
                  if (safeFrom(entries, i)) break;
                  if (!token.loading) { token.loading = true; onState?.("loading"); }
                  await waitForProgress(entries, i);
                  if (current !== token) return;
                }
                if (whole) {
                  const result = recording.result || await recording.promise;
                  if (current !== token || !await playWhole(result)) return;
                  break;
                }
              }
              const segment = { start: 0, end: entries[i].clip.duration, offset: parts[i].offset, text: parts[i].text };
              if (!await playClip(entries[i].blob, [segment])) return;
            }
          }
          if (current !== token) return;
          player.removeAttribute("src"); player.load();
          current = null; onEnd?.(); pump();
        } catch (error) {
          if (current !== token) return;
          stop(); onError?.(error); onEnd?.();
        }
      })();
    },
    pause() { if (current) { current.paused = true; player?.pause(); } },
    resume() { if (current) { current.paused = false; current.play?.(); } },
    stop,
    get speaking() { return !!current && !current.paused; },
    get paused() { return !!current?.paused; },
    get loading() { return !!current?.loading; },
    listen(language, { onResult, onError, onEnd, onState } = {}) {
      let stream, recorder, timer, ended = false, cancelled = false, finishRequested = false;
      const controller = new AbortController(), chunks = [];
      let size = 0;
      const release = () => { clearTimeout(timer); stream?.getTracks().forEach(track => track.stop()); };
      const end = () => { if (!ended) { ended = true; release(); onEnd?.(); } };
      const finish = () => { finishRequested = true; if (recorder?.state === "recording") recorder.stop(); };
      finish.abort = () => { cancelled = true; controller.abort(); finish(); end(); };
      (async () => {
        try {
          stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true }, video: false });
          if (cancelled || finishRequested) { release(); end(); return; }
          const mimeType = ["audio/webm;codecs=opus", "audio/ogg;codecs=opus", "audio/mp4"].find(type => MediaRecorder.isTypeSupported(type));
          recorder = new MediaRecorder(stream, mimeType ? { mimeType } : {});
          recorder.ondataavailable = event => {
            if (event.data.size && !cancelled) { chunks.push(event.data); size += event.data.size; if (size > 12 * 1024 * 1024) finish(); }
          };
          recorder.onerror = () => { cancelled = true; onError?.(new Error("Microphone recording failed. Please try again.")); finish(); end(); };
          recorder.onstop = async () => {
            release();
            if (cancelled) return end();
            onState?.("transcribing");
            try {
              const result = await API.transcribe(new Blob(chunks, { type: recorder.mimeType }), language, controller.signal);
              if (!cancelled) onResult?.(result.text);
            } catch (error) { if (!cancelled && error.name !== "AbortError") onError?.(error); }
            finally { end(); }
          };
          recorder.start(1000);
          onState?.("recording");
          timer = setTimeout(finish, 60000);
        } catch (error) {
          if (!cancelled) onError?.(error.name === "NotAllowedError" ? Object.assign(new Error("Microphone permission was denied."), { code: "not-allowed" }) : error);
          end();
        }
      })();
      return finish;
    },
  };
})();
