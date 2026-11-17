"""青少年板块：每日两个题材（一个时事、一个往事）的提示词和校验（纯函数，取网页的函数由调用方传入）。

每个题材：培养理由（练哪项能力、为什么选它）→ 背景 → 现象 → 最多 3 道逐层递进的题（看清 → 追问 → 换位与评价）。
"""
from __future__ import annotations

import json
import re
from datetime import date, timedelta

KINDS = ("时事", "往事")
ABILITIES = ("思辨", "感同身受")
DOMAINS = ("社会", "经济", "军事", "政治", "文学", "生物", "地理", "历史", "科技", "环境", "艺术")
LEVELS = {1: "看清", 2: "追问", 3: "换位与评价"}
MAX_Q = 3
NEWS_WINDOW_DAYS = 7


def day_prompt(recent: list[dict], feedback: dict, redo: str = "") -> str:
    seen = "\n".join(f"- {r['day']} {r['kind']}｜{r['domain']}｜{r['headline']}" for r in recent) or "（还没有）"
    scores = "\n".join(f"- 第{lv}层（{LEVELS.get(lv, '')}）{ab}：平均自评 {v['avg']:.1f}/2，共 {v['n']} 次" for (lv, ab), v in feedback["scores"].items()) or "（还没有作答记录）"
    notes = "\n".join(f"- {n}" for n in feedback["improve"]) or "（还没有）"
    thoughts = "\n".join(f"- {n}" for n in feedback["thoughts"]) or "（还没有）"
    retry = f"\n\n## 上一版被打回的原因（这次必须改掉）\n{redo}" if redo else ""
    return f"""你是「青少年」板块的出题人。读者是初中到高中的学生，目标是通过每天的两个题材，从现象看到背后的问题，培养两种能力：
- 思辨：区分事实和观点、找隐含前提、因果还是相关、多角度看、找反例、给出有依据的判断；
- 感同身受：站到不同处境的人的位置，理解他们的动机、代价和限制；理解不等于认同。

## 今天要出两个题材
1. 一个「时事」：最近 {NEWS_WINDOW_DAYS} 天内发生的真实事件。先用 WebSearch / WebFetch 找权威来源（新华社、人民日报、央视、中国政府网、联合国、路透、BBC、权威期刊或官方机构等），记下链接和发布日期。打不开的网页不能当来源。
2. 一个「往事」：从过去的知识里挖掘——历史事件、地理现象、生物规律、文学作品、经典案例，选一个能照亮今天某类问题的。来源用权威资料（教材级百科、博物馆、官方机构、学术机构、经典原著出处），同样要链接。
两个题材领域不同，领域从这些里选：{'、'.join(DOMAINS)}。题材要有分量、有争议或有张力，不选明星八卦、纯猎奇、血腥细节。立场中立，不灌输结论，涉及政治、军事只讲事实、不同方的诉求和后果。

## 最近出过的题材（不要重复，领域尽量换）
{seen}

## 孩子的作答反馈（据此调整难度和侧重：自评低的能力和层级多练，一直满分的层级往上提一点）
{scores}
孩子写下的想法：
{thoughts}
孩子提的改进意见（必须尽量落实）：
{notes}

## 每个题材的结构
- kind：时事 或 往事；domain：上面领域之一；headline：一句话标题，说清是什么事。
- train_focus：这个题材重点练的具体能力，如「区分事实和观点」「看见不同处境的人」，并在 ability 里写 思辨 或 感同身受。
- why_this：为什么选它、为什么练这个，不超过 80 字。
- ladder：三层题怎么一层层递进的，一句话，不超过 80 字。
- source：name、url、date（时事必填 YYYY-MM-DD；往事写资料发布或修订日期，没有就空）。
- background：青少年读得懂的背景，150–300 字，不堆术语，术语第一次出现用括号解释，数字只能来自来源网页。
- phenomenon：一句话写表面看到的现象。
- questions：1–3 道，level 依次为 1、2、3，不跳层：
  - 第 1 层「看清」：事实是什么、谁受影响、哪些是事实哪些是说法（初中水平）；
  - 第 2 层「追问」：为什么会这样、背后的结构和利益、因果还是相关、各方怎么看（高一水平）；
  - 第 3 层「换位与评价」：站到某一方想一想、权衡代价、给出有依据的判断，难度到高考语文、政治的材料分析题，要求答题者结合材料自己组织论述。
  - 每题字段：level、ability（思辨 或 感同身受）、q（题目，必须结合材料，不考死记）、answer（参考答案，分点写清思路，不是只给结论）、points（得分要点 2–4 条）、hint（卡住时的一句提示，可空）。
  - 每个题材的题目里至少有一道是感同身受，至少有一道是思辨。

## 输出
只输出一个 JSON 对象，不要别的文字：
{{"items": [{{"kind": "时事", "domain": "经济", "headline": "...", "train_focus": "...", "ability": "思辨", "why_this": "...", "ladder": "...",
  "source": {{"name": "...", "url": "https://...", "date": "YYYY-MM-DD"}}, "background": "...", "phenomenon": "...",
  "questions": [{{"level": 1, "ability": "思辨", "q": "...", "answer": "...", "points": ["..."], "hint": ""}}]}},
  {{"kind": "往事", "...": "..."}}]}}{retry}
"""


def check(out: dict, fetch_text, today: date | None = None) -> dict:
    """返回 {ok, problems[]}；fetch_text(url) -> (status, text)。"""
    today = today or date.today()
    probs: list[str] = []
    items = [i for i in out.get("items") or [] if isinstance(i, dict)]
    if [i.get("kind") for i in items] != list(KINDS):
        probs.append("要正好两个题材：先时事、后往事")
    if len({i.get("domain") for i in items}) < len(items):
        probs.append("两个题材的领域要不同")
    for i in items:
        tag = f"{i.get('kind')}「{str(i.get('headline'))[:12]}」"
        for k in ("headline", "train_focus", "why_this", "ladder", "background", "phenomenon"):
            if not str(i.get(k) or "").strip():
                probs.append(f"{tag}缺少 {k}")
        if i.get("domain") not in DOMAINS:
            probs.append(f"{tag}领域要在 {'、'.join(DOMAINS)} 里")
        if i.get("ability") not in ABILITIES:
            probs.append(f"{tag}ability 要写 思辨 或 感同身受")
        if len(i.get("why_this") or "") > 80 or len(i.get("ladder") or "") > 80:
            probs.append(f"{tag}why_this 和 ladder 各不超过 80 字")
        if not 100 <= len(i.get("background") or "") <= 400:
            probs.append(f"{tag}背景要 150–300 字，现在 {len(i.get('background') or '')} 字")
        src = i.get("source") if isinstance(i.get("source"), dict) else {}
        url, sdate = src.get("url") or "", src.get("date") or ""
        if not src.get("name") or not url.startswith("http"):
            probs.append(f"{tag}缺少来源名称或链接")
        else:
            status, _ = fetch_text(url)
            if not 200 <= status < 400:
                probs.append(f"{tag}链接打不开（{status}）：{url}")
        if i.get("kind") == "时事":
            try:
                d = date.fromisoformat(sdate)
                if not today - timedelta(days=NEWS_WINDOW_DAYS) <= d <= today:
                    probs.append(f"{tag}发布日期 {sdate} 不在最近 {NEWS_WINDOW_DAYS} 天")
            except ValueError:
                probs.append(f"{tag}时事来源缺发布日期")
        qs = [q for q in i.get("questions") or [] if isinstance(q, dict)]
        if not 1 <= len(qs) <= MAX_Q:
            probs.append(f"{tag}题目要 1–{MAX_Q} 道")
        if [q.get("level") for q in qs] != list(range(1, len(qs) + 1)):
            probs.append(f"{tag}题目 level 要从 1 开始逐层递增")
        for q in qs:
            if q.get("ability") not in ABILITIES:
                probs.append(f"{tag}第{q.get('level')}题 ability 要写 思辨 或 感同身受")
            if not str(q.get("q") or "").strip() or not str(q.get("answer") or "").strip():
                probs.append(f"{tag}第{q.get('level')}题缺题目或答案")
            if not [p for p in q.get("points") or [] if str(p).strip()]:
                probs.append(f"{tag}第{q.get('level')}题缺得分要点")
        if len(qs) >= 2 and {q.get("ability") for q in qs} != set(ABILITIES):
            probs.append(f"{tag}题目里思辨和感同身受都要有")
    return {"ok": not probs, "problems": probs}


def parse(text: str) -> dict | None:
    for m in [re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text or "", re.S), re.search(r"\{.*\}", text or "", re.S)]:
        if m:
            try:
                o = json.loads(m.group(1) if m.lastindex else m.group(0))
                return o if isinstance(o, dict) else None
            except json.JSONDecodeError:
                continue
    return None
