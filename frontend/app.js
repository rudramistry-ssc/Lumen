// Main UI logic: image upload -> extracted text -> read aloud -> chat.
(function () {
  const $ = (id) => document.getElementById(id);
  const cfg = window.APP_CONFIG;

  const store = {
    get(k, d) { try { const v = localStorage.getItem("signspeak." + k); return v === null ? d : JSON.parse(v); } catch (_) { return d; } },
    set(k, v) { try { localStorage.setItem("signspeak." + k, JSON.stringify(v)); } catch (_) {} },
  };

  const state = {
    uiLang: store.get("uiLang", (navigator.language || "en").startsWith("fr") ? "fr" : "en"),
    textScale: store.get("textScale", 1),
    theme: store.get("theme", "dark"), // dark by default; null = follow system
    sessionId: newId(),
    ready: false,
    file: null,
    text: "",
    report: null,
    confidence: null,
    language: "none",
    busy: false,
    stopListening: null,
  };

  let extractSequence = 0;
  let extractController = null;
  let stopExtractStages = null;
  let previewUrl = null;
  let chatController = null;
  let chatSequence = 0;
  let prepareSpeechTimer = null;

  function cancelExtraction() {
    extractSequence++;
    if (extractController) extractController.abort();
    if (stopExtractStages) stopExtractStages(true);
    extractController = null;
    stopExtractStages = null;
  }

  function newId() {
    return crypto.randomUUID();
  }

  // ---------- i18n ----------
  function t(key, vars) {
    let s = (I18N[state.uiLang] || I18N.en)[key] ?? I18N.en[key] ?? key;
    if (vars) for (const k in vars) s = s.replace(`{${k}}`, vars[k]);
    return s;
  }
  const langName = (code) => (I18N[state.uiLang].langNames || {})[code] || code;

  function applyI18n() {
    document.documentElement.lang = state.uiLang;
    document.querySelectorAll("[data-i18n]").forEach((el) => (el.textContent = t(el.dataset.i18n)));
    document.querySelectorAll("[data-i18n-aria]").forEach((el) => {
      el.setAttribute("aria-label", t(el.dataset.i18nAria));
      el.title = t(el.dataset.i18nAria);
    });
    document.querySelectorAll("[data-i18n-placeholder]").forEach((el) => (el.placeholder = t(el.dataset.i18nPlaceholder)));
    document.querySelectorAll("[data-ui-lang]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.uiLang === state.uiLang)));
    $("chat-input").placeholder = state.text ? t("chatPlaceholder") : t("chatPlaceholderEmpty");
    $("session-label").textContent = `· ${t("session")} ${state.sessionId.slice(0, 8)}`;
    updatePlayButton();
    renderStatus();
    renderConfidence();
  }

  function renderConfidence() {
    const badge = $("confidence");
    const loading = $("extract-card").dataset.state === "loading";
    const edited = state.ready && state.report?.text !== state.text;
    const score = value => typeof value === "number" && Number.isFinite(value)
      && Number.isInteger(value) && value >= 0 && value <= 100 ? value : null;
    const textScore = score(state.confidence?.text), summaryScore = score(state.confidence?.summary);
    const overall = textScore !== null && summaryScore !== null ? Math.min(textScore, summaryScore) : null;
    const percent = value => value === null ? "—" : `${value}%`;
    badge.dataset.state = loading ? "loading" : edited ? "edited" : state.ready ? "ready" : "empty";
    const scores = `${t("confidenceText")} ${percent(textScore)} · ${t("confidenceSummary")} ${percent(summaryScore)}`;
    badge.title = `${t("confidenceHelp")}\n${edited ? t("confidenceEdited") : scores}`;
    badge.textContent = `${t("confidenceLabel")}: ${loading ? t("confidenceAssessing") : edited ? t("confidenceEdited") : percent(overall)}`;
    badge.setAttribute("aria-label", `${badge.textContent}. ${badge.title}`);
  }

  // ---------- settings ----------
  function applyScale() { document.documentElement.style.setProperty("--scale", state.textScale); }
  // The design is dark-only, so there is no theme toggle.
  function applyTheme() {}
  function currentTheme() {
    return state.theme || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  }

  // ---------- backend status ----------
  let backendState = cfg.USE_MOCK ? "mock" : "unknown";
  function renderStatus() {
    const el = $("backend-status");
    el.hidden = backendState === "mock"; // nothing to show when using sample answers
    el.dataset.state = backendState;
    el.textContent = backendState === "mock" ? t("statusMock") : backendState === "ok" ? t("statusOk") : t("statusDown");
    el.title = backendState === "mock" ? t("statusMockTitle") : "";
  }
  async function checkBackend() {
    if (cfg.USE_MOCK) return renderStatus();
    try { await API.health(); backendState = "ok"; } catch (_) { backendState = "down"; }
    renderStatus();
  }

  // ---------- image upload ----------
  const dz = $("dropzone");
  dz.addEventListener("click", () => $("file-input").click());
  dz.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); $("file-input").click(); } });
  $("replace-image").addEventListener("click", () => { resetSession(); $("file-input").click(); });
  $("file-input").addEventListener("change", (e) => { if (e.target.files[0]) handleFile(e.target.files[0]); e.target.value = ""; });
  ["dragenter", "dragover"].forEach((ev) => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.add("is-over"); }));
  ["dragleave", "drop"].forEach((ev) => dz.addEventListener(ev, () => dz.classList.remove("is-over")));
  dz.addEventListener("drop", (e) => { e.preventDefault(); const f = e.dataTransfer.files[0]; if (f) handleFile(f); });
  document.addEventListener("paste", (e) => {
    const item = [...(e.clipboardData?.items || [])].find((i) => i.type.startsWith("image/"));
    if (item) { e.preventDefault(); handleFile(item.getAsFile()); }
  });

  // ---------- sample photos ----------
  function dataUrlToFile(dataUrl, name) {
    const [head, b64] = dataUrl.split(",");
    const bin = atob(b64);
    const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    return new File([bytes], name, { type: head.match(/data:(.*?);/)[1] });
  }
  document.querySelectorAll(".sample").forEach((btn) => {
    const key = btn.dataset.sample;
    const src = (window.SAMPLE_IMAGES || {})[key];
    if (!src) return (btn.hidden = true);
    btn.querySelector("img").src = src;
    btn.addEventListener("click", () => handleFile(dataUrlToFile(src, `sample-${key}.jpg`)));
  });

  async function handleFile(file) {
    showExtractError("");
    if (state.file) return showExtractError(t("newImageSession"));
    if (!file.type.startsWith("image/")) return showExtractError(t("errNotImage"));
    if (file.size > cfg.MAX_IMAGE_MB * 1024 * 1024) return showExtractError(t("errTooBig", { mb: cfg.MAX_IMAGE_MB }));

    stopAll();
    cancelExtraction();
    const requestId = extractSequence;
    extractController = new AbortController();
    state.file = file;
    state.text = "";
    state.report = null;
    state.language = "none";
    $("lang-select").value = "none";
    $("extracted-text").value = "";
    state.confidence = null;
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    previewUrl = URL.createObjectURL(file);
    $("preview").src = previewUrl;
    $("preview").alt = file.name || "Uploaded image";
    $("preview").hidden = false;
    $("drop-empty").hidden = true;
    dz.classList.add("has-image");
    $("image-actions").hidden = false;
    $("file-name").textContent = file.name || "pasted-image.png";

    setExtractState("loading");
    const stopStages = runStages();
    stopExtractStages = stopStages;
    try {
      const res = await API.extract(file, state.sessionId, extractController.signal);
      if (requestId !== extractSequence) { API.closeSession(res.session_id).catch(() => {}); return; }
      await stopStages();
      if (requestId !== extractSequence) return;
      const sourceLabel = `${t("reportText")}:\n`;
      const sourceText = res.text || t("noTextExtracted");
      const summaryLabel = `\n\n${t("reportSummary")}:\n`;
      state.text = sourceLabel + sourceText + summaryLabel + res.summary;
      state.report = {
        text: state.text, sourceStart: sourceLabel.length, sourceEnd: sourceLabel.length + sourceText.length,
        summaryStart: sourceLabel.length + sourceText.length + summaryLabel.length,
        labelLanguage: state.uiLang, summaryLanguage: res.summary_language || "en",
      };
      state.language = res.language || "none";
      state.ready = true;
      prepareSourceSpeech();
      $("extracted-text").value = state.text;
      $("lang-select").value = state.language;
      state.confidence = res.confidence?.method === "model_estimate" ? res.confidence : null;
      setExtractState("ready");
      addMessage("assistant", t("gotImage"), { speakable: false }).dataset.uiText = "1";
      warnIfNoVoice();
    } catch (err) {
      if (requestId !== extractSequence || err.name === "AbortError") return;
      console.error(err);
      state.file = null;
      stopStages(true);
      setExtractState("empty");
      showExtractError(err.message || t("errExtract"));
    } finally {
      if (requestId === extractSequence) {
        extractController = null;
        stopExtractStages = null;
      }
    }
    applyI18n();
  }

  // Fake progress: real backend gives one response, so stages advance on a timer
  // and all finish when the response arrives.
  function runStages() {
    const items = [...document.querySelectorAll("#extract-loading li")];
    items.forEach((li) => (li.dataset.status = "todo"));
    let i = 0;
    const step = () => { if (i > 0) items[i - 1].dataset.status = "done"; if (i < items.length) items[i].dataset.status = "active"; i++; };
    step();
    const timer = setInterval(() => { if (i < items.length) step(); }, 550);
    return (failed) => {
      clearInterval(timer);
      if (failed) return;
      items.forEach((li) => (li.dataset.status = "done"));
      return new Promise((r) => setTimeout(r, 250));
    };
  }

  function setExtractState(s) {
    $("extract-card").dataset.state = s;
    const loading = s === "loading";
    $("extract-loading").hidden = !loading;
    $("extracted-text").hidden = loading;
    $("extracted-text").disabled = s !== "ready";
    $("lang-select").disabled = s !== "ready";
    $("play-btn").disabled = s !== "ready";
    $("stop-btn").disabled = s !== "ready";
    $("copy-btn").disabled = s !== "ready";
    $("suggestions").hidden = s !== "ready";
    $("extract-hint").textContent = loading ? t("reading") : t("editHint");
    renderConfidence();
  }
  function showExtractError(msg) { $("extract-error").textContent = msg; $("extract-error").hidden = !msg; }

  $("extracted-text").addEventListener("input", (e) => {
    state.text = e.target.value;
    renderConfidence();
    stopAll();
    Speech.clear?.();
    clearTimeout(prepareSpeechTimer);
    prepareSpeechTimer = setTimeout(prepareSourceSpeech, 300);
  });
  $("copy-btn").addEventListener("click", async () => {
    try { await navigator.clipboard.writeText(state.text); }
    catch (_) { const ta = $("extracted-text"); ta.focus(); ta.select(); document.execCommand && document.execCommand("copy"); }
    const label = $("copy-label");
    label.textContent = t("copied");
    setTimeout(() => (label.textContent = t("copy")), 1500);
  });
  $("lang-select").addEventListener("change", (e) => { state.language = e.target.value; stopAll(); Speech.clear?.(); prepareSourceSpeech(); warnIfNoVoice(); });

  function warnIfNoVoice() {
    $("extract-hint").textContent = t("editHint");
  }

  // ---------- read aloud ----------
  let playing = null; // "source" | message element | null
  function sourceLanguage() { return state.language === "none" ? state.uiLang : state.language; }
  function sourceLanguageRanges() {
    const report = state.report;
    if (!report) return null;
    let start = report.sourceStart, end = report.sourceEnd, summary = report.summaryStart;
    if (report.text !== state.text) {
      // Corrections in the textarea change offsets, but the UI's headings
      // must not become spoken content as a side effect of those edits.
      const prefix = report.text.slice(0, report.sourceStart);
      const separator = report.text.slice(report.sourceEnd, report.summaryStart);
      const index = state.text.lastIndexOf(separator);
      if (!state.text.startsWith(prefix) || index < prefix.length) return null;
      start = prefix.length; end = index; summary = index + separator.length;
    }
    return [{ start, end, language: sourceLanguage() },
      { start: summary, end: state.text.length, language: report.summaryLanguage }];
  }
  function prepareSourceSpeech() {
    if (!state.ready || !Speech.prepare) return;
    // Warm the audio cache silently in the background; the UI only reports
    // "Preparing audio…" once the user actually presses Read aloud.
    Promise.resolve(Speech.prepare(state.text, sourceLanguage(), { languageRanges: sourceLanguageRanges() })).catch(() => {});
  }
  function updatePlayButton() {
    const srcPlaying = playing === "source";
    const paused = srcPlaying && Speech.paused;
    const preparing = srcPlaying && Speech.loading;
    $("play-label").textContent = preparing ? t("preparingSpeech") : !srcPlaying ? t("readAloud") : paused ? t("resume") : t("pause");
    $("play-btn").setAttribute("aria-busy", String(preparing));
    $("play-icon").setAttribute("d", srcPlaying && !paused ? "M7 5h4v14H7zM13 5h4v14h-4z" : "M8 5v14l11-7z");
    $("play-btn").classList.toggle("is-playing", srcPlaying && !paused);
  }
  $("play-btn").addEventListener("click", () => {
    if (playing === "source") {
      if (Speech.loading) return;
      Speech.paused ? Speech.resume() : Speech.pause();
      return setTimeout(updatePlayButton, 30);
    }
    speak(state.text, sourceLanguage(), "source");
  });
  function stopAll() {
    Speech.stop(); playing = null; refreshPlaying();
    if ($("mic-note").dataset.speech === "loading") $("mic-note").hidden = true;
    $("mic-note").dataset.speech = "";
  }
  $("stop-btn").addEventListener("click", stopAll);
  $("rate").addEventListener("input", (e) => ($("rate-out").textContent = Number(e.target.value).toFixed(1) + "×"));

  // Word-by-word highlight while the source text is read aloud
  let wordSpans = [];
  function showReadingView(text) {
    const view = $("reading-view");
    view.textContent = "";
    wordSpans = [];
    const re = /\S+/g;
    let last = 0, m;
    while ((m = re.exec(text))) {
      view.append(document.createTextNode(text.slice(last, m.index)));
      const span = document.createElement("span");
      span.className = "w";
      span.textContent = m[0];
      span.dataset.start = m.index;
      view.append(span);
      wordSpans.push(span);
      last = m.index + m[0].length;
    }
    view.append(document.createTextNode(text.slice(last)));
    view.style.height = $("extracted-text").offsetHeight + "px";
    view.hidden = false;
    $("extracted-text").hidden = true;
  }
  function hideReadingView() {
    if ($("reading-view").hidden) return;
    $("reading-view").hidden = true;
    $("extracted-text").hidden = false;
  }
  function highlightAt(charIndex) {
    let cur = null;
    for (const s of wordSpans) {
      const start = Number(s.dataset.start);
      if (start <= charIndex) { s.classList.add("said"); cur = s; } else s.classList.remove("said");
      s.classList.remove("now");
    }
    if (cur) {
      cur.classList.add("now");
      const view = $("reading-view");
      const top = cur.offsetTop - view.offsetTop;
      if (top < view.scrollTop || top > view.scrollTop + view.clientHeight - 40) view.scrollTop = top - 20;
    }
  }

  function speak(text, lang, owner) {
    if (!text.trim()) return;
    if (owner === "source") showReadingView(text); else hideReadingView();
    Speech.speak(text, lang, {
      rate: Number($("rate").value),
      languageRanges: owner === "source" ? sourceLanguageRanges() : null,
      onBoundary: owner === "source" ? highlightAt : null,
      onStart: () => { playing = owner; refreshPlaying(); },
      onState: (status) => {
        const note = $("mic-note");
        if (status === "loading") { note.dataset.speech = "loading"; note.textContent = t("preparingSpeech"); note.hidden = false; }
        else if (note.dataset.speech === "loading") { note.dataset.speech = ""; note.hidden = true; }
        refreshPlaying();
      },
      onEnd: () => { if (playing === owner) { playing = null; refreshPlaying(); } },
      onError: (error) => { $("mic-note").dataset.speech = "error"; $("mic-note").textContent = error.message || t("speechError"); $("mic-note").hidden = false; },
    });
    playing = owner;
    refreshPlaying();
  }
  function refreshPlaying() {
    if (playing !== "source") hideReadingView();
    updatePlayButton();
    document.querySelectorAll(".msg-speak").forEach((b) => b.classList.toggle("is-playing", playing === b.closest(".msg")));
  }

  // ---------- chat ----------
  function addMessage(role, text, { speakable = true, pending = false } = {}) {
    const li = document.createElement("li");
    li.className = `msg msg-${role}` + (pending ? " is-pending" : "");
    const who = document.createElement("span");
    who.className = "msg-who";
    who.dataset.i18n = role === "user" ? "you" : "assistant";
    who.textContent = t(who.dataset.i18n);
    const body = document.createElement("p");
    body.className = "msg-body";
    body.textContent = text;
    li.append(who, body);
    if (role === "assistant" && speakable) addSpeakButton(li);
    $("messages").append(li);
    li.scrollIntoView({ block: "end", behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
    return li;
  }
  function addSpeakButton(li, prepare = true) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "msg-speak";
    b.setAttribute("aria-label", t("listen"));
    b.title = t("listen");
    b.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 9v6h4l5 4V5L8 9H4z" fill="currentColor"/><path d="M16 8.5a5 5 0 0 1 0 7M18.5 6a8.5 8.5 0 0 1 0 12" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>';
    b.addEventListener("click", () => {
      if (playing === li) { stopAll(); return; }
      speak(li.querySelector(".msg-body").textContent, messageVoice(li), li);
    });
    li.append(b);
    if (prepare) Speech.prepare?.(li.querySelector(".msg-body").textContent, messageVoice(li));
  }
  // Interface strings are in the UI language. Answers are requested in it too,
  // but can quote a French sign or be written in French, so detect each
  // sentence and quotation and fall back to the requested language.
  function messageVoice(li) {
    return li.dataset.uiText ? state.uiLang : "auto:" + (li.dataset.lang || replyLang());
  }
  // Answers come back in the interface language, so an English speaker can
  // understand a French sign and the other way round.
  const replyLang = () => state.uiLang;

  document.querySelectorAll("[data-ask]").forEach((chip) =>
    chip.addEventListener("click", () => { $("chat-input").value = t(chip.dataset.ask); send(); })
  );

  $("chat-form").addEventListener("submit", (e) => { e.preventDefault(); send(); });
  $("chat-input").addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } });
  $("chat-input").addEventListener("input", autoGrow);
  function autoGrow() { const el = $("chat-input"); el.style.height = "auto"; el.style.height = Math.min(el.scrollHeight, 160) + "px"; }

  async function send() {
    const input = $("chat-input");
    const message = input.value.trim();
    if (!message || state.busy || state.stopListening) return;
    if (!state.ready) { $("mic-note").textContent = t("uploadFirst"); $("mic-note").hidden = false; return; }
    Speech.unlock?.();
    stopAll();
    const sequence = ++chatSequence;
    chatController = new AbortController();
    input.value = "";
    autoGrow();
    addMessage("user", message);
    state.busy = true;
    $("send-btn").disabled = true;
    $("mic-btn").disabled = true;
    const pending = addMessage("assistant", t("thinking"), { speakable: false, pending: true });
    try {
      const res = await API.chat({
        sessionId: state.sessionId,
        message,
        // The model already has the original reading; send only the user's edits.
        contextText: state.report && state.text !== state.report.text ? state.text : "",
        language: replyLang(),
      }, chatController.signal);
      if (sequence !== chatSequence) return;
      pending.classList.remove("is-pending");
      pending.querySelector(".msg-body").textContent = res.reply;
      pending.dataset.lang = res.language || replyLang();
      addSpeakButton(pending);
      if ($("auto-read").checked) speak(res.reply, messageVoice(pending), pending);
    } catch (err) {
      if (sequence !== chatSequence || err.name === "AbortError") return;
      console.error(err);
      pending.classList.remove("is-pending");
      pending.classList.add("is-error");
      pending.querySelector(".msg-body").textContent = err.message || t("errChat");
      if (!input.value) input.value = message;
    } finally {
      if (sequence === chatSequence) {
        state.busy = false;
        chatController = null;
        $("send-btn").disabled = false;
        $("mic-btn").disabled = false;
        input.focus();
      }
    }
  }

  // ---------- voice input ----------
  $("mic-btn").addEventListener("click", () => {
    const note = $("mic-note");
    if (state.busy) return;
    if (!state.ready) { note.textContent = t("uploadFirst"); note.hidden = false; return; }
    if (state.stopListening) { state.stopListening(); return; }
    if (!Speech.canListen) { note.textContent = t("micUnsupported"); note.hidden = false; return; }
    stopAll();
    note.textContent = t("listening");
    note.hidden = false;
    $("mic-btn").classList.add("is-listening");
    $("send-btn").disabled = true;
    const session = state.sessionId;
    let failed = false;
    state.stopListening = Speech.listen(replyLang(), {
      onResult: (text) => { if (session !== state.sessionId) return; state.stopListening = null; $("chat-input").value = text; autoGrow(); send(); },
      onState: (status) => {
        if (session !== state.sessionId) return;
        note.textContent = t(status === "transcribing" ? "transcribing" : "listening");
        $("mic-btn").disabled = status === "transcribing";
        $("mic-btn").classList.toggle("is-listening", status === "recording");
      },
      onError: (err) => { if (session !== state.sessionId) return; failed = true; note.textContent = err.code === "not-allowed" ? t("micDenied") : err.message || t("speechError"); },
      onEnd: () => {
        if (session !== state.sessionId) return;
        state.stopListening = null;
        $("mic-btn").classList.remove("is-listening");
        $("send-btn").disabled = state.busy;
        $("mic-btn").disabled = state.busy;
        if (!failed) note.hidden = true;
      },
    });
  });

  // ---------- top bar ----------
  document.querySelectorAll("[data-ui-lang]").forEach((b) =>
    b.addEventListener("click", () => { state.uiLang = b.dataset.uiLang; store.set("uiLang", state.uiLang); applyI18n(); })
  );
  $("text-smaller").addEventListener("click", () => setScale(state.textScale - 0.1));
  $("text-larger").addEventListener("click", () => setScale(state.textScale + 0.1));
  function setScale(v) { state.textScale = Math.round(Math.min(1.5, Math.max(0.9, v)) * 10) / 10; store.set("textScale", state.textScale); applyScale(); }
  $("new-session").addEventListener("click", resetSession);

  function resetSession() {
    const oldSession = state.sessionId;
    chatSequence++;
    chatController?.abort();
    chatController = null;
    stopAll();
    clearTimeout(prepareSpeechTimer);
    Speech.clear?.();
    cancelExtraction();
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    previewUrl = null;
    state.stopListening?.abort();
    if (state.file) API.closeSession(oldSession).catch(() => {});
    Object.assign(state, { sessionId: newId(), ready: false, busy: false, stopListening: null, file: null, text: "", report: null, confidence: null, language: "none" });
    $("send-btn").disabled = false;
    $("mic-btn").disabled = false;
    $("mic-btn").classList.remove("is-listening");
    $("mic-note").hidden = true;
    $("chat-input").value = "";
    autoGrow();
    playing = null;
    $("preview").hidden = true;
    $("preview").removeAttribute("src");
    $("drop-empty").hidden = false;
    dz.classList.remove("has-image");
    $("image-actions").hidden = true;
    $("extracted-text").value = "";
    $("lang-select").value = "none";
    showExtractError("");
    setExtractState("empty");
    $("messages").innerHTML = "";
    const w = addMessage("assistant", t("welcome"), { speakable: false });
    // The static greeting must not occupy the voice engine while OCR arrives.
    addSpeakButton(w, false);
    w.dataset.uiText = "1";
    w.querySelector(".msg-body").dataset.i18n = "welcome"; // re-translates with the UI
    applyI18n();
  }

  // ---------- start ----------
  window.addEventListener("pagehide", () => {
    cancelExtraction();
    chatSequence++;
    chatController?.abort();
    state.stopListening?.abort();
    Speech.stop();
    clearTimeout(prepareSpeechTimer);
    Speech.clear?.();
    if (state.file) API.closeSession(state.sessionId).catch(() => {});
    if (previewUrl) URL.revokeObjectURL(previewUrl);
  });
  applyScale();
  applyTheme();
  resetSession();
  checkBackend();
})();
