const assert = require('node:assert/strict');
const test = require('node:test');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '..', 'hud.js'), 'utf8');
const implementation = source.slice(source.indexOf('  function sermonDesignRoute('), source.indexOf('  async function send(prompt)'));
const context = vm.createContext({URLSearchParams});
vm.runInContext(implementation, context);
const route = input => context.sermonDesignRoute(input);

test('explicit first-line trigger preserves exact supplied titles', () => {
  const url = new URL(route('Sermon Title 16:9\nChinese: 认识神的声音！\nEnglish: Knowing the Voice of God\nAlignment: Right\nKeep negative space.'), 'https://office.example');
  assert.equal(url.pathname, '/sermon-studio.html');
  assert.equal(url.searchParams.get('mode'), 'title');
  assert.equal(url.searchParams.get('chinese'), '认识神的声音！');
  assert.equal(url.searchParams.get('english'), 'Knowing the Voice of God');
  assert.equal(url.searchParams.get('alignment'), 'right');
  assert.equal(url.searchParams.get('instructions'), 'Keep negative space.');
});
test('Creative selected agent and microphone send share the same route', () => {
  assert.match(route('Ask thumbnail-designer: Sermon Title 16:9\n中文：恩典\n英文：Grace'), /chinese=/);
  assert.match(route('XHS Sermon Recap Pro'), /mode=recap/);
  assert.match(source, /function sendVoice\(\)[^\n]+send\(text\)/);
  const send = source.slice(source.indexOf('  async function send(prompt)'), source.indexOf('  // ---------- sub-agent progress'));
  assert.ok(send.indexOf('sermonDesignRoute(prompt)') < send.indexOf('postJSON("/api/run"'));
});
test('ordinary tasks, quotations and feedback keep the existing lead workflow', () => {
  for (const input of ['Please design a poster', 'Explain Sermon Title 16:9', 'Feedback:\nSermon Title 16:9', '"Sermon Title 16:9"', 'Sermon Title 16:9 tomorrow', '/brief Sermon Title 16:9']) assert.equal(route(input), null);
});
test('Creative entry and real HQ review deep link are present', () => {
  assert.match(source, /t\.key === "creative"/);
  assert.match(source, /data-sermon-studio="title"/);
  assert.match(source, /data-sermon-studio="xhs"/);
  assert.match(source, /get\("task"\)/);
  assert.match(source, /openReview\(\{ taskId: requestedTask \}\)/);
});
test('native Studio delivery appears once while ordinary folder cards remain', () => {
  const helper = source.slice(source.indexOf('  function uncoveredSermonOutFolders('), source.indexOf('  function renderBoard()'));
  vm.runInContext(helper, context);
  const native = 'sermon-studio-project-one-r4-a1';
  const names = new Set([native, 'ordinary-video', 'sermon-studio-unlinked-r3-a1']);
  const review = [{id: 't1', status: 'review', note: `out:${native} Native Design Studio renderer; user OK required.`}, {id: 't2', status: 'review', note: 'out:ordinary-video'}];
  assert.deepEqual(Array.from(context.uncoveredSermonOutFolders(names, review)), ['ordinary-video', 'sermon-studio-unlinked-r3-a1']);
  assert.deepEqual(Array.from(context.uncoveredSermonOutFolders(names, [{...review[0], status: 'done'}])), Array.from(names));
  assert.deepEqual(Array.from(context.uncoveredSermonOutFolders(names, [{status: 'review', note: `out:${native}-other`}])), Array.from(names));
});
