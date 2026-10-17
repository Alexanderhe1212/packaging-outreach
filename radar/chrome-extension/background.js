importScripts('config.js');
const config = globalThis.USER_RADAR_CONFIG || {};
const PREFIX = '/api/extension';
const terminal = new Set(['done', 'error', 'failed', 'cancelled', 'completed']);
const timers = new Map();
const polling = new Set();
let storageQueue = Promise.resolve();
const starting = new Map();
function fail(message) { throw new Error(message); }
function validWebsite(value) {
  let url;
  try { url = new URL(value); } catch (_) { fail('请打开有效的公司官网。'); }
  const h = url.hostname.toLowerCase();
  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || h === 'localhost' || h.endsWith('.localhost') || h.endsWith('.local') || h.endsWith('.internal') || h.includes(':') || /^\d+(\.\d+){3}$/.test(h) || !h.includes('.')) fail('只支持公开的公司官网地址。');
  url.hash = ''; return url.href;
}
async function request(path, options = {}) {
  if (!config.token || config.extensionId !== chrome.runtime.id) fail('插件尚未连接。请使用用户雷达生成的安装文件夹。');
  if (config.apiBase !== 'http://127.0.0.1:18830') fail('后台地址配置不正确。');
  let response;
  try {
    response = await fetch(config.apiBase + PREFIX + path, {...options, headers: {'Authorization': 'Bearer ' + config.token, 'X-User-Radar-Extension': chrome.runtime.id, 'Content-Type': 'application/json', ...(options.headers || {})}, signal: AbortSignal.timeout(20000)});
  } catch (_) { fail('暂时连不上用户雷达，请确认本机后台已启动，再点击重试。'); }
  const contentType = response.headers.get('content-type') || '';
  const body = contentType.includes('json') ? await response.json() : await response.text();
  if (!response.ok) {
    if (response.status === 401 || response.status === 403) fail('连接授权无效或已更新，请重新生成插件连接配置。');
    if (response.status === 429) fail('当前查询较多，请稍后重试。');
    const error = new Error(typeof body === 'object' ? body.error || body.message || '后台暂时无法完成操作。' : '后台暂时无法完成操作。');
    error.status = response.status; throw error;
  }
  return body;
}
function remember(job) {
  const write = storageQueue.catch(() => {}).then(async () => {
  const {jobs = {}} = await chrome.storage.local.get('jobs');
  jobs[job.id] = {...jobs[job.id], ...job, updated_at: Date.now()};
  // Completed records live in the server customer table; cap only the recent-task view.
  const recent = Object.values(jobs).sort((a, b) => b.updated_at - a.updated_at).slice(0, 50);
  await chrome.storage.local.set({jobs: Object.fromEntries(recent.map(j => [j.id, j]))});
  });
  storageQueue = write; return write;
}
function schedule(id, delay = 3000) {
  if (timers.has(id)) clearTimeout(timers.get(id));
  timers.set(id, setTimeout(() => { timers.delete(id); poll(id).catch(() => {}); }, delay));
}
async function poll(id) {
  if (polling.has(id)) return;
  polling.add(id);
  try {
  const {jobs = {}} = await chrome.storage.local.get('jobs');
  if (!jobs[id] || terminal.has(jobs[id].status)) return;
  try {
    const raw = await request('/job/' + encodeURIComponent(id));
    const job = raw.job || raw;
    await remember({...job, id, connection_error: ''});
    if (!terminal.has(job.status)) schedule(id);
  } catch (error) {
    if (error.status === 400 && /不存在/.test(error.message)) {
      await remember({...jobs[id], status: 'error', connection_error: '', errors: ['后台重启后，本次临时查询已失效。已保存客户不受影响；请重新查询这家公司。']});
      return;
    }
    await remember({...jobs[id], connection_error: error.message});
    schedule(id, 15000);
  }
  } finally { polling.delete(id); }
}
async function resume() {
  const {jobs = {}} = await chrome.storage.local.get('jobs');
  await Promise.all(Object.values(jobs).filter(j => !terminal.has(j.status)).map(j => poll(j.id)));
}
async function startResearch(message) {
  const website = validWebsite(message.website);
  const company = new URL(website).hostname.toLowerCase().replace(/^www\./, '');
  if (starting.has(company)) return starting.get(company);
  const task = (async () => {
    const {jobs = {}} = await chrome.storage.local.get('jobs');
    const matching = Object.values(jobs).filter(j => {
      try { return new URL(j.website).hostname.toLowerCase().replace(/^www\./, '') === company; } catch (_) { return false; }
    }).sort((a,b) => b.updated_at - a.updated_at);
    const active = matching.find(j => !terminal.has(j.status));
    if (active) { schedule(active.id, 0); return active; }
    // Opening the toolbar shows prior results rather than spending another
    // research call. A deliberate Re-query button still starts a fresh job.
    const prior = matching.find(j => ['done','completed'].includes(j.status));
    if (message.reuse_completed === true && prior) return prior;
    const raw = await request('/start', {method:'POST',body:JSON.stringify({website})});
    const job = raw.job || raw, id = job.id || job.job_id;
    if (!id) fail('后台没有返回查询编号，请稍后重试。');
    const result = {...job,id,website,status:job.status || 'queued',contacts:job.contacts || []};
    await remember(result);schedule(id,0);return result;
  })();
  starting.set(company,task);
  try { return await task; } finally { if (starting.get(company) === task) starting.delete(company); }
}
chrome.alarms.create('resume-research', {periodInMinutes: 0.5});
chrome.alarms.onAlarm.addListener(alarm => { if (alarm.name === 'resume-research') resume().catch(() => {}); });
chrome.runtime.onStartup.addListener(() => resume().catch(() => {}));
chrome.runtime.onInstalled.addListener(() => resume().catch(() => {}));
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (sender.id !== chrome.runtime.id || !sender.url || !sender.url.startsWith(chrome.runtime.getURL(''))) return;
  (async () => {
    if (message.type === 'health') return request('/health');
    if (message.type === 'start') return startResearch(message);
    if (message.type === 'refresh') { await resume(); return true; }
    if (message.type === 'customers') return request('/customers');
    if (message.type === 'save') return request('/save', {method: 'POST', body: JSON.stringify({job_id: message.job_id, contact_id: message.contact_id})});
    if (message.type === 'export') return request('/export');
    fail('不支持的操作。');
  })().then(result => sendResponse({ok: true, result}), error => sendResponse({ok: false, error: error.message}));
  return true;
});
