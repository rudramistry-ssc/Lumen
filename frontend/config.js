// Frontend settings.
window.APP_CONFIG = {
  // Project name shown everywhere. Change it here only.
  APP_NAME: "Lumen",

  // Show the launch screen when the app opens
  SHOW_INTRO: true,

  // false = call the real backend (start it with `python run.py`)
  // true  = fake responses, no backend needed (good for UI work)
  // Adding ?demo to the address also turns on fake responses, e.g.
  // http://localhost:5500/?demo — a safe fallback if the backend fails live.
  USE_MOCK: new URLSearchParams(location.search).has("demo"),

  // Where the backend runs. "" would mean the same address as this page.
  API_BASE_URL: "http://127.0.0.1:8000",

  // Biggest image we send, in MB (the backend accepts up to 15)
  MAX_IMAGE_MB: 10,
};
