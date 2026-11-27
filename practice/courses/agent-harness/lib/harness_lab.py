"""Agent Harness 实践课的练习场：一个小项目 textkit + 10 道能自动判分的任务 + 评测、patch、钩子、插件小工具。

判分不看 agent 怎么说，只在工作区的一份拷贝里跑隐藏检查（agent 看不到也改不到）。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

import ss

LAB = ss.DSH
PY = sys.executable

CORE = '''"""textkit：几个处理文本的小函数。"""
import re


def slugify(s):
    """把标题变成 URL 片段：'Hello World!' -> 'hello-world'。"""
    s = re.sub(r"[^a-z0-9]+", "-", s.lower())
    return s.strip("-")


def chunks(xs, n):
    """按 n 个一组切分：chunks([1,2,3], 2) -> [[1,2],[3]]。"""
    return [xs[i:i + n] for i in range(0, len(xs), n)]


def wrap(text, width):
    """按单词贪心折行，每行不超过 width 个字符。"""
    lines, cur = [], ""
    for w in text.split():
        if cur and len(cur) + 1 + len(w) > width:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}" if cur else w
    if cur:
        lines.append(cur)
    return lines


def word_freq(text):
    """统计词频（忽略大小写和标点），返回 {词: 次数}。"""
    out = {}
    for w in re.findall(r"[a-z0-9']+", text.lower()):
        out[w] = out.get(w, 0) + 1
    return out


def title_case(s):
    """每个单词首字母大写。"""
    return " ".join(w[:1].upper() + w[1:] for w in s.split())
'''

CLI = '''"""命令行：python -m textkit.cli slug "Hello World" """
import sys

from textkit.core import slugify, title_case


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    cmd, *rest = argv
    if cmd == "slug":
        print(slugify(" ".join(rest)))
    elif cmd == "title":
        print(title_case(" ".join(rest)))
    else:
        print(f"unknown command: {cmd}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''

TESTS = '''import unittest

from textkit.core import chunks, slugify, title_case, wrap


class CoreTest(unittest.TestCase):
    def test_slugify(self):
        self.assertEqual(slugify("Hello World!"), "hello-world")

    def test_chunks(self):
        self.assertEqual(chunks([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])

    def test_wrap(self):
        self.assertEqual(wrap("a bb ccc dddd", 6), ["a bb", "ccc", "dddd"])

    def test_title_case(self):
        self.assertEqual(title_case("hello world"), "Hello World")


if __name__ == "__main__":
    unittest.main()
'''

CONTRIBUTING = '''# 贡献约定

- 跑测试：`python -m unittest discover -s tests`（本项目不用 pytest）。
- 每次改动代码，都要在 CHANGELOG.md 的「## 未发布」下面加一行 `- <改了什么>`。
- 新增的公开函数必须写 docstring。
- 不要修改 tests/ 里已有的测试来让它通过。
'''

WORDS = ("the cat sat on the mat the dog sat on the log a cat and a dog met the cat " * 3).strip() + "\n"


def project() -> dict:
    return {"textkit/__init__.py": "", "textkit/core.py": CORE, "textkit/cli.py": CLI, "tests/test_core.py": TESTS,
            "CONTRIBUTING.md": CONTRIBUTING, "CHANGELOG.md": "# 变更记录\n\n## 未发布\n", "data/words.txt": WORDS,
            "README.md": "# textkit\n\n几个处理文本的小函数，见 textkit/core.py；约定见 CONTRIBUTING.md。\n"}


@dataclass
class Task:
    id: str
    prompt: str
    check: str                       # 在工作区拷贝里执行的 Python，失败就 raise / assert
    seed: dict = field(default_factory=dict)       # 在原项目上做的改动（种 bug）：{路径: (旧, 新)} 或 {路径: 新全文}
    changelog: bool = False          # 判分时要求 CHANGELOG.md 新增了一行
    keep_tests: bool = True          # 判分时要求 tests/ 没被改


TASKS = [
    Task("slug-lower", "slugify('Hello World!') 应该返回 'hello-world'，现在返回的不对，修好它。",
         "from textkit.core import slugify as f\nassert f('Hello World!') == 'hello-world', f('Hello World!')\nassert f('A  B') == 'a-b'",
         seed={"textkit/core.py": ('s.lower()', 's')}, changelog=True),
    Task("chunks-tail", "测试挂了，找出原因修好。",
         "from textkit.core import chunks as f\nassert f([1,2,3,4,5], 2) == [[1,2],[3,4],[5]]\nassert f([], 3) == []\nassert f([1,2,3], 3) == [[1,2,3]]",
         seed={"textkit/core.py": ('range(0, len(xs), n)', 'range(0, len(xs) - n, n)')}, changelog=True),
    Task("freq-impl", "word_freq 还没实现，按 docstring 实现它。",
         "from textkit.core import word_freq as f\nassert f(\"The cat, the CAT! it's\") == {'the': 2, 'cat': 2, \"it's\": 1}",
         seed={"textkit/core.py": ('''    out = {}
    for w in re.findall(r"[a-z0-9']+", text.lower()):
        out[w] = out.get(w, 0) + 1
    return out''', '    raise NotImplementedError')}, changelog=True),
    Task("wrap-long", "wrap 遇到比 width 还长的单词时，那个单词要单独占一行（不截断）。检查现在的行为，不对就修。",
         "from textkit.core import wrap as f\nassert f('a verylongword b', 4) == ['a', 'verylongword', 'b'], f('a verylongword b', 4)\nassert f('', 5) == []",
         seed={"textkit/core.py": ('''        if cur and len(cur) + 1 + len(w) > width:''', '''        if len(w) > width:
            continue
        if cur and len(cur) + 1 + len(w) > width:''')}, changelog=True),
    Task("rename", "把 title_case 改名为 titlecase，所有用到的地方一起改，不保留旧名字。",
         "import textkit.core as c, pathlib\nassert hasattr(c, 'titlecase') and not hasattr(c, 'title_case')\nsrc = ''.join(p.read_text() for p in pathlib.Path('textkit').rglob('*.py'))\nassert 'title_case' not in src\n"
         "import subprocess, sys\nassert subprocess.run([sys.executable, '-m', 'textkit.cli', 'title', 'a b'], capture_output=True, text=True).stdout.strip() == 'A B'",
         changelog=True, keep_tests=False),
    Task("cli-upper", "给命令行加一个 upper 子命令：python -m textkit.cli upper hello world 输出 HELLO WORLD。",
         "import subprocess, sys\nr = subprocess.run([sys.executable, '-m', 'textkit.cli', 'upper', 'hello', 'world'], capture_output=True, text=True)\nassert r.stdout.strip() == 'HELLO WORLD', r.stdout + r.stderr",
         changelog=True),
    Task("count-words", "在 textkit/core.py 里新增 count_words(text)，返回单词个数（按空白切分）。",
         "from textkit.core import count_words as f\nassert f('a b  c\\n d') == 4 and f('') == 0\nassert (f.__doc__ or '').strip(), '缺 docstring'",
         changelog=True),
    Task("slug-cjk", "slugify 要保留汉字：slugify('你好 World') 应该是 '你好-world'。",
         "from textkit.core import slugify as f\nassert f('你好 World') == '你好-world', f('你好 World')\nassert f('Hello World!') == 'hello-world'",
         changelog=True),
    Task("top-words", "data/words.txt 里出现最多的 3 个词是什么？写到 answer.txt，每行一个词，按次数从多到少。",
         "lines = open('answer.txt').read().split()\nassert lines[:3] == ['the', 'cat', 'sat'] or lines[:3] == ['the', 'cat', 'on'], lines"),
    Task("cli-freq", "给命令行加 freq 子命令：python -m textkit.cli freq FILE 输出出现最多的 3 个词，每行 `词 次数`。",
         "import subprocess, sys\nr = subprocess.run([sys.executable, '-m', 'textkit.cli', 'freq', 'data/words.txt'], capture_output=True, text=True)\nrows = [l.split() for l in r.stdout.strip().splitlines()]\nassert rows[:2] == [['the', '15'], ['cat', '9']], r.stdout + r.stderr",
         changelog=True),
]
BY_ID = {t.id: t for t in TASKS}
TRAIN = ["slug-lower", "freq-impl", "rename", "count-words", "top-words"]
HOLDOUT = ["chunks-tail", "wrap-long", "cli-upper", "slug-cjk", "cli-freq"]


def files_for(task: Task) -> dict:
    files = project()
    for path, change in task.seed.items():
        if isinstance(change, tuple):
            old, new = change
            assert old in files[path], (task.id, old)
            files[path] = files[path].replace(old, new, 1)
        else:
            files[path] = change
    return files


def _digest(root: Path, sub: str) -> str:
    h = hashlib.md5()
    for p in sorted((root / sub).rglob("*")):
        if p.is_file() and "__pycache__" not in p.parts:
            h.update(str(p.relative_to(root)).encode() + p.read_bytes())
    return h.hexdigest()


def grade(task: Task, ws: Path) -> tuple[bool, str]:
    """在工作区的一份临时拷贝里跑隐藏检查；返回 (是否通过, 原因)。"""
    ws = Path(ws)
    with tempfile.TemporaryDirectory() as tmp:
        dst = Path(tmp) / "w"
        shutil.copytree(ws, dst, ignore=shutil.ignore_patterns("__pycache__", ".git"))
        r = subprocess.run([PY, "-c", task.check], cwd=dst, capture_output=True, text=True, timeout=60, env={**os.environ, "PYTHONPATH": str(dst)})
        if r.returncode:
            return False, "检查没过：" + (r.stderr.strip().splitlines() or ["?"])[-1][:200]
    if task.keep_tests and _digest(ws, "tests") != _digest_files(project(), "tests"):
        return False, "改了 tests/ 里的测试"
    if task.changelog:
        added = [l for l in (ws / "CHANGELOG.md").read_text().splitlines() if l.startswith("- ")]
        if not added:
            return False, "没在 CHANGELOG.md 记一行（CONTRIBUTING.md 的约定）"
    return True, "通过"


def _digest_files(files: dict, sub: str) -> str:
    h = hashlib.md5()
    for rel in sorted(k for k in files if k.startswith(sub + "/")):
        h.update(rel.encode() + files[rel].encode())
    return h.hexdigest()


def workspace(task: Task | str, tag: str = "run", extra: dict | None = None) -> Path:
    task = BY_ID[task] if isinstance(task, str) else task
    return ss.workspace(f"{tag}-{task.id}", {**files_for(task), **(extra or {})})


def run(task: Task | str, tag: str = "run", extra: dict | None = None, show: bool = False, prompt: str = "", **kw) -> dict:
    """在全新工作区里跑一道题并判分。prompt 可替换题面（如加 /plan 前缀）；kw 原样交给 ss.agent（profile / patches / env / home / approve …）。"""
    task = BY_ID[task] if isinstance(task, str) else task
    ws = workspace(task, tag, extra)
    r = ss.agent(prompt or task.prompt, ws, show=show, title=task.id, **kw)
    ok, why = grade(task, ws) if r.reason != "over-budget" else (False, "超出花费上限")
    t = r.tokens()
    return {"task": task.id, "ok": ok, "why": why, "steps": len(r.usage), "tools": len(r.calls), "in": t["inputTokens"] + t["cacheReadTokens"],
            "cost": round(r.cost, 4), "secs": round(r.seconds, 1), "reason": r.reason, "run": r, "ws": ws}


COLS = ["task", "ok", "why", "steps", "tools", "in", "cost", "secs"]


def bench(tasks=None, tag: str = "bench", repeats: int = 1, title: str = "", **kw) -> list:
    """一组题挨个跑，表格实时刷新。返回每次运行的结果行。"""
    ids = tasks or [t.id for t in TASKS]
    rows, view = [], ss.table([], COLS, title or tag)
    for rep in range(repeats):
        for tid in ids:
            res = run(tid, tag=f"{tag}{rep}", **kw)
            res["rep"] = rep
            rows.append(res)
            view.update(cols=COLS, rows=[[x[c] if c != "ok" else ("✓" if x["ok"] else "✗") for c in COLS] for x in rows],
                        title=f"{title or tag} · {sum(x['ok'] for x in rows)}/{len(rows)} 通过 · {sum(x['cost'] for x in rows):.3f} 元")
            if res["reason"] == "over-budget":
                return rows
    return rows


def score(rows: list) -> dict:
    n = len(rows) or 1
    return {"通过率": round(sum(r["ok"] for r in rows) / n, 3), "平均步数": round(sum(r["steps"] for r in rows) / n, 1),
            "平均花费（元）": round(sum(r["cost"] for r in rows) / n, 4), "总花费（元）": round(sum(r["cost"] for r in rows), 3), "次数": len(rows)}


# ---------- 配置：patch、导出配置树、装插件、钩子、MCP ----------

def patch(name: str, text: str) -> Path:
    """把一段 cordis patch（YAML）存成文件，返回路径，交给 ss.agent(patches=[...])。"""
    p = LAB / "patches" / f"{name}.yml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text.strip() + "\n")
    return p


def runtime_bin() -> str:
    from deepseek_harness_runtime import resolve_bundled_launch_args
    return resolve_bundled_launch_args()[0]


def _no_proxy_env(home) -> dict:
    env = {k: v for k, v in os.environ.items() if k.lower() not in ("http_proxy", "https_proxy", "all_proxy")}
    env["DSH_HOME"] = str(home)
    return env


def dump_text(profile: str = "sdk", patches=(), home=None) -> str:
    """组合后的配置树原文（dsh --dump-config）。"""
    home = home or LAB / f"home-{profile}"
    args = [runtime_bin(), "--profile", profile, *[a for p in patches for a in ("--patch", str(p))], "--dump-config"]
    return subprocess.run(args, capture_output=True, text=True, env=_no_proxy_env(home), timeout=120).stdout


def entry(profile: str, id_: str, patches=()) -> str:
    """配置树里某一条（按 id）的原文。"""
    m = re.search(rf"^- id: {re.escape(id_)}\n(?:(?!- id: ).*\n)*", dump_text(profile, patches), re.M)
    return m[0] if m else ""


def dump(profile: str = "sdk", patches=(), home=None) -> list:
    """返回组合后的插件列表 [(id, 包名, 是否禁用)]。"""
    out = dump_text(profile, patches, home)
    rows, cur = [], None
    for line in out.splitlines():
        m = re.match(r"^(\s*)- id: (\S+)", line)
        if m:
            cur = [m[2], "", False]
            rows.append(cur)
        elif cur and re.match(r"^\s+name: ", line) and not cur[1]:
            cur[1] = line.split("name:", 1)[1].strip().strip("'\"")
        elif cur and re.match(r"^\s+disabled: true", line):
            cur[2] = True
    return rows


def install(package: str, profile: str = "sdk", home=None) -> str:
    """往某个 profile 装一个 npm 上的 dsh 插件（版本要和运行时一致，如 @0.2.2-rc.2）。装过就跳过。"""
    home = Path(home or LAB / f"home-{profile}")
    name = package.rsplit("@", 1)[0] if package.count("@") > 1 else package
    pj = home / "profiles" / profile / "package.json"
    if pj.exists() and name in json.loads(pj.read_text()).get("dependencies", {}):
        return f"{name} 已装"
    if not pj.exists():
        dump(profile, home=home)
    r = subprocess.run([runtime_bin(), "plugin", "--profile", profile, "add", "-w", package], capture_output=True, text=True,
                       env=_no_proxy_env(home), timeout=900)
    if r.returncode:
        raise RuntimeError("装插件失败：" + (r.stderr or r.stdout)[-600:])
    return f"{package} 装好了"


def hooks(name: str, config: dict) -> Path:
    """写一份 Claude Code 格式的 hooks.json，并生成接 hooks-claude-code 桥的 patch。"""
    cfg = LAB / "hooks" / f"{name}.json"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(json.dumps({"hooks": config}, ensure_ascii=False, indent=1))
    return patch(f"hooks-{name}", f"""
- insert:
    - id: hooks-{name}
      name: '@deepseek-ai/dsh-hooks-claude-code'
      config:
        configPath: {cfg}
""")


def script(name: str, code: str) -> str:
    """把一段 Python 存成钩子 / MCP 服务脚本，返回可放进命令行的 `python 路径`。"""
    p = LAB / "scripts" / f"{name}.py"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("# -*- coding: utf-8 -*-\n" + code.strip() + "\n")
    return f"{PY} {p}"


def mcp(name: str, command: str, args=()) -> Path:
    """生成接一个 stdio MCP 服务的 patch。"""
    a = ", ".join(json.dumps(str(x)) for x in args)
    return patch(f"mcp-{name}", f"""
- insert:
    - id: mcp-{name}
      name: '@deepseek-ai/dsh-mcp-client'
      config:
        serverName: {name}
        transport: stdio
        command: {command}
        args: [{a}]
""")


def offered(run) -> list:
    """这次请求里提供给模型的工具名。"""
    h = next((e for e in run.events if e["type"] == "request/header"), None)
    return [t["name"] for t in h["data"]["header"]["tools"]] if h else []


def system_prompt(run) -> str:
    e = next((e for e in run.events if e["type"] == "system/message"), None)
    return ss._text(e["data"]["message"]["content"]) if e else ""


def src(path: str, find: str = "", lines: int = 40, title: str = "") -> ss.View:
    """显示课程仓库（dsh 源码）里一个文件的片段：从第一处包含 find 的行开始。"""
    text = Path(path).read_text(encoding="utf-8").splitlines()
    i = next((k for k, l in enumerate(text) if find in l), 0) if find else 0
    ext = Path(path).suffix.lstrip(".")
    lang = {"py": "python", "ts": "ts", "tsx": "ts", "js": "js", "mjs": "js", "yaml": "yaml", "yml": "yaml", "json": "json", "sh": "bash"}.get(ext, "")
    head = f"{path} · 第 {i + 1}–{min(len(text), i + lines)} 行"
    return ss.code("\n".join(text[i:i + lines]), lang, f"{title} · {head}" if title else head, start=i + 1, mark=[i + 1] if find else [])


def steer(h, session: str, text: str):
    """运行中给会话插一句话（进 inbox，下一步生效）。"""
    import threading
    threading.Thread(target=lambda: h.client.session_prompt(session, [{"type": "text", "text": text}]), daemon=True).start()


def sessions(home=None) -> list:
    """读一个（默认所有）DSH_HOME 下的全部会话日志：[{id, home, cwd, events}]。sdk 用 zstd 压缩，sdk-minimal 是纯 jsonl。"""
    import zstandard
    homes = [Path(home)] if home else sorted(LAB.glob("home-*"))
    out = []
    for hm in homes:
        for f in sorted(hm.glob("sessions/*/*/session.v4.jsonl*")):
            raw = f.read_bytes()
            if f.suffix == ".zstd":
                import io
                raw = zstandard.ZstdDecompressor().stream_reader(io.BytesIO(raw), read_across_frames=True).read()
            events = [json.loads(l) for l in raw.decode("utf-8", "replace").splitlines() if l.strip()]
            out.append({"id": f.parent.name, "home": hm.name, "cwd": f.parent.parent.name, "events": events, "mtime": f.stat().st_mtime})
    return out


# ---------- 第二部分：尺子、归因、写回、进化 ----------

def by_task(rows: list) -> dict:
    out = {}
    for r in rows:
        out.setdefault(r["task"], []).append(r["ok"])
    return out


def noise(rows: list) -> dict:
    """同一配置多次重复：每轮通过率、波动、每题是否稳定。"""
    reps = sorted({r.get("rep", 0) for r in rows})
    rates = [sum(r["ok"] for r in rows if r.get("rep", 0) == k) / max(1, sum(r.get("rep", 0) == k for r in rows)) for k in reps]
    flaky = [t for t, oks in by_task(rows).items() if 0 < sum(oks) < len(oks)]
    return {"每轮通过率": rates, "最高-最低": round(max(rates) - min(rates), 3) if rates else 0, "不稳定的题": flaky}


def paired(a: list, b: list) -> dict:
    """配对比较：同一道题上 A、B 各自的通过率，数 B 赢、输、平的题数。"""
    ta, tb = by_task(a), by_task(b)
    win = lose = tie = 0
    for t in ta.keys() & tb.keys():
        pa, pb = sum(ta[t]) / len(ta[t]), sum(tb[t]) / len(tb[t])
        win, lose, tie = win + (pb > pa), lose + (pb < pa), tie + (pb == pa)
    return {"B 更好": win, "B 更差": lose, "持平": tie}


def brief(row: dict, limit: int = 4000) -> str:
    """把一次运行压成给诊断者读的文字：题面、判分、按顺序的工具调用和关键输出、最终回答。"""
    r = row["run"]
    out = [f"题目：{BY_ID[row['task']].prompt}", f"判分：{row['why']}"]
    names = {}
    for e in r.events:
        d = e.get("data") or {}
        if e["type"] == "tool/call":
            names[d.get("callId")] = d.get("name")
            out.append(f"[调用] {d.get('name')} {str(d.get('arguments'))[:240]}")
        elif e["type"] == "tool/result":
            m = d.get("message") or {}
            out.append(f"[结果] {ss._text(m.get('content'))[:240]}")
    out.append("最终回答：" + r.final[:600])
    text = "\n".join(out)
    return text if len(text) <= limit else text[:limit // 2] + "\n…\n" + text[-limit // 2:]


@dataclass
class Config:
    """被进化的 harness 配置：AGENTS.md 规则、skill 文件、Stop 闸门检查项。每一项都可单独加减。"""
    rules: list = field(default_factory=list)
    skills: dict = field(default_factory=dict)
    stop_checks: list = field(default_factory=list)     # 取值 "tests" / "changelog"

    def files(self) -> dict:
        f = {}
        if self.rules:
            f["AGENTS.md"] = "# 给 agent 的说明\n" + "".join(f"- {r}\n" for r in self.rules)
        for name, body in self.skills.items():
            if not body.lstrip().startswith("---"):
                body = f"---\nname: {name}\ndescription: textkit 项目的做事经验，改代码前先读。\n---\n\n" + body
            f[f".agents/skills/{name}/SKILL.md"] = body
        return f

    def patches(self) -> list:
        if not self.stop_checks:
            return []
        checks = json.dumps(sorted(self.stop_checks))
        cmd = script("evo_stop_" + "_".join(sorted(self.stop_checks)), f"""
import json, subprocess, sys
e = json.load(sys.stdin)
if e.get("stop_hook_active"):
    sys.exit(0)
checks, why = {checks}, []
if "tests" in checks and subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests"], capture_output=True).returncode:
    why.append("单元测试没过")
if "changelog" in checks and not any(l.startswith("- ") for l in open("CHANGELOG.md", encoding="utf-8")):
    why.append("CHANGELOG.md 没记这次改动")
if why:
    print(json.dumps({{"decision": "block", "reason": "还不能结束：" + "；".join(why)}}, ensure_ascii=False))
""")
        return [hooks("evo-" + "-".join(sorted(self.stop_checks)), {"Stop": [{"hooks": [{"type": "command", "command": cmd}]}]})]

    def size(self) -> int:
        return len(self.rules) + len(self.skills) + len(self.stop_checks)

    def copy(self) -> "Config":
        return Config(list(self.rules), dict(self.skills), list(self.stop_checks))

    def show(self, title: str = "当前配置") -> ss.View:
        rows = [["规则", r] for r in self.rules] + [["skill", k] for k in self.skills] + [["Stop 闸门", c] for c in self.stop_checks]
        return ss.table(rows or [["（空）", "基线"]], ["层", "内容"], title)


def evaluate(cfg: Config, tasks, tag: str, repeats: int = 1, title: str = "") -> list:
    return bench(tasks, tag=tag, repeats=repeats, title=title or tag, extra=cfg.files(), patches=cfg.patches())


def apply_change(cfg: Config, ch: dict) -> Config:
    """ch = {"layer": "rule"|"skill"|"stop", "content": ..., "name"?: ...}；返回改动后的新配置。"""
    c = cfg.copy()
    if ch["layer"] == "rule":
        c.rules.append(ch["content"])
    elif ch["layer"] == "skill":
        c.skills[ch.get("name") or f"skill{len(c.skills) + 1}"] = ch["content"]
    elif ch["layer"] == "stop":
        if ch["content"] not in c.stop_checks:
            c.stop_checks.append(ch["content"])
    return c


def parse_json(text: str):
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    body = m[1] if m else text[text.find("{") if "{" in text else 0:]
    if body.lstrip().startswith("["):
        body = body[body.find("["):body.rfind("]") + 1]
    else:
        body = body[:body.rfind("}") + 1]
    return json.loads(body)
