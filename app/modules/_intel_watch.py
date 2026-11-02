"""产品雷达的默认关注名单：20 家 T1 / T2 公司 + 各自的官方源。

启动时把库里没有的公司 / 信息源补进去（按 slug / url），不覆盖用户在页面上的修改；
不想跟的公司在页面上关掉（enabled=0），不删。

每家公司两类信号：
- 已由信息推荐采集的官方 blog / X / GitHub：按 domains / feed_urls / x / github 从 feed_items 里认领，不重复抓；
- 这里列的 sources：changelog / 定价页 / 文档 / 专属 RSS，产品雷达自己定时快照。
  kind：changelog（文本 diff 出新增条目）、pricing（结构化 + diff）、docs（只存快照，P1 不出事件）、rss（RSS/Atom 条目）。
"""
from __future__ import annotations

# tier：1 = 大公司 / 头部模型厂，2 = 明星 AI native 产品公司（3 = 观察中的 startup，P1 不默认配）
COMPANIES: list[dict] = [
    {"slug": "openai", "name": "OpenAI", "tier": 1, "category": "模型 / 通用助手",
     "aliases": ["OpenAI", "ChatGPT", "GPT-5", "Codex", "Sora", "o3", "o4"],
     "domains": ["openai.com", "chatgpt.com"], "x": ["OpenAI", "OpenAIDevs", "sama"], "github": ["openai"],
     "feed_urls": ["https://openai.com/news/rss.xml"],
     "sources": [
         {"kind": "changelog", "label": "API Changelog", "product": "OpenAI API", "url": "https://platform.openai.com/docs/changelog"},
         {"kind": "rss", "label": "Codex CLI releases", "product": "Codex", "url": "https://github.com/openai/codex/releases.atom"},
         {"kind": "changelog", "label": "ChatGPT release notes", "product": "ChatGPT",
          "url": "https://help.openai.com/en/articles/6825453-chatgpt-release-notes", "note": "直连 403，需浏览器 / 人工"},
         {"kind": "pricing", "label": "ChatGPT 定价", "product": "ChatGPT", "url": "https://openai.com/chatgpt/pricing/",
          "note": "直连 403，需浏览器 / 人工"},
     ]},
    {"slug": "anthropic", "name": "Anthropic", "tier": 1, "category": "模型 / 编码 Agent",
     "aliases": ["Anthropic", "Claude", "Claude Code", "Opus", "Sonnet", "Haiku", "Fable"],
     "domains": ["anthropic.com", "claude.com", "claude.ai", "claude.dev"], "x": ["AnthropicAI", "ClaudeDevs", "claudeai"],
     "github": ["anthropics"],
     "feed_urls": ["https://raw.githubusercontent.com/Olshansk/rss-feeds/main/feeds/feed_anthropic_news.xml",
                   "https://raw.githubusercontent.com/Olshansk/rss-feeds/main/feeds/feed_anthropic_engineering.xml",
                   "https://raw.githubusercontent.com/Olshansk/rss-feeds/main/feeds/feed_claude.xml"],
     "sources": [
         {"kind": "changelog", "label": "Claude 应用 release notes", "product": "Claude",
          "url": "https://support.claude.com/en/articles/12138966-release-notes"},
         {"kind": "changelog", "label": "Claude Code CHANGELOG", "product": "Claude Code",
          "url": "https://raw.githubusercontent.com/anthropics/claude-code/main/CHANGELOG.md"},
         {"kind": "pricing", "label": "Claude 定价", "product": "Claude", "url": "https://claude.com/pricing"},
     ]},
    {"slug": "google", "name": "Google / DeepMind", "tier": 1, "category": "模型 / 通用助手",
     "aliases": ["Gemini", "DeepMind", "NotebookLM", "Veo", "Imagen", "Jules", "AI Studio", "Gemini CLI"],
     "domains": ["deepmind.google", "blog.google", "ai.google.dev", "gemini.google"], "x": ["GoogleDeepMind", "GeminiApp", "GoogleAIStudio"],
     "github": ["google-gemini", "google-deepmind"],
     "feed_urls": ["https://deepmind.google/blog/rss.xml", "https://blog.google/innovation-and-ai/technology/ai/rss/"],
     "sources": [
         {"kind": "changelog", "label": "Gemini API changelog", "product": "Gemini API", "url": "https://ai.google.dev/gemini-api/docs/changelog"},
         {"kind": "rss", "label": "Gemini CLI releases", "product": "Gemini CLI", "url": "https://github.com/google-gemini/gemini-cli/releases.atom"},
         {"kind": "pricing", "label": "Gemini API 定价", "product": "Gemini API", "url": "https://ai.google.dev/gemini-api/docs/pricing"},
     ]},
    {"slug": "microsoft-github", "name": "GitHub Copilot", "tier": 1, "category": "编码 Agent",
     "aliases": ["GitHub Copilot", "Copilot coding agent", "Copilot"],
     "domains": ["github.blog"], "x": ["GitHubCopilot"], "github": [],
     "feed_urls": ["https://github.blog/ai-and-ml/feed/"],
     "sources": [
         {"kind": "rss", "label": "GitHub Changelog · Copilot", "product": "GitHub Copilot",
          "url": "https://github.blog/changelog/label/copilot/feed/"},
     ]},
    {"slug": "xai", "name": "xAI", "tier": 1, "category": "模型",
     "aliases": ["xAI", "Grok"], "domains": ["x.ai"], "x": ["xai", "grok"], "github": ["xai-org"],
     "feed_urls": ["https://raw.githubusercontent.com/Olshansk/rss-feeds/main/feeds/feed_xainews.xml"],
     "sources": [
         {"kind": "changelog", "label": "xAI API release notes", "product": "Grok API", "url": "https://docs.x.ai/docs/release-notes"},
     ]},
    {"slug": "meta", "name": "Meta AI", "tier": 1, "category": "模型 / 开源",
     "aliases": ["Meta AI", "Llama"], "domains": ["ai.meta.com"], "x": ["AIatMeta"], "github": ["meta-llama", "facebookresearch"],
     "feed_urls": ["https://raw.githubusercontent.com/Olshansk/rss-feeds/main/feeds/feed_meta_ai.xml"], "sources": []},
    {"slug": "deepseek", "name": "DeepSeek", "tier": 1, "category": "模型 / 开源",
     "aliases": ["DeepSeek"], "domains": ["deepseek.com", "api-docs.deepseek.com"], "x": ["deepseek_ai"], "github": ["deepseek-ai"],
     "feed_urls": [],
     "sources": [
         {"kind": "changelog", "label": "API 更新日志", "product": "DeepSeek API", "url": "https://api-docs.deepseek.com/updates"},
         {"kind": "pricing", "label": "API 定价", "product": "DeepSeek API", "url": "https://api-docs.deepseek.com/quick_start/pricing"},
     ]},
    {"slug": "qwen", "name": "阿里 Qwen", "tier": 1, "category": "模型 / 开源",
     "aliases": ["Qwen", "通义", "Qwen Code"], "domains": ["qwenlm.github.io", "qwen.ai"], "x": ["Alibaba_Qwen"], "github": ["QwenLM"],
     "feed_urls": [],
     "sources": [{"kind": "rss", "label": "Qwen blog", "product": "Qwen", "url": "https://qwenlm.github.io/blog/index.xml"}]},
    {"slug": "moonshot", "name": "月之暗面 Kimi", "tier": 1, "category": "模型 / 通用助手",
     "aliases": ["Kimi", "Moonshot", "月之暗面"], "domains": ["kimi.com", "moonshot.ai", "moonshot.cn"], "x": ["Kimi_Moonshot"],
     "github": ["MoonshotAI"], "feed_urls": [],
     "sources": [
         {"kind": "pricing", "label": "API 定价", "product": "Kimi API", "url": "https://platform.moonshot.ai/docs/pricing/chat"},
     ]},
    {"slug": "mistral", "name": "Mistral", "tier": 1, "category": "模型 / 开源",
     "aliases": ["Mistral", "Le Chat", "Codestral", "Devstral"], "domains": ["mistral.ai"], "x": ["MistralAI"], "github": ["mistralai"],
     "feed_urls": ["https://mistral.ai/rss.xml"],
     "sources": [{"kind": "changelog", "label": "Docs changelog", "product": "Mistral API",
                  "url": "https://docs.mistral.ai/getting-started/changelog"}]},
    {"slug": "cursor", "name": "Cursor", "tier": 2, "category": "编码 Agent",
     "aliases": ["Cursor", "Anysphere"], "domains": ["cursor.com"], "x": ["cursor_ai", "mntruell"], "github": ["getcursor"],
     "feed_urls": [],
     "sources": [
         {"kind": "changelog", "label": "Changelog", "product": "Cursor", "url": "https://cursor.com/changelog"},
         {"kind": "pricing", "label": "定价", "product": "Cursor", "url": "https://cursor.com/pricing"},
     ]},
    {"slug": "cognition", "name": "Cognition（Devin / Windsurf）", "tier": 2, "category": "编码 Agent",
     "aliases": ["Cognition", "Devin", "Windsurf"], "domains": ["cognition.ai", "devin.ai", "windsurf.com"], "x": ["cognition", "windsurf"],
     "github": [], "feed_urls": [],
     "sources": [
         {"kind": "changelog", "label": "Devin release notes", "product": "Devin", "url": "https://docs.devin.ai/release-notes/overview"},
         {"kind": "changelog", "label": "Windsurf changelog", "product": "Windsurf", "url": "https://windsurf.com/changelog"},
     ]},
    {"slug": "replit", "name": "Replit", "tier": 2, "category": "应用生成 / Vibe coding",
     "aliases": ["Replit", "Replit Agent"], "domains": ["replit.com", "blog.replit.com"], "x": ["Replit", "amasad"], "github": ["replit"],
     "feed_urls": [],
     "sources": [{"kind": "changelog", "label": "Docs updates", "product": "Replit", "url": "https://docs.replit.com/updates"}]},
    {"slug": "lovable", "name": "Lovable", "tier": 2, "category": "应用生成 / Vibe coding",
     "aliases": ["Lovable"], "domains": ["lovable.dev"], "x": ["lovable_dev", "antonosika"], "github": [], "feed_urls": [],
     "sources": [
         {"kind": "changelog", "label": "Changelog", "product": "Lovable", "url": "https://docs.lovable.dev/changelog"},
         {"kind": "pricing", "label": "定价", "product": "Lovable", "url": "https://lovable.dev/pricing"},
     ]},
    {"slug": "perplexity", "name": "Perplexity", "tier": 2, "category": "搜索 / 浏览器 Agent",
     "aliases": ["Perplexity", "Comet", "Sonar"], "domains": ["perplexity.ai"], "x": ["perplexity_ai", "AravSrinivas"], "github": [],
     "feed_urls": [],
     "sources": [{"kind": "changelog", "label": "API changelog", "product": "Sonar API",
                  "url": "https://docs.perplexity.ai/changelog/changelog"}]},
    {"slug": "manus", "name": "Manus", "tier": 2, "category": "通用 Agent",
     "aliases": ["Manus"], "domains": ["manus.im"], "x": ["ManusAI_HQ"], "github": [], "feed_urls": [],
     "sources": [{"kind": "changelog", "label": "Blog", "product": "Manus", "url": "https://manus.im/blog"}]},
    {"slug": "minimax", "name": "MiniMax", "tier": 2, "category": "模型 / 多模态",
     "aliases": ["MiniMax", "海螺", "Hailuo"], "domains": ["minimax.io", "minimaxi.com"], "x": ["MiniMax__AI"], "github": ["MiniMax-AI"],
     "feed_urls": [], "sources": []},
    {"slug": "elevenlabs", "name": "ElevenLabs", "tier": 2, "category": "语音",
     "aliases": ["ElevenLabs"], "domains": ["elevenlabs.io"], "x": ["elevenlabsio"], "github": [], "feed_urls": [],
     "sources": [{"kind": "pricing", "label": "定价", "product": "ElevenLabs", "url": "https://elevenlabs.io/pricing"}]},
    {"slug": "midjourney", "name": "Midjourney", "tier": 2, "category": "图像 / 视频生成",
     "aliases": ["Midjourney"], "domains": ["midjourney.com"], "x": ["midjourney"], "github": [], "feed_urls": [],
     "sources": [{"kind": "changelog", "label": "Updates", "product": "Midjourney", "url": "https://updates.midjourney.com/"}]},
    {"slug": "suno", "name": "Suno", "tier": 2, "category": "音乐生成",
     "aliases": ["Suno"], "domains": ["suno.com"], "x": ["SunoMusic"], "github": [], "feed_urls": [],
     "sources": [{"kind": "changelog", "label": "Blog", "product": "Suno", "url": "https://suno.com/blog"}]},
]

EVERY_HOURS = {"changelog": 6, "rss": 6, "pricing": 24, "docs": 24}
