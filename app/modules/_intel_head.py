"""头部 AI 产品名单：只入库不监控（无信息源），供需求图谱按产品雷达公司库提炼。名单来自常见榜单的头部产品（a16z Top 100 / 流量榜同类），每季度对一次。"""
import html
import re

import httpx

AICPB = "https://aicpb.com/ai-rankings/products/"
PAGES = {
    "ai-agent-rankings": ("个人 Agent", "AI Agent 榜"), "ai-character-rankings": ("陪伴 / 角色对话", "AI 角色榜"), "ai-chatbot-rankings": ("模型 / 通用助手", "AI 聊天机器人榜"),
    "ai-image-editor-rankings": ("图像 / 视频生成", "AI 图像编辑榜"), "ai-image-generator-rankings": ("图像 / 视频生成", "AI 图像生成榜"),
    "ai-meeting-assistant-rankings": ("办公 / 生产力", "AI 会议助手榜"), "ai-music-generator-rankings": ("音乐 / 语音", "AI 音乐生成榜"), "ai-ppt-rankings": ("办公 / 生产力", "AI PPT 榜"),
    "ai-search-rankings": ("搜索 / 研究", "AI 搜索榜"), "ai-video-editing-rankings": ("图像 / 视频生成", "AI 视频剪辑榜"), "ai-video-generators-rankings": ("图像 / 视频生成", "AI 视频生成榜"),
    "vibe-coding-rankings": ("编程 / Agent", "AI 编程榜"), "openclaw-agent": ("个人 Agent", "Claw Agent 榜"), "china-ai-rankings": ("模型 / 通用助手", "国内 AI 榜"),
    "global-ai-rankings": ("模型 / 通用助手", "全球 AI 榜"), "china-ai-growth-rate-ranking": ("模型 / 通用助手", "国内 AI 增速榜"), "ai-global-growth-rate-ranking": ("模型 / 通用助手", "全球 AI 增速榜"),
    "claw-agent-growth-rate": ("个人 Agent", "Claw Agent 增速榜"),
}
DROP = {"shop", "百度网盘", "ai 搜索", "hostinger", "airtable", "supabase", "vercel", "ollama", "media", "z", "cal", "beautiful", "loom", "mentimeter", "阿里云", "腾讯云", "火山引擎", "讯飞开放平台", "硅基流动", "百度智能云", "百度文库"}
ALIAS = {"chatgpt", "new bing", "newbing", "copilot", "bing", "google gemini", "claude by anthropic", "kimi", "qwen", "千问", "runwayml", "openart", "klingai", "kling ai", "dreamina", "you", "fireflies", "opus clip ai", "maxai", "github copilot"}


def key(name: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", name.lower())


def short(k: str) -> str:
    return re.sub(r"(ai|app|io|com|cn)$", "", k)


def vol(v: str) -> float:
    m = re.match(r"^([\d.]+)([KMB]?)$", v)
    return float(m.group(1)) * {"": 1, "K": 1e3, "M": 1e6, "B": 1e9}[m.group(2)] if m else 0.0


MIN_VISITS = 2.5e6


def clean(name: str) -> str:
    n = re.split(r"[｜|]", name)[0]
    return re.split(r" - |：|:\s|-阿里|-昆仑|-美图|-豆包|-「", n)[0].strip()


def fetch_rows(client: httpx.Client | None = None) -> list[dict]:
    """AICPB 各品类榜单（国内榜、增速榜能先看到新进榜的产品）→ [{name, cat, rank, visits, list}]。榜单页没有反爬，抓不到的页跳过。"""
    own = client is None
    client = client or httpx.Client(timeout=30, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"})
    out, seen = [], set()
    try:
        for page, (cat, label) in PAGES.items():
            try:
                t = client.get(AICPB + page).text
            except httpx.HTTPError:
                continue
            t = re.sub(r"<script.*?</script>|<style.*?</style>", "", t, flags=re.S)
            L = [x.strip() for x in html.unescape(re.sub(r"<[^>]+>", "\n", t)).split("\n") if x.strip()]
            for i in range(len(L) - 3):
                if L[i].isdigit() and re.match(r"^[\d.]+[KMB]?$", L[i + 2]) and re.match(r"^-?[\d.]+%$", L[i + 3]):
                    name = clean(L[i + 1])
                    k = key(name)
                    if name and vol(L[i + 2]) >= MIN_VISITS and k not in seen and k not in DROP and name.lower() not in DROP and k not in {key(a) for a in ALIAS}:
                        seen.add(k)
                        out.append({"name": name, "cat": cat, "rank": int(L[i]), "visits": L[i + 2], "list": label})
    finally:
        if own:
            client.close()
    return out


HEAD: list[tuple[str, str, str]] = [
    ("Character.AI", "陪伴 / 角色对话", "角色扮演和虚拟陪伴聊天，用户自建角色，年轻用户占比高。"),
    ("Replika", "陪伴 / 角色对话", "AI 陪伴聊天，主打情感支持，订阅制。"),
    ("Talkie", "陪伴 / 角色对话", "角色聊天和互动故事，MiniMax 旗下海外产品。"),
    ("豆包", "模型 / 通用助手", "字节跳动的通用 AI 助手，国内月活最高的 AI 应用之一。"),
    ("腾讯元宝", "模型 / 通用助手", "腾讯的通用 AI 助手，接入微信生态和混元、DeepSeek 模型。"),
    ("文心一言", "模型 / 通用助手", "百度的通用 AI 助手，接入搜索和文库。"),
    ("通义", "模型 / 通用助手", "阿里的通用 AI 助手和办公助手。"),
    ("Poe", "模型 / 通用助手", "Quora 的多模型聚合聊天平台，可创建和分享 bot。"),
    ("Microsoft Copilot", "模型 / 通用助手", "微软的 AI 助手，嵌入 Windows、Edge 和 Microsoft 365。"),
    ("Gemini", "模型 / 通用助手", "Google 的通用 AI 助手，接入 Workspace 和 Android。"),
    ("Grok", "模型 / 通用助手", "xAI 的聊天助手，与 X 平台深度结合。"),
    ("You.com", "搜索 / 研究", "AI 搜索和研究助手，面向个人和企业。"),
    ("Genspark", "搜索 / 研究", "AI 搜索和通用 Agent，自动生成页面与报告。"),
    ("秘塔 AI 搜索", "搜索 / 研究", "国内 AI 搜索，无广告，强调研究型检索。"),
    ("NotebookLM", "搜索 / 研究", "Google 的资料问答与播客式音频概览工具。"),
    ("Elicit", "搜索 / 研究", "面向科研的文献检索和综述工具。"),
    ("Consensus", "搜索 / 研究", "基于论文的科研问答搜索引擎。"),
    ("Notion AI", "办公 / 生产力", "Notion 内置的写作、问答和数据库自动填充。"),
    ("Gamma", "办公 / 生产力", "AI 生成演示文稿、文档和网页。"),
    ("Granola", "办公 / 生产力", "AI 会议笔记，不进会议室也能记录并整理。"),
    ("Otter.ai", "办公 / 生产力", "会议转写和纪要，团队订阅。"),
    ("Fireflies.ai", "办公 / 生产力", "会议录音、转写和 CRM 同步。"),
    ("Superhuman", "办公 / 生产力", "高端邮箱，加入 AI 写信和分流。"),
    ("Zapier", "办公 / 生产力", "自动化平台，加入 AI Agent 和工作流生成。"),
    ("Glean", "办公 / 生产力", "企业内部搜索和工作助手，对接各类 SaaS。"),
    ("Grammarly", "写作", "写作纠错和改写助手，加入生成式 AI 与 Agent。"),
    ("Jasper", "写作", "营销文案生成，面向企业品牌团队。"),
    ("Copy.ai", "写作", "营销和销售文案生成与工作流。"),
    ("Writer", "写作", "企业级生成式 AI 平台，强调品牌和合规。"),
    ("Sudowrite", "写作", "面向小说作者的创作助手。"),
    ("QuillBot", "写作", "改写、摘要和语法检查工具。"),
    ("Turnitin", "教育", "学术抄袭与 AI 写作检测。"),
    ("Duolingo", "教育", "语言学习应用，加入 AI 对话和视频通话练习。"),
    ("Speak", "教育", "AI 口语陪练应用。"),
    ("Khanmigo", "教育", "可汗学院的 AI 辅导助手。"),
    ("Photomath", "教育", "拍照解数学题并给出步骤。"),
    ("Brainly", "教育", "学生互助问答，加入 AI 解题。"),
    ("作业帮", "教育", "国内作业辅导应用，加入 AI 解题和学习机。"),
    ("Canva", "设计", "在线设计平台，加入 Magic Studio 与 AI 设计功能。"),
    ("Figma", "设计", "协作设计工具，加入 Make 等 AI 设计与原型功能。"),
    ("Adobe Firefly", "设计", "Adobe 的生成式图像、视频和设计模型及应用。"),
    ("Leonardo.ai", "图像 / 视频生成", "图像生成平台，面向游戏和设计素材。"),
    ("Ideogram", "图像 / 视频生成", "擅长文字排版的图像生成。"),
    ("Krea", "图像 / 视频生成", "实时图像生成和多模型创作平台。"),
    ("Runway", "图像 / 视频生成", "AI 视频生成和编辑工具，面向影视创作者。"),
    ("Pika", "图像 / 视频生成", "文生视频和图生视频的消费级应用。"),
    ("Luma AI", "图像 / 视频生成", "Dream Machine 视频生成与 3D 捕捉。"),
    ("可灵", "图像 / 视频生成", "快手的视频生成模型和应用。"),
    ("即梦", "图像 / 视频生成", "字节的图像和视频生成创作平台。"),
    ("海螺 AI", "图像 / 视频生成", "MiniMax 的视频和对话应用。"),
    ("HeyGen", "图像 / 视频生成", "数字人视频和多语言配音。"),
    ("Synthesia", "图像 / 视频生成", "企业培训用数字人视频。"),
    ("CapCut", "图像 / 视频生成", "字节的视频剪辑应用，加入大量 AI 功能。"),
    ("Descript", "图像 / 视频生成", "通过改文字来剪辑音视频。"),
    ("OpusClip", "图像 / 视频生成", "长视频自动剪成短视频。"),
    ("Lensa", "图像 / 视频生成", "AI 头像和照片美化应用。"),
    ("Remini", "图像 / 视频生成", "照片修复和增强应用。"),
    ("Udio", "音乐 / 语音", "文生音乐平台。"),
    ("Murf", "音乐 / 语音", "文字转语音和配音。"),
    ("Speechify", "音乐 / 语音", "文字转语音阅读器。"),
    ("Cartesia", "音乐 / 语音", "低延迟语音合成和语音 Agent 基础设施。"),
    ("Vapi", "音乐 / 语音", "语音 Agent 开发平台。"),
    ("Bolt.new", "编程 / Agent", "StackBlitz 的浏览器内 AI 全栈应用生成。"),
    ("v0", "编程 / Agent", "Vercel 的界面和应用生成工具。"),
    ("Cline", "编程 / Agent", "开源 VS Code 编程 Agent 插件。"),
    ("Tabnine", "编程 / Agent", "代码补全，强调私有部署与合规。"),
    ("Codeium", "编程 / Agent", "代码补全和助手，后转型为 Windsurf。"),
    ("JetBrains AI", "编程 / Agent", "JetBrains IDE 内的 AI 助手和 Junie Agent。"),
    ("Sourcegraph Amp", "编程 / Agent", "Sourcegraph 的编程 Agent。"),
    ("Warp", "编程 / Agent", "带 AI 的终端和 Agent 环境。"),
    ("Hugging Face", "编程 / Agent", "模型和数据集托管社区，开发者首选入口。"),
    ("Hebbia", "金融 / 法律 / 专业", "面向金融机构的文档分析 Agent。"),
    ("Harvey", "金融 / 法律 / 专业", "面向律所的法律 AI 助手。"),
    ("Abridge", "金融 / 法律 / 专业", "医生看诊对话自动生成病历。"),
    ("OpenEvidence", "金融 / 法律 / 专业", "面向医生的循证医学问答。"),
    ("Hippocratic AI", "金融 / 法律 / 专业", "面向医疗场景的对话 Agent。"),
    ("Sierra", "客服 / 销售", "企业客服 Agent 平台。"),
    ("Decagon", "客服 / 销售", "面向消费品牌的客服 Agent。"),
    ("Intercom Fin", "客服 / 销售", "Intercom 的客服 AI Agent，按解决量收费。"),
    ("Clay", "客服 / 销售", "销售线索数据整合和 AI 外联。"),
    ("11x", "客服 / 销售", "AI 销售员 Alice 和 Julian。"),
    ("Scale AI", "数据 / 基础设施", "数据标注和评测服务，模型厂商的数据供应商。"),
    ("Databricks", "数据 / 基础设施", "数据与 AI 平台，含模型训练和 Agent 构建。"),
    ("Pinecone", "数据 / 基础设施", "向量数据库。"),
    ("LangChain", "数据 / 基础设施", "LLM 应用开发框架与 LangSmith 观测平台。"),
    ("Together AI", "数据 / 基础设施", "开源模型推理和训练云。"),
    ("Cohere", "数据 / 基础设施", "面向企业的大模型和检索产品。"),
    ("Pi", "陪伴 / 角色对话", "Inflection 的个人 AI 助手。"),
    ("Snapchat My AI", "陪伴 / 角色对话", "Snapchat 内置的聊天助手。"),
    ("Meitu", "图像 / 视频生成", "美图系应用，大量 AI 修图和设计功能。"),
    ("Pixverse", "图像 / 视频生成", "文生视频应用，社交传播强。"),
    ("Augment Code", "编程 / Agent", "面向大型代码库的企业级编程助手和 Agent。"),
    ("Qodo", "编程 / Agent", "代码审查和测试生成，强调代码质量。"),
    ("Base44", "编程 / Agent", "用自然语言生成完整应用，已被 Wix 收购。"),
    ("OpenRouter", "数据 / 基础设施", "统一接入多家模型的 API 路由和聚合平台。"),
    ("智谱清言", "模型 / 通用助手", "智谱 AI 的通用助手，背后是 GLM 系列模型。"),
    ("百川智能", "模型 / 通用助手", "国内大模型公司，产品偏医疗和通用助手。"),
    ("阶跃星辰", "模型 / 通用助手", "国内大模型公司，有跃问助手和多模态模型。"),
    ("扣子 Coze", "编程 / Agent", "字节的 Agent 和工作流搭建平台，可发布到多个渠道。"),
    ("Ambience Healthcare", "金融 / 法律 / 专业", "医疗场景的病历记录和编码 AI。"),
    ("Tempus AI", "金融 / 法律 / 专业", "用临床和分子数据做精准医疗的 AI 公司。"),
    ("Cresta", "客服 / 销售", "为客服座席提供实时辅助和培训的 AI。"),
    ("Forethought", "客服 / 销售", "客服 AI Agent 和工单分流。"),
    ("Moveworks", "客服 / 销售", "企业内部员工支持 AI 助手，已被 ServiceNow 收购。"),
    ("Gong", "客服 / 销售", "销售通话录音分析和收入情报平台。"),
    ("Apollo.io", "客服 / 销售", "销售线索数据库和外联自动化，加入 AI 功能。"),
    ("Salesforce Agentforce", "客服 / 销售", "Salesforce 的企业 Agent 平台。"),
    ("HubSpot Breeze", "客服 / 销售", "HubSpot 内置的营销、销售和客服 AI。"),
    ("Captions", "图像 / 视频生成", "面向创作者的 AI 视频字幕和口播剪辑应用。"),
    ("VEED", "图像 / 视频生成", "在线视频编辑器，加入 AI 字幕和数字人。"),
    ("Hedra", "图像 / 视频生成", "让角色开口说话的视频生成工具。"),
    ("Higgsfield", "图像 / 视频生成", "面向社交内容的视频生成与镜头控制应用。"),
    ("Lovart", "设计", "AI 设计 Agent，从一句话生成完整设计稿。"),
    ("Hume AI", "音乐 / 语音", "能感知情绪的语音模型和对话接口。"),
    ("Synthflow", "音乐 / 语音", "无代码搭建语音 Agent，用于客服和销售外呼。"),
    ("Bland AI", "音乐 / 语音", "AI 电话外呼和接听 Agent。"),
    ("Typeface", "写作", "企业品牌营销内容生成平台。"),
    ("Kajabi", "教育", "知识付费和课程平台，加入 AI 内容生成。"),
    ("ChatGPT Agent", "个人 Agent", "OpenAI 的通用任务 Agent，能操作浏览器和文件完成多步任务。"),
    ("Claude Cowork", "个人 Agent", "Anthropic 面向非开发者的桌面任务 Agent，可处理本地文件。"),
    ("Lindy", "个人 Agent", "无代码搭建个人和团队 AI 助理，处理邮件日程等。"),
    ("Relevance AI", "个人 Agent", "搭建 AI 员工和多 Agent 工作流的平台。"),
    ("Poke", "个人 Agent", "通过短信和聊天窗口使用的个人 AI 助理。"),
    ("Perplexity Comet", "个人 Agent", "Perplexity 的 AI 浏览器，可替用户执行网页任务。"),
    ("Dia", "个人 Agent", "The Browser Company 的 AI 浏览器，把对话放进标签页。"),
    ("Fellou", "个人 Agent", "主打 Agent 的 AI 浏览器，自动执行网页多步操作。"),
    ("Open Interpreter", "个人 Agent", "开源项目，让大模型在本机执行代码完成任务。"),
    ("OpenClaw", "个人 Agent", "开源个人 AI 助理，常驻本机并通过聊天软件操控。"),
    ("Limitless", "个人 Agent", "原 Rewind，随身录音和个人记忆助手。"),
    ("Plaud", "个人 Agent", "AI 录音卡片，自动转写和总结对话。"),
    ("Bee", "个人 Agent", "可穿戴 AI 助手，记录日常对话并生成待办。"),
    ("Rabbit", "个人 Agent", "r1 掌上设备和 Rabbit OS 的个人 Agent。"),
    ("Humane", "个人 Agent", "AI Pin 可穿戴设备，后被 HP 收购。"),
    ("Friend", "个人 Agent", "挂在脖子上的 AI 陪伴设备。"),
    ("Motion", "个人 Agent", "AI 自动排期的日程和任务管理工具。"),
    ("Reclaim.ai", "个人 Agent", "自动安排日程和任务时间的 AI 日历助手。"),
    ("Shortwave", "个人 Agent", "AI 邮箱，内置助手帮写信和整理收件箱。"),
    ("Sider", "个人 Agent", "浏览器侧边栏 AI 助手，支持多模型。"),
    ("Apple Intelligence", "个人 Agent", "苹果的系统级 AI，加入 Siri 与应用间的个人上下文。"),
    ("荣耀 YOYO", "个人 Agent", "荣耀手机的系统级智能体，可跨应用操作。"),
    ("豆包手机助手", "个人 Agent", "字节与手机厂商合作的系统级手机 Agent。"),
    ("智谱 AutoGLM", "个人 Agent", "智谱的手机和网页操作 Agent。"),
    ("Kimi OK Computer", "个人 Agent", "月之暗面的通用 Agent 模式，可生成网站和报告。"),
    ("Picsart", "图像 / 视频生成", "AICPB 2026-06 AI 图像生成榜第 2 名，月访问约 17.94M。"),
    ("SeaArt", "图像 / 视频生成", "AICPB 2026-06 AI 图像生成榜第 3 名，月访问约 17.77M。"),
    ("PixAI.Art", "图像 / 视频生成", "AICPB 2026-06 AI 图像生成榜第 6 名，月访问约 10.16M。"),
    ("Civitai", "图像 / 视频生成", "AICPB 2026-06 AI 图像生成榜第 8 名，月访问约 6.88M。"),
    ("Freepik AI image generator", "图像 / 视频生成", "AICPB 2026-06 AI 图像生成榜第 9 名，月访问约 5.79M。"),
    ("夸克", "模型 / 通用助手", "AICPB 2026-06 全球 AI 榜第 5 名，月访问约 159.24M。"),
    ("Dola", "模型 / 通用助手", "AICPB 2026-06 全球 AI 榜第 10 名，月访问约 79.36M。"),
    ("千问 qianwen.com", "模型 / 通用助手", "AICPB 2026-06 AI 聊天机器人榜第 9 名，月访问约 44.53M。"),
    ("纳米AI", "综合", "AICPB 2026-06 AI 应用榜第 10 名，月访问约 8.08M。"),
    ("Seekee", "综合", "AICPB 2026-06 AI 应用榜第 9 名，月访问约 27.13M。"),
    ("Claude by Anthropic", "综合", "AICPB 2026-06 AI 应用榜第 10 名，月访问约 39.81M。"),
    ("Gauth", "综合", "AICPB 2026-06 AI 应用榜第 1 名，月访问约 4.34M。"),
    ("invideo AI", "综合", "AICPB 2026-06 AI 应用榜第 8 名，月访问约 3.44M。"),
    ("Question.AI-Math Calculator", "综合", "AICPB 2026-06 AI 应用榜第 10 名，月访问约 3.65M。"),
    ("豆包爱学", "综合", "AICPB 2026-06 AI 应用榜第 3 名，月访问约 2.55M。"),
    ("Kagi Search", "搜索 / 研究", "AICPB 2026-06 AI 搜索榜第 5 名，月访问约 5.06M。"),
    ("ACCIO", "搜索 / 研究", "AICPB 2026-06 AI 搜索榜第 8 名，月访问约 2.60M。"),
    ("felo.ai", "搜索 / 研究", "AICPB 2026-06 AI 搜索榜第 9 名，月访问约 1.45M。"),
    ("Remove.bg", "图像 / 视频生成", "AICPB 2026-06 AI 图像编辑榜第 1 名，月访问约 59.68M。"),
    ("Photoroom", "图像 / 视频生成", "AICPB 2026-06 AI 图像编辑榜第 2 名，月访问约 19.56M。"),
    ("Pixelcut.ai", "图像 / 视频生成", "AICPB 2026-06 AI 图像编辑榜第 3 名，月访问约 11.86M。"),
    ("Pixlr", "图像 / 视频生成", "AICPB 2026-06 AI 图像编辑榜第 4 名，月访问约 9.88M。"),
    ("Cutout Pro", "图像 / 视频生成", "AICPB 2026-06 AI 图像编辑榜第 5 名，月访问约 9.80M。"),
    ("Fotor", "图像 / 视频生成", "AICPB 2026-06 AI 图像编辑榜第 6 名，月访问约 8.09M。"),
    ("WatermarkRemover.io", "图像 / 视频生成", "AICPB 2026-06 AI 图像编辑榜第 8 名，月访问约 3.86M。"),
    ("PicWish", "图像 / 视频生成", "AICPB 2026-06 AI 图像编辑榜第 9 名，月访问约 3.61M。"),
    ("airbrush", "图像 / 视频生成", "AICPB 2026-06 AI 图像编辑榜第 10 名，月访问约 3.38M。"),
    ("Suno.com", "音乐 / 语音", "AICPB 2026-06 AI 音乐生成榜第 1 名，月访问约 76.55M。"),
    ("Mureka", "音乐 / 语音", "AICPB 2026-06 AI 音乐生成榜第 4 名，月访问约 2.95M。"),
    ("Musicfy", "音乐 / 语音", "AICPB 2026-06 AI 音乐生成榜第 10 名，月访问约 351.86K。"),
    ("Skywork ai", "个人 Agent", "AICPB 2026-06 AI Agent 榜第 7 名，月访问约 3.33M。"),
    ("Composio", "个人 Agent", "AICPB 2026-06 AI Agent 榜第 9 名，月访问约 1.69M。"),
    ("Pollo", "图像 / 视频生成", "AICPB 2026-06 AI 视频生成榜第 6 名，月访问约 9.33M。"),
    ("Vidu 海外", "图像 / 视频生成", "AICPB 2026-06 AI 视频生成榜第 10 名，月访问约 3.17M。"),
    ("AiPPT.com", "办公 / 生产力", "AICPB 2026-06 AI PPT 榜第 2 名，月访问约 6.93M。"),
    ("Prezi", "办公 / 生产力", "AICPB 2026-06 AI PPT 榜第 3 名，月访问约 6.46M。"),
    ("slidesgo", "办公 / 生产力", "AICPB 2026-06 AI PPT 榜第 4 名，月访问约 4.94M。"),
    ("Pitch", "办公 / 生产力", "AICPB 2026-06 AI PPT 榜第 6 名，月访问约 1.44M。"),
    ("PresentationsAI", "办公 / 生产力", "AICPB 2026-06 AI PPT 榜第 7 名，月访问约 920.67K。"),
    ("Beautiful.ai", "办公 / 生产力", "AICPB 2026-06 AI PPT 榜第 8 名，月访问约 892.24K。"),
    ("AiPPT.cn", "办公 / 生产力", "AICPB 2026-06 AI PPT 榜第 9 名，月访问约 859.78K。"),
    ("Fathom", "办公 / 生产力", "AICPB 2026-06 AI 会议助手榜第 2 名，月访问约 5.26M。"),
    ("Notta", "办公 / 生产力", "AICPB 2026-06 AI 会议助手榜第 5 名，月访问约 2.61M。"),
    ("tldv.io", "办公 / 生产力", "AICPB 2026-06 AI 会议助手榜第 7 名，月访问约 1.53M。"),
    ("Transkriptor", "办公 / 生产力", "AICPB 2026-06 AI 会议助手榜第 8 名，月访问约 841.27K。"),
    ("Krisp", "办公 / 生产力", "AICPB 2026-06 AI 会议助手榜第 9 名，月访问约 651.81K。"),
    ("Avoma", "办公 / 生产力", "AICPB 2026-06 AI 会议助手榜第 10 名，月访问约 230.37K。"),
    ("Lovable.dev", "编程 / Agent", "AICPB 2026-06 AI 编程榜第 3 名，月访问约 34.83M。"),
    ("BASE44 2.0", "编程 / Agent", "AICPB 2026-06 AI 编程榜第 8 名，月访问约 17.16M。"),
    ("SpicyChat AI", "陪伴 / 角色对话", "AICPB 2026-06 AI 角色榜第 3 名，月访问约 79.31M。"),
    ("polybuzz", "陪伴 / 角色对话", "AICPB 2026-06 AI 角色榜第 4 名，月访问约 66.36M。"),
    ("Candy.ai", "陪伴 / 角色对话", "AICPB 2026-06 AI 角色榜第 5 名，月访问约 54.47M。"),
    ("chub.ai", "陪伴 / 角色对话", "AICPB 2026-06 AI 角色榜第 7 名，月访问约 9.01M。"),
    ("moescape", "陪伴 / 角色对话", "AICPB 2026-06 AI 角色榜第 9 名，月访问约 3.42M。"),
    ("Joyland", "陪伴 / 角色对话", "AICPB 2026-06 AI 角色榜第 10 名，月访问约 2.75M。"),
    ("DuMate", "个人 Agent", "AICPB 2026-06 Claw Agent 榜第 2 名，月访问约 949.38K。"),
    ("QClaw", "个人 Agent", "AICPB 2026-06 Claw Agent 榜第 5 名，月访问约 509.75K。"),
    ("nanoclaw.dev", "个人 Agent", "AICPB 2026-06 Claw Agent 榜第 7 名，月访问约 141.03K。"),
    ("Qwen.ai", "综合", "AICPB 2026-06 AI 网站榜第 8 名，月访问约 35.43M。"),
    ("Veed.io", "综合", "AICPB 2026-06 AI 网站榜第 1 名，月访问约 8.76M。"),
    ("ClipChamp", "综合", "AICPB 2026-06 AI 网站榜第 2 名，月访问约 7.60M。"),
    ("InVideo", "综合", "AICPB 2026-06 AI 网站榜第 3 名，月访问约 7.10M。"),
    ("Kapwing AI", "综合", "AICPB 2026-06 AI 网站榜第 5 名，月访问约 5.10M。"),
    ("Media.io", "综合", "AICPB 2026-06 AI 网站榜第 6 名，月访问约 4.27M。"),
    ("Lalal.ai", "综合", "AICPB 2026-06 AI 网站榜第 8 名，月访问约 2.51M。"),
    ("Vizard.ai", "综合", "AICPB 2026-06 AI 网站榜第 9 名，月访问约 1.82M。"),
    ("FlexClip", "综合", "AICPB 2026-06 AI 网站榜第 10 名，月访问约 1.77M。"),
    ("MaxAI.me", "综合", "AICPB 2026-06 AI 网站榜第 1 名，月访问约 2.56M。"),
    ("商汤小浣熊", "综合", "AICPB 2026-06 AI 网站榜第 2 名，月访问约 3.70M。"),
    ("Agnes AI", "综合", "AICPB 2026-06 AI 网站榜第 3 名，月访问约 2.08M。"),
    ("Hyper3D", "综合", "AICPB 2026-06 AI 网站榜第 4 名，月访问约 3.12M。"),
    ("Devin", "综合", "AICPB 2026-06 AI 网站榜第 5 名，月访问约 2.97M。"),
    ("OwlyWriter AI by Hootsuite", "综合", "AICPB 2026-06 AI 网站榜第 7 名，月访问约 2.79M。"),
    ("CodeBuddy", "综合", "AICPB 2026-06 AI 网站榜第 9 名，月访问约 7.49M。"),
    ("Z.ai", "综合", "AICPB 2026-06 AI 网站榜第 10 名，月访问约 10.24M。"),
    ("Qoder", "综合", "AICPB 2026-06 AI 网站榜第 4 名，月访问约 3.15M。"),
    ("沉浸式翻译", "综合", "AICPB 2026-06 AI 网站榜第 9 名，月访问约 5.51M。"),
    ("knowt.com", "综合", "AICPB 2026-06 AI 网站榜第 3 名，月访问约 2.42M。"),
    ("gauthmath", "综合", "AICPB 2026-06 AI 网站榜第 6 名，月访问约 4.33M。"),
    ("blackbox", "综合", "AICPB 2026-06 AI 网站榜第 8 名，月访问约 2.45M。"),
    ("CheggMate", "综合", "AICPB 2026-06 AI 网站榜第 9 名，月访问约 2.53M。"),
]
