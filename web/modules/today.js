// 今日：开奖 → 3 张精读（先判断再揭晓）→ 速览。只读复用产品雷达、增长 Case、论文、HN、X 长文；
// 判断写进判断台账，“没增量”和机会卡存本板块。设计稿 docs/designs/2026-11-25-daily-learning-system.html
const PROB_DEFAULT = 60;
const OPEN_FIRST = { product: ['所以呢'], growth: ['一句话', '我能怎么用'] };

export default {
  async render(el, { api, h, md, toast, ui }) {
    injectStyle();
    const body = h('div');
    let data = null;

    const load = async ({ refresh = false, due = true } = {}) => {
      const prevDue = data?.due || [];
      data = await api.get(`/api/today?refresh=${refresh ? 1 : 0}&due=${due ? 1 : 0}`);
      if (!due) data.due = prevDue;
      paint();
    };
    const post = async (url, payload, msg) => {
      try { await api.post(url, { ...payload, day: data.day }); if (msg) toast(msg); await load({ due: false }); } catch (e) { toast('没保存上：' + e.message); }
    };
    const link = (c, text = '看原卡') => h('a', c.link.startsWith('#') ? { href: c.link } : { href: c.link, target: '_blank', rel: 'noopener' }, text);
    const relates = (c) => (c.relates?.length ? h('div.td-rel', {}, ['和你有关：', ...c.relates.map((r) => h('span.tag', {}, r))]) : null);

    function feedbackRow(c) {
      const noGain = h('button' + (c.feedback === 'no_gain' ? '.on' : ''), { onclick: () => post('/api/today/feedback', { key: c.key, value: 'no_gain' }, '记下了：没增量') }, '没增量');
      return h('div.row.td-fb', {}, [noGain, oppButton(c), link(c)]);
    }

    function oppButton(c) {
      return h('button', {
        onclick: (e) => {
          const host = e.target.closest('.td-card');
          if (host.querySelector('.td-opp')) return;
          const f = (ph) => h('input', { placeholder: ph, 'aria-label': ph });
          const title = f('机会一句话（必填）'), change = f('什么变化让它成为可能'), pain = f('谁的痛点'), test = f('最小验证怎么做');
          const prob = h('input', { type: 'number', min: 0, max: 100, value: 30, 'aria-label': '6 个月内有人做成的概率' });
          host.append(h('div.td-opp', {}, [h('div.muted', {}, '记一张机会卡'), title, change, pain, test,
            h('label.row', {}, ['6 个月内会有人做成的概率 %', prob]),
            h('button.primary', { onclick: () => { if (!title.value.trim()) return toast('先写一句机会'); post('/api/today/opps', { key: c.key, title: title.value, change: change.value, pain: pain.value, test: test.value, prob: +prob.value }, '机会卡已记下'); } }, '保存机会卡')]));
        },
      }, '这里有机会');
    }

    function reveal(c) {
      const parts = Object.entries(c.reveal || {});
      const open = OPEN_FIRST[c.kind] || [];
      const shown = parts.filter(([k]) => open.includes(k));
      const folded = parts.filter(([k]) => !open.includes(k));
      return h('div.td-reveal', {}, [
        ...shown.map(([k, v]) => h('div', {}, [h('div.td-sec', {}, k), md(v)])),
        ...folded.map(([k, v]) => h('details.td-more', {}, [h('summary', {}, k), md(v)])),
        c.kind === 'tech' ? h('div.row', {}, [
          h('button', { onclick: async () => { try { await api.post('/api/learn/items', { url: c.url, reuse: true }); toast('已送去深读'); } catch (e) { toast(e.message); } } }, '送去深读'),
        ]) : null,
        feedbackRow(c),
      ]);
    }

    function judgeForm(c) {
      if (c.kind === 'growth') {
        const t = h('textarea', { rows: 2, placeholder: '比如：靠 SEO 榜单拉新，几个月翻倍', 'aria-label': '你的猜测' });
        return h('div.td-judge', {}, [h('div.td-q', {}, c.question), t,
          h('button.primary', { onclick: () => { if (!t.value.trim()) return toast('先写下你的猜测'); post('/api/today/guess', { key: c.key, text: t.value }); } }, '记下猜测，揭晓')]);
      }
      const text = h('textarea', { rows: 2, 'aria-label': '判断' });
      text.value = c.prediction || '';
      if (!c.prediction) text.placeholder = c.kind === 'tech' ? '一句话：值不值得深读，你会换成什么做法' : '一句话判断';
      const out = h('span.td-prob-v', {}, PROB_DEFAULT + '%');
      const prob = h('input', { type: 'range', min: 0, max: 100, step: 5, value: PROB_DEFAULT, 'aria-label': '概率', oninput: () => { out.textContent = prob.value + '%'; } });
      const reason = h('input', { placeholder: '一句理由（可选）', 'aria-label': '理由' });
      const withProb = c.kind === 'product';
      return h('div.td-judge', {}, [
        h('div.td-q', {}, c.question), text,
        withProb ? h('div.row.td-prob', {}, ['兑现概率', prob, out, h('span.muted', {}, '到期 ' + c.due)]) : null,
        reason,
        h('div.row', {}, [
          h('button.primary', { onclick: () => { if (!text.value.trim()) return toast('先写一句判断'); post('/api/today/judge', { key: c.key, text: text.value, prob: withProb ? +prob.value : null, reason: reason.value, due: withProb ? c.due : '' }, '已记进判断台账'); } }, '记下判断，揭晓'),
          h('button', { onclick: () => post('/api/today/guess', { key: c.key, action: 'read', text: '' }) }, '不判断，直接看'),
        ]),
      ]);
    }

    function deepCard(c) {
      return h('div.card.td-card' + (c.done ? '.done' : ''), {}, [
        h('div.row.between', {}, [h('span.card-label', {}, c.label), h('span.muted', {}, [c.company, c.date].filter(Boolean).join(' · '))]),
        h('h3', {}, c.title),
        c.summary ? h('p.td-sum', {}, c.summary) : null,
        c.why ? h('div.td-why', {}, ['为什么值得你想：', c.why]) : relates(c),
        c.hit ? h('div.td-hit', {}, ['你问过：', c.hit]) : null,
        c.done ? h('div', {}, [c.guess ? h('div.td-guess', {}, ['你的猜测：', c.guess]) : null, reveal(c)]) : judgeForm(c),
      ]);
    }

    function quickCard(c) {
      return h('div.td-quick' + (c.feedback === 'no_gain' ? '.dim' : ''), {}, [
        h('div.row.between', {}, [h('span.card-label', {}, c.label), h('span.muted', {}, c.date || '')]),
        h('div.td-qt', {}, c.title),
        c.summary ? h('div.muted', {}, c.summary) : null,
        c.takeaway ? h('div.td-take', {}, ['可迁移：', c.takeaway]) : null,
        relates(c),
        h('div.row.td-fb', {}, [link(c, c.link.startsWith('#') ? '深入' : '看原文'),
          h('button' + (c.feedback === 'no_gain' ? '.on' : ''), { onclick: () => post('/api/today/feedback', { key: c.key, value: 'no_gain' }, '记下了：没增量') }, '没增量')]),
      ]);
    }

    function dueList() {
      if (!data.due.length) return null;
      return h('div.card.flat', {}, [ui.section('开奖', `${data.due.length} 条到期`),
        ...data.due.map((j) => h('div.td-due', {}, [
          h('div', {}, [h('span.tag.gray', {}, j.type || '判断'), j.claim || j.title]),
          h('div.row', {}, [h('span.muted', {}, '到期 ' + j.due),
            ...[['holds', '仍成立'], ['revised', '要修正'], ['overturned', '推翻了'], ['pending', '还看不出']].map(([v, t]) =>
              h('button', { onclick: async () => { try { await api.post('/api/kb/judgments/review', { sid: j.sid, verdict: v }); toast('已记复查'); await load(); } catch (e) { toast(e.message); } } }, t)),
            h('a', { href: j.link || '#kb' }, '去台账')]),
        ]))]);
    }

    function paint() {
      const p = data.progress;
      const pct = p.deep_total ? Math.round((p.deep_done / p.deep_total) * 100) : 0;
      body.replaceChildren(
        h('div.card.flat.td-head', {}, [
          h('div.row.between', {}, [h('b', {}, `精读 ${p.deep_done}/${p.deep_total}`), h('span.muted', {}, `速览 ${p.quick_total} · 机会卡 ${p.opps} · 没增量 ${p.no_gain}`)]),
          ui.progress(pct),
          p.deep_total && p.deep_done >= p.deep_total ? h('div.td-end', {}, '今天的精读做完了，到此为止。') : null,
        ]),
        dueList() || h('span'),
        ui.section('精读', '先判断，再揭晓'),
        ...(data.deep.length ? data.deep.map(deepCard) : [ui.empty('今天没有合格的精读卡', '宁缺毋滥：来源里没有新的合格内容')]),
        ui.section('速览', '知道一下，想深挖就点进去'),
        data.quick.length ? h('div.td-quick-list', {}, data.quick.map(quickCard)) : ui.empty('今天没有速览'),
      );
    }

    el.append(ui.pageHead('今日', '每天 3 张精读 + 速览 + 开奖；内容复用产品雷达、增长 Case、论文、HN 和 X 长文',
      [h('button.outline', { title: '重新挑今天的卡（已做的记录保留）', onclick: () => load({ refresh: true }) }, [ui.icon('refresh'), '重选'])]), body);
    await load();
  },
};

function injectStyle() {
  if (document.getElementById('td-style')) return;
  const s = document.createElement('style');
  s.id = 'td-style';
  s.textContent = `
.td-head .progress { margin: 8px 0 2px; }
.td-end { margin-top: 8px; color: var(--ok); font-size: 14px; }
.td-card.done { border-color: var(--line); }
.td-sum { margin: 4px 0 8px; }
.td-rel { font-size: 13px; color: var(--muted); margin: 4px 0 10px; }
.td-judge, .td-opp { display: grid; gap: 8px; margin-top: 8px; }
.td-judge textarea, .td-judge input, .td-opp input { width: 100%; box-sizing: border-box; font: inherit; padding: 8px 10px; border: 1px solid var(--line-2); border-radius: 8px; background: var(--bg); color: var(--text); }
.td-judge input[type=range] { flex: 1; min-width: 120px; padding: 0; border: 0; }
.td-q { font-weight: 600; }
.td-why { font-size: 14px; margin: 4px 0; }
.td-hit { font-size: 13px; color: var(--muted); margin: 2px 0 8px; border-left: 3px solid var(--accent-soft); padding-left: 8px; }
.td-prob { font-size: 14px; }
.td-prob-v { font-weight: 700; color: var(--accent); min-width: 3em; }
.td-sec { font-size: 12px; color: var(--accent); font-weight: 700; margin-top: 10px; }
.td-more { margin-top: 8px; } .td-more summary { cursor: pointer; font-size: 13px; color: var(--accent); }
.td-guess { font-size: 14px; background: var(--bg-2); padding: 6px 10px; border-radius: 8px; margin: 6px 0; }
.td-fb { margin-top: 10px; }
.td-fb button.on { border-color: var(--accent); color: var(--accent); }
.td-quick-list { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 12px; }
.td-quick { border: 1px solid var(--line); border-radius: var(--radius); padding: 12px 14px; background: var(--panel); }
.td-quick.dim { opacity: .55; }
.td-qt { font-weight: 600; margin: 2px 0 4px; }
.td-take { font-size: 13px; margin-top: 4px; }
.td-due { padding: 8px 0; border-top: 1px solid var(--line); display: grid; gap: 6px; }
.td-due:first-of-type { border-top: 0; }
`;
  document.head.append(s);
}
