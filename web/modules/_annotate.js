// 阅读批注（调研报告、深读笔记、知识库文档、学习计划共用）：选中文字 → 「评论 / 问 Claude」，被评论的文字高亮，
// 讨论串列在旁边（窄屏在下方）；问 Claude 的回答就地挂在讨论串里，可以继续追问。数据在 /api/annotations。
// 用法：import { annotate } from './_annotate.js';
//   el.append(annotate(ctx, md(text), { doc: 'research:3:synth', title, link: '#research/r/3', source: text }))
//   compact: true —— 小段落（学习计划的步骤）：讨论串放在下方，没有批注时不占位置。
export function annotate(ctx, body, { doc, title = '', link = '', source = '', compact = false }) {
  const { api, h, md, toast, ui } = ctx;
  injectStyle();
  const rail = h('div.an-rail');
  const wrap = h('div.an-wrap' + (compact ? '.compact' : ''), {}, [h('div.an-body', {}, body), rail]);
  let threads = [];
  let showResolved = false;
  let composer = null; // 正在写的新批注 {quote, prefix, suffix, ask}
  let timer;

  const load = async () => {
    clearTimeout(timer);
    if (!wrap.isConnected && threads.length) return;
    try { threads = await api.get(`/api/annotations?doc=${encodeURIComponent(doc)}`); } catch { threads = []; }
    paint();
    if (threads.some((t) => t.msgs.some((m) => m.status === 'pending'))) timer = setTimeout(load, 1500);
  };

  // ---------- 高亮：在正文的文字里找回每条批注的原文（忽略空白差异，用前后文消歧） ----------
  function highlight() {
    body.querySelectorAll('mark.an-hl').forEach((m) => m.replaceWith(...m.childNodes));
    body.normalize();
    const lost = new Set();
    for (const t of threads) {
      if (!t.quote || (t.status === 'resolved' && !showResolved)) continue;
      const r = locate(body, t);
      if (!r) { lost.add(t.id); continue; }
      wrapRange(body, r[0], r[1], (m) => {
        m.dataset.aid = t.id;
        if (t.status === 'resolved') m.classList.add('resolved');
        m.onclick = () => focus(t.id);
      });
    }
    return lost;
  }

  function focus(id) {
    const card = rail.querySelector(`[data-aid="${id}"]`);
    if (!card) return;
    card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    card.classList.add('flash');
    setTimeout(() => card.classList.remove('flash'), 1200);
  }

  // ---------- 讨论串 ----------
  function paint() {
    const lost = highlight();
    const open = threads.filter((t) => t.status !== 'resolved');
    const resolved = threads.length - open.length;
    const shown = showResolved ? threads : open;
    // 按在正文里的位置排：全文的在最前，找不到原文的在最后
    const pos = (t) => {
      if (!t.quote) return -1;
      const m = body.querySelector(`mark.an-hl[data-aid="${t.id}"]`);
      return m ? m.getBoundingClientRect().top + window.scrollY : 1e9;
    };
    const sorted = [...shown].sort((a, b) => pos(a) - pos(b));
    wrap.classList.toggle('has-threads', !!threads.length || !!composer);
    rail.replaceChildren(...[
      h('div.an-head', {}, [
        h('b', {}, threads.length ? `批注 ${open.length}` : '批注'),
        resolved ? h('button.sm.ghost', { onclick: () => { showResolved = !showResolved; paint(); } }, showResolved ? '隐藏已解决' : `已解决 ${resolved}`) : null,
        h('span.grow'),
        h('button.sm.ghost', { title: '不划线，针对全文问 Claude', onclick: () => startNew({ quote: '', prefix: '', suffix: '', ask: true }) }, [ui.icon('spark'), '问全文']),
      ]),
      composer ? newCard() : null,
      ...sorted.map((t) => card(t, lost.has(t.id))),
      !threads.length && !composer ? h('div.an-hint', {}, '选中正文里的文字，可以写评论或直接问 Claude；讨论会保存下来，也会同步进知识库。') : null,
    ].filter(Boolean));
  }

  function startNew(c) {
    composer = c;
    paint();
    rail.querySelector('.an-new textarea')?.focus();
    rail.querySelector('.an-new')?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }

  function newCard() {
    const c = composer;
    const ta = h('textarea', { rows: 3, placeholder: c.ask ? '问 Claude 什么？留空 = 解释这段' : '写评论…（Enter 发送，Shift+Enter 换行）' });
    const send = async (ask) => {
      const text = ta.value.trim();
      if (!ask && !text) { ta.focus(); return toast('先写点评论', true); }
      try {
        await api.post('/api/annotations', { doc, title, link, quote: c.quote, prefix: c.prefix, suffix: c.suffix, text, ask, source });
        composer = null;
        window.getSelection()?.removeAllRanges();
        load();
      } catch (e) { toast(e.message, true); }
    };
    ta.onkeydown = (e) => {
      if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); send(c.ask || false); }
      if (e.key === 'Escape') { composer = null; paint(); }
    };
    return h('div.an-card.an-new', {}, [
      c.quote ? h('div.an-quote', {}, c.quote) : h('div.an-quote.all', {}, '针对全文'),
      ta,
      h('div.an-acts', {}, [
        h('button.sm.primary', { onclick: () => send(true) }, [ui.icon('spark'), '问 Claude']),
        h('button.sm.outline', { onclick: () => send(false) }, [ui.icon('chat'), '评论']),
        h('span.grow'),
        h('button.sm.ghost', { onclick: () => { composer = null; paint(); } }, '取消'),
      ]),
    ]);
  }

  function card(t, lost) {
    const pending = t.msgs.some((m) => m.status === 'pending');
    const ta = h('input', { type: 'text', placeholder: pending ? 'Claude 正在回答…' : '回复或追问（Enter 追问 Claude）', disabled: pending });
    const send = async (ask) => {
      const text = ta.value.trim();
      if (!text && !ask) return;
      try { await api.post(`/api/annotations/${t.id}/msgs`, { text, ask, source }); load(); } catch (e) { toast(e.message, true); }
    };
    ta.onkeydown = (e) => { if (e.key === 'Enter' && !e.isComposing && ta.value.trim()) send(true); };
    const setStatus = async (status) => { await api.patch(`/api/annotations/${t.id}`, { status }); load(); };
    const del = async () => { if (!confirm('删除这条批注和它的讨论？')) return; await api.del(`/api/annotations/${t.id}`); load(); };
    const msgs = t.msgs.map((m) => m.role === 'user'
      ? h('div.an-msg.me', {}, m.content)
      : h('div.an-msg.ai' + (m.status === 'pending' ? '.pending' : m.status === 'failed' ? '.failed' : ''), {}, [
        h('span.an-who', {}, [ui.icon('spark'), 'Claude']),
        m.content ? md(m.content) : null,
        m.status === 'pending' ? h('div.an-step', {}, ((x) => (x ? '正在：' + x : '正在读材料…'))((m.log || '').split('\n').filter(Boolean).slice(-1)[0])) : null,
      ]));
    const el = h('div.an-card' + (t.status === 'resolved' ? '.resolved' : ''), { 'data-aid': t.id }, [
      t.quote ? h('div.an-quote', { title: '在正文里定位', onclick: () => body.querySelector(`mark.an-hl[data-aid="${t.id}"]`)?.scrollIntoView({ behavior: 'smooth', block: 'center' }) },
        [t.quote, lost ? h('span.tag', { style: { marginLeft: '6px' } }, '原文已变') : null])
        : h('div.an-quote.all', {}, '针对全文'),
      ...msgs,
      h('div.an-reply', {}, [ta,
        h('button.sm.ghost', { title: '只记评论，不问 Claude', disabled: pending, onclick: () => send(false) }, ui.icon('chat')),
        h('button.sm.ghost', { title: t.status === 'resolved' ? '重新打开' : '标为已解决', onclick: () => setStatus(t.status === 'resolved' ? 'open' : 'resolved') }, ui.icon(t.status === 'resolved' ? 'refresh' : 'check')),
        h('button.sm.ghost', { title: '删除', onclick: del }, ui.icon('trash'))]),
    ]);
    el.onmouseenter = () => body.querySelectorAll(`mark.an-hl[data-aid="${t.id}"]`).forEach((m) => m.classList.add('on'));
    el.onmouseleave = () => body.querySelectorAll('mark.an-hl.on').forEach((m) => m.classList.remove('on'));
    return el;
  }

  // ---------- 选中文字弹出的工具条 ----------
  const bar = toolbar();
  const onUp = () => setTimeout(() => {
    const sel = window.getSelection();
    if (!sel || sel.isCollapsed || !sel.rangeCount) return;
    const r = sel.getRangeAt(0);
    if (!body.contains(r.commonAncestorContainer)) return;
    const quote = sel.toString().trim();
    if (quote.length < 2) return;
    const before = document.createRange(); before.setStart(body, 0); before.setEnd(r.startContainer, r.startOffset);
    const after = document.createRange(); after.setStart(r.endContainer, r.endOffset); after.setEnd(body, body.childNodes.length);
    const c = { quote: quote.slice(0, 2000), prefix: before.toString().slice(-80), suffix: after.toString().slice(0, 80) };
    const rect = r.getBoundingClientRect();
    bar.show(rect, (ask) => startNew({ ...c, ask }));
  });
  body.addEventListener('mouseup', onUp);
  body.addEventListener('keyup', (e) => { if (e.shiftKey) onUp(); });

  load();
  return wrap;

  // 一个页面共用一个工具条
  function toolbar() {
    let el = document.getElementById('an-bar');
    if (!el) {
      el = h('div#an-bar', { hidden: true });
      document.body.append(el);
      const hide = () => { el.hidden = true; };
      document.addEventListener('mousedown', (e) => { if (!el.contains(e.target)) hide(); });
      window.addEventListener('scroll', hide, true);
    }
    return {
      show(rect, pick) {
        el.replaceChildren(
          h('button', { onmousedown: (e) => e.preventDefault(), onclick: () => { el.hidden = true; pick(false); } }, [ui.icon('chat'), '评论']),
          h('button', { onmousedown: (e) => e.preventDefault(), onclick: () => { el.hidden = true; pick(true); } }, [ui.icon('spark'), '问 Claude']));
        el.hidden = false;
        const w = el.offsetWidth;
        el.style.left = `${Math.max(8, Math.min(window.innerWidth - w - 8, rect.left + rect.width / 2 - w / 2))}px`;
        el.style.top = `${rect.top > 48 ? rect.top - 42 : rect.bottom + 8}px`;
      },
    };
  }
}

// 正文所有文字节点拼起来，去掉空白后匹配（划线时 toString 带的换行和 DOM 里的不一样），再映射回节点位置
function textIndex(root) {
  const nodes = [];
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  let flat = '';
  for (let n = walker.nextNode(); n; n = walker.nextNode()) { nodes.push([n, flat.length]); flat += n.nodeValue; }
  let squeezed = '';
  const map = []; // squeezed 下标 → flat 下标
  for (let i = 0; i < flat.length; i++) if (!/\s/.test(flat[i])) { map.push(i); squeezed += flat[i]; }
  return { nodes, flat, squeezed, map };
}

const squeeze = (s) => (s || '').replace(/\s+/g, '');

function locate(root, t) {
  const idx = textIndex(root);
  const q = squeeze(t.quote);
  if (!q) return null;
  const pre = squeeze(t.prefix).slice(-30);
  const suf = squeeze(t.suffix).slice(0, 30);
  let best = -1, bestScore = -1;
  for (let i = idx.squeezed.indexOf(q); i >= 0; i = idx.squeezed.indexOf(q, i + 1)) {
    let score = 0;
    const before = idx.squeezed.slice(0, i), after = idx.squeezed.slice(i + q.length);
    while (score < pre.length && before[before.length - 1 - score] === pre[pre.length - 1 - score]) score++;
    let s2 = 0;
    while (s2 < suf.length && after[s2] === suf[s2]) s2++;
    if (score + s2 > bestScore) { best = i; bestScore = score + s2; }
  }
  if (best < 0) return null;
  return [idx.map[best], idx.map[best + q.length - 1] + 1];
}

function wrapRange(root, start, end, decorate) {
  const { nodes } = textIndex(root);
  for (const [node, off] of nodes) {
    const len = node.nodeValue.length;
    if (off + len <= start || off >= end) continue;
    let n = node;
    const s = Math.max(0, start - off), e = Math.min(len, end - off);
    if (!n.nodeValue.slice(s, e).trim()) continue; // 段落之间的空白不包
    if (e < len) n.splitText(e);
    if (s > 0) n = n.splitText(s);
    const mark = document.createElement('mark');
    mark.className = 'an-hl';
    decorate(mark);
    n.replaceWith(mark);
    mark.append(n);
  }
}

function injectStyle() {
  if (document.getElementById('an-style')) return;
  const s = document.createElement('style');
  s.id = 'an-style';
  s.textContent = `
  .an-wrap { display: grid; grid-template-columns: minmax(0, 1fr) minmax(230px, 300px); gap: 18px; align-items: start; }
  .an-wrap.compact, .an-wrap.compact.has-threads { grid-template-columns: minmax(0, 1fr); gap: 6px; }
  .an-wrap.compact:not(.has-threads) .an-rail { display: none; }
  @media (max-width: 1100px) { .an-wrap { grid-template-columns: minmax(0, 1fr); } }
  .an-rail { position: sticky; top: 12px; max-height: calc(100vh - 24px); overflow: auto; display: flex; flex-direction: column; gap: 8px;
    border-left: 1px solid var(--line); padding-left: 14px; }
  .an-wrap.compact .an-rail { position: static; max-height: none; border-left: 0; padding-left: 0; }
  @media (max-width: 1100px) { .an-rail { position: static; max-height: none; border-left: 0; padding-left: 0; border-top: 1px dashed var(--line); padding-top: 10px; } }
  .an-head { display: flex; align-items: center; gap: 6px; font-size: 13px; }
  .an-head .grow { flex: 1; }
  .an-hint { font-size: 12px; color: var(--muted); line-height: 1.6; }
  .an-card { background: var(--panel); border: 1px solid var(--line); border-radius: 10px; padding: 8px 10px; font-size: 13px; display: flex; flex-direction: column; gap: 6px;
    transition: box-shadow .2s; }
  .an-card.flash { box-shadow: 0 0 0 3px var(--accent-ring); }
  .an-card.resolved { opacity: .65; }
  .an-quote { border-left: 3px solid var(--accent); padding: 1px 0 1px 8px; color: var(--muted); font-size: 12px; line-height: 1.5; cursor: pointer;
    display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }
  .an-quote.all { border-left-color: var(--line-2); cursor: default; }
  .an-msg { line-height: 1.6; white-space: pre-wrap; word-break: break-word; }
  .an-msg.ai { white-space: normal; background: var(--bg-2); border-radius: 8px; padding: 6px 8px; }
  .an-msg.ai .md > :first-child { margin-top: 0; } .an-msg.ai .md > :last-child { margin-bottom: 0; }
  .an-msg.ai.failed { background: var(--err-soft); }
  .an-who { display: inline-flex; align-items: center; gap: 3px; font-size: 11px; color: var(--accent); font-weight: 600; }
  .an-who svg { width: 12px; height: 12px; }
  .an-step { font: 11px var(--mono, monospace); color: var(--muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .an-msg.pending .an-step::after { content: ' …'; animation: an-blink 1.2s infinite; }
  @keyframes an-blink { 50% { opacity: .2; } }
  .an-reply { display: flex; gap: 2px; align-items: center; }
  .an-reply input { flex: 1; min-width: 0; padding: 4px 10px; border-radius: 999px; font-size: 12px; }
  .an-new textarea { width: 100%; font-size: 13px; resize: vertical; }
  .an-acts { display: flex; gap: 6px; align-items: center; } .an-acts .grow { flex: 1; }
  mark.an-hl { background: var(--accent-soft); color: inherit; border-bottom: 2px solid var(--accent); cursor: pointer; padding: 0 1px; border-radius: 2px; }
  mark.an-hl.on { background: var(--accent-ring); }
  mark.an-hl.resolved { background: transparent; border-bottom-style: dashed; border-bottom-color: var(--line-2); }
  #an-bar { position: fixed; z-index: 50; display: flex; gap: 2px; padding: 3px; border-radius: 10px; background: var(--dark); box-shadow: 0 4px 16px rgba(0,0,0,.18); }
  #an-bar[hidden] { display: none; }
  #an-bar button { display: inline-flex; align-items: center; gap: 4px; background: transparent; color: var(--panel); border: 0; padding: 5px 10px; border-radius: 7px; font-size: 13px; cursor: pointer; }
  #an-bar button:hover { background: rgba(255,255,255,.14); }
  #an-bar svg { width: 14px; height: 14px; stroke: currentColor; }
  `;
  document.head.append(s);
}
