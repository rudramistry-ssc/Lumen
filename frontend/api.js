// All calls to the backend live here. See API_CONTRACT.md.
// With APP_CONFIG.USE_MOCK = true, fake responses are returned instead.
(function () {
  const cfg = window.APP_CONFIG;
  const base = () => cfg.API_BASE_URL.replace(/\/$/, "");

  async function request(path, options) {
    const res = await fetch(base() + path, options);
    if (!res.ok) {
      let detail = res.statusText;
      try { detail = (await res.json()).detail || detail; } catch (_) {}
      throw new Error(`${res.status}: ${detail}`);
    }
    return res.json();
  }

  // ---------- real backend ----------
  const real = {
    health: () => request("/api/health"),

    // -> { text, language: "en"|"fr"|"mixed", confidence?: 0..1 }
    extract(file, sessionId) {
      const form = new FormData();
      form.append("image", file);
      form.append("session_id", sessionId);
      return request("/api/extract", { method: "POST", body: form });
    },

    // -> { reply, language }
    chat({ sessionId, message, contextText, language, history }) {
      return request("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: sessionId,
          message,
          context_text: contextText,
          language,
          history, // [{ role: "user"|"assistant", content }]
        }),
      });
    },
  };

  // ---------- fake backend for UI work ----------
  // Text matches the sample photos in samples/, so the demo looks real.
  const SAMPLES = {
    en: {
      text: "NOTICE\nElevator out of service.\nPlease use the stairs at the end of the hallway.\nRepairs are expected to be finished by Friday at 5:00 PM.\nFor help, call building services at ext. 4410.",
      replies: {
        when: { en: "The notice says repairs should be finished by Friday at 5:00 PM.", fr: "Selon l'avis, les réparations devraient être terminées vendredi à 17 h." },
        summary: { en: "The elevator is broken. Take the stairs at the end of the hallway until Friday at 5 PM.", fr: "L'ascenseur est en panne. Prenez l'escalier au bout du couloir jusqu'à vendredi 17 h." },
        todo: { en: "Use the stairs at the end of the hallway. If you need help, call building services at extension 4410.", fr: "Utilisez l'escalier au bout du couloir. Pour de l'aide, composez le poste 4410 des services de l'immeuble." },
        translate: { en: "In French:\nAVIS. Ascenseur hors service. Veuillez utiliser l'escalier au bout du couloir. Les réparations devraient être terminées vendredi à 17 h.", fr: "En français :\nAVIS. Ascenseur hors service. Veuillez utiliser l'escalier au bout du couloir. Les réparations devraient être terminées vendredi à 17 h." },
      },
    },
    fr: {
      text: "AVIS\nExercice d'évacuation incendie\nUn exercice aura lieu le jeudi 30 octobre à 10 h.\nLorsque l'alarme sonne, quittez l'immeuble par l'escalier le plus proche.\nN'utilisez pas les ascenseurs.",
      replies: {
        when: { en: "The fire drill is on Thursday, October 30 at 10 AM.", fr: "L'exercice d'incendie aura lieu le jeudi 30 octobre à 10 h." },
        summary: { en: "There's a fire drill on Thursday, October 30 at 10 AM. When the alarm rings, leave by the nearest stairs. Don't use the elevators.", fr: "Exercice d'incendie le jeudi 30 octobre à 10 h. Quand l'alarme sonne, sortez par l'escalier le plus proche, sans prendre l'ascenseur." },
        todo: { en: "When the alarm rings, leave the building by the nearest staircase. Do not take the elevator.", fr: "Quand l'alarme sonne, quittez l'immeuble par l'escalier le plus proche. Ne prenez pas l'ascenseur." },
        translate: { en: "In English:\nNOTICE. Fire evacuation drill. A drill will take place on Thursday, October 30 at 10 AM. When the alarm rings, leave the building by the nearest stairs. Do not use the elevators.", fr: "En anglais :\nNOTICE. Fire evacuation drill. A drill will take place on Thursday, October 30 at 10 AM. When the alarm rings, leave the building by the nearest stairs. Do not use the elevators." },
      },
    },
    mixed: {
      text: "CAUTION · ATTENTION\nWet floor\nPlancher mouillé\nPlease walk carefully.\nVeuillez marcher prudemment.",
      replies: {
        when: { en: "The sign doesn't give a time. It's a warning that the floor is wet right now.", fr: "L'affiche n'indique pas d'heure. Elle avertit que le plancher est mouillé en ce moment." },
        summary: { en: "It's a caution sign: the floor is wet, so walk carefully.", fr: "C'est un avertissement : le plancher est mouillé, marchez prudemment." },
        todo: { en: "Walk slowly and carefully in this area, or go around the wet spot if you can.", fr: "Marchez lentement et prudemment dans cette zone, ou contournez la partie mouillée si possible." },
        translate: { en: "This sign is already in both languages. English: Wet floor, please walk carefully. French: Plancher mouillé, veuillez marcher prudemment.", fr: "Cette affiche est déjà bilingue. Anglais : Wet floor, please walk carefully. Français : Plancher mouillé, veuillez marcher prudemment." },
      },
    },
  };
  const INTENTS = [
    ["translate", /translat|tradui|in english|in french|en anglais|en français/],
    ["when", /when|quand|time|heure|date|jour|day/],
    ["todo", /should|what do i|what can i|dois|faire|que faire/],
    ["summary", /summar|résum|mean|veut dire|what does|say|dit/],
  ];
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  let mockCount = 0;

  function sampleFor(contextText) {
    return Object.values(SAMPLES).find((s) => contextText && contextText.includes(s.text.split("\n")[1]));
  }

  const mock = {
    async health() { await wait(150); return { status: "mock" }; },

    async extract(file) {
      await wait(1600);
      const name = (file.name || "").toLowerCase();
      let language;
      if (/fail|error/.test(name)) throw new Error("mock failure");
      if (/mix|bil/.test(name)) language = "mixed";
      else if (/fr/.test(name)) language = "fr";
      else if (/en/.test(name)) language = "en";
      else language = ["en", "fr", "mixed"][mockCount++ % 3];
      return { text: SAMPLES[language].text, language, confidence: [0.94, 0.91, 0.88][["en", "fr", "mixed"].indexOf(language)] };
    },

    async chat({ message, contextText, language }) {
      await wait(900);
      const fr = language === "fr";
      if (!contextText) {
        return { reply: fr ? "Ajoutez d'abord une photo pour que je puisse lire le texte." : "Add a photo first so I have some text to read.", language };
      }
      const q = message.toLowerCase();
      const intent = (INTENTS.find(([, re]) => re.test(q)) || [])[0];
      const sample = sampleFor(contextText);
      if (sample && intent) {
        return { reply: sample.replies[intent][fr ? "fr" : "en"], language: intent === "translate" ? "mixed" : language };
      }
      return { reply: fr ? "Je peux répondre aux questions sur le texte de cette affiche. Demandez-moi ce qu'elle dit, quoi faire, quand c'est, ou une traduction." : "I can answer questions about the text on this sign. Ask me what it says, what to do, when it is, or for a translation.", language };
    },
  };

  window.API = new Proxy({}, { get: (_, k) => (cfg.USE_MOCK ? mock : real)[k] });
})();
