// 论文「为什么不 XX」：深读页写替代方案 + 猜测，后台两层核验（论文自己 → 后续论文引用链），判断页看计分。
// 后端见 app/kb_whynot.py；whyNotPanel 用在 learn.js 论文条目页，whyNotSection 用在 kb.js 判断页。
const CSS = `
.wn-form { display: flex; flex-direction: column; gap: 8px; }
.wn-form textarea { min-height: 54px; }
.wn-form .row { flex-wrap: wrap; gap: 8px; }
.wn-form select { width: auto; flex: none; }
.wn-guess { display: inline-flex; border: 1px solid var(--line-2); border-radius: 999px; overflow: hidden; }
.wn-guess button { border: 0; border-radius: 0; padding: 4px 12px; font-size: 13px; background: var(--panel); }
.wn-guess button.on { background: var(--text); color: var(--bg); }
.wn-item { border-top: 1px solid var(--line); padding: 12px 0 4px; }
.wn-item:first-child { border-top: 0; padding-top: 2px; }
.wn-q { font: 600 15px/1.5 var(--serif); }
.wn-q small { font: 400 12.5px var(--sans, inherit); color: var(--muted); margin-left: 6px; }
.wn-layer { margin: 8px 0 0 2px; padding-left: 10px; border-left: 3px solid var(--line-2); font-size: 13.5px; line-height: 1.6; }
.wn-layer.done { border-left-color: var(--accent); }
.wn-layer .hd { display: flex; gap: 8px; align-items: baseline; flex-wrap: wrap; }
.wn-layer .hd b { font-size: 12.5px; color: var(--muted); font-weight: 500; }
.wn-v { font-size: 12px; padding: 1px 8px; border-radius: 999px; background: var(--line); color: var(--text); white-space: nowrap; }
.wn-v.good { background: #e3f1e6; color: #2f6b3c; } .wn-v.bad { background: #f8e3df; color: #9b3b26; }
.wn-v.mid { background: #efe9dd; color: #7a5b1f; } .wn-v.none { background: #ece8f4; color: #5f4a8a; }
.wn-quote { margin: 4px 0; color: var(--muted); font-style: italic; }
.wn-cite { margin: 3px 0; }
.wn-cite a { font-weight: 500; }
.wn-hit { font-size: 12px; margin-left: 6px; }
.wn-hint { color: var(--muted); margin-top: 4px; }
`;
let cssDone = false;
const css = () => { if (cssDone) return; cssDone = true; document.head.append(Object.assign(document.createElement('style'), { textContent: CSS })); };

const GUESSES = ['更好', '差不多', '更差', '说不准'];
const vClass = (v) => ({ 'XX 更好': 'good', 'XX 更差': 'bad', 差不多: 'mid', 有条件: 'mid', 还没人做: 'none' }[v] || '');
const vText = (v) => (v || '').replace('XX ', '替代方案');

function layer(ctx, w, c, name) {
  const { h } = ctx;
  if (!c) return null;
  const d = c.detail || {};
  if (c.status === 'running') return h('div.wn-layer', {}, h('div.hd', {}, [h('b', {}, name), h('span.muted.dots', {}, name === '后续论文' ? '沿引用链检索中（通常 1–3 分钟）' : '读论文原文中')]));
  if (c.status === 'failed') return h('div.wn-layer', {}, h('div.hd', {}, [h('b', {}, name), h('span', { style: { color: 'var(--err)' } }, '没查成：' + (c.summary || '未知原因'))]));
  const meta = name === '后续论文' && d.n_citations != null ? `引用它的 ${d.n_citations} 篇 + 关键词检索 → 筛出 ${d.n_candidates} 篇读摘要` : (d.fulltext === false ? '没找到 PDF，只读了深读笔记' : '');
  return h('div.wn-layer.done', {}, [
    h('div.hd', {}, [h('b', {}, name), h('span.wn-v.' + vClass(c.verdict), {}, vText(c.verdict) || '—'), h('span.muted', { style: { fontSize: '12px' } }, `${meta}${meta ? ' · ' : ''}${c.secs}s · ${c.at.slice(5, 16).replace('T', ' ')}`)]),
    h('div', {}, c.summary),
    ...(d.quotes || []).map((q) => h('div.wn-quote', {}, `“${q.text}”${q.where ? ' — ' + q.where : ''}`)),
    ...(d.cites || []).map((p) => h('div.wn-cite', {}, [h('a', { href: p.url, target: '_blank', rel: 'noopener' }, p.title), h('span.muted', {}, ` · ${p.year || ''}${p.cites_original ? ' · 引用了原论文' : ''}${p.strength ? ' · ' + p.strength : ''}`),
      p.finding ? h('div', {}, p.finding) : null])),
    d.hint ? h('div.wn-hint', {}, '要权衡的：' + d.hint) : null,
    d.next ? h('div.wn-hint', {}, '下一步：' + d.next) : null,
  ]);
}

function hitTag(h, w) {
  if (w.hit == null) return w.verdict === '还没人做' ? h('span.wn-hit.muted', {}, '· 还没人做，90 天后再查') : null;
  return h('span.wn-hit', { style: { color: w.hit >= 1 ? '#2f6b3c' : w.hit > 0 ? '#7a5b1f' : '#9b3b26' } }, w.hit >= 1 ? '· 猜对了' : w.hit > 0 ? '· 猜对一半（有条件）' : '· 猜错了');
}

// 一条「为什么不」：问题 + 两层核验结果；showPaper = 判断页上带论文标题
export function whyNotItem(ctx, w, { showPaper = false, onChange } = {}) {
  const { h, api, toast } = ctx;
  css();
  const recheck = async () => { await api.post(`/api/kb/whynot/${w.id}/recheck`, {}); toast('重新核验中'); onChange?.(); };
  return h('div.wn-item', {}, [
    showPaper && w.item ? h('div', {}, h('a.muted', { href: `#learn/item/${w.item_id}`, style: { fontSize: '12.5px' } }, '《' + w.item.title + '》')) : null,
    h('div.wn-q', {}, ['为什么不 ', w.alt, '？', h('small', {}, `我猜${w.guess === '说不准' ? '说不准' : '替代方案' + w.guess}${w.confidence ? ' · 信心' + w.confidence : ''} · ${w.created_at.slice(0, 10)}`), hitTag(h, w)]),
    w.reason ? h('div.muted', { style: { fontSize: '13px' } }, '理由：' + w.reason) : null,
    layer(ctx, w, w.paper, '论文自己'),
    layer(ctx, w, w.followup, '后续论文'),
    h('div.row', { style: { marginTop: '6px', gap: '10px' } }, [
      w.sid ? h('a.muted', { href: '#kb/judge', style: { fontSize: '12px' } }, '已记进判断台账') : null, h('span.grow'),
      w.running ? null : h('button.sm.ghost', { onclick: recheck, title: '另起一次核验（旧结果保留）' }, '重查'),
    ]),
  ]);
}

// 深读页面板：写一条 + 这篇的全部
export function whyNotPanel(ctx, it) {
  const { h, api, ui, toast } = ctx;
  css();
  const list = h('div');
  const box = h('div.card', {}, list);
  let timer = 0;
  const load = async () => {
    clearTimeout(timer);
    if (!box.isConnected && timer) return;
    const ws = await api.get(`/api/kb/whynot?item_id=${it.id}`).catch(() => []);
    list.replaceChildren(form(), ...ws.map((w) => whyNotItem(ctx, w, { onChange: load })));
    if (ws.some((w) => w.running)) timer = setTimeout(load, 4000);
  };
  function form() {
    const alt = h('textarea', { placeholder: '先别急着看实验：换成你来设计，会做什么不同的选择？例如：先整体规划再执行，而不是每步交替 Thought / Action' });
    let guess = '说不准';
    const gBox = h('span.wn-guess');
    const drawG = () => gBox.replaceChildren(...GUESSES.map((g) => h('button' + (g === guess ? '.on' : ''), { onclick: () => { guess = g; drawG(); } }, g)));
    drawG();
    const cf = h('select', {}, [['', '信心'], ['高', '信心高'], ['中', '信心中'], ['低', '信心低']].map(([v, l]) => h('option', { value: v }, l)));
    const reason = h('input', { placeholder: '为什么这么猜（可选）', style: { flex: 1, minWidth: '180px' } });
    const btn = h('button.primary', { onclick: async () => {
      if (!alt.value.trim()) return;
      btn.disabled = true;
      try { await api.post('/api/kb/whynot', { item_id: it.id, alt: alt.value, guess, confidence: cf.value, reason: reason.value }); toast('记下了：先查论文自己有没有回答，再沿引用链找后续论文'); }
      catch (e) { toast(String(e.message || e)); btn.disabled = false; return; }
      load();
    } }, '记下并核验');
    return h('div.wn-form', {}, [alt, h('div.row', {}, [h('span.muted', {}, '我猜替代方案比论文做法'), gBox, cf, reason, btn])]);
  }
  load();
  return [ui.section('为什么不', '写下你会怎么做不同的选择，再看论文和后续论文怎么回答'), box];
}

// 判断页：计分 + 最近的
export async function whyNotSection(ctx) {
  const { h, api, ui } = ctx;
  css();
  const o = await api.get('/api/kb/whynot').catch(() => null);
  if (!o || !o.stats.total) return [];
  const S = o.stats;
  const list = h('div.card', {}, o.items.map((w) => whyNotItem(ctx, w, { showPaper: true })));
  return [ui.section('为什么不', `${S.total} 条 · ${S.papers} 篇论文 · 在深读论文页里写`),
    ui.stats([
      { k: `命中率 · 有结论且我下了判断的 ${S.scored} 条`, v: S.hit_rate == null ? '—' : Math.round(S.hit_rate * 100) + '%' },
      { k: '论文或后续论文已回答', v: S.answered },
      { k: '还没人做（先想到 · 90 天后再查）', v: S.untested },
    ]), list];
}
