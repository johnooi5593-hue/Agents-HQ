// Agents HQ · HUD. Every HTML overlay over the 3D office, the data refresh loop and the lead's run stream.
// Owns window.HQ (contract: status, teams, agents, running, subagents, send, toast). Talks to the scene only
// through window.HQ_OFFICE when it exists (hq/office3d.js dispatches "hq-office-ready" once the scene is built).
// Plain ES2020, no framework. Sections: helpers · state · data · top bar · billboards · toasts · minimap ·
// panels (team, tasks, calendar, brain) · voice · ask box · agent card · lead log + run stream · office life · scene hookup.
// Office life (the scene's idle-agent simulation): the agent card says who an agent is talking with and about what
// (HQ_OFFICE.lifeOf), a shared lesson raises a soft toast at most every 2 minutes (HQ_OFFICE.onLife), and the user menu
// has an "Office life: on/off" switch remembered in localStorage ("hq.officeLife").
(() => {
  "use strict";

  // ---------- helpers ----------
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const el = (html) => { const t = document.createElement("template"); t.innerHTML = html.trim(); return t.content.firstElementChild; };
  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
  const pad2 = (n) => String(n).padStart(2, "0");
  const isoDate = (d) => `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`;
  const todayISO = () => isoDate(new Date());
  const isToday = (iso) => !!iso && String(iso).slice(0, 10) === todayISO();
  const fmtInt = (n) => Number(n || 0).toLocaleString("en-US");
  const cap = (s) => (s ? s[0].toUpperCase() + s.slice(1) : "");
  const cssq = (s) => (window.CSS && CSS.escape ? CSS.escape(s) : String(s).replace(/["\\]/g, "\\$&"));
  const BAR_H = 46;                                         // --bar-h in hud.css: billboards never slide under the top bar
  // Phones: the same query as the phone block in hud.css and PHONE_Q in office3d.js
  const PHONE_Q = "(max-width: 600px), (max-height: 500px) and (max-width: 1000px)";
  const phoneMQ = window.matchMedia ? window.matchMedia(PHONE_Q) : null;
  const isPhone = () => !!(phoneMQ && phoneMQ.matches);
  const fmtTime = (t) => String(t || "").replace(/^0(\d:)/, "$1");   // "09:00" → "9:00" like the video
  const DOW = ["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"];
  const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];

  function timeAgo(iso) {
    const t = typeof iso === "number" ? iso : Date.parse(iso || "");
    if (!t) return "";
    const s = Math.max(0, (Date.now() - t) / 1000);
    if (s < 45) return "just now";
    if (s < 3600) return `${Math.round(s / 60)}m ago`;
    if (s < 86400) return `${Math.round(s / 3600)}h ago`;
    return `${Math.round(s / 86400)}d ago`;
  }
  function relDay(iso) {                                   // "today" · "tomorrow" · "in 3 days" · "yesterday"
    if (!iso) return "";
    const a = new Date(iso + "T00:00:00"), b = new Date(todayISO() + "T00:00:00");
    const d = Math.round((a - b) / 86400000);
    return d === 0 ? "today" : d === 1 ? "tomorrow" : d === -1 ? "yesterday" : d > 1 ? `in ${d} days` : `${-d} days ago`;
  }
  const initials = (label) => String(label || "?").split(/[\s\-_]+/).filter(Boolean).slice(0, 2).map((w) => w[0].toUpperCase()).join("");
  function hex2rgb(hex) { const h = String(hex || "#888").replace("#", ""); const n = parseInt(h.length === 3 ? h.split("").map((c) => c + c).join("") : h, 16); return [(n >> 16) & 255, (n >> 8) & 255, n & 255]; }
  const rgb2hex = (r, g, b) => "#" + [r, g, b].map((v) => pad2(clamp(Math.round(v), 0, 255).toString(16))).join("");
  function mix(a, b, t) { const x = hex2rgb(a), y = hex2rgb(b); return rgb2hex(x[0] + (y[0] - x[0]) * t, x[1] + (y[1] - x[1]) * t, x[2] + (y[2] - x[2]) * t); }
  const lighten = (hex, t) => mix(hex, "#ffffff", t), darken = (hex, t) => mix(hex, "#000000", t);
  function hashColor(s) { let h = 0; for (const c of String(s)) h = (h * 31 + c.charCodeAt(0)) >>> 0; return `hsl(${h % 360} 45% 45%)`; }
  function seeded(key) { let x = 0; for (const c of String(key)) x = (x * 33 + c.charCodeAt(0)) >>> 0; return () => { x = (x * 1664525 + 1013904223) >>> 0; return x / 4294967296; }; }

  // inline SVG glyphs: UI icons and one glyph per team (keyed by team key)
  const ICON = {
    search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
    mic: '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/>',
    send: '<path d="m22 2-7 20-4-9-9-4Z"/><path d="M22 2 11 13"/>',
    close: '<path d="M18 6 6 18M6 6l12 12"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    list: '<path d="M4 6h16M4 12h16M4 18h10"/>',
    check: '<path d="m5 12 5 5L20 7"/>',
    play: '<path d="m8 5 12 7-12 7z"/>',
    folder: '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    brain: '<circle cx="12" cy="12" r="3"/><circle cx="12" cy="12" r="8"/><path d="M12 4v2M12 18v2M4 12h2M18 12h2"/>',
    cal: '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/>',
    chief: '<path d="M12 3 4 7v5c0 5 3.5 8.5 8 9 4.5-.5 8-4 8-9V7z"/><path d="m9 12 2 2 4-4"/>',
    research: '<circle cx="11" cy="11" r="6"/><path d="m20 20-4.5-4.5"/>',
    scripts: '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/>',
    social: '<path d="M21 12a8 8 0 0 1-11.6 7.1L4 21l1.9-5.4A8 8 0 1 1 21 12Z"/>',
    creative: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m10 9 5 3-5 3z" fill="currentColor"/>',
    analytics: '<path d="M5 20V11M11 20V5M17 20v-7"/>',
    shop: '<path d="M6 8h12l1 12H5Z"/><path d="M9 8a3 3 0 0 1 6 0"/>',
    dev: '<path d="m8 7-5 5 5 5M16 7l5 5-5 5"/>',
    inbox: '<path d="M3 13h5l2 3h4l2-3h5"/><path d="M5 5h14l2 8v6H3v-6z"/>',
  };
  const svg = (name, cls = "i") => `<svg class="${cls}" viewBox="0 0 24 24" aria-hidden="true">${ICON[name] || ""}</svg>`;
  const teamGlyph = (t) => (t && ICON[t.key] ? svg(t.key) : esc((t && (t.icon || t.name[0])) || "•"));

  // ---------- state ----------
  const state = {
    status: null, teams: [], agents: [], brain: null, brainNotes: null,
    notifs: [], notifTotal: 0, notifSeeded: false, unread: 0,
    view: "office", panelTeam: null, panelTab: "overview", focused: null,
    filter: "all", openDetail: null, calMonth: new Date().toISOString().slice(0, 7), calDays: {},
    askAgent: null,
    run: { id: null, offset: 0, quiet: false, seen: new Set(), prompt: "" },
    hookRunning: null, evOffset: 0, hookSig: "", hookAt: 0,   // the hook feed's {agent: count}, polled every 2 s from /api/events
    working: {},           // staff name -> task text (from the lead's stream); the first-version scene reads HQ.working
    pending: {},           // tool_use id -> {staff, text, start}
    finished: {}, firstSeen: {},
    sceneSubs: {},         // sub-agents someone spawned directly on the scene (e.g. a test harness)
    sentSubs: {}, subLabels: new Set(), blanked: new Set(), selfCall: false,
    skillPct: {}, voice: null, zoom: 100, scene: false, lastReply: "",
    life: true, lifeTipAt: 0,   // office life on/off (remembered) and when the last "shared a tip" toast showed
  };

  const teamByKey = (k) => state.teams.find((t) => t.key === k) || null;
  const teamByName = (n) => { const s = String(n || "").toLowerCase(); return state.teams.find((t) => t.name.toLowerCase() === s) || state.teams.find((t) => t.key === s) || null; };
  const agentByName = (n) => state.agents.find((a) => a.name === n) || null;
  const teamOf = (agentName) => { const a = agentByName(agentName); return a ? (teamByName(a.team) || teamByKey(a.teamKey)) : null; };
  const accent = (t) => (t && (t.accent || t.color)) || "#6b7280";
  const membersOf = (t) => (t ? state.agents.filter((a) => a.team === t.name) : []);
  const headOf = (t) => (t ? membersOf(t).find((a) => a.role === "head") || agentByName(t.lead) : null);
  const leadLabel = (t) => { const h = headOf(t); return h ? h.label : (t && (t.lead_label || t.lead)) || ""; };
  const avColor = (a, t, i = 0) => { const base = accent(t); return i % 3 === 1 ? lighten(base, 0.18) : i % 3 === 2 ? darken(base, 0.22) : base; };
  const hookRun = () => state.hookRunning || (state.status && state.status.running) || {};
  const hasProject = () => !!(window.HQ_OFFICE && typeof window.HQ_OFFICE.project === "function");
  const hasFn = (name) => !!(window.HQ_OFFICE && typeof window.HQ_OFFICE[name] === "function");
  const callScene = (name, ...args) => { if (!hasFn(name)) return undefined; try { return window.HQ_OFFICE[name](...args); } catch (e) { return undefined; } };
  const shortTask = (text, n = 28) => { const s = String(text || "").replace(/\s+/g, " ").trim(); return s.length > n ? s.slice(0, n - 1).trimEnd() + "…" : s; };
  const fileIn = (text) => { const m = /([\w\-]+\.(?:mp4|mov|m4v|mkv|webm|csv|md|txt|json|jpg|png))/i.exec(text || ""); return m ? m[1] : ""; };

  // ---------- who is running, which sub-agents exist ----------
  // HQ.running(): the hook feed (status.running counts) merged with the lead's own stream (task text),
  // plus "chief of staff" while a run is active. The scene reads this every frame.
  function runningMap() {
    const out = {}, st = state.status;
    for (const [k, v] of Object.entries(hookRun())) if (v > 0) out[k] = (state.activity && state.activity[k]) || true;   // task text from Claude's session logs
    for (const [k, v] of Object.entries(state.working)) out[k] = v || true;
    if ((st && st.desk && st.desk.busy) || state.run.id) out["chief of staff"] = "working";
    if (state.voice && state.voice.listening) out["chief of staff"] = "listening";
    for (const [key, items] of Object.entries(subagentsMap())) {        // a head with sub-agents in flight is delegating
      const h = headOf(teamByKey(key));
      if (h && items.length && typeof out[h.name] !== "string") out[h.name] = "delegating";
    }
    return out;
  }
  const STAGES = { "clip-editor": ["cutting", "captions", "thumbnail"], "thumbnail-designer": ["thumbnail"], "brand-checker": ["checking"], "hook-writer": ["drafting"], "copywriter": ["writing"], "qa-tester": ["testing"], "code-reviewer": ["reviewing"] };
  function stageOf(agent, p) { const s = STAGES[agent] || ["working"]; return s[Math.min(s.length - 1, Math.floor((p / 100) * s.length))]; }
  function pseudoProgress(start) { return clamp(Math.floor((Date.now() - (start || Date.now())) / 1200), 1, 96); }   // ~1 % per 1.2 s
  function noteHookStarts(run) {                           // remember when each parallel copy first showed up (for its % line)
    run = run || {};
    for (const [name, n] of Object.entries(run)) for (let i = 0; i < n; i++) { const k = `${name}#${i + 1}`; if (!state.firstSeen[k]) state.firstSeen[k] = Date.now(); }
    for (const k of Object.keys(state.firstSeen)) { const [name, i] = k.split("#"); if (!(run[name] >= Number(i))) delete state.firstSeen[k]; }
  }
  // Sub-agents of one team: 2+ parallel copies of one worker in the hook feed (one clip-editor per clip), or 2+
  // sub-agents of one team started by the lead within the run. Labelled "Sub n · <clip or short task>".
  let subsCache = { t: 0, v: {} };
  function derivedSubs() {
    const byTeam = {}, st = state.status, clips = (st && st.inbox && st.inbox.clips) || [];
    const push = (t, item) => { if (t) (byTeam[t.key] = byTeam[t.key] || []).push(item); };
    for (const [name, n] of Object.entries(hookRun())) {
      const a = agentByName(name); if (n < 2 || !a || a.role === "head") continue;
      for (let i = 0; i < n; i++) push(teamOf(name), { id: `${name}#${i + 1}`, agent: name, start: state.firstSeen[`${name}#${i + 1}`], clip: clips[i] || "" });
    }
    const stream = {};
    for (const [id, p] of Object.entries(state.pending)) { const t = teamOf(p.staff); if (t) (stream[t.key] = stream[t.key] || []).push({ id, agent: p.staff, start: p.start, text: p.text, clip: fileIn(p.text) }); }
    for (const [key, items] of Object.entries(stream)) {
      if (items.length >= 2 && !(byTeam[key] && byTeam[key].length >= items.length)) byTeam[key] = items;
      else if (byTeam[key]) byTeam[key].forEach((it, i) => { const s = items[i]; if (s && !it.clip) { it.clip = s.clip; it.text = s.text; } });   // hook copies borrow the stream's clip names
    }
    const out = {};
    for (const [key, items] of Object.entries(byTeam)) {
      if (items.length < 2) continue;
      out[key] = items.slice(0, 6).map((it, i) => {
        const prog = pseudoProgress(it.start), a = agentByName(it.agent);
        const short = it.clip ? it.clip.replace(/\.[a-z0-9]+$/i, "") : shortTask(it.text || (a ? a.label : it.agent), 16);
        return { id: it.id, label: `Sub ${i + 1} · ${short}`, subtitle: `${stageOf(it.agent, prog)} · ${prog}%`, progress: prog, agent: it.agent, file: it.clip || "", team: key };
      });
    }
    return out;
  }
  // Sub-agents spawned straight on the scene (a test harness, the console) win over the derived ones for that team: the
  // scene shows exactly those figures, so the pills, cards and counters follow them. Their % ticks on from the given value.
  function tickSceneSub(it) {
    const prog = clamp(Math.floor((it.progress0 || 0) + (Date.now() - (it.start || Date.now())) / 1200), 0, 96);
    const m = /^(.+?)\s*·\s*\d+%$/.exec(it.subtitle0 || "");
    const stage = m ? m[1].trim() : stageOf(it.agent || (it.file || /clip/i.test(it.label) ? "clip-editor" : ""), prog);
    return Object.assign({}, it, { progress: prog, subtitle: `${stage} · ${prog}%` });
  }
  function subagentsMap() {                                // HQ.subagents(): what the scene shows, else what the feed and the stream imply
    if (Date.now() - subsCache.t < 250) return subsCache.v;
    const v = derivedSubs();
    for (const [key, items] of Object.entries(state.sceneSubs)) if (items.length) v[key] = items.map(tickSceneSub);
    subsCache = { t: Date.now(), v };
    return v;
  }
  function syncSubagents() {                               // push derived sub-agents to the scene when they change, clear when they end
    const derived = derivedSubs();
    for (const [key, items] of Object.entries(derived)) {
      const sig = items.map((i) => i.id + "|" + i.label).join(";");
      if (state.sentSubs[key] === sig) continue;
      state.sentSubs[key] = sig; state.selfCall = true; delete state.sceneSubs[key];     // the HUD takes this room over
      callScene("spawnSubagents", key, items.map((i) => ({ id: i.id, label: i.label, subtitle: i.subtitle, progress: i.progress })));
      state.selfCall = false;
    }
    for (const key of Object.keys(state.sentSubs)) if (!derived[key]) { delete state.sentSubs[key]; state.selfCall = true; callScene("clearSubagents", key); state.selfCall = false; }
  }

  // ---------- public API ----------
  const HQ = (window.HQ = {
    status: () => state.status, teams: () => state.teams, agents: () => state.agents,
    running: runningMap, subagents: subagentsMap,
    send: (prompt) => send(prompt), toast: (team, title, body, opt) => toast(team, title, body, opt),
    working: state.working, open: (view) => openPanel(view), team: (key, tab) => openTeam(key, tab), focus: (key) => focusTeam(key),
    voice: () => openVoice(), ask: () => focusAsk(), state,
  });

  // ---------- data ----------
  async function getJSON(url, opt) {
    const r = await fetch(url, opt);
    if (r.status === 401) { location.href = "/login"; throw new Error("not logged in"); }
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw Object.assign(new Error(j.error || r.statusText || "request failed"), { status: r.status, body: j });
    return j;
  }
  const postJSON = (url, body) => getJSON(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

  async function refresh() {                               // every 4 s: status + teams (agents once, brain now and then)
    try {
      const [s, t] = await Promise.all([getJSON("/api/status"), getJSON("/api/teams")]);
      state.status = s; state.teams = t.teams || state.teams;
      if (t.brain_notes != null) state.brainNotes = t.brain_notes;
      if (Date.now() - state.hookAt > 8000) { state.hookRunning = s.running || {}; state.hookSig = JSON.stringify(state.hookRunning); }   // a slow status reply never overwrites a fresher events poll
      noteHookStarts(hookRun());
      if (!state.agents.length) await loadAgents();
      attachOngoingRun(s);
      showUpdate(s.update);
      renderAll();
    } catch (e) { /* offline or logging in: keep the last state */ }
  }
  function showUpdate(u) {                                 // which version runs, and whether the start-up update worked
    if (!u) return;
    const el = document.getElementById("hq-version");
    if (el) el.textContent = (u.version || "?") + " · " + (u.ok === false ? "couldn't update" : u.message || "");
    if (el) el.title = u.message || "";
    if (u.ok === false && !state.updateWarned) {
      state.updateWarned = true;
      toast("dev", "Update", "Agents HQ couldn't update itself: " + shortTask(u.message, 120) + ". Tray → Open engine log for details.", { bad: true });
    }
  }
  async function pollEvents() {                            // every 2 s: the hook feed's running map (lighter and quicker than /api/status)
    try {
      const r = await getJSON(`/api/events?after=${state.evOffset}`);
      state.evOffset = r.total != null ? r.total : state.evOffset; state.hookAt = Date.now();
      state.activity = r.activity || {};
      const sig = JSON.stringify(r.running || {}) + JSON.stringify(state.activity);
      if (sig === state.hookSig) return;
      state.hookSig = sig; state.hookRunning = r.running || {}; if (state.status) state.status.running = state.hookRunning;
      noteHookStarts(state.hookRunning); subsCache.t = 0;
      renderTopbar(); renderTeamCards(); renderAgentPills(); renderSubCards(); syncSubagents();
      if (state.view === "team") renderTeamPanel();
    } catch (e) { /* next poll */ }
  }
  async function loadAgents() { try { const a = await getJSON("/api/agents"); state.agents = a.agents || []; buildAskMenu(); } catch (e) { /* retried on the next refresh */ } }
  async function loadBrain() { try { state.brain = await getJSON("/api/brain"); renderOwner(); if (state.view === "brain") renderBrain(); } catch (e) { /* keep the last */ } }
  function renderAll() {
    renderTopbar(); renderTeamCards(); renderAgentPills(); renderBrainLabel(); renderRoomLabel(); renderChips(); renderSubCards(); syncSubagents();
    if (state.view === "tasks") renderBoard();
    if (state.view === "team") renderTeamPanel();
    if (state.view === "brain" && state.brain) renderBrain();
    if (!$("#agent-card").hidden && state.agentCard) showAgentCard(state.agentCard, true);
  }

  // ---------- notifications: toasts (last 3, fade after 12 s) and the bell (last 20) ----------
  async function pollNotifs() {
    try {
      const r = await getJSON(`/api/notifications?after=${state.notifTotal}`);
      const items = r.items || [];
      state.notifTotal = r.total != null ? r.total : state.notifTotal + items.length;
      if (!state.notifSeeded) {                            // first poll: fill the bell, ring only for what needs the owner
        state.notifSeeded = true; state.notifs = items.slice(-20); state.unread = items.filter((i) => i.kind === "waiting").length;
        const last = items.filter((i) => i.kind === "waiting").slice(-1)[0]; if (last) showToast(last);
      } else for (const i of items) addNotif(i, true);
      renderBell();
    } catch (e) { /* next poll */ }
  }
  function addNotif(item, withToast) {
    state.notifs.push(item); if (state.notifs.length > 20) state.notifs.shift();
    state.unread = Math.min(99, state.unread + 1); renderBell();
    if (withToast) showToast(item);
  }
  function toast(team, title, body, opt = {}) {           // HQ.toast(team, title, body)
    const t = typeof team === "object" && team ? team : teamByName(team) || teamByKey(team);
    const key = t ? t.key : /chief|lead|office/i.test(String(team)) ? "chief" : /brain/i.test(String(team)) ? "brain" : String(team || "office").toLowerCase();
    addNotif({ id: "l" + Date.now(), ts: Date.now(), team: t ? t.name : String(team || "Office"), teamKey: key, title: title || (t ? t.name : String(team || "Agents HQ")), body: body || "", kind: opt.kind || "info", bad: !!opt.bad }, true);
  }
  function iconTile(teamKey, extraClass = "") {            // the rounded team icon square (also "brain" and "chief")
    const t = teamByKey(teamKey) || teamByName(teamKey);
    if (t) return `<span class="ticon ${extraClass}" style="background:${accent(t)}">${teamGlyph(t)}</span>`;
    if (teamKey === "brain") return `<span class="ticon ${extraClass}" style="background:#38bdf8">${svg("brain")}</span>`;
    if (teamKey === "chief") return `<span class="ticon ${extraClass}" style="background:linear-gradient(135deg,#7583fb,#14343d)">${svg("chief")}</span>`;
    return `<span class="ticon ${extraClass}" style="background:#4b5563">${svg("list")}</span>`;
  }
  function showToast(item) {
    const host = $("#toasts");
    const node = el(`<div class="toast ${item.bad ? "bad" : ""} ${item.soft ? "soft" : ""}">${iconTile(item.teamKey)}<div><div class="title">${esc(item.title || item.team)}</div><div class="body">${esc(item.body)}</div></div><span class="when">now</span></div>`);
    host.prepend(node);
    while (host.children.length > (isPhone() ? 2 : 3)) host.lastElementChild.remove();
    const gone = () => { node.classList.add("fade"); setTimeout(() => node.remove(), 650); };
    node.addEventListener("click", gone);
    setTimeout(gone, isPhone() ? 7000 : 12000);
  }
  function renderBell() {
    const b = $("#bell-badge"); b.hidden = !state.unread; b.textContent = state.unread > 9 ? "9+" : String(state.unread);
    const list = $("#notif-list"); if (list.hidden) return;
    const rows = state.notifs.slice().reverse().map((n) => `<div class="notif">${iconTile(n.teamKey)}<div><div class="title">${esc(n.title || n.team)}</div><div class="body">${esc(n.body)}</div></div><span class="when">${esc(timeAgo(n.ts) || "now")}</span></div>`).join("");
    list.innerHTML = `<div class="hd"><span>Notifications</span><button type="button" id="notif-clear">clear</button><button type="button" class="xbtn notif-x" data-notif-close title="Close">${svg("close")}</button></div>${rows || '<div class="empty">Nothing yet. The bell rings when a team finishes something, starts sub-agents or needs your OK.</div>'}`;
    $("#notif-clear").onclick = () => { state.notifs = []; state.unread = 0; renderBell(); };
  }
  function toggleBell(force) {
    const list = $("#notif-list"), was = list.hidden; list.hidden = force != null ? !force : !list.hidden;
    if (!list.hidden) { state.unread = 0; renderBell(); } else renderBell();
    if (was !== list.hidden && typeof phonePause === "function") phonePause();
  }

  // ---------- top bar ----------
  function liveCounts() {                                  // header pill: 31 agents · 12 running → 34 · 15 while 3 sub-agents run
    const st = state.status, run = runningMap(), subs = subagentsMap();
    const subsN = Object.values(subs).reduce((n, a) => n + a.length, 0);
    let running = 0;
    for (const name of Object.keys(run)) {
      if (name === "chief of staff" || !agentByName(name)) continue;
      const hook = hookRun()[name] || 0, stream = Object.values(state.pending).filter((p) => p.staff === name).length;
      running += Math.max(1, hook, stream);
    }
    const extra = Object.values(state.sceneSubs).reduce((n, a) => n + a.length, 0) && !Object.keys(derivedSubs()).length ? subsN : 0;
    return { agents: (state.agents.length || (st && st.counts && st.counts.agents) || 0) + subsN, running: running + extra };
  }
  function renderTopbar() {
    const st = state.status, c = liveCounts();
    $("#agents-pill-text").textContent = isPhone() ? `${c.agents} · ${c.running} running` : `${c.agents} agents · ${c.running} running`;
    $("#agents-pill").classList.toggle("live", c.running > 0);
    const n = (st && st.counts && st.counts.tasks_running) || 0, badge = $("#tasks-badge");
    badge.textContent = String(n); badge.classList.toggle("zero", !n);
    $("#logout-form").hidden = !(st && st.auth);
    const lb = $("#lead-log"), busy = !!((st && st.desk && st.desk.busy) || state.run.id);
    lb.classList.toggle("busy", busy); $("#tab-lead").classList.toggle("busy", busy);
    const outside = state.activity && state.activity["chief of staff"];   // Claude working in another window or folder
    if (!state.run.id) $("#lead-text").textContent = busy ? "Lead · working…" : outside ? "Lead · working: " + shortTask(outside, 60) : state.lastReply ? "Lead · " + shortTask(state.lastReply, 60) : "Lead · idle";
  }
  function ownerName() {
    const c = (state.brain && state.brain.Company) || [];
    for (const o of c) {
      const m = /^(?:owner|founder|creator|ceo|run by|workspace|brand)\s*(?:is|:|=|-|–)\s*([^.,;\n(]+)/i.exec(o) || /\b(?:owner|founder)\s+(?:is|named|:)\s*([^.,;\n(]+)/i.exec(o);
      if (m) return m[1].trim().slice(0, 28);
    }
    return "Owner";
  }
  function renderOwner() {
    const name = ownerName();
    $("#user-name").textContent = name; $("#user-initial").textContent = initials(name); $("#avatar").textContent = initials(name);
  }

  // ---------- floating team cards (above each room) ----------
  function cardLine(t, run, subs) {
    const members = membersOf(t), m = members.filter((a) => run[a.name]).length, sub = subs[t.key] || [];
    const liveAgent = members.find((a) => typeof run[a.name] === "string" && !["working", "delegating", "listening"].includes(run[a.name]));
    if (sub.length) return { text: `${members.length} agents · ${sub.length} sub-agents`, live: true, on: true };
    if (liveAgent) return { text: `${liveAgent.label} · ${shortTask(run[liveAgent.name], 30)}`, live: true, on: true };
    return { text: `${members.length} agents · ${m} running`, live: false, on: m > 0 };
  }
  function cardHTML(t, line) {
    const members = membersOf(t);
    return `<span class="ticon" style="background:${accent(t)}">${teamGlyph(t)}</span><span class="txt"><span class="name">${esc(t.name)}</span><span class="line2 ${line.on ? "" : "idle"}"><i class="dot"></i>${esc(line.text)}</span></span><span class="avs">${members.slice(0, 3).map((a, i) => `<span class="av" style="background:${avColor(a, t, i)}" title="${esc(a.label)}">${esc(initials(a.label))}</span>`).join("")}</span>`;
  }
  function renderTeamCards() {
    const host = $("#team-cards"), run = runningMap(), subs = subagentsMap(), O = window.HQ_OFFICE;
    const project = hasProject(), useSetLabel = !project && hasFn("setLabel");
    for (const t of state.teams) {
      const line = cardLine(t, run, subs), html = cardHTML(t, line);
      if (useSetLabel) { callScene("setLabel", "team", t.key, `<div class="team-card static ${line.live ? "live" : ""}" data-team="${esc(t.key)}" style="--tc:${accent(t)}" onclick="HQ.team('${esc(t.key)}')">${html}</div>`); continue; }
      let card = host.querySelector(`.team-card[data-team="${cssq(t.key)}"]`);
      if (!card) {
        card = el(`<div class="team-card ia" data-team="${esc(t.key)}"></div>`);
        card.style.setProperty("--tc", accent(t));
        card.addEventListener("click", () => roomTap(t.key));
        host.appendChild(card);
      }
      if (card.dataset.html !== html) { card.innerHTML = html; card.dataset.html = html; }
      card.classList.toggle("live", line.live);
      card.classList.toggle("docked", !!(state.focused === t.key && state.view !== "team" && project && state.zoom >= 140));
      if (project && O && hasFn("setLabel") && !state.blanked.has(t.key)) { state.blanked.add(t.key); callScene("setLabel", "team", t.key, ""); }
    }
    host.classList.toggle("strip", !project);
    if (!project) for (const c of host.children) c.classList.add("show");
    renderSchedCard();
  }
  function nextScheduledPost() {                          // the Social sub-card: the next dated post on the board
    const tasks = (state.status && state.status.tasks) || [], today = todayISO();
    return tasks.filter((t) => t.date && t.date >= today && (t.kind === "post" || t.kind === "meeting") && t.status !== "done").sort((a, b) => (a.date + (a.time || "")).localeCompare(b.date + (b.time || "")))[0] || null;
  }
  function renderSchedCard() {
    const host = $("#team-cards"); let card = host.querySelector(".sched-card");
    const p = nextScheduledPost(), t = p && (teamByName(p.team) || teamByKey("social"));
    if (!p || !t) { if (card) card.remove(); return; }
    if (!card) { card = el(`<div class="sched-card ia"></div>`); card.addEventListener("click", () => openPanel("calendar")); host.appendChild(card); }
    card.dataset.team = t.key;
    const d = new Date(p.date + "T00:00:00");
    const html = `<span class="date-tile"><span class="d">${DOW[d.getDay()]}</span><span class="t">${esc(fmtTime(p.time) || pad2(d.getDate()))}</span></span><div style="min-width:0"><div class="title">${esc(p.title)}</div><div class="sub">${esc(relDay(p.date))} · ${p.status === "review" ? "needs your OK" : "scheduled ✓"}</div></div>`;
    if (card.dataset.html !== html) { card.innerHTML = html; card.dataset.html = html; }
    if (!hasProject()) card.classList.add("show");
  }

  // ---------- agent name pills, sub-agent pills, the Brain label ----------
  const pillHTML = (label, r, extra = "") => `<i class="dot"></i>${esc(label)}${typeof r === "string" && r ? `<span class="task"> · ${esc(shortTask(r, 26))}</span>` : ""}${extra}`;
  const subPillHTML = (it, cls = "") => `<div class="pill sub show ${cls}" data-kind="sub" data-key="${esc(it.id)}"><span class="main"><i class="dot"></i>${esc(it.label)}</span><span class="stage">${esc(it.subtitle)}</span></div>`;
  function renderAgentPills() {
    const host = $("#agent-pills"), run = runningMap(), subs = subagentsMap();
    const project = hasProject(), useSetLabel = !project && hasFn("setLabel");
    const live = new Set();
    for (const a of state.agents) {
      const r = run[a.name], t = teamByName(a.team);
      // 1: always (running, or in the focused room) · 2: only while the camera is near · 0: never
      const show = (!!r || (t && state.focused === t.key)) ? 1 : state.focused ? 0 : 2;
      const html = pillHTML(a.label, r);
      if (useSetLabel) { callScene("setLabel", "agent", a.name, show === 1 || (show === 2 && state.zoom >= 160) ? `<div class="pill static ${r ? "" : "idle"}">${html}</div>` : ""); continue; }
      let pill = host.querySelector(`.pill[data-kind="agent"][data-key="${cssq(a.name)}"]`);
      if (!pill) { pill = el(`<div class="pill ia" data-kind="agent" data-key="${esc(a.name)}"></div>`); pill.addEventListener("click", () => showAgentCard(a.name)); host.appendChild(pill); }
      if (pill.dataset.html !== html) { pill.innerHTML = html; pill.dataset.html = html; }
      pill.classList.toggle("idle", !r); pill.dataset.show = String(show);
      if (project && hasFn("setLabel") && !state.blanked.has("agent:" + a.name)) { state.blanked.add("agent:" + a.name); callScene("setLabel", "agent", a.name, ""); }
    }
    // sub-agent pills: the scene hosts a "sub" anchor per ghost (setLabel), else we project("sub", id) if the scene supports it
    for (const items of Object.values(subs)) for (const it of items) {
      live.add(it.id);
      if (hasFn("setLabel")) { callScene("setLabel", "sub", it.id, subPillHTML(it, "static")); state.subLabels.add(it.id); continue; }
      let pill = host.querySelector(`.pill[data-kind="sub"][data-key="${cssq(it.id)}"]`);
      if (!pill) { pill = el(subPillHTML(it)); pill.classList.remove("show"); host.appendChild(pill); }
      else pill.querySelector(".stage").textContent = it.subtitle;
      pill.dataset.show = "1";
    }
    for (const id of Array.from(state.subLabels)) if (!live.has(id)) { callScene("setLabel", "sub", id, ""); state.subLabels.delete(id); }
    for (const pill of $$('.pill[data-kind="sub"]', host)) if (!live.has(pill.dataset.key)) pill.remove();
  }
  function renderBrainLabel() {
    const n = state.status && state.status.brain_notes != null ? state.status.brain_notes : state.brainNotes;
    const b = $("#brain-label"); $("#brain-notes").textContent = n == null ? "…" : fmtInt(n);
    if (!hasProject() && hasFn("setLabel")) { callScene("setLabel", "brain", "brain", `<div class="brain-label static" onclick="HQ.open('brain')"><span class="t1">The Brain</span><span class="t2"><b>${n == null ? "…" : fmtInt(n)}</b> notes · shared memory</span></div>`); b.classList.remove("show"); return; }
    if (hasProject() && hasFn("setLabel") && !state.blanked.has("brain")) { state.blanked.add("brain"); callScene("setLabel", "brain", "brain", ""); }
  }

  // ---------- projection: place the billboards every frame from HQ_OFFICE.project(kind, key) ----------
  function projectRaw(kind, key) { try { return window.HQ_OFFICE.project(kind, key) || null; } catch (e) { return null; } }
  function tick() {
    requestAnimationFrame(tick);
    if (!hasProject() || document.hidden) return;
    const phone = isPhone();
    if (phone && state.view !== "office") return;                       // a full sheet covers the office: nothing to place
    // billboards keep a near-constant pixel size, scaled slightly with distance (project().scale when the scene gives it)
    const vf = phone ? 1 : clamp(Math.min(window.innerWidth / 1440, window.innerHeight / 810), 0.8, 1);     // small windows: smaller billboards
    const scaleOf = phone ? (p) => clamp(0.86 + 0.14 * (p && p.scale ? p.scale : state.zoom / 100), 0.9, 1.08) : (p) => vf * clamp(0.72 + 0.28 * (p && p.scale ? p.scale : state.zoom / 100), 0.88, 1.35);
    const cardPos = {}, W = window.innerWidth, H = phone ? $("#tabs").getBoundingClientRect().top : window.innerHeight;
    const barH = phone ? $("#topbar").offsetHeight : BAR_H;
    const box = $("#office3d").getBoundingClientRect(), ox = box.left, oy = box.top;   // project() is relative to #office3d (between the bars on a phone)
    const project = (kind, key) => { const p = projectRaw(kind, key); return p && (ox || oy) ? Object.assign({}, p, { x: p.x + ox, y: p.y + oy }) : p; };
    // screen-fixed chrome the billboards never slide under: the docked card of the focused room, the sub-agent cards
    // the sub-agent progress cards belong to the close-up (the video shows them beside the zoomed room); at office-wide
    // zoom the team cards say "3 sub-agents" and keep the right side free
    const subHost = $("#subagent-cards"); subHost.classList.toggle("away", state.view === "office" && state.zoom < 140);
    const blockers = [$("#team-cards .team-card.docked"), subHost.children.length && !subHost.classList.contains("away") ? subHost : null].filter(Boolean).map((n) => n.getBoundingClientRect());
    const blocked = (l, t, r, b) => blockers.some((k) => r > k.left - 8 && l < k.right + 8 && b > k.top - 8 && t < k.bottom + 8);
    for (const card of $("#team-cards").children) {
      if (!card.classList.contains("team-card")) continue;
      const key = card.dataset.team;
      if (card.classList.contains("docked")) { card.classList.add("show"); continue; }
      const hide = state.view === "team" && state.panelTeam === key && state.zoom > 135;
      const p = project("team", key);
      if (!p || p.visible === false || hide) { card.classList.remove("show"); continue; }
      const s = scaleOf(p), w = card.offsetWidth * s, h = card.offsetHeight * s, top = barH + (phone ? 6 : 12) + h + (phone ? 8 : 14);   // the card's top edge never goes under the top bar
      if (phone && state.focused && p.y < top - 4) { card.classList.remove("show"); continue; }   // a phone close-up: rooms above the frame keep their cards out of the way
      const x = Math.round(p.x), y = Math.round(Math.max(p.y, top));
      // a card mostly off-screen, or one that would slide under the docked card of the focused room, stays hidden
      const offscreen = x < 24 || x > W - 24 || y > H + (phone ? -4 : 20);                   // more than half off-screen (a phone: under the tab bar)
      if (offscreen || blocked(x - w / 2, y - h, x + w / 2, y)) { card.classList.remove("show"); continue; }
      cardPos[key] = { p, s, w, h, x, y };
      card.style.transform = `translate3d(${x}px, ${y}px, 0) translate(-50%, -100%) scale(${s})`;
      card.style.zIndex = String(y);
      card.classList.add("show");
    }
    const sched = $("#team-cards .sched-card");
    if (sched) {
      const c = cardPos[sched.dataset.team];
      if (c) {                                             // right of its team card; below it when the window has no room there
        const fits = c.x + c.w / 2 + 10 + 218 * c.s < W - 8;
        const x = fits ? c.x + c.w / 2 + 10 : clamp(c.x - 109 * c.s, 8, W - 226), y = fits ? clamp(c.y - c.h, 50, H - 70) : clamp(c.y + 6, 50, H - 70);
        if (blocked(x, y, x + 218 * c.s, y + 54 * c.s)) sched.classList.remove("show");
        else { sched.style.transform = `translate3d(${Math.round(x)}px, ${Math.round(y)}px, 0) scale(${c.s})`; sched.style.zIndex = String(c.y + 1); sched.classList.add("show"); } }
      else sched.classList.remove("show");
    }
    const talkers = hasFn("lifeTalkers") ? window.HQ_OFFICE.lifeTalkers() || null : null;   // office life: a speech bubble stands in for the name pill
    for (const pill of $("#agent-pills").children) {
      const lvl = pill.dataset.show, p = lvl && lvl !== "0" && !(talkers && talkers[pill.dataset.key] && pill.dataset.kind === "agent") ? project(pill.dataset.kind, pill.dataset.key) : null;
      const near = p && (p.near != null ? !!p.near : state.zoom >= 160);         // pills show inside the zoomed room only, like the video
      if (!p || p.visible === false || !near || (phone && (p.y > H || p.y < barH + 20))) { pill.classList.remove("show"); continue; }
      pill.style.transform = `translate3d(${Math.round(p.x)}px, ${Math.round(p.y - 4)}px, 0) translate(-50%, -100%) scale(${scaleOf(p)})`;
      pill.classList.add("show");
    }
    const b = $("#brain-label"), pb = project("brain", "brain");
    if (pb && pb.visible !== false && !(phone && (pb.y > H || pb.y < barH + 30))) { b.style.transform = `translate3d(${Math.round(pb.x)}px, ${Math.round(pb.y - 8)}px, 0) translate(-50%, -100%) scale(${scaleOf(pb)})`; b.classList.add("show"); } else b.classList.remove("show");
  }

  // ---------- room label card (bottom-left) and the RUNS ON chips ----------
  function renderRoomLabel() {
    const box = $("#room-label"), t = teamByKey(state.focused);
    if (!t) { box.hidden = true; return; }
    const html = `<span class="bar"></span><div><div class="t1">${esc(t.name)}</div><div class="t2">${esc(t.tagline || "")}</div></div><div class="rl-btns"><button class="btn sm blue" type="button" data-team-open="${esc(t.key)}">Open</button><button class="xbtn" type="button" data-overview title="Back to the overview">${svg("close")}</button></div>`;
    if (box.dataset.html !== html) { box.innerHTML = html; box.dataset.html = html; box.style.setProperty("--tc", accent(t)); }
    box.hidden = false;
  }
  function renderChips() {
    const t = teamByKey(state.focused), h = headOf(t), model = String((h && h.model) || (t ? "opus" : "")).toLowerCase();
    for (const c of $$("#status-chips .chip")) c.classList.toggle("hot", !!t && model.includes(c.dataset.model));
  }

  // ---------- minimap (bottom-right) ----------
  function fallbackMap() {                                 // no scene: the eight rooms in a ring, clockwise from the top
    const rooms = state.teams.map((t, i) => { const a = -Math.PI / 2 + (i / Math.max(1, state.teams.length)) * Math.PI * 2; return { key: t.key, x: 0.5 + 0.37 * Math.cos(a), y: 0.5 + 0.36 * Math.sin(a), w: 0.13, h: 0.14, color: accent(t) }; });
    return { rooms, brain: { x: 0.5, y: 0.5 }, camera: null, target: null };
  }
  function roundRect(g, x, y, w, h, r) { g.beginPath(); g.moveTo(x + r, y); g.arcTo(x + w, y, x + w, y + h, r); g.arcTo(x + w, y + h, x, y + h, r); g.arcTo(x, y + h, x, y, r); g.arcTo(x, y, x + w, y, r); g.closePath(); }
  function syncFocus(ms) {                                 // the camera may be flown from outside the HUD (scene clicks, the console)
    const mode = ms && typeof ms.mode === "string" ? ms.mode : "";
    const key = mode.startsWith("room:") ? mode.slice(5) : null;
    if (key && key !== state.focused && teamByKey(key)) state.focused = key;
    else if (mode === "overview" && state.focused) state.focused = null;
    else return;
    renderRoomLabel(); renderChips(); renderAgentPills(); renderTeamCards();
  }
  let mapSig = "";
  function drawMinimap(ms) {
    const cv = $("#minimap-canvas"); if (!cv || !cv.offsetParent) return;   // hidden (a phone): nothing to draw
    const dpr = Math.min(2, window.devicePixelRatio || 1), W = cv.clientWidth || 132, H = cv.clientHeight || 78;
    ms = ms || callScene("minimapState") || fallbackMap(); const run = runningMap();
    $("#minimap-zoom").textContent = `${Math.round(state.zoom)}%`;
    // redraw only when something on the map moved (a 2D canvas repaint is costly on software renderers)
    const r2 = (v) => Math.round((v || 0) * 200);
    const sig = [W, H, state.zoom | 0, state.focused, (ms.rooms || []).map((r) => r.key + (r.lit != null ? r.lit : membersOf(teamByKey(r.key)).some((a) => run[a.name])) + r2(r.x) + "," + r2(r.y)).join(";"), ms.camera && r2(ms.camera.x) + "," + r2(ms.camera.y), ms.target && r2(ms.target.x) + "," + r2(ms.target.y)].join("|");
    if (sig === mapSig) return; mapSig = sig;
    if (cv.width !== Math.round(W * dpr)) { cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr); }
    const g = cv.getContext("2d", { willReadFrequently: true }); g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, W, H);
    for (const r of ms.rooms || []) {
      const t = teamByKey(r.key), w = (r.w || 0.12) * W, h = (r.h || 0.12) * H, x = r.x * W - w / 2, y = r.y * H - h / 2;   // TODO(contract): x,y read as the room centre
      g.fillStyle = r.color || accent(t); g.globalAlpha = 0.95; roundRect(g, x, y, w, h, 2); g.fill(); g.globalAlpha = 1;
      const lit = r.lit != null ? r.lit : membersOf(t).some((a) => run[a.name]);
      if (lit) { g.fillStyle = "#fff"; g.beginPath(); g.arc(x + w - 2.5, y + 2.5, 1.6, 0, 7); g.fill(); }
      if (state.focused === r.key) { g.strokeStyle = "rgba(255,255,255,0.85)"; g.lineWidth = 1; roundRect(g, x - 2, y - 2, w + 4, h + 4, 3); g.stroke(); }
    }
    if (ms.brain) {                                        // the Brain: a soft cyan halo and a white dot
      g.fillStyle = "rgba(127,233,255,0.28)"; g.beginPath(); g.arc(ms.brain.x * W, ms.brain.y * H, 5.5, 0, 7); g.fill();
      g.fillStyle = "#dde8ec"; g.beginPath(); g.arc(ms.brain.x * W, ms.brain.y * H, 2.6, 0, 7); g.fill();
    }
    const tg = ms.target || ms.camera;
    if (tg) { const vw = clamp((W * 0.55 * 100) / state.zoom, 10, W), vh = clamp((H * 0.55 * 100) / state.zoom, 7, H); g.strokeStyle = "rgba(255,255,255,0.7)"; g.lineWidth = 1; g.strokeRect(tg.x * W - vw / 2, tg.y * H - vh / 2, vw, vh); }
    if (ms.camera) { g.fillStyle = "rgba(255,255,255,0.9)"; g.beginPath(); g.arc(ms.camera.x * W, ms.camera.y * H, 1.8, 0, 7); g.fill(); }
  }
  function floorOfMode(ms) {                              // which floor button is lit: the floor view, a room's floor, the Brain's
    const mode = (ms && ms.mode) || "";
    if (mode.startsWith("floor:")) return mode.slice(6);
    if (mode.startsWith("room:")) { const r = (ms.rooms || []).find((x) => x.key === mode.slice(5)); return r && r.floor != null ? String(r.floor) : "all"; }
    if (mode === "brain") return "0";
    return ms && ms.floorView != null ? String(ms.floorView) : "all";
  }
  function syncFloors(ms) { const on = floorOfMode(ms); for (const b of $$("#floor-ctl button")) b.classList.toggle("on", b.dataset.floor === on); }
  function buildFloorButtons() {                         // one button per floor of the office, top floor first, then All
    const host = $("#floor-ctl"), floors = hasFn("floors") ? callScene("floors") : null;
    if (!host || !Array.isArray(floors) || !floors.length) return;
    const short = (f) => (f.floor === 0 ? "G" : f.floor === floors.length - 1 && /roof/i.test(f.name) ? "R" : f.floor + "F");
    const title = (f) => esc(f.rooms && f.rooms.length ? `${f.name} · ${f.rooms.map((k) => (teamByKey(k) || { name: k }).name).join(", ")}` : f.name);
    host.innerHTML = floors.slice().reverse().map((f) => `<button type="button" data-floor="${f.floor}" title="${title(f)}">${short(f)}</button>`).join("") + '<button type="button" data-floor="all" class="on" title="The whole building">All</button>';
    host.hidden = false;
    for (const b of $$("#floor-ctl button")) b.addEventListener("click", () => {
      state.focused = null; callScene("showFloor", b.dataset.floor === "all" ? null : +b.dataset.floor); renderAll();
      syncFloors(callScene("minimapState"));
    });
  }
  function wireMinimap() {
    if (window.HQ_OFFICE && window.HQ_OFFICE.ready) buildFloorButtons(); else window.addEventListener("hq-office-ready", buildFloorButtons, { once: true });
    $("#minimap-out").addEventListener("click", () => { if (hasFn("zoom")) callScene("zoom", -1); else if (hasFn("setZoomPercent")) callScene("setZoomPercent", state.zoom - 15); });
    $("#minimap-in").addEventListener("click", () => { if (hasFn("zoom")) callScene("zoom", 1); else if (hasFn("setZoomPercent")) callScene("setZoomPercent", state.zoom + 15); });
    $("#minimap-full").addEventListener("click", () => { if (hasFn("fullscreen")) callScene("fullscreen"); else if (document.fullscreenElement) document.exitFullscreen(); else document.documentElement.requestFullscreen && document.documentElement.requestFullscreen().catch(() => {}); });
    $("#minimap-canvas").addEventListener("click", (e) => {       // click a room swatch to fly there
      const r = e.currentTarget.getBoundingClientRect(), x = (e.clientX - r.left) / r.width, y = (e.clientY - r.top) / r.height;
      const ms = callScene("minimapState") || fallbackMap();
      let best = null, bd = 0.08;
      for (const room of ms.rooms || []) { const d = Math.hypot(room.x - x, room.y - y); if (d < bd) { bd = d; best = room.key; } }
      if (best) focusTeam(best); else if (Math.hypot(0.5 - x, 0.5 - y) < 0.1) { state.focused = null; callScene("overview"); renderAll(); }
    });
  }

  // ---------- panels: one left panel at a time (team · tasks · calendar · brain) ----------
  const PANELS = { team: "#team-panel", tasks: "#task-board", calendar: "#calendar", brain: "#brain-view" };
  function openPanel(view) {
    const prev = state.view; state.view = PANELS[view] ? view : "office";
    for (const [v, id] of Object.entries(PANELS)) $(id).hidden = v !== state.view;
    $("#hud").classList.toggle("panel-open", state.view !== "office");
    $("#hud").classList.toggle("board-open", state.view === "tasks");
    $("#hud").dataset.view = state.view;
    for (const b of $$("#tabs .tab")) b.classList.toggle("open", b.dataset.view === state.view);
    closeMenus();
    if (isPhone()) { closeAsk(); if (state.view !== "office") setLead(false); }
    phonePause();
    if (state.view === "tasks") renderBoard();
    if (state.view === "calendar") loadCalendar();
    if (state.view === "brain") { renderBrain(); loadBrain(); }
    if (state.view === "team") renderTeamPanel();
    if (state.view === "office" && prev !== "office") renderTeamCards();
    if (state.focused && prev !== state.view && (prev === "office" || state.view === "office")) callScene("flyTo", state.focused, flyOpts());   // re-centre the room beside / without the panel
  }
  function openTeam(key, tab) {
    if (!teamByKey(key)) return;
    state.panelTab = tab || (state.panelTeam === key ? state.panelTab : "overview"); state.panelTeam = key;
    openPanel("team"); focusTeam(key);
  }
  const flyOpts = () => (state.view !== "office" && window.innerWidth > 1024 ? { shiftX: state.view === "tasks" ? 0.2 : 0.17 } : {});   // beside an open left panel
  function focusTeam(key) {                                // fly the camera to a room and show its label card
    state.focused = key; callScene("flyTo", key, flyOpts());
    renderRoomLabel(); renderChips(); renderAgentPills(); renderTeamCards();
  }
  function goOverview() { state.focused = null; callScene("overview"); renderAll(); }
  // A phone: a tap on a team card or a double-tap on a room flies there first; a second tap (or Open) opens the team.
  function roomTap(key) { if (isPhone() && state.focused !== key) focusTeam(key); else openTeam(key); }
  // A phone: the office does not draw while a full sheet covers it (battery), and resumes when it closes.
  function phonePause() { if (rv.open) { callScene("pause", true); return; } const cover = isPhone() && (state.view !== "office" || $("#lead-log").classList.contains("open") || $("#hud").classList.contains("ask-open") || !$("#notif-list").hidden || !!state.voice); callScene("pause", cover); }
  // the lead log: a drawer on desktop, a sheet on a phone (the Lead tab)
  function setLead(on) {
    const lg = $("#lead-log"); lg.classList.toggle("open", !!on);
    $("#hud").classList.toggle("lead-open", !!on && isPhone());
    if (on) { const con = $("#lead-con"); con.scrollTop = con.scrollHeight; if (isPhone()) closeAsk(); }
    phonePause();
  }
  // the ask sheet on a phone (the search icon in the top bar): input, mic, send and the agent picker
  function openAsk() { const hud = $("#hud"); if (!hud.classList.contains("ask-open")) { hud.classList.add("ask-open"); setLead(false); toggleBell(false); } buildAskMenu(); $("#ask-menu").hidden = false; const i = $("#ask-input"); i.focus(); phonePause(); }
  function closeAsk() { const hud = $("#hud"); if (!hud.classList.contains("ask-open")) return; hud.classList.remove("ask-open"); $("#ask-input").blur(); $("#ask-menu").hidden = true; phonePause(); }
  function closeMenus() { $("#user-dropdown").hidden = true; $("#ask-menu").hidden = true; toggleBell(false); }

  // ---------- shared pieces: sparklines, team tag pills, task rows ----------
  function sparkline(values, color) {
    const w = 120, h = 20, max = Math.max(...values, 1), min = Math.min(...values, 0);
    const pts = values.map((v, i) => `${((i / (values.length - 1)) * w).toFixed(1)},${(h - ((v - min) / (max - min || 1)) * (h - 3) - 1).toFixed(1)}`).join(" ");
    return `<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none"><polyline points="${pts}" fill="none" stroke="${color}" stroke-width="1.6" stroke-linejoin="round" stroke-linecap="round"/></svg>`;
  }
  function series(key, shape, live) {                     // a stable 12-point line per team, ending at the live value
    const r = seeded(key + shape), out = [];
    for (let i = 0; i < 12; i++) out.push(shape === "up" ? i * 1.2 + r() * 3 : shape === "down" ? 14 - i * 0.8 + r() * 3 : 5 + Math.sin(i * 1.1) * 2 + r() * 2);
    if (live != null && isFinite(live)) out[11] = Math.max(0.5, Number(live)) + (shape === "down" ? 2 : 0);
    return out;
  }
  const tagStyle = (t) => `--tcl:${lighten(accent(t), 0.35)};--tcd:${darken(accent(t), 0.5)}`;
  const tagPill = (team) => { const t = teamByName(team); return `<span class="tag" style="${t ? tagStyle(t) : "--tcl:#3a3f4d;--tcd:#d5d9e3"}">${esc(t ? t.name : team || "Office")}</span>`; };
  function ring(p) {
    const r = 13, c = 2 * Math.PI * r, off = c * (1 - clamp(p, 0, 100) / 100);
    return `<span class="ring"><svg viewBox="0 0 32 32"><circle class="trk" cx="16" cy="16" r="${r}"/><circle class="arc" cx="16" cy="16" r="${r}" stroke-dasharray="${c.toFixed(1)}" stroke-dashoffset="${off.toFixed(1)}"/></svg><span class="n">${Math.round(p)}</span></span>`;
  }
  // A task whose video, thumbnail and caption are all ready reads "Final · <clip>" (the server checks the folder).
  function taskTitle(t) {
    if (!t) return "";
    return t.final ? "Final · " + String(t.title).replace(/^(final|thumbnails?|covers?|captions?|post copy|copy|edit|video|clip|posting)\s*[·:\-–|]\s*/i, "") : t.title;
  }
  function taskRow(t) {                                    // one board row; the section decides glyph and control
    let glyph, meta, act, cls = "";
    if (t.status === "doing") { glyph = t.progress != null ? ring(t.progress) : '<span class="spin"></span>'; meta = t.subtitle || t.agent || "running"; act = t.progress != null ? "" : '<span class="chev">›</span>'; if (t.progress != null) { act = glyph; glyph = '<span class="spin"></span>'; } }
    else if (t.status === "review") { glyph = '<span class="warn">!</span>'; meta = t.subtitle || "needs your approval"; act = ["approval", "post"].includes(t.kind) ? `<button class="btn primary sm" data-approve="${esc(t.id)}">Approve</button>` : `<button class="btn sm" data-review="${esc(t.id)}">Review</button>`; cls = t.kind === "post" ? "hot" : ""; }
    else if (t.status === "done") { glyph = `<span class="done-g">${svg("check")}</span>`; meta = t.subtitle || timeAgo(t.done_at || t.updated); act = '<span class="chev">›</span>'; }
    else { glyph = '<span class="todo-g"></span>'; meta = t.subtitle || (t.date ? `${relDay(t.date)}${t.time ? " " + t.time : ""}` : "not started"); act = t.footage ? `<button class="btn sm blue" data-edit-footage="${esc(t.id)}" title="Edit this video now">Edit</button>` : `<button class="btn sm blue" data-run="${esc(t.id)}">Run</button>`; }
    const title = t.date && t.status !== "done" && !/\d{1,2}:\d{2}/.test(t.title) && t.time ? `${taskTitle(t)} · ${relDay(t.date)} ${fmtTime(t.time)}` : taskTitle(t);
    return `<div class="trow ${cls}" data-task="${esc(t.id)}"><span class="g">${glyph}</span><div class="tt ia" data-open="${esc(t.id)}"><div class="title">${esc(title)}</div><div class="meta">${tagPill(t.team)}${t.final ? '<span class="final-pill" title="Video, thumbnail and caption are all ready">✓ Final</span>' : ""}<span>${esc(meta)}</span></div></div><div class="act">${act}</div></div>${state.openDetail === t.id ? taskDetail(t) : ""}`;
  }
  function taskDetail(t) {
    const files = [], m = /out:([^\s,;]+)/.exec(t.note || ""), st = state.status || {}, top = m ? m[1].split("/")[0] : "";
    if (t.footage && t.status === "todo") files.push(`<button class="btn sm blue" data-edit-footage="${esc(t.id)}" type="button">${svg("play")} Edit this video</button>`);
    if (m && st.out && st.out[top]) files.push(`<button class="btn sm blue" data-rv-folder="out/${esc(m[1])}" data-rv-task="${esc(t.id)}" type="button">${svg("play")} Open ${(st.out[top].files || []).length} files</button>`);
    else if (m && st.approved && st.approved[top]) files.push(`<button class="btn sm blue" data-rv-folder="approved/${esc(m[1])}" data-rv-task="${esc(t.id)}" type="button">${svg("play")} Open to post</button>`);
    const moves = ["todo", "doing", "review", "done"].filter((s) => s !== t.status).map((s) => `<button class="btn sm" data-move="${esc(t.id)}:${s}">${({ todo: "To do", doing: "Running", review: "Waiting", done: "Done" })[s]}</button>`).join("");
    return `<div class="task-detail"><div><b>${esc(t.title)}</b> <span class="hint">· ${esc(t.kind)}${t.agent ? " · " + esc(t.agent) : ""}${t.date ? " · " + esc(t.date) + (t.time ? " " + esc(t.time) : "") : ""} · created ${esc(timeAgo(t.created))}</span></div>${t.note ? `<div class="nt">${esc(t.note)}</div>` : '<div class="hint" style="margin-top:4px">No note on this task.</div>'}${files.length ? `<div>${files.join("")}</div>` : ""}<div class="row">${moves}<button class="btn sm" data-remove="${esc(t.id)}" style="margin-left:auto">Remove</button></div></div>`;
  }
  const teamTasks = (t) => ((state.status && state.status.tasks) || []).filter((x) => t && (x.team === t.name || String(x.team).toLowerCase() === t.key));

  // ---------- the team panel ----------
  const TOOL_STYLE = { facebook: ["#1877f2", "f"], "google drive": ["#1ca16b", "▲"], capcut: ["#222933", "C"], canva: ["linear-gradient(135deg,#46a5be,#6d5df5)", "C"], slack: ["#612656", "#"], github: ["#24292f", "G"], notion: ["#2b2b2b", "N"], gmail: ["#d93025", "M"], calendar: ["#1a73e8", "C"], instagram: ["linear-gradient(135deg,#f58529,#dd2a7b,#8134af)", "I"], youtube: ["#ff0033", "▶"], "youtube analytics": ["#ff0033", "Y"], sheets: ["#188038", "S"], shopify: ["#5e8e3e", "S"], stripe: ["#635bff", "S"], ci: ["#2088ff", "CI"], "web search": ["#2563eb", "W"], "rough cut": ["#5b5fd6", "✂"], captions: ["#5b5fd6", "cc"], thumbnails: ["#5b5fd6", "▣"] };
  function toolTile(tool) {
    const [bg, glyph] = TOOL_STYLE[String(tool.name).toLowerCase()] || [hashColor(tool.name), String(tool.name)[0].toUpperCase()];
    const on = tool.status === "connected";
    const posting = tool.via === "posting";                 // Facebook, Instagram, YouTube: connected under Accounts for posting
    const st = on ? `Connected · ${esc(posting ? tool.detail || "posting" : tool.via || "MCP")}` : posting ? "Not connected · tap to connect" : "Not connected";
    return `<div class="tool ${posting ? "ia" : ""}" title="${esc(tool.name)}" ${posting ? "data-rv-accounts" : ""}><span class="ic" style="background:${bg}">${esc(glyph)}</span><div style="min-width:0"><div class="nm">${esc(tool.name)}</div><div class="st ${on ? "" : "off"}"><i class="dot"></i>${st}</div></div></div>`;
  }
  function skillState(t, s, run) {                         // a skill runs while its agent runs; its % climbs 2-4 points a second
    const on = !!run[s.agent] || (s.skill && !!run[t.lead] && membersOf(t).some((a) => a.skills && a.skills.includes(s.skill) && run[a.name]));
    const store = (state.skillPct[t.key] = state.skillPct[t.key] || {});
    if (on && store[s.name] == null) store[s.name] = 30 + Math.floor(seeded(t.key + s.name)() * 45);
    if (!on) delete store[s.name];
    return { on, pct: store[s.name] };
  }
  function avgTurnaround(tasks) {
    const d = tasks.filter((t) => t.status === "done" && t.done_at && t.created).map((t) => Date.parse(t.done_at) - Date.parse(t.created)).filter((x) => x > 0);
    if (!d.length) return "—";
    const m = d.reduce((a, b) => a + b, 0) / d.length / 60000;
    return m < 60 ? `${Math.max(1, Math.round(m))}m` : m < 1440 ? `${(m / 60).toFixed(m < 600 ? 1 : 0)}h` : `${Math.round(m / 1440)}d`;
  }
  function renderTeamPanel() {
    const t = teamByKey(state.panelTeam), p = $("#team-panel"); if (!t) { p.hidden = true; return; }
    const members = membersOf(t), head = headOf(t), run = runningMap(), subs = subagentsMap()[t.key] || [];
    const runningN = members.filter((a) => run[a.name]).length + subs.length, tasks = teamTasks(t);
    const scrollTop = p.querySelector(".pbody") ? p.querySelector(".pbody").scrollTop : 0;
    const tabs = ["overview", "tasks", "calendar", "settings"].map((k) => `<button class="ptab" data-ptab="${k}" type="button">${cap(k)}</button>`).join("");
    let body = "";
    if (state.panelTab === "overview") {
      const today = tasks.filter((x) => isToday(x.created) || isToday(x.updated) || isToday(x.done_at) || x.status === "doing" || x.status === "review").length;
      const tools = t.tools || [], live = tools.filter((x) => x.status === "connected").length;
      const skills = (t.skills || []).map((s) => ({ ...s, ...skillState(t, s, run) })), par = skills.filter((s) => s.on).length;
      body = `<div class="tiles">
          <div class="tile"><div class="k">Tasks today</div><div class="v">${today}</div>${sparkline(series(t.key, "up", today), "#7d7dbd")}</div>
          <div class="tile"><div class="k">Running</div><div class="v">${runningN}</div>${sparkline(series(t.key, "flat", runningN), "#349282")}</div>
          <div class="tile"><div class="k">Avg. turnaround</div><div class="v">${esc(avgTurnaround(tasks))}</div>${sparkline(series(t.key, "down", null), "#889bc6")}</div>
        </div>
        <div class="sec"><span>Connected tools</span><span class="cnt">${live} live</span></div>
        <div class="tools">${tools.map(toolTile).join("") || '<div class="hint">No tools listed for this team in hq/teams.json.</div>'}</div>
        <div class="sec"><span>Skills</span>${par ? `<span class="cnt">${par} running in parallel</span>` : ""}</div>
        <div>${skills.map((s) => `<div class="skill ${s.on ? "" : "idle"}" data-skill="${esc(s.name)}" title="${esc(s.note || "")}"><i class="dot"></i><span class="nm">${esc(s.name)}</span><span class="bar"><i style="width:${s.on ? s.pct : 0}%"></i></span><span class="pct">${s.on ? s.pct + "%" : "idle"}</span></div>`).join("") || '<div class="hint">No skills listed.</div>'}</div>
        <div class="sec"><span>Agents</span><span class="cnt" style="background:none;color:#6a7080">${members.length}</span></div>
        ${members.map((a, i) => agentRow(a, t, run, i, a === head)).join("")}
        ${subs.map((s) => `<div class="arow"><span class="av" style="background:${lighten(accent(t), 0.3)}">S</span><div><div class="nm">${esc(s.label)}</div><div class="ds">sub-agent of ${esc(head ? head.label : t.name)}${s.file ? " · " + esc(s.file) : ""}</div></div><span class="stchip">${esc(s.subtitle)}</span></div>`).join("")}`;
    } else if (state.panelTab === "tasks") {
      const sec = (title, dot, rows) => rows.length ? `<div class="sec"><span class="dotl"><i class="dot" style="background:${dot};box-shadow:none"></i>${title} · ${rows.length}</span></div>${rows.map(taskRow).join("")}` : "";
      body = sec("Running", "#4f8cff", tasks.filter((x) => x.status === "doing")) + sec("Waiting for you", "#e4c830", tasks.filter((x) => x.status === "review")) + sec("To do", "#6b7280", tasks.filter((x) => x.status === "todo")) + sec("Done today", "#4cceac", tasks.filter((x) => x.status === "done" && isToday(x.done_at)));
      body = body || `<div class="empty">No tasks for ${esc(t.name)} yet. Add one on the board or send a brief.</div>`;
      body += `<div class="row" style="display:flex;gap:8px;margin-top:14px"><button class="btn sm" data-board>Open the board</button><button class="btn sm blue" data-brief>Brief ${esc(t.name)}</button></div>`;
    } else if (state.panelTab === "calendar") {
      const dated = tasks.filter((x) => x.date).sort((a, b) => (a.date + (a.time || "")).localeCompare(b.date + (b.time || "")));
      const byDate = {}; for (const x of dated) (byDate[x.date] = byDate[x.date] || []).push(x);
      body = Object.entries(byDate).map(([d, rows]) => `<div class="sec"><span>${DOW[new Date(d + "T00:00:00").getDay()]} · ${esc(d)}</span><span class="cnt" style="background:none;color:#6a7080">${esc(relDay(d))}</span></div>${rows.map((x) => `<div class="trow"><span class="g"><span class="date-tile" style="width:30px;height:30px"><span class="d">${DOW[new Date(x.date + "T00:00:00").getDay()]}</span><span class="t" style="font-size:9px">${esc(fmtTime(x.time))}</span></span></span><div class="tt ia" data-open-cal="${esc(x.id)}"><div class="title">${esc(x.title)}</div><div class="meta">${tagPill(x.team)}<span>${esc(x.kind)} · ${x.status === "done" ? "done" : x.status === "review" ? "needs your OK" : "scheduled ✓"}</span></div></div><div class="act"><span class="chev">›</span></div></div>`).join("")}`).join("") || `<div class="empty">Nothing on the calendar for ${esc(t.name)}. Dated posts and meetings show up here.</div>`;
      body += `<div class="row" style="display:flex;gap:8px;margin-top:14px"><button class="btn sm" data-cal>Open the calendar</button></div>`;
    } else {
      body = `<div class="sec"><span>Agents · models</span></div>${members.map((a) => `<div class="arow" data-agent="${esc(a.name)}"><span class="av" style="background:${avColor(a, t, 0)}">${esc(initials(a.label))}</span><div style="min-width:0"><div class="nm">${esc(a.label)}${a.role === "head" ? '<span class="lead-tag">LEAD</span>' : ""}</div><div class="ds"><code>.claude/agents/${esc(a.name)}.md</code></div></div><span class="mchip">${esc(a.model || "sonnet")}</span></div>`).join("")}
        <div class="sec"><span>Team</span></div>
        <div class="hint">Lead: <b>${esc(leadLabel(t))}</b> · ${members.length} agents · ${(t.tools || []).length} tools · ${(t.skills || []).length} skills</div>
        <div class="hint" style="margin-top:6px">Open agent file: <code>.claude/agents/&lt;name&gt;.md</code> (one job each). Team metadata: <code>hq/teams.json</code>. To add an agent, send <code>/hire &lt;name&gt;: &lt;job&gt;</code>.</div>
        <div class="hint" style="margin-top:6px">Tagline: <span class="mono">${esc(t.tagline || "")}</span></div>`;
    }
    p.innerHTML = `<div class="ph">${iconTile(t.key)}<div class="tt"><h2>${esc(t.name)}</h2><div class="sub"><i class="dot ${runningN ? "" : "off"}" style="${runningN ? "" : "background:#4f5665;box-shadow:none"}"></i>${members.length} agents · lead: ${esc(leadLabel(t))}</div></div><button class="xbtn" data-close type="button">${svg("close")}</button></div><div class="ptabs">${tabs}</div><div class="pbody">${body}</div>`;
    for (const b of $$(".ptab", p)) b.classList.toggle("active", b.dataset.ptab === state.panelTab);
    p.querySelector(".pbody").scrollTop = scrollTop;
  }
  function agentRow(a, t, run, i, isLead) {
    const r = run[a.name], first = (a.description || "").split(/\.\s/)[0];
    return `<div class="arow ${isLead ? "lead" : ""}" data-agent="${esc(a.name)}"><span class="av" style="background:${avColor(a, t, i)}">${esc(initials(a.label))}</span><div style="min-width:0"><div class="nm">${esc(a.label)}${isLead ? '<span class="lead-tag">LEAD</span>' : ""}</div><div class="ds">${esc(typeof r === "string" ? r : first)}</div></div><span class="stchip ${r ? "" : "idle"}">${r ? "working" : "idle"}</span></div>`;
  }
  function tickSkills() {                                  // every second: skill bars climb and wrap, sub-agent % lines tick
    for (const store of Object.values(state.skillPct)) for (const k of Object.keys(store)) { store[k] += 2 + Math.floor(Math.random() * 3); if (store[k] > 92) store[k] = 30; }
    if (state.view === "team") { const t = teamByKey(state.panelTeam), store = (t && state.skillPct[t.key]) || {}; for (const row of $$("#team-panel .skill:not(.idle)")) { const v = store[row.dataset.skill]; if (v == null) continue; row.querySelector(".bar i").style.width = v + "%"; row.querySelector(".pct").textContent = v + "%"; } }
    if (Object.keys(subagentsMap()).length) { subsCache.t = 0; renderAgentPills(); renderSubCards(); if (state.view === "team") renderTeamPanel(); }
  }

  // ---------- the task board ----------
  function renderBoard() {
    const p = $("#task-board"), st = state.status || {}, tasks = st.tasks || [];
    const doing = tasks.filter((t) => t.status === "doing"), review = tasks.filter((t) => t.status === "review"), todo = tasks.filter((t) => t.status === "todo");
    const done = tasks.filter((t) => t.status === "done" && isToday(t.done_at)).sort((a, b) => String(b.done_at).localeCompare(String(a.done_at)));
    // every finished folder in out/ waits for the owner: edits (edit.mp4), but also notes-only or script-only work
    const SPECIAL_OUT = ["scripts", "radar", "pulse"], outNames = new Set(st.waiting_for_approval || []);
    for (const [name, info] of Object.entries(st.out || {})) if (!SPECIAL_OUT.includes(name) && info && (info.files || []).length) outNames.add(name);
    const outWaiting = Array.from(outNames).sort().map((name) => ({ name, info: (st.out || {})[name] || {} }));
    const counts = { all: tasks.length + outWaiting.length, running: doing.length, waiting: review.length + outWaiting.length, done: done.length };
    const f = state.filter, show = (k) => f === "all" || f === k;
    const sec = (title, dot, n) => `<div class="sec"><span class="dotl"><i class="dot" style="background:${dot};${dot === "#4cceac" || dot === "#4f8cff" ? "" : "box-shadow:none"}"></i>${title} · ${n}</span></div>`;
    const approvalRow = ({ name, info }) => `<div class="trow approval hot ia" data-out="${esc(name)}" data-rv-folder="out/${esc(name)}"><span class="g">${info.cover ? `<img class="thumb" src="/files/out/${encodeURIComponent(name)}/cover.jpg" alt="">` : `<span class="thumb" style="display:grid;place-items:center;color:#9aa3b2">${svg("play")}</span>`}</span><div class="tt"><div class="title">${esc(name.replace(/[-_]+/g, " "))}</div><div class="meta">${tagPill("Creative")}<span>${info.edit ? "edit ready" : `${(info.files || []).length} file${(info.files || []).length === 1 ? "" : "s"}`} · needs your approval</span>${info.edit ? `<span class="mono" style="color:#9fb6ff">▶ watch</span>` : ""}</div></div><div class="act"><button class="btn primary sm" data-rv-folder="out/${esc(name)}" type="button">Review</button></div></div>`;
    const scrollTop = p.querySelector(".pbody") ? p.querySelector(".pbody").scrollTop : 0;
    const teamOpts = state.teams.map((t) => `<option value="${esc(t.name)}">${esc(t.name)}</option>`).join("");
    let body = "";
    const runningSec = show("running") ? sec("Running", "#4f8cff", doing.length) + (doing.map(taskRow).join("") || '<div class="hint" style="margin:2px 0 6px">Nothing running. Press Run on a task or send a brief.</div>') : "";
    const waitingSec = show("waiting") ? sec("Waiting for you", "#e4c830", counts.waiting) + outWaiting.map(approvalRow).join("") + (review.map(taskRow).join("") || (outWaiting.length ? "" : '<div class="hint" style="margin:2px 0 6px">Nothing waits for your OK.</div>')) : "";
    body += isPhone() ? waitingSec + runningSec : runningSec + waitingSec;      // a phone is for approving: what waits for you comes first
    if (f === "all" && todo.length) body += sec("To do", "#6b7280", todo.length) + todo.map(taskRow).join("");
    if (show("done")) body += sec("Done today", "#4cceac", done.length) + (done.map(taskRow).join("") || '<div class="hint" style="margin:2px 0 6px">Nothing finished yet today.</div>');
    p.innerHTML = `<div class="ph"><span class="picon">${svg("list")}</span><div class="tt"><h2>Task status</h2><div class="sub">Whole office · today</div></div><button class="xbtn" data-close type="button">${svg("close")}</button></div>
      <form class="add-task" id="add-task"><input id="task-title" type="text" placeholder="New task, for example: write the listing for the new hoodie" required><select id="task-team"><option value="">Auto</option>${teamOpts}</select><button class="btn blue" type="submit">Add</button></form>
      <div class="ftabs">${[["all", "All"], ["running", "Running"], ["waiting", "Waiting"], ["done", "Done"]].map(([k, l]) => `<button class="ftab ${f === k ? "active" : ""}" data-filter="${k}" type="button">${l} <b>${counts[k]}</b></button>`).join("")}</div>
      <div class="pbody">${body}</div>
      <div class="drop-strip"><div class="lbl"><span>Drop files · how work enters</span><span>${(st.inbox && st.inbox.clips || []).length} clips · ${(st.inbox && st.inbox.radar || []).length} notes · ${(st.inbox && st.inbox.stats || []).length} csv · ${(st.inbox && st.inbox.messages || []).length} mail</span></div><div class="drops">
        <div class="drop" data-kind="clips">Clips<small>mp4 mov mkv webm</small></div><div class="drop" data-kind="radar">Comments<small>txt md csv json</small></div><div class="drop" data-kind="stats">Analytics<small>csv exports</small></div><div class="drop" data-kind="messages">Emails<small>eml txt md json</small></div></div></div>`;
    if ($("#task-team") && state.addTeam) $("#task-team").value = state.addTeam;
    p.querySelector(".pbody").scrollTop = scrollTop;
  }
  async function taskAction(body, okText) {
    try { const r = await postJSON("/api/tasks", body); if (okText) toast("chief", "Board", okText); if (r.warning) toast("chief", "Board", r.warning, { bad: true }); await refresh(); return r; }
    catch (e) { toast("chief", "Board", e.message || "could not update the board", { bad: true }); }
  }
  async function approveOut(name) {
    try { await postJSON("/api/approve", { name }); toast("creative", "Approved", `${name} is in approved/ for you to publish.`); await refresh(); }
    catch (e) { toast("creative", "Approve", e.message || "could not approve", { bad: true }); }
  }
  async function upload(kind, files) {                     // PUT /api/inbox/<kind>/<name>: clips, comment exports, csv, emails
    for (const f of files) {
      try { await getJSON(`/api/inbox/${kind}/${encodeURIComponent(f.name)}`, { method: "PUT", body: f }); toast("chief", "Inbox", `${f.name} saved to inbox/${kind === "clips" ? "" : kind}`); }
      catch (e) { toast("chief", "Inbox", `${f.name}: ${e.message}`, { bad: true }); }
    }
    await refresh();
  }

  // ---------- the calendar ----------
  async function loadCalendar() { try { const r = await getJSON(`/api/calendar?month=${state.calMonth}`); state.calDays = r.days || {}; } catch (e) { state.calDays = {}; } renderCalendar(); }
  function renderCalendar() {
    const p = $("#calendar"), [y, m] = state.calMonth.split("-").map(Number), first = new Date(y, m - 1, 1), today = todayISO();
    const start = new Date(first); start.setDate(1 - ((first.getDay() + 6) % 7));           // Monday-first grid
    const cells = [];
    for (let i = 0; i < 42; i++) {
      const d = new Date(start); d.setDate(start.getDate() + i); const iso = isoDate(d), rows = state.calDays[iso] || [];
      cells.push(`<div class="cal-day ${d.getMonth() !== m - 1 ? "out" : ""} ${iso === today ? "today" : ""}" data-date="${iso}"><span class="dn">${d.getDate()}</span>${rows.slice(0, 3).map((t) => { const tm = teamByName(t.team); return `<button class="cal-chip" type="button" data-chip="${esc(t.id)}" style="${tm ? tagStyle(tm) : ""}" title="${esc(fmtTime(t.time) ? fmtTime(t.time) + " · " : "")}${esc(t.title)}">${esc(t.title)}</button>`; }).join("")}${rows.length > 3 ? `<span class="cal-more">+${rows.length - 3} more</span>` : ""}</div>`);
    }
    const all = Object.entries(state.calDays).sort(([a], [b]) => a.localeCompare(b));
    const teamOpts = state.teams.map((t) => `<option value="${esc(t.name)}">${esc(t.name)}</option>`).join("");
    p.innerHTML = `<div class="ph"><span class="picon" style="background:linear-gradient(135deg,#c43cc0,#e0457b)">${svg("cal")}</span><div class="tt"><h2>Calendar</h2><div class="sub">posts · meetings · deadlines</div></div><button class="xbtn" data-close type="button">${svg("close")}</button></div>
      <div class="cal-hd"><h3>${MONTHS[m - 1]} ${y}</h3><div class="nav"><button type="button" data-cal-nav="-1" title="Previous month">‹</button><button type="button" data-cal-nav="0" title="This month">•</button><button type="button" data-cal-nav="1" title="Next month">›</button></div></div>
      <div class="cal-grid">${["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((d) => `<div class="dow">${d}</div>`).join("")}${cells.join("")}</div>
      <form class="cal-add" id="cal-add"><input class="field wide" id="cal-title" type="text" placeholder="Schedule a post or meeting…" required><select class="field" id="cal-team"><option value="">Team</option>${teamOpts}</select><input class="field" id="cal-date" type="date" value="${today}" required><input class="field" id="cal-time" type="time" value="09:00"><button class="btn sm blue" type="submit" style="height:30px">Add</button></form>
      <div class="pbody cal-list" style="padding-top:6px">${all.length ? all.map(([d, rows]) => `<div class="d">${DOW[new Date(d + "T00:00:00").getDay()]} ${esc(d)} · ${esc(relDay(d))}</div>${rows.map((t) => `<div class="trow" style="min-height:52px"><span class="g"><span class="date-tile" style="width:30px;height:30px"><span class="d">${DOW[new Date(d + "T00:00:00").getDay()]}</span><span class="t" style="font-size:9px">${esc(fmtTime(t.time))}</span></span></span><div class="tt ia" data-chip="${esc(t.id)}"><div class="title">${esc(t.title)}</div><div class="meta">${tagPill(t.team)}<span>${esc(t.kind)} · ${t.status === "done" ? "done" : t.status === "review" ? "needs your OK" : "scheduled ✓"}</span></div></div><div class="act"><span class="chev">›</span></div></div>`).join("")}`).join("") : `<div class="empty">Nothing scheduled in ${MONTHS[m - 1]}. Add a dated post above, or ask Social to plan the week.</div>`}</div>`;
  }
  function calPopup(id, anchor) {                          // "TUE 9:00 · One Brain reel · tomorrow · scheduled ✓"
    const t = Object.values(state.calDays).flat().find((x) => x.id === id) || ((state.status && state.status.tasks) || []).find((x) => x.id === id);
    if (!t) return;
    $$(".cal-pop").forEach((n) => n.remove());
    const d = new Date((t.date || todayISO()) + "T00:00:00");
    const pop = el(`<div class="cal-pop ia"><span class="date-tile"><span class="d">${DOW[d.getDay()]}</span><span class="t">${esc(fmtTime(t.time) || pad2(d.getDate()))}</span></span><div style="min-width:0"><div class="title">${esc(t.title)}</div><div class="sub">${esc(relDay(t.date))} · ${t.status === "done" ? "done ✓" : t.status === "review" ? "needs your OK" : "scheduled ✓"}${t.team ? " · " + esc(t.team) : ""}</div></div><button class="x" type="button">×</button></div>`);
    const host = anchor.closest(".panel") || $("#hud"), hr = host.getBoundingClientRect(), ar = anchor.getBoundingClientRect();
    pop.style.left = clamp(ar.left - hr.left, 8, hr.width - 260) + "px"; pop.style.top = clamp(ar.bottom - hr.top + 6, 8, hr.height - 70) + "px";
    pop.querySelector(".x").onclick = () => pop.remove();
    host.appendChild(pop);
  }

  // ---------- the Brain tab ----------
  function renderBrain() {
    const p = $("#brain-view"), b = state.brain || {}, order = ["Company", "Brand rules", "Lessons", "Ideas"];
    const names = [...order, ...Object.keys(b).filter((k) => !order.includes(k))];
    const notes = state.status && state.status.brain_notes != null ? state.status.brain_notes : Object.values(b).reduce((n, a) => n + (a || []).length, 0);
    p.innerHTML = `<div class="ph"><span class="ticon" style="width:46px;height:46px;border-radius:12px;font-size:22px;background:linear-gradient(135deg,#38bdf8,#7b6cf6)">${svg("brain")}</span><div class="tt"><h2>The Brain</h2><div class="sub">shared memory · every agent reads it before working</div></div><button class="xbtn" data-close type="button">${svg("close")}</button></div>
      <div class="pbody">
        <div class="brain-stat"><span class="n">${fmtInt(notes)}</span><span class="l">notes · shared memory</span></div>
        <div class="sec"><span>Teach a rule</span><span class="cnt" style="background:none;color:#6a7080">saved by the chief of staff</span></div>
        <form class="teach" id="teach"><input class="field" id="teach-text" type="text" placeholder="for example: cover text is red, not yellow" required><button class="btn blue" type="submit">Teach</button></form>
        <div class="hint" style="margin:8px 0 14px">Sends <code>/teach &lt;rule&gt;</code> to the lead, who saves it under Brand rules. Say "from now on…" in any message and it lands here too.</div>
        <div class="bcards">${names.map((k) => { const items = b[k] || []; return `<div class="bcard"><h4>${esc(k)}<span>${items.length} note${items.length === 1 ? "" : "s"}</span></h4>${items.length ? `<ul>${items.map((o) => `<li>${esc(o)}</li>`).join("")}</ul>` : `<div class="none">${state.brain ? (k === "Company" ? "Nothing yet. Tell the lead about the company and it is saved here." : "Nothing yet.") : "loading…"}</div>`}</div>`; }).join("")}</div>
      </div>`;
  }

  // ---------- voice: the orb overlay (Web Speech API when the browser has it, typed fallback otherwise) ----------
  function openVoice() {
    const box = $("#voice-orb"); if (!box.classList.contains("mini")) return;
    box.classList.remove("mini"); box.classList.add("open");
    closeMenus(); $("#ask-input").blur();
    // the microphone needs a secure page (https or this computer); over plain http on Wi-Fi it types instead
    const SR = window.isSecureContext === false ? null : window.SpeechRecognition || window.webkitSpeechRecognition;
    state.voice = { listening: false, rec: null, typed: !SR, text: "" };
    const ta = $("#voice-text"); ta.value = ""; ta.readOnly = false; ta.placeholder = SR ? "Listening…" : "Type what you would say…";
    $("#voice-tbox").classList.toggle("typed", !SR); $("#voice-wave").classList.toggle("still", !SR);
    $("#voice-cap").textContent = SR ? "Listening" : "Type to the office"; $("#voice-hint").textContent = SR ? "Say it in one sentence, then press send." : window.isSecureContext === false ? "The microphone needs a secure (https) link. Type it, or tap the mic on your keyboard to dictate." : "Voice input is not available in this browser. Type your request instead.";
    $("#voice-mic").classList.toggle("off", !SR);
    if (SR) startListening(SR); else ta.focus();
    renderAgentPills(); renderTopbar(); phonePause();
  }
  function startListening(SR) {
    const v = state.voice; if (!v) return;
    try {
      const rec = new SR(); rec.continuous = true; rec.interimResults = true; rec.lang = navigator.language || "en-US";
      rec.onresult = (e) => { let fin = "", tmp = ""; for (let i = 0; i < e.results.length; i++) { const r = e.results[i]; if (r.isFinal) fin += r[0].transcript + " "; else tmp += r[0].transcript; } v.text = (fin + tmp).trim(); $("#voice-text").value = v.text; };
      rec.onerror = (e) => { if (["not-allowed", "service-not-allowed", "audio-capture", "network"].includes(e.error)) typedFallback(e.error === "network" ? "Speech recognition needs network access here. Type instead." : isPhone() ? "Microphone not available. Type it, or tap the mic on your keyboard to dictate." : "Microphone not available. Type your request instead."); };
      rec.onend = () => { if (state.voice && state.voice.listening && state.voice.rec === rec) { try { rec.start(); } catch (e) { /* stopped */ } } };
      rec.start(); v.rec = rec; v.listening = true;
      $("#voice-mic").classList.remove("off"); $("#voice-wave").classList.remove("still"); $("#voice-cap").textContent = "Listening";
      clearTimeout(v.quietTimer);                            // nothing heard for a while: say so, typing works anyway
      v.quietTimer = setTimeout(() => { if (state.voice === v && v.listening && !$("#voice-text").value.trim()) $("#voice-hint").textContent = "Nothing heard yet. You can also type it here and press send."; }, 6000);
    } catch (e) { typedFallback("Voice input is not available here. Type your request instead."); }
    renderAgentPills();
  }
  function stopListening() { const v = state.voice; if (!v) return; v.listening = false; clearTimeout(v.quietTimer); if (v.rec) { try { v.rec.stop(); } catch (e) { /* already stopped */ } v.rec = null; } $("#voice-mic").classList.add("off"); $("#voice-wave").classList.add("still"); $("#voice-cap").textContent = "Paused"; renderAgentPills(); }
  function typedFallback(msg) { const v = state.voice; if (!v) return; stopListening(); v.typed = true; const ta = $("#voice-text"); ta.readOnly = false; ta.placeholder = "Type what you would say…"; $("#voice-tbox").classList.add("typed"); $("#voice-cap").textContent = "Type to the office"; $("#voice-hint").textContent = msg || ""; ta.focus(); }
  function closeVoice() { stopListening(); state.voice = null; const box = $("#voice-orb"); box.classList.remove("open"); box.classList.add("mini"); $("#orb").classList.remove("thinking"); renderAgentPills(); renderTopbar(); phonePause(); }
  function sendVoice() { const text = $("#voice-text").value.trim(); if (!text) { $("#voice-hint").textContent = "Nothing heard yet."; return; } closeVoice(); send(text); }

  // ---------- Ask any agent (top bar) ----------
  function buildAskMenu() {
    const menu = $("#ask-menu"), q = ($("#ask-input").value || "").trim().toLowerCase();
    const filt = q.startsWith("@") ? q.slice(1) : "";
    const groups = state.teams.map((t) => ({ t, agents: membersOf(t).filter((a) => !filt || a.label.toLowerCase().includes(filt) || a.name.includes(filt)) })).filter((g) => g.agents.length);
    menu.innerHTML = `<div class="grp">Ask</div><button class="opt ${!state.askAgent ? "sel" : ""}" type="button" data-pick=""><span class="av" style="background:linear-gradient(135deg,#7583fb,#14343d)">HQ</span>Any agent · the chief of staff routes it<span class="sub">default</span></button>` +
      groups.map((g) => `<div class="grp">${esc(g.t.name)}</div>${g.agents.map((a, i) => `<button class="opt ${state.askAgent === a.name ? "sel" : ""}" type="button" data-pick="${esc(a.name)}"><span class="av" style="background:${avColor(a, g.t, i)}">${esc(initials(a.label))}</span>${esc(a.label)}<span class="sub">${a.role === "head" ? "lead · " : ""}${esc(a.model || "")}</span></button>`).join("")}`).join("");
  }
  function pickAgent(name) {
    state.askAgent = name || null; const who = $("#ask-who"), a = agentByName(name);
    who.classList.toggle("on", !!a); who.innerHTML = a ? `Ask <b>${esc(a.label)}</b><button type="button" id="ask-unpick" title="Any agent">×</button>` : "";
    $("#ask-input").placeholder = a ? `Ask ${a.label}…` : "Ask any agent…";
    buildAskMenu();
  }
  function focusAsk() { if (isPhone()) { openAsk(); return; } const i = $("#ask-input"); i.focus(); i.select(); }
  function submitAsk() {
    const i = $("#ask-input"), q = i.value.trim(); if (!q || q === "@") return;
    const a = agentByName(state.askAgent);
    send(a ? `Ask ${a.name}: ${q}` : q); i.value = ""; $("#ask-menu").hidden = true; i.blur();
    if (isPhone()) { closeAsk(); setLead(true); }           // a phone: watch the lead work on it
  }

  // ---------- agent card (click a character or a name pill) ----------
  function showAgentCard(name, quiet) {
    const a = agentByName(name), card = $("#agent-card");
    if (!a) { card.hidden = true; state.agentCard = null; return; }
    state.agentCard = name;
    const t = teamByName(a.team), r = runningMap()[a.name];
    card.innerHTML = `<div class="agent-card-head"><span class="av" style="background:${accent(t)};width:28px;height:28px;font-size:10px;box-shadow:none">${esc(initials(a.label))}</span><strong>${esc(a.label)}</strong><span class="tag ${r ? "ok" : ""}">${r ? (typeof r === "string" && r !== "working" ? esc(r.split(" ")[0]) : "working") : "idle"}</span><button class="small" data-close type="button">×</button></div>
      <div class="agent-card-meta">${esc(a.team)} · ${a.role === "head" ? "team head" : "worker"}${a.model ? " · " + esc(a.model) : ""}</div>
      <p>${esc(a.description || "")}</p>${typeof r === "string" && r.length > 12 ? `<p class="agent-card-task">Now: ${esc(r)}</p>` : ""}${r ? "" : lifeLine(callScene("lifeOf", a.name))}
      ${a.skills && a.skills.length ? `<div class="agent-card-row">Skills: ${a.skills.map(esc).join(", ")}</div>` : ""}
      <div class="agent-card-row"><code>.claude/agents/${esc(a.name)}.md</code></div>
      <div class="row"><button class="btn sm blue" data-ask="${esc(a.name)}" type="button">Ask ${esc(a.label)}</button>${t ? `<button class="btn sm" data-team="${esc(t.key)}" type="button">Open ${esc(t.name)}</button>` : ""}</div>`;
    card.hidden = false;
    if (!quiet) callScene("select", name);
  }
  function hideAgentCard() { $("#agent-card").hidden = true; state.agentCard = null; callScene("select", null); }

  // ---------- the lead's run stream (ported from the first app): /api/run then /api/runs/<id>?after=N every 800 ms ----------
  function log(cls, text) {
    const con = $("#lead-con"), d = document.createElement("div"); d.className = "ev " + cls; d.textContent = text; con.appendChild(d);
    while (con.children.length > 400) con.firstElementChild.remove();
    con.scrollTop = con.scrollHeight;
  }
  function handle(ev) {
    if (ev.type === "tool") {
      if (ev.staff) { const text = String(ev.text || "").replace(/^[^:]+:\s*/, ""); state.pending[ev.id] = { staff: ev.staff, text, start: Date.now() }; state.working[ev.staff] = text; log("staff", "→ " + ev.text); }
      else log("tool", "· " + (ev.text || ev.name || ""));
    } else if (ev.type === "tool_done") {
      const p = state.pending[ev.id];
      if (p && /background/i.test(ev.text || "")) log("staff", "… " + p.staff + " is working in the background");    // stays lit until the lead's reply
      else if (p) { delete state.pending[ev.id]; if (!Object.values(state.pending).some((q) => q.staff === p.staff)) delete state.working[p.staff]; state.finished[p.staff] = Date.now(); log("staff", "← " + p.staff + (ev.is_error ? " (error)" : " done")); }
    } else if (ev.type === "text") { log("text", ev.text); state.lastReply = ev.text; $("#lead-text").textContent = "Lead · " + shortTask(ev.text, 70); }
    else if (ev.type === "result") {
      for (const k of Object.keys(state.working)) delete state.working[k];
      for (const k of Object.keys(state.pending)) delete state.pending[k];
      const reply = ev.text || (ev.is_error ? "The lead hit an error. See the Lead log." : "(no reply)");
      const stats = ev.cost_usd != null ? ` (${ev.turns} turns, ${(ev.duration_ms / 1000).toFixed(0)}s, $${Number(ev.cost_usd).toFixed(3)})` : "";
      log(ev.is_error ? "error" : "result", (reply === state.lastReply ? "done" : reply) + stats);
      state.lastReply = reply; $("#lead-text").textContent = "Lead · " + shortTask(reply, 70);
      const leadSheet = isPhone() && $("#lead-log").classList.contains("open");   // a phone with the lead sheet open already shows the reply
      if ((!state.run.quiet || ev.is_error) && !leadSheet) toast("chief", "Chief of staff", shortTask(reply, 180), { bad: !!ev.is_error });
      $("#orb").classList.remove("thinking");
    } else log(ev.type || "system", ev.text || "");
    subsCache.t = 0; renderTopbar(); renderTeamCards(); renderAgentPills(); renderSubCards(); syncSubagents();
  }
  function attach(id, quiet) { state.run.id = id; state.run.offset = 0; state.run.said = false; state.run.quiet = !!quiet; state.run.seen.add(id); $("#lead-log").classList.add("busy"); poll(); }
  async function poll() {
    if (!state.run.id) return;
    try {
      const r = await getJSON(`/api/runs/${state.run.id}?after=${state.run.offset}`);
      // print "you: …" once per run: Claude can take a minute to start, and this poll repeats meanwhile
      if (!state.run.said && r.prompt) { state.run.said = true; log("you", "you: " + r.prompt); $("#lead-text").textContent = "Lead · working: " + shortTask(r.prompt, 60); }
      (r.events || []).forEach(handle); state.run.offset = (r.offset || 0) + (r.events || []).length;
      if (!r.done) return setTimeout(poll, 800);
      state.run.id = null; refresh();
    } catch (e) { if (e.status === 404) { state.run.id = null; return; } setTimeout(poll, 2000); }
  }
  function attachOngoingRun(s) {                           // a run started elsewhere (the CLI, another tab): follow it quietly
    if (!state.run.id && s && s.desk && s.desk.busy && s.desk.current && !state.run.seen.has(s.desk.current)) attach(s.desk.current, true);
  }
  async function send(prompt) {                            // HQ.send(prompt): one message to the lead
    prompt = String(prompt || "").trim(); if (!prompt) return null;
    try {
      const r = await postJSON("/api/run", { prompt });
      $("#lead-text").textContent = "Lead · working: " + shortTask(prompt, 60);
      attach(r.id, false); renderTopbar(); return r.id;
    } catch (e) { toast("chief", "Chief of staff", e.status === 409 ? "The lead is still working on the previous message." : e.message || "could not send", { bad: true }); return null; }
  }

  // ---------- sub-agent progress cards (right edge): CUT → CAPTIONS → THUMBNAIL ----------
  function renderSubCards() {
    const host = $("#subagent-cards"), subs = subagentsMap(), items = Object.values(subs).flat();
    if (!items.length) { host.innerHTML = ""; return; }
    const steps = (it) => { const clip = it.agent === "clip-editor" || /\.(mp4|mov|m4v|mkv|webm)$/i.test(it.file || "") || /clip/i.test(it.label || ""); const names = clip ? ["cut", "captions", "thumbnail"] : ["start", "work", "report"]; const idx = Math.min(names.length - 1, Math.floor((it.progress / 100) * names.length)); return names.map((n, i) => `<span class="step ${i < idx ? "ok" : i === idx ? "on" : ""}">${n}</span>`).join(""); };
    // update the cards in place (a rebuild every second would restart their rise animation and flicker)
    const live = new Set(items.map((it) => it.id));
    for (const c of Array.from(host.children)) if (!live.has(c.dataset.sub)) c.remove();
    items.forEach((it, i) => {
      let card = host.querySelector(`.scard[data-sub="${cssq(it.id)}"]`);
      if (!card) { card = el(`<div class="scard" data-sub="${esc(it.id)}"><div class="t"></div><div class="steps"></div><span class="line"></span></div>`); host.appendChild(card); }
      if (host.children[i] !== card) host.insertBefore(card, host.children[i] || null);
      const title = `Sub-agent ${i + 1} · ${it.file || it.label.replace(/^Sub \d+ · /, "")}`, st = steps(it);
      if (card.firstChild.textContent !== title) card.firstChild.textContent = title;
      if (card.dataset.steps !== st) { card.querySelector(".steps").innerHTML = st; card.dataset.steps = st; }
      card.querySelector(".line").style.width = `${it.progress}%`;
    });
  }

  // ---------- office life: what an idle agent is up to, the "shared a tip" toast, the on/off switch ----------
  function lifeLine(l) {
    if (!l || !l.action) return "";
    const who = l.partner ? ((agentByName(l.partner) || {}).label || l.partner) : "";
    if (l.homing) return `<p class="agent-card-life">🏃 Heading back to the desk</p>`;
    if (l.done && !l.talking && (l.action === "visit" || l.action === "chat")) return `<p class="agent-card-life">👋 Heading back after a chat${who ? ` with <b>${esc(who)}</b>` : ""}</p>`;
    if (l.talking && who) return `<p class="agent-card-life">💬 Talking with <b>${esc(who)}</b>${l.topic ? ` about: ${esc(shortTask(l.topic, 140))}` : ""}</p>`;
    const text = { coffee: "☕ On a coffee break", phone: "📞 On a phone call", note: "📝 Dropping a note into the Brain", stretch: "🙆 Stretching their legs",
      visit: who ? `🚶 On the way to visit <b>${esc(who)}</b>` : "🚶 Visiting another team", host: who ? `👋 Welcoming <b>${esc(who)}</b>` : "", chat: who ? `💬 Meeting <b>${esc(who)}</b> at the coffee machine` : "" }[l.action];
    return text ? `<p class="agent-card-life">${text}${l.topic && l.action === "visit" ? ` · about: ${esc(shortTask(l.topic, 120))}` : ""}</p>` : "";
  }
  function lifeEvent(ev) {                                 // from the scene: a visitor shared a lesson with another team
    if (!ev || ev.type !== "tip" || !ev.from || !ev.to) return;
    if (Date.now() - state.lifeTipAt < 120000 || document.hidden) return;   // at most one every 2 minutes
    if (isPhone() && state.view !== "office") return;
    state.lifeTipAt = Date.now();
    showToast({ teamKey: ev.fromKey || ev.from, title: `${ev.from} shared a tip with ${ev.to}`, body: shortTask(ev.text || "", 120), soft: true });   // soft: a toast only, the bell stays quiet
  }
  function renderLifeItem() { const b = $("#menu-life"); if (b) b.innerHTML = `Office life<span class="life-state ${state.life ? "on" : ""}">${state.life ? "on" : "off"}</span>`; }
  function setLife(on, save = true) {
    state.life = !!on; renderLifeItem();
    if (save) { try { localStorage.setItem("hq.officeLife", state.life ? "on" : "off"); } catch (e) { /* private mode: not remembered */ } }
    callScene("life", state.life);
  }
  function initLife() {
    try { state.life = localStorage.getItem("hq.officeLife") !== "off"; } catch (e) { state.life = true; }
    const lead = $("#menu-lead");
    if (lead && !$("#menu-life")) { const b = el(`<button class="menu-item" id="menu-life" type="button" title="Agents get up, fetch coffee, visit other teams and share lessons while idle"></button>`); lead.parentNode.insertBefore(b, lead.nextSibling); }
    renderLifeItem();
  }

  // ---------- the scene: callbacks, direct spawn calls, label blanking ----------
  function onSceneReady() {
    const O = window.HQ_OFFICE; if (!O || state.scene) return; state.scene = true;
    O.onRoomClick = (key) => roomTap(key);
    O.onAgentClick = (name) => showAgentCard(name);
    O.onBrainClick = () => openPanel(state.view === "brain" ? "office" : "brain");
    O.onLife = (ev) => lifeEvent(ev);
    callScene("life", state.life);
    // Notice sub-agents spawned straight on the scene (tests, the console) so the pills, cards and counters agree.
    if (typeof O.spawnSubagents === "function" && !O.spawnSubagents.hqWrapped) {
      const spawn = O.spawnSubagents, clear = O.clearSubagents;
      O.spawnSubagents = function (key, items) { if (!state.selfCall) { state.sceneSubs[key] = (items || []).map((i) => ({ id: String(i.id), label: i.label || "", subtitle: i.subtitle || "", subtitle0: i.subtitle || "", progress: i.progress || 0, progress0: i.progress || 0, start: Date.now(), agent: "", file: fileIn(i.label), team: key })); subsCache.t = 0; setTimeout(renderAll, 50); } return spawn.apply(O, arguments); };
      O.spawnSubagents.hqWrapped = true;
      O.clearSubagents = function (key) { delete state.sceneSubs[key]; subsCache.t = 0; setTimeout(renderAll, 50); return clear ? clear.apply(O, arguments) : undefined; };
    }
    state.zoom = Number(callScene("getZoomPercent")) || 100;
    renderAll(); drawMinimap();
  }

  // ---------- the review screen: watch, read and approve finished work without leaving the office ----------
  // Opens over everything (full screen on a phone, a large card on desktop). Videos play inline, covers open in a
  // lightbox, captions are a tappable list that seeks the video, post copy has Copy buttons, and Approve / Ask for
  // changes act right here. The phone's back gesture and the browser's Back button close it (history state), so the
  // owner never lands on a raw file with no way home.
  var rv = { open: false, folder: null, taskId: null, data: null, vid: 0, img: null, mode: null, pushed: false };
  const fmtBytes = (n) => (n > 1e6 ? (n / 1e6).toFixed(1) + " MB" : n > 1e3 ? Math.round(n / 1e3) + " KB" : n + " B");
  const prettyName = (s) => String(s || "").replace(/\.[a-z0-9]+$/i, "").replace(/[-_]+/g, " ").trim();
  // A task's work folder: out/<name> while it waits for the OK, approved/<name> once approved (the folder moves there,
  // the task's note still says out:<name>), so an approved video can be opened again to post or schedule it.
  function folderOfTask(t) {
    const m = /out:([^\s,;]+)/.exec((t && t.note) || ""); if (!m) return null;
    const name = m[1].replace(/\/+$/, ""), top = name.split("/")[0], st = state.status || {};
    return !(st.out && st.out[top]) && st.approved && st.approved[top] ? "approved/" + name : "out/" + name;
  }
  function ensureReviewHost() {
    let host = $("#review");
    if (!host) {
      host = el('<div id="review" class="review" hidden role="dialog" aria-modal="true"></div>'); document.body.appendChild(host);
      host.addEventListener("input", (e) => { const d = e.target.dataset || {}; if (d.pubField) rv.edits[d.pubField] = e.target.value; if (d.pubWhen != null) { rv.whenVal = e.target.value; const n = $("#pub-when-say"); if (n) n.textContent = whenSay(); } });
      host.addEventListener("change", (e) => { const k = e.target.dataset && e.target.dataset.pubSel; if (k) { rv.sel[k] = e.target.checked; renderReview(); } });
    }
    return host;
  }
  async function openReview({ folder, taskId, accounts, channel }) {
    const host = ensureReviewHost(), st = state.status || {};
    const task = taskId ? (st.tasks || []).find((t) => t.id === taskId) : null;
    stopPubPoll();
    Object.assign(rv, { open: true, folder: accounts ? null : folder || folderOfTask(task), taskId: taskId || null, data: null, vid: 0, img: null, mode: null,
      accounts: !!accounts, acc: null, accBusy: "", ch: channel || "", chans: rv.chans || null, pub: null, pubSub: "", pubEdit: false, whenOn: false, whenVal: "", edits: {}, sel: null, pick: {} });
    if (!rv.pushed) { try { history.pushState({ hqReview: 1 }, ""); rv.pushed = true; } catch (e) { /* no history API */ } }
    host.hidden = false; document.body.classList.add("review-open"); closeMenus(); hideAgentCard(); callScene("pause", true);
    renderReview();
    if (rv.folder) {
      try { rv.data = await getJSON(`/api/work?folder=${encodeURIComponent(rv.folder)}`); }
      catch (e) { rv.data = { error: e.message || "could not open this folder", files: [] }; }
      if (rv.open) renderReview();
      loadPub();
    }
    if (rv.accounts) loadAccounts();
  }
  // ---- posting: the overview of what goes where, and the owner's Approve & post (the only thing that posts)
  const PUB = [["facebook", "Facebook"], ["instagram", "Instagram"], ["youtube", "YouTube Shorts"]];
  const PUB_URL = "/api/" + "publish";
  // what can be posted: the folder itself, or each topic of a long talk (a subfolder with its own post.md)
  const pubTargets = () => ((rv.data && rv.data.files) || []).filter((f) => /^post\.md$/i.test(f.name) && f.path.split("/").length <= 2).map((f) => f.path.split("/").slice(0, -1).join("/"));
  const pubFolder = () => rv.folder + (rv.pubSub ? "/" + rv.pubSub : "");
  async function loadPub(sub) {
    const targets = pubTargets();
    if (!rv.folder || !targets.length) { rv.pub = null; return; }
    if (sub != null) rv.pubSub = sub; else if (!targets.includes(rv.pubSub)) rv.pubSub = targets[0];
    if (sub != null) { rv.sel = null; rv.edits = {}; rv.pick = {}; }
    try { rv.pub = await getJSON(`${PUB_URL}?folder=${encodeURIComponent(pubFolder())}`); } catch (e) { rv.pub = null; }
    if (rv.pub && !rv.sel) { rv.sel = {}; for (const [k] of PUB) rv.sel[k] = !!(rv.pub.accounts[k] || {}).connected && !["posted", "scheduled"].includes((rv.pub.posted[k] || {}).state); }
    if (rv.pub && rv.pub.busy) startPubPoll();
    if (rv.open) renderReview();
  }
  function stopPubPoll() { if (rv.poll) { clearInterval(rv.poll); rv.poll = null; } }
  function startPubPoll() {
    stopPubPoll();
    rv.poll = setInterval(async () => {
      if (!rv.open || !rv.folder) return stopPubPoll();
      try { rv.pub = await getJSON(`${PUB_URL}?folder=${encodeURIComponent(pubFolder())}`); } catch (e) { return; }
      renderReview();
      if (!rv.pub.busy) {
        stopPubPoll();
        const r = rv.pub.posted || {}, ok = PUB.filter(([k]) => (r[k] || {}).state === "posted").map(([, n]) => n), bad = PUB.filter(([k]) => (r[k] || {}).state === "failed").map(([, n]) => n);
        if (ok.length) toast("social", "Posted", ok.join(", ") + (bad.length ? ` · failed: ${bad.join(", ")}` : ""));
        else if (bad.length) toast("social", "Posting failed", bad.join(", ") + ": see the review screen", { bad: true });
      }
    }, 3000);
  }
  const chosenPub = () => PUB.filter(([k]) => rv.pub && rv.sel && rv.sel[k] && (rv.pub.accounts[k] || {}).connected).map(([k]) => k);
  function pubValue(k, f) { const key = k + "." + f; return rv.edits[key] != null ? rv.edits[key] : ((rv.pub.drafts[k] || {})[f] || ""); }
  function pickPub(kind, val) {                             // the owner picks the topic, the thumbnail, the video, or one caption for every platform
    if (kind === "topic") { stopPubPoll(); loadPub(val); return; }
    if (kind === "edit") { rv.pubEdit = !rv.pubEdit; renderReview(); return; }
    if (kind === "when") { rv.whenOn = val === "later"; if (rv.whenOn && !rv.whenVal) rv.whenVal = defaultWhen(); renderReview(); return; }
    if (kind === "video" || kind === "cover") rv.pick[kind] = val;
    else if (kind === "caption") {
      const o = ((rv.pub.drafts || {}).options || [])[+val];
      if (o) { for (const [k] of PUB) for (const [f, v] of Object.entries(o[k] || {})) rv.edits[k + "." + f] = v; rv.pick.caption = +val; }
    }
    renderReview();
  }
  // ---- scheduling: a local date and time from the picker, sent as a unix time
  const pad = (n) => String(n).padStart(2, "0");
  const localInput = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
  function defaultWhen() { const d = new Date(Date.now() + 86400000); d.setHours(20, 0, 0, 0); return localInput(d); }   // tomorrow 8 pm
  const whenUnix = () => (rv.whenOn && rv.whenVal ? Math.floor(new Date(rv.whenVal).getTime() / 1000) : null);
  const fmtWhen = (u) => new Date(u * 1000).toLocaleString([], { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
  function whenSay() { const u = whenUnix(); if (!u) return ""; const m = Math.round((u * 1000 - Date.now()) / 60000); return m < 10 ? "Pick a time at least 10 minutes from now." : `Goes out ${fmtWhen(u)}.`; }
  async function cancelScheduled(k) {
    try { rv.pub = await postJSON(PUB_URL, { folder: pubFolder(), cancel: k }); renderReview(); toast("social", "Cancelled", "The scheduled Instagram post won't go out."); }
    catch (e) { toast("social", "Cancel", e.message || "could not cancel", { bad: true }); }
  }
  async function startPost() {
    const folder = pubFolder();
    if (!folder.startsWith("approved/") || !rv.pub) return;
    const platforms = {};
    for (const k of chosenPub()) {
      platforms[k] = k === "youtube" ? { title: pubValue(k, "title"), description: pubValue(k, "description") } : { caption: pubValue(k, "caption") };
      if (((rv.pub.posted || {})[k] || {}).state === "posted") platforms[k].again = true;
    }
    if (!Object.keys(platforms).length) return;
    const when = whenUnix();
    const body = { folder, platforms, video: rv.pick.video || rv.pub.video, cover: rv.pick.cover || rv.pub.cover, when };
    const names = Object.keys(platforms).map((k) => PUB.find((p) => p[0] === k)[1]).join(", ");
    try { rv.pub = await postJSON(PUB_URL, body); renderReview(); startPubPoll(); toast("social", when ? "Scheduled" : "Posting", when ? `${names} · ${fmtWhen(when)}` : names); }
    catch (e) { toast("social", "Post", e.message || "could not post", { bad: true }); }
  }
  function pubSection() {
    const p = rv.pub; if (!p) return "";
    const sub = rv.pubSub || "", files = (rv.data && rv.data.files) || [];
    const fileOf = (rel) => files.find((f) => f.path === (sub ? sub + "/" : "") + rel);
    const post = fileOf("post.md");
    const plan = post ? postSections(post.text).find((x) => /^plan\b/i.test(x.title)) : null;
    const vSel = rv.pick.video || p.video, cSel = rv.pick.cover || p.cover, cap = rv.pick.caption || 0;
    const opts = (p.drafts && p.drafts.options) || [], targets = pubTargets(), on = chosenPub();
    let h = `<div class="rv-sec pub"><div class="rv-h">Posting overview <span>${p.channel ? "for " + esc(p.channel_name || p.channel) + " · " : ""}prepared by Social</span><button class="rv-copy" data-rv-accounts="${esc(p.channel || "")}" type="button">Accounts</button></div>`;
    if (targets.length > 1) h += `<div class="pub-h">Topic <span>each topic is its own post</span></div><div class="rv-chips">${targets.map((t) => `<button class="rv-chip ${t === sub ? "on" : ""}" data-pub-pick="topic" data-pub-val="${esc(t)}" type="button">${esc(prettyName(t || "main"))}</button>`).join("")}</div>`;
    if (plan) h += `<div class="md pub-plan">${mdHtml(plan.body)}</div>`;
    // the final check: the three parts of the post, each ticked when it is there, and the video itself to play
    const vf = vSel ? fileOf(vSel) : null, vUrl = vf ? vf.url : vSel && (p.linked || []).includes(vSel) ? "/files/" + vSel.split("/").map(encodeURIComponent).join("/") : "";
    const cf = cSel ? fileOf(cSel) : null, capText = opts.length ? ((opts[cap] || opts[0]).caption || (opts[cap] || opts[0]).title || "") : "";
    const ready = { video: !!vUrl, thumb: !!cf, caption: !!String(capText).trim() };
    rv.ready = ready.video && ready.thumb && ready.caption;
    const tick = (ok, label, what) => `<span class="fin-item ${ok ? "ok" : "no"}">${ok ? svg("check") : "!"}<b>${label}</b><span>${esc(what)}</span></span>`;
    h += `<div class="pub-final ${rv.ready ? "ready" : ""}"><div class="fin-h">${rv.ready ? "Final · ready to post" : "Final · not ready yet"}</div>
      <div class="fin-items">${tick(ready.video, "Video", ready.video ? prettyName(vSel) : "missing")}${tick(ready.thumb, "Thumbnail", ready.thumb ? prettyName(cSel) : "missing")}${tick(ready.caption, "Caption", ready.caption ? "option " + (cap + 1) : "missing")}</div>
      ${vUrl ? `<video class="fin-video" src="${esc(vUrl)}" ${cf ? `poster="${esc(cf.url)}"` : ""} controls playsinline preload="metadata"></video>` : ""}</div>`;
    // 1. the thumbnail: one for every platform
    const covers = (p.covers || []).map((n) => ({ n, f: fileOf(n) })).filter((x) => x.f);
    if (covers.length) h += `<div class="pub-h">1 · Thumbnail <span>${covers.length > 1 ? "tap the one you want, it goes on every platform" : "used on every platform"}</span></div><div class="pub-pick">${covers.map(({ n, f }) => `<button class="pub-thumb ${n === cSel ? "on" : ""}" data-pub-pick="cover" data-pub-val="${esc(n)}" type="button"><img src="${esc(f.url)}" alt="" loading="lazy">${n === cSel ? `<i>${svg("check")}</i>` : ""}</button>`).join("")}</div>`;
    // 2. the caption: one choice fills Facebook, Instagram and YouTube
    if (opts.length) h += `<div class="pub-h">2 · Caption <span>${opts.length > 1 ? "tap one, it fills every platform" : "used on every platform"}</span></div><div class="pub-caps">${opts.map((o, i) => `<button class="pub-cap ${i === cap ? "on" : ""}" data-pub-pick="caption" data-pub-val="${i}" type="button">${i === cap ? `<i>${svg("check")}</i>` : ""}<b>${esc(o.title || "")}</b><span>${esc(o.caption || "")}</span></button>`).join("")}</div>`;
    // 3. the video: only when there is more than one version
    if ((p.videos || []).length > 1) h += `<div class="pub-h">Video <span>which version to post</span></div><div class="rv-chips">${p.videos.map((n) => `<button class="rv-chip ${n === vSel ? "on" : ""}" data-pub-pick="video" data-pub-val="${esc(n)}" type="button">${n === vSel ? svg("check") : svg("play")}${esc(prettyName(n))}</button>`).join("")}</div>`;
    else if (!p.videos || !p.videos.length) h += '<div class="pub-warn">No video found in this folder yet, so there is nothing to post.</div>';
    // where it goes
    h += `<div class="pub-h">${opts.length ? "3" : "2"} · Post to</div>`;
    for (const [k, label] of PUB) {
      const acc = p.accounts[k] || {}, done = (p.posted || {})[k] || {}, ticked = on.includes(k);
      const st = done.state === "posted" ? `<a class="pub-ok" href="${esc(done.link || "#")}" target="_blank" rel="noopener">${svg("check")} Posted · view</a>`
        : done.state === "failed" ? `<span class="pub-bad">Failed: ${esc(done.error || "")}</span>`
        : done.state === "scheduled" ? `<span class="pub-sched">${svg("cal")} Scheduled · ${esc(fmtWhen(done.when))}${done.job ? ` <button class="rv-copy" data-pub-cancel="${k}" type="button">Cancel</button>` : ""}</span>`
        : done.state === "cancelled" ? '<span class="pub-acc">Schedule cancelled</span>'
        : ["posting", "waiting", "uploading"].includes(done.state) ? `<span class="pub-run"><span class="spin"></span> ${({ posting: "Posting…", waiting: "Waiting…", uploading: "Uploading for the scheduled time…" })[done.state]}</span>` : "";
      h += `<div class="pub-row ${ticked ? "on" : ""}"><label class="pub-top"><input type="checkbox" data-pub-sel="${k}" ${ticked ? "checked" : ""} ${acc.connected ? "" : "disabled"}><b>${label}</b>
        <span class="pub-acc">${acc.connected ? esc(acc.name || "connected") : acc.problem ? esc(acc.problem) : "not connected"}</span></label>${st}`;
      if (!acc.connected) h += `<button class="rv-copy" data-rv-accounts="${esc(p.channel || "")}" type="button">Connect</button>`;
      if (done.warning) h += `<div class="pub-warn">${esc(done.warning)}</div>`;
      if (ticked && rv.pubEdit) h += k === "youtube"
        ? `<input class="pub-in" data-pub-field="youtube.title" maxlength="100" value="${esc(pubValue(k, "title"))}" placeholder="Title"><textarea class="pub-in" rows="3" data-pub-field="youtube.description" placeholder="Description">${esc(pubValue(k, "description"))}</textarea>`
        : `<textarea class="pub-in" rows="4" data-pub-field="${k}.caption" placeholder="Caption">${esc(pubValue(k, "caption"))}</textarea>`;
      h += "</div>";
    }
    if (on.length) h += `<button class="rv-copy pub-edit" data-pub-pick="edit" type="button">${rv.pubEdit ? "Hide the text per platform" : "Change the text for one platform"}</button>`;
    if (on.length) {
      h += `<div class="pub-h">${opts.length ? "4" : "3"} · When</div><div class="rv-chips"><button class="rv-chip ${rv.whenOn ? "" : "on"}" data-pub-pick="when" data-pub-val="now" type="button">${rv.whenOn ? "" : svg("check")}Post now</button><button class="rv-chip ${rv.whenOn ? "on" : ""}" data-pub-pick="when" data-pub-val="later" type="button">${rv.whenOn ? svg("check") : svg("cal")}Schedule</button></div>`;
      if (rv.whenOn) h += `<input class="pub-in pub-when" type="datetime-local" data-pub-when value="${esc(rv.whenVal)}" min="${localInput(new Date(Date.now() + 11 * 60000))}"><div class="pub-note" id="pub-when-say">${esc(whenSay())}</div>${on.includes("instagram") ? '<div class="pub-note">Facebook and YouTube publish it themselves at that time. Instagram is posted by Agents HQ, so keep this computer on with Agents HQ running then; if it was off, it posts as soon as Agents HQ opens again.</div>' : ""}`;
    }
    h += `<div class="pub-note">${rv.whenOn ? "Schedules" : "Posts"} <b>${esc(vSel ? prettyName(vSel) : "no video")}</b>${cSel ? " with the thumbnail you picked" : ""} and caption ${opts.length ? cap + 1 : ""} on every ticked account${rv.whenOn ? " for the time above" : " at the same time"}. TikTok: post by hand with the TikTok text below.</div></div>`;
    return h;
  }
  // ---- accounts: connect Facebook + Instagram (one Meta app) and YouTube (one Google OAuth client), once
  async function loadAccounts() {
    try { rv.chans = (await getJSON("/api/channels")).channels; } catch (e) { rv.chans = rv.chans || []; }
    if (rv.ch !== "+" && !(rv.chans || []).some((c) => c.key === rv.ch)) rv.ch = "";
    if (rv.ch === "+") rv.acc = {};
    else { try { rv.acc = await getJSON("/api/accounts?channel=" + encodeURIComponent(rv.ch)); } catch (e) { rv.acc = { error: e.message }; } }
    if (rv.open && rv.accounts) renderReview();
  }
  function pickChannel(key) { rv.ch = key; rv.acc = null; renderReview(); loadAccounts(); }
  // ---- channels: each brand with its own brain, its own accounts and its own Google Drive folder for raw footage
  async function channelAction(what) {
    const v = (id) => { const x = $("#" + id); return x ? x.value.trim() : ""; };
    const body = what === "add" ? { action: "add", name: v("ch-name"), about: v("ch-about"), drive: v("ch-drive") }
      : what === "scan" ? { action: "scan" } : { action: "update", key: rv.ch, drive: v("ch-drive"), ...(rv.ch ? {} : { name: v("ch-main-name") }) };
    rv.accBusy = "ch-" + what; renderReview();
    try {
      const r = await postJSON("/api/channels", body);
      rv.chans = r.channels;
      if (what === "add") { rv.ch = r.added; toast("social", "Channel added", `${body.name}: connect its accounts below, and tell the chief of staff about its brand so the agents know its style.`); loadAccounts(); }
      else if (what === "scan") toast("creative", "Google Drive", r.imported && r.imported.length ? `${r.imported.length} new video(s) on the board as New footage.` : "No new videos yet. A video shows up about a minute after Drive has finished syncing it.");
      else toast("social", "Saved", body.drive ? "New videos in that folder will show up on the board as New footage." : "Saved.");
    } catch (e) { toast("social", "Channels", e.message || "could not save", { bad: true }); }
    rv.accBusy = ""; if (rv.open) renderReview();
  }
  function channelsSec() {
    const list = rv.chans || [], cur = list.find((c) => c.key === rv.ch), busy = (k) => (rv.accBusy === k ? '<span class="spin"></span> ' : "");
    const name = (c) => c.name || (c.main ? "Main channel" : c.key);
    let h = `<div class="rv-sec acc"><div class="rv-h">Channel <span>each one has its own brand, accounts and Drive folder</span></div><div class="rv-chips">`
      + list.map((c) => `<button class="rv-chip ${c.key === rv.ch ? "on" : ""}" data-chan="${esc(c.key)}" type="button">${c.key === rv.ch ? svg("check") : ""}${esc(name(c))}</button>`).join("")
      + `<button class="rv-chip ${rv.ch === "+" ? "on" : ""}" data-chan="+" type="button">+ Add a channel</button></div>`;
    if (rv.ch === "+") {
      h += `<input class="pub-in" id="ch-name" placeholder="Channel name" maxlength="60" autocomplete="off">
        <textarea class="pub-in" id="ch-about" rows="2" placeholder="What is it about, who is it for, how should it sound? (the agents follow this)"></textarea>
        <input class="pub-in" id="ch-drive" placeholder="Google Drive folder for raw footage, e.g. G:\\My Drive\\New channel raw" autocomplete="off">
        <div class="acc-row"><button class="btn primary" data-chan-save="add" type="button">${busy("ch-add")}Add channel</button></div>`;
    } else if (cur) {
      h += `${cur.main ? `<input class="pub-in" id="ch-main-name" placeholder="Name of your main channel" maxlength="60" value="${esc(cur.name || "")}" autocomplete="off">` : ""}
        <div class="pub-h">Raw footage folder <span>${cur.drive ? (cur.drive_ok ? "watching: new videos show up as New footage" : "this computer can't find that folder right now") : "not set"}</span></div>
        <input class="pub-in" id="ch-drive" placeholder="G:\\My Drive\\${esc(name(cur))} raw" value="${esc(cur.drive || "")}" autocomplete="off">
        <div class="acc-row"><button class="btn primary" data-chan-save="update" type="button">${busy("ch-update")}Save</button>${cur.drive ? `<button class="btn" data-chan-save="scan" type="button">${busy("ch-scan")}Check now</button>` : ""}</div>
        <details class="acc-help"><summary>How to use Google Drive for raw footage</summary><ol>
          <li>On this computer install <b>Google Drive for desktop</b> (google.com/drive/download) and sign in with the Google account that has the footage.</li>
          <li>In Google Drive make a folder for this channel's raw videos, for example <b>${esc(name(cur))} raw</b>.</li>
          <li>Open File Explorer → <b>Google Drive (G:)</b> → My Drive → that folder. Click the address bar, copy the path, paste it above and press Save.</li>
          <li>Drop videos into that folder from your phone or any computer. About a minute after Drive has synced one, it shows up on the board as <b>New footage</b>. Press <b>Edit</b> on it when you want it edited.</li>
          <li>Agents HQ copies the video. It never moves or deletes anything in your Drive. Keep this computer on with Agents HQ running.</li></ol></details>`;
    }
    return h + "</div>";
  }
  async function accountAction(kind) {
    const v = (id) => { const x = $("#" + id); return x ? x.value.trim() : ""; };
    let body;
    if (kind === "meta") body = { action: "meta", app_id: v("acc-app-id"), app_secret: v("acc-app-secret"), token: v("acc-token"), page: v("acc-page") };
    else if (kind === "youtube") body = { action: "youtube", client_json: v("acc-yt-json") };
    else body = { action: "disconnect", which: kind.replace(/^off-/, "") };
    body.channel = rv.ch;
    rv.accBusy = kind; renderReview();
    try {
      const r = await postJSON("/api/accounts", body);
      if (r.url) {
        window.open(r.url, "_blank");
        toast("social", "YouTube", "Sign in with Google in the browser window, then come back here.");
        let n = 0; const t = setInterval(async () => { n++; await loadAccounts(); if ((rv.acc && rv.acc.youtube && rv.acc.youtube.connected) || n > 100 || !rv.open) clearInterval(t); }, 3000);
      } else {
        if (r.accounts) rv.acc = r.accounts;
        if (kind === "meta") toast("social", "Connected", `Facebook Page ${r.page || ""}${r.instagram ? " and Instagram @" + r.instagram : " (no Instagram linked)"}` +
          (r.missing && r.missing.length ? `. Missing permission: ${r.missing.join(", ")}. Get the token again with these ticked, or posting will fail.` : ""));
      }
    } catch (e) { toast("social", "Accounts", e.message || "could not connect", { bad: true }); }
    rv.accBusy = ""; if (rv.open) renderReview();
  }
  function accountsCard() {
    const a = rv.acc || {}, fb = a.facebook || {}, ig = a.instagram || {}, yt = a.youtube || {}, busy = (k) => (rv.accBusy === k ? '<span class="spin"></span> ' : "");
    const line = (ok, name, label) => `<div class="acc-line ${ok ? "ok" : ""}">${ok ? svg("check") : "○"} <b>${label}</b> ${ok ? esc(name || "connected") : "not connected"}</div>`;
    return `<div class="rv-card">
      <div class="rv-head"><button class="rv-back" data-rv-close type="button" aria-label="Back to the office">${svg("close")}<span>Back</span></button>
        <div class="rv-title"><div class="t">Channels &amp; accounts</div><div class="s"><span>Connect once. Agents never post: only your Approve &amp; post button does.</span></div></div></div>
      <div class="rv-body">
      ${channelsSec()}
      ${rv.ch === "+" ? "" : `${a.error ? `<div class="rv-empty">${esc(a.error)}</div>` : !rv.acc ? '<div class="rv-empty"><span class="spin"></span> Loading…</div>' : ""}
      <div class="rv-sec acc"><div class="rv-h">Facebook + Instagram</div>
        ${line(fb.connected, fb.name, "Facebook Page")}${line(ig.connected, ig.name, "Instagram")}${ig.problem ? `<div class="pub-warn">${esc(ig.problem)}: in the Instagram app switch to a Professional account and link it to your Facebook Page, then connect again.</div>` : ""}
        <input class="pub-in" id="acc-app-id" placeholder="App ID${rv.ch ? " (leave empty to use the same Meta app)" : ""}" autocomplete="off">
        <input class="pub-in" id="acc-app-secret" type="password" placeholder="App secret${rv.ch ? " (leave empty to use the same Meta app)" : ""}" autocomplete="off">
        <textarea class="pub-in" id="acc-token" rows="2" placeholder="User access token from the Graph API Explorer"></textarea>
        <input class="pub-in" id="acc-page" placeholder="Page name (only if you manage several Pages)" autocomplete="off">
        <div class="acc-row"><button class="btn primary" data-acc="meta" type="button">${busy("meta")}Connect Facebook + Instagram</button>${fb.connected ? '<button class="btn" data-acc="off-meta" type="button">Disconnect</button>' : ""}</div>
        <details class="acc-help"><summary>How to get these (about 10 minutes, once)</summary><ol>
          <li>Instagram must be a <b>Professional</b> account (Business or Creator) <b>linked to your Facebook Page</b>.</li>
          <li>Open <b>developers.facebook.com</b> → My Apps → <b>Create app</b>. Pick the use cases for managing a Page and publishing to Instagram (Facebook Login for Business).</li>
          <li>App settings → Basic: copy the <b>App ID</b> and <b>App secret</b>.</li>
          <li>Tools → <b>Graph API Explorer</b>: choose your app, <b>Get User Access Token</b>, tick <code>pages_show_list</code>, <code>pages_read_engagement</code>, <code>pages_manage_posts</code>, <code>instagram_basic</code>, <code>instagram_content_publish</code>, <code>business_management</code> (and <code>publish_video</code> if it is listed). Generate, allow your Page and Instagram, copy the token.</li>
          <li>Paste all three here and press Connect. Agents HQ swaps the token for one that keeps working, so you do this once. You are the app's admin, so it works for your own Page without Meta's app review.</li></ol></details>
      </div>
      <div class="rv-sec acc"><div class="rv-h">YouTube Shorts</div>
        ${line(yt.connected, yt.name, "YouTube channel")}
        <textarea class="pub-in" id="acc-yt-json" rows="3" placeholder="${yt.client || rv.ch ? "Leave empty to use the Google client you already set up" : "Paste everything from your client_secret_….json file"}"></textarea>
        <div class="acc-row"><button class="btn primary" data-acc="youtube" type="button">${busy("youtube")}Connect YouTube</button>${yt.connected ? '<button class="btn" data-acc="off-youtube" type="button">Disconnect</button>' : ""}</div>
        <div class="pub-note">Do this on the computer, not the phone: Google sends you back to this computer after you sign in.</div>
        <details class="acc-help"><summary>How to get the file (about 10 minutes, once)</summary><ol>
          <li>Open <b>console.cloud.google.com</b> and create a project called Agents HQ.</li>
          <li>APIs &amp; Services → Library → enable <b>YouTube Data API v3</b>.</li>
          <li>OAuth consent screen: External, add your Google account as a test user, then <b>Publish app</b> (otherwise the sign-in stops working after 7 days).</li>
          <li>Credentials → Create credentials → OAuth client ID → <b>Desktop app</b> → Download JSON. Open it in Notepad, copy everything, paste it here.</li>
          <li>Press Connect YouTube, sign in and allow. Google says it hasn't verified the app: press Advanced → Go to Agents HQ (it is your own app).</li>
          <li><b>Good to know:</b> Google keeps videos uploaded by a new project <b>private</b> until the project passes its free YouTube API audit (a form in the Google Cloud console). Until then, Shorts arrive private and Agents HQ tells you so.</li></ol></details>
      </div>
      <div class="rv-sec acc"><div class="rv-h">TikTok</div><div class="pub-note">Not yet: TikTok only allows private posts from an app until TikTok reviews it. Post TikTok by hand with the TikTok text the Social team writes.</div></div>`}
      </div><div class="rv-actions"><button class="btn" data-rv-close type="button">Done</button></div></div>`;
  }
  function closeReview(fromHistory) {
    if (!rv.open) return;
    rv.open = false; stopPubPoll();
    const host = $("#review");
    if (host) { host.querySelectorAll("video").forEach((v) => { try { v.pause(); } catch (e) { /* gone */ } }); host.hidden = true; host.innerHTML = ""; }
    document.body.classList.remove("review-open");
    callScene("pause", false); phonePause();
    if (rv.pushed && !fromHistory) { rv.pushed = false; try { history.back(); } catch (e) { /* ignore */ } } else rv.pushed = false;
  }
  function parseSrt(text) {
    const cues = [], toSec = (t) => { const m = /(\d+):(\d+):(\d+)[,.](\d+)/.exec(t); return m ? +m[1] * 3600 + +m[2] * 60 + +m[3] + +m[4] / 1000 : 0; };
    for (const block of String(text || "").replace(/\r/g, "").split(/\n\n+/)) {
      const lines = block.trim().split("\n"); const i = lines.findIndex((l) => l.includes("-->"));
      if (i < 0) continue;
      const [a] = lines[i].split("-->"); const words = lines.slice(i + 1).join(" ").replace(/<[^>]+>/g, "").trim();
      if (words) cues.push({ t: toSec(a), text: words });
    }
    return cues;
  }
  function mdHtml(text) {                                   // a small, safe Markdown renderer: headings, lists, tables, bold, code
    const inline = (s) => esc(s).replace(/`([^`]+)`/g, "<code>$1</code>").replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>").replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<i>$2</i>");
    const out = [], lines = String(text || "").replace(/\r/g, "").split("\n");
    for (let i = 0; i < lines.length; i++) {
      const l = lines[i];
      if (/^\s*\|.*\|\s*$/.test(l)) {                       // a table: collect its rows
        const rows = []; while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) { rows.push(lines[i]); i++; } i--;
        const cells = (r) => r.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
        const body = rows.filter((r) => !/^\s*\|[\s:|-]+\|\s*$/.test(r));
        out.push(`<div class="md-table"><table>${body.map((r, k) => `<tr>${cells(r).map((c) => (k === 0 ? `<th>${inline(c)}</th>` : `<td>${inline(c)}</td>`)).join("")}</tr>`).join("")}</table></div>`);
        continue;
      }
      const h = /^(#{1,4})\s+(.*)$/.exec(l);
      if (h) { out.push(`<div class="md-h md-h${h[1].length}">${inline(h[2])}</div>`); continue; }
      const li = /^\s*(?:[-*•]|\d+[.)])\s+(.*)$/.exec(l);
      if (li) { out.push(`<div class="md-li">${inline(li[1])}</div>`); continue; }
      if (!l.trim()) { out.push('<div class="md-gap"></div>'); continue; }
      out.push(`<div class="md-p">${inline(l)}</div>`);
    }
    return out.join("");
  }
  function copyText(text) {                                 // the clipboard API needs https; a phone on Wi-Fi or Tailscale is plain http
    const done = () => toast("chief", "Copied", shortTask(text, 60));
    if (navigator.clipboard && window.isSecureContext) { navigator.clipboard.writeText(text).then(done, () => legacy()); return; }
    legacy();
    function legacy() {
      const ta = el('<textarea readonly style="position:fixed;left:-9999px;top:0"></textarea>'); ta.value = text; document.body.appendChild(ta);
      ta.select(); ta.setSelectionRange(0, text.length);
      let ok = false; try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
      ta.remove(); if (ok) done(); else toast("chief", "Copy", "Press and hold the text to copy it.", { bad: true });
    }
  }
  function postSections(text) {                             // post.md: one copyable block per "## Platform" section
    const parts = String(text || "").replace(/\r/g, "").split(/\n(?=##\s)/);
    return parts.map((p) => { const m = /^##\s+(.*)\n?([\s\S]*)$/.exec(p.trim()); return m ? { title: m[1].trim(), body: m[2].trim() } : { title: "", body: p.replace(/^#\s+.*\n?/, "").trim() }; }).filter((s) => s.body);
  }
  function renderReview() {
    const host = $("#review"); if (!host || !rv.open) return;
    if (rv.accounts) { host.innerHTML = accountsCard(); return; }
    const st = state.status || {}, task = rv.taskId ? (st.tasks || []).find((t) => t.id === rv.taskId) : null;
    const name = rv.folder ? rv.folder.split("/").slice(1).join("/") : "";
    const title = task ? taskTitle(task) : prettyName(name);
    const files = (rv.data && rv.data.files) || [], loading = rv.folder && !rv.data;
    const rank = (f) => (/^(edit|final|reel)\b/i.test(f.name) ? 0 : /clean|nocap|no-captions/i.test(f.name) ? 2 : /^cut/i.test(f.name) ? 3 : 1);
    const vids = files.filter((f) => f.kind === "video").sort((a, b) => rank(a) - rank(b) || a.path.localeCompare(b.path));
    const imgs = files.filter((f) => f.kind === "image").sort((a, b) => (/cover/i.test(b.name) - /cover/i.test(a.name)) || a.path.localeCompare(b.path));
    const byName = (re) => files.find((f) => f.kind === "text" && re.test(f.name) && f.text != null);
    const post = byName(/^post\.md$/i), notes = byName(/^notes\.md$/i), plan = byName(/^plan\.md$/i), srt = byName(/\.srt$/i);
    const shown = new Set([post, notes, plan, srt].filter(Boolean).map((f) => f.path));
    const others = files.filter((f) => !vids.includes(f) && !imgs.includes(f) && !shown.has(f.path));
    const area = rv.folder ? rv.folder.split("/")[0] : "", canApprove = area === "out" || (task && task.status === "review");
    const v = vids[rv.vid] || vids[0], poster = imgs.find((i) => /cover/i.test(i.name)) || imgs[0];
    let html = `<div class="rv-card">
      <div class="rv-head"><button class="rv-back" data-rv-close type="button" aria-label="Back to the office">${svg("close")}<span>Back</span></button>
        <div class="rv-title"><div class="t">${esc(title)}</div><div class="s">${tagPill(task ? task.team : "Creative")}<span>${area === "approved" ? "approved" : task && task.status !== "review" ? esc(task.status) : "waiting for your OK"}${files.length ? ` · ${files.length} file${files.length === 1 ? "" : "s"}` : ""}</span></div></div></div>
      <div class="rv-body">`;
    if (loading) html += '<div class="rv-empty"><span class="spin"></span> Opening…</div>';
    else if (rv.data && rv.data.error) html += `<div class="rv-empty">${esc(rv.data.error)}. The folder may have been approved or moved.</div>`;
    if (v) {
      html += `<div class="rv-sec"><div class="rv-video"><video src="${esc(v.url)}" ${poster ? `poster="${esc(poster.url)}"` : ""} controls playsinline preload="metadata" id="rv-player"></video></div>`;
      if (vids.length > 1) html += `<div class="rv-chips">${vids.map((x, i) => `<button class="rv-chip ${x === v ? "on" : ""}" data-rv-vid="${i}" type="button">${svg("play")}${esc(prettyName(x.path))}</button>`).join("")}</div>`;
      html += "</div>";
    }
    if (imgs.length) html += `<div class="rv-sec"><div class="rv-h">Covers and images <span>${imgs.length}</span></div><div class="rv-imgs">${imgs.map((i) => `<button class="rv-img" data-rv-img="${esc(i.url)}" type="button"><img src="${esc(i.url)}" alt="" loading="lazy"><span>${esc(prettyName(i.path))}</span></button>`).join("")}</div></div>`;
    html += pubSection();
    if (post) {
      // with the posting overview above, only what you post by hand is left here (TikTok, the pinned comment)
      const secs = postSections(post.text).map((x, i) => ({ ...x, i })).filter((x) => !/^plan\b/i.test(x.title) && !(rv.pub && /^(captions?|options?|youtube|instagram|facebook)\b/i.test(x.title)));
      if (secs.length) html += `<div class="rv-sec"><div class="rv-h">${rv.pub ? "Post by hand" : "Post copy"} <button class="rv-copy" data-rv-copy="${esc(post.path)}" data-rv-part="all" type="button">Copy all</button></div>${secs.map((s) => `<div class="rv-post"><div class="rv-post-h"><b>${esc(s.title || "Copy")}</b><button class="rv-copy" data-rv-copy="${esc(post.path)}" data-rv-part="${s.i}" type="button">Copy</button></div><div class="md">${mdHtml(s.body)}</div></div>`).join("")}</div>`;
    }
    if (srt) {
      const cues = parseSrt(srt.text);
      if (cues.length) html += `<div class="rv-sec"><div class="rv-h">Captions <span>${cues.length} lines · tap a line to jump there</span></div><div class="rv-cues">${cues.map((c) => `<button class="rv-cue" data-rv-seek="${c.t.toFixed(2)}" type="button"><span class="ts">${Math.floor(c.t / 60)}:${pad2(Math.floor(c.t % 60))}</span>${esc(c.text)}</button>`).join("")}</div></div>`;
    }
    if (notes) html += `<div class="rv-sec"><div class="rv-h">Notes</div><div class="md">${mdHtml(notes.text)}</div></div>`;
    if (plan) html += `<details class="rv-sec rv-more"><summary class="rv-h">Planning page (企划页)</summary><div class="md">${mdHtml(plan.text)}</div></details>`;
    if (task && task.note && !/^out:\S+$/.test(task.note.trim())) html += `<div class="rv-sec"><div class="rv-h">Note on the task</div><div class="md">${mdHtml(task.note)}</div></div>`;
    if (others.length) html += `<details class="rv-sec rv-more"><summary class="rv-h">Other files <span>${others.length}</span></summary>${others.map((f) => `<div class="rv-file"><span class="nm">${esc(f.path)}</span><span class="sz">${fmtBytes(f.size)}</span>${f.text != null ? `<button class="rv-copy" data-rv-copy="${esc(f.path)}" data-rv-part="raw" type="button">Copy</button>` : ""}<a class="rv-dl" href="${esc(f.url)}" download="${esc(f.name)}">Save</a></div>`).join("")}</details>`;
    if (!loading && !files.length && !task) html += '<div class="rv-empty">Nothing in this folder yet.</div>';
    if (!rv.folder && task) html += `<div class="rv-sec"><div class="rv-h">Details</div><div class="md">${mdHtml([task.subtitle, task.agent ? "By " + task.agent : "", task.date ? "Date: " + task.date + (task.time ? " " + task.time : "") : "", "Created " + timeAgo(task.created)].filter(Boolean).join("\n"))}</div></div>`;
    html += "</div>";
    if (rv.mode === "changes") html += `<form class="rv-changes" id="rv-changes"><textarea id="rv-change-text" rows="3" placeholder="What should change? For example: make the yellow words bigger, cut the first sentence" required></textarea><div class="row"><button class="btn" type="button" data-rv-mode="">Cancel</button><button class="btn blue" type="submit">Send to the team</button></div></form>`;
    else if (rv.mode === "approved") html += `<div class="rv-actions done"><div class="msg">${svg("check")} Approved${rv.pub && rv.pub.busy ? " and posting" : ""}. It's in <b>approved/</b>. Teach the team from this one?</div><button class="btn" data-rv-close type="button">Done</button><button class="btn blue" data-rv-retro type="button">Run a retro</button></div>`;
    else {
      const n = rv.ready === false ? 0 : chosenPub().length, busyPub = rv.pub && rv.pub.busy;   // nothing to post until the final check is ready
      const verb = rv.whenOn ? "schedule" : "post";
      const postBtn = n ? `<button class="btn primary" data-rv-approve="post" type="button">${area === "approved" ? (rv.whenOn ? "Schedule" : "Post now") : `Approve &amp; ${verb}`} (${n})</button>` : "";
      html += `<div class="rv-actions">${canApprove ? `<button class="btn" data-rv-mode="changes" type="button">Ask for changes</button><button class="btn ${n ? "" : "primary"}" data-rv-approve type="button">Approve${n ? " only" : ""}</button>${postBtn}`
        : area === "approved" && rv.pub ? `<button class="btn" data-rv-close type="button">Close</button>${busyPub ? '<button class="btn" disabled type="button"><span class="spin"></span> Posting…</button>' : postBtn}` : `<button class="btn" data-rv-close type="button">Close</button>`}</div>`;
    }
    html += "</div>";
    if (rv.img) html += `<div class="rv-light" data-rv-img=""><img src="${esc(rv.img)}" alt=""><button class="rv-back" data-rv-img="" type="button">${svg("close")}<span>Close</span></button></div>`;
    const keepTime = $("#rv-player") && $("#rv-player").getAttribute("src") === (v && v.url) ? $("#rv-player").currentTime : null;
    const scroll = host.querySelector(".rv-body") ? host.querySelector(".rv-body").scrollTop : 0;
    host.innerHTML = html;
    if (keepTime) { const p = $("#rv-player"); if (p) p.currentTime = keepTime; }
    const b = host.querySelector(".rv-body"); if (b) b.scrollTop = scroll;
    if (rv.mode === "changes") { const t = $("#rv-change-text"); if (t) t.focus(); }
  }
  async function reviewApprove(andPost) {
    if (andPost && (rv.folder || "").startsWith("approved/")) return startPost();
    const st = state.status || {}, task = rv.taskId ? (st.tasks || []).find((t) => t.id === rv.taskId) : null;
    const name = rv.folder && rv.folder.startsWith("out/") ? rv.folder.slice(4) : null;
    try {
      if (task) await postJSON("/api/tasks", { action: "approve", id: task.id });             // also moves out/<name> when the note names it
      else if (name) await postJSON("/api/approve", { name });
      if (task && name && folderOfTask(task) !== rv.folder) { try { await postJSON("/api/approve", { name }); } catch (e) { /* already moved */ } }
      rv.mode = "approved"; if (rv.folder && rv.folder.startsWith("out/")) rv.folder = "approved/" + rv.folder.slice(4);
      try { rv.data = await getJSON(`/api/work?folder=${encodeURIComponent(rv.folder)}`); } catch (e) { /* keep the last */ }
      if (andPost) await startPost();
      renderReview(); refresh();
    } catch (e) { toast("creative", "Approve", e.message || "could not approve", { bad: true }); }
  }
  function reviewChanges(text) {
    const st = state.status || {}, task = rv.taskId ? (st.tasks || []).find((t) => t.id === rv.taskId) : null;
    const what = rv.folder ? rv.folder : `board task ${task ? task.id : ""}`;
    send(`Changes requested by the owner on ${what}${task ? ` (board task ${task.id}: ${task.title})` : ""}: ${text}\nApply them, put the new version back in Waiting for my OK, and save what we learned with /retro.`);
    if (task) taskAction({ action: "move", id: task.id, status: "doing" });
    toast("chief", "Sent to the team", shortTask(text, 70));
    closeReview();
  }
  function reviewClick(e) {                                 // returns true when the click belonged to the review screen
    const b = e.target.closest("[data-rv-accounts], [data-acc], [data-chan], [data-chan-save], [data-pub-pick], [data-pub-cancel], [data-rv-close], [data-rv-vid], [data-rv-img], [data-rv-seek], [data-rv-copy], [data-rv-mode], [data-rv-approve], [data-rv-retro], [data-rv-folder], [data-rv-task]");
    if (!b) return false;
    const d = b.dataset;
    if (d.rvAccounts != null) { openReview({ accounts: true, channel: d.rvAccounts }); return true; }
    if (d.chan != null) { pickChannel(d.chan); return true; }
    if (d.chanSave != null) { channelAction(d.chanSave); return true; }
    if (d.acc) { if (!rv.accBusy) accountAction(d.acc); return true; }
    if (d.pubPick) { pickPub(d.pubPick, d.pubVal); return true; }
    if (d.pubCancel) { cancelScheduled(d.pubCancel); return true; }
    if (d.rvFolder) { openReview({ folder: d.rvFolder, taskId: d.rvTask || null }); return true; }
    if (d.rvTask) { openReview({ taskId: d.rvTask }); return true; }
    if (d.rvClose != null) { closeReview(); return true; }
    if (d.rvVid != null) { rv.vid = +d.rvVid; renderReview(); return true; }
    if (d.rvImg != null) { rv.img = d.rvImg || null; renderReview(); return true; }
    if (d.rvSeek != null) { const p = $("#rv-player"); if (p) { p.currentTime = +d.rvSeek; p.play().catch(() => {}); p.scrollIntoView({ block: "nearest", behavior: "smooth" }); } return true; }
    if (d.rvCopy) {
      const f = ((rv.data && rv.data.files) || []).find((x) => x.path === d.rvCopy); if (!f) return true;
      if (d.rvPart === "all" || d.rvPart === "raw") copyText(d.rvPart === "raw" ? f.text : f.text.replace(/^#{1,4}\s+/gm, "").replace(/\*\*/g, "").trim());
      else { const s = postSections(f.text)[+d.rvPart]; if (s) copyText(s.body.replace(/\*\*/g, "")); }
      return true;
    }
    if (d.rvMode != null) { rv.mode = d.rvMode || null; renderReview(); return true; }
    if (d.rvApprove != null) { reviewApprove(d.rvApprove === "post"); return true; }
    if (d.rvRetro != null) { send(`/retro ${rv.folder || "board task " + rv.taskId} (the owner approved it)`); toast("chief", "Retro started", "The team is writing down what worked."); closeReview(); return true; }
    return false;
  }
  window.addEventListener("popstate", () => { if (rv.open) closeReview(true); });

  // ---------- events ----------
  function wire() {
    document.addEventListener("click", (e) => {
      if (reviewClick(e)) return;                          // the review screen and everything that opens it
      if (rv.open) return;
      const b = e.target.closest("button, [data-open], [data-chip], [data-open-cal], [data-agent], .tab");
      const inMenu = e.target.closest("#user-menu, #ask-any, #notif-list, #bell");
      if (!inMenu) closeMenus();
      if (!e.target.closest(".cal-pop, [data-chip]")) $$(".cal-pop").forEach((n) => n.remove());
      if (isPhone() && $("#hud").classList.contains("ask-open") && !e.target.closest("#ask-any, #ask-open, #agent-card, [data-brief]")) closeAsk();
      if (!b) return;
      const d = b.dataset;
      if (b.id === "tab-lead") { setLead(!($("#lead-log").classList.contains("open") && isPhone())); return; }
      if (b.classList.contains("tab")) {
        const v = d.view;
        if (isPhone()) { const leadWasOpen = $("#lead-log").classList.contains("open"); setLead(false); if (v === "office") { openPanel("office"); if (state.focused && !leadWasOpen) goOverview(); } else openPanel(v); hideAgentCard(); return; }   // bottom tabs: open, never toggle
        if (v === "office") { openPanel("office"); if (state.focused) goOverview(); } else openPanel(state.view === v ? "office" : v); return;
      }
      if (b.id === "ask-open") { openAsk(); return; }
      if (b.id === "ask-close") { closeAsk(); return; }
      if (b.id === "lead-close") return;                   // the lead bar's own handler closes the sheet
      if (d.notifClose != null) { toggleBell(false); return; }
      if (d.teamOpen) { openTeam(d.teamOpen); return; }
      if (d.overview != null) { openPanel("office"); goOverview(); return; }
      if (b.id === "user-btn") { const m = $("#user-dropdown"); const was = m.hidden; closeMenus(); m.hidden = !was; return; }
      if (b.id === "menu-overview") { openPanel("office"); goOverview(); return; }
      if (b.id === "menu-accounts") { openReview({ accounts: true }); return; }
      if (b.id === "menu-lead") { setLead(true); $("#lead-input").focus(); return; }
      if (b.id === "menu-life") { setLife(!state.life); return; }
      if (b.id === "bell") { const was = $("#notif-list").hidden; closeMenus(); toggleBell(was); return; }
      if (b.id === "ask-mic" || d.voice != null) { openVoice(); return; }
      if (b.id === "ask-unpick") { pickAgent(null); focusAsk(); return; }
      if (d.pick != null) { pickAgent(d.pick); $("#ask-menu").hidden = true; focusAsk(); return; }
      if (b.id === "voice-close") { closeVoice(); return; }
      if (b.id === "voice-mic") { const v = state.voice; if (!v) return; if (v.listening) stopListening(); else { const SR = window.SpeechRecognition || window.webkitSpeechRecognition; if (SR) startListening(SR); else typedFallback(); } return; }
      if (b.id === "voice-send") { sendVoice(); return; }
      if (d.close != null) { if (b.closest("#agent-card")) hideAgentCard(); else openPanel("office"); return; }
      if (d.ptab) { state.panelTab = d.ptab; renderTeamPanel(); return; }
      if (d.filter) { state.filter = d.filter; renderBoard(); return; }
      if (d.approve) { const t = ((state.status && state.status.tasks) || []).find((x) => x.id === d.approve); if (t && folderOfTask(t)) { openReview({ taskId: t.id }); return; } taskAction({ action: "approve", id: d.approve }, "Approved. The owner publishes; nothing is posted by the office."); return; }
      if (d.approveOut) { openReview({ folder: "out/" + d.approveOut }); return; }   // look before you approve
      if (d.review) { openReview({ taskId: d.review }); return; }
      if (d.open) { const t = ((state.status && state.status.tasks) || []).find((x) => x.id === d.open); if (t && (t.status === "review" || folderOfTask(t))) { openReview({ taskId: t.id }); return; } state.openDetail = state.openDetail === d.open ? null : d.open; if (state.view === "tasks") renderBoard(); else renderTeamPanel(); return; }
      if (d.move) { const [id, status] = d.move.split(":"); taskAction({ action: "move", id, status }); return; }
      if (d.remove) { taskAction({ action: "remove", id: d.remove }, "Task removed from the board."); return; }
      if (d.editFootage) { taskAction({ action: "edit", id: d.editFootage }, "Editing started: the Creative team is on it. Nothing posts until you approve.").then((r) => { if (r) setLead(true); }); return; }
      if (d.run) { const t = ((state.status && state.status.tasks) || []).find((x) => x.id === d.run); if (t) { send(`/brief ${t.title} (board task ${t.id}${t.team ? ", team " + t.team : ""})`); setLead(true); } return; }
      if (d.board != null) { openPanel("tasks"); return; }
      if (d.cal != null) { openPanel("calendar"); return; }
      if (d.brief != null) { const t = teamByKey(state.panelTeam); pickAgent(t ? (headOf(t) || {}).name : null); focusAsk(); return; }
      if (d.chip || d.openCal) { calPopup(d.chip || d.openCal, b); return; }
      if (d.calNav != null) { const [y, m] = state.calMonth.split("-").map(Number); const dt = d.calNav === "0" ? new Date() : new Date(y, m - 1 + Number(d.calNav), 1); state.calMonth = `${dt.getFullYear()}-${pad2(dt.getMonth() + 1)}`; loadCalendar(); return; }
      if (d.ask != null && b.closest("#agent-card")) { pickAgent(d.ask); focusAsk(); return; }
      if (d.team != null && b.closest("#agent-card")) { openTeam(d.team); return; }
      if (d.agent) { showAgentCard(d.agent); return; }
      if (b.closest(".drop")) { const kind = b.closest(".drop").dataset.kind, pk = $("#picker"); pk.onchange = () => { if (pk.files.length) upload(kind, Array.from(pk.files)); pk.value = ""; }; pk.value = ""; pk.click(); }
    });
    document.addEventListener("click", (e) => { const z = e.target.closest(".drop"); if (z && !e.target.closest("button")) { const pk = $("#picker"); pk.onchange = () => { if (pk.files.length) upload(z.dataset.kind, Array.from(pk.files)); pk.value = ""; }; pk.value = ""; pk.click(); } });
    document.addEventListener("submit", (e) => {
      const f = e.target;
      if (f.id === "rv-changes") { e.preventDefault(); const t = $("#rv-change-text").value.trim(); if (t) reviewChanges(t); return; }
      if (f.id === "ask-any") { e.preventDefault(); submitAsk(); }
      else if (f.id === "lead-form") { e.preventDefault(); const i = $("#lead-input"); if (i.value.trim()) send(i.value.trim()); i.value = ""; }
      else if (f.id === "add-task") { e.preventDefault(); const title = $("#task-title").value.trim(); if (!title) return; state.addTeam = $("#task-team").value; taskAction({ action: "add", title, team: $("#task-team").value }, `Added "${shortTask(title, 40)}" to the board.`); }
      else if (f.id === "teach") { e.preventDefault(); const i = $("#teach-text"); if (i.value.trim()) send("/teach " + i.value.trim()); i.value = ""; setLead(true); }
      else if (f.id === "cal-add") { e.preventDefault(); const title = $("#cal-title").value.trim(); if (!title) return; taskAction({ action: "add", title, team: $("#cal-team").value, kind: "post", date: $("#cal-date").value, time: $("#cal-time").value }, `Scheduled "${shortTask(title, 40)}".`).then(loadCalendar); }
    });
    // drag and drop onto the board's strip
    document.addEventListener("dragover", (e) => { const z = e.target.closest(".drop"); if (z) { e.preventDefault(); z.classList.add("over"); } });
    document.addEventListener("dragleave", (e) => { const z = e.target.closest(".drop"); if (z) z.classList.remove("over"); });
    document.addEventListener("drop", (e) => { const z = e.target.closest(".drop"); if (!z) return; e.preventDefault(); z.classList.remove("over"); if (e.dataTransfer.files.length) upload(z.dataset.kind, Array.from(e.dataTransfer.files)); });
    // ask box
    const ask = $("#ask-input");
    ask.addEventListener("focus", () => { buildAskMenu(); $("#ask-menu").hidden = false; });
    ask.addEventListener("input", () => { if (ask.value.startsWith("@")) { buildAskMenu(); $("#ask-menu").hidden = false; } });
    ask.addEventListener("keydown", (e) => { if (e.key === "Escape") { $("#ask-menu").hidden = true; ask.blur(); } });
    $("#lead-bar").addEventListener("click", () => setLead(!$("#lead-log").classList.contains("open")));
    $("#voice-orb").addEventListener("click", (e) => { if (e.currentTarget.classList.contains("mini")) openVoice(); });
    $("#voice-orb").addEventListener("keydown", (e) => { if ((e.key === "Enter" || e.key === " ") && e.currentTarget.classList.contains("mini")) { e.preventDefault(); openVoice(); } });
    $("#voice-text").addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendVoice(); } });
    $("#brain-label").addEventListener("click", () => openPanel(state.view === "brain" ? "office" : "brain"));
    $("#panel-dim").addEventListener("click", () => openPanel("office"));
    $("#avatar").addEventListener("click", () => { const m = $("#user-dropdown"); const was = m.hidden; closeMenus(); m.hidden = !was; });
    window.addEventListener("keydown", (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); focusAsk(); return; }
      if (e.key === "Escape" && rv.open) { if (rv.img) { rv.img = null; renderReview(); } else closeReview(); return; }
      if (e.key === "Escape") { if (state.voice) closeVoice(); else if ($("#hud").classList.contains("ask-open")) closeAsk(); else if (!$("#ask-menu").hidden || !$("#user-dropdown").hidden || !$("#notif-list").hidden) closeMenus(); else if (!$("#agent-card").hidden) hideAgentCard(); else if (state.view !== "office") openPanel("office"); }
    });
    window.addEventListener("hq-office-ready", onSceneReady);
    window.addEventListener("resize", () => { callScene("resize"); drawMinimap(); });
    const onPhoneChange = () => { if (!isPhone()) { closeAsk(); $("#hud").classList.remove("lead-open"); } else if ($("#lead-log").classList.contains("open")) $("#hud").classList.add("lead-open"); renderTopbar(); phonePause(); };
    if (phoneMQ) { if (phoneMQ.addEventListener) phoneMQ.addEventListener("change", onPhoneChange); else if (phoneMQ.addListener) phoneMQ.addListener(onPhoneChange); }
    wireMinimap();
  }

  // ---------- init ----------
  function init() {
    $("#user-name").textContent = "Owner"; $("#hud").dataset.view = "office";
    $("#ask-kbd").textContent = /Mac|iPhone|iPad/.test(navigator.platform || "") ? "⌘K" : "Ctrl K";
    initLife(); wire();
    refresh().then(pollNotifs); loadBrain();
    setInterval(refresh, 4000);
    setInterval(pollNotifs, 5000);
    setInterval(pollEvents, 2000);
    setInterval(loadBrain, 30000);
    setInterval(tickSkills, 1000);
    setInterval(() => { const was = state.zoom >= 140, z = Number(callScene("getZoomPercent")); if (z) state.zoom = z; const ms = callScene("minimapState"); syncFocus(ms); syncFloors(ms); drawMinimap(ms); if (isPhone() && was !== state.zoom >= 140) renderTeamCards(); }, 250);   // a phone: dock the focused room's card as soon as the camera arrives
    requestAnimationFrame(tick);
    if (window.HQ_OFFICE) onSceneReady();                  // the scene may already be there
    else setTimeout(() => { if (window.HQ_OFFICE) onSceneReady(); }, 3000);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init); else init();
})();
