// 便签：用户自己写的灵感和感想，按天贴在时间线上。类型可以自己加，便签之间可以连线，可以引用来源文章。
// 系统记的问题与经验在「复盘」；数据都在 review_notes，靠 author 区分。
import { kindChips, kindColor } from '../ui.js';
import { noteHtml } from '../api.js';
import { FOCUS_KEY } from './_annotate.js';

const KIND_KEY = 'note-kind'; // 上次选的类型
const short = (t, n = 18) => (t.length > n ? t.slice(0, n) + '…' : t);
const WEEK = '日一二三四五六';
const dayLabel = (s) => { const d = new Date(s + 'T12:00:00'); return { day: `${d.getMonth() + 1}月${d.getDate()}日`, week: `周${WEEK[d.getDay()]}` }; };

export default {
  async render(el, { api, h, toast, ui, sub }) {
    injectStyle();
    let notes = [], links = [], kinds = [], rels = [];
    let selected = +sub?.[0] || null, linking = false, filter = '', query = '';
    let composeKind = (() => { try { return localStorage.getItem(KIND_KEY) || 'spark'; } catch { return 'spark'; } })();
    let pending = [], pickingCompose = false, pickingNote = false;

    const load = async () => {
      const r = await api.get('/api/notes');
      ({ notes, links, kinds, rels } = r);
      if (selected && !notes.some((n) => n.id === selected)) selected = null;
      paint();
    };
    const labelOf = (k) => kinds.find((x) => x.key === k)?.label || k;
    const linksOf = (id) => links.filter((l) => l.a === id || l.b === id);
    const matches = (n) => (!filter || n.kind === filter) && (!query
      || `${n.text} ${n.tags} ${n.sources.map((s) => s.title).join(' ')}`.toLowerCase().includes(query.toLowerCase()));

    // ---------- 引用文章 ----------
    function picker(onPick) {
      const results = h('div.sn-results');
      const search = async () => {
        const v = input.value.trim();
        const found = await api.get(`/api/notes/sources?q=${encodeURIComponent(v)}`).catch(() => []);
        results.replaceChildren(...(found.length ? found.map((s) => h('button.sn-pick', { onclick: () => onPick(s) }, [h('b', {}, s.type), s.title]))
          : [h('div.muted', {}, '没找到，可以直接粘贴链接')]));
      };
      const input = h('input', { placeholder: '搜平台里的文章，或粘贴链接', 'aria-label': '搜索要引用的文章',
        oninput: () => { clearTimeout(input._t); input._t = setTimeout(search, 200); } });
      search();
      setTimeout(() => input.focus());
      return h('div.sn-picker', {}, [input, results]);
    }
    const focusOn = (s) => { if (s.annotation_id) { try { sessionStorage.setItem(FOCUS_KEY, String(s.annotation_id)); } catch { /* ignore */ } } };
    const srcLink = (s) => (s.link
      ? h('a', { ...(s.link.startsWith('#') ? { href: s.link } : { href: s.link, target: '_blank', rel: 'noopener' }), onclick: () => focusOn(s) }, s.title)
      : h('span', {}, s.title));
    const srcRow = (s, onRemove) => h('div.sn-src', {}, [
      h('span', {}, [h('b', {}, s.type), srcLink(s)]),
      h('button.sn-x', { onclick: onRemove }, '移除'),
      s.quote ? h('blockquote', {}, s.quote) : null,
    ]);

    // ---------- 写一张 ----------
    const ta = h('textarea', { rows: 2, placeholder: '突然想到什么，写下来…  Enter 贴上墙，Shift+Enter 换行，#标签' });
    const compKinds = h('div.sn-row');
    const compSrc = h('div');
    const post = async () => {
      const text = ta.value.trim();
      if (!text) return;
      try {
        const n = await api.post('/api/notes', { text, kind: composeKind, sources: pending });
        ta.value = ''; pending = []; pickingCompose = false;
        selected = n.id;
        try { localStorage.setItem(KIND_KEY, composeKind); } catch { /* ignore */ }
        await load();
      } catch (e) { toast(e.message, true); }
    };
    ta.addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); post(); } });
    function paintCompose() {
      compKinds.replaceChildren(
        kindChips(kinds, composeKind, (k) => { composeKind = k; paintCompose(); }),
        h('button.sn-chip.add', { onclick: () => { pickingCompose = !pickingCompose; paintCompose(); } }, '+ 引用文章'),
        h('button.primary.sm.sn-post', { onclick: post }, '贴上墙'),
      );
      compSrc.replaceChildren(...pending.map((s, i) => srcRow(s, () => { pending.splice(i, 1); paintCompose(); })),
        ...(pickingCompose ? [picker((s) => { pending.push(s); pickingCompose = false; paintCompose(); })] : []));
    }

    // ---------- 墙 ----------
    const filters = h('div.sn-filters');
    const search = h('input', { type: 'search', placeholder: '搜索便签', 'aria-label': '搜索便签',
      oninput: () => { query = search.value.trim(); paintBoard(); } });
    function paintFilters() {
      const used = kinds.filter((k) => k.count);
      filters.replaceChildren(search, h('button.sn-chip' + (!filter ? '.on' : ''), { onclick: () => { filter = ''; paint(); } }, `全部 ${notes.length}`),
        ...used.map((k) => h('button.sn-chip' + (filter === k.key ? '.on' : ''), { onclick: () => { filter = k.key; paint(); } },
          [h(`i.kc${kindColor(k.key, kinds)}`), `${k.label} ${k.count}`])));
    }
    const lines = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    lines.setAttribute('aria-hidden', 'true');
    const days = h('div');
    const board = h('div.sn-board', {}, [lines, days]);
    function noteEl(n) {
      const cnt = linksOf(n.id).length;
      const related = selected && linksOf(selected).some((l) => l.a === n.id || l.b === n.id);
      const state = n.id === selected ? '.sel' : selected && !linking ? (related ? '.rel' : '.dim') : '';
      return h(`button.sn-note.sn-c${kindColor(n.kind, kinds)}${state}`, { 'data-note': n.id, onclick: () => clickNote(n.id) }, [
        h('span.txt', {}, noteHtml(n.text)),
        n.sources.length ? h('span.src', {}, `出处：${short(n.sources[0].title)}${n.sources.length > 1 ? ` 等 ${n.sources.length} 篇` : ''}`) : null,
        h('span.meta', {}, [h('em', {}, labelOf(n.kind)), h('span', {}, (n.created_at || '').slice(11, 16)),
          n.tags ? h('span', {}, n.tags.split(',').filter(Boolean).map((t) => '#' + t).join(' ')) : null,
          h('span.grow'), cnt ? h('span', {}, `↔ ${cnt}`) : null]),
      ]);
    }
    async function clickNote(id) {
      if (linking) {
        if (id === selected) return;
        try {
          await api.post(`/api/notes/${selected}/links`, { to: id });
          linking = false;
          await load();
        } catch (e) { toast(e.message, true); }
        return;
      }
      selected = selected === id ? null : id;
      pickingNote = false;
      paintBoard(); paintSide();
    }
    function paintBoard() {
      const shown = notes.filter(matches);
      const dates = [...new Set(shown.map((n) => n.date))];
      days.replaceChildren(...(dates.length ? dates.map((d) => {
        const l = dayLabel(d);
        return h('div.sn-day', {}, [h('div.sn-day-label', {}, [h('b', {}, l.day), h('span', {}, l.week)]),
          h('div.sn-notes', {}, shown.filter((n) => n.date === d).map(noteEl))]);
      }) : [notes.length ? ui.empty('没有符合条件的便签') : ui.empty('还没有便签', '在上面写一句，或者在任何页面按 ⌘K')]));
      requestAnimationFrame(drawLines);
    }
    function drawLines() {
      lines.innerHTML = '';
      if (!selected || linking || !board.isConnected) return;
      const box = board.getBoundingClientRect();
      const center = (id) => {
        const n = board.querySelector(`[data-note="${id}"]`);
        if (!n) return null;
        const r = n.getBoundingClientRect();
        return { x: r.left + r.width / 2 - box.left, y: r.top + r.height / 2 - box.top };
      };
      const from = center(selected);
      if (!from) return;
      lines.innerHTML = linksOf(selected).map((l) => {
        const to = center(l.a === selected ? l.b : l.a);
        if (!to) return '';
        const dir = Math.sign(to.y - from.y || 1), bend = Math.min(60, Math.abs(to.y - from.y) / 2 + 20);
        return `<path d="M${from.x} ${from.y} C${from.x} ${from.y + dir * bend}, ${to.x} ${to.y - dir * bend}, ${to.x} ${to.y}"/><circle cx="${to.x}" cy="${to.y}" r="3.5"/>`;
      }).join('');
    }

    // ---------- 选中便签的详情 ----------
    const side = h('aside.sn-side');
    const patch = async (id, d) => { try { await api.patch(`/api/notes/${id}`, d); await load(); } catch (e) { toast(e.message, true); } };
    function paintSide() {
      const n = notes.find((x) => x.id === selected);
      side.classList.toggle('idle', !n);
      if (!n) {
        side.replaceChildren(h('h2', {}, '选一张便签'), h('div.muted', {}, '点任意一张，可以改内容和类型、引用文章，也可以和别的便签连起来。'));
        return;
      }
      const edit = h('textarea', { rows: 4, value: n.text, 'aria-label': '便签内容' });
      const saveBtn = h('button.primary.sm', { hidden: true, onclick: () => patch(n.id, { text: edit.value }) }, '保存');
      const fitContent = () => { edit.style.height = 'auto'; edit.style.height = `${edit.scrollHeight + edit.offsetHeight - edit.clientHeight}px`; };
      new ResizeObserver(fitContent).observe(edit);
      edit.oninput = () => { saveBtn.hidden = edit.value.trim() === n.text; fitContent(); };
      const rows = linksOf(n.id).map((l) => {
        const other = notes.find((x) => x.id === (l.a === n.id ? l.b : l.a));
        if (!other) return null;
        const sel = h('select', { 'aria-label': '关系类型', onchange: async () => { await api.patch(`/api/notes/links/${l.id}`, { rel: sel.value }); l.rel = sel.value; } },
          rels.map((x) => h('option', x === l.rel ? { selected: true } : {}, x)));
        return h('div.sn-link', {}, [sel,
          h('a', { href: `#notes/${other.id}`, title: other.text, onclick: (e) => { e.preventDefault(); selected = other.id; paintBoard(); paintSide(); } }, short(other.text)),
          h('button.sn-x', { onclick: async () => { await api.del(`/api/notes/links/${l.id}`); await load(); } }, '解除')]);
      }).filter(Boolean);
      side.replaceChildren(
        h('div', {}, [h('div.sn-label', {}, `${n.date} ${(n.created_at || '').slice(11, 16)}`), edit, saveBtn]),
        h('div', {}, [h('div.sn-label', {}, '类型'), kindChips(kinds, n.kind, (k) => patch(n.id, { kind: k }))]),
        h('div', {}, [h('div.sn-label', {}, `来源文章（${n.sources.length}）`),
          ...n.sources.map((s, i) => srcRow(s, () => patch(n.id, { sources: n.sources.filter((_, j) => j !== i) }))),
          pickingNote ? picker((s) => { pickingNote = false; patch(n.id, { sources: [...n.sources, s] }); })
            : h('button.ghost.sm', { onclick: () => { pickingNote = true; paintSide(); } }, '引用文章')]),
        h('div', {}, [h('div.sn-label', {}, `关系（${rows.length}）`), ...(rows.length ? rows : [h('div.muted', {}, '还没有连到别的便签。')])]),
        linking ? h('div', {}, [h('div.sn-hint', {}, '现在点另一张便签，就连上了'), h('button.ghost.sm', { onclick: () => { linking = false; paint(); } }, '取消')])
          : h('button.ghost.sm', { onclick: () => { linking = true; paint(); } }, '连到另一张便签'),
        h('div.sn-row.foot', {}, [
          h('button.sn-x', { title: '这条不是你自己写的：移回复盘的问题与经验', onclick: async () => { await patch(n.id, { author: 'system' }); toast('已移回问题与经验'); } }, '不是我写的'),
          h('span.grow'),
          h('button.sn-x', { onclick: async () => { if (confirm('删除这张便签？它的关系也会解除。')) { await api.del(`/api/notes/${n.id}`); selected = null; await load(); } } }, '删除')]),
      );
    }

    function paint() { paintCompose(); paintFilters(); paintBoard(); paintSide(); }

    el.append(
      ui.pageHead('便签', '只放你自己写的。任何页面按 ⌘K 都能记，读文章时会带上出处；系统记的问题与经验在复盘里'),
      h('div.card.sn-composer', {}, [ta, compKinds, compSrc]),
      filters,
      h('div.sn-work', {}, [board, side]),
    );
    const onQuick = () => { if (el.isConnected) load(); else document.removeEventListener('quick-note', onQuick); };
    document.addEventListener('quick-note', onQuick);
    const onResize = () => { if (el.isConnected) drawLines(); else window.removeEventListener('resize', onResize); };
    window.addEventListener('resize', onResize);
    await load();
    if (selected) board.querySelector(`[data-note="${selected}"]`)?.scrollIntoView({ block: 'center' });
  },
};

function injectStyle() {
  if (document.getElementById('sn-style')) return;
  const s = document.createElement('style');
  s.id = 'sn-style';
  s.textContent = `
  .sn-composer { display: grid; gap: 8px; border: 1.5px solid var(--accent); padding: 12px 14px; }
  .sn-composer textarea { width: 100%; min-height: 48px; border: 0; background: transparent; resize: vertical; padding: 2px; box-shadow: none; }
  .sn-composer textarea:focus { box-shadow: none; }
  .sn-row { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
  .sn-row .grow { flex: 1 1 auto; }
  .sn-post { margin-left: auto; }
  .sn-row .kind-chips { display: contents; }
  .sn-filters { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; margin: 18px 0 6px; }
  .sn-filters input { flex: 0 1 220px; min-width: 0; border-radius: 99px; padding: 3px 14px; }
  .sn-chip { border: 1px solid var(--line-2); background: transparent; border-radius: 99px; padding: 2px 11px; cursor: pointer; font-size: 13px; color: var(--text); }
  .sn-chip:hover { border-color: var(--accent); }
  .sn-chip.on { background: var(--accent-soft); border-color: var(--accent); color: var(--accent); font-weight: 600; }
  .sn-chip.add { border-style: dashed; color: var(--muted); }
  .sn-chip i { display: inline-block; width: 9px; height: 9px; margin-right: 5px; border-radius: 2px; border: 1px solid rgba(0,0,0,.12); }
  .sn-work { display: grid; grid-template-columns: minmax(0, 1fr) 300px; gap: 24px; align-items: start; }
  .sn-board { position: relative; min-width: 0; }
  .sn-board > svg { position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; z-index: 0; overflow: visible; }
  .sn-board > svg path { fill: none; stroke: var(--accent); stroke-width: 1.6; stroke-dasharray: 5 4; }
  .sn-board > svg circle { fill: var(--accent); }
  .sn-day { display: grid; grid-template-columns: 74px minmax(0, 1fr); gap: 14px; padding-block: 14px; }
  .sn-day-label { position: relative; text-align: right; padding-right: 14px; border-right: 2px solid var(--line-2); font-variant-numeric: tabular-nums; }
  .sn-day-label b { display: block; font: 700 17px/1.3 var(--serif); }
  .sn-day-label span { color: var(--muted); font-size: 12px; }
  .sn-day-label::after { content: ""; position: absolute; right: -6px; top: 6px; width: 10px; height: 10px; border-radius: 50%; background: var(--accent); }
  .sn-notes { display: flex; flex-wrap: wrap; gap: 18px; align-items: flex-start; min-width: 0; }
  button.sn-note { position: relative; z-index: 1; width: 204px; max-width: 100%; min-height: 150px; padding: 18px 14px 10px; color: var(--note-ink); text-align: left; font-weight: 400;
    border: 0; border-radius: 2px 2px 22px 2px / 2px 2px 8px 2px; box-shadow: var(--note-shadow); cursor: pointer; display: flex; flex-direction: column; align-items: stretch; justify-content: flex-start; gap: 8px; transition: transform .15s, opacity .15s; }
  .sn-note:nth-child(3n+1) { transform: rotate(-1deg); } .sn-note:nth-child(3n+2) { transform: rotate(.7deg); } .sn-note:nth-child(3n) { transform: rotate(-.3deg); }
  button.sn-note:hover, button.sn-note.sel { transform: none; }
  .sn-note.sel { outline: 2px solid var(--accent); outline-offset: 2px; z-index: 2; }
  .sn-note.dim { opacity: .38; }
  .sn-note.rel { z-index: 2; }
  .sn-note::before { content: ""; position: absolute; top: -7px; left: 50%; width: 58px; height: 15px; margin-left: -29px; background: rgba(255,255,255,.5); box-shadow: 0 0 1px rgba(0,0,0,.2); }
  .sn-note .txt { flex: 1; font: 500 14px/1.6 var(--serif); overflow-wrap: anywhere; max-height: 14.4em; overflow: hidden; }
  .sn-note .txt .md { line-height: inherit; } .sn-note .txt p { margin: 0 0 .3em; } .sn-note .txt ol, .sn-note .txt ul { margin: 0 0 .3em; padding-left: 1.3em; }
  .sn-note .src { font-size: 12px; color: #5c5247; border-top: 1px dashed rgba(60,40,20,.28); padding-top: 5px; overflow-wrap: anywhere; }
  .sn-note .meta { display: flex; flex-wrap: wrap; gap: 6px; font-size: 11.5px; color: #5c5247; align-items: center; font-variant-numeric: tabular-nums; }
  .sn-note .meta em { font-style: normal; font-weight: 600; }
  .sn-note .meta .grow { flex: 1; }
  .sn-c0 { background: var(--note-yellow); } .sn-c1 { background: var(--note-pink); } .sn-c2 { background: var(--note-blue); }
  .sn-c3 { background: var(--note-green); } .sn-c4 { background: var(--note-purple); } .sn-c5 { background: var(--note-sand); } .sn-c6 { background: var(--note-teal); }
  .sn-side { position: sticky; top: 16px; max-height: calc(100vh - 32px); overflow-y: auto; background: var(--panel); border: 1px solid var(--line); border-radius: 14px; padding: 16px; display: grid; gap: 12px; min-width: 0; }
  .sn-side h2 { font-size: 15px; margin: 0; }
  .sn-side textarea { width: 100%; resize: none; overflow: hidden; }
  .sn-side button[hidden] { display: none; }
  .sn-side .sn-row.foot { border-top: 1px solid var(--line); padding-top: 8px; }
  .sn-label { color: var(--muted); font-size: 12px; margin-bottom: 4px; letter-spacing: .04em; }
  .sn-link { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; gap: 6px; align-items: center; padding: 6px 0; border-top: 1px solid var(--line); }
  .sn-link select { border-radius: 6px; font-size: 12px; padding: 1px 2px; width: auto; }
  .sn-link a { color: var(--text); font-size: 13px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .sn-link a:hover { color: var(--accent); }
  .sn-x { border: 0; background: none; color: var(--muted); cursor: pointer; font-size: 12px; padding: 0; }
  .sn-x:hover { color: var(--accent); }
  .sn-hint { background: var(--accent-soft); color: var(--accent); border-radius: 8px; padding: 6px 10px; font-size: 13px; margin-bottom: 6px; }
  .sn-src { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 2px 6px; padding: 6px 0; border-top: 1px solid var(--line); font-size: 13px; overflow-wrap: anywhere; }
  .sn-src b, .sn-pick b { font-weight: 600; color: var(--accent); margin-right: 5px; }
  .sn-src blockquote { grid-column: 1 / -1; margin: 2px 0 0; padding-left: 8px; border-left: 2px solid var(--line-2); color: var(--muted); font: 13px/1.55 var(--serif); }
  .sn-picker { display: grid; gap: 4px; margin-top: 4px; }
  .sn-picker input { width: 100%; min-width: 0; }
  .sn-pick { display: block; width: 100%; text-align: left; border: 0; background: transparent; padding: 4px 6px; border-radius: 6px; cursor: pointer; font-size: 13px; font-weight: 400; overflow-wrap: anywhere; color: var(--text); }
  .sn-pick:hover { background: var(--accent-soft); }
  @media (max-width: 900px) { .sn-work { grid-template-columns: minmax(0, 1fr); } .sn-side { position: static; max-height: none; order: -1; } .sn-side.idle { display: none; } }
  @media (max-width: 480px) {
    .sn-day { grid-template-columns: minmax(0, 1fr); gap: 8px; }
    .sn-day-label { text-align: left; border-right: 0; padding-right: 0; }
    .sn-day-label b, .sn-day-label span { display: inline; margin-right: 6px; }
    .sn-day-label::after { display: none; }
    button.sn-note { width: 100%; min-height: 110px; }
  }
  @media (prefers-reduced-motion: reduce) { button.sn-note { transition: none; } }
  `;
  document.head.append(s);
}
