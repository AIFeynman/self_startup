// 信息推荐 ·「名人」：名单里的人最近在 X / YouTube / 播客 / 论文 / 新闻 / B站 的发声，按人归组（后端见 app/modules/_people.py）。
// 路由：#feed/people、#feed/people/methods（高人方法）、#feed/people/<人物 id>、#feed/people/batch/<提醒批次>（点提醒进来，只看那一次提醒里的发声）
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
.pp-it .g { font-size: 13.5px; line-height: 1.55; margin-top: 2px; }
.pp-it .s { color: var(--muted); font-size: 12.5px; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.pp-ch { font-size: 11.5px; border-radius: 6px; padding: 1px 7px; background: var(--accent-soft); color: var(--accent); white-space: nowrap; }
.pp-pin { border-color: var(--accent); }
.pp-pin > b, .pp-batch > b { display: block; margin-bottom: 4px; }
.pp-batch { border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-soft); }
.pp-it.pp-focus { background: var(--accent-soft); border-radius: 8px; box-shadow: 0 0 0 6px var(--accent-soft); }
.pp-pin > b small, .pp-batch > b small { color: var(--muted); font-weight: 400; font-size: 12px; margin-left: 6px; }
.pp-people { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 8px; }
.pp-people button { text-align: left; border: 1px solid var(--line); background: var(--panel); border-radius: 8px; padding: 8px 12px; color: var(--text); }
.pp-people button:hover { border-color: var(--accent); }
.pp-people small { display: block; color: var(--muted); font-size: 12px; }
.pp-more { font-size: 12.5px; }
.pp-it a.pp-done, .pp-it a.muted { font-size: 12.5px; white-space: nowrap; }
.pm-head { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin: 0 0 10px; font-size: 12.5px; color: var(--muted); }
.pm-add { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
.pm-add select { flex: 0 1 220px; min-width: 0; }
.pm-add input { min-width: 0; flex: 1 1 240px; }
.pm-m { padding: 10px 0; border-top: 1px dashed var(--line); }
.pm-m:first-of-type { border-top: 0; }
.pm-name { display: flex; flex-wrap: wrap; gap: 4px 8px; align-items: baseline; }
.pm-name b { font-size: 14.5px; }
.pm-tag { font-size: 11.5px; border-radius: 6px; padding: 1px 7px; background: var(--accent-soft); color: var(--accent); white-space: nowrap; }
.pm-tag.weak { background: var(--panel); color: var(--muted); border: 1px solid var(--line); }
.pm-how { font-size: 13.5px; line-height: 1.6; margin-top: 3px; }
.pm-why, .pm-try { font-size: 12.5px; color: var(--muted); line-height: 1.55; margin-top: 2px; }
.pm-try b { color: var(--text); font-weight: 500; }
.pm-ev { font-size: 12.5px; margin-top: 4px; }
.pm-ev summary { cursor: pointer; color: var(--muted); }
.pm-ev li { margin: 4px 0; line-height: 1.5; overflow-wrap: anywhere; }
.pm-ev q { color: var(--text); }
@media (max-width: 640px) { .pp-it { grid-template-columns: minmax(0, 1fr) auto; } .pp-it .pp-ch { grid-column: 1 / -1; justify-self: start; } }
`;

const CH = { x: 'X', blog: '博客', youtube: 'YouTube', podcast: '播客', paper: '论文', news: '新闻', bili: 'B站' };
// 视频和播客深读时才转写：播客传音频直链，按视频走字幕 / whisper
const DEEP = new Set(['blog', 'youtube', 'podcast', 'paper', 'news', 'bili']);
const state = { view: 'today', person: '', batch: '', focus: '' };
const KIND = { own: '本人', retell: '转述', link: '访谈 / 报道' };
const safeUrl = (u) => (/^https?:\/\//i.test(u || '') ? u : '#');

export function peopleTab(box, ctx, sub = []) {
  const { api, h, ui, toast } = ctx;
  if (!document.getElementById('pp-style')) document.head.append(h('style#pp-style', {}, CSS));
  if (sub[0] === 'batch' && sub[1]) { state.view = 'batch'; state.batch = sub[1]; state.focus = sub[2] ? decodeURIComponent(sub[2]) : ''; }
  else if (sub[0] === 'methods') state.view = 'methods';
  else if (sub[0]) { state.view = 'person'; state.person = sub[0]; }
  else if (state.view === 'batch') state.view = 'today';
  const go = (view, person = '') => {
    state.view = view; state.person = person;
    const want = view === 'methods' ? '#feed/people/methods' : '#feed/people';
    if (location.hash !== want) history.replaceState(history.state, '', want);
    load();
  };
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
      it.learn = { id: r.id, status: r.status };
      if (r.status === 'done') location.hash = `#learn/item/${r.id}`;
      else { btn.replaceWith(deepBtn(it)); toast('已开始深读，解析完会弹提醒（含系统通知）'); }
    } catch (e) { btn.disabled = false; toast('开始深读失败：' + e.message, true); }
  }

  const when = (d) => {
    if (!/(Z|[+-]\d\d:\d\d)$/.test(d)) return d.slice(5, 16).replace('T', ' ');
    const t = new Date(d), p = (n) => String(n).padStart(2, '0');
    return `${p(t.getMonth() + 1)}-${p(t.getDate())} ${p(t.getHours())}:${p(t.getMinutes())}`;
  };
  const meta = (it) => [it.date ? when(it.date) : '', it.extra.uploader || it.extra.outlet || it.extra.show || it.extra.site || '',
    it.channel === 'x' && it.popularity ? `${it.popularity} 赞` : ''].filter(Boolean).join(' · ');
  const deepBtn = (it) => {
    if (!DEEP.has(it.channel)) return h('span');
    if (it.learn?.status === 'done') return h('a.pp-done', { href: `#learn/item/${it.learn.id}`, title: '已经深读过，打开笔记' }, '看笔记');
    if (it.learn) return h('a.muted', { href: `#learn/item/${it.learn.id}`, title: '深读解析中，完成后会提醒' }, '解析中');
    return h('button.ghost.sm', { onclick: (e) => deep(it, e.currentTarget) }, '深读');
  };
  const row = (it, showPeople = false, idx = {}) => {
    const b = deepBtn(it);
    return h('div.pp-it', { 'data-id': it.id }, [
      h('span.pp-ch', {}, CH[it.channel] || it.channel),
      h('div.t', {}, [h('a', { href: safeUrl(it.url), target: '_blank', rel: 'noopener' }, it.title),
        h('div.m', {}, [meta(it), showPeople ? ' · ' + it.people.map((p) => idx[p] ? who(idx[p]) : p).join('、') : '']),
        it.extra.gist ? h('div.g', {}, it.extra.gist) : it.summary && it.channel !== 'x' ? h('div.s', {}, it.summary) : null]),
      b,
    ]);
  };

  function bar(s) {
    const seg = (id, name) => h('button' + (state.view === id ? '.on' : ''), { onclick: () => go(id) }, name);
    const refresh = h('button.ghost.sm', { disabled: s.running, onclick: async () => {
      try {
        const r = await api.post('/api/feed/people/refresh', { channels: [] });
        toast(r.started ? '开始按人名搜各渠道，几分钟后出结果' : r.running ? '正在搜索中' : '各渠道刚搜过，稍后再试');
        if (r.started || r.running) poll();
      } catch (e) { toast(e.message, true); }
    } }, [ui.icon('refresh'), s.running ? '搜索中…' : '立即搜一轮']);
    return h('div.pp-bar', {}, [h('div.fd-seg', {}, [seg('today', '今天'), seg('week', '近 7 天'), seg('all', '按人'), seg('methods', '高人方法')]), refresh,
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

  const method = (m) => h('div.pm-m', {}, [
    h('div.pm-name', {}, [h('b', {}, m.name),
      h('span.pm-tag' + (m.own ? '' : '.weak'), { title: m.own ? '有本人发的推文 / 文章' : '只找到别人的转述，可能失真' }, m.own ? '本人原话' : '仅转述'),
      m.retellers ? h('span.pm-tag.weak', {}, `${m.retellers} 人转述`) : null,
      h('a', { href: safeUrl(m.origin.url), target: '_blank', rel: 'noopener', style: { fontSize: '12.5px' } }, `出处 · ${KIND[m.origin.kind]} ${m.origin.date || ''}`)]),
    h('div.pm-how', {}, m.how),
    m.why ? h('div.pm-why', {}, '为什么有效：' + m.why) : null,
    m.try ? h('div.pm-try', {}, [h('b', {}, '今天就能试：'), m.try]) : null,
    h('details.pm-ev', {}, [h('summary', {}, `原话与出处 ${m.evidence.length} 条`), h('ul', {}, m.evidence.map((e) => h('li', {}, [
      h('span.pm-tag.weak', {}, KIND[e.kind]), ' ', h('q', {}, e.quote), ' — ',
      h('a', { href: safeUrl(e.url), target: '_blank', rel: 'noopener' }, `${e.kind === 'link' ? '' : '@'}${e.author}${e.date ? ' · ' + e.date : ''}`)])))]),
  ]);

  async function methods() {
    const [r, ps] = await Promise.all([api.get('/api/feed/people/methods'), api.get('/api/feed/people?days=1')]);
    const idx = Object.fromEntries(ps.people.map((p) => [p.id, p]));
    const sel = h('select', {}, [...ps.people].sort((a, b) => a.tier - b.tier).map((p) => h('option', { value: p.id }, who(p))));
    const url = h('input', { type: 'url', placeholder: '访谈 / 博客链接，下次提炼时抓正文' });
    const add = h('button.ghost.sm', { onclick: async () => {
      try { await api.post('/api/feed/people/methods/links', { url: url.value, person: sel.value }); url.value = ''; toast('已加入，点「重新提炼」生效'); }
      catch (e) { toast(e.message, true); }
    } }, '加链接');
    const run = h('button.ghost.sm', { disabled: r.running, onclick: async () => {
      try { const x = await api.post('/api/feed/people/methods/run', {}); toast(x.started ? '开始提炼，名单里的人都过一遍，要一阵子' : '正在提炼中'); mpoll(); }
      catch (e) { toast(e.message, true); }
    } }, [ui.icon('refresh'), r.running ? `提炼中 · ${r.stage_name} ${r.step}/${r.steps}` : '重新提炼']);
    const d = r.data;
    const src = d ? `${d.n} 个方法 · 材料：本人高赞推文 ${d.sources.own} 条、点名转述 ${d.sources.retell} 篇、访谈链接 ${d.sources.link} 篇` : '还没提炼过';
    box.replaceChildren(bar(ps), h('div.pm-head', {}, [h('span', {}, `名人自己提出、推荐或在用的做法，带原话和出处 · ${src}`), run,
      r.error ? h('span', { style: { color: 'var(--warn, #b7791f)' } }, r.error) : null]),
    h('div.pm-add', { style: { marginBottom: '12px' } }, [sel, url, add]),
    ...(d?.people.length ? d.people.map((g) => h('div.card.pp-grp', {}, [
      h('div.pp-who', {}, [h('b', {}, who(idx[g.person.id] || g.person)), h('span.pp-role', {}, `Tier${g.person.tier} · ${g.person.role || ''} · ${g.methods.length} 个方法`)]),
      ...g.methods.map(method)])) : [ui.empty('还没有方法卡', '点「重新提炼」，从名人的高赞推文、点名转述的长文和你加的访谈链接里抽')]));
    if (r.running) mpoll();
  }

  let mpolling = false;
  async function mpoll() {
    if (mpolling) return;
    mpolling = true;
    try {
      for (;;) {
        await new Promise((r) => setTimeout(r, 5000));
        if (!box.isConnected || state.view !== 'methods') return;
        const s = await api.get('/api/feed/people/methods');
        if (!s.running) { await methods(); return; }
      }
    } finally { mpolling = false; }
  }

  async function load() {
    if (state.view === 'methods') return methods();
    if (state.view === 'person' && state.person) {
      const r = await api.get('/api/feed/people?person=' + encodeURIComponent(state.person));
      const p = r.person || { name: state.person };
      box.replaceChildren(bar(r), h('div.card.pp-grp', {}, [
        h('div.pp-who', {}, [h('a', { href: '#', onclick: (e) => { e.preventDefault(); go('all'); } }, '← 全部名人'), h('b', {}, who(p)),
          h('span.pp-role', {}, p.role || ''), p.x ? h('a', { href: `https://x.com/${p.x}`, target: '_blank', rel: 'noopener' }, '@' + p.x) : null]),
        ...(r.items.length ? r.items.map((it) => row(it)) : [h('div.muted', {}, '还没搜到这个人的发声')])]));
      if (r.running) poll();
      return;
    }
    if (state.view === 'batch') {
      const r = await api.get('/api/feed/people?batch=' + encodeURIComponent(state.batch));
      const idx = Object.fromEntries(r.people.map((p) => [p.id, p]));
      box.replaceChildren(bar(r), h('div.card.pp-grp.pp-batch', {}, [
        h('b', {}, ['这次提醒的发声', h('small', {}, `${r.batch.length} 条 · Tier1 在前`)]),
        ...(r.batch.length ? r.batch.map((it) => row(it, true, idx)) : [h('div.muted', {}, '这次提醒里的条目已经被过滤掉了')]),
        h('a.pp-more', { href: '#', onclick: (e) => { e.preventDefault(); go('today'); } }, '看今天全部 →')]));
      const want = r.batch.find((it) => it.id === state.focus) || r.batch[0];
      const hit = want && [...box.querySelectorAll('.pp-it')].find((e) => e.dataset.id === want.id);
      if (hit) {
        hit.classList.add('pp-focus');
        [0, 300, 900, 1800].forEach((ms) => setTimeout(() => { if (hit.isConnected) hit.scrollIntoView({ block: 'center' }); }, ms));
      }
      if (r.running) poll();
      return;
    }
    const days = state.view === 'week' ? 7 : state.view === 'all' ? 30 : 1;
    const r = await api.get('/api/feed/people?days=' + days);
    const idx = Object.fromEntries(r.people.map((p) => [p.id, p]));
    const open = (pid) => go('person', pid);
    if (state.view === 'all') {
      const ps = [...r.people].sort((a, b) => a.tier - b.tier || b.total - a.total);
      box.replaceChildren(bar(r), h('div.pp-people', {}, ps.map((p) => h('button', { onclick: () => open(p.id) }, [
        h('b', {}, who(p)), h('small', {}, `Tier${p.tier} · ${p.group} · ${p.total} 条`)]))));
    } else {
      const n = r.groups.reduce((s, g) => s + g.items.length, 0);
      const pin = r.pinned.length ? h('div.card.pp-grp.pp-pin', {}, [h('b', {}, ['置顶 · 核心长文与视频', h('small', {}, `${days === 1 ? '最近 24 小时发布' : '近 7 天发布'} ${r.pinned.length} 条 · 博客长文、X 长文、论文、本人出镜的访谈 / 演讲 / 播客`)]),
        ...r.pinned.map((it) => row(it, true, idx))]) : null;
      box.replaceChildren(bar(r), pin || '', r.groups.length ? h('div.muted', { style: { fontSize: '12.5px', margin: '0 0 8px' } },
        `${days === 1 ? '最近 24 小时' : '最近 7 天'}其他新发现 ${r.groups.length} 人 · ${n} 条 · Tier1 在前`) : pin ? '' : ui.empty('这段时间还没发现新发声', '点「立即搜一轮」，或等自动搜索（X 每 3 小时，其他渠道 6–12 小时）'),
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
