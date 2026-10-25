// Agents HQ office: a pixel-art office drawn on a canvas. Every staff agent has a desk and a character;
// the character types when that agent is working, shows its task in a speech bubble, and ticks a check
// when it finishes. The lead sits at the front desk. The brain, the inbox and the work shelf show live counts.
// Everything is drawn in code, no image files. Reads window.HQ (working, finished, status) from app.html.
(() => {
  const W = 384, H = 216;                                 // scene size in "pixels" (each drawn s×s on screen)
  const canvas = document.getElementById("office");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  let s = 3, frame = 0;

  const DESKS = {                                          // where each staff member sits
    "clip-editor":   { x: 52,  y: 66,  name: "Clip editor",   shirt: "#ffd400", hair: "#3b2a1a" },
    "brand-checker": { x: 152, y: 66,  name: "Brand checker", shirt: "#f87171", hair: "#1c1c1c" },
    "scriptwriter":  { x: 252, y: 66,  name: "Scriptwriter",  shirt: "#60a5fa", hair: "#8b5a2b" },
    "scout":         { x: 52,  y: 126, name: "Scout",         shirt: "#4ade80", hair: "#d9a066" },
    "copywriter":    { x: 152, y: 126, name: "Copywriter",    shirt: "#c084fc", hair: "#1c1c1c" },
    "analyst":       { x: 252, y: 126, name: "Analyst",       shirt: "#22d3ee", hair: "#6b3e26" },
  };
  const LEAD = { x: 22, y: 176, name: "Lead", shirt: "#e8eaf0", hair: "#2b2b2b" };

  const px = (x, y, w, h, c) => { ctx.fillStyle = c; ctx.fillRect(Math.round(x * s), Math.round(y * s), Math.round(w * s), Math.round(h * s)); };
  const text = (str, x, y, opt = {}) => {
    ctx.font = `${opt.bold ? "600 " : ""}${Math.max(8, opt.size || 11)}px -apple-system, "Segoe UI", Inter, Roboto, sans-serif`;
    ctx.textAlign = opt.align || "center"; ctx.textBaseline = "middle"; ctx.fillStyle = opt.color || "#e8eaf0";
    ctx.fillText(str, x * s, y * s);
  };

  function resize() {
    const box = canvas.parentElement.getBoundingClientRect();
    s = Math.max(1, Math.min(4, box.width / W));            // fractional: the scene fills the width it gets, phone or desktop
    canvas.width = Math.round(W * s); canvas.height = Math.round(H * s);
    canvas.style.width = canvas.width + "px"; canvas.style.height = canvas.height + "px";
  }

  function room() {
    px(0, 0, W, 40, "#2b3340"); px(0, 38, W, 2, "#1e242e");                     // wall and skirting
    for (const wx of [40, 140, 240]) {                                            // windows, night sky outside
      px(wx, 8, 36, 24, "#141a2a"); px(wx + 2, 10, 32, 20, "#1d2a4a"); px(wx + 17, 10, 2, 20, "#2b3340"); px(wx + 2, 19, 32, 2, "#2b3340");
      px(wx + 6, 13, 1, 1, "#e8eaf0"); px(wx + 26, 24, 1, 1, "#e8eaf0"); px(wx + 12, 26, 1, 1, "#ffd400");
    }
    for (let y = 40; y < H; y += 16) for (let x = 0; x < W; x += 16) px(x, y, 16, 16, ((x + y) / 16) % 2 ? "#1b1f27" : "#1e232c");
    px(0, 196, 28, 20, "#262c38"); px(2, 198, 24, 18, "#1a1e26"); px(20, 206, 2, 2, "#ffd400");     // door
    text("AGENTS HQ", 192, 26, { size: 10 * s / 3 * 1.1, bold: true, color: "#8b93a7" });
    const t = new Date(); px(176, 4, 32, 10, "#171a21"); text(`${String(t.getHours()).padStart(2, "0")}:${String(t.getMinutes()).padStart(2, "0")}`, 192, 9, { size: 8 * s / 3 * 1.2, color: "#8b93a7" });
  }

  function desk(d, working, finished) {
    px(d.x, d.y, 44, 14, "#6b4a2b"); px(d.x, d.y + 14, 44, 2, "#4a331d");                       // desk top and edge
    px(d.x + 4, d.y + 16, 2, 6, "#4a331d"); px(d.x + 38, d.y + 16, 2, 6, "#4a331d");             // legs
    const glow = working ? (frame % 6 < 3 ? "#67e8f9" : "#22d3ee") : "#2a2f3a";
    px(d.x + 14, d.y - 10, 16, 11, "#111317"); px(d.x + 15, d.y - 9, 14, 9, glow); px(d.x + 21, d.y + 1, 2, 2, "#111317");   // monitor
    if (working) for (let i = 0; i < 4; i++) px(d.x + 17, d.y - 7 + i * 2, 4 + ((frame + i) % 4) * 2, 1, "#0e7490");
    px(d.x + 30, d.y + 6, 8, 2, "#2a2f3a"); px(d.x + 6, d.y + 4, 6, 4, "#e8eaf0");             // keyboard, papers
    chair(d.x + 17, d.y + 18);
    person(d.x + 17, d.y + 14, d, working);
    text(d.name, d.x + 22, d.y + 36, { size: 9 * s / 3 * 1.15, color: working ? "#4ade80" : "#8b93a7" });
    if (working) bubble(d.x + 22, d.y - 16, working);
    else if (finished && Date.now() - finished < 3500) bubble(d.x + 22, d.y - 16, "✓ done", "#4ade80");
  }

  const chair = (x, y) => { px(x - 1, y + 8, 12, 3, "#3a4150"); px(x + 4, y + 11, 2, 3, "#3a4150"); };

  function person(x, y, who, working) {
    const typing = working && frame % 4 < 2, blink = !working && frame % 24 === 0;
    px(x + 2, y - 12, 6, 6, "#f1c9a5"); px(x + 2, y - 13, 6, 2, who.hair); px(x + 1, y - 12, 1, 3, who.hair);   // head, hair
    if (!blink) { px(x + 3, y - 9, 1, 1, "#1c1c1c"); px(x + 6, y - 9, 1, 1, "#1c1c1c"); }                       // eyes
    px(x + 1, y - 6, 8, 7, who.shirt);                                                                           // body
    px(x + (typing ? 0 : 1), y - (typing ? 5 : 3), 2, 4, "#f1c9a5"); px(x + (typing ? 8 : 7), y - (typing ? 5 : 3), 2, 4, "#f1c9a5");   // arms
    px(x + 2, y + 1, 2, 4, "#2a2f3a"); px(x + 6, y + 1, 2, 4, "#2a2f3a");                                       // legs
  }

  function bubble(cx, cy, str, color) {
    const label = str.length > 30 ? str.slice(0, 29) + "…" : str;
    ctx.font = `${Math.max(8, 10 * s / 3 * 1.2)}px -apple-system, "Segoe UI", Inter, Roboto, sans-serif`;
    const w = ctx.measureText(label).width / s + 10, h = Math.max(12, 14 / s * 1.2), x = Math.max(2, Math.min(W - w - 2, cx - w / 2)), y = cy - h;
    px(x, y, w, h, "#ffffff"); px(cx - 2, y + h, 4, 2, "#ffffff"); px(cx - 1, y + h + 2, 2, 1, "#ffffff");
    text(label, x + w / 2, y + h / 2, { size: 10 * s / 3 * 1.2, color: color || "#111317" });
  }

  function props(st) {
    const rules = (st && st.brain && st.brain["Brand rules"]) || 0, clips = (st && st.inbox.clips.length) || 0, waiting = (st && st.waiting_for_approval.length) || 0;
    px(336, 44, 28, 44, "#171a21"); px(338, 46, 24, 40, "#0f1115");                                                  // the brain: a server rack
    for (let i = 0; i < 5; i++) { px(340, 49 + i * 7, 20, 5, "#1e222b"); px(357, 51 + i * 7, 2, 1, (frame + i) % 5 === 0 ? "#ffd400" : "#4ade80"); }
    text("BRAIN", 350, 96, { bold: true, size: 9 * s / 3 * 1.15, color: "#8b93a7" }); text(`${rules} rules`, 350, 105, { size: 9 * s / 3 * 1.15, color: "#ffd400" });
    px(86, 184, 30, 12, "#3a4150"); px(88, 186, 26, 8, "#262c38");                                                 // inbox tray with clips stacked
    for (let i = 0; i < Math.min(clips, 5); i++) px(90 + i * 5, 180 - i, 4, 6, i % 2 ? "#e8eaf0" : "#ffd400");
    text("INBOX", 101, 203, { bold: true, size: 9 * s / 3 * 1.15, color: clips ? "#ffd400" : "#8b93a7" }); text(`${clips} clips`, 101, 211, { size: 8 * s / 3 * 1.15, color: "#8b93a7" });
    px(282, 176, 48, 3, "#6b4a2b"); px(282, 192, 48, 3, "#6b4a2b");                                                 // work shelf with finished reels
    for (let i = 0; i < Math.min(waiting, 6); i++) { px(285 + i * 7, 180, 6, 11, "#111317"); px(286 + i * 7, 181, 4, 9, "#ffd400"); }
    text("WORK", 306, 203, { bold: true, size: 9 * s / 3 * 1.15, color: waiting ? "#ffd400" : "#8b93a7" }); text(`${waiting} waiting for OK`, 306, 212, { size: 8 * s / 3 * 1.15, color: "#8b93a7" });
    px(352, 140, 16, 22, "#3a4150"); px(354, 142, 12, 8, "#0f1115"); px(358, 152, 4, 6, "#e8eaf0"); if (frame % 8 < 4) px(359, 148, 1, 2, "#8b93a7");   // coffee machine
    px(366, 196, 10, 8, "#6b4a2b"); px(367, 184, 8, 12, "#2f8f4e"); px(369, 180, 4, 6, "#3fae5f");                 // plant
  }

  function lead(busy) {
    px(LEAD.x, LEAD.y, 56, 14, "#6b4a2b"); px(LEAD.x, LEAD.y + 14, 56, 2, "#4a331d"); px(LEAD.x + 6, LEAD.y + 4, 14, 6, "#e8eaf0");
    px(LEAD.x + 36, LEAD.y - 10, 16, 11, "#111317"); px(LEAD.x + 37, LEAD.y - 9, 14, 9, busy ? "#67e8f9" : "#2a2f3a");
    chair(LEAD.x + 20, LEAD.y + 18); person(LEAD.x + 20, LEAD.y + 14, LEAD, busy);
    text("Lead", LEAD.x + 28, LEAD.y + 36, { size: 9 * s / 3 * 1.15, color: busy ? "#4ade80" : "#8b93a7" });
    if (busy) bubble(LEAD.x + 28, LEAD.y - 16, "working" + ".".repeat(1 + frame % 3));
  }

  function draw() {
    const hq = window.HQ || {}, st = hq.status ? hq.status() : null, working = hq.working || {}, finished = hq.finished || {};
    frame++;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    room();
    for (const [id, d] of Object.entries(DESKS)) desk(d, working[id], finished[id]);
    props(st);
    lead(!!(st && st.desk && st.desk.busy));
  }

  window.addEventListener("resize", () => { resize(); draw(); });
  resize(); draw();
  setInterval(draw, 160);
})();
