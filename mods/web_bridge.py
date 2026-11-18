# -*- coding: utf-8 -*-
"""web_bridge —— 兼容接口（mods/*.py + handle_command）的联网桥。

给 Aster 接三件事，全部不需要 API Key：

1. **新闻**：RSS 聚合（IT之家 / Solidot / 少数派），按发布时间排序取头条；
2. **天气**：wttr.in（JSON），城市名 → 当前天气 + 今日温度；
3. **搜索**：Bing 公开结果页，用清洗过的关键词。

设计约束（重要）：
- 只在自己"确定该出手"时返回字符串，直接作为本轮回答；
- 不确定、或消息里带链接（那是 net_read 的活）时返回 None，把话交回 Aster；
- 永远不编：取不到就说明取不到。
"""

import html as _html
import json
import re
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from email.utils import parsedate_to_datetime

import requests

_CACHE = {}


def _cached(key, ttl, fn):
    """同一问题短时间内只打一次网络：省时间，也少惹人限流。"""
    hit = _CACHE.get(key)
    now = time.time()
    if hit and now - hit[0] < ttl:
        return hit[1]
    val = fn()
    _CACHE[key] = (now, val)
    return val

MOD_NAME = "联网桥"
MOD_VERSION = "0.1.0"
MOD_DESC = "新闻 / 天气 / 搜索：兼容接口接入，结果直接回给 Aster"

UA = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.6",
}
TIMEOUT = (4, 8)

FEEDS = [
    ("IT之家", "https://www.ithome.com/rss/"),
    ("Solidot", "https://www.solidot.org/index.rss"),
    ("少数派", "https://sspai.com/feed"),
]

NEWS_RE = re.compile(r"(新闻|头条|热点|热搜|要闻|大事|发生了什么|最近发生)")
WEATHER_RE = re.compile(r"(天气|气温|降雨|下雨|几度|冷不冷|热不热)")
SEARCH_RE = re.compile(r"(搜一下|搜搜|搜索|查一下|查查|帮我查|查下|搜下)")
URL_RE = re.compile(r"https?://[^\s，。；、）)】>\]]+")

_FILLERS = ("帮我看看", "帮我查查", "帮我搜搜", "帮我查", "帮我搜", "我想知道", "我想问",
            "想知道", "看一下", "看看", "查查", "搜搜", "搜一下", "查一下", "搜索一下",
            "搜索", "请问", "麻烦", "给我", "说一下", "讲一下", "介绍一下", "了解一下",
            "了解", "一下", "现在", "今天")


def get_description():
    return f"{MOD_NAME} v{MOD_VERSION}: {MOD_DESC}"


def on_load():
    # 兼容接口没有 ctx，这里不打印，避免污染对话；加载状态由主体记录
    return True


# ---------------- 入口 ----------------

def handle_command(text):
    """主体每轮都会调用；快速判断该不该我们出手。"""
    text = (text or "").strip()
    if not text or text.startswith("/"):
        return None
    if URL_RE.search(text):
        return None                      # 带链接 → 交给 net_read 读正文
    if WEATHER_RE.search(text):
        return _weather(text)
    if NEWS_RE.search(text):
        return _news()
    if SEARCH_RE.search(text):
        return _search_reply(text)
    return None


# ---------------- 新闻 ----------------

def _fetch_feed(source, url):
    try:
        r = requests.get(url, headers=UA, timeout=TIMEOUT)
        if r.status_code != 200:
            return []
        return _parse_feed(source, r.content)
    except Exception:
        return []


def _parse_feed(source, raw):
    """RSS/Atom → [{title, link, source, time, ts}]，离线可测。"""
    try:
        root = ET.fromstring(raw)
    except Exception:
        return []
    out = []
    for item in root.iter("item"):
        title = _text(item.find("title"))
        link = _text(item.find("link"))
        pub = _text(item.find("pubDate")) or _text(item.find(
            "{http://purl.org/dc/elements/1.1/}date"))
        if not title or not link:
            continue
        out.append({"title": title, "link": link, "source": source,
                    "time": _short_time(pub), "ts": _timestamp(pub)})
    return out


def _text(node):
    return (node.text or "").strip() if node is not None else ""


def _timestamp(pub):
    try:
        return parsedate_to_datetime(pub).timestamp()
    except Exception:
        return 0.0


def _short_time(pub):
    try:
        dt = parsedate_to_datetime(pub)
        return dt.strftime("%m-%d %H:%M")
    except Exception:
        return ""


def _news(limit=8):
    return _cached(("news", limit), 300, lambda: _news_raw(limit))


def _news_raw(limit=8):
    items = []
    try:
        with ThreadPoolExecutor(max_workers=len(FEEDS)) as pool:
            for got in pool.map(lambda f: _fetch_feed(*f), FEEDS):
                items.extend(got)
    except Exception:
        pass
    if not items:
        return "📰 新闻源这次没取到内容（RSS 不通或被限流），稍等再试，或者给我一个具体链接我直接读。"
    # 按来源分组，轮流取头条：避免整屏都是一家站
    by_source = {}
    for it in items:
        by_source.setdefault(it["source"], []).append(it)
    for group in by_source.values():
        group.sort(key=lambda x: x["ts"], reverse=True)
    uniq, seen = [], set()
    while len(uniq) < limit and any(by_source.values()):
        for source in list(by_source):
            group = by_source.get(source) or []
            while group:
                it = group.pop(0)
                key = re.sub(r"\W", "", it["title"])[:18]
                if key in seen:
                    continue
                seen.add(key)
                uniq.append(it)
                break
            if len(uniq) >= limit:
                break
    lines = [f"📰 最新 {min(limit, len(uniq))} 条 · {time.strftime('%m-%d %H:%M')}"]
    for i, it in enumerate(uniq[:limit], 1):
        stamp = f" · {it['time']}" if it["time"] else ""
        lines.append(f"{i}. {it['title']}")
        lines.append(f"   {it['source']}{stamp}")
        lines.append(f"   {it['link']}")
    lines.append("（来源：IT之家 / Solidot / 少数派 RSS，标题照原样，未改写）")
    return "\n".join(lines)


# ---------------- 天气 ----------------

_CITY_FILLERS = tuple(w for w in _FILLERS if w not in ("今天", "现在"))


def _extract_city(text):
    t = _text_only(text)
    for word in _CITY_FILLERS:     # 去掉"帮我看看"这类，但保留"今天/现在"
        t = t.replace(word, " ")
    t = re.sub(r"(?<=[\u4e00-\u9fa5])\s+(?=[\u4e00-\u9fa5])", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    patterns = [
        r"([\u4e00-\u9fa5]{2,8}?)(?:今天|明天|现在|这几天的)?的?天气",
        r"天气(?:怎么样|如何|咋样)?[：:，,\s]*([\u4e00-\u9fa5]{2,8})",
        r"(?:查|看|问)(?:一下|下)?([\u4e00-\u9fa5]{2,8}?)(?:今天|明天|现在)?的?天气",
    ]
    for pat in patterns:
        m = re.search(pat, t)
        if m:
            city = m.group(1).strip("的了在是有")
            if _looks_like_city(city):
                return city
    return ""


_NOT_CITY = ("怎么样", "如何", "咋样", "什么", "多少", "天气", "今天", "明天", "现在",
             "这里", "那边", "外面", "最近", "这几天", "情况", "预报", "温度")


def _looks_like_city(word):
    if not word or len(word) < 2:
        return False
    if word in _NOT_CITY:
        return False
    if re.search(r"(怎么样|如何|咋样|什么|多少|吗|呢|吧)$", word):
        return False
    return bool(re.fullmatch(r"[\u4e00-\u9fa5]{2,8}", word))


DESC_ZH = {
    "Sunny": "晴", "Clear": "晴", "Partly cloudy": "多云", "Cloudy": "多云",
    "Overcast": "阴", "Mist": "薄雾", "Fog": "雾", "Haze": "霾",
    "Patchy rain nearby": "局部有雨", "Patchy rain possible": "可能有雨",
    "Light rain": "小雨", "Moderate rain": "中雨", "Heavy rain": "大雨",
    "Light drizzle": "毛毛雨", "Patchy light drizzle": "零星毛毛雨",
    "Light rain shower": "小阵雨", "Moderate or heavy rain shower": "中到大阵雨",
    "Patchy light rain": "零星小雨", "Light snow": "小雪", "Moderate snow": "中雪",
    "Heavy snow": "大雪", "Thundery outbreaks possible": "可能有雷阵雨",
}

WEATHER_CODE = {
    0: "晴", 1: "晴间多云", 2: "多云", 3: "阴", 45: "雾", 48: "雾凇",
    51: "小毛毛雨", 53: "毛毛雨", 55: "大毛毛雨", 61: "小雨", 63: "中雨", 65: "大雨",
    71: "小雪", 73: "中雪", 75: "大雪", 80: "阵雨", 81: "强阵雨", 82: "暴雨",
    95: "雷阵雨", 96: "雷阵雨伴冰雹", 99: "强雷暴",
}


def _weather(text):
    city = _extract_city(text)
    if not city:
        return "🌤 想知道哪里的天气？我这边不知道你在哪儿——把城市名带上就行，比如「北京天气」或「查天气：上海」。"
    try:
        r = requests.get(f"https://wttr.in/{city}", params={"format": "j1", "lang": "zh"},
                         headers=UA, timeout=TIMEOUT)
        if r.status_code != 200:
            return f"🌤 {city}：天气服务返回 HTTP {r.status_code}，这次没拿到。"
        data = r.json()
        cur = (data.get("current_condition") or [{}])[0]
        today = (data.get("weather") or [{}])[0]
        area = ((data.get("nearest_area") or [{}])[0].get("areaName") or [{}])[0].get("value") or city
    except Exception as e:
        return f"🌤 {city}：天气没取到（{type(e).__name__}），稍后再试。"

    def desc():
        try:
            raw_desc = cur["weatherDesc"][0]["value"].strip()
        except Exception:
            return "—"
        return DESC_ZH.get(raw_desc, raw_desc)

    lines = [f"🌤 {city} · 现在 {cur.get('temp_C', '?')}°C（体感 {cur.get('FeelsLikeC', '?')}°C）· {desc()}"]
    extra = []
    if cur.get("humidity"):
        extra.append(f"湿度 {cur['humidity']}%")
    if cur.get("windspeedKmph"):
        extra.append(f"风速 {cur['windspeedKmph']} km/h")
    if cur.get("precipMM"):
        extra.append(f"降水 {cur['precipMM']} mm")
    if extra:
        lines.append(" · ".join(extra))
    if today.get("mintempC") and today.get("maxtempC"):
        lines.append(f"今天 {today['mintempC']}°C ~ {today['maxtempC']}°C")
    if today.get("hourly"):
        rain = [h.get("chanceofrain") for h in today["hourly"]]
        try:
            lines.append(f"今天最高降水概率 {max(int(x) for x in rain if x)}%")
        except Exception:
            pass
    lines.append(f"（数据：wttr.in，查询词「{city}」）")
    return "\n".join(lines)


# ---------------- 搜索 ----------------

def _clean_query(text):
    q = _text_only(text)
    for word in _FILLERS:
        q = q.replace(word, " ")
    q = re.sub(r"[？?！!。，,、；;：:]+", " ", q)
    return re.sub(r"\s+", " ", q).strip()[:60]


def _text_only(text):
    return re.sub(r"\s+", " ", (text or "").strip())


def _search_reply(text):
    query = _clean_query(text)
    if len(query) < 2:
        return None
    try:
        rows = _bing(query)
    except Exception as e:
        return f"🔎 搜索「{query}」没成功（{type(e).__name__}），换个说法或给我链接。"
    if not rows:
        return f"🔎 没搜到「{query}」的结果——不是没网，是这次结果页没解析出来。"
    lines = [f"🔎 「{query}」的 {len(rows)} 条结果"]
    for i, r in enumerate(rows, 1):
        lines.append(f"{i}. {r['title']}")
        lines.append(f"   {r['url']}")
        if r.get("snippet"):
            lines.append(f"   {r['snippet'][:160]}")
    lines.append("（来源：Bing 公开结果页，摘要未改写）")
    return "\n".join(lines)


def _bing(query, limit=5):
    return _cached(("bing", query, limit), 300, lambda: _bing_raw(query, limit))


def _bing_raw(query, limit=5):
    r = requests.get("https://cn.bing.com/search",
                     params={"q": query, "setlang": "zh-CN", "mkt": "zh-CN"},
                     headers=UA, timeout=TIMEOUT)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}")
    return _parse_bing(r.text, limit)


def _parse_bing(html_text, limit=5):
    rows, seen = [], set()
    for chunk in re.split(r'class="b_algo"', html_text or "")[1:]:
        m = re.search(r'<h2[^>]*>\s*<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', chunk, re.S)
        if not m:
            continue
        url = m.group(1).strip()
        title = _strip(m.group(2))
        if not title or not url.startswith("http"):
            continue
        snippet = ""
        for sm in re.finditer(r"<p[^>]*>(.*?)</p>", chunk, re.S):
            t = _strip(sm.group(1))
            if len(t) >= 20:
                snippet = t
                break
        key = url.split("?")[0].split("#")[0]
        if key in seen:
            continue
        seen.add(key)
        rows.append({"title": title[:100], "url": url, "snippet": snippet[:200]})
        if len(rows) >= limit:
            break
    return rows


def _strip(s):
    s = re.sub(r"<script.*?</script>", " ", s or "", flags=re.S | re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = _html.unescape(s)
    s = re.sub(r"\s+", " ", s).strip()
    # 中文之间被标签切出来的空格，合并回去
    s = re.sub(r"(?<=[\u4e00-\u9fa5])\s+(?=[\u4e00-\u9fa5])", "", s)
    return s
