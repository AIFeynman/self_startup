// 今日板块的子页：深度 / 动手 / 学 / 台账 / 画像。接口在 /api/today/*（app/modules/_today_tabs.py）。
const MEMO = [['conclusion', '结论', '第一句就是结论'], ['why', '为什么（机制）', '讲清为什么这样，而不只是它做了什么'],
  ['numbers', '数字', '至少一个估算或对比，数量级也行'], ['verify', '怎么验证', '什么实验或数据能证明或推翻它'],
  ['transfer', '对我的项目', '用在哪、边界在哪']];
const OPP_NAME = { idea: '想到', written: '写透', tested: '验证过', dropped: '放弃', pushing: '推进' };
const ext = (h, url, text) => h('a', url.startsWith('#') ? { href: url } : { href: url, target: '_blank', rel: 'noopener' }, text);
const field = (h, ph, value = '', rows = 2) => { const t = h('textarea', { rows, placeholder: ph, 'aria-label': ph }); t.value = value; return t; };

// ---------- 深度 ----------
export async function renderDeep(el, { api, h, toast, ui, openChat }) {
  const reload = async () => { el.replaceChildren(); await renderDeep(el, { api, h, toast, ui, openChat }); };
  const d = await api.get('/api/today/deep');
  const box = h('div');
  el.append(box);
  if (!d.topic) {
    const custom = h('input', { placeholder: '或者自己写一个主题', 'aria-label': '自定主题' });
    box.append(h('div.card', {}, [
      h('div.card-label', {}, `本周（${d.week} 起）还没有深度主题`),
      h('p.muted', {}, '每周只钻一个主题，每天 60 分钟：读 → 写 → 辩 → 记。候选优先来自你自己问过、还没解决的问题。'),
      ...d.candidates.map((c) => h('div.td-cand', {}, [h('div', {}, [h('b', {}, c.title), c.why ? h('div.muted', {}, c.why) : null]),
        h('button.primary', { onclick: async () => { await api.post('/api/today/deep/topic', { id: c.id }); reload(); } }, '就钻这个')])),
      h('div.row', {}, [
        h('button', { onclick: async (e) => { e.target.disabled = true; e.target.textContent = '正在从你的问题里挑…'; try { await api.post('/api/today/deep/suggest'); } catch (err) { toast(err.message); } reload(); } },
          d.candidates.length ? '换一批候选' : '给我 3 个候选'),
        custom, h('button', { onclick: async () => { if (!custom.value.trim()) return; await api.post('/api/today/deep/topic', { title: custom.value }); reload(); } }, '用这个'),
      ]),
    ]));
    if (d.past.length) box.append(h('div.card.flat', {}, [ui.section('以前的主题'), ...d.past.map((p) => h('div.muted', {}, `${p.week} · ${p.title}`))]));
    return;
  }
  const t = d.topic;
  box.append(h('div.card.flat', {}, [
    h('div.row.between', {}, [h('span.card-label', {}, `本周主题 · ${d.week} 起`), h('button', { onclick: async () => { if (confirm('结束这个主题，重新选？')) { await api.post('/api/today/deep/topic', { title: '' }).catch(() => {}); await api.post('/api/today/deep/suggest'); reload(); } } }, '换主题')]),
    h('h3', {}, t.title), t.why ? h('div.muted', {}, t.why) : null,
  ]));
  box.append(h('div.card', {}, [ui.section('① 读（25 分钟）', '先读你已经有的，不够再深读新的'),
    ...(d.materials.length ? d.materials.map((m) => h('div.td-mat', {}, [h('span.tag.gray', {}, m.kind), ext(h, m.link, m.title), m.summary ? h('div.muted', {}, m.summary) : null]))
      : [h('div.muted', {}, '知识库和深读里还没有相关材料。可以去「今日」卡片或深度学习里送一篇去深读。')])]));
  const inputs = Object.fromEntries(MEMO.map(([k, , ph]) => [k, field(h, ph)]));
  box.append(h('div.card', {}, [ui.section('② 写（20 分钟）', '合上材料写；先结论，再为什么、数字、怎么验证'),
    ...MEMO.map(([k, name]) => h('label.td-memo', {}, [h('b', {}, name), inputs[k]])),
    h('div.row', {}, [h('button.primary', { onclick: async () => {
      const body = { topic_id: t.id, ...Object.fromEntries(MEMO.map(([k]) => [k, inputs[k].value])) };
      try { const r = await api.post('/api/today/deep/memo', body); toast('思考稿已保存，批判者在看…'); await api.post(`/api/today/deep/memo/${r.id}/critique`); reload(); } catch (e) { toast(e.message); }
    } }, '保存，请批判者来挑刺')])]));
  if (d.memos.length) {
    box.append(h('div.card.flat', {}, [ui.section('③ 辩 · ④ 记', '批判者只追问不给答案；想清楚的预测记进台账'),
      ...d.memos.map((m) => h('div.td-memo-done', {}, [
        h('div.row.between', {}, [h('b', {}, m.day), m.score != null ? h('span.tag' + (m.score >= 70 ? '.ok' : '.warn'), {}, `${m.score} 分`) : null]),
        ...MEMO.filter(([k]) => m[k]).map(([k, name]) => h('div', {}, [h('span.muted', {}, name + '：'), m[k]])),
        m.critique?.dims ? h('div.td-dims', {}, Object.entries(m.critique.dims).map(([k, v]) => h('span.tag.gray', {}, `${k} ${v}/${d.dims[k] ?? ''}`))) : null,
        ...(m.critique?.followups || []).map((f) => h('div.td-follow', {}, ['追问：', f])),
        h('div.row', {}, [
          h('button', { onclick: () => openChat({ module: 'talk', title: '讨论', send: `接着想「${t.title}」。我的思考稿：${MEMO.map(([k, n]) => m[k] ? `${n}：${m[k]}` : '').filter(Boolean).join('；')}。批判者的追问：${(m.critique?.followups || []).join('；')}` }) }, '去讨论里接着辩'),
          predictButton(h, api, toast, m.conclusion, t.title),
        ]),
      ]))]));
  }
}

function predictButton(h, api, toast, text, title) {
  return h('button', { onclick: (e) => {
    const host = e.target.closest('.td-memo-done');
    if (host.querySelector('.td-pred')) return;
    const claim = field(h, '一个能到期对答案的预测', text);
    const prob = h('input', { type: 'number', min: 0, max: 100, value: 60, 'aria-label': '概率' });
    const due = h('input', { type: 'date', 'aria-label': '到期日' });
    host.append(h('div.td-pred.td-judge', {}, [claim, h('label.row', {}, ['概率 %', prob, '到期', due]),
      h('button.primary', { onclick: async () => {
        try { await api.post('/api/kb/judgments', { text: claim.value, type: '预测', due: due.value, note: `深度主题「${title}」· 概率 ${prob.value}%` }); toast('已记进判断台账'); host.querySelector('.td-pred').remove(); } catch (err) { toast(err.message); }
      } }, '记进台账')]));
  } }, '拆一个预测进台账');
}

// ---------- 动手 ----------
export async function renderHands(el, { api, h, toast, ui }) {
  const reload = async () => { el.replaceChildren(); await renderHands(el, { api, h, toast, ui }); };
  const d = await api.get('/api/today/hands');
  const planOf = async (c) => { try { await api.post('/api/today/hands/plan', { kind: c.kind, name: c.name, url: c.url, key: c.key || '' }); toast('任务单好了'); reload(); } catch (e) { toast(e.message); } };
  if (d.due_reviews.length) {
    el.append(h('div.card.flat', {}, [ui.section('到期回看', '30 天前的采用结论，现在还在用吗？'),
      ...d.due_reviews.map((t) => h('div.muted', {}, `${t.name} · 当时：${t.verdict || '—'} · ${t.result?.note || ''}`))]));
  }
  const name = h('input', { placeholder: '产品名或仓库名', 'aria-label': '名称' });
  const url = h('input', { placeholder: '链接（可选）', 'aria-label': '链接' });
  el.append(h('div.card', {}, [ui.section('选一个来用', '周一 / 三 / 五亲测产品，周二 / 四上手开源'),
    ...d.candidates.map((c) => h('div.td-cand', {}, [
      h('div', {}, [h('span.tag' + (c.kind === 'oss' ? '.gray' : ''), {}, c.kind === 'oss' ? '开源' : '产品'), h('b', {}, c.name), h('span.muted', {}, ' · ' + c.from),
        c.why ? h('div.muted', {}, c.why) : null]),
      h('button', { onclick: () => planOf(c) }, '出任务单')])),
    h('div.row', {}, [name, url,
      h('button', { onclick: () => name.value.trim() && planOf({ kind: 'product', name: name.value, url: url.value }) }, '亲测这个产品'),
      h('button', { onclick: () => name.value.trim() && planOf({ kind: 'oss', name: name.value, url: url.value }) }, '上手这个仓库')]),
  ]));
  for (const t of d.trials) el.append(trialCard(h, api, toast, t, reload));
}

function trialCard(h, api, toast, t, reload) {
  const isP = t.kind === 'product';
  const head = h('div.row.between', {}, [h('span.card-label', {}, (isP ? '产品亲测' : '开源上手') + (t.status === 'done' ? ' · 已完成' : '')),
    t.url ? ext(h, t.url, '打开') : null]);
  if (t.status === 'done') {
    const r = t.result || {};
    return h('div.card.flat', {}, [head, h('h3', {}, t.name),
      h('div', {}, [`结论：${t.verdict || '—'}`, t.prob != null ? ` · 概率 ${t.prob}%` : '', r.minutes_to_value != null ? ` · 首次价值 ${r.minutes_to_value} 分钟` : '']),
      r.best ? h('div.muted', {}, '最好：' + r.best) : null, r.worst ? h('div.muted', {}, '最差：' + r.worst) : null,
      r.note ? h('div.muted', {}, r.note) : null, h('div.muted', {}, `回看：${t.review_due}`)]);
  }
  const checks = (t.plan.tasks || []).map((x) => { const c = h('input', { type: 'checkbox', 'aria-label': x }); return [c, h('label.td-task', {}, [c, x])]; });
  const guess = field(h, t.plan.guess || '用之前先猜');
  const mins = h('input', { type: 'number', min: 0, placeholder: '分钟', 'aria-label': '首次拿到价值用了几分钟' });
  const best = field(h, isP ? '最好的一个设计' : '最值得借鉴的设计', '', 1);
  const worst = field(h, isP ? '最差的一个设计' : '踩到的坑', '', 1);
  const compare = field(h, isP ? '和对标产品比：同一个任务选哪个，为什么' : '和你自己的做法比', '', 1);
  const verdicts = isP ? ['会用', '借鉴', '不用'] : ['采用', '只借鉴', '不采用'];
  let verdict = '';
  const vbtns = verdicts.map((v) => h('button', { onclick: (e) => { verdict = v; vbtns.forEach((b) => b.classList.toggle('on', b === e.target)); } }, v));
  const prob = h('input', { type: 'number', min: 0, max: 100, placeholder: '%', 'aria-label': '概率' });
  const note = field(h, '一句话结论和理由', '', 2);
  return h('div.card', {}, [head, h('h3', {}, t.name),
    h('div.td-q', {}, '先猜'), guess,
    h('div.td-q', {}, '任务'), ...checks.map(([, l]) => l),
    (t.plan.claims || []).length ? h('div.muted', {}, '要验证的说法：' + t.plan.claims.join('；')) : null,
    h('div.td-q', {}, '记录'), isP ? h('label.row', {}, ['首次拿到价值用了', mins, '分钟']) : null, best, worst, compare,
    h('div.row.td-fb', {}, ['结论：', ...vbtns]),
    h('label.row', {}, [isP ? '半年内它会有明显起色的概率' : '30 天后你还在用的概率', prob, '%']), note,
    h('button.primary', { onclick: async () => {
      if (!verdict) return toast('先选一个结论');
      try {
        await api.post(`/api/today/hands/${t.id}/record`, { guess: guess.value, minutes_to_value: mins.value === '' ? null : +mins.value,
          tasks_done: checks.map(([c]) => c.checked), best: best.value, worst: worst.value, compare: compare.value, verdict,
          keep_using: verdict === '会用' || verdict === '采用', prob: prob.value === '' ? null : +prob.value, note: note.value });
        toast(isP ? '已记下，并写进调研的产品体验' : '已记下，30 天后回看'); reload();
      } catch (e) { toast(e.message); }
    } }, '记下结论')]);
}

// ---------- 学 ----------
export async function renderLearn(el, { api, h, toast, ui }) {
  const d = await api.get('/api/today/learn');
  el.append(h('p.muted', {}, '每天 40 分钟补弱项：一章 + 一道应用题。同时只推进 2 个计划，其余计划原样保留在深度学习里。'));
  if (!d.plans.length) el.append(ui.empty('还没有进行中的学习计划', '去深度学习里建一个'));
  for (const p of d.plans) {
    el.append(h('div.card', {}, [h('div.row.between', {}, [h('span.card-label', {}, p.method === 'business' ? '增长 / 商业' : '技术'), h('span.muted', {}, `${p.done}/${p.total} 步`)]),
      h('h3', {}, p.topic), ui.progress(p.total ? Math.round((p.done / p.total) * 100) : 0),
      p.next ? h('div.row.between', {}, [h('div', {}, ['下一步：', h('b', {}, p.next.title)]), h('a.td-go', { href: p.next.link }, '跟着学 →')]) : h('div.muted', {}, '这个计划学完了'),
      h('a', { href: p.link }, '看整个计划')]));
  }
  if (d.all.length > 2) {
    const sel = [0, 1].map((i) => h('select', { 'aria-label': `计划 ${i + 1}` }, d.all.map((p) => h('option', { value: p.id }, p.topic))));
    sel.forEach((s, i) => { if (d.plans[i]) s.value = d.plans[i].id; });
    el.append(h('div.card.flat', {}, [ui.section('换计划'), ...sel,
      h('button', { onclick: async () => { await api.post('/api/today/learn/pin', { plan_ids: [...new Set(sel.map((s) => +s.value))] }); toast('已换'); el.replaceChildren(); renderLearn(el, { api, h, toast, ui }); } }, '用这两个')]));
  }
}

// ---------- 台账 ----------
export async function renderLedger(el, { api, h, toast, ui }) {
  const d = await api.get('/api/today/ledger');
  const s = d.stats;
  el.append(ui.stats([{ k: '本周判断', v: s.judgments }, { k: '带概率', v: s.with_prob }, { k: '思考稿', v: s.memos }, { k: '动手', v: s.trials }, { k: '机会卡', v: s.opps }]));
  const review = (j) => h('div.td-due', {}, [h('div', {}, [h('span.tag.gray', {}, j.type || '判断'), j.claim || j.title]),
    h('div.row', {}, [h('span.muted', {}, '到期 ' + j.due), ...[['holds', '仍成立'], ['revised', '要修正'], ['overturned', '推翻了'], ['pending', '还看不出']].map(([v, t]) =>
      h('button', { onclick: async () => { try { await api.post('/api/kb/judgments/review', { sid: j.sid, verdict: v }); toast('已记复查'); } catch (e) { toast(e.message); } } }, t))])]);
  el.append(h('div.card.flat', {}, [ui.section('开奖', `${d.due.length} 条到期`), ...(d.due.length ? d.due.map(review) : [h('div.muted', {}, '今天没有到期的判断')])]));
  if (d.upcoming.length) el.append(h('div.card.flat', {}, [ui.section('快到期'), ...d.upcoming.map((j) => h('div.muted', {}, `${j.due} · ${j.claim || j.title}`))]));
  el.append(h('div.card.flat', {}, [ui.section('机会台账', '想到 → 写透 → 验证过 → 推进 / 放弃'),
    ...(d.opps.length ? d.opps.map((o) => {
      const note = h('input', { placeholder: '进展一句话（可选）', 'aria-label': '进展' });
      return h('div.td-opp-row', {}, [h('div', {}, [h('span.tag', {}, OPP_NAME[o.status] || o.status), h('b', {}, o.title), o.prob != null ? h('span.muted', {}, ` · ${o.prob}%`) : null]),
        [o.change, o.pain, o.test].some(Boolean) ? h('div.muted', {}, [o.change, o.pain, o.test].filter(Boolean).join(' · ')) : null,
        o.note ? h('div.muted', {}, o.note) : null,
        h('div.row', {}, [note, ...d.opp_status.filter((x) => x !== o.status).map((x) => h('button', { onclick: async () => {
          await api.post(`/api/today/opps/${o.id}`, { status: x, note: note.value }); toast('已更新'); el.replaceChildren(); renderLedger(el, { api, h, toast, ui });
        } }, OPP_NAME[x]))])]);
    }) : [h('div.muted', {}, '还没有机会卡。在「今日」的卡片上点“这里有机会”。')])]));
}

// ---------- 画像 ----------
export async function renderProfile(el, { api, h, ui }) {
  const d = await api.get('/api/today/profile');
  el.append(h('p.muted', {}, `能力尺子：${d.ladder.join(' → ')}。画像按信号每周更新，等级一变，今日卡和深度材料的难度跟着换档。`));
  for (const m of d.motivations) {
    el.append(h('div.card.flat', {}, [h('div.row.between', {}, [h('b', {}, `${m.id} ${m.name}`), h('span', {}, Object.entries(m.levels).map(([k, v]) => h('span.tag', {}, `${k} ${v}`)))]),
      h('div.muted', {}, m.want)]));
  }
  const q = d.signals.questions || {};
  el.append(h('div.card.flat', {}, [ui.section('信号：你提问的类型', '概念 → 机制 → 决策，往右走说明在升级'),
    ...Object.entries(q).map(([area, v]) => h('div.td-sig', {}, [h('b', {}, area), ` 共 ${v['合计']} 问 · 概念 ${v['概念']} · 机制 ${v['机制']} · 决策 ${v['决策']}`])),
    ui.section('章末测试三维'), h('div', {}, Object.entries(d.signals.quiz || {}).map(([k, v]) => h('span.tag' + (v < 60 ? '.warn' : '.ok'), {}, `${k} ${v}`))),
    h('div.muted', {}, `思考稿平均分 ${d.signals.memo_avg != null ? Math.round(d.signals.memo_avg) : '—'} · 已完成动手 ${d.signals.trials} 次`)]));
}
