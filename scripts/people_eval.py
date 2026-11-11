"""人物发声的准召评估：对样本人物，在最近 N 天里比较「系统的搜法」和「逐人不合并、不过滤的参考搜法」。

参考集合 = 系统规则层结果 ∪ 参考搜法结果（pooling），每条由本机较强模型标注是否本人发声（可人工抽查改标）。
输出各渠道：规则层召回、最终召回、最终准确率，以及漏掉 / 误收的条目，写到 --out 目录（report.json / labels.json）。
只读外部接口，不写平台数据库（SELF_STARTUP_DATA 指向临时目录跑）。

python scripts/people_eval.py --out /tmp/eval [--days 7] [--channels x,youtube,podcast,paper,news] [--relabel]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import agent  # noqa: E402
from app.modules import _feed_sources as src  # noqa: E402
from app.modules import _people as P  # noqa: E402

SAMPLE = ["dario", "altman", "koray", "wang", "cherny", "tibo", "karpathy", "feifei", "lecun", "hinton",
          "dean", "weil", "shazeer", "aravind", "truell", "mensch", "yangzhilin", "yanjunjie", "shunyu", "ng"]
GOLD_MODEL = "claude-sonnet-5-5"
GOLD_SYSTEM = (
    "你是严格的标注员。每条输入是一个视频 / 播客 / 新闻 / 论文 / 推文 / 博客，以及它关联的 AI 人物（带身份）。\n"
    "目标是发现该人物新的原始发声。voice=true 只算：本人新出镜或出声的完整访谈、演讲、播客、发布会、听证会（原节目或官方频道发布，含官方频道剪出的片段）；"
    "本人撰写或署名的文章、论文；直接报道本人新说了什么、宣布了什么的新闻。\n"
    "voice=false：同名的其他人；以他为话题的评论、解读、八卦、传记、盘点；股价或公司新闻；第三方剪辑、Shorts、搬运、翻译配字幕、AI 配音；"
    "旧内容（原始发声明显早于发布日期一个月以上）的重发；只是提到名字。\n"
    "voice=true 时给 event：这次发声的简短英文标识（人物 + 场合，如 altman-raj-shamani-podcast、hinton-guardian-interview），"
    "同一场访谈 / 演讲 / 表态的不同报道用同一个 event。\n"
    '只输出 JSON：{"items": [{"id": "<原样>", "voice": true/false, "event": "<voice 为 true 时>", "note": "<十字以内理由>"}]}，每条都要有。'
)


def sample_pool() -> list[dict]:
    idx = P.by_id()
    return [idx[i] for i in SAMPLE]


def system_raw(ch: str, pool: list[dict]) -> list[dict]:
    items, errs = P.FETCHERS[ch](pool)
    for e in errs:
        print(f"  [system {ch}] {e}")
    return items


# ---------- 参考搜法：逐人、不合并、不做本人过滤 ----------
def ref_x(pool):
    provs = src._x_providers()
    since = P._cutoff("x")
    out = []
    with src._client() as c:
        def one(p):
            try:
                return p, src._x_call(c, provs, "timeline", p["x"])
            except Exception as e:  # noqa: BLE001
                print(f"  [ref x] {p['x']}: {e}")
                return p, []
        with ThreadPoolExecutor(4) as ex:
            for p, tweets in ex.map(one, [p for p in pool if p.get("x")]):
                for t in tweets:
                    it = src.x_item(t, "ref")
                    if it and (it["date"] or "") >= since:
                        out.append(P._item(it["id"], "x", [p["id"]], it["title"], it["url"], it["date"], it["summary"]))
    return out


def ref_youtube(pool):
    key = src.os.environ.get("YOUTUBE_API_KEY", "").strip()
    since = P._cutoff("youtube") + "Z"
    out = {}
    with src._client() as c:
        for p in pool:
            for n in P.search_names(p):
                r = c.get("https://www.googleapis.com/youtube/v3/search", params={
                    "key": key, "part": "snippet", "q": f'"{n}"', "type": "video", "order": "date",
                    "publishedAfter": since, "maxResults": 50})
                if r.status_code != 200:
                    print(f"  [ref youtube] {n}: {r.status_code}")
                    continue
                for v in r.json().get("items", []):
                    vid, sn = (v.get("id") or {}).get("videoId"), v.get("snippet") or {}
                    if vid and P.mentions(p, f"{sn.get('title', '')} {sn.get('description', '')}"):
                        it = out.setdefault(vid, P._item(f"youtube:{vid}", "youtube", [], sn.get("title", ""),
                                                         f"https://www.youtube.com/watch?v={vid}", (sn.get("publishedAt") or "")[:19],
                                                         sn.get("description", ""), uploader=sn.get("channelTitle", "")))
                        it["people"] = sorted(set(it["people"]) | {p["id"]})
    return list(out.values())


def ref_podcast(pool):
    since = P._cutoff("podcast")
    out = {}
    with src._client() as c:
        for p in pool:
            for n in P.search_names(p):
                zh = P.is_zh(n)
                for term in ([n, f"{n} 访谈", f"{n} 播客"] if zh else [n, f"{n} interview", f"{n} podcast"]):
                    time.sleep(2.5)
                    try:
                        res = c.get("https://itunes.apple.com/search", params={
                            "term": term, "entity": "podcastEpisode", "limit": 50, "country": "cn" if zh else "us"}).json().get("results", [])
                    except Exception as e:  # noqa: BLE001
                        print(f"  [ref podcast] {term}: {e}")
                        continue
                    for e in res:
                        text = f"{e.get('trackName', '')} {e.get('description') or ''}"
                        if (e.get("releaseDate") or "")[:19] >= since and P.mentions(p, text):
                            it = out.setdefault(f"podcast:{e['trackId']}", P._item(
                                f"podcast:{e['trackId']}", "podcast", [], e.get("trackName", ""), e.get("trackViewUrl", ""),
                                (e.get("releaseDate") or "")[:19], e.get("description") or "", show=e.get("collectionName", "")))
                            it["people"] = sorted(set(it["people"]) | {p["id"]})
    return list(out.values())


def ref_news(pool):
    out = {}
    with src._client() as c:
        for p in pool:
            for n in P.search_names(p):
                try:
                    r = c.get(P.news_url(n, P.NEWS_WINDOW))
                except Exception as e:  # noqa: BLE001
                    print(f"  [ref news] {n}: {e}")
                    continue
                for e in src.feedparser.parse(r.text).entries:
                    title = P.re.sub(r"\s+-\s+[^-]+$", "", e.get("title", ""))
                    tm = e.get("published_parsed")
                    date = time.strftime("%Y-%m-%dT%H:%M:%S", tm) if tm else ""
                    if not P.mentions(p, title):
                        continue
                    iid = "news:" + P.hashlib.sha1(title.lower().encode()).hexdigest()[:16]
                    it = out.setdefault(iid, P._item(iid, "news", [], title, e.get("link", ""), date,
                                                     outlet=(e.get("source") or {}).get("title", "")))
                    it["people"] = sorted(set(it["people"]) | {p["id"]})
    return list(out.values())


def ref_paper(pool):
    out = []
    for p in pool:
        if p.get("papers"):
            items, _ = P.fetch_paper([p], pause=3)
            out += items
            time.sleep(3)
    return out


def ref_blog(pool):
    return []


REFS = {"blog": ref_blog, "x": ref_x, "youtube": ref_youtube, "podcast": ref_podcast, "news": ref_news, "paper": ref_paper}


def gold_label(items: list[dict], labels: dict) -> dict:
    todo = [it for it in items if it["id"] not in labels]
    idx = P.by_id()
    for i in range(0, len(todo), 30):
        batch = todo[i:i + 30]
        rows = [{"id": it["id"], "people": [f"{idx[p]['name']}（{idx[p].get('zh') or ''}），{idx[p]['role']}" for p in it["people"]],
                 "channel": it["channel"], "date": it["date"], "title": it["title"], "summary": it["summary"][:400],
                 "source": it["extra"].get("uploader") or it["extra"].get("outlet") or it["extra"].get("show") or ""} for it in batch]
        r = agent.run_once(json.dumps(rows, ensure_ascii=False), engine="claude", system=GOLD_SYSTEM, model=GOLD_MODEL,
                           readonly=True, fallback=False)
        m = P.re.search(r"\{.*\}", r.get("text") or "", P.re.S)
        for x in (json.loads(m.group(0)).get("items") or []) if m else []:
            labels[str(x["id"])] = {"voice": bool(x.get("voice")), "event": str(x.get("event") or ""), "note": x.get("note", ""),
                                    "by": GOLD_MODEL}
        print(f"  gold {i + len(batch)}/{len(todo)}")
    return labels


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--channels", default="x,blog,youtube,podcast,paper,news")
    ap.add_argument("--relabel", action="store_true")
    ap.add_argument("--ref-from", default="", help="复用之前评估目录里的参考搜法结果（pool_<渠道>.json），省配额")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for ch in P.LOOKBACK_DAYS:
        P.LOOKBACK_DAYS[ch] = a.days
    P.NEWS_WINDOW = f"{a.days}d"
    pool = sample_pool()
    lab_file = out / "labels.json"
    labels = {} if a.relabel or not lab_file.exists() else json.loads(lab_file.read_text())
    runner = (lambda prompt, system="", model="": agent.run_once(prompt, engine="claude", system=system, model=model,
                                                                  readonly=True, fallback=False))
    report = {}
    for ch in a.channels.split(","):
        print(f"== {ch}")
        raw = system_raw(ch, pool)
        final = raw if ch in ("x", "blog", "paper") else P.voice_filter(raw, runner, "claude-haiku-5-5")[0]
        cached = Path(a.ref_from) / f"pool_{ch}.json" if a.ref_from else None
        ref = json.loads(cached.read_text()) if cached and cached.exists() else REFS[ch](pool)
        poolset = {it["id"]: it for it in ref + raw}
        if ch in ("x", "blog"):
            for it in poolset.values():
                labels.setdefault(it["id"], {"voice": True, "event": it["id"], "note": "本人账号", "by": "rule"})
        else:
            labels = gold_label(list(poolset.values()), labels)
        lab_file.write_text(json.dumps(labels, ensure_ascii=False, indent=1))
        gold = {i for i in poolset if labels.get(i, {}).get("voice")}
        raw_ids, final_ids = {it["id"] for it in raw}, {it["id"] for it in final}
        hit_raw, hit_final = raw_ids & gold, final_ids & gold
        ev = lambda ids: {labels[i].get("event") or i for i in ids}
        events = ev(gold)
        report[ch] = {
            "events": len(events),
            "recall_event_rules": round(len(ev(hit_raw)) / len(events), 3) if events else None,
            "recall_event_final": round(len(ev(hit_final)) / len(events), 3) if events else None,
            "pool": len(poolset), "gold": len(gold), "system_raw": len(raw_ids), "system_final": len(final_ids),
            "recall_rules": round(len(hit_raw) / len(gold), 3) if gold else None,
            "recall_final": round(len(hit_final) / len(gold), 3) if gold else None,
            "precision_final": round(len(hit_final) / len(final_ids), 3) if final_ids else None,
            "missed_events": sorted(events - ev(hit_final)),
            "missed": [{"id": i, "event": labels[i].get("event"), "title": poolset[i]["title"], "people": poolset[i]["people"], "date": poolset[i]["date"],
                        "dropped_by_judge": i in raw_ids} for i in sorted(gold - final_ids)],
            "wrong": [{"id": i, "title": poolset[i]["title"], "people": poolset[i]["people"], "note": labels.get(i, {}).get("note", "")}
                      for i in sorted(final_ids - gold)],
        }
        print({k: v for k, v in report[ch].items() if k not in ("missed", "wrong")})
        (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1))
        (out / f"pool_{ch}.json").write_text(json.dumps(list(poolset.values()), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
