"""中新网精选补充：仅从首页、时政/国际频道提取有界候选并补采详情。

每类最多保存 5 条，详情请求上限每类 15 条；旧归档解析不再用于生产采集。
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone

from . import NewsCandidate
from .http_common import fetch_text

logger = logging.getLogger(__name__)

CST = timezone(timedelta(hours=8))

LI_RE = re.compile(
    r'<div class="dd_lm">\[<a[^>]*>(?P<cat>[^<]*)</a>\]</div>\s*<div class="dd_bt">'
    r'<a[^>]*href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a></div>'
    r'<div class="dd_time">(?P<time>\d{1,2}-\d{1,2}\s+\d{2}:\d{2})</div>',
    re.S,
)

# 时政栏中与国际有关的标题信号（V0.6：涉外时政纳入国际候选）
INTL_KEYWORDS = (
    "美国", "美", "俄罗斯", "俄", "乌克兰", "伊朗", "以色列", "巴勒斯坦", "叙利亚",
    "特朗普", "拜登", "普京", "欧盟", "欧洲", "北约", "联合国", "阿富汗", "朝鲜",
    "日本", "韩国", "印度", "东盟", "APEC", "世卫", "美联储", "原油", "油价", "美元",
    "中东", "加沙", "胡塞", "台海", "外交部", "中方",
)
INTL_COLUMNS = {"国际", "东盟"}


def classify(category: str, title: str) -> str:
    if category in INTL_COLUMNS:
        return "international"
    if category == "时政" and any(k in title for k in INTL_KEYWORDS):
        return "international"
    return "domestic"


def parse_archive(html: str, page_date: str) -> list[NewsCandidate]:
    """解析单个归档页；page_date=YYYY/MM/DD（用于确定年份）。"""

    year = int(page_date.split("/")[0])
    out: list[NewsCandidate] = []
    for m in LI_RE.finditer(html):
        cat = m.group("cat").strip()
        mmdd, hhmm = m.group("time").split()
        mo, dd = (int(x) for x in mmdd.split("-"))
        hh, mi = (int(x) for x in hhmm.split(":"))
        dt = datetime(year, mo, dd, hh, mi, tzinfo=CST)
        href = m.group("href")
        if href.startswith("/"):
            href = "https://www.chinanews.com.cn" + href
        title = re.sub(r"<[^>]+>", "", m.group("title")).strip()
        out.append(NewsCandidate(
            category=classify(cat, title),
            title=title,
            summary="",
            source_name="中国新闻网",
            source_url=href,
            published_at=dt.isoformat(),
            adapter="chinanews",
            raw={"column": cat},
        ))
    return out


def fetch_window(prev_date: str, curr_date: str) -> list[NewsCandidate]:
    """抓取两天归档页（prev/curr 均为 YYYY-MM-DD）。"""

    out: list[NewsCandidate] = []
    for day in (prev_date, curr_date):
        y, mo, d = day.split("-")
        url = f"https://www.chinanews.com.cn/scroll-news/{y}/{mo}{d}/news.shtml"
        out.extend(parse_archive(fetch_text(url), f"{y}/{mo}/{d}"))
    return out


# 新采集入口只访问精选页；旧归档解析保留供历史兼容，不再进入生产采集。
FEATURED_PAGES = ("https://www.chinanews.com/", "https://www.chinanews.com.cn/china/",
                  "https://www.chinanews.com.cn/world/")


def parse_featured(html: str, page_url: str) -> list[NewsCandidate]:
    from html.parser import HTMLParser
    from urllib.parse import urljoin, urlparse

    class Links(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.href = None
            self.text = []
            self.out = []
        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if tag == "a":
                self.href = attrs.get("href")
                self.text = []
        def handle_data(self, text):
            if self.href:
                self.text.append(text)
        def handle_endtag(self, tag):
            if tag == "a" and self.href:
                self.out.append((urljoin(page_url, self.href), "".join(self.text).strip()))
                self.href = None
    parser = Links()
    parser.feed(html)
    seen = set()
    out = []
    for url, title in parser.out:
        parsed = urlparse(url)
        match = re.fullmatch(r"/(gn|gj|cj|sh)/20\d{2}/\d{2}-\d{2}/\d+\.shtml", parsed.path)
        if not match or not title or parsed.hostname not in ("www.chinanews.com.cn", "www.chinanews.com"):
            continue
        url = "https://www.chinanews.com.cn" + parsed.path
        if url in seen:
            continue
        seen.add(url)
        category = "international" if match[1] == "gj" else classify("时政" if match[1] == "gn" else "", title)
        out.append(NewsCandidate(category=category, title=title, summary="",
            source_name="中国新闻网", source_url=url, published_at=None, adapter="chinanews",
            raw={"selection_kind": "featured", "featured_page": page_url}))
    return out


def fetch_featured(window_start: str, window_end: str, cancel_check=None) -> list[NewsCandidate]:
    from .article import fetch_article
    from .http_common import FetchError

    start, end = datetime.fromisoformat(window_start), datetime.fromisoformat(window_end)
    pools = {"domestic": [], "international": []}
    seen = set()
    failures = []
    successful_pages = 0
    for page in FEATURED_PAGES:
        if cancel_check:
            cancel_check()
        try:
            entries = parse_featured(fetch_text(page), page)
            if not entries:
                raise FetchError(page, "精选页面没有可解析条目")
            successful_pages += 1
        except FetchError:
            failures.append(page)
            continue
        for entry in entries:
            # URL 仅用于提前跳过明显无关日期，不能当作发布时间。
            day_match = re.search(r"/(20\d{2})/(\d{2}-\d{2})/", entry.source_url)
            day = f"{day_match[1]}-{day_match[2]}"
            if not start.date().isoformat() <= day <= end.date().isoformat():
                continue
            if entry.source_url not in seen and len(pools[entry.category]) < 15:
                seen.add(entry.source_url)
                pools[entry.category].append(entry)
    if not successful_pages:
        raise FetchError(FEATURED_PAGES[0], "中新网精选入口全部不可用")
    out = []
    for category, pool in pools.items():
        saved = 0
        for entry in pool:
            if cancel_check:
                cancel_check()
            if saved >= 5:
                break
            try:
                detail = fetch_article(entry.source_url)
                entry.published_at = detail["published_at"]
                entry.summary = detail["summary"]
                entry.raw["time_source"] = "article_page" if entry.published_at else "unknown"
            except FetchError:
                entry.raw["detail_status"] = "failed"
            if entry.published_at and not start <= datetime.fromisoformat(entry.published_at) < end:
                continue
            if not entry.published_at:
                entry.raw["time_confidence"] = "unknown"
            entry.raw["featured_page_failures"] = len(failures)
            out.append(entry)
            saved += 1
    return out
