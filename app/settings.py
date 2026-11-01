"""全局设置：data/settings.json，缺省值在这里。UI 的「设置」页可改。"""
from __future__ import annotations

import copy
import json
import os
import shutil
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .db import DATA_DIR, ROOT

SETTINGS_PATH = DATA_DIR / "settings.json"
ENV_PATH = ROOT / ".env"         # 第三方接口密钥（X / Product Hunt / GitHub …），不进 git
TZ_CACHE = "tz_inferred.json"   # 设置里 timezone 留空时，按作息推断的时区（app/modules/_tzinfer.py 写）

DEFAULTS: dict = {
    # 人重度干预时间窗（专注时间）；其余时间放可自动跑 / 低干预的任务
    "focus_windows": [{"start": "10:00", "end": "11:40"}, {"start": "13:30", "end": "16:50"}],
    "day_start": "08:30",
    # 你所在的时区（IANA 名，如 Asia/Shanghai）；留空 = 按会话作息自动推断（推断不出 / 和系统一致时跟随系统）。所有「几点 / 哪一天」都按它算：
    # 系统时区和你实际作息不一致时（比如系统是 America/Los_Angeles），专注时间窗、工作时间、日期边界都会整体错位
    "timezone": "",
    "day_end": "23:00",
    # 同一时刻最多并行的自动任务数（Claude Code / Codex 并发度）
    "max_agent_concurrency": 3,
    # 规划排好的自动任务（auto + Claude/Codex）到开始时间、依赖完成后自动派发，不用人点
    "plan_auto_dispatch": True,
    # 起后台任务前看机器：1 分钟负载 / CPU 核数超过它、或可用内存低于它（GB）就继续排队
    "job_guard": {"max_load_per_cpu": 0.9, "min_free_mem_gb": 4},
    "engines": {
        "default": "claude",            # claude / codex
        "claude": {
            # reclaude = 绑定了本机账号的 Claude Code 启动器（参数与 claude 一致），没有就用 claude
            "bin": "reclaude" if shutil.which("reclaude") else "claude",
            "model": "",
            "permission_mode": "acceptEdits",
            "allowed_tools": [
                "Read", "Glob", "Grep", "Write", "Edit", "WebSearch", "WebFetch",
                "Bash(curl:*)", "Bash(git:*)", "Bash(ls:*)", "Bash(cat:*)", "Bash(python3:*)", "Bash(uv:*)",
            ],
        },
        # proxy：只给 Codex 用的代理，如 "http://127.0.0.1:12001"；空 = 直连；代理端口没开时自动直连
        "codex": {"bin": "codex", "model": "", "sandbox": "workspace-write", "proxy": ""},
        # 调研引擎：GrokBot 走 codex skill 里的 webhook 脚本；Muse 无 CLI，走「复制 brief → 打开网页版（mode=app 时开桌面 App）→ 粘贴结果」
        # app_data：Grok Bot 桌面版聊天记录目录，回传没到本机时从这里按 request_id 取回答（留空用默认位置）
        "grokbot": {"script": str(Path.home() / ".codex/skills/grokbot-webhook/scripts/grokbot.py"), "app_data": ""},
        # mode：auto = 用 Playwright 驱动本机 Chrome 自动提问取回答（首次在弹出窗口登录）；web / app = 只复制提问并打开，手动粘贴
        # selectors（可选）：页面改版时覆盖 input / send / stop / answer 选择器
        "muse": {"mode": "auto", "url": "https://muse.ai", "app": "Muse"},
    },
    # 按板块指定 Claude 模型（后台任务和对话都生效；空 / 不写 = 用 engines.claude.model）
    "module_models": {"learn": "claude-sonnet-5-5"},
    # 学习习惯：每天自动加一个「读前沿论文」学习块（规划页打开今天时加；在信息推荐的论文上写一句话判断即完成）
    "habits": {"paper_task": True, "paper_minutes": 30, "paper_per_day": 2},
    # 复盘时分析的代码库 / 文档目录
    "repos": [],
    # Claude Code / Codex 会话日志位置（效率复盘）
    "session_dirs": {
        "claude": [str(Path.home() / ".claude/projects"), str(Path.home() / ".rec/claude/accounts/53616/config/projects")],
        "codex": [str(Path.home() / ".codex/sessions")],
    },
    # 信息收集
    "feed": {
        "interests": ["agent", "llm", "claude code", "codex", "reasoning", "rl", "eval", "coding agent", "mcp"],
        # 博客 RSS：厂商官方 + 研究机构 + 一线实践者 + 中文媒体（名单来自 learn_evolve 的 Tier1/Tier2 编辑审核，只留 AI 相关）。
        # anthropic.com / claude.com / x.ai / Meta AI 没有官方 RSS，用社区镜像（Olshansk/rss-feeds）
        "rss": [
            "https://openai.com/news/rss.xml",
            "https://raw.githubusercontent.com/Olshansk/rss-feeds/main/feeds/feed_anthropic_news.xml",
            "https://raw.githubusercontent.com/Olshansk/rss-feeds/main/feeds/feed_anthropic_engineering.xml",
            "https://raw.githubusercontent.com/Olshansk/rss-feeds/main/feeds/feed_anthropic_research.xml",
            "https://raw.githubusercontent.com/Olshansk/rss-feeds/main/feeds/feed_claude.xml",
            "https://raw.githubusercontent.com/Olshansk/rss-feeds/main/feeds/feed_xainews.xml",
            "https://raw.githubusercontent.com/Olshansk/rss-feeds/main/feeds/feed_meta_ai.xml",
            "https://deepmind.google/blog/rss.xml",
            "https://blog.google/innovation-and-ai/technology/ai/rss/",
            "https://research.google/blog/rss/",
            "https://mistral.ai/rss.xml",
            "https://www.microsoft.com/en-us/research/feed/",
            "https://machinelearning.apple.com/rss.xml",
            "https://developer.nvidia.com/blog/feed/",
            "https://www.amazon.science/index.rss",
            "https://www.together.ai/blog/rss.xml",
            "https://thinkingmachines.ai/blog/index.xml",
            "https://sierra.ai/rss.xml",
            "https://github.blog/ai-and-ml/feed/",
            "https://bair.berkeley.edu/blog/feed.xml",
            "https://huggingface.co/blog/feed.xml",
            "https://simonwillison.net/atom/everything/",
            "https://www.latent.space/feed",
            "https://www.interconnects.ai/feed",
            "https://importai.substack.com/feed",
            "https://www.oneusefulthing.org/feed",
            "https://www.dwarkesh.com/feed",
            "https://www.lennysnewsletter.com/feed",
            "https://hamel.dev/index.xml",
            "https://eugeneyan.com/rss/",
            "https://huyenchip.com/feed.xml",
            "https://borischerny.com/feed.xml",
            "https://magazine.sebastianraschka.com/feed",
            "https://lilianweng.github.io/index.xml",
            "https://www.normaltech.ai/feed",
            "https://www.ben-evans.com/benedictevans?format=rss",
            "https://www.tanayj.com/feed",
            "https://lastweekin.ai/feed",
            "https://the-decoder.com/feed/",
            "https://www.testingcatalog.com/rss/",
            "https://www.technologyreview.com/topic/artificial-intelligence/feed/",
            "https://www.qbitai.com/feed",
        ],
        # 没有 RSS 的官方站：抓列表页里匹配 link_re 的文章链接，再读文章页的标题 / 发布日期 / 简介
        "sites": [
            {"name": "Claude.dev Blog", "url": "https://claude.dev/", "link_re": r"/blog/[a-z0-9][a-z0-9-]+/?"},
            {"name": "ByteDance Seed", "url": "https://seed.bytedance.com/en/research", "link_re": r"/en/blog/[a-z0-9][a-z0-9-]+"},
            {"name": "DeepSeek", "url": "https://deepseek.com/en/news/", "link_re": r"/en/news/[a-z0-9][a-z0-9-]+/?"},
            {"name": "Kimi", "url": "https://www.kimi.com/en/blog/", "link_re": r"/en/blog/[a-z0-9-]+"},
            {"name": "MiniMax", "url": "https://www.minimax.io/blog", "link_re": r"/blog/[a-z0-9-]+"},
            {"name": "Thinking Machines News", "url": "https://thinkingmachines.ai/news/", "link_re": r"/news/[a-z0-9][a-z0-9-]+/?"},
            {"name": "Tencent Newsroom", "url": "https://www.tencent.com/newsroom/",
             "link_re": r"https://www\.tencent\.com/[a-z0-9][a-z0-9-]{20,}/?", "ai_only": True},
        ],
        # 播客 RSS（只取标题 + 节目简介，不转写）
        "podcasts": [
            "https://api.substack.com/feed/podcast/1084089.rss",    # Latent Space
            "https://api.substack.com/feed/podcast/69345.rss",      # Dwarkesh Podcast
            "https://feeds.megaphone.fm/nopriors",                  # No Priors
            "https://anchor.fm/s/1e4a0eac/podcast/rss",             # Machine Learning Street Talk
            "https://feeds.megaphone.fm/MLN2155636147",             # TWIML AI
            "https://api.substack.com/feed/podcast/10845.rss",      # Lenny's Podcast
            "https://changelog.com/practicalai/feed",               # Practical AI
            "https://lexfridman.com/feed/podcast/",                 # Lex Fridman
            "https://rss.art19.com/last-week-in-ai",                # Last Week in AI
            "https://feeds.fireside.fm/sv101/rss",                  # 硅谷101
            "https://feeds.fireside.fm/shengdongjixi/rss",          # 声东击西
        ],
        # YouTube 频道（官方 RSS，带播放数，去掉 Shorts）：只放音频 RSS 里没有的高质量访谈 / 播客频道，
        # Latent Space、Dwarkesh、No Priors、Lenny、Lex 已在上面的播客 RSS 里，不重复
        "youtube": [
            {"name": "Y Combinator", "url": "https://www.youtube.com/feeds/videos.xml?channel_id=UCcefcZRL2oaA_uBNeo5UOWg"},
            {"name": "a16z", "url": "https://www.youtube.com/feeds/videos.xml?channel_id=UC9cn0TuPq4dnbTY-CBsm8XA"},
            {"name": "Sequoia Capital", "url": "https://www.youtube.com/feeds/videos.xml?channel_id=UCWrF0oN6unbXrWsTN7RctTw"},
            {"name": "Every", "url": "https://www.youtube.com/feeds/videos.xml?channel_id=UCjIMtrzxYc0lblGhmOgC_CA"},
            {"name": "Cognitive Revolution", "url": "https://www.youtube.com/feeds/videos.xml?channel_id=UCjNRVMBVI30Sak_p6HRWhIA"},
            {"name": "AI Engineer", "url": "https://www.youtube.com/feeds/videos.xml?channel_id=UCLKPca3kwwd-B59HNr-_lvA"},
            {"name": "20VC", "url": "https://www.youtube.com/feeds/videos.xml?channel_id=UCf0PBRjhf0rF8fWBIxTuoWA"},
        ],
        # 产品分析：投资机构 / 孵化器的分析文章 RSS（进「产品」分类；YC 的产品发布另由 Launch YC 采集）
        "product_rss": [
            {"name": "a16z", "url": "https://www.a16z.news/feed"},
        ],
        # 小宇宙节目页（直读页面内嵌数据，带播放数；失败时走 rsshub_bases 里的公共 RSSHub）
        "xiaoyuzhou": [
            "https://www.xiaoyuzhoufm.com/podcast/626b46ea9cbbf0451cf5a962",   # 张小珺Jùn｜商业访谈录
            "https://www.xiaoyuzhoufm.com/podcast/60502e253c92d4f62c2a9577",   # 十字路口Crossing
            "https://www.xiaoyuzhoufm.com/podcast/61933ace1b4320461e91fd55",   # 晚点聊 LateTalk
        ],
        "rsshub_bases": ["https://rsshub.ktachibana.party", "https://rsshub.app", "https://hub.slarker.me"],
        # X 账号：learn_evolve 编辑审核的 Tier1（官方 / 研究 / 工程 / 商业），外加几个 Claude Code / Codex 一线账号
        "x_accounts": [
            "OpenAI", "OpenAIDevs", "AnthropicAI", "ClaudeDevs", "GoogleDeepMind", "GoogleAI", "GoogleAIStudio",
            "GoogleResearch", "huggingface", "nvidia", "NVIDIAAI", "NVIDIARobotics", "deepseek_ai", "Alibaba_Qwen",
            "Kimi_Moonshot", "MiniMax_AI", "Zai_org", "MistralAI", "metaai", "AIatMeta", "GeminiApp", "xai",
            "OpenRouter", "lmsysorg", "arena", "ArtificialAnlys", "vllm_project", "ollama", "UnslothAI",
            "karpathy", "_jasonwei", "AlecRad", "ilyasut", "DarioAmodei", "demishassabis", "JeffDean",
            "OriolVinyalsML", "ylecun", "drfeifei", "AndrewYNg", "fchollet", "jeremyphoward", "JustinLin610",
            "Thom_Wolf", "ClementDelangue", "polynoamial", "soumithchintala", "DrJimFan", "natolambert", "rasbt",
            "NeelNanda5", "janleike", "jackclarkSF", "srush_nlp", "tri_dao", "giffmana", "OfirPress", "hardmaru",
            "seb_ruder", "NandoDF", "simonw", "ChipHuyen", "clattner_llvm", "ggerganov", "swyx", "RLanceMartin",
            "goodside", "hwchase17", "jerryjliu0", "mntruell", "steipete", "eugeneyan", "_philschmid", "sama",
            "amasad", "AravSrinivas", "emollick", "dylan522p", "alexandr_wang", "saranormous", "MelMitchell1",
            "RichardMCNgo", "GaryMarcus", "gwern", "ESYudkowsky", "tegmark", "AndrewCritchPhD", "ch402",
            "TrentonBricken",
            "thsottiaux", "trq212", "adocomplete", "gdb", "OfficialLoganK",
        ],
        # X 热帖搜索（高级搜索语法）：补名单外的爆款
        "x_queries": [
            "LLM min_faves:500 -filter:replies lang:en",
            "Claude min_faves:500 -filter:replies lang:en",
            "Codex min_faves:300 -filter:replies lang:en",
            "(\"AI agent\" OR \"coding agent\" OR \"agent harness\") min_faves:300 -filter:replies lang:en",
            # 专搜 X 长文（补完标题后再按 AI 词过滤）
            "url:\"x.com/i/article\" (Claude OR Codex OR LLM OR \"AI agent\" OR \"coding agent\") min_faves:200",
        ],
    },
    # 深度学习：已有的 codex 解析 skill
    "learn": {
        "paper_skill": str(Path.home() / ".codex/skills/paper-library/SKILL.md"),
        "github_skill": str(Path.home() / ".codex/skills/github-code-walkthrough/SKILL.md"),
        "output_dir": str(DATA_DIR / "learn"),
    },
}


def load_env(path: Path = ENV_PATH) -> None:
    """读 .env（KEY=VALUE，# 注释）进 os.environ；已有的环境变量优先，不覆盖。"""
    if not path.exists():
        return
    for line in path.read_text("utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.removeprefix("export ").split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip("'\""))


load_env()


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def load() -> dict:
    over = {}
    if SETTINGS_PATH.exists():
        try:
            over = json.loads(SETTINGS_PATH.read_text("utf-8"))
        except json.JSONDecodeError:
            over = {}
    return _merge(DEFAULTS, over)


def save(new: dict) -> dict:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    new = {k: v for k, v in new.items() if k != "timezone_effective"}
    merged = _merge(load(), new)
    SETTINGS_PATH.write_text(json.dumps(merged, ensure_ascii=False, indent=2), "utf-8")
    apply_timezone()
    return merged


_SYSTEM_TZ = os.environ.get("TZ")


def apply_timezone(tz: str | None = None) -> str:
    """把进程的本地时区设成设置里的 timezone（datetime.now()、日期边界、会话日志时间都跟着变）；
    留空用按作息推断的时区（data/tz_inferred.json），也没有就恢复系统时区。"""
    tz = load().get("timezone", "") if tz is None else tz
    if not tz:
        try:
            tz = json.loads((DATA_DIR / TZ_CACHE).read_text("utf-8")).get("tz", "")
        except (OSError, ValueError):
            tz = ""
    if tz:
        try:
            ZoneInfo(tz)
        except (ZoneInfoNotFoundError, ValueError):
            tz = ""  # 写错了就跟随系统，不要静默变成 UTC
    if tz:
        os.environ["TZ"] = tz
    elif _SYSTEM_TZ is None:
        os.environ.pop("TZ", None)
    else:
        os.environ["TZ"] = _SYSTEM_TZ
    time.tzset()
    return time.tzname[0]


def _system_tz_name() -> str:
    return _SYSTEM_TZ or str(Path("/etc/localtime").resolve()).partition("zoneinfo/")[2]


def effective_tz() -> str:
    """进程当前用的时区名（IANA，如 Etc/GMT-8），给前端按同一时区算「今天」「现在」。"""
    return os.environ.get("TZ") or _system_tz_name()


def system_utc_offset(at: datetime | None = None) -> float:
    """系统时区（不受 apply_timezone 影响）此刻的 UTC 偏移小时。"""
    name = _system_tz_name()
    try:
        z = ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return 0.0
    return (at or datetime.now(z)).astimezone(z).utcoffset().total_seconds() / 3600


def get(path: str, default=None):
    cur = load()
    for p in path.split("."):
        if not isinstance(cur, dict) or p not in cur:
            return default
        cur = cur[p]
    return cur
