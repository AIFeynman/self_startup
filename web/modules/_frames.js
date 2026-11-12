// 讨论 · 框架库：产品 / 设计 / 运营 / 工程 / 算法 / 增长的判断卡，按「目标 → 角度 → 手段 → 空间 → 好坏 → 反模式」组织（后端见 app/kb_lens.py）。
// 讨论时 Agent 自己挑合适的卡；这里可以翻看，也可以点某张卡直接开聊。
const CSS = `
.fr-lib > summary { cursor: pointer; font-weight: 600; }
.fr-legend { display: flex; flex-wrap: wrap; gap: 6px; margin: 12px 0 0; }
.fr-legend button { border: 1px solid var(--line); background: var(--panel); border-radius: 999px; padding: 3px 11px; font-size: 12px; color: var(--text); }
.fr-legend button.on { border-color: var(--text); }
.fr-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 12px; margin-top: 10px; }
.fr-card { margin: 0; padding: 14px 16px; cursor: pointer; display: flex; flex-direction: column; gap: 6px; }
.fr-card:hover { border-color: var(--accent); }
.fr-card.open { grid-column: 1 / -1; cursor: default; border-color: var(--accent); }
.fr-card h3 { margin: 0; font-size: 15.5px; display: flex; gap: 8px; align-items: baseline; }
.fr-card .goal { color: var(--muted); font-size: 13.5px; line-height: 1.6; }
.fr-card.open .goal { color: var(--text); }
.fr-secs { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 10px 20px; margin-top: 6px; }
.fr-sec h4 { margin: 0 0 4px; font-size: 13px; color: var(--accent); }
.fr-sec ul { margin: 0; padding-left: 18px; font-size: 13.5px; line-height: 1.65; }
.fr-drill { background: var(--accent-soft); border-radius: 8px; padding: 8px 12px; font-size: 13.5px; }
.fr-src { font-size: 12.5px; color: var(--muted); }
.fr-acts { display: flex; flex-wrap: wrap; gap: 8px; }
`;

export async function framesSection(ctx) {
  const { api, h, ui, openChat } = ctx;
  if (!document.getElementById('fr-style')) document.head.append(h('style#fr-style', {}, CSS));
  const data = await api.get('/api/talk/frames');
  const all = data.domains.flatMap((d) => d.cards);
  let domain = '', open = '';
  const legend = h('div.fr-legend');
  const grid = h('div.fr-grid');
  const talk = (c, prefill) => openChat({ module: 'talk', ref: 'lens:' + c.id, title: '讨论 · ' + c.title, fresh: true, prefill });
  const card = (c) => {
    const isOpen = open === c.id;
    const el = h('div.card.fr-card' + (isOpen ? '.open' : ''), { onclick: () => { if (!isOpen) { open = c.id; draw(); } } }, [
      h('h3', {}, [h('span.tag', {}, c.domain), h('span.grow', {}, c.title),
        isOpen ? h('button.ghost.sm', { onclick: (e) => { e.stopPropagation(); open = ''; draw(); } }, '收起') : null]),
      h('div.goal', {}, [isOpen ? h('b', {}, '目标函数：') : null, c.goal]),
    ]);
    if (!isOpen) return el;
    el.append(
      h('div.fr-secs', {}, data.sections.slice(1).map((s) => h('div.fr-sec', {}, [h('h4', {}, s.name),
        h('ul', {}, c[s.key].map((x) => h('li', {}, s.key === 'levers' ? [h('b', {}, x.name + '：'), x.how] : x)))]))),
      h('div.fr-drill', {}, [h('b', {}, '练习题：'), c.drill]),
      h('div.fr-src', {}, '参考：' + c.sources.join('；')),
      h('div.fr-acts', {}, [
        h('button', { onclick: () => talk(c, '我的场景：\n我的判断：') }, [ui.icon('chat'), '用这张卡开聊']),
        h('button.ghost', { onclick: () => talk(c, `练习题：${c.drill}\n我的判断：`) }, '作答练习题'),
      ]),
    );
    return el;
  };
  const draw = () => {
    legend.replaceChildren(...[['', '全部'], ...data.domains.map((d) => [d.name, `${d.name} ${d.cards.length}`])].map(([v, l]) =>
      h('button' + (domain === v ? '.on' : ''), { onclick: () => { domain = v; open = ''; draw(); } }, l)));
    grid.replaceChildren(...all.filter((c) => !domain || c.domain === domain).map(card));
  };
  draw();
  return h('details.card.fr-lib', {}, [h('summary', {}, `框架库 · ${all.length} 张判断卡（讨论时 Agent 会自己挑，也可以点一张直接开聊）`), legend, grid]);
}
