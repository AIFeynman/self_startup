// 共享 UI 组件：图标、大输入框、快捷 chip、页头、统计块、空状态。
// 板块页面：import { icon, composer, chips, pageHead, section, stats, empty, progress } from '../ui.js'
import { h, nowLocal } from './api.js';

const P = {
  home: 'M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6h-6v6H4a1 1 0 0 1-1-1z',
  review: 'M4 4h16v16H4z M8 9h8 M8 13h8 M8 17h5',
  plan: 'M8 3v3 M16 3v3 M4 7h16v13H4z M8 12h3 M8 16h6',
  feed: 'M5 12a7 7 0 0 1 7 7 M5 5a14 14 0 0 1 14 14 M6 19h.01',
  research: 'M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14z M20 20l-4-4',
  learn: 'M3 5h6a3 3 0 0 1 3 3v12a2 2 0 0 0-2-2H3z M21 5h-6a3 3 0 0 0-3 3v12a2 2 0 0 1 2-2h7z',
  kb: 'M4 4h11l5 5v11H4z M15 4v5h5 M8 13h8 M8 17h6',
  settings: 'M12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6z M19.4 15a1.6 1.6 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.6 1.6 0 0 0-1.8-.3 1.6 1.6 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.6 1.6 0 0 0-1-1.5 1.6 1.6 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.6 1.6 0 0 0 .3-1.8 1.6 1.6 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.6 1.6 0 0 0 1.5-1 1.6 1.6 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.6 1.6 0 0 0 1.8.3H9a1.6 1.6 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.6 1.6 0 0 0 1 1.5 1.6 1.6 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.6 1.6 0 0 0-.3 1.8V9a1.6 1.6 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.6 1.6 0 0 0-1.5 1z',
  leaf: 'M20 4C10 4 5 9 5 17c0 1 .2 2 .5 3 M20 4c0 9-5 14-13 14 M5 20c3-5 7-9 12-12 M9 13c-2-1-4-1-5 0 M12 9c-1-2-1-4 0-5',
  plus: 'M12 5v14 M5 12h14',
  send: 'M12 19V5 M6 11l6-6 6 6',
  spark: 'M12 3v4 M12 17v4 M3 12h4 M17 12h4 M6 6l2.5 2.5 M15.5 15.5 18 18 M6 18l2.5-2.5 M15.5 8.5 18 6',
  bulb: 'M9 18h6 M10 21h4 M12 3a6 6 0 0 0-3.5 10.9c.6.5 1 1.2 1 2V16h5v-.1c0-.8.4-1.5 1-2A6 6 0 0 0 12 3z',
  check: 'M5 12.5l4.5 4.5L19 7',
  clock: 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z M12 7v5l3 2',
  link: 'M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1 M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1',
  chat: 'M4 5h16v11H9l-5 4z',
  doc: 'M6 3h9l4 4v14H6z M14 3v5h5 M9 13h6 M9 17h4',
  refresh: 'M20 11a8 8 0 0 0-14.3-4.9L4 8 M4 4v4h4 M4 13a8 8 0 0 0 14.3 4.9L20 16 M20 20v-4h-4',
  star: 'M12 3l2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1L3.2 9.5l6.1-.9z',
  thumb: 'M7 11v9H4v-9z M7 11l4-8a2 2 0 0 1 2 2v4h5.5a2 2 0 0 1 2 2.3l-1.2 7A2 2 0 0 1 17.3 20H7',
  bolt: 'M13 3 5 14h6l-1 7 8-11h-6z',
  user: 'M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8z M4 21a8 8 0 0 1 16 0',
  robot: 'M12 3v3 M6 8h12v11H6z M9 13h.01 M15 13h.01 M3 12v3 M21 12v3',
  x: 'M6 6l12 12 M18 6 6 18',
  expand: 'M14 4h6v6 M20 4l-7 7 M10 20H4v-6 M4 20l7-7',
  search: 'M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14z M20 20l-4-4',
  arrow: 'M5 12h14 M13 6l6 6-6 6',
  tag: 'M3 12V4h8l10 10-8 8z M7.5 7.5h.01',
  box: 'M3 7l9-4 9 4-9 4z M3 7v10l9 4 9-4V7 M12 11v10',
  trash: 'M4 7h16 M9 7V4h6v3 M6 7l1 13h10l1-13',
  edit: 'M4 20h4L19 9l-4-4L4 16z M14 6l4 4',
};

export function icon(name, cls = '') {
  const ns = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(ns, 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('class', 'i ' + cls);
  for (const d of (P[name] || P.spark).split(' M').map((s, i) => (i ? 'M' + s : s))) {
    const p = document.createElementNS(ns, 'path');
    p.setAttribute('d', d);
    svg.append(p);
  }
  return svg;
}

/**
 * 大输入框。Enter 发送，Shift+Enter 换行；/ 键在页面任意处聚焦第一个 composer。
 * opts: { placeholder, hint, onSubmit(text, mode) => Promise|void, modes: [{id,label}], mode, value, rows, autofocus, compact }
 * 返回元素，el.setValue(text) / el.focus() / el.mode 可用。
 */
export function composer(opts = {}) {
  const ta = h('textarea', { rows: opts.rows || 1, placeholder: opts.placeholder || '说点什么…' });
  if (opts.value) ta.value = opts.value;
  const send = h('button.send', { title: '发送 (Enter)', disabled: !opts.value }, icon('send'));
  let mode = opts.mode || opts.modes?.[0]?.id || '';
  const modeBtns = (opts.modes || []).map((m) => h('button' + (m.id === mode ? '.on' : ''), {
    onclick: () => { mode = m.id; el.mode = mode; modeBtns.forEach((b, i) => b.classList.toggle('on', opts.modes[i].id === mode));
      if (m.placeholder) ta.placeholder = m.placeholder; ta.focus(); },
  }, m.label));
  const hint = h('span.hint', {}, opts.hint ?? '');
  const el = h('div.composer', {}, [ta, h('div.bar', {}, [modeBtns.length ? h('div.modes', {}, modeBtns) : null, hint, send])]);
  el.mode = mode;
  // 空的或还不可见（如收起的对话面板，宽度 0 时 scrollHeight 会很大）时不撑高
  const grow = () => { ta.style.height = 'auto'; if (ta.value && ta.offsetWidth) ta.style.height = Math.min(ta.scrollHeight, 240) + 'px'; send.disabled = !ta.value.trim(); };
  let busy = false;
  const submit = async () => {
    const text = ta.value.trim();
    if (!text || busy) return;
    busy = true; send.disabled = true;
    try {
      const r = await opts.onSubmit?.(text, mode);
      if (r !== false) { ta.value = ''; }
    } finally { busy = false; grow(); }
  };
  ta.addEventListener('input', grow);
  ta.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); submit(); }
  });
  send.addEventListener('click', submit);
  el.setValue = (v) => { ta.value = v; grow(); ta.focus(); ta.setSelectionRange(v.length, v.length); };
  el.focus = () => ta.focus();
  el.setHint = (t) => { hint.textContent = t; };
  if (opts.autofocus) setTimeout(() => ta.focus(), 30);
  setTimeout(grow, 0);
  return el;
}

// 快捷 chip：items = [{label, icon, onClick}]
export function chips(items, { left = false } = {}) {
  return h('div.chips' + (left ? '.left' : ''), {}, items.map((it) =>
    h('button.chip', { onclick: it.onClick, title: it.title || '' }, [it.icon ? icon(it.icon) : null, it.label])));
}

// 页头：大衬线标题 + 副标题 + 右侧操作
export function pageHead(title, sub = '', actions = []) {
  return h('div.page-head', {}, [h('div.titles', {}, [h('h1', {}, title), sub ? h('div.sub', {}, sub) : null]),
    ...[].concat(actions).filter(Boolean)]);
}

// 分节标题：—— 标题 ——————— 右侧说明
export const section = (title, extra = '') => h('div.section-title', {}, [title, extra ? h('span.extra', {}, extra) : null]);

// 统计块：[{k:'完成', v:'3/5'}]
// stats([{k, v, onClick?, active?}])：带 onClick 的卡片可点击（用于筛选）
export const stats = (items) => h('div.stats', {}, items.map((s) => h('div.stat' + (s.onClick ? '.click' : '') + (s.active ? '.on' : ''),
  s.onClick ? { onclick: s.onClick, title: s.title || '点击筛选', role: 'button' } : {}, [h('span.v', {}, s.v), h('span.k', {}, s.k)])));

export const empty = (title, sub = '') => h('div.empty', {}, [h('div.serif', {}, title), sub ? h('div', {}, sub) : null]);

export const progress = (pct) => h('div.progress', {}, h('i', { style: { width: Math.max(0, Math.min(100, pct)) + '%' } }));

// 问候语
export function greeting() {
  const hr = +nowLocal().slice(11, 13);
  return hr < 6 ? '夜深了' : hr < 11 ? '早上好' : hr < 13 ? '中午好' : hr < 18 ? '下午好' : '晚上好';
}

// 全局：按 / 聚焦页面上的第一个输入框
document.addEventListener('keydown', (e) => {
  if (e.key !== '/' || e.metaKey || e.ctrlKey) return;
  const tag = document.activeElement?.tagName;
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
  const ta = document.querySelector('#page .composer textarea');
  if (ta) { e.preventDefault(); ta.focus(); }
});
