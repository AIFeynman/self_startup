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
  div.querySelectorAll('a').forEach((a) => { a.target = '_blank'; a.rel = 'noopener'; });
  return div;
}

export function toast(msg, isErr = false) {
  const t = h('div.toast' + (isErr ? '.err' : ''), {}, msg);
  document.body.append(t);
  setTimeout(() => t.remove(), 3500);
}

export const today = () => new Date().toLocaleDateString('sv-SE'); // YYYY-MM-DD

// 简单表单字段：field('标题', inputEl)
export const field = (label, input) => h('label.field', {}, [h('span', {}, label), input]);
