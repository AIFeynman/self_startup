// 复盘 · 考题卡：批注、Claude 对话和已读历史出的问答题，按艾宾浩斯间隔复习；答错回到第 1 天，下次换一道变式题。由 review.js 的「考题卡」标签调用。
const KIND = { ann: '批注', chat: 'Claude 对话', read: '已读' };
const VERDICT = { right: ['答对了', 'ok'], wrong: ['没答对', 'bad'], pending: ['自动判分没成功', 'gray'] };

const days = (d) => Math.round((new Date(d + 'T12:00:00') - new Date(new Date().toLocaleDateString('sv-SE') + 'T12:00:00')) / 864e5);

export async function renderQuiz(body, ctx) {
  const { api, h, md, toast, ui } = ctx;
  injectStyle();
  let polls = 0;

  const src = (c) => h('div.qz-src', {}, [h('span.tag.gray', {}, KIND[c.src_kind] || c.src_kind),
    c.src_link ? h('a', c.src_link.startsWith('#') ? { href: c.src_link } : { href: c.src_link, target: '_blank', rel: 'noopener' }, c.src_title) : c.src_title]);

  const rounds = (c, n) => h('span.qz-rounds', { title: `连续答对 ${c.stage} 次，答对 ${n} 次算掌握` },
    Array.from({ length: n }, (_, i) => h('i' + (i < c.stage ? '.on' : ''))));

  function result(c, r, box) {
    const [label, cls] = VERDICT[r.verdict] || VERDICT.pending;
    const next = r.next_due ? (r.mastered ? '已掌握，不再出这道题' : `下次 ${days(r.next_due)} 天后（${r.next_due}）${r.verdict === 'wrong' ? '，会换一道变式题' : ''}`) : '';
    const judge = (v, text) => h('button', { onclick: async () => {
      try { const o = await api.post(`/api/review/quiz/${c.id}/override`, { verdict: v }); result(c, { ...r, ...o, feedback: r.feedback }, box); } catch (e) { toast('没改上：' + e.message); }
    } }, text);
    box.replaceChildren(
      h('div.qz-verdict.' + cls, {}, [label, r.score != null ? ` · ${r.score}/10` : '', r.feedback ? h('span.muted', {}, ' · ' + r.feedback) : null]),
      h('div.qz-ans', {}, [h('div.td-sec', {}, '参考答案'), md(r.answer || '')]),
      next ? h('div.muted', {}, next) : null,
      h('div.row', {}, r.verdict === 'pending' ? [h('span.muted', {}, '自己判：'), judge('right', '我答对了'), judge('wrong', '没答对')]
        : [h('span.muted', {}, '判得不对？'), r.verdict === 'right' ? judge('wrong', '改成没答对') : judge('right', '改成答对了')]));
  }

  function card(c, n) {
    const ta = h('textarea', { rows: 3, placeholder: '用自己的话答，答到要点就算对', 'aria-label': '你的回答' });
    const box = h('div.qz-form', {}, [ta]);
    const send = async (dontKnow) => {
      if (!dontKnow && !ta.value.trim()) return toast('先写下你的回答，或点「不会」');
      box.replaceChildren(h('div.muted', {}, dontKnow ? '记下了…' : '判分中…'));
      try { result(c, await api.post(`/api/review/quiz/${c.id}/answer`, { answer: ta.value, dont_know: dontKnow }), box); }
      catch (e) { toast('没提交上：' + e.message); box.replaceChildren(ta, btns); }
    };
    const btns = h('div.row', {}, [h('button.primary', { onclick: () => send(false) }, '提交'), h('button', { onclick: () => send(true) }, '不会，看答案')]);
    box.append(btns);
    return h('div.card.qz-card', {}, [
      h('div.row.between', {}, [src(c), h('span.row', {}, [
        c.variant ? h('span.tag', { title: '上次没答对，换了个问法' }, `变式 ${c.variant}`) : null,
        c.wrong ? h('span.tag.gray', {}, `错过 ${c.wrong} 次`) : null, rounds(c, n)])]),
      c.point ? h('div.muted.qz-point', {}, '考点：' + c.point) : null,
      h('div.qz-q', {}, c.q),
      box,
    ]);
  }

  async function load() {
    const d = await api.get('/api/review/quiz');
    const s = d.stats, n = d.intervals.length;
    const more = s.due > d.due.length ? `，先考最要紧的 ${d.due.length} 张（错过的排前面）` : '';
    body.replaceChildren(
      ui.section('考题卡', '防遗忘'),
      h('div.card.flat.qz-stats', {}, [
        h('b', {}, `今天待考 ${s.due} 张${more}`),
        h('span.muted', {}, `今天考过 ${s.done_today} · 明天到期 ${s.tomorrow} · 复习中 ${s.active} · 已掌握 ${s.mastered} · 错题本 ${s.wrongbook}`),
        h('span.muted', {}, `题目来自你的批注、Claude 对话和已读历史；按 ${d.intervals.join(' / ')} 天的间隔复习，连续答对 ${n} 次算掌握，答错回到第 1 天、下次换一道变式题`),
        d.harvesting ? h('div.muted', {}, '正在从新的批注、对话和已读里出题…') : null,
      ]),
      ...(d.due.length ? d.due.map((c) => card(c, n)) : [ui.empty('今天没有要考的', s.active ? `明天到期 ${s.tomorrow} 张` : '划线评论、问 Claude 或读文章后，第二天会出现考题')]),
      h('div.row', {}, [h('button.outline', { onclick: async (e) => {
        e.target.disabled = true;
        try { const r = await api.post('/api/review/quiz/harvest'); toast(r.new ? `出了 ${r.new} 道新题，明天开始考` : '没有新素材可出题'); await load(); } catch (err) { toast('出题失败：' + err.message); e.target.disabled = false; }
      } }, '现在从新素材出题')]),
      d.wrongbook.length ? h('details.card.qz-wrong', {}, [h('summary', {}, `错题本（${d.wrongbook.length}）`),
        ...d.wrongbook.map((c) => h('div.qz-wb', {}, [src(c), h('div.qz-q', {}, c.q), h('div.muted', {}, c.answer),
          h('div.muted', {}, c.status === 'mastered' ? '已掌握' : `错过 ${c.wrong} 次 · 下次 ${c.due}`)]))]) : null,
    );
    if (d.harvesting && polls++ < 10 && body.isConnected) setTimeout(load, 8000);
  }
  await load();
}

function injectStyle() {
  if (document.getElementById('qz-style')) return;
  const s = document.createElement('style');
  s.id = 'qz-style';
  s.textContent = `
.qz-stats { display: grid; gap: 4px; margin-bottom: 12px; }
.qz-card { margin-bottom: 12px; }
.qz-src { display: flex; gap: 6px; align-items: center; font-size: 13px; min-width: 0; }
.qz-src a { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 46ch; }
.qz-q { font: 600 17px/1.6 var(--serif); margin: 8px 0; }
.qz-point { font-size: 13px; margin-top: 6px; }
.qz-form { display: grid; gap: 8px; }
.qz-form textarea { width: 100%; box-sizing: border-box; font: inherit; padding: 8px 10px; border: 1px solid var(--line-2); border-radius: 8px; background: var(--bg); color: var(--text); }
.qz-verdict { font-weight: 600; }
.qz-verdict.ok { color: var(--ok, #2f8a4c); } .qz-verdict.bad { color: var(--danger, #c0392b); }
.qz-ans { background: var(--bg-2); border-radius: 8px; padding: 6px 10px; }
.qz-rounds { display: inline-flex; gap: 3px; } .qz-rounds i { width: 8px; height: 8px; border-radius: 50%; background: var(--line-2); }
.qz-rounds i.on { background: var(--accent); }
.qz-wrong summary { cursor: pointer; font-weight: 600; } .qz-wb { border-top: 1px solid var(--line); padding: 8px 0; }
@media (max-width: 640px) { .qz-card > .row.between { flex-wrap: wrap; gap: 6px; } .qz-src a { max-width: 28ch; } }
`;
  document.head.append(s);
}
