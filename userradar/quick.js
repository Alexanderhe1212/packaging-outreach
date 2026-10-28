// Website jobs publish observed fields as pages finish; this owns only its own job.
(()=>{
  let active=null, generation=0;
  const status=$('research-status'), stop=$('research-stop'), retry=$('research-retry');
  const host=value=>{try{return new URL(value.includes('://')?value:'https://'+value).hostname.replace(/^www\./,'').toLowerCase()}catch{return ''}};
  const hasSource=p=>/^https?:\/\//i.test(p.source||'')||(p.sources||[]).some(s=>/^https?:\/\//i.test(s));
  const meaningful=report=>!!report&&(typeof report.useful_partial==='boolean'?report.useful_partial:((report.people||[]).some(p=>hasSource(p)&&(p.name||p.title||p.email||p.mobile||p.phone))||(report.qualified_people||[]).some(p=>hasSource(p)&&(p.name||p.title||p.email||p.mobile||p.phone))||(report.emails||[]).some(p=>p.email&&hasSource(p))||(report.phones||[]).some(p=>p.phone&&hasSource(p))));
  const coreComplete=report=>Array.isArray(report?.core_people)?report.core_people.length>0:(report?.qualified_people||[]).some(p=>p.qualified!==false&&p.name&&p.title&&p.email&&(p.mobile||p.phone)&&String(p.mobile||p.phone).replace(/\D/g,'').length>=7&&hasSource(p)&&!p.historical&&!p.review_required&&!p.needs_review&&!p.phone_conflict);
  const current=job=>active===job&&job.generation===generation;
  const elapsed=job=>Math.max(0,Math.floor((Date.now()-job.started)/1000));
  const limited=data=>data.error_metadata?.http_status===429||(data.report?.errors||[]).some(e=>e.http_status===429);
  function provenance(job){
    if(!$('result-context')||!latest)return;
    const own=job.hasReport&&host(latest.website)===host(job.url);
    $('result-context').textContent=own?(job.finished?'本次结果':'本次已核实的部分结果，仍在后台读取')+' · '+latest.website:'下方保留上一份结果：'+latest.website+'；不是本次 '+job.url+' 的结果。';
    $('dashboard').dataset.state=own?(job.finished?'ready':'partial'):'previous';
  }
  async function request(path,data,timeout=10000){
    const controller=new AbortController(), timer=setTimeout(()=>controller.abort(),timeout);
    try{
      const response=await fetch(path,{method:data?'POST':'GET',headers:data?{'Content-Type':'application/json'}:undefined,body:data?JSON.stringify(data):undefined,signal:controller.signal});
      const body=await response.json();
      if(!response.ok||(body.error&&!body.status))throw Error(body.error||'请求失败（'+response.status+'）');
      return body;
    }catch(error){if(error.name==='AbortError')throw Error('网络请求超时');throw error}finally{clearTimeout(timer)}
  }
  function controls(job){stop.hidden=!job||job.finished;stop.disabled=!!job?.stopping;retry.hidden=!job?.paused;$('go').disabled=false;}
  function cacheText(job,data){
    if(!(data.metrics?.cache_hit||job.cacheHit))return '';
    const checked=data.metrics?.source_checked_at||data.report?.checked_at;
    return '缓存命中'+(checked?' · 原始核实于 '+new Date(checked).toLocaleString():' · 原始核实时间未记录')+'；如需更新，请勾选重新读取官网。';
  }
  function paint(job,data){
    const useful=meaningful(data.report);
    if(useful){
      const checked=data.metrics?.source_checked_at||data.report.checked_at;
      render({...data.report,checked_at:checked});job.hasReport=true;
    }
    const ended=['done','cancelled','error'].includes(data.status);job.finished=ended;provenance(job);
    status.dataset.jobId=job.id;
    status.dataset.jobState=data.status;
    status.dataset.outcome=ended?(limited(data)?'limited':(job.hasReport?'useful':(data.status==='done'?'empty':'incomplete'))):'pending';
    const time=Number.isFinite(data.metrics?.elapsed_seconds)?data.metrics.elapsed_seconds:elapsed(job);
    const first=data.metrics?.first_result_seconds;
    status.dataset.firstResultSeconds=Number.isFinite(first)?String(first):'';
    const timing=(Number.isFinite(first)?'首个有用结果 '+first.toFixed(1)+' 秒 · ':'')+'已用 '+Number(time).toFixed(1)+' 秒';
    const cache=cacheText(job,data);
    if(data.status==='done')status.textContent=(limited(data)?'官网当前限流，联系人读取尚未完成；已有核实结果保留。':(job.hasReport?'官网阶段完成，已核实结果保留。':'本次未找到可核实的联系人或公司联系方式。'+(latest?'下方上一份结果保留。':'')))+'\n'+timing+(cache?'\n'+cache:'');
    else if(data.status==='cancelled')status.textContent='官网读取已停止，已核实结果保留。\n'+timing;
    else if(data.status==='error')status.textContent='官网读取未完成：'+(data.error||data.progress||'部分来源读取失败')+'。已核实结果保留，可重新查询。\n'+timing;
    else status.textContent=(data.progress||'正在读取官网公开信息…')+'\n'+(job.hasReport?'已显示真实字段，正在后台补全。':'尚未读到可核实的字段，'+(latest?'下方为上一份结果。':'请稍候。'))+' '+timing+(cache?'\n'+cache:'');
    if(ended&&data.report?.errors?.length)status.textContent+='\n读取限制：'+[...new Set(data.report.errors.map(e=>e.error).filter(Boolean))].slice(0,2).join('；');
    controls(job);return ended;
  }
  function schedule(job,delay=650){clearTimeout(job.timer);job.timer=setTimeout(()=>poll(job),delay)}
  async function poll(job){
    if(!current(job)||!job.id||job.finished)return;
    const sequence=job.pollSequence=(job.pollSequence||0)+1;
    try{
      const data=await request('/api/research-job/'+encodeURIComponent(job.id));
      if(!current(job)||sequence!==job.pollSequence)return;
      job.failures=0;job.paused=false;
      const ended=paint(job,data);
      if(!ended){schedule(job);return}
      const coreReady=coreComplete(data.report);
      if(limited(data)){status.textContent+='\n请在官网冷却结束后重试；本轮不自动重复启动模型补查。';return}
      if(data.status==='done'&&data.report&&!job.stopping&&!coreReady&&$('auto-supplement')?.checked&&host($('url').value.trim())===host(job.url)&&typeof startWebsiteSupplement==='function'){
        status.textContent+='\n核心字段尚未齐全，正在启动公开来源补查；官网结果保留。';
        await startWebsiteSupplement(true,job.id);
      }
    }catch(error){
      if(!current(job)||sequence!==job.pollSequence)return;
      job.failures=(job.failures||0)+1;
      if(job.failures<=3){status.textContent='暂时无法读取查询状态：'+error.message+'。已核实结果保留，正在重试（'+job.failures+'/3）。';schedule(job,Math.min(800*2**(job.failures-1),3200))}
      else{job.paused=true;status.textContent='读取查询状态失败：'+error.message+'。已核实结果保留；可恢复读取原任务状态，不会重新启动研究。';controls(job)}
    }
  }
  async function stopOwned(job){if(job?.id&&!job.finished)await request('/api/research-stop',{id:job.id})}
  $('form').onsubmit=async event=>{
    event.preventDefault();
    const url=$('url').value.trim();if(!url)return;
    const previous=active;if(previous){clearTimeout(previous.timer);stopOwned(previous).catch(()=>{})}
    const job={url,generation:++generation,started:Date.now(),id:'',hasReport:false,finished:false,stopping:false,failures:0};active=job;
    delete status.dataset.jobId;status.dataset.jobState='submitting';status.dataset.outcome='pending';
    clearInterval(timer);provenance(job);controls(job);status.textContent='正在启动官网读取…'+(latest?'下方上一份结果保留。':'');
    try{
      const result=await request('/api/research-start',{url,refresh:!!$('research-refresh')?.checked});
      job.id=result.id;job.cacheHit=!!result.cache_hit;
      if(!current(job)){await stopOwned(job).catch(()=>{});return}
      if(!job.id)throw Error('服务器未返回查询编号');
      if(job.stopping){await stopOwned(job);schedule(job,0)}else await poll(job);
    }catch(error){if(!current(job))return;job.finished=true;controls(job);status.textContent='未能确认官网查询已启动：'+error.message+'。已有结果保留；请求超时时后台仍可能已启动，本页没有自动重发。';provenance(job)}
  };
  stop.onclick=async()=>{
    const job=active;if(!job||job.finished)return;
    job.stopping=true;controls(job);status.textContent='正在停止本次官网读取，已核实结果保留。';
    if(!job.id)return;
    try{await stopOwned(job);if(current(job)){job.paused=false;job.failures=0;schedule(job,0)}}
    catch(error){if(current(job)){job.stopping=false;controls(job);status.textContent='停止请求未完成：'+error.message+'。查询仍可能在运行，已有结果保留，可再次停止。'}}
  };
  retry.onclick=()=>{if(active&&!active.finished){active.paused=false;active.failures=0;controls(active);poll(active)}};
  // Opening a saved record is intentional navigation; a pending response must not replace it.
  const loadSaved=$('load').onclick;
  $('load').onclick=event=>{if($('history').value==='')return;const old=active;active=null;generation++;if(old){clearTimeout(old.timer);stopOwned(old).catch(()=>{})}controls(null);status.textContent='已打开本机保存记录，核实时间沿用原记录。';loadSaved(event);if($('result-context')&&latest)$('result-context').textContent='本机保存记录 · '+latest.website};
})();
