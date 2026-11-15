"""分级规则（纯函数）：feed 条目 → Tier / 类别 / 理由。只读条目，不碰信息推荐和产品雷达的排序与配置。
机构、人物白名单全部复用现成数据：people.json（人）、_feed_rank 的官方域名和 GitHub 机构、条目自带的 judge_important。"""
import re
from functools import cache

from . import _feed_rank as rk
from . import _people

CATS = {
    "report": (1, "头部开源技术报告"), "official": (1, "官方深度文章"), "repo": (1, "头部机构开源项目"),
    "person": (1, "名人深度内容"), "case": (1, "增长 / 产品案例"),
    "launch": (2, "重要产品发布"), "paper": (2, "热点论文"), "trending": (2, "增速快的项目"), "product": (2, "热点产品"),
    "author": (2, "作者干货"), "update": (2, "产品重要更新"), "top": (2, "头部内容"), "interest": (2, "兴趣相关"),
}

LABS = {name: re.compile(p, re.I) for name, p in {
    "DeepSeek": r"DeepSeek", "Qwen": r"Qwen|Alibaba|Tongyi", "Kimi": r"Kimi|Moonshot", "MiniMax": r"MiniMax",
    "Z.AI": r"\bZ\.ai\b|Zhipu|智谱|\bGLM\b|THUDM", "Mistral": r"Mistral", "Meta": r"\bLlama\b|Meta AI|Meta Superintelligence",
}.items()}
LAB_GITHUB = {"deepseek-ai", "qwenlm", "moonshotai", "minimax-ai", "zai-org", "thudm", "mistralai"}
TECH_REPORT = re.compile(r"technical report|tech report|技术报告", re.I)
DEEP_URL = re.compile(r"/(?:research|engineering|safety|alignment|interpretability|science)\b|research\.google|deepmind\.google/(?:research|science)", re.I)
AI_CASE = re.compile(r"\bAI\b|\bLLM|GPT|Claude|\bagents?\b|人工智能", re.I)
ANNOUNCE = re.compile(r"\b(?:launch(?:ing|ed)?|announc\w+|introducing|excited|thrilled|proud|rolling out|shipped|available (?:now|today|to)|now available|today we|out now)\b|发布|上线", re.I)

OFFICIAL_DEEP, OFFICIAL_UPDATE = 0.8, 0.4     # 官方博客 judge_important：深度文章 / 值得扫一眼的更新，再低的是客户案例和 PR 稿
POP_TOP, POP_MID = 0.85, 0.5                   # 同源热度百分位
LONG_POST_CHARS = 350                          # X 帖正文最多存 400 字，接近上限的是长帖 / thread
INTERVIEW_STRICT_S, INTERVIEW_S = 1800, 1200   # 名人访谈 ≥30 分钟进 Tier1，其他作者 ≥20 分钟算干货

INTEREST_LINES = {
    "AI Teams 架构和管理": ["agent team", "multi-agent", "multi agent", "subagent", "sub-agent", "orchestration", "orchestrator", "agent org", "ai team",
                         "多智能体", "多 agent", "子 agent", "agent 团队", "ai 团队", "agent swarm"],
    "Agents 与 harness": ["harness", "agent loop", "context engineering", "上下文工程", "claude code", "codex", "agents.md", "claude.md",
                          "coding agent", "agent sdk", "long-running agent", "长程", "agent skills", "mcp server"],
    "程序化视频生成": ["programmatic video", "remotion", "motion canvas", "manim", "code-to-video", "程序化视频", "视频生成", "代码生成视频"],
}


@cache
def _x_tier() -> dict[str, int]:
    return {p["x"].lower(): p["tier"] for p in _people.people() if p.get("x")}


def person_tier(it: dict) -> int:
    ex = it.get("extra") or {}
    if it["source"] == "twitter":
        return _x_tier().get((ex.get("author") or "").lower().lstrip("@"), 0)
    text = f"{ex.get('author') or ''} {ex.get('channel') or ''}" + (f" {it['title']}" if it["type"] in ("podcast", "video") else "")
    by_id = _people.by_id()
    return min((by_id[i]["tier"] for i in _people.match_people(text)), default=0)


def lab_of(it: dict) -> str:
    ex = it.get("extra") or {}
    text = f"{it['title']} {ex.get('orgs') or ''} {ex.get('affil') or ''} {ex.get('author') or ''} {it.get('url') or ''}"
    return next((n for n, p in LABS.items() if p.search(text)), "")


def _owner(it: dict) -> str:
    return ((it.get("extra") or {}).get("repo") or "").split("/")[0].lower()


def depth(it: dict, min_video_s: int = INTERVIEW_S) -> bool:
    """干货门槛：长文 / 长帖 / 论文 / 项目 / 够长的访谈。一两句话的帖子、讨论串、短视频不算。"""
    ex, typ = it.get("extra") or {}, it["type"]
    if it["source"] == "twitter":
        body = it.get("summary") or ""
        return bool(ex.get("x_article") or ex.get("article_title")) or (len(body) >= LONG_POST_CHARS and not ANNOUNCE.search(body))
    if typ == "video":
        return (ex.get("duration") or 0) >= min_video_s
    return typ in ("paper", "repo", "blog", "podcast") and it["source"] != "zhihu"


@cache
def _kw_re(kw: str) -> re.Pattern:
    if kw.isascii():
        return re.compile(rf"(?<![a-z0-9]){re.escape(kw)}s?(?![a-z0-9])")
    return re.compile(re.escape(kw))


def interest_hit(it: dict, lines: dict[str, list[str]] = INTEREST_LINES) -> str:
    title = it["title"].lower()
    body = f"{title} {it.get('summary') or ''} {(it.get('extra') or {}).get('gist') or ''}".lower()
    for name, kws in lines.items():
        if any(_kw_re(k).search(title) for k in kws) or len({k for k in kws if _kw_re(k).search(body)}) >= 2:
            return name
    return ""


def long_form(it: dict) -> bool:
    """兴趣提权到 Tier1 只给博客 / 播客 / 视频长内容：论文、项目、X 帖命中兴趣词不代表适合深读。"""
    imp = (it.get("extra") or {}).get("judge_important")
    return it["type"] in ("blog", "podcast", "video") and depth(it) and (imp is None or imp >= 0.7)


def _org_repo(it: dict, org: str) -> tuple[str, str]:
    """机构新仓库：重要度够高，或没有判断分时简介够长，才算有内容；demo 和空简介的降到 Tier2。"""
    imp = (it.get("extra") or {}).get("judge_important")
    solid = imp >= OFFICIAL_DEEP if imp is not None else len(it.get("summary") or "") >= 30
    return ("repo", f"{org} 新开源项目") if solid else ("trending", f"{org} 新仓库，内容信息不足")


def _base(it: dict) -> tuple[str, str] | None:
    src, typ, ex = it["source"], it["type"], it.get("extra") or {}
    pop, imp = it.get("pop_norm") or 0, ex.get("judge_important")
    lab = lab_of(it)
    if lab and typ in ("paper", "blog", "repo") and TECH_REPORT.search(it["title"]):
        return "report", f"{lab} 技术报告"
    if org := rk.official_org(it):
        if src == "github":
            return _org_repo(it, org)
        if imp is not None and imp >= OFFICIAL_DEEP and DEEP_URL.search(it.get("url") or ""):
            return "official", f"{org} 官方研究 / 工程文章，重要度 {imp:.2f}"
        if imp is None or imp >= OFFICIAL_UPDATE:
            return "update", f"{org} 官方更新"
        return None
    if src == "github":
        owner = _owner(it)
        if owner in LAB_GITHUB and (ex.get("watch_org") or ex.get("trending")):
            return _org_repo(it, owner)
        if ex.get("trending") or pop >= 0.7:
            return "trending", "增速快的项目"
        return None
    tier = person_tier(it)
    if tier and depth(it, INTERVIEW_STRICT_S if tier == 1 else INTERVIEW_S):
        return ("person", "名人深度内容") if tier == 1 else ("author", "作者干货")
    if typ == "paper":
        orgs = rk.paper_orgs(it)
        if lab or orgs:
            return "paper", f"{lab or orgs[0]} 论文"
        return ("paper", "热点论文") if pop >= POP_TOP else None
    if typ == "product":
        return ("product", "热点产品") if src in ("producthunt", "yc", "analysis") and pop >= POP_TOP else None
    if src == "hn":
        return ("top", "HN 前列") if pop >= 0.9 else None
    if src == "reddit":
        return ("top", "Reddit 高赞高价值") if pop >= 0.9 and (ex.get("judge_value") or 0) >= 0.7 else None
    if typ == "video":
        return ("top", "视频高价值") if (ex.get("judge_value") or 0) >= 0.7 else None
    if src == "blog" and (imp is None or imp >= OFFICIAL_UPDATE):
        return "author", "博客深度文章"
    if typ == "podcast":
        return "top", "播客新一期"
    if src == "twitter":
        if ex.get("article_title") and pop >= 0.3:
            return "author", "X 深度长文"
        if depth(it) and pop >= POP_TOP:
            return "author", "作者干货"
    return None


def classify(it: dict, interests: dict[str, list[str]] = INTEREST_LINES) -> dict:
    base = _base(it)
    hit = interest_hit(it, interests)
    boosted = False
    if base is None:
        base = ("interest", f"命中兴趣：{hit}") if hit else None
    elif hit and CATS[base[0]][0] == 2 and long_form(it):
        boosted = True
    if base is None:
        return {"tier": 3, "cat": "", "why": [], "boosted": False}
    cat, why = base
    tier = 1 if boosted else CATS[cat][0]
    return {"tier": tier, "cat": cat, "why": [why] + ([f"命中兴趣：{hit}，提到 Tier1"] if boosted else []), "boosted": boosted}
