// Text-to-speech and speech-to-text using the browser's built-in APIs.
// TTS works offline with the voices installed on the computer.
// Browser speech recognition (Chrome/Edge) sends audio online; for a fully
// offline app, replace listen() with a call to a backend Whisper endpoint.
(function () {
  const synth = window.speechSynthesis;
  const LOCALES = { en: ["en-CA", "en-US", "en-GB", "en"], fr: ["fr-CA", "fr-FR", "fr"] };

  function pickVoice(lang) {
    if (!synth) return null;
    const voices = synth.getVoices();
    for (const loc of LOCALES[lang] || LOCALES.en) {
      const v = voices.find((x) => x.lang.toLowerCase().startsWith(loc.toLowerCase()));
      if (v) return v;
    }
    return null;
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

  window.Speech = {
    supported: !!synth,
    canListen: !!(window.SpeechRecognition || window.webkitSpeechRecognition),

    hasVoice: (lang) => !!pickVoice(lang),

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
  };

  if (synth) synth.onvoiceschanged = () => synth.getVoices();
})();
