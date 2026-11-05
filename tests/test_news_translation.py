"""资讯中文翻译单元测试（隔离临时库 + FakeLLM，零真实外网/零真实 Token）。

覆盖需求三：批量一次调用、仅 TOP 10 未翻译项入队、中文资讯免翻译、
无摘要不编造、失败回退原文且不再自动重试、token_usage 成本记录。
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine

from alembic import command
from alembic.config import Config

from app.adapters.news_common import RawNewsItem
from app.models import NewsItem, NewsSource, TokenUsage
from app.services import news_service, news_translation

NOW = datetime(2026, 11, 10, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture()
def session(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'news.db'}"
    import os
    from pathlib import Path

    os.environ["PH_DATABASE_URL"] = db_url
    command.upgrade(Config(str(Path(__file__).resolve().parent.parent / "alembic.ini")), "head")
    engine = create_engine(db_url)
    factory = sessionmaker(bind=engine)
    with factory() as s:
        yield s
    engine.dispose()


class FakeLLM:
    """批量翻译 FakeLLM：输出与输入一一对应的 JSON 数组；可注入失败。"""

    model_name = "fake-translate"

    def __init__(self, fail: bool = False):
        self.calls = 0
        self.fail = fail
        self.last_prompt = ""

    def invoke(self, prompt):
        self.calls += 1
        self.last_prompt = prompt

        class _Resp:
            def __init__(self, content):
                self.content = content
                self.usage_metadata = {"input_tokens": 10, "output_tokens": 20}

        if self.fail:
            return _Resp("garbage")
        match = re.search(r"待翻译资讯（JSON 数组）：\n(\[.*\])", prompt, re.DOTALL)
        items = json.loads(match.group(1))
        results = [
            {
                "title_zh": f"译：{it['title']}",
                "summary_zh": f"译摘要：{it['title']}" if it.get("summary") else "",
            }
            for it in items
        ]
        return _Resp(json.dumps(results, ensure_ascii=False))


def _add_item(session, title, url, summary="Some summary", hours_old=1, source_name="Test"):
    source = session.execute(select(NewsSource).where(NewsSource.name == source_name)).scalars().first()
    if source is None:
        source = NewsSource(name=source_name, kind="rss", endpoint=f"https://{source_name}.example.com/feed", enabled=1, weight=1.0)
        session.add(source)
        session.commit()
        session.refresh(source)
    raw = RawNewsItem(
        title=title,
        url=url,
        published_at=NOW - timedelta(hours=hours_old),
        raw_summary=summary,
        heat_raw=0.0,
    )
    news_service.upsert_items(session, source, [raw])
    return session.execute(select(NewsItem).where(NewsItem.url == url)).scalar_one()


def test_batch_translate_top10_once_and_cache(session):
    # 12 条入缓存（分布在 4 个来源，绕开单来源上榜上限 4），仅 TOP 10 进入翻译队列
    for i in range(12):
        _add_item(session, f"English news {i}", f"https://example.com/{i}", source_name=f"S{i % 4}")
    fake = FakeLLM()

    result = news_translation.translate_pending(session, llm=fake)
    assert result["translated"] == 10
    assert fake.calls == 1  # 批量一次 API 调用

    # 结果落库复用：重复执行零 LLM 调用（刷新/打开页面不重复翻译）
    again = news_translation.translate_pending(session, llm=fake)
    assert again == {"translated": 0, "skipped_chinese": 0, "failed": 0}
    assert fake.calls == 1

    # 榜单输出携带中文缓存
    top = news_service.top_items(session)
    assert all(item["title_zh"].startswith("译：") for item in top["items"])
    assert all(item["translate_status"] == "done" for item in top["items"])

    # 成本落 token_usage
    usage = session.execute(select(TokenUsage).where(TokenUsage.kind == "llm")).scalars().all()
    assert len(usage) == 1
    assert usage[0].ref.startswith("news.translate")
    assert usage[0].input_tokens == 10 and usage[0].output_tokens == 20


def test_chinese_item_not_translated(session):
    item = _add_item(session, "阮一峰：科技爱好者周刊", "https://example.com/zh", summary="中文摘要")
    fake = FakeLLM()
    result = news_translation.translate_pending(session, llm=fake)
    assert result["skipped_chinese"] == 1
    assert fake.calls == 0  # 已是中文：不调 LLM
    session.refresh(item)
    assert item.title_zh == item.title
    assert item.summary_zh == "中文摘要"
    assert item.translate_status == "done"


def test_no_summary_not_invented(session):
    item = _add_item(session, "Release v2.0", "https://example.com/release", summary="")
    fake = FakeLLM()
    news_translation.translate_pending(session, llm=fake)
    session.refresh(item)
    assert item.title_zh.startswith("译：")
    assert item.summary_zh == ""  # 无摘要：不得凭标题编造
    assert item.translate_status == "done"


def test_translate_failure_falls_back_and_no_retry(session):
    item = _add_item(session, "Breaking news", "https://example.com/break")
    fake = FakeLLM(fail=True)
    result = news_translation.translate_pending(session, llm=fake)
    assert result["failed"] == 1
    session.refresh(item)
    assert item.translate_status == "failed"
    assert item.title_zh == ""  # 回退原文由前端处理

    # 失败条目不再自动重试（不每隔刷新周期重复调用）
    retry = news_translation.translate_pending(session, llm=FakeLLM())
    assert retry["translated"] == 0 and retry["failed"] == 0


def test_prompt_requires_terms_and_no_fabrication(session):
    _add_item(session, "LangGraph and MCP support", "https://example.com/terms", summary="About Python tools")
    fake = FakeLLM()
    news_translation.translate_pending(session, llm=fake)
    assert "LangGraph" in fake.last_prompt
    assert "不得凭标题编造" in fake.last_prompt
