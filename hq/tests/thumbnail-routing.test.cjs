const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
test('video review hands off the selected video identity and channel without accepting a client title',()=>{
  const source=fs.readFileSync(path.join(__dirname,'..','hud.js'),'utf8');
  const start=source.indexOf('  function thumbnailStudioHref('),end=source.indexOf('\n  // Opens over everything',start);
  const ctx=vm.createContext({URLSearchParams});vm.runInContext(source.slice(start,end),ctx);
  const first=new URL(ctx.thumbnailStudioHref('out/中文-video','t1','edit.mp4',''),'http://office.local');
  const second=new URL(ctx.thumbnailStudioHref('out/中文-video','t1','version 2/final.mp4',''),'http://office.local');
  assert.equal(first.searchParams.get('folder'),'out/中文-video');assert.equal(first.searchParams.get('videoPath'),'edit.mp4');
  assert.equal(second.searchParams.get('videoPath'),'version 2/final.mp4');assert.equal(second.searchParams.get('channel'),'');assert.equal(second.searchParams.has('title'),false);
  assert.match(source,/thumbnailStudioHref\(rv\.folder, rv\.taskId, v && v\.path, rv\.ch\)/);
});
test('each returned thumbnail final has one review entry and unlinked work stays visible',()=>{
  const source=fs.readFileSync(path.join(__dirname,'..','hud.js'),'utf8');
  const ctx=vm.createContext({});
  vm.runInContext(source.slice(source.indexOf('  function uncoveredSermonOutFolders('),source.indexOf('  function renderBoard()')),ctx);
  const names=['thumbnail-final-abc','thumbnail-final-unlinked','ordinary-video'];
  const result=ctx.uncoveredSermonOutFolders(new Set(names),[{status:'review',note:'out:thumbnail-final-abc thumbnail-request:abc'},{status:'review',note:'out:ordinary-video'}]);
  assert.deepEqual(Array.from(result),['thumbnail-final-unlinked','ordinary-video']);
  assert.deepEqual(Array.from(ctx.uncoveredSermonOutFolders(new Set(names),[{status:'review',note:'out:thumbnail-final-abc-extra'}])),names);
});
