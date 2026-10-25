// Agents HQ: the 3D office (hq/office3d.js). Built on Three.js r128 (hq/vendor/three.min.js) and the vendored UMD
// examples (EffectComposer, UnrealBloomPass, RoundedBoxGeometry, CSS2DRenderer, OrbitControls).
//
// The look follows docs/video-spec.md: the Brain in the middle (round platform, neon rings, light beam, orbit rings,
// particles), eight square team rooms around it (floor, carpet, two back walls, trims, desks, monitors, dashboards,
// lamps, shelves, plants, sofas), dark walkways with dashed centre lines, data wires with travelling sparks, chibi
// characters at their desks, walkers on the walkways, ghost sub-agents, and bloom on everything that glows.
// The interface follows docs/build-contract.md: window.HQ_OFFICE (flyTo, overview, select, focusAgent, project,
// setLabel, spawnSubagents, clearSubagents, zoom, setZoomPercent, getZoomPercent, fullscreen, resize, minimapState,
// onRoomClick / onAgentClick / onBrainClick), plus focusBrain(), bloom(strength, threshold, radius) and an optional
// options object on flyTo / overview / focusAgent / focusBrain: { shiftX: 0.17 } moves the framed point right by that
// fraction of the viewport (room beside an open left panel), { duration, zoom } tune the move. No text is drawn in the
// scene for names: the HUD fills the CSS2D label elements through setLabel(kind, key, html) or positions its own
// elements from project(kind, key). The running state comes from window.HQ.running() every frame.
(() => {
  'use strict';
  const host = document.getElementById('office3d');
  if (!host || typeof THREE === 'undefined') return;

  // ------------------------------------------------------------------ constants
  const S = 20;                                  // room side in world units
  const WALL_H = 9.4, WALL_T = 0.45, SLAB_H = 0.7;
  const RING_R = 44;                             // distance from the Brain to a room centre
  const PLATFORM_R = 17;                         // the Brain platform
  const GROUND_Y = -6.5;                         // the void floor under the floating slabs
  const WALK_W = 4.2, WALK_Y = 0.45;             // walkway width and top height
  const CORE_Y = 9.5;                            // the Brain sphere height
  const SQ = Math.SQRT1_2;
  const DEG = Math.PI / 180;
  const OVERVIEW = { yaw: 45 * DEG, pitch: 40 * DEG, dist: 170, target: new THREE.Vector3(0, 1.5, 0) };
  const ROOM_VIEW = { pitch: 37 * DEG, dist: 68 };
  const CHAR_SCALE = 1.22;                       // characters are ~1.6 desk-heights tall in the video

  // Fallback metadata (the contract's table) used only if /api/teams cannot be read.
  const FALLBACK_TEAMS = [
    { key: 'research', name: 'Research', color: '#5d88cf', color_light: '#c6d5ee', color_wall: '#334b72', accent: '#3858bd', tagline: 'github radar · markets · trends', lead: 'research-director' },
    { key: 'scripts', name: 'Scripts', color: '#d8b055', color_light: '#f1e3c4', color_wall: '#77612f', accent: '#e3b031', tagline: 'hooks · scripts · fact-check', lead: 'script-writer' },
    { key: 'social', name: 'Social', color: '#ca54cf', color_light: '#ecc3ee', color_wall: '#6f2e72', accent: '#cd51d5', tagline: 'posts · calendar · replies', lead: 'social-media-manager' },
    { key: 'creative', name: 'Creative', color: '#7a69d1', color_light: '#d0caef', color_wall: '#433a73', accent: '#7269d4', tagline: 'rough cuts · captions · thumbnails', lead: 'creative-director' },
    { key: 'analytics', name: 'Analytics', color: '#40aa9c', color_light: '#bce1dc', color_wall: '#235e56', accent: '#07b594', tagline: 'retention · reports · lessons', lead: 'analytics-lead' },
    { key: 'shop', name: 'Shop', color: '#d74961', color_light: '#f1bfc8', color_wall: '#762835', accent: '#f6275b', tagline: 'listings · orders · support', lead: 'shop-manager' },
    { key: 'dev', name: 'Dev', color: '#48b467', color_light: '#bfe5ca', color_wall: '#286339', accent: '#28ad5e', tagline: 'ships the code', lead: 'engineering-lead' },
    { key: 'inbox', name: 'Inbox', color: '#d69155', color_light: '#f1d8c4', color_wall: '#76502f', accent: '#f69a4f', tagline: 'email · brand deals · quotes', lead: 'inbox-manager' },
  ];

  // Character looks taken from the video where the spec names them; everyone else gets a hashed variation.
  const SKINS = [0xe8d4c1, 0xd1b9a8, 0xc3b38f, 0x645348, 0xf1c9a5, 0x7a4b2e];
  const HAIRS = [0x926546, 0xab754b, 0xb33a2a, 0xeed787, 0x795e55, 0x2a2a2e];
  const STYLES = ['short', 'bob', 'long', 'bun', 'short', 'beanie', 'cap'];
  const LOOKS = {
    'research-director': { hair: 0x2a2a2e, style: 'short', shirt: 0xea8a38 },
    'market-analyst': { hair: 0x926546, style: 'short', shirt: 0x75bdd8, phones: 0x3fbf6a },
    'trend-scout': { hair: 0xb33a2a, style: 'bob', shirt: 0x3fbf6a },
    'competitor-analyst': { hair: 0xeed787, style: 'bun', shirt: 0x465364 },
    'script-writer': { hair: 0xb33a2a, style: 'cap', hat: 0xd63a3a, shirt: 0x2f3340 },
    'hook-writer': { hair: 0x926546, style: 'bob', shirt: 0x8569db },
    'seo-specialist': { hair: 0xeed787, style: 'short', shirt: 0xe3b031 },
    'social-media-manager': { hair: 0xb33a2a, style: 'long', shirt: 0xcd51d5 },
    'community-manager': { hair: 0x3fbf6a, style: 'short', shirt: 0xea8a38, phones: 0x3fbf6a },
    'email-marketer': { hair: 0x795e55, style: 'bun', shirt: 0xe8e8e8 },
    'outreach-writer': { hair: 0x2a2a2e, style: 'short', shirt: 0xef3155 },
    'creative-director': { hair: 0xc3c7cc, style: 'short', shirt: 0x7c6cf0, phones: 0xe6e6e6 },
    'thumbnail-designer': { skin: 0x645348, hair: 0x2a2a2e, style: 'short', shirt: 0xe8e8e8, phones: 0xe0432f, glasses: true },
    'clip-editor': { hair: 0xb33a2a, style: 'bob', shirt: 0x3a3f4a },
    'brand-checker': { hair: 0xeed787, style: 'long', shirt: 0x8569db },
    'analytics-lead': { hair: 0x795e55, style: 'short', shirt: 0xe89549 },
    'data-analyst': { hair: 0xeed787, style: 'bob', shirt: 0x54c9a6 },
    'strategist': { hair: 0x926546, style: 'short', shirt: 0x465364 },
    'shop-manager': { hair: 0x2a2a2e, style: 'short', shirt: 0xea8a38, phones: 0x222222 },
    'copywriter': { hair: 0xd9652f, style: 'long', shirt: 0xef3155 },
    'ads-specialist': { hair: 0x926546, style: 'short', shirt: 0xe8e8e8 },
    'finance-analyst': { hair: 0xeed787, style: 'bun', shirt: 0x75bdd8 },
    'project-manager': { hair: 0x795e55, style: 'beanie', hat: 0xd63a3a, shirt: 0x465364 },
    'engineering-lead': { hair: 0x2a2a2e, style: 'short', shirt: 0x6f7bd6 },
    'frontend-dev': { hair: 0x926546, style: 'short', shirt: 0xef3155 },
    'backend-dev': { hair: 0xeed787, style: 'short', shirt: 0x3fbf6a, glasses: true },
    'qa-tester': { hair: 0xb33a2a, style: 'bob', shirt: 0x54c9a6 },
    'code-reviewer': { hair: 0x795e55, style: 'cap', hat: 0x3fbf6a, shirt: 0xe8e8e8 },
    'inbox-manager': { hair: 0x926546, style: 'short', shirt: 0x3fbf6a },
    'customer-support': { hair: 0xeed787, style: 'bob', shirt: 0x75bdd8, phones: 0xe6e6e6 },
    'proposal-writer': { hair: 0x2a2a2e, style: 'short', shirt: 0xea8a38 },
  };

  // ------------------------------------------------------------------ small helpers
  const hash = (str) => { let h = 2166136261; for (let i = 0; i < str.length; i++) { h ^= str.charCodeAt(i); h = Math.imul(h, 16777619); } return h >>> 0; };
  const rng = (seed) => { let s = (seed >>> 0) || 1; return () => { s = (Math.imul(s, 1664525) + 1013904223) >>> 0; return s / 4294967296; }; };
  const col = (c) => (c instanceof THREE.Color ? c.clone() : new THREE.Color(c));
  const mix = (a, b, t) => col(a).lerp(col(b), t);
  const hexOf = (c) => '#' + col(c).getHexString();
  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
  const ease = (x) => (x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2);
  const easeOut = (x) => 1 - Math.pow(1 - x, 3);

  function canvasTex(w, h, draw) {
    const c = document.createElement('canvas'); c.width = w; c.height = h;
    draw(c.getContext('2d'), w, h);
    const t = new THREE.CanvasTexture(c); t.anisotropy = 4; return t;
  }
  const MONO = 'ui-monospace, "JetBrains Mono", Menlo, Consolas, monospace';

  // A soft radial glow (used by sprites, light pools and the particle points).
  const glowTex = canvasTex(128, 128, (g, w, h) => {
    const r = g.createRadialGradient(w / 2, h / 2, 0, w / 2, h / 2, w / 2);
    r.addColorStop(0, 'rgba(255,255,255,1)'); r.addColorStop(0.35, 'rgba(255,255,255,0.55)'); r.addColorStop(1, 'rgba(255,255,255,0)');
    g.fillStyle = r; g.fillRect(0, 0, w, h);
  });
  // Dashes for the walkway centre lines (repeat along v).
  const dashTex = canvasTex(16, 64, (g, w, h) => { g.clearRect(0, 0, w, h); g.fillStyle = '#fff'; g.fillRect(4, 6, w - 8, h / 2 - 6); });
  dashTex.wrapS = dashTex.wrapT = THREE.RepeatWrapping;
  // The void floor: lit near the Brain, dark at the corners.
  const groundTex = canvasTex(1024, 1024, (g, w, h) => {
    const r = g.createRadialGradient(w / 2, h / 2, 0, w / 2, h / 2, w / 2);
    // the visible area is ~190 units around the Brain on a 760-unit plane, so the fall-off has to happen within r < 0.3
    r.addColorStop(0, '#4a5470'); r.addColorStop(0.08, '#3d4660'); r.addColorStop(0.17, '#2c3245'); r.addColorStop(0.3, '#1b1e2c'); r.addColorStop(1, '#13151f');
    g.fillStyle = r; g.fillRect(0, 0, w, h);
  });

  // Screen pictures drawn once and shared.
  function monitorTex(kind, seed) {
    const r = rng(hash(kind + seed));
    return canvasTex(256, 160, (g, w, h) => {
      const line = (x, y, len, color, th) => { g.fillStyle = color; g.fillRect(x, y, len, th || 6); };
      if (kind === 'code') {
        g.fillStyle = '#0b0d12'; g.fillRect(0, 0, w, h);
        for (let i = 0; i < 12; i++) { const y = 10 + i * 12, ind = 10 + (i % 4) * 14; line(ind, y, 20 + r() * 40, '#6ea8ff'); line(ind + 28 + r() * 40, y, 20 + r() * 90, r() < 0.3 ? '#8fe0a8' : r() < 0.5 ? '#ffb86b' : '#a9c8ff'); }
      } else if (kind === 'chart') {
        g.fillStyle = '#1b2338'; g.fillRect(0, 0, w, h);
        g.strokeStyle = 'rgba(255,255,255,0.08)'; g.lineWidth = 1; for (let i = 1; i < 5; i++) { g.beginPath(); g.moveTo(10, i * 30); g.lineTo(w - 10, i * 30); g.stroke(); }
        for (let i = 0; i < 8; i++) { g.fillStyle = 'rgba(120,170,255,0.35)'; const bh = 20 + r() * 70; g.fillRect(16 + i * 30, h - 14 - bh, 18, bh); }
        g.strokeStyle = '#e9f2ff'; g.lineWidth = 3; g.beginPath(); let y = h * 0.7; g.moveTo(10, y); for (let x = 30; x <= w - 10; x += 22) { y -= r() * 16 - 5; y = clamp(y, 18, h - 20); g.lineTo(x, y); } g.stroke();
      } else if (kind === 'timeline') {
        g.fillStyle = '#0e1016'; g.fillRect(0, 0, w, h);
        g.fillStyle = '#1b1e2a'; g.fillRect(12, 10, 70, 44); g.fillStyle = '#d96a3a'; g.fillRect(18, 16, 58, 32); g.fillStyle = '#f2d16b'; g.fillRect(40, 24, 22, 14);
        g.fillStyle = '#20232f'; g.fillRect(90, 10, w - 102, 44); for (let i = 0; i < 6; i++) line(96 + i * 24, 18 + (i % 3) * 10, 18, '#8b93a7', 3);
        const colors = ['#36d6e7', '#ff9a3c', '#ff5fd2', '#4ade80', '#ffd84a', '#8f7cff'];
        for (let i = 0; i < 6; i++) { const y = 64 + i * 15, x = 12 + r() * 60, len = 40 + r() * 140; g.fillStyle = '#171a24'; g.fillRect(10, y - 2, w - 20, 13); g.fillStyle = colors[i]; g.fillRect(x, y, Math.min(len, w - 12 - x), 9); }
        g.fillStyle = '#ffffff'; g.fillRect(118, 58, 2, h - 62);
      } else if (kind === 'products') {
        g.fillStyle = '#141420'; g.fillRect(0, 0, w, h);
        const colors = ['#e24b4b', '#3b63d6', '#ff8a3c', '#8f5cff', '#3fbf6a', '#ff6fb1', '#2fb7a1', '#ffd84a'];
        for (let i = 0; i < 8; i++) { const x = 12 + (i % 4) * 60, y = 12 + Math.floor(i / 4) * 72; g.fillStyle = '#1f2030'; g.fillRect(x, y, 52, 64); g.fillStyle = colors[i]; g.fillRect(x + 6, y + 6, 40, 36); line(x + 6, y + 48, 30, '#dfe3ee', 4); line(x + 6, y + 56, 18, '#8b93a7', 4); }
      } else if (kind === 'captions') {
        g.fillStyle = '#0f1218'; g.fillRect(0, 0, w, h);
        for (let i = 0; i < 11; i++) { const y = 12 + i * 13; line(12, y, 16, '#6b7280', 5); line(36, y, 40 + r() * 150, i % 3 === 0 ? '#e6edf3' : '#4cd9a6', 5); }
      } else if (kind === 'text') {
        g.fillStyle = '#0d1017'; g.fillRect(0, 0, w, h);
        for (let i = 0; i < 10; i++) { const y = 12 + i * 14; line(14, y, 60 + r() * 150, i === 0 ? '#ffffff' : '#9aa3b2', i === 0 ? 7 : 5); }
        g.fillStyle = '#6ea8ff'; g.fillRect(200, 12, 42, 12);
      } else {                                                                   // 'white': the sub-agents' glowing screens
        g.fillStyle = '#ffffff'; g.fillRect(0, 0, w, h);
        for (let i = 0; i < 7; i++) line(16, 18 + i * 18, 60 + r() * 150, 'rgba(120,130,160,0.35)', 6);
      }
    });
  }
  const screenTex = {};
  const getScreenTex = (kind) => screenTex[kind] || (screenTex[kind] = monitorTex(kind, 1));

  // The wall dashboard of a team: tiny title in the team colour, white stat numbers, a rising line chart.
  function dashboardTex(team) {
    const r = rng(hash(team.key)), red = team.key === 'shop';
    return canvasTex(512, 288, (g, w, h) => {
      g.fillStyle = '#121116'; g.fillRect(0, 0, w, h);
      g.fillStyle = team.accent; g.font = 'bold 20px ' + MONO; g.fillText(team.name.toUpperCase(), 26, 40);
      g.fillStyle = '#eef1f7'; g.font = 'bold 30px ' + MONO;
      const stats = [String(40 + Math.floor(r() * 140)), String(3 + Math.floor(r() * 30)), Math.floor(r() * 90 + 10) + '%'];
      stats.forEach((s, i) => { g.fillText(s, 26 + i * 150, 92); g.fillStyle = '#6b7280'; g.fillRect(26 + i * 150, 104, 80, 4); g.fillStyle = '#eef1f7'; });
      g.strokeStyle = 'rgba(255,255,255,0.07)'; g.lineWidth = 1; for (let i = 0; i < 4; i++) { g.beginPath(); g.moveTo(26, 130 + i * 36); g.lineTo(w - 26, 130 + i * 36); g.stroke(); }
      g.strokeStyle = red ? '#ff5a6a' : '#f4f6fa'; g.lineWidth = 5; g.lineJoin = 'round'; g.beginPath();
      let y = h - 40; g.moveTo(26, y); for (let x = 60; x <= w - 26; x += 34) { y -= r() * 30 - 8; y = clamp(y, 128, h - 30); g.lineTo(x, y); } g.stroke();
      g.fillStyle = 'rgba(255,255,255,0.12)'; for (let i = 0; i < 3; i++) g.fillRect(w - 110 + i * 34, 30, 24, 10);
    });
  }
  const smallScreenTex = canvasTex(256, 160, (g, w, h) => {
    g.fillStyle = '#121116'; g.fillRect(0, 0, w, h); const r = rng(7);
    for (let i = 0; i < 8; i++) { const y = 18 + i * 17; g.fillStyle = i % 4 === 0 ? '#8fe0a8' : '#c3c8d3'; g.fillRect(16, y, 30 + r() * 170, 6); }
  });

  // The Creative floor decal: a dashed rounded rectangle, with the "SUB-AGENT BAY · ready" text until sub-agents arrive.
  function bayTex(withText) {
    return canvasTex(1024, 400, (g, w, h) => {
      g.clearRect(0, 0, w, h);
      g.strokeStyle = 'rgba(214,208,255,0.85)'; g.lineWidth = 5; g.setLineDash([22, 14]);
      g.beginPath(); g.moveTo(44, 16); g.lineTo(w - 44, 16); g.quadraticCurveTo(w - 16, 16, w - 16, 44); g.lineTo(w - 16, h - 44); g.quadraticCurveTo(w - 16, h - 16, w - 44, h - 16);
      g.lineTo(44, h - 16); g.quadraticCurveTo(16, h - 16, 16, h - 44); g.lineTo(16, 44); g.quadraticCurveTo(16, 16, 44, 16); g.stroke();
      if (withText) { g.setLineDash([]); g.fillStyle = 'rgba(230,226,255,0.9)'; g.font = '600 44px ' + MONO; g.fillText('SUB-AGENT BAY · ready', 60, h - 54); }
    });
  }

  // ------------------------------------------------------------------ geometry merging (static props become one mesh)
  const G = {
    box: new THREE.BoxGeometry(1, 1, 1).toNonIndexed(),
    cyl: new THREE.CylinderGeometry(1, 1, 1, 16).toNonIndexed(),
    cone: new THREE.ConeGeometry(1, 1, 16).toNonIndexed(),
    ico: new THREE.IcosahedronGeometry(1, 1),
    sphere: new THREE.SphereGeometry(1, 14, 10).toNonIndexed(),
  };
  const _m = new THREE.Matrix4(), _nm = new THREE.Matrix3(), _q = new THREE.Quaternion(), _e = new THREE.Euler(), _s = new THREE.Vector3(), _p = new THREE.Vector3(), _v = new THREE.Vector3();
  class Merger {
    constructor(material) { this.pos = []; this.nor = []; this.col = []; this.material = material; }
    add(geo, color, x, y, z, o) {
      o = o || {};
      const g = geo.index ? geo.toNonIndexed() : geo;
      _m.compose(_p.set(x, y, z), _q.setFromEuler(_e.set(o.rx || 0, o.ry || 0, o.rz || 0)), _s.set(o.sx || 1, o.sy || 1, o.sz || 1));
      if (o.parent) _m.premultiply(o.parent);
      _nm.getNormalMatrix(_m);
      const c = col(color), P = g.attributes.position, N = g.attributes.normal;
      for (let i = 0; i < P.count; i++) {
        _v.fromBufferAttribute(P, i).applyMatrix4(_m); this.pos.push(_v.x, _v.y, _v.z);
        _v.fromBufferAttribute(N, i).applyMatrix3(_nm).normalize(); this.nor.push(_v.x, _v.y, _v.z);
        this.col.push(c.r, c.g, c.b);
      }
      if (g !== geo) g.dispose();
    }
    box(w, h, d, x, y, z, color, o) { this.add(G.box, color, x, y, z, Object.assign({}, o, { sx: w, sy: h, sz: d })); }
    cyl(r, h, x, y, z, color, o) { this.add(G.cyl, color, x, y, z, Object.assign({}, o, { sx: r, sy: h, sz: r })); }
    ball(r, x, y, z, color, o) { this.add(G.ico, color, x, y, z, Object.assign({}, o, { sx: r, sy: r, sz: r })); }
    mesh() {
      const geo = new THREE.BufferGeometry();
      geo.setAttribute('position', new THREE.Float32BufferAttribute(this.pos, 3));
      geo.setAttribute('normal', new THREE.Float32BufferAttribute(this.nor, 3));
      geo.setAttribute('color', new THREE.Float32BufferAttribute(this.col, 3));
      geo.computeBoundingSphere();
      const m = new THREE.Mesh(geo, this.material); m.matrixAutoUpdate = false; return m;
    }
  }
  const basic = (hex, o) => new THREE.MeshBasicMaterial(Object.assign({ color: hex }, o || {}));
  const geoCache = new Map();
  const rbox = (w, h, d, r) => { const k = [w, h, d, r].join(','); if (!geoCache.has(k)) geoCache.set(k, THREE.RoundedBoxGeometry ? new THREE.RoundedBoxGeometry(w, h, d, 3, r) : new THREE.BoxGeometry(w, h, d)); return geoCache.get(k); };

  // ------------------------------------------------------------------ renderer, scene, camera
  let renderer, scene, camera, controls, composer, bloomPass, css, clock;
  const state = {
    teams: [], agents: [], rooms: {}, roomList: [], seats: {}, walkers: [], subs: {}, built: false,
    mode: 'overview', userActiveUntil: 0, tween: null, selected: null, selectRing: null, fallbackRunning: {},
    size: { w: 0, h: 0 }, labelRules: { agentMaxDist: 110 },
  };
  const labels = { team: {}, agent: {}, brain: {}, sub: {} };
  const pickables = [];
  const anim = { dashboards: [], crawlers: [], glows: [], particles: null, rings: [], brain: {}, dust: null };

  function setupRenderer() {
    renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false, powerPreference: 'high-performance' });
    renderer.setPixelRatio(Math.min(1.5, window.devicePixelRatio || 1));
    renderer.setClearColor(0x13151f);
    renderer.domElement.style.display = 'block';
    if (getComputedStyle(host).position === 'static') host.style.position = 'relative';
    host.style.overflow = 'hidden';
    host.appendChild(renderer.domElement);

    scene = new THREE.Scene();
    scene.background = new THREE.Color(0x13151f);
    camera = new THREE.PerspectiveCamera(26, 1, 1, 900);

    controls = new THREE.OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true; controls.dampingFactor = 0.08;
    controls.minDistance = 18; controls.maxDistance = 360;
    controls.minPolarAngle = 0.25; controls.maxPolarAngle = 1.35;
    controls.autoRotateSpeed = -0.1;                                      // the idle drift: about ten minutes per orbit
    controls.screenSpacePanning = false;
    controls.addEventListener('start', () => { state.userActiveUntil = performance.now() + 9000; state.mode = 'free'; state.tween = null; controls.autoRotate = false; });

    // CSS2D labels sit in a layer over the canvas; clicks fall through to the canvas unless a label says otherwise.
    css = new THREE.CSS2DRenderer();
    Object.assign(css.domElement.style, { position: 'absolute', top: '0', left: '0', pointerEvents: 'none', overflow: 'hidden' });
    css.domElement.className = 'hq-labels';
    host.appendChild(css.domElement);

    composer = new THREE.EffectComposer(renderer);
    composer.addPass(new THREE.RenderPass(scene, camera));
    bloomPass = new THREE.UnrealBloomPass(new THREE.Vector2(800, 450), 0.9, 0.4, 0.85);   // strength, radius, threshold: glows bloom, rooms stay crisp
    composer.addPass(bloomPass);

    // Lights: cool ambient, a warm key from the camera side so the inner wall faces are lit, a faint fill.
    scene.add(new THREE.HemisphereLight(0xffffff, 0x55607a, 0.56));
    const key = new THREE.DirectionalLight(0xfff3e4, 0.48); key.position.set(60, 54, 60); scene.add(key);
    const fill = new THREE.DirectionalLight(0xbcd0ff, 0.16); fill.position.set(-40, 30, -25); scene.add(fill);
    const brainLight = new THREE.PointLight(0x9fd8ff, 0.75, 70, 1.6); brainLight.position.set(0, CORE_Y + 3.5, 0); scene.add(brainLight); anim.brain.light = brainLight;

    // The void: a gradient floor far below, dust dots on it and a few in the air.
    const ground = new THREE.Mesh(new THREE.PlaneGeometry(760, 760), new THREE.MeshBasicMaterial({ map: groundTex }));
    ground.rotation.x = -Math.PI / 2; ground.position.y = GROUND_Y; scene.add(ground);
    const dust = [], r = rng(99);
    for (let i = 0; i < 520; i++) { const a = r() * Math.PI * 2, d = 12 + Math.sqrt(r()) * 250; dust.push(Math.cos(a) * d, GROUND_Y + 0.15 + (i % 5 === 0 ? r() * 40 : 0), Math.sin(a) * d); }
    const dg = new THREE.BufferGeometry(); dg.setAttribute('position', new THREE.Float32BufferAttribute(dust, 3));
    anim.dust = new THREE.Points(dg, new THREE.PointsMaterial({ size: 1.0, map: glowTex, color: 0xd6dbe6, transparent: true, opacity: 0.55, depthWrite: false, sizeAttenuation: true }));
    scene.add(anim.dust);

    clock = new THREE.Clock();
    resize();
    if (window.ResizeObserver) new ResizeObserver(() => resize()).observe(host); else window.addEventListener('resize', resize);
    setupPicking();
  }

  function resize() {
    if (!renderer) return;
    const w = host.clientWidth || 800;
    let h = host.clientHeight;
    if (h < 40) { h = Math.max(320, Math.round(w * 0.56)); host.style.height = h + 'px'; }     // a bare container gets a 16:9-ish height
    state.size = { w, h };
    renderer.setSize(w, h); composer.setSize(w, h); css.setSize(w, h);
    camera.aspect = w / h; camera.updateProjectionMatrix();
    // The overview distance fits the ring of rooms into the frame the way the video frames it: the far room's wall top
    // (plus room for its floating card) sits just under the top bar and the bottom room is slightly cut.
    const hfov = 2 * Math.atan(Math.tan(camera.fov * DEG / 2) * camera.aspect);
    const dh = (RING_R + S * 0.85) / Math.tan(hfov / 2);
    const dv = ((RING_R + S * 0.72) * Math.sin(OVERVIEW.pitch) + WALL_H * Math.cos(OVERVIEW.pitch) + 6) / Math.tan(camera.fov * DEG / 2);
    OVERVIEW.dist = Math.max(dh * 0.9, dv) * 0.92;
    if (state.mode === 'overview' && !state.tween) placeCamera(OVERVIEW.yaw, OVERVIEW.pitch, OVERVIEW.dist, OVERVIEW.target);
  }

  // ------------------------------------------------------------------ the Brain
  function buildBrain() {
    const g = new THREE.Group(); scene.add(g);
    // Low gloss on purpose: the point light above the centre would otherwise put a hard specular hotspot on the discs,
    // and bloom turns any hotspot into a white blob.
    const phong = (c, o) => new THREE.MeshPhongMaterial(Object.assign({ color: c, shininess: 16, specular: 0x2a333d }, o || {}));
    const disc = (r, h, y, color) => { const m = new THREE.Mesh(new THREE.CylinderGeometry(r, r + 0.3, h, 96), phong(color)); m.position.y = y; g.add(m); return m; };
    const outer = disc(PLATFORM_R, 1.2, 0.6, 0x3a4858); outer.userData.brain = true; pickables.push(outer);
    disc(13.2, 0.5, 1.45, 0x4a6478);
    disc(7.8, 0.6, 2.0, 0x567488);
    const inner = new THREE.Mesh(new THREE.CircleGeometry(6.4, 64), new THREE.MeshLambertMaterial({ color: 0x567a8e, emissive: 0x2e5467, emissiveIntensity: 0.55 })); inner.rotation.x = -Math.PI / 2; inner.position.y = 2.32; g.add(inner);
    const ring = (r, tube, y, color, opacity) => { const m = new THREE.Mesh(new THREE.TorusGeometry(r, tube, 8, 128), basic(color, { transparent: opacity < 1, opacity })); m.rotation.x = -Math.PI / 2; m.position.y = y; g.add(m); return m; };
    anim.brain.neon = [ring(8.6, 0.11, 1.72, 0xc6f4ff, 1), ring(12.3, 0.11, 1.72, 0xc6f4ff, 1)];
    ring(5.4, 0.045, 2.33, 0x9fd0de, 0.7); ring(10.4, 0.045, 1.72, 0x8fb4c4, 0.6); ring(15.3, 0.045, 1.22, 0x8fb4c4, 0.55); ring(PLATFORM_R + 0.02, 0.06, 1.2, 0xa8bfd0, 0.6);
    // glow on the centre, the base glow under the platform and the beam of light dropping into the void
    const pool = flatGlow(5.5, 0x8fdcff, 0.22); pool.position.y = 2.36; g.add(pool);
    const base = flatGlow(16, 0x6fb6d8, 0.55); base.position.y = GROUND_Y + 0.12; g.add(base);
    const cone = new THREE.Mesh(new THREE.ConeGeometry(6.5, -GROUND_Y + 0.2, 48, 1, true), new THREE.MeshBasicMaterial({ color: 0x56859c, transparent: true, opacity: 0.22, blending: THREE.AdditiveBlending, depthWrite: false, side: THREE.DoubleSide }));
    cone.rotation.x = Math.PI; cone.position.y = GROUND_Y / 2 + 0.1; g.add(cone);
    // the core sphere, its beam and halo
    // The core is a matte ice-blue ball (it must not bloom into a white blob); only its halo and the beam glow.
    const core = new THREE.Mesh(new THREE.SphereGeometry(2.4, 40, 28), new THREE.MeshLambertMaterial({ color: 0xa9cfdd, emissive: 0x6a9db2, emissiveIntensity: 0.3 }));
    core.position.y = CORE_Y; g.add(core); anim.brain.core = core;
    const beam = new THREE.Mesh(new THREE.CylinderGeometry(0.2, 0.2, 110, 16, 1, true), basic(0xe6dcc4, { transparent: true })); beam.position.y = 2.3 + 55; g.add(beam); anim.brain.beam = beam;
    const halo = new THREE.Mesh(new THREE.CylinderGeometry(0.75, 0.75, 110, 16, 1, true), new THREE.MeshBasicMaterial({ color: 0xbfe9ff, transparent: true, opacity: 0.07, blending: THREE.AdditiveBlending, depthWrite: false, side: THREE.DoubleSide })); halo.position.y = beam.position.y; g.add(halo); anim.brain.halo = halo;
    const coreGlow = new THREE.Sprite(new THREE.SpriteMaterial({ map: glowTex, color: 0xbfe4ff, transparent: true, opacity: 0.12, blending: THREE.AdditiveBlending, depthWrite: false })); coreGlow.scale.set(7, 7, 1); coreGlow.position.y = CORE_Y; g.add(coreGlow); anim.brain.glow = coreGlow;
    // orbit rings (gyroscope look) and a faint lattice
    const r = rng(5);
    for (let i = 0; i < 5; i++) {
      const holder = new THREE.Group(); holder.position.y = CORE_Y; holder.rotation.set(1.0 + r() * 1.2, r() * Math.PI, r() * 0.9); g.add(holder);
      const radius = 4.3 + i * 0.75;
      const torus = new THREE.Mesh(new THREE.TorusGeometry(radius, 0.035, 6, 120), basic(0xffffff, { transparent: true, opacity: 0.55 })); torus.rotation.x = Math.PI / 2; holder.add(torus);
      anim.rings.push({ holder, radius, speed: (0.15 + r() * 0.25) * (i % 2 ? 1 : -1), phase: r() * 6.28 });
    }
    const lattice = new THREE.Mesh(new THREE.IcosahedronGeometry(5.6, 2), basic(0xbfe9ff, { wireframe: true, transparent: true, opacity: 0.08 })); lattice.position.y = CORE_Y; g.add(lattice); anim.brain.lattice = lattice;
    // a few faint network lines fanning out into space
    const netGeo = new THREE.BufferGeometry(), pts = [];
    for (let i = 0; i < 7; i++) { const a = r() * 6.28; pts.push(0, CORE_Y, 0, Math.cos(a) * 60, CORE_Y + 10 + r() * 40, Math.sin(a) * 60); }
    netGeo.setAttribute('position', new THREE.Float32BufferAttribute(pts, 3));
    g.add(new THREE.LineSegments(netGeo, new THREE.LineBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.08 })));
    // the small amber marker under the platform's front edge (seen in the overview)
    const marker = new THREE.Mesh(new THREE.ConeGeometry(0.5, 1.3, 12), basic(0xf0b24a)); marker.position.set(13.4, GROUND_Y + 0.65, 13.4); g.add(marker);
    const mg = flatGlow(3, 0xffd9a0, 0.6); mg.position.set(13.4, GROUND_Y + 0.14, 13.4); g.add(mg);
    // label anchor
    makeAnchor('brain', 'brain', g, new THREE.Vector3(0, CORE_Y + 5.2, 0));
  }

  // A flat additive glow disc lying on the floor (light pools, floor circles).
  function flatGlow(radius, color, opacity) {
    const m = new THREE.Mesh(new THREE.CircleGeometry(1, 40), new THREE.MeshBasicMaterial({ map: glowTex, color, transparent: true, opacity, blending: THREE.AdditiveBlending, depthWrite: false }));
    m.rotation.x = -Math.PI / 2; m.scale.set(radius, radius, 1); m.renderOrder = 2; return m;
  }

  // ------------------------------------------------------------------ rooms
  // Room i sits at the i-th clock position (0 = top of the screen, clockwise). The camera looks from +x+z, so screen
  // up is world (-x,-z) and screen right is world (+x,-z); all rooms are axis-aligned squares (diamonds on screen).
  function roomDir(i) { const a = i * Math.PI / 4; return new THREE.Vector3((Math.sin(a) - Math.cos(a)) * SQ, 0, (-Math.sin(a) - Math.cos(a)) * SQ); }

  // Desk slots in room-local units (x, z, facing): rot 0 faces -z (the back-right wall), PI/2 faces -x (the back-left wall).
  const SLOTS = {
    normal: { A: [0, -3.6, 0], B: [-3.2, 2.6, 0], C: [3.2, 2.6, 0], D: [-7.0, -2.0, Math.PI / 2], E: [6.6, -5.6, 0] },
    creative: { A: [0, -7.5, 0], B: [-3.6, -1.5, 0], C: [3.6, -1.5, 0], D: [-10.4, -6.0, Math.PI / 2], E: [9.6, -8.5, 0] },
  };

  function buildRoom(team, i, members) {
    const big = team.key === 'creative';
    const size = big ? S * 1.4 : S, h = size / 2;
    const dir = roomDir(i);
    const R = RING_R + (big ? (size - S) / 2 : 0);
    const cx = dir.x * R, cz = dir.z * R;
    const floorC = col(team.color), carpetC = col(team.color_light), wallC = col(team.color_wall).multiplyScalar(1.3), accentC = col(team.accent || team.color);
    const trimC = mix(accentC, 0xffffff, 0.35), topTrimC = mix(wallC, 0xffffff, 0.25);
    const hasSofa = ['inbox', 'social', 'analytics'].includes(team.key);
    const room = { key: team.key, team, index: i, center: new THREE.Vector3(cx, 0, cz), size, half: h, dir, color: team.color, members, seats: [], subs: [], lit: false, big };
    room.near = h / Math.max(Math.abs(dir.x), Math.abs(dir.z));            // distance from the centre to the slab edge toward the Brain
    const F = SLAB_H;                                                          // floor top
    const shell = new Merger(new THREE.MeshPhongMaterial({ vertexColors: true, shininess: 14, specular: 0x202024 }));
    const props = new Merger(new THREE.MeshLambertMaterial({ vertexColors: true }));
    const glow = new Merger(new THREE.MeshBasicMaterial({ vertexColors: true }));

    // slab, two back walls (inner faces catch the key light), top trims, edge trims, the corner post, the carpet
    shell.box(size, SLAB_H, size, cx, SLAB_H / 2, cz, floorC);
    shell.box(WALL_T, WALL_H, size, cx - h + WALL_T / 2, F + WALL_H / 2, cz, wallC);
    shell.box(size, WALL_H, WALL_T, cx, F + WALL_H / 2, cz - h + WALL_T / 2, wallC);
    shell.box(WALL_T + 0.16, 0.16, size, cx - h + WALL_T / 2, F + WALL_H + 0.08, cz, topTrimC);
    shell.box(size, 0.16, WALL_T + 0.16, cx, F + WALL_H + 0.08, cz - h + WALL_T / 2, topTrimC);
    shell.box(0.55, WALL_H + 1.6, 0.55, cx - h + 0.27, F + (WALL_H + 1.6) / 2, cz - h + 0.27, 0x1d2029);
    const edge = (w, d, x, z, c) => shell.box(w, 0.1, d, x, F + 0.05, z, c);
    if (team.key === 'social') {                                               // neon magenta strips on every edge and wall top
      for (const [w, d, x, z] of [[size, 0.18, cx, cz + h - 0.1], [0.18, size, cx + h - 0.1, cz], [size, 0.18, cx, cz - h + WALL_T + 0.1], [0.18, size, cx - h + WALL_T + 0.1, cz]]) glow.box(w, 0.12, d, x, F + 0.06, z, 0xffc6ff);
      glow.box(0.14, 0.14, size, cx - h + WALL_T / 2, F + WALL_H + 0.22, cz, 0xffc6ff);
      glow.box(size, 0.14, 0.14, cx, F + WALL_H + 0.22, cz - h + WALL_T / 2, 0xffc6ff);
    } else {
      edge(size, 0.22, cx, cz + h - 0.11, team.key === 'creative' ? 0xe6dcff : trimC);
      edge(0.22, size, cx + h - 0.11, cz, trimC);
      if (team.key === 'creative') glow.box(size, 0.1, 0.16, cx, F + 0.08, cz + h - 0.1, 0xe6dcff);
    }
    const carpet = big ? [0, -4.5, 15, 12] : [0, 2.2, 12, 9];
    shell.box(carpet[2], 0.05, carpet[3], cx + carpet[0], F + 0.025, cz + carpet[1], carpetC);

    // wall dashboard on the back-left wall (+ a smaller text screen in some rooms)
    const dashTexm = dashboardTex(team);
    props.box(0.16, 3.6, 6.4, cx - h + WALL_T + 0.08, F + 5.5, cz - h + size * 0.3, 0x0d0d12);
    const dash = new THREE.Mesh(new THREE.PlaneGeometry(6.0, 3.3), new THREE.MeshBasicMaterial({ map: dashTexm }));
    dash.rotation.y = Math.PI / 2; dash.position.set(cx - h + WALL_T + 0.17, F + 5.5, cz - h + size * 0.3); scene.add(dash);
    anim.dashboards.push({ mesh: dash, team: team.key });
    if (['research', 'scripts', 'creative', 'dev', 'inbox'].includes(team.key)) {
      props.box(0.16, 2.0, 3.0, cx - h + WALL_T + 0.08, F + 5.0, cz - h + size * 0.62, 0x0d0d12);
      const small = new THREE.Mesh(new THREE.PlaneGeometry(2.7, 1.7), new THREE.MeshBasicMaterial({ map: smallScreenTex, color: 0xbbbbbb }));
      small.rotation.y = Math.PI / 2; small.position.set(cx - h + WALL_T + 0.17, F + 5.0, cz - h + size * 0.62); scene.add(small);
    }
    // floor lamp in the back corner: black pole, glowing bulb, warm point light and a light pool
    const lx = cx - h + 1.7, lz = cz - h + 1.7;
    props.cyl(0.42, 0.12, lx, F + 0.06, lz, 0x15151a); props.cyl(0.07, 5.2, lx, F + 2.6, lz, 0x15151a);
    glow.ball(0.42, lx, F + 5.45, lz, 0xfff6e6);
    addGlowSprite(lx, F + 5.45, lz, 0xffecc8, 2.0, 0.45);
    const pool = flatGlow(3.8, 0xffe2b8, 0.26); pool.position.set(lx, F + 0.03, lz); scene.add(pool);
    const pl = new THREE.PointLight(0xffe3b8, 0.5, 15, 2); pl.position.set(lx, F + 5.0, lz); scene.add(pl);

    // bookshelf on the back-right wall: a light plank with books (product boxes in the Shop) and a tiny plant
    const sx = cx + size * 0.22, sz = cz - h + WALL_T + 0.4, sy = F + 5.3;
    props.box(3.4, 0.12, 0.75, sx, sy, sz, 0xe8dcc4);
    const books = team.key === 'shop' ? [0xe24b4b, 0x3b63d6, 0xff8a3c, 0x8f5cff, 0x3fbf6a, 0xff6fb1] : [0xe0485e, 0x3b63d6, 0x6a5bd6, 0xff7ab8, 0xf2efe8, 0xe0c040];
    books.forEach((c, k) => { if (team.key === 'shop') props.box(0.42, 0.42, 0.42, sx - 1.35 + k * 0.5, sy + 0.27, sz, c); else props.box(0.26, 0.9 + (k % 3) * 0.08, 0.55, sx - 1.45 + k * 0.34, sy + 0.51, sz, c, { rz: k === 3 ? 0.18 : 0 }); });
    plant(props, sx + 1.35, sy + 0.06, sz, 0.42);
    // plants: inside the right corner and the front corner
    plant(props, cx + h - 1.7, F, cz - h + 1.9, 1);
    plant(props, cx + h - 1.6, F, cz + h - 1.6, 0.9);
    // sofa rooms: white two-seater and a round side table along the left wall
    if (hasSofa) {
      const sc = team.key === 'analytics' ? 0xc3d1d1 : 0xd9cdd7, ox = cx - h + 1.9, oz = cz + 0.8;
      props.box(1.5, 0.7, 3.4, ox, F + 0.45, oz, sc); props.box(0.45, 0.95, 3.4, ox - 0.55, F + 1.05, oz, sc);
      props.box(1.5, 0.45, 0.3, ox, F + 0.95, oz - 1.6, sc); props.box(1.5, 0.45, 0.3, ox, F + 0.95, oz + 1.6, sc);
      props.box(1.3, 0.16, 1.45, ox + 0.1, F + 0.85, oz - 0.78, mix(sc, 0xffffff, 0.3)); props.box(1.3, 0.16, 1.45, ox + 0.1, F + 0.85, oz + 0.78, mix(sc, 0xffffff, 0.3));
      props.cyl(0.55, 0.1, ox, F + 0.85, oz + 2.75, 0xf8f0f1); props.cyl(0.08, 0.8, ox, F + 0.4, oz + 2.75, 0xd8d0d2);
    }
    // Creative extras: ring light on a stand, a tripod, a second white light, the sub-agent bay decal
    if (big) {
      const rx = cx - h + 2.8, rz = cz - size * 0.08;
      props.cyl(0.5, 0.1, rx, F + 0.05, rz, 0x15151a); props.cyl(0.06, 4.6, rx, F + 2.3, rz, 0x15151a);
      const ringLight = new THREE.Mesh(new THREE.TorusGeometry(1.15, 0.13, 10, 48), basic(0xf4f0ff)); ringLight.position.set(rx, F + 5.5, rz); ringLight.rotation.y = Math.PI / 4; scene.add(ringLight);
      addGlowSprite(rx, F + 5.5, rz, 0xe8e0ff, 3.0, 0.35);
      const tx = cx - h + 3.4, tz = cz + h - 3.6;
      for (let k = 0; k < 3; k++) { const a = k * 2.094; props.box(0.08, 4.4, 0.08, tx + Math.cos(a) * 0.55, F + 2.1, tz + Math.sin(a) * 0.55, 0x101014, { rx: Math.sin(a) * 0.25, rz: -Math.cos(a) * 0.25 }); }
      props.box(0.55, 0.4, 0.3, tx, F + 4.5, tz, 0x101014);
      props.cyl(0.07, 3.0, cx + h - 1.6, F + 1.5, cz - h + 4.6, 0x15151a); glow.ball(0.3, cx + h - 1.6, F + 3.1, cz - h + 4.6, 0xffffff);
      room.bay = { x: 0, z: 7.0, w: 22, d: 9 };
      room.bayTex = { text: bayTex(true), plain: bayTex(false) };
      const decal = new THREE.Mesh(new THREE.PlaneGeometry(room.bay.w, room.bay.d), new THREE.MeshBasicMaterial({ map: room.bayTex.text, transparent: true, depthWrite: false }));
      decal.rotation.x = -Math.PI / 2; decal.position.set(cx + room.bay.x, F + 0.04, cz + room.bay.z); decal.renderOrder = 1; scene.add(decal); room.decal = decal;
    }
    // Research extras: glowing crawler rings on the floor and walls and a white orb
    if (team.key === 'research') {
      const r = rng(31);
      for (let k = 0; k < 12; k++) {
        const ringM = new THREE.Mesh(new THREE.TorusGeometry(0.34, 0.05, 6, 24), basic(0xd8f8ff, { transparent: true, opacity: 0.8 }));
        if (k < 9) { ringM.rotation.x = -Math.PI / 2; ringM.position.set(cx - h + 1.5 + r() * (size - 3), F + 0.08, cz - h + 1.5 + r() * (size - 3)); }
        else if (k < 11) { ringM.rotation.y = Math.PI / 2; ringM.position.set(cx - h + WALL_T + 0.1, F + 1.5 + r() * 6, cz - 2 + r() * 10); }
        else ringM.position.set(cx - 4 + r() * 8, F + 1.5 + r() * 6, cz - h + WALL_T + 0.1);
        scene.add(ringM); anim.crawlers.push({ mesh: ringM, phase: r() * 6.28 });
      }
      const orb = new THREE.Mesh(new THREE.SphereGeometry(0.35, 12, 10), basic(0xffffff)); orb.position.set(cx - 3.5, F + 5.6, cz - 3.5); scene.add(orb);
      addGlowSprite(cx - 3.5, F + 5.6, cz - 3.5, 0xdfffff, 2.4, 0.45); anim.crawlers.push({ mesh: orb, orb: true, phase: 0, base: orb.position.clone() });
    }

    // desks: the head at the back, workers in front, then the side slots
    const slots = big ? SLOTS.creative : SLOTS.normal;
    const order = hasSofa ? ['A', 'B', 'C', 'E', 'D'] : ['A', 'B', 'C', 'D', 'E'];
    const head = members.find((a) => a.role === 'head'), workers = members.filter((a) => a !== head);
    const seated = (head ? [head] : []).concat(workers);
    seated.forEach((agent, k) => {
      const slot = slots[order[k % order.length]];
      if (k >= order.length) return;                                          // more than 5 agents: the rest have no desk (not the case today)
      addSeat(room, agent, slot, props, cx, cz, k === 0 && head === agent);
    });
    // merged meshes
    const shellMesh = shell.mesh(); shellMesh.userData.room = team.key; scene.add(shellMesh); pickables.push(shellMesh);
    scene.add(props.mesh()); scene.add(glow.mesh());
    // the team label above the back corner
    makeAnchor('team', team.key, scene, new THREE.Vector3(cx - h + 0.3, F + WALL_H + 4.0, cz - h + 0.3));
    state.rooms[team.key] = room; state.roomList.push(room);
    return room;
  }

  function plant(merger, x, y, z, k) {
    merger.cyl(0.55 * k, 0.9 * k, x, y + 0.45 * k, z, 0xd3d7ce);
    merger.ball(0.95 * k, x, y + 1.55 * k, z, 0x52a775); merger.ball(0.7 * k, x + 0.45 * k, y + 2.1 * k, z + 0.2 * k, 0x3fae5a); merger.ball(0.62 * k, x - 0.4 * k, y + 2.2 * k, z - 0.25 * k, 0x5db87c);
  }
  function addGlowSprite(x, y, z, color, scale, opacity) {
    const sp = new THREE.Sprite(new THREE.SpriteMaterial({ map: glowTex, color, transparent: true, opacity, blending: THREE.AdditiveBlending, depthWrite: false }));
    sp.scale.set(scale, scale, 1); sp.position.set(x, y, z); scene.add(sp); return sp;
  }

  // One desk unit: desk, chair, monitor(s), the seated character, a floor pool and ring, and the agent's label anchor.
  function addSeat(room, agent, slot, props, cx, cz, isHead) {
    const F = SLAB_H, rot = slot[2];
    const unit = new THREE.Matrix4().makeRotationY(rot).setPosition(cx + slot[0], F, cz + slot[1]);
    const o = { parent: unit };
    const deskC = isHead ? 0xd2b07a : 0xe2d8c6, deskW = isHead ? 5.0 : 4.4;
    props.box(deskW, 0.14, 1.8, 0, 1.93, 0, deskC, o);
    for (const ex of [-deskW / 2 + 0.25, deskW / 2 - 0.25]) { props.box(0.1, 1.86, 0.1, ex, 0.93, -0.7, 0x151010, o); props.box(0.1, 1.86, 0.1, ex, 0.93, 0.7, 0x151010, o); props.box(0.1, 0.1, 1.5, ex, 0.05, 0, 0x151010, o); }
    props.box(1.1, 0.05, 0.38, 0, 2.03, 0.45, 0x2a2d35, o);                                   // keyboard
    // chair: seat, back, column, star base
    const chz = 1.6;
    props.box(1.35, 0.16, 1.35, 0, 1.18, chz, 0x2a2d31, o); props.box(1.3, 1.3, 0.14, 0, 1.95, chz + 0.64, 0x2a2d31, o);
    props.cyl(0.07, 0.9, 0, 0.64, chz, 0x3a3d42, o);
    for (let k = 0; k < 5; k++) { const a = k * 1.2566; props.box(0.95, 0.07, 0.1, Math.cos(a) * 0.44, 0.1, chz + Math.sin(a) * 0.44, 0x1c1e24, Object.assign({ ry: -a }, o)); }
    // monitor(s): dark frame + stand (merged) and a screen plane (separate, lit by the running state)
    const kinds = screenKinds(room.key, agent);
    const n = isHead ? 2 : 1, screens = [];
    const mw = n === 2 ? 1.8 : 2.0, mh = n === 2 ? 1.1 : 1.2;
    for (let k = 0; k < n; k++) {
      const mx = n === 2 ? (k === 0 ? -1.0 : 1.0) : 0, yaw = n === 2 ? (k === 0 ? 0.14 : -0.14) : 0;
      const mm = new THREE.Matrix4().makeRotationY(yaw).setPosition(mx, 0, -0.42);
      const mo = { parent: new THREE.Matrix4().multiplyMatrices(unit, mm) };
      const my = 2.0 + 0.4 + mh / 2;
      props.box(mw, mh, 0.07, 0, my, 0, 0x181619, mo); props.cyl(0.07, 0.4, 0, 2.2, 0, 0x202024, mo); props.box(0.7, 0.04, 0.38, 0, 2.02, 0.02, 0x202024, mo);
      const screen = new THREE.Mesh(new THREE.PlaneGeometry(mw - 0.14, mh - 0.14), new THREE.MeshBasicMaterial({ map: getScreenTex(kinds[k % kinds.length]), color: 0xcfcfcf }));
      screen.position.set(0, my, 0.04); screen.applyMatrix4(mo.parent); scene.add(screen); screens.push(screen.material);
    }
    if (isHead) { props.cyl(0.05, 0.9, 1.9, 2.45, -0.5, 0x15151a, o); const lp = new THREE.Vector3(1.9, 2.95, -0.5).applyMatrix4(unit); const bulb = new THREE.Mesh(new THREE.SphereGeometry(0.16, 10, 8), basic(0xffffff)); bulb.position.copy(lp); scene.add(bulb); addGlowSprite(lp.x, lp.y, lp.z, 0xfff4e0, 1.3, 0.45); }
    // the character on the chair, facing the desk
    const look = lookFor(agent, room.team);
    const ch = makeCharacter(look, { seated: true, head: isHead });
    const cp = new THREE.Vector3(0, 0, chz).applyMatrix4(unit);
    ch.group.position.copy(cp); ch.group.rotation.y = rot + Math.PI; ch.group.scale.setScalar(CHAR_SCALE); ch.baseY = cp.y; scene.add(ch.group);
    const hit = new THREE.Mesh(new THREE.BoxGeometry(1.6, 3.8, 1.6), new THREE.MeshBasicMaterial({ visible: false })); hit.position.y = 1.9; hit.userData.agent = agent.name; ch.group.add(hit); pickables.push(hit);
    // floor pool and running ring under the chair
    const pool = flatGlow(2.3, 0xffffff, 0.09); pool.position.set(cp.x, F + 0.03, cp.z); scene.add(pool);
    const ring = new THREE.Mesh(new THREE.RingGeometry(0.95, 1.35, 40), new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0, blending: THREE.AdditiveBlending, depthWrite: false }));
    ring.rotation.x = -Math.PI / 2; ring.position.set(cp.x, F + 0.05, cp.z); scene.add(ring);
    const anchor = makeAnchor('agent', agent.name, ch.group, new THREE.Vector3(0, 4.4, 0));
    const seat = { agent, room, ch, screens, pool, ring, anchor, phase: hash(agent.name) % 100 / 10, running: false };
    state.seats[agent.name] = seat; room.seats.push(seat);
  }

  function screenKinds(teamKey, agent) {
    const head = agent.role === 'head';
    switch (teamKey) {
      case 'creative': return head ? ['timeline', 'timeline'] : [agent.name === 'thumbnail-designer' ? 'products' : 'captions'];
      case 'shop': return head ? ['products', 'chart'] : ['chart'];
      case 'analytics': return head ? ['chart', 'chart'] : ['chart'];
      case 'dev': return head ? ['code', 'chart'] : ['code'];
      case 'social': return head ? ['chart', 'text'] : ['text'];
      case 'inbox': return head ? ['text', 'text'] : ['text'];
      case 'scripts': return head ? ['text', 'code'] : ['text'];
      default: return head ? ['code', 'chart'] : ['code'];
    }
  }

  // ------------------------------------------------------------------ characters
  function lookFor(agent, team) {
    const h = hash(agent.name), base = LOOKS[agent.name] || {};
    const accent = team ? col(team.accent || team.color).getHex() : 0x8569db;
    return {
      skin: base.skin || SKINS[h % SKINS.length],
      hair: base.hair || HAIRS[(h >>> 3) % HAIRS.length],
      style: base.style || STYLES[(h >>> 6) % STYLES.length],
      hat: base.hat || [0x2a2a2e, 0xd63a3a, 0x3fbf6a, 0xf2f2f2][(h >>> 9) % 4],
      shirt: base.shirt || ((h >>> 12) % 3 === 0 ? [0xe8e8e8, 0x465364, 0x54c9a6][(h >>> 14) % 3] : accent),
      phones: base.phones || null,
      glasses: !!base.glasses,
      trousers: 0x2b3350,
    };
  }

  // A chibi figure: rounded head with a hair cap, box torso, two-segment legs, arms hanging from the shoulders.
  // Origin at the feet. Faces +z. opts.seated poses it on a chair; opts.ghost makes the white translucent sub-agent.
  // Every rigid piece (head, torso, each arm, each thigh, each shin with its shoe) is ONE merged vertex-coloured mesh,
  // so a character costs 8 draw calls instead of ~20; the pivots (hips, knees, arms, head) still animate.
  const charMat = new THREE.MeshLambertMaterial({ vertexColors: true });
  const CG = {
    band: new THREE.TorusGeometry(0.64, 0.06, 6, 24, Math.PI).toNonIndexed(),
    glass: new THREE.TorusGeometry(0.16, 0.025, 6, 16).toNonIndexed(),
    sphere: new THREE.SphereGeometry(1, 10, 8).toNonIndexed(),
    cyl: new THREE.CylinderGeometry(1, 1, 1, 18).toNonIndexed(),
  };
  function makeCharacter(look, opts) {
    opts = opts || {};
    const group = new THREE.Group(), mats = [];
    const material = opts.ghost ? new THREE.MeshLambertMaterial({ vertexColors: true, emissive: 0xdcd6ff, emissiveIntensity: 0.9, transparent: true, opacity: 0.6 }) : charMat;
    if (opts.ghost) mats.push(material);
    const pieces = {};
    const add = (name, geo, hex, x, y, z, o) => (pieces[name] || (pieces[name] = new Merger(material))).add(geo, hex, x, y, z, o);
    const parts = {};
    // legs: hip pivots with thigh + knee pivot with shin and shoe
    for (const side of [-1, 1]) {
      const s = side < 0 ? 'L' : 'R';
      const hip = new THREE.Group(); hip.position.set(side * 0.27, 1.05, 0); group.add(hip);
      add('hip' + s, rbox(0.42, 0.56, 0.42, 0.12), look.trousers, 0, -0.28, 0);
      const knee = new THREE.Group(); knee.position.set(0, -0.55, 0); hip.add(knee);
      add('knee' + s, rbox(0.4, 0.5, 0.4, 0.12), look.trousers, 0, -0.25, 0);
      add('knee' + s, rbox(0.46, 0.22, 0.62, 0.1), 0xe4e4e4, 0, -0.44, 0.08);
      parts['hip' + s] = hip; parts['knee' + s] = knee;
    }
    add('torso', rbox(1.15, 1.25, 0.72, 0.22), look.shirt, 0, 1.62, 0);
    if (opts.head && !opts.ghost) add('torso', rbox(0.26, 0.3, 0.06, 0.04), 0xf5c542, 0.32, 1.95, 0.38);   // the lead badge
    if (opts.tablet) { add('torso', rbox(0.9, 0.62, 0.05, 0.03), 0x3a3f4a, 0, 1.75, 0.95, { rx: -0.5 }); parts.tablet = true; }
    for (const side of [-1, 1]) {
      const s = side < 0 ? 'L' : 'R';
      const arm = new THREE.Group(); arm.position.set(side * 0.73, 2.12, 0); group.add(arm);
      add('arm' + s, rbox(0.3, 1.05, 0.3, 0.14), look.shirt, 0, -0.5, 0);
      add('arm' + s, CG.sphere, look.skin, 0, -1.05, 0, { sx: 0.17, sy: 0.17, sz: 0.17 });
      parts['arm' + s] = arm;
    }
    // head pivot at the neck: skull, eyes, hair or hat, headphones, glasses
    const head = new THREE.Group(); head.position.set(0, 2.3, 0); group.add(head); parts.head = head;
    add('head', rbox(1.15, 1.05, 1.1, 0.3), look.skin, 0, 0.6, 0);
    add('head', rbox(0.12, 0.14, 0.05, 0.02), 0x2a2228, -0.22, 0.6, 0.55); add('head', rbox(0.12, 0.14, 0.05, 0.02), 0x2a2228, 0.22, 0.6, 0.55);
    const st = look.style;
    if (st === 'cap' || (opts.head && !look.phones && st !== 'beanie')) {
      add('head', rbox(1.2, 0.42, 1.14, 0.28), look.hair, 0, 0.92, -0.02);
      add('head', CG.cyl, look.hat, 0, 1.12, 0, { sx: 0.61, sy: 0.34, sz: 0.61 });
      add('head', rbox(0.74, 0.07, 0.5, 0.03), look.hat, 0, 1.0, 0.62);
    } else if (st === 'beanie') {
      add('head', rbox(1.22, 0.7, 1.16, 0.36), look.hat, 0, 0.98, 0);
    } else {
      add('head', rbox(1.2, 0.48, 1.14, 0.26), look.hair, 0, 0.93, -0.03);
      if (st === 'bob' || st === 'long') add('head', rbox(1.24, 0.9, 0.95, 0.25), look.hair, 0, 0.6, -0.22);
      if (st === 'long') add('head', rbox(0.95, 0.9, 0.3, 0.12), look.hair, 0, 0.1, -0.5);
      if (st === 'bun') add('head', CG.sphere, look.hair, 0, 1.1, -0.45, { sx: 0.28, sy: 0.28, sz: 0.28 });
    }
    if (look.phones) {
      add('head', CG.band, look.phones, 0, 0.6, 0);
      for (const side of [-1, 1]) add('head', CG.cyl, look.phones, side * 0.62, 0.55, 0, { sx: 0.22, sy: 0.14, sz: 0.22, rz: Math.PI / 2 });
    }
    if (look.glasses) for (const side of [-1, 1]) add('head', CG.glass, 0x1d1b22, side * 0.22, 0.6, 0.57);
    // one mesh per piece, attached to its pivot
    const owner = { head, torso: group, armL: parts.armL, armR: parts.armR, hipL: parts.hipL, hipR: parts.hipR, kneeL: parts.kneeL, kneeR: parts.kneeR };
    for (const name in pieces) { const m = pieces[name].mesh(); m.matrixAutoUpdate = true; owner[name].add(m); if (name === 'torso') parts.torso = m; }
    const ch = { group, parts, mats, look, seated: !!opts.seated };
    if (opts.seated) poseSeated(parts); else poseStand(parts);
    return ch;
  }
  function poseSeated(p) {
    const lift = 0.1;                                                        // the chair seat is slightly higher than the hips of a standing figure
    for (const k of ['torso', 'head', 'armL', 'armR', 'hipL', 'hipR']) p[k].position.y += lift;
    p.hipL.rotation.x = -Math.PI / 2 + 0.05; p.hipR.rotation.x = -Math.PI / 2 + 0.05;
    p.kneeL.rotation.x = Math.PI / 2 - 0.1; p.kneeR.rotation.x = Math.PI / 2 - 0.1;
    p.armL.rotation.x = -1.45; p.armR.rotation.x = -1.45;
  }
  function poseStand(p) {
    p.hipL.rotation.x = p.hipR.rotation.x = 0; p.kneeL.rotation.x = p.kneeR.rotation.x = 0; p.armL.rotation.x = p.armR.rotation.x = 0;
  }

  // ------------------------------------------------------------------ walkways, wires, walkers, particles
  const particleSets = { walk: [], wire: [], rider: [], orbit: [], rise: [] };
  function buildPaths() {
    const paths = new Merger(new THREE.MeshLambertMaterial({ vertexColors: true }));
    const strip = (a, b, w, color, y) => {
      const d = new THREE.Vector3().subVectors(b, a), len = d.length(), mid = new THREE.Vector3().addVectors(a, b).multiplyScalar(0.5);
      paths.box(w, 0.35, len, mid.x, (y || WALK_Y) - 0.175, mid.z, color, { ry: Math.atan2(d.x, d.z) });
      return { a, b, len, dir: d.normalize() };
    };
    for (const room of state.roomList) {
      const a = room.dir.clone().multiplyScalar(PLATFORM_R - 1.5), b = room.dir.clone().multiplyScalar(room.center.length() - room.near + 1.2);
      a.y = b.y = 0;
      const p = strip(a, b, WALK_W, 0x343844); room.path = p;
      // dashed centre line
      const holder = new THREE.Group(); holder.position.copy(a).add(b).multiplyScalar(0.5); holder.position.y = WALK_Y + 0.01; holder.rotation.y = Math.atan2(p.dir.x, p.dir.z); scene.add(holder);
      const tex = dashTex.clone(); tex.needsUpdate = true; tex.repeat.set(1, p.len / 2.6);
      const line = new THREE.Mesh(new THREE.PlaneGeometry(0.32, p.len), new THREE.MeshBasicMaterial({ map: tex, color: 0xd8d2b4, transparent: true, opacity: 0.8, depthWrite: false })); line.rotation.x = -Math.PI / 2; holder.add(line);
      for (let k = 0; k < 3; k++) particleSets.walk.push({ path: p, k, side: k % 2 ? 1 : -1 });
      // data wire from the back corner of the room up to the Brain sphere
      const corner = new THREE.Vector3(room.center.x - room.half + 0.3, SLAB_H + WALL_H + 1.4, room.center.z - room.half + 0.3);
      const curve = new THREE.QuadraticBezierCurve3(corner, new THREE.Vector3(corner.x * 0.45, CORE_Y + 16, corner.z * 0.45), new THREE.Vector3(0, CORE_Y, 0));
      const wire = new THREE.Line(new THREE.BufferGeometry().setFromPoints(curve.getPoints(48)), new THREE.LineBasicMaterial({ color: mix(room.team.accent || room.color, 0xffffff, 0.25), transparent: true, opacity: 0.55 }));
      scene.add(wire); room.wire = curve;
      for (let k = 0; k < 5; k++) particleSets.wire.push({ curve, k });
      // a thin straight floor line from the room's near corner to the platform (the red "laser" of the Shop and friends)
      if (room.key === 'shop' || room.key === 'social') {
        const lg = new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(room.center.x + room.half * 0.6, 0.2, room.center.z + room.half * 0.6), new THREE.Vector3(room.dir.x * PLATFORM_R, 0.6, room.dir.z * PLATFORM_R)]);
        scene.add(new THREE.Line(lg, new THREE.LineBasicMaterial({ color: room.key === 'shop' ? 0xff4d5e : 0xff5fff, transparent: true, opacity: 0.35 })));
      }
    }
    // short links between neighbouring rooms behind Creative
    const link = (k1, k2) => { const r1 = state.rooms[k1], r2 = state.rooms[k2]; if (!r1 || !r2) return; const a = r1.center.clone().lerp(r2.center, 0.32), b = r1.center.clone().lerp(r2.center, 0.68); a.y = b.y = 0; strip(a, b, 2.6, 0x2c303a, WALK_Y - 0.05); };
    link('creative', 'social'); link('creative', 'analytics');
    scene.add(paths.mesh());
    // walkers: one per walkway, two on every third
    state.roomList.forEach((room, i) => {
      const n = i % 3 === 0 ? 2 : 1;
      for (let k = 0; k < n; k++) {
        const r = rng(hash('walker' + i + k));
        const look = { skin: SKINS[Math.floor(r() * SKINS.length)], hair: HAIRS[Math.floor(r() * HAIRS.length)], style: STYLES[Math.floor(r() * STYLES.length)], hat: [0x3fbf6a, 0xd63a3a, 0xf2f2f2][Math.floor(r() * 3)], shirt: [0x3fbf6a, 0xea8a38, 0x75bdd8, 0x54c9a6, 0x465364, 0xef3155, 0x8569db][Math.floor(r() * 7)], trousers: 0x2b3350 };
        const ch = makeCharacter(look, { tablet: r() < 0.6 });
        ch.group.scale.setScalar(CHAR_SCALE); scene.add(ch.group);
        const glow = flatGlow(1.6, 0xffffff, 0.28); scene.add(glow);
        const side = new THREE.Vector3(-room.path.dir.z, 0, room.path.dir.x).multiplyScalar(n === 2 ? (k ? 1 : -1) * 1.0 : 0);
        state.walkers.push({ ch, glow, path: room.path, side, u: r(), sign: r() < 0.5 ? 1 : -1, speed: 1.3 + r() * 0.6, pause: 0, yaw: 0, phase: r() * 6.28 });
      }
    });
    // particles: walkway LEDs, wire sparks, ring riders, the orbit cloud, beam risers (one Points object)
    const r = rng(17);
    for (const ring of anim.rings) for (let k = 0; k < 2; k++) particleSets.rider.push({ ring, a: r() * 6.28, speed: 0.6 + r() * 0.5 });
    for (let k = 0; k < 48; k++) { const n = new THREE.Vector3(r() - 0.5, r() - 0.5, r() - 0.5).normalize(), u = new THREE.Vector3(0, 1, 0).cross(n).normalize(), v = new THREE.Vector3().crossVectors(n, u); particleSets.orbit.push({ u, v, radius: 3.6 + r() * 4.5, phase: r() * 6.28, speed: (0.2 + r() * 0.5) * (r() < 0.5 ? 1 : -1) }); }
    for (let k = 0; k < 18; k++) particleSets.rise.push({ x: (r() - 0.5) * 2.2, z: (r() - 0.5) * 2.2, phase: r(), speed: 0.05 + r() * 0.08 });
    const count = particleSets.walk.length + particleSets.wire.length + particleSets.rider.length + particleSets.orbit.length + particleSets.rise.length;
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.Float32BufferAttribute(new Float32Array(count * 3), 3));
    geo.setAttribute('color', new THREE.Float32BufferAttribute(new Float32Array(count * 3).fill(1), 3));
    anim.particles = new THREE.Points(geo, new THREE.PointsMaterial({ size: 1.25, map: glowTex, vertexColors: true, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, sizeAttenuation: true }));
    anim.particles.frustumCulled = false; scene.add(anim.particles);
  }

  const _a = new THREE.Vector3(), _b = new THREE.Vector3();
  function animateParticles(t) {
    const pos = anim.particles.geometry.attributes.position, colr = anim.particles.geometry.attributes.color;
    let i = 0;
    const put = (x, y, z, bright) => { pos.setXYZ(i, x, y, z); if (bright !== undefined) colr.setXYZ(i, bright, bright, bright); i++; };
    for (const p of particleSets.walk) { const u = 1 - ((t * 0.06 + p.k / 3) % 1); _a.lerpVectors(p.path.a, p.path.b, u); put(_a.x - p.path.dir.z * p.side * 1.7, WALK_Y + 0.25, _a.z + p.path.dir.x * p.side * 1.7, 0.9); }
    for (const p of particleSets.wire) { const u = 1 - ((t * 0.09 + p.k / 5) % 1); p.curve.getPoint(u, _a); put(_a.x, _a.y, _a.z, 1); }
    for (const p of particleSets.rider) { const a = p.a + t * p.speed; _a.set(Math.cos(a) * p.ring.radius, 0, Math.sin(a) * p.ring.radius).applyMatrix4(p.ring.holder.matrixWorld); put(_a.x, _a.y, _a.z, 1); }
    for (const p of particleSets.orbit) { const a = p.phase + t * p.speed; _a.copy(p.u).multiplyScalar(Math.cos(a) * p.radius).addScaledVector(p.v, Math.sin(a) * p.radius); put(_a.x, CORE_Y + _a.y, _a.z, 0.7); }
    for (const p of particleSets.rise) { const u = (p.phase + t * p.speed) % 1; put(p.x, 2.4 + u * 46, p.z, Math.sin(u * Math.PI) * 0.9); }
    pos.needsUpdate = true; colr.needsUpdate = true;
  }

  function animateWalkers(t, dt) {
    for (const w of state.walkers) {
      if (w.pause > 0) w.pause -= dt;
      else { w.u += w.sign * w.speed * dt / w.path.len; if (w.u > 0.74) { w.u = 0.74; w.sign = -1; w.pause = 0.8; } else if (w.u < 0.06) { w.u = 0.06; w.sign = 1; w.pause = 0.8; } }   // turn well before the slab edge so close-ups stay clear
      _a.lerpVectors(w.path.a, w.path.b, w.u).add(w.side);
      w.ch.group.position.set(_a.x, WALK_Y, _a.z);
      w.glow.position.set(_a.x, WALK_Y + 0.02, _a.z);
      const dir = _b.copy(w.path.dir).multiplyScalar(w.sign);
      const target = Math.atan2(dir.x, dir.z);
      let d = target - w.yaw; d = Math.atan2(Math.sin(d), Math.cos(d)); w.yaw += d * Math.min(1, dt * 6);
      w.ch.group.rotation.y = w.yaw;
      const p = w.ch.parts, moving = w.pause <= 0, s = t * 6.5 + w.phase, amp = moving ? 0.5 : 0;
      p.hipL.rotation.x = Math.sin(s) * amp; p.hipR.rotation.x = -Math.sin(s) * amp;
      p.kneeL.rotation.x = Math.max(0, -Math.sin(s)) * amp * 1.2; p.kneeR.rotation.x = Math.max(0, Math.sin(s)) * amp * 1.2;
      if (p.tablet) { p.armL.rotation.x = p.armR.rotation.x = -1.2; } else { p.armL.rotation.x = -Math.sin(s) * amp * 0.7; p.armR.rotation.x = Math.sin(s) * amp * 0.7; }
      w.ch.group.position.y += moving ? Math.abs(Math.sin(s)) * 0.06 : 0;
    }
  }

  // ------------------------------------------------------------------ sub-agents (ghost figures in the bay / open floor)
  function spawnSubagents(teamKey, items) {
    const room = state.rooms[teamKey]; if (!room) return;
    items = Array.isArray(items) ? items : [];
    const keep = new Set(items.map((it) => String(it.id)));
    room.subs.filter((s) => !keep.has(s.id)).forEach((s) => removeSub(room, s));
    const now = performance.now() / 1000;
    items.forEach((it, idx) => {
      const id = String(it.id);
      let sub = room.subs.find((s) => s.id === id);
      const pos = subPosition(room, idx, items.length);
      if (!sub) { sub = createSub(room, id, pos, now, idx); room.subs.push(sub); }
      sub.item = it; sub.target = pos;
      sub.group.position.set(room.center.x + pos.x, SLAB_H, room.center.z + pos.z);
    });
    if (room.decal) room.decal.material.map = room.subs.length ? room.bayTex.plain : room.bayTex.text;
  }
  function clearSubagents(teamKey) { const room = state.rooms[teamKey]; if (!room) return; room.subs.slice().forEach((s) => removeSub(room, s)); if (room.decal) room.decal.material.map = room.bayTex.text; }
  function subPosition(room, idx, n) {
    if (room.bay) { const cols = Math.min(n, 4), row = Math.floor(idx / 4), c = idx % 4; return { x: room.bay.x - (cols - 1) * 3 + c * 6, z: room.bay.z - 1.2 + row * 4.2, desk: true }; }
    return { x: -4.5 + (idx % 4) * 3, z: room.half - 2.2 - Math.floor(idx / 4) * 3, desk: false };
  }
  function createSub(room, id, pos, now, idx) {
    const g = new THREE.Group(); g.position.set(room.center.x + pos.x, SLAB_H, room.center.z + pos.z); scene.add(g);
    const r = rng(hash(room.key + id));
    const look = { skin: SKINS[Math.floor(r() * 3)], hair: [0xeed787, 0xb33a2a, 0xd9c59a][idx % 3], style: ['short', 'bob', 'short'][idx % 3], hat: 0x3fbf6a, shirt: col(room.team.accent || room.color).getHex(), phones: [0x54c9a6, null, 0xe6e6e6][idx % 3], trousers: 0x2b3350 };
    const ch = makeCharacter(look, { seated: pos.desk, ghost: true, tablet: !pos.desk });
    ch.group.rotation.y = Math.PI; ch.group.position.z = pos.desk ? 1.6 : 0; ch.group.scale.setScalar(CHAR_SCALE); g.add(ch.group);
    const hit = new THREE.Mesh(new THREE.BoxGeometry(1.6, 3.8, 1.6), new THREE.MeshBasicMaterial({ visible: false })); hit.position.y = 1.9; hit.userData.agent = 'sub:' + id; ch.group.add(hit); pickables.push(hit);
    let screen = null;
    if (pos.desk) {                                                            // a small white desk with one glowing monitor and a chair
      const props = new Merger(new THREE.MeshLambertMaterial({ vertexColors: true }));
      props.box(3.2, 0.12, 1.5, 0, 1.93, 0, 0xf1ece2); for (const ex of [-1.35, 1.35]) { props.box(0.09, 1.86, 0.09, ex, 0.93, -0.55, 0x151010); props.box(0.09, 1.86, 0.09, ex, 0.93, 0.55, 0x151010); props.box(0.09, 0.09, 1.2, ex, 0.05, 0, 0x151010); }
      props.box(1.35, 0.16, 1.35, 0, 1.18, 1.6, 0x2a2d31); props.box(1.3, 1.3, 0.14, 0, 1.95, 2.24, 0x2a2d31); props.cyl(0.07, 0.9, 0, 0.64, 1.6, 0x3a3d42);
      for (let k = 0; k < 5; k++) { const a = k * 1.2566; props.box(0.95, 0.07, 0.1, Math.cos(a) * 0.44, 0.1, 1.6 + Math.sin(a) * 0.44, 0x1c1e24, { ry: -a }); }
      props.box(1.9, 1.15, 0.07, 0, 2.98, -0.35, 0x181619); props.cyl(0.06, 0.4, 0, 2.2, -0.35, 0x202024);
      g.add(props.mesh());
      screen = new THREE.Mesh(new THREE.PlaneGeometry(1.76, 1.01), new THREE.MeshBasicMaterial({ map: getScreenTex('white') })); screen.position.set(0, 2.98, -0.31); g.add(screen);
    }
    const pool = flatGlow(3.0, 0xffffff, 0.3); pool.position.set(0, 0.03, pos.desk ? 1.6 : 0); g.add(pool);
    const big = flatGlow(6, 0xe4e0ff, 0.22); big.position.set(0, 0.02, pos.desk ? 1.0 : 0); g.add(big);
    const rings = [0, 1].map((k) => { const m = new THREE.Mesh(new THREE.RingGeometry(0.9, 1.05, 48), new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.8, blending: THREE.AdditiveBlending, depthWrite: false })); m.rotation.x = -Math.PI / 2; m.position.set(0, 0.06, pos.desk ? 1.0 : 0); g.add(m); return m; });
    const anchor = makeAnchor('sub', id, ch.group, new THREE.Vector3(0, 4.4, 0));
    g.scale.setScalar(0.01);
    return { id, group: g, ch, screen, pool, big, rings, anchor, born: now + idx * 0.15, item: null, phase: idx * 1.7 };
  }
  function removeSub(room, sub) {
    room.subs.splice(room.subs.indexOf(sub), 1);
    scene.remove(sub.group);
    const i = pickables.findIndex((o) => o.userData.agent === 'sub:' + sub.id); if (i >= 0) pickables.splice(i, 1);
    delete labels.sub[sub.id];
    if (sub.anchor.element.parentNode) sub.anchor.element.parentNode.removeChild(sub.anchor.element);   // the CSS2D element does not leave the DOM on its own
    sub.group.traverse((o) => { if (o.isMesh && o.material && sub.ch.mats.includes(o.material)) o.material.dispose(); });
  }
  function animateSubs(t) {
    const now = performance.now() / 1000;
    for (const room of state.roomList) for (const sub of room.subs) {
      const age = now - sub.born;
      if (age < 0) { sub.group.scale.setScalar(0.01); continue; }
      sub.group.scale.setScalar(0.01 + 0.99 * easeOut(Math.min(1, age / 0.45)));
      const resolve = Math.min(1, Math.max(0, (age - 0.6) / 1.8));               // ghost → nearly solid
      for (const m of sub.ch.mats) { m.opacity = 0.55 + 0.4 * resolve; m.emissiveIntensity = 0.9 - 0.75 * resolve; m.emissive.setHex(0xdcd6ff).lerp(col(0x9a8fd6), resolve); }
      sub.rings.forEach((rm, k) => { const u = ((age * 0.7 + k * 0.5) % 1); rm.scale.setScalar(1 + u * 3.2); rm.material.opacity = (1 - u) * 0.7 * (age < 4 ? 1 : 0.35); });
      sub.big.material.opacity = 0.22 - 0.14 * resolve; sub.pool.material.opacity = 0.3 + Math.sin(t * 3 + sub.phase) * 0.06;
      const p = sub.ch.parts, s = t * 9 + sub.phase;
      if (sub.ch.seated) { p.armL.rotation.x = -1.45 + Math.sin(s) * 0.09; p.armR.rotation.x = -1.45 + Math.cos(s * 1.3) * 0.09; }
      p.head.rotation.y = Math.sin(t * 0.9 + sub.phase) * 0.12; p.head.rotation.x = Math.sin(t * 2.2 + sub.phase) * 0.04;
    }
  }

  // ------------------------------------------------------------------ labels (CSS2D anchors the HUD fills)
  function makeAnchor(kind, key, parent, pos) {
    const el = document.createElement('div');
    el.className = 'hq-label hq-label-' + kind; el.dataset.kind = kind; el.dataset.key = key;
    el.style.pointerEvents = 'none';
    const obj = new THREE.CSS2DObject(el); obj.position.copy(pos); obj.visible = false; parent.add(obj);
    labels[kind][key] = { obj, el, has: false };
    return obj;
  }
  function setLabel(kind, key, html) {
    const L = labels[kind] && labels[kind][key]; if (!L) return false;
    L.el.innerHTML = html == null ? '' : String(html); L.has = !!L.el.innerHTML.trim();
    L.el.style.pointerEvents = L.has ? 'auto' : 'none'; L.obj.visible = L.has; return true;
  }
  const _w = new THREE.Vector3();
  function updateLabels() {
    const maxD = state.labelRules.agentMaxDist;
    for (const kind of ['agent', 'sub']) for (const key in labels[kind]) {
      const L = labels[kind][key]; if (!L.has) { L.obj.visible = false; continue; }
      L.obj.getWorldPosition(_w); L.obj.visible = _w.distanceTo(camera.position) < maxD;
    }
  }
  function project(kind, key) {
    const L = labels[kind] && labels[kind][key];
    if (!L || !camera) return { x: 0, y: 0, visible: false };
    L.obj.getWorldPosition(_w);
    const dist = _w.distanceTo(camera.position);
    _w.project(camera);
    const x = (_w.x + 1) / 2 * state.size.w, y = (1 - _w.y) / 2 * state.size.h;
    const onScreen = _w.z > -1 && _w.z < 1 && x > -200 && x < state.size.w + 200 && y > -200 && y < state.size.h + 200;
    return { x, y, visible: onScreen, dist, near: dist < state.labelRules.agentMaxDist, scale: clamp(OVERVIEW.dist / Math.max(1, dist), 0.6, 2.2) };
  }

  // ------------------------------------------------------------------ camera
  function placeCamera(yaw, pitch, dist, target) {
    camera.position.set(target.x + dist * Math.cos(pitch) * Math.cos(yaw), target.y + dist * Math.sin(pitch), target.z + dist * Math.cos(pitch) * Math.sin(yaw));
    controls.target.copy(target); camera.lookAt(target);
  }
  function currentView() {
    const off = _a.subVectors(camera.position, controls.target), dist = off.length();
    return { yaw: Math.atan2(off.z, off.x), pitch: Math.asin(clamp(off.y / dist, -1, 1)), dist, target: controls.target.clone() };
  }
  function tweenTo(to, dur) {
    const from = currentView();
    let dy = to.yaw - from.yaw; dy = Math.atan2(Math.sin(dy), Math.cos(dy)); to = Object.assign({}, to, { yaw: from.yaw + dy });
    state.tween = { from, to, t0: performance.now(), dur: dur || 900 };
    controls.autoRotate = false;
  }
  function updateCamera(now) {
    const tw = state.tween;
    if (tw) {
      const s = ease(clamp((now - tw.t0) / tw.dur, 0, 1));
      const target = tw.from.target.clone().lerp(tw.to.target, s);
      placeCamera(tw.from.yaw + (tw.to.yaw - tw.from.yaw) * s, tw.from.pitch + (tw.to.pitch - tw.from.pitch) * s, tw.from.dist + (tw.to.dist - tw.from.dist) * s, target);
      if (s >= 1) state.tween = null;
    }
    controls.autoRotate = state.mode === 'overview' && !state.tween && now > state.userActiveUntil;
  }
  // Shift a view target so the framed point lands `shiftX` viewport-widths right of centre (e.g. 0.17 beside a left panel).
  function shiftTarget(target, dist, shiftX) {
    if (!shiftX) return target;
    const width = 2 * dist * Math.tan(camera.fov * DEG / 2) * camera.aspect;
    const right = new THREE.Vector3(Math.sin(OVERVIEW.yaw), 0, -Math.cos(OVERVIEW.yaw));    // screen-right for the standard yaw (forward x up)
    return target.clone().addScaledVector(right, -shiftX * width);
  }
  function flyTo(teamKey, opts) {
    const room = state.rooms[teamKey]; if (!room) return false;
    opts = opts || {};
    state.mode = 'room:' + teamKey;
    const dist = ROOM_VIEW.dist * (room.big ? 1.26 : 1) * (opts.zoom || 1);
    tweenTo({ yaw: OVERVIEW.yaw, pitch: ROOM_VIEW.pitch, dist, target: shiftTarget(new THREE.Vector3(room.center.x, 2.2, room.center.z), dist, opts.shiftX) }, opts.duration || 950);
    return true;
  }
  function overview(opts) { opts = opts || {}; state.mode = 'overview'; tweenTo({ yaw: OVERVIEW.yaw, pitch: OVERVIEW.pitch, dist: OVERVIEW.dist, target: shiftTarget(OVERVIEW.target.clone(), OVERVIEW.dist, opts.shiftX) }, opts.duration || 1100); }
  function focusAgent(name, opts) {
    const seat = state.seats[name]; if (!seat) return false;
    opts = opts || {};
    state.mode = 'agent:' + name; const p = seat.ch.group.position;
    tweenTo({ yaw: OVERVIEW.yaw, pitch: 38 * DEG, dist: 34, target: shiftTarget(new THREE.Vector3(p.x, p.y + 1.8, p.z), 34, opts.shiftX) }, opts.duration || 900);
    return true;
  }
  function focusBrain(opts) { opts = opts || {}; state.mode = 'brain'; tweenTo({ yaw: OVERVIEW.yaw, pitch: 46 * DEG, dist: 62, target: shiftTarget(new THREE.Vector3(0, 4, 0), 62, opts.shiftX) }, opts.duration || 1000); }
  function getZoomPercent() { return Math.round(OVERVIEW.dist / Math.max(1, currentView().dist) * 100); }
  function setZoomPercent(p) { const v = currentView(); p = clamp(+p || 100, 25, 900); tweenTo({ yaw: v.yaw, pitch: v.pitch, dist: OVERVIEW.dist * 100 / p, target: v.target }, 450); if (state.mode === 'overview') state.mode = 'free'; }
  function zoom(delta) { const v = currentView(); tweenTo({ yaw: v.yaw, pitch: v.pitch, dist: clamp(v.dist * Math.pow(0.82, +delta || 0), controls.minDistance, controls.maxDistance), target: v.target }, 400); if (state.mode === 'overview') state.mode = 'free'; }
  function fullscreen() { const el = host.parentElement || host; if (document.fullscreenElement) { document.exitFullscreen && document.exitFullscreen(); } else if (el.requestFullscreen) el.requestFullscreen().catch(() => {}); }
  function select(name) {
    state.selected = name || null;
    if (!state.selectRing) { state.selectRing = new THREE.Mesh(new THREE.RingGeometry(1.1, 1.45, 48), new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.9, blending: THREE.AdditiveBlending, depthWrite: false })); state.selectRing.rotation.x = -Math.PI / 2; scene.add(state.selectRing); }
    const seat = name && state.seats[name];
    state.selectRing.visible = !!seat;
    if (seat) { const p = seat.ch.group.position; state.selectRing.position.set(p.x, SLAB_H + 0.07, p.z); }
  }

  // Minimap state in 0..1 map coordinates (screen-aligned: Research at the top, the Brain in the middle).
  // `view` is the floor area the camera sees (the white viewport rectangle); `camera` is clamped to the map's edge.
  const _ray = new THREE.Raycaster(), _floor = new THREE.Plane(new THREE.Vector3(0, 1, 0), -SLAB_H), _ndc = new THREE.Vector2();
  function minimapState() {
    const E = RING_R + S * 1.15;
    const mapOf = (x, z) => ({ x: 0.5 + ((x - z) * SQ) / (2 * E), y: 0.5 + ((x + z) * SQ) / (2 * E) });
    const v = currentView();
    let view = null;
    const pts = [];
    for (const [nx, ny] of [[-1, 1], [1, 1], [1, -1], [-1, -1]]) {
      _ray.setFromCamera(_ndc.set(nx, ny), camera);
      if (_ray.ray.intersectPlane(_floor, _a)) pts.push(mapOf(_a.x, _a.z));
    }
    if (pts.length === 4) {
      const xs = pts.map((p) => p.x), ys = pts.map((p) => p.y);
      const x0 = clamp(Math.min(...xs), -1, 2), x1 = clamp(Math.max(...xs), -1, 2), y0 = clamp(Math.min(...ys), -1, 2), y1 = clamp(Math.max(...ys), -1, 2);
      view = { x: x0, y: y0, w: x1 - x0, h: y1 - y0, corners: pts };
    }
    const cam = mapOf(camera.position.x, camera.position.z);
    return {
      rooms: state.roomList.map((r) => Object.assign(mapOf(r.center.x, r.center.z), { key: r.key, w: r.size / (2 * E), h: r.size / (2 * E), color: r.color, lit: r.lit })),
      brain: mapOf(0, 0), camera: { x: clamp(cam.x, 0.02, 0.98), y: clamp(cam.y, 0.02, 0.98) }, target: mapOf(v.target.x, v.target.z), view,
      yaw: v.yaw, yawOffset: v.yaw - OVERVIEW.yaw, zoom: getZoomPercent(), mode: state.mode,
    };
  }

  // ------------------------------------------------------------------ picking
  function setupPicking() {
    const el = renderer.domElement, ray = new THREE.Raycaster(); let down = null;
    el.addEventListener('pointerdown', (e) => { down = { x: e.clientX, y: e.clientY, b: e.button }; });
    el.addEventListener('pointerup', (e) => {
      if (!down || down.b !== 0 || Math.abs(e.clientX - down.x) + Math.abs(e.clientY - down.y) > 6) { down = null; return; }
      down = null;
      const r = el.getBoundingClientRect();
      ray.setFromCamera(new THREE.Vector2(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1), camera);
      const hit = ray.intersectObjects(pickables, false)[0]; if (!hit) return;
      const u = hit.object.userData, api = window.HQ_OFFICE;
      if (u.agent) { if (typeof api.onAgentClick === 'function') api.onAgentClick(u.agent); else { select(u.agent); focusAgent(u.agent); } }
      else if (u.room) { if (typeof api.onRoomClick === 'function') api.onRoomClick(u.room); else flyTo(u.room); }
      else if (u.brain) { if (typeof api.onBrainClick === 'function') api.onBrainClick(); else focusBrain(); }
    });
    el.addEventListener('contextmenu', (e) => e.preventDefault());
  }

  // ------------------------------------------------------------------ running state
  function runningMap() {
    const hq = window.HQ;
    if (hq && typeof hq.running === 'function') { try { return hq.running() || {}; } catch (e) { return {}; } }
    return state.fallbackRunning;
  }
  function pollFallback() {                                                   // only while there is no HUD (window.HQ)
    if (window.HQ && typeof window.HQ.running === 'function') return;
    fetch('/api/status').then((r) => r.json()).then((st) => { const out = {}; for (const [k, v] of Object.entries(st.running || {})) if (v > 0) out[k] = true; if (st.desk && st.desk.busy) out['chief of staff'] = 'working'; state.fallbackRunning = out; }).catch(() => {});
  }

  // ------------------------------------------------------------------ the frame
  let lastT = 0;
  function isVisible() { return !document.hidden && host.offsetWidth > 0 && host.offsetHeight > 0 && host.getClientRects().length > 0; }
  function frame() {
    requestAnimationFrame(frame);
    if (!state.built || !isVisible()) return;
    const now = performance.now(), t = clock.getElapsedTime(), dt = Math.min(0.1, t - lastT); lastT = t;
    if (host.clientWidth !== state.size.w || host.clientHeight !== state.size.h) resize();
    updateCamera(now); controls.update();
    const run = runningMap();
    // the Brain
    const chief = !!run['chief of staff'];
    anim.brain.core.material.emissiveIntensity = 0.3 + Math.sin(t * (chief ? 4 : 1.4)) * (chief ? 0.14 : 0.05);
    anim.brain.glow.material.opacity = 0.12 + Math.sin(t * 1.4) * 0.03 + (chief ? 0.08 : 0);
    anim.brain.light.intensity = 0.75 + Math.sin(t * 1.4) * 0.15;
    anim.brain.lattice.rotation.y = t * 0.05;
    // the beam fades while the camera is close to a room so it never washes out a close-up
    const near = clamp((currentView().dist - 80) / 60, 0, 1);
    anim.brain.beam.material.opacity = 0.85 * near; anim.brain.beam.visible = anim.brain.halo.visible = near > 0.02; anim.brain.halo.material.opacity = 0.07 * near; anim.brain.glow.material.opacity *= 0.5 + 0.5 * near;
    const neon = 0.88 + Math.sin(t * 1.1) * 0.12; anim.brain.neon.forEach((m, k) => m.material.color.setRGB(0.78 * neon, 0.96 * neon, 1 * neon));
    for (const r of anim.rings) r.holder.rotation.y = r.phase + t * r.speed;
    anim.dust.rotation.y = t * 0.004;
    animateParticles(t);
    // rooms: dashboards, crawlers
    for (const room of state.roomList) room.lit = room.seats.some((s) => !!run[s.agent.name]) || room.subs.length > 0;
    for (const d of anim.dashboards) { const lit = state.rooms[d.team].lit; const b = lit ? 0.95 + Math.sin(t * 4) * 0.25 : 0.82; d.mesh.material.color.setScalar(b); }
    for (const c of anim.crawlers) { if (c.orb) { c.mesh.position.y = c.base.y + Math.sin(t * 0.8) * 0.4; c.mesh.position.x = c.base.x + Math.sin(t * 0.5) * 0.6; } else c.mesh.material.opacity = 0.25 + 0.65 * (0.5 + 0.5 * Math.sin(t * 2.2 + c.phase)); }
    // seated agents
    for (const name in state.seats) {
      const seat = state.seats[name], on = !!run[name], p = seat.ch.parts, ph = seat.phase;
      if (on) {
        const s = t * 9 + ph;
        p.armL.rotation.x = -1.45 + Math.sin(s) * 0.1; p.armR.rotation.x = -1.45 + Math.cos(s * 1.3) * 0.1;
        p.head.rotation.x = Math.sin(t * 2.4 + ph) * 0.06; p.head.rotation.y = Math.sin(t * 1.1 + ph) * 0.18;
        seat.ring.material.opacity = 0.35 + Math.sin(t * 3 + ph) * 0.2; seat.ring.scale.setScalar(1 + Math.sin(t * 3 + ph) * 0.08);
        seat.pool.material.opacity = 0.3 + Math.sin(t * 3 + ph) * 0.08;
        const sb = 1.25 + Math.sin(t * 5 + ph) * 0.12; for (const m of seat.screens) m.color.setScalar(sb);
      } else {
        p.armL.rotation.x = -1.45; p.armR.rotation.x = -1.45;
        p.head.rotation.x = Math.sin(t * 0.7 + ph) * 0.02; p.head.rotation.y = Math.sin(t * 0.3 + ph) * 0.09;
        seat.ring.material.opacity = 0; seat.pool.material.opacity = 0.09;
        for (const m of seat.screens) m.color.setScalar(0.8);
      }
      seat.ch.group.position.y = seat.ch.baseY + Math.sin(t * (on ? 4 : 1.2) + ph) * (on ? 0.03 : 0.015);
      seat.running = on;
    }
    animateWalkers(t, dt); animateSubs(t); updateLabels();
    if (state.selectRing && state.selectRing.visible) state.selectRing.material.opacity = 0.6 + Math.sin(t * 4) * 0.3;
    composer.render();
    css.render(scene, camera);
  }

  // ------------------------------------------------------------------ data and boot
  function ensureExamples(done) {
    const needed = [['CopyShader', 'CopyShader'], ['LuminosityHighPassShader', 'LuminosityHighPassShader'], ['EffectComposer', 'EffectComposer'], ['RenderPass', 'RenderPass'], ['ShaderPass', 'ShaderPass'], ['UnrealBloomPass', 'UnrealBloomPass'], ['RoundedBoxGeometry', 'RoundedBoxGeometry'], ['CSS2DRenderer', 'CSS2DRenderer'], ['OrbitControls', 'OrbitControls']];
    const missing = needed.filter(([g]) => !THREE[g]);
    const base = (document.currentScript && document.currentScript.src) ? document.currentScript.src.replace(/[^/]*$/, '') : '/';
    (function next(i) {
      if (i >= missing.length) return done();
      const s = document.createElement('script'); s.src = base + 'vendor/three-examples/' + missing[i][1] + '.js'; s.onload = () => next(i + 1); s.onerror = () => next(i + 1); document.head.appendChild(s);
    })(0);
  }
  const getJSON = (url) => fetch(url).then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); });

  function build(teams, agents) {
    state.teams = teams; state.agents = agents;
    buildBrain();
    teams.forEach((team, i) => buildRoom(team, i, agents.filter((a) => a.teamKey === team.key || a.team === team.name)));
    buildPaths();
    state.built = true;
    placeCamera(OVERVIEW.yaw, OVERVIEW.pitch, OVERVIEW.dist, OVERVIEW.target);
    state.userActiveUntil = performance.now() + 5000;
    window.HQ_OFFICE.ready = true;
    window.dispatchEvent(new CustomEvent('hq-office-ready'));
  }

  // The public API exists from load; calls made before the scene is built are safe no-ops.
  const api = window.HQ_OFFICE = Object.assign(window.HQ_OFFICE || {}, {
    ready: false,
    flyTo: (k, o) => state.built && flyTo(k, o), overview: (o) => state.built && overview(o), select: (n) => state.built && select(n), focusAgent: (n, o) => state.built && focusAgent(n, o), focusBrain: (o) => state.built && focusBrain(o),
    project, setLabel, spawnSubagents: (k, items) => state.built && spawnSubagents(k, items), clearSubagents: (k) => state.built && clearSubagents(k),
    zoom: (d) => state.built && zoom(d), setZoomPercent: (p) => state.built && setZoomPercent(p), getZoomPercent: () => (state.built ? getZoomPercent() : 100),
    fullscreen, resize, minimapState: () => (state.built ? minimapState() : { rooms: [], brain: { x: 0.5, y: 0.5 }, camera: { x: 0.5, y: 0.5 }, target: { x: 0.5, y: 0.5 }, zoom: 100 }),
    bloom: (strength, threshold, radius) => { if (!bloomPass) return; if (strength != null) bloomPass.strength = +strength; if (threshold != null) bloomPass.threshold = +threshold; if (radius != null) bloomPass.radius = +radius; return { strength: bloomPass.strength, threshold: bloomPass.threshold, radius: bloomPass.radius }; },
    labelRules: (rules) => Object.assign(state.labelRules, rules || {}),
    teams: () => state.teams, agents: () => state.agents, rooms: () => state.roomList.map((r) => ({ key: r.key, center: r.center.clone(), size: r.size })),
    _three: () => ({ scene, camera, renderer, composer, controls, state }),
  });
  if (!('onRoomClick' in api)) api.onRoomClick = null;
  if (!('onAgentClick' in api)) api.onAgentClick = null;
  if (!('onBrainClick' in api)) api.onBrainClick = null;

  ensureExamples(() => {
    setupRenderer();
    requestAnimationFrame(frame);
    Promise.all([
      getJSON('/api/teams').then((d) => (d.teams && d.teams.length ? d.teams : FALLBACK_TEAMS)).catch(() => FALLBACK_TEAMS),
      getJSON('/api/agents').then((d) => d.agents || []).catch(() => []),
    ]).then(([teams, agents]) => {
      if (!agents.length) agents = FALLBACK_TEAMS.map((t) => ({ name: t.lead, label: t.lead, team: t.name, teamKey: t.key, role: 'head' }));
      build(teams, agents);
      pollFallback(); setInterval(pollFallback, 6000);
    }).catch((e) => { console.error('office3d: could not build the office', e); });
  });
})();
