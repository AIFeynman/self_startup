// HN 吸收：过去一周 HN 上 AI 相关的讨论压成话题。每张卡三块：社区怎么分（阵营比例，颜色和编号对应下面的观点）、做过的人（成功 / 失败 / 有条件）、推荐的资源；原话只留“原评论 ↗”链接。
// 顶部筛选：共识度、含推荐资源（按类型）、含经验（按成败）；选了内容筛选就只显示命中的话题，卡里只露命中那一类，点“展开全部内容”恢复。键盘 j/k 逐张、1–4 表态。
const CSS = `
.hn-t { background: var(--panel); border: 1px solid var(--line); border-radius: 14px; padding: 16px 18px; margin: 14px 0; border-left: 4px solid transparent; }
.hn-t.cur { border-left-color: var(--accent); }
.hn-t h3 { font: 700 19px/1.5 var(--serif); margin: 0 0 4px; }
.hn-t h3 .ab-tg { display: inline-block; padding: 0 8px; margin-right: 6px; vertical-align: 3px; line-height: 20px; height: 20px; }
.hn-kind { background: var(--bg-2); color: var(--accent); }
.hn-cs0 { background: var(--ok-soft); color: var(--ok); } .hn-cs1 { background: var(--err-soft); color: var(--err); } .hn-cs2 { background: var(--bg-2); color: var(--muted); }
.hn-meta { font-size: 13.5px; color: var(--muted); } .hn-meta details { display: inline; } .hn-meta summary { display: inline; cursor: pointer; color: var(--accent); }
.hn-ps { margin: 6px 0; padding-left: 18px; font-size: 14px; color: var(--text); }
.hn-v { font-size: 16.5px; line-height: 1.75; margin: 10px 0 4px; }
.hn-sx { margin-top: 14px; } .hn-sx h4 { margin: 0 0 6px; font-size: 14px; color: var(--muted); font-weight: 600; } .hn-sx h4 span { font-weight: 400; }
.hn-bar { display: flex; height: 26px; border-radius: 7px; overflow: hidden; gap: 2px; margin: 4px 0 8px; }
.hn-bar i { display: flex; align-items: center; justify-content: center; gap: 5px; color: #fff; font-style: normal; font-size: 12.5px; font-weight: 700; min-width: 30px; } .hn-bar i b { opacity: .85; }
.hn-camps { list-style: none; margin: 0; padding: 0; }
.hn-camps li { display: grid; grid-template-columns: 26px 1fr auto; gap: 4px 10px; align-items: start; padding: 6px 0; border-top: 1px solid var(--line); } .hn-camps li:first-child { border-top: 0; }
.hn-sw { width: 24px; height: 24px; border-radius: 50%; color: #fff; font-size: 13px; font-weight: 700; display: flex; align-items: center; justify-content: center; margin-top: 2px; }
.hn-ct { font-size: 16px; line-height: 1.7; } .hn-cn { font-size: 13.5px; color: var(--muted); white-space: nowrap; text-align: right; }
.hn-o { display: inline-block; font-size: 12px; font-weight: 700; border-radius: 4px; padding: 0 6px; margin-right: 6px; vertical-align: 1px; }
.hn-o0 { background: var(--ok-soft); color: var(--ok); } .hn-o1 { background: var(--err-soft); color: var(--err); } .hn-o2 { background: var(--warn-soft); color: var(--warn); }
.hn-oc { font-weight: 400; font-size: 13.5px; } .hn-oc .hn-o { margin-left: 6px; margin-right: 3px; }
.hn-l { list-style: none; margin: 0; padding: 0; } .hn-l li { padding: 5px 0; border-top: 1px solid var(--line); font-size: 15px; line-height: 1.7; overflow-wrap: anywhere; } .hn-l li:first-child { border-top: 0; }
.hn-l li a.src { font-size: 13px; white-space: nowrap; }
.hn-k { display: inline-block; font-size: 12px; font-weight: 700; border-radius: 4px; padding: 0 6px; margin-right: 7px; background: var(--bg-2); color: var(--accent); }
.hn-rn { font-size: 12px; background: var(--ok-soft); color: var(--ok); border-radius: 4px; padding: 0 6px; margin-left: 7px; white-space: nowrap; } .hn-why { color: var(--muted); font-size: 14px; }
.hn-sx details.hn-more { margin-top: 2px; } .hn-more summary { cursor: pointer; font-size: 13.5px; color: var(--accent); padding: 4px 0; } .hn-more .hn-l li { color: var(--muted); }
.hn-mine { display: flex; gap: 5px; flex-wrap: wrap; margin-top: 10px; } .hn-mine span { font-size: 12.5px; border-radius: 999px; padding: 0 10px; background: var(--err-soft); color: var(--err); } .hn-mine span.ok { background: var(--ok-soft); color: var(--ok); }
.hn-act { display: flex; gap: 5px; flex-wrap: wrap; margin-top: 12px; align-items: center; }
.hn-act button, .hn-all { border: 1px solid var(--line); background: var(--panel); color: var(--text); border-radius: 999px; padding: 1px 11px; font-size: 12.5px; cursor: pointer; }
.hn-act button.on { background: var(--accent); border-color: var(--accent); color: #fff; } .hn-act .sp { color: var(--line-2); }
.hn-st { display: inline-flex; gap: 1px; margin-left: 8px; } .hn-act .hn-st button { border: 0; background: none; font-size: 18px; line-height: 1; padding: 0 1px; color: var(--line-2); } .hn-act .hn-st button.on { background: none; color: var(--warn); }
.hn-all { margin-top: 12px; background: var(--bg); }
.hn-fb { position: sticky; top: 0; z-index: 5; background: var(--bg); padding: 8px 0; border-bottom: 1px solid var(--line); display: flex; flex-direction: column; gap: 6px; margin-bottom: 4px; }
.hn-fg { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; } .hn-fl { font-size: 13px; color: var(--muted); width: 84px; }
.hn-fg button { border: 1px solid var(--line); background: var(--panel); color: var(--text); border-radius: 999px; padding: 2px 13px; font-size: 14px; cursor: pointer; } .hn-fg button.on { background: var(--dark); color: var(--bg); border-color: var(--dark); }
.hn-fg label { font-size: 13px; color: var(--muted); cursor: pointer; margin-left: 6px; }
.hn-tail li { margin: 2px 0; overflow-wrap: anywhere; }
@media (max-width: 720px) { .hn-fb { position: static; } .hn-t { padding: 14px; } .hn-t h3 { font-size: 17px; } .hn-camps li { grid-template-columns: 26px 1fr; } .hn-cn { grid-column: 2; text-align: left; } .hn-fl { width: 100%; } }
`;
const E = (s) => (s == null ? '' : String(s)).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const N = (n) => (n || 0).toLocaleString();
const ACT = ['没增量', '有收获', '很受用', '会用上'];
const STANCE = ['站主流', '站反对', '先不站'];
const CS = { 基本共识: 'hn-cs0', 有分歧: 'hn-cs1', 讨论少: 'hn-cs2' };
const OUT = ['成功', '失败', '有条件'];
const COL = ['#3f7f4f', '#b8432f', '#b9781d', '#3b6ea8', '#8d857b'];
const KO = ['产品', '仓库', '数据', '视频', '论文', '文档'];
const kk = (k) => (k === '博客' ? '文档' : k);
const hnc = (id) => `https://news.ycombinator.com/item?id=${id}`;
const link = (u, t) => (/^https?:/.test(u) ? `<a href="${E(u)}" target="_blank" rel="noopener">${E(t)}</a>` : E(t));
const src = (id) => `<a class="src" href="${hnc(id)}" target="_blank" rel="noopener">原评论 ↗</a>`;

function res(t, D) {
  const L = t.res.map((k) => D.resources[k]).filter((r) => r.intent !== '批评');
  return { rec: L.filter((r) => r.intent === '推荐'), oth: L.filter((r) => r.intent !== '推荐') };
}

function campsHtml(t) {
  const tot = t.camps.reduce((a, c) => a + c.n, 0) || 1;
  return `<div class="hn-bar">${t.camps.map((c, i) => `<i style="flex:${c.n};background:${COL[i % 5]}" title="${E(c.claim)}"><b>${i + 1}</b><span>${Math.round(c.n / tot * 100)}%</span></i>`).join('')}</div>
<ul class="hn-camps">${t.camps.map((c, i) => `<li><span class="hn-sw" style="background:${COL[i % 5]}">${i + 1}</span><div class="hn-ct">${E(c.claim)}</div><div class="hn-cn">${c.n} 条 · ${Math.round(c.n / tot * 100)}% ${src(c.cid)}</div></li>`).join('')}</ul>`;
}

function expsHtml(t, F, full) {
  const L = t.exps.filter((x) => full || !F.exp || x.outcome === F.exp);
  const one = (x) => `<li><span class="hn-o hn-o${OUT.indexOf(x.outcome)}">${x.outcome}</span>${E(x.who)}：${E(x.did)}${x.result ? `，结果：${E(x.result)}` : ''} ${src(x.cids[0])}</li>`;
  const open = F.exp && !full;
  return `<ul class="hn-l">${L.slice(0, open ? 99 : 3).map(one).join('')}</ul>${!open && L.length > 3 ? `<details class="hn-more"><summary>再看 ${L.length - 3} 条</summary><ul class="hn-l">${L.slice(3).map(one).join('')}</ul></details>` : ''}`;
}

function resHtml(t, D, F, full) {
  const { rec, oth } = res(t, D);
  const filt = F.res && !full;
  const keep = (r) => !filt || kk(r.kind) === F.res;
  const li = (r) => `<li><span class="hn-k">${E(kk(r.kind))}</span>${link(r.url, r.title + ' ↗')}${r.intent === '推荐' ? `<span class="hn-rn">${Math.max(r.rec, 1)} 人推荐</span>` : ''}${filt ? '' : `<span class="hn-why"> — ${E(r.why)}</span>`}</li>`;
  const order = (a) => [...a].sort((x, y) => KO.indexOf(kk(x.kind)) - KO.indexOf(kk(y.kind)));
  const R = order(rec.filter(keep)), O = order(oth.filter(keep));
  const showOth = !filt || F.incl;
  return (R.length ? `<ul class="hn-l">${R.map(li).join('')}</ul>` : '<div class="ab-m">没有评论者明确推荐的资源</div>')
    + (showOth && O.length ? `<details class="hn-more"${filt ? ' open' : ''}><summary>另有 ${O.length} 条只是被引用（论据、数据来源），不是推荐</summary><ul class="hn-l">${O.map(li).join('')}</ul></details>` : '');
}

function topic(t, R, D, F) {
  const r = R[t.id] || {}, full = (!F.res && !F.exp) || F.open.has(t.id);
  const nrec = res(t, D).rec.length;
  const oc = OUT.filter((o) => t.exps.some((x) => x.outcome === o)).map((o) => `<span class="hn-o hn-o${OUT.indexOf(o)}">${o}</span>${t.exps.filter((x) => x.outcome === o).length}`).join(' · ');
  const showCamps = full, showExps = full || F.exp, showRes = full || F.res;
  return `<article class="hn-t" data-t="${t.id}"><h3><span class="ab-tg hn-kind">${t.kind}</span><span class="ab-tg ${CS[t.consensus]}">${t.consensus}</span>${E(t.title)}</h3>
<div class="hn-meta">${t.stats.posts} 帖 · ${N(t.stats.comments)} 评论 · 最高 ${N(Math.max(...t.posts.map((p) => p.points)))} 分 · <details><summary>看帖子</summary><ul class="hn-ps">${t.posts.map((p) => `<li>${link(p.url, p.title)} <span class="ab-m">· ${N(p.points)} 分 · <a href="${E(p.hn_url)}" target="_blank" rel="noopener">${N(p.comments)} 评论</a></span></li>`).join('')}</ul></details></div>
${full && t.verdict ? `<p class="hn-v">${E(t.verdict.replace(/\[\d+\]/g, '').trim())}</p>` : ''}
${showCamps && t.camps.length ? `<section class="hn-sx"><h4>社区怎么分 <span>按持该观点的评论数</span></h4>${campsHtml(t)}</section>` : ''}
${showExps && t.exps.length ? `<section class="hn-sx"><h4>做过的人 <span class="hn-oc">${oc}</span></h4>${expsHtml(t, F, full)}</section>` : ''}
${showRes ? `<section class="hn-sx"><h4>推荐的资源 <span>${nrec} 条评论者明确推荐</span></h4>${resHtml(t, D, F, full)}</section>` : ''}
${full && t.mine.length ? `<div class="hn-mine">${t.mine.map((m) => `<span class="${m.rel === '印证' ? 'ok' : ''}" title="${E(m.why)}">与你的判断${m.rel}：${E(m.judgment)}</span>`).join('')}</div>` : ''}
${!full ? `<button class="hn-all" data-all="${t.id}">展开全部内容</button>` : ''}
<div class="hn-act">${ACT.map((a, i) => `<button data-a="${a}" title="键盘 ${i + 1}" class="${r.act === a ? 'on' : ''}">${a}</button>`).join('')}<span class="sp">｜</span>${STANCE.map((a) => `<button data-s="${a}" class="${r.stance === a ? 'on' : ''}">${a}</button>`).join('')}<span class="hn-st" title="这个话题整理得好不好用：1 星很差，5 星很好">${[1, 2, 3, 4, 5].map((n) => `<button data-n="${n}" class="${(r.stars || 0) >= n ? 'on' : ''}">★</button>`).join('')}</span></div></article>`;
}

function match(t, D, F, R) {
  if (F.cons && t.consensus !== F.cons) return false;
  if (F.todo && R[t.id] && R[t.id].act) return false;
  if (F.res) { const { rec, oth } = res(t, D); if (![...rec, ...(F.incl ? oth : [])].some((r) => kk(r.kind) === F.res)) return false; }
  if (F.exp && !t.exps.some((x) => x.outcome === F.exp)) return false;
  return true;
}

function how(D) {
  const M = D.meta, F = M.fails || {};
  return `<div class="ab-fun">${[[M.queried, '搜到的 AI 相关帖'], [M.collected, `达到门槛（≥${M.weights.min_points} 分或≥${M.weights.min_comments} 评论）`], [M.ai + M.edge, '判为 AI 相关'], [M.digested, `评论≥${M.weights.digest_min}，已提炼`], [N(M.comments), '条评论已读']].map((x) => `<div><b>${typeof x[0] === 'number' ? N(x[0]) : x[0]}</b><span>${x[1]}</span></div>`).join('')}
<div class="hl"><b>${M.topics}</b><span>个话题（覆盖 ${M.in_topics} 帖）</span></div><div><b>${M.tail}</b><span>帖在长尾</span></div><div><b>${M.resources}</b><span>个被推荐的资源</span></div><div><b>${M.exps}</b><span>条做过的经验</span></div><div><b>${M.quotes_kept}/${M.quotes_raw}</b><span>观点和经验的原话通过核对</span></div></div>
<div class="ab-q"><h2>这页是怎么算出来的</h2>
<p><b>采集：</b>${E(M.start)} 至 ${E(M.end)}（UTC），HN 搜索接口按 18 个 AI 相关词取帖，保留 ≥${M.weights.min_points} 分或 ≥${M.weights.min_comments} 条评论的，Show / Launch HN 评论 ≥10 也收；Jev 按标题判是否主要在讨论 AI（概率 ≥${M.weights.jev_min} 算相关；它给的概率偏低，这个阈值与 Claude 判断吻合 97%），明确的标“AI”，在边缘的也保留（${M.edge} 帖）。</p>
<p><b>提炼：</b>评论 ≥${M.weights.digest_min} 条的帖子由 ${E(M.models.digest)} 逐帖读评论区（最多 8 万字符，按 HN 自己的排序取靠前的讨论串），抽观点、亲身经验、推荐链接。每条观点和经验必须带一句评论原文，程序在评论里逐字核对，找不到的丢弃（${M.quotes_raw - M.quotes_kept} 条被丢）；链接必须在评论里真出现过。</p>
<p><b>话题：</b>${E(M.models.topics)} 看每帖的标题、讨论一句话和主要对象，聚成 ${M.topics} 个话题，不适合并入的放长尾。再对每个话题逐个综合：观点按立场并成阵营，阵营人数是持该观点的评论数相加（HN 不公开评论得分，这是近似，只说明谁说得多，不说明谁说得对）。一句话结论每句要带阵营序号，没带的隐藏（${M.unchecked} 个话题被隐藏）。</p>
<p><b>共识度：</b>评论总数 &lt;80 为“讨论少”；最大阵营占比 ≥60% 为“基本共识”；其余且第二大阵营 ≥25% 为“有分歧”。</p>
<p><b>资源：</b>按网址去重。提炼时模型给每个链接标意图：评论者明确说好用 / 有价值 / 推荐的算“推荐”（共 ${M.recommended} 个），只是当论据、数据来源引用的算“被引用”，当反面例子的不展示。话题卡里只列推荐的，被引用的折叠；“N 人推荐”是提到该链接的不同评论者数（不含作者自荐），是近似。没有核实链接内容。</p>
<p class="ab-m">星级：每个话题可打 1–5 星，表示这个话题整理得好不好用，存在表态日志里，用来评估聚类和综合质量。没做的：与上周话题对照（需要上一周的数据）；原话没有翻译；表态“站某边”只记草稿，不写进你的判断库。HN 评论者偏工程师、偏怀疑，不代表市场上的用户。${F.digest ? `有 ${F.digest} 帖提炼失败已跳过；` : ''}${M.minutes ? `耗时 ${M.minutes} 分钟，` : ''}Claude 模型费用 $${M.cost}，Jev 调用费用没有统计。</p></div>`;
}

export async function hnView(el, ctx, rid) {
  const { api, h, ui, toast } = ctx;
  const runs = await api.get('/api/absorb/hn/runs');
  const cur = rid ? decodeURIComponent(rid) : (runs.find((r) => r.done) || runs[0] || {}).id;
  const body = h('div');
  let timer = null;
  const head = h('div', {}, [h('div.tabs', {}, [h('button', { onclick: () => { location.hash = '#absorb'; } }, '选题吸收'), h('button.active', {}, 'HN 吸收')]),
    h('div.tabs.ab-sub', {}, runs.map((r) => h('button', { class: r.id === cur ? 'active' : '', onclick: () => { location.hash = '#absorb/hn/' + encodeURIComponent(r.id); } }, r.id.replace('_', ' 至 ') + (r.done ? '' : r.running ? ' · 进行中' : ' · 中断'))))]);
  el.append(h('style', {}, CSS), ui.pageHead('吸收', '过去一周 HN 上 AI 相关的讨论：按话题看社区站哪边、谁做过什么、推荐了什么', []), head, body);
  if (!cur) { body.append(ui.empty('还没有跑过。每天会自动跑一次；也可以命令行：python -m app.modules._absorb_hn --start 起 --end 止')); return; }
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
    const F = { cons: '', res: '', exp: '', incl: false, todo: false, open: new Set() };
    let view = 'topic';
    const done = () => `已表态 ${D.topics.filter((t) => R[t.id] && (R[t.id].act || R[t.id].stars)).length}/${D.topics.length}`;
    const btn = (g, v, label) => `<button data-g="${g}" data-v="${v}" class="${(g === 'todo' ? F.todo : F[g]) === (g === 'todo' ? true : v) && (v !== '' || !F[g]) ? 'on' : ''}">${label}</button>`;
    const draw = () => {
      const L = D.topics.filter((t) => match(t, D, F, R));
      const cs = D.topics.reduce((a, t) => ({ ...a, [t.consensus]: (a[t.consensus] || 0) + 1 }), {});
      const filters = `<div class="hn-fb"><div class="hn-fg"><span class="hn-fl">共识度</span>${btn('cons', '', '全部')}${btn('cons', '有分歧', '有分歧')}${btn('cons', '基本共识', '基本共识')}${btn('cons', '讨论少', '讨论少')}${btn('todo', '1', '未表态')}</div>
<div class="hn-fg"><span class="hn-fl">含推荐资源</span>${KO.map((k) => btn('res', k, k)).join('')}<label><input type="checkbox" data-incl ${F.incl ? 'checked' : ''}> 也算只被引用的</label></div>
<div class="hn-fg"><span class="hn-fl">含经验</span>${OUT.map((k) => btn('exp', k, k)).join('')}<span class="ab-m">显示 ${L.length} / ${D.topics.length} 个话题 · ${done()}</span></div></div>`;
      body.innerHTML = `<div class="ab-m">${E(M.start)} 至 ${E(M.end)} · 观点和经验的原话已逐字核对，归并和结论由模型完成，未经人工校对</div>
<div class="ab-note">${N(M.collected)} 帖里 ${N(M.ai + M.edge)} 帖与 AI 相关，压成 <b>${M.topics} 个话题</b>（覆盖 ${M.in_topics} 帖），另有 ${M.tail} 帖在长尾。先看<b>有分歧 ${cs['有分歧'] || 0}</b>：社区没谈拢；<b>基本共识 ${cs['基本共识'] || 0}</b> 看一句话结论即可。<span class="ab-key">键盘 <kbd>j</kbd>/<kbd>k</kbd> 逐张 <kbd>1</kbd>–<kbd>4</kbd> 表态</span></div>
<div class="ab-bar">${[['topic', '话题'], ['how', '口径']].map((x) => `<button data-v="${x[0]}" class="${view === x[0] ? 'on' : ''}">${x[1]}</button>`).join('')}<span class="ab-sp"></span><span class="ab-m">推荐资源 ${M.recommended} · 经验 ${M.exps}</span></div>
${view === 'topic' ? filters + (L.map((t) => topic(t, R, D, F)).join('') || '<div class="ab-m">这个筛选下没有话题</div>') + (!F.res && !F.exp && !F.cons && !F.todo ? `<details class="ab-fold hn-tail"><summary>长尾：另有 ${M.tail} 帖没并进话题</summary><ul>${D.tail.map((p) => `<li>${link(p.url, p.title)} <span class="ab-m">· <a href="${E(p.hn_url)}" target="_blank" rel="noopener">${N(p.comments)} 评论</a>${p.tldr ? ' · ' + E(p.tldr) : ''}</span></li>`).join('')}</ul></details>` : '') : how(D)}`;
    };
    const vis = () => [...body.querySelectorAll('.hn-t')];
    const focus = (x) => { if (!x) return; body.querySelectorAll('.hn-t.cur').forEach((y) => y.classList.remove('cur')); x.classList.add('cur'); x.scrollIntoView({ block: 'nearest' }); };
    const react = async (c, patch) => {
      const id = c.dataset.t, old = R[id] || {}, nx = { act: old.act || '', stance: old.stance || '', stars: old.stars || 0, ...patch };
      for (const k of Object.keys(patch)) if (old[k] === patch[k]) nx[k] = k === 'stars' ? 0 : '';
      try { await api.post(`/api/absorb/hn/runs/${encodeURIComponent(cur)}/react`, { topic: +id, act: nx.act, stance: nx.stance, stars: nx.stars }); } catch (err) { toast(err.message || '没存上'); return false; }
      if (nx.act || nx.stance || nx.stars) R[id] = nx; else delete R[id];
      c.querySelectorAll('[data-a]').forEach((b) => b.classList.toggle('on', nx.act === b.dataset.a));
      c.querySelectorAll('[data-s]').forEach((b) => b.classList.toggle('on', nx.stance === b.dataset.s));
      c.querySelectorAll('[data-n]').forEach((b) => b.classList.toggle('on', nx.stars >= +b.dataset.n));
      return true;
    };
    const key = async (e) => {
      if (!body.isConnected) return document.removeEventListener('keydown', key);
      if (view !== 'topic' || e.metaKey || e.ctrlKey || e.altKey || e.target.closest('input, textarea, select')) return;
      const L = vis(), c = body.querySelector('.hn-t.cur'), i = L.indexOf(c);
      if (e.key === 'j') focus(L[i + 1] || L[i]);
      else if (e.key === 'k') focus(L[Math.max(0, i - 1)]);
      else if (c && ACT[e.key - 1]) { e.preventDefault(); if (await react(c, { act: ACT[e.key - 1] })) focus(L[i + 1] || c); return; }
      else return;
      e.preventDefault();
    };
    document.addEventListener('keydown', key);
    body.onchange = (e) => { if (e.target.dataset.incl !== undefined) { F.incl = e.target.checked; draw(); } };
    body.onclick = async (e) => {
      const t = e.target, d = t.dataset;
      if (d.v && !d.g) { view = d.v; return draw(); }
      if (d.g) {
        if (d.g === 'todo') F.todo = !F.todo;
        else { F[d.g] = F[d.g] === d.v ? '' : d.v; F.open.clear(); }
        return draw();
      }
      if (d.all) { F.open.add(+d.all); return draw(); }
      const c = t.closest('.hn-t');
      if (d.a) return react(c, { act: d.a });
      if (d.s) return react(c, { stance: d.s });
      if (d.n) return react(c, { stars: +d.n });
      if (c && !t.closest('a, summary, details')) focus(c);
    };
    draw();
  };
  await show();
}
