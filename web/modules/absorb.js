// 吸收：按选题看一段时间的认知卡。每个问题先看现状，再看挑战你判断的、有争议的、印证你判断的；卡片上直接对照你的判断和对立说法，点开看各作者原话和挂上的证据；键盘 j/k 逐张、1–4 表态。
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
.ab-tj { background: var(--err-soft); color: var(--err); } .ab-tc { background: var(--warn-soft); color: var(--warn); } .ab-ts { background: var(--ok-soft); color: var(--ok); }
.ab-tr { background: var(--bg-2); color: var(--accent); } .ab-tn { background: var(--bg-2); color: var(--muted); }
.ab-cl { font-size: 15px; font-weight: 600; line-height: 1.5; } .ab-sc { color: var(--muted); font-size: 12.5px; }
.ab-vs { font-size: 13px; margin: 5px 0 0; padding: 3px 9px; border-left: 3px solid var(--line-2); background: var(--bg); border-radius: 0 6px 6px 0; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.ab-vs b { font-size: 11.5px; margin-right: 6px; } .ab-c.open .ab-vs { -webkit-line-clamp: unset; }
.ab-v0 { border-left-color: var(--err); } .ab-v0 b { color: var(--err); } .ab-v1 { border-left-color: var(--ok); } .ab-v1 b { color: var(--ok); } .ab-v2 b { color: var(--accent); }
.ab-lt { display: flex; gap: 4px 10px; flex-wrap: wrap; align-items: center; margin-top: 5px; font-size: 12px; color: var(--muted); }
.ab-lt .dt { letter-spacing: 1px; color: var(--dark); } .ab-lt .on { color: var(--ok); font-weight: 600; } .ab-lt .no { color: var(--err); font-weight: 600; }
.ab-act { display: flex; gap: 5px; flex-wrap: wrap; margin: 7px 0 0 72px; }
.ab-act button { font-size: 12px; padding: 1px 10px; }
.ab-act button.on { background: var(--accent); border-color: var(--accent); color: #fff; }
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
.ab-sb .ab-tj { background: var(--err); } .ab-sb .ab-tc { background: var(--warn); } .ab-sb .ab-ts { background: var(--ok); } .ab-sb .ab-tr { background: var(--accent); opacity: .55; } .ab-sb .ab-tn { background: var(--line-2); }
.ab-key { font-size: 12px; color: var(--muted); } .ab-key kbd { font: 11px var(--font); border: 1px solid var(--line); border-bottom-width: 2px; border-radius: 4px; padding: 0 4px; background: var(--panel); }
.ab-pre { font-size: 12.5px; color: var(--muted); flex-basis: 100%; } .ab-pre.bad { color: var(--err); }
.ab-new { display: flex; gap: 8px; flex-wrap: wrap; align-items: end; background: var(--panel); border: 1px solid var(--line); border-radius: var(--radius); padding: 12px 14px; margin: 0 0 14px; }
.ab-new label { display: flex; flex-direction: column; gap: 3px; font-size: 12px; color: var(--muted); }
.ab-new input { min-width: 0; }
.ab-run { background: var(--panel); border: 1px solid var(--line); border-radius: var(--radius); padding: 18px; margin: 12px 0; }
.ab-prog { height: 6px; border-radius: 3px; background: var(--bg-2); overflow: hidden; margin: 10px 0 6px; }
.ab-prog i { display: block; height: 100%; background: var(--accent); }
.ab-hide { display: none; }
@media (max-width: 720px) { .ab-fun { grid-template-columns: repeat(2, 1fr); } .ab-ch { grid-template-columns: 58px minmax(0, 1fr); } .ab-act, .ab-d { margin-left: 0; } .ab-new label { flex: 1 1 120px; } .ab-key { display: none; } .ab-bar { gap: 4px; } .ab-bar button { padding: 2px 9px; } .ab-qg { grid-template-columns: 1fr; } }
`;

const E = (s) => (s == null ? '' : String(s)).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const N = (n) => (n || 0).toLocaleString();
const TG = { j: ['挑战判断', 'ab-tj'], c: ['有争议', 'ab-tc'], s: ['印证判断', 'ab-ts'], r: ['相关判断', 'ab-tr'], n: ['新的', 'ab-tn'] };
const TAGS = Object.keys(TG);
const REL = { 相反: ['它反驳了你的判断', 'ab-v0'], 一致: ['它支持你的判断', 'ab-v1'], 补充: ['它补充你的判断', 'ab-v2'] };
const ACT = ['已知', '采纳', '不信', '想试'];
const ST = { 共识为主: 'ab-st0', 有分歧: 'ab-st1', 证据少: 'ab-st2' };
const POOL = { papers: '论文', repos: '开源项目', intel: '产品动态', disc: '讨论' };
const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;

function lights(c) {
  const n = (k) => c.ev.filter((e) => e.pool === k && e.v === '佐证').length;
  const a = c.ev.filter((e) => e.v === '反对').length + c.conf.length, k = c.src.filter((u) => u.kind === '实践者' || u.kind === '官方').length;
  const L = [[n('papers'), '篇论文佐证'], [n('repos'), '个项目实现了'], [n('intel'), '个产品这么做'], [n('disc'), '条讨论佐证']].filter((x) => x[0]);
  return `<div class="ab-lt"><span><span class="dt">${'●'.repeat(Math.min(5, c.authors.length))}</span> ${c.authors.length} 位作者${k ? `，${k} 位一手` : ''}</span>${L.map((x) => `<span class="on">${x[0]} ${x[1]}</span>`).join('')}${a ? `<span class="no">${a} 处反对</span>` : ''}</div>`;
}

function vs(c) {
  const j = c.judg[0], x = c.conf[0];
  return (j ? `<div class="ab-vs ${REL[j.rel] ? REL[j.rel][1] : ''}"><b>${REL[j.rel] ? REL[j.rel][0] : j.rel}</b>${E(j.text)}${c.judg.length > 1 ? ` <span class="ab-m">另 ${c.judg.length - 1} 条</span>` : ''}</div>` : '')
    + (x ? `<div class="ab-vs ab-v0"><b>有人说相反</b>${E(x.claim)} <span class="ab-m">分歧：${E(x.point)}</span></div>` : '');
}

function detail(c, byId) {
  let s = '';
  if (c.judg.length > 1) s += '<h5>碰到的你已有的判断</h5>' + c.judg.map((j) => `<div class="ab-e"><span class="v ${j.rel === '相反' ? 'v0' : 'v1'}">${j.rel}</span>${E(j.text)} <span class="ab-m">· ${E(j.concept)} · ${E(j.date)}</span></div>`).join('');
  if (c.conf.length) s += '<h5>与它矛盾的说法</h5>' + c.conf.map((x) => `<div class="ab-e"><span class="v v0">矛盾</span>${E(byId[x.o] ? byId[x.o].claim : x.claim)} <span class="ab-m">· 分歧点：${E(x.point)}</span></div>`).join('');
  s += '<h5>各作者的说法（按时间）</h5>' + c.src.map((u) => `<div class="ab-s"><a href="${E(u.url)}" target="_blank" rel="noopener">@${E(u.user)}</a> <span class="ab-m">${E(u.day.slice(5))} · ${E(u.kind)}</span>${u.gain ? ` <span class="g">＋${E(u.gain)}</span>` : ''}<br>${E(u.claim)}<br><q>${E(u.quote)}</q></div>`).join('');
  if (c.ev.length) s += '<h5>其他来源的证据</h5>' + c.ev.map((e) => `<div class="ab-e"><span class="v ${e.v === '反对' ? 'v0' : 'v1'}">${POOL[e.pool]}·${e.v}</span>${/^https?:/.test(e.url) ? `<a href="${E(e.url)}" target="_blank" rel="noopener">${E(e.title)}</a>` : E(e.title)} <span class="ab-m">${E(e.date)}${e.pool === 'repos' ? ` · ★${N(e.meta)}` : e.pool === 'papers' ? (e.meta ? ` · 引用 ${e.meta}` : '') : e.meta ? ` · ${E(e.meta)}` : ''} · ${E(e.why)}</span></div>`).join('');
  return s;
}

function how(D) {
  const M = D.meta, P = D.profile, r = M.rel || {}, p = M.pools || {};
  return `<div class="ab-fun">${[[M.scanned, '相关领域长文'], [M.theme, '属于这个选题'], [M.extracted, `质量分≥${M.min_q}，已抽取`], [M.units, '条认知（引文已核对）'], [M.cards, '张认知卡']].map((x) => `<div><b>${N(x[0])}</b><span>${x[1]}</span></div>`).join('')}
<div class="hl"><b>${N(M.shown)}</b><span>张需要看</span></div><div><b>${N(M.multi)}</b><span>其中多人印证</span></div><div><b>${N(M.conf)}</b><span>对已复核的矛盾</span></div><div><b>${N(M.jrel)}</b><span>张碰到你已有判断</span></div><div><b>${N(M.evcards)}</b><span>张挂上了其他来源证据</span></div></div>
<div class="ab-q"><h2>这页是怎么算出来的</h2>
<p><b>选题范围：</b>${E(P.scope)}</p><p><b>不算：</b>${E(P.exclude)}</p>
<p><b>筛选：</b>${E(M.window)} 长文库相关领域共 ${N(M.scanned)} 篇，模型判定属于这个选题的 ${N(M.theme)} 篇，其中质量分≥${M.min_q} 的 ${N(M.extracted)} 篇做了抽取。</p>
<p><b>抽取：</b>共 ${N(M.units)} 条认知，每条带一句原文引文，引文在原文里找不到的 ${N(M.quote_bad)} 条已丢弃；${N(M.unassigned)} 条没归到任何问题。</p>
<p><b>合并：</b>同一问题内向量相近的 ${N(M.pairs)} 对交给模型判断：重复 ${N(r['重复'])}、增益 ${N(r['增益'])}、反驳 ${N(r['反驳'])}、不同 ${N(r['不同'])}。重复和增益合成一张卡，共 ${N(M.cards)} 张；反驳经更强的模型复核，成立 ${N(M.conf)} 对。合并判得偏严，说法相近但结论不完全相同的不会合并。</p>
<p><b>需要看的 ${N(M.shown)} 张：</b>两个以上独立作者都说的、碰到你已有判断的、复核成立的矛盾双方，再加每个问题最多 3 张质量分≥4 的实践者或官方单来源卡。其余 ${N(M.folded)} 张单一来源卡折叠在各问题末尾。</p>
<p><b>你已有的判断：</b>取自${E(M.judg_scope)}的“我的判断”，共 ${N(p.judg)} 条。</p>
<p><b>证据池：</b>论文 ${N(p.papers)} 篇、开源项目 ${N(p.repos)} 个、产品动态 ${N(p.intel)} 条、讨论 ${N(p.disc)} 条；每张卡每类取向量最相近的 4 条，由模型逐条判为佐证、反对或无关，只留前两种。</p>
<p><b>标签：</b>挑战判断 = 与你已有的某条判断结论相反；有争议 = 有复核成立的对立说法，或论文 / 项目 / 产品 / 讨论里有反对证据；印证判断 = 与你的判断一致，且有两个以上独立作者或有论文 / 项目 / 产品佐证；相关判断 = 与你的判断一致但只有单一来源，或在你的判断上补充了数据、条件、做法；新的 = 没碰到你已有的判断。一张卡只取最靠前的一个标签。</p>
<p class="ab-m">抽取、合并、挂证据都由模型完成，没有人工校对；${M.fails ? `有 ${M.fails} 次模型调用重试后仍失败，对应的那批按“不属于 / 不同 / 无关”处理；` : ''}${M.minutes ? `耗时 ${M.minutes} 分钟，` : ''}模型花费 $${M.cost}（按接口价折算）。</p></div>`;
}

export default {
  async render(el, ctx) {
    const { api, h, ui, toast, sub } = ctx;
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
    head.append(h('div.tabs', {}, [
      ...runs.map((r) => chips[r.id] = h('button', { class: r.id === cur ? 'active' : '', onclick: () => go(r.id) }, label(r))),
      h('button', { onclick: () => { form.classList.toggle('ab-hide'); check(); } }, '＋ 新选题'),
    ]), form);
    el.append(h('style', {}, CSS), ui.pageHead('吸收', '按选题把一段时间的长文压成认知卡：每个问题先看现状，再看哪些挑战或加强了你已有的判断', []), head, body);
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
      paint(r.data, Object.fromEntries(Object.entries(r.reactions).map(([k, v]) => [k, v.act])));
    };

    const paint = (D, R) => {
      const M = D.meta, byId = Object.fromEntries(D.cards.map((c) => [c.id, c]));
      let flt = 'all', view = 'brief';
      const card = (c) => `<div class="ab-c" data-c="${c.id}"><div class="ab-ch"><span class="ab-tg ${TG[c.tag][1]}">${TG[c.tag][0]}</span><div><div class="ab-cl">${E(c.claim)}</div>${c.scope ? `<div class="ab-sc">适用：${E(c.scope)}</div>` : ''}${vs(c)}${lights(c)}</div></div>
<div class="ab-act">${ACT.map((a, i) => `<button data-a="${a}" title="键盘 ${i + 1}" class="${R[c.id] === a ? 'on' : ''}">${a}</button>`).join('')}</div><div class="ab-d"></div></div>`;
      const pick = (cs) => flt === 'todo' ? cs.filter((c) => !R[c.id]) : flt === 'all' ? cs : cs.filter((c) => c.tag === flt);
      const brief = () => D.questions.map((q) => {
        const cs = pick(D.cards.filter((c) => c.qid === q.id));
        if (flt !== 'all' && !cs.length) return '';
        return `<div class="ab-q" data-qid="${q.id}"><h2>${E(q.q)}<span class="ab-st ${ST[q.status] || 'ab-st2'}">${E(q.status)}</span></h2><div class="ab-m">${N(q.n_units)} 条认知 → ${q.n_shown} 张需要看${flt === 'all' ? '' : `，这里列出 ${cs.length} 张`}</div>
${q.now ? `<div class="ab-now"><b>现状：</b>${E(q.now).replace(/\[C(\d+)\]/g, (m, n) => `<a data-j="${n}">[${n}]</a>`)}</div>` : ''}
${cs.slice(0, 3).map(card).join('')}<div class="ab-rest ab-hide">${cs.slice(3).map(card).join('')}</div>
${cs.length > 3 ? `<div class="ab-more"><button data-more>再看 ${cs.length - 3} 张</button></div>` : ''}
${flt === 'all' && q.fold.length ? `<details class="ab-fold"><summary>另有 ${N(q.fold.length)} 张单一来源的卡（已折叠）</summary><ul>${q.fold.map((f) => `<li>${E(f[0])} <a href="https://x.com/${E(f[1])}/status/${E(f[2])}" target="_blank" rel="noopener">@${E(f[1])}</a></li>`).join('')}</ul></details>` : ''}</div>`;
      }).join('') || ui.empty('这个筛选下没有卡').outerHTML;
      const qmap = () => `<div class="ab-qg">${D.questions.map((q) => {
        const cs = D.cards.filter((c) => c.qid === q.id), t = TAGS.map((k) => [k, cs.filter((c) => c.tag === k).length]).filter((x) => x[1]);
        return `<div class="ab-qc" data-q="${q.id}"><div class="t">${E(q.q)}</div><span class="ab-st ${ST[q.status] || 'ab-st2'}" style="margin:0">${E(q.status)}</span> <span class="ab-m">${N(q.n_units)} 条认知 → ${q.n_shown} 张需要看 · 已表态 ${cs.filter((c) => R[c.id]).length}</span>
<div class="ab-sb">${t.map(([k, n]) => `<i class="${TG[k][1]}" style="flex:${n}"></i>`).join('')}</div><div class="ab-m">${t.map(([k, n]) => `${TG[k][0]} ${n}`).join(' · ')}</div></div>`;
      }).join('')}</div><p class="ab-m">点一个问题跳到它的卡片。没归到任何问题的认知有 ${N(M.unassigned)} 条。</p>`;
      const done = () => `已表态 ${D.cards.filter((c) => R[c.id]).length}/${D.cards.length}`;
      const T = M.tags || {};
      const draw = () => {
        body.innerHTML = `<div class="ab-m">${E(M.window)} · 抽取与比对由模型完成，未经人工校对${M.minutes ? ` · 耗时 ${M.minutes} 分钟` : ''} · 模型花费 $${M.cost}</div>
<div class="ab-note">${N(M.units)} 条认知压成 ${N(M.shown)} 张需要看（约 ${M.ratio} : 1）。先看<b>挑战判断 ${N(T.j)}</b>和<b>有争议 ${N(T.c)}</b>：它们和你已有的判断或彼此冲突；再看<b>印证判断 ${N(T.s)}</b>，可以放心用。<span class="ab-key">键盘 <kbd>j</kbd>/<kbd>k</kbd> 逐张，<kbd>1</kbd>–<kbd>4</kbd> 表态并跳到下一张，<kbd>o</kbd> 展开原话和证据。</span></div>
<div class="ab-bar">${[['brief', '卡片'], ['map', '问题'], ['how', '口径']].map((x) => `<button data-v="${x[0]}" class="${view === x[0] ? 'on' : ''}">${x[1]}</button>`).join('')}<span class="ab-sp"></span>
${view === 'brief' ? [['all', '全部'], ...TAGS.map((k) => [k, TG[k][0]]), ['todo', '未表态']].map((x) => `<button data-f="${x[0]}" class="${flt === x[0] ? 'on' : ''}">${x[1]}${T[x[0]] ? ' ' + T[x[0]] : ''}</button>`).join('') + `<span class="ab-m ab-done">${done()}</span>` : ''}</div>
<div>${view === 'brief' ? brief() : view === 'map' ? qmap() : how(D)}</div>`;
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
      const react = async (c, a) => {
        const id = c.dataset.c, act = R[id] === a ? '' : a;
        try { await api.post(`/api/absorb/runs/${encodeURIComponent(cur)}/react`, { card: +id, act }); } catch (err) { toast(err.message || '没存上'); return false; }
        if (act) R[id] = act; else delete R[id];
        c.querySelectorAll('.ab-act button').forEach((b) => b.classList.toggle('on', R[id] === b.dataset.a));
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
        else if (c && ACT[e.key - 1]) { e.preventDefault(); if (await react(c, ACT[e.key - 1])) focus(L[i + 1] || c); return; }
        else return;
        e.preventDefault();
      };
      document.addEventListener('keydown', key);
      body.onclick = async (e) => {
        const t = e.target, d = t.dataset, q = t.closest('[data-q]');
        if (d.v) { view = d.v; return draw(); }
        if (d.f) { flt = d.f; return draw(); }
        if (d.a) return react(t.closest('.ab-c'), d.a);
        if (d.more !== undefined) { t.closest('.ab-q').querySelector('.ab-rest').classList.remove('ab-hide'); return t.parentNode.remove(); }
        if (d.j) { if (flt !== 'all') { flt = 'all'; draw(); } return open(d.j, true); }
        if (q) { view = 'brief'; flt = 'all'; draw(); return body.querySelector(`[data-qid="${q.dataset.q}"]`).scrollIntoView(); }
        const hd = t.closest('.ab-ch');
        if (hd && !t.closest('a')) { focus(hd.parentNode); open(hd.parentNode.dataset.c); }
      };
      draw();
    };
    await show();
  },
};
