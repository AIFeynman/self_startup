// 吸收：按选题看一段时间的认知卡。默认先看 know-how 地图（领域结构、做事流程、成熟度、每个问题的成功做法和失败教训、分歧、失败模式、该跟的人、空白，每条挂着依据的卡）；卡片视图里每个问题先看现状，再看有争议的和高置信的；每张卡给出判断的来源构成（几位作者、几篇论文 / 项目 / 产品 / 讨论佐证、几处反对）和置信度，点开看各作者原话和挂上的证据；键盘 j/k 逐张、1–4 表态。
import { hnView } from './_absorb_hn.js';

const CSS = `
.ab-fun { display: grid; grid-template-columns: repeat(5, 1fr); gap: 8px; margin: 12px 0; }
.ab-fun div { background: var(--panel); border: 1px solid var(--line); border-radius: var(--radius-sm); padding: 8px 10px; }
.ab-fun b { display: block; font-size: 21px; font-variant-numeric: tabular-nums; }
.ab-fun span { font-size: 12px; color: var(--muted); }
.ab-fun .hl { border: 2px solid var(--accent); }
.ab-note { background: var(--panel); border: 1px solid var(--line); border-left: 4px solid var(--warn); border-radius: 8px; padding: 8px 12px; font-size: 13.5px; margin: 10px 0; }
.ab-bar { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; margin: 10px 0 8px; padding: 8px 0; position: sticky; top: 0; z-index: 5; background: var(--bg); border-bottom: 1px solid var(--line); }
.ab-bar button, .ab-act button, .ab-more button { border: 1px solid var(--line); background: var(--panel); color: var(--text); border-radius: 999px; padding: 3px 12px; font-size: 13px; cursor: pointer; }
.ab-bar button.on { background: var(--dark); color: var(--bg); border-color: var(--dark); }
.ab-sp { flex: 1; }
.ab-m { color: var(--muted); font-size: 13px; }
.ab-q { background: var(--panel); border: 1px solid var(--line); border-radius: var(--radius); padding: 12px 14px; margin: 12px 0; }
.ab-q h2 { font: 700 17px/1.5 var(--serif); margin: 0 0 4px; }
.ab-st { font: 700 11.5px var(--font); border-radius: 4px; padding: 1px 7px; margin-left: 6px; vertical-align: 2px; white-space: nowrap; }
.ab-st0 { background: var(--ok-soft); color: var(--ok); } .ab-st1 { background: var(--err-soft); color: var(--err); } .ab-st2 { background: var(--warn-soft); color: var(--warn); }
.ab-now { font-size: 14px; margin: 6px 0 8px; padding: 6px 10px; background: var(--bg); border-radius: 8px; }
.ab-now a { font-size: 11.5px; cursor: pointer; }
.ab-c { border-top: 1px solid var(--line); padding: 10px 0 10px 8px; margin-left: -8px; border-left: 3px solid transparent; }
.ab-c.cur { border-left-color: var(--accent); background: var(--bg); }
.ab-ch { display: grid; grid-template-columns: 64px minmax(0, 1fr); gap: 8px; cursor: pointer; }
.ab-tg { font-size: 11px; font-weight: 700; border-radius: 4px; height: 20px; line-height: 20px; text-align: center; margin-top: 2px; white-space: nowrap; }
.ab-tc { background: var(--warn-soft); color: var(--warn); } .ab-th { background: var(--ok-soft); color: var(--ok); }
.ab-tm { background: var(--bg-2); color: var(--accent); } .ab-tl { background: var(--bg-2); color: var(--muted); }
.ab-cl { font-size: 15px; font-weight: 600; line-height: 1.5; } .ab-sc { color: var(--muted); font-size: 12.5px; }
.ab-vs { font-size: 13px; margin: 5px 0 0; padding: 3px 9px; border-left: 3px solid var(--line-2); background: var(--bg); border-radius: 0 6px 6px 0; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.ab-vs b { font-size: 11.5px; margin-right: 6px; } .ab-c.open .ab-vs { -webkit-line-clamp: unset; }
.ab-v0 { border-left-color: var(--err); } .ab-v0 b { color: var(--err); }
.ab-lt { display: flex; gap: 4px 10px; flex-wrap: wrap; align-items: center; margin-top: 5px; font-size: 12px; color: var(--muted); }
.ab-lt .dt { letter-spacing: 1px; color: var(--dark); } .ab-lt .on { color: var(--ok); font-weight: 600; } .ab-lt .no { color: var(--err); font-weight: 600; }
.ab-act { display: flex; gap: 5px; flex-wrap: wrap; margin: 7px 0 0 72px; }
.ab-act button { font-size: 12px; padding: 1px 10px; }
.ab-act button.on { background: var(--accent); border-color: var(--accent); color: #fff; }
.ab-act .ab-stars { display: inline-flex; gap: 1px; margin-left: 8px; }
.ab-act .ab-stars button { border: 0; background: none; padding: 0 1px; font-size: 18px; line-height: 1; color: var(--line-2); }
.ab-act .ab-stars button.on { background: none; color: var(--warn); }
.ab-bar select { width: auto; font: inherit; font-size: 13px; padding: 2px 8px; border: 1px solid var(--line); border-radius: 999px; background: var(--panel); color: var(--text); }
.ab-d { margin: 8px 0 2px 72px; font-size: 13px; display: none; overflow-wrap: anywhere; }
.ab-c.open .ab-d { display: block; }
.ab-d h5 { margin: 8px 0 3px; font-size: 12px; color: var(--muted); font-weight: 600; }
.ab-s { border-left: 3px solid var(--line-2); padding: 2px 0 2px 9px; margin: 4px 0; }
.ab-s q { color: var(--muted); quotes: "“" "”"; } .ab-s .g { color: var(--ok); }
.ab-e { padding: 2px 0; } .ab-e .v { font-size: 11px; font-weight: 700; margin-right: 4px; } .ab-e .v1 { color: var(--ok); } .ab-e .v0 { color: var(--err); }
.ab-more { margin: 6px 0 0; }
.ab-fold { font-size: 13px; color: var(--muted); margin-top: 6px; } .ab-fold summary { cursor: pointer; } .ab-fold li { margin: 2px 0; }
.ab-qg { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 10px; margin: 12px 0; }
.ab-qc { background: var(--panel); border: 1px solid var(--line); border-radius: var(--radius); padding: 12px 14px; cursor: pointer; }
.ab-qc:hover { border-color: var(--accent); } .ab-qc .t { font: 700 15px/1.5 var(--serif); margin-bottom: 4px; }
.ab-sb { display: flex; height: 8px; border-radius: 4px; overflow: hidden; margin: 8px 0 4px; gap: 2px; } .ab-sb i { display: block; min-width: 3px; }
.ab-sb .ab-tc { background: var(--warn); } .ab-sb .ab-th { background: var(--ok); } .ab-sb .ab-tm { background: var(--accent); opacity: .55; } .ab-sb .ab-tl { background: var(--line-2); }
.ab-key { font-size: 12px; color: var(--muted); } .ab-key kbd { font: 11px var(--font); border: 1px solid var(--line); border-bottom-width: 2px; border-radius: 4px; padding: 0 4px; background: var(--panel); }
.ab-pre { font-size: 12.5px; color: var(--muted); flex-basis: 100%; } .ab-pre.bad { color: var(--err); }
.ab-new { display: flex; gap: 8px; flex-wrap: wrap; align-items: end; background: var(--panel); border: 1px solid var(--line); border-radius: var(--radius); padding: 12px 14px; margin: 0 0 14px; }
.ab-new label { display: flex; flex-direction: column; gap: 3px; font-size: 12px; color: var(--muted); }
.ab-new input { min-width: 0; }
.ab-run { background: var(--panel); border: 1px solid var(--line); border-radius: var(--radius); padding: 18px; margin: 12px 0; }
.ab-prog { height: 6px; border-radius: 3px; background: var(--bg-2); overflow: hidden; margin: 10px 0 6px; }
.ab-prog i { display: block; height: 100%; background: var(--accent); }
.ab-hide { display: none; }
.ab-sub { margin: -6px 0 14px; padding-left: 10px; border-left: 3px solid var(--line-2); } .ab-sub button { font-size: 13px; padding: 3px 12px; }
.ab-fb table { border-collapse: collapse; width: 100%; font-size: 13px; margin: 4px 0 14px; }
.ab-fb th, .ab-fb td { text-align: left; padding: 4px 8px; border-bottom: 1px solid var(--line); font-variant-numeric: tabular-nums; }
.ab-fb th { color: var(--muted); font-weight: 600; font-size: 12px; }
.ab-fb .bar { display: inline-block; height: 8px; border-radius: 3px; background: var(--accent); vertical-align: middle; margin-right: 6px; }
.ab-fb .bar.k { background: var(--line-2); } .ab-fb .bar.d { background: var(--err); }
.ab-fb h3 { font: 700 15px/1.5 var(--serif); margin: 14px 0 2px; }
.ab-kh h3 { font: 700 16px/1.5 var(--serif); margin: 22px 0 6px; } .ab-kh .ab-q { scroll-margin-top: 60px; }
.ab-kt { width: 100%; border-collapse: collapse; font-size: 13.5px; background: var(--panel); border: 1px solid var(--line); border-radius: var(--radius); overflow: hidden; margin: 4px 0; }
.ab-kt th, .ab-kt td { text-align: left; padding: 7px 10px; border-bottom: 1px solid var(--line); vertical-align: top; }
.ab-kt th { color: var(--muted); font-weight: 600; font-size: 12px; white-space: nowrap; } .ab-kt tr:last-child td { border-bottom: 0; }
.ab-flow { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 8px; margin: 4px 0; }
.ab-flow div { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 8px 10px; font-size: 13px; } .ab-flow b { display: block; font-size: 14px; }
.ab-k5 { font-size: 12px; font-weight: 700; margin: 8px 0 0; } .ab-k5.d { color: var(--ok); } .ab-k5.f { color: var(--err); }
.ab-kl { margin: 2px 0 0; padding-left: 20px; font-size: 14px; } .ab-kl li { margin: 5px 0; } .ab-kl.d li::marker { color: var(--ok); } .ab-kl.f li::marker { color: var(--err); }
.ab-rf, .ab-qa { font-size: 11.5px; color: var(--muted); } .ab-rf a, .ab-qa a { cursor: pointer; margin-left: 4px; }
.ab-split { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin: 6px 0; } .ab-split div { background: var(--bg); border-radius: 8px; padding: 6px 10px; font-size: 13.5px; }
.ab-cond { font-size: 13px; color: var(--muted); margin: 4px 0 0; } .ab-cond b { color: var(--accent); font-size: 12px; margin-right: 6px; }
@media (max-width: 720px) { .ab-split { grid-template-columns: 1fr; } .ab-kt thead { display: none; } .ab-kt, .ab-kt tbody, .ab-kt tr, .ab-kt td { display: block; } .ab-kt tr { border-bottom: 1px solid var(--line); padding: 6px 0; } .ab-kt td { border: 0; padding: 2px 10px; } .ab-kt td:not(:first-child)::before { content: attr(data-l) "："; color: var(--muted); font-size: 12px; } }
@media (max-width: 720px) { .ab-fun { grid-template-columns: repeat(2, 1fr); } .ab-ch { grid-template-columns: 58px minmax(0, 1fr); } .ab-act, .ab-d { margin-left: 0; } .ab-new label { flex: 1 1 120px; } .ab-key { display: none; } .ab-bar { gap: 4px; } .ab-bar button { padding: 2px 9px; } .ab-qg { grid-template-columns: 1fr; } }
`;

const E = (s) => (s == null ? '' : String(s)).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const N = (n) => (n || 0).toLocaleString();
const TG = { c: ['有争议', 'ab-tc'], h: ['高置信', 'ab-th'], m: ['中置信', 'ab-tm'], l: ['低置信', 'ab-tl'] };
const LV = { h: '高', m: '中', l: '低' };
const TAGS = Object.keys(TG);
const ACT = ['没增量', '有收获', '很受用', '会用上'];
const ACT_TIP = { 没增量: '受用程度 0：早就知道，或与我无关', 有收获: '受用程度 1：新知道的，值得记一下', 很受用: '受用程度 2：加深或改变了我对这个问题的理解', 会用上: '受用程度 3：会影响我之后的判断、取舍或做法' };
const ST = { 共识为主: 'ab-st0', 有分歧: 'ab-st1', 证据少: 'ab-st2' };
const POOL = { papers: '论文', repos: '开源项目', intel: '产品动态', disc: '讨论' };
const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;

function lights(c) {
  const g = c.conf;
  const L = [[g.papers, '篇论文佐证'], [g.repos, '个项目实现了'], [g.intel, '个产品这么做'], [g.disc, '条讨论佐证']].filter((x) => x[0]);
  return `<div class="ab-lt"><span title="得分 ${g.score}：作者最多计 3，有一手来源 +1，论文 / 项目 / 产品佐证最多计 2，有讨论佐证 +1，有反对 −2；≥5 高，≥3 中">置信 <b>${LV[g.level]}</b></span><span><span class="dt">${'●'.repeat(Math.min(5, g.authors))}</span> ${g.authors} 位独立作者${g.first ? `，${g.first} 位一手` : ''}</span>${L.map((x) => `<span class="on">${x[0]} ${x[1]}</span>`).join('')}${g.against ? `<span class="no">${g.against} 处反对</span>` : ''}</div>`;
}

function vs(c) {
  const x = c.opp[0];
  return x ? `<div class="ab-vs ab-v0"><b>有人说相反</b>${E(x.claim)} <span class="ab-m">分歧：${E(x.point)}</span></div>` : '';
}

function detail(c, byId) {
  let s = '';
  if (c.opp.length) s += '<h5>与它矛盾的说法</h5>' + c.opp.map((x) => `<div class="ab-e"><span class="v v0">矛盾</span>${E(byId[x.o] ? byId[x.o].claim : x.claim)} <span class="ab-m">· 分歧点：${E(x.point)}</span></div>`).join('');
  s += '<h5>各作者的说法（按时间）</h5>' + c.src.map((u) => `<div class="ab-s"><a href="${E(u.url)}" target="_blank" rel="noopener">@${E(u.user)}</a> <span class="ab-m">${E(u.day.slice(5))} · ${E(u.kind)}</span>${u.gain ? ` <span class="g">＋${E(u.gain)}</span>` : ''}<br>${E(u.claim)}${u.thesis ? `<br><span class="ab-m">这篇文章的主张：${E(u.thesis)}</span>` : ''}<br><q>${E(u.quote)}</q></div>`).join('');
  if (c.ev.length) s += '<h5>其他来源的证据</h5>' + c.ev.map((e) => `<div class="ab-e"><span class="v ${e.v === '反对' ? 'v0' : 'v1'}">${POOL[e.pool]}·${e.v}</span>${/^https?:/.test(e.url) ? `<a href="${E(e.url)}" target="_blank" rel="noopener">${E(e.title)}</a>` : E(e.title)} <span class="ab-m">${E(e.date)}${e.pool === 'repos' ? ` · ★${N(e.meta)}` : e.pool === 'papers' ? (e.meta ? ` · 引用 ${e.meta}` : '') : e.meta ? ` · ${E(e.meta)}` : ''} · ${E(e.why)}</span></div>`).join('');
  return s;
}

function kh(D) {
  const S = D.synth;
  if (!S) return `<div class="ab-q"><h2>还没有 know-how 地图</h2><p class="ab-m">这个选题是在加“综合”这一步之前跑的。生成地图只补最后两步：按每个问题整理成功做法和失败教训，再综合出领域结构、做事流程、成熟度、分歧和失败模式；前面的抽取、合并、挂证据都不重跑，大约 5 分钟。</p><button class="primary" data-syn>生成 know-how 地图</button></div>`;
  const R = D.refs || {}, Q = Object.fromEntries(D.questions.map((q) => [q.id, q]));
  const ref = (ids) => `<span class="ab-rf">${ids.filter((i, k) => R[i] && (R[i].shown || ids.findIndex((j) => R[j] && !R[j].shown && R[j].user === R[i].user) === k)).map((i) => { const r = R[i]; return r.shown ? `<a data-j="${i}" title="${E(r.claim)}">[${i}]</a>` : `<a href="${E(r.url)}" target="_blank" rel="noopener" title="${E(r.claim)}">@${E(r.user)}</a>`; }).join('')}</span>`;
  const qa = (qs) => `<span class="ab-qa">${(qs || []).filter((q) => Q[q]).map((q) => `<a data-kq="${q}" title="${E(Q[q].q)}">${q}</a>`).join('')}</span>`;
  const tbl = (hs, rows) => `<table class="ab-kt"><thead><tr>${hs.map((x) => `<th>${x}</th>`).join('')}</tr></thead><tbody>${rows.map((r) => `<tr>${r.map((c, i) => `<td data-l="${hs[i]}">${c}</td>`).join('')}</tr>`).join('')}</tbody></table>`;
  const li = (xs, k) => (xs.length ? `<div class="ab-k5 ${k}">${k === 'd' ? '成功做法' : '失败教训'}</div><ul class="ab-kl ${k}">${xs.map((x) => `<li>${E(x.t)} ${ref(x.c)}</li>`).join('')}</ul>` : '');
  const n = D.questions.reduce((a, q) => a + ((S.q[q.id] || {}).do || []).length + ((S.q[q.id] || {}).fail || []).length, 0);
  return `<div class="ab-kh">${S.line ? `<div class="ab-note"><b>一句话：</b>${E(S.line)}</div>` : ''}
<div class="ab-m">${D.questions.length} 个关键问题 · ${n} 条做法和教训，每条都挂着依据：[编号] 是需要看的卡，点开跳到卡片；@作者 是折叠起来的单一来源，点开看原文。</div>
${S.structure.length ? `<h3>领域由哪几块组成</h3>${tbl(['组成部分', '包含', '最常见的坑', '相关问题'], S.structure.map((x) => [`<b>${E(x.name)}</b>`, E(x.what), E(x.pitfall), qa(x.q)]))}` : ''}
${S.flow.length ? `<h3>做事流程</h3><div class="ab-flow">${S.flow.map((x, i) => `<div><b>${i + 1} · ${E(x.name)}</b>${E(x.what)} ${qa(x.q)}</div>`).join('')}</div>` : ''}
${S.levels.length ? `<h3>成熟度：从手工到自动</h3>${tbl(['级别', '怎么做', '前提', '例子', '主要风险'], S.levels.map((x) => [`<b>${E(x.name)}</b>`, E(x.how), E(x.needs), E(x.example), E(x.risk)]))}` : ''}
<h3>关键问题：成功做法与失败教训</h3>
${D.questions.map((q) => { const p = S.q[q.id] || { do: [], fail: [] }; return `<div class="ab-q" id="kh-${q.id}"><h2>${E(q.q)}<span class="ab-st ${ST[q.status] || 'ab-st2'}">${E(q.status)}</span></h2>${q.now ? `<div class="ab-now"><b>现状：</b>${E(q.now).replace(/\[C(\d+)\]/g, (m, k) => `<a data-j="${k}">[${k}]</a>`)}</div>` : ''}${li(p.do, 'd')}${li(p.fail, 'f')}${p.do.length || p.fail.length ? '' : '<div class="ab-m">这个问题下的材料不够整理出做法。</div>'}</div>`; }).join('')}
${S.disputes.length ? `<h3>分歧：做过的人结论相反的地方</h3>${S.disputes.map((x) => `<div class="ab-q"><b>${E(x.t)}</b> ${ref(x.c)}<div class="ab-split"><div>${E(x.a)}</div><div>${E(x.b)}</div></div><div class="ab-cond"><b>怎么选</b>${E(x.cond)}</div></div>`).join('')}` : ''}
${S.failures.length ? `<h3>失败模式</h3>${tbl(['失败模式', '长什么样', '看哪个问题'], S.failures.map((x) => [`<b>${E(x.name)}</b>`, E(x.looks), qa(x.q)]))}` : ''}
${(D.people || []).length ? `<h3>该持续跟的人</h3>${tbl(['作者', '文章 / 认知', '涉及问题', '代表说法'], D.people.map((p) => [`<a href="${E(p.url)}" target="_blank" rel="noopener">@${E(p.user)}</a>`, `${p.arts} 篇 / ${p.units} 条`, qa(p.qs), E(p.best)]))}` : ''}
${S.gaps.length ? `<h3>空白</h3><ul class="ab-kl">${S.gaps.map((g) => `<li>${E(g)}</li>`).join('')}</ul>` : ''}
<p class="ab-m">地图由模型根据本选题的认知卡综合，只用卡片里有的信息；做法和教训必须引用到卡片，引用不上的已丢弃。该跟的人按实践者、官方一手文章数排。</p></div>`;
}

function how(D) {
  const M = D.meta, P = D.profile, r = M.rel || {}, p = M.pools || {};
  return `<div class="ab-fun">${[[M.scanned, '相关领域长文'], [M.theme, '属于这个选题'], [M.extracted, `质量分≥${M.min_q}，已抽取`], [M.units, '条认知（引文已核对）'], [M.cards, '张认知卡']].map((x) => `<div><b>${N(x[0])}</b><span>${x[1]}</span></div>`).join('')}
<div class="hl"><b>${N(M.shown)}</b><span>张需要看</span></div><div><b>${N(M.multi)}</b><span>其中多人印证</span></div><div><b>${N(M.conf)}</b><span>对已复核的矛盾</span></div><div><b>${N((M.tags || {}).h)}</b><span>张高置信</span></div><div><b>${N(M.evcards)}</b><span>张挂上了其他来源证据</span></div></div>
<div class="ab-q"><h2>这页是怎么算出来的</h2>
<p><b>选题范围：</b>${E(P.scope)}</p><p><b>不算：</b>${E(P.exclude)}</p>
<p><b>筛选：</b>${E(M.window)} 长文库相关领域共 ${N(M.scanned)} 篇，模型判定属于这个选题的 ${N(M.theme)} 篇，其中质量分≥${M.min_q} 的 ${N(M.extracted)} 篇做了抽取。</p>
<p><b>抽取：</b>共 ${N(M.units)} 条认知，每条带一句原文引文，引文在原文里找不到的 ${N(M.quote_bad)} 条已丢弃；${N(M.unassigned)} 条没归到任何问题。</p>
<p><b>合并：</b>同一问题内向量相近的 ${N(M.pairs)} 对交给模型判断：重复 ${N(r['重复'])}、增益 ${N(r['增益'])}、反驳 ${N(r['反驳'])}、不同 ${N(r['不同'])}。重复和增益合成一张卡，共 ${N(M.cards)} 张；反驳经更强的模型复核，成立 ${N(M.conf)} 对。合并判得偏严，说法相近但结论不完全相同的不会合并。</p>
<p><b>需要看的 ${N(M.shown)} 张：</b>两个以上独立作者都说的、复核成立的矛盾双方，再加每个问题最多 3 张质量分≥4 的实践者或官方单来源卡。其余 ${N(M.folded)} 张单一来源卡折叠在各问题末尾。</p>
<p><b>证据池：</b>论文 ${N(p.papers)} 篇、开源项目 ${N(p.repos)} 个、产品动态 ${N(p.intel)} 条、讨论 ${N(p.disc)} 条；每张卡每类取向量最相近的 4 条，由模型逐条判为佐证、反对或无关，只留前两种。</p>
<p><b>置信度：</b>不看你怎么想，只看这条说法有多少独立来源撑着。得分 = 独立作者数（最多计 3）+ 有实践者或官方一手来源（1）+ 论文 / 开源项目 / 产品动态佐证（最多计 2）+ 有社区讨论佐证（1）−（有反对，2）。≥5 为高，≥3 为中，其余为低。同一作者多篇只算一人；推广类来源不计作者。</p>
<p><b>标签：</b>有争议 = 有复核成立的对立说法，或论文 / 项目 / 产品 / 讨论里有反对证据，无论得分多少都先看；其余按置信度分高 / 中 / 低。一张卡只取一个标签。每张卡上列出的人数和各类佐证数就是得分的依据。</p>
<p class="ab-m">抽取、合并、挂证据都由模型完成，没有人工校对；${M.fails ? `有 ${M.fails} 次模型调用重试后仍失败，对应的那批按“不属于 / 不同 / 无关”处理；` : ''}${M.minutes ? `耗时 ${M.minutes} 分钟，` : ''}模型花费 $${M.cost}（按接口价折算）。</p></div>`;
}

function fb(F) {
  if (!F.n) return '<div class="ab-fb ab-m">还没有表态。在卡片上点“没增量 / 有收获 / 很受用 / 会用上”，这里会按提炼的角度统计哪类认知对你有用。</div>';
  const pc = (x) => Math.round(x * 100) + '%', w = (x) => Math.max(1, Math.round(x * 90));
  const tbl = (d) => `<h3>${E(d.name)}</h3><table><tr><th></th><th>条数</th><th>会用上</th><th>很受用及以上</th><th>没增量</th><th>平均受用（0–3）</th></tr>${d.rows.map((r) => `<tr><td>${E(r.v)}</td><td>${r.n}</td><td><i class="bar" style="width:${w(r.try)}px"></i>${pc(r.try)}</td><td><i class="bar" style="width:${w(r.useful)}px;opacity:.55"></i>${pc(r.useful)}</td><td><i class="bar k" style="width:${w(r.none)}px"></i>${pc(r.none)}</td><td>${r.gain}</td></tr>`).join('')}</table>`;
  const ex = (t, l) => l.length ? `<h3>${t}</h3><ul>${l.map((x) => `<li>${E(x.claim)} <span class="ab-m">· ${E(x.type)} · ${E(x.topic)}</span></li>`).join('')}</ul>` : '';
  return `<div class="ab-fb"><div class="ab-note">共 ${F.n} 条表态：${ACT.map((a) => `${a} ${F.acts[a]}`).join('，')}。受用程度分：没增量 0、有收获 1、很受用 2、会用上 3，取平均。样本少时只看趋势，别当结论；表态存在独立日志里，换选题、重跑都不丢。</div>${F.dims.filter((d) => d.key !== 'topic' || d.rows.length > 1).map(tbl).join('')}${ex('最近判为会用上的', F.try)}${ex('最近判为没增量的（提炼时该少抽这类）', F.none)}</div>`;
}

export default {
  async render(el, ctx) {
    const { api, h, ui, toast, sub } = ctx;
    if (['hn', 'x', 'xart'].includes(sub[0])) { el.append(h('style', {}, CSS)); return hnView(el, ctx, sub[0]); }
    const head = h('div'), body = h('div');
    let timer = null;
    const stop = () => clearTimeout(timer);
    const go = (id) => { location.hash = '#absorb/' + encodeURIComponent(id); };
    const [runs, topics] = await Promise.all([api.get('/api/absorb/runs'), api.get('/api/absorb/topics')]);
    const cur = sub[0] ? decodeURIComponent(sub[0]) : (runs.find((r) => r.done) || runs[0] || {}).id;

    const end = new Date(), start = new Date(Date.now() - 13 * 864e5);
    const fTopic = h('input', { list: 'ab-topics', placeholder: '知识库主题或任意选题', value: '' });
    const fStart = h('input', { type: 'date', value: iso(start) }), fEnd = h('input', { type: 'date', value: iso(end) });
    const pre = h('span.ab-pre'), goBtn = h('button.primary', { onclick: async () => {
      try { go((await api.post('/api/absorb/runs', { topic: fTopic.value, start: fStart.value, end: fEnd.value })).id); } catch (e) { toast(e.message || '发起失败'); }
    } }, '开始吸收');
    const check = async () => {
      const p = await api.get(`/api/absorb/preflight?start=${fStart.value}&end=${fEnd.value}`).catch(() => null);
      if (!p) { pre.textContent = ''; return; }
      const g = p.gaps.map((d) => d.slice(5)).join('、');
      pre.className = 'ab-pre' + (p.classified ? '' : ' bad');
      pre.textContent = p.classified
        ? `这段时间有 ${N(p.classified)} 篇已分类的长文会参与筛选${g ? `；${g} 还没怎么分类，这几天的文章基本进不来` : ''}。两周的量大约 40 分钟、4–5 美元。`
        : `这段时间的长文都还没分类，跑不出结果，换一段更早的时间。`;
      goBtn.disabled = !p.classified;
    };
    fStart.onchange = check; fEnd.onchange = check;
    const form = h('div.ab-new.ab-hide', {}, [
      h('datalist#ab-topics', {}, topics.map((t) => h('option', { value: t }))),
      h('label', {}, ['选题', fTopic]), h('label', {}, ['开始', fStart]), h('label', {}, ['结束', fEnd]),
      goBtn, h('span.ab-m', {}, '跑完留在这里；同一选题和时间窗再点会接着上次的进度。'), pre,
    ]);
    const label = (r) => `${r.topic} · ${r.start.slice(5)}–${r.end.slice(5)}${r.done ? '' : r.running ? ' · 进行中' : ' · 中断'}`;
    const chips = {};
    head.append(h('div.tabs', {}, [h('button.active', {}, '选题吸收'), h('button', { onclick: () => { location.hash = '#absorb/hn'; } }, 'HN 吸收'), h('button', { onclick: () => { location.hash = '#absorb/x'; } }, 'X 反应'), h('button', { onclick: () => { location.hash = '#absorb/xart'; } }, 'X 长文')]), h('div.tabs.ab-sub', {}, [
      ...runs.map((r) => chips[r.id] = h('button', { class: r.id === cur ? 'active' : '', onclick: () => go(r.id) }, label(r))),
      h('button', { onclick: () => { form.classList.toggle('ab-hide'); check(); } }, '＋ 新选题'),
    ]), form);
    el.append(h('style', {}, CSS), ui.pageHead('吸收', '按选题把一段时间的长文压成 know-how 地图和认知卡：领域结构、关键问题的成功做法与失败教训、分歧和失败模式，每条都能追到原文', []), head, body);
    if (!cur) { form.classList.remove('ab-hide'); check(); body.append(ui.empty('还没有跑过的选题，填上面的表单开始第一个')); return; }

    const show = async () => {
      if (!el.isConnected) return stop();
      const r = await api.get('/api/absorb/runs/' + encodeURIComponent(cur));
      if (chips[cur]) chips[cur].textContent = label(r);
      if (!r.data) {
        body.innerHTML = `<div class="ab-run"><b>${E(r.topic)}</b> <span class="ab-m">${E(r.start)} 至 ${E(r.end)}</span>
<div class="ab-prog"><i style="width:${Math.max(2, Math.round((r.step - (r.running ? 0.5 : 0)) / r.steps * 100))}%"></i></div>
<div class="ab-m">${r.running ? (r.step ? `第 ${r.step} / ${r.steps} 步：${E(r.stage_name)} · 已花费 $${r.cost}` : '正在启动') : `停在第 ${r.step} / ${r.steps} 步（${E(r.stage_name)}）：${E(r.error)}`}</div></div>`;
        if (r.running) timer = setTimeout(show, 5000);
        else body.append(h('button.primary', { onclick: async () => { await api.post('/api/absorb/runs', { topic: r.topic, start: r.start, end: r.end }); show(); } }, '接着跑'));
        return;
      }
      paint(r.data, r.reactions, r);
    };

    const paint = (D, R, run) => {
      const M = D.meta, byId = Object.fromEntries(D.cards.map((c) => [c.id, c]));
      let flt = 'all', view = D.synth ? 'kh' : 'brief', sflt = '';
      const acted = (id) => R[id] && (R[id].act || R[id].stars);
      const card = (c) => `<div class="ab-c" data-c="${c.id}"><div class="ab-ch"><span class="ab-tg ${TG[c.tag][1]}">${TG[c.tag][0]}</span><div><div class="ab-cl">${E(c.claim)}</div>${c.scope ? `<div class="ab-sc">适用：${E(c.scope)}</div>` : ''}${vs(c)}${lights(c)}</div></div>
<div class="ab-act">${ACT.map((a, i) => `<button data-a="${a}" title="键盘 ${i + 1}：${ACT_TIP[a]}" class="${R[c.id]?.act === a ? 'on' : ''}">${a}</button>`).join('')}<span class="ab-stars" title="这条整理得好不好用：1 星很差，5 星很好；再点同一颗星取消">${[1, 2, 3, 4, 5].map((n) => `<button data-n="${n}" class="${(R[c.id]?.stars || 0) >= n ? 'on' : ''}">★</button>`).join('')}</span></div><div class="ab-d"></div></div>`;
      const starOk = (c) => !sflt || (sflt === '0' ? !R[c.id]?.stars : (R[c.id]?.stars || 0) >= +sflt);
      const pick = (cs) => (flt === 'todo' ? cs.filter((c) => !acted(c.id)) : flt === 'all' ? cs : cs.filter((c) => c.tag === flt)).filter(starOk);
      const brief = () => D.questions.map((q) => {
        const cs = pick(D.cards.filter((c) => c.qid === q.id));
        if ((flt !== 'all' || sflt) && !cs.length) return '';
        return `<div class="ab-q" data-qid="${q.id}"><h2>${E(q.q)}<span class="ab-st ${ST[q.status] || 'ab-st2'}">${E(q.status)}</span></h2><div class="ab-m">${N(q.n_units)} 条认知 → ${q.n_shown} 张需要看${flt === 'all' && !sflt ? '' : `，这里列出 ${cs.length} 张`}</div>
${q.now ? `<div class="ab-now"><b>现状：</b>${E(q.now).replace(/\[C(\d+)\]/g, (m, n) => `<a data-j="${n}">[${n}]</a>`)}</div>` : ''}
${cs.slice(0, 3).map(card).join('')}<div class="ab-rest ab-hide">${cs.slice(3).map(card).join('')}</div>
${cs.length > 3 ? `<div class="ab-more"><button data-more>再看 ${cs.length - 3} 张</button></div>` : ''}
${flt === 'all' && !sflt && q.fold.length ? `<details class="ab-fold"><summary>另有 ${N(q.fold.length)} 张单一来源的卡（已折叠）</summary><ul>${q.fold.map((f) => `<li>${E(f[0])} <a href="https://x.com/${E(f[1])}/status/${E(f[2])}" target="_blank" rel="noopener">@${E(f[1])}</a></li>`).join('')}</ul></details>` : ''}</div>`;
      }).join('') || ui.empty('这个筛选下没有卡').outerHTML;
      const qmap = () => `<div class="ab-qg">${D.questions.map((q) => {
        const cs = D.cards.filter((c) => c.qid === q.id), t = TAGS.map((k) => [k, cs.filter((c) => c.tag === k).length]).filter((x) => x[1]);
        return `<div class="ab-qc" data-q="${q.id}"><div class="t">${E(q.q)}</div><span class="ab-st ${ST[q.status] || 'ab-st2'}" style="margin:0">${E(q.status)}</span> <span class="ab-m">${N(q.n_units)} 条认知 → ${q.n_shown} 张需要看 · 已表态 ${cs.filter((c) => acted(c.id)).length}</span>
<div class="ab-sb">${t.map(([k, n]) => `<i class="${TG[k][1]}" style="flex:${n}"></i>`).join('')}</div><div class="ab-m">${t.map(([k, n]) => `${TG[k][0]} ${n}`).join(' · ')}</div></div>`;
      }).join('')}</div><p class="ab-m">点一个问题跳到它的卡片。没归到任何问题的认知有 ${N(M.unassigned)} 条。</p>`;
      const done = () => `已表态 ${D.cards.filter((c) => acted(c.id)).length}/${D.cards.length} · 已打星 ${D.cards.filter((c) => R[c.id]?.stars).length}`;
      const T = M.tags || {};
      const draw = () => {
        body.innerHTML = `<div class="ab-m">${E(M.window)} · 抽取与比对由模型完成，未经人工校对${M.minutes ? ` · 耗时 ${M.minutes} 分钟` : ''} · 模型花费 $${M.cost}</div>
<div class="ab-note${view === 'brief' ? '' : ' ab-hide'}">${N(M.units)} 条认知压成 ${N(M.shown)} 张需要看（约 ${M.ratio} : 1）。先看<b>有争议 ${N(T.c)}</b>：来源之间互相冲突；再看<b>高置信 ${N(T.h)}</b>，多个独立来源和硬证据撑着，可以放心用；<b>中置信 ${N(T.m)}</b>和<b>低置信 ${N(T.l)}</b>多为单一或少量来源，用前再核。<span class="ab-key">键盘 <kbd>j</kbd>/<kbd>k</kbd> 逐张，<kbd>1</kbd>–<kbd>4</kbd> 表态（没增量 / 有收获 / 很受用 / 会用上，受用程度由低到高）并跳到下一张，<kbd>o</kbd> 展开原话和证据。</span></div>
<div class="ab-bar">${[['kh', '地图'], ['brief', '卡片'], ['map', '问题'], ['how', '口径'], ['fb', '反馈']].map((x) => `<button data-v="${x[0]}" class="${view === x[0] ? 'on' : ''}">${x[1]}</button>`).join('')}<span class="ab-sp"></span>
${view === 'brief' ? [['all', '全部'], ...TAGS.map((k) => [k, TG[k][0]]), ['todo', '未表态']].map((x) => `<button data-f="${x[0]}" class="${flt === x[0] ? 'on' : ''}">${x[1]}${T[x[0]] ? ' ' + T[x[0]] : ''}</button>`).join('') + `<select data-sf title="按你打的星筛">${[['', '星级：全部'], ['0', '未打星'], ['3', '≥3 星'], ['4', '≥4 星'], ['5', '5 星']].map(([v, l]) => `<option value="${v}"${sflt === v ? ' selected' : ''}>${l}</option>`).join('')}</select><span class="ab-m ab-done">${done()}</span>` : ''}</div>
<div>${view === 'kh' ? kh(D) : view === 'brief' ? brief() : view === 'map' ? qmap() : view === 'how' ? how(D) : '<div class="ab-fb ab-m">加载中</div>'}</div>`;
        if (view === 'fb') api.get('/api/absorb/feedback').then((F) => { const x = body.querySelector('.ab-fb'); if (x) x.outerHTML = fb(F); });
      };
      const open = (id, keep) => {
        const c = body.querySelector(`[data-c="${id}"]`);
        if (!c) return;
        const rest = c.closest('.ab-rest');
        if (rest) { rest.classList.remove('ab-hide'); const m = rest.parentNode.querySelector('.ab-more'); if (m) m.remove(); }
        if (c.classList.contains('open') && !keep) return c.classList.remove('open');
        c.querySelector('.ab-d').innerHTML = detail(byId[id], byId);
        c.classList.add('open');
        if (keep) c.scrollIntoView({ block: 'center' });
      };
      const vis = () => [...body.querySelectorAll('.ab-c')].filter((x) => x.offsetParent);
      const focus = (x) => {
        if (!x) return;
        body.querySelectorAll('.ab-c.cur').forEach((y) => y.classList.remove('cur'));
        x.classList.add('cur');
        x.scrollIntoView({ block: 'nearest' });
      };
      const react = async (c, patch) => {
        const id = c.dataset.c, old = R[id] || {}, nx = { act: old.act || '', stars: old.stars || 0, ...patch };
        for (const k of Object.keys(patch)) if (old[k] === patch[k]) nx[k] = k === 'stars' ? 0 : '';
        try { await api.post(`/api/absorb/runs/${encodeURIComponent(cur)}/react`, { card: +id, act: nx.act, stars: nx.stars }); } catch (err) { toast(err.message || '没存上'); return false; }
        if (nx.act || nx.stars) R[id] = nx; else delete R[id];
        c.querySelectorAll('.ab-act [data-a]').forEach((b) => b.classList.toggle('on', nx.act === b.dataset.a));
        c.querySelectorAll('.ab-act [data-n]').forEach((b) => b.classList.toggle('on', nx.stars >= +b.dataset.n));
        body.querySelector('.ab-done').textContent = done();
        return true;
      };
      const key = async (e) => {
        if (!body.isConnected) return document.removeEventListener('keydown', key);
        if (view !== 'brief' || e.metaKey || e.ctrlKey || e.altKey || e.target.closest('input, textarea, select')) return;
        const L = vis(), c = body.querySelector('.ab-c.cur'), i = L.indexOf(c);
        if (e.key === 'j') focus(L[i + 1] || L[i]);
        else if (e.key === 'k') focus(L[Math.max(0, i - 1)]);
        else if (c && (e.key === 'o' || e.key === 'Enter')) open(c.dataset.c);
        else if (c && ACT[e.key - 1]) { e.preventDefault(); if (await react(c, { act: ACT[e.key - 1] })) focus(L[i + 1] || c); return; }
        else return;
        e.preventDefault();
      };
      document.addEventListener('keydown', key);
      body.onclick = async (e) => {
        const t = e.target, d = t.dataset, q = t.closest('[data-q]');
        if (d.v) { view = d.v; return draw(); }
        if (d.f) { flt = d.f; return draw(); }
        if (d.a) return react(t.closest('.ab-c'), { act: d.a });
        if (d.n) return react(t.closest('.ab-c'), { stars: +d.n });
        if (d.more !== undefined) { t.closest('.ab-q').querySelector('.ab-rest').classList.remove('ab-hide'); return t.parentNode.remove(); }
        if (d.j) { if (view !== 'brief' || flt !== 'all' || sflt) { view = 'brief'; flt = 'all'; sflt = ''; draw(); } return open(d.j, true); }
        if (d.kq) return body.querySelector('#kh-' + d.kq)?.scrollIntoView({ block: 'start' });
        if (d.syn !== undefined) { t.disabled = true; try { await api.post('/api/absorb/runs', { topic: run.topic, start: run.start, end: run.end }); } catch (err) { t.disabled = false; return toast(err.message || '发起失败'); } return show(); }
        if (q) { view = 'brief'; flt = 'all'; sflt = ''; draw(); return body.querySelector(`[data-qid="${q.dataset.q}"]`).scrollIntoView(); }
        const hd = t.closest('.ab-ch');
        if (hd && !t.closest('a')) { focus(hd.parentNode); open(hd.parentNode.dataset.c); }
      };
      body.onchange = (e) => { if (e.target.dataset.sf !== undefined) { sflt = e.target.value; draw(); } };
      draw();
    };
    await show();
  },
};
