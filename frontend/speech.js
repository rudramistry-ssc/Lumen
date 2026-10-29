// Text-to-speech and speech-to-text using the browser's built-in APIs.
// TTS works offline with the voices installed on the computer.
// Browser speech recognition (Chrome/Edge) sends audio online; for a fully
// offline app, replace listen() with a call to a backend Whisper endpoint.
(function () {
  const synth = window.speechSynthesis;
  const LOCALES = { en: ["en-CA", "en-US", "en-GB", "en"], fr: ["fr-CA", "fr-FR", "fr"] };

  function voicesFor(lang) {
    if (!synth) return [];
    const voices = synth.getVoices();
    for (const loc of LOCALES[lang] || LOCALES.en) {
      const match = voices.filter((x) => x.lang.toLowerCase().startsWith(loc.toLowerCase()));
      if (match.length) return match;
    }
    return [];
  }

  // Chrome and Edge list cloud voices next to local ones. Cloud voices are
  // silent without internet, so always prefer a voice installed on the
  // computer; fall back to a cloud voice only when we are online.
  function pickVoice(lang) {
    const match = voicesFor(lang);
    return match.find((v) => v.localService) || (navigator.onLine ? match[0] : null) || null;
  }

  // Split mixed text into chunks by guessed language, so each part is read
  // with a matching voice. Very simple heuristic; the backend can do better.
  const FR_HINT = /[àâçéèêëîïôûùüÿœ]|\b(le|la|les|des|du|de|et|veuillez|est|pour|au|aux|une?|vous|plancher|mouillé)\b/i;
  function chunksFor(text, lang) {
    if (lang !== "mixed") return [{ text, lang, offset: 0 }];
    let cursor = 0;
    return text
      .split(/\n|(?<=[.!?])\s+|\s[—\/·-]\s/)
      .map((s) => s.trim())
      .filter(Boolean)
      .map((s) => {
        const offset = text.indexOf(s, cursor);
        cursor = offset + s.length;
        return { text: s, lang: FR_HINT.test(s) ? "fr" : "en", offset };
      });
  }

  let current = null;

  // Chrome/Edge record WebM, Firefox Ogg, Safari MP4. Prefer Opus when offered.
  function pickMimeType() {
    if (!window.MediaRecorder || !MediaRecorder.isTypeSupported) return "";
    const candidates = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus", "audio/mp4"];
    return candidates.find((t) => MediaRecorder.isTypeSupported(t)) || "";
  }

  window.Speech = {
    supported: !!synth,
    canListen: !!(window.SpeechRecognition || window.webkitSpeechRecognition),
    // MediaRecorder keeps the audio local; unlike SpeechRecognition this works
    // offline. getUserMedia needs a secure context (localhost or HTTPS).
    canRecord: !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia && window.MediaRecorder),

    hasVoice: (lang) => !!pickVoice(lang),
    // True only for voices that work without internet.
    hasLocalVoice: (lang) => voicesFor(lang).some((v) => v.localService),

    speak(text, lang, { rate = 1, onStart, onEnd, onBoundary } = {}) {
      if (!synth) return;
      synth.cancel();
      const parts = chunksFor(text, lang);
      const token = {};
      current = token;
      parts.forEach((p, i) => {
        const u = new SpeechSynthesisUtterance(p.text);
        const v = pickVoice(p.lang);
        if (v) u.voice = v;
        u.lang = v ? v.lang : (p.lang === "fr" ? "fr-CA" : "en-CA");
        u.rate = rate;
        // charIndex is relative to this chunk; report it relative to the full text
        u.onboundary = (e) => { if (current === token && onBoundary && e.name !== "sentence") onBoundary(p.offset + e.charIndex); };
        if (i === 0) u.onstart = () => onStart && onStart();
        if (i === parts.length - 1) u.onend = u.onerror = () => { if (current === token) { current = null; onEnd && onEnd(); } };
        synth.speak(u);
      });
    },
    pause: () => synth && synth.pause(),
    resume: () => synth && synth.resume(),
    stop() { if (synth) { current = null; synth.cancel(); } },
    get speaking() { return !!synth && synth.speaking; },
    get paused() { return !!synth && synth.paused; },

    // Returns a stop() function. Calls onResult(finalText) once.
    listen(lang, { onResult, onError, onEnd }) {
      const Rec = window.SpeechRecognition || window.webkitSpeechRecognition;
      if (!Rec) { onError && onError("unsupported"); return () => {}; }
      const rec = new Rec();
      rec.lang = lang === "fr" ? "fr-CA" : "en-CA";
      rec.interimResults = false;
      rec.maxAlternatives = 1;
      rec.onresult = (e) => onResult && onResult(e.results[0][0].transcript);
      rec.onerror = (e) => onError && onError(e.error);
      rec.onend = () => onEnd && onEnd();
      rec.start();
      return () => rec.stop();
    },

    // Records a clip with the microphone and keeps it in memory. Resolves to
    // { mimeType, stop() }, where stop() returns a Promise<Blob>. Safe to call
    // stop() more than once; the same promise is returned.
    async record({ maxMs = 60000, onAutoStop } = {}) {
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia || !window.MediaRecorder) {
        const err = new Error("Recording is not supported");
        err.name = "NotSupportedError";
        throw err;
      }

      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mimeType = pickMimeType();
      let rec;
      try {
        rec = mimeType ? new MediaRecorder(stream, { mimeType }) : new MediaRecorder(stream);
      } catch (err) {
        stream.getTracks().forEach((t) => t.stop());
        throw err;
      }

      const chunks = [];
      rec.ondataavailable = (e) => { if (e.data && e.data.size) chunks.push(e.data); };

      const done = new Promise((resolve, reject) => {
        rec.onstop = () => {
          stream.getTracks().forEach((t) => t.stop());
          resolve(new Blob(chunks, { type: rec.mimeType || mimeType || "audio/webm" }));
        };
        rec.onerror = (e) => {
          stream.getTracks().forEach((t) => t.stop());
          reject((e && e.error) || new Error("recorder-error"));
        };
      });

      let stopped = false;
      let timer = null;
      const stop = () => {
        clearTimeout(timer);
        if (!stopped) {
          stopped = true;
          if (rec.state !== "inactive") rec.stop();
        }
        return done;
      };

      rec.start();
      // Safety net: never leave the microphone open if the user walks away.
      timer = setTimeout(() => {
        if (stopped) return;
        stop();
        if (onAutoStop) onAutoStop();
      }, maxMs);

      return { mimeType: rec.mimeType || mimeType || "audio/webm", stop };
    },
  };

  if (synth) synth.onvoiceschanged = () => synth.getVoices();
})();
