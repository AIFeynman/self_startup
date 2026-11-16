// 青少年板块：每天两个题材（一个时事、一个往事），三层递进的题，记录作答、想法和改进意见。
// 数据全在后端 /api/teen/*；题和答案来自通过校验的出题结果，作答只追加。
const LEVEL = { 1: '看清', 2: '追问', 3: '换位与评价' };
const SELF = [['没想到', 0], ['想到一部分', 1], ['想全了', 2]];

function replies(h, it, qidx, kind) {
  const list = it.replies.filter((r) => r.qidx === qidx && r.kind === kind);
  if (!list.length) return null;
  return h('ul.tn-hist', {}, list.map((r) => h('li', {}, [h('span.muted', {}, `${r.created_at.slice(5, 16).replace('T', ' ')} `),
    r.self_score !== null ? h('span.tag', {}, SELF[r.self_score][0]) : null, ' ', r.content])));
}

function box(ctx, it, { qidx, kind, label, placeholder, scored = false, after = () => {} }) {
  const { h, api, toast } = ctx;
  const ta = h('textarea.tn-ta', { rows: 3, placeholder });
  let score = null;
  const chips = scored ? h('div.tn-self', {}, [h('span.muted', {}, '我对照答案后觉得：'), ...SELF.map(([t, v]) => h('button.chip', {
    onclick: (e) => { score = v; [...e.target.parentNode.querySelectorAll('button')].forEach((b) => b.classList.toggle('on', b === e.target)); } }, t))]) : null;
  const save = h('button.ghost', { onclick: async () => {
    if (!ta.value.trim() && score === null) return toast('先写点什么', true);
    try { await api.post(`/api/teen/items/${it.id}/reply`, { qidx, kind, content: ta.value, self_score: score }); toast('已记录'); await after(); } catch (e) { toast(e.message, true); }
  } }, '记录');
  return h('div.tn-box', {}, [h('span.card-label', {}, label), ta, chips, save, replies(h, it, qidx, kind)]);
}

function question(ctx, it, q, i, refresh) {
  const { h } = ctx;
  return h('div.tn-q', {}, [
    h('div.row', {}, [h('span.tag', {}, `第 ${q.level} 层 · ${LEVEL[q.level] || ''}`), h('span.tag.gray', {}, q.ability)]),
    h('p.tn-qtext', {}, q.q),
    q.hint ? h('details', {}, [h('summary.muted', {}, '卡住了？看提示'), h('div', {}, q.hint)]) : null,
    box(ctx, it, { qidx: i, kind: 'answer', label: '我的作答', placeholder: '先自己写，再看答案', scored: true, after: refresh }),
    h('details.tn-ans', {}, [h('summary', {}, '看参考答案'), h('div.tn-answer', {}, q.answer),
      h('ul.vs-list', {}, (q.points || []).map((p) => h('li', {}, p)))]),
  ]);
}

function itemCard(ctx, it, refresh) {
  const { h } = ctx;
  const b = it.body, s = b.source || {};
  return h('div.card.tn-card', {}, [
    h('div.row.between', {}, [h('div', {}, [h(`span.tag${it.kind === '时事' ? '.ok' : ''}`, {}, it.kind), ' ', h('span.tag.gray', {}, it.domain)]),
      h('a.muted', { href: s.url, target: '_blank', rel: 'noopener' }, `出处：${s.name}${s.date ? `（${s.date}）` : ''}`)]),
    h('h3.vs-card-title', {}, it.headline),
    h('div.tn-train', {}, [h('span.card-label', {}, '为什么练这个'),
      h('div', {}, [h('b', {}, `${b.ability} · ${b.train_focus}`), '。', b.why_this]),
      h('div.muted', {}, `三层怎么递进：${b.ladder}`)]),
    h('p', {}, b.background),
    h('div.tn-phe', {}, [h('span.card-label', {}, '眼前的现象'), b.phenomenon]),
    ...(b.questions || []).map((q, i) => question(ctx, it, q, i, refresh)),
    h('div.tn-wrap', {}, [
      box(ctx, it, { qidx: -1, kind: 'thought', label: '我想到了哪些', placeholder: '读完、答完之后，还想到什么？联想、疑问、不同意的地方都行', after: refresh }),
      box(ctx, it, { qidx: -1, kind: 'improve', label: '后面怎么改进', placeholder: '这个题材或题目哪里太浅、太深、不好懂？想看什么？下次出题会参考', after: refresh })]),
  ]);
}

function statusLine(d) {
  const l = d.last;
  if (!l) return '还没出过题，点右上角「现在出题」，或等每天自动生成';
  const m = { running: '正在出题（查来源 → 出题 → 校验）', done: `最近一次出题 ${l.updated_at}`, rejected: `第 ${l.attempt} 次没通过校验，会自动重出`, failed: '最近一次出题失败' };
  return m[l.status] || l.status;
}

function scoreStats(ctx, d) {
  const { ui } = ctx;
  if (!d.scores.length) return null;
  return [ui.section('我的自评', '平均分满分 2，越低越要多练'),
    ui.stats(d.scores.map((s) => ({ k: `第${s.level}层 · ${s.ability}（${s.n} 次）`, v: s.avg.toFixed(1) })))];
}

export default {
  async render(el, ctx) {
    injectStyle();
    const { api, h, ui, toast } = ctx;
    const refresh = async () => { el.innerHTML = ''; await this.render(el, ctx); };
    const d = await api.get('/api/teen/overview');
    const btn = h('button.ghost', { onclick: async () => {
      const r = await api.post('/api/teen/refresh', {});
      toast(r.ok ? '开始出题，几分钟后刷新' : (r.reason || '正在出题'));
    } }, [ui.icon('refresh'), ' 现在出题']);
    const [first, ...older] = d.days;
    el.append(h('div.vs-page', {}, [
      ui.pageHead('青少年', statusLine(d), [btn]),
      d.last?.status === 'rejected' && d.last.problems.length ? h('div.card.muted', {}, `上一版被打回：${d.last.problems.join('；')}`) : null,
      first ? [ui.section(first.day === d.today ? '今天' : first.day, '一个时事 + 一个往事'), ...first.items.map((it) => itemCard(ctx, it, refresh))]
        : ui.empty('还没有题材', '每天自动挑两个：一个最近的真实事件，一个从过去知识里挖出来的题材。'),
      scoreStats(ctx, d),
      older.length ? ui.section('往天的题材', '作答和想法都留着，可以回头补写') : null,
      ...older.map((day) => h('details.card', {}, [h('summary', {}, `${day.day} · ${day.items.map((i) => i.headline).join(' / ')}`),
        ...day.items.map((it) => itemCard(ctx, it, refresh))])),
    ].flat().filter(Boolean)));
  },
};

const CSS = `
.tn-card { display: flex; flex-direction: column; gap: 12px; margin-bottom: 16px; min-width: 0; }
.tn-train { background: var(--bg-2); border-radius: 10px; padding: 10px 12px; font-size: 14px; line-height: 1.65; }
.tn-phe { font-size: 15px; font-weight: 600; }
.tn-q { border-top: 1px solid var(--line); padding-top: 12px; display: flex; flex-direction: column; gap: 8px; }
.tn-qtext { margin: 0; font-size: 15px; line-height: 1.7; }
.tn-box { display: flex; flex-direction: column; gap: 6px; }
.tn-ta { width: 100%; box-sizing: border-box; font: inherit; resize: vertical; }
.tn-self { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
.tn-self .chip.on { border-color: var(--accent); color: var(--accent); }
.tn-answer { white-space: pre-wrap; font-size: 14px; line-height: 1.7; margin: 6px 0; }
.tn-ans summary { cursor: pointer; }
.tn-hist { margin: 0; padding-left: 18px; font-size: 13px; }
.tn-wrap { border-top: 1px solid var(--line); padding-top: 12px; display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
@media (max-width: 720px) { .tn-wrap { grid-template-columns: 1fr; } }
`;

function injectStyle() {
  if (document.getElementById('tn-style')) return;
  const s = document.createElement('style');
  s.id = 'tn-style';
  s.textContent = CSS;
  document.head.append(s);
}
