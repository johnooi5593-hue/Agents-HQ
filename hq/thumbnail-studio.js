(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const query = new URLSearchParams(location.search);
  let folder = query.get('folder'), taskId = query.get('taskId') || '';
  let openedJob = null, retryRequested = false, pollStarted = Date.now();
  const state = {config:null, context:null, jobs:new Map(), pending:false, timer:null};
  const esc = text => String(text ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function notice(message, error=false) { $('notice').textContent=message; $('notice').className=error?'error':''; }
  async function api(route, body) {
    const response=await fetch('/api/thumbnail-design'+route, body===undefined?{cache:'no-store'}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    let data; try { data=await response.json(); } catch { throw Error('封面功能尚未连接，请在 HQ 正常重启引擎后再试。'); }
    if(!response.ok) throw Error(data.error||`请求失败 (${response.status})`);
    return data;
  }
  const selectedChannel=()=>state.config?.channels.find(c=>c.key===$('channel').value);
  function renderTemplates() {
    const channel=selectedChannel(), templates=channel?.templates||[];
    $('templates').innerHTML=templates.length?templates.map(t=>`<article class="template"><img src="${esc(t.previewUrl)}" alt="${esc(t.name)}"><div class="content"><h3>${esc(t.name)}</h3><small>${t.width} × ${t.height} · v${t.revision}</small>${t.id===channel.defaultTemplateId?'<small>✓ 频道默认模板</small>':`<button type="button" data-default="${esc(t.id)}">设为默认</button>`}</div></article>`).join(''):'<p>这个频道还没有模板。请先上传，其他频道的模板不会自动套用。</p>';
    const previous=$('video-template').value;
    $('video-template').innerHTML=templates.map(t=>`<option value="${esc(t.id)}">${esc(t.name)} · ${t.width} × ${t.height}${t.id===channel.defaultTemplateId?' · 默认':''}</option>`).join('');
    $('video-template').value=templates.some(t=>t.id===previous)?previous:channel?.defaultTemplateId||templates[0]?.id||'';
    $('approve').disabled=state.pending||!templates.length||!state.context?.eligible;
  }
  async function loadConfig(preferred) {
    state.config=await api('/config');
    $('channel').innerHTML=state.config.channels.map(c=>`<option value="${esc(c.key)}">${esc(c.name||'Main channel')}</option>`).join('');
    if(state.config.channels.some(c=>c.key===preferred)) $('channel').value=preferred;
    renderTemplates();
  }
  function renderJobs() {
    const labels={dispatching:'正在提交 Codex',watching:'Codex 正在制作',uncertain:'正在核对提交结果','delivery-error':'回传未完成',pending:'等待接收',queued:'已排队',running:'Codex 正在制作',generating:'Codex 正在制作',delivering:'正在回传 HQ',succeeded:'封面已生成',awaiting_approval:'Final 等你审核',delivered:'Final 等你审核',failed:'本次未完成',interrupted:'本次已中断',needs_input:'需要补充资料',delivery_error:'回传未完成'};
    $('jobs').innerHTML=[...state.jobs.values()].reverse().map(j=>`<div class="job"><strong>${esc(labels[j.status]||j.status)}</strong><small>${esc(j.stage||j.id)}</small>${['dispatching','watching','pending','queued','running','generating','delivering'].includes(j.status)?`<progress max="100" value="${Math.max(0,Math.min(100,Number(j.progress)||0))}"></progress>`:''}${(j.warnings||[]).map(w=>`<p>${esc(w)}</p>`).join('')}${j.error?`<p>${esc(j.error)}</p>`:''}${j.status==='failed'?'<button type="button" data-retry>重新提交当前设置，生成新版本</button>':''}${!j.delivery&&j.status!=='failed'?`<button type="button" data-collect="${esc(j.id)}">检查并收取现有结果</button>`:''}${j.delivery?`<p>视频与四张封面已回到 Agent HQ。请在那里选择封面，检查并给最终 OK。</p><a class="action" href="/?task=${encodeURIComponent(j.delivery.taskId)}">打开 Final 审核 →</a>`:''}</div>`).join('');
  }
  async function pollJobs() {
    clearTimeout(state.timer);
    for(const [id,job] of state.jobs) {
      if(job.delivery||['failed','interrupted','delivery_error','delivery-error'].includes(job.status))continue;
      try { const data=await api('/jobs/'+encodeURIComponent(id));state.jobs.set(id,data.job); } catch(error) { notice(error.message,true); }
    }
    renderJobs();
    if(Date.now()-pollStarted<30*60*1000&&[...state.jobs.values()].some(j=>!j.delivery&&!['failed','interrupted','delivery_error','delivery-error'].includes(j.status)))state.timer=setTimeout(pollJobs,4000);
  }
  function updateVideo() {
    const video=state.context?.videos.find(v=>v.path===$('video').value);
    $('player').src=video?.url||('/files/'+folder.split('/').map(encodeURIComponent).join('/')+'/'+(video?.path||'').split('/').map(encodeURIComponent).join('/'));
  }
  async function loadContext() {
    const data=await api('/context?'+new URLSearchParams({folder,taskId})); state.context=data;
    if(data.channel!==undefined&&data.channel!==null) {$('channel').value=data.channel;$('channel').disabled=data.channelKnown===true;}
    if(!data.channelKnown){const option=document.createElement('option');option.value='__choose__';option.textContent='请选择这个视频所属频道';option.disabled=true;$('channel').prepend(option);$('channel').value='__choose__';}
    $('video-section').hidden=false;
    $('video').innerHTML=(data.videos||[]).map(v=>`<option value="${esc(v.path)}">${esc(v.name)}</option>`).join('');
    if(data.title)$('title').value=data.title;
    for(const job of data.jobs||[])state.jobs.set(job.id,job);
    if(data.videos?.length)updateVideo();
    renderTemplates();renderJobs();
    if(!data.channelKnown)notice('这个视频未记录频道，请先确认所属品牌，再批准视频。');
    if(!data.eligible)notice(data.error||'这个版本暂时不能开始封面制作。',true);
    if(state.jobs.size)pollJobs();
  }
  $('channel').addEventListener('change',()=>{renderTemplates();notice('已切换频道。模板只应用于当前频道。');});
  $('video').addEventListener('change',updateVideo);
  $('templates').addEventListener('click',async event=>{
    const button=event.target.closest('[data-default]');if(!button)return;
    button.disabled=true;try {const channel=$('channel').value;await api('/default',{channel,templateId:button.dataset.default});await loadConfig(channel);notice('已保存这个频道的默认模板。');}catch(error){notice(error.message,true);button.disabled=false;}
  });
  const asDataUrl=file=>new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.onerror=()=>reject(Error('无法读取模板图片。'));reader.readAsDataURL(file);});
  $('template-form').addEventListener('submit',async event=>{
    event.preventDefault();const button=event.submitter;button.disabled=true;
    try {
      const file=$('template-file').files[0];if(!file||!['image/png','image/jpeg','image/webp'].includes(file.type)||file.size>15*1024*1024)throw Error('请选择 15 MB 以下的 PNG、JPG 或 WebP 模板。');
      const channel=$('channel').value,[width,height]=$('dimensions').value.split('x').map(Number);
      await api('/templates',{channel,name:$('template-name').value.trim(),dataUrl:await asDataUrl(file),width,height,instructions:$('template-instructions').value.trim(),makeDefault:$('make-default').checked});
      await loadConfig(channel);$('template-form').reset();$('upload-details').open=false;notice('模板已保存。之后这个频道的视频会使用所选默认模板。');
    }catch(error){notice(error.message,true);}finally{button.disabled=false;}
  });
  $('video-form').addEventListener('submit',async event=>{
    event.preventDefault();if(state.pending)return;state.pending=true;renderTemplates();
    try {
      const video=state.context.videos.find(v=>v.path===$('video').value);if(!video)throw Error('请先选择这次批准的视频。');
      const data=await api('/approve-video',{folder,taskId,videoPath:video.path,videoSha256:video.sha256,channel:$('channel').value,templateId:$('video-template').value,title:$('title').value.trim(),subtitle:$('subtitle').value.trim(),instructions:$('video-instructions').value.trim(),approval:true,retry:retryRequested});
      state.jobs.set(data.job.id,data.job);renderJobs();notice('视频批准已记录，封面任务已提交。生成结果会回传 HQ，等待最终审核。');pollJobs();
    }catch(error){notice(error.message,true);}finally{state.pending=false;retryRequested=false;renderTemplates();}
  });
  $('jobs').addEventListener('click',async event=>{
    if(event.target.closest('[data-retry]')){retryRequested=true;$('video-form').requestSubmit($('approve'));return;}
    const button=event.target.closest('[data-collect]');if(!button)return;button.disabled=true;
    try{const data=await api('/jobs/'+encodeURIComponent(button.dataset.collect));state.jobs.set(data.job.id,data.job);renderJobs();pollStarted=Date.now();notice('已检查现有任务，没有重新生成图片。');pollJobs();}catch(error){notice(error.message,true);button.disabled=false;}
  });
  (async()=>{try{
    if(query.get('job')){openedJob=(await api('/jobs/'+encodeURIComponent(query.get('job')))).job;folder=openedJob.folder;taskId=openedJob.taskId||'';}
    await loadConfig(query.get('channel')||'');notice('模板与视频按频道关联。');if(folder)await loadContext();
    if(openedJob){$('title').value=openedJob.title||'';$('subtitle').value=openedJob.subtitle||'';$('video-instructions').value=openedJob.instructions||'';$('video-template').value=openedJob.templateId||'';$('video').value=openedJob.videoPath||'';updateVideo();}
  }catch(error){notice(error.message,true);$('approve').disabled=true;}})();
})();
