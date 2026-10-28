"""日报渲染：仿 wechat-chat-summary 的视觉风格输出 HTML，可选导出 PNG。

版式要点（参考 wzj042/wechat-auto-insight）：
- 页面米白→浅绿渐变，顶部绿→黄渐变头图横幅；
- 一级顺序固定：今日总览 → 今日速览 → 今日主要话题 → AI 今日观察 → 今日活跃情况 → 报告结尾；
- 话题用"圆形序号 + 标题 + 时间范围 + 正文 + 引用块"结构。
所有聊天内容经 html.escape 转义，防注入。
"""

from __future__ import annotations

import html
from pathlib import Path
from typing import Any

PAGE_CSS = """
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  width: 760px; margin: 0 auto; padding: 0 0 48px;
  font-family: "Microsoft YaHei", "PingFang SC", sans-serif;
  background: linear-gradient(180deg, #faf6ec 0%, #eef6e8 60%, #e4f2e2 100%);
  color: #33342e; line-height: 1.75;
}
.banner {
  height: 150px; border-radius: 0 0 24px 24px;
  background: linear-gradient(120deg, #7fb069 0%, #a9c97a 55%, #e8d264 100%);
  display: flex; flex-direction: column; justify-content: center; align-items: center;
  color: #fff; text-shadow: 0 1px 3px rgba(0,0,0,.25);
}
.banner h1 { font-size: 26px; letter-spacing: 2px; }
.banner p { font-size: 14px; opacity: .95; margin-top: 6px; }
section { margin: 28px 24px 0; }
h2 {
  font-size: 19px; color: #3e6b35; margin-bottom: 14px;
  padding-left: 12px; border-left: 5px solid #7fb069;
}
.summary-box, .closing-box {
  background: rgba(255,255,255,.75); border-radius: 14px; padding: 18px 20px;
  box-shadow: 0 2px 8px rgba(90,120,80,.10);
}
.highlights li { margin: 8px 0 8px 20px; }
.topic { margin-bottom: 22px; }
.topic-head { display: flex; align-items: center; margin-bottom: 8px; }
.topic-index {
  flex: 0 0 30px; width: 30px; height: 30px; border-radius: 50%;
  background: #7fb069; color: #fff; font-size: 15px;
  display: flex; align-items: center; justify-content: center; margin-right: 12px;
}
.topic-title { font-size: 16.5px; font-weight: 700; color: #2f4a2a; }
.topic-time { font-size: 12.5px; color: #8a9a7d; margin: 2px 0 8px 42px; }
.topic-body { margin-left: 42px; }
.topic-body p { margin: 6px 0; font-size: 14.5px; }
.quote {
  margin: 10px 0; padding: 10px 14px; border-radius: 10px;
  background: rgba(127,176,105,.12); font-size: 13.5px; color: #4a5c40;
}
.quote .who { font-weight: 700; color: #2f6fbd; }
.quote .when { color: #93a184; margin-left: 8px; font-size: 12.5px; }
.observations li { margin: 8px 0 8px 20px; }
.stats-grid { display: flex; gap: 12px; margin-bottom: 14px; }
.stat-card {
  flex: 1; background: rgba(255,255,255,.75); border-radius: 12px;
  padding: 14px; text-align: center; box-shadow: 0 2px 8px rgba(90,120,80,.08);
}
.stat-card .num { font-size: 24px; font-weight: 700; color: #3e6b35; }
.stat-card .label { font-size: 12.5px; color: #8a9a7d; margin-top: 4px; }
.sender-row { font-size: 14px; margin: 4px 0; }
.sender-row .bar {
  display: inline-block; height: 10px; border-radius: 5px;
  background: linear-gradient(90deg, #7fb069, #a9c97a); vertical-align: middle;
}
.sender-row .name { color: #2f6fbd; font-weight: 700; }
.footer { text-align: center; color: #9aa88c; font-size: 12px; margin-top: 36px; }
"""


def _e(value: Any) -> str:
    return html.escape(str(value if value is not None else ""))


def _quotes_html(quotes: list[Any]) -> str:
    blocks = []
    for quote in quotes or []:
        if not isinstance(quote, dict):
            continue
        blocks.append(
            '<div class="quote">'
            f'<span class="who">{_e(quote.get("sender"))}</span>'
            f'<span class="when">{_e(quote.get("time"))}</span>'
            f'<div>{_e(quote.get("text"))}</div>'
            "</div>"
        )
    return "".join(blocks)


def render_html(report: dict[str, Any]) -> str:
    chat_name = _e(report.get("chat_name"))
    date = _e(report.get("date"))

    highlights = "".join(
        f"<li>{_e(item)}</li>" for item in report.get("highlights") or []
    )

    topics_html = []
    for index, topic in enumerate(report.get("topics") or [], start=1):
        if not isinstance(topic, dict):
            continue
        time_ranges = "、".join(str(item) for item in topic.get("time_ranges") or [])
        paragraphs = "".join(
            f"<p>{_e(seg)}</p>"
            for seg in str(topic.get("discussion") or "").split("\n")
            if seg.strip()
        )
        topics_html.append(
            '<div class="topic">'
            '<div class="topic-head">'
            f'<div class="topic-index">{index}</div>'
            f'<div class="topic-title">{_e(topic.get("title"))}</div>'
            "</div>"
            f'<div class="topic-time">{html.escape(time_ranges)}</div>'
            f'<div class="topic-body">{paragraphs}{_quotes_html(topic.get("quotes"))}</div>'
            "</div>"
        )

    observations = "".join(
        f"<li>{_e(item)}</li>" for item in report.get("observations") or []
    )

    activity = report.get("activity") or {}
    top_senders = activity.get("top_senders") or []
    max_count = max((int(item.get("count", 0)) for item in top_senders), default=1)
    sender_rows = "".join(
        '<div class="sender-row">'
        f'<span class="name">{_e(item.get("sender"))}</span> '
        f'<span class="bar" style="width:{max(4, int(item.get("count", 0)) / max_count * 180):.0f}px"></span> '
        f'{int(item.get("count", 0))} 条</div>'
        for item in top_senders[:10]
        if isinstance(item, dict)
    )
    type_counts = activity.get("type_counts") or {}
    type_summary = "、".join(
        f"{_e(kind)} {count}" for kind, count in sorted(
            type_counts.items(), key=lambda kv: kv[1], reverse=True
        )
    )

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>{chat_name} {date} 群聊总结</title>
<style>{PAGE_CSS}</style>
</head>
<body>
<div class="banner">
  <h1>{chat_name} · 群聊日报</h1>
  <p>{date}</p>
</div>

<section>
  <h2>今日总览</h2>
  <div class="summary-box">{_e(report.get("summary"))}</div>
</section>

<section>
  <h2>今日速览</h2>
  <ul class="highlights">{highlights}</ul>
</section>

<section>
  <h2>今日主要话题</h2>
  {''.join(topics_html)}
</section>

<section>
  <h2>AI 今日观察</h2>
  <ul class="observations">{observations}</ul>
</section>

<section>
  <h2>今日活跃情况</h2>
  <div class="stats-grid">
    <div class="stat-card"><div class="num">{int(activity.get("message_count", 0))}</div><div class="label">总消息数</div></div>
    <div class="stat-card"><div class="num">{int(activity.get("participant_count", 0))}</div><div class="label">参与人数</div></div>
  </div>
  <div class="sender-row" style="color:#8a9a7d">{type_summary}</div>
  {sender_rows}
</section>

<section>
  <h2>报告结尾</h2>
  <div class="closing-box">{_e(report.get("closing"))}</div>
</section>

<div class="footer">由 WeChat Agent 生成 · 数据来自本地聊天快照</div>
</body>
</html>
"""


def export_png(html_path: Path, png_path: Path) -> bool:
    """Playwright 整页截图导出 PNG。未安装 playwright 时返回 False（HTML 不受影响）。"""

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return False
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 760, "height": 1000})
        page.goto(html_path.resolve().as_uri())
        page.wait_for_timeout(500)
        page.screenshot(path=str(png_path), full_page=True)
        browser.close()
    return True
