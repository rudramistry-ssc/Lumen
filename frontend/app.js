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
    file: null,
    text: "",
    language: "en",
    history: [], // [{ role, content }]
    document: null,
    extracting: false,
    busy: false,
    stopListening: null,
  };

  function newId() {
    return (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + Math.random().toString(16).slice(2)).slice(0, 8);
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
    $("session-label").textContent = `· ${t("session")} ${state.sessionId}`;
    updatePlayButton();
    renderDocumentReview();
    if (state.document) $("extract-hint").textContent = t("documentReadHint");
    renderStatus();
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
  $("replace-image").addEventListener("click", () => $("file-input").click());
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
    if (state.extracting || state.busy || uploading || starting || recorder) return;
    showExtractError("");
    if (!file.type.startsWith("image/")) return showExtractError(t("errNotImage"));
    if (file.size > cfg.MAX_IMAGE_MB * 1024 * 1024) return showExtractError(t("errTooBig", { mb: cfg.MAX_IMAGE_MB }));

    stopAll();
    state.extracting = true;
    state.document = null;
    state.text = "";
    $("extracted-text").value = "";
    $("new-session").disabled = true;
    $("send-btn").disabled = true;
    $("mic-btn").disabled = true;
    renderDocumentReview();
    state.file = file;
    const url = URL.createObjectURL(file);
    $("preview").src = url;
    $("preview").alt = file.name || "Uploaded image";
    $("preview").hidden = false;
    $("drop-empty").hidden = true;
    dz.classList.add("has-image");
    $("image-actions").hidden = false;
    $("file-name").textContent = file.name || "pasted-image.png";

    setExtractState("loading");
    const stopStages = runStages();
    try {
      const res = await API.extract(file, state.sessionId);
      await stopStages();
      state.document = res.status ? res : null;
      state.text = res.text || "";
      state.language = res.language || "";
      state.history = [];
      $("messages").textContent = "";
      $("extracted-text").value = state.text;
      $("lang-select").value = state.language;
      $("confidence").textContent = res.confidence != null ? `${Math.round(res.confidence * 100)}%` : "";
      setExtractState("ready");
      addMessage("assistant", res.status ? t("documentReady") : t("gotText", { lang: langName(state.language) }), { speakable: false }).dataset.uiText = "1";
      warnIfNoVoice();
    } catch (err) {
      console.error(err);
      stopStages(true);
      setExtractState("empty");
      showExtractError(`${t("errExtract")} ${err.message || ""}`);
    } finally {
      state.extracting = false;
      $("new-session").disabled = false;
      $("send-btn").disabled = state.document?.status === "ocr_unreviewed_fallback";
      $("mic-btn").disabled = state.document?.status === "ocr_unreviewed_fallback";
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
    $("extracted-text").readOnly = !!state.document;
    $("lang-select").disabled = s !== "ready";
    $("play-btn").disabled = s !== "ready" || (!state.text.trim() && !state.document?.visual_descriptions?.length) || state.document?.status === "ocr_unreviewed_fallback";
    $("stop-btn").disabled = s !== "ready";
    $("copy-btn").disabled = s !== "ready";
    $("suggestions").hidden = s !== "ready" || state.document?.status === "ocr_unreviewed_fallback";
    $("extract-hint").textContent = loading ? t("reading") : t(state.document ? "documentReadHint" : "editHint");
  }
  function showExtractError(msg) { $("extract-error").textContent = msg; $("extract-error").hidden = !msg; }

  function renderDocumentReview() {
    const doc = state.document;
    $("document-review").hidden = !doc;
    if (!doc) return;
    $("document-status").textContent = t(doc.status === "ocr_unreviewed_fallback" ? "documentFallback" : "documentNeedsReview");
    const warnings = $("document-warnings");
    warnings.textContent = "";
    for (const warning of doc.warnings || []) {
      const li = document.createElement("li");
      li.textContent = typeof warning === "string" ? warning : JSON.stringify(warning);
      warnings.append(li);
    }
    const descriptions = $("document-descriptions");
    descriptions.textContent = "";
    for (const description of doc.visual_descriptions || []) {
      const li = document.createElement("li");
      li.textContent = description.text;
      descriptions.append(li);
    }
    $("document-visuals").hidden = !(doc.visual_descriptions || []).length;
    $("document-metadata").textContent = JSON.stringify({
      session_id: doc.session_id, document_id: doc.document_id,
      status: doc.status, selected_method: doc.selected_method,
      printed_text_status: doc.printed_text_status,
      sections: doc.sections, text_observations: doc.text_observations,
      ocr_comparison: doc.ocr_comparison, guardrails: doc.guardrails,
      cache_hit: doc.cache_hit, execution_this_call: doc.execution_this_call,
    }, null, 2);
  }

  $("extracted-text").addEventListener("input", (e) => {
    state.text = e.target.value;
    $("play-btn").disabled = !state.text.trim() || state.document?.status === "ocr_unreviewed_fallback";
  });
  $("copy-btn").addEventListener("click", async () => {
    try { await navigator.clipboard.writeText(state.text); }
    catch (_) { const ta = $("extracted-text"); ta.focus(); ta.select(); document.execCommand && document.execCommand("copy"); }
    const label = $("copy-label");
    label.textContent = t("copied");
    setTimeout(() => (label.textContent = t("copy")), 1500);
  });
  $("lang-select").addEventListener("change", (e) => { state.language = e.target.value; stopAll(); warnIfNoVoice(); });

  function warnIfNoVoice() {
    if (state.document) return;
    const need = state.language === "mixed" ? ["en", "fr"] : [state.language];
    const missing = need.filter((l) => Speech.supported && speechSynthesis.getVoices().length && !Speech.hasLocalVoice(l));
    if (missing.length) $("extract-hint").textContent = t("noVoice", { lang: missing.map(langName).join(" / ") });
  }

  // ---------- read aloud ----------
  let playing = null; // "source" | message element | null
  const mediaPlayer = new Audio();
  let playbackGeneration = 0;
  let readingDocument = false;
  function playbackEnded() { playing = null; refreshPlaying(); }
  mediaPlayer.addEventListener("ended", playbackEnded);
  mediaPlayer.addEventListener("pause", updatePlayButton);
  mediaPlayer.addEventListener("play", updatePlayButton);
  mediaPlayer.addEventListener("error", () => {
    playbackEnded();
    showExtractError(t("errPlayback"));
  });
  function updatePlayButton() {
    const srcPlaying = playing === "source";
    const paused = srcPlaying && (state.document ? mediaPlayer.paused : Speech.paused);
    $("play-label").textContent = !srcPlaying ? t("readAloud") : paused ? t("resume") : t("pause");
    $("play-icon").setAttribute("d", srcPlaying && !paused ? "M7 5h4v14H7zM13 5h4v14h-4z" : "M8 5v14l11-7z");
    $("play-btn").classList.toggle("is-playing", srcPlaying && !paused);
  }
  $("play-btn").addEventListener("click", async () => {
    if (readingDocument) return;
    if (state.document) {
      if (playing === "source") {
        if (mediaPlayer.paused) {
          try { await mediaPlayer.play(); }
          catch (err) { showExtractError(`${t("errPlayback")} ${err.message}`); }
        } else mediaPlayer.pause();
        return;
      }
      stopAll();
      const generation = playbackGeneration;
      const doc = state.document;
      const language = ["en", "fr"].includes(state.language) ? state.language : state.uiLang;
      readingDocument = true;
      $("play-btn").disabled = true;
      showExtractError("");
      try {
        if (!doc.audio_url || doc.audio_language !== language) {
          const res = await API.readDocument(state.sessionId, language);
          doc.audio_url = res.audio_url;
          doc.audio_language = language;
        }
        if (generation === playbackGeneration) await playAudio(doc.audio_url, "source");
      } catch (err) {
        if (generation === playbackGeneration) showExtractError(`${t("errPlayback")} ${err.message}`);
      } finally {
        readingDocument = false;
        if (state.document === doc) $("play-btn").disabled = false;
      }
      return;
    }
    if (playing === "source") {
      Speech.paused ? Speech.resume() : Speech.pause();
      return setTimeout(updatePlayButton, 30);
    }
    speak(state.text, state.language, "source");
  });
  function stopAll() {
    playbackGeneration++;
    mediaPlayer.pause();
    mediaPlayer.removeAttribute("src");
    mediaPlayer.load();
    Speech.stop();
    playing = null;
    refreshPlaying();
  }
  async function playAudio(url, owner) {
    stopAll();
    mediaPlayer.src = apiUrl(url);
    mediaPlayer.playbackRate = Number($("rate").value);
    playing = owner;
    refreshPlaying();
    try { await mediaPlayer.play(); }
    catch (err) { playing = null; refreshPlaying(); throw err; }
  }
  $("stop-btn").addEventListener("click", stopAll);
  $("rate").addEventListener("input", (e) => {
    $("rate-out").textContent = Number(e.target.value).toFixed(1) + "×";
    mediaPlayer.playbackRate = Number(e.target.value);
  });

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
    stopAll();
    if (owner === "source") showReadingView(text); else hideReadingView();
    Speech.speak(text, lang, {
      rate: Number($("rate").value),
      onBoundary: owner === "source" ? highlightAt : null,
      onStart: () => { playing = owner; refreshPlaying(); },
      onEnd: () => { if (playing === owner) { playing = null; refreshPlaying(); } },
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
  function addSpeakButton(li) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "msg-speak";
    b.setAttribute("aria-label", t("listen"));
    b.title = t("listen");
    b.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 9v6h4l5 4V5L8 9H4z" fill="currentColor"/><path d="M16 8.5a5 5 0 0 1 0 7M18.5 6a8.5 8.5 0 0 1 0 12" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>';
    b.addEventListener("click", async () => {
      if (playing === li) return stopAll();
      if (li.dataset.audioUrl) {
        try { await playAudio(li.dataset.audioUrl, li); }
        catch (err) { showExtractError(`${t("errPlayback")} ${err.message}`); }
        return;
      }
      speak(li.querySelector(".msg-body").textContent, li.dataset.uiText ? state.uiLang : li.dataset.lang || replyLang(), li);
    });
    li.append(b);
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
    if (!message || state.busy || state.extracting || uploading || starting || recorder) return;
    if (state.document?.status === "ocr_unreviewed_fallback") {
      showNote("documentFallback");
      return;
    }
    input.value = "";
    autoGrow();
    addMessage("user", message);
    state.busy = true;
    $("new-session").disabled = true;
    $("send-btn").disabled = true;
    const pending = addMessage("assistant", t("thinking"), { speakable: false, pending: true });
    try {
      const res = await API.chat({
        sessionId: state.sessionId,
        message,
        contextText: state.text,
        language: replyLang(),
        history: state.history,
      });
      const blocked = res.status === "blocked";
      if (!blocked) state.history.push({ role: "user", content: message }, { role: "assistant", content: res.reply });
      pending.classList.remove("is-pending");
      pending.querySelector(".msg-body").textContent = res.reply;
      pending.dataset.lang = res.language || replyLang();
      if (res.audio_url && !blocked) pending.dataset.audioUrl = res.audio_url;
      if (res.errors?.length) {
        const note = document.createElement("p");
        note.className = "hint";
        note.textContent = t("answerTextOnly") + " " + res.errors.map((error) => error.message).join(" ");
        pending.append(note);
      }
      if (!blocked && (!state.document || res.audio_url)) addSpeakButton(pending);
      if (blocked) pending.classList.add("is-notice");
      if ($("auto-read").checked && !blocked) {
        if (res.audio_url) {
          try { await playAudio(res.audio_url, pending); }
          catch (err) { showExtractError(`${t("errPlayback")} ${err.message}`); }
        } else if (!state.document) speak(res.reply, pending.dataset.lang, pending);
      }
    } catch (err) {
      console.error(err);
      pending.classList.remove("is-pending");
      pending.classList.add("is-error");
      pending.querySelector(".msg-body").textContent = `${t("errChat")} ${err.message || ""}`;
    } finally {
      state.busy = false;
      $("new-session").disabled = false;
      $("send-btn").disabled = false;
      input.focus();
    }
  }

  // ---------- voice input ----------
  // Document audio is transcribed locally; the user must press Send after review.
  let recorder = null;
  let uploading = false;
  let starting = false; // true while the browser is asking for the mic

  function setMicState(active) {
    $("mic-btn").classList.toggle("is-listening", active);
    $("mic-btn").setAttribute("aria-pressed", String(active));
  }

  function showNote(key, vars) {
    const note = $("mic-note");
    note.textContent = t(key, vars);
    note.hidden = false;
  }

  function hideNote() {
    const note = $("mic-note");
    note.hidden = true;
    note.textContent = "";
  }

  // Relative media URLs need the API origin when the UI is served separately;
  // blob: URLs from demo mode are used as-is.
  function apiUrl(path) {
    if (!path || /^(blob:|data:|https?:)/i.test(path)) return path || "";
    return (cfg.API_BASE_URL || "").replace(/\/$/, "") + path;
  }

  async function stopRecordingAndUpload() {
    if (!recorder) return;
    const current = recorder;
    recorder = null;
    setMicState(false);
    uploading = true;
    $("new-session").disabled = true;
    $("send-btn").disabled = true;
    $("mic-btn").disabled = true;
    $("chat-input").disabled = true;
    try {
      const blob = await current.stop();
      if (!blob || !blob.size) { showNote("micEmpty"); return; }
      if (state.document) {
        showNote("micTranscribing");
        const res = await API.transcribe(state.sessionId, blob);
        if (res.status === "ready_for_review") {
          $("chat-input").value = res.review_text;
          autoGrow();
          showNote("micReview");
          const warnings = res.transcription?.warnings || [];
          if (warnings.length) $("mic-note").textContent += " " + warnings.join(" ");
          $("chat-input").focus();
        } else {
          showNote("micNoTranscript");
          $("mic-note").textContent += ` (${res.status})`;
        }
      } else {
        showNote("micUploading");
        const res = await API.uploadAudio(state.sessionId, blob);
        const audio = $("mic-preview");
        audio.src = apiUrl(res.audio_url);
        audio.hidden = false;
        showNote("micRecorded");
      }
    } catch (err) {
      console.error(err);
      showNote("micUploadFailed");
      $("mic-note").textContent += " " + (err.message || "");
    } finally {
      uploading = false;
      $("new-session").disabled = false;
      $("send-btn").disabled = false;
      $("mic-btn").disabled = false;
      $("chat-input").disabled = false;
      $("chat-input").focus();
    }
  }

  async function startRecording() {
    if (starting) return; // ignore double-clicks while the mic prompt is open
    starting = true;
    $("new-session").disabled = true;
    hideNote();
    stopAll();
    try {
      recorder = await Speech.record({
        maxMs: 60000,
        onAutoStop: () => stopRecordingAndUpload(),
      });
    } catch (err) {
      const code = err && err.name === "NotAllowedError" ? "micDenied"
        : err && err.name === "NotFoundError" ? "micNoDevice"
        : "micUnsupported";
      showNote(code);
      return;
    } finally {
      starting = false;
      $("new-session").disabled = !!recorder;
    }
    setMicState(true);
    showNote("micRecording");
  }

  $("mic-btn").addEventListener("click", () => {
    if (uploading || starting || state.busy || state.extracting) return;
    if (recorder) { stopRecordingAndUpload(); return; }
    if (state.document?.status === "ocr_unreviewed_fallback") { showNote("documentFallback"); return; }
    if ($("chat-input").value.trim()) { showNote("micDraft"); return; }
    if (Speech.canRecord) { startRecording(); return; }
    showNote("micUnsupported");
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
    stopAll();
    if (state.stopListening) state.stopListening();
    if (recorder) { const r = recorder; recorder = null; r.stop().catch(() => {}); }
    uploading = false;
    setMicState(false);
    hideNote();
    const micPreview = $("mic-preview");
    micPreview.pause();
    micPreview.hidden = true;
    micPreview.removeAttribute("src");
    Object.assign(state, { sessionId: newId(), file: null, text: "", language: "en", history: [], document: null });
    $("send-btn").disabled = false;
    $("mic-btn").disabled = false;
    $("chat-input").value = "";
    renderDocumentReview();
    playing = null;
    $("preview").hidden = true;
    $("preview").removeAttribute("src");
    $("drop-empty").hidden = false;
    dz.classList.remove("has-image");
    $("image-actions").hidden = true;
    $("extracted-text").value = "";
    $("confidence").textContent = "";
    $("lang-select").value = "en";
    showExtractError("");
    setExtractState("empty");
    $("messages").innerHTML = "";
    const w = addMessage("assistant", t("welcome"), { speakable: true });
    w.dataset.uiText = "1";
    w.querySelector(".msg-body").dataset.i18n = "welcome"; // re-translates with the UI
    applyI18n();
  }

  // ---------- start ----------
  applyScale();
  applyTheme();
  resetSession();
  checkBackend();
})();
