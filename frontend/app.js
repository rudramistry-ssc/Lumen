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
    showExtractError("");
    if (!file.type.startsWith("image/")) return showExtractError(t("errNotImage"));
    if (file.size > cfg.MAX_IMAGE_MB * 1024 * 1024) return showExtractError(t("errTooBig", { mb: cfg.MAX_IMAGE_MB }));

    stopAll();
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
      state.text = res.text || "";
      state.language = res.language || "en";
      $("extracted-text").value = state.text;
      $("lang-select").value = state.language;
      $("confidence").textContent = res.confidence != null ? `${Math.round(res.confidence * 100)}%` : "";
      setExtractState("ready");
      addMessage("assistant", t("gotText", { lang: langName(state.language) }), { speakable: false }).dataset.uiText = "1";
      warnIfNoVoice();
    } catch (err) {
      console.error(err);
      stopStages(true);
      setExtractState("empty");
      showExtractError(t("errExtract"));
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
  }
  function showExtractError(msg) { $("extract-error").textContent = msg; $("extract-error").hidden = !msg; }

  $("extracted-text").addEventListener("input", (e) => (state.text = e.target.value));
  $("copy-btn").addEventListener("click", async () => {
    try { await navigator.clipboard.writeText(state.text); }
    catch (_) { const ta = $("extracted-text"); ta.focus(); ta.select(); document.execCommand && document.execCommand("copy"); }
    const label = $("copy-label");
    label.textContent = t("copied");
    setTimeout(() => (label.textContent = t("copy")), 1500);
  });
  $("lang-select").addEventListener("change", (e) => { state.language = e.target.value; stopAll(); warnIfNoVoice(); });

  function warnIfNoVoice() {
    const need = state.language === "mixed" ? ["en", "fr"] : [state.language];
    const missing = need.filter((l) => Speech.supported && speechSynthesis.getVoices().length && !Speech.hasLocalVoice(l));
    if (missing.length) $("extract-hint").textContent = t("noVoice", { lang: missing.map(langName).join(" / ") });
  }

  // ---------- read aloud ----------
  let playing = null; // "source" | message element | null
  function updatePlayButton() {
    const srcPlaying = playing === "source";
    const paused = srcPlaying && Speech.paused;
    $("play-label").textContent = !srcPlaying ? t("readAloud") : paused ? t("resume") : t("pause");
    $("play-icon").setAttribute("d", srcPlaying && !paused ? "M7 5h4v14H7zM13 5h4v14h-4z" : "M8 5v14l11-7z");
    $("play-btn").classList.toggle("is-playing", srcPlaying && !paused);
  }
  $("play-btn").addEventListener("click", () => {
    if (playing === "source") {
      Speech.paused ? Speech.resume() : Speech.pause();
      return setTimeout(updatePlayButton, 30);
    }
    speak(state.text, state.language, "source");
  });
  function stopAll() { Speech.stop(); playing = null; refreshPlaying(); }
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
    b.addEventListener("click", () => {
      if (playing === li) { Speech.stop(); playing = null; return refreshPlaying(); }
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
    if (!message || state.busy) return;
    input.value = "";
    autoGrow();
    addMessage("user", message);
    state.busy = true;
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
      state.history.push({ role: "user", content: message }, { role: "assistant", content: res.reply });
      pending.classList.remove("is-pending");
      pending.querySelector(".msg-body").textContent = res.reply;
      pending.dataset.lang = res.language || replyLang();
      addSpeakButton(pending);
      if ($("auto-read").checked) speak(res.reply, pending.dataset.lang, pending);
    } catch (err) {
      console.error(err);
      pending.classList.remove("is-pending");
      pending.classList.add("is-error");
      pending.querySelector(".msg-body").textContent = t("errChat");
    } finally {
      state.busy = false;
      $("send-btn").disabled = false;
      input.focus();
    }
  }

  // ---------- voice input ----------
  // Preferred path: record with MediaRecorder and upload the clip. It works
  // offline and needs no cloud speech service. If the browser cannot record,
  // fall back to SpeechRecognition (Chrome/Edge, online only).
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
    try {
      const blob = await current.stop();
      if (!blob || !blob.size) { showNote("micEmpty"); return; }
      showNote("micUploading");
      const res = await API.uploadAudio(state.sessionId, blob);
      const audio = $("mic-preview");
      audio.src = apiUrl(res.audio_url);
      audio.hidden = false;
      showNote("micRecorded");
    } catch (err) {
      console.error(err);
      showNote("micUploadFailed");
    } finally {
      uploading = false;
    }
  }

  async function startRecording() {
    if (starting) return; // ignore double-clicks while the mic prompt is open
    starting = true;
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
    }
    setMicState(true);
    showNote("micRecording");
  }

  $("mic-btn").addEventListener("click", () => {
    if (uploading || starting) return;
    if (recorder) { stopRecordingAndUpload(); return; }
    if (state.stopListening) { state.stopListening(); return; }
    if (Speech.canRecord) { startRecording(); return; }
    if (!Speech.canListen) { showNote("micUnsupported"); return; }

    // Fallback: the browser's cloud recognition, used only when recording is
    // unavailable. It needs an internet connection.
    stopAll();
    showNote("listening");
    setMicState(true);
    state.stopListening = Speech.listen(replyLang(), {
      onResult: (text) => { $("chat-input").value = text; autoGrow(); send(); },
      onError: (err) => {
        if (err === "not-allowed") showNote("micDenied");
        else if (err === "network") showNote("micNetwork");
        else showNote("micUnsupported");
      },
      onEnd: () => {
        state.stopListening = null;
        setMicState(false);
        if ($("mic-note").textContent === t("listening")) hideNote();
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
    Object.assign(state, { sessionId: newId(), file: null, text: "", language: "en", history: [] });
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
