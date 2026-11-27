const E = (s) => (s == null ? '' : String(s)).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const TIERS = [['small', '小'], ['mid', '中'], ['large', '大']];
export const MRR = [['', '全部 MRR'], ['has', '有收入数据'], ['1e4', 'MRR ≥ $10k'], ['1e5', 'MRR ≥ $100k'], ['1e6', 'MRR ≥ $1M'], ['1e7', 'MRR ≥ $10M']];
export const ST = [['', '全部状态'], ['unseen', '没看过'], ['seen', '看过'], ['rated', '评过星'], ['noted', '有评论 / 讨论'], ['touched', '有任何交互']];

export const PANEL_CSS = `
.pn-sum { display: flex; gap: 14px; flex-wrap: wrap; align-items: center; font-size: 13px; margin: 6px 0 8px; }
.pn-sum b { font-variant-numeric: tabular-nums; } .pn-bar { flex: 1; min-width: 120px; max-width: 260px; height: 6px; background: var(--bg-2); border-radius: 3px; overflow: hidden; }
.pn-bar i { display: block; height: 100%; background: var(--accent); }
.pn-lg { font-size: 12px; color: var(--muted); display: flex; gap: 10px; flex-wrap: wrap; }
.pn-grid { display: grid; grid-template-columns: minmax(150px, 220px) repeat(var(--cols), minmax(0, 1fr)); border: 1px solid var(--line); border-radius: var(--radius); background: var(--panel); }
.pn-grid > div { padding: 6px 8px; border-top: 1px solid var(--line); min-width: 0; }
.pn-grid > .pn-h { position: sticky; top: 0; z-index: 2; background: var(--panel); font-weight: 700; font-size: 13px; border-top: none; }
.pn-grid > .pn-sc { grid-column: 1 / -1; background: var(--bg-2); font-weight: 700; font-size: 13.5px; }
.pn-sc small, .pn-sb small { font-weight: 400; color: var(--muted); margin-left: 6px; }
.pn-sb { font-size: 13px; } .pn-sb .p { display: block; font-size: 11.5px; color: var(--muted); line-height: 1.4; }
.pn-cell { display: flex; flex-wrap: wrap; gap: 4px; align-content: flex-start; }
.pn-cell > .pn-t { display: none; }
.pn-c { font-size: 12.5px; line-height: 1.5; border: 1px solid var(--line); border-radius: 6px; padding: 0 6px; cursor: pointer; color: var(--text); background: var(--bg); white-space: nowrap; max-width: 100%; overflow: hidden; text-overflow: ellipsis; }
.pn-c:hover { border-color: var(--accent); }
.pn-c.seen { background: var(--bg-2); color: var(--muted); }
.pn-c.seen::before { content: '✓ '; color: var(--accent); }
.pn-c i { font-style: normal; color: var(--accent); margin-left: 3px; font-size: 11.5px; }
.pn-c u { text-decoration: none; margin-left: 3px; font-size: 11px; color: var(--bg); background: var(--accent); border-radius: 4px; padding: 0 3px; }
.pn-c.on { outline: 2px solid var(--accent); }
.pn-pop { position: fixed; right: 16px; top: 80px; bottom: 16px; width: min(420px, calc(100vw - 32px)); z-index: 30; overflow: auto; background: var(--panel); border: 1px solid var(--line); border-radius: var(--radius); box-shadow: 0 8px 30px rgba(0,0,0,.18); padding: 12px 14px; font-size: 14px; line-height: 1.6; }
.pn-pop h4 { margin: 0 28px 2px 0; font: 700 17px/1.4 var(--serif); }
.pn-pop .x { position: absolute; right: 8px; top: 6px; border: none; background: none; font-size: 20px; cursor: pointer; color: var(--muted); }
.pn-pop dl { margin: 6px 0; } .pn-pop dt { color: var(--muted); font-size: 12px; margin-top: 6px; } .pn-pop dd { margin: 0; }
.pn-acts { display: flex; gap: 6px; flex-wrap: wrap; margin: 8px 0; }
.pn-th { border-top: 1px dashed var(--line); padding: 6px 0; font-size: 13px; }
.pn-th q { display: block; color: var(--muted); quotes: '「' '」'; }
.pn-th .u { font-weight: 600; } .pn-th .a { color: var(--muted); display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }
@container (max-width: 640px) {
  .pn-grid { grid-template-columns: 1fr; }
  .pn-grid > .pn-h { display: none; }
  .pn-grid > .pn-cell { border-top: none; padding-top: 0; }
  .pn-cell > .pn-t { display: inline; font-size: 11.5px; color: var(--muted); margin-right: 2px; }
  .pn-cell:empty, .pn-cell.none { display: none; }
}
`;

export const money = (v) => (v >= 1e9 ? `$${(v / 1e9).toFixed(1)}B` : v >= 1e6 ? `$${(v / 1e6).toFixed(1)}M` : v >= 1e3 ? `$${Math.round(v / 1e3)}k` : `$${Math.round(v)}`);

export function panelState(D, A, star) {
  const seen = (k) => !!A.seen[k], noted = (k) => !!A.notes[k];
  const touched = (k) => seen(k) || noted(k) || star(k) > 0;
  return { seen, noted, touched };
}

export function panelHtml(D, A, o) {
  const { star, fit, size, mrr, st, dom, cur } = o;
  const { seen, noted, touched } = panelState(D, A, star);
  const mrrOk = (c) => !mrr || (mrr === 'has' ? (c.arr_v || 0) > 0 : (c.arr_v || 0) / 12 >= +mrr);
  const stOk = (k) => !st || (st === 'unseen' ? !seen(k) : st === 'seen' ? seen(k) : st === 'rated' ? star(k) > 0 : st === 'noted' ? noted(k) : touched(k));
  const ok = (k) => D.cards[k] && fit(k) && mrrOk(D.cards[k]) && stOk(k);
  const cols = TIERS.filter(([t]) => !size || size === t);
  const doms = (D.graph.domains || []).filter((d) => !dom || d.id === dom);
  const scById = Object.fromEntries(D.graph.scenes.map((s) => [s.id, s]));
  const order = (ks) => ks.sort((a, b) => star(b) - star(a) || (D.cards[b].arr_v || 0) - (D.cards[a].arr_v || 0));
  const chip = (k) => {
    const c = D.cards[k], n = A.notes[k];
    const tip = [c.name, c.arr_v ? `MRR ≈ ${money(c.arr_v / 12)}` : '', seen(k) ? '看过' : '没看过', n ? `评论 ${n.threads} 条 · 问 Claude ${n.asks} 次` : ''].filter(Boolean).join(' · ');
    return `<a class="pn-c${seen(k) ? ' seen' : ''}${cur === k ? ' on' : ''}" data-pk="${E(k)}" title="${E(tip)}">${E(c.name)}${star(k) ? `<i>★${star(k)}</i>` : ''}${n ? `<u>${n.threads}</u>` : ''}</a>`;
  };
  const all = new Set();
  let body = '';
  for (const d of doms) {
    for (const sid of d.scenes) {
      const sc = scById[sid];
      if (!sc) continue;
      const rows = sc.subs.map((sb) => ({ sb, ks: [...new Set(sb.products)].filter(ok) })).filter((r) => r.ks.length);
      if (!rows.length) continue;
      const sk = rows.flatMap((r) => r.ks);
      sk.forEach((k) => all.add(k));
      body += `<div class="pn-sc">${E(d.name)} · ${E(sc.name)}<small>${sk.length} 家 · 看过 ${sk.filter(seen).length}</small></div>`;
      body += rows.map(({ sb, ks }) => `<div class="pn-sb">${E(sb.name)}<small>${ks.filter(seen).length}/${ks.length}</small><span class="p">${E(sb.pain || '')}</span></div>`
        + cols.map(([t, lab]) => { const x = order(ks.filter((k) => D.cards[k].tier === t)); return `<div class="pn-cell${x.length ? '' : ' none'}">${x.length ? `<span class="pn-t">${lab}</span>` : ''}${x.map(chip).join('')}</div>`; }).join('')).join('');
    }
  }
  const un = dom ? [] : [...new Set(D.graph.unplaced || [])].filter((k) => ok(k) && !all.has(k));
  if (un.length) {
    un.forEach((k) => all.add(k));
    body += `<div class="pn-sc">未归类<small>${un.length} 家 · 看过 ${un.filter(seen).length}</small></div><div class="pn-sb">还没归到痛点的公司<small>${un.filter(seen).length}/${un.length}</small></div>`
      + cols.map(([t, lab]) => { const x = order(un.filter((k) => D.cards[k].tier === t)); return `<div class="pn-cell${x.length ? '' : ' none'}">${x.length ? `<span class="pn-t">${lab}</span>` : ''}${x.map(chip).join('')}</div>`; }).join('');
  }
  const ks = [...all], ns = ks.filter(seen).length, nr = ks.filter((k) => star(k) > 0).length, nn = ks.filter(noted).length;
  const sel = (f, opts, v) => `<select data-pf="${f}">${opts.map(([x, t]) => `<option value="${E(x)}" ${v === x ? 'selected' : ''}>${E(t)}</option>`).join('')}</select>`;
  return `<div class="dm-flt">${sel('dom', [['', '全部领域'], ...(D.graph.domains || []).map((d) => [d.id, d.name])], dom)}${sel('mrr', MRR, mrr)}${sel('st', ST, st)}
<span class="dm-m">星级、规模、来源等筛选沿用上面那排</span></div>
<div class="pn-sum"><span>共 <b>${ks.length}</b> 家</span><span>看过 <b>${ns}</b></span><span class="pn-bar"><i style="width:${ks.length ? Math.round(ns / ks.length * 100) : 0}%"></i></span><span>评过星 <b>${nr}</b></span><span>有评论 / 讨论 <b>${nn}</b></span>
<span class="pn-lg"><span>✓ 看过</span><span>★ 你的星级</span><span><span class="pn-c" style="border:none;padding:0;background:none"><u>2</u></span> 评论 / 讨论条数</span><span>每格按星级、收入排</span></span></div>
${ks.length ? `<div class="pn-grid" style="--cols:${cols.length}"><div class="pn-h">赛道（痛点）</div>${cols.map(([, l]) => `<div class="pn-h">${l}公司</div>`).join('')}${body}</div>` : '<div class="dm-m">没有符合筛选的公司</div>'}`;
}

export function popHtml(D, A, k, star, threads, starSvg) {
  const c = D.cards[k], n = A.notes[k], at = A.seen[k], v = star(k);
  const intro = [c.product, c.pain].filter(Boolean).join(' 痛点：');
  const links = [...(c.links || []).map((l) => [l[0], l[1]]), ...((c.deep?.sources || []).slice(0, 3).map((u) => { try { return [new URL(u).hostname.replace(/^www\./, ''), u]; } catch { return [u, u]; } }))];
  const rate = `<span class="dm-rate" style="float:none;margin:0">${[1, 2, 3, 4, 5].map((i) => `<button data-rate="${i}" data-k="${E(k)}" aria-label="${i} 星" class="${i <= v ? 'on' : ''}">${starSvg}</button>`).join('')}</span>`;
  const th = threads == null ? '<div class="dm-m">读取评论中…</div>' : threads.length ? threads.map((t) => {
    const u = t.msgs.filter((m) => m.role === 'user'), a = t.msgs.filter((m) => m.role === 'assistant');
    return `<div class="pn-th">${t.quote ? `<q>${E(t.quote.slice(0, 80))}</q>` : ''}${u.map((m) => `<div class="u">${E(m.content.slice(0, 160))}</div>`).join('')}${a.length ? `<div class="a">Claude：${E(a.at(-1).content.slice(0, 240))}</div>` : ''}<div class="dm-m">${E((t.updated_at || t.created_at || '').slice(0, 16))}</div></div>`;
  }).join('') : '<div class="dm-m">还没有评论或讨论。到详情卡里划词就能评论、问 Claude。</div>';
  return `<button class="x" data-pclose="1" aria-label="关闭">×</button><h4>${E(c.name)}</h4>
<div class="dm-m">${c.tier ? `<span class="dm-size ${c.tier}">${({ small: '小', mid: '中', large: '大' })[c.tier]}</span> ` : ''}${(c.sources || []).map(E).join(' · ')}${at ? ` · 看过于 ${E(at.slice(0, 10))}` : ''}</div>
<div class="pn-acts">${rate}<button data-pseen="${E(k)}" class="${at ? '' : 'primary'}">${at ? '标为没看过' : '标为看过'}</button><button data-go="${E(k)}">看详情卡${n ? `（评论 ${n.threads}）` : ''}</button></div>
<dl><dt>MRR</dt><dd>${c.arr_v ? `≈ ${money(c.arr_v / 12)}<span class="dm-m">（${E(c.arr || '')}）</span>` : c.arr ? E(c.arr) : '<span class="dm-m">没查到收入</span>'}</dd>
${c.funding ? `<dt>融资</dt><dd>${E(c.funding)}</dd>` : ''}
<dt>简介</dt><dd>${E(intro) || '<span class="dm-m">暂无</span>'}</dd>
${c.deep?.moat?.length ? `<dt>壁垒</dt><dd>${c.deep.moat.map((m) => `<span class="dm-chp">${E(m.kind)}</span>`).join('')}</dd>` : ''}
${links.length ? `<dt>链接</dt><dd>${links.map(([t, u]) => `<a href="${E(u)}" target="_blank" rel="noopener" data-pout="${E(k)}">${E(t)}</a>`).join(' · ')}</dd>` : ''}</dl>
<div><b style="font-size:13px">我的评论和讨论</b>${n ? `<span class="dm-m"> · ${n.threads} 条，问 Claude ${n.asks} 次</span>` : ''}</div>${th}`;
}
