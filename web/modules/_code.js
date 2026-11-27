// 代码展示与编辑：轻量语法高亮（python / ts / js / yaml / json / bash）、行号、可编辑的高亮编辑器。
import { h } from '../api.js';

const esc = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

const KW = {
  python: 'False None True and as assert async await break class continue def del elif else except finally for from global if import in is lambda nonlocal not or pass raise return try while with yield match case',
  ts: 'abstract as async await break case catch class const continue default delete do else enum export extends false finally for from function if implements import in instanceof interface let new null of private protected public readonly return static super switch this throw true try type typeof undefined var void while yield',
  bash: 'if then else elif fi for in do done while case esac function return export local set echo cd',
};
KW.js = KW.ts;
const BUILTIN = { python: 'print len range dict list set tuple str int float bool open sum max min sorted enumerate zip map filter any all isinstance getattr hasattr self' };

const RULES = {
  python: [['com', /#.*/y], ['str', /(?:[rbfRBF]{0,2})("""[\s\S]*?"""|'''[\s\S]*?'''|"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*')/y], ['dec', /@[\w.]+/y]],
  ts: [['com', /\/\/.*|\/\*[\s\S]*?\*\//y], ['str', /`(?:\\.|[^`\\])*`|"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*'/y]],
  yaml: [['com', /#.*/y], ['key', /^[ \t-]*[\w@./'"-]+(?=:(\s|$))/my], ['str', /"(?:\\.|[^"\\\n])*"|'(?:[^'\n])*'/y], ['dec', /!![\w]+/y]],
  json: [['key', /"(?:\\.|[^"\\\n])*"(?=\s*:)/y], ['str', /"(?:\\.|[^"\\\n])*"/y]],
  bash: [['com', /#.*/y], ['str', /"(?:\\.|[^"\\\n])*"|'[^'\n]*'/y], ['dec', /\$\{?[\w@#?]+\}?/y]],
};
RULES.js = RULES.ts;

export function langOf(name = '') {
  const n = name.toLowerCase();
  if (/^(py|python)$|\.py$/.test(n)) return 'python';
  if (/^(ts|tsx|typescript)$|\.tsx?$/.test(n)) return 'ts';
  if (/^(js|javascript|mjs)$|\.m?js$/.test(n)) return 'js';
  if (/^(ya?ml)$|\.ya?ml$/.test(n)) return 'yaml';
  if (/^json$|\.json$/.test(n)) return 'json';
  if (/^(sh|bash|shell|zsh)$|\.sh$/.test(n)) return 'bash';
  return '';
}

export function highlight(code, lang = 'python') {
  const rules = RULES[lang];
  if (!rules) return esc(code);
  const kw = new Set((KW[lang] || '').split(' ')), bi = new Set((BUILTIN[lang] || '').split(' '));
  let out = '', i = 0;
  const word = /[A-Za-z_$][\w$]*/y, num = /\b(?:0x[\da-fA-F]+|\d[\d_]*(?:\.\d+)?(?:e[+-]?\d+)?)\b/y;
  outer: while (i < code.length) {
    for (const [cls, re] of rules) {
      re.lastIndex = i;
      const m = re.exec(code);
      if (m && m[0]) { out += `<span class="t-${cls}">${esc(m[0])}</span>`; i += m[0].length; continue outer; }
    }
    word.lastIndex = i;
    let m = word.exec(code);
    if (m) {
      const w = m[0], next = code[i + w.length];
      const cls = kw.has(w) ? 'kw' : bi.has(w) ? 'bi' : next === '(' ? 'fn' : (lang === 'yaml' && /^(true|false|null)$/.test(w)) ? 'kw' : '';
      out += cls ? `<span class="t-${cls}">${w}</span>` : w;
      i += w.length; continue;
    }
    num.lastIndex = i;
    m = num.exec(code);
    if (m) { out += `<span class="t-num">${m[0]}</span>`; i += m[0].length; continue; }
    out += esc(code[i]); i += 1;
  }
  return out;
}

export const CODE_CSS = `
.cv { display: flex; background: #23211e; color: #f1ece4; font: 13px/1.6 var(--mono); border-radius: 8px; overflow: hidden; }
.cv .gut { flex: none; padding: 10px 8px 10px 10px; text-align: right; color: #6f685e; user-select: none; white-space: pre; border-right: 1px solid #38342e; background: #1e1c19; }
.cv .gut .mk, .cv pre .mk { background: rgba(240,168,104,.16); }
.cv .scroll { flex: 1; min-width: 0; overflow-x: auto; }
.cv .ed { position: relative; display: inline-block; min-width: 100%; vertical-align: top; }
.cv .ed pre.hl { display: block; }
.cv pre .mk { display: inline-block; min-width: 100%; }
.cv pre.hl { margin: 0; padding: 10px 12px; display: inline-block; min-width: 100%; box-sizing: border-box; white-space: pre; tab-size: 4; font: inherit; background: none; color: inherit; }
.cv textarea { position: absolute; inset: 0; width: 100%; height: 100%; box-sizing: border-box; margin: 0; padding: 10px 12px; border: 0; outline: none; resize: none; overflow: hidden;
  background: transparent; color: transparent; caret-color: #f1ece4; white-space: pre; tab-size: 4; font: inherit; border-radius: 0; }
.cv textarea::selection { background: rgba(127,184,216,.35); color: transparent; }
.cv.edit:focus-within { box-shadow: inset 0 0 0 1px #7fb8d8; }
.t-kw { color: #f0a868; } .t-str { color: #a8c97f; } .t-com { color: #8b8378; font-style: italic; } .t-num { color: #d4a5e0; }
.t-fn { color: #7fb8d8; } .t-bi { color: #e8c56b; } .t-dec { color: #e8c56b; } .t-key { color: #7fb8d8; }
.md pre.cv-md { padding: 0; background: none; border: 0; }
`;

const gutter = (n, start, mark) => {
  const g = h('div.gut');
  g.innerHTML = Array.from({ length: n }, (_, k) => {
    const ln = start + k;
    return mark.has(ln) ? `<span class="mk">${ln}</span>` : String(ln);
  }).join('\n');
  return g;
};

// 只读代码块：行号 + 高亮；mark 里的行号会标亮
export function codeView(code, { lang = 'python', start = 1, mark = [] } = {}) {
  const text = String(code).replace(/\n$/, '');
  const marks = new Set(mark);
  const pre = h('pre.hl');
  if (marks.size) {
    pre.innerHTML = text.split('\n').map((l, k) => (marks.has(start + k) ? `<span class="mk">${highlight(l, lang) || ' '}</span>` : highlight(l, lang))).join('\n');
  } else pre.innerHTML = highlight(text, lang);
  return h('div.cv', {}, [gutter(text.split('\n').length, start, marks), h('div.scroll', {}, pre)]);
}

// 可编辑的高亮编辑器：返回 { el, ta, refresh }，ta 就是普通 textarea（value / 事件照常用）
export function codeEditor(code, { lang = 'python', onInput } = {}) {
  const ta = h('textarea', { spellcheck: 'false', autocapitalize: 'off', autocomplete: 'off' });
  ta.value = code;
  const pre = h('pre.hl', { 'aria-hidden': 'true' });
  const gut = h('div.gut');
  const refresh = () => {
    pre.innerHTML = highlight(ta.value, lang) + '\n';
    gut.textContent = Array.from({ length: ta.value.split('\n').length }, (_, k) => k + 1).join('\n');
    onInput?.();
  };
  ta.addEventListener('input', refresh);
  refresh();
  return { el: h('div.cv.edit', {}, [gut, h('div.scroll', {}, h('div.ed', {}, [pre, ta]))]), ta, refresh };
}

// 把 md() 渲染出的 ```lang 代码块换成高亮版（带行号）
export function enhanceMd(root) {
  root.querySelectorAll('pre > code').forEach((c) => {
    const lang = langOf((c.className.match(/language-(\S+)/) || [])[1] || '');
    if (!lang) return;
    const pre = c.parentElement;
    const v = codeView(c.textContent, { lang });
    pre.replaceWith(h('pre.cv-md', {}, v));
  });
  return root;
}
