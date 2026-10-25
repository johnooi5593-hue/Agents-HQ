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
      renderAll();
    } catch (e) { /* offline or logging in: keep the last state */ }
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
  function wireMinimap() {
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
  function phonePause() { const cover = isPhone() && (state.view !== "office" || $("#lead-log").classList.contains("open") || $("#hud").classList.contains("ask-open") || !$("#notif-list").hidden || !!state.voice); callScene("pause", cover); }
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
  function taskRow(t) {                                    // one board row; the section decides glyph and control
    let glyph, meta, act, cls = "";
    if (t.status === "doing") { glyph = t.progress != null ? ring(t.progress) : '<span class="spin"></span>'; meta = t.subtitle || t.agent || "running"; act = t.progress != null ? "" : '<span class="chev">›</span>'; if (t.progress != null) { act = glyph; glyph = '<span class="spin"></span>'; } }
    else if (t.status === "review") { glyph = '<span class="warn">!</span>'; meta = t.subtitle || "needs your approval"; act = ["approval", "post"].includes(t.kind) ? `<button class="btn primary sm" data-approve="${esc(t.id)}">Approve</button>` : `<button class="btn sm" data-review="${esc(t.id)}">Review</button>`; cls = t.kind === "post" ? "hot" : ""; }
    else if (t.status === "done") { glyph = `<span class="done-g">${svg("check")}</span>`; meta = t.subtitle || timeAgo(t.done_at || t.updated); act = '<span class="chev">›</span>'; }
    else { glyph = '<span class="todo-g"></span>'; meta = t.subtitle || (t.date ? `${relDay(t.date)}${t.time ? " " + t.time : ""}` : "not started"); act = `<button class="btn sm blue" data-run="${esc(t.id)}">Run</button>`; }
    const title = t.date && t.status !== "done" && !/\d{1,2}:\d{2}/.test(t.title) && t.time ? `${t.title} · ${relDay(t.date)} ${fmtTime(t.time)}` : t.title;
    return `<div class="trow ${cls}" data-task="${esc(t.id)}"><span class="g">${glyph}</span><div class="tt ia" data-open="${esc(t.id)}"><div class="title">${esc(title)}</div><div class="meta">${tagPill(t.team)}<span>${esc(meta)}</span></div></div><div class="act">${act}</div></div>${state.openDetail === t.id ? taskDetail(t) : ""}`;
  }
  function taskDetail(t) {
    const files = [], m = /out:([^\s,;]+)/.exec(t.note || ""), st = state.status || {};
    if (m && st.out && st.out[m[1]]) for (const f of st.out[m[1]].files || []) files.push(`<a href="/files/out/${encodeURIComponent(m[1])}/${encodeURIComponent(f)}" target="_blank" rel="noopener">${esc(f)}</a>`);
    const moves = ["todo", "doing", "review", "done"].filter((s) => s !== t.status).map((s) => `<button class="btn sm" data-move="${esc(t.id)}:${s}">${({ todo: "To do", doing: "Running", review: "Waiting", done: "Done" })[s]}</button>`).join("");
    return `<div class="task-detail"><div><b>${esc(t.title)}</b> <span class="hint">· ${esc(t.kind)}${t.agent ? " · " + esc(t.agent) : ""}${t.date ? " · " + esc(t.date) + (t.time ? " " + esc(t.time) : "") : ""} · created ${esc(timeAgo(t.created))}</span></div>${t.note ? `<div class="nt">${esc(t.note)}</div>` : '<div class="hint" style="margin-top:4px">No note on this task.</div>'}${files.length ? `<div>${files.join("")}</div>` : ""}<div class="row">${moves}<button class="btn sm" data-remove="${esc(t.id)}" style="margin-left:auto">Remove</button></div></div>`;
  }
  const teamTasks = (t) => ((state.status && state.status.tasks) || []).filter((x) => t && (x.team === t.name || String(x.team).toLowerCase() === t.key));

  // ---------- the team panel ----------
  const TOOL_STYLE = { "google drive": ["#1ca16b", "▲"], capcut: ["#222933", "C"], canva: ["linear-gradient(135deg,#46a5be,#6d5df5)", "C"], slack: ["#612656", "#"], github: ["#24292f", "G"], notion: ["#2b2b2b", "N"], gmail: ["#d93025", "M"], calendar: ["#1a73e8", "C"], instagram: ["linear-gradient(135deg,#f58529,#dd2a7b,#8134af)", "I"], youtube: ["#ff0033", "▶"], "youtube analytics": ["#ff0033", "Y"], sheets: ["#188038", "S"], shopify: ["#5e8e3e", "S"], stripe: ["#635bff", "S"], ci: ["#2088ff", "CI"], "web search": ["#2563eb", "W"], "rough cut": ["#5b5fd6", "✂"], captions: ["#5b5fd6", "cc"], thumbnails: ["#5b5fd6", "▣"] };
  function toolTile(tool) {
    const [bg, glyph] = TOOL_STYLE[String(tool.name).toLowerCase()] || [hashColor(tool.name), String(tool.name)[0].toUpperCase()];
    const on = tool.status === "connected";
    return `<div class="tool" title="${esc(tool.name)}"><span class="ic" style="background:${bg}">${esc(glyph)}</span><div style="min-width:0"><div class="nm">${esc(tool.name)}</div><div class="st ${on ? "" : "off"}"><i class="dot"></i>${on ? `Connected · ${esc(tool.via || "MCP")}` : "Not connected"}</div></div></div>`;
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
    const approvalRow = ({ name, info }) => `<div class="trow approval hot" data-out="${esc(name)}"><span class="g">${info.cover ? `<img class="thumb" src="/files/out/${encodeURIComponent(name)}/cover.jpg" alt="">` : `<span class="thumb" style="display:grid;place-items:center;color:#9aa3b2">${svg("play")}</span>`}</span><div class="tt"><div class="title">${esc(name.replace(/[-_]+/g, " "))}</div><div class="meta">${tagPill("Creative")}<span>${info.edit ? "edit ready" : `${(info.files || []).length} file${(info.files || []).length === 1 ? "" : "s"}`} · needs your approval</span>${info.edit ? `<a class="mono" href="/files/out/${encodeURIComponent(name)}/edit.mp4" target="_blank" rel="noopener" style="color:#9fb6ff">▶ watch</a>` : ""}</div></div><div class="act"><button class="btn primary sm" data-approve-out="${esc(name)}">Approve</button></div></div>`;
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
  function attach(id, quiet) { state.run.id = id; state.run.offset = 0; state.run.quiet = !!quiet; state.run.seen.add(id); $("#lead-log").classList.add("busy"); poll(); }
  async function poll() {
    if (!state.run.id) return;
    try {
      const r = await getJSON(`/api/runs/${state.run.id}?after=${state.run.offset}`);
      if (state.run.offset === 0 && r.prompt) { log("you", "you: " + r.prompt); $("#lead-text").textContent = "Lead · working: " + shortTask(r.prompt, 60); }
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

  // ---------- events ----------
  function wire() {
    document.addEventListener("click", (e) => {
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
      if (d.approve) { taskAction({ action: "approve", id: d.approve }, "Approved. The owner publishes; nothing is posted by the office."); return; }
      if (d.approveOut) { approveOut(d.approveOut); return; }
      if (d.review || d.open) { const id = d.review || d.open; state.openDetail = state.openDetail === id ? null : id; if (state.view === "tasks") renderBoard(); else renderTeamPanel(); return; }
      if (d.move) { const [id, status] = d.move.split(":"); taskAction({ action: "move", id, status }); return; }
      if (d.remove) { taskAction({ action: "remove", id: d.remove }, "Task removed from the board."); return; }
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
    setInterval(() => { const was = state.zoom >= 140, z = Number(callScene("getZoomPercent")); if (z) state.zoom = z; const ms = callScene("minimapState"); syncFocus(ms); drawMinimap(ms); if (isPhone() && was !== state.zoom >= 140) renderTeamCards(); }, 250);   // a phone: dock the focused room's card as soon as the camera arrives
    requestAnimationFrame(tick);
    if (window.HQ_OFFICE) onSceneReady();                  // the scene may already be there
    else setTimeout(() => { if (window.HQ_OFFICE) onSceneReady(); }, 3000);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init); else init();
})();
