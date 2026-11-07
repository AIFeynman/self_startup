import { api, h, toast } from './api.js';

const clock = (at) => at.slice(11, 16);
const elapsed = (s) => {
  const hh = Math.floor(s / 3600), mm = Math.floor(s / 60) % 60, ss = String(s % 60).padStart(2, '0');
  return hh ? `${hh}:${String(mm).padStart(2, '0')}:${ss}` : `${mm}:${ss}`;
};

export function pauseButton({ onRecorded }) {
  const box = h('div.pause');
  let shown = '';

  const step = async (call) => {
    try {
      const a = await call();
      if (a?.discarded) toast(a.discarded);
      draw(a?.discarded ? null : a);
    } catch (e) {
      toast(e.message, true);
      draw(await api.get('/api/review/away'));
    }
  };
  const cancel = (label) => h('button.ghost.sm', { onclick: () => {
    if (confirm('这段暂停不记了？')) step(async () => { await api.del('/api/review/away'); return null; });
  } }, label);

  const drawPaused = (a) => {
    const openedAt = Date.now();
    const timer = h('div.pause-timer', {}, elapsed(a.seconds));
    const tick = setInterval(() => {
      if (!timer.isConnected) return clearInterval(tick);
      timer.textContent = elapsed(a.seconds + Math.floor((Date.now() - openedAt) / 1000));
    }, 1000);
    box.replaceChildren(h('div.pause-head', {}, `${clock(a.started_at)} 暂停`), timer,
      h('button.pause-go.resume', { onclick: () => step(() => api.post('/api/review/away/back')) }, '继续'),
      cancel('点错了，不记'));
  };
  const drawResumed = (a) => {
    let category = '';
    const gain = h('input.pause-gain', { placeholder: '收获（可不填）' });
    const submit = h('button.primary.pause-go.send', { disabled: true, onclick: async () => {
      try {
        const r = await api.post('/api/review/away/submit', { category, output: gain.value });
        toast(`已记到人工效率：${r.date} ${clock(a.started_at)}–${clock(a.ended_at)} ${category}`);
        draw(null);
        onRecorded();
      } catch (e) { toast(e.message, true); }
    } }, '提交');
    const kinds = a.categories.map((c) => h('button.kind-chip', { onclick: (e) => {
      category = c;
      kinds.forEach((k) => k.classList.toggle('on', k === e.currentTarget));
      submit.disabled = false;
    } }, c));
    box.replaceChildren(h('div.pause-sum', {}, `${clock(a.started_at)}–${clock(a.ended_at)} · ${elapsed(a.seconds)}`),
      h('div.pause-kinds', {}, kinds), gain, submit, cancel('不记了'));
  };
  const draw = (a) => {
    shown = a ? `${a.started_at}|${a.ended_at}` : '';
    if (a?.ended_at) drawResumed(a);
    else if (a) drawPaused(a);
    else box.replaceChildren(h('button.primary.pause-go', { title: '离开电脑时点一下，回来点「继续」', onclick: () => step(() => api.post('/api/review/away/start')) }, '暂停'));
  };

  const sync = async () => {
    const a = await api.get('/api/review/away').catch(() => undefined);
    if (a !== undefined && (a ? `${a.started_at}|${a.ended_at}` : '') !== shown) draw(a);
  };
  draw(null);
  sync();
  document.addEventListener('visibilitychange', () => !document.hidden && sync());
  return box;
}
