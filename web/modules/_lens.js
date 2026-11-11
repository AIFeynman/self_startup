// 判断卡：产品 / 设计 / 运营 / 工程 / 算法 / 增长的关键问题，按「目标 → 角度 → 手段 → 空间 → 好坏 → 反模式」组织，可带场景和 Agent 讨论（后端见 app/kb_lens.py）。
// 路由：#kb/lens（全部）#kb/lens/<卡片 id>（展开某张）
import { chatBusy, chatSnapshot } from '../chat.js';

const CSS = `
.ln-ask { display: grid; gap: 8px; padding: 14px 16px; }
.ln-ask textarea { width: 100%; min-height: 64px; font: inherit; padding: 8px 10px; border: 1px solid var(--line-2); border-radius: 8px; background: var(--panel); color: var(--text); resize: vertical; box-sizing: border-box; }
.ln-ask select { max-width: 100%; }
.ln-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 12px; }
.ln-card { margin: 0; padding: 14px 16px; cursor: pointer; display: flex; flex-direction: column; gap: 6px; }
.ln-card:hover { border-color: var(--accent); }
.ln-card.open { grid-column: 1 / -1; cursor: default; border-color: var(--accent); }
.ln-card h3 { margin: 0; font-size: 16px; display: flex; gap: 8px; align-items: baseline; }
.ln-card .goal { color: var(--muted); font-size: 13.5px; line-height: 1.6; }
.ln-card.open .goal { color: var(--text); }
.ln-secs { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 10px 20px; margin-top: 6px; }
.ln-sec h4 { margin: 0 0 4px; font-size: 13px; color: var(--accent); }
.ln-sec ul { margin: 0; padding-left: 18px; font-size: 13.5px; line-height: 1.65; }
.ln-sec li b { font-weight: 600; }
.ln-drill { background: var(--accent-soft); border-radius: 8px; padding: 8px 12px; font-size: 13.5px; }
.ln-src { font-size: 12.5px; color: var(--muted); }
.ln-acts { display: flex; flex-wrap: wrap; gap: 8px; }
`;

export async function lensTab(body, ctx, focus = '') {
  const { api, h, ui } = ctx;
  if (!document.getElementById('ln-style')) document.head.append(h('style#ln-style', {}, CSS));
  const data = await api.get('/api/kb/lens');
  const all = data.domains.flatMap((d) => d.cards);
  let domain = all.find((c) => c.id === focus)?.domain || '';
  let open = focus;

  const pick = h('select', { 'aria-label': '按哪张卡讨论' }, [h('option', { value: '' }, '不指定卡片，让 Agent 匹配'),
    ...data.domains.map((d) => h('optgroup', { label: d.name }, d.cards.map((c) => h('option', { value: c.id }, c.title))))]);
  const say = h('textarea', { 'aria-label': '你的场景和判断', placeholder: '写下你遇到的具体场景，和你自己的初步判断（往哪看、打算怎么做、觉得还有多大空间），Agent 按判断卡点评' });
  const go = h('button', { onclick: async () => {
    if (!say.value.trim()) return ctx.toast('先写一个场景或问题', true);
    go.disabled = true;
    try {
      if (await discuss(ctx, all.find((c) => c.id === pick.value), say.value, true)) say.value = '';
    } catch (e) { ctx.toast(e.message, true); }
    finally { go.disabled = false; }
  } }, [ui.icon('chat'), '和 Agent 讨论']);
  body.append(h('div.card.ln-ask', {}, [h('b', {}, '带着场景来练判断'), h('div.row', { style: { flexWrap: 'wrap', gap: '8px' } }, [pick]), say,
    h('div.row', {}, [h('span.muted', {}, '先写自己的判断再看点评，练得最快 · 对话自动保存，可在右侧续聊'), h('span.grow'), go])]));

  const legend = h('div.kb-legend');
  const grid = h('div.ln-grid');
  body.append(ui.section('判断卡', `${data.domains.length} 个领域 · ${all.length} 个关键问题`), legend, grid);

  const draw = () => {
    legend.replaceChildren(...[['', '全部'], ...data.domains.map((d) => [d.name, `${d.name} ${d.cards.length}`])].map(([v, l]) =>
      h('button' + (domain === v ? '.on' : ''), { onclick: () => { domain = v; draw(); } }, l)));
    grid.replaceChildren(...all.filter((c) => !domain || c.domain === domain).map((c) => card(c)));
  };
  const card = (c) => {
    const isOpen = open === c.id;
    const el = h('div.card.ln-card' + (isOpen ? '.open' : ''), { id: 'ln-' + c.id, onclick: () => { if (!isOpen) { open = c.id; draw(); history.replaceState(null, '', '#kb/lens/' + c.id); } } }, [
      h('h3', {}, [h('span.tag', {}, c.domain), h('span.grow', {}, c.title),
        isOpen ? h('button.ghost', { onclick: (e) => { e.stopPropagation(); open = ''; draw(); history.replaceState(null, '', '#kb/lens'); } }, '收起') : null]),
      h('div.goal', {}, [isOpen ? h('b', {}, '目标函数：') : null, c.goal]),
    ]);
    if (!isOpen) return el;
    el.append(
      h('div.ln-secs', {}, data.sections.slice(1).map((s) => h('div.ln-sec', {}, [h('h4', {}, s.name),
        h('ul', {}, c[s.key].map((x) => h('li', {}, s.key === 'levers' ? [h('b', {}, x.name + '：'), x.how] : x)))]))),
      h('div.ln-drill', {}, [h('b', {}, '练习题：'), c.drill]),
      h('div.ln-src', {}, '参考：' + c.sources.join('；')),
      h('div.ln-acts', {}, [
        h('button', { onclick: () => discuss(ctx, c, `练习题：${c.drill}\n我的判断：`, false) }, [ui.icon('chat'), '作答练习题']),
        h('button.ghost', { onclick: () => discuss(ctx, c, '', false) }, '带自己的场景讨论'),
      ]),
    );
    return el;
  };
  draw();
  if (focus) setTimeout(() => document.getElementById('ln-' + focus)?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 60);
}

async function discuss(ctx, c, text, send) {
  if (chatBusy()) { ctx.toast('当前回复还在生成，请先等它结束或点击停止', true); return false; }
  const opts = { module: 'kb', ref: 'lens:' + (c?.id || ''), title: c ? '判断卡 · ' + c.title : '判断卡' };
  const now = chatSnapshot();
  const keepDraft = now.module === opts.module && now.ref === opts.ref && now.draft.trim();
  await ctx.openChat(send ? { ...opts, fresh: true, send: text } : { ...opts, prefill: keepDraft ? '' : text || '我的场景：\n我的判断：' });
  return true;
}
