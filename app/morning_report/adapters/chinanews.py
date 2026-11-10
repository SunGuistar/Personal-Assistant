"""中新网按日归档接入（国际栏目 + 涉外时政栏目，V0.6 §4.1）。

- 归档页 scroll-news/YYYY/MMDD/news.shtml，分钟级时间戳；跨两个自然日抓取后本地过滤窗口。
- 分类：国际/东盟栏目 → international；时政栏目且标题命中涉外关键词 → international；其余 domestic。
- HTML 解析非正式 API 契约：结构变化需告警（pipeline 记录解析条数异常）。
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
