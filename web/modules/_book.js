// 深度读书：#learn/book/<id>（书的封面：全书导读 + 目录）、#learn/book/<id>/ch/<n>（像读书一样一篇篇往下读）。
// 每篇三种看法：导读（来龙去脉 / 精髓 / 分节导读，打开时用轻量模型生成并预生成下一篇）、原文（按 PDF 页排版，分节导读可跳到对应段落）、PDF 原页。
// ← / → 翻篇；划线可评论或问 Claude（批注挂在 learn:book:<id>:ch:<n>）。
import { annotate } from './_annotate.js';

export const BOOK_CSS = `
.bk-cover { display: grid; grid-template-columns: 132px minmax(0, 1fr); gap: 22px; align-items: start; margin-bottom: 18px; }
.bk-spine { aspect-ratio: 2 / 3; border-radius: 4px 10px 10px 4px; background: linear-gradient(135deg, var(--accent), color-mix(in srgb, var(--accent) 55%, #000));
  color: #fff; padding: 14px 12px; display: flex; flex-direction: column; justify-content: space-between; box-shadow: inset 6px 0 0 rgba(0,0,0,.18), 0 6px 18px rgba(0,0,0,.12); }
.bk-spine b { font-family: var(--serif); font-size: 15px; line-height: 1.3; display: -webkit-box; -webkit-line-clamp: 6; -webkit-box-orient: vertical; overflow: hidden; }
.bk-spine span { font-size: 11px; opacity: .85; }
.bk-cover h1 { font-family: var(--serif); font-size: 26px; line-height: 1.3; margin: 0 0 6px; }
.bk-cover .meta { color: var(--muted); font-size: 13px; margin-bottom: 10px; }
.bk-cover .thesis { font-family: var(--serif); font-size: 17px; line-height: 1.7; margin: 10px 0 12px; padding-left: 12px; border-left: 3px solid var(--accent); }
.bk-actions { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; margin-top: 10px; }
.bk-ov { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 14px; margin-bottom: 8px; }
.bk-ov .card h4 { margin: 0 0 8px; font-size: 14px; color: var(--accent); font-weight: 600; letter-spacing: .02em; }
.bk-ov .card p { margin: 0; line-height: 1.8; font-size: 14px; }
.bk-ess { margin: 0; padding-left: 20px; line-height: 1.8; font-size: 14.5px; } .bk-ess li { margin-bottom: 6px; }
.bk-thread { margin-bottom: 10px; font-size: 14px; line-height: 1.7; } .bk-thread b { margin-right: 6px; }
.bk-thread .chs { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 4px; }
.bk-thread .chs a { font-size: 12px; padding: 0 7px; border-radius: 6px; background: var(--accent-soft); color: var(--accent); line-height: 20px; }
.bk-toc { columns: 2 360px; column-gap: 28px; }
.bk-part { break-inside: avoid; font-family: var(--serif); font-size: 15px; font-weight: 600; margin: 14px 0 6px; color: var(--accent); }
.bk-row { break-inside: avoid; display: grid; grid-template-columns: 14px minmax(0, 1fr) auto; gap: 8px; padding: 6px 8px; border-radius: 8px; cursor: pointer; align-items: baseline; }
.bk-row:hover { background: var(--panel); }
.bk-row .t { font-size: 14px; line-height: 1.45; } .bk-row.section .t { font-style: italic; } .bk-row.lv1 { padding-left: 22px; }
.bk-row.matter { opacity: .55; } .bk-row .one { display: block; font-size: 12.5px; color: var(--muted); font-style: normal; margin-top: 2px; }
.bk-row .pg { font-size: 12px; color: var(--muted); font-variant-numeric: tabular-nums; }
.bk-dot { width: 8px; height: 8px; border-radius: 50%; border: 1.5px solid var(--line-2); display: inline-block; }
.bk-dot.ready { border-color: var(--accent); } .bk-dot.read { background: var(--accent); border-color: var(--accent); }
.bk-dot.generating { border-color: var(--warn, #c90); animation: bkpulse 1.2s infinite; }
@keyframes bkpulse { 50% { opacity: .3; } }
.bk-read { display: grid; grid-template-columns: 220px minmax(0, 1fr); gap: 22px; align-items: start; }
.bk-read.side-off { grid-template-columns: 28px minmax(0, 1fr); }
.bk-side { position: sticky; top: 12px; max-height: calc(100vh - 28px); overflow: auto; font-size: 13px; }
.bk-side .k { display: flex; align-items: center; font-size: 12px; color: var(--muted); margin-bottom: 6px; } .bk-side .k span { flex: 1; }
.bk-side .k button, .bk-side .open { border: 0; background: none; color: var(--muted); padding: 0 4px; font-size: 12px; }
.bk-side a { display: flex; gap: 6px; align-items: center; padding: 4px 6px; border-left: 2px solid var(--line); color: var(--muted); line-height: 1.35; }
.bk-side a.sec { padding-left: 16px; font-style: italic; } .bk-side a.on { color: var(--accent); border-left-color: var(--accent); background: var(--accent-soft); }
.bk-side a:hover { color: var(--accent); } .bk-side .pt { font-size: 11.5px; color: var(--accent); margin: 10px 0 4px; font-weight: 600; }
.bk-read.side-off .bk-side > :not(.open) { display: none; } .bk-side .open { display: none; writing-mode: vertical-rl; } .bk-read.side-off .bk-side .open { display: block; }
.bk-head .k { color: var(--muted); font-size: 13px; }
.bk-modes { display: inline-flex; border: 1px solid var(--line-2); border-radius: 9px; overflow: hidden; }
.bk-modes button { border: 0; border-radius: 0; padding: 5px 14px; background: none; }
.bk-modes button.on { background: var(--accent); color: #fff; }
.bk-guide { font-size: 15px; line-height: 1.85; }
.bk-guide .lead { font-family: var(--serif); font-size: 19px; line-height: 1.6; margin: 0 0 18px; }
.bk-guide h3 { font-family: var(--serif); font-size: 18px; margin: 22px 0 10px; padding-bottom: 4px; border-bottom: 1px solid var(--line); }
.bk-ctx { display: grid; gap: 8px; } .bk-ctx div b { color: var(--accent); font-weight: 600; margin-right: 6px; }
.bk-guide blockquote { margin: 4px 0 0; padding: 2px 10px; border-left: 2px solid var(--line-2); color: var(--muted); font-family: var(--serif); font-size: 14px; }
.bk-sec { padding: 12px 14px; border: 1px solid var(--line); border-radius: 10px; margin-bottom: 10px; background: var(--panel); }
.bk-sec .st { display: flex; align-items: baseline; gap: 8px; font-weight: 600; margin-bottom: 4px; } .bk-sec .st span { flex: 1; }
.bk-sec .st .n { flex: none; color: var(--accent); font-variant-numeric: tabular-nums; }
.bk-sec .o, .bk-sec .e { font-size: 14px; margin-top: 4px; } .bk-sec .o b, .bk-sec .e b { color: var(--muted); font-weight: 500; margin-right: 4px; }
.bk-sec .e { color: var(--text); } .bk-sec .e b { color: var(--accent); }
.bk-terms { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 6px 16px; font-size: 14px; }
.bk-walk .bk-talk p { margin: 0 0 12px; } .bk-walk > .bk-talk:first-of-type p:first-child { font-size: 15.5px; }
.bk-seg { padding: 14px 0 6px; border-top: 1px dashed var(--line); }
.bk-seg .st { display: flex; align-items: baseline; gap: 8px; font-family: var(--serif); font-size: 17px; font-weight: 600; margin-bottom: 8px; }
.bk-seg .st .n { color: var(--accent); font-size: 13px; font-variant-numeric: tabular-nums; }
.bk-seg blockquote { margin: 2px 0 10px; }
.bk-orig { margin: 4px 0 10px; } .bk-orig summary { cursor: pointer; color: var(--accent); font-size: 13px; }
.bk-orig-body { margin-top: 8px; padding: 14px 18px; background: var(--bg); border: 1px solid var(--line); border-radius: 6px; max-height: 60vh; overflow: auto; }
.bk-orig-body pre { white-space: pre-wrap; word-break: break-word; font-family: var(--serif); font-size: 14.5px; line-height: 1.8; margin: 0; padding: 0; background: none; border: 0; color: var(--text); }
.bk-take { margin: 18px 0 8px; padding: 12px 16px; border-left: 3px solid var(--accent); background: var(--accent-soft); border-radius: 0 8px 8px 0; }
.bk-take h4 { margin: 0 0 6px; font-size: 14px; color: var(--accent); } .bk-take ol { margin: 0; padding-left: 20px; }
.bk-more { margin: 12px 0; } .bk-more summary { cursor: pointer; color: var(--muted); font-size: 13.5px; margin-bottom: 6px; }
.bk-q { display: flex; gap: 8px; align-items: baseline; margin-bottom: 6px; } .bk-q span { flex: 1; }
.bk-page { max-width: 720px; margin: 0 auto 18px; padding: 28px 38px 18px; background: var(--panel); border: 1px solid var(--line); border-radius: 6px;
  box-shadow: 0 1px 0 var(--line), 0 6px 16px rgba(0,0,0,.04); }
.bk-page pre { white-space: pre-wrap; word-break: break-word; font-family: var(--serif); font-size: 15.5px; line-height: 1.85; margin: 0; padding: 0; background: none; border: 0; color: var(--text); }
.bk-page .pn { text-align: center; color: var(--muted); font-size: 12px; margin-top: 10px; }
.bk-page mark.bk-jump { background: color-mix(in srgb, var(--accent) 28%, transparent); border-radius: 3px; animation: bkflash 2.4s ease-out; }
@keyframes bkflash { 0% { background: var(--accent); } }
.bk-pdf { width: 100%; height: calc(100vh - 150px); border: 1px solid var(--line); border-radius: 8px; background: #fff; }
.bk-nav { display: flex; justify-content: space-between; gap: 12px; margin: 22px 0 8px; }
.bk-nav button { max-width: 48%; } .bk-nav button span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.bk-wait { display: flex; gap: 12px; align-items: center; }
.bk-card { cursor: pointer; } .bk-card h3 { font-family: var(--serif); font-size: 18px; margin: 4px 0 6px; line-height: 1.35; }
@media (max-width: 860px) {
  .bk-read, .bk-read.side-off { grid-template-columns: minmax(0, 1fr); } .bk-side { position: static; max-height: 200px; }
  .bk-cover { grid-template-columns: 84px minmax(0, 1fr); gap: 14px; } .bk-page { padding: 18px 16px; }
  .bk-head .page-head { flex-wrap: wrap; align-items: center; } .bk-head .page-head .titles { flex-basis: 100%; }
}
`;

const KIND_TXT = { chapter: '章', section: '篇', front: '导论', matter: '附录' };
const BUSY = ['ingesting', 'toc'];
const MODE_KEY = 'bk-mode';
const SIDE_KEY = 'bk-side-off';
const store = { get: (k) => { try { return localStorage.getItem(k) || ''; } catch { return ''; } }, set: (k, v) => { try { localStorage.setItem(k, v); } catch { /* ignore */ } } };
const chHref = (bid, idx) => `#learn/book/${bid}/ch/${idx}`;
const usd = (x) => (x < 0.01 ? '<$0.01' : `$${x.toFixed(2)}`);
const dotOf = (h, c) => h('span.bk-dot.' + (c.read_at ? 'read' : c.status || 'none'), { title: c.read_at ? '读过' : c.status === 'ready' ? '导读已生成' : c.status === 'generating' ? '导读生成中' : '未读' });
const later = new Set(); // 正在轮询的书 / 篇，避免重复定时器

function poll(key, fn, ms = 3000) {
  if (later.has(key)) return;
  later.add(key);
  setTimeout(() => { later.delete(key); fn(); }, ms);
}

// ---------- 总览里的「深度读书」 ----------
export function bookCards(books, ctx) {
  const { h, ui } = ctx;
  return h('div.grid', {}, books.map((b) => {
    const pct = b.chapters_total ? Math.round((100 * b.chapters_read) / b.chapters_total) : 0;
    return h('div.card.bk-card', { onclick: () => { location.hash = `#learn/book/${b.id}`; } }, [
      h('span.card-label', {}, b.status === 'ready' ? `${b.pages} 页 · ${b.chapters_total} 篇` : b.status === 'failed' ? '解析失败' : '正在解析…'),
      h('h3', {}, b.title || b.url),
      b.overview?.one_line ? h('div.muted.clamp2', { style: { fontSize: '13px', marginBottom: '8px' } }, b.overview.one_line) : null,
      h('div.row', {}, [h('div.grow', {}, ui.progress(pct)), h('span.muted', {}, `读过 ${b.chapters_read}/${b.chapters_total}`)]),
    ]);
  }));
}

// ---------- 书的封面：全书导读 + 目录 ----------
export async function renderBook(el, ctx, bid, { back, refresh, watchJob }) {
  const { api, h, toast, ui, openChat } = ctx;
  let b;
  try { b = await api.get(`/api/learn/books/${bid}`); } catch { el.append(back(h, ui), ui.empty('书不存在')); return; }
  el.append(back(h, ui, '#learn', '深度学习'));
  const chat = () => openChat({ module: 'learn', ref: `learn:book:${bid}`, title: '读书：' + (b.title || '').slice(0, 16) });
  if (BUSY.includes(b.status)) {
    el.append(ui.pageHead(b.title || '正在打开这本书', b.url), h('div.card.bk-wait', {}, [h('span.dots', {}, b.status === 'toc' ? '目录页没解析出来，正在让模型从前几页抄出目录' : '正在下载 PDF、提取文字、按目录拆章（大书约半分钟）'), h('span.grow')]));
    if (b.status === 'toc') watchJob(ctx, b.overview_job, 'generating');
    poll(`book-${bid}`, refresh);
    return;
  }
  if (b.status === 'failed') {
    el.append(ui.pageHead(b.title || '解析失败', b.url), h('div.card', {}, [ui.empty('这本书没能打开', b.error || ''),
      h('div.row', { style: { justifyContent: 'center', gap: '8px' } }, [
        h('button.primary', { onclick: async () => { await api.post(`/api/learn/books/${bid}/reingest`, {}); refresh(); } }, [ui.icon('refresh'), '重新解析']),
        h('button.ghost', { onclick: async () => { if (!confirm('删除这本书？（批注不会删）')) return; await api.del(`/api/learn/books/${bid}`); location.hash = '#learn'; } }, [ui.icon('trash'), '删除'])])]));
    return;
  }
  const ov = b.overview || {};
  const readable = b.chapters.filter((c) => c.kind !== 'matter');
  const cur = b.chapters.find((c) => c.idx === b.cur_idx && c.kind !== 'matter') || readable[0];
  const started = readable.some((c) => c.read_at);
  const pct = readable.length ? Math.round((100 * b.chapters_read) / readable.length) : 0;
  const overviewBusy = b.overview_status === 'generating';
  if (overviewBusy) watchJob(ctx, b.overview_job, 'generating');

  el.append(h('div.bk-cover', {}, [
    h('div.bk-spine', {}, [h('b', {}, ov.title || b.title), h('span', {}, [b.author || ov.author || '', ov.year ? ` · ${ov.year}` : ''].join(''))]),
    h('div', {}, [
      h('h1', {}, ov.title || b.title),
      h('div.meta', {}, [b.author || ov.author, ov.year, `${b.pages} 页`, `${readable.length} 篇`, METHOD_TXT[b.method] || ''].filter(Boolean).join(' · ')),
      ov.one_line ? h('div.thesis', {}, ov.one_line) : overviewBusy ? h('div.muted.dots', {}, '正在写全书导读（精髓、成书背景、结构、读法），约 1 分钟') : null,
      h('div.row', {}, [h('div.grow', { style: { maxWidth: '320px' } }, ui.progress(pct)), h('span.muted', {}, `读过 ${b.chapters_read}/${readable.length} · 导读已生成 ${b.chapters_ready} 篇`)]),
      h('div.bk-actions', {}, [
        cur ? h('button.primary', { onclick: () => { location.hash = chHref(bid, cur.idx); } }, [ui.icon('arrow'), started ? `继续读：${cur.title.slice(0, 26)}` : '开始阅读']) : null,
        h('button', { onclick: chat }, [ui.icon('chat'), '聊这本书']),
        b.overview_status === 'failed' || (b.overview_status === 'ready' && !overviewBusy) ? h('button.ghost', { onclick: async () => {
          if (!confirm('重新生成全书导读？')) return; await api.post(`/api/learn/books/${bid}/overview`, {}); toast('正在重写全书导读'); refresh(); } }, [ui.icon('refresh'), '重写全书导读']) : null,
        h('span.muted', { title: `按轻量模型（Haiku）估算：全书正文约 ${(b.est_tokens / 1000).toFixed(0)}K token 输入；只为打开过的篇付费` }, `全书逐篇导读预计 ${usd(b.est_cost)}`),
      ]),
    ]),
  ]));

  if (b.overview_status === 'failed') el.append(h('div.card', {}, ui.empty('全书导读生成失败', '可以点「重写全书导读」重试；不影响逐篇阅读')));
  if (ov.essence) {
    const threads = (ov.threads || []).filter((t) => t && t.name);
    const byIdx = Object.fromEntries(b.chapters.map((c) => [c.idx, c]));
    el.append(ui.section('全书导读', '先看地图，再进章节'), h('div.bk-ov', {}, [
      h('div.card', {}, [h('h4', {}, '全书精髓'), h('ol.bk-ess', {}, ov.essence.map((e) => h('li', {}, String(e))))]),
      h('div.card', {}, [h('h4', {}, '作者与时代'), h('p', {}, ov.author_context || ''), ov.era_context ? h('p', { style: { marginTop: '8px' } }, ov.era_context) : null]),
      h('div.card', {}, [h('h4', {}, '全书结构'), h('p', {}, ov.structure || '')]),
      threads.length ? h('div.card', {}, [h('h4', {}, '贯穿全书的主线'), ...threads.map((t) => h('div.bk-thread', {}, [h('b', {}, t.name), t.desc,
        h('div.chs', {}, (t.chapters || []).filter((i) => byIdx[i]).map((i) => h('a', { href: chHref(bid, i), title: byIdx[i].title }, byIdx[i].title.replace(/^Chapter\s+/i, '').slice(0, 22))))]))]) : null,
      ov.how_to_read ? h('div.card', {}, [h('h4', {}, '怎么读'), h('p', {}, ov.how_to_read)]) : null,
    ]));
  }

  el.append(ui.section('目录', `${readable.length} 篇 · 点任意一篇开始读`), h('div.card', {}, h('div.bk-toc', {}, tocRows(h, bid, b.chapters))));
  el.append(h('div.row', { style: { marginTop: '14px', justifyContent: 'flex-end' } }, [
    h('a.muted', { href: b.url.startsWith('http') ? b.url : '#', target: '_blank', style: { fontSize: '12px', marginRight: 'auto' } }, b.url),
    h('button.ghost.sm', { onclick: async () => { if (!confirm('删除这本书和它的导读？（批注不会删）')) return; await api.del(`/api/learn/books/${bid}`); location.hash = '#learn'; } }, [ui.icon('trash'), '删除这本书'])]));
  if (b.chapters.some((c) => c.status === 'generating')) poll(`book-${bid}`, refresh, 5000);
}

const METHOD_TXT = { outline: '按书签拆章', toc: '按目录页拆章', toc_llm: '按模型识别的目录拆章', headings: '按章标题拆章', fixed: '没找到目录，按每 30 页分段' };

function tocRows(h, bid, chapters, { compact = false, current = -1 } = {}) {
  const out = [];
  let part = null;
  for (const c of chapters) {
    if (c.part !== part) {
      part = c.part;
      if (part) out.push(h(compact ? 'div.pt' : 'div.bk-part', {}, part));
    }
    if (compact) {
      if (c.kind === 'matter') continue;
      out.push(h('a' + (c.kind === 'section' ? '.sec' : '') + (c.idx === current ? '.on' : ''), { href: chHref(bid, c.idx), title: c.one_line || c.title }, [dotOf(h, c), h('span', {}, c.title)]));
      continue;
    }
    out.push(h(`div.bk-row.${c.kind}${c.level ? '.lv1' : ''}`, { onclick: () => { location.hash = chHref(bid, c.idx); } }, [
      dotOf(h, c),
      h('span.t', {}, [c.title, c.one_line ? h('span.one', {}, c.one_line) : null]),
      h('span.pg', {}, `p${c.page_start + 1}`),
    ]));
  }
  return out;
}

// ---------- 读一篇 ----------
const opened = new Set();
export async function renderBookChapter(el, ctx, bid, idx, { back, refresh, watchJob }) {
  const { api, h, toast, ui, openChat } = ctx;
  let b, c;
  try { [b, c] = await Promise.all([api.get(`/api/learn/books/${bid}`), api.get(`/api/learn/books/${bid}/chapters/${idx}`)]); } catch { el.append(back(h, ui, `#learn/book/${bid}`, '这本书'), ui.empty('没有这一篇')); return; }
  const key = `${bid}:${idx}`;
  if (!opened.has(key)) { // 第一次打开：记进度、没导读就生成、预生成下一篇
    opened.add(key);
    if (c.kind !== 'matter') {
      const r = await api.post(`/api/learn/books/${bid}/chapters/${idx}/open`, {}).catch(() => null);
      if (r?.job_id && c.status !== 'ready') Object.assign(c, { status: 'generating', job_id: r.job_id });
    }
  }
  let mode = c.kind === 'matter' ? 'text' : (store.get(MODE_KEY) || 'guide');
  const go = (x) => { if (x) location.hash = chHref(bid, x.idx); };
  const chat = (prefill) => openChat({ module: 'learn', ref: `learn:book:${bid}:ch:${idx}`, title: '本篇：' + c.title.slice(0, 16), prefill });
  const pages = `PDF 第 ${c.page_start + 1}${c.page_end > c.page_start ? `–${c.page_end + 1}` : ''} 页`;

  el.append(back(h, ui, `#learn/book/${bid}`, b.title));
  const modes = h('div.bk-modes', {}, [['guide', '导读'], ['text', '原文'], ['pdf', 'PDF 原页']].map(([k, t]) =>
    h('button' + (mode === k ? '.on' : ''), { disabled: k === 'guide' && c.kind === 'matter', onclick: () => { mode = k; if (c.kind !== 'matter') store.set(MODE_KEY, k); paint(); } }, t)));
  el.append(h('div.bk-head', {}, ui.pageHead(c.title, h('span.k', {}, [c.part, `${KIND_TXT[c.kind] || '篇'} · ${pages}`, c.status === 'ready' ? `本篇导读约 ${usd(c.est_cost)}` : ''].filter(Boolean).join(' · ')), [
    modes, h('button.primary', { onclick: () => chat() }, [ui.icon('chat'), '问这一篇'])])));

  const side = h('nav.bk-side', {}, [h('button.open', { onclick: () => setSide(false) }, '目录 »'),
    h('div.k', {}, [h('span', {}, b.title), h('button', { title: '收起目录', onclick: () => setSide(true) }, '«')]), ...tocRows(h, bid, b.chapters, { compact: true, current: idx })]);
  const main = h('div', { style: { minWidth: 0 } });
  const wrap = h('div.bk-read' + (store.get(SIDE_KEY) ? '.side-off' : ''), {}, [side, main]);
  const setSide = (off) => { wrap.classList.toggle('side-off', off); store.set(SIDE_KEY, off ? '1' : ''); };
  el.append(wrap);
  setTimeout(() => side.querySelector('a.on')?.scrollIntoView({ block: 'center' }), 0);

  let textCache = null;
  const nav = () => h('div.bk-nav', {}, [
    c.prev ? h('button', { onclick: () => go(c.prev), title: '← 键' }, [h('span', {}, '← ' + c.prev.title)]) : h('span'),
    c.next ? h('button.outline', { onclick: () => go(c.next), title: '→ 键' }, [h('span', {}, c.next.title + ' →')])
      : h('button.outline', { onclick: () => { location.hash = `#learn/book/${bid}`; } }, '读完了，回到封面'),
  ]);

  async function paint(jump) {
    modes.querySelectorAll('button').forEach((x, i) => x.classList.toggle('on', ['guide', 'text', 'pdf'][i] === mode));
    main.replaceChildren();
    if (mode === 'pdf') {
      main.append(h('iframe.bk-pdf', { src: `/api/learn/books/${bid}/pdf#page=${c.page_start + 1}` }), nav());
      return;
    }
    if (mode === 'text') {
      main.append(h('div.muted.dots', {}, '加载原文'));
      await loadText();
      const body = h('div', {}, textCache.pages.map((p) => h('div.bk-page', { id: `bk-p-${p.n}` }, [h('pre', {}, reflow(p.text)), h('div.pn', {}, `— ${p.n} —`)])));
      main.replaceChildren(annotate(ctx, body, { doc: `learn:book:${bid}:ch:${idx}:text`, title: `${b.title} · ${c.title}（原文）`, link: chHref(bid, idx),
        source: textCache.pages.map((p) => reflow(p.text)).join('\n'), actions: [{ icon: 'chat', label: '这段在说什么', onPick: (q) => chat(`「${q}」\n这段在说什么？放在本章的论证里起什么作用？`) }] }), nav());
      if (jump) setTimeout(() => jumpTo(body, jump), 30);
      return;
    }
    main.append(guideView());
    main.append(nav());
  }

  function guideView() {
    if (c.status === 'generating' || !c.status) {
      watchJob(ctx, c.job_id, 'generating');
      const line = h('span.dots', {}, '正在读这一篇、写伴读（顺着原文一段段讲）');
      const tick = async () => {
        if (!line.isConnected || !c.job_id) return;
        const j = await api.get(`/api/jobs/${c.job_id}`).catch(() => null);
        if (!j) return;
        if (j.status === 'queued') line.textContent = '排队中（前面还有任务）';
        else if (j.status === 'running') line.textContent = `正在写导读 · 已用 ${Math.round(j.elapsed_s ?? 0)} 秒（轻量模型，通常 30–90 秒）`;
        if (['queued', 'running'].includes(j.status)) setTimeout(tick, 3000); else refresh();
      };
      tick();
      return h('div.card', {}, [h('div.bk-wait', {}, [line, h('span.grow'), h('button.ghost.sm', { onclick: () => { mode = 'text'; paint(); } }, '先读原文')])]);
    }
    if (c.status === 'failed') {
      return h('div.card', {}, [ui.empty('导读生成失败', '可以重试，或先读原文'), h('div.row', { style: { justifyContent: 'center' } },
        h('button.primary', { onclick: async () => { await api.post(`/api/learn/books/${bid}/chapters/${idx}/open`, { force: true }); refresh(); } }, [ui.icon('refresh'), '重试']))]);
    }
    const g = c.guide || {};
    const body = g.walk ? walkView(g) : guideV1(g);
    return h('div.card', { style: { padding: '22px 26px' } }, [
      annotate(ctx, body, { doc: `learn:book:${bid}:ch:${idx}`, title: `${b.title} · ${c.title}`, link: chHref(bid, idx), source: body.textContent }),
      h('div.row', { style: { marginTop: '14px', justifyContent: 'flex-end' } }, [
        c.job_id ? h('a.muted', { href: `/api/jobs/${c.job_id}`, target: '_blank', style: { fontSize: '12px' } }, `job ${c.job_id}`) : null,
        h('button.ghost.sm', { onclick: async () => { if (!confirm('重新生成这一篇的导读？')) return; await api.post(`/api/learn/books/${bid}/chapters/${idx}/open`, { force: true }); toast('正在重写本篇导读'); refresh(); } }, [ui.icon('refresh'), '重写导读'])]),
    ]);
  }

  const loadText = async () => (textCache = textCache || await api.get(`/api/learn/books/${bid}/chapters/${idx}/text`).catch(() => ({ pages: [] })));
  const toText = (anchor) => { mode = 'text'; paint(anchor); };
  const paras = (t) => String(t || '').split(/\n+/).map((x) => x.trim()).filter(Boolean).map((x) => h('p', {}, x));

  // 伴读：开场 → 顺着原文一段段讲（每段下面可展开对照原文这一段）→ 收尾 → 带走三句话
  function walkView(g) {
    let slices = null;
    const fill = async (box, i) => {
      if (box.dataset.done) return;
      box.dataset.done = '1';
      box.replaceChildren(h('div.muted.dots', {}, '加载原文'));
      slices = slices || splitByAnchors((await loadText()).pages.map((p) => reflow(p.text)).join('\n\n'), g.walk.map((w) => w.anchor));
      const t = slices[i];
      box.replaceChildren(t ? h('pre', {}, t) : h('div.muted', {}, '没在原文里定位到这一段，可以到「原文」里找'),
        h('div.row', { style: { justifyContent: 'flex-end', marginTop: '6px' } }, h('button.sm.ghost', { onclick: () => toText(g.walk[i].anchor) }, '在整篇原文里看 →')));
    };
    const segs = g.walk.map((w, i) => {
      const box = h('div.bk-orig-body');
      const det = h('details.bk-orig', { ontoggle: () => { if (det.open) fill(box, i); } }, [h('summary', {}, '对照原文这一段'), box]);
      return h('section.bk-seg', {}, [
        h('div.st', {}, [h('span.n', {}, String(i + 1).padStart(2, '0')), h('span', {}, w.title)]),
        h('div.bk-talk', {}, paras(w.talk)),
        w.quote ? h('blockquote', {}, w.quote) : null,
        w.anchor ? det : null]);
    });
    const allBtn = h('button.sm.ghost', { onclick: () => {
      const dets = [...body.querySelectorAll('details.bk-orig')];
      const open = !dets.every((d) => d.open);
      dets.forEach((d) => { d.open = open; });
      allBtn.textContent = open ? '收起原文' : '展开全部原文';
    } }, '展开全部原文');
    const body = h('div.bk-guide.bk-walk', {}, [
      g.one_line ? h('p.lead', {}, g.one_line) : null,
      h('div.bk-talk', {}, paras(g.opening)),
      h('div.row', { style: { justifyContent: 'flex-end', margin: '-4px 0 6px' } }, allBtn),
      ...segs,
      g.closing ? h('h3', {}, '回头看') : null,
      h('div.bk-talk', {}, paras(g.closing)),
      (g.essence || []).length ? h('div.bk-take', {}, [h('h4', {}, '带走三句话'),
        h('ol', {}, g.essence.map((e) => h('li', {}, [typeof e === 'string' ? e : e.point, e.quote ? h('blockquote', {}, e.quote) : null])))]) : null,
      (g.terms || []).length ? h('details.bk-more', {}, [h('summary', {}, `术语（${g.terms.length}）`),
        h('div.bk-terms', {}, g.terms.map((t) => h('div', {}, [h('b', {}, t.term), '：', t.explain])))]) : null,
      (g.questions || []).length ? h('h3', {}, '读完自问') : null,
      ...(g.questions || []).map((q) => h('div.bk-q', {}, [h('span', {}, '· ' + q), h('button.sm.ghost', { onclick: () => chat(`${q}\n我的理解：`) }, '写下我的回答')])),
    ]);
    return body;
  }

  // 旧版导读（来龙去脉 / 精髓 / 分节卡片），已生成的照旧显示
  function guideV1(g) {
    const cx = g.context || {};
    return h('div.bk-guide', {}, [
      g.one_line ? h('p.lead', {}, g.one_line) : null,
      h('h3', {}, '来龙去脉'),
      h('div.bk-ctx', {}, [['为什么在这里', cx.why_here], ['背景', cx.background], ['前面讲过、这里要用', cx.prereq]].filter(([, v]) => v).map(([k, v]) => h('div', {}, [h('b', {}, k), v]))),
      h('h3', {}, '本篇精髓'),
      h('ol.bk-ess', {}, (g.essence || []).map((e) => h('li', {}, [h('b', {}, e.point), e.why ? ` —— ${e.why}` : '', e.quote ? h('blockquote', {}, e.quote) : null]))),
      (g.sections || []).length ? h('h3', {}, '分节导读') : null,
      ...(g.sections || []).map((s, i) => h('div.bk-sec', {}, [
        h('div.st', {}, [h('span.n', {}, String(i + 1).padStart(2, '0')), h('span', {}, s.title),
          s.anchor ? h('button.sm.ghost', { title: '跳到原文这一节', onclick: () => toText(s.anchor) }, '读原文 →') : null]),
        h('div', {}, s.summary),
        s.origin ? h('div.o', {}, [h('b', {}, '来龙去脉'), s.origin]) : null,
        s.essence ? h('div.e', {}, [h('b', {}, '精髓'), s.essence]) : null])),
      (g.terms || []).length ? h('h3', {}, '术语') : null,
      (g.terms || []).length ? h('div.bk-terms', {}, g.terms.map((t) => h('div', {}, [h('b', {}, t.term), '：', t.explain]))) : null,
      g.links && (g.links.back || g.links.forward) ? h('h3', {}, '前后呼应') : null,
      g.links?.back ? h('div', {}, [h('b', {}, '呼应前文：'), g.links.back]) : null,
      g.links?.forward ? h('div', {}, [h('b', {}, '埋下伏笔：'), g.links.forward]) : null,
      (g.questions || []).length ? h('h3', {}, '读完自问') : null,
      ...(g.questions || []).map((q) => h('div.bk-q', {}, [h('span', {}, '· ' + q), h('button.sm.ghost', { onclick: () => chat(`${q}\n我的理解：`) }, '写下我的回答')])),
    ]);
  }

  // ← / → 翻篇（输入框里不触发）；页面换掉后自动解绑
  const onKey = (e) => {
    if (!wrap.isConnected) { document.removeEventListener('keydown', onKey); return; }
    if (e.target.closest?.('input, textarea, [contenteditable]') || e.metaKey || e.ctrlKey || e.altKey) return;
    if (e.key === 'ArrowLeft') go(c.prev);
    if (e.key === 'ArrowRight') go(c.next);
  };
  document.removeEventListener('keydown', window.__bkKey || (() => {}));
  window.__bkKey = onKey;
  document.addEventListener('keydown', onKey);
  paint();
}

// PDF 抽出的文字每行硬换行：段内换行接起来（英文补空格、中文直接接，行尾连字符去掉），
// 比常见行长短得多的行（段落末行、小标题）后面保留换行
function reflow(text) {
  const lines = text.replace(/\s+$/, '').split('\n').map((l) => l.trimEnd());
  const lens = lines.map((l) => l.trim().length).filter((n) => n > 0).sort((a, b) => a - b);
  const full = lens[Math.floor(lens.length * 0.75)] || 0;
  let out = '';
  lines.forEach((l, i) => {
    const t = l.trim();
    out += i ? '' : t;
    if (!i) return;
    const prev = lines[i - 1].trim();
    if (!t || !prev || prev.length < full * 0.7) { out += '\n' + t; return; }
    if (/[A-Za-z]-$/.test(prev) && /^[a-z]/.test(t)) { out = out.slice(0, -1) + t; return; }
    out += (/[\u3000-\u9fff\uff00-\uffef]$/.test(prev) && /^[\u3000-\u9fff\uff00-\uffef]/.test(t) ? '' : ' ') + t;
  });
  return out.replace(/\n{3,}/g, '\n\n');
}

// 在原文里找到分节导读给的开头几个词（忽略空白和断行连字符），高亮并滚过去
function anchorRes(anchor) {
  const words = String(anchor || '').replace(/[“”"'‘’]/g, '').split(/\s+/).filter(Boolean).slice(0, 6);
  if (!words.length) return [];
  const esc = (w) => w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  return [new RegExp(words.map(esc).join('[\\s\\-­]+'), 'i'), new RegExp(words.slice(0, 3).map(esc).join('[\\s\\-­]+'), 'i')];
}

// 按伴读各段的 anchor 把整篇原文切开：第 i 段 = 它的开头到下一个定位到的开头；第一段从篇首起。
// 定位不到、或位置倒退的段返回 null（前一段会顺延覆盖它）
// 开头前一行是小标题（短、不以句末标点结尾）时，从标题行开始切，标题就不会挂在上一段末尾
function headStart(full, p) {
  const lineStart = full.lastIndexOf('\n', p - 1) + 1;
  if (full.slice(lineStart, p).trim()) return p;
  const prevStart = full.lastIndexOf('\n', lineStart - 2) + 1;
  const prev = full.slice(prevStart, lineStart).trim();
  return prev && prev.length <= 60 && !/[.!?。！？:;：；"”»)]$/.test(prev) ? prevStart : p;
}

function splitByAnchors(full, anchors) {
  let last = -1;
  const pos = anchors.map((a) => {
    for (const r of anchorRes(a)) {
      const m = new RegExp(r.source, 'gi');
      m.lastIndex = last + 1;
      const hit = m.exec(full);
      if (hit) { last = hit.index; return headStart(full, hit.index); }
    }
    return null;
  });
  return pos.map((p, i) => {
    if (p == null) return null;
    const start = i === pos.findIndex((x) => x != null) ? 0 : p;
    const next = pos.slice(i + 1).find((x) => x != null);
    return full.slice(start, next ?? full.length).trim();
  });
}

function jumpTo(body, anchor) {
  const res = anchorRes(anchor);
  for (const r of res) {
    for (const pre of body.querySelectorAll('pre')) {
      const node = pre.firstChild;
      if (!node || node.nodeType !== 3) continue;
      const m = r.exec(node.data);
      if (!m) continue;
      const range = document.createRange();
      range.setStart(node, m.index);
      range.setEnd(node, m.index + m[0].length);
      const mark = document.createElement('mark');
      mark.className = 'bk-jump';
      range.surroundContents(mark);
      mark.scrollIntoView({ block: 'center', behavior: 'smooth' });
      return;
    }
  }
}
