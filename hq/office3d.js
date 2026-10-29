// Agents HQ: the 3D office (hq/office3d.js). Built on Three.js r128 (hq/vendor/three.min.js) and the vendored UMD
// examples (EffectComposer, UnrealBloomPass, RoundedBoxGeometry, CSS2DRenderer, OrbitControls).
//
// The Tower: a glass office tower seen from the front at night, a city skyline behind it. Ground: the lobby with the
// reception, the canteen + kitchen and the lounge. Floors 1-4: two team rooms each (floor, carpet, two back walls, trims,
// desks, monitors, dashboards, lamps, shelves, plants, sofas) with glass meeting rooms and nooks at the ends. The roof:
// a terrace under a pergola, the game room and a coffee bar. Spiral stairs and a glass lift join the floors. In the plaza
// out front the Brain glows in a fountain (round platform, neon rings, a light beam, orbit rings, water jets); data wires
// with travelling sparks run from every room to it. Chibi characters work, climb the stairs, take breaks and drop notes
// that fly out to the Brain; ghost sub-agents; bloom on everything that glows.
// The interface follows docs/build-contract.md: window.HQ_OFFICE (flyTo, overview, select, focusAgent, project,
// setLabel, spawnSubagents, clearSubagents, zoom, setZoomPercent, getZoomPercent, fullscreen, resize, minimapState,
// onRoomClick / onAgentClick / onBrainClick), plus focusBrain(), showFloor(n|null) / floorView() / floors(),
// bloom(strength, threshold, radius) and an optional
// options object on flyTo / overview / focusAgent / focusBrain: { shiftX: 0.17 } moves the framed point right by that
// fraction of the viewport (room beside an open left panel), { duration, zoom } tune the move. No text is drawn in the
// scene for names: the HUD fills the CSS2D label elements through setLabel(kind, key, html) or positions its own
// elements from project(kind, key). The running state comes from window.HQ.running() every frame.
// Office life (the section of that name): idle agents stretch, fetch coffee, take calls, chat, visit other teams to
// share lessons from GET /api/chatter and drop notes into the Brain; a working agent hurries back to its desk. Speech
// bubbles are CSS2D labels of kind 'bubble'. API: life(on|off) → on, lifeOf(name) → { action, partner, talking, topic }
// or null, lifeTalkers() → { name: true } of agents mid-conversation, lifeState(), lifeDebug({ speed, force: 'visit'|'coffee'|'phone'|'stretch'|'chat'|'note', agent, to, with,
// graph, auto }), and the HUD callback onLife(event) ({ type: 'tip', from, fromKey, to, toKey, text, visitor, host }).
(() => {
  'use strict';
  const host = document.getElementById('office3d');
  if (!host || typeof THREE === 'undefined') return;

  // ------------------------------------------------------------------ constants
  const S = 20;                                  // room side in world units
  const WALL_H = 9.4, WALL_T = 0.45, SLAB_H = 0.7;
  const PLATFORM_R = 17;                         // the Brain platform
  const GROUND_Y = -0.05;                        // street level
  const WALK_W = 4.2, WALK_Y = 0.45;             // walkway width and top height
  const CORE_Y = 9.5;                            // the Brain sphere height
  const SQ = Math.SQRT1_2;
  const DEG = Math.PI / 180;
  const OVERVIEW = { yaw: 82 * DEG, pitch: 10 * DEG, dist: 220, target: new THREE.Vector3(0, 40, 8) };   // from the plaza, a little to the right
  const ROOM_VIEW = { pitch: 15 * DEG, dist: 64 };
  const CHAR_SCALE = 1.22;                       // characters are ~1.6 desk-heights tall in the video
  // The Tower. Floor f stands at y = f * FLOOR_H; floor 0 is the lobby, FLOORS - 1 the roof. Each team floor holds two
  // rooms, slot 0 on the left (x = -ROOM_X) and slot 1 on the right, backs to the building's back wall; a corridor runs
  // along the glass front (z = CZ); the core between the rooms has the spiral stairs and the lift.
  const FLOOR_H = 15, FLOORS = 8, ROOF = FLOORS - 1, HALL = 6;   // lobby, 5 team floors (the top one holds Design), the Meeting Hall, roof
  const WX = 60, DZ = 16;                        // half the building's width and depth
  const ROOM_X = 30, CZ = 13.5;                  // the rooms' centre offset; the corridor line along the front
  const STAIR = { x: -6, z: -6, r: 3, hole: 4.2 };   // the spiral stairs (and the opening in each floor above them)
  const LIFT = { x: 8, z: -10, r: 2.2 };         // the glass lift (lobby to the top team floor)
  const BRAIN = new THREE.Vector3(0, 0, 50);     // the fountain in the plaza
  const FLOOR_PLAN = { research: [1, 0], analytics: [1, 1], dev: [2, 0], inbox: [2, 1], scripts: [3, 0], shop: [3, 1], creative: [4, 0], social: [4, 1], design: [5, 0] };
  const FLOOR_NAMES = ['Ground · Lobby & canteen', '1F', '2F', '3F', '4F', '5F · Design', '6F · Meeting Hall', 'Roof · Terrace & game room'];
  const FLOOR_SHORT = ['G', '1F', '2F', '3F', '4F', '5F', '6F', 'R'];
  // Phones (the same query as hud.css): a lower pixel ratio, half-resolution bloom (dropped if the frame rate sags),
  // fewer particles, portrait framing that fits the ring of rooms by width, double-tap on a room. Desktop is untouched.
  // ?fx=low forces the light path, ?fx=full keeps the full one on a phone.
  const PHONE_Q = '(max-width: 600px), (max-height: 500px) and (max-width: 1000px)';
  const isPhone = () => !!(window.matchMedia && window.matchMedia(PHONE_Q).matches);
  const FX = (/[?&]fx=(low|full)\b/.exec(location.search) || [])[1] || '';
  const PHONE_AT_BOOT = isPhone();
  const DESKTOP_PITCH = 9 * DEG, PORTRAIT_PITCH = 11 * DEG;    // almost level: looking in through the glass front

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
    phone: PHONE_AT_BOOT, lowFx: FX === 'low', fit: 1, fitBrain: 1, paused: false, perf: { n: 0, sum: 0, t0: 0 },
    floors: [], floorView: null, commons: [], lift: null, people: null, wires: [],
  };
  const floorOfY = (y) => clamp(Math.floor((y + 3) / FLOOR_H), 0, FLOORS - 1);
  const floorShown = () => true;                                              // the glass front shows every floor at once
  // The floor the camera is about (a room, a floor view, the Brain, an agent), or null in the overview. Labels (room
  // cards, names, bubbles) show only for that floor, so cards from the floor below never sit on top of a close-up.
  function focusFloor() {
    const m = state.mode || '';
    if (m.startsWith('room:')) { const r = state.rooms[m.slice(5)]; return r ? r.floor : null; }
    if (m.startsWith('floor:')) return +m.slice(6);
    if (m === 'brain') return 0;
    if (m.startsWith('agent:')) { const st = state.seats[m.slice(6)]; return st ? floorOfY(st.ch.group.position.y) : null; }
    return null;
  }
  const labelShown = (f) => { const ff = focusFloor(); return ff == null || f === ff; };
  const TOP_Y = FLOORS * FLOOR_H;
  const maxPixelRatio = () => Math.min(state.phone ? (state.lowFx ? 1 : 1.25) : 1.5, window.devicePixelRatio || 1);
  const labels = { team: {}, agent: {}, brain: {}, sub: {}, bubble: {} };
  const pickables = [];
  const anim = { dashboards: [], crawlers: [], glows: [], particles: null, rings: [], brain: {}, dust: null };

  function setupRenderer() {
    renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false, powerPreference: 'high-performance' });
    renderer.setPixelRatio(maxPixelRatio());
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
    controls.minPolarAngle = 0.35; controls.maxPolarAngle = 1.52;
    controls.minAzimuthAngle = -1.15; controls.maxAzimuthAngle = 1.15;   // look around the front, never from behind the tower
    controls.autoRotateSpeed = 0;                                         // no drift: the tower faces you
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
    for (let i = 0; i < (PHONE_AT_BOOT ? 220 : 520); i++) { const a = r() * Math.PI * 2, d = 12 + Math.sqrt(r()) * 250; dust.push(Math.cos(a) * d, GROUND_Y + 0.15 + (i % 5 === 0 ? r() * 40 : 0), Math.sin(a) * d); }
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
    state.phone = isPhone();
    const pr = maxPixelRatio();
    if (renderer.getPixelRatio() !== pr) { renderer.setPixelRatio(pr); if (composer.setPixelRatio) composer.setPixelRatio(pr); }
    renderer.setSize(w, h); composer.setSize(w, h); css.setSize(w, h);
    if (state.phone) bloomPass.setSize(Math.round(w * pr * 0.5), Math.round(h * pr * 0.5));   // half-resolution bloom on a phone
    bloomPass.enabled = !state.lowFx;
    camera.aspect = w / h; camera.updateProjectionMatrix();
    // The overview frames the tower from the plaza: its full height with a little of the plaza below; a portrait screen
    // fits the height and crops the sides (pan to see the ends), a landscape one fits the width too.
    const portrait = camera.aspect < 0.95;
    OVERVIEW.pitch = portrait ? PORTRAIT_PITCH : DESKTOP_PITCH;
    const hfov = 2 * Math.atan(Math.tan(camera.fov * DEG / 2) * camera.aspect);
    const tanH = Math.tan(hfov / 2), tanV = Math.tan(camera.fov * DEG / 2), H = FLOORS * FLOOR_H;
    const dh = (WX + 12) / tanH, dv = (H * 0.5 + 14) / tanV;
    OVERVIEW.dist = portrait ? Math.max(dv, (WX * 0.8) / tanH) : Math.max(dh, dv);
    OVERVIEW.target.set(0, H * 0.43, DZ);
    state.fit = portrait ? Math.max(1, (S * 0.8) / tanH / ROOM_VIEW.dist) : 1;
    state.fitBrain = portrait ? Math.max(1, (PLATFORM_R + 6) / tanH / 62) : 1;
    controls.maxDistance = Math.max(360, OVERVIEW.dist * 1.5);
    if (state.mode === 'overview' && !state.tween) placeCamera(OVERVIEW.yaw, OVERVIEW.pitch, OVERVIEW.dist, OVERVIEW.target);
  }

  // ------------------------------------------------------------------ the Brain
  function buildBrain() {
    const g = new THREE.Group(); g.position.copy(BRAIN); scene.add(g);
    anim.brain.light.position.set(BRAIN.x, CORE_Y + 3.5, BRAIN.z);
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
    for (let i = 0; i < 7; i++) { const a = r() * 6.28; pts.push(0, CORE_Y, 0, Math.cos(a) * 60, CORE_Y + 30 + r() * 60, Math.sin(a) * 60); }
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

  function buildRoom(team, i, members, floor) {
    const big = team.key === 'creative';
    const size = big ? S * 1.4 : S, h = size / 2;
    const dir = new THREE.Vector3(0, 0, 1);
    const cx = (i ? 1 : -1) * ROOM_X, cz = big ? -DZ + h : -DZ + 2 + h, Y = floor * FLOOR_H;
    const realScene = scene; scene = state.floors[floor];                     // everything this room adds hides with its floor
    const floorC = col(team.color), carpetC = col(team.color_light), wallC = col(team.color_wall).multiplyScalar(1.3), accentC = col(team.accent || team.color);
    const trimC = mix(accentC, 0xffffff, 0.35), topTrimC = mix(wallC, 0xffffff, 0.25);
    const hasSofa = ['inbox', 'social', 'analytics'].includes(team.key);
    const room = { key: team.key, team, index: i, floor, y: Y, center: new THREE.Vector3(cx, Y, cz), size, half: h, dir, color: team.color, members, seats: [], subs: [], lit: false, big };
    room.near = h / Math.max(Math.abs(dir.x), Math.abs(dir.z));            // distance from the centre to the slab edge toward the Brain
    const F = Y + SLAB_H;                                                      // floor top
    const shell = new Merger(new THREE.MeshPhongMaterial({ vertexColors: true, shininess: 14, specular: 0x202024 }));
    const props = new Merger(new THREE.MeshLambertMaterial({ vertexColors: true }));
    const glow = new Merger(new THREE.MeshBasicMaterial({ vertexColors: true }));

    // slab, two back walls (inner faces catch the key light), top trims, edge trims, the corner post, the carpet
    shell.box(size, SLAB_H, size, cx, Y + SLAB_H / 2, cz, floorC);
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
      addSeat(room, agent, slot, props, cx, cz, k === 0 && head === agent, order[k % order.length]);
    });
    // merged meshes
    const shellMesh = shell.mesh(); shellMesh.userData.room = team.key; scene.add(shellMesh); pickables.push(shellMesh);
    scene.add(props.mesh()); scene.add(glow.mesh());
    // the team label above the back corner
    makeAnchor('team', team.key, scene, new THREE.Vector3(cx - h + 0.3, F + WALL_H + 1.4, cz - h + 0.3));   // under the ceiling, over the back corner
    state.rooms[team.key] = room; state.roomList.push(room);
    scene = realScene;
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
  function addSeat(room, agent, slot, props, cx, cz, isHead, slotKey) {
    const F = room.y + SLAB_H, rot = slot[2];
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
    const seat = { agent, room, ch, screens, pool, ring, anchor, phase: hash(agent.name) % 100 / 10, running: false, unit, slotKey: slotKey || 'A', life: null };
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

  // ------------------------------------------------------------------ the tower: floors, glass front, stairs, lift, wires
  const particleSets = { wire: [], rider: [], orbit: [], rise: [], jet: [] };
  const glassMat = new THREE.MeshBasicMaterial({ color: 0x9fd8ff, transparent: true, opacity: 0.07, depthWrite: false, side: THREE.DoubleSide });
  function glassBox(parent, w, h, d, x, y, z, edges) {
    const m = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), glassMat); m.position.set(x, y, z); m.renderOrder = 3; parent.add(m);
    if (edges !== false) { const e = new THREE.LineSegments(new THREE.EdgesGeometry(m.geometry), new THREE.LineBasicMaterial({ color: 0xbfe9ff, transparent: true, opacity: 0.32 })); e.position.copy(m.position); parent.add(e); }
    return m;
  }
  const tree = (M, x, y, z, k) => { M.cyl(0.6 * k, 1.0 * k, x, y + 0.5 * k, z, 0xd3d7ce); M.cyl(0.14 * k, 2.6 * k, x, y + 2.2 * k, z, 0x6b4a2e); M.ball(1.6 * k, x, y + 4.0 * k, z, 0x3f9e64); M.ball(1.2 * k, x + 0.8 * k, y + 4.7 * k, z + 0.3 * k, 0x52a775); M.ball(1.1 * k, x - 0.7 * k, y + 4.8 * k, z - 0.4 * k, 0x5db87c); };
  const sofa = (M, x, y, z, w, c, rot) => { M.box(w, 0.7, 1.7, x, y + 0.45, z, c, { ry: rot || 0 }); M.box(w, 1.0, 0.45, x - Math.sin(rot || 0) * 0.65, y + 1.15, z - Math.cos(rot || 0) * 0.65, c, { ry: rot || 0 }); };
  function buildPaths() {
    for (let f = 0; f < FLOORS; f++) {
      const g = state.floors[f], Y = f * FLOOR_H, top = Y + WALK_Y, th = 0.9, cy = top - th / 2, roof = f === ROOF, inner = FLOOR_H - th;
      const M = new Merger(new THREE.MeshPhongMaterial({ vertexColors: true, shininess: 18, specular: 0x23262e }));
      const GL = new Merger(new THREE.MeshBasicMaterial({ vertexColors: true }));
      const floorC = f === 0 ? 0xe9e2d6 : roof ? 0x8a8f9c : 0xdcc7a4;               // light oak floors, a pale stone lobby
      // the floor plate, open over the spiral stairs coming up from the floor below
      if (!f) M.box(2 * WX, th, 2 * DZ, 0, cy, 0, floorC);
      else {
        const H = STAIR.hole, x0 = STAIR.x - H, x1 = STAIR.x + H, z0 = STAIR.z - H, z1 = STAIR.z + H;
        M.box(x0 + WX, th, 2 * DZ, (-WX + x0) / 2, cy, 0, floorC); M.box(WX - x1, th, 2 * DZ, (x1 + WX) / 2, cy, 0, floorC);
        M.box(2 * H, th, z0 + DZ, STAIR.x, cy, (-DZ + z0) / 2, floorC); M.box(2 * H, th, DZ - z1, STAIR.x, cy, (z1 + DZ) / 2, floorC);
        // ceiling lights for the floor below: rows of warm panels under this plate
        for (let x = -54; x <= 54; x += 12) for (const z of [-9, 1, 10]) if (Math.abs(x - STAIR.x) > 5 || Math.abs(z - STAIR.z) > 5) GL.box(5, 0.08, 0.8, x, top - th - 0.06, z, 0xfff0d6);
      }
      // the slab edge: the lit floor line of a glass tower
      GL.box(2 * WX + 0.4, 0.2, 0.14, 0, top - 0.3, DZ + 0.42, f ? [0x8ab4f8, 0xf28b82, 0xfdd663, 0x81c995][f % 4] : 0xffe2b4);   // each floor's line glows in its own colour
      M.box(2 * WX + 0.4, th + 0.1, 0.3, 0, cy, DZ + 0.2, 0x2a2f3b);
      if (!roof) {
        M.box(2 * WX, inner, 0.5, 0, top + inner / 2, -DZ - 0.25, 0xeeeae3);                 // the back wall: warm white
        GL.box(2 * WX, 0.22, 0.06, 0, top + inner - 0.6, -DZ + 0.02, [0x4285f4, 0xea4335, 0xfbbc05, 0x34a853][f % 4]);   // a stripe in one of the brand colours
        const gf = new THREE.Mesh(new THREE.BoxGeometry(2 * WX, inner, 0.08), glassMat); gf.position.set(0, top + inner / 2, DZ + 0.3); gf.renderOrder = 3; g.add(gf);
        for (let x = -WX; x <= WX + 0.1; x += 10) M.box(0.28, inner, 0.32, x, top + inner / 2, DZ + 0.3, 0x1c2130);   // mullions
        for (const sx of [-1, 1]) { glassBox(g, 0.08, inner, 2 * DZ, sx * WX, top + inner / 2, 0, false); M.box(0.32, inner, 0.32, sx * WX, top + inner / 2, -DZ, 0x1c2130); }
      } else {
        for (const [w, d, x, z] of [[2 * WX, 0.08, 0, DZ - 0.1], [2 * WX, 0.08, 0, -DZ + 0.1], [0.08, 2 * DZ, -WX + 0.1, 0], [0.08, 2 * DZ, WX - 0.1, 0]]) {
          glassBox(g, w, 1.3, d, x, top + 0.65, z, false); GL.box(w + 0.1, 0.09, d + 0.1, x, top + 1.32, z, 0xd9f6ff);
        }
      }
      floorProps(f, M, GL, g, top);
      g.add(M.mesh()); g.add(GL.mesh());
    }
    // the spiral stairs: a white helix of steps round a pole, a pink rail, from the lobby to the roof
    const ST = new Merger(new THREE.MeshLambertMaterial({ vertexColors: true })), SG = new Merger(new THREE.MeshBasicMaterial({ vertexColors: true }));
    for (let f = 0; f < ROOF; f++) {
      const Y = f * FLOOR_H + WALK_Y, n = 24;
      ST.cyl(0.32, FLOOR_H, STAIR.x, Y + FLOOR_H / 2, STAIR.z, 0xd9d4cc);
      for (let k = 0; k < n; k++) {
        const a = Math.PI / 2 + (k + 0.5) * (2 * Math.PI / n), y = Y + (k + 0.5) * (FLOOR_H / n);
        ST.box(STAIR.r, 0.2, 0.95, STAIR.x + Math.cos(a) * STAIR.r / 2, y, STAIR.z + Math.sin(a) * STAIR.r / 2, 0xf2efe8, { ry: -a });
        ST.box(0.07, 1.1, 0.07, STAIR.x + Math.cos(a) * (STAIR.r + 0.05), y + 0.6, STAIR.z + Math.sin(a) * (STAIR.r + 0.05), 0xe7c3d6);
        SG.box(0.16, 0.12, 0.16, STAIR.x + Math.cos(a) * (STAIR.r + 0.05), y + 1.18, STAIR.z + Math.sin(a) * (STAIR.r + 0.05), 0xffd6ec);
      }
    }
    scene.add(ST.mesh()); scene.add(SG.mesh());
    // the glass lift: a shaft from the lobby to the top team floor, light rails, a car going up and down
    {
      const h = ROOF * FLOOR_H, gL = new THREE.Group(); scene.add(gL);
      const shaft = new THREE.Mesh(new THREE.CylinderGeometry(LIFT.r, LIFT.r, h, 32, 1, true), glassMat); shaft.position.set(LIFT.x, h / 2, LIFT.z); shaft.renderOrder = 3; gL.add(shaft);
      const rails = new Merger(new THREE.MeshBasicMaterial({ vertexColors: true }));
      for (let k = 0; k < 4; k++) { const a = Math.PI / 4 + k * Math.PI / 2; rails.box(0.09, h, 0.09, LIFT.x + Math.cos(a) * LIFT.r, h / 2, LIFT.z + Math.sin(a) * LIFT.r, 0xbff1ff); }
      gL.add(rails.mesh());
      const car = new THREE.Group(); car.position.set(LIFT.x, WALK_Y, LIFT.z); gL.add(car);
      const deck = new THREE.Mesh(new THREE.CylinderGeometry(LIFT.r - 0.2, LIFT.r - 0.2, 0.25, 32), new THREE.MeshLambertMaterial({ color: 0x4a5368 })); deck.position.y = 0.05; car.add(deck);
      const ring = new THREE.Mesh(new THREE.TorusGeometry(LIFT.r - 0.25, 0.06, 6, 40), basic(0xc6f4ff)); ring.rotation.x = -Math.PI / 2; ring.position.y = 0.2; car.add(ring);
      const roofRing = ring.clone(); roofRing.position.y = 4.6; car.add(roofRing);
      state.lift = { car, top: (ROOF - 1) * FLOOR_H + WALK_Y };
    }
    // data wires: from the back corner of every room out through the glass to the Brain in the fountain
    const core = new THREE.Vector3(BRAIN.x, CORE_Y, BRAIN.z);
    for (const room of state.roomList) {
      const F = room.y + SLAB_H, corner = new THREE.Vector3(room.center.x - room.half + 0.3, F + WALL_H - 0.6, room.center.z - room.half + 0.3);
      const ctrl = new THREE.Vector3(corner.x * 0.55, corner.y + 4, (corner.z + core.z) * 0.5);
      const curve = new THREE.QuadraticBezierCurve3(corner, ctrl, core);
      const wire = new THREE.Line(new THREE.BufferGeometry().setFromPoints(curve.getPoints(60)), new THREE.LineBasicMaterial({ color: mix(room.team.accent || room.color, 0xffffff, 0.25), transparent: true, opacity: 0.4 }));
      state.floors[room.floor].add(wire); room.wire = curve;
      for (let k = 0; k < 5; k++) particleSets.wire.push({ curve, k, floor: room.floor });
    }
    // particles: wire sparks, ring riders, the orbit cloud, beam risers, fountain jets (one Points object)
    const r = rng(17);
    for (const ring of anim.rings) for (let k = 0; k < 2; k++) particleSets.rider.push({ ring, a: r() * 6.28, speed: 0.6 + r() * 0.5 });
    for (let k = 0; k < (PHONE_AT_BOOT ? 26 : 48); k++) { const n = new THREE.Vector3(r() - 0.5, r() - 0.5, r() - 0.5).normalize(), u = new THREE.Vector3(0, 1, 0).cross(n).normalize(), v = new THREE.Vector3().crossVectors(n, u); particleSets.orbit.push({ u, v, radius: 3.6 + r() * 4.5, phase: r() * 6.28, speed: (0.2 + r() * 0.5) * (r() < 0.5 ? 1 : -1) }); }
    for (let k = 0; k < (PHONE_AT_BOOT ? 12 : 24); k++) particleSets.rise.push({ x: (r() - 0.5) * 2.2, z: (r() - 0.5) * 2.2, phase: r(), speed: 0.04 + r() * 0.06 });
    for (let j = 0; j < 10; j++) for (let k = 0; k < (PHONE_AT_BOOT ? 5 : 9); k++) particleSets.jet.push({ a: j * Math.PI / 5 + 0.3, phase: k / (PHONE_AT_BOOT ? 5 : 9) });
    const count = particleSets.wire.length + particleSets.rider.length + particleSets.orbit.length + particleSets.rise.length + particleSets.jet.length;
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.Float32BufferAttribute(new Float32Array(count * 3), 3));
    geo.setAttribute('color', new THREE.Float32BufferAttribute(new Float32Array(count * 3).fill(1), 3));
    anim.particles = new THREE.Points(geo, new THREE.PointsMaterial({ size: 1.25, map: glowTex, vertexColors: true, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, sizeAttenuation: true }));
    anim.particles.frustumCulled = false; scene.add(anim.particles);
  }

  // The ends of each floor (x beyond ±44, outside the rooms) and the lobby core: glass meeting rooms, phone booths,
  // reading and sofa nooks, plants. Nothing here is on a walking line (the corridor runs along the front at z = CZ).
  function meetingRoom(M, GL, g, x, top) {
    M.box(13, 0.05, 13, x, top + 0.03, -6, 0x323a4e); glassBox(g, 13, 7.2, 13, x, top + 3.6, -6);
    M.box(7, 0.16, 2.8, x, top + 1.95, -6, 0xd2b07a); M.box(0.3, 1.9, 1.4, x - 2.8, top + 0.95, -6, 0x2a2d35); M.box(0.3, 1.9, 1.4, x + 2.8, top + 0.95, -6, 0x2a2d35);
    for (let k = 0; k < 3; k++) for (const side of [-1, 1]) { const cx = x - 2.4 + k * 2.4, cz = -6 + side * 2.2; M.box(1.2, 0.16, 1.2, cx, top + 1.18, cz, 0x2a2d31); M.box(1.2, 1.2, 0.14, cx, top + 1.9, cz + side * 0.6, 0x2a2d31); }
    M.box(5.6, 3.0, 0.16, x, top + 4.0, -12.3, 0x0d0d12); GL.box(5.3, 2.7, 0.04, x, top + 4.0, -12.18, 0x4f7fd8);
  }
  function floorProps(f, M, GL, g, top) {
    const L = -52, R = 52;
    if (f === 0) {
      // the lobby: the front desk with the receptionist, a big sign, plants by the doors
      M.box(9, 1.8, 1.6, 4, top + 0.9, 2, 0x3b4560); M.box(9.2, 0.12, 1.8, 4, top + 1.86, 2, 0xe8e2d6); GL.box(8.6, 0.08, 0.04, 4, top + 1.2, 2.82, 0xf5c84b);
      const rc = makeCharacter({ skin: 0xf1c9a5, hair: 0x2a2a2e, style: 'short', hat: 0xf5c542, shirt: 0xf5c542, trousers: 0x2b3350 }, { seated: true, head: true });
      rc.group.position.set(4, top + 0.25, 0.4); rc.group.scale.setScalar(CHAR_SCALE); g.add(rc.group);
      const sign = new THREE.Mesh(new THREE.PlaneGeometry(14, 2.6), new THREE.MeshBasicMaterial({ map: signTex('AGENTS HQ', '#f5c84b'), transparent: true, depthWrite: false }));
      sign.position.set(2, top + 9.6, -DZ + 0.05); g.add(sign);
      tree(M, -14, top, 11, 0.85); tree(M, 18, top, 11, 0.85); tree(M, L, top, 8, 1); tree(M, R, top, 8, 1);
      sofa(M, L + 2, top, -6, 6, 0xc3d1d1, 0); sofa(M, R - 2, top, -6, 6, 0xc3d1d1, 0);
      return;
    }
    if (f === ROOF) {
      tree(M, L, top, -8, 1.1); tree(M, R, top, -8, 1.1); tree(M, L + 2, top, 8, 0.9); tree(M, R - 2, top, 8, 0.9);
      for (const x of [-14, 18]) { M.box(3.2, 0.5, 1.4, x, top + 0.6, 10, 0xf2efe8); M.box(3.2, 0.4, 1.4, x, top + 1.05, 9.4, 0xf2efe8, { rx: -0.5 }); }   // sun loungers
      return;
    }
    if (f === HALL) { hallProps(M, GL, g, top); return; }
    // team floors: a meeting room at one end, a nook at the other, alternating up the tower
    const mx = f % 2 ? R : L, nx = f % 2 ? L : R;
    meetingRoom(M, GL, g, mx, top);
    if (f === 2) for (const z of [-10, -4]) { glassBox(g, 3.2, 6.0, 3.6, nx, top + 3.0, z); M.box(3.2, 0.3, 3.6, nx, top + 6.15, z, 0x2a2f3c); M.box(1.4, 0.12, 0.9, nx + 0.6, top + 2.0, z, 0xe2d8c6); GL.box(1.6, 0.06, 0.3, nx, top + 5.9, z, 0xfff1d6); }
    else if (f === 3) { for (let k = 0; k < 3; k++) M.box(3.6, 6, 1.0, nx - 4 + k * 4, top + 3, -14.6, [0x8a6a4a, 0x6b4a2e, 0x8a6a4a][k]); sofa(M, nx, top, -6, 5, 0x6d5bd0, 0); tree(M, nx + 5, top, 6, 0.8); }
    else { sofa(M, nx, top, -8, 6, 0xd9cdd7, 0); M.box(2.2, 0.12, 2.2, nx, top + 0.95, -4.6, 0xc8925a); tree(M, nx - 5, top, 5, 0.85); tree(M, nx + 5, top, 5, 0.85); }
  }

  // ------------------------------------------------------------------ the Meeting Hall (6F)
  // The right half is the auditorium: a stage, the projector screen and four vertical (9:16, like the reels) TVs on the
  // back wall; 4 rows of 9 seats
  // facing them. The left half is a lounge with sofas, a bar and plants. The stairs and the lift stay clear in between.
  const HALL_ROWS = [-6.2, -2.2, 1.8, 5.8], HALL_COLS = [18, 22.5, 27, 31.5, 36, 40.5, 45, 49.5, 54];
  const HALL_SCREEN = { x: 36, w: 24, h: 10.5 };
  // the TVs: x, height, width, (with several channels: which channel, which of its videos)
  const HALL_TVS = [[15, 6.2, 4.4, 0, 0], [20.6, 6.2, 4.4, 0, 1], [51.6, 6.2, 4.4, 1, 0], [57, 6.2, 4.4, 1, 1], [-41, 4.6, 3.6, 0, 2], [-31, 4.6, 3.6, 1, 2]];
  function hallProps(M, GL, g, top) {
    const S0 = HALL_SCREEN, back = -DZ + 0.02;
    M.box(44, 0.06, 30, 36, top + 0.03, -1, 0x3b3550);                            // the auditorium carpet
    M.box(30, 0.45, 5.2, S0.x, top + 0.22, -12.9, 0x2a2440); GL.box(30.2, 0.06, 0.08, S0.x, top + 0.47, -10.3, 0xf5c84b);   // the stage, a gold edge
    M.box(S0.w + 1.2, S0.h + 1.2, 0.3, S0.x, top + 6.2, back + 0.15, 0x101018);   // the screen frame
    const scr = new THREE.Mesh(new THREE.PlaneGeometry(S0.w, S0.h), new THREE.MeshBasicMaterial({ map: canvasTex(16, 8, () => {}), toneMapped: false }));
    scr.position.set(S0.x, top + 6.2, back + 0.34); g.add(scr);
    const tvs = HALL_TVS.map(([x, y, w]) => {
      const h = w * 16 / 9;
      M.box(w + 0.45, h + 0.45, 0.3, x, top + y, back + 0.15, 0x0c0c12);
      const m = new THREE.Mesh(new THREE.PlaneGeometry(w, h), new THREE.MeshBasicMaterial({ map: canvasTex(9, 16, () => {}), toneMapped: false }));
      m.position.set(x, top + y, back + 0.33); g.add(m); return m;
    });
    // the projector on the ceiling, its beam, the lectern
    M.box(1.6, 0.6, 1.4, S0.x, top + 12.6, 4, 0xe9e6df); GL.box(0.5, 0.3, 0.06, S0.x, top + 12.5, 3.28, 0xbfe8ff);
    const beam = new THREE.Mesh(new THREE.ConeGeometry(7, 17.5, 4, 1, true), new THREE.MeshBasicMaterial({ color: 0x9fd8ff, transparent: true, opacity: 0.05, depthWrite: false, side: THREE.DoubleSide, blending: THREE.AdditiveBlending }));
    beam.rotation.x = Math.PI / 2 + 0.33; beam.position.set(S0.x, top + 9.4, -4.6); g.add(beam);
    M.box(1.6, 2.4, 1.0, S0.x, top + 1.65, -11.3, 0x6b4a2e); GL.box(1.2, 0.08, 0.06, S0.x, top + 2.7, -10.78, 0xf5c84b);
    // 36 seats in 4 rows, colour by row (Google-office brights)
    const rowC = [0x4285f4, 0xea4335, 0xfbbc05, 0x34a853];
    HALL_ROWS.forEach((z, r) => HALL_COLS.forEach((x) => {
      M.box(1.5, 0.18, 1.4, x, top + 1.05, z, rowC[r]); M.box(1.5, 1.4, 0.16, x, top + 1.75, z + 0.68, rowC[r]);
      M.box(0.12, 0.95, 0.12, x, top + 0.5, z, 0x2a2d35);
    }));
    // the lounge: sofas round rugs, a bar with stools, plants, pendant lights
    M.box(18, 0.05, 12, -36, top + 0.03, -4, 0xe9dcc8); M.box(10, 0.06, 7, -36, top + 0.06, -4, 0x6dbf9a);
    sofa(M, -36, top, -9.5, 9, 0x4285f4, 0); sofa(M, -42.5, top, -3.5, 6, 0xfbbc05, Math.PI / 2); sofa(M, -29.5, top, -3.5, 6, 0xea4335, -Math.PI / 2);
    M.box(4, 0.1, 2.4, -36, top + 0.9, -3.5, 0xc8925a); M.cyl(0.25, 0.85, -36, top + 0.45, -3.5, 0x2a2d35);
    M.box(12, 2.2, 1.6, -50, top + 1.1, -12.6, 0x2b2e36); M.box(12.2, 0.12, 1.8, -50, top + 2.26, -12.6, 0xe8e2d6); GL.box(11.6, 0.08, 0.04, -50, top + 1.5, -11.78, 0x34a853);
    for (let k = 0; k < 4; k++) { M.cyl(0.45, 0.1, -54 + k * 2.7, top + 1.6, -10.6, 0xea4335); M.cyl(0.08, 1.6, -54 + k * 2.7, top + 0.8, -10.6, 0x2a2d35); }
    for (const [x, z] of [[-56, 8], [-24, 8], [-56, -14], [-18, -13], [12, -13], [58, -13], [58, 10], [12, 10]]) tree(M, x, top, z, 0.95);
    for (let x = -50; x <= 54; x += 13) { if (Math.abs(x - STAIR.x) < 6 || Math.abs(x - LIFT.x) < 4) continue; GL.ball(0.5, x, top + 11.2, -2, 0xfff1d0); M.cyl(0.03, 2.6, x, top + 12.6, -2, 0x2a2d35); }
    const sign = new THREE.Mesh(new THREE.PlaneGeometry(20, 2.4), new THREE.MeshBasicMaterial({ map: signTex('ALL-HANDS HALL', '#fbbc05'), transparent: true, depthWrite: false }));
    sign.position.set(-36, top + 9.2, back + 0.2); g.add(sign);
    state.hall = { screen: scr, tvs, beam, top, slide: 0, slideAt: 0, data: null, imgs: {}, videos: [], drawn: 0 };
  }

  // ---------- the hall's screens: drawn into canvases a few times a second ----------
  const HALL_COLORS = ['#4285f4', '#ea4335', '#fbbc05', '#34a853'];
  function hallImg(url) {                                                      // one Image per address, loaded once (phone: a small preview)
    const H = state.hall; if (!url) return null;
    const u = url + (state.phone && /^\/(files|api\/thumbnail-design)\//.test(url) ? (url.includes('?') ? '&' : '?') + 'phone=1' : '');
    if (!H.imgs[u]) { const im = new Image(); im.src = u; H.imgs[u] = im; }
    const im = H.imgs[u]; return im.complete && im.naturalWidth ? im : null;
  }
  function coverFit(g, im, x, y, w, h) {
    const r = Math.max(w / im.naturalWidth, h / im.naturalHeight), iw = im.naturalWidth * r, ih = im.naturalHeight * r;
    g.save(); g.beginPath(); g.rect(x, y, w, h); g.clip(); g.drawImage(im, x + (w - iw) / 2, y + (h - ih) / 2, iw, ih); g.restore();
  }
  const CH_COLORS = ['#4285f4', '#34a853', '#fbbc05', '#ea4335'];
  function hallChannels(D) { return (D.channels || []).length ? D.channels : [{ key: '', name: 'NLRCC', numbers: D.numbers || [], videos: D.videos || [], designs: D.designs || [] }]; }
  function hallSlides(D) {
    const slides = ['numbers'];
    hallChannels(D).forEach((c, k) => { if ((c.videos || []).length || (c.numbers || []).some((n) => +n.value)) slides.push('ch' + k); });
    if ((D.review && (D.review.actions || []).length) || (D.review && (D.review.teams || []).length)) slides.push('improve');
    if ((D.designs || []).length) slides.push('designs');
    return slides;
  }
  function drawScreen(t) {
    const H = state.hall, D = H.data || {}, mesh = H.screen;
    let c = mesh.material.map.image;
    if (c.width !== 1280) { c = document.createElement('canvas'); c.width = 1280; c.height = 560; mesh.material.map = new THREE.CanvasTexture(c); mesh.material.needsUpdate = true; }
    const g = c.getContext('2d'), W = c.width, Hh = c.height, slides = hallSlides(D);
    if (t - H.slideAt > 9) { H.slide = (H.slide + 1) % slides.length; H.slideAt = t; }
    const kind = slides[H.slide % slides.length] || 'numbers', u = clamp((t - H.slideAt) / 1.4, 0, 1), live = MEET.on;
    const bg = g.createLinearGradient(0, 0, W, Hh); bg.addColorStop(0, '#0d1424'); bg.addColorStop(1, '#1b1033'); g.fillStyle = bg; g.fillRect(0, 0, W, Hh);
    for (let k = 0; k < 4; k++) { g.fillStyle = HALL_COLORS[k]; g.fillRect(k * W / 4, 0, W / 4, 8); }       // the four brand colours
    g.fillStyle = '#fff'; g.font = '700 34px Inter, system-ui, sans-serif'; g.textBaseline = 'middle';
    g.fillText(live ? 'ALL-HANDS MEETING' : 'MEETING HALL', 40, 50);
    g.font = '500 20px ' + MONO; g.fillStyle = '#9fb0cc';
    g.fillText(live ? (MEET.label || '') : 'next: ' + (D.next || '9:00 · 14:00 · 20:00'), 40, 86);
    if (live) { const on = Math.sin(t * 5) > 0; g.fillStyle = on ? '#ff4d5e' : '#7a2430'; g.beginPath(); g.arc(W - 120, 50, 9, 0, 7); g.fill(); g.fillStyle = '#fff'; g.font = '700 22px ' + MONO; g.fillText('LIVE', W - 102, 51); }
    const head = (txt) => { g.fillStyle = '#ffd77a'; g.font = '700 26px Inter, system-ui, sans-serif'; g.fillText(txt, 40, 136); };
    if (kind === 'numbers') {
      head('This week in the office');
      const N = (D.numbers || []).slice(0, 6), tw = (W - 80 - 5 * 20) / 6;
      N.forEach((n, i) => {
        const x = 40 + i * (tw + 20), y = 180, val = Math.round((+n.value || 0) * ease(u));
        g.fillStyle = 'rgba(255,255,255,0.06)'; g.fillRect(x, y, tw, 300);
        g.fillStyle = HALL_COLORS[i % 4]; g.fillRect(x, y, tw, 6);
        const glow = 0.5 + 0.5 * Math.sin(t * 3 + i); g.shadowColor = HALL_COLORS[i % 4]; g.shadowBlur = 18 * glow;
        g.fillStyle = '#fff'; g.font = '800 78px Inter, system-ui, sans-serif'; g.fillText(String(val), x + 18, y + 120); g.shadowBlur = 0;
        g.fillStyle = '#c9d3e6'; g.font = '600 20px Inter, system-ui, sans-serif';
        String(n.label || '').split('\n').forEach((ln, k) => g.fillText(ln, x + 18, y + 200 + k * 26));
        // a little bar chart under each number
        const bars = n.spark || []; const mx = Math.max(1, ...bars);
        bars.forEach((b, k) => { const bh = 46 * (b / mx) * ease(u); g.fillStyle = HALL_COLORS[i % 4]; g.fillRect(x + 18 + k * 18, y + 286 - bh, 12, bh); });
      });
    } else if (kind.startsWith('ch')) {                                      // one channel: its numbers and its latest reels
      const k = +kind.slice(2), C = hallChannels(D)[k] || {}, col = CH_COLORS[k % 4];
      g.fillStyle = col; g.fillRect(40, 118, 10, 36); g.fillStyle = '#fff'; g.font = '800 30px Inter, system-ui, sans-serif'; g.fillText(C.name || '', 62, 136);
      g.fillStyle = '#9fb0cc'; g.font = '600 20px Inter, system-ui, sans-serif'; g.fillText('this week · latest videos', 74 + g.measureText(C.name || '').width * 1.25, 137);
      (C.numbers || []).slice(0, 4).forEach((n, i) => {
        const x = 40 + (i % 2) * 262, y = 172 + Math.floor(i / 2) * 176, val = Math.round((+n.value || 0) * ease(u));
        g.fillStyle = 'rgba(255,255,255,0.06)'; g.fillRect(x, y, 246, 160); g.fillStyle = col; g.fillRect(x, y, 246, 5);
        const glow = 0.5 + 0.5 * Math.sin(t * 3 + i); g.shadowColor = col; g.shadowBlur = 16 * glow;
        g.fillStyle = '#fff'; g.font = '800 64px Inter, system-ui, sans-serif'; g.fillText(String(val), x + 16, y + 62); g.shadowBlur = 0;
        g.fillStyle = '#c9d3e6'; g.font = '600 18px Inter, system-ui, sans-serif'; String(n.label || '').split('\n').forEach((ln, j) => g.fillText(ln, x + 16, y + 112 + j * 22));
        const bars = n.spark || [], mx = Math.max(1, ...bars);
        bars.forEach((b, j) => { const bh = 34 * (b / mx) * ease(u); g.fillStyle = col; g.fillRect(x + 150 + j * 12, y + 150 - bh, 8, bh); });
      });
      const vids = (C.videos || []).slice(0, 3);
      vids.forEach((v, i) => {                                                  // vertical tiles, 9:16 like the reels
        const x = 596 + i * 216, y = 160, w = 196, h = 348, im = hallImg(v.cover), pop = clamp(u * 3 - i, 0, 1);
        g.globalAlpha = pop; g.fillStyle = '#000'; g.fillRect(x, y, w, h); if (im) coverFit(g, im, x, y, w, h);
        g.fillStyle = 'rgba(0,0,0,0.62)'; g.fillRect(x, y + h - 58, w, 58);
        g.fillStyle = '#fff'; g.font = '600 16px Inter, "PingFang SC", "Microsoft YaHei", sans-serif'; g.fillText(shorten(v.title || v.name, 13), x + 8, y + h - 38);
        g.fillStyle = v.state === 'scheduled' ? '#7fb0ff' : '#b8a2ff'; g.font = '700 13px ' + MONO; g.fillText((v.state || '').toUpperCase(), x + 8, y + h - 14);
        g.globalAlpha = 1;
      });
      if (!vids.length) { g.fillStyle = '#c9d3e6'; g.font = '600 22px Inter, system-ui, sans-serif'; g.fillText('No videos posted yet', 620, 320); }
    } else if (kind === 'improve') {
      head('How we improve · ' + ((D.review && D.review.date) || 'today'));
      const acts = (D.review && D.review.actions) || [], teams = (D.review && D.review.teams) || [];
      g.font = '600 24px Inter, "PingFang SC", "Microsoft YaHei", sans-serif';
      acts.slice(0, 3).forEach((a, k) => { const pop = clamp(u * 3 - k, 0, 1); g.globalAlpha = pop; g.fillStyle = HALL_COLORS[k % 4]; g.fillRect(40, 176 + k * 60, 10, 40); g.fillStyle = '#fff'; g.fillText((k + 1) + '. ' + shorten(a, 62), 64, 197 + k * 60); g.globalAlpha = 1; });
      g.font = '500 19px Inter, "PingFang SC", "Microsoft YaHei", sans-serif';
      teams.slice(0, 6).forEach((tm, k) => { const x = 40 + (k % 3) * 400, y = 380 + Math.floor(k / 3) * 70; g.fillStyle = '#ffd77a'; g.fillText(tm.team, x, y); g.fillStyle = '#c9d3e6'; g.fillText(shorten(tm.tip || '', 34), x, y + 28); });
      if (!acts.length && !teams.length) { g.fillStyle = '#c9d3e6'; g.fillText('The first review is written at 8 pm.', 40, 200); }
    } else {
      head('Latest designs');
      const chs = hallChannels(D);
      (D.designs || []).slice(0, 6).forEach((d0, i) => {
        const d = typeof d0 === 'string' ? { url: d0 } : d0, x = 40 + i * 202, y = 170, im = hallImg(d.url), k = Math.max(0, chs.findIndex((c) => c.key === (d.ch || '')));
        g.fillStyle = '#000'; g.fillRect(x, y, 186, 330); if (im) coverFit(g, im, x, y, 186, 330);
        g.fillStyle = CH_COLORS[k % 4]; g.fillRect(x, y + 336, 186, 4); g.fillStyle = '#c9d3e6'; g.font = '600 16px Inter, system-ui, sans-serif'; g.fillText((chs[k] || {}).name || '', x, y + 358);
      });
    }
    mesh.material.map.needsUpdate = true;
  }
  function tvPick(D, i) {                                                     // which channel and video a TV shows
    const chs = hallChannels(D), [, , , side, slot] = HALL_TVS[i];
    if (chs.length < 2) return { c: chs[0] || {}, k: 0, v: (D.videos || [])[i] };
    const k = side % chs.length, c = chs[k];
    const vids = c.videos || [];
    return { c, k, v: vids[slot] || vids[slot % Math.max(1, vids.length)] };   // fewer videos than TVs: they repeat
  }
  function drawTV(i, t) {
    const H = state.hall, D = H.data || {}, { c: C, k, v } = tvPick(D, i), mesh = H.tvs[i], W = 288, Hh = 512;
    let c = mesh.material.map.image;
    if (c.width !== W) { c = document.createElement('canvas'); c.width = W; c.height = Hh; mesh.material.map = new THREE.CanvasTexture(c); mesh.material.needsUpdate = true; }
    const g = c.getContext('2d'), col = CH_COLORS[k % 4];
    g.fillStyle = '#05060a'; g.fillRect(0, 0, W, Hh); g.textBaseline = 'middle';
    if (v) {
      const vid = hallVideo(i, v), playing = vid && !vid.paused && vid.readyState >= 2;
      if (playing) { const r = Math.max(W / vid.videoWidth, Hh / vid.videoHeight); const w = vid.videoWidth * r, h = vid.videoHeight * r; g.drawImage(vid, (W - w) / 2, (Hh - h) / 2, w, h); }
      else { const im = hallImg(v.cover); if (im) coverFit(g, im, 0, 0, W, Hh); }
      g.fillStyle = 'rgba(0,0,0,0.6)'; g.fillRect(0, Hh - 52, W, 52); g.fillStyle = '#fff'; g.font = '600 17px Inter, "PingFang SC", "Microsoft YaHei", sans-serif'; g.fillText(shorten(v.title || v.name, 15), 10, Hh - 26);
    } else { g.fillStyle = '#3a4152'; g.font = '600 20px Inter, sans-serif'; g.fillText('No video yet', 82, Hh / 2); }
    g.fillStyle = col; g.fillRect(0, 0, W, 30); g.fillStyle = '#fff'; g.font = '800 16px Inter, system-ui, sans-serif'; g.fillText(C.name || '', 10, 16);   // the channel on top
    mesh.material.map.needsUpdate = true;
  }
  function hallVideo(i, v) {                                                   // the TVs play the latest videos, muted, only while the hall is in use
    const H = state.hall; if (state.phone || !v.video) return null;
    let el = H.videos[i];
    if (!el || el.dataset.src !== v.video) { if (el) el.pause(); el = document.createElement('video'); el.muted = true; el.loop = true; el.playsInline = true; el.preload = 'none'; el.dataset.src = v.video; el.src = v.video + (v.video.includes('?') ? '&' : '?') + 'phone=1'; H.videos[i] = el; }
    const want = MEET.on || state.floorView === HALL;
    if (want && el.paused) el.play().catch(() => {}); else if (!want && !el.paused) el.pause();
    return el;
  }
  async function loadHall() {
    try {
      const r = await fetch('/api/meeting', { cache: 'no-store' });
      if (r.ok && state.hall) {
        const D = state.hall.data = await r.json();
        MEET.schedule = D.schedule || MEET.schedule; MEET.minutes = D.minutes || MEET.minutes; MEET.lines = (D.lines || []).concat(MEET_LINES);
        if (D.live && !MEET.on && D.live.until * 1000 > Date.now() + 60000) startMeeting((D.live.until * 1000 - Date.now()) / 60000, D.live.label);   // another device pressed OK, meeting now
      }
    } catch (e) { /* the hall keeps its last picture */ }
  }
  function updateHall(t) {
    const H = state.hall; if (!H) return;
    const every = state.phone ? 1 : (MEET.on || state.floorView === HALL ? 0.12 : 0.6);
    if (t - H.drawn < every) return;
    H.drawn = t; drawScreen(t); H.tvs.forEach((_, i) => drawTV(i, t));
    H.beam.material.opacity = MEET.on ? 0.07 + Math.sin(t * 2) * 0.015 : 0.035;
  }

  // ---------- meetings: the schedule, everyone walking in, listening, walking back ----------
  const MEET_LINES = ['Hook in the first 2 seconds 👀', 'More church-life Shorts 🙌', 'Never skip the Saturday invite 📣', 'Both thumbnail sizes, every time ✓',
    'Same-age views, not lifetime 📊', 'Pick the style per video 🎨', 'Shorter captions win on IG?', 'Let’s test a question title ❓', 'Great job on the 1024 kids video 👏', 'Fix the profile links this week 🔗'];
  const MEET = { on: false, endMs: 0, label: '', schedule: ['09:00', '14:00', '20:00'], minutes: 15, lastSlot: '', lines: MEET_LINES.slice(), talkAt: 0 };
  function meetingSlot(now) {                                                  // the scheduled meeting this minute falls in, if any
    const d = new Date(now), mins = d.getHours() * 60 + d.getMinutes();
    for (const hm of MEET.schedule) { const [h, m] = hm.split(':').map(Number), st = h * 60 + m; if (mins >= st && mins < st + MEET.minutes) return { key: d.toDateString() + ' ' + hm, endMs: now + (st + MEET.minutes - mins) * 60000 - d.getSeconds() * 1000, label: hm + ' all-hands' }; }
    return null;
  }
  function startMeeting(minutes, label) {
    MEET.on = true; MEET.endMs = Date.now() + (minutes || MEET.minutes) * 60000; MEET.label = label || 'all-hands';
    emitLife({ type: 'meeting', on: true, label: MEET.label, until: MEET.endMs });
    return true;
  }
  function endMeeting() { if (!MEET.on) return false; MEET.on = false; emitLife({ type: 'meeting', on: false }); return true; }
  function actMeeting(L) {
    const seatId = LIFE.hall && freeSpot(LIFE.hall.seats);
    if (seatId == null || !reserve(L, seatId)) return false;
    runSteps(L, [S_RISE(), S_WALK(seatId, HURRY_SPEED * 1.35), S_FACE(faceNode), S_PERCH(0), S_CALL((A) => { A.anim = 'listen'; A.inMeeting = true; }),
      S_WAIT(2, 'listen', () => !MEET.on, 3600), S_CALL((A) => { A.anim = null; A.inMeeting = false; }), S_PERCH(1), S_WALK(L.stand), S_SIT()], 'meeting');
    return true;
  }
  function meetingTick(run) {
    const now = Date.now(), slot = meetingSlot(now);
    if (slot && !MEET.on && MEET.lastSlot !== slot.key) { MEET.lastSlot = slot.key; startMeeting(Math.max(1, (slot.endMs - now) / 60000), slot.label); }
    if (MEET.on && now >= MEET.endMs) endMeeting();
    if (!MEET.on) return;
    for (const L of LIFE.actors) if (L.mode === 'seated' && !run[L.name] && !L.reservedBy && !L.inMeeting && now < MEET.endMs - 60000) actMeeting(L);
    if (LIFE.time > MEET.talkAt) {                                             // someone in the hall speaks up now and then
      MEET.talkAt = LIFE.time + 4 + Math.random() * 4;
      const here = LIFE.actors.filter((L) => L.inMeeting && !L.sayText); const L = here[Math.floor(Math.random() * here.length)];
      if (L) say(L, MEET.lines[Math.floor(Math.random() * MEET.lines.length)], 3.6);
    }
  }

  // ------------------------------------------------------------------ the commons (lobby floor and roof)
  // Rooms without desks in the team slots: the canteen + kitchen and the lounge in the lobby, the terrace (open air,
  // under a pergola) and the game room on the roof, plus the roof's coffee bar in the core. Spots for office life
  // (stools, sofas, bean bags, arcade machines, the counter) are room-local (x, z from the centre; back walls at -x
  // and -z) and become graph nodes in buildLife.
  const COMMONS = [
    { key: 'canteen', name: 'CANTEEN', floor: 0, slot: 0, floorC: 0x8b6b4e, wallC: 0x5d4b3e, walls: true, sign: '#f5c84b' },
    { key: 'lounge', name: 'LOUNGE', floor: 0, slot: 1, floorC: 0x35545c, wallC: 0x2a3f4a, walls: true, sign: '#7fe0d4' },
    { key: 'terrace', name: 'ROOF TERRACE', floor: ROOF, slot: 0, floorC: 0x3d6b52, walls: false, sign: '#ffd98a' },
    { key: 'gameroom', name: 'GAME ROOM', floor: ROOF, slot: 1, floorC: 0x2a2440, wallC: 0x1d1830, walls: true, sign: '#ff5fd2' },
  ];
  function signTex(text, color) {
    return canvasTex(512, 128, (c, w, h) => { c.clearRect(0, 0, w, h); c.font = '800 60px Inter, system-ui, sans-serif'; c.textAlign = 'center'; c.textBaseline = 'middle'; c.shadowColor = color; c.shadowBlur = 18; c.fillStyle = color; c.fillText(text, w / 2, h / 2 + 4); });
  }
  function buildCommons() {
    const h = S / 2;
    for (const def of COMMONS) {
      const realScene = scene; scene = state.floors[def.floor];
      const shell = new Merger(new THREE.MeshPhongMaterial({ vertexColors: true, shininess: 14, specular: 0x202024 }));
      const M = new Merger(new THREE.MeshLambertMaterial({ vertexColors: true }));
      const GL = new Merger(new THREE.MeshBasicMaterial({ vertexColors: true }));
      const Y = def.floor * FLOOR_H, F = Y + SLAB_H, cx = (def.slot ? 1 : -1) * ROOM_X, cz = -DZ + 2 + h;
      const box = (m, w, hh, d, lx, y, lz, c, o) => m.box(w, hh, d, cx + lx, y, cz + lz, c, o);
      const C = { key: def.key, floor: def.floor, center: new THREE.Vector3(cx, Y, cz), half: h, y: Y, lanes: Object.assign({}, LIFE_LAYOUT.normal.lanes), edges: LIFE_LAYOUT.normal.edges, spots: [] };
      const spot = (list, lx, lz, o) => { o = o || {}; C.spots.push({ list, x: lx, z: lz, y: o.y || 0, face: o.face || null, lane: o.lane, sit: !!o.sit }); };
      shell.box(S, SLAB_H, S, cx, Y + SLAB_H / 2, cz, def.floorC);
      shell.box(S, 0.1, 0.22, cx, F + 0.05, cz + h - 0.11, mix(def.floorC, 0xffffff, 0.45));
      shell.box(0.22, 0.1, S, cx + h - 0.11, F + 0.05, cz, mix(def.floorC, 0xffffff, 0.45));
      if (def.walls) {
        shell.box(WALL_T, WALL_H, S, cx - h + WALL_T / 2, F + WALL_H / 2, cz, def.wallC);
        shell.box(S, WALL_H, WALL_T, cx, F + WALL_H / 2, cz - h + WALL_T / 2, def.wallC);
        shell.box(0.55, WALL_H + 1.6, 0.55, cx - h + 0.27, F + (WALL_H + 1.6) / 2, cz - h + 0.27, 0x1d2029);
      }
      const sign = new THREE.Mesh(new THREE.PlaneGeometry(7.2, 1.8), new THREE.MeshBasicMaterial({ map: signTex(def.name, def.sign), transparent: true, depthWrite: false }));
      sign.position.set(cx + 1.2, F + (def.walls ? 7.6 : 6.4), cz - h + WALL_T + 0.03); scene.add(sign);
      if (def.key === 'canteen') {
        box(M, 12, 1.5, 1.6, -1, F + 0.75, -8.75, 0xefe9df); box(M, 12.2, 0.1, 1.75, -1, F + 1.55, -8.75, 0x8a6a4a);
        box(M, 1.4, 0.05, 0.9, -3, F + 1.62, -8.75, 0x9aa3ad); box(M, 1.2, 0.08, 0.9, 1.5, F + 1.63, -8.75, 0x22252c);
        box(M, 0.8, 1.0, 0.7, 4, F + 2.1, -8.9, 0x2b2e36); GL.box(0.07, 0.07, 0.07, 4.25, F + 2.45, -8.5, 0x7dffb0);
        box(M, 10, 1.4, 0.9, -1, F + 5.4, -9.1, 0xd8cfc0);
        box(M, 1.8, 4.4, 1.6, -8.6, F + 2.2, -8.75, 0xd9dde3); box(M, 0.08, 1.2, 0.1, -7.75, F + 2.6, -7.95, 0x9aa3ad);
        for (const tx of [-3.5, 3.0]) {
          M.cyl(1.25, 0.12, cx + tx, F + 1.6, cz + 3.6, 0xc8925a); M.cyl(0.12, 1.5, cx + tx, F + 0.8, cz + 3.6, 0x3a3d42); M.cyl(0.6, 0.06, cx + tx, F + 0.03, cz + 3.6, 0x3a3d42);
          M.cyl(0.04, 3.4, cx + tx, F + 6.7, cz + 3.6, 0x15151a); GL.cyl(0.55, 0.3, cx + tx, F + 4.9, cz + 3.6, 0xfff1d6); addGlowSprite(cx + tx, F + 4.7, cz + 3.6, 0xffe2b8, 3.2, 0.4);
        }
        for (const [sx, tx] of [[-5.5, -3.5], [-1.5, -3.5], [1.0, 3.0], [5.0, 3.0]]) {
          M.cyl(0.45, 0.12, cx + sx, F + 1.0, cz + 3.6, 0x2a2d35); M.cyl(0.08, 1.0, cx + sx, F + 0.5, cz + 3.6, 0x55596a);
          spot('sits', sx, 3.6, { sit: true, face: [tx, 3.6], lane: sx < -2 ? 'ML' : sx < 2 ? 'MM' : 'MR' });
        }
        spot('food', -4.5, -6.7, { face: [-4.5, -8.75], lane: 'ML' }); spot('food', 1.5, -6.7, { face: [1.5, -8.75], lane: 'MM' });
        plant(M, cx + h - 1.6, F, cz - h + 1.9, 1);
      } else if (def.key === 'lounge' || def.key === 'terrace') {
        const sc = def.key === 'lounge' ? 0xd9cdd7 : 0xf2efe8;
        box(M, 12, 0.06, 9, 0.5, F + 0.03, -3.5, def.key === 'lounge' ? 0x4f7f86 : 0x8a6a4a);
        box(M, 8.4, 0.7, 1.8, -1, F + 0.45, -8.5, sc); box(M, 8.4, 1.1, 0.45, -1, F + 1.2, -9.3, sc);
        box(M, 0.45, 1.0, 1.8, -5.0, F + 0.9, -8.5, sc); box(M, 0.45, 1.0, 1.8, 3.0, F + 0.9, -8.5, sc);
        for (const k of [-3.5, -1, 1.5]) box(M, 2.2, 0.18, 1.5, k, F + 0.88, -8.4, def.key === 'lounge' ? 0xefe6ee : 0xf5c84b);
        box(M, 1.8, 0.12, 1.2, 1.2, F + 0.95, -5.0, 0xc8925a); box(M, 1.5, 0.85, 0.9, 1.2, F + 0.45, -5.0, 0x8a6a4a);
        M.add(G.sphere, 0xf59e0b, cx + 3, F + 0.55, cz + 4.2, { sx: 1.1, sy: 0.6, sz: 1.1 }); M.add(G.sphere, 0x8b5cf6, cx + 6, F + 0.55, cz + 3.0, { sx: 1.1, sy: 0.6, sz: 1.1 });
        if (def.key === 'lounge') { box(M, 0.16, 2.6, 4.6, -9.5, F + 4.4, -1, 0x0d0d12); GL.box(0.04, 2.3, 4.3, -9.38, F + 4.4, -1, 0x3f6fd8); plant(M, cx + h - 1.6, F, cz - h + 1.9, 1); }
        else {                                                                 // the pergola with string lights
          for (const [px, pz] of [[-9, -9], [9, -9], [-9, 7], [9, 7]]) box(M, 0.4, 7, 0.4, px, F + 3.5, pz, 0x3a2e24);
          for (const pz of [-9, -3.7, 1.6, 7]) box(M, 18.4, 0.3, 0.3, 0, F + 7, pz, 0x3a2e24);
          box(M, 0.3, 0.3, 16.4, -9, F + 7.2, -1, 0x3a2e24); box(M, 0.3, 0.3, 16.4, 9, F + 7.2, -1, 0x3a2e24);
          for (const pz of [-9, -3.7, 1.6, 7]) for (let k = 0; k < 9; k++) { const lx = -8 + k * 2, sag = Math.sin(k / 8 * Math.PI) * 0.6; GL.ball(0.14, cx + lx, F + 6.75 - sag, cz + pz, 0xffe7a8); }
          tree(M, cx - 7.5, F, cz + 5.5, 0.7); tree(M, cx + 8, F, cz - 7.5, 0.7);
        }
        C.lanes = Object.assign(C.lanes, { S3: [4.6, -6.6], S2: [1.5, -6.6], S1: [-1, -6.6], S0: [-3.5, -6.6] });
        C.edges += ' MR-S3 S3-S2 S2-S1 S1-S0';
        [[-3.5, 'S0'], [-1, 'S1'], [1.5, 'S2']].forEach(([x, ln]) => spot('sits', x, -8.2, { sit: true, face: [x, 0], lane: ln }));
        spot('sits', 3, 4.2, { sit: true, face: [-9.5, -1], lane: 'MM' }); spot('sits', 6, 3.0, { sit: true, face: [-9.5, -1], lane: 'MR' });
      } else {
        // the game room: arcade machines along the back wall, a foosball table, a neon strip
        [[-6, 0xff5fd2], [-3.4, 0x5fd2ff], [-0.8, 0xf5c84b]].forEach(([x, c]) => {
          box(M, 1.7, 3.4, 1.4, x, F + 1.7, -8.6, 0x1b1d26); GL.box(1.3, 1.0, 0.05, x, F + 2.4, -7.88, c); GL.box(1.5, 0.35, 0.05, x, F + 3.2, -7.88, mix(c, 0xffffff, 0.4));
          spot('play', x, -6.6, { face: [x, -9], lane: x < -2 ? 'ML' : 'MM' });
        });
        box(M, 3.6, 0.3, 2.0, 5.5, F + 1.7, 3.6, 0x2f6b4a); box(M, 3.4, 1.55, 0.2, 5.5, F + 0.8, 2.7, 0x3a3d42); box(M, 3.4, 1.55, 0.2, 5.5, F + 0.8, 4.5, 0x3a3d42);
        spot('play', 3.2, 3.6, { face: [5.5, 3.6], lane: 'MR' }); spot('play', 7.8, 3.6, { face: [5.5, 3.6], lane: 'FR' });
        box(GL, 0.06, 0.12, 18, -9.5, F + 8.6, 0, 0xff5fd2); box(GL, 18, 0.12, 0.06, 0, F + 8.6, -9.5, 0x5fd2ff);
      }
      scene.add(shell.mesh()); scene.add(M.mesh()); scene.add(GL.mesh());
      state.commons.push(C);
      scene = realScene;
    }
    // the roof's coffee bar in the core: a counter against the back wall with a machine, three stools in front
    {
      const g = state.floors[ROOF], Y = ROOF * FLOOR_H, F = Y + WALK_Y, M = new Merger(new THREE.MeshLambertMaterial({ vertexColors: true })), GL = new Merger(new THREE.MeshBasicMaterial({ vertexColors: true }));
      M.box(12, 1.5, 1.6, 7, F + 0.75, -13.4, 0xefe9df); M.box(12.2, 0.1, 1.8, 7, F + 1.55, -13.4, 0x8a6a4a);
      M.box(0.9, 1.1, 0.8, 4, F + 2.15, -13.6, 0x2b2e36); GL.box(0.07, 0.07, 0.07, 4.25, F + 2.55, -13.15, 0x7dffb0);
      for (const x of [3.5, 7, 10.5]) { M.cyl(0.45, 0.12, x, F + 1.0, -11.3, 0x2a2d35); M.cyl(0.08, 1.0, x, F + 0.5, -11.3, 0x55596a); }
      const sign = new THREE.Mesh(new THREE.PlaneGeometry(5.5, 1.4), new THREE.MeshBasicMaterial({ map: signTex('COFFEE', '#ffd98a'), transparent: true, depthWrite: false })); sign.position.set(7, F + 4.6, -14.9); g.add(sign);
      g.add(M.mesh()); g.add(GL.mesh());
      state.commons.push({ key: 'cafe', floor: ROOF, center: new THREE.Vector3(7, Y, -6), half: 8, y: Y, lanes: { A: [-3.5, 5], B: [3.5, 5] }, edges: 'A-B', door: [0, 12], doorLanes: 'A B', spots: [3.5, 7, 10.5].map((x, k) => ({ list: 'bar', x: x - 7, z: -5.3, y: 0, face: [x - 7, -7.4], lane: k < 1 ? 'A' : 'B', sit: true })) });
    }
  }

  // ------------------------------------------------------------------ the plaza and the city
  const windowTex = canvasTex(256, 512, (c, w, h) => {
    c.fillStyle = '#121a2e'; c.fillRect(0, 0, w, h);
    const r = rng(7);
    for (let y = 8; y < h - 8; y += 20) for (let x = 8; x < w - 8; x += 18) { const v = r(); c.fillStyle = v < 0.42 ? (v < 0.12 ? '#ffe2a8' : '#fff6e0') : v < 0.6 ? '#2a3a5c' : '#1a2440'; c.fillRect(x, y, 10, 12); }
  });
  windowTex.wrapS = windowTex.wrapT = THREE.RepeatWrapping;
  function buildCity() {
    const M = new Merger(new THREE.MeshLambertMaterial({ vertexColors: true })), GL = new Merger(new THREE.MeshBasicMaterial({ vertexColors: true }));
    // plaza paving, the road, a sidewalk edge
    M.box(150, 0.3, 66, 0, 0.0, DZ + 33, 0x4d5363); M.box(150, 0.3, 0.6, 0, 0.18, DZ + 66, 0x8a90a0);
    M.box(420, 0.2, 22, 0, -0.05, DZ + 78, 0x15181f);
    for (let x = -200; x <= 200; x += 12) GL.box(5, 0.04, 0.4, x, 0.07, DZ + 78, 0xe8dfc4);
    // the fountain: a stone rim round a pool of water, the Brain's platform the island in the middle
    M.cyl(22.5, 1.3, BRAIN.x, 0.65, BRAIN.z, 0x9aa1ae); M.cyl(21.6, 1.32, BRAIN.x, 0.66, BRAIN.z, 0x3a4252);
    const water = new THREE.Mesh(new THREE.CircleGeometry(21.5, 64), new THREE.MeshPhongMaterial({ color: 0x1d5fb0, emissive: 0x0b2a5a, shininess: 90, specular: 0x9fd8ff, transparent: true, opacity: 0.88 }));
    water.rotation.x = -Math.PI / 2; water.position.set(BRAIN.x, 1.05, BRAIN.z); scene.add(water);
    for (let k = 0; k < 10; k++) { const a = k * Math.PI / 5 + 0.3; GL.ball(0.22, BRAIN.x + Math.cos(a) * 20.4, 1.2, BRAIN.z + Math.sin(a) * 20.4, 0xbff1ff); }
    // trees, benches, street lamps, two parked cars
    for (const [x, z, k] of [[-52, DZ + 14, 1.5], [52, DZ + 14, 1.5], [-46, DZ + 50, 1.7], [46, DZ + 52, 1.6], [-64, DZ + 34, 1.3], [64, DZ + 30, 1.3]]) tree(M, x, 0.15, z, k);
    for (const [x, z] of [[-30, DZ + 20], [30, DZ + 20], [-30, DZ + 52], [30, DZ + 52]]) { M.box(4, 0.25, 1.1, x, 1.0, z, 0xc8925a); M.box(0.25, 0.9, 1.0, x - 1.7, 0.45, z, 0x3a3d42); M.box(0.25, 0.9, 1.0, x + 1.7, 0.45, z, 0x3a3d42); }
    for (const [x, z] of [[-40, DZ + 64], [-12, DZ + 64], [12, DZ + 64], [40, DZ + 64], [-60, DZ + 8], [60, DZ + 8]]) { M.cyl(0.15, 9, x, 4.6, z, 0x23262e); GL.ball(0.45, x, 9.2, z, 0xfff0d0); addGlowSprite(x, 9.2, z, 0xffe2b8, 4.5, 0.5); }
    const car = (x, z, rot, c) => {
      const o = new THREE.Matrix4().makeRotationY(rot).setPosition(x, 0, z), at = { parent: o };
      M.box(4.6, 0.9, 9.2, 0, 1.0, 0, c, at); M.box(3.8, 0.8, 3.6, 0, 1.8, -0.4, mix(c, 0x111111, 0.55), at);
      for (const [wx, wz] of [[-2.3, 3], [2.3, 3], [-2.3, -3], [2.3, -3]]) M.cyl(0.75, 0.6, wx, 0.75, wz, 0x15151a, Object.assign({ rz: Math.PI / 2 }, at));
      for (const wx of [-1.5, 1.5]) GL.box(0.8, 0.25, 0.1, wx, 1.15, 4.62, 0xfff6e0, at);
      for (const wx of [-1.6, 1.6]) GL.box(0.8, 0.22, 0.1, wx, 1.15, -4.62, 0xff4d5e, at);
    };
    car(-36, DZ + 42, 1.35, 0xf2c230); car(36, DZ + 44, -1.75, 0xd8323a);
    scene.add(M.mesh()); scene.add(GL.mesh());
    // the skyline: dark towers with lit windows behind and beside the office
    const r = rng(21), mats = [0x9aa4c0, 0x7d88a6, 0xb0b8cc].map((c) => new THREE.MeshBasicMaterial({ map: windowTex, color: c }));
    const n = PHONE_AT_BOOT ? 18 : 30;
    for (let k = 0; k < n; k++) {
      const side = k % 3, w = 18 + r() * 26, d = 16 + r() * 20, h = 50 + r() * 130;
      const x = side === 0 ? -230 + r() * 460 : (side === 1 ? -1 : 1) * (95 + r() * 120), z = side === 0 ? -50 - r() * 120 : -40 + r() * 70;
      if (Math.abs(x) < WX + 12 && z > -DZ - 20) continue;
      const geo = new THREE.BoxGeometry(w, h, d), uv = geo.attributes.uv;
      for (let i = 0; i < uv.count; i++) uv.setXY(i, uv.getX(i) * w / 24, uv.getY(i) * h / 48);
      const b = new THREE.Mesh(geo, mats[k % 3]); b.position.set(x, h / 2, z); scene.add(b);
    }
  }

  const _a = new THREE.Vector3(), _b = new THREE.Vector3();
  function animateParticles(t) {
    const pos = anim.particles.geometry.attributes.position, colr = anim.particles.geometry.attributes.color;
    let i = 0;
    const put = (x, y, z, bright) => { pos.setXYZ(i, x, y, z); if (bright !== undefined) colr.setXYZ(i, bright, bright, bright); i++; };
    for (const p of particleSets.wire) { if (!floorShown(p.floor)) { put(0, -999, 0, 0); continue; } const u = (t * 0.09 + p.k / 5) % 1; p.curve.getPoint(u, _a); put(_a.x, _a.y, _a.z, 1); }
    for (const p of particleSets.rider) { const a = p.a + t * p.speed; _a.set(Math.cos(a) * p.ring.radius, 0, Math.sin(a) * p.ring.radius).applyMatrix4(p.ring.holder.matrixWorld); put(_a.x, _a.y, _a.z, 1); }
    for (const p of particleSets.orbit) { const a = p.phase + t * p.speed; _a.copy(p.u).multiplyScalar(Math.cos(a) * p.radius).addScaledVector(p.v, Math.sin(a) * p.radius); put(BRAIN.x + _a.x, CORE_Y + _a.y, BRAIN.z + _a.z, 0.7); }
    for (const p of particleSets.rise) { const u = (p.phase + t * p.speed) % 1; put(BRAIN.x + p.x, 2.4 + u * (TOP_Y + 20), BRAIN.z + p.z, Math.sin(u * Math.PI) * 0.9); }
    for (const p of particleSets.jet) {                                        // the fountain: arcs from the rim to the island
      const u = (p.phase + t * 0.55) % 1, r = 20.2 - u * 5.4, a = p.a;
      put(BRAIN.x + Math.cos(a) * r, 1.1 + 7.5 * 4 * u * (1 - u), BRAIN.z + Math.sin(a) * r, 0.75);
    }
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
      sub.group.position.set(room.center.x + pos.x, room.y + SLAB_H, room.center.z + pos.z);
    });
    if (room.decal) room.decal.material.map = room.subs.length ? room.bayTex.plain : room.bayTex.text;
  }
  function clearSubagents(teamKey) { const room = state.rooms[teamKey]; if (!room) return; room.subs.slice().forEach((s) => removeSub(room, s)); if (room.decal) room.decal.material.map = room.bayTex.text; }
  function subPosition(room, idx, n) {
    if (room.bay) { const cols = Math.min(n, 4), row = Math.floor(idx / 4), c = idx % 4; return { x: room.bay.x - (cols - 1) * 3 + c * 6, z: room.bay.z - 1.2 + row * 4.2, desk: true }; }
    return { x: -4.5 + (idx % 4) * 3, z: room.half - 2.2 - Math.floor(idx / 4) * 3, desk: false };
  }
  function createSub(room, id, pos, now, idx) {
    const g = new THREE.Group(); g.position.set(room.center.x + pos.x, room.y + SLAB_H, room.center.z + pos.z); state.floors[room.floor].add(g);
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
    if (sub.group.parent) sub.group.parent.remove(sub.group);
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

  // ------------------------------------------------------------------ office life (idle agents get up, walk and talk)
  // Every seated character has a small state machine. Idle agents (not in HQ.running()) mostly sit and work, now and
  // then stretch at the desk, stand up to stretch, fetch a coffee (their room's machine or the lobby bar on the Brain
  // platform), take a phone call pacing near the room's open edge, chat with a teammate at the coffee machine, visit
  // another team to share a lesson, or walk to the Brain and drop a note into it (the Brain pulses). Timers are
  // randomised and staggered and only LIFE.max agents are away at once (fewer on a phone). An agent that starts
  // running hurries back along its path and sits down; a visit or chat partner sits back down too.
  // Walking follows a waypoint graph built once: chair → stand spot beside the chair → the room's lanes → its door on
  // the open edge (a short porch strip around the walls where a walkway meets a wall) → walkway → the ring on the Brain
  // platform → another walkway → another room. Spots (stand, guest, coffee, phone, note, bar) are dead ends in the
  // graph and are reserved, so nobody walks through or stands in someone else's spot.
  // Bubbles are CSS2D labels of kind 'bubble' (one per character, filled through setLabel): text when the camera is
  // close, a small 💬 above a talking pair from far away. Lines come from GET /api/chatter (lessons with the teams they
  // help, ideas, brand rules, today's done tasks) and a pool of warm generic lines; nothing invents numbers or claims.
  const LIFE = {
    on: true, ready: false, auto: true, speed: 1, time: 0, max: 7, nodes: [], actors: [], by: {}, talks: [], topics: [], taken: {}, rooms: {}, commons: {}, ring: [], bar: [],
    pulse: 0, pulsed: false, notes: [], wave: null, debug: null, recent: {}, chatterTimer: 0, talkers: {},   // talkers: who is mid-conversation (the HUD hides their name pills)
  };
  // Room-local lanes (x, z from the room centre) for a normal room and for the big Creative room, the lanes each desk
  // slot's stand / guest spots connect to, the coffee counter against the left wall and two phone pacing spots.
  const LIFE_LAYOUT = {
    normal: {
      lanes: { FL: [-5.5, 6.9], FM: [0, 6.9], FR: [6.9, 6.7], RM: [7.8, 0.4], MR: [4.0, 0.3], MM: [0, 0.3], ML: [-4.2, 0.3] },
      edges: 'FL-FM FM-FR FR-RM RM-MR MR-MM MM-ML',
      slots: { A: 'MM MR', B: 'FM FL', C: 'FM FR', D: 'ML', E: 'RM' },
      counter: [-8.95, 6.0], coffee: [[-7.3, 6.0], [-5.4, 5.1]], coffeeLanes: 'FL',
      phone: [[2.2, 8.5, 'FM'], [4.6, 8.5, 'FR']],
    },
    creative: {
      lanes: { FL: [-8.5, 10.6], FM: [0, 10.6], FR: [11.0, 10.6], RF: [12.3, 6.0], RM: [12.3, 2.0], RB: [12.3, -3.5], MR: [7.6, 2.0], MM: [0, 2.0], ML: [-7.5, 2.0], LB: [-7.5, -2.6], AG: [0, -3.6], LF: [-11.4, 6.8] },
      edges: 'FL-FM FM-FR FR-RF RF-RM RM-RB RM-MR MR-MM MM-ML ML-LB MM-AG ML-LF LF-FL',
      slots: { A: 'AG', B: 'MM ML', C: 'MM MR', D: 'LB', E: 'RB' },
      counter: [-12.95, 3.6], coffee: [[-11.0, 3.6], [-10.0, 1.2]], coffeeLanes: 'ML',
      phone: [[-1.5, 12.3, 'FM'], [2.0, 12.3, 'FM']],
    },
  };
  // How each clock position reaches its room (h = half the room side): points outside the slab ('w' on the walkway,
  // 'p' on a porch strip around the back walls), then the door just inside the open edge and the lanes it joins.
  // Rooms 3, 4 and 5 turn their walls toward the Brain, so a porch leads around to the open side.
  const LIFE_ENTRY = [
    (h) => ({ out: [[h + 1.41, h + 1.41, 'w']], door: [h - 3.6, h - 1.1], lanes: 'FR FM' }),
    (h) => ({ out: [[0, h + 1.5, 'w']], door: [0, h - 1.4], lanes: 'FM' }),
    (h) => ({ out: [[-h - 1.77, h + 1.77, 'w'], [-h + 1.0, h + 1.4, 'w']], door: [-h + 3.5, h - 2.0], lanes: 'FL' }),
    (h) => ({ out: [[-h - 1.7, 0, 'w'], [-h - 1.7, h + 1.7, 'p'], [-h + 4.5, h + 1.7, 'p']], door: [-h + 4.5, h - 1.6], lanes: 'FL' }),
    (h) => ({ out: [[-h - 1.7, -h - 1.7, 'w'], [-h - 1.7, h + 1.7, 'p'], [-h + 3.0, h + 1.7, 'p']], door: [-h + 3.0, h - 1.4], lanes: 'FL' }),
    (h) => ({ out: [[0, -h - 1.7, 'w'], [h + 1.7, -h - 1.7, 'p'], [h + 1.7, 1.4, 'p']], door: [h - 1.3, 1.4], lanes: 'RM' }),
    (h) => ({ out: [[h + 1.7, -h - 1.7, 'w'], [h + 1.7, 1.4, 'p']], door: [h - 1.3, 1.4], lanes: 'RM' }),
    (h) => ({ out: [[h + 1.5, 0, 'w']], door: [h - 1.1, 0.8], lanes: 'RM' }),
  ];
  const WALK_SPEED = 2.4, HURRY_SPEED = 4.3, PACE_SPEED = 0.85;
  const HIP_S = -Math.PI / 2 + 0.05, KNEE_S = Math.PI / 2 - 0.1, ARM_S = -1.45;
  const _lo = new THREE.Vector3(), _lw = new THREE.Vector3(), _lc = new THREE.Vector3();
  const wrapA = (a) => Math.atan2(Math.sin(a), Math.cos(a));
  const smooth = (a, b, x) => { const u = clamp((x - a) / (b - a), 0, 1); return u * u * (3 - 2 * u); };
  const escHTML = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  // ---------- the lines (all warm and generic; the facts only ever come from /api/chatter) ----------
  const LINES = {
    tipOpen: ['Hey! Quick tip from {team} 👋', 'Got a sec? {team} learned something 💡', 'Hi! Bringing a fresh lesson from {team} ✨', 'Knock knock! {team} has a tip for you 🚪',
      'Psst, a little {team} wisdom for you 🤫', 'Hey neighbour! {team} found this out 🔍', 'Hiya! Sharing what worked for {team} 🙌', 'Quick one from {team} before I forget 📝',
      'Hey team! {team} wanted you to hear this 📣', 'Hello! Fresh from the {team} room 🍃', 'Mind if I share a {team} lesson? 😊', 'Hi friends! {team} tried something 🧪',
      'Hey! Our {team} retro had a gem 💎', 'Tiny tip from {team}, might help 🌱', 'Hi! {team} thinks this helps you too 🤝', 'Hey hey! A note from {team} 🗒️',
      'Good timing! {team} has a lesson 📬', 'Hi! I come bearing a {team} tip 🎁', 'Hey! {team} wrote this down for you ✍️', 'Oh hi! Got a {team} lesson to pass on 🔁',
      '嗨！{team} has a tip 👋', 'Hey! Something {team} learned the hard way 😅', 'Hi! {team} says this one is worth it ⭐', 'Hello hello! {team} lesson incoming 🛬',
      'Hey! Saving you a step, from {team} 🪜', 'Hi! {team} asked me to share this 💌'],
    hiOpen: ['Hi neighbours! 👋', 'Just stopping by to say hi 😊', "Hey! How's your day going? ☀️", 'Hi! Stretching my legs a bit 🚶', 'Hello from down the walkway 👋',
      'Hey! Mind if I hang out a sec? 🙂', 'Hi! Came over for a change of scenery 🌿', 'Hey team, quick hello 🙌', '嗨！Just visiting 😄', 'Hi! Took the long way to the coffee ☕',
      'Knock knock, friendly visit 🚪', 'Hey! Your room looks so cozy 🪴'],
    react: ['Ooh, trying that on our next {work}!', 'Nice, saving that 📌', "Oh that's good. Thank you! 🙏", 'Huh, never thought of that 🤔', 'Writing that down right now ✍️',
      'That makes so much sense 💡', 'Love it. Passing it to the team 🙌', "Great tip! We'll try it today 🚀", 'Oh nice, that explains a lot 😮', 'Adding it to our checklist ✅',
      'Ha, we needed this one 😅', 'Thanks! Our next {work} gets this 🎯', 'Smart. Stealing it 😄', 'Good one! 收到 👍', 'Ooh, I like that a lot ✨',
      "Okay, that's going on a sticky note 🗒️", 'Perfect timing, thank you! ⏰', "That's a keeper 💎", "Noted! We'll test it 🧪", 'Oh wow, simple and smart 👏',
      "Yes! Let's do that 🙌", 'Brilliant, thanks for walking over 🚶', "That'll save us time ⏱️", "I'll tell the others at standup 📣", 'Makes our {work} better, thanks! 🌟',
      '辛苦啦！Thanks for sharing 😊'],
    close: ['Coffee later? ☕', 'Anytime! See you around 👋', 'Happy to help 😊', 'Back to my desk. Bye! 👋', 'Let me know how it goes 🤞', 'Teamwork! 🙌', 'Catch you at lunch 🥪',
      'Good luck with it! 🍀', 'See you on the walkway 🚶', 'Ping me if you try it 📨', "That's all, have fun! ✨", 'Gotta run, bye bye 👋', 'Okay, back to work 💪', 'Glad it helps 🌱',
      'See you later, neighbours 🏡', 'Onward! 🚀', 'Cheers! 🥤', 'Talk soon 💬', '加油！👊', "I'll bring snacks next time 🍪", 'Shout if you need anything 📣', 'Bye for now 😊',
      'High five! ✋', 'Keep it up, team 💜', 'Off I go! 🏃'],
    small: ["How's your morning going? ☀️", 'This coffee is the best part of today ☕', '辛苦啦！Take a breather 😊', 'I love how calm the office is today 🌿', 'Did you see the Brain glow earlier? ✨',
      'Stretch break, my back says thanks 🧘', 'The plants look happy today 🪴', 'Almost lunch? 🥪', "One sip and I'm back to it ☕", 'We should do a team walk later 🚶',
      'Your desk setup looks so cozy 🖥️', 'Small steps, every day 🌱', 'Remember to drink water 💧', "Third coffee. Don't tell anyone 🤫", 'Nice to see you! 👋',
      'The walkway lights look pretty today 💡', "加油！We've got this 💪", "Let's keep it simple today ✨", "Who picked this coffee? It's great ☕", 'Five minutes, then back to focus ⏳',
      'I like our little office 🏠', 'Good vibes only today 😊', 'Taking a tiny break, back soon 🕊️', 'Breathe in, breathe out 🌬️', '早上好！Good morning 🌞', 'This view of the Brain never gets old 🧠'],
    reply: ['Same here 😄', 'Haha, agreed!', 'Totally ☕', 'Right? 😊', 'So true 🌿', 'Yes please!', 'Love that 💜', 'Ha, me too', 'Good point 👍', '对呀！😄', "Couldn't agree more",
      'Exactly!', 'Mm-hm ☕', 'You said it ✨', "That's the spirit 💪", 'Oh nice! 🙌', 'Ooh, tell me more', 'I needed to hear that 😊', 'Big yes 👍', '哈哈 so true', 'Count me in!',
      'We should do that more 🌱', 'Agreed, 100% 💯', 'Ha! Fair 😄', 'Mood ☕'],
    solo: ['Ahh, much better ☕', "Coffee o'clock ☕", 'Mmm, fresh brew ☕', 'Recharging… 🔋', 'One sip, then back to it', 'Little break, big help 🌿', '辛苦啦 to me ☕', 'Smells amazing ☕',
      'Warm mug, happy me 😊', 'Brain fuel ☕🧠'],
    lunch: ['Lunch time 🥪', 'Smells so good in here 🍜', 'Refuelling 🍱', 'Best part of the day 😋', '吃饭啦！🍚', 'A quick bite, then back up ⬆️'],
    play: ['One more round 🕹️', 'High score incoming 🏆', 'Foosball rematch? ⚽', 'Just five minutes 🎮'],
    rest: ['Comfy 🛋️', 'Five minutes on the sofa 😌', 'Nice to sit down for a bit 🌿', 'Watching the big screen 📺', 'Little break, big help ☕', 'Recharging… 🔋'],
    busy: ["Oh, you're busy! Later 👋", "Looks like you're on it. Next time! 🙂", "Ah, deep in work. I'll come back ✌️", 'No worries, catch you later 😊'],
    stretch: ['Stretch time 🙆', 'Ahh, that feels good 🧘', 'Shoulders, meet the ceiling 🙌', 'Quick stretch, back to it 💪'],
    note: ['Saving this for everyone 🧠', 'Into the Brain it goes 📝', 'Noting that down for the team ✍️', 'One more note for the Brain ✨'],
    idea: ['Idea I keep thinking about: {t} 💭', 'What if we made: {t}? 💡', 'Been dreaming up: {t} ✨', 'Idea board pick: {t} 📌'],
    rule: ['Remember: {t}!', 'Friendly reminder: {t} 📏', 'Brand rule check: {t} ✅', 'Little reminder: {t} 😊'],
  };
  const WORK = { research: 'brief', scripts: 'script', social: 'post', creative: 'edit', analytics: 'report', shop: 'listing', dev: 'build', inbox: 'reply' };
  function pickFresh(pool) {                                                   // a random line not used in the last few picks of that pool
    const arr = LINES[pool], seen = LIFE.recent[pool] || (LIFE.recent[pool] = []);
    let i = Math.floor(Math.random() * arr.length);
    for (let k = 0; k < 6 && seen.includes(i); k++) i = Math.floor(Math.random() * arr.length);
    seen.push(i); if (seen.length > Math.min(10, arr.length - 2)) seen.shift();
    return arr[i];
  }
  const teamNameOf = (key) => (state.rooms[key] ? state.rooms[key].team.name : key || 'the office');
  const fillLine = (tpl, L) => tpl.replace('{team}', teamNameOf(L.room)).replace('{work}', WORK[L.room] || 'work');
  function shorten(text, n) {
    const s = String(text || '').replace(/\s+/g, ' ').trim();
    if (s.length <= n) return s;
    const cut = s.slice(0, n - 1), sp = cut.lastIndexOf(' ');
    return (sp > n * 0.6 ? cut.slice(0, sp) : cut).replace(/[\s,;:.–—-]+$/, '') + '…';
  }
  function ruleText(raw) {                                                     // "Titles: under 60 characters, …" → "titles under 60 characters, …"
    let r = String(raw || '').split(/;|\.\s/)[0].replace(/\s*\([^)]*\)/g, '').replace(/^([A-Z][\w ]{0,24}):\s*/, '$1 ').split(/:\s/)[0].trim();
    if (r.length > 1 && !/^[A-Z]{2}/.test(r)) r = r[0].toLowerCase() + r.slice(1);
    return shorten(r, 52);
  }
  // A small-talk line from the brain (an idea, a brand rule, a task done today, a lesson) or a warm generic one.
  function topicLine(L) {
    const pool = LIFE.topics.filter((x) => x && x.text && (x.kind !== 'lesson' || !x.teamKey || x.teamKey === L.room));
    if (pool.length && Math.random() < 0.6) {
      const x = pool[Math.floor(Math.random() * pool.length)];
      if (x.kind === 'idea') return { text: pickFresh('idea').replace('{t}', shorten(x.text, 36)), topic: x.text };
      if (x.kind === 'rule') return { text: pickFresh('rule').replace('{t}', ruleText(x.text)), topic: x.text };
      if (x.kind === 'done') return { text: x.teamKey === L.room ? `We just shipped: ${shorten(x.text, 42)} 🎉` : x.team ? `${x.team} just shipped: ${shorten(x.text, 38)} 🎉` : `Done today: ${shorten(x.text, 46)} ✅`, topic: x.text };
      if (x.kind === 'lesson') return { text: `${x.team || 'We'} learned: ${shorten(x.text, 50)}`, topic: x.text };
    }
    return { text: pickFresh('small'), topic: '' };
  }
  function tipLines(V, H, lesson) {
    return [{ who: 0, text: fillLine(pickFresh('tipOpen'), V) }, { who: 0, text: shorten(lesson.text, 70), tip: true }, { who: 1, text: fillLine(pickFresh('react'), H) }, { who: 0, text: pickFresh('close') }];
  }
  function socialLines(V, H, tl) {
    return [{ who: 0, text: pickFresh('hiOpen') }, { who: 0, text: tl.text }, { who: 1, text: pickFresh('reply') }, { who: 0, text: pickFresh('close') }];
  }
  function chatLines(A, B, tl) {
    const lines = [{ who: 0, text: tl.text }, { who: 1, text: pickFresh('reply') }];
    if (Math.random() < 0.7) { lines.push({ who: 1, text: topicLine(B).text }); lines.push({ who: 0, text: pickFresh('reply') }); }
    return lines;
  }
  function loadChatter() {
    if (!LIFE.on || document.hidden || state.paused) return;
    fetch('/api/chatter').then((r) => (r.ok ? r.json() : null)).then((d) => { if (d && Array.isArray(d.topics)) LIFE.topics = d.topics; }).catch(() => {});
  }

  // ---------- the waypoint graph ----------
  function lnode(x, y, z, o) {
    o = o || {};
    const n = { id: LIFE.nodes.length, p: new THREE.Vector3(x, y, z), adj: [], w: o.w || 0, spot: !!o.spot, room: o.room || null, faceTo: o.faceTo || null };
    LIFE.nodes.push(n); return n.id;
  }
  function ledge(a, b) { if (a == null || b == null || a === b) return; const A = LIFE.nodes[a], B = LIFE.nodes[b]; if (!A.adj.includes(b)) A.adj.push(b); if (!B.adj.includes(a)) B.adj.push(a); }
  let _rd = null, _rp = null, _rv = null;
  function route(from, to) {                                                   // Dijkstra over ~300 nodes, only when an action starts or is cut short
    const N = LIFE.nodes, n = N.length;
    if (from == null || to == null) return null;
    if (!_rd || _rd.length < n) { _rd = new Float64Array(n); _rp = new Int32Array(n); _rv = new Uint8Array(n); }
    _rd.fill(Infinity, 0, n); _rp.fill(-1, 0, n); _rv.fill(0, 0, n); _rd[from] = 0;
    for (;;) {
      let u = -1, best = Infinity;
      for (let i = 0; i < n; i++) if (!_rv[i] && _rd[i] < best) { best = _rd[i]; u = i; }
      if (u < 0 || u === to) break;
      _rv[u] = 1;
      if (N[u].spot && u !== from) continue;                                   // a spot is a dead end: never walk through someone's spot
      for (const v of N[u].adj) { const nd = best + N[u].p.distanceTo(N[v].p); if (nd < _rd[v]) { _rd[v] = nd; _rp[v] = u; } }
    }
    if (from !== to && _rp[to] < 0) return null;
    const path = [to]; let c = to; while (c !== from) { c = _rp[c]; path.push(c); }
    path.reverse(); path.dist = _rd[to]; return path;
  }
  const routeDist = (a, b) => { const r = route(a, b); return r ? r.dist : Infinity; };

  function buildLife() {
    const N = LIFE.nodes;
    const Ms = state.floors.map(() => new Merger(new THREE.MeshLambertMaterial({ vertexColors: true }))), GLs = state.floors.map(() => new Merger(new THREE.MeshBasicMaterial({ vertexColors: true })));
    // every floor: a corridor along the glass front, with a point in front of each room, the stairs and the core
    const XS = [-52, -40, -ROOM_X, -20, STAIR.x, 0, 7, 14, 20, ROOM_X, 40, 52];
    const corr = [];
    for (let f = 0; f < FLOORS; f++) {
      const y = f * FLOOR_H + WALK_Y, ids = XS.map((x) => lnode(x, y, CZ, { w: 0.9 }));
      for (let k = 1; k < ids.length; k++) ledge(ids[k - 1], ids[k]);
      corr.push(ids);
    }
    const corrAt = (f, x) => { let best = 0; XS.forEach((cx, k) => { if (Math.abs(cx - x) < Math.abs(XS[best] - x)) best = k; }); return corr[f][best]; };
    // the spiral stairs: a landing at the foot of each flight, then a helix of points up to the next floor's landing
    const WR = 1.9;
    let last = null;
    for (let f = 0; f < FLOORS; f++) {
      const y = f * FLOOR_H + WALK_Y;
      const foot = lnode(STAIR.x, y, STAIR.z + WR), landing = lnode(STAIR.x, y, STAIR.z + STAIR.hole + 0.5, { w: 0.2 });
      ledge(foot, landing); ledge(landing, corrAt(f, STAIR.x));
      if (last != null) ledge(last, foot);
      if (f < ROOF) {
        let prev = foot;
        for (let k = 1; k < 12; k++) { const a = Math.PI / 2 + k * Math.PI / 6, id = lnode(STAIR.x + Math.cos(a) * WR, y + k / 12 * FLOOR_H, STAIR.z + Math.sin(a) * WR); ledge(prev, id); prev = id; }
        last = prev;
      }
    }
    {
      const hy = HALL * FLOOR_H + WALK_Y, seats = [], aisle = { L: [], R: [] };
      HALL_ROWS.forEach((z, r) => {
        const lane = HALL_COLS.map((x) => lnode(x, hy, z + 1.9));
        for (let k = 1; k < lane.length; k++) ledge(lane[k - 1], lane[k]);
        aisle.L.push(lnode(14.8, hy, z + 1.9)); aisle.R.push(lnode(57.6, hy, z + 1.9));
        ledge(aisle.L[r], lane[0]); ledge(aisle.R[r], lane[lane.length - 1]);
        HALL_COLS.forEach((x, k) => { const id = lnode(x, hy, z + 0.1, { spot: true, faceTo: new THREE.Vector3(x, hy, -60) }); LIFE.nodes[id].sit = true; ledge(id, lane[k]); seats.push(id); });
      });
      for (const side of ['L', 'R']) { const a = aisle[side]; for (let k = 1; k < a.length; k++) ledge(a[k - 1], a[k]); ledge(a[a.length - 1], corrAt(HALL, side === 'L' ? 14 : 52)); }
      LIFE.hall = { seats };
    }
    for (const room of state.roomList) {
      const lay = room.big ? LIFE_LAYOUT.creative : LIFE_LAYOUT.normal, h = room.half, cx = room.center.x, cz = room.center.z, key = room.key, F = room.y + SLAB_H;
      const M = Ms[room.floor], GL = GLs[room.floor];
      const R = (lx, lz, o) => lnode(cx + lx, F, cz + lz, Object.assign({ room: key }, o || {}));
      const lanes = {};
      for (const k of Object.keys(lay.lanes)) lanes[k] = R(lay.lanes[k][0], lay.lanes[k][1]);
      lay.edges.split(' ').forEach((e) => { const ab = e.split('-'); ledge(lanes[ab[0]], lanes[ab[1]]); });
      const joinLanes = (id, names) => names.split(' ').forEach((nm) => { if (lanes[nm] != null) ledge(id, lanes[nm]); });
      const j = corrAt(room.floor, cx), door = R(0, h - 1.2);
      ledge(j, door); joinLanes(door, 'FM');
      // desks: a stand spot beside the chair and a guest spot for a visitor, facing each other. The guest stands
      // across the screen from the host, so the pair reads side by side and neither hides the other.
      for (const seat of room.seats) {
        const st = new THREE.Vector3(1.5, 0, 1.9).applyMatrix4(seat.unit), side = Math.abs(wrapA(seat.ch.group.rotation.y - Math.PI)) > 0.5 ? -1 : 1;
        const gu = st.clone().add(new THREE.Vector3(-1.6 * side, 0, 1.6 * side));
        const sId = R(st.x - cx, st.z - cz, { spot: true }), gId = R(gu.x - cx, gu.z - cz, { spot: true });
        const ln = lay.slots[seat.slotKey] || 'MM';
        joinLanes(sId, ln); joinLanes(gId, ln);
        N[gId].faceTo = N[sId].p; N[sId].faceTo = N[gId].p;
        makeActor(seat, sId, gId);
      }
      // the coffee corner: a cabinet against the left wall with a machine, a cup under the spout and clean cups
      const wx = cx + lay.counter[0], wz = cz + lay.counter[1], cupC = [0xffffff, col(room.team.accent || room.color).getHex(), 0xf2c94c];
      M.box(1.2, 1.5, 2.2, wx, F + 0.75, wz, 0xefe9df); M.box(1.32, 0.1, 2.32, wx, F + 1.55, wz, 0x8a6a4a);
      M.box(0.02, 0.9, 1.9, wx + 0.61, F + 0.75, wz, 0xd9d1c4);
      M.box(0.72, 0.95, 0.62, wx - 0.14, F + 2.08, wz - 0.5, 0x2b2e36); M.box(0.32, 0.1, 0.4, wx + 0.18, F + 1.65, wz - 0.5, 0x15161a);
      M.box(0.22, 0.14, 0.2, wx + 0.18, F + 2.3, wz - 0.5, 0x3a3e48); M.cyl(0.11, 0.2, wx + 0.18, F + 1.8, wz - 0.5, 0xffffff);
      GL.ball(0.05, wx + 0.23, F + 2.45, wz - 0.28, 0x7dffb0);
      for (let k = 0; k < 3; k++) M.cyl(0.12, 0.22, wx + 0.12, F + 1.71, wz + 0.3 + k * 0.32, cupC[k]);
      const counterAt = new THREE.Vector3(wx, F, wz);
      const coffee = lay.coffee.map((c) => R(c[0], c[1], { spot: true, faceTo: counterAt }));
      coffee.forEach((id) => joinLanes(id, lay.coffeeLanes));
      // two phone spots near the open front edge (pace between them) and a note spot at the glass front: the note
      // flies out over the plaza into the Brain
      const phone = lay.phone.map((c) => { const id = R(c[0], c[1], { spot: true }); joinLanes(id, c[2]); return id; });
      ledge(phone[0], phone[1]);
      const ny = room.y + WALK_Y, note = lnode(cx + 6, ny, DZ - 1.2, { spot: true, faceTo: new THREE.Vector3(cx + 6, ny, DZ + 30) });
      ledge(note, j);
      LIFE.rooms[key] = { room, lanes, door, coffee, phone, note, junction: j };
    }
    // the commons: their lanes, spots (sit / food / play / bar) and the door from the corridor
    for (const C of state.commons) {
      const cx = C.center.x, cz = C.center.z, F = C.y + (C.key === 'cafe' ? WALK_Y : SLAB_H);
      const R = (lx, lz, o) => lnode(cx + lx, F + ((o && o.dy) || 0), cz + lz, Object.assign({ room: C.key }, o || {}));
      const lanes = {};
      for (const k of Object.keys(C.lanes)) lanes[k] = R(C.lanes[k][0], C.lanes[k][1]);
      C.edges.split(' ').forEach((e) => { const ab = e.split('-'); ledge(lanes[ab[0]], lanes[ab[1]]); });
      const dp = C.door || [0, C.half - 1.2], door = R(dp[0], dp[1]);
      ledge(door, corrAt(C.floor, cx + dp[0]));
      (C.doorLanes || 'FM').split(' ').forEach((nm) => { if (lanes[nm] != null) ledge(door, lanes[nm]); });
      const out = { key: C.key, sits: [], food: [] };
      for (const sp of C.spots) {
        const id = R(sp.x, sp.z, { spot: true, dy: sp.y, faceTo: sp.face ? new THREE.Vector3(cx + sp.face[0], F, cz + sp.face[1]) : null });
        N[id].sit = sp.sit; if (lanes[sp.lane] != null) ledge(id, lanes[sp.lane]);
        if (sp.list === 'bar') LIFE.bar.push(id); else out[sp.list === 'play' ? 'sits' : sp.list].push(id);
      }
      if (out.sits.length) LIFE.commons[C.key] = out;
    }
    Ms.forEach((m, f) => state.floors[f].add(m.mesh())); GLs.forEach((m, f) => state.floors[f].add(m.mesh()));
    // the note particles that fly into the Brain, and the ring wave of its pulse
    for (let k = 0; k < 3; k++) {
      const sp = new THREE.Sprite(new THREE.SpriteMaterial({ map: glowTex, color: 0xa8ecff, transparent: true, opacity: 0.95, blending: THREE.AdditiveBlending, depthWrite: false }));
      sp.scale.set(1.1, 1.1, 1); sp.visible = false; scene.add(sp);
      LIFE.notes.push({ sprite: sp, active: false, t: 0, from: new THREE.Vector3(), ctrl: new THREE.Vector3(), to: new THREE.Vector3(BRAIN.x, CORE_Y, BRAIN.z) });
    }
    const waves = [0, 1].map(() => { const m = new THREE.Mesh(new THREE.RingGeometry(0.86, 1.0, 72), new THREE.MeshBasicMaterial({ color: 0xc8f4ff, transparent: true, opacity: 0, blending: THREE.AdditiveBlending, depthWrite: false, side: THREE.DoubleSide })); m.rotation.x = -Math.PI / 2; m.position.set(BRAIN.x, 2.42, BRAIN.z); m.visible = false; scene.add(m); return m; });
    LIFE.wave = { meshes: waves, t: -1 };
    LIFE.ready = true;
    loadChatter(); LIFE.chatterTimer = setInterval(loadChatter, 60000);
  }

  // ---------- actors ----------
  function makeActor(seat, standId, guestId) {
    const ch = seat.ch, r = rng(hash('life:' + seat.agent.name));
    const L = {
      seat, name: seat.agent.name, room: seat.room.key, stand: standId, guest: guestId,
      cp: ch.group.position.clone(), chairYaw: ch.group.rotation.y, base: ch.group.position.clone(), off: new THREE.Vector3(), pos: ch.group.position.clone(), p0: new THREE.Vector3(),
      yaw: ch.group.rotation.y, yaw0: 0, pose: 0, pose0: 0, mode: 'seated', steps: null, si: 0, st: 0, node: standId, inNext: false, homing: false, hurry: false,
      next: 3 + r() * 45, microNext: 4 + r() * 30, micro: null, phase: r() * 6.28, moving: false, speedNow: 0, running: false,
      anim: null, hasMug: false, hasPhone: false, icon: null, sayText: '', sayUntil: 0, talk: null, speaking: false, holds: [], reservedBy: null,
      action: null, topic: '', partner: null, visit: null, pair: null, cgroup: null, sip: 0,
      wL: 0, wR: 0, oL: 0, oLz: 0, oR: 0, oRz: 0, bCode: 0, bText: '', bClearAt: 0, mug: null, phone: null, puffs: null,
    };
    seat.life = L; LIFE.actors.push(L); LIFE.by[L.name] = L;
    makeAnchor('bubble', L.name, ch.group, new THREE.Vector3(0, 4.4, 0));   // the name pill's point; hud.css lifts the bubble over the pill
    labels.bubble[L.name].el.addEventListener('click', () => { const fn = api.onAgentClick; if (typeof fn === 'function') fn(L.name); else { select(L.name); focusAgent(L.name); } });
  }
  function mugOf(L) {
    if (L.mug) return L.mug;
    const m = new Merger(charMat), c = [0xffffff, 0xf2c94c, 0x7fc8ff, 0xff8fa3, 0x9be7b0][hash(L.name) % 5];
    m.add(CG.cyl, c, 0, 0, 0, { sx: 0.17, sy: 0.3, sz: 0.17 }); m.add(CG.cyl, 0x4a2e1c, 0, 0.14, 0, { sx: 0.14, sy: 0.03, sz: 0.14 });
    m.add(CG.glass, c, 0.19, 0, 0, { sx: 0.55, sy: 0.55, sz: 0.55 });
    const mesh = m.mesh(); mesh.matrixAutoUpdate = true;
    const g = new THREE.Group(); g.add(mesh); g.position.set(0, -1.12, 0.2); g.visible = false; L.seat.ch.parts.armR.add(g); L.mug = g;
    L.puffs = [0, 1, 2].map(() => { const sp = new THREE.Sprite(new THREE.SpriteMaterial({ map: glowTex, color: 0xffffff, transparent: true, opacity: 0, depthWrite: false })); sp.scale.set(0.42, 0.42, 1); sp.visible = false; scene.add(sp); return sp; });
    return g;
  }
  function phoneOf(L) {
    if (L.phone) return L.phone;
    const m = new Merger(charMat);
    // with the arm raised to the ear, arm-local -z points forward: the phone sits just in front of the hand, by the cheek
    m.add(rbox(0.22, 0.46, 0.1, 0.04), 0x1b1d24, 0, 0, 0); m.add(G.box, 0x6f93ff, 0, 0.02, -0.055, { sx: 0.16, sy: 0.34, sz: 0.01 });
    const mesh = m.mesh(); mesh.matrixAutoUpdate = true; mesh.position.set(0.14, -0.98, -0.2); mesh.visible = false;
    L.seat.ch.parts.armL.add(mesh); L.phone = mesh; return mesh;
  }

  // ---------- steps: rise, walk, face, wait, call, sit ----------
  const S_RISE = () => ({ t: 'rise' }), S_SIT = () => ({ t: 'sit' });
  const S_WALK = (to, speed) => ({ t: 'walk', to, speed: speed || WALK_SPEED });
  const S_FACE = (fn) => ({ t: 'face', fn });
  const S_WAIT = (dur, anim, until, max) => ({ t: 'wait', dur, anim, until, max });
  const S_CALL = (fn) => ({ t: 'call', fn });
  const S_PERCH = (to) => ({ t: 'perch', to });                                // sit down (0) or stand up (1) right where the agent is
  const faceNode = (L) => { const n = LIFE.nodes[L.node]; return n && n.faceTo ? Math.atan2(n.faceTo.x - L.base.x, n.faceTo.z - L.base.z) : null; };
  const faceActor = (P) => (L) => (P ? Math.atan2(P.base.x - L.base.x, P.base.z - L.base.z) : null);
  function runSteps(L, steps, action) { L.steps = steps; L.si = -1; L.mode = 'active'; L.action = action; L.t0 = LIFE.time; nextStep(L); }
  function nextStep(L) {
    L.inNext = true;
    for (;;) {
      L.si++; L.st = 0;
      const s = L.steps && L.steps[L.si];
      if (!s) { L.inNext = false; finishAction(L); return; }
      if (s.t === 'call') { s.fn(L); if (L.mode === 'seated') { L.inNext = false; return; } continue; }
      if (s.t === 'rise' || s.t === 'sit' || s.t === 'perch') { L.p0.copy(L.base); L.pose0 = L.pose; L.yaw0 = L.yaw; }
      if (s.t === 'walk' && !walkInit(L, s)) continue;
      if (s.t === 'wait' && s.anim !== undefined) L.anim = s.anim;
      break;
    }
    L.inNext = false;
  }
  function walkInit(L, s) {
    const ids = route(L.node, s.to);
    if (!ids) return false;
    const pts = ids.map((id) => LIFE.nodes[id].p), ws = ids.map((id) => LIFE.nodes[id].w);
    if (s.from) { pts.unshift(s.from); ids.unshift(-1); ws.unshift(0); }       // rerouted mid-walk: start where the agent stands
    if (pts.length < 2) { L.node = s.to; return false; }
    s.ids = ids; s.pts = pts; s.ws = ws; s.k = 0; s.d = 0; return true;
  }
  function turnTo(L, target, dt, rate) { L.yaw += wrapA(target - L.yaw) * Math.min(1, dt * rate); }
  function walkStep(L, s, dt) {
    let left = dt * s.speed, a = s.pts[s.k], b = s.pts[s.k + 1], len = a.distanceTo(b);
    L.moving = true; L.speedNow = s.speed;
    while (left > 0) {
      if (s.d + left < len) { s.d += left; left = 0; break; }
      left -= len - s.d; s.d = 0; s.k++;
      if (s.ids[s.k] >= 0) L.node = s.ids[s.k];
      if (s.k >= s.pts.length - 1) { L.base.copy(s.pts[s.k]); L.moving = false; nextStep(L); return; }
      a = s.pts[s.k]; b = s.pts[s.k + 1]; len = a.distanceTo(b);
    }
    const u = len > 1e-6 ? s.d / len : 1, dx = b.x - a.x, dz = b.z - a.z, flat = Math.hypot(dx, dz), inv = 1 / Math.max(1e-6, flat), w = Math.min(s.ws[s.k], s.ws[s.k + 1]);
    const ride = flat < 0.05;                                                  // the lift: straight up or down
    L.base.set(a.x + dx * u, a.y + (b.y - a.y) * (ride ? ease(u) : smooth(0.3, 0.7, u)), a.z + dz * u);
    _lo.set(-dz * inv * w, 0, dx * inv * w);                                   // keep to one side of a walkway or the ring, so walkers pass each other
    L.off.lerp(_lo, Math.min(1, dt * 3.5));
    if (ride) L.moving = false; else turnTo(L, Math.atan2(dx, dz), dt, 7);
  }
  function stepActor(L, dt) {
    const s = L.steps && L.steps[L.si];
    if (!s) { finishAction(L); return; }
    L.st += dt; L.moving = false;
    if (s.t === 'rise') {
      const u = Math.min(1, L.st / 0.85), to = LIFE.nodes[L.stand].p;
      L.pose = L.pose0 + (1 - L.pose0) * easeOut(Math.min(1, u / 0.6));
      L.base.lerpVectors(L.p0, to, ease(clamp((u - 0.25) / 0.75, 0, 1)));
      if (L.base.distanceToSquared(to) > 0.01 || u < 0.5) turnTo(L, Math.atan2(to.x - L.cp.x, to.z - L.cp.z), dt, 5);
      if (u >= 1) { L.node = L.stand; nextStep(L); }
    } else if (s.t === 'sit') {
      const u = Math.min(1, L.st / 0.85);
      L.base.lerpVectors(L.p0, L.cp, ease(Math.min(1, u / 0.7)));
      L.pose = L.pose0 * (1 - easeOut(clamp((u - 0.3) / 0.7, 0, 1)));
      L.yaw = L.yaw0 + wrapA(L.chairYaw - L.yaw0) * ease(u);
      if (u >= 1) nextStep(L);
    } else if (s.t === 'perch') {
      const u = Math.min(1, L.st / 0.7);
      L.pose = L.pose0 + (s.to - L.pose0) * ease(u);
      if (u >= 1) nextStep(L);
    } else if (s.t === 'walk') walkStep(L, s, dt);
    else if (s.t === 'face') { const y = s.fn(L); if (y != null) turnTo(L, y, dt, 7); if (L.st > 0.6) nextStep(L); }
    else if (s.t === 'wait') {
      const T = L.talk && !L.talk.done ? L.talk : null, P = T ? (T.a === L ? T.b : T.a) : null;
      if (P && L.anim !== 'pour') turnTo(L, Math.atan2(P.base.x - L.base.x, P.base.z - L.base.z), dt, 4);   // talkers turn to each other
      if ((L.st >= s.dur && (!s.until || s.until(L))) || (s.max && L.st >= s.max)) nextStep(L);
    }
    else nextStep(L);
    if (!L.moving) L.off.multiplyScalar(Math.max(0, 1 - dt * 4));
    L.pos.copy(L.base).add(L.off);
  }
  function release(L) { for (const id of L.holds) if (LIFE.taken[id] === L) delete LIFE.taken[id]; L.holds.length = 0; }
  function reserve(L, id) { if (id == null || (LIFE.taken[id] && LIFE.taken[id] !== L)) return false; LIFE.taken[id] = L; L.holds.push(id); return true; }
  const freeSpot = (ids) => ids.find((id) => !LIFE.taken[id]);
  function cleanupAction(L) {
    if (L.talk && !L.talk.done) endTalk(L.talk);
    if (L.pair) L.pair.state = 'done';
    if (L.visit) { const v = L.visit; v.done = true; v.bail = true; if (v.host.reservedBy === L && v.host.mode === 'seated') v.host.reservedBy = null; }
    if (L.action === 'host' && L.partner && L.partner.visit) L.partner.visit.done = true;
    L.hasPhone = false; L.hasMug = false; L.icon = null; L.anim = null; L.sayText = '';
    release(L);
  }
  // Back to the desk: a working agent hurries (life switched off: a calm walk). Mid-walk it turns at the nearer end of
  // its current segment, so the way home always follows the graph.
  function goHome(L, hurry) {
    if (L.mode === 'seated') return;
    L.homing = true; L.hurry = !!hurry;
    cleanupAction(L);
    const s = L.steps && L.steps[L.si];
    if (s && s.t === 'sit') { L.steps = [s]; L.si = 0; return; }              // already sitting down: let it finish
    let steps;
    if (s && s.t === 'rise') steps = [S_SIT()];
    else {
      let from = null, c = L.node;
      if (s && s.t === 'walk' && s.pts) {
        const A = s.ids[s.k], B = s.ids[s.k + 1];
        from = L.base.clone();
        if (A < 0) c = B;
        else { const da = from.distanceTo(s.pts[s.k]) + routeDist(A, L.stand), db = from.distanceTo(s.pts[s.k + 1]) + routeDist(B, L.stand); c = da <= db ? A : B; }
        L.node = c;
      }
      const w = S_WALK(L.stand, hurry ? HURRY_SPEED : WALK_SPEED); w.from = from;
      steps = (L.pose < 0.95 && !(s && s.t === 'walk') ? [S_PERCH(1)] : []).concat([w, S_SIT()]);
    }
    L.steps = steps; L.si = -1;
    if (!L.inNext) nextStep(L);
  }
  function finishAction(L) {
    cleanupAction(L);
    L.mode = 'seated'; L.steps = null; L.homing = false; L.hurry = false; L.moving = false; L.reservedBy = null;
    L.talk = null; L.pair = null; L.visit = null; L.partner = null; L.action = null; L.topic = ''; L.cgroup = null; L.wL = L.wR = 0;
    L.base.copy(L.cp); L.pos.copy(L.cp); L.off.set(0, 0, 0); L.yaw = L.chairYaw; L.pose = 0; L.node = L.stand;
    poseActor(L, 0, 0);
    const p = L.seat.ch.parts; p.armL.rotation.z = p.armR.rotation.z = 0; p.head.rotation.set(0, 0, 0);
    if (L.mug) L.mug.visible = false; if (L.phone) L.phone.visible = false; if (L.puffs) L.puffs.forEach((sp) => { sp.visible = false; });
    L.next = (state.phone ? 45 : 22) + Math.random() * (state.phone ? 80 : 55);
  }

  // ---------- talks and bubbles ----------
  function say(L, text, dur) { L.sayText = text; L.sayUntil = LIFE.time + dur; }
  function startTalk(a, b, lines, topic, kind, onEnd) {
    const T = { a, b, lines, i: -1, t: 0, dur: 0, topic: topic || '', kind, done: false, onEnd };
    a.talk = T; a.topic = T.topic; a.partner = b || a.partner;
    if (b) { b.talk = T; b.topic = T.topic; b.partner = a; }
    LIFE.talkers[a.name] = true; if (b) LIFE.talkers[b.name] = true;
    LIFE.talks.push(T); nextLine(T); return T;
  }
  function nextLine(T) {
    T.i++; T.t = 0;
    const ln = T.lines[T.i];
    if (!ln || (ln.who && !T.b)) { endTalk(T); return; }
    const sp = ln.who ? T.b : T.a, ls = ln.who ? T.a : T.b;
    T.dur = clamp(2.3 + ln.text.length * 0.034, 2.6, 4.7);
    say(sp, ln.text, T.dur); sp.speaking = true;
    if (ls) { ls.speaking = false; ls.sayText = ''; }
    if (ln.tip && T.b) emitLife({ type: 'tip', from: teamNameOf(T.a.room), fromKey: T.a.room, to: teamNameOf(T.b.room), toKey: T.b.room, text: T.topic, visitor: T.a.name, host: T.b.name });
  }
  function endTalk(T) {
    if (T.done) return;
    T.done = true;
    for (const P of [T.a, T.b]) if (P) { P.speaking = false; if (P.talk === T) P.sayText = ''; delete LIFE.talkers[P.name]; }
    const i = LIFE.talks.indexOf(T); if (i >= 0) LIFE.talks.splice(i, 1);
    if (T.onEnd) T.onEnd();
  }
  function updateTalks(dt) {
    for (let i = LIFE.talks.length - 1; i >= 0; i--) { const T = LIFE.talks[i]; if (!T) continue; T.t += dt; if (T.t >= T.dur + 0.35) nextLine(T); }
  }
  function emitLife(ev) { const fn = api.onLife; if (typeof fn === 'function') { try { fn(ev); } catch (e) { /* the HUD's problem */ } } }
  // 0 nothing · 1 the text · 2 the pair's 💬 · 3 an icon (📞 📝). The DOM only changes when the code or the text does.
  function updateBubbles() {
    const lim = state.phone ? 2 : 6, nearD = (state.phone ? 82 : 96) * state.fit, now = performance.now();
    let shown = 0;
    for (const L of LIFE.actors) {
      let code = 0, text = '';
      if (L.sayText && LIFE.time >= L.sayUntil) L.sayText = '';
      if (L.mode !== 'seated' || L.sayText) {
        _lw.copy(L.pos); _lw.y += 5.4;
        const near = _lw.distanceTo(camera.position) < nearD, talking = !!(L.talk && !L.talk.done);
        if (L.sayText && near && shown < lim) { code = 1; text = L.sayText; shown++; }
        else if (talking && !near && L.talk.a === L && L.talk.b) { code = 2; text = '💬'; }   // from afar: one small icon per pair
        else if (L.icon && (near || L.icon === '📞')) { code = 3; text = L.icon; }
      }
      if (code === L.bCode && text === L.bText) { if (L.bClearAt && now >= L.bClearAt) { setLabel('bubble', L.name, ''); L.bClearAt = 0; } continue; }
      const lbl = labels.bubble[L.name];
      if (!code) {                                                             // fade out, then empty the label
        const inner = lbl && lbl.el.firstElementChild; if (inner) inner.classList.add('bye');
        L.bClearAt = now + 260;
      } else {
        const tc = state.rooms[L.room] ? (state.rooms[L.room].team.accent || state.rooms[L.room].color) : '#7b6cf6';
        setLabel('bubble', L.name, `<div class="hq-bubble${code === 1 ? (LIFE.talkers[L.name] ? ' talk' : '') : ' icon'}${code === 2 ? ' pair' : ''}" style="--bc:${tc}" title="${code === 1 ? '' : 'Office life · click to see who is talking'}">${escHTML(text)}</div>`);
        L.bClearAt = 0;
      }
      L.bCode = code; L.bText = text;
    }
  }

  // ---------- the actions ----------
  function actStretch(L) {
    const steps = [S_RISE(), S_WAIT(2.9, 'stretch'), S_WAIT(0.5, null), S_SIT()];
    if (Math.random() < 0.35) steps.splice(1, 0, S_CALL((A) => say(A, pickFresh('stretch'), 2.6)));
    runSteps(L, steps, 'stretch'); return true;
  }
  function actCoffee(L, opts) {
    const R = LIFE.rooms[L.room], bar = opts && opts.where ? opts.where === 'bar' : Math.random() < 0.22;
    let spot = bar ? freeSpot(LIFE.bar) : freeSpot(R.coffee);
    if (spot == null) spot = bar ? freeSpot(R.coffee) : freeSpot(LIFE.bar);
    if (spot == null || !reserve(L, spot)) return false;
    const group = LIFE.bar.includes(spot) ? 'bar' : L.room;
    // pour at the machine, then turn into the room with the mug (at the bar: stay facing the counter, toward the camera)
    const sipFace = (A) => { const P = A.talk && !A.talk.done ? (A.talk.a === A ? A.talk.b : A.talk.a) : null; if (P) return Math.atan2(P.base.x - A.base.x, P.base.z - A.base.z); const y = faceNode(A); return y == null ? null : group === 'bar' ? y : y + Math.PI * 0.85; };
    runSteps(L, [S_RISE(), S_WALK(spot), S_FACE(faceNode), S_WAIT(0.9, 'pour'), S_CALL((A) => { A.hasMug = true; mugOf(A); }), S_WAIT(0.5, 'pour'),
      S_CALL((A) => arriveCoffee(A, group)), S_FACE(sipFace), S_WAIT(8 + Math.random() * 5, 'sip', (A) => !A.talk || A.talk.done, 32), S_CALL((A) => { A.anim = null; }), S_WALK(L.stand), S_SIT()], 'coffee');
    return true;
  }
  function arriveCoffee(L, group) {
    L.hasMug = true; L.cgroup = group; L.sip = Math.random() * 2; mugOf(L);
    const other = LIFE.actors.find((M) => M !== L && M.cgroup === group && M.hasMug && M.mode === 'active' && !M.homing && (!M.talk || M.talk.done) && M.steps && M.steps[M.si] && M.steps[M.si].t === 'wait');
    if (other && Math.random() < 0.8) {
      const tl = topicLine(L), lines = [{ who: 0, text: tl.text }, { who: 1, text: pickFresh('reply') }];
      if (Math.random() < 0.5) lines.push({ who: 1, text: pickFresh('small') });
      startTalk(L, other, lines, tl.topic || 'coffee break small talk', 'coffee');
    } else if (Math.random() < 0.5) say(L, pickFresh('solo'), 3.4);
  }
  function actPhone(L) {
    const R = LIFE.rooms[L.room];
    if (LIFE.taken[R.phone[0]] || LIFE.taken[R.phone[1]]) return false;
    reserve(L, R.phone[0]); reserve(L, R.phone[1]);
    const steps = [S_RISE(), S_WALK(R.phone[0]), S_CALL((A) => { A.hasPhone = true; A.icon = '📞'; phoneOf(A); }), S_WAIT(1.4, 'phone')];
    const laps = 2 + Math.floor(Math.random() * 2);
    for (let k = 0; k < laps; k++) steps.push(S_WALK(R.phone[1], PACE_SPEED), S_WAIT(1.3, 'phone'), S_WALK(R.phone[0], PACE_SPEED), S_WAIT(1.3, 'phone'));
    steps.push(S_CALL((A) => { A.hasPhone = false; A.icon = null; A.anim = null; }), S_WALK(L.stand), S_SIT());
    runSteps(L, steps, 'phone'); return true;
  }
  function actNote(L) {
    const R = LIFE.rooms[L.room];
    if (!reserve(L, R.note)) return false;
    runSteps(L, [S_RISE(), S_WALK(R.note), S_FACE(faceNode), S_WAIT(0.4, null), S_CALL((A) => { A.icon = '📝'; if (Math.random() < 0.5) say(A, pickFresh('note'), 2.8); }),
      S_WAIT(0.45, 'note'), S_CALL(launchNote), S_WAIT(1.9, 'note'), S_CALL((A) => { A.icon = null; A.anim = null; }), S_WALK(L.stand), S_SIT()], 'note');
    return true;
  }
  // A break downstairs: lunch in the canteen (a plate from the kitchen counter first), the lounge sofas and bean bags,
  // or the town hall steps. Whoever is already there on a break gets a chat; the lift takes them down and back up.
  function actBreak(L, opts) {
    const want = opts && opts.where, weights = { canteen: 0.4, lounge: 0.3, terrace: 0.22, gameroom: 0.18 };
    const pool = Object.values(LIFE.commons).filter((c) => (!want || c.key === want) && freeSpot(c.sits) != null);
    if (!pool.length) return false;
    let x = Math.random() * pool.reduce((t, c) => t + (weights[c.key] || 0.1), 0), C = pool[0];
    for (const c of pool) { if ((x -= weights[c.key] || 0.1) <= 0) { C = c; break; } }
    const seatId = freeSpot(C.sits);
    if (seatId == null || !reserve(L, seatId)) return false;
    const steps = [S_RISE()];
    const food = C.food.length ? freeSpot(C.food) : null;
    if (food != null && reserve(L, food)) steps.push(S_WALK(food), S_FACE(faceNode), S_WAIT(1.3, 'pour'), S_CALL((A) => { A.hasMug = true; mugOf(A); }), S_WAIT(0.4, 'pour'));
    const sit = LIFE.nodes[seatId].sit;
    steps.push(S_WALK(seatId), S_FACE(faceNode));
    if (sit) steps.push(S_PERCH(0));
    steps.push(S_CALL((A) => arriveBreak(A, C.key)), S_WAIT(11 + Math.random() * 9, undefined, (A) => !A.talk || A.talk.done, 40), S_CALL((A) => { A.anim = null; }));
    if (sit) steps.push(S_PERCH(1));
    steps.push(S_CALL((A) => { A.hasMug = false; }), S_WALK(L.stand), S_SIT());
    runSteps(L, steps, 'break'); return true;
  }
  function arriveBreak(L, key) {
    L.cgroup = 'break:' + key; L.anim = L.hasMug ? 'sip' : 'listen'; L.sip = Math.random() * 2;
    const other = LIFE.actors.find((M) => M !== L && M.cgroup === L.cgroup && M.mode === 'active' && !M.homing && (!M.talk || M.talk.done) && M.steps && M.steps[M.si] && M.steps[M.si].t === 'wait');
    if (other && Math.random() < 0.85) {
      const tl = topicLine(L), lines = [{ who: 0, text: tl.text }, { who: 1, text: pickFresh('reply') }];
      if (Math.random() < 0.6) { lines.push({ who: 1, text: topicLine(other).text }); lines.push({ who: 0, text: pickFresh('reply') }); }
      startTalk(L, other, lines, tl.topic || 'a break downstairs', 'break');
    } else if (Math.random() < 0.5) say(L, pickFresh(key === 'canteen' ? 'lunch' : key === 'gameroom' ? 'play' : 'rest'), 3.2);
  }
  const isFree = (A) => A.mode === 'seated' && !A.running && !A.reservedBy && LIFE.on;
  function freeHost(roomKey, not) {
    const list = LIFE.actors.filter((A) => A.room === roomKey && A !== not && isFree(A) && !LIFE.taken[A.guest]);
    return list.length ? list[Math.floor(Math.random() * list.length)] : null;
  }
  function actChat(L, opts) {
    const R = LIFE.rooms[L.room];
    if (LIFE.taken[R.coffee[0]] || LIFE.taken[R.coffee[1]]) return false;
    const B = (opts && opts.with && LIFE.by[opts.with] && isFree(LIFE.by[opts.with]) && LIFE.by[opts.with]) || freeHost(L.room, L);
    if (!B) return false;
    reserve(L, R.coffee[0]); reserve(B, R.coffee[1]);
    const pair = { a: L, b: B, arrived: 0, state: 'gather' };
    L.pair = B.pair = pair; L.partner = B; B.partner = L;
    const arrive = () => { pair.arrived++; if (pair.arrived === 2 && pair.state === 'gather') { pair.state = 'talk'; const tl = topicLine(L); startTalk(L, B, chatLines(L, B, tl), tl.topic || 'a coffee-machine chat', 'chat', () => { pair.state = 'done'; }); } };
    const tail = (A) => [S_WAIT(0.2, 'listen', () => pair.state === 'done', 45), S_CALL((X) => { X.anim = null; if (pair.arrived < 2 && Math.random() < 0.6) say(X, pickFresh('busy'), 2.6); }), S_WAIT(pair.arrived < 2 ? 0.6 : 0.2, null), S_WALK(A.stand), S_SIT()];
    runSteps(L, [S_RISE(), S_WALK(R.coffee[0]), S_FACE(faceActor(B)), S_CALL(arrive)].concat(tail(L)), 'chat');
    runSteps(B, [S_WAIT(0.5 + Math.random() * 0.6, null), S_RISE(), S_WALK(R.coffee[1]), S_FACE(faceActor(L)), S_CALL(arrive)].concat(tail(B)), 'chat');
    return true;
  }
  // A visit with a purpose: a lesson this agent's team learned that is tagged for another team; else a neighbourly hello.
  function actVisit(V, opts) {
    let host = null, lesson = null;
    if (opts && opts.to && opts.to !== V.room) host = (opts.host && LIFE.by[opts.host] && LIFE.by[opts.host].room === opts.to && isFree(LIFE.by[opts.host]) && LIFE.by[opts.host]) || freeHost(opts.to);
    const lessons = LIFE.topics.filter((x) => x && x.kind === 'lesson' && x.teamKey === V.room && x.text);
    for (let k = lessons.length - 1; k > 0; k--) { const j = Math.floor(Math.random() * (k + 1)); const tmp = lessons[k]; lessons[k] = lessons[j]; lessons[j] = tmp; }
    if (host) lesson = lessons.find((x) => (x.forKeys || []).includes(host.room)) || null;
    else for (const ls of lessons) { for (const k of ls.forKeys || []) { if (k !== V.room) host = freeHost(k); if (host) break; } if (host) { lesson = ls; break; } }
    if (!host) {                                                               // no lesson for anyone: a hello, neighbours more likely
      const me = state.rooms[V.room], others = state.roomList.filter((r) => r.key !== V.room);
      const weights = others.map((r) => { const steps = Math.abs(wrapA((r.index - me.index) * Math.PI / 4)) / (Math.PI / 4) + 3 * Math.abs(r.floor - me.floor); return 1 / (0.6 + steps); });
      for (let tries = 0; tries < 4 && !host; tries++) { let x = Math.random() * weights.reduce((s, w) => s + w, 0), pick = others[0]; for (let i = 0; i < others.length; i++) { if ((x -= weights[i]) <= 0) { pick = others[i]; break; } } host = freeHost(pick.key); }
      if (host) { const fit = lessons.find((x) => !(x.forKeys || []).length); if (fit && Math.random() < 0.5) lesson = fit; }
    }
    if (!host || !reserve(V, host.guest)) return false;
    host.reservedBy = V;
    const tl = lesson ? null : topicLine(V);
    const v = V.visit = { host, lesson, tl, ready: false, done: false, bail: false, doneAt: 0 };
    V.partner = host; V.topic = lesson ? lesson.text : (tl.topic || 'a friendly hello');
    const knock = (A) => {
      if (host.reservedBy !== A || host.running || host.mode !== 'seated' || !LIFE.on) { v.bail = true; say(A, pickFresh('busy'), 2.6); v.doneAt = LIFE.time + 2.7; return; }
      host.partner = A; host.topic = A.topic;
      runSteps(host, [S_RISE(), S_CALL(() => { v.ready = true; }), S_FACE(faceActor(A)), S_WAIT(0.2, 'listen', () => v.done, 34), S_WAIT(0.5, null), S_SIT()], 'host');
    };
    const talk = (A) => {
      if (v.bail || !v.ready || v.done) { v.done = v.done || !v.bail; return; }
      startTalk(A, host, lesson ? tipLines(A, host, lesson) : socialLines(A, host, tl), A.topic, 'visit', () => { v.done = true; });
    };
    runSteps(V, [S_RISE(), S_WALK(host.guest), S_FACE(faceActor(host)), S_CALL(knock), S_WAIT(0.3, 'listen', () => v.ready || v.bail || v.done, 4), S_FACE(faceActor(host)), S_CALL(talk),
      S_WAIT(0.2, 'listen', () => v.done || (v.bail && LIFE.time >= v.doneAt), 32), S_CALL((A) => { A.anim = null; v.done = true; }), S_WAIT(0.3, null), S_WALK(V.stand), S_SIT()], 'visit');
    return true;
  }
  function startAction(L, kind, opts) {
    if (!kind) {
      const w = [['coffee', 0.2], ['stretch', 0.16], ['visit', 0.2], ['break', 0.16], ['phone', 0.1], ['chat', 0.1], ['note', 0.08]];
      let x = Math.random(); kind = 'stretch';
      for (const [k, v] of w) { if ((x -= v) <= 0) { kind = k; break; } }
    }
    const fn = { coffee: actCoffee, stretch: actStretch, visit: actVisit, phone: actPhone, chat: actChat, note: actNote, break: actBreak }[kind];
    return fn ? !!fn(L, opts) : false;
  }

  // ---------- poses ----------
  function poseActor(L, dt, t) {
    const ch = L.seat.ch, p = ch.parts, b = L.pose, sb = 1 - b, lift = 0.1 * sb, s = L.steps && L.steps[L.si];
    p.torso.position.y = lift; p.head.position.y = 2.3 + lift; p.armL.position.y = p.armR.position.y = 2.12 + lift; p.hipL.position.y = p.hipR.position.y = 1.05 + lift;
    let swing = 0, bob = 0, toe = 0;
    if (L.moving) {
      L.phase += dt * (1.4 + L.speedNow * 2.25);
      const amp = L.hurry ? 0.62 : L.speedNow < 1.2 ? 0.28 : 0.5;
      swing = Math.sin(L.phase) * amp; bob = Math.abs(Math.sin(L.phase)) * (L.hurry ? 0.08 : 0.055);
    }
    p.hipL.rotation.x = HIP_S * sb + swing * b; p.hipR.rotation.x = HIP_S * sb - swing * b;
    p.kneeL.rotation.x = KNEE_S * sb + Math.max(0, -swing) * 1.2 * b; p.kneeR.rotation.x = KNEE_S * sb + Math.max(0, swing) * 1.2 * b;
    // arms: the walk swing (or a small idle sway), then the action's pose blended in (mug, phone, stretch, talk, note)
    const idle = L.moving ? 0 : Math.sin(t * 1.3 + L.phase) * 0.05;
    const aL = ARM_S * sb + (-swing * 0.7 + idle) * b, aR = ARM_S * sb + (swing * 0.7 - idle) * b;
    let oL = null, oLz = 0, oR = null, oRz = 0, hx = 0, hy = 0, sipK = 0;
    const st = L.st, an = L.anim;
    if (an === 'stretch' && s && s.t === 'wait') {
      const e = Math.min(clamp(st / 0.7, 0, 1), clamp((s.dur - st) / 0.7, 0, 1)), k = ease(e);
      oL = oR = -3.05 * k; oLz = -0.38 * k; oRz = 0.38 * k; hx = -0.28 * k; toe = 0.06 * k;
    }
    if (L.hasPhone) { oL = -2.85; oLz = 0.16; hy = -0.12; }
    if (L.hasMug) {
      oR = -0.95; oRz = 0;
      if (an === 'sip' && !L.moving) {
        L.sip += dt; const c = (L.sip % 4.6) / 4.6;
        sipK = Math.sin(Math.PI * clamp(c / 0.34, 0, 1)); oR = -0.95 - 1.25 * sipK; oRz = -0.38 * sipK; hx = -0.14 * sipK;
      }
    }
    if (an === 'pour' && s && s.t === 'wait') { const e = Math.sin(Math.PI * clamp(L.st / 1.4, 0, 1)); oR = -1.25 * e - (L.hasMug ? 0.95 * (1 - e) : 0); hx = 0.12 * e; }
    if (an === 'note' && s && s.t === 'wait') { const e = Math.sin(Math.PI * clamp(st / 0.9, 0, 1)); oR = -2.6 * e; oRz = -0.1 * e; hx = -0.18; }
    const talking = L.talk && !L.talk.done;
    if (talking && L.speaking && !L.hasMug && !L.hasPhone) { oR = -0.55 + Math.sin(t * 5.3 + L.phase) * 0.3; oRz = -0.12; }
    if (talking) { hx += L.speaking ? Math.sin(t * 6.5 + L.phase) * 0.05 : 0.05 + Math.sin(t * 1.8 + L.phase) * 0.05; hy += L.speaking ? 0 : 0.1; }
    else if (an === 'listen') hx += 0.03;
    const kr = Math.min(1, dt * 7);
    L.wR += ((oR != null ? 1 : 0) - L.wR) * kr; if (oR != null) { L.oR = oR; L.oRz = oRz; }
    L.wL += ((oL != null ? 1 : 0) - L.wL) * kr; if (oL != null) { L.oL = oL; L.oLz = oLz; }
    p.armR.rotation.x = aR + (L.oR - aR) * L.wR * b; p.armR.rotation.z = L.oRz * L.wR * b;
    p.armL.rotation.x = aL + (L.oL - aL) * L.wL * b; p.armL.rotation.z = L.oLz * L.wL * b;
    p.head.rotation.x += (hx * b - p.head.rotation.x) * kr; p.head.rotation.y += (hy * b - p.head.rotation.y) * kr;
    ch.group.position.set(L.pos.x, L.pos.y + bob * b + toe, L.pos.z); ch.group.rotation.y = L.yaw;
    if (L.mug) { L.mug.visible = L.hasMug; if (L.hasMug) { L.mug.rotation.x = -p.armR.rotation.x * 0.94 - sipK * 0.45; L.mug.rotation.z = -p.armR.rotation.z; } }
    if (L.phone) L.phone.visible = L.hasPhone;
  }
  function lifeMicro(L, dtReal) {                                              // seated: a stretch with both arms up, or a look around
    const m = L.micro, p = L.seat.ch.parts;
    if (!LIFE.on || L.running) { L.micro = null; p.armL.rotation.z = p.armR.rotation.z = 0; return; }
    m.t += dtReal * LIFE.speed;
    const e = ease(Math.min(clamp(m.t / 0.6, 0, 1), clamp((m.dur - m.t) / 0.6, 0, 1)));
    if (m.kind === 'stretch') { p.armL.rotation.x = p.armR.rotation.x = ARM_S + (-3.0 - ARM_S) * e; p.armL.rotation.z = -0.3 * e; p.armR.rotation.z = 0.3 * e; p.head.rotation.x = -0.22 * e; }
    else p.head.rotation.y += m.dir * 0.55 * e;
    if (m.t >= m.dur) { L.micro = null; p.armL.rotation.z = p.armR.rotation.z = 0; }
  }
  function updateProps(t) {
    for (const L of LIFE.actors) {
      if (!L.puffs) continue;
      if (!L.hasMug || L.mode === 'seated') { if (L.puffs[0].visible) L.puffs.forEach((sp) => { sp.visible = false; }); continue; }
      L.mug.getWorldPosition(_lw);
      for (let k = 0; k < 3; k++) {
        const sp = L.puffs[k], c = (t * 0.55 + k / 3) % 1;
        sp.visible = true; sp.position.set(_lw.x + Math.sin(c * 6 + k * 2) * 0.1, _lw.y + 0.3 + c * 1.0, _lw.z + Math.cos(c * 5 + k) * 0.06);
        sp.material.opacity = 0.55 * (1 - c) * Math.min(1, c * 5); sp.scale.setScalar(0.32 + c * 0.5);
      }
    }
  }
  function launchNote(L) {
    const n = LIFE.notes.find((x) => !x.active); if (!n) { LIFE.pulse = 1; return; }
    L.seat.ch.parts.armR.localToWorld(n.from.set(0, -1.1, 0.15));
    n.ctrl.copy(n.from).lerp(n.to, 0.45); n.ctrl.y += 6;
    n.active = true; n.t = 0; n.sprite.visible = true; n.sprite.position.copy(n.from);
  }
  function updateNotes(dt) {
    for (const n of LIFE.notes) {
      if (!n.active) continue;
      n.t += dt / 1.25; const u = Math.min(1, n.t), iu = 1 - u;
      n.sprite.position.set(iu * iu * n.from.x + 2 * iu * u * n.ctrl.x + u * u * n.to.x, iu * iu * n.from.y + 2 * iu * u * n.ctrl.y + u * u * n.to.y, iu * iu * n.from.z + 2 * iu * u * n.ctrl.z + u * u * n.to.z);
      n.sprite.scale.setScalar(0.8 + Math.sin(u * Math.PI) * 0.7);
      if (u >= 1) { n.active = false; n.sprite.visible = false; LIFE.pulse = 1; if (LIFE.wave) LIFE.wave.t = 0; }
    }
    const W = LIFE.wave;                                                       // two rings ripple out over the Brain's inner disc
    if (W && W.t >= 0) {
      W.t += dt;
      W.meshes.forEach((m, k) => { const u = (W.t - k * 0.35) / 1.5; m.visible = u > 0 && u < 1; if (m.visible) { m.scale.setScalar(2.5 + easeOut(u) * 10.5); m.material.opacity = 0.95 * (1 - u); } });
      if (W.t > 1.9) W.t = -1;
    }
  }
  function lifePulse(dt) {                                                     // the Brain answers a note: the core, its glow and light swell once
    const k = LIFE.pulse, b = anim.brain;
    b.core.material.emissiveIntensity += 0.6 * k; b.glow.material.opacity = Math.min(1, b.glow.material.opacity + 0.35 * k);
    b.glow.scale.setScalar(7 * (1 + 0.55 * k)); b.light.intensity += 1.3 * k;
    LIFE.pulse = Math.max(0, k - dt * 0.9); LIFE.pulsed = LIFE.pulse > 0;
  }

  // ---------- the frame ----------
  function lifeUpdate(run, dtReal, t) {
    if (!LIFE.ready) return;
    const dt = dtReal * LIFE.speed;
    LIFE.time += dt; LIFE.max = state.phone ? 3 : 7;
    let active = 0;
    for (const L of LIFE.actors) {
      const on = !!run[L.name]; L.running = on;
      if (L.mode !== 'seated') { if ((on && !L.hurry) || (!LIFE.on && !L.homing)) goHome(L, on); active++; }
      else if (on && L.reservedBy) L.reservedBy = null;                       // a reserved host got work: the visitor finds them busy
    }
    updateTalks(dt);
    if (LIFE.on) meetingTick(run);
    if (LIFE.on && LIFE.auto && !MEET.on) for (const L of LIFE.actors) {
      if (L.mode !== 'seated' || L.running || L.reservedBy) continue;
      L.next -= dt;
      if (L.next <= 0) { if (active < LIFE.max && startAction(L)) active += L.action === 'chat' ? 2 : 1; else L.next = 4 + Math.random() * 9; }
      if (!L.micro && L.mode === 'seated') { L.microNext -= dt; if (L.microNext <= 0) { L.micro = { kind: Math.random() < 0.45 ? 'stretch' : 'look', t: 0, dur: 2.6, dir: Math.random() < 0.5 ? -1 : 1 }; L.microNext = 14 + Math.random() * 34; } }
    }
    for (const L of LIFE.actors) if (L.mode !== 'seated') { stepActor(L, dt); if (L.mode !== 'seated') poseActor(L, dt, t); }
    updateProps(t); updateNotes(dt); updateBubbles();
  }

  // ---------- the API: life(on|off), lifeOf(name), lifeState(), lifeDebug({speed, force, agent, to, with, graph}) ----------
  function lifeSwitch(on) {
    if (on === undefined) return LIFE.on;
    LIFE.on = !(on === false || on === 'off' || on === 0 || on === '0');
    if (LIFE.on) loadChatter();
    return LIFE.on;
  }
  function lifeOf(name) {
    const L = LIFE.by[name]; if (!L || L.mode === 'seated') return null;
    const T = L.talk && !L.talk.done ? L.talk : null, P = T ? (T.a === L ? T.b : T.a) : L.partner;
    const s = L.steps && L.steps[L.si];
    return { action: L.action, partner: P ? P.name : null, talking: !!(T && P), topic: (T && T.topic) || L.topic || '', step: s ? s.t : '', hurrying: L.hurry, homing: L.homing, done: !!((L.visit && L.visit.done) || (L.pair && L.pair.state === 'done')), mug: L.hasMug, phone: L.hasPhone, saying: L.sayText || '' };
  }
  function lifeState() {
    return { on: LIFE.on, ready: LIFE.ready, speed: LIFE.speed, max: LIFE.max, topics: LIFE.topics.length, talks: LIFE.talks.length,
      away: LIFE.actors.filter((L) => L.mode !== 'seated').map((L) => ({ name: L.name, action: L.action, step: L.steps && L.steps[L.si] ? L.steps[L.si].t : '', partner: L.partner ? L.partner.name : null, away: +(LIFE.time - (L.t0 || 0)).toFixed(1), x: +L.pos.x.toFixed(2), y: +L.pos.y.toFixed(2), z: +L.pos.z.toFixed(2) })) };
  }
  function lifeDebug(o) {
    o = o || {};
    if (o.speed != null) LIFE.speed = clamp(+o.speed || 1, 0.1, 20);
    if (o.auto != null) LIFE.auto = !!o.auto;                                // false: only forced actions (for tests)
    if (o.graph != null) {
      if (o.graph && !LIFE.debug) {
        const pts = [];
        for (const n of LIFE.nodes) for (const j of n.adj) if (j > n.id) { const m = LIFE.nodes[j]; pts.push(n.p.x, n.p.y + 0.12, n.p.z, m.p.x, m.p.y + 0.12, m.p.z); }
        const g = new THREE.BufferGeometry(); g.setAttribute('position', new THREE.Float32BufferAttribute(pts, 3));
        LIFE.debug = new THREE.LineSegments(g, new THREE.LineBasicMaterial({ color: 0xff3df2, depthTest: false, transparent: true })); LIFE.debug.renderOrder = 9; scene.add(LIFE.debug);
      } else if (!o.graph && LIFE.debug) { scene.remove(LIFE.debug); LIFE.debug = null; }
    }
    if (o.topics) LIFE.topics = o.topics;
    let res = { speed: LIFE.speed, auto: LIFE.auto, graph: !!LIFE.debug, nodes: LIFE.nodes.length };
    if (o.force) {
      let L = o.agent ? LIFE.by[o.agent] : null;
      if (L && !isFree(L)) return Object.assign(res, { ok: false, reason: o.agent + ' is busy' });
      if (!L) { const free = LIFE.actors.filter((A) => isFree(A) && (!o.room || A.room === o.room)); L = free[Math.floor(Math.random() * free.length)]; }
      if (!L) return Object.assign(res, { ok: false, reason: 'nobody is free' });
      const ok = startAction(L, o.force, o);
      res = Object.assign(res, { ok, agent: L.name, action: L.action, partner: L.partner ? L.partner.name : null, topic: L.topic });
    }
    return res;
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
    const maxD = state.labelRules.agentMaxDist * state.fit;
    for (const kind of ['agent', 'sub']) for (const key in labels[kind]) {
      const L = labels[kind][key]; if (!L.has) { L.obj.visible = false; continue; }
      L.obj.getWorldPosition(_w); L.obj.visible = _w.distanceTo(camera.position) < maxD && labelShown(floorOfY(_w.y - 4));
    }
    for (const kind of ['team', 'bubble', 'brain']) for (const key in labels[kind]) {  // a hidden or unfocused floor takes its labels along
      const L = labels[kind][key]; if (!L.has) continue;
      L.obj.getWorldPosition(_w); L.obj.visible = labelShown(floorOfY(_w.y - 6));
    }
  }
  function project(kind, key) {
    const L = labels[kind] && labels[kind][key];
    if (!L || !camera) return { x: 0, y: 0, visible: false };
    L.obj.getWorldPosition(_w);
    const dist = _w.distanceTo(camera.position);
    _w.project(camera);
    const x = (_w.x + 1) / 2 * state.size.w, y = (1 - _w.y) / 2 * state.size.h;
    const onScreen = _w.z > -1 && _w.z < 1 && x > -200 && x < state.size.w + 200 && y > -200 && y < state.size.h + 200 && labelShown(floorOfY(L.obj.getWorldPosition(_b).y - 5));
    return { x, y, visible: onScreen, dist, near: dist < state.labelRules.agentMaxDist * state.fit, scale: clamp(OVERVIEW.dist / Math.max(1, dist), 0.6, 2.2) };
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
    const dist = ROOM_VIEW.dist * (room.big ? 1.26 : 1) * (opts.zoom || 1) * state.fit;
    showFloor(room.floor);
    tweenTo({ yaw: OVERVIEW.yaw, pitch: ROOM_VIEW.pitch, dist, target: shiftTarget(new THREE.Vector3(room.center.x, room.y + 4.6, room.center.z + 3), dist, opts.shiftX) }, opts.duration || 950);
    return true;
  }
  function overview(opts) { opts = opts || {}; state.mode = 'overview'; showFloor(null); tweenTo({ yaw: OVERVIEW.yaw, pitch: OVERVIEW.pitch, dist: OVERVIEW.dist, target: shiftTarget(OVERVIEW.target.clone(), OVERVIEW.dist, opts.shiftX) }, opts.duration || 1100); }
  // The floor view: null shows the whole building; n hides every floor above n so you look straight into it.
  function showFloor(n) {
    n = n == null || n === 'all' || n === '' ? null : clamp(Math.round(+n), 0, FLOORS - 1);
    state.floorView = n;
    state.floors.forEach((g, f) => { g.visible = floorShown(f); });
    return n;
  }
  function viewFloor(n, opts) {                                               // the floor buttons: show a floor and frame it
    opts = opts || {};
    const v = showFloor(n);
    if (v == null) { overview(opts); return null; }
    state.mode = 'floor:' + v;
    const tanH = Math.tan(camera.fov * DEG / 2) * camera.aspect, d = (camera.aspect < 0.95 ? WX * 0.55 : WX + 4) / tanH;   // the whole floor across the frame
    tweenTo({ yaw: OVERVIEW.yaw, pitch: 12 * DEG, dist: d, target: shiftTarget(new THREE.Vector3(0, v * FLOOR_H + 5.5, 4), d, opts.shiftX) }, opts.duration || 1000);
    return v;
  }
  function focusAgent(name, opts) {
    const seat = state.seats[name]; if (!seat) return false;
    opts = opts || {};
    state.mode = 'agent:' + name; const p = seat.ch.group.position;
    const d = 34 * Math.sqrt(state.fit);
    showFloor(floorOfY(p.y));
    tweenTo({ yaw: OVERVIEW.yaw, pitch: 18 * DEG, dist: d, target: shiftTarget(new THREE.Vector3(p.x, p.y + 2.2, p.z), d, opts.shiftX) }, opts.duration || 900);
    return true;
  }
  function focusBrain(opts) { opts = opts || {}; state.mode = 'brain'; showFloor(0); const d = 76 * state.fitBrain; tweenTo({ yaw: OVERVIEW.yaw, pitch: 26 * DEG, dist: d, target: shiftTarget(new THREE.Vector3(BRAIN.x, 5, BRAIN.z), d, opts.shiftX) }, opts.duration || 1000); }
  function getZoomPercent() { return Math.round(OVERVIEW.dist / Math.max(1, currentView().dist) * 100); }
  function setZoomPercent(p) { const v = currentView(); p = clamp(+p || 100, 25, 900); tweenTo({ yaw: v.yaw, pitch: v.pitch, dist: OVERVIEW.dist * 100 / p, target: v.target }, 450); if (state.mode === 'overview') state.mode = 'free'; }
  function zoom(delta) { const v = currentView(); tweenTo({ yaw: v.yaw, pitch: v.pitch, dist: clamp(v.dist * Math.pow(0.82, +delta || 0), controls.minDistance, controls.maxDistance), target: v.target }, 400); if (state.mode === 'overview') state.mode = 'free'; }
  function fullscreen() { const el = host.parentElement || host; if (document.fullscreenElement) { document.exitFullscreen && document.exitFullscreen(); } else if (el.requestFullscreen) el.requestFullscreen().catch(() => {}); }
  function select(name) {
    state.selected = name || null;
    if (!state.selectRing) { state.selectRing = new THREE.Mesh(new THREE.RingGeometry(1.1, 1.45, 48), new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.9, blending: THREE.AdditiveBlending, depthWrite: false })); state.selectRing.rotation.x = -Math.PI / 2; scene.add(state.selectRing); }
    const seat = name && state.seats[name];
    state.selectRing.visible = !!seat;
    if (seat) { const p = seat.ch.group.position; state.selectRing.position.set(p.x, seat.room.y + SLAB_H + 0.07, p.z); }
  }

  // Minimap state in 0..1 map coordinates: the tower seen from the front, the ground floor at the bottom, each room at
  // its place on its floor, the Brain (the fountain) under the tower; the camera's target as a point.
  function minimapState() {
    const v = currentView(), H = FLOORS * FLOOR_H;
    const mapOf = (x, y) => ({ x: 0.5 + x / (2 * (WX + 6)), y: 0.86 - (y / H) * 0.8 });
    const rooms = state.roomList.map((r) => Object.assign(mapOf(r.center.x, r.y + FLOOR_H * 0.5), { key: r.key, w: r.size / (2 * (WX + 6)), h: 0.8 / FLOORS * 0.72, color: r.color, lit: r.lit, floor: r.floor }));
    const target = mapOf(v.target.x, v.target.y);
    return {
      rooms, brain: { x: 0.5, y: 0.95 }, camera: target, target, view: null, floors: FLOOR_NAMES.map((name, f) => ({ name, short: FLOOR_SHORT[f], y: mapOf(0, f * FLOOR_H + FLOOR_H / 2).y })),
      yaw: v.yaw, yawOffset: v.yaw - OVERVIEW.yaw, zoom: getZoomPercent(), mode: state.mode, floorView: state.floorView,
    };
  }

  // ------------------------------------------------------------------ picking
  function setupPicking() {
    const el = renderer.domElement, ray = new THREE.Raycaster(); let down = null, lastTap = null;
    el.addEventListener('pointerdown', (e) => { down = { x: e.clientX, y: e.clientY, b: e.button }; });
    el.addEventListener('pointerup', (e) => {
      if (!down || down.b !== 0 || Math.abs(e.clientX - down.x) + Math.abs(e.clientY - down.y) > 6) { down = null; return; }
      down = null;
      const r = el.getBoundingClientRect();
      ray.setFromCamera(new THREE.Vector2(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1), camera);
      const shown = (o) => { for (let x = o; x; x = x.parent) if (!x.visible) return false; return true; };
      const hit = ray.intersectObjects(pickables, false).find((h) => shown(h.object)); if (!hit) return;
      const u = hit.object.userData, api = window.HQ_OFFICE;
      if (e.pointerType === 'touch' && (u.room || u.brain)) {            // touch: a room or the Brain needs a double-tap (one-finger drags orbit)
        const id = u.room || 'brain', now = performance.now();
        if (!lastTap || lastTap.id !== id || now - lastTap.t > 450) { lastTap = { id, t: now }; return; }
        lastTap = null;
      }
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
    if (!state.built || state.paused || state.gfxLost || !isVisible()) return;
    const now = performance.now(), t = clock.getElapsedTime(), dt = Math.min(0.1, t - lastT); lastT = t;
    if (state.phone && !state.lowFx && !FX) watchFrameRate(now);
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
    const near = clamp((currentView().dist / state.fit - 80) / 60, 0, 1);
    anim.brain.beam.material.opacity = 0.3 * near;   // a soft beam: it stands in front of the tower anim.brain.beam.visible = anim.brain.halo.visible = near > 0.02; anim.brain.halo.material.opacity = 0.07 * near; anim.brain.glow.material.opacity *= 0.5 + 0.5 * near;
    const neon = 0.88 + Math.sin(t * 1.1) * 0.12; anim.brain.neon.forEach((m, k) => m.material.color.setRGB(0.78 * neon, 0.96 * neon, 1 * neon));
    if (LIFE.pulse > 0 || LIFE.pulsed) lifePulse(dt);                          // a note just landed in the Brain
    for (const r of anim.rings) r.holder.rotation.y = r.phase + t * r.speed;
    anim.dust.rotation.y = t * 0.004;
    animateParticles(t);
    // rooms: dashboards, crawlers
    for (const room of state.roomList) room.lit = room.seats.some((s) => !!run[s.agent.name]) || room.subs.length > 0;
    for (const d of anim.dashboards) { const lit = state.rooms[d.team].lit; const b = lit ? 0.95 + Math.sin(t * 4) * 0.25 : 0.82; d.mesh.material.color.setScalar(b); }
    for (const c of anim.crawlers) { if (c.orb) { c.mesh.position.y = c.base.y + Math.sin(t * 0.8) * 0.4; c.mesh.position.x = c.base.x + Math.sin(t * 0.5) * 0.6; } else c.mesh.material.opacity = 0.25 + 0.65 * (0.5 + 0.5 * Math.sin(t * 2.2 + c.phase)); }
    // seated agents
    lifeUpdate(run, dt, t);                                                    // office life moves the idle agents who are away from their desks
    for (const name in state.seats) {
      const seat = state.seats[name], on = !!run[name], p = seat.ch.parts, ph = seat.phase, away = !!(seat.life && seat.life.mode !== 'seated');
      if (on) {
        const s = t * 9 + ph;
        if (!away) { p.armL.rotation.x = -1.45 + Math.sin(s) * 0.1; p.armR.rotation.x = -1.45 + Math.cos(s * 1.3) * 0.1; }
        if (!away) { p.head.rotation.x = Math.sin(t * 2.4 + ph) * 0.06; p.head.rotation.y = Math.sin(t * 1.1 + ph) * 0.18; }
        seat.ring.material.opacity = 0.35 + Math.sin(t * 3 + ph) * 0.2; seat.ring.scale.setScalar(1 + Math.sin(t * 3 + ph) * 0.08);
        seat.pool.material.opacity = 0.3 + Math.sin(t * 3 + ph) * 0.08;
        const sb = 1.25 + Math.sin(t * 5 + ph) * 0.12; for (const m of seat.screens) m.color.setScalar(sb);
      } else {
        if (!away) { p.armL.rotation.x = -1.45; p.armR.rotation.x = -1.45; }
        if (!away) { p.head.rotation.x = Math.sin(t * 0.7 + ph) * 0.02; p.head.rotation.y = Math.sin(t * 0.3 + ph) * 0.09; }
        seat.ring.material.opacity = 0; seat.pool.material.opacity = 0.09;
        for (const m of seat.screens) m.color.setScalar(0.8);
      }
      if (!away) seat.ch.group.position.y = seat.ch.baseY + Math.sin(t * (on ? 4 : 1.2) + ph) * (on ? 0.03 : 0.015);
      if (!away && !on && seat.life && seat.life.micro) lifeMicro(seat.life, dt);   // a seated stretch or a look around
      seat.running = on;
    }
    for (const name in state.seats) { const g = state.seats[name].ch.group; g.visible = floorShown(floorOfY(g.position.y)); }
    if (state.lift) {                                                          // the lift glides up and down, pausing at the ends
      const c = (t * 0.035) % 1, u = c < 0.4 ? ease(c / 0.4) : c < 0.5 ? 1 : c < 0.9 ? 1 - ease((c - 0.5) / 0.4) : 0;
      state.lift.car.position.y = WALK_Y + u * (state.lift.top - WALK_Y);
    }
    animateWalkers(t, dt); animateSubs(t); updateLabels(); updateHall(t);
    if (state.selectRing && state.selectRing.visible) {
      state.selectRing.material.opacity = 0.6 + Math.sin(t * 4) * 0.3;
      const sel = state.seats[state.selected];                                  // the ring follows an agent who walked away from the desk
      if (sel && sel.life) { const q = sel.ch.group.position; state.selectRing.position.set(q.x, (sel.life.mode === 'seated' ? sel.room.y + SLAB_H : sel.life.base.y) + 0.07, q.z); }
      if (!sel || !sel.ch.group.visible) state.selectRing.material.opacity = 0;   // on a hidden floor
    }
    if (bloomPass.enabled) composer.render(); else renderer.render(scene, camera);
    css.render(scene, camera);
  }
  // Phones only: after a short warm-up, if frames average slower than ~28 fps, drop bloom and render at pixel ratio 1.
  function watchFrameRate(now) {
    const p = state.perf;
    if (!p.t0) { p.t0 = now; p.last = now; return; }
    const d = now - p.last; p.last = now;
    if (now - p.t0 < 2500 || d > 500) return;                                // skip the warm-up and tab switches
    p.n++; p.sum += d;
    if (p.n < 90) return;
    if (p.sum / p.n > 1000 / 28) { state.lowFx = true; resize(); }
    p.n = 0; p.sum = 0;
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
    for (let f = 0; f < FLOORS; f++) { const g = new THREE.Group(); g.name = 'floor' + f; scene.add(g); state.floors.push(g); }
    state.people = new THREE.Group(); scene.add(state.people);
    // the plan first, then any other team in a free slot of floors 1-4
    const used = {}, place = {};
    for (const t of teams) { const pl = FLOOR_PLAN[t.key]; if (pl && !used[pl.join()]) { used[pl.join()] = true; place[t.key] = pl; } }
    const free = []; for (let f = 1; f < HALL; f++) for (const c of [0, 1]) if (!used[f + ',' + c]) free.push([f, c]);
    for (const t of teams) if (!place[t.key]) { if (free.length) place[t.key] = free.shift(); else console.warn('office3d: no room left for', t.key); }
    resize();
    buildBrain();
    teams.forEach((team) => { const pl = place[team.key]; if (pl) buildRoom(team, pl[1], agents.filter((a) => a.teamKey === team.key || a.team === team.name), pl[0]); });
    for (const name in state.seats) state.people.add(state.seats[name].ch.group);   // characters keep their own floor rule (they take the stairs)
    buildCommons();
    buildPaths();
    buildCity();
    try { buildLife(); } catch (e) { console.warn('office3d: office life is off', e); LIFE.ready = false; }
    loadHall(); setInterval(loadHall, 60000);
    state.built = true;
    placeCamera(OVERVIEW.yaw, OVERVIEW.pitch, OVERVIEW.dist, OVERVIEW.target);
    state.userActiveUntil = performance.now() + 5000;
    window.HQ_OFFICE.ready = true;
    window.dispatchEvent(new CustomEvent('hq-office-ready'));
  }

  // The public API exists from load; calls made before the scene is built are safe no-ops.
  const api = window.HQ_OFFICE = Object.assign(window.HQ_OFFICE || {}, {
    ready: false,
    flyTo: (k, o) => state.built && flyTo(k, o), overview: (o) => state.built && overview(o),
    showFloor: (n, o) => (state.built ? viewFloor(n, o) : null), floorView: () => state.floorView, floors: () => FLOOR_NAMES.map((name, f) => ({ floor: f, name, rooms: state.roomList.filter((r) => r.floor === f).map((r) => r.key), shown: floorShown(f) })), select: (n) => state.built && select(n), focusAgent: (n, o) => state.built && focusAgent(n, o), focusBrain: (o) => state.built && focusBrain(o),
    project, setLabel, spawnSubagents: (k, items) => state.built && spawnSubagents(k, items), clearSubagents: (k) => state.built && clearSubagents(k),
    zoom: (d) => state.built && zoom(d), setZoomPercent: (p) => state.built && setZoomPercent(p), getZoomPercent: () => (state.built ? getZoomPercent() : 100),
    fullscreen, resize, minimapState: () => (state.built ? minimapState() : { rooms: [], brain: { x: 0.5, y: 0.5 }, camera: { x: 0.5, y: 0.5 }, target: { x: 0.5, y: 0.5 }, zoom: 100 }),
    bloom: (strength, threshold, radius) => { if (!bloomPass) return; if (strength != null) bloomPass.strength = +strength; if (threshold != null) bloomPass.threshold = +threshold; if (radius != null) bloomPass.radius = +radius; return { strength: bloomPass.strength, threshold: bloomPass.threshold, radius: bloomPass.radius }; },
    labelRules: (rules) => Object.assign(state.labelRules, rules || {}),
    pause: (on) => { state.paused = !!on; }, fx: () => ({ phone: state.phone, lowFx: state.lowFx, pixelRatio: renderer ? renderer.getPixelRatio() : 0, bloom: !!(bloomPass && bloomPass.enabled) }),
    teams: () => state.teams, agents: () => state.agents, rooms: () => state.roomList.map((r) => ({ key: r.key, center: r.center.clone(), size: r.size, floor: r.floor })),
    meeting: (what, minutes) => (what === 'start' ? startMeeting(minutes, 'meeting now') : what === 'end' ? endMeeting() : { on: MEET.on, until: MEET.endMs, label: MEET.label, schedule: MEET.schedule, inHall: LIFE.actors.filter((L) => L.inMeeting).length }),
    life: (on) => lifeSwitch(on), lifeOf: (n) => lifeOf(n), lifeState: () => lifeState(), lifeDebug: (o) => lifeDebug(o), lifeTalkers: () => LIFE.talkers,
    _three: () => ({ scene, camera, renderer, composer, controls, state }),
  });
  if (!('onRoomClick' in api)) api.onRoomClick = null;
  if (!('onAgentClick' in api)) api.onAgentClick = null;
  if (!('onBrainClick' in api)) api.onBrainClick = null;
  if (!('onLife' in api)) api.onLife = null;

  // The graphics can fail to start, most often right after coming back from another page (Thumbnail Studio, Design
  // Studio) while the GPU is still releasing that page, or on a computer whose driver blocked WebGL. Try again a few
  // times, then say so in the office area with a Reload button; the HUD around it keeps working either way.
  function gfxNotice(text) {
    let n = document.getElementById('office-gfx-note');
    if (!text) { if (n) n.remove(); return; }
    if (!n) {
      n = document.createElement('div'); n.id = 'office-gfx-note';
      n.setAttribute('style', 'position:absolute;inset:0;display:grid;place-items:center;z-index:1;pointer-events:none');
      host.appendChild(n);
    }
    n.innerHTML = '<div style="pointer-events:auto;max-width:420px;margin:16px;padding:18px 20px;border-radius:14px;background:#1b1f2b;border:1px solid #2c3242;color:#e8e8ea;font:14px Inter,system-ui,sans-serif;text-align:center;line-height:1.5">' +
      text + '<div style="margin-top:12px"><button type="button" style="padding:8px 16px;border-radius:9px;border:0;background:#f5b82e;color:#1a1300;font-weight:700;cursor:pointer" onclick="location.reload()">Reload the office</button></div></div>';
  }
  function startGraphics(attempt) {
    try { setupRenderer(); }
    catch (e) {
      console.warn('office3d: graphics did not start (try ' + (attempt + 1) + ')', e);
      if (renderer && renderer.domElement && renderer.domElement.parentNode) renderer.domElement.remove();
      renderer = null;
      if (attempt < 4) { setTimeout(() => startGraphics(attempt + 1), 600 * (attempt + 1)); return; }
      gfxNotice('The 3D office could not start its graphics on this computer just now. Everything else (tasks, review, posting) still works.');
      return;
    }
    gfxNotice('');
    const canvas = renderer.domElement;
    canvas.addEventListener('webglcontextlost', (e) => {     // let the browser give it back; if it doesn't, offer a reload
      e.preventDefault(); state.gfxLost = true;
      setTimeout(() => { if (state.gfxLost && renderer && renderer.getContext().isContextLost()) gfxNotice('The 3D office lost its graphics (the graphics driver reset).'); }, 3000);
    });
    canvas.addEventListener('webglcontextrestored', () => { state.gfxLost = false; gfxNotice(''); });
    // leaving the page (to a studio): give the GPU back now, so the office starts cleanly when you come back
    window.addEventListener('pagehide', () => { try { if (composer && composer.dispose) composer.dispose(); renderer.dispose(); } catch (err) { /* leaving anyway */ } });
    requestAnimationFrame(frame);
    loadOffice();
  }
  ensureExamples(() => startGraphics(0));
  function loadOffice() {
    Promise.all([
      getJSON('/api/teams').then((d) => (d.teams && d.teams.length ? d.teams : FALLBACK_TEAMS)).catch(() => FALLBACK_TEAMS),
      getJSON('/api/agents').then((d) => d.agents || []).catch(() => []),
    ]).then(([teams, agents]) => {
      if (!agents.length) agents = FALLBACK_TEAMS.map((t) => ({ name: t.lead, label: t.lead, team: t.name, teamKey: t.key, role: 'head' }));
      build(teams, agents);
      pollFallback(); setInterval(pollFallback, 6000);
    }).catch((e) => { console.error('office3d: could not build the office', e); });
  }
})();
