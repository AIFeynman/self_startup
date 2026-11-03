// 论文脉络：输入一个研究主题，从论文库里梳理出几条按时间演进的研究线（后端见 app/modules/_paper_map.py）。
// 路由：#kb/papers（主题列表）#kb/papers/<主题>（某个主题的脉络）
const CSS = `
.pm-ask { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; padding: 14px 16px; }
.pm-ask input { flex: 1; min-width: 200px; font: inherit; padding: 7px 10px; border: 1px solid var(--line-2); border-radius: 8px; background: var(--panel); color: var(--text); }
.pm-ask .muted { width: 100%; font-size: 12.5px; }
.pm-maps { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 10px; }
.pm-maps a { display: block; padding: 12px 14px; border: 1px solid var(--line); border-radius: var(--radius-sm); background: var(--panel); color: var(--text); }
.pm-maps a:hover { border-color: var(--accent); text-decoration: none; }
.pm-maps b { font: 600 15px var(--serif); display: block; margin-bottom: 2px; }
.pm-maps small { color: var(--muted); font-size: 12px; }
.pm-meta { display: flex; flex-wrap: wrap; gap: 6px 14px; color: var(--muted); font-size: 13px; margin: -4px 0 12px; align-items: center; }
.pm-ov { font: 15px/1.75 var(--serif); padding: 14px 18px; background: var(--focus); border-radius: var(--radius); border: 1px solid var(--line); margin-bottom: 16px; }
.pm-lanes { padding: 12px 16px 8px; margin-bottom: 16px; overflow-x: auto; }
.pm-lane { display: grid; grid-template-columns: 128px 1fr; align-items: center; min-width: 400px; height: 26px; }
.pm-lane > a { font-size: 12.5px; color: var(--text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; padding-right: 10px; }
.pm-lane > a:hover { color: var(--accent); text-decoration: none; }
.pm-track { position: relative; height: 100%; border-bottom: 1px dashed var(--line); }
.pm-dot { position: absolute; top: 50%; width: 9px; height: 9px; margin: -4.5px 0 0 -4.5px; border-radius: 50%; background: var(--muted); opacity: .75; cursor: pointer; }
.pm-dot.ms { width: 12px; height: 12px; margin: -6px 0 0 -6px; background: var(--accent); opacity: 1; }
.pm-dot:hover { outline: 2px solid var(--accent-ring); opacity: 1; }
.pm-axis { display: grid; grid-template-columns: 128px 1fr; min-width: 400px; }
.pm-axis div { position: relative; height: 18px; }
.pm-axis span { position: absolute; transform: translateX(-50%); font-size: 11px; color: var(--muted); font-variant-numeric: tabular-nums; }
.pm-found { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 8px; margin-bottom: 8px; }
.pm-found a { display: block; padding: 8px 12px; border: 1px solid var(--line); border-radius: var(--radius-sm); background: var(--panel); color: var(--text); font-size: 13px; }
.pm-found a:hover { border-color: var(--accent); text-decoration: none; }
.pm-found small { color: var(--muted); display: block; font-size: 12px; }
.pm-line { padding: 14px 18px 8px; margin-bottom: 14px; }
.pm-line h3 { margin: 0 0 4px; font-size: 17px; }
.pm-line > p { margin: 0 0 10px; color: var(--muted); font-size: 13.5px; line-height: 1.6; }
.pm-nodes { border-left: 2px solid var(--line-2); margin-left: 34px; }
.pm-node { position: relative; display: grid; grid-template-columns: 1fr; padding: 6px 0 10px 16px; }
.pm-node::before { content: ''; position: absolute; left: -6px; top: 12px; width: 10px; height: 10px; border-radius: 50%; background: var(--panel); border: 2px solid var(--line-2); }
.pm-node.ms::before { background: var(--accent); border-color: var(--accent); }
.pm-node.flash { background: var(--accent-soft); border-radius: 0 8px 8px 0; transition: background .6s; }
.pm-node .y { position: absolute; left: -44px; top: 8px; width: 34px; text-align: right; font-size: 12px; color: var(--muted); font-variant-numeric: tabular-nums; }
.pm-node .t { display: flex; flex-wrap: wrap; gap: 4px 8px; align-items: baseline; }
.pm-node .t a { font-weight: 600; font-size: 14px; color: var(--text); }
.pm-node .t a:hover { color: var(--accent); }
.pm-node .n { font-size: 13.5px; line-height: 1.6; margin-top: 2px; }
.pm-node .s { font-size: 12.5px; color: var(--muted); margin-top: 1px; }
.pm-role { font-size: 11.5px; border-radius: 5px; padding: 1px 7px; background: var(--line); color: var(--text); white-space: nowrap; }
.pm-role.ms { background: var(--accent); color: #fff; }
.pm-role.rel { background: none; border: 1px dashed var(--line-2); color: var(--muted); }
.pm-c { font-size: 12px; color: var(--muted); white-space: nowrap; font-variant-numeric: tabular-nums; }
.pm-tag { font-size: 11.5px; color: var(--muted); border: 1px solid var(--line); border-radius: 999px; padding: 0 7px; white-space: nowrap; }
.pm-open { margin: 4px 0 0; padding-left: 20px; } .pm-open li { margin: 4px 0; }
@media (max-width: 640px) { .pm-lane, .pm-axis { grid-template-columns: 84px 1fr; min-width: 0; } .pm-lane > a { font-size: 11.5px; } .pm-nodes { margin-left: 8px; } .pm-node .y { position: static; width: auto; text-align: left; } }
`;
let cssDone = false;
const css = () => { if (cssDone) return; cssDone = true; document.head.append(Object.assign(document.createElement('style'), { textContent: CSS })); };

const enc = encodeURIComponent;
const pLink = (topic) => '#kb/papers/' + enc(topic);
const TIERS = [['classic', '经典'], ['old', '5 年以上'], ['mid', '2–5 年'], ['young', '半年–2 年'], ['recent', '近半年']];
const MS = new Set(['起点', '里程碑']);
const fmt = (n) => Number(n || 0).toLocaleString();
const ago = (s) => (s || '').slice(5, 16).replace('T', ' ');

export async function papersTab(body, ctx, topic = '') {
  css();
  const { api, h, ui, toast } = ctx;
  const ov = await api.get('/api/kb/papers');
  const input = h('input', { placeholder: '输入一个研究主题，比如：后训练、检索增强生成、混合专家 MoE、推理模型的强化学习', value: topic });
  const btn = h('button', { onclick: () => go(input.value) }, '梳理脉络');
  input.addEventListener('keydown', (e) => { if (e.key === 'Enter') go(input.value); });
  const tiers = TIERS.filter(([k]) => ov.tiers[k]).map(([k, n]) => `${n} ${fmt(ov.tiers[k])}`).join(' · ');
  const note = h('div.muted', {}, ov.total
    ? `论文库 ${fmt(ov.total)} 篇（${tiers}），越老的论文门槛越高，近期论文过 Jev 筛水文；已标注 ${fmt(ov.labeled)} 篇。新主题生成一次约 20–60 秒、不到 1 分钱。`
    : '论文库还是空的：先跑采集和标注（scripts/paper_proto collect / judge / label）。');
  const out = h('div');
  body.append(h('div.card.pm-ask', {}, [input, btn, note]), out);

  if (topic) {
    try { show(await api.get('/api/kb/papers/map?topic=' + enc(topic))); } catch { go(topic, false); }
  } else list();

  function list() {
    out.replaceChildren(
      ui.section('已梳理的主题', `${ov.maps.length} 个`),
      ov.maps.length ? h('div.pm-maps', {}, ov.maps.map((m) => h('a', { href: pLink(m.topic) }, [
        h('b', {}, m.topic), h('small', {}, `${m.lines} 条研究线 · ${m.chosen} 篇候选 · ${ago(m.created)}`)])))
        : ui.empty('还没有梳理过的主题', '在上面输入一个主题试试'),
    );
  }

  async function go(t, force = false) {
    t = (t || '').trim();
    if (!t) return;
    if (decodeURIComponent(location.hash) !== '#kb/papers/' + t) { history.replaceState(null, '', pLink(t)); }
    btn.disabled = true;
    out.replaceChildren(ui.empty(`正在梳理「${t}」…`, '改写检索意图 → 召回 → 引用子图选点 → 模型分线，约 20–60 秒'));
    try { show(await api.post('/api/kb/papers/map', { topic: t, force })); } catch (e) { out.replaceChildren(); toast('生成失败：' + e.message, true); }
    btn.disabled = false;
  }

  function show(m) {
    const P = m.papers;
    const nodeEls = {};
    const lineEls = [];
    const paperLink = (s) => { const p = P[s] || {}; return h('a', { href: p.url, target: '_blank', rel: 'noopener', title: p.s || '' }, p.title || s); };
    const node = (n) => {
      const p = P[n.s2id] || {};
      const ms = MS.has(n.role);
      const el = h('div.pm-node' + (ms ? '.ms' : ''), {}, [
        h('span.y', {}, p.year || ''),
        h('div.t', {}, [h('span.pm-role' + (ms ? '.ms' : n.role === '相关' ? '.rel' : ''), {}, n.role || '—'), paperLink(n.s2id),
          h('span.pm-c', {}, `被引 ${fmt(p.cites)}`), p.kind ? h('span.pm-tag', {}, p.kind) : null]),
        n.note ? h('div.n', {}, n.note) : null,
        !n.note && p.s ? h('div.s', {}, p.s) : null,
      ]);
      (nodeEls[n.s2id] ||= el);
      return el;
    };
    const lines = m.lines.map((ln, i) => {
      const el = h('div.card.pm-line', { id: 'pm-l' + i }, [h('h3', {}, ln.name), ln.summary ? h('p', {}, ln.summary) : null,
        h('div.pm-nodes', {}, ln.nodes.map(node))]);
      lineEls.push(el);
      return el;
    });
    const jump = (s) => {
      const el = nodeEls[s];
      if (!el) return;
      el.scrollIntoView({ behavior: 'smooth', block: 'center' });
      el.classList.add('flash');
      setTimeout(() => el.classList.remove('flash'), 1400);
    };
    out.replaceChildren(
      h('div.pm-meta', {}, [
        h('a', { href: '#kb/papers' }, '← 全部主题'),
        h('span', {}, `召回 ${fmt(m.recalled)} 篇 → 子图 ${fmt(m.core)} 篇 → 选 ${m.chosen} 篇成 ${m.lines.length} 条线`),
        h('span', {}, `生成于 ${ago(m.created)} · $${m.cost}`),
        h('span.grow'),
        h('button.outline', { onclick: () => go(m.topic, true) }, '重新生成'),
      ]),
      m.overview ? h('div.pm-ov', {}, m.overview) : null,
      lanes(h, m, jump),
      m.foundations.length ? ui.section('前置基础', '这些不在主题里，但主题内的论文大量引用') : null,
      m.foundations.length ? h('div.pm-found', {}, m.foundations.map((s) => h('a', { href: P[s]?.url, target: '_blank', rel: 'noopener' }, [
        P[s]?.title || s, h('small', {}, `${P[s]?.year || ''} · 被引 ${fmt(P[s]?.cites)}${P[s]?.s ? ' · ' + P[s].s : ''}`)]))) : null,
      ui.section('研究线', `${m.lines.length} 条 · 每条按年份排；实心点 = 起点 / 里程碑`),
      ...lines,
      m.surveys.length ? ui.section('推荐综述') : null,
      m.surveys.length ? h('div.pm-found', {}, m.surveys.map((s) => h('a', { href: P[s]?.url, target: '_blank', rel: 'noopener' }, [
        P[s]?.title || s, h('small', {}, `${P[s]?.year || ''} · 被引 ${fmt(P[s]?.cites)}`)]))) : null,
      m.open.length ? ui.section('仍未解决') : null,
      m.open.length ? h('div.card', { style: { padding: '12px 16px' } }, h('ul.pm-open', {}, m.open.map((o) => h('li', {}, o)))) : null,
    );
  }
}

// 总览：每条线一行，论文按年份落点（有论文的年份等宽排开，近几年论文多也不挤），同年多篇横向错开；点一下跳到那篇
function lanes(h, m, jump) {
  const ys = [...new Set(m.lines.flatMap((ln) => ln.nodes.map((n) => m.papers[n.s2id]?.year).filter(Boolean)))].sort();
  if (!ys.length) return null;
  const col = 100 / ys.length;
  const x = (y, k = 0, n = 1) => `${col * ys.indexOf(y) + col * (k + 1) / (n + 1)}%`;
  return h('div.card.pm-lanes', {}, [
    ...m.lines.map((ln, i) => {
      const per = {};
      ln.nodes.forEach((n) => { const y = m.papers[n.s2id]?.year; if (y) per[y] = (per[y] || 0) + 1; });
      const seen = {};
      return h('div.pm-lane', {}, [
        h('a', { href: '#', title: ln.summary, onclick: (e) => { e.preventDefault(); document.getElementById('pm-l' + i)?.scrollIntoView({ behavior: 'smooth' }); } }, ln.name),
        h('div.pm-track', {}, ln.nodes.map((n) => {
          const p = m.papers[n.s2id];
          if (!p?.year) return null;
          const k = (seen[p.year] = (seen[p.year] || 0) + 1) - 1;
          return h('span.pm-dot' + (MS.has(n.role) ? '.ms' : ''), {
            title: `${p.year} · ${n.role} · ${p.title}`, onclick: () => jump(n.s2id), style: { left: x(p.year, k, per[p.year]) },
          });
        })),
      ]);
    }),
    h('div.pm-axis', {}, [h('i'), h('div', {}, ys.map((y, j) => h('span', { style: { left: `${col * (j + 0.5)}%` } }, ys.length > 7 ? `’${String(y).slice(2)}` : y)))]),
  ]);
}
