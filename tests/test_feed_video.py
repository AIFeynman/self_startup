"""Reddit / 视频源：字幕解析分段、Reddit RSS / YouTube RSS 解析、价值标签与过滤、关注源输入、深读识别视频。"""
from datetime import datetime, timezone

import pytest

from app.modules import _feed_follow as follow, _feed_rank as rk, _feed_sources as src, _video, learn

NOW = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)


@pytest.mark.parametrize("url,want", [
    ("https://www.youtube.com/watch?v=EWvNQjAaOHw&list=PLx&t=30s", "https://www.youtube.com/watch?v=EWvNQjAaOHw"),
    ("https://youtu.be/EWvNQjAaOHw?si=abc", "https://www.youtube.com/watch?v=EWvNQjAaOHw"),
    ("https://www.youtube.com/shorts/EWvNQjAaOHw", "https://www.youtube.com/watch?v=EWvNQjAaOHw"),
    ("https://www.bilibili.com/video/BV1xx411c7mD?p=1&spm=x", "https://www.bilibili.com/video/BV1xx411c7mD"),
    ("https://www.bilibili.com/video/BV1xx411c7mD?p=3", "https://www.bilibili.com/video/BV1xx411c7mD?p=3"),
    ("https://example.com/a", "https://example.com/a"),
])
def test_canonical_url(url, want):
    assert _video.canonical_url(url) == want


def test_at_url_and_hms():
    assert _video.at_url("https://youtu.be/EWvNQjAaOHw", 75.9) == "https://www.youtube.com/watch?v=EWvNQjAaOHw&t=75s"
    assert _video.at_url("https://www.bilibili.com/video/BV1xx411c7mD?p=3", 10) == \
        "https://www.bilibili.com/video/BV1xx411c7mD?p=3&t=10"
    assert _video.hms(75) == "01:15" and _video.hms(3725) == "1:02:05"


def test_pick_track_prefers_manual_then_orig():
    assert _video.pick_track({"subtitles": {"de": [1], "en": [1]}, "language": "de"}) == ("de", "manual")
    assert _video.pick_track({"subtitles": {"fr": [1], "en": [1]}, "language": "ja"}) == ("en", "manual")
    assert _video.pick_track({"subtitles": {"live_chat": [1]},
                              "automatic_captions": {"zh-Hans": [1], "en-orig": [1], "en": [1]}}) == ("en-orig", "auto")
    assert _video.pick_track({"automatic_captions": {"ja": [1], "en": [1]}, "language": "ja"}) == ("ja", "auto")
    assert _video.pick_track({}) is None


VTT = """WEBVTT

00:00:00.000 --> 00:00:02.000
<c>hello</c> there

00:00:02.000 --> 00:00:04.000
hello there
general kenobi.

00:00:50.000 --> 00:00:52.000
[Music]

00:00:52.000 --> 00:00:54.000
next part &amp; more
"""


def test_parse_vtt_dedups_rolling_lines():
    cues = _video.parse_vtt(VTT)
    assert cues == [(0.0, "hello there"), (2.0, "general kenobi."), (52.0, "next part & more")]


def test_segments_break_at_sentence_end():
    cues = [(i * 5.0, f"w{i}" + ("." if i % 4 == 3 else "")) for i in range(40)]
    segs = _video.segments(cues, seconds=45)
    assert [round(s) for s, _ in segs][:3] == [0, 60, 120]
    assert all(t.endswith(".") for _, t in segs[:-1])
    assert " ".join(t for _, t in segs).split() == [t for _, t in cues]


REDDIT_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
<entry>
  <category term="LocalLLaMA" label="r/LocalLLaMA"/>
  <content type="html">&lt;table&gt;&lt;tr&gt;&lt;td&gt;thumb&lt;/td&gt;&lt;/tr&gt;&lt;/table&gt;&lt;div&gt;&lt;p&gt;My setup for running Qwen locally&lt;/p&gt;&lt;/div&gt; submitted by &lt;a href="https://www.reddit.com/user/x"&gt;/u/x&lt;/a&gt; &lt;br/&gt; &lt;span&gt;&lt;a href="https://github.com/foo/bar"&gt;[link]&lt;/a&gt;&lt;/span&gt; &lt;span&gt;&lt;a href="https://www.reddit.com/r/LocalLLaMA/comments/abc123/t/"&gt;[comments]&lt;/a&gt;&lt;/span&gt;</content>
  <link href="https://www.reddit.com/r/LocalLLaMA/comments/abc123/i_built_x/"/>
  <updated>2026-10-31T10:00:00+00:00</updated>
  <published>2026-10-31T09:00:00+00:00</published>
  <title>I built a local coding agent, lessons learned</title>
</entry>
</feed>"""


def test_parse_reddit_rss():
    [it] = src.parse_reddit_rss(REDDIT_RSS, via="r/LocalLLaMA")
    assert it["id"] == "reddit:abc123" and it["type"] == "discussion"
    assert it["extra"]["subreddit"] == "LocalLLaMA" and it["extra"]["link"] == "https://github.com/foo/bar"
    assert "My setup" in it["summary"] and "thumb" not in it["summary"] and "submitted" not in it["summary"]
    assert it["date"].startswith("2026-10-31")


YT_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015" xmlns:media="http://search.yahoo.com/mrss/" xmlns="http://www.w3.org/2005/Atom">
 <title>Andrej Karpathy</title>
 <entry>
  <yt:videoId>EWvNQjAaOHw</yt:videoId><yt:channelId>UCXUPKJO5MZQN11PqgIvyuvQ</yt:channelId>
  <title>How I use LLMs</title>
  <link rel="alternate" href="https://www.youtube.com/watch?v=EWvNQjAaOHw"/>
  <author><name>Andrej Karpathy</name></author>
  <published>2026-10-25T00:00:00+00:00</published>
  <media:group><media:description>A tour of LLM apps</media:description>
   <media:community><media:statistics views="123456"/></media:community></media:group>
 </entry>
 <entry>
  <yt:videoId>AAAAAAAAAAA</yt:videoId><yt:channelId>UCXUPKJO5MZQN11PqgIvyuvQ</yt:channelId>
  <title>short</title>
  <link rel="alternate" href="https://www.youtube.com/shorts/AAAAAAAAAAA"/>
  <published>2026-10-26T00:00:00+00:00</published>
 </entry>
 <entry>
  <yt:videoId>BBBBBBBBBBB</yt:videoId>
  <title>old</title>
  <link rel="alternate" href="https://www.youtube.com/watch?v=BBBBBBBBBBB"/>
  <published>2020-01-01T00:00:00+00:00</published>
 </entry>
</feed>"""


def test_parse_youtube_feed_skips_shorts_and_old():
    items = src.parse_youtube_feed(YT_FEED, days=21)
    assert [it["id"] for it in items] == ["youtube:EWvNQjAaOHw"]
    it = items[0]
    assert it["type"] == "video" and it["popularity"] == 123456
    assert it["extra"]["channel"] == "Andrej Karpathy" and it["extra"]["via"] == "channel"


def _reddit(title, flair="", **ex):
    return {"id": "reddit:" + title[:8], "source": "reddit", "type": "discussion", "title": title, "summary": "",
            "url": "https://www.reddit.com/r/x/comments/" + title[:8].replace(" ", "_") + "/", "date": "2026-11-01T00:00:00+00:00", "popularity": 0,
            "extra": {"flair": flair, "subreddit": "LocalLLaMA", **ex}}


def test_value_tags_and_scores():
    good, noise = _reddit("I benchmarked 5 coding agents"), _reddit("When will Claude 5 come out?")
    assert rk.value_tag(good) == "实践" and rk.value_tag(_reddit("New paper", "Research")) == "前沿"
    assert rk.value_tag(noise) == "噪音"
    out = {x["id"]: x for x in rk.rank([good, noise], now=NOW)}
    assert out[good["id"]]["score"] > out[noise["id"]]["score"]
    assert out[good["id"]]["why"].startswith("实践经验")
    # 频道订阅的视频不判价值；搜索来的才判
    assert not rk.needs_value({"source": "youtube", "extra": {"via": "channel"}})
    assert rk.needs_value({"source": "youtube", "extra": {"via": "search"}})


def test_low_value_dropped_unless_saved():
    meh = _reddit("lol look at this", judge_value=0.1)
    ok = _reddit("some thread", judge_value=0.9)
    assert [x["id"] for x in rk.rank([meh, ok], now=NOW)] == [ok["id"]]
    kept = rk.rank([meh, ok], now=NOW, feedback={meh["id"]: {"saved": 1}})
    assert {x["id"] for x in kept} == {meh["id"], ok["id"]}
    assert "有干货" in next(x for x in kept if x["id"] == ok["id"])["why"]


def test_reddit_top_rank_hint():
    [x] = rk.rank([_reddit("some thread", top_rank=2)], now=NOW)
    assert "r/LocalLLaMA 本周 top 2" in x["why"]


@pytest.mark.parametrize("text,want", [
    ("https://space.bilibili.com/1567748478", ("bilibili", "1567748478")),
    ("bili 1567748478", ("bilibili", "1567748478")),
])
def test_follow_video_bilibili(text, want):
    assert follow.resolve("video", text)[:2] == want


def test_follow_video_youtube(monkeypatch):
    monkeypatch.setattr(src, "resolve_youtube_channel", lambda t: ("UCXUPKJO5MZQN11PqgIvyuvQ", "Andrej Karpathy"))
    assert follow.resolve("video", "@AndrejKarpathy") == ("youtube_channels", "UCXUPKJO5MZQN11PqgIvyuvQ", "Andrej Karpathy")
    with pytest.raises(follow.FollowError):
        follow.resolve("video", "hello world")


@pytest.mark.parametrize("url", ["https://www.youtube.com/watch?v=EWvNQjAaOHw", "https://youtu.be/EWvNQjAaOHw",
                                 "https://www.bilibili.com/video/BV1xx411c7mD"])
def test_detect_kind_video(url):
    assert learn.detect_kind(url) == "video"


@pytest.mark.parametrize("sn,ok", [
    ({"defaultAudioLanguage": "en-US", "title": "x"}, True),
    ({"defaultAudioLanguage": "zh-Hans", "title": "x"}, True),
    ({"defaultAudioLanguage": "pt-BR", "title": "Introdução ao Claude"}, False),
    ({"defaultLanguage": "hi", "title": "CLAUDE tutorial"}, False),
    ({"title": "딱 한 줄만 적었는데 AI 에이전트"}, False),
    ({"title": "How I use LLMs"}, True),
])
def test_yt_lang_ok(sn, ok):
    assert src.yt_lang_ok(sn) is ok


def test_youtube_search_drop_threshold_stricter():
    yt = {"id": "youtube:a", "source": "youtube", "type": "video", "title": "t", "url": "https://youtu.be/aaaaaaaaaaa",
          "extra": {"via": "search", "judge_value": 0.45}}
    assert rk.low_value(yt)
    assert not rk.low_value(_reddit("some thread", judge_value=0.45))
    assert not rk.low_value({**yt, "extra": {"via": "channel", "judge_value": 0.1}})   # 订阅频道不判


class _Resp:
    def __init__(self, data=None, text="", status=200):
        self._d, self.text, self.status_code = data, text, status

    def json(self):
        return self._d

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


def _yt_video(vid, title, secs, lang="en"):
    return {"id": vid, "snippet": {"title": title, "defaultAudioLanguage": lang, "channelTitle": "c", "channelId": "UC" + "x" * 22,
                                   "publishedAt": "2026-10-31T00:00:00Z"},
            "statistics": {"viewCount": "1000"}, "contentDetails": {"duration": f"PT{secs // 60}M{secs % 60}S"}}


def test_youtube_trending_filters_and_ranks():
    class C:
        def get(self, url, params):
            assert params["chart"] == "mostPopular" and params["regionCode"] == "US"
            if params["videoCategoryId"] == "27":
                return _Resp(status=404)
            return _Resp({"items": [_yt_video("aaaaaaaaaaa", "Short clip", 60), _yt_video("bbbbbbbbbbb", "How GPUs work", 900),
                                    _yt_video("ccccccccccc", "Vídeo", 900, "pt-BR")]})
    [it] = src.youtube_trending(C(), "k", ["28", "27"])
    assert it["id"] == "youtube:bbbbbbbbbbb"
    assert it["extra"]["via"] == "trending" and it["extra"]["rank"] == 2 and it["extra"]["board"] == "YouTube 科技热门"


BILI_RANK = """<?xml version="1.0"?><rss xmlns:dc="http://purl.org/dc/elements/1.1/" version="2.0"><channel><title>bilibili 排行榜-知识</title>
<item><title>大模型是怎么推理的</title><description>&lt;iframe src="x"&gt;&lt;/iframe&gt;讲 KV cache</description>
<link>https://www.bilibili.com/video/BV15Mxn6UEnt</link><pubDate>Sat, 31 Oct 2026 15:10:31 GMT</pubDate><dc:creator>某UP</dc:creator></item>
</channel></rss>"""


def test_bilibili_ranking_parse():
    class C:
        def get(self, url, timeout):
            return _Resp(text=BILI_RANK, status=200 if url.startswith("https://ok") else 503)
    [it] = src.bilibili_ranking(C(), "knowledge", ["https://bad", "https://ok"], days=0)
    assert it["id"] == "bilibili:BV15Mxn6UEnt" and it["url"] == "https://www.bilibili.com/video/BV15Mxn6UEnt"
    assert it["extra"]["via"] == "ranking" and it["extra"]["board"] == "B 站知识区排行" and it["extra"]["channel"] == "某UP"
    with pytest.raises(RuntimeError):
        src.bilibili_ranking(C(), "knowledge", ["https://bad"], days=0)


def test_trending_and_ranking_judged_and_labeled():
    tr = {"id": "youtube:t", "source": "youtube", "type": "video", "title": "How GPUs work", "summary": "",
          "url": "https://www.youtube.com/watch?v=ttttttttttt", "date": "2026-11-01T00:00:00+00:00", "popularity": 1000,
          "extra": {"via": "trending", "rank": 3, "board": "YouTube 科技热门", "judge_value": 0.8}}
    bl = {**tr, "id": "bilibili:b", "source": "bilibili", "url": "https://www.bilibili.com/video/BV1xx411c7mD",
          "extra": {"via": "ranking", "rank": 1, "board": "B 站知识区排行", "judge_value": 0.2}}
    assert rk.needs_value(tr) and rk.needs_value(bl) and not rk.needs_value({**bl, "extra": {"via": "rsshub"}})
    [x] = rk.rank([tr, bl], now=NOW)     # B 站那条判为没价值，被滤掉
    assert x["id"] == "youtube:t" and "YouTube 科技热门 #3" in x["why"]


@pytest.mark.parametrize("title,ok", [
    ("【漫士】这可能是人类提出最深刻的数学/计算机问题", True), ("How GPUs work", True), ("大模型是怎么推理的", True),
    ("iPhone Duo Durability: Destroyed", False), ("美国中期选举大斗法", False), ("酒店现在退房为什么不查房了", False),
])
def test_tech_topic_prefilter(title, ok):
    assert src.tech_topic({"title": title, "summary": ""}) is ok
