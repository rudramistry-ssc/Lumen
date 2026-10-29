// Landing page: scan-bar hero animation, tile animation, navigation, launch.
(function () {
  const cfg = window.APP_CONFIG;
  const body = document.body;
  const landing = document.getElementById("intro");
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;

  // Project name everywhere
  document.querySelectorAll(".app-name").forEach((el) => (el.textContent = cfg.APP_NAME));
  document.title = `${cfg.APP_NAME} · CanAI Garage`;

  // ---------- hero: clusters of flickering vertical light bars ----------
  const canvas = document.getElementById("hero-canvas");
  const ctx = canvas.getContext("2d");
  let W = 0, H = 0, blocks = [], running = false, t = 0, scanY = 0;
  const STEP = 4; // px between bars
  const PALETTE = [
    [52, 213, 154],  // neon green
    [202, 230, 220], // pale green
    [255, 255, 255], // white
    [74, 222, 128],  // light green
    [45, 160, 140],  // teal
  ];

  function rand(a, b) { return a + Math.random() * (b - a); }
  function spawn(initial) {
    const cols = Math.round(rand(4, 26));
    // more activity toward the right, like a light source off-frame
    const x = Math.round((Math.pow(Math.random(), 0.6) * (W + 40) - 20) / STEP) * STEP;
    const h = rand(H * 0.06, H * 0.42);
    return {
      x, cols, h,
      y: rand(-h * 0.3, H * 0.75),
      c: PALETTE[(Math.random() * (Math.random() < 0.55 ? 2 : PALETTE.length)) | 0],
      peak: rand(0.4, 1),
      life: initial ? rand(0, 1) : 0,
      speed: rand(0.002, 0.009),
      seed: Math.random() * 1000,
      gaps: rand(0.15, 0.5),
    };
  }
  function resize() {
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    W = canvas.clientWidth; H = canvas.clientHeight;
    canvas.width = W * dpr; canvas.height = H * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const n = Math.round(Math.min(95, W / 15));
    blocks = Array.from({ length: n }, () => spawn(true));
  }
  // cheap deterministic noise per column
  const hash = (n) => { const s = Math.sin(n * 127.1) * 43758.5453; return s - Math.floor(s); };

  function draw() {
    ctx.clearRect(0, 0, W, H);
    ctx.globalCompositeOperation = "lighter";
    scanY = (scanY + H / 420) % (H + 120);
    for (const b of blocks) {
      b.life += b.speed;
      if (b.life >= 1) { Object.assign(b, spawn(false)); continue; }
      const env = Math.sin(b.life * Math.PI); // fade in, fade out
      for (let i = 0; i < b.cols; i++) {
        const n = hash(b.seed + i);
        if (n < b.gaps) continue; // missing bars give the glitchy texture
        const flick = 0.55 + 0.45 * Math.sin(t * (0.04 + n * 0.12) + n * 40);
        // the scan line brightens what it passes, like reading a page
        const cy = b.y + b.h / 2;
        const scanBoost = Math.max(0, 1 - Math.abs(scanY - 60 - cy) / 90) * 0.6;
        const a = Math.min(1, b.peak * env * flick * (0.6 + n * 0.6) + scanBoost * env);
        if (a < 0.02) continue;
        const x = b.x + i * STEP;
        const hh = b.h * (0.55 + 0.45 * hash(b.seed + i * 3.7));
        const y = b.y + (b.h - hh) * hash(b.seed + i * 9.1);
        const [r, g, bl] = b.c;
        const grad = ctx.createLinearGradient(0, y, 0, y + hh);
        grad.addColorStop(0, `rgba(${r},${g},${bl},0)`);
        grad.addColorStop(0.5, `rgba(${r},${g},${bl},${a})`);
        grad.addColorStop(1, `rgba(${r},${g},${bl},0)`);
        ctx.fillStyle = grad;
        ctx.fillRect(x, y, n > 0.8 ? 2 : 1.5, hh);
        if (a > 0.45) { ctx.globalAlpha = 0.22; ctx.fillRect(x - 1.5, y, 5, hh); ctx.globalAlpha = 1; } // soft glow
      }
    }
    // the scan line itself
    const sg = ctx.createLinearGradient(0, scanY - 60, 0, scanY - 58);
    sg.addColorStop(0, "rgba(52,213,154,0)");
    sg.addColorStop(1, "rgba(52,213,154,0.18)");
    ctx.fillStyle = sg;
    ctx.fillRect(0, scanY - 61, W, 1);
    ctx.globalCompositeOperation = "source-over";
  }
  function loop() {
    if (!running) return;
    t++;
    draw();
    requestAnimationFrame(loop);
  }
  function start() {
    if (running) return;
    resize();
    if (reduce) { t = 200; for (const b of blocks) b.life = 0.5; draw(); return; }
    running = true;
    requestAnimationFrame(loop);
  }
  function stop() { running = false; }
  window.addEventListener("resize", () => { if (body.classList.contains("show-intro")) { resize(); if (reduce) draw(); } });

  // ---------- tile: dot grid that "scans" a sign ----------
  const grid = document.getElementById("scan-grid");
  const COLS = 22, ROWS = 9;
  // which cells are "text": row -> [start, end]
  const LINES = { 1: [3, 18], 3: [2, 20], 4: [2, 15], 6: [2, 19], 7: [2, 11] };
  const cells = [];
  for (let r = 0; r < ROWS; r++) for (let c = 0; c < COLS; c++) {
    const i = document.createElement("i");
    const L = LINES[r];
    i.dataset.text = L && c >= L[0] && c <= L[1] ? "1" : "";
    grid.append(i);
    cells.push(i);
  }
  let scanStep = 0;
  function scanTick() {
    const row = scanStep % (ROWS + 4);
    cells.forEach((el, idx) => {
      const r = Math.floor(idx / COLS);
      el.classList.toggle("on", !!el.dataset.text && r < row);
      el.classList.toggle("mid", r === row);
    });
    scanStep++;
  }
  scanTick();
  const scanTimer = reduce ? null : setInterval(() => { if (body.classList.contains("show-intro")) scanTick(); }, 380);
  if (reduce) { scanStep = ROWS; scanTick(); }

  // ---------- in-page links ----------
  document.querySelectorAll("[data-scroll]").forEach((a) =>
    a.addEventListener("click", (e) => {
      e.preventDefault();
      const target = document.getElementById(a.dataset.scroll);
      if (a.dataset.scroll === "top") landing.scrollTo({ top: 0, behavior: reduce ? "auto" : "smooth" });
      else if (target) landing.scrollTo({ top: target.offsetTop - 70, behavior: reduce ? "auto" : "smooth" });
    })
  );

  // ---------- open / close ----------
  function launch() {
    if (!body.classList.contains("show-intro")) return;
    body.classList.remove("show-intro");
    landing.setAttribute("aria-hidden", "true");
    landing.inert = true;
    document.getElementById("app").inert = false;
    setTimeout(stop, 700);
    setTimeout(() => document.getElementById("dropzone").focus({ preventScroll: true }), 600);
  }
  function showLanding() {
    body.classList.add("show-intro");
    landing.removeAttribute("aria-hidden");
    landing.inert = false;
    document.getElementById("app").inert = true;
    landing.scrollTop = 0;
    start();
  }
  document.querySelectorAll("[data-launch]").forEach((b) => b.addEventListener("click", launch));
  document.getElementById("brand-home").addEventListener("click", showLanding);

  if (cfg.SHOW_INTRO) showLanding();
  else launch();
})();
