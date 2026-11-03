"""理财板块的行情数据源：Yahoo chart（日线 / 小时线 + 最新价）、Google News RSS、yfinance 估值与业绩超预期。

都是无密钥的公开接口；yfinance 是可选依赖（没装就跳过估值背景，不影响概率模型）。
"""
from __future__ import annotations

import hashlib
import html
import json
import math
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any


class ProviderError(RuntimeError):
    pass


def get_bytes(url: str, timeout: float = 15.0, attempts: int = 2, headers: dict[str, str] | None = None) -> bytes:
    request_headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 self-startup-wealth/0.1",
        "Accept": "application/json, application/xml, text/xml, */*",
        **(headers or {}),
    }
    request = urllib.request.Request(url, headers=request_headers)
    last_error: Exception | None = None
    for attempt in range(max(1, attempts)):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read()
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(0.4 * (attempt + 1))
    raise ProviderError(f"request failed after {attempts} attempt(s): {url}: {last_error}")


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def chart(symbol: str, history_range: str = "2y", interval: str = "1d") -> dict[str, Any]:
    """K 线和最新价。返回 {bars: [{ts, open, high, low, close, adj_close, volume}], quote: {...}}。"""
    params = urllib.parse.urlencode({"range": history_range, "interval": interval, "includePrePost": "true", "events": "div,splits"})
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol, safe='')}?{params}"
    payload = json.loads(get_bytes(url).decode("utf-8")).get("chart", {})
    if payload.get("error"):
        raise ProviderError(f"Yahoo returned an error for {symbol}: {payload['error']}")
    if not payload.get("result"):
        raise ProviderError(f"Yahoo returned no data for {symbol}")
    result = payload["result"][0]
    meta = result.get("meta", {})
    q = ((result.get("indicators") or {}).get("quote") or [{}])[0]
    adjusted = ((result.get("indicators") or {}).get("adjclose") or [{}])[0].get("adjclose") or []

    def at(values: Any, i: int) -> float | None:
        return _number(values[i]) if values and i < len(values) else None

    bars = []
    for i, ts in enumerate(result.get("timestamp") or []):
        close = at(q.get("close"), i)
        if close is None:
            continue
        bars.append({"ts": int(ts), "open": at(q.get("open"), i), "high": at(q.get("high"), i), "low": at(q.get("low"), i),
                     "close": close, "adj_close": at(adjusted, i) or close, "volume": at(q.get("volume"), i)})
    market_time = meta.get("regularMarketTime")
    observed = (datetime.fromtimestamp(int(market_time), UTC) if market_time else datetime.now(UTC)).isoformat(timespec="seconds")
    price = _number(meta.get("regularMarketPrice"))
    if price is None and bars:
        price = bars[-1]["close"]
    previous = _previous_close([b["close"] for b in bars], price)
    return {"bars": bars, "quote": {
        "observed_at": observed, "price": price, "previous_close": previous,
        "change_pct": (price / previous - 1) * 100 if price is not None and previous else None,
        "volume": _number(meta.get("regularMarketVolume")), "market_state": str(meta.get("marketState") or "UNKNOWN"),
        "currency": str(meta.get("currency") or ""), "retrieved_at": datetime.now(UTC).isoformat(timespec="seconds")}}


def _previous_close(closes: list[float], price: float | None) -> float | None:
    """上一个完整交易日的收盘价（不用 Yahoo 的 chartPreviousClose，那是整个区间起点的）。"""
    if not closes:
        return None
    if len(closes) == 1:
        return closes[0]
    if price is not None and math.isclose(closes[-1], price, rel_tol=0.0005, abs_tol=0.0001):
        return closes[-2]
    return closes[-1]


def news(query: str, locale: str = "en-US", limit: int = 30) -> list[dict[str, Any]]:
    """Google News RSS 搜索结果，按「去掉来源后缀的标题 + 来源」去重。"""
    language, country = (locale.split("-", 1)[0], locale.split("-", 1)[1].upper()) if "-" in locale else (locale, "US")
    params = urllib.parse.urlencode({"q": query, "hl": locale, "gl": country, "ceid": f"{country}:{language}"})
    root = ET.fromstring(get_bytes(f"https://news.google.com/rss/search?{params}"))
    retrieved = datetime.now(UTC).isoformat(timespec="seconds")
    items = []
    for raw in root.findall("./channel/item")[:limit]:
        title = html.unescape((raw.findtext("title") or "").strip())
        link = (raw.findtext("link") or "").strip()
        node = raw.find("source")
        source = (node.text or "Google News").strip() if node is not None else "Google News"
        if not (title and link):
            continue
        normalized = re.sub(r"\W+", " ", re.sub(r"\s+-\s+[^-]{2,80}$", "", title).lower(), flags=re.UNICODE).strip()
        items.append({"hash": hashlib.sha256(f"{normalized}|{source}".encode("utf-8")).hexdigest(), "title": title, "url": link,
                      "source": source, "published_at": _published(raw.findtext("pubDate")), "retrieved_at": retrieved})
    return items


def _published(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
        return (parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)).astimezone(UTC).isoformat(timespec="seconds")
    except (TypeError, ValueError, OverflowError):
        return None


def research(symbol: str) -> dict[str, Any]:
    """yfinance 估值（forward / trailing PE）和最近几个季度的 EPS 超预期，只取目标计划理由里用到的字段。

    返回 {"profile": {...} | None, "estimates": {...} | None}；yfinance 没装或没覆盖时对应项为 None。
    """
    try:
        import yfinance as yf
    except ImportError:
        return {"profile": None, "estimates": None}
    ticker = yf.Ticker(symbol)
    out: dict[str, Any] = {"profile": None, "estimates": None}
    try:
        info = ticker.info or {}
        if info.get("trailingPE") or info.get("forwardPE"):
            out["profile"] = {"valuation": {k: _number(info.get(k)) for k in ("trailingPE", "forwardPE", "priceToBook", "marketCap")}}
    except Exception:
        pass
    try:
        frame = ticker.earnings_dates
        surprises = []
        if frame is not None and not getattr(frame, "empty", True):
            for stamp, row in frame.iterrows():
                actual = _number(row.get("Reported EPS"))
                if actual is not None:
                    surprises.append({"date": stamp.date().isoformat() if hasattr(stamp, "date") else str(stamp)[:10],
                                      "estimate": _number(row.get("EPS Estimate")), "actual": actual,
                                      "surprise_pct": _number(row.get("Surprise(%)"))})
        if surprises:
            out["estimates"] = {"surprises": sorted(surprises, key=lambda r: r["date"])[-12:]}
    except Exception:
        pass
    return out


class LiveFeed:
    """yfinance 的 Yahoo WebSocket 实时报价，只存在内存里（定时刷新的报价仍是记录）。断线指数退避重连。"""

    def __init__(self, symbols: list[str]):
        try:
            import yfinance as yf
        except ImportError:
            yf = None
        self._yf = yf
        self.symbols = sorted(set(symbols))
        self._quotes: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._socket = None
        self._thread: threading.Thread | None = None
        self.connected = False
        self.last_error = ""

    def start(self) -> None:
        if self._yf is None or self._thread:
            return
        self._thread = threading.Thread(target=self._run, name="wealth-live", daemon=True)
        self._thread.start()

    def quote(self, symbol: str) -> dict[str, Any] | None:
        with self._lock:
            return self._quotes.get(symbol)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            quotes = dict(self._quotes)
        return {"connected": self.connected, "symbols": len(self.symbols), "quotes": quotes, "error": self.last_error,
                "updated_at": max((q["time"] for q in quotes.values() if q.get("time")), default=None)}

    def handle(self, message: dict[str, Any]) -> None:
        symbol, price = message.get("id"), _number(message.get("price"))
        if not symbol or price is None:
            return
        millis = _number(message.get("time"))
        quote = {"price": price, "change_pct": _number(message.get("change_percent")), "market_hours": message.get("market_hours"),
                 "time": datetime.fromtimestamp(millis / 1000, UTC).isoformat(timespec="seconds") if millis else None}
        with self._lock:
            self._quotes[str(symbol)] = quote

    def _run(self) -> None:
        backoff = 2.0
        while not self._stop.is_set():
            try:
                self._socket = self._yf.WebSocket(verbose=False)
                self._socket.subscribe(self.symbols)
                self.connected, self.last_error, backoff = True, "", 2.0
                self._socket.listen(self.handle)  # 阻塞到连接断开
            except Exception as exc:  # noqa: BLE001 —— 一直重连，原因显示在状态里
                self.last_error = f"{type(exc).__name__}: {exc}"
            finally:
                self.connected = False
            if self._stop.wait(backoff):
                break
            backoff = min(backoff * 2, 60.0)
