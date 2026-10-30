// 外壳：侧边栏 + 页面路由（#<module>）+ 右侧 Agent 对话。
// 板块页面约定：web/modules/<id>.js 导出 default { render(container, ctx) }
//   ctx = { api, h, md, toast, openChat, refresh }；Agent 对话结束会触发 document 'agent-done' 事件，页面可据此刷新。
import { api, h, md, toast, field } from './api.js';
import { initChat, openChat } from './chat.js';

let meta;
const page = document.getElementById('page');

async function boot() {
  initChat(document.getElementById('chat'));
  meta = await api.get('/api/meta');
  const nav = document.getElementById('nav-links');
  for (const m of meta.modules) nav.append(h('a', { href: '#' + m.id, 'data-id': m.id }, m.title));
  document.getElementById('engine-status').textContent =
    Object.entries(meta.engines).map(([k, v]) => `${k}${v ? '✓' : '✗'}`).join(' ');
  window.addEventListener('hashchange', route);
  route();
}

async function route() {
  const id = location.hash.slice(1).split('/')[0] || meta.modules[0]?.id || 'settings';
  document.querySelectorAll('#nav-links a, .nav-foot a').forEach((a) => a.classList.toggle('active', a.getAttribute('href') === '#' + id));
  page.innerHTML = '';
  if (id === 'settings') return renderSettings();
  const m = meta.modules.find((x) => x.id === id);
  if (!m) { page.append(h('p', {}, '未知页面')); return; }
  const body = h('div.page-body');
  // 只重绘页面主体，不重置右侧（可能绑定了某个对象的）对话
  const refresh = async () => { body.innerHTML = ''; await mod.default.render(body, ctx); };
  const ctx = { api, h, md, toast, openChat, refresh, field, module: id, sub: location.hash.slice(1).split('/').slice(1) };
  let mod;
  try {
    mod = await import(`./modules/${id}.js?v=${Date.now()}`);
    openChat({ module: id, title: m.title, expand: false });
    page.append(h('div.page-head', {}, [h('h1', {}, m.title),
      h('button.ghost', { onclick: () => openChat({ module: id, title: m.title }) }, '💬 和 Agent 对话')]));
    page.append(body);
    await mod.default.render(body, ctx);
  } catch (e) {
    console.error(e);
    page.append(h('pre.error', {}, `加载板块 ${id} 失败：${e.message}`));
  }
}

async function renderSettings() {
  const s = await api.get('/api/settings');
  page.append(h('div.page-head', {}, [h('h1', {}, '设置')]));
  const focus = h('input', { value: s.focus_windows.map((w) => `${w.start}-${w.end}`).join(', ') });
  const conc = h('input', { type: 'number', value: s.max_agent_concurrency, min: 1, max: 10 });
  const eng = h('select', {}, ['claude', 'codex'].map((e) => h('option', { value: e, selected: s.engines.default === e }, e)));
  const codexModel = h('input', { value: s.engines.codex.model || '', placeholder: '留空=codex 默认模型' });
  const claudeModel = h('input', { value: s.engines.claude.model || '', placeholder: '留空=claude 默认模型' });
  const repos = h('textarea', { rows: 4, value: (s.repos || []).join('\n'), placeholder: '每行一个目录：复盘时分析的代码库/文档' });
  const raw = h('textarea.mono', { rows: 16, value: JSON.stringify(s, null, 2) });
  const save = async (body) => { await api.put('/api/settings', body); toast('已保存'); route(); };
  page.append(h('div.card', {}, [
    field('人重度干预时间窗（专注时间）', focus),
    field('Agent 并发度', conc),
    field('默认引擎', eng),
    field('Claude 模型', claudeModel),
    field('Codex 模型', codexModel),
    field('复盘分析目录', repos),
    h('button.primary', { onclick: () => save({
      focus_windows: focus.value.split(',').map((x) => x.trim()).filter(Boolean).map((x) => { const [start, end] = x.split('-'); return { start: start.trim(), end: end.trim() }; }),
      max_agent_concurrency: +conc.value,
      engines: { default: eng.value, codex: { model: codexModel.value.trim() }, claude: { model: claudeModel.value.trim() } },
      repos: repos.value.split('\n').map((x) => x.trim()).filter(Boolean),
    }) }, '保存'),
  ]), h('details.card', {}, [h('summary', {}, '全部设置（JSON）'), raw,
    h('button', { onclick: () => { try { save(JSON.parse(raw.value)); } catch (e) { toast('JSON 错误：' + e.message, true); } } }, '保存 JSON')]));
}

boot();
