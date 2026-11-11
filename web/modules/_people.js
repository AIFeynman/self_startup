// 信息推荐 ·「人物」：名单里的人最近在 X / YouTube / 播客 / 论文 / 新闻 / B站 的发声，按人归组（后端见 app/modules/_people.py）。
// 路由：#feed/people
const CSS = `
.pp-bar { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin: 4px 0 12px; }
.pp-chans { display: flex; flex-wrap: wrap; gap: 6px; font-size: 12px; color: var(--muted); }
.pp-chan { border: 1px solid var(--line); border-radius: 999px; padding: 1px 9px; background: var(--panel); }
.pp-chan.err { border-color: var(--warn, #b7791f); color: var(--warn, #b7791f); }
.pp-grp { padding: 12px 16px; margin-bottom: 10px; }
.pp-who { display: flex; flex-wrap: wrap; align-items: baseline; gap: 4px 10px; margin-bottom: 6px; }
.pp-who b { font-size: 15.5px; }
.pp-who a { font-size: 12.5px; }
.pp-role { color: var(--muted); font-size: 12.5px; }
.pp-it { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; gap: 2px 10px; align-items: baseline; padding: 6px 0; border-top: 1px dashed var(--line); }
.pp-it:first-of-type { border-top: 0; }
.pp-it .t { min-width: 0; }
.pp-it .t a { color: var(--text); font-size: 14px; }
.pp-it .t a:hover { color: var(--accent); }
.pp-it .m { color: var(--muted); font-size: 12px; }
.pp-it .s { color: var(--muted); font-size: 12.5px; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.pp-ch { font-size: 11.5px; border-radius: 6px; padding: 1px 7px; background: var(--accent-soft); color: var(--accent); white-space: nowrap; }
.pp-people { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 8px; }
.pp-people button { text-align: left; border: 1px solid var(--line); background: var(--panel); border-radius: 8px; padding: 8px 12px; color: var(--text); }
.pp-people button:hover { border-color: var(--accent); }
.pp-people small { display: block; color: var(--muted); font-size: 12px; }
.pp-more { font-size: 12.5px; }
@media (max-width: 640px) { .pp-it { grid-template-columns: minmax(0, 1fr) auto; } .pp-it .pp-ch { grid-column: 1 / -1; justify-self: start; } }
`;

const CH = { x: 'X', youtube: 'YouTube', podcast: '播客', paper: '论文', news: '新闻', bili: 'B站' };
// 视频和播客深读时才转写：播客传音频直链，按视频走字幕 / whisper
const DEEP = new Set(['youtube', 'podcast', 'paper', 'news', 'bili']);
const state = { view: 'today', person: '' };
const safeUrl = (u) => (/^https?:\/\//i.test(u || '') ? u : '#');

export function peopleTab(box, ctx, sub = '') {
  const { api, h, ui, toast } = ctx;
  if (!document.getElementById('pp-style')) document.head.append(h('style#pp-style', {}, CSS));
  if (sub) { state.view = 'person'; state.person = sub; }
  let polling = false;

  const ago = (t) => {
    if (!t) return '没跑过';
    const m = Math.round((Date.now() - new Date(t.replace(' ', 'T')).getTime()) / 60000);
    return m < 60 ? `${Math.max(m, 0)} 分钟前` : m < 1440 ? `${Math.round(m / 60)} 小时前` : `${Math.round(m / 1440)} 天前`;
  };
  const who = (p) => (p.zh && p.zh !== p.name ? `${p.zh} ${p.name}` : p.name);

  async function deep(it, btn) {
    btn.disabled = true;
    try {
      const audio = it.channel === 'podcast' && /^https?:\/\//i.test(it.extra.audio || '');
      const r = await api.post('/api/learn/items', audio ? { url: it.extra.audio, kind: 'video', reuse: true } : { url: it.url, reuse: true });
      if (r.status === 'done') location.hash = `#learn/item/${r.id}`;
      else { btn.textContent = '解析中'; toast('已开始深读，完成后会提醒'); }
    } catch (e) { btn.disabled = false; toast('开始深读失败：' + e.message, true); }
  }

  const meta = (it) => [it.date ? it.date.slice(5, 16).replace('T', ' ') : '', it.extra.uploader || it.extra.outlet || it.extra.show || '',
    it.channel === 'x' && it.popularity ? `${it.popularity} 赞` : ''].filter(Boolean).join(' · ');
  const row = (it, showPeople = false, idx = {}) => {
    const b = DEEP.has(it.channel) ? h('button.ghost.sm', { onclick: (e) => deep(it, e.currentTarget) }, '深读') : h('span');
    return h('div.pp-it', {}, [
      h('span.pp-ch', {}, CH[it.channel] || it.channel),
      h('div.t', {}, [h('a', { href: safeUrl(it.url), target: '_blank', rel: 'noopener' }, it.title),
        h('div.m', {}, [meta(it), showPeople ? ' · ' + it.people.map((p) => idx[p] ? who(idx[p]) : p).join('、') : '']),
        it.summary && it.channel !== 'x' ? h('div.s', {}, it.summary) : null]),
      b,
    ]);
  };

  function bar(s) {
    const seg = (id, name) => h('button' + (state.view === id ? '.on' : ''), { onclick: () => { state.view = id; state.person = ''; load(); } }, name);
    const refresh = h('button.ghost.sm', { disabled: s.running, onclick: async () => {
      try {
        const r = await api.post('/api/feed/people/refresh', { channels: [] });
        toast(r.started ? '开始按人名搜各渠道，几分钟后出结果' : r.running ? '正在搜索中' : '各渠道刚搜过，稍后再试');
        if (r.started || r.running) poll();
      } catch (e) { toast(e.message, true); }
    } }, [ui.icon('refresh'), s.running ? '搜索中…' : '立即搜一轮']);
    return h('div.pp-bar', {}, [h('div.fd-seg', {}, [seg('today', '今天'), seg('week', '近 7 天'), seg('all', '按人')]), refresh,
      h('div.pp-chans', {}, s.channels.map((c) => h('span.pp-chan' + (c.errors?.length ? '.err' : ''), { title: (c.errors || []).join('\n') || `每 ${c.hours} 小时一轮` },
        `${c.name} · ${ago(c.at)}${c.at ? ` · ${c.count} 条` : ''}${c.errors?.length ? ' · 有错误' : ''}`)))]);
  }

  async function poll() {
    if (polling) return;
    polling = true;
    try {
      for (;;) {
        await new Promise((r) => setTimeout(r, 4000));
        if (!box.isConnected) return;
        const s = await api.get('/api/feed/people/status');
        if (!s.running) { await load(); return; }
      }
    } finally { polling = false; }
  }

  async function load() {
    if (state.view === 'person' && state.person) {
      const r = await api.get('/api/feed/people?person=' + encodeURIComponent(state.person));
      const p = r.person || { name: state.person };
      box.replaceChildren(bar(r), h('div.card.pp-grp', {}, [
        h('div.pp-who', {}, [h('a', { href: '#', onclick: (e) => { e.preventDefault(); state.view = 'all'; load(); } }, '← 全部人物'), h('b', {}, who(p)),
          h('span.pp-role', {}, p.role || ''), p.x ? h('a', { href: `https://x.com/${p.x}`, target: '_blank', rel: 'noopener' }, '@' + p.x) : null]),
        ...(r.items.length ? r.items.map((it) => row(it)) : [h('div.muted', {}, '还没搜到这个人的发声')])]));
      if (r.running) poll();
      return;
    }
    const days = state.view === 'week' ? 7 : state.view === 'all' ? 30 : 1;
    const r = await api.get('/api/feed/people?days=' + days);
    const idx = Object.fromEntries(r.people.map((p) => [p.id, p]));
    const open = (pid) => { state.view = 'person'; state.person = pid; load(); };
    if (state.view === 'all') {
      const ps = [...r.people].sort((a, b) => a.tier - b.tier || b.total - a.total);
      box.replaceChildren(bar(r), h('div.pp-people', {}, ps.map((p) => h('button', { onclick: () => open(p.id) }, [
        h('b', {}, who(p)), h('small', {}, `Tier${p.tier} · ${p.group} · ${p.total} 条`)]))));
    } else {
      const n = r.groups.reduce((s, g) => s + g.items.length, 0);
      box.replaceChildren(bar(r), r.groups.length ? h('div.muted', { style: { fontSize: '12.5px', margin: '0 0 8px' } },
        `${days === 1 ? '最近 24 小时' : '最近 7 天'}新发现 ${r.groups.length} 人 · ${n} 条 · Tier1 在前`) : ui.empty('这段时间还没发现新发声', '点「立即搜一轮」，或等自动搜索（X 每 3 小时，其他渠道 6–12 小时）'),
      ...r.groups.map((g) => {
        const items = g.items.slice(0, 6);
        return h('div.card.pp-grp', {}, [
          h('div.pp-who', {}, [h('b', {}, who(g.person)), h('span.pp-role', {}, `Tier${g.person.tier || ''} · ${g.person.role || ''}`),
            h('a', { href: '#', onclick: (e) => { e.preventDefault(); open(g.person.id); } }, `时间线 →`)]),
          ...items.map((it) => row(it, it.people.length > 1, idx)),
          g.items.length > items.length ? h('a.pp-more', { href: '#', onclick: (e) => { e.preventDefault(); open(g.person.id); } }, `还有 ${g.items.length - items.length} 条`) : null,
        ]);
      }));
    }
    if (r.running) poll();
  }
  return load();
}
