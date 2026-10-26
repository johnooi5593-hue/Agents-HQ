const assert = require('node:assert/strict');
const test = require('node:test');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '..', 'hud.js'), 'utf8');
const implementation = source.slice(source.indexOf('  function sermonDesignRoute('), source.indexOf('  async function send(prompt)'));
const context = vm.createContext({URLSearchParams});
vm.runInContext(implementation, context);
vm.runInContext(source.slice(source.indexOf('  function reviewArtworkFiles('), source.indexOf('  function renderReview()')), context);
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
  for (const input of ['Please design a poster', 'Explain Sermon Title 16:9', 'Feedback:\nSermon Title 16:9', '"Sermon Title 16:9"', 'Sermon Title 16:9 tomorrow', '/brief Sermon Title 16:9', '"Sermon Poster"', 'Explain Create sermon poster', 'Feedback:\n制作讲道海报', '“制作讲道海报”', 'Please create sermon poster']) assert.equal(route(input), null);
});
test('easy first-line poster aliases support Chinese and English titles', () => {
  for (const alias of ['Sermon Poster', 'Create sermon poster', '制作讲道海报', 'Ask thumbnail-designer: Create sermon poster']) {
    const url = new URL(route(alias + '\n中文：恩典\nEnglish: Grace'), 'https://office.example');
    assert.equal(url.pathname, '/sermon-studio.html');
    assert.equal(url.searchParams.get('mode'), 'title');
    assert.equal(url.searchParams.get('chinese'), '恩典');
    assert.equal(url.searchParams.get('english'), 'Grace');
  }
  assert.match(source, /Create sermon poster \/ 讲道海报/);
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
test('native poster review shows only four final PNGs before supporting images', () => {
  const image = path => ({name: path.split('/').at(-1), path, url: '/files/out/test/' + path, kind: 'image'});
  const files = [image('assets/design-01-gpt-background.png'), image('assets/Sermon_Title_Design_01.png')];
  for (const index of ['04', '02', '01', '03']) {
    files.push(image(`Sermon_Title_Design_${index}.jpg`), image(`Sermon_Title_Design_${index}.png`));
  }
  const result = context.reviewArtworkFiles(files, 'out/sermon-studio-project-one-r4-a1');
  assert.equal(result.native, true);
  assert.deepEqual(Array.from(result.images, file => file.path), ['01', '02', '03', '04'].map(index => `Sermon_Title_Design_${index}.png`));
  for (const file of result.images) {
    assert.equal(result.alternatives[file.path].length, 1);
    assert.match(result.alternatives[file.path][0].path, /\.jpg$/);
  }
  const supporting = files.filter(file => !result.images.includes(file));
  assert.ok(supporting.some(file => file.path === 'assets/design-01-gpt-background.png'));
  assert.ok(supporting.some(file => /\.jpg$/.test(file.path)));
  assert.match(source, /artwork\.native \? "Finished artwork" : "Covers and images"/);
  assert.match(source, /aspect-ratio:\$\{ratio\};object-fit:contain/);
});
test('native XHS review shows two independent outputs and no background fallback', () => {
  const image = path => ({name: path.split('/').at(-1), path, url: '/files/out/test/' + path, kind: 'image'});
  const files = [image('assets/background.png'), image('XHS_Sermon_Recap_Cover.jpg'), image('XHS_Sermon_Recap_Cover.png'), image('XHS_Sermon_Main.jpg'), image('XHS_Sermon_Main.png')];
  const result = context.reviewArtworkFiles(files, 'approved/sermon-studio-project-two-r7-a2');
  assert.deepEqual(Array.from(result.images, file => file.path), ['XHS_Sermon_Main.png', 'XHS_Sermon_Recap_Cover.png']);
  assert.equal(context.reviewArtworkFiles([files[0]], 'out/sermon-studio-project-two-r7-a2').images.length, 0);
});
test('ordinary job review keeps every existing image and its original ordering', () => {
  const files = ['assets/background.png', 'cover.jpg', 'thumbnail.png'].map(path => ({name: path.split('/').at(-1), path, kind: 'image'}));
  const result = context.reviewArtworkFiles(files, 'out/ordinary-reel');
  assert.equal(result.native, false);
  assert.deepEqual(Array.from(result.images, file => file.path), ['cover.jpg', 'assets/background.png', 'thumbnail.png']);
});
