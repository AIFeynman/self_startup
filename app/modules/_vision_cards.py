"""视野解读卡：提示词、解析、校验（纯函数，取网页的函数由调用方传入）。

卡片结构见设计稿 1.1 / 1.2 节：标题即结论 → 一句话（≤60 字）→ 打个比方 → 为什么（带来源和日期）
→ 更深一层（四种洞见之一）→ 我们的判断（能到期对账的预测）→ 对你意味着 → 接下来看。
「变了多少」「口径提醒」由程序算，不让模型写。
"""
from __future__ import annotations

import json
import re
from datetime import date, timedelta

PLAIN_MAX = 60
INSIGHT_TYPES = ("交叉对照", "被平均数盖住", "领先关系", "反直觉")
TITLE_BANNED = ("同比", "环比", "分位", "标准差", "中位数", "季调", "z 分数")
TERMS = ("同比", "环比", "分位", "‰", "标准差", "中位数", "季调", "PMI", "FLOP", "ARR", "token", "基准")
OPS = (">", ">=", "<", "<=")
CONFIDENCE = ("高", "中", "低")


def _fmt_points(pts: list[tuple[str, float]], n: int = 120) -> str:
    return ", ".join(f"{p}:{v:g}" for p, v in pts[-n:])


def card_prompt(cfg: dict, pts: list[tuple[str, float]], summary: dict, sig: dict, related: list[dict],
                track: list[dict], feedback: str = "") -> str:
    rel = "\n".join(f"- {r['id']}｜{r['name']}（{r['unit']}）最新 {r['period']} = {r['value']:g}" for r in related) or "（无）"
    tr = "\n".join(f"- {t['created_at'][:10]} 判断「{t['series_id']} 到 {t['due_date']} {t['op']} {t['target']:g}」（可信度{t['confidence']}）"
                   f"→ {'实际 %g，%s' % (t['actual'], '命中' if t['hit'] else '没中') if t.get('actual') is not None else '还没到期'}"
                   for t in track) or "（还没有）"
    redo = f"\n\n## 上一版被打回的原因（这次必须改掉）\n{feedback}" if feedback else ""
    return f"""你是「视野」板块的数据解读作者，读者是不懂经济和 AI 行业的普通人。请为下面这个指标的最新变化写一张解读卡。

## 指标
- id：{cfg['id']}
- 名称：{cfg['name']}（单位：{cfg['unit'] or '无'}，频率：{cfg['freq']}，地区：{cfg.get('region') or '全球'}）
- 口径：{cfg.get('note') or '无'}
- 程序算出的统计：{json.dumps(summary, ensure_ascii=False)}
- 为什么值得写（程序判断的显著变化）：{'；'.join(sig['reasons'])}
- 历史数据（period:value，最近 120 期）：{_fmt_points(pts)}

## 相关指标的最新值（可以交叉对照）
{rel}

## 你过去的判断和对账结果（参考自己错在哪，调整这次的判断）
{tr}

## 要求
1. 先用 WebSearch / WebFetch 查这次变化的原因：官方发布、权威媒体、研究报告，记下链接和发布日期。查不到发布日期或打不开的网页不要当来源，换一个，或把这条原因标「推测」。
2. 标题就是结论，普通人一眼看懂，不用术语（不出现：{'、'.join(TITLE_BANNED)}）。
3. plain（一句话）硬上限 {PLAIN_MAX} 字（含标点），按 40 字左右写，留出余量；超了直接打回。
4. analogy：一个和日常生活有关的比方或例子。
5. 术语（{'、'.join(TERMS)}）在全卡任何一栏第一次出现时，紧跟一个括号解释，例如「同比（和去年同一个月比）」；能不用就不用。
6. deeper（更深一层）必须是下面四种之一，并在 type 里写明：交叉对照（和另一个指标对照得出结论）、被平均数盖住（找出被平均数掩盖的那部分人）、领先关系（谁领先谁几个月 / 几年）、反直觉（和大多数人的直觉相反，给出证据）。不要只是把数字换个说法，不要写「值得关注」这类空话。
7. predictions：至少一条能到期对账的预测。series_id 必须是上面出现过的指标 id（本指标或相关指标），due 是未来 3 年内的日期，op 是 > >= < <= 之一，target 是数值（和该指标同单位），confidence 是 高 / 中 / 低。不写「可能」「或许」。预测里的数字只放在 predictions 里，别的栏不要写对未来的数字。
8. 数字纪律：卡里出现的每个数字，要么来自上面给的数据（可以四舍五入、可以算差值和百分比变化），要么原样出现在你引用的来源网页里。不许编数字。
9. meaning（对你意味着）：联系 AI 创业方向或个人理财的大方向（比如资产配置该关注什么、哪类技能更值钱），不给具体的买卖建议。
10. next：接下来看什么数据、大约什么时候发布。

## 输出
只输出一个 JSON 对象，不要别的文字：
{{"title": "...", "plain": "...", "analogy": "...",
  "why": [{{"text": "原因", "url": "https://...", "date": "YYYY-MM-DD", "kind": "来源"}}, {{"text": "...", "url": "", "date": "", "kind": "推测"}}],
  "deeper": {{"type": "交叉对照", "text": "..."}},
  "predictions": [{{"series_id": "{cfg['id']}", "due": "YYYY-MM-DD", "op": ">", "target": 0, "confidence": "中", "text": "一句话写这个判断"}}],
  "meaning": "...", "next": "..."}}{redo}
"""


def review_prompt(cfg: dict, card: dict) -> str:
    return f"""你是严格的审稿人。下面是一张给普通读者看的数据解读卡（指标：{cfg['name']}）。按四条标准打分，判断能不能发：

1. 小白能懂：标题是结论、没有术语；一句话讲清楚；有贴近生活的比方。
2. 有洞见：「更深一层」确实是 交叉对照 / 被平均数盖住 / 领先关系 / 反直觉 之一，而不是把数字换个说法或「值得关注」类空话。
3. 判断可验证：预测有指标、日期、方向和数值，可信度和理由匹配。
4. 不越界：原因有来源或明确标了推测；「对你意味着」没有具体买卖建议。

卡片：
{json.dumps(card, ensure_ascii=False, indent=1)}

只输出 JSON：{{"pass": true 或 false, "scores": {{"小白能懂": 1-5, "有洞见": 1-5, "判断可验证": 1-5, "不越界": 1-5}}, "reason": "不通过时写清楚要改什么"}}
任何一项低于 3 分就是不通过。"""


def parse_json(text: str) -> dict | None:
    text = text or ""
    for m in [re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)] + [re.search(r"\{.*\}", text, re.S)]:
        if m:
            try:
                o = json.loads(m.group(1) if m.lastindex else m.group(0))
                return o if isinstance(o, dict) else None
            except json.JSONDecodeError:
                continue
    return None


_DATE = re.compile(r"\d{4}[-./年]\d{1,2}(?:[-./月]\d{1,2}日?)?月?|\d{4}\s*年|(?:19|20)\d{2}(?=\D|$)")
_NUM = re.compile(r"(?<![\w.])[-−+]?\d[\d,]*(?:\.\d+)?")


def numbers(text: str) -> list[str]:
    """正文里需要对账的数字：去掉日期和年份；13 以下的整数多是月份、序号、期数，不查。"""
    out = []
    for raw in _NUM.findall(_DATE.sub(" ", text or "")):
        s = raw.replace(",", "").replace("−", "-").lstrip("+")
        if "." not in s and abs(int(s)) < 13:
            continue
        out.append(s)
    return out


def fact_numbers(pts_by_series: dict[str, list[tuple[str, float]]], summary: dict) -> list[float]:
    """库里能对上的数：各序列的值，最新值和每个历史值的差、百分比变化、倍数，以及统计摘要里的数。"""
    facts: set[float] = set()
    for pts in pts_by_series.values():
        if not pts:
            continue
        v = pts[-1][1]
        for _, x in pts:
            facts.add(x)
            facts.add(v - x)
            if x:
                facts.add((v / x - 1) * 100)
                facts.add(v / x)
            if v:
                facts.add(x / v)
                facts.add((x / v - 1) * 100)
    for k, x in summary.items():
        if isinstance(x, (int, float)):
            facts.add(float(x))
        elif isinstance(x, (list, tuple)) and len(x) == 2 and isinstance(x[1], (int, float)):
            facts.add(float(x[1]))
    return [f for f in facts if f == f]


def matches(s: str, facts: list[float]) -> bool:
    x = abs(float(s))
    d = len(s.split(".")[1]) if "." in s else 0
    tol = 0.5 * 10 ** -d + 1e-9
    return any(abs(abs(f) - x) <= tol for f in facts)


def card_text(card: dict) -> str:
    why = " ".join(w.get("text", "") for w in card.get("why") or [] if isinstance(w, dict))
    deeper = (card.get("deeper") or {}).get("text", "") if isinstance(card.get("deeper"), dict) else ""
    return " ".join([card.get("title", ""), card.get("plain", ""), card.get("analogy", ""), why, deeper,
                     card.get("meaning", ""), card.get("next", "")])


def explained(body: str, i: int, term: str) -> bool:
    if re.match(r"\s*[（(]", body[i + len(term):i + len(term) + 2]):
        return True
    if re.search(r"[（(][^）)]{0,20}$", body[max(0, i - 21):i]):
        return True
    return term == "‰" and bool(re.search(r"千分之|每千", body))


def check(card: dict, facts: list[float], series_ids: set[str], fetch_text, today: date | None = None) -> dict:
    """返回 {ok, problems[]}；fetch_text(url) -> (status, text)，打不开时 status 非 2xx/3xx。"""
    today = today or date.today()
    probs: list[str] = []
    for k in ("title", "plain", "analogy", "meaning", "next"):
        if not str(card.get(k) or "").strip():
            probs.append(f"缺少 {k}")
    if len(card.get("plain") or "") > PLAIN_MAX:
        probs.append(f"一句话 {len(card['plain'])} 字，超过 {PLAIN_MAX} 字")
    if bad := [t for t in TITLE_BANNED if t in (card.get("title") or "")]:
        probs.append("标题里有术语：" + "、".join(bad))
    body = card_text(card)
    for t in TERMS:
        i = body.find(t)
        if i >= 0 and not explained(body, i, t) and t not in (card.get("title") or ""):
            probs.append(f"术语「{t}」第一次出现时没有括号解释")
    deeper = card.get("deeper") if isinstance(card.get("deeper"), dict) else {}
    if deeper.get("type") not in INSIGHT_TYPES or not deeper.get("text"):
        probs.append("更深一层要写明类型（" + " / ".join(INSIGHT_TYPES) + "）和内容")

    why = [w for w in card.get("why") or [] if isinstance(w, dict)]
    if not why:
        probs.append("缺少「为什么」")
    sources: dict[str, str] = {}
    for w in why:
        if w.get("kind") in ("推测", "判断"):
            continue
        url = w.get("url") or ""
        if not url.startswith("http"):
            probs.append(f"原因「{w.get('text', '')[:20]}」没有链接，要么补来源要么标推测")
            continue
        if not re.fullmatch(r"\d{4}-\d{2}(-\d{2})?", w.get("date") or ""):
            probs.append(f"来源 {url} 缺发布日期")
        status, text = fetch_text(url)
        if not (200 <= status < 400):
            probs.append(f"链接打不开（{status}）：{url}")
        else:
            sources[url] = text

    src_text = " ".join(sources.values()).replace(",", "")
    unknown = sorted({n for n in numbers(body) if not matches(n, facts) and n not in src_text and n.lstrip("-") not in src_text})
    if unknown:
        probs.append("这些数字在库里和引用来源里都找不到：" + "、".join(unknown))

    preds = [p for p in card.get("predictions") or [] if isinstance(p, dict)]
    if not preds:
        probs.append("至少要有一条能到期对账的预测")
    for p in preds:
        try:
            due = date.fromisoformat(str(p.get("due")))
        except ValueError:
            probs.append(f"预测日期不对：{p.get('due')}")
            continue
        if not (today < due <= today + timedelta(days=3 * 366)):
            probs.append(f"预测日期 {due} 要在未来 3 年内")
        if p.get("series_id") not in series_ids:
            probs.append(f"预测的指标 {p.get('series_id')} 不在指标库里")
        if p.get("op") not in OPS or not isinstance(p.get("target"), (int, float)):
            probs.append("预测要写比较符（> >= < <=）和数值")
        if p.get("confidence") not in CONFIDENCE:
            probs.append("预测可信度要写 高 / 中 / 低")
    return {"ok": not probs, "problems": probs}
