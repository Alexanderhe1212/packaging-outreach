// A separate full-team research view. Missing fields never enter the outreach export.
let activeTeam='',teamTimer,teamReport=null,teamStarting=false,teamFailures=0,teamPollSequence=0;
const teamStorageKey='user-radar-team-job';
function teamRemember(id){try{if(id)sessionStorage.setItem(teamStorageKey,id);else sessionStorage.removeItem(teamStorageKey)}catch{}}
function teamHost(value){try{return new URL(value.includes('://')?value:'https://'+value).hostname.replace(/^www\./,'').toLowerCase()}catch{return ''}}
function hasWebsiteTeam(website){return !!(typeof latest!=='undefined'&&latest&&teamHost(latest.website)===teamHost(website)&&(latest.people||[]).some(p=>p.name&&p.title&&p.evidence_by_field?.identity?.length))}
function teamSafePerson(person){const p={...person};const evidence=p.evidence_by_field||{};const fresh=field=>(evidence[field]||[]).some(e=>/^https?:\/\//i.test(e.url||'')&&(!e.source_year||Number(e.source_year)>new Date().getFullYear()-2));const review=p.historical||p.needs_review||p.review_required;const identified=!!(p.name&&p.title&&fresh('identity')&&!review);const shared=/^(admin|info|support|contact|hello|sales|office|service|enquiry|enquiries|marketing|export|exports|ceo|team)([._+-].*)?$/i.test((p.email||'').split('@')[0]);
p.email=identified&&fresh('email')&&!p.email_stale&&!p.email_exclusion&&!shared&&p.email_kind!=='person_attributed_role_mailbox'?p.email||'':'';
p.mobile=identified&&fresh('phone')&&!p.phone_stale&&!p.phone_conflict?p.mobile||'':'';
p.phone=identified&&fresh('phone')&&!p.phone_stale&&!p.phone_conflict?p.phone||'':'';
p.phone_e164=identified&&fresh('phone')&&!p.phone_stale&&!p.phone_conflict?p.phone_e164||'':'';
p.whatsapp=identified&&fresh('whatsapp')?(p.whatsapp||[]).filter(w=>w.attribution==='person'&&(w.attributed_name||'').trim().toLowerCase()===p.name.trim().toLowerCase()&&/^https?:\/\//i.test(w.source||w.person_source?.url||'')):[];
p.qualified=!!(p.name&&p.title&&p.email);p.complete=!!(p.qualified&&p.mobile&&p.whatsapp.length);return p}
function teamFullReport(job){const raw=job.report||{};const people=(raw.people||[]).map(teamSafePerson);for(const item of job.items||[]){if(item.name&&!people.some(p=>p.name.trim().toLowerCase()===item.name.trim().toLowerCase()))people.push(teamSafePerson({...item,email:'',phone:'',mobile:'',whatsapp:[]}))}return {...raw,website:raw.website||job.website,pages:raw.pages||[],people,qualified_people:people.filter(p=>p.qualified),complete_people:people.filter(p=>p.complete)}}
function teamCsvData(report){const rows=[['官网','姓名','职位','具名工作邮箱（已核对）','本人手机（已核对）','本人商务电话（已核对）','本人WhatsApp（已核对）','补查状态','姓名职位来源','邮箱来源','手机来源','商务电话来源','WhatsApp来源','领英公开链接','核实时间']];for(const raw of report.people||[]){const p=teamSafePerson(raw),ev=p.evidence_by_field||{},urls=k=>(ev[k]||[]).map(e=>e.url).filter(Boolean).join('; ');rows.push([report.website,p.name,p.title,p.email,p.mobile,p.mobile||p.phone_e164||p.phone,p.whatsapp.map(w=>w.url||w.phone||'').join('; '),p.status||'缺项留空，待补全',urls('identity'),p.email?urls('email'):'',p.mobile?urls('phone'):'',(p.mobile||p.phone_e164||p.phone)?urls('phone'):'',p.whatsapp.length?urls('whatsapp'):'',p.linkedin_url||'',report.checked_at||''])}return '\ufeff'+rows.map(row=>row.map(csvCell).join(',')).join('\r\n')}
function teamControls(active){if($('team-go'))$('team-go').disabled=active;if($('team-stop')){$('team-stop').hidden=!active;if(!active)$('team-stop').disabled=false;}}
function renderTeamEnrichment(job){if($('team-state'))$('team-state').textContent=job.progress||'正在逐人补查公开来源…';if(!job.report)return;teamReport=teamFullReport(job);const parent=$('team-results');if($('team-origin'))$('team-origin').textContent='此区域补查官网：'+teamReport.website;if(parent){parent.dataset.website=teamReport.website;parent.dataset.state=job.status;parent.replaceChildren();const labels={queued:'等待补查',running:'正在补查',done:'补查完成',error:'部分来源读取失败，已核对结果保留',cancelled:'已停止，缺项留空'};for(const p of teamReport.people){const item=(job.items||[]).find(i=>(i.name||'').trim().toLowerCase()===p.name.trim().toLowerCase());const card=node('article','');card.append(node('strong',p.name+' · '+(p.title||'职位未确认')),node('p',labels[item?.status]||'官网已找到，待补查'),node('p','邮箱：'+(p.email||'未核实，留空')),node('p','本人手机：'+(p.mobile||'未核实，留空')),node('p','本人商务电话：'+(p.mobile||p.phone_e164||p.phone||'未核实，留空')),node('p','本人 WhatsApp：'+(p.whatsapp.length?p.whatsapp.map(w=>w.phone||w.url).join('；'):'未核实，留空')));if(p.linkedin_url)source(card,p.linkedin_url,'领英公开线索 ↗');for(const url of p.sources||[p.source])source(card,url,'查看联系人来源 ↗');if(p.source_checks?.length){const checks=node('details','');checks.append(node('summary','查看本人的来源读取情况'));for(const check of p.source_checks){checks.append(node('p',check.status||check.error||'来源待核对'));source(checks,check.url,'查看该公开来源 ↗')}card.append(checks)}for(const error of item?.errors||[]){card.append(node('small',typeof error==='string'?error:error.error||'本人的部分来源未能读取'));if(error.url)source(card,error.url,'查看未能核实的来源 ↗')}parent.append(card)}for(const error of job.errors||[])parent.append(node('small',typeof error==='string'?error:error.error||'部分公开来源未能读取'))}if($('team-export'))$('team-export').disabled=!teamReport.people.length;const targetHost=teamHost($('url')?.value||''),reportHost=teamHost(teamReport.website),shownHost=teamHost(latest?.website||'');if((!targetHost||targetHost===reportHost)&&(!shownHost||shownHost===reportHost))render(teamReport);}
async function teamRequest(path,data){
  const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),10000);
  try{
    const response=await fetch(path,{method:data?'POST':'GET',headers:data?{'Content-Type':'application/json'}:undefined,body:data?JSON.stringify(data):undefined,signal:controller.signal});
    const body=await response.json();
    if(!response.ok||(body.error&&!body.status)){const error=Error(body.error||'请求失败');error.status=response.status;throw error}
    return body;
  }catch(error){if(error.name==='AbortError'){const timeoutError=Error(data?'网络请求超时，提交结果未知；任务可能仍在后台运行，未自动重新提交。':'网络请求超时');timeoutError.unknownOutcome=!!data;throw timeoutError}throw error}finally{clearTimeout(timeout)}
}
async function pollTeamEnrichment(){
  const id=activeTeam;if(!id)return;
  clearTimeout(teamTimer);const sequence=++teamPollSequence;
  try{
    const job=await teamRequest('/api/team-enrichment/'+encodeURIComponent(id));
    if(activeTeam!==id||sequence!==teamPollSequence)return;
    teamFailures=0;if($('team-retry'))$('team-retry').hidden=true;
    renderTeamEnrichment(job);
    const active=['running','stopping','queued'].includes(job.status);teamControls(active);
    if(active)teamTimer=setTimeout(pollTeamEnrichment,1500);else{activeTeam='';teamRemember('')}
  }catch(error){
    if(activeTeam!==id||sequence!==teamPollSequence)return;
    if(error.status===404){
      activeTeam='';teamRemember('');teamFailures=0;teamControls(false);if($('team-retry'))$('team-retry').hidden=true;
      if($('team-state'))$('team-state').textContent='上次逐人补查记录已过期，可重新开始；当前显示的结果保留。';return;
    }
    // A transport failure does not end the server job. Keep its ID and ownership.
    teamFailures++;teamControls(true);
    if(teamFailures<=3){
      if($('team-state'))$('team-state').textContent='暂时无法读取逐人补查状态：'+error.message+'。已有结果保留，正在重试（'+teamFailures+'/3）。';
      teamTimer=setTimeout(pollTeamEnrichment,Math.min(1000*2**(teamFailures-1),4000));
    }else{
      if($('team-state'))$('team-state').textContent='读取逐人补查状态失败：'+error.message+'。原任务编号和已有结果已保留，可恢复查询状态，不会重新启动补查。';
      if($('team-retry'))$('team-retry').hidden=false;
    }
  }
}
async function startTeamEnrichment(automatic=false,sourceJobId=''){if(activeTeam||teamStarting){if($('team-state'))$('team-state').textContent='已有逐人补查进行中，请等待或停止后重试。';return}let website=$('url').value.trim();if(!website){$('state').textContent='先填写需要补查的官网。';return}if(!website.includes('://'))website='https://'+website;teamStarting=true;teamControls(true);if($('team-state'))$('team-state').textContent=automatic?'已找到官网人员，正在自动逐人补查联系方式…':'正在读取官网人员并逐人补查…';try{const job=await teamRequest('/api/team-enrichment',{website,core_only:automatic===true,source_job_id:sourceJobId});if(!job.id)throw Error('服务器未返回逐人补查编号');activeTeam=job.id;teamFailures=0;if($('team-retry'))$('team-retry').hidden=true;teamRemember(activeTeam);await pollTeamEnrichment()}catch(error){teamControls(false);if($('team-state'))$('team-state').textContent=(error.unknownOutcome?'逐人补查状态未确认：':'逐人补查未启动：')+error.message}finally{teamStarting=false}}
if($('team-go'))$('team-go').onclick=()=>startTeamEnrichment(false);
if($('team-stop'))$('team-stop').onclick=async()=>{const id=activeTeam;if(!id)return;$('team-stop').disabled=true;try{await teamRequest('/api/team-enrichment-stop',{id});if(activeTeam!==id)return;$('team-state').textContent='正在停止逐人补查，已核对结果保留。';teamFailures=0;if($('team-retry'))$('team-retry').hidden=true;clearTimeout(teamTimer);teamTimer=setTimeout(pollTeamEnrichment,0)}catch(error){if(activeTeam===id)$('team-state').textContent='停止请求未完成：'+error.message+'。原任务编号已保留，可再次停止。'}finally{if(activeTeam===id)$('team-stop').disabled=false}};
if($('team-retry'))$('team-retry').onclick=()=>{if(!activeTeam)return;teamFailures=0;$('team-retry').hidden=true;pollTeamEnrichment()};
if($('team-export'))$('team-export').onclick=()=>{if(teamReport)download(teamCsvData(teamReport),'text/csv;charset=utf-8','user-radar-team-research-including-pending.csv')};
try{activeTeam=sessionStorage.getItem(teamStorageKey)||'';if(activeTeam){teamControls(true);pollTeamEnrichment()}}catch{}
