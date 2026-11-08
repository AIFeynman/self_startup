"""视野板块取数：每个来源一个适配器，输入指标配置，输出 [(period, value)]。

period 统一写法：年 YYYY、季 YYYY-Qn、月 YYYY-MM、日 YYYY-MM-DD。
同一轮里多个指标共用的下载（Epoch 压缩包、Indeed 表、OpenRouter 列表）放在 cache 里，只下一次。
"""
from __future__ import annotations

import csv
import io
import re
import statistics
import time
import zipfile
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

import httpx

# Wikimedia 要求 UA 带联系方式，写项目地址；不能带用户邮箱
UA = "self-startup-vision/0.1 (https://github.com/AIFeynman/self_startup) python-httpx"
TIMEOUT = httpx.Timeout(60.0, connect=15.0)
EPOCH = "https://epoch.ai/data"


def _get(url: str, **kw) -> httpx.Response:
    for i in range(3):
        try:
            r = httpx.get(url, headers={"User-Agent": UA}, timeout=TIMEOUT, follow_redirects=True, **kw)
            r.raise_for_status()
            return r
        except httpx.TransportError:
            if i == 2:
                raise
            time.sleep(3 * (i + 1))
    raise RuntimeError("unreachable")


def _csv(text: str) -> list[dict]:
    return list(csv.DictReader(io.StringIO(text)))


def _num(v) -> float | None:
    try:
        f = float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    return None if f != f else f


def _month(d: str) -> str:
    return d[:7]


def _cached(cache: dict, key: str, fn):
    if key not in cache:
        cache[key] = fn()
    return cache[key]


def _monthly_running_max(rows: list[tuple[str, float]]) -> list[tuple[str, float]]:
    """按发布日期取「截至每个月的最高分」，从第一个月连续到最后一次发布，中间没发新模型的月份沿用上月。"""
    best: dict[str, float] = {}
    for d, v in rows:
        m = _month(d)
        best[m] = max(best.get(m, v), v)
    if not best:
        return []
    out, cur, m, end = [], None, min(best), max(best)
    while m <= end:
        if m in best:
            cur = best[m] if cur is None else max(cur, best[m])
        out.append((m, cur))
        y, mo = int(m[:4]), int(m[5:])
        m = f"{y + (mo == 12)}-{mo % 12 + 1:02d}"
    return out


# ---------- Epoch AI ----------

def _epoch_zip(cache: dict) -> zipfile.ZipFile:
    return _cached(cache, "epoch_zip", lambda: zipfile.ZipFile(io.BytesIO(_get(f"{EPOCH}/benchmark_data.zip").content)))


def _zip_csv(z: zipfile.ZipFile, name: str) -> list[dict]:
    path = next(n for n in z.namelist() if n.endswith("/" + name) or n == name)
    return _csv(z.read(path).decode("utf-8-sig"))


def epoch_eci(cfg: dict, cache: dict) -> list[tuple[str, float]]:
    rows = _cached(cache, "eci", lambda: _zip_csv(_epoch_zip(cache), "eci_scores.csv"))

    def series(pred) -> dict[str, float]:
        pts = [(r["date"], v) for r in rows if (v := _num(r.get("eci"))) is not None and r.get("date") and pred(r)]
        return dict(_monthly_running_max(pts))

    closed = lambda r: r.get("Accessibility group", "").startswith("Closed")  # noqa: E731
    is_open = lambda r: r.get("Accessibility group") == "Open weights"  # noqa: E731
    country = lambda c: lambda r: c in (r.get("Country (of organization)") or "")  # noqa: E731
    g = cfg["args"]["group"]
    if g in ("closed", "open", "china"):
        s = series({"closed": closed, "open": is_open, "china": country("China")}[g])
        return sorted(s.items())
    a, b = (series(closed), series(is_open)) if g == "gap_open" else (series(country("United States")), series(country("China")))
    return sorted((m, round(a[m] - b[m], 2)) for m in a.keys() & b.keys())


def epoch_bench(cfg: dict, cache: dict) -> list[tuple[str, float]]:
    a = cfg["args"]
    rows = _zip_csv(_epoch_zip(cache), a["file"])
    pts = [(r["Release date"], v * a.get("scale", 1)) for r in rows
           if (v := _num(r.get(a["col"]))) is not None and r.get("Release date")]
    return [(m, round(v, 2)) for m, v in _monthly_running_max(pts)]


def epoch_models(cfg: dict, cache: dict) -> list[tuple[str, float]]:
    rows = _cached(cache, "models", lambda: _csv(_get(f"{EPOCH}/notable_ai_models.csv").text))
    by_year: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        y = (r.get("Publication date") or "")[:4]
        if y.isdigit() and int(y) >= 2000:
            by_year[y].append(_num(r.get("Training compute (FLOP)")) or 0)
    if cfg["args"]["kind"] == "count":
        return sorted((y, float(len(v))) for y, v in by_year.items() if y < str(date.today().year))
    return sorted((y, max(v)) for y, v in by_year.items() if max(v) > 0)


def epoch_dc(cfg: dict, cache: dict) -> list[tuple[str, float]]:
    rows = _cached(cache, "dc", lambda: _csv(_get(f"{EPOCH}/data_centers/data_centers.csv").text))
    total = sum(_num(r.get(cfg["args"]["col"])) or 0 for r in rows)
    return [(date.today().isoformat(), round(total * cfg["args"].get("scale", 1), 1))]


# ---------- 其他海外来源 ----------

def fred(cfg: dict, cache: dict) -> list[tuple[str, float]]:
    a = cfg["args"]
    rows = _csv(_get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={a['id']}").text)
    out = []
    for r in rows:
        d = r.get("observation_date") or r.get("DATE") or ""
        v = _num(r.get(a["id"]))
        if v is not None and d:
            out.append((d if cfg["freq"] == "D" else _month(d), round(v * a.get("scale", 1), 2)))
    return out


def indeed_ai(cfg: dict, cache: dict) -> list[tuple[str, float]]:
    rows = _cached(cache, "indeed", lambda: _csv(
        _get("https://raw.githubusercontent.com/hiring-lab/ai-tracker/main/AI_posting.csv").text))
    return [(r["date"], v) for r in rows if r.get("jobcountry") == cfg["args"]["country"]
            and (v := _num(r.get("AI_share_postings"))) is not None]


def wiki(cfg: dict, cache: dict) -> list[tuple[str, float]]:
    a = cfg["args"]
    end = date.today().replace(day=1) - timedelta(days=1)
    url = ("https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia/all-access/user/"
           f"{a['article']}/monthly/20150701/{end:%Y%m%d}")
    return [(f"{i['timestamp'][:4]}-{i['timestamp'][4:6]}", round(i["views"] * a.get("scale", 1), 2))
            for i in _get(url).json().get("items", [])]


def worldbank(cfg: dict, cache: dict) -> list[tuple[str, float]]:
    a = cfg["args"]
    url = (f"https://api.worldbank.org/v2/country/{a['country']}/indicator/{a['indicator']}"
           f"?format=json&per_page=400&date=1960:{date.today().year}")
    data = _get(url).json()
    rows = data[1] if len(data) > 1 and data[1] else []
    return sorted((r["date"], round(r["value"], 3)) for r in rows if r.get("value") is not None)


def oecd_cli(cfg: dict, cache: dict) -> list[tuple[str, float]]:
    def load():
        url = ("https://sdmx.oecd.org/public/rest/data/OECD.SDD.STES,DSD_STES@DF_CLI/.M.LI...AA...H"
               "?startPeriod=2000-01&format=csvfilewithlabels")
        return _csv(_get(url).text)

    rows = _cached(cache, "oecd_cli", load)
    return sorted((r["TIME_PERIOD"], round(v, 2)) for r in rows
                  if r.get("REF_AREA") == cfg["args"]["country"] and (v := _num(r.get("OBS_VALUE"))) is not None)


def openrouter(cfg: dict, cache: dict) -> list[tuple[str, float]]:
    models = _cached(cache, "openrouter", lambda: _get("https://openrouter.ai/api/v1/models").json()["data"])
    if cfg["args"]["kind"] == "new":
        n: dict[str, int] = defaultdict(int)
        for m in models:
            if m.get("created"):
                n[datetime.fromtimestamp(m["created"], timezone.utc).strftime("%Y-%m")] += 1
        return sorted((k, float(v)) for k, v in n.items() if k < date.today().strftime("%Y-%m"))
    cutoff = time.time() - 90 * 86400
    prices = [p * 1e6 for m in models if (m.get("created") or 0) >= cutoff
              and (p := _num((m.get("pricing") or {}).get("completion"))) and p > 0]
    return [(date.today().isoformat(), round(statistics.median(prices), 3))] if prices else []


# ---------- akshare（国内数据） ----------

def _ak():
    import akshare
    return akshare


def _cn_period(s) -> str:
    """「2026年10月份」「2026.9」「202609」「2026-09-01」→ 2026-09 这类月份。"""
    s = str(s)
    if m := re.match(r"(\d{4})\D*?(\d{1,2})月", s) or re.fullmatch(r"(\d{4})\.(\d{1,2})", s) \
            or re.fullmatch(r"(\d{4})(\d{2})", s) or re.match(r"(\d{4})-(\d{1,2})", s):
        return f"{m[1]}-{int(m[2]):02d}"
    raise ValueError(f"认不出的月份：{s}")


def _df_points(df, period_col: str, value_col: str) -> list[tuple[str, float]]:
    out = {}
    for p, v in zip(df[period_col], df[value_col]):
        if (f := _num(v)) is not None:
            out[_cn_period(p)] = round(f, 3)
    return sorted(out.items())


def ak_pmi(cfg: dict, cache: dict) -> list[tuple[str, float]]:
    return _df_points(_cached(cache, "ak_pmi", lambda: _ak().macro_china_pmi()), "月份", cfg["args"]["col"])


def ak_retail(cfg: dict, cache: dict) -> list[tuple[str, float]]:
    return _df_points(_ak().macro_china_consumer_goods_retail(), "月份", "同比增长")


def ak_xfzxx(cfg: dict, cache: dict) -> list[tuple[str, float]]:
    return _df_points(_ak().macro_china_xfzxx(), "月份", "消费者信心指数-指数值")


def ak_gyzjz(cfg: dict, cache: dict) -> list[tuple[str, float]]:
    return _df_points(_ak().macro_china_gyzjz(), "月份", "同比增长")


def ak_sina(cfg: dict, cache: dict) -> list[tuple[str, float]]:
    a = cfg["args"]
    df = _cached(cache, a["func"], lambda: getattr(_ak(), a["func"])())
    return _df_points(df, "统计时间", a["col"])


def ak_house(cfg: dict, cache: dict) -> list[tuple[str, float]]:
    a = cfg["args"]
    df = _cached(cache, "ak_house", lambda: _ak().macro_china_new_house_price())
    return _df_points(df[df["城市"] == a["city"]], "日期", a["col"])


def ak_unemp(cfg: dict, cache: dict) -> list[tuple[str, float]]:
    df = _cached(cache, "ak_unemp", lambda: _ak().macro_china_urban_unemployment())
    return _df_points(df[df["item"].str.strip() == cfg["args"]["item"]], "date", "value")


def ak_nbs(cfg: dict, cache: dict) -> list[tuple[str, float]]:
    a = cfg["args"]
    df = _ak().macro_china_nbs_nation(kind="年度数据", path=a["path"], period="LAST30")
    row = df.loc[a["row"]] if a["row"] in df.index else df[df.iloc[:, 0] == a["row"]].iloc[0]
    return sorted((m[1], round(f, 3)) for k, v in row.items()
                  if (m := re.fullmatch(r"(\d{4})年", str(k))) and (f := _num(v)) is not None)


def ak_boxoffice(cfg: dict, cache: dict, have: set[str] | None = None, years: int = 8, per_run: int = 30) -> list[tuple[str, float]]:
    """艺恩只给逐月影片榜，加总成月票房（万元 → 亿元）。已入库的月份不重取，只补缺的和最近两个月；
    艺恩经代理常断连，每轮最多取 per_run 个月，断了就带着已取到的返回，下一轮接着补。"""
    today = date.today().replace(day=1)
    months = []
    y, m = today.year - years, today.month
    while (y, m) < (today.year, today.month):
        months.append(f"{y}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    todo = months[-2:] + [p for p in reversed(months[:-2]) if p not in (have or set())]
    out = []
    for p in todo[:per_run]:
        try:
            df = _ak().movie_boxoffice_monthly(p.replace("-", "") + "01")
        except KeyError:  # 艺恩对没有榜单的月份返回空表，akshare 改列名时报 KeyError
            continue
        except Exception:  # noqa: BLE001
            if out:
                break
            raise
        out.append((p, round(float(df["单月票房"].astype(float).sum()) / 10000, 2)))
        time.sleep(1)
    return sorted(out)


ADAPTERS = {f.__name__: f for f in (epoch_eci, epoch_bench, epoch_models, epoch_dc, fred, indeed_ai, wiki, worldbank,
                                    oecd_cli, openrouter, ak_pmi, ak_retail, ak_xfzxx, ak_gyzjz, ak_sina, ak_house,
                                    ak_unemp, ak_nbs, ak_boxoffice)}


def fetch(cfg: dict, cache: dict, have: set[str] | None = None, tries: int = 3) -> list[tuple[str, float]]:
    """akshare 走 requests，经代理时常见 SSL EOF 断连：整次调用退避重试。"""
    fn = ADAPTERS[cfg["source"]]
    for i in range(tries):
        try:
            return fn(cfg, cache, have) if fn is ak_boxoffice else fn(cfg, cache)
        except Exception:  # noqa: BLE001
            if i == tries - 1:
                raise
            time.sleep(5 * (i + 1))
    return []
