// Frontend settings. Change these when the backend is ready.
window.APP_CONFIG = {
  // Project name shown everywhere. Change it here only.
  APP_NAME: "Lumen",

  // Show the launch screen when the app opens
  SHOW_INTRO: true,

  // true  = use fake responses (no backend needed, good for UI work)
  // false = call the real FastAPI backend
  USE_MOCK: false,

  // "" means same origin (FastAPI serves this folder).
  // Use e.g. "http://127.0.0.1:8000" if the frontend is opened separately.
  API_BASE_URL: "",

  // Biggest image we send, in MB
  MAX_IMAGE_MB: 10,
};
