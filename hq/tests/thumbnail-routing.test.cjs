const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
test('each returned thumbnail final has one review entry and unlinked work stays visible',()=>{
  const source=fs.readFileSync(path.join(__dirname,'..','hud.js'),'utf8');
  const ctx=vm.createContext({});
  vm.runInContext(source.slice(source.indexOf('  function uncoveredSermonOutFolders('),source.indexOf('  function renderBoard()')),ctx);
  const names=['thumbnail-final-abc','thumbnail-final-unlinked','ordinary-video'];
  const result=ctx.uncoveredSermonOutFolders(new Set(names),[{status:'review',note:'out:thumbnail-final-abc thumbnail-request:abc'},{status:'review',note:'out:ordinary-video'}]);
  assert.deepEqual(Array.from(result),['thumbnail-final-unlinked','ordinary-video']);
  assert.deepEqual(Array.from(ctx.uncoveredSermonOutFolders(new Set(names),[{status:'review',note:'out:thumbnail-final-abc-extra'}])),names);
});
