// 深度学习：条目深读（论文 / GitHub）+ 主题学习计划。
// 路由：#learn（总览 + 智能输入框）、#learn/plans（同总览，滚到计划）、#learn/plan/<id>、
//       #learn/plan/<id>/step/<sid>（跟着学：一章教程 + 章末测试）、#learn/item/<id>（笔记阅读）
// 按需加一节：读某一章时说「X 没懂 / 对 X 感兴趣」（或划线后点），在这一章后插一节针对性讲解 + 小测试
import { annotate } from './_annotate.js';
const CSS = `
.ln-opts { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; margin: -4px 0 10px; }
.ln-opts .lbl { font-size: 12px; color: var(--muted); margin-right: 2px; }
.ln-pill { padding: 4px 12px; font-size: 13px; background: var(--panel); border-color: var(--line-2); max-width: 340px; }
.ln-pill span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ln-pill.empty { color: var(--muted); border-style: dashed; }
.ln-pill.on { border-color: var(--accent); color: var(--accent); background: var(--accent-soft); }
.ln-pill svg { width: 15px; height: 15px; color: var(--accent); }
.ln-edit { display: flex; gap: 8px; align-items: center; margin: -2px 0 12px; padding: 10px 12px; background: var(--panel);
  border: 1px solid var(--line); border-radius: var(--radius-sm); }
.ln-edit input { flex: 1; }
.ln-edit .muted { white-space: nowrap; }
.ln-back { display: inline-flex; align-items: center; gap: 4px; font-size: 13px; color: var(--muted); margin-bottom: 10px; }
.ln-back svg { transform: rotate(180deg); width: 15px; height: 15px; }
.ln-card-click { cursor: pointer; transition: border-color .12s, transform .12s; }
.ln-card-click:hover { border-color: var(--accent); }
.ln-pcard h3 { font-size: 19px; margin: 2px 0 10px; }
.ln-pcard .next { font-size: 13px; margin-top: 8px; color: var(--text); }
.ln-pcard .next b { color: var(--accent); font-weight: 500; margin-right: 4px; }
.ln-icard { display: flex; flex-direction: column; }
.ln-icard h3 { font-size: 17px; line-height: 1.4; margin: 6px 0 6px; }
.ln-icard .tldr { white-space: pre-line; font-size: 13px; color: var(--muted); flex: 1; }
.ln-icard .foot { display: flex; align-items: center; gap: 8px; margin-top: 12px; padding-top: 10px; border-top: 1px solid var(--line); }
.ln-badge { font-size: 11px; padding: 0 8px; border-radius: 6px; line-height: 20px; font-weight: 600; letter-spacing: .03em; }
.ln-badge.paper { background: var(--accent-soft); color: var(--accent); }
.ln-steps { margin-top: 10px; display: flex; flex-direction: column; gap: 3px; }
.ln-step { font: 12px/1.5 var(--mono); color: var(--muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.ln-step:last-child { color: var(--accent); }
.ln-badge.github { background: var(--dark); color: var(--bg); }
.ln-badge.article { background: var(--ok-soft); color: var(--ok); }
.ln-badge.video { background: var(--warn-soft, var(--accent-soft)); color: var(--warn, var(--accent)); }
.ln-reads .ln-rd { display: grid; grid-template-columns: 7.5em 3em 1fr; gap: 8px; align-items: baseline; padding: 6px 0; border-top: 1px dashed var(--line); font-size: 13.5px; }
.ln-reads .ln-rd:first-of-type { border-top: 0; }
.ln-dd-exps { margin-bottom: 12px; } .ln-dd-exps .ln-rd { display: grid; grid-template-columns: 2.6em 3.4em 5.5em 1fr auto; gap: 8px; align-items: baseline; padding: 6px 0; border-top: 1px dashed var(--line); font-size: 13.5px; }
.ln-dd-exps .ln-rd:first-child { border-top: 0; }
/* 追问清单：逐题作答 + Agent 点评 */
.ln-qa { display: grid; gap: 10px; }
.ln-qa .qa { padding: 12px 14px; border: 1px solid var(--line); border-radius: var(--radius-sm); background: var(--panel); }
.ln-qa .qa.done { background: var(--bg); }
.ln-qa .qa .qh { display: flex; gap: 8px; align-items: baseline; }
.ln-qa .qa .qh .no { flex: none; font: 700 12px var(--mono); color: var(--accent); }
.ln-qa .qa .qh .qt { flex: 1; min-width: 0; } .ln-qa .qa .qh .qt p { margin: 0; }
.ln-qa .qa .qh .tag { flex: none; }
.ln-qa .qa textarea { width: 100%; margin-top: 8px; }
.ln-qa .qa .acts { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-top: 8px; }
.ln-qa .qa .mine { margin-top: 8px; padding: 8px 10px; border-left: 3px solid var(--line-2); white-space: pre-wrap; font-size: 13.5px; }
.ln-qa .qa .rv { margin-top: 8px; padding: 10px 12px; border-radius: var(--radius-sm); border: 1px solid var(--line); font-size: 13.5px; background: var(--panel); }
.ln-qa .qa .rv .row2 { display: flex; gap: 8px; margin: 3px 0; } .ln-qa .qa .rv .row2 > b { flex: none; min-width: 52px; font-size: 12px; }
.ln-qa .qa .rv .ok > b { color: var(--ok); } .ln-qa .qa .rv .miss > b { color: var(--warn); }
.ln-qa .qa .rv .better { margin-top: 6px; padding-top: 6px; border-top: 1px dashed var(--line-2); } .ln-qa .qa .rv .better p { margin: 4px 0; }
.ln-qa .qa .rv .sc { float: right; font: 700 13px var(--mono); color: var(--accent); }
.ln-qa .qa .rv .better .md { font-size: inherit; line-height: 1.65; } .ln-qa .qa .qt .md { font-size: 14.5px; }
.ln-qa details.old { font-size: 13px; } .ln-qa details.old .qa { margin-top: 8px; }
.ln-qa .qa .opt { display: flex; gap: 8px; align-items: flex-start; padding: 7px 10px; margin-top: 6px; border: 1px solid var(--line); border-radius: var(--radius-sm); cursor: pointer; font-size: 14px; background: var(--bg); }
.ln-qa .qa .opt:hover { border-color: var(--accent); }
.ln-qa .qa.locked .opt { cursor: default; } .ln-qa .qa.locked .opt:hover { border-color: var(--line); }
.ln-qa .qa .opt .k { flex: none; font: 700 12px/1.9 var(--mono); color: var(--muted); }
.ln-qa .qa .opt.right { border-color: var(--ok); background: var(--ok-soft); } .ln-qa .qa .opt.wrong { border-color: var(--err); background: var(--err-soft); }
.ln-qa .qa .qh .dim { flex: none; font-size: 11px; color: var(--muted); }
.ln-qa .gen { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; padding: 12px 14px; border: 1px dashed var(--line-2); border-radius: var(--radius-sm); font-size: 13.5px; }
.ln-qa details.legacy > summary { cursor: pointer; font-size: 13px; } .ln-qa details.legacy > .qa { margin-top: 8px; }
.ln-stars { display: inline-flex; gap: 0; }
.ln-stars button { border: none; background: none; padding: 1px; color: var(--line-2); border-radius: 4px; }
.ln-stars button svg { width: 17px; height: 17px; }
.ln-stars button.on { color: var(--accent); } .ln-stars button.on svg { fill: var(--accent); }
.ln-stars button:hover { color: var(--accent); }
.ln-stars.ro svg { width: 13px; height: 13px; }
.ln-head h1 { font-size: 30px; }
.ln-meta { display: flex; gap: 14px; align-items: center; flex-wrap: wrap; font-size: 13px; color: var(--muted); margin-top: 10px; }
.ln-meta .pct { font: 700 22px var(--serif); color: var(--accent); }
.ln-meta .progress { flex: 1; min-width: 160px; }
.ln-stagecard h3 { font-size: 17px; margin: 0 0 18px; }
.ln-stages { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); }
.ln-banner { display: flex; gap: 12px; align-items: center; padding: 12px 16px; margin-bottom: 14px; font-size: 14px; }
.ln-banner .t { flex: 1; min-width: 0; } .ln-banner .t .muted { font-size: 13px; }
.ln-res .sm { flex: none; }
.ln-stage { position: relative; text-align: center; cursor: pointer; padding: 0 4px; }
.ln-stage::before { content: ''; position: absolute; top: 9px; left: -50%; right: 50%; height: 1.5px; background: var(--line-2); }
.ln-stage:first-child::before { display: none; }
.ln-stage.reached::before { background: var(--accent); }
.ln-dot { position: relative; z-index: 1; width: 20px; height: 20px; margin: 0 auto 8px; border-radius: 50%; display: grid; place-items: center;
  background: var(--panel); border: 1.5px solid var(--line-2); }
.ln-dot svg { width: 12px; height: 12px; stroke-width: 3; color: #fff; }
.ln-stage.done .ln-dot { background: var(--accent); border-color: var(--accent); }
.ln-stage.cur .ln-dot { border-color: var(--accent); box-shadow: 0 0 0 5px var(--accent-ring); }
.ln-stage.cur .ln-dot::after { content: ''; width: 8px; height: 8px; border-radius: 50%; background: var(--accent); }
.ln-stage .k { font-size: 12px; color: var(--muted); }
.ln-stage .n { font-size: 13px; line-height: 1.35; }
.ln-stage.cur .n, .ln-stage.cur .k { color: var(--accent); }
.ln-stage.empty { opacity: .5; cursor: default; }
.ln-stage:hover .n { color: var(--accent); }
.ln-adapt { display: flex; gap: 8px; align-items: center; margin-top: 16px; padding-top: 14px; border-top: 1px solid var(--line); }
.ln-adapt input { flex: 1; }
.ln-step { padding: 14px 18px; margin-bottom: 10px; }
.ln-step.done { background: var(--bg); box-shadow: none; }
.ln-step.done .ln-st-title { color: var(--muted); text-decoration: line-through; text-decoration-color: var(--line-2); }
.ln-step.skipped { opacity: .55; box-shadow: none; }
.ln-step.cur { border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-ring); }
.ln-st-head { display: flex; gap: 10px; align-items: center; }
.ln-st-title { flex: 1; min-width: 0; font-weight: 600; font-size: 15px; cursor: pointer; }
.ln-check { width: 24px; height: 24px; padding: 0; justify-content: center; border-radius: 50%; border: 1.5px solid var(--line-2); background: var(--panel); flex: none; }
.ln-check svg { width: 14px; height: 14px; stroke-width: 2.6; color: transparent; }
.ln-check:hover svg { color: var(--accent); }
.ln-check.on { background: var(--accent); border-color: var(--accent); } .ln-check.on svg { color: #fff; }
.ln-st-head select { width: auto; font-size: 12px; padding: 2px 6px; border-radius: 8px; }
.ln-st-body { margin: 10px 0 0 34px; }
.ln-st-head .tg svg { transition: transform .15s; } .ln-step.open .ln-st-head .tg svg { transform: rotate(90deg); }
.ln-st-body .md { font-size: 14px; }
.ln-st-sub { font-size: 12px; color: var(--muted); margin: 12px 0 4px; letter-spacing: .03em; }
.ln-res { display: flex; gap: 8px; align-items: baseline; padding: 7px 10px; border-radius: var(--radius-sm); }
.ln-res:hover { background: var(--bg); }
.ln-res svg { width: 15px; height: 15px; color: var(--accent); align-self: center; }
.ln-res a { font-weight: 500; }
.ln-res .why { color: var(--muted); font-size: 13px; flex: 1; min-width: 0; }
.ln-q { display: flex; gap: 8px; padding: 4px 10px; font-size: 14px; }
.ln-q .no { color: var(--accent); font: 700 13px var(--serif); min-width: 18px; }
.ln-fb { display: flex; gap: 10px; align-items: center; margin-top: 14px; flex-wrap: wrap; }
.ln-fb input { flex: 1; min-width: 220px; }
.ln-saved { font-size: 12px; color: var(--ok); }
.ln-st-actions { display: flex; gap: 8px; align-items: center; margin-top: 10px; flex-wrap: wrap; }
.ln-reader { max-width: 780px; margin: 0 auto; }
.ln-reader .card { padding: 30px 40px; }
.ln-reader .md { font-size: 15.5px; line-height: 1.9; }
.ln-reader .md > :first-child { margin-top: 0; }
.ln-reader .md h1, .ln-reader .md h2, .ln-reader .md h3 { font-family: var(--serif); }
.ln-reader .md h2 { font-size: 21px; margin-top: 1.6em; padding-bottom: 4px; border-bottom: 1px solid var(--line); }
.ln-reader .md h3 { font-size: 17px; }
.ln-reader .md code { background: var(--bg-2); padding: 1px 5px; border-radius: 4px; }
.ln-reader .md pre code { background: none; padding: 0; }
.ln-reader .md img { display: block; max-width: 100%; height: auto; margin: 18px auto 6px; border-radius: 6px; border: 1px solid var(--line); background: #fff; cursor: zoom-in; }
.ln-reader .md img + em, .ln-reader .md p:has(> img) + blockquote { font-size: 14px; }
.ln-tldr { background: var(--focus); border: 1px solid var(--line); border-radius: var(--radius); padding: 16px 22px; margin-bottom: 14px; }
.ln-tldr ul { margin: 6px 0 0; padding-left: 18px; } .ln-tldr li { margin: 3px 0; }
.ln-purpose { font-size: 13px; color: var(--muted); margin: -6px 0 12px; padding-left: 10px; border-left: 2px solid var(--accent); }
.ln-purpose b { color: var(--text); font-weight: 500; }
.ln-goal { font-size: 13px; margin: 0 0 8px; } .ln-goal b { color: var(--accent); font-weight: 500; margin-right: 4px; }
.ln-cs { font-size: 11px; }
.ln-continue { display: flex; gap: 14px; align-items: center; padding: 14px 18px; margin-bottom: 16px; border-color: var(--accent); }
.ln-continue .t { flex: 1; min-width: 0; } .ln-continue .t .k { font-size: 12px; color: var(--muted); } .ln-continue .t .n { font-weight: 600; }
/* 章节阅读 */
.ln-chap { display: grid; grid-template-columns: 168px minmax(0, 1fr); gap: 20px; align-items: start; }
.ln-chap .an-wrap { grid-template-columns: minmax(0, 1fr) minmax(200px, 240px); }
.ln-chap .an-wrap:not(.has-threads) { grid-template-columns: minmax(0, 1fr); } /* 没有批注时不占宽度，划线评论时再出现 */
.ln-chap .an-wrap:not(.has-threads) .an-rail { display: none; }
.ln-chap .an-wrap.has-threads.has-w { grid-template-columns: minmax(0, 1fr) var(--an-rail-w); } /* 拖宽过的批注栏 */
.ln-chap .an-wrap.has-threads.rail-off { grid-template-columns: minmax(0, 1fr) 30px; }
.ln-chap .md { font-size: 15px; line-height: 1.85; }
.ln-chap .md h2 { font-family: var(--serif); font-size: 20px; margin-top: 1.6em; padding-bottom: 4px; border-bottom: 1px solid var(--line); }
.ln-toc { position: sticky; top: 16px; font-size: 13px; max-height: calc(100vh - 40px); overflow: auto; }
.ln-toc .k { font-size: 12px; color: var(--muted); letter-spacing: .03em; margin-bottom: 6px; }
.ln-toc a { display: block; padding: 4px 8px; border-left: 2px solid var(--line); color: var(--muted); line-height: 1.4; }
.ln-toc a:hover, .ln-toc a.on { color: var(--accent); border-left-color: var(--accent); }
.ln-toc a.quiz { margin-top: 8px; color: var(--accent); font-weight: 500; }
.ln-toc .k { display: flex; align-items: center; gap: 4px; } .ln-toc .k span { flex: 1; }
.ln-toc .k button { padding: 0 6px; font-size: 12px; line-height: 20px; border: 0; background: none; color: var(--muted); }
.ln-toc .k button:hover { color: var(--accent); }
.ln-chap.toc-off { grid-template-columns: 28px minmax(0, 1fr); }
.ln-chap.toc-off .ln-toc { overflow: visible; }
.ln-chap.toc-off .ln-toc > :not(.toc-open) { display: none; }
.ln-toc .toc-open { display: none; writing-mode: vertical-rl; padding: 10px 3px; font-size: 12px; letter-spacing: .2em; color: var(--muted); border-radius: var(--radius-sm); }
.ln-toc .toc-open:hover { color: var(--accent); border-color: var(--accent); }
.ln-chap.toc-off .ln-toc .toc-open { display: block; }
@media (max-width: 1150px) { .ln-chap, .ln-chap.toc-off { grid-template-columns: minmax(0, 1fr); } /* 窄屏目录本来就隐藏，收起状态不能占列 */ .ln-toc { display: none; } .ln-chap .an-wrap, .ln-chap .an-wrap.has-threads.has-w { grid-template-columns: minmax(0, 1fr); } }
.ln-chap-head .k { font-size: 13px; color: var(--muted); }
.ln-chap .md .fact, .ln-chap .md .judge { display: inline-block; font-size: 11px; font-weight: 600; line-height: 18px; padding: 0 7px; border-radius: 5px; margin-right: 6px; vertical-align: 1px; }
.ln-chap .md .fact { background: var(--accent-soft); color: var(--accent); }
.ln-chap .md .judge { background: var(--bg-2); color: var(--muted); border: 1px solid var(--line-2); }
.ln-chap .md details { margin: 10px 0; padding: 8px 14px; background: var(--bg); border: 1px solid var(--line); border-radius: var(--radius-sm); }
.ln-chap .md details summary { cursor: pointer; font-size: 13px; color: var(--muted); }
.ln-chap .md blockquote { border-left: 3px solid var(--accent); background: var(--focus); margin: 12px 0; padding: 8px 16px; border-radius: 0 var(--radius-sm) var(--radius-sm) 0; }
.ln-chap .md table { border-collapse: collapse; font-size: 14px; display: block; overflow-x: auto; }
.ln-chap .md th, .ln-chap .md td { border: 1px solid var(--line); padding: 5px 9px; vertical-align: top; min-width: 7em; }
.ln-chap .md pre { overflow-x: auto; white-space: pre; } /* 老章节里的字符画：不换行，横向滚动 */
/* 章节图示组件（skills/learn/chapter.md「图示组件」）：Agent 写结构化 HTML，样式在这里 */
.ln-chap .md [class^="dg-"] b { font-weight: 600; }
.ln-chap .md .dg-tree, .ln-chap .md .dg-flow, .ln-chap .md .dg-cards, .ln-chap .md .dg-vs { margin: 16px 0 20px; font-size: 13.5px; line-height: 1.55; }
.ln-chap .md .dg-root { margin: 0 auto; max-width: 560px; text-align: center; padding: 12px 18px; border-radius: var(--radius); background: var(--accent); color: #fff; }
.ln-chap .md .dg-root b, .ln-chap .md .dg-root span { display: block; } .ln-chap .md .dg-root span { opacity: .9; margin-top: 2px; }
.ln-chap .md .dg-branches { position: relative; display: grid; grid-template-columns: repeat(var(--n, 3), minmax(0, 1fr)); gap: 12px; margin-top: 26px; padding-top: 0; }
.ln-chap .md .dg-branches::before { content: ''; position: absolute; top: -26px; left: 50%; height: 13px; border-left: 1.5px solid var(--line-2); }
.ln-chap .md .dg-branches::after { content: ''; position: absolute; top: -13px; left: 8%; right: 8%; border-top: 1.5px solid var(--line-2); }
.ln-chap .md .dg-branch { position: relative; padding: 10px 12px; border: 1px solid var(--line); border-top: 3px solid var(--accent); border-radius: var(--radius-sm); background: var(--panel); }
.ln-chap .md .dg-branch::before { content: ''; position: absolute; top: -16px; left: 50%; height: 13px; border-left: 1.5px solid var(--line-2); }
.ln-chap .md .dg-branch ul { margin: 6px 0 0; padding-left: 16px; } .ln-chap .md .dg-branch li { margin: 2px 0; color: var(--muted); }
.ln-chap .md .dg-flow { display: flex; flex-wrap: wrap; gap: 8px 26px; align-items: stretch; }
.ln-chap .md .dg-node { position: relative; flex: 1 1 120px; padding: 10px 12px; border: 1px solid var(--line); border-radius: var(--radius-sm); background: var(--panel); }
.ln-chap .md .dg-node b, .ln-chap .md .dg-node span { display: block; } .ln-chap .md .dg-node span { color: var(--muted); font-size: 12.5px; margin-top: 2px; }
.ln-chap .md .dg-node:not(:last-child)::after { content: '→'; position: absolute; right: -20px; top: 50%; transform: translateY(-50%); color: var(--accent); font-weight: 700; }
.ln-chap .md .dg-flow.loop::after { content: '↺ 回到第一步，持续迭代'; flex-basis: 100%; text-align: center; font-size: 12px; color: var(--accent); padding: 4px; border: 1.5px dashed var(--accent-ring); border-top: 0; border-radius: 0 0 var(--radius-sm) var(--radius-sm); }
.ln-chap .md .dg-cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 10px; }
.ln-chap .md .dg-card { padding: 12px 14px; border: 1px solid var(--line); border-radius: var(--radius-sm); background: var(--panel); }
.ln-chap .md .dg-card i { display: inline-block; font-style: normal; font-size: 11px; padding: 0 7px; margin: 0 0 4px 6px; border-radius: 5px; background: var(--bg-2); color: var(--muted); }
.ln-chap .md .dg-card p, .ln-chap .md .dg-side p { margin: 4px 0 0; color: var(--muted); }
.ln-chap .md .dg-vs { display: grid; grid-template-columns: 1fr 1fr; gap: 0; border: 1px solid var(--line); border-radius: var(--radius-sm); overflow: hidden; }
.ln-chap .md .dg-side { padding: 12px 16px; background: var(--panel); } .ln-chap .md .dg-side + .dg-side { border-left: 1px solid var(--line); background: var(--bg); }
/* 体系架构图：从上到下分层，右侧一列贯穿各层的关注点 */
.ln-chap .md .dg-arch { display: grid; grid-template-columns: minmax(0, 1fr) minmax(140px, 22%); gap: 10px; margin: 16px 0 20px; font-size: 13px; line-height: 1.5; }
.ln-chap .md .dg-arch:not(:has(.dg-cross)) { grid-template-columns: minmax(0, 1fr); }
.ln-chap .md .dg-stack { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
.ln-chap .md .dg-layer { display: grid; grid-template-columns: 96px minmax(0, 1fr); gap: 10px; align-items: stretch; padding: 8px 10px; border: 1px solid var(--line); border-radius: var(--radius-sm); background: var(--bg); }
.ln-chap .md .dg-layer > b { display: flex; align-items: center; font-size: 12.5px; color: var(--accent); border-right: 2px solid var(--accent-ring); padding-right: 8px; }
.ln-chap .md .dg-layer:first-child { background: var(--accent-soft); }
.ln-chap .md .dg-boxes { display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 6px; }
.ln-chap .md .dg-box { padding: 7px 10px; border: 1px solid var(--line); border-radius: var(--radius-sm); background: var(--panel); min-width: 0; }
.ln-chap .md .dg-box > b, .ln-chap .md .dg-box > span { display: block; } .ln-chap .md .dg-box > span { color: var(--muted); font-size: 12px; margin-top: 1px; }
.ln-chap .md .dg-cross { display: flex; flex-direction: column; gap: 6px; padding: 8px 10px; border: 1.5px dashed var(--accent-ring); border-radius: var(--radius-sm); }
.ln-chap .md .dg-cross > b { font-size: 12.5px; color: var(--accent); text-align: center; }
.ln-chap .md .dg-box .dg-go { display: block; margin-top: 3px; font-size: 11.5px; font-weight: 500; color: var(--accent); text-align: right; }
.ln-chap .md .dg-box .dg-go.more { color: var(--muted); } .ln-chap .md .dg-box .dg-go.more:hover { color: var(--accent); }
.ln-chap .md .dg-box.dg-link { cursor: pointer; } .ln-chap .md .dg-box.dg-link:hover { border-color: var(--accent); }
@media (max-width: 640px) { .ln-chap .md .dg-arch { grid-template-columns: 1fr; } .ln-chap .md .dg-layer { grid-template-columns: 1fr; } .ln-chap .md .dg-layer > b { border-right: 0; border-bottom: 2px solid var(--accent-ring); padding: 0 0 4px; } }
.ln-chap .md .hot { border-color: var(--accent); box-shadow: 0 0 0 2px var(--accent-ring); }
.ln-chap .md .warn { border-color: var(--warn); background: var(--warn-soft); }
/* 交互：点开细节 / 逐步播放 / 标签页 / 翻转卡 / 小组件 */
.ln-chap .md .dg-more { display: none; margin-top: 6px; padding-top: 6px; border-top: 1px dashed var(--line-2); color: var(--text); font-size: 13px; }
.ln-chap .md .has-more { cursor: pointer; } .ln-chap .md .has-more.open > .dg-more { display: block; }
.ln-chap .md .has-more > b::after { content: ' +'; color: var(--accent); font-weight: 400; } .ln-chap .md .has-more.open > b::after { content: ' −'; }
.ln-chap .md .has-more:hover { border-color: var(--accent); }
.ln-chap .md .dg-flow.steps .dg-node { opacity: .45; transition: opacity .2s; } .ln-chap .md .dg-flow.steps .dg-node.on { opacity: 1; border-color: var(--accent); box-shadow: 0 0 0 2px var(--accent-ring); }
.ln-chap .md .dg-flow.steps .dg-node.seen { opacity: 1; }
.ln-chap .md .dg-flow.steps .dg-node > .dg-more { display: none !important; }
.ln-chap .md .dg-stepper { display: flex; gap: 10px; align-items: flex-start; margin: -8px 0 18px; padding: 10px 14px; background: var(--bg); border: 1px solid var(--line); border-radius: var(--radius-sm); font-size: 13.5px; }
.ln-chap .md .dg-stepper .txt { flex: 1; min-width: 0; } .ln-chap .md .dg-stepper .n { color: var(--accent); font: 700 13px var(--mono); white-space: nowrap; }
.ln-chap .md .dg-tabs { margin: 16px 0 20px; border: 1px solid var(--line); border-radius: var(--radius-sm); background: var(--panel); }
.ln-chap .md .dg-tabbar { display: flex; flex-wrap: wrap; gap: 2px; padding: 6px 6px 0; border-bottom: 1px solid var(--line); background: var(--bg); border-radius: var(--radius-sm) var(--radius-sm) 0 0; }
.ln-chap .md .dg-tabbar button { border: 0; background: none; padding: 6px 12px; font-size: 13px; color: var(--muted); border-bottom: 2px solid transparent; border-radius: 0; }
.ln-chap .md .dg-tabbar button.on { color: var(--accent); border-bottom-color: var(--accent); font-weight: 600; }
.ln-chap .md .dg-tab { display: none; padding: 4px 16px 10px; } .ln-chap .md .dg-tab.on { display: block; }
.ln-chap .md .dg-flash { position: relative; margin: 16px 0; padding: 12px 16px 14px; border: 1px dashed var(--accent); border-radius: var(--radius-sm); background: var(--accent-soft); font-size: 14px; }
.ln-chap .md .dg-flash .lbl { font-size: 11px; font-weight: 700; color: var(--accent); letter-spacing: .05em; }
.ln-chap .md .dg-flash .dg-q { font-weight: 500; margin: 2px 0 8px; }
.ln-chap .md .dg-flash > .dg-a { display: none; }
.ln-chap .md .dg-flash textarea { width: 100%; font-size: 14px; background: var(--panel); }
.ln-chap .md .dg-parts { display: grid; gap: 6px; }
.ln-chap .md .dg-parts label { display: grid; grid-template-columns: 92px 1fr; gap: 8px; align-items: start; }
.ln-chap .md .dg-parts label > span { font-size: 12px; font-weight: 600; color: var(--muted); padding-top: 7px; }
.ln-apply .ln-applyform { display: grid; grid-template-columns: 1fr 1fr auto; gap: 6px; margin-top: 10px; }
.ln-apply .ln-applyform .what { grid-column: 1 / -1; }
@media (max-width: 720px) { .ln-apply .ln-applyform { grid-template-columns: 1fr; } }
.ln-refs { margin-top: 8px; font-size: 13px; display: grid; gap: 4px; }
.ln-habits { display: grid; gap: 6px; margin: 10px 0; padding: 10px 14px; }
.ln-habit { display: grid; grid-template-columns: auto 9em 1fr; gap: 10px; align-items: baseline; font-size: 13px; color: inherit; text-decoration: none; }
.ln-habit .muted { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
@media (max-width: 640px) { .ln-habit { grid-template-columns: auto 1fr; } .ln-habit .muted { grid-column: 1 / -1; white-space: normal; } }
a.ln-habit:hover b { text-decoration: underline; }
.ln-chkstat { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin: 8px 0; font-size: 13px; }
.ln-chap .md .dg-ptags { display: flex; gap: 6px; flex-wrap: wrap; margin: 0 0 6px; }
@media (max-width: 640px) { .ln-chap .md .dg-parts label { grid-template-columns: 1fr; gap: 2px; } .ln-chap .md .dg-parts label > span { padding-top: 0; } }
.ln-chap .md .dg-flash .acts { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-top: 8px; }
.ln-chap .md .dg-flash .acts .muted { font-size: 12px; }
.ln-chap .md .dg-flash.open { border-style: solid; background: var(--panel); }
.ln-chap .md .dg-cmp { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 10px; }
.ln-chap .md .dg-cmp > div { padding: 10px 12px; border-radius: var(--radius-sm); border: 1px solid var(--line); background: var(--bg); min-width: 0; }
.ln-chap .md .dg-cmp > div > .k { font-size: 11px; font-weight: 700; color: var(--muted); letter-spacing: .05em; margin-bottom: 4px; }
.ln-chap .md .dg-cmp .mine { white-space: pre-wrap; } .ln-chap .md .dg-cmp .pts { background: var(--focus); }
.ln-chap .md .dg-cmp ul { margin: 0; padding-left: 18px; }
.ln-chap .md .dg-rv { margin-top: 10px; padding: 10px 12px; border-radius: var(--radius-sm); border: 1px solid var(--line); font-size: 13.5px; }
.ln-chap .md .dg-rv .row2 { display: flex; gap: 8px; margin: 3px 0; } .ln-chap .md .dg-rv .row2 > b { flex: none; min-width: 52px; font-size: 12px; }
.ln-chap .md .dg-rv .ok > b { color: var(--ok); } .ln-chap .md .dg-rv .miss > b { color: var(--warn); } .ln-chap .md .dg-rv .bad > b { color: var(--err); } .ln-chap .md .dg-rv .plus > b { color: var(--accent); }
.ln-chap .md .dg-rv .better { margin-top: 6px; padding-top: 6px; border-top: 1px dashed var(--line-2); }
.ln-chap .md .dg-rv .sc { float: right; font: 700 13px var(--mono); color: var(--accent); }
@media (max-width: 640px) { .ln-chap .md .dg-cmp { grid-template-columns: 1fr; } }
.ln-chap .md .dg-widget { margin: 16px 0 20px; border: 1px solid var(--line); border-radius: var(--radius-sm); overflow: hidden; background: var(--panel); }
.ln-chap .md .dg-widget .wt { padding: 7px 12px; font-size: 12.5px; color: var(--muted); background: var(--bg); border-bottom: 1px solid var(--line); }
.ln-chap .md .dg-widget iframe { display: block; width: 100%; border: 0; background: transparent; }
/* 知识卡复习 */
.ln-tabs2 { display: flex; gap: 4px; margin-bottom: 12px; } .ln-tabs2 button.on { background: var(--accent-soft); color: var(--accent); border-color: var(--accent); }
.ln-kp { display: grid; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); gap: 10px; }
.ln-kpc { padding: 12px 14px; border: 1px solid var(--line); border-left: 3px solid var(--accent); border-radius: var(--radius-sm); background: var(--panel); font-size: 14px; }
.ln-kpc .hd { display: flex; gap: 8px; align-items: baseline; margin-bottom: 4px; } .ln-kpc .hd b { flex: 1; }
.ln-kpc .tg { font-size: 11px; color: var(--muted); white-space: nowrap; } .ln-kpc .md { font-size: 13.5px; color: var(--text); } .ln-kpc .md p { margin: 0; }
.ln-dim { background: var(--accent-soft); color: var(--accent); }
.ln-hist { margin-top: 14px; } .ln-hist > summary { cursor: pointer; }
.ln-hi { padding: 10px 0; border-top: 1px solid var(--line); font-size: 13.5px; }
.ln-hi .hd { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-bottom: 4px; } .ln-hi .at { font: 12px var(--mono); color: var(--muted); }
.ln-hi .sub { margin: 3px 0; } .ln-hi .sub > b { font-weight: 600; } .ln-hi .mine { margin: 3px 0; padding: 4px 8px; background: var(--bg); border-radius: 6px; white-space: pre-wrap; }
.ln-hi details > summary { cursor: pointer; font-size: 12.5px; color: var(--muted); margin-top: 4px; }
.ln-growth { margin-bottom: 16px; } .ln-growth h3 { margin: 0; font-size: 17px; }
.ln-gch { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
.ln-gch a { display: inline-flex; gap: 8px; padding: 4px 10px; border: 1px solid var(--line); border-radius: 8px; font-size: 12.5px; color: var(--text); }
.ln-gch a b { color: var(--accent); font-family: var(--mono); }
.ln-weak { font-size: 13px; padding: 3px 0; } .ln-weak .tag { margin-right: 6px; }
.ln-about { font-size: 12px; color: var(--accent); margin: -4px 0 6px 22px; }
.ln-dims { margin-top: 10px; display: flex; flex-direction: column; gap: 6px; }
.ln-dimrow { display: grid; grid-template-columns: 34px 120px 40px minmax(0, 1fr); gap: 8px; align-items: center; font-size: 13px; }
.ln-dimrow .bar { height: 6px; border-radius: 3px; background: var(--bg-2); overflow: hidden; } .ln-dimrow .bar i { display: block; height: 100%; background: var(--accent); }
.ln-dimrow .v { font: 600 12px var(--mono); } .ln-dimrow .t { color: var(--muted); }
@media (max-width: 640px) { .ln-dimrow { grid-template-columns: 34px 1fr 40px; } .ln-dimrow .t { grid-column: 1 / -1; } }
@media (max-width: 640px) { .ln-chap .md .dg-branches { grid-template-columns: repeat(2, minmax(0, 1fr)); } .ln-chap .md .dg-vs { grid-template-columns: 1fr; } .ln-chap .md .dg-side + .dg-side { border-left: 0; border-top: 1px solid var(--line); }
  .ln-chap .md .dg-node:not(:last-child)::after { content: '↓'; right: auto; left: 50%; top: auto; bottom: -19px; transform: none; } }
.ln-qz { padding: 16px 20px; margin-bottom: 10px; }
.ln-qz .qh { display: flex; gap: 10px; align-items: baseline; }
.ln-qz .qh .no { color: var(--accent); font: 700 15px var(--serif); }
.ln-qz .qh .q { flex: 1; font-weight: 500; white-space: pre-wrap; }
.ln-qz .opt { display: flex; gap: 8px; align-items: flex-start; padding: 7px 10px; margin: 4px 0 0 22px; border: 1px solid var(--line); border-radius: var(--radius-sm); cursor: pointer; }
.ln-qz .opt input { margin-top: 4px; width: auto; }
.ln-qz .opt.right { border-color: var(--ok); background: var(--ok-soft); }
.ln-qz .opt.wrong { border-color: var(--err); background: var(--err-soft); }
.ln-qz textarea { margin: 8px 0 0 22px; width: calc(100% - 22px); }
.ln-qz .fbk { margin: 10px 0 0 22px; font-size: 14px; padding: 8px 12px; border-radius: var(--radius-sm); background: var(--bg); }
.ln-qz .fbk .ref { color: var(--muted); margin-top: 6px; white-space: pre-wrap; }
.ln-qz .sc { font: 700 13px var(--mono); }
.ln-qz .sc.full { color: var(--ok); } .ln-qz .sc.part { color: var(--warn); } .ln-qz .sc.zero { color: var(--err); }
.ln-score { display: flex; gap: 18px; align-items: center; padding: 18px 22px; margin-bottom: 12px; }
.ln-score .big { font: 700 40px var(--serif); line-height: 1; }
.ln-score.pass .big { color: var(--ok); } .ln-score.fail .big { color: var(--err); }
.ln-score .t { flex: 1; min-width: 0; font-size: 14px; } .ln-score ul { margin: 6px 0 0; padding-left: 18px; }
/* 按需加一节 */
.ln-extra { padding: 16px 20px; margin-top: 14px; border-style: dashed; border-color: var(--line-2); }
.ln-extra .hd { display: flex; gap: 10px; align-items: baseline; flex-wrap: wrap; margin-bottom: 10px; } .ln-extra .hd b { font-size: 15px; }
.ln-extra .hd .muted { font-size: 12.5px; }
.ln-extra .ln-tabs2 { margin-bottom: 8px; }
.ln-extra input { flex: 1; min-width: 200px; }
.ln-xquote { display: flex; gap: 8px; align-items: center; margin-bottom: 8px; padding: 6px 10px; font-size: 13px; color: var(--muted);
  background: var(--focus); border-left: 3px solid var(--accent); border-radius: 0 var(--radius-sm) var(--radius-sm) 0; }
.ln-xquote span { flex: 1; min-width: 0; }
.ln-xkids { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; margin-top: 10px; font-size: 13px; }
.ln-xkids a { display: inline-flex; gap: 6px; align-items: center; padding: 2px 10px; border: 1px solid var(--line); border-radius: 999px; }
.ln-xkids a.on { border-color: var(--accent); color: var(--accent); }
.ln-step.extra { margin-left: 28px; border-left: 3px solid var(--accent-ring); }
.ln-xtag { background: var(--accent-soft); color: var(--accent); }
.ln-chap-nav { display: flex; gap: 10px; justify-content: space-between; margin: 22px 0 8px; }
.ln-chap-nav button { max-width: 48%; } .ln-chap-nav span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
`;
const STATUS_TAG = { archived: 'gray', done: 'ok', active: 'ok', failed: 'err', running: 'warn', queued: 'warn', generating: 'warn', adapting: 'warn' };
const STATUS_TXT = { archived: '已归档', queued: '排队', running: '解析中', done: '完成', failed: '失败', generating: '生成中', active: '进行中', adapting: '调整中' };
const STEP_TXT = { todo: '待学', doing: '学习中', done: '已完成', skipped: '跳过' };
const openedChapters = new Set(); // 本次页面会话里已经「进入」过的章节（避免软刷新时重复触发生成）
const draftKey = (sid) => `ln-quiz-${sid}`;
const loadDraft = (sid) => { try { return JSON.parse(localStorage.getItem(draftKey(sid)) || '{}'); } catch { return {}; } };
const saveDraft = (sid, d) => { try { localStorage.setItem(draftKey(sid), JSON.stringify(d)); } catch { /* ignore */ } };
const chapterHref = (pid, sid) => `#learn/plan/${pid}/step/${sid}`;
const EXTRA_TXT = { interest: '深入', confused: '补课' };
// 新计划三轮（「第 1 轮」），老计划六阶段（「阶段 1」）
const stageNo = (p, no) => (p.unit === '轮' ? `第 ${no} 轮` : p.unit === '单元' ? `单元 ${no}` : `阶段 ${no}`);
// 「停一下」点评只分两项：抓到了（含要点外的合理补充）/ 漏掉了（含想偏的）。老记录的 off / extra 并进来
const reviewLists = (rv) => ({ got: [...(rv.covered || []), ...(rv.extra || [])], miss: [...(rv.missing || []), ...(rv.off || [])] });
const quizScore = (s) => (s.quiz_result?.status === 'graded' ? s.quiz_result.score : null);
function chapterTag(h, s) {
  const sc = quizScore(s);
  if (sc !== null) return h('span.tag.ln-cs' + (s.quiz_result.passed ? '.ok' : '.err'), {}, `测试 ${sc} 分`);
  if (s.quiz_result?.status === 'grading') return h('span.tag.warn.ln-cs', {}, '批改中');
  if (s.chapter_status === 'generating') return h('span.tag.warn.ln-cs', {}, s.material_status === 'generating' ? '整理课件中' : '章节生成中');
  if (s.chapter_status === 'ready') return h('span.tag.gray.ln-cs', {}, '章节就绪');
  return null;
}
const BUSY = ['queued', 'running', 'generating', 'adapting'];
const DEF_KEY = 'ln-defaults';
let onAgentDone = null;
let current = null;
const watching = new Set();
const openSteps = new Set(); // 重绘时保持展开的步骤
const closedSteps = new Set(); // 用户手动收起的「当前步骤」

const loadDefaults = () => { try { return { hours: 5, background: '', ...JSON.parse(localStorage.getItem(DEF_KEY) || '{}') }; } catch { return { hours: 5, background: '' }; } };
const saveDefaults = (d) => { try { localStorage.setItem(DEF_KEY, JSON.stringify(d)); } catch { /* ignore */ } };

const page = {
  // 不用 ctx.refresh()：外壳的 route() 会把右侧对话切回板块总览，打断绑定 ref 的对话。
  // 自己的 refresh 先在离屏容器渲染再整体替换，保持滚动位置、无闪烁。
  async render(el, ctx0) {
    current = { el, ctx0 };
    const ctx = { ...ctx0, sub: location.hash.slice(1).split('/').slice(1), refresh: softRefresh };
    const { h } = ctx;
    document.getElementById('learn-css')?.remove();
    let style = document.getElementById('ln-css');
    if (!style) { style = h('style', { id: 'ln-css' }); document.head.append(style); }
    style.textContent = CSS;
    if (onAgentDone) document.removeEventListener('agent-done', onAgentDone);
    onAgentDone = (e) => { if (e.detail?.module === 'learn' && location.hash.startsWith('#learn')) softRefresh(); };
    document.addEventListener('agent-done', onAgentDone);

    const [view, id] = ctx.sub;
    if (view === 'plan' && id && ctx.sub[2] === 'step' && ctx.sub[3]) return renderChapter(el, ctx, +id, +ctx.sub[3]);
    if (view === 'plan' && id) return renderPlan(el, ctx, +id);
    if (view === 'item' && id) return renderItem(el, ctx, +id);
    return renderHome(el, ctx, view === 'plans');
  },
};
export default page;

async function softRefresh() {
  if (!current || !location.hash.startsWith('#learn')) return;
  const { el, ctx0 } = current;
  const tmp = document.createElement('div');
  await page.render(tmp, ctx0);
  current.el = el;
  el.replaceChildren(...tmp.childNodes);
}

const tag = (h, status) => h('span.tag' + (STATUS_TAG[status] ? '.' + STATUS_TAG[status] : ''), {}, STATUS_TXT[status] || status);
const BADGE = { github: 'REPO', paper: 'PAPER', article: '文章', video: '视频' };
const badge = (h, kind) => h('span.ln-badge.' + (BADGE[kind] ? kind : 'paper'), {}, BADGE[kind] || 'PAPER');

function watchJob(ctx, jobId, status) {
  if (!jobId || watching.has(jobId) || !BUSY.includes(status)) return;
  watching.add(jobId);
  ctx.api.waitJob(jobId, null, 4000).catch(() => {}).finally(() => { watching.delete(jobId); softRefresh(); });
}

function stars(h, ui, value, onset, { readonly = false } = {}) {
  const box = h('span.ln-stars' + (readonly ? '.ro' : ''), { title: readonly ? `评分 ${value}/5` : '理解度（再点一次取消）' });
  const draw = (v) => box.replaceChildren(...[1, 2, 3, 4, 5].map((i) => {
    if (readonly) { const ic = ui.icon('star'); ic.style.color = i <= v ? 'var(--accent)' : 'var(--line-2)'; if (i <= v) ic.style.fill = 'var(--accent)'; return ic; }
    return h('button' + (i <= v ? '.on' : ''), { onclick: (e) => { e.stopPropagation(); const nv = i === v ? 0 : i; draw(nv); onset(nv); } }, ui.icon('star'));
  }));
  draw(value);
  return box;
}

// ---------- 意图识别 ----------
function detectIntent(text) {
  const t = text.trim();
  if (!t) return null;
  let m;
  if ((m = t.match(/arxiv\.org\/(?:abs|pdf|html)\/(\d{4}\.\d{4,5})/i)) || (m = t.match(/^(?:arxiv:)?(\d{4}\.\d{4,5})(v\d+)?$/i))) {
    return { kind: 'paper', label: `论文 arXiv ${m[1]}`, url: `https://arxiv.org/abs/${m[1]}` };
  }
  if ((m = t.match(/(10\.\d{4,9}\/\S+)/)) && !/\s/.test(t)) return { kind: 'paper', label: `论文 DOI ${m[1]}`, url: t };
  if ((m = t.match(/github\.com\/([\w.-]+)\/([\w.-]+)/i))) {
    const repo = `${m[1]}/${m[2].replace(/\.git$/, '')}`;
    return { kind: 'github', label: `仓库 ${repo}`, url: `https://github.com/${repo}` };
  }
  if ((m = t.match(/https?:\/\/(?:www\.|m\.)?(?:youtube\.com\/(?:watch|shorts\/|live\/)|youtu\.be\/|bilibili\.com\/video\/|b23\.tv\/)\S+/i))) {
    return { kind: 'video', label: '视频 ' + m[0].replace(/^https?:\/\/(www\.)?/, '').slice(0, 40), url: m[0] };
  }
  if ((m = t.match(/https?:\/\/[^\s，。、）)]+/i))) {
    const link = m[0];
    const u = new URL(link);
    const pdf = /\.pdf($|\?)/i.test(link);
    const name = pdf ? u.pathname.split('/').pop() : u.hostname.replace(/^www\./, '') + (u.pathname.length > 1 ? u.pathname.slice(0, 30) : '');
    return { kind: u.hostname.includes('openreview') || pdf ? 'paper' : '', label: (pdf ? '论文 PDF ' : '链接 ') + name, url: link };
  }
  if (/^[\w.-]+\/[\w.-]+$/.test(t) && !/^\d/.test(t)) return { kind: 'github', label: `仓库 ${t}`, url: t };
  if (/^[~/]\S*$/.test(t)) return { kind: 'github', label: `本地目录 ${t}`, url: t };
  return null;
}

// ---------- 总览：智能输入框 + 计划 + 条目 ----------
async function renderHome(el, ctx, scrollToPlans) {
  const { api, h, toast, ui, ask } = ctx;
  const [items, plans] = await Promise.all([api.get('/api/learn/items'), api.get('/api/learn/plans')]);
  items.forEach((it) => watchJob(ctx, it.job_id, it.status));
  plans.forEach((p) => watchJob(ctx, p.job_id, p.status));
  plans.sort((a, b) => (a.status === 'archived') - (b.status === 'archived'));
  const latestPlan = [...plans].filter((p) => !['failed', 'archived'].includes(p.status)).sort((a, b) => (b.updated_at || '').localeCompare(a.updated_at || ''))[0];

  const defs = loadDefaults();
  const opt = { background: defs.background, goal: '', hours: defs.hours, focus: '', kind: '', depth: 'quick' };
  let intent = 'plan';
  let target = null; // 识别出的链接
  const optsRow = h('div.ln-opts');
  const editRow = h('div');
  let editing = null;

  const box = ui.composer({
    placeholder: '粘贴 arXiv / PDF / DOI / GitHub / YouTube 链接深读，或输入想系统学习的主题…', autofocus: true,
    modes: [{ id: 'auto', label: '自动' }, { id: 'item', label: '深读', placeholder: 'arXiv / PDF / DOI 链接，或 GitHub owner/repo' },
      { id: 'plan', label: '学习计划', placeholder: '想系统学习的主题，例如：世界模型、RL 用于 LLM 推理' },
      { id: 'course', label: '导入课程', placeholder: '课程官网链接，例如 https://cs336.stanford.edu/' },
      { id: 'ask', label: '问 Agent', placeholder: '问学习 Agent，例如：ReAct 和 Reflexion 的区别？' }],
    onSubmit: async (text) => {
      try {
        if (intent === 'ask') { ask(text); return; }
        if (intent === 'open') { location.hash = `#learn/item/${target.existing.id}`; return; }
        if (intent === 'item') {
          const url = target?.url || text;
          const it = await api.post('/api/learn/items', { url, kind: opt.kind || target?.kind || '', focus: opt.focus.trim(), depth: (opt.kind || target?.kind) === 'github' ? opt.depth : '' });
          toast('已开始后台深读，完成后自动刷新');
          opt.focus = ''; location.hash = `#learn/item/${it.id}`;
          return;
        }
        saveDefaults({ background: opt.background, hours: opt.hours });
        if (intent === 'course') {
          const c = await api.post('/api/learn/courses', { url: text, background: opt.background, goal: opt.goal, hours_per_week: +opt.hours || 5 });
          toast('Agent 正在读课表、整理成单元（几分钟）；每讲的课件和录像在开始学时再整理');
          location.hash = `#learn/plan/${c.id}`;
          return;
        }
        const p = await api.post('/api/learn/plans', { topic: text, background: opt.background, goal: opt.goal, hours_per_week: +opt.hours || 5 });
        toast('Agent 正在检索资料生成计划（几分钟）');
        location.hash = `#learn/plan/${p.id}`;
      } catch (e) { toast('提交失败：' + e.message, true); return false; }
    },
  });
  const ta = box.querySelector('textarea');

  const pill = (key, ic, label, value, placeholder) => h('button.ln-pill' + (value ? '' : '.empty') + (editing === key ? '.on' : ''), {
    title: placeholder, onclick: () => { editing = editing === key ? null : key; update(); if (editing) editRow.querySelector('input')?.focus(); },
  }, [ui.icon(ic), h('span', {}, value ? `${label}：${value}` : `+ ${label}`)]);

  const editor = () => {
    if (!editing) return null;
    const cfg = { background: ['我的背景', '已经会什么、不会什么（记住，下次默认）'], goal: ['学习目标', '学完要能做到什么'],
      focus: ['关注点', '例如：评测是否可靠 / 调度怎么实现'] }[editing];
    if (editing === 'hours') {
      return h('div.ln-edit', {}, [h('span.muted', {}, '每周投入'), ...[2, 3, 5, 8, 12].map((n) => h('button.sm' + (+opt.hours === n ? '.primary' : ''), {
        onclick: () => { opt.hours = n; saveDefaults({ background: opt.background, hours: n }); editing = null; update(); ta.focus(); } }, `${n}h`)),
      h('input', { type: 'number', min: 1, max: 60, value: opt.hours, style: { width: '80px', flex: 'none' },
        onkeydown: (e) => { if (e.key === 'Enter') { opt.hours = +e.target.value || 5; saveDefaults({ background: opt.background, hours: opt.hours }); editing = null; update(); ta.focus(); } } })]);
    }
    if (editing === 'kind') return null;
    const inp = h('input', { value: opt[editing], placeholder: cfg[1],
      onkeydown: (e) => {
        if (e.key === 'Enter' && !e.isComposing) { e.preventDefault(); commit(); }
        if (e.key === 'Escape') { editing = null; update(); ta.focus(); }
      } });
    const commit = () => { opt[editing] = inp.value.trim(); if (editing === 'background') saveDefaults({ background: opt.background, hours: opt.hours }); editing = null; update(); ta.focus(); };
    return h('div.ln-edit', {}, [h('span.muted', {}, cfg[0]), inp, h('button.sm.primary', { onclick: commit }, '好'), h('span.muted', {}, 'Enter 确认 · Esc 取消')]);
  };

  const update = () => {
    const text = ta.value.trim();
    const mode = box.mode;
    const det = detectIntent(text);
    target = det;
    if (mode === 'ask') intent = 'ask';
    else if (mode === 'item') intent = 'item';
    else if (mode === 'plan') intent = 'plan';
    else if (mode === 'course') intent = 'course';
    else intent = det ? 'item' : /[?？]$/.test(text) ? 'ask' : 'plan';
    const existing = intent === 'item' && det && items.find((it) => it.url.trim() === det.url.trim());
    if (existing) { intent = 'open'; target = { ...det, existing }; }
    let hint;
    if (!text) hint = mode === 'ask' ? 'Enter 发给学习 Agent' : mode === 'item' ? '粘贴链接，Enter 开始深读' : mode === 'plan' ? '输入主题，Enter 生成学习计划'
      : mode === 'course' ? '粘贴课程官网链接，Enter 导入成学习计划（按课程单元学，课件和录像整理成中文精讲）'
      : '链接 → 深读 · 主题 → 学习计划 · 问句 → 问 Agent';
    else if (intent === 'ask') hint = 'Enter → 问学习 Agent';
    else if (intent === 'course') hint = /^https?:\/\//.test(text) ? `Enter → 导入课程 ${text.slice(0, 50)} · 每周 ${opt.hours}h` : '填课程官网链接（http/https）';
    else if (intent === 'open') hint = `已深读过「${(existing.title || existing.url).slice(0, 30)}」，Enter 打开笔记`;
    else if (intent === 'item') hint = `Enter → 将${(opt.kind || det?.kind) === 'github' && opt.depth !== 'full' ? '速读' : '深读'}${det ? det.label : '：' + text.slice(0, 40)}`;
    else hint = `Enter → 将生成「${text.slice(0, 24)}${text.length > 24 ? '…' : ''}」学习计划 · 每周 ${opt.hours}h`;
    box.setHint(hint);
    if (editing === 'focus' && intent !== 'item') editing = null;
    if (['background', 'goal', 'hours'].includes(editing) && !['plan', 'course'].includes(intent)) editing = null;
    const kindTxt = { '': '自动识别', paper: '论文', github: 'GitHub 项目' };
    optsRow.replaceChildren(...(['plan', 'course'].includes(intent) ? [h('span.lbl', {}, '计划选项'),
      pill('background', 'user', '背景', opt.background, '我的背景'), pill('goal', 'bulb', '目标', opt.goal, '学习目标'),
      h('button.ln-pill' + (editing === 'hours' ? '.on' : ''), { onclick: () => { editing = editing === 'hours' ? null : 'hours'; update(); } }, [ui.icon('clock'), h('span', {}, `每周 ${opt.hours}h`)])]
      : intent === 'item' ? [h('span.lbl', {}, '深读选项'), pill('focus', 'search', '关注点', opt.focus, '关注点'),
        h('button.ln-pill', { title: '点击切换类型', onclick: () => { opt.kind = { '': 'paper', paper: 'github', github: '' }[opt.kind]; update(); } },
          [ui.icon('box'), h('span', {}, '类型：' + (opt.kind ? kindTxt[opt.kind] : det?.kind ? kindTxt[det.kind] + '（自动）' : '自动识别'))]),
        (opt.kind || det?.kind) === 'github' ? h('button.ln-pill' + (opt.depth === 'full' ? '.on' : ''), {
          title: '速读：几分钟出一份 markdown 笔记；完整教程：离线 HTML + 流程图 + 函数级讲解，通常 10–20 分钟',
          onclick: () => { opt.depth = opt.depth === 'full' ? 'quick' : 'full'; update(); } },
        [ui.icon('clock'), h('span', {}, opt.depth === 'full' ? '完整 HTML 教程（较慢）' : '速读笔记（几分钟）')]) : null]
        : []));
    editRow.replaceChildren(...[editor()].filter(Boolean));
  };
  ta.addEventListener('input', update);
  box.querySelector('.modes')?.addEventListener('click', () => setTimeout(update, 0));
  const setMode = (id) => { const i = ['auto', 'item', 'plan', 'course', 'ask'].indexOf(id); box.querySelectorAll('.modes button')[i]?.click(); };

  const plansSec = h('div', { id: 'ln-plans' });
  const totalSteps = plans.reduce((a, p) => a + p.progress.total, 0);
  const doneSteps = plans.reduce((a, p) => a + p.progress.done, 0);
  el.append(
    ui.pageHead('深度学习', `${items.length} 篇深读 · ${plans.length} 个学习计划 · 已完成 ${doneSteps}/${totalSteps} 步`),
    box, optsRow, editRow,
    ui.chips([
      { label: '继续上次的计划', icon: 'arrow', onClick: () => (latestPlan ? (location.hash = `#learn/plan/${latestPlan.id}`) : toast('还没有学习计划', true)) },
      { label: '深读一篇论文', icon: 'doc', onClick: () => { setMode('item'); box.focus(); } },
      { label: '给我一个学习计划', icon: 'plan', onClick: () => { setMode('plan'); box.focus(); } },
      { label: '导入名校课程', icon: 'learn', onClick: () => { setMode('course'); box.focus(); } },
      { label: '根据反馈调整', icon: 'refresh', onClick: () => (latestPlan ? (location.hash = `#learn/plan/${latestPlan.id}/adapt`) : toast('还没有学习计划', true)) },
    ]),
    habitsCard(ctx),
  );
  update();

  plansSec.append(ui.section('学习计划', plans.length ? `${plans.length} 个` : ''),
    plans.length ? h('div.grid', {}, plans.map((p) => planCard(p, ctx))) : ui.empty('还没有学习计划', '在上面输入一个主题，Enter 即可生成'));
  el.append(plansSec,
    ui.section('论文与项目深读', items.length ? `${items.length} 篇` : ''),
    items.length ? h('div.grid', {}, items.map((it) => itemCard(it, ctx))) : ui.empty('还没有深读条目', '粘贴一个 arXiv / GitHub 链接试试'));
  if (scrollToPlans) setTimeout(() => plansSec.scrollIntoView({ block: 'start' }), 0);
}

function planCard(p, ctx) {
  const { h, ui } = ctx;
  return h('div.card.ln-pcard.ln-card-click', { onclick: () => { location.hash = `#learn/plan/${p.id}`; } }, [
    h('div.row.between', {}, [h('span.card-label', {}, `每周 ${p.hours_per_week}h · 约 ${p.progress.hours}h`), tag(h, p.status)]),
    h('h3', {}, p.topic),
    h('div.row', {}, [h('div.grow', {}, ui.progress(p.progress.pct)), h('span.muted', {}, `${p.progress.done}/${p.progress.total} · ${p.progress.pct}%`)]),
    p.goal ? h('div.muted.clamp2', { style: { marginTop: '8px' } }, '目标：' + p.goal) : null,
    BUSY.includes(p.status) ? h('div.muted.dots', { style: { marginTop: '6px' } }, p.status === 'generating' ? (p.layout === 'course' ? 'Agent 正在读课表' : 'Agent 正在生成计划') : (p.layout === 'course' ? 'Agent 正在同步课表' : 'Agent 正在调整计划')) : null,
  ]);
}

function itemCard(it, ctx) {
  const { h, ui, openChat } = ctx;
  const busy = BUSY.includes(it.status);
  const go = () => { location.hash = `#learn/item/${it.id}`; };
  return h('div.card.ln-icard.ln-card-click', { onclick: go }, [
    h('div.row', {}, [badge(h, it.kind), it.status !== 'done' ? tag(h, it.status) : null, h('span.grow'),
      it.rating ? stars(h, ui, it.rating, null, { readonly: true }) : null, h('span.muted', {}, (it.created_at || '').slice(5, 10))]),
    h('h3.serif.clamp2', {}, it.title || it.url),
    busy ? h('div.tldr.dots', {}, '后台解析中，完成后自动刷新')
      : it.status === 'failed' ? h('div.tldr', { style: { color: 'var(--err)' } }, '深读失败，可打开后重新生成')
        : h('div.tldr.clamp3', {}, (it.summary || '').replace(/^TL;DR[:：]?\s*/i, '') || '（无 TL;DR）'),
    h('div.foot', {}, [
      it.output_path ? h('button.sm.outline', { onclick: (e) => { e.stopPropagation(); go(); } }, [ui.icon('doc'), '打开笔记']) : null,
      h('button.sm.ghost', { onclick: (e) => { e.stopPropagation(); openChat({ module: 'learn', ref: `learn:item:${it.id}`, title: '追问：' + (it.title || it.url).slice(0, 20) }); } }, [ui.icon('chat'), '追问']),
      h('span.grow'),
      it.focus ? h('span.muted.clamp2', { style: { maxWidth: '45%', fontSize: '12px' } }, '关注：' + it.focus) : null,
    ]),
  ]);
}

// ---------- 条目阅读 ----------
async function renderItem(el, ctx, iid) {
  const { api, h, md, toast, ui, openChat } = ctx;
  let it;
  try { it = await api.get(`/api/learn/items/${iid}`); } catch { el.append(back(h, ui), ui.empty('条目不存在')); return; }
  watchJob(ctx, it.job_id, it.status);
  const busy = BUSY.includes(it.status);
  const isHtml = /\.html?$/i.test(it.output_path || '');
  const fileName = (it.output_path || '').split('/').pop();
  const ref = `learn:item:${it.id}`;
  const chat = () => openChat({ module: 'learn', ref, title: '追问：' + (it.title || it.url).slice(0, 20) });

  el.append(back(h, ui), h('div.ln-head', {}, ui.pageHead(it.title || it.url, h('span', {}, [
    badge(h, it.kind), ' ', h('a', { href: it.url.startsWith('http') ? it.url : '#learn', target: '_blank', rel: 'noopener' }, it.url),
    ` · ${(it.created_at || '').slice(0, 10)}`, it.focus ? ` · 关注：${it.focus}` : '']), [
    it.status !== 'done' ? tag(h, it.status) : null,
    h('button.primary', { onclick: chat }, [ui.icon('chat'), '继续追问']),
  ])));
  el.append(h('div.row', { style: { marginBottom: '16px' } }, [
    isHtml ? h('button.outline', { onclick: () => window.open(`/api/learn/items/${it.id}/out/${encodeURIComponent(fileName)}`, '_blank') }, [ui.icon('doc'), '打开 HTML 教程']) : null,
    it.kind === 'github' && it.output_path ? h('button', { onclick: () => window.open(`/api/learn/items/${it.id}/out/summary.md`, '_blank') }, 'summary.md') : null,
    it.kind === 'github' && !busy && it.output_path && !isHtml ? h('button.outline', { title: '离线 HTML + 流程图 + 函数级讲解，通常 10–20 分钟',
      onclick: async () => { await api.post(`/api/learn/items/${it.id}/rerun`, { depth: 'full' }); toast('已开始生成完整教程'); softRefresh(); } }, [ui.icon('doc'), '生成完整 HTML 教程']) : null,
    h('span.grow'),
    it.job_id ? h('a.muted', { href: `/api/jobs/${it.job_id}`, target: '_blank' }, `job ${it.job_id}`) : null,
    h('button.ghost', { disabled: busy, onclick: async () => { if (!confirm('重新生成会覆盖产物，继续？')) return; await api.post(`/api/learn/items/${it.id}/rerun`, {}); toast('已重新开始深读'); softRefresh(); } }, [ui.icon('refresh'), '重新生成']),
    h('button.ghost', { onclick: async () => { if (!confirm('删除该条目？（产物文件保留）')) return; await api.del(`/api/learn/items/${it.id}`); location.hash = '#learn'; } }, [ui.icon('trash'), '删除']),
  ]));

  // GitHub 项目：深读笔记 / Deep Dive 两个标签（#learn/item/<id>/deepdive）
  const ddTab = it.kind === 'github' && ctx.sub[2] === 'deepdive';
  if (it.kind === 'github') {
    el.append(h('div.ln-tabs2', {}, [
      h('button' + (ddTab ? '' : '.on'), { onclick: () => { location.hash = `#learn/item/${it.id}`; } }, '深读笔记'),
      h('button' + (ddTab ? '.on' : ''), { title: '自己拉仓库、写测试、做实验的深度解读（点了才生成）', onclick: () => { location.hash = `#learn/item/${it.id}/deepdive`; } },
        ['Deep Dive', it.dd_status === 'running' ? h('span.muted.dots', { style: { marginLeft: '6px' } }, '生成中') : it.dd_status === 'done' ? ' ✓' : '']),
    ]));
  }
  if (ddTab) { el.append(await deepDivePane(ctx, it)); return; }

  const reader = h('div.ln-reader');
  el.append(reader);
  const lines = (it.summary || '').split('\n').map((s) => s.replace(/^[-*•]\s*/, '').trim()).filter(Boolean);
  const tldrBox = lines.length ? h('div.ln-tldr', {}, [h('span.card-label', {}, 'TL;DR'), h('ul', {}, lines.map((l) => h('li', {}, l)))]) : null;

  if (busy || it.status === 'failed' || !it.output_path) { if (tldrBox) reader.append(tldrBox); }
  if (busy) {
    reader.append(jobProgress(ctx, it.job_id, '后台深读中', (it.depth || 'quick') === 'quick' && it.kind === 'github' ? '速读 · 通常几分钟' : it.kind === 'github' ? '完整教程 · 通常 10–20 分钟' : it.kind === 'article' ? '文章深读 · 通常 2–5 分钟' : it.kind === 'video' ? '视频解读 · 通常 3–8 分钟（无字幕时本机转写更久）' : '论文深读 · 通常 2–5 分钟'));
  }
  else if (it.status === 'failed') reader.append(h('div.card', {}, ui.empty('深读失败', '点「重新生成」再试一次，或看 job 日志')));
  else if (it.output_path) {
    let text = null;
    if (!isHtml) text = await api.get(`/api/learn/items/${it.id}/file`).catch(() => null);
    else if (it.kind === 'github') text = await api.get(`/api/learn/items/${it.id}/out/summary.md`).catch(() => null);
    const hasNote = typeof text === 'string' && text.trim();
    if (tldrBox && !(hasNote && /TL;?DR/i.test(text.slice(0, 3000)))) reader.append(tldrBox);
    if (hasNote) {
      // 追问清单那一节不在正文里列，改成下面的逐题作答区
      const note = text.replace(/^---[\s\S]*?---\s*/, '').replace(QA_SECTION, '');
      reader.append(h('div.card', {}, annotate(ctx, localImgs(md(note), `/api/learn/items/${it.id}/out/`), { doc: `learn:item:${it.id}`, title: it.title || it.url, link: `#learn/item/${it.id}`, source: note })));
      const qa = await api.get(`/api/learn/items/${it.id}/qa`).catch(() => null);
      if (qa) reader.append(qaSection(ctx, it, qa));
    }
    else if (isHtml) reader.append(h('div.card', {}, ui.empty('这是一份 HTML 教程', '点上方「打开 HTML 教程」在新标签页阅读')));
  }

  // 追问与感想：条目对话里自己说过的话（进复盘和知识库），点开接着聊
  const rd = await api.get(`/api/learn/items/${it.id}/reads`).catch(() => null);
  if (rd) {
    const lines = rd.lines || [];
    const nThought = lines.filter((x) => x.kind === 'thought').length;
    reader.append(ui.section('追问与感想', [lines.length ? `感想 ${nThought} · 追问 ${lines.length - nThought}` : '',
      rd.task ? h('a.muted', { href: `#plan`, style: { marginLeft: '10px' } }, `${rd.task.date} 深读事项 · ${rd.task.status === 'done' ? '已完成' : '进行中'}`) : null]),
    h('div.card.ln-reads', {}, lines.length ? [
      ...lines.map((x) => h('div.ln-rd', {}, [h('span.muted', {}, x.at.slice(5, 16).replace('T', ' ')),
        h('span.tag' + (x.kind === 'thought' ? '.ok' : '.gray'), {}, x.kind === 'thought' ? '感想' : '追问'), h('span', {}, x.text)])),
      h('div.row', { style: { marginTop: '10px' } }, [h('span.grow'), h('button.sm', { onclick: chat }, [ui.icon('chat'), '接着聊'])]),
    ] : [h('div.row', {}, [h('span.muted', {}, '读的时候想到什么、哪里不认同，就在对话里写下来：会记成感想，进复盘和知识库。'), h('span.grow'),
      h('button.sm.primary', { onclick: chat }, [ui.icon('chat'), '写感想 / 追问'])])]));
  }

  // 我的笔记 / 评分
  let rating = it.rating || 0;
  const notes = h('textarea', { rows: 4, value: it.my_notes || '', placeholder: '我的笔记 / 认识（⌘+Enter 保存）' });
  const saved = h('span.ln-saved');
  const saveNotes = async () => { await api.patch(`/api/learn/items/${it.id}`, { my_notes: notes.value, rating }); saved.textContent = '已保存 ✓'; setTimeout(() => { saved.textContent = ''; }, 2000); };
  notes.addEventListener('keydown', (e) => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); saveNotes(); } });
  reader.append(ui.section('我的笔记'), h('div.card', {}, [notes,
    h('div.row', { style: { marginTop: '10px' } }, [h('span.muted', {}, '评分'), stars(h, ui, rating, (v) => { rating = v; saveNotes(); }), h('span.grow'), saved,
      h('button.primary', { onclick: saveNotes }, [ui.icon('check'), '保存'])])]));
}

// 后台任务实时进度：已用时 + Agent 最近几步（读了哪些文件、跑了什么命令）
function jobProgress(ctx, jobId, title, hint, n = 6) {
  const { api, h } = ctx;
  const steps = h('div.ln-steps');
  const head = h('div.serif', {}, title);
  const card = h('div.card', {}, [h('div.row', {}, [head, h('span.grow'), h('span.muted', {}, hint)]), steps]);
  let started = false;
  const tick = async () => {
    if (started && !steps.isConnected) return;
    started = steps.isConnected || started;
    const j = await api.get(`/api/jobs/${jobId}`).catch(() => null);
    if (!j) return;
    head.textContent = `${title} · ${j.status === 'queued' ? '排队中' : `已用 ${((j.elapsed_s ?? 0) / 60).toFixed(1)} 分钟`}`;
    const lines = (j.log || '').split('\n').filter(Boolean).slice(-n).map((l) => l.replace(/^\[tool\]\s*/, '').replace(/\/Users\/[^ ]*\/data\/learn\/[^/]+\//g, ''));
    steps.replaceChildren(...(lines.length ? lines.map((l) => h('div.ln-step', { title: l }, l)) : [h('div.muted', {}, h('span.dots', {}, '准备中'))]));
    if (['queued', 'running'].includes(j.status)) setTimeout(tick, 4000);
  };
  tick();
  return card;
}

// ---------- Deep Dive：按需生成，拉仓库、写测试、做实验，命令 / 原样输出 / 结论都在文档里 ----------
const VERDICT_TAG = { 证实: 'ok', 推翻: 'err', 意外: 'warn', 部分: 'gray' };

async function deepDivePane(ctx, it) {
  const { api, h, md, toast, ui } = ctx;
  const box = h('div.ln-reader');
  const d = await api.get(`/api/learn/items/${it.id}/deepdive`).catch(() => null);
  if (!d) { box.append(ui.empty('读取 Deep Dive 状态失败')); return box; }
  const start = async (e) => {
    if (d.ready && !confirm('重新生成 Deep Dive？当前版本会保留为历史版本。')) return;
    e.target.disabled = true;
    try { await api.post(`/api/learn/items/${it.id}/deepdive`); toast('已开始生成 Deep Dive'); } catch (err) { toast('启动失败：' + err.message, true); }
    softRefresh();
  };
  const intro = '比深读笔记深一层：Agent 在本机隔离目录里单独克隆仓库，自己写测试、做消融 / 边界实验并真的跑出结果，命令、原样输出和结论都写进文档；同步进知识库。通常 30–60 分钟。';
  const jobLink = d.job_id ? h('a.muted', { href: `/api/jobs/${d.job_id}`, target: '_blank' }, `job ${d.job_id}`) : null;
  if (d.status === 'running') {
    watchJob(ctx, d.job_id, 'running');
    box.append(jobProgress(ctx, d.job_id, 'Deep Dive 生成中', '拉仓库 → 读代码 → 写测试 / 做实验 → 写文档 · 通常 30–60 分钟', 10));
    return box;
  }
  if (d.status === 'failed') {
    box.append(h('div.card', {}, [h('div.serif', { style: { color: 'var(--err)' } }, 'Deep Dive 生成失败'),
      h('div', { style: { margin: '8px 0' } }, d.error || '未知原因'),
      h('div.row', {}, [jobLink, h('span.muted', {}, d.ready ? '（下面是这次写出的部分内容）' : ''), h('span.grow'), h('button.primary', { onclick: start }, [ui.icon('refresh'), '重试'])])]));
  }
  if (!d.ready) {
    if (d.status !== 'failed') box.append(h('div.card', {}, [h('div.serif', {}, '还没有 Deep Dive'), h('p.muted', {}, intro),
      h('div.row', {}, [h('span.grow'), h('button.primary', { onclick: start }, [ui.icon('doc'), '生成 Deep Dive'])])]));
    return box;
  }
  const docBox = h('div.card');
  const show = async (version = '') => {
    const text = await api.get(`/api/learn/items/${it.id}/deepdive/file${version ? `?version=${encodeURIComponent(version)}` : ''}`).catch(() => null);
    if (typeof text !== 'string') { docBox.replaceChildren(ui.empty('读取文档失败')); return; }
    const body = text.replace(/^---[\s\S]*?---\s*/, '');
    docBox.replaceChildren(annotate(ctx, localImgs(md(body), `/api/learn/items/${it.id}/out/deepdive/`),
      { doc: `learn:item:${it.id}:deepdive`, title: d.title || `${it.title || it.url} · Deep Dive`, link: `#learn/item/${it.id}/deepdive`, source: body }));
  };
  const versions = d.versions.length ? h('select', { onchange: (e) => show(e.target.value) },
    [h('option', { value: '' }, '当前版本'), ...d.versions.map((v) => h('option', { value: v }, v.replace(/^deepdive\.|\.md$/g, '')))]) : null;
  box.append(h('div.row', { style: { marginBottom: '12px' } }, [
    h('span.muted', {}, `${d.experiments.length} 个实验 · ${(d.at || '').slice(0, 16).replace('T', ' ')}`), versions, h('span.grow'), jobLink,
    h('button.ghost', { onclick: start }, [ui.icon('refresh'), '重新生成']),
  ]));
  if (d.experiments.length) {
    box.append(h('div.card.ln-dd-exps', {}, d.experiments.map((x) => h('div.ln-rd', { title: x.cmd || '' }, [
      h('b', {}, x.id || ''), h('span.tag.' + (VERDICT_TAG[x.verdict] || 'gray'), {}, x.verdict || '—'), h('span.muted', {}, x.type || ''),
      h('span', {}, x.finding || x.title || ''),
      h('a.muted', { href: `/api/learn/items/${it.id}/out/deepdive/${String(x.out).split('/').map(encodeURIComponent).join('/')}`, target: '_blank' }, '原样输出'),
    ]))));
  }
  box.append(docBox);
  await show();
  return box;
}

// ---------- 追问清单：逐题作答，提交后 Agent 对照笔记 / 原文 / 源码点评 ----------
// 笔记里的相对路径图片（figs/fig1.png）指向条目输出目录；点图在新标签页看原尺寸
function localImgs(el, base) {
  for (const img of el.querySelectorAll('img')) {
    const src = img.getAttribute('src') || '';
    if (src && !/^([a-z]+:|\/|#)/i.test(src)) img.src = base + src.replace(/^\.\//, '').split('/').map(encodeURIComponent).join('/');
    img.loading = 'lazy';
    img.onclick = () => window.open(img.src, '_blank', 'noopener');
  }
  return el;
}

const QA_SECTION = /^#{2,4}\s*追问清单[^\n]*\n[\s\S]*?(?=^#{1,4}\s|(?![\s\S]))/m;

// 练习题（qa.json）：选择题点一下当场判对错并给解析，开放题 1–2 道交给 Agent 点评；老笔记没有练习题时可以让 Agent 出一套
function qaSection(ctx, it, qa) {
  const { api, h, toast, ui } = ctx;
  const box = h('div');
  const reload = async () => {
    const r = await api.get(`/api/learn/items/${it.id}/qa`).catch(() => null);
    if (r && box.isConnected) box.replaceWith(qaSection(ctx, it, r));
  };
  const gen = async (e) => {
    if (e?.target) e.target.disabled = true;
    try { await api.post(`/api/learn/items/${it.id}/qa/generate`); toast('Agent 正在出题，约 1 分钟'); }
    catch (err) { toast('出题失败：' + err.message.replace(/^"|"$/g, ''), true); }
    reload();
  };
  if (qa.gen?.status === 'generating') api.waitJob(qa.gen.job_id, null, 3000).catch(() => {}).finally(reload);
  const quiz = qa.mode === 'quiz';
  const choices = qa.items.filter((x) => x.type === 'choice');
  const shorts = qa.items.filter((x) => x.type !== 'choice');
  const head = h('span');
  const list = h('div.ln-qa');
  const count = () => {
    const ok = list.querySelectorAll(':scope > .qa.right').length, answered = list.querySelectorAll(':scope > .qa.locked').length;
    const reviewed = list.querySelectorAll(':scope > .qa.done:not(.locked)').length;
    head.textContent = quiz ? [choices.length ? `选择题 ${answered ? `已答 ${answered}/${choices.length} · 答对 ${ok}` : `${choices.length} 道`}` : '', shorts.length ? `开放题已点评 ${reviewed}/${shorts.length}` : ''].filter(Boolean).join(' · ')
      : (qa.items.length ? `已点评 ${list.querySelectorAll('.qa.done').length}/${qa.items.length}` : '');
  };
  const genBox = () => {
    if (qa.gen?.status === 'generating') return h('div.gen', {}, h('span.muted.dots', {}, 'Agent 正在读笔记出选择题（约 1 分钟），出好自动显示'));
    return h('div.gen', {}, [qa.gen?.status === 'failed' ? h('span', { style: { color: 'var(--err)' } }, '上次出题失败。') : null,
      h('span', {}, '这篇笔记还没有练习题：让 Agent 出 4 道选择题 + 1 道开放题，点选就能检验读懂没有。'),
      h('button.sm.primary', { onclick: gen }, '出选择题')]);
  };
  if (quiz) {
    list.append(...qa.items.map((x) => (x.type === 'choice' ? choiceCard(ctx, it, x, count, reload) : qaCard(ctx, it, x, count))));
  } else if (it.status === 'done') {
    list.append(genBox());
    if (qa.items.length) {
      const legacy = qa.items.map((x) => qaCard(ctx, it, x, count));
      list.append(h('details.legacy', { open: qa.items.some((x) => x.answer) }, [h('summary.muted', {}, `笔记里原来的开放题 ${qa.items.length} 道（可选，逐题写作答请 Agent 点评）`), ...legacy]));
    }
  }
  if (qa.earlier?.length) {
    list.append(h('details.old', {}, [h('summary.muted', {}, `以前的作答 ${qa.earlier.length} 条（换题前的作答）`),
      ...qa.earlier.map((x) => qaCard(ctx, it, x, null, true))]));
  }
  count();
  const hint = quiz ? '选择题点一下当场判对错并给解析；开放题写下判断和理由，Agent 会对照笔记、原文和源码点评。作答都会进学习记录和复盘。'
    : '';
  box.append(...[ui.section(quiz ? '练习题' : '追问清单', [head, quiz && qa.gen?.status !== 'generating' && it.status === 'done'
    ? h('button.sm.ghost', { title: '让 Agent 重新出一套；已答的进「以前的作答」', onclick: (e) => { if (confirm('重新出一套题？已答的会放进「以前的作答」')) gen(e); } }, [ui.icon('refresh'), '换一套']) : null]),
  hint ? h('div.muted', { style: { fontSize: '13px', margin: '-4px 0 10px' } }, hint) : null,
  quiz && qa.gen?.status === 'generating' ? h('div.ln-qa', { style: { marginBottom: '10px' } }, genBox()) : null, list].filter(Boolean));
  return box;
}

function choiceCard(ctx, it, x, onChange, reload) {
  const { api, h, md, toast } = ctx;
  let c = x;
  const card = h('div.qa');
  const pick = async (k) => {
    if ('choice' in c) return;
    try { c = { ...x, ...(await api.post(`/api/learn/items/${it.id}/qa/${x.n}`, { q: x.q, choice: k })) }; }
    catch (e) { toast('提交失败：' + e.message.replace(/^"|"$/g, ''), true); if (/已更新/.test(e.message)) reload(); return; }
    draw();
  };
  const draw = () => {
    const done = 'choice' in c;
    card.className = 'qa' + (done ? ' locked done ' + (c.correct ? 'right' : 'wrong') : '');
    const kids = [h('div.qh', {}, [h('span.no', {}, `Q${x.n}`), h('div.qt', {}, md(x.q)), x.dim ? h('span.dim', {}, x.dim) : null,
      done ? h('span.tag' + (c.correct ? '.ok' : '.err'), {}, c.correct ? '答对' : '答错') : null])];
    x.options.forEach((o, k) => {
      const cls = done ? (k === c.right ? '.right' : k === c.choice ? '.wrong' : '') : '';
      kids.push(h('div.opt' + cls, { role: 'button', tabindex: done ? -1 : 0, onclick: () => pick(k), onkeydown: (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); pick(k); } } },
        [h('span.k', {}, 'ABCDEFG'[k]), h('span', {}, o)]));
    });
    if (done && c.explain) kids.push(h('div.rv', {}, [h('b', {}, '解析：'), md(c.explain), x.section ? h('div.muted', { style: { fontSize: '12px', marginTop: '4px' } }, `对应笔记：${x.section}`) : null]));
    card.replaceChildren(...kids.filter(Boolean));
    onChange?.();
  };
  draw();
  return card;
}

function qaCard(ctx, it, x, onChange, readonly = false) {
  const { api, h, md, toast, openChat } = ctx;
  let c = x;
  const draftKey = `ln-qa-${it.id}-${x.n}`;
  let draft = c.answer || '';
  if (!draft) { try { draft = localStorage.getItem(draftKey) || ''; } catch { /* ignore */ } }
  const ta = h('textarea', { rows: 3, value: draft, placeholder: '我的判断 + 理由（不确定也可以写「不确定，我猜……」）。⌘+Enter 提交点评' });
  ta.addEventListener('input', () => { try { localStorage.setItem(draftKey, ta.value); } catch { /* ignore */ } });
  ta.addEventListener('keydown', (e) => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); submit(true); } });
  const card = h('div.qa');
  let editing = !c.answer;
  const submit = async (review) => {
    if (!ta.value.trim()) { toast('先写下你的作答', true); ta.focus(); return; }
    try { c = { n: x.n, ...(await api.post(`/api/learn/items/${it.id}/qa/${x.n}`, { q: x.q, answer: ta.value, review })) }; }
    catch (e) { toast('保存失败：' + e.message, true); return; }
    try { localStorage.removeItem(draftKey); } catch { /* ignore */ }
    editing = false;
    draw();
    if (c.status === 'reviewing') poll();
  };
  const poll = async () => {
    await api.waitJob(c.job_id, null, 3000).catch(() => {});
    const r = await api.get(`/api/learn/items/${it.id}/qa`).catch(() => null);
    const fresh = r?.items?.find((y) => y.n === x.n && y.q === x.q);
    if (fresh) { c = fresh; draw(); }
  };
  const lst = (cls, label, arr) => (arr?.length ? h('div.row2.' + cls, {}, [h('b', {}, label), h('div', {}, arr.length > 1 ? h('ul', { style: { margin: 0, paddingLeft: '16px' } }, arr.map((y) => h('li', {}, y))) : arr[0])]) : null);
  const statusTag = () => (c.status === 'reviewing' ? h('span.tag.warn', {}, '点评中')
    : c.review ? h('span.tag' + (c.review.score >= 0.7 ? '.ok' : '.gray'), {}, `${Math.round(c.review.score * 100)}%`)
      : c.status === 'failed' ? h('span.tag.err', {}, '点评失败') : c.answer ? h('span.tag.gray', {}, '已作答') : null);
  const ask = () => openChat({ module: 'learn', ref: `learn:item:${it.id}`, title: '追问：' + (it.title || it.url).slice(0, 20) });
  const draw = () => {
    card.classList.toggle('done', !!c.review);
    const kids = [h('div.qh', {}, [h('span.no', {}, `Q${x.n}`), h('div.qt', {}, md(x.q)), statusTag()])];
    if (editing && !readonly) {
      kids.push(ta, h('div.acts', {}, [
        h('button.sm.primary', { onclick: () => submit(true) }, '提交，请 Agent 点评'),
        h('button.sm', { onclick: () => submit(false) }, '只保存'),
        c.answer ? h('button.sm.ghost', { onclick: () => { editing = false; ta.value = c.answer; draw(); } }, '取消') : null,
      ]));
    } else {
      kids.push(h('div.mine', {}, c.answer));
      const rv = c.review;
      if (c.status === 'reviewing') kids.push(h('div.rv.muted.dots', {}, 'Agent 正在对照笔记和原文点评（约半分钟到两分钟）'));
      else if (rv) {
        kids.push(h('div.rv', {}, [h('span.sc', {}, `${Math.round((rv.score || 0) * 100)}%`),
          lst('ok', '抓到了', rv.covered), lst('miss', '漏掉了', rv.missing),
          rv.better ? h('div.better', {}, [h('b', {}, '参考答案：'), md(rv.better)]) : null]));
      } else if (c.status === 'failed') kids.push(h('div.rv', { style: { color: 'var(--err)' } }, '点评失败，可以再提交一次'));
      if (!readonly) {
        kids.push(h('div.acts', {}, [
          h('button.sm', { onclick: () => { editing = true; ta.value = c.answer; draw(); ta.focus(); } }, '改写作答'),
          !rv && c.status !== 'reviewing' ? h('button.sm.outline', { onclick: () => { ta.value = c.answer; submit(true); } }, '请 Agent 点评') : null,
          rv ? h('button.sm.ghost', { onclick: ask }, '接着追问') : null,
        ]));
      }
    }
    card.replaceChildren(...kids.filter(Boolean));
    onChange?.();
  };
  draw();
  if (c.status === 'reviewing') poll();
  return card;
}

const back = (h, ui, href = '#learn', label = '深度学习') => h('a.ln-back', { href }, [ui.icon('arrow'), label]);

// ---------- 计划详情 ----------
async function renderPlan(el, ctx, pid) {
  const { api, h, md, toast, ui, openChat } = ctx;
  let p;
  try { p = await api.get(`/api/learn/plans/${pid}`); } catch { el.append(back(h, ui), ui.empty('计划不存在')); return; }
  const ref = `learn:plan:${pid}`;
  const chatTitle = '计划：' + p.topic.slice(0, 16);
  watchJob(ctx, p.job_id, p.status);
  const busy = ['generating', 'adapting'].includes(p.status);

  // 阶段状态
  const stageInfo = Object.entries(p.stages).map(([no, name]) => {
    const ss = p.steps.filter((s) => s.stage === +no);
    const done = ss.filter((s) => s.status === 'done').length;
    const closed = ss.filter((s) => s.status === 'done' || s.status === 'skipped').length;
    return { no: +no, name, ss, done, isDone: ss.length > 0 && closed === ss.length, hours: ss.reduce((a, s) => a + (+s.est_hours || 0), 0) };
  });
  const cur = stageInfo.find((s) => s.ss.length && !s.isDone);
  const curStep = p.steps.find((s) => s.status === 'doing') || p.steps.find((s) => s.status === 'todo');

  el.append(back(h, ui), h('div.ln-head', {}, ui.pageHead(p.topic,
    [p.background ? `背景：${p.background}` : '', p.goal ? `目标：${p.goal}` : ''].filter(Boolean).join(' · '), [
      tag(h, p.status),
      h('button.primary', { onclick: () => openChat({ module: 'learn', ref, title: chatTitle }) }, [ui.icon('chat'), '讨论 / 改计划']),
    ])));
  if (p.status === 'archived' && p.rounds_plan) {
    el.append(h('div.card.ln-banner', {}, [h('div.t', {}, [h('b', {}, '这份计划已精简成三轮'), h('div.muted', {}, '进度、测试和学习记录都还在这里，可以随时回看')]),
      h('button.primary', { onclick: () => { location.hash = `#learn/plan/${p.rounds_plan}`; } }, ['去三轮计划', ui.icon('arrow')])]));
  } else if (p.from_plan) {
    el.append(h('div.card.ln-banner', {}, [h('div.t', {}, [h('b', {}, '由老计划精简成三轮'),
      h('div.muted', {}, `跳过了「${p.from_topic || p.topic}」里已经学会的，补上了测试和反馈里的薄弱处`)]),
      h('a', { href: `#learn/plan/${p.from_plan}` }, '查看老计划')]));
  } else if (p.unit === '阶段' && p.steps.length && !p.rounds_plan) {
    el.append(h('div.card.ln-banner', {}, [h('div.t', {}, [h('b', {}, '这是老的六阶段计划，比较长'),
      h('div.muted', {}, '可以精简成三轮由浅入深：最新全貌 + 主干 → 会判断 → 跟前沿、项目和产品实践，主线约 15–20 小时；已学的跳过、薄弱处补上，老计划保留')]),
      h('button.outline', { disabled: busy, onclick: async (e) => {
        e.target.disabled = true;
        try { const n = await api.post(`/api/learn/plans/${pid}/rounds`); toast('Agent 正在生成三轮计划（几分钟），生成好后老计划自动归档'); location.hash = `#learn/plan/${n.id}`; }
        catch (err) { toast('没成功：' + err.message, true); e.target.disabled = false; }
      } }, [ui.icon('refresh'), '精简成三轮'])]));
  } else if (p.unit === '阶段' && p.rounds_plan) {
    el.append(h('div.card.ln-banner', {}, [h('div.t', {}, h('b', {}, '三轮精简版正在生成')),
      h('a', { href: `#learn/plan/${p.rounds_plan}` }, '去看看')]));
  }
  el.append(h('div.ln-meta', { style: { marginTop: '-4px', marginBottom: '16px' } }, [
    h('span.pct', {}, `${p.progress.pct}%`), ui.progress(p.progress.pct),
    h('span', {}, `${p.progress.done}/${p.progress.total} 步`), h('span', {}, [ui.icon('clock'), ` 约 ${p.progress.hours}h`]),
    h('span', {}, `每周 ${p.hours_per_week}h`),
    p.progress.hours && p.hours_per_week ? h('span', {}, `≈ ${Math.ceil(p.progress.hours / p.hours_per_week)} 周`) : null,
  ]));

  // 阶段时间线 + 调整
  const adaptNote = h('input', { placeholder: p.unit === '单元' ? '怎么调整？如「单元 3 的作业太难，想先补 PyTorch」· Enter 提交' : p.unit === '轮' ? '怎么调整？如「第 2 轮太难」「想多做产品实践」· Enter 提交' : '怎么调整？如「第 4 阶段太难」「想多做实践」· Enter 提交', title: '会结合每步的反馈与理解度一起调整',
    onkeydown: (e) => { if (e.key === 'Enter' && !e.isComposing) { e.preventDefault(); doAdapt(); } } });
  const doAdapt = async () => {
    if (busy || !p.steps.length) return;
    await api.post(`/api/learn/plans/${pid}/adapt`, { note: adaptNote.value.trim() });
    toast('Agent 正在根据反馈调整计划'); softRefresh();
  };
  el.append(h('div.card.ln-stagecard', {}, [
    h('h3', {}, busy ? (p.status === 'generating' ? '计划生成中…' : '计划调整中…') : cur ? `当前${p.unit || '阶段'} · ${cur.name}` : p.steps.length ? `全部${p.unit || '阶段'}已完成` : '暂无步骤'),
    h('div.ln-stages', { style: { gridTemplateColumns: `repeat(${stageInfo.length}, minmax(0, 1fr))` } }, stageInfo.map((s, i) => {
      const prevDone = i > 0 && stageInfo[i - 1].isDone;
      const cls = [s.isDone ? 'done' : '', cur && s.no === cur.no ? 'cur' : '', (s.isDone || (cur && s.no === cur.no)) && (i === 0 || prevDone) ? 'reached' : '', s.ss.length ? '' : 'empty'].filter(Boolean).join('.');
      return h('div.ln-stage' + (cls ? '.' + cls : ''), { onclick: () => s.ss.length && document.getElementById(`ln-stage-${s.no}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' }) }, [
        h('div.ln-dot', {}, s.isDone ? ui.icon('check') : null),
        h('div.k', {}, `${stageNo(p, s.no)}${s.ss.length ? ` · ${s.done}/${s.ss.length}` : ''}`),
        h('div.n', {}, s.name),
      ]);
    })),
    h('div.ln-adapt', {}, [adaptNote,
      h('button.primary', { disabled: busy || !p.steps.length, onclick: doAdapt }, [ui.icon('refresh'), '根据反馈调整']),
      p.layout === 'course' ? h('button.ghost', { disabled: busy, title: '重新看一遍课程官网，只追加新发布的讲次和作业，已有步骤和学习记录不动', onclick: async () => {
        await api.post(`/api/learn/plans/${pid}/sync_course`); toast('Agent 正在同步课表'); softRefresh();
      } }, [ui.icon('refresh'), '同步课表']) : h('button.ghost', { disabled: busy, onclick: async () => {
        if (!confirm('重新生成会清空现有步骤与反馈，继续？')) return; await api.post(`/api/learn/plans/${pid}/regenerate`); softRefresh();
      } }, '重新生成'),
      h('button.ghost', { onclick: async () => { if (!confirm('删除计划？')) return; await api.del(`/api/learn/plans/${pid}`); location.hash = '#learn'; } }, [ui.icon('trash'), '删除']),
    ]),
    busy ? h('div.muted.dots', { style: { marginTop: '8px' } }, `job ${p.job_id} 运行中，完成后自动刷新`) : null,
  ]));
  if (ctx.sub[2] === 'adapt') setTimeout(() => { adaptNote.focus(); history.replaceState(null, '', `#learn/plan/${pid}`); }, 30);
  if (curStep && !busy) {
    const no = p.steps.filter((s) => s.status !== 'skipped').indexOf(curStep) + 1;
    el.append(h('div.card.ln-continue', {}, [
      h('div.t', {}, [h('div.k', {}, `跟着学 · 第 ${no} 章 · ${stageNo(p, curStep.stage)} ${p.stages[curStep.stage]}`), h('div.n', {}, curStep.title),
        curStep.goal ? h('div.muted', { style: { fontSize: '13px' } }, '学完能：' + curStep.goal) : null]),
      chapterTag(h, curStep),
      h('button.primary', { onclick: () => { location.hash = chapterHref(pid, curStep.id); } }, [curStep.chapter_status === 'ready' ? '继续学习' : '开始学习', ui.icon('arrow')]),
    ]));
  }

  el.append(growthView(ctx, pid));
  if (p.overview_md) {
    el.append(h('details.card.flat', { open: !p.steps.length }, [h('summary', {}, '计划总览 / 调整记录'),
      annotate(ctx, md(p.overview_md), { doc: `learn:plan:${pid}`, title: `${p.topic} · 计划总览`, link: `#learn/plan/${pid}`, source: p.overview_md })]));
  }
  for (const s of stageInfo) {
    if (!s.ss.length) continue;
    el.append(h('div', { id: `ln-stage-${s.no}`, style: { scrollMarginTop: '16px' } }, ui.section(`${stageNo(p, s.no)} · ${s.name}`, `${s.done}/${s.ss.length} · ${s.hours}h`)));
    if (p.stage_goals?.[s.no]) el.append(h('div.ln-purpose', {}, [h('b', {}, `本${p.unit || '阶段'}目的：`), p.stage_goals[s.no]]));
    s.ss.forEach((st) => el.append(stepView(st, p, ctx, curStep && st.id === curStep.id)));
  }
}

// 资源里的 GitHub 仓库：读过就打开笔记，没读过就开一个速读
async function quickRead(ctx, url) {
  const { api, toast } = ctx;
  const norm = (u) => (u || '').replace(/\/+$/, '').replace(/\.git$/, '').toLowerCase();
  try {
    const items = await api.get('/api/learn/items');
    const hit = items.find((it) => norm(it.url) === norm(url));
    const it = hit || await api.post('/api/learn/items', { url, kind: 'github', depth: 'quick' });
    if (!hit) toast('已开始速读这个仓库，几分钟出笔记');
    location.hash = `#learn/item/${it.id}`;
  } catch (e) { toast('速读没开始：' + e.message, true); }
}

function stepView(s, p, ctx, isCur) {
  const { api, h, md, toast, ui } = ctx;
  const save = async (patch, msg) => { await api.patch(`/api/learn/steps/${s.id}`, patch); if (msg) toast(msg); softRefresh(); };
  const saved = h('span.ln-saved');
  const flash = (t = '已保存 ✓') => { saved.textContent = t; setTimeout(() => { saved.textContent = ''; }, 2000); };
  const quiet = async (patch) => { await api.patch(`/api/learn/steps/${s.id}`, patch); flash(); };

  const fb = h('input', { value: s.feedback || '', placeholder: '一句话反馈：哪里没懂、太难/太简单、资源好不好…  Enter 保存',
    onkeydown: (e) => { if (e.key === 'Enter' && !e.isComposing) { e.preventDefault(); quiet({ feedback: fb.value }); } } });
  const notes = h('textarea', { rows: 2, value: s.notes || '', placeholder: '学习笔记 / 检查题的回答（离开输入框自动保存）',
    onchange: () => quiet({ notes: notes.value }) });
  const status = h('select', { title: '状态', onclick: (e) => e.stopPropagation(), onchange: () => save({ status: status.value }) },
    Object.entries(STEP_TXT).map(([k, v]) => h('option', { value: k, selected: s.status === k }, v)));
  const expanded = openSteps.has(s.id) || ((isCur || s.status === 'doing') && !closedSteps.has(s.id));
  const body = h('div.ln-st-body', { style: { display: expanded ? '' : 'none' } }, [
    s.goal ? h('div.ln-goal', {}, [h('b', {}, '能力目标'), s.goal]) : null,
    s.description ? annotate(ctx, md(s.description), { doc: `learn:step:${s.id}`, title: `${p.topic} · ${s.title}`, link: `#learn/plan/${p.id}`, source: s.description, compact: true }) : null,
    s.resources.length ? h('div.ln-st-sub', {}, '资源') : null,
    ...s.resources.map((r) => h('div.ln-res', {}, [ui.icon(r.type === 'code' || r.type === 'repo' || /github/.test(r.url || '') ? 'box' : r.type === 'product' ? 'spark' : r.type === 'video' ? 'bolt' : 'link'),
      h('div.why', {}, [r.url ? h('a', { href: r.url, target: '_blank', rel: 'noopener' }, r.title || r.url) : h('b', {}, r.title || ''),
        r.why ? h('span', {}, ' — ' + r.why) : null]),
      r.type ? h('span.tag.gray', {}, r.type) : null,
      r.verified === false ? h('span.tag.warn', {}, '未核验') : null,
      /github\.com\/[\w.-]+\/[\w.-]+/.test(r.url || '') ? h('button.sm.ghost', { title: '用深读板块速读这个仓库（几分钟出一份架构笔记）', onclick: () => quickRead(ctx, r.url) }, '速读') : null])),
    s.questions.length ? h('div.ln-st-sub', {}, '检查题 · 能答上来再打勾') : null,
    ...s.questions.map((q, i) => h('div.ln-q', {}, [h('span.no', {}, i + 1), h('span', {}, q)])),
    h('div.ln-fb', {}, [h('span.muted', {}, '理解度'), stars(h, ui, s.understanding, (v) => quiet({ understanding: v })), fb, saved]),
    h('div', { style: { marginTop: '8px' } }, notes),
    h('div.ln-st-actions', {}, [
      h('button.primary', { onclick: () => { location.hash = chapterHref(p.id, s.id); } }, [ui.icon('learn'),
        s.chapter_status === 'ready' ? (quizScore(s) !== null ? '回看本章' : '继续学习本章') : '开始学习本章（教程 + 测试）']),
      h('button.outline', { onclick: async () => { await api.post(`/api/learn/steps/${s.id}/today`, {}); toast('已加入今日计划'); softRefresh(); } }, [ui.icon('plan'), '加入今日计划']),
      h('button', { onclick: () => ctx.openChat({ module: 'learn', ref: `learn:plan:${p.id}`, title: '计划：' + p.topic.slice(0, 16),
        prefill: `关于步骤「${s.title}」（step_id=${s.id}）：` }) }, [ui.icon('chat'), '继续追问']),
      h('span.grow'),
      h('button.ghost.sm', { onclick: async () => { if (!confirm('删除这一步？')) return; await api.del(`/api/learn/steps/${s.id}`); softRefresh(); } }, [ui.icon('trash'), '删除']),
    ]),
  ]);
  const toggle = () => {
    const show = body.style.display === 'none'; body.style.display = show ? '' : 'none';
    if (show) { openSteps.add(s.id); closedSteps.delete(s.id); } else { openSteps.delete(s.id); closedSteps.add(s.id); }
    card.classList.toggle('open', show);
  };
  const done = s.status === 'done';
  const card = h('div.card.ln-step.' + s.status + (s.origin ? '.extra' : '') + (isCur ? '.cur' : '') + (expanded ? '.open' : ''), {}, [
    h('div.ln-st-head', {}, [
      h('button.ln-check' + (done ? '.on' : ''), { title: done ? '标记为未完成' : '标记完成', onclick: () => save({ status: done ? 'doing' : 'done' }, done ? '' : '完成一步 ✓') }, ui.icon('check')),
      h('span.ln-st-title', { onclick: toggle }, s.title),
      isCur ? h('span.tag', {}, '当前') : null,
      s.origin ? h('span.tag.ln-xtag.ln-cs', { title: s.request || '' }, '按需' + (EXTRA_TXT[s.origin] || '')) : null,
      s.step_kind === 'assignment' ? h('span.tag.ln-cs', { title: '课程作业：章节写成实践指导 + 自检清单，Agent 只点评、不代写' }, '作业') : null,
      chapterTag(h, s),
      s.understanding && !expanded ? stars(h, ui, s.understanding, null, { readonly: true }) : null,
      h('span.muted', {}, `${s.est_hours}h`), status,
      h('button.icon.tg', { title: '展开 / 收起', onclick: toggle }, ui.icon('arrow')),
    ]),
    body,
  ]);
  return card;
}

// ---------- 跟着学：一章教程 + 章末测试 ----------
async function renderChapter(el, ctx, pid, sid) {
  const { api, h, md, toast, ui, openChat } = ctx;
  let p;
  try { p = await api.get(`/api/learn/plans/${pid}`); } catch { el.append(back(h, ui), ui.empty('计划不存在')); return; }
  let s = p.steps.find((x) => x.id === sid);
  if (!s) { el.append(back(h, ui, `#learn/plan/${pid}`, p.topic), ui.empty('这一章不存在')); return; }
  // 第一次进入：没有章节就开始生成；已有章节就让后台准备下一章
  if (!openedChapters.has(sid)) {
    openedChapters.add(sid);
    if (!['generating'].includes(s.chapter_status)) s = await api.post(`/api/learn/steps/${sid}/open`, {}).catch(() => s);
  }
  const seq = p.steps.filter((x) => x.status !== 'skipped' || x.id === sid);
  const idx = seq.findIndex((x) => x.id === sid);
  const prev = seq[idx - 1], next = seq[idx + 1];
  const chat = (prefill) => openChat({ module: 'learn', ref: `learn:step:${sid}`, title: '本章：' + s.title.slice(0, 16), prefill });
  const parent = s.parent_id ? p.steps.find((x) => x.id === s.parent_id) : null;

  el.append(back(h, ui, `#learn/plan/${pid}`, p.topic));
  el.append(h('div.ln-head.ln-chap-head', {}, ui.pageHead(s.title,
    h('span.k', {}, `第 ${idx + 1}/${seq.length} 章 · ` + (s.origin ? `按需${EXTRA_TXT[s.origin] || ''}${parent ? ` · 源自「${parent.title}」` : ''}` : `${stageNo(p, s.stage)} ${p.stages[s.stage]}`) + ` · 约 ${s.est_hours}h`), [
      chapterTag(h, s),
      h('button.primary', { onclick: () => chat() }, [ui.icon('chat'), '追问本章']),
    ])));
  if (s.origin) {
    const [ask, quoted] = (s.request || s.title).split('\n划线原文：');
    el.append(h('div.ln-purpose', {}, [h('b', {}, s.origin === 'confused' ? '你没懂的地方：' : '你想深入的方向：'), ask,
      quoted ? h('span.muted', {}, `${ask ? ' · ' : ''}划线「${quoted}」`) : null,
      parent ? h('a', { href: chapterHref(pid, parent.id), style: { marginLeft: '10px' } }, '回到原章 ↩') : null]));
  } else el.append(h('div.ln-purpose', {}, [h('b', {}, `本${p.unit || '阶段'}目的：`), p.stage_goals?.[s.stage] || '']));
  if (s.goal) el.append(h('div.ln-goal', {}, [h('b', {}, s.origin ? '本节能力目标' : '本章能力目标'), s.goal]));
  const extra = s.chapter_status === 'ready' ? extraPanel(ctx, p, s) : null;

  const toolbar = h('div.row', { style: { margin: '6px 0 16px' } }, [
    extra ? h('button.outline', { title: '对某个子方向感兴趣，或哪里没懂：在本章后加一节针对性讲解 + 小测试', onclick: () => extra.open() }, [ui.icon('plus'), '按需加一节']) : null,
    h('span.grow'),
    s.chapter_job ? h('a.muted', { href: `/api/jobs/${s.chapter_job}`, target: '_blank' }, `job ${s.chapter_job}`) : null,
    h('button.ghost', { disabled: s.chapter_status === 'generating', onclick: async () => {
      const note = prompt('重新生成本章。有什么要求？（如「多讲推导」「换更新的资料」，可留空）', '');
      if (note === null) return;
      await api.post(`/api/learn/steps/${sid}/open`, { force: true, note }); toast('正在重新生成本章'); softRefresh();
    } }, [ui.icon('refresh'), '重新生成本章']),
  ]);
  el.append(toolbar);

  if (s.chapter_status === 'generating' || !s.chapter_status) {
    watchJob(ctx, s.chapter_job, 'generating');
    const steps = h('div.ln-steps');
    const head = h('div.serif', {}, 'Agent 正在读资料、写本章教程和测试');
    el.append(h('div.card', {}, [h('div.row', {}, [head, h('span.grow'), h('span.muted', {}, s.origin ? '通常 3–8 分钟，完成后自动刷新' : '通常 5–12 分钟，完成后自动刷新')]), steps,
      s.description ? h('div', { style: { marginTop: '14px' } }, [h('div.ln-st-sub', {}, '本步说明（来自计划）'), md(s.description)]) : null]));
    const tick = async () => {
      if (!steps.isConnected || !s.chapter_job) return;
      const j = await api.get(`/api/jobs/${s.chapter_job}`).catch(() => null);
      if (!j) return;
      const mins = ((j.elapsed_s ?? 0) / 60).toFixed(1);
      head.textContent = j.status === 'queued' ? '排队中（前面还有任务）' : `Agent 正在写本章 · 已用 ${mins} 分钟`;
      const lines = (j.log || '').split('\n').filter(Boolean).slice(-6).map((l) => l.replace(/^\[tool\]\s*/, '').replace(/\/Users\/[^ ]*\/data\/learn\/plans\/[^ ]*\//g, ''));
      steps.replaceChildren(...(lines.length ? lines.map((l) => h('div.ln-step', { title: l }, l)) : [h('div.muted', {}, h('span.dots', {}, '准备中'))]));
      if (['queued', 'running'].includes(j.status)) setTimeout(tick, 4000);
    };
    tick();
    el.append(chapterNav(h, ui, pid, prev, next));
    return;
  }
  if (s.chapter_status === 'failed') {
    el.append(h('div.card', {}, [ui.empty('本章生成失败', '可以看 job 日志，或点下面重试'),
      h('div.row', { style: { justifyContent: 'center' } }, h('button.primary', { onclick: async () => { await api.post(`/api/learn/steps/${sid}/open`, {}); softRefresh(); } }, [ui.icon('refresh'), '重试']))]));
    el.append(chapterNav(h, ui, pid, prev, next));
    return;
  }

  // 正文 + 目录
  const body = md(s.chapter_md);
  enhance(ctx, body, s, { p, extra });
  const heads = [...body.querySelectorAll('h2')];
  heads.forEach((hd, i) => { hd.id = `ln-h-${i}`; hd.style.scrollMarginTop = '16px'; });
  const TOC_KEY = 'ln-toc-off';
  const setToc = (off) => { chap.classList.toggle('toc-off', off); try { localStorage.setItem(TOC_KEY, off ? '1' : ''); } catch { /* ignore */ } };
  const toc = h('nav.ln-toc', {}, [h('button.toc-open', { title: '展开本章目录', onclick: () => setToc(false) }, '本章目录 »'),
    h('div.k', {}, [h('span', {}, '本章目录'), h('button', { title: '收起目录，正文更宽', onclick: () => setToc(true) }, '« 收起')]),
    ...heads.map((hd) => h('a', { href: 'javascript:void 0', onclick: () => hd.scrollIntoView({ behavior: 'smooth', block: 'start' }) }, hd.textContent)),
    s.quiz.length || s.cards?.length ? h('a.quiz', { href: 'javascript:void 0', onclick: () => document.getElementById('ln-quiz')?.scrollIntoView({ behavior: 'smooth', block: 'start' }) }, s.cards?.length ? `要点 ${s.cards.length} · 测试 ${s.quiz.length} 题` : `章末测试 · ${s.quiz.length} 题`) : null]);
  const main = h('div', { style: { minWidth: 0 } }, [
    h('div.card.ln-reader-card', { style: { padding: '22px 26px' } },
      annotate(ctx, body, { doc: `learn:chapter:${sid}`, title: `${p.topic} · ${s.title}`, link: chapterHref(pid, sid), source: s.chapter_md,
        actions: [{ icon: 'bulb', label: '没懂', onPick: (q) => extra.open('confused', q) }, { icon: 'search', label: '展开讲', onPick: (q) => extra.open('interest', q) }] })),
    extra.el,
  ]);
  const chap = h('div.ln-chap', {}, [toc, main]);
  try { if (localStorage.getItem(TOC_KEY)) chap.classList.add('toc-off'); } catch { /* ignore */ }
  el.append(chap);
  // 目录高亮当前小节
  const links = [...toc.querySelectorAll('a:not(.quiz)')];  // 收起按钮不是 a，不影响高亮
  const spy = () => {
    if (!toc.isConnected) { window.removeEventListener('scroll', spy, true); return; }
    let on = -1;
    heads.forEach((hd, i) => { if (hd.getBoundingClientRect().top < 120) on = i; });
    links.forEach((a, i) => a.classList.toggle('on', i === on));
  };
  window.addEventListener('scroll', spy, true);

  const gotoSection = (name) => {
    const hd = heads.find((x) => name && (x.textContent.includes(name) || name.includes(x.textContent.trim())));
    if (hd) hd.scrollIntoView({ behavior: 'smooth', block: 'start' });
    else toast('没找到对应小节，往上翻翻');
  };
  const qv = quizView(ctx, p, s, { gotoSection, chat, next, extra });
  if (s.cards?.length) {
    const deck = keyPoints(ctx, s);
    const key = `ln-chap-tab-${sid}`;
    let tab = (() => { try { return localStorage.getItem(key); } catch { return null; } })() || (s.quiz_result?.status ? 'quiz' : 'cards');
    const bCards = h('button.sm', { onclick: () => show('cards') }, `本章要点 · ${s.cards.length} 条`);
    const bQuiz = h('button.sm', { onclick: () => show('quiz') }, `章末测试 · ${s.quiz.length} 题`);
    const show = (t2) => { tab = t2; try { localStorage.setItem(key, t2); } catch { /* ignore */ }
      deck.style.display = t2 === 'cards' ? '' : 'none'; qv.style.display = t2 === 'quiz' ? '' : 'none';
      bCards.classList.toggle('on', t2 === 'cards'); bQuiz.classList.toggle('on', t2 === 'quiz'); };
    main.append(h('div', { id: 'ln-quiz', style: { scrollMarginTop: '16px' } }, [ui.section('复习与测试', '先过一遍要点，再做测试'), h('div.ln-tabs2', {}, [bCards, bQuiz]), deck, qv]));
    qv.removeAttribute('id');
    qv.querySelector('.section-title')?.remove();
    show(tab);
  } else main.append(qv);

  main.append(applyCard(ctx, s));
  main.append(historyView(ctx, s));
  // 我的笔记 / 理解度 / 反馈（与计划页同一份数据）
  const saved = h('span.ln-saved');
  const quiet = async (patch) => { await api.patch(`/api/learn/steps/${sid}`, patch); saved.textContent = '已保存 ✓'; setTimeout(() => { saved.textContent = ''; }, 2000); };
  const fb = h('input', { value: s.feedback || '', placeholder: '一句话反馈：哪里没懂、太难/太简单、讲得好不好…  Enter 保存',
    onkeydown: (e) => { if (e.key === 'Enter' && !e.isComposing) { e.preventDefault(); quiet({ feedback: fb.value }); } } });
  const notes = h('textarea', { rows: 3, value: s.notes || '', placeholder: '我的笔记（离开输入框自动保存）', onchange: () => quiet({ notes: notes.value }) });
  main.append(ui.section('我的笔记与反馈'), h('div.card', {}, [
    h('div.ln-fb', { style: { marginTop: 0 } }, [h('span.muted', {}, '理解度'), stars(h, ui, s.understanding, (v) => quiet({ understanding: v })), fb, saved]),
    h('div', { style: { marginTop: '8px' } }, notes)]));
  main.append(chapterNav(h, ui, pid, prev, next));
}

// 按需加一节：选「没懂 / 感兴趣」，写下要点（或带上划线原文），在本章后插一节讲解 + 小测试，跳过去看生成进度
function extraPanel(ctx, p, s) {
  const { api, h, toast, ui } = ctx;
  let kind = 'confused', quote = '';
  const modes = h('div.ln-tabs2');
  const quoteBox = h('div');
  const inp = h('input', { onkeydown: (e) => { if (e.key === 'Enter' && !e.isComposing) { e.preventDefault(); create(kind, inp.value); } } });
  const btn = h('button.primary', { onclick: () => create(kind, inp.value) }, [ui.icon('spark'), '生成这一节']);
  const draw = () => {
    modes.replaceChildren(...[['confused', '没懂，换个讲法讲透'], ['interest', '感兴趣，往深处讲']].map(([k, l]) =>
      h('button.sm' + (kind === k ? '.on' : ''), { onclick: () => { kind = k; draw(); inp.focus(); } }, l)));
    inp.placeholder = kind === 'confused' ? '哪里没懂？例如「为什么上线要看 pass^k 而不是 pass@k」· Enter 生成'
      : '对哪个子方向感兴趣？例如「多智能体系统怎么评测」· Enter 生成';
    quoteBox.replaceChildren(...(quote ? [h('div.ln-xquote', {}, [h('span.clamp2', {}, '划线：' + quote),
      h('button.icon.sm', { title: '去掉划线', onclick: () => { quote = ''; draw(); } }, ui.icon('x'))])] : []));
  };
  const create = async (k, text, q = quote) => {
    const request = (text || '').trim();
    if (!request && !q) { toast(k === 'confused' ? '先写下哪里没懂，或在正文里划线' : '先写下感兴趣的子方向', true); inp.focus(); return; }
    btn.disabled = true;
    try {
      const x = await api.post(`/api/learn/steps/${s.id}/extra`, { kind: k, request, quote: q });
      toast(x.chapter_status === 'ready' ? '这一节之前加过，直接打开' : `已在本章后加一节${EXTRA_TXT[k]}，Agent 正在写`);
      location.hash = chapterHref(p.id, x.id);
    } catch (e) { toast('没加上：' + e.message, true); btn.disabled = false; }
  };
  const root = s.parent_id || s.id;
  const kids = p.steps.filter((x) => x.parent_id === root);
  const el = h('div.card.ln-extra', {}, [
    h('div.hd', {}, [h('b', {}, '按需加一节'), h('span.muted', {}, '在本章后插入一节针对你这个点的讲解 + 2–3 道小测试，通常 3–8 分钟；正文里划线后点「没懂 / 展开讲」也行')]),
    modes, quoteBox, h('div.row', {}, [inp, btn]),
    kids.length ? h('div.ln-xkids', {}, [h('span.muted', {}, '本章已加：'), ...kids.map((x) => h('a' + (x.id === s.id ? '.on' : ''), { href: chapterHref(p.id, x.id), title: x.request || '' },
      [x.title, quizScore(x) !== null ? h('span.muted', {}, `${quizScore(x)} 分`) : x.chapter_status === 'generating' ? h('span.muted', {}, '生成中') : null]))]) : null,
  ]);
  draw();
  return {
    el, create,
    open(k = kind, q, text) {
      kind = k; if (q !== undefined) quote = q.slice(0, 1500); if (text !== undefined) inp.value = text; draw();
      el.scrollIntoView({ behavior: 'smooth', block: 'center' }); setTimeout(() => inp.focus({ preventScroll: true }), 350);
    },
  };
}

function chapterNav(h, ui, pid, prev, next) {
  return h('div.ln-chap-nav', {}, [
    prev ? h('button', { onclick: () => { location.hash = chapterHref(pid, prev.id); } }, [h('span', {}, '← 上一章：' + prev.title)]) : h('span'),
    next ? h('button.outline', { onclick: () => { location.hash = chapterHref(pid, next.id); } }, [h('span', {}, '下一章：' + next.title + ' →')])
      : h('button.outline', { onclick: () => { location.hash = `#learn/plan/${pid}`; } }, '回到计划'),
  ]);
}

function quizView(ctx, p, s, { gotoSection, chat, next, extra }) {
  const { api, h, toast, ui } = ctx;
  const wrap = h('div', { id: 'ln-quiz', style: { scrollMarginTop: '16px' } });
  if (!s.quiz.length) {
    wrap.append(ui.section('章末测试'), h('div.card', {}, ui.empty('本章没有生成测试', '可以「重新生成本章」，或在追问里让 Agent 出几道题')));
    return wrap;
  }
  const r = s.quiz_result || {};
  const graded = r.status === 'graded';
  const grading = r.status === 'grading';
  const answers = graded || grading || r.status === 'failed' ? { ...(r.answers || {}) } : loadDraft(s.id);
  wrap.append(ui.section('章末测试', `${s.quiz.length} 题 · 评估理解 / 判断 / 应用 · ${PASS_TXT}` + (r.attempt ? ` · 第 ${r.attempt + (graded || grading ? 0 : 1)} 次` : '')));

  if (graded) {
    const pass = r.passed;
    wrap.append(h('div.card.ln-score.' + (pass ? 'pass' : 'fail'), {}, [
      h('div.big', {}, String(r.score)),
      h('div.t', {}, [
        h('div', {}, h('b', {}, pass ? '通过，本章已标记完成' : '还没过关：建议回看薄弱处再重做')),
        r.summary ? h('div', { style: { marginTop: '4px' } }, r.summary) : null,
        r.dims && Object.keys(r.dims).length ? h('div.ln-dims', {}, Object.entries(r.dims).map(([d, v]) => h('div.ln-dimrow', {}, [
          h('b', {}, d), h('div.bar', {}, h('i', { style: { width: v + '%' } })), h('span.v', {}, v + '%'),
          r.assessment?.[d] ? h('span.t', {}, r.assessment[d]) : null]))) : null,
        r.weak_points?.length ? h('ul', {}, r.weak_points.map((w) => h('li', {}, w))) : null,
        r.advice ? h('div.muted', { style: { marginTop: '4px' } }, '建议：' + r.advice) : null,
      ]),
    ]));
  } else if (grading) {
    watchJob(ctx, r.job_id, 'running');
    wrap.append(h('div.card', {}, h('div.muted.dots', {}, '选择题已判，简答题 Agent 批改中（通常 1–2 分钟），完成后自动刷新')));
  } else if (r.status === 'failed') {
    wrap.append(h('div.card', { style: { color: 'var(--err)' } }, '简答题批改失败，可以直接再交一次'));
  } else if (r.last_score !== undefined && r.last_score !== null) {
    wrap.append(h('div.muted', { style: { margin: '-4px 0 10px' } }, `上次 ${r.last_score} 分`));
  }

  const locked = graded || grading;
  s.quiz.forEach((q, i) => {
    const it = (r.items || {})[q.id];
    const scoreCls = it ? (it.score >= 1 ? 'full' : it.score > 0 ? 'part' : 'zero') : '';
    const card = h('div.card.ln-qz', {}, [q.about && !/无直接相关/.test(q.about) ? h('div.ln-about', {}, ['学以致用 · ', q.about]) : null, h('div.qh', {}, [h('span.no', {}, i + 1), h('span.q', {}, q.q),
      q.dim ? h('span.tag.ln-dim', { title: { 理解: '对这个方向的理解', 判断: '判断力', 应用: '用到自己的论文 / 项目上' }[q.dim] || '' }, q.dim) : null,
      graded && it ? h('span.sc.' + scoreCls, {}, q.type === 'choice' ? (it.score ? '✓' : '✗') : `${Math.round(it.score * 100)}%`) : null])]);
    if (q.type === 'choice') {
      q.options.forEach((o, k) => {
        const cls = graded ? (k === q.answer ? '.right' : +answers[q.id] === k ? '.wrong' : '') : '';
        const inp = h('input', { type: 'radio', name: `q-${s.id}-${q.id}`, checked: answers[q.id] !== undefined && answers[q.id] !== null && +answers[q.id] === k, disabled: locked,
          onchange: () => { answers[q.id] = k; saveDraft(s.id, answers); } });
        card.append(h('label.opt' + cls, {}, [inp, h('span', {}, `${'ABCDEFG'[k]}. ${o}`)]));
      });
    } else {
      card.append(h('textarea', { rows: 3, value: answers[q.id] || '', disabled: locked, placeholder: '写下你的回答和理由（判断题先给结论，再给依据）',
        oninput: (e) => { answers[q.id] = e.target.value; saveDraft(s.id, answers); } }));
    }
    if (graded && it) {
      card.append(h('div.fbk', {}, [
        it.feedback ? h('div', {}, it.feedback) : null,
        q.type === 'short' && q.reference ? h('div.ref', {}, '参考要点：' + q.reference) : null,
        it.score < 1 && q.section ? h('a', { href: 'javascript:void 0', style: { fontSize: '13px' }, onclick: () => gotoSection(q.section) }, `回看：${q.section} ↑`) : null,
      ]));
    }
    wrap.append(card);
  });

  const actions = h('div.row', { style: { marginTop: '12px', flexWrap: 'wrap' } });
  if (!locked) {
    actions.append(h('button.primary', { onclick: async (e) => {
      const empty = s.quiz.filter((q) => answers[q.id] === undefined || answers[q.id] === null || String(answers[q.id]).trim() === '').length;
      if (empty && !confirm(`还有 ${empty} 题没答，未答按 0 分，交卷？`)) return;
      e.target.disabled = true;
      try { await api.post(`/api/learn/steps/${s.id}/quiz`, { answers }); saveDraft(s.id, {}); toast('已交卷'); softRefresh(); }
      catch (err) { toast('交卷失败：' + err.message, true); e.target.disabled = false; }
    } }, [ui.icon('check'), '交卷']), h('span.muted', {}, '选择题当场判分，简答题由 Agent 批改；答案自动暂存在本机'));
  } else if (graded) {
    if (next) actions.append(h('button.primary', { onclick: () => { location.hash = chapterHref(p.id, next.id); } }, ['下一章', ui.icon('arrow')]));
    actions.append(
      r.weak_points?.length || !r.passed ? h('button.outline', { title: '针对薄弱处在本章后加一节补课：换个讲法讲透 + 2–3 道小测试', onclick: () => extra.create('confused',
        r.weak_points?.length ? `测试薄弱处：${r.weak_points.join('；')}` : `测试 ${r.score} 分，没过关的地方`) }, [ui.icon('plus'), '生成补课小节']) : null,
      h('button', { onclick: () => chat(`我刚做完本章测试（${r.score} 分），薄弱处：${(r.weak_points || []).join('；') || '见批改'}。请针对这些地方换个角度讲透，再出 2 道类似的题考我。`) }, [ui.icon('chat'), '针对薄弱处再讲一遍']),
      h('button.ghost', { onclick: async () => { await api.post(`/api/learn/steps/${s.id}/quiz/reset`); softRefresh(); } }, [ui.icon('refresh'), '重做测试']),
      !r.passed ? h('button.ghost', { onclick: async () => {
        await api.post(`/api/learn/plans/${p.id}/adapt`, { note: `「${s.title}」测试 ${r.score} 分，薄弱：${(r.weak_points || []).join('；')}` });
        toast('Agent 正在根据测试结果调整计划');
      } }, '按测试结果调整计划') : null,
    );
  }
  wrap.append(actions);
  return wrap;
}
const PASS_TXT = '70 分及格，及格自动完成本章';

// 章节里的交互组件：Agent 写结构化 HTML（skills/learn/chapter.md），这里接上行为
function enhance(ctx, body, s, { p, extra } = {}) {
  const { h } = ctx;
  const sid = s.id;
  // 体系架构图：模块点一下跳到计划里讲它的那一章（data-step）或本章小节（data-section）；没人讲的模块可「展开讲」按需生成一节
  const seq = p ? p.steps.filter((x) => x.status !== 'skipped') : [];
  body.querySelectorAll('.dg-arch .dg-box').forEach((box) => {
    const name = box.querySelector(':scope > b')?.textContent.trim() || box.textContent.trim().slice(0, 30);
    const layer = box.closest('.dg-layer')?.querySelector(':scope > b')?.textContent.trim() || '贯穿各层';
    const st = box.dataset.step && seq.find((x) => String(x.id) === box.dataset.step && x.id !== sid);
    const hd = box.dataset.section && [...body.querySelectorAll('h2, h3')].find((x) => x.textContent.includes(box.dataset.section) || box.dataset.section.includes(x.textContent.trim()));
    let label, title, go;
    if (st) { label = `第 ${seq.indexOf(st) + 1} 章${st.status === 'done' ? ' ✓' : ''} →`; title = `跳到「${st.title}」`; go = () => { location.hash = chapterHref(p.id, st.id); }; }
    else if (hd) { label = '本章 ↓'; title = `跳到本章「${hd.textContent.trim()}」`; go = () => hd.scrollIntoView({ behavior: 'smooth', block: 'start' }); }
    else if (extra) { label = '展开讲 +'; title = '计划里没有专门讲它：按需加一节讲讲'; go = () => extra.open('interest', undefined, `体系架构图里「${layer}」层的「${name}」：它解决什么、代表工作、和相邻模块的关系`); }
    if (!go) return;
    box.append(h('a.dg-go' + (st || hd ? '' : '.more'), { href: 'javascript:void 0', title, onclick: (e) => { e.stopPropagation(); go(); } }, label));
    if (!box.querySelector('.dg-more') && (st || hd)) { box.classList.add('dg-link'); box.title = title; box.addEventListener('click', go); }
  });
  // 树：一行放下所有分支（最多 5 列，再多换行）
  body.querySelectorAll('.dg-branches').forEach((b) => { const n = b.children.length; b.style.setProperty('--n', n <= 5 ? n : 3); });
  // 点开看细节
  body.querySelectorAll('.dg-more').forEach((m) => {
    const host = m.parentElement;
    if (!host || host.closest('.dg-flow.steps')) return;
    host.classList.add('has-more');
    host.addEventListener('click', (e) => { if (window.getSelection()?.toString()) return; e.stopPropagation(); host.classList.toggle('open'); });
  });
  // 逐步播放
  body.querySelectorAll('.dg-flow.steps').forEach((flow) => {
    const nodes = [...flow.querySelectorAll(':scope > .dg-node')];
    if (!nodes.length) return;
    let i = -1;
    const txt = h('div.txt'), n = h('span.n');
    const prev = h('button.sm', { onclick: () => go(i - 1) }, '上一步');
    const nextB = h('button.sm.primary', { onclick: () => go(i + 1) }, '开始');
    const go = (k) => {
      i = Math.max(0, Math.min(nodes.length - 1, k));
      nodes.forEach((nd, j) => { nd.classList.toggle('on', j === i); nd.classList.toggle('seen', j < i); });
      const nd = nodes[i];
      const more = nd.querySelector('.dg-more');
      txt.replaceChildren(h('b', {}, nd.querySelector('b')?.textContent || ''), ' ', more ? h('span', { html: more.innerHTML }) : h('span.muted', {}, nd.querySelector('span')?.textContent || ''));
      n.textContent = `${i + 1}/${nodes.length}`;
      prev.disabled = i === 0; nextB.textContent = i === nodes.length - 1 ? '已到最后' : '下一步'; nextB.disabled = i === nodes.length - 1;
    };
    nodes.forEach((nd, j) => nd.addEventListener('click', () => go(j)));
    prev.disabled = true;
    txt.append(h('span.muted', {}, `${nodes.length} 步，点「开始」或点任一节点逐步看`));
    flow.after(h('div.dg-stepper', {}, [n, txt, prev, nextB]));
  });
  // 标签页
  body.querySelectorAll('.dg-tabs').forEach((box) => {
    const tabs = [...box.querySelectorAll(':scope > .dg-tab')];
    if (!tabs.length) return;
    const btns = tabs.map((tb, j) => h('button', { onclick: () => pick(j) }, tb.dataset.title || `${j + 1}`));
    const pick = (j) => { tabs.forEach((tb, k) => tb.classList.toggle('on', k === j)); btns.forEach((b, k) => b.classList.toggle('on', k === j)); };
    box.prepend(h('div.dg-tabbar', {}, btns));
    pick(0);
  });
  // 停一下：先写自己的判断，再和要点并排对照，可请 Agent 点评差异
  body.querySelectorAll('.dg-flash').forEach((c, i) => checkCard(ctx, c, s, i));
  // 交互小组件：沙箱 iframe（只允许脚本，不同源）
  body.querySelectorAll('.dg-widget[data-src]').forEach((w) => {
    const src = (w.dataset.src || '').replace(/^\/+/, '');
    if (!/^[\w./-]+\.html?$/.test(src) || src.includes('..')) return;
    const height = Math.max(160, Math.min(640, +w.dataset.height || 360));
    w.replaceChildren(
      h('div.wt', {}, ['可交互 · ', w.dataset.title || '动手试试', ' · ', h('a', { href: `/api/learn/steps/${sid}/out/${src}`, target: '_blank', rel: 'noopener' }, '新窗口打开')]),
      h('iframe', { src: `/api/learn/steps/${sid}/out/${src}`, sandbox: 'allow-scripts', loading: 'lazy', style: { height: height + 'px' }, title: w.dataset.title || 'widget' }));
  });
}

// 本章要点：直接总结，只读不答
function keyPoints(ctx, s) {
  const { h, md } = ctx;
  return h('div.ln-kp', {}, s.cards.map((c) => h('div.ln-kpc', {}, [
    h('div.hd', {}, [h('b', {}, c.front), c.tag ? h('span.tg', {}, c.tag) : null]), md(c.back)])));
}

// 停一下的固定作答格式：结论 + 为什么（机制）+ 一个例子 + 在我项目里怎么用（前三栏必填才能请 Agent 点评）
const CHECK_PARTS = [
  ['结论', '结论', '一句话下判断'],
  ['机制', '为什么', '背后的机制 / 因果：为什么成立，不是复述结论'],
  ['例子', '例子', '一个具体例子或数字（哪个产品 / 论文 / 场景）'],
  ['应用', '用到我的项目', '在我的项目里怎么用（暂时用不上就写为什么）'],
];
const CHECK_REQUIRED = ['结论', '机制', '例子'];

function checkCard(ctx, card, s, idx) {
  const { api, h, toast } = ctx;
  const qEl = card.querySelector('.dg-q'), aEl = card.querySelector('.dg-a');
  if (!qEl || !aEl) return;
  const q = qEl.textContent.trim(), points = aEl.innerText.trim(), pointsHtml = aEl.innerHTML;
  let c = (s.checks || {})[idx] || null;
  const draftKey = `ln-chk-${s.id}-${idx}`;
  // 老作答没有分栏：整段放进「结论」，改写时再拆
  const initial = () => c?.parts || (c?.answer ? { 结论: c.answer } : null);
  let draft = initial();
  if (!draft) { try { draft = JSON.parse(localStorage.getItem(draftKey) || 'null'); } catch { draft = null; } }
  const fields = Object.fromEntries(CHECK_PARTS.map(([k, , ph]) => [k, h('textarea', { rows: k === '结论' && (draft?.[k] || '').length < 30 ? 1 : 2, placeholder: ph, value: draft?.[k] || '' })]));
  const parts = () => Object.fromEntries(CHECK_PARTS.map(([k]) => [k, fields[k].value.trim()]).filter(([, v]) => v));
  const missing = () => CHECK_REQUIRED.filter((k) => !fields[k].value.trim());
  Object.values(fields).forEach((ta) => ta.addEventListener('input', () => { try { localStorage.setItem(draftKey, JSON.stringify(parts())); } catch { /* ignore */ } }));
  const form = h('div.dg-parts', {}, CHECK_PARTS.map(([k, label]) => h('label', {}, [h('span', {}, label + (CHECK_REQUIRED.includes(k) ? '' : '（选填）')), fields[k]])));
  const box = h('div');
  const save = async (review) => {
    try { c = await api.post(`/api/learn/steps/${s.id}/checks/${idx}`, { q, points, parts: parts(), review }); }
    catch (e) { toast('保存失败：' + e.message, true); return; }
    try { localStorage.removeItem(draftKey); } catch { /* ignore */ }
    draw();
    if (c.status === 'reviewing') poll();
  };
  const poll = async () => {
    await ctx.api.waitJob(c.job_id, null, 3000).catch(() => {});
    const st = await api.get(`/api/learn/steps/${s.id}`).catch(() => null);
    if (st?.checks?.[idx]) { c = st.checks[idx]; draw(); }
  };
  const askReview = () => {
    const miss = missing();
    if (miss.length) { toast('按格式补上：' + miss.map((k) => CHECK_PARTS.find((x) => x[0] === k)[1]).join('、'), true); fields[miss[0]].focus(); return; }
    save(true);
  };
  const list = (cls, label, arr) => (arr?.length ? h('div.row2.' + cls, {}, [h('b', {}, label), h('div', {}, arr.length > 1 ? h('ul', { style: { margin: 0, paddingLeft: '16px' } }, arr.map((x) => h('li', {}, x))) : arr[0])]) : null);
  const partTags = (ps) => {
    const ks = CHECK_PARTS.filter(([k]) => ps?.[k] !== undefined);
    if (!ks.length) return null;
    const low = Math.min(...ks.map(([k]) => ps[k]));
    return h('div.dg-ptags', {}, ks.map(([k, label]) => h('span.tag' + (ps[k] >= 0.7 ? '.ok' : ps[k] === low && low < 0.7 ? '.warn' : '.gray'), {}, `${label} ${Math.round(ps[k] * 100)}%`)));
  };
  const draw = () => {
    const shown = c && ['viewed', 'answered', 'reviewing', 'reviewed', 'failed'].includes(c.status);
    card.classList.toggle('open', !!shown);
    const kids = [];
    if (!shown) {
      const plain = h('button.sm', { onclick: () => save(false) });
      const label = () => { plain.textContent = Object.keys(parts()).length ? '只对照要点' : '直接看要点'; };
      Object.values(fields).forEach((ta) => { ta.oninput = label; });
      label();
      kids.push(form, h('div.acts', {}, [
        h('button.sm.primary', { onclick: askReview }, '对照要点 + Agent 点评差异'),
        plain,
        h('span.muted', {}, '结论、为什么、例子都写上再对照，差距才看得见'),
      ]));
    } else {
      const mine = c.parts
        ? h('div', {}, CHECK_PARTS.filter(([k]) => c.parts[k]).map(([k, label]) => h('div', {}, [h('b', {}, label + '：'), c.parts[k]])))
        : (c.answer || h('span.muted', {}, '（没写，直接看了要点）'));
      kids.push(h('div.dg-cmp', {}, [
        h('div.mine', {}, [h('div.k', {}, '我的判断'), mine]),
        h('div.pts', {}, [h('div.k', {}, '要点'), h('div', { html: pointsHtml })]),
      ]));
      const rv = c.review;
      if (c.status === 'reviewing') kids.push(h('div.dg-rv.muted.dots', {}, 'Agent 正在对照点评（约半分钟）'));
      else if (rv) {
        kids.push(h('div.dg-rv', {}, [
          h('span.sc', {}, `${Math.round((rv.score || 0) * 100)}%`),
          partTags(rv.parts),
          list('ok', '抓到了', reviewLists(rv).got), list('miss', '漏掉了', reviewLists(rv).miss),
          rv.better ? h('div.better', {}, [h('b', {}, '高手会这样想：'), rv.better]) : null,
        ]));
      } else if (c.status === 'failed') kids.push(h('div.dg-rv', { style: { color: 'var(--err)' } }, '点评失败，可以重写后再试'));
      kids.push(h('div.acts', {}, [
        h('button.sm', { onclick: () => { c = { ...c, status: 'editing' }; draw(); fields[missing()[0] || '结论'].focus(); } }, c.answer ? '改写我的判断' : '补写我的判断'),
        c.answer && !rv && c.status !== 'reviewing' ? h('button.sm.outline', { onclick: askReview }, '请 Agent 点评差异') : null,
      ]));
    }
    box.replaceChildren(...kids.filter(Boolean));
  };
  card.replaceChildren(h('div.lbl', {}, '停一下 · 结论 → 为什么 → 例子 → 用到我的项目'), qEl, aEl, box);
  draw();
  if (c?.status === 'reviewing') poll();
}

// 学习记录：本章历次测试、停一下作答与点评、理解度变化（只追加，重新生成章节也保留）
function historyView(ctx, s) {
  const { api, h, ui } = ctx;
  const box = h('details.card.flat.ln-hist', {}, [h('summary', {}, '学习记录（历次测试、停一下作答与点评）')]);
  box.addEventListener('toggle', async () => {
    if (!box.open || box.dataset.loaded) return;
    box.dataset.loaded = '1';
    const evs = (await api.get(`/api/learn/steps/${s.id}/events`).catch(() => [])).filter((e) => e.kind !== 'check');
    if (!evs.length) { box.append(h('div.muted', {}, '还没有记录')); return; }
    box.append(...evs.slice().reverse().map((e) => histItem(ctx, e)));
  });
  return box;
}

function histItem(ctx, e) {
  const { h, ui } = ctx;
  const d = e.data || {};
  const at = h('span.at', {}, (e.created_at || '').slice(5, 16).replace('T', ' '));
  if (e.kind === 'quiz') {
    const items = Object.entries(d.items || {});
    return h('div.ln-hi', {}, [h('div.hd', {}, [at, h('b', {}, `测试第 ${d.attempt || 1} 次`), d.score !== null && d.score !== undefined ? h('span.tag' + (d.passed ? '.ok' : ''), {}, `${d.score} 分`) : null,
      ...Object.entries(d.dims || {}).map(([k, v]) => h('span.tag.gray', {}, `${k} ${v}`)), d.backfill ? h('span.muted', {}, '（从任务记录补回）') : null]),
      d.summary ? h('div', {}, d.summary) : null,
      ...Object.entries(d.assessment || {}).map(([k, v]) => h('div.sub', {}, [h('b', {}, k + '：'), v])),
      d.weak_points?.length ? h('div.sub', {}, [h('b', {}, '薄弱：'), d.weak_points.join('；')]) : null,
      d.advice ? h('div.sub', {}, [h('b', {}, '建议：'), d.advice]) : null,
      items.length ? h('details', {}, [h('summary', {}, `逐题（${items.length}）`), ...items.map(([qid, it]) => {
        const q = (d.questions || []).find((x) => x.id === qid) || {};
        const mine = it.answer ?? d.answers?.[qid];
        return h('div.sub', {}, [h('b', {}, `${qid} · ${Math.round((it.score || 0) * 100)}%`), ' ', it.q || q.q || '',
          mine !== undefined && mine !== null && mine !== '' ? h('div.mine', {}, '我答：' + (q.options ? `${'ABCDEFG'[+mine]}. ${q.options[+mine] ?? ''}` : mine)) : null,
          it.feedback ? h('div.muted', {}, it.feedback) : null]);
      })]) : null]);
  }
  if (e.kind === 'check_review') {
    const rv = d.review || {};
    const li = (label, arr) => (arr?.length ? h('div.sub', {}, [h('b', {}, label), arr.join('；')]) : null);
    return h('div.ln-hi', {}, [h('div.hd', {}, [at, h('b', {}, '停一下'), h('span.tag', {}, `${Math.round((rv.score || 0) * 100)}%`), d.backfill ? h('span.muted', {}, '（从任务记录补回）') : null]),
      h('div', {}, d.q), h('div.mine', {}, '我答：' + (d.answer || '')),
      rv.parts && Object.keys(rv.parts).length ? h('div.sub', {}, CHECK_PARTS.filter(([k]) => rv.parts[k] !== undefined).map(([k, l]) => `${l} ${Math.round(rv.parts[k] * 100)}%`).join(' · ')) : null,
      li('抓到了：', reviewLists(rv).got), li('漏掉了：', reviewLists(rv).miss),
      rv.better ? h('div.sub', {}, [h('b', {}, '高手会这样想：'), rv.better]) : null]);
  }
  if (e.kind === 'chapter') return h('div.ln-hi', {}, h('div.hd', {}, [at, h('b', {}, '章节' + (d.action || '生成')), d.note ? h('span.muted', {}, '要求：' + d.note) : null,
    d.old_score !== null && d.old_score !== undefined ? h('span.muted', {}, `旧版测试 ${d.old_score} 分`) : null]));
  if (e.kind === 'rating') {
    const names = { understanding: '理解度', feedback: '反馈', status: '状态', notes: '笔记' };
    return h('div.ln-hi', {}, h('div.hd', {}, [at, ...Object.entries(d).filter(([k]) => k !== 'prev').map(([k, v]) => h('span', {}, `${names[k] || k}：${String(v).slice(0, 80)}`))]));
  }
  return h('div.ln-hi', {}, h('div.hd', {}, [at, e.kind]));
}

// 学完当天用到项目：复制一段给 Claude Code 的提示，自动找当天会话 / 文档 / 提交里的引用，也能手动记一条
function applyCard(ctx, s) {
  const { api, h, toast, ui } = ctx;
  const box = h('div.card.ln-apply', { id: 'ln-apply' });
  const load = async () => {
    let a;
    try { a = await api.get(`/api/learn/steps/${s.id}/apply`); } catch { box.replaceChildren(); return; }
    const t = a.today || {};
    const refs = a.records || [];
    const kindName = { manual: '手动记录', session: '会话', doc: '文档', commit: '提交' };
    const proj = h('input', { placeholder: '项目，例如 self_startup' });
    const what = h('input.what', { placeholder: '用了这一章的哪一条、怎么用的' });
    const ev = h('input', { placeholder: '证据（可选）：commit / 文档 / 会话' });
    box.replaceChildren(...[
      h('div.row', {}, [h('h3', {}, '学完今天就用一次'), h('span.grow'),
        t.applied ? h('span.tag.ok', {}, '今天已用到项目') : a.today ? h('span.tag.warn', {}, '今天学完了，还没用到项目') : h('span.muted', {}, '学完当天在一个项目里用一次')]),
      h('div.muted', {}, '复制下面的提示发给项目里的 Claude Code，让它把这章的一条方法用到当前工作上；会话、文档或提交里提到这一章就自动算数。'),
      h('div.row', { style: { marginTop: '8px' } }, [
        h('button.sm.primary', { onclick: async () => { try { await navigator.clipboard.writeText(a.prompt); toast('已复制，贴到项目会话里'); } catch { toast('复制失败', true); } } }, [ui.icon('doc'), ' 复制给 Claude Code 的提示']),
        h('span.muted', { title: (a.terms || []).join('\n') }, `自动识别 ${(a.terms || []).length} 个词（章名、知识卡标题…）`)]),
      (t.refs || []).length ? h('div.ln-refs', {}, t.refs.map((r) => h('div', {}, [h('span.tag.gray', {}, kindName[r.kind] || r.kind), ' ', r.where, r.term ? h('span.muted', {}, ` · ${r.term}`) : null]))) : null,
      h('div.ln-applyform', {}, [what, proj, ev, h('button.sm', { onclick: async () => {
        if (!what.value.trim()) { toast('写一句用了哪一条', true); return; }
        try { await api.post(`/api/learn/steps/${s.id}/apply`, { project: proj.value.trim(), what: what.value.trim(), evidence: ev.value.trim() }); toast('已记录'); load(); }
        catch (e) { toast('记录失败：' + e.message, true); }
      } }, '手动记一条')]),
      refs.length ? h('div.ln-refs', {}, [h('div.card-label', {}, '历次应用'), ...refs.slice(0, 6).map((r) => h('div', {}, [h('span.muted', {}, (r.at || '').slice(0, 16).replace('T', ' ') + ' '), r.project ? h('b', {}, r.project + ' ') : null, r.what, r.evidence ? h('span.muted', {}, ` · ${r.evidence}`) : null]))]) : null,
    ].filter(Boolean));
  };
  load();
  return box;
}

// 总览顶部：三个习惯今天的状态
function habitsCard(ctx) {
  const { api, h } = ctx;
  const box = h('div');
  api.get('/api/learn/habits').then((x) => {
    const k = x.check || {}, a = x.apply || {}, p = x.paper || {};
    const recent = k.recent_avg ?? null;
    const item = (ok, title, text, href) => h(href ? 'a.ln-habit' : 'div.ln-habit', href ? { href } : {}, [h('span.tag' + (ok === null ? '.gray' : ok ? '.ok' : '.warn'), {}, ok === null ? '—' : ok ? '达标' : '未达标'), h('b', {}, title), h('span.muted', { title: text }, text)]);
    box.replaceChildren(h('div.card.ln-habits', {}, [
      item(recent === null ? null : recent >= k.target, '停一下', recent === null ? `近 ${k.days || 7} 天没作答 · 目标 ≥ ${k.target || 65}%`
        : `近 ${k.days} 天 ${recent}% · 目标 ≥ ${k.target}%` + (k.weakest ? ` · 最弱：${(CHECK_PARTS.find(([key]) => key === k.weakest) || [])[1] || k.weakest}` : '')),
      (() => {
        const miss = (a.learned || []).filter((c) => !c.applied);
        const first = miss[0];
        return item(a.total ? !miss.length : null, '学完当天用到项目', a.total ? `今天学完 ${a.total} 章，已用到项目 ${a.applied} 章` + (first ? ` · 下一章去用：${first.title.split(/[：:]/)[0]}` : '') : '今天还没学完新章节',
          first ? chapterHref(first.plan_id, first.step_id) : '');
      })(),
      item(p.done, '每日论文', p.done ? `已读 ${p.count}/${p.goal} 篇` + (p.deepread ? `（深读 ${p.deepread} 篇）` : '') + (p.kb_path ? ` → ${p.kb_path}` : '') : `今天还没读 · ${p.minutes} 分钟，在信息推荐里挑 1–${p.goal} 篇写一句话判断`, '#feed'),
    ]));
  }).catch(() => {});
  return box;
}

// 停一下：近 7 天平均对照目标，四栏各自平均，标出最弱的一栏
function checkStatsRow(ctx, k) {
  const { h } = ctx;
  if (!k || k.avg === null || k.avg === undefined) return null;
  const label = Object.fromEntries(CHECK_PARTS.map(([key, l]) => [key, l]));
  const recent = k.recent_avg ?? null;
  return h('div.ln-chkstat', {}, [
    h('b', {}, '停一下'),
    h('span.tag' + (recent !== null && recent >= k.target ? '.ok' : '.warn'), {}, recent !== null ? `近 ${k.days} 天 ${recent}%（${k.recent_n} 次）` : `近 ${k.days} 天没作答`),
    h('span.muted', {}, `目标 ≥ ${k.target}% · 累计平均 ${k.avg}%`),
    ...Object.entries(k.parts || {}).map(([key, v]) => h('span.tag' + (key === k.weakest ? '.warn' : '.gray'), { title: key === k.weakest ? '最弱的一栏，下一次重点补' : '' }, `${label[key] || key} ${v}%`)),
  ]);
}

// 成长档案：每章最近一次测试、三个维度平均、最近的薄弱点
function growthView(ctx, pid) {
  const { api, h, ui } = ctx;
  const box = h('div');
  api.get(`/api/learn/plans/${pid}/growth`).then((g) => {
    if (!g.counts.events) return;
    const titles = g.titles || {};
    box.append(h('div.card.ln-growth', {}, [
      h('div.row', {}, [h('h3', {}, '成长档案'), h('span.grow'), h('span.muted', {},
        `测试 ${g.counts.quiz} 次 · 停一下点评 ${g.counts.check} 次` + (g.counts.check_avg !== null ? `（平均 ${g.counts.check_avg}%）` : ''))]),
      Object.keys(g.dims).length ? h('div.ln-dims', {}, Object.entries(g.dims).map(([d, v]) => h('div.ln-dimrow', {}, [
        h('b', {}, d), h('div.bar', {}, h('i', { style: { width: v + '%' } })), h('span.v', {}, v + '%'), h('span.t', {}, { 理解: '对这个方向的理解', 判断: '判断力', 应用: '用到自己的论文 / 项目' }[d])]))) : null,
      checkStatsRow(ctx, g.checks),
      g.chapters.length ? h('div.ln-gch', {}, g.chapters.map((c) => h('a', { href: chapterHref(pid, c.step_id) }, [
        h('span', {}, c.title), h('b', {}, c.score !== null && c.score !== undefined ? `${c.score}` : '—')]))) : null,
      g.weak.length ? h('div', { style: { marginTop: '10px' } }, [h('div.card-label', {}, '最近要补的地方（来自测试和停一下点评）'),
        ...g.weak.slice(0, 6).map((w) => h('div.ln-weak', {}, [h('span.tag.gray', {}, w.from), w.text,
          h('a.muted', { href: chapterHref(pid, w.step_id) }, ' · ' + (titles[w.step_id] || '').slice(0, 16))]))]) : null,
    ]));
  }).catch(() => {});
  return box;
}
