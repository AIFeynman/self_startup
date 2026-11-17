// 吸收：按选题看一段时间的认知卡。先看每个问题的现状，再看被挑战 / 被加强 / 新的；点卡片看各作者原话和挂上的证据，四个按钮表态。
const CSS = `
.ab-fun { display: grid; grid-template-columns: repeat(5, 1fr); gap: 8px; margin: 12px 0; }
.ab-fun div { background: var(--panel); border: 1px solid var(--line); border-radius: var(--radius-sm); padding: 8px 10px; }
.ab-fun b { display: block; font-size: 21px; font-variant-numeric: tabular-nums; }
.ab-fun span { font-size: 12px; color: var(--muted); }
.ab-fun .hl { border: 2px solid var(--accent); }
.ab-note { background: var(--panel); border: 1px solid var(--line); border-left: 4px solid var(--warn); border-radius: 8px; padding: 8px 12px; font-size: 13.5px; margin: 10px 0; }
.ab-bar { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; margin: 14px 0 8px; padding: 8px 0; position: sticky; top: 0; z-index: 5; background: var(--bg); border-bottom: 1px solid var(--line); }
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
.ab-c { border-top: 1px solid var(--line); padding: 8px 0; }
.ab-ch { display: grid; grid-template-columns: 58px minmax(0, 1fr); gap: 8px; cursor: pointer; }
.ab-tg { font-size: 11px; font-weight: 700; border-radius: 4px; height: 20px; line-height: 20px; text-align: center; margin-top: 2px; }
.ab-tn { background: var(--bg-2); color: var(--muted); } .ab-ts { background: var(--ok-soft); color: var(--ok); } .ab-tc { background: var(--err-soft); color: var(--err); }
.ab-cl { font-size: 14.5px; } .ab-sc { color: var(--muted); font-size: 12.5px; }
.ab-lt { display: flex; gap: 4px; flex-wrap: wrap; margin-top: 3px; }
.ab-lt span { font-size: 11px; border: 1px solid var(--line); border-radius: 999px; padding: 0 7px; color: var(--muted); }
.ab-lt .on { background: var(--ok-soft); color: var(--ok); border-color: transparent; } .ab-lt .no { background: var(--err-soft); color: var(--err); border-color: transparent; }
.ab-act { display: flex; gap: 5px; flex-wrap: wrap; margin: 6px 0 0 66px; }
.ab-act button { font-size: 12px; padding: 1px 10px; }
.ab-act button.on { background: var(--accent); border-color: var(--accent); color: #fff; }
.ab-d { margin: 8px 0 2px 66px; font-size: 13px; display: none; overflow-wrap: anywhere; }
.ab-c.open .ab-d { display: block; }
.ab-d h5 { margin: 8px 0 3px; font-size: 12px; color: var(--muted); font-weight: 600; }
.ab-s { border-left: 3px solid var(--line-2); padding: 2px 0 2px 9px; margin: 4px 0; }
.ab-s q { color: var(--muted); quotes: "“" "”"; } .ab-s .g { color: var(--ok); }
.ab-e { padding: 2px 0; } .ab-e .v { font-size: 11px; font-weight: 700; margin-right: 4px; } .ab-e .v1 { color: var(--ok); } .ab-e .v0 { color: var(--err); }
.ab-more { margin: 6px 0 0; }
.ab-fold { font-size: 13px; color: var(--muted); margin-top: 6px; } .ab-fold summary { cursor: pointer; } .ab-fold li { margin: 2px 0; }
.ab-tw { overflow-x: auto; }
.ab-tw table { border-collapse: collapse; width: 100%; font-size: 13px; background: var(--panel); border: 1px solid var(--line); }
.ab-tw th, .ab-tw td { border-top: 1px solid var(--line); padding: 6px 8px; text-align: left; vertical-align: top; }
.ab-tw th { border-top: 0; color: var(--muted); font-size: 12px; white-space: nowrap; }
.ab-tw td.n { text-align: right; font-variant-numeric: tabular-nums; } .ab-tw td a { cursor: pointer; }
.ab-new { display: flex; gap: 8px; flex-wrap: wrap; align-items: end; background: var(--panel); border: 1px solid var(--line); border-radius: var(--radius); padding: 12px 14px; margin: 0 0 14px; }
.ab-new label { display: flex; flex-direction: column; gap: 3px; font-size: 12px; color: var(--muted); }
.ab-new input { min-width: 0; }
.ab-run { background: var(--panel); border: 1px solid var(--line); border-radius: var(--radius); padding: 18px; margin: 12px 0; }
.ab-prog { height: 6px; border-radius: 3px; background: var(--bg-2); overflow: hidden; margin: 10px 0 6px; }
.ab-prog i { display: block; height: 100%; background: var(--accent); }
.ab-hide { display: none; }
@media (max-width: 720px) { .ab-fun { grid-template-columns: repeat(2, 1fr); } .ab-ch { grid-template-columns: 52px minmax(0, 1fr); } .ab-act, .ab-d { margin-left: 0; } .ab-new label { flex: 1 1 120px; } }
`;

const E = (s) => (s == null ? '' : String(s)).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const N = (n) => (n || 0).toLocaleString();
const TG = { n: ['新的', 'ab-tn'], s: ['被加强', 'ab-ts'], c: ['被挑战', 'ab-tc'] };
const ACT = ['已知', '采纳', '不信', '想试'];
const ST = { 共识为主: 'ab-st0', 有分歧: 'ab-st1', 证据少: 'ab-st2' };
const POOL = { papers: '论文', repos: '开源项目', intel: '产品动态', disc: '讨论' };
const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;

function lights(c) {
  const n = (k) => c.ev.filter((e) => e.pool === k && e.v === '佐证').length;
  const a = c.ev.filter((e) => e.v === '反对').length + c.conf.length;
  const L = [['有人这么做', c.authors.length, '个作者'], ['有数据', n('papers'), '篇论文'], ['有人做出来', n('repos'), '个项目'], ['有人买单', n('intel'), '个产品'], ['有讨论佐证', n('disc'), '条讨论']];
  return `<div class="ab-lt">${L.map((x) => `<span class="${x[1] ? 'on' : ''}">${x[1] ? `${x[1]} ${x[2]}` : x[0]}</span>`).join('')}${a ? `<span class="no">${a} 处反对</span>` : ''}</div>`;
}

function detail(c, byId) {
  let s = '';
  if (c.judg.length) s += '<h5>你已有的判断</h5>' + c.judg.map((j) => `<div class="ab-e"><span class="v ${j.rel === '相反' ? 'v0' : 'v1'}">${j.rel}</span>${E(j.text)} <span class="ab-m">· ${E(j.concept)} · ${E(j.date)}</span></div>`).join('');
  if (c.conf.length) s += '<h5>与它矛盾的说法</h5>' + c.conf.map((x) => `<div class="ab-e"><span class="v v0">矛盾</span>${E(byId[x.o] ? byId[x.o].claim : x.claim)} <span class="ab-m">· 分歧点：${E(x.point)}</span></div>`).join('');
  s += '<h5>各作者的说法（按时间）</h5>' + c.src.map((u) => `<div class="ab-s"><a href="${E(u.url)}" target="_blank" rel="noopener">@${E(u.user)}</a> <span class="ab-m">${E(u.day.slice(5))} · ${E(u.kind)}</span>${u.gain ? ` <span class="g">＋${E(u.gain)}</span>` : ''}<br>${E(u.claim)}<br><q>${E(u.quote)}</q></div>`).join('');
  if (c.ev.length) s += '<h5>其他来源的证据</h5>' + c.ev.map((e) => `<div class="ab-e"><span class="v ${e.v === '反对' ? 'v0' : 'v1'}">${POOL[e.pool]}·${e.v}</span>${/^https?:/.test(e.url) ? `<a href="${E(e.url)}" target="_blank" rel="noopener">${E(e.title)}</a>` : E(e.title)} <span class="ab-m">${E(e.date)}${e.pool === 'repos' ? ` · ★${N(e.meta)}` : e.pool === 'papers' ? (e.meta ? ` · 引用 ${e.meta}` : '') : e.meta ? ` · ${E(e.meta)}` : ''} · ${E(e.why)}</span></div>`).join('');
  return s;
}

function how(D) {
  const M = D.meta, P = D.profile, r = M.rel || {}, p = M.pools || {};
  return `<div class="ab-q"><h2>这页是怎么算出来的</h2>
<p><b>选题范围：</b>${E(P.scope)}</p><p><b>不算：</b>${E(P.exclude)}</p>
<p><b>筛选：</b>${E(M.window)} 长文库相关领域共 ${N(M.scanned)} 篇，模型判定属于这个选题的 ${N(M.theme)} 篇，其中质量分≥${M.min_q} 的 ${N(M.extracted)} 篇做了抽取。</p>
<p><b>抽取：</b>共 ${N(M.units)} 条认知，每条带一句原文引文，引文在原文里找不到的 ${N(M.quote_bad)} 条已丢弃；${N(M.unassigned)} 条没归到任何问题。</p>
<p><b>合并：</b>同一问题内向量相近的 ${N(M.pairs)} 对交给模型判断：重复 ${N(r['重复'])}、增益 ${N(r['增益'])}、反驳 ${N(r['反驳'])}、不同 ${N(r['不同'])}。重复和增益合成一张卡，共 ${N(M.cards)} 张；反驳经更强的模型复核，成立 ${N(M.conf)} 对。合并判得偏严，说法相近但结论不完全相同的不会合并。</p>
<p><b>需要看的 ${N(M.shown)} 张：</b>两个以上独立作者都说的、碰到你已有判断的、复核成立的矛盾双方，再加每个问题最多 3 张质量分≥4 的实践者或官方单来源卡。其余 ${N(M.folded)} 张单一来源卡折叠在各问题末尾。</p>
<p><b>你已有的判断：</b>取自${E(M.judg_scope)}的“我的判断”，共 ${N(p.judg)} 条。</p>
<p><b>证据池：</b>论文 ${N(p.papers)} 篇、开源项目 ${N(p.repos)} 个、产品动态 ${N(p.intel)} 条、讨论 ${N(p.disc)} 条；每张卡每类取向量最相近的 4 条，由模型逐条判为佐证、反对或无关，只留前两种。</p>
<p><b>标签：</b>被挑战 = 有复核成立的矛盾、与你的判断相反或有反对证据；被加强 = 与你的判断一致或补充；新的 = 其余。</p>
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
    const form = h('div.ab-new.ab-hide', {}, [
      h('datalist#ab-topics', {}, topics.map((t) => h('option', { value: t }))),
      h('label', {}, ['选题', fTopic]), h('label', {}, ['开始', fStart]), h('label', {}, ['结束', fEnd]),
      h('button.primary', { onclick: async () => {
        try { go((await api.post('/api/absorb/runs', { topic: fTopic.value, start: fStart.value, end: fEnd.value })).id); } catch (e) { toast(e.message || '发起失败'); }
      } }, '开始吸收'),
      h('span.ab-m', {}, '两周的量大约 40–60 分钟，跑完留在这里；同一选题和时间窗再点会接着上次的进度。'),
    ]);
    head.append(h('div.tabs', {}, [
      ...runs.map((r) => h('button', { class: r.id === cur ? 'active' : '', onclick: () => go(r.id) }, `${r.topic} · ${r.start.slice(5)}–${r.end.slice(5)}${r.done ? '' : r.running ? ' · 进行中' : ' · 中断'}`)),
      h('button', { onclick: () => form.classList.toggle('ab-hide') }, '＋ 新选题'),
    ]), form);
    el.append(h('style', {}, CSS), ui.pageHead('吸收', '按选题把一段时间的长文压成认知卡：每个问题先看现状，再看哪些挑战或加强了你已有的判断', []), head, body);
    if (!cur) { form.classList.remove('ab-hide'); body.append(ui.empty('还没有跑过的选题，填上面的表单开始第一个')); return; }

    const show = async () => {
      if (!el.isConnected) return stop();
      const r = await api.get('/api/absorb/runs/' + encodeURIComponent(cur));
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
      const card = (c) => `<div class="ab-c" data-c="${c.id}"><div class="ab-ch"><span class="ab-tg ${TG[c.tag][1]}">${TG[c.tag][0]}</span><div><div class="ab-cl">${E(c.claim)}</div>${c.scope ? `<div class="ab-sc">适用：${E(c.scope)}</div>` : ''}${lights(c)}</div></div>
<div class="ab-act">${ACT.map((a) => `<button data-a="${a}" class="${R[c.id] === a ? 'on' : ''}">${a}</button>`).join('')}</div><div class="ab-d"></div></div>`;
      const brief = () => D.questions.map((q) => {
        let cs = D.cards.filter((c) => c.qid === q.id);
        if (flt === 'todo') cs = cs.filter((c) => !R[c.id]); else if (flt !== 'all') cs = cs.filter((c) => c.tag === flt);
        return `<div class="ab-q" data-qid="${q.id}"><h2>${E(q.q)}<span class="ab-st ${ST[q.status] || 'ab-st2'}">${E(q.status)}</span></h2><div class="ab-m">${N(q.n_units)} 条认知 · ${N(q.n_cards)} 张卡 · 需要看 ${q.n_shown} 张</div>
${q.now ? `<div class="ab-now"><b>现状：</b>${E(q.now).replace(/\[C(\d+)\]/g, (m, n) => `<a data-j="${n}">[${n}]</a>`)}</div>` : ''}
${cs.slice(0, 6).map(card).join('')}<div class="ab-rest ab-hide">${cs.slice(6).map(card).join('')}</div>
${cs.length > 6 ? `<div class="ab-more"><button data-more>展开其余 ${cs.length - 6} 条</button></div>` : ''}
<details class="ab-fold"><summary>另有 ${N(q.fold.length)} 张单一来源的卡（已折叠）</summary><ul>${q.fold.map((f) => `<li>${E(f[0])} <a href="https://x.com/${E(f[1])}/status/${E(f[2])}" target="_blank" rel="noopener">@${E(f[1])}</a></li>`).join('')}</ul></details></div>`;
      }).join('');
      const map = () => `<div class="ab-tw"><table><tr><th>问题</th><th>状态</th><th>认知</th><th>卡</th><th>需要看</th><th>多人印证</th><th>矛盾</th><th>论文</th><th>项目</th><th>产品</th><th>讨论</th></tr>${D.questions.map((q) => `<tr><td><a data-q="${q.id}">${E(q.q)}</a></td><td>${E(q.status)}</td>${[q.n_units, q.n_cards, q.n_shown, q.n_multi, q.n_conf, q.ev.papers, q.ev.repos, q.ev.intel, q.ev.disc].map((x) => `<td class="n">${N(x)}</td>`).join('')}</tr>`).join('')}</table></div>
<p class="ab-m">论文、项目、产品、讨论四列是挂到该问题下“需要看”的卡上、经模型判为佐证或反对的条数。没归到任何问题的认知有 ${N(M.unassigned)} 条。</p>`;
      const done = () => `已表态 ${D.cards.filter((c) => R[c.id]).length}/${D.cards.length}`;
      const draw = () => {
        body.innerHTML = `<div class="ab-m">${E(M.window)} · 抽取与比对由模型完成，未经人工校对${M.minutes ? ` · 耗时 ${M.minutes} 分钟` : ''} · 模型花费 $${M.cost}</div>
<div class="ab-fun">${[[M.scanned, '相关领域长文'], [M.theme, '属于这个选题'], [M.extracted, `质量分≥${M.min_q}，已抽取`], [M.units, '条认知（引文已核对）'], [M.cards, '张认知卡']].map((x) => `<div><b>${N(x[0])}</b><span>${x[1]}</span></div>`).join('')}
<div class="hl"><b>${N(M.shown)}</b><span>张需要看</span></div><div><b>${N(M.multi)}</b><span>其中多人印证</span></div><div><b>${N(M.conf)}</b><span>对已复核的矛盾</span></div><div><b>${N(M.jrel)}</b><span>张碰到你已有判断</span></div><div><b>${N(M.evcards)}</b><span>张挂上了其他来源证据</span></div></div>
<div class="ab-note"><b>压缩比：</b>${N(M.units)} 条认知 → ${N(M.shown)} 张需要看，约 ${M.ratio} : 1；另有 ${N(M.folded)} 张单一来源的卡折叠在各问题末尾。点一条看每个作者的原话和原文链接、挂上的论文 / 项目 / 产品 / 讨论。</div>
<div class="ab-bar">${[['brief', '变化简报'], ['map', '问题地图'], ['how', '口径说明']].map((x) => `<button data-v="${x[0]}" class="${view === x[0] ? 'on' : ''}">${x[1]}</button>`).join('')}<span class="ab-sp"></span>
${view === 'brief' ? [['all', '全部'], ['c', '被挑战'], ['s', '被加强'], ['n', '新的'], ['todo', '未表态']].map((x) => `<button data-f="${x[0]}" class="${flt === x[0] ? 'on' : ''}">${x[1]}${M.tags && M.tags[x[0]] ? ' ' + M.tags[x[0]] : ''}</button>`).join('') + `<span class="ab-m ab-done">${done()}</span>` : ''}</div>
<div>${view === 'brief' ? brief() : view === 'map' ? map() : how(D)}</div>`;
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
      body.onclick = async (e) => {
        const t = e.target, d = t.dataset;
        if (d.v) { view = d.v; return draw(); }
        if (d.f) { flt = d.f; return draw(); }
        if (d.a) {
          const id = t.closest('.ab-c').dataset.c, act = R[id] === d.a ? '' : d.a;
          try { await api.post(`/api/absorb/runs/${encodeURIComponent(cur)}/react`, { card: +id, act }); } catch (err) { return toast(err.message || '没存上'); }
          if (act) R[id] = act; else delete R[id];
          t.parentNode.querySelectorAll('button').forEach((b) => b.classList.toggle('on', R[id] === b.dataset.a));
          body.querySelector('.ab-done').textContent = done();
          return;
        }
        if (d.more !== undefined) { t.closest('.ab-q').querySelector('.ab-rest').classList.remove('ab-hide'); return t.parentNode.remove(); }
        if (d.j) { if (flt !== 'all') { flt = 'all'; draw(); } return open(d.j, true); }
        if (d.q) { view = 'brief'; draw(); return body.querySelector(`[data-qid="${d.q}"]`).scrollIntoView(); }
        const hd = t.closest('.ab-ch');
        if (hd && !t.closest('a')) open(hd.parentNode.dataset.c);
      };
      draw();
    };
    await show();
  },
};
