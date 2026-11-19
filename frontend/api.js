(function () {
  const url = (path) => window.APP_CONFIG.API_BASE_URL.replace(/\/$/, "") + path;
  async function checked(response) {
    if (response.ok) return response;
    const result = await response.json().catch(() => ({}));
    const error = new Error(typeof result.detail === "string" ? result.detail : "The request failed. Please try again.");
    error.status = response.status;
    throw error;
  }
  const json = async (response) => (await checked(response)).json();
  const LIVE = "application/x-ndjson";
  // Live results: while the model writes, the server sends one JSON object per
  // line ({"partial": ...}); the last line is the result or {"error", "status"}.
  // A plain JSON response (no streaming) is accepted too.
  async function live(response, onProgress) {
    response = await checked(response);
    const type = (response.headers && response.headers.get && response.headers.get("content-type")) || "";
    if (!type.includes(LIVE) || !response.body) return response.json();
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "", final = null;
    const handle = (line) => {
      if (!line.trim()) return;
      const event = JSON.parse(line);
      if (event.error !== undefined) {
        const error = new Error(typeof event.error === "string" ? event.error : "The request failed. Please try again.");
        error.status = event.status;
        throw error;
      }
      if (event.partial !== undefined) { if (onProgress) onProgress(event.partial); }
      else final = event.result !== undefined ? event.result : event;
    };
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      for (let end = buffer.indexOf("\n"); end >= 0; end = buffer.indexOf("\n")) {
        handle(buffer.slice(0, end));
        buffer = buffer.slice(end + 1);
      }
    }
    handle(buffer + decoder.decode());
    if (!final) throw new Error("The connection closed before the result arrived. Please try again.");
    return final;
  }
  function localSpeechUrl(path) {
    const target = new URL(url(path), window.location.href);
    if (!["localhost", "127.0.0.1", "[::1]"].includes(target.hostname)) {
      throw new Error("Open Lumen on localhost to use speech on your own device.");
    }
    return target.href;
  }
  window.API = {
    async health() { return json(await fetch(url("/api/health"))); },
    // onProgress({text, summary}) receives the reading while the model writes it.
    async extract(image, sessionId, signal, onProgress) {
      const form = new FormData();
      form.append("image", image);
      form.append("session_id", sessionId);
      const result = await live(await fetch(url("/api/extract"), {
        method: "POST", body: form, signal, headers: { Accept: LIVE },
      }), onProgress);
      if (typeof result.text !== "string" || typeof result.summary !== "string" || typeof result.session_id !== "string"
          || !["en", "fr", "mixed", "none"].includes(result.language)) {
        throw new Error("The server returned an incomplete result. Please try again.");
      }
      if (result.confidence !== undefined) {
        const confidence = result.confidence;
        const valid = value => value === null || (Number.isInteger(value) && value >= 0 && value <= 100);
        if (!confidence || confidence.method !== "model_estimate" || !valid(confidence.text) || !valid(confidence.summary)) {
          throw new Error("The server returned invalid confidence estimates. Please try again.");
        }
      }
      return result;
    },
    // onProgress(text) receives the answer while the model writes it.
    async chat({ sessionId, message, contextText, language }, signal, onProgress) {
      const result = await live(await fetch(url("/api/chat"), {
        method: "POST", headers: { "Content-Type": "application/json", Accept: LIVE }, signal,
        body: JSON.stringify({ session_id: sessionId, message, context_text: contextText, language }),
      }), onProgress);
      if (typeof result.reply !== "string" || !result.reply.trim()) throw new Error("The model returned an empty reply.");
      return result;
    },
    async closeSession(sessionId) {
      await checked(await fetch(url("/api/sessions/" + encodeURIComponent(sessionId)), { method: "DELETE", keepalive: true }));
    },
    async transcribe(audio, language, signal) {
      const form = new FormData();
      form.append("audio", audio, "question");
      form.append("language", language);
      return json(await fetch(localSpeechUrl("/api/speech/transcribe"), { method: "POST", body: form, signal }));
    },
    async synthesize(text, language, signal) {
      const response = await checked(await fetch(localSpeechUrl("/api/speech/synthesize"), {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text, language }), signal,
      }));
      return response.blob();
    },
  };
})();
