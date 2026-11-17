// X 长文库：AI 相关 X 长文，按质量分 / 时间 / 观看数 / 作者粉丝排序，可设最低质量；顶部主搜索输入的关键词在库内筛选，没有就一键去 X 上搜（后端见 app/modules/_xart.py）。
// 路由：#kb/xart
const CSS = `
.xa-bar { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-bottom: 10px; }
.xa-bar select { font: inherit; width: auto; padding: 6px 10px; border: 1px solid var(--line-2); border-radius: 8px; background: var(--panel); color: var(--text); }
.xa-bar input { flex: 1; min-width: 180px; }
.xa-x { padding: 12px 16px; margin-bottom: 14px; }
.xa-x .row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.xa-x .muted { font-size: 12.5px; }
.xa-x .muted:last-child { margin-top: 6px; }
.xa-list { display: grid; gap: 8px; }
.xa-it { display: grid; grid-template-columns: 44px 1fr; gap: 12px; padding: 12px 14px; border: 1px solid var(--line); border-radius: var(--radius-sm); background: var(--panel); }
.xa-q { font: 600 20px var(--serif); text-align: center; color: var(--muted); line-height: 1.2; }
.xa-q small { display: block; white-space: nowrap; font: 11px var(--sans, inherit); color: var(--muted); }
.xa-q.hi { color: var(--accent); }
.xa-it h4 { margin: 0 0 3px; font-size: 15px; line-height: 1.4; }
.xa-it h4 a { color: var(--text); } .xa-it h4 a:hover { color: var(--accent); }
.xa-sum { font-size: 13.5px; line-height: 1.6; }
.xa-full img { display: block; max-width: 100%; height: auto; margin: 8px 0; border-radius: 6px; }
.xa-full { margin-top: 8px; padding: 10px 12px; max-height: 420px; overflow: auto; white-space: pre-wrap; overflow-wrap: anywhere; font-size: 13px; line-height: 1.7; background: var(--panel-2, var(--panel)); border: 1px solid var(--line); border-radius: 8px; }
.xa-take { font-size: 12.5px; color: var(--muted); margin-top: 3px; }
.xa-meta { display: flex; flex-wrap: wrap; gap: 4px 10px; align-items: center; margin-top: 6px; font-size: 12px; color: var(--muted); font-variant-numeric: tabular-nums; }
.xa-tag { font-size: 11.5px; color: var(--muted); border: 1px solid var(--line); border-radius: 999px; padding: 0 7px; white-space: nowrap; }
@media (max-width: 640px) { .xa-it { grid-template-columns: 30px 1fr; gap: 8px; padding: 10px; } }
`;
let cssDone = false;
const IMG = /^!\[\]\((https:\/\/[^\s)]+)\)$/;
const fill = (h, box, text) => {
  box.textContent = '';
  text.split('\n').forEach((ln, i, all) => {
    const m = IMG.exec(ln);
    if (m) box.append(h('img', { src: m[1], loading: 'lazy', referrerpolicy: 'no-referrer' }));
    else box.append(ln + (i < all.length - 1 && !IMG.test(all[i + 1]) ? '\n' : ''));
  });
};
const css = () => { if (cssDone) return; cssDone = true; document.head.append(Object.assign(document.createElement('style'), { textContent: CSS })); };
const fmt = (n) => (n >= 10000 ? (n / 10000).toFixed(1) + ' 万' : String(n || 0));
const stored = (k, d) => { try { return localStorage.getItem('xa-' + k) ?? d; } catch { return d; } };
const keep = (k, v) => { try { localStorage.setItem('xa-' + k, v); } catch { /* 私密窗口不存 */ } };

export function xartTab(body, ctx) {
  css();
  const { api, h, ui, toast } = ctx;
  const f = { q: '', sort: stored('sort', 'q'), q_min: stored('qmin', '2') };
  const sel = (key, opts, label) => h('select', { 'aria-label': label, onchange: (e) => { f[key] = e.target.value; keep(key === 'q_min' ? 'qmin' : key, f[key]); load(); } },
    opts.map(([v, n]) => h('option', { value: v, ...(f[key] === v ? { selected: true } : {}) }, n)));
  const bar = h('div.xa-bar', {}, [
    sel('sort', [['q', '按质量分'], ['date', '按时间'], ['views', '按观看数'], ['fol', '按作者粉丝']], '排序'),
    sel('q_min', [['1', '质量 ≥1'], ['2', '质量 ≥2'], ['3', '质量 ≥3'], ['4', '质量 ≥4']], '最低质量'),
  ]);
  const out = h('div');
  body.append(bar, out);

  let seq = 0;
  async function load() {
    const mine = ++seq;
    const p = new URLSearchParams({ q: f.q, sort: f.sort, q_min: f.q_min, limit: 200 });
    const items = (await api.get('/api/kb/xarticles?' + p)).items;
    if (mine !== seq) return;
    const n = items.length;
    out.replaceChildren(
      ui.section(f.q ? `「${f.q}」` : 'X 长文', [`${n}${n >= 200 ? '+' : ''} 篇 · ${{ q: '质量分高的在前', date: '最新的在前', views: '观看数多的在前', fol: '作者粉丝多的在前' }[f.sort] || ''}`,
        ...(f.q ? [' · ', h('a', { href: '#', onclick: (e) => { e.preventDefault(); f.q = ''; load(); } }, '清除关键词')] : [])]),
      f.q ? h('div.card.xa-x', {}, [h('div.row', {}, [
        h('span.muted', {}, '库里没有想要的？'),
        h('button.outline', { onclick: () => fetchX(f.q) }, `去 X 上搜「${f.q}」并入库`)]), xnote]) : '',
      n ? h('div.xa-list', {}, items.map(card)) : ui.empty('没有符合条件的长文', '放宽最低质量，或换个关键词'),
    );
  }
  const xnote = h('div.muted', {}, '关键词支持 X 搜索语法，比如 from:omarsar0、"context engineering"。取阅读最高的 40 篇读全文、提炼、打分，约 0.05 美元，1–3 分钟。');

  async function fetchX(q) {
    try { await api.post('/api/kb/xarticles/search', { q, days: 30 }); } catch (e) { toast(e.message, true); return; }
    poll();
  }
  async function poll() {
    const s = await api.get('/api/kb/xarticles/search');
    if (!body.isConnected) return;
    if (s.running) { xnote.textContent = `正在 X 上搜「${s.q}」，抓全文并提炼中…`; setTimeout(poll, 3000); return; }
    if (s.error) { xnote.textContent = '搜索失败：' + s.error; return; }
    if (s.result) {
      const r = s.result;
      xnote.textContent = `搜到 ${r.found} 篇，新读 ${r.new} 篇，入库打分 ${r.scored} 篇。`;
      f.q_min = '1'; f.q = s.q.replace(/"/g, '').split(/\s+/).map((w) => w.replace(/^from:/i, '')).filter((w) => w && !w.includes(':')).join(' ');
      load();
    }
  }

  function card(a) {
    let box = null, orig = '', zh = '', showZh = false;
    const tr = h('a', { href: '#', style: 'display:none', onclick: async (e) => {
      e.preventDefault();
      if (showZh) { showZh = false; tr.textContent = '翻译成中文'; fill(h, box, orig); return; }
      if (!zh) {
        tr.textContent = '翻译中…（长文要几十秒）';
        try { zh = (await api.post('/api/kb/xarticles/' + a.id + '/translate', {})).text; } catch (err) { tr.textContent = '翻译失败：' + err.message; return; }
      }
      showZh = true; tr.textContent = '看原文'; fill(h, box, zh);
    } }, '翻译成中文');
    const toggle = h('a', { href: '#', onclick: async (e) => {
      e.preventDefault();
      if (box) { box.remove(); box = null; toggle.textContent = '展开全文'; tr.style.display = 'none'; return; }
      box = h('div.xa-full', {}, '加载中…');
      info.after(box);
      toggle.textContent = '收起全文';
      try { orig = (await api.get('/api/kb/xarticles/' + a.id)).text || '（没有存全文）'; showZh = false; tr.textContent = '翻译成中文'; tr.style.display = ''; fill(h, box, orig); } catch (err) { box.textContent = '加载失败：' + err.message; }
    } }, '展开全文');
    const info = h('div.xa-meta', {}, [`@${a.user}`, `${fmt(a.fol)} 粉丝`, a.day, `${fmt(a.views)} 观看`, `${fmt(a.likes)} 赞`, a.kind].map((t) => h('span', {}, t)).concat(...a.tags.map((t) => h('span.xa-tag', {}, t)), toggle, tr));
    return h('div.xa-it', {}, [
      h('div.xa-q' + (a.q >= 4 ? '.hi' : ''), {}, [String(a.q), h('small', {}, '质量')]),
      h('div', {}, [
        h('h4', {}, h('a', { href: a.url, target: '_blank', rel: 'noopener' }, a.title)),
        h('div.xa-sum', {}, a.summary),
        a.take ? h('div.xa-take', {}, '可迁移：' + a.take) : null,
        info,
      ]),
    ]);
  }
  load();
  return { search: (q) => { f.q = q; return load(); } };
}
