// HN 吸收：过去一段时间 HN 上 AI 相关的讨论压成话题。每个话题给一句话结论、阵营（人数 + 逐字原话）、做过的人和被推荐的资源；另有资源、经验两个跨话题视图。键盘 j/k 逐张、1–4 表态。
const CSS = `
.hn-kind { background: var(--bg-2); color: var(--accent); }
.hn-cs0 { background: var(--ok-soft); color: var(--ok); } .hn-cs1 { background: var(--err-soft); color: var(--err); } .hn-cs2 { background: var(--bg-2); color: var(--muted); }
.hn-t { border-top: 1px solid var(--line); padding: 12px 0 12px 8px; margin-left: -8px; border-left: 3px solid transparent; }
.hn-t.cur { border-left-color: var(--accent); background: var(--bg); }
.hn-t h3 { font: 700 16px/1.5 var(--serif); margin: 0 0 3px; cursor: pointer; }
.hn-t h3 .ab-tg { display: inline-block; padding: 0 7px; margin-right: 5px; vertical-align: 2px; }
.hn-v { font-size: 14px; margin: 6px 0; } .hn-v a { cursor: pointer; font-size: 11.5px; }
.hn-camp { display: flex; height: 9px; border-radius: 4px; overflow: hidden; gap: 2px; margin: 8px 0 4px; } .hn-camp i { display: block; min-width: 4px; }
.hn-c0 { background: var(--ok); } .hn-c1 { background: var(--err); } .hn-c2 { background: var(--warn); } .hn-c3 { background: var(--line-2); } .hn-c4 { background: var(--accent); opacity: .5; }
.hn-cp { font-size: 13px; margin: 5px 0; padding-left: 9px; border-left: 3px solid var(--line-2); }
.hn-cp b { font-weight: 600; } .hn-cp q { display: block; color: var(--muted); font-size: 12.5px; quotes: "“" "”"; margin-top: 1px; overflow-wrap: anywhere; }
.hn-cp .n { color: var(--muted); font-size: 12px; margin-left: 6px; }
.hn-ex { font-size: 13px; margin: 4px 0; } .hn-ex .o { font-size: 11px; font-weight: 700; border-radius: 4px; padding: 0 5px; margin-right: 5px; white-space: nowrap; }
.hn-o0 { background: var(--ok-soft); color: var(--ok); } .hn-o1 { background: var(--err-soft); color: var(--err); } .hn-o2 { background: var(--warn-soft); color: var(--warn); }
.hn-ex q { color: var(--muted); font-size: 12.5px; quotes: "“" "”"; display: block; overflow-wrap: anywhere; }
.hn-chips { display: flex; gap: 5px; flex-wrap: wrap; margin: 6px 0; font-size: 12px; align-items: center; }
.hn-chips a, .hn-chips span.c { border: 1px solid var(--line); border-radius: 999px; padding: 0 9px; color: var(--muted); text-decoration: none; max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.hn-chips a:hover { border-color: var(--accent); color: var(--accent); }
.hn-chips .mine { background: var(--err-soft); color: var(--err); border-color: transparent; } .hn-chips .mine.ok { background: var(--ok-soft); color: var(--ok); }
.hn-act { display: flex; gap: 5px; flex-wrap: wrap; margin-top: 7px; align-items: center; }
.hn-act button { border: 1px solid var(--line); background: var(--panel); color: var(--text); border-radius: 999px; padding: 1px 10px; font-size: 12px; cursor: pointer; }
.hn-act button.on { background: var(--accent); border-color: var(--accent); color: #fff; } .hn-act .sp { color: var(--line-2); }
.hn-d { display: none; margin-top: 8px; font-size: 13px; } .hn-t.open .hn-d { display: block; } .hn-d h5 { margin: 9px 0 3px; font-size: 12px; color: var(--muted); font-weight: 600; }
.hn-d .p { padding: 1px 0; overflow-wrap: anywhere; }
.hn-r { border-top: 1px solid var(--line); padding: 8px 0; } .hn-r .t { font-weight: 600; font-size: 14.5px; overflow-wrap: anywhere; } .hn-r .w { font-size: 13px; color: var(--muted); }
.hn-r .k { font-size: 11px; font-weight: 700; border-radius: 4px; padding: 0 6px; background: var(--bg-2); color: var(--accent); margin-right: 6px; white-space: nowrap; }
.hn-tail li { margin: 2px 0; overflow-wrap: anywhere; }
@media (max-width: 720px) { .hn-t h3 { font-size: 15px; } }
`;
const E = (s) => (s == null ? '' : String(s)).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const N = (n) => (n || 0).toLocaleString();
const ACT = ['没增量', '有收获', '很受用', '会用上'];
const STANCE = ['站主流', '站反对', '先不站'];
const CS = { 基本共识: 'hn-cs0', 有分歧: 'hn-cs1', 讨论少: 'hn-cs2' };
const OC = { 成功: 'hn-o0', 失败: 'hn-o1', 有条件: 'hn-o2' };
const KIND = { 产品: '产品', 仓库: '仓库', 数据: '数据', 视频: '视频', 论文: '论文', 文档: '文档', 博客: '博客', 讨论: '讨论', 其他: '其他' };
const RK = [['all', '全部'], ['产品', '产品'], ['仓库', '仓库'], ['数据', '数据'], ['视频', '视频'], ['论文', '论文'], ['文档', '文档 / 博客']];
const hnc = (id) => `https://news.ycombinator.com/item?id=${id}`;
const link = (u, t) => (/^https?:/.test(u) ? `<a href="${E(u)}" target="_blank" rel="noopener">${E(t)}</a>` : E(t));

function camps(t) {
  return `<div class="hn-camp">${t.camps.map((c, i) => `<i class="hn-c${Math.min(i, 4)}" style="flex:${c.n}" title="${E(c.claim)}"></i>`).join('')}</div>
<div class="ab-m">${t.camps.map((c, i) => `<span>${i + 1}. ${E(c.claim)} <b>${c.n}</b></span>`).join(' · ')}</div>`;
}

function quote(c, withClaim = true) {
  return `<div class="hn-cp">${withClaim ? `<b>${E(c.side)}：${E(c.claim)}</b><span class="n">约 ${c.n} 条评论持此观点</span>` : ''}<q>${E(c.quote)}</q><a class="ab-m" href="${hnc(c.cid)}" target="_blank" rel="noopener">@${E(c.by)} · 看原评论</a></div>`;
}

function exps(list, n) {
  return list.slice(0, n).map((x) => `<div class="hn-ex"><span class="o ${OC[x.outcome]}">${x.outcome}</span>${E(x.who)}：${E(x.did)}${x.result ? `，结果：${E(x.result)}` : ''}<q>${E(x.quote)}</q><a class="ab-m" href="${hnc(x.cids[0])}" target="_blank" rel="noopener">@${E(x.by)} · 看原评论</a></div>`).join('');
}

function topic(t, R, D) {
  const r = R[t.id] || {};
  const res = t.res.map((k) => D.resources[k]);
  return `<div class="hn-t" data-t="${t.id}"><h3><span class="ab-tg hn-kind">${t.kind}</span><span class="ab-tg ${CS[t.consensus]}">${t.consensus}</span>${E(t.title)}</h3>
<div class="ab-m">${t.stats.posts} 帖 · ${N(t.stats.comments)} 评论 · ${N(t.stats.people)} 位评论者被引用 · 最高 ${N(Math.max(...t.posts.map((p) => p.points)))} 分</div>
${t.verdict ? `<div class="hn-v"><b>一句话：</b>${E(t.verdict).replace(/\[(\d+)\]/g, (m, n) => `<a data-c="${n}">[${n}]</a>`)}</div>` : '<div class="hn-v ab-m">这个话题的结论没通过引用检查，已隐藏；看下面各阵营。</div>'}
${t.camps.length ? camps(t) : ''}
${t.camps.slice(0, 2).map((c) => quote(c)).join('')}
${t.exps.length ? `<div class="hn-chips ab-m">做过的人 ${t.exps.length}：${['成功', '失败', '有条件'].map((o) => `${o} ${t.exps.filter((x) => x.outcome === o).length}`).join(' · ')}</div>${exps(t.exps, 2)}` : ''}
${t.mine.length ? `<div class="hn-chips">${t.mine.map((m) => `<span class="c mine ${m.rel === '印证' ? 'ok' : ''}" title="${E(m.why)}">与你的判断${m.rel}：${E(m.judgment)}</span>`).join('')}</div>` : ''}
${res.length ? `<div class="hn-chips"><span class="ab-m">资源 ${t.res.length}</span>${res.map((x) => `<a href="${E(x.url)}" target="_blank" rel="noopener" title="${E(x.why)}">${E(KIND[x.kind] || x.kind)} · ${E(x.title)}</a>`).join('')}</div>` : ''}
<div class="hn-act">${ACT.map((a, i) => `<button data-a="${a}" title="键盘 ${i + 1}" class="${r.act === a ? 'on' : ''}">${a}</button>`).join('')}<span class="sp">｜</span>${STANCE.map((a) => `<button data-s="${a}" class="${r.stance === a ? 'on' : ''}">${a}</button>`).join('')}</div>
<div class="hn-d"></div></div>`;
}

function detail(t) {
  return `<h5>各阵营和原话（${t.camps.length}）</h5>${t.camps.map((c) => quote(c)).join('')}
${t.exps.length ? `<h5>做过的人（${t.exps.length}）</h5>${exps(t.exps, 99)}` : ''}
<h5>讨论的帖子（${t.posts.length}）</h5>${t.posts.map((p) => `<div class="p">${link(p.url, p.title)} <span class="ab-m">· ${N(p.points)} 分 · <a href="${E(p.hn_url)}" target="_blank" rel="noopener">${N(p.comments)} 评论</a></span></div>`).join('')}`;
}

function how(D) {
  const M = D.meta, F = M.fails || {};
  return `<div class="ab-fun">${[[M.queried, '搜到的 AI 相关帖'], [M.collected, `达到门槛（≥${M.weights.min_points} 分或≥${M.weights.min_comments} 评论）`], [M.ai + M.edge, '判为 AI 相关'], [M.digested, `评论≥${M.weights.digest_min}，已提炼`], [N(M.comments), '条评论已读']].map((x) => `<div><b>${typeof x[0] === 'number' ? N(x[0]) : x[0]}</b><span>${x[1]}</span></div>`).join('')}
<div class="hl"><b>${M.topics}</b><span>个话题（覆盖 ${M.in_topics} 帖）</span></div><div><b>${M.tail}</b><span>帖在长尾</span></div><div><b>${M.resources}</b><span>个被推荐的资源</span></div><div><b>${M.exps}</b><span>条做过的经验</span></div><div><b>${M.quotes_kept}/${M.quotes_raw}</b><span>观点和经验的原话通过核对</span></div></div>
<div class="ab-q"><h2>这页是怎么算出来的</h2>
<p><b>采集：</b>${E(M.start)} 至 ${E(M.end)}（UTC），HN 搜索接口按 18 个 AI 相关词取帖，保留 ≥${M.weights.min_points} 分或 ≥${M.weights.min_comments} 条评论的，Show / Launch HN 评论 ≥10 也收；模型按标题判是否主要在讨论 AI，“边缘”也保留（${M.edge} 帖）。</p>
<p><b>提炼：</b>评论 ≥${M.weights.digest_min} 条的帖子逐帖读评论区（最多 8 万字符，按 HN 自己的排序取靠前的讨论串），抽观点、亲身经验、推荐链接。每条观点和经验必须带一句评论原文，程序在评论里逐字核对，找不到的丢弃（${M.quotes_raw - M.quotes_kept} 条被丢）；链接必须在评论里真出现过。</p>
<p><b>话题：</b>模型看每帖的标题、讨论一句话和主要对象，聚成 ${M.topics} 个话题，不适合并入的放长尾。再对每个话题逐个综合：观点按立场并成阵营，阵营人数是持该观点的评论数相加（HN 不公开评论得分，这是近似，只说明谁说得多，不说明谁说得对）。一句话结论每句要带阵营序号，没带的隐藏（${M.unchecked} 个话题被隐藏）。</p>
<p><b>共识度：</b>评论总数 &lt;80 为“讨论少”；最大阵营占比 ≥60% 为“基本共识”；其余且第二大阵营 ≥25% 为“有分歧”。</p>
<p><b>资源：</b>按网址去重，“被几位评论者提到”是不同评论者数；帖子作者自己贴的链接降权。这页没有计算好评占比，也没有核实链接内容。</p>
<p class="ab-m">没做的：与上周话题对照（需要上一周的数据）；原话没有翻译；表态“站某边”只记草稿，不写进你的判断库。HN 评论者偏工程师、偏怀疑，不代表市场上的用户。${F.digest ? `有 ${F.digest} 帖提炼失败已跳过；` : ''}${M.minutes ? `耗时 ${M.minutes} 分钟，` : ''}模型费用（Claude 部分）$${M.cost}，单帖提炼走 DeepSeek 未计入。</p></div>`;
}

function res(D, flt) {
  const L = D.resources.filter((x) => flt === 'all' || x.kind === flt || (flt === '文档' && ['文档', '博客'].includes(x.kind))).filter((x) => x.kind !== '讨论' && x.kind !== '其他' || flt === 'all');
  if (!L.length) return '<div class="ab-m">这个类型下没有资源</div>';
  return L.slice(0, 80).map((x) => `<div class="hn-r"><div class="t"><span class="k">${E(KIND[x.kind] || x.kind)}</span>${link(x.url, x.title)}</div><div class="w">${E(x.why)}</div>
<div class="ab-m">${x.people} 位评论者提到${x.self ? ' · 含作者自荐' : ''} · 来自 <a href="${hnc(x.post)}" target="_blank" rel="noopener">${E(x.post_title)}</a>${x.topics.length ? ' · 话题 ' + x.topics.map((k) => `<a data-tj="${k}">${k + 1}</a>`).join(' ') : ''}</div></div>`).join('') + (L.length > 80 ? `<div class="ab-m">只列前 80 个，共 ${L.length} 个</div>` : '');
}

function expView(D, flt) {
  const L = D.topics.flatMap((t) => t.exps.map((x) => ({ ...x, t }))).filter((x) => flt === 'all' || x.outcome === flt);
  return L.map((x) => `<div class="hn-r"><div class="hn-ex" style="margin:0"><span class="o ${OC[x.outcome]}">${x.outcome}</span>${E(x.who)}：${E(x.did)}${x.result ? `，结果：${E(x.result)}` : ''}<q>${E(x.quote)}</q></div>
<div class="ab-m"><a href="${hnc(x.cids[0])}" target="_blank" rel="noopener">@${E(x.by)} · 原评论</a> · 话题 <a data-tj="${x.t.id}">${E(x.t.title)}</a></div></div>`).join('') || '<div class="ab-m">没有</div>';
}

export async function hnView(el, ctx, rid) {
  const { api, h, ui, toast } = ctx;
  const runs = await api.get('/api/absorb/hn/runs');
  const cur = rid ? decodeURIComponent(rid) : (runs.find((r) => r.done) || runs[0] || {}).id;
  const body = h('div');
  let timer = null;
  const head = h('div.tabs', {}, [
    h('button', { onclick: () => { location.hash = '#absorb'; } }, '选题吸收'), h('button.active', {}, 'HN 吸收'),
    ...runs.map((r) => h('button', { class: r.id === cur ? 'active' : '', style: 'margin-left:8px', onclick: () => { location.hash = '#absorb/hn/' + encodeURIComponent(r.id); } }, r.id.replace('_', ' 至 ') + (r.done ? '' : r.running ? ' · 进行中' : ' · 中断'))),
  ]);
  el.append(h('style', {}, CSS), ui.pageHead('吸收', '过去一周 HN 上 AI 相关的讨论：按话题看社区站哪边、谁做过什么、推荐了什么', []), head, body);
  if (!cur) { body.append(ui.empty('还没有跑过。命令行：python -m app.modules._absorb_hn --start 起 --end 止')); return; }
  const show = async () => {
    if (!el.isConnected) return clearTimeout(timer);
    const r = await api.get('/api/absorb/hn/runs/' + encodeURIComponent(cur));
    if (!r.data) {
      body.innerHTML = `<div class="ab-run"><b>HN ${E(r.start)} 至 ${E(r.end)}</b><div class="ab-prog"><i style="width:${Math.max(2, Math.round((r.step - (r.running ? 0.5 : 0)) / r.steps * 100))}%"></i></div>
<div class="ab-m">${r.running ? `第 ${r.step} / ${r.steps} 步：${E(r.stage_name)} · 已花费 $${r.cost}` : `停在第 ${r.step} / ${r.steps} 步（${E(r.stage_name)}）：${E(r.error)}`}</div></div>`;
      if (r.running) timer = setTimeout(show, 5000);
      else body.append(h('button.primary', { onclick: async () => { await api.post('/api/absorb/hn/runs', { start: r.start, end: r.end }); show(); } }, '接着跑'));
      return;
    }
    paint(r.data, r.reactions);
  };

  const paint = (D, R) => {
    const M = D.meta, byId = Object.fromEntries(D.topics.map((t) => [t.id, t]));
    let view = 'topic', flt = 'all', rflt = 'all', eflt = 'all';
    const done = () => `已表态 ${D.topics.filter((t) => R[t.id] && R[t.id].act).length}/${D.topics.length}`;
    const draw = () => {
      let main;
      if (view === 'topic') {
        const L = D.topics.filter((t) => flt === 'all' || (flt === 'todo' ? !(R[t.id] && R[t.id].act) : t.consensus === flt));
        main = (L.map((t) => topic(t, R, D)).join('') || '<div class="ab-m">这个筛选下没有话题</div>') + (flt === 'all' ? `<details class="ab-fold hn-tail"><summary>长尾：另有 ${M.tail} 帖没并进话题</summary><ul>${D.tail.map((p) => `<li>${link(p.url, p.title)} <span class="ab-m">· <a href="${E(p.hn_url)}" target="_blank" rel="noopener">${N(p.comments)} 评论</a>${p.tldr ? ' · ' + E(p.tldr) : ''}</span></li>`).join('')}</ul></details>` : '');
      } else if (view === 'res') main = `<div class="ab-bar" style="position:static">${RK.map((x) => `<button data-rf="${x[0]}" class="${rflt === x[0] ? 'on' : ''}">${x[1]}</button>`).join('')}</div>` + res(D, rflt);
      else if (view === 'exp') main = `<div class="ab-bar" style="position:static">${['all', '成功', '失败', '有条件'].map((x) => `<button data-ef="${x}" class="${eflt === x ? 'on' : ''}">${x === 'all' ? '全部' : x}</button>`).join('')}</div>` + expView(D, eflt);
      else main = how(D);
      const cs = D.topics.reduce((a, t) => ({ ...a, [t.consensus]: (a[t.consensus] || 0) + 1 }), {});
      body.innerHTML = `<div class="ab-m">${E(M.start)} 至 ${E(M.end)} · 观点和经验的原话已逐字核对，归并和结论由模型完成，未经人工校对</div>
<div class="ab-note">${N(M.collected)} 帖里 ${N(M.ai + M.edge)} 帖与 AI 相关，压成 <b>${M.topics} 个话题</b>（覆盖 ${M.in_topics} 帖），另有 ${M.tail} 帖在长尾。先看<b>有分歧 ${cs['有分歧'] || 0}</b>：社区没谈拢；<b>基本共识 ${cs['基本共识'] || 0}</b> 看一句话结论即可。<span class="ab-key">键盘 <kbd>j</kbd>/<kbd>k</kbd> 逐张 <kbd>1</kbd>–<kbd>4</kbd> 表态 <kbd>o</kbd> 展开</span></div>
<div class="ab-bar">${[['topic', '话题'], ['res', `资源 ${M.resources}`], ['exp', `经验 ${M.exps}`], ['how', '口径']].map((x) => `<button data-v="${x[0]}" class="${view === x[0] ? 'on' : ''}">${x[1]}</button>`).join('')}<span class="ab-sp"></span>
${view === 'topic' ? [['all', '全部'], ['有分歧', '有分歧'], ['基本共识', '基本共识'], ['讨论少', '讨论少'], ['todo', '未表态']].map((x) => `<button data-f="${x[0]}" class="${flt === x[0] ? 'on' : ''}">${x[1]}</button>`).join('') + `<span class="ab-m ab-done">${done()}</span>` : ''}</div><div>${main}</div>`;
    };
    const open = (id, keep) => {
      const c = body.querySelector(`[data-t="${id}"]`);
      if (!c) return;
      if (c.classList.contains('open') && !keep) return c.classList.remove('open');
      c.querySelector('.hn-d').innerHTML = detail(byId[id]);
      c.classList.add('open');
      if (keep) c.scrollIntoView({ block: 'center' });
    };
    const vis = () => [...body.querySelectorAll('.hn-t')].filter((x) => x.offsetParent);
    const focus = (x) => { if (!x) return; body.querySelectorAll('.hn-t.cur').forEach((y) => y.classList.remove('cur')); x.classList.add('cur'); x.scrollIntoView({ block: 'nearest' }); };
    const react = async (c, patch) => {
      const id = c.dataset.t, old = R[id] || {}, nx = { act: old.act || '', stance: old.stance || '', ...patch };
      for (const k of Object.keys(patch)) if (old[k] === patch[k]) nx[k] = '';
      try { await api.post(`/api/absorb/hn/runs/${encodeURIComponent(cur)}/react`, { topic: +id, act: nx.act, stance: nx.stance }); } catch (err) { toast(err.message || '没存上'); return false; }
      if (nx.act || nx.stance) R[id] = nx; else delete R[id];
      c.querySelectorAll('[data-a]').forEach((b) => b.classList.toggle('on', nx.act === b.dataset.a));
      c.querySelectorAll('[data-s]').forEach((b) => b.classList.toggle('on', nx.stance === b.dataset.s));
      const d = body.querySelector('.ab-done'); if (d) d.textContent = done();
      return true;
    };
    const key = async (e) => {
      if (!body.isConnected) return document.removeEventListener('keydown', key);
      if (view !== 'topic' || e.metaKey || e.ctrlKey || e.altKey || e.target.closest('input, textarea, select')) return;
      const L = vis(), c = body.querySelector('.hn-t.cur'), i = L.indexOf(c);
      if (e.key === 'j') focus(L[i + 1] || L[i]);
      else if (e.key === 'k') focus(L[Math.max(0, i - 1)]);
      else if (c && (e.key === 'o' || e.key === 'Enter')) open(c.dataset.t);
      else if (c && ACT[e.key - 1]) { e.preventDefault(); if (await react(c, { act: ACT[e.key - 1] })) focus(L[i + 1] || c); return; }
      else return;
      e.preventDefault();
    };
    document.addEventListener('keydown', key);
    body.onclick = async (e) => {
      const t = e.target, d = t.dataset;
      if (d.v) { view = d.v; return draw(); }
      if (d.f) { flt = d.f; return draw(); }
      if (d.rf) { rflt = d.rf; return draw(); }
      if (d.ef) { eflt = d.ef; return draw(); }
      if (d.a) return react(t.closest('.hn-t'), { act: d.a });
      if (d.s) return react(t.closest('.hn-t'), { stance: d.s });
      if (d.tj) { view = 'topic'; flt = 'all'; draw(); const c = body.querySelector(`[data-t="${d.tj}"]`); focus(c); return c.scrollIntoView(); }
      if (d.c) { open(t.closest('.hn-t').dataset.t, true); return; }
      const hd = t.closest('h3');
      if (hd && !t.closest('a')) { focus(hd.parentNode); open(hd.parentNode.dataset.t); }
    };
    draw();
  };
  await show();
}
