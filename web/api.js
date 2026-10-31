// 前端通用工具：请求、DOM、markdown。板块页面 import { api, h, md, toast } from '../api.js'

async function req(method, url, body) {
  const r = await fetch(url, {
    method,
    headers: body !== undefined ? { 'Content-Type': 'application/json' } : {},
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  const text = await r.text();
  let data;
  try { data = text ? JSON.parse(text) : null; } catch { data = text; }
  if (!r.ok) throw new Error((data && data.detail) ? JSON.stringify(data.detail) : `${r.status} ${text}`);
  return data;
}

export const api = {
  get: (u) => req('GET', u),
  post: (u, b = {}) => req('POST', u, b),
  put: (u, b = {}) => req('PUT', u, b),
  patch: (u, b = {}) => req('PATCH', u, b),
  del: (u) => req('DELETE', u),
  // 轮询后台 job 直到结束；onTick(job) 每次回调
  async waitJob(id, onTick, intervalMs = 2500) {
    for (;;) {
      const j = await req('GET', `/api/jobs/${id}`);
      onTick && onTick(j);
      if (j.status === 'done' || j.status === 'failed') return j;
      await new Promise((r) => setTimeout(r, intervalMs));
    }
  },
};

// h('div.card', {onclick}, [children]) —— 极简 DOM 构造
export function h(tag, attrs = {}, children = []) {
  const id = (tag.match(/#([\w-]+)/) || [])[1];
  const [name, ...classes] = tag.replace(/#[\w-]+/, '').split('.');
  const el = document.createElement(name || 'div');
  if (id) el.id = id;
  if (classes.length) el.className = classes.join(' ');
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === undefined || v === null || v === false) continue;
    if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2), v);
    else if (k === 'html') el.innerHTML = v;
    else if (k === 'style' && typeof v === 'object') Object.assign(el.style, v);
    else if (k === 'value') el.value = v;
    else if (k in el && typeof v !== 'string') el[k] = v;
    else el.setAttribute(k, v === true ? '' : v);
  }
  for (const c of [].concat(children)) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

export function md(text) {
  const div = document.createElement('div');
  div.className = 'md';
  div.innerHTML = window.marked ? window.marked.parse(text || '') : (text || '').replace(/</g, '&lt;').replace(/\n/g, '<br>');
  // 站外链接新标签打开；#learn/... 这类站内链接在当前页跳转
  div.querySelectorAll('a').forEach((a) => { if (!a.getAttribute('href')?.startsWith('#')) { a.target = '_blank'; a.rel = 'noopener'; } });
  return div;
}

export function toast(msg, isErr = false) {
  const t = h('div.toast' + (isErr ? '.err' : ''), {}, msg);
  document.body.append(t);
  setTimeout(() => t.remove(), 3500);
}

// 平台时区：服务端按它写时间、划分日期（/api/meta 的 tz，设置里的 timezone 或按作息推断）。
// 页面上的「今天」「现在」、不带时区的时间串都按它算，不跟浏览器所在时区走，否则两边会差出一天。
let TZ;
export const setTz = (tz) => { try { new Intl.DateTimeFormat('sv-SE', { timeZone: tz || undefined }); TZ = tz || undefined; } catch { TZ = undefined; } };
const WALL = { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23' };
// 平台时区的墙上时间 YYYY-MM-DDTHH:MM:SS（和服务端 db.now() 同格式）
export const nowLocal = (ms = Date.now()) => new Intl.DateTimeFormat('sv-SE', { ...WALL, timeZone: TZ }).format(ms).replace(' ', 'T');
export const today = () => nowLocal().slice(0, 10); // YYYY-MM-DD
// 服务端时间串 → 毫秒时间戳；不带时区的按平台时区解释
export const toMs = (s) => {
  s = String(s).replace(' ', 'T');
  if (/(Z|[+-]\d\d:?\d\d)$/.test(s)) return Date.parse(s);
  const asUtc = Date.parse(s + 'Z');
  return asUtc - (Date.parse(nowLocal(asUtc) + 'Z') - asUtc);
};

// 简单表单字段：field('标题', inputEl)
export const field = (label, input) => h('label.field', {}, [h('span', {}, label), input]);
