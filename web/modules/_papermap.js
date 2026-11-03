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
.pm-rd { font-size: 11.5px; border-radius: 5px; padding: 0 7px; white-space: nowrap; border: 1px solid var(--line-2); color: var(--muted); background: none; cursor: pointer; font-family: inherit; line-height: 18px; }
.pm-rd:hover { color: var(--accent); border-color: var(--accent); text-decoration: none; }
.pm-rd.done { border-color: var(--accent); color: var(--accent); }
.pm-rd.run { border-style: dashed; }
.pm-lh { display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; } .pm-lh h3 { flex: 1; }
.pm-batch { border: 1px solid var(--line); border-radius: var(--radius-sm); background: var(--focus); padding: 10px 14px; margin: 0 0 12px; font-size: 13px; }
.pm-batch label { display: flex; gap: 8px; align-items: baseline; padding: 2px 0; }
.pm-batch label.off { color: var(--muted); }
.pm-batch .act { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-top: 8px; }
.pm-found > div { padding: 8px 12px; border: 1px solid var(--line); border-radius: var(--radius-sm); background: var(--panel); font-size: 13px; }
.pm-found > div > a { color: var(--text); } .pm-found > div > a:hover { color: var(--accent); }
.pm-found > div .pm-rd { margin-left: 6px; }
.pm-add { padding: 12px 16px; margin-bottom: 14px; }
.pm-add .row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.pm-add input { flex: 1; min-width: 200px; font: inherit; padding: 6px 10px; border: 1px solid var(--line-2); border-radius: 8px; background: var(--panel); color: var(--text); }
.pm-add .muted { font-size: 12.5px; margin-top: 6px; }
.pm-add ol { margin: 8px 0 4px; padding-left: 22px; font-size: 13px; max-height: 320px; overflow: auto; } .pm-add li { margin: 2px 0; }
.pm-add .act { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-top: 8px; font-size: 13px; }
.pm-new { color: var(--accent); font-size: 12px; display: block; margin-top: 2px; }
.pm-mt { width: 100%; font-size: 12px; color: var(--muted); display: flex; gap: 4px 12px; flex-wrap: wrap; align-items: center; }
.pm-mt .bad { color: var(--err); }
.pm-mt button { font-size: 12px; padding: 1px 8px; }
.pm-thin { border: 1px dashed var(--line-2); border-radius: var(--radius-sm); padding: 8px 12px; margin: 0 0 12px; font-size: 13px; display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
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
const READ_MAX = 10;        // 和后端 PAPER_READ_MAX 一致：一次最多新开几篇深读
const RUNNING = new Set(['queued', 'running']);

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
  const adder = addPanel(ctx, (t) => go(t, false));
  body.append(h('div.card.pm-ask', {}, [input, btn, note, ov.total ? maintLine(ctx, ov.maintain) : null]), adder.el, out);

  if (topic) {
    try { show(await api.get('/api/kb/papers/map?topic=' + enc(topic))); } catch { go(topic, false); }
  } else list();

  function list() {
    out.replaceChildren(
      ui.section('已梳理的主题', `${ov.maps.length} 个`),
      ov.maps.length ? h('div.pm-maps', {}, ov.maps.map((m) => h('a', { href: pLink(m.topic) }, [
        h('b', {}, m.topic), h('small', {}, `${m.lines} 条研究线 · ${m.chosen} 篇候选 · ${ago(m.created)}`),
        m.new ? h('span.pm-new', {}, `自生成后相关论文多了 ${m.new} 篇（新入库或重新标注），可重新生成`) : null])))
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
    const badges = {};          // s2id → 页面上它的深读标记（同一篇可能出现在几处），轮询时原地更新
    let timer = 0;
    // 深读标记：已有条目 → 打开（跑完的看笔记 / 追问，没跑完的看进度）；没有 → 点一下新建并跳过去
    const badge = (s) => {
      const r = P[s]?.read;
      const el = r ? h('a.pm-rd' + (RUNNING.has(r.status) ? '.run' : '.done'), { href: `#learn/item/${r.id}`, title: '在深度学习板块打开：笔记、练习题、追问讨论' },
        RUNNING.has(r.status) ? '深读中' : '已深读')
        : P[s]?.url?.includes('arxiv.org') ? h('button.pm-rd', { title: '送去深度学习板块深读（本机 Claude Code，约十几分钟）', onclick: async (e) => {
          e.target.disabled = true;
          try { const r = await api.post('/api/kb/papers/read', { s2ids: [s] }); const it = [...r.new, ...r.reuse][0]; if (it) location.hash = `#learn/item/${it.id}`; }
          catch (err) { toast('开始深读失败：' + err.message, true); e.target.disabled = false; }
        } }, '深读') : null;
      (badges[s] ||= []).push(el);
      return el;
    };
    const refresh = (got) => {
      for (const [s, els] of Object.entries(badges)) {
        if (!got[s]) continue;
        P[s].read = got[s].read;
        badges[s] = [];
        els.forEach((el) => el?.replaceWith(badge(s) || ''));
      }
    };
    const poll = () => {
      clearTimeout(timer);
      if (!Object.values(P).some((p) => RUNNING.has(p.read?.status))) return;
      timer = setTimeout(async () => {
        if (!out.isConnected || decodeURIComponent(location.hash) !== '#kb/papers/' + m.topic) return;
        try { refresh((await api.get('/api/kb/papers/map?topic=' + enc(m.topic))).papers); } catch { /* 下一轮再试 */ }
        poll();
      }, 30000);
    };
    // 一组论文一起深读：先列出哪些复用、哪些新跑，按被引多少默认勾前 READ_MAX 篇，确认后才建任务
    const batch = (ids, host) => async (e) => {
      const btnEl = e.target;
      if (host.firstChild?.classList?.contains('pm-batch')) { host.firstChild.remove(); return; }
      btnEl.disabled = true;
      let r;
      try { r = await api.post('/api/kb/papers/read', { s2ids: ids, dry_run: true }); } catch (err) { toast(err.message, true); btnEl.disabled = false; return; }
      btnEl.disabled = false;
      const order = [...r.new].sort((a, b) => (P[b]?.cites || 0) - (P[a]?.cites || 0));
      const pick = new Set(order.slice(0, READ_MAX));
      const boxes = {};
      const go = h('button', {}, '');
      const sum = h('span.muted');
      const upd = () => {
        const n = pick.size;
        go.textContent = n ? `开始深读 ${n} 篇` : '没有要新跑的';
        go.disabled = !n;
        sum.textContent = `复用已有深读 ${r.reuse.length} 篇 · 新跑 ${n} 篇（每篇十几分钟，最多 3 篇同时跑，约 ${Math.ceil(n / 3) * 15} 分钟）${r.skip.length ? ` · ${r.skip.length} 篇没有 arXiv 链接，跳过` : ''}`;
        for (const s of order) { const c = boxes[s]; c.disabled = !pick.has(s) && n >= READ_MAX; c.parentNode.classList.toggle('off', !pick.has(s)); }
      };
      const row = (s, tag, input) => h('label', {}, [input, h('span', {}, [P[s]?.title || s, h('span.pm-c', {}, ` ${P[s]?.year || ''} · 被引 ${fmt(P[s]?.cites)}`)]), tag ? h('span.pm-tag', {}, tag) : null]);
      const panel = h('div.pm-batch', {}, [
        h('div', {}, `一次最多新开 ${READ_MAX} 篇，默认勾被引最多的；已深读过的直接复用，不重跑。`),
        ...r.reuse.map((x) => row(x.s2id, RUNNING.has(x.status) ? '深读中' : '复用', h('input', { type: 'checkbox', checked: true, disabled: true }))),
        ...order.map((s) => row(s, '', boxes[s] = h('input', { type: 'checkbox', checked: pick.has(s), onchange: (ev) => { ev.target.checked ? pick.add(s) : pick.delete(s); upd(); } }))),
        h('div.act', {}, [go, h('button.ghost', { onclick: () => panel.remove() }, '取消'), sum]),
      ]);
      go.onclick = async () => {
        go.disabled = true;
        try {
          const res = await api.post('/api/kb/papers/read', { s2ids: [...pick] });
          const got = {};
          for (const x of [...res.new, ...res.reuse]) got[x.s2id] = { read: { id: x.id, status: x.status } };
          refresh(got);
          panel.remove();
          toast(`已排进深度学习：新开 ${res.new.length} 篇，跑完的点「已深读」看笔记和追问`);
          poll();
        } catch (err) { toast('开始深读失败：' + err.message, true); go.disabled = false; }
      };
      upd();
      host.prepend(panel);
    };
    const batchBtn = (ids, host) => h('button.outline.sm', { onclick: batch(ids, host) }, '整组深读');
    const paperLink = (s) => { const p = P[s] || {}; return h('a', { href: p.url, target: '_blank', rel: 'noopener', title: p.s || '' }, p.title || s); };
    const node = (n) => {
      const p = P[n.s2id] || {};
      const ms = MS.has(n.role);
      const el = h('div.pm-node' + (ms ? '.ms' : ''), {}, [
        h('span.y', {}, p.year || ''),
        h('div.t', {}, [h('span.pm-role' + (ms ? '.ms' : n.role === '相关' ? '.rel' : ''), {}, n.role || '—'), paperLink(n.s2id),
          h('span.pm-c', {}, `被引 ${fmt(p.cites)}`), p.kind ? h('span.pm-tag', {}, p.kind) : null, badge(n.s2id)]),
        n.note ? h('div.n', {}, n.note) : null,
        !n.note && p.s ? h('div.s', {}, p.s) : null,
      ]);
      (nodeEls[n.s2id] ||= el);
      return el;
    };
    const lines = m.lines.map((ln, i) => {
      const host = h('div');
      const el = h('div.card.pm-line', { id: 'pm-l' + i }, [
        h('div.pm-lh', {}, [h('h3', {}, ln.name), h('button.outline.sm', { onclick: batch(ln.nodes.map((n) => n.s2id), host) }, '整条线深读')]),
        ln.summary ? h('p', {}, ln.summary) : null, host,
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
    // 前置基础 / 推荐综述：卡片列表，每篇可单独深读，标题栏可整组深读
    function group(title, sub, ids, more) {
      if (!ids.length) return [];
      const host = h('div');
      return [ui.section(title, h('span', {}, [sub, sub ? ' ' : '', batchBtn(ids, host)])), host,
        h('div.pm-found', {}, ids.map((s) => h('div', {}, [h('a', { href: P[s]?.url, target: '_blank', rel: 'noopener' }, P[s]?.title || s), badge(s),
          h('small', {}, `${P[s]?.year || ''} · 被引 ${fmt(P[s]?.cites)}${more(s)}`)])))];
    }
    poll();
    out.replaceChildren(
      h('div.pm-meta', {}, [
        h('a', { href: '#kb/papers' }, '← 全部主题'),
        h('span', {}, `召回 ${fmt(m.recalled)} 篇 → 子图 ${fmt(m.core)} 篇 → 选 ${m.chosen} 篇成 ${m.lines.length} 条线`),
        h('span', {}, `生成于 ${ago(m.created)} · $${m.cost}`),
        h('span.grow'),
        m.new ? h('span.pm-new', {}, `自生成后相关论文多了 ${m.new} 篇（新入库或重新标注）`) : null,
        h('button.outline', { onclick: () => go(m.topic, true) }, '重新生成'),
      ]),
      m.thin ? h('div.pm-thin', {}, [h('span', {}, `库里和「${m.topic}」相关的论文只召回到 ${m.recalled} 篇，脉络可能不全。`),
        h('button.outline', { onclick: () => adder.topic(m.topic) }, '补充这个方向')]) : null,
      m.overview ? h('div.pm-ov', {}, m.overview) : null,
      lanes(h, m, jump),
      ...group('前置基础', '这些不在主题里，但主题内的论文大量引用', m.foundations, (s) => P[s]?.s ? ' · ' + P[s].s : ''),
      ui.section('研究线', `${m.lines.length} 条 · 每条按年份排；实心点 = 起点 / 里程碑`),
      ...lines,
      ...group('推荐综述', '', m.surveys, () => ''),
      m.open.length ? ui.section('仍未解决') : null,
      m.open.length ? h('div.card', { style: { padding: '12px 16px' } }, h('ul.pm-open', {}, m.open.map((o) => h('li', {}, o)))) : null,
    );
  }
}

// 维护状态：每日热门入库 / 每周维护（刷新被引、重判门槛、补标注）各自最近一次；同一种连续失败两次标红
function maintLine(ctx, mt) {
  const { api, h, toast } = ctx;
  const R = (r) => r?.result || {};
  const feed = mt.feed ? `${ago(mt.feed.started)}，新收 ${R(mt.feed).admitted ?? 0} 篇` : '还没跑过（信息推荐刷新后自动跑）';
  const wk = mt.running ? `进行中：${mt.weekly?.step || '准备中'}`
    : mt.weekly ? `${ago(mt.weekly.started)}，刷新被引 ${fmt(R(mt.weekly).checked ?? 0)} 篇${R(mt.weekly).full ? '（每月全量）' : '（接近门槛的）'}，新收 ${R(mt.weekly).admitted ?? 0} 篇，重标 ${R(mt.weekly).relabel ?? 0} 篇`
      : '还没跑过';
  const bad = (k) => (mt[`${k}_alert`] ? '.bad' : '');
  const fail = (r) => (r?.status === 'failed' ? `（失败：${r.step}）` : r?.status === 'partial' ? '（部分出错）' : '');
  const btn = mt.running ? null : h('button.outline', { title: '刷新被引、重判门槛、标注新收和要重标的论文，约几分钟', onclick: async () => {
    btn.disabled = true;
    try { await api.post('/api/kb/papers/maintain', {}); toast('已开始维护，几分钟后刷新看结果'); } catch (e) { toast('启动失败：' + e.message, true); btn.disabled = false; }
  } }, '立即维护');
  return h('div.pm-mt', {}, [
    h('span' + bad('feed'), { title: mt.feed?.step || '' }, `每日热门入库：${feed}${fail(mt.feed)}`),
    h('span' + bad('weekly'), {}, `每周维护：${wk}${mt.running ? '' : fail(mt.weekly)}`),
    btn,
  ]);
}

// 补充论文：补一篇具体论文（直接入库并标注），或补一个方向（先预览「将新增 N 篇」，确认后后台入库、标注、重新生成脉络）
function addPanel(ctx, openMap) {
  const { api, h, toast } = ctx;
  const input = h('input', { placeholder: 'arXiv 编号 / 链接 / 论文标题，或者一个方向（如：生成式推荐）' });
  const one = h('button.outline', { onclick: () => paper() }, '加这篇论文');
  const dir = h('button.outline', { onclick: () => topic(input.value) }, '补这个方向');
  const res = h('div');
  const el = h('div.card.pm-add', {}, [h('div.row', {}, [h('b', {}, '补充论文'), input, one, dir]),
    h('div.muted', {}, '具体论文不看被引门槛直接入库，约 10–40 秒；方向按正常门槛检索，先给你看会新增哪些，确认后在后台入库。'), res]);
  const busy = (b) => { one.disabled = dir.disabled = b; };
  const pl = (p) => h('a', { href: p.arxiv ? `https://arxiv.org/abs/${p.arxiv}` : `https://www.semanticscholar.org/paper/${p.s2id}`, target: '_blank', rel: 'noopener' }, p.title);

  async function paper() {
    const t = input.value.trim();
    if (!t) return;
    busy(true);
    res.replaceChildren(h('div.muted', {}, `正在查找「${t}」并标注…`));
    try {
      const r = await api.post('/api/kb/papers/add', { text: t });
      const p = r.paper;
      res.replaceChildren(h('div.act', {}, [h('span', {}, r.already ? '已经在库里：' : '已入库：'), pl(p),
        h('span.pm-c', {}, `${p.year || ''} · 被引 ${fmt(p.cites)}${p.domain ? ' · ' + p.domain : ''}`),
        p.s ? h('div.muted', { style: { width: '100%' } }, p.s) : h('div.muted', { style: { width: '100%' } }, '标注没成功，下次全量标注会补上')]));
    } catch (e) { res.replaceChildren(); toast('补充失败：' + e.message, true); }
    busy(false);
  }

  async function topic(t) {
    t = (t || '').trim();
    if (!t) return;
    input.value = t;
    el.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    busy(true);
    res.replaceChildren(h('div.muted', {}, `正在检索「${t}」：改写成英文说法 → Semantic Scholar 按年龄段检索 → 按门槛预判，约 20–40 秒…`));
    try { preview(await api.post('/api/kb/papers/topic/preview', { topic: t })); } catch (e) { res.replaceChildren(); toast('检索失败：' + e.message, true); }
    busy(false);
  }

  function preview(a) {
    const go = h('button', { onclick: async () => {
      go.disabled = true;
      try { poll(await api.post(`/api/kb/papers/topic/${a.id}/start`, {})); } catch (e) { go.disabled = false; toast(e.message, true); }
    } }, `确认入库（${a.n_new + a.n_maybe} 篇候选）`);
    res.replaceChildren(
      h('div.act', {}, [h('span', {}, `「${a.topic}」将新增 ${fmt(a.n_new)} 篇` + (a.n_maybe ? `，另有 ${fmt(a.n_maybe)} 篇被引够工业界门槛、取摘要后再判` : '') + `；库里已有 ${fmt(a.have)} 篇。`),
        a.n_new + a.n_maybe ? go : null, h('button.outline', { onclick: () => res.replaceChildren() }, '取消')]),
      a.new.length ? h('ol', {}, a.new.map((p) => h('li', {}, [pl(p), h('span.pm-c', {}, ` ${p.year || ''} · 被引 ${fmt(p.cites)}`)]))) : null,
      a.n_new > a.new.length ? h('div.muted', {}, `只列了被引最高的 ${a.new.length} 篇`) : null,
      h('div.muted', {}, `检索式：${a.query}`));
  }

  async function poll(a) {
    const done = a.status === 'done', bad = a.status === 'failed', r = a.result || {};
    res.replaceChildren(h('div.act', {}, done
      ? [h('span', {}, `「${a.topic}」补充完成：入库 ${fmt(r.admitted)} 篇，标注 ${fmt(r.labeled)} 篇，花费 $${r.cost ?? 0}。`),
        r.map ? h('button', { onclick: () => openMap(a.topic) }, '看脉络') : h('span.muted', {}, '脉络没生成成功：' + (r.map_error || ''))]
      : [h('span', {}, `「${a.topic}」${bad ? '' : '补充中：'}${a.step}`)]));
    if (!done && !bad) setTimeout(async () => { if (el.isConnected) poll(await api.get(`/api/kb/papers/topic/${a.id}`)); }, 3000);
  }

  return { el, topic };
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
