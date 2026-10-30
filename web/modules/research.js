// 调研：新调研 / 调研文档 / 产品体验。路由 #research/<tab>，详情 #research/r/<id>。
const STATUS = {
  queued: ['排队中', ''], running: ['调研中', 'warn'], waiting: ['等待 GrokBot', 'warn'], timeout: ['等待超时', 'warn'],
  awaiting_paste: ['待粘贴', 'warn'], done: ['完成', 'ok'], failed: ['失败', 'err'],
};
const ENGINE_NAMES = { claude: 'Claude Code', codex: 'Codex', grokbot: 'GrokBot', muse: 'Muse' };
const PREFILL_KEY = 'research-prefill';
const go = (path) => { location.hash = '#research' + (path ? '/' + path : ''); };
const tagsOf = (s) => s.split(/[,，、\s]+/).map((x) => x.trim()).filter(Boolean);

export default {
  async render(el, ctx) {
    const { h } = ctx;
    const [tab = 'new', arg] = ctx.sub;
    const tabs = [['new', '新调研'], ['docs', '调研文档'], ['products', '产品体验']];
    const cur = tab === 'r' ? 'new' : tab;
    el.append(h('div.tabs', {}, tabs.map(([id, name]) =>
      h('button' + (cur === id ? '.active' : ''), { onclick: () => go(id) }, name))));
    const body = h('div');
    el.append(body);
    if (tab === 'r') return detail(body, ctx, +arg);
    if (tab === 'docs') return docs(body, ctx, arg ? +arg : null);
    if (tab === 'products') return products(body, ctx);
    return newResearch(body, ctx);
  },
};

const statusTag = (h, s) => { const [t, c] = STATUS[s] || [s || '—', '']; return h('span.tag' + (c ? '.' + c : ''), {}, t); };

// ---------- 新调研 ----------
async function newResearch(el, ctx) {
  const { api, h, toast, field } = ctx;
  const presets = await api.get('/api/research/presets');
  let pre = {};
  try { pre = JSON.parse(sessionStorage.getItem(PREFILL_KEY) || '{}'); sessionStorage.removeItem(PREFILL_KEY); } catch { /* ignore */ }

  const topic = h('input', { placeholder: '任意主题，如：AI 编程助手的商业模式', value: pre.topic || '' });
  const angleBoxes = presets.angles.map((a) => {
    const cb = h('input', { type: 'checkbox', value: a, checked: (pre.angles || []).includes(a) });
    return { cb, el: h('label.tag', {}, [cb, ' ' + a]) };
  });
  const extraAngles = h('input', { placeholder: '自定义角度，逗号分隔', value: (pre.angles || []).filter((a) => !presets.angles.includes(a)).join('，') });
  const engineBoxes = presets.engines.map((e) => {
    const cb = h('input', { type: 'checkbox', value: e.id, checked: e.id === 'claude' });
    return { cb, el: h('label.tag' + (e.available ? '' : '.err'), { title: e.available ? '' : '本机未检测到' }, [cb, ' ' + e.name]) };
  });
  const context = h('textarea', { rows: 4, placeholder: '背景 / 已有认知 / 想重点弄清的问题（可选）' }, [pre.context || '']);
  const submit = h('button.primary', {
    onclick: async () => {
      const angles = [...angleBoxes.filter((x) => x.cb.checked).map((x) => x.cb.value), ...tagsOf(extraAngles.value)];
      const engines = engineBoxes.filter((x) => x.cb.checked).map((x) => x.cb.value);
      if (!topic.value.trim()) return toast('请填写主题', true);
      if (!engines.length) return toast('至少选一个引擎', true);
      submit.disabled = true;
      try {
        const r = await api.post('/api/research', { topic: topic.value, angles, engines, context: context.value, product_id: pre.product_id || null });
        go('r/' + r.id);
      } catch (e) { toast(e.message, true); submit.disabled = false; }
    },
  }, '开始调研');

  el.append(h('div.card', {}, [
    h('h3', {}, '新调研'),
    field('主题', topic),
    field('关注角度', h('div.row', {}, angleBoxes.map((x) => x.el))),
    extraAngles,
    h('div', { style: { height: '10px' } }),
    field('引擎（并行）', h('div.row', {}, engineBoxes.map((x) => x.el))),
    h('div.muted', {}, 'Claude/Codex：联网检索网页与文档；GrokBot：X/Twitter 讨论；Muse：复制提问并打开 App，回答需手动粘贴回来。'),
    h('div', { style: { height: '8px' } }),
    field('背景（可选）', context),
    submit,
  ]));

  const q = h('input', { placeholder: '搜索历史调研…' });
  const list = h('div.list');
  const load = async () => {
    const rs = await api.get('/api/research?q=' + encodeURIComponent(q.value));
    list.replaceChildren(...(rs.length ? rs.map((r) => h('div.item', { style: { cursor: 'pointer' }, onclick: () => go('r/' + r.id) }, [
      h('div.row', {}, [h('b', {}, r.topic), statusTag(h, r.status), ...r.engines.map((e) => h('span.muted', {}, ENGINE_NAMES[e] || e))]),
      h('div.muted', {}, `${r.angles.join('、') || '整体'} · ${r.created_at.slice(0, 16).replace('T', ' ')}`),
    ])) : [h('div.muted', {}, '还没有调研')]));
  };
  q.addEventListener('input', debounce(load));
  el.append(h('div.card', {}, [h('h3', {}, '历史调研'), q, h('div', { style: { height: '8px' } }), list]));
  await load();
}

// ---------- 调研详情 ----------
async function detail(el, ctx, id) {
  const { api, h, md, toast, openChat } = ctx;
  let r;
  try { r = await api.get(`/api/research/${id}`); } catch (e) { el.append(h('pre.error', {}, e.message)); return; }
  const rerender = () => { if (el.isConnected) { el.innerHTML = ''; detail(el, ctx, id); } };

  const doneCount = r.results.filter((x) => x.status === 'done').length;
  const synthBtn = h('button.primary', {
    disabled: !doneCount || r.synth_status === 'running',
    onclick: async () => { try { await api.post(`/api/research/${id}/synthesize`); toast('综合任务已提交'); rerender(); } catch (e) { toast(e.message, true); } },
  }, r.synth_status === 'running' ? '综合中…' : (r.synthesis ? '重新综合' : '综合'));

  el.append(h('div.card', {}, [
    h('div.row', {}, [h('h3', { style: { flex: 1, margin: 0 } }, r.topic), statusTag(h, r.status)]),
    h('div', { style: { margin: '6px 0' } }, r.angles.length ? r.angles.map((a) => h('span.tag', {}, a)) : h('span.muted', {}, '整体概况')),
    r.context ? h('pre', {}, r.context) : null,
    h('div.row', {}, [
      synthBtn,
      h('button', { onclick: () => openChat({ module: 'research', ref: `research:${id}`, title: '调研：' + r.topic }) }, '和 Agent 讨论'),
      r.doc_id ? h('button', { onclick: () => go('docs/' + r.doc_id) }, '查看文档') : null,
      h('button.ghost', { onclick: async () => { if (confirm('删除这条调研及其文档？')) { await api.del(`/api/research/${id}`); go('new'); } } }, '删除'),
      h('span.muted', {}, r.doc_path),
    ]),
  ]));

  if (r.synth_status) {
    el.append(h('div.card', {}, [h('div.row', {}, [h('h3', { style: { flex: 1, margin: 0 } }, '综合'), statusTag(h, r.synth_status)]),
      r.synthesis ? md(r.synthesis) : h('div.muted', {}, r.synth_status === 'failed' ? '综合失败，可重试' : '正在合并各引擎结果…')]));
    if (r.synth_status === 'running' && r.synth_job_id) watchJob(api, r.synth_job_id, el, rerender);
  }

  const grid = h('div.list');
  el.append(grid);
  for (const x of r.results) grid.append(resultCard(x, ctx, rerender, el));
}

function resultCard(x, ctx, rerender, root) {
  const { api, h, md, toast } = ctx;
  const card = h('div.card');
  const logEl = h('pre.muted', { style: { maxHeight: '120px', overflow: 'auto', display: 'none' } });
  const act = async (path, body) => { try { await api.post(`/api/research/results/${x.id}/${path}`, body); rerender(); } catch (e) { toast(e.message, true); } };
  const head = h('div.row', {}, [h('b', { style: { flex: 1 } }, ENGINE_NAMES[x.engine] || x.engine), statusTag(h, x.status),
    x.finished_at ? h('span.muted', {}, x.finished_at.slice(5, 16).replace('T', ' ')) : null]);
  card.append(head);

  if (x.status === 'done') {
    const det = h('details', { open: true }, [h('summary', {}, '结果'), md(x.content)]);
    card.append(det);
  } else if (x.status === 'awaiting_paste') {
    const ta = h('textarea', { rows: 8, placeholder: '把 Muse 的回答粘贴到这里' });
    card.append(
      h('div.muted', {}, x.error),
      h('details', {}, [h('summary', {}, '提问 brief'), h('pre', {}, x.brief)]),
      h('div.row', { style: { margin: '6px 0' } }, [
        h('button', { onclick: async () => { await navigator.clipboard.writeText(x.brief); toast('已复制'); } }, '复制 brief'),
        h('button', { onclick: () => act('muse') }, '重新复制并打开 Muse'),
      ]),
      ta,
      h('button.primary', { onclick: () => (ta.value.trim() ? act('paste', { content: ta.value }) : toast('内容为空', true)) }, '保存回答'),
    );
  } else if (x.status === 'failed') {
    card.append(h('pre.error', {}, x.error || '失败'),
      h('button', { onclick: () => { if (x.engine !== 'grokbot' || confirm('将向 GrokBot 发送一个新请求，确定？')) act('retry'); } }, '重试'));
  } else if (x.status === 'timeout') {
    card.append(h('div.muted', {}, x.error), h('button', { onclick: () => act('resume') }, '继续等待（不重发）'));
  } else {
    card.append(h('div.muted', {}, x.engine === 'grokbot' ? (x.request_id ? `已发送，request_id=${x.request_id}，等待回复…` : '检查配置并发送…') : '后台 Agent 调研中…'), logEl);
    if (x.job_id) watchJob(api, x.job_id, root, rerender, logEl);
    else if (x.engine === 'grokbot') pollResult(api, x, root, rerender);
  }
  return card;
}

// 轮询 job（Claude/Codex/综合），结束后重绘；离开页面即停止
function watchJob(api, jobId, root, rerender, logEl) {
  api.waitJob(jobId, (j) => {
    if (!root.isConnected) throw new Error('detached');
    if (logEl && j.log) { logEl.style.display = ''; logEl.textContent = j.log.split('\n').slice(-6).join('\n'); }
  }, 3000).then(() => setTimeout(rerender, 800)).catch(() => {});
}

// 轮询 GrokBot 结果
function pollResult(api, x, root, rerender) {
  const t = setInterval(async () => {
    if (!root.isConnected) return clearInterval(t);
    const y = await api.get(`/api/research/results/${x.id}`).catch(() => null);
    if (y && (y.status !== x.status || y.request_id !== x.request_id)) { clearInterval(t); rerender(); }
  }, 5000);
}

// ---------- 文档库 ----------
async function docs(el, ctx, openId) {
  const { api, h, md, toast, field } = ctx;
  const q = h('input', { placeholder: '搜索标题和正文…' });
  const tag = h('select', {}, [h('option', { value: '' }, '全部标签')]);
  const since = h('input', { type: 'date' });
  const until = h('input', { type: 'date' });
  const list = h('div.list');
  const view = h('div');
  const tags = await api.get('/api/research/docs/tags');
  tag.append(...tags.map((t) => h('option', { value: t }, t)));

  const load = async () => {
    const p = new URLSearchParams({ q: q.value, tag: tag.value, since: since.value, until: until.value });
    const ds = await api.get('/api/research/docs?' + p);
    list.replaceChildren(...(ds.length ? ds.map((d) => h('div.item', { style: { cursor: 'pointer' }, onclick: () => show(d.id) }, [
      h('div.row', {}, [h('b', {}, d.title), ...d.tags.map((t) => h('span.tag', {}, t))]),
      h('div.muted', {}, `${d.research_id ? '调研 #' + d.research_id : '手写'} · ${d.updated_at.slice(0, 16).replace('T', ' ')}`),
    ])) : [h('div.muted', {}, '没有文档')]));
  };

  const show = async (id) => {
    const d = await api.get(`/api/research/docs/${id}`);
    view.replaceChildren(h('div.card', {}, [
      h('div.row', {}, [h('h3', { style: { flex: 1, margin: 0 } }, d.title),
        d.research_id ? h('button', { onclick: () => go('r/' + d.research_id) }, '打开调研') : h('button', { onclick: () => editor(d) }, '编辑'),
        h('button', { onclick: async () => { await navigator.clipboard.writeText(d.content); toast('已复制 markdown'); } }, '复制'),
        h('button.ghost', { onclick: async () => {
          if (!confirm(d.research_id ? '删除文档会同时删除这条调研记录，确定？' : '删除这篇文档？')) return;
          await api.del(`/api/research/docs/${id}`); view.innerHTML = ''; load();
        } }, '删除')]),
      h('div.muted', {}, d.path),
      md(d.content),
    ]));
    view.scrollIntoView({ behavior: 'smooth' });
  };

  const editor = (d = null) => {
    const title = h('input', { value: d?.title || '', placeholder: '标题' });
    const tg = h('input', { value: (d?.tags || []).join('，'), placeholder: '标签，逗号分隔' });
    const content = h('textarea.mono', { rows: 16, placeholder: '粘贴或撰写 markdown' }, [d?.content || '']);
    view.replaceChildren(h('div.card', {}, [h('h3', {}, d ? '编辑文档' : '新建文档'), field('标题', title), field('标签', tg), field('正文（markdown）', content),
      h('div.row', {}, [
        h('button.primary', { onclick: async () => {
          const body = { title: title.value, content: content.value, tags: tagsOf(tg.value) };
          try { const r = d ? await api.put(`/api/research/docs/${d.id}`, body) : await api.post('/api/research/docs', body); await load(); show(r.id); } catch (e) { toast(e.message, true); }
        } }, '保存'),
        h('button.ghost', { onclick: () => { view.innerHTML = ''; } }, '取消')])]));
  };

  const reload = debounce(load);
  [q, since, until].forEach((x) => x.addEventListener('input', reload));
  tag.addEventListener('change', load);
  el.append(h('div.card', {}, [
    h('div.row', {}, [h('div', { style: { flex: 2, minWidth: '180px' } }, q), h('div', { style: { flex: 1, minWidth: '120px' } }, tag),
      h('div', { style: { width: '150px' } }, since), h('span.muted', {}, '至'), h('div', { style: { width: '150px' } }, until),
      h('button', { onclick: () => editor() }, '+ 新建文档')]),
    h('div', { style: { height: '8px' } }), list]), view);
  await load();
  if (openId) show(openId);
}

// ---------- 产品体验 ----------
async function products(el, ctx) {
  const { api, h, md, toast, field } = ctx;
  const formBox = h('div');
  const q = h('input', { placeholder: '搜索产品、体验、标签…' });
  const list = h('div.grid');

  const form = (p = null) => {
    const f = {
      name: h('input', { value: p?.name || '', placeholder: '产品名' }),
      url: h('input', { value: p?.url || '', placeholder: 'https://' }),
      category: h('input', { value: p?.category || '', placeholder: '如：AI 编程 / 笔记 / 硬件' }),
      rating: h('select', {}, [0, 1, 2, 3, 4, 5].map((n) => h('option', { value: n, selected: (p?.rating || 0) === n }, n ? '★'.repeat(n) : '未评分'))),
      used_at: h('input', { type: 'date', value: p?.used_at || '' }),
      tags: h('input', { value: (p?.tags || []).join('，'), placeholder: '逗号分隔' }),
      experience: h('textarea', { rows: 4, placeholder: '怎么用的、场景、感受' }, [p?.experience || '']),
      pros: h('textarea', { rows: 2 }, [p?.pros || '']),
      cons: h('textarea', { rows: 2 }, [p?.cons || '']),
    };
    const save = async () => {
      const body = { name: f.name.value, url: f.url.value, category: f.category.value, rating: +f.rating.value, used_at: f.used_at.value,
        tags: tagsOf(f.tags.value), experience: f.experience.value, pros: f.pros.value, cons: f.cons.value };
      try { p ? await api.put(`/api/research/products/${p.id}`, body) : await api.post('/api/research/products', body); toast('已保存'); formBox.innerHTML = ''; load(); } catch (e) { toast(e.message, true); }
    };
    formBox.replaceChildren(h('div.card', {}, [h('h3', {}, p ? '编辑产品体验' : '记录产品体验'),
      h('div.grid', {}, [field('产品名', f.name), field('链接', f.url), field('类别', f.category), field('评分', f.rating), field('使用时间', f.used_at), field('标签', f.tags)]),
      field('我的体验', f.experience), h('div.grid', {}, [field('优点', f.pros), field('缺点', f.cons)]),
      h('div.row', {}, [h('button.primary', { onclick: save }, '保存'), h('button.ghost', { onclick: () => { formBox.innerHTML = ''; } }, '取消')])]));
    f.name.focus();
  };

  const researchIt = async (p) => {
    const d = await api.get(`/api/research/products/${p.id}/draft`);
    sessionStorage.setItem(PREFILL_KEY, JSON.stringify(d));
    go('new');
  };

  const load = async () => {
    const ps = await api.get('/api/research/products?q=' + encodeURIComponent(q.value));
    list.replaceChildren(...(ps.length ? ps.map((p) => h('div.card', {}, [
      h('div.row', {}, [h('b', { style: { flex: 1 } }, p.url ? h('a', { href: p.url, target: '_blank', rel: 'noopener' }, p.name) : p.name),
        h('span', { title: '评分' }, p.rating ? '★'.repeat(p.rating) : '')]),
      h('div.muted', {}, [p.category, p.used_at].filter(Boolean).join(' · ')),
      h('div', {}, p.tags.map((t) => h('span.tag', {}, t))),
      p.experience ? md(p.experience) : null,
      p.pros ? h('div', {}, [h('span.tag.ok', {}, '优'), p.pros]) : null,
      p.cons ? h('div', {}, [h('span.tag.err', {}, '缺'), p.cons]) : null,
      h('div.row', { style: { marginTop: '8px' } }, [
        h('button.primary', { onclick: () => researchIt(p) }, '调研这个产品'),
        h('button', { onclick: () => form(p) }, '编辑'),
        h('button.ghost', { onclick: async () => { if (confirm(`删除「${p.name}」？`)) { await api.del(`/api/research/products/${p.id}`); load(); } } }, '删除'),
      ]),
    ])) : [h('div.muted', {}, '还没有记录')]));
  };
  q.addEventListener('input', debounce(load));
  el.append(h('div.row', { style: { marginBottom: '10px' } }, [h('div', { style: { flex: 1 } }, q), h('button.primary', { onclick: () => form() }, '+ 记录产品体验')]), formBox, list);
  await load();
}

function debounce(fn, ms = 300) {
  let t;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}
