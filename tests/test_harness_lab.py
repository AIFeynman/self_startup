import importlib
import sys
from pathlib import Path

import pytest

LIB = Path(__file__).resolve().parents[1] / "practice"

FIX = {
    "slug-lower": {"textkit/core.py": ('re.sub(r"[^a-z0-9]+", "-", s)', 're.sub(r"[^a-z0-9]+", "-", s.lower())')},
    "chunks-tail": {"textkit/core.py": ("len(xs) - n, n)", "len(xs), n)")},
    "freq-impl": {"textkit/core.py": ("    raise NotImplementedError", "    out = {}\n    for w in re.findall(r\"[a-z0-9']+\", text.lower()):\n        out[w] = out.get(w, 0) + 1\n    return out")},
    "wrap-long": {"textkit/core.py": ("        if len(w) > width:\n            continue\n", "")},
    "rename": {"textkit/core.py": ("def title_case", "def titlecase"), "textkit/cli.py": ("title_case", "titlecase"), "tests/test_core.py": ("title_case", "titlecase")},
    "cli-upper": {"textkit/cli.py": ('    elif cmd == "title":', '    elif cmd == "upper":\n        print(" ".join(rest).upper())\n    elif cmd == "title":')},
    "count-words": {"textkit/core.py": ("def title_case", 'def count_words(text):\n    """数单词。"""\n    return len(text.split())\n\n\ndef title_case')},
    "slug-cjk": {"textkit/core.py": ('re.sub(r"[^a-z0-9]+", "-", s.lower())', 're.sub(r"[^a-z0-9\\u4e00-\\u9fff]+", "-", s.lower())')},
    "top-words": {"answer.txt": "the\ncat\nsat\n"},
    "cli-freq": {"textkit/cli.py": ('    elif cmd == "title":', '    elif cmd == "freq":\n        from textkit.core import word_freq\n        top = sorted(word_freq(open(rest[0]).read()).items(), key=lambda x: -x[1])[:3]\n        print("\\n".join(f"{w} {c}" for w, c in top))\n    elif cmd == "title":')},
}


@pytest.fixture(scope="module")
def lab(tmp_path_factory):
    import os
    os.environ["SS_WORK"] = str(tmp_path_factory.mktemp("work"))
    sys.path[:0] = [str(LIB), str(LIB / "courses" / "agent-harness" / "lib")]
    for m in ("ss", "harness_lab"):
        sys.modules.pop(m, None)
    return importlib.import_module("harness_lab")


def _apply(ws: Path, fix: dict, changelog: bool):
    for rel, change in fix.items():
        p = ws / rel
        if isinstance(change, tuple):
            text = p.read_text()
            assert change[0] in text, (rel, change[0])
            p.write_text(text.replace(change[0], change[1]))
        else:
            p.write_text(change)
    if changelog:
        p = ws / "CHANGELOG.md"
        p.write_text(p.read_text() + "- 修好了\n")


def test_every_task_has_a_reference_fix(lab):
    assert set(FIX) == set(lab.BY_ID) and set(lab.TRAIN) | set(lab.HOLDOUT) == set(lab.BY_ID)
    assert not set(lab.TRAIN) & set(lab.HOLDOUT)


@pytest.mark.parametrize("tid", sorted(FIX))
def test_seeded_fails_and_reference_passes(lab, tid):
    task = lab.BY_ID[tid]
    ws = lab.workspace(task, "selftest")
    ok, why = lab.grade(task, ws)
    assert not ok, f"{tid} 不做任何事就判过了"
    _apply(ws, FIX[tid], task.changelog)
    ok, why = lab.grade(task, ws)
    assert ok, f"{tid} 参考答案没判过：{why}"


def test_fix_without_changelog_fails(lab):
    task = lab.BY_ID["slug-lower"]
    ws = lab.workspace(task, "nolog")
    _apply(ws, FIX["slug-lower"], changelog=False)
    assert lab.grade(task, ws) == (False, "没在 CHANGELOG.md 记一行（CONTRIBUTING.md 的约定）")


def test_editing_tests_is_caught(lab):
    task = lab.BY_ID["chunks-tail"]
    ws = lab.workspace(task, "cheat")
    _apply(ws, FIX["chunks-tail"], changelog=True)
    (ws / "tests" / "test_core.py").write_text("")
    assert lab.grade(task, ws) == (False, "改了 tests/ 里的测试")


def test_src_shows_numbered_highlighted_slice_marking_found_line(lab, tmp_path, monkeypatch):
    shown = []
    monkeypatch.setattr(lab.ss, "View", lambda kind, data: shown.append({"kind": kind, **data}))
    f = tmp_path / "agent.ts"
    f.write_text("\n".join(f"line {i}" for i in range(1, 21)) + "\n  private async kick() {\n  }\n", encoding="utf-8")
    lab.src(str(f), "private async kick", 2, "kick")
    v = shown[-1]
    assert (v["kind"], v["lang"], v["start"], v["mark"]) == ("code", "ts", 21, [21])
    assert v["code"] == "  private async kick() {\n  }"
    assert "第 21–22 行" in v["title"]
