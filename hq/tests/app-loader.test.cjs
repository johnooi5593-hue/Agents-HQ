const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');

// The start-up script at the end of app.html, run with a fake page: which scripts run, in what order, and what it shows.
const html=fs.readFileSync(path.join(__dirname,'..','app.html'),'utf8');
const loader=html.slice(html.lastIndexOf('<script>')+8,html.lastIndexOf('</script>'));

function el(tag){
  const node={tag,text:'',children:[],childNodes:[],setAttribute(){},appendChild(c){this.children.push(c);this.childNodes.push(c);return c;}};
  if(tag==='div'){const span=el('span');node.querySelector=()=>span;node.span=span;}
  return node;
}
function page(answer){
  const body=el('body'),calls={};
  const ctx={
    Date,Promise,Error,String,
    location:{origin:'https://pc.ts.net:8443',href:'/'},
    setTimeout:(fn)=>setImmediate(fn),
    addEventListener(){},
    fetch(src){calls[src]=(calls[src]||0)+1;return answer(src,calls[src]);},
    document:{body,documentElement:body,createElement:el,createTextNode:(t)=>({t})},
  };
  ctx.window=ctx;
  vm.createContext(ctx);
  vm.runInContext(loader,ctx);
  return {ctx,body,calls};
}
const ok=(src)=>Promise.resolve({ok:true,status:200,text:()=>Promise.resolve('/* '+src+' */')});
const settle=()=>new Promise((r)=>setTimeout(r,50));
const ran=(body)=>body.children.filter((c)=>c.tag==='script').map((c)=>c.text.match(/\/\* (\S+) \*\//)[1]);
const alert=(body)=>body.children.find((c)=>c.tag==='div');

test('every script runs in order, three.js first and the office last',async()=>{
  const {body}=page(ok);
  await settle();
  const order=ran(body);
  assert.equal(order.length,12);
  assert.equal(order[0],'/vendor/three.min.js');
  assert.deepEqual(order.slice(-2),['/hud.js','/office3d.js']);
  assert.equal(alert(body),undefined);
  assert.match(body.children[0].text,/\/\/# sourceURL=https:\/\/pc\.ts\.net:8443\/vendor\/three\.min\.js$/);
});

test('a file that drops on the way is fetched again, and the page does not complain',async()=>{
  const {body,calls}=page((src,n)=>src==='/office3d.js'&&n<3?Promise.reject(new TypeError('Load failed')):ok(src));
  await settle();
  assert.equal(calls['/office3d.js'],3);
  assert.equal(ran(body).at(-1),'/office3d.js');
  assert.equal(alert(body),undefined);
});

test('a file that never arrives is named on screen; the others still run',async()=>{
  const {body,calls}=page((src)=>src==='/office3d.js'?Promise.reject(new TypeError('Load failed')):ok(src));
  await settle();
  assert.equal(calls['/office3d.js'],4);
  assert.equal(ran(body).length,11);
  const msg=alert(body).span.childNodes.map((n)=>n.t||'').join('');
  assert.match(msg,/Could not load \/office3d\.js \(Load failed\)/);
});

test('a logged-out phone goes to the login page instead of retrying',async()=>{
  const {ctx,calls}=page((src)=>src==='/hud.js'?Promise.resolve({ok:false,status:401}):ok(src));
  await settle();
  assert.equal(calls['/hud.js'],1);
  assert.equal(ctx.location.href,'/login');
});
