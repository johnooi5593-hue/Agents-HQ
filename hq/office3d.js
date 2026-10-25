// Agents HQ, the 3D office. The Brain in the middle, one room per team on walkways around it, one desk and one
// character per agent (heads wear a hat). A character's screen lights up and a bubble appears while its agent runs.
// Drag to orbit, right-drag to pan, wheel to zoom, click a character for its card, click a room floor to fly there,
// keys 1-8 jump to a room, 0 is the overview. Built on Three.js (hq/vendor/three.min.js). Reads window.HQ from app.html.
(() => {
  const host = document.getElementById("office3d");
  if (!host || typeof THREE === "undefined") return;
  const TEAM_COLORS = { Research: 0x60a5fa, Inbox: 0xfb923c, Scripts: 0x22d3ee, Dev: 0x4ade80, Shop: 0xffd400, Social: 0xf472b6, Creative: 0xc084fc, Analytics: 0xf87171 };
  const R = 30, ROOM_W = 17, ROOM_D = 13;
  const state = { agents: [], teams: [], rooms: {}, chars: {}, frame: 0, target: new THREE.Vector3(0, 0, 0), goal: null, theta: 0.9, phi: 1.05, dist: 64, selected: null };

  // renderer, scene, camera
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
  renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
  renderer.setClearColor(0x0b0d11);
  host.appendChild(renderer.domElement);
  const scene = new THREE.Scene();
  scene.fog = new THREE.Fog(0x0b0d11, 90, 160);
  const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 400);
  scene.add(new THREE.HemisphereLight(0xaab4ff, 0x1a1d24, 0.9));
  const sun = new THREE.DirectionalLight(0xffffff, 0.7); sun.position.set(30, 60, 20); scene.add(sun);
  const floor = new THREE.Mesh(new THREE.CircleGeometry(70, 64), new THREE.MeshLambertMaterial({ color: 0x12151b }));
  floor.rotation.x = -Math.PI / 2; floor.position.y = -0.3; scene.add(floor);
  const grid = new THREE.GridHelper(140, 70, 0x1c2029, 0x161a21); grid.position.y = -0.29; scene.add(grid);

  const mat = (color, extra = {}) => new THREE.MeshLambertMaterial({ color, ...extra });
  const box = (w, h, d, color, extra) => new THREE.Mesh(new THREE.BoxGeometry(w, h, d), mat(color, extra));

  function label(str, opt = {}) {                         // a text sprite with a dark pill behind it
    const c = document.createElement("canvas"), size = opt.size || 28, pad = 14;
    const g = c.getContext("2d"); g.font = `${opt.bold ? "600 " : ""}${size}px -apple-system, "Segoe UI", Inter, Roboto, sans-serif`;
    const w = Math.ceil(g.measureText(str).width) + pad * 2, h = size + pad; c.width = w; c.height = h;
    g.font = `${opt.bold ? "600 " : ""}${size}px -apple-system, "Segoe UI", Inter, Roboto, sans-serif`;
    g.fillStyle = opt.bg || "rgba(15,17,21,0.85)"; g.beginPath(); g.roundRect ? g.roundRect(0, 0, w, h, h / 2) : g.rect(0, 0, w, h); g.fill();
    g.fillStyle = opt.color || "#e8eaf0"; g.textBaseline = "middle"; g.textAlign = "center"; g.fillText(str, w / 2, h / 2);
    const tex = new THREE.CanvasTexture(c); tex.minFilter = THREE.LinearFilter;
    const sp = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, transparent: true, depthTest: false }));
    const k = opt.scale || 0.055; sp.scale.set(w * k, h * k, 1); sp.renderOrder = 10; return sp;
  }

  // the Brain
  const hub = new THREE.Group();
  hub.add(box(14, 0.4, 14, 0x1a1e27)); const hubRing = new THREE.Mesh(new THREE.TorusGeometry(5.2, 0.12, 8, 48), mat(0xffd400, { emissive: 0xffd400, emissiveIntensity: 0.5 })); hubRing.rotation.x = Math.PI / 2; hubRing.position.y = 1.2; hub.add(hubRing);
  const core = new THREE.Mesh(new THREE.IcosahedronGeometry(2.2, 1), new THREE.MeshLambertMaterial({ color: 0xffd400, emissive: 0xb89a00, emissiveIntensity: 0.6, wireframe: false })); core.position.y = 3.2; hub.add(core);
  const coreWire = new THREE.Mesh(new THREE.IcosahedronGeometry(2.6, 1), new THREE.MeshBasicMaterial({ color: 0xffd400, wireframe: true, transparent: true, opacity: 0.35 })); coreWire.position.y = 3.2; hub.add(coreWire);
  const hubLight = new THREE.PointLight(0xffd400, 1.2, 30); hubLight.position.y = 4; hub.add(hubLight);
  const hubLabel = label("THE BRAIN", { bold: true, color: "#ffd400", scale: 0.05 }); hubLabel.position.y = 8.4; hub.add(hubLabel);
  let rulesLabel = label("…", { size: 22, scale: 0.034, color: "#8b93a7" }); rulesLabel.position.y = 7.0; hub.add(rulesLabel);
  scene.add(hub);

  function character(a, color) {                           // a small blocky person, head wears a hat
    const g = new THREE.Group();
    const body = box(0.9, 1.1, 0.6, color); body.position.y = 0.85; g.add(body);
    const head = box(0.7, 0.7, 0.7, 0xf1c9a5); head.position.y = 1.85; g.add(head);
    const hair = box(0.74, 0.22, 0.74, 0x2b2b2b); hair.position.y = 2.17; g.add(hair);
    if (a.role === "head") { const hat = new THREE.Mesh(new THREE.ConeGeometry(0.5, 0.7, 4), mat(0xffd400)); hat.position.y = 2.6; hat.rotation.y = Math.PI / 4; g.add(hat); }
    const name = label(a.name, { size: 22, scale: 0.034 }); name.position.y = 3.0; g.add(name);
    g.userData = { agent: a, body, head, name }; return g;
  }

  function desk(a, color, x, z, parent) {
    const d = new THREE.Group(); d.position.set(x, 0, z);
    const top = box(3, 0.2, 1.4, 0x6b4a2b); top.position.y = 1.1; d.add(top);
    for (const [lx, lz] of [[-1.3, -0.5], [1.3, -0.5], [-1.3, 0.5], [1.3, 0.5]]) { const leg = box(0.12, 1.1, 0.12, 0x4a331d); leg.position.set(lx, 0.55, lz); d.add(leg); }
    const screen = box(1.2, 0.8, 0.08, 0x111317, { emissive: 0x000000 }); screen.position.set(0, 1.7, -0.3); d.add(screen);
    const stand = box(0.1, 0.3, 0.1, 0x2a2f3a); stand.position.set(0, 1.3, -0.3); d.add(stand);
    const chair = box(0.9, 0.2, 0.9, 0x3a4150); chair.position.set(0, 0.7, 1.2); d.add(chair);
    const c = character(a, color); c.position.set(0, 0, 1.2); c.rotation.y = Math.PI; d.add(c);
    const lamp = new THREE.PointLight(0x67e8f9, 0, 7); lamp.position.set(0, 2.2, 0); d.add(lamp);
    const bubble = label("working…", { size: 22, scale: 0.04, bg: "#ffffff", color: "#111317" }); bubble.position.set(0, 4.3, 1.2); bubble.visible = false; d.add(bubble);
    parent.add(d);
    state.chars[a.name] = { group: d, char: c, screen, lamp, bubble, agent: a, lastText: "" };
    return d;
  }

  function build(data) {
    state.agents = data.agents; state.teams = data.teams;
    const n = state.teams.length;
    state.teams.forEach((team, i) => {
      const th = (i / n) * Math.PI * 2 - Math.PI / 2, cx = R * Math.cos(th), cz = R * Math.sin(th);
      const color = TEAM_COLORS[team] || 0x8b93a7;
      const room = new THREE.Group(); room.position.set(cx, 0, cz); room.rotation.y = Math.atan2(-Math.cos(th), -Math.sin(th));
      const slab = box(ROOM_W, 0.4, ROOM_D, 0x171a21); slab.userData = { room: team }; room.add(slab);
      const trim = box(ROOM_W + 0.4, 0.1, ROOM_D + 0.4, color); trim.position.y = -0.2; room.add(trim);
      const back = box(ROOM_W, 3, 0.3, 0x222733); back.position.set(0, 1.5, -ROOM_D / 2); room.add(back);
      const stripe = box(ROOM_W, 0.3, 0.32, color); stripe.position.set(0, 2.8, -ROOM_D / 2); room.add(stripe);
      for (const sx of [-1, 1]) { const side = box(0.3, 3, ROOM_D * 0.55, 0x222733); side.position.set(sx * ROOM_W / 2, 1.5, -ROOM_D * 0.22); room.add(side); }
      const sign = label(team.toUpperCase(), { bold: true, size: 30, scale: 0.05, color: "#" + color.toString(16).padStart(6, "0") }); sign.position.set(0, 5.4, -ROOM_D / 2); room.add(sign);
      const members = state.agents.filter((a) => a.team === team), head = members.find((a) => a.role === "head"), workers = members.filter((a) => a !== head);
      if (head) desk(head, color, 0, -3.6, room);
      workers.forEach((w, j) => desk(w, color, (j - (workers.length - 1) / 2) * 4, 1.6, room));
      const walk = box(3.2, 0.2, R - ROOM_D / 2 - 8, 0x1d2129); walk.position.set(Math.cos(th) * (R - ROOM_D / 2 + 8) / 2, -0.2, Math.sin(th) * (R - ROOM_D / 2 + 8) / 2); walk.rotation.y = room.rotation.y; scene.add(walk);
      scene.add(room);
      state.rooms[team] = { group: room, center: new THREE.Vector3(cx, 0, cz), color, index: i };
    });
    // the chief of staff at the Brain
    const lead = { name: "chief of staff", team: "The Brain", role: "lead", model: "you", description: "Routes work, starts agents in parallel, reviews, reports.", tools: [], skills: [] };
    desk(lead, 0xe8eaf0, 0, 5.6, hub);
    renderCounter();
  }

  // camera control: orbit around a target
  function placeCamera() {
    const t = state.target;
    camera.position.set(t.x + state.dist * Math.sin(state.phi) * Math.cos(state.theta), t.y + state.dist * Math.cos(state.phi), t.z + state.dist * Math.sin(state.phi) * Math.sin(state.theta));
    camera.lookAt(t);
  }
  let drag = null;
  const el = renderer.domElement;
  el.addEventListener("contextmenu", (e) => e.preventDefault());
  el.addEventListener("pointerdown", (e) => { drag = { x: e.clientX, y: e.clientY, button: e.button, moved: false }; el.setPointerCapture(e.pointerId); });
  el.addEventListener("pointermove", (e) => {
    if (!drag) return;
    const dx = e.clientX - drag.x, dy = e.clientY - drag.y; drag.x = e.clientX; drag.y = e.clientY;
    if (Math.abs(dx) + Math.abs(dy) > 2) drag.moved = true;
    if (drag.button === 2 || e.shiftKey) {                   // pan
      const right = new THREE.Vector3().crossVectors(camera.getWorldDirection(new THREE.Vector3()), camera.up).normalize();
      const fwd = new THREE.Vector3(-Math.cos(state.theta), 0, -Math.sin(state.theta));
      state.target.addScaledVector(right, -dx * state.dist * 0.0015).addScaledVector(fwd, -dy * state.dist * 0.0015); state.goal = null;
    } else { state.theta += dx * 0.006; state.phi = Math.max(0.25, Math.min(1.45, state.phi + dy * 0.004)); }
  });
  el.addEventListener("pointerup", (e) => { if (drag && !drag.moved && e.button === 0) pick(e); drag = null; });
  el.addEventListener("wheel", (e) => { e.preventDefault(); state.dist = Math.max(10, Math.min(140, state.dist * (1 + Math.sign(e.deltaY) * 0.08))); }, { passive: false });
  window.addEventListener("keydown", (e) => {
    if (!host.closest(".view.active") || e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA") return;
    if (e.key === "0" || e.key.toLowerCase() === "o") flyTo(new THREE.Vector3(0, 0, 0), 64);
    const i = parseInt(e.key, 10); if (i >= 1 && i <= state.teams.length) flyTo(state.rooms[state.teams[i - 1]].center, 26);
  });
  function flyTo(v, dist) { state.goal = { target: v.clone(), dist: dist || state.dist }; }
  const ray = new THREE.Raycaster();
  function pick(e) {
    const r = el.getBoundingClientRect(), m = new THREE.Vector2(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
    ray.setFromCamera(m, camera);
    const hits = ray.intersectObjects(scene.children, true);
    for (const h of hits) {
      let o = h.object;
      while (o) { if (o.userData && o.userData.agent) return select(o.userData.agent); if (o.userData && o.userData.room) return flyTo(state.rooms[o.userData.room].center, 26); o = o.parent; }
    }
    select(null);
  }
  function select(agent) {
    state.selected = agent && agent.name;
    const card = document.getElementById("agent-card");
    if (!card) return;
    if (!agent) { card.hidden = true; return; }
    const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
    const running = runningMap()[agent.name];
    card.innerHTML = `<div class="agent-card-head"><strong>${esc(agent.name)}</strong><span class="tag ${running ? "ok" : ""}">${running ? "working" : "idle"}</span><button class="small" id="agent-card-close">×</button></div>
      <div class="agent-card-meta">${esc(agent.team)} · ${agent.role === "head" ? "team head" : agent.role === "lead" ? "the lead" : "worker"} · ${esc(agent.model || "")}</div>
      <p>${esc(agent.description)}</p>${running && typeof running === "string" ? `<p class="agent-card-task">Now: ${esc(running)}</p>` : ""}
      ${agent.skills && agent.skills.length ? `<div class="agent-card-row">Skills: ${agent.skills.map(esc).join(", ")}</div>` : ""}
      ${agent.tools && agent.tools.length ? `<div class="agent-card-row">Tools: ${agent.tools.map(esc).join(", ")}</div>` : ""}`;
    card.hidden = false;
    document.getElementById("agent-card-close").onclick = () => select(null);
  }

  // what is running: the app's own stream (task text) merged with the hook feed (counts)
  function runningMap() {
    const hq = window.HQ || {}, out = {};
    const st = hq.status ? hq.status() : null;
    if (st && st.running) for (const [k, v] of Object.entries(st.running)) if (v > 0) out[k] = true;
    if (hq.working) for (const [k, v] of Object.entries(hq.working)) out[k] = v || true;
    if (st && st.desk && st.desk.busy) out["chief of staff"] = "working";
    return out;
  }
  function renderCounter() {
    const el = document.getElementById("office-counter"); if (!el) return;
    const n = Object.keys(runningMap()).filter((k) => k !== "chief of staff").length;
    el.textContent = `${state.agents.length} agents · ${n} running`;
    el.className = "office-counter" + (n ? " live" : "");
  }

  // minimap
  const mini = document.getElementById("minimap");
  function drawMini() {
    if (!mini) return;
    const g = mini.getContext("2d"), w = mini.width, h = mini.height, k = w / 150;
    g.clearRect(0, 0, w, h); g.fillStyle = "rgba(15,17,21,0.9)"; g.fillRect(0, 0, w, h);
    const run = runningMap();
    const P = (v) => [w / 2 + v.x * k, h / 2 + v.z * k];
    for (const [team, r] of Object.entries(state.rooms)) {
      const [x, y] = P(r.center); g.fillStyle = "#" + r.color.toString(16).padStart(6, "0"); g.globalAlpha = 0.35; g.fillRect(x - 8, y - 6, 16, 12); g.globalAlpha = 1;
      const lit = state.agents.some((a) => a.team === team && run[a.name]); if (lit) { g.fillStyle = "#4ade80"; g.beginPath(); g.arc(x, y, 2.5, 0, 7); g.fill(); }
    }
    g.fillStyle = "#ffd400"; g.beginPath(); g.arc(w / 2, h / 2, 3, 0, 7); g.fill();
    const [cx, cy] = P(camera.position); g.strokeStyle = "#e8eaf0"; g.beginPath(); g.arc(cx, cy, 3, 0, 7); g.stroke();
    const [tx, ty] = P(state.target); g.strokeStyle = "#8b93a7"; g.strokeRect(tx - 4, ty - 4, 8, 8);
  }
  if (mini) mini.addEventListener("click", (e) => { const r = mini.getBoundingClientRect(), k = mini.width / 150; flyTo(new THREE.Vector3((e.clientX - r.left) * (mini.width / r.width) / k - 75, 0, (e.clientY - r.top) * (mini.height / r.height) / k - 75), 30); });

  function resize() {
    const w = host.clientWidth || 800, h = Math.max(320, Math.min(640, Math.round(w * 0.56)));
    renderer.setSize(w, h); camera.aspect = w / h; camera.updateProjectionMatrix();
  }
  window.addEventListener("resize", resize);

  function animate() {
    requestAnimationFrame(animate);
    if (!host.closest(".view.active")) return;                // draw only while the Office tab is open
    state.frame++;
    if (state.goal) { state.target.lerp(state.goal.target, 0.08); state.dist += (state.goal.dist - state.dist) * 0.08; if (state.target.distanceTo(state.goal.target) < 0.05) state.goal = null; }
    placeCamera();
    core.rotation.y += 0.01; coreWire.rotation.y -= 0.006; hubRing.rotation.z += 0.004;
    hubLight.intensity = 1 + Math.sin(state.frame * 0.05) * 0.3;
    const run = runningMap();
    for (const [name, c] of Object.entries(state.chars)) {
      const on = !!run[name], t = state.frame * 0.15;
      c.screen.material.emissive.setHex(on ? (Math.sin(t) > 0 ? 0x22d3ee : 0x0e7490) : 0x000000);
      c.lamp.intensity = on ? 0.8 + Math.sin(t) * 0.3 : 0;
      c.char.position.y = on ? Math.abs(Math.sin(t)) * 0.15 : 0;
      c.char.userData.head.rotation.y = on ? Math.sin(t * 0.5) * 0.3 : Math.sin(state.frame * 0.01 + name.length) * 0.1;
      const text = typeof run[name] === "string" ? run[name] : on ? "working…" : "";
      if (on && text !== c.lastText) { c.group.remove(c.bubble); c.bubble = label(text.length > 34 ? text.slice(0, 33) + "…" : text, { size: 22, scale: 0.04, bg: "#ffffff", color: "#111317" }); c.bubble.position.set(0, 4.3, 1.2); c.group.add(c.bubble); c.lastText = text; }
      c.bubble.visible = on;
      c.char.userData.name.visible = state.dist < 50 || on || state.selected === name;   // names only up close, or while working
    }
    const st = window.HQ && window.HQ.status ? window.HQ.status() : null;
    if (st && state.frame % 30 === 0) { const rules = (st.brain && st.brain["Brand rules"]) || 0; const txt = `${rules} rules · ${st.brain && st.brain["Lessons"] || 0} lessons`; if (rulesLabel.userData.txt !== txt) { hub.remove(rulesLabel); const nl = label(txt, { size: 22, scale: 0.034, color: "#8b93a7" }); nl.position.y = 7.0; nl.userData.txt = txt; hub.add(nl); rulesLabel = nl; } }
    if (state.frame % 15 === 0) { renderCounter(); drawMini(); }
    renderer.render(scene, camera);
  }

  fetch("/api/agents").then((r) => r.json()).then((data) => { build(data); resize(); placeCamera(); animate(); }).catch((e) => { host.textContent = "The office could not load: " + e; });
  window.HQ_OFFICE = { flyTo: (team) => state.rooms[team] && flyTo(state.rooms[team].center, 26), overview: () => flyTo(new THREE.Vector3(0, 0, 0), 64), select: (name) => select(state.agents.find((a) => a.name === name) || null), resize };
})();
