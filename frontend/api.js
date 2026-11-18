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
  function localSpeechUrl(path) {
    const target = new URL(url(path), window.location.href);
    if (!["localhost", "127.0.0.1", "[::1]"].includes(target.hostname)) {
      throw new Error("Open Lumen on localhost to use speech on your own device.");
    }
    return target.href;
  }
  window.API = {
    async health() { return json(await fetch(url("/api/health"))); },
    async extract(image, sessionId, signal) {
      const form = new FormData();
      form.append("image", image);
      form.append("session_id", sessionId);
      const result = await json(await fetch(url("/api/extract"), { method: "POST", body: form, signal }));
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
    async chat({ sessionId, message, contextText, language }, signal) {
      const result = await json(await fetch(url("/api/chat"), {
        method: "POST", headers: { "Content-Type": "application/json" }, signal,
        body: JSON.stringify({ session_id: sessionId, message, context_text: contextText, language }),
      }));
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
