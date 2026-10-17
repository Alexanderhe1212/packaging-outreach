'use strict';
const $ = id => document.getElementById(id);
const workspace = document.body.dataset.view === 'workspace';
const states = {queued: '等待查询', running: '正在查找和核实', done: '本轮查询完成', completed: '本轮查询完成', failed: '查询未完成', error: '查询未完成', cancelled: '已停止'};
let selectedJob = '';
let savedKeys = new Set();
function node(tag, value, className) { const el = document.createElement(tag); if (value !== undefined) el.textContent = String(value); if (className) el.className = className; return el; }
function notify(text, error = false) { $('message').replaceChildren(node('div', text, error ? 'error' : 'notice')); }
async function send(type, fields = {}) { const response = await chrome.runtime.sendMessage({type, ...fields}); if (!response || !response.ok) throw new Error(response?.error || '插件连接中断，请重试。'); return response.result; }
function safeUrl(value) { try { const u = new URL(value); return ['https:', 'http:'].includes(u.protocol) && !u.username && !u.password ? u.href : ''; } catch (_) { return ''; } }
function isPublicSite(value) {
  try { const u = new URL(value), h = u.hostname.toLowerCase(); return !!safeUrl(value) && h.includes('.') && h !== 'localhost' && !h.endsWith('.localhost') && !h.endsWith('.local') && !h.endsWith('.internal') && !h.includes(':') && !/^\d+(\.\d+){3}$/.test(h); } catch (_) { return false; }
}
function link(url, text) { const href = safeUrl(url); if (!href) return node('span', text || '来源地址不可用'); const a = node('a', text || new URL(href).hostname); a.href = href; a.target = '_blank'; a.rel = 'noopener noreferrer'; return a; }
function isQualified(c) {
  if (!c || c.qualified !== true || !String(c.name || '').trim()) return false;
  const email = String(c.email || '').trim();
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email) && !/^(info|contact|hello|admin|sales|support|office|customerservice|service|enquir(?:y|ies)|marketing|orders|team|general|reception|press|media|hr|careers|privacy|procurement|purchase|purchasing)([._+-].*)?@/i.test(email);
}
function isSavedCompany(c) {
  return c && c.contact_kind === 'company_public' && c.qualified === false && !c.name && /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(c.email || '') && (c.sources || []).length > 0;
}
function contactKey(c) {
  let host = ''; try { host = new URL(c.website).hostname.toLowerCase().replace(/^www\./, ''); } catch (_) {}
  return [host, String(c.name || '').trim().toLowerCase(), String(c.email || '').trim().toLowerCase()].join('|');
}
function field(label, value, el) { const row = node('div', undefined, 'field'); row.append(node('span', label, 'field-label'), el || node('span', value || '')); return row; }
function renderContact(c, jobId, canSave = true) {
  const card = node('article', undefined, 'contact');
  card.append(node('div', c.name || c.company || '公司公共联系方式', 'person'), node('div', c.contact_kind === 'company_public' ? '公司公共联系方式 · 非个人联系人' : c.title, 'role'));
  card.append(field(c.contact_kind === 'company_public' ? '官网公共邮箱' : '具名邮箱', c.email));
  card.append(field('本人手机', c.mobile_verified_personal === true ? c.mobile : ''));
  const whatsapps = c.whatsapp_verified_personal === true ? (Array.isArray(c.whatsapp) ? c.whatsapp : [c.whatsapp]).filter(Boolean) : [];
  card.append(field('WhatsApp', whatsapps.map(w => typeof w === 'string' ? w : w.phone || w.url || '').filter(Boolean).join(' · ')));
  card.append(node('p', c.contact_kind === 'company_public' ? '官网公开的公司联系方式；尚未找到具名联系人，未验证投递。' : '公开来源联系人；职位选填，未验证邮箱投递或采购权。', 'hint'));
  if (c.website) card.append(field('公司官网', '', link(c.website)));
  const fields = c.evidence_by_field || {};
  const labeledSources = Object.entries(fields).flatMap(([key, values]) => (Array.isArray(values) ? values : []).map(value => ({...value, label: ({identity:'姓名（职位选填）',email:'具名邮箱',phone:'本人手机',whatsapp:'本人 WhatsApp'})[key] || '公开证据'})));
  const sources = labeledSources.length ? labeledSources : (Array.isArray(c.sources) ? c.sources : []);
  if (sources.length) {
    const details = node('details', undefined, 'sources'); details.append(node('summary', '查看核实来源（' + sources.length + '）'));
    const ul = node('ul');
    for (const source of sources) {
      const url = typeof source === 'string' ? source : source.url || source.source_url;
      const li = node('li'); li.append(link(url, typeof source === 'string' ? undefined : source.title || source.label));
      const quote = typeof source === 'object' ? source.quote || source.excerpt : '';
      if (quote) li.append(node('p', quote));
      ul.append(li);
    }
    details.append(ul); card.append(details);
  }
  if (canSave) {
    const actions = node('div', undefined, 'contact-actions');
    const button = node('button', savedKeys.has(contactKey(c)) ? '已在客户表' : '保存到客户表', 'secondary');
    button.disabled = savedKeys.has(contactKey(c));
    button.dataset.contactId = c.contact_id;
    button.addEventListener('click', async () => {
      button.disabled = true;
      try { const result = await send('save', {job_id: jobId, contact_id: c.contact_id}); savedKeys.add(contactKey(c)); button.textContent = '已在客户表'; notify(result.created === false ? '客户表中已有这位联系人。' : '已保存到客户表。'); await loadCustomers(); }
      catch (error) { button.disabled = false; notify(error.message, true); }
    });
    actions.append(button); card.append(actions);
  }
  return card;
}
function errorsText(errors) {
  if (!Array.isArray(errors)) return typeof errors === 'string' ? errors : '';
  return errors.map(e => typeof e === 'string' ? e : e.message || e.error || e.status || '').filter(Boolean).join('；');
}
async function renderJobs() {
  const {jobs = {}} = await chrome.storage.local.get('jobs');
  const list = Object.values(jobs).sort((a, b) => b.updated_at - a.updated_at);
  const selected = list.find(j => j.id === selectedJob);
  if (!workspace && selected) $('research').textContent = ['done','completed','error','failed','cancelled'].includes(selected.status) ? '重新查询这家公司' : '查看当前查询';
  const visible = workspace ? list : list.slice(0, 3);
  const container = $('jobs');
  // Retain manually opened source sections when background progress changes.
  const openJobs = new Set([...container.querySelectorAll('details.job[open]')].map(el => el.dataset.jobId));
  container.replaceChildren();
  if (!visible.length) { container.append(node('div', '打开公司官网，点击查找。核实后才会显示可保存联系人。', 'empty')); return; }
  for (const job of visible) {
    const details = node('details', undefined, 'job'); details.dataset.jobId = job.id;
    details.open = openJobs.has(job.id) || job.id === selectedJob || (!openJobs.size && job.id === visible[0].id);
    const summary = node('summary', undefined, 'job-summary');
    summary.append(node('div', job.website || '公司查询', 'job-title'));
    const contacts = (job.contacts || []).filter(isQualified);
    let text = states[job.status] || '正在查询';
    if (job.progress && typeof job.progress === 'string') text += ' · ' + job.progress;
    text += ' · 已找到 ' + contacts.length + ' 人';
    summary.append(node('div', text, 'job-status')); details.append(summary);
    const content = node('div', undefined, 'job-content');
    if (job.connection_error) content.append(node('p', job.connection_error + ' 查询记录已保留，连接恢复后继续。', 'error'));
    const errors = errorsText(job.errors);
    if (errors) content.append(node('p', errors, 'hint'));
    for (const c of contacts) content.append(renderContact(c, job.id));
    if (!contacts.length) content.append(node('p', ['done', 'completed'].includes(job.status) ? '本轮未核实到姓名与具名邮箱齐全的联系人。访问受限或没有找到证据，并不代表公司没有联系人。' : '正在查找公开资料，并核对联系人归属。', 'hint'));
    details.append(content); container.append(details);
  }
}
async function loadCustomers() {
  const data = await send('customers');
  const customers = (Array.isArray(data) ? data : data.customers || []).filter(c => isQualified(c) || isSavedCompany(c));
  savedKeys = new Set(customers.map(contactKey));
  if (workspace) {
    const target = $('customers'); target.replaceChildren();
    if (!customers.length) target.append(node('div', '客户表还没有联系人。请在查询结果中点击“保存到客户表”。', 'empty'));
    else for (const c of customers) target.append(renderContact(c, c.source_job_id, false));
  }
  return customers;
}
$('research').addEventListener('click', async () => {
  const button = $('research'); button.disabled = true;
  try { const job = await send('start', {website: $('website').value.trim()}); selectedJob = job.id; notify('已开始查询。关闭这个窗口后仍会继续，可在客户工作台查看。'); await renderJobs(); }
  catch (error) { notify(error.message, true); }
  finally { button.disabled = false; }
});
$('refresh').addEventListener('click', async () => { try { await send('refresh'); await loadCustomers(); await renderJobs(); } catch (error) { notify(error.message, true); } });
if ($('workspace')) $('workspace').addEventListener('click', () => chrome.tabs.create({url: chrome.runtime.getURL('workspace.html')}));
if ($('export')) $('export').addEventListener('click', async () => {
  try {
    const csv = await send('export');
    if (typeof csv !== 'string') throw new Error('导出格式异常，请重试。');
    const url = URL.createObjectURL(new Blob(['\uFEFF' + csv.replace(/^\uFEFF/, '')], {type: 'text/csv;charset=utf-8'}));
    const anchor = node('a'); anchor.href = url; anchor.download = 'User-Radar-contacts-' + new Date().toISOString().slice(0, 10) + '.csv'; anchor.click(); setTimeout(() => URL.revokeObjectURL(url), 30000);
  } catch (error) { notify(error.message, true); }
});
chrome.storage.onChanged.addListener((changes, area) => { if (area === 'local' && changes.jobs) renderJobs().catch(error => notify(error.message, true)); });
(async () => {
  if (!workspace) {
    try { const [tab] = await chrome.tabs.query({active: true, currentWindow: true}); if (tab?.url && isPublicSite(tab.url)) $('website').value = tab.url; else notify('请先打开一家公司的公开官网。', true); } catch (_) { notify('无法读取当前网址，请重新点击插件图标。', true); }
  }
  await renderJobs();
  try {
    await send('health'); $('connection').textContent = '● 已连接本机用户雷达'; $('connection').className = 'connection good'; await loadCustomers(); await renderJobs(); await send('refresh');
    if (!workspace && $('website').value) {
      const job = await send('start', {website:$('website').value.trim(),reuse_completed:true});
      selectedJob = job.id;
      $('research').textContent = ['done','completed'].includes(job.status) ? '重新查询这家公司' : '查看当前查询';
      notify(['done','completed'].includes(job.status) ? '已显示上次结果。如需重新核实，请点击重新查询。' : '已自动开始或接续当前查询。关闭窗口后继续。');
      await renderJobs();
    }
  }
  catch (error) { $('connection').textContent = error.message; $('connection').className = 'connection bad'; }
})();
